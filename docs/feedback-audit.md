# Player feedback audit — October 12, 2026

Scope: all 30 authored levels, all 25 sandbox examples, the 31 visible piece
cards, attachment tools, anonymous saves, and shared desktop/phone controls.
This reviews the feedback accumulated in the owner conversation. A passing
physics test does not establish that a new player understands a challenge.

## Changes made during this audit

- **Turn the axle:** start the motor in reverse, with direction selected for
  adjustment. Forward is a decision the player must make.
- **River-powered lift:** start the wheel on the bank and leave its drum
  disconnected. Moving into the current and connecting the gate are separate
  necessary actions. Neither alone lifts the gate.
- **Charge then lift:** require panel Out → supply In. The panel's isolated
  local store cannot secretly power the flag. The matching **Sun powers the
  flag** sandbox example includes the same visible lead.
- Invalidate water/electrical rehearsal readings immediately on an edit,
  including edits waiting for a placement reply. Show **Updating…** and stop
  flow dots until the current rehearsal arrives. Keep the optical preview's
  independent trace/update behavior.
- Preserve version-1 recipes for the three changed Easy families; new recipes
  use version 2. Keep existing saved sandbox declarations unchanged.
- Correct obsolete roadmap entries for contact gears, lamps and switches, and
  remove a stale statement that persistent storage still awaited verification.

No native law, goal threshold, deadline, tolerance, or authored winning
placement was weakened. The solar solution adds a real charging connection.

## Every level

“Verified” below means the own solution passes three nudged native runs, the
empty setup cannot win, and the existing wrong controls are tested. It does
not mean every possible misplaced design was exhaustively searched.

| Level | Visible target and player work | Audit result / remaining concern |
|---|---|---|
| Mind the gap | Marble and cup; lengthen and position a bridge | Verified. Target exists before adding the plank. |
| Cut it down | Suspended weight and bin; align the swinging edge with the cord | Verified. No scripted severing. |
| Knock it off | Pedestal block; aim cannon, draw both leads, drag physical trigger | Verified. Missing lead, weak charge and bad aim fail; Run alone cannot fire it. |
| Up she goes | Piston height target; position steam assembly and increase heat | Verified. Heat setting is a prepared boiler input, not an editable gas/thermal construction system. |
| Chain reaction | Lever, physical contacts, cannon and block; route the falling marble | Verified. Inspectable contact diagram replaces the unexplained trigger line. The prepared circuit is intentionally supplied. |
| Bounce to the target | Laser source and sensor; align mirror | Verified; appears before Bounce the beam. |
| Bounce the beam | Beam, wall, cord and weight; route two reflections | Verified; optical preview remains available while editing. |
| Catch the sun (winch) | Broad shade wall, winch and crate; place/aim collector and draw cable | Verified. Shade still samples the collector center, not its partly lit area. |
| Lift with less | Crate, shelf mark and gantry; choose tackle geometry/counterweight | Verified; device and ropes can reopen adjustment without running. |
| Cut the cord | Waiting suspended weight; knife alignment | Verified. |
| Find the focus | Broad laser and sensor; put a visible lens in the beam | Verified. Native centered defaults already meet the goal: this teaches placement, not necessarily focus tuning. A second focus-distance lesson would be clearer. |
| Catch the sun (battery) | Wall and receiving battery; aim collector and draw output lead | Verified. Missing cable leaves only the panel's local store charged. |
| Raise the crate | Waiting glass crate and height guide; increase counterweight | Verified; acts on the existing crate. |
| Pour onto the paddles | Waiting wheel and dry channel; add a separate tank, aim and open tap | Verified. Closed tap/missed paddles fail; wheel has no attached water supply. |
| Wheel in the river | River and work area; move wheel off the bank | Verified. Current pushes immersed paddles. |
| Spring lifts the load | Waiting oak load, cradle and height guide; increase spring relaxed length | Verified; acts on the existing load. Spring/contact correction remains measured, not exact conservation. |
| Turn the big wheel | Powered toothed drive and target wheel; size and place an individual bridge gear | Verified. Native teeth/contact transmit torque; no ideal gear joint in this apparatus. |
| Tip the lever | Existing seesaw; put a raised weight over one end | Verified. |
| Turn the axle | Supply followed by motor/rotor; choose forward from reverse | Fixed in audit; verified. A separate waiting target/flag and direction arrow would improve the initial screen. The supply housing alone is not a clear task target. |
| Give it power | Waiting 12 V bulb; choose battery voltage, draw +/− leads and size copper wires | Verified. Wires show delivered watts/current and source limit. A resistive bulb works with either polarity; motor polarity changes direction. |
| Close the switch | Battery and bulb; add open switch and drag its field rocker | Verified. Mechanical force/angle closes the circuit; no queued Boolean toggle. |
| Light the bulb | 2.5 W supply; shrink the default 12 W bulb to match | Verified. Ratings and actual volts/watts distinguish demand from delivery. Overvoltage explosions are not modeled. |
| Finish the loop | Prepared battery, switch and bulb; draw missing return | Verified. Same terminal interaction as advanced sandbox wiring. Crossing wires do not create junctions. |
| Fill the receiver | Collection channel and 3 L target; aim separate tank and increase opening | Verified. Actual receiver landings count, not poured volume alone. |
| Heat to release | Waiting oak cord and weight; choose hot coil | Verified. Local heat/weakening/combustion model; not spreading environmental fire. |
| Gentle first launch | Receiving bin; aim counterweight cradle launcher | Verified. Default cradle is already released; remaining priority: held start and a player-operated live latch. Current restraint selector chooses the starting setup. |
| Marble turns on a light | Falling marble and wired bulb; place paddle switch below it | Verified. Centered native defaults win; acceptable as placement introduction, but start off-axis for a more explicit alignment lesson in a future version. |
| Water opens a gate | Guided gate; separate tank, wheel and drum connection | Verified. Open/aim tap and connect the wheel to the existing gate. |
| Charge then lift | Empty battery, motor and offset flag; aim panel and draw charging lead | Fixed in audit; verified. Prepared motor/bulb terminal wiring is visible. |
| River-powered lift | River and guided gate; move off bank and connect drum | Fixed in audit; verified. A connected wheel on the bank and an immersed unconnected wheel both fail. |

