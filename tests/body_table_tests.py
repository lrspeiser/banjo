"""The body table survives being rearranged underneath things that index it.

Three things hold indices into the world's body table: the hand, the fracture
being worked out, and anything queued behind it. Applying a fracture erases the
island it broke and appends what it became, so every one of those has to be
followed across the rearrangement.

Following them by counting how many slots below an index were erased is wrong,
and wrong in a way that looks right: a body that comes through a fracture WHOLE
keeps its name and is erased and re-appended at the end. It has not gone, so
nothing counts it as gone, and yet every index above its old slot has moved down
by one. Queued jobs then hold indices one too high, and the next apply destroys
the body next door.

What that looked like from inside the room: an iron ball dropped on a plate
quietly deleted two anchored piers -- one of them on the far side of the room --
and left the ball sitting there beside a full set of its own pieces, so there
appeared to be two balls, one of them made of cubes.

These check the two things that are visible from outside: scenery does not
vanish, and nothing is ever present at the same time as its own pieces.
"""

from __future__ import annotations

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


def drop_on(plate: str, horizon: float = 2.5) -> tuple[set[str], set[str], int]:
    """Drop the iron ball on a plate. Returns (anchored at the start, names at
    the end, how many bodies)."""
    live = live_session.Session(ENGINE, fracture_lab.validate(world_room.room()),
                                (ROOT / "playground" / "runs").resolve())
    try:
        # Foresight on, because it is what makes several breaks be in flight at
        # once, which is what put indices under the queue in the first place.
        live.send(op="foresee", horizon_s=horizon)
        anchored = {b["name"] for b in live.state["bodies"] if b["anchored"]}
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
        names = {b["name"] for b in live.state["bodies"]}
        return anchored, names, len(names)
    finally:
        live.close()


PLATES = ["iron plate 20mm", "glass plate 20mm", "concrete plate 20mm", "ice plate 20mm"]


def sceneryDoesNotVanish() -> None:
    """Anchored scenery is the world. Nothing should be able to delete it."""
    worst = 0
    for plate in PLATES:
        anchored, names, count = drop_on(plate)
        require(anchored, "the scene has no anchored scenery, so this proves nothing")
        lost = anchored - names
        worst = max(worst, len(lost))
        require(not lost,
                f"dropping the ball on {plate!r} deleted {len(lost)} pieces of "
                f"anchored scenery: {sorted(lost)[:3]}")
    print(f"  four drops, {len(PLATES)} plates: no anchored body lost (worst {worst})")


def nothingIsPresentBesideItsOwnPieces() -> None:
    """A body and its pieces are the same matter. Both at once is one of them
    conjured out of nothing -- and it looked, from the room, like a second ball
    made of cubes sitting next to the first."""
    for plate in PLATES:
        _, names, count = drop_on(plate)
        both = sorted(n for n in names if f"{n} piece 1" in names)
        require(not both,
                f"after dropping on {plate!r}, {both[:2]} are in the world at the "
                f"same time as their own pieces")
    print(f"  and nothing was left standing beside its own pieces")


def aBrokenSceneIsStillCountable() -> None:
    """Whatever breaks, the world's own count and the list it hands out agree.

    A table whose indices have been corrupted tends to disagree with itself, and
    that is cheap to check on every reply.
    """
    live = live_session.Session(ENGINE, fracture_lab.validate(world_room.room()),
                                (ROOT / "playground" / "runs").resolve())
    try:
        at = next(b["position_m"] for b in live.state["bodies"]
                  if b["name"] == "glass plate 20mm")
        live.send(op="grab", name="iron ball")
        live.send(op="move", to=[at[0], at[1] + 4.0, at[2]])
        live.send(op="step", dt=1 / 240.0, n=1)
        live.send(op="release")
        checked = 0
        for _ in range(400):
            state = live.send(op="step", dt=1 / 120.0, n=4, moved=True)
            if state.get("breakable") and not state.get("working_on"):
                live.send(op="fracture", name=state["breakable"][0], wait=False)
            whole = live.state
            names = [b["name"] for b in whole["bodies"]]
            require(len(names) == len(set(names)),
                    f"the world is holding the same name twice: "
                    f"{[n for n in names if names.count(n) > 1][:2]}")
            if isinstance(whole.get("count"), int):
                require(whole["count"] == len(names),
                        f"the world says it holds {whole['count']} bodies and hands "
                        f"out {len(names)}")
                checked += 1
        print(f"  {checked} replies where the count and the list agreed, and no name twice")
        require(checked > 100, "hardly any replies were checked, so this proves little")
    finally:
        live.close()


def main() -> int:
    if not ENGINE.exists():
        print(f"no engine at {ENGINE} -- build banjo_live_world_run first")
        return 2
    for name, test in [
        ("scenery does not vanish", sceneryDoesNotVanish),
        ("nothing is present beside its own pieces", nothingIsPresentBesideItsOwnPieces),
        ("a broken scene is still countable", aBrokenSceneIsStillCountable),
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
    print("\nall body table tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
