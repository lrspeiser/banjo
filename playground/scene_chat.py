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
        "shape": {"type": "string", "enum": ["box", "sphere", "cone"]},
        "material": {"type": "string", "enum": list(fracture_lab.MATERIALS)},
        "size_mm": {"type": "array", "items": {"type": "number"}},
        "center_mm": {"type": "array", "items": {"type": "number"}},
        "velocity_m_s": {"type": "array", "items": {"type": "number"}},
        "join": {"type": "string"},
        "rotation_deg": {"type": "array", "items": {"type": "number"}},
        "anchored": {"type": "boolean"},
        "rest_on": {"type": "string"},
        "subtract": {"type": "boolean"},
    },
    "required": ["name", "shape", "material", "size_mm", "center_mm", "velocity_m_s", "join",
                 "rotation_deg", "anchored", "rest_on", "subtract"],
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
        # Length along x, width along z, then thickness. Millimetres.
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

SHAPES. box, sphere or cone. A sphere uses size_mm[0] as its diameter and
ignores the other two, but still send three numbers. A cone's three numbers are
the diameter at its top, its height, and the diameter at its bottom, so one
shape gives you a cone, a funnel, a cylinder and everything between: [300, 200,
60] is a bowl-shaped flare, wide at the top and narrow at the bottom, and an end
of 0 makes a point. A round shape is cut from cells rather than tiled by them,
so its dimensions are used exactly and never snapped to the grid.

You can rest_on a join name as well as a body name, which is what to use when
the thing being stood on is built from several shapes.

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

COUNT THE CELLS BEFORE YOU ANSWER. Nothing tells you the total after the fact
except a refusal, so do the arithmetic yourself: a box is
(length/cell) x (width/cell) x (height/cell), so 600 x 40 x 240 mm at 20 mm is
30 x 2 x 12 = 720 cells; a sphere of diameter d is a little over half of
(d/cell) cubed. Add them up and keep the total under 16000. Long objects are
what blow this: two 2000 x 60 x 400 mm ramps at 20 mm are 60000 cells on their
own. If the total is too big, raise cell_mm before you answer rather than
shrinking what was asked for -- doubling the cell divides the count by eight.

A BALL IS DRAWN AS A BALL. A sphere that stays whole is drawn at the diameter
you asked for, not as the cubes it is built from, so you never need a smaller
cell to make something look round. Only ask for a smaller cell when the physics
needs it.

TILTED THINGS DIP. A body's corner sits lower than its centre by more than half
its thickness once it is rotated, and a body that reaches below y = 0 is
refused. If a body has a rotation_deg and sits near the ground, give it a
rest_on and let its height be worked out instead of guessing a centre.

OVERLAP IS AN ERROR, EXCEPT WHEN IT IS A JOIN. Two objects that occupy the same
space blow apart on the first step, because nothing settles and the engine has
to undo the interpenetration all at once. This is the single commonest way to
produce a scene that detonates. Every object must either rest on top of what
holds it or stand clear of it.

HOLLOW THINGS. A body in a join group with "subtract": true is cut out of the
group rather than added to it. Union alone makes only shapes that bulge, so this
is the only way to build anything hollow or concave: a bowl is a sphere, a
smaller sphere inside it and a box over the top, all three sharing one join
name, with the last two subtracting. A cup, a pipe, an arch and a room are the
same idea. Anchor a hollow thing that is meant to hold something, because
anchored scenery collides as its own cells; an unanchored one collides as the
solid shape its outside describes, and things land on it rather than in it.

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

ANCHORED SCENERY. An object with nothing under it falls, and that includes the
thing you meant to be the floor. Set "anchored": true on anything that is
scenery rather than a participant: a lane, a table, a ramp, a wall, a pier. An
anchored body does not move, still collides, and still breaks if hit hard
enough. Ordinary objects that are meant to fall or be knocked over stay
unanchored.

TILT. "rotation_deg" turns a body about its own centre, x then y then z. Use it
for a ramp rather than building a staircase of boxes: a stack of steps collides
with itself and with whatever stands on it, and a ball bounces down it instead
of rolling. A ramp is one anchored box with a rotation of a few degrees. Note
that a tilted box reaches higher at one end than its centre, so put what sits on
it above the surface at that end, not above the centre.

