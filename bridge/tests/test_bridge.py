from __future__ import annotations

import http.client
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import Mock

from cliproxy_usage_bridge.cliproxy_client import ManagementClient, ManagementError
from cliproxy_usage_bridge.config import Config, load_config, rewrite_source_config
from cliproxy_usage_bridge.models import summary_schema
from cliproxy_usage_bridge.providers.antigravity import collect as collect_antigravity, parse_models
from cliproxy_usage_bridge.providers.codex import collect, parse_usage
from cliproxy_usage_bridge.redaction import redact, safe_error
from cliproxy_usage_bridge.server import handler_for
from cliproxy_usage_bridge.service import SummaryService


CONFIG = Config("http://100.64.0.3:8317", "test-management-key", cache_ttl_seconds=2, stale_after_seconds=4)


class FakeClient:
    auth_blocked = False

    def __init__(self, files, responses):
        self.files = files
        self.responses = iter(responses)
        self.calls = []

    def auth_files(self):
        return self.files

    def api_call(self, *args):
        self.calls.append(args)
        return next(self.responses)


class FakeConfigClient(FakeClient):
    def __init__(self, config):
        super().__init__([], [])
        self.config = config


class BridgeTests(unittest.TestCase):
    def test_codex_payload_schema_and_aggregation(self):
        usage_a = {"rate_limit": {"primary_window": {"limit_window_seconds": 18000, "used_percent": 42, "reset_at": 1760000000}, "secondary_window": {"limit_window_seconds": 604800, "used_percent": 31}}}
        usage_b = {"rateLimit": {"primaryWindow": {"limitWindowSeconds": 18000, "usedPercent": 58}, "secondaryWindow": {"limitWindowSeconds": 604800, "usedPercent": 10}}}
        files = [
            {"provider": "codex", "auth_index": "one", "chatgpt_account_id": "a"},
            {"provider": "codex", "auth_index": "two", "chatgpt_account_id": "b"},
        ]
        client = FakeClient(files, [{"status_code": 200, "body": usage_a}, {"statusCode": 200, "body": json.dumps(usage_b)}])
        provider, errors, online = collect(client)
        self.assertEqual(errors, [])
        self.assertTrue(online)
        self.assertEqual(provider["summary_used_percent"], 58)
        self.assertEqual(provider["windows"]["five_hour"]["remaining_percent"], 42)
        self.assertEqual(provider["windows"]["weekly"]["used_percent"], 31)
        self.assertEqual(len(provider["accounts"]), 2)
        self.assertEqual(provider["accounts"][0]["display_name"], "Account 1")
        self.assertEqual(provider["accounts"][0]["windows"]["five_hour"]["used_percent"], 42)
        self.assertEqual(provider["accounts"][0]["windows"]["weekly"]["used_percent"], 31)
        self.assertEqual(provider["accounts"][1]["windows"]["five_hour"]["used_percent"], 58)
        self.assertEqual(provider["accounts"][1]["windows"]["weekly"]["used_percent"], 10)
        self.assertIn("five_hour", parse_usage(usage_a))

    def test_antigravity_model_quota_aggregation(self):
        payload_a = {
            "models": {
                "gemini-flash": {"displayName": "Gemini Flash", "quotaInfo": {"remainingFraction": 0.72, "resetTime": "2026-09-22T11:21:56Z"}},
                "claude": {"displayName": "Claude", "quotaInfo": {"remainingFraction": 0.40}},
            }
        }
        payload_b = {"models": {"gemini-flash": {"displayName": "Gemini Flash", "quotaInfo": {"remainingFraction": 0.15}}}}
        files = [{"provider": "antigravity", "auth_index": "one"}, {"provider": "antigravity", "auth_index": "two"}]
        client = FakeClient(files, [{"status_code": 200, "body": payload_a}, {"status_code": 200, "body": json.dumps(payload_b)}])
        provider, errors, online = collect_antigravity(client)
        self.assertTrue(online)
        self.assertEqual(errors, [])
        self.assertEqual(provider["accounts_total"], 2)
        self.assertEqual(provider["accounts_available"], 2)
        self.assertEqual(provider["summary_used_percent"], 85)
        self.assertEqual(provider["windows"]["gemini-flash"]["remaining_percent"], 15)
        self.assertEqual(provider["accounts"][0]["windows"]["claude"]["remaining_percent"], 40)
        self.assertEqual(client.calls[0][3], "{}")
        self.assertIn("gemini-flash", parse_models(payload_a))

    def test_nested_id_token_account_and_token_substitution(self):
        usage = {"rate_limit": {"primary_window": {"used_percent": 12}}}
        files = [{"provider": "codex", "auth_index": "one", "id_token": {"chatgpt_account_id": "nested-account"}}]
        client = FakeClient(files, [{"status_code": 200, "body": usage}])
        provider, errors, online = collect(client)
        self.assertTrue(online)
        self.assertEqual(errors, [])
        self.assertEqual(provider["accounts_available"], 1)
        self.assertEqual(client.calls[0][2]["Authorization"], "Bearer $TOKEN$")
        self.assertEqual(client.calls[0][2]["Chatgpt-Account-Id"], "nested-account")

    def test_partial_failure_keeps_successful_account(self):
        files = [{"provider": "codex", "auth_index": "one", "chatgpt_account_id": "a"}, {"provider": "codex", "auth_index": "two", "chatgpt_account_id": "b"}]
        payload = {"rate_limit": {"primary_window": {"used_percent": 20}, "secondary_window": {"used_percent": 40}}}
        provider, errors, online = collect(FakeClient(files, [{"status_code": 200, "body": payload}, {"status_code": 503, "body": {}}]))
        self.assertTrue(online)
        self.assertEqual(provider["accounts_available"], 1)
        self.assertEqual(len(provider["accounts"]), 2)
        self.assertTrue(provider["accounts"][0]["available"])
        self.assertFalse(provider["accounts"][1]["available"])
        self.assertIn("error", provider["accounts"][1])
        self.assertEqual(len(errors), 1)

    def test_cache_states(self):
        payload = {"rate_limit": {"primary_window": {"used_percent": 20}, "secondary_window": {"used_percent": 40}}}
        service = SummaryService(CONFIG, FakeClient([{"provider": "codex", "auth_index": "one", "chatgpt_account_id": "a"}], [{"status_code": 200, "body": payload}]), start_refresh=False)
        service.refresh()
        self.assertEqual(service.get_summary()["cache_state"], "live")
        service._updated_monotonic -= 3
        self.assertEqual(service._decorate_cache_locked()["cache_state"], "cached")
        service._updated_monotonic -= 3
        self.assertEqual(service._decorate_cache_locked()["cache_state"], "stale")

    def test_public_summary_schema(self):
        payload = {"rate_limit": {"primary_window": {"used_percent": 20}, "secondary_window": {"used_percent": 40}}}
        service = SummaryService(CONFIG, FakeClient([{"provider": "codex", "auth_index": "one", "chatgpt_account_id": "a"}], [{"status_code": 200, "body": payload}]), start_refresh=False)
        initial = service.get_summary()
        self.assertTrue(summary_schema(initial))
        self.assertEqual(initial["errors"][0]["message"], "initial refresh in progress")
        service.refresh()
        self.assertTrue(summary_schema(service.get_summary()))

    def test_401_blocks_future_requests(self):
        opener = Mock(side_effect=HTTPError("http://test", 401, "Unauthorized", {}, BytesIO(b"{}")))
        client = ManagementClient(CONFIG, opener=opener)
        with self.assertRaises(ManagementError):
            client.auth_files()
        with self.assertRaises(ManagementError):
            client.auth_files()
        self.assertTrue(client.auth_blocked)
        self.assertEqual(opener.call_count, 1)

    def test_redaction(self):
        result = redact({"management_key": "do-not-leak", "nested": ["Bearer abc.def.ghi"]})
        self.assertEqual(result["management_key"], "[REDACTED]")
        self.assertNotIn("abc.def.ghi", safe_error("Bearer abc.def.ghi"))

    def test_rewrite_source_config_is_atomic_0600_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            key = "old-secret"
            path.write_text(
                'remote_base_url = "http://100.64.0.3:8317"\n'
                f'management_key = "{key}"\n'
                "bind_host = \"127.0.0.1\"\n"
                "bind_port = 17855\n"
                "custom_setting = \"preserved\"\n",
                encoding="utf-8",
            )
            path.chmod(0o600)
            updated = rewrite_source_config(load_config(path), "http://100.64.0.8:8317", "new-secret")
            self.assertEqual(updated.remote_base_url, "http://100.64.0.8:8317")
            self.assertEqual(updated.management_key, "new-secret")
            self.assertEqual(updated.bind_port, 17855)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            contents = path.read_text(encoding="utf-8")
            self.assertIn('custom_setting = "preserved"', contents)
            self.assertIn('management_key = "new-secret"', contents)

    def test_settings_api_hides_key_updates_source_and_rejects_public_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            old_key = "old-secret"
            new_key = "new-secret"
            path.write_text(
                'remote_base_url = "http://100.64.0.3:8317"\n'
                f'management_key = "{old_key}"\n'
                "bind_host = \"127.0.0.1\"\n"
                "bind_port = 17855\n"
                "custom_setting = \"preserved\"\n",
                encoding="utf-8",
            )
            path.chmod(0o600)
            service = SummaryService(load_config(path), start_refresh=False, client_factory=FakeConfigClient)
            service._summary = {"old": "cache"}
            service.client.auth_blocked = True
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                response = self._request(server, "GET", "/api/v1/settings")
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    json.loads(response.body),
                    {
                        "schema_version": 1,
                        "remote_base_url": "http://100.64.0.3:8317",
                        "management_key_configured": True,
                    },
                )
                self.assertNotIn(old_key, response.body)

                response = self._request(
                    server,
                    "POST",
                    "/api/v1/settings",
                    {"remote_base_url": "http://100.64.0.8:8317", "management_key": new_key},
                )
                self.assertEqual(response.status, 202)
                self.assertNotIn("management_key\"", response.body)
                self.assertIn('"management_key_configured":true', response.body)
                self.assertNotIn(old_key, response.body)
                self.assertNotIn(new_key, response.body)
                self.assertEqual(service.client.config.management_key, new_key)
                self.assertFalse(service.client.auth_blocked)
                self.assertEqual(service.config.remote_base_url, "http://100.64.0.8:8317")
                self.assertIn('custom_setting = "preserved"', path.read_text(encoding="utf-8"))
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

                response = self._request(server, "POST", "/api/v1/settings", {"remote_base_url": "http://100.64.0.9:8317", "management_key": ""})
                self.assertEqual(response.status, 202)
                self.assertEqual(service.client.config.management_key, new_key)

                response = self._request(server, "POST", "/api/v1/settings", {"remote_base_url": "http://100.64.0.10:8317"})
                self.assertEqual(response.status, 202)
                self.assertEqual(service.client.config.management_key, new_key)

                response = self._request(server, "POST", "/api/v1/settings", {"remote_base_url": "https://public.example"})
                self.assertEqual(response.status, 400)
                self.assertNotIn(old_key, response.body)
                self.assertNotIn(new_key, response.body)
                self.assertEqual(load_config(path).remote_base_url, "http://100.64.0.10:8317")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    @staticmethod
    def _request(server, method, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            connection.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
            raw_response = connection.getresponse()
            return type("Response", (), {"status": raw_response.status, "body": raw_response.read().decode("utf-8")})
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
