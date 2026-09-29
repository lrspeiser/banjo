"""The abandoned workings, photographed where the engine says they are.

The valley is not empty ground: somebody found the vein where it broke surface,
followed it in an open cut, sank a shaft at the end of it when the cut got too
deep to throw spoil out of, cut an adit mouth into the hillside lower down, and
left the spoil in heaps (docs/earth-and-mining-plan.md). The terrain block says
where each piece is; this stands off each one and takes its picture.

    python tests/mine_site_shots.py --port 18875
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

MINE = """
(async () => {
  const status = await (await fetch("/api/status")).json();
  const said = await (await fetch("/api/live/act", { method: "POST",
      headers: { "Content-Type": "application/json", "X-Banjo-Token": status.csrf_token },
      body: JSON.stringify({ session: window.banjoRoom.world.session, op: "terrain" }) })).json();
  return (said.terrain || {}).mine || null;
})()
"""

SURVEY = """
(async () => {
  const status = await (await fetch("/api/status")).json();
  const said = await (await fetch("/api/live/act", { method: "POST",
      headers: { "Content-Type": "application/json", "X-Banjo-Token": status.csrf_token },
      body: JSON.stringify({ session: window.banjoRoom.world.session, op: "survey",
                             at: [%(x)s, %(z)s] }) })).json();
  return said.survey || null;
})()
"""

STAND = """
(() => {
  window.banjoRoom.standAt(%(x)s, %(y)s, %(z)s);
  window.banjoRoom.lookAt(%(lx)s, %(ly)s, %(lz)s);
  return true;
})()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=18875)
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "mine-site")
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
        # The first ask after a server restart can land before the page has its
        # session, and an empty answer then is a race, not a valley with nothing
        # in it. Ask again before believing it.
        mine = None
        for _ in range(10):
            mine = page.evaluate(MINE, await_promise=True, timeout=60)
            if mine:
                break
            time.sleep(1.0)
        if not mine:
            print("this valley was never worked, or the page never got a session")
            return 1
        print("what they left:", json.dumps(mine, indent=1))

        def survey(x, z, what):
            said = page.evaluate(SURVEY % {"x": x, "z": z}, await_promise=True, timeout=30)
            if not said:
                return None
            runs = ", ".join(f"{r['material']} to {r['to_m']:+.2f}" for r in (said.get("runs") or []))
            print(f"  {what:>12}: ground {said['ground_m']:+.2f} m, {runs}")
            return said

        print("the ground at each piece of it:")
        survey(*mine["cut_from_m"], "cut, at the outcrop")
        survey(*mine["cut_to_m"], "cut, far end")
        survey(*mine["shaft_m"], "shaft collar")
        survey(*mine["adit_m"], "adit mouth")

        def shoot(name, at, back, up, look_down=0.8):
            here = survey(at[0], at[1], "") or {"ground_m": 0.0}
            page.evaluate(STAND % {"x": at[0] + back[0], "y": here["ground_m"] + up,
                                   "z": at[1] + back[1], "lx": at[0],
                                   "ly": here["ground_m"] - look_down, "lz": at[1]}, timeout=10)
            time.sleep(1.0)
            qa_browser._shoot(page, args.out / name)

        # The whole working from across the valley, then each piece of it from
        # far enough back to be outside the spoil.
        mx = 0.5 * (mine["cut_from_m"][0] + mine["cut_to_m"][0])
        mz = 0.5 * (mine["cut_from_m"][1] + mine["cut_to_m"][1])
        ax = mine["cut_to_m"][0] - mine["cut_from_m"][0]
        az = mine["cut_to_m"][1] - mine["cut_from_m"][1]
        n = max(1e-6, (ax * ax + az * az) ** 0.5)
        # Perpendicular to the working, so its whole length is across the view.
        px, pz = -az / n, ax / n
        shoot("site.png", [mx, mz], (px * 13.0, pz * 13.0), 11.0, 4.0)
        shoot("shaft.png", mine["shaft_m"], (px * 5.0, pz * 5.0), 3.4, 2.4)
        shoot("cut.png", mine["cut_from_m"], (px * 5.0, pz * 5.0), 3.0, 1.6)
        shoot("adit.png", mine["adit_m"],
              (-mine["adit_into"][0] * 6.0, -mine["adit_into"][1] * 6.0), 2.4, 1.2)
        print("shots in", args.out)
        return 0
    finally:
        chrome.close()


if __name__ == "__main__":
    raise SystemExit(main())
