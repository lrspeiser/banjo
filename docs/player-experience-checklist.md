# Player experience work — September 30, 2026

The owner's fourteen-point goal supersedes the earlier progression-only task.
This is the current acceptance list, not a claim that all features are done.

| Item | Acceptance | Status |
|---|---|---|
| 1. Action clarity | Recorded dig/delivery/process packets, filling rover inventory, visible output, nearby personal pickup; failure/restart/race checks | Native/browser checkpoint verified; general generated routing remains a separate gate. See [resource flow](resource-flow.md). |
| 2. Day/night | Moving sun/shadows; measured solar charge; dark night; lamp switches on and draws its battery | Verified native cycle and ordinary Chrome sun/shadow/charging/night/lamp/dawn journey. Store values/rates come from actual native counters; unwiring the lamp visibly darkens the scene. See [day/night evidence](daylight-player-checkpoint.md). Rendering/photometry approximations are explicit; saved worlds retain their sun. |
| 3. Fresh start | Ordinary entry creates a new playable generated map with bootstrap equipment; samples remain in Debug | Chrome verifies two plain entries create different generated worlds. Explicit world/scene/QA links preserved. |
| 4. Resource discovery | Deposits have readable visual cues; selection shows actual substance, quantity, reachable gathering action | Ledger extraction rings/labels implemented and present in Chrome; ground selection shows actual reserve/grade/rover action. Full selection usability review pending. These are extraction areas, not native ore-cell composition. |
| 5. Gravity mode | Menu toggles exploration/gravity walking; ground support, falling, grounded jump and collision boundaries verified | Chrome verifies menu, falling, one grounded jump per press and fly altitude. Kinematic terrain controller: native physical avatar/body collision boundaries remain open. |
| 6. Component inspection | Selected item can expand real components, with names/materials and a return to assembled view | Verified connected rover assembly, actual pick cell partition, names/materials, persistent expansion, Return to assembled and separate native-cell view. Full native-part membership, unchanged physical state, reduced motion and watched inspection pass. See component checkpoint below. |
| 7. Recipe guidance | Select recipe → exact personal/shared shortages, acquisition routes, blocking skill/equipment | [Ordinary shortage→collect→paid Make](recipe-supply-checkpoint.md) and [recursive raw-source guidance](gathering-supply-checkpoint.md) verified, including empty hopper yield targets and cycle refusal. No invented Make skill gate. Process/output-to-build and broader saved-design shortage journeys remain. |
| 8. Gathering loop | Reach/find/make tool, explain capacity/refusal, visible carried stock in World, explicit empty/store/use action | [Actual browser Find/E/J/F/full/H/resume](gathering-supply-checkpoint.md) and [private native carrying](private-ground-checkpoint.md) pass: personal capacity/bag mass, stroke ownership, two-player/server restart and staged storage. World/Inventory show actual ground stock. Earlier unassigned-load recovery, broken-rock empty/storage and usable build stock remain. |
| 9. Workshop chat | Typing, sending and draft selection work; chat focus cannot be stolen by world key bindings | Native Chrome ordinary typing, submission, head edit and subsequent whole-item edit pass. Local failure cleanup and replacement textarea retain selection/disabled state. |
| 10. Pick authoring | Whole pick appears in Lab; metal head modification has actual component geometry/material; Save and Make give actionable outcomes | Verified exact bootstrap source recovery includes head/handle. Explicit Recipe→Lab survives reload; head-only iron edit and Save pass. Supported oak Make debits stock and preserves existing machines. Mixed-material lattice joining remains unsupported: metal-head Make and visual shape improvement remain open. |
| 11. Durability/repair | Integrity derives from actual recorded damage; supported repair requires matching material/energy and native restored/admitted geometry | Partial: [native condition readings](body-condition.md) show actual cuts, supported current thermal factors, unresolved/broken and unmodeled states in World/Inventory/carried Lab. Bag/restart readings pass. Fatigue, joint health and paid native repair remain open; no free restoration or strength certificate. |
| 12. Rover safety/recovery | Actual sensor readings visible; route/dig clearance avoids own support; ordinary recovery available with bounded forces/work | Ground/water probes, support-aware digging and nearby bounded recovery verified. Ordinary recovery stops the rover, preserves collected load and restores the personal grip on reload. Native actual-pit lift passes; extended drive/route/grade qualification remains open. |
| 13. Water and hills | Gravity walking can leave water and climb ordinary hills; rover climbs measured grades without forced motion | Player river/hill and deep-pool controls pass. [Native stock-rover experiments](rover-grades.md) qualify a 12° generated oak-rover declaration with glass/oak/iron comparisons and native terrain climbs; sharp ground warnings remain. General generated routes, physical payload and native avatars remain open. |
| 14. Output pickup and contained inputs | Output voxels fly into personal inventory on nearby walking; processor inputs stay in visible hoppers; rover delivery visibly fills them | Native/browser automatic output-only pickup and input bins implemented and verified. Fly leaves outputs untouched; server refuses auto-input pickup. Existing recorded dump/dock transfers retained; broad generated rover delivery and physical cargo/tipping remain open. |

