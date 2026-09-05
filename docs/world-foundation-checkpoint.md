# Sparse-world and thermal foundation

Initial checkpoint, September 5, 2026. This implements the first slice of the [world runtime plan](world-runtime-plan.md), with [primary-source research](world-runtime-research.md). It does not fix the unvalidated glass fracture response by changing strength or generating canned destruction.

## Implemented

- `ResolutionBudget` bounds the highest linear spring frequency using the mass-weighted stiffness row sums. `material-network-v2` reports the implied substep requirement. Optional `temporal_policy: require-resolved` rejects under-resolved packages; default `diagnose` retains the experimental comparator. This excludes contact stiffness, is a conservative temporal sampling policy, and does not certify accuracy or material realism.
- `SparseThermalWorld` stores uniform 16-cubed chunks and explicitly activated insulated regions. There is no per-cold-voxel rigid body and no cold-chunk scan during advance. Region size, active count, per-call jobs and work are bounded. Wall deadlines are soft and checked between atomic region steps. Unfinished time remains reported backlog.
- `ThermalKernel` exchanges heat exactly for an isolated constant-property pair. A graph uses symmetric operator splitting, tested for convergence. Heater work, sensible energy, finite fuel and oxygen, chemical energy and retained products are accounted separately. Reaction transfers chemical to thermal energy and conserves reservoir mass. Solid heat capacity stays constant; trapped oxygen/products do not add evolving heat capacity. This is a numerical reaction model, not calibrated wood combustion.
- `banjo_world_cli` and `banjo_world_lab` run the same four numerical coupons: glass, oak with finite oxygen, iron, and identical oak without oxygen. Each has 64 one-centimeter voxels, four center cells heated to 650 K, with material-dependent heater work recorded. The visual lab shows temperature and reaction energy, not invented flames.

## Initial verification

Windows MSVC Release, Intel Core Ultra 9 285K, CPU physics. Four affected CTest suites pass: thermal kernel, sparse world, temporal resolution, network runtime. Existing network behavior is unchanged apart from diagnostics/admission. The initial 600-frame / 10-second simulation with 4096 chunks (16,777,216 represented voxels), 256 active cells and 4 insulated regions measured advance p95 0.1646 ms, p99 0.4031 ms, no late regions, and combined active energy residual -2.85e-10 J. This is one initial run, not a repeated benchmark or full-world performance guarantee. Payload accounting excludes allocator overhead. Rendering is excluded from these timings.

## Immediate work

The owner's latest direction brings water/ice enthalpy and latent heat into the language/runtime foundation. Smoke and full fluid dynamics are deferred. A falling stone's gravitational potential energy belongs to the stone-field configuration; it becomes kinetic energy and impact work. Chemical, thermal/latent, recoverable strain, kinetic and gravitational energy are distinct stores, with explicit transfers rather than an undifferentiated material energy number.

Next: integrate phase-change laws and a bounded declarative world package, repeat fixed-active and growing-active benchmarks, then implement conservative thermal frontier exchange and select/refine the local continuum/contact solver. Glass fracture, wood grain, calibrated metal/tissue, automatic activation/demotion, contact/whole-trajectory energy closure, and actual Minecraft-scale mixed physics remain open. The existing 40 mechanics/platform requirements remain retained.

## Run

Build targets `banjo_world_cli`, `banjo_world_lab`. CLI example:

```text
banjo_world_cli --chunks 4096 --regions 4 --frames 600 --output world-report.json
```

The lab uses Space to pause, R to reset and S to save its report and screenshot. Four coupon boundaries are explicitly insulated even though their storage chunks have neighbors. Cold storage does not imply active simulation of every voxel.
