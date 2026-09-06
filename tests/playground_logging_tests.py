"""Evidence persistence, redaction and paid-review idempotence."""
import json
from unittest import mock
from playground_tests import PlaygroundTestCase, plan_for, PRIVATE_KEY, playground_server

class LoggingTests(PlaygroundTestCase):
    def completed(self):
        app=self.make_app(mock.Mock(return_value=(plan_for("panel_impact"),{})))
        job_id=app.submit({"message":"Compare impact", "request_id":"logging_test_01", "auto_open":False})["job_id"]
        self.assertEqual(app.get(job_id)["status"],"complete")
        return app,job_id

    def test_events_and_evidence_are_persistent_and_redacted(self):
        app,job_id=self.completed()
        app.log_event(job_id,"redaction_test",message=PRIVATE_KEY)
        raw=(app.runs_path/job_id/"events.jsonl").read_text()
        self.assertNotIn(PRIVATE_KEY,raw)
        events=[json.loads(line) for line in raw.splitlines()]
        self.assertTrue(all(e["schema"]=="banjo.experiment-event.v1" for e in events))
        self.assertEqual(events[0]["event"],"started")
        self.assertEqual(len(events[0]["engine_sha256"]),64)
        evidence=app.evidence(job_id,0)
        self.assertEqual(evidence["request"],"Compare impact")
        self.assertIn("native_facts",evidence["diagnostics"])
        self.assertNotIn(PRIVATE_KEY,json.dumps(evidence))

    def test_review_is_cached_and_saved_without_repeating_provider_call(self):
        app,job_id=self.completed()
        result={"review":{"verdict":"insufficient_evidence","summary":"No contact measurements","findings":[],"next_steps":[]},"review_metadata":{"model":"fake-model"}}
        with mock.patch.object(playground_server,"review_evidence",return_value=result) as provider:
            self.assertEqual(app.analyze(job_id,{"case_index":0}),result)
            self.assertEqual(app.analyze(job_id,{"case_index":0}),result)
            provider.assert_called_once()
        saved=json.loads((app.runs_path/job_id/"job.json").read_text())
        self.assertEqual(saved["cases"][0]["llm_review"],result)

    def test_review_failure_releases_lock_and_keeps_evidence(self):
        app,job_id=self.completed()
        with mock.patch.object(playground_server,"review_evidence",side_effect=ValueError("Provider unavailable")):
            with self.assertRaisesRegex(ValueError,"Provider unavailable"):
                app.analyze(job_id,{"case_index":0})
        self.assertFalse(app.reviewing)
        self.assertEqual(app.evidence(job_id,0)["events"][-1]["event"],"review_failed")
