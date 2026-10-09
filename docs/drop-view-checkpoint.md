# High-drop visibility and controls — October 9, 2026

## Actual reported problem

The owner's recorded glass experiment uses a 0.01 kg iron ball at 10 m clearance, dt 1/240 s. Ten steps reach only 0.041667 physical seconds: the ball descends 8.516 mm and is still 9.991 m clear of the sheet. The original camera framed a 10 m drop around a 30 mm-wide sheet, making both physical objects tiny. Inspect impact could also select support/ground compression before the ball arrived. This was a viewer/orchestration problem alongside the known slow experimental solver; it was not evidence that a 10 m collision had completed.

## Delivered behavior

- Target view frames the target independently of drop height. Follow ball tracks accepted ball positions at a useful close-up scale. Full drop fits both endpoints and labels their actual projected positions; marker labels do not enlarge simulated objects.
- The overlay reports the shown accepted time, actual geometric gap and vertical velocity. Remaining time is explicitly a gravity-only estimate using 9.81 m/s², straight descent and nearest rendered surface; it is not CCD or a collision forecast for arbitrary trajectories.
- Run 10 steps displays its actual duration for the selected dt. Editing a setting is detected both by input events and comparison with the active declaration; Run sets up that selected experiment before advancing it.
- Run to ball contact requests every accepted step up to the existing two-second experiment bound. Stop lets the in-flight step complete and accept, then sends no further steps. No skip to an analytical impact pose, authored velocity or outcome animation.
- Inspect ball contact selects an actual accepted microstep with sphere/box-or-plane geometric overlap. It reports geometric overlap, not solver force or the former whole-scene compression maximum. Support-only motion cannot enable it. A refused simulation stops with its actual last accepted time and retained diagnostics.

## Verification and boundaries

Base main `41e1f01344dbbb3c3424b4546b3d2f4e8966451e`; Windows x64. The native executable and coupled CUDA physics digest `31105d759be71507d256aac805caf643c5cf21e9895669e3d122819e96a0b33d` remain unchanged. No physical law, solver tolerance, timestep or solver work capacity was loosened. The exact replay journal storage bound expands from 32 MB compressed / 256 MB encoded to 128 MB / 1.024 GB per session; this changes storage capacity only, not physics admission. The first actual 10 m browser run hit the former compressed bound at 1.204167 s, with the ball still 2.888 m clear. It is retained as a failed delivery attempt, not an impact. Journal boundary tests verify lossless streaming and refusal without corrupting the previous record.

Five CMake-registered scoped suites pass in 10.41 s: gateway, pipeline, playback, scene session and coupled view. The view suite checks independent gravity estimates, sphere/rotated-box geometry, support-only contact exclusion, camera projection at three aspect ratios, immutable physical inputs, changed settings and the floating-point two-second boundary. The client suite checks a long bounded action stopping at an accepted observation, cancellation before the next request, expiry without replay and propagation of physical failures. Source registration is 345/345 with zero exclusions. [Actual check transcript](evidence/drop-view/checks.json).

Normal browser verification uses the actual CUDA glass/iron 10 m experiment, applies an edited height through Run, checks all three views, checks Stop at an accepted step and runs the ten-metre experiment through its actual refusal. The website reports incomplete material qualification and slow calculations. This control improvement does not qualify high-energy fracture, dents, connected trajectories, realtime, phone input or cross-GPU behavior. The current sphere/box/plane geometry observer is for this bounded lab, not a new general collision engine. Full nonlinear residency and material/contact convergence remain open.

## Actual 10 m outcome

[Browser and exact-journal evidence](evidence/drop-view/browser.json): 344 state rows, 42,018,109 compressed bytes. The run crosses the old storage ceiling but refuses the interval after 1.425 s with `Coupled Newton iteration budget exceeded`. Its last accepted ball gap is approximately 0.040 m; 43 private substeps roll back. Inspect ball contact stays disabled. No accepted ball contact, fracture or yield is claimed. Accepted substep peak residual norms are P 5.56e-12 N s, L 6.60e-14 N m s and energy 2.30e-12 J. Computation alone costs 422.84 wall seconds for 1.425 physical seconds (0.00337x); this is not realtime. Next physics work must diagnose and resolve the recorded strong-impact convergence failure under unchanged physical admission gates, with glass/oak/iron comparisons, before claiming a usable high-drop collision.

A separate 1 mm clearance control with the same glass/iron materials, mass and host timestep observes accepted ball contact at approximately 0.0145833 s, stops at host time 0.016667 s and enables inspection of its 0.389 micrometre geometric overlap. This verifies the positive contact UI path, not high-energy damage.

Publishing: this checkpoint is committed and pushed to GitHub main; the delivered server is restarted on that revision. The exact revision is supplied by `/api/checkpoint` and the Git commit containing this document, rather than a self-referential hash embedded here.
