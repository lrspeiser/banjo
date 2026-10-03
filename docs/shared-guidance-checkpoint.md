# Shared player guidance and paid build readiness

October 3, 2026. Published implementation: `0c18d18` on GitHub main.
Verification base: published `560aa03`, plus the outgoing host/UI changes.
Full owner scope remains active.

## Implemented

`playground/player_guidance.py` resolves one authenticated next action from
the active goal and the same observed capability catalog used by the reference
AI. World and every Workshop screen use `player_guidance.js`. Market's project
reading and AI Guide snapshots consume the same result. AI-character conversation
instructions distinguish its current recommendation from its recorded planner
history and the visitor's account.

The new `/api/world/guidance` route accepts an optional focused object, never
client-supplied inventory, wallet, owner or skill state. All personal reads bind
to the authenticated account. The result is a snapshot, not an action receipt.
Every actual action still rechecks ownership, sources, native admission and
placement. No chat grants a skill, material or physical outcome.

For the recommended project and Lab review, one exact quote path supplies
native manufacture mass, processed goods, energy and minimum duration. One
readiness calculation distinguishes missing supplies, unfunded station
materials, unfunded energy, an occupied station and the workpiece budget.
**Shape fits** on recipe cards is a geometry assessment, not a funded-build
promise. Stock quantities and the Market wallet do not fund a workbench by
themselves. Current paid Make has no technique gate; `skills_required=[]`
describes that lane and does not claim every design/function is supported.

`/api/world/fabrication/review_plan` refreshes an existing owned, unexpired
review against current station/source/configuration state. It does not reserve
or debit stock, allocate a new plan, extend expiry or replace its accepted
design. The Lab starts only when the server readiness permits it. Supply
buttons retain finite-source and request-retry guards.

An owned running/paused/ready workpiece takes priority over another build.
Its Lab link reloads the accepted candidate, including custom components and
machine bindings, and retains the actual job ID. Browser-local design edits
cannot replace the paid preview. Ready output can enter personal Inventory.
Equip guidance leads to the World quick slot. Gathering destinations aim at
the actual surveyed ground column, rather than the held tool. These links
change the view without moving the player or granting material. Lab-only review/condition panels
are hidden on other tabs. Before a native world is reopened, guidance says
**Open your saved World**, rather than claiming that unseen sources are empty.

## Verification

Windows, Python 3.13.5, Node 22.18.0, Intel Core Ultra 9 285K; reported display
devices include RTX 5090 and Parsec Virtual Display Adapter. Existing MSVC
Release native binaries: `build/agent-object-strike/Release`. No native source,
material law, solver tolerance or binary changed in this checkpoint. Browser
checks do not establish cross-GPU behavior or physics performance.

```powershell
$env:BANJO_LIVE_ENGINE=Join-Path $PWD 'build/agent-object-strike/Release/banjo_live_world_run.exe'
$env:BANJO_LIBRARY=Join-Path $PWD 'build/agent-object-strike/Release/banjo.dll'
$env:BANJO_BUILD_DIR=Join-Path $PWD 'build/agent-object-strike/Release'
python -m unittest discover -s tests -p game_guidance_tests.py -v
python -m unittest discover -s tests -p fabrication_remake_tests.py -k NativeRemake -v
python -m unittest discover -s tests -p ai_player_tests.py -k test_skill_and_market_guidance -v
python -m unittest discover -s tests -p ai_player_tests.py -k ControllerBoundaries -v
python -m unittest discover -s tests -p ai_player_tests.py -k test_reference_explorer_completes_goal_chains -v
node --experimental-default-type=module --check playground/player_guidance.js
node --experimental-default-type=module --check playground/workshop.js
node --experimental-default-type=module --check playground/world.js
python scripts/check-source-registration.py
git diff --check
```

- Eight guidance checks pass in 13.066 s. They cover client-state refusal,
  model instruction/tool boundaries, analytical mixed material/goods/energy
  gates, station occupation/workpiece limits, private snapshots with world
  access released during the provider call, actual empty processor input,
  plan refresh/configuration/expiry, correct surveyed-ground destinations and finite wood/solar funding.
