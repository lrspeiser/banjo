# Work-accounted opening-interface reference

Source `5360f032ceed78dd511c0b989310fb351d833a33`, local `codex/physics-foundation`, September 5, 2026. Not pushed or merged. Gates 1 and 2, realistic branch cutting and the complete platform remain open.

The default brittle solver still deletes bonds after strain-history thresholds and reports their removed spring energy as unassigned. That diagnostic is not a constitutive fracture-work model. This checkpoint introduces a separately selected scalar normal-opening interface reference in `physics/CohesiveInterface`, with an explicit law/state/response API and a reproducible coupon probe. It does not replace the old solver, alter the starter branch-release approximation, or claim a repaired default fracture pipeline.

## Law and boundary

A linear elastic rise followed by linear softening can define fracture energy through the area under its traction–separation curve. Irreversible maximum-opening history supports linear unloading/reloading without healing. This model family and the relation between critical opening and energy are documented in [Abaqus Contact Cohesive Behavior](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEITNRefMap/simaitn-c-cohesivebehavior.htm). Banjo implements the pure normal-opening case; this is not a claim of Abaqus equivalence or validation.

Inputs are stiffness K in Pa/m, peak strength S in Pa, fracture energy Gc in J/m² and physical interface area A in m². Damage begins at d0=S/K; full separation occurs at df=2Gc/S. Validation requires positive finite parameters and df>d0. The envelope is K*d before d0, then S*(df-d)/(df-d0), then zero. A persistent maximum opening determines the degraded unloading stiffness. Negative opening supplies no cohesive compression force; separate contact is required. Full separation does not heal upon closing.

The response exposes force/traction, stored recoverable energy, irreversible damage work, damage and separation state. Each monotone opening increment independently integrates its piecewise-linear force path. The work-conjugate average force is distinct from endpoint force. The reported residual is integrated work minus stored-energy change minus damage-work change; it is not silently assigned to heat or another store. A whole loading/unloading/reloading history consumes A*Gc at separation and cannot refund damage work. There are no arbitrary impulses or material-name branches.

## Tests and measured evidence

Windows Release build passes and all 17 suites pass in 13.26 seconds. The new tests cover peak traction, elastic/no-damage behavior, increments crossing onset/full separation, 1/4/17/1000-increment loading, unloading/reloading, no healing, no double charge, invalid history/parameters and uniform area partition into 1/4/16/100 patches. Area partition is a prescribed uniform-opening check, not proof of spatial crack convergence.

The probe records 300 prescribed increments per material: load to 0.6df, unload to zero, then reload beyond df. Area is 0.0001 m². Catalog strengths/Gc are illustrative inputs, not newly calibrated material measurements. Stiffness is explicitly chosen as 2*S²/Gc, giving the same d0/df=1/4 ratio for the three comparisons; it is not inferred from lattice bond count.

| Input set | Gc, J/m² | Separation work A*Gc, J | Measured cyclic work, J | Maximum incremental residual, J |
|---|---:|---:|---:|---:|
| Glass | 8 | 0.0008 | 0.0008000000000000001 | 2.34e-19 |
| Oak | 1000 | 0.1 | 0.10000000000000002 | 1.21e-17 |
| Iron | 100000 | 10 | 9.999999999999993 | 1.97e-15 |

Tests require residual/work agreement within max(1e-12 J, A*Gc*1e-11). No tolerance was relaxed to accommodate a failure. These are normal cohesive reference tests, not realistic wood/iron failure predictions, timestep convergence of dynamic fracture, or proof of a closed full-world ledger.

## Next required integration

Couple the work-conjugate law to finite-body dynamics with measured momentum/reactions and a stable nonlinear solve. Define physical interface geometry and area from matter, preserving area/history through refinement and topology changes. Add mixed-mode shear, compression/contact ownership and material-specific response/calibration before general cutting, adhesives or fastener failure. Resolve existing default contact/floor correction energy and over-fragmentation independently; the new reference cannot hide those defects. No thermal, plastic, grain, fatigue, tool-processing or fabrication-energy model is implemented here.

Run `banjo_cohesive_probe OUTPUT.csv` for the 900-row cycle trace and `banjo_cohesive_interface_tests` for the analytical checks. Standard Release build/CTest commands apply. Environment remains Windows 11 Pro 26200, MSVC 19.44 x64 Release, CMake 4.1.2, Core Ultra 9 285K and the existing Jolt/raylib runtime. This pure CPU reference has no new visual controls; no new interactive fracture claim follows.
