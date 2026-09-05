# Adaptive compliant reference and next laboratory milestone

Latest code: `8cf33bccf3c21eea69efaea192efa10e1be43198` on local `codex/physics-foundation`. The controller and 12 full-size material runs use `a7acccfe60cfa3a77159aa831079c67c55380c7f`; the later code adds a finite-sphere grazing guard and the comparison script. All **13 Windows CTest executables pass in 10.23 s** on the later code. This is an opt-in reference, separate from the default lab and from GitHub main. Gate 1 remains open.

## What changed

`CompliantAdvance` compares one interval with two actual half steps from the same state. It measures maximum node/finite-sphere position and velocity differences, live-bond strain differences and contact damping-work differences. Each local difference limit is multiplied by interval/reference time. Only the two physical half steps can be published: no extrapolation, velocity projection, alternative material law or synthetic energy. This is a local error indicator, not a rigorous global exact-solution guarantee.

The whole requested interval is transactional. Nonlinear failure, excessive error, compression/geometry limits, the trial budget or a final work/reaction audit can reject it without publishing partial matter, finite-sphere state or elapsed time. Exact tiny final remainders are advanced rather than discarded. Accepted support impulses, damping and piecewise gravity torque accumulate on one shared clock.

Thousands of short accepted steps exposed a nonlinear-stopping problem: the first full-size glass contact initially rejected with 1.59487e-6 J of whole-interval energy residual. Scaling state-audit tolerances directly then reached rounded-state angular noise (1.79097e-14 kg m²/s) and rejected. The final implementation allocates duration/per-trial budgets to **equation residual work and impulse**, retaining the original independent state-audit tolerances. The corrected first-impact interval passes with -9.88724e-10 J. Failed diagnostics are retained in the raw archive. No conservation tolerance was widened.

At the later code, a 100 m/s point passing a finite 0.5 m sphere with a 0.499 m offset reproduces a complete shallow collision hidden between outside endpoints. Both step-doubling paths previously missed it. A swept chord entering more than the declared 1e-10 m contact tolerance now rejects a buried contact and requires subdivision, even below the allowed compression limit. Deep chords still fail the compression bound. Exact tangency remains free flight. This is a guard for the supported finite-sphere geometry, not general continuous collision detection.

## Analytical and regression evidence

- Two-mass elastic oscillator: tightening the declared comparison limits from 0.01 to 0.0001 reduces the velocity-plus-frequency-scaled-position error from 0.00148141 to 2.08507e-5; accepted segments rise from 13 to 121. Independent energy/momentum bounds are 1e-9.
- Compression-only damped analytical bounce (mass 2 kg, stiffness 2000 N/m, damping ratio 0.25): rebound 0.711532 m/s, loss 0.493723 J, 421 segments and 6 rejected trials; position, rebound and work match the continuous oracle within 1e-4.
- Gravity-loaded critically damped contact matches analytical position within 1e-6 m and its work/angular ledger within 1e-9. Finite oblique pair rotation/translation/boost, whole-interval rollback, trial/error floors and tiny remainder tests pass.
- Glass, oak and iron coarse-lattice contact cases all refine and conserve under the same parameters; no material-name branch selects an outcome.
- Grazing finite-sphere regression: reaction speed 0.231703 m/s, difference from a 0.5-microsecond fixed-step reference 2.85687e-5 m/s; 246 accepted segments and 19 rejections. Momentum/angular residual limits are 1e-9 and work limit 1e-6 J. The fixed trajectory is an approximation, not an analytical oracle.

## Full-size glass, oak and iron comparison

Identical recipe for all three: radius 0.25 m, cells 0.04 m, horizon 2, occupancy sampling 3, 1285 nodes and 17097 bonds. Initial velocity (0.3,-1,0.2) m/s, no spin or gravity, static plane 1 mm below the lowest node. Explicit interface k=1e8 N/m per contact, compression-only c=10000 kg/s and maximum compression 0.005 m. No damage, friction or internal damping. Catalog density/stiffness differ; the central-bond isotropic approximation is not calibrated glass fracture, wood grain or iron plasticity.

All 12 runs finish 5 ms, exporting every node at 51 shared times. The fixed baseline uses 0.78125-microsecond steps. Adaptive runs request 100-microsecond output intervals, maximum trial comparison interval 50 microseconds, minimum 1e-11 s and 65536 raw-solve trials per output interval. Error scales 1000, 100 and 10 multiply base position 1e-7 m, velocity 1e-3 m/s, strain 1e-6 and damping work 1e-5 J per 1 ms reference time. The tightest full-size run here is scale 10, not the default scale 1.

Tightest sampled setting (scale 10):

| Material | Final COM vy (m/s) | Damping work (J) | Maximum compression (m) | Final E residual (J) | Final P residual (kg m/s) | Solver wall time (s) |
|---|---:|---:|---:|---:|---:|---:|
| glass | 0.782672 | 31.371 | 0.000195635 | -2.11575e-09 | 6.38101e-09 | 378.682 |
| oak | 0.769874 | 8.83028 | 9.25455e-05 | 3.34044e-11 | 2.05404e-10 | 392.419 |
| iron | 0.855605 | 68.8354 | 0.00038488 | -2.29592e-08 | 2.87955e-08 | 332.564 |

