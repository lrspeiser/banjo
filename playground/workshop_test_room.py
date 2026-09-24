"""The Workshop's test room: a little world, with the world's own physics.

The owner: *"the test environment should have ground and gravity and operate the
same as the real world. It can also have the sun positioned in the sky or
nighttime and data about power loading in a battery via solar, and so forth.
Make sure it is all built out such that when we then put the product in the real
world it operates the same way."*

The bench used to answer "does it work?" with a static-load rig: the design's
cells floating in an empty spec with a weight set on top -- no ground, no sky,
nothing for it to stand on or drive over. A machine cannot be tested that way at
all, and nothing about the answer carried to the world.

So a test room here is a **room**, of the same shape a world room is: flat
ground of real soil, gravity, a sky with the sun somewhere in it (or below it),
and whatever else you want to stand there. Testing a thing is **installing** it
into that room -- through `workshop_install`, the same call the world uses, so
the same compiler draws it, the same placement seats it on the ground, and the
same machine declarations wire up its battery, its motors and its program. There
is no second physics and no second way of making a thing. What it does here is
what it does there, because it is the same code doing it.

What is different is only what a bench should be: the room is small, it is
thrown away when you are done, and nothing in it is stepped until you say so.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any

import inventory
import live_session
import rigid_assembly
import room_store
import workshop_install as install
import world_room

SCHEMA = "banjo.workshop-test-room.v1"

#: The ground's surface. Flat ground stands at the depth of its soil, not at
#: zero, and a thing set down at zero is buried in it.
GROUND_M = 0.4
#: The cell the bench checks at (workshop_chat), so a thing checked there is
#: drawn the same way here.
CELL_M = 0.04
#: The world page's own step.
DT = 1 / 240
#: Noon over a clear day, which is what a panel is rated against.
NOON = {"elevation_deg": 60.0, "azimuth_deg": 180.0, "irradiance_w_m2": 1000.0}


def _box(name, material, size_m, at_m, anchored=False, shape="box"):
    return {"name": name, "shape": shape, "material": material, "anchored": bool(anchored),
            "size_mm": [round(v * 1000.0, 3) for v in size_m],
            "center_mm": [round(v * 1000.0, 3) for v in at_m]}


def _stool(name, at):
    """A stool: a 450 mm oak seat on four legs, its top 450 mm up, standing free."""
    parts = [{"name": "seat", "dimensions_m": [0.45, 0.04, 0.45], "center_local_m": [0.0, 0.43, 0.0]}]
    for i, (sx, sz) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
        parts.append({"name": f"leg {i}", "dimensions_m": [0.05, 0.41, 0.05],
                      "center_local_m": [sx * 0.18, 0.205, sz * 0.18]})
    body = {"name": name, "material": "oak", "position_m": [at[0], 0.0, at[1]],
            "_centre_m": [0.0, 0.35, 0.0], "parts": parts}
    one = rigid_assembly.placed({"bodies": [body], "joints": []}, [at[0], 0.0, at[1]])
    lift = GROUND_M + max(-low for low, _, _ in rigid_assembly.footprint(one))
    one = rigid_assembly.placed({"bodies": [deepcopy(body)], "joints": []}, [at[0], lift, at[1]])
    return {"precise_rigid_bodies": rigid_assembly.scene_bodies(one)}


#: What you can stand in the room beside the thing being tested. A person picks
#: from these by name, and so can the model: they are the things a product is
#: usually tested against -- something to sit on, something to push, something
#: to hit, something that will not move.
THINGS = {
    "stool": ("something to sit on: a 450 mm oak seat on four legs", _stool),
    "plank": ("an oak plank lying on the ground, 1.2 m by 200 mm",
              lambda name, at: {"bodies": [_box(name, "oak", (0.2, 0.05, 1.2),
                                                (at[0], GROUND_M + 0.025, at[1]))]}),
    "ball": ("a 200 mm iron ball",
             lambda name, at: {"bodies": [_box(name, "iron", (0.2, 0.2, 0.2),
                                               (at[0], GROUND_M + 0.1, at[1]), shape="sphere")]}),
    "post": ("a concrete post standing in the ground, 150 mm square and 900 mm tall",
             lambda name, at: {"bodies": [_box(name, "concrete", (0.15, 0.9, 0.15),
                                               (at[0], GROUND_M + 0.45, at[1]), anchored=True)]}),
}


def things() -> list[dict[str, str]]:
    """What can be put in the room, for a person or the model to choose from."""
    return [{"what": name, "says": says} for name, (says, _) in sorted(THINGS.items())]


def spec(*, sun: Any = None, day: Any = None, items: Any = ()) -> dict[str, Any]:
    """A little room: flat ground of real soil, gravity, a sky, and what you put in it.

    `sun` puts it at a fixed place -- elevation, azimuth and irradiance -- and
    `day` gives it a day it crosses, so a machine can be tested at four in the
    afternoon or in the dark. Neither, and it is noon on a clear day, which is
    what a panel is rated against. `day` with an hour after sunset IS the night:
    nothing charges, and a machine that rests until morning will.
    """
    room: dict[str, Any] = {
        "algorithm": "lattice", "cell_m": CELL_M, "plasticity": "on",
        "terrain": {"generate": {"kind": "flat", "nx": 64, "nz": 64, "cell_m": 0.25,
                                 "soil_m": GROUND_M, "sand_m": 0.0}},
        # Every room of exact bodies needs one thing made of cells to size
        # itself by, and it is kept well out of the way.
        "bodies": [_box("marker", "concrete", (0.15, 0.15, 0.15), (7.0, GROUND_M + 0.075, -7.0), anchored=True)],
        "precise_rigid_bodies": [], "joints": [],
    }
    if day:
        room["sun"] = {"day_s": float(day.get("day_s", 240.0)),
                       "noon_elevation_deg": float(day.get("noon_elevation_deg", 60.0)),
                       "hour": float(day.get("hour", 12.0)),
                       "irradiance_w_m2": float(day.get("irradiance_w_m2", 1000.0))}
    else:
        room["sun"] = dict(sun or NOON)
    for i, item in enumerate(items or ()):
        what = str(item.get("what") or "")
        if what not in THINGS:
            raise ValueError(f"nothing here is a {what!r}; the room can hold "
                             + ", ".join(sorted(THINGS)))
        at = item.get("at_m") or (0.0, 1.5)
        made = THINGS[what][1](str(item.get("name") or what), (float(at[0]), float(at[1])))
        for field, extra in made.items():
            room[field] = (room.get(field) or []) + extra
    return room


class Bench:
    """A room at the bench, open and stopped, with the thing in it.

    Nothing is stepped until `run` is called: time is frozen, which is what a
    bench is for.
    """

    def __init__(self, app: Any, *, sun: Any = None, day: Any = None, items: Any = ()):
        self._held = tempfile.TemporaryDirectory()
        root = Path(self._held.name)
        self.live = live_session.Live()
        self.room = world_room.Room("bench-test")
        self.room.spec = spec(sun=sun, day=day, items=items)
        self.room.inventory = inventory.Inventory()
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room,
                                   engine_path=getattr(app, "engine_path"),
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"),
                                   workshop_owner_id=getattr(app, "workshop_owner_id", "owner"))
        # Trying a thing costs nothing. The room keeps a rack of its own, thrown
        # away with the room, because a person must be able to find out whether
        # a design works before they have the material to make it -- being
        # refused a test for want of stock is backwards. Making it in the WORLD
        # spends the world's rack, and that gate is untouched.
        import workshop_library
        for material in workshop_library.MATERIALS if hasattr(workshop_library, "MATERIALS") else (
                "oak", "iron", "concrete", "glass", "aluminum", "rubber", "ice", "alumina ceramic"):
            try:
                workshop_library.set_rack(self.app, material, 1000.0)
            except Exception:       # a material this build does not carry
                pass
        self.live.open(self.app, {"spec": self.room.spec})
        self.t_s = 0.0
        self.made: dict[str, Any] | None = None

    def close(self) -> None:
        try:
            self.live.shutdown()
        finally:
            self._held.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
        return False

    def make(self, candidate: dict[str, Any], *, at_m=(0.0, 0.0)) -> dict[str, Any]:
        """Make the thing in the room -- the same call the world makes it with.

        Not a copy of the installer and not a simplified one: `workshop_install`
        itself, so the design is compiled by whichever compiler the world would
        choose, seated on the ground the way the world seats it, and its battery,
        motors and program declared the way the world declares them. That is the
        whole reason this answers for the world.
        """
        ctx = install.context(self.app, {})
        preview = install.preview(self.app, {"session": ctx["session"], "scene": self.room.scene,
                                             "mode": "authoring", "position_m": list(at_m),
                                             "candidate": candidate})
        self.made = install.commit(self.app, {"scene": self.room.scene, "session": ctx["session"],
                                              "preview_id": preview["preview_id"],
                                              "request_id": "bench-test-" + preview["preview_id"][:8]})
        return self.made

    def turn_on(self, name: str | None = None, *, power: bool = True) -> dict[str, Any]:
        """Set the thing's program running, as a person does from its panel."""
        said = self.reading()
        programs = said["programs"]
        if not programs:
            raise ValueError("nothing here has a program to turn on")
        which = next((p for p in programs if p["name"] == name), None) if name else programs[0]
        if which is None:
            raise ValueError(f"nothing here has a program called {name!r}")
        answer = self.live.session.send(op="run", program=which["id"], sender="bench",
                                        seq=int(self.t_s * 1000) + 1, power=bool(power))
        return answer.get("program") or {}

    def run(self, seconds: float) -> dict[str, Any]:
        """Let the room run, a quarter of a second at a time."""
        left = int(round(float(seconds) / DT))
        while left > 0:
            n = min(60, left)
            self.live.session.send(op="step", dt=DT, n=n)
            self.t_s += n * DT
            left -= n
        return self.reading()

    def reading(self) -> dict[str, Any]:
        """What the room says now: where everything is, and what its machines read."""
        reply = self.live.session.send(op="step", dt=DT, n=1)
        self.t_s += DT
        machines = reply.get("machines") or {}
        poses = self.live.session.send(op="poses")
        # A sun with a day says where it has got to; a fixed one is only what
        # the room declared, so say that rather than nothing.
        return {"schema": SCHEMA, "t_s": round(self.t_s, 4),
                "sun": poses.get("sun") or reply.get("sun") or dict(self.room.spec.get("sun") or {}),
                "bodies": {b["name"]: {"at_m": [round(v, 5) for v in b["position_m"]],
                                       "speed_m_s": round(math.dist(b.get("velocity_m_s") or [0, 0, 0],
                                                                    [0, 0, 0]), 5)}
                           for b in poses.get("bodies") or []},
                "stores": machines.get("stores") or [],
                "panels": machines.get("panels") or [],
                "controls": machines.get("controls") or [],
                "programs": machines.get("programs") or []}


