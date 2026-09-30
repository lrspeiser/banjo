# Workshop recipe contract

## Visual cards and Make feedback — September 30, 2026

Recipes now show source thumbnails, mass-weighted material completion, named missing-supply bars, Build and Skill values, and compact declared-use badges. Full material quantities and compiler reasons are expandable. World process inputs/outputs/machines are under a separate fold; internal family names and default dimensions are not primary card content. Thumbnail reads do not select or replace the player's Lab item.

Make stays on Recipes and reports progress, a refusal or `Made` on that card. A made object stands in the World, not automatically in the bag. View in World preserves the world/guest, turns the camera toward the installed body's current native position and selects its inspector without moving the player's position. Pick it up in the World to carry it. Successful Make refreshes all material percentages; a stock race shows the refusal and refreshed shortfall on the same screen.

Recipe Make now uses a separately reconstructed source and `replace:false`, so another click creates another paid native copy rather than replacing an earlier prototype. The Lab's existing prototype-replacement behavior is retained. Placement retries recognize the exact adapter's overlap refusal as well as the previous cell-claim errors. Other refusals remain failures, and all preview/stock/admission/commit gates stay authoritative. Eight fixed placement positions are still the search boundary; arbitrary terrain-aware placement is not added.

**Skills:** this Workshop authoring/Make path currently enforces no progression technique gate, so cards say `None required`. Do not infer a skill requirement from an item name, declared use or a tech-tree hint. Adding enforceable source skill requirements needs a separate authoring/persistence/server contract; this UI does not claim such locks exist. Uses summarize source intent and Carry/Place handling, not functional certification; a trial remains necessary for powered behavior or performance claims.

Windows verification on source based on main `086c54b`, using Chrome and the existing Visual Studio Release native engine: 55 Workshop browser and 6 navigation/Inventory/Recipes checks pass (61 total). The new browser journey makes two distinct Camp stools, verifies guest-owned native receipts and a total 5.0176 kg oak debit, keeps the Lab empty, and follows the world link to an actually rendered body with the same guest and camera facing it. A second test drains shared stock after listing and confirms a visible refusal, no installation and no spending by Make. Screenshots were inspected; JavaScript syntax, Python compilation and all 286 source registrations pass. No native solver, material law, timestep or resolution changed; the broader physics suite was not rerun. The published revision is recorded by this section's Git commit.

September 29, 2026. A recipe is a reproducible **source design**: assembly kind,
parameters, component overrides, dimensions and materials, joints, purpose and
any interaction/use declaration. Saving one does not prove that it can be made.
The same contract applies to built-in templates and designs saved by the
Workshop assistant. The latter appear in Recipes as drafts until they pass.

## Readiness gates

1. **Assemble and inspect.** Every part has a material and dimensions in metres;
   joints name parts that exist and meet. A powered item names its store,
   controls, use part and interaction points. The source is kept exactly as
   authored. The recipe list checks the current source each time it opens.
2. **Compile the same source in both places.** `workshop_recipe.assess` calls
   `workshop_fitting.check_validity` for the Workshop test room's 40 mm grid and
   the open main world's native grid. Any refusal or proposed redraw means the
   recipe is **not ready as drawn**. `Check it` can propose/apply a redraw, but
   its changed dimensions must be shown and checked again; no recipe silently
   grows to fit when Make is pressed. The grid sizes and first reason are shown
   on the recipe card. A room with no open world cannot get a world-ready claim.
3. **Trial.** Run a concrete use case in the Workshop test room, with an
   observable criterion. A static load estimate is not a run. A single trial
   supports only its recorded scenario; it does not certify all loads,
   fracture, joints or long-term performance.
4. **Stock and native preview.** Materials and goods are checked separately
   from geometry. The recipe card enables Make only with enough stock and both
   grids compiling as drawn. Make calls the same native preview and commit as
   the Lab, so live placement, existing world state, terrain and current stock
   are checked again at action time. A failed preview spends nothing.

These gates distinguish a draft, a grid-ready design, a tested design and an
item actually made in the main world. The Make button requires the two grid
checks, stock and native preview; it does not require a recorded functional
trial, so a made item can still be untested for its declared use. Grid-ready is
an admission result, not a strength claim. Material properties, joint
strength, fatigue and real-world manufacturing are outside this contract.

## Instructions for the Workshop assistant

When asked to create or finish a new item: inspect the design; declare the
purpose, components, materials, dimensions, fastenings, and interaction/use
points; call `check_validity` using the open world's grid; report every redraw;
verify that the revised source also passes the Workshop grid; run
`try_it_in_a_room` on a specific task and report measured pass/fail; call
`what_it_needs`; then save when asked. Saved items appear in Recipes even when
unfinished, with their current blockers. Never call an untested item proven,
never infer buildability from how it looks or from a low cell count, and never
promise that a successful test room run bypasses the final native preview.

## Current implementation boundary

The built-in stool now has a 50 mm top and 60 mm legs; its source passes the
40 mm Workshop and 50 mm new-game grids. In the Workshop's native room, it
also held a 100 kg resting load for two seconds without a reported break or
tip. The previous 40 mm top and 32 mm first seed variant lost the top on the
40 mm grid. Other built-in templates
that do not meet the contract remain visible for design work, with Make
disabled and the reason shown. The workshop can still explore thinner seed
variants; choosing one does not change the ready source recipe.
