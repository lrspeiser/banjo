"""Wireframe-first workshop design helpers.

The workshop is deliberately separate from the running Banjo world.  It works
with cheap, inspectable design descriptions, component families and candidate
variants.  Nothing in this module advances physics or mutates a live world.

A design is materialized only after the player/agent chooses a candidate.
Materialization snaps every solid to the requested cell grid and returns a
plain object plan that the existing Banjo authoring layer can consume later.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from itertools import product
from math import isfinite
from typing import Any, Iterable


WORKSHOP_SCHEMA = "banjo.workshop.v1"


def _positive(name: str, value: float) -> float:
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def _snap(value: float, cell: float) -> float:
    return max(cell, round(float(value) / cell) * cell)


def _snap_at(value: float, cell: float) -> float:
    return round(float(value) / cell) * cell


@dataclass(frozen=True)
class WirePart:
    """One cheap design member.

    Boxes are enough for the first workshop slice because Banjo already knows
    how to turn boxes into matter and because table/chair frames are a useful
    test of component reuse. ``role`` is semantic and survives materialization.
    """

    name: str
    role: str
    size_m: tuple[float, float, float]
    center_m: tuple[float, float, float]
    material: str = "oak"
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        if not self.name or not self.role:
            raise ValueError("wire parts need a name and a role")
        for i, value in enumerate(self.size_m):
            _positive(f"size_m[{i}]", value)
        if len(self.center_m) != 3 or len(self.rotation_deg) != 3:
            raise ValueError("center_m and rotation_deg must each have three values")
        if not all(isfinite(float(x)) for x in (*self.center_m, *self.rotation_deg)):
            raise ValueError("wire part coordinates and rotations must be finite")


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

    def validate(self) -> "WorkshopDesign":
        if not self.design_id:
            raise ValueError("design_id is required")
        if not self.purpose:
            raise ValueError("purpose is required")
        if not self.parts:
            raise ValueError("a workshop design must contain at least one part")
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
            "purpose": self.purpose,
            "parameters": deepcopy(self.parameters),
            "lineage": deepcopy(self.lineage),
            "parts": [
                {
                    "name": p.name,
                    "role": p.role,
                    "shape": "box",
                    "size_m": list(p.size_m),
                    "center_m": list(p.center_m),
                    "rotation_deg": list(p.rotation_deg),
                    "material": p.material,
                }
                for p in self.parts
            ],
            "tests": deepcopy(self.tests),
            "notes": list(self.notes),
        }


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


class ComponentLibrary:
    """Small semantic component registry used by the workshop agent.

    Families return wire members, not finished voxel bodies.  That makes them
    cheap to vary, preview and score.  The initial ``leg`` family deliberately
    serves both tables and chairs.
    """

    def __init__(self) -> None:
        self._families: dict[str, Any] = {}
        self.register("leg", self._leg)

    def register(self, name: str, factory: Any) -> None:
        if not name:
            raise ValueError("component family needs a name")
        if name in self._families:
            raise ValueError(f"component family already exists: {name}")
        self._families[name] = factory

    def families(self) -> tuple[str, ...]:
        return tuple(sorted(self._families))

    def make(self, family: str, *, name: str, at_m: Iterable[float],
             parameters: dict[str, Any] | None = None, material: str = "oak") -> list[WirePart]:
        try:
            factory = self._families[family]
        except KeyError as exc:
            raise KeyError(f"unknown component family: {family}") from exc
        at = tuple(float(x) for x in at_m)
        if len(at) != 3 or not all(isfinite(x) for x in at):
            raise ValueError("at_m must be three finite coordinates")
        return factory(name=name, at=at, parameters=dict(parameters or {}), material=material)

    @staticmethod
    def _leg(*, name: str, at: tuple[float, float, float],
             parameters: dict[str, Any], material: str) -> list[WirePart]:
        height = _positive("height_m", parameters.get("height_m", 0.72))
        width = _positive("width_m", parameters.get("width_m", 0.06))
        depth = _positive("depth_m", parameters.get("depth_m", width))
        style = str(parameters.get("style", "straight"))
        splay = float(parameters.get("splay_deg", 5.0 if style == "splayed" else 0.0))
        if not isfinite(splay) or abs(splay) > 25:
            raise ValueError("splay_deg must be finite and at most 25 degrees")
        if style not in {"straight", "splayed", "tapered"}:
            raise ValueError("leg style must be straight, splayed or tapered")

        # Taper is semantic for now. The first materializer still uses a box;
        # a future surface/voxel compiler can honor it without changing designs
        # that reference this family.
        return [WirePart(
            name=name,
            role="leg",
            size_m=(width, height, depth),
            center_m=(at[0], at[1] + height / 2, at[2]),
            material=material,
            rotation_deg=(0.0, 0.0, splay),
        )]


def rectangular_four_leg_frame(*, design_id: str, purpose: str,
                               top_size_m: tuple[float, float, float],
                               top_height_m: float,
                               leg_family: str = "leg",
                               leg_parameters: dict[str, Any] | None = None,
                               material: str = "oak",
                               library: ComponentLibrary | None = None) -> WorkshopDesign:
    """Build a reusable table/chair-like wireframe from one leg family."""

    library = library or ComponentLibrary()
    width, top_thickness, depth = (_positive("top size", x) for x in top_size_m)
    top_height = _positive("top_height_m", top_height_m)
    if top_thickness >= top_height:
        raise ValueError("top thickness must be below the top height")

    lp = dict(leg_parameters or {})
    lp.setdefault("height_m", top_height - top_thickness)
    leg_w = _positive("leg width", lp.get("width_m", 0.06))
    leg_d = _positive("leg depth", lp.get("depth_m", leg_w))
    inset_x = max(leg_w / 2, min(width / 4, float(lp.pop("inset_x_m", 0.05))))
    inset_z = max(leg_d / 2, min(depth / 4, float(lp.pop("inset_z_m", 0.05))))

    parts = [WirePart(
        name="top",
        role="top",
        size_m=(width, top_thickness, depth),
        center_m=(0.0, top_height - top_thickness / 2, 0.0),
        material=material,
    )]
    corners = [
        (-width / 2 + inset_x, -depth / 2 + inset_z),
        ( width / 2 - inset_x, -depth / 2 + inset_z),
        ( width / 2 - inset_x,  depth / 2 - inset_z),
        (-width / 2 + inset_x,  depth / 2 - inset_z),
    ]
    for i, (x, z) in enumerate(corners, 1):
        parts.extend(library.make(
            leg_family, name=f"leg-{i}", at_m=(x, 0.0, z),
            parameters=lp, material=material))

    kind = "chair" if top_height < 0.60 else "table"
    return WorkshopDesign(
        design_id=design_id,
        purpose=purpose,
        parts=parts,
        parameters={
            "archetype": f"four-leg-{kind}",
            "top_size_m": [width, top_thickness, depth],
            "top_height_m": top_height,
            "leg_family": leg_family,
            "leg_parameters": deepcopy(lp),
        },
        lineage={"components": [{"family": leg_family, "count": 4}]},
        tests=[
            {"kind": "static_load", "on": "top", "load_kg": 100.0 if kind == "table" else 120.0},
            {"kind": "tip", "direction": "x"},
            {"kind": "tip", "direction": "z"},
        ],
    ).validate()


def variants(base: WorkshopDesign, sweeps: dict[str, Iterable[Any]]) -> list[WorkshopDesign]:
    """Fork cheap workshop variants from a design without touching Banjo."""

    keys = list(sweeps)
    values = [list(sweeps[k]) for k in keys]
    out: list[WorkshopDesign] = []
    for index, combination in enumerate(product(*values), 1):
        candidate = deepcopy(base)
        changes = dict(zip(keys, combination))
        candidate.design_id = f"{base.design_id}-v{index}"
        candidate.parameters.update(changes)
        candidate.lineage = {
            "parent": base.design_id,
            "variant": index,
            "changes": deepcopy(changes),
        }
        out.append(candidate.validate())
    return out


def materialize(design: WorkshopDesign, *, cell_size_m: float = 0.04) -> dict[str, Any]:
    """Snap a chosen wireframe to Banjo's material grid.

    This is a plan, not a live-world mutation and not a physics success claim.
    A later transaction must independently validate placement, inventory,
    fabrication energy and the design's functional trials.
    """

    design.validate()
    cell = _positive("cell_size_m", cell_size_m)
    objects = []
    for part in design.parts:
        objects.append({
            "name": part.name,
            "role": part.role,
            "shape": "box",
            "material": part.material,
            "size_m": [_snap(x, cell) for x in part.size_m],
            "center_m": [_snap_at(x, cell) for x in part.center_m],
            "rotation_deg": list(part.rotation_deg),
            "source": {"design_id": design.design_id, "representation": "wireframe"},
        })
    return {
        "schema": WORKSHOP_SCHEMA,
        "representation": "materialization-plan",
        "design_id": design.design_id,
        "cell_size_m": cell,
        "objects": objects,
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
        "rating": rating,
        "selected": selected,
        "note": str(note),
        "lineage": deepcopy(design.lineage),
        "parameters": deepcopy(design.parameters),
    }
