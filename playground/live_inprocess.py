"""The same live world, held in this process instead of a subprocess.

`live_session.Session` spawns `banjo_live_world_run` and talks JSON over a pipe.
That works, and it is what the playground has always done, but it is also the
only way anything outside the C++ tree could reach the engine -- which is a
strange thing to be true of a physics engine. The C library exists to fix that,
and this is the playground taking its own medicine: the same scenes, the same
physics, the same replies, with no process boundary and no JSON in the middle.

It answers to the same interface `Session` does -- `state`, `send(**command)`,
`close()` -- so the server does not know or care which one it is holding. That
is deliberate: two implementations of one interface can be run against the same
tests and compared reply for reply, which is the only honest way to claim the
in-process path does the same thing.

Turned on with `--live-inprocess` or `BANJO_LIVE_INPROCESS=1`. Off by default,
because the subprocess is the one that has been watched working: a world that
crashes takes the server down with it when it is in the same process, and the
server is what the owner is looking at.
"""
from __future__ import annotations

import math
import sys
import uuid
from pathlib import Path
from typing import Any

import fracture_lab

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bindings" / "python"))

# Imported lazily by `available()` so that a tree without the library built
# still starts: this is an option, not a requirement.
banjo: Any = None


def available() -> tuple[bool, str]:
    """Whether the C library can be loaded, and what went wrong if not."""
    global banjo
    try:
        if banjo is None:
            import banjo as module   # noqa: PLC0415
            banjo = module
        banjo.library()
        return True, ""
    except Exception as error:      # a missing library is a reason, not a crash
        return False, str(error)


class InProcessSession:
    """One open world, living here.

    Every method mirrors an op of the line protocol, and every reply is shaped
    exactly like the subprocess's, because the browser and the server are
    written against that shape and neither should have to know the difference.
    """

    def __init__(self, spec: dict[str, Any], cell_m: float | None = None) -> None:
        ok, why = available()
        if not ok:
            raise ValueError(f"the in-process engine is not available: {why}")
        bodies = fracture_lab.as_objects(spec)
        if not bodies:
            raise ValueError("This scene has nothing in it to simulate.")
        spec = dict(spec, bodies=bodies)
        self.id = uuid.uuid4().hex
        self.spec = spec
        self.opened_at = 0.0
        scene = fracture_lab.scene_document(spec)
        self._cell_m = float(cell_m if cell_m is not None else spec["cell_m"])
        self._stepped_back = False
        try:
            self._world = banjo.World(scene, cell_size_m=self._cell_m)
        except Exception as error:
            raise ValueError(str(error)) from error
        self.state = self._describe(geometry=True)

    # -- the wire, without a wire -----------------------------------------
    @staticmethod
    def _number(value: float) -> float | None:
        """A float JSON can carry, or null.

        An impact can report an infinite threshold, and it means something: the
        speed at which this body could break is unbounded, so nothing can break
        it. A single cell with no bonds left to fail is the usual way to get
        one. The subprocess lane has always sent those as null -- nlohmann
        writes a non-finite double that way without comment -- so this sends
        null too, and the browser cannot tell the lanes apart. Python's json
        refuses inf outright, which is how this surfaced at all: the same value
        had been going quietly over the pipe the whole time.
        """
        return value if math.isfinite(value) else None

    def _describe(self, geometry: bool = False, extra: dict[str, Any] | None = None
                  ) -> dict[str, Any]:
        world = self._world
        bodies = []
        for body in world.bodies():
            bodies.append({
                "name": body.name,
                "material": body.material,
                "shape": body.shape,
                "dimensions_m": list(body.dimensions_m),
                "position_m": [self._number(v) for v in body.position_m],
                "orientation_wxyz": [self._number(v) for v in body.orientation_wxyz],
                "velocity_m_s": [self._number(v) for v in body.velocity_m_s],
                "anchored": body.anchored,
                "held": body.held,
                "color_rgba": f"{body.rgba:08x}",
            })
        state: dict[str, Any] = {
            "ok": True,
            "t": self._number(world.time_s),
            # A step that was taken back did not happen: the world is one step
            # short of an impact and the host has a decision to make before time
            # moves again.
            "stepped_back": self._stepped_back,
            "cell_size_m": self._cell_m,
            "geometry": geometry,
            "held": world.held,
            "bodies": bodies,
            "impacts": [{"struck": i.struck, "by": i.by,
                         "closing_speed_m_s": self._number(i.closing_speed_m_s),
                         "threshold_speed_m_s": self._number(i.threshold_speed_m_s),
                         "dent_speed_m_s": self._number(i.dent_speed_m_s),
                         "would_dent": i.would_dent,
                         "energy_j": self._number(i.energy_j),
                         "would_break": i.would_break}
                        for i in world.impacts()],
            "breakable": world.breakable(),
        }
        if extra:
            state.update(extra)
        return state

    def send(self, **command: Any) -> dict[str, Any]:
        op = str(command.get("op", ""))
        world = self._world
        try:
            if op == "step":
                dt = float(command.get("dt", 1 / 60.0))
                # Stop the batch on a step that was taken back, exactly as the
                # line protocol does, and hand the decision back to the host.
                #
                # banjo_advance would settle the break here instead, and that is
                # the right call for a program that just wants a world running.
                # It is the wrong one for this: the playground TELLS the reader
                # what broke and how hard it was hit -- "iron ball hit glass
                # plate at 6.3 m/s, it broke into 8 pieces" -- and it can only
                # do that if it is the one that decides. Resolving the break in
                # here left the chat silent about the only interesting thing
                # that had happened.
                for _ in range(max(1, int(command.get("n", 1)))):
                    if world.step(dt) == banjo.BREAK_PENDING:
                        self._stepped_back = True
                        break
                    self._stepped_back = False
            elif op == "grab":
                world.grab(str(command.get("name", "")))
            elif op == "move":
                world.move_held(command.get("to") or [0.0, 0.0, 0.0])
            elif op == "release":
                world.release()
            elif op == "fracture":
                pieces = world.fracture(str(command.get("name", "")),
                                        float(command.get("window_s", 0.003)))
                self.state = self._describe(geometry=True,
                                            extra={"pieces": pieces,
                                                   "outcome": world.last_outcome})
                return self.state
            elif op == "pick":
                # The one reply that does not carry the world: it changes
                # nothing and a pointer asks it on every mouse move.
                found = world.pick(command.get("from") or [0, 0, 0],
                                   command.get("dir") or [0, -1, 0],
                                   float(command.get("max_m", 1000.0)))
                return {"ok": True, "hit": found.hit, "name": found.name,
                        "distance_m": self._number(found.distance_m),
                        "point_m": [self._number(v) for v in found.point_m]}
            elif op != "poses":
                raise ValueError(f"unknown live operation: {op}")
        except Exception as error:
            raise ValueError(str(error)) from error
        self.state = self._describe(geometry=(op == "poses"))
        return self.state

    def close(self) -> None:
        try:
            self._world.close()
        except Exception:
            pass


def scene_for(spec: dict[str, Any]) -> dict[str, Any]:
    """The scene document a spec becomes, for comparing the two lanes."""
    bodies = fracture_lab.as_objects(spec)
    return fracture_lab.scene_document(dict(spec, bodies=bodies))
