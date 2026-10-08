# Manifold law admission — October 7, 2026

## Implementation and regression

Baseline: main `4e33ee7c871082f5721917a1dcf63e59e11648f0`; Windows x64,
MSVC Release, Jolt double positions, separate build `build/local-cell-tools`.
This continues the [controlled contact investigation](controlled-contact-checkpoint.md)
and the complete [live 3D physics objective](world-physics-action-plan.md).

The material manifold still evaluated each witness as an isolated point/rigid
collision solely to validate declarations. Its unused result could refuse on
the isolated velocity/work audit before the actual simultaneous response ran.
`validatePointRigidContactLaw` now shares the unchanged normal/gap/timestep,
friction, restitution, threshold and margin checks without solving an impulse.
Point contact retains its original response and audits. Manifold contact uses
its existing coupled mass matrix, complete Coulomb residual and whole-system
work/reaction audits. Nonfinite relative/normal speeds and target speeds refuse.
No contact law, tolerance, native constraint or timestep floor is changed.

A material-neutral analytical regression uses eight 2 kg translational nodes,
a 1 kg rigid source with diagonal inertia 0.01 kg m², common translation 6 m/s,
an affine compression rate 2.5e-6 /s, two opposing offset surface witnesses,
zero friction/restitution and 100 ns horizon. The isolated point response
refuses its velocity/work audit; on the old manifold code the new regression
also failed with that exact error. With shared declaration validation the
simultaneous response succeeds, retaining 1e-12 SI reaction/work bounds.
Removing the common translation changes contact impulses by less than 1e-14
N s. Invalid declarations on the final witness still refuse, including nonunit
normal, NaN gap, invalid friction/restitution, negative threshold and margin.
This analytical regression is not a material realism or fracture claim.

## Matched material evidence and remaining gates

Glass/oak/iron retain identical 40 mm cells, 120 mm/27-node target, nine far-face
clamps, iron head/oak laboratory handle, initial velocity (6, 0.2, 0.1) m/s and
no gravity/damping. Target masses are 4.32, 1.2096 and 13.59936 kg respectively;
density/stiffness remain 2500 kg/m³ / 70 GPa, 700 / 12 GPa and 7870 / 211 GPa.
Oak remains laboratory comparison only, without grain or organic gameplay.

The six controlled sustained cases still refuse before fracture:

| Material / head width | Accepted time (µs) | Accepted intervals | Current refusal |
| --- | --- | --- | --- |
| Glass / 40 mm | 5.946875 | 930 | Contact-transfer accuracy |
| Oak / 40 mm | 5.850931 | 415 | Contact-transfer accuracy |
| Iron / 40 mm | 0.1 | 2 | Native position accuracy |
| Glass / 120 mm | 5.78125 | 217 | Contact-transfer accuracy |
| Oak / 120 mm | 6.1 | 112 | Contact-transfer accuracy |
| Iron / 120 mm | 5.95 | 230 | Contact-transfer accuracy |

The broad oak case now evaluates the actual manifold instead of stopping at
the unused point response; its final normalized contact-transfer disagreement
is 1.165009. Its accepted time is unchanged. No inaccurate interval is forced
through. Maximum attributed residuals remain 1.35e-14 N s, 1.26e-16 kg m²/s
and 3.43e-12 J; mass and rollback checks pass. Incomplete case wall times are
roughly 0.01–0.49 s, not realtime or useful digging-speed qualification.

The original strict 100/50 ns command still fails narrow glass with 19/7
broken bonds. Broad glass remains 13/13; oak/iron remain unbroken at both widths.
All twelve fixed-step cases complete 204.8 µs. Maximum attributed residuals are
3.02e-13 N s, 7.77e-16 kg m²/s and 4.19e-12 J, within the unchanged 1e-9 SI /
1e-10 J tests. These attributed accounts include numerical and support terms;
they do not establish full-world conservation or calibrated material realism.

## Verification and next work

Rebuilt scope: material-surface, fixed-assembly, native-point, native-lattice,
fast-lattice, external-load, plasticity and Verlet executables. Ten scoped CTest
entries pass in 48.20 s, including the new regression and retained glass/oak/iron cases.
Source registration remains 315/315. PR #2 remains merged at `138260d2` and its
pinned conservative contact note was reread. Publication is recorded in Git and
the user report. Diagnostic logs remain ignored in `build/material-lab/`.

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_material_surface_contact_tests banjo_fixed_assembly_contact_tests banjo_native_point_contact_tests banjo_native_lattice_contact_tests banjo_fast_lattice_tests banjo_lattice_external_load_tests banjo_lattice_plasticity_tests banjo_lattice_verlet_tests --parallel 4
ctest --test-dir build/local-cell-tools -C Release -R 'banjo_(material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|fixed_assembly_contact_tests|native_lattice_contact_tests|native_point_contact_tests|fast_lattice_tests|lattice_external_load_tests|lattice_plasticity_tests|lattice_verlet_tests)$' --output-on-failure
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --controlled-manifold
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --coupled-manifold --require-live-contact-convergence
python scripts/check-source-registration.py
```

Next: resolve the native attachment/rotation projection floor and the sustained
contact-transfer disagreement while retaining reactions and work. Then qualify
ordinary live tool fracture and persistent physical fragments, followed by the
remaining deformation, mechanisms, fluid, thermal, energy and pressure stages.
The original strict gate and all six controlled gates remain explicitly open.
Running demos and saved gameplay are unchanged; this checkpoint has no UI,
phone, normal interactive, full-suite or cross-platform qualification.
