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
| `list_materials` | the eight materials and what each actually does, with measured speeds. **Worth calling first** — the numbers are not the ones you would guess. |
| `create_world` | build a world from a list of objects; returns an id |
| `run` | let time pass and say what happened: every break, every dent, and the hardest contacts with the speeds they would have needed |
| `drop` | the common experiment: put an object a given distance above a point, let it fall, report. The height is measured from **what it lands on**, not from the floor. |
| `describe_world` | every object, where it is, and what has happened to it |
| `add_object` / `remove_object` | change a world. It is opened again from its scene, so anything in flight starts over — and every joint is hung again. A removed object takes the joints that held it with it, and they are listed. `add_object` given `position_m` as **[x, z]** sets the thing down on whatever is under that point — the ground, the floor or the top of what is there — and says what in `set_down`; [x, y, z] puts it exactly there, and when that is in the air the answer's `in_the_air` says how far above what is under it the thing starts, and that it will fall. On ground with water it says `in_water` when that is where it went. |
| `move_object` | put an object somewhere else, at rest: an **edit**, not a push. Refused for a joined object, with the reason — a joint is made at fixed points |
| `clear_world` | empty a world, joints and all, to build it again. It stays open under the same id |
| `pick_up` / `place` / `let_go` | the hand: take hold of something already in the world and move it. Without this a model can only add new objects from above — it can build a scene but never rearrange one. |
| `collect` | sweep up the loose pieces near a point and say what they were made of, by material and by weight |
| `carried` | what has been swept up in this world so far |
| `cast_ray` | what a ray meets first — what is above or below something, what is in the way |
| `blade` | give a body an **edge**: where it runs, which way it faces, how thick, how sharp (a radius) and its bevel, and where it is held. There is no cutting power: what resists the edge is the target's own fracture energy and hardness. [docs/cutting-model.md](../cutting-model.md) |
| `blades` | every edge, what it has cut and what that cost |
| `wield` | take hold of a body by its grip with a hand whose force (800 N) and torque (60 N m) are bounded — not `pick_up`, which places a thing exactly |
| `swing` | swing the wielded blade the way a person does and report every edge contact on the way: edge, slice or press (it bit), glancing, flat or point (an ordinary contact), blunt or brittle (it could not). With `through_m`, `pointing` and `edge_facing` the hand takes the blade up off its rest, back clear and round to one side, then swings it round a shoulder half a metre behind the grip, 100 degrees in `seconds` (0.13 by default), so that the middle of the edge passes through `through_m`; an edge facing across the swing leads with the edge, one facing up or down leads with the flat. (Driven along a straight line at its grip, a sword trails its point: a measured straight swing crossed the rope's line 0.19 m short and met nothing.) With `to_m` instead it moves the grip along a straight line, which is a press or a push |
| `cuts` | every edge contact since the last swing, including the ones that cut nothing and why |
| `close_world` | free it |
| `hinge` / `slide` | a pin or a groove: `b` turns about, or slides along, a line fixed in `a` |
| `tie` / `reeve` | a rope between a point on each of two things, or one run over two fixed pulleys |
| `fix` / `spring` | a latch or bracket that holds two things as one piece; an elastic element that pushes and pulls |
| `joints` / `hinge_friction` / `unhinge` | read them, stiffen them, take one out |
| `overloaded` | what is carrying more than it can hold, worked out from statics — the only way a loaded shelf is ever noticed |
| `list_substances` | what matter is made of: substances, reactions (with where every number came from) and the catalogue's compositions — oak is dry wood, moisture and ash, which is why an oak log can burn |
| `enclose_gas` | a column of gas under a loose piston, starting at the pressure that holds the piston and its load up |
| `heat` | heat from outside — kindling, a torch, a stove — into a body or a gas region, from when the world starts |
| `thermal_state` | how hot everything is, what is burning and how hard, the fuel left and how long it would last at this rate, what the gas is doing, and the energy ledger |
| `make_terrain` | ground that is not flat: a **valley** with a river along it and a pond beside it, made once by physics -- drainage decided where the river runs, erosion wore its channel -- and cached; or a basin holding a lake, a sloping channel with a stream, flat ground, or none. [docs/terrain-and-water.md](../terrain-and-water.md) |
| `survey` | the ground and the water at a point or along a line: height, rock, soil or sand, slope, and the water's depth, level and speed. How to find the river, and what to stand things on |
| `water_state` | the rivers and ponds: how much water, what comes in and goes out, each pond's level, the river every 2 m along its course, what is in the water and whether it floats, and the water's ledger |
| `dig` / `fill` | a trench or a pit, so wide and so deep below the ground as it stands; what comes out is carried, and `fill` heaps only what was carried |
| `cut_block` | a block of stone out of bare rock; the ground loses exactly that much and the block is an ordinary loose object |
| `set_river` | a river's discharge from now: a flood or a drought |

`add_object` also takes `contents` (what the object is made of inside, by mass
fraction) and `temperature_k`. Every `run` carries a `heat` summary whenever
anything is hot, burning or pushing. On ground that is not flat, `add_object`
seats a thing on the ground under it and says whether it is in water, and every
`run` carries a `water` summary.

`run` holds the **break conversation** itself. That is the part of this engine a
caller can get wrong: ignore it and the world freezes at the first impact for
ever. Nothing using these tools has to know that.

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
  never silently.

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
the segment like the end of a stiff arm that is not there.

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
(`ground does not come from nowhere`). `cut_block` takes a stone block out of
bare rock and adds it as an ordinary loose body. The water is carried across a
rebuild: a reservoir filled behind a dam is still there when a log is added.

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
