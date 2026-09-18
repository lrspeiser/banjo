# What is not done

**Workshop installation update:** [The first prototype adapter](workshop-install-checkpoint.md) is implemented for authoring-only, single-material solids on flat floors. This does not complete the inventory/fabrication, terrain, articulated or mixed-material installation gates below.

Written 2026-09-16, at the close of the authoring work that began with the
owner's review of 2026-09-15. Everything here is either unfinished, recorded
but unfixed, or finished in a way that is easy to misread. Numbers are
measured, not estimated; where a thing was measured badly, that is said too.

The work that IS done is in [development-status.md](development-status.md),
[building-from-language.md](building-from-language.md) and
[asset-compiler.md](asset-compiler.md).

## 1. Building from language: increments 3 and 4

Increments 1 and 2 landed (the construction contract; the room laying a
structure out on the ground itself). The rest of the owner's architecture did
not.

- **Nothing is ever tried.** A construction that passes is the right shape, is
  anchored, stands on the ground and has its clearance. No sled has gone down a
  ski jump, nobody has walked up a staircase, nothing has crossed a bridge.
  `check_construction` is geometric. Increment 3 -- a test sled, with no
  unexplained push and no friction lowered to pass -- is not started.
- **The model never sees what it built.** No rendered side, top or perspective
  view is sent back to it. It answers from numbers alone.
- **The lab's chat is not on the contract.** `playground/scene_chat.py` has the
  corrected prompt (a ramp is read for what it is for; the cell arithmetic is
  right) but cannot declare or check a construction. Increment 4, one authoring
  path for the lab and the room, is not started.
- **The benchmark is a third built.** The owner asked for eight: a ski jump, an
  access ramp, a bridge, a staircase, an arch, a hollow container, a gate and a
  hoist. There are kinds for the first four plus a generic `structure`. An
  arch, a hollow container, a gate and a hoist as *constructions* -- declared,
  built by code, measured -- do not exist.
- **No controlled comparison of how the model is run.** Baseline against better
  planning against structured construction against structured-with-review was
  proposed and never done. Both chats still think at `"effort": "low"`
  (`world_chat.payload`).

## 2. The owner's placement rule, half done

The owner, 2026-09-15: "if there is already something in a space we need to ask
the user if we can move it or we try to put it where it won't overlap
something, that includes the ground, which in general we should make the bottom
of the object be no lower than the ground."

Done: the room refuses overlaps by cells; it lifts a body given a height inside
the ground and says so; the guide tells the chat to build where there is room,
never to move or take away the person's things without asking, and to read what
the room says when it moves a part; `add_object` now says when a side over 4 m
was cut to 4 m.

**Not done: the room's corrections still reach only the chat, never the
person.** Measured on the owner's own sim: asked for a staircase two storeys
tall, the chat was told `set_down` (a tread was inside the ground and was set on
top of it), `overhangs` (2 of 9 points over the ground), `in_the_air` (a tread
0.16 m above the one below), and `seated_on_the_ground` (a stringer lifted from
y 3.0 to 4.10) -- and then answered "the staircase stands fixed where placed (no
movement or failure reported)". Every clause of that was contradicted by answers
it had just received.

The fix, designed and not built: carry what the room changed in the turn's
answer (as `checked` already is) and show it under the reply in the page, so a
claim cannot paper over it.

## 3. Cost

**Update:** [The object-result transport checkpoint](chat-object-transport-checkpoint.md) now compacts repeated successful authoring outputs for the room chat, after a full baseline. The original measurement below is historical; live model/token-cost comparison and repair-round cost isolation remain open. MCP answers and audit logs stay complete.

- **Every `add_object` answer carries the whole world's object list.** One
  valley turn read **2.76 M input tokens** for 30 rounds. Trimming that answer
  to what changed is not done, and it is the single largest cost in the chat.
- A turn that declares a construction now runs a check at the end and up to two
  repair rounds. The cost of that was not measured separately.

## 4. Millions of cells

The owner asked how to grow a room to millions of cells. Two measurements were
taken and none of the work was done.

Measured: **integration is nearly free and barely scales** -- 492 cells cost
0.059 ms per 1/240 s step, 16,680 cells cost 0.067 ms (34x the matter, 14% more
time). **One break costs 309 ms** -- 5,275 substeps of 1.36 us, 44 pieces,
three runs within 3 ms, from `scratchpad/measure_trial_clock.py`.

So the 16,000-cell cap protects against fracture, not integration. None of the
four changes that follow from that exist:

1. **Anchored matter costing no cells.** Scenery never breaks and never moves;
   it needs collision geometry, not a lattice. An anchored ski jump spends
   ~3,000 of a room's 16,000 on matter that can never deform.
2. **A cell size per body.** One size governs a whole scene today
   (`SceneBody`; contact radius and support offset are shared).
3. **Dormant islands that wake.** A cell's cost is per substep, not per
   existence.
4. **Refining on break**, which needs a lattice per body.

**A fracture-cost-against-cell-size measurement was attempted five times and
failed five times.** Four hand-built scenes measured a sleeping or a
never-breaking world; the fifth reported a pane that survived at 10, 20 and
40 mm. Only `measure_trial_clock.py`, which was validated against a known
before-and-after result, can be trusted. Anyone continuing this should drive
that script rather than build a sixth scene.

## 5. The asset compiler

What works is in [asset-compiler.md](asset-compiler.md): a real AP214 assembly
(441,968 bytes) becomes a blueprint in under a second at every resolution, 5
unique parts converted once and placed 18 times, 30 tests.

- **Nothing imported can enter a room.** The compiler emits blueprints; the
  engine cannot load one. There is no scene-schema reference to a compiled
  asset (a body is a shape name, a size and a material) and no C API entry that
  accepts cells. Short of that, a blueprint can only be expanded into a join
  group of boxes, which throws away the part identity that makes one conversion
  serve twelve instances.
- **No cell size is both resolved and affordable**, measured on the real file:
  731 cells at 10 mm (the 3 mm nut has vanished), 6,196 at 5 mm (bolt holes weld
  shut, `required_gap_lost`), **28,804 at 3 mm against a 16,000 budget**, 95,165
  at 2 mm. This is blocked on a cell size per body, section 4.
- **No OpenVDB.** It has no distribution for Python 3.13 on Windows, so there
  are no narrow-band level sets and occupancy stays a dense scan. (`pythonocc-core`
  has none either; Open Cascade is reachable as `cadquery-ocp==8.0.1.0.0`.)
- **STEP units are unverified.** Open Cascade normalises to millimetres as it
  reads, so a part declared in another unit is caught by nothing. First thing to
  add.
- **Connections cannot come from STEP.** AP214 says a bolt is *in* an assembly,
  never that it is threaded into anything: `connection_ambiguous` fired 10-22
  times on the real file. Joints must come from reviewed metadata or geometry
  proposals.
- **No traversal validation.** The imported file is a bracket assembly. It
  exercises instancing and assembly structure thoroughly and traversal not at
  all. Nothing imported has been walked on.
- **Rotation conventions are unreconciled**: anything finer than a quarter turn
  is treated as a different asset (a 45-degree placement costs +3.50% cells).

## 6. Engine defects recorded and not fixed

- **`buildBonds` bonds across a void** (`src/matter/Lattice.cpp:113`). It walks
  a cube of offsets to the neighbour horizon and bonds to any occupied cell it
  finds, with no test that the segment between them crosses empty space, so
  material on two sides of a one-cell slot bonds through the slot. Recorded with
  a failing fixture in the compiler's tests. In the engine the fix costs 3 of 16
  offsets at horizon 2. Changing it is a material-model change and must be
  regression-tested, which is why it was not done here.
- **Inertia is reconstructed two ways.** `calculateRestInertia` includes each
  cubic cell's own inertia; `mergeLattices` rebuilds a merged tensor from point
  masses. Whether they agree was not audited.

## 7. Older open items, still open

- **A hoist stopped itself** with "too weak at this setting: the load turned it
  back" after rising 1.05 m, in a room the chat built. Never diagnosed.
- **The chat buried a ball under the terrain** (y 0.08 where the ground was
  2.36). Raised as a background task and not fixed.
- **`agent/shard-rest`** (bonds broken in one run coming back in the next;
  shards released 45-140 kJ) is uncommitted and awaiting the owner.
- **`agent/foresight-partner`** is uncommitted.
- **Render has no disk** on the free plan, so rooms saved there do not survive a
  deploy or an idle spin-down.

## 8. Finished, but easy to misread

- **"The valley ski ramp works" means `build_structure` works.** A chat that
  places parts by hand on a slope still gets it wrong -- it did, for 30 rounds --
  and the room now says "Not finished" instead of accepting it. The guide sends
  it to the builder, but nothing forces it.
- **"Passes every check" is geometric.** It means the right size, one surface,
  a takeoff that rises, every part anchored and standing, a clear runout. It
  does not mean anyone has used the thing.
- **The construction contract binds the room's chat only.** The MCP tools are
  available to any client, but only `playground/world_chat.py` measures what was
  declared and refuses to call it done.
