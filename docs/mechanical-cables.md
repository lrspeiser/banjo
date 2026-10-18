# Physical electrical leads — October 16, 2026

October 18 wall construction adds an opt-in XY service-coil layout. It changes
only the initially manufactured path, retaining stock length, native mass,
resistance, self/contact constraints and pull-out. Ordinary 3D stock keeps its
XZ construction layout. The wall motor's two 2 m leads sag and stay connected
over the 2 s native regression; the missing return leaves its motor stopped.

## Delivered scope

All explicit electrical graph wires, solar charging cords and the old
supply/contact/heater circuit leads now build native articulated cables. This
covers motors, bulbs, batteries, switches, resistors, capacitors and ignition
clips in levels and Sandbox. It also includes unpowered islands and incorrect
connections: a wire has mass even when its circuit is open.

This does **not** replace ties, pulley/drum ropes or implicit/internal connections.
The separate low-power optical sources and the laser still draw directly from
their declared store without an external feeder. Motor interiors retain the
lumped torque/back-EMF model. These are explicit remaining model gaps.

The authoring compiler calculates a conservative clear construction path and
adds manufactured slack. Its arc length sets copper resistance, using
0.0172 ohm mm²/m and the declared area. Runtime motion never recalculates this
route. Native gravity/contact must move the wire around an obstruction. The
3D renderer uses the returned rod endpoints and the actual collision radius,
including in predicted flow frames. It does not smooth a line through solids.

## Mechanical model and units

### Setup gravity

Placed live wired setups advance Jolt's cable world at 1/240 s in eight-step
batches (30 Hz), even while the puzzle's time is zero. Existing machinery is
held by temporary native fixed constraints to the world. This is an editor
fixture boundary condition: gravity reactions can go into the fixed supports;
it is not a closed free-machine conservation experiment. On entering setup,
the machinery's declared velocity is stored and held at zero. On starting,
fixtures are removed and the machinery's declared initial state is restored
once, including any chosen initial spin. No cable pose or velocity is reset.
Finite solver fixture drift is therefore corrected at the setup/run boundary;
its work is not reported as puzzle energy or as material heat. No per-step
assigned sag or cable velocity is used.

Puzzle clocks, circuits, motors, water and material evolution do not advance
in this phase. Thus waiting on the setup cannot drain a battery or fire an
igniter. The renderer shows the native rods over prediction drawings. Try It!
reuses an unchanged, ready setup session, so cables do not spring back to the
manufactured route. Editing/undo/reset still rebuilds a setup and its cords
settle again. Ordinary pause after a run freezes the entire simulation.
Unpaced rehearsals take only their explicit steps. An unwatched setup stops
spending CPU after five seconds without frame requests, and resumes on return.

Historical motor checkpoint 0160b77, measured on Turn the axle: after one second of setup, the two leads reached
minimum heights 2.82 mm / 6.30 mm; both connectors remained attached (peak
loads 4.06–7.27 N). The first running step moved any sampled cable endpoint
by at most 1.60 mm, rather than reconstructing the elevated construction path.
The native snapshot's puzzle time, step count and circuit state were unchanged
by those 240 setup steps. Live-session regression also checks continued setup
updates and unchanged rendered machine poses before play. Browser regression
uses Place then Try It! on desktop and phone portrait/landscape, checks visible
moving native leads at puzzle time zero and verifies the same session wins.

`MechanicalCable` builds rods in the same Jolt world as the machinery. Jolt is
the single owner of their rigid contacts and connector response. Each rod has
a capsule collision envelope and material-derived mass:

`mass/length = conductor_area * conductor_density + insulation_area * insulation_density`.

