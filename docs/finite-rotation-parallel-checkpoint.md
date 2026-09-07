# Parallel physics: rotation, tearing, metal state and thermal playback

September 6, 2026. Developed from main `d1a6a91` on Windows MSVC 19.44 Release with double Jolt. All nine workstreams, 40 retained mechanics and R01–R10 remain in scope. This is a development checkpoint, not completed glass shattering or world-scale realtime qualification.

## What each worker delivered

| Lane | Delivered and measured | Next physical dependency |
|---|---|---|
| Primary: glass and shared contact | Explicit corotated bulk/cohesive dynamics, bounded fragment-overlap audit, typed compression-handoff rejection with atomic rollback | Transfer compression energy into one authoritative fragment-contact response; resolve event timing and continued contacts |
| `surface_contact_geometry`: metal | Complete in-memory sphere/material snapshot and validated restore, including plastic history and accepted force cache | Unloaded equilibrium and a bounded versioned binary codec |
| `sphere_patch_acceptance`: cutting | Objective mixed-mode tearing, compressed-shear control and loading-increment refinement | Resolved finite blade geometry/contact and appropriate finite-strain tissue response |
| `dynamic_patch`: fire | Typed GPT thermal authoring, native execution, saved evidence and actual cell-state 3D playback | Thermal/mechanical coupling and broader validated material experiments |

These are independent assignment batches. An agent finishing its batch is not a completed physics category; the primary integrates and publishes the accepted changes while subsequent bounded dependencies can run separately.

## Finite rotations and the remaining fracture failure

`CohesiveDynamicPatch` now offers explicit `Corotated` kinematics. It combines the existing corotated tetrahedral potential with a rotating cohesive midsurface and an exact forward-mode potential gradient. The default small-displacement path is unchanged. The new path currently accepts isotropic elastic bulk with nonnegative Lamé lambda. Plastic bulk, anisotropic finite rotation and general large-strain tissue are not implied.

The spinning two-tetrahedron regression undergoes more than 0.25 rad of actual rotation with nonzero elastic stretch below the declared 0.2 limit. Angular momentum and rotated/translated experiment equivalence pass; halving the timestep reduces the accumulated absolute numerical energy error. Each active facet uses one derivative pass. The reference-configuration timestep cap is **not** a certificate for the evolving nonlinear stiffness; raw energy checks and refinement remain necessary.

The 80 × 20 × 80 mm, six-tetrahedron fictional reference from the preceding checkpoint was rerun with the new law. It remains a launched sphere into a numerical material, not a calibrated glass plate/drop. The 0.03 m/s control completes 8 ms intact. The 1 m/s case stops before full facet separation:

| Fraction of reference step cap | Accepted time | Sum of absolute numerical energy residuals | Compression energy in rejected facet 5 |
|---|---:|---:|---:|
| 0.2 | 0.320469 ms | 5.91578e-5 J | 3.99315e-5 J |
| 0.1 | 0.325182 ms | 2.87020e-5 J | 3.98470e-5 J |
| 0.05 | 0.325182 ms | 1.51233e-5 J | 4.46163e-5 J |

All three report `Severed interface retains compression energy; contact handoff required`. Some integration points have fully damaged, but zero complete facets have detached and the accepted target remains one component. The typed diagnostic identifies the rejected facet and retained energy. A regression verifies unchanged material positions, velocities, irreversible history, topology, time and energy, together with unchanged sphere motion. Deleting that compression energy or inventing fragment velocities would invalidate the result.

`FractureOverlap` adds a capped tetrahedron separating-axis audit across distinct components. Work exhaustion reports unresolved, not collision-free. This is an endpoint audit with no impulses or continuous collision guarantee. It cannot replace the missing fragment contact response.

The native probe accepts `--corotated` and emits schema v2. This development output is not yet accepted by the existing v1 cohesive playground adapter. The earlier v1 archive and the user's failed glass job remain unchanged. No new completed glass-shatter playback is claimed.

## Metal and cutting evidence

The metal snapshot fixture contains 18 nodes and 24 material points. At capture it has maximum equivalent plastic strain 1.10536e-5, stored energy 4.65448e-5 J and plastic dissipation 7.07429e-8 J. A fresh compatible world continues 300 steps bitwise-identically. Corrupt and incompatible restores reject atomically. Estimated payload is 17,558 bytes excluding allocation overhead; **this is in-memory state, not a compact serialized world format**. The 27.23 micrometre endpoint displacement alone is not evidence of a settled dent.

