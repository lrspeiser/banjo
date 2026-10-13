# Puzzles on the machine (/play)

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
  drawn at its starting top plus 5 cm. The spring can attach to an existing
  moving load in the sandbox too; its original included-load mode remains.
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
**Run it** alone leaves it open. Reset restores the original open handle.
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

**Valves and release**, beside the 3D scene, queues water-valve and catapult-restraint operations between engine steps. **Run it** continues that same session; **Set up again** restores the saved initial state. These live operations do not change a saved version. Manual switches instead use their physical field handles. Prepared, player-placed and flow-preview wires use the same thick floor routes, with short leads up to the actual terminals. Wires brighten yellow from measured current, and bulbs glow from measured emitted optical power. Removing a device removes its attached wires and renames surviving references; Undo restores the graph. Saved versions and shared links retain the initial parts, connections, charge, water, preload and restraints.

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

## Fresh easy challenges

**New challenge** on the level chooser lets the player select any of the twenty families. The same action beside an easy challenge makes another setup in that family. It changes one bounded physical input: source power, sunlight elevation, supply voltage, cord or lever length, load height, bearing friction, starting water, flow or catapult cock angle. Prepared settings are fixed in that challenge's tray; its goal and deadline remain the family's own. There are 78 physical presets across the twenty families; different seeds can select the same preset. This is repeatable authored variation, not unlimited procedural geometry or a language-model-generated level.

Before offering a setup, the server rehearses its private solution, empty machine and wrong setup with three nudges each. All three correct runs must win and every empty/wrong run must fail without engine errors or incomplete rehearsals. It tries at most three seeded candidates, then a checked original setup; the page explicitly identifies that fallback. It refuses the request if even the original fails. Public responses contain no solution, wrong placements or private rehearsal receipts. Native preflight shares the server's two preview slots and reliability-check request allowance.

Versioned recipe IDs include family, seed and accepted attempt. **Share this challenge** exposes a link to that exact recipe. The last twelve generated challenges appear under **Return to a challenge** inside the chooser’s **More** menu for the current anonymous save. Shared recipes are verified on their first request to a server/engine; an in-memory bounded cache avoids repeating the work on subsequent requests. Energy par is the actual three-run mean rounded upward to three significant figures, including measured water source work. Reopening recreates the initial puzzle; **Set up again** retries with the pieces currently placed.

The native sweep passed all 78 presets: 234/234 correct nudges won, 0/234 empty and 0/234 wrong nudges won. Goals and deadlines were unchanged. The sweep took about 90 seconds on the integration binary; its eight-test suite also checks seed identity, bounded retries, fallback refusal, native errors and incomplete negative runs. Delivery regressions verify exact recipe reopening after cache loss and keep water work in rehearsal energy receipts. The full game/browser suites now contain 39/25 tests, including generated challenge → terminal selection → native win → share/reload → recent replay on desktop and both phone orientations.

## Playing a level

**One control panel.** The tray, Run/Pause, Reset, Pull/Attach, Undo/Redo, camera turn/zoom buttons and the selected piece's movement and adjustment controls share one module. It stays on the right on desktop and phone landscape, and below the visible scene on phone portrait. Scrolling the phone panel leaves the scene visible. Camera buttons turn or zoom the view without moving the ghost. The live valves/release disclosure is in this panel too; manual rocker handles stay on the scene.

Tray carousel verification, October 11: all 37 Chrome browser tests passed in 186.1 s, including desktop 1280×860, portrait 390×844 and landscape 844×390. Checks cover single-card trays, wraparound browsing without a new engine setup, clicking the selected card, cancellation, the full library, saved versions, eight placed batteries exhausting their sandbox card, and unobstructed 44 px arrows/actions. An independent four-test agent run passed in 29.0 s. Phone checks now scroll the real pane and open the Tools disclosure before inspecting its controls; each phone-tab case creates an independent design. Terminal buttons also refresh when a wire connection finishes, addressing a timing failure in the previous Linux CI run; the saved-wiring check passed three repeated runs. The client geometry CTest and all 269 source registrations passed. This changes the page controls, not physics, energy accounting or the save schema; the native executable remains SHA-256 `569a441595274e13128e1b8f06ff54d392232409b312d2089a77c2451315c976`.

