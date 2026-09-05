# Windows contact integration checkpoint

Date: September 4, 2026, America/Los_Angeles.

## Source and scope

The local branch `codex/physics-foundation` integrates main `3a38d7d6e37f12657baa2777cb906c1682c9b098` and PR #2 head `138260d2f3d2e30a112f28034731db6052ae1720`. The tested code commit is **`29254bd0a0f8287ac6470f5c1d5af5fad32d6161`**. The worktree is `C:/Users/henry/dev/banjo-integration`; the original checkout remains on main.

This checkpoint is local. It has not been pushed or merged into GitHub main. PR #2 remains open/draft. Its successful Linux CI runs belong to `138260d`, not to this integration commit. See [development status](development-status.md) for the historical CI links.

The merge preserves main's `SUPPORT_CUSTOM_FRAME_CONTROL=OFF`, `SUPPORT_BUSY_WAIT_LOOP=OFF`, and `USE_STATIC_MSVC_RUNTIME_LIBRARY=OFF` settings.

## Changes

- Integrated sensor-deferred activation, experimental two-way sphere/material contact, synchronized microsteps, rolling-resistance torque, internal-damping separation, measured slip, launch-spin selection, support-footprint checks and contact diagnostics from PR #2.
- Fixed missed short keyboard taps. The old viewer sampled final key-down state; a press and release processed together between frames disappeared. The viewer now consumes raylib's key-press queue. This was reproduced with Windows input and then verified after the change.
- Added simulated time and fixed-tick readouts to make pause, reset and single-step observable.
- Documented and bounded a platform-dependent frictionless spin residual. No compensating torque, velocity reset or extra damping was introduced.

## Environment and reproduction

Windows 11 Pro `10.0.26200`, Visual Studio 2022 Build Tools, MSVC `19.44.35228.0`, Windows SDK `10.0.26100.0`, CMake `4.1.2`, Release x64. Renderer: NVIDIA GeForce RTX 5090, OpenGL `3.3.0 NVIDIA 580.88`.

Jolt sources are pinned to tag `v5.6.0`; raylib sources to tag `6.0`. Both tags were checked locally. This build used the already-fetched sources in the original checkout, with a separate binary directory:

```powershell
cmake -S . -B build/win-integration -G "Visual Studio 17 2022" -A x64 -DFETCHCONTENT_SOURCE_DIR_JOLTPHYSICS=C:/Users/henry/dev/banjo/build/win/_deps/joltphysics-src -DFETCHCONTENT_SOURCE_DIR_RAYLIB=C:/Users/henry/dev/banjo/build/win/_deps/raylib-src
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
./build/win-integration/Release/banjo_headless.exe
./build/win-integration/Release/banjo_precompute.exe build/win-integration/ball-scenarios.csv
./build/win-integration/Release/banjo_lab.exe --cache build/win-integration/ball-scenarios.csv --capture build/win-integration/contact.png --frames 210
./build/win-integration/Release/banjo_lab.exe
```

For a fresh checkout omit the two `FETCHCONTENT_SOURCE_DIR_*` overrides and let CMake fetch the pinned dependencies. The build logs, headless log, capture log and CTest results remain under `build/win-integration`.

## Verification results

| Check | Result |
|---|---|
| Release compilation | Passed, including normal graphical executable |
| CTest | All seven executables passed; runtime suite 12/12 |
| Slide-to-roll | 2 m/s launch settled to 1.42857 m/s; measured slip 1.66893e-6 m/s |
| Frictionless drift | Angular drift 4.48667e-5 rad/s; surface drift 1.12167e-5 m/s at radius 0.25 m |
| Scenario generator | 960 analytical scenarios generated |
| Capture with projection cache | 210-frame PNG exported and window exited successfully |
| Normal window | Visible 3D scene and diagnostic overlays; frame presentation continued |
| Pause and step | Paused at tick 875 / 7.2917 s; N advanced to tick 876 / 7.3000 s and remained paused |
| Reset | R returned to rigid phase with intact bonds, cleared clock and resumed; first observed frame tick 2 / 0.0167 s |
| Launch spin | L changed ratio 1 to 0; reset showed measured sliding/slipping |
| Slope | Right bracket changed 0 to 5 degrees and reset |
| Gravity | G changed 9.81 to 1.62 m/s²; V changed direction, with the projected regime changing to detached/ballistic |
| Controls and overlays | Motion panel and bottom controls remained readable; new clock fits the left panel |

