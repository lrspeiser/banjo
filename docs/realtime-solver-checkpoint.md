# Realtime pipeline: observable delivery and finite-rotation experiment

October 8, 2026. Windows x64, MSVC Release CPU. This checkpoint advances
measurement and an opt-in mathematical interface; it does **not** close the
realtime calculation or full energy gates. The default remains `native-motor`.

## Pipeline and next implementation order

The delivered path is declaration → native CPU world on a background worker →
latest accepted timestamped state → bounded two-pose 3D rendering. Native contact
and interface impulses drive motion; the renderer does not author fragments,
launch velocities or predicted fracture. Failed native trials retain the last
accepted state. Exact command batches and observed states persist in compressed
session journals. The live site exposes simulation speed separately from fps.

This update adds nearest-rank native batch p95 over at most 256 batches, maximum
batch latency, age of the published accepted pose, last browser control round
trip and journal size. Native batch cost includes calculation and IPC. Pose age
uses one server monotonic clock, including time spent paused. The browser adds
local elapsed time since receipt so the readout keeps aging when polling stops;
network transit is not included in this estimate. It does not subtract
client/server clocks. Browser control latency includes the HTTP round
trip, not only handler execution. Metrics are observations, not admission gates
or modifications to the selected material law. A slow batch can exceed the
8 ms soft target; Pause stops scheduling and drains that batch once.

1. **Keep responsive delivery and quantify its budget.** Test native/render
   independence, bounded memory, Pause/Reset, replay equality and actual 3D
   controls. Target ≥50 render fps and p95 control acknowledgement <100 ms.
   Keep calculation ratio and pose age visible when native stepping is slow.
2. **Build a coupled CPU reference for finite material-cell motion.** Carry
   orientation, material stress/strain, mass/inertia, and actual contact work in
   one accepted step. Measure signed P/L/E including support/gravity/fracture
   transfers and numerical loss. Resolve current glass-ball energy refusal.
   Changing a spring's coordinate system alone is not that complete solve.
3. **Schedule interacting regions locally.** Form contact/interface islands;
   predict conservative collision bounds, wake approaching bodies and exchange
   accounted impulses/work at shared time boundaries. Permit unloaded settled
   regions to take larger steps without making a distant fast fragment refine
   the entire world. Compare against the full coupled reference through impact.
4. **Refine detail where it matters.** Split/coarsen cells near contact, damage
   or thin geometry. Transfer mass, inertia, momentum, energy and constitutive
   history; invalidate incompatible topology. Compare glass/oak/iron/ice across
   timestep and spatial resolution. Metal plasticity must change persistent
   geometry and subsequent collision, rather than only its rendered appearance.
5. **Optimize the measured kernel.** Reuse sparse structures, parallelize
   independent islands, then evaluate GPU execution against the CPU reference.
   Initial representative-impact target: ≥0.8 physical seconds per wall second.
   Faster models may author or explain a design on demand; no LLM call belongs
   in the simulation or render tick. Validated declarations use this same path.

These are ordered acceptance tasks, not claims that local stepping, spatial
refinement, metal dents or GPU execution are delivered by this checkpoint.

## Opt-in rotation interface

`face_law: "log-gradient"` selects an experimental SO(3) interface. The shortest
relative orientation logarithm is its strain in radians. The world differential
maps angular velocity into strain rate; anisotropic elastic torque is the
gradient of `0.5 * sum(k_i * phi_i²)`. Jolt receives normalized angular rows with
the corresponding stiffness/damping scaling. Linear forces act at the same
anchor on both endpoints, with reaction torque. Actual generalized rotational
impulses are projected into physical material-frame torque for fracture stress.

The unique-log domain excludes the π branch (within 1e-7 rad); invalid frames
refuse explicitly. Generic Jolt constraint-settings serialization is unsupported
and explicitly refuses; immutable validated declarations recreate this
constraint. Native trial state recording restores its row axes, scales and
impulses. The default interfaces and existing material catalog are retained.

The live site's **Physics & record → Interface solver** selector rebuilds a
disposable experiment and records the choice. Experimental qualification remains
false in each native state. Glass-ball selection stays unavailable because the
full energy gate is unresolved. No calibrated glass/oak grain/metal plasticity
claim is made. Historical oak remains a comparison material, not a gameplay
organic-material enablement.

## Failed experiment retained

The separate `BANJO_JOLT_CONTINUOUS_SMALL_ROTATION=ON` probe did not qualify for
delivery. With the log-gradient law, glass/glass stopped at 1.638786 s and
glass/iron at 1.513265 s; oak, iron and ice completed two seconds with unresolved
energy deficits. More importantly, the default native-motor regression refused
the aluminum-ball/glass-sheet case at 1.496143 s. Its previous default passes
that case. Therefore this checkpoint runs the original **OFF** integration
profile; the ON build is not the website's verified binary. Failed probes are
evidence against promoting that change, not a test-suite success.

No energy/timestep/iteration tolerance is relaxed. Rotation-gradient oracles
establish a mathematical force property; they do not establish conservative
full-pipeline integration. Large unexplained energy deficits, full angular
momentum accounts, meaningful speed, calibrated fracture and plasticity remain
open. The five active objective stages remain incomplete.

## Verification and publication

The source-registration guard includes all new C++ sources in CMake targets.
Analytical tests cover zero, tiny and large finite rotations, anisotropic energy
gradients, equal/opposite reactions, objectivity, quaternion sign and refusal.
The native face-spring suite runs both laws under both execution runners,
including impulse reactions and state rollback. Pipeline tests verify p95
window bounds and an injected 300 ms batch delay with responsive Pause, alongside
glass/oak/iron/ice native-state/replay parity. Gateway tests reject malformed law
declarations and confirm the default remains native-motor.