Undo toolbar verification, October 12, 2026: six focused Chrome regressions passed in 41.2 s. The new check exercises levels and independent Sandbox designs at 1280×860, 390×844 and 844×390, with unobstructed buttons at least 44×44 px on every tab, and Undo while the panel is collapsed. Placement, adjustment, removal, Redo, circuit reconnection/disconnection and saved-version restoration retain the original setup. Separate local browser play and screenshots cover desktop and phone layouts. The source registration guard passed for all 269 sources. This changes the client toolbar only, with native engine SHA-256 `0bcf6978067ec59ab0b89325abb8feef051e398594169c602e664a989e2883a0`; no physics law, timestep, goal, energy accounting or conservation tolerance changed.

**Adjust a placed device.** Click its solid parts or rope. A tackle's connected crate also selects the tackle when it has a single owning pulley device; for a shared load, click the device itself. Thin ropes have a six-screen-pixel selection margin. Picking up during or after a run restores the initial setup and opens the ghost at world time zero; it does not start the live simulation. A late reply from the old run cannot restart the editing session. Set down commits the adjustment; Cancel restores the piece.

Reset and compact-toolbar verification, October 12, 2026: 14 focused Chrome regressions passed in two batches (eight in 95.9 s, six in 59.0 s), at desktop 1280×860 and phone 390×844 / 844×390. Reset clears a challenge after a win or during an adjustment, restores the tray, discards the pending ghost and returns native time to zero; Undo recovers the last completed setup. Sandbox Reset preserves its base, pieces, saved versions and selected tab. Restart with my pieces retains circuits, solar connections and water routes while returning their native state to zero. The first broader phone check exposed the preceding two-row toolbar reducing the control pane below its existing minimum height. The final toolbar puts Undo beside Run/Reset in one row and moves Collapse/Expand to the scene corner; the original pane-height checks now pass without changing their thresholds. Local browser screenshots confirm the layouts. All 269 source registrations and 65 local document links pass. This changes client controls only, using the same engine SHA-256 `0bcf6978067ec59ab0b89325abb8feef051e398594169c602e664a989e2883a0`, with no new physics or conservation claim.

Checked on October 11, 2026: all 29 Chrome browser tests passed in 112.5 seconds, including real clicks on the tackle rope and crate, post-win adjustment, separate camera movement, and visible unobstructed 44 px action buttons at 1280×860, 390×844 and 844×390. The tackle solution reaches its unchanged goal at 3.70 s. The final compact layout also has a targeted tackle/phone rerun. This page change uses the previously verified solar checkpoint engine; no native physics, timestep, conservation tolerance or material model changed. Source registration still covers all 269 C++ sources.

