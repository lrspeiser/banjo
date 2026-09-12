"""The QA suite's 3D pass: saved chat-built rooms, opened in the real playground
page in headless Chrome, and photographed.

Each chat trial in the QA suite leaves its finished room behind as
build/agent-regression/<run>/<case>-<trial>.spec.json. The engine checks say
whether a room WORKS; this shows what it LOOKS like, in the page the owner uses
and on the real engine: /world?qa=<run>/<case>-<trial> on a running playground
server, in a 1280x800 headless Chrome, framed on the build, photographed as
soon as it is on screen and again after it has run for a while in real time.

    python tests/qa_browser.py --port 8769 --run 20260912-101201
    python tests/qa_browser.py --port 8769 --run 20260912-101201 --show-for hearth=80
    python tests/qa_browser.py --port 8769 --sample

--sample first saves three builds as a new run -- the courtyard as authored, and
the guide's hinged-gate and hearth recipes built in the yard through the MCP,
as tests/agent_build_tests.py run_recipe builds them -- and captures those. It
needs BANJO_LIBRARY, to build the recipes.

The server must already be running, and must not be one somebody is using: it
holds ONE room and every capture replaces it. Start one of your own:

    python -u playground/server.py --port 8769 --engine <abs>/banjo_platform_cli.exe
        --studio <abs>/banjo_network_lab.exe

From Python: capture(builds, port, out_dir) -> list[dict], each build being
{"id": "<run>/<case>-<trial>", "focus_m": [x, y, z], "extent_m": r, "show_s": s}.

Chrome is driven over the DevTools protocol with the installed `websockets`
package; nothing is downloaded. One Chrome for the batch, on a profile of its
own under build/, one page and one build at a time, closed by PID at the end.
"""
from __future__ import annotations

import argparse
import atexit
import base64
import http.client
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
QA_ROOT = ROOT / "build" / "agent-regression"
PROFILES = ROOT / "build" / "qa-chrome"
CHROME = Path(os.environ.get("BANJO_CHROME")
              or "C:/Program Files/Google/Chrome/Application/chrome.exe")

# The server's pattern (playground/server.py QA_ID), in its three parts.
QA_ID = re.compile(r"(\d{8}-\d{6})/([a-z0-9-]+)-(\d+)", re.ASCII)
RUN_ID = re.compile(r"\d{8}-\d{6}", re.ASCII)

VIEWPORT = (1280, 800)
PANEL_PX = 360            # the page's panel covers the right of the frame (world.css #panel)
OPEN_TIMEOUT_S = 90.0     # from asking for the page to the room on screen
DEFAULT_SHOW_S = 4.0
# Not part of what was built: the yard's marker stone stands five metres off on
# purpose, so that an empty yard is still a world.
NOT_THE_BUILD = {"marker stone"}
# The owner's rule is that nothing runs more than 10% slower than the
# interaction it shows. The room steps by the wall clock, so a room that falls
# behind it is the engine not keeping up.
REALTIME_FLOOR = 1.0 / 1.1


# ---------------------------------------------------------------------------
# What to look at
# ---------------------------------------------------------------------------

def frame_of(spec: dict[str, Any]) -> tuple[list[float], float]:
    """The centre of what was built, and the radius round it, in metres.

    The box round every body but the marker stone. A body turned by
    rotation_deg counts as the sphere round it, since its sides no longer run
    along the axes.
    """
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for body in spec.get("bodies") or []:
        if body.get("name") in NOT_THE_BUILD:
            continue
        centre = [float(v) / 1000.0 for v in body["center_mm"]]
        size = [float(v) / 1000.0 for v in body["size_mm"]]
        turn = body.get("rotation_deg") or 0
        turned = any(float(a or 0) for a in (turn if isinstance(turn, (list, tuple)) else [turn]))
        half = [0.5 * math.hypot(*size)] * 3 if turned else [0.5 * s for s in size]
        for i in range(3):
            lo[i] = min(lo[i], centre[i] - half[i])
            hi[i] = max(hi[i], centre[i] + half[i])
    if lo[0] == math.inf:
        raise ValueError("there is nothing in this room but its marker stone")
    focus = [round(0.5 * (a + b), 4) for a, b in zip(lo, hi)]
    return focus, round(0.5 * math.dist(lo, hi), 4)


