"""Conversational Workshop agent with bounded, atomic design tools.

The Workshop assistant is deliberately not a live-world agent.  It may inspect
all of the current product geometry/physics/library context and apply several
Workshop edits to an in-memory candidate during one turn.  The caller receives
the final candidate only after the whole turn succeeds, so a failed model/tool
sequence never leaves a half-edited browser design.

``propose`` keeps the original API surface used by ``workshop_api``.  For
compatibility it mutates the candidate dictionary that API already owns and
returns ``action='none'`` after applying its own bounded tool calls.  That lets
us ship the richer conversational behavior without coupling the LLM to live
world authoring.
"""
from __future__ import annotations

from copy import deepcopy
import json
import logging
import re
import threading
import time
from typing import Any
from urllib import error, request

from mcp import engine_materials, workshop_components, workshop_construction, workshop_graph, workshop_machines, interaction_points
from mcp.product_contract import compile_contract
from mcp.workshop import WirePart, assemble, assembly
from mcp.workshop_statics import declared_statics
import workshop_fitting
import workshop_test_room as test_room
import workshop_library

log = logging.getLogger(__name__)

#: What each turn is doing, while it does it, so the page can say so.
#:
#: A turn is one POST that answers when the whole thing is finished, and the
#: work inside it is several round trips to the model with a run of the little
#: world in between. Waiting thirty seconds at a bubble that says "Working" and
#: nothing else is the same as waiting at a blank screen. The page hands in an
#: id, this is written as the turn goes, and the page reads it back.
_PROGRESS: dict[str, dict[str, Any]] = {}
_PROGRESS_LOCK = threading.Lock()
#: How many times one tool may be refused before this turn stops calling it,
#: and how many refusals in all before the turn gives up and answers with what
#: it has. A turn that has been told the same thing twice has been told.
REFUSALS_A_TOOL = 3
REFUSALS_A_TURN = 8

#: How many turns are remembered, and for how long. A turn is small; this is
#: only here so that a long session does not grow without end.
PROGRESS_KEPT = 32
PROGRESS_TTL_S = 900.0
#: What each tool is doing, said the way a person would say it. A tool name is
#: the code's word for it; nobody watching wants to read edit_components.
DOING = {
    "inspect_design": "looking at the design",
    "inspect_component": "looking at that part",
    "inspect_physics": "measuring it",
    "search_library": "looking through your library",
    "edit_components": "changing the parts",
    "set_parameter": "changing a number on it",
    "reuse_library_component": "putting one of your saved parts in",
    "what_it_needs": "working out what making it would take",
    "set_skin": "changing how it looks",
    "add_part": "adding a part",
    "remove_part": "taking a part off",
    "set_joint": "changing how two parts are fastened",
    "add_power_part": "wiring something in",
    "set_program": "writing what it does on its own",
    "check_validity": "checking the room can carry it",
    "define_interaction_points": "saying where you take hold of it",
    "program_use": "writing what it is for",
    "try_it_in_a_room": "trying it in a little world",
    "find_the_limit": "finding where it gives way",
    "save_design": "saving it",
    "list_saved_designs": "looking at what you saved",
    "open_saved_design": "opening a saved design",
    "take_it_back": "taking that back",
    "ask_the_person": "asking you",
}


def progress(turn: str) -> dict[str, Any]:
    """What that turn has done so far, for the page to show while it waits."""
    with _PROGRESS_LOCK:
        return deepcopy(_PROGRESS.get(str(turn)) or {"turn": str(turn), "steps": [], "done": False})


def _note(turn: str | None, said: str, *, done: bool = False, ok: bool = True) -> None:
    """One line of what is happening now."""
    if not turn:
        return
    now = time.time()
    with _PROGRESS_LOCK:
        held = _PROGRESS.setdefault(str(turn), {"turn": str(turn), "began": now, "steps": [],
                                                "done": False})
        if said:
            held["steps"].append({"at_s": round(now - held["began"], 2), "said": said, "ok": ok})
            del held["steps"][:-40]
        held["done"] = bool(done)
        held["seen"] = now
        for stale in [k for k, v in _PROGRESS.items()
                      if now - v.get("seen", now) > PROGRESS_TTL_S]:
            del _PROGRESS[stale]
        while len(_PROGRESS) > PROGRESS_KEPT:
            del _PROGRESS[next(iter(_PROGRESS))]

EDIT_ACTIONS = ("longer", "shorter", "thicker", "thinner", "wider", "narrower", "material")
MAX_HISTORY = 20
MAX_MESSAGE_CHARS = 48_000
# How long a turn may go on before it has to stop and say what it has.
#
# The owner, after a turn died with "Workshop chat could not finish within its
# bounded reasoning loop": *"we need to rethink the reasoning loop, the llm has
# memory and should be able to get to an answer and we should not need to limit
# the tokens to get there."*
#
# Two things were wrong, and neither was the size of the numbers.
#
# The first is that running out threw the turn AWAY. Eight rounds in, having
# inspected the design and made every edit it was asked for, the loop raised --
# so the person saw an error, not the work. A turn that runs long now WRAPS UP:
# one more call with the tools switched off and "answer now with what you
# have", which is what you would say to a person who was still measuring when
# the bell went. It has the whole conversation in front of it and can always
# say something true about it.
#
# The second is the per-call ceiling. There is none now. A ceiling on output
# tokens is a ceiling on THINKING -- the provider counts reasoning against it --
# and a turn cut off mid-thought comes back with no words at all, which is how
# "I inspected the design but made no changes" got said about a turn that had
# done neither. What bounds a turn is how long it may go on and how much of the
# room it may touch, not how many words it may think in.
MAX_TOOL_ROUNDS = 32
MAX_TOOL_CALLS = 120
#: A turn that has been going this long is not converging, whatever it says.
MAX_TURN_SECONDS = 240.0

