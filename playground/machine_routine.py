"""A machine's routine (docs/machine-world.md, "A machine's senses and its
tools"; "Raw materials into finished goods"): what it does when nobody is
telling it anything.

A routine is a list of steps, each one tool call with its arguments and what
ends it, run by one generic runner that knows nothing of digging: it issues
the step's tool, waits until the world says the step is done -- the program
has finished what it was asked, the hopper is full, the machine has arrived --
and goes on to the next, round again at the end. A routine is data, declared
on a program in the room's spec, in one of two ways: a named kind whose steps
are written here (ROUTINES),

    "routine": {"kind": "dig", "places": {"dig site": [x, z], "depot": [x, z]},
                "hopper_kg": 40, "work_j_per_kg": 50}

or steps of its own, in the same words a named kind's are written in, which
is how a person or a model writes a machine a new job:

    "routine": {"kind": "custom", "hopper_kg": 20,
                "places": {"vein": [x, z], "smelter intake": [x, z]},
                "steps": [{"do": "go_to", "args": {"place": "vein"}, "until": "arrived"},
                          {"do": "dig", "until": "load_full", "repeat": true},
                          {"do": "go_to", "args": {"place": "smelter intake"}, "until": "arrived"},
                          {"do": "dump", "args": {"place": "smelter intake"}, "until": "load_empty"}]}

A step's `until` is "arrived" (a go_to that got there), "asked_done" (the
program has finished what the tool asked of it), "load_full", "load_empty",
"done" (the tool did it, once) or a number of seconds; `repeat` issues the
tool again each time it finishes until `until` holds; a step that fails is
tried again up to `retries` times before the routine gives up and waits for
someone. The runner reads places, loads and limits from the declaration.
While someone else has the machine -- Jev or the model on something that
happened, a person talking to it, its own program resting for want of charge
-- the routine waits, and takes up its step again when the ask is lifted.

What it carries is its hopper: an account kept here, apart from what the
person carries, of the sand and soil a scoop brought up (filled by the dig
tool out of the ground's carried volume, emptied by the dump tool back onto
the ground, so the ground's ledger stays whole) and of the goods in it -- ore
a scoop brought up from a deposit, or what it took off a stockpile -- by
substance and mass. A machine that processes (the "process" routine) holds
nothing itself: it works its intake stockpile into its output one by a
recipe of the room's (machine_goods). The hopper is not saved with the world
yet: a restart empties it.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import machine_senses as senses
import machine_tools as tools

# The steps of each named routine: a tool, its arguments (a "place" names one
# of the routine's places), and what ends the step.
ROUTINES: dict[str, dict[str, Any]] = {
    "dig": {
        "description": "Dig at its dig site until its hopper is full, carry the load to its depot, dump it "
                       "there, and go back for more.",
        "needs": ["hopper_kg"], "places": ["dig site", "depot"],
        "steps": [
            {"do": "go_to", "args": {"place": "dig site"}, "until": "arrived", "retries": 3},
            {"do": "dig", "args": {}, "until": "load_full", "repeat": True},
            # Away from its own hole before it turns for the depot.
            {"do": "back_off", "args": {"for_s": 1.5}, "until": "asked_done"},
            {"do": "go_to", "args": {"place": "depot"}, "until": "arrived", "retries": 3},
            {"do": "dump", "args": {"place": "depot"}, "until": "load_empty"},
        ],
    },
    "haul": {
        "description": "Take what is on the stockpile at its source, carry it to its destination, put it "
                       "there, and go back for more.",
        "needs": ["hopper_kg"], "places": ["source", "destination"],
        "steps": [
            {"do": "go_to", "args": {"place": "source"}, "until": "arrived", "retries": 3},
            {"do": "take", "args": {"place": "source"}, "until": "load_full", "repeat": True},
            {"do": "go_to", "args": {"place": "destination"}, "until": "arrived", "retries": 3},
            {"do": "dump", "args": {"place": "destination"}, "until": "load_empty"},
        ],
    },
    "process": {
        "description": "Work what is on its intake stockpile into its output one, a batch at a time, by its "
                       "recipe.",
        "needs": ["recipe", "intake", "output"], "places": [],
        "steps": [
            {"do": "process", "args": {}, "until": "asked_done", "repeat": True},
        ],
    },
    "custom": {"description": "Its own steps, as they were written.", "needs": ["steps"], "places": [],
               "steps": []},
    "roam": {"description": "Roam by its reflexes alone.", "needs": [], "places": [], "steps": []},
}
DEFAULT_HOPPER_KG = 40.0
NOTES_KEPT = 12
# A go_to that runs out of time is tried again from where it stands, this many
# times, before the routine gives up the step.
RETRIES = 3
UNTILS = ("arrived", "asked_done", "load_full", "load_empty", "done")
STEPS_MOST = 24
# A machine that processes works this much of its recipe's input at a time
# unless its routine says otherwise.
BATCH_KG = 5.0


def checked_steps(given: Any) -> list[dict[str, Any]]:
    """Steps as a person or a model writes them, checked: a tool the machines
    have, arguments as an object, an `until` the runner knows or a number of
    seconds, repeat and retries."""
    if not isinstance(given, list) or not given or len(given) > STEPS_MOST:
        raise ValueError(f"steps is a list of 1 to {STEPS_MOST} steps")
    out = []
    for i, step in enumerate(given):
        if not isinstance(step, dict):
            raise ValueError(f"step {i + 1} is an object: do, args, until, repeat, retries")
        unknown = set(step) - {"do", "args", "until", "repeat", "retries"}
        if unknown:
            raise ValueError(f"step {i + 1} cannot say {sorted(unknown)}")
        do = str(step.get("do") or "")
        if do not in tools.TOOLS:
            raise ValueError(f"step {i + 1} does {do!r}, and there is no such tool; the tools are "
                             + ", ".join(sorted(tools.TOOLS)))
        args = step.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError(f"step {i + 1} args is an object")
        until = step.get("until", "done")
        if isinstance(until, bool) or not (until in UNTILS or (isinstance(until, (int, float)) and 0 < until <= 3600)):
            raise ValueError(f"step {i + 1} until is one of {', '.join(UNTILS)}, or seconds up to 3600")
        made: dict[str, Any] = {"do": do, "args": {str(k): v for k, v in args.items()}, "until": until}
        if step.get("repeat"):
            made["repeat"] = True
        if step.get("retries") is not None:
            retries = int(step["retries"])
            if not 0 <= retries <= 20:
                raise ValueError(f"step {i + 1} retries is 0 to 20")
            made["retries"] = retries
        out.append(made)
    return out


class Routine:
    """One machine's routine as it runs: which step it is on, what it carries,
    and what it has done lately."""

    def __init__(self, name: str, declared: dict[str, Any] | None):
        declared = declared or {}
        self.name = name
        self.kind = str(declared.get("kind") or "roam")
        self.spec = ROUTINES.get(self.kind) or ROUTINES["roam"]
        self.steps: list[dict[str, Any]] = (list(declared.get("steps") or []) if self.kind == "custom"
                                            else list(self.spec["steps"]))
        self.places: dict[str, list[float]] = {str(k): [float(v[0]), float(v[1])]
                                               for k, v in (declared.get("places") or {}).items()}
        self.hopper_kg = float(declared.get("hopper_kg") or 0.0)
        self.work_j_per_kg = float(declared.get("work_j_per_kg") or tools.WORK_J_PER_KG)
        # A machine that processes: its recipe, the stockpiles it works
        # between, and how much it takes on at a time.
        self.recipe = str(declared.get("recipe") or "") or None
        self.intake = str(declared.get("intake") or "") or None
        self.output = str(declared.get("output") or "") or None
        self.batch_kg = float(declared.get("batch_kg") or BATCH_KG)
        self.made_kg = 0.0
        self.batches = 0
        self.sand_m3 = self.soil_m3 = self.kg = 0.0
        self.goods: dict[str, float] = {}
        self.delivered_kg = 0.0
        self.trips = 0
        self.step = 0
        self.tries = 0
        self.issued: dict[str, Any] | None = None    # what the current step last did
        self.issued_t: float = 0.0
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

    def load_in(self, sand_m3: float, soil_m3: float, kg: float, goods: dict[str, float] | None = None) -> None:
        self.sand_m3 += sand_m3
        self.soil_m3 += soil_m3
        self.kg += kg
        for k, v in (goods or {}).items():
            if v > 0.0:
                self.goods[k] = self.goods.get(k, 0.0) + float(v)

    def load_out(self) -> tuple[float, float, float]:
        out = (self.sand_m3, self.soil_m3, self.kg)
        self.sand_m3 = self.soil_m3 = self.kg = 0.0
        self.goods = {}
        return out

    def delivered(self, sand_m3: float, soil_m3: float, kg: float) -> None:
        self.delivered_kg += kg
        self.trips += 1

    def load_reading(self) -> dict[str, Any]:
        return {"kg": round(self.kg, 2), "sand_m3": round(self.sand_m3, 4), "soil_m3": round(self.soil_m3, 4),
                "goods_kg": {k: round(v, 3) for k, v in self.goods.items() if v > 0.0},
                "capacity_kg": self.hopper_kg, "full": self.load_full(), "empty": self.kg <= 0.0,
                "delivered_kg": round(self.delivered_kg, 2), "trips": self.trips}

    def note(self, words: str) -> None:
        self.notes.append(words)

    # ---- running ---------------------------------------------------------------
    def current(self) -> dict[str, Any] | None:
        return self.steps[self.step % len(self.steps)] if self.steps else None

    def resume(self) -> None:
        self.paused_by = None
        self.issued = None

    def _advance(self, why: str) -> None:
        self.note(f"step {self.step % len(self.steps) + 1} done: {why}")
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
        until = step.get("until", "done")
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
            if until == "done" and not self.issued.get("failed"):
                self._advance("done")
                return None
            if isinstance(until, (int, float)) and not isinstance(until, bool) \
                    and float(ctx.t) - self.issued_t >= float(until):
                self._advance(f"{until:g} s are up")
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
        self.issued_t = float(ctx.t)
        if did.get("idle"):
            # Nothing to do yet (nothing on the pile, nothing to work): asked
            # again next time, quietly. A take with something in the hopper
            # and nothing more to take goes on with what it has.
            if until == "load_full" and self.kg > 0.0:
                self._advance("nothing more to take there")
            else:
                self.issued = None
            return None
        if did.get("failed"):
            self.tries += 1
            self.note(did.get("did", "failed"))
            if self.tries > int(step.get("retries", RETRIES)):
                self.paused_by = "a step it could not do"
        return did

    def summary(self) -> dict[str, Any]:
        step = self.current()
        out = {"kind": self.kind, "description": self.spec["description"], "places": self.places,
               "step": (self.step % len(self.steps) + 1) if self.steps else None, "of": len(self.steps),
               "doing": (f"{step['do']} {step['args'].get('place', '')}".strip() if step else "nothing"),
               "paused_by": self.paused_by, "load": self.load_reading() if self.carries() else None,
               "notes": list(self.notes)[-6:]}
        if self.recipe:
            out["making"] = {"recipe": self.recipe, "intake": self.intake, "output": self.output,
                             "batch_kg": self.batch_kg, "made_kg": round(self.made_kg, 2), "batches": self.batches}
        return out


def declared_for(spec: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    """The routine a room declares on the program of this name, if any."""
    for program in ((spec or {}).get("machines") or {}).get("programs") or []:
        if isinstance(program, dict) and program.get("name") == name:
            return program.get("routine") if isinstance(program.get("routine"), dict) else None
    return None
