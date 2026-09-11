"""Walking over the pieces picks them up.

A room that shatters fills with debris. It will lie there for as long as the
world is open, and past a couple of thousand bodies the engine cannot take a
step back -- which is the whole basis of breaking. So sweeping the floor is not
only where raw materials come from, it is how the room stays able to break
things at all.

What these pin down is mostly what must NOT be swept up: the rules are narrow on
purpose, because a sweep that took the wrong thing would quietly eat the scene.
"""

from __future__ import annotations

import math
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


def open_room() -> live_session.Session:
    return live_session.Session(ENGINE, fracture_lab.validate(world_room.room()),
                                (ROOT / "playground" / "runs").resolve())


def shatter(live: live_session.Session, plate: str = "glass plate 20mm") -> list[float]:
    """Drop the iron ball on a pane and wait for the pieces."""
    at = next(b["position_m"] for b in live.state["bodies"] if b["name"] == plate)
    live.send(op="grab", name="iron ball")
    live.send(op="move", to=[at[0], at[1] + 4.0, at[2]])
    live.send(op="step", dt=1 / 240.0, n=1)
    live.send(op="release")
    for _ in range(600):
        state = live.send(op="step", dt=1 / 120.0, n=4, moved=True)
        if state.get("breakable") and not state.get("working_on"):
            live.send(op="fracture", name=state["breakable"][0], wait=False)
    while live.state.get("working_on"):
        live.send(op="step", dt=1 / 120.0, n=4, moved=True)
    return at


def hulls(live: live_session.Session) -> list[dict]:
    return [b for b in live.send(op="poses")["bodies"] if b["shape"] == "hull"]


def theFloorCanBeSweptUp() -> None:
    live = open_room()
    try:
        at = shatter(live)
        pieces = hulls(live)
        before = len(live.state["bodies"])
        require(len(pieces) > 10, "nothing shattered, so there is nothing to sweep")

        got = live.send(op="collect", at=at, radius_m=1.2)["collected"]
        after = len(live.state["bodies"])
        print(f"  {len(pieces)} pieces on the floor -> "
              + ", ".join(f"{lot['kg'] * 1000:.0f} g of {lot['material']}" for lot in got))

        require(got, "standing on the debris collected nothing")
        require(all(lot["kg"] > 0.0 for lot in got),
                "something was collected but it weighed nothing")
        require(after < before, f"the bodies did not go: {before} before, {after} after")
        # What it weighs has to be the matter that was there, not a count.
        cells = sum(lot["cells"] for lot in got)
        cell_m = live.state["cell_size_m"]
        glass = next(lot for lot in got if lot["material"] == "glass")
        expected = glass["cells"] * cell_m ** 3 * 2500.0
        require(abs(glass["kg"] - expected) / expected < 0.25,
                f"{glass['kg']:.3f} kg of glass from {glass['cells']} cells is not "
                f"near the {expected:.3f} kg that much glass weighs")
        require(len(got[0].get("took") or []) > 0,
                "the sweep did not say which bodies it took, so a host cannot "
                "show them going")
    finally:
        live.close()


def itOnlyReachesSoFar() -> None:
    live = open_room()
    try:
        at = shatter(live)
        away = [at[0] + 3.0, at[1], at[2]]
        got = live.send(op="collect", at=away, radius_m=1.2)["collected"]
        print(f"  standing 3 m away collected {got or 'nothing'}")
        require(not got, f"a sweep 3 m away still collected {got}")
        near = live.send(op="collect", at=at, radius_m=1.2)["collected"]
        require(near, "and standing on it collected nothing either, so the test "
                      "proves nothing about reach")
    finally:
        live.close()


def itTakesOnlyThePieces() -> None:
    """The scene must survive being walked through.

    Only a hull -- what something becomes when it breaks or bends -- is debris.
    Authored objects, anchored scenery and whatever is in a hand stay put, or
    walking across the room would quietly eat it.
    """
    live = open_room()
    try:
        whole = {b["name"] for b in live.state["bodies"]}
        anchored = {b["name"] for b in live.state["bodies"] if b["anchored"]}
        at = shatter(live)
        require(anchored, "the scene has no anchored scenery to protect")

        # Sweep the whole room, from every plate, with a generous reach.
        for body in list(live.state["bodies"]):
            live.send(op="collect", at=body["position_m"], radius_m=2.0)
        left = {b["name"] for b in live.state["bodies"]}

        gone_scenery = anchored - left
        require(not gone_scenery,
                f"sweeping took {len(gone_scenery)} pieces of anchored scenery: "
                f"{sorted(gone_scenery)[:4]}")
        # Everything authored that did not break is still here.
        authored_left = {n for n in whole if n in left}
        broke = {"glass plate 20mm"}
        missing = whole - left - broke
        require(not missing,
                f"sweeping took authored objects that never broke: {sorted(missing)[:4]}")
        print(f"  swept the whole room: {len(authored_left)} authored bodies untouched, "
              f"{len(anchored)} anchored")
    finally:
        live.close()


def somethingInAHandIsNotDebris() -> None:
    live = open_room()
    try:
        at = shatter(live)
        pieces = [b["name"] for b in hulls(live)]
        require(pieces, "nothing shattered")
        held = pieces[0]
        live.send(op="grab", name=held)
        # Carry it right through the debris and sweep from there.
        live.send(op="move", to=at)
        live.send(op="step", dt=1 / 240.0, n=1)
        live.send(op="collect", at=at, radius_m=2.0)
        still = {b["name"] for b in live.state["bodies"]}
        print(f"  swept while holding '{held[:34]}': still in hand = {held in still}")
        require(held in still,
                "the sweep took the piece out of the hand that was holding it")
        require(live.state.get("held") == held,
                f"the world says it is holding {live.state.get('held')!r}, not {held!r}")
    finally:
        live.close()


def aSweptRoomCanStillBreakThings() -> None:
    """The point of sweeping, as far as the engine is concerned.

    Debris is what fills the body table, and a full body table is what stops
    the step being taken back, which is what breaking needs.
    """
    live = open_room()
    try:
        # A different pane each time -- the first one is not there to break twice.
        for plate in ("glass plate 20mm", "glass plate 40mm", "ice plate 20mm"):
            at = shatter(live, plate)
            live.send(op="collect", at=at, radius_m=3.0)
        left = len(live.state["bodies"])
        print(f"  three panes broken and swept: {left} bodies left in the room")
        require(left < 120,
                f"{left} bodies after sweeping three shattered panes -- sweeping is "
                f"not keeping the room small")
    finally:
        live.close()


def main() -> int:
    if not ENGINE.exists():
        print(f"no engine at {ENGINE} -- build banjo_live_world_run first")
        return 2
    for name, test in [
        ("the floor can be swept up", theFloorCanBeSweptUp),
        ("it only reaches so far", itOnlyReachesSoFar),
        ("it takes only the pieces", itTakesOnlyThePieces),
        ("something in a hand is not debris", somethingInAHandIsNotDebris),
        ("a swept room can still break things", aSweptRoomCanStillBreakThings),
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
    print("\nall collect tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
