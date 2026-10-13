# Sandbox electrical pieces and measured circuits

October 11, 2026. `scripts/sandbox_electrics.py` defines placeable batteries,
manual or hinged paddle switches, bulbs, wires, motor mounts and attached
heating coils, plus explicit solar power leads. Their terminal graph compiles to `machines::Circuit`; positions
and names do not substitute for a circuit solve. Existing solar panels charge
the same declared battery store used by the graph.

## Bulb sizing and shared supply limits (October 12)

**Light the bulb** now begins with a large bulb on a prepared closed loop.
The bulb-size family declares 12 V components: large 12 W / 16 cm diameter,
medium 6 W / 13 cm, small 2.5 W / 10 cm. The native resistor is still
`R = rated_voltage² / rated_watts`; geometric size does not derive its rating.
Glass geometry and mass come from the normal compiled body. Older small/bright
presets retain 3/12 W ratings and their 10 cm geometry when **bulb size** is
set to **preset** (also the default for saved designs missing that field).

The prepared finite store is 12 V with nominal maximum power 2.5 W. Native
regulation caps current at `max_power / nominal_voltage = 0.208333333 A`,
reducing terminal voltage as needed and booking regulation heat. It is not
a constant 2.5 W delivered to the lamp. The source has 0.05 Ω internal
resistance, each of three legacy prepared leads 0.01 Ω, and the closed rocker
0.001 Ω. The analytic current is `min(12/(R_lamp + 0.081), 2.5/12)`.

| Size | Rated W | Lamp V | Lamp W | Current A | Goal nudges |
|---|---:|---:|---:|---:|---:|
| Large | 12 | 2.5 | 0.520833333 | 0.208333333 | 0/3 |
| Medium | 6 | 5.0 | 1.041666667 | 0.208333333 | 0/3 |
| Small | 2.5 | 11.983148697 | 2.492983554 | 0.208040776 | 3/3 |

The unchanged goal is ≥2 W for 0.5 s within 4 s. The small bulb wins at
0.583 s, drawing 1.456285432 J, with a 101,023,754 J embodied construction
score and retained 102 MJ par. Nominal plus two whole-apparatus nudges use
the existing 1.5 mm loose-body perturbations. The initial switch is already
closed; no runtime script changes it or switches to a smaller bulb.

One-second native integrations at both 1/240 and 1/480 s, 2 cm voxels, produce
the same V/I/W above. Large and medium draw 2.5 J; their heat/light splits are
2.395833333/0.104166667 J and 2.291666667/0.208333333 J. Small draws
2.496489312 J, with 1.997892601 J heat and 0.498596711 J emitted light.
Maximum electrical residual across all six runs is 1.22e-12 J and maximum
thermal residual 5.27e-8 J. Tests also bound KCL residual below 1e-9 A.
These are full native circuit receipts, not a mechanical energy audit.

Wire badges carry the connected finite source's declared voltage and maximum
power through the same flow frames as measured current/power. One lead per
circuit displays that shared rating to keep phone scenes clear; other leads
keep their measured-flow labels. **Shared supply**
means all branches and losses share this rating; it is not independent power
per wire, guaranteed arriving voltage, a heat-based cable limit or ampacity.
The bulb badge separately shows actual voltage drop, rated volts/watts and
the goal. Unsupported filament temperature/resistance, insulation failure,
wire mass and realistic bulb explosions remain unsupported. The analytic
circuit oracle is material-neutral; existing glass/oak/iron heater comparisons
still run in the electrical regression set.

Fresh recipes use v3, with source limits 2.5/2.6/2.7/2.8 W. All four presets
pass three correct, empty and oversized-bulb checks: 12/12 correct wins and
zero empty/wrong wins. Legacy v1/v2 seeds keep the earlier circuit, source
limit, knob choices, solution and par; cache-loss and native validations pass.
Verification: 25 electrical tests (35.54 s), five focused recipe/compatibility
tests (11.11 s), and the full 51-test game suite pass. Three browser tests
pass at 1280×860, 390×844 and 844×390 (36.78 s), exercising the oversized
failure, actual size edit, successful run, source labels and prior battery/
power feedback. Native binary SHA-256 is unchanged:
`3fac18bff131cf0d819e6186969c4ed64b27210eef04e36f420bd497ce39d24a`.

## Battery voltage and copper wire resistance (October 12)

The current **Give it power** lesson has a fixed ground-mounted supply and
the existing 12 V, 3 W resistive bulb. Its goal remains 2 W for 0.5 s within
4 s. The player chooses voltage and draws both terminal connections; contact
alignment is retained only in the older v2 lesson and the Sandbox holder.
Fresh seeded battery recipes use v3; v1/v2 declarations and seeds are preserved.

Selected copper wire resistance is `rho * L / A`, using
`rho = 0.0172 ohm mm²/m` at 20 °C, declared length including slack, and
cross sections thin 0.01, standard 0.5, thick 2.5 mm². The two lesson leads
are each 5 m: thin 8.6 Ω, standard 0.172 Ω, thick 0.0344 Ω. The native
circuit solves their voltage drops and books `I²R` heat. The source retains
its 0.05 Ω internal resistance. Old saved and prepared wires retain 0.01 Ω.
The **low resistance** Sandbox choice exposes that legacy lumped model.

