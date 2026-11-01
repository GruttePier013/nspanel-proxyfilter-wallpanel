#!/usr/bin/env python3
"""Proxyfilter for photo/wallpanel - a filtering reverse proxy for the Home Assistant frontend.

The HA frontend subscribes to ALL entities (subscribe_entities). On a weak wall panel
that means every state change of every entity is processed, even if the dashboard only
shows a handful of them. This proxy sits in front of Home Assistant, passes everything
through unchanged (HTTP, login, static files) and filters only the entity stream of the
HA users you select, so the panel receives just what it needs.

* Entities used on the dashboards you select ALWAYS pass.
* Everything else passes, except what matches your exclude file ("exclude" mode),
  or nothing else passes ("include" mode).
* A small web UI (Home Assistant ingress) edits all of this.

Standalone usage (outside Home Assistant OS):
  pip install aiohttp
  python3 proxyfilter_wallpanel.py --upstream http://homeassistant.local:8123 \
      --config-dir /config --data-dir ./data --exclude-file proxyfilter_exclude.txt
"""
import argparse
import asyncio
import collections
import fnmatch
import hashlib
import ipaddress
import json
import os
import sys
import re
import shutil
import signal
import time
import traceback
from urllib.parse import urlsplit

import aiohttp
from aiohttp import WSMsgType, web

VERSION = "2.0.4"

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
       "te", "trailers", "transfer-encoding", "upgrade", "host"}
BUILTIN_ALLOW = ["sun.sun", "zone.*", "person.*", "persistent_notification.*"]
HEAVY_DOMAINS = ("camera", "image", "media_player")
ENTITY_RE = re.compile(r"\b[a-z][a-z0-9_]*\.[a-z0-9_]+\b")
TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_*?]+$")
ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
ENTITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")
MAX_THROTTLE = 600                     # seconds
LOGIN_PATHS = ("/auth/token", "/auth/login_flow", "/auth/authorize", "/auth/revoke")
INGRESS_GATEWAY = "172.30.32.2"
ORANGE, RESET = "\033[38;5;208m", "\033[0m"
VERBOSE = False
CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
FWD_HEADERS = {"x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "forwarded"}
UP_MAX = 64 * 1024 * 1024              # largest message accepted from Home Assistant (a full state dump is a few MB)
DEFAULT_MAX_CONNECTIONS = 20           # simultaneous websocket connections through the proxy
UI_LIMITS = {"GET": 120, "POST": 60}   # web UI requests per minute (the page polls 12 times a minute)
WS_CLIENT_MAX = 16 * 1024 * 1024        # largest message a client may send us (HA itself allows far less)

EXCLUDE_TEMPLATE = """\
# Proxyfilter for photo/wallpanel - entities your wall panel does NOT need.
# (You can edit it here or in the add-on's web UI; the add-on keeps a .bak copy when saving from the UI.)
#
# One pattern per line. * and ? are wildcards. Everything after # is a comment.
# Entities used on the dashboards you selected are NEVER blocked, whatever is
# listed here: literal entity ids, wildcards such as sensor.air_mini_*, and the
# entities of devices/areas that the dashboards refer to.
#
# You can paste lines straight from the add-on log; the entity is extracted for you.
#
# Generic examples (remove the # to activate):
# sensor.example_inverter_*            # everything from one chatty device
# sensor.example_meter_phase_?_current # ? matches exactly one character
# binary_sensor.example_motion_*
# update.*                             # a whole domain
"""


# ----------------------------------------------------------------------------- logging
def clean(text):
    """Make untrusted text (URL paths, headers, names) safe for the log: no line breaks, no ANSI codes."""
    return CTRL_RE.sub("?", str(text))


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {clean(msg)}", flush=True)


def warn(msg):
    """Orange warning line (ANSI colour; the word WARNING keeps it visible without colour)."""
    print(f"{ORANGE}[{time.strftime('%Y-%m-%d %H:%M:%S')}] ⚠ WARNING  {clean(msg)}{RESET}", flush=True)


def _ip(text):
    try:
        return ipaddress.ip_address(str(text).strip())
    except ValueError:
        return None


def from_trusted_proxy(request, nets):
    ip = _ip(request.remote)
    return bool(ip and any(ip in n for n in nets))


def client_chain(request, nets):
    """Real client address chain. X-Forwarded-For sent by a client is IGNORED (it could be forged);
    it is only honoured when the TCP peer is one of the configured trusted reverse proxies."""
    chain = []
    if nets and from_trusted_proxy(request, nets):
        chain = [x.strip() for x in request.headers.get("X-Forwarded-For", "").split(",") if _ip(x)]
    return chain + [request.remote or "?"]


def peer_of(request):
    nets = request.app["trusted_nets"]
    return client_chain(request, nets)[0] if nets and from_trusted_proxy(request, nets) else (request.remote or "?")


def upstream_headers(request):
    """Headers for Home Assistant: hop-by-hop and any client-supplied forwarding headers removed;
    the verified client chain is added when Home Assistant is set up for reverse proxies."""
    app = request.app
    h = {k: v for k, v in request.headers.items() if k.lower() not in HOP and k.lower() not in FWD_HEADERS}
    h.update(forward_headers(request))
    h["Host"] = app["up_host"]
    return h


def forward_headers(request):
    app = request.app
    if app["fwd"]["ok"]:
        return {"X-Forwarded-For": ", ".join(client_chain(request, app["trusted_nets"]))}
    return {}


async def probe_forwarding(app):
    """Does Home Assistant accept X-Forwarded-For from us? (http: use_x_forwarded_for + trusted_proxies)"""
    try:
        async with app["session"].get(app["upstream"] + "/manifest.json", headers={"X-Forwarded-For": "203.0.113.7"},
                                      timeout=aiohttp.ClientTimeout(total=10)) as r:
            ok = r.status != 400
    except Exception:                                     # noqa: BLE001 - unreachable: try again later
        return
    if ok != app["fwd"]["ok"]:
        app["fwd"]["ok"] = ok
        if ok:
            log("upstream      Home Assistant accepts forwarded client addresses: panels are seen with their real IP")
        else:
            log_warnings(app)


def parse_pattern_line(line):
    """First token that looks like `domain.pattern`. Lets you paste report lines straight into the
    exclude file: '[2026-01-01 12:00:00]   19.0/min  sensor.example_x  [passed]' -> 'sensor.example_x'."""
    for tok in line.split("#", 1)[0].split():
        if TOKEN_RE.match(tok) and not tok.endswith((".txt", ".yaml", ".yml", ".json")):
            return tok
    return None


# ----------------------------------------------------------------------------- HA files
def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def atomic_write(path, text):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def discover_dashboards(config_dir):
    """Dashboards that exist in this HA instance (UI/storage mode)."""
    st = os.path.join(config_dir, ".storage")
    out = [{"key": "lovelace", "title": "Default dashboard (Overview)", "url_path": "(default)"}]
    data = read_json(os.path.join(st, "lovelace_dashboards")) or {}
    for it in ((data.get("data") or {}).get("items") or []):
        key = it.get("id")
        if isinstance(key, str) and ID_RE.match(key):
            out.append({"key": key, "title": it.get("title") or key, "url_path": it.get("url_path") or key})
    for d in out:
        d["file"] = os.path.join(st, "lovelace" if d["key"] == "lovelace" else f"lovelace.{d['key']}")
        d["exists"] = os.path.isfile(d["file"])
    return out


def discover_users(config_dir):
    """Display names of the real (non-system, active) HA users. Only names are read."""
    data = read_json(os.path.join(config_dir, ".storage", "auth")) or {}
    names = {u["name"] for u in ((data.get("data") or {}).get("users") or [])
             if isinstance(u, dict) and u.get("name") and not u.get("system_generated") and u.get("is_active", True)}
    return sorted(names, key=str.lower)


def apply_timezone(config_dir):
    tz = ((read_json(os.path.join(config_dir, ".storage", "core.config")) or {}).get("data") or {}).get("time_zone")
    if tz:
        os.environ["TZ"] = tz
        try:
            time.tzset()
        except AttributeError:
            pass


class Settings:
    """UI-managed settings (selected dashboards, users, scope, throttles), kept in the add-on's private /data."""

    def __init__(self, path):
        self.path = path
        self.data = {"dashboards": [], "users": [], "scope": "port", "throttle": {}}
        self.prev_version = None                  # version that wrote the file (None = first start)
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            warn(f"settings file unreadable ({exc}); starting with empty settings. "
                 f"The broken file is kept as {self.path}.broken")
            try:
                shutil.copy(self.path, self.path + ".broken")
            except OSError:
                pass
            return
        raw = raw if isinstance(raw, dict) else {}
        self.prev_version = str(raw.get("version"))[:20] if raw.get("version") else "older"
        for k in ("dashboards", "users"):
            v = raw.get(k)
            self.data[k] = [str(x)[:100] for x in v][:50] if isinstance(v, list) else []
        thr = raw.get("throttle")
        if isinstance(thr, dict):
            self.data["throttle"] = {e: int(v) for e, v in thr.items()
                                     if isinstance(e, str) and ENTITY_ID_RE.match(e)
                                     and isinstance(v, int) and 1 <= v <= MAX_THROTTLE}
        if raw.get("scope") in ("port", "users"):
            self.data["scope"] = raw["scope"]

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        atomic_write(self.path, json.dumps({"version": VERSION, **self.data}, indent=2))


# ----------------------------------------------------------------------------- allow/deny
WILD_RE = re.compile(r"\b[a-z][a-z0-9_]*\.[a-z0-9_]*[*?][a-z0-9_*?]*")
REF_KEYS = {"device_id": "device", "device": "device", "devices": "device",
            "area": "area", "area_id": "area", "areas": "area"}
REGISTRY_FILES = ("core.entity_registry", "core.device_registry")


def scan_dashboard(text):
    """What a dashboard needs: literal entity ids, wildcard patterns (auto-entities & co.),
    and the devices/areas it refers to (area cards, device actions)."""
    ids = set(ENTITY_RE.findall(text))
    wild = set(WILD_RE.findall(text))
    ids -= {re.split(r"[*?]", w)[0] for w in wild}              # "sensor.air_*" also yields the fragment "sensor.air_"
    refs = {"device": set(), "area": set()}
    try:
        data = json.loads(text)
    except ValueError:
        data = None

    def walk(x, key=None):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, str) and key in REF_KEYS:
            refs[REF_KEYS[key]].add(x)
    walk(data)
    return ids, wild, refs["device"], refs["area"]


