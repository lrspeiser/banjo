# Separate native contact preparation

October 9, 2026. **Implemented private CPU endpoint inspection; reduced execution, detailed ball/sheet fracture and complete realtime remain open.** Base main `839b59a8ff5e3b92cd0031f439fbe876fc9c3e0b`. Follows the [object representation contract](object-representation-design.md) and [correlated continuous contact bounds](correlated-contact-bounds-checkpoint.md).

## Visible test

In `/coupled`, open **Inspect / save / tests** beside the 3D scene and choose **Inspect vibration basis**. The supported sheet remains visible at the same accepted time. The inspector now shows separate opening/closing contact choices, compressed/touching sites, native force reconstruction and remaining material qualification. Run/reset controls remain adjacent to the scene. This inspection is not a smash or an admitted reduced timestep; use **Fall & rebound** for the retained actual drop control.

## Implementation

`banjo_coupled_cpu_material_trials` calls the same native material/history transport and gather in original order, without contact. This is a private preparation API, not an alternative world solver. The normal full native CPU/CUDA response and its convergence gates are unchanged. Material-only poses/history match full-native trials exactly in the comparative tests. Invalid requests refuse; accepted world state is not changed.

`banjo_coupled_cpu_contact_stiffness` exposes the existing material-derived contact coefficient in exact native site order. Capacity and invalid-input checks occur before caller output is written. There is no material-name selection or new contact coefficient.

For a smooth scalar surface gap `g`, native normal gradient `a`, and native stiffness `k`, the compressed endpoint potential is `U = k g²/2`. Its frozen-coordinate stiffness is `K = k (a aᵀ + g Hessian(g))`. The second term preserves preload/geometry curvature, including rotations and both objects' reaction rows. At exact touching, **open** and **closed** candidates are explicit; they are not averaged together. Box feature ties, exterior-feature curvature and unsupported primitive curvature refuse. Broad SAT/event continuation remains unqualified.

The analytical gap Hessian uses left/world Cayley rotations and additive translations. Material torques are pulled back through the same Cayley chart before differentiating. A world-torque derivative alone is not that chart's potential Hessian. Endpoint potential curvature is also distinct from the native discrete-gradient timestep Newton Jacobian.

Material probes still use central averaging where their one-sided derivatives disagree. Their asymmetry, half-resolution change and irreversible sample changes are reported, and an inconsistent material candidate is marked invalid. No candidate can advance the world. The existing affine probe now records the dynamic impulse mismatch between its symmetrized active tangent and unsymmetrized full force tangent. Full candidate reaction maps are not retained as an executable representation yet.

## Comparative evidence

Same fixture for glass, oak, iron and ice: nine 10 mm connected cells, existing fixed supports, native material/geometry/contact laws, gravity 9.81 m/s². No accepted timestep occurs during preparation. Translation/rotation probes use 1e-13 m / 1e-11 rad and half those values; stationary/path reads use the native 1e-6 s trial API. Preparation clocks are private and are not physical elapsed time.

| Material | Material one-sided defect | Half-resolution change | Native stationary force residual | Contact energy residual |
|---|---:|---:|---:|---:|
| Glass | 0.501745 | 1.55e-12 | 8.50e-18 | 0 J |
| Oak | 0.501745 | 1.55e-12 | 3.68e-18 | 0 J |
| Iron | 2.65e-12 | 7.05e-6 | 0 | 0 J |
| Ice | 0.501745 | 1.51e-12 | 7.36e-18 | 0 J |

Force residual is the combined L2 norm of force/torque rows in their native N / N·m units, **not a full-pipeline conservation metric**. Each initial fixture has 20 numerically compressed and 96 exactly touching sites. Tiny initial compression is retained, not erased. Density-derived sheet masses remain glass 0.0225 kg, oak 0.0063 kg, iron 0.07083 kg and ice 0.008253 kg. Frequencies retain their corresponding density/stiffness differences. Oak uses its existing declared interface law; this adds no grain/anisotropy or wood calibration. Iron retains existing connector plasticity; this adds no continuum dent/tearing law.

288 independent two-body native scalar-gap directional curvature checks cover plane/box targets, swapped owners, mixed translations/rotations and compressed geometry. Maximum absolute curvature discrepancy was 3.46e-9 in the declared scaled directions on Windows and Linux. Twelve additional native contact-potential second differences check the complete loaded Hessian. Opening, touching and compressed choices, force/torque pair reactions, invalid capacity and invalid branch refusal are tested. These analytical/preparation checks supply no new mass, impulse, energy or work transfer; native full-world conservation is retained by separate unchanged runtime regressions.

Windows branch preparation cost 24.6–43.4 ms in single runs, excluding constructor, full original preparation, HTTP and rendering. Full browser inspection measured 339 ms in one local run. These are preparation measurements, **not a realtime world speedup**. [Per-material Windows/Linux receipts and verification scope](evidence/contact-branches/verification.json) preserve the evidence.

## Verification and remaining work

MSVC Release headless separate build `build/contact-branches` compiles the changed native API. Eight scoped Windows CTests pass: native coupled contact, CPU modes, contact observations, new contact branches, coupled view, local Jacobian, CPU world and high-drop controls. Actual protected CPU HTTP gateway tests pass. Independent GCC Release Linux branch/modes suites pass. Source registration is 354/354. The actual local browser verifies the new inspection results on the 3D sheet and phone controls at 390 x 844. Hosted verification is recorded after publication. This is not a full repository regression or cross-platform determinism claim.

Next requirements, still part of the original eight-family objective:

1. Resolve constitutive opening/compression branches and iron refinement; qualify consistent contact events and broad-feature changes along the actual path.
2. Construct native-consistent finite endpoint poses, physical angular velocity and persistent history. Cohesive maximum opening can change at an interior excursion without damage; unchanged damage alone is insufficient.
3. Retain/integrate full support reactions and actual path work, P/L/E, with atomic reduced/detailed transfer and independent nonlinear trajectory error.
4. Admit and measure actual reduced continuation against always-detailed controls; qualify strong four-material sheet impacts and detailed ball/fragment reactivation.
5. Finish the remaining sleeping/articulated/flow/thermal/reaction transfers and complete simulation-to-3D realtime measurements. Diagnostic inspection does not satisfy these deliverables.
