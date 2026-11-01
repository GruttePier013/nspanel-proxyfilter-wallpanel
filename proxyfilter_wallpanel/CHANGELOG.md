# Changelog

All notable changes to this add-on. Format based on [Keep a Changelog](https://keepachangelog.com/).

## 2.0.0

First public release of **Proxyfilter for photo/wallpanel**: a filtering proxy that forwards only the traffic a
wall panel, photo frame or other small device running the HA Companion app needs, so weak CPUs stay responsive.

### Added
- **Web UI in the Home Assistant sidebar** (ingress) to complete the configuration: the Configuration tab points to
  it as step 1 ("Start the WEB-UI to complete the configuration").
  - **Dashboard pills**: pick one or more dashboards your wall panel opens; their entities always pass.
  - **Two ways to recognise the panel**: a *dedicated port* (everything on port 8124 is filtered; recommended, no token
    handling) or *by Home Assistant user* (pills; one port serves everybody).
  - Live statistics, exclude editor, throttling and checks.
- **Exclude list editor**: the file is created automatically in the add-on's own config folder, validated on save,
  a `.bak` copy is kept, pasted log lines are converted to patterns, changes apply immediately.
- **Dashboard protection**: entity ids, wildcards (`sensor.air_mini_*`) and the entities of devices/areas used on
  your dashboards always pass, even when an exclude pattern matches them. Overlaps are reported in the UI and log.
- **Check an entity**: shows exactly why an entity passes or is blocked.
- **Clickable lists** behind the *dashboard entities* and *exclude patterns* counters.
- **Throttling**: a card with the busiest entities and a drop-down per entity (max one update per 5/10/30/60 s up
  to 10 min); the latest value is always delivered.
- **Noisiest entities** table and wildcard suggestions with one-click "add to exclude list".
- **Orange warnings** in the log and UI for heavy dashboard entities (camera/image/media_player and entities that
  update more often than a configurable rate), unknown or auto-generated dashboards, missing exclude file, unknown
  users, Home Assistant not set up for reverse proxies and `local_only` switched off.
- Health endpoint with Supervisor watchdog, log timestamps in the Home Assistant time zone, new icon and logo.
- Modes: `exclude` (default; everything passes except the exclude list) and `include` (only dashboard entities pass).

### Security
- Home Assistant config folder mapped **read-only**; the add-on writes only in its own config folder (exclude
  file) and its private `/data`.
- The web UI is reachable only through Home Assistant ingress (admins) and writes only the exclude file and the add-on's private settings.
- `local_only` (default on): connections from public IP addresses are refused. Never forward port 8124.
- Client-supplied `X-Forwarded-For`, `X-Real-IP` and `Forwarded` headers are removed; the verified client address
  is passed on only when Home Assistant is set up for it (detected automatically). `trusted_proxies` is an explicit
  opt-in.
- Request bodies are streamed (no buffering); client websocket messages are limited to 16 MB.
- Control characters in URLs and names are neutralised in the log; query strings and tokens are never logged.
- In by-user mode the extra user lookup happens only after Home Assistant accepted the token, so invalid tokens
  cannot provoke failed-login bans. Failed lookups fall back to the normal stream, so nobody is locked out.
- Web UI: strict Content-Security-Policy, `nosniff`, no referrer, JSON-only POSTs, answers only the ingress gateway.
- `/__health` returns only `{"status":"ok"}`.

### Fixed
- Stopping the add-on closes panel connections first and exits within a second with exit code 0, so Home Assistant
  no longer reports an error after a manual stop.

### Notes
- Experimental: tested end-to-end against a mock Home Assistant, not yet against every real setup.
- The container installs Python and aiohttp through the package manager of the Supervisor's base image.
- The filter reduces traffic; it is not an access control. Use a restricted HA user for that.