def registry_entities(config_dir, devices, areas):
    """{entity id: reason} for entities that belong to a device/area the dashboards refer to."""
    if not config_dir or not (devices or areas):
        return {}
    st = os.path.join(config_dir, ".storage")
    ents = ((read_json(os.path.join(st, "core.entity_registry")) or {}).get("data") or {}).get("entities") or []
    devs = ((read_json(os.path.join(st, "core.device_registry")) or {}).get("data") or {}).get("devices") or []
    dev_area = {d.get("id"): d.get("area_id") for d in devs if isinstance(d, dict)}
    out = {}
    for e in ents:
        eid = e.get("entity_id") if isinstance(e, dict) else None
        if not isinstance(eid, str):
            continue
        dev = e.get("device_id")
        area = e.get("area_id") or dev_area.get(dev)
        if dev and dev in devices:
            out[eid] = "its device is used on a selected dashboard"
        elif area and area in areas:
            out[eid] = f"its area ({area}) is used on a selected dashboard"
    return out


class Allow:
    """Decides which entity ids reach the panel.

    ALWAYS pass: entities on the selected dashboards (literal ids, dashboard wildcards such as
    `sensor.air_mini_*`, and entities of devices/areas the dashboards refer to), built-ins and
    --allow patterns. These win over the exclude file.
    mode "include": everything else is dropped.
    mode "exclude": everything else passes unless it matches an exclude pattern.
    """

    def __init__(self, dashboards, patterns, mode="exclude", excludes=(), exclude_files=(), config_dir=None):
        self.dashboards = list(dashboards)
        self.exclude_files = list(exclude_files)
        self.static_excl = list(excludes)
        self.config_dir = config_dir
        self.mode = mode
        self.rx = self._rx(list(BUILTIN_ALLOW) + list(patterns))
        self.mtimes, self.exact, self.excl_pats, self.excl = {}, {}, [], None
        self.wild, self.wild_rx = [], None
        self.reload(force=True)

    @staticmethod
    def _rx(pats):
        return re.compile("|".join(fnmatch.translate(p) for p in pats)) if pats else None

    def set_dashboards(self, paths):
        self.dashboards = list(paths)
        return self.reload(force=True)

    def reload(self, force=False):
        watch = self.dashboards + self.exclude_files
        if self.config_dir:
            watch += [os.path.join(self.config_dir, ".storage", f) for f in REGISTRY_FILES]
        mt = {}
        for p in watch:
            try:
                mt[p] = os.path.getmtime(p)
            except OSError:
                pass
        if not force and mt == self.mtimes:
            return False
        exact, pats, wild, devs, areas = {}, list(self.static_excl), set(), set(), set()
        for path in mt:
            try:
                if path in self.exclude_files:
                    with open(path, encoding="utf-8") as fh:
                        pats += [x for x in map(parse_pattern_line, fh) if x]
                elif path in self.dashboards:
                    with open(path, encoding="utf-8") as fh:
                        ids, w, d, a = scan_dashboard(fh.read())
                    for e in ids:
                        exact.setdefault(e, f"listed on dashboard {os.path.basename(path)}")
                    wild |= w
                    devs |= d
                    areas |= a
            except (OSError, UnicodeDecodeError) as exc:
                warn(f"cannot read {path}: {exc}")
        for e, why in registry_entities(self.config_dir, devs, areas).items():
            exact.setdefault(e, why)
        wild = sorted(wild)
        changed = exact != self.exact or pats != self.excl_pats or wild != self.wild
        self.mtimes, self.exact, self.excl_pats, self.excl = mt, exact, pats, self._rx(pats)
        self.wild, self.wild_rx = wild, self._rx(wild)
        return changed

    def protected(self, entity_id):
        return (entity_id in self.exact or (self.rx is not None and self.rx.match(entity_id) is not None)
                or (self.wild_rx is not None and self.wild_rx.match(entity_id) is not None))

    def __call__(self, entity_id):
        if self.protected(entity_id):
            return True
        if self.mode == "include":
            return False
        return self.excl is None or self.excl.match(entity_id) is None

    def explain(self, e):
        """(passes, reason) - why this entity id does or does not reach the panel."""
        if e in self.exact:
            return True, f"passes (always): {self.exact[e]}"
        if self.rx is not None and self.rx.match(e):
            return True, "passes (always): built-in or extra allowed pattern"
        for w in self.wild:
            if fnmatch.fnmatchcase(e, w):
                return True, f"passes (always): matches the wildcard {w} used on a selected dashboard"
        if self.mode == "include":
            return False, "blocked: include mode and not used on a selected dashboard"
        for pat in self.excl_pats:
            if fnmatch.fnmatchcase(e, pat):
                return False, f"blocked by exclude pattern {pat}"
        return True, "passes: not used on a dashboard, but not excluded either"

    def overlaps(self):
        """Exclude patterns that also match protected dashboard entities (those stay visible)."""
        out = []
        for pat in self.excl_pats:
            hit = sorted(e for e in self.exact if fnmatch.fnmatchcase(e, pat))
            if hit:
                out.append({"pattern": pat, "count": len(hit), "examples": hit[:4]})
        return out


