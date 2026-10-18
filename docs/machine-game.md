# Puzzles on the machine (/play)

October 18 wall workshop: **Sandbox → Build on a wall** creates a saved design
with a 6 × 4 m backing and a 0.62 m deep retaining lane. This is a separate
creation action beside Add New Design; the five example cards and existing
3D saves remain available. Its versioned `build_surface` declaration preserves
the wall across save, share, reopen, Undo and Clear. Clear removes placed
pieces and keeps the board. Foundation bodies cannot be picked up. A saved
surface missing its backing, guard or mounting is refused.

The front camera pans instead of orbiting. Dragging a piece changes X and
height together, at fixed Z = 0.30 m; wheel/pinch still zooms. The 5 cm grid is
on the wall. Track/seesaw rotation is about Z. Size and slope controls use the
existing direct handles and exact-value fallback. Controls on all ordinary
3D designs retain their previous axes. The wall library has 14 piece types:
wall track (length, slope, high-end stop), funnel (mouth width), catching cup
(width), peg (diameter), seesaw (length, starting tilt), marble (diameter,
material), individual gear (teeth, tooth size, tooth alignment, height), powered gear (same
size controls, motor command), battery, switch, bulb, wire, resistor and
capacitor. Electrical ratings retain the existing DC models. Wires default
to 2 m stock; clear service loops are manufactured in the XY plane near the
sockets, then native rods fall under gravity, collide and can disconnect.
The powered gear uses a declared 0.08 N m stall / 8 rad/s motor rather than
the larger bench motor; this stays inside the native coupling step bound.
The wall builder prompt uses explicit X/height coordinates and these pieces.
Reusable 3D blueprints are hidden in wall mode pending planar group placement;
wall versions and complete shared designs already preserve their assemblies.

Physical qualification: `sandbox_wall_tests.py` composes every piece, opens
native shapes and checks mounted fixtures drift less than 1 mm over 1 s at
1/240 s. The starter's 0.08 m glass, oak and iron marbles all contact each of
three tracks and the cup, with starts shifted −2/0/+2 mm (nine runs). They
settle in the cup at about 6.88–7.02 s, costing 0.29–0.34 s unpaced per 10 s
run locally. Moving the starting track away sends the marble to the ground.
The open funnel passes a marble to a cup; a falling marble visibly tips the
free seesaw while the unloaded seesaw stays balanced. The paired wall motor
test turns 2.475 rad in 2 s with both leads, and stays still with a missing
return. The wires retain their 2 m material length, sag and stay connected;
12-tooth gears with 24 mm module, 15° receiving-wheel phase and 0.30 m centre
spacing transmit torque through native contact; at 0.60 m spacing the passive
wheel stays still. The existing rectangular teeth can jam when too close;
they are not an involute profile and there is no imposed gear-ratio joint.
largest measured joint gap was 0.765 mm. Native DC source energy 1.071799 J,
shaft work 0.154358 J, heat 0.918141 J, coupling residual 0.0006994 J,
electrical residual −8.22e−13 J. These are the existing electrical/coupling
ledgers, not full-world momentum or energy closure (contacts, supports and
gravity exchange energy/momentum with the environment). No native laws or
existing level goals/tolerances changed. Exact compounds do not honour a
declaration's fixed flag; this mode therefore adds actual native fixed joints
to anchored brackets, including the clear front guard. Mounts remain ideal
supports, not a bolt failure or wall-deformation model. The guard stays out
of picking and rendering so it cannot cover the editor. Depth confinement is
physical 3D contact; runtime positions and velocities are never projected
onto the wall plane. Sources, plumbing and optics are not in this first wall
library. This is not an all-components wall mode or an exact 2D solver.

Browser checks cover desktop 1280×860 and phone 390×844 / 844×390: planar
dragging, front-facing pan, Undo, 14 thumbnails, save/reopen, Run and Reset.
Headless local checks use CPU SwiftShader under the shared GPU queue policy.
Manual desktop-to-phone rotation exposed an aspect-fit error that fresh-phone
loads did not show. Wall resize now preserves the ratio to the board's own
width/height fit, retaining the player's pan and relative zoom. The browser
regression rotates an already-open board through portrait, landscape and
desktop, checking both opposite board corners remain within the scene.

October 18 Sandbox marble journeys: the five gallery cards are now full
editable machines built in `scripts/sandbox_showcases.py`. Stations only
observe native motion, contact, electrical load and destination volumes; no
station operates a gate, teleports a marble or assigns a velocity. The four
storey tower has three descending hairpins, a low swinging door and five
dominoes. The other journeys connect a finite header tank/wheel/drum/glass
tube, solar charging/motor/contact gears/carrier, optical cord failure and a
falling weight/native fibre strand/sliding gate, and a second marble released
by a physical switch/resistor/capacitor/motor branch. Floors and rails remain
individual contact bodies on anchored supports. These are prepared apparatus,
not a new structural deformation or flexible track model.

| Example | Native parts | Nominal last station (s) | Nominal unpaced wall (s) |
| --- | ---: | ---: | ---: |
| Marble skyscraper | 103 | 13.667 | 0.94 |
| Waterworks express | 69 | 10.850 | 1.44 |
| Solar pinball factory | 68 | 7.817 | 6.28 |
| Light the fuse | 86 | 10.283 | 11.58 |
| Electric marble relay | 117 | 14.717 | 30.32 |

This final rerun shared the CPU with independent edit/browser audits; wall
times vary with that load. Measurements include another 0.25 s after all
stations complete. The native
outer step is 1/240 s, cell size 0.02 m; existing coupled rope/cable solvers
retain their finer internal steps. Reference plus two 1.5 mm native nudges
complete every station in order in all five machines. Recorded traveller
paths are 11.1–17.7 m. Widening the carrier's receiving course to 0.40 m fixes
the relay's lateral drift at a narrow track entrance; no goal volume or
numerical tolerance changed. Removing the starting marble, closing the tank,
removing sunlight, emptying the laser supply or removing the switch marble
prevents the respective downstream handoff. The optical gate's 4 N sliding
friction holds against the unburned strand's weight but releases under the
falling load, with a physical slot in the rails for the sliding bar.

Under identical tower geometry, 0.08 m spheres and 1/240 s outer steps, glass,
oak and iron all cross the three upper floors and finish the domino chain.
Their last station times are 13.667, 14.933 and 12.950 s respectively. This is
a comparative geometry/content regression, not a new material calibration or
full-pipeline momentum/energy closure result. No native laws changed; no new
conservation residual is claimed. The existing cable, optics, thermo and
electrical approximations still apply, including anchored fixtures, lumped
DC components, prescribed sunlight, simplified channel flow and the optical
source's declared internal energy feed. These examples do not demonstrate
every library family or model a device's internals. Optical/electrical chains
cost more than the tower; the table is local unpaced measurement, not a hosted
real-time guarantee.
Waterworks retains the existing ideal winding-drum constraint; its winding
lead is not a native deformable fibre strand. Light the fuse uses the native
fibre strand model for its falling-weight/gate connection. No new drum/cable,
optics, fluid or structural law is claimed by these content changes.

The gallery keeps exactly five cards and leaves saved designs/shared links
intact. Historical examples remain in compatibility tests and shared-design
imports, rather than returning as extra cards. Gallery declarations are cached
per process and copied before use; player edits cannot mutate another copy.
The prepared designs carry an overview presentation hint. Their initial view
fits the projected apparatus bounds at a higher angle, and starts with camera
following off, preventing a phone's view from moving inside the tank or a
bridge. Explicit camera turn, zoom and following controls still work normally.
Browser runs complete and reset the tower on desktop/landscape and Waterworks
on phone portrait with visible 44 px actions and no horizontal overflow.
The authored-level regression still completes every lesson's reference setup
in three runs and rejects empty setups; the archived nine-stage Chain reaction
also completes in order (both checks together: 110.473 s locally).
All five also complete through ordinary browser Run controls and preserve
their exact bases in saved versions (106.824 s together). The electrical
relay's browser run measured 20.408 s compute for 15.567 s world time,
5.650 s maximum backlog; this remains the expensive example. The Windows
engine used throughout has SHA-256
`dc3878fd08e6d8431708becd0ad49bbcce04420059bc65a73efdb27519573c5b`.
Moving a prepared native strand endpoint now translates only that body's
endpoint; moving both translates the entire construction route. Unmoved guide
points remain fixed, and the ordinary surface/solid checks still reject bad
routes. The focused gate edit regression passes in 0.198 s. The apparatus
audit uses whole-cell 6 cm translations so thin lens holders retain their
voxel phase (5 cm can legitimately introduce a 5 mm construction shift).
Its position, volume, material, reference-pruning and immutability assertions
are unchanged. Independent apparatus edits run on up to four worker processes;
the native simulations retain their original timesteps and goals.
All 419 editable apparatus groups pass those move/remove checks; together
with the rope-end regression and curated-gallery declarations, the three
checks pass in 260.145 s locally. Source registration remains 274/274 and the
client geometry/interpolation checks pass. The tighter overview fits each
body's actual bounds rather than empty corners of the combined world box.
The original combined edit audit exceeded its 600 s deadline on the Linux CI
runner during the electrical relay edits; it reported no failed edit assertion.
The same 419 independent move/remove cases now run in four disjoint CTest/CI
batches of 104 or 105 groups. Each keeps the 600 s deadline and every geometry,
material, reference and immutability assertion. Coverage checks require the
partitions' union to equal the complete apparatus list without duplication;
the aggregate publishing check requires all four batches.
The relay also exposed a browser build timeout on the Linux runner: repeatedly
checking its cable visibility graph exceeded the 90 s opening deadline.
Construction now rejects edges whose axis bounds are entirely outside an
obstacle before running the existing slab intersection test. Its tolerances,
route search, stock fitting and native cable model are unchanged. An independent
copy of the original slab oracle agrees on 20,006 boundary/random cases;
all five compiled examples have byte-for-byte equal cable path/settings data.
Relay compilation measured 4.194 s before and 2.749 s after locally. All 18
electrical graph regressions pass; no physical tolerance or loading deadline
was increased.
The repeated browser run also caught the relay marble jumping its first
hairpin after cable settling changed the carrier's arrival speed. The powered
courses now have 0.50 m physical sidewalls (other courses retain 0.20 m),
without changing checkpoints or assigning velocities. Relay runs after 2 s
and 8 s of native cable setup complete all eight stations; the last stations
occur at 13.833 s and 14.700 s. All five finish and save their unchanged bases
through the ordinary browser controls in 133.790 s with CPU SwiftShader
rendering. The electrical browser run measures 33.923 s compute for 14.517 s
world time under concurrent CPU audit load; this is still the expensive example.
The final native showcase suite passes all four checks in 283.573 s (15
reference/nudged journeys, two settled relay runs, five blocked inputs and
glass/oak/iron tower comparisons). All 419 apparatus edits/removals pass again
with the taller sidewalls in 210.200 s. These local receipts supersede the
earlier content timings; hosted CI is checked separately before delivery.

October 18 result actions: level wins offer Next level (when one remains),
Play again and All levels. Manual assembly saving stays in Sandbox under
Design → Blueprints → Save as blueprint, with reuse through Add a piece → Blueprints.
The completion actions use two columns. On short landscape
screens the score summary and actions sit side by side. The Thread a pulley
browser check verifies every result action is visible, unobstructed and at least
44 px at 1280×860, 390×844, 844×390 and 320×568, with no horizontal overflow.
The simplified win card and Sandbox blueprint save/reuse checks pass together
in 13.057 s; Sandbox reuse covers desktop and phone portrait. This is an
interface change with no engine, scoring or physical-tolerance changes.
The interpolation audit pauses with one atomic label-check/click, avoiding a
race with scoring's own pause; its measured-frame and pose tolerances are unchanged.
The Chain reaction result check now measures the visible, unclipped score and
unobstructed 44 px actions instead of requiring the older stacked card's height
to exceed 150 px. This keeps the collapse regression without prescribing one
layout's height; it does not change any physical goal or numerical tolerance.

October 17 audit implementation, checkpoint 2:

* Individual Rope anchor, Pulley wheel, Counterweight and Rope through pulleys
  pieces are in Sandbox. In **Thread a pulley**, start at a gold end ring, tap
  the wheel, then the other ring. Wheel routes have explicit Over/Under choices.
  **Raise the crate** and **Lift with less** use a moving wheel bolted to the
  crate and a separate fixed wheel. Choosing the moving wheel's Load aligns
  its hook to the selected box; the native fixed mount remains an ideal bolt.
  Neither level's goal geometry nor deadline changed. The new Raise the crate
  kit's fabrication benchmark is 1.32 GJ (1,314,787,828 J including the strand,
  rounded up), replacing its older kit's 827,064,040 J benchmark. Lift with less
  uses 1.43 GJ for its new kit (1,425,959,350 J), replacing 749 MJ. Fibre fabrication
  uses the existing generic 20 MJ/kg estimate, not a measured material property;
  it is separate from the native mechanical energy ledger. Legacy tackle pieces and v1/v2 recipes retain
  their original ideal constraints. [Measurements and limits](physical-pulleys.md).
* Blueprint v2 stores local piece IDs, internal references and explicit outside
  ports. Design → Blueprints can save a selected subset. Insertion checks the
  current inventory and native geometry, shows a group preview, and allows
  ground dragging, vertical dragging and 90° turns before one Place/Undo step.
  Existing v1 saves remain readable; copying now renames terminal references
  and transforms endpoint coordinates too. Ports require an explicit destination.
  A Load port can align the group's saved load attachment to the chosen box.
  The saved pieces are rebuilt and simulated; no assembly trajectory is replayed.
  Anonymous profile synchronization carries the same JSON through the existing
  store; a clean second browser recovered a v2 blueprint through the return URL.
  New rope ends store body-relative surface coordinates, so editing a device's
  position or size rebuilds its manufactured route from the new attachment.
  Older absolute endpoints remain readable. Runtime length, contact and tension
  remain native. Winning a lift-building lesson keeps a starter from the player's
  actual placed pieces when the library has room; automatic starters never evict
  a saved assembly. Manual saving is available in Sandbox's Design → Blueprints;
  level completion has no separate assembly-saving action.
  Levels offer only inventory-compatible groups.
* Manual switches enter Run ready at time zero. Dragging starts native time;
  pressing Run again explicitly runs without that input. Build cannot release
  a spring latch. Tanks offer Adjust tap while building, with live opening in Run.
  Already-closed hand switches start normally on the first Run. Control cards
  apply mode visibility synchronously when created or editing begins, rather
  than waiting for an animation frame. The rope lesson's interaction data also
  retains the surface anchors produced by ring selection.
  Tap adjustment cards have no release button; their availability check handles
  that explicitly. A held-resume navigation regression still verifies that a
  queued pause cannot act on the next design after changing scenes.
  Preparation progress appears only while waiting to run, outside the workspace;
  background preparation does not add height to the controls panel.
* Measured locally: 30 native rope/contact/reaction/refinement scenarios pass;
  all three routed-rope lessons pass three native runs with nudges and their
  negative controls fail. A 90° rotated assembly also reaches the same height.
  A saved starter resized for the heavier crate retains its ends and reaches
  the original Lift with less goal and deadline.
  Host (42), prepared playback (4), blueprint geometry/reference checks and
  desktop/phone group placement and Undo pass. Thread a pulley passes ordinary
  scene clicks at 1280×860, 390×844 and 844×390. Spring release, lens and tap
  controls, and the manual cannon flow pass their focused browser checks.
  These are automated checks, not timed human playtests or physical-phone FPS.

October 17 audit implementation, checkpoint 1:

* New levels and designs clear Tune/Run intent and restore Build. Tune is
  disabled until a player piece or editable Sandbox object exists. A Run-ready
  spring remains in Run at time zero; selecting it returns to editing. Device
  operating controls wait for Run, while Adjust spring remains an editing action.
* Ordinary property selection uses labelled values beside the object (up to
  three, with More for larger editors). Precision retains the exact selector.
  Editable and operating highlights also draw gold/teal edges on actual meshes.
* `machine_replay.py` records bounded native rehearsal deltas at 20 Hz and
  supplies a normal session interface for timed playback. It preserves native
  body geometry, topology events, readouts and scoring; the client still blends
  between received frames. Prepared runs are scoped to the visitor/page, complete
  compiled setup and engine digest, consumed once, expire after five minutes,
  and have 16 MiB/run and 64 MiB/server limits. Incomplete/oversized preparations
  fall back to live calculation. No new timestep, goal or physics law is used.
  Manual controls, finite-water taps, Sandbox and setups with settling cords stay
  live; the recorder is not a general device-interior or subsystem trajectory cache.
  Preparation uses the existing preview lane and cancellation; camera changes do
  not alter its key. The progress indicator reports simulated time, not an ETA.
* Measured locally: four replay identity/topology/native-goal tests and 42 host
  tests pass. Browser checks pass for new-level tray recovery at 1280×860,
  390×844, 844×390 and 320×568, and prepared native Mind the gap playback,
  edit invalidation and mode transitions at desktop/portrait/landscape sizes.
  The spring editor/release regression passes all four sizes. These results
  do not establish frame rates on a physical phone or the hosting server.

October 16 playtest follow-up (the engine, every level's goal and every test
tolerance are unchanged; Sandbox gains optional player goals):

* **Motion drawn between engine frames (October 17).** While a machine runs
  the page still requests at most 20 frames a second (`RUNNING_MS`). It draws
  the run about a frame and a half behind the newest frame (`FramePlayback` in
  `machine-view.mjs`): a frame is applied when the drawn time reaches it, and
  each moving body is drawn part of the way from the applied frame to the next
  one received, never past the newest and without prediction. When frames
  stop, the drawing stops exactly at the last one. Ropes, pins, drum ropes,
  native cords, labels and connection rings are drawn from the same in-between
  poses. A tab that is not being drawn applies frames as they arrive, so goals
  still register. This replaced the first version (October 16), which glided
  each body from its drawn pose toward the newest pose while cords, labels and
  rings stayed at the newest pose. Browser check: every drawn frame equals the
  blend of the applied and next frames to 1e-9 m, the finished machine is drawn
  at the engine pose, and Mind the gap is still won, at 1280×860, 390×844 and
  844×390 (`test_running_pieces_are_drawn_between_engine_frames_on_desktop_and_phones`).
* **Cords measured with their devices (October 17).** The server read cord
  shapes only every 0.1 s of world time while bodies came every step, so a
  cord plugged into a moving device was drawn up to 0.1 s behind it: 50 mm off
  on a battery falling 159 mm into its holder. Now, in the step after a body a
  cord is plugged into moves more than 1 mm or turns more than 0.5°
  (`CABLE_FOLLOW_M`, `CABLE_FOLLOW_COS`), the cords are read again; through
  the same fall the cord end stays within 0.3 mm of its connection ring.
  Still machines keep the 0.1 s reading. Engine time for one run, measured
  locally: Give it power 3.35–3.43 s for 4.5 s of world (3.44–3.56 s before),
  Turn the axle 0.35–0.36 s (unchanged); reading cords on every step instead
  cost 3.66–3.80 s and 0.40–0.45 s. Browser check:
  `test_a_cord_stays_on_the_battery_it_is_plugged_into_while_the_battery_falls`.
* **Server pace.** Each watched run writes one `RUN_PACE {...}` line to the
  server log (world time, the most it fell behind real time, engine and
  fracture time), and the page logs `Banjo run pace` to its console, so a
  hosted server falling behind shows up in its log. Measured locally, Mind the
  gap's own solution kept real time (6.52 s of world in 6.51 s, 0.25–0.41 s of
  engine work, never behind): its chug was the page drawing 20 positions a
  second.
* **Preview motion.** Flow-preview mechanisms blend between rehearsal samples
  (at least 0.1 s apart) instead of holding each one. A see-through copy of the
  goal body travels the rehearsed path at real speed, rests 0.8 s at its end and
  repeats. Paths store position only, so the copy keeps its starting
  orientation; it is a teaching overlay, not a new prediction.
* **Interactive glow.** The mouse-over piece you can pick up has a gold
  emissive glow; tapping empty scene briefly tints every pickable piece (1.4 s).
  Prepared puzzle parts are not included. Measured heat glow takes precedence.
  Live controls have their own colour (October 17): a switch handle under the
  mouse, or the machine a live-control card works (Release spring, a tap
  opening) while the pointer or focus is on the card, glows teal (`0x0a5a50`),
  and the cards and their buttons are teal too, apart from the blue editing
  controls. Browser check: `test_live_controls_glow_teal_apart_from_your_pieces`.
* **Add another.** After **Place**, the scene tray's **+ Add a piece** button
  pulses for 2.4 s. Opening the library with a fitted piece selected places it
  first; an unfitted piece stays selected with a message. **+ Add another**
  (October 17) is a full-width row under the piece toolbar, shown while the
  tray has something left to add after the selected piece: it places the piece
  and opens the library (Sandbox) or brings up the scene tray (a lesson with a
  small tray). Cables, wires and strings do not count as a next piece. It is
  hidden on screens 500 px tall or less, where the extra row reached the
  camera controls and covered Place (CI, Sun lesson at 844×390); there the
  library still places the piece first. (An earlier
  **+** inside the toolbar row was removed because it widened the editor past
  the screen edge; a row of its own keeps the 250 px width.) Browser check:
  `test_add_another_places_the_piece_then_offers_the_next` at 1280×860, 390×844
  and 844×390, and in Point the laser.
* **Library filters.** Category chips (44 px) replace the dropdown, with a
  **Recent** chip for the last eight Sandbox pieces added (browser storage,
  optional). The last search and category persist across visits too
  (`banjo.pieceFilter` in browser storage, October 17).
  Search matches every typed word against the name, description, category and
  a short list of everyday words (ball, board, rope, cog, lamp...).
* **Build ▸ Tune ▸ Run.** A three-step switch (44 px buttons, small arrows
  between the steps) sits in the middle of the bar above the scene on every
  screen. The mode is derived from state: Run while a machine runs or
  has run (world time above zero), Tune while a selected piece is on its
  adjustment controls or Tune was chosen, otherwise Build. Tune hides the scene
  tray and opens the last edited piece; Build after a run is **Restart with my
  pieces**. **Run** is the start button itself (`#start`); there is no
  separate Try It! button. It reads **Pause** while the machine runs, then
  **Run** again: it continues a paused run and, after a run is over, runs the
  setup again from the start. A missed run keeps it in place; the result card
  still offers Try again and Ask for Help. Live device controls (for example
  Release spring) are unchanged.
* **One bar above the scene (October 17, owner request).** From 900 px wide
  the bar is one row: Reset, Controls/Help (and Design in Sandbox) and Undo on
  the left, Build ▸ Tune ▸ Run in the middle, and the camera controls (turn,
  tilt, zoom) on the right, so the scene gains the height of the camera row
  that used to sit over its top. Redo appears beside Undo only when there is
  something to redo. Narrower, the bar holds Reset, the switch and the tabs
  (the tabs drop to a second row in Sandbox and below 360 px), and the camera
  row stays along the top of the scene. Browser checks:
  `test_header_and_camera_share_single_rows_without_an_idle_banner` (one row of
  44 px buttons at 1280×860), `test_build_tune_run_switch_follows_and_changes_what_the_player_is_doing`
  and `test_scene_and_action_bar_above_it_share_one_layout_on_desktop_and_phones`
  (the switch centred, clear of Reset and the tabs, at 1440 to 320 px wide).
* **Move grip and local guides.** A 36 px gold grip marks the centre of a
  movable selected piece (display only; the scene drag is unchanged). Axis
  guides extend 3× the piece's size (0.8–4 m) unless Precision controls are open,
  when they keep their 50 m length.
* **Simple plank handles and Precise (October 17).** A selected plank shows a
  gold ball on each end (22 px on a 44 px target) and the middle grip, and
  nothing else: its arrows, axis lines and +/- length handles wait behind
  **Precise**, a switch beside Move that opens the Precision controls. Dragging
  an end ball sets the length from the point on the plank's line nearest the
  pointer, with the other end kept where it is (the middle moves by half the
  change; about the middle when the level does not let the plank move). Arrow
  keys on a focused end change the length 2 cm at a time, so the middle moves
  one whole 1 cm position step and the other end stays exactly put. The plank
  is built of 2 cm cells, so its drawn ends sit on that grid; an end that stays
  put stays within half a cell. On a plank short on screen the balls sit at
  least 50 px from the middle so the grip stays reachable. Browser check:
  `test_plank_end_balls_change_its_length_from_one_end_and_precise_brings_back_the_arrows`
  at 1280×860, 390×844 and 844×390.
