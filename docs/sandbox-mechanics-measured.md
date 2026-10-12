# Sandbox mechanics and optics: measured checkpoint

11 October 2026. This implements the guide's knife, mirror, lens, solar panel,
block and tackle, spring, gear pair and weight cards as independent declaration
builders. Each has an editable saved example and an easy challenge. The
examples and controls run the same engine as ordinary levels. No piece name
selects an outcome and no launch or rolling velocity is assigned.

The new registry lives in `scripts/sandbox_mechanics.py`; its tests are
`tests/sandbox_mechanics_tests.py`. All eight example declarations were composed
through the real game and checked for placement clashes. Tests initially used
the existing `build/rube/Release/banjo_live_world_run.exe` and were repeated with
the extended `build/agent-water/Release/banjo_live_world_run.exe`. The module
changes declarations, not C++ physics. These are laboratory-model validations,
not calibrations against manufactured parts.

## Controls and reusable examples

| Card | Editable physical settings | Example |
| --- | --- | --- |
| Knife pendulum | Position, pivot height, arm length, swing direction, edge radius, whole-kit turns | Cut and catch: an edge strikes an oak cord holding an iron weight over a bin |
| Mirror | Position, beam height, square aperture, face angle, tip and roll | Around the corner: a 10 W electrical laser source reflects onto a 400 mm² sensor |
| Lens | Position, beam height, convex/concave faces, curvature radius, aperture, whole-kit turns | Find the focus: a broad beam and a sensor show the effect of alignment and concentration |
| Solar panel | Position, post height, square active area, orientation, included or selected battery store | Charge in the sun: a 20° sun and an initially empty 10 kJ battery |
| Block and tackle | Position, counterweight height, material-and-size mass preset, ratio 1–4, included load material or selected existing moving load | Lift with less: a supported frame raises a load using a falling counterweight |
| Spring with guided load | Position, initial height, relaxed length, stiffness, internal viscous damping, load material | Bounce and settle: a moving box compresses a spring attached to a grounded base |
| Gear pair | Position, axle height, 12/18/24 tooth presets, bearing friction, explicit included drive off/forward/reverse | Fast wheel slow wheel: a finite battery motor drives the pair; off supplies no power |
| Weight | Position, side length, initial height, oak/glass/iron, loose/hanging/guided mounting, whole-piece turns | Tip the lever: a raised loose weight falls onto one end |

Named solar battery stores and tackle loads are real declaration references.
An included panel battery starts empty. With no sun in the base the panel
declares a disabled, zero-irradiance environment so that placement is valid
without supplying free energy. The working solar example supplies its explicit
sun. The included gear drive is explicitly selected in the saved example; the
ordinary gear card starts unpowered. Gears also expose named input and output
hinges for a separately wired motor.

The spring card packages a supported linear element and guided load. Its coil
does not claim a material-derived stiffness, plasticity, or nonlinear force
law. General two-part spring attachment is a separate connection workflow;
the basic card's initial preload is the difference between its declared anchor
distance and relaxed length. Initial elastic energy is one half stiffness
times that difference squared; gravitational energy comes from actual mass
and height. Changing the saved initial setup rebuilds those stores, not an
already-running state.

## Engine results

Standard world step is 1/240 s and matter resolution is 20 mm. The low-power
optics source traces 64 rays, once per four steps. Sensor power is an engine
reading; a guide arrow applies no force.

| Scenario | Measured result | Physical negative control |
| --- | --- | --- |
| Knife through 20 mm oak cord | 3.77789 m/s edge contact, 452.6 mm² cut, 6.789 J spent; weight reaches its bin at 0.683 s | Knife moved away leaves the weight hanging |
| Mirror at 45° | Sensor receives 1.9406 W; light energy residual 5.33×10⁻¹⁵ J | 0° orientation misses the sensor |
| Convex lens, face radius 0.2 m, aperture 0.12 m | Sensor receives 7.3134 W | Moving the lens 0.3 m sideways gives 0.2812 W, below the 2 W goal |
| 0.25 m² panel aimed at 20° sun | 250 W incident, 50 W charging; 46.7 J stored after the session's one-second sample | Flat stores 16 J; disabled sun stores zero; full battery stays at 10 kJ |
| 2:1 tackle with included oak load | Counterweight falls 0.92204 m, load rises 0.46092 m; travel residual 0.00020 m | Same 2.7 kg preset cannot raise the heavier iron load |
| 12:24 gear pair, two-second run | Input +559.08°, output −279.54°, 4.33 J source draw; electrical residual −8.81×10⁻¹³ J | Drive off remains still |
| Guided spring, 400 N/m and 20 N s/m, three seconds | Oak centre 0.54984 m; glass 0.47996 m; iron 0.23480 m | Material-derived mass changes the equilibrium and dynamics |