| Supply and leads | Lamp V | Current A | Lamp W | Nudged wins |
|---|---:|---:|---:|---:|
| 12 V, standard | 11.9023019 | 0.247964624 | 2.95134982 | 3/3 |
| 12 V, thin | 8.8275862 | 0.183908046 | 1.62346413 | 0/3 |
| 6 V, standard | 5.9511510 | 0.123982312 | 0.737837455 | 0/3 |
| Missing return | 0 | 0 | 0 | 0/3 |
| 12 V, standard, reversed lamp leads | -11.9023019 | -0.247964624 | 2.95134982 | 3/3 |

These are native, whole-apparatus runs at 1/240 s and 2 cm voxel resolution,
with nominal plus two genuine 1.5 mm loose-body nudges. The apparatus has no
loose bodies to align, so those runs coincide. Signed lamp voltage is computed
from the native node difference; the player meter shows its magnitude. The
bulb remains nonpolar. Native motor polarity already reverses torque; there
is no name-based wrong-polarity failure or fake wire animation deciding a win.

Independent one-second native integration at both 1/240 and 1/480 s delivers
2.95134982 W. At either step, source energy is 2.975575485 J, heat is
2.385305520 J and emitted light 0.590269964 J. Electrical residual is
-2.41e-13 J and KCL residual 2.01e-14 A; thermal residuals are -5.50e-9 J
and -3.53e-8 J respectively. The goal run completes at 0.583 s and draws
1.735752366 J. Its material-derived construction score is 881,440,000 J;
the new lesson uses the earlier fixed-case 882 MJ rounded par. The v2 holder
retains its 375 MJ par. No goal, tolerance or native binary changed.

Limits: cable geometry shows topology and enlarged thickness cues, not exact
length or real coiled slack. Wires have no mechanical mass or tensile model.
Joule heat remains lumped into the supply thermal node, not spatially resolved
copper. Copper resistance is constant with temperature; insulation, ampacity,
filament temperature/resistance, safe household wire sizing and bulb explosions
are unsupported. The existing bulb model splits power into heat and light.
The new-wire analytic oracle is material-neutral. Existing identical-coil
glass/oak/iron heating comparisons and physical-holder regressions remain in
the measured regression set; they are not copper calibration.

Verification: 23 electrical tests (33.72 s), nine holder tests (7.40 s),
and the 51-test game suite pass. The new voltage/thickness browser test and
the preserved holder test pass at 1280×860, 390×844 and 844×390 (16.75 s).
The client view CTest, syntax checks and 269 source registrations pass.
The final meter-layout/battery-control rerun passes the new battery test and
the existing cable-power test (26.28 s). The recipe sweep checks all 88
presets: 264/264 solution nudges, zero empty or wrong wins. That 16-test run
also exposed one presentation assertion: the generic tray adapter added an
unwanted across-position control. Marking this lesson's battery/wires as
non-positionable fixes it; the failed version assertion and legacy v1
cache-loss test then pass together (1.48 s). The entire recipe suite was
not repeated after that metadata fix. The original lamp goal and deadline
are unchanged. Focused tests do not imply the entire repository CI passed.

## Cable power and starting load estimates (October 12)

The new cable/object badges are measurements and static estimates only. They
do not command forces, modify circuits, change goals or add native physics.
Cable pulses indicate activity and conventional-current direction; their
animation speed is not a model of electron motion. They stop for zero current
and while a changed design is awaiting its measured preview.

Ordinary wire watts use the native signed current and upstream node voltage,
explicitly relative to the supply's negative terminal. The native solver may
choose a different voltage gauge, so its reference value is subtracted first.
This is power at a point on the circuit, not the wire's much smaller `I²R`
heat. Return lead labels show current; its near-zero referenced watt value
does not mean that the appliance receives no power. A unit regression compares
identical networks at voltage offsets 0, -12 and +100 V; a 1 A, 12 V feed reads
12 W at each gauge while its heating remains 0.01 W. Native device input power
includes the engine's step/coupling accounting and can differ slightly from an
instantaneous wire `V*I` reading during acceleration.

For a simple grounded motor arm the display calculates gravity torque from
native mass and centre of mass relative to the declared hinge. For a vertical
drum lift it adds `mass * 9.81 * radius`, plus declared bearing friction. At
rest the native DC model's winding power is `torque² * no_load / stall`, using
the declared gear ratio. The label calls this **Start ≈**, not the power for
a timed goal, sustained speed or acceleration. Other shared loads and supply
losses still consume power. Full-command stall torque is a rating at rest,
not a hard torque cap under all speeds or commands. Actual input watts and
actual native motor torque appear on the same object badge.

Complex contacts, compound gear bodies without a drum, coupled ideal gears,
springs, fixed links and constrained drum payloads do not receive an invented
minimum. They display variable demand and the motor's stall rating. Bulbs
display their rated brightness power or the existing level's measured watt
goal; the rating is not an on/off threshold. The measurements travel in the
same bounded preview frames as the wiring and appear during ordinary live
runs, without another simulation or search for a minimum supply.

