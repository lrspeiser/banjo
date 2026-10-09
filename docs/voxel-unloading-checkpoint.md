# Native unloading and retained metal deformation

October 8, 2026. Implemented experimental external-force integration; all five platform goals remain open.

## What the user can test

In the [3D lab](http://127.0.0.1:18912/), select Iron, **Yielding · experimental**, **Coupled friction · experimental**, 5 kg and 1 m. Drop the ball. **Lift ball** applies a real upward force to the ball for another 0.6 physical seconds. **Release lift** stops that applied force and advances another 0.6 seconds; it does not stop the ball's motion. Use **Whole rig** to see the lifted ball, **Before/Live** to compare actual cell poses, and **Physics & record** to inspect external work and retained yielding history. The complete experiment is bounded to four physical seconds. Calculation remains slow. **Center change** reports the volume-weighted vertical change of original cells in the central quarter of the sheet plan area, in millimetres; missing tracked cells report unavailable, and this reading alone does not prove a settled dent.

This extends the [connector plasticity checkpoint](connector-plasticity-checkpoint.md). It supplies a controlled unloading experiment that was previously missing. It does not certify static settling, continuum plasticity, calibrated dents or ductile tearing.

## Implementation and units

[`VoxelImpactWorld::setObjectAcceleration`](../src/platform/VoxelImpactWorld.hpp) accepts a finite acceleration vector in m/s² for either dynamic object in this bounded laboratory (sheet 1 or ball 2). Magnitude is limited to 30 m/s² and a scene admits at most 32 commands. Centered pose/interface integration and actual dynamic cells are required. Invalid input is refused before mutation. The gateway retains its playable accepted state after an invalid actuator command.

Every constituent cell receives native force F = material-derived mass times declared acceleration at its center of mass. Forces are queued inside the reversible candidate trial, so native refusal restores the force accumulator and activation state. Accepted candidates alone promote work and impulse totals. No pose, velocity, replacement fragment trajectory or material removal is assigned.

For each accepted trajectory, external work is F dotted with center-of-mass travel (J); scheduled impulse is F times interval (N s); its world-origin angular impulse is start-of-interval position crossed with impulse (N m s). Actual native force-phase momentum changes are measured separately from that scheduled input. Float rounding and other force-phase discrepancies remain in a signed residual. The local and cumulative energy gates subtract only this declared external work; their existing tolerances are unchanged. Full linear/angular accounts subtract the scheduled external input. Accounting an input is not proof of full coupled conservation.

Snapshots and the persistent journal record commands, timestamps, work, impulse, angular impulse and force-phase residual. Release sets acceleration to zero; it supplies no additional work or impulse. Ordinary default scenes omit the new fields and retain their prior behavior. The browser enables Lift only for a verified native hash advertising the capability and centered integration. Whole-rig framing uses actual accepted geometry, including the moving ball.

## Recording boundary repair

The ordinary browser exposed a real failure at 2.780 s during release: the 32 MB record bound was exhausted. The bound and physics were retained. On all 1,736 exact archived rows, gzip levels 1/3/6 produced 31.99/31.15/29.55 MB; streaming gzip and bitwise-float patch prototypes brought no useful reduction and were withdrawn. Independent bzip2 members at level 1 produced 24.41 MB from the same exact rows (about 24% less), with 4.06 s total compression versus 0.63 s for gzip. This is an explicit storage/CPU tradeoff, not a solver speedup.

New sessions persist each completed member as `.jsonl.bz2`; snapshots/downloads stream the original JSONL records, and older gzip archives remain readable. Uncompressed and compressed limits remain 256/32 MB. Exact signed-zero/type/list history, concatenated records, legacy reads and actual native stream parity are tested. Very large experiments can still exhaust the bounded journal; no unlimited recording claim is made.

## Analytical and comparative evidence

Native free-flight controls use glass, oak and iron sheets/balls, zero gravity, 1 kg ball, acceleration (2,10,0) m/s² for 0.1 s, followed by 0.1 s coasting. Expected ball work is 0.52 J and impulse (0.2,1,0) N s. Measured energy residuals are 3.39e-6 / 1.80e-6 / 1.23e-5 J. New oracle bounds are 64 float epsilons for velocity/position, 1e-5 J for work and 1e-4 J for full energy; these bounds accommodate native float accumulation and do not relax an existing physical gate. Unsupported modes, malformed/oversized inputs, command budget, unchanged poses on admission and force-free release are checked.

Matched supported sheets: 0.4 m square, 4 mm thick, 8 by 8 cells, 32 ball cells and 11 anchored cells; 5 kg iron ball from 1 m; centered face law, coupled friction, 96 velocity iterations, nominal dt 1/960 s. Load to 0.6 s, accelerate upward at 20 m/s² for 0.4 s, then release for 0.1 s. All four scenes retain dynamic mass and physically separate ball and sheet. Glass/oak/iron density is 2500/700/7870 kg/m³; modulus is 70/12/211 GPa. Oak remains an elastic comparison: grain/plasticity is unsupported, rather than replaced by a brittle display-name preset.

| Sheet response | External work (J) | Unclosed energy (J) | Maximum sheet vertical displacement at 1.1 s (m) |
|---|---:|---:|---:|
| Glass, existing brittle | 138.551541 | -45.748188 | 0.904615 |
| Oak, elastic | 183.147550 | -14.091535 | 0.004152 |
| Iron, elastic | 160.233103 | -20.061051 | 0.017500 |
| Iron, experimental plastic | 73.662704 | -13.024898 | 0.007760 |

Iron plastic history retains 24 yielded connections, 31.576116 J physical yield work and 1.443777 J numerical return excess. Central cell mean remains about 5.65 mm below its original level at 1.1 s. Maximum displacement alone would confuse elastic vibration with a permanent dent; the test also checks retained native plastic rest and downward central geometry after physical separation.

A supplemental matched iron probe continues to 2 s using 9.81 m/s² upward acceleration after lifting (explicit gravity compensation, not velocity holding). Elastic center mean returns within 0.011 mm of its initial height; plastic center mean remains 5.769 mm below it. Peak sheet speeds are still 0.0435 / 0.0909 m/s, so neither is claimed statically settled. Unclosed energies remain -20.767366 / -13.012834 J. Runtime was 63.73 / 65.77 wall seconds under overlapping verification; these are not isolated speed benchmarks.

The 1.1 s full linear-momentum residual norms remain about 2.07e-4 / 5.28e-4 / 4.92e-4 / 1.14e-3 N s for glass/oak/iron elastic/iron plastic. Their corresponding angular residual norms are about 9.63e-3 / 5.89e-5 / 1.36e-4 / 2.17e-5 N m s. Full world-origin angular residuals remain available in `step_work.full_angular_residual_n_m_s`; the new external angular input is explicit. Significant energy deficits and whole-impact refinement are still unqualified.

## Verification scope and reproducibility

Windows, MSVC Release, precise CPU floating-point policy, SDK 10.0.26100; separate output `build/voxel-unload/Release`. Native SHA-256: `8b776001a625b99904149003e9509adcebe6aea8eba23a7c4e3ec21aecda811d`. Source and tests are published to GitHub main as `bbb00f2ccada0179dd48d53eef9115089f6dcd9f`. The following metadata commit records this tested native/source pair and refreshes the live lab.

- Nine scoped CTests pass in 9.30 s: connector plasticity, native face springs, state recorder, rigid work, reversible trials, friction block, gateway, pipeline and playback.
- Registered `banjo_voxel_actuation_tests` exercises the three analytical controls and four matched unloaded scenes against the real native executable. It is also runnable directly with an output artifact.
- Four complete default two-second glass/oak/iron/ice physical/work comparisons match the previous plastic executable exactly at each 16-tick output; only wall profiler fields are excluded. Measured glass times are 35.46 versus 35.31 s: no speed improvement is claimed.
- Source registration is 336/336 with no exclusions. Changed runtime targets compile; this is not a claim that every registered source was rebuilt in this scope.
- Ordinary browser Drop → Lift → Release reaches 2.0/2.6/3.2 s. Before/Live, whole-rig framing, landscape 844 by 390 control access and console checks pass. The downloaded 2,060-row journal retains all 3,072 native ticks and both actuator commands, and its final state equals the displayed native state exactly. Compressed storage is 29.03 MB; expanded streamed JSONL is 165.91 MB. Final unclosed energy remains -16.435286 J. The new center measurement is also checked against all four real unloaded snapshots and ordinary browser Step; physical phone and other platforms are not claimed.

Local evidence: `build/voxel-unload-publish-ctest.log`, `build/voxel-unload-results.json`, `build/voxel-unload-final-results.json`, `build/voxel-unload-default-parity.log`, `build/voxel-unload-settle-results.json`, `build/voxel-unload-browser-result.json`, `build/voxel-unload-browser-record-proof.json`, `build/voxel-unload-before.png`, `build/voxel-unload-after.png`. These local artifacts are excluded from commits.

```text
cmake --build build/voxel-contact-audit --config Release --target banjo_voxel_world_run --parallel 4
python tests/voxel_actuation_test.py build/voxel-unload/Release/banjo_voxel_world_run.exe --results build/voxel-unload-final-results.json
python tests/voxel_execution_test.py build/voxel-unload/Release/banjo_voxel_world_run.exe build/voxel-plastic-face/Release/banjo_voxel_world_run.exe --strict-inline-baseline --alternate-request-order
python scripts/check-source-registration.py
node --check client/voxel-lab/world.js
```

## Remaining requirements

1. Resolve glass-ball and general contact/island energy losses; qualify full energy, momentum, angular momentum and timestep/spatial refinement.
2. Reduce native update/global adaptive substep cost materially, preserving the declared material law and accuracy.
3. Integrate yielding into the coupled iteration, qualify combined loads and unloaded settling, support material-history save/resume, and implement measured ductile tearing.
4. Implement adaptive spatial cells with conserved geometry, mass, momentum, elastic/plastic history and refinement/coarsening validation.
5. Admit validated unit-bearing custom material/geometry declarations, versioned laws and bounded user/LLM authoring.

This checkpoint advances the third requirement and explicit input accounting. It closes none of the five full goals.
