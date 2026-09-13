# Terrain and water

Ground and water built so that **physics decides what changes**, instead of the
engine re-simulating everything that exists. A landscape is generated once by
physics and saved; what it retains is cheap physical state -- columns of
material, static colliders, a water surface; and detailed physics runs only
around what is actively changing. Digging one hole does not activate the
mountain, and a river costs what its wet columns cost, not what the valley is.

Branch `worktree-agent-a835aa893d4ba61fb`, from `agent/integration` (`9275d61`),
with `main` (`821ecb0`, blades and cutting) merged in. Engine: `src/water/`
(library `banjo_water`: `ShallowWater`, `WaterCoupling`) and `src/terrain/`
(`banjo_terrain`: `TerrainField`, `TerrainGenerator`; `banjo_environment`:
`Environment`), with thin hooks in `LiveWorld` and `JoltWorld`.

## What changes, and what it costs

    generate once (drainage, erosion) -> save
    hold still: material columns + static height-field colliders, bodies asleep
    an edit -> mark -> recheck the columns it disturbed -> move what fails
            -> settle and stop -> rebuild the changed chunks' colliders
            -> wake only what those chunks held up
    water: only wet tiles and a one-tile ring are computed, on the water's own
           clock, in substeps its stability limit allows

The cost follows the amount of actively changing material and water. Measured
in the valley (19,500 columns, 20 colliders): a pit dug in one corner asked 65
columns whether they still stand, rebuilt **1 of 20** colliders in 0.05 ms and
woke **no** body; the rigid solver was stepping 4 bodies before and 4 after,
and the water computed **7,136 columns before and 7,136 after**. On a bare
128 x 160 grid, a puddle in one corner computes 256 of 20,480 columns.

## The ground

Every column is rock up to a height, native soil on the rock, and a loose
layer of sand or soil on top:

| material | density | friction angle | cohesion | behaviour |
|---|---|---|---|---|
| rock | 2400 kg/m3 | -- | 10 MPa | never slumps; a spade stops on it; blocks can be cut out of it |
| soil | 1600 kg/m3 | 30 deg | 2 kPa | holds a spade-deep wall |
| sand | 1600 kg/m3 | 32 deg | 0 | slumps to its angle of repose |

**Stability is asked, not assumed.** When the ground changes, only the columns
that changed and their neighbours are rechecked. A step between two columns
fails if it is taller than the material can hold: for a cohesionless layer,
the infinite-slope limit `dx tan(phi)`; for cohesive soil, Terzaghi's critical
height for an unsupported cut, `H_c = 2.67 (c / gamma) tan(45 deg + phi / 2)`.
What fails flows down at the rate a granular layer of that thickness can,
`~ sqrt(g h)`, until it is within Pouliquen's stopping layer (`h_stop` = 5 mm)
-- which is what makes a heap stop, and stop slightly steeper than its angle
of repose. Measured: a pit dug in sand settles to **33.6183 deg**, against the
model's own stable limit of 33.6187 deg (32 deg plus the stopping layer at
0.25 m columns); a 0.5 m trench in soil stands and a 1.6 m one caves in, 4.27
m3 slumping into it; rock does not move.

**The collider is the ground.** The field is cut into chunks of 31 x 31 cells
(32 x 32 heights, shared edges), each a static Jolt `HeightFieldShape`
compressed to within 2 mm. A changed chunk gets a new shape built and swapped
in between steps (`SetShape`) -- never the one the solver may be reading --
and `ActivateBodiesInAABox` wakes what it held. The triangles are split from
(i, j) to (i + 1, j + 1), in the collider and in the drawing, so what is drawn
is what things stand on. To the rigid solver the ground is soil: friction 0.7
static and 0.6 dynamic, rolling resistance 0.05.

**Impacts are judged against what the ground is there.** Whether a body could
break against the ground uses the contact impedance of the material at the
contact point: rock `sqrt(2400 x 30e9)`, soil and sand `sqrt(1600 x 0.05e9)`.
Before this, a concrete boulder dug under was judged as though it had landed
on concrete, shattered into 2,185 bodies, and the valley ran at 2.54x realtime.

