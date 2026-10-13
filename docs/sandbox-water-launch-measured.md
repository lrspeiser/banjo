# Fixed water sources and counterweight launchers

Updated October 12, 2026. The independent gravity tank measurements below
supersede the October 11 metered-tank lesson timings and model limits. The
older measurements remain as receipts for saved metered sources.

11 October 2026. Implemented in `scripts/sandbox_water_launch.py`,
`scripts/machine_world.py` and the existing falling-water engine. Measurements
below use the final Windows Release integration engine built in
`build/agent-integration` (and the earlier `build/agent-water` calibration), 2 cm solid
cells, 10 cm flume columns and 4 cm water parcel spacing (64 mL, 64 g per
parcel). Direct native audits use 2 ms rigid steps (and 1 ms comparisons);
live/rehearsed challenge tests use the game's 1/240 s steps, grouped in
four-step replies. Fluid substeps satisfy its support/sound-speed bound,
0.25×0.10 m/(20 m/s + parcel speed). Challenge readouts are sampled roughly
every 1/12 s, which limits precision of the reported win times.
These are game demonstrations, not calibrated
water-turbine or real-world catapult predictions.

## Divert water into a fixed container (October 12)

**Divert the water** adds one routing lesson without changing earlier water
lessons or their goals. Its fixed, finite source supplies 1 L/s downward from
1.25 m, with 4 L available. The separate empty collector has an 80×50 cm
outer footprint. A supported, three-sided chute defaults crosswise; aiming
it along +x with a 20° downhill slope routes the water into the collector.
The current 3 L must remain within its interior measurement box for 0.5 s.
The authored solution wins at 4.567 s in all three nudged runs. Construction
plus source work is 6,849,818,448.737 J; par is that measured answer rounded
up by less than 1 kJ. No existing goal, deadline or tolerance changed.

The Sandbox adds independent **Water chute** and **Water collector** cards
and an example with both editable placements. Their mounts use ordinary fix
joints to visible grounded stands. Stand feet follow the channel bed, with
cell-aligned clearance. Placement overlap and bounds checks remain active.
Collector `water_regions` declarations are read-only meters, not sandbox
win stations. A lesson's `water_in_zone_l` station uses the same observation.
The meter counts the current native parcel positions inside the box. Volume
per parcel is recovered from full-precision source emitted-minus-landed-
minus-runoff ledgers and the complete native parcel count, rather than from
rounded display totals. Boundaries inherit the exported 1 mm position
resolution. Water outside, lost downstream, or previously passing through
does not count. The preview is labelled; Reset restores an empty collector.

At 8 s, equal-geometry glass/oak/iron chute and collector runs all retain
3.968 L, with 32 mL left in the supply. Source and parcel mass residuals are
below 1e-12 m³. Engine: Windows Release SHA-256
`1ebc084656f9b4c0206e6c7ca7f9d0e12546700c60e495781ca781493587c352`.


| Material | dt (s) | Falling-water energy residual (J) | Momentum residual magnitude (N s) | Explicit numerical correction (J) |
|---|---|---|---|---|
| Glass | 1/240 | −1.92049e−8 | 8.06e−10 | +0.774295 |
| Glass | 1/480 | +5.71149e−8 | 8.12e−10 | +0.754917 |
| Oak | 1/240 | −1.87342e−8 | 6.51e−10 | +0.774360 |
| Oak | 1/480 | +5.71045e−8 | 9.08e−10 | +0.766375 |
| Iron | 1/240 | −1.92111e−8 | 8.20e−10 | +0.774285 |
| Iron | 1/480 | +5.71285e−8 | 9.12e−10 | +0.766371 |

Empty, crosswise, reversed and sideways-misplaced setups fail for lack of
retained water. After the source stops, the observed region remains filled;
moving only the observation box to the source yields zero. Retained volume
is 3.968 L, distinct from the native rounded display total of 3.97 L.

**Validity and limits:** no new native fluid law was added. This uses existing
64 mL, 4 cm weakly-compressible parcels resting against fixed surfaces, with
frictionless non-bouncing contacts and pressure/viscous pair forces. It does
not establish a smooth hydrostatic free surface, sloshing, moving buckets,
surface tension, arbitrary closed-vessel containment, calibrated pipe flow,
or full rigid/joint/support energy and momentum closure. The visual shows
native parcels; it does not invent a flat water surface. A perfectly flat
chute initially exposed an admitted-speed refusal in the existing parcel
model. The offered chute therefore admits positive 5–35° drainage slopes;
flat pooling is explicitly unsupported. At this apparatus's default position,
5–20° routes successfully; steeper slopes overlap other apparatus and must
be moved before placement. The original failing flat run is not counted as
green, and no native admission threshold was increased.