- **The goal** is a green box drawn in the scene ("the ball is in the cup") and a time limit. The engine checks it on every step: the goal happens when the named part's centre is inside the box.
- **The tray** is one large clickable pictured card at the top of the control panel beside the 3D view. Its 72 px thumbnail, piece name and remaining count replace the small Add button and the duplicate tray list lower down. Click the card to add its see-through **ghost**: it is not in the machine yet. When there are multiple piece types, **Previous piece** and **Next piece** arrows cycle through them and wrap at either end; an index shows which card is displayed. Browsing does not place a ghost, change the build or rebuild the engine session. Cancelling placement returns to the same card. A single piece type has no arrows, and an exhausted card is disabled. The sandbox's 31 cards can be browsed this way, while **Add a piece** still opens the full library with search and categories. The pictures are drawn in the page from the piece's own parts, as the server would build it. A level whose goal is about a piece (level 4: the engine's piston) opens before that piece is placed, with its goal zone drawn, and says what it needs.
- **The ghost is placed at once**, where the middle of the view meets the scene, ready to change. Drag it or use the arrows to adjust it. A scene click or tap never relocates it; it returns to View. Set down or Run it confirms placement.
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
- **Test a part: 🖐 Pull.** Beside Run it is a Pull switch. With it on, press on any loose part in the scene and drag: the engine pulls that point of the part that way, harder the further you drag (400 N a metre, at most 200 N), a line showing the string, and letting go lets go. It is a force on the part, not a hand in the world. Pulling starts the world if it was not running. The work your pulls do counts in the run's energy, and a run using this general Pull tool is **a test run**: it says whether the goal happened, earns no stars and is not kept -- to win, the machine has to do it. (On level 5 with no ramp, pulling the lever's end down closes the firing circuit and the cannon fires.) While Pull is on, clicking one of your pieces pulls it rather than picking it up. Right/middle or Ctrl+drag turns the camera without starting a pull. A second touch releases the force to zero before turning the camera; cancelling or losing pointer capture also releases it.
- **A rope cut part way** (level 2) is weaker by what was cut: it holds the weight if what is left can carry it, and tears at the cut if not -- the piece above the cut staying on its arm, the piece below falling with the weight. A knife whose swing runs out part way through, or a blade that only clips the rope, leaves it hanging by what is left (docs/cutting-model.md, "A rope cut part way through").
- **A cord that sways** (Bounce the beam): the weight hangs on a chain of small oak segments that swings and is knocked about, with a cord through it carrying the weight exactly; the laser chars one segment away and the cord parts there, the chain with it, and the weight falls. Level 2's rope is still the stiff one, because a knife swung into a slack chain knocks it aside (docs/cutting-model.md, "A cord that bends and sways").
- **Nothing floats.** Everything in the world is held up by something: a fixed part stands on the ground, or is bolted to a fixed part that does, by a chain of them down to the ground. A piece that would hang in the air gets a stand, a concrete post from the top of whatever is under it (the ground, a table) up to its underside: a mirror stands on a post, a cannon's barrel on one, a ramp on two legs. A leg goes where it is clear, moved along the piece off whatever is in the way (level 5's lever), and a piece held by one leg needs no second; when no leg finds anywhere clear, the piece is red and says what its stand goes into. The stand is part of the piece: it shows with the ghost and in the tray's picture, and its concrete counts in the energy to make the piece. The levels' own parts keep to it too: Bounce the beam's laser sits on its post, and Lift with less's rope turns over two iron pulley blocks hung under the gantry's beam, the beam over the rope and the counterweight in line under it (it has no across knob). Loose things need no stand: gravity and contact hold them, or they fall. `scripts/machine_game.py` `hold_up` adds the stands as a level is built; tests/machine_game_tests.py checks every level, with its solution and with every knob at either end of its range.
- **Set it down** (or press Enter) and the engine builds it. From then on a loose piece is held only by gravity and contact: a plank too short for the gap falls in, and one too long for the ledges rests on the tables' tops a step up. Cancel (or Esc) throws the ghost away. Clicking (tapping) the piece in the scene turns a piece you have set down back into a ghost; Cancel puts it back as it was. During or after a run the level goes back to its start first, where pieces are placed. **Run it** also sets down the piece you are adjusting, then starts the machine in one rebuild. It waits for the latest placement check; a piece that does not fit stays red with the reason, so you can move it. Cancelling the piece while that check is pending cancels the requested run.
- **Where things will go.** Before a run, the scene shows a see-through path for every loose thing, and a see-through copy of the goal's thing where it ends up: the engine rehearsing the level as it stands, quickly and out of sight (with a ghost as if it were set down, so moving or turning a ghost shows where things would go). It is blue while a thing moves freely, green inside the goal zone, and after it hits something, that thing's colour, with a dot where it hit; a key over the scene says when the goal would happen and what each colour is. It is the engine's own answer, so the run follows it (level 1: the goal at 1.90 s in both). It changes a moment after anything is changed and stays up while the run plays. Each preview is a rehearsal of engine time: rationed per visitor (BANJO_PREVIEWS_PER_HOUR 300, BANJO_PREVIEWS_PER_DAY 6000) and two at a time.
- **Run it** and **Reset** stay visible beside the section tabs on desktop and phones, even when another tab is open or the panel is collapsed. **Undo / Redo** occupy the upper scene corner. Pull, Attach, **Restart with my pieces** and speed/follow controls appear directly within Controls when applicable. The prediction key stays over the scene. Run commits any valid new piece or adjustment at its current position (one Undo step), builds the machine afresh and plays it at real time; while it plays it is Pause, then Continue, and after the run Run again. Reset puts a challenge back at its authored beginning, clears your added pieces and restores its tray. Undo recovers the cleared setup. **Restart with my pieces** in Controls returns to time zero with your build. Sandbox Reset returns the machine to time zero, cancels a pending edit and keeps its design and saved versions. When the goal happens, a card in Controls says **Level complete!** with the stars, **Energy details** and the next actions, and the world stops a moment later; the card sits in Controls so it leaves the 3D machine unobstructed (the details start folded away; opening them shows the total, the run and each piece on desktop and phone, with the card scrolling within Controls when needed). A first win with a tool -- a plank, a knife, a cannon, a steam engine, a ramp, a mirror, a solar panel, a block and tackle -- says **Achievement Unlocked** instead, and which tool; each player's tools are kept with their progress (a player's wins from before tools were counted bring the tools of the levels won). After the last level it says so and offers level 1 again. When time runs out without the goal, the card says so and offers **Start over** (the level as it began, no pieces) or **Keep my pieces** (back to the start with them, to move or change): running the same pieces again would only do the same thing.
- **Energy: win on as little as you can.** A win is scored by the energy it took, two kinds, both real: making your pieces (each part's mass, from the engine's densities, times its material's embodied energy -- typical cradle-to-gate values from ICE, the Inventory of Carbon and Energy: oak 10.4 MJ/kg, iron 25, aluminium 155, glass 15, concrete 0.95; ice is the heat taken out to freeze it), and what came into the machine during the run, each once: what its batteries gave, as the engine measured it (a coil's heat, a laser's light, a motor's work all come out of a battery and are counted there, not again where they end up; the sun's is free), fuel burned in its heaters (level 4's firebox: its 12 kW for as long as the run has gone), and the powder in its charges at 2.8 MJ/kg. Making the pieces dwarfs the run (a 0.7 m oak plank is 30.6 MJ; a gram of powder 2.8 kJ), so smaller pieces and cheaper materials count most: in Lift with less an iron counterweight, heavier, takes less energy to make than an aluminium one. Each level's par (`par_energy_j`) is its own solution's energy, measured, rounded up to three figures.
- **Stars**, from what the engine measured: one for the goal in time, a second for winning on no more than a quarter more energy than par, a third for par or less. If the chat placed the pieces, one star at most. The win card offers Next level, **Play again** (back to the start with your pieces, to win on less) and All levels. Its **Energy details** says what it took (pieces and run), against par and your best. Checked in Chrome at 1280 × 860, 390 × 844 and 844 × 390: the details open and close, the piece breakdown is visible when open, and the next actions are reachable inside the scene (tests/machine_game_browser_tests.py, October 11, 2026).
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

