# Held strikes: actual player hand rollback — October 2, 2026

## Implemented boundary

`LiveWorld::step` now saves every player's complete hand context before it
advances the hand wishes. A refused native contact step restores the context
map and the caller's active working context, including stroke progress/recent
history, desired grip and wrist, queued hauling force, work and release records.
Restoration selects the caller's terrain carrier without flushing tentative
working fields back into the saved map. Loading the saved active context moves
its stroke and strings. The snapshot is consumed only once; carrier restoration
failure reports a discard-world error. This does not promise recovery from
allocator failure. The earlier partial `abandonHandStep` is removed.

The accepted-step counter is restored on refusal and on an exception before
native acceptance. The previous horizon is restored on exception. A genuine
material offer retains the refused step's duration: the fracture window must
cover the time to that contact, and the support penetration admission also uses
that duration. This deliberate distinction is not a second accepted step.
The guard stops restoring actors once the native step has been accepted; a
later settlement failure cannot pretend that already advanced bodies rewound.

This completes the hand boundary in the existing ordinary native trial, not
the entire world transaction. Cut/tool preparation, programs, controls,
motors/circuits, fracture-offer receipts and postaccept settlement are separate
histories. The large-world path beyond native reversible-trial capacity still
has no native rollback. This change does not coordinate these actors with the
new paired native/CPU target loop yet. No material law, controller force/torque
limit, response, damping or test tolerance changes.

## Regression and measured results

The compiled hand suite first reproduced the defect before the fix:
`refused/retried step changed a player's hand state`. The regression now runs
nine same-condition comparisons: catalog glass, oak and iron, each with free
wielding, actual hinged hauling and an ideal fixed tool/handle group. It uses
Windows x64 Release, CPU Parallel, 20 mm cells, zero gravity, seed 971 and
1/240 s world steps.

Each actor has a 100 mm sphere head, starting at (+/-1, 1.5, 1) m. Mirrored
0.8 m strokes request 4 m/s, 40 m/s² acceleration, 50 mm lead and a 0.4 rad
wrist turn. Strength remains 800 N and torque 60 N m. Hauling uses an anchored
40 mm iron block and an actual ideal hinge. The fixed case uses a
240×40×40 mm oak handle and the ordinary ideal native fixing. These ideal
interfaces are fixtures, not finite strength measurements.

A separate 100 mm iron sphere, explicitly initialized at (0, .24, 0) m with
velocity (0, -8, 0) m/s and zero spin, meets a 300×40×300 mm glass pane at
(0, .1, 0) m. Foresight is disabled. This actual native contact produces the
material admission and refusal; damage is not injected. The same offers are
declined in the retry and never-rejected controls so they can compare the
accepted rigid trajectory without launching an unrelated fracture job.

For each case the test checks both actors' public hand state before and after
refusal exactly, then compares accepted time, grip/work/release/stroke fields
and actual native constituent position, velocity and orientation against the
never-rejected control. A subsequent unrepresentable positive timestep throws
after hand wishes begin; both actors and time restore, and the next accepted
step again matches the control.

After cancelling the strokes, snapshots must retain identical `hand` and
`player_hands` data and accepted `steps`/`last_dt_s` metadata. Both snapshots
must reopen at `whole` tier; eight additional steps compare both players and
native constituent motion exactly. This compares two reopened worlds, not
reconstructed native solver caches against a still-running world. In-flight
strokes remain outside the save format.

| Mode | Head material | Head mass (kg) | Right player's signed work before restart (J) | Refusal/retry/restart differences |
|---|---|---:|---:|---|
| Free grip | Glass | 1.12 | +0.310001 | Exact |
| Free grip | Oak | 0.3136 | +0.0868004 | Exact |
| Free grip | Iron | 3.52576 | +0.674483 | Exact |
| Hinged haul | Glass | 1.12 | +0.147805 | Exact |
| Hinged haul | Oak | 0.3136 | +0.082133 | Exact |
| Hinged haul | Iron | 3.52576 | +0.0794768 | Exact |
| Fixed group | Glass | 1.12 | +0.0378528 | Exact |
| Fixed group | Oak | 0.3136 | +0.0158737 | Exact |
| Fixed group | Iron | 3.52576 | +0.103424 | Exact |

All three materials retain their density/mass and catalog constitutive inputs.
This experiment measures restoration and replay, not fracture, grain,
plasticity, energy conservation or calibrated interface strength. No new
momentum/energy residual bound is asserted. The retained physical phase
measurements and their unclosed source/hand remainders are in the
[hand](held-strike-hand-checkpoint.md) and
[integrator](held-strike-integrator-checkpoint.md) checkpoints; exact replay
does not resolve those balances or imply cross-platform determinism.

## Verification and publication

Separate build: `build/agent-paid-machine`, Visual Studio 2022 x64 Release,
MSVC 19.44.35228.0 / MSBuild 17.14.51, CPU, `BANJO_BUILD_LAB=OFF`.
The focused executable passes all nine named cases, including the nine
mode/material comparisons above. The source-registration guard passes
297/297 sources. All 14 affected ordinary suites pass in 86.49 seconds:
hand stroke, LiveWorld, live determinism, ground work, blade, fixing, rope,
motor, circuit, machine control, thermo live, thermal mechanics, thermal
geometry and blade thermo. The full long material-network capacity suite is
outside this unchanged scope.

Logs (ignored local artifacts):
`build/resource-flow/actor-rollback-before-results.log`,
`actor-rollback-restart-build.log`, `actor-rollback-restart-results.log`,
`actor-rollback-regression-build.log`, `actor-rollback-regression-results.log`.

Published implementation: `ef5ebc046e967610c7c6b033e8147c984f9545b4`
on GitHub main. The compiled implementation sources and tests are those at
that revision. No app or preview EXE/DLL is replaced; no new interactive window
or ordinary object-use route is verified by this engine regression.

## Next player work

Connect actual held actors and accepted time to the
[paired native/CPU target boundary](held-strike-rollback-checkpoint.md).
Complete finite interface failure/load accounting and grip remapping, then
pass a named native crosshair target through ordinary tool Use. Qualify actual
damage/separation, private collection/history, funded replacement or genuinely
supported repair, equip/use, another player, failed saves and restart. This
checkpoint does not close R3 or advertise made-object destruction in the app.
Include the striking tool's own supported damage and finite-fixing failure;
ordinary use still has no fatigue, abrasive wear or edge-blunting law.
