"""Exercise the browser/MCP QA runner outside the suite it launches."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"playground"),str(ROOT/"tests")]
from workbench_tests import WorkbenchTestCase
import live_session
import fabrication_mcp_tools
import fabrication_qa

ENGINE=Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None

@unittest.skipUnless(ENGINE and ENGINE.is_file(),"BANJO_LIVE_ENGINE is required")
class IsolatedRunner(WorkbenchTestCase):
    def native(self):
        app=self.start();app.engine_path=ENGINE;app.live=live_session.Live()
        self.addCleanup(app.live.shutdown)
        opened=self.post(app,"/api/world/open",{"scene":"fabrication"})
        manager=fabrication_qa.manager(app);self.addCleanup(manager.shutdown)
        return app,manager,opened

    def test_http_launch_mcp_status_recorded_results_and_unchanged_live_room(self):
        app,manager,opened=self.native()
        old=app.live.session
        saved=app.store.path_of("fabrication").read_bytes()
        status,_,raw=self.request(app,"POST","/api/fabrication-qa/run",{})
        self.assertEqual(status,202,raw)
        ident=json.loads(raw)["id"]
        status,_,_=self.request(app,"POST","/api/fabrication-qa/run",{})
        self.assertEqual(status,400)
        manager.thread.join(timeout=45);self.assertFalse(manager.thread.is_alive())
        report=self.get(app,"/api/fabrication-qa/runs/"+ident)
        self.assertEqual(report["status"],"passed",report)
        self.assertEqual(report["completed"],len(report["results"]))
        self.assertTrue(all(r["status"]=="passed" for r in report["results"]))
        self.assertTrue(any(r.get("measurements") for r in report["results"]))
        self.assertTrue(any('test_compiled_bearing_moves_under_gravity' in r['id'] and len(r.get('measurements',[]))==3 for r in report['results']))
        self.assertTrue(any('test_articulated_staging_preserves_old_motion' in r['id'] and len(r.get('measurements',[]))==3 for r in report['results']))
        self.assertEqual(len(report["engine_sha256"]),64)
        self.assertEqual(len(report["library_sha256"]),64)
        self.assertIs(app.live.session,old)
        self.assertEqual(app.store.path_of("fabrication").read_bytes(),saved)
        with mock.patch.dict(os.environ,{"BANJO_PLAYGROUND_URL":f"http://127.0.0.1:{app.port}"}):
            self.assertEqual(fabrication_mcp_tools.call("fabrication_qa_status",{"run_id":ident}),report)
            self.assertEqual(fabrication_mcp_tools.call("fabrication_qa_status",{})["runs"][0]["id"],ident)
        for body in ({"command":"arbitrary"},[],None):
            with self.assertRaises(ValueError):manager.start(body)
        with self.assertRaises(ValueError):manager.status("../escape")

    def test_cancel_keeps_report_and_live_room(self):
        app,manager,opened=self.native();old=app.live.session
        with mock.patch.dict(os.environ,{"BANJO_PLAYGROUND_URL":f"http://127.0.0.1:{app.port}"}):
            started=fabrication_mcp_tools.call("fabrication_qa_run",{})
            cancelled=fabrication_mcp_tools.call("fabrication_qa_cancel",{"run_id":started["id"]})
        self.assertEqual(cancelled["status"],"cancelling")
        manager.thread.join(timeout=15);self.assertFalse(manager.thread.is_alive())
        self.assertEqual(manager.status(started["id"])["status"],"cancelled")
        self.assertIs(app.live.session,old)

if __name__=="__main__":unittest.main()
