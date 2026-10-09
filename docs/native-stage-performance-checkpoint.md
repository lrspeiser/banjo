# Native execution stages and exact snapshot storage

October 8, 2026. Implementation and measured overhead reduction; full physics goals remain open.

## Scope and reproducibility

Source checkpoint: `8de0f3b609c158f4c537657aa677e42c74be5a06`. Windows x64, MSVC Release, precise floating-point profile, CPU inline runner. Native executable: `build/voxel-compact-record/Release/banjo_voxel_world_run.exe`, SHA-256 `33abca5ee37001f1562ea33f51f8f1711d2c02046152401caefb9f47343cd618`. Separate CMake tree: `build/voxel-contact-audit`; source registration 334/334, no exclusions. This is scoped verification, not the entire regression suite or physical-phone validation.

Profiling baseline executable: `build/voxel-execution-profile/Release/banjo_voxel_world_run.exe`. Earlier published physics baseline: `build/voxel-friction-fastpath/Release/banjo_voxel_world_run.exe`, SHA-256 `43131a17e44f92d07bbe2397d020875f086d77a353ff7b10d56af25bf1a571ae`. Four complete baseline comparisons retain every physical and work field exactly at every 16 host ticks through two physical seconds. Only wall-clock profiling fields are excluded.

## Where the reference calculation spends time

All four fixtures use a 1 kg iron ball, 10 m height, 4 mm sheet, 8 by 8 sheet cells, 32 cm support gap, 1/960 s host step and 96 velocity iterations. Material-dependent mass/stiffness remain catalog-derived. Native update includes Jolt jobs and enabled callbacks; it does not isolate collision detection from constraint solution.

| Sheet | Complete request wall s | Accepted substeps | Jolt update s | Trial capture s | Rejected trials | Signed unclosed energy J |
|---|---:|---:|---:|---:|---:|---:|
| glass | 38.238 | 41823 | 28.021 | 4.241 | 5 | -92.923298 |
| oak | 7.637 | 6410 | 5.407 | 0.866 | 828 | -44.166886 |
| iron | 6.436 | 5224 | 4.546 | 0.708 | 898 | -82.828571 |
| ice | 40.118 | 73631 | 26.603 | 5.314 | 0 | -103.151846 |

Glass uses 41,823 accepted substeps and just five rejected trials. Jolt update is about 73% of its 38.238 s request wall time. Rejection/restoration is not its dominant cost. Local solve/substep work remains the necessary large optimization. Inclusive `trial_ms` contains capture, step, candidate observations and restore; never add it to those constituent stages. The four step stages are disjoint and contained by `native_step_ms`. Timings include attempted work, including rejected trials, and never feed physical decisions.

## Implemented transport change

[`BoundedStateRecorder.hpp`](../src/rigid/BoundedStateRecorder.hpp) transports the exact bytes Jolt writes into reusable bounded storage. Each native trial depth has its own recorder; parents survive both accepted and rejected children. Full native state, contacts, warm-start impulses and constraint history are still captured. Contact auditing parses a view of another reusable recorder rather than copying a fresh string. Each recorder accepts at most 16 MiB of native state, the existing maximum trial depth remains 16, and unsupported or overflowing reads/writes fail. The maximum retained logical backing sizes sum to 272 MiB across 16 trial recorders plus the contact recorder; standard-vector capacity/allocator overhead is additional. Allocation is lazy and actual fixture records are much smaller. This is not a whole-process memory ceiling. It is transport reuse, not cached outcomes. The spring-specific recorder path remains unchanged.

No contact/elastic/fracture law, impulse cap, iteration count, timestep rule or energy tolerance changes. No mass or velocity corrections, omitted contacts, fake fragments or result reuse.

## Verification