## Sandbox examples

All examples were independently composed from their saved base and placements,
compiled, and rehearsed for up to 25 simulated seconds. Native station completion
can stop a rehearsal earlier. No engine errors occurred. Examples without
stations are runnable designs, not newly certified challenge solutions.

| Example | What it shows / audit note |
|---|---|
| Gate and split | Held marbles, routing, split paths and dominoes; existing three-nudge routing test checks outcomes. |
| Chain reaction | Nine measured stations, all completed in order at 20.462 s; water/fire/glass stages remain experimental. |
| Cut and catch | Blade, cord and receiving bin. |
| Around the corner | A reflected beam reaching a sensor. |
| Find the focus | Lens focusing; sensor station completes. |
| Charge in the sun | Legacy integrated panel/store example. Its implicit battery selection differs from new player-drawn solar leads; migrate the new example in a future checkpoint while retaining old saves. |
| Lift with less | Falling counterweight, pulley and rising load. |
| Bounce and settle | Contact and damping; not a manufactured bounce animation. |
| Fast wheel slow wheel | Three individual gears with a visibly wired motor supply. |
| Tip the lever | Weight on an existing seesaw; native station completes. |
| Build your first circuit | Visible battery, closed mechanical switch and bulb loop. |
| Two bulbs one battery | Parallel loads sharing finite source power. |
| Marble turns on a light | Marble physically tips a switch paddle. |
| Motor and finite supply | Motor torque and battery discharge. |
| Burn the cord | Coil heats and weakens an oak cord; experimental combustion. |
| Drop a battery into its holder | Battery caps physically meet metal pads; rigid binary contact model. |
| Water turns a wheel | Separate gravity tank and wheel. |
| A tank that runs dry | Finite water visible in a fixed container; native outlet/depletion. |
| Counterweight cradle launcher | Cradle/contact launch; starts released, pending live latch controls. |
| Water opens a gate | Separate tank, wheel and drum rope lifting a gate. |
| One tank, one wheel | Finite source runs dry; no wheel-owned feed. |
| River powers a lift | Immersed wheel connected to a guided gate. |
| Build beside a river | Empty river workbench with waiting gate for construction. |
| Wheel in the river | Current/wheel contact without a falling-water source. |
| Sun powers the flag | Now shows explicit collector-to-battery cable; motor and parallel bulb share charge. |

## Library, controls and saving

The 31 visible cards cover marble, straight track, bend, shelf/gate, flip-flop,
funnel, block, dominoes, lever, plank, ramp, cannon, steam, knife, mirror, lens,
solar, tackle, weight, spring, individual gear, battery, switch, bulb, wire,
charging cable, motor, ignition coil, water wheel, water tank and catapult.
Attachment tools add glue/pin/string/spring connections. Legacy paired gears
remain loadable but are not offered as a new card.

