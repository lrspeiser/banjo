# Chat-authored experiments and embedded 3D controls

September 6, 2026. This advances G09 authoring and inspection; none of the nine
platform goals or 40 retained requirements is discharged.

## Implemented

Chat produces a validated physics declaration plus up to twelve declarative
buttons, sliders and toggles. Network packages run once in the native recorder;
their reports and browser states come from that same continuous execution.
The page opens the actual recording in **3D Playback**, with orbit, zoom,
pause, frame stepping, inspection and internal structure display. Pressure
reference output uses solved tetrahedral displacements and accepted states.

Authored physical controls create new immutable runs without calling GPT again.
Supported parameters are drop height, impact speed and reference pressure.
Playback speed, displacement magnification and structural overlays affect display
only. Pressure frames are load increments presented at 150 ms per frame, not
physical elapsed time. Network timing uses recorded SI timestamps without
interpolation. Browser refresh and explicit `?job=<id>` recover a result while
the same server session is running. Server restart still clears its index.

No arbitrary generated JavaScript or HTML runs. Recordings are served only from
registered server-owned paths; the native recorder caps steps (1440), frames
(122), cumulative bodies (4096), bonds per frame (20000) and bytes (64 MiB).
Three.js 0.185.1 and its MIT license are pinned and served locally.

## Verification

Windows MSVC 19.44 Release, Intel Core Ultra 9 285K:

- 58 existing native suites pass in 80.92 s.
- Three native recorder integration tests pass in 2.155 s: matched glass/oak/iron
  rigid and panel recording, CLI physical report parity, exclusive output and
  input/step rejection. Timing/compiler/derived-skin-query counters are excluded
  from parity; physical fields are retained.
- 33 existing mocked playground tests, seven control-contract tests and nine
  new browser API tests pass. Coverage includes no second engine run, no planner
  call during control reruns, immutable plans, idempotency, requirement blocking,
  playback registration, and CSRF/origin checks. These are also added to CI.
- Live GPT job `fac4b4a0ebe24ec4bf1569808e9aa35d` requested the illustrative
  glass/oak/iron pressure reference at 200 MPa, resolution 4, 16 increments.
  GPT authored Watch response, Reset test, components, magnification and pressure
  controls; the page automatically displayed the resulting 3D experiment.
  Planning took 12.506 s; total run took 12.699 s.
- Its browser pressure slider generated job `07b7f93bb6d04ce694e87c65e6e1421b`
  at 800 MPa in 0.210 s, with model=null and zero planning time. Original pressure
  remained 200 MPa. At 200 MPa all three completed and unloaded almost to rest.
  At 800 MPa oak stopped at a solver limit; iron completed with final maximum
  displacement 3.4582e-5 m and plastic strain 0.0038335. These are illustrative
  model results, not calibrated material measurements or speed qualification.
- Live GPT rigid control `679aca0741054bb493059dfe1964a16e` produced 121 sampled
  frames over 0.5 s, displayed in the browser with a generated Release button and
  height control. End-frame scrubbing and browser refresh were exercised.
- A live thin-glass request failed validation because GPT proposed an incompatible
  control; no simulation or substitute scene ran. Separate deterministic tests
  verify thin-glass and explicit unmet-requirement blocking. Planning can still
  misinterpret requests; strict schema validation is not semantic omniscience.

## Remaining boundaries and next work

This is bounded native computation followed by interactive recorded viewing,
not a realtime browser solver. Network fracture and the quasistatic continuum
reference remain separate runtimes; collision-driven J2 deformation, calibrated
thin-glass shattering, tomato cutting, full conservation and refinement gates
remain open. Pressure high-load spatial convergence still fails. No new material
law or accuracy claim is introduced by this renderer.

Next: unify contact, constitutive state and fracture before expanding claims;
add calibrated comparative fixtures, cancellation, durable job restoration,
and measured capture/render budgets. Retain all goals and scorecard rows.

## Blocked-request visibility follow-up

The owner's thin-glass job `fe25f038cc7b451d9cb1fdbf143caae7` was blocked before native execution, but the 3D tab showed only generic empty-view text. It now shows the unmet requirements and reasons, disables playback controls, and offers Edit request. Fresh terminal failures and restored blocked links share this presentation. Verified using the actual blocked job in the browser, JavaScript syntax checks and browser error inspection; successful pressure playback still loads. This is a UI correction, not added thin-glass physics.
