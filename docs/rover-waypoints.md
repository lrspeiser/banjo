# Native rover waypoints — October 1

Published implementation: `18180a7ac98822980e3fa013f4d4da5d984721c1` on
GitHub main. The native runner, platform CLI, DLL and regression executable
were rebuilt in the separate MSVC Release directory described below.

## Implemented boundary

The native `behave` operation accepts optional `near_m` from 0.1 to 1 m for
roam programs. The default remains 1 m. It is a radius for an `approaching`
ask, not a body-position constraint or a guarantee about final stopping error.
The runner reports the radius and arrival latch in `asked`; snapshots preserve
both. Older snapshots without these fields restore 1 m and an unset latch.
Invalid radii are refused before sender sequence or native state changes.

For a smaller radius, the controller brakes before turning until speed is at
most 0.01 m/s and yaw rate at most 2°/s, or three seconds have passed. Entering
the radius latches waiting until the next ask. All motion still comes from the
existing native motors, contact and brakes. A slope can prevent a complete
stop; actual stopping position must be checked by the caller. Water and ground
reflexes continue to interrupt autonomous requests.

Native terrain survey now includes `ground_gradient_xz`, in metres/metre,
using the same half-cell central differences as the ground-probe reference.
Together with `ground_m` at the chassis and probe, this predicts that probe's
terrain discrepancy. Surveying does not modify terrain or native state. This
is a top-height-field reading; it does not certify support, overhangs or soil
stability.

## Measured verification

Windows, MSVC Release, `build/agent-progression`; 50 mm scene cells and
`dt=1/240 s`. `banjo_rover_roam_tests` passes all 20 cases, including the
retained 18 glass/oak/iron material/grade scenarios inside the ramp case.
Their mass, sampled contact slip, electrical residual and unclosed mechanical
work remain as recorded in [rover-grades.md](rover-grades.md). No material,
contact, friction or motor law changed here.

In the flat native fixture a target starts 0.7 m ahead. With the default 1 m
radius the rover travels 0.000007411 m; with 0.2 m it travels 0.743121 m and
stops 0.0431262 m from the target. Both retain attached joints and end waiting
after snapshot/reopen. A 0.01 m request is refused with an identical complete
snapshot. In the separate tilted-rover experiment, the survey gradient predicts
the actual probe's reading over a real 0.5 m cut within `1e-9 m`.

The machine API and API documentation CTest gates pass (2.28 s together).
The source-registration guard reports 286/286 registered C++ sources. Evidence
logs are local build outputs: `build/resource-flow/waypoint-api-native.log`
and `build/resource-flow/waypoint-api-tests.log`.

## Open acceptance work

At this engine/API checkpoint, the local Python planner, routine arrival handling
and generated-layout changes were experimental and unpublished. A sample
delivery passes in that worktree, but both 300 s generated-world route runs
still make zero deliveries. Heading-aware planning also encounters actual
ground reflexes. These APIs do not establish successful generated hauling.

The subsequent [generated first-haul checkpoint](generated-rover-hauling.md)
records positive receiving receipts, processing and private pickup on both
maps; sustained return hauling and actual turning/drive clearance remain next.
Physical cargo inertia/tipping, reacting avatars and funded repair remain open
within the full fourteen-item player-experience goal.