SYSTEM = """You are the Banjo Workshop design assistant.

You are operating ONLY on the isolated Workshop candidate. Never claim to edit,
run, or commit the outside live world. The user expects you to behave like a
CAD/physics copilot, not a one-shot intent classifier.

Important behavior:
- define_interaction_points says where a finished product is taken hold of and
  what it receives: grip/use points, plus real receiving surfaces or cargo
  interiors. Positions are in the design frame; a receiving position is on the
  floor and size_m is the usable space above it. Metadata never creates a
  cavity. ONLY when the person is making or finishing a product, when they ask
  for it, or when GEOMETRY you just changed has moved the points -- a change of
  material has moved nothing.
- A finished product needs a primary_use program, written with program_use when
  it is being MADE or FINISHED, or when the person asks what it does. It is
  stored with the design, exposed in ProductGraph controls and carried into the
  world. Never claim a product is operational if its intended action is
  unsupported. Do not write one as a bonus on top of an edit that had nothing to
  do with what the thing is for.
- MAKE YOUR BEST GUESS AND GO. Do not ask before you start. Every round trip
  to ask something costs the person a wait as long as the work itself, and
  anything you do can be taken back -- take_it_back undoes it, and they know
  that. Pick the sensible thing, DO it, say what you picked and why in one
  line, and THEN offer what else they might have meant. "I dropped 20 kg on it
  from 2 m -- it held. Want it harder, or from higher?" is a good turn. "How
  heavy, and from what height?" is a bad one: it is a wait for nothing.
- ask_the_person is for AFTERWARDS, or for a fork you genuinely cannot pick
  between -- not for numbers you can choose yourself. When you do call it, give
  two to four CONCRETE answers they can click ("Make it 50 mm", "Add a
  sleeve"), never "what would you like?". Writing their own is always offered.
  Put what you would do first. Calling it ends your turn.
- NEVER END A TURN WITH AN OPEN QUESTION IN PROSE. If you want a decision, that
  is what ask_the_person is for.
- DO WHAT WAS ASKED AND STOP. Asked to change a material, change the material.
  Do not also declare where the thing is held, write it a use, give it a skin
  or run a test nobody mentioned. Measured: "make the table out of glass" was
  done at the second round trip, in 13 seconds, and then spent 129 more on
  interaction points and a usage program that nobody had asked for and that
  were refused 27 times between them.
- A REFUSAL IS INFORMATION, NOT A SETBACK. Read what it says and change that,
  or leave the tool alone and say what you could not do. Calling it again the
  same way gets the same answer and costs the person another wait. After a few
  refusals of one tool this bench stops running it for the rest of the turn.
- ONLY OFFER WHAT THIS BENCH CAN DO. Every alternative you name has to be one
  you could carry out with the tools you have, on the next turn, without asking
  anybody for anything. A part is one of the materials in the material enum,
  solid through, at a size and a place. There is no tempering, no laminating,
  no coating, no filling, no adhesive, no bracket and no bought fastener: a
  joint is a declared fastening between two parts and nothing else. Offering a
  choice between annealed and tempered glass, or a metal insert down the middle
  of a leg, is offering something nobody here can make -- and it reads as
  expertise, which makes it worse.
- Say plainly when a tool call failed and what you did about it. "I attempted to
  set a usage program but that call failed" in the middle of a list of results
  is a thing gone wrong being carried along as though it were an outcome.
- Use tools to inspect the design before guessing about component names,
  positions, dimensions, interfaces, contacts, physics, evidence, or library
  contents.
- You may call several tools in one turn. A request such as 'make all the legs
  longer and thinner' should normally inspect/select the legs and then perform
  both edits. 'Make all the legs longer' must affect every matching leg, not
  only whichever part happens to be selected in the UI.
- Prefer semantic selectors (role/family) for requests like all legs, wheels,
  braces, shelves, etc. Use exact names when the user names a specific part.
- Geometry coordinates are metres in product-local 3D space. inspect_design
  returns every part's centre, size and rotation. inspect_component returns the
  component's interfaces and physical contacts.
- inspect_physics exposes measured mass/balance/support, analytical load
  evidence, ProductGraph relationships and the reduced PhysicsContract.
- search_library can find reusable components by name/role/family/physics tags.
- what_it_needs answers what MAKING the design would take in materials, what
  the rack holds and what is short. Call it whenever the person asks what a
  design needs, what else they need, whether they can make it, or what it
  costs, and after an edit that changes size or material when they are asking
  about making it. Designing, measuring and bench-testing are free whatever the
  rack holds; only making it draws stock. Report a shortfall in the material
  and the kilograms, and never shrink or re-material a design to fit the rack
  unless the person asks for that.
- HOW IT LOOKS is set_skin, and it is separate from what it is. Profile,
  colour, roughness and metalness dress a component without touching its mass,
  its joints or anything the bench measured. Reach for it when someone wants a
  thing to look better rather than work differently, and name real components
  or a role rather than reskinning everything by reflex. Only pass physical
  true when they want the SHAPE changed, and tell them it makes earlier
  measurements stale.
- BUILDING SOMETHING FROM PARTS: add_part puts a component in and fastens it,
  set_joint changes how two parts are fastened, remove_part takes one out. A
  part must TOUCH what it fastens to -- place it face to face against that part,
  because a gap is refused and the message tells you so. Use 'bearing' for
  anything meant to turn on another part (a wheel on its mount, a door leaf on
  its post, a pulley on its pin) and 'fixed' for anything bonded solid. Build
  the concept first and do not agonise over millimetres.
- KEEPING IT: save_design writes the design down under a name you choose, and
  saving the same name again is a new revision of it rather than a second
  thing. list_saved_designs says what is there, and open_saved_design brings
  one back -- which REPLACES what is on the bench, so ask first unless they
  said to. take_it_back undoes the last change, or several. These were panels
  on the page once; they are yours now, so a person who asks you to "save this
  as the tall one" gets it saved rather than pointed at a control.
- DROPPING SOMETHING ON IT is try_it_in_a_room with load_kg and from_m. `strike`
  throws a block at its SIDE, along the floor, and is not what anyone means by
  "drop a block on it"; `drop_m` lets go of the THING, not of something onto it.
- TESTING MEANS FINDING THE RANGE, NOT POKING IT ONCE. What anybody wants to
  know is where a thing changes: it holds 120 kg, cracks at 300, shatters at
  500. One run only tells you whether the number you guessed was over or under,
  so DO NOT stop at one. Call find_the_limit and sweep the thing that matters
  up through five or six values. It is fast -- a run is about a third of a
  second -- and the answer is the useful one.
  Do the same for anything with a range: a solar panel gives nothing in the
  dark, a little at daybreak and a lot at noon, and a sweep over the hour says
  so in one turn. Report the whole range, not the one number you tried.
- WORK IT BY HAND with `do`: a list of {at_s, control, power, direction,
  setting} carried out while it runs, which is what a person does at a
  machine's panel in the world. "Drive it forward for three seconds and then
  stop" is two orders at 0 s and two at 3 s. turn_on starts its OWN program
  instead; do not do both unless you mean them to fight.
- WRITE THE ROOM when none of those is the test. try_it_in_a_room takes `add`:
  anything you can describe standing in the world beside the thing -- a ramp
  tilted 20 degrees, a ball already rolling at 3 m/s, a wall driven into the
  ground for it to hit. Say what it is made of, how big, where, which way up
  and how fast it is already going. HEIGHT IS MEASURED FROM THE GROUND, so 0 is
  resting on it. Build the test you were actually asked for rather than the
  nearest of the four settings: "roll a ball down a ramp into its leg" is a
  ramp and a ball, not a thrown block.
- MAKING IT GO: add_power_part puts a store, motor, panel or control on the
  design and set_program says what it does on its own. A motor names the two
  components its pin joins and that pin MUST be a bearing -- a bond cannot
  turn -- and it draws on a store you have already added. A panel sits on a
  component and faces the way that component faces. Build the machine the same
  way you build the shape: say what is there, then let check_validity tell you
  whether it is wired to anything real. It names a motor driving a bonded
  joint, or drawing on a store that is not there, rather than quietly fixing it.
- THEN CALL check_validity. The room carries matter on a 40 mm cell grid, and
  sizes that read well to a person are usually not sizes the grid can hold. It
  redraws what it must and tells you every change: a part thinner than two cells
  is drawn thicker, faces are snapped to cell boundaries, a shaft that runs
  THROUGH its mounts becomes a stub per bearing (no lattice body can carry a
  hole for another to turn inside -- this is true at every cell size), a moving
  group is made of one material, and a strut is rebuilt between its anchors.
- What check_validity will NOT do is invent a concept that is missing. A part
  fastened to nothing, or a wheel with nothing to turn on, comes back refused
  with the reason. Fix the assembly and call it again; never talk around it.
- Never say a thing turns, swings, rolls or works until check_validity has said
  ok. Before that you know what was drawn, not what the room can carry. When it
  has redrawn something, tell the person what changed and why, in its words.
- Edits are deterministic tools. Do not fabricate geometry or silently change
  unrelated components.
- Ambiguity is not a reason to ask. It is a reason to pick, do it, and say in
  one line what you picked -- "glass everywhere, top and legs; say the word if
  you meant the top only". The person can take it back.
- Explain what actually changed, using real component names/counts from tool
  results. Distinguish analytical estimates from engine evidence.
"""


