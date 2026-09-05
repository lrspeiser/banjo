# Normal-speed platform playback and scratch-buffer checkpoint

Source `852cf97`; published through the regular main-update workflow.

## User-visible behavior

Selecting a detailed reference example calculates a 1.25-second trajectory in a cancellable background worker. Once complete, Replay presents actual recorded render states at normal wall-clock speed. No interpolation between incompatible topology, authored destruction or future-state insertion into live physics occurs. Rigid examples remain live.

Up to four completed recordings remain in this process. The key contains the entire initial package and the exact floating-point duration bits. Resetting or revisiting an identical completed experiment reuses its recording. A changed package or duration requires new work. The process uses one compiled catalog/solver; recordings are not persisted across versions or processes. This is passive laboratory playback, not a general live-world outcome cache, physics state resumption, or completion of the adaptive real-time runtime.

Each recording is limited to 100000 render-instance samples and two simulated seconds. Fixed-tick states are sampled at no more than 120 Hz plus endpoints. Incomplete, cancelled or failed calculations publish no clip. Export final computed report explicitly identifies the final physical state and separately records the displayed replay time. Replay rendering does not mutate a physics world.

## Solver diagnosis and limited optimization

The four-body drop uses a regular internal step of 1.7475902493525004e-7 s: about 5.72 million regular internal steps per simulated second before additional event refinement. The coarse reference continuously resolves stiff material dynamics. Moving that work to a worker did not make physical time advance in real time.

Two per-internal-step vectors (pre-step rollback state and force workspace) now reuse scratch allocations. No material coefficient, timestep, numerical tolerance, fracture law or trajectory policy changes. Recursive refinement still restores the candidate state and returns through the same accepted path; whole-interval rollback remains intact.

One before/after 0.5 m iron-on-glass/oak run (1.1 s physical time) measured 40.834 s versus 38.080 s in the solver. Other desktop/tests were active, so this roughly 7% difference is indicative, not a controlled performance guarantee. Physical output fields match exactly: body states, fracture event records, connected components, fracture work and energy residual. Both runs produce 53 broken glass bonds. Reference calculation remains far below real time.

## Verification

Windows MSVC Release/double-position build. Both affected suites pass in 44.39 s, including previous fracture/ground/reaction/offset cases plus recording checks:
- Recorded endpoint positions equal a direct solver run.
- Playback advances with wall-clock time and stops at the recorded endpoint.
- Exact package reuse avoids recomputation.
- Changed initial velocity and even a sub-microsecond duration change invalidate reuse.
- Cancellation discards partial work; invalid input publishes an error, not a recording.

Native calculation progress, completed Replay control, normal-speed advancement through fracture to 1.25 s/53 broken bonds, and image capture verified. The current prepared recording is left available.

## Remaining performance gate

This checkpoint fixes viewing speed and avoids repeated laboratory calculations. It does not deliver real-time deformable physics. Next: measured solver-stage profiling, validated rigid-to-local-material activation, boundary coupling, local step scheduling, damage-preserving coarsening, and mixed-scene frame-time/energy/trajectory tests. Preserve all 40 original mechanics/platform rows and three-material comparisons.
