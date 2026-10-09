# Global stepping cost and coherent body observations

October 8, 2026. Experimental performance work on Windows x64. The proposed pair-sweep stepping policy is withdrawn after the complete material tests below. The retained native changes are coherent read-only body observations and recursive motion-driver counters. No useful simulation speed gain or new material accuracy is admitted.

## Current speed and the work still needed

The default glass lab still needs about 37 wall seconds to calculate two physical seconds: approximately 0.054 times realtime. The renderer can draw around 60 frames per second while the calculation progresses slowly. Finishing the speed requirement means at least one simulated second per wall second in complete declared glass, oak, iron and ice experiments, with qualified accuracy, responsive controls and visible actual native reactions.

Required sequence:

1. Recover the older hybrid architecture: ordinary motion uses Jolt rigid components; impact/loading activates detailed material work; stable components return to the rigid lane while retaining geometry, material history and accounted transfers. Reuse and audit existing handoff/activation primitives. Verify later piece-versus-piece impact reactivation before admitting it; the old lane had this gap.
2. Couple normal, sliding/twisting and elastic interface responses over the active contact island; measure energy, linear/angular momentum, reaction work and convergence together. A motion shortcut cannot fix contact energy injection.
3. Use geometrically relevant motion bounds and local active stepping without forcing unrelated cells through the smallest sheet's timestep. Keep collision-path coverage, force/pose consistency and rollback admission.
4. Introduce larger intact regions and finer contact/thin-feature cells with conserved mass, inertia and material history. The current fixed cell layout is not adaptive spatial refinement.
5. Benchmark the complete calculation, delivery and renderer. Consider GPU batching only after measured CPU bottlenecks and transfer costs justify it; GPU hardware is not currently required.
6. Admit each supported interaction only after material comparisons, timestep/spatial refinement and visible before/during/after tests. Plasticity, fracture calibration, heat, fluids, burning and power each retain their separate unfinished gates.

## Earlier system: what was already solved

