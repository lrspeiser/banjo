# Rotational assembly loading and small-box inertia correction

September 5, 2026. Local source `e86cb8e`; not pushed or merged. Full platform goal active.

The public version-2 Jolt assembly test accepts optional `initial_angular_velocity_rad_s`, an object mapping exactly the two declared part IDs to world-space rad/s vectors. Both vectors must be finite and have length at most 10 rad/s. Omitting the field preserves zero spin. Spin is initialized once; subsequent rotation follows the simulation. Total actual initialized kinetic energy, including spin, is capped at 10000 J. Requested separating energy remains a distinct input. The report now separately records initial rotational kinetic energy. Unknown/missing IDs and out-of-bound spin reject without changing the caller world.

## Physical defect found and corrected

An independent analytical initial-energy assertion failed for the 0.02 m oak cube. In the pinned Jolt source, `MotionProperties::SetMassProperties` substitutes radius-one sphere inertia when the principal-inertia diagonal is considered near zero. A valid small box can trigger that absolute threshold. The two-box oak fixture then began with 0.01008567 J of rotational energy instead of 0.00000735 J, approximately 1372 times the intended amount. Earlier aligned tests had no spin and did not reveal it.

The box adapter now installs the known analytical box principal inverse inertias and identity local principal-axis rotation directly after body creation, before any simulation step. It validates representability first and retains cleanup on failed initialization. Jolt still applies the body's orientation to produce world inertia. The correction applies to dynamic boxes of every substance, without material-name dispatch. Tiny 0.002 by 0.003 by 0.004 m rotated glass/oak/iron boxes now pass independent diagonal/off-diagonal tensor checks within 1e-6 relative scale. The spinning two-box fixture matches analytical rotational energy within 1e-6 relative tolerance.

This correction does not establish the same guarantee for spheres or arbitrary fragment tensors; those adapters still need a threshold audit.

## Compatibility

The current runtime identity is now `jolt-5.6/banjo-rigid-primitives-v3-analytic-box`. Saved v2 primitive-runtime identities reject instead of silently changing inertia on reload. The older sphere-only v1 compatibility path remains separate. The existing precision converter does not migrate this runtime identity; explicit source-preserving migration remains required before promoting existing graphical workspaces. Their old binaries/saves are untouched and were not restarted in this checkpoint. New runtime CLI reports carry the new identity.

## Off-center experiment and retained failures

Glass, oak and iron use two 0.02/0.03 m boxes, 0.001 m face gap, 0.01 by 0.012 m patch with 4 by 4 sites and a 0.003 m face-u offset. Initial world angular velocities are (0,0,3) and (0,0,-2) rad/s. Duration is 0.1 s. The intentionally compliant law has 0.005/0.02 m onset/failure openings: S=2*Gc/0.02 and K=S/0.005. Initial relative translation energy is 0.1*A*Gc. The integration-error criterion is 0.0009*A*Gc, transfer budget is 1e-6*A*Gc per kick, and required separated fraction is zero so the criterion measures integration quality without demanding fracture. These are illustrative joints, not calibrated materials or a cutting model.

| Material | 512-step max integration error J | 1024-step error J | 2048-step error J | Budget J |
|---|---:|---:|---:|---:|
| Glass | 1.331589e-9 | 4.723117e-10 | 1.887638e-9 | 8.64e-7 |
| Oak | 4.792164e-4 | 2.294805e-4 | 1.127769e-4 | 1.08e-4 |
| Iron | 0.4807246 | 0.1165832 | 0.0565000 | 0.0108 |

Glass meets the criterion but its very small error is nonmonotonic under refinement. Oak and iron fail at all three listed resolutions. Iron still fails at the supported maximum 4096 steps with error 0.02345352 J. No tolerance or step limit was loosened to turn these results green. Regression tests preserve iron's reported failure while verifying API execution, analytical starting energy, evolving spin, input validation and caller-state immutability.

At 2048 steps, maximum angular-momentum changes are 7.55339e-10, 1.43165e-10 and 2.38091e-9 kg m2/s for glass/oak/iron. Before the inertia correction, oak showed 4.27095e-7 in this experiment. This improvement does not discharge full angular/energy conservation. The integration residual excludes separately reported Jolt-stage energy change and signed transfer roundoff; it is not a certificate that the total simulation conserves energy. One contact event is reported per trial and can be speculative; actual collision timing/impulse requires stronger evidence. Damage work stays zero in these fixtures.

## Next work

Localize the remaining error around contact and tension/slack transitions, establish event/timestep controls and full trajectory ledgers, and audit the other mass/inertia adapters. Add explicit runtime migration before native promotion. Persistent joints and resource/energy-backed crafting remain open; this evidence prevents claiming the aligned separation fixture is sufficient for realistic branches or tools. All 40 mechanics/platform rows and the complete goal remain active.

## Regression verification

All test executables and the runtime cohesive probe rebuilt successfully in both configurations. All 27 double-position suites pass in 25.21 seconds and all 25 legacy suites pass in 19.84 seconds. Passing regression tests includes retaining failed iron trial reports, not certifying those dynamics. Windows 11 / MSVC 19.44 x64 Release / CMake 4.1.2 / Jolt 5.6. The double-position creator CLI was rebuilt; ten rotational command/result artifacts were exported. No new native UI or live crafting interaction is claimed.
