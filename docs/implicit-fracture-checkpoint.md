# Fracture in the implicit solver

Tested code: branch `agent/implicit-fracture` in worktree `C:/Users/henry/dev/banjo-agents/implicit`, based on `1d2d89f`. September 7, 2026, America/Los_Angeles. Not pushed, not merged, not on main.

Predecessors: the [global elastic solve](elastic-newton-checkpoint.md) that this lane extends, the [coupled support evidence](coupled-support-checkpoint.md), and the [glass shatter diagnosis](glass-shatter-diagnosis.md) that produced the failure criterion being reused.

## Result

The implicit (Newton/GMRES) conservative reference can now break bonds. It uses the *same* failure criterion as the explicit XPBD lane, not a copy of it. A step that would leave a bond past its failure strain is treated as inadmissible: the step is discarded, the bond is removed, and the same interval is solved again against the new topology, using the existing transactional mechanism. Fragments are the connected components that remain. Nothing precuts geometry, animates a shatter, or assigns a fragment velocity.

Three things are **implemented and measured**:

- Glass fractures under a resolved floor impact: 5,478 of 17,097 bonds removed, 71 connected components, with the mechanical ledger closing to `9.19e-10 J` once the removed bond energy is named.
- The cost of arming fracture is **+2.9% wall time when nothing breaks**, and 1.2x to 4.1x when it does, depending on step length.
- The fracture criterion re-imposes an accuracy limit that the implicit solve had removed. Bulk outcomes (removed energy, largest fragment mass) converge once the step drops below the lattice's own elastic-wave resolution limit; the **fragment count and broken-bond count do not converge at any step tested**.

Nothing here is **validated** against laboratory data. There is no Gc calibration, no fragment-size distribution claim, no friction, damping or restitution, and no fragment-fragment contact. Oak and iron are still catalog `RigidOnly` presets; they are fractured here through an explicitly-labelled strength-derived isotropic surface with no grain, anisotropy, yield or plasticity.

## Method

### One criterion, two lanes

`src/fracture/BondFailure.{hpp,cpp}` is new and holds the criterion that was file-local inside `src/fracture/BrittleBondSolver.cpp`: the nonlocal Green-Lagrange node strain, its resolution along each bond's own rest axis, the damage ramp, and the removal rule that charges the bond's stored energy to `unassigned_bond_removal_energy_j`. The move is code motion; every statement and its order are preserved. `BrittleBondSolver::step` now calls `resetBondStrainPeaks`, `accumulateBondStrainPeaks` and `applyBondFailure` instead of its own copies, and the implicit lane calls the same three functions.

The explicit lane's existing tests were not touched and still pass, including `banjo_bond_failure_orientation_tests`, which pins the oriented criterion. More directly, the full `banjo_glass_diagnostic` run reproduces the broken-bond set, component count and removal energy it produced before this branch existed, to every published digit; see [the explicit lane is unchanged](#the-explicit-lane-is-unchanged).

`withStrengthDerivedFailure` in `src/material/MaterialCompiler.{hpp,cpp}` factors the strength-to-strain conversion out of `compileBrittleMaterial` and makes it applicable to an already-compiled elastic reference. `compileBrittleMaterial` now calls it, so a `BrittleBond` preset compiled either way gets identical thresholds. It does **not** declare a material brittle: it adds the isotropic central-bond strength surface and nothing else, leaving the elastic reference's zero damping and zero strength variation in place so a material comparison is not confounded by a randomised strength field.

### Transactional fracture

`src/physics/FractureStep.{hpp,cpp}` wraps `tryConservativeStep`. For one frame:

1. Sample the bond strain peaks at the interval's start.
2. Take an implicit step. If it fails its convergence or mechanical audit, restore the whole frame and report `SolverRejected`.
3. Sample the peaks again at the accepted end state, and apply the shared criterion.
4. If no bond failed, commit the segment and continue with the remaining time.
5. If a bond failed, the interval was solved with a bond that should not have been there. Discard the trial, restore the segment's start state, remove the failed bonds *there*, and re-solve the same interval. Repeat until an interval carries no new failure or the trial budget runs out.

Two endpoint samples per interval mirror the two samples the explicit lane takes per substep. A strain excursion that peaks strictly inside an interval and returns below threshold before its end is invisible at that step length. That is a resolution limit of the step, not of the criterion.