The default is 2.5 mm² conductor, 3 mm outer radius, 8960 kg/m³ conductor and
1200 kg/m³ insulation. Density values are explicit model parameters, not a
calibrated commercial cable specification. Rod inertia homogenizes that mass
over the cylindrical section; overlapping collision caps add no extra mass.
Only the immediate material neighbourhood (including overlapping capsule caps
on tiny construction legs) and each terminal's embedded rod exclude their
own overlapping contact envelopes. Other rods, other wires and obstacles retain
Jolt contact. There is no assigned sag trajectory or velocity.

The translation rows are inextensible constraints, with passive rotational
springs for effective bending/twist. The factory uses maximum rod lengths of 4 cm for motor leads and 8 cm for
other leads;
effective rigidity is 0.00002 N m² and viscous loss time is 0.002 s. The
construction path is a **preformed stress-free shape**. It is not a straight
wire constitutive rest configuration, nor an analytical catenary. Effective
rigidity, insulation friction (0.5) and connector ratings are declared
prototype parameters, not measured calibration. Internal spring damping is
separate from environmental drag; native linear/angular drag is zero.

Cable joints request 128 velocity and 16 position iterations; rod contact uses
32/8. Bounds are 256 rods per lead and 256 leads per world, subject also to Jolt's
existing joint/body budgets. Default game steps are 1/240 s. Contact tolerances
and finite segment resolution remain relevant for thin objects and fast impacts.

The accepted-step terminal load is the native translational connector impulse
magnitude divided by dt. Its retention rating is a resultant load limit,
including shear, not an axial-only plug geometry. Exceeding it removes that
terminal's constraint, restores its ordinary contact and opens the matching
native circuit branch before the next electrical step. A pulled-out cable stays
in the world, with mass and momentum; it is not deleted or launched. Removed
connector elastic energy is recorded as `pullout_dissipated_j`; it is not applied
as an impulse or booked as simulated material temperature. The last accepted
electrical step still owns its energy, while displayed current becomes zero on
disconnection. Full native snapshots preserve cable poses and detached ends.
Unpowered electrical islands also build physical leads, including a cable whose
two ports belong to the same housing. A missing supply never removes their mass.

## Factory fitting and electrical coupling

Standard game power plugs declare 50 N resultant retention; the solar lift
bench's four prepared load leads declare 200 N locking plugs. The low-level
native cable default remains 15 N, which is also the falling-load qualification
rating. Neither is commercial calibration. The instantaneous solved connector
force still decides pullout; there is no grace timer, force suppression or
per-level exemption. The attempted elastic connector variants were rejected
for energy gain/unstable seating and are not part of this implementation.

Chosen wire stock length is actual manufactured material: excess stock forms
an initially clear service coil. A wire piece defaults to 5 m; its area controls
copper resistance and mass. Prepared auto-fitted wires use the fitted arc
length. Legacy circuit service loops try 1 m, 0.5 m and 0.25 m extra, then the
clear slack arch, when space is limited. This choice is made only at build
and sets real mass and resistance. The runtime never reroutes wires.

The fitting graph avoids conservative solid bounds and previously fitted
cords. Shared plugs occupy separate seats across the pad, with straight
strain reliefs. Reserved future plug corridors keep earlier cords from
blocking the next socket. These reservations are construction constraints,
not invisible runtime collision bodies. Compound bounds remain conservative;
they do not exploit arbitrary holes. A short stock or an inaccessible pad
returns a fitting error instead of putting material through a solid.

PV charging cords contain two declared copper cores. Resistance is
`2 * 0.0172 * length_m / area_mm2`. For available converted sunlight P,
destination voltage V and cord resistance R, the regulated lumped input uses
`I = 2P / (V + sqrt(V² + 4RP))`: delivery is VI and cord loss is I²R.
Store saturation reduces current; a detached plug stops delivery. The solar
ledger separates delivered energy, spilled conversion and conversion/cord
heat. This is not a switching-converter or MPPT circuit model. Copper heat is
booked energy; no conductor temperature, insulation failure or wet short was
added. A native integration regression checks two-core mass, resistance,
charge/loss closure and zero charging after physical pullout.

