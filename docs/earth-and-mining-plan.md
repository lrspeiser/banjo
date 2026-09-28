# The earth, and mining it: a plan

A plan, not a report. Nothing here is built. It says what the ground should be
made of, what a person and a machine do to it, what each piece costs, and in
what order it can be built so that every stage ends with something to look at in
the playground.

Written against `main` at `b34c9dc`.

## 1. What the ground is now, and why you cannot read it

The ground is a **height field of columns** (`src/terrain/TerrainField.hpp`). Each
column is four numbers: where the rock stops, then soil, then sand, then loose
soil on top. One valley is 19,500 columns 0.25 m apart, 39 m by 31 m. It is not a
voxel model of anything: it is a surface with three layer thicknesses hung under
it.

Five consequences, all of them things you have hit:

1. **You cannot see what you are standing in.** The page draws one mesh, one
   colour per column, taken from the *top* material only (`GROUND_COLOURS` in
   `playground/world.js`, three colours). A pit's wall is drawn in the colour of
   the grass above it. There is nowhere for a vein to show.
2. **A vein is not in the ground at all.** It is a circle on the map with a mass
   in it: `{"name": "copper vein", "at_m": [x, z], "radius_m": 4, "grade": 0.3,
   "reserve_kg": 2000}` in the room's `goods` block. A scoop anywhere in the
   circle brings up ore at `grade` until `reserve_kg` runs out. Nothing about it
   is a place; digging deeper does not find more of it; it cannot outcrop, pinch
   out, or dip.
3. **A tunnel is geometrically impossible.** A height field has one surface per
   column. There is no representation for solid-over-void, so there is nothing to
   walk into, and `dig` can only ever take the top off.
4. **The earth is 2 m deep.** `floor_ = min(rock) - 2.0` and a cut is refused
   below `floor_ + 0.05`. There is no depth to mine into.
5. **Rock is a wall, by declaration.** `docs/ground-work.md`: a point in rock is
   `stopped` if it is softer than the rock and `not supported` if it is harder —
   "breaking rock out under a point has no law here". So mining, as physics, does
   not exist yet.

What *is* right, and must not be broken, is the accounting and the activity
model: every cubic metre is counted by kind, an edit marks the columns it touched
and only those are asked whether they still stand, only the chunks that changed
get new colliders, and the water only computes tiles that are wet. Digging one
corner of the valley asks 65 columns of 19,500 and rebuilds 1 collider of 20.
Everything below keeps that shape: **ask, do not sweep.**

## 2. The idea, in one page

**A column stops being three thicknesses and becomes a list of runs.**

    now:   rock_top=1.2   soil=0.5   sand=0.1   loose=0.0

    then:  [ granite      to  -18.0 ]      <- the runs of one column,
           [ copper ore   to   -2.4 ]         bottom to top, each with
           [ granite      to    0.9 ]         a material and a top
           [ shale        to    1.2 ]
           [ subsoil      to    1.7 ]
           [ topsoil      to    1.8 ]

A run is a material and the height it reaches. That is a **run-length-encoded
voxel earth**: the same information as one voxel per 0.25 m of depth, stored in
the six numbers the geology actually needs instead of eighty. A column that
happens to hold `granite / soil / sand` is exactly today's column, so today's
physics and today's tests are the special case.

Two rules make it read like blocks without pretending geology is cubic:

- **Solid runs keep continuous tops.** Soil surfaces are not cubic, slumping
  moves millimetres, a heap settles to 33.6 degrees, the water's bed is a real
  height. Quantising those would break the conservation and rest tests that
  already pass. Geology stays smooth.
- **Voids are cell-quantised in all three axes.** A hole you make is made of
  0.25 m cubes. So a tunnel is blocky, legible and Minecraft-shaped; its floor
  and roof land on exact multiples, which is what makes the collider and the
  drawing cheap; and there is a visible unit of progress — one cube — to work
  towards.

And one addition that does most of the work for the eye: **exposed vertical faces
are drawn, in the colours of the runs they cut through.** Today a step between
columns is drawn as a stretched flat triangle. Drawn as a face split at every run
boundary, the same pit suddenly shows topsoil over subsoil over rock, and a vein
shows as a band you can follow. No physics changes to get that.

## 3. What a person does — the loop this is for

