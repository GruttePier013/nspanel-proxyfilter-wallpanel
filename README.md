<p align="center"><img src="proxyfilter_wallpanel/logo.png" alt="Proxyfilter for photo/wallpanel" width="250"></p>

# Proxyfilter for photo/wallpanel – Home Assistant add-on

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FYOUR-GITHUB-USER%2Fproxyfilter-wallpanel-addon)

**Make a slow wallpanel or photo frame fast – without disabling a single entity.**

> Status: experimental. Please report problems via GitHub issues.

Proxy filter designed to feed only the traffic that is relevant to a wallpanel, photo frame or other small
hardware device running the Home Assistant Companion app. The purpose is to use as little of the device's CPU as
possible, which is especially handy for small CPUs, for example:

* **Rockchip** RK3326, RK3566 (budget Android tablets and panels)
* **Allwinner** A133, A64 (cheap Android tablets, wall displays)
* **Amlogic** S905 family (TV-box based displays)
* **MediaTek** MT8163, MT8167 (low-end tablets, e-readers)
* **Raspberry Pi** Zero 2 W and Pi 3 running a kiosk browser
* Ready-made smart wall panels such as the Sonoff NSPanel Pro

The cause of the slowness is usually not your dashboard: the Home Assistant frontend receives *every* state change
of *every* entity, and the device spends its CPU on updates it never shows. On a busy installation that is thousands
of updates per minute. Proxyfilter for photo/wallpanel sits between the device and Home Assistant and forwards only
the entities that device needs. Login, the dashboard itself and all other traffic pass through untouched.

## Features

- 🖥️ **Visual add-on** in the sidebar – no YAML needed
- 🔘 **Pill buttons** to pick the dashboards the panel opens, and whether to filter a dedicated port or a Home Assistant user
- 📝 **Exclude list helper**: you keep the file yourself; the UI shows it, validates it and builds the lines to paste
- ⏱️ **Throttle** busy dashboard entities (e.g. power sensors) without removing them
- 📊 **Noisiest entities** list with one-click exclude and wildcard suggestions
- 🟠 **Orange warnings** (log and UI) for heavy entities on the panel dashboard and for risky setups
- 🔒 **Hardened**: read-only access to HA, local network only, forged client addresses stripped – see [SECURITY.md](SECURITY.md)
- 🛟 **Fail-open**: if anything is unclear the panel simply gets the normal, unfiltered stream
- Entities on your dashboards are **never** blocked, so you cannot break the panel from the exclude list

## Install

1. In Home Assistant: **Settings → Add-ons → Add-on store → ⋮ → Repositories** and add  
   `https://github.com/YOUR-GITHUB-USER/proxyfilter-wallpanel-addon`  
   (or click the badge above).
2. Install **Proxyfilter for photo/wallpanel**, enable *Start on boot* and *Watchdog*, then **Start**.
3. Open **Proxyfilter for photo/wallpanel** in the sidebar and follow the four numbered steps:
   dashboards → dedicated port or user → point the panel to `http://<home-assistant-ip>:8124` → exclude list.

Full instructions, troubleshooting and background: [DOCS.md](proxyfilter_wallpanel/DOCS.md).

### Local install (without GitHub)

Copy the `proxyfilter_wallpanel` folder to `/addons/proxyfilter_wallpanel` on your Home Assistant (Samba or SSH add-on),
then **Add-on store → ⋮ → Check for updates**. It appears under *Local add-ons*.

## Repository layout

```
repository.yaml            add-on repository metadata (edit your GitHub URL here)
proxyfilter_wallpanel/          the add-on
  config.yaml Dockerfile   add-on definition and image
  app/                     proxy + web UI (Python, aiohttp) and ui/index.html
  README.md DOCS.md CHANGELOG.md icon.png logo.png translations/
assets/                    logo sources (SVG) and make_logos.py
tests/test_all.py          end-to-end + security tests against a mock Home Assistant
SECURITY.md                threat model and hardening advice
```

## Development

```bash
pip install aiohttp
python3 tests/test_all.py                         # runs the whole suite
python3 proxyfilter_wallpanel/app/proxyfilter_wallpanel.py --help   # run outside Home Assistant
python3 assets/make_logos.py                      # re-render icon.png / logo.png (needs playwright)
```

## License

MIT – see [LICENSE](LICENSE).