| Feedback area | Present behavior | Remaining work |
|---|---|---|
| One sandbox instead of Free + sandbox | `/play?level=free` migrates into saved `/machine` designs; gallery has examples and Add New Design | None found in this audit's migration/version checks. |
| Large piece picker | Full dialog, category/search, thumbnails, return to scene | Thumbnails depend on example context; complex pieces still benefit from an illustrated connection diagram. |
| Manipulation | Click selects/View without relocating; near-object drag moves; background/secondary drag rotates; pinch/zoom supported | Smallest-phone grid regression investigated separately below; no claim that simulated touch replaces testing on physical devices. |
| Placement feedback | 5 cm ground grid, gentle snap, exact controls and dimension/turn guides | Native collision/placement checks may take time; detailed and precision controls should remain optional. |
| Predictive feedback | Marble path, continuously available optical trace, water/current rehearsal and actual live readings | Rehearsal is costly; cached last traces must visibly identify updating. Prediction does not include reference player trigger forces. |
| Phone controls | Scene-attached Run/Pause/Reset and piece actions; shared tabs; optional wiring pins/help/details | Dense circuits can exhaust label space; lower-priority labels are hidden. Visible labels alone do not prove every device is inspected. |
| Help and notes | How to play overlay; task counts instead of difficulty filters; save help on demand; Recent Changes navigation | Keep remaining lesson improvements in this audit instead of adding more explanatory boxes over the scene. |
| Anonymous recovery | Private UUID return link, cookie, local cache plus server SQLite profile; saved versions and progress recover across devices | Bearer-link loss has no independent account recovery. Backups/disk-loss recovery remain unconfigured. |
| Public persistence | Render reports `storage.persistent: true` during audit; October 11 isolated redeploy-retention receipt in [deploy.md](deploy.md) | Mount detection is not a backup or disk-loss test. |

## Unsupported or limited physics

The library does not expose every capability declared by the engine. A water
wheel/tank requires the flume workbench; a fresh dry-table design cannot simply
create a river. Fresh dry designs also have no enabled sun; use a solar example
or deliberately configure the environment. A clearer environment chooser is a
priority. Legacy solar's battery dropdown and new explicit charging leads need
one consistent new-design workflow, while preserving old saved declarations.

Water tanks are fixed reservoirs feeding modeled parcels/channel flow, not
free liquid contained in a moving bucket. Gears have contact teeth but are not
calibrated transmission models. Solar shade is one center ray. Charging leads
are ideal energy routes; electrical wires have selected resistance, not a full
insulation/ampacity/temperature model. Bulbs are resistive loads with brightness,
not exploding filaments. Gas/steam assemblies are prepared components, not an
arbitrary sealed vessel editor. Wood burning/cutting and brittle fracture retain
the experimental limits in [machine-physics-roadmap.md](machine-physics-roadmap.md).

## Verification record

Engine under test: `build/agent-integration/water-native/banjo_live_world_run.exe`,
SHA-256 `3fac18bff131cf0d819e6186969c4ed64b27210eef04e36f420bd497ce39d24a`.
Default live stepping is 1/240 s. No C++/native physics source changed.

- Full game baseline: 51 tests passed, all 30 own solutions 3/3. Examples sweep:
  25/25 runnable without native errors. This is a smoke audit, not per-example
  full energy/momentum certification.
- Changed solar lift: aligned panel plus cable 3/3; flat, missing lead and empty
  fail. Comparative oak/glass/iron runs at 1/240, 1/480, .001 and .0005 s retain
  the original conditions. At .75 s, oak lifts about .092 m; heavier glass/iron
  do not. Oak mechanical residual spans −.00256 to +.000327 J. Electrical
  residual is bounded by the existing 1e−8 J test, thermal by 1e−6 J; coupling
  correction is recorded separately, not called exact conservation.
- New wrong/default controls: five cases, three nudges each, all fail without
  engine errors. New motor/river/solar recipes: four presets per family plus
  retained v1 recipe passed native preflight.
- Final full game run: **52 tests passed in 84.765 s**. Electrical: 25 tests
  passed in 37.278 s; mechanics: 15 in 22.591 s; water/launch: 12 in 30.397 s;
  combined solar: 3 in 9.523 s.
- Recipe suite: all 22 families' four presets, 264 successful nudged solutions,
  no empty/wrong wins. Of 18 checks, one old assertion expected the motor's
  current identity still to be v1; it now explicitly checks retained v1 and new
  v2 and passed on rerun. Native recipe outcomes had no failures.
- Browser sweep: 75 existing checks, initially one failure at 320×568. A 3 cm
  test move projected below the 7 px accidental-click guard. The precision-drag
  fixture now exceeds the guard before returning to its exact endpoint;
  thresholds and placement tolerances were not changed. Grid checks at all
  four viewports passed on rerun, along with separate no-move clicks/tiny drags.
- New catalogue sweep: all 30 levels at 1280×860, 390×844 and 844×390 (90 opens)
  expose unobstructed ≥44 px Run/Reset controls in the adjacent scene toolbar.
  New solar cable/no-cable, motor direction and delayed-reply feedback tests
  passed; current river UI and placement/camera checks also passed. Anonymous
  cookie, fresh-browser return-link, Unicode saves and version-restore checks
  passed in the broader sweep. These are browser-emulated phone layouts.
- Source registration: all 269 sources registered; client view CTest,
  JavaScript syntax and changed-file whitespace checks passed. Local solar lift
  was played through ordinary collector settings, endpoint clicks and Run,
  reaching three stars. Desktop and phone screenshot review completed.

Public revision and final live check are reported in the task's publication
receipt rather than adding a commit identifier to the commit that contains it.

QA inventories and raw run receipts are ignored artifacts under
`build/agent-integration/feedback-audit-*.json`; private visitor credentials are
not in this document, screenshots or Git.