def framing(focus: list[float], extent: float,
            azimuth_deg: float = 20.0) -> tuple[list[float], list[float]]:
    """Where to stand, and what to look at.

    Back from the focus by 2.5 extents and a metre, on the +z side -- the side
    the room's own camera starts on, looking along -z -- turned a little round
    so that depth reads, with the eye above the focus looking down onto it.
    Kept inside the box the page lets an eye go (y 0.25..12 m, x and z 28 m).
    """
    back = 2.5 * float(extent) + 1.0
    turn = math.radians(azimuth_deg)
    eye = [focus[0] + back * math.sin(turn),
           focus[1] + max(0.6, 0.45 * back),
           focus[2] + back * math.cos(turn)]
    eye = [min(27.5, max(-27.5, eye[0])), min(11.5, max(0.3, eye[1])),
           min(27.5, max(-27.5, eye[2]))]
    return [round(v, 3) for v in eye], [float(v) for v in focus]


def builds_in(run: str, show_s: float = DEFAULT_SHOW_S,
              show_for: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """One build for each room saved in a run folder, framed from its own bodies."""
    if not RUN_ID.fullmatch(run):
        raise ValueError(f"{run!r} is not a run: runs are named like 20260912-101201")
    folder = QA_ROOT / run
    if not folder.is_dir():
        raise FileNotFoundError(f"there is no run {run} in {QA_ROOT}")
    builds = []
    for path in sorted(folder.glob("*.spec.json")):
        build_id = f"{run}/{path.name[:-len('.spec.json')]}"
        match = QA_ID.fullmatch(build_id)
        if not match:
            print(f"skipped {path.name}: not named <case>-<trial>.spec.json", flush=True)
            continue
        focus, extent = frame_of(json.loads(path.read_text(encoding="utf-8")))
        builds.append({"id": build_id, "focus_m": focus, "extent_m": extent,
                       "show_s": float((show_for or {}).get(match[2], show_s))})
    return builds


# ---------------------------------------------------------------------------
# Chrome, over the DevTools protocol
# ---------------------------------------------------------------------------

class DevTools:
    """One DevTools connection: commands out, their answers back, and every
    event that arrived in between kept in `events`."""

    def __init__(self, url: str) -> None:
        from websockets.sync.client import connect
        # No size limit (a screenshot is megabytes of base64), no compression
        # and no keepalive pings: this is a local socket to a local browser.
        self.socket = connect(url, max_size=None, compression=None, ping_interval=None,
                              open_timeout=15, max_queue=1024)
        self.next_id = 0
        self.events: list[dict[str, Any]] = []

    def send(self, method: str, params: dict[str, Any] | None = None,
             timeout: float = 30.0) -> dict[str, Any]:
        self.next_id += 1
        ident = self.next_id
        self.socket.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"DevTools did not answer {method} within {timeout:.0f} s")
            message = json.loads(self.socket.recv(timeout=left))
            if message.get("id") == ident:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error'].get('message')}")
                return message.get("result") or {}
            if "method" in message:
                self.events.append(message)

    def evaluate(self, expression: str, await_promise: bool = False,
                 timeout: float = 30.0) -> Any:
        """Run JavaScript in the page's own world -- where window.banjoRoom is."""
        answer = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                "awaitPromise": await_promise}, timeout)
        if "exceptionDetails" in answer:
            detail = answer["exceptionDetails"]
            raise RuntimeError((detail.get("exception") or {}).get("description")
                               or detail.get("text") or "the page threw")
        return (answer.get("result") or {}).get("value")

    def close(self) -> None:
        try:
            self.socket.close()
        except Exception:
            pass


