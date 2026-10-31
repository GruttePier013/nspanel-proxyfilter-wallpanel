# Security

## What this add-on is

A reverse proxy for the Home Assistant frontend. It sees all traffic of the panel, including login requests and
access tokens, and forwards it to Home Assistant. Authentication stays with Home Assistant; the add-on adds none.
**Filtering is a performance feature, not a security boundary**: it can only hide entity updates from a panel, never
reveal more than Home Assistant would send to that user anyway.

## Threat model and mitigations

| Threat | Mitigation |
|---|---|
| Internet-exposed port 8124 (port-forward, UPnP) | `local_only` refuses public addresses; docs forbid port-forwarding |
| Client forges `X-Forwarded-For` to bypass bans / "local only" users / trusted networks | client forwarding headers are always stripped; address replaced by the verified one; `trusted_proxies` explicit opt-in |
| Memory exhaustion by big uploads/messages | request bodies streamed; client websocket messages ≤ 16 MB |
| Failed-login bans provoked via the add-on | user lookup only after HA accepted the token; real client IP forwarded when HA supports it |
| Add-on bug → modify Home Assistant configuration | the add-on has **no write access** to your HA folder or its own config folder (both mapped read-only); the exclude file is yours to place and edit |
| Path traversal in options / UI | exclude file confined to the add-on config folder (symlinks resolved); dashboards only by validated ids from HA's own list |
| Log forging via URLs / user names | control characters replaced before logging; query strings and tokens never logged |
| XSS / CSRF in the UI | UI built with `textContent` only; CSP; POST requires JSON content type (no cross-site form posts); UI only answers the Supervisor ingress gateway (admins) |
| Token theft at rest | tokens are never stored; a SHA-256 hash is cached in memory for 5 minutes |

## Residual risks and recommended hardening

1. **Traffic is plain HTTP** on your LAN, like Home Assistant on port 8123. Anyone who can sniff the network can read
   tokens. Use a separate IoT VLAN/SSID for panels, or terminate TLS in front (nginx / HA SSL) and set `trusted_proxies`.
2. **The panel is the weakest device.** Use a dedicated, **non-administrator** Home Assistant user for it, enable
   "Can only log in from the local network", and give it only the dashboards it needs. If the panel is stolen or
   compromised: delete the user's refresh tokens (Profile → Security) and change the password.
3. **Close ADB.** If you debug the panel over ADB (port 5555), that interface has no authentication: anyone on the
   network gets a shell and the stored HA token. Turn it off after use and block port 5555 in your firewall.
4. **Keep 8124 off the internet.** Do not forward it; for remote access use the HA Cloud, a VPN or a TLS reverse
   proxy with authentication. Keep `local_only` on.
5. **Firewall:** if your router supports it, allow port 8124 only from the panel's address.
6. **Home Assistant `http:` settings:** set `use_x_forwarded_for` + `trusted_proxies: [172.30.32.0/23]` (the add-on
   tells you), and keep `ip_ban_enabled` on. Never add the Docker network to a `trusted_networks` auth provider.
7. **Other add-ons** share the ingress origin in the browser. Install add-ons you trust.
8. **Supply chain:** the image installs `python3` and `aiohttp` from the distribution packages of the Home Assistant
   base image. In your own fork pin GitHub Actions by commit SHA and enable Dependabot.
9. **Dedicated port vs. by user.** *Dedicated port* (default) is the safer choice: no tokens are inspected, no extra
   connection to Home Assistant is made, there is no lookup that can fail open, and port 8124 can be firewalled to
   the panel's address. *By user* is convenient (one entry point) but adds the lookup code path and fails open: if
   the lookup fails the panel gets the normal stream. That is a performance trade-off, not an access-control decision.

## Reporting a vulnerability

Please open a private security advisory on GitHub (*Security → Report a vulnerability*) instead of a public issue.
