# GPU Newton probe scheduling — October 9, 2026

## Implemented scope

The coupled CuPy CUDA laboratory now tries the full Newton step first, then evaluates the seven smaller step-size candidates together if necessary. It still chooses the first valid reducing candidate in the original order. Physical inputs, material history, force/torque equations, finite-difference scale, nonlinear tolerance, contact timing and whole-interval admission gates are unchanged. The old one-at-a-time line search remains selectable. Evaluating a candidate never commits it: unused later probes do not alter the accepted world.

The candidate norms use the same vector reduction as the reference. One bounded host read returns fault codes and norms for a group; actual poses, forces and material histories stay on CUDA. Failure logs retain only the last considered candidate, its one fault code and the same considered probe prefix as the reference. This is scheduling within a private Newton iteration, not cached fracture results or prediction substituted for physical motion.

The [3D coupled lab](http://127.0.0.1:18893/coupled) exposes **Step-size probes → Full step, then GPU batch / One at a time · reference**. Set up, Physics step, Run 0.1 s, Before, Inspect impact and Live use actual accepted states. The [isolated timing control](http://127.0.0.1:18893/coupled?test=contact) remains available. Browser rendering runs separately from CUDA calculation; simulation is not decelerated or fabricated to match its display.

Base revision `c4113374515d9598add8d37f63116cce44a8ba6d`; publication is the commit containing this note, reported by `/api/checkpoint`. Coupled source SHA `18716413cf18147bd79f4730fcce32c493e2ff0b9c296da4ba4a91775c809c0c`. Windows / MSVC 19.44 / RTX 5090 / driver 610.88 / CUDA driver API 13.3 / CuPy 13.5.1 / NumPy 2.5.3. CPU material-world executable and shared constitutive headers are unchanged.

## Measurements that selected this change

[Instrumented reference observations](evidence/gpu-line-search/profile.json) record actual low-energy worlds on the preceding source. Ten glass host ticks launch 2223 evaluations and wait on 4388 GPU scalar observations; iron launches 4794 and waits on 9498. Dense linear solving occupies about 8–10% of measured wall time. CUDA event intervals and host waits overlap and must not be added. Instrumentation adds overhead; it is separate from the paired wall-time comparisons.

An [all-eight-at-once trial](evidence/gpu-line-search/all-eight-trial.json) retained exact physical histories but cost slightly more in both stronger oak runs. It is not the installed policy. The chosen implementation preserves the common full-step fast path and batches the remaining candidates only after that step fails. The trial record is historical evidence, not an automatically reused outcome.

## Comparative verification and performance

[Registered paired tests](../tests/gpu_coupled_line_search_test.py) retain glass, oak, iron and ice. Low-energy experiments use nine connected 10 mm cells on two fixed iron posts, a 0.01 kg iron ball, 1 mm clearance, host dt 1/240 s and ten host ticks (0.0416667 physical seconds). Each material has three complete paired runs; execution order alternates every tick. Warm private solves compile/allocate before measurement without changing physical inputs. Wall time includes stepping, snapshots and audit records, excludes setup, and includes remaining host work. No simultaneous GPU verification jobs run during these comparisons. Timing varies with system load and clocks; these are fixture measurements, not a throughput guarantee.

| Sheet material | Reference median wall s | GPU-batch median wall s | Wall-time reduction |
|---|---:|---:|---:|
| glass | 2.675 | 2.043 | 23.6% |
| oak | 1.291 | 0.958 | 25.8% |
| iron | 5.616 | 4.919 | 12.4% |
| ice | 0.589 | 0.491 | 16.7% |

Every accepted microstep's poses, velocities, material history, reactions, work account and Newton starting choices are exactly equal to one-at-a-time evaluation. Final resident body/interface arrays are compared byte for byte. Timing, private evaluation counters and the declared scheduling choice are intentionally different metadata.

Eight stronger comparisons retain a 0.1 kg iron ball, 5 mm clearance, dt 1/960 and 1/1920 s, and 0.104167 physical seconds. All full accepted histories match exactly. All eight retain zero separated sites and zero yielded faces; these are not fracture/plasticity demonstrations. Their wall reductions range from 0.2 to 15.5%; this is not a uniform throughput promise. Maximum per-step residuals across these eight comparisons: P 1.023e-11 N·s, L 5.403e-14 N·m·s, energy 2.003e-13 J. Every microstep retains the existing 1e-9 P/L limits and its existing scale-dependent energy tolerance. No tolerance change.

Four 0.1 kg, 20 mm ball/ground comparisons with 0.25 rad contact refinement also retain exact accepted histories. The registered suite replays the actual prior glass single-start refusal: inputs, ordered considered probes, actual last candidate and Jacobian are equal; GPU inputs remain unchanged. A forced failure after one private accepted substep restores the whole requested interval and resident arrays. Passing rollback tests does not qualify the rejected physical experiment.

Fourteen scoped CTests pass in `build/voxel-contact-audit` (564.67 s): coupled contact, rotation strain, voxel face spring, compliant step, GPU laws, GPU frames, GPU coupled world, GPU coupled pipeline, GPU coupled convergence, GPU probe scheduling, GPU contact timing, voxel gateway, voxel pipeline and voxel playback. The new suite is registered by CMake and actually run by CTest (199.15 s), not an uncalled script. This is not the entire historical repository suite. The real shared contact/oracle targets compile; source registration is 345/345 with zero exclusions. The retained contact suite checks analytical clocks and actual refined-assembly refusal/rollback; failure coverage is distinct from admission. [CUDA sanitizer checks](evidence/gpu-line-search/sanitizers.json) report zero memcheck errors and zero racecheck errors/warnings. They execute full/localized contributions, contact scheduling and the actual recorded full-step/tail-probe refusal. [Check transcript](evidence/gpu-line-search/checks.json) retains the scoped CTest and source-registration evidence. [Normal browser and journal verification](evidence/gpu-line-search/browser.json) runs the same sheet through both selectable modes. Its eleven journal states (setup plus ten ticks) match exactly; 34 microsteps reach 0.0416667 s with -2.044e-15 J global energy residual. Before/Live and the actual peak-impact view are checked; peak sampled compression is 0.389 micrometers at 0.0145833 s. The source is unpublished/dirty during that prepublication UI check, and the page reports this. Publication hashes and restart status are checked again after main is pushed. No phone/cross-GPU validation is inferred.

## Remaining boundaries and next work

This optimization improves GPU orchestration while preserving the current numerical trajectory. It does not fix the known connected-sheet temporal errors or nonlinear-root uncertainty. All four contact-refined sheet attempts still exceed their bounded trial work and restore the scene. The isolated contact clock is analytically checked; connected-material accuracy and full-world near realtime remain OPEN.

These are bounded isotropic rigid cells, cohesive interfaces / six-mode plastic connectors and frictionless normal compliance. Oak has no grain model; iron is not continuum J2 plasticity or tearing. No general GPU fracture/dent realism, thermodynamics, fire, phase change, water/wheel/power, adaptive spatial cells, cross-GPU determinism or phone verification is claimed.

Next: keep nonlinear norms, line-search decisions and local tangent work resident to remove the remaining CPU waits; reduce dense whole-scene work with verified local/sparse structure; qualify material-mode temporal error and fracture/plastic unloading; then extend the same authoritative state/work pipeline to adaptive cells and the remaining physical laws. Raising budgets or relaxing admission tolerances is not this optimization.

For library roles and why Jolt is not an automatic CuPy converter, see the [GPU migration assessment](gpu-migration-plan.md). CuPy is the numerical runtime; shared material kernels are Banjo's audited physics. Newton/Warp and PhysX have separately measured contact experiments and explicit limitations.