1. **Walk and look.** A vein that reaches the surface shows as a stained outcrop:
   a patch of a different colour on the hillside. The river's sand carries a
   little of whatever it has eroded upstream, so a panned handful points you up
   the valley.
2. **Test.** Sink a test pit or drive a hand auger: one column, a metre or two
   down, and the panel tells you the column in words — *0 to 0.2 m topsoil, 0.2
   to 1.1 m subsoil, 1.1 to 1.5 m weathered granite, granite below, copper-
   bearing from 2.2 m*. Three pits tell you which way the vein runs.
3. **Open a face.** Dig the soil off the vein where it is shallowest — a spade
   job, which works today. Now you are looking at rock with a band of ore in it.
4. **Work the vein by hand.** The oxidised top of a vein is soft; a pick takes it
   a bite at a time and the face recedes cube by cube. You carry ore out in
   40 kg loads. This is the session-scale activity.
5. **Go in.** The vein dips under the hill. To follow it you need a heading — and
   a heading through fresh rock is a machine's job, not a person's (§7). You set
   a breaker machine to drive it and go do something else; the world keeps
   running while you are in the Workshop.
6. **Hold the roof up.** Before it will offer a heading, the page shows you the
   ghosts of what the roof needs: *granite 0.4 m thick under 6 m of ground holds
   2.6 m; this chamber is 5 m across, so props no more than 2.6 m apart — 3 of
   them. You have 2 oak posts on the rack. You are short 1.* Place them and they
   hold because they are there; get it wrong and the roof comes down, as real
   bodies, on whatever is underneath.
7. **Keep it dry.** Below the water table the ground is saturated: the walls
   stand less well, and a gravel lens floods the heading in minutes. Drive above
   the table, or drive a drain lower down and let it run out.
8. **Take it home.** Ore is already goods: the rover hauls it, the smelter smelts
   it, the wire lands on the Workshop's rack. That chain works today; this plan
   puts a real hole in the ground at the front of it.

Everything in that list is a consequence of a declared model plus what the solver
measures. Nothing in it is a scripted event or a number tuned to feel nice.

## 4. The model, part by part

### 4.1 The column becomes runs

`TerrainField` holds three flat arrays instead of four:

    col_start : uint32[cells + 1]       where each column's runs begin
    run_top   : double[]                the top of each run, bottom-up
    run_kind  : uint8[]                 which ground material it is

CSR, so a column's runs are contiguous and the whole field is three contiguous
blocks: cache-friendly to walk, bit-exact to save and restore, trivial to
base64. About 6 runs a column in fresh ground, 1 MB for the valley; a mined
column adds at most 2 more per void level.

Kept exactly as they are:

- `height(c)`, `rockTop(c)`, `soil(c)`, `sand(c)`, `looseSoil(c)`, `surface(c)`
  — computed from the runs, so every caller, every test and the whole C API keep
  working. `rockTop` becomes "the top of the topmost run that is rock-like".
- `relax()`, the Mohr-Coulomb / Terzaghi / Pouliquen stability check. It reads
  the material on top of a column, which is now the top run's. Slumping moves
  material between the top runs of neighbours. No change to the physics.
- `dig`, `deposit`, `cut` and the ledger's `initial - dug - cut + deposited`.

Changed:

- `Volumes{rock, soil, sand}` becomes `double by_kind[kGroundKinds]` with
  `rock_m3()`, `soil_m3()`, `sand_m3()` kept as sums over the kinds that are
  rock-like, soil-like and sand-like. Every JSON field that exists today keeps
  its name and meaning; a `by_kind` object is added beside it. **This is the
  widest edit in the plan** — `Volumes` reaches `EditReport`, `Ledger`,
  `carried`, `withdrawCarried`, the C API, the MCP, the page's Carried list —
  and it is worth doing properly once. ABI 15 to 16.
- `floor_` stops being `min(rock) - 2.0` and becomes a declared depth (30 m
  below the lowest rock, say) so there is something to mine into. The initial
  rock volume in the ledger changes with it, so the conservation tests get new
  numbers — expected, and each one is still an identity.

The ground materials table (`GroundMaterial`) grows from three to about ten:
topsoil, subsoil, sand, gravel, clay, weathered rock, rock, and one entry per ore
that a vein can be made of, plus `Void`. Each carries what it already carries — a
density, a friction angle, a cohesion, a rolling resistance — and three new
declared numbers: an **indentation hardness** (for §4.4, from the same place the
cutting model gets one), a **tensile strength** (for §4.6), and a **hydraulic
conductivity** (for §4.7). Ore also carries its substance name and its grade.

