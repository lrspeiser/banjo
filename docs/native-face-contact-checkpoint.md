# Native face contact checkpoint — October 7, 2026

## Scope and publication boundary

Baseline main `8aa4025aa47433be36e3fed09a222e97f48440a6`; Windows x64,
MSVC Release, Jolt v5.6.0, double world positions. This continues the
[witness investigation](contact-witness-accuracy-checkpoint.md) and
[free-form world plan](world-physics-action-plan.md). The checkpoint revision
is the Git commit containing this note; publication to main is recorded in the
user report.

Implemented: an explicitly selected native clipped-face geometry query, a
smaller numerical derivative probe in the shared Coulomb solve, comparative
regressions and isolated temporary outcome files. Experimental: sustained
clipped-face material contact. Validated only within the experiments below:
read-only geometry and instantaneous impact accounting. **Sustained fracture
and live world integration remain unqualified.**

The three retained strict failures and six controlled refusals were not waived.
Publishing is limited to the tested query/solver/regression checkpoint; the new
geometry is opt-in and no ordinary world path selects it. There is no promotion
to a playable fracture law. The shared derivative change does affect numerical
trajectories, which is why cached solver versions change.

## Implemented changes

- `MaterialContactGeometry::ClippedFace` requests Jolt supporting faces and
  uses its native manifold clipping. Every returned point retains its own
  signed gap, normal and leaf material. No point pruning, centroid replacement,
  persistent patch cache or fake launch velocity is introduced. A total expanded
  witness budget refuses overflow. `ClosestPoint` remains the API default.
- Curved/edge cases retain the native single-point fallback. The query remains
  read-only, with actual float shape inputs and local coordinates. Geometry is
  not a new material law or a finite-cell rotational model.
- The shared Coulomb Jacobian relative probe changes from `1e-7` to `1e-9`
  times `max(1e-3, |impulse|)`, in N s. Nearly redundant face rows near stick/slip
  required the smaller probe. Complete contact residual, work bounds and search
  iteration limits remain unchanged. The positive-normal starting-guess
  experiment did not fix admission and was removed.
- Outcome solver keys are 7 (default native rotation) / 8 (experimental continuous
  small rotation), formerly 5/6. Tests reject old keys and the opposite native
  integration. This is not permission to reuse a patch outcome without complete
  physical-state, geometry, contact-policy and solver applicability keys.
- File round-trip tests atomically claim a private random temporary directory.
  Two separate builds previously raced on one fixed file, causing wrong-model
  reads or Windows file-lock failures. Cleanup removes only the owned file and
  directory. Concurrent CTest runs now pass.

## Matched geometry and initial impacts

Glass, oak and iron share the declared geometry experiments: 80 mm source cube,
40 mm query box, gaps -2/0/+1 mm, rotated supporting faces, sphere fallback,
compound void/material identity, read-only snapshots and overflow/enum refusal.
The new geometry oracle bound is 100 nm; existing bounds are unchanged.

Replaying the captured broad-oak native poses separated by 0.5 ps under each
material returns four clipped points with bidirectional nearest-vertex patch
movement **5.26961043317 nm**. The prior single representative point switched
28.2844 mm in that captured pair. This eliminates that particular point-switch
reduction; it does not establish continuity across all genuine feature changes.

Initial full-manifold tests use 40 mm target cells, a 120 mm / 27-node target,
nine far-face clamps, 40/120 mm iron heads and the laboratory oak handle,
initial velocity (6, 0.2, 0.1) m/s and no gravity/damping. This is one instantaneous
response, not a sustained elapsed-time simulation. All returned rows are retained
even when only a subset carries nonzero impulse.

| Target | Head width | Points / active | Target work J | Contact loss J | Native energy correction J |
|---|---:|---:|---:|---:|---:|
| Glass | 40 mm | 12 / 7 | 19.55710538 | 4.00315708 | -8.127989e-7 |
| Oak | 40 mm | 12 / 6 | 5.44078626 | 2.12814072 | 1.416001e-6 |
| Iron | 40 mm | 12 / 6 | 24.77734850 | 12.45194465 | -2.226656e-7 |
| Glass | 120 mm | 36 / 5 | 25.75483460 | 4.59462697 | 5.945958e-6 |
| Oak | 120 mm | 36 / 5 | 5.92984912 | 2.22181499 | -6.084126e-6 |
| Iron | 120 mm | 36 / 5 | 48.13068376 | 17.35675860 | 2.118163e-6 |

Target masses: glass 4.32 kg, oak 1.2096 kg, iron 13.59936 kg. Catalog density /
stiffness: 2500 kg/m³ / 70 GPa, 700 / 12 GPa and 7870 / 211 GPa respectively.
Oak remains an isotropic comparison laboratory declaration, without grain,
organic gameplay or validated wood failure. Iron plasticity is not implemented
by this contact change.

Maximum instantaneous *attributed* residuals: 6.52960e-15 N s linear momentum,
4.05275e-17 kg m²/s angular momentum and 1.68754e-14 J energy, after actual native
delivery correction and geometry-couple attribution. Original limits remain
1e-9 N s, 1e-9 kg m²/s and 1e-10 J, with 1e-12 kg mass retention. These accounts
are not proof of full-pipeline conservation. Exact receipts and executable
fingerprints are in the [measured evidence](evidence/material-lab/native-face-results-20261007.json).