class Chrome:
    """One headless Chrome on a profile of its own, closed by its PID."""

    def __init__(self, width: int = VIEWPORT[0], height: int = VIEWPORT[1]) -> None:
        if not CHROME.is_file():
            raise RuntimeError(f"Chrome is not at {CHROME}; set BANJO_CHROME to it")
        PROFILES.mkdir(parents=True, exist_ok=True)
        # A profile per Chrome. A second Chrome on a profile that is already open
        # hands its command line to the first and exits -- leaving a PID that is
        # gone and a browser nobody launched.
        self.profile = PROFILES / f"chrome-{os.getpid()}-{time.time_ns()}"
        self.page: DevTools | None = None
        self.process: subprocess.Popen | None = subprocess.Popen(
            [str(CHROME), "--headless=new", "--remote-debugging-port=0",
             f"--user-data-dir={self.profile}", f"--window-size={width},{height}",
             "--no-first-run", "--no-default-browser-check", "--disable-extensions",
             "--disable-sync", "--mute-audio", "--hide-scrollbars",
             # A page that is not being looked at is throttled to about one tick
             # a second, which reads as the room running at a fraction of real
             # time. Headless is always looked at; these make sure of it.
             "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
             "--disable-backgrounding-occluded-windows", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.pid = self.process.pid
        atexit.register(self.close)
        try:
            self.port, self.browser_path = self._devtools_port()
            self.page = DevTools(self._page_socket())
        except Exception:
            self.close()
            raise

    def _devtools_port(self, timeout_s: float = 30.0) -> tuple[int, str]:
        """Chrome picks its own port (so no other session's browser is in the
        way) and writes it, with the browser's socket path, into the profile."""
        marker = self.profile / "DevToolsActivePort"
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            assert self.process is not None
            if self.process.poll() is not None:
                raise RuntimeError(f"Chrome exited while starting (code {self.process.returncode})")
            try:
                lines = marker.read_text(encoding="utf-8").split()
                if len(lines) >= 2:
                    return int(lines[0]), lines[1]
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        raise RuntimeError("Chrome never opened its DevTools port")

    def _http(self, method: str, path: str) -> Any:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path)
            return json.loads(connection.getresponse().read() or b"null")
        finally:
            connection.close()

    def _page_socket(self) -> str:
        for target in self._http("GET", "/json/list") or []:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return target["webSocketDebuggerUrl"]
        return self._http("PUT", "/json/new?about:blank")["webSocketDebuggerUrl"]

    def close(self) -> None:
        """Close Chrome and make sure of it: by PID, the whole tree, never by
        image name -- other sessions' browsers share that name."""
        process, self.process = self.process, None
        if process is None:
            return
        if self.page is not None:
            self.page.close()
        try:
            browser = DevTools(f"ws://127.0.0.1:{self.port}{self.browser_path}")
            try:
                browser.send("Browser.close", timeout=5)
            finally:
                browser.close()
        except Exception:
            pass   # it went before it could answer, or never came up
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True)
            else:
                process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        for _ in range(20):
            shutil.rmtree(self.profile, ignore_errors=True)
            if not self.profile.exists():
                break
            time.sleep(0.25)


# ---------------------------------------------------------------------------
# In the page
# ---------------------------------------------------------------------------

# null while the page being left is still the one answering, or before the
# room's handle exists.
STATUS = """(() => {
  if (window.__qaLeaving) return null;
  const room = window.banjoRoom;
  return room && room.status ? room.status() : null;
})()"""

TWO_FRAMES = """new Promise((done) =>
  requestAnimationFrame(() => requestAnimationFrame(() => done(true))))"""

# A style property rather than `hidden`, which the page's aim() sets several
# times a second; and set through the CSSOM, which the page's CSP allows.
HIDE_AIM_LABEL = """(() => {
  const label = document.getElementById("label");
  if (label) label.style.visibility = "hidden";
  return !!label;
})()"""

