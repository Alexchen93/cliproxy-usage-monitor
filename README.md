# CLIProxyAPI Usage Monitor

A local-only Ubuntu GNOME top-bar monitor for a remote CLIProxyAPI instance.

## Architecture

```text
GNOME Shell Extension
  -> http://127.0.0.1:17831
Usage Bridge (systemd --user)
  -> Headscale/private network
CLIProxyAPI Management API
```

The GNOME extension never receives the CLIProxyAPI management key. The bridge refuses non-loopback binds and normalizes upstream data into schema v1.

## Current scope

- GNOME Shell 46 extension
- Codex 5-hour and weekly quota aggregation
- Cached/stale/offline state
- Manual refresh with debounce
- Partial failure handling

Antigravity, notifications, and historical usage collection are later phases.

## Development checks

```bash
cd bridge
python3 -m unittest discover -s tests -v
python3 -m compileall -q cliproxy_usage_bridge
cd ..
node --test extension/tests/format.test.mjs
python3 -m json.tool extension/metadata.json >/dev/null
gnome-extensions pack extension --force --out-dir=/tmp
```

## Desktop paths

- Bridge runtime: `~/.local/share/cliproxy-usage-bridge`
- Bridge config: `~/.config/cliproxy-usage-bridge/config.toml` (mode 0600)
- User service: `~/.config/systemd/user/cliproxy-usage-bridge.service`
- Extension: `~/.local/share/gnome-shell/extensions/cliproxy-usage-monitor@priveate.uk`

The bridge config uses the private endpoint `http://100.64.0.3:8317`. Never commit a real management key.
