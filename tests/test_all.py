"""End-to-end tests against a mock Home Assistant. Run:  python3 tests/test_all.py   (needs aiohttp)

All entity names, dashboards and users below are generic examples.
"""
import asyncio
import importlib.util
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile

import aiohttp
from aiohttp import web

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("wf", ROOT / "proxyfilter_wallpanel" / "app" / "proxyfilter_wallpanel.py")
wf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wf)

TOKENS = {"tok-panel": {"id": "u1", "name": "Wall Panel"}, "tok-alice": {"id": "u2", "name": "Alice"}}
PROXY, UI, MOCK = 18124, 18099, 18123
passed = []
STRICT = {"v": False}      # mock HA refuses X-Forwarded-For (not set up for reverse proxies)
SEEN = {"ws_xff": [], "ws_count": 0}
REAL_OUT = sys.stdout
LOG = io.StringIO()


class Tee:
    def write(self, t):
        LOG.write(t)

    def flush(self):
        pass


def check(cond, name):
    print(("PASS " if cond else "FAIL ") + name, file=REAL_OUT)
    passed.append(bool(cond))


# ---------------------------------------------------------------- fake HA config folder
def make_config(tmp):
    st = pathlib.Path(tmp, ".storage")
    st.mkdir(parents=True)
    (st / "lovelace_dashboards").write_text(json.dumps({"data": {"items": [
        {"id": "wall_panel", "url_path": "wall-panel", "title": "Wall panel"},
        {"id": "garage", "url_path": "garage", "title": "Garage"},
        {"id": "../evil", "url_path": "x", "title": "Evil"}]}}))
    (st / "lovelace.wall_panel").write_text(json.dumps({"data": {"config": {"views": [{"cards": [
        {"type": "entities", "entities": ["sensor.example_living_temp", "light.example_lamp", "camera.example_door",
                                           "sensor.air_mini_pm25"]},
        {"type": "area", "area": "living"},
        {"type": "tile", "tap_action": {"action": "call-service", "target": {"device_id": "dev_kitchen"}}},
        {"type": "custom:auto-entities", "filter": {"include": [{"entity_id": "sensor.example_wild_*"}]}}]}]}}}))
    (st / "core.entity_registry").write_text(json.dumps({"data": {"entities": [
        {"entity_id": "sensor.air_mini_co2", "device_id": "dev_air", "area_id": "living"},
        {"entity_id": "sensor.air_monitor_pm25", "device_id": "dev_monitor", "area_id": None},
        {"entity_id": "sensor.example_kitchen_temp", "device_id": "dev_kitchen", "area_id": None}]}}))
    (st / "core.device_registry").write_text(json.dumps({"data": {"devices": [
        {"id": "dev_air", "area_id": "living"}, {"id": "dev_monitor", "area_id": "office"}, {"id": "dev_kitchen", "area_id": None}]}}))
    (st / "auth").write_text(json.dumps({"data": {"users": [
        {"name": "Wall Panel", "is_active": True, "system_generated": False},
        {"name": "Alice", "is_active": True, "system_generated": False},
        {"name": "Supervisor", "is_active": True, "system_generated": True}]}}))
    (st / "core.config").write_text(json.dumps({"data": {"time_zone": "Europe/Amsterdam"}}))


# ---------------------------------------------------------------- mock HA websocket
async def manifest(request):
    if STRICT["v"] and "X-Forwarded-For" in request.headers:
        return web.Response(status=400, text="reverse proxy not set up")
    return web.json_response({})


async def echo(request):
    n = 0
    async for chunk in request.content.iter_chunked(65536):
        n += len(chunk)
    return web.json_response({"xff": request.headers.get("X-Forwarded-For"), "bytes": n,
                              "xrip": request.headers.get("X-Real-IP")})


