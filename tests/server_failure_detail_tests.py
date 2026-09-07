from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"playground"))
import server


def thin_plan():
    """A 4 mm plate 240 mm across: 20:1 cells, refused on cell shape."""
    return {"experiment":"drop_test","name":"Saved thin network request",
            "drop":{"target_dimensions_m":[.24,.36,.004],"resolution":[6,9,2],
                    "representation":"network"}}


def small_cell_plan():
    """Cubic cells at 2.00 mm: the only failure left is the size floor."""
    return {"experiment":"drop_test","name":"Saved small-cell request",
            "drop":{"target_dimensions_m":[.024,.024,.024],"resolution":[12,12,12],
                    "representation":"network"}}


class FailureDetailTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);engine=self.base/"engine.fake";studio=self.base/"studio.fake"
        engine.touch();studio.touch()
        with mock.patch.object(server,"local_configuration",return_value=("","test-model")):
            self.app=server.Playground(engine,studio,self.base/"runs",planner=lambda *args:None)
        self.addCleanup(self.app.pool.shutdown)

    def test_describe_failure_generic_fallback(self):
        detail=server.describe_failure({"experiment":"drop_test"},"ordinary native failure")
        self.assertEqual(detail["code"],"experiment_error")
        self.assertEqual(detail["summary"],"ordinary native failure")
        self.assertIn("no computed playback",detail["scope"])

    def test_live_thin_network_failure_is_precise_and_defensively_copied(self):
        job_id="1"*32;plan=thin_plan();request="Test the saved four millimeter panel"
        error="network cells below collision resolution"
        self.app.jobs[job_id]={"id":job_id,"status":"error","plan":plan,
                               "request_text":request,"error":error,"cases":[]}
        result=self.app.get(job_id);detail=result["failure_detail"]
        self.assertEqual(detail["code"],"network_collision_resolution")
        self.assertIn("20.00:1, not cubic",detail["detail"])
        self.assertIn("spacing [40.0, 40.0, 2.0] mm",detail["detail"])
        self.assertEqual((result["plan"],result["request_text"],result["error"]),(plan,request,error))
        detail["detail"]="caller mutation";result["plan"]["drop"]["resolution"][2]=99
        again=self.app.get(job_id)
        self.assertIn("20.00:1, not cubic",again["failure_detail"]["detail"])
        self.assertEqual(again["plan"],plan)

    def test_small_cell_failure_still_reports_the_collision_radius_floor(self):
        job_id="3"*32
        self.app.jobs[job_id]={"id":job_id,"status":"error","plan":small_cell_plan(),
                               "request_text":"r","error":"network cells below collision resolution",
                               "cases":[]}
        detail=self.app.get(job_id)["failure_detail"]
        self.assertEqual(detail["code"],"network_collision_resolution")
        self.assertIn("0.98 mm radius",detail["detail"])
        self.assertIn("at least 1 mm",detail["detail"])

    def test_archived_failure_has_same_detail_and_preserves_saved_fields(self):
        job_id="a"*32;directory=self.base/"runs"/job_id;directory.mkdir(parents=True)
        plan=thin_plan();request="Archived original request";error="network cells below collision resolution"
        saved={"id":job_id,"status":"error","plan":plan,"request_text":request,
               "error":error,"message":"older display message","cases":[],"warnings":[],"timing":{}}
        (directory/"job.json").write_text(json.dumps(saved),encoding="utf-8")
        restored=self.app.get(job_id)
        self.assertTrue(restored["restored_from_disk"])
        self.assertEqual(restored["failure_detail"]["code"],"network_collision_resolution")
        self.assertIn("20.00:1, not cubic",restored["failure_detail"]["detail"])
        self.assertEqual((restored["plan"],restored["request_text"],restored["error"]),
                         (plan,request,error))
        restored["failure_detail"]["summary"]="changed"
        self.assertNotEqual(self.app.get(job_id)["failure_detail"]["summary"],"changed")

    def test_live_and_archived_generic_errors_use_error_before_message(self):
        live_id="2"*32
        self.app.jobs[live_id]={"id":live_id,"status":"error","plan":None,"request_text":"r",
                                "error":"specific stored error","message":"generic message","cases":[]}
        self.assertEqual(self.app.get(live_id)["failure_detail"]["summary"],"specific stored error")
        archive_id="b"*32;directory=self.base/"runs"/archive_id;directory.mkdir(parents=True)
        saved={"id":archive_id,"status":"error","plan":None,"request_text":"archived r",
               "error":"archived stored error","message":"generic message","cases":[]}
        (directory/"job.json").write_text(json.dumps(saved),encoding="utf-8")
        self.assertEqual(self.app.get(archive_id)["failure_detail"]["summary"],"archived stored error")


if __name__=="__main__":unittest.main()
