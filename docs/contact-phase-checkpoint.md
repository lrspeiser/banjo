# Contact phase and source precision — October 7, 2026

## Scope

Baseline main `8cc32294625eb5f770538657daf0b1a6e48214a1`, Windows x64,
MSVC Release, pinned Jolt v5.6.0, double positions and the experimental continuous
small-rotation build (solver model 8). PR #2 is merged at `138260d2`; its pinned
contact checkpoint was reread. This continues the
[native face checkpoint](native-face-contact-checkpoint.md) toward the full
[world objective](world-physics-action-plan.md).

Implemented: native manifold receipts retain actual joint IDs and attachment
witnesses, matched rollback diagnostics and a registered unrounded zero-time
reapplication oracle. Measured: the main small-step discrepancy in these six
states comes from material force advancement between contact projections.
**No integration repair or playable fracture is claimed.** Numerical laws,
acceptance bounds, outcome versions and running worlds remain unchanged.

## Authoritative source metadata

`FixedSurfaceManifoldKick` now carries `joint_ids` and `links`, matching the
existing point-contact receipt. They come directly from native assembly
inspection and preserve the order of reconciliation/contact reaction receipts.
This exposes the actual force-transfer path rather than leaving consumers with
unidentified joint reactions. The six initial glass/oak/iron face-impact oracles
verify two source bodies, one native fixing and its attachment identity.

Those registered cases also reapply the same complete contact equations to the
unrounded candidate states without elapsed time. Target work must remain below
the new 1e-8 J idempotence oracle bound. This is a numerical oracle bound, not a
relaxation of the existing 1e-10 J whole-impact accounting check or the 1 µJ
adaptive work comparison. No unrounded candidate is written into native state.

## Paired operator isolation

At each of the six actual sustained-contact refusals, the test runs four
rollback-only, two-contact experiments with the same queried face geometry:

1. Advance neither system between projections.
2. Advance only native constraints by 0.5 ps between projections.
3. Advance only material forces/drift by 0.5 ps between projections.
4. Advance both by 0.5 ps between projections.

All 24 finish without diagnostic errors. Native-only advancement changes the
second target-work result by at most **3.31951e-10 J** relative to the corresponding
no-native experiment. By comparison, material-only advancement produces second
target work from 3.53509e-7 to 2.02695e-6 J. Native joint stepping is not the main
cause of these work comparisons. It does not follow that native joints are
universally accurate or qualified.

All queried gaps must be within their contact margin, so the diagnostic cannot
alter a predictive restitution horizon. Native/mechanical transfers and actual
clock/history rollback are checked. Frozen witnesses are an isolation instrument,
never a moving-world geometry cache or an accepted production contact step.

## Source rounding comparison

For each refused state, apply its actual full contact once, then advance material
forces by 0, 0.5 or 50 ps, without native stepping. Re-evaluate the same current
material nodes and captured geometry twice:

- with the first solve's unrounded double source candidate;
- with its actual native delivered source velocities.

Both evaluations use the same declared masses, symmetric inertia, actual native
attachment witnesses, support indices and Coulomb equations. Only source
velocity/spin rounding differs. Both are pure diagnostic evaluations; neither
second result is committed. Topology changes refuse the isolation, and every
trial restores target displacement, previous displacement, velocity, damage,
alive state and both clocks.

All 18 evaluations finish. At zero elapsed time the unrounded reapplication has
at most **2.43294e-12 J** target work. Source velocity rounding is 2.90e-8 to
1.11e-7 m/s; its zero-time target-work effect reaches 2.52466e-7 J. This is a real
numerical contribution, but does not explain the dominant force-interval scaling:

| Target | Head width | Unrounded work after 0.5 ps (J) | Unrounded work after 50 ps (J) | Work ratio |
|---|---:|---:|---:|---:|
| Glass | 40 mm | 9.078395e-7 | 9.078283e-5 | 99.998760 |
| Oak | 40 mm | 3.253687e-7 | 3.253689e-5 | 100.000054 |
| Iron | 40 mm | 6.117245e-7 | 6.117162e-5 | 99.998644 |
| Glass | 120 mm | 1.687523e-6 | 1.687515e-4 | 99.999574 |
| Oak | 120 mm | 3.725869e-7 | 3.725872e-5 | 100.000079 |
| Iron | 120 mm | 2.288853e-6 | 2.288840e-4 | 99.999430 |

