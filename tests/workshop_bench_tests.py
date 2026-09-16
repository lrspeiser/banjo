"""Fast contracts for Workshop's isolated functional/compilation test bench."""
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import workshop_bench  # noqa: E402
import workshop_library  # noqa: E402
from mcp.workshop import assemble  # noqa: E402


class App:
    def __init__(self, root: Path) -> None:
        self.engine_path = root / "fake-engine"
        self.runs_path = root / "runs"
        self.workshop_db = root / "banjo.db"
        self.live = object()


class FakeKettleSession:
    def __init__(self, engine, spec, runs):
        self.spec, self.closed = spec, False
        self.state = {"t": 0.0, "bodies": []}
        self.thermo_calls = 0

    def send(self, **command):
        op = command.get("op")
        if op == "thermo":
            self.thermo_calls += 1
            t = 293.15 if self.thermo_calls == 1 else 335.15
            return {"ok": True, "thermo": {"bodies": [
                {"name": "water charge", "temperature_k": t, "contents_kg": {"moisture": 1.0}},
                {"name": "kettle bottom", "temperature_k": 350.0},
                {"name": "heater plate", "temperature_k": 500.0},
            ], "ledger": {"heater_in_j": 216000.0, "residual_j": 0.0}}}
        if op == "step":
            self.state = {"ok": True, "t": self.state["t"] + command.get("dt", 0) * command.get("n", 1), "bodies": []}
            return self.state
        raise AssertionError(op)

    def close(self): self.closed = True


class FakeMachineSession:
    def __init__(self):
        self.id = "scratch"
        self.state = {"t": 0.0, "bodies": [{"name": "load", "position_m": [0.1, 0.45, 0.0]}],
                      "machines": {"controls": [{"id": 7, "name": "hoist", "condition": "stopped"}]}}

    def send(self, **command):
        op = command.get("op")
        if op == "operate":
            self.state["machines"]["controls"] = [{"id": 7, "name": "hoist", "power": command.get("power"),
                "direction": command.get("direction"), "setting": command.get("setting"),
                "condition": "running", "speed_rpm": 55.0}]
            return {"ok": True, "operated": "applied", "control": self.state["machines"]["controls"][0]}
        if op == "step":
            self.state["t"] += command.get("dt", 0) * command.get("n", 1)
            self.state["bodies"][0]["position_m"][1] += 0.01
            self.state["machines"].update({
                "motors": [{"power_w": 120.0, "current_a": 5.0, "heat_j": 2.0}],
                "stores": [{"charge_j": 4800.0, "given_j": 200.0}],
                "ropes": [{"out_m": 1.2, "rope_speed_m_s": -0.1}],
            })
            return {"ok": True, **self.state}
        if op == "poses": return {"ok": True, **self.state}
        raise AssertionError(op)


class FakeLive:
    last = None
    def __init__(self):
        self.session = FakeMachineSession(); self.closed = False; FakeLive.last = self
    def open(self, app, body):
        return {"session": self.session.id,
                "machines": {"controls": [{"id": 7, "name": "hoist", "condition": "stopped"}]},
                "bodies": list(self.session.state["bodies"])}
    def shutdown(self): self.closed = True


class BenchCatalog(unittest.TestCase):
    def test_generic_compiler_kettle_and_machine_are_bench_operations(self):
        tests = {t["test"]: t for t in workshop_bench.catalog()}
        self.assertTrue({"runtime_contract", "kettle_heat", "machine_control"} <= set(tests))
        self.assertEqual([], tests["runtime_contract"]["controls"])
        self.assertIn("water_kg", {c["name"] for c in tests["kettle_heat"]["controls"]})
        machine = {c["name"] for c in tests["machine_control"]["controls"]}
        self.assertTrue({"power", "direction", "setting", "load_kg"} <= machine)


class IsolatedBench(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.app = App(self.root); self.design = assemble("table", design_id="candidate")
    def tearDown(self): self.tmp.cleanup()

    def test_runtime_contract_compiles_current_design_without_an_engine(self):
        outside = self.app.live
        result = workshop_bench.run(self.app, self.design, {"test": "runtime_contract", "config": {}})
        self.assertIs(self.app.live, outside)
        self.assertEqual("banjo.product-graph.v1", result["product_graph"]["schema"])
        self.assertEqual("banjo.physics-contract.v1", result["physics_contract"]["schema"])
        self.assertEqual(len(self.design.parts), result["summary"]["detailed_components"])
        self.assertAlmostEqual(self.design.measure()["mass_kg"], result["summary"]["mass_kg"], places=2)
        self.assertGreaterEqual(result["summary"]["runtime_bodies"], 1)

    def test_kettle_reports_engine_temperature_and_ledger_without_the_outside_world(self):
        outside = self.app.live
        with mock.patch.object(workshop_bench.live_session, "Session", FakeKettleSession):
            result = workshop_bench.run(self.app, self.design, {
                "test": "kettle_heat", "config": {"water_kg": 1.0, "duration_s": 120, "heater_power_w": 1800}})
        self.assertIs(self.app.live, outside)
        self.assertEqual("engine-trial", result["evidence"])
        self.assertEqual(293.15, result["measured"]["water_start_k"])
        self.assertEqual(335.15, result["measured"]["water_end_k"])
        self.assertEqual(216000.0, result["measured"]["ledger"]["heater_in_j"])
        self.assertIn("free liquid", result["limitations"][0])

    def test_machine_edits_the_real_controller_contract_and_owns_its_session(self):
        outside = self.app.live
        with mock.patch.object(workshop_bench.live_session, "Live", FakeLive):
            result = workshop_bench.run(self.app, self.design, {
                "test": "machine_control", "config": {"power": True, "direction": -1,
                                                        "setting": 35, "duration_s": 0.5, "load_kg": 20}})
        self.assertIs(self.app.live, outside); self.assertTrue(FakeLive.last.closed)
        self.assertEqual("applied", result["measured"]["acknowledgement"])
        control = result["measured"]["control"]
        self.assertEqual(-1, control["direction"]); self.assertAlmostEqual(0.35, control["setting"])
        self.assertNotEqual(0.0, result["measured"]["load_delta_y_m"])

    def test_bench_presets_are_owner_scoped_and_persistent(self):
        one = workshop_library.save_bench_preset(self.app, name="Half speed lift", test_name="machine_control",
                                                  config={"power": True, "direction": 1, "setting": 50})
        self.assertEqual("machine_control", one["test"])
        self.assertEqual("Half speed lift", workshop_library.list_bench_presets(self.app)[0]["name"])
        other = App(self.root); other.workshop_owner_id = "someone-else"
        self.assertEqual([], workshop_library.list_bench_presets(other))


if __name__ == "__main__": unittest.main()
