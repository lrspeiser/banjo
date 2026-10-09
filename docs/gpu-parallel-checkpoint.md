# Parallel coupled CUDA pipeline — October 9, 2026

## What changed

The actual `/coupled` 3D lab now defaults to a parallel CUDA contribution pipeline and retains an explicit **Serial reference** selector. Both run the same implicit finite-cell model. Nine cubes, material histories, a density-derived ball and fixed support reactions remain the same. Geometry, constitutive laws, Newton tolerances, timestep choices and conservation/travel/compression gates were not relaxed. The CPU material world's native executable remains unchanged.

GPU work is split into prepared body states, pair separation, independent material/contact contributions, ordered body gathering, ordered ledger gathering and fault collection. There are no floating-point force atomics or reordered sum trees. Each body/component gathers contributions in the original material-edge / shape-pair / sample order, preserving signed zero by skipping unapplied forces. The corresponding CPU serial entry uses the extracted shared contribution functions and is still compiled in the actual oracle target.

Each Newton Jacobian changes only one body DOF per candidate. Pairs not involving that body have exactly the base candidate's two input states, material coefficients/history and dt. Their contributions are copied exactly from the freshly evaluated base. This reuse is restricted to the current Jacobian: no outcome cache crosses a physical update, Newton base, topology, material history or solver setting. The final whole-scene force/ledger gathering stays identical. Future nonlocal laws must expand the dependency set or use complete evaluation; pair locality is not assumed for unimplemented thermal/fluid models.

## Evidence and performance

Repository base `3cb4457adf4e2e19bca89db18e9fac2c4386c1f4` plus this checkpoint. Publication revision is the commit containing this note and is exposed by `/api/checkpoint`. Windows 11 / MSVC 19.44 / RTX 5090 / CuPy 13.5.1 / NumPy 2.5.3 / CUDA driver API 13.3. No cross-GPU, macOS or physical phone claim.

The initial profile measured about 26 ms for both one and 120 candidates, with 255 registers and 7600 local bytes in the monolithic kernel. A warmed 60-variable dense solve took about 0.19 ms. This identified serial candidate traversal and spilling as the first target.

[Current warmed profiler](evidence/gpu-parallel/profile.json), reproducible with `build/gpu-runtime/Scripts/python.exe scripts/gpu-coupled-profile.py --report build/profile.json`: nine medians per path, same 13-body scene, dt 1/960 s, 120 single-DOF Jacobian candidates. Timings below exclude full Newton/integration/audit, journaling, gateway and rendering. CUDA event phase timings include measurement overhead; whole-batch CUDA time includes stream scheduling gaps. No realtime admission follows from a fast candidate kernel.

| Material | Serial single · ms | Parallel single · ms | Serial full Jacobian · ms | Parallel local Jacobian · ms |
|---|---:|---:|---:|---:|
| glass | 26.771 | 0.697 | 27.936 | 1.131 |
| oak | 26.925 | 0.703 | 27.928 | 1.131 |
| iron | 25.389 | 0.657 | 25.946 | 1.017 |
| ice | 26.780 | 0.697 | 27.707 | 1.128 |

[Exact pipeline parity](evidence/gpu-parallel/parity.json): 128 mixed-material candidate trials and 480 local Jacobian candidates match full evaluation bit for bit across poses, forces, residuals, histories, ledgers and faults. All four matched ten-tick low-energy physical trajectories also match the retained serial pipeline exactly, including every microstep, histories, reaction/work accounts, equation residual and iteration count. Interleaved test timing shows about 15× full-run improvement, but other verification work was active; it is not a standalone throughput certificate.

[Standalone parallel world controls](evidence/gpu-parallel/world-controls.json) took about 1.4–3.0 wall s for 0.0416667 physical s, versus tens of seconds before. This remains roughly 34–73× slower than realtime. These controls have 10 gram iron balls dropped 1 mm onto the same slab at host dt 1/240 s. All four retain the previous full energy/P/L accounts. They do not fracture or yield. Four analytical freefall controls and whole-interval rollback also pass.

Eleven distinct scoped CTests pass: contact geometry/work derivatives, rotation, native face spring, normal compliance, GPU laws/frames/coupled world/parallel pipeline and gateway/pipeline/playback. 345/345 sources are registered. CUDA memcheck covers full and localized Jacobian batches for all four materials and reports zero errors. A private archived original published CUDA reference also matches 64 candidates bit for bit. These are scoped algorithm/memory tests, not material realism or general impact qualification.

## Stronger impacts and retained failures

[Actual stronger outcomes](evidence/gpu-parallel/stronger-outcomes.json) use the same 100 gram iron ball, 5 mm clearance and dt 1/960 s for glass, oak, iron and ice. Oak and iron reach 0.104167 physical s without fracture/yield. Glass refuses at 0.034375 s and ice at 0.0958333 s. The affected interval restores its prior accepted scene and stops; failures are not skipped or converted into animation.

An isolated repeat confirms the glass failure at the same accepted time. It takes 12.3 wall s and privately accepts 62 microsteps before exhausting the 128-trial interval bound, rather than the 30 s time bound. Recent private steps are about 8.14 microseconds and contain no damage. Newton/adaptive work near contact remains a fundamental bottleneck. Raising the work limit is not offered as a speed or accuracy fix.

The earlier [coupled model assumptions](gpu-coupled-checkpoint.md) still apply: isotropic rigid finite cells, declared cohesive/plastic interfaces, frictionless linear compliance, unqualified sample-only edge contacts/CCD, no oak grain or bulk J2 denting/tearing. No fracture/dent, thermal/fire/fluid/water-wheel/power or complete-world realtime qualification is added.

## Next implementation

1. Record exact Newton refusal reasons and candidate states at the strong glass/ice failures. Qualify contact/timestep convergence and the finite-difference scale before claiming usable fracture impacts.
2. Profile/reduce ordered ledger and fault scans, dense solve/host synchronization, then move to sparse resident tangents/islands. Preserve the reference and compare all physical histories.
3. Expand admitted off-axis and higher-energy experiments until connectivity actually breaks and permanent material geometry survives unloading with complete work/P/L and refinement. Then grow cell count/shape hierarchy and reusable authoring/gameplay.
4. Thermal/fire, fluids/phase changes, power and adaptive cell resolution remain part of the full active objective. The faster pipeline is progress toward it, not completion.

## Browser checkpoint

The normal `/coupled` controls were exercised with Parallel selected: Run 10 steps reached 0.04167 physical seconds, retained 13 cells / 48 interfaces, reported no separated sites or yielded faces, and exposed an energy residual of -1.67e-14 J. This confirms the displayed accepted CUDA state and control path; it does not qualify realtime or visible fracture. The published server revision and source hashes are checked after restart.