Real wire resistance reduced the cannon heaters' power relative to the old
ideal wiring. **Knock it off** and **Chain reaction** now declare 32 V supplies,
restoring useful heating with the physical stock. Their powder, target zones,
deadlines and goal tolerances are unchanged. Wires on the press deck attach
at its conductive pivot, so hanging inlet weight does not operate an empty
switch. Heater polarities bind to opposite clip jaws; solar cords leave the
panel's rear face.

## Qualification

Release verification on the current engine: native cable qualification passes
in 3.892 s on Windows and 3.530 s on Ubuntu 24.04; the circuit target also
passes on both. The level audit passes all 34 solutions in three nudged runs,
plus three settled-setup runs for wired levels, physical negatives and all five
Sandbox demonstrations. See the [full receipt and review notes](level-release-audit-2026-10-16.md).
The detailed 4/2 cm table below is the original motor checkpoint's record;
the current target additionally covers 8 cm rods without changing its bounds.


`banjo_mechanical_cable_tests` is a compiled CMake/CTest target. Its support test
uses the same 0.854400 m lead (0.0455645 kg) over the same 24 × 40 × 30 cm support
with top at 0.75 m, comparing glass, oak and iron. It verifies actual contact,
samples every rod for entry into solid interiors, checks sag, material mass,
constraint gaps and absence of unexplained energy gain. Each material runs at
8 cm, 4 cm and 2 cm segment maxima, at 1/240 and 1/480 s.

| Support | Lowest point after 2 s, 4 cm, 240/480 Hz | Maximum joint gap, 4 cm, 240/480 Hz |
|---|---|---|
| Glass | 0.721365 / 0.724026 m | 0.306246 / 0.149056 mm |
| Oak | 0.722354 / 0.726094 m | 0.306344 / 0.149148 mm |
| Iron | 0.720780 / 0.726502 m | 0.306395 / 0.149184 mm |

At 2 cm resolution the lowest points are 0.723345/0.727431 m (glass),
0.727556/0.726681 m (oak), and 0.728981/0.726234 m (iron). Maximum joint gaps
remain below 0.406 mm. This is a finite-resolution comparison, not proof of
continuum convergence. The acceptance gap bound is 3 mm; no level goal or
existing game tolerance was loosened.

Dropping the same 16 cm cube from y=1.25 m onto the cable pulls a normal 15 N
terminal at 0.220833 s (glass, 10.24 kg), 0.225 s (oak, 2.8672 kg) and 0.225 s
(iron, 32.2355 kg). Shape and release conditions match; masses differ by material.
No scripted impulse is used. Separate weak-terminal tests verify pull-out and
save/restore; native electrical integration verifies zero current afterwards.

The free-system test includes **both movable terminal bodies and every rod**,
zero gravity/drag and zero constitutive damping. A 1 N force acts on one rod
for 0.05 s; the world continues to 0.3 s. It records external impulse, angular
impulse and midpoint work from measured velocities. Across glass/oak/iron mounts,
linear momentum residual is below 8.2e-7 kg m/s and angular momentum residual
below 4.8e-6 kg m²/s. The fixed acceptance bounds are 2e-6 and 1e-5 respectively.

| Mount | Mechanical energy minus external work, 240/480 Hz |
|---|---|
| Glass | -0.00272537 / -0.000237416 J |
| Oak | -0.00129666 / -0.000153079 J |
| Iron | -0.00329508 / -0.000325120 J |

Refining dt reduces absolute residual by more than fourfold for the same driven
experiment. These are **numerical losses**, not cable heating or verified
mechanical energy closure. Rotational stored-energy readings use the small-angle
isotropic approximation; the native quaternion spring law remains the response.
Contact friction/damping work and numerical corrections are not yet separately
resolved into a complete cable thermal ledger. Fixed-support tests include
gravity in potential energy and zero work at immovable supports. Their maximum
energy change stays nonpositive; that alone does not validate energy closure.

