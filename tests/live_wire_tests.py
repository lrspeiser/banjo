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


def whatASpringHoldsComesWithTheStep() -> None:
    """What a spring holds comes with the step, and it is the engine's reading.

    The pins travel only when their SET changes. What an elastic holds changes
    with every step it is drawn through, and the room used to ask for the whole
    list four times a second to find out -- so the bow's meter trailed the draw
    by about 100 mm at the page's 0.4 m/s. Each reading that changed now comes
    on the step's reply. This draws the courtyard's bow the way the page does,
    keeps what the room would have from those readings alone -- folded in by
    id, as world.js does, while somebody else asks the same world for all of
    it now and then -- and holds that to the engine's own `joints` answer
    after every step.
    """
    wire = raw_replies()
    live = live_session.Live()

    class App:
        engine_path = ENGINE
        runs_path = (ROOT / "build" / "playground-runs").resolve()
        live_inprocess = False

    try:
        opened = live.open(App(), {"spec": world_room.courtyard()})
        require(not opened.get("joint_problems"),
                f"the bow would not build: {opened.get('joint_problems')}")
        session = live.session
        room = {j["id"]: dict(j) for j in opened["joints"]}

        def step() -> dict:
            state = session.send(op="step", dt=1 / 240.0, n=8, moved=True)
            reply = wire[-1]
            if reply.get("joints") is not None:
                room.clear()
                room.update({j["id"]: dict(j) for j in reply["joints"]})
            for reading in reply.get("elastics") or ():
                room[reading["id"]].update(reading)
            # Answered, as the room answers it, or the world waits at the step.
            for coming in state.get("breakable") or ():
                session.send(op="fracture", name=coming, wait=False)
            return reply

        def agrees(when: str) -> float:
            truth = {j["id"]: j for j in session.send(op="joints")["joints"]
                     if j["kind"] == "elastic"}
            require(len(truth) == 2, f"the courtyard's bow has {len(truth)} limbs, not two")
            folded = {e["id"]: e for e in session.state.get("elastics") or ()}
            for joint_id, limb in truth.items():
                for key in ("metres", "force_n", "stored_j"):
                    require(room[joint_id][key] == limb[key],
                            f"{when}: the room has limb {joint_id}'s {key} at "
                            f"{room[joint_id][key]}, the engine at {limb[key]}")
                    require(folded.get(joint_id, {}).get(key) == limb[key],
                            f"{when}: the session has limb {joint_id}'s {key} at "
                            f"{folded.get(joint_id, {}).get(key)}, the engine at {limb[key]}")
            return sum(limb["stored_j"] for limb in truth.values())

        # Standing, as a room has stood before anyone walks up to it.
        for _ in range(30):
            step()
        quiet = sum(1 for _ in range(30) if not step().get("elastics"))
        agrees("at brace")

        braced = next(b for b in session.state["bodies"] if b["name"] == "bowstring")["position_m"]
        session.send(op="grab", name="bowstring")
        # Drawn the way the page draws it: the engine's own stroke of the
        # bounded hand, back along the shot at 0.4 m/s.
        session.send(op="stroke", path=[braced, [braced[0] - 0.45, braced[1], braced[2]]],
                     speed_m_s=0.4, accel_m_s2=2.0, lead_m=0.05, let_go=False, give_up_s=30)
        carried, held = 0, 0.0
        for i in range(60):
            reply = step()
            carried += bool(reply.get("partial") and reply.get("elastics"))
            held = agrees(f"{8 * (i + 1)} steps into the draw")
            if i % 9 == 4:
                # Somebody else -- the chat -- asks the same world for all of it.
                session.send(op="poses")
        print(f"  {held:.1f} J in the limbs after 2 s of drawing; {carried} trimmed replies "
              f"carried the limbs' readings; {quiet} of 30 replies at brace said nothing")
        require(held > 30.0, f"the draw stored only {held:.1f} J, so the bow was barely drawn")
        require(carried > 20, "the readings came only on whole replies, so nothing shows "
                              "that they survive trimming")
        require(quiet > 20, "a bow standing at brace sent its limbs' readings with almost "
                            "every step")
    finally:
        live.shutdown()


