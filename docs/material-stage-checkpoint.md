# Accepted-state damage and active-stage accounting

September 4, 2026, America/Los_Angeles. Tested code **`d56611cd582a1e51e4169ef10e62aa5773eec75b`**, local `codex/physics-foundation`, worktree `C:/Users/henry/dev/banjo-integration`. Original main remains `3a38d7d`; this work is not pushed or merged. Source ancestry and Windows toolchain remain as recorded in the previous transfer checkpoint: MSVC 19.44, Release x64, Windows 11 build 26200, Jolt v5.6.0, raylib 6.0, RTX 5090.

## Corrected defect

The old bond solver accumulated damage from predicted positions and every intermediate constraint iteration. Those are numerical guesses. A stiff spring could break even though its accepted strain remained below the damage threshold. Damage now samples the beginning and end of each physical substep, retaining strain already present at the beginning and previously accumulated irreversible damage. Intermediate solver iterates cannot add damage history.

An independent two-mass, one-spring test reproduced the defect before the fix. With unit masses, rest length 1 m, compliance `c=1e-5 m/N`, initially zero extension and separating relative speed 0.4 m/s, the one-dimensional implicit solution is:

`extension_end = dt * 0.4 / (1 + 2*dt*dt/c)`.

At `dt=0.01 s`, the predictor extends the bond by 0.004 m, above its 0.002 failure threshold. The solved extension is only 0.000190476 m, below the 0.001 damage onset. The old code failed this test; the new code passes at timesteps 0.0025, 0.005, 0.01 and 0.02 s, each with 1, 4 and 12 iterations. Position and kinetic/elastic energy agree with the analytical solution to absolute `1e-12` in the corresponding SI units. A separate initially strained fixture still breaks and reports the removed stored energy.

