# Voxel impact world checkpoint — October 8, 2026

## Scope and provenance

Experimental implementation, not a calibrated continuum or complete game rewrite. Replaces the website served on local port **18893** with one native 3D sheet/ball/support world. Historical sources and regression laboratories remain in Git; their website routes redirect to the new scene. Saved player worlds on other servers are not migrated.

Base main revision: `2745d0eb4a4047127c2718fc67ef076b8e9195ac`. The publishing revision is the commit containing this document. Native Release executable SHA256: `3c53fea299fb0043c403da3b89f16324f8775426963dafd1c9a0ca0ef18fe006`. Windows x64, Visual Studio/MSBuild 17.14.51, local-cell-tools separate build; Windows browser 1280 × 720. No macOS/Linux/cross-GPU qualification.

## Authoritative geometry and state

Sources: [native world](../src/platform/VoxelImpactWorld.cpp), [native protocol](../tools/voxel_world_run.cpp), [Jolt bridge](../src/rigid/JoltWorld.cpp), [gateway](../scripts/voxel-lab.py), [renderer](../client/voxel-lab/world.js).

Default sheet: 400 × 4 × 400 mm, **64 actual cuboid bodies**, 50 × 4 × 50 mm each. 112 nearest-face interfaces join the original intact sheet. Optional 12 × 12 / 16 × 16 sheets contain 144 / 256 cells at unchanged dimensions/mass. These are anisotropic occupied cuboids, not a uniform cubic hierarchy.

Default ball: **32 occupied cuboid bodies** selected inside a 4 × 4 × 4 spherical grid. Its diameter is derived from requested mass, density and the grid's exact 0.5 occupied fraction. It is a coarse voxel approximation, not a smooth exact sphere. Two anchored concrete support cells have 60 mm width, 500 mm height and 460 mm depth, separated by a selectable centre gap (default 320 mm). Nine anchored 1 m floor cells complete the default **107-cell** scene. There is no invisible tabletop or fixed sheet clamp.

Every cell has material-density × occupied-volume mass and box inertia, a native body ID, orientation, linear velocity and spin. Breaking removes interfaces, not bodies. Cell IDs, dimensions, masses and material assignments persist. Separated voxels retain native motion and undergo Jolt self/support/floor collision. The browser draws only returned transforms; no precut shards, trajectories, launch impulses or shatter animations exist.

There is no automatic spatial split/merge, local knife-edge refinement, general custom-tool authoring or player-world migration yet. Larger support/floor cells and finer sheet cells are explicit authoring choices. Ball resolution is currently fixed.

## Material and contact model

Reference catalog numbers drive the shared model; material display names do not select a fracture pattern. Each face uses passive six-axis elastic springs at the common face centroid: translational stiffness EA/L and GA/L; rotational EI/L and a polar-area G(Iy+Iz)/L torsion approximation. Damping is internal, separate from native Coulomb/restitution contact. Rotation damping uses an approximate reduced minimum principal inertia; torsion and damping are not calibrated finite-element laws.

Glass/ice/ceramic use brittle admission: combined tensile/bending or shear/torsion stress reaches catalog strength **and** stored interface energy exceeds Gc × area. Both are required. Iron/aluminum/oak currently retain elastic connections without plasticity, grain behavior or brittle-name substitution. Oak remains only a required historical comparison, not restored organic gameplay.

Contacts between connected neighbors have one spring owner; broken interfaces restore native contact. Other contacts are native. CCD is disabled for these constrained cells. Small-cell speculative distance, penetration slop and manifold tolerance are explicitly scaled by sheet thickness (0.1, 0.01, 0.05). Contact position projection is disabled: the rejected prototype stretched stiff springs through unaccounted positional correction. Native contacts still resolve velocities; penetration accuracy needs qualification.

Host timestep: **1/960 s**. Near the apparatus, intervals subdivide until maximum voxel-point travel is at most 5% of sheet thickness. Native reversible trials further halve rejected intervals (maximum depth 14). A local positive-energy bound of 1e-5 × max(1, |previous mechanical + elastic energy|) + 1e-6 J and a whole-run positive unclosed-energy ceiling of **0.1 J** reject spontaneous growth. These are experimental numerical admission bounds, not full conservation proof or empirical calibration. A refusal returns the last accepted state and diagnostics; the renderer stops rather than inventing a result.

