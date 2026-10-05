# Phone digging and opened pits — October 5, 2026

## Report and repairs

The owner reported finger taps digging at the crosshair, water failing to enter a hole, and surface tiles remaining above removed material.

- **Touch targeting:** the shared tool scheduler now retains a finger tap's camera ray through pointer release and delayed/queued execution. A later tap replaces the single pending tap; keyboard/mouse repeats still follow the current sight, and sidebar actions retain their explicit point. Native reach, tool ownership and material admission still decide whether it can dig. Touch is identified on pointerdown so the screen edge does not turn the camera before the first pointermove. The released finger no longer leaves a hover cursor.
- **Opened roof boundary:** taking the last solid cap down to its lower interface now removes the empty trailing void from the column boundary. Before this repair, a zero-thickness cap could leave the void's ceiling reported as the top surface. That rendered a phantom tile and kept the shallow-water bed too high. Real remaining roofs still exist; this does not implement caving-in or tunnel water.
- **Older saved air caps:** an explicit strike in that column on a zero-thickness cap clears only the empty boundary, marks the selected column for collision/render/water updates, and credits no additional material. Normal saved-state restoration remains exact; there is no automatic rewriting of player worlds.

## Verification and measured boundary

Base main revision `c3e79e92`; Windows/MSVC Release, Python 3.13, Node 22 and installed Chrome. Build: `build/agent-column-terrain`, Lab off, runtime output `build/pickaxe-preview/Release`.

- Phone browser journey uses real DevTools touchStart/touchEnd at 844×390, with a tap visibly away from the crosshair. The native tool request selects the finger's column, removes its top 25 cm cube, and the drawn surface reaches the native floor. No mouse hover supplies the tap target.
- Tool client regression retains immutable touch rays through release and waiting, one pending tap, sidebar targets, live keyboard/held repeats, private pickup/refusal and receipt deduplication.
- Render regression checks all four top vertices move to the exposed floor and no old ceiling face remains after a roof-removal packet.
- Terrain regressions cover soil, sand and rock roof removal, material totals, unchanged neighbors, saved-state reopening, and recovery of an older empty cap without duplicate credit.
- Native held-tool/water experiments retain glass, oak and iron under identical conditions: 20×20 grid, 25 cm cells, soil top 0.75 m, 0.00625 m³ initial water, steps at 1/240 s. Remove one underground cube, then its actual roof cube. Water enters the exposed pit and whole native reopening retains the floor and water. Per material: ground volume residual 0 m³, water residual −1.89258331229e−15 m³ (unchanged tolerance 1e−10 m³). The retained five-cell open-channel comparison gives water residual 3.98986399475e−17 m³ and ground residual 0 m³.

The cube strike is the existing fixed-work gameplay abstraction; equal removal across these three tools does not calibrate density/stiffness/wet strength effects. The fix changes terrain topology bookkeeping, not the shallow-water equations, contact/material laws, time step or physical test tolerances. Full work/momentum/energy closure, grain/fracture/erosion, volumetric or under-roof water, and water in streamed regions remain unqualified or separate work. R3 remains paused.

Logs/screenshots are local ignored artifacts under `build/construction-preview/mobile-*` and `build/player-regression/`. No player data or credentials are committed. Physical phone/browser hardware acceptance still needs the owner's retest.

The first full six-player run passed digging, phone touch, rover and point/click. Walking A reached 90% speed in 0.533 s against the retained 0.4 s limit; the previously recorded timing gate stays open. The paid Workshop journey still referenced the removed Recipes navigation button, and now follows Build and explicitly opens Customize with AI. The old global "Needs changes" assertion also read unrelated recipe cards now visible beside the editor; it now checks the selected Build editor, retaining the paid native admission checks. The touch journey equips its tool through the authenticated Inventory API as a fixture precondition, then reloads and uses real touch input; the independent dig journey retains actual E pickup and bag controls.

Final registered repair selection: six CTest targets pass in 14.75 s (terrain, ground work, environment FFI, terrain rendering, tool client and column material integration); the preceding ten-target selection additionally passed water, valley-live and smooth/cut material integration in 108.31 s. All 40 host tool-use checks pass. No physical tolerances are widened.

The corrected final phone and paid Workshop journeys both pass (24.184 s): off-center touch → native cube removal → rendered floor; Build catalog → selected stool → explicit AI customization → paid Make → Inventory → World equip. The existing walking timing failure remains documented separately.

## Published demo

Implementation and tests are on main at `56f0d08d`. Port 18890 was restarted with the verified rebuilt executable/library and the fast-forwarded demo checkout; served World/tool scripts and three native product hashes match the verified files. The existing room store is retained and backed up locally under ignored `build/construction-preview/mobile-demo-backup-56f0d08d`. The owner saved world reopens as Live in the in-app browser.
