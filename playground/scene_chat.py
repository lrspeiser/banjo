"""Ask for a scene in words; get back a spec the lab would have accepted anyway.

The model never touches physics. It fills in the same fields the manual controls
fill in, and the answer goes through `fracture_lab.validate` before anything is
run, so a scene it asks for is a scene the engine can build: three measured
materials, blocks and balls, whole numbers of cells, inside the lane's cell cap.
Anything outside that is refused by name rather than repaired into something
else, and the refusal is handed back so the next turn can fix it.
"""
from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, request

import fracture_lab

# What the model may return. OpenAI strict mode wants every property required
# and no additional ones, so optional fields are expressed as nullable rather
# than omitted. Ranges are deliberately absent: `fracture_lab.validate` is the
# one place bounds are enforced, and duplicating them here would let the two
# drift apart.
BODY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "shape": {"type": "string", "enum": ["box", "sphere"]},
        "material": {"type": "string", "enum": list(fracture_lab.MATERIALS)},
        "size_mm": {"type": "array", "items": {"type": "number"}},
        "center_mm": {"type": "array", "items": {"type": "number"}},
        "velocity_m_s": {"type": "array", "items": {"type": "number"}},
        "join": {"type": "string"},
    },
    "required": ["name", "shape", "material", "size_mm", "center_mm", "velocity_m_s", "join"],
}

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "explanation": {"type": "string"},
        "mode": {"type": "string", "enum": ["plate", "objects"]},
        "cell_mm": {"type": "number"},
        "duration_s": {"type": "number"},
        "failure_law": {"type": "string", "enum": list(fracture_lab.FAILURE_LAWS)},
        "plasticity": {"type": "string", "enum": list(fracture_lab.PLASTICITY)},
        "bodies": {"type": "array", "items": BODY_SCHEMA},
        # Read only when mode is "plate".
        "plate_mm": {"type": "array", "items": {"type": "number"}},
        "plate_material": {"type": "string", "enum": list(fracture_lab.MATERIALS)},
        "striker_material": {"type": "string", "enum": list(fracture_lab.MATERIALS)},
        "ball_mm": {"type": "number"},
        "impact_speed_m_s": {"type": ["number", "null"]},
        "drop_m": {"type": ["number", "null"]},
        "support": {"type": "string", "enum": list(fracture_lab.SUPPORTS)},
    },
    "required": ["explanation", "mode", "cell_mm", "duration_s", "failure_law", "plasticity",
                 "bodies", "plate_mm", "plate_material", "striker_material", "ball_mm",
                 "impact_speed_m_s", "drop_m", "support"],
}