def aPreviewOfAThrowIsTheThrow() -> None:
    """The aim arc is drawn from the preview, so the preview has to be the throw.

    The room asked for its preview without saying let_go, and the line read that
    the way it reads a stroke: one that keeps hold, whose hand slows to ARRIVE at
    the end. The arc was drawn from that. Measured in the bench room, a rubber
    ball the arc said would leave at 4.7 m/s left at 14.7 and came down metres
    past the ring. This winds the ball back as the page does, asks for the
    preview both ways a host can -- through the room's own path and straight
    down the line -- neither saying let_go, then throws it, and holds each
    preview's release and landing to the throw's, to the bounds the engine's own
    test holds a preview to (tests/hand_stroke_tests.cpp).
    """
    live = live_session.Live()

    class App:
        engine_path = ENGINE
        runs_path = (ROOT / "build" / "playground-runs").resolve()
        live_inprocess = False

    try:
        opened = live.open(App(), {"spec": world_room.room()})
        room = opened["session"]

        def act(op: str, **rest) -> dict:
            return live.act({"session": room, "op": op, **rest})

        def ball(state: dict) -> dict:
            return next(b for b in state["bodies"] if b["name"] == "rubber ball")

        centre = ball(opened)["position_m"]
        radius = 0.5 * ball(opened)["dimensions_m"][0]
        act("wield", name="rubber ball", grip=centre)
        # Stood a metre behind the ball, looking level along +z, as the page
        # stands: wound back 0.22 m behind the eye, 0.34 m right and 0.12 m up,
        # and let go 0.72 m ahead, 0.12 m right and 0.02 m down, the last 0.3 m
        # of the way along the line of sight (playground/interaction.js).
        eye = [centre[0], 1.62, centre[2] - 1.0]
        wound = [eye[0] - 0.34, eye[1] + 0.12, eye[2] - 0.22]
        on_line = [eye[0] - 0.12, eye[1] - 0.02, eye[2] + 0.42]
        release = [eye[0] - 0.12, eye[1] - 0.02, eye[2] + 0.72]
        state: dict = {}
        for _ in range(60):   # two seconds, eight steps a call, as the page steps
            state = act("step", dt=1 / 240.0, n=8, hand=wound)
        grip = state["hand"]["grip_m"]
        stroke = {"path": [grip, on_line, release], "speed_m_s": 20.0, "accel_m_s2": 2000.0,
                  "lead_m": 0.05, "give_up_s": 1.0}
        by_room = act("preview_stroke", horizon_s=4.0, **stroke)
        by_line = live.session.send(op="preview_stroke", horizon_s=4.0, **stroke)

        act("stroke", let_go=True, **stroke)
        let_go = None
        for _ in range(480):
            state = act("step", dt=1 / 240.0, n=1)
            let_go = (state.get("hand") or {}).get("let_go")
            if let_go and let_go.get("body") == "rubber ball":
                break
        require(bool(let_go) and let_go.get("body") == "rubber ball",
                "the throw never let go of the ball")
        speed = sum(c * c for c in let_go["velocity_m_s"]) ** 0.5
        let_go_at = ball(state)["position_m"]

        # Fly it for real, and carry its last free state on to the ground the
        # preview came down on, ballistically: the preview follows the centre
        # line, and the ball touches down its own radius before that.
        ground = by_room["flight"]["hit_point_m"][1] if by_room["flight"]["hit"] else 0.0
        p, v = ball(state)["position_m"], ball(state)["velocity_m_s"]
        for _ in range(2400):
            now = ball(act("step", dt=1 / 240.0, n=1))
            if now["position_m"][1] <= ground + radius + 0.003 or now["velocity_m_s"][1] > v[1] + 1.0:
                break
            p, v = now["position_m"], now["velocity_m_s"]
        g = 9.80665
        fall = (v[1] + (v[1] * v[1] + 2.0 * g * (p[1] - ground)) ** 0.5) / g
        landed = (p[0] + v[0] * fall, p[2] + v[2] * fall)
        reach = ((landed[0] - let_go_at[0]) ** 2 + (landed[1] - let_go_at[2]) ** 2) ** 0.5

        for how, seen in (("through the room", by_room), ("down the line", by_line)):
            previewed = sum(c * c for c in seen["let_go_velocity_m_s"]) ** 0.5
            hit = seen["flight"]["hit_point_m"] if seen["flight"]["hit"] else None
            off = (((landed[0] - hit[0]) ** 2 + (landed[1] - hit[2]) ** 2) ** 0.5
                   if hit else float("inf"))
            print(f"  previewed {how}: leaves at {previewed:.2f} m/s and comes down "
                  f"{off:.3f} m from where the ball did; the throw left at {speed:.2f} m/s "
                  f"and flew {reach:.2f} m")
            require(seen["possible"] and seen["reaches_end"],
                    f"the preview {how} said the throw could not be made: {seen.get('why')}")
            require(abs(previewed - speed) <= 0.03 * speed + 0.05,
                    f"the preview {how} has the ball leaving at {previewed:.2f} m/s; it left at "
                    f"{speed:.2f}")
            require(off <= 0.02 + 0.04 * reach,
                    f"the preview {how} came down {off:.2f} m from where the ball did, over "
                    f"{reach:.2f} m")
        require(by_room["let_go_velocity_m_s"] == by_line["let_go_velocity_m_s"],
                "the room and the line were told different throws from the same world")
    finally:
        live.shutdown()


def main() -> int:
    if not ENGINE.exists():
        print(f"no engine at {ENGINE} -- build banjo_live_world_run first")
        return 2
    for name, test in [
        ("the trimmed world is the whole world", theTrimmedWorldIsTheWholeWorld),
        ("a full reply to somebody else does not strand the room",
         aFullReplyToSomebodyElseDoesNotStrandTheRoom),
        ("the session still answers with everything", theSessionStillAnswersWithEverything),
        ("what a spring holds comes with the step", whatASpringHoldsComesWithTheStep),
        ("a preview of a throw is the throw", aPreviewOfAThrowIsTheThrow),
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
