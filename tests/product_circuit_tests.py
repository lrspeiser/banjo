"""Construction -> contract -> native circuit, with no scripted shaft motion."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bindings" / "python"))
from mcp.product_contract import compile_contract
from mcp.product_circuit import install_circuit


def product() -> dict:
    return {
        "schema": "banjo.product-graph.v1", "product_id": "drive",
        "components": [{"id": name, "role": name, "geometry": {},
                        "interfaces": [{"id": "p", "kind": "electrical"}, {"id": "n", "kind": "electrical"}]}
                       for name in ["battery", "switch", "fuse", "motor"]],
        "relationships": [{"id": str(i), "kind": "electrical", "a": a, "b": b,
                           "a_interface": ap, "b_interface": bp}
                          for i, (a, ap, b, bp) in enumerate([
                              ("battery", "p", "switch", "p"), ("switch", "n", "fuse", "p"),
                              ("fuse", "n", "motor", "p"), ("motor", "n", "battery", "n")])],
        "energy": [{"kind": "circuit", "network": {
            "schema": "banjo.circuit.v1", "id": "drive", "source": {
                "store_component": "battery", "positive": "battery.p", "negative": "battery.n",
                "resistance_ohm": .1, "thermal": "case"},
            "thermal_nodes": [{"id": "case", "component": "battery", "capacity_j_k": 100},
                              {"id": "winding", "component": "motor", "capacity_j_k": 10}],
            "thermal_links": [{"a": "winding", "b": "case", "conductance_w_k": 1}],
            "branches": [
                {"id": "switch", "kind": "switch", "component": "switch", "a": "switch.p", "b": "switch.n",
                 "resistance_ohm": .1, "thermal": "case"},
                {"id": "fuse", "kind": "fuse", "component": "fuse", "a": "fuse.p", "b": "fuse.n",
                 "resistance_ohm": .05, "fuse_a2_s": 1000, "thermal": "case"},
                {"id": "motor", "kind": "motor", "component": "motor", "motor_component": "motor",
                 "a": "motor.p", "b": "motor.n", "thermal": "winding", "gear_ratio": 2}],
        }}],
    }


class ProductCircuits(unittest.TestCase):
    def test_terminals_compile_and_ids_survive_reduction(self):
        graph = product(); before = deepcopy(graph)
        contract = compile_contract(graph)
        network = contract["operating_model"]["circuits"][0]
        self.assertEqual(len(network["nodes"]), 4)
        self.assertEqual(network["source"]["positive"], network["branches"][0]["a"])
        self.assertEqual(network["branches"][0]["b"], network["branches"][1]["a"])
        self.assertEqual(graph, before)
        self.assertEqual(len(contract["runtime_bodies"]), 4)

    def test_missing_and_mixed_ports_and_unsupported_models_reject(self):
        for field, value in [("a_interface", None), ("a_interface", "missing")]:
            graph = product(); graph["relationships"][0][field] = value
            with self.assertRaises(ValueError): compile_contract(graph)
        graph = product(); graph["components"][0]["interfaces"][0]["kind"] = "fluid"
        with self.assertRaises(ValueError): compile_contract(graph)
        graph = product(); graph["energy"][0]["network"]["source"]["store"] = 1
        with self.assertRaises(ValueError): compile_contract(graph)

    def test_relationship_alone_does_not_claim_a_solver(self):
        graph = product(); graph["energy"] = []
        self.assertEqual(compile_contract(graph)["operating_model"]["circuits"], [])

    def test_native_install_operate_inspect_and_restore(self):
        import banjo
        scene = {"bodies": [
            {"name": "post", "shape": "box", "material": "iron", "dimensions_m": [.1, .8, .1],
             "center_m": [.5, .4, 0], "anchored": True},
            {"name": "wheel", "shape": "box", "material": "iron", "dimensions_m": [.4, .1, .4],
             "center_m": [.5, 1, 0]}]}
        with banjo.World(scene, cell_size_m=.05) as world:
            pin = world.hinge("post", "wheel", [.5, 1, 0], [0, 1, 0])
            store = world.energy_store("battery", "post", 1000, 1000, 24, 30)
            motor = world.motor(pin, store, 10, 10)
            contract = compile_contract(product())
            circuit = install_circuit(world, contract, "drive", stores={"battery": store}, motors={"motor": motor})
            world.drive_motor(motor, 1)
            for _ in range(120): world.step(1 / 240)
            self.assertGreater(world.motors()[0].speed_rad_s, 0)
            self.assertLess(world.energy_stores()[0].charge_j, 1000)
            state = world.circuits()
            self.assertEqual(state, world.circuits())  # inspection has no effects
            self.assertGreater(state[0]["thermal_nodes"][1]["temperature_k"], 293.15)
            world.circuit_switch(circuit, "switch", False)
            charge = world.energy_stores()[0].charge_j
            snapshot = world.snapshot()
            self.assertIsNotNone(snapshot)
        with banjo.World(scene, cell_size_m=.05, snapshot=snapshot) as restored:
            self.assertEqual(restored.energy_stores()[0].charge_j, charge)
            self.assertEqual(restored.circuits()[0]["thermal_nodes"], state[0]["thermal_nodes"])
            for _ in range(12): restored.step(1 / 240)
            self.assertAlmostEqual(restored.energy_stores()[0].charge_j, charge, places=8)
            self.assertAlmostEqual(restored.motors()[0].current_a, 0, places=9)
            with self.assertRaises(Exception):
                install_circuit(restored, contract, "drive", stores={"battery": store}, motors={"motor": motor})


if __name__ == "__main__":
    unittest.main()
