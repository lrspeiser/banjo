# Asymmetric cohesive rigid verification

Local source `c56988a6157f157d56bb50b9048d3ea7b6329a8d`, September 5, 2026. Not pushed or merged; full goal remains active. This checkpoint changes tests, not the runtime or numerical tolerances.

The coupled rigid reference now has an unequal-body experiment with distinct orientations, noncoplanar attachment offsets, nonzero COM velocity and total angular momentum. It checks whole-trajectory totals relative to the initial state, rather than relying on per-step cancellation in the earlier symmetric setup. All three catalog substances are retained under the same geometry and dimensionless loading protocol.

Body A is a 0.012 by 0.01 by 0.008 m box rotated 0.3 rad around z; B is a 0.014 by 0.009 by 0.01 m box rotated 0.4 rad around y. Mass and principal inertia follow density and solid-box dimensions. Local attachments are (0.005,0.003,0.002) and (-0.006,-0.003,0.003) m. A's center is (-0.015,0,0) m; B is placed so the initial attachment separation is 0.02 m along normalize(1,0.1,-0.2). Area is 0.0001 m2, with the preceding illustrative K=2*S*S/Gc law. Surface geometry is not yet derived from a joining process.

Initial relative speed is sqrt(12*A*Gc/reduced_mass), directed along normalize(1,0.2,0.3). This supplies relative kinetic energy 6*A*Gc, with an additional common velocity speed*(0.13,0.07,-0.05). Initial spin is zero. Each case runs 512/1024/2048 steps over 8*failure_opening/speed. Both bodies must acquire spin and the interface must separate during the declared interval. The duration differs by material because this is a dimensionless loading comparison, not a common-duration performance claim.

| Material | Duration, s | Finest maximum energy error, J | Finest max linear momentum error, kg m/s | Finest max angular momentum error, kg m2/s | Relative endpoint-velocity difference, 1024 to 2048 |
|---|---:|---:|---:|---:|---:|
| Glass | 1.07146e-6 | 3.85477e-9 | 8.11632e-18 | 7.90489e-17 | 2.00244e-7 |
| Oak | 3.16942e-6 | 4.66444e-7 | 6.50290e-17 | 2.67233e-15 | 1.11750e-7 |
| Iron | 3.82579e-5 | 3.78102e-5 | 1.58085e-15 | 1.99582e-15 | 6.32315e-7 |

Energy error includes kinetic, stored and damage energy relative to initial energy. Tests require finest error below A*Gc*1e-4 and below one quarter of the 512-step error. Finest relative-velocity difference must be below 1e-4 of initial speed and smaller than the preceding refinement difference. Whole-trajectory momentum tolerances are absolute 1e-12 SI plus 1e-10 times the initial vector magnitude. No tolerance was relaxed. Fine velocity agreement is a convergence comparison, not agreement with an independent exact damage solution. Nonsmooth damage events do not establish a uniform temporal order.

Targeted Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass. Environment remains CMake 4.1.2/Core Ultra 9 285K. Reproduce with `banjo_cohesive_rigid_tests`; complete logs are exported. No viewer code changed, and the running starter was left untouched; no new native verification is claimed.

The coupled solver now has evidence beyond symmetric cancellation, while numerical energy error remains explicit and uncorrected. Next: resolve damage events and derive finite attachment geometry/contact ownership before connecting this law to application objects. Actual cutting, grain, plasticity, joining processes, default fracture defects and all remaining platform gates stay open. The full 40-row scorecard is retained.
