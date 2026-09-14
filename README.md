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
- A local Settings window for the CLIProxyAPI private URL and one-way Management Key replacement

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
- Extension: `~/.local/share/gnome-shell/extensions/cliproxy-usage-monitor-v4@priveate.uk`

The bridge config uses the private endpoint `http://100.64.0.3:8317`. Never commit a real management key.

## Settings and secret handling

Open the monitor popup and choose **Settings…** to edit the private CLIProxyAPI URL. The bridge accepts only literal private, loopback, link-local, or Headscale CGNAT addresses; it refuses public endpoints and never exposes its Management Key through its local API.

For first-time setup or key rotation, enter a Management Key in the Settings window and save. The field is always blank when the window opens. The bridge atomically writes it only to `~/.config/cliproxy-usage-bridge/config.toml` with mode `0600`; blank means keep the existing key.
