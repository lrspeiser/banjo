# Reversible variable contact steps — October 7, 2026

## Implemented scope

Based on main `86933f89`, Windows x64 / MSVC Release, separate build directory
`build/local-cell-tools`. The serial double CPU Verlet backend now provides
`advanceExternalContactStep(dt, contact)` within an existing paired native/material
reversible trial. It scopes the actual contact horizon to the requested positive
timestep, executes current source/contact work, then advances the material once.
The uploaded timestep is an upper bound and is restored after the call. Current
spring stability is checked before contact and during the existing integrator.
No material law, strength, damping, contact tolerance or outcome is replaced.

`externalContactElapsedTime()` records accepted physical seconds since upload,
with compensated summation, independent of accepted substep count. Ordinary serial
double Verlet `run()` also advances that clock. A rejected or throwing paired
trial restores time/correction, histories, loads, numerical accounts and native
state. An upload deliberately starts a new local clock; an owner transferring
constituents must retain the absolute time origin separately.

The callback is a trusted serial host operation. It owns advancing the native
source exactly once at the scoped timestep and must keep receipts provisional
until the enclosing paired trial is accepted. Recursive variable steps, target
`run()` and force/wrench replacement inside the callback refuse. Trial nesting and
upload retain their existing refusal. Float, parallel CPU and XPBD backends refuse
the new API. Their integration paths are unchanged.

Finite queued forces/wrenches currently declare durations in substeps. While such
a load is active, a changed timestep refuses rather than silently changing its
physical duration. Uploaded-duration steps remain available; smaller steps become
available after the finite queue expires. Constant gravity integrates at each
actual timestep and uses the existing delivered-work/impulse ledger. This boundary
needs a physical-time load scheduler before adaptive actuator integration.

## Matched evidence

The compiled surface-contact test exercises glass, oak and iron with the same
40 mm cells, eight-node 80 mm target, initial geometry, finite iron head/oak
laboratory handle, velocity (6, 0.2, 0.1) m/s and existing axial material laws.
Oak remains a laboratory comparison; grain and organic gameplay are unsupported.
The two actual contact steps use 100 then 50 ns. The accepted clock is 150 ns,
the step count is two and the restored declared horizon is 100 ns. These are
short boundary/oracle experiments, not fracture calibration or gameplay speed.

| Material | Target mass (kg) | Attributed P residual (N s) | Attributed L residual (kg m²/s) | Attributed E residual (J) |
| --- | --- | --- | --- | --- |
| Glass | 1.28 | 1.95e-14 | 5.76e-18 | -1.07e-14 |
| Oak | 0.3584 | 3.35e-15 | 2.09e-18 | -4.62e-15 |
| Iron | 4.02944 | 4.97e-15 | 1.20e-17 | -4.78e-14 |

Attribution includes measured native integration and contact roundoff, fixing
geometry torque, target bond-kick correction, numerical integration energy and
existing bond loss/plastic accounts. Existing 1e-9 momentum/angular and 1e-10 J
energy test bounds are retained. These attributed residuals concern this paired
reference; full-world conservation remains unqualified.

Additional same-material cases verify:

- Rejected 25/12.5 ns trials and exceptions restore node positions, previous
  positions, velocities, masses, alive/damage/plastic/strain histories, both joined
  native poses/rotations/velocities, status, transfer work and the physical clock.
- Invalid, excessive and empty requests refuse before integration. Callback
  double stepping, recursion and force/wrench replacement refuse.
- A two-step uniform force retains its 200 ns duration and delivered impulse.
  Three 100 ns steps followed by a 50 ns step leave the actual clock at 350 ns.
- Gravity over 100/50/25 ns matches analytical assembly momentum and center-of-mass
  displacement at 175 ns. Measured gravity impulses are -2.19744e-6,
  -6.152832e-7 and -6.91754112e-6 N s for glass/oak/iron respectively. Mass is unchanged.

The initial new uniform-force assertion demanded each node reproduce the same
velocity within 1e-18 m/s. A measured 4.25e-14 m/s internal redistribution arose
from reconstructed-position spring roundoff. The final oracle checks assembly
momentum within 2e-20 N s and gravity center displacement within 1e-24 m; internal
action/reaction may redistribute motion. Existing physical tests/tolerances are
unchanged.

## Verification and remaining work

Ten rebuilt scoped CTest entries pass in 48.95 s, including the CPU reference,
external loads, plasticity, Verlet, fixed/native contact and both material paths.
The oracle-only command passes with all three new variable-step cases. The original
strict coupled command still returns failure for one narrow-glass topology gate
(19/7 broken bonds); the new API is not enabled in that sustained fixture and does
not change or suppress its physical acceptance requirement. New code is built
through existing CMake targets; source registration remains 315/315.
PR #2 is freshly confirmed merged at head `138260d2`; its pinned contact note was
reread. No branch is reset or merged. Publication revision is recorded in Git and
the user report; local logs remain ignored under `build/material-lab/`.

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_material_surface_contact_tests banjo_fixed_assembly_contact_tests banjo_native_point_contact_tests banjo_native_lattice_contact_tests banjo_fast_lattice_tests banjo_lattice_external_load_tests banjo_lattice_plasticity_tests banjo_lattice_verlet_tests --parallel 4
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --manifold-oracles-only
ctest --test-dir build/local-cell-tools -C Release -R 'banjo_(material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|fixed_assembly_contact_tests|native_lattice_contact_tests|native_point_contact_tests|fast_lattice_tests|lattice_external_load_tests|lattice_plasticity_tests|lattice_verlet_tests)$' --output-on-failure
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --coupled-manifold --require-live-contact-convergence
python scripts/check-source-registration.py
```

This implements the history/time primitive needed by the next accuracy controller.
Automatic timestep selection, full-step/two-half-step comparison, topology/event
acceptance, clock origins at constituent transfer and physical-time actuator loads
remain open. The original strict narrow-glass convergence gate is retained.
Ordinary held-tool fracture, physical fragment continuation, realtime speed and
the complete [free-form live world objective](world-physics-action-plan.md) remain
unfinished. Running demos and saved gameplay are unchanged. No normal interactive
window, full-suite, physical-phone or cross-platform qualification is claimed.
