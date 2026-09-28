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

## 2a. Why there is already a mine here

The owner, 2026-09-28: *"We land at this spot to find an abandoned mine site. So
there are already mine shafts and tunnels and some structures on the surface.
This would allow us to immediately experience what is possible, even though we
have to start from the bottom of the tech tree to build up."*

That is the best argument for all of this, and it costs nothing extra, because
**the workings are made of the same ground everything else is**. Somebody found
the vein where it broke surface and followed it: an open cut while the ore was
within reach of the top, a shaft at the high end when it got too deep to throw
spoil out of, an adit mouth notched into the hillside below to come in
underneath, and the spoil in heaps where it was thrown.

It teaches the tech tree without a word of tutorial, because the ground says what
stopped them: **the cut runs out where the ore stops being oxidised and soft and
turns fresh and hard.** You arrive, you can see the whole shape of what mining is
-- follow the vein, take the cover off, sink a shaft, drive in from below -- and
you cannot do any of it yet, for exactly the reason they could not carry on.

Built, 2026-09-28: the cut, the shaft, the mouth, the heaps, and `mine` in the
terrain block saying where each piece is. NOT built: the underground (the mouth
stops at a notch until stage 3 gives it a void), and the surface structures --
a headframe over the shaft, a ruined hut, old timbers -- which are bodies a
scene stands up at the places the terrain block reports.

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
5. **Go in.** The vein dips under the hill, so you follow it in. Nothing hands you
   a tunnel shape: the hole is whatever the tool has broken (§4.9), and a machine
   opens one it can fit through and then keeps the section it is in. Through fresh
   rock that is a machine's job, not a person's (§7) — you set a breaker on the
   face, and go and do something else, because the world keeps running while you
   are in the Workshop.
6. **Hold the roof up.** As the hole you have cut gets near what the roof can
   span, the page puts up the ghosts of what it needs: *rock 0.4 m thick under 6 m
   of ground holds 2.6 m; this chamber is 5 m across, so props no more than 2.6 m
   apart — 3 of them. You have 2 oak posts on the rack. You are short 1.* Place
   them and they hold because they are there; get it wrong and the roof comes
   down, as real bodies, on whatever is underneath — including you.
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
- `volumes()` stops being a sweep. Totalling every run of every column to get the
  ground by kind is 0.09 ms against today's 0.016 ms (§9, spike 2) — the one
  regression either spike found. It becomes a running total the edits keep, the
  way the ledger already keeps what is dug and deposited, and `residual()` stays
  the identity it is.

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

**A column with a void needs THREE surfaces, not two** — the first draft of this
plan got that wrong and the spike (§9) caught it before any of it was built:

    y=5   ----------------****----------------   (a) the hill you walk on,
                           ||                        with a HOLE at the shaft
    y=2   --------++++++++++  ++++++++++-------   (c) the tunnel's ceiling
                  |                      |
    y=1   --------++++++++++++++++++++++++-----   (b) the tunnel's floor

So the collider, per chunk:

- **(a) the surface patch** is the one that exists, unchanged — the terrain's own
  top, which is still what you walk on when you are on the hill above a tunnel.
  Where a void reaches the sky its columns become holes in it (a non-finite
  height already means a hole), so you can fall down a shaft.
- **(b) the floor patch** is an ordinary height field at the void's bottom, with
  `cNoCollisionValue` everywhere there is no void. It is what you stand on inside.
- **(c) the ceiling patch** is the same shape turned upside down so its surface
  faces down: a static body rotated half a turn about X, with the rows reversed
  to match and `cNoCollisionValue` outside the void.
- **The walls** are already there: a 2 m step between adjacent floor columns is a
  steep triangle, the same way a pit's wall is today.

A chunk with no voids has one patch, exactly as now. A chunk with a void has
three, and with K void levels 1 + 2K.