RENDERER = """(() => {
  const gl = window.banjoRoom.renderer.getContext();
  const info = gl.getExtension("WEBGL_debug_renderer_info");
  return String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
})()"""

# What is in the picture, measured rather than squinted at. The room's own
# renderer draws the frame twice in one task -- once as it is, once with the
# build's bodies hidden -- and reads both back. Pixels that change ARE the
# build: none means an empty yard, and a frame with almost nothing lit is a
# black one. Put back and drawn again before returning, so nothing on screen
# ever shows the hidden version.
SEEN = """(() => {
  const r = window.banjoRoom;
  const skip = new Set(%s);
  const meshes = [...r.world.bodies].filter(([name]) => !skip.has(name)).map(([, e]) => e.mesh);
  const gl = r.renderer.getContext();
  const grab = () => {
    r.renderer.render(r.scene, r.camera);
    const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
    const px = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
    return { w, h, px };
  };
  const shown = grab();
  const was = meshes.map((m) => m.visible);
  meshes.forEach((m) => { m.visible = false; });
  const bare = grab();
  meshes.forEach((m, i) => { m.visible = was[i]; });
  r.renderer.render(r.scene, r.camera);
  const { w, h } = shown, a = shown.px, b = bare.px;
  let n = 0, lit = 0, luma = 0, changed = 0, x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y += 2) for (let x = 0; x < w; x += 2) {
    const i = (y * w + x) * 4;
    const l = 0.2126 * a[i] + 0.7152 * a[i + 1] + 0.0722 * a[i + 2];
    n++; luma += l; if (l > 40) lit++;
    if (Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]) > 30) {
      changed++;
      const top = h - 1 - y;   // readPixels rows run bottom up
      x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, top); y1 = Math.max(y1, top);
    }
  }
  return { width: w, height: h, bodies: meshes.length, mean_luma: +(luma / n).toFixed(1),
           lit_fraction: +(lit / n).toFixed(4), build_fraction: +(changed / n).toFixed(4),
           build_box_px: changed ? [x0, y0, x1, y1] : null };
})()""" % json.dumps(sorted(NOT_THE_BUILD))


def _wait_until_ready(page: DevTools, timeout_s: float = OPEN_TIMEOUT_S) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_s
    status = None
    while time.monotonic() < deadline:
        try:
            status = page.evaluate(STATUS, timeout=10)
        except (RuntimeError, TimeoutError):
            status = None   # between documents
        if status and status.get("ready"):
            return status
        if status and str(status.get("panel", "")).startswith("Could not open the room"):
            return status
        time.sleep(0.1)
    return status


def _shoot(page: DevTools, path: Path) -> str:
    shot = page.send("Page.captureScreenshot", {"format": "png"}, timeout=60)
    path.write_bytes(base64.b64decode(shot["data"]))
    return str(path)


def _expected(entry: dict[str, Any]) -> bool:
    """The two failed requests every page load makes on purpose: its first
    POST, answered 403, is how the page learns it needs the session token; and
    the browser asks for a favicon nobody serves."""
    url, text = str(entry.get("url") or ""), str(entry.get("text") or "")
    return url.endswith("/favicon.ico") or ("status of 403" in text and "/api/" in url)


def _errors_into(record: dict[str, Any], events: list[dict[str, Any]],
                 status: dict[str, Any] | None) -> None:
    console, exceptions = [], []
    for event in events:
        method, params = event.get("method"), event.get("params") or {}
        if method == "Runtime.exceptionThrown":
            detail = params.get("exceptionDetails") or {}
            exceptions.append(str((detail.get("exception") or {}).get("description")
                                  or detail.get("text"))[:500])
        elif method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "assert"):
            console.append(" ".join(str(a.get("value", a.get("description", "")))
                                    for a in params.get("args") or [])[:500])
        elif method == "Log.entryAdded":
            entry = params.get("entry") or {}
            if entry.get("level") == "error" and not _expected(entry):
                console.append(f"{entry.get('text')} ({entry.get('url')})"[:500])
    noted = [e.get("what") for e in (status or {}).get("errors") or []]
    record.update(console_errors=console, exceptions=exceptions, page_errors=noted)
    for label, found in (("console error", console), ("exception", exceptions),
                         ("error the page noted", noted)):
        if found:
            record["problems"].append(f"{len(found)} {label}(s), the first: {found[0]}")


