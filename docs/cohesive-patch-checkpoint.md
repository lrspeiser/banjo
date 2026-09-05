# Finite rectangular cohesive patch reference

Local source `9b1229feb58647bfcfe56165634102777742c3d4`, September 5, 2026. Not pushed or merged; full goal remains active.

`makeRectangularCohesivePatch` derives interface area from width and height and distributes it over midpoint quadrature sites. Each site has two body-local attachment coordinates, initial gap, area and independent opening/damage history. `advanceCohesivePatch` applies all site forces to the same two moving, rotating bodies. The half kicks sum their impulses and torques before one shared drift, then update each site's history and apply the second half kicks. Bending can therefore open and damage one region while another closes.

The initial faces must be corresponding congruent rectangles across a positive normal gap. Body-local tangent bases must be orthonormal and agree after rotation into world space. Width/height are positive finite; 1 to 16 cells per axis permits at most 256 sites. Geometry area is width*height, and site area is that value divided by site count. The common law's area field is explicitly ignored by this API: each site's geometric area supplies it. The constructor does not verify that the authored rectangle lies on the body's actual boundary, nor does it intersect arbitrary shapes.

This is an area-weighted central-connector approximation. Site forces act along the current line between corresponding points; it is not a complete surface-normal/mixed-mode interface law. Compression has zero cohesive force and lacks a contact owner, so the closing side can overlap. No claim of a realistic welded, glued or cut wood joint follows from these tests. Adaptive stepping from the single-site API is not yet generalized to patches. The bounded single-step patch solver reports numerical energy error and checks geometry/state/site count, aggregate stiffness screening and rotation screening; it does not enforce a caller's global energy budget.

## Comparative bending tests

Glass, oak and iron use identical 0.012 by 0.01 by 0.008 m solid boxes with density-derived mass and principal inertia. Centers are at x=+/-0.016 m. Interface rectangles lie at local x=+/-0.006 m and span width 0.01 m along y and height 0.008 m along z, leaving initial gap 0.02 m and physical area 0.00008 m2. This deliberately gapped reference tests mechanics, not a touching joint. Each experiment starts with only body B spinning around z.

Initial rotational energy is 0.25, 1 or 4 times area*Gc. Each uses 4, 16 or 64 quadrature sites and 2048 time steps over failure_opening/(0.005*initial_angular_speed): 27 material/loading/resolution combinations. Earlier exploratory runs at the lower loads did not satisfy the intended damage assertion in the coarse case; those loads were retained without requiring damage, and a declared 4*area*Gc case was added. No strength or solver tolerance was changed to force damage.

At the high load, minimum damage is zero and maximum sampled damage is:

| Material | 4 sites | 16 sites | 64 sites |
|---|---:|---:|---:|
| Glass | 0.550831 | 0.841761 | 0.916059 |
| Oak | 0.556729 | 0.844046 | 0.917713 |
| Iron | 0.715310 | 0.909526 | 0.965894 |

Every grid preserves total area within 1e-16 m2. High-load tests require a damage range greater than 0.01. Per-step angular residual must remain below 1e-10 kg m2/s, and maximum whole-trajectory kinetic+stored+damage-energy error must be below area*Gc*1e-4 J. Full logs include all low/high cases and both per-step and trajectory energy residuals. These are bounded checks, not demonstrated spatial convergence: higher grids sample closer to rectangle edges, and the maximum is not a common-point comparison. Integrated moment/work and timestep convergence remain needed before application use.

Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass; environment remains CMake 4.1.2/Core Ultra 9 285K. Reproduce with `banjo_cohesive_rigid_tests`. Logs are exported. The owned starter was intentionally stopped for relinking and restarted; no fresh native gameplay validation is claimed.

Next: area-integrated spatial convergence, patch-level adaptive/error budgets, compression/contact ownership and geometry validation against actual objects. Realistic cutting, grain, plasticity, damage-preserving remeshing, default fracture defects and remaining platform gates remain open. This reference is not yet connected to the starter tree. All 40 scorecard rows are preserved.
