# Contact at Verlet force boundaries — October 7, 2026

## Scope and implementation

Baseline main `1983adafb56696cd113e4f44dc85036dcc0bd8c5`, Windows x64,
MSVC Release and pinned Jolt v5.6.0. PR #2 is merged at `138260d2`; its
[conservative checkpoint](contact-checkpoint.md) remains the earlier boundary.
This implements the next repair from the [phase investigation](contact-phase-checkpoint.md).
The complete [live world objective](world-physics-action-plan.md) remains active.

`advanceCoupledContactStep` adds a bounded, serial-double CPU reference:

1. Actual external/gravity/internal force half-kicks.
2. `BeforeDrift` contact, then one native source step.
3. Actual material drift and remaining forces/damping.
4. `AfterForces` contact, then material damage/failure/history update.

One material step consumes one finite-load substep and advances physical time
once. Source stepping occurs once between projections. Queries use the actual
current geometry and material state at each phase; this introduces no stored
contact geometry or outcome reuse. Contact work performed inside the integrator
is subtracted from the numerical integration ledger, alongside external/gravity
work. It is not falsely reported as integration error.

`NativeContactComposition::VerletForceBoundaries` selects this experimental path.
The default remains `BeforeForces`. Float, parallel and XPBD backends refuse the
new API. Callbacks cannot run/reenter the material backend, upload/reset it, or
replace its finite force/wrench schedule. The paired native/material trial owns
both phases, actual clocks, histories, captures and ledgers; exceptions restore
them together. No constitutive/contact law, strength, acceptance bound, outcome
format/model key or running world changes. The controller does not use an outcome
cache; a future cached algorithm must include its composition in the complete key.

## Analytical and native verification

Glass, oak and iron share a 40 mm-cell, 80 mm target for the analytical fixture,
at dt = 100 ns. It starts at the origin to avoid an unrelated translated rest-edge
roundoff impulse. External acceleration is 2 m/s² in x, gravity −9.81 m/s² in y.
An ideal stationary inelastic constraint removes each actual half-kick before
drift. Expected displacement is zero; reaction impulse is −M a dt; contact work
is −M |a|² dt² / 4, exactly opposing the measured force work. Work balances and
integration-error checks retain a 1e-24 J oracle bound. This is an analytical
constraint test, not a new game contact preset or material failure claim.

False trials and exceptions at both phases restore load duration, material
history, native/source and material clocks, transfer counts and work. Admission
tests cover empty callbacks, nonfinite/nonpositive/oversized horizons, queued
loads, recursive calls, upload and unsupported backends. Actual native source
contact tests compare both compositions under all three materials; failures at
the full and half-step contact phases restore the real contacted states.

In the continuous-small-rotation build, short force-boundary contacts accept
100 ns for glass, 50 ns for oak and 25 ns
for iron, compared with 12.5 / 25 / 12.5 ns in the preceding composition. Each
accepted interval commits two half steps with complete source/target/support
reaction and numerical accounts. The largest force-boundary short-contact
attributed energy residual is 1.54e-14 J. This qualifies that bounded experiment,
not sustained fracture or full gameplay conservation. The default rotation build
accepts 100 / 50 / 50 ns, with maximum attributed energy residual 2.06e-14 J.

Twelve rebuilt scoped CTest entries pass in both builds: default 44.19 s,
continuous-small-rotation 43.71 s. They include Verlet, finite loads, constituent
partition/patch, native/lattice contact, material surface/manifold and outcome
compatibility. Source registration is 315/315 across 31 CMake files. After the
last diagnostic-only test edit, the executable is rebuilt in both directories;
the final controlled command reruns the current analytical/native oracles.

## Sustained acceptance remains failed

The retained experiment uses 40 mm cells, a 120 mm / 27-node target, nine far-face
clamps, iron heads of 40/120 mm width, the laboratory oak handle, initial source
velocity (6, 0.2, 0.1) m/s, and no gravity/damping. Target masses are glass 4.32 kg,
oak 1.2096 kg and iron 13.59936 kg. Catalog density/stiffness remains glass
2500 kg/m³ / 70 GPa, oak 700 / 12 GPa and iron 7870 / 211 GPa. Oak remains an
uncalibrated laboratory comparison; no organic gameplay or grain model is added.

The diagnostic interval limit is explicit (`1..100000`, default still 100000).
Exhausting it is a failure, not success at a shorter duration. The required
physical interval remains **204.8 µs**, and all work/state/topology bounds remain.

