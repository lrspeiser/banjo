"""Generic recipe validation, HTTP/MCP parity and native trial lifecycle."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"playground"),str(ROOT/"tests")]
import physics_trials as trial
import mechanics_qa as qa
import physics_trial_planner as planner
from mcp import physics_trial_tools as tools, workshop_mcp_tools
from workbench_tests import WorkbenchTestCase

def example(name="bounded-lift-oak"):
    return deepcopy(next(c["document"] for c in qa.cases() if c["id"]==name))

class Contracts(unittest.TestCase):
    def test_all_fixtures_use_the_same_validator(self):
        self.assertEqual(len(qa.cases()),23)
        for c in qa.cases(): trial.validate(c["document"])
        self.assertFalse(qa.catalog(None)["engine_available"])

    def test_rejects_unbounded_or_scripted_actions_before_start(self):
        changes=[
          lambda d:d["steps"].append({"op":"teleport","to":[1,2,3]}),
          lambda d:d.update(cell_m=float("nan")),
          lambda d:d["actuator"].update(strength_n=True),
          lambda d:d["actuator"].update(strength_n=1001),
          lambda d:d["bodies"][0].update(size_m=[2,2,2]),
          lambda d:d["bodies"].append(deepcopy(d["bodies"][0])),
          lambda d:d["steps"][0].update(name="missing"),
          lambda d:d["steps"][0].update(force_magic=True),
          lambda d:d["steps"].insert(3,{"op":"checkpoint"}),
          lambda d:d["checks"][0].update(metric="health_points"),
          lambda d:d["checks"][0].update(metric=[]),
          lambda d:d["checks"][0].update(body={}),
          lambda d:d["steps"][0].update(op=[]),
          lambda d:d["steps"][0].update(name={}),
          lambda d:d["bodies"][0].update(material=[]),
          lambda d:d["checks"][0].update(min=10,max=1),
          lambda d:d["steps"][2].update(duration_s=6),
          lambda d:d["steps"][2].update(duration_s=.001),
        ]
        for change in changes:
            d=example();change(d)
            with self.subTest(document=d):
                with self.assertRaises(ValueError):trial.validate(d)

    def test_initial_overlap_and_late_construction_are_rejected(self):
        d=example("connection-strong-glass")
        d["bodies"][1]["position_m"]=d["bodies"][0]["position_m"]
        with self.assertRaises(ValueError):trial.validate(d)
        d=example("connection-strong-glass")
        d["steps"].insert(0,{"op":"advance","duration_s":.1})
        with self.assertRaises(ValueError):trial.validate(d)

    def test_validation_does_not_mutate_recipe_or_regression(self):
        d=example("support-oak");original=deepcopy(d)
        normalized,_=trial.validate(d)
        self.assertEqual(d,original)
        self.assertIn("actuator",normalized)
        d["checks"][0]["min"]=-1
        self.assertEqual(example("support-oak"),original)

    def test_mcp_calls_the_same_validator(self):
        d=example()
        self.assertEqual(tools.validate({"document":d})["document"],trial.validate(d)[0])
        self.assertEqual({t["name"] for t in tools.TOOLS},set(tools.HANDLERS))
        with mock.patch.object(workshop_mcp_tools,"APP",SimpleNamespace(engine_path=None)):
            self.assertFalse(tools.catalog({})["engine_available"])

    def test_planner_cannot_execute_or_accept_unknown_operations(self):
        app=SimpleNamespace(api_key="test-key",model="test")
        proposed={"document":example(),"explanation":"Change applied"}
        response={"status":"completed","output":[{"content":[{"type":"output_text","text":json.dumps(proposed)}]}]}
        def reply():
            cm=mock.MagicMock()
            import io
            cm.__enter__.return_value=io.StringIO(json.dumps(response))
            return cm
        with mock.patch.object(planner.request,"urlopen",return_value=reply()),mock.patch.object(trial,"run") as run:
            result=planner.propose(app,{"message":"Inspect recipe","document":example()})
            self.assertFalse(result["executed"]);run.assert_not_called()
        proposed["document"]["steps"][0]={"op":"teleport"}
        response["output"][0]["content"][0]["text"]=json.dumps(proposed)
        with mock.patch.object(planner.request,"urlopen",return_value=reply()):
            with self.assertRaises(ValueError):planner.propose(app,{"message":"Edit","document":example()})

    def test_watchdog_kills_and_reaps_an_unresponsive_owned_child(self):
        # Exercise the actual pipe wait; no substitute solver is accepted as evidence.
        process=subprocess.Popen([sys.executable,"-c","import time; time.sleep(10)"],
                                 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        s=trial.TrialSession.__new__(trial.TrialSession)
        s._process=process;s.cancel=threading.Event();s.deadline=time.monotonic()+.1
        s.finished=threading.Event();s.watcher=None;s.stopped_reason=None
        s._lock=threading.RLock();s._closed=False
        try:
            with self.assertRaisesRegex(ValueError,"deadline"):
                s._read("test")
        finally:s.close()
        self.assertIsNotNone(process.poll())

    def test_cancel_also_reaps_blocked_startup(self):
        process=subprocess.Popen([sys.executable,"-c","import time; time.sleep(10)"],
                                 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        s=trial.TrialSession.__new__(trial.TrialSession)
        s._process=process;s.cancel=threading.Event();s.cancel.set();s.deadline=time.monotonic()+5
        s.finished=threading.Event();s.watcher=None;s.stopped_reason=None
        s._lock=threading.RLock();s._closed=False
        try:
            with self.assertRaisesRegex(ValueError,"cancelled"):s._read("test")
        finally:s.close()
        self.assertIsNotNone(process.poll())

    def test_manager_rejects_paths_and_conflicting_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=qa.Manager(SimpleNamespace(runs_path=Path(folder),engine_path=None))
            with self.assertRaises(ValueError):manager.folder("../outside")
            with self.assertRaises(ValueError):manager.start({"document":example(),"case_ids":[]})
            with self.assertRaises(ValueError):manager.start({"document":example()})
            with self.assertRaises(ValueError):manager.case("a"*32,"../outside")
            manager.shutdown()


    def test_status_reads_final_report_when_worker_finishes_during_read(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=qa.Manager(SimpleNamespace(runs_path=Path(folder),engine_path=None))
            manager.run_id="a"*32
            manager.thread=SimpleNamespace(is_alive=lambda:False)
            path=manager.folder(manager.run_id)/"report.json"
            qa.artifacts.write_json(path,{"id":manager.run_id,"status":"passed"})
            with mock.patch.object(qa.artifacts,"read_json",side_effect=[
                    {"id":manager.run_id,"status":"running"},{"id":manager.run_id,"status":"passed"}]):
                self.assertEqual(manager.status(manager.run_id)["status"],"passed")
            manager.shutdown()


    def test_transient_windows_report_sharing_is_retried_but_not_hidden(self):
        action=mock.Mock(side_effect=[PermissionError("sharing"),{"status":"passed"}])
        with mock.patch.object(qa.artifacts.time,"sleep"):
            self.assertEqual(qa.artifacts._file_access(action),{"status":"passed"})
            self.assertEqual(action.call_count,2)
            denied=mock.Mock(side_effect=PermissionError("denied"))
            with self.assertRaises(PermissionError):qa.artifacts._file_access(denied)
            self.assertEqual(denied.call_count,20)

class HTTP(WorkbenchTestCase):
    def test_catalog_validation_and_static_page_preserve_live_room(self):
        app=self.start()
        original=app.live
        data=self.get(app,"/api/mechanics-qa")
        self.assertEqual(len(data["cases"]),23)
        data=self.post(app,"/api/mechanics-qa/validate",{"document":example()})
        self.assertTrue(data["valid"])
        status,content,raw=self.request(app,"GET","/mechanics-qa")
        self.assertEqual(status,200);self.assertIn("text/html",content)
        self.assertIn(b"mechanics-qa.js",raw)
        self.assertIs(app.live,original)


@unittest.skipUnless(os.environ.get("BANJO_TRIAL_ENGINE"), "Set BANJO_TRIAL_ENGINE for the native MCP protocol test (required in CI)")
class NativeProtocol(unittest.TestCase):
    def test_platform_tools_run_and_return_the_same_native_evidence(self):
        import banjo_mcp_tests as protocol
        with tempfile.TemporaryDirectory() as folder:
            environment={"BANJO_WORKSHOP_HOME":folder,
                         "BANJO_LIVE_ENGINE":str(Path(os.environ["BANJO_TRIAL_ENGINE"]).resolve())}
            with mock.patch.dict(os.environ,environment),mock.patch.object(protocol,"SERVER",ROOT/"mcp/banjo_platform_mcp.py"):
                client=protocol.Client()
                watchdog=threading.Timer(30,client.process.kill);watchdog.start()
                try:
                    hello=client.send("initialize",{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"qa","version":"1"}})
                    self.assertEqual(hello["result"]["serverInfo"]["version"],"1.8.0")
                    offered=client.send("tools/list")["result"]["tools"]
                    names=[t["name"] for t in offered]
                    self.assertEqual(len(names),len(set(names)))
                    self.assertTrue(set(tools.HANDLERS).issubset(names))
                    catalog=client.call("physics_trial_catalog")
                    self.assertEqual(len(catalog["cases"]),23)
                    doc=example()
                    self.assertTrue(client.call("physics_trial_validate",document=doc)["valid"])
                    client.refuse("physics_trial_validate",document={**doc,"steps":[{"op":"teleport"}]})
                    started=client.call("physics_trial_run",case_ids=["bounded-lift-oak","bounded-lift-iron"])
                    deadline=time.monotonic()+20
                    while time.monotonic()<deadline:
                        report=client.call("physics_trial_status",run_id=started["id"])
                        if report["status"] not in ("starting","running"):break
                        time.sleep(.05)
                    self.assertEqual(report["status"],"passed",report)
                    self.assertEqual(report["completed"],2)
                    actual=client.call("physics_trial_case",run_id=started["id"],case_id="bounded-lift-oak")
                    recorded=client.call("physics_trial_case",run_id=started["id"],case_id="bounded-lift-oak",artifact="playback")
                    request=client.call("physics_trial_case",run_id=started["id"],case_id="bounded-lift-oak",artifact="request")
                    self.assertEqual(request,trial.validate(doc)[0])
                    dy=recorded["frames"][-1]["poses"][0]["position_m"][1]-recorded["frames"][0]["poses"][0]["position_m"][1]
                    self.assertAlmostEqual(dy,next(c["value"] for c in actual["checks"] if c["metric"]=="displacement_y_m"))
                    self.assertTrue(any(r["id"]==started["id"] for r in client.call("physics_trial_status")["runs"]))
                    client.refuse("physics_trial_case",run_id=started["id"],case_id="../outside")
                finally:
                    watchdog.cancel();client.close()

if __name__=="__main__":unittest.main()