def filter_event(ev, allow, counts=None):
    """Filter one subscribe_entities event ({a: added, c: changed, r: removed})."""
    out = {}
    if counts is not None:
        if isinstance(counts, collections.Counter):
            counts = [counts]
        for e in ev.get("c", ()):
            for c in counts:
                c[e] += 1
    if "a" in ev:
        a = {k: v for k, v in ev["a"].items() if allow(k)}
        if a:
            out["a"] = a
    if "c" in ev:
        c = {k: v for k, v in ev["c"].items() if allow(k)}
        if c:
            out["c"] = c
    if "r" in ev:
        r = [k for k in ev["r"] if allow(k)]
        if r:
            out["r"] = r
    return out


def merge_diff(old, new):
    """Merge two subscribe_entities change diffs ({"+": added/changed, "-": removed}) of one entity."""
    if not old:
        return new
    plus = dict(old.get("+", {}))
    minus = {k: list(v) if isinstance(v, list) else v for k, v in old.get("-", {}).items()}
    for k, v in new.get("+", {}).items():
        if k == "a" and isinstance(v, dict) and isinstance(plus.get("a"), dict):
            plus["a"] = {**plus["a"], **v}
        else:
            plus[k] = v
    for k, v in new.get("-", {}).items():
        if isinstance(v, list):
            minus[k] = sorted(set(minus.get(k, [])) | set(v))
            if k == "a" and isinstance(plus.get("a"), dict):          # removed again after being set
                plus["a"] = {a: b for a, b in plus["a"].items() if a not in v}
        else:
            minus[k] = v
    if isinstance(plus.get("a"), dict) and isinstance(minus.get("a"), list):
        minus["a"] = [x for x in minus["a"] if x not in plus["a"]]
    minus = {k: v for k, v in minus.items() if v}
    out = {}
    if plus:
        out["+"] = plus
    if minus:
        out["-"] = minus
    return out


def group_wildcards(entities):
    """[(entity, count)] -> {wildcard: [n_entities, n_events]} using the first word of the name."""
    groups = collections.defaultdict(lambda: [0, 0])
    for e, n in entities:
        dom, _, name = e.partition(".")
        key = f"{dom}.{name.split('_')[0]}_*" if "_" in name else e
        groups[key][0] += 1
        groups[key][1] += n
    return groups


# ----------------------------------------------------------------------------- exclude file
def normalize_exclude(text):
    """Clean up the exclude file text. Returns (text, converted, errors, warnings)."""
    out, errors, warnings, converted = [], [], [], 0
    for i, line in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            out.append(line.rstrip())
            continue
        pat = parse_pattern_line(line)
        if pat is None:
            errors.append(f"line {i}: “{s[:60]}” is not an entity pattern such as sensor.example_* "
                          f"(start the line with # to make it a comment)")
            continue
        if pat != s.split("#", 1)[0].strip():
            converted += 1
        comment = ("  #" + line.split("#", 1)[1].rstrip()) if "#" in line else ""
        out.append(pat + comment)
        if set(pat.partition(".")[2]) <= {"*", "?"}:
            warnings.append(f"{pat} blocks every entity of that domain that is not on your dashboards")
    while out and not out[-1]:
        out.pop()
    return "\n".join(out) + "\n", converted, errors, warnings


def ensure_exclude_file(path):
    """Create the exclude file (with a generic template) in the add-on's own config folder if missing."""
    if not path:
        return
    try:
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            atomic_write(path, EXCLUDE_TEMPLATE)
            log(f"exclude file  {path} did not exist: created it with generic examples")
    except OSError as exc:
        warn(f"cannot create exclude file {path}: {exc}")


