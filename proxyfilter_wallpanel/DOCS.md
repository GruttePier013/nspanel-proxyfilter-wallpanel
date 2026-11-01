# Documentation

## Quick start

1. **Start the add-on** and open **Proxyfilter for photo/wallpanel** in the sidebar. The *Setup* block opens by itself
   until a dashboard is selected and a panel has connected.
2. **Dashboards.** Click the dashed pill of the dashboard your panel opens. Add more than one if the panel switches
   between dashboards.
3. **Which connections are filtered?** Pick one:
   * **Dedicated port (recommended):** everything that connects to port 8124 is filtered. Only the wall panel uses
     8124; phones and browsers keep using Home Assistant's normal address. No tokens or user lookups are involved.
   * **By Home Assistant user:** one port serves everybody and only the selected user(s) are filtered. Create a
     dedicated user for the panel (Settings → People → Users) first.
4. **Point the panel to the filter.** In the Companion app of the panel set the server URL to
   `http://<home-assistant-ip>:8124` (and log in as the selected user if you chose that option).
5. **Check that it works.** Within a minute the summary at the top shows `1 / 1` filtered connections and the log
   shows `ws auth … OK` (in by-user mode also `ws user … FILTERED`). The log must not show a `NOT reachable` warning.
   If you see the orange *not set up for reverse proxies* warning, add the `http:` block from the
   [Advanced](#advanced-client-addresses-bans-and-trusted_proxies) section and restart Home Assistant.
6. **Fill the exclude list.** The add-on creates `proxyfilter_exclude.txt` in its own config folder. After a few
   minutes the UI lists the noisiest entities that still reach the panel: click **exclude** (or a wildcard pill) and
   press **Save**. Within 30 seconds the filter reloads and the panel reconnects. "Traffic removed" rises as the list
   grows. Use **Check an entity** to see why an entity does or does not reach the panel.

Click the **dashboard entities** or **exclude patterns** tile in the summary to expand the list behind the number.

## How it works

The add-on listens on port **8124**. Everything is forwarded to Home Assistant; only the websocket entity
subscription (`subscribe_entities`) of the filtered connections is changed. In *dedicated port* mode that is every
connection on 8124. In *by user* mode the user behind a connection is looked up with Home Assistant's own
`auth/current_user` command, using the token the panel logs in with (after Home Assistant accepted it); tokens are
never stored or logged.

An entity reaches the panel when:

1. it is used on one of the selected dashboards (**always**), or
2. in **exclude** mode (default): it does not match the exclude file; in **include** mode: never.

Because new entities pass automatically in exclude mode, nothing you add to Home Assistant later disappears from
the panel.

## The exclude file

* It lives in the add-on's **own** config folder (`addon_configs/…_proxyfilter_wallpanel` in Samba / File editor) and
  is **created automatically** with generic examples when missing. Edit it in the web UI (a `.bak` copy is kept on
  every save) or by hand. Default `proxyfilter_exclude.txt`; change name/sub-folder in the add-on *Configuration* tab,
  e.g. `lists/proxyfilter_exclude.txt`.
* One pattern per line, `*` and `?` are wildcards, `#` starts a comment: `sensor.example_inverter_*`
* Pasting a line from the add-on log such as `[2026-01-01 12:00:00]  19.0/min  sensor.example_meter_l1  [passed]`
  works: the entity is extracted when you save.
* Invalid lines are refused in the UI (nothing is saved); in a hand-edited file they are ignored.
* Changes are picked up within 30 seconds.

### What is protected from the exclude file

Everything the selected dashboards need always passes, **even when an exclude pattern matches it**:

1. entity ids written in the dashboard (`sensor.air_mini_pm25`);
2. wildcards written in the dashboard, such as `auto-entities` filters (`sensor.air_mini_*`);
3. all entities of a **device** or **area** the dashboard refers to (area cards, device actions), resolved with
   Home Assistant's registries.

Example: with `sensor.air_*` in the exclude file, `sensor.air_monitor_*` is blocked but `sensor.air_mini_*` stays
visible when the dashboard uses it. The UI and log tell you when a pattern also matches protected entities
("… also matches 3 entities on your dashboard(s) – those stay visible"). **Check an entity** shows the exact reason
for any entity id. Not detected: entities that only appear through runtime templates or regex filters.

## Throttling busy dashboard entities

Entities on your dashboard always reach the panel, even if they update every second (power meters, for example).
When the UI shows an orange "heavy dashboard entity" warning you can click **max 1 per 5 / 10 / 30 / 60 s**. The
filter then holds back the updates in between, merges them and delivers the latest state when the interval has
passed, so the panel never shows a stale final value. Remove the throttle with the **remove** button. The choice is
stored in the add-on's private data. All of this is in the **Throttling** card of the UI: a table of the busiest entities
with a drop-down per entity, plus a field to add any entity id.

## Warnings (orange)

| Warning | Meaning | What to do |
|---|---|---|
| `too many websocket connections` in the log | More simultaneous connections than `max_connections`, e.g. a device reconnecting in a loop | Find the device; raise the limit only if you really have that many panels |
| No dashboard selected | Nothing is protected from the exclude list | Select the panel's dashboard in the web UI |
| Dashboard has no saved configuration | An auto-generated dashboard shows *all* entities, the filter cannot know which are needed | Dashboard → ⋮ → Edit → *Take control*, save |
| Selected dashboard no longer exists | Deleted or renamed | Remove the pill and pick the right dashboard |
| No user selected (by-user mode) | **Every** connection is filtered, including phones | Select the panel's user, or switch to *dedicated port* |
| Exclude file could not be created | Nothing is excluded, so little traffic is saved | Check the add-on log (folder permissions) |
| Selected user does not exist | Renamed/deleted; that user is not filtered | Re-select the user |
| `camera.*` / `image.*` / `media_player.*` on the dashboard | These update often and can never be filtered | Remove them from the wall panel dashboard |
| Heavy dashboard entity (n×/min) | A dashboard entity updates more often than *Heavy entity warning* (default 20/min) | Remove it, or use a template/helper that updates less often |

Warnings appear in the add-on **Log** (orange, starting with `⚠ WARNING`) and at the top of the UI.

## Configuration options

| Option | Default | Description |
|---|---|---|
| `upstream` | `http://homeassistant:8123` | Home Assistant address as seen from the add-on |
| `mode` | `exclude` | `exclude` or `include` (only dashboard entities pass – strict) |
| `exclude_file` | `proxyfilter_exclude.txt` | Path inside the add-on's own config folder, must end in `.txt` or `.list`; created if missing |
| `max_connections` | `20` | Maximum simultaneous websocket connections through port 8124 (a panel normally needs 1-2); extra ones get HTTP 503 |
| `local_only` | `true` | Refuse connections from public IP addresses |
| `trusted_proxies` | empty | Address/network of a reverse proxy placed *in front of* this add-on (its `X-Forwarded-For` is then trusted) |
| `heavy_per_minute` | `20` | Updates/min above which a dashboard entity triggers a warning |
| `top` | `25` | Lines per list in the log reports (0 = none) |
| `min_per_minute` / `min_per_hour` | `2` / `120` | Entities below these rates are hidden in log reports |
| `verbose` | `false` | Log every HTTP request |

Dashboards, filter scope and users are managed in the web UI, not here.

## Self-test and health

The web UI has a **Self-test** card (also run at startup, summary in the log): Home Assistant reachable, folders
readable/writable, dashboards found, exclude file usable, aiohttp version. Press **Run again** after fixing something.
Below it the add-on shows repeated failures (upstream connection, reload job) and how many connections were refused
because of `max_connections`.

## Log reports

After start and whenever the panel connects after being idle you get ten per-minute reports, then one per hour:

```
~1353.6/min [dropped] 14 entities from proxyfilter_exclude.txt
~220.0/min [passed] not on a dashboard or exclude list (candidates for the exclude file): 40 entities
    19.0/min  sensor.example_meter_l1  [passed]
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Panel shows login but nothing is filtered | By-user mode: the panel's user is not selected in Setup, or the log says `ws user … passthrough`; the name must match the Home Assistant display name. Or the panel is not using port 8124. |
| "Filtered / open connections" stays 0 | The panel does not use `:8124` yet. Check the server URL in the Companion app. |
| Add-on build fails with a network/timeout error | The Pi cannot reach the container registry. Check DNS/internet (`ha dns restart`), then Rebuild. |
| A card on the panel stays empty | The entity is in the exclude list *and* not found on a selected dashboard (e.g. a YAML-mode dashboard or an entity used only inside a custom card template). Add the dashboard, or remove the pattern; **Check an entity** shows why it is blocked. |
| Panel login loops | Open the add-on log; `login … -> 4xx` lines show the upstream answer. Check `upstream`. |
| Filter seems stuck after a Home Assistant restart | The panel reconnects by itself; restart the Companion app if it does not. |

**Limitations:** dashboards in YAML mode are not listed in the UI (their entities cannot be read from storage) –
convert them to storage mode or protect their entities by not excluding them. Entities referenced only through
templates generated at runtime cannot be detected; they are protected only if their id appears in the dashboard
configuration.

## Advanced: client addresses, bans and `trusted_proxies`

Home Assistant only sees the add-on as the sender of every request. For failed-login bans, "local only" users and
trusted networks to keep working, tell Home Assistant to trust the add-on's forwarded address in `configuration.yaml`:

```yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 172.30.32.0/23
```

The add-on checks this at start-up and every minute until it works; if Home Assistant is not set up yet you get an
orange warning with exactly this snippet, and everything keeps working (without real client addresses). The add-on
always **replaces** any `X-Forwarded-For` a client sends with the address it really saw, so clients cannot forge
their address.

If you keep nginx (or similar) in front of the add-on, put that proxy's address in the add-on option
`trusted_proxies`; only then is its `X-Forwarded-For` honoured. In *by user* mode no per-panel routing rules are needed.

## Updating

* Install the add-on **from the repository** (Settings → Add-ons → Add-on Store → ⋮ → Repositories). A copy placed in
  the `/addons` folder is a *local* add-on: Home Assistant never updates those.
* Turn on **Auto update** on the add-on's Info tab to install new versions automatically, or press **Update**
  yourself. The store refreshes about once a day; use ⋮ → **Check for updates** to refresh now.
* An update rebuilds the container on your device (no prebuilt image), which can take a few minutes on a Raspberry Pi.
  The panel reconnects by itself afterwards.
* Your dashboards, filter scope, throttles and exclude file are kept. The log shows `updated from X to Y`.

## Privacy and security

What the add-on reads and writes, the threat model and hardening advice are in
[SECURITY.md](https://github.com/GruttePier013/proxyfilter-wallpanel-addon/blob/main/SECURITY.md).