Verification: the 14-test water/launch suite passes in 37.249 s, including
the new retention and six material/timestep receipts. The complete game
suite passes 53 tests, including all 31 own solutions in three nudged runs.
That complete run took 86.280 s.
All four new width variants pass solution/empty/wrong preflight (three runs
each). Three focused Chrome tests pass in 45.043 s, covering the new lesson
and native win/reset at 1280×860, 390×844 and 844×390, the prior finite-tank
lesson, and the complete Sandbox library/save flow. The shared toolbar check
also passes; short adjustment chips now retain a 44 px minimum width.
Source registration remains 269/269. C++ and its laws are unchanged.
The final diversion browser check also passes in 21.695 s after keeping both
source and destination visible during follow mode and moving its win result
outside the 3D view. It verifies those view constraints in all three sizes.

## What a player can build (earlier pieces)

**Water wheel:** a real supported eight-paddle wheel in an explicitly chosen
flume. Radius 25–65 cm, location along/across the channel, left/right/off external
pour, and 0.5–3 L/s metered supply. A bridge carries the feed over the wheel
from a grounded bank post. Clearance adapts to radius so the axle stays at
least 55 mm above the bank; all nine offered radii have compose-and-run
regressions. The optional Load part control connects a drum rope to an
existing part using its geometry, as in the gate example. The spout is an externally supplied demonstration,
limited to six seconds; choosing Off removes its feed and lets another tank
supply the wheel. The water pushes its paddles with opposite body impulses.

**Fixed water tank:** a hollow iron vessel and grounded frame, with 0–8 L
initial water, a fixed outlet 0.5–1.4 m high and 0.5–3 L/s metered flow. This
is a fixed reservoir model, not a liquid surface, hydrostatic outlet or tipping
bucket. Its valve can be set in the initial setup and changed live. Closing
stops new parcels immediately; water already falling continues. Reset restores
the declared fill and valve. The source retains its subparcel remainder, so
four litres emits 3.968 L and retains 32 mL. Receipts show initial, remaining,
emitted, received and runoff volumes. The receiver is the declared trench
bounds: a landing outside those bounds does not count as a filled receiver.

**Counterweight catapult:** a grounded frame, oak throwing arm with a rigid
cradle, iron counterweight with its own material-derived mass and a separate
marble. Controls set position, aim, 20–40° cocking angle, 10–16 cm
counterweight side and material, 6–10 cm oak/glass/iron marble, loaded/empty
cradle and Held/Released restraint. The
marble is never assigned a launch speed. The falling counterweight turns the
arm, and cradle contact pushes the marble. A held setup installs a physical
fixing; live Release removes that fixing through the general native unhinge
operation. Its axle stays installed. The arm has an ideal upper stop. Reset
recocks the arm and reinstalls the declared restraint.

Saved initial placements contain these settings. Runtime valve changes and
restraint withdrawal are separate queued engine operations; they do not
rewrite the saved setup.

## Examples and easy challenges

The library contains Water turns a wheel, A tank that runs dry, Counterweight
cradle launcher, Water opens a gate, and One tank, one wheel. Every example
builds through the same sandbox composition path. Channel examples create
their compatible flume. A wheel or tank on a dry base is refused with an
instruction to open its example. The finite-tank-and-wheel example disables
the wheel's external feed before adding its four-litre tank.

Four authored easy challenges have measured targets:

| Challenge | Actual engine goal | Three nudged runs | Wrong setup |
|---|---|---|---|
| 6. Pour onto the paddles | Wheel turns 30° | 1.167 s in all runs | Off supply stays still |
| 15. Fill the receiver | 3 L actually lands within collection trench | 2.083 s in all runs | Closed valve, zero fill and 2 L fill fail |
| 17. Gentle first launch | Oak marble enters wide receiving bin zone | 1.100 s in all runs | Held restraint or 90° wrong aim fails |
| 19. Water opens a gate | Guided gate rises 8 cm | 2.033, 2.017, 2.017 s | Off supply or opposite winding direction fails |

Nudges move every explicitly declared loose body independently by up to
1.5 mm per axis, seeds 0–2. A same-size oak counterweight also fails the catch
because it supplies insufficient energy; an empty cradle leaves the arm free
to turn but cannot satisfy a marble goal. No goal threshold or tolerance was reduced to
pass. The wheel/gate connection uses a real drum rope with a 4 cm winding
radius and a real slide constraint. The gate is not moved by a timer or
by watching the wheel's angle in game code. Runs used 0.05–0.28 s wall time
per 1.1–2.1 s of engine time on the development computer.

## Water ledgers and model limits

