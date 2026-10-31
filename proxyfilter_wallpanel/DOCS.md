# Proxyfilter for photo/wallpanel – documentation

Proxy filter designed to feed only traffic relevant to a wallpanel, photo frame or other small hardware device running
the Home Assistant Companion app, so the device's limited CPU is used as little as possible.

## Quick start

1. Start the add-on and open **Proxyfilter for photo/wallpanel** in the sidebar.
2. **Step 1 – Dashboards.** Click the dashed pill of the dashboard your panel opens. Add more than one if the panel
   switches between dashboards.
3. **Step 2 – Which connections are filtered?** Pick one:
   * **Dedicated port (recommended):** everything that connects to port 8124 is filtered. Only the wall panel uses
     8124; phones and browsers keep using Home Assistant's normal address. No tokens or user lookups are involved.
   * **By Home Assistant user:** one port serves everybody and only the selected user(s) are filtered. Create a
     dedicated user for the panel (Settings → People → Users) first.
4. **Step 3 – Point the panel to the filter.** In the Companion app of the panel set the server URL to
   `http://<home-assistant-ip>:8124` (and log in as the selected user if you chose that option).
5. **Step 4 – Exclude list.** Create the file `proxyfilter_exclude.txt` in this add-on's config folder (`addon_configs/…_proxyfilter_wallpanel`
   in Samba, or via the File editor add-on). The UI shows a template (*Copy complete file*). After a few minutes it lists the noisiest
   entities that still reach the panel: click **exclude**, press **Copy new lines** and paste them into the file.
   Within 30 seconds the filter reloads and the panel reconnects automatically.

The status block in step 3 shows how much traffic was removed and whether a filtered panel is connected.

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

* **You** create and edit it; the add-on only reads it. It lives in the add-on's **own** config folder
  (`addon_configs/…_proxyfilter_wallpanel` in Samba / File editor), which is mapped read-only, so nothing in your Home
  Assistant configuration is touched. Default `proxyfilter_exclude.txt`; change name/sub-folder in the add-on
  *Configuration* tab, e.g. `lists/proxyfilter_exclude.txt`.
* One pattern per line, `*` and `?` are wildcards, `#` starts a comment: `sensor.example_inverter_*`
* Pasting a line from the add-on log such as `[2026-01-01 12:00:00]  19.0/min  sensor.example_meter_l1  [passed]`
  works: the filter extracts the entity. The UI's *Copy new lines* does the same clean-up for you.
* Lines that are not patterns are reported in the UI and ignored; they can never break the filter.
* Changes are picked up within 30 seconds.

## Throttling busy dashboard entities

Entities on your dashboard always reach the panel, even if they update every second (power meters, for example).
When the UI shows an orange "heavy dashboard entity" warning you can click **max 1 per 5 / 10 / 30 / 60 s**. The
filter then holds back the updates in between, merges them and delivers the latest state when the interval has
passed, so the panel never shows a stale final value. Remove the throttle with the **remove** button. The choice is
stored in the add-on's private data; the panel reconnects are not needed.

## Warnings (orange)

| Warning | Meaning | What to do |
|---|---|---|
| No dashboard selected | Nothing is protected from the exclude list | Select the panel's dashboard |
| Dashboard has no saved configuration | An auto-generated dashboard shows *all* entities, the filter cannot know which are needed | Dashboard → ⋮ → Edit → *Take control*, save |
| Selected dashboard no longer exists | Deleted or renamed | Remove the pill and pick the right dashboard |
| No user selected (by-user mode) | **Every** connection is filtered, including phones | Select the panel's user, or switch to *dedicated port* |
| Exclude file does not exist | Nothing is excluded, so little traffic is saved | Create the file (template in the UI) |
| Selected user does not exist | Renamed/deleted; that user is not filtered | Re-select the user |
| `camera.*` / `image.*` / `media_player.*` on the dashboard | These update often and can never be filtered | Remove them from the wall panel dashboard |
| Heavy dashboard entity (n×/min) | A dashboard entity updates more often than *Heavy entity warning* (default 20/min) | Remove it, or use a template/helper that updates less often |

