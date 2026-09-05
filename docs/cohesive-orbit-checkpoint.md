# Analytical circular-motion checkpoint

Local source `faa78bb8493a480afab07344959b638c7e09259b`, September 5, 2026; not pushed or merged. Full goal remains active. This adds verification to the existing spatial cohesive reference without changing its runtime or tolerance contract.

An independent circular-orbit solution tests trajectory accuracy, beyond the preceding conservation checks. With elastic opening q, radius r and reduced mass mu, the constant interface tension is F=A*K*q, relative speed is sqrt(F*r/mu), and period is 2*pi*r/speed. After one revolution, position and velocity must return to their initial values. Initial velocities split relative motion according to the two finite masses, with zero COM velocity.

Glass, oak and iron retain area 0.0001 m2 and masses from density times area times coupon lengths 0.01 and 0.02 m. Each uses rest distance 10 times failure opening and elastic opening 0.1 times damage-onset opening. These dimensionless controls intentionally scale physical geometry with the constitutive opening scale; this is not a common-size material-performance comparison. All use the same 512/1024/2048 steps per period. Every public step is asserted to use exactly one internal substep, so refinement is not hidden by automatic subdivision. Damage work must remain exactly zero throughout.

| Material | Period, s | Relative position/velocity error at 512 steps | At 1024 | At 2048 |
|---|---:|---:|---:|---:|
| Glass | 2.28294e-5 | 7.88513e-5 | 1.97131e-5 | 4.92831e-6 |
| Oak | 6.75302e-5 | 7.88513e-5 | 1.97131e-5 | 4.92831e-6 |
| Iron | 8.15152e-4 | 7.88513e-5 | 1.97131e-5 | 4.92831e-6 |

Relative position error is endpoint Euclidean distance divided by radius; relative velocity error uses relative-velocity difference divided by initial relative speed. Tests require successive maximum-error ratios between 3.8 and 4.2 and finest error below 1e-5. Maximum relative radius drift observed across all runs is 3.20806e-15, against a 1e-8 bound. Equal nondimensional errors are expected for these similarly scaled elastic orbits; they do not establish equivalent material behavior.

The targeted Windows Release build and all 19 CTest suites pass. Reproduce with `banjo_cohesive_spatial_tests`. Environment is unchanged from the spatial checkpoint: MSVC 19.44, CMake 4.1.2, Core Ultra 9 285K. Only tests and documentation changed, so the starter executable and running user session were left untouched. Logs accompany this note.

This establishes second-order temporal convergence for a smooth elastic circular orbit. It does not establish turning damage-path convergence, arbitrary length-scale accuracy, intrinsic rigid-body rotation, actual interface geometry, wood grain, plasticity or realistic cutting. Next: rotating extended-body attachment mechanics with both force arms and intrinsic angular momentum, plus damaging-turn refinement. Existing full-pipeline conservation and fracture defects remain open; retain all 40 scorecard rows and all goal gates.
