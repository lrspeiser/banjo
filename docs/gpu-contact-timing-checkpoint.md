# GPU normal-contact timing — October 9, 2026

## Implemented scope

The experimental coupled CUDA world now has an explicit contact-refinement choice, with the previous scheduling retained as Reference. The policy uses the same shared CPU/CUDA geometry, surface samples, normal stiffness and mass/inertia. It bounds the phase of excited sampled normal contacts and shortens a predicted free approach. It does not change contact/material laws, assign velocities, add damping, raise work limits or manufacture fracture. Fixed-body reactions and the existing energy/P/L gates remain authoritative.

The frozen-geometry normal stiffness/mass trace estimates frequency. A contact excitation cutoff of **0.0001 m/s** is explicit: tiny motions are not forced to resolve their contact clock. The same cutoff applies to predicted entry, using a local quadratic free-flight estimate. The estimate excludes material forces and is not a certified acceleration bound or CCD. It does not resolve all material-interface modes, prove trajectory convergence for an assembly, or guarantee every unexcited mode stays unexcited.

At microsecond steps, a velocity-only finite-difference perturbation can move contact positions by less than a floating-point ULP. The Newton tangent now uses the greater of the preceding 1e-12 scaled weighted-velocity perturbation and `2e-16 / dt`. With midpoint motion, that gives a 1e-16 sqrt(kg)·m weighted displacement floor. This is a numerical derivative scale, not a material calibration or tolerance relaxation. Equation, work/P/L and geometry admission tolerances are unchanged. Very large translated coordinates and other derivative scales remain unqualified.