The original all-elastic translation trial was rejected: stiff axial springs
accumulated excessive elastic energy and opened normal terminals. It is not
published. Increasing only body contact iterations did not fix long-chain joint
error. Native fixed translation rows and explicit joint iteration budgets
substantially reduce gaps and energy residuals; the remaining losses are above.

## Remaining limits

October 16 solar-bench qualification: its four prepared leads now declare
200 N locking-plug retention; the separate solar charging cord retains 50 N.
On two CPU slots with no Jolt workers, Linux at dt=0.0005 s previously pulled
out a 50 N motor return during its floor impact, stopping the oak load at
0.01509 m. With the declared locking connectors it rises 0.08396 m and the
largest measured plug force is 106.31 N over 0.75 s. The goal and tolerances
are unchanged. Windows and Linux compare oak/glass/iron at 240/480/1000/2000 Hz;
the load/hinge energy ledger is distinct from cable whole-pipeline conservation.
These are prototype connector ratings, not calibrated hardware geometry.
Impact peak forces in this inextensible model remain timestep-sensitive; this
fixture change does not establish a converged connector-damage or axial-strain law.

This is a discrete, inextensible, preformed cable approximation. It does not
resolve copper strands, axial stretch/yield, plastic kinks, insulation wear,
dielectric breakdown, cutting/melting, arcing, thermal expansion, connector
friction/contact geometry or calibration against a real wire sample. Thin-wire
high-speed contact and arbitrary large mass ratios are not universally qualified.
Mechanical contact is with the rigid Jolt world; this does not register a new
fracturable/optical/thermal material volume in every other domain. No library
change or visible tube can establish those capabilities by itself.

Native measurements and performance receipts are kept under ignored
`build/cable-native-final.log` and `build/cable-linux-native.log`; browser and
integration logs use the same prefix. Recent Changes describes the visible electrical wire families migrated by
this checkpoint; it does not claim distributed rope or internal-device physics.

The native qualification runs in 2.993 s on Windows and 2.644 s on local Ubuntu
24.04, covering twelve sag/contact scenarios, three falling materials, six
whole-system reaction scenarios and pull-out/restore. These are test-suite wall
times, not an isolated hosted-server benchmark. Windows additionally passes
80 game checks (130.093 s), 41 electrical checks (99.415 s), and the three-layout
motor browser check (9.966 s). The final unpowered-island, pull-out, restore,
motor-direction and gear follow-up passes four checks in 3.412 s. HTTP hosting
and co-host test isolation pass 42 and seven checks respectively. Source
registration covers all 273 C++ sources. Logs retain the rejected trials too.

Inherited CI at 2ca1ae3 failed the spring Adjust button's immediate hit test on
390 and 320 px phones. The regression now waits for the complete existing
enabled/44 px/in-scene/hit-test predicate, rather than visibility alone, while
the native session and next layout frame finish. No target-size or visibility
condition is weakened and no spring behavior changes. Its four-layout native
lift check passes in 25.881 s; full checkpoint CI remains required.

The first hosted checkpoint dd36c712 passed package checks and manually completed
Turn the axle with three stars, with its engine hash matching the published
package. Broader CI then exposed a Sun-powered lift editor placement at
x=-0.16, z=-0.6, turn=-90°, tip=70°. The old construction bound replaced every
rotated box with a diagonal-size cube, falsely enclosing a motor terminal in
empty space and blocking placement/connection. Bounds now use actual transformed
corners, recursively through compounds, in the engine's Rx Ry Rz convention.
Native collision laws, goals and tolerances are unchanged. A compilation/corner regression
and the ordinary three-layout solar connection flow cover this follow-up.
Three compilation/native checks pass in 2.832 s. The solar connection and motor
browser flows pass in 36.106 s across desktop, phone portrait and landscape.
The native executable is unchanged by this construction-bound correction.
