"""Wireframe-first workshop design helpers.

The workshop is deliberately separate from the running Banjo world.  It works
with cheap, inspectable design descriptions, component families and candidate
variants.  Nothing in this module advances physics or mutates a live world.

A design is materialized only after the player/agent chooses a candidate.
Materialization snaps every solid to the requested cell grid and returns a
plain object plan that the existing Banjo authoring layer can consume later.

This module is the ONLY place workshop designs exist.  The page renders what
``wireframe()`` returns and decides nothing about geometry itself; see
``playground/workshop_api.py`` and ``docs/workshop-next.md`` stage 1.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from itertools import product
from json import dumps
from math import acos, atan2, cos, degrees, hypot, isfinite, radians, sin, sqrt, tan
from typing import Any, Callable, Iterable

from mcp import engine_materials


WORKSHOP_SCHEMA = "banjo.workshop.v1"

# Density only, in kg/m3, so a design can report an honest mass and centre of
# mass.  A density is NOT a constitutive model: nothing here claims how these
# materials break, bend or conduct.  Those come from the engine's own catalogue
# when a candidate reaches a scratch trial (docs/workshop-next.md stage 6).
#
# A material the engine has a preset for weighs what the engine's catalogue
# says (mcp/engine_materials.py, which the parity test pins to
# MaterialCatalog.cpp).  This table used to keep its own oak (750) and rubber
# (1200) until something called engine_materials.synchronize_workshop_model(),
# so one oak table weighed 102.0 kg or 95.2 kg depending on which modules the
# process happened to import first.  pine and steel have no engine preset; they
# stay for old saved designs and are display-only.
DENSITY_KG_M3 = {
    "oak": engine_materials.density("oak"),
    "pine": 500.0,
    "iron": engine_materials.density("iron"),
    "steel": 7850.0,
    "aluminium": engine_materials.density("aluminium"),
    "glass": engine_materials.density("glass"),
    "concrete": engine_materials.density("concrete"),
    "rubber": engine_materials.density("rubber"),
    "alumina ceramic": engine_materials.density("alumina ceramic"),
}

_ON_THE_FLOOR_M = 0.002  # a part this close to the lowest point is standing on it


def _positive(name: str, value: float) -> float:
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def _finite3(name: str, value: Iterable[float]) -> tuple[float, float, float]:
    out = tuple(float(x) for x in value)
    if len(out) != 3 or not all(isfinite(x) for x in out):
        raise ValueError(f"{name} must be three finite numbers")
    return out  # type: ignore[return-value]


def _snap(value: float, cell: float) -> float:
    return max(cell, round(float(value) / cell) * cell)


def _snap_at(value: float, cell: float) -> float:
    return round(float(value) / cell) * cell


def rotation_onto(direction: Iterable[float]) -> tuple[float, float, float]:
    """Euler degrees taking a part's local +y onto ``direction``.

    The angles are Banjo's own convention -- the rotation is built z first, so
    the matrix is Rx.Ry.Rz -- which is also three.js's default ``Euler`` order,
    so the page can apply the same three numbers without a second convention.
    Only two of the three are needed to aim one axis, so the x angle is zero and
    the remaining spin about the member's own length is left free.
    """
    x, y, z = _finite3("direction", direction)
    length = sqrt(x * x + y * y + z * z)
    if length <= 0:
        raise ValueError("direction must not be zero length")
    x, y, z = x / length, y / length, z / length
    across = hypot(x, z)
    tilt = degrees(acos(max(-1.0, min(1.0, y))))
    if across < 1e-12:
        return (0.0, 0.0, 0.0 if y >= 0 else 180.0)
    return (0.0, degrees(atan2(z, -x)), tilt)


@dataclass(frozen=True)
class WirePart:
    """One cheap design member.

    ``role`` is semantic and survives materialization.  ``shape`` is a hint for
    the renderer and for a later voxel compiler: a ``tapered`` member still
    occupies the box that ``size_m`` describes, so every measurement here holds
    whatever the shape.
    """

    name: str
    role: str
    size_m: tuple[float, float, float]
    center_m: tuple[float, float, float]
    material: str = "oak"
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    shape: str = "box"
    family: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.role:
            raise ValueError("wire parts need a name and a role")
        for i, value in enumerate(self.size_m):
            _positive(f"size_m[{i}]", value)
        _finite3("center_m", self.center_m)
        _finite3("rotation_deg", self.rotation_deg)
        if self.shape not in {"box", "tapered", "cylinder"}:
            raise ValueError("shape must be box, tapered or cylinder")

    def volume_m3(self) -> float:
        w, h, d = self.size_m
        # A tapered member is a frustum; the mean cross-section is what it
        # displaces.  A cylinder inscribes the box.
        if self.shape == "tapered":
            return w * h * d * 0.72
        if self.shape == "cylinder":
            return w * h * d * 0.7854
        return w * h * d

    def mass_kg(self) -> float:
        return self.volume_m3() * DENSITY_KG_M3.get(self.material, DENSITY_KG_M3["oak"])

    def ends_m(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Where the member's own length axis begins and ends, in world metres."""
        half = self.size_m[1] / 2
        ax, ay, az = _axis_of(self.rotation_deg)
        cx, cy, cz = self.center_m
        return ((cx - ax * half, cy - ay * half, cz - az * half),
                (cx + ax * half, cy + ay * half, cz + az * half))

    def corners_m(self) -> list[tuple[float, float, float]]:
        """The member's eight box corners in world metres, its rotation included.

        A member that stands on the ground touches it over a FACE, not at a
        point: a cabinet side is held up by a rectangle. Measuring from corners
        is what lets the support polygon be right for panels as well as legs.
        """
        w, h, d = self.size_m
        cx, cy, cz = self.center_m
        out = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    ox, oy, oz = _rotate(self.rotation_deg,
                                         (sx * w / 2, sy * h / 2, sz * d / 2))
                    out.append((cx + ox, cy + oy, cz + oz))
        return out

    def lowest_m(self) -> float:
        """The lowest point the member reaches, its tilt included."""
        return min(c[1] for c in self.corners_m())

    def highest_end_m(self) -> tuple[float, float, float]:
        """Whichever end of the member's length axis is the higher."""
        low, high = self.ends_m()
        return high if high[1] >= low[1] else low

    def ground_contacts_m(self) -> list[tuple[float, float]]:
        """Where this member meets the ground, as xz points.

        A tilted leg is not balanced on one corner: its foot is cut flat so it
        stands, so the contact is the end face. A roller lying on its side --
        a wheel -- touches along a line under its own axis instead.
        """
        axis = _axis_of(self.rotation_deg)
        w, h, d = self.size_m
        cx, cy, cz = self.center_m
        if self.shape == "cylinder" and abs(axis[1]) < 0.3:
            half = h / 2
            return [(cx - axis[0] * half, cz - axis[2] * half),
                    (cx + axis[0] * half, cz + axis[2] * half)]
        low = -1 if axis[1] >= 0 else 1
        out = []
        for sx in (-1, 1):
            for sz in (-1, 1):
                ox, _, oz = _rotate(self.rotation_deg, (sx * w / 2, low * h / 2, sz * d / 2))
                out.append((cx + ox, cz + oz))
        return out


