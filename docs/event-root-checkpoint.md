# Contact root recovery and full-resolution stepping

Tested code: `b31a8a5cf51d09dc725fe1448c9eb27254aeb2ea`, local `codex/physics-foundation`, September 4, 2026 evening (logs September 5 UTC). This follows the [first event/material checkpoint](event-material-checkpoint.md). Changes are not pushed or merged into main. Gate 1 remains open, and the default lab still uses the separate-correction solver with its documented energy defects.

## Fixed failures

The full-resolution nominal 1 ms arrival left **5.55111512313e-17 s** after the internal contact root. The old controller rejected that remainder because it was smaller than its subdivision floor. It now attempts the exact remaining duration once under the normal physics audits. A failed attempt still rolls back the whole requested interval; it does not skip time or permit recursive subdivisions below the floor. All three material boundary cases now pass, with independent energy and reaction checks.

False-position contact search could stall when the positive and negative gap magnitudes differed greatly. The search now forces bisection after an insufficient bracket reduction. It accepts only an arriving contact, so proximity during departure cannot masquerade as a new impact. A failed physics trial no longer supplies an invented negative gap to the root bracket; the controller retries a shorter interval instead. Failed probes now expose the remaining time, last trial duration, measured gap and last root bracket.

The solver's velocity, geometry, energy and momentum tolerances are unchanged. The 2,048-trial and 128-substep budgets remain bounded per requested interval. Two new regression cases cover near-contact departure/return and the full-resolution boundary remainder for glass, oak and iron. Together with the previous event checks, there are nine event test groups.

## Full-resolution comparison

All three materials now finish **2 ms of physical time at full resolution using 100 intervals of 20 microseconds or 200 intervals of 10 microseconds**. Each has 1,285 nodes / 17,097 bonds, radius 0.25 m, spacing 0.04 m, horizon 2, occupancy sampling 3, initial velocity `(0.3,-1,0.2) m/s`, no spin/gravity/damage/friction, and an infinite plane 1 mm below the lowest node. Normal restitution is explicitly 1. Catalog density/stiffness differ; geometry and numerical settings do not. [Recorded configurations and numerical results](evidence/event-root-fine-steps.csv) include exact source and commands.

| Material | Interval (microseconds) | Final COM vertical speed (m/s) | Energy residual (J) | Momentum residual (kg m/s) | Solver wall time (s) | Events / trials |
|---|---:|---:|---:|---:|---:|---:|
| glass | 20 | 0.952063860 | -4.277E-010 | 3.110E-009 | 46.21 | 634 / 10883 |
| glass | 10 | 0.952646114 | -5.380E-009 | 2.694E-009 | 43.01 | 623 / 10203 |
| oak | 20 | 0.952282952 | -5.580E-010 | 3.958E-010 | 48.17 | 623 / 10600 |
| oak | 10 | 0.954531818 | -1.156E-009 | 3.493E-011 | 41.25 | 638 / 10221 |
| iron | 20 | 0.952899124 | -1.377E-009 | 8.542E-009 | 47.36 | 645 / 11101 |
| iron | 10 | 0.955487956 | -3.642E-008 | 3.081E-008 | 44.92 | 619 / 10180 |

Raw numerical normal loss is zero in all six runs; unit-restitution impact work is within roundoff. The totals include every completed interval and support reaction. Halving the interval changes final vertical speed by 0.00058225 m/s (glass), 0.00224887 m/s (oak), and 0.00258883 m/s (iron). Two rates do not establish a converged trajectory or a convergence order. Add finer-rate, resolution and orientation comparisons before declaring temporal accuracy. This is conservation evidence for the elastic approximation, not calibrated wood/iron/glass behavior. Wood grain, plasticity and fracture calibration remain absent.

The runs need roughly 41–48 seconds of solver wall time for 0.002 seconds of physical time and thousands of trial solves. These are observed development runs with other desktop activity, not benchmark distributions. A brief coarse diagnostic ran during the 10-microsecond batch, so these timings should not be used to rank rates precisely. The reference is far from real time. No conservation bound was relaxed to make it advance.

Reproduce from the repository root after building Release:

```powershell
foreach ($material in @('glass','oak','iron')) {
  ./build/win-integration/Release/banjo_solver_probe.exe --material $material --case floor --step-mode events --voxel-size 0.04 --dt 0.00002 --steps 100
  ./build/win-integration/Release/banjo_solver_probe.exe --material $material --case floor --step-mode events --voxel-size 0.04 --dt 0.00001 --steps 200
}
```

## Still failing and what it means

Full-resolution success currently uses short intervals; larger-interval accuracy has not been established. All three coarse dissipative `e=0.3` experiments now reach repeated tiny impacts and exhaust the substep budget instead of stalling in the old root search. The [current 18-case coarse matrix](evidence/event-root-coarse-matrix.csv) records 15 accepted cases and those three rejections. Failed intervals retain the original input state; their internal work/counters are not completed physical results. The [earlier 36-case matrix](evidence/event-material-matrix.csv) remains a historical baseline, not the current test outcome.

This repeated-impact behavior is consistent with a known limitation of resolving every idealized rigid impact separately, but it is not proof of mathematical Zeno behavior for this lattice. A published [nonsmooth-dynamics benchmark](https://link.springer.com/article/10.1186/s40323-019-0126-y) demonstrates finite-time bounce accumulation and discusses its cost in nodal contact. [Stewart and Trinkle](https://www.cse.lehigh.edu/~trink/Papers/STicra00.pdf) formulate sustained and impulsive contact through time-integrated impulses. [Acary's energy analysis](https://tripop.inrialpes.fr/people/acary/publications/Acary_ZAMM2015_HD.pdf) studies conservation/dissipation for nonsmooth elastodynamic integrators. These are references for the next design work, not algorithms newly implemented by this patch.

The next work must handle sustained contact and dense impact sequences with explicit energy/work accounting and temporal error control. Do not remove this failure by silently changing restitution, snapping velocities to rest, dropping time, or only increasing the trial budget. Retain the analytical contact oracles and glass/oak/iron matrix while comparing alternative contact integration. Larger-step conservation alone cannot establish a correct trajectory. Then integrate the audited solver with friction, rigid/material ownership, activation and handoff before claiming the default-runtime defect is fixed.

## Verification

Complete Windows x64 Release build passes without warnings/errors in the captured build log. All **11 CTest executables pass (6.57 s)**, including nine event groups and 17 raw-reference groups. The environment is unchanged from the prior checkpoint: Windows 11 Pro 26200, Intel Core Ultra 9 285K, VS2022 / MSVC 19.44.35228, Windows SDK 10.0.26100, CMake 4.1.2, cached Jolt 5.6 / raylib 6. Main's frame-control/busy-wait/static-runtime settings remain OFF.

The rebuilt native laboratory starts and renders; normal reset input was observed. This checks the unchanged default viewer, which does not run the new reference. No new capture-path, cross-platform, remote-CI or material-realism claim is made.

The [mechanics scorecard](mechanics-scorecard.md) and [roadmap](roadmap.md) retain unresolved contact, material, shape, adaptive-object and publishing requirements. This checkpoint does not complete a platform gate.