Breaking books GcA and separately reports discarded unreleased elastic overshoot. No release impulse is injected. Current total kinetic/potential/elastic energy and total linear/angular momentum are reported, but native contact/constraint damping, anchored reaction/work and numerical loss are not fully attributed. **Negative unclosed energy is substantial and remains a defect to quantify, not evidence of conservation.** Fracture topology, contact penetration, timestep/resolution convergence and realistic fragments remain unqualified.

## Measured common experiment

Same 400 × 4 × 400 mm sheet; 64 cells; unpowered 1 kg iron voxel ball starting 10 m above the sheet; identical supports; 1/960 s host step; adaptive native intervals; 2 physical seconds.

| Sheet | Density kg/m³ | E GPa | Sheet mass kg | Broken faces | Connected pieces | Unclosed E J | Native wall s |
|---|---:|---:|---:|---:|---:|---:|---:|
| Glass | 2500 | 70 | 1.60000 | 40 | 12 | −92.9233 | 37.8 |
| Oak | 700 | 12 | 0.44800 | 0 | 1 | −44.1673 | 7.6 |
| Iron | 7870 | 211 | 5.03680 | 0 | 1 | −82.8286 | 6.4 |
| Ice | 917 | 9 | 0.58688 | 110 | 62 | −103.1518 | 38.4 |

Differences in density, stiffness, strength and supported constitutive models matter simultaneously; these comparisons do not establish real oak toughness or real metal denting. Glass and ice move original cells below the former sheet plane; no-ball and missed-ball controls remain intact. Analytical freefall is checked before contact. All original body IDs and per-cell masses are retained at every received frame.

At **1.5 physical seconds**, glass sheets with 144 / 256 cells complete with 56 / 115 broken faces and 18 / 37 connected pieces (17.6 / 60.6 native wall seconds in exploratory runs). This is measured resolution sensitivity, **not spatial convergence**. Ice, aluminum and ceramic balls against the default glass sheet also reach 1.5 s with actual separation; longer/settled outcomes need qualification.

**Retained failure:** the glass-ball/glass-sheet experiment refuses at about 1.427663 s: previous E 94.227132 J, rejected candidate 94.228952 J at the refinement floor. Its UI option is unavailable. The regression checks the explicit refusal and retained snapshot; it does not count this as a successful drop. Repair native contact/elastic precision and requalify it before enabling the choice.

## Verification and public interface

[Native regression](../tests/voxel_world_test.py): four common-duration materials, freefall, exact cell identity/mass continuity, visible constituent movement, through-plane passage for brittle references, no-ball/missed-ball controls, changed ball materials and fine sheet grids; separately preserves the glass-ball integration refusal. It rejects energy growth beyond the declared ceiling and non-finite states. It does not certify full P/L/E, realism or rendering by itself.

[Gateway regression](../tests/voxel_gateway_test.py): ordinary new routes, separate native sessions, bounded requests, refusal state retention, exact persisted native responses and close. Session records include native/asset hashes and every request/response. Eight concurrent bounded local sessions, ten-minute expiry, four native physical seconds maximum, 25-second per-command deadline and 32 MB record limit. This is a local test server, not scalable multiplayer hosting.

Registered native voxel regression passes in 200.18 s: 11 completed experiments plus the retained refusal check. Gateway and rebuilt spring-trial, scene-joint and joint-interface suites also pass (four CTest entries, 2.02 s). Source registration: **325/325**, no exclusions. Windows desktop browser verifies ordinary Drop, visible glass opening/fragments, 2 s completion, Before/Live return and no console errors. Screenshots are local build evidence `build/voxel-before.png` and `build/voxel-after.png`; artifacts are excluded from commits. The full repository regression and physical-phone input are not claimed.

## Next gates

1. Resolve the glass-ball energy refusal and close signed contact/constraint/support work accounts; distinguish loss and numerical error.
2. Profile native trial capture, spring/contact iterations and active intervals. Improve speed without reducing E/strength or supplying cosmetic motion.
3. Paired timestep/refinement comparisons across glass/oak/iron/ice; measure penetration and geometry as well as topology, P/L/E and performance.
4. Add return-mapping plasticity with retained plastic strain, yield/hardening and dissipation so metals can make real dents; add calibrated brittle release/topology accuracy.
5. Declarative unit-bearing custom materials/objects; bounded validated laws. Mixed-resolution interfaces, conservative split/merge and contact-local refinement must preserve mass, inertia, momentum, energy and fracture history.
6. Use the same native path for authored tools and a freely editable 3D world only after these gates pass. Keep the live laboratory available throughout.
