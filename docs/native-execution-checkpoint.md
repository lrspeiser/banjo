# Native execution comparison — October 8, 2026

## Scope

This checkpoint targets native scheduling/allocation overhead, not a material
law or timestep change. The CPU reference stays selectable in the executable
with `--serve-reference`. Ordinary `--serve` uses scene-sized contact storage
and Jolt’s inline zero-worker job runner. Other JoltWorld callers retain their
existing thread-pool default; requesting inline execution with workers refuses.

The default 107-cell scene allocates 2,048 body-pair / 1,024 contact-constraint
slots, versus the retained reference 32,768 / 16,384. Larger sheet resolutions
scale the bounded buffers by occupied-cell headroom. This is not an arbitrary
world capacity proof. Capacity faults continue to refuse and roll back the
native trial, rather than accepting missing contacts. Both execution paths use
96 velocity / 4 position iterations, the same constitutive inputs, 1/960 s host
ticks, swept-distance and energy gates, native mass/inertia, and contact owner.

## Comparative verification

The preliminary allocation-only comparison gave exact state parity at each
16-tick output through two physical seconds for glass, oak, iron and ice. Its
paired timings were 35.35 / 35.51 s (glass), 7.12 / 7.10 s (oak), 5.96 / 5.90 s
(iron), 36.57 / 36.64 s (ice), scene/reference respectively. This does **not**
establish a useful speedup. The inline scheduler is measured separately below.

The new CMake-registered `banjo_voxel_execution_tests` compares complete physical
state at every 16 host ticks through all four two-second impacts. Only wall-time
profiles are excluded. Constituent identity/mass, motions, topology, reaction,
energy and momentum observations are compared exactly, with no tolerance change.
The contact/spring suite now runs its twelve existing analytical/rollback cases
under both schedulers. Those material-neutral oracles do not certify a material
model. Glass/oak/iron/ice tests retain their separate physical characteristics;
oak/iron remain elastic with grain and plasticity unsupported.

## Remaining work

The substantial energy deficit and glass-ball refusal, useful realtime solver
speed, persistent metal yielding/dents/tearing, spatial adaptive cells and
validated custom declarations remain open. The next major speed task is a local
or coupled solid solve that avoids refining the whole scene for distant fast
fragments while retaining accounted contact/interface exchanges. This cannot be
claimed from scheduler parity or smaller storage.

## Inline comparison results

| Material | Inline seconds | Reference seconds | Accepted substeps | Sheet pieces | Unclosed energy J | Linear residual magnitude N·s |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 35.978 | 36.302 | 41,823 | 12 | -92.923298 | 0.002550530 |
| Oak | 7.108 | 7.105 | 6,410 | 1 | -44.166886 | 0.000221430 |
| Iron | 5.969 | 5.996 | 5,224 | 1 | -82.828571 | 0.000209460 |
| Ice | 36.770 | 36.557 | 73,631 | 62 | -103.151846 | 0.002694887 |

These are paired observations, not a useful speed improvement or repeated
benchmark qualification. Some earlier build/scoped checks overlapped the glass
comparison; later ice briefly overlapped the beginning of the wider regression.
Timing differences below one percent do not justify a performance claim. Every
physical field matches at all 120 outputs per material; profiler fields alone
are excluded. The smaller scene allocation remains a storage reduction, not a
realtime solve. The inline runner removes zero-worker barrier scheduling but
does not reduce constitutive or contact calculations.

The native executable is MSVC/Windows x64 Release, SHA256
`37881cdb5396d91be7a1d4ba2d0979f5b474a49cbc947dc4030c55e61dd894c0`.
Six scoped CTest entries pass in 9.48 s: face-spring/contact (24 cases across the
two runners), spring trial, rolling resistance, gateway, pipeline and playback.
The four-material full-impact execution parity test is run directly and is also
registered in CMake with a 300 s timeout. Source registration is 326/326 with no
exclusions. This is not a full repository regression or physical material
calibration. Existing nonlinear rotation, spring/contact loss interpretation,
and all five objective stages remain unfinished.

Commands: `cmake --build build/voxel-contact-audit --config Release --target
banjo_voxel_world_run banjo_voxel_face_spring_tests banjo_spring_trial_tests
banjo_rolling_resistance_tests --parallel 4`; `python tests/voxel_execution_test.py
build/voxel-inline/Release/banjo_voxel_world_run.exe`; the six named scoped CTests;
`python tests/voxel_world_test.py --native
build/voxel-inline/Release/banjo_voxel_world_run.exe`;
`python scripts/check-source-registration.py`. Runtime outputs are isolated in
`build/voxel-inline/Release` so the live verified executable is not overwritten.
Local JSONL/build logs retain the preliminary allocation and inline experiments.

The fresh wider production-path regression also passes all eleven completed
comparative/control/refinement experiments, including no-ball/missed-drop,
alternative balls and 12/16 sheet resolutions. The glass-ball energy refusal and
exact retained last accepted state are still tested as a known blocked gate.

The ordinary candidate browser drop reaches 2.000 s, 40 broken faces, 12 pieces,
107 original cells and 41,823 accepted substeps. Downloaded native records retain
all 1,920 host ticks and the tested executable hash. The page reports 60 fps and
approximately 0.05× realtime; native-update profile time is 30.246 s. Contact,
spring and momentum fields match the reference. No useful speedup is established.
Largest batch 488.4 ms exceeds the 8 ms soft budget; this run overlapped the tail
of the wider regression and is not an isolated latency benchmark. Captured page
errors/warnings and final published-server identity are checked at delivery.

Physics source identity and the final website delivery revision are pinned by
`client/voxel-lab/checkpoint.json` and `/api/checkpoint`. Both are published to main
using ordinary fast-forward checkpoints. Remaining failures stay visible.


