# Rigid attachment impulse checkpoint

Local source `6992342611c8c9db3b12bcb3619a759955769ac1`, September 5, 2026, not pushed or merged. Full goal remains active.

`applyAttachmentImpulse` applies an externally supplied equal/opposite impulse to two world-space attachment points. Each body receives J/m translation and inverse-inertia times (arm cross J) spin change. The API carries full world-space inertia tensors, so rotated anisotropic solids are supported. It is an instantaneous transfer primitive: no timestep, orientation integration, cohesive force selection, attachment surface derivation or damage update is supplied. It is not yet wired into the cohesive motion solver, starter or fracture pipeline.

The independent impulse-work expression uses the average pre/post attachment velocities dotted with the applied impulses. The result reports this work, actual translational-plus-rotational kinetic change, their residual, linear momentum residual and angular momentum residual after subtracting the net applied couple. For distinct attachment points that couple is (pointA-pointB) cross J. Central forces yield zero net couple; noncentral forces require a corresponding torque owner in the later interface model. Equal/opposite forces alone are insufficient to assert angular conservation.

Inputs use kg, m, m/s, rad/s, kg m2 and N s. Mass/state and matrices must be finite; mass positive; normalized inertia symmetric within 1e-14, positive definite and normalized determinant greater than 1e-14. This excludes ill-conditioned tensors and does not establish matter provenance. Kinetic/work residual acceptance is 1e-12 J plus 1e-10 times initial kinetic energy plus absolute impulse work. Momentum residuals are exposed and checked in tests, not clamped. Candidate computation leaves inputs unchanged. There is no assertion that the supplied impulse has a physical energy source; the eventual coupled law must establish that source.

## Common-condition comparison

All three catalog substances use identical 0.2 by 0.1 by 0.08 m solid boxes. Mass is density times volume and diagonal body inertia uses the solid-box formula. Both have the same initial velocities/spins and receive a 0.01 N s x-directed impulse at a 0.04 m y-offset. The reference centers are (-1,0,0) and (1,0,0); attachment points (-0.9,0.04,0) and (0.9,0.04,0). This tests transfer math, not the realism of a long connecting interface.

| Material | Mass of each body, kg | Spin change of A, rad/s | Work residual, J | Angular residual magnitude, kg m2/s |
|---|---:|---:|---:|---:|
| Glass | 4 | -0.024 | -2.12504e-17 | 1.11022e-16 |
| Oak | 1.12 | -0.0857143 | -3.46945e-18 | 0 |
| Iron | 12.592 | -0.00762389 | -1.63931e-16 | 0 |

Tests verify analytical spin, work and momentum to absolute 1e-12 SI, a known noncentral couple of -0.0008 kg m2/s, covariance after rotating every vector and the inertia tensor 45 degrees, an out-of-plane impulse exercising the non-diagonal inverse, and invalid inertia rejection. The first test run exposed an incorrect expected cross-product sign in the noncentral oracle; that expectation was corrected from positive to negative. No runtime law or tolerance changed to accommodate it.

Windows MSVC 19.44 x64 Release/CMake 4.1.2 targeted build succeeds; all 20 CTest suites pass in 12.25 seconds. Reproduce using `banjo_rigid_attachment_tests`; logs accompany this note. No viewer/runtime integration changed and no new native gameplay test is claimed. The running starter was left untouched.

Next: combine attachment kinematics, evolving orientation and cohesive history in a bounded dynamic solve, then test torque/work conservation and timestep refinement under separation. Actual area/geometry, compression/shear ownership, physical wood cutting and default correction-energy/fragmentation defects remain open. This checkpoint adds a required transfer primitive, not complete rotating-body cohesive dynamics. Preserve all 40 scorecard rows and remaining goal gates.
