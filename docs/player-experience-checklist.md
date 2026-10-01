# Player experience work — September 30, 2026

The owner's fourteen-point goal supersedes the earlier progression-only task.
This is the current acceptance list, not a claim that all features are done.

| Item | Acceptance | Status |
|---|---|---|
| 1. Action clarity | Recorded dig/delivery/process packets, filling rover inventory, visible output, nearby personal pickup; failure/restart/race checks | Native/browser checkpoint verified; general generated routing remains a separate gate. See [resource flow](resource-flow.md). |
| 2. Day/night | Moving sun/shadows; measured solar charge; dark night; lamp switches on and draws its battery | New games declare a 600 s day and battery-powered automatic camp lamp. Native accelerated 10 s cycle verifies solar accounting, night draw and dawn switching; visual night/shadow review remains. Existing explicit worlds retain their declared sun. |
| 3. Fresh start | Ordinary entry creates a new playable generated map with bootstrap equipment; samples remain in Debug | Chrome verifies two plain entries create different generated worlds. Explicit world/scene/QA links preserved. |
| 4. Resource discovery | Deposits have readable visual cues; selection shows actual substance, quantity, reachable gathering action | Ledger extraction rings/labels implemented and present in Chrome; ground selection shows actual reserve/grade/rover action. Full selection usability review pending. These are extraction areas, not native ore-cell composition. |
| 5. Gravity mode | Menu toggles exploration/gravity walking; ground support, falling, grounded jump and collision boundaries verified | Chrome verifies menu, falling, one grounded jump per press and fly altitude. Kinematic terrain controller: native physical avatar/body collision boundaries remain open. |
| 6. Component inspection | Selected item can expand real components, with names/materials and a return to assembled view | Verified connected rover assembly, actual pick cell partition, names/materials, persistent expansion, Return to assembled and separate native-cell view. Full native-part membership, unchanged physical state, reduced motion and watched inspection pass. See component checkpoint below. |
| 7. Recipe guidance | Select recipe → exact personal/shared shortages, acquisition routes, blocking skill/equipment | Expandable card materials/acquisition routes implemented; native connected tool readiness fixed without granting strength. Full shortage/route browser journey pending. |
| 8. Gathering loop | Reach/find/make tool, explain capacity/refusal, visible carried stock in World, explicit empty/store/use action | World load meter shows actual native carried mass/limit/materials; full load displays stopped digging and H emptying guidance. Chrome HUD check passes; complete tool/full/empty journey pending. |
| 9. Workshop chat | Typing, sending and draft selection work; chat focus cannot be stolen by world key bindings | Native Chrome ordinary typing, submission, head edit and subsequent whole-item edit pass. Local failure cleanup and replacement textarea retain selection/disabled state. |
| 10. Pick authoring | Whole pick appears in Lab; metal head modification has actual component geometry/material; Save and Make give actionable outcomes | Verified exact bootstrap source recovery includes head/handle. Explicit Recipe→Lab survives reload; head-only iron edit and Save pass. Supported oak Make debits stock and preserves existing machines. Mixed-material lattice joining remains unsupported: metal-head Make and visual shape improvement remain open. |
| 11. Durability/repair | Integrity derives from actual recorded damage; supported repair requires matching material/energy and native restored/admitted geometry | Pending. No invented physical health, strength or free restoration. |
| 12. Rover safety/recovery | Actual sensor readings visible; route/dig clearance avoids own support; ordinary recovery available with bounded forces/work | Pending native reproduction on multiple terrains. |
| 13. Water and hills | Gravity walking can leave water and climb ordinary hills; rover climbs measured grades without forced motion | Player controller verified on two generated river crossings and hills; declared deep-pool ascent, buoyancy, dive and recovery pass. Native avatar and rover hill capability remain open. |
| 14. Output pickup and contained inputs | Output voxels fly into personal inventory on nearby walking; processor inputs stay in visible hoppers; rover delivery visibly fills them | Native/browser automatic output-only pickup and input bins implemented and verified. Fly leaves outputs untouched; server refuses auto-input pickup. Existing recorded dump/dock transfers retained; broad generated rover delivery and physical cargo/tipping remain open. |

Priorities: preserve the verified transfer checkpoint, repair fresh entry and
Workshop/tool/capacity blockers, then connect the remaining ordinary-player
journeys with measured acceptance. Keep CPU/native simulation separate from
presentation, retain glass/oak/iron comparisons for physical changes, and publish
verified coherent checkpoints regularly.

