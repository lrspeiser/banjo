"""Run the material range; exit nonzero on failures or baseline changes."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
import material_qa

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True,
                        help="banjo_fast_lattice_run or an adjacent engine executable")
    parser.add_argument("--out", type=Path, required=True, help="New evidence directory")
    parser.add_argument("--case", action="append", dest="ids", help="Catalog case ID; repeatable")
    parser.add_argument("--baseline", type=Path, default=material_qa.BASELINE)
    parser.add_argument("--no-baseline", action="store_true", help="Measure without accepting a new baseline")
    args = parser.parse_args()
    try:
        report = material_qa.run_suite(args.engine.resolve(), args.out.resolve(), args.ids,
                                      None if args.no_baseline else args.baseline)
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps({k: report[k] for k in ("id", "status", "total", "completed", "baseline_checked")}))
    for row in report["results"]:
        print(row["id"], row["status"], "; ".join(row.get("issues", []) + row.get("changes", [])))
    return 0 if report["status"] == "passed" else 1

if __name__ == "__main__":
    raise SystemExit(main())
