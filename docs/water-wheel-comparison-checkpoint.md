# Water-wheel and before/after comparisons — October 8, 2026

## Implementation and usable experiment

Open `http://127.0.0.1:18893/drop.html`, choose **Water / wheel**,
**Prepare / reset**, then **Drop / continue**. A finite 5.12 L column falls
from rest onto an unpowered oak wheel. The declared observation ends at 1.6 s.
Choose left paddles to reverse the input, missed stream or dry control.
Glass and iron wheels are retained mass/inertia comparisons.

This uses the shared `PlatformWorld` host, instance snapshots, bounded native
runner, session/JSONL gateway and WebGL scene. `fluid-wheel-v1` is an explicit
experimental backend; it does not silently turn the axial solid network or
the existing shallow-water river solver into a 3D fluid model. No gameplay
world migration or organic gameplay policy change is included.

Every ball/sheet and wheel selection shows its actual **before** state on the
left and latest **after** state on the right, using the same camera. Initial
poses remain frozen. Connected-piece colors and the wheel's marked yellow
paddle identify real topology/orientation; they do not move bodies apart.
Native receipts retain both complete snapshots and host-tick trajectories.

## Water and wheel model, units and ownership

- 80 parcels, each 0.04³ m³ × 1000 kg/m³ = 0.064 kg; actual native sum is
  5.1200003125 kg (float mass storage). Initially a 4 × 5 × 4 column, zero
  velocity, lowest centres at y = 1.65 m; jet x = ±0.36 m or 0.95 m.
- Experimental weakly compressible SPH: normalized 3D Wendland C2 kernel,
  support 0.10 m; `p = c² max(ρ − ρ₀, 0)`, reduced c = 20 m/s, dynamic
  viscosity 0.001 Pa s. Pressure and radial viscosity forces are paired,
  equal/opposite and central. Viscosity has nonpositive pair power. Pressure
  internal energy uses the matching EOS potential, zero below rest density.
- Jolt owns gravity, wheel hinge, fluid/solid and floor contacts. SPH owns
  fluid/fluid response: their Jolt pair contacts are explicitly disabled.
  There is no duplicate contact, wheel motor, prescribed rotation, trajectory
  animation, arbitrary fragment kick or inlet that creates unaccounted mass.
- Water collision proxies have 18 mm radius. These are parcel/solid contact
  envelopes, not physically rigid cubes of water; parcel represented volume
  drives mass and kernel density. Missing solid boundary density correction
  and coarse sphere envelopes are limitations, not a calibrated fluid surface.
- Wheel: eight 280 × 25 × 35 mm spokes, eight 160 × 35 × 180 mm paddles and
  one 40 mm radius hub; symmetric, radius 480 mm, centre y = 0.65 m. The 17
  parts form one ideal rigid compound with volume-derived mass and rotated
  parallel-axis inertia, on a real free z-axis hinge attached to a fixed post.
  Paddle grain, bending, fracture and attachment failure are unsupported.
- Gravity −9.81 m/s²; host dt 1/240 s (comparison 1/480 s). Substeps use
  0.25 h/c; both host cadences currently share the same 1/960 s internal
  clock. This is a batching comparison, **not** a temporal convergence proof.
  Native solver 48 velocity / 8 position iterations. A CFL measurement at or
  above 0.5 or parcel speed above 30 m/s refuses state admission.

## Measurements and visual assessment

Same geometry, released water and 1.6 s endpoint; only wheel catalog properties
change. Glass density 2500, oak 700, iron 7870 kg/m³ explain the mass/inertia
differences. All wheels are rigid: catalog stiffness is not an implemented
wood, metal or glass constitutive response in this experiment.

| Wheel | Mass kg | Rotation rad | Wheel kinetic J | Contact events | Unseparated energy change J |
|---|---:|---:|---:|---:|---:|
| Glass | 25.7302 | −2.41692 | 6.44639 | 144 | −23.1450 |
| Oak | 7.20446 | −3.80633 | 3.02981 | 146 | −27.3224 |
| Iron | 80.9987 | −0.869122 | 2.77281 | 156 | −26.8778 |

