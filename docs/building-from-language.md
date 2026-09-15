# Building from language

The owner's review of 2026-09-15. Asked for "a long ski ramp", both of the
playground's chats built one tilted board:

- the lab's chat, a 1600 x 600 x 100 mm oak box tilted 12 degrees;
- the room's chat, a 1.44 x 0.40 x 0.80 m oak box tilted 15 degrees, at the
  person's feet, with a "Use the ramp" action it was nudged into inventing.

Both said they had built a ski ramp. A board is valid geometry and a stable
object, so the room accepted it, and nothing asked whether it was what had been
asked for. The review found why, in the prompts:

- `scene_chat.py` said "A ramp is one anchored box with a rotation of a few
  degrees" -- every ramp, whatever it is for;
- its cell budget was out by five: it said two 2000 x 60 x 400 mm ramps at
  20 mm cells were 60,000 cells, where they are 2 x (100 x 3 x 20) = 12,000;
- `world_chat.py` put everything close in front of the person, sized for the
  hand;
- neither sends the model a view of what it built, and both think briefly;
- "the engine accepted it" stands in for "it does what was asked".

Its recommendation: ask the model to say what the construction must
accomplish, let code calculate its geometry, then show it the result and test
whether it actually works.

```
request -> functional specification -> parameterised construction plan
        -> geometry compiler and constraint checks -> candidate in the real engine
        -> measurements + rendered views + a functional trial
        -> targeted repair, or a limitation said plainly -> the construction kept
```

## The increments

1. **The authoring contract** (this change). The one-box ramp rule is gone, the
   budget arithmetic is right, a thing to take is told apart from a structure,
   and a structure keeps explicit requirements that are measured. Done when a
   flat board cannot satisfy a ski-jump request merely by being named "ramp".
2. **Geometric builders**: a surface along a profile, a span between two ends,
   supports under a surface, interfaces aligned, a part repeated along a path,
   a space kept clear -- code doing the trigonometry that the model gets wrong,
   in a local frame, with a budget query that changes nothing. And a structural
   representation for what the cell budget cannot hold: a 12 x 2 x 0.08 m deck
   is 30,000 cells at 40 mm against a room's 16,000.
3. **Candidate review and trials**: side, top and perspective views with names,
   axes and a scale; a trial of what it is for (a sled down the ski jump),
   with no unexplained push and no friction lowered to pass.
4. **One authoring path** for the lab and the room.

Then a benchmark of real model-built constructions -- a ski jump, an access
ramp, a bridge, a staircase, an arch, a hollow container, a gate and a hoist --
and a controlled comparison of how much the model thinks and how it builds.

## Increment 1: the contract

### A structure is declared before it is built

