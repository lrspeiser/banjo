# Ordered active work and final-update convergence

October 9, 2026. Experimental GPU implementation; complete object representations, impact accuracy and realtime remain open. Parent main `2747d8c1f798c36db8286cc7e8e455fccd359d4e`. This continues the [representation adapter](gpu-representation-checkpoint.md) and [eight-family design](object-representation-design.md).

## What changed

The CUDA material island still solves its actual gravity, supports, interfaces and contacts. Two changes remove redundant work without a constitutive approximation:

- Initial accepted pair geometry is evaluated once per ordinary trial batch. All candidates share that geometry. A numerical-Jacobian batch can reuse only its freshly evaluated base's initial flags; ordinary trials recompute them after motion or edits. Candidate ending geometry remains independently evaluated when necessary.
- Contact jobs retain their original contiguous pair/site order. Ledger gathering omits only groups whose broadphase flag guarantees that every site's ledger is zero. All material rows and potentially active contact rows remain in the original sum/max order. No force reduction, law, history, activation bound or physical gate is changed. The uniform gather and serial evaluator remain reference controls.

The failure witness also exposed an iteration-boundary defect: the final permitted Newton update had already evaluated a complete trial below the original equation tolerance, but the outer controller required another iteration to notice it. The controller now admits that final converged private trial within the same update budget. Full world conservation/geometry/work checks still run before any state is accepted. It retains the original refusal for an unconverged final update; no limit or tolerance is increased. Solver receipts mark `converged_on_final_update`.

This is solver work for the current detailed-cell material island. It adds no reduced elastic modes, general definition registry, detailed sphere fracture, damaged-fragment conversion, thermal/chemical/flowing coupling or new material law.

## Reproduction and evidence

Windows x64, RTX 5090, CuPy 13.5.1 / NumPy 2.5.3, CUDA FP64 `--fmad=false`; MSVC Release CPU oracle. Final physics fingerprint `f1cb8651d27c90b5fa46a1d985fc105a846421b77407cfe07f500180202a7dca`.

[Ordered-graph measurement before the controller fix](evidence/gpu-representations/ordered-graph-before-controller.json) pins intermediate source `5d56634...`. Its alternating-order glass/oak/iron/ice 0.1 s prefixes improve by 1.185× / 1.076× / 1.164× / 1.147×. Each accepted state is bitwise identical to the prior phase kernels. The complete 10 m glass attempt improves **43.286 → 36.022 wall s for 1.425 physical s**, with identical accepted-state chains and identical refusal witnesses. This is still about 25× too slow and does not finish impact.

[Jacobian profiling](evidence/gpu-representations/ordered-graph-profile.json) measures about 0.49 ms for a 108-candidate material-island Jacobian after the ordered-work changes. CUDA event regions and wall observations overlap; these warmed single-run measurements are diagnostics, not throughput/tail qualification.

[Actual final-update replay](evidence/gpu-representations/final-update-replay.json) reuses the retained glass/iron failure input at dt 4.0690104 microseconds. The final probe's residual **8.5200718e-11** satisfies the original **1.4000364e-10** tolerance. The corrected controller returns the same candidate in 24 updates, with canonical arrays unchanged. This proves private convergence for that witness, not whole-world impact or material accuracy.

The pipeline regression also replays that exact input from the committed [original full failure archive](evidence/gpu-representations/backend-performance.json), so the real failure remains reproducible after temporary build files are removed. That added replay function is checked separately after the full expanded suite; subsequent registered suite runs include it.

[Final full-scene phase comparison](evidence/gpu-representations/ordered-graph-performance.json), source `f1cb8651...`, uses the corrected controller on both paths. The full 10 m glass attempt costs **36.397 wall s / 1.425 physical s** versus **40.689 wall s** with the prior phase kernels: 1.118× speedup. All accepted-state chain and refusal hashes match between these two phase paths. Both stop before accepted ball impact. The controller repair changes some subdivision/root selections relative to the intermediate build; it is not a proof of unchanged full trajectories or refined accuracy across controller versions.