October 13, 2026: desktop, phone portrait and phone landscape share **Controls / Level (or Design) / Help** tabs. **Run it / Pause**, **Reset** and collapse/expand stay beside the 3D view on every tab. The level name and a one-line task appear beside the scene; **Puzzle details** keeps the full brief, deadline and energy par. **Undo / Redo** sit in the upper scene corner, while a logarithmic zoom slider and minus/plus magnifiers sit in the lower corner. Zoom spans 0.4–40 m without changing the piece; wheel, trackpad pinch and touch pinch remain supported. Corner controls reserve space in callout and terminal placement.

There is no **Tools and speed**, **Readings and wiring** or **Adjust a piece** dropdown. Applicable actions appear in Controls: Pull, Attach, Restart with my pieces, speed/follow, Connect wires, valve/release controls and inspection. During an edit, optional test tools stay under Precision controls to leave room for the active setting; Sandbox Reset already keeps the design, so it needs no duplicate restart action. **Focus selected piece** is in the selected inspector; optical focus also frames source and receiver. **Whole machine** restores the overview. Result cards stay in Controls for every level, including tackle and Chain reaction, so a completed run does not cover selectable geometry.

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

The header's **Sandbox** link and the levels screen's Sandbox card open `/machine`: a single gallery with **Your designs** first and all **Examples** below, plus **Add New Design** in its header. A new design opens immediately as **Untitled design**; rename it in the editor’s **Design** tab. Cards show static top-view setup sketches from declared geometry (unexpanded pieces are position markers), rather than a physics rehearsal. Start from an editable copy of **Gate and split** (the former free-build example) or **Chain reaction** (the original sandbox declaration). There is one editor: the levels' tray and placement controls, Run it, Pause, Set up again, Pull and Attach, plus the sandbox's speed, Follow, engine readings and base declaration. Nothing is scored. The empty table's corners are marked by small concrete stones, 2 m out each way. The tray has every piece, subject to the server's part, cell and tray limits.

**Choose a piece.** **Add a piece**, attached to the scene beside Run it, opens a full-screen library with large thumbnails drawn from each piece's actual parts, descriptions, search and category filters. Choose a card to return to the same design with that piece as a ghost, ready to place. **Back to sandbox** or Escape closes the library without adding anything. Only the cards scroll: search and Back stay visible. Keyboard focus stays inside the library and returns to the scene when it closes. Puzzle trays of four pieces or fewer keep their individual buttons in the control panel; larger puzzle trays use the same library with remaining counts and **Back to puzzle**. Attach remains beside the scene. Checked on October 11, 2026 (`tests/machine_game_browser_tests.py`): search, category filters, no matches, closing without changing the setup, selecting and placing a piece, running and resetting the resulting machine at 1280 × 860, 390 × 844 and 844 × 390. No engine or physics model changed.

