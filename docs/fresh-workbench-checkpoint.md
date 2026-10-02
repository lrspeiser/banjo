# Ordinary fresh-world workbench

October 1, 2026. Main based on `94a52ad`; verification used uncommitted changes.
Implementation `b305129` is published on GitHub main. Refreshed own 8770
preview reopens the existing 10-body legacy world without retrofitting its
process. Fresh entry has an empty workbench, 22-cell pick geometry, two component
thumbnails, native pickup and compact Inventory with zero JavaScript exceptions.

## Implemented

New generated maps declare a finite workbench in their manifest. It starts with
zero stock and zero energy: 500 W supply, 100 J/kg authored shaping work,
efficiency 1, 10,000 J/K station heat capacity, 2 W/K cooling and 473.15 K limit.
These are lumped gameplay inputs, not calibrated machining properties. The
station has no physical workbench mesh or native circuit connection. Existing
catalog stock and native starter battery declarations remain finite supplies.

The process ledger is initialized only after the native world opens, then saved
with the matching native time. A failed initial save can retry without a reset
or refill. Rejoin/restart retain both halves. Existing manifests without this
declaration keep their prior process or its absence; no legacy retrofit occurs.

Normal inventory, excavation, machine controls, goods collection, tool use and
saved actions remain available in funded worlds. Free native creation/charge and
unpaid installation remain refused. Raw program/control/drive writes use the
normal machine route; manual riding retains its bounded native command. A rover
under a player's recovery grip cannot be started or driven by another player,
including a numeric program ID supplied as a string.

Funded World chat reads the actual native world and runs existing saved item
actions. It never opens an authoring copy or creates free items. Its two tools
come from the existing MCP definitions. Incomplete provider responses execute
no partial tool calls. New/modified designs use Recipes or owned Inventory →
Lab → reviewed supplies → paid Make → native collection/use. The World text and
chat placeholder now describe this flow. Provider transport is mocked in these
checks; real-model creative/task success is not claimed.

Camp stool and work-table recipes declare a Place core use. Pending AI builds
compare current station and personal stock against their frozen quote, then buy
missing personal supplies using observed market prices and banked native energy.
Uncertain writes replay before any new purchase/debit. Empty market shelves
produce an explicit blocker with the workpiece retained. Shared stock is never
silently spent by the autonomous guest.

## Verification

[Retained measurements](evidence/fresh-workbench-checkpoint.json).

- Fixed fabrication QA **68/68**, 103.345 s, retaining native glass/oak/iron
  comparisons, paid machines, actual Chrome funding, original damage, rollback,
  replay and whole restart. No solver, material law or tolerance changed.
- Default-world First Camp **4/4**, 53.317 s: actual Chrome bank/buy, Recipes
  Make, personal funding, solar transfer, native work/placement, Q pickup,
  compact Inventory and Goals reload. Two players buy and build separately;
  both named stools and bags survive restart. A third paid product retains
  parked products/player records exactly; unparked bodies advance with time.
- Reference AI completes both available chains on both terrain types: **61
  decisions each**, 102.825/102.463 s wall time, 18.75417/18.95417 s native time.
  Zero provider calls; no supply/outcome fixtures. Each spends its own 8.8704 kg
  purchased oak and 887.04 J metered solar energy for a 2.5088 kg stool and
  6.3616 kg table. It personally studies/uses the ground tool and witnesses
  smelting. Two techniques learned out of ten; this is not the full tech tree.
  Empty-market blockers pass on both maps.
- Local material/work residuals zero; process-energy residual at most
  5.627e-13 J, native battery transfer residual at most 1.956e-10 J. These
  boundaries exclude the rest of the world and installed products' later work.
- Default/legacy/save-retry/controller/chat/concurrency **12/12**, 8.324 s;
  final funded-chat HTTP **1/1**, 1.183 s. Native/browser rover recovery
  **2/2**, 9.493 s. Chat tool parity **24/24**, Actions **40/40**.
- Default-world goods/player suite **15/15**, 107.296 s, including component
  pictures, goods failure/retry, automatic output pickup, daylight, gravity,
  recovery and private material stock. The ordinary paid pick authoring
  journey passes head-only iron edit, Save,
  supported all-oak draft, explicit shared stock/native energy funding and
  native placement. Mixed-material lattice fabrication remains refused.
- Source registration **287/287**, no exclusions. Windows MSVC 19.44 Release
  binaries in `build/agent-paid-machine/Release`, native dt=1/240 s and generated
  scene 50 mm. Separate retained fabrication fixtures use 40 mm. Native hashes
  are recorded in the JSON; no C++ source changed.

The HTTP test server joins requests after closing browser keep-alive connections
before deleting its temporary database. The closed-runner recovery fixture
clears its live holder before restoring the saved pair. Browser waits now check
that funding controls are enabled and use current compact Inventory selectors.

```powershell
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/agent-paid-machine/Release/banjo_live_world_run.exe).Path
$env:BANJO_LIBRARY=(Resolve-Path build/agent-paid-machine/Release/banjo.dll).Path
$env:BANJO_BROWSER_TESTS='required'
python scripts/fabrication_qa.py --engine build/agent-paid-machine/Release/banjo_live_world_run.exe --out build/resource-flow/fresh-workbench-20261001
python tests/starter_goals_tests.py
python tests/ai_player_tests.py ControllerBoundaries AutonomousGuests.test_fresh_workbench_is_empty_paired_durable_and_initial_save_can_retry AutonomousGuests.test_legacy_world_keeps_undeclared_workbench_after_restart AutonomousGuests.test_funded_chat_reads_actual_precise_world_and_refuses_free_creation AutonomousGuests.test_waiting_action_allows_world_clock_and_other_guest_to_run
python tests/ai_player_tests.py AutonomousGuests.test_reference_explorer_completes_goal_chains_on_both_generated_terrains AutonomousGuests.test_reference_explorer_reports_empty_market_shelves_on_both_terrains
python tests/world_goods_tests.py
python tests/chat_tool_parity_tests.py
python tests/actions_tests.py
python scripts/check-source-registration.py
```

## Remaining acceptance

The original fourteen-item goal stays active: **four verified, ten partial**.
This closes the ordinary empty-workbench/two-chain paid progression gap. It does
not qualify an actually damaged tool through fresh-world replacement/equip/use,
all resource sources, broad generated hauling routes, every machine, calibrated
forming, exact internal damage, mixed lattice interfaces, physical processed
constituents or transport. The next gate is an ordinary damaged-tool journey.
