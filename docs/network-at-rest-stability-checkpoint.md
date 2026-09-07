# Network lane at-rest stability checkpoint

Recorded 2026-09-07. Environment: Windows 11, MSVC 19.44.35228.0, Visual Studio
17 2022 generator, x64 Release, Jolt v5.6.0, `DOUBLE_PRECISION=ON`. Backend
`material-network-v2`, ABI `banjo-network-2`.

This checkpoint closes the defect recorded in
[the convergence study](convergence-study-checkpoint.md) section 8: a lattice at
rest in a vacuum, with the exact answer that nothing happens, tore itself apart.

## What was wrong

The springs were integrated far outside their own stability limit. For the
authored iron panel the fastest bond mode has a period of 2.9e-5 s while
`fixed_dt_s` is 2.083e-4 s, so the constraint solver advanced the network
**about seven times its own period per solve**. `assessSpringResolution` already
measured this and reported `resolved: false` with 315 to 787 required substeps,
and three separate mechanisms already refused such a run when asked:
`temporal_policy: require-resolved` rejects at load, `damage_integration` with
`on_limit: reject` rejects at the step, and
`maximum_reaction_geometric_extension_discrepancy_m` records the residual.

None of them were on the default path. The default path ran anyway and reported
`state_valid: true` beside 2,141 fabricated fractures and 1.19e9 J of elastic
energy created from a 0 J start.

The fabrication had a specific route. A bond's extension is not measured
geometrically; it is reconstructed from the reaction the constraint solver
actually applied, as `-impulse/dt - damping*rate` divided by stiffness. Dividing
by the step amplifies any unconverged residual as the step shrinks, which is why
refining the timestep made the damage worse rather than better. That
reconstructed extension is what `advanceNetworkBond` reads, so a solver residual
was written into damage, fracture and plastic state as though it were material
behaviour.

Measured on the unpinned 6x9x2 glass panel at rest, 0.5 s, varying only the
constraint solver's velocity iterations. The residual is quoted against d0, the
extension at which that bond fails, which is 1.286e-5 m for the 0.02 m bonds:

| solver iterations | broken bonds | reconstruction residual | residual / d0 |
|---:|---:|---:|---:|
| 4 | 409 | 2.899e-3 m | 225 |
| 8 | 364 | 1.297e-3 m | 101 |
| 16 | 311 | 6.313e-4 m | 49 |
| 24 (default) | 322 | 3.083e-4 m | 24 |
| 48 | 149 | 1.285e-4 m | 10.0 |
| 96 | **0** | 7.841e-9 m | 6.1e-4 |
| 128 | **0** | 7.010e-9 m | 5.5e-4 |

The two regimes are four orders of magnitude apart. Raising iterations is not a
fix, though: at 10x15x4 the residual is still 4.3e-3 m at 128 iterations, and
the panel still gains 3.9e4 J from rest.

## What changed

Two changes in `src/platform/NetworkWorld.cpp`, one in
`src/platform/PlatformWorld.cpp`.

**1. The network runs on its own clock.** `fixed_dt_s` is a host cadence, not a
claim about what the material can be integrated at. Each host tick is now
subdivided into `assessSpringResolution`'s required substeps, capped at
`kMaximumStabilitySubsteps` (1024), at `kStabilityPhaseRadians` (0.2 rad of the
fastest mode per solve). The authored package, the reported time and the outer
cadence are unchanged; only the number of internal solves differs. The adaptive
path substeps *inside* its existing transaction, so a terminal rejection still
discards the complete outer tick, and its reported
`maximum_solver_trials_per_tick` now scales with the substep count.

**2. An unconverged reaction may not become material state.** Before a bond
update is committed, the reconstruction's residual is compared against the
smallest extension that would change that bond irreversibly — its failure
opening, or its yield opening where the material has one. Above that the engine
cannot distinguish a bond that is breaking from a solver that has not converged,
so it refuses the update, leaves the bond's history untouched, and counts the
refusal. Both integration paths share one helper, so a depth-zero adaptive trial
still reproduces the single-step result exactly.

**3. The refusal is visible.** The report gains `network_substepping`
(substeps per tick, requirement, whether the budget bound) and
`reaction_reconstruction` (worst residual ratio, refused updates, admissible).
A run that refused any update reports `state_valid: false`, because it has not
measured its own material state.

## Measured after

At rest, 0.5 s, zero gravity, no ground, no contact, unpinned, `fixed_dt_s`
1/4800. Exact answer: nothing happens, every energy stays zero.

| case | broken before | broken after | energy before | energy after | substeps |
|---|---:|---:|---:|---:|---:|
| glass 6x9x2 | 322 | **0** | 5.54 J | **7.8e-8 J** | 315/315 |
| oak 6x9x2 | 219 | **0** | 0.875 J | **2.3e-10 J** | 127/127 |
| iron 6x9x2 | 0 | **0** | 1.13e6 J | **exactly 0** | 308/308 |

All three report `state_valid: true`, zero refused updates, and no budget
limiting.

The same change substantially altered driven impact, on the identical package:

| case | broken before | broken after | fracture work before | fracture work after |
|---|---:|---:|---:|---:|
| iron ball into glass at 12 m/s | 4 | **299 of 586** | 0.0054 J | **0.402 J** |
| iron ball into oak at 12 m/s | 30 | **94** | 14.9 J | **45.1 J** |

Both resolved (787 and 316 substeps), `state_valid: true`, zero refusals. Glass
breaks more bonds for far less fracture work than oak, which is the expected
brittle/tough ordering.

## What this does not establish

- **It is not fragmentation.** The 12 m/s glass case reports 14 components, but
  the largest holds 95 of 108 cells: one mostly intact panel and about thirteen
  single-cell chips. A 6x9x2 panel is two cells thick and cannot represent a
  shard. Fragment counts from this mesh are not a shatter result.
- **It is not calibration.** Nothing here compares against laboratory glass. The
  strength-based lattice criterion and its `Gc` disagreement are unchanged.
- **It is not spatial convergence.** Only the temporal stability bound is
  enforced. Mesh refinement is untouched, and the fragment counts above are not
  claimed to converge.
- **The fine meshes are unverified.** 10x15x4 at 600 cells needs 254 to 670
  substeps; a 0.5 s run did not complete in 45 minutes and was abandoned. Their
  at-rest behaviour after this change is not measured.
- **The cost is large.** 315 to 787 internal solves per host tick. The 108-cell
  0.5 s at-rest case takes about 3 minutes, roughly 360x slower than real time,
  and the full ctest suite went from 88 s to over an hour. Correctness here is
  bought with wall clock, and world-scale realtime is further away than the
  earlier numbers suggested, because those numbers were measured on an
  integration that was not stable.

## Next

Measure the fine-mesh at-rest cases to completion. Establish whether
`kStabilityPhaseRadians` can be loosened without reintroducing the instability,
since substep count and therefore cost scale directly with it. Then revisit the
spatial question: fragment counts cannot be trusted until a mesh that can
represent a shard is affordable at a stable step.
