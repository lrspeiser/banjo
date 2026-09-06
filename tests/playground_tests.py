"""Bounded playground language and local HTTP boundary tests.

Run from the repository root:
    python tests/playground_tests.py -v

These tests use an injected planner, fake engine, and ephemeral loopback HTTP
server. They never call the OpenAI API or launch a native Banjo process/window.
"""

from __future__ import annotations

from copy import deepcopy
import http.client
from http.server import ThreadingHTTPServer
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
sys.path.insert(0, str(ROOT / "examples" / "authoring"))

import experiment_language as language
import server as playground_server


PRIVATE_KEY = "private-test-key-never-return"


def plan_for(experiment="panel_impact", **changes):
    plan = {
        "language": "banjo-playground-1",
        "name": "Bounded test experiment",
        "experiment": experiment,
        "explanation": "A bounded test plan; no calibration claim.",
        "limitations": ["Synthetic unit-test plan."],
        "speeds_m_s": [2.0] if experiment in ("panel_impact", "knife_cut") else [],
        "heights_m": [0.25] if experiment in ("plate_drop", "rigid_drop") else [],
        "duration_s": 1.0,
        "projectile": "iron_ball",
        "panel_dimensions_m": [0.5, 0.36, 0.006] if experiment == "glass_reference" else [0.24, 0.36, 0.04],
        "objects": [],
    }
    if experiment == "custom_objects":
        plan["objects"] = [{
            "preset": "iron_ball",
            "position_m": [0.0, 0.5, 0.0],
            "velocity_m_s": [0.0, 0.0, 0.0],
            "dimensions_m": None,
        }]
    plan.update(changes)
    return plan


class InlineExecutor:
    """Small executor with deterministic, same-thread worker execution."""

    def submit(self, function, *args, **kwargs):
        function(*args, **kwargs)
        return object()

    def shutdown(self, wait=True, cancel_futures=False):
        return None


class HoldingExecutor:
    """Records work without running it, leaving the job in planning state."""

    def __init__(self):
        self.calls = []

    def submit(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return object()

    def shutdown(self, wait=True, cancel_futures=False):
        return None


class FakeEngine:
    def __init__(self):
        self.call_order = []
        self.validated_paths = []
        self.run_calls = []
        self.validation_error = None

    def validate(self, path):
        path = Path(path).resolve()
        self.call_order.append(("validate", path))
        self.validated_paths.append(path)
        if self.validation_error is not None:
            raise self.validation_error
        return {"status": "valid"}

    def run(self, path, steps):
        path = Path(path).resolve()
        self.call_order.append(("run", path, steps))
        self.run_calls.append((path, steps))
        return {"status": "complete", "steps": steps}


class FakeHTTPResponse:
    def __init__(self, value):
        self.payload = json.dumps(value, allow_nan=False).encode("utf-8")
        self.requested_read_size = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size=-1):
        self.requested_read_size = size
        return self.payload


