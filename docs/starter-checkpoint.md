# Willow Clearing: first-person starter game

Source `c10d379b6da72f7f07a283909d6dd577d4302084` on local `codex/physics-foundation`, following the gameplay/runtime foundation `facfdba83d8ba9c5e79e97f7bf637f6df1cd0941`. Local only, not pushed or merged. The original main laboratory remains separate. This is a playable starter prototype, not completion of realistic cutting, physical energy accounting or the full [project goal](project-master-plan.md).

## What is implemented

- First-person mouse-look camera with no visible body or hands; WASD walking on a bounded flat clearing, static obstacle checks, crosshair and click targeting within 3.2 m.
- Eighteen loose resources across oak, iron and glass, a crafting table and one attached oak branch. Actual resource bodies and crafted spheres/boxes use the shared Jolt runtime; the table, trunk and rest log have fixed colliders. Perimeter trees/canopies are scenery, not general simulated/harvestable vegetation.
- Clicking a settled resource consumes gameplay stamina, removes its body and credits its exact material volume to raw inventory. The UI displays density-derived kilograms and equivalent 1 cm voxel counts. Fractional voxel equivalents retain volume; this is a raw-material reservoir, not a dense grid or a fracture/thermal-state-preserving physical conversion.
- The crafting table lists six preset designs: wooden pry tool, iron cutting tool, glass/oak/iron rolling spheres and an oak block. It shows required/held/missing material, level, stamina and other blockers; acceptance rechecks them. Tools are carried/equipped without drawing hands. Other outputs spawn physically on the table, where they fall and collide.
- Every successful pickup gives 5 XP, craft gives 10 XP and completed branch cut gives 10 XP. Level is `1 + floor(XP/20)`. The iron cutting tool and iron sphere require level 2; the basic designs require level 1. XP is checked against persisted object/cut/crafting progress.
- Stamina begins at 100. Pickup costs 8 without a tool, 5.6 with the wood tool, or 3.6 with the iron tool. Craft costs are declared game rules: 12 for the pry tool, 18 for the cutting tool, 10 for glass/oak shapes, 14 for the iron sphere. Hold R to recover 12 stamina per second up to 100. These are gameplay units and balancing parameters, not joules or physical efficiency measurements.
- Cutting requires the iron tool. Four actions, each costing 5 stamina, increment a stored cut fraction. At completion, the fixed Jolt attachment is removed and gravity moves the branch without a synthetic launch impulse. It must be collected separately after settling. This whole-branch cut rule does not weaken the solver constraint continuously, deform the branch, propagate a crack, simulate grain, account fracture work or establish realistic wood cutting.
- Action IDs preserve successful interaction/craft replies. Retries do not debit or award XP twice; conflicting IDs reject. Actions execute on an unpublished candidate and publish only after successful validation. Saves retain raw material, objects, tools, cut fraction, stamina ledger, XP, ticks and receipts. Material balances, declaration identity, progress bounds, duplicate fields and malformed saves are checked.

The first path is **collect wood → craft pry tool → collect iron and reach level 2 → craft cutting tool → cut branch → let it fall → collect raw wood**. Better tools reduce the cost of later gathering. An unaffordable or locked design remains visible.

## Playing

The game is currently running from `build/starter-play` in the development repository. Controls:

| Control | Action |
|---|---|
| WASD held | Walk |
| Mouse | Look |
| Left click | Collect/cut target or open crafting table |
| Tab | Inventory |
| R held | Rest/recover stamina |
| Escape | Pause or return |
| Home | Reset view direction |

The app autosaves about every 10 render seconds and after successful click actions; it saves on normal close. Player position/view and an open menu are not persisted. The old workshop workspace is preserved. To launch after closing the running instance:

```text
build/win-integration/Release/banjo_starter.exe --workspace build/starter-play
```

## Verification and evidence

All **16 Windows CTest executables pass in 11.67 s** at the gameplay/runtime foundation. The later source change only switches discrete inventory/pause keys to raylib's key-down event queue and adds Home view reset; it builds and passes the native checks below. The headless/runtime sources and binaries are unchanged by that input-only patch.

