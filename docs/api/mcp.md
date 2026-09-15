# Banjo as a tool a model can use

A model asked "does a glass ball break if I drop it two metres onto concrete"
will give you a confident paragraph. This gives it a way to find out.

`mcp/banjo_mcp.py` speaks the Model Context Protocol over stdio, so anything
that can launch a subprocess — Claude, ChatGPT, your own agent loop — can build
a world out of real matter, run it, and be told what actually happened.

**No dependencies.** The protocol is JSON-RPC 2.0 over newline-delimited stdio,
which is short enough to speak directly; a server that needs a package installed
first is a server that does not get installed.

## Install

Build the library once:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --target banjo_c
```

Then register it. For Claude Code:

```bash
claude mcp add banjo -- python /path/to/banjo/mcp/banjo_mcp.py
```

Or in any client's config file:

```json
{
  "mcpServers": {
    "banjo": {
      "command": "python",
      "args": ["/path/to/banjo/mcp/banjo_mcp.py"]
    }
  }
}
```

If the library is somewhere unusual, set `BANJO_LIBRARY` to its path in the
server's environment. Otherwise it is found next to the repository.

## The tools

Deliberately above the level of the C API. A model does not want to take four
hundred and eighty steps; it wants to set something up, run it, and be told what
broke.

| tool | what it does |
|---|---|
| `list_materials` | the eight materials and what each actually does, with measured speeds, and each one's rolling resistance -- marked sourced or a demonstration value -- with the floor's, rock's, soil's and sand's. A ball is resisted with its own plus the surface's, rests on any slope whose tangent is below that, and on the level stops in v² / (2 · 5/7 c g). **Worth calling first** — the numbers are not the ones you would guess. |
| `create_world` | build a world from a list of objects; returns an id |
| `run` | let time pass and say what happened: every break, every dent, and the hardest contacts with the speeds they would have needed; and which balls rolling resistance holds still, which are rolling against it, and the energy it took |
| `drop` | the common experiment: put an object a given distance above a point, let it fall, report. The height is measured from **what it lands on**, not from the floor. |
| `describe_world` | every object, where it is, what it weighs (`mass_kg`, which every answer that lists `objects` carries: whether a person's 800 N hand can hold a thing up and turn it depends on it), and what has happened to it |
| `add_object` / `remove_object` | change a world. It is opened again from its scene, so anything in flight starts over — and every joint is hung again. A removed object takes the joints that held it with it, and they are listed. `add_object` given `position_m` as **[x, z]** sets the thing down on whatever is under that point — the ground, the floor or the top of what is there — and says what in `set_down` — with `overhangs` when only part of it is over that, so it may tip; [x, y, z] puts it exactly there, and when that is in the air the answer's `in_the_air` says how far above what is under it the thing starts, and that it will fall unless a joint holds it — a thing about to be hung with `fix`, `hinge`, `slide`, `tie`, `reeve` or `spring` is meant to start there. On ground with water it says `in_water` when that is where it went. A part of a piece (a `join` name) that [x, z] would set down on top of another part of the same piece is refused: every part of one piece takes its exact [x, y, z]. |
| `move_object` | put an object somewhere else, at rest: an **edit**, not a push. Refused for a joined object, with the reason — a joint is made at fixed points |
| `turn_object` | stand an object **upright** — its longest side vertical — or lay it down, its longest side level, and set it down at `at_m` [x, z] on whatever is under that point. An **edit**, like `move_object`, that the engine holds to what the world would do with it: it must not overlap anything, what is under it has to be under its middle on every side and flat (not the top of a ball), and the world is then **run** — from a third of a degree off how it was put, so a balance only an exact run could keep is found out — until it is still. Standing as it was put (moved under 20 mm, turned under 5 degrees) it is kept; otherwise it is refused with what happened and nothing changes. The answer says what it stands on and how far its long side came to rest from vertical. "Turn this upright and set it in front of me" is this call. [Turning a thing](#turning-a-thing) |
| `offer_actions` | what a person can **do** with a thing, kept with it: up to nine short programs of up to twelve steps — stand, take_hold, carry_to, put_down, let_go, push, heat, wait, drive — each checked when it is offered against what the engine says of the thing (a hand holds up at most 73 kg, a thing fixed in place is not moved, a drive step needs a motor that turns the thing, and a program ends with the hand empty). A client lists them when the thing is clicked and runs one on the world as it is then. A field a step's kind does not use is set aside and listed in `not_read`. [A thing's actions](#a-things-actions) |
| `read_knowledge` | what the person knows: techniques, each design by its standing (found, built, demonstrated for a stated use) with the evidence it rests on — the engine's own numbers for what their tool did, scoped to what was tried, with the model's limitations — and what is blocked and by what. It spends nothing and changes nothing: no tool can add to it. [What a person knows](#what-a-person-knows) |
| `clear_world` | empty a world, joints and all, to build it again. It stays open under the same id |
| `pick_up` / `place` / `let_go` | the hand: take hold of something already in the world and move it. Without this a model can only add new objects from above — it can build a scene but never rearrange one. |
| `collect` | sweep up the loose pieces near a point and say what they were made of, by material and by weight |
| `carried` | what has been swept up in this world so far, and the sand and soil dug out of its ground and not put back |
| `cast_ray` | what a ray meets first — what is above or below something, what is in the way |
| `blade` | give a body an **edge**: where it runs, which way it faces, how thick, how sharp (a radius) and its bevel, and where it is held. There is no cutting power: what resists the edge is the target's own fracture energy and hardness. [docs/cutting-model.md](../cutting-model.md) |
| `blades` | every edge, what it has cut and what that cost |
| `wield` | take hold of a body by its grip with a hand whose force (800 N) and torque (60 N m) are bounded — not `pick_up`, which places a thing exactly |
| `swing` | swing the wielded blade the way a person does and report every edge contact on the way: edge, slice or press (it bit), glancing, flat or point (an ordinary contact), blunt or brittle (it could not). With `through_m`, `pointing` and `edge_facing` the hand takes the blade up off its rest, back clear and round to one side, then swings it round a shoulder half a metre behind the grip, 100 degrees in `seconds` (0.13 by default), so that the middle of the edge passes through `through_m`; an edge facing across the swing leads with the edge, one facing up or down leads with the flat. (Driven along a straight line at its grip, a sword trails its point: a measured straight swing crossed the rope's line 0.19 m short and met nothing.) With `to_m` instead it moves the grip along a straight line, which is a press or a push |
| `cuts` | every edge contact since the last swing, including the ones that cut nothing and why |
| `tool_point` | give a body a **point** that can go into the ground -- a pick's, a stake's: its tip, the way it goes in, its width, thickness, angle and how much of the tool is point, and where it is held. The tip has to be at the end of the body's matter and the grip on it, or the call is refused and says which. There is no digging power: how far it goes in, what a pry breaks out and what stops it is ground-work-v1, a declared model from the ground's own materials. A joined part is taken as its whole piece; the answer says the tool's mass and its weight's pull about the grip, against the hand's 60 N m wrist. Kept with its body through every rebuild, and the playground's room has it. [docs/ground-work.md](../ground-work.md) |
| `strike` | use the wielded tool's point on the ground as a person does: a swing brings it round a shoulder so the point comes down on `at_m` along its own axis, with the hand's 800 N and 60 N m; `lever` pries a point that is in the ground and draws it out. Reports every meeting of the point with the ground -- how deep, the work and peak force measured off the solver, the model's own resistances, what came loose and whether the tool is whole -- and what a pry broke out is carried and kept as the ground's own dig edit |
| `ground_work` | every meeting of a point with the ground since the last strike, including the ones that did nothing and why (stopped by rock, glanced, not supported by the model), and every tool's point and what it is in |
| `close_world` | free it |
| `hinge` / `slide` | a pin or a groove: `b` turns about, or slides along, a line fixed in `a` |
| `tie` / `reeve` | a rope between a point on each of two things, or one run over two fixed pulleys |
| `fix` / `spring` | a latch or bracket that holds two things as one piece; an elastic element that pushes and pulls. `fix`, `spring` and `tie` take `member`: what the joint is MADE of, so heat changes what it can take ([Heat and strength](#heat-and-strength)) |
| `drum` | a rope that **winds onto a drum**: from a drum on a pin of its own to a load, off the drum's rim at its tangent, so what is off the drum changes by the radius times the turn, for as many turns as there is rope. In metres like every joint: the drum's centre and axle, `radius_m`, where the rope is made off on the load, `length_m` and `out_m` (0: as it hangs); `winds`, when left out, is worked out from the side the load hangs on. Refused for a load over the drum itself, less rope out than the span it has to run, and a rope shorter than what is off the drum; warned for a drum on no pin and a rope that does not hang straight down ([Machines](#machines)) |
| `store` / `motor` / `drive` | a **battery** in a named thing, in joules, volts and watts; a DC **motor** on a pin named by the two things it joins, wired to a battery by name, given by its stall torque, its unloaded speed in turns a minute and its brake; and what a motor is **told** from now on, found by the thing it turns: a command from -1 to 1, and its brake. `run` and `describe_world` say what each battery gave and each motor did ([Machines](#machines)) |
| `control` / `operate` | a **controller** for a motor, named by the two things its pin joins -- a hoist's when the drum it turns has a rope on it, its travel the rope out at the top and at the bottom -- and **working** it as the person's panel does: `direction` raise, lower or stop (forward or reverse for a shaft), `power`, and a drive `setting`, the machine found by its name or any part of it. It slows for each end of a hoist's travel and stops at it, stops a motor that gets nowhere, and says what stands in its way ([A machine's controller](#a-machines-controller)) |
| `plan_construction` / `check_construction` | declare a **structure** before building it -- `ski_jump`, `downhill_ramp`, `access_ramp`, `bridge`, `staircase` or `structure` -- with one sentence on how the request was read, where its line runs on the ground and its size; the kind brings what it must do, in numbers, and declared again it can be raised, never lowered. `check_construction` measures what was built against that from the world's own geometry -- rays cast straight down along its line, the ground under it, the bodies around it -- and answers each requirement with what was required and what was measured. A flat board declared a ski jump fails its takeoff. In the playground's room, the chat's structures are measured as it answers, and its answer starts "Not finished:" while one fails ([Structures](#structures)) |
| `use_action` | press one of a thing's **actions** (`offer_actions`), by its label or its number from 1: what the person's E does. In the playground's room the room runs it **as it stands** -- a hoist wound up from where its crate hangs -- and nothing is opened again, so nothing goes back to where it was made; `drive` there tells the running room's motor too. In the MCP's own world a drive step tells the motor, and an action with a step the person's hand takes is refused ([Machines](#machines)) |
| `interaction` | say how a person **uses** a thing you built — draw-and-release, a bow; or swing-and-lever, a tool with a `tool_point` swung into the ground and levered, tried by being swung into the nearest level soil, levered out, and swung onto the nearest bare rock — so the playground gives them its controls. Held to what is built (a part that is not there, a nock that holds both ways or lets go backwards, a limb that is not an elastic are refused), never a speed, kept through every rebuild and withdrawn with the reason when what it names is taken away; and **tried** in a scratch world with a person's 800 N hand, returning what was drawn, what the limbs held and what the projectile left with, and `sound` false with why when the engine did not follow the shot. [Things a person uses](#things-a-person-uses) |
| `duplicate` | make **another** of something already built, somewhere else, exactly: the bodies named, every joint between them with its points moved with it, their edges and how a person uses them. What should differ is said as `changes`, by kind of joint (`{"spring": {"stiffness_n_m": 8000}}`); the offset is rounded to whole cells; where the world refuses overlaps (the playground's room does) a copy that would overlap is refused and nothing is left half made; a copied bow is tried. [Things a person uses](#things-a-person-uses) |
| `build_recipe` | build a mechanism the engine has been tried on, **exactly**, at a place `[x, z]`: every part, every joint and its actions, on the ground surveyed there and laid on the room's cells — `gate` (between two posts, with a latch bar), `portcullis` (raised by a winch beside it), `door` (that shuts itself on a spring), `bell` (on a rope from a frame), `bow`, `table` (with a chair), `hoist` (a battery hoist, with its motor and its crate: [Machines](#machines)), and the tools that work the ground, `pick`, `mattock` and `hoe` (each one piece, with its point and how a person uses it, tried in the engine). For a tool, optional `tool` makes it the one the person asked for: `call_it`; `material` (the whole piece's — a joined piece is all one material); head and haft sizes; the point's shape (as broad as its head unless said); and `use` (as `interaction`'s, less `pry`, which is the kind's). Blanks are dropped, and a tool the hand's 60 N m wrist cannot hold level is not built. A second one's parts are numbered; if any part would overlap what is there, nothing is built. It exists because a model given a gate as seven calls of offsets set its parts down on the ground and put its pin 0.22 m inside the gate's edge, and a mattock made by hand was refused three times and ended as an action that only carried it |
| `joints` / `hinge_friction` / `unhinge` | read them, stiffen them, take one out |
| `overloaded` | what is carrying more than it can hold, worked out from statics — the only way a loaded shelf is ever noticed |
| `list_substances` | what matter is made of: substances, reactions (with where every number came from) and the catalogue's compositions — oak is dry wood, moisture and ash, which is why an oak log can burn |
| `enclose_gas` | a column of gas under a loose piston, starting at the pressure that holds the piston and its load up |
| `heat` | heat from outside — kindling, a torch, a stove — into a body or a gas region, from when the world starts |
| `thermal_state` | how hot everything is, what is burning and how hard, the fuel left and how long it would last at this rate, what the gas is doing, the energy ledger, and **strength**: what heat has left of each heated body and what every joint made of one carries against what it can still take |
| `make_terrain` | ground that is not flat: a **valley** with a river along it and a pond beside it, made once by physics -- drainage decided where the river runs, erosion wore its channel -- and cached; or a basin holding a lake, a sloping channel with a stream, flat ground, a **clearing** (level dry soil at y = 0 with a slab of bare rock beside it, to try a tool that digs on both), or none. With `beyond_the_edges`, a valley's or a channel's river goes on beyond its edges as a river network: a reach down from a reservoir onto where it comes in, and from its mouth a reach to a confluence where a brook from a spring joins it and another on to a lake with a weir -- what crosses each edge decided by the water on both sides. [docs/terrain-and-water.md](../terrain-and-water.md), [docs/watershed.md](../watershed.md) |
| `survey` | the ground and the water at a point or along a line: height, rock, soil or sand, slope, and the water's depth, level and speed. At a point it also gives the ground's rolling resistance and which materials of ball rest there and which roll away. How to find the river, and what to stand things on |
| `water_state` | the rivers and ponds: how much water, what comes in and goes out, each pond's level, the river every 2 m along its course, what is in the water and whether it floats, and the water's ledger; where the river goes on beyond the edges, each basin's and junction's level, volume, feed, what it lets out and what it sends into the valley, and what each river beyond is carrying where it starts, in its middle and where it ends (`beyond_the_edges`) |
| `dig` / `fill` | a trench or a pit, so wide and so deep below the ground as it stands; what comes out is carried, and `fill` heaps only what was carried -- the ground's own account, so a rebuild carries the same, and in the playground's room it includes what the person dug with their own spade |
| `cut_block` | a block of stone out of bare rock; the ground loses exactly that much and the block is an ordinary loose object |
| `set_river` | a river's discharge from now: a flood or a drought. Where the river comes down from a reservoir beyond the edge, what feeds the reservoir; a basin or spring out there by its own name |

`add_object` also takes `contents` (what the object is made of inside, by mass
fraction), `temperature_k`, `rotation_deg` and `join`. `rotation_deg` is how it
is turned about its own centre, in degrees -- about its own x axis, then its own
y, then its own z, which is z, then y, then x about the room's axes
(`create_world`'s objects take it too), and `describe_world` gives every box that
is not square to the room the `rotation_deg` it stands at now. Objects given the
same `join` name are built as ONE piece, their cells unioned and bonded across
the seam, named by the first of them -- a pick's haft and its arm. Every `run`
carries a `heat` summary whenever
anything is hot, burning or pushing. On ground that is not flat, `add_object`
seats a thing on the ground under it and says whether it is in water, and every
`run` carries a `water` summary.

`run` holds the **break conversation** itself. That is the part of this engine a
caller can get wrong: ignore it and the world freezes at the first impact for
ever. Nothing using these tools has to know that.

## Turning a thing

`turn_object` is how a model stands a pillar up, or lays a plank down, when a
person asks it to ("turn this upright and set it in front of me"). It is an edit,
like `move_object`: the thing is standing there as if it had been built so. What
makes it more than an edit is that the engine holds it to what the world would
do with it, in four steps, and any one of them refuses it with the reason and
leaves the world as it was:

1. **Nothing shares its space.** Its box against every other box and ball as
   built. What it stands on was looked at where it is now, settled a millimetre
   or two in, so it is lifted clear of that; standing on a thing is never taken
   for being in it. Where the world refuses overlaps (the playground's room
   does) that check runs as well.
2. **What is under it is under its middle, on every side.** Nine points of its
   footprint, straight down. Half over an edge, or on the point of a post, it
   is refused.
3. **It rests on a face, not a point.** Opposite points of the footprint have to
   average to the height under its middle, as they do on level or sloping
   ground. On the top of a ball they are both lower, and the base would sit on
   the point between them.
4. **It stays as it was put.** The world is run until it is still, for up to
   four seconds, from a third of a degree off how it was put, so that a balance
   only an exact run could keep is found out. It has to end within 20 mm and 5
   degrees of how it was put.

A box is turned by giving it its new sides and a heading about the vertical,
never a tilt: stood on end, a 0.16 × 0.16 × 0.8 m pillar is a 0.16 × 0.8 × 0.16 m
one, so its own axes stay the world's up to one turn about the vertical. It lies
down along any direction. Until 2026-09-13 only along x: the engine reported a
thing built with a heading as facing no way at all, so the settling run read a
pillar lying still along z as having turned 90 degrees, and refused it.

**Measured** (`tests/banjo_mcp_tests.py`, the real engine):

- A 49 kg concrete pillar lying on the floor, stood upright 1.2 m away, came to
  rest in 0.53 s, 0.00 degrees from vertical, 2 mm from where it was put.
- The same pillar asked onto a crate stood on the crate.
- Asked onto a rubber ball it is refused. Before the flatness rule, a pillar
  stood dead on top of a ball stayed there through the whole settling run,
  exact start or not: rolling resistance held the ball still.
- Asked onto the end of a plank balanced on a trestle, all of it over the
  plank, the plank tipped in the settling run and the pillar fell. Refused, and
  the pillar was back lying where it had been.

## A thing's actions

`offer_actions` gives a thing the actions a person takes with it. Each is a
label and a short program of steps, and the room runs the program when the
person chooses it: in the playground the side view lists a thing's actions while
the crosshair is on it, E does the one it marks, and Tab moves E on to the next.
The owner asked
for this on 2026-09-13. The model making a thing works out "what the user would
need to do", since "a bow and arrow would have different actions than a chair",
and is "given the ability to program the execution of it".

Every step is something the engine already does:

| Step | Does |
|---|---|
| `stand` | `turn_object` on the object, with all four checks above: `upright` or `lying`, `along` facing / across / x / z, `where` here or in_front |
| `take_hold` | The hand grips a part at its middle with its own 800 N, which holds up at most 73 kg |
| `carry_to` | The hand carries what it holds to a place with its own stroke, at `speed_m_s` |
| `put_down` | Lowers what it holds onto what is under it, and lets go |
| `let_go` | Opens the hand where it is |
| `push` | Grips a part, pushes it `distance_m` toward a place and lets go, so a door, gate or lever goes where its joints let it |
| `heat` | `power_w` into a part for `seconds` |
| `wait` | Lets the room run for `seconds` |
| `turn` | Takes hold of whatever stands off the pin that a part turns on (its own pin, or that of what it is fixed to, as a winch's handle is to its wheel). Carries it round the pin's axis with the hand's own strokes, by `degrees` (right-handed about the axis) or to a `stop`: `all_the_way`, `half_way`, `all_the_way_back` or `back_to_start`. It says how far it went and what else moved |
| `slide` | The same along the groove a part slides in, by `distance_m` or to a `stop` |
| `drive` | Tells the motor on the pin a part turns on (its `part`, the thing itself when left out) a `command` from -1 to 1, as `drive` does. At 0 it stops, and its `brake` goes on unless the step says `brake` false. The hand is not needed. Checked when offered: a motor has to turn the part, and one only; a brake with the motor driving is set aside and said ([Machines](#machines)) |

A place is where the hand takes the middle of what it moves. Its `kind` says
which of these it is, and only that kind's fields are read; without a `kind`,
exactly one may be given. A step likewise reads only its own kind's fields. The
room's chat fills every field it is shown, so fields that do not apply are set
aside, not refused, and the answer lists them under `not_read`.
- `in_front_m`, in front of the person when the key is pressed, its bottom
  `height_m` above the ground there (0, or none, is resting on it);
- `on` a thing;
- `beside` a thing, on a `side` near, far, left or right as the person sees it, with `gap_m`;
- `from` a thing, at `offset_m`.

When actions are offered, the tool checks them the way the room will run them.
The hand holds one thing at a time. Every part named exists and is not fixed in
place. What is taken hold of weighs 73 kg or less; anything heavier gets `stand`
steps instead. A `turn` needs a pin and a `slide` a groove, its part's own or
that of what the part is fixed to. The program ends with the hand empty, unless
its last step is a `turn` or a `slide`. That step keeps hold, so what it raised
stays up until the person lets go. While it is held, the room runs that thing's
programs that begin with a `turn` or a `slide` from the hold, so "Lower the gate"
does not drop it first.

When a key is pressed, the program runs on the room as it is then, and
everything it does is the engine's answer. A stroke that is blocked, or a stand
that is refused, stops the action with the reason; the hand is opened and what
was done stays done. A thing may have at most nine actions, few enough to step
through with Tab.
Calling the tool again replaces them, and an empty list takes them away. The
playground keeps them in the room's spec (`actions`), so they survive every
later edit and a restart. The page presses one with `POST /api/world/action`
(playground/README.md), on the room it has open: a press from a page whose room
was opened again elsewhere is refused, with nothing done. The playground also gives every loose thing built-in
actions that no model offers, run the same way and listed after its own: "Put
it on the ground in front of me" (`put_on_ground`) for what a hand can lift, and
"Stand it upright" (`stand_upright`) and "Lay it down where I'm facing"
(`lay_down`) for a box longer than it is wide. Everything on a pin gets "Turn it
all the way", "Turn it half way" and "Turn it all the way back", plus "Turn it back
to where it started" when it turns both ways from there. A wheel, whose stops are
a whole turn apart, goes half a turn for "all the way" and has no "all the way
back", which would be the same place. Anything a latch holds shut gets "Release
the latch", which the page does itself, as R does. Everything in a groove
gets the same with "Slide" (`turn` and `slide` with a `stop`). These are offered
in every room, whoever made the thing, with the stops taken from the joint. The
room's chat is told to name its own after what the thing is for: "Raise the gate",
not "Turn it". `offer_actions` refuses a label the page already offers, and one
of a thing's own that does what a built-in does takes that one's place on the
menu.

## What a person knows

`read_knowledge` reads a person's notebook: the knowledge layer of
[knowledge and progression](../knowledge-and-progression.md), increment 2. It
answers with:
- `techniques`: what they know how to do;
- `designs`: each design they have met, by its standing (`found`, `built`,
  `demonstrated`), with `evidence`. For each result the engine accepted, the
  evidence gives what it measured (`said`), the claim that supports, its scope
  (this design revision, this ground) and the model's limitations;
- `blocked`: each route to making a design that is not open, and what closes it
  (a technique not known, a process the engine does not run yet, no workbench).

A thing is a design by its construction, never by its name: its parts' sizes
and materials, whether they are one piece, and its point. A construction no
registered design matches is a design of its own (`own:<hash>`), with claims of
its own.

Nothing adds to a notebook but the engine. No tool awards anything, a
scratch-world trial earns nothing, and a result the engine marked "not
supported" is not evidence. The playground keeps its person's notebook beside
their rooms and gives the room's chat a read-only copy. A world with no
person's notebook attached knows nothing yet.

## A joint outlives the next edit

A world is opened from its scene, so adding, moving or removing an object means
opening it again. The scene used to hold bodies only, and so every joint
vanished at the next edit: hinge a gate, add a ball, and the gate was lying on
the floor with nothing anywhere to say it had ever been hung. Now:

- every joint is recorded as the call that made it and **hung again** on every
  rebuild, in the order it was made;
- the id `hinge` returned is the id `joints`, `hinge_friction` and `unhinge`
  keep taking, however the engine numbers them afresh underneath;
- what `hinge_friction` set is kept, and a joint `unhinge` took out stays out;
- removing an object removes the joints that held it, and says which;
- a joint that cannot be hung again is dropped and listed under `joints_lost`,
  never silently;
- a battery and a motor are kept the same way ([Machines](#machines)): made
  again after the joints, each motor told what it was last told, and taken out
  with what they need -- what a battery is in, a motor's pin or its battery --
  and listed under `machines_removed_with_it`.

`move_object` refuses a joined object rather than leave its pins behind in
mid-air: unhinge it first, or put things where they belong before joining them.
Two objects can no longer share a name, because joints and every later call
find things by name.

**A world's owner can add conditions.** A world entry may carry a
`check(scene, joints)` callable, run before any rebuild or new joint is
committed; raising refuses the change and leaves the world exactly as it was.
The playground uses this to hold its room to its lane's rules — no overlaps, at
most 16,000 cells and 120 objects — so a model hears about a broken rule at the
call that broke it rather than the person at the next reopen. Worlds made over
stdio have no check and behave as before.

**The playground's chat is a client of exactly these tools.** It is sent this
list — the same names, descriptions and schemas, less `world_id` — and every
call it makes runs these handlers, on the person's room held as an MCP world
(`playground/room_world.py`). A tool added here reaches it untouched;
`tests/chat_tool_parity_tests.py` fails if one does not and no reason is
written down.

## Things a person uses

A bow here is a grip, two limbs, a string and a nock, and every one of them is
an ordinary joint. What makes it a bow to a person is what they do with it:
take it up, draw the string back, let go. `interaction` says that
([interaction-profiles.md](../interaction-profiles.md)):

- which bodies are the object (`parts`), the part the hand draws and the way
  it comes back (`draw`: `part`, `axis`, `max_m`, `speed_m_s`), the ONE-WAY
  fixing that holds what is shot (`nock`: a `fix` with `comes_off_n`), the
  elastics that store the draw (`limbs`), and the `projectile`;
- never what the physics does: what a bow shoots with is its limbs', and how
  deep a point goes is the ground's. How the person's hand moves it may be
  said, within the hand's own bounds -- how far and how fast a bow is drawn
  (`draw` `max_m`, `speed_m_s`), and how a tool is swung and pried (`use`,
  below).

It is held to what is BUILT: the calls that made the joints, not what the world
happens to be doing, so a nock an arrow has just come off in a `run` is still
the bow's nock. The playground's rooms are held to the same rules
(`mcp/interaction_profiles.py`, shared). A profile is kept through every
rebuild, and the call that takes away something it names withdraws it: that
call's answer carries `interactions_withdrawn`, each with the object and why.
`describe_world` lists what is left under `things_a_person_uses`.

A tool that digs is a `swing-and-lever`: its `parts` and its `tool`, the part
with the `tool_point`, which the hand takes by the point's grip. It is refused
if the tool has no point. Its trial, in a scratch world holding the tool and the
ground with every edit made to it, takes the tool by its grip, holds it ready in
front of a person standing 1.2 m back, swings it into the nearest level soil
(deep enough for the point) and levers it out -- drawing it straight up if the
lever's own lift did not bring it out -- then swings it onto the nearest level
bare rock. It answers what each swing met, how deep, the work and peak force,
what came loose and what stopped it, and the seconds of world against the
seconds of computing. Measured, the pick the playground's chat is given (1.21 kg
of oak, lying on the clearing's soil): 120.3 mm into the soil at 9.17 m/s,
5.61 L broken out by the lever, stopped by the rock at 8.22 m/s; 6.6 s of world
in 0.17 s. [docs/ground-work.md](../ground-work.md)

The playground uses every tool the same way (`playground/tool_use.py`, and
`POST /api/world/tool` and `/api/world/tool/use` in playground/README.md): E
takes it up, a ring on the ground shows where it will come down and whether it
can work there, one click does the whole of it -- swing, pry, draw out -- and
holding the button keeps going. A tool's optional `use` shapes that for the
thing that was made, and only what it says is kept:

| `use` field | What it says | When not said |
|---|---|---|
| `label` | What the click is called, at most 40 letters | "Dig here" |
| `past` | How a result is said, at most 24 letters | "dug" |
| `swing` | `speed_m_s` 1 to 5 and `raise_deg` 30 to 170: how fast the HAND moves along the swing (the point arrives two to three times faster: a 4 m/s swing brings a pick's point down at 9.2 m/s). Measured live, the world's pick dug at 4 and 5 m/s and stopped short at 6 and 8 | 4 m/s, 110 degrees |
| `lever` | `speed_m_s` 0.3 to 4 and `lever_deg` 5 to 80: how it is pried | 1.2 m/s, 40 degrees |
| `pry` | false for a tool that is only swung and drawn out | true |
| `reach_m` | [nearest, furthest] in front of the person, within 0.3 to 2 m | [1.15, 2]: from 1.2 m out every swing measured dug, and at 1.05-1.1 m about one in several came down short |
| `repeat` | false where holding the button should not go on | true |

Its trial swings it with the same numbers, from `interaction_profiles.TOOL_USE_DEFAULTS`
and what `use` says, so what the trial measured is what the person gets. Blank
fields of a `use` -- a model's function call often fills every one -- are
dropped rather than refused; a value outside the hand's bounds is refused with
them.

A caller that sends every field it is offered -- a model's function call often
does -- sends the other kind's too. With a `template` said, what the other kind
has and it has not (a pick's `draw`, `nock`, `limbs` and `projectile`; a bow's
`tool`) is set aside whatever it holds, and the answer names it under
`not_read`; only where those fields would make a working profile of the other
kind is the call refused, since then it says two things. With no template said
a profile is a draw-and-release: blanks are dropped, and a `tool` that names
something is refused, since it may be the only sign a tool was meant.

`duplicate` makes another of something already built, exactly: the bodies it
is given, every joint between them with its points moved with the copy, their
edges and points, and how a person uses them -- which a copied bow is then tried by. What
should differ is said as `changes`, by kind of joint, so a stiffer bow is
`{"spring": {"stiffness_n_m": 8000}}` rather than a bow built again number by
number. The offset is rounded to whole cells, so the grid cuts the copy as it
cut the original. In a world that refuses overlaps, as the playground's room
does, a copy that would overlap anything is refused with the room's own reason,
and nothing of it is left behind; a world made over stdio has no such rule, for
a copy as for `add_object`. It exists because a model asked
for a second bow beside the courtyard's added one offset to forty numbers and
did not: it put the copy's limb tips 0.2 m from where they belonged, the string's
centre where one of its ropes was made off, and the whole bow in the first one's
line of fire with its arrow inside the gate.

And it is TRIED, unless `trial` is false. The trial runs in a scratch world
opened from what was built, holding the object and whatever is joined to it --
never the world a caller holds -- stepped at 1/240 s as the playground's room
is. The engine's own hand, 800 N, takes the draw part, strokes it back along the
draw at the draw's speed until the limbs balance it or it reaches `max_m`,
holds it a quarter of a second and lets go. The answer is what was drawn, how
hard the hand pulled, what the limbs held, and what the projectile LEFT with:
its speed at the step the nock let it go, along the shot, and the share of the
limbs' energy that is. `sound` is false, with `why`, when the shot is not one
the engine followed: the arrow was not on the string when it was loosed, or
never came off it; it lost more in one step on the string than its nock's grip,
what it rubs on and gravity could take; it came off going backwards, or left
with more than the limbs held; the string struck it after it came off, or
something drove it on.

Measured, the recipe the playground's chat is given (6 kN/m limbs on 45 g tips,
a 672 g oak arrow on a 20 N nock, drawn 0.45 m): drawn 436 mm by 214 N, the
limbs held 42.2 J, and the arrow came off 0.09 s after the loose at 8.30 m/s --
55% of it. The same hand on other limbs: 3 kN/m 5.58 m/s, 4.5 kN/m 7.11, 8 kN/m
9.67, 12 kN/m 11.87, 20 kN/m 15.48 (686 N of the hand's 800). Drawn less, less:
6 kN/m drawn 0.20 m, 2.10 m/s; 0.30 m, 4.72; 0.40 m, 7.20. Each trial took 0.05
to 0.08 s to compute.

The trial is what found the engine wanting. Before every moving box and hull
was given round edges -- 2 mm, or a tenth of its thinnest half if that is less
(`kSweepRadiusM` in `src/rigid/JoltWorld.cpp`) -- the arrow
sliding over its rest was stopped dead on 13 of 19 of those draws and
stiffnesses by a false hit of Jolt's own sweep: 5.58 m/s to −2.54 in one step,
still nocked, with nothing touching it. It was not the bow: a 0.6 m oak box sent
along an oak plank it lay on at 5 m/s did the same, and so, at any speed past
about 3.6 m/s, would anything sliding fast over what it rests on.

## What `joints` says about a rope

For a `tie`, `apart_m` is how long the rope is now: the distance between the two
points it was tied at (`at_a_m` and `at_b_m`), each carried with its object as the
object moves and turns. A taut rope reads its own `length_m` and a slack one
reads less. It used to be the distance between the two objects' centres, which is
a different number whenever a rope is not tied at a middle: a 1 m rope hauled
tight from the foot of a post to the back of an iron block read 1.27 m. For a
`reeve`, `rope_m` is the whole run, measured the same way.

`tension_n` is newtons: the force the rope carried over the last step, and only
that. A hanging weight reads its weight at any step size, and held down by the
hand, which pulls with 800 N, its weight plus 800 N. `place` moves the hand once
and then lets the world run, so that is what a rope held against it carries. A
host driving the engine directly that moves the hand before every step pulls
twice as hard; see `tension_n` in [c-api.md](c-api.md).

For a rope on a `drum`, `rope_out_m` is how much of it is off the drum -- the
most the span to the load may be -- `on_the_drum_m` how much is wound on, and
`length_m` the whole rope; `leaves_m` and `meets_m` are where it leaves the drum
and where it meets the load, and `at_m` and `axis` the drum's centre and axle as
it stands.

## Machines

A battery turns a motor, and the motor winds a rope onto a drum and lifts a load
([machine-world.md](../machine-world.md)). Four tools make one, each the
engine's own call through the binding (`banjo_drum`, `banjo_make_energy_store`,
`banjo_make_motor` and `banjo_drive_motor` in [c-api.md](c-api.md)):

- `drum`: a rope from a drum `a` -- a thing on a pin of its own -- to a load `b`,
  made off at `at_b_m`. `at_m` and `axis` are the drum's centre and axle,
  `radius_m` where the rope lies on it, `length_m` the whole rope, and `out_m`
  what is off the drum (0: as it hangs). `winds` is +1 when the drum turning the
  positive way about its axle takes rope on; left out, it is the way that runs
  the rope off the side of the drum the load hangs on, and the answer says which.
  Refused: a load over the drum itself, seen along its axle; an `out_m` less than
  the span the rope has to run, which would snap the load toward the drum on the
  first step; and a rope shorter than what is off the drum. Warned: a drum on no
  pin, or on one about another axis; an end made off in the air; and a rope that
  does not run straight down to what hangs on it.
- `store`: a battery in a named thing, with `capacity_j`, `charge_j` (full when
  left out), `voltage_v` (24) and `max_power_w` (0, no limit but its charge).
  Refused: nothing of that name to put it in, a name another store has, a charge
  over its capacity.
- `motor`: a DC motor on a pin, named by the two things the pin joins (`on`,
  either way round; it is kept in the pin's own order), wired to a store by its
  name, with `stall_torque_n_m`, `no_load_rpm` (turns a minute) and
  `brake_torque_n_m`. With a brake it starts braked. The answer says which way a
  command of 1 turns each drum's rope on its pin, and warns of a load it cannot
  lift (m g r over its stall torque), a brake that cannot hold it, and a load
  hanging on a motor with no brake. Refused: no pin between the two, a pin with a
  motor already, no store of that name.
- `drive`: what a motor is told from now on, found by the thing it turns
  (`part`), as the page finds it: `command` from -1 to 1, and `brake`, which is on
  when it is stopped unless said. The answer says what that does to each drum's
  load. Refused: nothing turning that part with a motor, two motors on its pins,
  and a command past -1 or 1.

The numbers take the room's own bounds (`fracture_lab.normalise_machines`), so
whatever one takes the other does.

A world keeps all of it through every rebuild: the rope on a drum is a joint,
recorded as the call that made it, and the batteries and motors are kept as the
room spells them and made again after the joints. `run` and `describe_world`
carry `machines`: each battery's charge and what it has given, each motor's
state, speed, torque, power, whole turn and account (`drawn_j` is `work_j` plus
`heat_j`), and each drum's rope. A thing's actions take a `drive` step (see
[A thing's actions](#a-things-actions)).

In the playground's room all four are part of what the room is: the drum joint
and a `machines` block, `stores` and `motors`, in the room's spec, which
`playground/live_session.py` opens. A motor keeps what `drive` last told it, so
the room runs it as the chat left it -- from the room as authored, since a room
the chat changed is opened again.

`build_recipe` `"hoist"` builds a battery hoist at `[x, z]`: a concrete post; a
cell in front of it an oak drum 0.16 m square on a pin along z, 2 m up; a 32 kg
iron crate hanging 0.32 m clear of the ground on 2 m of rope, which runs straight
down from the drum's +x rim to the middle of its top; a 20 kJ, 24 V battery
beside the post; and a motor on the drum's pin that stalls at 60 N m, runs at
95.5 turns a minute unloaded and has a 200 N m brake. Its actions, on the drum,
are "Wind it up" (drive 1), "Stop" (drive 0 with the brake) and "Let it down"
(drive -0.1). A `tool` filled in, which only shapes a tool that works the
ground, is left out of the hoist, as it is of every recipe that is not such a
tool, and the answer says so under `left_out`: the chat fills every field it
is shown, and refused, it filled `tool` in again until the turn ran out.

"Let it down" is -0.1 because the crate lets itself down. Driven backwards with
a load pulling the same way, a DC motor turns faster than it would unloaded, and
its line holds it back: the crate comes down at r w0 (|u| + m g r / stall), and
here m g r / stall is 0.42. So -0.1 brings the crate down at 0.42 m/s, 0.08 faster
than its weight alone would, and an empty rope is still paid out, at 0.08 m/s.
The test room's -0.3 would be 0.58 m/s. A command of 0 without the brake would
drop it, since the motor is then off. The battery gives nothing while the load
drives the motor (decision D2).

**Measured**, the recipe built by `build_recipe` on the world's west terrace,
opened on the live runner and worked by its own actions
(`tests/world_room_tests.py` TheWorldsHoistByRecipe):

| check | result |
|---|---|
| "Wind it up" for a second | the drum turned 0.889 times and took on 0.4470 m of rope, its radius times its turn (0.4471 m); the crate rose 0.4470 m |
| its account | the battery gave 267.251 J, what the motor drew: 145.466 J of work and 121.785 J of heat |
| "Stop" | in the next second the crate moved 0.000000 m, and nothing more was drawn |
| "Let it down" | 0.4170 m/s, where the motor's line says 0.4173, and the battery gave 0 J |

The same hoist built with the four tools in the MCP's own world, through the
binding (`tests/banjo_mcp_tests.py`), and through `room_world` into a room that
the live runner opened (`tests/machine_room_tests.py`), rose by its radius times
its turn to within a hundredth, with the battery giving what the motor drew.

## A machine's controller

The owner's review of 2026-09-15: a powered machine is worked from a panel, like
an appliance, not by grabbing its drum or pressing E through a list of actions
([machine-world.md](../machine-world.md), "Operating a machine"). `control`
gives a motor a controller, and `operate` works it as the playground's panel
does. Each is the engine's own call (`banjo_make_control` and `banjo_operate`,
[c-api.md](c-api.md#a-machines-controller)), and the controller runs in the
engine, before every step.

- `control`:
  - the motor, by the two things its pin joins (`on`);
  - a `name`: `hoist` for a hoist, and the thing its motor turns otherwise,
    numbered when the name is taken;
  - a hoist's travel: `top_out_m`, 0.3 m of rope out when left out, and
    `bottom_out_m`, the rope's length less 5 cm when left out.

  It starts off, holding on its brake. Refused: no motor on that pin, and a
  motor with a controller already.
- `operate`:
  - the machine, by its name or by any part of it (a part of two machines is
    refused, naming both);
  - `direction`: raise, lower or stop, or forward or reverse;
  - `power`;
  - a drive `setting` from 0 to 1, the share of its battery's voltage.

  A direction that moves it turns the power on, unless `power` false is said.
  The answer says what it does and what stands in its way. `run` and
  `describe_world` carry each controller under `machines.controls`: what it was
  told, its shaft's turns a minute, a hoist's rope, and its `condition`.

What a controller does:

- a hoist's slows for each end of its travel, stops at it and holds on its
  brake;
- lowering comes on gently, so the rope never goes slack;
- it stops when the load comes to rest on something;
- told the other way, it stops first;
- driven into something that will not move, it stops within 3 s and says it
  stalled.

`build_recipe "hoist"` gives its hoist a controller named `hoist`. Its travel
runs from 0.3 m of rope out to 1.75 m. The drum's three actions stay beside it,
and now go through it, so they stop at the ends too.

In the playground's room, every motor has a controller. One the room's spec
does not give is given one, which passes on what its motor was told: a hoist a
room left winding winds on. `operate` is one of the calls that work the room as
it stands (`room_world.LIVE`): the running room's machine is told, and the room
is not opened again. The page's panel goes to the same controller by a route
of its own, `POST /api/world/machine`, with the page's own sender and count.

## Structures

The owner's review of 2026-09-15: asked for "a long ski ramp", the
playground's chats each built one tilted board, called it a ski ramp, and
nothing asked whether it was one. A structure is now declared before it is
built and measured against what it must do
([building-from-language.md](../building-from-language.md)).

- `plan_construction`:
  - a `name`, and a `kind`: `ski_jump`, `downhill_ramp`, `access_ramp`,
    `bridge`, `staircase`, or `structure` for anything else;
  - `reading`: one sentence on how the request was read, which the person sees;
  - its line: `start_m` [x, z] (a ramp's raised end) or `middle_m`, and
    `facing`;
  - its size: `length_m`, `width_m` and `height_m` (a ramp's start height, an
    access ramp's rise), and `scale` `model` for one asked to be small.

  The answer says what it must do in words (`must`), where a point `s` m along
  its line is, and the `rotation_deg` of a board along it: `[0, yaw_deg, t]`,
  tilted `t` degrees. Everything added after it, until another is declared, is
  one of its parts. Refused: less than the kind's least (a ski jump is at least
  6 m long, its start at least 2 m up and a fifth of its length); declared
  again, a lower requirement or another kind.
- `check_construction`: its `name`, and `parts` built before it was declared.
  The answer gives `passed`, `failed`, and each requirement with `required` and
  `measured`.

| kind | what it must do |
|---|---|
| `ski_jump` | its length, width and start height; one surface along it, with no gap or step over 5 cm; coming down by at least half its start height; rising at least 5 degrees over its last metre; every part anchored; every part standing on the ground, on scenery or on another part; 3 m clear beyond its end |
| `downhill_ramp` | its length, width and start height; one surface; coming down; anchored; supported |
| `access_ramp` | its length, width and rise; no steeper than 7.2 degrees (one in eight) over any half metre; one surface; anchored; supported |
| `bridge` | its deck from within 0.3 m of its start to within 0.3 m of its length along its line; its width; one surface; walkable, no steeper than 12 degrees over any half metre; its deck at least `height_m` (0.3 m unless said) above the ground or the water under its middle; anchored; supported |
| `staircase` | its rise, from its foot to its top; at least 2 even steps, each rising 0.10 to 0.22 m and going at least 0.22 m (the top one as far as it likes), their rises within 2 cm of each other; its width; anchored; supported |
| `structure` | its length and width along its line; supported |

A kind is a selection of measurements, not code of its own, so a new kind is a
new selection: the surface along its line and its width, its slopes over a
window, its gaps and steps, its treads and risers, how high it stands over the
ground or water, what stands in a space beyond it, and what holds up what.

It is measured from the world's own geometry. Rays are cast straight down every
centimetre along its line, and meet it as the solver collides it -- a tilted
board as its exact box. Two parts touch when their turned boxes come within
6 cm (a separating-axis test), a part stands on the ground when a corner is
within 6 cm of the ground under it, and the runout is the box beyond its end,
as wide as it and 2.5 m high.

In the playground's room, `plan_construction` changes what the room is
(`room_world.AUTHORING`), and the room keeps each declaration with its parts.
As the chat answers, each structure it declared or changed that turn is
measured; one that fails goes back to it with the measurements, at most twice,
and after that its answer starts "Not finished:" with what failed. The page
shows the measurements under the answer.

## What a session looks like

> **Build a glass pane on two piers and drop an iron ball on it from three
> metres.**

```
create_world  → world_id "a3f91c02", 3 objects
drop          → fall_m 3.0, iron ball, over [0,0,0]
```

```json
{
 "dropped": {"object": "iron ball", "fall_m": 3.0, "onto": "pane"},
 "simulated_s": 2.283,
 "computing_took_s": 0.85,
 "what_happened": [
  {"what": "broke", "object": "pane", "into_pieces": 40,
   "because": {"hit_by": "iron ball", "at_m_s": 7.62, "breaks_above_m_s": 4.51}}
 ],
 "hardest_contacts": [
  {"struck": "iron ball", "by": "pane piece 27", "at_m_s": 10.27,
   "breaks_above_m_s": 25.03, "bends_above_m_s": 10.01},
  {"struck": "pane", "by": "iron ball", "at_m_s": 7.62,
   "breaks_above_m_s": 4.51, "bends_above_m_s": null}
 ]
}
```

Every event carries **what caused it**, read before the fracture — afterwards
the body is gone and its pieces report their own collisions instead. Without
that, the answer is a list of shards hitting each other and no sign of what
actually happened.

`bends_above_m_s` is `null` for the pane because glass is brittle: it has no
speed at which it bends, which is a real answer rather than a missing one. The
iron ball has one, because iron does.

Then the follow-up nobody used to be able to ask:

> **Sweep up the glass and tell me how much there is.**

```
collect → near [0,0,0], radius 4.0
```

```json
{
 "picked_up": [{"material": "glass", "grams": 2040.0, "pieces": 93}],
 "objects_before": 109, "objects_now": 16,
 "carried": {"glass": {"grams": 2040.0, "pieces": 93}}
}
```

A hundred and nine bodies down to sixteen, which is the other half of why this
exists: the next experiment in that world would have found the pane unbreakable.

And when nothing happens, it says why:

```json
{
 "what_happened": "nothing broke or bent",
 "hardest_contacts": [
  {"struck": "pane", "by": "iron ball", "at_m_s": 2.34, "breaks_above_m_s": 4.51}
 ],
 "why_nothing_happened":
  "Every contact was under the speed it would have taken. Drop it from higher,
   or use something denser to do the hitting: a threshold depends on what is
   doing the striking as much as how fast it goes."
}
```

That is the answer someone actually needs. A tool that reports silence when a
thing bounced off teaches nothing.

## What the server tells the model about itself

On `initialize` it returns instructions, so a client that reads them starts in
the right frame:

> Banjo simulates matter: objects are cells joined by bonds that carry tension
> and compression, yield, and fail. Call `list_materials` first — what a thing
> is made of decides what happens to it, and the numbers are not the ones you
> would guess. Build with `create_world`, then `run` or `drop`. **Never say
> something broke unless a tool reported that it did.**

That last line is the point of the whole thing.

## Bounds

| | |
|---|---|
| 8 worlds open at once | each is a physics engine with its scene resident in it |
| 60 objects per world | plenty for an experiment |
| 20 s simulated per `run` | so a caller cannot ask for an hour |
| 25 s of computing per `run` | so one scene of shattering concrete cannot fail to return |

The wall-clock bound is the one that matters. The engine is far faster than real
time when nothing is breaking — a room at rest runs at 0.02× — and far slower
for the moments when something is. If `run` stops early it says so, with how
much it managed.

## Things the model will get wrong unless told

These are worth putting in your system prompt if you are building on this:

- **The centre is the middle.** An object at y = 0 is buried half in the floor.
  A thing resting on the floor has its centre at half its own height.
- **A plate on the floor will not break.** What breaks a plate is a span under
  it. Bridge it between piers.
- **A threshold is not a promise.** Clearing it means a break is *possible*.
  5.4 m/s on a 4.5 m/s pane still held.
- **Mass does not help.** 111 kg and 0.9 kg at the same speed are judged the
  same.
- **Iron is the hammer.** Aluminium is springy and transmits less of the blow.
- **A world that shatters fills up, and a full world stops breaking.** Fracture
  needs a step the engine can take back, and that cannot run past a couple of
  thousand bodies. Past it the room keeps running perfectly and quietly stops
  being able to break anything: the same iron ball onto the same 20 mm pane
  broke it into 71 pieces in a room of 58 bodies and left it whole in a room of
  430. One shattered pane is a hundred bodies, so this arrives sooner than
  anyone expects. **Call `collect` between experiments.**
- **A dented thing is not debris.** Something that bends is rebuilt from where
  its matter ended up, which makes it the same kind of shape a shard is — but it
  is still the object it was, and `collect` leaves it alone. So does anything
  anchored, and whatever is in the hand.

## Sweeping, and what it is for

```
collect(world_id, near_m=[0, 0, 0], radius_m=1.5)
-> {"picked_up": [{"material": "glass", "grams": 2040.0, "pieces": 93}],
    "objects_before": 109, "objects_now": 16,
    "carried": {"glass": {"grams": 2040.0, "pieces": 93}}}
