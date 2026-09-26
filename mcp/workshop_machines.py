"""What makes a product go: its stores, motors, panels, controls and program.

A Workshop design says what a thing is made of and how its parts are fastened.
This says what drives it.  The world already carries all of it -- a rover has a
battery, two motors, a solar panel, two water eyes and a program that roams --
but only a hand-written room file could ever declare them, so a machine could
be run and never made.

Everything here is named by COMPONENT, because that is what a person is looking
at on the bench.  A motor names the two components its pin joins, exactly as
the room names a motor by the two things its pin joins; the installer turns
those into the bodies the compiler made (``installed`` below).  Nothing here
guesses: a motor on a joint that does not turn, or drawing on a store that is
not there, is refused by name rather than invented.

A program can carry what the room's rover carries: its SENSORS (a water eye at
a point on a component, in the design's own metres) and its ROUTINE (what it
does on its own: docs/machine-world.md, "A machine's senses and its tools" --
its kind, its hopper, what a scoop costs; the places it works between are the
room's, given when it is installed).  A panel says where on its component it
lies and which way it faces, or the installer takes the component's top.
"""
from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

MACHINES_KEY = "@machines"
SCHEMA = "banjo.workshop-machines.v1"
# The room's program kinds: "roam" is the one there is (playground/fracture_lab
# PROGRAM_KINDS); a "drive" program was allowed here and refused at the door.
PROGRAM_KINDS = ("roam",)
SENSOR_KINDS = ("water",)
ROUTINE_KINDS = ("dig", "roam")
MAX_EACH = 32