The finite debit belongs to the engine's accepted falling-water Plan. A
rejected plan consumes no source water. Mass closes across remaining source,
falling parcels, landed channel water and runoff. Poured = landed + runoff +
in air. Per-source received volume is a subset of landed volume, not a second
store of water. The depth-averaged channel's own volume ledger receives every
landed parcel exactly once.

Falling-parcel energy accounts for fixed-mouth source potential/kinetic
energy, pressure/viscous work, contact dissipation, body work, landing/runoff
energy and energy currently in air. Integration and contact-position
corrections are reported separately as numerical correction. Momentum
accounts for emitted momentum, gravity impulse, opposite body impulse,
landing/runoff momentum and momentum currently in air. The reported source
support reaction is the opposite of chosen outlet emission momentum; it is
not a measured tank-support load.

For the four-litre tank after 3.5 s: source energy 42.818688 J, 3.968 L emitted
and received, 32 mL retained; mass residual 0 m³, falling energy residual
−4.97×10⁻¹⁴ J, momentum residual magnitude 2.26×10⁻¹² N s. Its explicit
integrator correction is about −0.386 J. Native unit tests also cover closed
valves, rejected plans, an empty source and a missed receiver.

These are full falling-parcel ledger checks, not a claim of closed coupled
turbine conservation. The shallow channel accepts volume and horizontal
momentum, but does not preserve vertical landing kinetic energy as an
explicit heat store. Moving solid surfaces are predicted from beginning-of-step
velocity during the fluid step; body work uses that surface velocity and is
not yet independently reconciled with every rigid constraint reaction.
Pressure/viscous work is an explicit term, not a proved thermodynamic SPH
internal-energy model. There is no sloshing, arbitrary movable liquid vessel,
spray, capillary force or porous absorption. The October 12 fixed gravity
outlet below adds a lumped head law; it does not add free vessel containment.

## Comparative launch measurement

All three marbles use the same 8 cm geometry, arm, 14 cm iron counterweight,
30° cocking angle and 0.8 s run. Mass comes from occupied 2 cm cells (34 cells),
not a projectile mass override. The glass value is the catalogue's 2500 kg/m³.

| Material | Marble mass | Peak sampled speed, 2 ms | Peak sampled speed, 1 ms | Whole rigid mechanical energy change, 2 ms / 1 ms |
|---|---:|---:|---:|---:|
| Oak | 0.19040 kg | 4.550 m/s | 4.559 m/s | −45.286 / −45.342 J |
| Glass | 0.68000 kg | 4.044 m/s | 4.056 m/s | −37.581 / −37.567 J |
| Iron | 2.14064 kg | 2.823 m/s | 2.825 m/s | −20.182 / −20.254 J |

All projectiles pass 1.45 m height through actual cradle contact; sampled
whole-world mechanical energy never rises above initial energy (+0.01 J
test allowance for solver/receipt precision). The timestep speed difference
is under 0.014 m/s. These measurements are not a conservation residual:
the existing rigid pipeline does not separately report all cradle friction,
ideal hinge-stop losses, joint support impulses or pose corrections. The
large energy reduction includes the arm meeting its upper stop. It is
reported rather than hidden behind the thermal ledger's unrelated zero
residual. Detailed launch conservation auditing and a spring-powered
catapult preset remain experimental work; this first card exposes the
measured counterweight launcher only. A sling is not implemented.

Verification: `tests/sandbox_water_launch_tests.py` exercises actual sandbox
composition, nudged solutions, wrong/closed/empty/unreleased cases, runtime
worker queues, source receipts and all three projectile materials at two
timesteps. `tests/water_tests.cpp` covers accepted-plan debit and complete
falling-parcel ledger closure with a fixed source and receiver.

## River-current wheel

The two new sandbox designs are **Build beside a river** (no wheel placed)
and **River powers a lift** (connected example). River-powered lift asks the player to
place a wheel in the current and raise the guided gate 8 cm within 10 s.
The base is a 6 m by 4 m grid: 10 cm fluid columns, a 60 cm-wide trench,
35 cm depth, 0.005 bed slope, 100 L/s west-boundary inflow and east outflow.
It starts dry. The water initially entering the scene is an external supply;
there is no infinite local tank or invisible falling spout.

The default oak wheel has a 65 cm radius, eight paddles, 36 cm paddle width,
6.5 cm bed clearance and 0.2 N m bearing friction. Its axle is about 35 cm
above the bank datum; a 4 cm drum winds the rope attached to the offset gate's
top. The load slides vertically on its existing physical guide. Its goal,
deadline and tolerances were not reduced to pass; geometry must keep the
target below the drum's lower rope departure. Moving the wheel onto the bank
removes its wetted paddles and cannot lift the load.

