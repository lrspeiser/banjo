# Stable world geometry and compact Inventory

October 1, 2026. Windows, main, based on `c83e56720480b070c58c288f23cc377e5c54298d`.
Publication mapping is recorded below after the verified checkpoint is pushed.

## Implemented

- The apparent wooden slab was the field pick's bounding box. Startup machine,
  sun and tool declarations returned poses without hull cells and replaced the
  host's opening picture. Pickup then requested complete geometry. The host now
  reads native geometry after declarations, before the first frame, including
  restored and carried worlds. Startup/restore receipts are preserved. The read
  advances no simulation time and changes no material, mass, ownership or law.
- The right-side Bag/Notes/Room/Bench/Keys/Settings strip is removed. The shared
  World/Inventory/Lab/Skills/Recipes/Market/Goals navigation remains. Keyboard
  help, recorded experiments, machine driving and world diagnostics live in
  Menu; learning navigation goes to Skills. K opens recorded experiments there.
- Mini Inventory reads the same authenticated hands, bag, stock and wallet as
  Inventory. It shows product thumbnails, Hold/Stow, compact material quantities,
  spendable personal energy, shared solar storage and current solar generation.
  Materials open filtered Recipes; Open all opens Inventory in the same world.
  Icons and quantity formatting are shared. Solar charge is not wallet currency
  or automatic income. Background reads neither collect nor bank anything.
- Product thumbnails use the current world mesh, cached per world/player for
  stow and reload. Previously parked items without a cached picture use a generic
  Inventory icon; full Inventory retains its design previews and Lab entry.
- Live meter updates keep the item and machine-choice buttons stable through
  pointer-down/up. Menu suppresses world shortcuts. One existing Walk/Fly
  selector replaces the duplicate legacy Fly control and releases a ridden
  machine before returning to walking or flying.

## Verified behavior

Evidence: [retained summary](evidence/inventory-rendering-checkpoint.json).

Fresh generated Chrome entry draws the pick's handle/head from its 22 native
cells before pickup. Actual E → Stow → reload → Hold preserves the exact local
vertex array, cell positions and 1.925 kg mass. Its cached picture survives stow
and reload. The same item appears in full Inventory. No JavaScript exceptions.
Short-window controls, mouse machine choice, driving/release, camera attachment,
keyboard help, K experiment listing and the unified fly/return journey pass.
Prior own-preview world reopens with ten bodies. The 1280×800 window capture was
inspected; the item button and energy readings fit in the right rail.

Matched joined T fixture: handle 200×40×40 mm, head 40×40×120 mm, overlapping
40×40×40 mm; 20 mm grid, no physical step, geometry read at t=0:

| Material | Native cells | Native mass kg | Mass change kg | Elapsed change s |
|---|---:|---:|---:|---:|
| Glass | 56 | 1.12 | 0 | 0 |
| Oak | 56 | 0.3136 | 0 | 0 |
| Iron | 56 | 3.52576 | 0 | 0 |

Mass differences follow catalog density. This is geometry transport/identity
acceptance, not a stiffness, fracture, grain, forming or conservation claim.
No solver or constitutive tolerance changed. Exact thermal/internal damage,
mixed lattice interfaces and calibrated forming retain their existing limits.

Checks on the existing Windows Release binaries in `build/agent-paid-machine`:

- Fixed Fabrication QA: **64/64**, 72.912 s. An initial geometry-read regression
  erased host restore receipts; preserving them fixes all five affected cases.
- Browser journeys: **8/8**, 44.516 s, with actual mouse/keyboard input. An
  initial choice-button replacement failure and legacy fly-mode failure were
  fixed. The final shared-helper/layout/K changes additionally pass both compact
  Inventory and short-window journeys, plus fresh/prior preview acceptance.
- Native session suite: **10/10**, 0.436 s; matched geometry evidence rerun passes.
- Source registration: **287/287**, no exclusions; changed-file/link checks pass.

Commands:

```powershell
$env:BANJO_BUILD_DIR=(Resolve-Path build/agent-paid-machine/Release).Path
$env:BANJO_BROWSER_TESTS='required'
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/agent-paid-machine/Release/banjo_live_world_run.exe).Path
$env:BANJO_LIBRARY=(Resolve-Path build/agent-paid-machine/Release/banjo.dll).Path
python scripts/fabrication_qa.py --engine build/agent-paid-machine/Release/banjo_live_world_run.exe --out build/resource-flow/compact-inventory-final-20261001
python tests/live_session_tests.py LiveSession -v
python tests/world_page_journey_tests.py CompactInventoryAndStableToolShape TheBottomOfThePanelCanBeReached YouAreAMachineInTheRoom AThingIsDrawnAsTheShapeItWasDrawnTo -v
python scripts/check-source-registration.py
```

Headless Chrome runs the actual browser input/render loop. Native raylib Lab was
not rebuilt or requalified; no cross-GPU/macOS/Linux qualification is implied.
The complete fourteen-item player experience goal remains active: four verified,
ten partial. This improves item identity and usable navigation; ordinary finite
workbench integration, full paid progression and damaged-tool use remain next.
