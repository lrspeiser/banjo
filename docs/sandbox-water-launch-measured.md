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
flume. Radius 25–40 cm, location along the channel, left/right/off external
pour, and 0.5–3 L/s metered supply. A bridge carries the feed over the wheel
from a grounded bank post. Clearance adapts to radius so the axle stays at
least 55 mm above the bank; all four offered radii have compose-and-run
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

Final integration verification: all eight Python water/launch tests pass in
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