Warnings appear in the add-on **Log** (orange, starting with `⚠ WARNING`) and at the top of the UI.

## Configuration options

| Option | Default | Description |
|---|---|---|
| `upstream` | `http://homeassistant:8123` | Home Assistant address as seen from the add-on |
| `mode` | `exclude` | `exclude` or `include` (only dashboard entities pass – strict) |
| `exclude_file` | `proxyfilter_exclude.txt` | Path inside the add-on's config folder, must end in `.txt` or `.list` |
| `local_only` | `true` | Refuse connections from public IP addresses |
| `trusted_proxies` | empty | Address/network of a reverse proxy placed *in front of* this add-on (its `X-Forwarded-For` is then trusted) |
| `heavy_per_minute` | `20` | Updates/min above which a dashboard entity triggers a warning |
| `top` | `25` | Lines per list in the log reports (0 = none) |
| `min_per_minute` / `min_per_hour` | `2` / `120` | Entities below these rates are hidden in log reports |
| `verbose` | `false` | Log every HTTP request |

Dashboards and users are managed in the UI, not here.

## Log reports

After start and whenever the panel connects after being idle you get ten per-minute reports, then one per hour:

```
~1353.6/min [dropped] 14 entities from proxyfilter_exclude.txt
~220.0/min [passed] not on a dashboard or exclude list (candidates for the exclude file): 40 entities
    19.0/min  sensor.example_meter_l1  [passed]
```

## Client addresses, bans and `trusted_proxies` (important)

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

## First-run checklist

1. The add-on log shows `listening … web UI …` and no `NOT reachable` warning.
2. The sidebar page opens and lists your dashboards (and users).
3. After step 3 the status block shows `1 / 1` filtered connections within a minute of the panel connecting.
4. The log shows `ws auth … OK` (and, in by-user mode, `ws user … FILTERED`).
5. "Traffic removed" rises once the exclude file contains patterns.
6. If you see the orange *not set up for reverse proxies* warning, add the shown `http:` block and restart HA.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Panel shows login but nothing is filtered | By-user mode: the panel's user is not selected (step 2), or the log says `ws user … passthrough`; the name must match the Home Assistant display name. Or the panel is not using port 8124. |
| "Filtered / open connections" stays 0 | The panel does not use `:8124` yet. Check the server URL in the Companion app. |
| Add-on build fails with a network/timeout error | The Pi cannot reach the container registry. Check DNS/internet (`ha dns restart`), then Rebuild. |
| A card on the panel stays empty | The entity is in the exclude list *and* not found on a selected dashboard (e.g. a YAML-mode dashboard or an entity used only inside a custom card template). Add the dashboard, or remove the pattern. |
| Panel login loops | Open the add-on log; `login … -> 4xx` lines show the upstream answer. Check `upstream`. |
| Filter seems stuck after a Home Assistant restart | The panel reconnects by itself; restart the Companion app if it does not. |

**Limitations:** dashboards in YAML mode are not listed in the UI (their entities cannot be read from storage) –
convert them to storage mode or protect their entities by not excluding them. Entities referenced only through
templates generated at runtime cannot be detected; they are protected only if their id appears in the dashboard
configuration.

## Privacy & security

* Both the Home Assistant config folder and the add-on's own config folder are mapped **read-only**; the only
  writable place is the add-on's private `/data` (UI choices). It cannot change your configuration. It reads `.storage/lovelace*` (dashboards), `.storage/auth` (display names of users, nothing else)
  and `.storage/core.config` (time zone).
* The web UI is only reachable through Home Assistant's ingress (admins only).
* Port 8124 forwards to Home Assistant, which does the authentication. By default (`local_only`) connections from
  public IP addresses are refused. Never port-forward 8124; see [SECURITY.md](../SECURITY.md).
* Access tokens are held in memory as a hash for 5 minutes (to avoid repeated lookups) and never logged.
