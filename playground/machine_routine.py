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
from dataclasses import dataclass
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
        unknown = set(step) - {"do", "args", "until", "repeat", "retries", "when", "unless"}
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
        import machine_conditions as conditions
        for key in ("when", "unless"):
            if step.get(key) is not None:
                made[key] = conditions.checked(step[key])
        out.append(made)
    return out


def checked_watch(given: Any) -> list[dict[str, Any]]:
    """What a routine watches for (docs/machine-world.md, "A routine that
    responds"): each a condition and the steps to run the moment it comes to
    hold, interrupting whatever the routine was doing; `then` is "resume"
    (back to the interrupted step) or "restart" (its round from the top)."""
    if given is None:
        return []
    if not isinstance(given, list) or len(given) > 8:
        raise ValueError("watch is a list of at most 8 {when, do, then}")
    import machine_conditions as conditions
    out = []
    for i, watch in enumerate(given):
        if not isinstance(watch, dict) or set(watch) - {"when", "do", "then"} or "when" not in watch or "do" not in watch:
            raise ValueError(f"watch {i + 1} is {{when: condition, do: steps, then: resume | restart}}")
        then = str(watch.get("then") or "resume")
        if then not in ("resume", "restart"):
            raise ValueError(f"watch {i + 1} then is resume or restart")
        out.append({"when": conditions.checked(watch["when"]), "do": checked_steps(watch["do"]), "then": then})
    return out


@dataclass
class Frame:
    """A run of steps as it goes: the routine's own round, an interruption a
    watch raised, or an order a person gave."""
    name: str
    steps: list[dict[str, Any]]
    then: str = "round"                          # round: again from the top; resume: back to what was interrupted
    step: int = 0
    tries: int = 0
    issued: dict[str, Any] | None = None         # what the current step last did
    issued_t: float = 0.0
    order_id: int | None = None

    def current(self) -> dict[str, Any] | None:
        if not self.steps:
            return None
        return self.steps[self.step % len(self.steps)] if self.then == "round" else (
            self.steps[self.step] if self.step < len(self.steps) else None)

    def done(self) -> bool:
        return self.then != "round" and self.step >= len(self.steps)