| Material | Accepted physical half steps | Raw trials | Rejected comparison segments | Minimum accepted half step (s) | Maximum accepted normalized error |
|---|---:|---:|---:|---:|---:|
| glass | 43106 | 64698 | 13 | 1.69153e-09 | 0.970271 |
| oak | 46008 | 69054 | 14 | 7.62939e-10 | 0.915728 |
| iron | 36848 | 55374 | 34 | 2.88213e-09 | 0.997983 |

Maximum mass-weighted node-velocity RMS differences over all 51 shared times, in m/s:

| Material | Scale 1000 vs 100 | Scale 100 vs 10 | Scale 10 vs fixed 0.78125 us |
|---|---:|---:|---:|
| glass | 0.0245312 | 0.00592634 | 0.0227165 |
| oak | 0.0416803 | 0.00494632 | 0.0305189 |
| iron | 0.0122514 | 0.00339417 | 0.00991913 |

These compare complete matched states and verify initial state, mass, binary, physical inputs, COM and internal kinetic energy independently. Differences against the fixed reference need not shrink monotonically: the fixed reference is itself approximate. The earlier [five-rate evidence](trajectory-checkpoint.md) already showed that internal motion is less converged than bulk rebound. Local indicator acceptance is useful evidence but does not certify global trajectory accuracy, spatial convergence or calibrated substances.

Across all 12 runs the maximum absolute final E/P/L residuals are 2.29592e-08 J, 2.87955e-08 kg m/s and 1.2101e-11 kg m²/s. All accepted local indicators are at most one. Timings span 36.1947–392.419 solver seconds per **0.005 seconds of simulated motion**, excluding trajectory export. Materials ran concurrently and other development checks overlapped: these are observed costs, not a controlled benchmark or speedup claim. The accuracy-controlled reference is far from real time.

## Reproduction and source provenance

```powershell
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
& scripts/run-adaptive-matrix.ps1 -OutputDirectory build/adaptive-matrix
python scripts/compare-adaptive-trajectories.py build/adaptive-matrix/matrix.csv --output build/adaptive-comparison.csv
```

The recorded matrix was split into three material workers with the same options. Their original metadata says dirty `8bb44d0`; those exact solver sources were subsequently committed as `a7acccfe60cfa3a77159aa831079c67c55380c7f`. The unchanged matrix executable SHA-256 was `bbc4757d1177ef69180f0a7b76b5862c8bfc7fc2b1fc04c8e9d28e5f03aac3f6`. The probe was not rebuilt while any matrix worker used it. The later grazing guard was built/tested separately, so the 12 plane-only runs are attributed to the earlier controller source rather than relabeled as later-code runs. Plane contact equations are unchanged by the grazing guard. New code can reproduce the scenario, but binary identity must always be checked within a new comparison.

Environment: Windows 11 Pro build 26200, Intel Core Ultra 9 285K, VS 2022 x64 Release/MSVC 19.44.35228, Windows SDK 10.0.26100, CMake 4.1.2; existing Jolt 5.6.0/raylib 6.0 dependencies. The full Windows build passes. CMake frame-control, busy-wait and static MSVC-runtime fixes remain OFF. The rebuilt normal viewer was launched, displayed the scene and accepted pause/reset input; the original main viewer was preserved. The default runtime/viewer has no new solver selection in this checkpoint, its energy/fracture defects remain current, and prior automated capture evidence is historical. This is not a claim that the adaptive reference runs interactively.

Recorded files: [run commands and source attribution](evidence/adaptive-matrix.csv), [run diagnostics](evidence/adaptive-comparison-runs.csv), [15 matched comparisons](evidence/adaptive-comparison.csv), [765 shared-time samples](evidence/adaptive-comparison-times.csv). Full node traces, stdout, failed development probes and test evidence are provided in the user-facing raw archive, outside Git.

## What to switch to next

The next product milestone is an **inventory-backed creator workbench**: [collect materials, ask an LLM, create a supported object, test and revise it](creator-loop.md). The same object/compiler path must serve the glass/oak/iron experiments. This creator loop is planned, not yet implemented end to end. Keep the reference explicit and its cost/accuracy visible; the default pipeline is not repaired merely because this solver passes its references.

1. Introduce a visible collected-material inventory and a bounded, inspectable object specification shared by LLM and human requests. Validate material quantities/provenance and commit inventory/object creation together. Use one shared experiment declaration for objects, materials, geometry, initial motion, interfaces, gravity and numerical limits. Use it in headless runs and the viewer, with reset/pause/step, per-material time series and export. Start with glass/oak/iron drop and rebound; support reproducible saved experiments.
2. Give the audited advance sole ownership of both active matter and participating rigid-body clocks/contact response. The current `stepFracturingPhase` advances Jolt first; directly adding a solver that also advances the sphere would double-advance it. Publish accepted states together and display budget/rejection states explicitly. Keep expensive reference work off the rendering/input loop.
3. Add work-accounted friction and torque to the same contact boundary, then comparative frictionless sliding, slide-to-roll, backspin/overspin and inclines with measured slip. Do not force a no-slip velocity. Preserve every material in the regression set.
4. Expand to hollow spheres, cylinders and boxes with real matter-derived inertia/contact geometry. In parallel with later material stages, add area-aware interfaces and calibrated elastic/fracture coupons, directional wood response and iron plastic work. These remain separate implementations, not preset renames.

General object authoring, local material activation, assemblies, persistent damage/history, publishing and multiplayer remain later gates. The [40-row mechanics/platform scorecard](mechanics-scorecard.md) and [roadmap](roadmap.md) retain their evidence, limitations and next steps. No gate or overall platform completion is claimed.
