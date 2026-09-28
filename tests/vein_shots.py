"""The vein: found by looking, then looked at.

The valley's rock has a mantle of weathered rock, a bed of clay dipping under
it, and a vein of ore cutting through both, its top oxidised where the weather
has reached it (docs/earth-and-mining-plan.md, stage 2). This asks the engine
where the vein reaches the surface -- the way a person spots a stain on a
hillside -- and photographs it, then photographs what a survey says about the
column underneath.

    python tests/vein_shots.py --port 18875
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import qa_browser  # noqa: E402

READY = """
(() => {
  const room = window.banjoRoom;
  return room && room.scene ? { ready: true, frames: room.world.framesSinceOpen } : { ready: false };
})()
"""

# Every column's top material, from the runs the page holds: where the vein
# reaches daylight, and what the valley is made of on top.
OUTCROPS = """
(async () => {
  const status = await (await fetch("/api/status")).json();
  const act = async (body) => (await (await fetch("/api/live/act", { method: "POST",
      headers: { "Content-Type": "application/json", "X-Banjo-Token": status.csrf_token },
      body: JSON.stringify({ session: window.banjoRoom.world.session, ...body }) })).json());
  const ground = (await act({ op: "terrain" })).terrain;
  const raw = atob(ground.runs_b64), grid = ground.grid;
  const floor = ground.floor_m;
  const names = ["rock", "soil", "sand", "loose soil", "weathered rock", "clay", "ore", "oxidised ore"];
  const tally = {}, found = [];
  let at = 0;
  for (let c = 0; c < grid.nx * grid.nz; ++c) {
    const count = raw.charCodeAt(at++);
    let kind = 0, deepest = [];
    for (let k = 0; k < count; ++k) {
      kind = raw.charCodeAt(at);
      deepest.push([names[kind], floor + (raw.charCodeAt(at + 1) | (raw.charCodeAt(at + 2) << 8)) / 1000]);
      at += 3;
    }
    const name = names[kind];
    tally[name] = (tally[name] || 0) + 1;
    if (name === "oxidised ore" || name === "ore")
      found.push({ x: +(grid.x0_m + (c % grid.nx) * grid.cell_m).toFixed(2),
                   z: +(grid.z0_m + Math.floor(c / grid.nx) * grid.cell_m).toFixed(2) });
  }
  return { tally, outcrops: found.length,
           middle: found.length ? found[Math.floor(found.length / 2)] : null };
})()
"""

STAND = """
(() => {
  window.banjoRoom.standAt(%(x)s, %(y)s, %(z)s);
  window.banjoRoom.lookAt(%(lx)s, %(ly)s, %(lz)s);
  return true;
})()
"""

SURVEY = """
(async () => {
  const status = await (await fetch("/api/status")).json();
  const said = await (await fetch("/api/live/act", { method: "POST",
      headers: { "Content-Type": "application/json", "X-Banjo-Token": status.csrf_token },
      body: JSON.stringify({ session: window.banjoRoom.world.session, op: "survey",
                             at: [%(x)s, %(z)s] }) })).json();
  return (said.survey || {}).runs || null;
})()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=18875)
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "vein")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    chrome = qa_browser.Chrome()
    try:
        page = chrome.page
        page.send("Page.enable")
        page.send("Runtime.enable")
        page.send("Page.navigate", {"url": f"http://127.0.0.1:{args.port}/world?scene=world"})
        for _ in range(60):
            time.sleep(0.5)
            seen = page.evaluate(READY, timeout=20)
            if seen and seen.get("ready") and seen.get("frames", 0) > 5:
                break
        found = page.evaluate(OUTCROPS, await_promise=True, timeout=120)
        print("what the valley shows on top:", json.dumps(found["tally"]))
        print(f"columns where the vein reaches daylight: {found['outcrops']}")
        if not found["middle"]:
            print("the vein does not reach the surface anywhere")
            return 1
        at = found["middle"]
        print("standing off the outcrop at", json.dumps(at))

        runs = page.evaluate(SURVEY % {"x": at["x"], "z": at["z"]}, await_promise=True, timeout=30)
        print("the column under it:")
        for r in runs or []:
            print(f"   {r['material']:>14}  to {r['to_m']:+.2f} m  ({r['thickness_m']:.2f} m thick)")

        # From across the valley, then close.
        for name, back, up in (("outcrop-far.png", 9.0, 5.0), ("outcrop-near.png", 3.0, 1.6)):
            page.evaluate(STAND % {"x": at["x"] + back * 0.7, "y": 6.0 + up, "z": at["z"] + back,
                                   "lx": at["x"], "ly": 4.5, "lz": at["z"]}, timeout=10)
            time.sleep(1.0)
            qa_browser._shoot(page, args.out / name)
        print("shots in", args.out)
        return 0
    finally:
        chrome.close()


if __name__ == "__main__":
    raise SystemExit(main())
