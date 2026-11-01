# Proxyfilter for photo/wallpanel

![Web UI](https://raw.githubusercontent.com/GruttePier013/proxyfilter-wallpanel-addon/main/assets/screenshot-ui.png)

## Features

- Visual web UI in the sidebar, no YAML: pick the dashboards your panel opens and how the panel is recognised
- Dashboard entities always reach the panel, so the exclude list cannot break it
- Exclude list editor, "Check an entity" and one-click suggestions for the noisiest entities
- Throttling for busy entities such as power meters, without removing them
- Orange warnings in the log and the UI for heavy entities and risky setups
- Fail-open: when in doubt the panel simply gets the normal, unfiltered stream

## Made for small devices

Handy for small CPUs, for example:

- **Rockchip** RK3326, RK3566 (budget Android tablets and panels)
- **Allwinner** A133, A64 (cheap Android tablets, wall displays)
- **Amlogic** S905 family (TV-box based displays)
- **MediaTek** MT8163, MT8167 (low-end tablets, e-readers)
- **Raspberry Pi** Zero 2 W and Pi 3 running a kiosk browser
- Android-based smart wall panels such as the Sonoff NSPanel Pro

## First steps

1. Start the add-on and open **Proxyfilter for photo/wallpanel** in the sidebar.
2. Select your dashboard(s) and set the panel's server URL in the Companion app to `http://<home-assistant-ip>:8124`.
3. Add noisy entities to the exclude list. Details are in the **Documentation** tab.

> Experimental. Never forward port 8124 to the internet; the add-on refuses public addresses by default.