class StrictJsonTests(unittest.TestCase):
    def test_duplicate_fields_are_rejected_at_every_object_level(self):
        for text in ('{"a":1,"a":2}', '{"outer":{"a":1,"a":2}}'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Duplicate JSON field"):
                playground_server.strict_json(text)

    def test_nonfinite_json_constants_are_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Nonfinite JSON value"):
                playground_server.strict_json('{"value":' + value + "}")

    def test_finite_json_is_preserved(self):
        parsed = playground_server.strict_json(b'{"finite":1.25,"items":[true,null]}')
        self.assertEqual(parsed, {"finite": 1.25, "items": [True, None]})


class PlanValidationTests(unittest.TestCase):
    def test_exact_top_level_and_custom_object_fields_are_required(self):
        unknown = plan_for()
        unknown["shell"] = "powershell -File arbitrary.ps1"
        missing = plan_for()
        del missing["duration_s"]
        object_path = plan_for("custom_objects")
        object_path["objects"][0]["path"] = "../../.env"
        for plan in (unknown, missing, object_path):
            with self.subTest(keys=sorted(plan)), self.assertRaisesRegex(ValueError, "Unknown or missing"):
                language.validate_plan(plan)

    def test_numeric_ranges_and_boolean_numbers_are_rejected(self):
        invalid = [
            plan_for(duration_s=0.049),
            plan_for(duration_s=3.001),
            plan_for(duration_s=True),
            plan_for(speeds_m_s=[-0.01]),
            plan_for(speeds_m_s=[20.01]),
            plan_for(speeds_m_s=[math.inf]),
            plan_for(speeds_m_s=[2.0] * 5),
            plan_for("plate_drop", heights_m=[-0.01]),
            plan_for("plate_drop", heights_m=[2.01]),
            plan_for("plate_drop", heights_m=[math.nan]),
            plan_for("plate_drop", heights_m=[0.25] * 5),
            plan_for(panel_dimensions_m=[0.079, 0.36, 0.04]),
            plan_for(panel_dimensions_m=[0.24, 0.36, 0.011]),
            plan_for(panel_dimensions_m=[0.24, 0.36, 0.151]),
            plan_for(panel_dimensions_m=[0.24, 0.36]),
        ]
        for index, plan in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                language.validate_plan(plan)

    def test_text_array_and_object_budgets_are_enforced(self):
        object_template = plan_for("custom_objects")["objects"][0]
        invalid = [
            plan_for(name=""),
            plan_for(name="n" * 121),
            plan_for(explanation="e" * 2501),
            plan_for(limitations=["limit"] * 13),
            plan_for(limitations=["x" * 1001]),
            plan_for("custom_objects", objects=[deepcopy(object_template) for _ in range(13)]),
        ]
        for index, plan in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                language.validate_plan(plan)

    def test_required_sweeps_and_projectile_capabilities_are_enforced(self):
        invalid = [
            plan_for(speeds_m_s=[]),
            plan_for("knife_cut", speeds_m_s=[]),
            plan_for("plate_drop", heights_m=[]),
            plan_for("rigid_drop", heights_m=[]),
            plan_for("plate_drop", projectile="knife"),
            plan_for("rigid_drop", projectile="axe_head"),
            plan_for("custom_objects", objects=[]),
        ]
        for index, plan in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                language.validate_plan(plan)

    def test_template_experiments_reject_ignored_custom_objects(self):
        explicit_object = deepcopy(plan_for("custom_objects")["objects"])
        for experiment in ("panel_impact", "plate_drop", "rigid_drop", "knife_cut",
                           "thermal_frontier", "material_state_reference",
                           "glass_reference", "unsupported"):
            plan = plan_for(experiment, objects=deepcopy(explicit_object))
            with self.subTest(experiment=experiment), self.assertRaisesRegex(
                    ValueError, "require objects=\\[\\]"):
                language.validate_plan(plan)

    def test_thin_network_panel_is_rejected_but_glass_reference_is_admitted(self):
        with self.assertRaisesRegex(ValueError, "thin tempered glass"):
            language.validate_plan(plan_for(panel_dimensions_m=[0.5, 0.36, 0.006]))
        reference = plan_for("glass_reference")
        self.assertIs(language.validate_plan(reference), reference)
        self.assertEqual(language.compile_plan(reference), [])

    def test_reference_dimensions_remain_finite_and_bounded(self):
        for dimensions in ([0.0, 0.36, 0.006], [1.001, 0.36, 0.006], [0.5, math.nan, 0.006]):
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                language.validate_plan(plan_for("glass_reference", panel_dimensions_m=dimensions))

    def test_cell_admission_budget_rejects_three_dense_matter_balls(self):
        entries = []
        for index, preset in enumerate(("glass_matter_ball", "wood_matter_ball", "iron_matter_ball")):
            entries.append({
                "preset": preset,
                "position_m": [float(index), 0.5, 0.0],
                "velocity_m_s": [0.0, 0.0, 0.0],
                "dimensions_m": None,
            })
        plan = plan_for("custom_objects", objects=entries)
        language.validate_plan(plan)
        with self.assertRaisesRegex(ValueError, "850-cell admission budget"):
            language.compile_plan(plan)


class CompilationTests(unittest.TestCase):
    def test_matched_panel_sweep_preserves_materials_dimensions_and_speeds(self):
        dimensions = [0.30, 0.40, 0.05]
        packages = language.compile_plan(plan_for(
            speeds_m_s=[2.5, 7.0], panel_dimensions_m=dimensions))
        self.assertEqual(len(packages), 2)
        for package, speed in zip(packages, (2.5, 7.0)):
            panels = package["objects"][::2]
            projectiles = package["objects"][1::2]
            self.assertEqual([panel["material"] for panel in panels], ["glass", "oak", "iron"])
            self.assertTrue(all(panel["dimensions_m"] == dimensions for panel in panels))
            self.assertEqual([projectile["velocity_m_s"] for projectile in projectiles],
                             [[0.0, 0.0, -speed]] * 3)
            self.assertEqual(len({panel["position_m"][0] for panel in panels}), 3)
            self.assertEqual(package["damage_integration"]["on_limit"], "reject")

    def test_plate_drop_height_sets_sphere_clearance_above_horizontal_panel(self):
        dimensions = [0.24, 0.36, 0.04]
        height = 0.625
        package = language.compile_plan(plan_for(
            "plate_drop", heights_m=[height], panel_dimensions_m=dimensions))[0]
        panels = package["objects"][::2]
        projectiles = package["objects"][1::2]
        self.assertEqual([panel["material"] for panel in panels], ["glass", "oak", "iron"])
        for panel, projectile in zip(panels, projectiles):
            projectile_half_height = projectile["dimensions_m"][1] / 2.0
            expected_y = 0.18 + dimensions[2] / 2.0 + projectile_half_height + height
            self.assertAlmostEqual(projectile["position_m"][1], expected_y)
            self.assertEqual(projectile["velocity_m_s"], [0, 0, 0])
            self.assertEqual(panel["orientation_wxyz"], [math.sqrt(0.5), math.sqrt(0.5), 0, 0])

    def test_rigid_drop_is_an_explicit_unpinned_no_damage_control(self):
        package = language.compile_plan(plan_for("rigid_drop", heights_m=[0.25]))[0]
        panels = package["objects"][::2]
        self.assertEqual([panel["material"] for panel in panels], ["glass", "oak", "iron"])
        for panel in panels:
            self.assertEqual(panel["representation"], "rigid")
            for network_only_field in ("resolution", "pin_boundary", "grain_wxyz"):
                self.assertNotIn(network_only_field, panel)
        self.assertNotIn("damage_integration", package)

    def test_custom_objects_only_compile_catalog_presets_and_data_fields(self):
        plan = plan_for("custom_objects", name="literal ; shell $(never) ../../.env")
        package = language.compile_plan(plan)[0]
        self.assertEqual(package["name"], plan["name"])
        self.assertEqual(len(package["objects"]), 1)
        obj = package["objects"][0]
        self.assertEqual(obj["material"], "iron")
        self.assertEqual(obj["position_m"], [0.0, 0.5, 0.0])
        self.assertNotIn("path", obj)
        self.assertNotIn("command", obj)


class PlaygroundTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.engine_path = self.base / "banjo_platform_cli.fake"
        self.studio_path = self.base / "banjo_network_lab.fake"
        self.engine_path.touch()
        self.studio_path.touch()

    def make_app(self, planner, executor=None):
        with mock.patch.object(
                playground_server, "local_configuration",
                return_value=(PRIVATE_KEY, "fake-model")):
            app = playground_server.Playground(
                self.engine_path, self.studio_path, self.base / "runs", planner=planner)
        app.pool.shutdown(wait=True, cancel_futures=True)
        app.pool = executor or InlineExecutor()
        app.engine = FakeEngine()
        self.addCleanup(app.pool.shutdown, wait=False, cancel_futures=True)
        return app


class PlannerTransportTests(unittest.TestCase):
    def test_mocked_upstream_response_produces_valid_plan_without_network(self):
        plan = plan_for("glass_reference")
        upstream = FakeHTTPResponse({
            "id": "response-test",
            "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": json.dumps(plan)}]}],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        })
        with mock.patch.object(playground_server.request, "urlopen", return_value=upstream) as urlopen:
            received, timing = playground_server.request_plan(
                PRIVATE_KEY, "fake-model", "show the glass reference")
        self.assertEqual(received, plan)
        self.assertEqual(timing["response_id"], "response-test")
        self.assertEqual(urlopen.call_count, 1)
        request_object = urlopen.call_args.args[0]
        self.assertEqual(request_object.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request_object.get_header("Authorization"), "Bearer " + PRIVATE_KEY)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 90)
        self.assertEqual(upstream.requested_read_size, 1024 * 1024 + 1)

    def test_mocked_upstream_malformed_plan_is_rejected(self):
        malformed = plan_for()
        malformed["file"] = "../../.env"
        upstream = FakeHTTPResponse({
            "id": "response-test",
            "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": json.dumps(malformed)}]}],
            "usage": {},
        })
        with mock.patch.object(playground_server.request, "urlopen", return_value=upstream):
            with self.assertRaisesRegex(ValueError, "Unknown or missing"):
                playground_server.request_plan(PRIVATE_KEY, "fake-model", "malformed")


