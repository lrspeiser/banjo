# Runtime cohesive motion: position precision gate

Local source `f5d2226a0fc045c04dd4713dc8fc4cfd4a150a17`, September 5, 2026; not pushed or merged. The full platform goal remains active.

The new `banjo_runtime_cohesive_probe` connects the cohesive interface force to live Jolt drift using the audited pair-impulse API. It is an isolated experiment, not an application stepping API: two 0.02 m cubes, an axial connector of area 0.0001 m2, 0.001 m nominal reference gap, no gravity, external bodies or surface contact. Both bodies retain material-derived mass/inertia. The connector supplies velocity-Verlet half-kicks around each Jolt step; its opening and irreversible history come from actual runtime positions. Whole-pair External ownership suppresses Jolt contact between these bodies. This does not implement contact outside a small patch.

The law uses catalog tensile strength S and fracture work Gc with K=2*S*S/Gc. These are uncalibrated cohesive examples, not real glass/wood/iron joint certifications. Elastic runs begin at 0.4 times the damage-onset opening and zero velocity, ending after one eighth of an elastic period (omega*t=pi/4). The oracle is q=q0*cos(omega*t). Separation runs begin with approximately 6*A*Gc of relative kinetic energy, zero total momentum, and run for 8*failure-opening/initial-relative-speed. The independent final-speed oracle is sqrt(2*(initial measured KE-A*Gc)/reduced mass). No arbitrary fracture launch impulse is added.

Both fixtures run at world offsets 0 and 10 m, with 128/256/512/1024 steps, for glass, oak and iron: 48 experiments per configuration. Timestep is rounded once to the value Jolt actually accepts. Inserted separation defines the initial reference while retaining the chosen initial strain, isolating subsequent motion quantization from initial placement error. Each report contains measured maximum whole-trajectory energy error, signed and accumulated-absolute transfer error, error after subtracting transfer contributions, total momentum error, damage work, separation and oracle error. No cancellation-based transfer bound is claimed.

## Verified failure in the current application configuration

Current `build/win-integration` uses `DOUBLE_PRECISION=OFF`: world positions have 32 bits. Its existing 23 CTest suites pass in 18.88 s, but the new explicit accuracy command exits 2 and fails 11 of 12 finest-resolution material/location/mode checks. This new behavior is unsupported in that configuration; existing green tests are not proof of coupled-joint accuracy.

At 10 m, the finest elastic runs have approximately 61.7% maximum energy error relative to initial energy and 0.292893 normalized opening error for all three substances. Glass and oak high-energy runs fail to separate at all because incremental motion cannot be represented at that position scale. Those two runs show zero energy error while moving incorrectly, demonstrating why energy balance alone cannot validate dynamics. Iron separates but has approximately 0.713% energy error and 0.003893 normalized speed error. Glass also has major errors near the origin because its cohesive length scale is small.

## Separate double-position build

`build/win-joint-double` is configured with `DOUBLE_PRECISION=ON` and `BANJO_BUILD_LAB=OFF`, using the same vendored sources and dynamic MSVC runtime. It changes position precision only; Jolt velocities and many other quantities remain float. All 24 suites pass in 20.50 s, including the new accuracy suite (1.80 s). All 12 finest checks pass. The current application configuration and saved worlds have not been switched.

Finest measurements at world offset 10 m:

| Material | Elastic normalized opening error | High-energy separation | Max high-energy error J | Normalized final-speed error |
|---|---:|---|---:|---:|
| Glass | 2.19636e-7 | Yes | 4.37899e-8 | 4.33504e-6 |
| Oak | 1.24382e-7 | Yes | 7.36504e-6 | 5.98202e-6 |
| Iron | 8.14819e-8 | Yes | 6.00703e-4 | 5.03966e-6 |

The finest gate requires elastic opening error <1e-6 and energy error <1e-5 of initial energy, with no damage; separation must spend A*Gc (relative tolerance 1e-12), have maximum energy error <1e-4*A*Gc and normalized final-speed error <1e-5. These are bounded fixture criteria. Separation maximum energy error decreases with refinement in this sweep, but endpoint-speed errors and the finest elastic errors are not monotonic; float velocity accumulation and event integration remain limits. No general convergence order, spatial convergence or arbitrarily distant-world support is established.

## Reproduction and next work

Run either build's `banjo_runtime_cohesive_probe OUTPUT.csv --require-accuracy`. Without the final option it exports diagnostics while reporting unmet checks; with it, unmet accuracy returns 2. CTest registers the accuracy gate only for double-position builds. Preserve the explicit failing single-position report as evidence, not as an expected-pass physics test.

Windows 11 / MSVC 19.44 x64 Release / CMake 4.1.2 / Jolt 5.6 / Core Ultra 9 285K / RTX 5090. Separate double build is headless; no new native UI verification. Existing starter/workshop processes were not changed in this checkpoint. Default frame-control/busy-wait fixes remain intact.

Next: promote an explicit position-precision contract into runtime identity, authoring capability checks and save/cache compatibility before enabling live joints. Then couple finite-area joint forces, all uncovered surface contact, external work/reactions and failure with trajectory error control. The experiment has no rollback for a partially advanced Jolt step and is not a production transaction. Realistic branch cutting, fabrication work sources, calibration, default fracture-pipeline defects, all 40 scorecard rows and all remaining full-goal gates stay open.
