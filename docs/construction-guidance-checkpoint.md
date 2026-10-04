# Construction requirements, starter foundations and proactive guidance

October 3, 2026. Based on fetched GitHub main
`410ac439faed8def6208c03d6f27a00e202ed284`. Verified implementation published to
GitHub main as `23e48727ce832c7d399483cc9cde2bc64300bcd6`. The construction goal is active
and unfinished. The earlier readable-world wrap and separately paused R3 do
not close or pause this new goal.

## Implemented scope

- [Construction contract](../mcp/workshop_placement.py) derives supports,
  support bounds, authored connections and machine input/output declarations
  from actual designs. Bounded `@placement` overrides declare clearance,
  upright requirements, ports and skills. They cannot grant stock, knowledge,
  positions, anchors or strength. Lab candidates, Recipes, paid manufacture
  readiness and AI observations use this same adapter. Cosmetic preview IDs
  are excluded from requirements so identical geometry has identical gates.
- [Editable foundation pad](../mcp/workshop_products.py) has one platform and
  four independently sized footings, using the existing native rigid compiler.
  The catalog starts with a 0.4 m square, 0.05 m thick platform and 0.05 m
  footings: 24 kg of concrete by declared volume/density, within the initial
  shared 40 kg supply. Machine foundations override these dimensions using
  actual terrain bounds. Changing dimensions or material updates the paid
  quote; no stock is granted by editing a design.
- [New-world composition](../tools/build_new_world.py) places standing starter
  works on free concrete pads. Machine bodies remain free on their platforms.
  Expanded reservations include pad edges, pile access and haul corridors.
  Generated pad and machine source recipes are persisted as initial-world
  provenance and reopen in the Lab. They are not paid construction receipts or
  skill evidence. Existing saved worlds are not retroactively rebuilt.
- Recipes has a visible Construction section, including foundation pads,
  frames, shelters and bridges, with the existing thumbnails, supply bars and
  Lab/Make actions. Saved construction designs use the same category.
  Direct Workshop tabs open the saved native world before reading paid
  readiness, including after a server restart; loading still selects no Lab item.
- [Proactive guide](../playground/proactive_guidance.py) explains the current
  authenticated next action asynchronously. World and Workshop show that
  verified clickable action immediately. A completed model response adds one
  short tip, Hide tip and Quiet guide. Dismissal and enable preferences are
  private SQL records keyed by world/player and survive restart/navigation.
- At most two provider workers run per world, one pending request per player;
  new calls have a 20-second cooldown. Clock ticks alone do not invalidate
  advice. Changed next actions invalidate in-flight results, which are checked
  again when polled. The provider gets a copied observation, no live world
  reference or action tools, and holds no simulation lease. Six-second provider
  timeout/failure leaves the verified next action usable. Shutdown discards
  pending results. Measurements retain only the last 256 timing/usage outcomes.
  A selected project excludes the unrelated background goal from model input;
  this fixes the observed foundation tip incorrectly describing tool supplies.