```

Added up by material rather than by shard, because that is the form anything
built out of them wants: nobody needs ninety-three entries called
`"glass pane piece 31"`, they need to know there are two kilograms of glass. The
weight is the matter that was actually there — a piece's cells are its volume,
and volume times the material's density is what has been carried away.

`carried` accumulates per world, so a session can break several things and ask
what it has.

## Heat, fire and gas

```
add_object(object={"name": "log 1", "shape": "box", "material": "oak",
                   "size_m": [0.12, 0.12, 0.48], "position_m": [-0.08, 0.14, 0]})
heat(target="log 1", power_w=10000, seconds=90)
run(seconds=120)
-> "heat": {"bodies": [{"object": "log 1", "surface_k": 871.0, "burning": true,
                        "heat_release_kw": 11.28, "fuel_left_kg": 4.12,
                        "would_last_min_at_this_rate": 95.7}, ...]}
```

Declared in the scene document -- `contents` on the body, gas regions and
heaters in a `thermo` block -- so every rebuild carries them the way it carries
the objects, and the playground's room is handed them in its spec. A `heat` is
authored: it runs from when the world starts. Removing an object takes the
heaters aimed at it and the gas regions that pushed on it with it, and says so.

Things a model gets wrong unless told, and the tool descriptions say so: one log
beside a cold one on a stone slab does not light with the kindling that lights a
log on its own -- the slab and the cold log take the margin -- and a piston must
be loose, on a `slide`, a cell clear of its walls.

## Heat and strength

Heat changes what things can carry, by each material's declared law
([thermal-mechanics.md](../thermal-mechanics.md)): oak by EN 1995-1-2's softwood
curves (it has lost most of its shear strength by 200 degC and is char, carrying
nothing, past 300), iron by EN 1993-1-2 (no loss below 400 degC), concrete by EN
1992-1-2 (it does not come back when it cools). Glass, aluminium, ceramic,
rubber and ice have no law and are not changed. `list_substances` lists every
law with its source and what it does not model.

```
fix(a="gatepost", b="oak peg", at_m=[0, 1.4, 0.08], axis=[0, 0, 1],
    holds_shear_n=800, member="oak peg")