def _rotate(rotation_deg: Iterable[float],
            v: tuple[float, float, float]) -> tuple[float, float, float]:
    """Apply Banjo's rotation -- built z first, so Rx.Ry.Rz -- to a vector."""
    ax, ay, az = (radians(a) for a in rotation_deg)
    x, y, z = v
    x, y = x * cos(az) - y * sin(az), x * sin(az) + y * cos(az)
    x, z = x * cos(ay) + z * sin(ay), -x * sin(ay) + z * cos(ay)
    y, z = y * cos(ax) - z * sin(ax), y * sin(ax) + z * cos(ax)
    return (x, y, z)


def _axis_of(rotation_deg: Iterable[float]) -> tuple[float, float, float]:
    """The world direction of a part's local +y under Rx.Ry.Rz."""
    return _rotate(rotation_deg, (0.0, 1.0, 0.0))


def strut(*, name: str, role: str, from_m: Iterable[float], to_m: Iterable[float],
          section_m: tuple[float, float], material: str = "oak",
          shape: str = "box", family: str | None = None) -> WirePart:
    """A member spanning two points, which derives its own length and rotation.

    This is the library's primitive.  Legs, stretchers, posts, beams and braces
    are all struts, so a splayed leg is described by where its foot and its head
    actually are rather than by a rotation applied to an upright box -- which is
    what let the splay run the wrong way and the footprint be measured from the
    leg centres (docs/workshop-next.md stage 0).
    """
    a = _finite3("from_m", from_m)
    b = _finite3("to_m", to_m)
    span = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    length = sqrt(sum(v * v for v in span))
    if length <= 0:
        raise ValueError(f"{name}: a strut needs two different points")
    width = _positive("section width", section_m[0])
    depth = _positive("section depth", section_m[1])
    return WirePart(
        name=name, role=role,
        size_m=(width, length, depth),
        center_m=((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2),
        material=material, rotation_deg=rotation_onto(span), shape=shape, family=family)


@dataclass(frozen=True)
class Parameter:
    """One knob a family offers, with its unit and its bounds."""

    name: str
    unit: str
    default: Any
    low: float | None = None
    high: float | None = None
    choices: tuple[str, ...] | None = None
    about: str = ""

    def check(self, value: Any) -> Any:
        if self.choices is not None:
            if value not in self.choices:
                raise ValueError(f"{self.name} must be one of {', '.join(self.choices)}")
            return value
        number = float(value)
        if not isfinite(number):
            raise ValueError(f"{self.name} must be a finite number")
        if self.low is not None and number < self.low:
            raise ValueError(f"{self.name} must be at least {self.low} {self.unit}")
        if self.high is not None and number > self.high:
            raise ValueError(f"{self.name} must be at most {self.high} {self.unit}")
        return number

    def described(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "unit": self.unit,
                               "default": self.default, "about": self.about}
        if self.choices is not None:
            out["choices"] = list(self.choices)
        else:
            out["low"], out["high"] = self.low, self.high
        return out


@dataclass(frozen=True)
class Component:
    """What a family made: its parts, and the anchors other families attach to."""

    parts: list[WirePart]
    anchors: dict[str, tuple[float, float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Family:
    name: str
    role: str
    about: str
    parameters: tuple[Parameter, ...]
    build: Callable[..., Component]
    offers: tuple[str, ...] = ()

    def defaults(self) -> dict[str, Any]:
        return {p.name: p.default for p in self.parameters}

    def checked(self, given: dict[str, Any] | None) -> dict[str, Any]:
        known = {p.name: p for p in self.parameters}
        values = self.defaults()
        for key, value in (given or {}).items():
            if key not in known:
                raise KeyError(f"{self.name} has no parameter {key!r}; "
                               f"it takes {', '.join(sorted(known))}")
            values[key] = known[key].check(value)
        return values

    def described(self) -> dict[str, Any]:
        return {"family": self.name, "role": self.role, "about": self.about,
                "offers": list(self.offers),
                "parameters": [p.described() for p in self.parameters]}


# ---------------------------------------------------------------------------
# Component families
#
# Each family returns a Component: the parts it made, and the anchors other
# families attach to.  An assembly composes families by anchor, so a family can
# be added without touching an assembly and the other way round
# (docs/workshop-next.md stage 2).
# ---------------------------------------------------------------------------


#: A leg asked to splay with no angle given splays this far. Without it,
#: choosing "splayed" and leaving the angle alone builds a straight leg, and a
#: whole row of candidates comes out identical.
DEFAULT_SPLAY_DEG = 6.0


def _splay_of(style: str, splay_deg: float) -> float:
    if style == "straight":
        return 0.0
    return float(splay_deg) if float(splay_deg) > 0 else DEFAULT_SPLAY_DEG


def _leg(*, name: str, at_m: Iterable[float], material: str, height_m: float,
         width_m: float, depth_m: float, style: str, splay_deg: float,
         lean_x: float, lean_z: float) -> Component:
    foot = _finite3("at_m", at_m)
    splay = _splay_of(style, splay_deg)
    reach = height_m * tan(radians(splay))
    lean = hypot(lean_x, lean_z)
    if lean > 0:
        lean_x, lean_z = lean_x / lean, lean_z / lean
    head = (foot[0] - lean_x * reach, foot[1] + height_m, foot[2] - lean_z * reach)
    part = strut(name=name, role="leg", from_m=foot, to_m=head,
                 section_m=(width_m, depth_m), material=material,
                 shape="tapered" if style == "tapered" else "box", family="leg")
    return Component(parts=[part], anchors={"foot": foot, "head": head})


def _surface(*, name: str, at_m: Iterable[float], material: str, width_m: float,
             thickness_m: float, depth_m: float, profile: str) -> Component:
    top = _finite3("at_m", at_m)
    centre = (top[0], top[1] - thickness_m / 2, top[2])
    part = WirePart(name=name, role="top", size_m=(width_m, thickness_m, depth_m),
                    center_m=centre, material=material,
                    shape="cylinder" if profile == "round" else "box", family="surface")
    under = top[1] - thickness_m
    half_w, half_d = width_m / 2, depth_m / 2
    corners = [(-half_w, -half_d), (half_w, -half_d), (half_w, half_d), (-half_w, half_d)]
    anchors = {"under_%d" % i: (top[0] + dx, under, top[2] + dz)
               for i, (dx, dz) in enumerate(corners, 1)}
    anchors["under_centre"] = (top[0], under, top[2])
    anchors["top_centre"] = top
    return Component(parts=[part], anchors=anchors)


def _spanning(role, family, shape="box"):
    """A family that simply spans two points: stretchers, beams, braces, aprons."""

    def build(*, name: str, from_m: Iterable[float], to_m: Iterable[float],
              material: str, width_m: float, depth_m: float) -> Component:
        part = strut(name=name, role=role, from_m=from_m, to_m=to_m,
                     section_m=(width_m, depth_m), material=material,
                     shape=shape, family=family)
        a, b = part.ends_m()
        return Component(parts=[part],
                         anchors={"start": a, "end": b, "middle": part.center_m})

    return build


def _panel(*, name: str, at_m: Iterable[float], material: str, width_m: float,
           height_m: float, thickness_m: float, facing: str) -> Component:
    at = _finite3("at_m", at_m)
    size = (thickness_m, height_m, width_m) if facing == "x" else (width_m, height_m, thickness_m)
    part = WirePart(name=name, role="panel", size_m=size, center_m=at,
                    material=material, family="panel")
    return Component(parts=[part], anchors={"centre": at})


def _wheel(*, name: str, at_m: Iterable[float], material: str, diameter_m: float,
           width_m: float) -> Component:
    at = _finite3("at_m", at_m)
    # A wheel turns on an axle that lies along x, so its local +y -- the disc's
    # own axis -- is turned onto x and the disc stands up.
    part = WirePart(name=name, role="wheel", size_m=(diameter_m, width_m, diameter_m),
                    center_m=at, material=material,
                    rotation_deg=rotation_onto((1.0, 0.0, 0.0)),
                    shape="cylinder", family="wheel")
    return Component(parts=[part], anchors={"hub": at})


# ---------------------------------------------------------------------------
# A machine's components (docs/machine-world.md, "The Workshop's robot parts"):
# what a robot is put together from, each a component the bench chat can
# search, place and fasten -- a bearing mount, a driven wheel on its stub, a
# caster, a battery, a solar panel, a hopper. Every one is the rover's own, as
# tools/build_rover_room.py hand-writes it, so a machine assembled from them
# is the machine the room has run since September 22.
# ---------------------------------------------------------------------------

def _mount(*, name: str, at_m: Iterable[float], material: str, section_m: float,
           height_m: float) -> Component:
    """A bearing mount: a block hung under a deck, a shaft through it."""
    at = _finite3("at_m", at_m)
    part = WirePart(name=name, role="bearing_mount", size_m=(section_m, height_m, section_m),
                    center_m=at, material=material, family="mount")
    return Component(parts=[part], anchors={"centre": at, "top": (at[0], at[1] + height_m / 2, at[2]),
                                            "bottom": (at[0], at[1] - height_m / 2, at[2])})


def _drive_wheel(*, name: str, at_m: Iterable[float], material: str, diameter_m: float,
                 width_m: float, stub_diameter_m: float, stub_length_m: float, side: float) -> Component:
    """A driven wheel on its own short iron stub, which turns in a mount:
    the stub reaches inward from the wheel's hub, along x, `side` +1 for the
    machine's left (+x) and -1 for its right. A motor goes on the pair mount
    and stub; the wheel is fixed to the stub."""
    at = _finite3("at_m", at_m)
    s = 1.0 if float(side) >= 0 else -1.0
    stub_centre = (at[0] - s * (width_m / 2 + stub_length_m / 2 - 0.02), at[1], at[2])
    stub = WirePart(name=f"{name} stub", role="axle", size_m=(stub_diameter_m, stub_length_m, stub_diameter_m),
                    center_m=stub_centre, material="iron", rotation_deg=rotation_onto((1.0, 0.0, 0.0)),
                    shape="cylinder", family="drive-wheel")
    wheel = WirePart(name=name, role="wheel", size_m=(diameter_m, width_m, diameter_m), center_m=at,
                     material=material, rotation_deg=rotation_onto((1.0, 0.0, 0.0)), shape="cylinder",
                     family="drive-wheel")
    return Component(parts=[stub, wheel], anchors={"hub": at, "stub_centre": stub_centre})


def _caster(*, name: str, at_m: Iterable[float], material: str, diameter_m: float,
            width_m: float, trail_m: float) -> Component:
    """A caster: a swivel pin standing up into a mount, a plate under the
    mount, two cheeks down from the plate, a pin across them, and a wheel on
    the pin, trailing `trail_m` behind the swivel's axis so it swings round to
    follow. `at_m` is the swivel's axis at the plate's top; the wheel's
    material is `material`, the rest iron (a light caster wheel sank into the
    ground under a heavy machine: tools/build_rover_room.py)."""
    x, y, z = _finite3("at_m", at_m)
    r = diameter_m / 2
    swivel = WirePart(name=f"{name} swivel", role="axle", size_m=(0.02, 0.06, 0.02), center_m=(x, y + 0.02, z),
                      material="iron", shape="cylinder", family="caster")
    plate = WirePart(name=f"{name} plate", role="post", size_m=(0.08, 0.02, 0.08), center_m=(x, y - 0.01, z),
                     material="iron", family="caster")
    cheek_h = y - 0.02 - r
    cheeks = [WirePart(name=f"{name} {side} cheek", role="post", size_m=(0.012, cheek_h, 0.05),
                       center_m=(x + sx * 0.035, y - 0.02 - cheek_h / 2, z - trail_m + 0.015),
                       material="iron", family="caster")
              for side, sx in (("left", 1.0), ("right", -1.0))]
    pin = WirePart(name=f"{name} pin", role="axle", size_m=(0.012, 0.082, 0.012), center_m=(x, r, z - trail_m),
                   material="iron", rotation_deg=rotation_onto((1.0, 0.0, 0.0)), shape="cylinder", family="caster")
    wheel = WirePart(name=f"{name} wheel", role="wheel", size_m=(diameter_m, width_m, diameter_m),
                     center_m=(x, r, z - trail_m), material=material, rotation_deg=rotation_onto((1.0, 0.0, 0.0)),
                     shape="cylinder", family="caster")
    return Component(parts=[swivel, plate, *cheeks, pin, wheel],
                     anchors={"swivel_top": (x, y + 0.05, z), "hub": (x, r, z - trail_m)})


def _block(role: str, family: str):
    """A box that sits on something: a battery, a hopper."""
    def build(*, name: str, at_m: Iterable[float], material: str, width_m: float, height_m: float,
              depth_m: float) -> Component:
        bottom = _finite3("at_m", at_m)
        centre = (bottom[0], bottom[1] + height_m / 2, bottom[2])
        part = WirePart(name=name, role=role, size_m=(width_m, height_m, depth_m), center_m=centre,
                        material=material, family=family)
        return Component(parts=[part], anchors={"bottom": bottom, "top": (bottom[0], bottom[1] + height_m, bottom[2]),
                                                "centre": centre})
    return build


def _solar_panel(*, name: str, at_m: Iterable[float], material: str, width_m: float, depth_m: float,
                 thickness_m: float) -> Component:
    """A flat glass collector lying on a deck, facing up."""
    bottom = _finite3("at_m", at_m)
    centre = (bottom[0], bottom[1] + thickness_m / 2, bottom[2])
    part = WirePart(name=name, role="panel", size_m=(width_m, thickness_m, depth_m), center_m=centre,
                    material="glass", family="solar-panel")
    return Component(parts=[part], anchors={"bottom": bottom, "top": (bottom[0], bottom[1] + thickness_m, bottom[2])})


MACHINE_FAMILIES = (
    Family("mount", "bearing_mount", "A bearing mount: a block hung under a deck that a wheel's stub turns in.",
           (Parameter("section_m", "m", 0.0345, 0.02, 0.2), Parameter("height_m", "m", 0.18, 0.02, 0.6)),
           _mount, offers=("centre", "top", "bottom")),
    Family("drive-wheel", "wheel", "A driven wheel on its own short iron stub, which turns in a mount; a motor "
                                   "goes on the mount and the stub.",
           (Parameter("diameter_m", "m", 0.32, 0.05, 1.2), Parameter("width_m", "m", 0.06, 0.01, 0.4),
            Parameter("stub_diameter_m", "m", 0.03, 0.008, 0.1), Parameter("stub_length_m", "m", 0.20, 0.05, 0.6),
            Parameter("side", "", 1.0, -1.0, 1.0, about="+1 on the machine's left (+x), -1 on its right")),
           _drive_wheel, offers=("hub", "stub_centre")),
    Family("caster", "wheel", "A caster: a swivel pin up into a mount, a fork, and a trailing wheel that swings "
                              "round to follow.",
           (Parameter("diameter_m", "m", 0.16, 0.05, 0.6), Parameter("width_m", "m", 0.04, 0.01, 0.2),
            Parameter("trail_m", "m", 0.06, 0.0, 0.3)),
           _caster, offers=("swivel_top", "hub")),
    Family("battery", "post", "A battery: a box on the deck that holds joules (declare the store on it).",
           (Parameter("width_m", "m", 0.2, 0.05, 1.0), Parameter("height_m", "m", 0.06, 0.02, 0.5),
            Parameter("depth_m", "m", 0.18, 0.05, 1.0)),
           _block("post", "battery"), offers=("bottom", "top", "centre")),
    Family("solar-panel", "panel", "A flat glass collector on the deck, facing up (declare the panel on it).",
           (Parameter("width_m", "m", 0.4, 0.05, 2.0), Parameter("depth_m", "m", 0.4, 0.05, 2.0),
            Parameter("thickness_m", "m", 0.01, 0.004, 0.05)),
           _solar_panel, offers=("bottom", "top")),
    Family("hopper", "post", "A hopper: a bin on the deck that a dig routine fills (declare hopper_kg on the "
                             "routine).",
           (Parameter("width_m", "m", 0.3, 0.05, 1.5), Parameter("height_m", "m", 0.15, 0.03, 1.0),
            Parameter("depth_m", "m", 0.3, 0.05, 1.5)),
           _block("post", "hopper"), offers=("bottom", "top", "centre")),
)


LIBRARY_FAMILIES = (
    Family("leg", "leg",
           "A standing member. Straight, splayed out to a wider base, or tapered.",
           (Parameter("height_m", "m", 0.72, 0.05, 3.0, about="foot to head"),
            Parameter("width_m", "m", 0.06, 0.01, 0.4, about="section across x"),
            Parameter("depth_m", "m", 0.06, 0.01, 0.4, about="section across z"),
            Parameter("style", "", "straight", choices=("straight", "splayed", "tapered")),
            Parameter("splay_deg", "deg", 0.0, 0.0, 25.0,
                      about="how far the foot stands outside the head"),
            Parameter("lean_x", "", 1.0, -1.0, 1.0,
                      about="which way the foot leans; an assembly sets this per corner"),
            Parameter("lean_z", "", 0.0, -1.0, 1.0, about="the same across z")),
           _leg, offers=("foot", "head")),
    Family("surface", "top", "A flat slab: a table top, a seat, a shelf or a deck.",
           (Parameter("width_m", "m", 1.2, 0.1, 4.0),
            Parameter("thickness_m", "m", 0.04, 0.005, 0.3),
            Parameter("depth_m", "m", 0.7, 0.1, 4.0),
            Parameter("profile", "", "square", choices=("square", "round"))),
           _surface, offers=("under_1", "under_2", "under_3", "under_4",
                             "under_centre", "top_centre")),
    Family("apron", "apron", "A rail just under a top edge, joining two leg heads.",
           (Parameter("width_m", "m", 0.02, 0.005, 0.2),
            Parameter("depth_m", "m", 0.08, 0.01, 0.4)),
           _spanning("apron", "apron"), offers=("start", "end", "middle")),
    Family("stretcher", "stretcher",
           "A low rail between two legs, which stops a frame racking.",
           (Parameter("width_m", "m", 0.03, 0.005, 0.2),
            Parameter("depth_m", "m", 0.03, 0.005, 0.2)),
           _spanning("stretcher", "stretcher"), offers=("start", "end", "middle")),
    Family("beam", "beam", "A horizontal structural member.",
           (Parameter("width_m", "m", 0.06, 0.01, 0.5),
            Parameter("depth_m", "m", 0.06, 0.01, 0.5)),
           _spanning("beam", "beam"), offers=("start", "end", "middle")),
    Family("post", "post", "An upright structural member between two points.",
           (Parameter("width_m", "m", 0.05, 0.01, 0.5),
            Parameter("depth_m", "m", 0.05, 0.01, 0.5)),
           _spanning("post", "post"), offers=("start", "end", "middle")),
    Family("brace", "brace", "A diagonal member that triangulates a frame.",
           (Parameter("width_m", "m", 0.03, 0.005, 0.2),
            Parameter("depth_m", "m", 0.03, 0.005, 0.2)),
           _spanning("brace", "brace"), offers=("start", "end", "middle")),
    Family("panel", "panel", "A flat upright sheet: a chair back, a cabinet side.",
           (Parameter("width_m", "m", 0.4, 0.05, 3.0),
            Parameter("height_m", "m", 0.2, 0.02, 3.0),
            Parameter("thickness_m", "m", 0.02, 0.004, 0.2),
            Parameter("facing", "", "z", choices=("x", "z"))),
           _panel, offers=("centre",)),
    Family("axle", "axle", "A shaft two wheels turn on.",
           (Parameter("width_m", "m", 0.03, 0.005, 0.3),
            Parameter("depth_m", "m", 0.03, 0.005, 0.3)),
           _spanning("axle", "axle", shape="cylinder"), offers=("start", "end", "middle")),
    Family("wheel", "wheel", "A disc on an axle.",
           (Parameter("diameter_m", "m", 0.3, 0.02, 2.0),
            Parameter("width_m", "m", 0.05, 0.005, 0.5)),
           _wheel, offers=("hub",)),
    *MACHINE_FAMILIES,
    Family("handle", "handle", "A bar to pull or lift by.",
           (Parameter("width_m", "m", 0.03, 0.005, 0.2),
            Parameter("depth_m", "m", 0.03, 0.005, 0.2)),
           _spanning("handle", "handle", shape="cylinder"),
           offers=("start", "end", "middle")),
)


class ComponentLibrary:
    """The semantic component registry the workshop agent and page both read."""

    def __init__(self, families: Iterable[Family] = LIBRARY_FAMILIES) -> None:
        self._families: dict[str, Family] = {}
        for family in families:
            self.register(family)

    def register(self, family: Family) -> None:
        if not family.name:
            raise ValueError("component family needs a name")
        if family.name in self._families:
            raise ValueError("component family already exists: " + family.name)
        self._families[family.name] = family

    def families(self) -> tuple[str, ...]:
        return tuple(sorted(self._families))

    def family(self, name: str) -> Family:
        try:
            return self._families[name]
        except KeyError as exc:
            raise KeyError("unknown component family: " + str(name)) from exc

    def described(self) -> list[dict[str, Any]]:
        return [self._families[n].described() for n in self.families()]

    def make(self, family: str, *, name: str, material: str = "oak",
             parameters: dict[str, Any] | None = None, **where: Any) -> Component:
        chosen = self.family(family)
        values = chosen.checked(parameters)
        return chosen.build(name=name, material=material, **values, **where)


# ---------------------------------------------------------------------------
# Assemblies
#
# An assembly composes families by anchor.  It never does corner arithmetic for
# a family: it asks the surface where its underside corners are, decides where
# each leg's HEAD goes, and lets the leg family work out its own foot, length
# and rotation from its splay.
# ---------------------------------------------------------------------------


_CORNERS = ((-1, -1), (1, -1), (1, 1), (-1, 1))


def _legs_under(library: ComponentLibrary, *, corners: list[tuple[float, float, float]],
                leans: Iterable[tuple[float, float]], height_m: float, section_m: float,
                style: str, splay_deg: float, material: str,
                first: int = 1) -> tuple[list[WirePart], list[Component]]:
    """One leg per corner, each hung from its head and standing on its own foot."""
    made: list[Component] = []
    reach = height_m * tan(radians(_splay_of(style, splay_deg)))
    for i, (head, (lean_x, lean_z)) in enumerate(zip(corners, leans), first):
        # The leg family normalises its lean before it walks the foot outwards,
        # so this must too, or the head it rebuilds lands off the corner it was
        # hung from -- by 7 mm at 15 degrees, which put the leg off the top.
        norm = hypot(lean_x, lean_z) or 1.0
        unit_x, unit_z = lean_x / norm, lean_z / norm
        foot = (head[0] + unit_x * reach, head[1] - height_m, head[2] + unit_z * reach)
        made.append(library.make(
            "leg", name="leg-%d" % i, material=material, at_m=foot,
            parameters={"height_m": height_m, "width_m": section_m, "depth_m": section_m,
                        "style": style, "splay_deg": splay_deg,
                        "lean_x": float(lean_x), "lean_z": float(lean_z)}))
    return [p for c in made for p in c.parts], made


def _framed(*, width_m: float, depth_m: float, height_m: float, top_thickness_m: float,
            leg_section_m: float, leg_style: str, splay_deg: float, leg_inset_m: float,
            material: str, aprons: bool, stretchers: bool, top_profile: str,
            library: ComponentLibrary, top_name: str = "top") -> list[WirePart]:
    """A slab held up at four corners: the shape under a table, stool or bench."""
    surface = library.make("surface", name=top_name, material=material,
                           at_m=(0.0, height_m, 0.0),
                           parameters={"width_m": width_m, "thickness_m": top_thickness_m,
                                       "depth_m": depth_m, "profile": top_profile})
    inset = max(leg_section_m / 2, min(width_m / 4, depth_m / 4, leg_inset_m))
    heads, leans = [], []
    for i, (sx, sz) in enumerate(_CORNERS, 1):
        corner = surface.anchors["under_%d" % i]
        heads.append((corner[0] - sx * inset, corner[1], corner[2] - sz * inset))
        leans.append((float(sx), float(sz)))
    legs, made = _legs_under(library, corners=heads, leans=leans,
                             height_m=height_m - top_thickness_m, section_m=leg_section_m,
                             style=leg_style, splay_deg=splay_deg, material=material)
    parts = list(surface.parts) + legs
    if aprons:
        for i in range(4):
            a, b = made[i].anchors["head"], made[(i + 1) % 4].anchors["head"]
            parts.extend(library.make("apron", name="apron-%d" % (i + 1), material=material,
                                      from_m=a, to_m=b, parameters={}).parts)
    if stretchers:
        for i in range(4):
            a, b = made[i].anchors["foot"], made[(i + 1) % 4].anchors["foot"]
            low = 0.28 * (height_m - top_thickness_m)
            parts.extend(library.make(
                "stretcher", name="stretcher-%d" % (i + 1), material=material,
                from_m=(a[0], a[1] + low, a[2]), to_m=(b[0], b[1] + low, b[2]),
                parameters={}).parts)
    return parts


_FRAME_PARAMETERS = (
    Parameter("width_m", "m", 1.2, 0.2, 4.0, about="across x"),
    Parameter("depth_m", "m", 0.7, 0.2, 4.0, about="across z"),
    Parameter("height_m", "m", 0.76, 0.1, 2.0, about="to the upper surface"),
    Parameter("top_thickness_m", "m", 0.04, 0.005, 0.3),
    Parameter("top_profile", "", "square", choices=("square", "round")),
    Parameter("leg_section_m", "m", 0.06, 0.015, 0.3),
    Parameter("leg_style", "", "straight", choices=("straight", "splayed", "tapered")),
    Parameter("splay_deg", "deg", 0.0, 0.0, 25.0),
    Parameter("leg_inset_m", "m", 0.05, 0.0, 1.0, about="how far in from the corner"),
    Parameter("material", "", "oak", choices=tuple(sorted(DENSITY_KG_M3))),
    Parameter("aprons", "", 0.0, 0.0, 1.0, about="1 adds rails under the top"),
    Parameter("stretchers", "", 0.0, 0.0, 1.0, about="1 adds low rails between the legs"),
)


def _build_framed(library: ComponentLibrary, values: dict[str, Any],
                  top_name: str = "top") -> list[WirePart]:
    return _framed(width_m=values["width_m"], depth_m=values["depth_m"],
                   height_m=values["height_m"], top_thickness_m=values["top_thickness_m"],
                   leg_section_m=values["leg_section_m"], leg_style=values["leg_style"],
                   splay_deg=values["splay_deg"], leg_inset_m=values["leg_inset_m"],
                   material=values["material"], aprons=bool(values["aprons"]),
                   stretchers=bool(values["stretchers"]), top_profile=values["top_profile"],
                   library=library, top_name=top_name)


def _build_chair(library: ComponentLibrary, values: dict[str, Any]) -> list[WirePart]:
    parts = _build_framed(library, values, top_name="seat")
    seat = parts[0]
    material, back_h = values["material"], values["back_height_m"]
    top_y = values["height_m"]
    half_w, half_d = values["width_m"] / 2, values["depth_m"] / 2
    section = max(0.02, values["leg_section_m"] * 0.6)
    inset = max(section / 2, min(half_w / 2, values["leg_inset_m"]))
    posts = []
    for i, sx in enumerate((-1, 1), 1):
        at = (sx * (half_w - inset), top_y, half_d - section / 2)
        made = library.make("post", name="back-post-%d" % i, material=material,
                            from_m=at, to_m=(at[0], at[1] + back_h, at[2]),
                            parameters={"width_m": section, "depth_m": section})
        posts.append(made)
        parts.extend(made.parts)
    panel_h = min(back_h * 0.45, 0.24)
    parts.extend(library.make(
        "panel", name="back-panel", material=material,
        at_m=(0.0, top_y + back_h - panel_h / 2 - back_h * 0.08, half_d - section / 2),
        parameters={"width_m": (half_w - inset) * 2 + section, "height_m": panel_h,
                    "thickness_m": max(0.012, section * 0.5), "facing": "z"}).parts)
    if seat.role != "top":
        raise ValueError("the seat must be the first part")
    return parts


def _build_cart(library: ComponentLibrary, values: dict[str, Any]) -> list[WirePart]:
    material = values["material"]
    width, depth = values["width_m"], values["depth_m"]
    wheel_d, deck_y = values["wheel_diameter_m"], values["deck_height_m"]
    deck = library.make("surface", name="deck", material=material,
                        at_m=(0.0, deck_y, 0.0),
                        parameters={"width_m": width, "thickness_m": values["top_thickness_m"],
                                    "depth_m": depth, "profile": "square"})
    parts = list(deck.parts)
    hub_y = wheel_d / 2
    half_w = width / 2
    under = deck_y - values["top_thickness_m"]
    mount = max(0.025, values["axle_section_m"])
    for i, sz in enumerate((-1, 1), 1):
        z = sz * (depth / 2 - values["axle_inset_m"])
        parts.extend(library.make(
            "axle", name="axle-%d" % i, material="iron",
            from_m=(-half_w, hub_y, z), to_m=(half_w, hub_y, z),
            parameters={"width_m": values["axle_section_m"],
                        "depth_m": values["axle_section_m"]}).parts)
        # The axle hangs from the deck: without these the axles and wheels
        # floated under a deck they were joined to by nothing.
        if under - hub_y > 1e-3:
            for j, sx in enumerate((-1, 1), 1):
                x = sx * half_w * 0.62
                parts.extend(library.make(
                    "post", name="mount-%d%d" % (i, j), material=material,
                    from_m=(x, hub_y, z), to_m=(x, under, z),
                    parameters={"width_m": mount, "depth_m": mount}).parts)
        for j, sx in enumerate((-1, 1), 1):
            parts.extend(library.make(
                "wheel", name="wheel-%d%d" % (i, j), material=material,
                at_m=(sx * (half_w + values["wheel_width_m"] / 2), hub_y, z),
                parameters={"diameter_m": wheel_d,
                            "width_m": values["wheel_width_m"]}).parts)
    reach = values["handle_reach_m"]
    bar_y, bar_z = deck_y + reach * 0.5, -depth / 2 - reach
    for j, sx in enumerate((-1, 1), 1):
        x = sx * half_w * 0.6
        parts.extend(library.make(
            "beam", name="handle-arm-%d" % j, material=material,
            from_m=(x, deck_y, -depth / 2), to_m=(x, bar_y, bar_z),
            parameters={"width_m": mount, "depth_m": mount}).parts)
    parts.extend(library.make(
        "handle", name="handle", material=material,
        from_m=(-half_w * 0.6, bar_y, bar_z), to_m=(half_w * 0.6, bar_y, bar_z),
        parameters={}).parts)
    return parts


def _build_shelf_unit(library: ComponentLibrary, values: dict[str, Any]) -> list[WirePart]:
    material = values["material"]
    width, depth, height = values["width_m"], values["depth_m"], values["height_m"]
    shelves = max(2, int(round(values["shelves"])))
    thickness = values["top_thickness_m"]
    side = max(0.012, values["side_thickness_m"])
    parts: list[WirePart] = []
    for i, sx in enumerate((-1, 1), 1):
        parts.extend(library.make(
            "panel", name="side-%d" % i, material=material,
            at_m=(sx * (width / 2 - side / 2), height / 2, 0.0),
            parameters={"width_m": depth, "height_m": height,
                        "thickness_m": side, "facing": "x"}).parts)
    for i in range(shelves):
        y = thickness + (height - thickness) * i / max(1, shelves - 1)
        parts.extend(library.make(
            "surface", name="shelf-%d" % (i + 1), material=material,
            at_m=(0.0, min(y, height), 0.0),
            parameters={"width_m": width - 2 * side, "thickness_m": thickness,
                        "depth_m": depth, "profile": "square"}).parts)
    return parts


@dataclass(frozen=True)
class Assembly:
    """A named thing the workshop knows how to compose out of families."""

    name: str
    purpose: str
    about: str
    parameters: tuple[Parameter, ...]
    build: Callable[[ComponentLibrary, dict[str, Any]], list[WirePart]]
    trials: Callable[[dict[str, Any]], list[dict[str, Any]]]
    # What the template says of itself beyond its parts: how they are fastened
    # (@construction), what drives it (@machines), how each is modelled. A
    # machine's template authors every joint, so nothing is inferred.
    overrides: Callable[[dict[str, Any], list[WirePart]], dict[str, Any]] | None = None

    def defaults(self) -> dict[str, Any]:
        return {p.name: p.default for p in self.parameters}

    def checked(self, given: dict[str, Any] | None) -> dict[str, Any]:
        known = {p.name: p for p in self.parameters}
        values = self.defaults()
        for key, value in (given or {}).items():
            if key not in known:
                raise KeyError("%s has no parameter %r; it takes %s"
                               % (self.name, key, ", ".join(sorted(known))))
            values[key] = known[key].check(value)
        return values

    def described(self) -> dict[str, Any]:
        return {"assembly": self.name, "purpose": self.purpose, "about": self.about,
                "parameters": [p.described() for p in self.parameters]}


def _with(extra: Iterable[Parameter], *, drop: Iterable[str] = (),
          override: dict[str, Any] | None = None) -> tuple[Parameter, ...]:
    dropped = set(drop)
    out = []
    for p in _FRAME_PARAMETERS:
        if p.name in dropped:
            continue
        if override and p.name in override:
            p = Parameter(p.name, p.unit, override[p.name], p.low, p.high, p.choices, p.about)
        out.append(p)
    return tuple(out) + tuple(extra)


def _hold_and_tip(load_kg: float):
    def trials(values: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"kind": "static_load", "on": "top", "load_kg": load_kg},
                {"kind": "tip", "direction": "x"}, {"kind": "tip", "direction": "z"}]
    return trials


ASSEMBLIES: tuple[Assembly, ...] = (
    Assembly("table", "hold objects on a stable work surface",
             "A slab on four legs, optionally with aprons and stretchers.",
             _FRAME_PARAMETERS, _build_framed, _hold_and_tip(100.0)),
    Assembly("stool", "seat one person, with no back",
             "A small top on four legs; splay earns its keep here.",
             _with((), override={"width_m": 0.36, "depth_m": 0.36, "height_m": 0.46,
                                 "leg_section_m": 0.04, "top_profile": "round"}),
             _build_framed, _hold_and_tip(120.0)),
    Assembly("bench", "seat two or three people in a row",
             "A long top on four legs.",
             _with((), override={"width_m": 1.6, "depth_m": 0.36, "height_m": 0.45,
                                 "leg_section_m": 0.05}),
             _build_framed, _hold_and_tip(240.0)),
    Assembly("chair", "support a seated person, with a back",
             "A stool with two back posts and a panel between them.",
             _with((Parameter("back_height_m", "m", 0.46, 0.1, 1.2),),
                   override={"width_m": 0.46, "depth_m": 0.46, "height_m": 0.46,
                             "leg_section_m": 0.04}),
             _build_chair, _hold_and_tip(120.0)),
    Assembly("shelf-unit", "hold things on several levels",
             "Two side panels carrying a stack of shelves.",
             _with((Parameter("shelves", "", 4.0, 2.0, 8.0),
                    Parameter("side_thickness_m", "m", 0.018, 0.006, 0.08)),
                   drop=("leg_section_m", "leg_style", "splay_deg", "leg_inset_m",
                         "aprons", "stretchers", "top_profile"),
                   override={"width_m": 0.9, "depth_m": 0.3, "height_m": 1.8}),
             _build_shelf_unit, _hold_and_tip(60.0)),
    Assembly("cart", "carry a load on wheels",
             "A deck on two axles and four wheels, with a handle.",
             _with((Parameter("wheel_diameter_m", "m", 0.32, 0.05, 1.2),
                    Parameter("wheel_width_m", "m", 0.06, 0.01, 0.4),
                    Parameter("axle_section_m", "m", 0.03, 0.008, 0.2),
                    Parameter("axle_inset_m", "m", 0.18, 0.0, 1.0),
                    Parameter("deck_height_m", "m", 0.38, 0.05, 1.5),
                    Parameter("handle_reach_m", "m", 0.4, 0.1, 1.5)),
                   drop=("height_m", "leg_section_m", "leg_style", "splay_deg",
                         "leg_inset_m", "aprons", "stretchers", "top_profile"),
                   override={"width_m": 0.7, "depth_m": 1.0}),
             _build_cart, _hold_and_tip(150.0)),
)

#: No template at all: every part is one the person put in
#: (mcp/workshop_construction.py). It has no numbers to sweep, declares no trial
#: of its own, and is not among the assemblies the bench offers, because on its
#: own it has no parts to show.
CUSTOM = Assembly("custom", "do what its parts are put together to do",
                  "A design built part by part from the library.",
                  (), lambda library, values: [], lambda values: [])

_BY_NAME = {a.name: a for a in ASSEMBLIES}


def assemblies() -> list[dict[str, Any]]:
    return [a.described() for a in ASSEMBLIES]


def assembly(name: str) -> Assembly:
    if name == CUSTOM.name:
        return CUSTOM
    try:
        return _BY_NAME[name]
    except KeyError as exc:
        raise KeyError("unknown assembly: %s; the workshop knows %s"
                       % (name, ", ".join(sorted(_BY_NAME)))) from exc


# ---------------------------------------------------------------------------
# Designs, measurement and materialization
# ---------------------------------------------------------------------------


def _component_counts(parts: Iterable[WirePart]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for part in parts:
        if part.family:
            counts[part.family] = counts.get(part.family, 0) + 1
    return [{"family": name, "count": counts[name]} for name in sorted(counts)]


@dataclass
class WorkshopDesign:
    """A candidate object/assembly while the outside world is paused."""

    design_id: str
    purpose: str
    parts: list[WirePart]
    parameters: dict[str, Any] = field(default_factory=dict)
    lineage: dict[str, Any] = field(default_factory=dict)
    tests: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    kind: str | None = None

    def validate(self) -> "WorkshopDesign":
        if not self.design_id:
            raise ValueError("design_id is required")
        if not self.purpose:
            raise ValueError("purpose is required")
        if not self.parts:
            raise ValueError("a workshop design must contain at least one part")
        if "interaction_points" in self.parameters:
            from mcp import interaction_points
            interaction_points.checked(self.parameters["interaction_points"])
        if "primary_use" in self.parameters:
            from mcp import core_use
            core_use.checked_program(self.parameters["primary_use"])
        names = [p.name for p in self.parts]
        if len(names) != len(set(names)):
            raise ValueError("part names must be unique inside a workshop design")
        return self

    def wireframe(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": WORKSHOP_SCHEMA,
            "representation": "wireframe",
            "design_id": self.design_id,
            "kind": self.kind,
            "purpose": self.purpose,
            "parameters": deepcopy(self.parameters),
            "lineage": deepcopy(self.lineage),
            "parts": [
                {
                    "name": p.name,
                    "role": p.role,
                    "family": p.family,
                    "shape": p.shape,
                    "size_m": list(p.size_m),
                    "center_m": list(p.center_m),
                    "rotation_deg": list(p.rotation_deg),
                    "material": p.material,
                    "mass_kg": round(p.mass_kg(), 4),
                }
                for p in self.parts
            ],
            "measured": self.measure(),
            "tests": deepcopy(self.tests),
            "notes": list(self.notes),
        }

    def measure(self) -> dict[str, Any]:
        return measure(self)


@dataclass(frozen=True)
class WorkshopSession:
    """Metadata for an isolated workshop visit.

    ``world_revision`` is intentionally opaque.  The live-world layer can use a
    snapshot id, room revision, save hash or another durable identity.  The key
    rule is that the workshop has an immutable source and does not advance it.
    """

    session_id: str
    world_revision: str
    target: str
    outside_paused: bool = True

    def __post_init__(self) -> None:
        if not self.session_id or not self.world_revision or not self.target:
            raise ValueError("session_id, world_revision and target are required")
        if not self.outside_paused:
            raise ValueError("a workshop session must pause the outside world")

    def described(self) -> dict[str, Any]:
        return {"schema": WORKSHOP_SCHEMA, "session_id": self.session_id,
                "world_revision": self.world_revision, "target": self.target,
                "outside_paused": self.outside_paused}


def measure(design: WorkshopDesign) -> dict[str, Any]:
    """What the design weighs, where it balances, and what holds it up.

    Every number here is arithmetic over the wireframe: no physics has run.  The
    support polygon is taken from where the members actually TOUCH THE GROUND,
    not from where their centres are, which is what made a splayed candidate
    report a wider base than it has (docs/workshop-next.md stage 0).
    """
    design.validate()
    parts = design.parts
    masses = [p.mass_kg() for p in parts]
    total = sum(masses)
    if total <= 0:
        raise ValueError("a design must have mass")
    com = tuple(sum(p.center_m[i] * m for p, m in zip(parts, masses)) / total
                for i in range(3))

    floor = min(p.lowest_m() for p in parts)
    standing = [p for p in parts if p.lowest_m() <= floor + _ON_THE_FLOOR_M]
    feet = [point for p in standing for point in p.ground_contacts_m()]

    xs = [f[0] for f in feet] or [com[0]]
    zs = [f[1] for f in feet] or [com[2]]
    span_x, span_z = max(xs) - min(xs), max(zs) - min(zs)
    lift = max(1e-6, com[1] - floor)
    margins = {"x-": com[0] - min(xs), "x+": max(xs) - com[0],
               "z-": com[2] - min(zs), "z+": max(zs) - com[2]}
    worst = min(margins, key=lambda k: margins[k])

    # A splayed leg's FOOT is meant to stand outside the top -- that is the
    # point of splay. The defect worth reporting is a leg whose HEAD is not
    # under the top, because then it meets nothing.
    tops = [p for p in parts if p.name in {"top", "seat", "deck"}]
    over = []
    if tops:
        top = tops[0]
        half_w, half_d = top.size_m[0] / 2, top.size_m[2] / 2
        for part in parts:
            if part.role != "leg":
                continue
            head = part.highest_end_m()
            if (abs(head[0] - top.center_m[0]) > half_w + 1e-9
                    or abs(head[2] - top.center_m[2]) > half_d + 1e-9):
                over.append(part.name)

    return {
        "mass_kg": round(total, 3),
        "centre_of_mass_m": [round(v, 4) for v in com],
        "lowest_m": round(floor, 4),
        "standing_on": [p.name for p in standing],
        "ground_contacts_m": [[round(x, 4), round(z, 4)] for x, z in feet],
        "support_footprint_m": [round(span_x, 4), round(span_z, 4)],
        "tip_margin_m": {k: round(v, 4) for k, v in margins.items()},
        "smallest_tip_margin_m": round(margins[worst], 4),
        "tip_angle_deg": round(degrees(atan2(margins[worst], lift)), 2),
        "stands_up": all(v > 0 for v in margins.values()),
        "legs_not_under_the_top": sorted(set(over)),
        "bounding_box_m": [round(hi - lo, 4) for lo, hi in _extent(parts)],
    }


def _extent(parts: Iterable[WirePart]) -> list[tuple[float, float]]:
    corners = [c for p in parts for c in p.corners_m()]
    return [(min(c[i] for c in corners), max(c[i] for c in corners)) for i in range(3)]


def assemble(kind: str, *, design_id: str | None = None, purpose: str | None = None,
             parameters: dict[str, Any] | None = None,
             library: ComponentLibrary | None = None) -> WorkshopDesign:
    """Compose a named assembly out of the component library."""
    spec = assembly(kind)
    library = library or ComponentLibrary()
    from mcp import core_use
    supplied = dict(parameters or {})
    points = supplied.pop("interaction_points", None)
    use = supplied.pop("primary_use", None)
    use_component = supplied.pop("primary_use_component", None)
    point_components = supplied.pop("interaction_point_components", None)
    values = spec.checked(supplied)
    if use_component is not None:
        if not isinstance(use_component, str) or not use_component or len(use_component)>120:
            raise ValueError("primary_use_component must name a component")
        values["primary_use_component"] = use_component
    if point_components is not None:
        if (not isinstance(point_components, dict) or len(point_components)>32
                or any(not isinstance(k,str) or not isinstance(v,str) or not k or not v
                       or len(k)>60 or len(v)>120 for k,v in point_components.items())):
            raise ValueError("interaction_point_components must map point IDs to component names")
        values["interaction_point_components"] = dict(point_components)
    if use is not None:
        values["primary_use"] = core_use.checked_program(use)
    if points is not None:
        from mcp import interaction_points
        values["interaction_points"] = interaction_points.checked(points)
    parts = spec.build(library, values)
    lineage: dict[str, Any] = {"components": _component_counts(parts)}
    if spec.overrides is not None and parts:
        lineage["component_overrides"] = spec.overrides(values, parts)
    design = WorkshopDesign(
        design_id=design_id or kind,
        purpose=purpose or spec.purpose,
        parts=parts,
        kind=kind,
        parameters=values,
        lineage=lineage,
        tests=spec.trials(values),
    )
    # A template with no parts of its own is only the ground a construction is
    # built on; it is validated once its parts are in (apply_overrides).
    return design.validate() if parts else design


def variants(base: WorkshopDesign, sweeps: dict[str, Iterable[Any]]) -> list[WorkshopDesign]:
    """Fork cheap workshop candidates that really differ.

    Every candidate is REBUILT from the swept parameters.  An earlier version
    only wrote the changes into a parameters dict and copied the parent's parts,
    so six candidates materialized to identical geometry.
    """
    if not base.kind:
        raise ValueError("only an assembled design can be forked; it has no kind")
    spec = assembly(base.kind)
    known = {p.name for p in spec.parameters}
    keys = list(sweeps)
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise KeyError("%s has no parameter %s; it takes %s"
                       % (base.kind, ", ".join(repr(k) for k in unknown),
                          ", ".join(sorted(known))))
    values = [list(sweeps[k]) for k in keys]
    out: list[WorkshopDesign] = []
    for index, combination in enumerate(product(*values), 1):
        changes = dict(zip(keys, combination))
        candidate = assemble(base.kind, design_id="%s-v%d" % (base.design_id, index),
                             purpose=base.purpose,
                             parameters={**base.parameters, **changes})
        candidate.lineage = {
            "parent": base.design_id,
            "variant": index,
            "changes": deepcopy(changes),
            "components": _component_counts(candidate.parts),
        }
        out.append(candidate)
    return out


def materialize(design: WorkshopDesign, *, cell_size_m: float = 0.04) -> dict[str, Any]:
    """Snap a chosen wireframe to Banjo's material grid.

    This is a plan, not a live-world mutation and not a physics success claim.
    A later transaction must independently validate placement, inventory,
    fabrication energy and the design's functional trials.

    Snapping is REPORTED.  At a 40 mm cell a 45 mm and a 58 mm leg become the
    same 40 mm leg, so candidates that look different on the bench can arrive
    identical; ``fingerprint`` is what tells two plans apart, and ``snapping``
    says how far each member moved to get there.
    """
    design.validate()
    cell = _positive("cell_size_m", cell_size_m)
    # Model choice is persistent physical intent, not a hint to the renderer.
    # Keep the legacy grid planner from silently voxelizing a rigid recipe.
    from . import workshop_rigid
    models = workshop_rigid.requested_models(design)
    if models != {"lattice"}:
        model = next(iter(models)) if len(models) == 1 else "mixed"
        source = design.wireframe()
        return {
            "schema": WORKSHOP_SCHEMA, "representation": "materialization-plan",
            "design_id": design.design_id, "kind": design.kind,
            "mechanical_model": model, "cell_size_m": cell,
            "fingerprint": sha256(dumps({"source": source, "models": sorted(models)},
                                        sort_keys=True).encode()).hexdigest()[:16],
            "objects": [], "source_geometry": source,
            "snapping": {"cell_size_m": None, "members_changed": 0, "largest_change_m": 0.0},
            "measured": design.measure(), "tests": deepcopy(design.tests),
            "commit": {"status": "not-committed", "requires": [
                "supported live-room adapter for the explicitly selected mechanical representation",
                "placement validation", "inventory/material allocation",
                "fabrication energy/process validation", "functional trials"]},
        }
    objects, changes = [], []
    for part in design.parts:
        size = [_snap(x, cell) for x in part.size_m]
        moved = max(abs(a - b) for a, b in zip(size, part.size_m))
        changes.append(moved)
        entry = {
            "name": part.name,
            "role": part.role,
            "component_family": part.family,
            "shape": part.shape,
            "material": part.material,
            "size_m": size,
            "center_m": [_snap_at(x, cell) for x in part.center_m],
            "rotation_deg": [round(a, 4) for a in part.rotation_deg],
            "source": {"design_id": design.design_id, "representation": "wireframe"},
        }
        if moved > 1e-9:
            entry["snapped_from_m"] = [round(x, 5) for x in part.size_m]
        objects.append(entry)
    shape = [[o["size_m"], o["center_m"], o["rotation_deg"], o["material"], o["shape"]]
             for o in objects]
    return {
        "schema": WORKSHOP_SCHEMA,
        "representation": "materialization-plan",
        "design_id": design.design_id,
        "kind": design.kind,
        "cell_size_m": cell,
        "fingerprint": sha256(dumps(shape, sort_keys=True).encode()).hexdigest()[:16],
        "objects": objects,
        "snapping": {
            "cell_size_m": cell,
            "members_changed": sum(1 for c in changes if c > 1e-9),
            "largest_change_m": round(max(changes), 5) if changes else 0.0,
        },
        "measured": design.measure(),
        "tests": deepcopy(design.tests),
        "commit": {
            "status": "not-committed",
            "requires": [
                "placement validation",
                "inventory/material allocation",
                "fabrication energy/process validation",
                "functional trials",
            ],
        },
    }


def feedback(design: WorkshopDesign, *, rating: int | None = None,
             selected: bool | None = None, note: str = "") -> dict[str, Any]:
    """Structured user feedback suitable for a future component-learning store."""

    if rating is not None and rating not in range(1, 6):
        raise ValueError("rating must be 1 through 5")
    return {
        "schema": WORKSHOP_SCHEMA,
        "kind": "feedback",
        "design_id": design.design_id,
        "assembly": design.kind,
        "rating": rating,
        "selected": selected,
        "note": str(note),
        "lineage": deepcopy(design.lineage),
        "parameters": deepcopy(design.parameters),
    }


def rectangular_four_leg_frame(*, design_id: str, purpose: str,
                               top_size_m: tuple[float, float, float],
                               top_height_m: float,
                               leg_family: str = "leg",
                               leg_parameters: dict[str, Any] | None = None,
                               material: str = "oak",
                               library: ComponentLibrary | None = None) -> WorkshopDesign:
    """Build a reusable table/chair-like wireframe from one leg family.

    Kept as the short way to say "a slab on four legs" from Python; it composes
    the same ``table`` assembly the page and the agent use.
    """
    if leg_family != "leg":
        raise ValueError("rectangular_four_leg_frame stands the top on the leg family")
    width, thickness, depth = (_positive("top size", x) for x in top_size_m)
    height = _positive("top_height_m", top_height_m)
    if thickness >= height:
        raise ValueError("top thickness must be below the top height")
    lp = dict(leg_parameters or {})
    section = _positive("leg width", lp.get("width_m", 0.06))
    return assemble(
        "table", design_id=design_id, purpose=purpose, library=library,
        parameters={
            "width_m": width, "depth_m": depth, "height_m": height,
            "top_thickness_m": thickness, "leg_section_m": section,
            "leg_style": lp.get("style", "straight"),
            "splay_deg": lp.get("splay_deg", 0.0),
            "leg_inset_m": lp.get("inset_m", 0.05),
            "material": material,
        })
