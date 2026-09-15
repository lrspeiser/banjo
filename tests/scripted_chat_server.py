"""The playground server with a scripted model in place of the paid one.

For the page journeys (tests/world_page_journey_tests.py): the room's chat runs
as it does for a person -- the page's own ask, the chat's MCP tools, the room
opened again after the change -- except that the model's answers are read, in
turn, from the JSON list in BANJO_SCRIPTED_CHAT, the last one again once the
list is spent. No key is read and nothing is sent anywhere: the model is the
script.

    BANJO_SCRIPTED_CHAT=answers.json python tests/scripted_chat_server.py --port N ...

It takes server.py's own arguments.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import server  # noqa: E402
import world_chat  # noqa: E402

ANSWERS = json.loads(Path(os.environ["BANJO_SCRIPTED_CHAT"]).read_text(encoding="utf-8"))
_asked: list[int] = []


def scripted(api_key, model, conversation):
    """The next answer in the script, as the model's API gives one."""
    answer = ANSWERS[min(len(_asked), len(ANSWERS) - 1)]
    _asked.append(len(conversation))
    return answer


world_chat._call = scripted
# Something to ask with, so the chat is not refused for want of a key. It goes
# nowhere, because the model is the script.
server.local_configuration = lambda: ("scripted", "a scripted model")

if __name__ == "__main__":
    server.main()
