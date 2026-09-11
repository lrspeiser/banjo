"""The wire carries what moved, and that is the same world.

A room that has shattered holds two hundred and fifty bodies and four of them
are moving. Sending the other two hundred and forty-six thirty times a second
was six megabytes a second for the host to fetch, parse and walk, to be told
that nothing happened -- and it showed up as the room stuttering, which reads
exactly like the physics being slow.

So a step can ask for only what changed. That is only worth having if the world
you rebuild from the pieces is the world the engine has, so that is what these
check: not that the replies are smaller, but that they say the same thing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab  # noqa: E402
import live_session  # noqa: E402
import world_room  # noqa: E402

ENGINE = ROOT / "build" / "integration" / "Release" / "banjo_live_world_run.exe"
if not ENGINE.exists():
    ENGINE = ROOT / "build" / "integration" / "banjo_live_world_run"

FAILURES: list[str] = []


def require(ok: bool, why: str) -> None:
    if not ok:
        raise AssertionError(why)


def bodies_by_name(state: dict) -> dict[str, dict]:
    return {body["name"]: body for body in state["bodies"]}


def merge(have: dict[str, dict], reply: dict) -> dict[str, dict]:
    """What a host does with a partial reply: drop what went, take what came."""
    if not reply.get("partial"):
        return bodies_by_name(reply)
    out = dict(have)
    for name in reply.get("gone") or ():
        out.pop(name, None)
    for body in reply["bodies"]:
        out[body["name"]] = body
    return out


def open_room() -> live_session.Session:
    return live_session.Session(ENGINE, fracture_lab.validate(world_room.room()),
                                (ROOT / "playground" / "runs").resolve())


_READ = live_session.Session._read


def raw_replies() -> list[dict]:
    """Every line the engine actually wrote, before anything merges it."""
    seen: list[dict] = []
    original = _READ

    def spy(self, what: str) -> dict:
        reply = original(self, what)
        seen.append(reply)
        return reply

    live_session.Session._read = spy
    return seen


def theTrimmedWorldIsTheWholeWorld() -> None:
    """Rebuild from the pieces, then ask for everything, and compare."""
    wire = raw_replies()
    live = open_room()
    try:
        live.send(op="grab", name="iron ball")
        live.send(op="move", to=[-2.8, 4.4, -1.2])
        live.send(op="step", dt=1 / 240.0, n=1)
        live.send(op="release")
        wire.clear()

        have: dict[str, dict] = {}
        trimmed = 0
        for _ in range(200):
            state = live.send(op="step", dt=1 / 120.0, n=4, moved=True)
            reply = wire[-1]
            if reply.get("partial"):
                trimmed += 1
            have = merge(have, reply)
            if state.get("breakable") and not state.get("working_on"):
                live.send(op="fracture", name=state["breakable"][0], wait=False)
                # A fracture reply carries geometry and so goes out whole; the
                # host replaces what it has, exactly as the room does.
                have = bodies_by_name(wire[-1])
        # A fracture runs on a worker and this loop sends far faster than real
        # time, so it can finish before the answer does. Keep stepping until the
        # world has nothing outstanding -- otherwise the test measures its own
        # impatience rather than the wire.
        while live.state.get("working_on"):
            live.send(op="step", dt=1 / 120.0, n=4, moved=True)
            have = merge(have, wire[-1])

        whole = bodies_by_name(live.send(op="poses"))
        rebuilt = have

        print(f"  {len(whole)} bodies, rebuilt from {trimmed} trimmed replies")
        require(trimmed > 100, "nothing was trimmed, so this proves nothing")
        require(len(whole) > 60, "nothing broke, so there was nothing to keep track of")
        missing = set(whole) - set(rebuilt)
        extra = set(rebuilt) - set(whole)
        require(not missing, f"the host would be missing {len(missing)}: {sorted(missing)[:4]}")
        require(not extra, f"the host would still be drawing {len(extra)} that are gone: "
                           f"{sorted(extra)[:4]}")
        for name, body in whole.items():
            require(rebuilt[name]["position_m"] == body["position_m"],
                    f"{name} is in the wrong place: the host has "
                    f"{rebuilt[name]['position_m']}, the world has {body['position_m']}")
    finally:
        live.close()


def aFullReplyToSomebodyElseDoesNotStrandTheRoom() -> None:
    """One process, two askers.

    The chat window asks the same live world questions while the room is drawing
    it. Those answers go out whole. If the engine counted them as "already
    sent", the room would never hear about the bodies that moved during them and
    would leave them standing in the air.
    """
    wire = raw_replies()
    live = open_room()
    try:
        live.send(op="grab", name="iron ball")
        live.send(op="move", to=[-2.8, 4.4, -1.2])
        live.send(op="release")
        have = bodies_by_name(live.send(op="step", dt=1 / 120.0, n=4, moved=True))

        resyncs = 0
        for i in range(60):
            live.send(op="step", dt=1 / 120.0, n=4, moved=True)
            have = merge(have, wire[-1])
            if i % 7 == 3:
                # Somebody else asks the same world a question.
                live.send(op="poses")
            elif i % 7 == 4 and not wire[-1].get("partial"):
                resyncs += 1

        whole = bodies_by_name(live.send(op="poses"))
        print(f"  {resyncs} replies came back whole after somebody else asked")
        require(resyncs > 0,
                "a full reply to another asker did not reset the trimming, so the "
                "room can be told a body is unchanged on the strength of a reply "
                "it never saw")
        for name, body in whole.items():
            require(name in have, f"the room lost {name} entirely")
            require(have[name]["position_m"] == body["position_m"],
                    f"the room has {name} at {have[name]['position_m']}, the world "
                    f"has it at {body['position_m']}")
    finally:
        live.close()


def theSessionStillAnswersWithEverything() -> None:
    """Trimming is for the wire, not for the callers on this side.

    The tools, the tests and anything else asking a Session what the world looks
    like get all of it, whichever way the reply arrived.
    """
    live = open_room()
    try:
        live.send(op="grab", name="iron ball")
        live.send(op="move", to=[-2.8, 4.4, -1.2])
        live.send(op="release")
        live.send(op="step", dt=1 / 120.0, n=4, moved=True)
        for _ in range(40):
            wire = live.send(op="step", dt=1 / 120.0, n=4, moved=True)
        held = live.state
        print(f"  the wire carried {len(wire['bodies'])} bodies, the session reports "
              f"{len(held['bodies'])}")
        require(len(wire["bodies"]) < len(held["bodies"]),
                "the wire carried as much as the session holds, so nothing was "
                "trimmed and this proves nothing")
        require(held["partial"] is False,
                "the session handed a partial world to a caller that wants all of it")
        whole = live.send(op="poses")
        require(len(whole["bodies"]) == len(held["bodies"]),
                "the session and the world hold different numbers of bodies")
        places = {b["name"]: b["position_m"] for b in whole["bodies"]}
        for body in held["bodies"]:
            require(places[body["name"]] == body["position_m"],
                    f"the session has {body['name']} in the wrong place")
    finally:
        live.close()


def main() -> int:
    if not ENGINE.exists():
        print(f"no engine at {ENGINE} -- build banjo_live_world_run first")
        return 2
    for name, test in [
        ("the trimmed world is the whole world", theTrimmedWorldIsTheWholeWorld),
        ("a full reply to somebody else does not strand the room",
         aFullReplyToSomebodyElseDoesNotStrandTheRoom),
        ("the session still answers with everything", theSessionStillAnswersWithEverything),
    ]:
        try:
            test()
            print(f"[PASS] {name}")
        except Exception as failure:  # noqa: BLE001 - a failing test is the output
            FAILURES.append(f"{name}: {failure}")
            print(f"[FAIL] {name}: {failure}")
    if FAILURES:
        print(f"\n{len(FAILURES)} failed")
        return 1
    print("\nall wire tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