def _name(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 120:
        raise ValueError(f"{what} needs a name of 1 to 120 characters")
    return text


def _number(value: Any, what: str, low: float, high: float, default: Any = None) -> float:
    if value is None and default is not None:
        value = default
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number") from None
    if not isfinite(out) or not low <= out <= high:
        raise ValueError(f"{what} must be between {low:g} and {high:g}")
    return out


def _pair(value: Any, what: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{what} names the two components its pin joins")
    a, b = _name(value[0], what), _name(value[1], what)
    if a == b:
        raise ValueError(f"{what} names the same component twice; a pin joins two things")
    return [a, b]


def _rows(value: Any, what: str) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > MAX_EACH:
        raise ValueError(f"{what} must be a list of at most {MAX_EACH}")
    for row in value:
        if not isinstance(row, dict):
            raise ValueError(f"each of {what} is an object")
    return list(value)


def checked(value: Any) -> dict[str, Any]:
    """The declaration as written, with its shape and its numbers checked.

    Whether the components and joints it names actually exist is a question
    about a design, not about this record, and is asked by ``concepts``.
    """
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("machines must be an object")
    unknown = set(value) - {"schema", "stores", "motors", "panels", "controls", "programs"}
    if unknown:
        raise ValueError("unknown machine field(s): " + ", ".join(sorted(unknown)))

    out: dict[str, Any] = {"schema": SCHEMA}

    out["stores"] = [{
        "name": _name(row.get("name"), "a store"),
        "in": _name(row.get("in"), "a store's component"),
        "capacity_j": _number(row.get("capacity_j"), "capacity_j", 1.0, 1e12),
        "charge_j": _number(row.get("charge_j"), "charge_j", 0.0, 1e12, default=0.0),
        "voltage_v": _number(row.get("voltage_v"), "voltage_v", 0.1, 1e5, default=24.0),
    } for row in _rows(value.get("stores"), "stores")]
    for store in out["stores"]:
        if store["charge_j"] > store["capacity_j"]:
            raise ValueError(f"{store['name']} holds more than it can: "
                             f"{store['charge_j']:g} J in a {store['capacity_j']:g} J store")

    out["motors"] = [{
        "name": _name(row.get("name") or "motor", "a motor"),
        "turns": _pair(row.get("turns"), "a motor"),
        "store": _name(row.get("store"), "a motor's store"),
        "stall_torque_n_m": _number(row.get("stall_torque_n_m"), "stall_torque_n_m", 0.001, 1e6),
        "no_load_rpm": _number(row.get("no_load_rpm"), "no_load_rpm", 0.01, 1e5),
        "brake_torque_n_m": _number(row.get("brake_torque_n_m"), "brake_torque_n_m", 0.0, 1e6, default=0.0),
    } for row in _rows(value.get("motors"), "motors")]

    out["panels"] = [{
        "name": _name(row.get("name") or "solar panel", "a panel"),
        "on": _name(row.get("on"), "a panel's component"),
        "store": _name(row.get("store"), "a panel's store"),
        "area_m2": _number(row.get("area_m2"), "area_m2", 1e-4, 1e4),
        "efficiency": _number(row.get("efficiency"), "efficiency", 0.001, 1.0, default=0.2),
        # Where on its component it lies and which way it faces, in the
        # design's frame; left out, the installer takes the component's top.
        **({"at_m": _three(row.get("at_m"), "a panel's at_m")} if row.get("at_m") is not None else {}),
        **({"normal": _three(row.get("normal"), "a panel's normal")} if row.get("normal") is not None else {}),
    } for row in _rows(value.get("panels"), "panels")]

    out["controls"] = [{
        "name": _name(row.get("name"), "a control"),
        "turns": _pair(row.get("turns"), "a control"),
    } for row in _rows(value.get("controls"), "controls")]

    programs = _rows(value.get("programs"), "programs")
    if len(programs) > 1:
        raise ValueError("a product runs one program")
    out["programs"] = []
    for row in programs:
        kind = str(row.get("kind") or "").strip()
        if kind not in PROGRAM_KINDS:
            raise ValueError("a program's kind is " + " or ".join(PROGRAM_KINDS))
        program = {"kind": kind,
                   "left": _name(row.get("left"), "a program's left control"),
                   "right": _name(row.get("right"), "a program's right control"),
                   "setting": _number(row.get("setting"), "setting", 0.0, 1.0, default=1.0)}
        if row.get("climb_deg") is not None:
            program["climb_deg"] = _number(row.get("climb_deg"), "climb_deg", 0.0, 89.0)
        if row.get("rest_below") is not None:
            program["rest_below"] = _number(row.get("rest_below"), "rest_below", 0.0, 1.0)
        if row.get("rest_until") is not None:
            program["rest_until"] = _number(row.get("rest_until"), "rest_until", 0.0, 1.0)
        if program.get("rest_below") is not None and program.get("rest_until") is not None \
                and program["rest_until"] < program["rest_below"]:
            raise ValueError("a machine rests until it holds MORE than it rested at")
        if program.get("rest_until") is not None and program.get("rest_below") is None:
            raise ValueError("rest_until says when it sets off again; it needs rest_below to say when it stops")
        sensors = _rows(row.get("sensors"), "a program's sensors")
        if len(sensors) > 8:
            raise ValueError("a program reads at most 8 sensors")
        if sensors:
            program["sensors"] = [{
                "kind": _kind(s.get("kind") or "water", SENSOR_KINDS, "a sensor"),
                "on": _name(s.get("on"), "a sensor's component"),
                "at_m": _three(s.get("at_m"), "a sensor's at_m"),
                "depth_m": _number(s.get("depth_m"), "a sensor's depth_m", 0.001, 10.0, default=0.003),
            } for s in sensors]
        if row.get("routine") is not None:
            program["routine"] = _routine(row["routine"])
        out["programs"].append(program)

    return {k: v for k, v in out.items() if v or k == "schema"}


def _three(value: Any, what: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{what} is three numbers")
    out = [float(v) for v in value]
    if not all(isfinite(v) for v in out):
        raise ValueError(f"{what} must be finite")
    return out


def _kind(value: Any, kinds: tuple[str, ...], what: str) -> str:
    kind = str(value or "").strip()
    if kind not in kinds:
        raise ValueError(f"{what}'s kind is " + " or ".join(kinds))
    return kind


def _routine(value: Any) -> dict[str, Any]:
    """What a machine does on its own, as far as a design can say it: its
    kind, its hopper and what a scoop costs. The places it works between are
    the room's, given when it is installed."""
    if not isinstance(value, dict):
        raise ValueError("a routine is an object: kind, hopper_kg, work_j_per_kg")
    unknown = set(value) - {"kind", "hopper_kg", "work_j_per_kg", "places"}
    if unknown:
        raise ValueError("a routine cannot say " + ", ".join(sorted(unknown)))
    out: dict[str, Any] = {"kind": _kind(value.get("kind") or "roam", ROUTINE_KINDS, "a routine")}
    if out["kind"] == "dig" and not value.get("hopper_kg"):
        raise ValueError("a dig routine needs a hopper: hopper_kg above 0")
    if value.get("hopper_kg") is not None:
        out["hopper_kg"] = _number(value.get("hopper_kg"), "hopper_kg", 0.1, 1000.0)
    if value.get("work_j_per_kg") is not None:
        out["work_j_per_kg"] = _number(value.get("work_j_per_kg"), "work_j_per_kg", 0.0, 10000.0)
    if value.get("places") is not None:
        places = value["places"]
        if not isinstance(places, dict) or len(places) > 16:
            raise ValueError("a routine's places map at most 16 names to [x, z]")
        out["places"] = {}
        for name, xz in places.items():
            if not isinstance(xz, (list, tuple)) or len(xz) != 2:
                raise ValueError(f"the place {name!r} is [x, z] in the room's metres")
            out["places"][_name(name, "a place")] = [_number(xz[0], "x", -1000.0, 1000.0),
                                                     _number(xz[1], "z", -1000.0, 1000.0)]
    return out


def of_overrides(overrides: Any) -> dict[str, Any]:
    if not isinstance(overrides, dict):
        return {}
    return deepcopy(overrides.get(MACHINES_KEY) or {})


def of(design: Any) -> dict[str, Any]:
    return of_overrides((getattr(design, "lineage", None) or {}).get("component_overrides"))


def described(design: Any) -> dict[str, Any]:
    record = of(design)
    if not record:
        return {"schema": SCHEMA, "stores": [], "motors": [], "panels": [],
                "controls": [], "programs": [], "says": "nothing drives it"}
    parts = []
    for key, word in (("stores", "store"), ("motors", "motor"), ("panels", "panel"),
                      ("controls", "control")):
        count = len(record.get(key) or [])
        if count:
            parts.append(f"{count} {word}{'' if count == 1 else 's'}")
    if record.get("programs"):
        program = record["programs"][0]
        words = "a " + program["kind"] + " program"
        eyes = len(program.get("sensors") or [])
        if eyes:
            words += f" with {eyes} water eye{'' if eyes == 1 else 's'}"
        if program.get("routine"):
            routine = program["routine"]
            words += f" and a {routine['kind']} routine"
            if routine.get("hopper_kg"):
                words += f" ({routine['hopper_kg']:g} kg hopper)"
        parts.append(words)
    return {**record, "says": ", ".join(parts) if parts else "nothing drives it"}


def installed(design: Any, component_to_body: dict[str, str], frame: Any = None,
              places: dict[str, Any] | None = None) -> dict[str, Any]:
    """The room's own ``machines`` block for a design that has been compiled.

    A motor names its pin by the two things the pin joins, so the components it
    was declared against become the bodies the compiler made. A store or a panel
    sits on whichever body its component ended up in. A program's chassis is
    the component both its wheels' pins share. Points -- a sensor's, a panel's
    -- are carried from the design's frame into the room's by ``frame``, a
    pair (point, direction) of callables taking design-frame metres and
    returning room metres and room directions; without one, they are taken as
    they are. ``places`` are the routine's, in the room's metres.
    """
    record = of(design)
    if not record:
        return {}

    def body(component: str, what: str) -> str:
        found = component_to_body.get(component)
        if not found:
            raise ValueError(f"{what} names {component!r}, which is not a component of this design")
        return found

    to_room = frame[0] if frame else (lambda p: list(p))
    to_direction = frame[1] if frame else (lambda d: list(d))
    parts = {p.name: p for p in getattr(design, "parts", [])}

    def top_of(component: str) -> tuple[list[float], list[float]]:
        """A component's top face: its centre, and up."""
        part = parts.get(component)
        if part is None:
            return [0.0, 0.0, 0.0], [0.0, 1.0, 0.0]
        corners = part.corners_m()
        top = max(c[1] for c in corners)
        centre = [float(part.center_m[0]), float(top), float(part.center_m[2])]
        return centre, [0.0, 1.0, 0.0]

    out: dict[str, Any] = {}
    if record.get("stores"):
        out["stores"] = [{"name": s["name"], "body": body(s["in"], "a store"),
                          "capacity_j": s["capacity_j"], "charge_j": s["charge_j"],
                          "voltage_v": s["voltage_v"]} for s in record["stores"]]
    if record.get("motors"):
        out["motors"] = [{"on": [body(m["turns"][0], "a motor"), body(m["turns"][1], "a motor")],
                          "store": m["store"], "stall_torque_n_m": m["stall_torque_n_m"],
                          "no_load_rpm": m["no_load_rpm"],
                          "brake_torque_n_m": m["brake_torque_n_m"]} for m in record["motors"]]
    if record.get("panels"):
        out["panels"] = []
        for p in record["panels"]:
            at, normal = top_of(p["on"])
            at = p.get("at_m") or at
            normal = p.get("normal") or normal
            out["panels"].append({"name": p["name"], "body": body(p["on"], "a panel"), "store": p["store"],
                                  "at_mm": [round(1000.0 * v, 1) for v in to_room(at)],
                                  "normal": [round(float(v), 9) for v in to_direction(normal)],
                                  "area_m2": p["area_m2"], "efficiency": p["efficiency"]})
    if record.get("controls"):
        out["controls"] = [{"name": c["name"],
                            "on": [body(c["turns"][0], "a control"), body(c["turns"][1], "a control")]}
                           for c in record["controls"]]
    if record.get("programs"):
        program = dict(record["programs"][0])
        controls = {c["name"]: c for c in record.get("controls") or []}
        left, right = controls.get(program["left"]), controls.get(program["right"])
        # Its chassis: the body both wheels' pins turn on -- the mounts are
        # components of their own, but one body with the deck.
        shared = ({body(c, "a control") for c in left["turns"]} & {body(c, "a control") for c in right["turns"]}
                  if left and right else set())
        if len(shared) != 1:
            raise ValueError("a program's chassis is the one body both its wheels' pins turn on; "
                             f"{program['left']!r} and {program['right']!r} share "
                             + (", ".join(sorted(shared)) if shared else "nothing"))
        chassis = next(iter(shared))
        made: dict[str, Any] = {k: v for k, v in program.items() if k not in ("sensors", "routine")}
        # Named as the person knows it: the design's kind ("rover"), not the
        # bench's candidate id ("rover-g1-v1"); the installer keeps names apart.
        made["name"] = program.get("name") or getattr(design, "kind", None) or design.design_id
        made["body"] = chassis
        if program.get("sensors"):
            made["sensors"] = [{"kind": s["kind"], "body": body(s["on"], "a sensor"),
                                "at_mm": [round(1000.0 * v, 1) for v in to_room(s["at_m"])],
                                "depth_mm": round(1000.0 * s["depth_m"], 3)} for s in program["sensors"]]
        if program.get("routine"):
            routine = dict(program["routine"])
            if places:
                routine["places"] = {str(k): [float(v[0]), float(v[1])] for k, v in places.items()}
            made["routine"] = routine
        out["programs"] = [made]
    return out