## Day/night checkpoint — October 1

The subsequent [condition checkpoint](body-condition.md) makes item 11 partial:
four verified and ten partial, with fatigue and supported repair still open.
The counts below describe the earlier daylight checkpoint.

[Native-to-browser acceptance](daylight-player-checkpoint.md) completes item 2:
moving visible sun and measured shadows, actual solar charge/flow, dark night,
native 20 W automatic lamp and dawn switching. Verified items are now 2, 3, 6
and 9; nine remain partial and durability/repair is pending. The full goal stays
active. Historical checkpoint counts below reflect their earlier state.

## Generated first-haul checkpoint — October 1

The subsequent [return-hauling checkpoint](rover-return-routing.md) now verifies
three positive receiving loads on both maps, exact routine reopen and retained
first-load processing/private pickup. It supersedes the earlier blocked-return
result below. Items 1, 12, 13 and 14 remain partial because general terrain,
physical cargo/tipping and the other listed boundaries are still open.

[Two-map acceptance](generated-rover-hauling.md) now verifies ordinary native
startup, first mining/delivery, processing, nearby personal pickup and exact
SQL credit/restart/retry. First loads are 40.000000 / 29.995942 kg at 68.2 /
82.0 s. Two generated cases, all 15 browser/player cases and all 50 rover-brain
cases pass. The refreshed 8770 preview also passes entry/readings/recovery/release.

Items 1, 12, 13 and 14 gain this first-haul evidence but remain partial:
sustained return hauling, general terrain clearance and physical cargo/tipping
are open. Items 3, 6 and 9 remain verified; durability/repair is pending.
The full fourteen-item goal stays active. Earlier checkpoint entries below
retain their historical measurements and limitations.

Priorities: preserve the verified transfer checkpoint, repair fresh entry and
Workshop/tool/capacity blockers, then connect the remaining ordinary-player
journeys with measured acceptance. Keep CPU/native simulation separate from
presentation, retain glass/oak/iron comparisons for physical changes, and publish
verified coherent checkpoints regularly.

## Stock-rover grade checkpoint — October 1

Published implementation: `8d3bc1f` on GitHub main. Native runner/platform CLI
and native test were rebuilt from this checkpoint's sources; preview 8770 was
restarted and verified with that build.

[Full grade measurements](rover-grades.md) record 18 material/grade scenarios,
autonomous ramp/terrain cases, actual motor torque-speed envelope, battery
residuals and unclosed mechanical work. Ground probes no longer use chassis
pitch as the terrain reference. An initially tilted flat-terrain probe reads
zero, then detects a real 0.5 m cut. Native ordinary-hill travel improves from
1.28087 to 3.34079 m with 8° / 12° declarations; tight curvature still warns.
New generated stock oak rovers use 12°; saved programs and the distinct editable
Workshop assembly retain their settings.

Windows/MSVC Release: 19 native cases pass, three affected CTest suites pass
in 11.22 s, 15 resource/player/browser checks pass in 104.936 s, source guard
286/286, rebuilt preview Chrome fresh entry/readings/recovery/release passes
with 794.61 N pull, 544.19 J hand work and zero exceptions. Native runner and
platform CLI were rebuilt; ordinary preview remains on port 8770.

