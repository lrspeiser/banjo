# Lab session recovery — October 9, 2026

## Cause and implementation

Lab workers expire after ten minutes of inactivity, or disappear when their server restarts. Previously, Set up closed the old session before creating a new scene; closing an absent session failed, so the requested reset never happened. Returning from browser back/forward caching could also retain a closed handle.

The shared gateway now returns HTTP 410 with `code: session_expired` for absent/expired scene operations. Close is idempotent on both CPU and GPU endpoints. Invalid identifiers and wrong-backend operations remain errors. Other live scenes retain their state. The ten-minute worker resource limit is unchanged.

The coupled lab uses a tested session client. An advance that encounters structured expiry sets up a fresh scene using the selected controls and tells the user to run it again. It never retries the interrupted step/batch, resumes fabricated history or treats a physics refusal as session expiry. Fresh scene measurements start at time zero. Reset refreshes the running physics digest, and a restored browser page requests setup. Other lab pages benefit from idempotent close during manual setup; automatic recovery is currently wired to the coupled page only.

## Verification and scope

Base main: `080cb31d900639e94d5835c1a7f3012e329d52aa`. Windows x64, Node and Python gateway; unchanged native executable and coupled CUDA digest `31105d759be71507d256aac805caf643c5cf21e9895669e3d122819e96a0b33d`.

Four CMake-registered scoped suites pass: gateway, pipeline, playback and scene session (11.07 s). The gateway ages an actual worker by 601 seconds, verifies structured expiry, repeated close, fresh setup/advance and isolation of another scene. The client checks expiry during a multi-step action, exactly one recovery, cancellation of remaining steps and propagation of physical/network/recovery failures. Source registration remains 345/345, zero exclusions. No source-level material law, solver tolerance or physics model changed; this is not new physical qualification.

Normal browser verification reproduces a missing server session in the coupled 3D page, checks automatic fresh setup without stepping, then checks successful user-requested advancement. Manual Set up after an absent session is also checked. The published server and source keys are verified after pushing main. Full material accuracy and realtime gates remain open.

Evidence: [scoped test transcript](evidence/session-recovery/checks.json) and [normal browser recovery](evidence/session-recovery/browser.json).