def _capture_one(page: DevTools, build: dict[str, Any], port: int, out: Path) -> dict[str, Any]:
    match = QA_ID.fullmatch(str(build.get("id", "")))
    if not match:
        raise ValueError(f"{build.get('id')!r} is not a QA build id (<run>/<case>-<trial>)")
    run, case, trial = match.groups()
    name = f"{case}-{trial}"
    if "focus_m" not in build or "extent_m" not in build:
        spec = json.loads((QA_ROOT / f"{build['id']}.spec.json").read_text(encoding="utf-8"))
        focus, extent = frame_of(spec)
        build = {"focus_m": focus, "extent_m": extent, **build}
    show_s = float(build.get("show_s", DEFAULT_SHOW_S))
    url = f"http://127.0.0.1:{port}/world?qa={quote(build['id'], safe='/')}"
    record: dict[str, Any] = {"id": build["id"], "run": run, "case": case, "trial": int(trial),
                              "url": url, "ok": False, "problems": [], "show_s": show_s,
                              "start_png": None, "later_png": None}
    problems = record["problems"]

    # Mark the page being left, so that it cannot answer for the new one.
    page.evaluate("window.__qaLeaving = true")
    page.events.clear()
    asked = time.perf_counter()
    navigated = page.send("Page.navigate", {"url": url})
    if navigated.get("errorText"):
        problems.append(f"the page would not load: {navigated['errorText']}")
        return record
    status = _wait_until_ready(page)
    record["ready_s"] = round(time.perf_counter() - asked, 2)
    if not status or not status.get("ready"):
        problems.append("the room never came up: " + (str(status.get("panel")) if status
                                                      else "the page never offered banjoRoom"))
        record["status"] = {"opened": status}
        _errors_into(record, page.events, status)
        return record
    if status.get("scene") != f"qa:{build['id']}":
        problems.append(f"the server opened {status.get('scene')!r} and not this build: it "
                        f"predates ?qa=, and needs restarting from code that has it")
    record["renderer"] = page.evaluate(RENDERER)
    # Framing puts the crosshair on the build, and the label saying what the
    # crosshair is on would then sit over the middle of it in every picture.
    # Hidden for the pictures only; the crosshair itself stays.
    record["aim_label_hidden"] = page.evaluate(HIDE_AIM_LABEL)

    eye, look = framing(build["focus_m"], build["extent_m"], float(build.get("azimuth_deg", 20.0)))
    record["framing"] = {"stand_m": eye, "look_at_m": look, "extent_m": float(build["extent_m"])}
    page.evaluate(f"banjoRoom.standAt({eye[0]}, {eye[1]}, {eye[2]}); "
                  f"banjoRoom.lookAt({look[0]}, {look[1]}, {look[2]}); true")
    page.evaluate(TWO_FRAMES, await_promise=True)

    seen_start = page.evaluate(SEEN)
    start = page.evaluate(STATUS)
    wall_start = time.perf_counter()
    record["start_png"] = _shoot(page, out / f"{name}-start.png")
    # Real time: the room steps by the wall clock, so this is the build
    # running. Looked in on once a second, which also reads the page's events
    # as they come rather than letting them pile up in the socket.
    while (left := show_s - (time.perf_counter() - wall_start)) > 0:
        time.sleep(min(1.0, left))
        page.evaluate("0")
    later = page.evaluate(STATUS)
    wall_later = time.perf_counter()
    seen_later = page.evaluate(SEEN)
    record["later_png"] = _shoot(page, out / f"{name}-later.png")
    record["heat_drawn"] = page.evaluate("banjoRoom.heatDrawn()")
    record["status"] = {"start": start, "later": later}
    record["seen"] = {"start": seen_start, "later": seen_later}

    wall_s = wall_later - wall_start
    world_s = float(later.get("time_s") or 0.0) - float(start.get("time_s") or 0.0)
    realtime = world_s / wall_s if wall_s > 0 else None
    record["ran"] = {"wall_s": round(wall_s, 2), "world_s": round(world_s, 2),
                     "realtime": None if realtime is None else round(realtime, 3),
                     "fps": round((later.get("frames", 0) - start.get("frames", 0)) / wall_s, 1)
                     if wall_s > 0 else None}
    if not later.get("session") or later.get("session") != start.get("session"):
        problems.append(f"the room stopped while it ran: {later.get('panel')}")
    elif realtime is not None and wall_s >= 1.0 and realtime < REALTIME_FLOOR:
        problems.append(f"the room ran at {100 * realtime:.0f}% of realtime, slower than "
                        f"the 1.1x limit allows")
    for when, seen in (("start", seen_start), ("later", seen_later)):
        if seen["lit_fraction"] < 0.01:
            problems.append(f"the {when} picture is black")
        elif seen["build_fraction"] < 0.002:
            problems.append(f"the build is not in the {when} picture: it changes "
                            f"{100 * seen['build_fraction']:.2f}% of it")
        elif seen["build_box_px"][0] >= VIEWPORT[0] - PANEL_PX:
            problems.append(f"the build is behind the panel in the {when} picture")
    _errors_into(record, page.events, later)
    record["ok"] = not problems
    return record