Where a number exists in the engine already it is taken from there, not invented.
Rock is the concrete preset, which `MaterialCatalog` already gives as 2400 kg/m³,
E 30 GPa, **tensile 3.0 MPa**, compressive 35 MPa, **hardness 100 MPa** — so both
new numbers the roof rule and the rock law need are already declared and sourced,
and the worked examples below are the engine's own. (One caveat: strengths reach
fracture through `break_strain_multiplier`, and that calibration is finished for
glass and not for ceramic. Stone's should be checked before the roof rule leans on
it.)

### 4.2 Strata and veins: putting them there

One new pass in `TerrainGenerator`, after erosion and before the river spins up,
so it costs generation time once and is cached (`kGeneratorVersion` bumped, which
retires every cached valley):

- **Beds.** A stack of sedimentary beds with a dip — a plane, a strike and a dip
  angle of a few degrees, each bed a thickness with fractal variation. Sampled
  down each column into runs. Because the beds cut across the topography, a
  hillside shows them as bands, and a bed you find at one place tells you where
  it is at another. That is the whole of prospecting geometry and it is one
  plane equation.
- **A weak bed.** One of them is clay or shale: low tensile strength. Mining
  under it is where a roof falls in (§4.6). Bad ground is a real thing and it is
  where the drama lives.
- **Veins.** Tabular bodies: a plane with a strike, a dip, a thickness, an
  extent and a noise envelope so it pinches and swells; plus lenses for placer
  and gravel bodies. Each carries a substance and a grade. Sampled into runs
  where they cut the column.
- **An oxidised cap.** The top 1–3 m of a vein is weathered: same substance, much
  lower hardness. This is real, and it is the difficulty ramp — the cap can be
  worked by hand, the fresh ore below it cannot (§7).
- **Outcrops.** Where a vein comes within 0.3 m of the surface the surface run
  becomes a stained variant with its own colour. That is the thing you spot from
  across the valley.
- **Placer in the river.** The erosion pass already moves sediment without making
  or losing any; where it erodes a vein it can carry that substance into the sand
  it lays down. Panning then points upstream. Cheap, optional, and lovely.

Determinism: all of it from the seed, all of it in the cache key.

Compatibility: a room that declares a circle deposit in `goods` gets ore voxels
generated from the circle when the world opens, so `tests-mine` keeps working —
and its vein becomes something you can see and stand in.

### 4.3 Seeing it

Three changes in the page, no physics:

1. **Faces.** Where adjacent columns differ in height by more than a threshold,
   emit a vertical quad strip split at every run boundary that crosses the step,
   each piece in its run's colour. Fresh valleys are smooth and emit almost
   nothing; a mine emits a few thousand quads, which is nothing for three.js.
   The face is drawn on the same diagonal split the collider uses, as the top
   surface already is, so what you see is what you stand on.
2. **Void cubes.** Void runs are cell-quantised, so a tunnel is drawn as the
   exposed faces of cubes — floor, roof and walls, each in the colour of the
   material it is cut from. A tunnel reads as carved rock.
3. **Words.** `surveyJson` gains the column as a list of runs, and the page's
   panel says it in plain English — *"under your feet: 0.2 m of topsoil, 0.9 m of
   subsoil, then weathered granite; copper-bearing from 2.2 to 2.6 m"*. The same
   text is what a machine's `survey` sense reads, so a decider knows what its
   own hole is in.

On the wire: the runs go in a `runs_b64` block beside today's `heights_b64` and
`ground_b64` — per column a count then (kind, top) pairs. Sent whole once when the
world opens (~350 KB for the valley, and it compresses) and afterwards only for
the rectangle that changed, exactly as `terrain_changed` already works. If the
open cost matters, the page only needs runs where a face is exposed, so the
engine can send runs for those columns and a single surface kind for the rest.

### 4.4 Breaking rock: the law that is missing

`docs/ground-work.md` says outright that there is no law for breaking rock out
under a point. This adds one, in the same style as the rest — a declared
reduced-order model, closed form, sourced, with the work **measured** from the
solver's own impulses.