A separate supported unit-cube coupon now reaches actual zero-load equilibrium after forty loading and forty unloading increments. Its illustrative J2 law has E = 211 GPa, Poisson ratio 0.29, yield = 250 MPa and hardening = 1 GPa. The 270 MPa peak is chosen from the in-domain estimate `(270−250) MPa / 1 GPa = 0.02` plastic strain, preserving the 0.05 validity bound. Residual displacement is 0.0244949 m; free-force residual is 7.28705e-5 N against 8.11512e-4 N tolerance. Stored hardening energy is 200,000 J and plastic dissipation is 5,000,000 J. Trapezoidal external work of approximately 5,199,190 J closes that partition within the declared 2e-4 relative budget. The matched elastic coupon returns to 2.7586e-15 m residual displacement and zero plastic history. This is quasistatic constitutive evidence, not a sphere-produced dent or iron calibration.

The material-neutral tearing coupon rotates 2.1 rad while opening/sliding, unloads without healing and pays exactly 0.012 J (`Gc × reference area`) at complete failure. Four versus forty prescribed loading increments reduce the largest damage increment from 0.00430535 J to 0.000430535 J while retaining the same total fracture work. At 1.6 rad, compression alone causes zero fracture dissipation; added shear causes 0.0072 J. These are constitutive tests, not dynamic knife contact, a sliced tomato or a timestep-converged cutting experiment. The earlier wedge/tomato route still has a connected core and timestep-sensitive damage.

The new bounded `closestSegmentTriangle` query supplies actual closest points, barycentric weights, plane signs and geometric classification for a finite blade edge and material face. Piercing, endpoint/edge contact, coplanar overlap, separation, rigid transformations and invalid/degenerate geometry pass four tests. It does not produce impulses, continuous collision detection, damage or cutting by itself.

## Actual GPT thermal experiments and 3D

`thermal_material_experiment` accepts explicit SI material, cell, heater, horizon and work-limit descriptors. Names do not select behavior. The server executes the bounded native thermal CLI and archives the request, response, provenance hashes, diagnostics, accepted frames, reactants/products and energy ledgers. The viewer renders fixed authored cell positions with a temperature legend, play/pause, frame stepping, slow playback and cell inspection. Smoke, airflow and full fluids remain deferred; this does not render flames or invent moving/burning geometry.

Two actual GPT-authored jobs use the same two-cell geometry, density 700 kg/m³, heat capacity 1700 J/(kg K), conductivity 0.12 W/(m K), initial 300 K, finite 3000 J heater and 0.1 s horizon in ten 0.01 s steps. Only the reactive descriptor supplies fuel, oxygen and a reaction law. The inert comparator is deliberately labeled `oak-looking inert control`.

| Result | Reactive descriptor | Matched inert descriptor |
|---|---:|---:|
| Job | `bd17a88380a147d78cbef4041d89d31f` | `6ef80b0441dd46059bf7ef7c6c7efb53` |
| Accepted frames / jobs / cell operations | 11 / 10 / 60 | 11 / 10 / 60 |
| Reaction heat | 7747.396 J | 0 J |
| Final heated-cell temperature | 1428.907 K | 615.118 K |
| Mass residual | 0 kg | 0 kg |
| Combined energy residual | -3.64e-12 J | -9.09e-13 J |
| Remaining duration / backlog | 0 / 0 | 0 / 0 |

These coefficients are illustrative, not combustion calibration. The earlier matched glass/oak/iron thermal controls remain retained. Reaction and phase change cannot be combined in this route, and thermal state does not yet alter mechanical strength or topology.

## Verification and publication

The integrated Release build and 77 native suites pass (95.65 s); the two subsequently added segment-contact and metal-unload suites also pass (0.12 s). Python discovers 165 tests: 164 pass and one skips (10.966 s). Both browser JavaScript files pass syntax checks. A Windows rejected-POST connection reset exposed by the HTTP suite was fixed by consuming the bounded body before origin/session rejection; checks still precede JSON interpretation or any application action. The full Python rerun passes after that correction.

Browser checks cover actual reactive/inert archives, normal play, slow playback, reset, final-frame scrubbing, synchronized authored controls and full thermal inspection with component edges enabled. The output bundle contains build/test logs, probe data, snapshot/thermal evidence and captures. The published revision is recorded in the bundle's receipt. No full platform goal or visual glass-shatter gate is completed by this checkpoint.
