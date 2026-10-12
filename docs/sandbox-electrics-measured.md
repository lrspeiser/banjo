# Sandbox electrical pieces and measured circuits

October 11, 2026. `scripts/sandbox_electrics.py` defines placeable batteries,
manual or hinged paddle switches, bulbs, wires, motor mounts and attached
heating coils, plus explicit solar power leads. Their terminal graph compiles to `machines::Circuit`; positions
and names do not substitute for a circuit solve. Existing solar panels charge
the same declared battery store used by the graph.

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