**rock-work-v1.** Rock is broken by specific energy: `e_s = k_c · H`, where `H` is
the material's indentation hardness (already in the engine) and `k_c` is declared
from the rock-cutting literature, where the specific energy of efficient cutting
runs at a fraction of the unconfined strength. A blow that the solver measures as
delivering `W` joules into the point breaks `V = W / e_s` of rock.

- The broken volume accumulates **per voxel**, in a small map of part-broken
  voxels (only the working face is ever in it, so it is tens of entries, not
  millions). When a voxel's accumulated volume reaches its own, the voxel becomes
  `Void` and the face has receded one cube. The page shades the voxel being
  worked by its damage fraction, so you can see progress.
- What comes out is **rubble**: loose material of that voxel's kind, at a declared
  bulking factor — broken rock takes up 1.5 to 1.7 times the space it did intact.
  So the spoil from a tunnel does not fit back into it, which is true and is a
  real constraint on where you put it.
- Ore voxels yield their substance at their grade and the host rock as rubble,
  both through the paths that exist: the substance as a goods packet
  (`machine_goods`), the rubble as carried ground.
- The hardness gate stays exactly as it is. An oak point on granite still
  `stopped`s. An iron point on the oxidised cap works. An iron point on fresh
  granite works, slowly (§7). The tool's own dents and breaks are the lattice's,
  as now.

### 4.5 Voids: the hole, and what holds it up to the solver

A void is a run like any other, cell-quantised. **One void level per column to
start** — solid below, void, solid above (or open sky). Two levels later if a
tunnel ever needs to cross over another; the storage already allows it, the
collider and the drawing are what limit it.

The collider, per chunk:

- **The floor patch** is the one that exists: the top of the topmost solid run
  *below* the void, which is the surface you walk on. Where there is no void it is
  today's ground exactly.
- **The roof patch** is new: the underside of the solid run above the void, as a
  height field turned upside down — the same `HeightFieldShape`, the same
  compression, the same build-and-swap between steps, on a static body rotated
  half a turn about X (with the rows reversed to match), and
  `cNoCollisionValue` everywhere there is no void. A chunk with no voids has no
  roof patch at all.
- **The walls** are already there: a 2 m step between adjacent floor columns is a
  steep triangle, the same way a pit's wall is today.

`JoltWorld` gains `addRoofPatch` / `replaceRoofPatch` beside `addGroundPatch` /
`replaceGroundPatch`, and nothing else changes: the rebuild, the wake
(`wakeBodiesIn`), and the marking all work on chunks as they do now.

**The risk, and the fallback.** Whether Jolt is happy with an inverted height
field on a rotated static body is the one thing in this plan I would not promise
without trying it, and it is half a day to find out (§9). If it is not, the
fallback is a replaceable static mesh patch per void chunk: `addTriangleSupport`
already builds a `MeshShape` from triangles, so the work is generalising it from
"the one support surface" to "a patch you can swap", and the surface itself comes
from the void cubes' exposed faces — which the page is building anyway.

**Being in a hole** is the part that touches the most code outside the engine.
The page and the senses ask for "the ground at x, z" in a dozen places and get
the top of the column; inside a tunnel the answer has to be the floor you are
standing on. That means the eye height, the reach, the placement rays, the
ghost's resting height, a machine's `survey`, and the getting-nowhere sense.
`docs/reach-from-the-camera` and the placement rules have been wrong about
heights before; this is where that bites again, so it gets its own stage and its
own visual test.

### 4.6 The roof, the props, and the ghosts

**roof-span-v1, declared.** A roof over a void is a beam of the solid run above
it, held at both ends. For a span `L`, a roof thickness `t`, and everything above
pressing down with `p`:

    sigma = (rho g t + p) L^2 / (2 t^2)          fails when sigma > sigma_t
    L_crit = t sqrt( 2 sigma_t / (rho g t + p) )

`p` is the weight of the runs above, per unit area, which the runs make a two-line
sum. `sigma_t` is the roof material's tensile strength. Three regimes fall out of
the one formula, and they are the right three:

| the roof is | at the engine's own numbers (rock: 2400 kg/m³, sigma_t 3 MPa) |
|---|---|
| 3 m of rock over a shallow adit | holds about 27 m. A shallow adit in rock needs nothing, and that is correct. |
| 0.5 m of rock under 10 m of ground | holds 2.5 m. Props. |
| 0.5 m of rock under 20 m of ground | holds 1.8 m. More props. |
| the weak bed above you | its tensile strength is a fraction of rock's, so the span is a fraction of these. |
| soil | `sigma_t` is nothing, so `L_crit` is nothing. **You cannot tunnel in soil without supporting it, ever** — which is exactly true, and is why soil headings need timbering and lagging. |

