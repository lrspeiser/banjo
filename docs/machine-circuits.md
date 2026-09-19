# Executable machine networks, first checkpoint

The current [API/MCP reference](api/machine-networks.md) documents all circuit
calls, product installation, runner commands and unchanged-world restart. Both
MCP servers now expose the network at version 1.2.0 (native ABI remains 25).

Initial base: main `1b27e67`, September 19, 2026, immediately after `434ff2b`.
Integrated concurrent main through `4e00a52` before publishing; its source
change to `TileImpactScene.hpp` is commentary, alongside product/root-body and
fracture-result UI fixes. No concurrent work was replaced.
The weak-joint factors remain inactive. This is a bounded DC/thermal and live
mechanical integration checkpoint, not qualification of the full engine or all
fifteen machine capabilities. See [the remaining program](machine-network-roadmap.md).

## Construction, operation and inspection

`ProductGraph` retains construction and geometry. A graph's `energy` list can
contain `{"kind":"circuit","network":{...}}`. `product_circuit.compile_circuits`
compiles its named electrical interfaces and ideal junction relationships into
a `banjo.circuit.v1` network in `PhysicsContract.operating_model.circuits`.
Every branch and thermal node names its source component. Explicit physical
wires are resistive branches; a junction is a shared node, not a wire model.
Mixed/missing electrical terminals are errors. Connected declarations cannot
be split between independent circuit solves.

`product_circuit.install_circuit(world, contract, id, stores=..., motors=...)`
binds construction component ids to already installed native store/motor ids.
Geometry, exposed moving parts, contacts and hinges remain in `LiveWorld`.
The native operating model stores electrical switching/fuse history and
component temperatures. `world.circuits()` is a read-only inspection of those
same states. `World(..., snapshot=...)` resumes them, rather than reinstalling
construction defaults. Automatic Workshop controls for creating/editing these
networks remain future UI work; the compiler, native API and Python path run now.

ABI 25 adds `banjo_make_circuit`, `banjo_circuit_switch`, `banjo_circuits` and
Python `World.circuit`, `circuit_switch`, `circuits`. Existing direct-store
machines retain their old model until explicitly attached to a circuit. One
circuit owns each store and includes **all** motors spending it; duplicate
attachment and later direct-store additions are refused. Full unchanged-world
restore is supported. Edited-scene carry of a circuit snapshot is explicitly
refused until component/state remapping is implemented, so it cannot silently
refill, cool, repair or erase the machine.

An executable product example and its complete native integration journey are
in `tests/product_circuit_tests.py`. C++ analytical and live tests are in
`tests/circuit_tests.cpp`. Both are registered with CMake/CTest.
`examples/authoring/circuit_drive.py` and `circuit_product.json` are a runnable
construction-to-world example. Set `BANJO_LIBRARY` to the built ABI 25 library.
Use `--open-at-s 1`, `--locked --charge-j 1`, or
`--locked --fuse-a2-s 0.2` for disconnect, stalled exhaustion or fuse overload.
The script emits observations as CSV and the actual resumable world snapshot.

## Laws, units and signs

Electrical nodes carry volts. Branch current is positive from `a` to `b`.
The DC nodal solve enforces Kirchhoff current balance at every node and
`I = (Va - Vb - emf) / R` on each conducting branch. Disconnected islands get
one arbitrary voltage reference each; there is no artificial leakage path.
Supported branches are wire, resistor, switch, fuse and motor. Non-motor
resistance is declared in ohms; an authoring caller may derive it from
resistivity times length divided by cross-section. This checkpoint does not
infer resistivity from a material's display name. Positive temperature
coefficients use `R(T) = Rref * (1 + alpha * (T - Tref))`; an invalid negative
resistance domain is rejected.

A supply uses its existing store's open-circuit voltage and finite joules,
plus an explicit internal resistance and thermal destination. It changes from
constant voltage to a current limit when `Vopen * I` would exceed the shared
power/remaining-energy budget. The power rating is at the **stored-energy**
boundary, including source/regulator losses. Those losses heat its declared
thermal node. Reverse charging is blocked in this milestone. A back-driven
motor can transfer energy to connected resistive loads; it cannot recharge
the source. Rechargeable storage and converters need separate declared laws.

Existing motor stall torque and no-load speed at the store's voltage derive
`k = V / omega_no_load` and `R = V^2 / (tau_stall * omega_no_load)`.
For command `u`, an ideal averaged bidirectional driver obeys
`Vwinding = u * Vterminal`, `Iterminal = u * Iwinding`. Zero command disconnects
the winding. It consumes no fictional control power. A positive ideal gearbox
ratio `g = omega_motor / omega_output` gives `k_output = g*k`, so speed falls
and torque rises without changing power. Gear tooth contact, backlash,
compliance and a separate gearbox inertia are not simulated. Existing hinge
friction/brake work becomes heat at the branch's thermal destination.