class PlaygroundJobTests(PlaygroundTestCase):
    def test_request_identity_is_idempotent_and_changed_reuse_is_rejected(self):
        planner = mock.Mock(return_value=(plan_for("unsupported"), {"model": "fake-model"}))
        holding = HoldingExecutor()
        app = self.make_app(planner, holding)
        body = {
            "message": "bounded request",
            "previous_plan": None,
            "request_id": "request_0001",
            "auto_open": False,
        }
        first = app.submit(body)
        self.assertEqual(app.submit(deepcopy(body)), first)
        self.assertEqual(len(app.jobs), 1)
        self.assertEqual(len(holding.calls), 1)
        changed = deepcopy(body)
        changed["message"] = "changed content"
        with self.assertRaisesRegex(ValueError, "already used for different content"):
            app.submit(changed)
        second = deepcopy(body)
        second["request_id"] = "request_0002"
        with self.assertRaisesRegex(ValueError, "already running"):
            app.submit(second)

    def test_job_history_and_request_identity_budgets_are_bounded(self):
        planner = mock.Mock(return_value=(plan_for("unsupported"), {"model": "fake-model"}))
        app = self.make_app(planner, HoldingExecutor())
        app.jobs = {f"{index:032x}": {"status": "complete"} for index in range(100)}
        with self.assertRaisesRegex(ValueError, "100-job history budget"):
            app.submit({"message": "one too many", "request_id": "request_0101", "auto_open": False})
        self.assertEqual(planner.call_count, 0)
        for request_id in ("short", "contains space", "x" * 81):
            with self.subTest(request_id=request_id), self.assertRaisesRegex(ValueError, "Invalid request identity"):
                app.submit({"message": "bounded", "request_id": request_id, "auto_open": False})

    def test_all_packages_validate_before_any_engine_run(self):
        plan = plan_for(speeds_m_s=[2.0, 6.0], duration_s=0.1)
        planner = mock.Mock(return_value=(plan, {"model": "fake-model"}))
        app = self.make_app(planner)
        app.open_case = mock.Mock(side_effect=AssertionError("native window must not open"))
        result = app.submit({
            "message": "compare two speeds",
            "request_id": "request_0201",
            "auto_open": False,
        })
        job = app.get(result["job_id"])
        self.assertEqual(job["status"], "complete")
        self.assertEqual([call[0] for call in app.engine.call_order],
                         ["validate", "validate", "run", "run"])
        self.assertEqual([steps for _, steps in app.engine.run_calls], [48, 48])
        self.assertEqual(len(job["cases"]), 2)
        self.assertTrue(all(case["status"] == "complete" for case in job["cases"]))
        scene_directory = app.engine.validated_paths[0].parent
        self.assertEqual(scene_directory.name, "scenes")
        self.assertEqual({path.parent for path in app.engine.validated_paths}, {scene_directory})
        self.assertEqual(sorted(path.name for path in scene_directory.glob("*.json")),
                         ["case-00.json", "case-01.json"])
        self.assertEqual(list(scene_directory.glob("report-*.json")), [])
        self.assertEqual(sorted(path.name for path in scene_directory.parent.glob("report-*.json")),
                         ["report-00.json", "report-01.json"])
        app.open_case.assert_not_called()

    def test_worker_blocks_malformed_model_plan_before_files_or_engine(self):
        malformed = plan_for()
        malformed["command"] = "cmd.exe /c type .env"
        planner = mock.Mock(return_value=(malformed, {"model": "fake-model"}))
        app = self.make_app(planner)
        result = app.submit({
            "message": "malformed model output",
            "request_id": "request_0301",
            "auto_open": False,
        })
        job = app.get(result["job_id"])
        self.assertEqual(job["status"], "error")
        self.assertIn("Unknown or missing", job["error"])
        self.assertEqual(app.engine.call_order, [])
        self.assertFalse((app.runs_path / result["job_id"]).exists())

    def test_custom_object_native_capability_error_is_reported_without_running(self):
        planner = mock.Mock(return_value=(plan_for("custom_objects"), {"model": "fake-model"}))
        app = self.make_app(planner)
        app.engine.validation_error = playground_server.EngineError(
            64, {"error": "Native capability rejected this custom object"})
        with mock.patch.object(playground_server.subprocess, "run") as process_run, \
                mock.patch.object(playground_server.subprocess, "Popen") as process_open:
            result = app.submit({
                "message": "custom object",
                "request_id": "request_0401",
                "auto_open": False,
            })
        job = app.get(result["job_id"])
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["error"], "Native capability rejected this custom object")
        self.assertNotIn("calibrat", job["error"].lower())
        self.assertEqual([call[0] for call in app.engine.call_order], ["validate"])
        self.assertEqual(app.engine.run_calls, [])
        self.assertTrue(app.engine.validated_paths[0].is_relative_to(app.runs_path))
        process_run.assert_not_called()
        process_open.assert_not_called()

    def test_glass_reference_is_reference_only_and_never_reaches_engine(self):
        planner = mock.Mock(return_value=(plan_for("glass_reference"), {"model": "fake-model"}))
        app = self.make_app(planner)
        result = app.submit({
            "message": "documented six millimetre glass",
            "request_id": "request_0501",
            "auto_open": False,
        })
        job = app.get(result["job_id"])
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(job["cases"][0]["status"], "reference_only")
        self.assertEqual(job["cases"][0]["report"]["banjo_validation_status"], "not_run")
        self.assertEqual(app.engine.call_order, [])

    def test_private_key_is_redacted_from_worker_errors(self):
        planner = mock.Mock(side_effect=ValueError("upstream echoed " + PRIVATE_KEY))
        app = self.make_app(planner)
        result = app.submit({
            "message": "redaction",
            "request_id": "request_0601",
            "auto_open": False,
        })
        job_text = json.dumps(app.get(result["job_id"]), allow_nan=False)
        self.assertNotIn(PRIVATE_KEY, job_text)
        self.assertIn("[redacted]", job_text)

    def test_network_studio_receives_scene_directory_and_selected_filename(self):
        planner = mock.Mock(return_value=(plan_for("unsupported"), {"model": "fake-model"}))
        app = self.make_app(planner)
        job_id = "a" * 32
        scene_directory = self.base / "runs" / job_id / "scenes"
        scene_directory.mkdir(parents=True)
        scene_path = scene_directory / "case-00.json"
        scene_path.write_text("{}", encoding="utf-8")
        plan = plan_for(duration_s=0.1)
        package = language.compile_plan(plan)[0]
        app.paths[(job_id, 0)] = (scene_path, "network")
        app.jobs[job_id] = {
            "plan": plan,
            "cases": [{"package": package}],
        }

        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = playground_server.subprocess.TimeoutExpired(
            cmd=str(self.studio_path), timeout=0.2)
        with mock.patch.object(playground_server.subprocess, "Popen", return_value=process) as popen:
            self.assertEqual(app.open_case(job_id, 0), {"opened": True})

        args = popen.call_args.args[0]
        self.assertEqual(args[:4], [str(self.studio_path.resolve()), str(scene_directory.resolve()),
                                    scene_path.name, "--studio"])
        self.assertEqual(args[4:7], ["--duration-s", "0.1", "--live-report"])
        live_report = Path(args[7])
        self.assertEqual(live_report.parent, scene_directory.parent / "native")
        self.assertEqual(live_report.suffix, ".json")
        self.assertRegex(live_report.stem, r"^[0-9a-f]{32}$")
        self.assertTrue(live_report.parent.is_dir())
        self.assertFalse(live_report.is_relative_to(scene_directory))
        self.assertEqual(Path(popen.call_args.kwargs["cwd"]), scene_directory.resolve())
        self.assertEqual(len(app.studios), 1)


