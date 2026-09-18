from __future__ import annotations

import base64
import struct
from dataclasses import replace
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
        if command["op"] == "snapshot":
            h = self.spec["cell_m"]
            cells = set()
            for body in self.spec["bodies"]:
                if not body.get("join"):
                    continue
                counts = [round(v/1000/h) for v in body["size_mm"]]
                lo = [round(body["center_mm"][a]/1000/h-counts[a]/2) for a in range(3)]
                cells.update((x,y,z) for x in range(lo[0],lo[0]+counts[0])
                             for y in range(lo[1],lo[1]+counts[1])
                             for z in range(lo[2],lo[2]+counts[2]))
            offsets = b"".join(struct.pack("<ddd", *((g[a]+.5)*h-self.root_at[a] for a in range(3)))
                               for g in sorted(cells))
            return {"snapshot": {"bodies": [{"name": self.root_name,
                "material": self.spec["bodies"][0]["material"],
                "offsets_b64": base64.b64encode(offsets).decode(),
                "pose": {"com_m": self.root_at, "q_wxyz": [1,0,0,0]}}]}}
        if command["op"] == "poses": return self._state()
        if command["op"] == "step":
            self.t += float(command["dt"]) * int(command["n"])
            return self._state()
        raise AssertionError(command)

    def close(self): self.closed = True


class PrototypeScene(unittest.TestCase):
    def test_table_is_encoded_as_the_exact_matter_union_plus_only_the_test_load(self):
        setup = workshop_trials.prototype_scene(
            assemble("table", design_id="t"), load_kg=100, cell_size_m=0.04)
        bodies = setup["spec"]["bodies"]
        candidate = [b for b in bodies if str(b["name"]).startswith("candidate/")]
        self.assertGreaterEqual(len(candidate), 1)
        joins = {b.get("join") for b in candidate}
        self.assertEqual(1, len(joins))
        self.assertTrue(next(iter(joins)).startswith("workshop-matter-"))
        self.assertEqual("workshop/test-load", bodies[-1]["name"])
        self.assertEqual(0.04, setup["requested_cell_size_m"])
        self.assertEqual(0.04, setup["cell_size_m"])
        self.assertTrue(setup["matter_roundtrip_exact"])
        self.assertGreater(setup["matter_cells"], 0)
        self.assertGreater(setup["matter_boxes"], 0)
        self.assertLessEqual(setup["matter_boxes"], setup["matter_cells"])
        self.assertEqual(64, len(setup["matter_physics_hash"]))
        self.assertEqual(64, len(setup["matter_artifact_hash"]))

    def test_exact_scene_boxes_are_grid_aligned_and_cover_the_canonical_cells(self):
        cell = 0.02
        setup = workshop_trials.prototype_scene(
            assemble("table", design_id="grid-table"), load_kg=100, cell_size_m=cell)
        candidate = [b for b in setup["spec"]["bodies"] if b.get("join")]
        for body in candidate:
            size_cells = [round(float(v) / 1000.0 / cell) for v in body["size_mm"]]
            self.assertTrue(all(n >= 1 for n in size_cells))
            self.assertTrue(all(abs(float(body["size_mm"][i]) / 1000.0 - size_cells[i] * cell) < 1e-9
                                for i in range(3)))
            self.assertTrue(all(abs(2.0 * float(v) / 1000.0 / cell
                                    - round(2.0 * float(v) / 1000.0 / cell)) < 1e-9
                                for v in body["center_mm"]))
        self.assertTrue(setup["matter_roundtrip_exact"])

    def test_mixed_material_fused_trial_is_refused_instead_of_lying(self):
        mixed = assemble("table", design_id="mixed")
        mixed.parts = [replace(p, material="iron") if p.name == "top" else p for p in mixed.parts]
        self.assertGreater(len({p.material for p in mixed.parts}), 1)
        with self.assertRaisesRegex(ValueError, "one material|mixed-material"):
            workshop_trials.prototype_scene(mixed, load_kg=100, cell_size_m=0.02)

    def test_engine_unknown_display_material_is_refused(self):
        table = assemble("table", design_id="pine", parameters={"material": "pine"})
        with self.assertRaisesRegex(ValueError, "material preset"):
            workshop_trials.prototype_scene(table, load_kg=100)

    def test_taper_is_compiled_to_cells_not_replaced_by_a_box(self):
        straight = workshop_trials.prototype_scene(
            assemble("table", design_id="straight", parameters={"leg_style": "straight"}),
            load_kg=100, cell_size_m=0.02)
        tapered = workshop_trials.prototype_scene(
            assemble("table", design_id="taper", parameters={"leg_style": "tapered"}),
            load_kg=100, cell_size_m=0.02)
        self.assertTrue(tapered["matter_roundtrip_exact"])
        self.assertNotEqual(straight["matter_physics_hash"], tapered["matter_physics_hash"])
        self.assertNotEqual(straight["matter_cells"], tapered["matter_cells"])


