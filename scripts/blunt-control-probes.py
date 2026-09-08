"""Write the blunt-control probe packages used by docs/blunt-control-substep-checkpoint.md.

Each probe is assets/runtime-v2/02-blunt-four-materials.json reduced to the
soft-tissue target (object 7) and its tool (object 8), with unused materials
dropped and nothing else changed, plus one of:

  tissue_default_damping  nothing else: the lane's own 5 substeps per tick
  tissue_zero_damping     contact_damping_ratio 0 on both materials (the
                          behaviour before 287c1c7)
  tissue_plus_glass2/3    the fixture's glass target (object 1) kept at 2x2x2 or
                          3x3x3 so it sets the substep count (901 / 2,271)
  tissue_pacer3600        a 2x2x2 iron block with 15 mm cells 1.5 m away, so the
                          substep count is 4,699 at negligible cost

Run each with banjo_playground_record --package <file> --steps 720 and read
report.objects[id=7], report.network_substepping.substeps_per_host_tick,
report.maximum_observed_axial_strain and
report.reaction_reconstruction.maximum_residual_over_irreversible_extension.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "assets" / "runtime-v2" / "02-blunt-four-materials.json"


def reduced(source: dict, keep_objects: set[int], keep_materials: set[str]) -> dict:
    package = copy.deepcopy(source)
    package["objects"] = [o for o in package["objects"] if o["id"] in keep_objects]
    package["materials"] = [m for m in package["materials"] if m["id"] in keep_materials]
    return package


def main(out_dir: Path) -> None:
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: dict[str, dict] = {}
    probes["tissue_default_damping"] = reduced(source, {7, 8}, {"soft-tissue", "iron"})
    zero = reduced(source, {7, 8}, {"soft-tissue", "iron"})
    for material in zero["materials"]:
        material["contact_damping_ratio"] = 0.0
    probes["tissue_zero_damping"] = zero
    for resolution in (2, 3):
        package = reduced(source, {1, 2, 7, 8}, {"soft-tissue", "iron", "glass"})
        for obj in package["objects"]:
            if obj["id"] == 1:
                obj["resolution"] = [resolution] * 3
        probes[f"tissue_plus_glass{resolution}"] = package
    paced = reduced(source, {7, 8}, {"soft-tissue", "iron"})
    pacer = copy.deepcopy(next(o for o in source["objects"] if o["id"] == 5))
    pacer.update({"id": 9, "name": "substep pacer (iron)", "resolution": [2, 2, 2],
                  "dimensions_m": [0.03, 0.03, 0.03], "position_m": [1.5, 0.015, 1.5],
                  "velocity_m_s": [0, 0, 0]})
    paced["objects"].append(pacer)
    probes["tissue_pacer3600"] = paced
    for name, package in probes.items():
        (out_dir / f"{name}.json").write_text(json.dumps(package, indent=1), encoding="utf-8")
        print(f"wrote {out_dir / (name + '.json')}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "blunt-probe")