Same 0.5×0.06×0.12 m offset arm, 0.15 m gravity lever, 0.001 N m bearing
friction, 5 N m stall motor and 6 rad/s no-load speed, at native initial rest:

| Material | Native mass (kg) | Estimated starting torque (N m) | Estimated winding power (W) | Can the 5 N m motor overcome this static load? |
| --- | --- | --- | --- | --- |
| Glass | 9.00000 | 13.244500 | 210.500136 | No; exceeds its stall rating |
| Oak | 2.52000 | 3.709180 | 16.509620 | Yes, if the circuit supplies it |
| Iron | 28.33200 | 41.691538 | 2085.821209 | No; exceeds its stall rating |

All three materials are compared at 1/240 and 1/480 s; estimates are identical
at initial rest, native first-step declarations remain valid, and the display
helper leaves the compiled declaration unchanged. Torque/power comparisons
use 1e-5 N m / 1e-4 W tolerances for native mass/pose serialization. The existing
combined solar/lamp/motor/arm audit remains passing at its four steps: electrical
residual <1e-8 J, thermal residual <1e-6 J, booked electrical/shaft coupling
balance <1e-7 J and whole-arm mechanical remainder <0.01 J. These are the
specific fixture's receipts, not a new conservation claim for arbitrary loads.

Catch the sun's 7.87 kg load and 40 mm drum estimate 3.088188 N m and 14.305358 W
at rest. In a 0.15 s native probe its motor takes 28.780 W and supplies 4.167
N m while accelerating; a correct panel cable carries 50 W. A flat panel
carries roughly 13 W in its preview. The current timed goal still needs the
full native run rather than this starting estimate.

Verification: electrical suite 21 tests in 31.2 s; combined power/mechanics
suite 3 in 9.1 s; full game 51 in 77.2 s. Three focused Chrome checks pass in
46.2 s across 1280×860, 390×844 and 844×390: changing panel orientation updates
the cable watts, live runs animate flow, requirement labels remain visible
inside the scene without covering Run, and the existing solar wiring and
preview scrubbing work. The verified engine is unchanged, SHA-256
`3fac18bff131cf0d819e6186969c4ed64b27210eef04e36f420bd497ce39d24a`.
After the torque line and wiring-control collision bounds were refined, the
new power-feedback test passes all three viewports again. A combined run's
Chain reaction landscape case timed out after Chrome reported
`ERR_NO_BUFFER_SPACE`; its isolated desktop/portrait/landscape rerun passes
in 17.1 s. The resource error is recorded rather than counted as a passing
combined run. Full browser-suite/CI results are not implied by these focused
checks. Source registration (269 sources), JavaScript syntax and the native
machine-view CTest also pass.

## Controls and supported connections

- Battery: 6–24 V, 100–10,000 J capacity, initial charge 0–100%, and a
  10–2,000 W discharge ceiling. Its positive and negative terminals are labelled.
- Switch: a loose manual rocker on a frictional hinge, or a paddle on a real
  hinge with a 2–25 degree travel threshold. Drag the rocker or its labelled
  scene handle to apply force. Its measured angle determines the contact state;
  there is no Toggle command. A paddle cannot also be thrown manually.
  Reset and saved versions restore the declared physical starting pose.
- Bulb: 3 W or 12 W rated at 12 V. Fixed resistance is V²/P; actual voltage
  determines actual I²R consumption. 20% becomes light and 80% becomes lumped
  heat. Brightness and ray emission follow the solved power, including dimming.
- Wire: two explicit terminal references, 0.01 ohm resistance, and no implicit
  junction at a crossing. Moving a device moves its displayed terminal positions
  but keeps identity and connectivity. Routes are visual and do not change
  resistance. Delete or disconnect a terminal and no electrical shortcut remains.
  Click/tap two labelled scene terminals to place one wire, or edit its terminal
  selectors. Prepared, placed and preview wires share thick orthogonal floor
  routes and endpoint pins; yellow indicates measured current. These routes
  have no cable mass, length-dependent loss, collision or mechanical constraint.
  The **Finish the loop** lesson introduces the missing return lead; the
  marble/paddle lesson retains its prepared leads, visible even during placement.
  Wires are electrical graph elements, with no simulated cable mass, sag or
  mechanical attachment; their fixed resistance is a disclosed idealization.
- Power cable: a saved two-conductor charging lead from a solar output to a
  finite battery input. It chooses the existing native panel's charging store;
  no energy is copied or recreated. Each output and receiver accepts one cable.
  Cable loss, mass, sag and parallel charging electronics are not modeled.
  A generic solar panel exposes `<panel>:power`; a graph battery exposes
  `<device>:power`. The original Catch the sun challenge provides `winch:power`.
  Until connected, that challenge's panel charges its own empty 20 kJ local
  store, and its winch battery stays empty. Older sandbox templates retain their
  declared store connection until an explicit cable chooses another receiver.
- Motor: forward/reverse, throttle 0–1 and either the included axle or an
  explicitly selected existing hinge. The preset is 2 N m stall torque and
  8 rad/s no-load speed. The selected hinge's housing takes the reaction torque;
  speed is never prescribed. A rear-mounted housing clears the rotor's sweep.