**The ground has a ledger.** What crosses its boundary -- dug out, cut out,
heaped on -- is counted by material, slumping is counted apart, and the
residual is rounding: a dig heaped back leaves 6.3e-13 m3.

## Generating the valley

Once, and saved (keyed by the parameters and the generator's version, under
`BANJO_TERRAIN_CACHE`), never replayed while anyone is in it:

1. **Landform.** A valley floor falling 1.2% to the east between walls rising
   4 m, with fractal roughness, a rocky knoll (a mesa of bare rock) and a
   hollow on the floodplain.
2. **Drainage.** Priority-Flood (Barnes, Lehman and Mulla 2014), seeded at the
   river's mouth, so that every cell drains. Of 112 depressions found, one is
   kept as a pond -- at least 0.25 m deep, 3 m2 in area, and clear of the edge
   -- and 111 pits are filled (3.50 m3).
3. **The channel,** carved along the drainage route that the flow
   accumulation picks out: 64.1 m3, flat-bottomed.
4. **Erosion:** 300 passes of virtual-pipe hydraulic erosion (after Mei, Decaudin
   and Hu 2007): 0.90 m3 taken up and 0.80 m3 laid down. Soil is thinned where
   the ground is steep, so the valley walls show rock.
5. **The river, spun up** with the shallow-water solver itself to steady flow:
   145 s of river in 0.80 s, 0.35 m3/s in and 0.344 out, 29.34 m3 standing.

1.11 s from nothing; read back from the cache bit for bit.

## The water

The shallow-water (Saint-Venant) equations, first-order finite volume, on the
ground's own grid:

- **State:** the surface elevation and the discharge per column, over a bed
  that is the ground or whatever rests on it. Stored as the surface, not the
  depth, so that **a lake at rest stays at rest bit for bit**.
- **Fluxes:** hydrostatic reconstruction (Audusse et al. 2004) with a Rusanov
  flux, which balances the pressure against the bed slope exactly.
- **Wet and dry:** depths stay non-negative; thin films use a desingularised
  velocity (Kurganov and Petrova); a column under 1e-6 m is dry.
- **Stability:** every substep is inside Courant number 0.24 (the scheme stays
  positive up to 1/4 with four faces; measured worst 0.194); the water advances
  on a 1/60 s stride in as many substeps as that needs, and never more than
  1/30 s at once.
- **Friction:** Manning, n = 0.03, implicit -- it can stop the water, never
  reverse it.
- **Edges:** walls reflect; a river comes in at a prescribed discharge; a mouth
  is a free outfall, a broad-crested weir, `q = (2/3)^(3/2) sqrt(g) h^(3/2)`.
- **Cost:** tiles of 8 x 8 columns; only wet tiles and a one-tile ring round
  them are computed.
- **The ledger:** `volume - initial = inflow - outflow + numerical + residual`.
  A closed basin drifts 4.3e-14 m3 in 10 s (4.1e-15 of its volume); a river
  settles to passing 0.12 m3/s in and out with a residual of -2.6e-13 m3;
  `numerical` has been zero in every run.

## Bodies in the water: one accounting path

Each body's surface is split into patches -- a box's faces subdivided, a
sphere as a polyhedron of the same volume, a lattice piece's own cells. On
every patch the water presses `rho g (eta - y)`, clipped at the local surface.
**That is buoyancy**: nothing else is added, and it comes from density and
displaced volume alone. In flat water it is Archimedes exactly: oak (700
kg/m3) floats with 70% of itself under; iron (7870) is lifted 904 N against its
7,115 N; a ball displaces its own volume to 1e-9.

**Drag is relative motion.** On each patch, form drag (Cd 1.0) on the part of
the water's velocity relative to the patch that meets it face on, skin friction
(Cf 0.01) on the part that slides along it. Held still in a 1 m/s current, a
block takes 46.8 N (form drag alone 45 N). The reaction goes back into the
water, as momentum in the columns the patches were in: **one path** by which
momentum crosses, so the water slows what it pushes on.

