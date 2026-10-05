# Tool grip recovery — October 5, 2026

Source base: main `5db45923`. Windows, MSVC Release native bundle from
`build/pickaxe-preview/Release`; host and browser changes only.

## Observed failure and repair

The actual port 18890 world showed Player 2 holding Field pick while tool
readiness replied “Take up a tool first.” Both native player grips were empty;
Player 1's inventory still claimed the released pick. A refused inventory
pickup fell through to an untracked native grip, and the page ignored native
tool release. The two-metre pickup lay just outside the existing arm bound.

Registered-item pickup refusals now stop and explain themselves. Only an
explicit unknown item permits the loose-fragment fallback. Native release
clears the tool icon, target and queued strikes, prompts recovery and refreshes
inventory. Inventory reconciles an explicitly empty native hand to world
ownership, retaining retry receipts. Missing hand data is not a release.
Whole restoration keeps this correction; fresh authored reopening still puts
old held items into the bag as before. Q uses E's nearby-tool detection when a
thin handle misses the centre ray, then normal numbered equip brings it out.

## Verification

- 19 native-backed inventory tests pass, including release/reacquisition and
  Alice/Bob exclusion while held, followed by pickup after release. Existing
  fresh reopening and whole-held restoration pass.
- Eight client input tests pass, including native release, cancelled repeats,
  registered refusal versus unknown-fragment fallback and thin-tool bag pickup.
- Three player identity, six inventory record and 39 host tool tests pass.
- Actual in-app browser, preserved owner world: reproduce refusal; recover
  through Find tool → Q → equip slot 1; green rock target; 10–90% progress;
  full cube removed; Collect Rock adds 37.5 kg to Player 2's stock. The normal
  UI shows the pick in the right hand and the stock after collection.
  Ignored screenshot: `build/construction-preview/rock-hand-recovery.png`.

Native arm bounds, mining work, density, terrain laws and binaries are unchanged.
This qualifies grip/ownership presentation and recovery, not new physics.
The broader body/view timing and partial-mining persistence boundaries remain
in [the cube targeting checkpoint](cube-targeting-checkpoint.md).