- Heating coil: attached target, 12 ohm warm or 0.12 ohm hot preset, and two
  terminals. Its calculated Joule heat enters the material's thermal parcel.
  A separate declared 48 V, 100 kJ, 10 kW source powers the high-power cord demo.
  Heating itself never commands a rope to part.

The graph permits parallel and series resistor/bulb loads, switches, wires and
native motor branches. There is one finite battery per connected component,
with one authoritative charge state for all its loads. Interconnecting two
batteries, duplicate identities, missing terminals, missing hinges and invalid
conversion efficiency are refused. A battery already owned by a legacy circuit
cannot also be assigned to a graph. Detached graph islands are unpowered.
Unsupported models include AC, capacitors, inductors, diodes, arbitrary battery
series/parallel combinations, filament temperature-dependent resistance,
electrical arcs and selectable conductor thickness. Both switch types use an
ideal contact with 0.001 ohm closed resistance, controlled by measured hinge
travel. Internal conductive contact geometry and pressure-dependent resistance
are not modeled.

## Physical manual rocker, October 11, 2026

The manual handle is a loose 0.20 × 0.04 × 0.06 m body, default oak, with a
fixed rear support and iron axle. The hinge axis is z, the world travel limits
are ±25 degrees, and hinge friction is 0.08 N m. Open starts at +25 degrees,
closed at −25; the circuit closes at horizontal. Native hinge readings are
relative to the initial pose, so declared limits and the contact threshold
include that offset. No runtime angle or velocity is assigned.

A drag of at least six pixels starts or resumes the whole simulation and
applies a camera-plane force at the grip: 400 N/m of pointer displacement,
capped at 20 N. Releasing, cancelling, pausing or changing scenes requests zero
force; a one-second server lease also expires abandoned input. The server
accepts only the declared loose handle and a nearby grip point. The scene
label reports Open/Closed and measured current. General Pull remains a test
intervention earning zero stars; this validated field control earns ordinary
goal scores, with native external work included once. Run receipts now retain
millijoules instead of rounding subjoule input away.

Old saved manual declarations compile to physical rockers without changing
their saved input, device identities, wires, starting state or handle material.
Fresh switch, bulb and loop recipes use version 2. Version 1 retains its seed
policy and raw declarations, then migrates the manual mechanism at compilation;
its compiled geometry is consequently not frozen. Paddle declarations remain
paddles. Private preflight solutions start closed, while a player can save an
open starting pose and operate it on the field. The switch construction par is
18.7 MJ. The loop par is recalibrated from the former whole-joule receipt of
2 J to 1.75 J, rounding its measured 1.747 J up to three figures. Goals,
deadlines and physics tolerances are unchanged.

`tests/mechanical_switch_tests.py` compares equal geometry in glass, oak and
iron at 1/240 and 1/480 s. At 20 mm resolution the tilted handle voxelizes to
72 cells: masses are 1.44, 0.4032 and 4.53312 kg respectively, rather than the
ideal box-volume mass. An 8 N downward force for 0.25 s closes each; it holds
unforced for two seconds, and 8 N upward for 0.25 s opens each. Native Boolean
switch commands cannot override the hinge controller.

The following independent short, pre-stop 0.025 s audit integrates F·dx at
the grip. Energy units are joules. Hinge friction is estimated from travel;
the residual is full work minus ΔKE, ΔPE and that friction estimate.

| Material | Step s | Full F·dx | Native booked work | Missing release step | ΔKE | ΔPE | Hinge friction | Residual |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Glass | 1/240 | 0.02088152 | 0.01487 | 0.00601153 | 0.01541251 | −0.00000534 | 0.00285644 | 0.00261792 |
| Glass | 1/480 | 0.01937498 | 0.01637 | 0.00300632 | 0.01541671 | −0.00000034 | 0.00265220 | 0.00130641 |
| Oak | 1/240 | 0.07653737 | 0.05413 | 0.02241014 | 0.05643218 | −0.00000292 | 0.01027628 | 0.00983182 |
| Oak | 1/480 | 0.07092189 | 0.05971 | 0.01121032 | 0.05647650 | −0.00000057 | 0.00953925 | 0.00490672 |
| Iron | 1/240 | 0.00658503 | 0.00470 | 0.00188525 | 0.00486134 | −0.00001290 | 0.00090553 | 0.00083106 |
| Iron | 1/480 | 0.00611149 | 0.00517 | 0.00094277 | 0.00486191 | −0.00000079 | 0.00084085 | 0.00040953 |

An existing native Pull bookkeeping gap can omit the final preceding step's
work on a force update or release. Adding that independently measured step
reconciles booked work with integrated F·dx within 5.1×10⁻⁶ J; this does not fix
the runtime receipt. Remaining damping/integration residuals decrease with
timestep, but stop losses and support reaction work have not been closed
independently. These tests are not a full coupled conservation proof. The
mechanism has no snap detent, elastic contact bounce, arcing or filament model.

## Physical battery holder, October 11, 2026