**Supports are measured, not declared.** The span is not "how many braces did you
place": it is the largest unsupported gap across the void's footprint, measured to
its walls, its pillars, and **whatever is actually standing against the roof** — a
cheap query of bodies whose top is within a few millimetres of the roof over that
chunk. A prop works because it is there. And the load it takes is a real contact
force, so a prop too weak for its tributary load is broken by the engine's own
material response, with no extra law: it breaks, the span doubles, and then the
roof goes. Nothing about that chain is scripted.

**Pillars.** A solid column left standing inside a void's footprint is a support,
so the formula already rewards room-and-pillar mining. The pillar's own vertical
stress — tributary load over its area — against the rock's compressive strength is
one more line, and it says what it should: at our depths pillars do not crush
unless you mine nearly everything away.

**Asked, not assumed.** Roofs enter a frontier exactly as unstable slope faces do:
a void whose footprint changed, or whose supports moved or broke, is asked on the
next pass. A quiet mine costs nothing. This is the same machinery as `relax()` and
should live next to it.

**Failing.** The failing span's roof voxels leave the ground. Big and coherent:
through the existing `cut` path, as a falling body — which can crush a prop, a
machine, or you. Thin: as rubble deposited on the void's floor, no body at all.
Either way the ledger closes and the bodies underneath are woken, both of which
already happen for a boulder dug out from under.

**The warning.** Over 0.7 of its tensile strength a roof reports `groaning`: the
page says so, dust falls. Derived from the same number, not a scripted tell. This
is the fairness knob, and the only one.

**The ghosts** — the thing you asked for. At a face, "drive a heading" shows the
ghost of the next section (say 1 m × 1 m × 1 m of void) *and* the ghosts of the
supports the rule demands at their computed spacing, using the green / amber / red
ghost look the page already has (`GHOST_LOOK`). Under them, the rack's own
shortfall sentence, which also already exists: *"It takes 3 oak posts and 1 cap.
You are short 1 oak post."* The count comes from `L_crit`, and the panel says
where it came from, in the same breath. The ghosts are advice; the physics is
still what holds the roof up. Place them badly and the span rule measures the real
gaps and is unimpressed.

### 4.7 Water: the table, the pool, and running sand

Yes — the material changes, and the change is the water table.

- **A water table per column**, generated: tied to the river's surface and
  smoothed up under the topography (a Dupuit-style level, clamped below the
  ground). Cheap, and it makes the table follow the valley — high under the
  floodplain, deep under the knoll, which is what decides where you can mine dry.
- **Runs below the table are saturated.** Two effects, both closed forms already
  in the literature the terrain quotes:
  - **It holds less.** Use the buoyant unit weight below the table in the slope
    and roof checks. A wall that stands dry caves in wet.
  - **Sand runs.** A saturated cohesionless face with an outward seepage gradient
    at or above the critical gradient `i_c = gamma' / gamma_w` (about 1) is
    quick: it flows. The slumping machinery does the flowing; the criterion is
    one comparison. This is the classic boiling condition and it is the honest
    reason you do not open a sand face below the table.
- **Inflow is Darcy.** A void below the table takes `Q = k A i` from the faces
  that are in saturated ground, with `k` per material. The numbers are the whole
  design: intact rock `1e-8 m/s` — dry; sand `1e-4` — a slow seep; gravel `1e-2`
  — a 2 m heading floods in minutes. So **where you dig decides whether you
  flood**, and the generated gravel lenses are the hazard. No fudge factor.
- **Water in a hole is a pool, not a river.** The shallow-water solver is a
  surface solver on the column grid and has no business underground. A connected
  set of void columns is a pool with one level; inflow raises it; it drains
  through its lowest opening, which is why driving a lower adit dewaters your
  mine by gravity. Still water at one level is exactly right for a flooded
  working, and it is a fraction of the cost of Saint-Venant. Where a void is open
  to the sky, the pool and the surface water meet at the one level they share.
- **The wet law for tools.** `judgeGround` currently refuses ground under more
  than 5 mm of water as "no wet-soil law". With saturation in the runs there is
  one: the same bearing and passive formulas on the buoyant weight, with
  cohesion gone. That also makes dredging a lake bed possible, and makes its
  walls slump as they should.