async def mock_ws(request):
    SEEN["ws_xff"].append(request.headers.get("X-Forwarded-For"))
    SEEN["ws_count"] += 1
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(request)
    await ws.send_str(json.dumps({"type": "auth_required"}))
    a = await ws.receive_json()
    user = TOKENS.get(a.get("access_token"))
    if not user:
        await ws.send_str(json.dumps({"type": "auth_invalid"}))
        return ws
    await ws.send_str(json.dumps({"type": "auth_ok"}))
    async for m in ws:
        j = json.loads(m.data)
        if j["type"] == "auth/current_user":
            await ws.send_str(json.dumps({"id": j["id"], "type": "result", "success": True, "result": user}))
        elif j["type"] == "subscribe_entities":
            i = j["id"]
            await ws.send_str(json.dumps({"id": i, "type": "result", "success": True, "result": None}))
            await ws.send_str(json.dumps({"id": i, "type": "event", "event": {"a": {
                "sensor.example_living_temp": {"s": "21", "a": {}}, "sensor.example_inverter_power": {"s": "5", "a": {}},
                "sensor.example_meter_l1": {"s": "1", "a": {}}, "sun.sun": {"s": "up", "a": {}}}}}))
            for n in range(30):
                await ws.send_str(json.dumps({"id": i, "type": "event", "event": {"c": {
                    "sensor.example_inverter_power": {"+": {"s": str(n)}},
                    "sensor.example_meter_l1": {"+": {"s": str(n)}},
                    "camera.example_door": {"+": {"s": str(n)}}}}}))
            await ws.send_str(json.dumps([{"id": i, "type": "event", "event": {"c": {"sensor.example_inverter_power": {"+": {"s": "x"}}}}},
                                          {"id": i, "type": "event", "event": {"c": {"sensor.example_living_temp": {"+": {"s": "22"}}}}}]))
            await ws.send_str(json.dumps({"id": i, "type": "event", "event": {"c": {"sensor.example_living_temp": {"+": {"s": "23"}}}}}))
    return ws


async def collect(token, wait=1.0):
    """Connect as `token`, return every entity id received."""
    seen = set()
    async with aiohttp.ClientSession() as s:
        ws = await s.ws_connect(f"http://127.0.0.1:{PROXY}/api/websocket")
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        if (await ws.receive_json())["type"] != "auth_ok":
            return None
        await ws.send_json({"id": 3, "type": "subscribe_entities"})
        t_end = asyncio.get_event_loop().time() + wait
        while asyncio.get_event_loop().time() < t_end:
            try:
                m = await ws.receive(timeout=0.3)
            except asyncio.TimeoutError:
                continue
            if m.type != aiohttp.WSMsgType.TEXT:
                break
            j = json.loads(m.data)
            for x in (j if isinstance(j, list) else [j]):
                ev = x.get("event") or {}
                for k in "ac":
                    seen |= set(ev.get(k, {}))
        await ws.close()
    return seen


async def jget(s, path):
    async with s.get(f"http://127.0.0.1:{UI}/{path}") as r:
        return r.status, await r.json()


async def jpost(s, path, body):
    async with s.post(f"http://127.0.0.1:{UI}/{path}", json=body) as r:
        return r.status, await r.json()


