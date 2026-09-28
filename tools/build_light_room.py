"""Write the room that shows the whole mining loop, with nothing wired yet.

The owner, 2026-09-28: light in a mine is electric, on cables running up to a
solar farm -- and then: "prove that we can take the same parts from the workshop,
put them into our inventory, go into the world and dig a tunnel and install the
lights to a solar panel".

So this room is the KIT, not the finished job. Standing at the valley's old adit
are three things the Workshop makes from its own templates -- a solar array, a
mine lamp and a powered breaker -- and NOTHING is wired. The lamp is dark
because a lamp is a fitting; the heading is dark because there is rock over it.
What is left is what a person does: pick the lamp up, carry it in, stand it at
the face, and run a cable to it from the array (P at the battery, walk, P at the
lamp). The breaker is there to take the face back with.

It writes `playground/rooms/tests-light.json`, open at `/world?scene=tests-light`.

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
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]

from mcp import workshop as w, workshop_machines, workshop_products  # noqa: E402

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


def built(kind: str, at: tuple[float, float, float]) -> tuple[dict, dict]:
    """A Workshop template, built and stood at a place.

    The same two calls the bench makes -- assemble the template, then ask
    `workshop_machines` for the room's own rows -- so nothing here is drawn by
    hand and a change to the template shows up here. It comes out as an EXACT
    BODY, which is what these products install as: one rigid group with its
    parts in their own frame.
    """
    workshop_products.install()
    design = w.assemble(kind)
    group = {"name": kind, "material": str(design.parts[0].material),
             "position_m": [round(float(v), 4) for v in at],
             "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
             "parts": [{"name": part.name,
                        "center_local_m": [round(float(v), 5) for v in part.center_m],
                        "dimensions_m": [round(float(v), 5) for v in part.size_m],
                        "material": str(part.material)} for part in design.parts]}
    rows = workshop_machines.installed(design, {part.name: kind for part in design.parts})
    for key in ("panels", "lamps", "breakers"):
        for row in rows.get(key) or []:
            row["at_mm"] = [round(row["at_mm"][i] + 1000.0 * at[i], 1) for i in range(3)]
    return group, rows


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
    # The array on the flat ground the plinth was going to stand on, and the
    # lamp and the breaker at the mouth of the adit, where somebody would have
    # put them down. Standing on the ground, not floating over it: a template's
    # own frame has its feet at y = 0.
    array, array_rows = built("solar-array", (farm_x, stands_at, farm_z))
    # The lamp and the breaker are IN the heading, at the face -- carried there
    # already, which is the part `tests/mine_loop_tests.py` proves. What is left
    # here is the wiring, and the wiring is what the page shows.
    lamp_at = (round(face["x"], 3), round(face["floor"], 3), round(face["z"], 3))
    lamp, lamp_rows = built("mine-lamp", lamp_at)
    breaker_at = (round(face["x"] + 0.4, 3), round(face["floor"] + 0.05, 3), round(face["z"], 3))
    breaker, breaker_rows = built("breaker", breaker_at)
    print(f"the array at [{farm_x:.2f}, {farm_z:.2f}]; the lamp and the breaker at the face "
          f"[{face['x']:.2f}, {face['z']:.2f}], on its floor at {face['floor']:.2f} m "
          f"under {face['hill'] - face['roof']:.2f} m of hill")

    machines = {
        "stores": (array_rows.get("stores") or []) + (breaker_rows.get("stores") or []),
        "panels": array_rows.get("panels") or [],
        # Unwired, and switched on, so it lights the moment a run reaches it.
        "lamps": lamp_rows.get("lamps") or [],
        # The breaker's chisel looks along the way the template draws it (+z),
        # and it reaches a hand's breadth past its point.
        "breakers": [{"name": "breaker", "body": "breaker", "store": "breaker battery",
                      "at_mm": mm(breaker_at[0], breaker_at[1] + 0.02, breaker_at[2] + 0.3),
                      "along": [0.0, 0.0, 1.0], "watts": 1500.0, "reach_m": 0.15, "on": False}],
    }

    room = {
        "algorithm": "lattice",
        "cell_m": 0.01,
        "terrain": {"generate": "valley"},
        # A day of four minutes, starting at four in the afternoon, so the sun
        # goes down while you are in the mine and a lamp is all there is.
        "sun": {"day_s": 240, "noon_elevation_deg": 60, "hour": 16, "irradiance_w_m2": 1000},
        # One marker so the room is this room: a spec with an empty bodies list
        # gets the engine's own drop-test scene instead.
        "bodies": [{"name": "claim post", "shape": "box", "material": "oak",
                    "size_mm": [80.0, 1200.0, 80.0],
                    "center_mm": mm(mouth["x"] + 1.2, mouth["hill"] + 0.6, mouth["z"] - 1.2),
                    "anchored": True, "color_rgba": "8a6b45ff"}],
        "precise_rigid_bodies": [array, lamp, breaker],
        "machines": machines,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(room, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