### 4.8 Ore into the chain that exists

`machine_goods` keeps recipes and stockpiles exactly as they are. Deposits stop
being the authority on how much ore there is and become a **view of the ground**:
`reserve_kg` is what is still in the ore voxels. A declared circle becomes
generated voxels at open, so nothing that works today stops working.

The machines' side:

- The scoop stays a scoop: soil, sand and shallow ore, as now.
- A **breaker** is a new tool in `machine_tools`, the machine's version of the
  pick: it works a rock face by rock-work-v1, drawing its energy from the
  machine's store. `work_j_per_kg` stops being declared per machine and becomes
  what the rock costs, which is what makes the battery and the solar panels
  matter.
- "A spot is scooped once" — the rule that stopped the rover digging itself into a
  pit — becomes structural: a voxel taken is not there to take again. The dig
  siting fix stays; the pathology it was patching stops existing.
- The accumulating quarry that eventually traps a machine (the honest end state in
  `docs/machine-world.md`) becomes a navigable thing instead: a void is somewhere
  to drive in and out of, and a step too tall to climb is a real obstacle the
  getting-nowhere sense can see.

## 5. What it costs, and what must not move

The baseline to hold, from `docs/terrain-and-water.md`: 60 s of the valley with
bodies in it takes **4.68 s of wall clock, 0.078x realtime**; the terrain and
water are 2.40 s of that; the worst collider rebuild 0.20 ms; the worst step
515 ms, and that was a fracture trial, not the ground.

The budget this plan is allowed:

| | budget |
|---|---|
| 60 s of the valley, nothing being mined | stays under **0.10x** (it is 0.078x) |
| 60 s with a machine driving a heading | under **0.20x** |
| the ground's own added work, per step, p95 | under **1 ms** |
| worst added step, excluding a fracture the engine asks for | under **5 ms** |
| open cost: runs onto the wire | under **50 ms** and under **500 KB** |
| generation, once, cached | under **3 s** (it is 1.11 s) |

Why that is achievable rather than hopeful: nothing here sweeps. `relax()` reads
one run per column asked. Roofs are only asked where a void or a support changed.
Roof patches exist only for chunks with voids. The part-broken voxel map holds the
working face. Darcy is computed on the faces of pools, and a pool is a handful of
columns. The runs cost memory (1 MB) and a little indirection, not time.

What must not regress, and is tested today, so every stage reruns it:

- a closed basin conserves water to 1e-14; a lake at rest stays at rest bit for
  bit; a dam raises the level upstream by what it should
- ground plus carried is the ground there was, to 1e-9; a world opened again from
  its edits is identical to the bit
- digging one corner asks 65 columns of 19,500 and rebuilds 1 collider of 20
- a pit in sand settles to 33.6183 degrees against a stable limit of 33.6187
- `tests/valley_live_tests.cpp`, `water_tests`, `terrain_tests`,
  `ground_work_tests`, `environment_ffi_tests`, `world_room_tests`, `goods_tests`

One thing does have to move: the initial rock volume, because the earth gets
deeper (§4.1). Those tests are identities, not magic numbers, and they get new
totals.

**Fracture stays out of the ground.** A 2 m cube of fallen roof at the bodies'
40 mm cell size is 125,000 cells against a 16,000 cap, and one break is ~309 ms. A
collapsed block is a rigid body at a coarse cell size; if it lands hard on rock
the existing impedance rule may ask for a trial on it, and that is the only way
the lattice ever sees the ground.

**Determinism.** Runs are walked in one order (column index, then run index from
the bottom); collapse candidates are sorted before any of them is acted on; the
part-broken map is keyed by (column, run index), never by a pointer or an
iteration order. The contact-order lesson applies here too.

**The 400-edit cap is a stage-3 blocker.** The room replays its digs as edits
(`MAX_GROUND_EDITS = 400` in `playground/server.py`) and already warns when it
overflows. A mine is thousands of bites. The way out exists: the saved world
already carries the whole ground state (`doc["ground"]` from
`Environment::groundStateJson`, restored through `Environment::fromScene`). Once a
room has voids, the **state is the authority** and the edit list is only a
fallback for rooms that have none. That has to land with stage 3, not after it.

## 6. The stages

