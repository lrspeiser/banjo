"""The world keeps running when nobody is looking at it.

The owner, 2026-09-26, on leaving to the Workshop: "when you leave to the
workshop tab the passive system takes over the rules of that machine."

IT COULD NOT, AND THIS IS WHY. The page was the world's clock. `setInterval`
in world.js asked the server for a step thirty times a second, and that was
the only thing that ever stepped a room -- the server had no loop of its own.
So a tab that went to the Workshop, or to another window, or to sleep, stopped
time: the rover froze mid-drive, the smelter stopped mid-batch, and the world
you came back to was the world you left, to the millisecond. The Workshop
link's own tooltip admitted it: "Pause the world and design one object in
isolation."

This is that loop. When no page has stepped the room for a moment, the clock
takes over and steps it; when a page comes back, the clock stands down. Only
one of them ever holds it, and the live session's own lock makes that safe
even in the moment they change over.

NO MODEL IS ASKED WHILE NOBODY IS WATCHING. The owner again: "if we do keep
the world running we can't have every bot constantly asking llms for what to
do, it will need to have routines that it can run without constant calls to
the llm." A machine has three layers that can drive it and only the top one
costs anything:

  * its REFLEXES, in the engine, 240 times a second -- free;
  * its ROUTINE, a list of tool calls run here in Python -- free;
  * a DECIDER, Jev or the chat's model, asked when something happens to it.

The first two are the whole of what a machine needs to do its job: dig, haul,
smelt, come back for more. The third is off entirely while the clock has the
room (`Brains.unattended`), so a world left running overnight costs nothing
but the processor it runs on. A machine set to be decided for by a model goes
back to being decided for the moment a person is watching it again.

WHAT IT DOES NOT DO.

  * It never runs the world faster than the clock on the wall. It keeps a due
    time, steps however much world time it owes, sleeps when it is early, and
    carries a shortfall into the next slice rather than losing it. Where the
    machine cannot keep up at all it falls behind and says so in the log
    rather than racing. Measured on the new-game valley: 12.96 s of world in
    the 13 s it had, which is realtime to within a third of a percent. The
    two seconds before that are PAGE_HAS_IT_S -- the world is still the
    page's for that long after the page stops asking, so nothing is stepped
    twice in the moment somebody walks away and comes straight back.
  * It does not draw, and it does not send anything to anybody. A page that
    comes back is given the room as it now stands by the ordinary open path.
  * It does not run a room nobody has opened, and it stops the moment the
    session it was given goes away or is replaced.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

_log = logging.getLogger("banjo.world_clock")

#: The world time one tick covers. A quarter of a second is long enough that
#: the cost of a round of routines is lost against the stepping, and short
#: enough that a page taking the room back waits no longer than that.
TICK_S = 0.25
#: The substep the engine is asked for, the same one the page asks for
#: (world.js, LIVE_DT), so an unattended world is stepped exactly as a watched
#: one is and nothing about the physics depends on who was looking.
DT_S = 1.0 / 240.0
#: A page that stepped this recently still has the room. Longer than a frame
#: by a wide margin, so an ordinary stutter does not hand the room over and
#: back; short enough that walking away is noticed at once.
PAGE_HAS_IT_S = 2.0
#: How far behind the wall clock the room may fall before it is worth saying
#: so. The house gate is realtime (docs/machine-world.md); this only logs.
BEHIND_SAYS_S = 2.0
#: The most world time one tick may cover while catching up. A page that
#: held the room for a while, or a machine that stalled, must not produce
#: one enormous step: the engine's own cap is MAX_STEPS_PER_CALL, and a
#: huge slice would also make the room jump for anybody watching.
MOST_AT_ONCE_S = 1.0
#: How often it looks to see whether the page has gone, while the page
#: still has the room. Cheap, and it is only a look.
IDLE_LOOK_S = 0.25
#: After a failure, wait this long before trying again rather than spinning.
AFTER_TROUBLE_S = 1.0


class WorldClock:
    """Steps the open room while no page is stepping it."""

    def __init__(self, app: Any, keep: Any = None) -> None:
        self.app = app
        #: How the running world is saved (server.keep_world), passed in
        #: rather than reached for, because it is a function of the server's
        #: and not a method of the app's.
        self.keep = keep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._page_at = time.monotonic()
        self._lock = threading.Lock()
        #: What it has done, for anybody asking how the unattended world went.
        self.ticks = 0
        self.world_s = 0.0
        self.behind_s = 0.0
        self.trouble = ""

    # ---- who has the room -----------------------------------------------------
    def page_stepped(self) -> None:
        """A page just stepped the room: it has it, and the clock stands
        down."""
        with self._lock:
            self._page_at = time.monotonic()

    def has_it(self) -> bool:
        """Whether the clock, rather than a page, is stepping the room now."""
        with self._lock:
            return time.monotonic() - self._page_at >= PAGE_HAS_IT_S

    # ---- running --------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="banjo-world-clock", daemon=True)
        self._thread.start()
        _log.info("banjo: the world clock is running; a room keeps going when no page is stepping it")

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _run(self) -> None:
        # A SLICE IS OWED, NOT TIMED. Stepping a quarter second and then
        # sleeping a quarter second loses whatever the step and the sleep's
        # own granularity cost, every tick, for ever: measured at 83% of
        # realtime doing it that way, and 68% with a poll on top of it. So the
        # clock keeps a due time, steps however much world time it owes, and
        # carries the shortfall into the next slice. It still never runs AHEAD
        # -- it sleeps when it is early -- it only stops losing ground.
        due = time.monotonic()
        while not self._stop.is_set():
            if not self.has_it():
                self._stop.wait(IDLE_LOOK_S)
                due = time.monotonic()                   # the page had it; owe nothing
                continue
            owed = min(TICK_S + max(0.0, time.monotonic() - due), MOST_AT_ONCE_S)
            try:
                stepped = self._tick(owed)
            except Exception as failed:                  # never let the clock die of one bad step
                self.trouble = str(failed)[:200]
                _log.warning("banjo: the world clock could not step: %s", self.trouble)
                self._stop.wait(AFTER_TROUBLE_S)
                due = time.monotonic()
                continue
            if not stepped:
                self._stop.wait(0.2)                     # nothing open to step
                due = time.monotonic()
                continue
            self.trouble = ""
            due += owed
            spare = due - time.monotonic()
            if spare > 0:
                self._stop.wait(spare)
            else:
                self.behind_s += -spare
                if -spare >= BEHIND_SAYS_S:
                    _log.warning("banjo: the world clock is %.1f s behind the wall; it will catch up in "
                                 "slices of at most %.2f s", -spare, MOST_AT_ONCE_S)

    def _tick(self, world_s: float = TICK_S) -> bool:
        """This much world time, stepped the way the page steps it."""
        app = self.app
        live = getattr(app, "live", None)
        session = getattr(live, "session", None) if live is not None else None
        if session is None or getattr(app, "live_holder", None) != "world":
            return False
        body = {"session": session.id, "op": "step", "dt": DT_S,
                "n": max(1, int(round(world_s / DT_S)))}
        brains = getattr(app, "brains", None)
        # The routines take their next step, exactly as they do under a page.
        # No decider is asked: `unattended` is set for as long as the clock
        # has the room (see this module's own note).
        if brains is not None:
            brains.unattended = True
            brains.before(app, body)
        answer = live.act(body)
        # A page that comes back is sent the machines whole by the open path,
        # so nothing is attached here -- there is nobody to attach it to.
        self.ticks += 1
        self.world_s += TICK_S
        if callable(self.keep):
            # Time-gated inside itself (KEEP_WORLD_EVERY_S of world time), so
            # this is not a write per tick.
            self.keep(app, "the world ran on while nobody was looking")
        return isinstance(answer, dict)
