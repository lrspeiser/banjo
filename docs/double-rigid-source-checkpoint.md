# Double CPU rigid source — October 7, 2026

## Scope and ownership

Experimental CPU implementation from main `e50172c1b5f27f3ad5b911ef02d0b30cdfb3b8a7`,
Windows x64 / MSVC Release, default Jolt rotation configuration. This implements
the next foundation identified by the [force-boundary experiment](force-boundary-contact-checkpoint.md):
native float velocity/spin limits sustained contact-work refinement. The complete
[live world physics objective](world-physics-action-plan.md) remains active.

`DoubleRigidState` owns double mass, body-frame inertia, world position,
orientation, linear velocity and **world spin angular momentum**. Angular velocity
is derived from physical inertia and orientation. No native body is stepped or
written by this lane; native collision/render geometry is not its physics state.
The ordinary running sandbox still uses the existing native rigid-body path.

Free rotation uses a symmetric composition of exact rank-one kinetic Hamiltonian
flows. Cholesky columns of inverse body inertia define each term; its axis
projection of body angular momentum stays constant during that term's rotation.
This extends the existing principal-axis algorithm to a general SPD tensor,
without a new eigen dependency, constant-spin approximation or angular dead
zone. World spin momentum is retained; orientation normalization removes only
quaternion roundoff. Resulting energy error is measured as numerical error,
never assigned to contact heat or a material fracture law. Signed free intervals
support reversal, with finite absolute duration <= 1 s and each axis rotation
<= 0.25 rad; larger rotations refuse and require refinement. Tensor admission
retains the shared contact tensor's symmetry/conditioning bounds.

The standalone cohesive rigid-pair/patch solver now uses this shared rotation
helper. Its physical laws and error budgets stay unchanged; the cohesive and
Creator tests are rebuilt and rerun because this changes its numerical code.

`DoubleFixedSource` owns a bounded ideal rigid fixed tree (1..256 members).
Mass/inertia comes from the supplied physical states, not material names.
Member geometry, relative orientations and fixing positions rotate with the
compound. This is an ideal rigid assembly, not separate compliant/failing joints.
Initial relative velocity is reconciled through the existing fixed-tree solve
with explicit loss and fixing reactions. Import requires exactly coincident
anchors; drifted/native anchors are refused rather than silently snapped.
Import is not an audited native-to-CPU representation transition yet.

Point impulses and free angular impulses apply actual aggregate force/moment
and signed kinetic work. The existing fixed-tree reaction auditor then reports
the actual member/fixing impulses at unchanged physical geometry. There is no
ongoing rolling/no-slip assignment, hand-pose servo, fragment launch velocity,
damage assignment or shatter animation. Free compound motion preserves relative
geometry; no positional constraint correction is hidden as energy loss.

## Material coupling

`DoubleFixedContact` applies the **existing** simultaneous Coulomb manifold law
to the CPU source and the serial-double material backend. Current surviving
material bonds select each support; union/witness/node budgets remain <= 64.
All candidate source geometry/mass/velocity and target ledgers are preflighted
before an atomic target commit and a no-throw move of the prepared source.
Source contact projection roundoff is measured separately from physical loss.
Preflight bounds are the existing absolute 1e-9 N s / kg m² s⁻¹ and 1e-10 J.
No material/contact strength, acceptance bound or default native path changes.

One paired step does:

1. Target half forces, actual source half-wrench impulses, contact.
2. CPU source free drift and target material drift/final forces.
3. Source half-wrench impulses, contact, then target damage/history.

Up to 256 source wrenches declare member-local application points, constant
world forces and independent world couples, in SI. Their signed work and fixing
reactions are retained. These are trusted reference external loads, not player
energy grants or a calibrated human actuator. Source/target absolute clocks
must agree and be able to advance the requested interval. Both advance once;
false trials and exceptions restore source state/clock and target state,
history, queued loads, captures and ledgers. Callbacks cannot advance the source
clock or recursively advance/reset the material backend.

Geometry witnesses still come from a trusted host. This checkpoint recomputes a
declared touching box face from the actual CPU pose; it does **not** implement
native shape queries at that pose, swept contact discovery, automatic paired
accuracy control or reuse of a stored fracture outcome. No cache is used by this
API. A future cached solver must identify this distinct source/integration model
and complete state; existing native outcome model keys remain applicable only
to their unchanged native algorithms.

## Measured verification

[Machine-readable results and executable/source fingerprints](evidence/material-lab/double-rigid-source-results-20261007.json).

Analytical tests cover exact principal-axis rotation/translation, a 1e-8 rad
rotation without the native dead zone, non-diagonal inertia, signed reversal,
point-impulse work, actual fixing reactions and uniform-gravity free fall.
Non-diagonal free rotation over 0.2 s is compared with a 3200-step reference:

| dt | Orientation error (quaternion chord) | Signed energy error |
|---|---:|---:|
| 0.01 s | 2.39377e-5 | -1.19446e-3 J |
| 0.005 s | 5.98350e-6 | -2.98568e-4 J |
| 0.0025 s | 1.49516e-6 | -7.46390e-5 J |

Error decreases about fourfold on each halving; free world angular momentum
residual is <= 5.70e-14 kg m²/s. Reversal error is <= 5e-14 quaternion chord.
This is approximate second-order dynamics with an explicit energy error, not
exact kinetic conservation. Glass/oak/iron head assemblies preserve spacing
through 1000 steps at 0.1 ms and retain member spin/orbital momentum; the largest
measured assembly angular residual is 8.65e-15 kg m²/s. The same 10 ms uniform
gravity experiment gives the analytical displacement/velocity and work for all
three masses; density changes weight/work, not gravitational acceleration.

The short material fixture uses a 40 mm cell / 80 mm cube (eight nodes), an
80 mm iron head and a 240 x 40 x 40 mm laboratory oak handle, initial source
velocity (6, 0.2, 0.1) m/s, and dt = 100 ns. Head/handle source mass is
4.29824 kg. Target density/stiffness remains glass 2500 kg/m³ / 70 GPa, oak
700 / 12 GPa, iron 7870 / 211 GPa. The existing axial lattice law is retained;
oak is an uncalibrated laboratory comparison, not gameplay wood, grain or
brittle-material realism, and this adds no constitutive iron plasticity model.
Two matched conditions per material: no fields; then uniform gravity plus
an actual handle force (1,2,3) N at local (0.02,0.01,0) m and free couple
(0,0.001,0) N m. Damping is zero.

| Target | Mass | Largest attributed energy residual across the two conditions |
|---|---:|---:|
| Glass | 1.28 kg | 3.37174e-14 J |
| Oak | 0.3584 kg | 3.42919e-14 J |
| Iron | 4.02944 kg | 4.71062e-14 J |

Across all six short cases, largest attributed P/L residuals are
1.07137e-14 N s / 1.05794e-17 kg m²/s. Source projection energy roundoff is
<= 2.84217e-14 J. Full source-plus-material measurements include signed external
work/impulses, material bond roundoff, numerical drift/integration error and
applicable material losses; these are not merely pairwise or mass-sum checks.
Each case has two active contact phases and **zero broken bonds**. Observed
whole short-step/report costs are 38–64 microseconds for 0.1 microseconds of
physical time, excluding collision discovery. This is not gameplay speed.

Both contact-phase exceptions, deliberate false trials, a callback that advances
the source, invalid absolute clocks, unsupported float backend, malformed late
contact law, invalid source wrench/member, changed mass/pose, incompatible
fixed velocities and drifted anchors are refused without partial state writes.
The first global-energy assertion exposed a test-fixture error: backend download
updates dynamic fields, so its static mass/geometry must be retained from upload.
The fixture was repaired; the 1e-10 J bound was not increased.

Fifteen rebuilt focused CTest entries pass in 53.35 s, including the new source,
cohesive rigid, Creator, fixed/point/native/material contact, Verlet, external
loads, constituent/patch and outcome tests. Source registration is **319/319**
across 31 CMake files. This is Windows-only scoped verification; no full suite,
new browser installation, normal interactive-window or physical-phone result
is claimed by this checkpoint. No rendering/input loop changes.

## Remaining work and exact next gate

The six sustained native/contact failures in the preceding checkpoint stay
open and are not rerun or declared fixed by these short CPU cases. The previous
13.4059 microjoule full/half source discrepancy is not yet replayed through this
new source. The ordinary 3D world remains pickup plus rigid collision; intrinsic
fracture/debris, useful sustained digging and the full world objective are
unfinished.

1. Add explicit read-only native shape queries at **CPU-authoritative** current
   member poses, with audited geometry/import identities and no second native
   dynamics owner. Refuse drifted anchor imports until a measured transition
   is implemented; preserve native joints/pair coverage and material mass.
2. Extend paired full/two-half accuracy selection to CPU source + material,
   complete external/source/target ledgers, exact topology and equal elapsed
   time. Replay the captured failing source state and all six sustained cases
   under unchanged bounds.
3. Qualify actual fracture and persistent constituent debris through ordinary
   player actions in the same 3D world, then combine subsequent stages.
   Deformation/structures/mechanisms and water/heat/energy/pressure remain required.

Reproduce the new reference:

```powershell
cmake --build build/local-cell-tools --config Release --parallel 4 --target banjo_double_rigid_source_tests
./build/local-cell-tools/Release/banjo_double_rigid_source_tests.exe
ctest --test-dir build/local-cell-tools -C Release -R '^banjo_double_rigid_source_tests$' --output-on-failure
python scripts/check-source-registration.py
```

Use the repository's separate-build configuration for a fresh checkout. Exact
publication revision is recorded in Git and the checkpoint report; binaries,
logs and environment secrets remain outside commits.
