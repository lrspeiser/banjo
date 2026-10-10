# Conditional native material branches

October 9, 2026. Base main `100e26f52f29f06975729c6725b749f9d80c36e0`. Implemented private CPU preparation; reduced motion and complete realtime remain unfinished. Work stops at this checkpoint at the owner's request.

## What is included

`banjo_coupled_cpu_material_geometry` returns bounded native compensated attachment coordinates, their world-coordinate Jacobians and geometric data without changing accepted state. `scripts/material_modes.py` constructs conditional elastic potential Hessians with all force/torque rows, including fixed support reactions. Opening and compression choices are explicit per attachment. Cohesive shear remains active in both choices; native connector rest history is retained. Geometric preload curvature is included for translation strains. No display-name preset, physical-law change, tolerance relaxation or accepted timestep is introduced.

The initial supported sheet can prepare four combinations of material opening/compression and contact opening/closing. Private candidates retain full support maps, body and attachment history. The older central-difference diagnostics remain identified separately. Damage/yield crossings, inconsistent retained energy/history and unqualified rotation-log preload refuse preparation. These candidates cannot advance the world.

In `/coupled`, **Inspect vibration basis** beside the 3D scene shows material branch qualification and retained support maps. **Reduced motion: Not admitted** remains explicit. This is endpoint inspection, not a completed smash simulation.

## Verification

Windows MSVC Release separate build `build/material-branches` compiles the changed native API. Five scoped CTests pass: CPU coupled modes, contact observations, contact branches, material branches and coupled view (23.09 seconds total). The actual protected CPU HTTP gateway test also passes. Source registration passes with 354/354 sources; no exclusions. This is not the full repository regression. Current changes have not received independent Linux, ordinary browser or hosted deployment verification; earlier checkpoint evidence remains historical.

Same native isolated attachment experiment for glass, oak, iron and ice: initial and rotated coordinate derivatives, mixed translation/rotation curvature, one-sided opening/compression probes at 1e-10 and 5e-11 m, shear retention, native force/energy reconstruction, read-only state and invalid-input refusal. Maximum coordinate derivative error is 5.79e-11; maximum attachment curvature discrepancy is 8.86e-10 in the tested scaled directions. Native one-sided relative force errors are at most 7.08e-11 for glass/oak/ice and 8.64e-12 for iron. [Measured receipt](evidence/material-branches/verification.json) records per-material results. Properties and native mass/geometry remain unchanged; no oak grain law or calibrated iron continuum dent law is added.

These tests concern potential derivatives and private preparation, not full-pipeline momentum, angular momentum, energy or work transfer. No new simulation speed or conservation claim is made.

## Remaining acceptance

1. Qualify mixed attachment/contact events and broad feature changes along the actual path, with nonlinear trajectory error bounds.
2. Qualify finite endpoint poses, physical angular velocity, irreversible history and interior maximum-opening excursions; support damage/yield and rotation-log preload when warranted.
3. Integrate full support reactions and external/numerical work with complete P/L/E accounting and atomic reduced/detailed transfers.
4. Admit reduced continuation only against always-detailed controls; finish strong glass/oak/iron/ice sheet impacts and detailed ball/fragment reactivation.
5. Complete remaining representation/field transfers and measure full simulation-to-3D realtime delivery.

The commit containing this file is the published checkpoint; inspect its Git revision rather than treating the base revision as the implementation revision. Main publishing is authorized; a new Render deployment is not verified by these local checks.