Dry and missed-stream oak controls: exactly zero rotation, wheel energy and
wheel/water contact events. Left-side oak pour: +3.80638 rad, reversing
rotation. Water mass and identities remain unchanged. Pair force/torque sums
are below 1e−12 N / N m in these cases, tested against 1e−10 SI roundoff
bounds. This proves the pair symmetry and meaningful contact-driven response,
not full-system conservation. Peak density reaches 1104–1222 kg/m³ and Mach
0.49: compressibility is too high to claim realistic incompressible water.

**How it looks:** wheel motion follows water arrival, and the marked paddle
makes rotation visible. That agrees with the intended momentum-transfer test.
Water still looks like coarse parcels rather than a calibrated stream/puddle.
Some splash parcels escape the finite floor. A longer exploratory run reached
the CFL refusal around 3.61 s after escaped parcels accelerated in free fall.
That failure is retained as a boundary/outflow gate. Native and UI now admit
only the explicitly tested 1.6 s experiment, preserve its valid final state
and refuse continuation without inventing settling or hiding lost water.

The solid drop comparison also reports the distinction between observed and
expected appearance:

- The glass sheet breaks 44 bonds but stays one connected piece, with only
  0.5 mm maximum cell travel. It does **not** show scattered shards. The glass
  ball comparison has seven connected pieces, colored by actual topology;
  its early view does not establish settled scattering either.
- The iron sheet records zero plastic work in the iron-ball comparison; the
  iron ball records 57.394 J. A visibly dented plate has **not** been shown.
  Early shifted cells are not proof of that dent; unloading, bending and a
  later observation are required. The UI distinguishes ball from sheet.
- Intact or elastically displaced cells are reported as no measured permanent
  damage. Rigid baseline mode explicitly cannot fracture or dent.

Actual browser before/after images:
[water wheel](evidence/material-lab/water-wheel-before-after-20261008.png),
[glass sheet](evidence/material-lab/glass-sheet-before-after-20261008.png),
[iron sheet](evidence/material-lab/iron-sheet-before-after-20261008.png).
[Native water declarations and paired states](evidence/material-lab/water-wheel-results-20261008.json)
include the binary fingerprint and per-material accounts.

Energy change above includes unseparated native contact, support and numerical
losses. SPH pressure potential and radial viscous work are recorded. Total
Gravity impulse/moment and inferred support/contact P/L transfers are also
recorded, but those inferred terms are not an independent conservation audit.
`energy_residual_j` stays null and `release_ready` stays false.

## Verification and remaining gates

Windows 10.0.26200 / MSVC Release in `build/local-cell-tools`.
The registered native drop, water-wheel, sheet-gateway and platform suites pass
(4/4, 34.60 s). Native binary SHA256:
`5c39522c80312381274c376a075d1d3f74685835fb1a59bf9c553bccbbee0c64`.
Water tests include actual contacts, retained particle mass/identity, three
material comparisons, dry/missed/mirrored controls, duration refusal, and
kernel normalization plus initial density/EOS energy oracles. The HTTP test
runner executes the actual binary and verifies its SHA256. Node explanation
checks consume actual native before/after records; they reject incomplete
state and distinguish fracture, plasticity, dry and contact-driven outcomes.
These are scoped checks, not full regression or physical-phone acceptance.
The registered explanation test requests fresh drop/water fixture runs when
selected by itself (3/3 including setup, 34.16 s), rejects an empty comparison
set, and the named HTTP checks pass (2 tests, 8.742 s). Source registration
is 324/324; TypeScript compilation and JavaScript/Python syntax checks pass.

Next: independent full contact/hinge/floor E/P/L accounting, bounded outflow or
a physical basin for longer pours, fluid resolution/internal timestep
refinement, realistic compressibility and boundary treatment. Separately,
solid finite-cell bending and useful later-time unloading/scattering remain
open in the [shared drop plan](shared-drop-world-checkpoint.md).
