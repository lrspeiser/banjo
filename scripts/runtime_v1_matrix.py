"""Run all live v1 scenes; export measured scope, material outcomes and timings."""
import argparse
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--exe", type=Path, default=Path("build/win-joint-double/Release/banjo_platform_cli.exe"))
parser.add_argument("--output", type=Path, default=Path("build/runtime-v1-validation"))
parser.add_argument("--repeat", type=int, default=3)
args = parser.parse_args()
if not 1 <= args.repeat <= 10:
    parser.error("repeat must be 1..10")
args.output.mkdir(parents=True, exist_ok=True)
rows = []
for path in sorted(Path("assets/runtime-v1").glob("*.json")):
    source = json.loads(path.read_text(encoding="utf-8"))
    steps = round(3 / source["fixed_dt_s"])
    for repeat in range(args.repeat):
        run = subprocess.run([str(args.exe), "--run", str(path), str(steps)], capture_output=True, text=True, check=True)
        report = json.loads(run.stdout)
        if report["fault"]:
            raise RuntimeError(f"{path.name}: {report['fault']}")
        if report["maximum_transfer_energy_error_j"] >= 1e-5:
            raise RuntimeError(f"{path.name}: transfer energy drift exceeded tolerance")
        for item in report["material_results"]:
            if item["material"] in {"oak", "iron"} and (item["broken_links"] or item["components"] != 1):
                raise RuntimeError(f"{path.name}: unsupported material failure")
        filename = f"{path.stem}-run-{repeat+1}.json"
        (args.output / filename).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        glass = [item for item in report["material_results"] if item["material"] == "glass"]
        rows.append(dict(scene=path.name, run=repeat+1, simulated_s=report["elapsed_s"],
                         physics_ms=report["performance"]["step_wall_total_ms"],
                         p95_step_ms=report["performance"]["step_p95_ms"],
                         peak_step_ms=report["performance"]["step_max_ms"],
                         load_ms=report["load_wall_ms"],
                         glass_broken=sum(x["broken_links"] for x in glass),
                         glass_components=sum(x["components"] for x in glass),
                         local_solves=report["local_solves"], budget_limited=report["budget_limited_impacts"],
                         transfer_energy_error_j=report["maximum_transfer_energy_error_j"]))
        print(path.name, repeat+1, "physics_ms", round(rows[-1]["physics_ms"], 2),
              "glass", rows[-1]["glass_broken"], "links /", rows[-1]["glass_components"], "components")
(args.output / "summary.json").write_text(json.dumps(dict(
    scope="3 simulated seconds; CPU physics includes contact, local solves and body replacement; excludes rendering and package compilation; no guaranteed frame budget",
    rows=rows), indent=2) + "\n", encoding="utf-8")
