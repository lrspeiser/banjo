"""Run recorded tool-use trials without touching a live room."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"playground"))
import tool_qa

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--case",action="append",dest="ids")
    args=parser.parse_args()
    report=tool_qa.run_suite(args.engine.resolve(),args.out.resolve(),args.ids)
    for r in report["results"]: print(r["id"],r["status"],r.get("error",r.get("outcome","")))
    # Unsupported rock cases are expected capability boundaries, retained in
    # the report. Only operational failures/unresolved trials fail the runner.
    return 0 if report["status"] in ("passed","unsupported") else 1

if __name__=="__main__":raise SystemExit(main())
