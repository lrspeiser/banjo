# Controlled coupled contact — October 7, 2026

## Scope and implementation

Source baseline: main `342d2781339e431ecaf272f95f2427b68ddae3ee`. Windows x64,
MSVC Release, Jolt double positions, separate build `build/local-cell-tools`.
This continues the [reversible variable step](variable-contact-step-checkpoint.md)
and the full [live world objective](world-physics-action-plan.md). The controller
is an experimental CPU reference. Its sustained acceptance gate fails; it is not
installed in the live sandbox or saved gameplay.

`advanceNativeFixedTargetControlled` compares one full step with two half steps
from the same current paired native/material state. The full trial always rolls
back. An accepted fine trial commits exactly two actual substeps; a refused trial
commits none. Disagreement halves the proposed interval within declared time and
refinement budgets. The result returns accepted receipts, suggested next interval,
topology agreement and the largest normalized error/metric. Nothing chooses a
response by material name, scene ID or recorded outcome.

Comparison covers material displacement/velocity, damage, plastic extension and
strain, strain histories, exact surviving bonds/failure modes; every participating
native body's position, orientation and linear/angular velocity; and individual
external/contact/support/numerical work and impulse accounts. `u_prev` samples
different physical times in full and half steps, so it is preserved by rollback
but is not directly equated across those different discretizations. Comparing
one interval does not establish a global error bound or calibrated material law.

The controller owns native and target stepping. Native body inventory is sorted
and read-only; parked bodies do not participate. A callback that advances the
native world is detected and its trial rolls back. Callback exceptions, malformed
audits and invalid bounds/budgets also refuse. Callback receipts must remain
provisional and external controller histories must not be mutated. Existing
finite queued loads refuse changed durations; physical-time actuator scheduling
and actor/hand history journaling remain separate work.

The reference permits up to 1,024 target nodes, 65,536 bonds, 2,048 participating
native bodies and 20 halvings, subject to existing paired 16 MiB state budgets.
Default local comparison bounds are explicitly declared: 1e-8 m position,
1e-4 m/s velocity, 1e-5 rad orientation, 1e-4 rad/s angular velocity, 1e-5 damage/
strain histories, 1e-8 m plastic extension, 1e-6 J energy, 1e-6 N s impulse and
1e-7 kg m²/s angular impulse. Minimum substep is 1 ps; default refinement budget
is 12. These are new experimental numerical comparison settings, not changes to
the existing contact-law or strict fracture/refinement acceptance bounds.

## Removed redundant response

Native manifold preparation formerly called isolated point-contact preparation
to collect ownership, tree, shape and attachment information. That operation
also solved and audited a different first-witness response. Assembly metadata
inspection is now shared independently; point preparation evaluates its point,
and manifold preparation evaluates its actual coupled manifold. Both retain
current identities, epochs, shapes, native attachment checks and roundoff budgets.

A material-neutral symmetric oracle reproduces the difference: opposing affine
nodal velocities act at two actual source faces. The isolated first witness
refuses a 1e-12 SI native roundoff budget, while the simultaneous pair has zero
net source kick and meets that same budget. Both contact orders admit the same
coupled nodal velocities. This is an analytical admission regression, not a
fracture or general material-realism claim. The sustained small-step refusal
below remains, including an audit inside the actual contact solve.

## Matched short contact evidence

Glass/oak/iron use the same 40 mm cells, 80 mm eight-node target, finite iron
head/oak laboratory handle, initial velocity (6, 0.2, 0.1) m/s, no gravity or
damping and existing axial elastic/plastic/failure laws. Catalog density/stiffness
are glass 2,500 kg/m³ / 70 GPa, oak 700 / 12 GPa and iron 7,870 / 211 GPa. Oak
remains a comparison laboratory material; grain/organic gameplay are unsupported.

| Material | Target mass (kg) | Accepted interval (ns) | Full/fine attempts | Normalized disagreement |
| --- | --- | --- | --- | --- |
| Glass | 1.28 | 12.5 | 4 | 0.0103342 |
| Oak | 0.3584 | 25 | 3 | 0.0059510 |
| Iron | 4.02944 | 12.5 | 4 | 0.0372377 |

Each result commits only two half steps and preserves declared mass. Maximum
attributed residuals are 1.22e-14 N s, 1.72e-17 kg m²/s and 1.03e-14 J. Attribution
includes measured native stepping, contact roundoff/reconciliation, fixing
geometry couple, target bond correction and existing numerical/material losses.
Existing test bounds of 1e-9 for momentum/angular attribution and 1e-10 J energy
remain. This paired reference does not qualify full-world conservation.