async def main():
    tmp = tempfile.mkdtemp()
    cfg, data = os.path.join(tmp, "config"), os.path.join(tmp, "data")
    make_config(cfg)
    os.makedirs(data)
    os.makedirs(os.path.join(tmp, "addon_config"))

    # ---- unit: patterns, normalising, discovery
    check(wf.parse_pattern_line("[2026-01-01 10:00:00]   19.0/min  sensor.example_x  [passed]") == "sensor.example_x", "parse pasted log line")
    check(wf.parse_pattern_line("# sensor.example_x") is None, "comment line ignored")
    text, conv, errs, warns = wf.normalize_exclude("# c\n  19.0/min  sensor.example_a  [passed]\nsensor.example_b_*  # keep\n\n")
    check(conv == 1 and not errs and "sensor.example_a\n" in text and "sensor.example_b_*  # keep" in text, "normalize converts pasted lines, keeps comments")
    check(bool(wf.normalize_exclude("hello world")[2]), "garbage line is rejected")
    check(bool(wf.normalize_exclude("sensor.*")[3]), "very broad pattern gives a warning")
    d = wf.discover_dashboards(cfg)
    check([x["key"] for x in d] == ["lovelace", "wall_panel", "garage"], "dashboards discovered, unsafe id ignored")
    check(wf.discover_users(cfg) == ["Alice", "Wall Panel"], "users discovered, system user hidden")

    al = wf.Allow([os.path.join(cfg, ".storage", "lovelace.wall_panel")], [], "exclude", ["sensor.air_*"], [], cfg)
    check(al("sensor.air_mini_pm25") and "listed on dashboard" in al.explain("sensor.air_mini_pm25")[1],
          "exclude sensor.air_* does NOT block an air_mini entity listed on the dashboard")
    check(al("sensor.air_mini_co2") and "area (living)" in al.explain("sensor.air_mini_co2")[1],
          "entities of an area used on the dashboard are protected (via the registry)")
    check(al("sensor.example_kitchen_temp") and "device" in al.explain("sensor.example_kitchen_temp")[1],
          "entities of a device used on the dashboard are protected")
    check("sensor.example_wild_" not in al.exact, "a wildcard on the dashboard does not leave a fake entity behind")
    check(al("sensor.example_wild_anything") and "wildcard" in al.explain("sensor.example_wild_anything")[1],
          "dashboard wildcards (auto-entities) protect matching entities")
    check(not al("sensor.air_monitor_pm25") and "exclude pattern sensor.air_*" in al.explain("sensor.air_monitor_pm25")[1],
          "air_monitor is blocked by sensor.air_*, with the reason")
    check(al.overlaps() and al.overlaps()[0]["pattern"] == "sensor.air_*" and al.overlaps()[0]["count"] >= 2,
          "overlap report: the pattern also matches dashboard entities that stay visible")

    md = wf.merge_diff
    m = md({"+": {"s": "1", "a": {"x": 1, "y": 2}}, "-": {"a": ["z"]}}, {"+": {"s": "2", "a": {"x": 5, "z": 9}}, "-": {"a": ["y"]}})
    check(m == {"+": {"s": "2", "a": {"x": 5, "z": 9}}, "-": {"a": ["y"]}}, f"merge_diff keeps the latest value and attribute removals ({m})")
    check(md(None, {"+": {"s": "3"}}) == {"+": {"s": "3"}}, "merge_diff with nothing held")

    # ---- start mock HA + add-on
    mock = web.Application()
    mock.router.add_get("/api/websocket", mock_ws)
    mock.router.add_get("/manifest.json", manifest)
    mock.router.add_route("*", "/echo", echo)
    mock._client_max_size = 0
    mr = web.AppRunner(mock, access_log=None)
    await mr.setup()
    await web.TCPSite(mr, "127.0.0.1", MOCK).start()
    optfile = os.path.join(tmp, "options.json")
    json.dump({"dashboards": [], "scope": "port", "users": []}, open(optfile, "w"))

    async def setopts(**o):
        json.dump(o, open(optfile, "w"))
        await asyncio.sleep(2.2)                       # the reloader runs every second

    args = wf.parse_args(["--upstream", f"http://127.0.0.1:{MOCK}", "--config-dir", cfg, "--data-dir", data,
                          "--listen", f"127.0.0.1:{PROXY}", "--ui-listen", f"127.0.0.1:{UI}",
                          "--exclude-file", os.path.join(tmp, "addon_config", "proxyfilter_exclude.txt"),
                          "--heavy-per-min", "5", "--report", "1", "--fast-count", "3", "--reload", "1",
                          "--options", os.path.join(tmp, "options.json")])
    runners, app = await wf.start_servers(args)
    buf = LOG
    exc_path = os.path.join(tmp, "addon_config", "proxyfilter_exclude.txt")
    check(os.path.exists(exc_path) and "Generic examples" in open(exc_path).read(), "exclude file is created in the add-on config folder when missing")
    check(os.environ.get("TZ") == "Europe/Amsterdam", "timezone taken from HA config")
    check("No dashboard selected" in buf.getvalue() and "No user selected" not in buf.getvalue(), "startup warns: no dashboard (default scope is the dedicated port, no user needed)")
    check("\033[38;5;208m" in buf.getvalue(), "warnings are orange")

    async with aiohttp.ClientSession() as s:
        st, j = await jget(s, "api/state")
        check(st == 200 and j["version"] and len(j["dashboards"]) == 3, "UI state endpoint")
        async with s.get(f"http://127.0.0.1:{UI}/") as r:
            html = await r.text()
        check(r.status == 200 and "Proxyfilter for photo/wallpanel" in html and "__VERSION__" not in html, "UI page served")
        async with s.post(f"http://127.0.0.1:{UI}/api/users", data="x=1") as r:
            check(r.status == 415, "POST without JSON content-type refused")

        # dedicated-port scope (default): every connection filtered, no user lookup at all
        count0 = SEEN["ws_count"]
        j0 = None
        async with s.get(f"http://127.0.0.1:{UI}/api/state") as r0:
            j0 = await r0.json()
        check(j0["settings"]["scope"] == "port", "default scope is the dedicated port")
        st, j = await jpost(s, "api/exclude", {"text": "sensor.example_inverter_*\n"})
        check(j["ok"], "exclude saved through the UI")
        got = await collect("tok-alice", 0.6)
        check("sensor.example_inverter_power" not in got and SEEN["ws_count"] - count0 == 1,
              "dedicated port: everybody filtered, no extra lookup connection to HA")
        for ep in ("api/scope", "api/dashboards", "api/users"):
            async with s.post(f"http://127.0.0.1:{UI}/{ep}", json={"scope": "users"}) as r:
                st = r.status
            check(st in (404, 405), f"{ep} no longer exists: dashboards/scope/users come from the add-on configuration")
        await setopts(dashboards=[], scope="users", users=[])
        st, j = await jget(s, "api/state")
        check(any("No user selected" in w["text"] for w in j["warnings"]), "users scope without a user: warning")
        await setopts(dashboards=["wall_panel", "../evil", "nope"], scope="port", users=[])
        st, j = await jget(s, "api/state")
        check(j["settings"]["dashboards"] == ["wall_panel"] and j["unknown_dashboards"] == ["../evil", "nope"],
              "configured dashboards resolved by URL name; unknown names reported")
        check(any("does not match any dashboard" in w["text"] for w in j["warnings"]), "warning for unknown dashboard name")
        check("camera.example_door" in app["allow"].exact, "dashboard entities loaded after a configuration change (no restart)")
        check(any("camera.* entity" in w["text"] for w in j["warnings"]), "static heavy warning (camera on dashboard)")
        check(not any("No dashboard selected" in w["text"] for w in j["warnings"]), "no-dashboard warning cleared")
        await setopts(dashboards=["WALL PANEL", "default"], scope="users", users=["wall panel"])
        st, j = await jget(s, "api/state")
        check(j["settings"]["dashboards"] == ["wall_panel", "lovelace"] and j["settings"]["users"] == ["wall panel"]
              and not j["unknown_dashboards"], "names are case-insensitive; 'default' = default dashboard; user taken over")
        check(app["users"] == {"wall panel"}, "user scope active after configuration change")
        await setopts(dashboards=["wall_panel"], scope="users", users=["wall panel"])
        check(not os.path.exists(os.path.join(data, "settings.json")) or "users" not in json.load(open(os.path.join(data, "settings.json"))),
              "dashboards/users are not persisted in /data (configuration is the single source)")

        # throttling a dashboard entity
        for bad in ({"entity": "../x", "seconds": 5}, {"entity": "camera.example_door", "seconds": 9999}, {"entity": "camera.example_door", "seconds": True}):
            st, j = await jpost(s, "api/throttle", bad)
            check(st == 400, f"invalid throttle refused {bad}")
        st, j = await jpost(s, "api/throttle", {"entity": "camera.example_door", "seconds": 2})
        check(j["ok"] and j["state"]["throttled"][0]["seconds"] == 2, "throttle set via UI")
        ev_count, last_state = 0, None
        async with aiohttp.ClientSession() as s3:
            ws = await s3.ws_connect(f"http://127.0.0.1:{PROXY}/api/websocket")
            await ws.receive_json(); await ws.send_json({"type": "auth", "access_token": "tok-panel"}); await ws.receive_json()
            await ws.send_json({"id": 3, "type": "subscribe_entities"})
            t_end = asyncio.get_event_loop().time() + 3.5
            while asyncio.get_event_loop().time() < t_end:
                try:
                    mm = await ws.receive(timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if mm.type != aiohttp.WSMsgType.TEXT:
                    break
                jj = json.loads(mm.data)
                for x in (jj if isinstance(jj, list) else [jj]):
                    c = (x.get("event") or {}).get("c", {})
                    if "camera.example_door" in c:
                        ev_count += 1
                        last_state = c["camera.example_door"]["+"]["s"]
            await ws.close()
        check(0 < ev_count <= 3 and last_state == "29", f"throttled entity: 30 updates became {ev_count}, final state delivered ({last_state})")
        await jpost(s, "api/throttle", {"entity": "camera.example_door", "seconds": 0})

        # exclude file editor
        st, j = await jpost(s, "api/exclude", {"text": "  12.0/min  sensor.example_inverter_power  [passed]\n"})
        check(j["ok"] and j["converted"] == 1 and os.path.exists(exc_path + ".bak"), "exclude saved, pasted log line converted, backup written")
        st, j = await jpost(s, "api/exclude", {"text": "this is not a pattern\n"})
        check(st == 400 and j["errors"], "invalid exclude refused")
        check("sensor.example_inverter_power" in open(exc_path).read(), "file unchanged after a refused save")
        st, j = await jget(s, "api/exclude")
        check(j["ok"] and j["exists"] and "sensor.example_inverter_power" in j["text"], "UI can read the file")
        st, j = await jpost(s, "api/exclude", {"text": "sensor.air_*\n"})
        check(j["ok"] and any(o["pattern"] == "sensor.air_*" for o in j["overlaps"]), "save reports patterns that overlap dashboard entities")
        st, j = await jget(s, "api/explain?entity=sensor.air_mini_pm25")
        check(j["ok"] and j["passes"] and "dashboard" in j["reason"], "explain endpoint: dashboard entity passes despite the pattern")
        st, j = await jget(s, "api/explain?entity=sensor.air_monitor_pm25")
        check(j["ok"] and not j["passes"], "explain endpoint: air_monitor blocked")
        st, j = await jget(s, "api/explain?entity=../etc")
        check(st == 400, "explain refuses invalid input")
        st, j = await jpost(s, "api/exclude", {"text": "sensor.example_inverter_power\n"})

        # filtering per user
        got = await collect("tok-panel")
        check(got is not None and "sensor.example_inverter_power" not in got and "sensor.example_living_temp" in got
              and "camera.example_door" in got and "sensor.example_meter_l1" in got,
              f"panel user filtered (excluded gone, dashboard kept, others pass): {sorted(got or [])}")
        got = await collect("tok-alice", 0.5)
        check("sensor.example_inverter_power" in got, "other user passes through unfiltered")
        check(await collect("tok-bad", 0.2) is None, "invalid token is rejected by HA, not hidden")

        # live candidates + heavy warning
        await asyncio.sleep(1.5)
        st, j = await jget(s, "api/state")
        check(any(c["entity"] == "sensor.example_meter_l1" for c in j["candidates"]), "noisy candidate shown in UI state")
        check(any(h["entity"] == "camera.example_door" for h in j["heavy"]), "heavy dashboard entity detected live")
        check(j["status"]["in_per_min"] > j["status"]["out_per_min"] > 0, "traffic stats")
        check(any(b["entity"] == "camera.example_door" and b["protected"] for b in j["busy"]), "busy list for the throttle card contains the busy dashboard entity")
        st, jl = await jget(s, "api/list?kind=dashboard")
        items = {i["entity"]: i for i in jl["items"]}
        check(jl["ok"] and "sensor.air_mini_co2" in items and "area (living)" in items["sensor.air_mini_co2"]["reason"]
              and items["sensor.example_living_temp"]["known"] is True and items["sensor.air_mini_pm25"]["known"] is False and "sensor.example_wild_*" in jl["wildcards"],
              "dashboard list: entities with the reason they pass, wildcards, known flag")
        st, jl = await jget(s, "api/list?kind=exclude")
        check(jl["ok"] and any(i["pattern"] for i in jl["items"]), "exclude list endpoint")
        st, jl = await jget(s, "api/list?kind=bogus")
        check(st == 400, "list endpoint refuses unknown kind")

        # an exclude change reconnects a filtered panel
        async with aiohttp.ClientSession() as s2:
            ws = await s2.ws_connect(f"http://127.0.0.1:{PROXY}/api/websocket")
            await ws.receive_json(); await ws.send_json({"type": "auth", "access_token": "tok-panel"}); await ws.receive_json()
            await ws.send_json({"id": 3, "type": "subscribe_entities"})
            await asyncio.sleep(0.4)
            await jpost(s, "api/exclude", {"text": "sensor.example_meter_*\n"})
            closed = False
            for _ in range(60):
                m = await ws.receive(timeout=4)
                if m.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    closed = True
                    break
            check(closed and ws.close_code == 1012, f"filtered panel is told to reconnect after a filter change (closed={closed} code={ws.close_code} type={m.type})")
            if not closed: print("DEBUG", [l for l in LOG.getvalue().splitlines() if "filter changed" in l or "ws user" in l][-6:], file=REAL_OUT)
        async with s.get(f"http://127.0.0.1:{PROXY}/__health") as r:
            check(r.status == 200 and await r.json() == {"status": "ok"}, "health endpoint reveals nothing but ok")

        # ---- security
        await asyncio.sleep(0.2)
        async with s.get(f"http://127.0.0.1:{PROXY}/echo", headers={"X-Forwarded-For": "6.6.6.6", "X-Real-IP": "6.6.6.6"}) as r:
            j = await r.json()
        check(j["xff"] == "127.0.0.1" and j["xrip"] is None, f"forged X-Forwarded-For/X-Real-IP is replaced by the real address ({j['xff']})")
        blob = b"x" * (6 * 1024 * 1024)
        async with s.post(f"http://127.0.0.1:{PROXY}/echo", data=blob) as r:
            j = await r.json()
        check(j["bytes"] == len(blob), "6 MB upload is streamed through intact")
        async with s.get(f"http://127.0.0.1:{PROXY}/%0a%1b[31mFAKE%20LINE%0a", params={"code": "SECRET"}) as r:
            pass
        await asyncio.sleep(0.2)
        check(not any(l.startswith("FAKE") or "\x1b[31m" in l for l in LOG.getvalue().splitlines()),
              "control characters in URLs cannot forge log lines")
        check("SECRET" not in LOG.getvalue(), "query strings are never logged")
        ws = await s.ws_connect(f"http://127.0.0.1:{PROXY}/api/websocket")
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": "tok-alice"})
        await ws.receive_json()
        try:
            await ws.send_str("x" * (17 * 1024 * 1024))
        except ConnectionError:
            pass                                          # server already hung up while we were sending
        m = await ws.receive(timeout=5)
        check(m.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR),
              "oversized client websocket message ends the connection")
        check(SEEN["ws_xff"] and all(x == "127.0.0.1" for x in SEEN["ws_xff"][:1]), "websocket upstream gets the real client address too")

        # local_only: a public peer is refused, a private one is not (mocked requests)
        from aiohttp.test_utils import make_mocked_request
        from unittest import mock as um

        def req(ip):
            tr = um.MagicMock()
            tr.get_extra_info.side_effect = lambda k, d=None: (ip, 5555) if k == "peername" else d
            r = make_mocked_request("GET", "/__health", transport=tr, app=app)
            return r
        r1 = await wf.handler(req("8.8.8.8"))
        r2 = await wf.handler(req("192.168.1.50"))
        check(r1.status == 403 and r2.status == 200, f"local_only refuses public addresses, accepts private ones ({r1.status}/{r2.status})")

    for r in runners:
        await r.cleanup()
    await mr.cleanup()
    out = LOG.getvalue()
    check("heavy dashboard entity: camera.example_door" in out, "runtime orange heavy warning in the log")
    check(not any(w in out for w in ("tok-panel", "tok-alice")), "tokens never logged")
    shutil.rmtree(tmp)