Removing a bond is a topology change *between* conservative trials, so it can never widen a trial's own energy, momentum or penetration audit; those budgets are unchanged. What leaves the ledger is the stored energy the bond held at the instant of removal, reported as `removed_bond_energy_j`. The frame is transactional as a whole: on any failure every node, bond, damage value and sphere value is exactly what it was on entry, including segments that had already been advanced.

### Removal instant

`BondFailureTiming` selects when a failing bond is removed, because that is a physical choice and not bookkeeping:

- `EndOfStep` accepts the overstressed interval and then removes the bond. One solve per step; the bond carried load for the whole interval while already past failure.
- `StepRestart` (default) discards the interval and removes the bond at its start.
- `BisectedTime` halves the interval, up to a per-frame budget, before restarting, converging the removal instant from above.

### Probe

`banjo_solver_probe` gains `--step-mode fracture`, `--fracture-timing end|restart|bisect`, `--fracture-trials`, `--bisections` and `--stretch-rate`. Fracture mode compiles the strength-derived failure surface, sets the reference positions the nonlocal strain needs, and reports broken bonds, connected components, largest component, detached node count and mass fraction, per-mode failure counts, removed bond energy, solver trials and discarded trials. It also prints the lattice's own resolution limit and the step's ratio to it. The other step modes are unchanged; `--step-mode raw` output at the previous checkpoint's conditions is identical (coarse free case still reports 3 outer / 62 linear iterations).

## Conditions

Two scenarios, both on `generateSphereLattice({0.25, h, 2, 3})`:

- **Free flight (S1).** Translation `(0.3,-0.1,0.2) m/s`, spin `(1,-2,3) rad/s`, zero gravity, no support. This is the previous checkpoint's case.
- **Floor impact (S2).** Translation `(0.3,-20,0.2) m/s`, zero spin, support plane 1 mm below the lowest node, zero gravity, coupled support solve.

`h=0.12` gives 81 nodes / 773 bonds; `h=0.04` gives 1,285 nodes / 17,097 bonds. Strength-derived thresholds, uniform across bonds:

| Material | tensile damage → break | shear damage → break | compression damage |
|---|---|---|---|
| glass | 6.4286e-4 → 1.2857e-3 | 1.22e-3 → 2.44e-3 | 1.4286e-2 |
| oak | 7.5e-3 → 1.5e-2 | 2.475e-3 → 4.95e-3 | 4.3333e-3 |
| iron | 1.1848e-3 → 2.3697e-3 | 2.0787e-3 → 4.1573e-3 | 2.8436e-3 |

The lattice reports its own limit through `measureLatticeResolutionLimit`. For the `h=0.04` glass lattice the fastest bond mode has period `4.643e-6 s` and an explicit-integration substep limit of `1.478e-6 s`. The implicit solve is not conditionally stable, so exceeding that limit does not diverge; it bounds *accuracy*, and the fracture criterion reads strain, so it inherits that bound. The 1/240-second target step is **2,819x** the limit, the same ratio the [shatter diagnosis](glass-shatter-diagnosis.md) recorded for the shipped material substep.

## 1. Fracture, measured

S2, `h=0.04`, glass, `dt=2e-5 s`, 30 steps (6e-4 s simulated):

| Quantity | Value |
|---|---|
| Bonds removed | 5,478 of 17,097 |
| Connected components | 71 |
| Largest component | 1,146 of 1,285 nodes |
| Detached mass fraction | 10.97% |
| Removed bond energy | 9,289.38 J |
| Failure modes | 2,436 tensile / 51 compressive / 2,991 shear |
| Energy residual (frame ledger, removal named) | `9.19e-10 J` |
| Linear momentum residual | `7.70e-11 N s` |
| Angular momentum residual | `5.28e-11 kg m²/s` |

Breakage is progressive, not a single event: 212 bonds at step 3, then 240, 440, 388, 240, 92, and the component count rises from 1 to 71 over steps 9 to 29. That is a growing crack network rather than a body that dissolves at once.

### Glass, oak and iron under the same conditions

S2, `dt=2e-5 s`, same lattice, same impact:

