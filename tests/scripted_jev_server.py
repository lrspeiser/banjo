"""A stand-in for Jev (docs/machine-world.md, "What the rover decides by
itself"): an HTTP server that speaks TypeSafe's systemone API and answers from
a script, so the playground can be run and its page journeys filmed without a
key and without sending anything anywhere.

    python tests/scripted_jev_server.py --port 8899 [--script answers.json]

Point the playground at it with JEV_API_URL=http://127.0.0.1:8899/v1/systemone
and any TYPESAFE_API_KEY. Without a script it answers as a sensible Jev might:
a question named `next` is answered back_off at 90%, `stuck` 0.1, `battery`
level 0; a question named `intent` is sorted by plain words, as
rover_talk.PLAIN sorts them. A script is a JSON list of answer objects given
in turn, the last one again once the list is spent; each is the `answers`
map of one reply.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
import rover_talk  # noqa: E402

asked: list[dict] = []


def sensible(state: dict, questions: dict) -> dict:
    answers: dict = {}
    for name, question in questions.items():
        kind = question.get("type")
        if name == "intent" and kind == "choice":
            said = str((state or {}).get("said", "")).lower()
            intent = next((i for i, pattern in rover_talk.PLAIN if re.search(pattern, said)), "other")
            answers[name] = {"type": "choice", "choice": intent, "confidence": 0.9,
                             "probabilities": {intent: 0.9}}
        elif kind == "choice":
            options = list((question.get("criteria") or {}).keys()) or ["go_on"]
            pick = "back_off" if "back_off" in options else options[0]
            answers[name] = {"type": "choice", "choice": pick, "confidence": 0.9, "probabilities": {pick: 0.9}}
        elif kind == "noul":
            answers[name] = {"type": "noul", "noul": 0.1}
        elif kind == "score":
            levels = list((question.get("criteria") or {}).keys()) or ["0"]
            answers[name] = {"type": "score", "score": 0.0, "legend": {str(i): l for i, l in enumerate(levels)},
                             "probabilities": {"0": 1.0}, "confidence": 0.9}
    return answers


class Handler(BaseHTTPRequestHandler):
    script: list[dict] = []

    def log_message(self, *args):   # quiet
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        asked.append(body)
        if self.script:
            answers = self.script[min(len(asked) - 1, len(self.script) - 1)]
        else:
            answers = sensible(body.get("state") or {}, body.get("questions") or {})
        reply = json.dumps({"model": "jev-scripted", "answers": answers,
                            "usage": {"input_tokens": len(json.dumps(body)) // 4, "output_tokens": 0}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)


def serve(port: int, script: list[dict] | None = None) -> ThreadingHTTPServer:
    Handler.script = script or []
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--script", type=Path)
    args = parser.parse_args()
    httpd = serve(args.port, json.loads(args.script.read_text(encoding="utf-8")) if args.script else None)
    print(f"scripted Jev at http://127.0.0.1:{httpd.server_port}/v1/systemone", flush=True)
    httpd.serve_forever()