`scripts/sandbox_battery_socket.py` declares a loose pack and an anchored two-pad holder. The pack comprises a 200×80×100 mm housing, two 40×40×80 mm glass insulating spacers and two same-sized iron caps; four ordinary fix joints hold them together. Housing material changes actual mass, rather than changing a display label. The concrete holder base is 400×80×280 mm, with two separately collidable 60×40×100 mm iron pads at x ±80 mm. At release the housing centre is 0.4 m high; the cap bottoms are 0.28 m high and pads top out at 0.12 m. Pack rotation rotates the bodies, fix points and terminals together.

The graph declares four possible cap-to-pad paths, each a 0.001 Ω native `follows_contact` switch. Native shape touching with the existing 1 mm contact-query margin closes each path; the 20 mm broadphase proximity test does not energize the lamp. Both terminals are bound to their separate cap bodies and both holder terminals to their pads. Declared contact bodies must be iron or aluminium and carry the graph terminals. The holder has no branch shorting its poles. Reversed packs use the crossed paths and reverse lamp current; I²R power remains positive. The solver still uses the original 12 V, 1,000 J store, 200 W ceiling, 0.05 Ω source resistance and two 0.01 Ω floor leads. The lamp is a 48 Ω load with 20% optical efficiency. Steady native power is 2.99102021 W.

`tests/battery_socket_tests.py`, registered as `banjo_battery_socket_tests`, passes nine native-backed regressions: zero/one/two contacts, off-holder and crosswise controls, housing-only contact, depleted charge, reversed polarity, detached cap, actual 200 N pull-out, sleeping bodies, native snapshots and three nudges per material. The canonical solution wins three nudges at 0.933 s; empty and misplaced controls win zero of three. The goal is unchanged at ≥2 W for 0.5 s within four seconds. The comparative pack goals are 0.817 s for glass and 0.933 s for oak/iron.

Windows Release engine SHA-256 `807ae9c34f0516a0d0dbf588400451b865083043d614cd1aab8040140c830f87`, 20 mm game cells, identical geometry and source, simulated for two seconds at 1/240 and 1/480 s:

| Housing | Pack mass kg | Source energy J, dt240 / dt480 | Heat J, dt240 / dt480 | Light J, dt240 / dt480 | Rigid Δ(KE+PE) J, dt240 / dt480 |
|---|---:|---:|---:|---:|---:|
| Glass | 6.65472 | 5.354468 / 5.441837 | 4.285179 / 4.355100 | 1.069290 / 1.086737 | −10.509944 / −10.461993 |
| Oak | 3.77472 | 5.029955 / 5.061158 | 4.025471 / 4.050443 | 1.004484 / 1.010716 | −5.925891 / −5.925114 |
| Iron | 15.24672 | 5.379431 / 5.129805 | 4.305156 / 4.105381 | 1.074275 / 1.024424 | −23.981266 / −23.889497 |

All six electrical residuals (source − heat − light) are below 2×10⁻¹¹ J, against this regression’s fixed 10⁻⁸ J tolerance; the existing native solver checks use their scale-dependent tolerance. Thermal residual magnitude is below 10⁻⁷ J. Charge debit equals measured source energy; heat storage and ambient loss are tracked separately. The timestep-dependent contact settling time changes total energized duration, especially for iron; steady electrical power agrees at both steps, but these totals are not a convergence proof. A 200 N pull lifts the iron pack away, with measured external pull work 84.405 J, opening both contacts and stopping the lamp.

Rigid Δ(KE+PE) is a measured change, **not a conservation residual**. Ground/holder reactions, contact dissipation and numerical correction have not been reconciled into an independent full drop-and-support energy or momentum closure. The contact rule is a binary geometric idealization with fixed resistance, not a pressure-dependent or calibrated connector law. Oxidation, arcing, capacitance, elastic contact bounce waveforms, battery chemistry/voltage sag and temperature-dependent filament resistance remain unsupported. Contact/wire heat is lumped into the supply thermal node, not a cap temperature model. No fracture, wood grain, plasticity or new native contact law is claimed.

## Earlier circuit verification

Native: `tests/circuit_tests.cpp`, built as `banjo_circuit_tests`. Python:
`tests/sandbox_electrics_tests.py`, registered in CMake. Windows Release,
CPU precise floating-point model, 2 cm game cells, fixed 1/240 s game step.
The native electrical point-network oracles use their explicitly stated steps
and do not depend on material labels.

A closed 12 V loop gives a 3 W bulb over 2.9 W. Opening its switch, omitting
its return, or exhausting the battery gives no light. Two series bulbs each
draw under 0.8 W. Two parallel bulbs under a shared 3 W supply limit receive
equal power. Across 1.9833 s that supply gives 5.950 J: 5.355 J heat and 0.595 J
emitted light, electrical residual −8.8e−13 J and thermal residual 2.2e−8 J.
The thermal solve tracks storage and heat lost to ambient separately. The ray
tracer receives exactly the bulb branch's emitted watts and independently
balances absorbed, escaped, ground, scattered and unfollowed power. Its heat
is therefore not a second electrical draw.

Power-cable regressions preserve saved endpoint names, compile a cable declared
before its source panel, reject reversed/missing endpoints and duplicate or
parallel charging sources, and exercise empty and full receiving stores. In a
full battery the accepted panel energy stays zero and excess converted energy
is reported as spilled. Panel `collected_j` is cumulative accepted solar energy;
`charged_j` is the receiving store's current balance, including initial charge
and motor withdrawals. The panel audit is
`sunlight_j = collected_j + spilled_j + heat_j`, within 0.003 J in the Python
readout regression; store `taken_j` matches accepted input within 0.001 J.
Public current charge is rounded to 0.1 J and is tested at that display precision.