## Verification checkpoint

Resource flow implementation is published as `9cc3ad1` on main. The next
player-entry/Workshop checkpoint is published as `6098387` on main and uses Python 3.13.5, Windows Chrome and the
existing MSVC Release native engines from `f819e81`, at 50 mm and native
`dt=1/240 s`. No C++ or constitutive law changed. The explicit 10 s lighting
experiment consumed 100 J over five seconds at 20 W; array charge agrees with
initial charge + native collected − delivered energy within `3e-5 J` after
protocol rounding. It does not qualify full-world conservation or new materials.

Focused checks: resource suite (including two-guest failure/restart/races),
Workshop fitting 47, chat 38, tools 7, solar 9, live session 12, and both CSP
world-address/current-file hash checks. Remaining acceptance is listed above;
the full goal remains active.

## Water and hill controller checkpoint — October 1

Published implementation (including automatic output pickup/input bins):
`3a6d789` on GitHub main. Local preview restarted at `http://127.0.0.1:8770/world`.

Walking on open ground now reads the same interpolated triangles as the terrain
collider; underground floors retain solid/void-run support. The controller
permits half-metre steps and limits grounded hill ascent to 45 degrees. Gravity
and grounded jump remain 9.81 m/s² and 4.5 m/s. The camera uses an explicit
70 kg / 75 litre approximation over 1.6 m below the eye for water buoyancy,
2.5/s submerged vertical drag, and Space/Shift+Space swim strokes of ±6 m/s².
Acceleration is integrated in at most 1/120 s slices; no constant swimming
velocity is assigned. The menu and world inventory overlay show swim controls.

`world_goods_tests.GoodsJourney.test_gravity_player_exits_real_river_walks_hills_and_can_swim_up`
passes actual backward entry/shore return and uphill movement on terrain seeds
4/7 (resource seeds 851269741/851269742). A separate declared 2.3 m pool checks upward swimming,
surface flotation after releasing Space, diving and upward recovery. This pool
does not claim a native water volume or reaction test. Evidence is written to
ignored `build/resource-flow/movement-acceptance.json`. The existing native/browser
fresh-entry falling, single jump per press and fly-altitude case also passes.
The legacy sample water/current case passes after changing its fixture URL to
explicit `?scene=world`; a plain URL now intentionally creates a new game.

Windows Chrome, Python 3.13.5 and unchanged MSVC Release `f819e81` engines at
50 mm / native `dt=1/240 s`. This is a kinematic camera controller, not a native
colliding avatar: no reaction on water, carried objects or terrain is applied.
Rover torque/traction and grade qualification remain separate item 13 work.

## Component inspection checkpoint — October 1

Published implementation: `bcda7ab` on GitHub main.

Selection traverses actual attached joints (bounded to 64 bodies) and expands
reported precise parts (bounded to 256). Authored lattice boxes partition only
reported cells: every current cell must be assigned and every named component
must retain matter; otherwise current body matter is shown together. No material,
cell, joint, fragment or impulse is added to the native world. Body geometry
revisions invalidate the presentation. Labels identify component and material;
overlapping/out-of-view world labels are suppressed while the complete panel
list stays available. The assembly's mass/material/component count are reported
from all included bodies. Return to assembled restores the view; Show native
cells retains the existing timed voxel inspection. Reduced motion expands
immediately. Existing ground-layer inspection remains available.

Windows Chrome/native checks:

- `world_goods_tests.GoodsJourney.test_component_inspection_explodes_full_rover_and_actual_pick_cells_without_native_changes`
  matches the entire native attached-joint part set (14 parts across five rover
  bodies), partitions the pick's actual cells into haft/arm, checks persistence
  and collapse, and compares exact native time/bodies/machines before/after.
  Screenshot: ignored `build/resource-flow/rover-components.png`, visually reviewed.
- `workshop_navigation_tests.GameScreens.test_world_selection_reveals_reported_structure_then_restores_skin_without_stepping`
  retains exact cell edge/centre buffers, faded/restored skins and native state.
- The ground/reduced-motion/escape navigation case and reference character
  watched-inspection case retain their native no-mutation checks.

Native engines remain the existing MSVC Release `f819e81` binaries, 50 mm,
`dt=1/240 s`. This is presentation/inspection work, with no new material,
constitutive, fracture, repair, collision or conservation claim. Rover ground
support sensing, avoidance and bounded recovery remain item 12 work.
