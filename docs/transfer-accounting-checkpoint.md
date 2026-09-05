# Finite-cell spin and representation-transfer checkpoint

Subsequent work: [accepted-state damage and stage diagnostics at `d56611c`](material-stage-checkpoint.md) supersedes the latest-status interpretation, while measurements below remain tied to `68c4908`.

Date: September 4, 2026, America/Los_Angeles. Tested code: **`68c49084f1bdcb2cc20e1c20f55f0499e1a4a3b9`**, local branch `codex/physics-foundation`, worktree `C:/Users/henry/dev/banjo-integration`.

The branch contains main `3a38d7d6e37f12657baa2777cb906c1682c9b098` and draft PR #2 head `138260d2f3d2e30a112f28034731db6052ae1720`. Both remote refs were refreshed before this work and were unchanged. The original checkout remains on main. No changes in this checkpoint have been pushed or merged into GitHub main. Earlier PR CI is not CI for this local code.

## Result and scope

Finite-cell spin and sampled inertia now survive rigid/material/fragment transfers. Measurements include the state accepted by Jolt and the actual overflow-debris representation. Eight Windows CTest executables pass, including a new seven-check transfer suite. The normal viewer and capture path work.

**Gate 1 remains open.** These tests bound representation changes, not the complete nonlinear simulation. The active solver changes angular momentum; its energy accounting is incomplete, and the default supported experiment reports 5.38 MJ of unassigned removed spring energy. Severe over-fragmentation remains. None of those results validates glass fracture or an energy-conserving full simulation.

## Implemented changes and model assumptions

- Active cells retain intrinsic angular velocity with isotropic inertia `Icell = m*h*h/6`, consistent with the existing finite-voxel mass model. Activation copies rigid angular velocity into this degree of freedom. It has no torsional bond or contact coupling; this is a spin reservoir, not a calibrated micropolar material model. Partially sampled boundary cells still use this cubic inertia approximation.
- The target sphere's Jolt inertia uses the sampled lattice rest inertia. Sphere-recipe isotropy is tested at three resolutions. This does not establish mass-property convergence for arbitrary shapes or repair the different geometry used by smooth collision spheres and sampled matter.
- Fragment angular momentum includes both `offset × momentum` and intrinsic cell spin. A valid small inertia tensor is no longer discarded by an absolute determinant cutoff. Rigidification records signed source-minus-rigid kinetic energy and removed live-bond spring energy instead of concealing those losses.
- Overflow debris retains the full component inertia. Its later dynamics still use a fixed-inertia spin reservoir; orientation-dependent torque-free motion and complete support-contact angular dynamics remain incomplete.
- `MechanicalAccounting` measures mass, mass first moment/COM, linear momentum, angular momentum about the world origin, kinetic energy, live-bond spring energy and uniform-gravity potential `-g · mass_first_moment`. Actual Jolt mass and world inertia are read after updates/insertion, outside concurrent stepping. Static support is excluded from dynamic totals.
- Runtime activation and fragment audits record before/after states. Headless CSV adds per-tick totals, damping/contact/coarsening terms, removed-bond spring energy, constraint-stage mechanical changes, and constraint/contact-correction angular changes. These terms do not yet form a closed work/impulse ledger.
- Outcome format 2 / solver model 4 serializes intrinsic spin in the activation frame. Format 1 is rejected because it lacks that state. This is a compatibility break, not an automatic migration or a complete cache-validity implementation; automatic outcome playback remains disabled.

## Environment and reproduction

Windows 11 Pro `10.0.26200`, MSVC `19.44.35228.0`, Visual Studio 2022 x64 Release, SDK `10.0.26100.0`, CMake `4.1.2`. NVIDIA RTX 5090, OpenGL `3.3.0 NVIDIA 580.88`. Pinned dependencies: Jolt `v5.6.0`, raylib `6.0`. A separate `build/win-integration` directory reuses previously fetched dependency sources; the configuration is recorded in the earlier Windows integration checkpoint. Main's three raylib/MSVC CMake fixes remain intact.

Run from the worktree after configuring:

```powershell
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
./build/win-integration/Release/banjo_headless.exe --audit-csv build/win-integration/supported.csv
./build/win-integration/Release/banjo_headless.exe --isolated --target-speed 1 --audit-csv build/win-integration/isolated.csv
./build/win-integration/Release/banjo_lab.exe --capture build/win-integration/transfers.png --frames 210
./build/win-integration/Release/banjo_lab.exe
```

`--isolated` disables gravity and support. `--target-speed` uses m/s; `--voxel-size` uses meters. The default fixed-step/duration settings remain in `ExperimentSettings`. CSV starts at tick zero and stops at the headless handoff endpoint. Diagnostic columns containing cumulative losses or stage changes must not be summed again across rows. A successful headless exit still means the original structural handoff check passed, not that full-step conservation passed.

## Verification and tolerances

