# Execution checkpoint — September 5, 2026

The [six-goal execution list](execution-goals.md) and [machine-readable list](execution-goals.json) retain all 40 mechanics/platform requirements. G01, G03 and G05 have new implementation evidence and remain active. G02, G04 and G06 remain queued; no full goal or overall platform is marked complete. Routine documentation, test fixtures and benchmark generation used GPT-5.6 Luna; bounded numerical work and review used GPT-5.6 Sol; the parent handled integration, review and final verification.

## Implemented

- **G01:** `CellSkin` and `PlatformWorld::renderSkins()` derive blocky surfaces from accepted cells and interfaces. Live neighbors hide interior faces; failed faces get distinct owner-local crack centers, even when another path retains one component. Topology is cached per affected object/revision. A least-squares frame follows live neighbor motion; rank-deficient remnants use an explicitly reported fallback. Skin queries do not change physical state. The native v2 lab defaults to skins; K cycles skin, cells and structure. `banjo_platform_cli --skin package.json steps output.json` exports derived geometry with object/material/component/cell identities and rejects existing output files. This export is not a simulation snapshot.
- **G03:** `SparseThermalWorld::joinInsulatedRegions(first,second,expected_time)` atomically joins neighboring, caught-up regions with matching clocks, preserving the first ID, retiring the second, retaining all cell/phase/reaction state and summing reference/external-work ledgers. Cross-boundary faces become ordinary conservative conduction edges. External boundaries remain insulated. There is no automatic cold-neighbor activation, demotion, or independent asynchronous boundary exchange.
- **G05:** the phase pair kernel directly solves at most five affine intervals of the same backward-Euler equation. It passes 432 independent oracle cases including phase edges and extreme mass ratios. Five one-million-call microbenchmarks measured **4.37–4.77×** versus the old 64-step search on this Windows machine. This is a kernel result, not a whole-engine speedup. The world CLI exposes `--jobs` and records the configured job allowance; zero jobs preserves backlog and values above 4096 reject.

## Verification and measured limits

Full Windows MSVC Release build succeeded. **47/47 CTest suites passed in 83.33 s**, followed by CLI checks for zero/excess job budgets and skin export/no-overwrite. The skin tests compare every cell's exact position, orientation and velocities against an unqueried control during actual cutting/fracture, compare four materials and renamed IDs, and exercise partial cracks, invalid/stale geometry and rigid transforms. The free-flight mesh-only tolerance is 1e-7 m because shared vertices fit several moving cells; physical trajectory comparisons remain exact. The join suite checks mixed glass/oak/iron, reactive history, water/ice, pre-joined-reference equivalence, stale/backlogged/capacity rejection and scheduler compaction.

Native release and K view switching were exercised. Final offline captures run the same physics with fixed steps and are labeled offline; their 60 FPS display is not a realtime physics claim.

| Capture | Physical cells | Broken bonds | Cut faces | Skin triangles | Skin query p95 / p99 ms |
|---|---:|---:|---:|---:|---:|
| tissue | 121 | 14 | 12 | 416 | 0.041 / 0.198 |
| cubes | 84 | 75 | 70 | 604 | 0.069 / 0.100 |

Skins remain synchronous and blocky, with whole affected-object rebuilds. Local asynchronous patches, persistent GPU buffers, UVs, physical layers, surface/contact error convergence and smooth finite-strain skins remain open. Face-only surface topology is not a continuum fracture-surface reconstruction; diagonal bond failure alone does not expose a face. The underlying glass/contact solver is unchanged and still unreliable. No skin improvement certifies material realism or full energy closure.

The new thermal/phase workload repeats each case three times for 600 host frames (10 requested seconds), retaining glass, oak, iron and water/ice. It stores 16,777,216 voxels in 4096 uniform chunks while activating only the cells below. The default allowance is 64 jobs, 32768 abstract cell/edge operations and a soft 4 ms wall budget per host call.

| Active cells | p95 ms range | p99 ms range | Maximum final lag s | Maximum transient late regions |
|---|---:|---:|---:|---:|
| 256 | 0.164–0.188 | 0.188–0.309 | 0.000 | 0 |
| 1,024 | 0.692–0.698 | 0.990–1.546 | 0.000 | 0 |
| 4,096 | 2.916–2.965 | 3.698–4.022 | 0.000 | 35 |
| 16,384 | 3.586–4.021 | 4.037–4.101 | 2.700 | 256 |

The 256–4096-cell cases all reach the same accepted 10 s state; 252 per-region material states match across their repeated equal-time comparisons. The 16384-cell overload ends at differing accepted times and is not compared as if it had completed 10 s. Maximum absolute combined thermal/chemical energy residual is 1.10e-8 J in that overload case. This is insulated field work without rendering or mechanics; stored voxels are not all actively simulated.

With **128 permitted jobs**, the same 16384-cell input and unchanged 32768-operation/4 ms budget finish **0.050 s behind** in all three runs, compared with 2.65–2.70 s at 64 jobs. Peak lag is 0.133–0.150 s; p95 is 4.037–4.039 ms, p99 4.078–4.129 ms, and the maximum callback is 4.234 ms. There are still 163 due regions at the final sampling instant. The cap is checked between atomic jobs and is not a hard deadline. Defaults remain conservative; this measured host configuration is not a general realtime guarantee. Next: wake/activation work, error/age budgets and joint mechanical loads.

## Reproduce

```text
cmake --build build/win-joint-double --config Release -j 8
ctest --test-dir build/win-joint-double -C Release --output-on-failure
build/win-joint-double/Release/banjo_phase_pair_benchmark.exe 1000000
python tools/phase_world_benchmark.py --exe build/win-joint-double/Release/banjo_world_cli.exe --out build/phase-world-evidence
build/win-joint-double/Release/banjo_world_cli.exe --package build/phase-world-evidence/inputs-256-regions.json --frames 600 --jobs 128 --output build/jobs128.json
build/win-joint-double/Release/banjo_network_lab.exe assets/runtime-v2 04-soft-tissue-offset-cut.json
```

Raw reports, the test XML, input packages, screenshots, exported skin and executable hashes are retained in the user-facing execution evidence folder. The publication manifest records the exact GitHub main revision after the ordinary fast-forward push. Existing comparison evidence and all 40 scorecard rows remain retained; smoke and full fluid dynamics remain deferred.