def try_it(app: Any, candidate: dict[str, Any], *, seconds: float = 10.0, sun: Any = None, day: Any = None,
           items: Any = (), at_m=(0.0, 0.0), turn_on: bool = True) -> dict[str, Any]:
    """Make the thing in a little room, let it run, and say what happened.

    One call: open the room, install the design into it the way the world
    installs it, set any program of its own running, step it for `seconds`, and
    hand back what changed. The room is thrown away afterwards; the world is
    untouched throughout, because none of this is the world's session.
    """
    seconds = float(seconds)
    if not 0.0 < seconds <= 120.0:
        raise ValueError("a test runs for up to 120 seconds")
    with Bench(app, sun=sun, day=day, items=items) as room:
        made = room.make(candidate, at_m=at_m)
        began = room.reading()
        turned_on = None
        if turn_on and began["programs"]:
            turned_on = room.turn_on()
        ended = room.run(seconds)
        return {"schema": SCHEMA, "made": {k: made.get(k) for k in
                                           ("root_body", "root_bodies", "mass_kg", "cells", "design_id")},
                "ran_for_s": round(seconds, 3), "turned_on": bool(turned_on),
                "sky": ended["sun"], "in_the_room": [t["what"] for t in (items or ())] if items else [],
                "began": began, "ended": ended, "says": _says(made, began, ended)}


def _says(made: dict[str, Any], began: dict[str, Any], ended: dict[str, Any]) -> str:
    """What happened, in a sentence a person reads."""
    said = []
    deck = made.get("root_body")
    body = ended["bodies"].get(deck or "")
    if body:
        was = began["bodies"].get(deck or "", {}).get("at_m") or body["at_m"]
        went = math.dist(body["at_m"], was)
        said.append(f"it is {body['at_m'][1]:.2f} m up and has moved {went:.2f} m"
                    if went >= 0.01 else f"it stands where it was put, {body['at_m'][1]:.2f} m up")
    for store, before in zip(ended["stores"], began["stores"]):
        change = store["charge_j"] - before["charge_j"]
        said.append(f"{store['name']} went {before['charge_j']:.0f} -> {store['charge_j']:.0f} J"
                    if abs(change) >= 1.0 else f"{store['name']} holds {store['charge_j']:.0f} J still")
    for panel in ended["panels"]:
        said.append(f"{panel['name']} is giving {panel['power_w']:.1f} W")
    for program in ended["programs"]:
        said.append(f"{program['name']} is {program['doing']}: {program['why']}")
    return "; ".join(said) or "nothing in it says anything"
