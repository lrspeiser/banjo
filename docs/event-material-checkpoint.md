# Event contact and comparative-material checkpoint

September 4, 2026 (local evening; logs use September 5 UTC). Tested code: `dc49f1293dd656bac3a33e717e1a9bd29555bf5d`, local `codex/physics-foundation`. This extends the [coupled support reference](coupled-support-checkpoint.md). Main remains at the previously pulled `3a38d7d6e37f12657baa2777cb906c1682c9b098`; these changes are not pushed or merged. The laboratory still uses the default solver whose [energy defects](material-stage-checkpoint.md) remain unresolved. Gate 1 is open.

## What changed

`ConservativeAdvance` locates new normal contacts using unpublished, masked solves from a common starting state. It brackets arrival, applies an instantaneous frictionless normal impulse with a prescribed restitution coefficient, and continues motion for the remainder of the requested interval. Existing contacts retain their coupled elastic/support solve. Finite spheres receive the equal and opposite reaction. Position is not projected onto the surface, and a second continuous-contact impulse is not applied for the instantaneous event.

The full requested interval is transactional. Failed event location, solver convergence, budgets or whole-interval balances preserve the caller's positions, velocities and sphere state. Internal accepted trials are not published time. The whole-interval energy, linear momentum and angular momentum audit includes gravity work/impulse, support reaction/torque, prescribed impact loss and a separate numerical normal-loss budget.

`NormalImpact` uses unilateral impulse iteration with initial normal speed `w0`, target speed `-e*min(w0,0)` and nonnegative impulse. Its work ledger is `loss = -sum(lambda*(w0+w1)/2)`. For a point of mass `m` striking a fixed plane at speed `u`, the analytical impulse is `m*(1+e)*u` and loss is `m*(1-e*e)*u*u/2`. For an isolated finite pair, replace `m` with the reduced mass in the loss expression. These are the explicit idealized test laws, not calibrated material restitution. Simultaneous impact configurations that fail convergence or increase energy beyond the budget reject; this is not a general validated multiple-impact model.

`compileElasticLatticeReference` explicitly uses catalog density and modulus in the common central-bond elastic approximation. Damage thresholds are disabled, and the catalog model is unchanged: oak and iron are not relabeled as brittle substances. Poisson response, wood grain, metal plasticity, damping and fracture are not established by this approximation.

Material-dependent reference regressions and the new matrix retain **glass, oak (wood), and iron**. Additions must expand the comparison set. Analytical point/spring oracles remain alongside the material cases. The [mechanics scorecard](mechanics-scorecard.md) records 30 mechanics and 10 platform capabilities, evidence, defects, unsupported behavior and next steps. `AGENTS.md` makes this maintenance and comparison rule part of future work.

## Bounds and analytical tests

The raw velocity residual remains `1e-9 m/s`, relative energy/momentum budgets remain `1e-9` with an SI floor of one, and raw geometric tolerance remains `1e-10 m`. Event arrival tolerance is `1e-14 m`; the new controller permits subdivisions down to `1e-15 s`, with at most 2,048 trials and 128 accepted internal substeps. The lower time floor was necessary for near-simultaneous contact arrivals in the three-material coarse case; it does not loosen geometry or conservation. Raw numerical normal loss is separately bounded by `1e-8` of the initial kinetic/elastic energy scale. Whole-interval negative loss is bounded too. The energy scale excludes bulk COM kinetic energy in isolated systems and includes it for fixed supports; potential-energy zero is not a tolerance source.

Seven new top-level analytical/regression checks cover:

- Point/plane phases from immediate contact through no impact during the interval, with `e = 0, 0.3, 1`; analytical post-impact positions, velocities, impulse and loss.
- Accelerated impact timing and post-impact gravity over the full clock.
- A fast point traversing a finite sphere's diameter in an unsplit trial; reaction, flight and work for `e = 0, 0.3, 1`.
- Whole-interval rollback when the substep budget expires after an internal accepted arrival.
- An impact exactly at an interval boundary and the following outgoing flight; resting gravity support.
- Rotated/translated support with a tangential boost, plus invalid input rejection before impact work.
- Glass/oak/iron density, unchanged catalog models, disabled failure thresholds, repeated elastic contacts, independent energy and support-momentum ledgers.

The 17 existing raw-reference checks now include all three materials at the full 1,285-node / 17,097-bond resolution for isolated and supported 2 ms steps. A bounded conservation result does not establish temporal accuracy of high-frequency elastic motion.

## Reproducible comparison

The [36 recorded configurations and results](evidence/event-material-matrix.csv) include both accepted and rejected cases, exact tested source, original pre-commit source metadata, UTC times and elapsed cost.

Run from the repository root after building Release:

```powershell
./scripts/run-reference-matrix.ps1 -VoxelSize 0.12 -OutputDirectory build/reference-matrix-coarse
./scripts/run-reference-matrix.ps1 -VoxelSize 0.04 -OutputDirectory build/reference-matrix-full
```

The script retains all three substances and runs six cases for each: free motion; raw floor impact; event floor impact at 2 ms, 1 ms, and 0.5 ms intervals; and an event impact with prescribed `e = 0.3`. Each asks for the same 2 ms physical duration. It saves the exact command, source HEAD/dirty state, UTC start, exit code, elapsed wall time, per-step diagnostics and final balance when available. The matrix has known rejected experiments, so its aggregate exit is nonzero; individual rows retain the reason. A failed row's work and counters describe unpublished internal trials, not a completed physical experiment.

