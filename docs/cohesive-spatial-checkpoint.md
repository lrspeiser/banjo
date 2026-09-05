# Three-dimensional central cohesive reference

Source `ab8bcd317299c9f08779490d30a28da869a544ea`, local `codex/physics-foundation`, September 5, 2026. Not pushed or merged. Full goal and remaining gates stay active.

The finite-pair reference now supports three-dimensional material-point motion. A central cohesive force can turn with the separation vector while accounting for kinetic energy, stored interface energy, irreversible damage work, linear momentum and orbital angular momentum. This is a separate CPU reference, not an integration into the starter tree or default fracture pipeline.

## Method and validity

For separation vectors r0 and r1, the discrete length gradient is d=(r0+r1)/(|r0|+|r1|). Its dot product with r1-r0 equals the length change. The independently integrated cohesive work supplies the scalar work-conjugate force; multiplying by d supplies its direction. The midpoint position solve uses this vector force and both finite masses. Equal/opposite impulses change velocities, and the COM moves freely. The force is parallel to the midpoint separation, preserving orbital angular momentum up to solve/roundoff residual. No residual is corrected or credited as heat.

Inputs include masses in kg, rest distance and vectors in m, velocities in m/s, timestep in s, and the existing area/stiffness/strength/Gc interface law. Geometry and opening must agree within 1e-12 times rest distance plus 1e-14 times failure opening. Point separation below one quarter of rest distance rejects. Compression contact is unsupported, even where the tension law has zero force. Constitutive assumptions and illustrative catalog provenance remain those of the [opening law](cohesive-interface-checkpoint.md).

The bounded fixed-point solve allows 100 iterations per substep. The step bound uses both constitutive slopes plus a central-direction stiffness bound; it is a convergence guard, not an accuracy estimate. Position tolerance is 2e-14 times max(rest distance, initial substep length), with final equation residual at most four times that tolerance. Calls permit at most one second and 4096 substeps; exceeding the budget rejects the immutable input. Per-call energy, momentum and angular-momentum acceptance uses an absolute 1e-12 in the respective SI units plus 1e-9 times the magnitude of the initial quantity. This new vector API has its own acceptance contract; the prior scalar API's 1e-10 relative tolerance is unchanged. No tolerance was relaxed following test failure.

These are central material points, not extended rigid bodies. Intrinsic spin, off-center force application, actual surface-area derivation, shear, compression/contact ownership, external forces, plasticity, grain and topology are absent. Tiny-opening accuracy at arbitrary length scales, temporal refinement of turning trajectories, spatial crack convergence and calibration remain unverified.

## Verification

Windows MSVC 19.44 x64 Release, CMake 4.1.2, Core Ultra 9 285K. Full build succeeds; all 19 CTest suites pass in 13.37 seconds. No viewer controls changed. The owned starter was intentionally stopped for relinking and restarted afterward; this is not a fresh native progression test.

All three substances use area 0.0001 m2, rest distance 0.001 m, masses density times area times lengths 0.01 and 0.02 m, initial relative kinetic energy 1.5*A*Gc, and the common axis normalize(1,2,3). K=2*S*S/Gc with catalog strength S and fracture energy Gc. Each runs 512 steps over duration 8*failure_opening/initial_relative_speed. The endpoint reduces to the scalar reference within 1e-5 times failure opening and 1e-6 times initial speed. Complete damage work agrees with A*Gc within relative 1e-12. These checks use existing illustrative values, not newly calibrated wood or iron models.

| Material | Max per-step energy residual, J | Max per-step angular momentum residual, kg m2/s | Separation work, J |
|---|---:|---:|---:|
| Glass | 3.90313e-16 | 4.04058e-22 | 0.0008 |
| Oak | 7.49401e-16 | 1.81018e-21 | 0.1 |
| Iron | 7.10543e-15 | 8.14064e-20 | 10 |

A separate material-neutral turning case uses K=1000 Pa/m, S=10 Pa, Gc=1 J/m2, A=0.1 m2, masses 1 and 2 kg, rest distance 0.1 m and initial transverse relative speed 1 m/s. After 1000 steps of 0.0005 s, its separation angle is 1.48097 rad. Maximum whole-trajectory energy residual is 8.32667e-16 J and orbital angular-momentum residual is 2.77556e-16 kg m2/s. A rotated, translated, velocity-boosted copy agrees in relative position and transformed velocity within 1e-10 SI. Geometry mismatch and insufficient budget reject. Conservation evidence from these isolated cases does not prove full-pipeline conservation or trajectory accuracy in general.

Reproduce with `banjo_cohesive_spatial_tests` and the standard Release build/CTest commands. Exported logs contain measured results. Next: turning-trajectory refinement, rigid-part attachment points and intrinsic rotation, physical interface geometry, one contact/shear owner, then calibrated cutting and persistent damage. Existing correction-energy and over-fragmentation defects remain open. Gameplay stamina is still separate from physical joules.
