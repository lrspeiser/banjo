"""Electric light underground, in the page.

The engine's half is checked in `tests/solar_panel_tests.cpp`. This is the other
half: the tunnel dark because there is rock over it, the lamps on the cable
lighting it, and the run of cable visible along the roof.

Three shots, and the numbers behind each one:
  dark.png    the heading with the lamps switched off -- what a mine looks like
  lit.png     the same view with them on
  farm.png    the solar farm on the hill, and the cable running down to the adit

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

# What the page has been told about the lamps and the run, and how dark it is
# where the eye stands.
LIGHTS = """
(() => {
  const m = window.banjoRoom.world.machines || {};
  const eye = window.banjoRoom.camera.position;
  return { lamps: (m.lamps || []).map((l) => ({ name: l.name, on: l.on, lit: l.lit,
                                                drawn_w: l.drawn_w, lumens: l.lumens, why: l.why,
                                                at: l.at_m })),
           cables: (m.cables || []).map((c) => ({ name: c.name, length_m: c.length_m,
                                                  resistance_ohm: c.resistance_ohm,
                                                  current_a: c.current_a, volts_lost: c.volts_lost,
                                                  loss_w: c.loss_w, carried_w: c.carried_w })),
           stores: (m.stores || []).map((s) => ({ name: s.name, charge_j: s.charge_j })),
           eye: { x: +eye.x.toFixed(2), y: +eye.y.toFixed(2), z: +eye.z.toFixed(2) } };
})()
"""

SWITCH = """
(async () => {
  const status = await (await fetch("/api/status")).json();
  const said = [];
  for (const lamp of (window.banjoRoom.world.machines.lamps || [])) {
    said.push(await (await fetch("/api/live/act", { method: "POST",
      headers: { "Content-Type": "application/json", "X-Banjo-Token": status.csrf_token },
      body: JSON.stringify({ session: window.banjoRoom.world.session, op: "lamp_switch",
                             lamp: lamp.id, on: %(on)s }) })).json());
  }
  return said.length;
})()
"""

STAND = """
(() => {
  window.banjoRoom.standAt(%(x)s, %(y)s, %(z)s);
  window.banjoRoom.lookAt(%(lx)s, %(ly)s, %(lz)s);
  return true;
})()
"""

# How bright a shot actually is: the mean of the PNG the page gave us, over the
# part of it the world is drawn in. Read from the file and not from the canvas --
# the page's WebGL context does not keep its drawing buffer, so reading the
# canvas back from a script gives black whatever is on the screen.
def brightness(png: Path) -> float:
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
    # The side panel is its own thing and always lit; only the world is measured.
    world = int(width * 0.7)
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
        # Let the room take a few steps so the lamps have drawn something.
        for _ in range(30):
            time.sleep(0.5)
            said = page.evaluate(LIGHTS, timeout=20)
            if said and said.get("lamps"):
                break
        if not said or not said.get("lamps"):
            print("the page was told of no lamps")
            return 1
        print(f"{len(said['lamps'])} lamps on {len(said['cables'])} run(s)")
        for c in said["cables"]:
            print(f"  {c['name']}: {c['length_m']:.1f} m, {c['resistance_ohm']:.3f} ohm, "
                  f"{c['current_a']:.2f} A, {c['volts_lost']:.2f} V lost, "
                  f"{c['carried_w']:.1f} W carried, {c['loss_w']:.2f} W lost")
        for l in said["lamps"]:
            print(f"  {l['name']}: {'lit' if l['lit'] else 'dark'} at {l['drawn_w']:.1f} W, "
                  f"{l['lumens']:.0f} lm{(' -- ' + l['why']) if l['why'] else ''}")

        # Stand a third of the way in from the mouth, looking along the heading
        # at the face. Not right under a lamp: the cable is 8 mm and a hand's
        # breadth from the eye it fills the picture.
        face = said["lamps"][-1]["at"]
        mouth = said["lamps"][0]["at"]
        eye = face[1] - 0.55
        third = [mouth[k] + (face[k] - mouth[k]) / 3.0 for k in (0, 2)]
        put = {"x": third[0], "y": eye, "z": third[1],
               "lx": face[0], "ly": eye - 0.1, "lz": face[2]}

        # Dark first: switch them all off, and see what the mine is without them.
        page.evaluate(SWITCH % {"on": "false"}, await_promise=True, timeout=60)
        page.evaluate(STAND % put, timeout=10)
        time.sleep(1.5)
        qa_browser._shoot(page, args.out / "dark.png")
        dark = brightness(args.out / "dark.png")
        where = page.evaluate(LIGHTS, timeout=20)
        print(f"lamps off, standing in the heading at y={where['eye']['y']}: "
              f"the picture is {dark:.3f} bright")

        # Then on.
        page.evaluate(SWITCH % {"on": "true"}, await_promise=True, timeout=60)
        time.sleep(1.5)
        qa_browser._shoot(page, args.out / "lit.png")
        lit = brightness(args.out / "lit.png")
        on = page.evaluate(LIGHTS, timeout=20)
        print(f"lamps on: {lit:.3f} bright -- {lit / max(dark, 1e-6):.1f} times the dark one")
        for l in on["lamps"]:
            print(f"  {l['name']}: {l['drawn_w']:.1f} W, {l['lumens']:.0f} lm")

        # And the farm on the hill, with the cable coming down off it.
        run = on["cables"][0] if on["cables"] else None
        page.evaluate(STAND % {"x": mouth[0] + 8.0, "y": mouth[1] + 5.0, "z": mouth[2] - 9.0,
                               "lx": mouth[0], "ly": mouth[1], "lz": mouth[2]}, timeout=10)
        time.sleep(1.5)
        qa_browser._shoot(page, args.out / "farm.png")
        print("shots in", args.out)
        if run:
            print(json.dumps(run))
        if not (lit > dark * 1.3):
            print("the lamps did not make the picture brighter")
            return 1
        return 0
    finally:
        chrome.close()


if __name__ == "__main__":
    raise SystemExit(main())