Seven. Each is shippable on its own, each ends with something to look at in the
playground at a URL, each states what it measured. None of them is "done" until
the owner can see it in 3D.

### Stage 1 — see the ground you already have

Runs in `TerrainField`, three legacy layers as three runs, `Volumes` by kind,
faces drawn, the survey in words, the earth made 30 m deep. No new materials, no
new physics.

**You can see:** dig the same pit as today in the valley and its wall shows
topsoil over subsoil over rock instead of one flat colour; the panel tells you
the column in words.

**Measured:** every terrain, water, ledger and world_room test passes unchanged
except the rock totals; 60 s of the valley within 0.10x; the runs on the wire
under the budget.

### Stage 2 — strata and veins in the ground

The generation pass: beds with a dip, a weak bed, veins with strike and dip and an
oxidised cap, outcrops, gravel lenses. `kGeneratorVersion` bumped. Deposits read
the ground. Test pits and the prospecting panel.

**You can see:** walk the valley and spot a stained outcrop from across it; sink
three test pits and read the vein's dip off them; `tests-mine`'s copper vein is
now a body in the rock you can look at in the wall of a pit.

**Measured:** generation still under 3 s and cached bit for bit; the vein's mass
in the ground equals what the room's deposit used to declare; nothing in the
running cost moves.

### Stage 3 — a hole you can walk into

Void runs, the roof patch (or the mesh fallback), void cubes drawn, and the
"which floor am I on" work through the page and the senses. Ground state as the
room's authority.

**You can see:** a tunnel declared into the hillside in a test room, walked into,
looked out of; a rover driven in and out; the room reopened and it is still there.

**Measured:** the collider rebuild for a void chunk against the budget; bodies
woken by a void appearing; a person and a machine stand on the floor of the
tunnel and not on the hill above it; reopen is bit-identical.

### Stage 4 — break the rock

rock-work-v1: specific energy, per-voxel damage, rubble with bulking, the hardness
gate as it is. The pick works a face. A machine's breaker tool.

**You can see:** swing an iron pick at an exposed vein and watch the face recede
cube by cube, the worked cube shading as it goes, ore and rubble arriving in the
Carried list; set a rover's breaker on a heading and come back to a metre of
tunnel.