- The paid flow confirms identical readiness between central guidance and
  the actual Lab review, all seven AI Guide screen snapshots, a private peer
  remaining on its own goal, and owned running/finished workpiece priority.
  Reads retain one cached plan. No wallet deposit is required.
- The native remake group has **8 passes and 1 existing failure**, detailed
  below. Passing cases retain glass/oak/iron paid Make/remake, source history,
  finite funding, refusal, save/restart and owned solar-bank bindings.
- The existing skill/equipment/input-shortage test passes. The full reference
  explorer passes both terrains in 186.718 s: seed 7/goods 851269742,
  33 decisions, 110.936 s wall / 40.4625 s native; seed 4/goods 1,
  31 decisions, 73.863 s wall / 22.0625 s native. Both obtain gathering and
  copper-smelting evidence, complete the two opening chains and retain private
  accounts through restart. Provider calls are zero in that headless test.
  This is not a ten-technique or live-provider completion claim.
- Nine existing controller-boundary checks pass in 0.017 s, retaining actual
  catalog targets, attributed evidence, pending paid work and bounded dry routes.
- The reference run preceded the final workpiece-priority/display refinements;
  its action executor and planner policy are unchanged. The subsequent owned
  job/refresh tests and browser recovery qualify those refinements directly.
- Source registration is 297/297 with zero exclusions. Python compile, Node
  syntax and diff whitespace checks pass. No tolerance changed.

Actual in-app browser: World and all six Workshop tabs show the same next
action for the same player. A real 1.925 kg oak / 192.5 J personal pick is
reviewed, funded from finite shared oak and a native connected array battery,
started, recovered by its owned job link/reload and collected into Inventory.
The product and private goal survive a full preview-server restart. Its World
quick slot is available after reopening. Captured JavaScript errors are zero.
Evidence is ignored under `build/shared-guidance/lab-ready.jpg` and
`inventory-next.jpg`. Only the owned port 8773 preview was restarted; the
user's port 8771 preview was left running. The preview retains its configured
autonomous machine behavior and may make model calls; the headless zero-call
statement above does not apply to the preview.

### Existing failed check explicitly separated

`test_failed_connection_paid_mixed_replacement_retains_original_and_works`
fails at its no-refusal assertion. The target connection actually fails during
preparation, followed by **The tool cannot reach that contact from here**.
The identical check against an isolated `git archive` of published `560aa03`
also fails: 3.5041667 → 6.1625 s, 53.06019 J hand work, 671.66807 N target
connection load against 200 N. The guidance change does not modify this law,
controller or contact path. The affected full physics/reuse gate is not claimed
green and the test/tolerance is unchanged. This is retained unfinished R3
behavior, outside the resumed guidance/hauling/avatar scope.

A broad test discovery initially selected the older browser harness; it was
stopped and is not counted as browser verification. Browser evidence uses the
in-app browser. An initial new refresh test incorrectly expected a candidate
field on a recipe-card row; it now requests the actual recommended candidate,
and the complete guidance group passes.

## Remaining full-scope acceptance

- Selected Lab project and editing/test conversations need shared focused
  readiness/guidance; the current central result follows the active goal or
  owned pending work. Empty-Lab/all-tab AI Guide integration is measured;
  selected design conversation is still its separate bounded assistant.
- Exact paid readiness covers the recommended project and reviewed Lab draft.
  Other recipe cards retain estimated BOM quantities and shape assessment.
  Broaden supported source/processor/recipe coverage and unavailable-source
  guidance, including exhausted physical energy.
- Finish actual human opening from loose wood and recognition/exposed-layer/
  gathering/peer/reload acceptance, with frame/native-step/memory measurements.
- Complete broader model-driven progression and LLM-created functional items.
- Reproduce/fix hauling failures and qualify native avatars/water and physical
  cargo under [R4/R5](player-experience-checklist.md#remaining-work).

The [realism review](world-realism-review.md) explains the product recommendation;
[readable world plan](readable-world-plan.md) retains the full active scope.
This is progress, not completion or a blocked goal.
