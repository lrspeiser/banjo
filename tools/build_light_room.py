"""Write the room that shows electric light underground.

The owner, 2026-09-28: light in a mine is electric, on cables running up to a
solar farm. This lays the smallest room that shows it whole -- a solar farm on
the hill over the old adit, a battery beside it, a cable down the slope and in
along the heading, and three lamps hung on that cable -- and writes it out as
`playground/rooms/tests-light.json`, open at `/world?scene=tests-light`.

The adit is where the valley's generator put it, not where anybody guessed. So
this opens the valley in the engine first, reads back the runs, and lays the
cable and the lamps along the working it finds. Run it again after any change to
the generator and the room follows the mine.

    python tools/build_light_room.py --engine build/integration/Release/banjo_live_world_run.exe
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOMS = ROOT / "playground" / "rooms"

RUN_VOID = 8


def ask(engine: Path, scene: dict, ops: list[dict]) -> list[dict]:
    """Open `scene` in the runner, send `ops`, and give back what it said."""
    written = Path(tempfile.gettempdir()) / "banjo-light-room-scene.json"
    written.write_text(json.dumps(scene), encoding="utf-8")
    lines = [json.dumps(op) for op in ops]
    lines.append(json.dumps({"op": "quit"}))
    done = subprocess.run([str(engine.resolve()), "--scene", str(written)],
                          input="\n".join(lines) + "\n", capture_output=True,
                          text=True, timeout=600)
    said = []
    for line in done.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            said.append(json.loads(line))
    if not said:
        raise SystemExit(f"the engine said nothing:\n{done.stderr[-2000:]}")
    return said


def read_runs(terrain: dict):
    """Every column's top, and every column with a hole in it, off the runs the
    engine sent. `tops` is what the ground stands at; `holes` is the old mine."""
    raw = base64.b64decode(terrain["runs_b64"])
    g, floor = terrain["grid"], terrain["floor_m"]
    nx, nz, cell = g["nx"], g["nz"], g["cell_m"]
    found, tops, at = [], {}, 0
    for c in range(nx * nz):
        n = raw[at]
        at += 1
        below, hole, top = floor, None, floor
        for _ in range(n):
            kind = raw[at]
            h = floor + (raw[at + 1] | (raw[at + 2] << 8)) / 1000.0
            if kind == RUN_VOID:
                hole = (below, h)
            below = top = h
            at += 3
        tops[(c % nx, c // nx)] = top
        if hole:
            found.append({"x": g["x0_m"] + (c % nx) * cell, "z": g["z0_m"] + (c // nx) * cell,
                          "floor": hole[0], "roof": hole[1], "hill": top})
    return found, tops, g


def ground_at(tops, g, x: float, z: float) -> float:
    """What the ground stands at, at a point: the top of its column."""
    i = round((x - g["x0_m"]) / g["cell_m"])
    j = round((z - g["z0_m"]) / g["cell_m"])
    return tops.get((i, j), 0.0)


def flat_ground(tops, g, holes, near: dict, least_m: float, most_m: float, wide_m: float):
    """Somewhere to stand a plinth `wide_m` across: ground between `least_m` and
    `most_m` from `near`, level to within 150 mm across the plinth's whole
    footprint, and no working anywhere under it. The highest such place wins, so
    the panels get the sun. None if there is nowhere."""
    cell = g["cell_m"]
    worked = {(round((h["x"] - g["x0_m"]) / cell), round((h["z"] - g["z0_m"]) / cell)) for h in holes}
    half = max(1, int(round(0.5 * wide_m / cell)))
    best = None
    for (i, j), top in tops.items():
        x = g["x0_m"] + i * cell
        z = g["z0_m"] + j * cell
        away = ((x - near["x"]) ** 2 + (z - near["z"]) ** 2) ** 0.5
        if not least_m <= away <= most_m:
            continue
        under = [tops.get((i + di, j + dj)) for di in range(-half, half + 1)
                 for dj in range(-half, half + 1)]
        if any(u is None for u in under):
            continue
        if any((i + di, j + dj) in worked for di in range(-half, half + 1)
               for dj in range(-half, half + 1)):
            continue
        if max(under) - min(under) > 0.15:
            continue
        if best is None or top > best[2]:
            best = (round(x, 3), round(z, 3), round(min(under), 3))
    return best


def mm(x: float, y: float, z: float) -> list[float]:
    return [round(x * 1000.0, 1), round(y * 1000.0, 1), round(z * 1000.0, 1)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", type=Path,
                    default=ROOT / "build" / "integration" / "Release" / "banjo_live_world_run.exe")
    ap.add_argument("--out", type=Path, default=ROOMS / "tests-light.json")
    args = ap.parse_args()

    # The runner wants a scene with something in it, so the probe brings a pebble
    # it does not care about: all this asks the engine for is the ground.
    valley = {"terrain": {"generate": "valley"}, "cell_m": 0.05,
              "bodies": [{"name": "pebble", "shape": "box", "material": "concrete",
                          "size_mm": [100, 100, 100], "center_mm": [0, 40000, 0],
                          "anchored": True}]}
    said = ask(args.engine, valley, [{"op": "terrain"}])
    terrain = next((s["terrain"] for s in said if isinstance(s, dict) and s.get("terrain")), None)
    if not terrain or not terrain.get("runs_b64"):
        raise SystemExit("the valley came back without its runs")
    holes, tops, grid = read_runs(terrain)
    if not holes:
        raise SystemExit("this valley has no old mine in it")
    # The mouth of the adit is the working with least hill over it; the far end
    # is the one with most. The cable runs from the hill above the mouth, in at
    # the mouth, and along to the face.
    mouth = min(holes, key=lambda h: h["hill"] - h["roof"])
    face = max(holes, key=lambda h: h["hill"] - h["roof"])
    print(f"{len(holes)} columns of working; the mouth at "
          f"[{mouth['x']:.2f}, {mouth['z']:.2f}] under {mouth['hill'] - mouth['roof']:.2f} m of hill, "
          f"the face at [{face['x']:.2f}, {face['z']:.2f}] under {face['hill'] - face['roof']:.2f} m")

    # The farm: a concrete plinth on the hill a few metres back from the mouth.
    # Ground flat enough to stand a 1.6 m plinth on and clear of the old workings
    # -- the spoil and the open cut are right beside the adit, and a plinth put
    # down by guesswork ends up hanging over the edge of one of them.
    site = flat_ground(tops, grid, holes, mouth, 3.0, 9.0, 1.6)
    if site is None:
        raise SystemExit("no flat ground near the adit to stand a solar farm on")
    farm_x, farm_z, stands_at = site
    # Standing ON the hill, not over it: half the plinth is under the ground.
    farm_y = round(stands_at + 0.3, 3)
    print(f"the farm on flat ground at [{farm_x:.2f}, {farm_z:.2f}], standing at {stands_at:.2f} m")
    plinth = {"name": "farm plinth", "shape": "box", "material": "concrete",
              "size_mm": mm(1.6, 0.6, 1.6), "center_mm": mm(farm_x, farm_y, farm_z),
              "anchored": True, "color_rgba": "6d7280ff"}
    top = farm_y + 0.3

    # The run: down off the plinth, across the ground to the mouth, in at the
    # mouth and along the heading to the face, hung just under the roof.
    hang = min(mouth["roof"], face["roof"]) - 0.08
    run = [mm(farm_x, top, farm_z),
           mm(farm_x, farm_y - 0.3 + 0.05, farm_z),
           mm(mouth["x"], mouth["hill"] + 0.1, mouth["z"]),
           mm(mouth["x"], hang, mouth["z"]),
           mm(face["x"], hang, face["z"])]
    # Three lamps along it: one at the mouth, one halfway in, one at the face.
    def between(t: float) -> list[float]:
        return mm(mouth["x"] + t * (face["x"] - mouth["x"]), hang,
                  mouth["z"] + t * (face["z"] - mouth["z"]))
    lamps = [{"name": "mouth lamp", "cable": "the mine feeder", "at_mm": between(0.05),
              "watts": 20.0, "on": True},
             {"name": "heading lamp", "cable": "the mine feeder", "at_mm": between(0.5),
              "watts": 20.0, "on": True},
             {"name": "face lamp", "cable": "the mine feeder", "at_mm": between(0.95),
              "watts": 20.0, "on": True}]

    room = {
        "algorithm": "lattice",
        "cell_m": 0.05,
        "terrain": {"generate": "valley"},
        # A day of four minutes, starting at four in the afternoon, so the sun
        # goes down while you are in the mine and the lamps are all there is.
        "sun": {"day_s": 240, "noon_elevation_deg": 60, "hour": 16, "irradiance_w_m2": 1000},
        "bodies": [plinth],
        "machines": {
            "stores": [{"name": "the farm battery", "body": "farm plinth",
                        "capacity_j": 2.0e6, "charge_j": 4.0e5, "voltage_v": 24.0}],
            "panels": [{"name": "east panel", "body": "farm plinth", "store": "the farm battery",
                        "at_mm": mm(farm_x - 0.35, top, farm_z), "normal": [0.0, 1.0, 0.0],
                        "area_m2": 0.5, "efficiency": 0.2},
                       {"name": "west panel", "body": "farm plinth", "store": "the farm battery",
                        "at_mm": mm(farm_x + 0.35, top, farm_z), "normal": [0.0, 1.0, 0.0],
                        "area_m2": 0.5, "efficiency": 0.2}],
            # 4 mm2 copper: thick enough that this run costs a fraction of a volt.
            # Lay it in 1.5 and the face lamp goes noticeably dim, which is the
            # thing to try in the page.
            "cables": [{"name": "the mine feeder", "store": "the farm battery",
                        "run_mm": run, "area_mm2": 4.0}],
            "lamps": lamps,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(room, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