**Saving and reopening.** Drafts sync as you change the setup, separately for each design in your anonymous save. **Save version** validates the setup and keeps a checkpoint; **Saved versions** restores one of the latest 30 checkpoints. Restoring a different version also checkpoints the previous draft, so you can return to it. **All designs** returns to the library and stops the current simulation. Reloading a design's URL reopens its draft. Saved setups contain initial declarations and placements, not bodies' positions after running. Existing free builds migrate into **My free build**; old `/play?level=free` links reopen the last design. Server save failures are reported and unsent changes remain in the browser cache when available; use a shared design link to export a copy. Your private return link restores server saves on another device. The save-status message distinguishes durable storage from an unmounted public filesystem.

**The machine as data** edits the base declaration, before tray pieces are added; both are kept together in saves and shared links. A base can contain its own stations, which remain visible under **Engine readings**. Its explicit anchors and kit supports are retained; automatic stands are added to tray pieces only. Names starting with `your ` belong to tray pieces and are refused in a base. A custom base cannot replace a puzzle level. **Set out the example** replaces the setup with Gate and split. **Clear the table** removes both the base and tray pieces; saved versions remain and Undo restores the cleared setup.

Checked on October 11, 2026 (`tests/machine_game_tests.py` and `tests/machine_game_browser_tests.py`): both templates compile; the chain's original 25 parts and nine stations are retained. All nine happen in order, from the wheel at 1.867 s to the glass breaking at 20.462 s (4.98 s wall time in the unpaced rehearsal on this computer). Gate and split still reaches both outputs and topples all six dominoes in its nominal and nudged runs. Chrome checks cover migration, two independent designs, draft reload, save/restore, storage refusal, clearing and undoing a base with added pieces, old and new share links, and the library and scene controls at 390 × 844 and 844 × 390. Manual checks also used 1280 × 860. This changes composition and storage, not the native physics model: the engine timestep, cell resolution, material laws and conservation tolerances are unchanged. The chain's experimental burning and glass fracture retain their existing limitations.

The pieces, besides the levels' plank, ramp, cannon and steam engine:

- **Marble**: an iron, oak or rubber ball, 4 or 6 cm, set down on whatever is under it. On a slope it rests on the slope itself, not on top of the slope's box.
- **Track**: a board with a rail on each side, from its top end down by its drop over its length. It can be turned about the upright to point any way. Its far end is open (a marble rolls off it), a stop (the marble stays there), or a gate.
- **Shelf**: a short track tilted a little toward its gate, so marbles set down on it roll to the gate and wait there. This is how a marble stays up high until something lets it go.
- **The gate**: a flap hangs across the track from a bar on a pin over one rail, and the pin runs along the track. A marble pushes the flap along the pin, which the pin holds, so the flap doesn't move. Out past the rail is a short arm with a paddle on its end. Press the paddle down (drop a marble on it, tip a lever under it, or pull it) and the flap swings up out of the way. On its own it falls shut again. A **gate that stays open** has a catch that holds it once it is 20° up. Measured: three iron marbles wait at a closed gate. An iron marble dropped onto its paddle swings it up 56°: with the catch, all three roll off the end; without it, the gate falls shut before they arrive and they wait.
- **Flip-flop**: a rocker on a pin, tipped one way, with a fin standing up from its middle. Drop marbles on its middle from a track end above it, along the pin, and they go one way, then the other. The fin leans toward the low end, so a marble lands on the high side. Its weight tips the rocker over and it rolls off that end, leaving the rocker tipped the other way for the next marble. A board behind the rocker holds its pin and stops a marble that comes in fast. Measured: four iron marbles fed down a track went right, left, right, left. Two marbles that arrive together go the same way, as they would on a real one. An oak marble is too light to tip it.
- **Bend**: a curved track, turning up to 180° either way round a radius of 15 cm to 1 m, dropping as it goes. It is made of straight sections, one for every 22.5° of turn, each a board with a rail on each side, overlapping at the seams. A marble rolls on a tilted board's true surface (measured to a tenth of a millimetre, turned or not), not on the cells the board is built from, so a marble goes round a bend smoothly: down a track, round 90° either way, onto the track snapped to its far end and to that track's stop.
- **Funnel**: a square mouth 20 cm to 1 m across, four boards sloping in to a 6 cm hole 12 cm lower. It gathers marbles from several paths into one: what lands anywhere on it rolls in and drops out of the hole. Measured: marbles dropped on its corners, its edges and near its middle all went through the hole within 2 cm of its middle. Moved near a track's far end, it goes under it, its mouth 6 cm past and 2 cm below.
- **Block**: a fixed post, wall, step or stop of any size, in concrete, oak or iron, set down on what is under it.
- **Dominoes**: a row of oak dominoes, 2 to 20 of them, standing on what is under the row.
- **Lever**: a seesaw on a pin on a block.