The cutting comparison uses identical cord geometry, initial blade setup and
iron hanging weight, changing the cord's declared material only. Oak cuts
through as above. Glass reports glancing contact at 3.13475 m/s and no cut work;
iron reports blunt contact at 3.77838 m/s and no cut work. Both remain hanging.
These observations distinguish cutting from brittle cracking or metal cutting;
they do not claim that every possible blade/material combination was validated.

Each new easy solution reaches its own goal in three runs: original and two
nudged declarations, up to 1.5 mm on every moving body's initial position.
Each specifically wrong setup wins zero of three, and each empty machine
fails to meet its goal. Observed goal times were knife 0.683 s, mirror 0.017 s,
lens 0.017 s, solar 0.467 s, tackle 0.733 s, spring 0.050 s, gears 1.400 s and
weight 0.233 s. The spring challenge is the guide's gentle stored-energy lift
variant, using a compressed spring; it does not score mere transient passage
through the settling example's height band. Scoring pars were measured from
each own solution and rounded upward to three significant figures.

## Spring ledger and numerical correction

A separate full moving-system audit runs identical 120 mm boxes, starting at
0.65 m, on the guided spring: 1000 N/m, rest length 0.5 m, viscous damping
30 N s/m. There is no floor or guide-stop contact during the 0.25 s audit.
The fixed base and guide do zero work; gravity is external. Kinetic energy,
gravitational potential, elastic energy, and a stepwise integral of damping
are included. Fixed-anchor reaction impulse is accounted for by the spring
force and damping impulse. The difference from measured moving-body momentum
is recorded separately as numerical correction.

| Material | Actual mass kg | Energy correction J, 240 Hz / 480 Hz | Impulse correction N s, 240 Hz / 480 Hz |
| --- | --- | --- | --- |
| Oak | 1.2096 | −0.400340 / −0.216929 | +0.330507 / +0.165843 |
| Glass | 4.32 | −0.677215 / −0.363059 | +0.617298 / +0.317187 |
| Iron | 13.59936 | −1.367879 / −0.742379 | +1.309027 / +0.696001 |

The implicit spring/constraint integration and damping quadrature produce
additional numerical loss. Refining the step reduces both residuals. These
losses remain separate from the declared viscous damping and from environmental
drag. They are not evidence for exact full-pipeline conservation, nor a reason
to use stiff presets as precise engineering predictions. Long-time rigid-body
sleep can also stop a load near, rather than exactly at, its analytical
equilibrium. Gear travel ratio and tackle travel ratio alone likewise do not
prove complete mechanical energy conservation.

## Combined easy challenge 20: charge then lift

`scripts/sandbox_combinations.py` assembles an empty finite battery, panel,
motor, a real offset oak lifting arm and a parallel 30 W bulb. A ratchet
holds the arm against gravity before there is power. The arm is 0.5×0.06×0.12 m,
its centre 0.15 m from the axle; its material gives 2.52 kg. The motor has
5 N m stall torque and 6 rad/s no-load speed. The supported hinge has
0.001 N m bearing friction. The low sun is fixed at elevation 20°, azimuth 180°.
The working panel turns −90° and tips 70°, producing 50 W. A flat panel gives
too little voltage under the bulb and gravity load to lift the arm.

The arm centre must rise 50 mm. Correct setup wins three of three nudged runs
at 0.533, 0.550 and 0.517 s; flat and empty setups win zero of three. A direct
hinge removes any dependency on the existing drum-rope constraint for this
challenge. A candidate drum lift was rejected after its shaft-to-load audit
showed roughly 0.37 J unexplained gain in a four-second run; that result is
not silently treated as a successful validation.

`tests/sandbox_combinations_tests.py` audits the entire final transfer at
0.75 s, including solar input, stored battery energy, wire/motor/bulb heat,
emitted light, shaft work, arm gravitational and kinetic energy and bearing
loss. The fixed mount's reaction does zero work. Its mechanical inertia about
the axle is computed from the material-derived box mass and parallel-axis
theorem; no decorative flag mass is omitted.

| Step s | Arm potential J | Arm kinetic J | Bearing heat J | Shaft work J | Mechanical residual J | Electrical coupling correction J |
| --- | --- | --- | --- | --- | --- | --- |
| 1/240 | 2.274845 | 0.173921 | 0.000660 | 2.451985 | −0.002559 | +0.028164 |
| 1/480 | 2.275586 | 0.174643 | 0.000661 | 2.451774 | −0.000884 | +0.014104 |
| 0.001 | 2.275834 | 0.175004 | 0.000661 | 2.451648 | −0.000150 | +0.006778 |
| 0.0005 | 2.276081 | 0.175171 | 0.000661 | 2.451586 | +0.000327 | +0.003395 |

The electrical coupling correction is an explicitly booked numerical work
term: source plus correction equals shaft plus circuit heat plus emitted
light plus exported heat. It is not relabelled as a physical heat loss.
It is below 2% of shaft work at the standard step and decreases with refinement.
Mechanical residual stays below 0.01 J; the finest-step sign change is comparable
to the rounded pose/velocity output used in this audit. Electrical residuals
are below 7×10⁻¹³ J; thermal residuals below 7×10⁻⁸ J. The battery ledger closes
solar receipts minus withdrawals to remaining charge within 10⁻⁵ J.