| Material | Head | 500-interval stopping time | 2000-interval stopping time | Broken bonds |
|---|---:|---:|---:|---:|
| Glass | 40 mm | 6.395776 µs | 6.617700 µs | 0 |
| Oak | 40 mm | 6.391754 µs | 6.400909 µs | 0 |
| Iron | 40 mm | 7.747852 µs | 10.091602 µs | 0 |
| Glass | 120 mm | 5.900430 µs | 5.905008 µs | 0 |
| Oak | 120 mm | 6.596094 µs | 6.889063 µs | 0 |
| Iron | 120 mm | 6.123828 µs | 6.123828 µs | 0 |

The 2000-interval broad oak experiment costs 191.79 s. Five cases exhaust that
budget; broad iron refuses after 383 intervals. Its final source contact
correction differs by **13.4059 µJ** between full and half trials at a 3.05176 ps
comparison interval, against the retained **1 µJ** bound. This source rounding
account must be resolved, not hidden as contact loss. Native velocity/spin remain
float despite double native positions and double material integration.

Across those six preliminary runs, attributed P/L/E residual maxima are
1.57e-14 N s / 1.33e-16 kg m²/s / 4.63e-12 J, inside the existing 1e-9 SI /
1e-10 J attribution bounds. Integration error is explicitly retained separately.
These residuals explain the numerical transfers; they do not establish physical
conservation, calibrated fracture, useful speed or a realistic material law.

The final 500-interval run retains phase-aware full/two-half traces at 100/10/1 ns,
100/1 ps, plus rollback-only source/geometry isolations. The
[measured rows and executable fingerprint](evidence/material-lab/force-boundary-results-20261007.json)
distinguish these from the earlier 2000-interval diagnostic executable.
Large raw traces remain ignored under `build/material-lab/`.

At each final stopped state, actual phase-aware rollback trials show the following
full-minus-two-half target work magnitudes. Reducing the interval tenfold reduces
this error approximately one hundredfold, consistent with second-order contact/
force composition over this measured range. At smaller intervals source rounding
noise becomes visible. This is a local refinement result, not proof of global
trajectory convergence or permission to omit the failed sustained gate.

| Material | Head | Error at 100 ns | Error at 10 ns | Reduction |
|---|---:|---:|---:|---:|
| Glass | 40 mm | 773.590 µJ | 7.352 µJ | 105.22× |
| Oak | 40 mm | 120.676 µJ | 1.156 µJ | 104.39× |
| Iron | 40 mm | 703.723 µJ | 7.208 µJ | 97.63× |
| Glass | 120 mm | 1095.477 µJ | 10.761 µJ | 101.80× |
| Oak | 120 mm | 143.799 µJ | 1.421 µJ | 101.19× |
| Iron | 120 mm | 1690.096 µJ | 17.239 µJ | 98.04× |

## Reproduce

```powershell
cmake --build build/agent-point-separation --config Release --target banjo_material_surface_contact_tests banjo_native_point_contact_tests banjo_fixed_assembly_contact_tests banjo_point_rigid_contact_tests banjo_native_lattice_contact_tests banjo_outcome_tests banjo_lattice_verlet_tests banjo_lattice_external_load_tests banjo_solid_matter_patch_tests banjo_constituent_partition_tests --parallel 4
ctest --test-dir build/agent-point-separation -C Release -R 'banjo_(point_rigid_contact_tests|fixed_assembly_contact_tests|native_point_contact_tests|native_lattice_contact_tests|material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|outcome_tests|lattice_verlet_tests|lattice_external_load_tests|solid_matter_patch_tests|constituent_partition_tests)$' --output-on-failure
build/agent-point-separation/Release/banjo_material_surface_contact_tests.exe --controlled-manifold --face-patches --force-boundary-contact --controlled-interval-limit 500
python scripts/check-source-registration.py
```

The controlled command exits **1**. This experimental checkpoint explicitly
retains that failure; it is not enabled as the live-world solver. The default
build repeats the same scoped CTest command in `build/local-cell-tools`. This is
not the full repository regression, interactive-loop or phone qualification.
No browser change or sandbox/saved-world reset is included. Main publication is
recorded in Git and the user report.

## Next implementation

Use the phase-aware comparisons to separate discretization from native source
representability. Implement an authoritative double CPU reference for source
velocity/spin and coupled forces/constraints, with explicit collision/render
projection boundaries and physical-state ownership. Qualify its actual joint
reactions, mass/inertia, contact-point slip, clocks and P/L/E transfers before
selecting it. Do not merely write unrounded candidates over float native state
or silently reinterpret float rounding as a constitutive loss.

Then qualify sustained contact through intrinsic fracture, transfer unchanged
constituents to physical fragments and connect ordinary free-form tool actions
to that persistent world. Deformation/structures/mechanisms and water/heat/energy/
pressure remain required stages of the same full objective, not alternate goals.