def _history(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for row in value[-MAX_HISTORY:]:
        if not isinstance(row, dict) or row.get("role") not in {"user", "assistant"}:
            continue
        text = " ".join(str(row.get("content") or "").split())[:4000]
        if text:
            rows.append({"role": str(row["role"]), "content": text})
    return rows


def _spec(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": str(candidate.get("kind") or ""),
        "design_id": str(candidate.get("design_id") or candidate.get("kind") or "candidate"),
        "purpose": candidate.get("purpose"),
        "parameters": dict(candidate.get("parameters") or {}),
        "component_overrides": deepcopy(candidate.get("component_overrides") or {}),
    }


def _refresh(app: Any, candidate: dict[str, Any], design: Any,
             overrides: dict[str, dict[str, Any]]) -> None:
    """Replace one candidate dictionary from the authoritative Workshop model."""
    prior_label = candidate.get("label")
    wire = design.wireframe()
    wire["component_overrides"] = workshop_components.checked_overrides(overrides)
    if prior_label:
        wire["label"] = prior_label
    try:
        wire["analytical"] = {"static_loads": declared_statics(design), "limitations": []}
    except ValueError as problem:
        wire["analytical"] = {"static_loads": [], "limitations": [str(problem)]}
    wire["bom"] = workshop_library.bill_of_materials(app, design)
    candidate.clear()
    candidate.update(wire)


def _round_along(axis: Any, size: list[float]) -> tuple[str, tuple[float, float, float], list[float]]:
    """A round part, said the way a person says it.

    The chat gives every part the box it fills, which is what a person sees. A
    cylinder is drawn in its own frame instead -- diameter, length, diameter,
    about its own y -- and turned onto the axis it lies along, so this does that
    turning rather than asking the model for three Euler angles. Without it the
    chat could only make boxes, and a robot it designed had square wheels: the
    library has carried cylinders all along (workshop_construction.checked) and
    only this tool could not say one.
    """
    if not axis:
        return "box", (0.0, 0.0, 0.0), size
    along = str(axis).lower()
    if along not in ("x", "y", "z"):
        raise ValueError("round_along is x, y or z: the axis the cylinder lies along")
    a = "xyz".index(along)
    across = [size[i] for i in range(3) if i != a]
    if abs(across[0] - across[1]) > 1e-9:
        raise ValueError(f"a part round along {along} is as wide as it is deep across that axis, and this one "
                         f"is {across[0] * 1000:.0f} mm by {across[1] * 1000:.0f} mm")
    # Its own frame: as round as it is across, as long as it is along.
    drawn = [across[0], size[a], across[0]]
    turn = {"x": (0.0, 0.0, 90.0), "y": (0.0, 0.0, 0.0), "z": (90.0, 0.0, 0.0)}[along]
    return "cylinder", turn, drawn


def _part_doc(part: Any) -> dict[str, Any]:
    return {
        "name": part.name, "role": part.role, "family": part.family,
        "material": part.material, "shape": part.shape,
        "center_m": [round(float(v), 6) for v in part.center_m],
        "size_m": [round(float(v), 6) for v in part.size_m],
        "rotation_deg": [round(float(v), 4) for v in part.rotation_deg],
    }


def _selector_names(design: Any, selector: Any, selected_name: str | None) -> list[str]:
    selector = selector if isinstance(selector, dict) else {}
    names = {str(v) for v in (selector.get("names") or []) if str(v)}
    roles = {str(v).lower() for v in (selector.get("roles") or []) if str(v)}
    families = {str(v).lower() for v in (selector.get("families") or []) if str(v)}
    if not names and not roles and not families:
        if selected_name:
            names = {selected_name}
        else:
            raise ValueError("choose a component name, role or family")
    out = []
    for part in design.parts:
        if names and part.name not in names:
            continue
        if roles and str(part.role).lower() not in roles:
            continue
        if families and str(part.family or "").lower() not in families:
            continue
        out.append(part.name)
    missing = names - {part.name for part in design.parts}
    if missing:
        raise ValueError("unknown component name(s): " + ", ".join(sorted(missing)))
    if not out:
        raise ValueError("that selector matches no components in the current design")
    return out


def _tool_definitions(materials: list[str]) -> list[dict[str, Any]]:
    selector = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "names": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
            "roles": {"type": "array", "items": {"type": "string"}, "maxItems": 40},
            "families": {"type": "array", "items": {"type": "string"}, "maxItems": 40},
        },
    }
    return [
        {"type": "function", "name": "define_interaction_points",
         "description": "Define the product's key interactions in design-local metres. grip/use points and surface/container receiving floors; size_m is usable width/height/depth above the floor. Does not add geometry.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["points"],
                        "properties": {"points": interaction_points.LIST_SCHEMA}}},
        {"type": "function", "name": "program_use",
         "description": "Program the product's single core Use on Left mouse / J. Physical bounded steps; never arbitrary code. strike and place require holding it; place uses the visible contextual destination. push_forward requires an empty hand. Use inspect for a passive product, not as a pretend machine function.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["label", "steps"],
                        "properties": {
                            "label": {"type": "string", "minLength": 1, "maxLength": 60},
                            "steps": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
                                "type": "object", "additionalProperties": False, "required": ["do"],
                                "properties": {"do": {"type": "string", "enum": ["inspect", "strike", "push_forward", "place"]},
                                               "distance_m": {"type": "number"},
                                               "speed_m_s": {"type": "number"}}}}}}},
        {"type": "function", "name": "inspect_design",
         "description": "Inspect the complete current Workshop candidate including every component's 3D centre, size, rotation and measured design metrics.",
         "parameters": {"type": "object", "additionalProperties": False, "properties": {}}},
        {"type": "function", "name": "inspect_component",
         "description": "Inspect one named component, its 3D geometry, interfaces, physics tags, capabilities and touching components.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "required": ["name"], "properties": {"name": {"type": "string"}}}},
        {"type": "function", "name": "inspect_physics",
         "description": "Inspect mass/balance/support, analytical static-load evidence, ProductGraph relationships and the reduced PhysicsContract.",
         "parameters": {"type": "object", "additionalProperties": False, "properties": {}}},
        {"type": "function", "name": "add_part",
         "description": "Put one new component into the design and fasten it. size_m is [width, height, depth] "
                        "in metres and center_m is its middle in the design frame. It must TOUCH the part it "
                        "fastens to -- move it against that part first, face to face; a gap is refused. "
                        "kind is 'fixed' for a part bonded solid, or 'bearing' for one that turns on the other "
                        "(a wheel, a door leaf, a pulley). round_along makes it a cylinder lying along that "
                        "axis -- a wheel that rolls forward is round along x, the axis across the machine. A "
                        "bearing turns about the face the two parts meet on, so a wheel goes against the side "
                        "of its mount and a thing that swivels goes under a flat face. Do not fret about the "
                        "millimetres: call "
                        "check_validity when the assembly is complete and it redraws whatever the room's cell "
                        "grid cannot carry.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "required": ["name", "role", "size_m", "center_m"],
                        "properties": {
                            "name": {"type": "string"},
                            "role": {"type": "string",
                                     "description": "what it is: post, beam, brace, panel, surface, top, leg, "
                                                    "wheel, axle, bearing_mount, handle, drum, rope"},
                            "size_m": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                            "center_m": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                            "material": {"type": "string", "enum": list(materials)},
                            "fasten_to": {"type": "string", "description": "the part it is fastened to"},
                            "kind": {"type": "string", "enum": ["fixed", "bearing"]},
                            "round_along": {"type": "string", "enum": ["x", "y", "z"],
                                            "description": "leave it out for a box; give the axis it is round "
                                                           "about to make it a cylinder"}}}},
        {"type": "function", "name": "remove_part",
         "description": "Take one component out of the design, with whatever fastened it.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["name"],
                        "properties": {"name": {"type": "string"}}}},
        {"type": "function", "name": "set_joint",
         "description": "Fasten two parts that touch, change how they are fastened, or unfasten them. "
                        "kind 'fixed' bonds them solid, 'bearing' lets one turn on the other, and leaving kind "
                        "out unfastens them.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["a", "b"],
                        "properties": {"a": {"type": "string"}, "b": {"type": "string"},
                                       "kind": {"type": "string", "enum": ["fixed", "bearing"]}}}},
        {"type": "function", "name": "set_skin",
         "description": "Change how chosen components LOOK: their shape profile, colour and finish. "
                        "profile 'design' keeps the built shape, 'block' squares it off, 'round' turns it "
                        "on its long axis, and 'curve' bends it by bend_m. colour is a CSS colour. "
                        "roughness 0 is a mirror and 1 is matt; metalness 1 reads as bare metal. "
                        "By default this is appearance only and changes nothing physical -- the mass, the "
                        "joints and the bench results all stay as they were. Pass physical true ONLY when "
                        "the person wants the shape itself changed, and say so when you do, because it "
                        "makes every earlier measurement stale.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["selector"],
                        "properties": {
                            "selector": selector,
                            "profile": {"type": "string", "enum": ["design", "block", "round", "curve"]},
                            "color": {"type": "string", "maxLength": 32},
                            "roughness": {"type": "number", "minimum": 0, "maximum": 1},
                            "metalness": {"type": "number", "minimum": 0, "maximum": 1},
                            "bend_m": {"type": "number", "minimum": -5, "maximum": 5},
                            "physical": {"type": "boolean"}}}},
        {"type": "function", "name": "add_power_part",
         "description": "Put a store, motor, panel or control on the design. A MOTOR names the two "
                        "components its pin joins, exactly as a wheel and the mount it turns in -- it "
                        "must be a bearing, because a bond cannot turn -- and the store it draws on. A "
                        "STORE sits in a component and holds joules. A PANEL sits on a component, faces "
                        "the way that component faces, and charges a store. A CONTROL names a pin so a "
                        "program can work it. Nothing is guessed: naming a joint that does not turn, or "
                        "a store that is not there, comes back refused.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["kind"],
                        "properties": {
                            "kind": {"type": "string", "enum": ["store", "motor", "panel", "control"]},
                            "name": {"type": "string"},
                            "in": {"type": "string", "description": "for a store: the component it sits in"},
                            "on": {"type": "string", "description": "for a panel: the component it sits on"},
                            "turns": {"type": "array", "items": {"type": "string"}, "minItems": 2,
                                      "maxItems": 2,
                                      "description": "for a motor or control: the two components its pin joins"},
                            "store": {"type": "string", "description": "for a motor or panel: the store it uses"},
                            "capacity_j": {"type": "number"}, "charge_j": {"type": "number"},
                            "voltage_v": {"type": "number"},
                            "stall_torque_n_m": {"type": "number"}, "no_load_rpm": {"type": "number"},
                            "brake_torque_n_m": {"type": "number"},
                            "area_m2": {"type": "number"}, "efficiency": {"type": "number"}}}},
        {"type": "function", "name": "set_program",
         "description": "What the machine does on its own. 'drive' runs until something stops it; 'roam' "
                        "wanders and turns away from water; 'sit' goes to a thing already standing in the "
                        "world and holds a pose there. left and right name controls. climb_deg is "
                        "the steepest ground it will take, rest_below the share of charge it stops at and "
                        "rest_until the share it sets off again at. For 'sit': toward is the world's name "
                        "for the thing it goes to, close_m how near its middle comes to that thing's middle "
                        "across the ground, and pose/pose_deg the control it works when it gets there and "
                        "the angle it turns that pin to. A product runs one program.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "required": ["kind", "left", "right"],
                        "properties": {
                            "kind": {"type": "string", "enum": ["roam", "drive", "sit"]},
                            "left": {"type": "string"}, "right": {"type": "string"},
                            "setting": {"type": "number", "minimum": 0, "maximum": 1},
                            "climb_deg": {"type": "number", "minimum": 0, "maximum": 89},
                            "rest_below": {"type": "number", "minimum": 0, "maximum": 1},
                            "rest_until": {"type": "number", "minimum": 0, "maximum": 1},
                            "toward": {"type": "string"},
                            "close_m": {"type": "number", "minimum": 0.01, "maximum": 100},
                            "pose": {"type": "string"},
                            "pose_deg": {"type": "number", "minimum": -360, "maximum": 360}}}},
        {"type": "function", "name": "try_it_in_a_room",
         "description": "Make the design in a little room with real ground, gravity and a sky, let it run, and "
                        "say what happened. It is the world's own physics and the world's own way of making a "
                        "thing, so what it does here is what it will do out there. Put the sun where you like -- "
                        "leave it out for noon, or give a day with an hour for the afternoon or the dark -- and "
                        "stand other things in the room to test it against. Call this to answer whether "
                        "something WORKS, rather than guessing from its shape. Call check_validity first.",
         "parameters": {"type": "object", "additionalProperties": False, "properties": {
                            "seconds": {"type": "number", "minimum": 0.5, "maximum": 120,
                                        "description": "how long to let it run"},
                            "day": {"type": "object", "additionalProperties": False,
                                    "description": "a sky with a day it crosses; hour 23 is the dark",
                                    "properties": {"day_s": {"type": "number"},
                                                   "noon_elevation_deg": {"type": "number"},
                                                   "hour": {"type": "number", "minimum": 0, "maximum": 23.99},
                                                   "irradiance_w_m2": {"type": "number"}}},
                            "add": {"type": "array", "maxItems": 12,
                                    "description": "things YOU write into the room, beside the design",
                                    "items": {"type": "object", "additionalProperties": False,
                                              "required": ["size_m", "at_m"],
                                              "properties": {
                                                  "name": {"type": "string",
                                                           "description": "what to call it, e.g. 'the ramp'"},
                                                  "shape": {"type": "string",
                                                            "enum": ["box", "sphere", "cylinder"]},
                                                  "material": {"type": "string",
                                                               "enum": ["oak", "iron", "concrete", "glass"]},
                                                  "size_m": {"type": "array", "minItems": 3, "maxItems": 3,
                                                             "items": {"type": "number"},
                                                             "description": "x, y, z in metres; a cylinder is [across, along, across]"},
                                                  "at_m": {"type": "array", "minItems": 3, "maxItems": 3,
                                                           "items": {"type": "number"},
                                                           "description": "x, HEIGHT ABOVE THE GROUND, z. 0 is resting on it."},
                                                  "tilt_deg": {"type": "array", "minItems": 3, "maxItems": 3,
                                                               "items": {"type": "number"},
                                                               "description": "degrees about x, y, z; a tilted thing is an exact body"},
                                                  "moving_m_s": {"type": "array", "minItems": 3, "maxItems": 3,
                                                                 "items": {"type": "number"},
                                                                 "description": "how fast it is already going"},
                                                  "fixed": {"type": "boolean",
                                                            "description": "driven into the ground; cannot move or be tilted"}}}},
                            "items": {"type": "array", "maxItems": 6, "description": "four things it already knows how to make",
                                      "items": {"type": "object", "additionalProperties": False,
                                                "required": ["what"],
                                                "properties": {"what": {"type": "string",
                                                                        "enum": sorted(test_room.THINGS)},
                                                               "at_m": {"type": "array", "items": {"type": "number"},
                                                                        "minItems": 2, "maxItems": 2}}}},
                            "turn_on": {"type": "boolean",
                                        "description": "set its program running, if it has one (default true)"},
                            "do": {"type": "array", "maxItems": 24,
                                   "description": "what to do to its controls while it runs, by hand",
                                   "items": {"type": "object", "additionalProperties": False,
                                             "required": ["control"],
                                             "properties": {
                                                 "at_s": {"type": "number", "minimum": 0,
                                                          "description": "how far into the run (0)"},
                                                 "control": {"type": "string",
                                                             "description": "its name, from check_validity or inspect_physics"},
                                                 "power": {"type": "boolean", "description": "on (default true)"},
                                                 "direction": {"type": "integer", "enum": [-1, 0, 1]},
                                                 "setting": {"type": "number", "minimum": 0, "maximum": 1}}}},
                            # What to DO to it, once it is standing there. Leave
                            # them all out and it simply stands, which answers
                            # whether it stands.
                            "load_kg": {"type": "number", "minimum": 0, "maximum": test_room.MAX_LOAD_KG,
                                        "description": "set an iron weight of this many kilograms on it"},
                            "on": {"type": "string",
                                   "description": "the name of the part to set the weight on; the whole thing by default"},
                            "from_m": {"type": "number", "minimum": 0, "maximum": 5,
                                       "description": "DROP that weight on it from this height instead of "
                                                      "setting it there. This is how you drop something ON "
                                                      "a thing; `strike` throws a block at its SIDE."},
                            "drop_m": {"type": "number", "minimum": 0, "maximum": test_room.MAX_DROP_M,
                                       "description": "let it go from this far above where it stands"},
                            "slide_m_s": {"type": "number", "minimum": -test_room.MAX_SPEED_M_S,
                                          "maximum": test_room.MAX_SPEED_M_S,
                                          "description": "start it moving along +X at this speed"},
                            "strike": {"type": "object", "additionalProperties": False,
                                       "description": "throw an iron block at it",
                                       "properties": {"kg": {"type": "number", "minimum": 0.1,
                                                             "maximum": test_room.MAX_STRIKER_KG},
                                                      "speed_m_s": {"type": "number", "minimum": 0.1,
                                                                    "maximum": test_room.MAX_SPEED_M_S},
                                                      "height_fraction": {"type": "number", "minimum": 0,
                                                                          "maximum": 1}}}}}},
        {"type": "function", "name": "save_design",
         "description": "Write the design down under a name. Saving the same design again is a new "
                        "revision of it, not a second one. Use the name the person used.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["name"],
                        "properties": {"name": {"type": "string",
                                                "description": "what to call it, in their words"}}}},
        {"type": "function", "name": "list_saved_designs",
         "description": "What has been saved, newest first: the name, what it is, how many times it "
                        "was saved and its id. Call this before opening one by name.",
         "parameters": {"type": "object", "additionalProperties": False, "properties": {}}},
        {"type": "function", "name": "open_saved_design",
         "description": "Bring a saved design back onto the bench. This REPLACES what is there now, "
                        "so say what you are about to lose unless they already said to.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["design_id"],
                        "properties": {"design_id": {"type": "string",
                                                     "description": "from list_saved_designs"}}}},
        {"type": "function", "name": "take_it_back",
         "description": "Undo the last change to the design, or several. The bench remembers every "
                        "state of this session, so this reaches back past your own turn.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "properties": {"steps": {"type": "integer", "minimum": 1, "maximum": 20,
                                                 "description": "how many changes to take back (1)"}}}},
        {"type": "function", "name": "find_the_limit",
         "description": "Run the same test again and again with ONE thing turned up, and say "
                        "where it changes: holds here, cracks there, shatters beyond. This is what "
                        "testing is for; a single run only says whether one guess was over or "
                        "under. Also the way to show a range -- sweep the hour to show a panel "
                        "giving nothing in the dark and a lot at noon. Every row is a real run; "
                        "nothing is interpolated. Fast: a run is about a third of a second.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "required": ["changing", "over"],
                        "properties": {
                            "changing": {"type": "string",
                                         "enum": sorted(test_room.SWEEPS),
                                         "description": "the one thing to turn up"},
                            "over": {"type": "array", "minItems": 2, "maxItems": 12,
                                     "items": {"type": "number"},
                                     "description": "the values to try, going up"},
                            "seconds": {"type": "number", "minimum": 0.5, "maximum": 30,
                                        "description": "how long each run is (3)"},
                            "load_kg": {"type": "number", "minimum": 0, "maximum": 2000},
                            "from_m": {"type": "number", "minimum": 0, "maximum": 5},
                            "drop_m": {"type": "number", "minimum": 0, "maximum": 5},
                            "slide_m_s": {"type": "number", "minimum": -30, "maximum": 30},
                            "strike_kg": {"type": "number", "minimum": 0, "maximum": 500},
                            "strike_speed_m_s": {"type": "number", "minimum": 0, "maximum": 30},
                            "hour": {"type": "number", "minimum": 0, "maximum": 24},
                            "turn_on": {"type": "boolean"}}}},
        {"type": "function", "name": "ask_the_person",
         "description": "Ask the person a question you cannot answer yourself, with concrete "
                        "answers they can click. ALWAYS use this instead of asking in prose. "
                        "Ends your turn; their answer arrives as the next message. Put the "
                        "option you would choose first.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "required": ["question", "options"],
                        "properties": {
                            "question": {"type": "string",
                                         "description": "one sentence, ending in a question mark"},
                            "options": {"type": "array", "minItems": 2, "maxItems": 6,
                                        "description": "concrete answers, best first",
                                        "items": {"type": "object", "additionalProperties": False,
                                                  "required": ["label"],
                                                  "properties": {
                                                      "label": {"type": "string",
                                                                "description": "what the button says, e.g. 'Make it 50 mm'"},
                                                      "why": {"type": "string",
                                                              "description": "at most a dozen words on what it would mean"}}}},
                            "several": {"type": "boolean",
                                        "description": "true when more than one option can be picked at once"}}}},
        {"type": "function", "name": "check_validity",
         "description": "Say whether this assembly is a machine, and redraw it until the room can carry it. "
                        "It checks the concepts first -- every part fastened, every wheel with something to "
                        "turn on, something standing still for the rest to move against -- and refuses, "
                        "naming what is missing, rather than inventing it. Then it redraws: nothing thinner "
                        "than two cells, every face on a cell boundary, a shaft that runs through its mounts "
                        "becomes a stub per bearing, one material to a moving group, and a strut rebuilt "
                        "between its anchors. It returns every change and why. Call this whenever the person "
                        "asks whether something works, before saying a design is finished, and always before "
                        "claiming anything about it turning, swinging or rolling.",
         "parameters": {"type": "object", "additionalProperties": False, "required": [], "properties": {}}},
        {"type": "function", "name": "what_it_needs",
         "description": "What making the current design would take in materials, what the rack holds, and what is short. "
                        "Call this whenever the person asks what a design needs, what else they need, whether they can "
                        "make it, or what it would cost. Designing and bench-testing cost nothing; only making it draws "
                        "on the rack, so a shortfall is a fact to report, never a reason to change the design unasked.",
         "parameters": {"type": "object", "additionalProperties": False, "required": [], "properties": {}}},
        {"type": "function", "name": "list_materials",
         "description": "List materials currently available to Workshop component edits.",
         "parameters": {"type": "object", "additionalProperties": False, "properties": {}}},
        {"type": "function", "name": "search_library",
         "description": "Search My Library for reusable components/assemblies by text, role, family or physics tag.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "properties": {"text": {"type": "string"}, "role": {"type": "string"},
                                       "family": {"type": "string"}, "physics_tag": {"type": "string"}}}},
        {"type": "function", "name": "edit_components",
         "description": "Apply one deterministic edit to every component matching the selector. Call repeatedly for several edits in one user turn.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "required": ["selector", "action"],
                        "properties": {"selector": selector,
                                       "action": {"type": "string", "enum": list(EDIT_ACTIONS)},
                                       "amount": {"type": "number", "minimum": 0.01, "maximum": 0.8},
                                       "material": {"type": ["string", "null"], "enum": [None, *materials]}}}},
        {"type": "function", "name": "set_parameter",
         "description": "Change one assembly-level Workshop parameter such as width, height, splay, shelf count or wheel diameter.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "required": ["name", "value"],
                        "properties": {"name": {"type": "string"},
                                       "value": {"type": ["string", "number", "boolean"]}}}},
        {"type": "function", "name": "reuse_library_component",
         "description": "Replace every matching target component with one compatible saved component from My Library.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "required": ["selector", "item_id"],
                        "properties": {"selector": selector, "item_id": {"type": "string"}}}},
    ]


