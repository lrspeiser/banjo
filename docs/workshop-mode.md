# Workshop Mode: fast isolated design, variants, tests and component learning

Workshop Mode is a second view of Banjo for designing **one object or assembly at a time**. The live world is paused at an immutable revision while the workshop forks a cheap design sandbox. The sandbox may generate many candidates, compare them, run bounded tests and collect user feedback without advancing the outside world's clock or consuming its inventory.

The core product rule is:

> **Explore cheaply in wireframe; prove selectively in physics; materialize only the chosen design; commit it to the live world only as an explicit transaction.**

This is deliberately different from putting the whole live world into a hidden room. A workshop candidate is not a second authoritative world. It is a design branch rooted in a saved live-world revision.

## Why this exists

The general world has too much state for design search. If an agent wants to try 40 chair-leg geometries, rebuilding or copying the river, terrain, machines, inventory and every unrelated body 40 times is both expensive and conceptually wrong. The agent should reason about the chair, its interfaces and its tests.

This gives Banjo three execution costs instead of one:

1. **Wireframe cost** — almost free. Semantic members, dimensions, interfaces and constraints; no voxels and no running physics.
2. **Prototype cost** — selected candidates only. Compile enough material/rigid geometry to run a local functional test.
3. **World cost** — the winner only. Validate resources, process/energy, placement and current world revision, then commit atomically.

The first code slice is `mcp/workshop.py` with tests in `tests/workshop_tests.py`.

## User experience

A player looks at an object, a partial assembly or an empty work area and chooses **Workshop**. The outside view visually freezes and dims. The workshop becomes the primary viewport.

The screen should have four persistent regions:

- **Object view** — orbitable isolated candidate; wireframe by default, material preview on demand.
- **Variants** — thumbnail/grid of current candidates and their measured differences.
- **Parts** — semantic assembly tree (`top`, `leg-1`, `hinge`, `axle`, etc.) with the component family and parameters that produced each part.
- **Ask / tests / feedback** — the agent conversation, proposed trials, test results and simple user signals: select, reject, like/dislike, "more like this", and freeform notes.

The user should be able to say:

- "make the legs thinner"
- "show me six different leg styles"
- "I like #3 but make it lower"
- "try the same legs on a chair"
- "which two survive 120 kg and are hardest to tip?"
- "make that one real"

The key behavior is that "make that one real" is qualitatively different from "show me another version". The former crosses the materialization/transaction boundary; the latter never touches the live world.

## The workshop session

A workshop opens from:

```text
session_id
source world revision / snapshot identity
target selection or requested new object
local coordinate frame
available component-library version
available material/process capability versions
player knowledge and visible inventory as read-only context
```

While open:

- the outside world's clock does not advance;
- nothing outside the target sandbox is simulated;
- inventory is never debited;
- prototypes cannot charge or recharge live energy stores;
- tests run in isolated scratch worlds;
- the agent may create and delete candidates freely;
- user feedback is durable design evidence, not a physics result.

If the live world somehow changes through another authority (future multiplayer, another editor, etc.), materialization must revalidate against the current world revision rather than silently applying the workshop's old assumptions.

## Representation ladder

### Level 0 — semantic design

This is the cheapest representation. It contains purpose, component families, parameters and relationships:

```text
Table
  top: rectangular surface 1.2 x 0.7 m
  legs: family leg x4
    height 0.72 m
    style straight
    section 60 x 60 mm
  function: hold 100 kg on top; remain standing under tip trials
```

No world coordinates should be required other than a local assembly frame.

### Level 1 — wireframe / construction skeleton

A wireframe is not merely visual lines. It is an inspectable geometric contract:

```text
part id
semantic role
shape primitive or centerline/profile
local transform
dimensions/interfaces
material class/preference
component-family lineage
```

The browser may draw it as edges/lines even when the member is logically a solid box. This is ideal for agent iteration because changing dimensions does not require voxel generation.

### Level 2 — surface preview

A render mesh or procedural skin may be generated around the wire representation. This is presentation, not authoritative matter. It lets the user judge aesthetics before paying voxel or test cost.

A component may provide a skin generator distinct from its physical representation. A turned wooden leg, for example, can have an attractive smooth preview while its first physics prototype uses a simpler conservative solid.

### Level 3 — physical prototype

The chosen wireframe is compiled into the cheapest physical representation that can answer the requested test:

- rigid boxes for balance and gross loading;
- beam/rod model when available for slender members;
- voxels/lattice where fracture/material behavior matters;
- joints, motors, ropes, fluids, etc. only where the function needs them.

