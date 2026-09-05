# Integrated patch refinement: convergence remains open

Local source `716c27d97316b7475aefb4ee2c587ba4ae37de70`, September 5, 2026. Not pushed or merged; full goal remains active. Tests and documentation changed; runtime is unchanged.

The finite-patch experiment now compares 4, 16, 64 and 256 sites for glass, oak and iron at initial rotational energies 0.25, 1 and 4 times area*Gc: 36 cases. All retain the preceding rectangular geometry, material parameters and 2048 timesteps per material/loading interval from the [patch checkpoint](cohesive-patch-checkpoint.md). The new diagnostics sum dissipated work across the physical area and compare body B's final angular momentum across grids.

Damage-work differences are divided by area*Gc; spin differences by initial body-B angular momentum magnitude. These reference scales are not the final damage work or final spin, so a small normalized difference can still be large relative to a small damaged region. Comparing an area integral avoids interpreting a changing maximum sample location as convergence.

| Material | Loading factor | 64-to-256 normalized damage-work difference | Normalized spin difference | Damage difference decreased from preceding grid pair? |
|---|---:|---:|---:|---|
| Glass | 0.25 | 0.00183243 | 0.00140259 | No |
| Glass | 1 | 0.000288524 | 0.000972332 | No |
| Glass | 4 | 0.000159119 | 0.0000664099 | Yes |
| Oak | 0.25 | 0.00180049 | 0.00135961 | No |
| Oak | 1 | 0.000294616 | 0.00100304 | No |
| Oak | 4 | 0.000158249 | 0.0000633262 | Yes |
| Iron | 0.25 | 0.000704636 | 0.000676141 | Yes |
| Iron | 1 | 0.00367454 | 0.000478394 | No |
| Iron | 4 | 0.000190951 | 0.0000101735 | Yes |

Spin differences decrease in all nine comparisons. Damage differences do not decrease in five of nine. For low-load glass, finer sampling resolves previously undersampled edge damage; the 64-to-256-site change is larger than the 16-to-64 change. This is evidence against claiming demonstrated asymptotic spatial convergence at the present resolution. Further event/space refinement or better quadrature is needed; results do not certify realistic joint failure.

The first regression required both decreasing damage difference and a difference below 0.02 of reference work. It failed on low-load glass. The monotonic requirement was replaced with an explicit diagnostic flag, while the original 0.02 bound was retained for both work and spin. Thus passing tests prove bounded agreement for these grids, not monotonic convergence. No physics law, numerical solver or tolerance bound was changed. Existing area, damage variation and whole-trajectory energy checks remain.

Targeted Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass. Environment remains CMake 4.1.2/Core Ultra 9 285K. Reproduce with `banjo_cohesive_rigid_tests`; logs contain all grid integrals and flags. No application binary changed and the running starter was left untouched. No new native verification is claimed.

Next: establish an independent prescribed-bending integration oracle and resolve the damage front before relying on dynamic spatial convergence. Patch-level timestep/error control and compression/contact ownership also remain required before integration. Realistic cutting, grain/plasticity and all other goal gates remain open; all 40 scorecard rows are retained.
