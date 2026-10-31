# Proxyfilter for photo/wallpanel

> ### 👉 STEP 1 ▶ **Start the WEB-UI to complete the configuration** 🖥️
> Open *Proxyfilter for photo/wallpanel* in the sidebar and pick your dashboards there. ✅

Proxy filter designed to feed only the traffic that is relevant to a wallpanel, photo frame or other small
hardware device running the Home Assistant Companion app. The purpose is to use as little of the device's CPU as
possible, which is especially handy for small CPUs, for example:

* **Rockchip** RK3326, RK3566 (budget Android tablets and panels)
* **Allwinner** A133, A64 (cheap Android tablets, wall displays)
* **Amlogic** S905 family (TV-box based displays)
* **MediaTek** MT8163, MT8167 (low-end tablets, e-readers)
* **Raspberry Pi** Zero 2 W and Pi 3 running a kiosk browser
* Ready-made smart wall panels such as the Sonoff NSPanel Pro

How it works: the Home Assistant frontend receives every state change of every entity. The filter forwards only
the entities the device needs, for a dedicated port or for the Home Assistant user(s) you select. Everything else
passes through unchanged.

* Visual setup in the sidebar: pick dashboards with pill buttons, filter a dedicated port or a user; also filters, throttling and checks
* Exclude list editor in the UI (file created in the add-on's own folder); "Check an entity" explains every decision
* Orange warnings for heavy entities and risky setups; throttling for busy entities
* Fail-open: when in doubt the device gets the normal stream

See the **Documentation** tab to get started.
