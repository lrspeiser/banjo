"""Run a constructed product's circuit against a real hinged flywheel.

Set BANJO_LIBRARY to the newly built library, then run this file. Examples:
  python examples/authoring/circuit_drive.py --open-at-s 1
  python examples/authoring/circuit_drive.py --locked --charge-j 1
  python examples/authoring/circuit_drive.py --locked --fuse-a2-s 0.2
All motion is from the native engine. CSV observations and a world snapshot
are written beside --output; opening the snapshot resumes the same machine.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bindings" / "python"))
import banjo
from mcp.product_contract import compile_contract
from mcp.product_circuit import install_circuit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=2)
    parser.add_argument("--charge-j", type=float, default=1000)
    parser.add_argument("--power-w", type=float, default=30)
    parser.add_argument("--locked", action="store_true")
    parser.add_argument("--open-at-s", type=float, default=1e9)
    parser.add_argument("--fuse-a2-s", type=float, default=1000)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "circuit-drive.csv")
    args = parser.parse_args()
    if not 1 / 240 <= args.seconds <= 60:
        parser.error("seconds must be in [1/240, 60]")
    graph = json.loads(Path(__file__).with_name("circuit_product.json").read_text(encoding="utf-8"))
    graph["energy"][0]["network"]["branches"][1]["fuse_a2_s"] = args.fuse_a2_s
    scene = {"bodies": [
        {"name": "post", "shape": "box", "material": "iron", "dimensions_m": [.1, .8, .1],
         "center_m": [.5, .4, 0], "anchored": True},
        {"name": "wheel", "shape": "box", "material": "iron", "dimensions_m": [.4, .1, .4],
         "center_m": [.5, 1, 0]}]}
    rows = []
    with banjo.World(scene, cell_size_m=.05) as world:
        pin = world.hinge("post", "wheel", [.5, 1, 0], [0, 1, 0],
                          lower_deg=0 if args.locked else -180, upper_deg=0 if args.locked else 180)
        store = world.energy_store("battery", "post", args.charge_j, args.charge_j, 24, args.power_w)
        motor = world.motor(pin, store, 10, 10)
        circuit = install_circuit(world, compile_contract(graph), "drive",
                                  stores={"battery": store}, motors={"motor": motor})
        world.drive_motor(motor, 1)
        for i in range(round(args.seconds * 240)):
            if i / 240 >= args.open_at_s:
                world.circuit_switch(circuit, "switch", False)
            if world.step(1 / 240) == banjo.BREAK_PENDING:
                raise RuntimeError("mechanical fracture requires attention; trace stops at the accepted state")
            m = world.motors()[0]; c = world.circuits()[0]
            rows.append({"time_s": (i + 1) / 240, "speed_rad_s": m.speed_rad_s,
                         "torque_n_m": m.torque_n_m, "current_a": m.current_a,
                         "charge_j": world.energy_stores()[0].charge_j,
                         "winding_k": c["thermal_nodes"][1]["temperature_k"],
                         "case_k": c["thermal_nodes"][0]["temperature_k"],
                         "fuse_failed": c["branches"][1]["failed"],
                         "coupling_residual_j": c["ledger"]["coupling_residual_j"]})
        snapshot = world.snapshot()
        if snapshot is None:
            raise RuntimeError("world snapshot was refused")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        args.output.with_suffix(".world.json").write_text(json.dumps({"scene": scene, "snapshot": snapshot}, indent=2), encoding="utf-8")
        print(json.dumps({"last": rows[-1], "ledger": world.circuits()[0]["ledger"], "csv": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
