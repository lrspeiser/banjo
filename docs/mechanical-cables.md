# Physical motor leads — October 16, 2026

## Delivered scope

Motor leads in Turn the axle, the prepared gear motor and Sandbox motor setups
are native mechanical bodies. Electrical wires can also opt in with a
`mechanical` object. Old non-motor wires and ideal solar charging leads remain
electrical graphs/drawings; ties and ideal pulley/drum ropes are not replaced.
The motor itself retains its existing lumped torque/back-EMF model.

The authoring compiler calculates a conservative clear construction path and
adds manufactured slack. Its arc length sets copper resistance, using
0.0172 ohm mm²/m and the declared area. Runtime motion never recalculates this
route. Native gravity/contact must move the wire around an obstruction. The
3D renderer uses the returned rod endpoints and the actual collision radius,
including in predicted flow frames. It does not smooth a line through solids.

## Mechanical model and units

`MechanicalCable` builds rods in the same Jolt world as the machinery. Jolt is
the single owner of their rigid contacts and connector response. Each rod has
a capsule collision envelope and material-derived mass:

`mass/length = conductor_area * conductor_density + insulation_area * insulation_density`.

The default is 2.5 mm² conductor, 3 mm outer radius, 8960 kg/m³ conductor and
1200 kg/m³ insulation. Density values are explicit model parameters, not a
calibrated commercial cable specification. Rod inertia homogenizes that mass
over the cylindrical section; overlapping collision caps add no extra mass.
Only adjacent rods and each terminal's immediately embedded rod exclude their
own overlapping contact envelopes. Other rods, other wires and obstacles retain
Jolt contact. There is no assigned sag trajectory or velocity.

The translation rows are inextensible constraints, with passive rotational
springs for effective bending/twist. Default maximum rod length is 4 cm;
effective rigidity is 0.00002 N m² and viscous loss time is 0.002 s. The
construction path is a **preformed stress-free shape**. It is not a straight
wire constitutive rest configuration, nor an analytical catenary. Effective
rigidity, insulation friction (0.5) and connector rating (15 N) are declared
prototype parameters, not measured calibration. Internal spring damping is
separate from environmental drag; native linear/angular drag is zero.

Cable joints request 128 velocity and 16 position iterations; rod contact uses
32/8. Bounds are 256 rods per lead and 32 leads per world, subject also to Jolt's
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

## Qualification

`banjo_mechanical_cable_tests` is a compiled CMake/CTest target. Its support test
uses the same 0.854400 m lead (0.0455645 kg) over the same 24 × 40 × 30 cm support
with top at 0.75 m, comparing glass, oak and iron. It verifies actual contact,
samples every rod for entry into solid interiors, checks sag, material mass,
constraint gaps and absence of unexplained energy gain. Each material runs at
4 cm and 2 cm segment maxima, at 1/240 and 1/480 s.

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
integration logs use the same prefix. Recent Changes describes the delivered
motor behavior without claiming that all old connections have been migrated.

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
