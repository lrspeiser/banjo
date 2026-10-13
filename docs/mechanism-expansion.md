# Mechanism catalogue and first expansion pack

October 13, 2026. This audits the owner's supplied mechanism list against the
game and records the new playable pack. It does not restore the removed open
world or labs. A named card is only available when its underlying model runs.

## Implemented in this pack

Seven additional library cards and seven editable examples are described in
[machine-game.md](machine-game.md#more-contact-and-spring-mechanisms).
Dominoes already existed; their Sandbox controls now include material and a
leaning first piece. The existing level recipes continue using their original
builders, goals and deadlines. There are no new challenge levels in this pack.

Door/trapdoor leaves are material-mass cuboids on native hinges. Pendulums
are one rigid compound arm/bob. Flywheels are precise cylindrical compound
bodies with a native axle. Their motor reacts through the mount and consumes
a finite wired source. Loose blocks and dominoes use ordinary rigid contacts.
No named trigger tips the next domino, opens a door or gives a ball velocity.

The trampoline is a rigid rubber/oak/glass/iron deck on four bounded linear
distance springs and one vertical guide. Total stiffness/damping are divided
equally among the springs. Its nominal unloaded equilibrium uses
`height = 0.4 - mass * 9.81 / total_stiffness` metres; springs attach at 0.08 m
and 0.02 m below the deck center with a 0.3 m relaxed length. Mass is density
times deck volume. Existing cell rounding and the spring/contact solver cause
small settling. No initial upward velocity or extra rebound impulse is used.
Travel stops are mechanical constraints. This is not fabric tension,
finite-element membrane deformation, nonlinear rubber elasticity or a person
jumping on a trampoline.

## Prescribed open-air drag

An **Open airflow** marker declares an external, constant velocity inside an
axis-aligned box. The native engine evaluates each current primitive body's
center, orientation, dimensions and velocity before every step. For relative
speed `u = air_velocity - body_velocity`:

`F = 0.5 * rho * Cd * projected_area * |u| * u`

Air density is 1.225 kg/m³. The approximate bluff cuboid coefficient is 1.05,
with `A = |nx| dy dz + |ny| dx dz + |nz| dx dy` in the body's shape frame.
Spheres use `Cd = 0.47` and `A = pi * diameter² / 4`. These are illustrative
constant-coefficient drag approximations, not measured fan calibration or a
Reynolds-dependent aerodynamic catalogue. Dimensions, including the authored
shape rotation, determine exposed area. This applies to every matching box or
sphere, irrespective of name. Compound bodies and fractured hulls are excluded.

Force acts at the center of mass. A door turns because that point is offset
from its hinge; the hinge solver supplies the mount reaction. No independent
aerodynamic couple or rotational surface-velocity model is added. The external
atmosphere receives the opposite force, reported as `external_reaction_n`;
its state is not simulated. The body load ledger records signed `F·delta_x`
work through the committed displacement, including the latest step. Positive
air work contributes to the game's run energy; negative work is exported to
the prescribed atmosphere. Native snapshots retain fields and their ledgers;
saved design versions retain their declarations and restart at time zero.

There is no powered fan, CFD, occlusion behind walls, pressure, lift, gusts,
turbulence, balloon gas or propeller thrust. The box boundary is abrupt and
tests body centers rather than partial immersion. Independent fields must not
overlap, so contradictory velocities cannot produce double drag. The marker
is not a silently powered motor. Axle-driving windmill blades need a future
surface-velocity/torque model, not a continuously assigned spin.

## Measurements

`tests/sandbox_motion_tests.py` runs builders, the declaration compiler and the
compiled native engine. All seven examples compile. Setup editing moves the
air field with its source and removing its source prunes it. Overlapping fields
are rejected. Runtime wind snapshot continuation matches poses and work within
0.0001 m/J after an additional 0.05 s. A missing flywheel return wire leaves its
axle at rest; the closed loop rotates it. Door runs with wind exceed 5° in one
second for oak, glass and iron; zero prescribed air does not open it. Domino
chains topple their last block at 0.1 m spacing and leave it standing at 0.4 m,
for all three materials. Pendulums strike an independent block, and trapdoors
fall under gravity for all three materials; 20 N·m holds the oak flap.

The default rubber-deck trampoline compresses and the marble rebounds by at
least 0.08 m after its first local minimum, remaining below its 1.2 m release
height. That is a behavior check, not a full joint/contact energy ledger closure.
Spring damping, material contact losses and the existing solver correction
must not be conflated with airflow drag.

The full free-fall airflow audit uses a 0.2 m cuboid, released at 2 m, inside an
8 m/s field for 0.2 s, 20 mm cell resolution, no contact. Existing cuboid solver
background damping is 0.02/s; its impulse and work are accounted separately.
Semi-implicit integration's measured loss is separated from physical drag.
Numbers below include gravity, wind, background damping and integration loss;
public pose output is rounded to 5 decimals.

| Material | Mass kg | dt s | Air work J | Background loss J | Integration loss J | Closed residual J | Largest momentum residual N·s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Oak | 5.6 | 1/240 | -0.049253 | 0.029409 | 0.222037 | 0.000212 | 0.000024 |
| Oak | 5.6 | 1/480 | -0.049433 | 0.028958 | 0.111013 | -0.000084 | 0.000022 |
| Glass | 20 | 1/240 | -0.058505 | 0.105390 | 0.796907 | -0.000343 | 0.000087 |
| Glass | 20 | 1/480 | -0.058620 | 0.103777 | 0.398462 | 0.000751 | 0.000056 |
| Iron | 62.96 | 1/240 | -0.060994 | 0.332130 | 2.512463 | 0.000763 | 0.000159 |
| Iron | 62.96 | 1/480 | -0.061092 | 0.327050 | 1.256283 | -0.001662 | 0.000309 |

Residual limits are 0.02 N·s and `mass * 0.0001` J, chosen for the rounded
readout and tested timesteps. Refining dt approximately halves integration
loss. Negative total wind work here means vertical drag removes more fall
energy than horizontal wind supplies. These runs take about 0.012–0.025 wall
seconds each on this Windows machine. They do not establish full-pipeline
conservation for collisions, hinges, fracture or fluids.

All 34 existing levels' author solutions pass three nudged native runs and
their missing-piece setups remain unsuccessful (`machine_game_tests.py`,
Tray/FreeBuild plus the full level solution regression: 33 tests, 41.8 s).
Browser checks open every level and exercise the new examples, editing airflow,
Undo, Run/Pause/Reset, saved-version persistence and replay at 1280×860,
390×844 and 844×390 (two browser tests, 30.3 s). These are measured behavior
and layout results, not proof of all catalogue physics.

## Supplied catalogue: existing, new and still to build

| Mechanism family | Available game scope | Remaining work |
| --- | --- | --- |
| Toppling / collapsing stacks | Domino rows and new independent loose blocks | Calibrated buckling and structural-collapse fracture |
| Rolling balls / cylinders | Marbles, ramps and colliding hollow pipes; native cylinder compounds | Separate rolling-cylinder card and complete rolling-loss audit |
| Sliding / ice / sleds | Existing material contacts, ice material, loose boards/blocks | Sled card and calibrated surface presets |
| Bouncing / trampolines | Native material restitution; new spring platform | Flexible membrane and calibrated rubber strain |
| Swinging / pendulums / wrecking balls | New weighted rigid pendulum; existing hanging weights/rope | Articulated chain wrecking-ball assemblies |
| Balancing / seesaws / scales | Existing hinged lever and weights | Scale/readout card |
| Rotation / flywheels / turntables | New passive flywheel and existing motor/axles | Horizontal turntable card and angular drag |
| Gears / pulleys / springs / levers | Existing separate contact gears, tackle, springs, lever and links | Involute teeth, belts and flexible cables |
| Projectiles | Existing cannon and contact-driven catapult | More general projectile launch mechanisms |
| Doors / tripwires / ratchets | New doors/trapdoors; existing ropes, hinges and native ratchet law | Reusable physical latch, pawl and tripwire cards |
| Water wheels / channels / reservoirs | Existing wheels, river, finite gravity tanks, chutes, collectors | Moving tank containment and COM shift for tipping buckets |
| Pipes / valves / siphons | Existing colliding hollow routes and tank taps | Pressure plumbing, joint leaks, siphon priming and network head losses |
| Wind / airflow | New prescribed drag on simple boxes and spheres | Shielding, fan energy, sails, balloons, propellers, gusts and surface torques |
| Buoyancy / floating platforms | No validated general placeable floating apparatus in this pack | Solid displaced-volume pressure/reaction and stability checks |
| Dams / displacement / vortices / fountains | Existing shallow river and falling native parcels | Validated water pressure/displacement, vortices and pumps |
| Hydraulics / pneumatics | Existing thermodynamic piston/gas engine scope | Separate hydraulic/pneumatic components, connectors and volume conservation |
| Granular sand / jamming | No game card | Material grains, contact/friction, piles, hoppers and validated jamming |
| Viscosity / oil / honey | No game card | Declared calibrated viscous-fluid constitutive laws |
| Batteries / switches / motors / RC circuits | Existing placeable wired components, physical rockers, lamps, resistors and capacitors | See [electronics expansion](electronics-expansion.md): inductors, diodes, transistors and more |
| Magnetism / electromagnets / solenoids | No magnetic machine law in this pack | Fields, current coupling, force/reaction/energy and saturation |
| Thermal expansion / wax / boiling | Existing heating, thermo gas and steam apparatus | Geometry-changing expansion, melting wax, phase transitions and latent heat |
| Combustion / fuses / candles | Existing native material heating/char/cutting and ignition controls | Validated spreading flame, fuse progression, smoke and oxidizer transport |
| Material failure / glue / suction | Existing limited cutting/thermal weakening and native constraints | Calibrated glue/suction, damage/plasticity/grain and full transfer accounting |
| Rubber bands / chains / belts / membranes | Existing linear spring/rope constraints only | Flexible geometry, strain/contact, mass and calibrated damping |
| Freezing / condensation / sound / vibration | No new game components | Phase-change transport and mechanically coupled acoustic response |

Next coherent packs should be physical latches/ratchets and turntables, then
moving liquid containers/buoyancy/pressure plumbing, followed by magnetic and
thermal/phase-change work. The proposed ten-mechanism 60-second benchmark
remains to build and audit; this document does not claim it exists.