| Lattice | Material | Broken | Components | Largest | Detached mass | Removed J | max tensile ε |
|---|---|---|---|---|---|---|---|
| `h=0.12`, 40 steps | glass | 99 | 2 | 72/81 | — | 5,314.6 | 1.23e-3 |
| `h=0.12`, 40 steps | oak | 0 | 1 | 81/81 | — | 0 | 3.66e-3 |
| `h=0.12`, 40 steps | iron | 11 | 1 | 81/81 | — | 1,372.8 | 2.33e-3 |
| `h=0.04`, 30 steps | glass | 5,478 | 71 | 1,146/1,285 | 10.97% | 9,289.4 | 1.28e-3 |
| `h=0.04`, 30 steps | oak | 250 | 2 | 1,260/1,285 | 1.02% | 669.1 | 2.75e-3 |
| `h=0.04`, 30 steps | iron | 250 | 2 | 1,260/1,285 | 1.02% | 2,042.4 | 8.93e-4 |

The ordering is the expected one: glass has the lowest failure strain of the three and is the only material that fragments. Oak survives the coarse case entirely.

**The oak and iron full-lattice numbers should not be read as a material result.** Both remove exactly 250 bonds, detaching exactly the same 25 nodes, on one step and then stop, with 0 tensile / 50 compressive / 200 shear failures in both. Two materials whose shear thresholds differ by 19% and whose compression thresholds differ by 52% cannot coincidentally lose the identical bond set.

The node masses say what the trigger is. Occupancy sampling of partially-filled surface cells gives every material's lattice a **27:1** node-mass spread (glass `0.00593`–`0.16 kg`, oak `0.00166`–`0.0448`, iron `0.01865`–`0.50368`). Expressed as a fraction of the heaviest node, oak's detached set spans `0.111`–`0.667` and iron's spans exactly the same `0.111`–`0.667`: the identical 25 light surface nodes, and every one of them below the lattice mean. Glass's detached set spans `0.111`–`1.000` of the heaviest node, so glass is detaching full-mass interior material as well as surface cells.

Oak and iron are therefore showing a contact-patch spall of the sampled surface, not material fracture. This is a discretisation artefact and it is the first thing to fix before any oak or iron fracture claim. Glass's result does not reduce to it.

## 2. Cost

Machine: Intel Core Ultra 9 285K, Windows 11 Pro build 26200, MSVC 19.44.35228, CMake 4.1.2, VS 2022 x64 Release, `-DBANJO_BUILD_LAB=OFF`. Serial measurement with other applications present; not an isolated benchmark.

### Overhead when nothing breaks

S1, `h=0.04`, `dt=1/240 s`, 20 steps, three repetitions:

| Repetition | No fracture, median | Fracture armed, median |
|---|---|---|
| 1 | 47.489 ms | 48.539 ms |
| 2 | 48.014 ms | 49.282 ms |
| 3 | 47.915 ms | 49.331 ms |

**+2.9%**. Newton iterations (4) and Krylov iterations (359) are identical, and the energy/momentum residuals are bit-identical, so the extra time is the criterion evaluation over 17,097 bonds and nothing else. At `dt=1/240 s` this lands at **11.8x slower than realtime** — the same order as the 13x recorded without fracture at the previous checkpoint.

### Cost when it does break

S2, `h=0.04`, glass:

| Step | Steps | No fracture median | Fracture median | Ratio | Newton | Krylov | Solver trials / step | Discarded |
|---|---|---|---|---|---|---|---|---|
| `2e-5 s` | 30 | 10.94 ms (p95 14.24) | 44.36 ms (p95 78.02) | 4.06x | 4 | 52 | 4.50 | 105 of 135 |
| `6.25e-7 s` | 960 | 4.294 ms (p95 5.80) | 5.235 ms (p95 17.30) | 1.22x | 3 | 6 | 1.57 | 551 of 1,511 |

The retopology overhead falls as the step shortens, because fewer bonds fail per step and fewer trials are discarded. Newton and Krylov counts per *accepted* trial are unchanged by fracture; the entire extra cost is discarded trials.

### Distance from realtime

| Case | Wall | Simulated | Factor |
|---|---|---|---|
| S1, `dt=1/240 s`, fracture armed, nothing breaks | 49.3 ms/step | 4.167 ms/step | **11.8x** |
| S2, `dt=6.25e-7 s`, fracture active, converged-energy regime | 7.102 s | 6.0e-4 s | **11,837x** |
| S2, same, no fracture | 4.116 s | 6.0e-4 s | 6,860x |