The compiler should not voxelize the entire candidate automatically. Fidelity is selected by the question being asked.

### Level 4 — materialized design

The approved design is snapped/compiled into a complete Banjo construction plan. `mcp.workshop.materialize()` currently performs the first conservative version: each wire solid becomes a cell-aligned object plan, with semantic role and design provenance retained.

This still **does not mutate the world**. It must pass:

1. placement validation;
2. inventory/material allocation;
3. supported process and fabrication-energy validation;
4. required functional trials;
5. stale-world/stale-design checks.

Only then may a commit transaction publish it into the running world.

## Component library

The library should store **families of useful physical concepts**, not finished named objects.

Good early families:

```text
Structural
  leg
  post
  beam
  brace
  panel
  shelf
  frame
  truss_member

Connections
  fixed_joint
  pinned_joint
  hinge
  slider
  axle_support
  bearing
  latch
  rope_attachment

Motion / power
  axle
  wheel
  pulley
  drum
  crank
  lever
  spring
  motor_mount

Containers / surfaces
  tray
  wall
  rim
  handle
  lid
```

A `leg` is intentionally not `table_leg` or `chair_leg`. It describes a support member with dimensions, end interfaces, style parameters and validity bounds. Tables, chairs, benches and work stands can all consume it.

The initial implementation registers `leg` with:

- height;
- width/depth;
- `straight`, `splayed`, or semantic `tapered` style;
- bounded splay angle;
- material.

`rectangular_four_leg_frame()` proves one family can build both table-like and chair-like candidates.

### Components need contracts

Each mature family should eventually expose:

```text
id + schema version
semantic roles it can satisfy
parameters + ranges
input/output attachment interfaces
construction geometry generator
preview/skin generator
physical compilation choices
applicable tests
known validity limits
examples / successful design evidence
```

Do **not** let the LLM's prose become the library. The library is structured and deterministic. The LLM chooses, parameterizes, combines and proposes new families.

## Agent design loop

The agent should use a hierarchical search instead of emitting final coordinates.

```text
1. Understand purpose and acceptance criteria.
2. Choose an archetype or decompose into semantic roles.
3. Resolve roles against component families.
4. Produce a wireframe baseline.
5. Ask deterministic geometry/constraint code to resolve interfaces.
6. Generate a bounded family of variants.
7. Apply cheap static/geometric filters.
8. Render survivors as wireframe thumbnails.
9. Let the user/agent select candidates for physical tests.
10. Run isolated tests at the minimum necessary fidelity.
11. Rank/explain results; retain Pareto alternatives, not one fake "best".
12. Record user selection/feedback.
13. Repeat locally.
14. Materialize the selected design.
15. Revalidate against resources/process/world revision.
16. Commit atomically to the live world.
```

The agent should be able to create hundreds of Level-0/1 variants but only a small number of Level-3 prototypes.

## Variant search

Variants should be explicit lineage, not anonymous regenerated objects.

Each candidate records:

```text
candidate id
parent candidate
changed parameters
component versions
constraints
cheap metrics
physical tests run
user feedback
```

The first `variants()` helper creates Cartesian parameter sweeps without touching Banjo. Later strategies can include:

- grid/random/Latin-hypercube sweeps;
- constraint-directed mutation;
- evolutionary search;
- surrogate-model/Bayesian optimization;
- "more like selected candidate" local exploration.

The workshop should preserve a Pareto set when objectives conflict: weight, material, stiffness, stability, cost, aesthetics, etc. The AI can explain tradeoffs but should not hide alternatives behind one scalar score.

## User feedback and learning

User feedback belongs to the design system, not the physics law. A record should bind feedback to the exact candidate lineage and parameters.

Examples:

```text
selected=true
rating=5
note="I like the splayed legs but make the top thinner"
```

Over time this supports two different forms of learning:

1. **Personal preference** — this player likes certain proportions/styles.
2. **Reusable engineering evidence** — this component family worked under a particular measured trial.

Never merge the two. "The user likes tapered legs" is not evidence that tapered legs carry more load.

## Test library

The workshop needs reusable functional tests parallel to the component library.

Early tests:

```text
static load
center-of-mass / tip margin
push / pull
drop
swing/open/close
clearance / fit
range of motion
fatigue proxy later
thermal exposure
water fill/leak
machine stall / travel
```

`rectangular_four_leg_frame()` already declares `static_load` plus tip tests in x and z as design intent. Those are currently specifications only; the next workshop increment should bind them to scratch-world execution.

Tests should return measurements and limitations, not pass because of a display name. A table is not stable because it is named table.

## Wireframe rendering