Motor torque `g*k*Iwinding` is applied to the output body and its opposite to
the housing, inside the mechanical trial. Neither shaft speed nor world
motion is assigned. World contacts/limits decide what moves. This is an
explicit electrical-to-mechanical time coupling: the circuit uses the speed
at the beginning of the step. The difference between actual shaft work and
the electrical back-emf work is reported as `coupling_residual_j`, never
hidden as heat or battery shortfall. It must be checked under step refinement.
The live host rejects steps above 1/60 s, one tenth of the estimated relative
shaft electrical-damping time constant, or 0.5 rad of initial-speed rotation,
whichever is smallest. It checks before mutating the world. This stability
screen is not an accuracy proof for arbitrary contacts or nonlinear loads.
Angles use the existing hinge's short-way
reading, requiring less than half a revolution per accepted step.

Thermal nodes retain kelvin and positive capacity in J/K; links carry W/K.
Backward Euler solves the thermal network, including specified conductance
to a prescribed ambient reservoir. Winding heat can raise resistance or open
a declared overtemperature failure. `fuse_a2_s` integrates squared branch
current; at the threshold it fails permanently. Failure events are resolved
at accepted step boundaries (up to one step of excess exposure). They are
not calibrated manufacturer time/current curves. Damage persists on cooling,
inspection, switching and restart.

## Accounting and bounds

The electrical ledger separately records source energy, heat and converted
shaft work. The thermal ledger measures change in `sum(C*T)` plus heat to
ambient minus deposited heat. Mechanical friction is a shaft-to-thermal
transfer. The mechanical-coupling residual uses actual measured turn. Thus
electrical ledger closure alone does not prove whole-world conservation.
Mount torque reaches the mechanical world, whose contact and constraint
numerical errors are not relabelled electrical losses.

Networks are bounded to 128 electrical nodes, 256 branches, 128 thermal nodes,
256 thermal links and 32 circuits per world. The initial dense nodal reference
has cubic solve cost, appropriate for these small networks, not a whole power
grid. Each circuit has one supply; multiple machines can share it. Multiple
interconnected supplies, RLC transients, diode models and general electronics
remain unsupported. Thermal nodes currently exchange with their own declared
network and prescribed ambient, not arbitrary existing `ThermoWorld` parcels
or a finite room atmosphere. No new material calibration is claimed.

Circuit solving is read-only until the mechanical step is accepted. Battery,
heat, fuse history and damage commit once. A refused mechanical trial does
not spend them. The declarative model and mutable snapshot use the same
versioned schema; only restore reads saved damage/history.

The connector separation follows the potential/flow distinction in the
[Modelica connector specification](https://specification.modelica.org/maint/3.6/connectors-and-connections.html).
Temperature-dependent resistors and loss destinations follow the standard
[resistor model pattern](https://doc.modelica.org/Modelica%204.0.0/Resources/helpWSM/Modelica/Modelica.Electrical.Analog.Basic.Resistor.html).
These are reference patterns, not a claim that Banjo implements Modelica.

## Measured checkpoint

Windows x64, MSVC 19.44.35228, Release, Jolt v5.6.0, double-precision positions,
`banjo-cpu-precise-v1`; fresh build from the base above plus this checkpoint.
Native circuit tests include parallel loads, shared current/power allocation,
branch-order invariance, floating/open islands, exhausted stores, backdrive
powering another load without battery charging, temperature-dependent
resistance, fuse/overtemperature damage, rejected declarations/steps, cooling,
full restart, free-housing reaction and a matched step-refinement sweep.
The tests take about 0.40 s on this machine; this is suite timing, not a
world-scale performance qualification.

One second of an anchored housing, iron inertial flywheel, 2:1 ideal gear and
50 W store limit gives the following **analytical inertial experiment**, not
a material calibration. Resistances/capacities are demonstration declarations.

| Step | Store energy J | Electrical heat J | Final kinetic energy J | Store - heat - kinetic J | Coupling residual J |
|---|---:|---:|---:|---:|---:|
| 1/120 s | 49.072398 | 34.849147 | 14.3430 | -0.119786 | 0.239571 |
| 1/240 s | 49.054139 | 34.781624 | 14.3324 | -0.059869 | 0.119706 |
| 1/480 s | 49.045037 | 34.747884 | 14.3271 | -0.029958 | 0.059843 |

Electrical residual is bounded at 1e-8 relative to transferred energy,
junction residual at 1e-8 relative to source current, and thermal analytical
checks at 1e-8 J or tighter. The independent whole-loop residual approximately
halves with timestep and is about 0.12% of store consumption at 1/240 s. It is
numerical energy creation, explicitly measured; it is **not** a physical loss
or exact conservation claim. Midpoint/implicit mechanical-network coupling is
the next accuracy improvement. Existing motor and controller behavior retains
its previous tests and tolerances.

Verification scope: the five focused CTest suites (circuit, product circuit,
motor, machine control, joint binding) pass. The separate three existing
`MachinesFromPython` FFI cases pass; product contract, refinement and mating
regressions also pass. Source registration and the floating-point build audit
pass. The broad `banjo_ffi_tests` run was deliberately stopped after 524.87 s
while running its existing `test_a_hard_enough_hit_breaks_it_and_says_how_many_pieces`;
it had passed the preceding save/restore and asynchronous-fracture cases, with
no assertion result for the active case. CTest therefore reports that canceled
suite as failed. It is **not** counted as a pass or a full-engine qualification.
The outgoing checkpoint is scoped to the passing machine/network checks;
the long fracture suite remains an uncompleted verification item. No browser,
interactive-window, cross-platform or GPU qualification is claimed here.