The second row is the honest number for a fractured impact whose energy ledger has converged. Fracture itself contributes a factor of 1.7 to it; the other 6,860 comes from needing a step below the lattice's elastic-wave resolution limit.

## 3. Timestep refinement: the fragment outcome does not converge

S2, `h=0.04`, glass, **fixed 6.0e-4 s of simulated time**, `StepRestart`:

| dt (s) | dt / substep limit | Steps | Broken bonds | Components | Largest | Detached mass | Removed J |
|---|---|---|---|---|---|---|---|
| 4.0e-5 | 27.06 | 15 | 3,929 | 41 | 1,178 | 8.72% | 4,566.7 |
| 2.0e-5 | 13.53 | 30 | 5,478 | 71 | 1,146 | 10.97% | 9,289.4 |
| 1.0e-5 | 6.77 | 60 | 5,952 | 110 | 1,076 | 17.56% | 13,406.6 |
| 5.0e-6 | 3.38 | 120 | 5,934 | 94 | 1,114 | 11.57% | 16,143.6 |
| 2.5e-6 | 1.69 | 240 | 4,845 | 69 | 1,126 | 12.24% | 18,311.3 |
| 1.25e-6 | 0.846 | 480 | 5,713 | 86 | 1,122 | 10.88% | 18,512.9 |
| 6.25e-7 | 0.423 | 960 | 5,551 | 65 | 1,118 | 12.04% | 18,525.3 |

Two different behaviours, separated by the lattice resolution limit:

**Continuous measures converge below the limit.** Removed bond energy over the last three refinements is `18,311.3 → 18,512.9 → 18,525.3 J`: successive changes of 1.10% then 0.067%. The largest component goes `1,126 → 1,122 → 1,118` nodes, a 0.36% change per halving. Above the limit the same quantity drifts by a factor of four.

**The discrete outcome does not converge anywhere.** Broken bonds run `3,929 → 5,478 → 5,952 → 5,934 → 4,845 → 5,713 → 5,551`, non-monotonic with a 1.51x spread over the ladder and still ±9% over the last three points where the energy has settled to 0.07%. Component counts run `41 → 71 → 110 → 94 → 69 → 86 → 65`, a 2.7x spread with no trend.

The coarse lattice behaves the same way. S2, `h=0.12`, glass, fixed 8.0e-4 s:

| dt (s) | Steps | Broken | Components | Removed J |
|---|---|---|---|---|
| 4.0e-5 | 20 | 98 | 3 | 5,129.7 |
| 2.0e-5 | 40 | 99 | 2 | 5,314.6 |
| 1.0e-5 | 80 | 195 | 1 | 7,669.7 |
| 5.0e-6 | 160 | 195 | 2 | 9,308.9 |
| 2.5e-6 | 320 | 165 | 4 | 7,580.2 |

**This is the single most important result and it is negative.** The explicit network lane's fragment counts do not converge: 221–299 broken bonds, non-monotonic, over a 20x refinement. The implicit lane's do not converge either: 3,929–5,952 broken bonds and 41–110 components, non-monotonic, over a 64x refinement. On this axis the implicit lane is not an improvement. Removing the wave-speed *stability* limit did not remove the wave-transit *accuracy* limit, and fracture is an accuracy-limited quantity: it reads a strain field that only exists once the lattice can carry its own elastic wave.

What the implicit lane does add is that the boundary is now visible and cheap to cross. `dt = 6.25e-7 s` is 0.42 of the lattice limit and costs 5.2 ms per step on 1,285 nodes; the explicit lane's constraint is the same 1.478e-6 s, and it does not get to choose a larger step at all.

## 4. Removal instant: it matters, and refinement does not settle it

S2, `h=0.04`, glass, fixed 6.0e-4 s:

| dt | Timing | Broken | Components | Removed J | Solver trials | Trials/step |
|---|---|---|---|---|---|---|
| 2e-5 | end | 4,281 | 79 | 24,041.9 | 30 | 1.00 |
| 2e-5 | restart | 5,478 | 71 | 9,289.4 | 135 | 4.50 |
| 2e-5 | bisect | 6,234 | 111 | 15,362.3 | 743 | 24.77 |
| 5e-6 | end | 4,097 | 52 | 20,709.9 | 120 | 1.00 |
| 5e-6 | restart | 5,934 | 94 | 16,143.6 | 351 | 2.93 |
| 5e-6 | bisect | 5,681 | 68 | 17,643.5 | 2,319 | 19.33 |

