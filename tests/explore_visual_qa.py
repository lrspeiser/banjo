"""The Explorer, checked by what a person SEES.

    python tests/explore_visual_qa.py
    python tests/explore_visual_qa.py --only "oak block" stool
    python tests/explore_visual_qa.py --keep-server        # leave it up to look at

The owner, 2026-09-21: "i can't put anything down, it is still not working
intuitively, how can you build a visual QA test to confirm things are working?"
-- after a test of mine had passed by reading what the page SAID ("holding:
nothing") without ever looking at what it showed.

So this looks. It runs a playground server of its own (a port the system picks,
a throwaway room folder -- never anybody's open room), opens /explore in a
1280x800 Chrome, and does with each thing what a person does: walk up to it,
press E, look down at the ground, press E again, pick it back up, let go. The
keys go through Chrome's own input (Input.dispatchKeyEvent), as a keyboard's
do, not as events made up inside the page.

Every step is filmed, and each check is something a person expects, measured
off the screen and the engine's own positions together:

  - the sight is on the thing before E is pressed;
  - E takes it up quickly, you can see it come up, it stays in view and does
    not fill the view, and the hands panel shows a picture of it;
  - looking down shows the preview, where you are looking;
  - E puts it down: something happens at once, it leaves your hands, it comes
    to rest quickly, where the preview was, on the ground and in one piece,
    and the screen says what happened;
  - E picks it up again, and X lets go.

It writes build/visual-qa/<stamp>/: report.html (a filmstrip per thing, the
sight, the thing and the preview marked on every frame, every check with the
frame it was measured on), sheet.png (one row per thing: before, holding it,
the preview, put down) and a GIF per thing of it being put down. It exits 0
only when every check passes.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import qa_browser  # noqa: E402

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

W, H = 1280, 800
# The mace is taken up by its handle ("mace"); its head comes with it, on its
# tie (the owner's carry rule, agent/carry-whole).
THINGS = ("oak block", "iron block", "glass block", "concrete block", "ceramic block", "ice block",
          "aluminium block", "rubber block", "stool", "chair", "bench", "table", "shelf-unit",
          "mace")

# What a person expects, as numbers. Each is the longest a person waits before
# deciding it did not work, or the furthest a thing may be from where it was
# shown. They are the test; change them only knowing that.
TAKE_WITHIN_S = 0.6            # E to it being in your hands
LIFT_M = 0.05                  # how far it must come up for you to see it has
RESPOND_WITHIN_S = 0.4         # E to anything visibly happening
RELEASE_WITHIN_S = 1.0         # E to it leaving your hands, for anything up to...
LIGHT_KG = 30.0                # ...this; a heavier thing is allowed 0.5 s more per 15 kg,
                               # since nobody expects 60 kg of iron to go down like a block of oak
REST_WITHIN_S = 2.0            # E to it lying still
LANDS_WITHIN_M = 0.25          # from the middle of the preview
PREVIEW_WITHIN_S = 1.0         # looking down to the preview appearing
PREVIEW_NEAR_SIGHT_PX = 140    # the preview is where you are looking
FILLS_AT_MOST = 0.6            # of what you can see, taken up by what you hold
HIDES_AT_MOST = 0.35           # of the preview, hidden behind what you hold
FALLEN_DEG = 30.0              # leaning more than this from how it was set down is fallen over
GREEN = "#a2e1c8"              # the preview's colour when it promises the thing will stay
# Where a person looks next when the preview is amber or red: metres ahead,
# and a turn from where they first looked.
OTHER_SPOTS = ((1.3, 0.0), (1.9, 0.0), (1.6, 0.3), (1.6, -0.3), (1.2, 0.45), (1.2, -0.45))

KEYS = {"KeyE": ("e", 69), "KeyX": ("x", 88), "KeyQ": ("q", 81), "KeyJ": ("j", 74)}

# Things in the valley that cannot yet be whole, and why. Their checks run and
# are reported, marked KNOWN, and do not fail the run. Empty: the kettle and the
# cart were here -- neither can be built whole at the valley's 40 mm cells --
# and the owner's call (2026-09-21) was to take them out of the valley until
# they can be, rather than keep excusing them.
KNOWN: dict[str, str] = {}


# --------------------------------------------------------------------------
# A server of its own
# --------------------------------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(out: Path) -> tuple[subprocess.Popen, int]:
    built = ROOT / "build" / "joints" / "Release"
    engine = Path(os.environ.get("BANJO_LIVE_ENGINE") or built / "banjo_platform_cli.exe")
    studio = Path(os.environ.get("BANJO_STUDIO") or built / "banjo_network_lab.exe")
    for need in (engine, studio):
        if not need.is_file():
            raise SystemExit(f"no engine at {need}: build it, or set BANJO_LIVE_ENGINE/BANJO_STUDIO")
    port = free_port()
    log = open(out / "server.log", "w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "playground" / "server.py"), "--port", str(port),
         "--engine", str(engine), "--studio", str(studio),
         "--runs", str(out / "runs"), "--rooms", str(out / "rooms")],
        stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise SystemExit(f"the server stopped while starting; see {out / 'server.log'}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2) as r:
                if json.load(r).get("engine_ready"):
                    return server, port
        except OSError:
            pass
        time.sleep(0.3)
    stop(server)
    raise SystemExit("the server never came up")


def stop(process: subprocess.Popen | None) -> None:
    """By PID and its whole tree: the server runs the engine as a child."""
    if process is None or process.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                   capture_output=True, check=False)


# --------------------------------------------------------------------------
# The page, as a person has it
# --------------------------------------------------------------------------

class Page:
    def __init__(self, chrome: qa_browser.Chrome) -> None:
        self.dev = chrome.page
        for domain in ("Runtime", "Page", "Log"):
            self.dev.send(f"{domain}.enable")

    def js(self, expression: str, wait: bool = False):
        return self.dev.evaluate(expression, await_promise=wait)

    def now(self) -> float:
        return float(self.js("performance.now()"))

    def key(self, code: str) -> float:
        """A real key: down and up, through Chrome's input. Returns the page's
        clock at the press, which is what every time below is measured from."""
        key, vk = KEYS[code]
        pressed = self.now()
        common = {"code": code, "key": key, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        self.dev.send("Input.dispatchKeyEvent", {"type": "keyDown", "text": key, **common})
        self.dev.send("Input.dispatchKeyEvent", {"type": "keyUp", **common})
        return pressed

    def shot(self) -> bytes:
        got = self.dev.send("Page.captureScreenshot", {"format": "jpeg", "quality": 72}, timeout=60)
        return base64.b64decode(got["data"])

    def snap(self, names: list[str]) -> dict:
        return json.loads(self.js(f"JSON.stringify(banjoExplorer.snapshot({json.dumps(names)}))"))

    def errors(self) -> list[str]:
        said = []
        for e in self.dev.events:
            if e.get("method") == "Runtime.exceptionThrown":
                d = e["params"]["exceptionDetails"]
                said.append((d.get("exception") or {}).get("description") or d.get("text") or "?")
            elif e.get("method") == "Log.entryAdded" and e["params"]["entry"].get("level") == "error":
                said.append(e["params"]["entry"].get("text", "?"))
        return said


def film(page: Page, names: list[str], seconds: float, since: float, label: str,
         every: float = 0.1) -> list[dict]:
    """Photograph the page, with what it shows, until `seconds` have gone."""
    frames = []
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        began = time.monotonic()
        jpeg = page.shot()
        snap = page.snap(names)
        frames.append({"phase": label, "t": (snap["now"] - since) / 1000.0,
                       "jpeg": jpeg, "snap": snap})
        time.sleep(max(0.0, every - (time.monotonic() - began)))
    return frames


# --------------------------------------------------------------------------
# What a person expects
# --------------------------------------------------------------------------

def visible_area(snap: dict) -> tuple[float, float, float, float]:
    return (0.0, 0.0, snap["view"]["w"] - snap["view"]["side"], snap["view"]["h"])


def overlap(box: dict | None, area: tuple) -> float:
    if not box:
        return 0.0
    x0, y0 = max(box["x0"], area[0]), max(box["y0"], area[1])
    x1, y1 = min(box["x1"], area[2]), min(box["y1"], area[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def picture_in(jpeg: bytes, rect: dict) -> float:
    """How much there is to see in part of a frame: the spread of its pixels.
    An empty canvas is one flat colour and reads near 0."""
    image = Image.open(io.BytesIO(jpeg)).convert("L")
    crop = image.crop((int(rect["x"]) + 2, int(rect["y"]) + 2,
                       int(rect["x"] + rect["w"]) - 2, int(rect["y"] + rect["h"]) - 2))
    pixels = list(crop.getdata())
    if not pixels:
        return 0.0
    mean = sum(pixels) / len(pixels)
    return (sum((p - mean) ** 2 for p in pixels) / len(pixels)) ** 0.5


class Journey:
    def __init__(self, name: str) -> None:
        self.name = name
        self.frames: list[dict] = []
        self.checks: list[dict] = []
        self.note = ""

    def check(self, what: str, ok: bool, got: str, frame: dict | None = None) -> bool:
        self.checks.append({"what": what, "ok": bool(ok), "got": got,
                            "frame": self.frames.index(frame) if frame in self.frames else None})
        return bool(ok)


def first(frames: list[dict], test) -> dict | None:
    return next((f for f in frames if test(f)), None)


def it(frame: dict, name: str) -> dict | None:
    return frame["snap"]["things"].get(name)


def journey(page: Page, name: str) -> Journey:
    j = Journey(name)
    names = [name]
    if not page.js(f"banjoExplorer.faceThing({json.dumps(name)}, 1.8)"):
        j.note = "not in the valley"
        return j
    time.sleep(0.8)

    # --- Walking up to it ------------------------------------------------
    since = page.now()
    before = film(page, names, 0.4, since, "looking at it")
    j.frames += before
    rest = it(before[-1], name)
    j.check("the sight is on it", before[-1]["snap"]["said"]["inFront"] == name,
            f"in front: {before[-1]['snap']['said']['inFront']!r}", before[-1])

    # --- E: take it --------------------------------------------------------
    pressed = page.key("KeyE")
    take = film(page, names, 2.0, pressed, "E: take it")
    j.frames += take
    held = first(take, lambda f: (it(f, name) or {}).get("held"))
    if held is None:
        said = take[-1]["snap"]["said"]
        j.check("E takes it up", False,
                f"never held; the screen said {said['loud'] or said['panel']!r}", take[-1])
        return j
    j.check(f"E takes it up within {TAKE_WITHIN_S} s", held["t"] <= TAKE_WITHIN_S,
            f"{held['t']:.2f} s", held)
    lift = max(take, key=lambda f: (it(f, name) or rest)["lowest"])
    up = it(lift, name)["lowest"] - rest["lowest"]
    j.check(f"you can see it come up (at least {LIFT_M * 100:.0f} cm)", up >= LIFT_M,
            f"{up * 100:.1f} cm", lift)
    last = take[-1]
    area = visible_area(last["snap"])
    seen = overlap(it(last, name)["box"], area) / ((area[2] - area[0]) * (area[3] - area[1]))
    j.check("it is in view while you hold it", seen > 0.002, f"{seen:.1%} of the view", last)
    clear = it(last, name).get("seeThrough")
    j.check(f"it leaves the view clear (covers at most {FILLS_AT_MOST:.0%}, or is see-through)",
            seen <= FILLS_AT_MOST or clear,
            f"{seen:.1%} of the view" + (", drawn see-through" if clear else ""), last)
    detail = picture_in(last["jpeg"], last["snap"]["handView"])
    j.check("the hands panel shows a picture of it", detail > 6.0, f"pixel spread {detail:.1f}", last)

    # --- Look down at the ground: the preview ------------------------------
    page.js("banjoExplorer.aimAtGround(1.6)")
    since = page.now()
    aim = film(page, names, 1.4, since, "look down: the preview")
    j.frames += aim
    shown = first(aim, lambda f: f["snap"]["ghost"] is not None)
    if not j.check(f"the preview appears within {PREVIEW_WITHIN_S} s",
                   shown is not None and shown["t"] <= PREVIEW_WITHIN_S,
                   f"{shown['t']:.2f} s" if shown else "never", shown or aim[-1]):
        ghost_then = None
    else:
        g, s = aim[-1]["snap"]["ghost"] or shown["snap"]["ghost"], aim[-1]["snap"]["sight"]
        # From where it will stand, not from the middle of the preview: a tall
        # thing's middle is far above the spot the sight is on.
        spot = g.get("base") or g["screen"]
        off = ((spot["x"] - s["x"]) ** 2 + (spot["y"] - s["y"]) ** 2) ** 0.5
        j.check(f"the preview is where you are looking (within {PREVIEW_NEAR_SIGHT_PX} px)",
                off <= PREVIEW_NEAR_SIGHT_PX, f"{off:.0f} px from the sight", aim[-1])
        # Amber or red says it may fall or will not go: a person looks for a
        # better spot before pressing E, and so does this.
        first_said = aim[-1]["snap"]["said"]["ghost"]
        if (g.get("colour") or "").lower() != GREEN:
            yaw0 = page.js("banjoExplorer.person.yaw")
            for ahead, turn in OTHER_SPOTS:
                page.js(f"banjoExplorer.person.yaw = {yaw0}; banjoExplorer.aimAtGround({ahead}, {turn})")
                more = film(page, names, 0.7, page.now(), "look for a better spot")
                j.frames += more
                aim = aim + more
                now = more[-1]["snap"]["ghost"]
                if now and (now.get("colour") or "").lower() == GREEN:
                    break
            g = aim[-1]["snap"]["ghost"] or g
            s = aim[-1]["snap"]["sight"]
        j.promise = "green" if (g.get("colour") or "").lower() == GREEN else "warned"
        j.warning = "" if j.promise == "green" else (aim[-1]["snap"]["said"]["ghost"] or first_said or "")
        ghost_then = g
        held_box = (it(aim[-1], name) or {}).get("box")
        if g.get("box"):
            gb = g["box"]
            whole = max(1.0, (gb["x1"] - gb["x0"]) * (gb["y1"] - gb["y0"]))
            hidden = overlap(held_box, (gb["x0"], gb["y0"], gb["x1"], gb["y1"])) / whole
            # Behind a thing drawn see-through is still in sight.
            clear = (it(aim[-1], name) or {}).get("seeThrough")
            j.check(f"you can see the preview past or through what you hold (at most {HIDES_AT_MOST:.0%} hidden)",
                    hidden <= HIDES_AT_MOST or clear,
                    f"{hidden:.0%} of it behind what you hold" + (", which is drawn see-through" if clear else ""),
                    aim[-1])
        clear = (it(aim[-1], name) or {}).get("seeThrough")
        covered = bool(held_box) and held_box["x0"] <= s["x"] <= held_box["x1"] \
            and held_box["y0"] <= s["y"] <= held_box["y1"]
        j.check("what you hold does not hide the sight", not covered or clear,
                ("it is over the sight, drawn see-through" if clear else "it is over the sight")
                if covered else "the sight is clear", aim[-1])

    # --- E: put it down ------------------------------------------------------
    carried = it(aim[-1], name)
    before_e = aim[-1]["snap"]["said"]["loud"]
    pressed = page.key("KeyE")
    down = film(page, names, 4.5, pressed, "E: put it down")
    j.frames += down
    fresh = lambda f: f["snap"]["said"]["loud"] and f["snap"]["said"]["loud"] != before_e

    def moved(f):
        now = it(f, name)
        return now and sum((now["centre"][k] - carried["centre"][k]) ** 2 for k in range(3)) ** 0.5 > 0.03

    # Something NEW: the message still up from picking it up does not count.
    answer = first(down, lambda f: moved(f) or fresh(f))
    j.check(f"something happens within {RESPOND_WITHIN_S} s of E",
            answer is not None and answer["t"] <= RESPOND_WITHIN_S,
            f"{answer['t']:.2f} s" if answer else "nothing, for 4.5 s", answer or down[-1])
    let_go = first(down, lambda f: not (it(f, name) or {}).get("held"))
    kg = carried.get("mass_kg") or 0.0
    allowed = RELEASE_WITHIN_S + max(0.0, kg - LIGHT_KG) / 15.0 * 0.5
    j.check(f"it leaves your hands within {allowed:.1f} s ({kg:.0f} kg)",
            let_go is not None and let_go["t"] <= allowed,
            f"{let_go['t']:.2f} s" if let_go else "still held after 4.5 s", let_go or down[-1])
    still = None
    if let_go is not None:
        after = down[down.index(let_go):]
        for a, b in zip(after, after[1:]):
            pa, pb = it(a, name), it(b, name)
            if pa and pb and sum((pa["centre"][k] - pb["centre"][k]) ** 2 for k in range(3)) ** 0.5 < 0.004:
                still = b
                break
    end = down[-1]
    final = it(end, name)
    warned = getattr(j, "promise", "green") != "green"
    fell = bool(final) and let_go is not None and \
        abs(final["tilt"] - (it(let_go, name) or final)["tilt"]) > FALLEN_DEG
    if not warned:
        # A green preview is a promise: it lands there, stays up, and is still.
        j.check(f"it lies still within {REST_WITHIN_S} s", still is not None and still["t"] <= REST_WITHIN_S,
                f"{still['t']:.2f} s" if still else "still moving", still or down[-1])
        if ghost_then is not None and final:
            off = ((final["centre"][0] - ghost_then["at"][0]) ** 2
                   + (final["centre"][2] - ghost_then["at"][2]) ** 2) ** 0.5
            j.check(f"it lands where the preview showed (within {LANDS_WITHIN_M} m)",
                    off <= LANDS_WITHIN_M, f"{off:.2f} m away", end)
        if final:
            j.check("it stays standing, as the green preview promised", not fell,
                    f"it fell over ({final['tilt']:.0f} degrees from upright)" if fell else
                    f"{final['tilt']:.0f} degrees from upright", end)
    elif ghost_then is not None and let_go is not None:
        # Warned it may fall, and nowhere green in reach: it must still go
        # where it was shown. What it does after that is what it was warned of.
        at = it(let_go, name)
        off = ((at["centre"][0] - ghost_then["at"][0]) ** 2
               + (at["centre"][2] - ghost_then["at"][2]) ** 2) ** 0.5
        j.check(f"it is let go where the preview showed (within {LANDS_WITHIN_M} m)",
                off <= LANDS_WITHIN_M,
                f"{off:.2f} m away when let go; warned {j.warning!r}, and then it "
                + ("fell over" if fell else "stayed up"), let_go)
    if final:
        j.check("it is not in the ground", final["lowest"] >= final["ground"] - 0.05,
                f"underside {final['lowest']:.3f}, ground {final['ground']:.3f}", end)
        j.check("it is in one piece", final["parts"] == rest["parts"] and final["cells"] == rest["cells"],
                f"{final['parts']} parts, {final['cells']} cells (was {rest['parts']}, {rest['cells']})", end)
    # What it says once it is done -- not "Putting it down...", and not the
    # message still up from picking it up.
    told = [f for f in down if fresh(f) and not f["snap"]["said"]["loud"].startswith("Putting")]
    said = told[-1] if told else None
    j.check("the screen says what happened",
            said is not None and not said["snap"]["said"]["refused"],
            repr(said["snap"]["said"]["loud"]) if said else "nothing new was said", said or end)
    j.check("your hands are empty on screen", end["snap"]["said"]["held"] == "nothing",
            f"hands: {end['snap']['said']['held']!r}", end)

    # --- E again: take it back up --------------------------------------------
    if final and let_go is not None:
        page.js(f"banjoExplorer.aimAt({json.dumps(final['aim'])})")
        time.sleep(0.4)
        pressed = page.key("KeyE")
        again = film(page, names, 1.6, pressed, "E: take it again")
        j.frames += again
        back = first(again, lambda f: (it(f, name) or {}).get("held"))
        j.check(f"E takes it up again within {TAKE_WITHIN_S} s",
                back is not None and back["t"] <= TAKE_WITHIN_S,
                f"{back['t']:.2f} s" if back else f"not held; in front: {again[-1]['snap']['said']['inFront']!r}",
                back or again[-1])
        if back is not None:
            pressed = page.key("KeyX")
            gone = film(page, names, 2.0, pressed, "X: let go")
            j.frames += gone
            out = first(gone, lambda f: not (it(f, name) or {}).get("held"))
            j.check(f"X lets go within {RELEASE_WITHIN_S} s", out is not None and out["t"] <= RELEASE_WITHIN_S,
                    f"{out['t']:.2f} s" if out else "still held", out or gone[-1])
    stalled(j)
    return j


def stalled(j: Journey) -> None:
    """The world keeps running the whole time. The page steps it from its frame
    loop, which waits on each step: one step that never comes back stops the
    world and the drawing while the screen goes on looking perfectly normal --
    the ice block froze in mid-air this way, "held" for ever."""
    worst, where, began = 0.0, None, None
    for a, b in zip(j.frames, j.frames[1:]):
        if b["snap"]["t"] > a["snap"]["t"] + 1e-9:
            began = None
            continue
        began = began or a
        span = (b["snap"]["now"] - began["snap"]["now"]) / 1000.0
        if span > worst:
            worst, where = span, b
    waiting = ", ".join(f"{w['path']}{' ' + w['op'] if w['op'] else ''} for {w['for_s']:.1f} s"
                        for w in (where or {"snap": {"waiting": []}})["snap"].get("waiting", []))
    j.check("the world keeps running (never still for more than 0.5 s)", worst <= 0.5,
            f"stopped for {worst:.1f} s" + (f"; the page was waiting on {waiting}" if waiting else "")
            if worst > 0.5 else "it ran throughout", where)


# --------------------------------------------------------------------------
# What it looked like
# --------------------------------------------------------------------------

try:
    FONT = ImageFont.truetype("segoeui.ttf", 22)
    SMALL = ImageFont.truetype("segoeui.ttf", 17)
except OSError:
    FONT = SMALL = ImageFont.load_default()


def marked(frame: dict, name: str, scale: float = 0.5) -> Image.Image:
    """The frame, with the sight, the thing and the preview drawn on it."""
    image = Image.open(io.BytesIO(frame["jpeg"])).convert("RGB")
    draw = ImageDraw.Draw(image)
    snap = frame["snap"]
    thing = snap["things"].get(name)
    if thing and thing.get("box"):
        b = thing["box"]
        draw.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=(255, 214, 90), width=3)
    ghost = snap.get("ghost")
    if ghost and ghost.get("box"):
        b = ghost["box"]
        colour = (120, 230, 170) if ghost["colour"].lower() in ("#a2e1c8", "#ffd195") else (255, 120, 110)
        draw.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=colour, width=3)
    s = snap["sight"]
    draw.ellipse([s["x"] - 11, s["y"] - 11, s["x"] + 11, s["y"] + 11], outline=(255, 255, 255), width=2)
    held = "HELD" if thing and thing.get("held") else "on the ground"
    said = snap["said"]["loud"] or ""
    draw.rectangle([0, 0, 900, 62], fill=(0, 0, 0))
    draw.text((10, 4), f"{frame['phase']}   {frame['t']:+.2f} s   {held}", fill=(255, 255, 255), font=FONT)
    if said:
        draw.text((10, 34), said[:95], fill=(255, 150, 130) if snap["said"]["refused"] else (160, 230, 200),
                  font=SMALL)
    return image.resize((int(W * scale), int(H * scale)), Image.LANCZOS)


def key_frames(j: Journey) -> list[dict]:
    """Before, holding it, the preview, and put down."""
    by = {}
    for f in j.frames:
        by.setdefault(f["phase"], []).append(f)
    picks = []
    for phase in ("looking at it", "E: take it", "look down: the preview", "E: put it down"):
        if by.get(phase):
            picks.append(by[phase][-1])
    return picks


def write_report(out: Path, journeys: list[Journey], meta: dict) -> None:
    frames_dir = out / "frames"
    frames_dir.mkdir(exist_ok=True)
    # Every frame's numbers too, for reading a failure frame by frame.
    (out / "frames.json").write_text(json.dumps(
        {j.name: [{"phase": f["phase"], "t": f["t"], "snap": f["snap"]} for f in j.frames]
         for j in journeys}, indent=1), encoding="utf-8")
    rows = []
    for j in journeys:
        picks = key_frames(j)
        if picks:
            rows.append([marked(f, j.name, 0.3) for f in picks])
        for i, f in enumerate(j.frames):
            marked(f, j.name, 0.5).save(frames_dir / f"{j.name.replace(' ', '_')}-{i:03d}.jpg", quality=80)
        down = [f for f in j.frames if f["phase"] == "E: put it down"]
        if down:
            gif = [marked(f, j.name, 0.4) for f in down]
            gif[0].save(out / f"{j.name.replace(' ', '_')}-put-down.gif", save_all=True,
                        append_images=gif[1:], duration=100, loop=0)
    if rows:
        tw, th = rows[0][0].size
        sheet = Image.new("RGB", (tw * 4 + 250, th * len(rows)), (12, 20, 24))
        d = ImageDraw.Draw(sheet)
        for r, (j, row) in enumerate(zip([j for j in journeys if key_frames(j)], rows)):
            passed = sum(c["ok"] for c in j.checks)
            d.text((12, r * th + 12), j.name, fill=(255, 255, 255), font=FONT)
            d.text((12, r * th + 44), f"{passed}/{len(j.checks)} checks",
                   fill=(160, 230, 200) if passed == len(j.checks) else (255, 150, 130), font=SMALL)
            for c, image in enumerate(row):
                sheet.paste(image, (250 + c * tw, r * th))
        sheet.save(out / "sheet.png")

    parts = [f"<!doctype html><meta charset=utf-8><title>Explorer visual QA</title>",
             "<style>body{font:15px system-ui;background:#0c1418;color:#dfe9ec;margin:24px}"
             "table{border-collapse:collapse;margin:8px 0 18px}td,th{padding:4px 10px;border-bottom:1px solid #243238;text-align:left}"
             ".ok{color:#8fe0b8}.no{color:#ff9f91}.strip{display:flex;gap:6px;overflow-x:auto;padding-bottom:8px}"
             ".strip img{height:170px;border:1px solid #243238}h2{margin-top:34px}</style>",
             f"<h1>Explorer visual QA</h1><p>{html.escape(meta['when'])} · commit {html.escape(meta['commit'])} · "
             f"{html.escape(meta['view'])} · the room ran at {meta['pace']}</p>",
             "<p>Yellow: where the engine says the thing is. Green/red: the preview. White ring: the sight.</p>",
             "<img src=sheet.png style='max-width:100%'>"]
    for j in journeys:
        passed = sum(c["ok"] for c in j.checks)
        parts.append(f"<h2>{html.escape(j.name)} <span class={'ok' if passed == len(j.checks) and j.checks else 'no'}>"
                     f"{passed}/{len(j.checks)}</span> {html.escape(j.note)}</h2><table>")
        for c in j.checks:
            link = (f"<a href='frames/{j.name.replace(' ', '_')}-{c['frame']:03d}.jpg'>frame {c['frame']}</a>"
                    if c["frame"] is not None else "")
            parts.append(f"<tr><td class={'ok' if c['ok'] else 'no'}>{'PASS' if c['ok'] else 'FAIL'}</td>"
                         f"<td>{html.escape(c['what'])}</td><td>{html.escape(c['got'])}</td><td>{link}</td></tr>")
        parts.append("</table><div class=strip>")
        for i, f in enumerate(j.frames):
            parts.append(f"<img title='{html.escape(f['phase'])} {f['t']:+.2f}s' "
                         f"src='frames/{j.name.replace(' ', '_')}-{i:03d}.jpg'>")
        parts.append("</div>")
    if meta["errors"]:
        parts.append("<h2 class=no>The page threw</h2><pre>" + html.escape("\n".join(meta["errors"])) + "</pre>")
    (out / "report.html").write_text("\n".join(parts), encoding="utf-8")


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", help="just these things")
    ap.add_argument("--port", type=int, help="use a server already running here instead of starting one")
    ap.add_argument("--keep-server", action="store_true")
    ap.add_argument("--scene", default="explore",
                    help="the room to open (world_room.SCENES), e.g. tests-carry")
    args = ap.parse_args(argv)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "build" / "visual-qa" / stamp
    out.mkdir(parents=True, exist_ok=True)
    server = None
    if args.port:
        port = args.port
    else:
        server, port = start_server(out)
    chrome = None
    try:
        chrome = qa_browser.Chrome(W, H)
        page = Page(chrome)
        page.js(f'location.href = "http://127.0.0.1:{port}/explore?scene={args.scene}"')
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            time.sleep(0.5)
            try:
                up = page.js("window.banjoExplorer && banjoExplorer.status().session "
                             "&& banjoExplorer.status().bodies > 0 && banjoExplorer.status().pace > 0")
            except RuntimeError:
                up = False
            if up:
                break
        else:
            raise SystemExit("the Explorer never opened")
        time.sleep(1.5)
        there = set(page.js("banjoExplorer.names()"))
        wanted = [t for t in (args.only or THINGS) if t in there]
        journeys = []
        for name in wanted:
            j = journey(page, name)
            journeys.append(j)
            passed = sum(c["ok"] for c in j.checks)
            if name in KNOWN:
                j.note = f"KNOWN: {KNOWN[name]}"
            print(f"{name:<12} {passed:>2}/{len(j.checks):<2} " + ("KNOWN " if name in KNOWN else "") +
                  "  ".join(f"FAIL {c['what']} ({c['got']})" for c in j.checks if not c["ok"]))
        pace = page.js("banjoExplorer.status().pace")
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        write_report(out, journeys, {"when": stamp, "commit": commit, "view": f"{W}x{H}",
                                     "pace": f"{pace:.1f}x realtime", "errors": page.errors()})
        failed = sum(not c["ok"] for j in journeys for c in j.checks if j.name not in KNOWN)
        known = sum(not c["ok"] for j in journeys for c in j.checks if j.name in KNOWN)
        print(f"\n{sum(len(j.checks) for j in journeys) - failed - known} passed, {failed} failed"
              + (f", {known} failed on things KNOWN not to be whole yet" if known else ""))
        print(f"report: {out / 'report.html'}")
        return 0 if failed == 0 and journeys else 1
    finally:
        if chrome is not None:
            chrome.close()
        if not args.keep_server:
            stop(server)


if __name__ == "__main__":
    raise SystemExit(main())