* **Result card on short screens (October 17).** The Level Complete card uses
  its compact layout on screens 430 px tall or less as well as 820 px wide or
  less. At 844×390 the scene is about 230 px tall and the card 160 px; with the
  large title the energy line was cut off below it (measured on Windows fonts;
  CI's Linux fonts happened to fit).
* **Blueprints (Sandbox).** **Design → Blueprints** saves the design's placed
  pieces (not its prepared base objects) under a name, up to 20, in the
  anonymous profile; blueprints merge across devices by id. **Add a piece →
  Blueprints** adds a copy centred on the view's target point.
  `blueprintPlacements` (machine-view.mjs) renumbers `your <piece> <n>`
  references within the group after the existing pieces; names outside the
  group are kept. The combined setup goes through the server `check` first; a
  refused drop changes nothing. Saving preview/simulation results with a
  blueprint was not implemented: a blueprint's behaviour depends on what it is
  combined with, so the engine always rehearses the whole machine.
* **Player goals and challenges (Sandbox).** `machine_game.sandbox_goal`
  accepts one `in_zone` goal per design: a named body, or `piece` (the first
  placed piece of that kind), a centre within 50 m and sides of 2 cm–5 m. It is
  added as the first station and reported, never scored or ranked. Measured:
  a marble dropped from 0.4 m over a 0.4 × 0.3 × 0.4 m zone reaches it; one
  dropped 1.5 m to the side does not (`tests/machine_game_tests.py`
  `SandboxGoal`). **Copy challenge link** packs the base and goal without the
  author's pieces; a goal about one of the author's named pieces is refused for
  sharing. Challenges are not yet listed in the level menu.
  A goal can instead be **light reaches a target** (`lit_at`, October 17): a
  fixed 12 × 12 cm plate, 2 cm thick, its face where the view is centred and
  facing the camera (the nearest of ±x, ±z, or up when the view looks down
  steeply), on a 4 cm post to the ground, with a 2 × 2 cm light sensor on its
  face. The station is the same `lit_w` check the optical examples use, at
  0.2 W. A target inside another part is refused with "set it in open space".
  Measured in **Find the focus** (`tests/machine_game_tests.py` `SandboxGoal`):
  a target in the laser's beam facing it is lit at 0.017 s; one 0.5 m beside
  the beam, or in the beam facing away, is not. Browser check:
  `test_sandbox_light_goal_puts_a_target_facing_the_view_and_the_engine_measures_it`.

## Starter lessons: ball, block and string (October 17)

A playtester found **Raise the crate** (block and tackle) too early. Three
one-idea lessons now come first in Level 1: Mechanics, so the catalogue has 37
challenges (eight chain-reaction levels, twenty-six piece lessons, three
advanced electronics activities). The Level 1 order is now: Tip the lever,
Roll the ball, Fill the trench, Mind the gap, Swing on a rope, Spring lifts the
load, Raise the crate, then the earlier sequence. Later ranks move down by three;
chapter order and the other relative orders are unchanged. Their minute
estimates come from author review only. They were added after the October 13
blind probe and are not in its receipt; their cards say so.

The lessons use the existing core `marble`, `block` and `link` builders and
the ordinary level stands. No goal, tolerance or engine law changed. Native
outcomes are decided by gravity, contact and joints:

| Level (id, rank) | What it teaches and the player's work | Reference solution, measured (3 nudged runs) | Misplaced setups, measured (all 0/3 wins, no engine errors) |
|---|---|---|---|
| Roll the ball (`easy-roll`, 2) | Gravity rolls a ball down a slope. Place one 4 cm iron marble (position only) on a fixed oak slope; it must roll into a cup on the floor within 3 s. | Marble at x = −0.7 m: in the cup at 1.017 / 1.033 / 1.017 s. Par 6.60 MJ (6,593,156 J marble fabrication). | Default x = 0.1 m on flat floor (authored wrong setup), and on the slope's line but 0.3 m to the side: it rests where it is set. |
| Fill the trench (`easy-block`, 3) | A fixed block provides structure. The 6 cm iron ball rolls off a ramp along a table toward a 0.30 m wide, 0.30 m deep trench. The player sets a 0.26 × 0.30 m concrete block in the trench and stretches its height (0.04–0.50 m). Ball in the cup within 4 s. | Block at x = 0.05 m, 0.30 m tall (top level with the tables): in the cup at 1.500 / 1.467 / 1.483 s. Par 53.4 MJ (56.16 kg concrete). | 0.20 m tall (authored wrong setup: the ball drops into the hole), 0.40 m tall (a wall stops it), no block, and the default block set down on the far table (also a wall). |
| Swing on a rope (`easy-rope`, 5) | A string carries tension, never compression. A trapdoor's own weight opens it at the start. The player places the **ring marble** on it, uses **Attach** to tie it to the end of a cantilever beam with a `string` (native `tie`: a maximum distance, slack below it) and it swings into a raised zone within 3 s. | Ring marble at x = −0.5 m; string from the beam end (0, 1.40, 0) to the top bar of the marble's ring (−0.5, 0.855, 0): in the zone at 0.683 s in all three runs (October 17; the plain marble tied at its top took 0.667 s). Par 7.06 MJ: the 0.282 kg ring marble only, since the tie has no modelled mass. | String tied low on the trapdoor stand (authored wrong setup: it stays slack and the marble falls), no string, and a string tied to the beam 0.4 m along from the marble instead of 0.5 m (a shorter swing that does not reach the zone). |

The **Attach** tool, previously Sandbox only, now appears in a level whose tray
offers a join. Its card offers only the join kinds that tray allows (this
lesson: String). A level tray's single join is counted like any other piece.
This is a presentation change; the `link` builder, the tie joint and compose
validation are unchanged. Focused verification: both engine tests of
`tests/machine_game_tests.py` restricted to these three levels pass in 2.741 s
on `build/linux/banjo_live_world_run`, plus `node tests/level_intro_test.mjs`
(37 introductions) and the source-registration guard. The browser suite was not
run for this change; its catalogue counts now expect 37. Remaining caveats: the
rope lesson's tie is an ideal massless string with no rendered sag or
breaking load; the minute estimates are unprobed.

October 16 setup guidance: the Try It!/Reset and Controls/Help action bar
precedes the scene on desktop and phone. Try It! uses secondary styling until
the lesson’s required piece counts are placed, including wires. Counts expose
no solution positions or adjustments; incorrect and incomplete setups remain
testable. Sandbox has no required-piece gate. After Undo/rebuild, retained
geometry cannot be selected until the replacement session matches the setup.
The updated layout and battery/wire flow pass on desktop, portrait and
landscape phones in 101.701 s. The layout also checks 320 px width; action
buttons stay at least 44 px and incorrect placements still enable emphasis.
Two cable removal/Undo flows, including a deliberately delayed replacement
world, pass under two-core Windows affinity with SwiftShader in 150.599 s.


October 16 electrical cord rollout: visible graph wires, solar charging cords
and legacy heater/cannon circuit leads now use native articulated Jolt cables
in levels and Sandbox. They sag and contact solids during placed setup, retain
that state on Try It!, and unplug electrically under their declared load limit.
Stock length and copper area affect actual mass and resistance; excess wire
forms a physical service coil. Shared sockets have separate plug seats.
The scene's cable selection/deletion follows the native cord, including solar
leads, rather than the old schematic curve.
Outside a connection ring, an exposed placed cord takes precedence over a
socket's enlarged touch halo. Tapping the ring or explicitly starting a new
connection still chooses wiring. The browser probe now checks actual cord
visibility and socket overlap before choosing a deletion point.
Cable taps retain their initial press hit until release, so a settling cord
does not select the exposed case behind it. Moving more than the existing
click threshold or starting a second touch cancels the tap. Three browser
flows (held taps, solar removal/Undo and camera dragging/prepared leads) pass
in 76.813 s across desktop and phone orientations. The complete Linux
machine-world suite passes 38 checks in 49.442 s; the native binary is unchanged.
All removable cords inside a tap's hit area now offer a labelled chooser,
rather than requiring their projected distances to be within 6 px. The probe
chooses an exposed, nearest cord; held taps, removal/Undo, solar cords and
camera dragging pass four flows in 97.595 s. The falling battery test compares
its input and cord endpoint in one captured frame after the original 10 cm
drop; a later physical bounce cannot replace that measurement.
Under a two-core Windows affinity with SwiftShader rendering, the full battery
wiring/removal/gauge flow and same-frame falling-input check pass on desktop
and phone orientations in 74.047 s. This mirrors the CI CPU/rendering budget;
it does not claim bit-identical Windows/Linux trajectories. The connected-wire
length test waits for completed placement and native readiness before using
the placed-wire button, retaining its hit target and exact 10 cm increment.
The follow-up precision-tap probe waits two native setup seconds after
rebuilding/Undo, while its early held tap retains a 0.35-second minimum.
One hit test per candidate replaces repeated whole-scene raycasts that could
delay a dispatched press while the cord moved. The read-only setup probe exposes
the existing server setup-time measurement; gravity, retention, clocks and
electrical consumption are unchanged. All three removal/Undo/camera flows pass
under two-core Windows affinity with SwiftShader in 123.000 s, including stronger
endpoint assertions after the repeated removal.
The solar-cord remove/Undo/live-edit flow also passes under the same two-core
software-rendering budget in 78.186 s with the setup-time wait and single-hit
probe. No cord is frozen to make these interaction checks pass.
Cable fitting rejects pairs whose axis intervals are already farther apart
than the required clearance before computing exact segment distance. All 39
authored/example compiled declarations matched the previous implementation;
one sequential local construction sample fell from 4.59 s to 1.49 s.
This affects construction only, not native contact or timestep behavior.
Archived v1 paddle switches put fixed jacks at y=7 cm, z=9 cm to clear the
moving deck. Glass/oak/iron deck comparisons at 240/480 Hz completed the same
lamp goal in 0.433–0.467 s; electrical residuals were below 1.8e-13 J.
Their old near-side negative could rebound off a real lead into the paddle;
the negative rehearsal now uses a clear 50 cm lateral miss. The goal, time
limit, friction, and successful placement remain unchanged.
Legacy circuit conversion separates coincident nominal plug positions when a
single body contains both source and load, at 12 mm seat spacing. Other
connections retain their existing positions. All 39 authored/example compiled
declarations match before/after. The ball-on-plate contact regression now builds
and retains its original closure timing/at-rest assertions. The live current
oracle includes the sum of geometry-derived copper resistances at its original
three-decimal precision; electrical and heater-ledger bounds are unchanged.
Wire proximity picking yields to solid cases unless the actual visible cable
mesh is in front. The older falling battery holder puts its wire jacks on the
front of its metal pads, leaving the top contact faces clear. Six native checks
(glass/oak/iron pack housings at 240/480 Hz) powered the lamp for at least 34 of
40 sampled intervals; electrical residuals stayed below 4.4e-12 J over two
seconds. This is a fixture routing fix, not a change to contact or pullout laws.
Sandbox library thumbnails use an isolated construction context rather than
depending on removed gallery cards.
Rebuilding a setup keeps the last drawn scene until the new engine session
has returned successfully. Picking up the solar panel after a run no longer
clears every body while waiting for its replacement world. Browser regression
holds that response to check the retained geometry across all three viewports.
Cable fitting reuses an identical visibility graph while trying different
slack-coil sides within one connection. It never reuses answers across edited
machines or endpoints. Comparing all 34 authored solutions plus the five
examples produced identical compiled declarations before/after this cache;
the local comparison took 11.21 s before and 4.96 s after (one sequential
construction sample, not a hosted runtime benchmark).

**Knock it off** and **Chain reaction** use 32 V heater supplies to account for
their real wire loss. Their target zones and deadlines are unchanged.
Sandbox now shows five marble journeys: **Marble skyscraper**, **Waterworks
express**, **Solar pinball factory**, **Light the fuse**, and **Electric marble
relay**. User designs remain at the top; the full piece library remains
available. Historical designs and shared links retain their component support.
See [the cable model and qualification](mechanical-cables.md) and
[the release level audit](level-release-audit-2026-10-16.md).

Placed cords also advance under native gravity during the placed setup, before
Try It!, at 1/240 s steps in 30 Hz batches. The puzzle clock, electrical solve
and battery consumption remain paused. Editor fixtures hold the machinery;
Try It! removes them and keeps the cables' native poses and velocities in the
same session. Editing a placement rebuilds its construction, then the new cords
settle again. Live setup cords remain visible over prediction overlays.

October 16 spring access: a placed spring now has **Adjust spring** beside
**Release spring**. This uses the same selection/editor path as clicking the
coil, retains its setup and opens the length buttons with proposed force and
stored energy. It remains available after Try It! readies the paused latch;
it cannot actuate the latch, and disables once the machine runs or is released.
The lesson changes relaxed length/preload at a fixed held length and 200 N/m
stiffness. It does not add an independent tension/stiffness setting; Sandbox
retains its full editor. No native model, goal, tolerance or solution changes.

The public test site at e4fa9d9 was manually played in ordinary Chrome: visible
length buttons changed 20 cm / 0 N / 0 J to 70 cm / 100 N / 25 J proposed push
and storage; selecting the placed coil reopened the controls, and Try It! then
Release spring completed the actual lift with three stars. Screenshots record
the buttons/values and completed result. At verification, production remained
0017397 and did not contain these explicit spring-length buttons.

The inherited e4fa9d9 CI failure was the 320 px camera-row swipe: held zoom
buttons disabled native touch panning. They now allow horizontal panning while
the existing pointer-cancel path stops repetition. Its native-tests and seven
other browser batches had passed; the aggregate job correctly failed alongside
that browser batch. Complete new-checkpoint CI is still required for promotion.
Three focused Ubuntu/SwiftShader browser scenarios pass in 51.170 s: direct
spring reopening on four layouts, unchanged compression/placement and the native
lift; the formerly failing camera-row swipe; and held adjustments, zoom, drag
cancellation and limits. Source registration and JavaScript/Python syntax pass.
The native binary is unchanged.
The ready-state follow-up disables Adjust spring while a replacement native
session is opening. A deliberately gated open verifies the disabled state
before allowing construction to finish, then reopens the editor and completes
the lift on all four layouts (25.638 s). This prevents an immediate adjustment
from being replaced by the still-finishing Try It! setup. Manual Chrome checks
also verify the placed Adjust/Release buttons and reopening from 100 N to 90 N
and back, with the latch held; phone screenshots record both states.

October 15 phone gear-card follow-up: Move, Place and cancel share one row
with 44 px touch targets on a 156 px card. This removes a row of height so
the editor can clear the target wheel while showing the alignment feedback.
The four-viewport size/height/control check passes in 14.724 s. The gear-win
regression additionally checks that the card leaves both wheel centres visible;
it passes on desktop, phone portrait and landscape in 27.256 s, including the
original native win. No engine or physics thresholds change.

October 15 gear alignment and held adjustments: compound toothed wheels now
expose their compiled cylinder centre and hinge axis as the primary working
point, rather than a post's upper face. Nearby wheel rings turn green for
parallel planes within 8 mm; their centre connectors require both matching
planes and centre heights within 8 mm. The editor reports the largest depth
and height offset in centimetres. Plane alignment does not claim tooth contact
or a win: the native moving preview remains authoritative. Geometry tests
also distinguish reachable teeth, root overlap and separated rims. Guides
use compiled shapes/joints and continue working after arbitrary part renaming.
Aligned but separated teeth show **Teeth apart**. An engine-rejected overlap
shows **Clear the overlap — move apart**, rather than staying at Checking.
No placement, material, joint law, goal or stored solution is changed.

Holding numeric +/− controls, spring-length buttons and zoom magnifiers starts
repeating after 350 ms, then once per 100 ms. Taps keep their one-step action.
Release, cancellation, lost capture/focus, hidden/removed controls and beginning
a gold-handle drag stop repetition. Numeric ranges remain clamped; a drag or
held press cannot add an extra click when released. Directional movement-pad
buttons retain their existing held behavior.

Four focused Ubuntu/SwiftShader browser cases pass in 77.321 s: geometry/colour
feedback and the gear's native win, four-size gear controls, mouse/touch holds
across gears/lenses/batteries/springs, and the spring's native latch/lift. The
two-case follow-up passes in 43.424 s, checking actual ring material colours,
held zoom, touch cancellation, limits, release and switching a hold into a drag.
Pure view tests and two compiled-geometry/working-point checks pass. The native
gear replay check passes in 2.320 s: replay/ordinary runs each took 0.2 s;
all three nudged runs reach the original goal at 1.750, 1.633 and 1.750 s, while
missing/misplaced gears fail. This editor change adds no conservation model;
the native binary and all physical thresholds remain unchanged.
The final spacing-message regression passes on desktop, phone portrait and
landscape (27.913 s), checking both gap and overlap feedback before the native
win. Ordinary Chrome checks and screenshots cover all three layouts. Syntax,
view helpers and the 271-source registration guard pass. Full checkpoint CI
remains required before production promotion.

October 15 controls simplification: the bottom-right collapse caret and its
hidden-panel mode are removed on desktop and phones. Controls, Help and the
Sandbox Design tab switch the always-open dock; Try It!, Reset and the scene's
Undo remain reachable. Heat inspection keeps the dock available too. Browser
checks now exercise those ordinary tabs rather than the removed toggle.
In short landscape views optional wire callouts may yield to the lamp rating;
every displayed callout retains the same edge, leader and non-overlap checks.
No physics, goals or numerical tolerances change.
Eight focused Ubuntu/SwiftShader browser checks pass in 181.143 s across desktop,
phone portrait/landscape and the 320 px layout, covering tabs, dock layout,
Reset/Undo, wire leaders, switch inspection, solar wiring and the spring lift.
The laser-burn inspection check also passes on all three layouts (38.742 s).
JavaScript/Python syntax and the 271-source registration guard pass. Ordinary
Windows Chrome checks confirm the cleared corner and working spring buttons;
screenshots cover desktop and phone portrait/landscape. The verified engine
binary is unchanged; complete checkpoint CI still runs before promotion.

October 15 spring-control discoverability: selected springs show a labelled
**Spring length** value in centimetres and direct **− 5 cm / + 5 cm** buttons
in their edge editor. These change the declared relaxed length; the latch
still holds the compressed plate, and the existing gold handles give finer
changes. Buttons disable at the declared limits. The length controls remain
available when a placed spring is selected again. The length buttons also
stay visible and usable with the Help tab selected. Lesson filtering still
hides unrelated stiffness, materials and orientation; Sandbox retains its
full editor. The model, latch, goal and energy scoring are unchanged.
The browser regression exercises both buttons, limits, unchanged placement
and compression, reselection, fine dragging and the native five-centimetre
lift at desktop, phone portrait/landscape and 320×568. The updated test passes
on Ubuntu/SwiftShader in 21.296 s, using the previously verified native
engine. JavaScript/Python syntax and the 271-source registration guard pass.
Ordinary Windows-browser clicking updates the visible length and stored-energy
reading. No new physical law or conservation result is claimed by this UI fix.

October 15 navigation qualification: `c156ac6c` passed seven browser batches,
including the corrected wire audit. Its solar lift check read the hidden
guide while entering the Sandbox example. All 52 browser navigation call
sites now share a helper that waits for a new document epoch and completed
document load; same-document fragment navigation retains its existing epoch.
Gallery button checks also wait for the actual create/open action to finish
its native rebuild, rather than accepting the previous ready clock. Four
focused Ubuntu/SwiftShader cases pass in 47.203 s: solar lift and its Sandbox
example, saved-design return URLs/cookies, Help navigation, and leaving during
a deliberately delayed world open. This does not wait for the engine during
navigation, so the last cancellation test retains its original behavior.
These are harness changes only. The full exact-checkpoint CI remains required.

October 15 moving-wire snapshot correction: `f8c5e955` CI caught another
cross-frame audit read: the portrait label endpoint and its wire midpoint,
read in separate CDP requests, differed by 6.647 pixels while the preview
advanced. The audit now captures labels, body bounds, view bounds and every
compared wire midpoint in one render callback. All assertions then use that
single snapshot. The two-pixel endpoint tolerance and zero-overlap checks
are unchanged. No application or physics behavior changes in this correction.
The corrected audit passes three consecutive Ubuntu/SwiftShader runs in
40.449 s, each covering desktop, portrait, landscape and changed perspective.
The redundant four-batch local audit was stopped after CI exposed this
remaining measurement race; it is not reported as a complete passing run.
The next exact checkpoint must pass the complete CI suite before promotion.

October 15 rendered-frame qualification: the follow-up exposed two more
fixture races, a touch aimed before connection framing finished and a layout
snapshot mixing the last DOM label position with the next camera position.
Ghost inspection and completed drags now await two rendered frames. Scene
socket taps await framing before aiming and paint before reading a choice.
The label audit samples its geometry together in a render callback; its
zero-overlap and leader-position assertions are unchanged. Navigation waits
require the destination element to exist. The five affected Ubuntu/SwiftShader
cases pass (101.763 s), including the strict 8 cm river-lift assertion.
These are browser-harness changes; the application simulation and controls
are unchanged. Complete checkpoint qualification is still required.

October 15 duplicate-PR qualification: the exact staged `f249755e` source
passed all 146 browser scenarios and 158 native groups before promotion.
Its parallel PR merge build exposed three timing-sensitive fixture cases:
the wiring hint was read before repaint, Help navigation dereferenced a new
page's element before it existed, and the river gate was sampled one display
frame before reaching the asserted 8 cm rise. These checks now wait for those
same states. The gate still must rise at least 0.08 m; native goals, materials,
timestep and tolerances are unchanged. This follow-up changes tests and the
dated release notes, not application behavior. Its own complete checks remain
required before promotion.
All three affected cases pass on Ubuntu with the published Linux engine and
SwiftShader (46.478 s), including desktop and phone views. Source registration
and the unchanged promotion-guard tests pass. Linux tests use
`GIT_OPTIONAL_LOCKS=0` when run from WSL against the Windows checkout so a
timed-out read-only Git status cannot leave an index-refresh lock.

October 15 final meter sizing correction: candidate `6210faae` passed all 158
native CTest groups and 145 of 146 browser scenarios on Linux; its remaining
failure was the capacitor meter in phone landscape. A pending label could be
positioned close to the right edge, then measure longer text against that old
position. Its automatic width stayed at 75.7 px and wrapped to 113.9 px tall,
so no clear placement fit. Power and water edge meters now use intrinsic text
width, still bounded by their existing maximum width and collision checks.
The regression forces that old narrow position, waits for repaint, and keeps
the same visibility, native 4 J storage, win and reset assertions. The forced
Linux reproduction fails before the correction (34.093 s) and passes after
(19.553 s); the committed regression also passes on Windows (16.129 s).
All eight focused Ubuntu/SwiftShader readout scenarios pass (170.399 s),
covering the capacitor regression, wire gauges/edge leaders, bulb sizing,
live cable power, solar/winch readings and connections, timed receiver fill
and diverted-water collection. JavaScript syntax, the view-module test and
the 271-source registration guard pass. Exact-revision CI remains required.
No physics model, target, deadline or numerical tolerance changed.

October 15 Linux qualification follow-up: the first parallel run passed the
native regression job and browser batch 4, but exposed a hidden capacitor
meter on Linux landscape, immediate post-click reading races, and accumulated
loopback preview quotas. The capacitor edge meter now shows voltage and
stored energy, with current retained in its tooltip and electrical readings.
Independent browser scenarios reset their preview/optical request history;
the public limits and each scenario's limits stay unchanged. Explicit waits
check the hidden preview legend, flowing-current dots and removed placement
leader after the browser paints them. All physical thresholds stay unchanged.
Failure traces stream immediately and screenshots are retained in CI. Eight
smaller browser batches cover the same 146 scenarios with the same 1200-second
deadline, keeping the two catalogue sweeps from crowding out later cases.
All seven affected scenarios pass locally with SwiftShader (88.410 s), including
capacitor storage/reset, contact battery, marble-switch current, named wheel
load, edge callouts, solar lift and water diversion. Source registration,
JavaScript syntax, the view-module test and two promotion-guard tests pass.
The candidate still requires all exact-revision checks before promotion.

October 15 Linux release follow-up: software-rendered CI found four failures
in three browser cases after their Windows runs passed. The capacitor case
now closes the completion overlay before inspecting its edge meter; the wire
case waits for its adjustment button to be painted; the lens case waits for
both native power and the matching visible reading instead of accepting the
previous trace while the replacement is scheduled. All three pass locally
with SwiftShader enabled. No physical assertion, goal or timeout was loosened.
The first complete local CI batch also passes, and its measured request
counts remain below the fixture's preview allowance.

CI now compiles and runs all non-browser CTest checks in `native-tests`, while
the complete browser scenarios run on independent Ubuntu runners.
Each builds this revision's engine; no shared Render CPU or runtime artifact
is involved. The existing 1200-second browser-batch deadline is retained.
The required `build-and-test` check is a fail-closed aggregate of source
registration, native tests and every matrix result. Its gate was checked
against success/failure/cancelled/skipped dependency outcomes. The promotion
script's required check names and exact-revision rules are unchanged. A full
green run of this candidate remains required before production promotion.

October 15 final local browser qualification: all 146 distinct scenarios pass
across measured batches and affected-case reruns, with the unchanged Windows
engine SHA-256 `35230eb7ee76ee0209ff034558ea6110061babd072635561b98d988b92c3f67a`.
This includes all 34 level pages at desktop, portrait and landscape sizes.
The last three fixture corrections reveal snapping in Changes, use the
labelled object choice beside overlapping terminals with wiring mode off,
and check the complete river connection text in its narrower edge card.
The former 200 px full-width button expectation is now the required 44 px
touch target plus unclipped text and viewport bounds; physical deadlines,
goals and tolerances remain unchanged. The 42 HTTP checks, two host admission
checks, source guard and view-module test pass. Exact-revision Linux CI and
the clean running test checkpoint remain required by the promotion guard.
The dated notes below record earlier checkpoint status, including failures
subsequently resolved by this qualification; interrupted runs are not counted
as successful full-suite runs.

October 15 release qualification: the compact camera row no longer covers
Expand controls or Inspect switch/heat. Socket choices open above scene tools;
dimension handles avoid the editor's current position. Switch inspection keeps
the completion card in the scene when returning to the overview. The bulb's
goal label includes its shared supply limit when a separate wire card cannot
fit; optional wire readings still yield to objects and required controls.
The real-engine chain inspection, bulb supply/size, live power/current, empty
Sandbox battery, lens focus and manual cannon cases pass on desktop and phones.
The 42 HTTP checks and two host admission checks pass. Browser scenarios now
use a fresh owned Chrome profile for each case, reveal Settings in Changes, wait for the next paint
before hit testing, and close result overlays before operating scene controls.
Legacy fixtures use Sandbox for unrestricted rotation/charge settings instead
of expecting those unrelated controls in a lesson. Physics assertions, physical
deadlines and numerical tolerances are unchanged. Full CI must pass on the
published candidate before promotion; the interrupted parallel Windows run
reported exhausted loopback connections and is not a successful full-suite result.
The later stall at visitor 21 was the isolated HTTP fixture's 20/hour creation
allowance: fresh scenarios intentionally need separate visitors. The browser
fixture now permits 1000 creations while production retains its existing
20/hour limit. HTTP error diagnostics include status and path without query
credentials. Fresh profiles also bound graphics/module state between cases.

October 15 release-candidate controls: selected-piece and live device cards
dock at scene edges with dotted leaders at desktop widths too. Undo remains
visible when disabled; only unavailable Redo is hidden. Completion cards start
54 px below the top of the scene, beneath the camera row, leaving the lower
machine visible. Changes contains Settings (snapping, precision and level
instructions), and the following Share header link copies a canonical level
or serialized Sandbox setup URL. Its real href also supports normal link
actions. Narrow headers retain the Banjo logo and TEST badge while shortening
the text brand when needed. Actions such as Attach close Settings so the
player can operate the scene.

The test-only busy panel offers Use this browser, explicitly ending the other
test run and opening the current setup; it never changes saved profiles. The
button stays in the first row so short landscape views cannot clip it below
the explanation. A displaced page offers the same action. The production API
rejects takeover, and invalid placements are checked before any run is closed.
Host admission serializes pending opens, preventing concurrent requests from
exceeding the pool limit. Frame reads use the existing independent lock.
Focused browser checks cover desktop edge callouts (1280/1920 px), persistent
Undo, Settings/Share, precision editing, native receiver wins with raised
completion cards, and busy/takeover including short landscape. The 42 HTTP
checks cover test-only takeover and invalid-request preservation. Broad
browser release qualification is in progress; the prior failures remain a
production-promotion blocker until fixed. No native laws/goals/tolerances changed.

October 15 compact chrome update: Banjo and navigation share one header row;
phones show the shorter Help and Changes labels with the original accessible
names. The TEST badge still fits on a 320 px screen. History, camera arrows
and zoom occupy one 44 px touch row at the top of the scene. Unavailable
Undo/Redo buttons stay hidden. Zoom +/- remain available when the slider is
omitted on narrow phones; the row can scroll horizontally if both history
actions fill a very narrow view. Idle time-zero status is hidden, while
building, running, connection and capacity errors remain visible. Meters and
terminal framing reserve the top row even when the status banner is hidden.
No physics, goals or scoring changed. The new real-engine browser regression
checks 320/390 px portrait, 844 px landscape and desktop: one-row header
including TEST, 44 px unobstructed controls, Undo/Redo and visible running
status. Existing phone placement, direct-editing, wire-callout, capacity/retry,
Recent Changes and How to play scenarios pass. Recent Changes now checks
accessible navigation names because phones intentionally use shorter labels.
Broader CI failures recorded below remain separate from these focused checks.

October 15 session cleanup: opening Levels or the Sandbox library saves the
current draft and releases its native world. Back to a level rebuilds its
placed setup at time zero. World opens and closes are serialized per page;
an open abandoned during navigation is closed before a later one can start.
An old polling response cannot overwrite the new screen. This prevents a
page's own rebuild from competing for the test host's single simulation slot.
Other active players still receive the host's capacity protection. Busy
messages distinguish capacity from invalid geometry and name Try It! as the
retry action. No physics, goals or capacity limits changed.
Verification: three new real-engine browser regressions pass, including a
deliberately delayed close, navigation during an open, preserved placements
on return, and busy/retry without closing another player's world. The existing
retry test passes at desktop/phone sizes; the phone callout test also passes.
The host capacity unit test and source registration guard pass. Broader CI
on the preceding staged revision has unrelated browser failures (including
outdated property fixtures and covered placement controls); those remain
unresolved and production promotion remains blocked by the CI guard.

October 14 phone callout update: selected-piece editors and live device control
cards dock to a left/right scene edge on phone portrait and short landscape
views. Portrait editors use a 136 px card, with Move/Place on separate rows and
all three gear measurements visible. Thin dotted, noninteractive SVG leaders
connect cards to projected objects. Editors and dimension handles reserve the
prepared apparatus; electrical readings keep their existing edge callouts.
Narrow phones use two rows of perspective buttons and a smaller bottom dock
while editing. The one-time Add framing includes the lesson apparatus so a new
piece can be lined up with its target; manual zoom and camera gestures remain
available. Sandbox does not zoom out to include its whole machine on Add.
This changes presentation only: native physics, placements, goals and scores
are unchanged. The small-screen callout regression checks edge docking, clear
ghost/seesaw hit targets, leader anchoring after turning the view, and hiding
the leader after Place at 390×844, 320×568 and 844×390. Existing control fixtures
now reflect the already-published Controls → Settings location, hidden exact
sliders and Mind the gap’s length-only lesson controls.
Verification: seven focused Chrome scenarios pass in 69.221 s, exercising
desktop, phone portrait/landscape, direct dimension gestures, gear sizing,
lens/receiver edits and the spring latch/native lift. The registered client
geometry test, JavaScript/Python syntax, diff check and all 271 source
registrations pass. Native Windows SHA-256 remains
`35230eb7ee76ee0209ff034558ea6110061babd072635561b98d988b92c3f67a`;
no new physical calibration or conservation claim is made.

October 14 lesson-control audit: all 34 authored levels now have explicit
`lesson_controls` metadata for every tray piece in `level-onboarding.json`.
The level loader validates coverage and unknown/duplicate keys. The client
uses `lesson_knobs` in the common visibility predicate, so the scene chooser,
exact fields, height handles, rotation buttons/shortcuts and Square it up all
follow the same list. Opening Precision controls does not restore Sandbox
properties. Fixed one-choice/prepared numeric values are not presented as
adjustable. A single property needs no redundant property dropdown; its gold
handles, toggle or named choices remain beside the piece. Move-only pieces
retain placement and exact position controls. Gear Teeth/Radius/Height stay
together. Sandbox has no lesson whitelist and retains the full editor.

Physical switches, spring latches, heater clips, required wiring and water-wheel
load connections retain their scene actions. Help's hint/coach property lists
exclude unrelated controls and prepared constants; hints are instructed to
teach only those controls. This is presentation metadata, not a restriction on
saved declarations or a change to forces, materials, defaults, recipe identities,
goals, deadlines, scoring or tolerances. Earlier shared recipes adapt the list
to their original apparatus, including old gear pairs, contact batteries,
starting switch state and integral water supplies.

Placement across the available ground axes remains available unless a tray
already lacks that axis. These are the remaining device adjustments/connections:

| Level | Device controls |
|---|---|
| Tip the lever | weight: Starting height (m) |
| Roll the ball (added October 17) | marble: placement only |
| Fill the trench (added October 17) | block: Height (m) |
| Mind the gap | plank: Cut to length |
| Swing on a rope (added October 17) | ring marble: placement only; link: Attach picks both ends of a string |
| Spring lifts the load | spring: Relaxed length (m) |
| Raise the crate | tackle: Counterweight preset (kg), Rope ratio, Counterweight height (m) |
| Find the focus | lens: Focus / face radius, Diameter (m) |
| Cut the cord | knife: Pivot height (m), Arm length (m), turn |
| Bounce to the target | mirror: Mirror angle |
| Gentle first launch | catapult: iron counterweight side (m), cocked angle, aim |
| Cut it down | knife: Pivot height, Arm length, turn |
| Lift with less | tackle: counterweight (kg), pulleys, hung at height |
| Bounce the beam | mirror: turn |
| Turn the big wheel | gear: Teeth, Radius, Axle height (m) |
| Turn the axle | motor: direction, throttle |
| Light the bulb | bulb: bulb size |
| Finish the loop | wire: scene connection endpoints |
| Limit the voltage drop | resistor: resistance (ohms) |
| Close the switch | switch: placement only |
| Marble turns on a light | switch: placement only |
| Give it power | battery: voltage (V); wire: wire thickness, scene connection endpoints |
| Series or parallel? | wire: scene connection endpoints |
| Store the charge | capacitor: capacitance (F) |
| Charge in the sun | solar: tip, turn, Post height (m); power_cable: scene connection endpoints |
| Sun-powered lift | solar: tip, turn, Post height (m); power_cable: scene connection endpoints |
| Catch the sun | solar: tip, turn, height; power_cable: scene connection endpoints |
| Fill the receiver | water_tank: tap opening (%) |
| Wheel in the river | water_wheel: placement only |
| Pour onto the paddles | water_tank: tap opening (%), fixed outlet height (m) |
| River-powered lift | water_wheel: rope to gate |
| Water opens a gate | water_wheel: wheel radius (m), load to lift (optional); water_tank: tap opening (%), fixed outlet height (m) |
| Divert the water | water_chute: aim |
| Up she goes | steam: Firebox (kW) |
| Heat to release | ignition: coil preset, attached target; wire: scene connection endpoints |
| Chain reaction | ramp: Top height, Run, Foot height |
| Knock it off | cannon: Bore height, turn, tip; wire: scene connection endpoints |

Measured: all 34 reference setups compile to exactly the same native machines
when initialized with Add's defaults and edited only through the lesson list.
The same comparison passes for 47 current/legacy seed-42 recipes. Existing
native goal checks pass all 34 levels in three runs each, with the empty setup
checks where runnable, in 32.397 s. No new conservation or material law is
claimed by this UI work. Browser audit covers all authored non-connection
tray devices on desktop and six representative levels on phone portrait and
landscape, including opening/closing Precision controls without changing values.
The audit, ordinary gear completion on all three layouts, and full Sandbox
catalogue property reachability pass together in 68.434 s. Connections have
separate ordinary socket-drawing regressions. The final unit/declaration suites pass 50 tests in 19.112 s. The
current/legacy seed-42 and authored machine-equivalence checks also pass in
1.491 s. Ordinary capacitor/heater/shared-challenge flows pass; spring and
lens/receiver scene edits pass including 320×568 after keeping only the title
in that smallest dock (GO and Level instructions retain the full briefing).

The wiring audit found that gauge choices were inside the hidden geometric
editor while drawing a lead. They now stay in Controls before the second
socket click, only for lessons with gauge in their control list. Short wide
views allow wider edge callouts and put rated/goal power together, preserving
all values so the bulb voltage fits below the scene-corner buttons. Full
voltage/gauge wiring, unobstructed edge readings and the existing crowded-scene
Controls fallback pass in 27.335 s, with the original 8.8/11.9 V and 1.6/3.0 W
expectations unchanged. Wire test selection now uses that already-existing
Controls button when a callout intentionally yields to the scene. Syntax,
renderer, introductions and source registration (271 sources) pass. Final authored-control, full Sandbox catalogue and four-layout
gear-field browser checks pass together in 59.024 s.

October 14 simultaneous gear controls: three 44 px minimum scene buttons show
Teeth, Radius and Height together. Teeth/Radius select their property and open
the existing named presets directly; Height activates the compiled vertical
handles for drag or one-increment +/− taps. All displayed values, including
Radius after a tooth-count change, update from the proposed declaration.
Accessible descriptions include the current values. The generic adjustment
selector moves into Controls → Settings → Precision controls for gears;
secondary settings retain their existing editing paths. Native preview
playback remains automatic. No declaration, preset, cost, material, physics
law, goal, scoring or tolerance changed.

For screens below 360 px wide, selected gear editing reserves more scene room
by temporarily hiding the dock's repeated task sentence (the level name stays).
The clock occupies the clear lower-left corner. The existing one-time Add
camera fit also backs away, with the angle/look-at point preserved, checking
up to 20 times for controls to clear the full assembly's projected bounds,
capped at 40 m.
Later manual zooms remain manual; this is camera placement, not mechanical
seating or a force applied to a neighbouring wheel.

Browser verification passes all three direct edits and visible, unobstructed
44 px targets at 1280×860, 390×844, 844×390 and 320×568, in 6.880 s. Native
lesson completion and the saved Sandbox example pass with the field check in
28.160 s. The full 44-device catalogue/settings audit passes in 36.184 s;
gold tooth handles and named/material choices also pass. Renderer/syntax and
source registration pass. These UI measurements add no new physical calibration
or conservation claim; existing gear measurements below still apply.

October 14 hint prompt follow-up: a live local failed-gear request returned a
dismissible model reply, but combined several adjustments and recommended the
largest tooth module without evidence that it fits. Hint instructions now ask
for one next action, adding a missing tray piece before prescribing settings,
using player-visible labels and avoiding unsupported numeric recommendations.
Gear context explains the Radius/module relation and actual contact requirements.
Regression checks these instructions, forwarded measured run, unchanged level
declaration, private-solution isolation and suppression of model placements in
hint responses; four focused prompt/editor/heater tests pass in 0.078 s. A second
live local request identifies the missing bridging gear and asks the player to
add one. Dismiss works and the response remains in Help. This improves the supplied context; it does not validate model
advice in the native engine or guarantee future answer quality.

October 14 Help and trial layout update: Try It! (and Pause during a run) is
160–240 px wide and horizontally centered directly below the 3D view. Reset
sits left; smaller tabs sit right. On narrow phones and phone Sandbox layouts,
tabs use a second row to keep all touch targets clear. Help contains only the
question/response area and a subdued Report a bug disclosure. Guided-clue and
automatic-placement buttons are no longer presented. Controls → Settings now
holds exact/snap controls, level instructions and Share. Opening Settings
temporarily hides the dock's goal row, reserving room to reach the settings;
the level introduction and scene remain available. This supersedes earlier
Help → Settings locations and guided-clue UI descriptions in this document.

A missed run presents Try again and Ask for Help. The latter makes an explicit
hint request with the current placements, editing context and measured
`last_run`, including bounded station, joint, circuit, pour and power-source
readouts; it does not rerun the machine or apply model placements. A modal
opens with a thinking state, then plain-text reply or provider error, and
Dismiss/Escape closes it. The reply remains in Help. A pre-existing typed
question and the retry selection are retained. Failed runs do not call the
model automatically; no new scoring, native-law or tolerance changes occur.

Browser verification passes the typed-help and failed-attempt provider fixture
on desktop, phone portrait/landscape and 320×568, asserting one model call,
measured failed-run context and unchanged placements. The unavailable-provider
case preserves the setup and retry. Radius/settings and failed-help checks pass
in 34.893 s; shared layout, Sandbox word building/sharing, plain Help and
provider-error checks pass in 50.949 s; heater attachment/wiring/completion
passes in 31.809 s. Final gear/radius/help checks pass in 51.189 s; measured-run
context and retry-selection regressions pass in 58.783 s after adding the
bounded readouts. The fixture verifies routing/behavior, not a real provider's
answer quality. Intro, renderer and source-registration guards pass. Physical
gear comparisons from the preceding checkpoint remain unchanged.

October 14 gear placement preview: selecting an individual gear automatically
plays the native rehearsal, including the drive, proposed and target wheels.
The beside-piece readout shows the target's measured cumulative `turned_deg`
(or the selected axle in Sandbox), explicitly marked Preview. Editing remains
at world time zero; replay poses never feed back into the engine. Ordinary
gear controls are Teeth, Radius and Axle height. Help → Settings → Precision
controls exposes tooth alignment, material and bearing friction. Radius is a
display of the existing discrete module choices, not a new native property:
`(teeth / 2 + 0.7) * module_m`, the radial distance to a tooth's outer face.
Changing it also changes tooth spacing; teeth and radius therefore interact.
Saved declarations and existing 16/24/32 mm module presets remain unchanged.

The flow observer now includes native hinged compound-body poses, capped at
32 bodies, with sampling interval `max(0.1, rehearsal_seconds / 180)` seconds.
No contact, torque, drive, mass or energy law changed. Gear replay and ordinary
run station and native readout records match exactly in regression (0.22 / 0.23
wall seconds for a two-second rehearsal). Three nudged solutions still reach
180° at 1.750/1.633/1.750 s; empty and axially misplaced controls fail. Native
light/water/current preview regression also passes; the final gear regression
passes in 2.498 s. Browser checks pass in 104.853 s for radius
choices, three-layout native-pose replay and completion, the full 44-device
control audit and river lift preview; large handles/named choices pass in
4.974 s. No goal or tolerance changed. This adds no contact-driven seating while dragging, calibrated
involute teeth or tooth failure model. Existing per-material measurements and
full-pipeline conservation limits remain in the gear measurements below.

October 14 Divert the water simplification: `water_controls: false` is public
UI metadata for this lesson. It omits the optional source-valve card; Try It!
starts the existing open finite supply automatically. The introduction and
first hint explain that sequence. Sandbox and Fill the receiver keep their
source/tap controls. This does not modify the source, recipe policy, native law,
saved valve behavior, chute, collector or goal: 4 L at 1 L/s, with 3 L retained
for 0.5 s before the existing 8 s deadline. No turnable-tap model was added.

Native regression: all three nudged own solutions reach the goal at 4.567 s;
the empty and reversed-chute cases fail, in 1.902 s total. Browser regression
passes in 18.089 s: automatic flow and completion on desktop, phone portrait
and landscape, no valve before/after the run or Reset, plus retained Sandbox
valve and receiver tap. Intro coverage for all 34 levels, syntax and source
registration pass. The engine binary and physical tolerances are unchanged.

October 14 on-object adjustment audit: the dropdown-adjacent `↔` grip is removed.
All adjustable numeric ranges and numeric presets use 56 px gold +/− handles
in the scene: tap one schema increment, drag along the projected direction, or
use arrow keys for one increment without changing X/Z placement. Geometry
handles keep their compiled face/optical anchors. Joint and rating properties
that move no face use nearby scene handles and proposed numeric feedback,
without pretending the solid changed shape. When the axis has no clear phone
space, handles take the nearest unobstructed space and show a thin leader to
the working point. Handles also avoid the selected object’s projected bounds;
readouts yield to them. Help demonstrations follow the handle’s projected direction.
Exact fields remain in Help → Settings; choices and references retain named
pickers and toggles. Connected wires anchor length controls to their drawn route.

Spring relaxed-length arrows and a dotted measurement use the compiled spring
joint’s endpoints, axis and `rest_m`, including turned springs. This annotation
does not stretch the latched coil, release a restraint, modify a placement,
change forces or feed preview poses back into the engine. Proposed relaxed
length, push and stored energy are visible beside the piece. The held coil
still spans its actual joint endpoints. Coordinate comparisons allow sqrt(3)
micrometres for the existing independently rounded endpoint coordinates; native
goal and energy tolerances are unchanged.

Browser auditing covers all 44 current placeable catalogue devices and their
reachable setting modes (including contact-pack batteries, paddle switches,
marble placement and elbow planes), plus connected-wire length. Numeric touch
targets must be at least 56 px and reachable without a toolbar grip. Spring
tap/drag, unchanged held length, latch readiness, native release and box lift
pass on desktop, phone portrait/landscape and 320 px portrait. Lens curvature,
tap opening, keyboard steps, named gear sizes and guided Help have regression
coverage. Geometry-only ghost comparisons verify annotations cannot alter the
compiled setup. This is an editor change, not a new physics model or conservation
claim; the tested native binary is unchanged.
The final four interaction regressions pass in 52.341 s and the seven-device/
layout/Help regression group in 93.925 s. The readout follow-up passes in
7.342 s: its fixture now finishes connecting before changing a placed wire’s
gauge, matching the ordinary controls. In the 167 px landscape canvas it uses
Collapse controls to make room for all three callouts; a crowded canvas still
hides readings that cannot fit, rather than placing them over buttons or bodies.
The spring/geometry annotation checks pass in 10.907 s. JavaScript syntax,
machine-view checks and source registration pass. No native source or solver
binary changed; no full-pipeline conservation claim is added.

October 14 load-chooser follow-up: **Wheel in the river** hides its optional
load reference because this spin-only lesson has no separate load. The knob
remains in the schema for saved recipes; no default, native goal or law changes.
Sandbox water wheels call it **Load to lift**. Generic scene reference controls
open a named list of the same allowed connections, with **Pick in scene** to
dismiss the list while retaining direct picking, and **Cancel**/Escape to exit.
Choosing a name changes only the declared reference, using the existing native
composition and validation. A wheel’s own bodies are excluded from load choices.
If there is no movable load, the disabled chooser explains adding a weight or
loose box. This does not add rope attachment or collision laws.

Reference names, instructions and adjustment feedback now wrap rather than
using ellipses. Named targets have 56 px hit areas; Pick in scene and Cancel
are at least 44 px. Open pickers reposition on viewport changes. Browser checks
cover the spin lesson on all three layouts, existing river workbench save/
restore and gate lift, named gate selection with an engine-reported drum joint,
empty-load guidance, self-exclusion, direct motor/gear picking and the live tap.
The named/direct regression pair passes in 14.439 s, including viewport rotation.
The direct-picker fixture now clears its inherited Sandbox first, so a
prior water example cannot collide with its new gear. Native physics models,
energy/goal tolerances and saved load identities are unchanged.

October 13 Chain reaction follow-up: ramp X/Z placement now accepts −10…10 m
instead of X −2…0.5 m and Z −0.3…0.3 m. The same 1 cm control increments,
grid/object snaps and native overlap/support refusal remain. Mouse and touch
drags beyond both old limits can be placed and selected again. A new
ramp begins at its clear declared defaults instead of the view centre, where
it could overlap the cannon. An off-axis
ramp still fails because its marble misses the seesaw. Dimensions, rotations,
goal zone (centre 2.75/0.1/0.6 m, size 1/0.2/0.8 m), six-second deadline,
budget and energy par are unchanged.

The prepared cannon’s declared powder charge is reduced from 1 g to 0.75 g.
The former nominal setup crossed the goal but finished at X 3.4866 m, beyond
its 3.25 m edge. The new nominal/two nudged iron-box runs reach the goal at
1.562/1.587/1.592 s and finish at respectively (2.7904, 0.0503, 0.6039),
(2.6590, 0.0505, 0.4222), and (2.9808, 0.0509, 0.5664) m. Each was followed
through 6.5 s, with actual cannon-ball/block contact and no target-exit on X.
This edits the authored charge, not propellant, contact, drag or friction laws.
No velocity is prescribed, no decorative brake is added and no goal is enlarged.

The engine’s setup search now narrows its sampling bounds for broad ramp
position controls using the first declared contact milestone’s public body
geometry and ramp reach/orientation. Player ranges are unchanged by search,
and private answers are never consulted. The existing wrong-start regression
still finds a native solution within its unchanged 48-run budget (two runs in
this measurement). Disjoint proposed search bounds fall back to the ordinary
property range. This is search assistance, not a physics snap or force.

Scoped browser checks pass at 1280×860, 390×844 and 844×390 (42.785 s): free
ramp drags, placement/reselection, off-axis failure, visible switch contacts,
current preview and repeated completion. The complete authored-level oracle
passes: all 34 reference setups win 3/3 with the same nudges, and empty setups
do not win. Together with the new search isolation and material comparison,
that verification batch took 35.012 s. Source registration and Python syntax pass.

Comparative cannon impacts use the same 10 cm target block, iron shot, 0.75 g
charge, 20 mm lattice and 1/240 s timestep. Native initial masses are glass
2.5 kg, oak 0.7 kg and iron 7.87 kg. Nominal final X is 3.7236, 5.4295 and
2.7904 m respectively; the level is tuned for its declared iron box, not all
materials. Runs take 0.90/0.79/0.90 s wall time. Maximum electrical residual is
4.78e−12 J; reported thermal-ledger residuals are 1.04e−6, 8.20e−7 and
4.47e−7 J. These subsystem receipts and initial masses are not a full-pipeline
momentum/energy audit. Fixed support reactions, contact/numerical loss separation,
propellant/gas calibration, fragmentation and oak grain/plasticity assumptions
retain the limitations described in the physics roadmap. No native model changed.

October 13 Heat to release usability follow-up: adding its coil shows one
large **Clip to cord** action beside the declared goal cord. The unrelated
box attachment rings no longer compete in this lesson. This action uses the
same explicit target declaration and native fixed mount as the existing ring;
it does not pre-place, power or heat the device. Sandbox retains its material
attachment rings. The winding toggle now displays **Warm · 12 Ω** or
**Hot · 0.12 Ω**. Its introduction names Clip, Hot, Place and the two supply/
heater connections; legacy shared heaters retain their earlier explanation.

**Show me what to do** provides the next attachment, winding, placement,
feed/return or run interaction from the current editor and circuit declarations,
without needing a provider connection for this simple heater setup. It draws
the existing guide over a supplied visible control/socket and never performs
the action. More complex circuits and shorts still use model diagnosis.
Typed hints receive the unplaced editor state and the same heater instructions;
basic setup hints also work without a provider. Visible two-choice toggles are
now available as coach targets. No private solution is supplied to either help
path. No native law, material, goal, deadline, timestep or energy par changed.

The browser checks cover the actual Clip button (reachable, at least 56 px
high), Warm/Hot toggle, guided feed/return connections and native completion
on desktop 1280×860, phone 390×844 and landscape 844×390, with the provider
disabled. General guided-help and unavailable-provider regressions also pass
(three methods in 37.833 s). Four scoped help-context/isolation tests pass;
the additional typed-help browser path passes all three layouts in 32.613 s.
If a connection ring is outside the usable scene, setup help points to zoom
out instead of guessing an inaccessible endpoint.
The native heater regression confirms three nudged wins for the correct setup
and zero for unattached, missing-feed, missing-return and warm setups
(18.057 s). This is interface/help validation against the existing measured
thermal model, not a new conservation or material calibration claim.

October 13 choice-control follow-up: previous/next value arrows have been
replaced with named choices opened by tapping the current value beside the
piece. Choice targets are at least 56 px high; selection updates the proposed
declaration and closes the picker. Escape or clicking outside dismisses it.
It stays associated with the selected piece and closes when selection ends.
Material and other non-geometric choices use this picker; binary toggles and
the three wire-gauge buttons keep their existing behavior.

The gold geometry grips are now 56 × 56 px, with collision clearance adjusted
to the larger hit area. Discrete numeric dimensions such as gear teeth also
accept a tap: **+** chooses the next allowed size and **−** the preceding size,
with MIN/MAX at the bounds. Dragging remains limited to the allowed presets;
a drag does not add an extra tap step on release. Keyboard arrows still change
one increment without moving the piece. Geometry and rays still come from
the server/native engine; these controls assign no simulated force or success.

Five scoped browser checks pass in 50.390 s for size taps and named material
choices on desktop and both phone orientations, the unchanged gear win,
allowed-size dragging, keyboard increments, lens editing and the receiver tap.
The final picker-position regression passes in 4.612 s; picker coordinates
must be finite, clear the header and remain within the viewport. Pickers stay
inside the scene when their full size fits, using the viewport for short or
crowded layouts. The keyboard fixture now chooses a visible geometry grip
after the native guide refresh, rather than requiring an off-screen endpoint.
Geometry helper, syntax, introduction-content and source-registration checks
pass. No native law, scoring tolerance or physical calibration changed.

October 13 level-introduction update: every challenge opens a dismissible
overlay with its name, **You’ll place**, **How it works**, **Your goal** and one
**GO** action. The three descriptions use the available tray and a reviewed
mechanism explanation for each of the 34 authored levels. They read only the
public level data and do not use private solutions or exact solution settings.
GO dismisses the card; it does not start native time or add a piece. Escape
also dismisses it. Retry and Reset keep it dismissed; choosing another level
shows that level’s introduction. Sandbox designs do not force a level briefing.
**Help → Level instructions** opens the same card again.

Goal markers remain in the scene, but their large instruction sprites no longer
render over the working area. In **Wheel in the river** and **River-powered
lift**, the green current region remains visible while the paddles can be
positioned without text across them. Native goals, dimensions, laws, timing
and recorded outcomes are unchanged. The dialog keeps GO visible on desktop
and phone portrait/landscape; longer text scrolls within the card in small
viewports. Its position follows the scene while staying within the viewport.

The unit check covers all 34 introductions, public goal thresholds, retained
spring descriptions and isolation from private answers. Five focused browser
checks pass in 46.437 s: introduction/dismiss/reopen/reset on nine level and
viewport combinations, the two river lessons on desktop and both phone
orientations, spring/tackle lifts and guided-help overlays. The river fixture
now returns from precision settings to Controls and waits for the adjacent
rope button to become reachable before using it. Syntax, view geometry and
source registration checks pass. No native physics or energy validation was
changed or newly claimed by this interface-only checkpoint.

October 13 spring follow-up: **Spring lifts the load** now has a visibly coiled
spring, a narrow iron push plate and a manual latch. The oak box remains on
its fork cradle; the spring has no joint to that box. Place it beneath the box,
increase **Relaxed length** from 0.2 m, then press **Release spring** beside it.
**Try It!** readies this lesson without starting its timer; Release spring
starts native motion and the unchanged one-second goal clock. It must raise
the same box 5 cm. The correct 0.7 m setting reaches the goal at 0.100 s in
all three nudged runs; no release, the 0.2 m setting and a one-metre sideways
miss each win 0/3. No goal or deadline was relaxed. Its measured construction
energy par is now 137,614,000 J for the changed assembly.

New Sandbox springs use the same latched contact assembly, with **Held spring
length**, stiffness, damping and rotation. Move/Turn and the property grip stay
beside it. Stored joules and push newtons update as proposed settings; live
spring readings come from the engine. The aiming guide follows the push face
and the declared slide axis. **Latch and lift** demonstrates it with a separate
box. Missing construction versions in old saves still select the original
directly attached spring; shared v1/v2 challenges also retain their apparatus.
The coil and latch marker depict ideal native constraints, rather than a
resolved wire or latch material model. Comparative measurements are in
[the spring audit](sandbox-mechanics-measured.md#latched-contact-spring-october-13).

October 13 direct editing follow-up (supersedes the dock editing descriptions
below): **Try It!** is the primary left-hand action; compact Controls/Help tabs
sit on the right. Pause and Continue keep their existing behavior. A successful
**Level Complete!** result is a bounded overlay within the expanded scene, with
score, Play again, next level, Close and optional Energy details. Failure has only a compact Try again button over the bottom of the scene. Closing or changing tabs restores the dock.

Every visible, supported property of a selected tray piece is available in the
small toolbar beside its geometry, rather than only the former primary-knob
subset. Move/Turn/Place stay there, with a property chooser, numeric ↔ grip and
current proposed value. Binary choices are labelled toggles; longer choices use
previous/next buttons. Wire gauges retain their explicit thickness buttons.
Load, battery-store and motor-axle references have **Choose … in scene** actions;
only the same compatible references accepted by the exact controls are accepted.
Defaults can be restored, and Escape cancels choosing. Existing terminal rings,
power sockets and heater clips retain their direct connection gestures.

Gold 44 px dimension grips project the existing geometry-derived change arrows.
Dragging along the indicated direction changes the declaration in its existing
increments, including discrete numeric choices such as gear teeth. Keyboard
arrows also change one increment. Grips yield to the toolbar and fixed camera
controls and disappear when an anchor is off-screen; the toolbar grip remains.
They preserve pointer capture and keyboard focus during asynchronous preview replacement. Keyboard arrow events stay with the handle and do not also invoke the scene movement shortcuts. The three-case keyboard/lens/gear follow-up passes in 35.81 s; the keyboard regression requires one declared increment and unchanged X/Z placement. Touch
value editing disables browser scrolling on the grip. These are editor
annotations and inputs, not extra forces or prescribed motion in the simulation.

The lens property is **Focus / face radius (m)**. It changes the existing spherical
face radius; no independent or scripted focal-distance law was added. Its gold
grip is anchored to the front face in the compiled optical setup. The native laser
trace and lens outlines update with curvature, shape, diameter and orientation.
Non-geometric properties (voltage, resistance, capacity, friction, stiffness,
damping, fuel and flow settings) use the adjacent grip/current reading rather
than pretending their numbers are visible geometric dimensions.

**Fill the receiver** exposes tap opening beside its tank. Its other lesson
parameters are still deliberately locked: the task is collecting 3 L in 5 s
from the fixed four-litre source. Sandbox tanks expose the full declared settings.
Freshly rebuilt electrical endpoints are framed into the usable scene below the clock when needed, keeping viewing angles unchanged.
Once placed, live tap-opening sliders, other tank-valve toggles and catapult
release buttons sit in cards beside their actual device, including live status
and errors. They send the existing native control requests; live changes retain
the saved initial declaration, and reset behavior is unchanged. Cards use the
projected device bounds and avoid camera tools and the selected editor. Multiple
cards can still compete for limited scene space in very large Sandbox builds.

Audit of the ordinary piece controls:

| Pieces | Settings available beside the selected piece |
|---|---|
| Plank, ramp, track, shelf, bend, funnel | Length, slope/drop, height, width/radius and available end choices |
| Marble, weight, loose block, dominoes | Size, material, start/mounting settings, quantity/spacing where declared |
| Knife, lever, flip-flop, door, trapdoor, pendulum | Arm/length, starting angle, limits, hinge friction, direction/material where declared |
| Mirror, lens, solar panel | Height, aim/orientation, aperture/width; lens shape and face radius; solar battery-store selection |
| Spring, tackle, gear, flywheel, trampoline | Declared dimensions, load/ratio, teeth/module/phase, stiffness, damping, friction and materials |
| Battery, bulb, resistor, capacitor, motor, switch, coil | Declared ratings, presets, start state/direction/throttle; axle/load or clip connections where supported |
| Water tank, wheel, chute, collector | Declared size/height, fill/opening/flow, side/load/discharge settings; conditional settings follow the existing model |
| Straight pipe, elbow, reducer, scaffolding | Bore and outlet radii, length/slope, bend/plane, support, dimensions/material |
| Cannon, catapult, steam, airflow | Existing bore/fuel/start, restraint/loaded state, heat/boiler side and airflow direction/speed/width |
| Editable Sandbox base objects | The existing position, orientation, dimension and material properties exposed by that object's editor |

Controls that remain outside the nearby piece toolbar, and why:

| Control | Location and reason |
|---|---|
| Exact coordinates, precise numbers and reference strings | Help → Settings → Precision controls: a fallback for exact input or an occluded connection point |
| Delete a selected piece / occasional disconnect action | Precision controls: deliberate secondary actions, keeping the normal placement toolbar small |
| Ground type and river flow | Sandbox ground controls: change the shared environment rather than one selected device |
| Preview timeline, playback speed and snap preferences | Help → Settings: affect the whole scene; both snaps start enabled |
| Save, restore, share and build-from-data | Design/Help: operate on the whole design rather than one object's physical adjustment |
| Fixed challenge apparatus and locked lesson parameters | Intentionally not editable in a challenge; use Sandbox for the freely editable build |

This interface work changes no native laws, recipes, goal thresholds, energy
accounting or physical tolerances. Native preview and goal behavior use the
previously verified Windows binary, SHA-256
`997b02d2b9f4594dbb575eeca38c17777a7ce6ec74e8832f97d265f8974464a9`.

The 28 catalogue/placement tests pass in 15.79 s, including existing glass/oak/iron geometry and mass checks. The UI catalogue audit covers all 44 placeable non-wire families; electrical and power wires have separate connection/gauge coverage. JavaScript syntax, client geometry and source registration (271/271 sources in 41 CMake files) pass. Final browser receipts: 14 focused scenarios pass in 157.76 s; the five
retry/layout/wiring/inspection scenarios pass in 102.64 s. Coverage includes
1280×720/860, 1440×900, 390×844, 844×390 and 320×568. The new direct
lens/tap test drags mouse/touch grips, checks the native trace request, changes
lens shape with the toggle and physically fills the receiver to win; the live
tap/axle test verifies actual native commands and unchanged saved initial values.
The gear handle accepts only the existing tooth sizes. Save/reopen, typed/guided
help, energy comparisons and last-piece retry are checked. Earlier runs found
narrow-view overlap and clipped footer actions; the affected cases pass after
fixes. These are scoped UI checks, not a rerun of the complete native physics
suite or a new conservation/calibration measurement.

October 13 guided help: **Show me what to do** is the first action in Help on
challenges and Sandbox. A live local provider check returned a real tray highlight
without changing the setup. Its first reply combined adding, resizing and placing;
the prompt is tightened to explain only the highlighted interaction, use visible
landmarks instead of XYZ prose and request fewer than 180 characters. This is a
model instruction rather than proof of universally correct teaching advice.
The read-only guide contract regression still passes.
Suggested Move gestures project the editor's grab plane with its retained grab
offset, rather than projecting an arbitrary proposed body center. The browser
fixture follows that actual annotation with mouse/touch and checks the resulting
X/Z placement within the existing 2 cm input tolerance; no state is assigned by
the guide and no physical win is implied.
The expanded two-test guide/availability rerun passes in 6.58 s.
The live public follow-up named an internal knob key and confused choosing a
property with changing its value. Target context now includes the exact menu
labels, selected property and ↔ handle's current reading. The prompt distinguishes
those interactions and asks for overlap at bridge supports. Browser regressions
verify that these displayed labels reach the provider, alongside the read-only
overlay checks; a hint remains advice rather than an engine-verified solution.

Guided help is available on
challenges and Sandbox. A separate read-only model request sees the tray and its
rules, compiled layout, current edit/mode, supplied target catalogue, previous
hint and last measured run; it never receives the authored solution. It returns
one brief action and a target, optionally a suggested scene drag or two sockets.
The client outlines that target and animates a pointer along the proposed path.
It does not dispatch input, change placements, rehearse a setup or assign success.
Model-suggested geometry is advice, not a verified physical solution. **Next hint**
refreshes the advice from the current state; **Close** and Escape remove it and
restore the task. A level change invalidates pending answers. Typed drafts remain.

The server returns only reply/guide/usage, dropping any model-proposed build or
placement fields. Targets must belong to the supplied catalogue. Drag coordinates
are finite numbers within the existing workspace bounds; controls use local
bindings rather than model-generated selectors, HTML or code. The usual public
chat quota and configured model apply, with an 1800-token output limit for this
short response. Missing configuration reports an explicit unavailable message;
it leaves Next hint, Close and ordinary play usable. Reduced-motion preferences
replace pointer motion with a stationary marker.

Measured with a deterministic provider fixture: the three-step add/drag/adjust
flow at 1280×720, 390×844 and 844×390 highlights the actual target, advances the
pointer animation, preserves typed text and every placement/edit value, and lets
the user click through the overlay. The Sandbox/missing-provider test preserves
its base and placements and recovers on retry. Both tests pass in 5.30 s; all 28
catalogue/placement tests pass in 16.75 s, including the read-only coaching contract
and existing glass/oak/iron geometry checks. The shared layout and existing typed
Sandbox-builder regressions also pass. These fixture measurements validate the
interface contract, not the quality or latency of live model advice. No engine,
physics law, energy accounting, goal or tolerance changes are part of this update.

October 13 shared layout follow-up: desktop, phone portrait and landscape now
use a full-width scene above one bottom dock, without a desktop sidebar.
Controls keeps the task and active adjustment together. Help already contains
the brief, so Help and Design use the space without a duplicate task row.
Tabs and Run/Pause/Reset remain visible while the active pane scrolls. Collapsing
the dock expands the scene and keeps its run bar. Short landscape views put the
adjustment, proposed value and fit status on one row with a complete 44 px handle.
Solar connection buttons can fit beside camera/history tools when both outer
edges are occupied; their leaders still point to the actual port, and the body
bounds stay reserved. This is layout only, with no engine or physics changes.

Measured in Chrome at 1440×900, 1280×720, 390×844, 844×390 and 320×568:
scene and dock both span the page width, remain within the viewport, and expose
Run and the complete adjustment handle. Collapse, tab changes, failed-run retry,
direct mouse/touch editing, reset/undo, Sandbox library, saved versions and tab
rotation are checked by the focused browser regressions. Electrical and solar
wiring still use scene endpoints. Source registration and client geometry checks
pass. The former always-visible task assertion on Help now checks Help's actual
brief instead, since duplicating that row would consume the landscape pane.
Physics goals, tolerances, energy accounting and the verified binary are unchanged.

October 13 beginner controls update (supersedes earlier interface descriptions):
the goal uses larger, wrapping text beside the scene. Selecting a placed piece
opens a small adjacent toolbar with Move, Turn, Place and cancel. The property
selector and drag handle now sit in the scene toolbar (see the direct editing follow-up above).
Mouse/touch drags move the declaration on the ground, turn it, or change the
selected numeric property in its declared increments. The separate ↔ handle
changes the same property, including non-geometric electrical ratings; proposed
ratings still update beside the device. Engine ownership of simulated bodies is
unchanged. Sliders and exact values are a fallback in Help → Settings, alongside
grid/object snap toggles. Both start enabled for each opened level/design.
Camera turn/tilt buttons sit above zoom; Undo/Redo remain in the scene.

After a failed run the engine pauses and the result contains only Try again.
It rebuilds the retained setup at time zero, then selects the last edited piece.
Reset still clears a challenge, with Undo available. Used challenge tray cards
disappear; selecting a placed object uses its rendered solid. Whole machine,
Restart with my pieces and the Puzzle details disclosure are removed from the
ordinary game interface. Existing inspection-return controls remain separate.

All 34 challenges (37 since the October 17 starter lessons) stay visible in four chapters: Level 1: Mechanics (including
spatial optics), Level 2: Electricity, Level 3: Water, Level 4: Heat and chain
reactions. Chapter order supersedes the former global difficulty ranking;
relative ranks within chapters retain that audit's ordering. The time estimates
are historical estimates, not timings measured with this interface. Physics
recipes, goals, tolerances and energy pars are unchanged.

The layout assigns the adjacent toolbar before placing edge readouts, so
mutual avoidance cannot make Place move under the pointer. Proposed numeric
ratings use a compact edge badge; complete ratings remain in Controls. Objective
meters get priority when labels compete for space. Both wire gauges remain
available as touch targets in Controls if two edge badges cannot fit. Camera
controls leave attachment points clear, and a click listener identifies the
canvas to browser touch adjustment without performing a second action.
Successful runs keep the camera view steady; the energy comparison stays
visible, with achievement prose inside Energy details.

Physics recipes, goals and tolerances are unchanged. The native binary is
unchanged (Windows SHA-256 `997b02d2b9f4594dbb575eeca38c17777a7ce6ec74e8832f97d265f8974464a9`).
The 27 catalogue/placement tests pass, including the existing glass/oak/iron
geometry and mass checks, in 16.74 s. Client geometry tests, JavaScript syntax,
source registration and changed documentation links pass. No new conservation
or material-calibration claim is made for this interface change.

Browser verification: all 120 Chrome scenarios passed across four 30-case
batches and targeted reruns after fixes. Batches 0/1 passed in 270.52/215.43 s.
Batches 2/3 initially found five failures: crowded wire-gauge placement, a
solar-wire touch removal, heater attachment/terminal taps on two phone views,
and a force-test fixture assuming no earlier saved win. The corrected affected
scenarios pass; physical goals and numeric tolerances were not changed. Wire
gauge checks now require either both edge badges or both readable adjacent
controls, since the latter intentionally avoids covering the world. The
force-test check preserves any pre-existing score and verifies it earns none.
The expanded retry test preserves both leads while selecting a re-edited
battery instead of the last-added wire. Mouse/touch manipulation and visible
44 px controls are exercised at 1280×860, 390×844, 844×390 and 320×568.
Proof images live in the ignored `build/ui-proof/` directory.

October 13 Help and reporting: levels use **Controls / Help**; Help contains
the task description, Share, hints and Report a bug. Sandbox keeps its Design tab
and adds Describe a design to focus the existing word builder. Builder requests
include the committed base machine; its proposals are compiled and rehearsed
by the native engine. New challenge and general Pull are removed from player
controls; older seeded links, native physical switches and internal force tests
remain supported. Level and exported Sandbox share links use https://banjo.is.

Reports are durably saved before Linear delivery. A server credential is
required for real delivery; without it, players see an explicit pending status.
The first deployed verification report was saved but remained pending with a
configured credential. Operational checkpoints now retain a sanitized failure
category; outbox migration and HTTP-authentication failures have regressions.
Migration resumes pending reports immediately without changing their identities;
the expanded 19-test host suite passes, including team-only delivery.
The live checkpoint confirmed a GraphQL rejection. Classification now uses
Linear's documented SDK `extensions.type` as well as standard GraphQL codes,
with the failed project/issue operation; provider messages remain private.
Direct authenticated verification confirmed project and BAN-team access.
The API rejected UUID5 issue IDs with `id must be a UUID`; a v4 ID passed
validation in a request with a deliberately invalid team, creating no issue.
Issue IDs now derive stable bytes with v4/variant bits, and an API-contract
regression checks the UUID version. Migration resumes the saved pending report.
The next create reached a business validation error: the original Banjo project
was archived at 21:47:10 UTC. The latest owner-supplied link identifies Banjo
team BAN; reports now default to that team without the archived project.
Optional active-project routing remains supported. IDs derive from the report
identity independently of destination; retry recovery checks the returned team.
A live create and matching returned destination complete release verification.
The 17 host tests passed, including restart retention and simulated recovery of
an issue created before its response was lost. Eight focused browser tests passed
in 30.4 s across desktop, portrait and landscape: merged Help, canonical sharing,
Sandbox base-preserving word building, Undo, saved exports, reporting and the
hidden force fixture. Manual play exposed a previously hidden Puzzle details
disclosure; it now has a 44 px target and opens its brief, deadline and energy par.
The subsequent four-test layout/replay rerun verifies this correction. Client
geometry, syntax and all 271 source registrations pass. Native SHA-256 remains
`997b02d2b9f4594dbb575eeca38c17777a7ce6ec74e8832f97d265f8974464a9`;
no physics law, timestep, goal or energy accounting changed.

October 13 object snapping default: **Snap to objects** starts enabled on
every level/design open and page load. The old stored off preference is
ignored. Switching it off affects the current setup; it no longer persists
to other levels or future visits. Alt-drag continues to bypass snapping.
Verified in Chrome on desktop, phone portrait and landscape with an existing
stored off value: reload and an in-page level change restore On; switching
Off stays available while editing that setup. Sandbox also starts On.

October 13 knife/cord alignment: compiled slender box members named by a
joint's `member` record expose finite centerline spans from their real size
and rotated axes. Working XYZ/direction guides compare against the nearest
point on that span, so a cord crossing between its center and endpoints
highlights green. No piece-name or level-ID lookup chooses the target.
For a horizontal knife sweep, dragging with **Snap to objects** on captures
the cutting plane within 8 cm transversely and holds it to 11 cm. The
working-point height must cross the finite member, and its forward tangent
offset must be between -1 cm and 11 cm. Only horizontal transverse placement
is suggested; forward position, height and simulated motion are untouched.
Existing assembly overlap/range checks validate the suggestion. Pull away,
disable object snapping or Alt-drag to bypass it. The slider's centimetre
step can leave a 5 mm center offset, inside the existing 8 mm green-guide
tolerance. Green indicates geometric alignment, not a guaranteed cut.
Measured in Chrome at 1280 × 860, 390 × 844 and 844 × 390: a knife dragged
near the cord captures its plane, reports alignment, releases when pulled
away and completes the level through the native cut after recapture. Marble
seating, working guides and initial piece framing regressions passed too.
Backend checks cover both knife levels, release hysteresis, off-depth/far
placements and a tangent above the cord; view checks include angled spans.
All 34 authored solutions still reached their goals in three nudged native
runs per level, and misplaced-piece checks passed. No goals, energy pars,
physics laws or tolerances changed.


October 13 new-piece framing: the first compiled preview of every newly added
piece checks all eight corners of its rendered bounds in the current camera.
The camera only moves backwards as needed (up to the existing 40 m limit),
preserving its angle and look-at point and leaving room for scene controls.
Both the current and settled camera pan are checked. This replaces the
selected tray cards' automatic whole-machine framing; it also covers
**Cut the cord**, **Cut it down** and Sandbox additions. Later edits,
pickup and manual zoom keep the player's camera; small additions that
already fit do not change it. Placement coordinates and physics are unchanged.
Measured in Chrome at 1280 × 860, 390 × 844 and 844 × 390: the new knife's
complete bounds fit inside the scene before placement; its angle is retained,
a later manual zoom survives a position edit and a small plank leaves zoom
unchanged. Gear meshing and river-wheel drag-to-current lessons still complete
through their ordinary controls. Plank drag/edit/run and desktop trackpad
pinch checks also passed. The plank browser test's next-level assertion was
updated to follow the current catalogue rather than the removed level order.

October 13 retry scoring: every result card shows the current run's energy,
the **Perfect score target** and its energy margin without opening Energy
details, including **Play again**, **Keep my pieces** and **Restart with my
pieces**. The target is the existing authored energy par, not a proven global
minimum. Three stars still require the goal in time, energy at or below par
and an unassisted eligible run. Fabrication/run breakdown and personal best
remain in Energy details. Failed and hand-pulled test runs also show the
energy comparison, without awarding a win for meeting the energy target.
Measured in Chrome at 1280 × 860, 390 × 844 and 844 × 390: the comparison
stays visible with Energy details closed; retained-piece retries recompute
the score, and shortening a 0.78 m plank to 0.70 m changes the result from
34.1 MJ / two stars to 30.6 MJ / three stars. Failed retained-piece retries,
the optional breakdown and Recent Changes layout also passed browser checks.
No scoring thresholds or physical behavior changed.

October 13 electrical backend: new engine builds solve circuit operating
points with ngspice. Player controls, wiring, capacitor state and lesson goals
are unchanged. Circuit receipts name the solver and numerical method. This
does not add AC/semiconductor components or complete device interiors.
See [solver scope and measurements](physics-solvers.md).

October 12, 2026. Open `/play` to choose eight chain-reaction levels, twenty-three piece lessons and three advanced electronics activities. Each level starts with an object or visible goal area and a tray of pieces you add to make the goal happen. The engine runs the whole thing; nothing about the outcome is decided by the game.

October 13 onboarding audit: all 34 authored levels use an audited teaching
sequence from simpler visible tasks toward combined mechanisms. Cards show
estimated newcomer minutes, distinct from their simulation deadline. Three
solution-blind LLM probes covered the catalogue with no reference answers;
25 initial proposals and 32 eventual proposals won. These are expert,
geometry-assisted probes and uncalibrated human-time estimates, not measured
human completion times. See [the complete per-level table and methodology](level-onboarding-audit.md).
The main Adjustment menu prioritizes task-relevant controls; opening Precision
controls restores the complete menu. Sandbox retains its full menu. Every solar
lesson shows the existing Sun direction marker. The charging lesson is named
**Charge in the sun**; **Catch the sun** remains the full winch puzzle.
IDs, saved progress, goals, reference solutions and physics are unchanged.
Older dated measurement notes below retain their original level numbers;
use the audit table for current numbering and the level names/IDs to compare
those historical measurements.

**Joining in a lesson.** A lesson whose tray offers a join shows it as a tray
card; it turns on Attach with a hint, and the join card offers only the kinds
that tray allows. Swing on a rope draws a gold tie ring at [0, 1.4, 0] under
the beam end; a tap on the beam within 0.2 m of it ties there. Measured with the
engine: a knot 4 cm off the ring along the beam still wins, 8 cm off misses,
and a knot on the beam's front face (z = 0.08 m) misses, while the marble's own
tie point and marble positions from x = −0.56 to −0.44 m all win. Taps alone
were therefore too imprecise; the ring is placement help, and the goal zone,
geometry and engine are unchanged. Browser check: placing the marble by drag,
tapping the beam face and the marble, and choosing String wins with three
stars (goal at 0.70 s) on desktop and portrait phone.

Tying by touch (October 17, from a playtest report that tapping the rope part
did nothing): at the lesson's default view the marble is about 6 px wide on a
390×844 phone and 7 px on desktop, so after the ring a tap had to land exactly
on it; a tap 10 px off did nothing on the phone and picked the trapdoor leaf on
desktop. Now, in a lesson, a tap within 32 px (touch) or 16 px (mouse) of one of
the player's own pieces picks that piece even over another part; in Sandbox only
when nothing is under the tap. After the first point the join card offers each
of the player's own moving pieces by name (**Tie to your marble**); the knot
goes on the surface point facing the first point, found on the piece's mesh. A
tap on nothing says so. Join card buttons are 44 px tall. Browser check
(`test_rope_lesson_ties_by_touch_near_the_marble_or_by_choosing_it`): a near
miss by touch on a portrait phone and the named choice on portrait and
landscape phones each tie the marble and win; a mouse near miss over the
trapdoor picks the marble.

Dragging the string (October 17, owner playtest): the dashed preview of where
the marble falls looked like a string waiting to be tied. The preview stays.
After the first point, when the tray's join offers a string, a string now
hangs 0.3 m down from that point with a small circle on its loose end (a 44 px
touch target). Dragging the circle moves the end across the plane through the
knot that faces the camera (at most 3 m of string, never below the ground); it
turns gold over a part it can tie to. Letting go on a part ties a string there
at once, as long as it is then; letting go on nothing leaves the string hanging
and says so. A tap on the circle is an ordinary tap on what is under it, so the
tap-and-choose route and **Tie to your …** still work. The lesson now uses a
**ring marble** (below), and its string ties to the top bar of the marble's
ring. Browser check
(`test_rope_lesson_ties_by_dragging_the_string_end_onto_the_ring_marble`): on
390×844 and 844×390 by touch and 1280×860 by mouse, the string hangs below the
tie ring, a drop on nothing keeps it, and a drop on the ring marble ties it to
(−0.5, 0.855, 0) and wins.

**Ring marble.** A Sandbox piece, and the rope lesson's marble: a 4 cm iron
marble with an iron tie ring fixed on top for tying a string. The ring is its
own body, eight 4 mm bars round a 20 mm circle with its hole along z, welded
1 mm above the ball with a fixed joint (as glue joins two pieces); 0.282 kg in
all. Its tray row declares where a string ties (`tie_on`: the ring's top bar),
so a tap on the ball or near the piece ties to the ring. Nothing about rolling
is scripted. A first ring 12 mm in radius let it roll like a wheel about the
ring's axis with the ring clear of the floor: down the Roll the ball slope it
curved away and was still rolling after 6 s. The ring is now wider than the
ball (44 mm across against 40 mm), so it reaches the floor whichever way the
ball rolls. On the same slope, set down at x = −0.7 m it stops at the slope's
foot (x = −0.10 m) 4.3 s in, at −0.3 m it stops after 1.65 s having moved
4 cm, and at −0.5 m it veers 0.44 m sideways; the plain marble rolls into the
cup from −0.7 and −0.5 m. Engine check
(`test_a_ring_marble_does_not_roll_true_where_a_marble_does`, nudged, three
runs each): the marble reaches the cup from both places, the ring marble from
neither, with no engine error.

## More contact and spring mechanisms

October 13: the Sandbox library has **Hinged door**, **Trapdoor**,
**Pendulum**, **Spring trampoline**, **Flywheel**, **Loose block** and
**Open airflow**. **Domino row** additionally offers oak/glass/iron and a
first-domino lean. Lean is an initial orientation: gravity starts it; actual
contacts pass the chain. Wide spacing breaks the chain. Existing challenge
recipes and their goals are unchanged.

| Piece | Controls and physical behavior |
| --- | --- |
| Hinged door | Width, height, initial opening, material and bearing resistance. Its leaf is a colliding body on a vertical pin. Contact, an ordinary test pull or airflow can turn it. |
| Trapdoor | Flap length, mount height, material and bearing resistance. Gravity acts at its offset center of mass. More bearing resistance can hold it; there is no automatic latch release. |
| Pendulum | Arm length, pivot height, initial swing angle, material and bearing resistance. One rigid weighted arm swings on a native hinge. |
| Spring trampoline | Deck width, material, total spring stiffness and damping. Four visible native springs support a guided rigid deck, initially near unloaded static equilibrium. A falling ball compresses it and can rebound through contact. This is a spring platform, not a flexible cloth membrane. |
| Flywheel | Radius, material and bearing resistance. A passive wheel on an axle stores kinetic energy. The example explicitly wires a finite battery and motor to that axle. |
| Loose block | Three dimensions, material and center height. Independent blocks fall, collide, slide and stack; they are not anchored scenery. |
| Open airflow | Speed, direction and field width. A pale boundary and six arrows show the prescribed field while editing and running. Native drag acts on boxes and spheres inside it. Readings lists air speed, force and signed external work. Overlapping fields are refused. |

Try **Domino chain**, **Wind opens a door**, **Spring trampoline**,
**Pendulum and blocks**, **Gravity trapdoor**, **Flywheel workbench** and
**Stack loose blocks** in the ordinary Sandbox gallery. Each opens an editable
design, with the same Undo, Reset and saved-version controls. No additional
challenge levels are published in this pack. See [the mechanism catalogue,
measurements and remaining work](mechanism-expansion.md).

## Pipes and scaffolding

Sandbox has **straight pipe**, **pipe elbow**, **pipe reducer** and
**scaffolding** cards. Pipes have colliding hollow walls, so the same opening
can carry native water parcels or a marble. Glass walls let you see inside;
oak and iron use the same offered geometry with their own mass and contact
properties. Choose the inlet position/height, inside radius, material and
support. Straight pipes and reducers expose length and 5–90° downhill angle;
reducers additionally expose an independent outlet radius. Elbows expose bend
radius, ±45°/±90° turn and **horizontal**/**downward** bend plane. Horizontal
elbows have an independent fall; downward elbows derive it from the bend.
A bend radius smaller than twice the outside pipe radius is refused.

Green inlet and amber outlet dots use the real route endpoints. Drag a pipe
near an outlet to snap its inlet there; the connector leaves 15 mm of clearance
for the independently colliding walls. Move a marble near an inlet to seat it
inside. Sandbox marbles also expose **starting position: on surface / at
height**, a center height, glass material and 8/10 cm sizes. Ordinary placement
still rests on the highest surface; the chosen height lets a ball enter a
hollow route instead of being placed on its roof. Nothing forces its later
velocity or spin.

Pipe **support: scaffolding / loose** adds/removes two grounded trestles and
declared mounting bolts (one for a vertical straight pipe). These supports
have real geometry and count toward construction energy. **Scaffolding** is
a separate grounded platform: adjust height, width, depth, direction and
material, then place it below a loose board or other part. Contact supports
the object; adding a platform does not anchor the object itself. Ground or
object penetration is refused rather than hidden.

Try the three editable examples **Water through pipes**, **Marble through a
pipe** and **Support a loose board**. The first connects a finite gravity tank,
downward elbow, reducer and separate container. The second uses a straight
pipe and a waiting bin. The third lets you remove a platform to watch its board
and marble fall. Water tank vessels move clear of their outlet when the
outlet is relocated near the tank wall, preventing that wall from catching
newly emitted water. These are gravity-driven routes, not a pressure network,
calibrated hydraulic resistance, leaking joints, valves inside pipes or
structural buckling. See [measurements and limits](sandbox-water-launch-measured.md#hollow-pipes-and-scaffolding-october-12).

## Advanced electronics

October 13: **Heat to release** v2 uses a hollow, four-bar iron heating coil.
Click a prepared box-shaped material's **Clip** ring while placing the heater;
its bars surround the target and declared native fixed joints mount it there.
The target dropdown is replaced by this scene attachment. **Unclip heater**
lets you choose another target. Set down, then draw both source/return leads
with the ordinary scene terminals and select **hot**. No current is supplied
merely by placement. Native current, Joule power and material temperature are
shown beside the heater. **Burn the cord** supplies editable copies of this
heater and both leads; saved v1 recipes retain their previous remote-target
coil and automatic leads.

The winding is a lumped rated resistor: native Joule energy goes into its
mounted material parcel, not spatially resolved surface heat transport. A
wired unattached heater heats its own bar, never a remote cord. Box targets
only are offered; precise compound bodies cannot accept this thermal model.
The goal/deadline are unchanged; the current construction's energy par is
37.9 MJ, measured from 37.776 MJ construction plus 84.167 kJ battery work.
At 1/240 s, the reference hot circuit releases the weight at about 8.33 s;
missing either lead, an unattached heater and the warm preset fail in all
three nudges. The electrical suite passed 39 tests; current and legacy heat
recipes and ordinary scene wiring passed desktop 1280×860, phone 390×844
and landscape 844×390 checks. The generic edit-guide compatibility case
was repaired and passed again after the full game suite found it.

Glass/oak/iron comparison: identical 4×30×4 cm targets, 12 V, 12 Ω, 2 s,
at both 1/240 and 1/480 s. Final temperatures were respectively 293.173491,
293.273858–293.273861 and 293.163958 K. Each run used 23.860812 J from the
source, exported 23.722431 J and retained 0.138381 J as heat. Maximum circuit
residual was 4.4e-13 J and thermal residual 1.1e-8 J. These are electrical
and thermal ledgers, not a full mechanical support-reaction audit.

October 13: **Marble turns on a light** uses a broad one-sided press deck,
lower counterbalance, open support frame and shallow colliding curbs. A marble
on the deck lowers the attached iron contact leaf onto a separate iron pad;
the source lead connects to the leaf and the switched lead to the pad.
**Inspect contacts** shows both actual bodies, contact state and native branch
current. Conventional-current markers across the switch require a closed
contact and nonzero measured current, including a complete return circuit.
The original balanced paddle remains in saved designs and v2 recipe links;
v1 angle-based links also retain their earlier apparatus. Fresh pieces carry
their construction version explicitly. See [measurements and the electrical
audit](sandbox-electrics-measured.md#broad-press-deck-and-electrical-audit-october-13).

Electrical and solar cable drawings use clearance routes around conservative
bounds of the native solid shapes; current markers follow the same straight
segments instead of a curve that cuts across corners. Source/solder endpoints
may attach to a conductor surface. A route that cannot clear the bounds is
hidden and labelled as blocked. These are display routes, including during
the flow preview, not mechanical cables: moving geometry can reroute the
drawing without mechanical work or changing the declared electrical length.
Cable mass, collision, flexible bending, support, insulation and connector
retention still need native models. **Click a wire** remains the deliberate
editor removal action, recoverable with Undo; collisions never cut a cable.

**Resistor** and **Capacitor** are separate Sandbox cards with A/B terminals.
Choose rated resistance or capacitance, location and glass/oak/iron housing.
Capacitors also expose internal series resistance and leakage resistance.
They are nonpolar rated parts, not a geometry-derived dielectric model.
Click A/B endpoints to draw wires just as with batteries and lamps. Voltage
drop, signed current and capacitor volts/joules appear beside the parts;
Scene callouts include the same measurements. Current dots require
measured flow. Reset starts capacitors uncharged. Saved designs/versions
preserve ratings, placements and topology; native runtime snapshots additionally
preserve instantaneous charge.

| Activity | Starting apparatus and player work | Measured goal |
| --- | --- | --- |
| Limit the voltage drop | Grounded 12 V supply and lamp; add a series resistor, then reduce its initially excessive 48 Ω resistance. | Lamp receives at least 2 W for 0.5 s. |
| Series or parallel? | One 12 V supply and two separate lamps; draw four leads to connect parallel feeds and returns. | Both lamps receive at least 2 W each for 0.5 s. A series chain or lighting only one fails. |
| Store the charge | Grounded supply and 12 Ω charging resistor; increase the initially small 0.005 F capacitor. | Store at least 4 J for 0.1 s within 4 s. The 0.1 F author solution reaches the goal at 1.867 s. |

All three author solutions pass nominal and two nudged native runs. The high
resistance, series chain and undersized-capacitor controls fail all three runs.
The **Charge and release** Sandbox example connects a switch, charging resistor,
capacitor and lamp. Run to charge, then drag the rocker open in the scene:
the capacitor supplies the lamp and loses stored energy. **Series and parallel
bench** gives two unwired lamps for comparison. See the
[measurements and validity](sandbox-electrics-measured.md#native-rc-components-and-advanced-activities-october-12)
and [full electronics catalogue](electronics-expansion.md).

**Divert the water** starts with a finite four-litre source and a separate,
empty fixed container. Add a water chute, turn it from the crosswise starting
orientation toward the container, then adjust the downhill slope or length.
The goal is at least three litres currently inside the container for half a
second; cumulative arrivals outside or water passing through do not count.
The small scene meter shows retained litres against the target. Preview is
labelled separately; Reset empties the container and refills the source.
The camera follows both the source and destination, and the win message
stays in Controls so it does not cover the collected water.
The Sandbox has separate Water chute and Water collector cards, plus the
editable **Divert water into a container** example. Chutes offer location,
mount height, length, width, aim, 5–35° downhill slope and iron/glass/oak.
Collectors offer location, floor height and glass/oak/iron material.
Overlapping or off-ground placements are refused by the ordinary geometry
checks. The container holds existing native parcels; a smooth liquid surface
is not invented. See [routing measurements and limits](sandbox-water-launch-measured.md#divert-water-into-a-fixed-container-october-12).

## Feedback audit and meaningful starting controls

October 12 laser display update: **Bounce the beam** exposes native occupied
cells under the beam, each cell's steady spot temperature, absorbed power,
stored ablation energy and current removal cost. The charred cell is drawn
dark while the native `chars` law supplies removal power. **% cell energy**
means held joules divided by the cell's current removal price; it is not
percentage rope section removed or a timed animation. Only native geometry
updates open the gap and move the released load. Other nearby cells may remain
heated after the load-bearing cord parts; the label retains **Cut through**
when the native rope joint reports detached.

**Inspect burn / Inspect heat** looks at the real heated cell from its incoming
beam's side. On a phone it collapses the controls while retaining Run/Pause/Reset.
The close-up draws at most six actual sampled ray paths to keep the char and
gap visible; all native rays and their powers still determine the heating.
**Whole machine** restores the previous view, follow preference and panel state.
Thermal wins put their result in the control panel, leaving the cut and fall
visible. Reset rebuilds the unburned geometry and clears the readout.

This adds read-only observations and display, not heat, material loss, forces
or a new combustion law. The existing 20 mm cell model removes whole cells;
steady spot warm-up, fiber-resolved rope, sub-cell kerfs, glass/metal melting,
flame shape and smoke are not simulated. No flame or invented fragment motion
is drawn. See [localized light model and limits](light-spots.md).

The [complete feedback audit](feedback-audit.md) reviews every level, sandbox
example, library piece, phone controls and saved-version workflow, including
remaining teaching and physics gaps. **Turn the axle** now starts in reverse;
choose forward to reach its positive-angle goal. **River-powered lift** starts
its wheel on the bank with no drum load: move it into the marked current and
choose **Connect rope to gate**. Both actions are physically necessary. The
preview shows native wheel rotation, rope endpoints and gate movement while
the live setup stays ready at time zero; the readout labels this as Preview.

**Sun-powered lift** (formerly **Charge then lift**, stable ID
`easy-charge-lift`) starts the receiving motor battery empty. Its panel
collects the declared sun at 20° elevation; the bulb is a parallel load on
the battery, not the light source. Controls show **Sun → Panel → Battery →
Motor → Arm**, with **Panel Out** and **Battery In** buttons that use the
same explicit cable interaction as Sandbox. Set down the aimed panel, then
click those two buttons; successful compact wiring keeps detailed readings
folded. A camera-relative sun-direction marker also indicates when the sun
is behind the view. **Why the bulb?** opens the optional load explanation.
The guide shows native panel watts, stored battery joules and motor watts;
flow previews use the same sampled native values and are labelled Preview.
The matching **Sun powers the flag** sandbox example includes this same lead
and power-path guide. Without it, sunlight can charge the panel's isolated
local store but cannot power the motor. These three Easy families use version-2
recipes; shared version-1 recipes keep their original apparatus and defaults.
The solar lesson now indicates two tasks. Goals, deadlines and pars are unchanged.

Water/current rehearsal feedback changes to **Updating…** immediately after a
setup edit, before its placement-check response arrives. Old current dots stop
and the stale flow frame is hidden; the separate laser preview keeps its last
trace with its existing updating indication. Native tests measure three nudges
of disconnected solar, bank-only/connection-only river and default reverse
motor failures, plus the unchanged successful solutions. The audit records
browser, comparative-material and residual checks separately.

## Shrink the bulb to fit the supply

Latest October 12 update: **Light the bulb** starts with a large 12 V, 12 W
bulb on the prepared, closed circuit. Select **bulb size** and shrink it to
medium (6 W) or small (2.5 W). Their declared glass diameters are 16, 13 and
10 cm. These are a family of rated components, not a law deriving electrical
demand from glass diameter. Placement is free and does not connect the circuit;
the visible prepared leads already join both bulb terminals.

The bulb badge always shows its rated voltage and watts, the unchanged 2 W
goal and measured arriving volts/watts. Each ordinary wire shows its measured
flow, with the connected battery's **Shared supply ≤ W · V** rating beside
one lead per circuit to avoid repeating the same budget across the scene. This is
one shared source budget including other loads and losses, not a separate
budget or ampacity for each wire. It appears in build previews and live runs.

The prepared supply is 12 V, limited to 2.5 W nominal, using the existing
native current limit of 2.5/12 A. The large bulb receives 2.5 V and 0.520833 W;
the medium receives 5 V and 1.041667 W. Both miss the target. The small bulb
receives 11.983149 V and 2.492984 W, reaching the goal in all three genuine
nudged runs at 0.583 s. No goal, deadline, force or conservation tolerance is
changed. Its 102 MJ par is retained. Fresh variants use v3 and vary the
shared supply limit from 2.5 to 2.8 W; earlier v1/v2 shares retain their old
prepared circuit, 200 W source limit, voltage seeds and original bulb presets.
Saved Sandbox **small/bright** presets also retain their original 3/12 W
ratings and 10 cm diameter; the additional **bulb size** choice selects the
new rated family. See [the measurements](sandbox-electrics-measured.md#bulb-sizing-and-shared-supply-limits-october-12).

## Battery voltage and wire thickness

Latest October 12 update: **Give it power** uses a fixed, grounded battery
with just a voltage control; it needs no contact alignment, height or rotation.
The waiting lamp is rated 12 V. Add the battery, choose 6 or 12 V, and click
the labelled terminals to draw a positive lead and a return lead. New lesson
wires start thin; pick either wire again and choose standard or thick. The
lamp badge shows its 2 W goal, 12 V rating and measured arriving volts/watts
in both preview and live runs. Three tasks count voltage, closing the loop
and selecting wires. Run/Pause/Set up again remain beside the scene.

Copper choices use `R = 0.0172 * length_m / area_mm2` at 20 °C:
thin 0.01 mm², standard 0.5 mm² and thick 2.5 mm². The lesson has two 5 m
leads including slack; Sandbox exposes 0.1–100 m. These are illustrative
resistance choices, not recommended household wiring sizes. Floor routes
show connections rather than exact cable length, and their enlarged widths
show the selected thickness. Wires heat through the existing native `I²R`
model; no ampacity, insulation breakdown or temperature-dependent copper
resistance is added. Existing saved wires retain their original 0.01 Ω
model through the **low resistance** setting.

The bulb is a nonpolar resistor: crossing its two leads still lights it.
Both must form a loop. A motor instead reverses with signed current when
its leads are exchanged. No piece-name polarity rule decides a win.
The unchanged lamp goal is ≥2 W for 0.5 s within 4 s. Standard 12 V wiring
delivers 11.9023 V and 2.95135 W; thin wiring delivers 8.82759 V and 1.62346 W;
6 V with standard wiring delivers 5.95115 V and 0.737837 W. An absent return
delivers zero. The solution succeeds in all three native nudges at 0.583 s,
and its 881,440,001.736 J measured score uses the 882 MJ fixed-case par.

Fresh battery challenges use recipe v3. Existing v1 fixed/prewired and v2
contact-holder links retain their apparatus, seed policies and one-task counts.
**Drop a battery into its holder** remains a separate Sandbox example with
physical cap/pad contacts. See [electrical measurements](sandbox-electrics-measured.md#battery-voltage-and-copper-wire-resistance-october-12)
for checks and model limits.

## Cable power and object requirements

Latest October 12 update: compact labels next to cables show measured watts
and amps in both build preview and live runs. Moving dots indicate activity
and conventional-current direction, not electron speed. Solar charging leads
show native collected watts; ordinary supply wires show instantaneous `V * I`
relative to battery negative, distinct from their native `I²R` heating. Return
leads show current to avoid implying that their low reference-dependent watt
reading is the appliance's available supply. Native voltage arrays can use
another gauge; the display explicitly subtracts the source-negative voltage.

Bulb labels show the existing level's power target, or the full-brightness
rating in a sandbox. Simple grounded motor arms and unencumbered vertical drum
lifts show **Start ≈ W · N·m**, plus actual input watts. This is a static
gravity/bearing estimate from native body mass and centre of mass; moving
faster, accelerating, wire losses and other shared loads need more power.
Catch the sun's 7.87 kg load on a 40 mm drum estimates 3.088 N·m and 14.305 W
at rest, not a promise of its timed goal. A motor whose torque rating is too
small is labelled accordingly; adding watts cannot exceed its stall rating at rest.
Complex contacts, springs, coupled gears and other linked loads show variable
demand and the motor's full-command stall torque rather than a fabricated minimum.

Badges use the same measured preview frame as the flow and switch indicators.
They show Updating while a changed setup is being measured; inactive cables
have no moving dots. These are display calculations, never force commands or
new win conditions. Badges do not intercept dragging, avoid the scene controls
and hide overflow rather than stack over other labels. The old preview-only
wire-number sprites are replaced by these shared compact meters.
See [the electrical measurements](sandbox-electrics-measured.md#cable-power-and-starting-load-estimates-october-12)
for calibration limits and verification.

## Individual gears with contact-driven teeth

Later October 12 update: **Gear** replaces the paired card in the new-piece
library. One Add creates one mounted wheel, with 12/18/24/36 teeth, tooth size
16/24/32 mm, axle height, tooth alignment, aluminum/oak/glass/iron material and
bearing friction. Increasing tooth count or tooth size increases its actual
diameter and material-derived inertia. It creates no battery, motor, second
wheel or ideal gear constraint. Connect a separate motor to the gear's named
axle and wire a finite battery to that motor. The visible rectangular teeth
are native rigid colliders; their contacts carry torque. Too-close wheels
are refused as overlaps, while a gap, an axial offset or teeth too small to
reach leave the next wheel unpowered. This is a simplified rectangular tooth
profile with backlash, not calibrated involute gearing or tooth stress/failure.

**Turn the big wheel** begins with a wired 12 V battery and 4 N m motor driving
one 12-tooth wheel, plus the existing 24-tooth target. Choose and place a single
gear between them; the starting 18-tooth loose gear does not solve the gap.
The player makes two decisions: size and placement. Correct 12-tooth placement
wins all three nudges at 1.750/1.633/1.750 s. The target still must turn 180°
within two seconds. Empty/default/axially misplaced/undersized controls fail;
an empty battery or interrupted supply wire keeps the target still. No goal
or deadline was loosened. The measured authored par is 1.05 GJ (fabrication
1,041,093,292 J plus 27.117 J source draw, rounded upward).

The **Fast wheel slow wheel** sandbox example uses these separate gears.
Old saved `gears` pieces still compile with their original paired builder,
but that legacy card is hidden from Add/library browsing. Current gear recipes
are version 3; v1 paired and v2 paired-with-added-motor recipes retain their
declarations, seed policies and one-task count. The current seeds still vary
the supply voltage, without changing contact geometry or imposing a ratio.
See [contact gear measurements](sandbox-mechanics-measured.md#individual-contact-gears-october-12)
for the glass/oak/iron comparison, timestep and conservation limits.

Chrome verification passes the gear lesson with ordinary mouse/touch drags at
1280×860, 390×844 and 844×390, plus the library filtering check on all three
viewports and a phone saved-example reload/restore check. The newly added gear
frames once so it remains visible while resizing and dragging. Run/Set up
again and piece adjustments remain beside the 3D view. Historical broader
browser-suite limitations below have not been claimed as resolved by this
focused gear work.

## Start with an object or visible goal area

October 12 update, superseding the earlier empty learning fields: every one
of the 30 authored levels now opens with existing apparatus or a visible goal
area. No unrelated reference boxes were reintroduced.

* **Spring lifts the load:** an oak load rests on a real fork cradle. Add the
  spring underneath it and increase its relaxed length from the 20 cm starting
  setting. The existing load must rise the same 5 cm; a green height mark is
  drawn at its starting top plus 5 cm. The October 13 latched contact assembly
  described above replaces the direct attachment for the current lesson and
  new Sandbox pieces; earlier saves keep the original construction.
* **Raise the crate:** the glass crate waits on a physical pedestal. The added
  tackle connects to that crate instead of creating another load. Its unchanged
  target is a 25 cm rise, with a mark above the crate's original top.
* **Turn the big wheel:** the powered drive gear and target start on the field.
  Size and place one independent gear to bridge the gap, as described above.
* **Pour onto the paddles:** the independent wheel is already in the dry
  channel. Add a separate tank, open its initially closed tap and aim the
  pour at the paddles. The unchanged target is 30 degrees within six seconds.
* **Fill the receiver:** a raised, empty fixed box waits for the source.
  Increase the source tap from its 10% starting opening to retain 3 L for
  half a second within 5 s. The current boxed goal counts native parcels
  inside the receiver, rather than cumulative channel arrivals.
* **Wheel in the river:** the river has a green current marker before a
  piece is added. It identifies the working area, not another scoring zone.

The green guides are visual descriptions, not colliders or scripted win
conditions. Existing apparatus, native movement and the original goal rules
still decide success. Goal areas contribute to initial camera framing; adding
the river wheel frames it once so its bank position remains draggable. Other
camera gestures and exact controls keep their behavior. Goal label textures,
line geometry and materials are disposed when the scene is rebuilt.

Correct spring, tackle, gear and pour solutions win all three native nudges
at 0.050, 0.733, 1.750/1.633/1.750 and 1.517/1.867/1.400 s respectively. Empty and authored
wrong setups win 0/3 each without engine errors. The default 20 cm spring and
a spring one metre beside the load also fail 0/3. No goal, deadline or
conservation tolerance was relaxed. Scoring excludes already supplied targets:
measured construction plus the usual 1 kJ margin for spring/tackle/pour gives authored pars
21,341,800 / 827,064,040 / 1,050,000,000 / 460,651,224 J respectively; the gear par rounds the measured sum upward to three figures.

Current spring/tackle recipes use version 2; gear and pour use version 3.
Earlier v1 mechanical/pour and v2 modular-pour links retain their apparatus,
goals and seed policies. Their native solution/empty/wrong checks pass in
three nudges; v2 pour keeps its former two-player-piece task count. The new
spring seeds vary stiffness 180/200/220/240 N/m; gear seeds vary supply
11/11.5/12.5/13 V. All 22 families' 88 presets pass 264 correct nudges with
zero empty/wrong wins. The recipe suite passes 15 tests in 137.5 s, plus
the added legacy-target recipe regression in 4.4 s.

The full game suite passes 50 tests, plus the new all-level starting-target
regression; water/launch passes 12 in 29.8 s and mechanics 12 in 7.8 s.
The client-view CTest, JavaScript syntax and all 269 source registrations pass.
The native executable is unchanged:
`3fac18bff131cf0d819e6186969c4ed64b27210eef04e36f420bd497ce39d24a`.
These change authored apparatus and presentation, not engine laws. Spring
comparisons and unreconciled support/numerical receipts are recorded in
[the mechanics measurements](sandbox-mechanics-measured.md#waiting-load-spring-october-12).

Five focused Chrome checks pass in 45.6 s: the original waiting loads are
visible before Add and the added spring/tackle lift those same bodies, the
then-supplied gear pair responded to an added motor (superseded by the individual-gear lesson above), the waiting wheel responds to
the tank, and the river wheel remains draggable after area framing. They
cover 1280×860 desktop, 390×844 portrait and 844×390 landscape; the tank also
passes at 320×568. Run/Set down/Reset use visible, unobstructed 44 px targets.
The new area initially made the bank wheel too large for a reliable drag;
framing the newly added wheel fixes that case without changing gesture or
goal tolerances. Manual phone play wins the spring lesson. Broader earlier
CI failures in other controls remain outside this verified scope.

The legacy water-save browser fixture now waits for the actual saved-version
count/status before reloading. A previous Linux CI run refreshed during its
native validation check, before a profile sync had started, and then read a
missing version. The fixture retains its existing ten-second save timeout;
no save implementation or assertion was relaxed.

## Learn one reflection before routing two

October 12, 2026: **Bounce to the target** (`easy-mirror`) is now level 6,
immediately before **Bounce the beam** (`laser`), now level 7. The level list
and Next level use the same catalogue order. Other levels keep their relative
order. Stars/progress stay keyed by level ID; existing links, challenge recipes,
machines, solutions, pars and goals are unchanged.

Existing catalogue/solution-fit and task-metadata checks pass 2/2 in 0.12 s.
The chooser regression verifies the new numbers/order on desktop and phone
portrait/landscape and passes in 1.48 s. This is presentation order only and
does not add or imply new physical validation.

## Fine grid and gentle placement assistance

October 12, 2026: the flat ground shows 5 cm subdivisions with stronger 50 cm
lines. The minor grid is a 10 m patch centered on the current view, moved only
by whole major squares so its world coordinates do not shift. Its edges fade
over the outer 2 m; fine lines also fade with camera distance, disappearing in
overviews at 12 m. The original 40 m ground/major grid remains. The patch uses
804 line vertices and the major grid 324, in two line batches rather than the
previous single 324-vertex grid. This bounds visual density and rendering work
instead of drawing tiny lines across the entire distant ground.

**Snap to grid**, in the selected piece's Controls module, starts enabled and
remembers the browser's preference. A real drag catches each x/z grid line
within 8 mm and holds it until the pointer leaves a 12 mm release band. This
small hysteresis avoids chatter; positions farther from a line move freely.
**Alt+drag** temporarily bypasses ground and object snapping on a computer. A small gold
ground mark and **X / Z aligned** feedback identify the placement point and
aligned axes. Nearby object/connector joining, when enabled, takes precedence; a connector adjustment
clears grid feedback if it changes x/z. No ground snapping is applied where
the flat grid is absent, or to wire/power-cable endpoints.

This edits only proposed x/z placement knobs. It does not quantize height,
angles, dimensions, exact controls, arrow movements, existing placements or
saved versions, and it never moves a simulated body. A tap, a drag below the
existing 6 px threshold, camera gestures, and zoom with a stationary held piece
retain their previous behavior. The precision-fields scroll area reserves
8 px at its edges so revealed controls clear the Set down footer.

October 13: **Snap to objects** is a separate remembered preference, enabled
initially. A real drag can seat a tray marble on the center lane of a nearby
compiled flat board or track, or seat an independently editable prepared
loose sphere. Surface placement retains the compiler's ordinary support
height; explicit-height/prepared spheres can adjust height to the nearby
surface. Candidates need at least a diameter plus 10 mm of lane width, 5 mm
end clearance, and an upward face normal with vertical component ≥0.65.

October 16: **like pieces meet flush** in the Sandbox. With **Snap to
objects** on, a plank or block dragged within the same 8 cm capture distance
(released past 11 cm) of a like piece's face is moved so the two meet:

- **Plank end to plank end**: along the same line, at the same height. A plank
  turned within 10° of the other's line is turned onto it; one further off is
  left alone. Only flat planks (no tip or roll) have ends to snap.
- **Block side to block side**: any of a block's four sides, bottoms level, for
  fixed blocks and loose blocks alike. A block turned within 10° of any quarter
  turn of its neighbour is squared up with it.
- **Block on top**: centred on the lower block's top. A fixed block is set down
  as before, so it stacks when dragged over the other's middle; a loose block,
  whose height is its own knob, stacks when held over it or dragged into it.

Planks snap only to planks, blocks (fixed or loose) only to blocks. The
pieces are left 0.1 mm apart, so rounding never overlaps them, and the server
builds the snapped spot and offers it only if the two then touch within 1 mm
(and two planks lie at one height) and nothing about the piece is refused: an
overlap with anything else, or a plank that would come to rest higher on
something in the way, cancels the snap. The page keeps these positions as the
server measured them rather than rounding them to the 1 cm slider step. A
plank turned only about the vertical is now set down by its own outline, not
the square round it, so it lies beside a turned neighbour instead of on it.

Snapping is placement geometry only. No glue or joint is added: fixed blocks
are each held by the world, while loose planks and loose blocks merely touch,
and **Attach** (glue or a pin) joins them. Lessons keep their own snaps: faces
are only offered in the free build, so no level's solution or snapping
changes. Alt-drag, the exact controls and turning do not snap, and grid snap
behaves as before. Measured by `tests/machine_game_tests.py` (FreeBuild): plank
ends at 0°, 30° and −90° (gap 0 to 1 mm, no overlap, same height, on one line,
no joints); all four block sides and a turned block; fixed and loose stacks
centred on top; release beyond capture and hold to the release distance;
refusal when a post stands in the snapped spot; and no faces in any lesson.
Capture uses a full 3D distance of 80 mm; an existing match releases at 110 mm.
An airborne ball far above a track does not teleport down. Ordinary overlap,
ground and support-height checks reject blocked seats. Track/pipe connector
translations use the same local capture band, including height. The old
explicit joining API and authored recipes retain their wider search. Toggles,
exact controls, camera movement and existing saved placements never relocate
an object; Alt bypasses both capture systems. No magnet force is added to a run.

XYZ guides pass through the selected working point: compiled mirror center
and face normal, lens center/axis, panel collecting face, a track/pipe endpoint,
a board top or a generic body center. Changing track length/drop selects the
exit endpoint. A knife uses its declared edge and connected hinge to locate
the lowest point of its edge circle, with a tangent in the initial gravity
torque direction. This is reachable geometry, not an engine-predicted swing:
contact, stops and energy may prevent reaching it. Its tooltip states that.
Other compiled centers, flat surfaces and electrical terminals supply target
points. A bright green axis requires both transverse coordinates within
8 mm and a target within 5 m along it. Facing arrows require the same 3D
perpendicular tolerance, forward of the face. Occlusion, reflection and energy
are not checked by these annotations; native laser previews and runs remain
authoritative. Small dots mark matching points; text stays in Controls.

Verification: 59 full game/engine tests passed in 98.197 s before the final
prepared-sphere addition; its added geometry and obstruction cases passed
separately. Desktop/portrait/landscape browser checks passed ordinary marble
drag capture/release, disabled assistance, native rolling after Set down/Run,
turning mirror normals, prepared-sphere placement and exact Undo restoration
in 15.737 s. Existing track joining and the four-size ground-grid check also
passed, along with the client geometry CTest and 269 source registrations.
100 knife-geometry replies measured median 1.82 ms, maximum 2.61 ms locally;
they do not run the engine. Windows engine SHA-256 remains
`4bde8f581098a877616ac5647923de8a2b0aada2d5db39911f85b8bef1e783a8`.

CI follow-up: the e52b87 switch fixture accidentally requested the new contact
paddle while asserting archived v1 geometry; it now explicitly requests v1
and all five mechanical-switch tests pass locally. The crowded-wire browser
check also passed locally. The growing 111-case browser suite is registered
as four disjoint batches after Linux's aggregate run exceeded 1200 s. No case,
individual wait, physical deadline or tolerance was removed or increased.
Broader CI remains separate from the measured local placement checks.

Measured with the unchanged native SHA-256
`807ae9c34f0516a0d0dbf588400451b865083043d614cd1aab8040140c830f87`:
seven targeted Chrome regressions pass in 44.92 s, covering gentle drag capture
and release at 1280×860, 390×844, 844×390 and 320×568; disabled snapping;
unchanged non-position knobs; precision steps; preference reload; exact saved
sandbox versions/restoration; taps, camera zoom, connector joins, place-and-run
and phone tabs/rotation. Final grid/Alt override, precision footer and both
reading-overlay checks pass 4/4 in 27.80 s after the rendering fade and updated
help/Recent Changes text. Manual phone portrait/landscape and desktop checks
verify visible controls and grid contrast; the page reports no shader errors.
The registered client-view test and all 269 source registrations pass. No native
source, material, timestep, goal, energy or conservation tolerance changed;
this is placement/layout assistance, not new physical validation. Previously
recorded broader-browser/CI failures are not resolved by these checks.

## Recent Changes in the top navigation

October 12, 2026: **Recent Changes** opens dated, player-friendly notes from
the levels chooser, sandbox gallery, design editor or any level. Newest dates
come first. The notes live in `client/voxel-lab/machine.html`; `AGENTS.md`
requires updating them for every published checkpoint. Current entries cover
the seesaw contacts/wires, solar shadows/cables, player-operated cannon,
clearer controls and anonymous saved designs.

Like How to play, this is an on-demand modal. Close, Escape or a backdrop tap
returns focus to its top link without navigating, rebuilding, discarding a
ghost or changing saves. A running machine continues while reading. Notes
scroll inside the layer with its Close button always available. On narrow
phones navigation occupies two rows so every link remains visible; scene and
panel height subtract the measured header height after resize/rotation.

Chrome checks pass 3/3 in 14.41 s: the new overlay regression, existing How to
play and existing View/Move regressions. The new check covers 1280×860,
390×844, 844×390 and 320×568: visible 44 px navigation targets, keyboard/focus,
older notes, drafts, running machines and all four page contexts. The client
view CTest and all 269 source registrations pass. This changes client layout
and reading overlays only; the native binary, laws and goals are unchanged.
It adds no new physics or conservation validation. Previously documented
broad-browser/CI failures remain outside this UI scope.

## See the seesaw's firing switch

October 12, 2026: **Chain reaction** depicts its prepared firing circuit as
three visible floor-routed leads: battery supply to the fixed contact pad,
the moving seesaw contact to the cannon's heating coil, and the blue return
to the battery. Red is the supply/switched path; leads turn yellow only with
measured nonzero current. No wire bridges the open contact gap. The earlier
single thin line skipped contact-operated switches because it only looked
for a switch hinge.

**Inspect switch**, attached to the scene, zooms under the seesaw and labels
**Moving contact** and **Fixed pad**. Orange outlines identify open contacts;
green shows the engine's closed switch. The Controls module reveals measured
switch state, amps and coil watts, with a short explanation of the power
loop. Inspection opens collapsed controls, keeps the close-up during Run,
and returns to the overview with **Whole machine**. It never moves a part or
operates the switch. Readings remain below/beside the scene, not in floating
cards. The two small component labels appear only while inspecting.
While inspecting, the result card stays in the Controls module so a win
cannot cover the contacts. Returning to Whole machine restores its usual
scene placement. The final inspection/result-card and energy checks pass
2/2 in 14.44 s; the final labelled/live-reading inspection check also passes
on all three viewports in 11.73 s.
Public phone play on `e84d9799` wins with three stars and measured closed
contacts/coil power, but exposes a grid-layout issue: the result card shrinks
inside the Controls pane. Its scoped layout now preserves natural content
height and lets the outer pane scroll. The strengthened three-viewport check
requires a full-height card and presses Play again through its visible touch
target, then wins again; it passes in 17.08 s. This follow-up changes layout,
not native behavior or game state.

Rehearsal frames transport measured contact/lever poses and circuit readings.
The preview draws the same complete leads, current arrows and an outline of
the calculated seesaw/contact pose. It is labelled Preview; inspection shows
the current live setup instead of presenting future closure as a live reading.

This is a diagram of the existing ideal circuit. Connector anchors and floor
routing are drawing geometry; there are no new cable bodies, mass, resistance,
elasticity or winding models. The native touch switch, 4° ratchet, coil heating,
powder/gas model, materials, timestep, goals and 109 MJ par are unchanged.
No new coupled conservation claim accompanies a rendering/transport change.

Measured on the same native SHA-256
`807ae9c34f0516a0d0dbf588400451b865083043d614cd1aab8040140c830f87`,
dt = 1/240 s, four steps per host call: correct ramp placements win 3/3 at
1.575, 1.550 and 1.521 s. Empty and sideways-misplaced ramps win 0/3 each.
Rehearsals start with zero current/open contact and later report a closed
contact and positive coil watts, with all three lead currents matching the
same native circuit account. Registered game, world and view checks pass
3/3 in 67.38 s, including all 29 levels' existing solution/par checks. All
269 C++ sources remain registered; no native source or engine binary changed.

Browser coverage runs all 64 methods in two fresh-browser groups: 31/32 in
182.28 s and 32/32 in 200.23 s. One portrait battery-drop request receives the
previously recorded Windows `net::ERR_NO_BUFFER_SPACE`; the broad local run
is not green. The unchanged battery-drop case, the switch-grip case and the
final Chain reaction inspection test pass together, 3/3 in 17.11 s. The new
check covers desktop, phone portrait/landscape, collapsed controls, preserved
inspection during Run, actual closure/coil power, and unrelated-level cleanup.
The prior `9e0453e3` Linux CI completes 153/154 CTests; its one failure is a
10 s wait for an initial manual-switch grip drag to become active, rather than
the former aggregate timeout. Its cause remains unproven; a Windows isolated
pass is not a Linux fix. Current Linux verification must complete before a
new result can be claimed.

## Clear solar shadows and required delivery cables

October 12 editing correction: moving a placed solar panel previously left
its old live shade label and obstruction ray on screen. Proposed placements
now receive a debounced native **ready-state** sunlight sample in a separate
paused world. Old shade labels/rays clear as soon as an edit begins; the new
reading and ray are marked **Preview**. This works independently of path
playback and does not advance or charge the live machine. Set down switches
back to live measurements. A small sample dot marks the actual panel-center
ray origin. **In shadow at panel center** names the blocking part; the setup
controls also report measured sunlight rather than an unshaded-only estimate.
The engine still uses a center ray, so this does not establish partial-panel
shading. Ground shadows are drawn at floor height; the ray is sampled on the
raised panel, which can have a different shade boundary. Sun direction and
rendered wall intersections are checked against the native sample on both
solar-wall levels, on desktop and phone portrait/landscape.

Both **Catch the sun** cards now have a concrete wall, 2 m wide, 1.6 m high
and 0.12 m thick. The winch wall is turned 45° across the low sun's direction;
the introductory wall stands across its south-facing sunlight. Move the
collector beside the wall, aim it toward the sun, and open **Readings and
wiring → Connect wires**. Click collector **Out**, then winch **In** or the
introductory battery **In**. The cable is visible and follows piece edits.
**In shadow · shade wall** identifies native obstruction; the same line
always reports **Cable connected** or **Output not wired**. The rendered sun
uses lower ambient fill for clearer cast shadows, without changing physics.
The initial overview frames full rendered geometry rather than body centers,
including composite shapes. Resizing or collapsing controls preserves that
framing so a broad wall and its collector stay visible on a phone.

The collector lesson has two tasks and an empty fixed receiving battery.
Its unchanged 20 J / 1 s goal now measures delivered energy in that receiver;
an unwired collector charging its own local store cannot finish it. New seeded
solar challenges use recipe version 2; version-1 URLs retain their original
preconnected apparatus, goal and 532 MJ par. Current par is 192 MJ, rounded
above measured 191,439,840 J fabrication because the receiver housing is now
fixed apparatus rather than a player-built included battery.

Measured at dt = 1/240 s on native SHA-256
`807ae9c34f0516a0d0dbf588400451b865083043d614cd1aab8040140c830f87`:
at 1000 W/m², collector area 0.25 m² and 20% conversion, the winch sun is
15° above ground at azimuth 225°, and the lesson sun is 20° at azimuth 180°.
Both aimed, unshaded collectors deliver 50 W; the declared shaded controls
deliver 0 W. Each correct setup wins 3/3 nudged runs. Each disconnected,
shaded and flat-panel control wins 0/3; disconnected receivers retain zero
charge while the panel's local store charges. Solar energy-account residuals
for these controls are within 9.7e−11 J. The intro wins at 0.467 s; the winch
wins at 2.400, 2.450 and 2.383 s, with its existing goal and 193 MJ par.
These are solar/store measurements, not full motor/contact energy closure.
The center-ray shade approximation and ideal charging cable limitations
remain unchanged; this adds no material or electrical law.

The five registered game, mechanics, electrics, recipe and client-geometry
checks pass (115.58 s), including all 29 level solutions and the 82-preset
native recipe sweep. Source registration covers all 269 C++ files. Both
previous published Linux CI runs reached the browser suite's 600 s aggregate
cap with passing cases still in progress; the aggregate cap is now 1200 s.
Individual browser waits, physical deadlines, goals and assertions are
unchanged. Linux CI must complete before its new result can be claimed.

A preceding complete Chrome run passed 62/63 in 402.00 s; the landscape
save-restore request failed with `net::ERR_NO_BUFFER_SPACE`. Its unchanged
three-viewport test passed separately in 5.89 s. This was a local browser
transport failure, not a native or save assertion failure; the underlying
socket exhaustion cause remains unproven. No click retries or relaxed waits
were introduced. The game and recipe metadata recheck passes both registered
targets in 118.04 s.
The full confirmation run also passes 62/63 (400.66 s), this time with the
same socket-buffer error on a profile request while reopening a fresh
challenge. Its previously failing save-restore case passes. Every solar,
wiring, framing and touch case passes both complete runs; the complete local
browser suite is nevertheless not green. This Windows transport limitation
remains recorded separately from the verified outgoing solar scope.
The unchanged fresh-challenge test and all three solar/clear-scene tests
pass together, 4/4 in 66.02 s across desktop and both phone viewports. Manual
ordinary-control play completes both solar levels with three stars; captured
portrait, landscape and desktop views show the full wall, shadow and cable.

## Player-operated cannon and level-control audit

October 11, 2026: **Knock it off** now has four player tasks: place and aim
the cannon, draw its two firing leads, and operate its physical trigger.
In **Controls**, choose **Connect wires**, connect **trigger Out**
to **cannon +**, then **cannon −** to **supply −**. The supply-to-trigger
lead is part of the fixed apparatus and is visible from the start. Drag the
**Drag to fire ↓** handle down to close the circuit. A tap applies no force;
**Try It!** alone leaves it open. Reset restores the original open handle.
The scene keeps only compact endpoints during wiring and the handle during
operation; the current, coil watts and available charge-temperature readings
stay in the disclosure below/beside the view.

The trigger has the engine's existing ideal ratchet: after its hinge passes
−30° relative to its initial 25° pose, it can travel further closed but cannot
rebound open. This keeps the heating circuit closed after a short pull. Reset
releases the latch by rebuilding the original open apparatus. It is a native
joint constraint, not a Boolean firing command or a forced angle.

The old falling trigger weight and automatic `fired_by` connection are gone.
The coil must receive solved circuit current and heat the charge, its gas
must break the wad and accelerate the ball, and the ball must hit the block
into the existing green zone. Position, height, direction and powder still
determine the shot. Wires explicitly retain their terminal graph when the
cannon is moved; they do not appear merely because it was placed. This uses
the existing fixed-resistance ideal wiring model (0.01 Ω per lead): cable
length, mass, elasticity and detachment are not modeled.

**Close the switch** also had a shortcut: choosing an initially closed
handle could finish the field-operation lesson without operating it. New
canonical and version-3 seeded challenges permit only the open manual
starting pose. The player must drag it to close the lamp circuit. Sandbox
still permits either initial pose. Version-1 and version-2 shared challenges
retain their earlier pose/mode choices and original seed policies.

Manual-input previews say **waiting for your handle drag** and rehearse the
actual open starting machine, without firing or closing it for the player.
**Place it for me** delivers a checked setup and asks the player to operate
the handle; it does not search for a way around the operation or claim a
rehearsed win. The offline reference `solution_inputs` are bounded forces
through the same validated handle API, supplied explicitly by tests and
seeded-challenge verification only. They never enter a live declaration,
ordinary preview, save or public level response.

All 29 canonical levels were inspected and run with correct, empty and
incorrect configurations, three trials each. Correct configurations won
87/87; empty configurations won 0/87; incorrect controls won 0/87, with no
engine errors. At that earlier audit checkpoint, Light the bulb's negative control kept the bulb and
leads but emptied its source battery, since spatial movement cannot break
an ideal wired circuit. For manual lessons, a correct placement without
handle input is the negative control. These checks preserve goals, deadlines
and tolerances.

| Levels audited | Source of action and player responsibility |
|---|---|
| Mind the gap; Cut it down; Cut the cord | Gravity starts the ball or pendulum; bridge/edge geometry must work. |
| Knock it off; Close the switch | Explicit wiring and/or actual handle force; no automatic start shortcut in new challenges. |
| Chain reaction; Marble turns on a light | A real ball tips the lever/paddle. The first level includes its fixed firing circuit; the second includes visible prepared leads. |
| Up she goes; Heat to release | Declared firebox or wired coil supplies heat; native pressure or cord weakening reaches the goal. |
| Bounce the beam; Bounce to the target; Find the focus | Native rays must reach the cord/sensor through the player's optical geometry. |
| Catch the sun; Catch the sun (collector lesson); Sun-powered lift | All require a player-drawn charging cable and sunlight. The lift starts with an empty battery; its prepared motor and parallel bulb share the received energy. |
| Lift with less; Raise the crate; Tip the lever; Spring lifts the load | Material-derived weight, gravitational travel or stored spring energy provides the motion. |
| Turn the big wheel; Turn the axle | Prepared drive/leads are stated in the brief. Position does not create a socket connection. Gear drive and motor direction remain player settings. |
| Light the bulb | Shrink the rated bulb to match the prepared supply. Voltage/power readings show the real current-limited result. |
| Give it power; Finish the loop | Select the battery voltage and wire thickness, then complete both leads; or draw the explicit missing return wire. |
| Pour onto the paddles; Fill the receiver; Water opens a gate; River-powered lift | Water must reach the receiving area/paddles. Valve/pour state is a setup control; gate lessons also require a drum rope. |
| Gentle first launch | Arm restraint is a setup control; a released raised counterweight turns the cradle and contact launches the marble. |

The motor, bulb and gear briefs now distinguish prepared wiring/drive from
spatial placement. Water valves and catapult restraints remain declared
starting conditions plus the existing live controls; they are not new
mechanical valve/trigger models. No timed cannon primer was found in an
authored level. The Sandbox retains its explicit primer-time option.

Measured on native SHA-256
`807ae9c34f0516a0d0dbf588400451b865083043d614cd1aab8040140c830f87`,
dt = 1/240 s, four steps per host call: the aimed, wired cannon with an
explicit 8 N downward reference grip force reaches the unchanged goal at
0.925, 0.979 and 0.858 s. No input, no leads, each missing lead, 35° wrong
aim, a 0.5 g weak charge and a 0.20 m low bore all fail 0/3 with no engine
error. Its nominal win takes 904,301,244.324 J against the unchanged 905 MJ
par: 904,295,646 J fabrication, 2,799.993 J declared powder, 2,797.790 J
battery draw and 0.541 J grip work. Electrical ledger residual is
−1.8741e−12 J; thermal residual is 1.1515e−8 J. These are circuit ledgers,
not a full gas/rigid/contact momentum or energy conservation claim. The
existing simplified powder, warm charge and ball-at-muzzle model limits
remain in [the physics roadmap](machine-physics-roadmap.md).

The original 82-preset native recipe sweep passes 246/246 correct trials and
zero empty/wrong wins; fresh switch recipes now exercise actual grip force.
The 19 electrical regressions still include glass/oak/iron under matching
declared conditions. No native model, material property, timestep or scoring
tolerance changed.

Short-pull comparison: identical 0.20×0.04×0.06 m handles, the same 8 N
downward grip force released at 0.25 s, the same circuit and 1 g charge,
dt = 1/240 s. All three handles remained latched near −50.0002° with zero
remaining applied force and normal goal scoring. Glass/oak/iron reached the
goal at 1.012/0.954/1.079 s. Their sampled electrical residuals were
−2.5402e−12/−2.6112e−12/−2.3981e−12 J and thermal residuals
1.5537e−8/1.5985e−8/1.4650e−8 J. Grip work was 0.541 J in each run. The
ratchet has no tooth compliance, wear or separately modeled pawl losses.

An initial aggregate run passed 14/15 CTests, including all 62 browser checks
in 315.41 s; the recipe target caught an indentation error in its new test,
which was fixed and passed its separate 13-test run in 107.49 s. Repeated
unlatched cannon drags then caught two desktop failures: the handle rebounded
open after briefly closing the circuit, giving only 729.282 J from the supply
and a weak shot that fell short. The native latch above resolves that physical
failure. Its nine repeated desktop/portrait/landscape browser plays passed
in 65.672 s; the glass/oak/iron short-pull test and all seven negative cannon
controls also pass. These initial failures are retained here rather than
treated as successful final verification.

Final local verification: all 15 relevant registered CTest targets passed in
314.62 s, including 62 browser checks (314.61 s), 46 game checks (61.34 s),
13 recipe checks (107.97 s), and the world, physics, mechanics, electrics,
water/launch, combinations, HTTP, save and client suites. The final canonical
29-level audit repeats all 261 scenarios in 48.505 s with the outcomes above.
JavaScript syntax and source registration (269/269 C++ sources) pass. The
cannon browser regression uses actual visible clicks and pointer/touch drags
at 1280×860, 390×844 and 844×390, preserves both saved terminal leads, verifies
Run alone fails, and earns three stars only after the physical trigger drag.

The chooser shows every level together, with no difficulty filters or Easy
labels. Each card says **1 thing to do**, **2 things to do**, and so on.
This counts the expected player tasks: placing and adjusting one piece is
one task; a separate wire, field operation or drum connection is another.
Automatic events and the common Run button are not additional tasks.
For example, Mind the gap counts one plank, Bounce the beam counts two
mirrors, Catch the sun counts a collector and a power cable, and Close the
switch counts placing the switch and operating its field handle. This menu
metadata does not change the machine, its goal or its scoring.

Checked October 11, 2026: all 43 game tests pass through the registered CMake
target in 49.04 s with the unchanged `807ae9c3…` engine. Three focused Chrome
checks pass in 15.726 s, covering all 29 cards, singular/plural task labels,
removed filters and Easy prefixes, saved wiring, and generating, sharing and
reopening a challenge at 1280×860, 390×844 and 844×390. An initial run still
looked for the old **Recent easy challenges** accessible label; its selector
was updated to **Recent challenges**, without changing waits or goal checks.
Task counts are authored in `scripts/machine_game.py::PLAYER_TASK_COUNTS`;
new levels must add an entry, and generated variants inherit their family's
count. This update changes menu metadata and labels only, with no new physical
model or conservation claim.

## Expanded sandbox and easy challenges

**Anonymous saves (October 11, 2026).** The Levels and Sandbox screens offer
**Your return link** and **Copy return link**, with no player-name entry.
The **?** buttons beside the return link and **Save version** open save help
only when requested. Cookie/return-link guidance, privacy and version-history
explanations live in these popovers. The screens use short status labels such
as **Saved**, **Saving…**, **Not synced** or **Temporary storage**; actual save
errors remain visible. Version confirmations are **Version N saved** or
**Restored version N**. The sandbox introduction and free-build goal no longer
repeat save instructions.

Save help supports Close, Escape with focus returned to its button, and outside
click dismissal. It fits above or below its 44 px button, scrolls in limited
space and stays outside the phone panel's clipping area. Navigation hides the
old screen's popover. Three focused Chrome checks pass in 9.501 s at desktop
1280×860, portrait 390×844 and landscape 844×390, including real unobstructed
clicks, bounded popovers, unchanged design/URL, acknowledged versions and
cross-browser recovery. Initial runs caught a startup error and a copy button
covered before the asynchronous popup positioning; both were corrected,
keeping the visibility assertions and timeouts. The registered sync and client
geometry CTests pass in 1.53 s. The suite now registers 56 browser checks; it
has not been rerun in full for this UI change. The engine and storage model
are unchanged.

The URL is `/play?visitor=<random UUIDv4>`; a one-year HttpOnly, SameSite=Lax
cookie remembers the selected save (Secure on the public site). Keep the link
private: possession grants access to its progress and designs. Shared challenge
and design links do not contain this identifier.

`POST /api/profile` opens the save or writes a numbered revision to SQLite.
Progress, earned tools, recent challenges, drafts and the latest 30 versions
travel together. Browser storage is a cache and backup of unsent changes;
the server is authoritative for a clean cache. Old named browser profiles
migrate to distinct anonymous saves, retaining their progress and versions;
**Previous saves** offers anonymous links to the other migrated profiles.
Existing free-build and saved-design URLs continue to use the selected cookie.

Drafts debounce writes by 250 ms. Save version confirms success only after a
server acknowledgement; browser storage being full does not prevent a cloud
save. A failed request leaves the draft and dirty cache available and reports
that it is not synced. Saving again explicitly retries. Concurrent device saves
use revision comparison: progress is merged, independent designs are retained,
and conflicting edits to one design keep both complete histories, with the
local design becoming a **recovered copy**. This is conflict recovery on writes,
not a live multiplayer editor. A page closes its native world independently.

The database path is `BANJO_PROFILE_DB` (the image defaults to
`/data/banjo/profiles.sqlite3`). The [deployment guide](deploy.md) records the
pending public persistent-disk requirement. Local storage survives a server
restart; an unmounted Render filesystem does not survive a deployment, and the
page explicitly reports temporary storage. Public durability is not yet
verified. These changes do not alter any engine law, goal or score tolerance.

Anonymous-save verification uses the unchanged native SHA-256
`807ae9c34f0516a0d0dbf588400451b865083043d614cd1aab8040140c830f87`.
The five registered storage, HTTP, identity, sync and client-geometry CTests
pass in 4.96 s (8 SQLite, 14 HTTP, 4 identity and 11 sync checks, plus the
existing geometry suite). The full Chrome suite passes 53/53 in 265.909 s.
Two added browser regressions bring the registered suite to 55: cookie-only
recovery after clearing the cache, and a Unicode design larger than 64 KiB
saved and recovered in a fresh browser. Both pass in the scoped final run;
the complete 55-test suite has not been rerun.

One later focused run passes 10/11 and records a Chrome
`net::ERR_NO_BUFFER_SPACE` on `/api/machine` during named-save migration.
The same migration check passes separately in 1.978 s without code, timeout
or request-retry changes. Subsequent socket and memory counts do not establish
the failure's cause. This failed run remains recorded. Browser checks also
confirm a real earned win and immutable version recovery with no prior cookie
or cache, and successful server saves when browser storage rejects writes.

The preceding published `ca8d68b1` Linux CI passes 149/150 CTests; its only
failed target is the browser suite (48/50), reporting an enabled battery
terminal before Run and a covered solar-output target. New terminal buttons
now start disabled until positioned, and a power-meter update immediately
repositions terminal cards before the next animation frame. This closes
observed readiness gaps without claiming to prove the earlier timing cause.
The battery and exact moving solar-input checks pass with unchanged click,
contact and goal assertions on desktop and both phone orientations; the latter
passes separately in 4.862 s. A new Linux CI result is not yet available.

**Manual switches are operated on the field.** Drag the rocker itself or its
44 px **Drag handle** label; a six-pixel movement starts or resumes the whole
simulation and applies force to the native loose body. Its actual hinge angle
opens or closes the circuit, with Open/Closed and current feedback beside it.
A click or small jitter applies no force. Release, cancellation, Pause,
navigation and a second touch release the handle; two fingers then control the
camera. The initial-state setting chooses the physical starting pose, retained
by Save version and restored by Set up again. There is no queued Toggle action.

This field operation earns normal goal scores, and its measured work enters
run energy once. General Pull is still a test intervention earning zero stars.
Receipts now retain millijoules, so a small handle operation is visible. An
existing native Pull receipt gap can omit the last preceding step's work when
force changes or is released; the [material comparison and independent
audit](sandbox-electrics-measured.md#physical-manual-rocker-october-11-2026)
records that limitation rather than claiming full conservation.

Fresh switch, bulb and loop challenges use recipe v2. Older saved manual
declarations compile to physical handles without rewriting their stored input,
wires, identities, initial state or material. Version-1 recipes retain their
seed policy and raw declarations, then use that compiler migration. Paddles
remain automatically operated by physical hinge travel. The switch par is
18.7 MJ for its larger physical construction; the loop par is 1.75 J after
retaining its measured 1.747 J rather than rounding to 2 J. Goals, deadlines
and test tolerances are unchanged.

Manual-rocker verification uses native SHA-256
`807ae9c34f0516a0d0dbf588400451b865083043d614cd1aab8040140c830f87`.
Five mechanical regressions pass through their registered CMake target in
7.26 s; 19 electrical tests pass in 13.61 s; 42 game tests pass in 47.69 s;
12 recipe tests pass in 104.82 s. The 82-preset sweep gives 246/246 correct
nudged wins and zero of 246 empty or wrong wins; migrated version-1 switch,
bulb and loop shares win all nine checked nudges with no empty/wrong win.
Three old game receipt assertions now expect millijoule precision, retaining
their exactness; no tolerance was loosened. The source-registration guard
accounts for all 269 C++ sources. No native C++ law changed for this update. An abandoned-drag regression sends no release or refresh: the native force becomes zero after 1.18 s of wall time, retains 0.541 J booked input, keeps the world running and does not mark the run as a general Pull test.

The browser checks also exposed intermittent initial request/module failures.
An independent Windows transport comparison uses the actual server and full
`/machine.js` responses, without opening an engine: with the inherited five
pending-connection queue, three synchronized 64-client bursts return 54, 60
and 34 complete responses. The remaining requests reset, abort or time out.
With a queue of 128, all 192 responses are complete, with maximum burst
latencies of 0.031–0.034 s. Six/eight-client bursts pass both configurations,
though two old-queue eight-client bursts delay about 0.525 s. Seven host tests
pass in 1.49 s, and their existing CMake target passes in 1.82 s under its
unchanged 30-second timeout. The queue is enlarged without request retries.
These measurements establish a burst-handling defect and its fix; they do
not prove that the earlier Chrome `ERR_CONNECTION_REFUSED` had exactly that
cause. Browser navigation checks now require the new document and exact URL
before accepting Ready, with the same 90-second timeout. Delayed Run/Pause
commands are also bound to their original scene; a held-response regression
reproduces an unwanted second command before the guard correction.

The final focused browser run passes nine checks in 32.20 s with the larger
queue: field handle motion/current/scoring, saved pose/reset, force release,
old-scene command rejection, holder setup, tray carousel, View/Move, Run
cancellation and preview. Desktop 1280×860, portrait 390×844 and landscape
844×390 retain visible 44 px handle targets and reachable scene actions.
The full browser suite now contains 50 checks. Earlier failed runs are not
counted as green: one obsolete v1-link fixture was stopped, then the 49-check
runs passed 48 and 47 checks with initial request/module failures; the exact
historical transport cause remains unproven. The client geometry CTest and
JavaScript/Python syntax checks pass.

The following is the preserved v2 contact-holder checkpoint; the current v3 lesson is described above.

**Give it power** in v2 teaches physical electrical contact. Drop the battery pack onto the holder's two metal pads; the prepared floor leads run from those pads to the lamp. The case, two glass spacers and two metal terminals are separate material bodies held together by fix joints. Both terminals must actually touch pads to close the loop. Rotate the pack, change its release height, position or initial charge, and inspect the terminal cards for pad contact, battery joules and lamp watts. A crosswise or misplaced pack stays dark; lifting the pack off the pads breaks the circuit. Reversing the pack still lights the resistive bulb. The target remains at least 2 W for 0.5 s within 4 s.

The editable **Drop a battery into its holder** sandbox example uses the same apparatus. **Save version** preserves its initial position, rotation, release height, housing material and charge, with the holder and wires in the saved base. Dry sandbox designs retain fixed batteries and their existing explicit wires. The battery's fixed/contact-pack mount selector changes its construction; release height, pack rotation and housing material apply to contact packs. Terminals, contact guides and floor leads follow the actual moving cap bodies; charging sockets and solar leads also follow the moving housing. The contact pack shows a charging input only when a collector or charging cable is present. Starting or continuing a live run clears pending predictions, so an earlier failed rehearsal cannot contradict the live lamp reading. Dashed guides show possible contact paths, orange while open and green while touching; they are not wires. Flow rehearsals are labelled Preview, with measured live readouts after Run.

At the contact-holder checkpoint, fresh seeded Give it power challenges used recipe v2. Existing v1 shared URLs retain the earlier fixed-battery, prepared-wire apparatus and its seed policy; At that contact-holder checkpoint the other families retained v1; the manual-rocker update above also versions switch, bulb and loop. No old saved declaration is rewritten. New canonical construction cost is 374,768,000 J, with 2 J consumed by the measured goal; its 375 MJ par is the three-significant-digit ceiling of that score, replacing the larger fixed case's par.

Contact-pack measurements and model limits are recorded in [sandbox-electrics-measured.md](sandbox-electrics-measured.md#physical-battery-holder-october-11-2026). This uses the existing native contact and circuit laws; no goal, deadline, conservation tolerance or native binary changed.

Native verification for this update: nine contact-holder regressions pass through their CMake test target in 7.3 s; 15 electrical tests pass in 11.0 s; 42 game tests pass in 47.8 s; ten recipe tests pass in 100.4 s. The 21-family, 82-preset sweep produces 246/246 correct nudged wins and zero of 246 empty or wrong wins. All four v2 lamp presets pass at 0.933 s with measured scores 374,768,002.67–374,768,003.67 J. Legacy v1 shares reopen after cache loss and win all six checked nudges at 0.583 s. The client geometry CTest, Python/JavaScript syntax checks and all 269 CMake source registrations pass.

Browser verification: the final full Chrome suite passes 47/47 tests in 248.9 s at 1280×860, 390×844 and 844×390. New checks cover native falling terminals, two closed pads and a powered lamp, misplaced/depleted controls, saved charge/base/version restoration, and a charging lead following the moving pack. Live runs clear stale predictions immediately, including after a win. The first 46-test run had a phone save fixture click Set down before its asynchronous fit check finished; the fixture now waits for that existing check, without changing timeouts or assertions. The moving-lead fixture uses an in-view collector so ordinary visible terminal clicks can reach it. The previously intermittent solar click case passes this full run; this is not a claim that its earlier unrecorded cause was diagnosed.

The sandbox catalogue has 31 placeable cards, plus the Attach tool. Its 25 prebuilt designs are editable copies. The full-screen library has routing, motion, supports, power, optics, electricity and water categories; **Try example** opens a saved copy that supplies the required environment or connections. Water cards explicitly require a collection-channel base. The knife, mirror, lens, solar panel and block-and-tackle are now independently available alongside springs, gears, weights, motors, batteries, switches, bulbs, wires, finite water tanks, water wheels, heating coils and the counterweight catapult.

| Card/tool | Controls and supported behavior |
|---|---|
| Knife | Position, pivot height, arm, blade/weight geometry and orientation; native edge cuts material |
| Mirror / lens | Size, height, orientation, convex/concave curvature; traced reflected/refracted power |
| Solar panel | Size, orientation, chosen battery; finite battery charges from declared sunlight; dark empty designs create no power |
| Block and tackle | Load, counterweight and pulley ratio; included supported load or existing moving load |
| Spring | Guided material load, stiffness, relaxed length and internal damping; Attach also joins two picked points with a spring |
| Gear / weight | One toothed wheel: size, tooth alignment, axle height, bearing friction and material; separate wired motor supply. Weights have size/material and loose/guided/hanging mounts. |
| Battery / motor | Fixed or falling contact pack, release height, rotation, housing material, voltage, capacity, charge and power limit; direction/throttle and included or selected physical axle |
| Switch / bulb / wire | Force-dragged manual rocker with glass/oak/iron handle and saved initial pose, or real paddle switch; bulb preset and explicit terminals; crossing wires never connect |
| Fixed water tank | Starting litres, tap opening, outlet position and height; gravity head sets the flow, and a subparcel remainder stays in the tank. Legacy saved metered outlets keep their original settings. |
| Water wheel | Radius 25–65 cm, position along/across the river, optional falling supply and drum load; current forces act on immersed paddles |
| Ignition coil | Selected material target and heater preset; wired electrical input becomes heat; oak combustion remains experimental |
| Catapult | Cock angle, aim, material/size of counterweight and marble, loaded/empty cradle and held/released restraint; actual contact launches the marble |

**Valves and release**, beside the 3D scene, queues water-valve and catapult-restraint operations between engine steps. **Try It!** continues that same session; **Set up again** restores the saved initial state. These live operations do not change a saved version. Manual switches instead use their physical field handles. Prepared, player-placed and flow-preview wires use the same thick floor routes, with short leads up to the actual terminals. Wires brighten yellow from measured current, and bulbs glow from measured emitted optical power. Removing a device removes its attached wires and renames surviving references; Undo restores the graph. Saved versions and shared links retain the initial parts, connections, charge, water, preload and restraints.

**Draw wires directly in 3D (October 12).** When the tray has wires, small rings at the actual declared/body-transformed terminals can be clicked without opening a disclosure or selecting a Wire. Click one ring, then another to validate and save a wire through the same server/engine path. Adding a Wire from the tray enters the same interaction. The selected ring turns amber, a dashed provisional line follows the pointer, and the selected terminal's name appears above the scene. Esc or clicking the first ring again cancels without saving. Primary drags, camera rotation, two-finger gestures and live runs cannot commit wires. The rings use **+/−**, **In/Out** and **A/B** labels. A mouse click searches within 22 px; touch searches within 28 px. Nearby candidates whose pointer-distance difference is under 8 px offer a short list of labelled 44 px buttons instead of guessing. Points under interactive scene UI or outside the view are excluded; zoom/turn to inspect them. Solar cables accept input-first or output-first clicks. Endpoint dropdowns remain in **Precision controls**, with wire thickness/length as the ordinary knobs. The optional **Connect wires** buttons remain accessible alternatives. The provisional line is an editing guide, not measured current or a physical conductor.

Ten focused Chrome cases cover direct canvas clicks/touch on all three viewports, cancelling and gesture quarantine, ambiguous-point choices, solar input-first wiring with/without the cable tray, native loop/solar wins, saving/reloading/Undo/version restore, the existing accessible buttons and trackpad zoom. Five wiring/layout cases passed together in 44.6 s after reserving connection-ring space so power labels cannot cover them; the saved-graph and existing-control cases passed in the earlier targeted batch. The final connection-status wording has a direct-wire/solar rerun. The native executable remains SHA-256 `0bcf6978067ec59ab0b89325abb8feef051e398594169c602e664a989e2883a0`; no native laws, timesteps, goals, pars or conservation tolerances changed. This is interface verification, not additional circuit-model validation.

**Finish the loop** teaches drawing a wire: connect **lamp −** to **supply −**, then run the circuit. An additional supply lead cannot replace its missing return path. **Marble turns on a light** keeps its prepared circuit and teaches placing the paddle; its socket leads are visible while adjusting the switch, before setting it down. Those prepared leads use the same drawing as wires a player places in advanced builds. Solar charging sockets are hidden in circuit lessons that have no collector or charging cable. Terminal buttons are read-only where the tray has no wires; a crowded sandbox can hide labels that do not fit without covering the scene actions, so pan or zoom to inspect another device.

Cable routes are visual geometry, not simulated physical cables: they do not change resistance, add mass, collide with pieces or make junctions at crossings. No electrical law, level goal, solution or tolerance was changed for this UI update.

**Click a wire to remove it (October 12, owner correction).** Click a player-placed electrical wire or solar cable in the scene to delete it, then click two connection rings to draw its replacement. Undo restores the exact deleted endpoints, thickness and declared length; Redo removes it again. A click during a live run first rebuilds a paused starting setup. Drags still rotate the camera. Crossed/overlapping wires offer labelled 44 px Remove choices; authored puzzle wiring stays fixed. Picking uses the rendered route/curve with 14 px mouse and 24 px touch margins and excludes segments behind solid meshes. Terminal rings still start a wire. The enlarged terminal hit margin no longer captures case clicks on a placed component: a click outside the actual 9 px ring on the case opens its adjustment unless wiring was explicitly started. A level's exhausted tray card reopens its first placed piece instead of staying disabled; Sandbox exhaustion is unchanged. After placing a battery, levels with wires available keep a short ring-to-ring wiring prompt visible. These are editing aids, not a physical flexible-cable or unplugging model. Multiple wires may share a terminal; crossings alone remain separate, and the native circuit solver decides their current.

**Choose and see wire gauge.** A wire ghost's thickness control offers visible Thin / Standard / Thick buttons (44 px minimum targets), with the selected choice marked. The same buttons appear when picking a placed wire by clicking its gauge label. Labels beside placed electrical wires show their declared copper cross-section from the compiled electrical graph: thin 0.01 mm², standard 0.5 mm², thick 2.5 mm². These are cross-sectional areas, not AWG numbers. They remain visible with zero current; flow dots still depend on measured current. Legacy low-resistance wires show their declared resistance instead of an invented conductor gauge. Solar cables retain their existing ideal-lead model and do not claim a physical gauge. During a gauge check the label says Gauge updating. The existing engine computes copper resistance from length and area; this change adds no new conductor law. Thicker wires reduce voltage loss in a completed circuit and cannot close an open return path.

**Reading callouts at the scene edges.** Power and wire labels choose the left or right edge, wrap within a bounded width and use a muted, one-pixel dashed leader to the displayed component or rendered cable midpoint. Their layout reserves the projected electrical/solar component bounds, connection rings and action overlays; crowded overflow remains in Controls rather than covering controls. Solar endpoint callouts and electrical connection buttons also use the edges. Water-container litres/deadline meters have matching leaders to the measured volume. Leaders are editing annotations, not powered wires; they do not intercept clicks or change the circuit. Camera turns update the anchors. The preview Play/Pause label now updates immediately when a rehearsal or its playback state changes.

Callout checks, October 12, 2026: eight focused browser cases passed across the final checks, covering wire/battery controls, scene-edge callout geometry, solar and cable feedback, fill deadlines, water diversion, plumbing saves and the preview timeline at 1280×860, 390×844 and 844×390. The new geometry case checks three visible callouts before and after a real camera drag: their boxes avoid the protected components, their leaders meet the label boxes and start within 2 screen pixels of the rendered cable midpoints. Early checks exposed fractional CSS box rounding and a mismatch between sampled and displayed cable routes; leaders now use the actual label rectangle and rendered curve. A browser fixture also raced the preview disclosure; it now opens the real disclosure and waits for the visible Play/Pause control. The final battery/preview rerun passed in 32.5 s; six other focused cases passed in the preceding run. This changes client layout only, using engine SHA-256 `0bcf6978067ec59ab0b89325abb8feef051e398594169c602e664a989e2883a0`. It changes no physical law, timestep, goal, energy accounting or conservation tolerance. Source registration and local document links remain checked before publication.

Seven targeted Chrome cases pass, including electrical/solar rewiring on 1280×860, 390×844 and 844×390, both solar endpoints, complete disconnection, native open-loop failure and restored-loop success, live-edit pause/reset, camera-drag quarantine, prepared-wire protection, saved versions/reload/Undo and the prior direct-wiring/trackpad checks. Six ran together in 49.8 s; the prepared-wire/drag case passed separately in 1.7 s. Native engine SHA-256 remains `0bcf6978067ec59ab0b89325abb8feef051e398594169c602e664a989e2883a0`. No native law, material, timestep, goal, par or conservation tolerance changed; no new physical wire model or conservation validation is claimed.

The preceding endpoint-lifting interface and footer were verified in 37.1 s before the owner's correction to click-to-delete. That historical result does not verify the new interaction. Precision endpoint edits remain available by picking up a wire through the placed-piece controls.

Wire correction verification, October 12, 2026: nine focused Chrome cases passed in 79.7 s at desktop 1280×860 and phone 390×844 / 844×390. The battery case and its tray card reopen voltage controls. Real connection-ring clicks draw both leads; visible gauge buttons remain unobstructed and at least 44×44 px, update their selected state, and survive committing the wire. Two mistaken leads sharing lamp minus are allowed by topology; clicking one removes only that lead, Undo recovers it, and redrawing a complete loop works. Thin 0.01 mm² leads measure about 8.8 V / 1.6 W at the lamp; standard 0.5 mm² leads measure about 11.9 V / 3.0 W and meet the unchanged goal. The test explicitly plays a paused electrical preview before checking current and voltage. Cable gauge labels agree with the compiled conductor area. Solar deletion works from either end and during a live run; Undo restores its endpoints. Saved versions retain a deletion across reload and restore the complete earlier graph. Authored wires remain fixed; drags and two-finger camera gestures do not delete or connect. All 269 source registrations, JavaScript syntax and 65 local document links pass. This changes client interactions and displayed declarations only, with the same verified engine SHA-256 `0bcf6978067ec59ab0b89325abb8feef051e398594169c602e664a989e2883a0`; no conductor model, physical goal, energy budget or conservation tolerance changed.

Wiring UI verification, October 11: all 35 Chrome browser tests passed in 173.2 s, including desktop 1280×860, portrait 390×844 and landscape 844×390. Checks covered terminal clicks, cancelling a pending wire, wrong-wire failure, the correct loop's native win/current, prepared switch leads before Run, and saving/reopening/Undo/version restoration. All 12 electrical tests passed, including nominal/nudged solutions, missing returns and the existing glass/oak/iron heating comparisons. The client geometry CTest and all 269 source registrations passed. The tested native executable remains SHA-256 `569a441595274e13128e1b8f06ff54d392232409b312d2089a77c2451315c976`. A prior Linux browser test read the clock before it existed during reload; the ready wait now handles that DOM gap with the same timeout, and the affected saved-solar test passed again locally.

The chooser includes twenty-two lesson families: cut, reflection, focus, sunlight, tackle, water wheel, river wheel placement, spring, gears, weight, motor, battery, switch, bulb, closed loop, receiver fill, ignition, catapult, marble switch, water gate, sunlight-powered lift and river-powered lift. Every family has its own private solution, three nominal/nudged engine checks and physical empty/wrong controls. Goals also include sensor power, sustained electrical power, stored charge and actual water received; a green box is shown for spatial goals.

Mechanical and water catalogue bases contain no decorative reference-marker boxes. **Turn the big wheel** now starts with independent powered and target gears; the player sizes and places a single contact gear between them. The historical empty-field measurements below describe the earlier apparatus. Water-channel setups retain their ground and any functional receiver, guide or load. Previously saved designs retain their saved parts. No goal, solution or physical tolerance changes accompany this cleanup.

Empty-field verification: six introductory lessons open and step with zero native solid bodies. Their initial-scene assertions now require an empty field; other lessons still require their necessary starting parts. The loader distinguishes an explicitly authored empty array from the legacy test fixture, and empty worlds save/restore without inventing bodies. Full native LiveWorld verification passes 36 checks, with five selected terrain/water checks. An empty 100 L/s flume at 1/240 s over one second retains 0.1 m³, with volume residual −1.53×10⁻¹⁶ m³; dry flow retains zero. No contact, material or fluid-force law changes accompany this loading behavior. The game suite passes 42/42 in 48.572 s, water/launch 10/10 in 18.434 s, and seeded recipes 8/8 in 98.185 s (246 correct nudged wins, zero empty/wrong wins). The final browser run passes 42/43 in 276.647 s: the previously reported solar cable-click timeout recurs on landscape, while the new empty-field gear test and river checks pass on all three viewports. The unchanged solar test passes two isolated repeats (12.744 s and 12.703 s) without click retries or relaxed assertions; its cause remains unproven and it remains a QA limitation. Manual portrait play wins the gear lesson at 1.40 s, and desktop/phone screenshots show an empty starting field. Source registration passes 269/269. The verified executable is `build/agent-integration/empty-native/banjo_live_world_run.exe`, SHA-256 `807ae9c34f0516a0d0dbf588400451b865083043d614cd1aab8040140c830f87`.

Per-material measurements, conservation receipts, timesteps and limits are in [mechanics and optics](sandbox-mechanics-measured.md), [electrics](sandbox-electrics-measured.md), and [water and launch](sandbox-water-launch-measured.md). These models do not implement free sloshing/tipping buckets, calibrated involute gear profiles or tooth stress/failure, realistic incandescent filaments or calibrated spreading fire. Falling-water ledgers close, but the coupled channel/rigid pipeline is not a complete conservation proof. The counterweight launch is measured experimental behavior; a spring catapult preset remains future work. The combined sunlight challenge uses a direct gravity-loaded motor arm and reports shaft, load, bearing and numerical-correction energy.

Integration verification used `build/agent-integration/Release/banjo_live_world_run.exe`, SHA-256 `b98d68d42734536b6bacc3ca008690d061d7e89fab290ca42bfc1235b0a3161a`. All 147 applicable CTest entries passed across the full run and the corrected browser/water rerun (long/performance labels excluded). The browser suite passed 24 tests, including desktop, 390×844 portrait and 844×390 landscape, explicit wiring, version restoration and queued live controls. The game suite passed 37 tests; the added mechanics/electrics/water/combinations suites passed 11/7/8/2 tests. Source registration accounts for all 269 C++ sources. No complete rigid/fluid/contact energy closure is claimed by these results.

The catalogue checkpoint was published as `874c2796`; `banjo.is` served that header and its water-wheel example poured 12 litres and turned its axle in a live browser run. That catalogue checkpoint used the tested executable above; the solar update below records its replacement.

## River workbench

In Sandbox, **Build beside a river** starts a channel with an upstream supply and a guided gate. Add a water wheel, place its lower paddles in the current and choose **river gate** as its **drum load**. River designs start new wheels at 65 cm radius with the falling-water supply Off; the stream still drives them. **River powers a lift** opens the connected example. These two designs add no new wheel-driving law: the existing engine calculates water pressure/drag and paddle torque. **Off** switches off the separate falling-water feed, not the river's upstream supply.

The straight river fills from its west boundary when Run starts, flows along x and leaves at the east boundary; it starts dry, with no hidden reservoir. The setup preview shows its predicted water/current before Run. Static arrows represent native sampled velocity, quantized at 0.05 m/s per axis (clipped at ±6.35 m/s). They do not animate an invented current. Ready/live water, the flow preview and Engine readings expose direction, sampled speed/depth and measured inflow/outflow. Preview packets retain at most 96 velocity samples and 512 surface tiles per frame. Pause/scrub selects an engine-rehearsed snapshot. Saved versions retain the river declaration, wheel position and named drum connection, not elapsed runtime.

In this lesson the wheel has a fixed 65 cm radius; its connection control is a
**Connect rope to gate** button instead of a load dropdown. Sandbox keeps the
adjustable wheel sizes and general drum-load picker, which excludes fixed
objects from new choices while preserving an existing saved connection. The
marked channel and **Wheel on bank** cue identify the placement task. Preview
readings show measured wheel turn and gate rise; the win result appears beside
the scene in Controls.

**River-powered lift** teaches placing the wheel in the current to raise the gate eight centimetres within ten seconds. Its 65 cm oak wheel puts the drum's lower rope departure above the gate's target position. The default flow is 100 L/s; seeded versions vary the actual upstream supply to 95, 105, 110 or 120 L/s. At the game's 1/240 s step the nominal solution and all three nudged runs reach the unchanged target at about 4.10 s. The generated settings reach it at 4.383, 3.85, 3.65 and 3.35 s; bank placement, dry/no-flow, no wheel and no drum connection fail physically. The existing twenty seed families and their version-1 identities keep their meaning. River scoring currently accounts for construction and the game's existing energy inputs; complete hydraulic boundary work is not available in that score. See the [river measurements and limits](sandbox-water-launch-measured.md#river-current-wheel).

River UI verification: both new browser tests pass, including the lesson's native win at 1280×860, 390×844 and 844×390, saving/reloading/restoring the river base and rope connection, and restoring the dry example's 40 cm/Left defaults. Sparse saved placements now display their compiled defaults when edited; full and compact connection selectors stay synchronized. The selected tray card survives Set down and rebuild. Manual portrait/landscape review kept Run/Pause/Reset and the river scene visible. The final broad browser run passed 41/42 in 271.367 s: one existing portrait solar input click did not append its cable. The unchanged solar test then passed six repetitions (18 viewport flows), including four preceding-state checks; no clicks were retried or tolerances relaxed. Its cause remains unproven and intermittent click behavior remains a QA limitation. The earlier pre-editor-fix broad run passed 42/42 in 213.186 s; it is not substituted for the final result.

## Solar feedback and explicit power leads

The collector has a small, non-interactive watts marker in the scene, which
does not block object dragging. **Controls** in Controls contains
the full meter in challenges and the sandbox: incident sunlight in watts,
power accepted by its battery in watts, current
stored energy in joules, and angle off the sun. It updates while running and
also measures the ready setup without advancing time or adding charge. A full
store accepts no charging power even if sunlight still reaches the panel.
The ghost's aiming estimate is labelled **before shade**; set it down to see
the native measurement.

Solar shading currently uses one ray from the center of the collecting face,
offset 10 mm outward, toward the declared sun. It tests the engine's actual
collision shapes. A blocked center makes this model shade the entire
collector; it does not integrate partially lit area or transmit through glass.
The visual shadow map is illustrative. **In shadow · …** names the
measured obstruction, and an orange dashed ray ends at its actual hit point.
A clear collector draws a short yellow ray toward the sun. The unrecoverable
earlier player placement did not establish a specific false pillar hit.

In **Catch the sun**, place and aim a collector, then open **Readings and
wiring** and press **Connect wires**. Tap **Out** on the collector and **In**
on the winch. These small scene endpoints appear only while wiring; connecting
a solar lead hides them again. This saves a visible **power cable**. Its
absence leaves the winch's battery empty: collection goes into the panel's
own finite store and cannot lift the weight. Click an output and a different
input to replace its connection. Remove its cable to disconnect it. Esc
cancels an unfinished connection and hides the endpoints; **Finish wiring**
does the same. Wiring rebuilds the setup at time zero.
The same ports support charging a placeable battery in a saved sandbox design;
the battery's plus/minus terminal graph powers bulbs, motors and switches.
Existing prepared sandbox declarations retain their declared charging store.

`electrical.power_ports` identify a solar output or finite-battery input by
name, housing and world position; `electrical.power_cables` save their explicit
connections. The **Power cable** card also offers endpoint selectors. A cable
is an ideal two-conductor charging lead, with no modeled mass, resistance,
voltage conversion, sag, breakage or heating. Each output and receiver accepts
one cable; parallel solar sources are unsupported. Collection, battery
saturation and motor torque remain native calculations. Cable endpoints follow
piece edits, rename with piece indices, and in saved sandbox designs survive Undo, reload, version
restoration and shared saved declarations; removing an endpoint removes its
cables.

Measured with `build/agent-integration/Release/banjo_live_world_run.exe`, SHA-256
`569a441595274e13128e1b8f06ff54d392232409b312d2089a77c2451315c976`:
the original winch solution wins at 2.400, 2.450 and 2.383 seconds under the
three nudges; disconnected, flat and shaded controls fail. Its goal, deadline
and energy par are unchanged. An aligned ready collector reads 250 W sunlight,
50 W charging and 0 J stored. At `dt = 1/240 s`, one second gives
250 J sunlight = 50 J collected + 200 J conversion heat, with residual
−1.56 × 10⁻¹² J. An initially full 100 J receiver spills the 50 J instead,
with zero change to its reserve. These are solar/store accounts, not proof of
full motor/contact energy closure. Native solar and sun-day suites pass 11
and 7 cases. The full game suite passes 39 tests (all 28 solutions, three
nudges each); the electrical suite passes 11. Host, world, physics, live
controls and view integration also pass their targeted CTest entries.
The complete browser suite passes 27 tests, including ready-state metering,
real output/input clicks and native wins at 1280×860, 390×844 and 844×390,
unobstructed 44 px targets, moving both endpoints and saved graph restoration.
Source registration still accounts for all 269 C++ sources.

## Light, water and current in the build preview

The same engine rehearsal that draws a marble's path also samples light,
falling water, wet channel surfaces and wire current. This works in challenges
and saved sandbox designs, including a fitting ghost as if it were set down.
Dashed pink lines follow native reflected/refracted rays. Blue dots show the
native falling parcels and translucent blue tiles show measured wet surfaces.
Yellow wire arrows show **conventional current**, with the direction taken
from the signed native branch current. Number labels appear while wiring or
when **Flow preview** is open, rather than covering objects during ordinary
placement. An open circuit
has no arrows. A solar charging lead reports watts instead; this ideal lead
does not have a modeled voltage/current conversion. Bulb preview glow follows
measured emitted optical power.

**Flow preview** in the combined control panel plays the sampled timeline
automatically. Open it to pause, replay or scrub **Preview time** and read
released/remaining water and electrical power. The actual world's clock stays
at zero: this does not run the live machine, drain its battery/tank or change a
saved design. Editing rebuilds the rehearsal; outdated flow responses are
discarded. The flow layer hides during the live run, when the ordinary native
readings and water/rays take over. A stopped or unfinished rehearsal is labelled
incomplete. Run/Pause remains visible while the expanded panel scrolls on a
short phone screen.

**Laser preview** stays visible in optical setups without opening Flow preview.
Moving or adjusting a piece requests a separate short native trace; the last
path remains labelled **Updating laser preview** until the latest answer arrives.
The receiver's measured watts appear in Controls. This sample takes four
ordinary 1/240 s steps (1/60 s total) in an isolated engine, establishing the
lamp's initial circuit power; it predicts neither a later switch action nor a
win. It does not consume the live battery, run the level, or alter a save.
Requests coalesce and stale answers are discarded. Run clears this setup layer
and shows actual native rays. The full rehearsal still owns water, wire-current
and moving-object timelines.

October 12 optics checks: the authored Find the focus lens receives 7.31342 W
at the short sample; moving it 30 cm across misses the 2 W goal. Fifty mounts
cover all five tray diameters, convex/concave shapes and five representative
orientations, including combined turn/tip/roll. Their native light-power ledger
residuals are below 1e-10 W; the focus sample's light-energy residual is below
1e-10 J. Local trace time was about 20–70 ms, excluding network and debounce.
All three optical lessons still solve in three nudged runs each and meet their
unchanged energy pars. Native optics/light-spot tests retain their existing
refraction, heating and ledger checks. The new circular-holder test compares
equal geometry at five rolls: glass fits; opaque oak and iron remain refused;
offset glass outside its holder remains refused. These are optical/containment
checks, not new contact or full mechanical-conservation validation.

Lens outlines draw the two native spherical faces at their actual aperture.
The 44 px drag marker enlarges the visible interaction cue, not the glass or
its collider. Thin-holder grid construction now moves the attached optical
glass with its holder. Native containment bounds the circular aperture instead
of an arbitrary square around it; the tenth-cell geometric allowance, holder
mass, material laws, optical aperture and scoring are unchanged.

Samples use the existing 0.1 s readout cadence, spaced further apart for a
longer rehearsal (`max(0.1, horizon/180)`), with a final sample. Geometry is
bounded to 32 representative traced rays, 128 falling parcel positions and
512 wet cells per sample; the full native volume/current readings are retained.
The free-design rehearsal keeps its existing maximum 12.3 s horizon and can
stop half a second after all underlying machine stations finish. Playback holds
the last sample between timestamps. Water has no persistent parcel IDs in
the protocol, so successive array entries are never joined into invented
trajectories. Wire curves and arrows are display annotations, not moving
electrons or a propagation-speed model. Future flow is shown over the initial
setup and its existing body paths, rather than moving every solid body in the
preview.

The native regression compares a closed circuit (~0.2496 A) with an open
circuit (<1e-8 A), reverses a wire's endpoints to check its current sign, shows
a finite 4 L source stop emitting before 3 s while the channel remains wet,
and verifies the reflected laser solution and blocked control. The water
volume residual stays below 1e-8 m³. Native physics, materials, timesteps and
conservation tolerances are unchanged; these are checks of sampled display
data, not new physical models or a full energy-closure claim.

Measured on 11 October 2026: all 40 game tests pass (46.744 s), including each
level's three nudged solutions. All 30 browser tests pass (127.437 s), with
real preview buttons, paused scrubbing, water-valve edits, Save version and
All designs at 1280×860, 390×844 and 844×390. Existing solar output/input clicks
and tackle selection also pass. Host, world, live-control and view integration
pass their four CTest entries (21.28 s). Source registration accounts for all
269 C++ sources. The unchanged tested Windows engine SHA-256 is
`569a441595274e13128e1b8f06ff54d392232409b312d2089a77c2451315c976`.

## Previously generated easy challenges

October 13: **New challenge** is removed from player controls. Existing seeded links and **Return to a challenge** remain supported. The retained server generator covers twenty families. It changes one bounded physical input: source power, sunlight elevation, supply voltage, cord or lever length, load height, bearing friction, starting water, flow or catapult cock angle. Prepared settings are fixed in that challenge's tray; its goal and deadline remain the family's own. There are 78 physical presets across the twenty families; different seeds can select the same preset. This is repeatable authored variation, not unlimited procedural geometry or a language-model-generated level.

Before offering a setup, the server rehearses its private solution, empty machine and wrong setup with three nudges each. All three correct runs must win and every empty/wrong run must fail without engine errors or incomplete rehearsals. It tries at most three seeded candidates, then a checked original setup; the page explicitly identifies that fallback. It refuses the request if even the original fails. Public responses contain no solution, wrong placements or private rehearsal receipts. Native preflight shares the server's two preview slots and reliability-check request allowance.

Versioned recipe IDs include family, seed and accepted attempt. **Share** exposes a canonical `https://banjo.is/play?level=…` link to that exact recipe. The last twelve generated challenges appear under **Return to a challenge** inside the chooser’s **More** menu for the current anonymous save. Shared recipes are verified on their first request to a server/engine; an in-memory bounded cache avoids repeating the work on subsequent requests. Energy par is the actual three-run mean rounded upward to three significant figures, including measured water source work. Reopening recreates the initial puzzle; **Set up again** retries with the pieces currently placed.

The native sweep passed all 78 presets: 234/234 correct nudges won, 0/234 empty and 0/234 wrong nudges won. Goals and deadlines were unchanged. The sweep took about 90 seconds on the integration binary; its eight-test suite also checks seed identity, bounded retries, fallback refusal, native errors and incomplete negative runs. Delivery regressions verify exact recipe reopening after cache loss and keep water work in rehearsal energy receipts. The full game/browser suites now contain 39/25 tests, including generated challenge → terminal selection → native win → share/reload → recent replay on desktop and both phone orientations.

## Playing a level

**One control panel.** The tray, Run/Pause, Reset, Attach, Undo/Redo, camera turn/zoom buttons and the selected piece's movement and adjustment controls share one module. It stays on the right on desktop and phone landscape, and below the visible scene on phone portrait. Scrolling the phone panel leaves the scene visible. Camera buttons turn or zoom the view without moving the ghost. The live valves/release disclosure is in this panel too; manual rocker handles stay on the scene.

Tray carousel verification, October 11: all 37 Chrome browser tests passed in 186.1 s, including desktop 1280×860, portrait 390×844 and landscape 844×390. Checks cover single-card trays, wraparound browsing without a new engine setup, clicking the selected card, cancellation, the full library, saved versions, eight placed batteries exhausting their sandbox card, and unobstructed 44 px arrows/actions. An independent four-test agent run passed in 29.0 s. Phone checks now scroll the real pane and open the Tools disclosure before inspecting its controls; each phone-tab case creates an independent design. Terminal buttons also refresh when a wire connection finishes, addressing a timing failure in the previous Linux CI run; the saved-wiring check passed three repeated runs. The client geometry CTest and all 269 source registrations passed. This changes the page controls, not physics, energy accounting or the save schema; the native executable remains SHA-256 `569a441595274e13128e1b8f06ff54d392232409b312d2089a77c2451315c976`.

Undo toolbar verification, October 12, 2026: six focused Chrome regressions passed in 41.2 s. The new check exercises levels and independent Sandbox designs at 1280×860, 390×844 and 844×390, with unobstructed buttons at least 44×44 px on every tab, and Undo while the panel is collapsed. Placement, adjustment, removal, Redo, circuit reconnection/disconnection and saved-version restoration retain the original setup. Separate local browser play and screenshots cover desktop and phone layouts. The source registration guard passed for all 269 sources. This changes the client toolbar only, with native engine SHA-256 `0bcf6978067ec59ab0b89325abb8feef051e398594169c602e664a989e2883a0`; no physics law, timestep, goal, energy accounting or conservation tolerance changed.

**Adjust a placed device.** Click its solid parts or rope. A tackle's connected crate also selects the tackle when it has a single owning pulley device; for a shared load, click the device itself. Thin ropes have a six-screen-pixel selection margin. Picking up during or after a run restores the initial setup and opens the ghost at world time zero; it does not start the live simulation. A late reply from the old run cannot restart the editing session. Set down commits the adjustment; Cancel restores the piece.

Reset and compact-toolbar verification, October 12, 2026: 14 focused Chrome regressions passed in two batches (eight in 95.9 s, six in 59.0 s), at desktop 1280×860 and phone 390×844 / 844×390. Reset clears a challenge after a win or during an adjustment, restores the tray, discards the pending ghost and returns native time to zero; Undo recovers the last completed setup. Sandbox Reset preserves its base, pieces, saved versions and selected tab. Restart with my pieces retains circuits, solar connections and water routes while returning their native state to zero. The first broader phone check exposed the preceding two-row toolbar reducing the control pane below its existing minimum height. The final toolbar puts Undo beside Run/Reset in one row and moves Collapse/Expand to the scene corner; the original pane-height checks now pass without changing their thresholds. Local browser screenshots confirm the layouts. All 269 source registrations and 65 local document links pass. This changes client controls only, using the same engine SHA-256 `0bcf6978067ec59ab0b89325abb8feef051e398594169c602e664a989e2883a0`, with no new physics or conservation claim.

Checked on October 11, 2026: all 29 Chrome browser tests passed in 112.5 seconds, including real clicks on the tackle rope and crate, post-win adjustment, separate camera movement, and visible unobstructed 44 px action buttons at 1280×860, 390×844 and 844×390. The tackle solution reaches its unchanged goal at 3.70 s. The final compact layout also has a targeted tackle/phone rerun. This page change uses the previously verified solar checkpoint engine; no native physics, timestep, conservation tolerance or material model changed. Source registration still covers all 269 C++ sources.

- **The goal** is a green box drawn in the scene ("the ball is in the cup") and a time limit. The engine checks it on every step: the goal happens when the named part's centre is inside the box.
- **The tray** is one large clickable pictured card at the top of the control panel beside the 3D view. Its 72 px thumbnail, piece name and remaining count replace the small Add button and the duplicate tray list lower down. Click the card to add its see-through **ghost**: it is not in the machine yet. When there are multiple piece types, **Previous piece** and **Next piece** arrows cycle through them and wrap at either end; an index shows which card is displayed. Browsing does not place a ghost, change the build or rebuild the engine session. Cancelling placement returns to the same card. A single piece type has no arrows, and an exhausted card is disabled. The sandbox's 31 cards can be browsed this way, while **Add a piece** still opens the full library with search and categories. The pictures are drawn in the page from the piece's own parts, as the server would build it. A level whose goal is about a piece (level 4: the engine's piston) opens before that piece is placed, with its goal zone drawn, and says what it needs.
- **The ghost is placed at once**, where the middle of the view meets the scene, ready to change. Drag it or use the arrows to adjust it. A scene click or tap never relocates it; it returns to View. Set down or Try It! confirms placement.
- **Moving it, as 3D builders do.** A primary drag may start anywhere within 40 pixels of the ghost, not only on its own few pixels (a mirror seen edge-on is three pixels wide); the hand cursor marks this grab area. It starts moving only after the pointer travels at least 6 pixels. It then slides on a level plane at the height it stands, by however far the pointer moves: it never jumps onto whatever is behind the pointer, so it can be pulled out from behind a wall. The same grab margin and drag threshold apply on phones. Two fingers turn and zoom the view; after one finger lifts, the remaining finger stays a camera gesture until it also lifts. Empty-space drags turn the view. Right/middle mouse drags and Ctrl+drag turn the view even over the ghost, while the editor remains open. A drag keeps its grab offset and does not set the piece down. Wheel zoom also works while holding it: the grab ray is rebased so a stationary pointer cannot relocate it after zooming. Small pointer jitter makes no placement request.
- **Guide lines** through the ghost, as 3D editors draw them: red along x and blue along z, out to the horizon, at the height it stands; the same, fainter, on the ground beneath when it stands above the ground; and a green line straight down to a ring on the ground under it. They show where it is against the rest of the level from any angle. Its controls are just below the scene, out of the way of the 3D view (on a phone right under the scene, with the page's header one short row so both fit on the screen; on a wider screen at the top of the side panel, kept in sight): chips pick a knob (length, turn, tip...), with - and + either side of its slider, and Set down. Where it stands is not a chip: the arrows and dragging move it. The full list of its knobs, x and z among them, is also in the panel.
- **The arrows** in the control panel move it as you see it, 2 cm a press, and on while held: left, right, away from you and toward you go along whichever guide line (red x, blue z) is nearest that way on the screen, and each arrow is drawn in that line's colour, so turning the view can turn a blue arrow red. Up and down (green, like the vertical guide line) raise and lower whatever sets its height -- a panel's post, a cannon's bore, a knife's pivot, a whole ramp -- for a piece that has one; a plank or a mirror rests on what is under it and has none. The arrow keys do the same, a centimetre at a time (with Shift, ten), and Page Up and Page Down raise and lower it.
- **See what a knob changes.** Selecting length, drop, turn or another knob outlines the affected part in amber. Amber arrows on the ghost show the direction of increasing that value: length points outward at both plank ends; a track's drop points down at its lower end. **Far end** marks that end with a ring and highlights its stop or gate. Controls such as material or power highlight the part without movement arrows. The guides follow the piece when moved, turned or tipped, and disappear on Set down or Cancel. Blue/red still reports whether the placement fits. These are editing annotations, not forces or predicted motion.
- **View and Move.** While adjusting a piece, two labelled buttons stay in the lower-left corner of the 3D scene, including when another phone tab is open. The highlighted button is the active mode: **Move** indicates piece adjustment; a scene click or tap returns to **View** without changing placement. Deliberately dragging the ghost resumes Move from either mode; dragging empty space, using right/middle or Ctrl+drag, or using two fingers turns the camera. The arrows still move the piece in either mode. Esc switches between them; cancelling or placing hides the buttons. A new piece starts in Move. This is especially useful for looking around a large piece such as level 2's knife.
- **Desktop trackpad zoom (October 12).** Point into the scene and pinch apart/together. Chromium's Ctrl+wheel pinch input has higher sensitivity than an ordinary mouse wheel; pixel, line and page wheel units are normalized. A pinch also works over scene sockets without drawing a cable; ordinary scrolling over controls is left alone. The camera stays within 0.4–40 m. Browser checks use real DevTools wheel input, verify zoom in/out with small pinch deltas, unchanged page scale and saved placements, and no stationary held-piece movement after zoom. Phone two-finger camera gestures remain separate. These are camera checks, not new physics validation; native engine and conservation tolerances are unchanged.

  Measured in Chrome on October 12: five focused browser cases passed in 27.6 s, including the existing wiring layout at 1280×860, 390×844 and 844×390. Pixel pinch input uses DevTools; line/page wheel-unit and distance-bound checks use DOM wheel events. Desktop and both phone layouts were also inspected in the local browser. This does not measure a physical trackpad or establish Safari gesture-event support.
- **Energy against par, while you change it.** The ghost's bar says what the piece takes to make, with your other pieces, against the level's par: "It takes 34.1 MJ to make: 3.47 MJ over par (30.6 MJ)" for a 0.78 m plank on level 1, falling as it is cut shorter. The win card's **Energy details** lists what each piece weighed and took, and on a win over par how much lighter the heaviest piece would need to be: "your plank 1 about 11% lighter". Level 1's par is its 0.70 m plank, which bridges the gap with its middle anywhere from x = 0.26 to 0.34 m; 0.66 m still does from 0.28 to 0.32 m (under par), and 0.62 m does not reach.
- **Turn it any way.** Every piece can be turned about the vertical (turn), tipped end up or down (tip), and rolled about its length (roll), by any angle: with the −15° and +15° buttons, with the sliders, or with keys (Q/E turn, R/F tip, Z/C roll; with Shift, one degree at a time). Shift and the mouse wheel turn it; Alt and the wheel tip it. Square it up puts it back level. Turning costs nothing. Everything the piece is made of turns with it: a cannon turned 20° fires 20° off to the side, and tipped up it fires upward. A piece tipped so far that part of it would go into the ground is lifted to stand on the ground.
- **Blue fits, red does not.** While you move, change and turn the ghost, the server works out where the piece would really be (a plank is lowered onto the highest thing under it) and whether it can go there. This takes a few milliseconds and runs nothing in the engine. A red ghost says why, for example "your mirror 1 goes 120 mm into wall; move it", and cannot be set down. Nothing of yours may go into anything solid, the level's or another of your pieces.
- **A cannon is fired by the player** (level 3). Draw both firing leads in Readings and wiring, then drag the physical trigger handle down. Current must heat the powder before the gas launches the ball. Run alone does not operate the trigger; location affects the shot, and placement does not wire it. Level 5 closes its circuit the same way: an aluminium contact under the lever's left end, where the ball lands, and an aluminium plate under it. The ball comes off the ramp hard enough to knock the lever down and fly on -- a contact alone would touch for a moment, too short to heat the powder -- so the lever has a **ratchet**: past 4 degrees a pawl catches and it can go on down but not come back up, and the contact stays pressed on the plate while the coil lights the powder (the lever is a metre long so the ball lands on it rather than clipping its end).
- **Internal force fixture.** General Pull is hidden from player controls as of October 13. Its diagnostic handler and force-release regression coverage remain; runs using it earn no stars. Ordinary physical switch handles remain interactive on the scene.
- **A rope cut part way** (level 2) is weaker by what was cut: it holds the weight if what is left can carry it, and tears at the cut if not -- the piece above the cut staying on its arm, the piece below falling with the weight. A knife whose swing runs out part way through, or a blade that only clips the rope, leaves it hanging by what is left (docs/cutting-model.md, "A rope cut part way through").
- **A cord that sways** (Bounce the beam): the weight hangs on a chain of small oak segments that swings and is knocked about, with a cord through it carrying the weight exactly; the laser chars one segment away and the cord parts there, the chain with it, and the weight falls. Level 2's rope is still the stiff one, because a knife swung into a slack chain knocks it aside (docs/cutting-model.md, "A cord that bends and sways").
- **Nothing floats.** Everything in the world is held up by something: a fixed part stands on the ground, or is bolted to a fixed part that does, by a chain of them down to the ground. A piece that would hang in the air gets a stand, a concrete post from the top of whatever is under it (the ground, a table) up to its underside: a mirror stands on a post, a cannon's barrel on one, a ramp on two legs. A leg goes where it is clear, moved along the piece off whatever is in the way (level 5's lever), and a piece held by one leg needs no second; when no leg finds anywhere clear, the piece is red and says what its stand goes into. The stand is part of the piece: it shows with the ghost and in the tray's picture, and its concrete counts in the energy to make the piece. The levels' own parts keep to it too: Bounce the beam's laser sits on its post, and Lift with less's rope turns over two iron pulley blocks hung under the gantry's beam, the beam over the rope and the counterweight in line under it (it has no across knob). Loose things need no stand: gravity and contact hold them, or they fall. `scripts/machine_game.py` `hold_up` adds the stands as a level is built; tests/machine_game_tests.py checks every level, with its solution and with every knob at either end of its range.
- **Set it down** (or press Enter) and the engine builds it. From then on a loose piece is held only by gravity and contact: a plank too short for the gap falls in, and one too long for the ledges rests on the tables' tops a step up. Cancel (or Esc) throws the ghost away. Clicking (tapping) the piece in the scene turns a piece you have set down back into a ghost; Cancel puts it back as it was. During or after a run the level goes back to its start first, where pieces are placed. **Try It!** also sets down the piece you are adjusting, then starts the machine in one rebuild. It waits for the latest placement check; a piece that does not fit stays red with the reason, so you can move it. Cancelling the piece while that check is pending cancels the requested run.
- **Where things will go.** Before a run, the scene shows a see-through path for every loose thing, and a see-through copy of the goal's thing where it ends up: the engine rehearsing the level as it stands, quickly and out of sight (with a ghost as if it were set down, so moving or turning a ghost shows where things would go). It is blue while a thing moves freely, green inside the goal zone, and after it hits something, that thing's colour, with a dot where it hit; a key over the scene says when the goal would happen and what each colour is. It is the engine's own answer, so the run follows it (level 1: the goal at 1.90 s in both). It changes a moment after anything is changed and stays up while the run plays. Each preview is a rehearsal of engine time: rationed per visitor (BANJO_PREVIEWS_PER_HOUR 300, BANJO_PREVIEWS_PER_DAY 6000) and two at a time.
- **Try It!** and **Reset** stay visible beside the section tabs on desktop and phones, even when another tab is open or the panel is collapsed. **Undo / Redo** occupy the upper scene corner. Attach, **Restart with my pieces** and speed/follow controls appear directly within Controls when applicable. The prediction key stays over the scene. Run commits any valid new piece or adjustment at its current position (one Undo step), builds the machine afresh and plays it at real time; while it plays it is Pause, then Continue, and after the run Try It!. Reset puts a challenge back at its authored beginning, clears your added pieces and restores its tray. Undo recovers the cleared setup. **Restart with my pieces** in Controls returns to time zero with your build. Sandbox Reset returns the machine to time zero, cancels a pending edit and keeps its design and saved versions. When the goal happens, a card in Controls says **Level complete!** with the stars, **Energy details** and the next actions, and the world stops a moment later; the card sits in Controls so it leaves the 3D machine unobstructed (the details start folded away; opening them shows the run and each piece on desktop and phone, with the card scrolling within Controls when needed). A first win with a tool -- a plank, a knife, a cannon, a steam engine, a ramp, a mirror, a solar panel, a block and tackle -- says **Achievement Unlocked** instead, and which tool; each player's tools are kept with their progress (a player's wins from before tools were counted bring the tools of the levels won). After the last level it says so and offers level 1 again. When time runs out without the goal, the card says so and offers **Start over** (the level as it began, no pieces) or **Keep my pieces** (back to the start with them, to move or change): running the same pieces again would only do the same thing.
- **Energy: win on as little as you can.** A win is scored by the energy it took, two kinds, both real: making your pieces (each part's mass, from the engine's densities, times its material's embodied energy -- typical cradle-to-gate values from ICE, the Inventory of Carbon and Energy: oak 10.4 MJ/kg, iron 25, aluminium 155, glass 15, concrete 0.95; ice is the heat taken out to freeze it), and what came into the machine during the run, each once: what its batteries gave, as the engine measured it (a coil's heat, a laser's light, a motor's work all come out of a battery and are counted there, not again where they end up; the sun's is free), fuel burned in its heaters (level 4's firebox: its 12 kW for as long as the run has gone), and the powder in its charges at 2.8 MJ/kg. Making the pieces dwarfs the run (a 0.7 m oak plank is 30.6 MJ; a gram of powder 2.8 kJ), so smaller pieces and cheaper materials count most: in Lift with less an iron counterweight, heavier, takes less energy to make than an aluminium one. Each level's par (`par_energy_j`) is its own solution's energy, measured, rounded up to three figures.
- **Stars**, from what the engine measured: one for the goal in time, a second for winning on no more than a quarter more energy than par, a third for par or less. If the chat placed the pieces, one star at most. The win card offers Next level, **Play again** (back to the start with your pieces, to win on less) and All levels. Its visible score comparison shows current energy against the **Perfect score target**, including retained-piece reruns. **Energy details** shows the pieces/run breakdown and your best. Checked in Chrome at 1280 × 860, 390 × 844 and 844 × 390: the details open and close, the piece breakdown is visible when open, and the next actions are reachable inside the scene (tests/machine_game_browser_tests.py, October 11, 2026).
- **The levels screen** (`/play` on its own, the header's Levels, or All levels): every level with its stars and your best win's energy against par, how many you have won, and which is next. Opening the site's root redirects to `/play` before serving a page. The initial HTML hides the editor while loading; browsing levels keeps `/play` and creates no live machine until you choose a level. How to play opens on demand from the header link. Direct `/play?level=…` and saved sandbox design links still open their setups. Checked with the page module blocked during initial load and the actual API requests recorded (Chrome, October 11, 2026); the levels screen fits desktop and phone portrait/landscape without horizontal overflow. **Your return link** opens your anonymous progress -- stars, least energy and the last level played -- and designs on another device. A cookie remembers the selected save; no player name is requested.
- **What the game page leaves out.** The sandbox (`/machine`) has the engine's own controls, and the game page hides them: the speed (a level plays at real time), Follow (the camera follows what moves), Path (the path is always shown), the list of levels (they have their own screen), and the engine's readings (stations, measurements, the list of what happened). The server's reliability check, the `trial` op (a machine run three times with every loose part nudged by up to 1.5 mm), is still there for scripts and tests, but has no button.

Drag-only placement checked October 11, 2026: the full 39-test Chrome suite passed in 193.1 s. A final four-test rerun passed in 8.8 s after excluding fixed-port power cables from object dragging and adding the second-finger Pull release test (40 browser regressions in total). Checks cover clicks and 5 px jitter leaving all placement knobs unchanged, 7 px near-piece drags resuming Move, background/right/middle/Ctrl camera drags, zoom while holding a piece, two-finger release quarantine, touch cancellation, snapped track endpoints, unchanged gap wins and energy, explicit solar wiring, saved versions and 44 px unobstructed controls at 1280×860, 390×844 and 844×390. Wire and power-cable previews stay attached to their named sockets; dragging near them turns the camera. The Pull regression records an active force request followed by a zero-force release before camera movement. The client view CTest, JavaScript syntax check and all 269 source registrations passed. This changes client gestures only, using engine SHA-256 569a441595274e13128e1b8f06ff54d392232409b312d2089a77c2451315c976; it changes no native physics, material model, timestep, goal or conservation tolerance.

The preceding Linux CI checkpoint passed 147 of 148 CTests; its browser suite was killed by the 300 s aggregate limit after 27 passing tests, with no assertion failure reported. With 40 browser regressions now registered and Linux CI using software rendering, that suite's CTest allowance is 600 s. Individual browser waits, level goals and physical tolerances are unchanged. The longer aggregate allowance is configuration, not a new claim that Linux CI has passed.

## The eight levels


Place-and-run checked October 11, 2026: all 33 Chrome browser tests passed in 152.4 s. At 1280×860, 390×844 and 844×390, Run places a new piece or adjustment once, uses one setup request, reaches the unchanged gap goal, preserves Undo, and keeps sandbox drafts and saved versions. A delayed placement reply followed by an invalid edit cannot place the earlier valid position; cancelling during validation cannot start a run. A red mirror inside the wall remains unplaced. The focused solar/player/preview rerun also passed (3 tests, 27.2 s); an earlier full run missed a portrait solar wiring click, which was not reproduced in either follow-up. The player-progress fixture now uses distinct known scores, and sandbox navigation waits for its element to exist before reading visibility. The client view test and all 269 source registrations passed. This is a client change using the same verified engine SHA-256 `569a441595274e13128e1b8f06ff54d392232409b312d2089a77c2451315c976`; no native physics or conservation tolerance changed.

View/Move corner controls checked October 11, 2026: five Chrome regressions passed in 40.1 s, including visible, unobstructed 44 px buttons at 1280x860, 390x844, 844x390 and 320x568, active-mode feedback, switching from the Help tab, Escape, camera drags that leave the knife unchanged, piece drags in Move, existing adjustment guides, solar wiring and place-and-run. The client view test and all 269 source registrations passed. This changes only the client controls and overlay layout, using the previously verified engine; it adds no physics or conservation claims.

Editing guides checked on October 11, 2026: all 35 game tests and 20 Chrome browser tests passed, including every free-tray knob at its default and limits, turned/tipped planks, track drop and far-end selection, and visible controls and guide labels at 1280 × 860, 390 × 844 and 844 × 390. The caption stays inside the visible scene and chooses space beside the controls when the toolbar wraps; the targeted browser regression and manual landscape check passed after this adjustment. Guide requests leave the compiled setup and fit verdict unchanged. On this computer, 150 track-ghost requests averaged 2.19 ms without annotations and 5.43 ms with drop annotations; selecting a knob alone does not request another engine rehearsal. No native physics, timestep, resolution or conservation tolerance changed; this check adds no new material-law or conservation claim.

| Level | What it teaches | The pieces | A solution, as tested |
|---|---|---|---|
| 1. Mind the gap | rolling | a plank | a plank cut to 0.7 m and set down at x = 0.3 drops into the ledges each table has at the gap, level with the tables: the ball reaches the cup at 1.9 s |
| 2. Cut it down | cutting | a knife pendulum | pivot at x = -0.08 m, 1.31 m up, a 0.6 m arm: the edge cuts the oak rope and the weight is in the bin at 0.7 s |
| 3. Knock it off | a wired heating coil, pressure and impact, operated by the player | a cannon and two firing leads | muzzle x = 1.4 m, bore 0.48 m up, 1 g of powder; with the explicitly applied 8 N reference grip force the block reaches the zone at 0.858–0.979 s |
| 4. Up she goes | steam | a steam engine | over the marker with a 12 kW firebox: the piston reaches the zone at 3.4 s |
| 5. Chain reaction | a chain | a ramp with a ball | the ball tips the lever, which closes the switch; the coil lights the cannon's powder; the ball knocks the block into the zone at 1.5 s |
| 7. Bounce the beam | light: reflection, and light heating what it lands on | two mirrors | a 5 kW laser's beam bounced around a wall by two mirrors at 45 and -45 degrees burns through the cord; the weight is in the bin at about 5 s (within 12 s) |
| 8. Catch the sun | sunlight: a panel facing the sun catches the most | a solar panel and an explicit power cable | a sun 15 degrees up behind the shed; the panel at x = 1.0, z = 0.4, turned -45 degrees and tipped 75 to face the sun squarely, takes 250 W of sunlight and stores 50 W, and the solar winch lifts the weight to the mark at 2.4 s |
| 9. Lift with less | mechanical advantage: a block and tackle | a counterweight on a block and tackle | a 4.7 kg counterweight through 3 pulleys, hung 1.75 m up, lifts the 13.6 kg crate to the shelf mark at 3.65 s for a cost of 11.4 |

How forgiving they are, measured: in level 2 the knife works with its pivot anywhere from 16 cm behind the rope's line to level with it, across about 25 cm of height. In level 3, 1 g of powder works from several places; 0.5 g falls short and 2 g throws the block past the zone. In Catch the sun the winch needs about 185 W of sunlight on the panel: lying flat in the sun it gets 65 W and the weight never moves; tipped only 30 degrees, or tipped without being turned toward the sun, is not enough; tipped 45 degrees toward the sun it lifts the weight by 3.2 s; in the shed's shadow it gets nothing, however it faces. The ghost of a panel says how squarely it faces the sun and how much sunlight that gives, if nothing shades it. In Lift with less, measured: 21.6 kg on one pulley lifts the crate at 0.67 s but costs 45; 13.6 kg on one pulley, the crate's own weight, does not move it at all; 7.4 kg on two lifts it at 1.9 s for 16.8; 4.7 kg on three, hung 1.75 m up, lifts it at 3.65 s for 11.4, but hung at 1.4 m it reaches the ground first and the crate stops 6 cm short; 4 kg on four would have to fall from higher than the gantry allows.

## Compact game views

October 13, 2026: desktop, phone portrait and phone landscape share **Controls / Help** tabs; Sandbox additionally has **Design**. **Try It! / Pause**, **Reset** and collapse/expand stay beside the 3D view on every tab. The level name and a one-line task appear beside the scene; **Puzzle details** keeps the full brief, deadline and energy par. **Undo / Redo** sit in the upper scene corner, while a logarithmic zoom slider and minus/plus magnifiers sit in the lower corner. Zoom spans 0.4–40 m without changing the piece; wheel, trackpad pinch and touch pinch remain supported. Corner controls reserve space in callout and terminal placement.

There is no **Tools and speed**, **Readings and wiring** or **Adjust a piece** dropdown. Applicable actions appear in Controls: Attach, Restart with my pieces, speed/follow, Connect wires, valve/release controls and inspection. During an edit, optional test tools stay under Precision controls to leave room for the active setting; Sandbox Reset already keeps the design, so it needs no duplicate restart action. **Focus selected piece** is in the selected inspector; optical focus also frames source and receiver. **Whole machine** restores the overview. Result cards stay in Controls for every level, including tackle and Chain reaction, so a completed run does not cover selectable geometry.

Click a piece's solid geometry or rope to adjust it. A single **Adjustment** menu replaces the horizontally scrolling settings chips. The selected numeric setting has a full-width flat slider, a rectangular thumb, ticks quantized to its authored increment and an exact value with the same limits. Existing dimensional changes and native adjustment guides remain visible. Battery volts/charge, bulb rating, resistor ohms, capacitor farads, motor throttle and switch settings get a **Proposed** rating both in the inspector and in an edge callout anchored to the part. This is declared edit feedback, not a claim of measured runtime current. Click a player wire's gauge label to edit it; its Wire button in Controls remains available when a crowded scene cannot fit that callout. Click the cable itself to delete it. **Delete piece** is in the selected inspector. The duplicate Pick up/Copy/Remove list is removed; Undo/Redo still restore placements and topology.

**Precision controls** retains positioning, angle and optional endpoint controls. Run and Set down commit the latest validated edit; Cancel restores the previous setup. Actual circuit, solar and water readings stay at the scene edges with leaders; inspection and connection buttons remain visible in Controls. The native engine, materials, goals, timesteps and conservation tolerances are unchanged by this interface checkpoint.

Picking uses solid geometry and owned pulley ropes; decorative outline edges no longer steal selection from a thin board. Visible overlapping objects behind transparent glass offer a short scene chooser. A tiny component whose terminal rings overlap also gets an Adjust choice. These editing choices do not teleport a live body or change physical contacts. **Support a loose board** was measured at 1280×860, 390×844 and 844×390: the board can be selected independently, translated 1 m, undone/redone, saved/reloaded and then falls below 10 cm when run off its platform. It is already a loose oak body; its surroundings are still the existing ground boundary, not a new physical table assembly.

Checkpoint verification: 57 game/engine tests passed in 98.373 s, including authored solutions and nudged runs; the client geometry CTest and all 269 source registrations passed. Browser checks cover all 34 level openings, sliders and exact values, zoom/history on four screen sizes (including 320×568), wiring/gauge edits, glass selection, tackle reselection, saves and resets. Earlier broad-run failures were resolved with interface fixes and fixture updates to the visible controls: Sandbox Reset replaces its duplicate restart button, the piece library includes Open airflow, and river wheels no longer expect a removed dummy placement. The phone pane now reserves a title/task row while retaining at least four 44 px touch rows. The grid test keeps its grab away from the new touch zoom corner; its snap tolerances are unchanged. The dimensional guide check changes one full 2 cm native cell rather than half a cell; no physics threshold was relaxed. The tested Windows binary remains SHA-256 `4bde8f581098a877616ac5647923de8a2b0aada2d5db39911f85b8bef1e783a8`.

Clear-scene checks, October 11: the new desktop/portrait/landscape regression
measures the default solar watts marker below 3% of the scene area, requires
endpoint buttons hidden until Connect wires is pressed, connects the native
collector and winch, and reaches the unchanged goal. The camera focus keeps
piece knobs and viewing angles unchanged and frames the selected geometry.
The broad browser run passes 60/61 cases in 303.04 s; its sole failure is an
obsolete saved-wire test selector looking for buttons in the readings host.
That test now opens wiring through the normal controls and checks the scene
endpoint host. The corrected saved-graph check, camera/clear-scene regression,
exact-value inspector and zoom/drag regression pass together in 21.619 s.
Earlier solar wiring, electrical terminal wiring and clear-scene checks pass
in 45.421 s; aiming guides and physical handle operation also pass. Six
registered storage/HTTP/client CTests pass in 4.30 s; all 269 C++ sources are
registered. Phone placement and camera focus were played and visually reviewed.
The follow-up broad run and Linux CI follow the checkpoint. This changes the
client layout and camera only: the verified native engine remains SHA-256
`807ae9c34f0516a0d0dbf588400451b865083043d614cd1aab8040140c830f87`.
No physical model, level goal, timestep or tolerance changed.

Compact-view verification, October 11: the broad registered Chrome suite, before the final scroll-footer correction, passes 59/60 tests in 367.875 s at 1280×860, 390×844 and 844×390. All new UI checks pass, including actual typed numeric input, invalid-value refusal, single-editor placement, collapse/expand with Run/Pause/Reset, gallery creation/rename/reopening, and opt-in details that do not create a live machine. An existing malformed-return-link check failed because Chrome reported `net::ERR_NO_BUFFER_SPACE` fetching `machine-view.mjs`; the unchanged exact check then passed separately in 1.982 s. Its cause remains unproven and the complete suite is not reported as green. The isolated gallery run earlier hit the same transport error; its subsequent desktop/portrait/landscape run passed. The initial full run had five UI-test failures (seven subcases): stale snap wording, inactive duplicate-button selectors, preview scrolling, and inspector height. Those were corrected without changing physical goals, waits or tolerances. The six affected editor/flow/save checks pass in 34.644 s. Four registered client CTests pass in 1.68 s (including four declared-geometry preview cases), profile storage passes, and all 269 C++ sources remain registered. Manual phone play checks numeric editing, placement on Run, Pause and Reset; desktop and both phone orientations were visually reviewed. No native physics or conservation model changed; the engine remains SHA-256 `807ae9c34f0516a0d0dbf588400451b865083043d614cd1aab8040140c830f87`.

Final scroll-footer correction: the inspector now scrolls in a bounded inner area above a separate placement action row. Landscape review exposed partially covered movement arrows in the earlier sticky-row layout. Seven final Chrome checks pass in 61.496 s across desktop and both phone orientations, including actual Run/placement, post-run tackle editing, preview controls, independent tabs, collapse/expand and complete 44×44 movement targets after ordinary scrolling. The new target check requires their full bounds inside the scroll area with no overlap against the placement row, and tests interior points inset from their existing rounded corners. The complete 60-test suite was not repeated after this layout-only correction; its recorded script-fetch transport failure remains a QA limitation.

## Sandbox (including the former Free build)

The header's **Sandbox** link and the levels screen's Sandbox card open `/machine`: a single gallery with **Your designs** first and all **Examples** below, plus **Add New Design** in its header. A new design opens immediately as **Untitled design**; rename it in the editor’s **Design** tab. Cards show static top-view setup sketches from declared geometry (unexpanded pieces are position markers), rather than a physics rehearsal. Start from an editable copy of **Gate and split** (the former free-build example) or **Chain reaction** (the original sandbox declaration). There is one editor: the levels' tray and placement controls, Try It!, Pause, Set up again and Attach, plus the sandbox's speed, Follow, engine readings and base declaration. Nothing is scored. The empty table's corners are marked by small concrete stones, 2 m out each way. The tray has every piece, subject to the server's part, cell and tray limits.

**Choose a piece.** **Add a piece**, attached to the scene beside Try It!, opens a full-screen library with large thumbnails drawn from each piece's actual parts, descriptions, search and category filters. Choose a card to return to the same design with that piece as a ghost, ready to place. **Back to sandbox** or Escape closes the library without adding anything. Only the cards scroll: search and Back stay visible. Keyboard focus stays inside the library and returns to the scene when it closes. Puzzle trays of four pieces or fewer keep their individual buttons in the control panel; larger puzzle trays use the same library with remaining counts and **Back to puzzle**. Attach remains beside the scene. Checked on October 11, 2026 (`tests/machine_game_browser_tests.py`): search, category filters, no matches, closing without changing the setup, selecting and placing a piece, running and resetting the resulting machine at 1280 × 860, 390 × 844 and 844 × 390. No engine or physics model changed.

**Saving and reopening.** Drafts sync as you change the setup, separately for each design in your anonymous save. **Save version** validates the setup and keeps a checkpoint; **Saved versions** restores one of the latest 30 checkpoints. Restoring a different version also checkpoints the previous draft, so you can return to it. **All designs** returns to the library and stops the current simulation. Reloading a design's URL reopens its draft. Saved setups contain initial declarations and placements, not bodies' positions after running. Existing free builds migrate into **My free build**; old `/play?level=free` links reopen the last design. Server save failures are reported and unsent changes remain in the browser cache when available; use a shared design link to export a copy. Your private return link restores server saves on another device. The save-status message distinguishes durable storage from an unmounted public filesystem.

**The machine as data** edits the base declaration, before tray pieces are added; both are kept together in saves and shared links. A base can contain its own stations, which remain visible under **Engine readings**. Its explicit anchors and kit supports are retained; automatic stands are added to tray pieces only. Names starting with `your ` belong to tray pieces and are refused in a base. A custom base cannot replace a puzzle level. **Set out the example** replaces the setup with Gate and split. **Clear the table** removes both the base and tray pieces; saved versions remain and Undo restores the cleared setup.

Checked on October 11, 2026 (`tests/machine_game_tests.py` and `tests/machine_game_browser_tests.py`): both templates compile; the chain's original 25 parts and nine stations are retained. All nine happen in order, from the wheel at 1.867 s to the glass breaking at 20.462 s (4.98 s wall time in the unpaced rehearsal on this computer). Gate and split still reaches both outputs and topples all six dominoes in its nominal and nudged runs. Chrome checks cover migration, two independent designs, draft reload, save/restore, storage refusal, clearing and undoing a base with added pieces, old and new share links, and the library and scene controls at 390 × 844 and 844 × 390. Manual checks also used 1280 × 860. This changes composition and storage, not the native physics model: the engine timestep, cell resolution, material laws and conservation tolerances are unchanged. The chain's experimental burning and glass fracture retain their existing limitations.

The pieces, besides the levels' plank, ramp, cannon and steam engine:

- **Marble**: an iron, oak or rubber ball, 4 or 6 cm, set down on whatever is under it. On a slope it rests on the slope itself, not on top of the slope's box.
- **Ring marble**: a 4 cm iron marble with an iron tie ring welded on top, for tying a string. The ring is wider than the ball, so it lurches and stops instead of rolling true (see Ring marble above).
- **Track**: a board with a rail on each side, from its top end down by its drop over its length. It can be turned about the upright to point any way. Its far end is open (a marble rolls off it), a stop (the marble stays there), or a gate.
- **Shelf**: a short track tilted a little toward its gate, so marbles set down on it roll to the gate and wait there. This is how a marble stays up high until something lets it go.
- **The gate**: a flap hangs across the track from a bar on a pin over one rail, and the pin runs along the track. A marble pushes the flap along the pin, which the pin holds, so the flap doesn't move. Out past the rail is a short arm with a paddle on its end. Press the paddle down (drop a marble on it, tip a lever under it, or pull it) and the flap swings up out of the way. On its own it falls shut again. A **gate that stays open** has a catch that holds it once it is 20° up. Measured: three iron marbles wait at a closed gate. An iron marble dropped onto its paddle swings it up 56°: with the catch, all three roll off the end; without it, the gate falls shut before they arrive and they wait.
- **Flip-flop**: a rocker on a pin, tipped one way, with a fin standing up from its middle. Drop marbles on its middle from a track end above it, along the pin, and they go one way, then the other. The fin leans toward the low end, so a marble lands on the high side. Its weight tips the rocker over and it rolls off that end, leaving the rocker tipped the other way for the next marble. A board behind the rocker holds its pin and stops a marble that comes in fast. Measured: four iron marbles fed down a track went right, left, right, left. Two marbles that arrive together go the same way, as they would on a real one. An oak marble is too light to tip it.
- **Bend**: a curved track, turning up to 180° either way round a radius of 15 cm to 1 m, dropping as it goes. It is made of straight sections, one for every 22.5° of turn, each a board with a rail on each side, overlapping at the seams. A marble rolls on a tilted board's true surface (measured to a tenth of a millimetre, turned or not), not on the cells the board is built from, so a marble goes round a bend smoothly: down a track, round 90° either way, onto the track snapped to its far end and to that track's stop.
- **Funnel**: a square mouth 20 cm to 1 m across, four boards sloping in to a 6 cm hole 12 cm lower. It gathers marbles from several paths into one: what lands anywhere on it rolls in and drops out of the hole. Measured: marbles dropped on its corners, its edges and near its middle all went through the hole within 2 cm of its middle. Moved near a track's far end, it goes under it, its mouth 6 cm past and 2 cm below.
- **Block**: a fixed post, wall, step or stop of any size, in concrete, oak or iron, set down on what is under it.
- **Dominoes**: a row of oak dominoes, 2 to 20 of them, standing on what is under the row.
- **Lever**: a seesaw on a pin on a block.

**Snap points.** While a piece is being placed, dots show where the other pieces connect: green where a marble comes in (a track's or bend's top end, a flip-flop's middle), amber where it goes out (a far end, or below and just beyond a flip-flop's ends, where what joins there is clear of the rocker as it tips), violet a gate's paddle. Drag a piece near one, within 10 cm across the ground and a metre up or down, and it is put where the two connect, and its bar says what it is joined to. A track's top end goes 3 cm past and 4 cm under another's far end, so what rolls off drops onto it. A track's far end goes 4 cm above another's top end, or 11 cm above a flip-flop's middle and 4 cm short of it, or 6.5 cm above a gate's paddle and 5 cm short of it, because what rolls off flies on a little as it falls. A flip-flop goes under a track's far end with its board behind, where the marbles fly. A marble goes just inside a track's top end. Only a piece moved by hand snaps; the arrows, the sliders and turning move it freely. Measured: a marble rolls down a track and onto the track snapped to it, and stops at its end. In the free build, planks also snap end to end and blocks side to side or on top (see "like pieces meet flush" above).

**Attach.** 🔗 Attach joins two parts: press one, then the other, and choose **glue** (held together where they were pressed), a **pin** (they turn about it, its axle along x, along z or upright), or a **string** (tied from the first point to the second, as long as it is then). A join is one of your pieces: it is listed, kept with the build, taken back with Undo and removed with Remove. Taking a piece away takes the joins to it with it. Two fixed parts are not joined, since that would move nothing. A pin or glue shows as a dot where the parts join, and a string as a line. Measured: a plank on a block, pinned at its middle, tips when a marble lands on one end and stays on its pin; glued there, it does not tip.

**Sharing a design.** **Share this design** makes a link containing its name, base declaration and tray pieces, compressed into the part after the `#`, which a browser never sends to the server. It is copied, and also shown to copy by hand. Opening it creates a separate design; existing designs stay in the library. Older links containing only tray pieces are still readable. A link pasted into a tab already on the page works too.

**Build with words.** In a free build the chat builds what it is asked, for example "hold three marbles up high behind a gate, then split them three ways". The model does not work out where things go; a model cannot lay out a build of many parts from numbers. It says which pieces it wants and what each one **joins** to: "this marble joins the shelf's top end", "this track's far end joins the gate's paddle", "this flip-flop joins that track's far end". The server puts each piece there with the same rules as snapping by hand. Marbles joined to the same top end line up along it. A track joined to a far end or a flip-flop's end starts the way the marble leaves; to turn, a bend goes there. The server lays the build out on a table as big as the world and then moves the whole build to the middle of the real table. It checks the build: a build it refuses goes back to the model with the reasons, at most twice. Then it rehearses it once in the engine, and the chat says how many marbles ended on a piece and how many on the floor. Try It! to watch, and move what needs moving. The model is told recipes that were measured to work. Built from joins alone, four marbles held on a shelf end on all three tracks of a three-way split (tests/machine_game_tests.py). Asked the request above three times, gpt-5-mini built it each time; in two, every marble held on the shelf ended on an output track, and in the third one stopped on a flip-flop.

**Copy, undo and redo.** Copy, beside Pick up, makes a new ghost of a piece 10 cm along from it. **Undo** stays beside Run and Reset on every tab and when the controls are collapsed, in both levels and Sandbox. It is disabled until there is a completed change to take back. **Redo** remains in Tools and speed. Ctrl+Z and Ctrl+Y also take back and put back changes to the pieces: setting one down, moving or adjusting it, removing it, wiring or disconnecting it, clearing the table, setting out the example, joining two parts. History holds up to 60 setup changes for the current visit; saved versions keep designs between visits. Undo restores the setup and resets the run; it does not rewind running physics.

**The example**: a marble rolls down a short track onto a gate's paddle, and the gate opens and its catch holds it. The three marbles waiting on the shelf behind the gate roll off onto a track that runs down to a flip-flop, which sends them to the left and right. One track ends at a stop; the other runs out onto the floor into six dominoes, and they fall. Measured in the engine: the gate catches, marbles reach both sides and all six dominoes fall, in the run as written and in runs with every loose part nudged by up to 1.5 mm. The preview follows the marbles first. Its key names four of the things they hit, and how many more.

A thin turned part, such as a domino turned a quarter round, is built from the engine's grid of 2 cm cells. When its middle lies exactly between cells, no cell would be inside it, and the engine refuses a world with a body that has no matter. Such a part is now moved across its thickness by a quarter or half a cell and the machine's notes say so; none of the levels' parts needs it.

## Asking for help

Phone tabs verified October 11, 2026: the full Chrome suite passed 31 tests in 129.6 s at desktop 1280×860, portrait 390×844 and landscape 844×390. After the final test changes, the two tab/flow regressions passed again in 17.2 s, including real scrolling to the last Design disclosure, visible 44 px targets, saved versions, Run/Pause/Reset from another tab, automatic piece selection, preserved chat drafts, rotation and keyboard navigation. A 320×568 phone layout was also inspected manually without horizontal overflow. The client view test and all 269 source registrations passed. These are UI checks using the previously verified engine SHA-256 `569a441595274e13128e1b8f06ff54d392232409b312d2089a77c2451315c976`, not new physical measurements. The previous Linux CI preview check could read its drawing statistics before the first render; it now waits for the same positive laser-segment count without changing its timeout.

On phones, the panel beside or below the scene uses **Controls / Help** tabs for levels and **Controls / Design / Help** for Sandbox. Controls contains the tray carousel, camera, piece adjustments and flow preview; Design contains saving, versions, the placed-piece list and engine/data disclosures; Help contains the level objective, sharing, existing chat and Report a bug. Each selected section has the full remaining panel height and scrolls within it, with no content behind a sticky controls box. Run/Pause and Reset stay in the tab toolbar. Picking up a piece selects Controls and brings its adjustments to the top. Draft text, scroll positions and the machine survive tab changes and resizing; desktop uses the same tabs. The tabs support arrow keys, Home and End; their arrow keys are consumed before the scene's piece-nudging shortcuts. This is a page layout change; the physics and save format are unchanged.

Floating station captions (such as “The crate is up at the shelf mark”) have been removed from the 3D scene. The puzzle objective stays beside the game; use the chat for a hint. Live solar meters, connection ports, placement feedback and the green goal boxes remain visible. Browser regression checks cover the on-demand help on desktop, 390×844 portrait and 844×390 landscape, including preserved URLs/designs, keyboard focus, dismissal and blocked game shortcuts while reading. The full browser suite passes 28 tests in 97.5 seconds using the solar checkpoint engine above; source registration still covers all 269 C++ sources. This is a page change with no new physical measurement.

The chat box on a level does two things:

- **Ask for a hint** sends your question, your pieces and what the engine measured in your last run (where things went, how fast, what they hit) to the model, which answers with a hint. It is never shown the level's solution.
- **Place it for me** asks the model for up to three ways to place the tray's pieces. The engine rehearses each and uses the first that reaches the goal. A knob just outside its range is brought to the end of the range, as the slider would. If none works, the engine searches from the one that came nearest: sixteen random settings of the same pieces first (nearness can mislead -- a ball flying past a lever comes near its middle from a ramp in quite the wrong place), then one knob at a time, keeping each change that brings the goal nearer and going on in that direction while it helps, up to 48 runs. "Nearer" counts the steps of a chain not yet reached (a level's `milestones`: in level 5 the ball hitting the lever, the switch closing, the cannon firing) and how near the first of them came. Measured with gpt-5-mini: levels 1, 2 and 4 placed by the model itself; levels 3 and 5 finished by the engine's search (level 5 from a ramp over the lever in 4 to 29 runs, three seeds).

## Adding a level

Levels are in `client/voxel-lab/levels.json`. Each has:

- `machine`: the fixed machine, a `banjo.machine.v1` declaration;
- `goal`: a title and a station rule, usually `in_zone` with a part, the box's centre and its size;
- `tray`: the pieces, each with `count`, `cost` (and `cost_per` a knob), and its knobs' ranges;
- `budget`, `par`, `time_s`, `hints` (shown to the player and to the model);
- `solution`, which is never sent to the page or the model.

The pieces (`plank`, `knife`, `cannon`, `steam`, `ramp`) are in `scripts/machine_game.py`. `tests/machine_game_tests.py` checks that every level's solution reaches its goal in three nudged runs out of three, that no level is solved with no pieces, and that a misplaced piece fails for a physical reason.

Bounce the beam burns the cord in seconds, as a real laser would: light heats the spot it lands on and chars the oak there away ([light-spots.md](light-spots.md)). Its own solution puts the weight in the bin at about 5 s, 3 runs in 3 (it took 20.3 s when a body's heat was spread through all of it).

## The site

October 12 header/icon verification: the shared Controls and Recent Changes
browser checks pass in 10.247 s across desktop, phone portrait and landscape.
The new PNG assets return their exact bytes with `image/png`; the manifest
references the transparent app icon. Both PNGs have zero-alpha corner pixels.
The favicon is a 64×64, 6.6 kB derivative of the transparent imagegen edit;
the larger PNG supplies the touch/manifest icon. Source registration remains
269/269. This changes branding only, with no new physics validation.

The transparent orange mark appears beside the header name **Banjo**, also used as the browser page title. The red/cream app logo has a transparent exterior in `brand/banjo-app-icon.png`; it is declared as the browser favicon, Apple touch icon and web manifest icon. Its exterior white JPEG margin was removed with imagegen; the original PNG/JPEG artwork remains under `client/voxel-lab/brand/`. The browser scales the PNG for each surface. The manifest opens `/play` and uses the name **Banjo**. This supplies home-screen branding; offline play and installation on physical iOS/Android devices were not verified. Historical branding verification, October 11: all three existing Chrome layout/control checks pass in 4.514 s at desktop 1280×860, portrait 390×844 and landscape 844×390. The public server returned the original images and manifest with their correct MIME types and original content; source registration remained 269/269. The native engine and game physics are unchanged.

The deployed site is the game and nothing else, open to anyone with no login: `scripts/voxel-lab.py --site game --public` (the Dockerfile's command) serves `/play`, the sandbox `/machine` it is built on, and what those pages load; `/` goes to `/play`; every other page and API answers 404. With no password in front of it, what costs money or a lot of engine time is rationed instead: the chat (which spends the model's key) to 12 requests per visitor an hour and 400 a day, and the reliability check to 30 per visitor an hour and 2,000 a day (BANJO_CHAT_PER_HOUR, BANJO_CHAT_PER_DAY, BANJO_TRIALS_PER_HOUR, BANJO_TRIALS_PER_DAY). The server runs at most BANJO_MACHINE_SESSIONS live levels at once (10 as deployed, from the Dockerfile; 4 by default). Nobody's game is ended while they play it: a new level takes the place of one whose page has closed or gone quiet for 15 s (a page polls every second, and tells the server when it is closed), else of one whose player has not built or started anything for 3 minutes; otherwise the newcomer is told the site is busy and to try again in a minute or two. A level closed while it sat idle is built again when its player presses Try It!. A player can **tell us what happened** from the box under the verdict: their words, with the level and the pieces placed, are written to the server's log as a `FEEDBACK` line and to `feedback.jsonl` beside the machines' logs, rationed to 10 an hour per visitor and 500 a day; nothing that names the player is kept. **How to play** opens only when the header link is clicked. It is a modal layer over the current puzzle, level chooser, sandbox library or saved design; it never navigates or rebuilds the machine. Close, Escape or a backdrop click dismisses it and returns focus to the header link. Its scrollable instructions keep the 44 px Close button visible on phones. It does not appear automatically on a first visit. `--public` is refused without `--site game`. Without `--public` the server needs `BANJO_PASSWORD` to listen anywhere but on this computer.

## Real time

A level plays at real time. When something breaks or dents, the engine solves the impact in its lattice of cells. Played live, that solve runs on the engine's worker while everything else carries on and the pair that met is held still, for at most 50 ms of world time. If the answer is not back by then, the machine waits for it, because a body held longer misses what it should have been doing. Rehearsals, tests and reliability runs always wait, so their answers are exactly the physics'. How long a solve takes is being worked on (see docs/machine-physics-roadmap.md).

## Prepublication checks after disk setup

October 11, 2026: six registered storage/HTTP/client CTests pass in 4.97 s, with all 269 C++ sources registered. The complete 60-test Chrome run at the branding checkpoint passes 59/60 in 364.518 s: one desktop tackle bootstrap fails while Chrome reports `net::ERR_CONNECTION_TIMED_OUT` loading `three.core.js`, before the game module can initialize. The same unchanged tackle check passes separately across all three viewports in 16.349 s. All save-recovery, CAS, wiring, native-win, gallery and editor assertions in the broad run pass. This is treated as the recorded local browser transport limitation, with its cause still unproven; the broad run is not labelled green. No retries, timeout changes, goal changes or physical tolerance changes were added. Linux CI and public-site durability checks follow publication.

The public recovery check exposed a 17 px Saved versions disclosure. It now
has a 44 px touch target while retaining its native disclosure marker. The
gallery browser regression clicks it open and closed at 1280×860, 390×844 and
844×390, checking visible, unobstructed geometry; it passes in 2.858 s. This is
a CSS correction; saved data and physics are unchanged.

Linux CI for `97931d7e` completed with 153/154 CTests passing in 1119.44 s.
The browser suite passed 58/60 cases in 582.529 s: the help overlay compared
cache bytes before an existing cloud save acknowledged, and a save
acknowledgement refreshed the version picker back to its newest option while
an older version was being selected. The help fixture now waits for that
existing save to settle before its unchanged no-mutation assertions. The
client preserves the selected version when refreshing the same design, and
resets it when opening a different design. The river regression holds a real
save acknowledgement, selects the older version, releases it, checks the
choice remains and restores the wheel and connections. Five focused Chrome
checks pass in 21.890 s: river, help across all three viewports, solar cable,
terminal graph and design-version restoration. The follow-up Linux CI verdict
is pending. No engine code, physical goal, timeout or tolerance changed.


## Separate tanks, adjustable taps and river placement — October 12

**Pour onto the paddles** now supplies two independent cards. Add the wheel,
add the tank, increase **tap opening** from its closed default and aim the
outlet at the left paddles. The wheel has no attached feed. Either piece order
works: the goal resolves the actual wheel's hinge, then native torque decides
the outcome. **Water opens a gate** uses the same pair plus a drum connection;
**Fill the receiver** now requires increasing a trickle to fill its waiting
box before a five-second deadline, as described below. Task counts are
2, 3 and 1 respectively. Closed taps, a nearly closed 1% tap, missed pours
and a wheel alone fail three nudged checks. A 5% pour can turn an unloaded
wheel in some nudges; opposite-side pours can also rebound and later turn it.
These are not classified as universal failures or hidden behind scripted goals.

New **Wheel in the river**, directly after the pour lesson, starts its 65 cm
wheel on the bank. Drag it into the current: it must turn thirty degrees
within ten seconds. No tank, falling spout, rope or unexplained load box is
present. Its simple sandbox example allows the same comparison. The later
river-powered lift still teaches connecting useful work to the axle.

The tank is a fixed thin glass vessel on a grounded frame, with a 24×24 cm
inner section and a nominal 50 mm outlet. **Initial water**, **fixed outlet
height**, outlet position and **tap opening** are editable. Tap opening is
the primary control when added. The camera fits a newly added tall lesson
tank beside the existing wheel once; subsequent edits preserve the view.
A transparent water volume and compact meter show native remaining litres,
opening and flow (or explicitly Updating flow while a preview is pending).
Preview readings are labelled; Run uses live receipts. The runtime tap control
queues a fractional native boundary change. It does not apply torque to its
handle; the setup handle's angle illustrates the declared opening. Set up
again restores the declared opening and fill. Saved versions store that setup,
not runtime tap changes. This is a fixed reservoir, not a movable/sloshing bucket.

New water examples use a separate tank and wheel. Browser saves and imported
shares lacking the new outlet setting retain their old metered tank; old
wheels lacking a feed setting retain their former Left feed. Version-1 seeded
water identities reconstruct their original one-piece apparatus, while new
pour/receiver/gate identities use version 2. There are 25 examples, 31 cards
plus Attach, and 30 authored levels (22 lesson families plus eight chain levels).

At 1/240 s, the native three-nudge solution times are 1.517/1.867/1.400 s
for the pour, 3.983 s for receiver fill, 3.183/4.417/2.733 s for the gate,
and 3.983/4.100/3.883 s for river placement. All goals and deadlines stay
unchanged. Construction changed with independent geometry: current authored
pars are measured nominal construction plus the existing 1 kJ margin, not
adjusted goal tolerances. The 22-family, 88-preset sweep gives 264/264 correct
nudged wins and zero of 264 empty or wrong wins. Its 15 recipe tests pass
in 134.8 s. The full 50-test game suite passes in 74.1 s. Detailed gravity
law, per-material comparisons, residuals and limits are in
[water measurements](sandbox-water-launch-measured.md#independent-gravity-tanks-october-12).

Final scope checks: twelve water/launch tests pass in 30.4 s; nine declaration
tests pass in 0.19 s; native water, terrain, LiveWorld and client-view CTests
pass. Six targeted Chrome regressions pass (34.9 s + 37.1 s): independent
pieces and tap edits, camera framing, native visible volume/flow/reset, river
dragging, runtime current, preview timeline, old shares and new saved versions.
They cover desktop 1280×860, portrait 390×844 and landscape 844×390, plus the
new tank lesson at 320×568. Ordinary Run/Set down/Reset targets stay visible,
unobstructed and at least 44 px. The build and all 269 source registrations
pass. Native SHA-256 is
`3fac18bff131cf0d819e6186969c4ed64b27210eef04e36f420bd497ce39d24a`.
Legacy v1 wheel/gate/receiver recipes also pass their native three-nudge
solution/empty/wrong validation. Local complete preview wall times are
0.252–0.266 s for the pour and 0.391–0.394 s for river placement (three calls
each), excluding network/rendering delay. This is targeted water verification;
the earlier full CI phone-cannon, 320 px precision and laser-status timing
failures have not been fixed by this update. The task-count browser fixture
now checks level IDs rather than stale list indices as new lessons are added.


## Timed receiver fill — October 12

**Fill the receiver** begins with a glass box mounted on four grounded legs.
Add the four-litre gravity source over it; its 10% tap opening is too slow.
The primary **tap opening** control changes the existing native head-driven
flow. Initial fill, outlet height, valve state and outlet model are prepared
for this lesson; location remains editable, and a missed pour fails physically.
Native source flow decreases as head falls. No new water law is introduced.

The goal is at least 3 L currently inside the receiver's interior region,
retained continuously for 0.5 s before 5 s of simulation time. The 3 L amount
is retained from the earlier goal; the deadline is tightened from 6 to 5 s
and the goal changes from cumulative channel arrival to actual box retention,
as requested by the owner. It is a new v3 recipe, not a changed v1/v2 share.
Old versions keep their original source, cumulative receipt, knobs and deadline.
The original 460,651,224 J energy par is unchanged.

The scene meter shows **Container L / 3 L**. While running, it also shows
remaining simulation time; a successful native goal reports **Filled in … s**.
Preview volume is labelled separately, with its timeline in Flow preview;
the live countdown begins with Run. A failed timed-fill run pauses after its
deadline is observed, rather than continuing to pour until it eventually fills.
Scoring still rejects any native goal reached after the deadline. The result
stays beside the scene. Reset empties the box and refills the source.

Measured nominal runs: 10% delivers only 0.640 L by 5 s; 50% retains 2.752 L
and fails. At 75%, three nudges complete at 4.567, 4.450 and 4.333 s; 100%
completes at 3.483 s in all three. Full flow placed outside the box also fails.
All four seeded initial-fill presets keep the same 3 L/5 s goal and pass
native correct/empty/wrong preflight. See
[timed-receiver measurements](sandbox-water-launch-measured.md#timed-receiver-fill-october-12).


## Current-driven wires and metal paddle contacts — October 12

Wire insulation retains its positive/negative color without current. Yellow
highlights and moving dots require the native branch current magnitude to exceed
0.0001 A; a closed switch alone is insufficient. An open DC loop can have voltage
available at its source but has no steady current through either series lead.
Arrows indicate conventional current, not a simulated electron transit speed.

Electrical flow rehearsals start paused at their initial snapshot. **Play
preview** or scrubbing explicitly shows future measured current. The preview
includes the native moving paddle/contact-leaf poses, so its closed-current
sample no longer appears over an unchanged open mechanism. **Try It!** uses the
live circuit and hides the rehearsal. Water-only rehearsals retain playback.

New paddle switches have a 38×4×12 cm iron paddle, a separate iron contact leaf
fixed beside it, a grounded output pad and concrete support. The native engine's
existing body-contact observation closes the branch only when the two conductors
touch (within its existing 1 mm observation distance). Wiring In to the leaf and
Out to the pad completes the same terminal graph used in Sandbox. Crossing wires
still do not form a connection. Glass/oak contact conductors and terminals bound
to different bodies are rejected. **Readings and wiring → Inspect contacts**
zooms in on the actual leaf and pad; the reading reports open/closed and amperes.
The completed-run card moves into Controls during that inspection, clearing
the contact view.

**Marble turns on a light** uses 5° initial contact placement; changing paddle
travel moves the physical output pad. Its goal remains at least 2 W for 0.1 s
within 3 s, with its unchanged 462 MJ energy par. The reference machine wins
at 0.933 s in all three nudged runs and takes 457.787 MJ. Current v2 seeded
starts use 0.48, 0.51, 0.58 and 0.59 m drops, all verified; the former 0.62 m
preset did not hold contact reliably and is outside the new recipe domain.
Version-1 links keep their earlier hinge switch and height presets.

Manual rockers still use the native measured hinge threshold. The paddle's
interface remains a lumped 0.001 ohm contact: metal body types are validated,
but resistance is not yet derived from contact pressure, real surface area,
metal resistivity or oxidation. No electron, arcing or elastic contact-bounce
model is claimed. Existing wire sizing uses copper resistance at 20 °C.
See [contact measurements](sandbox-electrics-measured.md#current-driven-display-and-paddle-metal-contact-october-12).

## Editing prepared Sandbox objects and adding a river — October 12

Gear-workbench routing follow-up: its custom small motor housing previously
overrode the ordinary motor's corrected pins. Both now derive their rear
connection points from the actual housing dimensions, with x/y inside that
face and z 5 mm beyond it. The gear lesson's three nudged native solutions
still reach its unchanged goal. These are clear drawing routes, not a newly
implemented mechanical cable law.

Phone gear-choice follow-up: manual review found that slider-column styles
overrode the new choice grid. Gear choices now explicitly use two equal
columns and normal button text. Both gear browser checks pass in 16.513 s;
the lesson checks all four button widths/heights, bounds and two-row layout
at desktop, portrait and landscape sizes, in addition to its native win.

Follow-up verification: the motor lesson's terminals are on the rear face of
its fixed housing, 5 mm beyond that face and over 25 cm behind the rotor's
rear face. Rendered floor routes clear the rotor's full swept bounds on
desktop and both phone layouts. The unchanged forward goal succeeds in all
three nudged native runs; reverse fails all three. This fixes geometry of the
connections, not mechanical cable collision or connector tear-out.

Gear size and tooth-size controls use labelled buttons rather than a dropdown.
Size buttons show tooth count and approximate outside diameter, including
tooth depth. Four radial arrows identify the changed radius; tooth alignment
shows two tangential arrows, and axle height marks its pivot. The outlines
use the compiled wheel's centre and declared dimensions. They do not move
neighbouring gears. Contact still rotates gears during native runs; force-based
seating while placing a ghost is unfinished. Prepared-object ghosts now reject
increased penetration into unrelated base bodies while preserving authored
bolted overlaps.

The follow-up also repairs compound-body bounds: renderer groups no longer
pretend to have a BufferGeometry just to expose a disposal method. Bounds,
picking and edge-label protection can measure gears and other compound parts;
removal/rebuild disposes each child geometry. The initial motor/gear browser
batch failed opening the gear scene with `geometry.getAttribute`; after this
fix the four affected cases pass in 28.139 s. Four additional checks pass in
61.793 s, covering prepared-object edits, compound pipe layouts, wire labels
and selected-control guides. Native gear contact/free-wiring checks pass in
2.766 s, and three declaration/guide regressions in 13.265 s. No goal, physics
law, conservation tolerance or native binary changed.

The gallery has one list: your recently edited designs first, then every
example. The headings do not filter or hide cards. **Add New Design** stays
in the header.

Prepared parts can be selected by clicking their solid bodies in the scene. Drag their blue ghost, use movement arrows
or precision positions, then **Set down**. **Delete piece** sits beside Set down
for both prepared and tray objects. Kits and hinge/slide/weld assemblies
move together. Kit translation applies to generated parts, joint anchors,
water sources, thermal regions, blades and light sources while preserving
compound-local geometry. Removing an apparatus clears dependent joints,
electrical devices, wires and observations; Undo recovers the whole setup.
Custom declarations with unsupported dependencies are refused before commit.
Prepared apparatus remains fixed in scored challenges.

**Ground and river**, attached to the scene in Controls, chooses Table, Dry
channel or River. River inlet flow is 1–1,000 L/s; current still comes from
the native flume. Changing ground keeps the other declarations and tray
placements. The first water wheel, tank, chute or collector creates a dry
channel if its design had none, so adding those pieces no longer requires
opening a separate example. Ground changes participate in Undo, drafts and
saved versions. Removing a channel needed by existing water pieces is
refused with the compiler's reason. The ground disclosure hides while
editing a piece to keep the phone inspector's scroll area usable.

Verification: all 104 prepared object groups across the example catalogue
compile after a 5 cm horizontal move and after removal, without mutating
the shared template. Geometry/material/volume are preserved by translation;
glass, oak and iron lever pivots follow a declared 3D translation. A native
free-fall comparison for glass/oak/iron boxes at 2 cm resolution and 1/240 s
steps preserves native mass and velocity and translates the position within
1 µm after 24 steps. This is a setup transformation test, not a new contact
law or a full momentum/energy audit. All 21 Tray checks pass. The three new
browser checks pass in 23.953 s at 1280×860, 390×844 and 844×390: body selection,
prepared moves/removal, dependent rope cleanup, Undo, version save/reload,
automatic water ground, added river current, tray removal and the unfiltered
gallery. An initial phone failure exposed the open ground disclosure reducing
the inspector's scroll area; hiding it during editing fixes the actual layout
without changing the 44 px touch-target checks.

## Obsolete movement previews and the glass timing audit — October 14

Starting a live run or rebuilding a setup cancels that page's unfinished
movement rehearsal. The server terminates only the owned, disposable preview
engine. A separate live session and other visitors/pages remain untouched.
Cancelled rehearsals return no paths, goal result or claim of completion.
Page-scoped UUIDs and monotonically increasing request epochs prevent an older
HTTP request from restarting a preview after Try It. The registry retains at
most 512 recent epoch markers and the currently admitted previews. Existing
clients without these fields retain their previous API behavior.

The **Chain reaction** example was profiled at its unchanged 20 mm cell size
and 1/240 s rigid timestep. Its iron weight strikes the 480×20×280 mm glass
plate at approximately 4.68 m/s and world time 20.462 s. Subsequent shard
collisions require additional lattice runs; the rendering is not a shatter
animation. On the existing Windows engine, a paced 25.0 s run stayed at real
time with 1.289 s accumulated fracture-call waiting. A production API run took
31.84 s to reach 25.2625 s and accumulated 5.480 s of fracture waiting. This
was an ordinary engine run without a concurrent preview requested by the
test; cancelling obsolete previews cannot remove that underlying compute cost.
The earlier CPU/AVX2 optimizations and container CPU quota check are present.

An isolated unpaced Windows comparison changed only the plate material: glass
took 9.316 s wall time with 1.605 s fracture calls; oak took 6.662 s and iron
6.473 s with no fracture calls. All reached at least 25 s world time without
an engine error. Geometry, material-derived mass, contact/fracture criteria,
lattice timestep and resolution were unchanged. This is a timing comparison,
not new material calibration or a full-pipeline conservation proof. Existing
energy/momentum limitations remain in the physics roadmap. A tested alternative
SIMD row-loading kernel did not reduce fracture waiting and was discarded.

Cancellation regressions cover visitor/page isolation, delayed requests,
replacement cleanup, pre-cancelled jobs and native process termination while
a separate live world remains playable. The initial native cancellation and
subsequent live-play check together took 0.111 s. HTTP verification exercises
the actual level-preview → play route and confirms that a delayed preview
remains cancelled. The remaining public fracture delay still needs CPU
capacity/per-phase measurements on the hosting instance; no faster fracture
solver is claimed by this checkpoint.

Delivery checks: 79 game tests pass in 140.912 s, including all authored
solutions/negative cases/nudges and the nine-station Sandbox chain; 36 world
tests pass in 23.373 s; 20 HTTP tests pass in 2.347 s. JavaScript/Python syntax
and the source-registration guard pass. The browser's ordinary Reset →
Try It! flow was exercised while a rehearsal process was active: the two
owned setup/preview processes were replaced by one live process, and the
glass broke and settled. The update dialog was inspected at 390×844 and
the game at 844×390; the desktop and portrait screenshots are saved under
the ignored `build/ui-proof` directory. Native binary SHA-256 remains
`997b02d2b9f4594dbb575eeca38c17777a7ce6ec74e8832f97d265f8974464a9`.
## CPU allocation and rigid workers — October 14

Render's authenticated Compute page shows **1c-2g**, one CPU and 2 GB RAM.
Read-only inspection of the actual container showed cgroup v2 `cpu.max`
`100000 100000`, `/proc/self/cgroup` `0::/`, and affinity to 16 logical CPUs.
The lattice already respected the one-CPU quota; LiveWorld instead requested
Jolt workers from the host CPU count, capped at 64.

LiveWorld now uses the same affinity/quota detector. It reserves the world
caller and default fracture lane before assigning at most seven additional
rigid workers. At one CPU there are zero extra rigid workers: Jolt's existing
zero-worker thread pool executes its jobs on the caller. The single-threaded
job-system implementation, physics settings, contact capacity, material laws,
resolution and timesteps are unchanged. Native state and `/api/machine` frames
include read-only `runtime` diagnostics (`cpu_slots`, `rigid_workers`,
`default_fracture_threads`). CPU slots have a minimum of one even on fractional
allocations; this is a scheduling budget, not a Render plan name.

A Windows CPU-affinity launcher confined both the prior and new engine to the
same single CPU. Each ran the original Chain reaction declarations to 25 s
world time, changing only the plate material. All station records and all
body records (excluding host sequence bookkeeping) were exactly identical
between old and new runs, including geometry, mass, pose and velocity. Glass
ended with 110 bodies in both runs; oak and iron retained 25. Timings:

| Plate | Old wall / fracture calls | Bounded workers wall / fracture calls |
| --- | --- | --- |
| Glass | 8.268 s / 2.325 s | 8.275 s / 2.319 s |
| Oak | 5.060 s / 0 s | 5.038 s / 0 s |
| Iron | 4.967 s / 0 s | 4.920 s / 0 s |

These single-run timings do **not** establish a faster standalone glass break.
The worker correction bounds resource allocation. A public verification of
the preceding preview-cancellation revision reached all nine stations, stopped
its obsolete preview, and took 31.116 s wall to reach 25.0792 s world time,
with 5.620 s accumulated fracture calls. The worker correction did not resolve the standalone fracture delay.

The new native affinity regression opens 80 mm glass/oak/iron boxes at 2 m,
with 20 mm cells, on one CPU and observes zero rigid workers. After 24 rigid
steps at 1/240 s, all masses are preserved and each velocity matches the
declared gravity plus **environmental** 0.02 /s box drag within 2 µm/s.
The summed momentum residual is -6.93×10^-6 kg m/s at the native JSON reporting
precision; the bound is 2 µm/s times total mass. The initial oracle omitted
that declared drag and was corrected without loosening its tolerance. This is
a free-fall/scheduling regression, not a full-pipeline fracture conservation
or material-calibration proof.


The AVX2 damage kernel now returns zero immediately when all eight bonds
are below their material-derived damage-start threshold, matching the scalar
path. It avoids unused end-threshold calculations without changing the force
law, arithmetic precision, damage criteria or fragmentation. Five alternating
before/after runs of the same glass chain on one CPU reached exactly
25.0125 s: every reported body and station record was identical. Median
fracture-call waiting decreased from 2.289 s to 2.136 s (6.7%); median wall
time decreased from 8.202 s to 7.975 s (2.8%). A separate glass/oak/iron
comparison likewise preserved every body and station record. Oak and iron
had no fractures in this particular apparatus; their approximately 2% timing
variation does not establish a speed change. These Windows measurements do
not predict the same percentage on Render. This leaves substantial fracture
work; full-detail secondary collisions are still simulated.

Native scalar/SIMD regression CTests pass (lattice 7.70 s, LiveWorld 12.28 s).
All 79 game tests pass (125.282 s), including authored solutions, nudged
runs and physical negative cases. All 37 world tests (21.327 s) and 20 HTTP
tests (2.070 s) pass against this final executable. Python/JavaScript syntax,
diff whitespace and the CMake source-registration guard pass (271 sources).
Tested Windows engine SHA-256:
`35230eb7ee76ee0209ff034558ea6110061babd072635561b98d988b92c3f67a`.

Browser delivery: ordinary Sandbox Try It! → Pause → Continue runs the
original Chain reaction through 32.40 s, including the broken glass and
subsequent collisions. The dated Recent Changes article fits at 390×844
with its Close button unobstructed. Screenshots are in ignored
`build/ui-proof/fracture-final-local-desktop.png` and
`build/ui-proof/fracture-final-recent-phone.png`. The local checkpoint reports
the tested binary hash above and `restart_pending: false`. Finite ropes,
pulley/drum surfaces and mechanically colliding electrical wires identified
in the connection audit remain unimplemented by this optimization.


## Test build identity and saves — October 14

The test branch runs under `/test` on the existing server, using a separate
source package, native executable and machine process. Its header shows TEST;
navigation, APIs, setup shares and return URLs stay under `/test`. Test cookies
and browser progress are separate from live play. The profile bridge uses the
existing database with distinct test UUID identities and unchanged revision
conflict checks. It never acknowledges a failed upstream save as durable.
Replacing a test build ends its test runs while production remains reachable
and saved test versions persist. Routing and isolation are measured locally
and against the installed Linux runtime package. All 79 authored game tests
pass in that Linux build. The bootstrap release enables the public test route;
its checkpoint identifies the available revision independently of production.
Test simulations share host resources and have lower capacity/memory budgets;
this is not hostile-code isolation. For deployment and promotion,
see [deployment status and promotion](deploy.md#branch-testing-and-promotion).
These are hosting/save changes, not new physics measurements.