The removal instant changes broken bonds by up to 46%, component count by up to 56% and removed energy by up to 2.6x, at 1x, 3–4.5x and 19–25x the solver work. Keeping the overstressed bond for the whole interval (`end`) removes the *most* energy, because the bond is at its most stretched when it is finally cut; restarting removes it at the last configuration that satisfied the criterion, so it removes the least.

Refining the step from `2e-5` to `5e-6` does not bring the three into agreement. That is consistent with section 3: the underlying discrete outcome is not converged, so no choice of removal instant can be validated against it yet. `StepRestart` is the default because it is the only one of the three that never advances a state through a bond the criterion has already rejected, and because it costs a quarter of what bisection costs.

## 5. What does not work

- **The lane cannot take an impact at a realtime step.** S2 at `dt = 1/240 s` is rejected by `tryConservativeStep` on its first step, with the input state untouched. At 20 m/s the sphere would move 83 mm past the plane in one step. This is the contact/penetration audit, not fracture, and it is unchanged from the previous checkpoint — but it means the 11.8x free-flight number is not a fracture number.
- **The implicit solve stops converging on heavily fragmented states.** S2, `h=0.04`, `dt=1.25e-4 s`, `StepRestart`: steps 0–20 are accepted, reaching 5,231 broken bonds and 69 components, then step 21 is rejected with a constitutive velocity residual of `664.79 m/s`. Raising the budget from (256 outer, 400 linear) to (1024, 8000) does not change the outcome; nor does `--support-solver split`. The same scenario with fracture off, and the same scenario with `--fracture-timing end`, both complete all 24 steps. So it is the fragmented configuration — many small components resting on the support — that the coupled Newton/support system cannot resolve, not a budget shortfall. The frame is correctly rolled back, so this is a stall, not a corruption.
- **Fragment count and broken-bond count are not converged** at any step tested, as measured in section 3.
- **The oak and iron fracture is a discretisation artefact**, as measured in section 1: the same 25 low-mass surface nodes, at the same fraction of the heaviest node, for two different strength surfaces.
- **There is no fragment-fragment contact.** Detached components pass through each other and through the parent body; `tryConservativeStep` resolves material/support and material/sphere normal contact only. A "shattered" state is therefore not a physical post-fracture state.
- **Still absent from this lane:** friction, restitution, internal damping, plasticity, and any Gc-calibrated cohesive law. Damage does not soften a bond before it removes it, so the material has no pre-failure nonlinearity.
- **A cascade can exhaust the trial budget.** Each discarded trial removes at least one bond, so the loop terminates, but a frame in which many rounds of load redistribution each break new bonds will hit `maximum_solver_trials` (default 64) and be rejected wholesale. That was not reached in the runs above (worst observed: 24.8 trials per step under `bisect`), but it is a real failure mode for a larger step or a more violent load.

## Verification

Windows Release, `-DBANJO_BUILD_LAB=OFF`. `python scripts/check-source-registration.py` reports 188 of 188 sources registered.

**85 of 85 CTest suites pass** (78.85 s), excluding `banjo_network_skin_tests` and `banjo_network_runtime_tests`, which were excluded by instruction because each now takes roughly an hour. The baseline on the same exclusion, before any change, was 84 of 84. The one added suite is `banjo_implicit_fracture_tests`. **No existing test's tolerance was changed and no existing test file was edited.**

### The explicit lane is unchanged