`plan_construction` (MCP, [mcp.md](api/mcp.md#structures)) takes:

- a `kind`: `ski_jump`, `downhill_ramp`, `access_ramp`, `bridge`,
  `staircase`, or `structure`;
- a `reading`: one sentence saying how the request was read, which the person
  sees -- a ski ramp read as a jump, not as a slope to walk up;
- its line on the ground: `start_m` (a ramp's raised end) or `middle_m`, and
  `facing`;
- its size: `length_m`, `width_m`, `height_m`; `scale` `model` only for one the
  person asked to be small.

The kind brings what it must do, in numbers (`mcp/constructions.py`, `KINDS`):

| kind | what it must do |
|---|---|
| `ski_jump` | at least 6 m long and 0.6 m wide; its start at least 2 m up and a fifth of its length; one surface along it, with no gap or step over 5 cm; coming down by at least half its start height; rising at least 5 degrees over its last metre, to take off; every part anchored; every part standing on the ground, on scenery or on another part; 3 m clear beyond its end |
| `downhill_ramp` | at least 3 m long; its start at least 1 m up and 0.15 of its length; one surface; coming down; anchored; supported |
| `access_ramp` | at least 1 m long, rising at least 0.1 m; no steeper than one in eight (7.2 degrees) over any half metre; one surface; anchored; supported |
| `bridge` | at least 1.5 m long and 0.5 m wide; its deck from within 0.3 m of its start to within 0.3 m of its far end; one surface; walkable, no steeper than 12 degrees over any half metre; its deck at least 0.3 m (or as declared) above the ground or water under its middle; anchored; supported |
| `staircase` | rising at least 0.3 m; at least 2 even steps, each rising 0.10 to 0.22 m and going at least 0.22 m (the top one as far as it likes), their rises within 2 cm of each other; at least 0.5 m wide; anchored; supported |
| `structure` | its length and width along its line; supported |

The owner asked, the same day, whether this is "a general purpose llm toolset
or just focused on making a wooden board into a ski ramp". A kind is a
selection of measurements, not code of its own. The measurements are the
general part: the surface along a line and its width, slopes over a window,
gaps and steps, treads and risers, how high it stands over the ground or the
water, what stands in a space beyond it, and what holds up what. So a new kind
is a new selection, and the next ones on the benchmark (an arch, a hollow
container, a passage a person fits through) each want one or two
measurements more: a span's underside, an enclosed volume, a clear box.

The requirements are kept apart from the builder. Declared again, a
construction may raise them, never lower them, and cannot change its kind: a
repair cannot pass by giving up the thing it failed.

The answer says, worked out by code, where a point `s` metres along its line is
and the `rotation_deg` of a board along it (`[0, yaw, t]`, tilted `t` degrees).

### What is built is measured

`check_construction` measures it from the world's own geometry:

- rays cast straight down every centimetre along its line find its surface,
  from half a metre before its start to twice its length. A ray meets a body as
  the solver collides it: a tilted board as its exact box, not a staircase of
  cells (measured within 0.01 mm of the box's own top, with 40 mm cells);
- its length and start height from where the surface begins and ends;
- its width from rays at both edges, a quarter, half and three quarters along;
- a gap is a stretch of the line with none of it under it, and a step a rise or
  drop between rays a centimetre apart;
- its takeoff and steepness are the slopes of lines fitted to the surface;
- a part touches another when their boxes, as turned, come within 6 cm -- a
  separating-axis test, not their level bounds, which round a tilted board are
  so big that a post a metre short of it would have counted as holding it up;
- a part stands on the ground when a corner is within 6 cm of the ground under
  it (the terrain's, surveyed, in the valley);
- its runout is clear when no other body stands in the box beyond its end, as
  wide as it and 2.5 m high.

Its parts are those it was given and, in the turn it is declared, everything
added after it until another is declared.

### In the playground's room

- `plan_construction` is one of the calls that change what the room is
  (`room_world.AUTHORING`). The room keeps each declaration with its parts, as
  `constructions` in its spec, and opens it again with them.
- As the chat answers, every structure it declared or changed that turn is
  measured. One that fails goes back to it with the measurements, at most twice
  a turn (`world_chat.NOT_FINISHED`). After that its answer starts "Not
  finished:" with what failed and what it needed, and the page shows each
  requirement, measured, under the answer.
- The guide tells a thing to take (it goes close in front of the person) from a
  structure: its middle 6 m out, its line across their view
  (`the_person.structure_middle_m`, `across_the_view`), the size its use needs.
  It reads what a ramp is for, what a bridge and stairs are, and gives three
  worked structures -- a ski jump, a staircase and a bridge -- that pass every
  check, each built along two lines by `tests/chat_history_tests.py`.
- The actions nudge (`NOTHING_OFFERED`) is only for a thing to take: asked for
  a ski ramp, it had the chat give an anchored board a "Use the ramp" action.
- A call that works the running room (`use_action`, `drive`, `operate`) made
  after a change in the same turn is held back until the change is in the
  running room, and made then (`world_chat.HELD_BACK`, the server's `then`).
  Measured before: asked to wind a hoist up onto a block it had just added, the
  chat pressed "Wind it up" on the running room, where the block was not yet,
  and described the crate stopping on it from its own copy.
- `add_object` says when a side over 4 m was made 4 m (`size_cut`): a 7 m board
  was quietly made 4 m.

### Not yet

- The model still works out every part's place from the worked example and the
  plan's answer; the builders of increment 2 are what take that from it.
- Nothing is tried: a ski jump that passes is the right shape and stands, but
  no sled has gone down it (increment 3).
- The lab's chat (`scene_chat.py`) has the corrected prompt but not the
  contract (increment 4).
