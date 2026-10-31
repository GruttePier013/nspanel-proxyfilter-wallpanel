# Changelog

All notable changes to this add-on. Format based on [Keep a Changelog](https://keepachangelog.com/).

## 2.0.0

First public release of **Proxyfilter for photo/wallpanel**.

### Added
- **Web UI in the Home Assistant sidebar** (ingress) to manage everything without editing add-on options.
- **Dashboard pills**: pick one or more dashboards your wall panel opens; their entities always pass.
- **Two ways to recognise the panel**: a *dedicated port* (everything on port 8124 is filtered; recommended, no token
  handling) or *by Home Assistant user* (pills; one port serves everybody).
- **Exclude list helper**: shows the file read-only, reports invalid lines, builds clean lines to paste (pasted log
  lines are converted), offers a template. The add-on never writes the file.
- **Throttling**: slow down busy dashboard entities to at most one update per 5/10/30/60 s (latest value always delivered).
- **Noisiest entities** table and wildcard suggestions with one-click "add to new lines".
- **Orange warnings** in the add-on log and UI for heavy dashboard entities (camera/image/media_player and
  entities updating more often than a configurable rate), missing or auto-generated dashboards, missing exclude
  file, unknown users, Home Assistant not set up for reverse proxies, `local_only` off.
- Health endpoint and Supervisor watchdog; log timestamps follow the Home Assistant time zone; new icon and logo.

### Security
- Home Assistant config folder and the add-on's own config folder (`addon_config`, holds your exclude file) are both
  mapped **read-only**; the only writable place is the add-on's private `/data`.
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
