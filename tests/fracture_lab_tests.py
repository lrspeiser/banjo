"""Fracture lab: parameter validation, cell counts, lane commands and summaries.

Pure Python; no engine required. Run: python tests/fracture_lab_tests.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
import fracture_lab as lab  # noqa: E402

ENGINE = Path("C:/x/banjo_platform_cli.exe")


def rejects(spec, fragment):
    try:
        lab.validate(spec)
    except ValueError as error:
        assert fragment in str(error), (fragment, str(error))
        return
    raise AssertionError(f"accepted {spec!r}")


def main() -> int:
    spec = lab.validate({"algorithm": "reference"})
    assert spec["cells_per_axis"] == [25, 20, 1] and spec["cells"] == 500, spec
    assert math.isclose(spec["speed_m_s"], math.sqrt(2 * 9.81 * 2.0)), spec["speed_m_s"]

    given = lab.validate({"algorithm": "reference", "speed_m_s": 4.0})
    assert math.isclose(given["drop_m"], 16 / (2 * 9.81)), given["drop_m"]

    rejects({"algorithm": "nope"}, "algorithm must be one of")
    rejects({"algorithm": "reference", "plate_m": [0.25, 0.20, 0.01], "cell_m": 0.004}, "cubic cells")
    rejects({"algorithm": "reference", "plate_m": [0.5, 0.5, 0.01], "cell_m": 0.01}, "instant-run cap")
    rejects({"algorithm": "algo3", "offset_m": [0.2, 0.0]}, "offset x")
    rejects({"algorithm": "algo3", "bogus": 1}, "Unknown fracture lab fields")

    argv = lab.command("algo1", lab.validate({"algorithm": "algo1", "offset_m": [0.01, -0.02]}), ENGINE,
                       Path("out.json"), Path("cache"), Path("r.json"))
    assert argv[0].endswith("banjo_fracture_algo1.exe"), argv[0]
    assert argv[1:9] == ["--plate", "0.25", "0.2", "0.01", "--cell", "0.01", "--ball", "0.06"], argv[1:9]
    assert "--support" in argv and argv[argv.index("--support") + 1] == "ledges", argv
    assert argv[argv.index("--offset") + 1:argv.index("--offset") + 3] == ["0.01", "-0.02"], argv

    ref = lab.command("reference", lab.validate({"algorithm": "reference"}), ENGINE, Path("o.json"), Path("c"), Path("r.json"))
    assert ref[ref.index("--tile") + 1:ref.index("--tile") + 4] == ["0.25", "0.01", "0.2"], "tile is L, thickness, W"
    assert ref[ref.index("--ball-radius") + 1] == "0.03", ref
    assert ref[ref.index("--layout") + 1] == "bridge", ref
    try:
        lab.command("reference", lab.validate({"algorithm": "reference", "support": "clamped"}), ENGINE, Path("o"), Path("c"), Path("r"))
        raise AssertionError("reference accepted clamped support")
    except ValueError as error:
        assert "ledges" in str(error)

    # Summaries read whichever names a lane uses; the reference writes its
    # totals at the top of its report and its pieces under handoff.
    report = {"cells": 500, "bonds": 2777, "wall_total_s": 2.0, "simulated_total_s": 0.33, "realtime_ratio": 6.06,
              "lattice": {"broken_bonds": 73, "removed_energy_j": 2.1, "first_failure_s": 6.55e-4, "wall_s": 1.9, "simulated_s": 0.013},
              "handoff": {"components": 1, "largest_piece_cells": 500}}
    out = lab.summary(report, 2.06, spec)
    assert out["components"] == 1 and out["largest_component_cells"] == 500 and out["broken_bonds"] == 73, out
    assert math.isclose(out["fracture_window_ratio"], 1.9 / 0.013), out
    assert out["realtime_ratio"] == 6.06 and out["compute_wall_s"] == 2.0, out
    lane_report = {"cells": 500, "realtime": {"ratio": 0.02, "simulated_s": 2.0, "compute_wall_s": 0.04, "fracture_window_ratio": 3.0},
                   "components": 5, "broken_bonds": 120, "first_failure": {"time_s": 1e-4}, "precompute_s": 1.2, "precompute_cached": True}
    out = lab.summary(lane_report, 0.05, spec)
    assert out["realtime_ratio"] == 0.02 and out["fracture_window_ratio"] == 3.0 and out["components"] == 5, out
    assert out["precompute_cached"] is True and out["first_failure_time_s"] == 1e-4, out

    meta = lab.describe(ENGINE)
    assert [a["id"] for a in meta["algorithms"]] == ["algo1", "algo2", "algo3", "reference"], meta
    assert all(a["available"] is False for a in meta["algorithms"]), "no executables at a fake path"
    print("[PASS] fracture lab validation, commands and summaries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