| Check | Evidence |
|---|---|
| Build and CTest | Release build and all eight executables passed at the tested code; no new Linux/macOS or remote-CI claim |
| Small spinning cell | 0.002 m cell, 0.02 kg; nonzero spin survives a valid small inertia tensor |
| Rotated spinning sphere | Voxel sizes 0.04, 0.08, 0.12 m; mass/COM/P/L/K transfer tolerance `1e-11`, relative to each declared test scale |
| Actual fragment insertion | Fixture splits cells into singletons, sends four fragments to Jolt and overflow to debris; mass/COM/P/L/K tolerance `2e-6` for actual single-precision Jolt state |
| Coarsening | Opposing radial velocities contain 4 J of internal kinetic energy; projected rigid energy is zero and recorded loss is 4 J |
| Split position correction | Separating overlap preserves P/K but changes L; reported angular change equals measured change to `1e-12`. This tests the diagnostic, not physical correctness |
| Jolt free flight | Gravity impulse agrees within `2e-5` of impulse magnitude; K+U loss follows semi-implicit Euler's `0.5*m*g²*N*dt²` within 0.2% of that discretization loss |
| Runtime transfers | Supported and isolated spinning-target fixtures use shortened active budgets; transfer tolerances `2e-6`, with handoff energy reconciled against named coarsening losses |
| Serialization | Spin survives frame conversion/file round-trip; missing-spin format 1 is rejected |
| Capture | 210-frame 1280×800 PNG exists and was visually inspected; transfer panel, clock and controls are readable |
| Interactive | Pause at tick 7718 / 64.3167 s; N advances to 7719 / 64.3250 s and stays paused; R resets/resumes (next observed frame tick 118 / 0.9833 s) |

Core transfer comparisons use mass-relative error and `max(1, reference magnitude)` for COM, P, L and K; inertia isotropy uses `1e-12` times the diagonal inertia. Existing integration tolerances were not widened in this checkpoint. Measured roughly 50–60 FPS is only a smoke observation with another lab open, not a performance benchmark. Added diagnostic passes have not been profiled.

## Full-run evidence: do not confuse handoff with solver accuracy

| Measurement | Default supported | Isolated, target speed 1 m/s |
|---|---:|---:|
| CSV rows / final time | 246 / 2.041667 s | 234 / 1.941667 s |
| Initial / final measured mechanical energy | 24,747.211 / 12,571.944 J | 23,191.257 / 18,190.683 J |
| Normal impact energy | 3959.371 J | 3042.139 J |
| Broken bonds / components | 17,086 / 1,274 | 4,999 / 279 |
| Rigid fragments / debris | 64 / 1,210 | 64 / 215 |
| Activation delta-P norm | 3.01985e-17 N·s | 7.449344e-8 N·s |
| Activation delta-L norm | 1.010955e-25 kg·m²/s | 1.875731e-6 kg·m²/s |
| Handoff delta-P norm | 8.722969e-8 N·s | 1.690067e-5 N·s |
| Handoff delta-L norm | 1.372063e-9 kg·m²/s | 8.162994e-5 kg·m²/s |
| Handoff mechanical-energy change | -0.01658959 J | -11.20001 J |
| Coarsening kinetic / elastic loss | 0.008744390 / 0.007844798 J | 0.1486680 / 11.05139 J |
| Unassigned removed-bond spring energy | 5,382,703.056 J | 23,472.405 J |
| Accumulated constraint-stage mechanical change | -49,845,927.118 J | -34,663,925.856 J |

The supported handoff energy agrees with named losses to about `4e-7 J`; that local agreement cannot explain the entire run. Removed-bond energy is evaluated as `0.5*extension²/compliance` at removal. It is **not** calibrated crack-surface work, heat, or an independently verified physical energy loss. Constraint-stage change measures before/after projection and velocity reconstruction; it excludes other stages, including prediction and later contacts. Its enormous magnitude alongside removed spring energy demands stage-by-stage investigation. These numbers must not be added to contact loss and called a closed budget.

The separate shortened isolated runtime test has whole-run delta-P `0.00247202 N·s` and delta-L `1.15414 kg·m²/s`. Summing recorded constraint/contact-correction angular vectors accounts for norm `1.1513 kg·m²/s`; the remaining vector has norm `0.00509272 kg·m²/s`. The test asserts transfer accuracy, not these full-run residuals. Named numerical change is not physical conservation and must be reduced/justified before Gate 1 can pass.

## Next work

Audit predicted-position spring-energy changes, constraint work, geometric correction, damage removal, support reactions and Jolt/debris losses as distinct stages with a telescoping total. Add passive isolated reference experiments that fail on unexplained creation, then repair the responsible update rules and validate timestep/iteration dependence. Preserve the new transfer checks. Fracture-work calibration, coupon/property convergence and over-fragmentation are still Gate 2 work; general geometry, assemblies, authoring and publishing remain subsequent gates.
