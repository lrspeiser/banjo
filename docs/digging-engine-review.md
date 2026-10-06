# Digging engine review and controller replacement

October 6, 2026. Baseline: GitHub main `383d871b`, fetched before changes.
Windows x64, Python 3.13, MSVC 19.44, Release CPU build. This checkpoint replaces
player cutting authority and recovery behavior. It is **not a completed terrain
constitutive solver, a full engine rewrite, or a passed digging-speed gate**.

## What one click actually did

The current route is `world.js` press ray → `tools.js` scheduler →
`/api/world/tool/use` → `tool_use.py` → native hand stroke → `ToolTerrain`
resistance/work → `Environment::detachDig` → native components →
`physical_matter.js`. The renderer uses native poses; it does not make up
fragment flight. No LLM call belongs in this route.

| Finding | Evidence | Change / remaining boundary |
| --- | --- | --- |
| Preparation and carrying could enter cutting contact | `ToolTerrain::prepare` evaluated every attached point without active-use intent | Named players now start idle. Only explicit use opens a cutting patch; preparation retains ordinary rigid collision. |
| A target was recorded but did not constrain the bite | `ground_aims` was exposed by the host; ordinary `meet`/`finish` did not use it | New native `ground-action` controls contact admission and the selected column. The old research aim still supplies no work or yield. |
| Small bites became broad shallow edits | `finish` widened the wedge to at least 1.5 terrain cells and spread measured volume across all selected columns | Controlled column-ground cuts use one column, cap depth by measured penetration and cap volume by the reduced model. Adjacent columns remain intact. This does not grant a whole cube. |
| First use repeatedly lifted, turned and lowered the tool | Browser idle carry left its wrist unconstrained; `_contact` had to establish orientation at the target | Carry requests a bounded ready orientation above terrain, independently of hover. Native hand force/torque limits remain unchanged. |
| Completion could add a 1.5 s wait | Ground preparation called `_stroke` without its already accepted stroke acknowledgement | Ground phases now retain the acknowledgement, as the object-strike path already did. |
| A short tap could trigger a long recovery | The shared historical pull moved 40 cm at 0.6 m/s | Contact recovery measures the remaining clearance and requests only that bounded lift. Explicit full-swing laboratory recovery is retained. |
| Successful pickup hid failed digging | The browser navigation regression ended at pickup | It now verifies green readiness, actual mouse/offset-touch digging, real released source cells and a closed rail. |
| Hiding the tool still left a flying cylinder | Screenshot review exposed the separate 34 cm joint-pin decorations; the old renderer test exercised only body meshes | Local first-person rendering also hides the held assembly's pin/rope decorations and reveal overlay. Native bodies/joints remain physical and peer views remain unchanged. Actual browser draw callbacks check both bodies and pin attachments. |
| Earlier fast-tool tests described a removed output path | `quick_tool_tests.py` expects automatic ledger piles and six successful uses in three seconds | This older browser speed test is not current evidence. Physical debris, collection and restart use the newer native-matter journeys. Rewrite the speed gate around actual removal. |

### Authoritative action scope

`Session.send` registers each named player idle before their first native action.
Restored named hands are registered before any world stepping, retaining the
opening's one-time geometry and whole-restore proof. An active target is transient
and is never restored as continuing excavation. Player scopes are separate.

`tool_use.run` owns the operation: prepare while idle, open the selected patch,
perform the bounded stroke/withdrawal, clear intent in `finally`, clear busy state
and listeners. Object strikes also begin with ground cutting disabled. An explicitly
authored full swing opens the same player patch after preparation. Anonymous
laboratory experiments remain physical experiments; an empty carrier ID cannot
distinguish a dropped tool from an anonymous hand.

Native admission checks the actual working point's terrain field and column.
Outside the authorized patch it restores ordinary collision and closes a measured
bite. Command scope is not a fracture law. Within it, existing dry reduced resistance
and measured work still decide penetration and release. The point/grip/component
configuration is shared by built-in and unfamiliar authored tools.

## Measurements and failed experiment

Before this checkpoint the paid unfamiliar-tool fixture took **3.318 s** for one
ordinary use, excluding walking; that was not a sustained speed measurement.
The original oak column experiment measured **2.771 s simulated time / 77.3 ms
native computation**. Fast headless execution does not imply fast player actions.

The controlled oak full-swing reference now releases **0.002153738999 m³ / 3.446 kg**
in one selected column: **25 constituent cells**, one native component,
**15.0801 J** measured ground work, **1.00833 s** simulated time at **1/240 s**.
Collection volume residual is zero; unchanged neighboring columns are checked.
This remains an experimental reduced soil detachment model, not solid fracture.

The identical idle/wrong-column scenarios retain glass, oak and iron. Each uses
25 cm terrain columns and 1/240 s stepping and releases zero matter with zero
cutting work. Hand work is still nonzero: **66.2069 J glass, 19.8039 J oak,
17.2601 J iron** in that fixture. Density/inertia and rigid contact differences
remain; blocking cutting does not block gravity/contact or prescribe velocity.

Real mouse and landscape-phone input recordings are emitted to
`build/resource-flow/dig-input-1280x800.json` and `dig-input-844x390.json`.
They separate preparation, stroke, closure and native elapsed time. A preliminary
run measured 0.808 s native elapsed for desktop and 1.733 s for an offset phone
tap; shorter clearance recovery reduced the phone result to 1.167 s in a later
run. The later focused gate measured 0.933 s desktop and 0.8625 s phone; the
different outcomes illustrate that these are individual fixed-camera input
fixtures, **not p95/rate acceptance**.
Capture files are `dig-green-*` and `dig-result-*` in the same directory.
The final fixed-observer run records **0.63333 s native / 0.63931 s host phases**
for desktop and **0.80417 s native / 0.78904 s host phases** for offset touch.
[Kept desktop record](evidence/digging-controller/dig-input-1280x800.json) and
[touch record](evidence/digging-controller/dig-input-844x390.json) contain actual
work, depth, mass and source-column observations. The phase sum excludes network,
rendering and walking. [Green desktop target](evidence/digging-controller/dig-green-1280x800.png)
and [phone result](evidence/digging-controller/dig-result-844x390.png) show the
held assembly without floating body or pin decorations.