The 100× interval gives essentially 100× work. The present controller projects
contact before a full material force/drift update. Its two-half trial contains
another force-driven contact impulse that the full trial lacks. This identifies
a first-order contact/force composition discrepancy in these states; improving
source precision alone cannot repair it. The largest pure whole-response work
residual across both source choices is 4.12751e-14 J. That is instantaneous
accounting, not full-pipeline conservation or constitutive material validation.

The retained experiment uses 40 mm cells, a 120 mm / 27-node target, nine far-face
clamps, 40/120 mm iron heads, a laboratory oak handle, initial velocity
(6, 0.2, 0.1) m/s and no gravity/damping. Target masses remain glass 4.32 kg, oak
1.2096 kg and iron 13.59936 kg. Catalog density/stiffness is 2500 kg/m³ / 70 GPa,
700 / 12 GPa and 7870 / 211 GPa. No oak grain, calibrated wood failure, iron
plasticity or gameplay organic material is introduced.

[Measured rows and executable fingerprint](evidence/material-lab/contact-phase-results-20261007.json)
retain successful diagnostics and rejected-prototype scope. Large traces remain
ignored under `build/material-lab/`; rerun the command below to regenerate them.

## Rejected endpoint prototype

A temporary before-step-plus-endpoint contact composition was implemented and
compiled. It retained all original work/state/topology bounds and actual transfer
accounts, and added no elapsed time for the endpoint projection. It consumed
**371.61 CPU seconds without completing its first material case**. The process
was deliberately stopped for excessive measured cost, its terminal handle was
confirmed, and the prototype APIs/setting/CLI were removed before final rebuilds.
There is no completed three-material qualification of that variant and no claim
that it repairs the underlying force-kick composition. It is not published code.

## Final verification and retained failures

Eight rebuilt scoped CTest entries pass in each default and small-rotation build
(39.39 / 39.61 s): outcome, point-rigid, fixed-assembly, native-point,
native-lattice, bounded material-surface, manifold oracles and bounded coupled
material-surface. Source registration remains 315/315 across 31 CMake files.
This is not the full repository regression or an interactive/mobile qualification.

```powershell
cmake --build build/agent-point-separation --config Release --target banjo_material_surface_contact_tests banjo_native_point_contact_tests banjo_fixed_assembly_contact_tests banjo_point_rigid_contact_tests banjo_native_lattice_contact_tests banjo_outcome_tests --parallel 4
build/agent-point-separation/Release/banjo_material_surface_contact_tests.exe --controlled-manifold --face-patches
ctest --test-dir build/agent-point-separation -C Release -R 'banjo_(point_rigid_contact_tests|fixed_assembly_contact_tests|native_point_contact_tests|native_lattice_contact_tests|material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|outcome_tests)$' --output-on-failure
ctest --test-dir build/local-cell-tools -C Release -R 'banjo_(point_rigid_contact_tests|fixed_assembly_contact_tests|native_point_contact_tests|native_lattice_contact_tests|material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|outcome_tests)$' --output-on-failure
python scripts/check-source-registration.py
```

The controlled command still exits 1: all six cases stop at their previously
measured times before fracture, with zero broken bonds. The existing strict
convergence failures are not waived or claimed retested by this diagnostic-only
checkpoint. No response law changes and no saved/demo world migration occur.
The Git commit containing this note and the user report record main publication.

## Next repair

Implement bounded serial-double contact phases **at the actual Verlet force-kick
boundaries**, with source integration between them. The integration-energy audit
must subtract actual contact work performed inside the integrator; it must not
double-count it as numerical work. Keep native/source/target callbacks and clocks
atomic, retain complete reaction/loss accounts, and test false/exception rollback
at every phase. Compare the original and revised contact composition under all
three materials and both head widths, retaining strict topology/work bounds and
timed cost. Source representability remains a separate numerical limit to measure.

Then qualify actual sustained fracture, persistent physical fragments and ordinary
world actions, followed by the rest of the full world physics plan. The complete
goal remains active; this checkpoint supplies evidence for the next integration
change, not an alternative success criterion.
