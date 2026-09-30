# Workshop Mode: fast isolated design, variants, tests and component learning

**Recipes update, September 30:** [Visual cards and Make results](recipe-contract.md#visual-cards-and-make-feedback--september-30-2026) replace prose-first listings with source pictures, material progress/missing supplies and compact Build/Skill/Uses values. Make preserves Lab selection, reports on Recipes and adds separate native copies; View in World faces the new item. Current Workshop Make requires no technique unlock. The 55 browser and 6 screen-navigation regressions pass; this is UI/action integration, not a new physical law.

## Visual Inventory and starting a design — September 30, 2026

Inventory shows Hands & bag, Materials & supplies, categorized Saved designs, Saved parts when present, and Building blocks. Cards show names, shape thumbnails and a relevant action rather than family parameter dumps. Supplies retain useful mass quantities; they are stock for Make, not editable physical items. Saved designs open in Lab; a saved part starts a separate design copy. The redundant list of objects standing in the World is removed from Inventory.

Sixteen supported single-part families are grouped into Frames & supports, Surfaces & panels, Wheels & axles and Machine housings. Choosing one creates a uniquely identified saved draft through the existing authoring/feedback APIs, then explicitly selects it in Lab. It spends no stock and creates no native world object. These are starting shapes, not working machines: collector/power behavior and container walls require further authoring. Multi-part families that cannot seed the existing custom-source API are not offered here.

The screen explains the intended path: choose a block or open a saved design, describe changes in Lab chat, Save the design, then Make a physical item when admission and stock allow it. Merely visiting Inventory generates no LLM request. With an AI key connected, chat uses the existing assistant authoring tools; without one, the screen states that only basic chat edits and existing Recipes are available. Paid-provider quality and arbitrary prompt-to-functional-product success are not measured by this checkpoint.

Saved thumbnails read actual source parts with up to three requests in flight and a bounded revision cache. A reusable offscreen renderer leaves Lab geometry and selection unchanged. Shape previews do not certify grid admission, function or strength. Legacy Saved storage and carried-state adapter boundaries below still apply; this is not a persistence migration or new physics law.

Windows verification on source based on main `7b1b4d1`, using Chrome and the existing Visual Studio Release native engine: 55 Workshop browser tests and 4 navigation/Inventory tests pass (59 total). The added journey clicks all 16 blocks, checks distinct saved drafts and Lab selection, unchanged native carried/material/goods records, preview isolation, and a saved-part copy/reload with the original preserved. Screenshots were inspected. JavaScript syntax, Python compilation and the source-registration guard pass. The broader physics suite and a live paid model were not rerun for this UI checkpoint. The published revision is recorded by this section's Git commit.

## Inventory selection and shared navigation — September 30, 2026

Implemented browser behavior:

- The Lab starts empty. A template URL (`kind`) or old remembered template does not populate it.
- Explicitly select a physical item in your hands/bag, a saved design, or a saved assembly from Inventory. The current selection travels in `carry`, `design` or `library` when changing screens; reopening a carried item checks the current guest's inventory again. Clearing the Lab removes this selection, geometry, trials and undo history, without changing the physical inventory.
- Workshop-built carried items reopen their recorded installation recipe, including the five-part Camp stool. A missing installation recipe fails visibly. Other carried items retain the existing one-part design adapter; sphere/capsule surrogates and unsupported shapes remain approximations, not state-preserving physical replicas.
- A saved design is an editable design copy. Explicit Save updates the selection URL to the saved result, so reload reopens that result. Opening/editing alone does not alter its saved source or the carried object. Native Make still uses the existing admission, stock and commit pipeline.
- World, Inventory, Lab, Skills, Recipes, Market and Goals share navigation in the right rail, above chat. Workshop tab changes preserve the selected world and guest. Returning through World preserves the explicit selection for a later Lab visit. Recipes still offers Make; templates no longer open an unselected Lab through “Design it.” Empty-Lab chat cannot submit an item request.
- Startup loads catalog metadata without adopting its default candidate. Optional history arrives after selection and screen activation and cannot erase unsubmitted edits or pending trials.

Verification: `tests/workshop_navigation_tests.py` covers an empty Lab with old template memory, missing/foreign carried selections, actual Inventory clicks, a saved design's round trip through World/Skills/reload, clearing/reload, native Camp stool dimensions/mass and unchanged bag/hand records. `tests/workshop_browser_tests.py` uses an explicitly selected saved fixture for its existing bench regressions. The new selection suite is required in CI. Windows evidence uses Chrome and the existing Visual Studio Release native engine, based on main `3f6f0a9`; no solver/material law or native source changed.

Measured checkpoint: 3 selection tests, all 55 Workshop browser regressions, 4 opening-goal tests, 7 AI-character tests, 4 named-world tests and the existing native/browser bag-slot/Workshop-drag journey pass (74 checks). JavaScript syntax, Python compilation and source registration pass; all 286 C++ sources remain registered. `scripts/verify_screen_sim.py` includes selection tests in both modes; the complete broader physics screen suite was not rerun for this UI checkpoint. The published main revision is recorded by this section's Git commit and the task handoff.

Ownership boundary: physical carried items are guest-specific, and database assemblies use the existing personal library. Legacy Saved designs remain in the existing world Workshop folder; this UI change does not migrate them to account-private storage. Neither the browser selection checks nor the design adapter certify strength, fracture, collision-aware avatars or production scaling.

Workshop Mode is a second view of Banjo for designing **one object or assembly at a time**. Its design sandbox may generate candidates, compare them, run bounded trials and collect feedback without installing them or consuming native stock. Named-world simulation can continue through other viewers or characters; entering Workshop does not lock or freeze their world. Native Make remains an explicit transaction against the current room and stock.

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

## Lab, Inventory, Skills and Recipes

**Status, 2026-09-26.** The bench is the chat on the left, the object, and
four tabs over the object: **Lab**, Inventory, Skills, Recipes. The chat
stays beside all of them, with its suggestions (each a real turn) and a
narration of what the model is doing while a turn runs. On the Lab's one
bar there are only the two acts that leave the bench, Check it and Make it,
and the way to the world: no product dropdown (products are opened from
Recipes and Inventory), no Wire/Skin, no points of view. The other three
tabs read beside the Lab and spend nothing (`workshop_tabs`, one route
each: `/api/workshop/inventory`, `/skills`, `/recipes`).

**Takes.** Under the tabs is a strip of little pictures of the thing. The
first is *Clean*: the design as it is, untouched by any run, captured as
it is drawn. Every run -- one the chat asked for, one asked for below the
object -- becomes a take beside it, with its picture and its verdict in a
line ("it is 0.79 m up, has moved 2396 mm and turned 0.6 degrees; nothing
broke"), and stays for the session. Click a run's take and its replay is
shown; click Clean and the design is back, with no run over it. A run
never replaces the thing.

**Drive it.** The owner, of a panel of controls and a Do it button: "I
don't understand what turning the left wheel to reverse and hitting do it
means ... allow me to become the object and control it with the keys."
So, under the object: Take the keys, and you are the thing. W or up goes,
S or down backs, A or left turns left, D or right turns right, and a
machine that flies rises on Space and comes down on Shift+Space -- the
same two keys that take a person up and down in the world
(`interaction.js` BINDINGS) -- in a little world kept open on the server
(`workshop_drive`, `/api/workshop/drive`) and stepped as the keys arrive,
an eighth of a second at a time, every frame drawn here as it happens.
The keys are put to the thing's program as the asks a panel makes in the
world -- going forward, backing off, turning left, turning right, waiting,
and now **rising** and **descending** (`LiveWorld::behave`) -- so the
rover and the drone drive the same way; a machine with wheels and no
program is driven by its wheels' own controls, the same operate its panel
sends. Going up or down wins while its key is held, because it is the
deliberate one. Let go (or Esc), and the drive is a take beside the clean
thing, with its picture and how far it went.

**Rising and descending** are the hover program's, and the engine refuses
them to anything else ("only a machine that flies can be asked to be
rising or descending"). They move the height it HOLDS, 0.8 m/s, a little
under the 1 m/s its climb is limited to, so the machine keeps up with the
target and letting go leaves it hovering where it got to, the way a flown
machine answers a stick; held all the way down it sets itself on the
ground. Measured (`tests/drone_hover_tests.cpp`): asked to rise for three
seconds, 1.51 m up became 3.65 m, and let go it held between 3.65 and
3.95 m; asked to descend for four, it came back to 0.99 m and not through
the floor.

**The bench opens on what was open last**, not on the table every time: a
URL's `kind` wins, then whatever was last open in this browser, then the
table. It is kept in the browser alone, and a remembered thing that has
since gone -- a library item thrown away, a template renamed -- opens the
table without a word rather than an error. A saved design is remembered by
its kind, not by its revision. The little world takes the robot templates now (rover,
drone, processor: they install as exact bodies through the same gate).
Measured (`tests/workshop_drive_tests.py`): the rover, W held for two
seconds, went 2.2 m; A held, it turned; keys up, it held; and the drone,
W held, lifted and went forward. One drive at a time to a server.

- **Inventory**: the material rack, editable (oak, iron, glass, stocked on
  the bench), the goods rack (copper, copper wire: what machines put on a
  stockpile marked as the Workshop's rack), the products made and standing
  in the world and the designs saved on the bench -- each with a way into
  the Lab -- the personal library, and every component family a design is
  built from with its parameters.
- **Recipes**: for every template the bench can make, what it takes -- its
  parts and families, its materials by mass against the rack, the goods its
  machines take -- whether the rack covers it, and what it can do (drives
  itself, flies, digs and carries, hauls, works a recipe, sees water,
  charges from the sun); "Design it" opens it in the Lab. Beside them, the
  recipes the open room knows, which machine works each, and what is in the
  ground.
- **Skills**: achievements. Every technique the world has, known or not:
  known ones ticked, the next ones "within reach", the rest with what they
  need; what each opens; what has been demonstrated with how much evidence;
  what is blocked and why; and the regimes the engine said it does not
  model. It reads the person's notebook (`docs/knowledge-and-progression.md`)
  and awards nothing itself.

### Adding solar

Measured 2026-09-26, after the owner tried it: "adding solar did not seem to
work". The bench chat's `add_power_part` wrote a panel into the design's
record and nothing else -- no plate, nothing in the viewer, nothing in the
components list -- and a panel with no store came back refused as "a panel's
store needs a name of 1 to 120 characters", which says nothing about what
to do. Three framework changes:

- A power part is checked against the parts that are there, and what is
  missing is said in words that name the fix: "A panel charges a battery,
  and this design has none. Add one first -- add_power_part {kind: store,
  ...} -- and then the panel"; "a panel's `on` names 'roof', and there is no
  part called that; the parts are ..."; "which store does the panel charge?
  Say store: one of ...". The model reads the refusal and calls again; a
  person reads it and knows.
- A panel is a thing: adding one puts a square glass plate of its area on
  top of the part it sits on, fixed to it, as the rover template's is, so it
  shows in the viewer and the components list and weighs what glass weighs.
  With one store in the design the panel is wired to it unasked.
- The tool's description says the order: store before panel or motor.

So the answer to "should it have worked?" is no: the record was taken but
nothing was made of it. Checked by `tests/workshop_tabs_tests.py`.

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

## Inventory resources and Recipes sources — September 30, 2026

**Implemented:** Inventory now contains products in the authenticated guest's hands/bag, available raw material quantities, processed goods, and compact energy meter cards. Saved designs, reusable parts and all 16 starting blocks live in Recipes. Saved recipes retain supply bars, Make and Open in Lab together; mirrored library records are deduplicated. Source selection remains explicit, preserving Lab selection across screens/reload and leaving carried inventory unchanged. The empty Lab offers both Inventory and Recipes destinations. This supersedes the earlier placement of design catalogs in Inventory.

**Energy meaning:** Spendable joules come from the authenticated guest's Market wallet. Shared solar charge is the native solar-farm store meter; solar generation sums native panel `power_w` readings (watts = joules per second). World machine cards show program count and summed nonnegative motor power draw. These are shared world readings, not privately owned machines. Currency collection remains manual through Market banking, so automatic wallet and machine currency income are 0 J/s. Robot goods throughput is **Not metered**, not an invented rate. Generation is an instantaneous reported value, not a forecast or a full energy ledger. Meter cards refresh every five seconds while Inventory is visible; read failures show Unavailable rather than zero. Existing context/poses APIs are used without opening, stepping or drawing energy.

**Verification:** Windows 11 / Python 3.13 / Chrome / native Release integration binaries; source base `c6fbe0a` plus this checkpoint. All 55 Workshop browser tests, 7 screen-navigation tests and 4 opening-goal tests pass (66 total). JavaScript syntax, Python compilation, source registration (286 sources), changed-document link targets and diff whitespace checks pass. Screen tests exercise all 16 blocks, saved-part copying, saved-design selection/reload, two independent Camp stool builds and stock-race refusal. The new energy browser journey compares a 200 J personal balance, solar store and positive native solar rate, checks a five-second refresh leaves simulation time/machine state/balance unchanged with the test world clock disabled, and confirms a second guest sees their own 0 J balance. Native law, storage schema and ownership rules are unchanged. Shared plus personal rack availability is not a private physical bag; legacy world-folder Saved designs retain their existing visibility boundary.

**Next:** persistent machine ownership and measured robot goods flow histories before showing private robot income; real resource sales/automatic banking rules before showing passive currency earnings; live-provider prompt-to-functional-design trials remain unqualified.


## Material cards and recipe filters — September 30, 2026

**Implemented:** Raw-material and processed-goods cards are ordinary clickable buttons. Pictures, names and larger quantities on their own line replace the small overlapping corner badges. Material/goods quantities consistently use kilograms with locale formatting, up to three decimal places (six below 0.001 kg), without changing stored mass. Text selection is disabled inside cards; visible keyboard focus is retained. Selecting a material opens Recipes with `material=` in the URL. Material chips and **All materials** switch/clear the filter without making requests or spending stock. Matching build recipes and saved recipes retain ordinary readiness, supply, Make and Lab controls. Saved designs beyond the recipe summary list match their fetched source-part materials. Starting blocks/parts/world processes are hidden while filtered; clearing restores the catalog. A no-match view still offers All materials. Catalog shortcuts clear the filter, and guided Recipes destinations clear unrelated material filters so the target cannot disappear.

**Verification:** Windows Chrome/native Release integration, source base `c2364f2` plus this checkpoint. Eight screen-navigation tests, four opening-goal tests and four focused Workshop inventory/recipe browser checks pass (16 total). JavaScript syntax, Python compilation, source-registration (286 sources), local document link targets and whitespace checks pass. The material journey clicks the real Oak card, checks the declared-material match and saved-design inclusion, reloads, switches to Glass, clears/reloads, recovers from a no-match URL and verifies unchanged materials/goods/carry records and empty Lab. Quantity styling and selection behavior are checked. Existing native screen journeys retain all 16 draft sources, saved-part copying, separate Make copies, refusal feedback and private wallet readings. This is UI navigation/filtering only; matching a material does not establish affordability, build admission, learned skills or functional performance. Those remain the existing recipe fields and native checks. No backend, storage, native physics law or conservation evidence changed.