A deeper 20 cm travel experiment was rejected and reverted. The 3 mm shovel
lost its iron blade (retained inventory mass changed from 2.30796 kg to 1.458 kg).
The unfamiliar cutter reached 18.769 cm and absorbed 22.8358 J, but lateral work
was insufficient to loosen matter; it released zero. Neither force limits nor
joint capacities were increased to make those tests pass. Longer travel alone
does not solve excavation, contact recovery or tool durability.

## What needs an actual physics rewrite

The earlier [ground audit](ground-matter-audit.md) remains relevant. Current dry
ground is material columns and a reduced point/wedge law. Detached matter is
connected rigid slabs with constituent cells. It has no qualified internal
fracture, granular flow, wear, or general wet excavation. Funded `work-cut-v2`
is a separate explicitly reduced finite-work adapter, not an impact simulation.
Full momentum/angular momentum/energy accounting across the hand, terrain,
released components and numerical contact correction is still open. Volume
residuals and paid work receipts do not close that ledger.

The compiled `SolidMatterPatch` reference is a useful oracle, not a drop-in
gameplay replacement. Its published experiment applies opposed 400 kN loads to
a free 25 cm block at 100 ns steps; it lacks anchored terrain and a finite
holder/contact response. The gameplay hand is bounded at 800 N / 60 N·m. Applying
the reference loads to make digging fast would invalidate the work/reaction
model. Before coupling it, define support boundaries, force transfer, multirate
stepping and an acceptance experiment at actual tool limits. At 100 ns, directly
stepping one simulated second requires ten million substeps; this arithmetic
is a scheduling warning, not a measured runtime. See the
[reference experiment and its unsupported laws](solid-matter-reference-checkpoint.md).

The next rewrite must put the following behind one native action interface:

1. A material patch owning solid/void state, damage, source IDs and boundary
   geometry. Rendering and collision read it; neither owns an excavation rule.
2. One tool/patch response with holder work and support/fragment reactions.
   Audit contact recovery and release overlap before increasing bite depth.
3. Persistent constitutive damage and connectivity changes, then conservative
   transfer into finite native components. Begin with a bounded CPU reference
   and compare glass/oak/iron plus supported terrain materials. No invented shards,
   launch velocities, hit-count yield, or material-name switches.
4. Actual collection and fabrication retain cells/material state through
   ownership, retry and restart. Unlimited Inventory stays an explicit storage
   abstraction, not a simulated infinite cargo compartment.
5. A real player speed test: sustained two successful removals per second,
   p95 response at most 400 ms, plus the declared 1 × 1 × 3 m excavation within
   five minutes including collection and finite power. Soil and rock are separate.
   These gates remain **unpassed**; see [adaptive ground speed](adaptive-ground-speed-plan.md).

### Simplification and removal order

At audit the World module has 12,949 lines, LiveWorld 17,459, tool host 965,
tool client 445, ToolTerrain 1,221 and ground detachment 445. These counts locate
ownership problems; they are not a deletion target.

Move the explicit full-swing experiment and its settling/recovery policy out of
the gameplay host after its laboratory callers/tests are isolated. Consolidate
browser/API/MCP preparation against the same native action contract; currently
MCP trial stepping and the wall-clock gameplay planner are different controllers.
Then remove obsolete automatic heap/receipt paths from physical excavation while
retaining ordinary finite machine/starter stockpile accounts and legacy recovery.
Finally migrate smooth-ground bulk and column physical routes to the accepted
patch implementation before deleting either. Rover extraction is a separate
adapter and must not silently become evidence for hand excavation.

This checkpoint changes shared authority, rather than deleting thousands of
lines whose remaining callers have not been replaced. The native cut model,
machine stock accounts, persistence, and laboratory controls have distinct roles.

## Verification

Build directory: `build/local-cell-tools`, Release, LAB off. Build the live runner,
shared library and native ground-work test target before Python/browser tests.
No new native source file or changed tolerance was introduced.

Final scoped result: the ten listed suites pass. The combined run passed nine;
the navigation fixture's thin-tool click was repaired to use a fixed fly
observer before projecting the press ray, and all three navigation tests then
passed in 26.67 s. The separate walking/cursor transition tests remain. A prior
reload assertion also read the last anonymous clock hand; it now checks the
named owner's authoritative `player_hands` entry. These repairs do not mock
native pickup, contact, released matter or persistence. Source registration
reports 305/305 built sources; both edited JS modules pass syntax checks.

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_live_world_run banjo_c banjo_ground_work_tests --parallel 4
python scripts/check-source-registration.py
ctest --test-dir build/local-cell-tools -C Release -R 'banjo_(tool_use|tool_target_client|ground_work|workshop_ground_tools|metal_shovel_game|physical_matter.*|world_navigation|raw_crafting)_tests' --parallel 2 --output-on-failure
```

The focused gate covers native material contact, selected-column/idle behavior,
mouse/touch pickup and digging, unfamiliar/thin paid tools, private matter,
raw crafting, inventory and restart. It does not establish a green full CTest
regression, physical-phone performance, the raylib laboratory input loop,
calibrated materials, or the remaining excavation-speed/conservation gates.