The distinction between predicted positions, iterative solves and the accepted position/velocity update follows [XPBD Algorithm 1 and its implicit discretization](https://matthias-research.github.io/pages/publications/XPBD.pdf). The damage sampling rule and regression are Banjo implementation decisions; this is not a claim that the paper validates Banjo's fracture law. Endpoint sampling may miss real strain peaks when time resolution is insufficient. Timestep convergence and physical calibration remain required.

## Removed synthetic excitation

The obsolete opt-in internal impact pulse and its helper code were removed. Nonzero `impact_internal_energy_fraction` is rejected by the material solver and outcome-key builder; the legacy cap field remains ignored for compatibility. Runtime contact already used a zero pulse. The default outcome-key pulse fraction is now zero.

One historical test expected an arbitrary 350 J internal pulse to shatter a glass lattice. After corrected damage sampling it failed. That expectation had no independent fracture oracle and contradicts the contact-driven contract. It was replaced with a stronger activation boundary test: impact metadata cannot manufacture node velocity, an uncontacted resting lattice stays at rest, and legacy pulse settings fail explicitly. Existing actual-contact damage tests and tensile/compressive/shear fixtures still pass; no strength or tolerance was changed to make the suite green.

Outcome format stays 2; solver model is now **5**. Tests reject model-4 outcomes and nonzero synthetic-excitation keys. Full cache identity/applicability remains unfinished.

## Stage measurement boundary

`--audit-csv PATH` now enables optional full-state measurements for gravity kick, contact before prediction, position prediction, constraints/velocity reconstruction, damping, contact after constraints, support and damage. Each stage exports cumulative changes in kinetic, elastic and gravitational energy plus linear/angular momentum. Angular quantities use the world origin. The measured boundary includes active matter and the finite-mass coupled sphere proxy; it excludes the separate Jolt advance, activation, coarsening and subsequent debris/fragment evolution.

The CSV retains earlier columns and appends `audited_material_steps` plus nine fields for each stage. Stage columns are cumulative; do not sum them across CSV rows. Zero audit steps means the stages were not sampled. Sampling is disabled by default in the viewer to avoid extra full-lattice traversals. A regression checks identical positions/velocities with sampling on and off.

The sum of numerical-stage changes telescopes to the measured material-step change. **That identity is a diagnostic completeness check, not a proof of physical conservation.** Prediction can temporarily inflate elastic energy before an implicit solve removes it. Geometric correction can change stored energy without a physical work source. These must not be relabeled heat or fracture work.

## Verification at the tested commit

- Windows Release build and all **nine** CTest executables passed (4.33 s for the final full CTest run). No new Linux/macOS or remote-CI claim.
- The new suite has five checks: the 12-case spring reference; accepted-state failure/removal energy; separate gravity/support budgets; unchanged trajectory under optional sampling; finite-sphere contact reaction/energy.
- The gravity/support fixture checks `m*g*dt`, the semi-implicit gravity energy loss, normal/friction impulse, and potential added by floor position correction. Momentum/energy comparisons use absolute `1e-12` in their SI units.
- The finite-sphere fixture independently predicts a 0.8 N·s normal impulse, 0.4 N·s sliding impulse and 0.9 J kinetic loss. Its stage momentum changes vanish within `1e-12`, including sphere spin reaction.
- Supported and isolated headless runs exported CSV at this commit. The 210-frame, 1280×800 capture exists and was visually inspected: panels, units and clock are readable. The normal lab was launched again and input checked.
- Normal input: pause held at tick 4011, N advanced once to 4012, and R reset/resumed (first observed state tick 66 / 0.55 s). The viewer showed 18 FPS during an active-fracture observation and about 60 after handoff, with another baseline lab also open. This is not an isolated benchmark or a real-time performance claim; accepted-state strain sampling now traverses the neighborhood twice per substep, and its cost needs profiling.

Reproduce with the existing separate build directory:

```powershell
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
./build/win-integration/Release/banjo_headless.exe --audit-csv build/win-integration/stages-supported.csv
./build/win-integration/Release/banjo_headless.exe --isolated --target-speed 1 --audit-csv build/win-integration/stages-isolated.csv
./build/win-integration/Release/banjo_lab.exe --capture build/win-integration/stages.png --frames 210
./build/win-integration/Release/banjo_lab.exe
```

## Results and unresolved defects

| Measurement | Default supported | Isolated, target speed 1 m/s |
|---|---:|---:|
| CSV rows / final simulated time | 226 / 1.875 s | 378 / 3.141667 s |
| Audited material microsteps | 891 | 1,208 |
| Broken bonds / components | 11,729 / 804 | 0 / 1 |
| Rigid fragments / overflow debris | 64 / 740 | 1 / 0 |
| Initial / final total mechanical energy | 24,747.211 / 9,884.796 J | 23,191.257 / 18,151.705 J |
| Predictor energy change | +164.611 MJ | +124.017 MJ |
| Constraint-stage energy change | -174.925 MJ | -125.266 MJ |
| Post-constraint contact kinetic change | -3,201.622 J | -2,517.160 J |
| Post-constraint contact elastic change | +4,940,245.022 J | +1,246,433.151 J |
| Support kinetic change | -5,559.151 J | 0 |
| Support elastic change | +15,897,056.899 J | 0 |
| Support gravity-potential change | +11.981 J | 0 |
| Removed bond spring energy | 10.52045 MJ | 0 |
| Constraint angular-change vector norm | 5.959968 kg·m²/s | 5.135864 kg·m²/s |

The positive elastic changes in contact/support occur while those stages remove kinetic energy. They directly expose energy added by separate position corrections. The large predictor/constraint terms also show why reporting either alone as dissipation is misleading. The supported run breaks fewer bonds than the previous model, but this is **not evidence of calibrated material realism or a repaired energy budget**. It also retains 7,161.484 J of spring energy that is discarded at coarsening, separately reported. The isolated body now hands off intact on timeout; eliminating false predictor damage does not prove that this impact ought physically to leave glass intact.

The shortened isolated runtime transfer fixture still has whole-run delta-P `0.164904 N·s` and delta-L `5.28608 kg·m²/s`. The norm of recorded numerical angular changes is `5.30214`; the remaining angular vector has norm `0.0470261 kg·m²/s`. Transfer tests pass independently; the full simulation remains unvalidated. Jolt single-precision synchronization, solver angular drift, correction work, and physical fracture work remain open.

## Next acceptance work

Gate 1 is still active. Couple nonpenetration/contact with material response so position correction cannot inject unbudgeted strain energy after the solve. Establish consistent rigid/material temporal states, measure all Jolt/support/debris reactions and work, and repair angular drift. Preserve the analytical spring and transfer regressions; add passive full-system tests that fail on unexplained creation. Then validate timestep/iteration/resolution dependence before calibrated fracture coupons or broader material/shape claims.
