# Adaptive rigid cohesive advances

Local source `47ae5c6ac44cb054555b268121f2322ea8b91e30`, September 5, 2026. Not pushed or merged; full goal remains active.

`advanceCohesiveRigidAdaptive` adds bounded error control around the existing coupled rigid reference. It compares one full step against two half steps, accepts the two-half-step candidate, or recursively bisects. Only the typed timestep-screening exception is recoverable; unsupported geometry, invalid state and other failures propagate. Caller state is immutable; no partial candidate is returned on exhaustion.

Controls specify duration (0,1] seconds, positive absolute energy-error budget in joules, positive dimensionless state tolerance at most 0.1, and 3 to 65536 solver evaluations (default 8192). Recursion depth is at most 24. Every attempted solver evaluation counts, including timestep screening failures. The result reports evaluations, accepted half steps and accumulated absolute numerical energy error.

The energy measure sums the absolute energy residual of every accepted half step, avoiding cancellation between positive and negative errors. It includes kinetic, interface storage and irreversible damage work. State disagreement includes opening and maximum opening, COM positions normalized by failure opening, velocities normalized by sqrt(A*Gc/minimum_mass), angular momentum normalized by sqrt(A*Gc*minimum_principal_inertia), and sign-invariant quaternion distance. This is a step-doubling estimate, not a rigorous global trajectory bound.

Local budgets use max(interval/duration,1/maximum_evaluations) times the respective requested tolerance. An initial version used interval/duration alone and exhausted refinement depth near damage transitions as the allocated tolerance shrank toward roundoff. The bounded local floor was added after that failure. The requested global energy cap remains unchanged: an accepted segment may not push the accumulated absolute error above it, and a final check enforces it. No error is corrected by changing velocity or treated as physical dissipation. The state-disagreement tolerance has no asserted global bound.

## Comparative evidence

Tests retain the unequal-box geometry, initial orientations, off-center attachments, velocity boost and 6*A*Gc relative kinetic input from the [asymmetric checkpoint](cohesive-asymmetric-checkpoint.md). Both requested tolerances are tested for glass, oak and iron with maximum 65536 evaluations. Absolute energy budgets are A*Gc times 1e-4 or 1e-5; state tolerance uses the same dimensionless value. All candidates separate, remain within the requested accumulated energy cap and have smaller accumulated error under the tighter request. A three-evaluation budget rejects the entire advance.

| Material | Tolerance | Evaluations | Accepted half steps | Accumulated absolute energy error, J | Final energy error magnitude, J |
|---|---:|---:|---:|---:|---:|
| Glass | 1e-4 | 647 | 248 | 5.31319e-9 | 3.16282e-9 |
| Glass | 1e-5 | 2549 | 882 | 3.34547e-10 | 2.00050e-10 |
| Oak | 1e-4 | 617 | 238 | 6.63940e-7 | 3.95328e-7 |
| Oak | 1e-5 | 2543 | 880 | 4.17545e-8 | 2.49776e-8 |
| Iron | 1e-4 | 635 | 244 | 6.25749e-5 | 3.80653e-5 |
| Iron | 1e-5 | 2513 | 870 | 3.98057e-6 | 2.39005e-6 |

Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass. Environment remains CMake 4.1.2/Core Ultra 9 285K. Reproduce with `banjo_cohesive_rigid_tests`; logs are exported. The owned starter was intentionally stopped for relinking and restarted. No new native gameplay verification is claimed.

This improves error control near damage changes but does not locate exact constitutive events or guarantee that all within-step extrema are resolved. Both estimates can miss a sufficiently short event. The adaptive method is still an experimental isolated reference, with no physical interface-area derivation, shear/compression contact, calibrated grain/plasticity, starter cutting integration or full-pipeline fracture repair. Next: physical attachment geometry and contact ownership, explicit event evidence and application integration. Keep all 40 scorecard rows and remaining goal gates active.