Shared floor setup: radius 0.25 m; horizon 2; occupancy sampling 3; initially unstrained; translation `(0.3,-1,0.2) m/s`; zero spin/gravity/damage/friction; an infinite static horizontal plane 1 mm below the lowest node; global Newton elasticity/coupled support. Free cases use translation `(0.3,-0.1,0.2) m/s` and spin `(1,-2,3) rad/s`. Geometry and numerical settings are identical within a comparison; mass follows each substance's density.

At coarse spacing 0.12 m, each lattice has 81 nodes and 773 bonds. The unit-restitution 2 ms event interval completes:

| Material | Sampled mass (kg) | Events / trials | Energy residual (J) | Momentum residual (kg m/s) | Final COM vertical speed (m/s) |
|---|---:|---:|---:|---:|---:|
| Glass | 163.36 | 27 / 726 | -1.2734e-9 | 1.5177e-8 | 0.10556495 |
| Oak | 45.7408 | 28 / 804 | 3.8830e-9 | 4.5606e-9 | 0.13073149 |
| Iron | 514.25728 | 27 / 733 | -1.5426e-9 | 4.8076e-8 | 0.10556468 |

Raw numerical normal loss is zero in those event runs; prescribed `e=1` loss is within roundoff. The raw 2 ms floor method instead removes **81.506 J (glass), 22.791 J (oak), 256.557 J (iron)** numerically, almost all incident normal kinetic energy. This common defect across substances is a solver effect. The event method eliminates that defect in this bounded coarse experiment, but does not establish realistic rebound.

**Timestep accuracy remains a defect.** At the same 2 ms elapsed time, splitting into 1 ms intervals reproduces the coarse 2 ms values, but 0.5 ms intervals produce vertical COM speeds **0.23058036 / 0.30042370 / 0.23058006 m/s** for glass/oak/iron. This is substantial disagreement despite passing energy ledgers. Contact phase is not the only temporal error; the stiff elastic response and repeated event sequence need trajectory/error control. These are early-contact velocities, not final rebound coefficients.

**Dissipative sampled impacts remain unresolved.** All three coarse `e=0.3` cases reject at event location, despite the passing analytical restitution oracles. Do not use their speculative loss values as material measurements.

**Full-resolution event stepping remains unresolved.** At spacing 0.04 m (1,285 nodes / 17,097 bonds), raw free/support steps pass for all three materials. Event runs exceed the trial budget, fail event location, or reach the minimum step/loss limit. The nominal 1 ms endpoint cases reject after an internal arrival; a near-boundary remainder is a suspected cause requiring diagnosis. Advance any legitimate remainder without silently dropping time or relaxing the balance contract. Exact rejection reasons remain in the per-case logs. None of the full-resolution event floor runs establishes completed rebound.

## Environment and verification

Windows 11 Pro build 26200; Intel Core Ultra 9 285K; Visual Studio 2022 x64 Release, MSVC 19.44.35228, Windows SDK 10.0.26100; CMake 4.1.2; cached Jolt 5.6 / raylib 6. RTX 5090 / NVIDIA 580.88 / OpenGL 3.3 for the viewer. Main's custom frame control, busy-wait loop and static MSVC runtime options remain OFF.

The complete Release build passes, with no warnings/errors in the recorded build log. All **11 CTest executables pass (6.48 s)**, including the seven new event checks and 17 raw-reference checks. The native laboratory was restarted from the rebuilt executable; rendering at 60 FPS and normal reset input were observed. This is a startup/input check of the unchanged default viewer, not visual validation of the opt-in event solver. No new capture-path, macOS/Linux, cross-GPU or remote-CI claim is made.

The accepted coarse unit-restitution event probes take roughly 0.17–0.19 s of process wall time for 0.002 s of physical time; these are individual observed runs, not a benchmark distribution. Full-resolution rejected trials can take many seconds and do not yield usable advanced state. No real-time claim is supported. Matrix logs record the pre-commit HEAD plus dirty source; `dc49f1293dd656bac3a33e717e1a9bd29555bf5d` records the tested implementation, with no intervening behavioral edits.

## Next work and capability limits

1. Diagnose endpoint remainders, repeated/near-simultaneous contact roots and dissipative contact accumulation for all three materials. Retain bounded rejection and exact rollback; do not hide failures by increasing budgets alone.
2. Establish time-accurate trajectories with elastic error estimates or controlled step refinement, phase sweeps and equal-duration full-resolution runs. Conservation is necessary but insufficient.
3. Improve root/linear-solve cost from measured profiles. The current event search assumes local brackets and tests straight relative sphere sweeps; it is not complete continuous collision detection for arbitrary nonlinear trajectories.
4. After those cases pass, integrate friction/work and synchronized rigid/material ownership into the real runtime; re-audit activation, support, fracture and handoff. Then proceed to calibrated coupons, wood anisotropy, iron plasticity, fracture work and shape comparisons.

The controller currently supports sampled elastic nodes, one optional finite sphere and a static plane with footprint rejection. Finite edges/thickness, moving/curved support, multiple deformable bodies and self-contact remain absent. A contact at the exact interval endpoint uses the incoming state there and is resolved at the next interval start. Geometry within the declared event tolerance can be classified as touching. Persistent contact uses the raw midpoint constraint, not a calibrated compliant contact law. No damage, friction, adaptive matter, creator API or publishing gate is completed by this checkpoint.