The original sun goal, time limit and energy par are unchanged. Its panel plus
explicit cable wins at 2.400, 2.450 and 2.383 s in the three nudged runs. A facing
but disconnected panel stores about 397.5 J locally after the last sampled
8-second run state and gives the winch zero joules. Connected flat and shaded
controls still fail. Before Run, meters report geometry and available sunlight
(250 W for the aligned clear panel), while stored/taken/collected joules remain
zero. A ray hit and shadow distance are exposed for the shaded control. Solar
occlusion remains one center ray: partial-area shadowing is unsupported.

Native checks preserve battery/circuit/lamp state through an unchanged-world
snapshot, reject two owners of one supply, and exercise finite final joules,
stalls and runtime switching. The native full motor pipeline includes housing
reaction and rigid kinetic energy. At 120/240/480 Hz its whole-system residuals
are −0.1198/−0.05987/−0.02996 J and decrease with timestep. The circuit reports
the difference between predicted electrical shaft energy and accepted rigid
shaft work explicitly; these are numerical coupling residuals, not hidden heat.
An edited-scene carry of live circuit state remains unsupported. Missing source
housing disables its supply and a missing bulb housing opens that branch.

For identical 0.04 × 0.30 × 0.04 m boxes, one 12 V supply, 12 ohm coil and
2 s integration, exported coil energy is the same across glass, oak and iron.
The game rehearsal's last sampled export is 23.524744 J for each; native
temperatures at exactly 2 s are:

| Material | Surface K | Core K |
|---|---:|---:|
| Glass | 293.173516 | 293.173516 |
| Oak | 293.274349 | 293.150410 |
| Iron | 293.163980 | 293.163980 |

These compare low-power heating, not claims of equivalent combustion or
grain/plasticity. The oak cord demo uses the existing experimental material
burning and temperature-dependent joint capacity. It parts at 9.183 s under
the declared hot source, while the warm-coil control fails. The 12 V low-power
version warms the cord without releasing it and is not represented as ignition.

Five prebuilt designs show the manual loop, shared bulbs, marble-triggered
light, motor axle and burning cord. Seven easy challenges teach battery charge,
manual state, bulb placement, finishing the return, motor direction, coil power
and paddle placement. Every authored solution passes nominal plus two runs
with loose bodies nudged up to 1.5 mm. Reverse motor, misplaced paddle, open
switch, wrong return, empty supply and warm heater physically fail their goals.
The bulb challenge's omission control is no bulb; changing position in an ideal
explicit wire graph does not falsely disconnect it.

Energy pars come from `machine_game.measure_energy`, including embodied piece
energy and actual `given_j`. Solar charging's `taken_j` is reported separately;
net charge loss cannot substitute for consumption while the sun is charging.
The measured nominal motor reaches its 20 degree goal at 0.700 s; its nudged
runs reach it at 0.817 and 0.583 s. The goal and 1 s deadline stayed unchanged.


## Current-driven display and paddle metal contact — October 12

This checkpoint uses the unchanged native engine
`1ebc084656f9b4c0206e6c7ca7f9d0e12546700c60e495781ca781493587c352`.
No native solver, contact tolerance, goal or energy-par tolerance was changed.

A current paddle has a 0.38×0.04×0.12 m iron plate and its original hinge,
limits and friction. A separate material-derived iron compound leaf consists
of a 0.32×0.02×0.06 m bar and 0.02×0.02×0.067 m mounting stem, beside the
paddle at z=0.16 m. A native fixed joint mounts it to the paddle. The ideal
mount has a 3 mm modeled clearance rather than overlapping collision bodies;
it is not a resolved welded seam or a stress-calibrated elastic leaf. An iron
0.04×0.02×0.06 m output pad has a concrete support. Paddle travel positions
that pad geometrically; it no longer switches the branch at a named angle.
The leaf/pad branch uses the existing native body-touch observation (1 mm)
and 0.001 ohm lumped closed resistance. Broken/missing conductors do not touch.
The source and output terminals must bind to the declared conducting bodies;
glass and oak conductors are refused, while iron/aluminum are admitted.

The reference marble drops at x=0.12 m from y=0.55 m, on the same 12 V,
1000 J source and 3 W resistive lamp with a full three-lead circuit. The
unchanged goal is at least 2 W for 0.1 s within 3 s. All three reference nudges
win at 0.933 s. Embodied-plus-run energy is 457786660.911 J, under the unchanged
462000000 J par and within the existing one-percent par calibration check.
The slimmer plate makes room for separate hardware in that budget; no impulse,
forced angle, current, emissive power or goal event is assigned by the lesson.
An outlet pad displaced by 20 cm, missing return and flat source all fail.
Every sampled open-contact state has zero wire current within 1e-10 A, as do
incomplete/exhausted circuits. The native electrical-ledger limit remains 1e-8 J.

