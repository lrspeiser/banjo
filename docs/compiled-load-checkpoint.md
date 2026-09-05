# Loaded compiled box-face joints

Local source `3c5d007546adfc348ea2a893f957ea207021cc33`, September 5, 2026; not pushed or merged. Full goal active. Tests/documentation only; runtime unchanged.

The box-face compilation test now continues into adaptive physical separation. It retains the preceding 0.02/0.03 m cubes, density-derived masses/inertias, 0.4 rad world rotation, 0.001 m face gap, 0.01 by 0.012 m offset rectangles and 16-site patches. Glass/oak/iron each exercise x, y and z faces. No mass, inertia, area or attachment position is replaced after compilation; only initial velocities are supplied as the declared load.

Opposite normal velocities give zero COM momentum and relative kinetic energy 6*A*Gc. Duration is 8*failure_opening/initial_relative_speed. The tension-only illustrative law remains K=2*S*S/Gc. Adaptive energy budget is A*Gc*1e-6 J, state tolerance 1e-5, maximum evaluations 65536. Every site must separate, each body must acquire nonzero intrinsic angular momentum from the offset attachment, and total damage work must agree with compiled area*Gc within relative 1e-12. Final accounted energy must remain within the requested budget plus 1e-12 J roundoff allowance.

| Material | Separation work, J | Maximum final energy error across three axes, J | Maximum accumulated absolute energy error, J | Evaluation range |
|---|---:|---:|---:|---|
| Glass | 0.00096 | 3.74992e-11 | 6.69745e-11 | 4069–4087 |
| Oak | 0.12 | 4.67963e-9 | 8.25489e-9 | 4027 |
| Iron | 12 | 4.66161e-7 | 8.23630e-7 | 4021 |

These nine cases verify the compiler-to-solver path rather than only arithmetic geometry. They do not prove physical material calibration, arbitrary geometry, mixed materials or full-pipeline conservation. Existing separate momentum and constitutive tests remain in the suite.

Targeted Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass. Environment remains CMake 4.1.2/Core Ultra 9 285K. Reproduce with `banjo_cohesive_rigid_tests`; logs include each axis result. The application binary/running starter were untouched; no new native verification is claimed.

Next: define the bounded creator assembly contract and interface/contact ownership before exposing compiled joints in the application. Spatial convergence, shear, real surface contact, grain/plasticity and realistic cutting remain open. All 40 scorecard rows and remaining goal gates are retained.
