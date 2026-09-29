"""The mining loop in the page: a dark heading, a cable run to it, and light.

The engine's half is checked in `tests/mine_loop_tests.py` and
`tests/solar_panel_tests.cpp`. This is the other half, in the browser, on the
kit room `tools/build_light_room.py` lays out at `/world?scene=tests-light`:
the valley's old adit with a Workshop solar array on the hill, a Workshop mine
lamp standing at the mouth and a Workshop breaker beside it, and NOTHING wired.

It drives the page's own action -- `workTheCable()`, the function the P key is
bound to -- rather than talking to the engine behind the page's back, so what is
photographed is what a person does.

  dark.png    the heading, with a lamp in it that nobody has wired
  lit.png     the same view after the run reaches it
  farm.png    the array on the hill, and the way the cable came down

    python tests/lamp_shots.py --port 18875
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import qa_browser  # noqa: E402

PNG_MAGIC = bytes([137, 80, 78, 71, 13, 10, 26, 10])

READY = """
(() => {
  const room = window.banjoRoom;
  return room && room.scene ? { ready: true, frames: room.world.framesSinceOpen } : { ready: false };
})()
"""

# What the page has been told about the kit, and where the eye is.
KIT = """
(() => {
  const m = window.banjoRoom.world.machines || {};
  const eye = window.banjoRoom.camera.position;
  return { lamps: (m.lamps || []).map((l) => ({ id: l.id, name: l.name, on: l.on, lit: l.lit,
                                                cable: l.cable, drawn_w: l.drawn_w,
                                                lumens: l.lumens, why: l.why, at: l.at_m })),
           cables: (m.cables || []).map((c) => ({ name: c.name, length_m: c.length_m,
                                                  resistance_ohm: c.resistance_ohm,
                                                  current_a: c.current_a, volts_lost: c.volts_lost,
                                                  loss_w: c.loss_w, carried_w: c.carried_w })),
           breakers: (m.breakers || []).map((b) => ({ name: b.name, on: b.on, watts: b.watts,
                                                      why: b.why })),
           stores: (m.stores || []).map((s) => ({ name: s.name, charge_j: s.charge_j })),
           eye: { x: +eye.x.toFixed(2), y: +eye.y.toFixed(2), z: +eye.z.toFixed(2) } };
})()
"""

STAND = """
(() => {
  window.banjoRoom.standAt(%(x)s, %(y)s, %(z)s);
  window.banjoRoom.lookAt(%(lx)s, %(ly)s, %(lz)s);
  return true;
})()
"""

# The page's own wiring action, twice: once looking at the array's battery, once
# at the lamp. Between them the drum pays out along the points given, which is
# what walking does.
RUN_THE_CABLE = """
(async () => {
  const page = window.banjoRoom;
  page.world.aim = { name: "solar-array", distance_m: 1.0 };
  await page.workTheCable();
  if (!page.world.laying) return { started: false };
  page.world.laying.points = %(points)s;
  page.world.aim = { name: "mine-lamp", distance_m: 1.0 };
  await page.workTheCable();
  return { started: true, laying: !!page.world.laying,
           said: (document.querySelector("#details-last-text") || {}).textContent || "" };
})()
"""


def brightness(png: Path) -> float:
    """The mean of the world side of a shot: the only honest way to say one
    picture is darker than another.

    Read from the file, not the canvas -- the page's WebGL context does not keep
    its drawing buffer, so reading the canvas back from a script gives black
    whatever is on the screen.
    """
    raw = png.read_bytes()
    if raw[:8] != PNG_MAGIC:
        raise ValueError(f"{png} is not a PNG")
    at, width, height, colour, data = 8, 0, 0, 0, b""
    while at < len(raw):
        length = int.from_bytes(raw[at:at + 4], "big")
        kind, body = raw[at + 4:at + 8], raw[at + 8:at + 8 + length]
        at += 12 + length
        if kind == b"IHDR":
            width = int.from_bytes(body[0:4], "big")
            height = int.from_bytes(body[4:8], "big")
            colour = body[9]
        elif kind == b"IDAT":
            data += body
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour)
    if channels is None or channels < 3:
        raise ValueError(f"{png}: a colour image is wanted, not type {colour}")
    px = zlib.decompress(data)
    stride = width * channels
    world = int(width * 0.7)          # the side panel is its own thing, always lit
    previous, total, seen, i = bytearray(stride), 0.0, 0, 0
    for _ in range(height):
        how, i = px[i], i + 1
        line = bytearray(px[i:i + stride])
        i += stride
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b = previous[x]
            c = previous[x - channels] if x >= channels else 0
            if how == 1:
                line[x] = (line[x] + a) & 255
            elif how == 2:
                line[x] = (line[x] + b) & 255
            elif how == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif how == 4:
                guess = a + b - c
                da, db, dc = abs(guess - a), abs(guess - b), abs(guess - c)
                line[x] = (line[x] + (a if da <= db and da <= dc else (b if db <= dc else c))) & 255
        previous = line
        for x in range(0, world * channels, channels):
            total += 0.2126 * line[x] + 0.7152 * line[x + 1] + 0.0722 * line[x + 2]
            seen += 1
    return round(total / seen / 255.0, 4)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=18875)
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "mine-light")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    chrome = qa_browser.Chrome()
    try:
        page = chrome.page
        page.send("Page.enable")
        page.send("Runtime.enable")
        page.send("Page.navigate", {"url": f"http://127.0.0.1:{args.port}/world?scene=tests-light"})
        for _ in range(80):
            time.sleep(0.5)
            seen = page.evaluate(READY, timeout=20)
            if seen and seen.get("ready") and seen.get("frames", 0) > 5:
                break
        kit = None
        for _ in range(30):
            time.sleep(0.5)
            kit = page.evaluate(KIT, timeout=20)
            if kit and kit.get("lamps"):
                break
        if not kit or not kit.get("lamps"):
            print("the page was told of no lamp")
            return 1
        lamp = kit["lamps"][0]
        print(f"the kit: a {kit['breakers'][0]['watts']:.0f} W breaker, a {lamp['name']} "
              f"({'lit' if lamp['lit'] else 'dark'} -- {lamp['why']}), "
              f"and {len(kit['stores'])} batteries; {len(kit['cables'])} runs of cable")
        if lamp["lit"] or lamp["cable"]:
            print("the lamp is already wired: this room is meant to start with nothing wired")
            return 1

        # Stand in the heading, a little way back from the lamp, looking at it.
        at = lamp["at"]
        eye = at[1] + 1.1
        page.evaluate(STAND % {"x": at[0] - 1.6, "y": eye, "z": at[2] + 0.4,
                               "lx": at[0], "ly": at[1] + 0.3, "lz": at[2]}, timeout=10)
        time.sleep(1.5)
        qa_browser._shoot(page, args.out / "dark.png")
        dark = brightness(args.out / "dark.png")
        print(f"  standing in the heading with an unwired lamp in it: {dark:.3f} bright")

        # Run the cable, through the page's own action. The points are the way
        # somebody would walk it: off the array, down the slope, in at the mouth.
        array_at = [at[0] - 3.5, at[1] + 3.0, at[2] + 5.3]
        walk = [array_at,
                [at[0] - 2.0, at[1] + 2.6, at[2] + 3.0],
                [at[0] - 0.6, at[1] + 1.5, at[2] + 0.6],
                [at[0], at[1] + 1.4, at[2]]]
        said = page.evaluate(RUN_THE_CABLE % {"points": json.dumps(walk)},
                             await_promise=True, timeout=60)
        print("  the page's own wiring action:", json.dumps(said))
        if not said or not said.get("started") or said.get("laying"):
            print("the run did not go in")
            return 1
        time.sleep(1.5)
        wired = page.evaluate(KIT, timeout=20)
        run = (wired.get("cables") or [{}])[0]
        lamp = wired["lamps"][0]
        print(f"  {run.get('length_m', 0):.1f} m of cable, {run.get('resistance_ohm', 0):.3f} ohm, "
              f"{run.get('volts_lost', 0):.2f} V lost: the lamp is "
              f"{'lit' if lamp['lit'] else 'dark'} at {lamp['drawn_w']:.1f} W, "
              f"{lamp['lumens']:.0f} lumens")
        qa_browser._shoot(page, args.out / "lit.png")
        lit = brightness(args.out / "lit.png")
        print(f"  the same view, lit: {lit:.3f} bright -- {lit / max(dark, 1e-6):.0f} times the dark one")

        # And the array on the hill, with the run coming down off it.
        page.evaluate(STAND % {"x": array_at[0] + 4.0, "y": array_at[1] + 2.5, "z": array_at[2] + 4.0,
                               "lx": array_at[0], "ly": array_at[1], "lz": array_at[2]}, timeout=10)
        time.sleep(1.5)
        qa_browser._shoot(page, args.out / "farm.png")
        print("shots in", args.out)
        if not lamp["lit"]:
            print("the lamp did not light")
            return 1
        if not (lit > dark * 1.3):
            print("the lamp did not make the picture brighter")
            return 1
        return 0
    finally:
        chrome.close()


if __name__ == "__main__":
    raise SystemExit(main())
