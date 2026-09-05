# Coupled rigid cohesive dynamics checkpoint

Local source `ae7c4958ab8bb3691f7c575b94cfae695e3ccbbf`, September 5, 2026, not pushed or merged. Full goal remains active.

`advanceCohesiveRigidPair` now couples evolving rigid-body attachment points to the normal cohesive law. Body state contains mass, three principal moments of inertia, world COM/velocity/angular momentum, orientation quaternion and local attachment coordinates. Off-center cohesive forces change translation and spin; rotated attachments determine subsequent opening and irreversible damage. The existing full-tensor impulse primitive supplies both half kicks.

## Numerical method and limits

The step uses endpoint-force half kick, free translation/rotation, updated geometry and cohesive history, then endpoint-force half kick. Free asymmetric rotation uses the symmetric sequence of exact principal-axis kinetic Hamiltonian flows: x/2, y/2, z, y/2, x/2. World angular momentum remains fixed during that drift; orientation changes. No orientation normalization, velocity projection or invented release impulse is used. Complete-interface failure removes its force through the existing law.

This method has numerical energy error. The API reports kinetic plus stored plus damage-energy change as an error, without relabeling it as heat or subtracting it from velocities. It does not promise exact energy conservation or automatically enforce a caller energy tolerance. It is an experimental reference, unsuitable for silently replacing the production fracture path. The caller must refine and judge measured error. Damage maxima are sampled at step endpoints, so unresolved within-step extrema and nonsmooth transitions remain limitations.

Mass/inertia, finite state, unit quaternion within 1e-10 and geometry/opening consistency are checked. The underlying impulse primitive also checks full-tensor conditioning. dt must be positive and at most 1 s. A pre-step rotational advance above 0.1 rad rejects. Before complete separation, dt*sqrt(stiffness*effective_mobility) above 0.1 rejects, with mobility bounded by inverse mass plus arm-length-squared/minimum principal inertia. This is a conservative stiffness screening rule, not an error estimator or general stability proof. Point separation below one quarter of rest length rejects. Excess/invalid input throws without modifying the caller state. No compression/contact, shear, external forces or finite surface mesh is present.

## Three-material experiments

Glass, oak and iron use identical 0.012 by 0.01 by 0.008 m boxes, density-derived mass and solid-box principal moments. Area is 0.0001 m2. Centers initially sit at x=+/-0.015 m; local attachment coordinates are (+0.005,0.004,0) and (-0.005,0.004,0), giving rest separation 0.02 m. Initial orientations are identity and spin is zero. Opposite x velocities supply total kinetic energy 1.5 or 6 times A*Gc. All retain the preceding illustrative catalog K=2*S*S/Gc; no new physical calibration is claimed.

Each case runs 512, 1024 and 2048 steps over 8*failure_opening/initial_relative_speed. Lower input remains attached in the tested interval while transferring motion to spin; higher input separates. The first run showed that the previous point-pair expectation of separation at 1.5*A*Gc did not carry over to off-center rigid motion. That low-input case was retained and a separately declared higher-input case added; the force law and tolerances were not changed to force separation.

| Material | Fine low-input max energy error, J | Fine high-input max energy error, J | Fine low/high error divided by A*Gc |
|---|---:|---:|---|
| Glass | 1.32975e-8 | 9.73419e-9 | 1.66219e-5 / 1.21677e-5 |
| Oak | 1.66224e-6 | 1.21678e-6 | 1.66224e-5 / 1.21678e-5 |
| Iron | 1.66440e-4 | 1.21699e-4 | 1.66440e-5 / 1.21699e-5 |

Tests require finest maximum whole-trajectory energy error below A*Gc*1e-4 and below one quarter of the coarse error. Observed reduction is about 8.4 times for low input and 17.5 times for high input across fourfold refinement; no uniform order is claimed across damage events. Orientation and intrinsic spin must actually change. Per-step linear/angular residuals must be below 1e-10 SI. Reported angular residuals are zero in these symmetric trials, which is not proof of arbitrary-geometry conservation. Full conditions and all 18 run results are in the test log.

A torque-free triaxial test exercises all three rotation axes: moments (0.01,0.02,0.025) kg m2 and initial world angular momentum (0.001,0.002,0.003) kg m2/s. Over one second, maximum kinetic errors at 128/256/512 steps are 9.77544e-13, 2.44389e-13 and 6.10999e-14 J, showing second-order error reduction. World angular momentum agrees within 1e-12; an invalid quaternion rejects. This separately validates free rotation; a fully asymmetric, turning, damaging attachment remains a needed coupled test.

Full Windows Release build and all 21 CTest suites pass. Environment: MSVC 19.44, CMake 4.1.2, Core Ultra 9 285K. Reproduce with `banjo_cohesive_rigid_tests`; build and test logs accompany this note. The owned starter was intentionally stopped to relink and restarted afterward. No new native gameplay verification is claimed.

Next: asymmetric coupled angular-momentum/trajectory tests and damage-event resolution, physical interface area and contact/shear ownership, followed by supported cutting. This solver is not yet integrated into the starter tree or default fracture pipeline. Grain, plasticity, full-pipeline correction energy, over-fragmentation and realistic branch cutting remain open. Gameplay stamina still is not physical joules. Preserve all 40 scorecard rows and remaining goal gates.