# Everything below is what this lane learned the hard way. A model that does not
# know it produces scenes that look right and do nothing: objects hanging in the
# air, strikers that arrive after the only phase that can break anything, plates
# whose thickness is silently rounded away.
SYSTEM = """You lay out scenes for the Banjo explicit-lattice physics engine. You do not
choose physics: you place objects and the engine does the rest.

UNITS AND FRAME. Millimetres for every length. y is up, the ground plane is at
y = 0, and center_mm is the centre of the object, so a 60 mm cube resting on the
ground has its centre at y = 30. x is across, z is depth. velocity_m_s is in
metres per second and is what the object is already doing at t = 0; falling is
negative y.

MATERIALS. Only glass, oak and iron. These are the three this lane has measured.
There is no concrete, plastic, rubber or stone; pick the nearest of the three
and say in the explanation that you did.

SHAPES. box or sphere. A sphere uses size_mm[0] as its diameter and ignores the
other two, but still send three numbers.

CELLS. Every object in a scene is built from cubic cells of one shared size,
cell_mm. An object's every side must be a whole number of cells or it is
refused.

Cell size is the single most expensive choice you make, and it costs sixteen
times per halving: eight times the cells and twice the substeps. Use 20 mm.
A twelve-object scene at 20 mm runs in under 40 seconds; the same scene at
10 mm takes 46 seconds for a third of the objects and is no more interesting to
watch. Go below 20 mm only when asked for something whose detail genuinely
needs it, and say in the explanation that it will be slow. Prefer making objects
bigger over making cells smaller: an object needs to be at least two or three
cells on its smallest side to behave like a solid at all, so a 20 mm cell wants
objects of 40 mm and up.

OVERLAP IS AN ERROR, EXCEPT WHEN IT IS A JOIN. Two objects that occupy the same
space blow apart on the first step, because nothing settles and the engine has
to undo the interpenetration all at once. This is the single commonest way to
produce a scene that detonates. Every object must either rest on top of what
holds it or stand clear of it.

The exception is a deliberate join. Give two bodies the same "join" name and
their shapes are voxelised onto the shared grid and unioned: a cell both claim
is built once, and bonds are generated across the seam, so they become one
object rather than two touching ones. That is how a handle is attached to a
blade, a leg to a table, a spout to a jug. Overlap the two shapes where they
should meet and give them the same join name. A join takes one material, the
first body's, so do not join a wooden handle to an iron blade and expect the
handle to be wood.

ROLLING. A sphere given a horizontal velocity is rolled for you: the spin that
goes with its speed is worked out and applied, because nothing in the engine
turns sliding into rolling by itself. You do not have to ask for it. Do note
that a rolling ball travels a long way before it stops, so put what it should
hit within reach rather than at the far end of a long lane.

RESTING. Objects do not settle into place before the run; they start exactly
where you put them. Put anything meant to be resting so it just touches what
holds it, or it will start by falling. Stack two 60 mm cubes on a 40 mm floor
slab at y = 20 by placing them at y = 70 and y = 130.

THE STRIKE WINDOW. Only the first phase of a run can break anything, and it
lasts about 20 ms. A moving object must start within about (speed x 0.02) metres
of what it hits, or it arrives after that phase and can only push things over,
never crack them. A ball at 6 m/s must start within about 120 mm of its target.
Place a striker just clear of what it strikes: a gap of a few millimetres.

BREAKING. Glass breaks readily, oak less so, iron mostly dents. If asked for
something to shatter, use glass and give the striker enough speed: an iron ball
at 6 m/s cracks a 10 mm glass plate; 12 m/s breaks it apart.

TWO KINDS OF SCENE. mode "objects" is a list of bodies that fall on each other,
and is what almost every request wants. mode "plate" is the older single target
struck by one ball; use it only when asked for exactly that. Fill in the fields
of the mode you did not choose with sensible values anyway, and make cell_mm
divide every side of whichever one you did choose: a 10 mm plate needs a 10 mm
or 5 mm cell, not a 20 mm one.

SIZE OF A SCENE. Up to 250 objects and about 16000 cells will run. Cost rises
with both: 450 small cubes takes about 40 seconds of wall clock and 640 takes
over two minutes. Unless a large scene is asked for, stay near 4000 cells so a
run comes back in a few seconds and can be changed again.

Answer with the scene, and an explanation of one or two sentences saying what
you built and any substitution you had to make. Do not describe what will
happen: the run will show that."""