Strict new bounds deliberately exhaust one trial and confirm unchanged histories,
status and both clocks. A second-half exception rolls back the first half too.
Native double stepping, negative dissipation, nonfinite accuracy, excessive
refinement and changed finite-force duration refuse. Existing variable-step
glass/oak/iron freefall and rollback oracles still pass.

## Sustained gate and measured limit

The separate `--controlled-manifold` command uses the earlier 120 mm/27-node
target, nine far-face clamps, two head widths and intended 204.8 µs duration.
It allows all 20 halvings down to the 1 ps minimum and at most 100,000 accepted
intervals. Six cases currently fail before reaching the first fracture event:

| Material / width | Accepted time (µs) | Accepted intervals | Refusal |
| --- | --- | --- | --- |
| Glass / 40 mm | 5.946875 | 930 | Contact-transfer accuracy |
| Oak / 40 mm | 5.850931 | 415 | Contact-transfer accuracy |
| Iron / 40 mm | 0.1 | 2 | Native position accuracy |
| Glass / 120 mm | 5.78125 | 217 | Contact-transfer accuracy |
| Oak / 120 mm | 6.1 | 112 | Point-rigid work/velocity audit inside contact |
| Iron / 120 mm | 5.95 | 230 | Contact-transfer accuracy |

All six retain zero broken bonds, their last accepted state and mass. Maximum
attributed residuals are 1.35e-14 N s, 1.26e-16 kg m²/s and 3.43e-12 J. Accepted
integration error spans 4.09e-8 to 4.53e-5 J. Measured case wall times are roughly
0.01–0.43 s for these incomplete runs; this is not a realtime or digging-speed
qualification. Contact disagreement remains above the declared numerical bounds;
no tolerance is enlarged or minimum-step result forced through.

From each stopped state, separate full/two-half trials apply no new contact
impulse and roll back afterward. Reducing the interval from 100 ps to 1 ps leaves
native position disagreement nearly flat, approximately 0.8–11 nm across the six
states. Narrow iron remains 11.0026/10.9956 nm, beyond the declared 10 nm bound;
its native velocity disagreement is zero at those two intervals. Other native
velocity differences reach 1.7e-8 m/s. This isolates an existing native stepping
floor from the contact callback, but does not identify one sole cause for every
contact-work refusal.

Local Jolt source inspection confirms that SaveState/RestoreState retain the
previous timestep used to scale warm-start impulses, and Banjo's trial restores
its last timestep/configuration. Fixed-constraint position projection runs per
native step. Those observations motivate checking attachment/rotation precision
and projection consistency; they are not proof that disabling projection would
be a valid physical repair. Jolt iterations and position correction are unchanged.

## Verification and next work

Ten rebuilt scoped CTest entries pass in 49.51 s, including the new controller
and simultaneous-admission oracles. The original strict coupled command still
returns failure for its narrow-glass topology comparison (19/7 broken bonds).
The controlled sustained command returns failure with six open gates, including
after removing redundant first-witness preparation. Its exception output has no
stale comparison value: the failed contact audit is reported directly. Source
registration remains 315/315. PR #2 is freshly merged at `138260d2`; its pinned
contact note was reread. Publication revision is recorded in Git/user report.
Large logs remain ignored under `build/material-lab/`.

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_material_surface_contact_tests banjo_fixed_assembly_contact_tests banjo_native_point_contact_tests banjo_native_lattice_contact_tests banjo_fast_lattice_tests banjo_lattice_external_load_tests banjo_lattice_plasticity_tests banjo_lattice_verlet_tests --parallel 4
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --manifold-oracles-only
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --controlled-manifold
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --coupled-manifold --require-live-contact-convergence
ctest --test-dir build/local-cell-tools -C Release -R 'banjo_(material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|fixed_assembly_contact_tests|native_lattice_contact_tests|native_point_contact_tests|fast_lattice_tests|lattice_external_load_tests|lattice_plasticity_tests|lattice_verlet_tests)$' --output-on-failure
python scripts/check-source-registration.py
```

Next: capture/refine native fixing attachment and quaternion/projection error,
and isolate the actual small-step point-law audit. Preserve reactions and work
while making coupled contact/constraint continuation consistent; repeat all six
material/width conditions through fracture and the original strict gate. Then qualify
ordinary tool use, connected/fractured matter continuation, finite surrounding
terrain and actor accounts before installing live fracture. Useful speed,
durability, UI/phone acceptance, other constitutive laws and the complete physics
objective remain open. No full-suite, normal interactive, phone, cross-platform
or completed free-form-world claim is made. Running demos and saved worlds are
unchanged.