**Snap points.** While a piece is being placed, dots show where the other pieces connect: green where a marble comes in (a track's or bend's top end, a flip-flop's middle), amber where it goes out (a far end, or below and just beyond a flip-flop's ends, where what joins there is clear of the rocker as it tips), violet a gate's paddle. Drag a piece near one, within 10 cm across the ground and a metre up or down, and it is put where the two connect, and its bar says what it is joined to. A track's top end goes 3 cm past and 4 cm under another's far end, so what rolls off drops onto it. A track's far end goes 4 cm above another's top end, or 11 cm above a flip-flop's middle and 4 cm short of it, or 6.5 cm above a gate's paddle and 5 cm short of it, because what rolls off flies on a little as it falls. A flip-flop goes under a track's far end with its board behind, where the marbles fly. A marble goes just inside a track's top end. Only a piece moved by hand snaps; the arrows, the sliders and turning move it freely. Measured: a marble rolls down a track and onto the track snapped to it, and stops at its end.

**Attach.** 🔗 Attach joins two parts: press one, then the other, and choose **glue** (held together where they were pressed), a **pin** (they turn about it, its axle along x, along z or upright), or a **string** (tied from the first point to the second, as long as it is then). A join is one of your pieces: it is listed, kept with the build, taken back with Undo and removed with Remove. Taking a piece away takes the joins to it with it. Two fixed parts are not joined, since that would move nothing. A pin or glue shows as a dot where the parts join, and a string as a line. Measured: a plank on a block, pinned at its middle, tips when a marble lands on one end and stays on its pin; glued there, it does not tip.

**Sharing a design.** **Share this design** makes a link containing its name, base declaration and tray pieces, compressed into the part after the `#`, which a browser never sends to the server. It is copied, and also shown to copy by hand. Opening it creates a separate design; existing designs stay in the library. Older links containing only tray pieces are still readable. A link pasted into a tab already on the page works too.

**Build with words.** In a free build the chat builds what it is asked, for example "hold three marbles up high behind a gate, then split them three ways". The model does not work out where things go; a model cannot lay out a build of many parts from numbers. It says which pieces it wants and what each one **joins** to: "this marble joins the shelf's top end", "this track's far end joins the gate's paddle", "this flip-flop joins that track's far end". The server puts each piece there with the same rules as snapping by hand. Marbles joined to the same top end line up along it. A track joined to a far end or a flip-flop's end starts the way the marble leaves; to turn, a bend goes there. The server lays the build out on a table as big as the world and then moves the whole build to the middle of the real table. It checks the build: a build it refuses goes back to the model with the reasons, at most twice. Then it rehearses it once in the engine, and the chat says how many marbles ended on a piece and how many on the floor. Run it to watch, and move what needs moving. The model is told recipes that were measured to work. Built from joins alone, four marbles held on a shelf end on all three tracks of a three-way split (tests/machine_game_tests.py). Asked the request above three times, gpt-5-mini built it each time; in two, every marble held on the shelf ended on an output track, and in the third one stopped on a flip-flop.

**Copy, undo and redo.** Copy, beside Pick up, makes a new ghost of a piece 10 cm along from it. **Undo** stays beside Run and Reset on every tab and when the controls are collapsed, in both levels and Sandbox. It is disabled until there is a completed change to take back. **Redo** remains in Tools and speed. Ctrl+Z and Ctrl+Y also take back and put back changes to the pieces: setting one down, moving or adjusting it, removing it, wiring or disconnecting it, clearing the table, setting out the example, joining two parts. History holds up to 60 setup changes for the current visit; saved versions keep designs between visits. Undo restores the setup and resets the run; it does not rewind running physics.

