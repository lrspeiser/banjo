# Reversible interface compression

Local source `ef7e2c4438a9b863568378306e107f49daa55e3c`, September 5, 2026; not pushed or merged. Full goal active.

The cohesive law now has optional `compression_stiffness_pa_per_m`, default zero. For negative opening q, traction is Kc*q, force A*Kc*q and stored energy A*Kc*q²/2. Compression work is integrated independently over negative opening. Positive-opening traction/damage remains the existing cohesive law. Compression can return its stored energy but cannot refund fracture work or heal the maximum-opening history. Even after complete tensile separation, negative opening can carry compression if Kc is enabled; `separated` therefore describes tensile failure, not absence of all force.

The distributed patch is the supported dynamics owner for this option, including its adaptive wrapper. Aggregate timestep screening includes compression stiffness even after all sites have failed in tension. Legacy collinear, central-point and single-rigid-point solvers explicitly reject nonzero compression because their force bounds/solves have not been validated for it. Defaults preserve all preceding tension-only behavior. Invalid negative/nonfinite compression stiffness rejects.

This is a compliant central-connector response around the authored rest distance. It is not general surface collision detection, a hard nonpenetration constraint, friction or calibrated crushing. For the present gapped reference it behaves as a compressible interface layer. Connecting it to real object contact requires a defined reference geometry and one contact owner; it must not be stacked on an independent collision response for the same interaction. No application integration or physically realistic tree cutting is claimed.

## Verification

Glass/oak/iron constitutive cycles fully separate in tension, compress by 0.1*failure_opening, and release to zero. Tests check the analytical compression force, work balance, returned elastic energy, retained fracture work and damage=1 after release. Compression stiffness equals tensile stiffness for this illustrative experiment, not a calibrated material claim.

A dynamic oracle uses the same two density-derived 0.012 by 0.01 by 0.008 m boxes and 16-site 0.01 by 0.008 m patch with 0.02 m rest distance. Every site starts tensile-separated at zero current opening. Opposite velocities supply closing kinetic energy 0.1*A*Gc. With reduced mass mu and frequency sqrt(A*Kc/mu), an elastic half-period pi/frequency should return the relative speed with reversed sign. Adaptive energy budget is A*Gc*1e-6 J, state tolerance 1e-5, maximum 65536 evaluations.

| Material | Evaluations | Relative rebound-speed error | Accumulated absolute energy error, J |
|---|---:|---:|---:|
| Glass | 2479 | 5.49582e-9 | 3.54751e-10 |
| Oak | 2479 | 6.24856e-9 | 4.43464e-8 |
| Iron | 2479 | 6.25859e-9 | 4.43467e-6 |

The speed error must be below 1e-4 and all site damage must remain exactly 1. Existing tension-only, area, asymmetric, adaptive and bending-oracle tests remain passing. Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass; environment remains CMake 4.1.2/Core Ultra 9 285K. Reproduce with `banjo_cohesive_interface_tests` and `banjo_cohesive_rigid_tests`. Logs are exported. The owned starter was intentionally stopped for relinking and restarted; no new native gameplay verification is claimed.

Next: bending with simultaneous tensile damage/compression, contact-reference geometry and spatial comparisons under controlled timestep error. Unilateral compliance does not discharge hard-contact, shear, grain/plasticity or cutting requirements. Default full-pipeline fracture defects and all remaining goal gates stay open; all 40 scorecard rows are retained.
