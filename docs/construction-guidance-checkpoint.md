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

## Full construction goal: remaining work

1. Contract: declarations/readiness exist; enforce advanced skills and consume
   clearance/ports in the construction planner as those operations are built.
2. Sites: matched settling and two-surface furnace journey pass; qualify a wider
   terrain/resource seed matrix and generated native acceptance before admission.
3. Build mode: category exists; add Inventory → Place and one construction step
   card around the existing ghost preview.
4. Site suggestions: add one highlighted valid footprint, night visibility,
   short blocker reason and another-site option.
5. Preparation: highlight required ground cells and use ordinary paid tools,
   collected mass and native rechecks.
6. Proactive AI: next-action changes work; add placement, repeated-failure and
   construction milestone events and validate actual advice in those situations.
7. Routing: measure/tune latency and route routine design edits separately from
   complex redesigns. Provider stalls are isolated; p95 target remains open.
8. Projects: save prepare/support/platform/mount/access/operate steps with
   navigation links and durable resumption.
9. Supports: pad exists; qualify posts/beams/braces/platforms and actual concrete
   production, supported/unsupported comparisons and removal behavior.
10. Connections: distinguish attached hoppers from separate piles, implement
    mounting and truthful settling/movement/support-removal guidance. Current
    rigid fixed connections have no attachment failure model.
11. Customization: design editing and installation declarations exist; build
    bounded versioned proposals for slope fitting, recipes, appearance,
    machine behavior and goals through paid use/reopening.
12. Skills: evidence-based construction practice, reachable Learn paths,
    achievement/unlock presentation and no circular prerequisites.
13. Shared writes: existing ordinary ownership/revision/retry gates remain;
    extend them to projects, site preparation and mounting with two-player,
    depletion, stale advice, lost-reply and restart tests.
14. Usability: conduct unaided human and AI ordinary-control construction runs;
    measure time, hesitation, wrong clicks and repeated refusals at each slice.

Next publish visual preparation/projects, then foundations/skills, then broader
customization. The full goal cannot be declared complete from this checkpoint.