**The example**: a marble rolls down a short track onto a gate's paddle, and the gate opens and its catch holds it. The three marbles waiting on the shelf behind the gate roll off onto a track that runs down to a flip-flop, which sends them to the left and right. One track ends at a stop; the other runs out onto the floor into six dominoes, and they fall. Measured in the engine: the gate catches, marbles reach both sides and all six dominoes fall, in the run as written and in runs with every loose part nudged by up to 1.5 mm. The preview follows the marbles first. Its key names four of the things they hit, and how many more.

A thin turned part, such as a domino turned a quarter round, is built from the engine's grid of 2 cm cells. When its middle lies exactly between cells, no cell would be inside it, and the engine refuses a world with a body that has no matter. Such a part is now moved across its thickness by a quarter or half a cell and the machine's notes say so; none of the levels' parts needs it.

## Asking for help

Phone tabs verified October 11, 2026: the full Chrome suite passed 31 tests in 129.6 s at desktop 1280×860, portrait 390×844 and landscape 844×390. After the final test changes, the two tab/flow regressions passed again in 17.2 s, including real scrolling to the last Design disclosure, visible 44 px targets, saved versions, Run/Pause/Reset from another tab, automatic piece selection, preserved chat drafts, rotation and keyboard navigation. A 320×568 phone layout was also inspected manually without horizontal overflow. The client view test and all 269 source registrations passed. These are UI checks using the previously verified engine SHA-256 `569a441595274e13128e1b8f06ff54d392232409b312d2089a77c2451315c976`, not new physical measurements. The previous Linux CI preview check could read its drawing statistics before the first render; it now waits for the same positive laser-segment count without changing its timeout.

On phones, the panel beside or below the scene uses **Controls**, **Design** (or **Level** in a puzzle), and **Help** tabs. Controls contains the tray carousel, camera, piece adjustments and flow preview; Design contains saving, versions, the placed-piece list and engine/data disclosures; Level contains the puzzle objective; Help contains the existing chat. Each selected section has the full remaining panel height and scrolls within it, with no content behind a sticky controls box. Run/Pause and Reset stay in the tab toolbar. Picking up a piece selects Controls and brings its adjustments to the top. Draft text, scroll positions and the machine survive tab changes and resizing; desktop shows the sections together again. The tabs support arrow keys, Home and End; their arrow keys are consumed before the scene's piece-nudging shortcuts. This is a page layout change; the physics and save format are unchanged.

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

The deployed site is the game and nothing else, open to anyone with no login: `scripts/voxel-lab.py --site game --public` (the Dockerfile's command) serves `/play`, the sandbox `/machine` it is built on, and what those pages load; `/` goes to `/play`; every other page and API answers 404. With no password in front of it, what costs money or a lot of engine time is rationed instead: the chat (which spends the model's key) to 12 requests per visitor an hour and 400 a day, and the reliability check to 30 per visitor an hour and 2,000 a day (BANJO_CHAT_PER_HOUR, BANJO_CHAT_PER_DAY, BANJO_TRIALS_PER_HOUR, BANJO_TRIALS_PER_DAY). The server runs at most BANJO_MACHINE_SESSIONS live levels at once (10 as deployed, from the Dockerfile; 4 by default). Nobody's game is ended while they play it: a new level takes the place of one whose page has closed or gone quiet for 15 s (a page polls every second, and tells the server when it is closed), else of one whose player has not built or started anything for 3 minutes; otherwise the newcomer is told the site is busy and to try again in a minute or two. A level closed while it sat idle is built again when its player presses Run it. A player can **tell us what happened** from the box under the verdict: their words, with the level and the pieces placed, are written to the server's log as a `FEEDBACK` line and to `feedback.jsonl` beside the machines' logs, rationed to 10 an hour per visitor and 500 a day; nothing that names the player is kept. **How to play** opens only when the header link is clicked. It is a modal layer over the current puzzle, level chooser, sandbox library or saved design; it never navigates or rebuilds the machine. Close, Escape or a backdrop click dismisses it and returns focus to the header link. Its scrollable instructions keep the 44 px Close button visible on phones. It does not appear automatically on a first visit. `--public` is refused without `--site game`. Without `--public` the server needs `BANJO_PASSWORD` to listen anywhere but on this computer.

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
sample no longer appears over an unchanged open mechanism. **Run it** uses the
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
