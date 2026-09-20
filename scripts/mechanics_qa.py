"""Run the native mechanics contract suite used by the browser and MCP."""
from pathlib import Path
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"playground"))
import mechanics_qa

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--case", action="append")
    p.add_argument("--document", type=Path, help="Run an edited experiment, not the regression suite")
    args=p.parse_args()
    if args.case and args.document: p.error("Choose --case or --document")
    document=json.loads(args.document.read_text(encoding="utf-8")) if args.document else None
    report=mechanics_qa.run_suite(args.engine.resolve(), args.out, args.case, document=document)
    for r in report["results"]:
        print(r["id"], r["status"], r.get("error", ""), flush=True)
        for c in r.get("checks", []):
            if not c["passed"]: print("  failed:", c, flush=True)
    print(f'{report["completed"]}/{report["total"]}: {report["status"]}', flush=True)
    return 0 if report["status"]=="passed" else 1
if __name__=="__main__": raise SystemExit(main())
