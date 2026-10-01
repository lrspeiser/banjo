# Lattice ground tools beside exact equipment — September 30, 2026

Code `f819e81` on main narrows scene admission without adding or changing a material law. This is a prerequisite for the [player progression work](ai-player-playthrough-review.md#recommended-work-in-order), not a completed starter-tool journey.

## Implemented

A ground tool point can attach to an existing lattice body in a mixed scene containing precise rigid machinery. The Python scene validator admits lattice `swing-and-lever` profiles, and the native API checks the target body rather than rejecting every point because another body is exact. A saved lattice point can return in a whole restore or carry into an edited mixed scene.

Exact bodies still cannot carry ground tool points. Invalid saved points targeting an exact body are refused, including during edited-scene carry. Blades and draw-and-release profiles remain unavailable in mixed precise scenes. Heat on exact bodies, their internal fracture/deformation, and failures requiring an exact body inside a lattice solve retain their existing boundaries.

## Measured comparison

Windows 11, Python 3.13.5, MSVC 19.44, Release CPU reference, `build/agent-progression`. Native runner and the existing CMake-registered `banjo_ground_work_tests` target were rebuilt from this source. `banjo-cpu-precise-v1` command audit passed. Existing compiler warnings remain.

Identical 40 × 400 × 40 mm stakes, 40 mm cells, 30-degree point, 200 mm modeled point length, dropped from 250 mm above dry 400 mm soil. `dt = 1/240 s`, gravity `9.80665 m/s²`, 480 steps. Each material is run with and without a distant exact iron compound under identical conditions. No hand impulses, steering, outcome cache or fracture substitution is applied.

| Material | Mass (kg) | Penetration (m) | Bite work (J) | Corrected energy residual (J) | Existing damping bound (J) |
|---|---:|---:|---:|---:|---:|
| Glass | 1.600000 | 0.069447 | 4.998111 | -0.004325528 | 0.008098328 |
| Oak | 0.448000 | 0.033302 | 1.241271 | -0.000610494 | 0.001395404 |
| Iron | 5.036800 | 0.163013 | 20.342134 | -0.027121319 | 0.058831232 |

Material density drives the mass differences. A stiffer or more brittle material is not simulated as a different prescribed penetration: the ground model and solver take the actual mass/motion/material hardness. This drop does not load or validate internal tool deformation, fracture, grain or plasticity.

All three mixed/reference trajectories have measured maximum position/velocity difference **0**, equal bite work and equal material-derived mass. Ground ledger residual is within `1e-10 m³`; no ground is removed by this straight drop. The energy residual is bite work minus stake energy loss minus the existing semi-implicit gravity correction `m g dt v_entry / 2`; it fits the existing damping bound plus `1e-6 J`. No tolerance was widened. This is a bounded stake/ground work check, not full-world momentum/energy closure with arbitrary tool/machine contacts.

The first attempted one-metre comparative drop caused the heavier iron stake to bottom out beyond the modeled point, with additional ordinary surface-contact losses. It failed the point-only energy oracle and was not accepted. The same 250 mm drop for all materials keeps penetration below 200 mm. The original one-metre oak oracle remains unchanged and passes.

## Verification

```powershell
python scripts/check-source-registration.py
cmake --build build/agent-progression --config Release --target banjo_ground_work_tests banjo_live_world_run --parallel 4
build/agent-progression/Release/banjo_ground_work_tests.exe
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/agent-progression/Release/banjo_live_world_run.exe).Path
python -m unittest discover -s tests -p precise_rigid_live_tests.py
git diff --check
```

- Source guard: 286/286, no exclusions.
- Native ground-work suite: 9 checks pass, including the three-material mixed comparison, original drop/swing/pry/ground ledger and carried-budget checks.
- Python precise-rigid suite: 36 pass, no skips with rebuilt runner. New admission test retains full validation of point/profile references and rejects exact targets, unsupported profiles and malformed names.
- Native save/readback retains full body and point records. Edited-scene carry appends a marker and retains the unchanged exact compound and lattice point. A corrupted point redirected to the exact body is rejected.

No new interactive browser journey or cross-platform/GPU claim accompanies this checkpoint. Existing user servers remain running with their previously loaded code.

## Remaining work

The generated world still needs a reachable grid-appropriate gathering tool with a Workshop build contract. Personal study receipts, ordinary-player gathering in a generated mixed world, the next goal chain and broader AI play remain pending. Admitting a native point does not provide these automatically. Reliable generated rover route/delivery acceptance also remains open as recorded in the [learning checkpoint](player-learning-checkpoint.md).
