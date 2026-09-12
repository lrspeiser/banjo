"""A threshold is the speed below which nothing CAN happen.

That is the rule the whole admission test rests on, and it is stated everywhere
as a hard floor: clearing it means a break is *possible*, never that one will
occur, but failing it means nothing occurs at all.

There was one way round it. A lattice run has to contain whatever struck the
thing being broken -- a body entered alone is a free-flying object with no
stress in it and cannot break however hard it was hit -- so the striker is in a
run that is not about it, and its own bonds can fail there. Measured: an iron
ball hit a 20 mm glass plate at 11.5 m/s against its own breaking threshold of
25.03 m/s, with every contact reporting `would_break` false, and came out of the
plate's run as twenty-nine pieces.

Holding a body in an island must not be the same as condemning it.
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


def drop(striker: str, plate: str, fall: float = 6.0) -> dict:
    """Drop one thing on another and report what the world said and did."""
    live = live_session.Session(ENGINE, fracture_lab.validate(world_room.room()),
                                (ROOT / "playground" / "runs").resolve())
    try:
        here = {b["name"] for b in live.state["bodies"]}
        if striker not in here or plate not in here:
            return {}
        at = next(b["position_m"] for b in live.state["bodies"] if b["name"] == plate)
        live.send(op="grab", name=striker)
        live.send(op="move", to=[at[0], at[1] + fall, at[2]])
        live.send(op="step", dt=1 / 240.0, n=1)
        live.send(op="release")

        admitted: set[str] = set()      # anything a contact ever said could break
        hardest: dict[str, tuple[float, float]] = {}
        spared = 0
        for _ in range(500):
            state = live.send(op="step", dt=1 / 120.0, n=4, moved=True)
            for hit in state.get("impacts") or ():
                struck = hit["struck"]
                if hit.get("would_break") or hit.get("would_dent"):
                    admitted.add(struck)
                best = hardest.get(struck)
                # A threshold of null is infinity -- a single loose cell has no
                # bonds left to fail, so nothing can ever happen to it. That is
                # the strongest possible case for this rule, not a missing value.
                bar = hit["threshold_speed_m_s"]
                bar = float("inf") if bar is None else bar
                if best is None or hit["closing_speed_m_s"] > best[0]:
                    hardest[struck] = (hit["closing_speed_m_s"], bar)
            for wait in state.get("waits") or ():
                if wait["kind"] == "spared":
                    spared += int(wait["lead_ms"])
            if state.get("breakable") and not state.get("working_on"):
                answer = live.send(op="fracture", name=state["breakable"][0], wait=False)
                for wait in answer.get("waits") or ():
                    if wait["kind"] == "spared":
                        spared += int(wait["lead_ms"])
        while live.state.get("working_on"):
            live.send(op="step", dt=1 / 120.0, n=4, moved=True)
        names = {b["name"] for b in live.state["bodies"]}
        return {"names": names, "admitted": admitted, "hardest": hardest,
                "spared": spared, "striker": striker, "plate": plate}
    finally:
        live.close()


PAIRS = [("iron ball", "concrete plate 20mm"), ("iron ball", "glass plate 20mm"),
         ("iron marble", "concrete plate 20mm"), ("aluminium ball", "glass plate 20mm"),
         ("aluminium ball", "concrete plate 20mm"), ("glass marble", "ceramic plate 20mm")]


def nothingBreaksThatWasNeverAdmitted() -> None:
    """The invariant, over a spread of strikers and targets.

    This one guards; it does not demonstrate. With the protection removed it
    still passes in these scenes, because the bonds that wrongly fail are not
    enough to split the body -- they leave it carrying damage it should not
    have, which shows up as weakness at the NEXT hit rather than as pieces now.
    What proves the rule is running is the last test in this file.
    """
    checked = 0
    for striker, plate in PAIRS:
        run = drop(striker, plate)
        if not run:
            continue
        checked += 1
        # Everything the world reported a contact on, that it never admitted.
        #
        # Authored bodies only. A piece made part-way through a cascade can be
        # admitted in a step this loop never sees -- the engine captures a break
        # that arrives while another is running without the host being asked, so
        # "the host never saw it admitted" is not the same as "it was never
        # admitted" for anything born mid-cascade. Judging pieces on that made
        # this test fail about one run in three for a reason that was about the
        # test and not the rule. The striker is an authored body, and the
        # striker is the case this is about.
        for struck, (speed, bar) in run["hardest"].items():
            if struck in run["admitted"] or " piece " in struck:
                continue
            broke = any(n.startswith(struck + " piece") for n in run["names"])
            require(not broke,
                    f"dropping {striker!r} on {plate!r}: {struck!r} came apart, and "
                    f"the hardest thing that ever hit it was {speed:.2f} m/s against "
                    f"its own threshold of {bar:.2f} m/s -- below the speed at which "
                    f"anything can happen to it")
    print(f"  {checked} drops: nothing came apart that was never admitted")
    require(checked >= 4, "too few pairs ran to mean anything")


def theStrikerSurvivesBreakingSomethingElse() -> None:
    """The case that started this: iron onto glass.

    Iron needs 25 m/s against glass and arrives at about 11. The plate must
    shatter and the ball must not. (The twenty-nine pieces that prompted all
    this turned out to be a body-table index fault rather than this rule --
    see tests/body_table_tests.py -- so this guards the visible symptom while
    the rule itself is checked below.)
    """
    run = drop("iron ball", "glass plate 20mm")
    require(run, "the scene has no iron ball or no 20 mm glass plate")
    pieces = sum(1 for n in run["names"] if n.startswith("glass plate 20mm piece"))
    speed, bar = run["hardest"].get("iron ball", (0.0, 0.0))
    print(f"  iron ball onto 20 mm glass: the plate broke into {pieces}, the ball took "
          f"{speed:.2f} m/s against its own {bar:.2f} m/s bar")
    require(pieces > 1, "the plate did not break, so the run this is about never happened")
    require("iron ball" in run["names"],
            "the ball is gone: it was destroyed inside the plate's run without ever "
            "clearing its own threshold")
    require(not any(n.startswith("iron ball piece") for n in run["names"]),
            "the ball came apart inside the plate's run")


def theRuleIsActuallyBeingEnforced() -> None:
    """Not a coincidence.

    If no bond is ever put back, this file proves only that bystanders happen
    not to break in these scenes -- which is a much weaker statement, and would
    stop being true the moment they did.

    This is the test that fails when the protection is removed: measured, six
    bonds across these drops fail inside a body that never cleared its own bar.
    """
    total = 0
    for striker, plate in PAIRS:
        run = drop(striker, plate)
        if run:
            total += run["spared"]
    print(f"  {total} bonds were put back that a run had broken in a body which "
          f"never cleared its own threshold")
    require(total > 0,
            "no bond was ever put back, so nothing here exercises the rule -- either "
            "bystanders no longer break at all, in which case say so, or the "
            "protection is not running")


def main() -> int:
    if not ENGINE.exists():
        print(f"no engine at {ENGINE} -- build banjo_live_world_run first")
        return 2
    for name, test in [
        ("nothing breaks that was never admitted", nothingBreaksThatWasNeverAdmitted),
        ("the striker survives breaking something else", theStrikerSurvivesBreakingSomethingElse),
        ("the rule is actually being enforced", theRuleIsActuallyBeingEnforced),
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
    print("\nall threshold tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