-> "made_of": {"member": "oak peg", "holds_shear_n_cold": 800.0,
               "law": "timber, EN 1995-1-2 Annex B (reference-derived)", ...}
heat(target="oak peg", power_w=2000, seconds=300)
run(seconds=20) ... run(seconds=20)
-> "what_happened": [{"what": "gave way", "object": "oak peg from gatepost",
     "because": "sheared across its axis: carrying 318 N against the 318 N it could
                 still take (800 N cold) -- oak peg: surface 1072 K ... 40% of its
                 shear ... left"}]
thermal_state()
-> "strength": {"bodies": [{"object": "oak peg", "shear_left_pct": 40.0,
                            "char_mm": 3.0, "burned_away_mm": 0.1, ...}],
                "attachments": [{"made_of": "cold oak peg", "attached": true,
                                 "carrying_shear_n": 317.5, "holds_shear_n": 800.0}]}
```

`member` is one of the joint's own two ends. It is recorded with the joint, so
every rebuild -- including the one `heat` makes -- hangs it again made of the same
thing. A joint without one is exactly the numbers it was given, whatever heats
it. With one, a strength left at 0 is the member's own section, not a weld. A
joint gives way when the load the solver measures passes what the law has left,
never at a temperature or on a timer: an unloaded peg in the same fire does not
drop anything, and a heavier gate gives way sooner. Rate a fixing at least twice
what it holds -- a world starts with every load suddenly applied.

**One material state** ([thermal-mechanics.md](../thermal-mechanics.md), "One
material state"). What `strength` reports for a body is also what its lattice is
given if it is broken, what it collides and is drawn as, and what it weighs:

```
-> "strength": {"bodies": [{"object": "hot beam", "bending_left_pct": 48.4, ...,
                            "now_mm": [1398.8, 58.8, 98.8], "as_built_mm": [1400, 60, 100],
                            "mass_kg": 5.549, "cells": 1050, "cells_burned_away": 0,
                            "lattice_tension_left_pct": {"weakest_bond": 34.7, "mean": 50.2}}],
                "under_load": [{"object": "hot beam", "answer": "held",
                                "its_bonds_at_pct_of_what_breaks_them": 25.0, ...}],
                "burned_away": [...]}
```

- A beam carrying a load is **asked about when beam theory passes the strength
  of either side of its section** -- oak's compression side (52 MPa, and 0.25 of
  it at 100 degC) before its tension side -- and **answered by statics** on its
  own heated lattice, held where it rests and pressed by what rests on it.
  `under_load` says the answer and how near its bonds came: the lattice removes a
  bond at twice the strain the declared strength gives, so between the two a
  beam is asked about and holds, and the model says so.
- What burns **leaves the shape**: a box burns in from every face, the room draws
  it smaller and things resting on it settle with it; a piece whose cells burn
  away is rebuilt from the rest. A body whose load-bearing matter is all gone
  leaves the world (`burned_away`), and whatever was fixed to it lets go.
- Burning is **slow**, as timber is: at the oxygen the air can supply, oak
  recedes about 0.4 mm a minute. A 60 mm beam loses its strength to heat long
  before it burns away; a slat burns through in tens of minutes, not seconds.

## Blades

```
blade(body="sword", heel_m=[0.2, 1.02, 1.88], tip_m=[-0.3, 1.02, 1.88],
      facing=[0, 0, -1], thickness_m=0.04, edge_radius_m=0.0002,
      grip_m=[0.28, 1.02, 1.9])
wield(name="sword")
swing(through_m=[-0.5, 1.58, 1.4], pointing=[0, 0, -1], edge_facing=[-1, 0, 0],
      then_s=1.5)
-> "cuts": [{"met": "rope 4", "kind": "edge", "speed_m_s": 13.21,
             "resistance_j_m2": 7400.0, "cut_mm2": 1059.1, "work_j": 7.837,
             "bonds_severed": 2, "came_apart": true, "pieces": 2}, ...]
```

An edge is declared in the scene document -- `blades`, each kept in its body's
own frame -- so every rebuild arms it again on the same body, wherever that
body has since been put, and the playground's room is handed it in its spec.
Removing a body takes its edge with it and says so (`edge_removed_with_it`);
an edge that cannot be armed again is reported, never dropped silently.
`wield` and `swing` are uses, not authoring: they change the world the caller
is building in and nothing in its scene. So after the playground's chat has
cut a rope in its copy, the person's room still opens with the rope whole and
the sword on its rests, and the cut is theirs to make. The swing above is the
one `tests/banjo_mcp_tests.py` makes, on a rope of six rubber segments with a
4 kg weight at 0.04 m cells: the weight ended on the floor, and with
`edge_facing=[0, -1, 0]` the flat leads and nothing is cut.

Two ways a model got a cutting setup wrong, and what now says so. An edge
declared on a bar's far face but facing back into the bar is refused, with the
rule it broke: swung "edge first" it led with the bar's other face and glanced
off the rope. And a `tie` or `spring` made off more than a cell away from its
body is warned about: a model hung a weight 0.24 m below the end of its rope
and tied it from a point in the air under the last segment, which rides on
the segment like the end of a stiff arm that is not there. So is a `fix` whose
point is more than a cell outside either of the two things it joins: a model
set a peg down on top of its post and fixed it at the post's face 0.2 m below,
and when heat parted the fixing nothing fell, because the peg sat on the post.
(The 5 mm a jointed body stands clear is well inside a cell.)

## Terrain and water

```
make_terrain(kind="valley")
-> "ground": {"kind": "valley", "from_m": [-19.38, -15.5], "to_m": [19.38, 15.5],
              "column_m": 0.25, "bare_level_rock_at_m": [-9.12, 4.75], ...},
   "water": {"volume_m3": 29.338, "rivers": [{"name": "the river", "fed_m3_s": 0.35}],
             "ponds": [{"name": "the pond", "at_m": [4.77, -2.73], "level_m": 0.858}],
             "the_river_runs": {"columns": ["x_m", "z_m", "level_m", "depth_m", "speed_m_s"],
                                "every_2_m": [[-19.38, -2.75, 0.74, 0.305, 0.49], ...]}}
survey(from_m=[0.62, 0.25], to_m=[0.62, 6.25], every_m=0.25)
-> "water_between": [[[0.62, 1.5], [0.62, 4.5]]]
add_object(...) x 9: concrete blocks 0.48 x 0.96 x 0.48 m across the river
run(seconds=20)
-> 3 m upstream of them the level went from 0.506 to 0.636 m
dig(from_m=[4.77, -2.73], to_m=[4.77, 2.27], width_m=0.8, depth_m=0.7)
-> "dug_m3": 3.374, "columns": 88, "colliders_rebuilt": 2, "things_woken": 0
run(seconds=20)
-> the pond from 0.858 to 0.525 m
```

The ground is declared in the scene document -- a `terrain` block holding what
it was generated from and every edit made to it since, and a `water` block with
any change to its rivers -- so a rebuild makes the same ground again and the
playground's room is handed it in its spec. `dig` and `cut_block` are edits and
are recorded; what `dig` takes out is carried, and `fill` heaps only that back
(`ground does not come from nowhere`). What is carried of the ground is the
ground's own account, kept by the engine through every edit
(`environment_report`'s `ground.carried`): a rebuild replays the edits and
carries the same, and the playground's room -- opened from a spec that holds
the person's own digs and heaps -- carries what their spade dug, so `fill`
can heap it; `the_ground` in the room's opening message says how much
(`carried_m3`). `cut_block` takes a stone block out of
bare rock and adds it as an ordinary loose body. The water is carried across a
rebuild: a reservoir filled behind a dam is still there when a log is added.

**Regions beyond the edges** ([the watershed](../watershed.md)).
`make_terrain(kind="valley" or "channel", beyond_the_edges=true)` stands an
upstream reservoir beyond where the river comes in and a downstream basin
beyond its mouth, placed from the ground's own report: the reservoir 6 cm
above the river where it enters, fed at the river's own discharge, and the
basin at the mouth's lowest bed, letting water go over a 3 m weir. What
crosses each is the difference in level, either way: dam the river and the
reservoir fills while the basin falls. `water_state` then carries
`beyond_the_edges` -- each basin's level, volume, feed, what it lets out and
what it is sending into the valley, each connection's rate, and
`unaccounted_m3` for all the water together -- and `set_river` sets the
reservoir's feed. Ground with no river coming in and going out is refused
before it is touched. The playground's watershed room is the valley declared
this way.

Two things a model got wrong in the room, and what now says so. Objects on this
ground are **set on it**: asked for inside the ground, a block is lifted to rest
on the highest point under it and the answer says `seated_on_the_ground`, so y
only has to be roughly right. And a room holds 16,000 cells: nine blocks
0.48 x 0.96 x 0.48 m are 31,104, and the room refuses them -- the guide's dam is
nine blocks 0.32 m through and 0.48 m tall, 10,368 cells, which backed the
river up from 0.49 to 0.69 m in 30 s. Side by side, their centres go on the
0.04 m grid, or neighbours 0.48 m apart share a row of cells and are refused.

The numbers above were measured through `create_world`, which has no room's
cell budget; `tests/banjo_mcp_tests.py` makes the same dam and channel through
the server's own protocol. See [terrain-and-water.md](../terrain-and-water.md).

## Implementation

Roughly 700 lines of Python over the [C API](c-api.md), through
[the ctypes binding](../../bindings/python/banjo.py). It holds worlds by id,
converts the engine's refusals into sentences a model can act on, and turns
every non-finite number into `null` on the way out — infinity is a real answer
here (a brittle material's bending threshold *is* infinite) and JSON has no way
to write it.

Thirty-one tests in [`tests/banjo_mcp_tests.py`](../../tests/banjo_mcp_tests.py)
drive it as a real subprocess through the real protocol, because calling the
handlers directly would miss everything that goes wrong at a protocol
boundary — a notification answered when it should not be, a schema a client will
reject, an exception escaping as a crash instead of an answer.
