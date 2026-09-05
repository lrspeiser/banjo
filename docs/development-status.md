# Development status and handoff

**Latest local checkpoint:** tested code `68c49084f1bdcb2cc20e1c20f55f0499e1a4a3b9` on `codex/physics-foundation` adds finite-cell spin, sampled target inertia, actual Jolt/debris transfer measurements, named coarsening losses and per-tick CSV diagnostics. Windows Release, all eight CTest executables, headless supported/isolated runs, capture and normal pause/step/reset were verified. See [transfer-accounting evidence and limitations](transfer-accounting-checkpoint.md) and [property coverage](physics-coverage.md). Gate 1 remains open: the active solver has substantial numerical angular-momentum and energy changes, and bond removal is not calibrated fracture work. This work is local, not pushed or merged into GitHub main. The [earlier integration evidence](windows-integration-checkpoint.md) and audit below remain historical snapshots.

**Audit date:** September 4, 2026, America/Los_Angeles. Associated late-day GitHub events are dated September 5 in UTC. This is a pinned snapshot, not a promise that branch heads never change.

Read [project-master-plan.md](project-master-plan.md) for the complete product/architecture intent and [roadmap.md](roadmap.md) for the next work. This documentation checkpoint does not merge experimental code.

## 1. Where the code is

| Location | Audited commit | State |
|---|---|---|
| `main` code baseline | [`62cf812`](https://github.com/lrspeiser/banjo/commit/62cf8129a2ee08c9237eb5c42dac26680d186633) | Material laboratory plus subsequent interactive-window/MSVC build fixes |
| `feature/material-physics-lab` | [`a969178`](https://github.com/lrspeiser/banjo/commit/a969178e2d57555e211f49732e94269f26127712) | [PR #1](https://github.com/lrspeiser/banjo/pull/1) merged via `d944ba7`; no need to treat it as still unmerged |
| `feature/conservative-material-contact` | [`138260d`](https://github.com/lrspeiser/banjo/commit/138260d2f3d2e30a112f28034731db6052ae1720) | [PR #2](https://github.com/lrspeiser/banjo/pull/2) open and draft at audit; contact-driven fracture is not on main |

The documentation commit containing this file is layered on the main baseline above. Distinguish publishing a description of branch work on main from merging that branch's implementation.

**Important integration issue:** main advanced independently after the contact branch started. Preserve the main CMake fixes for `SUPPORT_CUSTOM_FRAME_CONTROL=OFF`, `SUPPORT_BUSY_WAIT_LOOP=OFF`, and `USE_STATIC_MSVC_RUNTIME_LIBRARY=OFF`. Do not replace main wholesale with the branch tree. The main fix explains that deterministic screenshot capture masked a normal interactive frame-presentation/input/timing bug; screenshot success alone is insufficient interactive verification.

## 2. What has been built, in order

### Bootstrap and first visual laboratory

The initial C++23/CMake implementation integrated Jolt, a procedural solid-sphere lattice with partial-cell volume sampling, engine-neutral impact events, energy-based activation, an XPBD-style brittle-bond solver, connected-component discovery, and fragment mass-property calculations. The first program was headless, which is why it built but showed no scene.

The next iteration added raylib visualization, a shared `RollingBallExperiment`, exposed-face meshes, convex collision proxies, batched Jolt fragment insertion, bounded full-rigid fragment counts, and lightweight debris. The renderer observes simulation state rather than owning a separate animation. Headless/visual CI and core tests were added. The earlier visual baseline was `ed0cfb5`.

### Material laboratory, now in main

PR #1 added material/contact definitions and presets, contact combination policies, elastic sphere-impact screening, rotation-invariant local strain evaluation with tensile/compressive/shear failure channels, support-plane/slope handling, full gravity vectors, material controls, analytical scenario projection/CSV caching, outcome serialization APIs, and additional tests. It did not finish constitutive validation or general two-way contact.

The main build fix `62cf812` addresses interactive raylib frame control and MSVC runtime linkage. Its commit message reports Windows and Ubuntu testing by its author. That report is distinct from the Linux Actions result and was not independently reproduced during this documentation audit.

### Conservative contact development, not yet in main

PR #2 replaces the runtime's synthetic fracture excitation with sphere/material contact impulses, defers activating Jolt contacts using sensor-like settings, and synchronizes finite-mass rigid reaction with material microsteps. It introduces measured slip classification, selectable launch spin, rolling-resistance torque instead of forced no-slip reassignment, separation of internal damping from rigid-body vacuum drag, support-footprint checks, and contact dissipation/impulse diagnostics.

The branch also contains an offline source-bundle workflow used to reproduce development with pinned dependency sources. That is a development aid, not part of the world-publishing system.

Read the [pinned contact checkpoint](https://github.com/lrspeiser/banjo/blob/138260d2f3d2e30a112f28034731db6052ae1720/docs/contact-checkpoint.md) and its source/tests before integration. The checkpoint's statement that graphical CI still needed checking was true when written; the CI evidence below supersedes that status only.

## 3. Implementation versus validation

| Capability | Main baseline | Contact branch / remaining boundary |
|---|---|---|
| Density-derived mass, COM, inertia | Implemented for the prototype's sampled matter and rigid spheres | Exact rotational consistency at representation transfers, including finite-cell spin, still needs an audit |
| Rolling and sliding | Initial no-slip launch; material contact friction; approximate rolling loss | Branch measures actual slip and replaces velocity reassignment with torque; no complete contact-load model |
| Material presets | Iron, aluminum, glass, ceramic, oak, rubber, ice, concrete | Preset names are not certified models; rigid materials do not thereby dent, creep, or split |
| Stiffness/strength response | Contact screening and approximate brittle constitutive channels | Resolution, strain-rate, and fracture-work calibration incomplete |
| Yield/hardness/anisotropy/temperature fields | Some used for screening or declared as metadata | Do not interpret declarations as working ductile plasticity, full anisotropic wood, or thermal mechanics |
| Gravity and slope | Shared frame/vector across ball experiment, support-plane material/debris handling and projections | Arbitrary geometry and robust finite support/contact need work |
| Original fracture handoff | Rigid collision followed by internal excitation | Branch disables that runtime pulse and adds actual sphere/material response |
| Two-way active material contact | Not implemented in main | Experimental sphere/point coupling in branch; not arbitrary-shape or material/material contact |
| Fragment creation | Connectivity -> mesh -> convex proxy -> Jolt, with overflow debris | Mass-accounting tests pass; full energy/angular-momentum correctness and realistic shard distribution are not established |
| Damage from floor/striker/repeated shards | Not general in the experiment | Future work; the demo principally activates the selected target in a ball/ball impact |
| Analytical scenario cache | Implemented; 960-scenario generator | Planner summaries do not execute adaptive scheduling or cached fracture playback |
| Material outcome capture/load/apply | Prototype library and tests | No automatic runtime reuse; state identity, frame applicability and time alignment incomplete |
| Physical LOD, sparse large worlds | Design only | Whole-object ball activation currently; no adaptive local patch hierarchy |
| Runtime material-file editing | JSON examples exist | No complete schema/unit-aware live authoring path; presets are compiled in code |
| Door/hinge assemblies, LawScript, AI authoring | Design only | Not implemented |
| Universe publishing, persistence, multiplayer | Design only | Not implemented |

Contact combination rules, damping-derived restitution, Hertz screening, point contacts, XPBD iterations, geometric correction and lightweight debris are model choices. They must be visible in tests and documentation, not labeled exact consequences of a handful of material constants.

## 4. Verification evidence

### Main lineage

[Material checkpoint CI run 33931822102](https://github.com/lrspeiser/banjo/actions/runs/33931822102) passed for `acd3aa3`: build, tests, analytical scenario generation, headless fracture/fragment handoff, and graphical capture. The later PR #1 head/merge and main build fixes must not be confused with that exact tested commit.

Main's CMake defines six CTest executables when runtime targets are enabled: `banjo_tests`, `banjo_material_tests`, `banjo_contact_tests`, `banjo_constitutive_tests`, `banjo_outcome_tests`, and `banjo_runtime_tests`. Executable count is not individual assertion count.

### Contact checkpoint

The pinned branch notes record seven passing local Linux CTest executables, including 12 runtime checks and seven conservative-contact checks, plus a passing headless experiment. A slide-to-roll test launched at 2 m/s measured 1.42857 m/s after settling. A frictionless test records a 6.53e-6 m/s surface-speed spin drift and a declared 1e-5 m/s tolerance rather than claiming exact zero numerical drift.

**Now verified:** [PR #2 CI run 33934550424](https://github.com/lrspeiser/banjo/actions/runs/33934550424), associated with `138260d`, completed successfully. Job `101219808357` passed compilation, core/material-law tests, scenario generation, headless handoff, graphical capture and artifact upload. This is a PR-triggered Linux workflow; do not treat it as independent macOS/Windows verification or proof of normal interactive input behavior on the unmerged branch.

The recorded default branch experiment had 1,285 nodes, 17,097 initial bonds, 17,076 broken bonds, 1,264 components, 64 Jolt fragments and 1,200 lightweight debris particles. Accounted target mass was 163.6089 kg. **This almost-complete breakup is a known model defect/over-fragmentation result, not validated glass behavior.** The large mass follows the 0.25 m radius solid sphere experiment, not a small household marble.

No new physics executable was built for this documentation-only audit. Historical measurements remain attributed to the exact checkpoint/report. Green tests and complete mass bookkeeping do not prove conservation across the whole nonlinear pipeline.

## 5. Current code map

| Area | Entry points |
|---|---|
| Build/targets | `CMakeLists.txt`, `CMakePresets.json`, `.github/workflows/ci.yml` |
| Authoring examples | `assets/materials/`, `assets/scenes/` (examples, not a complete live loader) |
| Material definitions/compilation | `src/material/Material.hpp`, `MaterialCatalog.cpp`, `MaterialCompiler.cpp` |
| Matter and geometric frames | `src/matter/Lattice.*`, `src/core/Math.hpp`, `Plane.hpp` |
| Contact screening | `src/physics/ContactMechanics.*`, `src/fracture/ActivationPolicy.*` |
| Rigid integration | `src/rigid/JoltWorld.*` |
| State machine | `src/sim/RollingBallExperiment.*` |
| Deformation/fracture | `src/fracture/ActiveMatter.hpp`, `BrittleBondSolver.*`, `ConnectedComponents.*` |
| Fragment transfer | `src/fracture/FragmentGeometry.*`, `FragmentMassProperties.*` |
| Predictions/outcome serialization | `src/prediction/`, `src/precompute/MaterialOutcome.*` |
| Viewer and tools | `src/viewer/main.cpp`, `src/app/headless_main.cpp`, `precompute_main.cpp` |
| Verification | `tests/`; inspect branch additions for conservative contact and rolling diagnostics |

## 6. Build and exercise the appropriate version

For main, use a separate working tree/build directory and keep local changes safe:

```sh
git fetch origin
git switch main
git pull --ff-only
cmake -S . -B build/main-test -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/main-test --parallel 4
ctest --test-dir build/main-test --output-on-failure
./build/main-test/banjo_lab
```

For contact development, switch to `feature/conservative-material-contact` and build into `build/contact-test`. Reconcile current main before relying on a standalone interactive build. Do not reset or force-push over other work. On a headless machine add `-DBANJO_BUILD_LAB=OFF` and run the `banjo_headless` executable. Linux graphical builds need the window/OpenGL development packages specified in CI; macOS/Windows setup and generator paths may differ.

Main viewer controls: `M` striker, `T` target, `S` support material; `[`/`]` slope; Up/Down striker speed; `G` gravity magnitude, `V` direction; `1`/`2`/`3` voxel detail; Space pause, `N` step, `R` reset; `B` bonds, `W` wireframe; right drag orbit, wheel zoom. The contact branch additionally exposes `L` initial-spin modes and measured motion readouts. Verify the branch's current control implementation rather than relying on an old screenshot.

```sh
./build/main-test/banjo_headless
./build/main-test/banjo_precompute build/main-test/ball-scenarios.csv
./build/main-test/banjo_lab --cache build/main-test/ball-scenarios.csv
```

The CSV contains analytical summaries, not precomputed fracture animations or an automatic real-time acceleration system.

## 7. Known issues and next handoff

Highest priority: reconcile/verify the contact branch; measure full-system momentum and energy with external-work accounting; remove artificial fracture energy from the authoritative path; calibrate over-fragmentation; and audit activation/handoff inertia, finite-cell spin, geometric correction, and damping.

Then widen to drop/floor activation, both objects and repeated shards, genuine material-specific laws, arbitrary surfaces and self-contact, deterministic parameter files, resolution/timestep tests, local physicalization, and measured performance. Automatic reuse of material outcomes is blocked on complete keys, physical applicability checks, and time-consistent integration. Language, assemblies, persistence and publishing follow the acceptance gates in the roadmap.

### Suggested coding-agent task

> Read `AGENTS.md`, `docs/project-master-plan.md`, `docs/development-status.md`, and `docs/roadmap.md`. Inspect current main and PR #2 rather than assuming historical branch heads. Reconcile the experimental contact implementation without losing main's raylib/MSVC fixes. Verify a normal interactive run as well as CI capture. Audit conservation through contact, fracture, and handoff; fix over-fragmentation through explicit constitutive/fracture-work modeling. Do not add synthetic impulses, precut chunks, forced rolling, or unvalidated cache playback. Keep the ball laboratory reproducible and update implementation status and verification evidence with each checkpoint.