Passing tests are necessary but not sufficient for a criterion refactor, so the explicit lane was also compared numerically against its own previously published output. `banjo_glass_diagnostic` at unchanged defaults (iron striker, 8 m/s, glass target, concrete support, gravity on, 1,285 nodes / 17,097 bonds, 105 ticks) reproduces every value the [shatter diagnosis](glass-shatter-diagnosis.md#measured-effect) recorded before this branch existed:

| Quantity | Recorded pre-refactor | Measured on this branch |
|---|---|---|
| Broken bonds | 16,932 / 17,097 | 16,932 / 17,097 |
| Connected components | 1,124 | 1,124 |
| Largest component | 8 nodes | 8 nodes |
| Unassigned bond-removal energy | 1.893809e+05 J | 1.89381e+05 J |
| Mass error | -3.5e-12 kg | -3.49587e-12 kg |

A 17,097-bond fracture run reaching the identical broken-bond set, component count and removal energy is direct evidence that moving the criterion changed nothing in the lane it came from.

`tests/implicit_fracture_tests.cpp` adds six checks:

- Explicit and implicit lanes, handed the same strained lattice and the same short interval, name the identical failing bond set, for glass, oak and iron. This is the check that the two lanes cannot silently disagree.
- No material loses a bond, or accumulates any damage, at 90% of its damage-start strain.
- A rejected fracturing frame retains every position, velocity, damage value and aliveness flag exactly, both when the solver budget is starved and when the trial budget stops a cascade.
- Severing every axial bond of the fixture leaves exactly the three transverse planes, nine nodes each — fragments are the surviving components.
- Over 20 steps, `E_after - E_before + removed_bond_energy` equals the sum of the accepted per-step energy residuals to `1e-9 J`.
- All three removal instants converge, cost 1 / >1 / ≥restart solves respectively, and remove measurably different amounts of stored energy.

Reproduction:

```powershell
# Explicit-lane comparison against the pre-refactor published numbers
./build/agent/Release/banjo_glass_diagnostic.exe

cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 4
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests" --output-on-failure

# Section 1: fracture and the material comparison
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --material glass --case floor --voxel-size 0.04 --dt 0.00002 --steps 30 --speed 20
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --material oak   --case floor --voxel-size 0.04 --dt 0.00002 --steps 30 --speed 20
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --material iron  --case floor --voxel-size 0.04 --dt 0.00002 --steps 30 --speed 20

# Section 2: overhead when nothing breaks, and the converged-regime cost
./build/agent/Release/banjo_solver_probe.exe                        --voxel-size 0.04 --dt 0.004166666666666667 --steps 20
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture   --voxel-size 0.04 --dt 0.004166666666666667 --steps 20
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --case floor --voxel-size 0.04 --dt 0.000000625 --steps 960 --speed 20

# Section 3: the refinement ladder (dt x steps is constant at 6e-4 s)
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --case floor --voxel-size 0.04 --dt 0.00004      --steps 15  --speed 20
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --case floor --voxel-size 0.04 --dt 0.0000025    --steps 240 --speed 20
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --case floor --voxel-size 0.04 --dt 0.000000625  --steps 960 --speed 20

# Section 4: removal instant
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --fracture-timing end     --case floor --voxel-size 0.04 --dt 0.00002 --steps 30 --speed 20
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --fracture-timing bisect  --case floor --voxel-size 0.04 --dt 0.00002 --steps 30 --speed 20

# Section 5: the stall on a fragmented state, and that a larger budget does not fix it
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --case floor --voxel-size 0.04 --dt 0.000125 --steps 24 --speed 20
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --case floor --voxel-size 0.04 --dt 0.000125 --steps 24 --speed 20 --iterations 1024 --linear-iterations 8000
./build/agent/Release/banjo_solver_probe.exe --step-mode fracture --case floor --voxel-size 0.04 --dt 0.004166666666666667 --steps 1 --speed 20
```

No Linux, macOS, cross-GPU or determinism claim is made. No cached outcome or scenario version changed; this lane is not part of `RollingBallExperiment` or any cached lab simulation.

## Next

Ordered by what blocks the most:

1. **Fix the surface-node mass artefact.** A 27:1 node-mass spread across the sampled surface makes the lightest cells fail first under any contact, which is why oak and iron lose the identical 25 nodes. Mass lumping or a minimum represented volume would remove a failure mode that has nothing to do with the material.
2. **Establish whether the fragment count can converge at all** at fixed lattice resolution, by refining the *lattice* alongside the step. The evidence here separates the step-resolution question from the criterion; it does not answer whether the criterion has a converged answer to give.
3. **Fragment-fragment contact.** Without it the post-fracture state is not physical, and no fragment-count measurement can be trusted past the first separation.
4. **Diagnose the fragmented-state Newton stall** in section 5. A component of a few free nodes on the support plane is a degenerate case for the coupled support solve; it likely needs per-component conditioning or a separate handoff rather than a bigger Krylov budget.
5. Only then: friction, restitution and internal damping, and a Gc-calibrated law to replace the strength-derived surface.