Equal geometry/source/drop conditions compare only the paddle's bulk material;
the leaf and output pad remain iron, separate from that material. Integration
covers 3 s, observed every 0.05 s, with 20 mm lattice solids and an exact rigid
compound leaf. Counts describe sampled contact closures, not a calibrated
contact-bounce frequency or proof of sustained closure for every material.

| Paddle material | Closed/open samples at 1/240 s | Closed/open samples at 1/480 s | Final electrical residual J, 1/240 / 1/480 s |
| --- | ---: | ---: | ---: |
| Glass | 0 / 60 | 0 / 60 | 0 / 0 |
| Oak | 8 / 52 | 9 / 51 | −8.369e−13 / −9.239e−13 |
| Iron | 12 / 48 | 43 / 17 | −1.185e−12 / −4.201e−12 |

Glass does not close in these probes; oak is intermittent, and the iron lesson
passes its native goal. The difference between iron closure counts at the two
steps remains a contact-resolution sensitivity. These circuits conserve their
own electrical energy within the stated test bound; the tests do not establish
a closed whole-system rigid/contact/heat momentum or energy audit. Fixed-support
reactions, hinge/contact losses and ideal mounting work remain unseparated.
The new contact resistance is not derived from material resistivity, pressure,
microscopic contact area or oxidation. Arcing, elastic switch bounce, a snap
detent, electron transport and realistic filament failure remain unsupported.
Manual rockers retain the prior measured hinge threshold; a trial contact
retrofit did not pass their nudged tests and was removed from this checkpoint.

Wire yellow highlights and flow dots require |I| > 0.0001 A. The legacy
schematic no longer equates a closed switch with current. Insulation stays
polarity-colored at zero current; arrows show conventional current, not an
electron speed. Electrical rehearsals start paused at their initial state.
Explicit Play preview/scrubbing carries the native paddle/leaf poses with its
sampled current. Run switches to live readings and Reset restores zero-current
initial state. Readings and wiring offers a 44 px Inspect contacts control,
verified to frame both conducting terminal points in all three viewports.
The completed-run card moves beside the scene on inspection, rather than
covering the metal connection.

Current v2 recipes test 0.48/0.51/0.58/0.59 m drops. Each passes correct/empty/
wrong preflight, including three nudges. The previous 0.62 m drop lost sustained
contact in one nudge, so it is outside the new version's offered domain.
Version-1 recipes preserve their original hinge apparatus, 0.48/0.51/0.59/0.62 m
policy and identities, including a separately verified old recipe.

Verification: 28/28 electrical tests in 39.214 s; 53/53 game tests in 89.624 s;
three browser regressions in 24.000 s cover live current, initial paused
rehearsal, explicit playback/scrubbing, reset and manual drag. The final
inspection/current browser regression passes all desktop, phone portrait and
landscape cases separately in 7.287 s. The current/retained recipe test passes in 6.083 s.

The inspection-card follow-up changes only UI placement. Its same complete
current/contact/reset/touch test passes in 7.386 s across all three viewports;
the native measurements above remain unchanged. Source registration is 269/269.

## Native RC components and advanced activities (October 12)

The standalone Resistor and nonpolar Capacitor cards use native Circuit,
including explicit series resistance and a separate leakage resistor. They have
A/B terminals; wiring determines series/parallel topology. Component ratings
are independent of housing geometry/material. Glass/oak/iron housings are
anchored, with native material-derived mass; the lumped thermal capacities are
declared component parameters, not a bulk-material heat model. No spatial
dielectric field, breakdown, electrolytic damage, arcing or magnetic flux is
implemented. A fresh/reset capacitor starts uncharged; snapshots preserve its
signed voltage/charge. The compiler retains a single battery per declared graph.
The graph includes open switches, so opening the supply leaves capacitor/load
islands available to the solver; an entirely battery-free declaration is not
yet compiled into a runtime circuit.

For each accepted timestep, backward Euler solves
`I = (V_A - V_B - V_C_old)/(R_ESR + dt/C)`, then
`V_C_new = V_C_old + dt*I/C`. Physical ESR heat is `I² R_ESR dt`.
The storage delta is `½ C (V_C_new² - V_C_old²)`. The numerical loss
`½ C (V_C_new - V_C_old)²` has its own ledger and never heats a body.
Source work balances heat, light, shaft work, storage delta and numerical loss,
with unchanged electrical tolerance `1e-8` times the step energy scale.
The KCL tolerance remains `1e-8*(1+abs(source_current))` amperes. There is one
voltage reference per conducting island, without an artificial ground leak.
Trial solves do not commit charge or thermal/fuse state.

Material-neutral analytic test: a 12 V source with 1 Ω internal resistance,
9 Ω feed, 0.1 Ω ESR and 0.1 F capacitor has τ=1.01 s. At 1 s:

| dt (s) | Native voltage (V) | Error vs exponential (V) | Numerical loss (J) |
| --- | --- | --- | --- |
| 0.0100 | 7.51976 | 0.0217629 | 0.0305240 |
| 0.0050 | 7.53062 | 0.0109040 | 0.0153117 |
| 0.0025 | 7.53606 | 0.0054576 | 0.00766831 |