class Running(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name); FakeSession.made.clear()

    def tearDown(self): self.tmp.cleanup()

    def test_trial_owns_and_closes_a_session_without_touching_app_live(self):
        app = App(self.root); live_before, room_before = app.live, dict(app.room)
        answer = workshop_trials.run_static_load(
            app, assemble("table", design_id="t"), load_kg=100,
            cell_size_m=0.04, duration_s=0.1, session_factory=FakeSession)
        self.assertIs(app.live, live_before); self.assertEqual(room_before, app.room)
        self.assertEqual(1, len(FakeSession.made)); self.assertTrue(FakeSession.made[0].closed)
        self.assertEqual("engine-trial", answer["evidence"])
        self.assertEqual("not-declared", answer["acceptance"]["status"])
        self.assertTrue(answer["measured"]["prototype_present"])
        self.assertEqual(answer["requested"]["cell_size_m"], answer["prototype"]["effective_cell_size_m"])
        self.assertTrue(answer["prototype"]["matter_roundtrip_exact"])
        self.assertTrue(answer["prototype"]["engine_grid_verified"])
        self.assertEqual(answer["prototype"]["matter_cells"], answer["prototype"]["engine_cells"])
        self.assertGreater(answer["prototype"]["matter_cells"], 0)
        self.assertEqual("joined-grid-boxes-exact-cell-union", answer["prototype"]["engine_geometry"])
        self.assertEqual(64, len(answer["prototype"]["matter_physics_hash"]))

    def test_declared_load_is_taken_from_the_assembly_not_a_page_guess(self):
        answer = workshop_trials.run_declared_static_load(
            App(self.root), assemble("chair", design_id="chair"),
            cell_size_m=0.02, duration_s=0.1, session_factory=FakeSession)
        self.assertEqual(120.0, answer["requested"]["load_kg"])
        self.assertEqual(0.02, answer["prototype"]["effective_cell_size_m"])
        self.assertTrue(answer["prototype"]["matter_roundtrip_exact"])
        self.assertTrue(answer["prototype"]["engine_grid_verified"])
        self.assertEqual(answer["prototype"]["matter_cells"], answer["prototype"]["engine_cells"])
        self.assertIn("actual_grid_load_kg", answer["measured"])



class NativeMatterVerification(unittest.TestCase):
    def test_native_cell_mismatch_and_material_mismatch_are_refused(self):
        from copy import deepcopy
        import workshop_sparse_trial
        setup = workshop_trials.prototype_scene(assemble("table"),load_kg=10,cell_size_m=.04)
        session = FakeSession(None,setup["spec"],None)
        snapshot = session.send(op="snapshot")["snapshot"]
        proof = workshop_sparse_trial.verify_engine_matter(snapshot,setup["matter"],setup["root_body"])
        self.assertTrue(proof["engine_grid_verified"])
        changed = deepcopy(snapshot);changed["bodies"][0]["material"]="iron"
        with self.assertRaisesRegex(ValueError,"material differs"):
            workshop_sparse_trial.verify_engine_matter(changed,setup["matter"],setup["root_body"])
        changed = deepcopy(snapshot)
        raw = base64.b64decode(changed["bodies"][0]["offsets_b64"])
        changed["bodies"][0]["offsets_b64"]=base64.b64encode(raw[:-24]).decode()
        with self.assertRaisesRegex(ValueError,"cells differ"):
            workshop_sparse_trial.verify_engine_matter(changed,setup["matter"],setup["root_body"])


class SimulationTraceTests(unittest.TestCase):
    def state(self, t):
        return {"t":t, "bodies":[{"name":"body", "position_m":[t,0,0]}]}

    def test_trace_is_bounded_and_sampling_stays_uniform_over_full_span(self):
        from workshop_recording import Recorder
        for capacity in (2, 20, 600):
            with self.subTest(capacity=capacity):
                recorder = Recorder(object(), max_frames=capacity)
                for i in range(6001):
                    recorder.capture(self.state(i/30))
                    self.assertLessEqual(len(recorder.frames), capacity)
                trace = recorder.recording(test="inspection")
                self.assertEqual(0,trace["frames"][0]["t_s"])
                self.assertEqual(200,trace["frames"][-1]["t_s"])
                self.assertLessEqual(trace["sampling"]["max_gap_s"], trace["sampling"]["effective_period_s"]+2e-6)
                self.assertTrue(trace["sampling"]["thinned"])

    def test_subsystem_query_does_not_erase_pose_or_clock(self):
        from workshop_recording import Recorder
        class Session:
            state = {"t":1.0}
        recorder=Recorder(Session())
        recorder.capture(self.state(1.0))
        recorder.capture({"thermo":{"temperature_k":340}})
        recorder.capture(self.state(1.0))
        self.assertEqual(1,len(recorder.frames))
        self.assertEqual(340,recorder.frames[0]["thermo"]["temperature_k"])
        self.assertEqual(1,recorder.frames[0]["t_s"])
        self.assertTrue(recorder.frames[0]["bodies"])

    def test_event_overflow_is_explicit_and_bounded(self):
        from workshop_recording import Recorder
        recorder=Recorder(object(),max_frames=10)
        for i in range(500):recorder.capture(self.state(i/30),event="drive")
        self.assertLessEqual(len(recorder.events),40)
        self.assertTrue(recorder.recording(test="events")["events_truncated"])

    def test_trace_can_be_disabled_without_skipping_native_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=workshop_trials.run_static_load(App(Path(tmp)),assemble("table"),
                load_kg=10,cell_size_m=.04,duration_s=.1,
                session_factory=FakeSession,record_trace=False)
        self.assertNotIn("playback",result)
        self.assertNotIn("render_geometry",result)
        self.assertTrue(result["prototype"]["engine_grid_verified"])


if __name__ == "__main__": unittest.main()