The existing `WaterCoupling` integrates pressure and relative-flow drag over
wetted surfaces, applies force and torque at their actual locations, and returns
horizontal drag impulse to the water. Drag coefficients Cd = 1 and Cf = 0.01
are declared game parameters, not turbine calibration. The new native surface
regression uses identical geometry for glass, oak and iron in the same 1 m/s
current: each receives 18.084 N drag and 6.3321 N m drive torque. The paired
horizontal reaction residual is exactly zero in that oracle. Still water
gives zero driving torque; a dry bank gives no wetted force; moving paddles
with the current reduces relative-flow torque. This instantaneous oracle is
not proof of full fluid/rigid conservation.

Full native fixture measurements below use 2 cm solids, 10 cm fluid columns,
10 s duration, 100 L/s, and 2 ms / 1 ms rigid steps. No chosen spin, assigned
wheel velocity, material-name override or scripted gate displacement is used.

| Wheel material | Native wheel mass (kg) | Final gate rise, 2 ms / 1 ms (m) | Whole rigid mechanical energy change, 2 ms / 1 ms (J) |
|---|---:|---:|---:|
| Glass | 194.76518 | 0 / 0 | −1.56e−11 / −1.56e−11 |
| Oak | 54.53425 | 0.09796 / 0.09750 | +0.857881 / +0.853848 |
| Iron | 613.12080 | 0 / 0 | −4.96e−11 / −4.96e−11 |

The oak gate reaches 8 cm at 4.080 s at both timesteps; its potential-energy
increase is 0.861045 / 0.857002 J. Glass and iron remain stationary. This
comparison does not isolate inertia: the existing 10 cm coarse obstacle
seal-gap rule and mass-scaled wake threshold (5% of weight/weight×half-size)
also affect dense wheels. The playable catalogue wheel is oak; dense turbine
behavior remains unvalidated and should not be claimed from a renamed preset.
Wall times for the 10 s native runs were 0.41–1.87 s at 2 ms and 0.50–3.35 s at
1 ms on this computer.

For the 2 ms oak run: initial water 0 m³, inflow 0.999000 m³, outflow
0.436081 m³, retained 0.562919 m³, volume residual −1.17e−14 m³. The maximum
volume residual across material/flow controls is 2.54e−14 m³. Returned
horizontal drag impulse is −67.5133 N s; this is a receipt, not a full momentum
residual. Boundary hydraulic energy, Manning/contact losses, hydrostatic bed
reaction, joint/support work and numerical corrections are not independently
reconciled. The rigid energy changes above are measured changes, not closure
residuals. River boundary work is not included in the game's existing energy
score; the new authored par uses its measured construction cost plus 1 kJ.

The game-step (1/240 s) solution and three nudged runs win at about 4.10 s.
All four seeded flows (95, 105, 110, 120 L/s) win in three nudged runs, at
4.383 / 3.85 / 3.65 / 3.35 s. Dry/no-flow, bank placement, absent wheel and
absent drum connection fail for physical reasons. A full 10 s direct native
probe winds 0.04275 m of rope and reaches a peak 0.10870 m gate rise; its peak
constraint tension of 926.261 N is a solver/contact measurement, not a
calibrated steady lifting force.

Current arrows are static samples of the native velocity grid, quantized at
0.05 m/s per axis and clipped at ±6.35 m/s. Surface heights are in millimetres;
bed heights are float metres. Preview packets retain up to 96 current vectors
and 512 surface tiles per frame; reported preview depth is rounded to 0.1 mm.
These displays change with engine snapshots, not a cosmetic current animation.
Saved versions keep the base's supply and the wheel/drum graph.

Verification: the existing CMake target compiles the added native regression;
`banjo_water_tests` passes 23/23. The full Python water/launch suite passes
10/10, including all nine radii and the river load/negative controls. The game
suite passes 40/40 and seeded recipe/preflight suite 8/8 on the verified
integration executable. Native physics source is unchanged; executable SHA-256
is `569a441595274e13128e1b8f06ff54d392232409b312d2089a77c2451315c976`.

Final browser verification: the river workbench's save/reload/restore test and
native lift lesson pass on desktop and both phone orientations. The battery
carousel and both river tests pass together 3/3 in 30.635 s. The final broad
suite passes 41/42 in 271.367 s, with one portrait solar input-click timeout.
That unchanged test passes three isolated repetitions in 35.665 s, then three
more after four preceding-state checks (7/7 in 47.236 s), without click retries
or relaxed assertions. The intermittent click's cause remains unproven; this
is a remaining QA limitation, not a fully green final broad run. Client geometry,
JavaScript syntax, changed documentation links and source registration (269/269)
pass. Manual portrait 390×844 and landscape 844×390 screenshots show the river
and unobstructed scene controls.

### Previous falling-water checkpoint

Before the river addition, all eight Python water/launch tests passed in
9.103 s. The existing native water suite passes 22/22, including the finite
source and receiver-bound regression. A same-geometry three-second pour
onto different wheel materials (2 ms rigid step, all other conditions held
the same) reports:

| Wheel material | Work handed to body from fluid surface estimate | Falling energy residual | Falling numerical correction |
|---|---:|---:|---:|
| Glass | 6.419442 J | +1.638×10⁻⁷ J | +0.097685 J |
| Oak | 12.095301 J | −5.946×10⁻⁸ J | +0.025795 J |
| Iron | 1.224857 J | +7.056×10⁻⁸ J | +0.067357 J |

All three falling-water momentum residuals are below 5.9×10⁻¹² N s; mass
residuals are below 10⁻¹² m³. These are the complete falling-parcel balances,
with the coupled rigid/channel limitations described above.


## Independent gravity tanks October 12

New tanks and wheels are separate. The wheel has no source unless a tank
pours on its paddles or a river supplies current. The new 25th sandbox example,
**Wheel in the river**, and its lesson use only a 100 L/s boundary current,
65 cm wheel and empty bank/channel. Moving the wheel from z=1 m to z=0 puts
the paddles in the water. Three actual whole-apparatus nudges win at
3.983/4.100/3.883 s; dry supply and bank placement fail 0/3. The earlier
river-lift and its calibrated limits above remain unchanged.

The independent tank is fixed and quiescent, with constant section A=0.0576 m²
(24×24 cm), 5 mm glass walls and floor, 50 mm nominal outlet diameter,
head offset 0.005 m and initial volume 4 L. Its visible surface is V/A above
its native declared floor; it is not an animated free surface or contained
SPH fluid. The builder places its grounded frame on the bank and routes
the ideal connection to the editable outlet. Tipping/sloshing buckets,
support deformation, actual internal pipe flow, approach-flow velocity,
viscous pipe losses, leaks and force-operated valve mechanics are unsupported.

