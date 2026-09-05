# Sparse-world and thermal foundation

Checkpoint, September 5, 2026. The initial slice is published as `6b0c7e4`; this follow-up adds energy/phase authoring and repeated scale evidence. It implements the first slice of the [world runtime plan](world-runtime-plan.md), with [primary-source research](world-runtime-research.md). It does not fix the unvalidated glass fracture response by changing strength or generating canned destruction.

## Implemented

- `ResolutionBudget` bounds the highest linear spring frequency using the mass-weighted stiffness row sums. `material-network-v2` reports the implied substep requirement. Optional `temporal_policy: require-resolved` rejects under-resolved packages; default `diagnose` retains the experimental comparator. This excludes contact stiffness, is a conservative temporal sampling policy, and does not certify accuracy or material realism.
- `SparseThermalWorld` stores uniform 16-cubed chunks and explicitly activated insulated regions. There is no per-cold-voxel rigid body and no cold-chunk scan during advance. Region size, active count, per-call jobs and work are bounded. Wall deadlines are soft and checked between atomic region steps. Unfinished time remains reported backlog.
- `ThermalKernel` exchanges heat exactly for an isolated constant-property pair. A graph uses symmetric operator splitting, tested for convergence. Heater work, sensible energy, finite fuel and oxygen, chemical energy and retained products are accounted separately. Reaction transfers chemical to thermal energy and conserves reservoir mass. Solid heat capacity stays constant; trapped oxygen/products do not add evolving heat capacity. This is a numerical reaction model, not calibrated wood combustion.
- `banjo_world_cli` and `banjo_world_lab` run the same four numerical coupons: glass, oak with finite oxygen, iron, and identical oak without oxygen. Each has 64 one-centimeter voxels, four center cells heated to 650 K, with material-dependent heater work recorded. The visual lab shows temperature and reaction energy, not invented flames.
- `EnthalpyLaw` keeps water identity constant while enthalpy determines temperature and liquid fraction. Melting/freezing uses latent heat at a fixed transition temperature. Phase edges use a bounded 64-iteration backward-Euler pair solve, with first-order temporal accuracy. Volume, density and conductivity stay fixed; flow, pressure, supercooling and thermomechanical coupling are absent. Combined reactive/phase materials reject rather than silently mixing incompatible models.
- `WorldPackage` validates the [SI language](world-physics-language.md), ABI, properties, references, insulated regions and bounded heater commands before returning a private candidate world. The CLI and lab accept `--package`. The new `assets/world-v1/energy-phase.json` retains glass/oak/iron and adds water/ice, while the original four-material fixture retains the no-oxygen control. No LLM or outcome lookup runs inside the thermal step.

## Verification and scale evidence

Windows MSVC Release, Intel Core Ultra 9 285K, CPU physics; NVIDIA RTX 5090 renders the lab. Full build succeeds and **all 44 CTest suites pass in 78.74 seconds**. The five affected world/kernel suites also pass after adding peak-backlog diagnostics. Coverage includes exact two-cell exchange, analytical three-cell chain refinement, conserved reaction reservoirs, no-oxygen and material-renaming controls, phase plateau and same-duration implicit refinement, cross-chunk iron/water melt and freeze within insulated regions, private-candidate schema rejection, budget deferral/catchup, and strict mechanical temporal admission. Existing mechanical outcomes remain unchanged.

`python tools/world_scale_benchmark.py --exe <banjo_world_cli> --out <directory>` runs each case three times sequentially, 600 calls at 60 Hz (10 requested seconds), 20 Hz thermal regions, 4 ms soft wall budget, 64 jobs and 32,768 abstract cell/edge work units per call. Each region has 64 cells and 112 face edges. Frame timings exclude rendering, loading, report formatting and materialization. Timing tails are measured, not hard deadlines.

