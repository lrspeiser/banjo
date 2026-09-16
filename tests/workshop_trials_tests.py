from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

from mcp.workshop import assemble  # noqa: E402
import workshop_trials  # noqa: E402


class App:
    def __init__(self, root: Path) -> None:
        self.engine_path = root / "fake-engine"
        self.runs_path = root / "runs"
        self.live = object()
        self.room = {"do_not_touch": True}


class FakeSession:
    made = []

    def __init__(self, engine, spec, runs) -> None:
        self.engine, self.spec, self.runs = engine, spec, runs
        self.closed = False
        self.t = 0.0
        root = spec["bodies"][0]
        load = spec["bodies"][-1]
        self.root_name = root["name"]
        self.load_name = load["name"]
        self.root_at = [float(v) / 1000.0 for v in root["center_mm"]]
        self.load_at = [float(v) / 1000.0 for v in load["center_mm"]]
        FakeSession.made.append(self)

    def _state(self):
        return {
            "ok": True,
            "t": self.t,
            "bodies": [
                {"name": self.root_name, "position_m": list(self.root_at),
                 "orientation_wxyz": [1.0, 0.0, 0.0, 0.0], "velocity_m_s": [0.0, 0.0, 0.0]},
                {"name": self.load_name, "position_m": list(self.load_at),
                 "orientation_wxyz": [1.0, 0.0, 0.0, 0.0], "velocity_m_s": [0.0, 0.0, 0.0]},
            ],
        }

    def send(self, **command):
        if command["op"] == "poses": return self._state()
        if command["op"] == "step":
            self.t += float(command["dt"]) * int(command["n"])
            return self._state()
        raise AssertionError(command)

    def close(self): self.closed = True


class PrototypeScene(unittest.TestCase):
    def test_table_becomes_one_join_group_plus_only_the_test_load(self):
        setup = workshop_trials.prototype_scene(assemble("table", design_id="t"), load_kg=100)
        bodies = setup["spec"]["bodies"]
        candidate = [b for b in bodies if str(b["name"]).startswith("candidate/")]
        self.assertGreater(len(candidate), 1)
        self.assertEqual({"workshop-prototype"}, {b["join"] for b in candidate})
        self.assertEqual("workshop/test-load", bodies[-1]["name"])
        self.assertEqual(0.04, setup["requested_cell_size_m"])
        self.assertLessEqual(setup["cell_size_m"], setup["requested_cell_size_m"])
        self.assertLessEqual(setup["cells"], 16000)
        self.assertTrue(all(workshop_trials._fits_cell(body, setup["cell_size_m"]) for body in bodies))

    def test_default_table_refines_only_as_far_as_geometry_and_budget_need(self):
        setup = workshop_trials.prototype_scene(assemble("table", design_id="t"), load_kg=100)
        # Do not lock the test to one magic resolution: the chooser is allowed
        # to use any finer cell that represents every member while staying in
        # the realtime scratch lane's cell budget.
        self.assertLess(setup["cell_size_m"], setup["requested_cell_size_m"])
        self.assertGreaterEqual(setup["cell_size_m"], 0.005)
        self.assertLessEqual(setup["cells"], 16000)
        self.assertTrue(all(workshop_trials._fits_cell(body, setup["cell_size_m"])
                            for body in setup["spec"]["bodies"]))

    def test_mixed_material_fused_trial_is_refused_instead_of_lying(self):
        cart = assemble("cart", design_id="cart")
        self.assertGreater(len({p.material for p in cart.parts}), 1)
        with self.assertRaisesRegex(ValueError, "mixed-material"):
            workshop_trials.prototype_scene(cart, load_kg=100)

    def test_engine_unknown_display_material_is_refused(self):
        table = assemble("table", design_id="pine", parameters={"material": "pine"})
        with self.assertRaisesRegex(ValueError, "engine material preset"):
            workshop_trials.prototype_scene(table, load_kg=100)

    def test_taper_is_declared_as_a_trial_approximation(self):
        setup = workshop_trials.prototype_scene(
            assemble("table", design_id="taper", parameters={"leg_style": "tapered"}), load_kg=100)
        self.assertTrue(any(name.startswith("leg-") for name in setup["approximated_parts"]))


class Running(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name); FakeSession.made.clear()

    def tearDown(self): self.tmp.cleanup()

    def test_trial_owns_and_closes_a_session_without_touching_app_live(self):
        app = App(self.root); live_before, room_before = app.live, dict(app.room)
        answer = workshop_trials.run_static_load(
            app, assemble("table", design_id="t"), load_kg=100,
            duration_s=0.1, session_factory=FakeSession)
        self.assertIs(app.live, live_before); self.assertEqual(room_before, app.room)
        self.assertEqual(1, len(FakeSession.made)); self.assertTrue(FakeSession.made[0].closed)
        self.assertEqual("engine-trial", answer["evidence"])
        self.assertEqual("not-declared", answer["acceptance"]["status"])
        self.assertTrue(answer["measured"]["prototype_present"])
        self.assertLess(answer["prototype"]["effective_cell_size_m"], answer["requested"]["cell_size_m"])
        self.assertLessEqual(answer["prototype"]["cells"], 16000)

    def test_declared_load_is_taken_from_the_assembly_not_a_page_guess(self):
        answer = workshop_trials.run_declared_static_load(
            App(self.root), assemble("chair", design_id="chair"),
            duration_s=0.1, session_factory=FakeSession)
        self.assertEqual(120.0, answer["requested"]["load_kg"])
        self.assertLess(answer["prototype"]["effective_cell_size_m"], 0.02)
        self.assertLessEqual(answer["prototype"]["cells"], 16000)


if __name__ == "__main__": unittest.main()