class Routine:
    """One machine's routine as it runs: which step it is on, what it carries,
    what it watches for, what it has been told to do, and what it has done
    lately."""

    def __init__(self, name: str, declared: dict[str, Any] | None):
        declared = declared or {}
        self.name = name
        self.kind = str(declared.get("kind") or "roam")
        self.spec = ROUTINES.get(self.kind) or ROUTINES["roam"]
        self.steps: list[dict[str, Any]] = [{"args": {}, **s} for s in
                                            (declared.get("steps") or [] if self.kind == "custom" else self.spec["steps"])]
        self.watch: list[dict[str, Any]] = [{**w, "do": [{"args": {}, **s} for s in w.get("do") or []]}
                                            for w in declared.get("watch") or []]
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
        # The frames: the routine's own round at the bottom, and above it
        # whatever interrupted it -- a watch's steps, an order -- run first.
        self.frames: list[Frame] = [Frame("routine", self.steps)]
        self.watching: list[bool] = [False] * len(self.watch)     # whether each watch held last time
        self.paused_by: str | None = None
        self.notes: deque[str] = deque(maxlen=NOTES_KEPT)
        self.finished: deque[dict[str, Any]] = deque(maxlen=8)  # orders and watches that ran to their end
        self.seq = 0
        self.next_order = 1

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

    # ---- frames: the round, interruptions, orders ------------------------------
    @property
    def frame(self) -> Frame:
        return self.frames[-1]

    @property
    def step(self) -> int:
        return self.frames[0].step

    @property
    def issued(self) -> dict[str, Any] | None:
        return self.frame.issued

    def current(self) -> dict[str, Any] | None:
        return self.frame.current()

    def resume(self) -> None:
        self.paused_by = None
        self.frame.issued = None

    def interrupt(self, name: str, steps: list[dict[str, Any]], then: str = "resume",
                  order_id: int | None = None) -> Frame:
        """Steps to run now, before whatever the routine was doing: a watch
        that fired, or an order. The interrupted step is issued again when
        they are done."""
        frame = Frame(name, [{"args": {}, **s} for s in steps], then=then, order_id=order_id)
        self.frames.append(frame)
        self.note(f"{name}: " + "; ".join(f"{s['do']} {s.get('args', {}).get('place', '')}".strip() for s in steps)[:120])
        return frame

    def order(self, said: str, steps: list[dict[str, Any]], by: str = "the person") -> dict[str, Any]:
        """An order (docs/machine-world.md, "Standing requests"): steps a
        person asked for, run before its own round and reported when done.
        Orders queue: a second one waits for the first."""
        order_id = self.next_order
        self.next_order += 1
        pending = [f for f in self.frames if f.order_id is not None]
        frame = Frame(f"order {order_id}", [{"args": {}, **s} for s in steps], then="resume", order_id=order_id)
        if pending:
            # Behind the orders already given: put under them, above the round.
            self.frames.insert(1, frame)
        else:
            self.frames.append(frame)
        self.note(f"told by {by}: {said[:80]}")
        return {"order": order_id, "said": said, "steps": steps, "queued_behind": len(pending)}

    def orders(self) -> list[dict[str, Any]]:
        return [{"order": f.order_id, "name": f.name, "step": f.step + 1, "of": len(f.steps),
                 "running": f is self.frame}
                for f in self.frames if f.order_id is not None]

    def cancel_orders(self) -> int:
        kept = [f for f in self.frames if f.order_id is None]
        gone = len(self.frames) - len(kept)
        self.frames = kept
        if gone:
            self.note(f"{gone} order{'' if gone == 1 else 's'} dropped")
            self.frame.issued = None
        return gone

    def _advance(self, why: str) -> None:
        frame = self.frame
        # The round's own steps are noted as they always were ("step 4 done");
        # an interruption's carry its name ("order 1 step 1 done").
        self.note(f"step {frame.step % max(1, len(frame.steps)) + 1} done: {why}"
                  if frame.name == "routine" else f"{frame.name} step {frame.step + 1} done: {why}")
        frame.step += 1
        frame.tries = 0
        frame.issued = None
        if frame.done() and len(self.frames) > 1:
            self.frames.pop()
            self.finished.append({"name": frame.name, "order": frame.order_id, "at_step": len(frame.steps)})
            if frame.then == "restart":
                self.frames[0].step = 0
                self.frames[0].tries = 0
            self.note(f"{frame.name} done; back to {self.frame.name}"
                      + (" from the top" if frame.then == "restart" else ""))
            self.frame.issued = None

    def _watches(self, ctx: senses.Context) -> dict[str, Any] | None:
        """A watch whose condition has just come to hold: its steps go on top,
        once per rising edge, and never while its own steps are running."""
        import machine_conditions as conditions
        running = {f.name for f in self.frames}
        fired = None
        for i, watch in enumerate(self.watch):
            name = f"watch {i + 1}"
            now = conditions.holds(ctx, watch["when"])
            rising = now and not self.watching[i]
            self.watching[i] = now
            if rising and fired is None and name not in running and self.frame.order_id is None:
                fired = watch
                self.interrupt(name, watch["do"], then=watch.get("then", "resume"))
                self.note(f"{name}: {conditions.described(watch['when'])}")
        return fired

    def tick(self, ctx: senses.Context, by: str = "routine") -> dict[str, Any] | None:
        """Before a step the page takes: the routine's next move, if it is its
        turn. Returns what it did, or None when it did nothing."""
        program = ctx.program
        if not program.get("power"):
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
            self.frame.issued = None
        if self.watch:
            self._watches(ctx)
        frame = self.frame
        step = frame.current()
        if step is None:
            if frame.done() and len(self.frames) > 1:
                self._advance("nothing more")
            return None
        until = step.get("until", "done")
        # Is the step done? A load's state says so whether or not this step
        # issued anything yet: a hopper filled at a person's word is full.
        if until == "load_full" and self.load_full():
            self._advance("its hopper is full")
            return None
        if until == "load_empty" and self.kg <= 0.0 and asked is None and frame.issued is not None:
            self._advance("its hopper is empty")
            return None
        if frame.issued is not None:
            if until == "arrived":
                if asked and asked.get("doing") == "approaching" and program.get("doing") == "waiting":
                    self._advance("it arrived")
                    return None
                if asked is None:
                    # Its time ran out short of the place: again, from here.
                    frame.tries += 1
                    if frame.tries > int(step.get("retries", RETRIES)):
                        self.note(f"gave up going to {step['args'].get('place')}: {frame.tries - 1} tries")
                        self._advance("given up")
                        return None
                    frame.issued = None
            if until == "asked_done" and asked is None:
                self._advance("done")
                return None
            if until == "done" and not frame.issued.get("failed"):
                self._advance("done")
                return None
            if isinstance(until, (int, float)) and not isinstance(until, bool) \
                    and float(ctx.t) - frame.issued_t >= float(until):
                self._advance(f"{until:g} s are up")
                return None
            if asked is not None:
                return None                       # still doing the step
            if frame.issued is not None and not step.get("repeat"):
                return None
        # A step with a condition on it: skipped unless it holds (when), or
        # while it holds (unless), read as the step is about to be issued.
        if step.get("when") is not None or step.get("unless") is not None:
            import machine_conditions as conditions
            if step.get("when") is not None and not conditions.holds(ctx, step["when"]):
                self._advance(f"skipped: {conditions.described(step['when'])} does not hold")
                return None
            if step.get("unless") is not None and conditions.holds(ctx, step["unless"]):
                self._advance(f"skipped: {conditions.described(step['unless'])} holds")
                return None
        # Issue the step (again, for a repeating one).
        self.seq += 1
        why = (f"its routine: {self.spec['description'].split(',')[0].lower()}" if frame.order_id is None
               and frame.name == "routine" else f"{frame.name}")
        call = tools.Call(step["do"], dict(step.get("args") or {}), by, why=why)
        did = tools.run(ctx, call)
        frame.issued = did
        frame.issued_t = float(ctx.t)
        if did.get("idle"):
            # Nothing to do yet (nothing on the pile, nothing to work): asked
            # again next time, quietly. A take with something in the hopper
            # and nothing more to take goes on with what it has.
            if until == "load_full" and self.kg > 0.0:
                self._advance("nothing more to take there")
            else:
                frame.issued = None
            return None
        if did.get("failed"):
            frame.tries += 1
            self.note(did.get("did", "failed"))
            if frame.tries > int(step.get("retries", RETRIES)):
                if frame.order_id is not None or frame.then != "round":
                    self._advance("given up: " + str(did.get("did", ""))[:80])
                else:
                    self.paused_by = "a step it could not do"
        return did

    def summary(self) -> dict[str, Any]:
        frame = self.frame
        step = frame.current()
        out = {"kind": self.kind, "description": self.spec["description"], "places": self.places,
               "step": (self.frames[0].step % len(self.steps) + 1) if self.steps else None, "of": len(self.steps),
               "doing": (f"{step['do']} {step['args'].get('place', '')}".strip() if step else "nothing"),
               "on": frame.name if frame.name != "routine" else None,
               "orders": self.orders(), "watches": len(self.watch),
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