The new starter test exercises pickup/craft cost and exact raw volume, missing stamina/level/material rollback, successful action replay, no duplicate XP, tool cost reductions, level unlock, fixed branch support, four cuts, impulse-free release, actual gravity/landing, separate branch collection, material restoration without stamina refunds, disk save replacement/reload and malformed/altered save rejection. Glass, oak and iron all undergo the same-sized crafted-sphere free fall and collection cycle. Separate equal-size pinned boxes support gravity, release with no change in velocity and reach **-1.962 m/s after 0.2 s** for all three materials, within 1e-4 m/s. Crafted sphere velocity after 0.1 s is checked against -0.981 m/s within 1e-5. Existing dynamics/creator/assistant/conservation regressions remain in the full suite. No prior physical tolerance was widened.

Automated clearing and crafting captures both exit 0 and were inspected for legibility, first-person view, missing material and level information, inventory and stamina. They use explicit deterministic fixtures; they are not normal gameplay input evidence.

Native window inspection became available for this app. Initial short Tab/Escape taps were lost by frame-state polling. Using the key-down queue fixes those taps; subsequent native checks successfully open inventory, click Back to World, open pause and click Resume. Mouse-look changes the view. A short injected W tap did not establish held-key walking. Native walking-to-pickup, collection, crafting, cutting and rest remain unverified; the full progression is verified through the shared game backend tests. Do not claim a complete normal-input walkthrough.

Current owned process: exec session **17588**, returned window **10159794**, workspace `build/starter-play`. Previous owned starter session 57130 and old workshop session 98011 were intentionally stopped for relinking; their Ctrl+C exit 1 is not a normal-close test. The separate main laboratory was left untouched.

Windows 11 Pro 26200, Core Ultra 9 285K, RTX 5090/NVIDIA 580.88/OpenGL 3.3, MSVC 19.44 x64 Release, CMake 4.1.2, Jolt 5.6, raylib 6.0. The custom-frame-control, busy-wait and static-MSVC-runtime options remain OFF.

Reproduce:

```text
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
build/win-integration/Release/banjo_starter.exe --workspace build/new-clearing-capture --capture build/clearing.png --layout clearing --frames 60
build/win-integration/Release/banjo_starter.exe --workspace build/new-crafting-capture --capture build/crafting.png --layout crafting --frames 60
```

## Required next work

1. Connect the existing real LLM designer to this player inventory, level, stamina and tool capabilities. The current starter table is a preset catalog; the earlier workshop retains the real natural-language creator. Do not claim that the new table already accepts arbitrary natural-language designs. Keep semantic intent, exact missing resources and explicit alternatives from the [requirements checkpoint](requirements-checkpoint.md).
2. Establish the physical stock/reference state and energy/process boundary before calling gathering or manufacture energy-conserving. Today's conversion and crafting are game/authoring transformations; removed motion/potential energy, processing work, support reactions and carried tool mass are not a closed physical ledger. No physical work source or real fabrication cost is implemented. Keep [the energy contract](energy-system.md) and M05 defects active.
3. Replace whole-branch cutting with a supported, work-accounted section/interface/material model: cut location, remaining cross-section, loads, bending, grain, failure, damage history and tool/material interaction. Carry glass/oak/iron controls and resolution/timestep/area tests. A cut percentage and fixed joint do not fulfill realistic fracture.
4. Unify general player-world resource/creator APIs, support actor authority, durable acknowledgement, isolated functional tests and LLM evidence, more harvestable geometry and meaningful tool actions. Current stamina multipliers are explicit game balance, not emergent tool mechanics. Camera locomotion has static planar obstacle checks, not a mass-bearing physical character or jump/terrain solver.
5. Finish native gameplay verification, persist player pose/pending designs and establish reliable multiple-session save ownership. Current bounded prototype supports 64 total object records and 512 action receipts. It rebuilds a candidate Jolt scene for authored actions, losing contact/sleep caches; it is not a performance or bit-exact reload guarantee. Atomic file replacement does not establish crash-durable combined acknowledgement.

Retain the full [40-row scorecard](mechanics-scorecard.md), every conservation/material/shape/adaptive-matter/assembly/API/publishing gate, and the complete application objective. This milestone makes the requested game loop concrete while keeping its unresolved physical requirements explicit.