The forces are pushed onto the body **inside** the step's reversible trial, so
a step taken back takes them with it; the water, the ground's settling and
its colliders are brought up to the world's clock only after the step is
accepted.

**A dam is whatever rests on the bed.** A body that is anchored, or denser than
water and resting on the bed, is to the water part of the bed: its top becomes
the bed of the columns under it (sealing a gap up to 0.1 m). A block across a
1.0 m / 0.2 m head carries exactly `1/2 rho g w (h1^2 - h2^2)` = 4,120.2 N and
no lift, because there is no water under it.

**Floating is judged over time.** A log bobbing in still water is held up by
anything from 0.75 to 1.3 times its weight as it passes through its waterline.
What the water held up against what a body weighs is averaged over accepted
steps with a 2 s time constant, and a body floats when the water carries at
least 95% of it. (An instantaneous test, which this replaced, called a
floating log "not floating" whenever it was on its way down.)

## Digging, heaping and cutting

A **dig** takes the ground down along a trench (or a pit) to a depth below the
ground as it stands: loose material first, then soil; a spade stops on rock.
The water over the dug columns keeps its volume -- digging makes none -- and
the dug material is the caller's to carry. A **heap** piles sand or soil round
a point and lets it settle. A **cut** takes a block of bare rock: a flat plane
a whole number of cells below the rock's mean top, so exactly the block's
volume leaves the ground; the block becomes an ordinary loose body in the
world opened next, and ground plus block are the rock there was.

Every edit marks the columns it changed; the recheck, the colliders and the
wake follow from the marks and from nothing else.

**Carrying the water across a reopen.** A world is opened from a scene, so
adding a body means opening it again. The water is carried: its depths,
discharges and ledger are saved (`banjo_environment_state`) and handed to the
new world as `"water": {"state": ...}`, where each column keeps its water over
whatever ground the new scene's edits leave. The reservoir behind a dam is
still there when a log is added. A new valley is new water.

## Measured

The owner's acceptance tests (`tests/valley_live_tests.cpp`, in a live world on
the generated valley, and `tests/water_tests.cpp`, the solver alone):

| test | measured |
|---|---|
| a closed basin conserves water | 10 s, 650 substeps: worst drift 4.3e-14 m3, 4.1e-15 of the volume; a closed basin in a live world with an oak log dropped in: drift 0 m3 |
| a lake at rest stays at rest | 551 wet and 1,369 dry columns, 400 substeps: every surface and discharge bit-identical; in a live world for 10 s, the largest change of surface 0 m and the fastest water 0 m/s |
| a dam raises the upstream level | 8 loose concrete blocks across the valley's river: 3 m upstream, 0.517 -> 0.721 m in 30 s, the blocks moving at most 12 mm; on the solver alone, 1.047 -> 1.2515 m |
| a new outlet drains it | a trench dug from the pond to the river (3.51 m3, 91 columns, 2 colliders rebuilt in 0.07 ms): the pond 0.858 -> 0.526 m in 30 s; on the solver alone, the dam taken out: 1.2515 -> 1.0478 m in 40 s |
| detached terrain is neither lost nor duplicated | a block cut (0.4 m3, 960 kg) and the world opened again with it as a body: ground 6,461.46 m3 + stone 0.4 m3 = 6,461.86 m3 against 6,461.86 m3 before |
| digging one corner does not activate the rest | 33 columns dug of 19,500: 65 asked whether they stand; 1 of 20 colliders rebuilt (0.05 ms); 0 bodies woken, 4 awake before and after; water columns computed 7,136 -> 7,136 |
| a boulder falls when dug under | woken by the dig (1 body), fell 0.30 m |
| a log floats and drifts | oak from x -12.8 to 2.5 m in 20 s (0.76 m/s), riding at y 0.421 m on a surface near 0.466 m; iron resting on the bed |
| water carried into a reopened world | 29.3647 m3 carried, 29.3647 m3 in the new world |
| realtime, worst step, active cells | see below |