| Stored voxels | Active cells | p95 advance ms, 3-run range | p99 ms range | Largest final lag | Peak late regions |
|---|---:|---:|---:|---:|---:|
| 1,048,576 | 256 | 0.172–0.185 | 0.235–0.257 | <1e-12 s | 0 |
| 16,777,216 | 256 | 0.171–0.181 | 0.242–0.445 | <1e-12 s | 0 |
| 134,217,728 | 256 | 0.163–0.176 | 0.210–0.263 | <1e-12 s | 0 |
| 16,777,216 | 1,024 | 0.715–0.768 | 1.023–1.653 | <1e-12 s | 0 |
| 16,777,216 | 4,096 | 3.007–3.062 | 4.017–4.025 | <1e-12 s | 40 |
| 16,777,216 | 16,384 | 3.809–4.027 | 4.035–4.145 | 2.70 s | 256 |

All three runs at 256 active cells produce the same final thermal/chemical states and residual -2.85e-10 J. The maximum active energy residual in the overload case is 1.67e-8 J. The 4096-cell case has transient missed region deadlines and catches up by the final sample; it is not a zero-latency result. The 16384-cell case is overloaded, preserves unfinished work, and has up to 2.733 seconds of observed lag. The largest measured advance is 4.362 ms, showing the between-job soft-deadline overshoot. Even an on-time 20 Hz thermal field has up to one-step state age; the observed age in the smaller cases is 0.0333 seconds.

Uniform storage payload plus active data is 40,960 / 179,200 / 1,211,392 bytes for the three fixed-active cases; this excludes map nodes, allocator overhead, caches and process memory. Median load time grows 0.242 / 0.760 / 5.130 ms. There are zero rigid bodies and no cold-chunk scan during advance in this thermal backend. **Cold storage size is not evidence that those millions of voxels are fully simulated.** Automatic activation/frontier and mixed mechanics performance remain unmeasured.

In the separate authored phase fixture, four 1-gram water cells receive 188 J each: 21 J warms each cell from 263.15 K to 273.15 K, then 167 J melts half its mass. After 10 seconds of exchange with neighboring cold ice, about 1.950 g remains liquid, with peak temperature still 273.15 K. Hot-iron melt and cold-iron freeze tests separately prove both directions under the same material ID. Glass and iron release no chemical heat; reactive oak releases approximately 4480 J from its finite local fuel/oxygen reservoirs; the no-oxygen oak control releases zero. These are declared numerical-law results, not calibrated combustion predictions.

## Immediate work

The owner's latest direction brings water/ice enthalpy and latent heat into the language/runtime foundation. Smoke and full fluid dynamics are deferred. A falling stone's gravitational potential energy belongs to the stone-field configuration; it becomes kinetic energy and impact work. Chemical, thermal/latent, recoverable strain, kinetic and gravitational energy are distinct stores, with explicit transfers rather than an undifferentiated material energy number.

Next: (1) compare a local continuum/contact solver against the failing glass/wood/iron and cut coupons, including time/space convergence and complete work accounting; (2) add conservative thermal frontier exchange and automatic activation across region/cold boundaries; (3) remove measured active-loop costs, stagger clocks, and test bounded materialization/demotion before parallel/GPU execution; (4) couple mechanical work and temperature-dependent laws without duplicating energy. The fracture and thermal streams can progress independently until that coupling gate. Glass fracture, wood grain, calibrated metal/tissue, contact/whole-trajectory energy closure, and Minecraft-scale mixed physics remain open. Smoke/full fluid dynamics stay deferred. All 40 mechanics/platform requirements remain retained.

## Run

Build targets `banjo_world_cli`, `banjo_world_lab`. CLI example:

```text
banjo_world_cli --chunks 4096 --regions 4 --frames 600 --output world-report.json
banjo_world_cli --package assets/world-v1/energy-phase.json --frames 600 --output phase-report.json
banjo_world_lab --package assets/world-v1/energy-phase.json
```

The lab uses Space to pause, R to reset and S to save its report and screenshot. The visual coupon client shows the first four regions and their local 8×8 z=0 cells; use headless reports for larger/different layouts. Optional `--capture path.png` runs the same stepping/drawing path for 600 frames and exports an image/report. Four coupon boundaries are explicitly insulated even though their storage chunks have neighbors. Cold storage does not imply active simulation of every voxel.
