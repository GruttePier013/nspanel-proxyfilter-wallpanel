# Changelog

All notable changes to this add-on. Format based on [Keep a Changelog](https://keepachangelog.com/).

## 2.0.0

First public release of **Proxyfilter for photo/wallpanel**.

### Added
- **Web UI in the Home Assistant sidebar** (ingress) for the exclude list, throttling, live statistics and checks.
- **`dashboards` option** in the normal Configuration tab: dashboards your wall panel opens, by URL name, title or id
  (`default` = default dashboard); their entities always pass. Unknown names are reported in the UI and log.
- **Two ways to recognise the panel** (`scope` option): `port` (everything on port 8124 is filtered; recommended, no
  token handling) or `users` (the HA users in `users`; one port serves everybody). Changes apply within 30 s without
  a restart.
- **Exclude list editor**: the file is created in the add-on's own config folder, edited in the UI with validation,
  pasted log lines are converted, a `.bak` copy is kept, changes apply immediately.
- **Dashboard protection**: besides literal entity ids, wildcards used on the dashboard (`sensor.air_mini_*`) and the
  entities of devices/areas the dashboard refers to always pass, even when an exclude pattern matches them. The UI
  and log report such overlaps.
- **Check an entity** tool, and clickable lists behind the *dashboard entities* and *exclude patterns* counters.
- **Throttling card** with a table of the busiest entities and a drop-down per entity.
- **Throttling**: slow down busy dashboard entities to at most one update per 5/10/30/60 s (latest value always delivered).
- **Noisiest entities** table and wildcard suggestions with one-click "add to new lines".
- **Orange warnings** in the add-on log and UI for heavy dashboard entities (camera/image/media_player and
  entities updating more often than a configurable rate), missing or auto-generated dashboards, missing exclude
  file, unknown users, Home Assistant not set up for reverse proxies, `local_only` off.
- Health endpoint and Supervisor watchdog; log timestamps follow the Home Assistant time zone; new icon and logo.

### Security
- Home Assistant config folder mapped **read-only**; the add-on can write only its own config folder (`addon_config`,
  the exclude file) and its private `/data`.
- `local_only` (default on): connections from public IP addresses are refused.
- Client-supplied `X-Forwarded-For`, `X-Real-IP` and `Forwarded` headers are removed; the verified address is sent
  instead (when Home Assistant is set up for it, detected automatically). `trusted_proxies` is an explicit opt-in.
- Uploads are streamed (no memory buffering); client websocket messages limited to 16 MB.
- Control characters in URLs/names are neutralised in the log; query strings and tokens are never logged.
- In by-user mode the extra lookup happens only after Home Assistant accepted the token, so invalid tokens cannot
  provoke failed-login bans.
- Web UI: strict Content-Security-Policy, `nosniff`, no referrer, JSON-only POSTs, ingress gateway only.
- `/__health` returns only `{"status":"ok"}`.
- Unknown or failed user lookups fall back to the normal stream, so nothing can lock a user out.
- Dashboard entities can never be blocked, whatever the exclude file says.

### Notes
- The container installs Python and aiohttp through the distribution package manager of the Supervisor's base image.
