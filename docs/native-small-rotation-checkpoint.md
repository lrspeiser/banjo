# Native small rotations — October 7, 2026

## Scope and identified cause

Baseline: main `8225ea31ce19dd53152731a973b87d313b4f973f`, Windows x64,
MSVC Release, Jolt v5.6.0, double positions. This continues the
[manifold investigation](manifold-law-admission-checkpoint.md) and the complete
[free-form live 3D physics objective](world-physics-action-plan.md).

Per-body full/two-half-step isolation now records starting and trial position,
orientation, velocity and spin, with exact position/velocity rollback checks.
Narrow iron's stopped source had approximately 10.677 rad/s z spin, yet both
body orientations were still identity after two accepted 50 ns steps. In a
1 ps native-only trial the handle moved roughly 12 nm by position correction,
rather than its sub-picometre ballistic travel; two half steps corrected it
again. This was not evidence of ordinary integrated rotation.

Jolt `Body::AddRotationStep` and `SubRotationStep` explicitly ignore an angular
increment whose length is at most 1e-6 rad. At microsteps, centre/attachment
velocities integrate while orientation stops; the point constraint then sees
drift and corrects it per native update. Reducing dt does not converge that
dead-zone model to continuous rotation. Earlier double centre-distance and
double rotated-arm experiments did not remove this floor and were removed.

## Experimental implementation

`BANJO_JOLT_CONTINUOUS_SMALL_ROTATION=ON` replaces those two threshold checks
with positive-length checks. The existing axis-angle quaternion integration,
normalization, torque/velocity response, damping, position stabilization and
constraint iteration counts remain. No pose/velocity is assigned to disguise
an error; no fragment template, launch impulse or new material law is added.
Float angular state/length and orientation rounding remain limitations; this
does not establish arbitrary precision at every angle or timestep.

The default remains OFF pending the sustained/strict and wider integration
gates. `cmake/JoltSmallRotation.cmake` produces a header overlay inside the
separate build directory, checks exactly two pinned upstream expressions and
never modifies the shared fetched Jolt checkout. Jolt and every linked consumer
receive the same PUBLIC include directory. The unchanged `Body.h` is copied
too because its relative `"Body.inl"` include would otherwise bypass the overlay.
A clean experimental rebuild and the angular oracle verify the implementation
actually executes, rather than merely generating an unused header.

`JoltWorld::rotationIntegrationProfile()` reports the selected compiled model.
The contact experiment prints it. Material-outcome solver keys are 6 for the
experimental integration and retain 5 for legacy; both builds reject the other
model's outcomes. The arithmetic compiler profile remains `banjo-cpu-precise-v1`.
This is not permission to reuse incomplete physical-state keys or cached fracture
outcomes in the live world.

## Analytical and matched material evidence

The new explicit `--require-small-rotation` diagnostic fails on the legacy
build with `native spin stopped integrating below one microradian`. Selected
experimental builds run this oracle automatically in the registered native-point
suite. Glass/oak/iron use identical 80 mm cubes, initial principal-axis spin
1 rad/s, no gravity/damping and a 100 ns horizon split into 1/2/4/16/64 actual
native steps (100 to 1.5625 ns). This free rigid-body experiment exercises mass,
inertia and rotation; it imposes no strain and does not test elastic stiffness.

Declared cube masses are 1.28 / 0.3584 / 4.02944 kg, with the runtime's existing
float mass representation (measured 1.28 / 0.35839997375 / 4.02943996741 kg).
Catalog densities/stiffness remain glass 2500 kg/m³ /
70 GPa, oak 700 / 12 GPa and iron 7870 / 211 GPa. Oak is a comparison laboratory
material, without grain or organic gameplay.

Every material's maximum angle error is 4.15e-14 rad, below the new analytical
2e-13 rad bound. Mass, centre, angular velocity and trial rollback are unchanged.
Energy and linear/angular momentum changes are zero in these three oracles;
the momentum checks retain 1e-12 SI bounds.
These are scoped rigid-motion oracles, not fracture or full-world conservation.

The existing 40 mm-cell, 120 mm/27-node target, nine far-face clamps, two head
widths and velocity (6, 0.2, 0.1) m/s remain unchanged. All six controlled cases
still stop before fracture:

