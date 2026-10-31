# Changelog

All notable changes to this add-on. Format based on [Keep a Changelog](https://keepachangelog.com/).
Every release bumps `version` in `config.yaml`; that is what makes Home Assistant offer (and, with *Auto update*
enabled, install) the update.

## 2.0.3

### Fixed
- **Automatic updates**: the add-on now records which version wrote its settings and, after an update, logs
  `updated from X to Y` and keeps your dashboards, scope, throttles and exclude file. The version in `config.yaml`,
  the script and this changelog are checked to be identical by the tests and CI, so a release can no longer ship
  with a mismatched or missing version bump.
- Settings written by older versions are read without losing anything.

### Documentation
- New *Updating* section: how to install from the repository (not as a local add-on), enable *Auto update* and force
  a refresh of the add-on store.

## 2.0.2

### Changed
- The first line of the add-on description, the options help, the README and the documentation now say:
  **Start the WEB-UI to complete the configuration** (pick your dashboards there).
- Dashboards, filter scope and users are chosen in the web UI (pills), so the available dashboards can be offered as
  suggestions.

### Fixed
- Stopping the add-on closes panel connections first and exits within a second with exit code 0, so Home Assistant
  no longer reports an error after a manual stop.

## 2.0.1

### Added
- **Exclude list editor** in the web UI: the file is created automatically in the add-on's own config folder
  (`addon_config`), validated on save, a `.bak` copy is kept, pasted log lines are converted to patterns.
- **Dashboard protection**: entity ids, wildcards (`sensor.air_mini_*`) and the entities of devices/areas used on your
  dashboards always pass, even when an exclude pattern matches them. Overlaps are reported in the UI and log.
- **Check an entity**: shows exactly why an entity passes or is blocked.
- **Clickable lists** behind the *dashboard entities* and *exclude patterns* counters.
- **Throttling card** with the busiest entities and a drop-down per entity.

## 2.0.0

First public release of **Proxyfilter for photo/wallpanel**: a filtering proxy that forwards only the traffic a
wall panel, photo frame or other small device running the HA Companion app needs, so weak CPUs stay responsive.

### Added
- **Web UI in the Home Assistant sidebar** (ingress) with live statistics.
- **Dashboard pills**: pick one or more dashboards your wall panel opens; their entities always pass.
- **Two ways to recognise the panel**: a *dedicated port* (everything on port 8124 is filtered; recommended, no token
  handling) or *by Home Assistant user* (pills; one port serves everybody).
- Modes: `exclude` (default; everything passes except the exclude list) and `include` (only dashboard entities pass).
- **Throttling**: at most one update per 5/10/30/60 s (up to 10 min) for busy entities; the latest value is always
  delivered.
- **Noisiest entities** table and wildcard suggestions with one-click "add to exclude list".
- **Orange warnings** in the log and UI for heavy dashboard entities (camera/image/media_player and entities that
  update more often than a configurable rate), unknown or auto-generated dashboards, missing exclude file, unknown
  users, Home Assistant not set up for reverse proxies and `local_only` switched off.
- Health endpoint with Supervisor watchdog, log timestamps in the Home Assistant time zone, new icon and logo.

### Security
- Home Assistant config folder mapped **read-only**; the add-on writes only in its own config folder and its private
  `/data`.
- The web UI is reachable only through Home Assistant ingress (admins) and writes only the exclude file and the
  add-on's private settings.
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

### Notes
- Experimental: tested end-to-end against a mock Home Assistant, not yet against every real setup.
- The container installs Python and aiohttp through the package manager of the Supervisor's base image.
- The filter reduces traffic; it is not an access control. Use a restricted HA user for that.
