import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib import error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
import experiment_review


PRIVATE_KEY = "private-test-key"


class FakeHTTPResponse:
    def __init__(self, value):
        self.data = json.dumps(value).encode("utf-8")
        self.requested_read_size = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size):
        self.requested_read_size = size
        return self.data


def response(text=None, **changes):
    review = {"verdict": "expected_behavior", "summary": "The measured result matches the declared check.",
              "findings": ["The run completed."], "next_steps": []}
    value = {"id": "response-secret-not-returned", "status": "completed",
             "output": [{"content": [{"type": "output_text", "text": text or json.dumps(review)}]}],
             "usage": {"input_tokens": 12, "output_tokens": 18}}
    value.update(changes)
    return FakeHTTPResponse(value)


class ExperimentReviewTests(unittest.TestCase):
    def test_request_is_bounded_structured_and_returns_safe_metadata(self):
        upstream = response()
        with mock.patch.object(experiment_review.request, "urlopen", return_value=upstream) as urlopen:
            result = experiment_review.review_evidence(PRIVATE_KEY, "fake-model", {"measured": {"speed": 1.0}})
        self.assertEqual(result["review"]["verdict"], "expected_behavior")
        self.assertEqual(result["review_metadata"]["model"], "fake-model")
        self.assertEqual(result["review_metadata"]["usage"]["input_tokens"], 12)
        self.assertGreaterEqual(result["review_metadata"]["review_wall_s"], 0)
        self.assertNotIn("response_id", result["review_metadata"])
        req = urlopen.call_args.args[0]
        payload = json.loads(req.data)
        self.assertEqual(req.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + PRIVATE_KEY)
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(payload["text"]["format"]["schema"], experiment_review.REVIEW_SCHEMA)
        self.assertFalse(payload["store"])
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 90)
        self.assertEqual(upstream.requested_read_size, 1024 * 1024 + 1)

    def test_rejects_oversized_and_nonfinite_evidence_before_network(self):
        urlopen = mock.Mock()
        with mock.patch.object(experiment_review.request, "urlopen", urlopen):
            with self.assertRaisesRegex(ValueError, "64 KiB"):
                experiment_review.review_evidence(PRIVATE_KEY, "fake-model", {"value": "x" * 65536})
            with self.assertRaisesRegex(ValueError, "finite JSON"):
                experiment_review.review_evidence(PRIVATE_KEY, "fake-model", {"value": float("nan")})
        urlopen.assert_not_called()

    def test_rejects_duplicate_or_invalid_structured_output(self):
        duplicate = '{"verdict":"expected_behavior","verdict":"unexpected_behavior","summary":"x","findings":[],"next_steps":[]}'
        invalid = json.dumps({"verdict": "expected_behavior", "summary": "x", "findings": [],
                              "next_steps": [], "raw_http_body": "forbidden"})
        for text, message in ((duplicate, "Duplicate JSON"), (invalid, "unknown or missing")):
            with self.subTest(message=message), mock.patch.object(
                    experiment_review.request, "urlopen", return_value=response(text)):
                with self.assertRaisesRegex(ValueError, message):
                    experiment_review.review_evidence(PRIVATE_KEY, "fake-model", {})

    def test_rejects_nonfinite_and_oversized_output_values(self):
        cases = [
            ('{"verdict":"expected_behavior","summary":NaN,"findings":[],"next_steps":[]}', "Nonfinite JSON"),
            (json.dumps({"verdict": "expected_behavior", "summary": "x" * 2001,
                         "findings": [], "next_steps": []}), "1..2000"),
            (json.dumps({"verdict": "expected_behavior", "summary": "x",
                         "findings": ["x"] * 9, "next_steps": []}), "at most 8"),
        ]
        for text, message in cases:
            with self.subTest(message=message), mock.patch.object(
                    experiment_review.request, "urlopen", return_value=response(text)):
                with self.assertRaisesRegex(ValueError, message):
                    experiment_review.review_evidence(PRIVATE_KEY, "fake-model", {})

    def test_http_error_does_not_expose_body_key_or_retry(self):
        exc = error.HTTPError("https://api.openai.com/v1/responses", 401, "bad", {}, None)
        with mock.patch.object(experiment_review.request, "urlopen", side_effect=exc) as urlopen:
            with self.assertRaises(ValueError) as raised:
                experiment_review.review_evidence(PRIVATE_KEY, "fake-model", {"secret_input": "private"})
        self.assertEqual(urlopen.call_count, 1)
        message = str(raised.exception)
        self.assertIn("HTTP 401", message)
        self.assertNotIn(PRIVATE_KEY, message)
        self.assertNotIn("secret_input", message)

    def test_connection_error_has_explicit_no_retry_message(self):
        with mock.patch.object(experiment_review.request, "urlopen", side_effect=error.URLError("offline")) as urlopen:
            with self.assertRaisesRegex(ValueError, "no automatic paid retry"):
                experiment_review.review_evidence(PRIVATE_KEY, "fake-model", {})
        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