Two 300 s baseline generated routes at source `5ab072f` fail to deliver:
seed 4 never loads, seed 7 holds 40 kg but never reaches its intake. Next
qualify actual route/obstacle/arrival and receiving receipts on both maps.
Ledger cargo adds no native inertia; this is not a material realism,
full conservation or general grade/route certificate. All fourteen gates remain.

## Rover recovery checkpoint — October 1

Published implementation: `a040683` on GitHub main. The native solver/runner
sources remain the preceding `29a3c71` build; the added native regression target
was rebuilt through CMake for this checkpoint. Preview:
`http://127.0.0.1:8770/world`.

Select a wheeled rover in the World right panel or open its machine panel and
press **Take hold to recover**. Approach the chassis within 2 m with a native
clear view. The program stops; looking up lifts the grip target, walking pulls,
the wheel adjusts reach, and **E / Release rover** lets go. The panel reports
actual hand pull in N and work in J; target/grip separation reports following
versus pulling. The rover stays off until explicitly turned on. Recovery uses
existing native `wield`, force-at-grip and wrist torque; it does not set a body
pose, assign a velocity, reset parts or replenish goods.

The existing authenticated `/api/world/machine` route accepts
`{session, program, recovery: "start" | "release", person}`. Start validates
the current attached part set, personal free hand, other players' grips,
native ray hit and existing carry allowance under the world state lock.
Power-on is refused while a rover has a recovery grip. A failed first save
releases that grip and leaves the rover stopped; failed release warns that
the change was not saved and can be retried. Repeated start retains the native
grip/work. Reload adopts its actual grip target without a hinge guide or a
second grasp. Packing during recovery is refused with Release guidance.

Windows / MSVC Release / Python 3.13.5 / Chrome; 50 mm and native
`dt=1/240 s`, unchanged solver/material laws:

- CMake-registered `banjo_rover_roam_tests` now passes 15 cases. The added case
  cuts an actual 0.6 m basin, lets the entire attached rover fall 0.601035 m,
  lifts it 1.23972 m, pulls it beyond the rim and releases it onto uncut ground.
  Peak pull is 800 N, measured hand work 541.516 J, unchanged native body mass
  43.5471 kg; every original joint attachment remains. Grip/work survive reopen.
  Work minus change in native mechanical energy is 6.71289 J. This residual is
  unclosed: brake/contact/drag losses and numerical correction are not fully
  allocated by this test, so it is not a full conservation certificate.
  The pit experiment declares 10,000 kg excavation storage to cut its basin;
  normal player allowance remains 80 kg, hand 800 N / 60 N m.
- The two-map API case collects a real routine scoop before recovery, retains
  hopper load and processor stock, refuses distant/occupied/other-player hands
  (including another wheel), preserves the native bodies after failed acquisition,
  and tests repeated start, failed release, retry and saved-world reopen. Native
  work/time/load persist; restored pose protocol checks use five decimal places.
  Hinge angles are recomputed from float poses, so full snapshot byte equality
  is not claimed across reopen.
- Chrome clicks the visible button, raises the native rover through view controls,
  reads Pull/Work, refuses Q packing, reloads without resetting the grip and clicks
  Release. No browser exceptions. Screenshot: ignored
  `build/resource-flow/rover-recovery.png`.

Final affected gates: 44 resource/browser/live/API/MCP transport checks pass in
111.287 s; source registration remains 286/286. Syntax and changed-file checks
pass. The combined transport suite also exposed an existing module-order issue:
its handshake expectations now read the source declarations, rather than the
platform wrapper's mutated imported core metadata. The running port 8770 preview
passes a fresh-world Chrome acquisition/lift/release with 793.37 N pull,
307.30 J work and zero browser exceptions.

The grip is an external actuator: a reacting native player body and muscular
energy budget are not implemented. Collected goods remain a durable ledger;
they do not yet add hopper inertia. One basin lift does not qualify all pit
shapes, slopes or extended routes. Retain native avatar, physical cargo/tipping,
grade and conservation gates, plus prior glass/oak/iron law boundaries.
The fourteen-item goal remains active.

## Rover excavation support checkpoint — October 1

Published implementation: `29a3c71` on GitHub main, following sensor checkpoint
`ff1b252`. MSVC Release native runner and regression targets were rebuilt from
these sources in `build/agent-progression`; earlier `f819e81` binaries are not
the current rover sensor/guard build. Local preview: `http://127.0.0.1:8770/world`.