def _spec_from_plan(plan: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """Turn the model's answer into the same spec the manual controls produce."""
    base = dict(fracture_lab.DEFAULT)
    if isinstance(previous, dict):
        # Carry anything the caller already had, so a follow-up turn changes
        # only what it mentions.
        base.update({k: v for k, v in previous.items() if k in fracture_lab.FIELDS and k != "request_id"})
    spec: dict[str, Any] = dict(base)
    spec["algorithm"] = "lattice"
    spec["cell_m"] = float(plan["cell_mm"]) / 1000.0
    spec["duration_s"] = float(plan["duration_s"])
    spec["failure_law"] = plan["failure_law"]
    spec["plasticity"] = plan["plasticity"]
    if plan["mode"] == "objects":
        spec["bodies"] = [{"name": b["name"], "shape": b["shape"], "material": b["material"],
                           "size_mm": list(b["size_mm"]), "center_mm": list(b["center_mm"]),
                           "velocity_m_s": list(b["velocity_m_s"]),
                           "join": b.get("join", "")}
                          for b in plan["bodies"]]
    else:
        spec["bodies"] = []
        spec["plate_m"] = [v / 1000.0 for v in plan["plate_mm"]]
        spec["material"] = plan["plate_material"]
        spec["striker"] = plan["striker_material"]
        spec["ball_m"] = float(plan["ball_mm"]) / 1000.0
        spec["support"] = plan["support"]
        if plan.get("impact_speed_m_s") is not None:
            spec["speed_m_s"] = float(plan["impact_speed_m_s"])
            spec["drop_m"] = 0.0
        else:
            spec["speed_m_s"] = None
            spec["drop_m"] = float(plan.get("drop_m") or 0.0)
    return spec


def ask_model(api_key: str, model: str, message: str, spec: dict[str, Any] | None,
              history: list[dict[str, str]]) -> tuple[dict[str, Any], float]:
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured in the local .env, so chat cannot plan a scene. "
                         "Add it and restart the server, or use the manual controls tab.")
    context = {"request": message,
               "current_scene": spec if spec else None,
               "earlier_turns": history[-6:]}
    payload = {"model": model, "store": False, "max_output_tokens": 4000,
               "reasoning": {"effort": "low"},
               "input": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps(context, allow_nan=False)}],
               "text": {"format": {"type": "json_schema", "name": "banjo_scene",
                                   "strict": True, "schema": PLAN_SCHEMA}}}
    req = request.Request("https://api.openai.com/v1/responses",
                          data=json.dumps(payload).encode(), method="POST",
                          headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=90) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("the model's answer exceeded the size budget")
            result = json.loads(raw)
    except error.HTTPError as exc:
        # The upstream body can echo the key or the input. Do not log it.
        raise ValueError(f"the model request failed (HTTP {exc.code}); "
                         f"check the local key, model access and account limits") from None
    except (error.URLError, TimeoutError):
        raise ValueError("the model could not be reached, and no paid retry was issued") from None
    if result.get("status") != "completed":
        raise ValueError("the model did not finish an answer; try a shorter request")
    texts = []
    for output in result.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "refusal":
                raise ValueError("the model declined this request")
            if content.get("type") == "output_text":
                texts.append(content.get("text", ""))
    if not texts:
        raise ValueError("the model returned no scene")
    return json.loads("".join(texts)), time.perf_counter() - started


def plan(app: Any, body: Any) -> dict[str, Any]:
    """One chat turn: words in, a validated spec and an explanation out."""
    if not isinstance(body, dict):
        raise ValueError("Chat request must be an object")
    unknown = set(body) - {"message", "spec", "history", "request_id"}
    if unknown:
        raise ValueError(f"Unknown chat fields: {sorted(unknown)}")
    message = str(body.get("message", "")).strip()
    if not message:
        raise ValueError("Say what you would like built")
    if len(message) > 4000:
        raise ValueError("That request is longer than the 4000 character limit")
    history = body.get("history") or []
    if not isinstance(history, list) or len(history) > 20:
        raise ValueError("history must be a list of at most 20 turns")
    clean_history = [{"role": str(h.get("role", ""))[:16], "text": str(h.get("text", ""))[:600]}
                     for h in history if isinstance(h, dict)]

    raw_plan, wall = ask_model(app.api_key, app.model, message, body.get("spec"), clean_history)
    spec = _spec_from_plan(raw_plan, body.get("spec"))
    # The one gate. Whatever the model asked for, this is what decides whether it
    # can be built, using exactly the rules the manual controls are held to.
    validated = fracture_lab.validate(spec)
    return {"explanation": str(raw_plan.get("explanation", ""))[:600],
            "mode": raw_plan["mode"],
            "spec": validated,
            "planning_wall_s": round(wall, 3)}