**Measured:** the work the solver measured against the model's own, the way the
ground bite is measured today (within one step's travel); ground plus carried plus
exported closes to 1e-9; the rate, stated plainly in m³ per hour per kilowatt, for
each material.

### Stage 5 — it can fall on you

roof-span-v1, supports measured from the rigid world, pillars, groaning, collapse
as a body or as rubble, and the ghosts with the rack's shortfall sentence.

**You can see:** a 5 m chamber in granite under the weak bed comes down when you
mine the last pillar out; the same chamber with three props holds; pull one prop
and it comes down on the others; a soil heading refuses to be offered without
timbering, and says why.

**Measured:** the collapse conserves; the frontier stays small (a quiet mine asks
nothing); the prop that fails is failed by the engine's own material response and
not by the roof rule; the same mine worked twice is the same to the bit.

### Stage 6 — water underground

The water table, saturated runs, buoyant weight in both stability checks, the
quick condition, Darcy inflow, pools, drainage by a lower adit, the wet law for
tools.

**You can see:** drive a heading into a gravel lens below the table and watch it
flood in minutes; drive the same heading two metres higher and stay dry; cut a
drain out of the flooded one and watch it empty; open a saturated sand face and
watch it run.

**Measured:** the water ledger still closes; a pool's level against the inflow
Darcy says; a dry mine costs nothing; the flooded-then-drained mine ends with the
water it should have.

### Stage 7 — the mine in the game

Ore and rubble through the goods chain, the breaker on the rover's routine, the
timber prop as a Workshop product, a starter vein sited where an adit of two or
three metres reaches it, the mine in the new-game seed.

**You can see:** a whole loop with nothing declared in it that is not physics —
find the outcrop, open the face, pick the cap by hand, build props on the bench,
set the rover to drive the heading, haul the ore, smelt it, and take the wire off
the rack.

**Measured:** twenty minutes of it unattended, with the machine never stuck and
the roof standing; realtime for the whole thing; the ledger closed end to end.

Stages 1 and 2 are worth doing whatever you decide about the rest: they cost no
physics and they fix the thing you actually complained about, which is not being
able to see what you are looking at.

## 7. The rate problem, said out loud

Rock is hard, and this is the one place where "physics real" and "fun" genuinely
pull against each other. The honest numbers, at the specific energies real
rock-cutting has:

- A hand pick delivers of order 100 J a blow (the engine has measured 16.5 J from
  a light swing of a 1.2 kg oak pick). Fresh granite at 30 MJ/m³ means a 0.25 m
  cube is hundreds of thousands of blows. **You cannot hand-mine hard rock. That
  is not a bug in the model; it is why nobody does it.**
- The oxidised cap of a vein is soft — a few MJ/m³ — so a cube of it is tens of
  kilojoules: minutes of work, and a 40 kg load of ore is a session. **By hand you
  work a vein, not a mountain**, and the geology of §4.2 is what makes that
  possible.
- A heading through fresh rock is a machine's job: at 30 MJ/m³ a 20 kW breaker
  advances a 1 m × 1 m heading about a metre an hour. That is slow to watch and
  perfectly fine to *run*, because the world keeps running when nobody is looking
  at it (`playground/world_clock.py`) and never faster than the wall clock. You
  set it going and you go and build something. The energy it spends is the real
  constraint, and it lands squarely on the battery and solar work that already
  exists.
- The page should say the estimate before you commit, from the measured rate:
  *"at what your breaker delivers, this heading is about 40 minutes"*. An honest
  number, and the player's decision.

The three ways to make it faster, in order of how honest they are: smaller
cross-sections (a 1 m × 1 m heading is enough for a person and a rover, and is a
quarter of the rock of a 2 m one); more power (which is the game); and drill-and-
blast, which is how rock is really moved and would be a genuinely fun later
project — a charge breaks cubic metres because it loads the rock in tension. It is
out of this plan.

## 8. What this plan deliberately does not do

- **Not a full 3D voxel earth.** Arbitrary overhangs, floating rock and caves
  that fold over themselves would need about 1.5 million voxels for this valley, a
  mesh collider per chunk, and a rewrite of the water's bed. The runs model buys
  strata, veins, tunnels, roof collapse and flooding for a few per cent of that,
  at one honest cost: a column holds a bounded number of void levels (one at
  first), so you cannot dig a spiral that crosses over itself. If that limit ever
  bites, raising it is a number, not a redesign.
- **No fracture of the ground by the lattice.** The cell caps forbid it (§5).
- **No Saint-Venant underground.** A flooded working is a pool at one level.
- **No blasting**, no wear on tools, no rate effects in the soil model, no
  calibration of any of this against a real site. Every new model says it is
  declared and names its sources, as `ground-work-v1` does.
- **No new numbers where the engine has one.** Hardness, tensile strength and
  density come from the material catalogue and the cutting model.

## 9. Two things to try before committing to the plan

Both are half a day, both are measurements and neither is a feature. Neither
should be reported as progress.

1. **The inverted roof collider.** One chunk, a hand-built void, a `HeightFieldShape`
   on a static body rotated half a turn about X with `cNoCollisionValue` outside
   the void, and a ball dropped in the tunnel: does it stay in, does the roof stop
   it going up, does `replaceGroundPatch`'s swap-in work on it. If Jolt refuses,
   the mesh-patch fallback is the plan and stage 3 costs a little more.
2. **The runs walk.** `TerrainField` with the three arrays, the valley loaded, and
   60 s stepped: does the indirection cost anything measurable against the 0.078x
   baseline. If it does, the fix is a fast path for the common case of one soil
   run over one rock run, which is most of any valley.

## 10. What I need you to decide

1. **How blocky?** My recommendation: geology continuous, voids in 0.25 m cubes
   (§2) — the ground stays exact, the hole you make is visibly made of blocks.
   The alternative is everything quantised, which looks more like Minecraft and
   breaks the settling and conservation tests that pass today.
2. **How big is a heading?** My recommendation: 1 m × 1 m as the standard, wide
   enough for a person and a rover, a quarter of the rock of a 2 m one. Chambers
   are what props are for.
3. **Can a collapse hurt you?** My recommendation: yes — a falling roof is a real
   body and it lands on whatever is under it, with the groaning warning as the
   only fairness. Saying it cannot would mean the props are decoration.
4. **Where does the first vein go?** My recommendation: in the knoll, with its
   oxidised cap outcropping on the valley side, so the first mine is an adit of
   two or three metres that a person can open by hand and a rover can drive into.