class _State:
    def __init__(self, app: Any, candidate: dict[str, Any], selected_name: str | None,
                 materials: list[str], library: list[dict[str, Any]],
                 turn: str | None = None) -> None:
        self.app = app
        #: Which turn this is, so what it does can be watched while it happens.
        self.turn = turn
        #: How many times each tool has refused in this turn.
        self.refused: dict[str, int] = {}
        self.candidate = candidate
        self.selected_name = selected_name
        self.materials = materials
        self.library = library
        spec = _spec(candidate)
        self.design, self.overrides = workshop_components.design_from_spec(spec)
        # The template the overrides sit on. Every redraw is the template plus
        # one set of overrides, never a patch on top of a patched design.
        self.base = assemble(str(spec.get("kind") or ""),
                             design_id=str(spec.get("design_id") or spec.get("kind") or "design"),
                             purpose=(str(spec["purpose"]) if spec.get("purpose") else None),
                             parameters=spec.get("parameters") or {})
        self.changed: list[str] = []
        self.trace: list[dict[str, Any]] = []
        #: The question this turn is waiting on, if it asked one.
        self.asking: dict[str, Any] | None = None
        #: A run for the person to watch, if the turn tried the thing out.
        self.showing: dict[str, Any] | None = None
        #: How many changes the page is being asked to take back.
        self.undo: int = 0

    def current_spec(self) -> dict[str, Any]:
        return {"kind": self.design.kind, "design_id": self.design.design_id,
                "purpose": self.design.purpose, "parameters": dict(self.design.parameters),
                "component_overrides": deepcopy(self.overrides)}

    def record(self, tool: str, result: dict[str, Any], *, ok: bool = True) -> dict[str, Any]:
        summary = result.get("summary") or result.get("error") or tool
        self.trace.append({"tool": tool, "ok": ok, "summary": str(summary)[:500]})
        _note(self.turn, f"{DOING.get(tool, tool)}: {str(summary)[:120]}", ok=ok)
        return result

    def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "save_design":
            import workshop_store
            from workshop_api_core import _store
            name = " ".join(str(args.get("name") or "").split())[:160]
            if not name:
                raise ValueError("a saved design needs a name")
            record = workshop_store.save(_store(self.app), self.design,
                                         label=name, world_revision=None)
            return self.record(tool, {
                "summary": f"saved as {record['label']!r} ({record['design_id']}), "
                           f"revision {record['revision']}",
                "design_id": record["design_id"], "revision": record["revision"],
                "label": record["label"]})

        if tool == "list_saved_designs":
            import workshop_store
            from workshop_api_core import _store
            rows = workshop_store.list_saved(_store(self.app), limit=40)
            return self.record(tool, {
                "summary": f"{len(rows)} saved" if rows else "nothing has been saved yet",
                "saved": [{"design_id": r.get("design_id"), "name": r.get("label"),
                           "kind": r.get("kind"), "times_saved": r.get("revision"),
                           "saved_at": r.get("saved_at")} for r in rows]})

        if tool == "open_saved_design":
            import workshop_store
            from workshop_api_core import _store
            design_id = str(args.get("design_id") or "")
            record, design = workshop_store.load(_store(self.app), design_id)
            # The candidate the API owns is replaced in place, the same way an
            # edit replaces it, so the page draws what came back without any
            # second route through the server.
            self.design = design
            self.overrides = workshop_components.checked_overrides(
                record.get("component_overrides") or design.lineage.get("component_overrides") or {})
            self.base = assemble(str(record["kind"]), design_id=str(record["design_id"]),
                                 purpose=(str(record.get("purpose")) if record.get("purpose") else None),
                                 parameters=dict(record.get("parameters") or {}))
            _refresh(self.app, self.candidate, self.design, self.overrides)
            self.changed = [part.name for part in self.design.parts]
            return self.record(tool, {
                "summary": f"opened {record.get('label') or design_id}: "
                           f"{len(self.design.parts)} parts",
                "design_id": design_id, "name": record.get("label"), "kind": record["kind"]})

        if tool == "take_it_back":
            # The bench keeps every state of the session and this turn does not,
            # so the page does the undoing. What comes back here is the
            # instruction; the page carries it out when the turn lands.
            steps = max(1, min(20, int(args.get("steps") or 1)))
            self.undo = steps
            return self.record(tool, {
                "summary": f"taking back the last {steps} change" + ("" if steps == 1 else "s"),
                "steps": steps})

        if tool == "ask_the_person":
            # A question is not work done to the design, so it ends the turn
            # rather than going round the loop again. What it leaves behind is
            # read by _model_turn, which stops there.
            question = " ".join(str(args.get("question") or "").split())[:400]
            if not question:
                raise ValueError("a question needs asking in words")
            options = []
            for raw in (args.get("options") or [])[:6]:
                label = " ".join(str((raw or {}).get("label") or "").split())[:120]
                if not label:
                    continue
                why = " ".join(str((raw or {}).get("why") or "").split())[:160]
                options.append({"label": label, **({"why": why} if why else {})})
            if len(options) < 2:
                raise ValueError("ask_the_person needs at least two answers they can click; "
                                 "an open question is what this tool exists to avoid")
            self.asking = {"question": question, "options": options,
                           "several": bool(args.get("several")),
                           # Writing their own is never taken away. It is what
                           # makes a suggested answer a suggestion.
                           "allow_other": True}
            return self.record(tool, {"summary": question,
                                      "options": [o["label"] for o in options]})

        if tool == "inspect_design":
            measured = self.design.measure()
            return self.record(tool, {
                "summary": f"{len(self.design.parts)} components; {measured.get('mass_kg')} kg",
                "kind": self.design.kind, "purpose": self.design.purpose,
                "parameters": dict(self.design.parameters), "measured": measured,
                "components": [_part_doc(part) for part in self.design.parts],
                "selected_component": self.selected_name,
            })

        if tool == "inspect_component":
            name = str(args.get("name") or "")
            part = next((p for p in self.design.parts if p.name == name), None)
            if part is None:
                raise ValueError(f"there is no component {name!r}")
            graph = workshop_graph.graph(self.design)
            node = next(n for n in graph["nodes"] if n["id"] == name)
            return self.record(tool, {
                "summary": f"{name}: {part.role} at {list(part.center_m)}",
                "component": _part_doc(part), "interfaces": node.get("interfaces") or [],
                "physics_tags": node.get("physics_tags") or [],
                "capabilities": node.get("capabilities") or [],
                "contacts": workshop_graph.contacts_of(graph, name),
            })

        if tool == "inspect_physics":
            graph = workshop_graph.product(self.design)
            try:
                statics = declared_statics(self.design)
                limitations: list[str] = []
            except ValueError as problem:
                statics, limitations = [], [str(problem)]
            contract = compile_contract(graph)
            return self.record(tool, {
                "summary": (f"{len(graph.components)} detailed components -> "
                            f"{len(contract['runtime_bodies'])} runtime bodies; "
                            f"{len(contract['mechanisms'])} mechanism DOFs"),
                "measured": self.design.measure(), "analytical_static_loads": statics,
                "analytical_limitations": limitations,
                "relationships": graph.described().get("relationships") or [],
                "physics_contract": contract,
                "declared_tests": deepcopy(self.design.tests),
            })

        if tool == "add_part":
            size = [float(v) for v in (args.get("size_m") or [])]
            centre = [float(v) for v in (args.get("center_m") or [])]
            if len(size) != 3 or len(centre) != 3:
                raise ValueError("size_m and center_m are each three numbers, in metres")
            role = str(args.get("role") or "beam")
            shape, turn, size = _round_along(args.get("round_along"), size)
            new = WirePart(name=str(args.get("name") or ""), role=role, size_m=tuple(size),
                           center_m=tuple(centre), material=str(args.get("material") or "oak"),
                           rotation_deg=turn, shape=shape, family=role)
            joint = None
            if args.get("fasten_to"):
                joint = {"to": str(args["fasten_to"]), "kind": str(args.get("kind") or "fixed")}
            self.overrides = workshop_construction.add_part(self.design, self.overrides,
                                                            part=new, joint=joint)
            self.design = workshop_components.apply_overrides(self.base, self.overrides)
            _refresh(self.app, self.candidate, self.design, self.overrides)
            self.changed.append(f"added:{new.name}")
            return self.record(tool, {
                "summary": f"added {new.name}" + (f", {joint['kind']} to {joint['to']}" if joint else ", unfastened"),
                "part": _part_doc(new), "parts_now": len(self.design.parts)})

        if tool == "remove_part":
            name = str(args.get("name") or "")
            self.overrides = workshop_construction.remove_part(self.design, self.overrides, name)
            self.design = workshop_components.apply_overrides(self.base, self.overrides)
            _refresh(self.app, self.candidate, self.design, self.overrides)
            self.changed.append(f"removed:{name}")
            return self.record(tool, {"summary": f"took {name} out",
                                      "parts_now": len(self.design.parts)})

        if tool == "set_joint":
            a, b = str(args.get("a") or ""), str(args.get("b") or "")
            kind = args.get("kind")
            self.overrides = workshop_construction.set_joint(
                self.design, self.overrides, a=a, b=b, kind=(str(kind) if kind else None))
            self.design = workshop_components.apply_overrides(self.base, self.overrides)
            _refresh(self.app, self.candidate, self.design, self.overrides)
            self.changed.append(f"joint:{a}-{b}")
            return self.record(tool, {
                "summary": (f"{a} and {b} are now {kind}" if kind else f"unfastened {a} from {b}"),
                "joints": workshop_construction.joints(self.design)})

        if tool == "set_skin":
            from mcp import workshop_visual
            names = _selector_names(self.design, args.get("selector"), self.selected_name)
            fields = {k: args[k] for k in ("profile", "color", "roughness", "metalness", "bend_m", "physical")
                      if args.get(k) is not None}
            if not fields:
                raise ValueError("say what to change about the skin: profile, color, roughness, "
                                 "metalness, bend_m or physical")
            for name in names:
                patch = dict(self.overrides.get(name) or {})
                skin = dict(patch.get("skin") or {})
                skin.update(fields)
                patch["skin"] = workshop_visual.checked_skin(skin)
                self.overrides = {**self.overrides, name: patch}
            self.design = workshop_components.apply_overrides(self.base, self.overrides)
            _refresh(self.app, self.candidate, self.design, self.overrides)
            self.changed.append("skin:" + ",".join(names))
            physical = bool(fields.get("physical"))
            return self.record(tool, {
                "summary": f"reskinned {len(names)} component(s): "
                           + ", ".join(f"{k}={v}" for k, v in sorted(fields.items())),
                "components": names, "skin": fields,
                "note": ("This changed the matter, so every measurement and bench result "
                         "taken before it is stale." if physical else
                         "Appearance only: the mass, the joints and the bench results are unchanged."),
            })

        if tool in ("add_power_part", "set_program"):
            record = dict(workshop_machines.of_overrides(self.overrides) or {})
            for key in ("stores", "motors", "panels", "controls", "programs"):
                record[key] = list(record.get(key) or [])
            if tool == "add_power_part":
                kind = str(args.get("kind") or "")
                fields = {k: v for k, v in args.items() if k != "kind" and v is not None}
                record[{"store": "stores", "motor": "motors",
                        "panel": "panels", "control": "controls"}[kind]].append(fields)
                said = f"added a {kind}"
            else:
                record["programs"] = [{k: v for k, v in args.items() if v is not None}]
                said = f"it runs a {args.get('kind')} program"
            checked = workshop_machines.checked(record)
            self.overrides = {**self.overrides, workshop_machines.MACHINES_KEY: checked}
            self.design = workshop_components.apply_overrides(self.base, self.overrides)
            _refresh(self.app, self.candidate, self.design, self.overrides)
            self.changed.append("power")
            described = workshop_machines.described(self.design)
            return self.record(tool, {
                "summary": f"{said}; it now has {described['says']}",
                "machines": {k: v for k, v in described.items() if k != "says"},
                "note": "Whether it is wired to anything real is check_validity's answer, not this one.",
            })

        if tool == "find_the_limit":
            changing = str(args.get("changing") or "")
            held = {k: v for k, v in args.items()
                    if k not in ("changing", "over", "seconds") and v is not None}
            held.pop(changing, None)
            found = test_room.sweep(
                self.app, {"kind": self.design.kind, "design_id": self.design.design_id,
                           "purpose": self.design.purpose, "parameters": dict(self.design.parameters),
                           "component_overrides": self.overrides},
                changing=changing, over=args.get("over") or (),
                seconds=float(args.get("seconds", 3.0)), **held)
            # The run worth looking at is played over the object, as one run is.
            self.showing = found.get("playback")
            return self.record(tool, {"summary": found["says"][:400], "sweep": changing,
                                      "runs": [{k: v for k, v in row.items() if k != "says"}
                                               for row in found["runs"]],
                                      "changed_at": found["changed_at"],
                                      "watching": found["watching"]})

        if tool == "try_it_in_a_room":
            answer = test_room.try_it(
                self.app, {"kind": self.design.kind, "design_id": self.design.design_id,
                           "purpose": self.design.purpose, "parameters": dict(self.design.parameters),
                           "component_overrides": self.overrides},
                seconds=float(args.get("seconds", 10.0)), day=args.get("day"),
                items=args.get("items") or (), add=args.get("add") or (),
                turn_on=bool(args.get("turn_on", True)),
                load_kg=float(args.get("load_kg") or 0.0), on=str(args.get("on") or "top"),
                from_m=float(args.get("from_m") or 0.0),
                drop_m=float(args.get("drop_m") or 0.0), slide_m_s=float(args.get("slide_m_s") or 0.0),
                strike=args.get("strike"), do=args.get("do") or (), record=True)
            # The person watches it. "Ask me to drop a bowling ball on the item"
            # and it will "do that and SHOW you": the recording goes to the page
            # and is played over the object, with one button back to the build.
            # It is deliberately not handed to the model -- sixty frames of body
            # poses is not something to reason over, and it would crowd out the
            # conversation it is meant to be part of.
            self.showing = answer.get("playback")
            return self.record(tool, {"summary": answer["says"][:400], "ran_for_s": answer["ran_for_s"],
                                      "did": answer["did"], "sky": answer["sky"], "made": answer["made"],
                                      "in_the_room": answer["in_the_room"],
                                      "worked": answer["worked"], "controls": answer["controls"],
                                      "where_everything_ended": {
                                          name: body["at_m"] for name, body in
                                          list(answer["ended"]["bodies"].items())[:24]},
                                      "broke": answer["broke"], "dented": answer["dented"],
                                      "fell_over": answer["fell_over"],
                                      "stores": answer["ended"]["stores"], "panels": answer["ended"]["panels"],
                                      "programs": answer["ended"]["programs"]})

        if tool == "check_validity":
            answer = workshop_fitting.check_validity(self.base, self.overrides, cell_m=0.04,
                                                     root=str(self.design.design_id or "assembly"))
            if answer["ok"] and answer["changes"]:
                self.overrides = answer["overrides"]
                self.design = workshop_components.apply_overrides(self.base, self.overrides)
                _refresh(self.app, self.candidate, self.design, self.overrides)
                self.changed.append("redrawn")
            return self.record(tool, {
                "summary": answer["says"][:400], "ok": answer["ok"], "stage": answer["stage"],
                "concepts": answer["concepts"],
                "changes": [{"rule": c["rule"], "part": c["part"], "says": c["says"]}
                            for c in answer["changes"]],
                "why": answer.get("why", ""),
                "note": ("It is a machine and the room can carry it." if answer["ok"] else
                         "It is not ready. Say what is missing; do not claim it works."),
            }, ok=answer["ok"])

        if tool == "what_it_needs":
            needs = workshop_library.what_it_needs(self.app, self.design)
            return self.record(tool, {
                "summary": needs["says"], "enough": needs["enough"],
                "materials": needs["materials"], "missing": needs["missing"],
                "material_cost": needs["material_cost"], "currency": needs["currency"],
                "basis": needs["basis"],
                "note": ("The rack covers this design." if needs["enough"] else
                         "It can still be drawn, measured and tried on the bench. It cannot be made."),
            })

        if tool == "list_materials":
            return self.record(tool, {"summary": f"{len(self.materials)} materials available",
                                      "materials": list(self.materials)})

        if tool == "search_library":
            text = str(args.get("text") or "").lower().strip()
            role = str(args.get("role") or "").lower().strip()
            family = str(args.get("family") or "").lower().strip()
            physics = str(args.get("physics_tag") or "").lower().strip().replace(" ", "_")
            rows = []
            for item in self.library:
                haystack = " ".join(str(item.get(k) or "") for k in ("name", "item_id", "role", "family")).lower()
                tags = item.get("tags") or {}
                if text and text not in haystack: continue
                if role and str(item.get("role") or "").lower() != role: continue
                if family and str(item.get("family") or "").lower() != family: continue
                if physics and physics not in set(tags.get("physics") or []): continue
                rows.append({k: item.get(k) for k in ("item_id", "item_type", "name", "family", "role", "version", "tags")})
                if len(rows) >= 30: break
            return self.record(tool, {"summary": f"{len(rows)} library matches", "items": rows})

        if tool == "edit_components":
            action = str(args.get("action") or "")
            if action not in EDIT_ACTIONS:
                raise ValueError("unknown component edit action")
            names = _selector_names(self.design, args.get("selector"), self.selected_name)
            amount = float(args.get("amount", 0.12))
            material = args.get("material")
            if action == "material":
                if material not in self.materials:
                    raise ValueError("material must come from the current Workshop material list")
            for name in names:
                self.design, self.overrides, _ = workshop_components.edit(
                    self.current_spec(), part_name=name, action=action, scope="this", amount=amount,
                    material=(str(material) if material is not None else None))
            self.changed.extend(name for name in names if name not in self.changed)
            _refresh(self.app, self.candidate, self.design, self.overrides)
            return self.record(tool, {"summary": f"{action} applied to {len(names)} component(s)",
                                      "changed": names, "action": action,
                                      "components": [_part_doc(next(p for p in self.design.parts if p.name == name))
                                                     for name in names]})

        if tool == "define_interaction_points":
            points = interaction_points.checked(args.get("points"))
            parameters = {**self.design.parameters, "interaction_points": points}
            base = assemble(str(self.design.kind), design_id=self.design.design_id,
                            purpose=self.design.purpose, parameters=parameters)
            self.design = workshop_components.apply_overrides(base, self.overrides)
            _refresh(self.app, self.candidate, self.design, self.overrides)
            self.changed.append("interaction_points")
            return self.record(tool, {"summary": "Defined interaction points", "points": points})

        if tool == "program_use":
            from mcp import core_use
            program = core_use.checked_program(args)
            parameters = {**self.design.parameters, "primary_use": program}
            base = assemble(str(self.design.kind), design_id=self.design.design_id,
                            purpose=self.design.purpose, parameters=parameters)
            self.design = workshop_components.apply_overrides(base, self.overrides)
            _refresh(self.app, self.candidate, self.design, self.overrides)
            self.changed.append("primary_use")
            return self.record(tool, {"summary": f"Use: {program['label']}", "primary_use": program})

        if tool == "set_parameter":
            name = str(args.get("name") or "")
            spec = assembly(str(self.design.kind or ""))
            known = {parameter.name for parameter in spec.parameters}
            if name not in known:
                raise ValueError(f"{name!r} is not an assembly parameter; available: {', '.join(sorted(known))}")
            parameters = dict(self.design.parameters); parameters[name] = args.get("value")
            base = assemble(str(self.design.kind), design_id=self.design.design_id,
                            purpose=self.design.purpose, parameters=parameters)
            self.design = workshop_components.apply_overrides(base, self.overrides)
            _refresh(self.app, self.candidate, self.design, self.overrides)
            self.changed.append(f"parameter:{name}")
            return self.record(tool, {"summary": f"set {name} to {self.design.parameters[name]!r}",
                                      "parameter": name, "value": self.design.parameters[name]})

        if tool == "reuse_library_component":
            item_id = str(args.get("item_id") or "")
            item = next((row for row in self.library if str(row.get("item_id")) == item_id), None)
            if item is None:
                item = workshop_library.load_item(self.app, item_id)
            if item.get("item_type") != "component":
                raise ValueError("reuse_library_component requires a component library item")
            names = _selector_names(self.design, args.get("selector"), self.selected_name)
            for name in names:
                self.design, self.overrides, _ = workshop_components.replace_with_recipe(
                    self.current_spec(), part_name=name, recipe=item["payload"], scope="this")
            self.changed.extend(name for name in names if name not in self.changed)
            _refresh(self.app, self.candidate, self.design, self.overrides)
            return self.record(tool, {"summary": f"reused {item.get('name') or item_id} on {len(names)} component(s)",
                                      "changed": names, "library_item_id": item_id})

        raise ValueError(f"unknown Workshop chat tool {tool!r}")


