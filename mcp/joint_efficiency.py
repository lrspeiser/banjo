"""How much of the material it joins a joint keeps, and why.

A joint is not the material either side of it. Glue a leg's end to a table top
and the joint is a fraction of the wood; laminate two boards face to face and it
is the wood; weld two plates with matching filler and it is the plate. Until
now a Workshop product compiled to one fused lattice in which a bond between a
leg's cell and the top's was an ordinary oak bond, so every joint was as strong
as the wood ([#20](https://github.com/lrspeiser/banjo/issues/20)).

This module is the law that says otherwise. It is declared, in the way
``src/thermo/ThermalMechanics.cpp`` declares the heat curves: every number
carries where it comes from and what it does not cover, and a demonstration
value says so in the answer rather than in a comment.

What a law decides is a multiplier on the material's own strength -- one for
tension, one for shear, one for compression -- which two things then read:

* :mod:`mcp.product_joints`, for what a joint can carry on the bench;
* the engine, as a scene ``interfaces`` block, which leaves the bonds crossing
  that joint with exactly that share of the material (``weakenBond``,
  ``matter/Lattice.hpp``).

One law, read twice, so the bench and the world cannot drift apart.

**Compression is 1.0 in every law, and that is physics, not a default.** Two
parts pushed together bear on each other directly: an end-grain butt joint that
holds a quarter of the wood in tension carries the wood's full compression,
because in compression the glue line is not what is carrying. A joint fails in
tension or in shear.

**Nothing here is in force yet, by the owner's call of 2026-09-19.** Every law
keeps the material whole -- 1.0 in every mode -- and what the sources would
support is recorded beside it as ``proposed``, read by nothing but the test that
pins it. Setting a number below 1 is a declaration about real joints, and it is
the owner's to make deliberately, not one to arrive with an implementation. So
the mechanism ships inert: a law that keeps everything is not declared to a
scene at all, no product breaks differently than it did, and putting the figures
in force later is an edit to this table and nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp import engine_materials

EFFICIENCY_SCHEMA = "banjo.joint-efficiency.v1"

#: Which of a part's own axes each of its faces looks along.
FACE_AXIS = {"face-x-": 0, "face-x+": 0, "face-y-": 1, "face-y+": 1, "face-z-": 2, "face-z+": 2}


@dataclass(frozen=True)
class JointLaw:
    """What one way of making a joint leaves of the material it joins."""

    id: str
    #: What this law leaves of the material, IN FORCE. 1.0 everywhere today:
    #: see the module docstring on the owner's call of 2026-09-19.
    tension: float
    shear: float
    #: reference-derived: from a published source. demonstration: a stated
    #: stand-in, because what it depends on is not declared anywhere.
    provenance: str
    source: str
    compression: float = 1.0
    #: (tension, shear) the source would support, for whoever puts it in force.
    #: Documentation. Nothing reads it but the test that pins what is in force.
    proposed: tuple[float, float] | None = None
    not_modelled: tuple[str, ...] = ()

    def whole(self) -> bool:
        """Whether this law leaves the material exactly as it is, so that there
        is nothing to declare to a scene."""
        return (self.tension, self.shear, self.compression) == (1.0, 1.0, 1.0)

    def described(self, basis: str) -> dict[str, Any]:
        return {"schema": EFFICIENCY_SCHEMA, "id": self.id, "basis": basis,
                "tension": self.tension, "shear": self.shear, "compression": self.compression,
                "provenance": self.provenance, "source": self.source,
                "in_force": not self.whole(),
                "proposed": list(self.proposed) if self.proposed else None,
                "not_modelled": list(self.not_modelled)}


_FAILS_IN_THE_PARENT = JointLaw(
    id="bonded, side grain or isotropic",
    tension=1.0, shear=1.0, provenance="reference-derived",
    source=(
        "A properly made side-grain glue joint in wood is as strong as the wood: the joint fails in "
        "the wood beside the bond line, not in it (USDA Forest Products Laboratory, Wood Handbook, "
        "FPL-GTR-190, 2010, ch. 10 'Adhesive Bonding of Wood Materials'). For a material with no "
        "grain the same holds of a full-penetration weld made with matching filler, which is "
        "designed to develop the base metal (AWS D1.1; EN 1993-1-8). So the joint is not what "
        "decides: the material is, and this law leaves it alone."),
    not_modelled=(
        "a badly made joint: a starved, cold or contaminated bond line is weaker than the parent, "
        "and how well it was made is not declared anywhere in a design",
        "a fillet weld, which is designed on its throat and not on the parent's section",
    ))

_END_GRAIN = JointLaw(
    id="bonded, end grain butted to another part",
    tension=1.0, shear=1.0, proposed=(0.25, 0.25), provenance="reference-derived",
    source=(
        "An end-grain butt joint in wood cannot be made to hold more than about a quarter of what a "
        "comparable side-grain joint holds: the open ends of the cells drink the adhesive and leave "
        "the line starved (USDA Forest Products Laboratory, Wood Handbook, FPL-GTR-190, 2010, "
        "ch. 10). It is why a scarf or a finger joint exists at all -- both work by turning end "
        "grain back into side grain. The quarter is the source's figure for TENSION."),
    not_modelled=(
        "the source gives the quarter for tension; the same share is assumed for shear",
        "a scarf, finger, mortise or dowelled joint, each of which is made precisely to avoid this "
        "and would be its own law",
        "which way the grain actually runs: this law takes it to run along a part's longest side, "
        "which is how timber is cut and why a strut is a strut, but no design declares it; a part "
        "with no single longest side, such as a cube or a disc, is taken to present end grain, "
        "because for a strength answer that is the safe way to be wrong",
    ))

_PRESSED = JointLaw(
    id="pressed fit",
    tension=1.0, shear=1.0, proposed=(0.15, 0.15), provenance="demonstration",
    source=(
        "A press fit holds by friction: what it carries is the coefficient of friction times the "
        "interface pressure times the area, and the pressure follows from the interference, the "
        "surface finish and the two elastic moduli. A Workshop design declares none of those, so "
        "no number can be derived from it. 0.15 is a DEMONSTRATION stand-in for a light "
        "interference fit, chosen to be clearly weak without being nothing; it is not a "
        "measurement, and a design that turns on it should declare its interference instead."),
    not_modelled=(
        "the interference, surface finish and assembly method a real press fit is specified by",
        "that a press fit loosens as it is loaded and unloaded, and with temperature",
    ))


def grain_axis(part: Any) -> int | None:
    """Which of a part's own axes its grain runs along: its longest side.

    Timber is cut with the grain along the length of the piece, which is why a
    strut is a strut and a board is a board. Nothing in a design declares the
    direction, so it is read from the shape. A part with no single longest side
    -- a cube, a disc -- has no answer, and ``None`` says so.
    """
    size = [float(v) for v in part.size_m]
    longest = max(size)
    along = [i for i, v in enumerate(size) if v >= longest * (1.0 - 1e-9)]
    return along[0] if len(along) == 1 else None


def _is_end(face: Any, part: Any) -> bool:
    """Whether that face of that part is its end grain.

    A part whose grain direction cannot be read from its shape is taken to
    present end grain, because for a strength answer the weaker reading is the
    safe one to be wrong about.
    """
    axis = FACE_AXIS.get(str(face or ""))
    if axis is None:
        return False
    along = grain_axis(part)
    return along is None or axis == along


def _directional(material: str) -> bool:
    """Whether the catalogue says this material has a grain direction."""
    try:
        return engine_materials.mechanics(material)["anisotropy_ratio"] > 1.0
    except KeyError:
        return False


def law(joint: dict[str, Any], a: Any, b: Any) -> tuple[JointLaw, str] | None:
    """The law for one joint, and the words for why it is that one.

    ``joint`` is a row of :func:`mcp.workshop_construction.joints`; ``a`` and
    ``b`` are its two parts. ``None`` means no law applies and the interface is
    left as the material's own -- which is said out loud, never assumed.
    """
    method = str(joint.get("method") or "")
    how = joint.get("interface") or {}
    if method == "bearing":
        return None
    if method == "pressed":
        return _PRESSED, "a shaft held in its bore by the fit alone"
    if method != "bonded":
        return None
    if how.get("form") == "planar":
        by = {str(how.get("on")): how.get("on_face"), str(how.get("against")): how.get("against_face")}
        for part in (a, b):
            if _is_end(by.get(part.name), part) and _directional(part.material):
                return _END_GRAIN, f"{part.name}'s end grain is butted to the other part"
        return _FAILS_IN_THE_PARENT, "the parts meet side grain to side grain"
    return _FAILS_IN_THE_PARENT, "a bonded joint on a shaft's own surface, which is side grain"


def efficiency(joint: dict[str, Any], a: Any, b: Any) -> dict[str, Any]:
    """What this joint keeps of the material it joins, with its provenance."""
    found = law(joint, a, b)
    if found is None:
        return {"schema": EFFICIENCY_SCHEMA, "id": "none", "rated": False,
                "tension": 1.0, "shear": 1.0, "compression": 1.0,
                "basis": ("a bearing is not a bond: it is a clearance fit, and what holds a wheel on "
                          "its axle -- a pin, a washer, a nut -- is not declared in the design. "
                          "Neither weakening it nor welding it would be that, so it is left as the "
                          "material's own and said here rather than claimed either way."),
                "provenance": "not-modelled", "source": "", "not_modelled": []}
    chosen, basis = found
    return {**chosen.described(basis), "rated": True}


def described() -> list[dict[str, Any]]:
    """Every law, for a catalogue the owner can read and change in one place."""
    return [chosen.described(basis) for chosen, basis in (
        (_FAILS_IN_THE_PARENT, "two parts bonded side grain to side grain, or a weld"),
        (_END_GRAIN, "a member's end bonded to another part"),
        (_PRESSED, "a shaft held in its bore by the fit alone"))]


def scene_interfaces(design: Any, prefix: str = "") -> list[dict[str, Any]]:
    """The joints of a built design, as the scene's own ``interfaces`` block.

    One entry per declared joint that a law applies to, naming the two parts by
    the labels its cells carry. A joint no law applies to -- a bearing -- is
    left out, so those bonds stay the material's own, which is what today
    already does and is said in :func:`efficiency`.

    `prefix` goes in front of both labels, for a scene that holds more than one
    product: two of the same design standing in a room are two objects, and a
    joint in one is not a joint in the other. A scene with one product under
    test needs none, and the labels are the design's own.
    """
    from mcp import workshop_construction

    parts = {part.name: part for part in design.parts}
    out: list[dict[str, Any]] = []
    for joint in workshop_construction.joints(design):
        if joint.get("open"):
            continue          # its parts no longer touch: there is nothing to cross
        keeps = efficiency(joint, parts[joint["a"]], parts[joint["b"]])
        if not keeps["rated"]:
            continue
        if (keeps["tension"], keeps["shear"], keeps["compression"]) == (1.0, 1.0, 1.0):
            # The law leaves the material exactly as it is, so there is nothing
            # to say: the bonds across this joint are already the wood's own.
            # This is what every law does today (the owner's call, 2026-09-19),
            # so a scene is declared nothing and no product changes. It also
            # keeps the engine's guard honest -- it refuses a declared joint
            # that weakens no bond, and a whole one would weaken none.
            continue
        out.append({"a": prefix + joint["a"], "b": prefix + joint["b"],
                    "tension": keeps["tension"], "shear": keeps["shear"],
                    "compression": keeps["compression"]})
    return out
