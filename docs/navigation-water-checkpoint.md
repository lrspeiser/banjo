# Walking, water and cursor controls — October 1, 2026

Verified on main base `04f5789bddda27b96aba2cdb0b64d5e764becd26` with outgoing changes present. [Machine-readable evidence](evidence/navigation-water-checkpoint.json) retains source/binary hashes, input measurements and water results. Implementation **`3e2b508de9e3864d792e68a26a5bfa0cee4491a8`** is published on GitHub main. Preview: http://127.0.0.1:8770/world.

## Player changes

- Default unloaded movement: **4.2 m/s**, up from 2.4; Shift sprint **6.8 m/s**, up from 5.6. Existing load and immersion penalties remain.
- Edge look: **1.7 rad/s yaw / 0.9 rad/s pitch**, up from 1.1 / 0.6. The wide central aim/click zone remains.
- **Esc** switches between Explore and Cursor. Cursor mode clears movement keys, stops tool repeat and cancels a prepared throw without throwing or dropping the held item. Selected component pictures remain. The world continues running, including gravity and current drift.
- **Click world** resumes Explore; that first click is consumed, so it cannot also use, throw or pick up an item. Clicking the panel or focusing chat/Menu also releases navigation. Closing machine controls or explicitly selecting Walk/Fly/a driven machine returns gameplay controls.
- A small HUD button shows the cursor mode. Water shows **Wade/Swim, centimetres immersed**, and reported **flow direction/speed** when flowing. Fly remains explicit; invalid legacy movement preferences now default to gravity instead of displaying Walk while falling through to flight.

## What water currently does

Native objects use `WaterCoupling` hydrostatic face pressure, buoyancy, drag from relative water/body motion, torque and the existing horizontal water reactions. The water solver is a shallow-water approximation. No water, contact or material law is changed here.

Players, including remote player pictures, are still **camera controllers**, not native colliding bodies. Gravity and vertical buoyancy/drag use the existing 70 kg / 75 litre controller approximation. Feet follow the solid bed, not the water surface. Shallow water can therefore leave the eye well above the surface. In controller water deeper than 0.5 m, the reported current begins to entrain movement, reaching the full current velocity at 1.2 m. Shallower wading does not currently drift. No avatar reaction is transferred to water, other people, native objects or carried cargo. The HUD communicates immersion; it does not certify a native avatar.

Actual native avatar/contact/cargo reactions remain **R5** in the [remaining goals](player-experience-checklist.md#remaining-work). AI walking remains its existing server pose/dry-route controller. A physical player must be implemented and qualified through the shared native solver before claiming the player has the object's physics.

## Verification and limits

Windows, Python 3.13, MSVC 19.44 Release CPU ABI 25, actual Chrome keyboard/mouse input. Generated worlds use 50 mm scene cells and native dt=1/240 s. No live LLM/provider calls. Browser runtime and native physics checks are separate.

- `python tests/world_navigation_tests.py -q`, required Chrome: **1 pass**. Measures ~4.2 m/s walk and ~6.8 m/s sprint, faster edge turn, frozen look/keys in Cursor, Menu/chat, consumed resume click, selected item retention and invalid stored-mode reload. CI includes this suite.
- `python tests/world_goods_tests.py GoodsJourney.test_gravity_player_exits_real_river_walks_hills_and_can_swim_up GoodsJourney.test_plain_entry_generates_world_and_menu_switches_fall_jump_and_fly -q`: **2 pass**. Actual dry→wet→dry entry on both generated terrains, feet below the surface, ordinary hill ascent, jump and explicit Fly. Separately declared 2.3 m pool verifies swim up/dive/recovery and 0.4 m/s current; ~0.327 m controller drift over 0.8 s. This declared current is not a native generated-river drift measurement.
- `python tests/quick_tool_tests.py -q`: **5 pass**, including Esc stopping actual held tool repeat while retaining the tool, save deferral/restart/error handling, matched glass/oak/iron native contact.
- `python tests/material_preview_tests.py -q`: **6 pass**, retaining whole-item pickup, native ground work, source navigation, machine controls close→J and private output Collect.
- `python tests/world_page_journey_tests.py ClickingSomethingKeepsIt.test_escape_frees_cursor_and_preserves_the_selected_item -q`: **1 pass** through the ordinary saved-room page.
- Built registered `banjo_water_tests` and `banjo_valley_live_tests` CMake targets. `banjo_water_tests.exe`: **19/19 pass**. Same 1.6 × 0.24 × 0.24 m box, still water at 1 m level, densities oak 700 / glass 2400 / iron 7870 kg/m³: oak floats 70% immersed, glass and iron weight exceed full-volume lift. Equal full immersion gives all three **904.0896 N** lift; oracle residual **0 N**, retained 1e-6 relative tolerance. Closed-basin drift **4.26326e-14 m³**; 100 s river volume residual **−2.61569e-13 m³**. Solver CFL substeps remain adaptive. These are local hydrostatic/volume oracles, not full-pipeline energy/momentum certification or material calibration.
- `banjo_valley_live_tests.exe 'oak log drifts'`: **1/1 pass**. Existing native oak log drifts **0.554044 m/s** over 20 s; iron rests on the bed. No forced body velocity.
- `python scripts/check-source-registration.py`: **287/287**. `git diff --check` and changed checkpoint links pass. Own 8770 preview retains legacy reopening and fresh funded-workbench/pickup/compact Inventory with zero JS exceptions.

Initial test assumptions that the frozen generated river must contain a deep fast current were removed: actual generated entry and declared deep-controller current are now reported separately. An unrelated random “Mining rover” assertion in the plain-entry test now checks the actual nearby-material UI; specific ore navigation remains covered by material-preview tests. Windows browser shutdown can still log the previously recorded `WinError 10053` connection-close trace. No new cross-platform, physical-avatar, cargo or rendering performance claim.
