from __future__ import annotations

import json
import unittest
from io import BytesIO
from urllib.error import HTTPError
from dataclasses import replace
from unittest.mock import Mock

from cliproxy_usage_bridge.cliproxy_client import ManagementClient, ManagementError
from cliproxy_usage_bridge.config import Config
from cliproxy_usage_bridge.models import summary_schema
from cliproxy_usage_bridge.providers.codex import collect, parse_usage
from cliproxy_usage_bridge.redaction import redact, safe_error
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


if __name__ == "__main__":
    unittest.main()