Electrical residuals are below 4e-14 J. Isolated storage retains voltage;
discharge through 10 Ω matches its exponential within 0.015 V. Equal capacitors
share approximately 6 V in series and receive approximately 12 V in parallel;
charge equality is within 1e-9 C. A native LiveWorld save/resume preserves the
complete circuit state and identical continuation. Existing DC/motor/contact
tests continue to pass; their coupled mechanical residuals remain reported
above and are not proof of full-pipeline conservation for arbitrary machines.

Same anchored apparatus with glass, oak and iron resistor/capacitor housings:
12 V finite 8 J supply, manual closed switch, 12 Ω charging resistor, 0.1 F
capacitor with 0.1 Ω ESR/1 MΩ leakage, 12 V/3 W lamp. At 7.95 s each records
0.09719398 J stored and −0.02897543 A capacitor current after source exhaustion.
Each consumes exactly 8 J: 7.49741150 J heat, 0.39627997 J emitted light,
0.09719398 J remaining storage and 0.00911454 J numerical loss. Electrical
residual is −2.60e-12 J; thermal residual is 6.63e-8 J. Electrical ratings are
identical across housings, intentionally; this does not claim microscopic
glass/oak/iron conduction or temperature calibration. The native default step
for this anchored scene is 1/240 s, with 20 mm body cells.

Three advanced activities pass their correct/empty/wrong checks. Correct and
wrong controls each receive nominal and two nudged runs:

| Activity | Correct result | Physical wrong control | Measured author energy / initial par |
| --- | --- | --- | --- |
| Limit the voltage drop | 3/3, goal at 0.583 s | 48 Ω series resistor, 0/3 | 172800001.613 J / 173000000 J |
| Series or parallel? | 3/3, both lamps at goal at 0.583 s | Series lamp chain, 0/3; a single powered lamp also fails | 3.491 J / 3.5 J |
| Store the charge | 3/3, 4 J goal at 1.867 s | 0.005 F stores at most 0.36 J at 12 V, 0/3 | 226800011.282 J / 227000000 J |

These pars are initial native calibrations for new levels; previous goals,
pars and tolerances are unchanged. The compact scene readings show volts,
current and stored joules without inventing flow. **Charge and release** and
**Series and parallel bench** are editable Sandbox examples.

Verification: 53/53 game tests in 88.026 s; 31/31 electrical tests in 42.717 s;
native circuit CTest passes in 0.34 s (0.38 s including runner). Source
registration is 269/269. Three browser tests pass in 21.453 s: charge/current
meters, reset, unobstructed labels, both-load wiring goals across desktop,
phone portrait and landscape, plus library availability and saving/reloading
component ratings/wires. The published revision is reported with the checkpoint.
See [the complete catalogue](electronics-expansion.md).

## Solar shade while moving a panel (October 12)

The old meter and dashed sunlight sample read only the live world's panel,
even while the displayed ghost had moved elsewhere. This could leave an
**In shadow** label and old obstruction ray on an unshaded proposed position.
The visual key light's direction already matched the engine's sun.

Proposed geometry now receives a separate native ready-state sample through
`level_sunlight`, debounced by 140 ms and sharing the bounded optical preview
lane. It builds a paused world, returns its native panels/stores and closes
it without stepping. New edits invalidate old observations immediately;
late replies cannot restore old shade data. Preview labels, the setup feedback,
the sample-origin dot and obstruction line all use that same accepted result.
Set down restores live readings. An unavailable preview asks for Set down
rather than displaying the old shade as current. No source, material,
collision, radiation or battery law changed; no goals/pars were relaxed.

Both wall levels compare shaded and unshaded author setups: 0 W or 250 W
incident sunlight respectively, zero elapsed simulation time, zero sunlight
energy, and zero battery draw/charging. Proposed placement declarations remain
unchanged. Both use the existing center ray; partial-panel shade and area
integration are still unsupported. The raised collecting face and the ground
can have different shade boundaries. The small dot identifies the center used
by this model rather than asserting that every cell receives identical light.

Native JSON vectors round components to 1e-5 (metres for position, dimensionless
for direction); the distance is unrounded. Reconstructing the reported hit
therefore has an analytically derived per-coordinate transport bound of
`5e-6*(2+distance_m)` metres. An initial new test incorrectly required five
decimal places without accounting for direction rounding; its assertion now
uses this bound. Existing physical tolerances remain unchanged.

Browser tests independently intersect the rendered wall meshes along the key
light direction. Their hit positions match native hits within 0.1 mm, and sun
directions within 1e-5, on both levels at 1280×860, 390×844 and 844×390. A delayed
sample verifies that moving out of shade clears the old label and guide before
the reply; the new preview reports 250 W while the actual live world remains
shaded and paused. Wiring, authored wins and saved cable/version workflows
retain their behavior.

Checks: 32/32 electrical tests in 47.765 s, 53/53 game tests in 95.423 s, and
four solar browser checks in 58.654 s. Source registration is 269/269.
The immediate-edit follow-up also checks the setup caption clears its old shade
message before the delayed reply; the six desktop/phone scenarios pass in
19.770 s with unchanged assertions for the live world and rendered geometry.
This observation/UI change reuses verified engine SHA-256
`acb79f1926052467cd1dad869ddd3b31cd503c54f0f77c641e99e270c0da8dfc`.