Machine digs carry their native program id. Native `digClearance` traverses
the current attached hinge assembly (bounded to 64 non-anchored bodies), reads
the solver's current turned collision-shape bounds and excludes any scoop/trench
rectangle intersecting that footprint. The exclusion includes half scoop width
plus one terrain-grid diagonal, because an edited height-field node changes
adjacent support triangles. The native dig checks again before removing anything.
`dig_clearance` is a read-only runner/Live query (`program`, `from`, optional
`to`, `width_m`), returning `clear`, `stand_off_m` and `why`. Ordinary manual
terrain edits remain possible; this is a machine digging policy.

The routine's default ahead scoop uses the reported conservative assembly radius
plus 20 mm, within its existing 2 m reach. Explicit targets/widths that would
undermine it are refused, with a compact reason retained in its notes. This
does not turn a flying scoop into a wheeled machine or alter native forces.

The additional native case verifies a wheel outside the chassis, exact snapshot
equality after refusal, a successful safe native cut and a rejected wider scoop.
Measured fixture stand-off: 1.23872 m. All 14 native rover cases pass. Ordinary
generated maps 4/7 refuse digging beneath the chassis without changing the
snapshot, and normal routine scoops collect 40.000000 / 29.994279 kg into their
40 kg hoppers (native removal varies with terrain).
The affected 40-test rover-brain suite passes, retaining its native routine
delivery and exact receiving/restart receipts. This is conservative collision-
shape clearance, not proof of slope stability: diagonal trench rectangles may
over-refuse; secondary collapse, traversing old excavations and a complete
generated delivery route remain acceptance work. Hover scoops retain their
existing exemption. Physical recovery and native grade qualification stay open.

Final Windows gates: 37 resource/browser/live/API tests pass in 99.888 s;
41 generated-scoop + rover-brain tests pass in 6.561 s. The rebuilt cart CTest
passes in 0.55 s; all 286 native sources remain registered. These measurements
qualify the guard and retained journeys, not a full material/conservation audit.

## Rover ground-sensor checkpoint — October 1

Sensor implementation is published on GitHub main at `ff1b252`.

Ground probes measure the signed discrepancy between the chassis tangent plane
and the actual interpolated terrain collider surface: positive is a drop,
negative a step. They trip on its absolute value. Default fresh/generated and
Workshop rovers fit five ground probes (three front, two rear), with a 0.12 m
threshold, beside five 3 mm water probes. Authoring, installation and native
save/reload preserve both kinds and direction. The bounded authoring/runtime
limit is 16 probes per controller/program. Existing saved rovers retain their
original declarations; this checkpoint does not retrofit them.

Selection shows live front/rear, side, Drop/Step/Level and Dry/depth values in
the right panel, with ground hazards first. Controller readouts, riding displays
and AI senses retain the kind; a ground hazard is not reported as water. The
program uses its existing motors/brakes/avoidance reflex. Explicit human driving
orders retain the existing override, which can drive into a reported hazard.

Windows / MSVC Release / Python 3.13.5 / Chrome, 50 mm matter and native
`dt=1/240 s`: 13 native rover cases pass, including a real dry cut with a
0.581449 m reported drop, unchanged rear ground, save/reopen reading difference
below `1e-6 m`, and six seconds of avoidance with maximum chassis z = 0 m before
the hole at z = 1.5 m. The cart CTest and 77 affected Python tests pass. All 12
resource/player journey checks pass, including an actual native dig changing
the selected rover's panel to Drop + warning; the final focused browser rerun
passes after rebuilding. Screenshot: ignored
`build/resource-flow/rover-ground-sensors.png`, visually reviewed. Source
registration is 286/286; JavaScript syntax passes.

This adds a sensor/query/controller capability, no contact, material,
constitutive or traction law. Earlier glass/oak/iron and conservation boundaries
remain. Point probes use the top height field; they do not detect cave roofs,
dynamic obstacles or every gap between probes. One dry-hole fixture is not
multi-terrain route qualification. Own-support excavation clearance, ordinary
physical recovery and native rover hill capability remain open.

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