The renderer should support three overlays from the same candidate:

- **skeleton** — centerlines, interfaces and axes;
- **wire solids** — box/profile edges for spatial understanding;
- **skin** — optional appearance preview.

Useful visual annotations:

- component family colors/labels;
- attachment points;
- local axes;
- dimensions;
- load arrows;
- center of mass;
- support polygon;
- collision/clearance failures;
- changed parts highlighted between variants.

The default should be wire solids because they communicate occupied volume without the cost or visual noise of voxels.

## Voxel/material compiler

The wireframe is not itself matter. Materialization should progressively compile it:

```text
semantic components
  -> resolved local solids/interfaces
  -> choose physical representation by required tests
  -> snap/mesh/discretize
  -> validate no accidental gaps/overlap
  -> assign material and state
  -> estimate inventory/process/energy
  -> prototype tests
  -> final construction plan
```

When the final object needs a smooth appearance, keep authoritative physical volume beneath a derived surface skin, consistent with Banjo's existing project contract.

## World commit

The commit operation should eventually resemble:

```text
commit_workshop_design(
    session_id,
    design_id,
    expected_world_revision,
    placement,
    material_sources,
    process_plan,
    expected_design_revision,
)
```

It must be atomic. A stale world, collision, missing stock, missing process, insufficient energy or failed required trial leaves the outside world unchanged.

On success the live object keeps:

- design id/revision;
- component lineage;
- materialization/compiler versions;
- test evidence used for acceptance;
- operation/resource receipt.

That provenance lets the user reopen the object later and say "edit this chair"; the workshop recovers the design rather than reverse engineering anonymous voxels.

## What to build next

### Increment 1 — landed on `agent/workshop-mode`

- pure isolated workshop/session contract;
- `banjo.workshop.v1` wireframe representation;
- reusable component registry;
- initial `leg` family used by table and chair frames;
- cheap variant forking with lineage;
- structured user feedback;
- conservative cell-grid materialization plan;
- tests proving no candidate operation claims a live-world commit.

### Increment 2 — visual workshop page

Add a `/workshop` or modal/route from `/world` that:

- freezes the room's visual/time controls;
- receives one wireframe candidate;
- renders orbitable wire solids;
- shows variants side by side;
- lets the user select/reject and annotate;
- exits without changing the room.

Use static demo designs first; no LLM dependency is necessary to validate the interaction.

### Increment 3 — workshop agent API

Expose bounded operations such as:

```text
open_workshop
list_component_families
instantiate_component
compose_design
fork_variants
inspect_candidate
record_feedback
materialize_candidate
close_workshop
```

The LLM never receives permission to call the live-world authoring tools while it is merely exploring a workshop candidate.

### Increment 4 — scratch physical trials

Bind the first tests:

- table/chair static load;
- tip stability;
- gate open/close;
- simple wheel/axle free rotation;
- hoist travel/stall.

Compile only the candidate and minimal fixtures into a scratch `LiveWorld`.

### Increment 5 — transactional world return

Integrate current inventory, energy/process work and world-carry semantics. The selected workshop result becomes one validated atomic live-world edit while unrelated world state remains exactly frozen at the workshop source revision.

### Increment 6 — learned design/component library

Persist:

- component definitions and versions;
- accepted design archetypes;
- physical evidence;
- user preference records;
- derivation/lineage.

Allow a successful custom subassembly to be promoted into a new reusable component family only through an explicit review step. This prevents the library from filling with every transient agent experiment.

## Acceptance examples

### Table / chair legs

1. Open an empty workshop.
2. Build a 1.2 m table with four `leg` components.
3. Reuse the exact family for a 0.46 m chair.
4. Generate straight/splayed/tapered candidates without materializing matter.
5. Render all as wire solids.
6. Select two for static/tip tests.
7. Give feedback and request more variants around one.
8. Materialize the winner to the cell grid.
9. Verify the returned plan still says `not-committed` until live-world resource/process checks are added.

### Editing an existing object

1. Pause live world at revision R.
2. Open chair C from its persisted design lineage.
3. Make ten back/leg variants in isolation.
4. Break prototypes freely; C in the outside world remains unchanged.
5. Pick one candidate.
6. Revalidate against current C revision and world R/current revision.
7. Atomically replace C, preserving old revision for rollback.

## Architectural consequence

If this works, the workshop becomes Banjo's **design compiler and learning environment**, while the general world remains Banjo's **persistent physical reality**.

That separation is powerful: the LLM gets freedom to search, the player gets fast visual iteration, the physics remains authoritative for claims, and the live world does not pay the computational or state-management cost of every discarded idea.