Material experiment results, exact native hash, scoped test duration and browser
delivery evidence are recorded below. The seven named
scoped CTests are not a full repository regression or a real-phone acceptance
test. Existing full-impact runner parity remains prior evidence from
[the execution checkpoint](native-execution-checkpoint.md).

Publication uses ordinary fast-forward main checkpoints. The final website
manifest pins the physics source and verified executable hash; `/api/checkpoint`
also identifies the running website and required restart. Local session journals
are retained across server restart. Only the disposable 18893 lab is reset;
unrelated player-world servers are not changed.

### OFF-profile finite-rotation observations

All rows use a 40 × 40 cm, 4 mm, 8 × 8 sheet on two edge supports with 32 cm
gap, a 1 kg constituent-cell ball dropped 10 m, 1/960 s host ticks, 96 velocity
iterations and the unchanged adaptive swept/energy gates. Refinement remains
global. All original cell masses/IDs remain; neither fragments nor launch
velocities are authored. Oak/iron retain one elastic sheet piece; no permanent
dents or oak grain failure is implemented.

| Sheet / ball | Physical s | Wall s | Substeps | Sheet pieces | Unclosed energy J | Outcome |
|---|---:|---:|---:|---:|---:|---|
| Glass / iron | 2.000 | 42.735 | 40,176 | 12 | -81.620111 | Completed, unqualified energy |
| Oak / iron | 2.000 | 7.141 | 6,295 | 1 | -44.821228 | Completed, elastic only |
| Iron / iron | 2.000 | 6.007 | 5,150 | 1 | -83.843917 | Completed, elastic only |
| Ice / iron | 2.000 | 28.016 | 54,314 | 64 | -87.278270 | Completed, unqualified energy |
| Glass / glass | 1.427654 | 2.117 | 2,714 | 10 | -10.766880 | Energy refusal; accepted state retained |

At the refused glass/glass trial the candidate total rose from 94.249782 to
94.253450 J at minimum refinement. The log-gradient model therefore does not
resolve the glass-ball gate. Compared with the prior default's approximately
36 s glass run, it does not establish a useful speed gain either. Individual
timings are observations, not repeated benchmark estimates. The material density
differences still set native mass/inertia; stiffness differences set distinct
elastic responses. Full energy/angular momentum/calibration remain unsupported.

The delivered executable SHA256 is
`e9736ab634bc6e40ea2049221d4c6c674f3833fc5e7985d20badd2da12438c62`.
Build directory `build/voxel-contact-audit`, separate runtime output
`build/voxel-log-gradient-final/Release`,
`BANJO_JOLT_CONTINUOUS_SMALL_ROTATION=OFF`, `BANJO_BUILD_LAB=OFF`.
The manifest records the final source revision after publication. This is a
headless native executable displayed in the interactive browser 3D world; it
does not qualify the separate raylib window or other operating systems/GPUs.

Seven scoped CTests pass in 282.56 s: rotation strain, native face springs,
experimental log-gradient runs, retained default world, gateway, pipeline and
playback. The face suite has 38 native cases across both runners/laws; the pure
rotation tests have four gradient cases and two refusal checks. Worst measured
finite-difference gradient error is 5.22e-9; native large-angle torque residual
is 9.46e-7 N·m and equal/opposite reaction residual 5.27e-13 N·m·s. Existing
tolerances are unchanged; new tolerances are respectively 2e-8, 4e-5 N·m and
1e-10 N·m·s to bound finite differencing/native float rounding.

The retained default completes all eleven world experiments and preserves the
known glass-ball refusal with exact snapshot rollback. Two-second default wall
times: glass 36.010 s, oak 7.197 s, iron 6.120 s, ice 36.400 s. Its material
energy deficits match the previous checkpoint; this is a retained baseline,
not an accuracy repair. The injected 300 ms batch probe acknowledges Pause in
1.68 ms and drains exactly once. Source registration passes 329/329 with no
exclusions; Python compilation and JavaScript syntax checks pass.

Commands: configure with the OFF profile and isolated runtime directory above;
`cmake --build build/voxel-contact-audit --config Release --target
banjo_voxel_world_run banjo_voxel_face_spring_tests banjo_rotation_strain_tests
--parallel 4`; `ctest --test-dir build/voxel-contact-audit -C Release -R
"banjo_(rotation_strain|voxel_(face_spring|world|gateway|pipeline|playback|log_gradient))_tests"
--output-on-failure`; `python scripts/check-source-registration.py`.

The ordinary preview browser selects the experimental interface, accepts Step,
streams an actual impact and pauses at 1.442 s with 40 broken faces/12 pieces.
The measured Pause round trip is 9.9 ms and rendering is 60 fps in that scoped
observation. The 844 × 390 landscape layout, scrollable diagnostics and restored
desktop viewport are checked; no physical-phone qualification is implied.

Published-server browser verification completes the reference two-second drop
with 40 broken faces, 12 sheet pieces, all 107 cells and 41,823 accepted substeps.
The browser reports 60 fps and 0.05× realtime; p95 over the final 256 background
batches is 69.1 ms, largest batch 632.8 ms, and native-update wall time 30.38 s.
This is an individual pipeline observation, not a repeated latency benchmark.
Captured warnings/errors are empty. The final native hash matches the manifest.

A subsequent host/presentation repair makes accepted-pose age continue advancing
while paused, and manual Step replies include their new accepted-frame metrics
after the calculating flag clears. Three affected scoped CTests (gateway,
pipeline, playback) pass again in 5.72 s, including a regression that prevents
manual controls waiting for a nonexistent batch. Native laws/binary are unchanged
by that repair; physics source is `a2895042cfe29c1b886832028f5714b66931495b`.
