# Simultaneous compression and tensile damage

Local source `08267f876d87ad29e0a7173b4a02ef43d1e02e97`, September 5, 2026; not pushed or merged. Full goal active. Tests/documentation only; the runtime law and tolerances are unchanged.

The distributed patch now has a combined bending regression, beyond separate compression-rebound and tension-only tests. It uses the established 64-site 0.01 by 0.008 m interface, 0.02 m rest gap, density-derived 0.012 by 0.01 by 0.008 m rigid boxes, and initial body-B rotational energy 4*area*Gc. Compression stiffness equals the illustrative tensile stiffness. All glass/oak/iron cases use these same geometry and dimensionless initial conditions.

Duration remains failure_opening/(0.005*initial_angular_speed). Adaptive accumulated-energy budget is area*Gc*1e-6 J; state tolerance is 1e-5 and maximum evaluations 65536. The completed state must have nonzero numbers of sites in compression, tension and irreversible damage. Total linear momentum must stay below 1e-10 kg m/s and total angular momentum must differ from the initial spin by less than 1e-10 kg m2/s. Final kinetic+stored+damage energy must match initial energy within the requested budget plus 1e-12 J roundoff allowance.

| Material | Compressed / tensile / damaged sites | Damage work, J | Final energy error magnitude, J | Angular momentum error, kg m2/s | Evaluations |
|---|---|---:|---:|---:|---:|
| Glass | 32 / 32 / 24 | 0.000108510 | 2.75350e-10 | 4.60786e-19 | 1447 |
| Oak | 32 / 32 / 24 | 0.0136842 | 3.44715e-8 | 4.64852e-18 | 1441 |
| Iron | 24 / 40 / 24 | 1.77832 | 3.61118e-6 | 1.45283e-16 | 1435 |

Counts describe endpoint force signs and damage states, not predetermined sectors. Material-dependent opening scales change the finite rotation and neutral region; identical counts are not required. There are no assigned fracture outcomes or impulses beyond the constitutive forces.

Targeted Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass. Environment remains CMake 4.1.2/Core Ultra 9 285K. Reproduce with `banjo_cohesive_rigid_tests`; logs include all retained experiments. The application binary and running starter were untouched; no new native gameplay verification is claimed.

This demonstrates simultaneous responses in an idealized compliant joint, not real surface contact or validated branch cutting. The interface remains a gapped central-connector model with no shear/friction, physical crushing or grain. Spatial damage-front convergence is still unresolved. Next: validate interface reference geometry against actual authored parts, prevent duplicate contact ownership, and compare spatial grids with controlled temporal error before exposing attachments through the application. All remaining goal gates and 40 scorecard rows remain active.