- Seven focused CTests pass in 8.59 s, including the registered byte transport test, native glass/oak/iron controls, work audit and gateway/pipeline/playback checks.
- Two additional rebuilt rollback/rolling tests pass in 4.04 s. Profiling enabled/disabled comparisons preserve exact glass/oak/iron motion and kinetic energy in both inline and thread-pool runners. Rejection, exceptions, child acceptance followed by parent refusal, and all 16 nested depths restore the native state.
- Four complete compact-recorder material comparisons preserve all physical/work fields, cells, mass, events, clocks and accepted/rejected counts at each output. Their provisional paired timing overlaps a short browser smoke check and additional compilation; use the balanced repeat below for the headline glass performance.
- A fresh alternating-order glass/iron comparison completes with exact parity: 35.573157 s new / 39.556575 s profiling baseline, a 10.07% measured reduction. Capture costs 1.440434 s and contact observation 0.532943 s in the new build. This is one repeated fixture on this Windows machine, not a statistical or cross-platform speed guarantee.
- Follow-up: all five full coupled-friction comparisons finished with exact physical/work parity: glass/iron, oak/iron, iron/iron, ice/iron, glass/glass. Request wall times were 154.26/169.84, 65.98/73.83, 112.58/117.70, 108.38/118.62 and 166.35/176.34 s (compact/profile baseline). Timings overlapped other verification and are not isolated benchmarks. All accuracy/constitutive gates stay open. See `build/voxel-compact-record-coupled.log`.
- The preview ordinary Step action displays 16 attempted / 16 accepted steps with finite stage timers. Coupled glass-ball controls, Run/Pause and absence of console errors are checked; desktop and 844 by 390 landscape drawer/readout checks pass. The scrollable landscape setup brings Step/Before/Live into view and advances to 0.033 s with 32/32 counters, no horizontal overflow and no console errors. Physical-phone acceptance is not claimed.

## Remaining work

All five requested goals remain open. Glass-ball energy failure is absent only in the existing coupled fixture; major losses, normal/island disagreement, fracture overshoot and physical refinement remain unqualified. This storage change preserves those results and adds no constitutive law. Realtime speed needs fewer globally refined updates and cheaper local active solves with accounted boundary transfers. Persistent metal plasticity/tearing, conservative adaptive spatial cells, and validated general material/geometry authoring still need integration into the same live 3D pipeline.

## Commands and local evidence

```text
cmake -S . -B build/voxel-contact-audit -DCMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE=C:/Users/henry/Documents/ChatGPT/Banjo/build/voxel-compact-record/Release
cmake --build build/voxel-contact-audit --config Release --target banjo_voxel_world_run banjo_voxel_face_spring_tests banjo_state_recorder_tests banjo_rigid_step_work_tests banjo_contact_friction_block_tests banjo_reversible_trial_tests banjo_rolling_resistance_tests --parallel 4
ctest --test-dir build/voxel-contact-audit -C Release --output-on-failure -R "banjo_(state_recorder|contact_friction_block|rigid_step_work|voxel_face_spring|reversible_trial|rolling_resistance|voxel_gateway|voxel_pipeline|voxel_playback)_tests"
python tests/voxel_execution_test.py build/voxel-compact-record/Release/banjo_voxel_world_run.exe build/voxel-execution-profile/Release/banjo_voxel_world_run.exe --strict-inline-baseline
python tests/voxel_execution_test.py build/voxel-compact-record/Release/banjo_voxel_world_run.exe build/voxel-execution-profile/Release/banjo_voxel_world_run.exe --strict-inline-baseline --case glass-iron --alternate-request-order
python scripts/check-source-registration.py
node --check client/voxel-lab/world.js
```

Local non-committed evidence: `build/voxel-execution-profile-comparison.log`, `build/voxel-execution-profile-measurements.json`, `build/voxel-compact-record-comparison.log`, `build/voxel-compact-record-measurements.json`, `build/voxel-compact-record-glass-balanced.log`, `build/voxel-compact-record-ctest.log`, `build/voxel-compact-record-rollback-tests.log`. The earlier timer fixture initially refused its unintended continuous-collision contact; setting the test body to the supported discrete audit mode resolves that failure, and all seven affected tests pass. The refused audit itself is retained.
