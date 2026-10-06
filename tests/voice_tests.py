"""Voice continuity, dedupe, and Realtime client-secret contract."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "playground"), str(ROOT / "tests"), str(ROOT)]

import game_guidance
import voice_api


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return self.payload


class VoiceContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = SimpleNamespace(
            world_id="world-a",
            workshop_store=Path(self.temp.name),
            api_key="server-secret-key",
            model="fixture",
        )

    def test_memory_is_private_bounded_and_survives_a_new_app_object(self):
        for n in range(voice_api.MAX_TURNS // 2 + 4):
            voice_api._remember_exchange(
                self.app, "alice", f"question {n}", f"answer {n}",
                focus="mill", screen="world",
            )
        remembered = voice_api.memory(self.app, "alice")
        self.assertEqual(voice_api.MAX_TURNS, len(remembered["turns"]))
        self.assertEqual([], voice_api.memory(self.app, "bob")["turns"])

        restarted = SimpleNamespace(
            world_id="world-a",
            workshop_store=Path(self.temp.name),
            api_key="server-secret-key",
            model="fixture",
        )
        self.assertEqual(remembered, voice_api.memory(restarted, "alice"))

        other_world = SimpleNamespace(
            world_id="world-b",
            workshop_store=Path(self.temp.name),
            api_key="server-secret-key",
            model="fixture",
        )
        self.assertEqual([], voice_api.memory(other_world, "alice")["turns"])
        self.assertEqual(
            {"schema": voice_api.SCHEMA, "remembered": voice_api.MAX_TURNS},
            voice_api.memory_request(restarted, "alice", {"action": "status"}),
        )
        cleared = voice_api.memory_request(restarted, "alice", {"action": "clear"})
        self.assertEqual(0, cleared["remembered"])
        self.assertEqual([], voice_api.memory(restarted, "alice")["turns"])

    def test_repeated_words_still_refresh_state_and_receive_recent_history(self):
        snapshots = []
        answers = []

        def snapshot(app, owner, journal, registry, focus):
            snapshots.append((owner, focus))
            return {"observed_native_t_s": len(snapshots)}

        def answer(app, body, context):
            answers.append(body)
            return {
                "reply": f"Answer {context['observed_native_t_s']} about {body.get('focus') or 'nothing'}.",
                "mode": "fixture",
                "observed_native_t_s": context["observed_native_t_s"],
            }

        with mock.patch.object(game_guidance, "snapshot", side_effect=snapshot), \
             mock.patch.object(game_guidance, "answer", side_effect=answer):
            first = voice_api.ask(
                self.app, "alice",
                {"message": "What is this?", "focus": "copper mill"},
                object(), object(),
            )
            repeated_words = voice_api.ask(
                self.app, "alice",
                {"message": "What is this?", "focus": "copper mill"},
                object(), object(),
            )
            changed_focus = voice_api.ask(
                self.app, "alice",
                {"message": "What is this?", "focus": "oak stool"},
                object(), object(),
            )

        self.assertEqual("Answer 1 about copper mill.", first["reply"])
        self.assertEqual("Answer 2 about copper mill.", repeated_words["reply"])
        self.assertEqual("Answer 3 about oak stool.", changed_focus["reply"])
        self.assertEqual(
            [
                ("alice", "copper mill"),
                ("alice", "copper mill"),
                ("alice", "oak stool"),
            ],
            snapshots,
        )
        self.assertEqual(3, len(answers))
        # The second question sees the prior explanation, but does not use it
        # instead of taking a new authenticated snapshot.
        self.assertEqual(
            ["user", "assistant"],
            [row["role"] for row in answers[1]["history"][-2:]],
        )
        self.assertIn("Answer 1", answers[1]["history"][-1]["content"])

    def test_session_config_is_manual_push_to_talk_and_secret_stays_server_side(self):
        captured = {}

        def opener(req, timeout):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            captured["body"] = json.loads(req.data)
            return FakeResponse({"value": "ephemeral-only", "expires_at": 123456})

        with mock.patch.dict(
            os.environ,
            {"BANJO_VOICE_MODEL": "", "BANJO_VOICE_NAME": ""},
            clear=False,
        ):
            result = voice_api.client_secret(self.app, "alice", opener=opener)

        session = captured["body"]["session"]
        self.assertEqual({'anchor':'created_at','seconds':60},captured['body']['expires_after'])
        self.assertEqual("gpt-realtime-2.1-mini", session["model"])
        self.assertEqual(["audio"], session["output_modalities"])
        self.assertEqual("marin", session["audio"]["output"]["voice"])
        self.assertEqual(
            "gpt-live-transcribe",
            session["audio"]["input"]["transcription"]["model"],
        )
        self.assertIsNone(session["audio"]["input"]["turn_detection"])
        self.assertEqual(
            "https://api.openai.com/v1/realtime/client_secrets",
            captured["url"],
        )
        self.assertEqual(
            "Bearer server-secret-key",
            captured["headers"]["authorization"],
        )
        safety = captured["headers"]["openai-safety-identifier"]
        self.assertTrue(safety.startswith("banjo-"))
        self.assertNotIn("alice", safety)
        self.assertNotIn("world-a", safety)

        self.assertEqual("ephemeral-only", result["value"])
        self.assertNotIn("server-secret-key", json.dumps(result))
        self.assertNotIn("server-secret-key", json.dumps(captured["body"]))

    def test_voice_request_rejects_forged_state_and_memory_status_hides_transcript(self):
        for bad in (
            {"message": "Hi", "wallet_j": 999},
            {"message": "Hi", "focus": 1},
            {"message": "Hi", "screen": "admin"},
            {"message": ""},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                voice_api.validate_ask(bad)
        voice_api._remember_exchange(
            self.app, "alice", "private question", "private answer",
            screen="world",
        )
        status = voice_api.memory_request(self.app, "alice", {"action": "status"})
        self.assertNotIn("private", json.dumps(status))


if __name__ == "__main__":
    unittest.main()