The exact same arm geometry, motor, light and sun were repeated with glass
(9 kg) and iron (28.332 kg). Both stall against gravity and remain held by the
ratchet, with zero lift and shaft work. Their input becomes real circuit heat
and light. The 0.01 J mechanical bound, 2% shaft coupling bound, 10⁻⁸ J
electrical bound and 10⁻⁶ J thermal bound are explicit regression limits for
this fixture, not general conservation guarantees.

The mechanics suite runs 11 tests in about six seconds; the combined suite
adds two tests in about nine seconds, including twelve material/timestep
audits. Source registration, browser layout, save/restore, live-server binary
receipt and published-site validation belong to the integrating delivery.
General tooth contact/backlash, textile rope, arbitrary blade release angles,
diffuse reflected illumination and calibrated wood-grain cutting remain
unsupported. The optical and pulley source fixtures are reusable saved bases;
the card alone does not invent a source or target.


## Waiting load spring October 12

The current spring lesson starts with a separate 12 cm oak load at y=0.4 m,
resting on two fixed fork prongs (top y=0.34 m). A grounded rear post carries
those prongs and leaves the center clear for the spring. Adding the spring
creates its fixed base at y=0.04 m, guide and existing general native spring
and slide joints, connected to the waiting body; it does not recreate or move
the load. The native 5 cm rise goal and one-second deadline are unchanged.
The 20 cm default relaxed length cannot lift it; increasing to 70 cm stores
energy in the declared compressed spring. A source one metre aside produces
downward tension rather than the needed lift and fails three nudges.

The sandbox's spring card can select an existing moving Load or retain its
original included load. An external load supplies its own material, mass and
initial position; the corresponding included-load height/material controls
are hidden. The axis guide and spring use that body's actual attachment
point. No arbitrary launch velocity, material-name exception or scripted
displacement was added. This remains an ideal linear force element, not a
constitutive model of metal coil geometry or buckling.

Matched full-fixture probe: oak/glass/iron, identical 12 cm load and cradle,
spring anchor y=0.08 m, k=200 N/m, rest=0.7 m, internal damping c=6 N s/m,
g=9.81 m/s², chosen initial velocity zero, duration 0.1 s, rigid steps
1/240 and 1/480 s, 2 cm solid lattice. Body masses are material-derived.
The motion window ends before the upper guide stop for the lifted loads.
The dense iron load instead remains on its physical cradle.

| Load | Mass (kg) | Final y, coarse / fine (m) | Initial load+spring energy (J) | Final energy, coarse / fine (J) | Damping quadrature, coarse / fine (J) |
|---|---:|---:|---:|---:|---:|
| Oak | 1.2096 | 0.59833 / 0.59802 | 19.1864704 | 15.8854084 / 16.0915492 | 2.5874690 / 2.7230532 |
| Glass | 4.3200 | 0.43681 / 0.43629 | 31.3916800 | 31.2398385 / 31.2649871 | 0.0922386 / 0.0958666 |
| Iron | 13.59936 | 0.40000 / 0.40000 | 67.8038886 | 67.8038886 / 67.8038886 | 0 / 0 |

Energy E=m*g*y + m*v²/2 + k*(y-0.78)²/2 includes gravity and the actual
spring preload. E_final + integral(c*v² dt) - E_initial is -0.713593 /
-0.371868 J for oak, -0.059603 / -0.030826 J for glass, and zero for iron.
This reported correction/contact remainder decreases on halving dt; it is
not reclassified as internal damping or claimed as a closed conservation
residual. The existing implicit joint solver and old-time quadrature are
unchanged. The +0.01 J no-new-energy check uses the existing mechanical
receipt allowance; no level or conservation tolerance changed.

Momentum m*v_final - integral((-m*g - k*(y-0.78) - c*v) dt) is -0.244974 /
-0.125415 N s for oak, -0.049859 / -0.026279 N s for glass, and +5.740972 N s
at both steps for iron. The last value includes the required external cradle
reaction: its weight exceeds spring preload by 57.40972 N over 0.1 s.
Native joint/contact support reactions and integration corrections are not
independently reconciled in this probe, so these values are explicitly
unaccounted support/numerical impulses, not full-pipeline momentum closure.
Fixed supports perform zero work in this geometry. Detailed constraint,
pose-correction and contact-loss reconciliation remains unsupported.

The nominal oak lesson reaches its unchanged goal at 0.050 s in all three
whole-apparatus nudges. Empty, default-length, short-length and one-metre
misplaced setups fail 0/3. The existing material-matched spring/damping and
tackle regressions still pass. Twelve mechanics tests complete in 7.8 s;
the new six-fixture plus misplaced/default control check takes 0.58 s alone.
The native engine remains SHA-256
3fac18bff131cf0d819e6186969c4ed64b27210eef04e36f420bd497ce39d24a.