The owner's reminder is supported by the repository. [The earlier fracture-window measurements](when-to-stop-the-fracture-window.md) record rigid continuation at 11–46 times faster than realtime and a default plate full run dropping from 1.20 to 0.471 wall seconds per simulated second after detailed work was ended on a removed-energy plateau. The measured plateau kept 99.76% of that comparator's removed energy; the fragment count changed. [The terrain/water implementation](terrain-and-water.md#realtime) records 60 simulated seconds in 4.68 wall seconds with local dirty-region work, though an individual fracture probe still took 515 ms. These are historical fixture measurements, not freshly rerun admission of the present lab.

Existing source includes [`RollingBallExperiment::finalizeFragments`](../src/sim/RollingBallExperiment.cpp), the material-driven [`ActivationPolicy`](../src/fracture/ActivationPolicy.cpp), and [`latticeExitReason`](../src/fastlattice/LatticePhysics.hpp). These are concrete reuse candidates. Their models and validity are not interchangeable with the present six-axis elastic interfaces. The old documentation also records a major gap: multi-object impacts arriving after the initial material window did not re-enter fracture, and piece-versus-piece refracture was unsupported in that fixture. An early exit based only on fragment count or a fixed elapsed duration can miss further material response.

The new voxel lab replaced that hybrid continuation with individual native cells and elastic connections active throughout the detailed solve. It has not retained the older performance architecture. Reusing the architecture with explicit handoff mass/inertia/energy/momentum/history checks, actual later-impact reactivation and maintained deformation response is now the first speed task. This checkpoint documents that gap; it does not claim the handoff has been wired into the new lab.

## What drives the global motion splits

[`VoxelImpactWorld`](../src/platform/VoxelImpactWorld.cpp) retains the original rule: when the ball's conservative lowest bound is below 0.65 m, split the whole interval if the largest cell's translational plus rotational surface-speed bound travels more than 5% of the smallest sheet thickness. For a 4 mm sheet this is 0.2 mm. The new counters identify the actual fastest cell at each recursive split proposal; they do not change decisions or assign any motion.

Default 10 m drop, 1 kg iron ball, 0.4 m square/4 mm sheet, 8 by 8 sheet cells, 32 cm support gap, nominal host dt 1/960 s; observe two physical seconds:

| Sheet | Accepted substeps | Motion split proposals | Largest driver |
|---|---:|---:|---|
| Glass | 41,823 | 39,898 | Sheet cell 147: 13,462 (33.7%) |
| Oak | 6,410 | 3,662 | Ball cell 206: 1,065 (29.1%) |
| Iron | 5,224 | 2,406 | Ball cell 206: 1,065 (44.3%) |
| Ice | 73,631 | 71,711 | Sheet cell 146: 65,276 (91.0%) |

Thus the detached/deforming sheet itself can dominate global refinement. These counts are not time attribution, and energy-driven rejected trials are separate. The website's **Physics & record** drawer now shows the total proposals, maximum recursive depth and largest driver. Older binaries show "Unavailable in this build" rather than inferred counters.

## Withdrawn pair-sweep policy

The private experiment used rotated box bounds, supplied linear/rotational vertex travel, existing internal pair suppression and native speculative distance to select geometrically eligible pairs. Both predicted motion and calculated candidate motion were checked; the original energy gates were retained. This was still global stepping, not local island integration. It changed the integration schedule and therefore required full impact qualification.

Matched conditions are those above. Glass/oak/iron/ice retain their material-derived density and stiffness: 2500/700/7870/917 kg/m³ and 70/12/211/9 GPa respectively. Oak remains an elastic comparison with no grain or plasticity law. Dynamic mass remains 2.600/1.448/6.0368/1.58688 kg. No precut shards, launch velocities or response animations were added.

| Sheet | Reference / pair wall s | Reference / pair substeps | Reference / pair unclosed energy J | Actual result |
|---|---:|---:|---:|---|
| Glass | 39.817 / 2.174 | 41,823 / 2,183 | -92.9233 / -10.2779 | Pair stops at 1.427850 s; durations differ, so this is not a speedup |
| Oak | 7.899 / 14.180 | 6,410 / 11,517 | -44.1669 / -44.5796 | Both finish; pair is slower |
| Iron | 6.336 / 10.761 | 5,224 / 7,222 | -82.8286 / -80.4027 | Both finish; pair is slower and losses differ |
| Ice | 39.338 / 26.695 | 73,631 / 38,321 | -103.1518 / -96.4264 | Both finish; pair changes fracture and losses |

Reference/pair linear residual norms in N·s are glass 0.002551/0.000461 (unequal duration), oak 0.000221/0.001194, iron 0.000209/0.000707 and ice 0.002695/0.001269. Full angular residual norms in N·m·s are glass 0.000261/3.63e-7 (unequal duration), oak 2.45e-6/7.43e-6, iron 2.90e-6/6.11e-5 and ice 0.000184/0.000105. These unresolved numerical/source terms and large energy deficits do not certify conservation or realistic materials.

Glass's refused candidate, at recursive depth 14 and dt 6.35783e-8 s, increases accounted energy from 98.726138 to 98.734092 J. Recorded contact work is +0.00791431 J; candidate sweep ratio is only 0.01454. The refusal is an energy error, not a missing motion split. The unchanged acceptance gates reject this candidate, and its pose is not rendered.

Ice's reference sheet has 62 components/110 broken faces; pair has 64/112. Sixteen additional matched 0.1 m drop experiments at 0.3 physical seconds and dt 1/960 versus 1/1920 s all complete. Pair glass's unclosed energy changes from -0.779348 to -0.705907 J under refinement; completion does not establish convergence. No tolerance was loosened. The native option and its API declaration are removed. Exact private source and result states remain in ignored local `build/voxel-pair-sweep/prototype-source/`, `material-benchmark.json` and `material-refinement.json`.

## Retained implementation

[`JoltWorld`](../src/rigid/JoltWorld.cpp) now observes pose and velocities under one native `BodyLockRead`, instead of four separately locking getters. `mechanicalState` reads motion, mass and inertia under the same lock. Static velocity remains zero, kinematic velocity remains readable, and the native mass/inertia arithmetic is retained. No forces, timesteps, material laws, solver ordering, damping or acceptance tolerances change.

The compiled CPU [`BoxSweep`](../src/physics/BoxSweep.hpp) primitive is retained for future geometry work. It bounds a finite oriented box given an explicitly supplied vertex path-length bound and reports eligible-pair travel relative to the smaller feature. Bounds include float geometry padding. It is a broad-phase helper, not a collision response or an automatic proof of an arbitrary trajectory. Tests cover 16,800 sampled translated/rotated corners, distant/crossing/thin/coarse pairs, ordering symmetry and invalid inputs. **The current native timestep selector does not call it.** Its analytical tests cannot admit the withdrawn integration.

## Verification boundary

Source parent: `f2f87d47d34f9ab6ace9469b703062631749d0e6`. Separate CMake tree `build/voxel-contact-audit`, output `build/voxel-observation/Release`; Windows SDK 10.0.26100, MSVC Release, precise CPU floating point, Intel Core Ultra 9 285K (24 logical CPUs). Native SHA-256: `e7e0c961b5398f0c5d8ee4beac32243504d92bb627c3e63e18874f2db94401ff`. The law baseline remains `bbb00f2ccada0179dd48d53eef9115089f6dcd9f`.

The first ten scoped CTests pass in 15.94 s, including native contact observation/rollback, four-material actual impact reporting, gateway, pipeline and playback. Registration is 340/340 with no exclusions. An accidentally selected long matter-network capacity suite was stopped after 86 s; its documented duration is about 34 minutes. Its result is **not** reported as a pass. The intended native contact capacity/rollback target passes; the full repository and long suites are not claimed.

Final scoped run: **14/14 CTests pass in 18.62 s**, including elastic faces, whole-state storage, reversible trials and rolling controls. Four complete two-second glass/oak/iron/ice comparisons against the prior published delivery binary retain every physical/work field at each 16-host-tick output; only wall profiling is excluded. Alternating request order limits timing order bias. Glass costs 37.132 versus 37.299 s; oak 7.213 versus 7.305 s; ice 37.386 versus 37.811 s. These small differences do not establish a useful speed gain. The original global step schedule and unresolved losses remain unchanged.

```text
cmake -S . -B build/voxel-contact-audit -DCMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE=C:/Users/henry/Documents/ChatGPT/Banjo/build/voxel-observation/Release
cmake --build build/voxel-contact-audit --config Release --target banjo_voxel_world_run banjo_box_sweep_tests banjo_contact_capacity_tests banjo_connector_plasticity_tests banjo_rigid_step_work_tests banjo_contact_friction_block_tests banjo_contact_normal_block_tests banjo_voxel_face_spring_tests banjo_state_recorder_tests banjo_reversible_trial_tests banjo_rolling_resistance_tests --parallel 4
ctest --test-dir build/voxel-contact-audit -C Release --output-on-failure -R "banjo_(box_sweep|native_contact_capacity|connector_plasticity|rigid_step_work|contact_friction_block|contact_normal_block|voxel_face_spring|state_recorder|reversible_trial|rolling_resistance|voxel_motion_profile|voxel_pipeline|voxel_playback|voxel_gateway)_tests"
python scripts/check-source-registration.py
node --check client/voxel-lab/world.js
python tests/voxel_execution_test.py build/voxel-observation/Release/banjo_voxel_world_run.exe build/voxel-delivery-reference/Release/banjo_voxel_world_run.exe --strict-inline-baseline --alternate-request-order --witness-path build/voxel-observation/parity-failure.json
```

The normal interactive browser Drop completes two physical seconds with 12 sheet components, 40 broken faces and 41,823 accepted steps, displaying about 0.05 times realtime and 60 renderer fps. The inspection drawer reads 39,898 motion split proposals, depth 7, with sheet cell 147 driving 33.7%; these agree with the native record. The old user sessions on ports 18912 and 18914 remain intact. This is Windows CPU laboratory verification; it does not establish physical-phone behavior, cross-GPU determinism, full material realism or migration of the player world.
