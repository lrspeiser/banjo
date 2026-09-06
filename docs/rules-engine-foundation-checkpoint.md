# General rules engine: first implementation checkpoint

This executes the first parts of [R01/R02](rules-engine-execution-plan.md), retaining all prior goals. Neither these goals nor the whole platform are complete.

## Property-based native execution

`MaterialBehavior` describes density and one isotropic elastic, orthotropic elastic or J2 plastic law using SI coefficients. Descriptions are immutable, physical hashes exclude display names/IDs, and unsupported capabilities are rejected. The C++ `banjo_material_behavior_probe` independently validates inputs, executes absolute strain paths with persistent constitutive history, and emits actual stress, stored energy, plastic dissipation and numerical work excess. `material_behavior_client.evaluate_material_path` exposes the path to programs with input/executable/material hashes. It is a material-point API, not a geometry or collision API.

The deterministic trial executed 12 unseen parameter sets. One actual gpt-5-mini request generated 3 fictional, uncalibrated sets, using 534 tokens in 4.14 seconds. All 15 passed the constrained axial stress oracle and exact native-output rename invariance. These reuse an implemented isotropic law, not LLM-invented physical equations. Native integration tests also cover orthotropic oak and J2 iron/new-alloy history. Names such as rubber cannot change the selected law.

## Inertial material state

`DynamicPatch` reuses `SmallStrainPatch` reference tetrahedra, mass and constitutive evaluation. It adds nodal velocity, gravity/force integration, stationary supports and symplectic Euler. Both displacement/J2 and dynamic state commit together; invalid strain, timestep or load leaves all state unchanged. Velocity assignment is restricted to initial conditions. Reports separate kinetic/stored energy, cumulative plastic dissipation, external work, support impulses and raw numerical energy/momentum residuals.

An elastic stiffness/mass absolute-row bound limits the explicit timestep. This is a conservative baseline and can be expensive for stiff thin objects. It is not a realtime solution or a nonlinear stability proof; strain/gradient validity checks still apply. Implicit/multirate stepping requires its own tests. No damping, surface contact, fracture, finite rotation, rubber constitutive law or dynamic state reload is added here.

Focused tests cover translation, free fall/momentum, complete rollback, analytic one-degree-of-freedom oscillator refinement, matched glass/oak/iron strain-free controls and positive persistent J2 history. The oscillator error decreased from 2.15662e-5 to 9.6614e-6 in the declared combined position/velocity metric. This is temporal refinement of a constrained tetrahedron, not spatial convergence of a sheet or a validated dent.

## Reproduction

Build `banjo_material_behavior_probe` and `banjo_dynamic_patch_tests` in the configured Release build. Run `python tests/material_behavior_tests.py`, `python tests/material_behavior_native_tests.py`, and `python tools/material_rules_trial.py` for offline trials. Explicit `--execute-llm` authorizes one paid generation call and writes proposal/result evidence; there is no automatic paid retry. The tool uses the ignored server-side key configuration.

## Next acceptance gate

R03 needs triangle/sphere surface contact, equal-and-opposite impulse and work accounting, no tunneling and timestep/mesh comparison. R04/R05 then require actual shape recovery and retained impact dents. R06 still requires a stable crack-propagation discretization; the recorded thin-glass failure remains unresolved. LLM playground authoring must admit only those capabilities that have actually been connected and tested.

## Verified checkpoint

Windows MSVC 19.44 Release, double positions: full build passes without compiler warnings in the captured build log; all 59 native CTest suites pass in 86.07 s. The new dynamic suite contains six focused cases. Python descriptor tests: 8 passed; native property-path integration tests: 4 passed. Existing playground group: 61 passed, one existing Windows symlink skip on rerun; the first run had one Windows connection-aborted error in the HTTP boundary test, and the unchanged full group passed on repeat. Python compilation, diff checks and changed-file credential scan pass. No new visual impact behavior is claimed.