`JoltWorld` gains `addVoidPatches` / `replaceVoidPatches` beside `addGroundPatch`
/ `replaceGroundPatch`, and nothing else changes: the rebuild, the wake
(`wakeBodiesIn`) and the marking all work on chunks as they do now.

**Measured, in Jolt, before committing to it** (§9): all of it holds, including
the shape swap on the turned body. The mesh-patch fallback is not needed.

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

**What "it lands on you" can mean.** The owner asked for a collapse that can hurt
you (§10), and there is a catch worth saying before anything is built: **the person
is a point of view and not a body** (`world.js`: "The person is a point of view and
not a body"). There is nothing for a falling block to collide with. The water work
already solved the same problem the honest way — the person is *taken* to hang
1.6 m below the eye, never below the ground, and how much of that is under water
decides how they wade, swim or are carried off. A roof should use the same
stand-in: a falling body whose path crosses that volume is measured against it, and
what follows is stated in physical terms — knocked down, pinned under what fell,
what you were carrying spilled on the floor, and you dig yourself out with the
spade you already have. No health, no death, no damage number: the engine has no
such notion and this plan does not add one. If you want the person to be a real
body that a rock can actually strike, that is its own project and a large one —
say so and I will scope it separately.

**Failing.** The failing span's roof voxels leave the ground. Big and coherent:
through the existing `cut` path, as a falling body — which can crush a prop, a
machine, or you. Thin: as rubble deposited on the void's floor, no body at all.
Either way the ledger closes and the bodies underneath are woken, both of which
already happen for a boulder dug out from under.

**The warning.** Over 0.7 of its tensile strength a roof reports `groaning`: the
page says so, dust falls. Derived from the same number, not a scripted tell. This
is the fairness knob, and the only one.

**The ghosts** — the thing you asked for. There is no ghost of the tunnel (§4.9:
the tool decides that). What is ghosted is the **support plan for the hole as it
stands**: as the span you have cut comes within reach of `L_crit`, the page puts
up the ghosts of the props the rule demands at their computed spacing, in the
green / amber / red ghost look the page already has (`GHOST_LOOK`). Under them, the rack's own
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

### 4.9 There is no standard tunnel: the section is what has to fit through it

The owner's decision (§10): no declared heading size. The void is whatever the
tool has broken, cube by cube, and the section emerges from the work. That removes
a made-up number and replaces it with two physical rules and one rule of thumb:

- **A machine cuts a section it can fit through.** Starting a fresh face, its
  breaker opens the smallest opening that clears its own body plus its clearance
  — which is a measurement of the machine, not a setting. A rover wants roughly
  its own width and height; a drone wants its rotor circle. Too small and it
  cannot follow its own heading, and the physics says so by stopping it.
- **A machine driving on keeps the section it is in.** The heading's profile is
  read off the void already there and continued, so a tunnel has a shape because
  the first few metres gave it one. Nothing declares it.
- **A person cuts what they can reach and swing at**, which is what the pick's
  own reach already decides.

Three consequences to build for:

- **The estimate is per cube and per metre, not per heading** (§7). The page can
  honestly say "your breaker takes about 9 minutes a cube in this rock, and the
  face you have cut is 16 cubes a metre — about 2½ hours a metre", and let you
  make it narrower if you do not like the answer. The narrowing is yours, not the
  design's.
- **The support ghosts follow what you actually cut** (§4.6), which is how the
  roof rule already works: it measures the real span. So props appear as the hole
  you are cutting approaches `L_crit`, and widening a heading is what summons
  them. This is better than checking a declared section against a rule — you can
  see the rule arrive.
- **Nothing offers you a shape.** There is no "drive a 1 m heading" button. There
  is a face, a tool, and a roof that is or is not holding. The plan the ghosts
  draw is the *support* plan, never the tunnel's.

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

**Half of this is done, 2026-09-27 — the half you can see.** What a column is
made of now goes over the wire as runs (`TerrainField::runsOf`,
`Environment::runsPacked`, `runs_b64` and `floor_m` in the terrain block and in
every changed rectangle), a survey says the column in words, the page draws the
face of every step in the materials the step cuts through, and its panel says
what is under your feet all the way down. Measured: the five checks in
`tests/terrain_runs_tests.py`, and in the real valley 10,780 bands in four
materials, with a pit dug to rock photographed by `tests/ground_faces_shots.py`.
Nothing else moved: `world_room` 57, `api_docs` 12, `terrain_tests` 11/11,
`water_tests` 19/19, `ground_work_tests` all, and **60 s of the valley in 4.638 s
of wall clock, 0.0773x realtime**, against the 0.078x this plan set out from.

**And the other half, the same day.** The rock under a column is now a stack of
**beds** -- CSR, held the way the engine walks it -- and the earth goes down
**30 m** instead of 2. A column with three beds keeps all three through a cut, a
save and a restore; a bed is worth what it is MADE of in the ledger, so a lens of
sand in the rock is counted as sand; and a cut that would reach a bed that is not
rock is refused with the reason rather than counted as rock. Ground state is
schema v4, and a room saved before it gets the deeper earth with the new rock put
into its opening figure, so its own account still closes. Measured: a new
`a column keeps its beds` check in `terrain_tests` (12/12) and
`tests/deep_earth_tests.py` (a 3 m block, which the 2 m earth refused, comes out
exactly its own volume and the ledger closes), with `valley_live` 11/11,
`water_tests` 19/19, `environment_ffi` 15, `world_room` 57, `ground_work_mcp` 24.

**Two things this deliberately did NOT do, against the plan as written.** The
runs did not replace the soil, sand and loose layers: the loose layer is a
MIXTURE of sand and loose soil, not two layers in an order, and a run holds one
material -- so rewriting it as runs would have changed the spoil physics and the
measured slump numbers for no gain, when what stage 2 needs (beds, veins, ore) all
live in the rock. And `Volumes` was not widened to a kind each: it is read in a
hundred places and has nothing new to count yet, so instead a bed adds to the kind
it is made of, and a cut into a bed that is not rock is refused until it does.

**And it turned out not to be stage 2's first job after all.** Stage 2 put clay
and ore in the ground and `Volumes` still did not need widening: a bed adds to
the bucket its matter belongs to (rock, weathered rock and ore are all the
ground's stone; clay is soil-like), the ledger closes, and what a vein is WORTH
is the goods account's business, not the ground's. The reason to widen it is the
mass of what comes out from under a tool, which arrives with stage 4's rock law.
That is where it belongs: where getting a density right decides something.

Runs in `TerrainField`, three legacy layers as three runs, `Volumes` by kind with
the total kept by the edits rather than swept (§9), faces drawn, the survey in
words, the earth made 30 m deep. No new materials, no new physics.

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

**Half of this is done, 2026-09-28: the ground has geology in it.** A mantle of
weathered rock over the rock, a bed of clay dipping along the valley under it,
and a vein of ore through both at its own strike and dip, oxidised where the
weather reached it. The page draws the top of a column in what the column is
MADE of rather than in one of three surface kinds, so the vein shows as a rust
stain on the knoll's bare rock and you can walk up to it; the panel says the
whole column -- "1.2 m of weathered rock, then 7.3 m of rock, then 70 cm of
clay, then rock". Measured (`the valley has geology in it`, terrain_tests
13/13): 19,476 columns have the clay bed, 1,963 the vein, 28 show it at
daylight, no column holds more than 8 runs, and the clay lies a metre lower at
the valley's east end than its west -- so a bed found in one place says where it
is in another. `kGeneratorVersion` is 4 and the beds are cached with the
landscape. One thing fell out of it worth keeping: the valley's cut-block test
used to look for bare level rock and now has to look for rock that is rock ALL
THE WAY DOWN, because a block of clay or ore is refused.

**Not built, and still stage 2's:** deposits reading the ground (a vein's
reserve is still the room's declared number, not what is in the rock), test pits
and the prospecting panel, the oxidised cap being softer to work than fresh ore
(nothing can work rock at all until stage 4), placer in the river, and gravel
lenses.

**Measured:** generation still under 3 s and cached bit for bit; the vein's mass
in the ground equals what the room's deposit used to declare; nothing in the
running cost moves.

### Stage 3 — a hole you can walk into

Void runs, the roof patch (or the mesh fallback), void cubes drawn, and the
"which floor am I on" work through the page and the senses. Ground state as the
room's authority.

**You can see:** a tunnel declared into the hillside in a test room, walked into,
looked out of; a rover driven in and out; the room reopened and it is still there.

**Started, 2026-09-28: the ground can hold a hole, and the old adit is one.**
`RunKind::Void` is a bed of nothing -- rock under it, rock over it -- with one
invariant that keeps everything else untouched: **a column's topmost bed is never
a void**, because a hole open to the sky is a hole in the surface, which a height
field already says. So `height()`, `rockTop()`, the soil on top and everything
that reads them are exactly as they were, and a void is always something with
rock over it. `JoltWorld::addRoofPatch` is the spike's arrangement made real: the
same height field on a static body turned half a turn about X, mostly holes,
built and swapped like any other patch. A chunk with a working gets two more
patches, its floor and its roof; a chunk without gets none.

The generator drives the old adit in as a real tunnel where there is hill over
it, and leaves it a notch where there is not: 75 columns of the valley are a
working 1.75 m from floor to roof with up to 1.4 m of hill above. Measured, in
the live world on the generated valley (`the adit is a hole with rock over it`,
valley_live 12/12): a pebble put in it rests at 2.05 m, its floor plus its
radius, and not on the world's floor; fired up at 8 m/s it reaches 3.68 m and
stops under the roof at 3.75, where free flight would have carried it to 5.33.

**And the other half, the same day: you can see it and stand in it.** The page
draws a working from the inside off the runs it already receives -- its floor,
the roof over it, and a wall wherever the rock beside it is solid -- and
`standingOn(x, z, y)` gives whoever is there the top of the highest SOLID run at
or below them, which on open ground is the ground and inside a working is its
floor. Asking the height field alone, which only knows the hill, is what used to
shove anyone who went in back out on top of it. Measured: the page builds 75
columns of working into its mesh (1,752 triangles with the faces), and a person
put inside at y = 3.60 m stays at 3.60 -- floor 2.00, roof 3.75, and the hill
5.13 over their head -- where before they would have been lifted to 5.13.

**Not built:** it is DARK in there, because a tunnel is, and nothing in the room
carries a light yet; the walls are drawn as the cell-stepped shapes they are;
and machines and their senses have not been told about workings at all, so a
rover would still drive over the top of one.

**Measured:** the collider rebuild for a void chunk against the budget; bodies
woken by a void appearing; a person and a machine stand on the floor of the
tunnel and not on the hill above it; reopen is bit-identical.

### Stage 4 — break the rock

rock-work-v1: specific energy, per-voxel damage, rubble with bulking, the hardness
gate as it is. The pick works a face. A machine's breaker tool.

**You can see:** swing an iron pick at an exposed vein and watch the face recede
cube by cube, the worked cube shading as it goes, ore and rubble arriving in the
Carried list; set a rover's breaker on a face and come back to a metre of tunnel
the width the rover needed to get down it (§4.9), with no section declared
anywhere.

**Measured:** the work the solver measured against the model's own, the way the
ground bite is measured today (within one step's travel); ground plus carried plus
exported closes to 1e-9; the rate, stated plainly in m³ per hour per kilowatt, for
each material.

### Stage 5 — it can fall on you

roof-span-v1, supports measured from the rigid world, pillars, groaning, collapse
as a body or as rubble, and the ghosts with the rack's shortfall sentence.

**You can see:** a 5 m chamber in rock under the weak bed comes down when you mine
the last pillar out; the same chamber with three props holds; pull one prop and it
comes down on the others; widen a heading until the prop ghosts appear and watch
the rule arrive; a roof that falls on a rover crushes it, as a falling body does;
and one that falls on the person knocks them down, spills what they carry and pins
them until they dig out — through the 1.6 m stand-in the water already uses, not a
new body.

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
  gets through about 2.4 m³ an hour, so a metre of advance costs an hour for
  every square metre of face. That is slow to watch and perfectly fine to *run*,
  because the world keeps running when nobody is looking at it
  (`playground/world_clock.py`) and never faster than the wall clock. You set it
  going and you go and build something. The energy it spends is the real
  constraint, and it lands squarely on the battery and solar work that already
  exists.
- The page says the rate before you commit, from what the tool has actually been
  measured delivering: *"about 9 minutes a cube in this rock; the face you have
  cut is 16 cubes a metre"*. An honest number against the hole you chose to cut,
  and then the player's decision.

The three ways to make it faster, in order of how honest they are: **cut less
rock** — the section is yours (§4.9), and a face half as wide is half the hours;
more power, which is the game; and drill-and-blast, which is how rock is really
moved and would be a genuinely fun later project — a charge breaks cubic metres
because it loads the rock in tension. Blasting is out of this plan.

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

## 8a. A stale cache, and a wrong conclusion drawn from it

Worth writing down, because it cost an hour and I told the owner something false
along the way.

A generated valley is cached by a key of its parameters and `kGeneratorVersion`.
**Change what generation does without bumping that version and every cache on the
machine hands back the old world** -- and there are several, in several places:
`banjo-terrain-cache` and `banjo-terrain-test-cache` under the system temp, one
per test suite (`banjo-valley-live-test-cache`), and whatever `BANJO_TERRAIN_CACHE`
points at.

What happened: the first version of the workings cut the riverbank, and the
valley's own acceptance test noticed -- the oak log that drifts 0.234 m/s down the
river dropped to 0.137. I gave the workings a standoff from the channel, and the
number did not move. I then built with the whole mine pass switched OFF, and the
number STILL did not move, to fifteen digits, and concluded the mine was innocent
and the regression had come in from main. I said so.

It had not. Every one of those runs was reading the same cached valley, made by
the first version, because the version had not changed. With it bumped and the
world regenerated the log drifts 0.554 m/s and valley_live is 12 of 12. The mine
had slowed the river; the standoff had fixed it; and the experiment that was
supposed to settle it was measuring a file.

The lesson is not "clear the cache". It is that **an experiment which cannot
distinguish the two cases is not evidence**, however decisive the number looks: a
result identical to fifteen digits across a change that large should have been
read as "nothing I did reached this code", not as "the change has no effect".

## 9. The two spikes, run 2026-09-27

Both were measurements, not features, and neither is engine progress: they are two
standalone programs in a scratch directory, compiled against the Jolt the checkout
has already built. They were run to find out whether the two load-bearing
assumptions in this plan are true before anyone starts on it.

### Spike 1: a tunnel out of Jolt height fields — it holds

`roof_spike.cpp`: a 32 x 32 chunk at the terrain's own 0.25 m, built through a
copy of `JoltWorld::groundShape` so it measures the real thing. A hill at y = 5
with a 1 m square hole in it, a chamber floor at y = 1, and a ceiling at y = 2 on
a static body turned half a turn about X. Five checks, at 1/240 s:

| | measured |
|---|---|
| a ball dropped down the shaft | falls through the hole in the hill, past the ceiling level, and rests at **y = 1.1000** — the chamber floor plus its radius |
| a ball fired up at the ceiling from inside, 8 m/s | stopped at **y = 1.9000**, the ceiling less its radius; free flight would have reached 4.46 m. **The upside-down height field collides from below.** |
| a ball dropped on the hill, clear of the void | rests at **y = 5.1000**: the surface patch still works with holes in it |
| a ball fired up off the hill outside the void | reaches **8.4453 m** against 8.46 in free flight: nothing invisible overhead where the ceiling is `cNoCollisionValue` |
| the ceiling swapped for one 0.4 m lower, between steps | `SetShape` on the turned body took it, and the next ball stopped at **y = 1.5008** |

The first run failed two of the five, both because the spike had put two balls in
the same column and they met in mid-air. Fixed, all five hold.

**What it settles.** Stage 3 needs no new collider machinery and no mesh
fallback: a void is three height patches, built and swapped exactly as the ground
already is. It also found the error in §4.5 — three surfaces per column, not two.

### Spike 2: walking the runs costs nothing that matters

`runs_walk_spike.cpp`: the valley's own 19,500 columns, held both ways — four
fixed doubles a column against CSR runs (5.44 runs a column fresh, 5.66 with a
tenth of the columns mined) — doing the same work in the four shapes the engine
actually reads the ground in. Per call, milliseconds:

| | four layers | runs | |
|---|---:|---:|---|
| a full height sweep (the page) | 0.0049 | 0.0076 | +55%, and 7.6 microseconds |
| a full volumes sweep (the ledger) | 0.0163 | 0.0922 | **+464%** |
| 100,000 random column lookups (every contact) | 0.3134 | 0.1073 | **3x faster** |
| a whole-field neighbour compare (relax's bound) | 0.0480 | 0.0260 | 1.8x faster |

Memory: 609 KB against 1,009 KB, 1.66x, for the whole valley.

**What it settles.** The indirection is not a problem, and the hottest path — a
contact asking the ground what it is made of — gets *faster*, because four
separate arrays cost four cache lines a column where the runs cost two. Against
the valley's own budget (4.68 s of wall clock over 14,400 steps is 0.325 ms a
step) every figure here is noise.

**The one real finding, and what came of it:** totalling the ground by kind by
sweeping every run is 0.09 ms, six times what it costs today, and I concluded that
`volumes()` should stop being a sweep and become a running total kept by the
edits. **That was wrong, and building it showed why:** `residual()` is the check
that the swept total still matches the ledger, so a running total would compare a
number with itself and pass for ever. The sweep IS the test. It is asked four
times a second, which is 0.036% of a second, and it stays a sweep.

Neither spike touched the engine. The real cost figure is still 60 s of the valley
once stage 1 lands, against the 0.078x baseline.

## 10. What the owner decided, 2026-09-27

1. **How blocky: smooth ground, blocky holes.** Geology keeps its real shapes;
   the hole you cut is 0.25 m cubes. As §2 has it, and every settling and
   conservation test that passes today still holds.
2. **How big is a heading: let the tool decide.** No standard section. §4.9 is
   what that means, and it turned out to be the more physical answer: a section
   is whatever has to pass through it.
3. **A collapse lands on you.** A fallen roof is a real body and crushes props and
   machines outright; the roof groans at 0.7 of its strength first, and that
   warning is the only fairness in it. For the *person* it has to go through the
   1.6 m stand-in the water already uses, because the person is not a body —
   knocked down, pinned, carrying nothing until they dig out. §4.6 says why, and
   what the alternative would cost.

Still open, and only a detail: **where the first vein goes.** My recommendation is
the knoll, with its oxidised cap outcropping on the valley side, so the first mine
is an adit of two or three metres that a person can open by hand and a rover can
drive into.

## 11. What it takes to make this a core part of the world

Asked for on 2026-09-28, after the abandoned mine landed. What exists now is a
place you arrive at, read and walk into. What it is NOT yet is something the
world runs on. This is everything between those two, in the order the
dependencies actually fall, with what each one unblocks and what "done" means.

The four marked **LOAD-BEARING** are the ones without which none of the rest is
worth building. Everything else is real work, but it is work on a thing that
already functions.

### 1. LOAD-BEARING — a pick can break rock (stage 4)

**Today nothing in the engine can take rock out of the ground.** `dig` strips
loose material and soil and stops on rock, by declaration; `cut` takes a block
of bare rock and hands it over as a body. `docs/ground-work.md` says outright
that breaking rock out under a point "has no law here". So the mine is a museum:
you can look at what somebody else did and you cannot do any of it.

- rock-work-v1: specific energy `e_s = k_c H` under a point, the work measured
  from the solver's own impulses as the ground bite already is.
- Per-voxel damage accumulating on the working face only, so a face recedes cube
  by cube and the page can shade the cube being worked.
- Rubble with a bulking factor: what comes out does not fit back in the hole.
- The hardness gate unchanged: an oak point on fresh rock still stops.

**Done when** a person with an iron pick can stand at the old face and take the
oxidised ore out of it, and the same pick on fresh rock is refused for the
reason the engine already gives.

**The law is built, 2026-09-28; joining it to a tool is not.** rock-work-v1:
`e_s = k_c H`, with `H` the material's own indentation hardness (the number the
cutting model already gates on) and `k_c` declared at 0.3 from the rock-cutting
literature, where the specific energy of efficient cutting runs at a fraction of
the unconfined strength. `judgeGround` no longer answers "breaking rock out of
the ground under a point has no law here": a point harder than the rock now
answers **Breakable**, and says what a cubic metre costs. Measured
(`ground_work_tests`): fresh rock 30 MJ/m3 and the oxidised cap of a vein
1.5 MJ/m3, so a 0.25 m cube is **4,688 hand blows of 100 J in the rock and 234
in the cap** -- two and a half hours against eight minutes, which is exactly the
ramp 7 describes and the reason the old workings stop where the cap does.

**And joined, the same day.** The join turned out to have a clean shape rather
than a fudge: breaking a cubic metre costs `e_s`, so pushing a point of
cross-section A through it costs `e_s A` newtons -- which is a RESISTANCE, and
drops straight into the ground bite the soil already uses. So a point in rock it
can break is held by what breaking costs, and the work is measured from the
solver's own impulses exactly as it is in soil. Nothing is a rate and nothing is
declared twice.

What the blow buys, `W / e_s`, goes into the ground as a CHIP
(`TerrainField::chip`): a volume smaller than a cell is not a hole, it is
progress towards one, kept column by column, and a whole cell of rock leaves
through `breakOut` on the blow that pays for it. Only the face being worked is
ever in that map.

Measured, end to end: an iron stake dropped on bare rock does **20.836 J** of
work by the solver's own account, which at 30 MJ/m3 is **0.000695 of a 0.25 m
cell** -- and the ground keeps it. `rock comes out a chip at a time`
(terrain_tests 15/15) pays for a cell in eleven bites and checks that nothing
leaves on the first ten, that exactly one cell leaves on the eleventh, that the
rock comes down by exactly one cell, and that the ledger closes.

### 2. LOAD-BEARING — the ground can be dug into a void at runtime

Voids exist, but **only the generator can make one**. Mining has to turn solid
into hole while the world is running, which means the edit path, not the
generation path:

- `TerrainField::breakOut` (or the same through `dig`): solid to `RunKind::Void`,
  cell-quantised, splitting a bed into three, with the spare slots already there.
- The collider follows: the surface patch, the floor patch and the roof patch of
  the changed chunk rebuilt and swapped between steps, exactly as a dig rebuilds
  one today, and whatever they held up woken.
- The ledger: what leaves is counted, and `volumes()` still closes.
- A column's topmost bed is still never a void, so breaking through to daylight
  turns the working into a pit rather than leaving an overhang.

**Done when** a heading driven by hand or by machine is a hole in the ground the
next step, and the room reopened an hour later still has it.

### 3. LOAD-BEARING — machines know a working is there

`survey` answers `ground_m` with `heightAt`, which is the hill. A rover sent to a
point over the adit is told the ground is 5.1 m up while the floor under it is at
2.0. `standingOn` exists only in the page, in JavaScript.

- The same rule in the engine: the top of the highest solid run at or below a
  given height, used by `survey`, by placement, by the aiming ray and by
  anything that asks where the ground is.
- The senses: a working in `look`, so a machine can be sent into one and can
  tell it is in one.
- Routines and `go_to`: a way in and a way out, and the getting-nowhere sense
  taught that a roof is not sky.

**Done when** the mine rover drives into the adit, works the face, and comes out
with a load, unattended.

### 4. LOAD-BEARING — you can see underground

The first photograph taken inside the adit was a black rectangle, which is
correct and useless. A tunnel is dark.

- A light that is a thing, not a rendering trick: a lamp the Workshop can make,
  carried or set down, with fuel or a battery, throwing light the page draws.
- It belongs to the crafting chain rather than beside it: the reason to make one
  is that you cannot work what you cannot see.

**Done when** a person carries a lamp into the adit and can work at the face.

### 5. The mine is dangerous (stage 5)

Nothing holds a roof up today, and nothing falls. This is where props, ghosts and
the rack shortfall come in -- and it is the whole reason to build anything.

- roof-span-v1 on a frontier, asked only where a void or a support changed.
- Supports measured from the rigid world, never counted.
- Collapse as a real body or as rubble, conserving; the groaning warning.
- The support ghosts and the rack's "you are short one oak post".
- What a falling roof does to a person, through the 1.6 m stand-in the water
  work uses, because the person is not a body.

### 6. The mine pays (stage 7, and stage 2's leftovers)

- Deposits read the ground: a vein's reserve is what is in the rock, not a
  declared number in the room's `goods` block.
- Ore out of a face becomes a goods packet of its substance at its grade.
- `Volumes` widened to a kind each, which is finally needed here: the mass of
  what comes out from under a tool decides what it is worth carrying.
- A breaker tool for machines, drawing its work from the battery, so the energy
  economy is what limits mining.
- Timber props as Workshop products, which is the loop closing: you mine to
  build, and you build to mine deeper.

### 7. Prospecting is a thing you do (stage 2's leftovers)

- Test pits and a hand auger: one column, read in words.
- The oxidised cap softer to work than fresh ore, which is the difficulty ramp
  the geology is already shaped for.
- Placer in the river, so panning points upstream.
- Gravel lenses, which stage 6 needs as the flooding hazard.

### 8. Water underground (stage 6)

- A water table per column, generated.
- Saturated ground: buoyant weight in the slope and roof checks, and the quick
  condition for a sand face.
- Darcy inflow into a working below the table; a pool at one level in a
  connected void; drainage by a lower adit.
- The wet law for tools, which `judgeGround` currently refuses outright.

### 9. It looks like a place

- The surface structures the mine site needs -- a headframe over the shaft, a
  ruined hut, old timbers -- which need a way for a scene to anchor bodies to
  generated features. The terrain block's `mine` already says where they go.
- Wall and roof geometry better than the cell-stepped shapes drawn now.
- The site dressed: rails, a barrow, a broken ladder in the shaft.

### 10. It holds up

- Persistence: a room with workings kept through both paths the playground has --
  the saved world (which carries beds, schema v4) and the replayed edit list
  (which cannot express a void, and has a 400-edit cap). One of them has to
  become the authority.
- Determinism and conservation tests for void edits, the way every other edit
  has them.
- The realtime budget with a mine being actively worked: collider churn on three
  patches a chunk, the roof frontier, and the page's mesh rebuild.
- More than one void level per column, if a heading ever has to cross another.

### The order I would build them

1, 2 and 4 together are the smallest thing that makes the mine real rather than
a ruin: a light, a pick that bites rock, and a hole that grows. 3 makes it a
place the world's machines share. 5 is what makes it a game rather than a
sandbox. 6 is the reward. 7, 8 and 9 deepen it. 10 is the tax on all of it and
should be paid as each lands rather than at the end.
