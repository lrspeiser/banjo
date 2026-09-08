"""Where the damage is, for each lane, from the recordings themselves.

A recording carries bond lines (a_m, b_m, live) on its early frames. This reads
the last frame that has them and reports, for the dead bonds, the radius of
gyration about the strike axis and the fraction inside successive radii. It is
the statistic the quasi-static checkpoint used to separate a crater from a
crack pattern, and it separates diffuse damage from crack paths the same way.

    python scripts/algo2-damage-geometry.py build/runs/algo2/base-algo2.json \
        build/runs/algo2/base-reference.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def analyse(path: Path) -> None:
    recording = json.loads(path.read_text(encoding="utf-8"))
    report = recording.get("report", {})
    frames = [f for f in recording.get("frames", []) if "bonds" in f]
    if not frames:
        print(f"{path.name}: no frame carries bond lines")
        return
    frame = frames[-1]
    dead = [b for b in frame["bonds"] if not b["live"]]
    live = [b for b in frame["bonds"] if b["live"]]
    if not dead:
        print(f"{path.name}: no dead bonds at t = {frame['time_s']:.6f} s")
        return
    strike = report.get("scene", {}).get("offset_m") or [0.0, 0.0]
    centres = [((b["a_m"][0] + b["b_m"][0]) / 2, (b["a_m"][2] + b["b_m"][2]) / 2) for b in dead]
    radii = sorted(math.hypot(x - strike[0], z - strike[1]) for x, z in centres)
    mean_x = sum(c[0] for c in centres) / len(centres)
    mean_z = sum(c[1] for c in centres) / len(centres)
    gyration = math.sqrt(sum((x - mean_x) ** 2 + (z - mean_z) ** 2 for x, z in centres) / len(centres))
    def fraction(limit: float) -> float:
        return sum(1 for r in radii if r <= limit) / len(radii)
    print(f"{path.name}: lane {report.get('lane')}  t = {frame['time_s']:.6f} s")
    print(f"  dead {len(dead)} of {len(dead) + len(live)} bonds")
    print(f"  radius of gyration of the dead set about its own centroid: {1000 * gyration:.1f} mm")
    print(f"  median distance from the strike axis: {1000 * radii[len(radii) // 2]:.1f} mm, "
          f"max {1000 * radii[-1]:.1f} mm")
    for limit in (0.02, 0.04, 0.06, 0.08, 0.12):
        print(f"  within {1000 * limit:5.0f} mm of the strike: {100 * fraction(limit):5.1f}%")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for name in sys.argv[1:]:
        analyse(Path(name))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