def _cut_short(response: dict[str, Any]) -> str:
    """Why a reply came back with no words, when the provider says why."""
    if str(response.get("status") or "") != "incomplete":
        return ""
    why = str((response.get("incomplete_details") or {}).get("reason") or "")
    return " (the reply hit its length limit)" if why == "max_output_tokens" else \
           (f" ({why})" if why else "")


def _extract_text(response: dict[str, Any]) -> str:
    texts = []
    for output in response.get("output") or []:
        for content in output.get("content") or []:
            if content.get("type") == "output_text":
                texts.append(str(content.get("text") or ""))
    return "".join(texts).strip()


def _call_model(app: Any, payload: dict[str, Any]) -> dict[str, Any]:
    req = request.Request("https://api.openai.com/v1/responses",
        data=json.dumps(payload, allow_nan=False).encode(), method="POST",
        headers={"Authorization": "Bearer " + app.api_key, "Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=60) as response:
            raw = response.read(512 * 1024 + 1)
    except error.HTTPError as exc:
        # Say WHY. Discarding the body left "Workshop chat failed (HTTP 400)"
        # as the only clue in the page, for an error whose cause was spelled
        # out plainly in the answer we threw away.
        try:
            said = json.loads(exc.read().decode("utf-8", "replace")).get("error") or {}
            because = " ".join(str(said.get("message") or "").split())[:300]
        except Exception:
            because = ""
        raise ValueError(
            f"Workshop chat failed (HTTP {exc.code})" + (f": {because}" if because else "")
        ) from None
    except (error.URLError, TimeoutError):
        raise ValueError("Workshop chat connection failed or timed out") from None
    if len(raw) > 512 * 1024:
        raise ValueError("Workshop chat response exceeded its size budget")
    return json.loads(raw)


def _carry(response: dict[str, Any]) -> list[dict[str, Any]]:
    """The model's own items to send back, when we carry the turn ourselves.

    Reasoning items are left out on purpose: they refer to state the provider
    kept, so replaying them is the same mistake as ``previous_response_id``.
    The tool calls and any text are what the next round actually needs.
    """
    return [item for item in (response.get("output") or [])
            if item.get("type") in {"function_call", "message"}]


def _what_it_is_looking_at(state: _State) -> str:
    """The design as it stands, so a simple edit needs no round trip to learn it.

    Every turn used to open by calling inspect_design, because the request said
    nothing about what was on the bench. Two to three seconds to be told five
    part names. They fit in a dozen lines.
    """
    measured = state.design.measure()
    rows = [f"ON THE BENCH: a {state.design.kind} called {state.design.design_id}, "
            f"{len(state.design.parts)} parts, {measured.get('mass_kg')} kg"
            + (f", for: {state.design.purpose}" if state.design.purpose else ""),
            f"SELECTED IN THE UI: {state.selected_name or 'nothing'}",
            "PARTS (name, what it is, what it is made of, size in mm, middle in mm):"]
    for part in state.design.parts:
        rows.append("  {}, {}, {}, {}, {}".format(
            part.name, part.role, part.material,
            "x".join(f"{v * 1000:.0f}" for v in part.size_m),
            " ".join(f"{v * 1000:.0f}" for v in part.center_m)))
    rows.append("This is the design as it stands. Inspect further only when you need "
                "something that is not here -- physics, joints, the library, the rack.")
    return "\n".join(rows)


def _model_turn(app: Any, state: _State, *, message: str, history: list[dict[str, str]]) -> str:
    # The instructions and the tools are the same bytes every turn, so they stay
    # cached; everything that varies goes after them, in `input`. They used to
    # end with the selection and the assembly kind, which put two changing lines
    # in front of 5,400 tokens of tool schema.
    instructions = SYSTEM
    inputs: list[dict[str, Any]] = list(history)
    inputs.append({"role": "user", "content": _what_it_is_looking_at(state)})
    inputs.append({"role": "user", "content": message})
    tools = _tool_definitions(state.materials)
    payload: dict[str, Any] = {
        "model": getattr(app, "model", "gpt-5-mini"), "store": False,
        "reasoning": {"effort": "medium"},
        "instructions": instructions, "input": inputs,
        "tools": tools, "tool_choice": "auto",
    }
    _note(state.turn, "thinking about what you asked")
    response = _call_model(app, payload)
    calls_used, began = 0, time.monotonic()
    for _round in range(MAX_TOOL_ROUNDS):
        calls = [output for output in response.get("output") or [] if output.get("type") == "function_call"]
        if not calls:
            text = _extract_text(response)
            if text:
                return text
            # No words came back. Say which of the two silences it was rather
            # than reporting a verdict the model never reached: a reply the
            # provider marked incomplete is one that ran out of room, and
            # telling a person "no changes" for that is telling them something
            # untrue about their own design.
            cut = _cut_short(response)
            if cut:
                return ("I ran out of room before I could answer" + cut +
                        (". What I did change is in the design." if state.changed
                         else ". Nothing in the design was changed. Ask again, more narrowly,"
                              " and I will have room to finish."))
            return "Updated the Workshop design." if state.changed else \
                   "I inspected the design but made no changes." 
        outputs = []
        for call in calls:
            calls_used += 1
            if calls_used > MAX_TOOL_CALLS:
                return _wrap_up(app, state, instructions, inputs + _carry(response),
                                f"after {calls_used - 1} tool calls")
            name = str(call.get("name") or "")
            # Measured on "make the table out of glass": 142 seconds, 34 round
            # trips, and the edit itself was done at round 2. The other 129
            # seconds were three refusals repeated NINE TIMES EACH -- program_use
            # told "inspect cannot say ['distance_m', 'speed_m_s']" nine times,
            # and asked again with the same two fields nine times. Being told
            # the same thing twice and trying again is not a model problem this
            # end can argue with; it is a loop that lets it.
            already = state.refused.get(name, 0)
            if already >= REFUSALS_A_TOOL:
                outputs.append({"type": "function_call_output", "call_id": call.get("call_id"),
                                "output": json.dumps({"ok": False, "error": (
                                    f"{name} has been refused {already} times this turn and was "
                                    "not run again. Leave it alone, finish anything else you "
                                    "meant to do, and say plainly what you could not do.")})})
                continue
            try:
                args = json.loads(call.get("arguments") or "{}")
                if not isinstance(args, dict): raise ValueError("tool arguments must be an object")
                result = state.execute(name, args)
                output = {"ok": True, **result}
                # A question ends the turn where it was asked. Going round again
                # would have the model answer its own question.
                if state.asking is not None:
                    return str(state.asking["question"])
            except Exception as problem:
                state.trace.append({"tool": name or "unknown", "ok": False, "summary": str(problem)[:500]})
                state.refused[name] = state.refused.get(name, 0) + 1
                again = state.refused[name]
                output = {"ok": False, "error": str(problem)}
                if again >= 2:
                    output["stop"] = (f"That is {again} refusals from {name} in this turn. Read the "
                                      "message and change what it names, or leave the tool alone: "
                                      "asking again the same way will be refused again.")
                if sum(state.refused.values()) >= REFUSALS_A_TURN:
                    outputs.append({"type": "function_call_output", "call_id": call.get("call_id"),
                                    "output": json.dumps(output, allow_nan=False)})
                    return _wrap_up(app, state, instructions, inputs + _carry(response) + outputs,
                                    f"after {sum(state.refused.values())} refused tool calls")
            outputs.append({"type": "function_call_output", "call_id": call.get("call_id"),
                            "output": json.dumps(output, allow_nan=False)})
        # Carry the turn forward in `input` rather than pointing at a stored
        # response. `previous_response_id` asks the provider to recall a reply
        # it kept, which an organization under Zero Data Retention never does:
        # it answered "Previous response cannot be used for this organization
        # due to Zero Data Retention" with HTTP 400, so EVERY tool-using turn
        # failed while the first, tool-free turn of a conversation worked. The
        # request already sets store=False, so nothing was being kept to point
        # at in any case.
        inputs = inputs + _carry(response) + outputs
        _note(state.turn, "thinking about what that told it")
        if time.monotonic() - began > MAX_TURN_SECONDS:
            return _wrap_up(app, state, instructions, inputs,
                            f"after {MAX_TURN_SECONDS:.0f} seconds")
        payload = {
            "model": getattr(app, "model", "gpt-5-mini"), "store": False,
            "reasoning": {"effort": "medium"},
            "instructions": instructions,
            "input": inputs, "tools": tools, "tool_choice": "auto",
        }
        response = _call_model(app, payload)
    return _wrap_up(app, state, instructions, inputs, f"after {MAX_TOOL_ROUNDS} rounds of tools")


def _wrap_up(app: Any, state: _State, instructions: str, inputs: list[dict[str, Any]],
             why: str) -> str:
    """Stop using tools and answer with what the turn already has.

    This replaces raising. A turn that has gone long has usually DONE the work
    -- it has inspected the design and made the edits -- and is going round
    again over something small; throwing it away told the person their request
    had failed when their design had already changed. One more call, with the
    tools off, gets the answer out of a model that has the whole conversation
    in front of it.
    """
    asked = inputs + [{"role": "user", "content":
                       "Stop here and answer me now, in words, with no further tool calls. "
                       "Say what you changed and what you did not, and if something is still "
                       "undecided, ask me about it with concrete options."}]
    try:
        last = _call_model(app, {
            "model": getattr(app, "model", "gpt-5-mini"), "store": False,
            "reasoning": {"effort": "low"}, "instructions": instructions,
            "input": asked, "tools": [], "tool_choice": "none"})
        text = _extract_text(last)
        if text:
            return text
    except Exception:
        log.exception("The Workshop chat's wrap-up call did not answer either")
    # Even that did not speak. Say what the room can see for itself rather than
    # an error: the tools that ran are a true account of the turn.
    did = ", ".join(dict.fromkeys(row["tool"] for row in state.trace)) or "nothing"
    return (f"I was still working {why} and had to stop. What I ran: {did}. "
            + ("The changes I made are in the design; ask me to carry on and I will pick it up."
               if state.changed else
               "Nothing in the design was changed. Ask me again, more narrowly."))


def _role_from_message(message: str, design: Any) -> str | None:
    lower = message.lower()
    roles = sorted({str(part.role) for part in design.parts}, key=len, reverse=True)
    for role in roles:
        variants = {role.lower(), role.lower() + "s"}
        if role.endswith("y"): variants.add(role[:-1].lower() + "ies")
        if any(re.search(r"\b" + re.escape(v) + r"\b", lower) for v in variants):
            return role
    return None


def fallback(message: str, *, materials: list[str], library: list[dict[str, Any]]) -> dict[str, Any]:
    """Legacy deterministic classifier retained for tests and tiny clients."""
    lower = message.lower(); action = "none"
    if any(w in lower for w in ("taller", "longer", "lengthen")): action = "longer"
    elif any(w in lower for w in ("shorter", "shorten")): action = "shorter"
    elif any(w in lower for w in ("thicker", "sturdier", "chunkier")): action = "thicker"
    elif any(w in lower for w in ("thinner", "slimmer")): action = "thinner"
    elif any(w in lower for w in ("wider", "broader")): action = "wider"
    elif "narrower" in lower: action = "narrower"
    material = next((m for m in materials if m.lower() in lower), None)
    if material: action = "material"
    selected_item = None
    for item in library:
        if item.get("item_type") == "component" and str(item.get("name") or "").lower() in lower:
            selected_item = str(item["item_id"]); action = "reuse"; break
    scope = "similar" if any(w in lower for w in ("all legs", "every leg", "all of them", "matching", "similar")) else "this"
    if any(w in lower for w in ("whole object", "everything", "entire object")): scope = "all"
    reply = (f"I'll make {scope} component(s) {action}." if action != "none"
             else "I can inspect and change Workshop components, materials, dimensions and saved library parts.")
    return {"reply": reply, "action": action, "scope": scope,
            "material": material, "library_item_id": selected_item}


def _fallback_turn(state: _State, message: str) -> str:
    """Useful no-key behavior: supports semantic multi-part and multi-edit requests."""
    lower = message.lower(); role = _role_from_message(message, state.design)
    selector: dict[str, Any] = {"roles": [role]} if role else {}
    actions = []
    for action, words in (
        ("longer", ("longer", "lengthen", "taller")),
        ("shorter", ("shorter", "shorten")),
        ("thicker", ("thicker", "sturdier", "chunkier")),
        ("thinner", ("thinner", "slimmer")),
        ("wider", ("wider", "broader")),
        ("narrower", ("narrower",)),
    ):
        if any(word in lower for word in words): actions.append(action)
    material = next((m for m in state.materials if m.lower() in lower), None)
    if material: actions.append("material")
    if actions:
        for action in actions:
            state.execute("edit_components", {"selector": selector, "action": action,
                                               "amount": 0.12, "material": material if action == "material" else None})
        target = role + "s" if role else (state.selected_name or "selected component")
        return f"Updated {target}: " + ", ".join(actions) + "."
    if any(word in lower for word in ("where", "position", "size", "physics", "mass", "balance", "support")):
        result = state.execute("inspect_physics" if any(w in lower for w in ("physics", "mass", "balance", "support")) else "inspect_design", {})
        return str(result["summary"])
    return "I can inspect the object and apply component, parameter, material, physics, and library changes. Tell me what you want changed."


def propose(app: Any, *, message: str, selected_part: dict[str, Any] | None,
            candidate: dict[str, Any], materials: list[str], library: list[dict[str, Any]],
            history: Any = None, turn: str | None = None) -> dict[str, Any]:
    """Run one conversational Workshop turn and atomically update ``candidate``."""
    # Browser chat may include recent transcript plus the current request. Keep a
    # generous bounded envelope, and keep its tail so CURRENT USER REQUEST (sent
    # last by the browser) can never be crowded out by an older conversation.
    message = " ".join(str(message).split())[-MAX_MESSAGE_CHARS:]
    if not message: raise ValueError("Workshop chat needs a message")
    selected_name = str((selected_part or {}).get("name") or "") or None
    original = deepcopy(candidate)
    state = _State(app, candidate, selected_name, materials, library, turn)
    try:
        if getattr(app, "api_key", ""):
            reply = _model_turn(app, state, message=message, history=_history(history))
        else:
            reply = _fallback_turn(state, message)
    except Exception as problem:
        candidate.clear(); candidate.update(original)
        _note(turn, f"that did not work: {problem}", done=True, ok=False)
        raise
    finally:
        _note(turn, "", done=True)
    return {
        "reply": reply[:4000],
        # What it is waiting to be told, with answers to click. The page draws
        # them; picking one sends it back as the next message.
        "asking": state.asking,
        # A run to watch, if it tried the thing out. The page plays it over the
        # object and offers the way back to the build.
        "showing": state.showing,
        # Changes to take back. The page holds the session's history, so it is
        # the page that walks back through it.
        "undo": state.undo,
        # The richer agent already applied its bounded edits to candidate. The
        # outer Workshop API sees `none` and simply returns that final candidate.
        "action": "none", "scope": "this", "material": None, "library_item_id": None,
        "changed": list(state.changed), "tool_trace": state.trace,
        "tools_used": len(state.trace),
    }