The native law is h=offset+V/A, v=sqrt(2gh), and
Q=Cc*Aout*opening*v, with g=9.81 m/s² and opening in [0,1]. Cc=0.62 models
nominal area contraction: the flowing jet area contracts, rather than giving
every emitted parcel an arbitrarily reduced kinetic energy. It is an
uncalibrated game parameter. The ideal head/velocity relationship and the
need to calibrate real orifice coefficients follow the
[USBR Water Measurement Manual](https://www.usbr.gov/tsc/techreferences/mands/wmm/chap02_08.html)
and its [coefficient discussion](https://www.usbr.gov/tsc/techreferences/mands/wmm/chap02_15.html).
Closing the tap stops new parcels; widening it increases Q, and declining
water head slows Q. The isolation valve and runtime fractional opening are
separate native boundary controls. The drawn handle shows the initial setting;
the runtime slider changes the ideal outlet, not a mechanical handle solver.

Only accepted Plans debit the fixed store. Each 64 mL / 64 g parcel uses
mid-volume head, so its source potential plus kinetic energy exactly equals
the corresponding reservoir potential decrease:
E(V)=rho*g*((mouth_y+offset)*V + V²/(2A)). A rejected Plan consumes nothing.
Four litres emits 3.968 L and retains 32 mL. Reservoir support impulse is
the stored water's integrated gravity impulse minus emitted momentum;
support moment uses its actual bank floor position and the outlet position.
These are receipts for an externally fixed support, not solved frame stress
or an independent total rigid/channel conservation residual. The legacy
support_reaction field still means minus emitted momentum alone.

The native unit oracle compares 25%/75% openings at 1/240 and 1/480 s,
using the same 4 L section and a declared 20 mm head offset. It checks the
continuous drainage solution to one parcel plus Q_initial*dt (the accepted
64 mL quantization and time integration bound), exact reservoir source-energy
debit within 1e-8 J, volume within 1e-12 m³, falling energy within 1e-6 J and
momentum within 1e-8 N s. These are new explicit discretization bounds; no
existing goal or conservation tolerance was relaxed. Native input rejects
non-finite/invalid openings, infinite gravity stores, inconsistent floor
datum, oversized outlets and simultaneously declared metered flow/speed.

For the unimpeded receiver tank at 2 ms after 7 s: 3.968 L emitted and received,
32 mL retained, source energy 44.3757312 J, volume residual zero, falling
energy residual 1.42e-14 J, momentum residual 1.88e-12 N s, reservoir support
impulse [0,-88.94991097,0] N s and moment [48.01388401,0,0] N m s.
The receiver audit duration is seven seconds because falling head slows the
last parcel; its unchanged three-litre lesson goal still happens at 3.983 s.

Equal-geometry material comparison: wheel and tank use glass, oak or iron;
4 L, 75% opening, x=-0.2 m, z=0, mouth y=1.1 m, 4 s duration, 2 cm wheel
solids, precise thin tank compound, 10 cm channel and 4 cm falling parcels.
Rigid dt=1/240 and 1/480 s; water retains its existing acoustic CFL substeps.
Mass comes from the actual volume and material density, with no overrides.

| Material | Final wheel angle, dt=1/240 / 1/480 (degrees) | Water→body work (J) | Falling energy residual (J) | Numerical correction (J) | Wall time (s) |
|---|---:|---:|---:|---:|---:|
| Glass | 126.962 / 129.601 | 4.086 / 4.352 | -5.70e-8 / -7.57e-8 | -0.1238 / -0.1226 | 0.299 / 0.525 |
| Oak | -11.708 / -0.495 | 6.404 / 6.246 | +2.70e-7 / -6.14e-8 | -0.1797 / -0.1910 | 0.277 / 0.485 |
| Iron | 32.617 / 35.849 | 0.728 / 1.024 | -8.36e-8 / +1.64e-7 | -0.1249 / -0.1094 | 0.312 / 0.511 |

All cases retain 0.736 L and report 36.6982944 J source energy. Volume
residual is below 1e-12 m³; maximum momentum residual magnitude is 2.66e-11
N s. Support impulses range -83.089107 to -83.088904 N s vertically, with
moments [44.7931..44.7932,0,16.6178..16.6179] N m s. These conserve the
reported falling parcel system with its explicit pressure/viscous work,
body exchange, contact losses and numerical correction. They do not close
every rigid constraint, bed reaction and hydraulic boundary-work term.
The light oak wheel can reverse after passing thirty degrees, and its final
angle differs by ~11 degrees on halving dt. These contact/parcel dynamics
are experimental, not a steady turbine efficiency or monotonic rotation claim.
No velocity assignment or arbitrary torque was added to make it win.

All new lesson solutions reach their original goals in three whole-apparatus
nudges at the game's dt: pour 1.517/1.867/1.400 s; gate
3.183/4.417/2.733 s; receiver 3.983 s. Closed and 1% taps, missing tanks and
pours missing the wheel along/across the channel fail 0/3. A 5% tap can win
two of three nudges, and the opposite-paddle pour at x=0.3 can rebound and
win one nudge; they are not asserted to fail universally. Either addition
order wins. Seeded v2 tank fills 3.5/4.5/5/5.5 L and river flows
95/105/110/120 L/s pass all three nudges, with no goal/tolerance changes.
Version-1 recipe identities retain the earlier metered apparatus. New authored
construction pars are 771,262,154 / 777,190,154 / 460,651,224 / 593,992,292 J
for pour/gate/receiver/river respectively, each nominal construction plus
the existing 1 kJ margin. River boundary work remains absent from the score.


### October 12 river-lift controls and mechanism preview

The lesson now marks the current and uses **Connect rope to gate** instead of
a list that also offered the fixed guide and foot. The lesson's 65 cm radius
is unchanged; Sandbox still offers wheel sizing and movable drum-load choices.
Goal rise (8 cm), deadline (10 s), native laws and solution remain unchanged.

River rehearsals expose up to 32 existing rotor/load bodies: shape records
travel once, and sampled native poses, unwrapped hinge turn and rope endpoints
travel with flow frames. The renderer moves copies using those measured poses;
it does not assign physical velocity or alter the editable/live setup. The
wheel, rope and gate therefore move alongside water in the explicitly labelled
preview while the real world clock remains ready at zero. This is a pose
preview, not a replay of later fracture geometry. Turn and gate-rise readings
are observations, not new hydraulic power or conservation claims. The fluid
calibration and unsupported conservation laws above still apply.

Browser regression checks the actual rendered poses against native snapshots,
requires gate rise of at least 8 cm and positive rope tension, verifies live
state remains unchanged before Run, and wins through the ordinary controls
on desktop, phone portrait and landscape. Connection toggling and Sandbox
save/reload/restore are also exercised.

Measured verification on the unchanged native executable
`1ebc084656f9b4c0206e6c7ca7f9d0e12546700c60e495781ca781493587c352`:
53/53 game tests in 86.354 s, 14/14 water/launch tests in 37.779 s,
and the final moving-preview/touch-layout test in all three viewports in
50.223 s. The Sandbox save/restore check passes separately in 7.566 s.
The river fixture still measures 0.10870 m peak gate rise, 34.51437° turn,
0.04275 m wound rope and 926.26119 N peak constraint tension at 2 ms. These
are the same calibrated native behaviors; this checkpoint adds observation
and controls. Source registration passes 269/269.


## Timed receiver fill — October 12

The new receiver uses the existing fixed collector geometry centered at
x=0,z=0: 0.8×0.5 m outer plan, 35 cm walls and floor at 25 cm, supported by
real legs/fix joints. Its observation region is 0.72×0.32×0.42 m. A finite
4 L source above it uses the existing 24×24 cm reservoir, nominal 50 mm outlet,
Cd=0.62 and gravity head law. Opening changes flow; falling head reduces it.
The default opening is 10%, with a 100% private solution. No velocities,
volume, goal events or particle contacts are fabricated by the lesson.

The native parcel-center region must retain at least 3 L continuously for
0.5 s, completed by 5 s of simulation time. The earlier cumulative-channel
receipt and six-second goal are retained for v1/v2 shares; current variants
use v3 and the existing initial-fill presets 3.5, 4.5, 5 and 5.5 L. Native
preflight checks all presets without changing the target, deadline or par.

At the 1/240 s game step, 10% retains 0.640 L after 5 s, and 50% retains
2.752 L; neither wins. Three 75% nudges complete at 4.567/4.450/4.333 s;
three 100% nudges complete at 3.483 s. Misplaced full-flow outlets fail.
The UI countdown uses simulation time, and successful fills use the native
goal timestamp. Failed timed runs pause on deadline observation; the legacy
0.3 s UI scoring grace is removed for region-fill goals, without changing
the native goal rule or its acceptance deadline. Successful runs retain their
existing settling interval. Score responses are scoped to their original
session so they cannot pause a newly opened level.

Comparison uses the same box, 4 L source, full opening, five-second run,
20 mm solids and existing 40 mm parcel discretization. Only the collector
material changes. Positions are exported in millimetres; unrounded source
parcel volumes determine the count.

| Box material | Retained L, 1/240 / 1/480 s | Falling energy residual J, 1/240 / 1/480 s | Numerical correction J, 1/240 / 1/480 s |
| --- | ---: | ---: | ---: |
| Glass | 3.968 / 3.968 | −2.607e−8 / −1.360e−8 | +0.32960 / +0.31991 |
| Oak | 3.840 / 3.968 | −6.144e−8 / −3.287e−8 | +0.20170 / +0.31804 |
| Iron | 3.968 / 3.840 | −1.897e−8 / −7.019e−9 | +0.31891 / +0.28027 |

Maximum volume residual magnitude is 5.21e−18 m³; maximum momentum residual
magnitude is 4.25e−10 N s. Initial volume equals emitted plus remaining volume
within the unchanged 1e−12 m³ check. The existing falling-energy limit is
1e−6 J and momentum limit 1e−8 N s; none is loosened. The numerical correction
is separately booked, not relabelled as physical heat or exact conservation.
These are falling-parcel ledger checks, not proof of closed coupled rigid/fluid
conservation or material-specific bucket calibration.

Water resting on the raised box remains a supported falling parcel in the
native ledger; it has not landed in the lower channel, so its channel received
receipt stays zero. The old source/channel ledger test uses the retained v2
fixture and keeps its original assertions. This model does not add movable
liquid vessels, sloshing, a resolved free surface, porous wood absorption or
complete support/contact-work reconciliation. The scene shows native parcels,
not an invented smooth fill surface.

Verification: 16/16 water/launch checks in 47.595 s, 53/53 game checks in
86.638 s, the 18-test seeded suite in 201.128 s, and the additional v3/retained
v1-v2 preset check in 10.589 s. Browser verification covers slow failure,
faster success, countdown/result, reset and both source/box framing on desktop
and phone portrait/landscape, with the diversion lesson in the same run:
2/2 browser checks in 52.085 s.
Native engine SHA-256 is unchanged:
`1ebc084656f9b4c0206e6c7ca7f9d0e12546700c60e495781ca781493587c352`.

## Hollow pipes and scaffolding (October 12)

`scripts/sandbox_plumbing.py` adds straight pipes, horizontal/downward elbows,
reducers and separate scaffolding. The pipe is a precise rigid compound of
twelve tangent box walls per section, 20 mm thick, with material-derived union
mass. Elbows use four chords per 90° bend with internal seam overlap; their
open ends are not extended. Reducers slope their actual walls between two
apertures. These are faceted approximations, not smooth circular swept solids.
The quoted inside radius is the polygon's apothem. Joining separate pieces
leaves 15 mm clearance, rather than creating an invisible fluid connection.

Grounded iron trestles, feet, short mounting screws and native fix joints hold
a supported pipe. Their beams are below the lowest wall in their clipped
footprint, so the support does not occupy the bore. Removing them removes the
fix joints. A separate platform has grounded legs/feet and supports a board
by native contact; the board is not fixed. These are ideal ground-anchored
rigid assemblies, not calibrated load-bearing trusses or buckling/fracture
models. Glass/oak/iron supported boards settle at y=0.620 m and their marble
at 0.680 m; removing the platform leaves the board at y=0.020 m after 1 s.

Native `PreciseRigidScene` now integrates same-density box unions by signed
tetrahedra from the existing clipped exposed boundary. Prefix-union volume
differences preserve earlier-part material ownership. Cylinders and mixed
densities keep their existing bounded overlap sampling. A 1.5 m long,
twelve-sided tube of 120 mm inside radius and 20 mm walls agrees with the
analytical polygon-annulus mass, centroid and axial/transverse inertia, both
unturned and rotated 20°. Glass/oak/iron masses are 62.7001/17.5560/197.380 kg;
relative mass residuals are at most 2.16e-15 and builds took 0.0010–0.0014 s.
The tests also open, drop, snapshot, restore and continue an exact-only world
without a hidden lattice marker. These are geometry/representation checks,
not a full coupled momentum/energy conservation proof.

The water example uses the native finite 4 L gravity reservoir, 65% tap,
1.4 m outlet, a 0.5 m downward elbow starting at 1.3 m, and a 0.5 m reducer
falling 5° from 120 to 80 mm inside radius. The receiving box floor is 0.25 m.
Native 40 mm / 64 mL water parcels have 18 mm contact radius. At 8 s all six
glass/oak/iron comparisons retain 3.968 L; 32 mL remains below the emission
quantum. Turning the elbow 90° misses the receiver and retains less than
0.2 L. Moving the fixed tank vessel clear of a nearby moved outlet prevents
the vessel wall from catching new parcels; default authored tank placements
retain their original vessel position.

| Pipe wall | Step (s) | Water energy residual (J) | Numerical correction (J) | Contact loss (J) | Wall time (s) |
| --- | --- | --- | --- | --- | --- |
| Glass | 1/240 | -7.59e-8 | 0.6381 | 45.8152 | 1.53 |
| Glass | 1/480 | -1.71e-7 | 0.6331 | 46.1353 | 1.87 |
| Oak | 1/240 | -2.89e-7 | 0.6394 | 45.8891 | 1.56 |
| Oak | 1/480 | -1.78e-8 | 0.6346 | 45.9904 | 1.79 |
| Iron | 1/240 | -1.54e-7 | 0.6408 | 45.8548 | 1.54 |
| Iron | 1/480 | +3.59e-8 | 0.6373 | 45.9381 | 1.83 |

Volume residuals are below 5.3e-18 m³ and water momentum residual norms below
9.3e-10 N s. The ledgers include source/gravity impulses, contact transfer,
pressure/viscous work and explicit numerical correction. Fixed reservoir
support reactions remain recorded. The moving pipe/fix/ground system's full
reaction and dissipated-work reconciliation is not established by those water
receipts. The correction and uncalibrated parcel pressure model must not be
presented as calibrated pipe hydraulics.

A separate straight-pipe snapshot comparison starts each glass/oak/iron ball
with zero spin. At 0.5 s, 1/480 s steps, native friction has produced
21.58/21.34/21.58 rad/s spin; measured tangential contact-point slips are
-0.0000010/-0.0000020/-0.0000071 m/s. The contact offset uses the actual
40 mm sphere radius and the 15° floor normal. No no-slip velocity assignment
is used.

The 80 mm ball comparison starts at rest inside a 1.2 m, 20° reducer. Native
contact/friction creates its later motion; no velocity or spin is assigned.
At both 1/240 and 1/480 s, glass/oak/iron balls pass a 90 mm outlet and stop
near x=0.4006 m at a 30 mm outlet. Passing runs' mechanical-energy changes
over 3 s are -3.76/-1.07/-11.83 J at 1/240 s; no mechanical energy increase
was observed. This is a bounded energy observation, not an accounting of every
rolling/contact loss or a closed fluid/ball coupling audit.

Unsupported: sealed pipe pressure/flow networks, calibrated friction factors,
water hammer, pumps, internal valves, leakage seals, resolved free surfaces,
pipe heat/failure, and water drag on a ball inside a pipe. Bore changes alter
real geometry; they do not install a declared hydraulic-resistance law.
Existing authored goals, pars and physical test tolerances are unchanged.
Native engine SHA-256:
`0bcf6978067ec59ab0b89325abb8feef051e398594169c602e664a989e2883a0`.

Verification: 53/53 game checks in 93.996 s; 32/32 electrical checks in
44.846 s; 22/22 water/launch checks (including six plumbing checks) in
60.104 s, plus the new slip check in 0.288 s. Native water, live-world and
precise-rigid CTest targets passed 3/3 in 14.83 s. Plumbing library, bore
adjustments, version save/reload and existing water lessons passed on desktop
and phone portrait/landscape: 3/3 browser checks in 66.662 s.
The additional marble-height and removable-platform browser check passed across all three viewports in 14.710 s.
