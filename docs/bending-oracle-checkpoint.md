# Exact prescribed-bending integration oracle

Local source `610da9c751199b85f1c70743b66b6b53b4aa8be3`, September 5, 2026. Not pushed or merged; full goal active. Only tests and documentation changed.

The new oracle separates spatial quadrature from motion integration. On a 0.01 by 0.008 m rectangle, it prescribes monotone linear opening q(y)=theta*y across y in [-0.005,0.005] m. Negative opening carries no tension. The exact total force, first moment and irreversible damage work come from directly integrating the elastic, softening and separated polynomial branches. Those formulas do not call the constitutive evaluator. The numerical side uses sites and areas from the production rectangular-patch constructor and the point constitutive evaluator.

Let b=width/2, a=min(b,d0/theta), c=min(b,df/theta), with d0=S/K and df=2*Gc/S. Exact force is height*[K*theta*a²/2 + S/(df-d0)*(df*(c-a)-theta*(c²-a²)/2)]. Exact moment is height*[K*theta*a³/3 + S/(df-d0)*(df*(c²-a²)/2-theta*(c³-a³)/3)]. Exact damage work is height*Gc*[theta*(c-a)²/(2*(df-d0))+max(0,b-df/theta)]. These formulas apply to this monotone loading protocol; they are not a general unloading/history solution.

Glass, oak and iron retain illustrative catalog strength/Gc and K=2*S*S/Gc. Peak opening is 0.3, 0.7 or 1.4 times df. Four grids (4/16/64/256 sites) give 36 independent material/loading/grid cases. Force error is normalized by S*area, moment by S*area*b and damage work by Gc*area. At 256 sites, the normalized errors are the same across the three dimensionlessly scaled material cases:

| Peak opening / df | Force error | Moment error | Damage-work error |
|---:|---:|---:|---:|
| 0.3 | 0.000694444 | 0.0000530478 | 0.000173611 |
| 0.7 | 0.000297619 | 0.000193984 | 0.0000744048 |
| 1.4 | 0.00476190 | 0.000629783 | 0.000744048 |

Tests require the maximum scaled error at the finest grid below 0.005 and below the coarse-grid maximum. No tolerance changed after running the test. The partially separated case is close to that bound, indicating that a uniform midpoint grid still resolves the moving branch boundary poorly. Equal dimensionless errors are expected for these scaled inputs and do not establish equivalent material behavior.

Targeted Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass. Environment remains CMake 4.1.2/Core Ultra 9 285K. Reproduce with `banjo_cohesive_rigid_tests`; exported logs include every oracle error and the retained dynamic tests. The application binary/running starter was unchanged; no new native verification is claimed.

This verifies bounded agreement with exact integrals for prescribed linear opening. It does not prove the earlier dynamic damage fronts converge, replace actual rotating geometry with this linear approximation, or validate physical compression/shear. Next: use the oracle to assess quadrature around branch transitions, then combine patch temporal error control and spatial refinement without healing damage. Realistic cutting, contact ownership, calibration and all other goal gates remain open. All 40 scorecard rows are retained.