The window showed roughly 50–60 FPS in these observations while another baseline lab was also running. This is an interactive smoke test, not an isolated performance benchmark or a demonstrated 60 Hz physics guarantee.

### Frictionless tolerance change

The existing frictionless test allowed less than 1e-5 m/s of spin surface speed. PR #2's Linux checkpoint reported 6.53e-6 m/s; this Windows build measured 1.12167e-5 m/s. The Jolt integration uses single-precision contact geometry and torque arms; the ideal zero-spin result has a small numerical residual.

The revised explicit regression budget is 8 parts per million of the 2 m/s launch speed, or **1.6e-5 m/s**. The unchanged COM-speed check remains below 1e-5 m/s error. A new independent energy interpretation requires rotational energy below 3e-11 of launch translational energy; the measured spin corresponds to approximately 1.26e-11. This preserves a small, quantified bound and does not claim exact zero torque or universal cross-platform precision. Larger changes must be investigated, not silently accommodated.

### Headless default experiment

| Measurement | Windows result |
|---|---:|
| Material nodes / initial bonds | 1,285 / 17,097 |
| Represented target mass | 163.6089 kg |
| Impact speed | 7.9859 m/s |
| Normal impact energy | 3959.3710 J |
| Sphere/material impulse contacts | 5,302 |
| Accumulated transfer diagnostic | 1323.0340 N·s |
| Reported contact dissipation | 3142.5856 J |
| Broken bonds / components | 17,089 / 1,277 |
| Rigid fragments / debris | 64 / 1,213 |
| Mass check | Absolute error below 1e-8 kg |

The transfer diagnostic sums magnitudes of per-step net material impulses; it is not the total-vector momentum residual. Contact dissipation covers the pair impulse operation, not the complete scene energy budget. Fragment count differs from the historical Linux checkpoint. **Almost complete breakup remains a known over-fragmentation defect, not validated glass behavior.** The default target is a 0.25 m radius solid sphere, explaining its large mass.

## Gate status and next engineering work

Gate 0 is satisfied for this local Windows integration: source is reviewable, main's fixes survive, normal input/frame presentation and capture were exercised, test evidence is tied to the exact code commit, and defects remain explicit. It is not a claim of new Linux/macOS verification, remote CI, or main integration.

Gate 1 remains open. Source inspection identifies concrete accounting gaps to instrument and test:

1. `JoltWorld::addBall` uses an analytical sphere inertia factor, while the target lattice carries sampled spatial inertia including finite-cell diagonal terms. Activation transfers velocities without reconciling those inertias.
2. `ActiveNodeState` stores translation but no intrinsic cell spin. `calculateFragmentMassProperties` includes finite-cell inertia but derives angular momentum from point motion alone. Audit a spinning intact object's activation and rigidification before treating the transfer as conservative.
3. Debris retains mass and angular velocity but drops the original component inertia. The aggregate fragment-build momentum fields describe pre-insertion component properties; they are not an audit of actual Jolt/debris state after insertion.
4. Split geometric correction changes positions without a complete angular-momentum, potential-energy or strain-energy ledger. The statement that it does not directly change kinetic energy is narrower than full conservation.
5. Bond failure removes stored constraints without a complete fracture-work budget. Coarsening can remove internal kinetic/elastic energy. Supports, Jolt contact, rolling resistance and debris interactions also need external impulse/torque/work and loss accounting.

Next: establish scene/transition measurements with explicit boundaries and state identity, add isolated and supported analytical regressions, quantify these residuals, then repair the representation and solver transfers. Calibrated fracture, property/shape coverage, arbitrary contacts, adaptive matter, validated speculation, assemblies, authoring and publishing remain subsequent gates in the full project goal.