The new final refusal has dt 4.0690104 microseconds and an actually unconverged final probe of approximately **0.11197**, against **1.39882e-10**. Its eight privately accepted microsteps roll back. Fixing the earlier boundary defect therefore does not complete impact. The separate clock gate **exits 1**, reporting this refusal and roughly 25.5× slower-than-wall computation. This remains an explicit failed capability gate, not a passing gameplay release.

Same-condition final prefixes (0.01 kg iron ball, 10 m clearance, dt 1/240 s, nine 10 mm sheet cells, identical supports):

| Sheet | Reference phase wall s | Current phase wall s | Global energy residual J |
|---|---:|---:|---:|
| Glass | 5.1250 | 4.4090 | 1.11e-16 |
| Oak | 0.8249 | 0.7645 | 2.22e-16 |
| Iron | 5.7136 | 5.0150 | 0 |
| Ice | 1.3315 | 1.2014 | 0 |

Each prefix advances 0.1 physical seconds with exact phase-reference common-time state. Density/stiffness remain glass 2500 kg/m³ / 70 GPa, oak 700 / 12, iron 7870 / 211 and ice 917 / 9. Mass differs accordingly; oak retains isotropic interfaces, iron six-mode connector plasticity. No grain, continuum J2 or new fracture law is inferred from these numbers. Existing accepted interval P/L gates (1e-9 N·s / N·m·s), scale-dependent energy gates, physical timestep and resolution are unchanged.

[Final pipeline regression](evidence/gpu-representations/ordered-graph-parity.json) passes 128 arbitrary candidate comparisons, 480 localized Jacobian comparisons, four complete 10-tick low-energy physical histories, 162 fault-priority cases and 68 ordered-ledger cases, including empty groups, mixed-sign work and nonfinite/overflow witnesses. Geometry edits invalidate initial flags. A two-update analytical gravity control returns the exact reference root at its final allowed update; a one-update nonlinear sheet still refuses and retains its actual private witness.

The registered CPU/CUDA coupled-world and representation suites pass on final source (21.85 s combined). Five affected gateway/pipeline/playback/session/view CTests pass (13.16 s). The expanded registered pipeline suite was also run directly on final source and passes. Source registration is 345/345; Python compilation, client syntax and local documentation links are checked. This is eight scoped suites, not the full repository, physical-phone, cross-GPU or material-realism qualification.

Run the reproducible phase comparison from the repository root:

```powershell
build/gpu-runtime/Scripts/python.exe scripts/gpu_active_graph_benchmark.py
build/gpu-runtime/Scripts/python.exe scripts/gpu_active_graph_benchmark.py --check-record build/gpu-representations/active-graph-performance.json
```

The benchmark reconstructs only the old pair/ledger phase kernels from the pinned parent revision; it uses the current shared laws and controller on both paths. It checks exact common-time state and refusal hashes. The second command is the separate acceptance gate: it exits nonzero if current-source glass fails to finish two physical seconds or is slower than wall time. Passing candidate/reference tests does not make this gate pass.

## What the user can test

At `/coupled?representations=1`, compare **Parallel** with **Serial reference**. **Contact sites · last substep** shows the actual active quadrature count from the accepted account, including support contacts; it does not count cracks or fabricated voxel removal. The page retains accepted time, mode, work, Stop, Before and refusal logs. Calculations remain independent of rendering. Slow and refused cases remain visible.

## Remaining acceptance

Continue local derivative/block assembly and a resident bounded solve/controller, followed by qualified reduced elastic continuation that preserves prestress/vibration. Resolve strong-impact and timestep/spatial convergence across glass/oak/iron/ice. Implement the design's versioned definition/instance registry and audited geometry/history mappings, detailed sphere/fragment activation, adaptive regions and coupled fields. Measure journal, HTTP and browser delivery separately before whole-pipeline realtime claims. The full active goal is incomplete.