class PlaygroundHttpTests(PlaygroundTestCase):
    def setUp(self):
        super().setUp()
        planner = mock.Mock(return_value=(plan_for("unsupported"), {"model": "fake-model"}))
        self.app = self.make_app(planner)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), playground_server.Handler)
        self.httpd.app = self.app
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.port = self.httpd.server_port

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        headers = dict(headers or {})
        payload = None
        if body is not None:
            payload = json.dumps(body, allow_nan=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            decoded = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
            return response.status, dict(response.getheaders()), decoded
        finally:
            connection.close()

    def test_status_exposes_boolean_key_state_but_never_private_key(self):
        status, headers, body = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertIs(body["key_configured"], True)
        self.assertEqual(body["model"], "fake-model")
        self.assertEqual(body["csrf_token"], self.app.csrf_token)
        self.assertNotIn(PRIVATE_KEY, json.dumps(body, allow_nan=False))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_static_allowlist_and_environment_paths(self):
        for path in ("/", "/index.html", "/app.js", "/style.css"):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path)
                self.assertEqual(status, 200)
        for path in ("/.env", "/../.env", "/%2e%2e/.env", "/server.py", "/unknown"):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, 404)
                self.assertEqual(body, {"error": "Not found"})

    def test_host_origin_and_session_token_checks(self):
        bad_host, _, _ = self.request("GET", "/api/status", headers={"Host": "attacker.invalid"})
        self.assertEqual(bad_host, 400)
        bad_origin, _, _ = self.request(
            "GET", "/api/status", headers={"Origin": "https://attacker.invalid"})
        self.assertEqual(bad_origin, 400)

        body = {"message": "bounded", "request_id": "request_0701", "auto_open": False}
        missing, _, missing_body = self.request("POST", "/api/chat", body)
        self.assertEqual(missing, 403)
        self.assertIn("invalid local session token", missing_body["error"])
        wrong, _, _ = self.request(
            "POST", "/api/chat", body, headers={"X-Banjo-Token": "wrong"})
        self.assertEqual(wrong, 403)

        accepted, _, response = self.request(
            "POST", "/api/chat", body,
            headers={"X-Banjo-Token": self.app.csrf_token,
                     "Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(accepted, 202)
        self.assertRegex(response["job_id"], r"^[0-9a-f]{32}$")

    def test_unknown_post_path_is_not_dispatched(self):
        status, _, body = self.request(
            "POST", "/api/arbitrary", {},
            headers={"X-Banjo-Token": self.app.csrf_token})
        self.assertEqual(status, 404)
        self.assertEqual(body, {"error": "Not found"})


if __name__ == "__main__":
    unittest.main()