- Routine proactive explanations use `gpt-5.6-luna`, reasoning `none`, a short
  structured response and a 160-token output budget. `BANJO_GUIDANCE_MODEL`
  provides a process-environment override. Account access was measured using
  the configured game key. [Official model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
  confirms the API model and supported reasoning setting. Existing design chat
  retains its configured model and existing thinking/output behavior.

## Measured Windows evidence

Windows 11, Python 3.13, Visual Studio 2022 x64/MSVC 19.44.35228, CPU Release,
existing `build/agent-column-terrain` binaries, Lab OFF. Native source, laws,
friction, drag, resolution, integration and binaries are unchanged.

### Native foundation comparison

[Construction tests](../tests/construction_tests.py) compare identical furnace
and pad geometry on terrain seed 4 at (10 m, 3 m), changing only pad material.
Smooth and 25 cm column terrain run 20 native seconds at dt = 1/240 s. Exact
rigid geometry is independent of the scene's 50 mm lattice. All eight cases
reopen with an identical native body table.

| Pad material | Native pad mass, kg | Smooth machine drift, mm / tilt, degrees | Column machine drift, mm / tilt, degrees |
| --- | ---: | ---: | ---: |
| Glass | 455.48714 | 1.460 / 0.370 | 0.880 / 0.066 |
| Oak | 127.53640 | 0.452 / 0.281 | 10.454 / 1.621 |
| Iron | 1433.87349 | 0.446 / 0.113 | 0.466 / 0.170 |
| Concrete | 437.26768 | 1.553 / 0.302 | 1.562 / 0.252 |

The proposed starter-site gates are horizontal drift < 0.15 m and pad/machine
tilt < 5 degrees after settling. These are gameplay acceptance bounds, not
changed native solver tolerances. Native mass minus declared volume × density
ranges from −6.9914e−5 to +1.2428e−5 kg, within the existing 2e−7 relative
material-mass comparison. Iron is denser and heavier; oak remains the existing
wood input and is not converted to a brittle preset. Constitutive stiffness,
grain, plasticity, soil bearing, concrete curing and attachment failure are
not established by these rigid contact experiments.

### Actual shared processing

[AI processing regression](../tests/ai_processing_tests.py) now succeeds on
both surfaces instead of expecting column failure. The authenticated reference
character stores and delivers 5 kg of private sand, chooses Melt Glass, pays
existing native heat/work, watches the actual batch and retains learned glass
evidence. Smooth takes 115.599 s wall time; columns 116.117 s, with retained
Store/load requests after lost replies, two restarts, one lot/delivery, peer
refusal and no physical port refusal. This is reference control, not a model
reasoning benchmark. The supplied sand is an explicit native extraction
fixture; this check does not establish unaided human gathering or locomotion.
An independently displaced-machine test retains the truthful port blocker.

### Guidance and retained source

[Proactive tests](../tests/proactive_guidance_tests.py) exercise slow provider
return/deduplication, stale response rejection, bounded concurrency, provider
failure, private dismissal/quiet preferences across manager and server
restart, and bounded read-only provider schema. A peer advances actual native
time while another player's model waits. On both terrain modes, saved source
foot dimensions match generated native parts; source recipes survive restart.
Human readiness and AI observation are compared using the same authenticated
player and live APIs.

Registered construction and proactive suites pass. Shared guidance/controller,
component/catalog/world-seed and design-chat regressions also pass; focused
processing verification records the actual stored-input/glass/light boundaries.
The source-registration guard reports 298/298 sources across 10 CMake files,
with zero deliberate omissions. New Python suites are registered with CTest.

Final registered retest: AI processing 4 checks in 235.37 s; stored-input,
glass and Camp light 3 checks in 83.69 s; construction 4 checks in 6.15 s;
proactive 6 checks in 9.98 s before the focused-project regression was added.
The final proactive/design-chat run passes 45 checks (7 proactive + 38 chat)
in 10.313 s. Shared guidance/controller 20, component/catalog/world-seed 42
and two non-browser recipe acquisition checks pass separately. Final AI
journey wall times are 115.142 s smooth and 115.832 s columns.

Six actual Luna calls use an authenticated fresh smooth-world observation.
Durations: 2.8085, 1.3952, 1.8165, 1.4181, 1.3773, 0.9331 seconds. Output is
29–30 tokens, input 688, no reasoning tokens. All six correctly point to the
observed oak pile/tool requirement. Nearest-rank sample p95 is **2.8085 s**;
the **2 s target is unmet**. Five responses fall below 2 s. This small local
sample is not production or multiplayer-load latency qualification.
After correcting project focus, two actual foundation tips take 1.4048 and
1.4588 s and correctly direct funding the selected pad; neither calls it a
tool. This additional two-case observation does not establish the p95 target.

The isolated 8779 browser shows the initial World tip next to the verified
action. Clicking Hide tip removes it, and it stays absent in Inventory after
navigation/reload. Recipes shows the Construction pad thumbnail, quantities,
Make and Open in Lab. This is agent-operated UI evidence; an unaided human
usability gate remains required. The running preview also reports a rover dry
route refusal; foundation qualification does not close broader R4 hauling.

Reports/screenshots are ignored local artifacts under `build/construction`,
`build/resource-flow` and `build/construction-preview`. No key or private token
belongs in this checkpoint or Git.

## Ground preparation and the two-second guide (2026-10-04)

**Preparing ground.** When nothing within reach will hold the item, the build
guide no longer just says "move or prepare the ground". It saves a patch in
front of the player, sized to the held item plus 10 cm all round, and reads
the ground's own cells under it (`construction_prepare.py`). Every cell
higher than the lowest by more than 2 cm is drawn on the ground in World:
amber for earth, red where rock is near the top. The guide says how many
squares, how deep at most and about how many litres, and that a shovel or
pick does it. A slope of more than 45 cm across the patch, water, or rock is
said plainly instead.

The marks are the terrain's own cells, so digging where one is drawn lowers
exactly the height that was read. An earlier version used squares turned to
face the player, and digging them missed the cells they had measured. The
patch is saved with the project, so it survives a reload. Every view reads
the ground again, which shows progress as the player digs. When the patch is
level the step is done, and the native placement trial still decides the
spot.

On a slope, digging down to the lowest square can be deep. When it would go
deeper than 15 cm and working to the patch's mean height is at least 30%
shallower, the guide marks amber squares to dig and blue squares to heap
that earth on (H heaps what you carry). Moving earth within the patch keeps
its mean, so what is dug is what is filled. The level is chosen once, when the
patch is marked, and saved, so earth carried off mid-job does not move it. The ground keeps its own books: the test digs earth from behind the
player to make a hump, because the engine refuses earth from nowhere.

**The guide answers in two seconds or not at all.** The proactive guide now
stops waiting at 2 s. The player keeps the verified next action, which is
already on screen. `tools/guide_latency.py` makes real calls the way the game
does:

| Run (30 calls each) | p50 | p95 | Longest | Within 2 s |
|---|---|---|---|---|
| Standard tier | 1.25 s | 1.53 s | 1.85 s | 30 |
| Priority tier | 0.83 s | 2.00 s | 10.0 s | 29 |
| As the game calls it | 1.12 s | 1.60 s | 1.81 s | 30 |
| As the game calls it, again | 1.30 s | 1.85 s | 2.01 s | 29 |

The priority tier was faster at the median, but one call hung for 10 s, so the
game stays on the standard tier. Sending a second request at 1.1 s fired on
almost every call and could not land before the deadline, so it is off. The
guide also now sees what preparation asks (which squares, which tool), but not
the depths: those change with every spadeful, and each change would have asked
for a new explanation. These are local measurements on one machine, not
multiplayer load.

## Fastening and the first construction skill (2026-10-04)

**Fastening.** A thing set down on a support only rests there. Once it is
placed on one, the build guide offers "Fasten to the (support)". That makes
a native fixing between the two (`construction_mount.py`), rated the way a
product's own bonded joint is: the weaker material's tensile and shear
strength over the area where the thing's foot meets the support's top. Joint
efficiency stays 1.0 by the owner's call of 2026-09-19. The fixing is a joint
in the room. It is saved with the room and comes back after a restart (tested
on the smelter, which really stands on its pad). When it is pulled or sheared
past its rating it breaks in the room, and the guide then says it came apart.
Unfasten removes it. The fastener itself (bolts, glue) is not modelled, and
the engine checks pull and shear only, not bending or twisting.

**Setting things down.** A new skill with no prerequisites. It is earned when
a player looks over a Camp light or Camp solar panel they placed with the
build guide, and the running room has it within 15 cm of where it was set
and within 10 degrees of upright: the guide's own Placed check and the stand
trial's tilt limit. Each placement is one evidence record, so looking again
adds nothing. A thing that moved or leans is recorded as not standing.

## Full construction goal: remaining work

1. Contract: declarations/readiness exist; enforce advanced skills and consume
   clearance/ports in the construction planner as those operations are built.
2. Sites: matched settling and two-surface furnace journey pass; qualify a wider
   terrain/resource seed matrix and generated native acceptance before admission.
3. Build mode: category and [Inventory → Place](construction-placement-checkpoint.md)
   now exist with one four-step placement card; expand to full construction steps.
4. Site suggestions: highlighted checked footprint, night label, blocker and
   another-site option now exist; qualify the wider terrain/site matrix.
5. Preparation: done (2026-10-04, below): dig down, or cut and fill a slope
   to its mean with the earth that was dug.
6. Proactive AI: next-action, placement and observed-placement tips work;
   add repeated-failure events and qualify the complete construction milestones.
7. Routing: the two-second guide target is met and measured (2026-10-04,
   below). Routing routine design edits apart from redesigns is still open.
8. Projects: prepare, hold, site, place, fasten and inspect are saved steps,
   each with where it is done; the current one is a link. Platform, access
   and operate steps are still to come.
9. Supports: pad exists; qualify posts/beams/braces/platforms and actual concrete
   production, supported/unsupported comparisons and removal behavior.
10. Connections: mounting is done (2026-10-04, below): a fastening is a
    native fixing rated by its contact, and it breaks in the room. Telling
    attached hoppers from separate piles is still open.
11. Customization: design editing and installation declarations exist; build
    bounded versioned proposals for slope fitting, recipes, appearance,
    machine behavior and goals through paid use/reopening.
12. Skills: "Setting things down" is earned from the engine (below). More
    construction techniques, such as building on a pad, are still to come.
13. Shared writes: private selection/site intent now has exact revision/retry
    receipts, peer privacy and restart checks; extend complete world mutation
    receipts to preparation/mounting, depletion, stale advice and lost replies.
14. Usability: conduct unaided human and AI ordinary-control construction runs;
    measure time, hesitation, wrong clicks and repeated refusals at each slice.

Next publish visual preparation/projects, then foundations/skills, then broader
customization. The full goal cannot be declared complete from this checkpoint.