def read_exclude(path):
    """(text, exists)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read(), True
    except (OSError, UnicodeDecodeError):
        return "", False


def effective_users(app):
    s = app["settings"].data
    names = {u.lower() for u in s["users"]} if s["scope"] == "users" else set()
    return names | {u.strip().lower() for u in app["args"].user if u.strip()}


# ----------------------------------------------------------------------------- warnings
def compute_warnings(app):
    """Configuration problems a human should know about. [{level, text}], level warn|info."""
    w = []
    s = app["settings"].data
    found = {d["key"]: d for d in discover_dashboards(app["config_dir"])}
    if not s["dashboards"] and not app["args"].dashboard:
        w.append(("warn", "No dashboard selected. Nothing is protected: entities on your wall panel dashboard can be "
                          "blocked by the exclude list. Open the web UI and select the dashboard(s) your wall panel shows."))
    heavy = collections.Counter()
    for key in s["dashboards"]:
        d = found.get(key)
        if d is None:
            w.append(("warn", f"Selected dashboard “{key}” no longer exists in Home Assistant."))
        elif not d["exists"]:
            w.append(("warn", f"Dashboard “{d['title']}” has no saved configuration yet (auto-generated). "
                              f"It shows ALL entities, so the filter cannot know which ones are needed. "
                              f"Take control of the dashboard (⋮ → Edit → Take control) and save it."))
    for e in app["allow"].exact:
        dom = e.partition(".")[0]
        if dom in HEAVY_DOMAINS and "." in e:
            heavy[dom] += 1
    for dom, n in sorted(heavy.items()):
        w.append(("warn", f"Selected dashboard(s) contain {n} {dom}.* entit{'y' if n == 1 else 'ies'}. "
                          f"These can update very often and are always passed through; avoid them on a weak panel."))
    users = discover_users(app["config_dir"])
    ep = app["exclude_path"]
    if ep and app["allow"].mode == "exclude" and not os.path.isfile(ep):
        w.append(("warn", f"Exclude file \u201c{os.path.basename(ep)}\u201d could not be created in the add-on\u2019s config "
                          f"folder, so nothing is excluded yet. Check the add-on log."))
    if s["scope"] == "users" and not s["users"] and not app["args"].user:
        w.append(("warn", "No user selected: EVERY connection (phones, browsers, ...) is filtered. "
                          "Select the HA user the wall panel logs in with, or switch to \u201cdedicated port\u201d."))
    for u in (s["users"] if s["scope"] == "users" else []):
        if users and u.lower() not in {x.lower() for x in users}:
            w.append(("warn", f"Selected user “{u}” does not exist (renamed or deleted?). "
                              f"That user is NOT filtered."))
    if app["fwd"]["ok"] is False:
        w.append(("warn", "Home Assistant is not set up for reverse proxies, so it sees EVERY connection as coming from "
                          "this add-on (failed-login bans, 'local only' users and trusted networks cannot tell "
                          "clients apart). Add to configuration.yaml and restart Home Assistant:  http: "
                          "use_x_forwarded_for: true  trusted_proxies: [172.30.32.0/23]"))
    if not app["args"].local_only:
        w.append(("warn", "local_only is off: port 8124 accepts connections from public IP addresses. "
                          "Never port-forward it to the internet."))
    return [{"level": lv, "text": t} for lv, t in w]


def log_overlaps(app):
    for o in app["allow"].overlaps():
        log(f"exclude file  pattern {o['pattern']} also matches {o['count']} entities used on your dashboard(s) "
            f"- those stay visible: {', '.join(o['examples'])}")


def log_warnings(app):
    app["warnings"] = compute_warnings(app)
    for w in app["warnings"]:
        warn(w["text"])


# ----------------------------------------------------------------------------- user lookup
def user_matches(user, wanted):
    return bool(user) and (str(user.get("name", "")).lower() in wanted
                           or str(user.get("id", "")).lower() in wanted)


async def _whoami(app, token, headers=None):
    async with app["session"].ws_connect(app["up_ws"], max_msg_size=UP_MAX, headers=headers) as ws:
        await ws.receive_json()                                   # auth_required
        await ws.send_json({"type": "auth", "access_token": token})
        if (await ws.receive_json()).get("type") != "auth_ok":
            return None
        await ws.send_json({"id": 1, "type": "auth/current_user"})
        r = await ws.receive_json()
        return r.get("result") if r.get("success") else None


async def identify(app, token, headers=None):
    """Cached lookup of the HA user behind an access token (None = unknown -> fail open)."""
    key = hashlib.sha256(token.encode()).hexdigest()
    cache, now = app["user_cache"], time.time()
    hit = cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    try:
        user = await asyncio.wait_for(_whoami(app, token, headers), 10)
    except Exception as exc:                                      # noqa: BLE001 - fail open
        warn(f"user lookup failed ({type(exc).__name__}: {exc}); this connection is NOT filtered")
        return None
    if user:
        if len(cache) > 200:
            for k in [k for k, (t, _) in cache.items() if t <= now]:
                del cache[k]
        cache[key] = (now + 300, user)
    return user


# ----------------------------------------------------------------------------- health: failures + self-test
def note_fail(app, name, exc):
    """Count consecutive failures of a background job / the upstream. Logs the first, then at 5, 20, 100, 500..."""
    f = app["fail"].setdefault(name, {"streak": 0, "total": 0, "last": ""})
    f["streak"] += 1
    f["total"] += 1
    f["last"] = f"{type(exc).__name__}: {exc}"[:200]
    n = f["streak"]
    if n == 1 or n in (5, 20) or (n >= 100 and n % 400 == 100):
        warn(f"{name} failed {n}\u00d7 in a row: {f['last']}")


def note_ok(app, name):
    f = app["fail"].get(name)
    if f and f["streak"]:
        if f["streak"] >= 3:
            log(f"{name} recovered after {f['streak']} failures")
        f["streak"] = 0


async def selftest(app):
    """Startup / on-demand checks. Returns [{ok, text}] and stores it in app['selftest']."""
    args, out = app["args"], []

    def add(ok, text):
        out.append({"ok": bool(ok), "text": text})
    try:
        async with app["session"].get(app["upstream"] + "/manifest.json",
                                      timeout=aiohttp.ClientTimeout(total=10)) as r:
            add(r.status < 500, f"Home Assistant reachable at {app['upstream']} (HTTP {r.status})")
    except Exception as exc:                                  # noqa: BLE001
        add(False, f"Home Assistant NOT reachable at {app['upstream']}: {type(exc).__name__}: {exc}")
    st = os.path.join(args.config_dir, ".storage")
    add(os.access(st, os.R_OK), "Home Assistant .storage folder readable" if os.access(st, os.R_OK)
        else f"cannot read {st} (is the config folder mapped?)")
    dashes = discover_dashboards(args.config_dir)
    add(len(dashes) > 1 or dashes[0]["exists"], f"{len(dashes)} dashboard(s) found")
    sel = [k for k in app["settings"].data["dashboards"] if k not in {d["key"] for d in dashes}]
    if sel:
        add(False, f"selected dashboard(s) no longer exist: {', '.join(sel)}")
    ep = app["exclude_path"]
    if ep:
        ok = os.path.isfile(ep) and os.access(ep, os.R_OK | os.W_OK)
        add(ok, f"exclude file {os.path.basename(ep)} readable and writable" if ok
            else f"exclude file {ep} missing or not readable/writable")
    dd = os.path.dirname(app["settings"].path) or "."
    add(os.access(dd, os.W_OK), "add-on data folder writable" if os.access(dd, os.W_OK)
        else f"cannot write to {dd}: UI choices will be lost on restart")
    try:
        ver = tuple(int(x) for x in aiohttp.__version__.split(".")[:2])
    except ValueError:
        ver = (99, 0)
    add(ver >= (3, 8), f"aiohttp {aiohttp.__version__}" + ("" if ver >= (3, 8) else " is too old (3.8 or newer needed)"))
    bad = [o for o in out if not o["ok"]]
    app["selftest"] = {"at": int(time.time()), "checks": out}
    if bad:
        for o in bad:
            warn(f"self-test     {o['text']}")
        log(f"self-test     {len(out) - len(bad)}/{len(out)} checks OK, {len(bad)} need attention")
    else:
        log(f"self-test     all {len(out)} checks OK")
    return out


# ----------------------------------------------------------------------------- proxy
async def ws_proxy(request):
    app = request.app
    if len(app["clients"]) >= app["max_connections"]:
        app["health"]["refused"] += 1
        if time.time() - app["health"]["refused_at"] > 60:                  # one log line per minute at most
            app["health"]["refused_at"] = time.time()
            warn(f"too many websocket connections ({len(app['clients'])}, limit {app['max_connections']}): "
                 f"refusing {peer_of(request)}. Raise max_connections if you really use that many panels.")
        return web.Response(status=503, text="too many connections", headers={"Retry-After": "10"})
    client = web.WebSocketResponse(max_msg_size=WS_CLIENT_MAX, heartbeat=30)
    await client.prepare(request)
    sub_ids, seen = set(), set()
    last, pend = {}, {}                                   # throttling: last send time / held diffs per entity
    stats, ui = app["stats"], app["ui"]
    users = app["users"]
    st = {"filter": False, "user": None, "token": None, "ent": None}

    def start_filtering():
        if not st["filter"]:
            st["filter"] = True
            if not app["filtered"]:
                app["rearm"]["v"] = True
            app["filtered"].add(client)
            app["seen"]["filtered"] = time.time()

    if not users:
        start_filtering()                                 # no user selected: filter everybody
    app["clients"].add(client)
    peer, t_start = peer_of(request), time.time()
    conn = {"in": 0, "out": 0}
    log(f"ws connect    {peer} ua={request.headers.get('User-Agent', '?')[:80]!r}")
    fwd = forward_headers(request)
    reason = "closed"
    try:
        async with app["session"].ws_connect(app["up_ws"], max_msg_size=UP_MAX, heartbeat=30, headers=fwd) as up:
            note_ok(app, "Home Assistant connection")

            async def c2u():
                async for m in client:
                    if m.type == WSMsgType.TEXT:
                        if users and st["token"] is None and '"access_token"' in m.data[:300]:
                            try:
                                j = json.loads(m.data)
                                if j.get("type") == "auth" and isinstance(j.get("access_token"), str):
                                    st["token"] = j["access_token"]       # only used after HA has accepted it
                            except (ValueError, AttributeError):
                                pass
                        if "subscribe_entities" in m.data:
                            try:
                                j = json.loads(m.data)
                                if j.get("type") == "subscribe_entities":
                                    sub_ids.add(j["id"])
                                    st["ent"] = j["id"]
                                    log(f"ws subscribe  {peer} subscribe_entities id={j['id']}")
                            except (ValueError, KeyError, AttributeError):
                                pass
                        await up.send_str(m.data)
                    elif m.type == WSMsgType.BINARY:
                        await up.send_bytes(m.data)
                    else:
                        break

            def filter_msg(j):
                ev = j.get("event") if isinstance(j, dict) else None
                if not (st["filter"] and isinstance(ev, dict) and j.get("id") in sub_ids
                        and ("a" in ev or "c" in ev or "r" in ev)):
                    return j
                n_in = sum(len(ev.get(k, ())) for k in "acr")
                if "a" in ev:
                    app["known"].update(ev["a"])                  # all entity ids that exist in HA (for the UI lists)
                new = filter_event(ev, app["allow"], [app["counts"], ui["counts"]])
                thr = app["throttle"]
                if thr and new:
                    now = time.monotonic()
                    for e in new.get("a", ()):
                        if e in thr:
                            pend.pop(e, None)
                            last[e] = now
                    for e in new.get("r", ()):
                        pend.pop(e, None)
                        last.pop(e, None)
                    c = new.get("c")
                    if c:
                        for e in [x for x in c if x in thr]:
                            if now - last.get(e, -1e9) >= thr[e]:
                                if e in pend:
                                    c[e] = merge_diff(pend.pop(e), c[e])
                                last[e] = now
                            else:                                  # too soon: hold, merge, send later
                                pend[e] = merge_diff(pend.get(e), c.pop(e))
                        if not c:
                            del new["c"]
                n_out = sum(len(new.get(k, ())) for k in "acr")
                for d in (stats, ui):
                    d["in"] += n_in
                    d["out"] += n_out
                conn["in"] += n_in
                conn["out"] += n_out
                first = j["id"] not in seen
                seen.add(j["id"])
                if not new and not first:
                    return None
                j["event"] = new
                return j

            async def u2c():
                async for m in up:
                    if m.type == WSMsgType.TEXT:
                        data = m.data
                        if data[:40].replace(" ", "").startswith('{"type":"auth_'):
                            head = data[:40]
                            if '"auth_ok"' in head:
                                log(f"ws auth       {peer} OK")
                                if users and st["token"] and st["user"] is None:
                                    # HA accepted this token, so the extra lookup cannot trigger failed-login bans
                                    user = await identify(app, st["token"], fwd)
                                    st["user"], st["token"] = user or {}, None
                                    if user:
                                        hit = user_matches(user, users)
                                        log(f"ws user       {peer} {user.get('name')!r} -> "
                                            + ("FILTERED" if hit else "passthrough (not a selected user)"))
                                        if hit:
                                            start_filtering()
                                    else:
                                        log(f"ws user       {peer} unknown (lookup failed) -> passthrough")
                            elif '"auth_invalid"' in head:
                                log(f"ws auth       {peer} FAILED (auth_invalid)")
                        if st["filter"] and sub_ids and (data[:1] == "[" or '"event"' in data[:80]):
                            try:
                                j = json.loads(data)
                            except ValueError:
                                j = None
                            if isinstance(j, list):        # coalesced frame
                                out = [x for x in (filter_msg(x) for x in j) if x is not None]
                                if not out:
                                    continue
                                data = json.dumps(out, separators=(",", ":"))
                            elif isinstance(j, dict):
                                out = filter_msg(j)
                                if out is None:
                                    continue
                                data = json.dumps(out, separators=(",", ":"))
                        await client.send_str(data)
                    elif m.type == WSMsgType.BINARY:
                        await client.send_bytes(m.data)
                    else:
                        break

            async def flusher():
                """Send held (throttled) updates once their interval has passed."""
                try:
                    while True:
                        await asyncio.sleep(0.5)
                        if not pend or st["ent"] is None:
                            continue
                        now, thr, due = time.monotonic(), app["throttle"], {}
                        for e in list(pend):
                            if e not in thr or now - last.get(e, 0) >= thr[e]:
                                due[e] = pend.pop(e)
                                last[e] = now
                        if due:
                            for d in (stats, ui, conn):
                                d["out"] += len(due)
                            await client.send_str(json.dumps(
                                {"id": st["ent"], "type": "event", "event": {"c": due}}, separators=(",", ":")))
                except (ConnectionError, RuntimeError):
                    return

            tasks = [asyncio.ensure_future(c2u()), asyncio.ensure_future(u2c())]
            fl = asyncio.ensure_future(flusher())
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            fl.cancel()
            for t in pending:
                t.cancel()
            side = "client" if tasks[0] in done else "upstream"
            reason = f"{side} closed (client code={client.close_code}, upstream code={up.close_code})"
            for t in done:
                exc = None if t.cancelled() else t.exception()
                if exc is not None:
                    reason = f"{side} closed, then error: {type(exc).__name__}: {exc}"
                    if not isinstance(exc, (ConnectionError, aiohttp.ClientConnectionResetError)):
                        traceback.print_exception(exc)
    except aiohttp.ClientError as exc:
        reason = f"upstream error: {exc}"
        note_fail(app, "Home Assistant connection", exc)
    except ConnectionResetError as exc:
        reason = f"connection reset: {exc}"
    except asyncio.CancelledError:
        reason = "cancelled"
    finally:
        app["clients"].discard(client)
        app["filtered"].discard(client)
        await client.close()
        log(f"ws disconnect {peer} after {time.time() - t_start:.0f}s ({reason}); "
            f"{'filtered' if st['filter'] else 'passthrough'}; "
            f"entity updates in={conn['in']} forwarded={conn['out']}")
    return client


async def http_proxy(request):
    app = request.app
    raw = request.rel_url.raw_path_qs
    if not raw.startswith("/"):
        return web.Response(status=400, text="bad request target")
    url = app["upstream"] + raw
    headers = upstream_headers(request)
    body = request.content if request.can_read_body else None      # streamed: no buffering of big uploads
    peer = peer_of(request)
    path = request.path                       # never log the query string (may hold codes/tokens)
    resp = None
    try:
        async with app["session"].request(
                request.method, url, headers=headers, data=body,
                allow_redirects=False, auto_decompress=False) as r:
            note_ok(app, "Home Assistant connection")
            resp = web.StreamResponse(status=r.status, reason=r.reason)
            for k, v in r.headers.items():
                if k.lower() not in HOP:
                    resp.headers.add(k, v)
            await resp.prepare(request)
            async for chunk in r.content.iter_chunked(65536):
                await resp.write(chunk)
            await resp.write_eof()
            if VERBOSE or r.status >= 400 or path.startswith(LOGIN_PATHS):
                tag = "login" if path.startswith(LOGIN_PATHS) else "http "
                log(f"{tag}         {peer} {request.method} {path} -> {r.status}")
            return resp
    except ConnectionError as exc:
        if VERBOSE:
            log(f"http          {peer} {request.method} {path} client aborted ({type(exc).__name__})")
        return resp if resp is not None else web.Response(status=499)
    except aiohttp.ClientError as exc:
        note_fail(app, "Home Assistant connection", exc)
        log(f"http          {peer} {request.method} {path} -> 502 upstream error: {exc}")
        return web.Response(status=502, text=f"upstream error: {exc}")


async def handler(request):
    app = request.app
    if app["args"].local_only:
        ip = _ip(request.remote)
        if ip is None or not (ip.is_private or ip.is_loopback or ip.is_link_local):
            if time.time() - app["blocked_at"] > 60:                    # one log line per minute at most
                app["blocked_at"] = time.time()
                warn(f"refused a connection from public address {request.remote} (local_only is on)")
            return web.Response(status=403, text="forbidden")
    if request.path == "/__health":
        return web.json_response({"status": "ok"})
    if request.path == "/api/websocket" and request.headers.get("Upgrade", "").lower() == "websocket":
        return await ws_proxy(request)
    return await http_proxy(request)


# ----------------------------------------------------------------------------- housekeeping
def resolve_dashboards(app):
    """Files of the selected dashboards (+ --dashboard from the command line)."""
    found = {d["key"]: d["file"] for d in discover_dashboards(app["config_dir"])}
    return [found[k] for k in app["settings"].data["dashboards"] if k in found] + list(app["args"].dashboard)


async def apply_changes(app, close_all=False):
    """Re-read dashboards/exclude file; make connected panels reconnect if the filter changed."""
    allow = app["allow"]
    changed = allow.set_dashboards(resolve_dashboards(app)) if allow.dashboards != resolve_dashboards(app) \
        else allow.reload()
    if changed or close_all:
        targets = list(app["clients"] if close_all else app["filtered"])
        log(f"filter changed: {len(allow.exact)} dashboard entities, {len(allow.wild)} dashboard wildcards, "
            f"{len(allow.excl_pats)} exclude patterns; reconnecting {len(targets)} client(s)")
        log_overlaps(app)
        for c in targets:                     # frontend reconnects and resubscribes -> fresh full state
            await c.close(code=1012, message=b"filter changed")
    return changed


async def forward_prober(app):
    """Probe at startup, then every minute until it works (HA may start later than this add-on)."""
    while True:
        try:
            await probe_forwarding(app)
            note_ok(app, "forwarding probe")
        except Exception as exc:                          # noqa: BLE001
            note_fail(app, "forwarding probe", exc)
        await asyncio.sleep(60 if not app["fwd"]["ok"] else 900)


async def reloader(app, every):
    while True:
        await asyncio.sleep(every)
        try:
            await apply_changes(app)
            note_ok(app, "reload")
        except Exception as exc:                          # noqa: BLE001 - never let the loop die
            note_fail(app, "reload", exc)


async def report(app, every, top, fast_count, slow_every):
    """Per-minute reports for the first `fast_count` reports after startup or after a panel
    (re)connects from idle, then one report per `slow_every` seconds."""
    fast_left = fast_count
    active = elapsed = 0
    ui = app["ui"]
    while True:
        for _ in range(every):
            await asyncio.sleep(1)
            if app["filtered"]:
                active += 1
                ui["secs"] += 1
                if ui["secs"] >= 1800:                    # decay: the UI shows roughly the last 15-30 min
                    ui["secs"] //= 2
                    ui["in"] //= 2
                    ui["out"] //= 2
                    for k in list(ui["counts"]):
                        ui["counts"][k] //= 2
                        if not ui["counts"][k]:
                            del ui["counts"][k]
            if app["rearm"]["v"]:
                app["rearm"]["v"] = False
                fast_left = fast_count
        elapsed += every
        slow = fast_left <= 0
        if slow and elapsed < slow_every:
            continue
        if not active:
            elapsed = 0
            continue
        s, counts, allow = app["stats"], app["counts"], app["allow"]
        unit, factor = ("hr", 3600) if slow else ("min", 60)

        def rate(n):
            return n * factor / active

        tag = "hourly" if slow else f"{fast_count - fast_left + 1}/{fast_count}"
        log(f"stats {tag:<7} entity updates in={s['in']} forwarded={s['out']} "
            f"dropped={s['in'] - s['out']} clients={len(app['filtered'])} "
            f"(last {elapsed}s, connected {active}s)")
        if counts:
            rows = counts.most_common()
            heavy = [(e, n * 60 / active) for e, n in rows if allow.protected(e)
                     and e not in app["throttle"] and n * 60 / active >= app["opts"]["heavy_per_minute"]]
            for e, r in heavy[:10]:
                warn(f"heavy dashboard entity: {e} updates {r:.0f}x/min and always passes the filter. "
                     f"Remove it from the wall panel dashboard if the panel feels slow.")
        if top and counts:
            dropped = [(e, n) for e, n in rows if not allow(e)]
            keep = [(e, n) for e, n in rows if allow(e)]
            protected = [(e, n) for e, n in keep if allow.protected(e)]
            cand = [(e, n) for e, n in keep if not allow.protected(e)]
            if allow.mode == "exclude":
                src = ", ".join(os.path.basename(f) for f in allow.exclude_files) or "exclude patterns"
            else:
                src = "include mode (not on a selected dashboard)"
            log(f"~{rate(sum(n for _, n in dropped)):.1f}/{unit} [dropped] {len(dropped)} entities from {src}")
            thr = app["opts"]["min_per_hour" if slow else "min_per_minute"]

            def block(title, items, mark):
                shown = [(e, n) for e, n in items if rate(n) >= thr][:top]
                hidden = len(items) - len([1 for _, n in items if rate(n) >= thr])
                log(f"~{rate(sum(n for _, n in items)):.1f}/{unit} {title}: {len(items)} entities"
                    + (f" ({hidden} below {thr:g}/{unit} hidden)" if hidden else ""))
                for e, n in shown:
                    log(f"{rate(n):8.1f}/{unit}  {e}  [{mark}]")

            block("[passed] dashboard entities (always pass)", protected, "dashboard")
            block("[passed] not on a dashboard or exclude list (candidates for the exclude file)", cand, "passed")
            wild = [(k, c, n) for k, (c, n) in sorted(group_wildcards(cand).items(), key=lambda kv: -kv[1][1])
                    if rate(n) >= thr]
            if wild:
                log("suggested wildcards for the candidates above:")
                for k, c, n in wild[:top]:
                    log(f"{rate(n):8.1f}/{unit}  {k}  [{c} entities]")
        if not slow:
            fast_left -= 1
            if fast_left == 0:
                log("stats         per-minute reports done; from now one report per hour "
                    "(a panel reconnecting after idle re-enables per-minute reports)")
        s["in"] = s["out"] = 0
        counts.clear()
        active = elapsed = 0


# ----------------------------------------------------------------------------- web UI
def build_state(app):
    allow, ui, s = app["allow"], app["ui"], app["settings"].data
    secs = max(ui["secs"], 1)
    rows = ui["counts"].most_common()
    thr = app["opts"]["heavy_per_minute"]
    cand = [(e, n) for e, n in rows if allow(e) and not allow.protected(e)]
    dropped = [(e, n) for e, n in rows if not allow(e)]
    thrott = app["throttle"]
    heavy = [{"entity": e, "rate": round(n * 60 / secs, 1)} for e, n in rows
             if allow.protected(e) and n * 60 / secs >= thr and e not in thrott]
    in_rate = dict(rows)
    busy = [{"entity": e, "rate": round(n * 60 / secs, 1), "protected": allow.protected(e), "seconds": thrott.get(e, 0)}
            for e, n in [r for r in rows if allow(r[0])][:15] if n * 60 / secs >= 0.5]
    min_rate = 1.0
    wild = sorted(group_wildcards(cand).items(), key=lambda kv: -kv[1][1])
    ago = None if not app["seen"]["filtered"] else int(time.time() - app["seen"]["filtered"])
    return {
        "version": VERSION,
        "mode": allow.mode,
        "panel_port": app["args"].listen.rpartition(":")[2],
        "settings": s,
        "dashboards": [{k: d[k] for k in ("key", "title", "url_path", "exists")}
                       for d in discover_dashboards(app["config_dir"])],
        "users": discover_users(app["config_dir"]),
        "warnings": app["warnings"],
        "selftest": app.get("selftest"),
        "health": {"refused": app["health"]["refused"], "max_connections": app["max_connections"],
                   "failures": {k: v for k, v in app["fail"].items() if v["total"]}},
        "heavy": heavy,
        "busy": busy,
        "throttled": [{"entity": e, "seconds": v, "rate": round(in_rate.get(e, 0) * 60 / secs, 1)}
                      for e, v in sorted(thrott.items())],
        "status": {
            "clients": len(app["clients"]), "filtered": len(app["filtered"]),
            "seconds_since_filtered": ago,
            "in_per_min": round(ui["in"] * 60 / secs, 1), "out_per_min": round(ui["out"] * 60 / secs, 1),
            "dashboard_entities": len(allow.exact), "exclude_patterns": len(allow.excl_pats),
            "measured_seconds": ui["secs"],
        },
        "exclude": {"name": os.path.basename(app["exclude_path"] or ""), "exists": bool(app["exclude_path"]) and os.path.isfile(app["exclude_path"])},
        "candidates": [{"entity": e, "rate": round(n * 60 / secs, 1)} for e, n in cand
                       if n * 60 / secs >= min_rate][:40],
        "wildcards": [{"pattern": k, "entities": c, "rate": round(n * 60 / secs, 1)}
                      for k, (c, n) in wild if n * 60 / secs >= min_rate and c > 1][:15],
        "dropped_per_min": round(sum(n for _, n in dropped) * 60 / secs, 1),
    }


def make_ui(app):
    page_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "index.html")

    recent = {"GET": collections.deque(), "POST": collections.deque()}

    @web.middleware
    async def guard(request, handler):
        if request.remote not in (INGRESS_GATEWAY, "127.0.0.1", "::1") and not app["args"].ui_open:
            return web.Response(status=403, text="Open this page from the Home Assistant sidebar.")
        kind = "POST" if request.method == "POST" else "GET"
        q, now = recent[kind], time.time()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= UI_LIMITS[kind]:                             # rate limit: a runaway tab cannot flood the add-on
            return web.json_response({"ok": False, "error": "too many requests, slow down"}, status=429,
                                     headers={"Retry-After": "10"})
        q.append(now)
        if request.method == "POST" and request.content_type != "application/json":
            return web.json_response({"ok": False, "error": "bad content type"}, status=415)
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception as exc:                                  # noqa: BLE001 - UI must never crash the proxy
            warn(f"UI error on {request.path}: {type(exc).__name__}: {exc}")
            return web.json_response({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status=500)

    async def index(_):
        with open(page_path, encoding="utf-8") as fh:
            html = fh.read().replace("__VERSION__", VERSION)
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def state(_):
        return web.json_response(build_state(app))

    async def body(request, limit=100):
        try:
            data = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="invalid JSON")
        return data

    async def set_dashboards(request):
        keys = (await body(request)).get("keys")
        known = {d["key"] for d in discover_dashboards(app["config_dir"])}
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            return web.json_response({"ok": False, "error": "keys must be a list"}, status=400)
        keep = [k for k in app["settings"].data["dashboards"] if k not in known and k in keys]  # keep stale pills removable
        keys = list(dict.fromkeys([k for k in keys if k in known] + keep))
        app["settings"].data["dashboards"] = keys
        app["settings"].save()
        changed = await apply_changes(app)
        log(f"settings      dashboards = {keys or 'none'}")
        log_warnings(app)
        return web.json_response({"ok": True, "changed": changed, "state": build_state(app)})

    async def set_users(request):
        names = (await body(request)).get("names")
        if not isinstance(names, list) or not all(isinstance(k, str) for k in names):
            return web.json_response({"ok": False, "error": "names must be a list"}, status=400)
        names = list(dict.fromkeys(n.strip()[:100] for n in names if n.strip()))[:20]
        app["settings"].data["users"] = names
        app["settings"].save()
        app["users"] = effective_users(app)
        log(f"settings      selected users = {names or 'none'}")
        log_warnings(app)
        await apply_changes(app, close_all=True)          # everybody re-identifies
        return web.json_response({"ok": True, "state": build_state(app)})

    async def set_scope(request):
        scope = (await body(request)).get("scope")
        if scope not in ("port", "users"):
            return web.json_response({"ok": False, "error": "scope must be port or users"}, status=400)
        app["settings"].data["scope"] = scope
        app["settings"].save()
        app["users"] = effective_users(app)
        log(f"settings      filter scope = {'everything on this port' if scope == 'port' else 'selected users'}")
        log_warnings(app)
        await apply_changes(app, close_all=True)
        return web.json_response({"ok": True, "state": build_state(app)})

    async def run_selftest(_):
        await selftest(app)
        return web.json_response({"ok": True, "state": build_state(app)})

    async def set_throttle(request):
        b = await body(request)
        entity, secs = b.get("entity"), b.get("seconds")
        if not (isinstance(entity, str) and ENTITY_ID_RE.match(entity)) or isinstance(secs, bool) \
                or not isinstance(secs, int) or not 0 <= secs <= MAX_THROTTLE:
            return web.json_response({"ok": False, "error": "need an entity id and 0-600 seconds"}, status=400)
        thr = app["settings"].data["throttle"]
        if secs == 0:
            thr.pop(entity, None)
        elif entity in thr or len(thr) < 100:
            thr[entity] = secs
        else:
            return web.json_response({"ok": False, "error": "at most 100 throttled entities"}, status=400)
        app["settings"].save()
        log(f"settings      throttle {entity} = {secs or 'off'}")
        return web.json_response({"ok": True, "state": build_state(app)})

    async def lists(request):
        kind = request.query.get("kind")
        allow, ui = app["allow"], app["ui"]
        secs, counts, known = max(ui["secs"], 1), ui["counts"], app["known"]
        if kind == "dashboard":
            items = [{"entity": e, "reason": r, "rate": round(counts.get(e, 0) * 60 / secs, 1),
                      "known": (e in known) if known else None} for e, r in sorted(allow.exact.items())]
            return web.json_response({"ok": True, "items": items, "wildcards": allow.wild,
                                      "known_count": sum(1 for i in items if i["known"]) if known else None})
        if kind == "exclude":
            items = []
            for pat in allow.excl_pats:
                hit = [(e, n) for e, n in counts.items() if fnmatch.fnmatchcase(e, pat) and not allow.protected(e)]
                items.append({"pattern": pat, "seen": len(hit),
                              "rate": round(sum(n for _, n in hit) * 60 / secs, 1)})
            return web.json_response({"ok": True, "items": items})
        return web.json_response({"ok": False, "error": "kind must be dashboard or exclude"}, status=400)

    async def get_exclude(_):
        path = app["exclude_path"]
        if not path:
            return web.json_response({"ok": False, "error": "no exclude file configured"}, status=404)
        ensure_exclude_file(path)
        text, exists = read_exclude(path)
        _, _, errors, warnings = normalize_exclude(text)
        return web.json_response({"ok": True, "text": text, "exists": exists, "template": EXCLUDE_TEMPLATE,
                                  "errors": errors, "warnings": warnings, "overlaps": app["allow"].overlaps()})

    async def put_exclude(request):
        path = app["exclude_path"]
        if not path:
            return web.json_response({"ok": False, "error": "no exclude file configured"}, status=404)
        text = (await body(request)).get("text")
        if not isinstance(text, str) or len(text) > 200_000:
            return web.json_response({"ok": False, "error": "text missing or too large"}, status=400)
        new, converted, errors, warnings = normalize_exclude(text)
        if errors:
            return web.json_response({"ok": False, "errors": errors}, status=400)
        backup = None
        if os.path.exists(path):
            backup = path + ".bak"
            shutil.copy(path, backup)
        atomic_write(path, new)
        changed = await apply_changes(app)
        n = len(app["allow"].excl_pats)
        log(f"settings      exclude file saved from the UI: {n} patterns, {converted} line(s) converted")
        for wmsg in warnings:
            warn(f"exclude file: {wmsg}")
        return web.json_response({"ok": True, "text": new, "converted": converted, "warnings": warnings,
                                  "patterns": n, "changed": changed, "backup": os.path.basename(backup or ""),
                                  "overlaps": app["allow"].overlaps()})

    async def explain(request):
        entity = request.query.get("entity", "").strip().lower()
        if not ENTITY_ID_RE.match(entity):
            return web.json_response({"ok": False, "error": "enter an entity id such as sensor.example_temperature"}, status=400)
        passes, why = app["allow"].explain(entity)
        return web.json_response({"ok": True, "entity": entity, "passes": passes, "reason": why})

    async def normalize(request):
        """Clean up lines you want to add (nothing is written anywhere)."""
        text = (await body(request)).get("text")
        if not isinstance(text, str) or len(text) > 200_000:
            return web.json_response({"ok": False, "error": "text missing or too large"}, status=400)
        new, converted, errors, warnings = normalize_exclude(text)
        return web.json_response({"ok": not errors, "text": new, "converted": converted,
                                  "errors": errors, "warnings": warnings})

    async def secure_headers(_, response):
        response.headers.update({
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                       "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'"})

    ui = web.Application(middlewares=[guard], client_max_size=300_000)
    ui.on_response_prepare.append(secure_headers)
    ui.router.add_get("/", index)
    ui.router.add_get("/api/state", state)
    ui.router.add_post("/api/dashboards", set_dashboards)
    ui.router.add_post("/api/users", set_users)
    ui.router.add_post("/api/scope", set_scope)
    ui.router.add_post("/api/throttle", set_throttle)
    ui.router.add_get("/api/exclude", get_exclude)
    ui.router.add_post("/api/exclude", put_exclude)
    ui.router.add_post("/api/exclude/normalize", normalize)
    ui.router.add_get("/api/explain", explain)
    ui.router.add_get("/api/list", lists)
    ui.router.add_post("/api/selftest", run_selftest)
    return ui


# ----------------------------------------------------------------------------- app setup
async def make_app(args):
    settings = Settings(os.path.join(args.data_dir, "settings.json"))
    if settings.prev_version and settings.prev_version != VERSION:
        log(f"update        updated from {settings.prev_version} to {VERSION}; your dashboards, scope, throttles "
            f"and exclude file are kept")
    try:
        settings.save()                                   # records the running version
    except OSError as exc:
        warn(f"cannot write settings to {settings.path}: {exc}")
    exclude_path = args.exclude_file[0] if args.exclude_file else None
    ensure_exclude_file(exclude_path)
    up = urlsplit(args.upstream)
    app = web.Application(client_max_size=1024)   # bodies are streamed, never buffered
    app["args"], app["settings"], app["config_dir"] = args, settings, args.config_dir
    app["exclude_path"] = exclude_path
    app["opts"] = {"min_per_minute": args.min_per_min, "min_per_hour": args.min_per_hr,
                   "heavy_per_minute": args.heavy_per_min}
    app["upstream"] = args.upstream.rstrip("/")
    app["up_host"] = up.netloc
    app["up_ws"] = ("wss" if up.scheme == "https" else "ws") + "://" + up.netloc + "/api/websocket"
    app["stats"] = {"in": 0, "out": 0}
    app["ui"] = {"in": 0, "out": 0, "secs": 0, "counts": collections.Counter()}
    app["seen"] = {"filtered": 0}
    app["clients"], app["filtered"] = set(), set()
    app["users"] = effective_users(app)
    app["user_cache"] = {}
    app["known"] = set()
    app["throttle"] = settings.data["throttle"]        # entity id -> minimum seconds between updates
    app["blocked_at"] = 0
    app["max_connections"] = args.max_connections
    app["health"] = {"refused": 0, "refused_at": 0}
    app["fail"] = {}
    app["fwd"] = {"ok": None}                         # None = not probed yet, True/False after the probe
    app["trusted_nets"] = []
    for net in args.trusted_proxy:
        try:
            app["trusted_nets"].append(ipaddress.ip_network(net.strip(), strict=False))
        except ValueError:
            warn(f"ignoring invalid trusted proxy address {net!r}")
    app["rearm"] = {"v": False}
    app["counts"] = collections.Counter()
    app["warnings"] = []
    app["allow"] = Allow([], args.allow, args.mode, args.exclude, args.exclude_file, args.config_dir)
    app["allow"].set_dashboards(resolve_dashboards(app))
    app["session"] = aiohttp.ClientSession(auto_decompress=False,
                                           timeout=aiohttp.ClientTimeout(total=None, sock_connect=10))
    app.router.add_route("*", "/{tail:.*}", handler)

    async def start_bg(a):
        asyncio.ensure_future(selftest(a))
        a["bg"] = [asyncio.ensure_future(forward_prober(a)),
                   asyncio.ensure_future(report(a, args.report, args.top, args.fast_count, args.slow_report)),
                   asyncio.ensure_future(reloader(a, args.reload))]

    async def stop_bg(a):
        for t in a["bg"]:
            t.cancel()
        await a["session"].close()

    app.on_startup.append(start_bg)
    app.on_cleanup.append(stop_bg)
    log(f"Proxyfilter for photo/wallpanel {VERSION}")
    log(f"mode          {args.mode}; dashboard entities that always pass: {len(app['allow'].exact)}; "
        f"exclude patterns: {len(app['allow'].excl_pats)}")
    log("filtered for  " + (f"users {sorted(app['users'])} (everybody else: passthrough)"
                           if app["users"] else "every connection on this port (dedicated panel port)"))
    log(f"listening     proxy {args.listen} -> {args.upstream}; web UI {args.ui_listen}")
    log_overlaps(app)
    log_warnings(app)
    return app


def apply_options(args, path):
    """Apply the add-on configuration (/data/options.json) to the parsed arguments."""
    with open(path, encoding="utf-8") as fh:
        o = json.load(fh)
    base = os.path.realpath(args.exclude_dir)

    def under(rel):
        full = os.path.realpath(os.path.join(base, rel.strip().lstrip("/")))
        if full != base and not full.startswith(base + os.sep):
            raise SystemExit(f"path outside the add-on config folder is not allowed: {rel!r}")
        return full

    for key, attr in (("upstream", "upstream"), ("mode", "mode")):
        if o.get(key):
            setattr(args, attr, o[key])
    if o.get("exclude_file"):
        args.exclude_file.append(under(o["exclude_file"]))
    for key, attr in (("min_per_minute", "min_per_min"), ("min_per_hour", "min_per_hr"),
                      ("heavy_per_minute", "heavy_per_min")):
        if o.get(key) is not None:
            setattr(args, attr, float(o[key]))
    if o.get("top") is not None:
        args.top = int(o["top"])
    if o.get("max_connections") is not None:
        args.max_connections = int(o["max_connections"])
    if o.get("verbose"):
        args.verbose = True
    if o.get("local_only") is not None:
        args.local_only = bool(o["local_only"])
    args.trusted_proxy += [str(x) for x in (o.get("trusted_proxies") or [])]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", default=None, help="e.g. http://homeassistant:8123")
    ap.add_argument("--options", help="add-on options.json")
    ap.add_argument("--config-dir", default="/homeassistant", help="HA config folder")
    ap.add_argument("--data-dir", default="/data", help="where the UI settings are stored")
    ap.add_argument("--listen", default="0.0.0.0:8124", help="proxy address")
    ap.add_argument("--exclude-dir", default="/config", help="the add-on's own config folder (mapped read-only)")
    ap.add_argument("--local-only", dest="local_only", action="store_true", default=True,
                    help="refuse connections from public IP addresses (default)")
    ap.add_argument("--allow-public", dest="local_only", action="store_false",
                    help="also accept connections from public IP addresses (not recommended)")
    ap.add_argument("--trusted-proxy", action="append", default=[],
                    help="CIDR of a reverse proxy in front of this one whose X-Forwarded-For is honoured")
    ap.add_argument("--ui-listen", default="0.0.0.0:8099", help="web UI address (ingress)")
    ap.add_argument("--ui-open", action="store_true", help="allow the web UI from any address (testing only)")
    ap.add_argument("--mode", choices=["include", "exclude"], default="exclude")
    ap.add_argument("--exclude-file", action="append", default=[], help="exclude patterns file (read-only; you create and edit it)")
    ap.add_argument("--exclude", action="append", default=[], help="extra fnmatch pattern to drop")
    ap.add_argument("--allow", action="append", default=[], help="extra fnmatch pattern that always passes")
    ap.add_argument("--dashboard", action="append", default=[], help="extra lovelace JSON file to scan")
    ap.add_argument("--user", action="append", default=[], help="extra HA user (name or id) to filter")
    ap.add_argument("--min-per-min", type=float, default=2.0)
    ap.add_argument("--min-per-hr", type=float, default=120.0)
    ap.add_argument("--max-connections", type=int, default=DEFAULT_MAX_CONNECTIONS,
                    help="maximum simultaneous websocket connections through the proxy")
    ap.add_argument("--heavy-per-min", type=float, default=20.0, help="warn for dashboard entities above this rate")
    ap.add_argument("--fast-count", type=int, default=10)
    ap.add_argument("--slow-report", type=int, default=3600)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--report", type=int, default=60)
    ap.add_argument("--reload", type=int, default=30)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.options:
        apply_options(args, args.options)
    if not args.upstream:
        ap.error("upstream is required (--upstream or the add-on option)")
    return args


async def start_servers(args):
    """Start proxy + UI. Returns (runners, proxy_app)."""
    apply_timezone(args.config_dir)
    app = await make_app(args)
    runners = []
    for application, addr in ((app, args.listen), (make_ui(app), args.ui_listen)):
        runner = web.AppRunner(application, access_log=None)
        await runner.setup()
        host, _, port = addr.rpartition(":")
        await web.TCPSite(runner, host or "0.0.0.0", int(port)).start()
        runners.append(runner)
    return runners, app


async def amain(args):
    global VERBOSE
    VERBOSE = args.verbose
    runners, papp = await start_servers(args)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()
    log("stopping      closing connections")
    # Close open panel connections first and never wait long: Supervisor kills the container after ~10 s,
    # which Home Assistant reports as an add-on error.
    for c in list(papp["clients"]):
        try:
            await asyncio.wait_for(c.close(code=1001, message=b"add-on stopping"), 1)
        except Exception:                                  # noqa: BLE001
            pass
    for r in runners:
        try:
            await asyncio.wait_for(r.cleanup(), 3)
        except Exception:                                  # noqa: BLE001
            pass
    log("stopped")


def main():
    try:
        asyncio.run(amain(parse_args()))
    except KeyboardInterrupt:
        pass
    sys.stdout.flush()
    os._exit(0)                                           # clean exit code even if a stray task lingers


if __name__ == "__main__":
    main()