| Material / width | Accepted time (µs) | Accepted intervals | Refusal |
| --- | --- | --- | --- |
| Glass / 40 mm | 5.4125 | 207 | Contact-transfer accuracy |
| Oak / 40 mm | 5.429898 | 100,000 | Accepted interval budget |
| Iron / 40 mm | 6.075 | 231 | Contact-transfer accuracy |
| Glass / 120 mm | 5.728125 | 215 | Contact-transfer accuracy |
| Oak / 120 mm | 6.110004 | 19,773 | Contact-transfer accuracy |
| Iron / 120 mm | 5.8875 | 228 | Contact-transfer accuracy |

Narrow iron advances from 0.1 to 6.075 µs; its native-only 1 ps position
disagreement drops from approximately 11 nm to 1.32e-13 m. Across all six stopped
states the 1 ps native position difference is 4.00e-15–1.89e-13 m. The original
native position floor is resolved in these comparisons, not every numerical
floor in the pipeline. Source velocity quantization and contact-work disagreement
remain; broad iron's native-only energy difference reaches 2.53e-7 J.

Controlled attributed residual maxima are 2.29e-14 N s, 2.08e-16 kg m²/s and
1.80e-12 J, with mass preserved. The oak runs reach picosecond intervals; the
first measured narrow/broad cases cost about 53/20 s for incomplete 5–6 µs
trajectories. This is not useful speed or a successful fracture run.

The strict 100/50 ns fixed-step comparisons now fail three gates, rather than
the legacy one's single failure. Correctly integrated source motion changes
narrow glass to 7/10 broken bonds and broad glass to 22/14; oak/iron remain
unbroken. Narrow glass's integration-error ratio also exceeds the retained 0.27
bound. All twelve runs still complete 204.8 µs; maximum attributed residuals
are 6.16e-13 N s, 4.07e-16 kg m²/s and 3.68e-12 J, within unchanged 1e-9 SI /
1e-10 J accounting bounds. Numerical/support attribution is not full-pipeline
conservation or material realism. No acceptance tolerance is increased to pass.

## Verification and next work

Six scoped CTest entries pass in each build: outcomes, fixed assembly, native
point, surface contact, coupled surface contact and manifold oracles (17.18 s
experimental / 16.28 s legacy). Experimental
native-point includes the new angular/rollback oracle; legacy's explicit angular
diagnostic remains a documented expected failure. Source registration is 315/315;
PR #2 remains merged at `138260d2` and its conservative checkpoint was reread.
Publication is recorded in Git/user report; large logs remain ignored under
`build/material-lab/`.

```powershell
cmake -S . -B build/agent-point-separation -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF -DBANJO_JOLT_CONTINUOUS_SMALL_ROTATION=ON
cmake --build build/agent-point-separation --config Release --target banjo_material_surface_contact_tests banjo_native_point_contact_tests banjo_fixed_assembly_contact_tests banjo_outcome_tests --parallel 4
ctest --test-dir build/agent-point-separation -C Release -R 'banjo_(fixed_assembly_contact_tests|native_point_contact_tests|material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|outcome_tests)$' --output-on-failure
build/agent-point-separation/Release/banjo_native_point_contact_tests.exe --require-small-rotation
build/agent-point-separation/Release/banjo_material_surface_contact_tests.exe --controlled-manifold
build/agent-point-separation/Release/banjo_material_surface_contact_tests.exe --coupled-manifold --require-live-contact-convergence
python scripts/check-source-registration.py
```

The local comparison reused fetched Jolt/JSON sources through their
`FETCHCONTENT_SOURCE_DIR_*` options; those sources were not edited. The failed
point-precision overlays were removed, and no build artifacts enter the commit.

Next: isolate the retained source quantization/contact-work floor and qualify
refinement through actual fracture with continuous source motion. Then verify
wider native mechanisms/actors and ordinary live tool fracture plus persistent
fragments before selecting this model for the playground. The full deformation,
structures, tools, fluids, heat, energy and pressure scope remains active. Running
demos/saved gameplay and default physics are unchanged. No normal interactive,
phone, full-regression, cross-platform or completed live-world claim is made.
