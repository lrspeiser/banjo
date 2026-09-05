# Audited impulses between live rigid bodies

Local source `2fa2fe257822c13401ffb7776bc85f571f7e1211`, September 5, 2026. Not pushed or merged. Full goal remains active.

`JoltWorld::applyPairImpulse` applies an externally supplied equal/opposite impulse at two world-space points. It changes linear and angular velocities using the current solver mass and full world inertia, leaves poses unchanged, and returns measured before/after mechanical totals, impulse work, numerical energy change, linear momentum error, applied couple and angular momentum error. Work is the reference midpoint attachment-velocity work; it is not inferred solely by subtracting runtime kinetic energies. A noncentral impulse at distinct points supplies a net couple `(point_a-point_b) cross impulse`; its source remains the calling law's responsibility.

The operation requires explicit External ownership of the entire body pair and two unrestricted, unpinned dynamic bodies. It preflights both candidate states before changing either body, including finite inputs, float representability, Jolt speed limits and a caller-specified absolute roundoff-energy budget in joules. Static reactions and pinned/locked bodies are unsupported. Like the ownership API, this is a host-thread operation between steps, not a concurrent or durable transaction. The velocity setter activates moving bodies normally.

Jolt's float-rotated inverse inertia produces a small nonsymmetric component on read-back. The adapter solves using the symmetric part of the measured world inertia, rejecting skew above 1e-6 of the largest tensor component. The mechanical ledger retains the raw read-back tensor so the transfer error includes this approximation. The strict double reference's tensor validation is unchanged. Jolt's own float speed-norm comparison is checked before its clamping setter; no energy-losing clamp is silently accepted.

## Three-material verification

Identical fixtures use glass, oak and iron: oriented boxes of 0.1 x 0.15 x 0.2 m and 0.15 x 0.12 x 0.08 m, different initial velocities/spins, off-center application points, and impulse magnitude proportional to the first body's mass. Both central and noncentral cases are tested. An independent homogeneous-box principal-axis torque oracle checks angular velocity to 2e-6 rad/s; linear response tolerance is 1e-7 m/s. Material names only select catalog properties.

| Material | Central work J | Central numerical dE J | Noncentral work J | Noncentral numerical dE J |
|---|---:|---:|---:|---:|
| Glass | 4.08383 | 3.81714e-8 | 0.580245 | -2.21509e-8 |
| Oak | 1.14347 | 2.72224e-8 | 0.162469 | -1.40859e-8 |
| Iron | 12.8559 | 6.10148e-7 | 1.82661 | -9.44218e-8 |

Accepted fixtures use a 1e-5 J transfer budget and independently require absolute error below 1e-12 + 2e-7 times initial kinetic energy plus absolute impulse work. Largest measured momentum residual is 2.56437e-7 kg m/s; largest angular residual after the explicit couple is 6.24164e-8 kg m2/s. These are instantaneous float-transfer measurements, not whole-trajectory conservation bounds.

Tests also cover energy withdrawal by the reverse impulse, reversed logical-ID ordering, measured receipt equality with actual runtime totals, rejection with half the observed roundoff budget, nonfinite/extreme inputs, speed overflow of the second candidate, and pinned/ordinary-Jolt ownership rejection without changing either body's snapshot. A separate static-body rejection fixture uses oak. After an accepted transfer, a 1/240 s live step follows the independently predicted translation within 1e-7 m and produces no duplicate impact event. The bodies are separated in this fixture; the prior overlap/contact-cache routing tests remain part of the suite.

Full MSVC Release build and all 23 CTest suites pass in 18.95 s; new impulse suite 0.02 s. Required custom frame control, busy wait and static MSVC runtime flags remain OFF. Environment: Windows 11, MSVC 19.44 x64, CMake 4.1.2, Jolt 5.6, raylib 6, Core Ultra 9 285K, RTX 5090. Starter and workshop were stopped for relinking and restarted successfully; no new native-input verification is claimed.

## Remaining work

This API supplies a live transfer boundary, not a joint/contact law, a physical work source or a fabrication process. No application path calls it yet. Next integrate joint impulses and their stored/damage energy with live drift and all surface contacts, account for splitting/roundoff over the trajectory, and test timestep refinement. External ownership still suppresses every surface of the body pair; a small cohesive patch alone cannot provide all those responses. Static reactions, partial-face routing, realistic cutting, material calibration, spatial convergence, fabrication transactions, and existing default fracture-pipeline defects remain open. All 40 scorecard rows and all full-goal gates remain retained.
