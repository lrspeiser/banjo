"""A machine's routine (docs/machine-world.md, "A machine's senses and its
tools"): what it does when nobody is telling it anything.

A routine is a list of steps, each one tool call with its arguments and what
ends it, run by one generic runner that knows nothing of digging: it issues
the step's tool, waits until the world says the step is done -- the program
has finished what it was asked, the hopper is full, the machine has arrived --
and goes on to the next, round again at the end. A routine is data
(ROUTINES), declared on a program in the room's spec:

    "routine": {"kind": "dig", "places": {"dig site": [x, z], "depot": [x, z]},
                "hopper_kg": 40, "work_j_per_kg": 50}

and the runner reads places, loads and limits from that. While someone else
has the machine -- Jev or the model on something that happened, a person
talking to it, its own program resting for want of charge -- the routine
waits, and takes up its step again when the ask is lifted. What it carries is
its hopper: an account kept here, apart from what the person carries, filled
by the dig tool out of the ground's carried volume and emptied by the dump
tool back onto the ground, so the ground's ledger stays whole. The hopper is
not saved with the world yet: a restart empties it.

The dig routine: go to the dig site; dig until the hopper is full; go to the
depot; dump; again. Rest is the program's own: below its rest_below it stops
where it is until charged, and the routine waits with it.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import machine_senses as senses
import machine_tools as tools

# The steps of each routine: a tool, its arguments (a "place" names one of the
# routine's places), and what ends the step -- "asked_done" (the program has
# finished what it was asked, or arrived), "load_full", "load_empty", or a
# number of seconds. A step that fails is tried again up to `retries` times
# before the routine gives up and waits for someone.
ROUTINES: dict[str, dict[str, Any]] = {
    "dig": {
        "description": "Dig at its dig site until its hopper is full, carry the load to its depot, dump it "
                       "there, and go back for more.",
        "needs": ["hopper_kg"], "places": ["dig site", "depot"],
        "steps": [
            {"do": "go_to", "args": {"place": "dig site"}, "until": "arrived", "retries": 3},
            {"do": "dig", "args": {}, "until": "load_full", "repeat": True},
            {"do": "go_to", "args": {"place": "depot"}, "until": "arrived", "retries": 3},
            {"do": "dump", "args": {}, "until": "load_empty"},
        ],
    },
    "roam": {"description": "Roam by its reflexes alone.", "needs": [], "places": [], "steps": []},
}
DEFAULT_HOPPER_KG = 40.0
NOTES_KEPT = 12
# A go_to that runs out of time is tried again from where it stands, this many
# times, before the routine gives up the step.
RETRIES = 3


class Routine:
    """One machine's routine as it runs: which step it is on, what it carries,
    and what it has done lately."""

    def __init__(self, name: str, declared: dict[str, Any] | None):
        declared = declared or {}
        self.name = name
        self.kind = str(declared.get("kind") or "roam")
        self.spec = ROUTINES.get(self.kind) or ROUTINES["roam"]
        self.places: dict[str, list[float]] = {str(k): [float(v[0]), float(v[1])]
                                               for k, v in (declared.get("places") or {}).items()}
        self.hopper_kg = float(declared.get("hopper_kg") or 0.0)
        self.work_j_per_kg = float(declared.get("work_j_per_kg") or tools.WORK_J_PER_KG)
        self.sand_m3 = self.soil_m3 = self.kg = 0.0
        self.delivered_kg = 0.0
        self.trips = 0
        self.step = 0
        self.tries = 0
        self.issued: dict[str, Any] | None = None    # what the current step last did
        self.paused_by: str | None = None
        self.notes: deque[str] = deque(maxlen=NOTES_KEPT)
        self.seq = 0

    # ---- the hopper ------------------------------------------------------------
    def carries(self) -> bool:
        return self.hopper_kg > 0.0

    def load_room_kg(self) -> float:
        return max(0.0, self.hopper_kg - self.kg)

    def load_full(self) -> bool:
        return self.carries() and self.kg >= 0.95 * self.hopper_kg

    def load_in(self, sand_m3: float, soil_m3: float, kg: float) -> None:
        self.sand_m3 += sand_m3
        self.soil_m3 += soil_m3
        self.kg += kg

    def load_out(self) -> tuple[float, float, float]:
        out = (self.sand_m3, self.soil_m3, self.kg)
        self.sand_m3 = self.soil_m3 = self.kg = 0.0
        return out

    def delivered(self, sand_m3: float, soil_m3: float, kg: float) -> None:
        self.delivered_kg += kg
        self.trips += 1

    def load_reading(self) -> dict[str, Any]:
        return {"kg": round(self.kg, 2), "sand_m3": round(self.sand_m3, 4), "soil_m3": round(self.soil_m3, 4),
                "capacity_kg": self.hopper_kg, "full": self.load_full(), "empty": self.kg <= 0.0,
                "delivered_kg": round(self.delivered_kg, 2), "trips": self.trips}

    def note(self, words: str) -> None:
        self.notes.append(words)

    # ---- running ---------------------------------------------------------------
    def current(self) -> dict[str, Any] | None:
        steps = self.spec["steps"]
        return steps[self.step % len(steps)] if steps else None

    def resume(self) -> None:
        self.paused_by = None
        self.issued = None

    def _advance(self, why: str) -> None:
        self.note(f"step {self.step % len(self.spec['steps']) + 1} done: {why}")
        self.step += 1
        self.tries = 0
        self.issued = None

    def tick(self, ctx: senses.Context, by: str = "routine") -> dict[str, Any] | None:
        """Before a step the page takes: the routine's next move, if it is its
        turn. Returns what it did, or None when it did nothing."""
        step = self.current()
        program = ctx.program
        if step is None or not program.get("power"):
            return None
        asked = program.get("asked") if isinstance(program.get("asked"), dict) else None
        if program.get("doing") == "resting":
            self.paused_by = "its battery"
            return None
        if asked and asked.get("by") != by:
            self.paused_by = str(asked.get("by"))
            return None
        if self.paused_by is not None:
            self.note(f"back on its routine after {self.paused_by} had it")
            self.paused_by = None
            self.issued = None
        until = step.get("until")
        # Is the step done? A load's state says so whether or not this step
        # issued anything yet: a hopper filled at a person's word is full.
        if until == "load_full" and self.load_full():
            self._advance("its hopper is full")
            return None
        if until == "load_empty" and self.kg <= 0.0 and asked is None and self.issued is not None:
            self._advance("its hopper is empty")
            return None
        if self.issued is not None:
            if until == "arrived":
                if asked and asked.get("doing") == "approaching" and program.get("doing") == "waiting":
                    self._advance("it arrived")
                    return None
                if asked is None:
                    # Its time ran out short of the place: again, from here.
                    self.tries += 1
                    if self.tries > int(step.get("retries", RETRIES)):
                        self.note(f"gave up going to {step['args'].get('place')}: {self.tries - 1} tries")
                        self._advance("given up")
                        return None
                    self.issued = None
            if until == "asked_done" and asked is None:
                self._advance("done")
                return None
            if asked is not None:
                return None                       # still doing the step
            if self.issued is not None and not step.get("repeat"):
                return None
        # Issue the step (again, for a repeating one).
        self.seq += 1
        call = tools.Call(step["do"], dict(step.get("args") or {}), by,
                          why=f"its routine: {self.spec['description'].split(',')[0].lower()}")
        did = tools.run(ctx, call)
        self.issued = did
        if did.get("failed"):
            self.tries += 1
            self.note(did.get("did", "failed"))
            if self.tries > int(step.get("retries", RETRIES)):
                self.paused_by = "a step it could not do"
        return did

    def summary(self) -> dict[str, Any]:
        steps = self.spec["steps"]
        step = self.current()
        return {"kind": self.kind, "description": self.spec["description"], "places": self.places,
                "step": (self.step % len(steps) + 1) if steps else None, "of": len(steps),
                "doing": (f"{step['do']} {step['args'].get('place', '')}".strip() if step else "nothing"),
                "paused_by": self.paused_by, "load": self.load_reading() if self.carries() else None,
                "notes": list(self.notes)[-6:]}


def declared_for(spec: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    """The routine a room declares on the program of this name, if any."""
    for program in ((spec or {}).get("machines") or {}).get("programs") or []:
        if isinstance(program, dict) and program.get("name") == name:
            return program.get("routine") if isinstance(program.get("routine"), dict) else None
    return None
