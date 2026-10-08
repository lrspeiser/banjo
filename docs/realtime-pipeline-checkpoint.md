# Near realtime pipeline — October 8, 2026

## Direction and first implemented stage

The owner prioritizes a pipeline for near realtime calculation and visible 3D
motion. The five physics objectives remain retained. This first stage separates
simulation delivery from rendering; it does **not** make the stiff native solver
realtime or resolve its energy/material limitations.

```
User controls → session controller → native CPU worker → accepted frame
                                         ↓                   ↓
                                  compressed journal    bounded delivery
                                                             ↓
                                                  two-pose playback → 3D
```

The [gateway](../scripts/voxel-lab.py) owns one serial native process per session.
A background worker advances the existing native host ticks. An 8 ms soft batch
budget adapts **the number of host ticks per call**, 1–16, without changing dt,
solver iterations, laws, topology admission or energy gates. One expensive host
tick can exceed the budget; the largest batch including IPC is shown. Fast runs
are paced with at most 30 ms physical lookahead. Slow runs stay behind wall time
and expose their actual physical/wall speed ratio.

Commands use a separate condition from the native pipe lock. Pause acknowledges
immediately and drains an in-flight batch once. Manual Step is refused until that
batch finishes. Reset/Close can terminate the disposable native session. Target
times must be later host-tick boundaries within the two-second browser test.
Session isolation, expiry, eight-process limit and request bounds remain.

The worker publishes at most 30 frames per wall second, plus terminal/pause/error
frames. Frame IDs identify immutable published states. The server retains one
published frame and the current accepted calculation state; slow clients receive
the latest frame instead of accumulating a queue. Bounded long polling (≤250 ms)
keeps the transport dependency free. This is a local prototype, not a scaled
multiplayer/network deployment or a hard realtime scheduler.

[Playback](../client/voxel-lab/playback.mjs) retains two accepted native poses.
The [renderer](../client/voxel-lab/world.js) interpolates their cell positions and
shortest-path orientations on its independent animation-frame loop, over a
bounded 16–100 ms presentation interval. It never extrapolates. Component,
broken-face event, material, mass or geometry changes snap to the newly accepted
state; incompatible fracture topology is not blended. Readouts show the latest
accepted physics; the canvas also exposes the interpolated render clock. This
presentation interpolation is not a computed intermediate collision trajectory
and can miss within-frame contact curvature. Precise inspection uses native
recorded states and Before/Live. It generates no shatter animation or impulses.

The visible readout distinguishes simulation speed from renderer fps. Rendering
at 60 fps does not certify 60 Hz physical calculation. The compact build panel
continues to list the unresolved glass-ball energy gate and the other objectives.

## Logging and verification

Higher publication frequency exceeded the old 32 MB plain journal at 1.976 s in
the first browser run. That failure was retained and fixed before publication.
New journals use concatenated lossless gzip members, with independent 32 MB
compressed / 256 MB uncompressed limits. The download endpoint still provides
plain NDJSON. Older plain journals remain on disk. Each published frame contains
the exact native response and the list of native `advance` counts since the last
publication, allowing replay of every completed call in that batch. Controls and
pipeline metrics are recorded. This is no cached physical outcome; it changes
storage/transport only. A record limit still stops the session explicitly.

[Pipeline tests](../tests/voxel_pipeline_test.py) compare all physical state fields
against the synchronous native reference for glass, oak, iron and ice, 96 ticks
at 1/960 s (0.1 s), same default 1 kg iron ball, 10 m height and 4 mm, 64-cell
sheet. Only wall-time profiler fields are excluded. State, mass, mechanics,
gravity/contact diagnostics and topology agree exactly. These short cases test
scheduling parity, not new constitutive validity. Archive response equality,
native command totals, compressed byte counts and bounded buffers are checked.
A deliberately added 300 ms native-call delay tests control separation, one
drained batch, stable pause, stepping exclusion and malformed/off-tick commands.
This injected delay is a control test, not a physics benchmark.

[Playback tests](../tests/voxel_playback_test.mjs) check bracket interpolation,
late/duplicate rejection, no extrapolation, topology/material/geometry snapping
and bounded/reset storage. Both tests are registered in CMake; Node is required
for the optional playback CTest entry. The existing gateway regression remains.
The native executable is reused unchanged from physics revision `5e01124f`, SHA256
`6b22cfb5171602946ebc25759bfb09a2b763bc9683a1d388fc148a52a6c580bc`.
Earlier twelve native oracles/eleven drop experiments remain prior evidence for
that exact binary; this stage does not claim a fresh full repository regression.
Windows x64/MSVC Release CPU and desktop browser scope only.

Three registered scoped CTest entries pass in 5.40 s (gateway, pipeline,
playback). Source registration is 326/326 with no exclusions. CMake was
reconfigured for test registration; the verified native executable was not
rebuilt or substituted. Node syntax and Python compilation checks pass.

The repaired ordinary browser drop reaches 2.000 s with 40 broken faces,
12 sheet pieces, all 107 original cells and 41,823 accepted substeps. Its final
native frame equals the archive exactly. All 1,920 native host ticks are recorded
in replay command batches; the journal has 604 rows / 33,393,742 uncompressed
bytes, safely inside the new bound. Measured wall time is 39.868 s, ratio
0.05017×, maximum native batch plus IPC 279.351 ms, versus the 8 ms soft target.
The browser displays about 60 fps. These separate numbers establish responsive
delivery and show that the physical calculation target remains failed.

Ordinary Pause/resume, camera mode during calculation, complete Drop and an
844 × 390 landscape layout were exercised. The original browser connection
interruption was repaired with bounded retries of idempotent frame reads and
50 ms polls; no side-effect command is automatically retried. The final browser
run reaches completion and captured warnings/errors are empty. No real-phone
input qualification is implied. Logs/screenshots remain local excluded evidence.

## Next stages and acceptance gates

1. **Measure the pipeline:** retain per-material simulation ratio, batch latency,
   packet/journal size, render rate, input acknowledgement and oldest displayed
   physical state. Initial targets: ≥0.8× physical speed during representative
   impacts, ≥50 fps rendering, p95 control acknowledgement <100 ms. Those are
   targets, not achieved solver claims.
2. **Reduce native work:** profile global refinement, active spring/contact solves,
   rollback snapshots and full-state serialization separately. Avoid scanning or
   solving settled/unloaded regions when the retained state allows it. Benchmark
   changes against the CPU reference, full signed conservation and refinement;
   do not obtain speed by silently dropping constraints or tolerances.
3. **Activate detail locally:** represent stable regions more cheaply and refine
   approaching impacts/edges. Transfers must retain mass, inertia, stress/strain,
   damage, momentum and energy with consistent time. Local schedules exchange
   accounted interface forces/work; no fast-fragment global slowdown or skipped
   external contact. This requires new measured physical qualifications.
4. **Improve the solid solver:** evaluate a coupled implicit sparse solve and
   parallel independent islands before a GPU implementation. Glass/oak/iron/ice
   must retain their differences and accuracy under resolution/timestep changes.
   Resolve the glass-ball energy failure; add permanent metal yield/dents/tearing.
5. **Author and publish:** custom geometry/material declarations, budgets and
   validity bounds feed this same pipeline. LLMs author/inspect on demand; none is
   required in the physics or rendering tick. Broader worlds and mobile acceptance
   follow measured local performance, rather than inheriting this lab's results.
