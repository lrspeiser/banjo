"""The faces of a step, photographed: what the ground is made of, where it is cut.

Opens the valley in the real page in headless Chrome (tests/qa_browser's own
Chrome and DevTools), says how many bands the page built and out of what, digs a
pit the way a person does -- a spadeful at a time, heaping what will not fit
somewhere else -- and photographs the wall it leaves.

    python tests/ground_faces_shots.py --port 18873

The server must be one of your own: this digs in its room.
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

# What the page built, and what it is standing in: read off the scene itself, so
# the answer is what is being drawn and not what the code meant to draw.
LOOK = """
(() => {
  const room = window.banjoRoom;
  if (!room || !room.scene) return { ready: false };
  let faces = null;
  room.scene.traverse((o) => {
    if (o.isMesh && o.material && o.material.side === 2 && o.material.polygonOffset) faces = o;
  });
  const colours = {};
  if (faces) {
    const c = faces.geometry.attributes.color.array;
    for (let v = 0; v < c.length; v += 18) {           // one band, six vertices
      const key = [c[v], c[v + 1], c[v + 2]].map((x) => Math.round(x * 255)).join(",");
      colours[key] = (colours[key] || 0) + 1;
    }
  }
  return { ready: true, frames: room.world.framesSinceOpen,
           bands: faces ? faces.geometry.attributes.position.count / 6 : 0,
           colours, details: (document.querySelector("#details") || {}).textContent || "" };
})()
"""

# The ground under a point, off the mesh that is being drawn: the nearest of its
# own vertices, which is the column the engine sent.
GROUND_AT = """
(() => {
  let mesh = null;
  window.banjoRoom.scene.traverse((o) => {
    if (o.isMesh && o.castShadow && o.geometry && o.geometry.index
        && o.geometry.attributes.color && o.geometry.attributes.position.count > 1000)
      mesh = mesh || o;
  });
  if (!mesh) return null;
  const p = mesh.geometry.attributes.position.array;
  let best = 1e9, y = null;
  for (let k = 0; k < p.length; k += 3) {
    const d = (p[k] - %(x)s) ** 2 + (p[k + 2] - %(z)s) ** 2;
    if (d < best) { best = d; y = p[k + 1]; }
  }
  return y;
})()
"""

STAND = """
(() => {
  window.banjoRoom.standAt(%(x)s, %(y)s, %(z)s);
  window.banjoRoom.lookAt(%(lx)s, %(ly)s, %(lz)s);
  return window.banjoRoom.camera.position.toArray();
})()
"""

# A spadeful, the way the page's own Dig here asks for it, and a heap of what we
# are carrying somewhere else so the next spadeful has room. A person can only
# carry 80 kg, which is why a pit takes more than one go.
SPADEFUL = """
(async () => {
  const status = await (await fetch("/api/status")).json();
  const act = async (body) => (await (await fetch("/api/live/act", { method: "POST",
      headers: { "Content-Type": "application/json", "X-Banjo-Token": status.csrf_token },
      body: JSON.stringify({ session: window.banjoRoom.world.session, ...body }) })).json());
  // Put down what we are carrying first: a spade takes nothing once the person
  // is full, which is how a pit is dug -- a load at a time, and a heap beside it.
  const empty = async () => {
    const said = await act({ op: "terrain" });
    const have = ((said.terrain || {}).carried) || {};
    if ((have.sand_m3 || 0) + (have.soil_m3 || 0) <= 1e-6) return false;
    await act({ op: "deposit", at: [%(hx)s, %(hz)s], radius_m: 1.2,
                sand_m3: have.sand_m3 || 0, soil_m3: have.soil_m3 || 0, from_carried: true });
    return true;
  };
  const heaped = await empty();
  const dug = await act({ op: "dig", from: [%(x)s, %(z)s], to: [%(x)s, %(z)s],
                          width_m: %(w)s, depth_m: %(d)s });
  return { depth_m: (dug.dug || {}).depth_m || 0, kg: (dug.dug || {}).kg || 0,
           heaped, why: dug.error || null };
})()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=18873)
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "ground-faces")
    ap.add_argument("--at", type=float, nargs=2, default=[2.0, -7.0], help="where to dig, x z")
    ap.add_argument("--spadefuls", type=int, default=10)
    ap.add_argument("--width", type=float, default=0.6, help="how wide the pit is")
    ap.add_argument("--dry-above", type=float, default=1.5,
                    help="only dig this far above the valley's own datum, clear of the river")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    x, z = args.at

    chrome = qa_browser.Chrome()
    try:
        page = chrome.page
        page.send("Page.enable")
        page.send("Runtime.enable")
        page.send("Page.navigate", {"url": f"http://127.0.0.1:{args.port}/world?scene=world"})
        seen = None
        for _ in range(60):
            time.sleep(0.5)
            seen = page.evaluate(LOOK, timeout=20)
            if seen and seen.get("ready") and seen.get("frames", 0) > 5:
                break
        print("as it opens:", json.dumps({k: v for k, v in seen.items() if k != "details"}))
        print("underfoot:", (seen.get("details") or "").split("·")[0][:120])

        def stand(eye, look):
            said = page.evaluate(STAND % {"x": eye[0], "y": eye[1], "z": eye[2],
                                          "lx": look[0], "ly": look[1], "lz": look[2]}, timeout=10)
            time.sleep(0.8)
            return said

        # Somewhere worth digging: dry, flat enough, and with something over the
        # rock. A spade stops on rock, and most of this valley's walls are rock
        # under a few millimetres of soil.
        spot = page.evaluate("""
        (async () => {
          const status = await (await fetch("/api/status")).json();
          const act = async (body) => (await (await fetch("/api/live/act", { method: "POST",
              headers: { "Content-Type": "application/json", "X-Banjo-Token": status.csrf_token },
              body: JSON.stringify({ session: window.banjoRoom.world.session, ...body }) })).json());
          let best = null;
          for (let x = -14; x <= 14; x += 2)
            for (let z = -12; z <= 12; z += 2) {
              const said = (await act({ op: "survey", at: [x, z] })).survey;
              if (!said || !said.on_the_ground || said.water) continue;
              // Well clear of the river, or the pit fills before it is a pit:
              // a hole dug beside a channel is a hole the channel runs into.
              if (!(said.ground_m >= %(dry)s) || said.slope_deg > 25) continue;
              // The pit worth photographing cuts through MORE THAN ONE material,
              // so what is wanted is the column with the most of its second
              // material, not the deepest one.
              const loose = (said.sand_m || 0) + (said.loose_soil_m || 0);
              const over = Math.min(loose, said.soil_m || 0);
              if (!best || over > best.over) best = { x, z, over, ground_m: said.ground_m,
                                                      loose_m: loose, soil_m: said.soil_m,
                                                      slope: said.slope_deg,
                                                      runs: (said.runs || []).length };
            }
          return best;
        })()
        """ % {"dry": args.dry_above}, await_promise=True, timeout=120)
        print("digging where the ground is deepest:", json.dumps(spot))
        if spot:
            x, z = spot["x"], spot["z"]
        here = page.evaluate(GROUND_AT % {"x": x, "z": z}, timeout=20)
        print(f"the ground at ({x}, {z}) is {here:.3f} m up")

        stand([x, here + 1.5, z + 3.0], [x, here - 0.2, z])
        qa_browser._shoot(page, args.out / "before.png")

        # A pit, a spadeful at a time.
        for n in range(args.spadefuls):
            did = page.evaluate(SPADEFUL % {"x": x, "z": z, "w": args.width, "d": 1.4,
                                            "hx": x + 3.5, "hz": z + 3.5},
                                await_promise=True, timeout=60)
            if n in (0, args.spadefuls - 1):
                print(f"spadeful {n + 1}: {json.dumps(did)}")
            if not did.get("kg"):
                break
        time.sleep(1.5)
        after = page.evaluate(LOOK, timeout=20)
        print("after digging:", json.dumps({k: v for k, v in after.items() if k != "details"}))
        deep = page.evaluate(GROUND_AT % {"x": x, "z": z}, timeout=20)
        print(f"the pit's floor is {deep:.3f} m up: {here - deep:.3f} m down")

        stand([x, here + 1.2, z + 2.2], [x, deep, z])
        qa_browser._shoot(page, args.out / "pit.png")
        stand([x, here + 0.55, z + 1.4], [x, deep + 0.05, z])
        qa_browser._shoot(page, args.out / "pit-close.png")
        print("shots in", args.out)
        return 0
    finally:
        chrome.close()


if __name__ == "__main__":
    raise SystemExit(main())
