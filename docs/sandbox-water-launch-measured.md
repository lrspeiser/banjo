# Fixed water sources and counterweight launchers

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

## What a player can build

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
spray, capillary force, porous absorption or pressure-driven outlet.

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
and **River powers a lift** (connected example). Easy 21 asks the player to
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
