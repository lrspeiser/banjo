# Sandbox electrical pieces and measured circuits

October 11, 2026. `scripts/sandbox_electrics.py` defines placeable batteries,
manual or hinged paddle switches, bulbs, wires, motor mounts and attached
heating coils. Their terminal graph compiles to `machines::Circuit`; positions
and names do not substitute for a circuit solve. Existing solar panels charge
the same declared battery store used by the graph.

## Controls and supported connections

- Battery: 6–24 V, 100–10,000 J capacity, initial charge 0–100%, and a
  10–2,000 W discharge ceiling. Its positive and negative terminals are labelled.
- Switch: manual initial open/closed state, or a paddle on a real hinge with
  a 2–25 degree travel threshold. A paddle cannot also be thrown manually.
  Runtime manual operations enter the simulation's queue between accepted
  steps. Reset and saved versions replay the declared initial state.
- Bulb: 3 W or 12 W rated at 12 V. Fixed resistance is V²/P; actual voltage
  determines actual I²R consumption. 20% becomes light and 80% becomes lumped
  heat. Brightness and ray emission follow the solved power, including dimming.
- Wire: two explicit terminal references, 0.01 ohm resistance, and no implicit
  junction at a crossing. Moving a device moves its displayed terminal positions
  but keeps identity and connectivity. Routes are visual and do not change
  resistance. Delete or disconnect a terminal and no electrical shortcut remains.
  Wires are electrical graph elements, with no simulated cable mass, sag or
  mechanical attachment; their fixed resistance is a disclosed idealization.
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
electrical arcs and selectable conductor thickness. A manual switch is an ideal
contact with 0.001 ohm closed resistance; its decorative handle is not a force
sensor. The paddle follows measured hinge travel rather than an invented load.

## Verification

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