def capture(builds: list[dict[str, Any]], port: int, out_dir: Path | str) -> list[dict[str, Any]]:
    """Open each saved build in the real page, frame it, and photograph it twice.

    One Chrome for the batch and one build at a time: the server holds one
    room, so two pages would take it from each other. Returns one dict per
    build: the pictures, how long it took to come up, how the room ran against
    the wall clock, what was in the frame, what heat was drawn, the page's
    status, every console error and exception, and `problems` (empty is `ok`).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    chrome = Chrome()
    try:
        page = chrome.page
        assert page is not None
        for method in ("Page.enable", "Runtime.enable", "Log.enable"):
            page.send(method)
        page.send("Emulation.setDeviceMetricsOverride",
                  {"width": VIEWPORT[0], "height": VIEWPORT[1], "deviceScaleFactor": 1,
                   "mobile": False})
        for build in builds:
            began = time.perf_counter()
            try:
                record = _capture_one(page, build, port, out)
            except Exception:
                record = {"id": build.get("id"), "ok": False,
                          "problems": ["the capture itself failed: "
                                       + traceback.format_exc(limit=4)[-700:]]}
            record["wall_s"] = round(time.perf_counter() - began, 2)
            results.append(record)
    finally:
        chrome.close()
    return results


# ---------------------------------------------------------------------------
# A sample run, and the command line
# ---------------------------------------------------------------------------

def make_sample(stamp: str | None = None) -> Path:
    """Three saved builds, as a QA run would leave them: the courtyard as
    authored, and the guide's hinged-gate and hearth recipes built in the yard
    through the MCP and exported, exactly as run_recipe builds them."""
    for folder in (ROOT / "playground", ROOT / "tests"):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    import room_world                             # noqa: E402 - needs BANJO_LIBRARY
    import world_room                             # noqa: E402
    from agent_build_tests import CASES, RECIPES  # noqa: E402

    folder = QA_ROOT / (stamp or time.strftime("%Y%m%d-%H%M%S"))
    specs = {"courtyard-1": world_room.courtyard()}
    for recipe in ("hinged-gate", "hearth"):
        case_id, calls = RECIPES[recipe]
        case = next(c for c in CASES if c.id == case_id)
        world_id = room_world.open_room(world_room.Room(case.scene).spec)
        try:
            room_world.call(world_id, "clear_world", {})
            for tool, args in calls:
                answer = room_world.call(world_id, tool, args)
                if "error" in answer:
                    raise RuntimeError(f"the {recipe} recipe was refused at {tool}: "
                                       f"{answer['error']}")
            specs[f"{case_id}-1"] = room_world.export_spec(room_world.entry_of(world_id))
        finally:
            room_world.close_room(world_id)
    folder.mkdir(parents=True, exist_ok=False)
    for name, spec in specs.items():
        (folder / f"{name}.spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    return folder


def _server_is_up(port: int) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", "/api/status")
        response = connection.getresponse()
        response.read()
        if response.status != 200:
            raise OSError(f"/api/status answered {response.status}")
    finally:
        connection.close()


def _line(record: dict[str, Any]) -> str:
    ran = record.get("ran") or {}
    seen = (record.get("seen") or {}).get("later") or {}
    flames = (record.get("heat_drawn") or {}).get("flames") or []
    parts = [f"{'ok  ' if record.get('ok') else 'FAIL'} {record.get('id')}",
             f"up in {record.get('ready_s')} s"]
    if ran.get("realtime") is not None:
        parts.append(f"ran {ran['world_s']} s of world in {ran['wall_s']} s "
                     f"({100 * ran['realtime']:.0f}% of realtime, {ran['fps']} fps)")
    if seen:
        parts.append(f"build fills {100 * seen['build_fraction']:.1f}% of the frame")
    if flames:
        parts.append("flames over " + ", ".join(flames))
    parts.append(f"{record.get('wall_s')} s in all")
    lines = ["  ".join(parts)]
    lines += [f"      {problem}" for problem in record.get("problems") or []]
    lines += [f"      {record[key]}" for key in ("start_png", "later_png") if record.get(key)]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=8769,
                        help="a playground server of your own (default 8769)")
    parser.add_argument("--run", help="a run under build/agent-regression, like 20260912-101201")
    parser.add_argument("--sample", action="store_true",
                        help="save the courtyard and the hinged-gate and hearth recipes as a "
                             "new run, and capture that (needs BANJO_LIBRARY)")
    parser.add_argument("--show-s", type=float, default=DEFAULT_SHOW_S,
                        help="real seconds between the two pictures (default 4)")
    parser.add_argument("--show-for", action="append", default=[], metavar="CASE=SECONDS",
                        help="a longer look for one case, like hearth=80: a fire takes about "
                             "a minute to catch (--sample does this for the hearth)")
    parser.add_argument("--out", type=Path, help="where the pictures go (default <run>/3d)")
    args = parser.parse_args(argv)
    if args.port == 8765:
        parser.error("8765 is the owner's playground. It holds ONE room and every capture "
                     "replaces it: start a server of your own and point this at that.")
    if bool(args.run) == bool(args.sample):
        parser.error("name a run with --run, or ask for --sample")
    show_for = {"hearth": 80.0} if args.sample else {}
    for item in args.show_for:
        case, _, seconds = item.partition("=")
        try:
            show_for[case.strip()] = float(seconds)
        except ValueError:
            parser.error(f"--show-for takes CASE=SECONDS, not {item!r}")
    try:
        _server_is_up(args.port)
    except OSError as problem:
        print(f"no playground server answers on port {args.port} ({problem}). Start one:\n"
              f"  python -u playground/server.py --port {args.port} "
              f"--engine <abs>/banjo_platform_cli.exe --studio <abs>/banjo_network_lab.exe")
        return 2
    if args.sample:
        run = make_sample().name
        print(f"saved three builds as run {run}", flush=True)
    else:
        run = args.run
    builds = builds_in(run, args.show_s, show_for)
    if not builds:
        print(f"nothing saved in {QA_ROOT / run}")
        return 2
    out = args.out or QA_ROOT / run / "3d"
    print(f"{len(builds)} build(s) from run {run}, on port {args.port}; pictures to {out}",
          flush=True)
    results = capture(builds, args.port, out)
    (Path(out) / "3d.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    for record in results:
        print(_line(record), flush=True)
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