Fail-before/pass-after check: restoring the old derivative probe makes the new
first narrow-glass 12-point oracle exit 1 with a 4.17209e-8 m/s residual against
6.00417e-10 m/s tolerance. Restoring the smaller probe admits all six cases.
Both final builds were rebuilt with the smaller probe.

## Sustained acceptance remains open

The continuous-small-rotation build, solver model 8, uses fresh clipped geometry
on every attempted contact and the existing full/two-half accuracy controller.
All six experiments still refuse at the target-contact-work comparison:

| Target | Head width | Accepted physical time µs | Accepted intervals | Last error / bound | Wall time s |
|---|---:|---:|---:|---:|---:|
| Glass | 40 mm | 6.381250 | 237 | 2.60 | 0.191 |
| Oak | 40 mm | 6.400003 | 118 | 1.06 | 0.106 |
| Iron | 40 mm | 7.400000 | 269 | 1.79 | 0.205 |
| Glass | 120 mm | 5.900000 | 222 | 5.40 | 0.887 |
| Oak | 120 mm | 6.250000 | 115 | 1.12 | 1.014 |
| Iron | 120 mm | 6.075000 | 235 | 6.72 | 0.924 |

Required duration is 204.8 µs. Every case has **zero broken bonds**. The last
comparison interval is 3.0517578125 ps and retained absolute work bound is 1 µJ.
The earlier oak 100,000-accepted-interval stall is absent, but this is still not
useful or qualified fracture. Frozen-geometry reapplication is rollback-only
diagnostic output; post-refusal diagnostic exceptions are now labelled so all
six refusals are reported, never admitted as successful steps.

The existing closest-point 100/50 ns strict comparison still exits 1 with three
open gates: narrow-glass topology, narrow-glass integration refinement and
broad-glass topology. A passing bounded-regression invocation explicitly reports
those gates as open; it is not strict acceptance.

Remaining limits: native float local faces/orientation/velocity and quantized
delivery, rounded supporting-face approximation, source constraints and
near-redundant contact precision; affine translational cell support does not
provide finite-cell spin or self-contact. No calibrated material fracture,
metal plasticity, free-form excavation or all-family physics claim is made.

## Verification and screenshots

Seven scoped CTest entries pass in **each** of `build/local-cell-tools` and
`build/agent-point-separation` (16.80 / 16.83 s in concurrent runs): outcome,
point-rigid, fixed assembly, native-point, bounded material-surface, manifold
oracles and bounded coupled material-surface. Source-registration passes
315/315 sources across 31 CMake files. This is not the full repository regression.

Commands, Release configuration:

```powershell
python scripts/check-source-registration.py
ctest --test-dir build/local-cell-tools -C Release -R 'banjo_(point_rigid_contact_tests|fixed_assembly_contact_tests|native_point_contact_tests|material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|outcome_tests)$' --output-on-failure
ctest --test-dir build/agent-point-separation -C Release -R 'banjo_(point_rigid_contact_tests|fixed_assembly_contact_tests|native_point_contact_tests|material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|outcome_tests)$' --output-on-failure
build/agent-point-separation/Release/banjo_native_point_contact_tests.exe
build/agent-point-separation/Release/banjo_material_surface_contact_tests.exe --manifold-oracles-only
build/agent-point-separation/Release/banjo_material_surface_contact_tests.exe --controlled-manifold --face-patches
build/agent-point-separation/Release/banjo_material_surface_contact_tests.exe --coupled-manifold --require-live-contact-convergence
```

The last two commands intentionally exit 1 while the recorded acceptance failures
remain unresolved. Experimental small-rotation mode defaults Off in production.

Browser verification on the retained live world at `http://127.0.0.1:18891/world.html`:
started a fresh sandbox, clicked the pick's **handle**, saw Hand = Pick, clicked
the glass slab and observed native contact confirmed at 1.72 m/s, with 0 cm target
travel. The slab remains intact. This exercises pickup and the existing native
swing; it does **not** exercise the new clipped-face mode or qualify fracture.
No saved gameplay world was reset. The test-hub page also reports an incomplete
catalog; the current screenshots of CPU results come from a separate generated
report built from actual executable logs at port 18892, not the hub catalog.

- [Passing CPU checks screenshot](evidence/material-lab/native-face-passing-20261007.jpg)
- [Unresolved gates screenshot](evidence/material-lab/native-face-gates-20261007.jpg)
- [Live native pickup/strike screenshot](evidence/material-lab/native-face-world-20261007.jpg)

No mobile hardware, other OS, cross-GPU determinism or full gameplay regression
was validated by this scoped checkpoint.

## Next work

Resolve the remaining native/contact numerical floor while retaining measured
work and reaction accounts; qualify sustained contact/topology through actual
fracture; then connect ordinary world tool actions to persistent physical
fragments. After that, follow deformation/structures/tools/mechanisms and
water/heat/energy/pressure in the full world plan. The complete platform goal
remains active.