## Realtime

Sixty seconds of the valley with bodies in it, stepped the way the room steps
it, took **4.68 s of wall clock: 0.078x realtime**. Of that, the terrain and
water took 2.40 s (the water's forces on the bodies 1.54 s, the water itself
0.80 s, the ground's settling 0.005 s) and everything else -- the rigid
solver, its reversible trial and the rest of the live world -- 1.76 s. The
water computed 8,160 of 19,500 columns (2,465 wet), its worst step 1.9 ms; the
worst collider rebuild 0.20 ms. **The worst step was 515 ms**, at t = 30.475 s:
not terrain or water but a lattice run working out whether the boulder dug out
from under, landing in its pit, breaks (it does not). The test asks for that
run synchronously; the room asks for it in the background.

## Where it is reachable

| layer | what |
|---|---|
| engine | `terrain::Environment`; `LiveWorld::environment / dig / deposit / cutBlock / setDischarge / environmentReport / environmentState / survey / awakeBodies` |
| C API (ABI 15) | `banjo_terrain_info`, `banjo_water_info`, `banjo_dig`, `banjo_deposit`, `banjo_cut_block`, `banjo_set_discharge`, `banjo_terrain_heights`, `banjo_water_surface`, `banjo_environment_report`, `banjo_environment_state`, `banjo_survey`, `banjo_awake_bodies` |
| Python | `World.terrain / water / dig / deposit / cut_block / set_discharge / terrain_heights / water_surface / environment_report / environment_state / survey / awake_bodies` |
| scene | `"terrain": {"generate": ..., "edits": [...]}`, `"water": {"discharge_m3_s" / "rivers", "state"}` |
| line protocol | ops `dig`, `deposit`, `cut_block`, `discharge`, `survey`, `environment`, `environment_state`, `terrain`; the ground whole when a world opens and afterwards only the rectangle that changed (`terrain_changed`); the water's surface and flow four times a world second |
| MCP | `make_terrain`, `survey`, `water_state`, `dig`, `fill` (only from what was dug), `cut_block`, `set_river`; `add_object` sets things on the ground and says if they are in water; every `run` carries a water summary |
| playground | the valley room, built by the chat from the MCP's tools; the ground and the water drawn from the engine's own heights and depths; **Dig here**; a water panel |

## Seeing it in 3D

Everything here is built by the playground's chat from the MCP's own tools;
only the valley itself -- the ground and its river -- comes from the
generation call. Start the playground against this build, with the library
the chat's tools load pointed at it too (ABI 15):

    set BANJO_LIBRARY=<checkout>\build\terrain\Release\banjo.dll
    python -u playground/server.py --port 8773 ^
        --engine <checkout>\build\terrain\Release\banjo_platform_cli.exe

and open http://127.0.0.1:8773/world.

1. **The river flowing.** Choose *A valley with a river* at the bottom right.
   You stand above the pond looking along the valley. The river runs west to
   east; the foam on it is carried by the engine's own velocity field. Aim at
   the water and the label says the depth and speed under the crosshair, and
   the Water panel says what is standing, coming in and going out, and how
   many columns the solver is computing.
2. **A dam backing water up.** Ask *"Dam the river with stone blocks so the
   water backs up behind them."* The chat sets nine concrete blocks across the
   river; the Water panel's outflow falls and the water standing behind the
   dam rises.
3. **A dug channel draining it.** Ask *"Dig a channel to drain the pond."*
   A trench runs north from the pond to the river, and the pond falls.
4. **A log floating and drifting.** Ask *"Put an oak log in the river."* It
   floats with about 70% of itself under and goes downstream with the
   current.
5. **A boulder falling when dug under.** Ask *"Put a big stone boulder on the
   river bank, where I can dig the ground out from under it."* Aim at the
   ground right beside it -- the label says *the ground* -- and press **Dig
   here**: the pit takes the ground from under it and it falls in.
6. **Digging.** **Dig here** anywhere on the ground digs a pit 0.8 m across
   and 0.4 m deep; sandy sides slump into it, and the pit is still there when
   the room is opened again.

Built in that order the room holds 12,960 of its 16,000 cells: the dam
10,368, the log 864, the boulder 1,728.

**Measured,** on 2026-09-12 on port 8773 in headless Chrome, the four
requests above typed into the room's own chat (the playground's configured
model, gpt-5-mini) and the room timed against the wall clock throughout:

| | the chat did | the room did | shown against the wall clock |
|---|---|---|---|
| idle | -- | the river flowing, foam carried on it | 20.72 s in 20.73 s |
| the dam | nine blocks 0.32 x 0.48 x 0.48 m across the river at x 0.64, in 34 s | 3 m upstream the river rose from 0.500 to 0.723 m in 41 s and was still rising; the outflow fell from 0.35 to 0.17 m3/s | 40.11 s in 40.16 s |
| the channel | the trench from the pond to the river, in 17 s | the room opened again with the dam's water carried into it; the pond fell from 0.846 to 0.514 m in 41 s | 40.15 s in 40.18 s |
| the log | oak, 0.96 x 0.24 x 0.24 m, in the river at x -13, in 12 s | afloat, from x -12.96 to -8.24 m in 20 s -- slowly, because the dam has backed the river up there | 19.49 s in 19.53 s |
| the boulder | concrete, 0.48 m, on the bank at [0.64, 1.04, 6.0], in 10 s | **Dig here** aimed at the ground 0.5 m beside it dug 0.23 m3 and rebuilt 1 collider; the boulder went down into the pit, y 1.016 -> 0.737 m, and 0.52 m sideways | -- |

The first time the dam was asked for, the chat was reading a guide that
still gave 0.96 m blocks: it placed four, ran out of the room's cells, and
said so rather than squeezing the rest in. The guide now gives the dam that
fits, and the second time it was built whole.

## Not modelled

- A floating body does not push water aside in the solver, so it radiates no
  waves and leaves no wake. Its bobbing is damped by drag alone: an oak log
  dropped into still water is still bobbing ±1 cm after 10 s, where a real one
  settles in a few seconds.
- The solver is first order: fronts are smeared (a dam-break front 3.4 m out
  after 1 s against Ritter's 4.4 m).
- No sediment moves while anyone is in the valley: erosion happens at
  generation only. No bank erosion, infiltration, evaporation or rain.
- The ground's stability is a column model: no rotational slips, no pore
  pressure; soil does not weaken when wet.
- No three-dimensional water: no spray, splashing or pouring. The surface
  drawn is the depth-averaged solver's; the foam on it is carried by the
  engine's velocity field and is a picture of it, nothing more.
- Dug material is a tally carried by whoever dug it, not a body.
- The in-process alternative to the live runner (`playground/live_inprocess.py`)
  has no terrain or water yet; the playground uses the runner.
- **Milestone 2 is not started:** the coarse river network (rivers as a graph
  of reaches beyond the detailed valley) and coarse-to-fine transitions.

## Milestones

| | status |
|---|---|
| 1. The valley | done: generated terrain with drainage and erosion, saved; material columns and static height-field colliders with chunked edits; a well-balanced wet/dry shallow-water solver on its own clock; a river fed at one end and draining at the other; a boulder that falls when dug under; a floating oak log; a dam of ordinary objects; all of it through the C API, the MCP and the playground's room |
| 2. The coarse river network and coarse-to-fine transitions | not started |

## Tests

| file | what |
|---|---|
| `tests/water_tests.cpp` | 13: the solver and the coupling on their own |
| `tests/terrain_tests.cpp` | 8: the ground, its stability model and the generator |
| `tests/valley_live_tests.cpp` | 10: the owner's acceptance tests in a live world, and the realtime rule |
| `tests/environment_ffi_tests.py` | 10: through the C library, from Python |
| `tests/banjo_mcp_tests.py` | a dam, a drained pond and a floating log through the MCP server's own protocol |
| `tests/agent_build_tests.py` | cases and `--recipes` for `dam-river`, `drain-pond`, `log-river` and `boulder-dug` |