RESTING. Objects do not settle into place before the run; they start exactly
where you put them. Do not work out heights yourself. Whenever an object stands
on anything -- the floor of your own scene, a table, a lane, another block in a
stack -- set rest_on and leave its y alone. A stack of four blocks is four
bodies each resting on the one below it, named in order; working their heights
out by hand is the single commonest way these scenes are refused. Name what an
object stands on: set "rest_on" to that object's name and its height is computed
from the surface directly beneath it. Use this for everything that sits on
something else, and always on a tilted or stepped surface, where the right
height is different for every object along the slope and is the commonest thing
to get wrong. Place the object over its support in x and z; only y is decided
for you. rest_on names what is DIRECTLY UNDERNEATH, never a neighbour: ten
pins spread across a lane all rest_on the lane, never on each other, however
close together they stand, and a pin beside another pin is not standing on
it. Name a second object only when one is genuinely stacked on top of the
first and sits within its footprint. Leave "rest_on" empty for anything standing on the ground or falling
through the air. Put anything meant to be resting so it just touches what
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
struck by one ball; use it only when asked for exactly that. Its plate_mm is
length along x, width along z, and thickness last, in that order: a 1000 by 800
window 10 mm thick is [1000, 800, 10], never [1000, 10, 800]. The thickness is
the small number and it goes last. A plate is 30 to 6000 mm on its first two
numbers and 2 to 100 mm thick. Fill in the fields
of the mode you did not choose with sensible values anyway, and make cell_mm
divide every side of whichever one you did choose: a 10 mm plate needs a 10 mm
or 5 mm cell, not a 20 mm one.

SIZE OF A SCENE. Up to 250 objects and about 16000 cells will run. Cost rises
with both: 450 small cubes takes about 40 seconds of wall clock and 640 takes
over two minutes. Unless a large scene is asked for, stay near 4000 cells so a
run comes back in a few seconds and can be changed again.

A WORKED EXAMPLE, a ball rolling down a ramp into pins. Note that the ramp is
anchored and tilted, that everything standing on it names it with rest_on and
leaves its own height to be worked out, and that everything standing on it is
inside its x and z extent:

  lane   box, oak,   2000 x 60 x 300, centre (0, 220, 0), rotation_deg (0,0,-6),
         anchored true
  pin1   box, glass, 40 x 120 x 40,   centre (680, 0, 0),   rest_on "lane"
  pin2   box, glass, 40 x 120 x 40,   centre (760, 0, -50), rest_on "lane"
  ball   sphere, iron, 100,           centre (-700, 0, 0),  rest_on "lane"

Use that shape of answer whenever anything rests on anything. Anchor the floor,
tilt it if a slope is asked for, and let rest_on decide the heights.

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
                           "join": b.get("join", ""),
                           "rotation_deg": list(b.get("rotation_deg") or [0.0, 0.0, 0.0]),
                           "anchored": bool(b.get("anchored", False)),
                           "rest_on": str(b.get("rest_on", "")),
                           "subtract": bool(b.get("subtract", False))}
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
    payload = {"model": model, "store": False, "max_output_tokens": 12000,
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


# How many times the model may be handed a refusal and asked again. Four is
# what it takes for a scene to clear two independent classes of fault -- a
# placement one and a budget one -- with a pass to spare; each costs one
# model round trip and nothing else.
ATTEMPTS = 4


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
    # The one gate. Whatever the model asked for, this is what decides whether it
    # can be built, using exactly the rules the manual controls are held to.
    #
    # Refusals arrive in independent classes, and fixing one can create another:
    # a scene refused for reaching below the ground gets raised, and the raised
    # version is then refused for exceeding the cell cap. With a single retry the
    # first class eats the only correction and the caller is handed a refusal
    # whose fix was already spelled out for it -- which is exactly what happened
    # to a ski ramp: two below-ground faults on the first pass, 58,540 cells
    # against a cap of 16,000 on the second, and no third pass to spend the
    # answer on. Every refusal here names the change to make, so the loop runs
    # until one validates or the attempts are gone.
    attempts, refusals, validated = ATTEMPTS, [], None
    for attempt in range(attempts):
        try:
            validated = fracture_lab.validate(_spec_from_plan(raw_plan, body.get("spec")))
            break
        except ValueError as refused:
            refusals.append(str(refused))
            if attempt + 1 == attempts:
                tried = "\n\n".join(f"attempt {i + 1}: {r}" for i, r in enumerate(refusals[:-1]))
                raise ValueError(
                    f"{refusals[-1]}\n\n(Tried {attempts} times. Earlier attempts were "
                    f"refused for:\n{tried})") from None
            # Only the last two turns of correction are worth carrying: the
            # refusal being answered, and what was tried just before it.
            history = clean_history + [
                {"role": "assistant", "text": json.dumps(raw_plan)[:600]},
                {"role": "refusal", "text": str(refused)[:2000]}]
            follow = (f"{message}\n\nThat scene was refused. Fix exactly these faults and change "
                      f"nothing else:\n{refused}")
            if len(refusals) > 1:
                follow += ("\n\nYou have already been refused for the following, so do not "
                           "reintroduce them:\n" + "\n".join(refusals[:-1])[:1500])
            raw_plan, again = ask_model(app.api_key, app.model, follow, body.get("spec"), history)
            wall += again
    corrected = ("" if not refusals else
                 f" It was refused {'once' if len(refusals) == 1 else f'{len(refusals)} times'} "
                 f"and corrected.")
    return {"explanation": str(raw_plan.get("explanation", ""))[:600] + corrected,
            "mode": raw_plan["mode"],
            "spec": validated,
            "planning_wall_s": round(wall, 3)}
