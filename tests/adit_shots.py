"""Inside the old adit: standing in it, and looking out of it.

The tunnel is real to the solver (tests/valley_live_tests.cpp, "the adit is a
hole with rock over it"). This is the other half: the page drawing it, and a
person standing on its floor instead of being shoved up onto the hill over it.

    python tests/adit_shots.py --port 18875
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

# Every column the page knows to be a working, off the runs it already holds.
WORKINGS = """
(async () => {
  const status = await (await fetch("/api/status")).json();
  const said = await (await fetch("/api/live/act", { method: "POST",
      headers: { "Content-Type": "application/json", "X-Banjo-Token": status.csrf_token },
      body: JSON.stringify({ session: window.banjoRoom.world.session, op: "terrain" }) })).json();
  const t = said.terrain; if (!t) return null;
  const raw = atob(t.runs_b64), g = t.grid, floor = t.floor_m;
  const found = [];
  let at = 0;
  for (let c = 0; c < g.nx * g.nz; ++c) {
    const n = raw.charCodeAt(at++);
    let below = floor, hole = null, top = floor;
    for (let k = 0; k < n; ++k) {
      const kind = raw.charCodeAt(at);
      const h = floor + (raw.charCodeAt(at + 1) | (raw.charCodeAt(at + 2) << 8)) / 1000;
      if (kind === 8) hole = { floor: below, roof: h };
      below = h; top = h; at += 3;
    }
    if (hole) found.push({ x: +(g.x0_m + (c % g.nx) * g.cell_m).toFixed(3),
                           z: +(g.z0_m + Math.floor(c / g.nx) * g.cell_m).toFixed(3),
                           floor: +hole.floor.toFixed(3), roof: +hole.roof.toFixed(3),
                           hill: +top.toFixed(3) });
  }
  return { count: found.length, middle: found[Math.floor(found.length / 2)],
           deepest: found.reduce((a, b) => (b.hill - b.roof > a.hill - a.roof ? b : a), found[0]) };
})()
"""

STAND = """
(() => {
  window.banjoRoom.standAt(%(x)s, %(y)s, %(z)s);
  window.banjoRoom.lookAt(%(lx)s, %(ly)s, %(lz)s);
  return true;
})()
"""

# Where the page thinks the person is standing, after it has settled them.
WHERE = """
(async () => {
  await new Promise((r) => setTimeout(r, 900));
  const c = window.banjoRoom.camera.position;
  return { x: +c.x.toFixed(3), y: +c.y.toFixed(3), z: +c.z.toFixed(3),
           details: (document.querySelector("#details") || {}).textContent || "" };
})()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=18875)
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "adit")
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
        found = None
        for _ in range(10):
            found = page.evaluate(WORKINGS, await_promise=True, timeout=60)
            if found:
                break
            time.sleep(1.0)
        if not found or not found["count"]:
            print("the page sees no working in this valley")
            return 1
        print(f"the page sees {found['count']} columns of working")
        deep = found["deepest"]
        print("the deepest of it:", json.dumps(deep))

        # Stand in it, eye a little under the roof, and look along it.
        eye = min(deep["floor"] + 1.6, deep["roof"] - 0.1)
        page.evaluate(STAND % {"x": deep["x"], "y": eye, "z": deep["z"] - 1.2,
                               "lx": deep["x"], "ly": eye - 0.15, "lz": deep["z"] + 2.0}, timeout=10)
        where = page.evaluate(WHERE, await_promise=True, timeout=30)
        print(f"put at y={eye:.2f} inside it, the page settled the eye at y={where['y']:.2f}"
              f" (its floor is {deep['floor']:.2f}, its roof {deep['roof']:.2f},"
              f" the hill over it {deep['hill']:.2f})")
        print("underfoot:", (where.get("details") or "").split("·")[0][:110])
        qa_browser._shoot(page, args.out / "inside.png")

        # And from outside, looking at the hill it is under.
        page.evaluate(STAND % {"x": deep["x"] + 4.0, "y": deep["hill"] + 2.0, "z": deep["z"] - 5.0,
                               "lx": deep["x"], "ly": deep["floor"], "lz": deep["z"]}, timeout=10)
        time.sleep(1.0)
        qa_browser._shoot(page, args.out / "outside.png")
        print("shots in", args.out)
        return 0
    finally:
        chrome.close()


if __name__ == "__main__":
    raise SystemExit(main())