async def scenarios():
    """Home Assistant not set up for proxies; trusted reverse proxy in front."""
    tmp = tempfile.mkdtemp()
    cfg = os.path.join(tmp, "config")
    make_config(cfg)
    mock = web.Application()
    mock.router.add_get("/manifest.json", manifest)
    mock.router.add_route("*", "/echo", echo)
    mr = web.AppRunner(mock, access_log=None)
    await mr.setup()
    await web.TCPSite(mr, "127.0.0.1", MOCK).start()

    def argv(*extra):
        return wf.parse_args(["--upstream", f"http://127.0.0.1:{MOCK}", "--config-dir", cfg, "--data-dir", tmp + "/d",
                              "--listen", f"127.0.0.1:{PROXY}", "--ui-listen", f"127.0.0.1:{UI}", *extra])
    STRICT["v"] = True
    LOG.truncate(0); LOG.seek(0)
    runners, app = await wf.start_servers(argv())
    await asyncio.sleep(0.5)
    async with aiohttp.ClientSession() as s:
        async with s.get(f"http://127.0.0.1:{PROXY}/echo") as r:
            j = await r.json()
    check(j["xff"] is None, "HA not set up for proxies: no forwarded header is sent (still works)")
    check(any("not set up for reverse proxies" in w["text"] for w in app["warnings"]), "UI/log warning with the exact configuration.yaml fix")
    check("not set up for reverse proxies" in LOG.getvalue() and "use_x_forwarded_for" in LOG.getvalue(), "orange log warning shows the fix")
    for r in runners:
        await r.cleanup()

    STRICT["v"] = False
    runners, app = await wf.start_servers(argv("--trusted-proxy", "127.0.0.0/8"))
    await asyncio.sleep(0.5)
    async with aiohttp.ClientSession() as s:
        async with s.get(f"http://127.0.0.1:{PROXY}/echo", headers={"X-Forwarded-For": "192.168.1.77, not-an-ip"}) as r:
            j = await r.json()
    check(j["xff"] == "192.168.1.77, 127.0.0.1", f"trusted proxy: valid forwarded chain kept, junk dropped ({j['xff']})")
    for r in runners:
        await r.cleanup()
    # option handling: exclude file must stay inside the add-on config folder
    import types
    od = os.path.join(tmp, "opts.json")
    ns = wf.parse_args(["--upstream", "http://x", "--exclude-dir", tmp])
    json.dump({"exclude_file": "../etc/x.txt"}, open(od, "w"))
    try:
        wf.apply_options(ns, od)
        check(False, "exclude_file path escape blocked")
    except SystemExit:
        check(True, "exclude_file path escape blocked")
    os.symlink("/etc", os.path.join(tmp, "link"))
    json.dump({"exclude_file": "link/x.txt"}, open(od, "w"))
    try:
        wf.apply_options(ns, od)
        check(False, "exclude_file symlink escape blocked")
    except SystemExit:
        check(True, "exclude_file symlink escape blocked")
    check(wf.clean("a\nb\x1b[0m") == "a?b?[0m", "clean() strips control characters")
    await mr.cleanup()
    shutil.rmtree(tmp)


async def everything():
    await main()
    await scenarios()


sys.stdout = Tee()
asyncio.run(everything())
sys.stdout = REAL_OUT
print(f"\n{sum(passed)}/{len(passed)} checks passed")
sys.exit(0 if all(passed) else 1)
