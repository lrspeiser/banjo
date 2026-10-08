# Contact time refinement — October 7, 2026

## Scope

Comparative CPU investigation based on main `9a6d0258`, Windows x64 / MSVC
Release, `build/local-cell-tools`. This checkpoint changes the compiled
regression/recorder, not production contact, constitutive laws or the installed
3D sandbox. The full [live world physics objective](world-physics-action-plan.md)
remains active. This follows the [contact-search repair](coupled-contact-search-checkpoint.md).

## Implemented diagnostic

The existing sustained coupled experiment accepts `--refinement-levels 2..5`.
Each level halves the actual physical timestep and doubles accepted steps while
preserving the 204.8 microsecond duration. Every adjacent pair is checked against
the original exact canonical bond-pattern comparison and integration-error ratio
below 0.27. Default behavior remains the original 100/50 ns comparison; strict
failure remains failure. Extended levels require the explicit coupled experiment
and cannot be combined with oracle-only mode.

Recorded `fracture_events` contain actual accepted states at each failure round,
in addition to the original 33 regular frames. The producer checks event count
against the backend's accepted failure-round counter. This exposes the first
failure and subsequent changes without replacing measured reactions with a stored
pattern. Ordinary twelve-case recordings retain `banjo.contact-recording.v1` and
the existing Test Hub contract. Extended matrices use the separate
`banjo.contact-refinement.v1` / `solver-refinement-recording` diagnostic format;
the existing browser viewer intentionally does not accept that matrix.

## Matched 24-case evidence

All three materials share 40 mm cells, the 120 mm / 27-node target, nine stationary
far-face boundary cells, finite native iron head/oak laboratory handle and initial
source velocity (6, 0.2, 0.1) m/s. Head widths are 40 and 120 mm. Target masses
remain glass 4.32 kg, oak 1.2096 kg and iron 13.59936 kg. Existing catalog density,
stiffness, strength and plastic laws are unchanged; oak remains a laboratory
comparison, not organic gameplay admission or a brittle preset.

| Material / head width | Broken bonds at 100 / 50 / 25 / 12.5 ns | Finest integration-error ratio |
| --- | --- | --- |
| Glass / 40 mm | 19 / 7 / 10 / 10 | 0.25369 |
| Oak / 40 mm | 0 / 0 / 0 / 0 | 0.25469 |
| Iron / 40 mm | 0 / 0 / 0 / 0 | 0.24905 |
| Glass / 120 mm | 13 / 13 / 13 / 13 | 0.25105 |
| Oak / 120 mm | 0 / 0 / 0 / 0 | 0.25293 |
| Iron / 120 mm | 0 / 0 / 0 / 0 | 0.25119 |

The 25/12.5 ns pair has exactly equal canonical bond patterns for all six
material/width conditions, not just equal counts. Narrow glass detaches 1.44 kg
at both finest timesteps; it detaches 1.44 kg at 100 ns and zero at 50 ns. Broad
glass has no detached component in these four runs. Oak and iron stay whole.

Narrow glass's first accepted failure occurs at 62 / 89.15 / 79.1 / 79.1375
microseconds. Its finest-pair integration errors are 3.1686e-5 / 8.0384e-6 J.
These are discrete accepted event times, not exact continuous crack-onset times.
The stable fine pair points to inadequate temporal resolution in the coarser
fixture, but does not prove a universal timestep bound, spatial convergence or
calibrated material realism. Event order/contact, native precision and nonlinear
fracture still need qualification across other geometry, speed and material
conditions.

All 24 cases complete without unsupported-region or contact-search refusal.
After external/numerical attribution, maximum absolute residuals are
9.56e-13 N s, 1.83e-15 kg m²/s and 4.19e-12 J. Those attributed residuals do not
prove full-world conservation. Source roundoff/native stepping, boundary
reactions, bond work/loss and integration correction remain separately measured.

Observed per-case wall time ranges 0.264–9.10 seconds for 204.8 microseconds of
simulated time. Refinement improves this fixture's accuracy and makes the
reference slower. Realtime gameplay, finite neighbouring terrain, cell spin,
self-contact, soil, water, tool wear and actor/hand coupling remain unqualified.

## Rejected experiment

A temporary midpoint-contact/two-half-integration variant was tested under the
same three-material conditions. Narrow glass changed from one to nine broken
bonds at its two timesteps, with a worse integration-error comparison; broad
glass later refused a nine-contact solve at 4.72e-10 m/s against the retained
1e-10 m/s bound. The variant is removed. Neither its result nor a widened
tolerance is used as an accepted physical response.

## Verification and retained failure

Six scoped CTest entries pass in 39.44 s. Three actual-recording client groups
pass against a newly produced default recording; five invalid refinement
requests refuse. The extended recording contains all 24 cases with initial/final
regular samples, matching clocks and monotone event identities/counts. Source
registration passes 315/315, and changed-file whitespace checks pass.

The original strict coupled command still fails its narrow-glass comparison.
The four-level strict command returns failure for three adjacent checks: narrow
glass topology at 100/50 and 50/25 ns, plus its integration-error ratio at 50/25
ns. Its finest pair passing does not suppress these failures or close the
original gate. The existing sequential and repeated-iron gates are not retired.
No full-suite, normal interactive window, phone or cross-platform claim is made.

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_material_surface_contact_tests --parallel 4
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --coupled-manifold --require-live-contact-convergence --record build/material-lab/contact-events-default-record.json
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --coupled-manifold --refinement-levels 4 --require-live-contact-convergence --record build/material-lab/contact-refinement-final-record.json
node tests/lab_test_hub_client_tests.mjs build/material-lab/contact-events-default-record.json
ctest --test-dir build/local-cell-tools -C Release -R 'banjo_(material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|fixed_assembly_contact_tests|native_lattice_contact_tests|native_point_contact_tests)$' --output-on-failure
python scripts/check-source-registration.py
```

Large measured recordings and experiment logs stay ignored under
`build/material-lab/`. Source is registered through the existing compiled test
target. PR #2 is currently merged, with head `138260d2`; its pinned
[contact checkpoint](contact-checkpoint.md) was reread. No branch is reset or
merged by this work. Publication revision is recorded in Git and the user report.

Next: implement current-state accuracy control over a paired source/material
step, comparing trial motion, damage/contact state and accounting while retaining
histories and actual accepted time. A fine timestep for one glass fixture must
not become a material-name rule or global gameplay speed claim. Then qualify
ordinary hand/tool contact, persistent physical fragments and subsequent
free-form actions in the same 3D world. The complete physics scope remains open.