The website exposes **Ball / ground · timing control**, the connected sheet, Reference and three contact-phase choices. [Open the matched 20 mm control](http://127.0.0.1:18893/coupled?test=contact), Run 0.1 s, then use Before, Inspect impact and Live. Impact inspection retains the actual accepted microstep with greatest recorded compression, its timestamp and poses; it is a read-only observation, not a reused simulation outcome. The ordinary accepted-time account remains separate from the displayed inspection timestamp. Logs retain all microstep poses, velocities, material histories, starting choices, contact scheduling estimates and work/reactions. A refused refined assembly reports the last estimate, pair, requested timestep and private elapsed time, then restores its prior accepted scene.

Base revision `802102f9bf9c8e0195162dc2689b1eff442b6aa4`; publication is the commit containing this note and is reported by `/api/checkpoint`. Coupled source SHA `012e17b9d2d577bd79fc8eb54f5a73c4ff7d2b5dd11daecc6f15345cd60f9988`. Windows / MSVC 19.44 / RTX 5090 / driver 610.88 / CUDA driver API 13.3 / CuPy 13.5.1 / NumPy 2.5.3. The CPU material-world executable is unchanged. Shared scheduling code is compiled by the real contact-test and GPU-oracle CMake targets.

## Independent normal collision oracle

For a 0.1 kg ball and fixed iron plane, the declared normal model is a linear compression spring with zero damping. Its stiffness is the same authored harmonic-modulus/length rule as before, not Hertz calibration. Radius comes from material density. With incoming speed `v`, frequency `omega = sqrt(k/m)` and gravity magnitude `g`, contact duration is `(pi + 2 atan(g/(v omega))) / omega`. During contact, signed gap is `g/omega² × (cos(omega t) - 1) - v/omega × sin(omega t)`; ballistic motion applies before and after. The tests calculate this oracle independently of the solver and policy.

The zero-gravity microstep test deliberately retains a coarse counterexample: at `dt × omega = 4`, energy closes but the ball is still compressed after the analytical collision has ended, with outgoing speed 0.18 instead of 0.3 m/s. Refining to 0.25 and 0.0625 rad reduces the position error and recovers the correct outgoing speed across glass, oak, iron and ice. This demonstrates why conservation alone does not qualify a trajectory.

The registered `banjo_gpu_contact_timing_tests` also runs all four real refined assembly attempts, distinguishes completion from a bounded refusal and verifies exact host/resident whole-interval restoration. A passing refusal regression is not physics admission. The suite covers twelve zero-gravity contact traces, **48 gravitational drop controls** (four ball materials, 1/20 mm surface clearance, host dt 1/240 and 1/960 s, Reference / 0.25 / 0.125 rad), **2040 compiled CPU/CUDA scheduling comparisons**, all accepted work/P/L gates and refined whole-interval rollback. Ball geometry is rigid in this fixture; no ball fracture, bulk plasticity, grain or thin-sheet realism is inferred. Material inputs, full per-material errors, traces, conditions and actual timing are in [contact evidence](evidence/gpu-contact-timing/timing.json).


### Measured timing and verification

| Ball material | Maximum position error, 1 mm / 20 mm | Maximum velocity error, 1 mm / 20 mm | 20 mm control wall seconds |
|---|---:|---:|---:|
| glass | 20.33 / 96.57 nm | 1.555 / 1.581 micrometers/s | 0.358 |
| oak | 43.74 / 202.87 nm | 3.353 / 3.320 micrometers/s | 0.326 |
| iron | 14.57 / 67.43 nm | 1.113 / 1.104 micrometers/s | 0.367 |
| ice | 50.38 / 233.58 nm | 3.865 / 3.822 micrometers/s | 0.343 |

These maxima are over host-output times, not every internal microstep; the separate zero-gravity traces cover the compression/release clock. The 0.125 rad choice improves each matched error by more than a factor of two. Per-step work/P/L is checked for every internal step. Maximum residuals over all 48 runs: P 3.117e-11 N·s, L zero in these centered fixtures, global energy 3.536e-11 J. These idealized model results do not establish material realism.

The 20 mm controls simulate 0.1 physical seconds. Wall time includes the CPU-oracle scheduling comparison, GPU steps and host evidence work; Calculation time for each actual run is retained in its performance account. Even this two-body control is not realtime. No large-world throughput guarantee is inferred from these single verification measurements.

Final source: 13/13 distinct scoped CTests pass in `build/voxel-contact-audit` (391.71 s): coupled contact, rotation strain, voxel face spring, compliant step, GPU laws, GPU frames, GPU coupled world, GPU coupled pipeline, GPU coupled convergence, GPU contact timing, voxel gateway, voxel pipeline and voxel playback. The timing suite is additionally expanded with actual four-material assembly refusal/rollback checks and passes its final repeat in 79.62 s. This is not the whole historical repository suite. Source registration is 345/345. Compiled CPU/CUDA trials and [exact current parallel/reference histories](evidence/gpu-contact-timing/parity.json) retain their checks; [world controls](evidence/gpu-contact-timing/controls.json) and [reference-scheduled refinement measurements](evidence/gpu-contact-timing/refinement.json) remain explicit, unqualified assembly evidence.

CUDA memcheck reports zero errors and racecheck zero errors/warnings for full/localized Jacobian evaluation and the new contact planner across the four materials. [Sanitizer provenance](evidence/gpu-contact-timing/sanitizers.json) records the exact smoke script and source. Reproduce the timing suite with `ctest --test-dir build/voxel-contact-audit -C Release -R banjo_gpu_contact_timing_tests --output-on-failure`.

[Normal browser and journal verification](evidence/gpu-contact-timing/browser.json) completes the matched iron-ball control and checks Before/Live/Impact. Its 43 accepted microsteps identify the actual 4.301 micrometer compression frame at 0.0638665 s. Contact shadows aid depth perception without changing geometry or physical motion. Published revision/hash verification is repeated after restart.

## Connected assemblies and remaining limits

[Same-condition refined sheet attempts](evidence/gpu-contact-timing/assemblies.json) retain glass/oak/iron/ice, a 0.1 kg iron ball, 5 mm clearance, host dt 1/960 s and a 0.25 rad contact limit. **All four stop at the unchanged 129th-trial refusal and restore the whole interval.** Their last accepted times are 0.0114583 / 0.03125 / 0.03125 / 0.03125 s. The last limiting frequencies are about 1.058 / 0.828 / 0.732 / 0.443 million rad/s. These failures are not fracture outcomes or successful simulation admission. Reference scheduling remains the sheet default; the refined choice is explicitly experimental.

The isolated clock improvement does not close the previously observed assembly timestep differences or nonlinear root-selection uncertainty. No full-world realtime, GPU material fracture/dent, calibrated physical realism or cross-GPU/phone validation is claimed. See the [ranked Newton evidence](gpu-ranked-newton-checkpoint.md) and retained [coupled model assumptions](gpu-coupled-checkpoint.md).

Next: reduce dense tangent/gather and host synchronization with resident local solves, then qualify coupled material modes, temporal error, fracture/plastic unloading and spatial refinement. Raising the work budget alone is not the solution. Adaptive cells, friction/CCD, grain, bulk plasticity/tearing, thermal/fire/phase change, fluids/water-wheel/power and editable gameplay remain open toward the complete near-realtime material objective.
