# Final contact slip and twisting disagreement

October 8, 2026. **Implemented read-only diagnostics and regression; the accuracy
and speed goals remain OPEN.** This follows [matched contact friction](midpoint-contact-friction-checkpoint.md).
No response law, impulse limit, contact ordering, iteration default, timestep,
damage law or acceptance tolerance changes in this checkpoint.

## What the remaining failure actually does

The midpoint glass-ball/glass-sheet experiment still stops at 1.4703653971358452 s.
The rejected candidate at h=6.357828776041667e-8 s has total twisting work
+0.06967099361581955 J. The dominant witness is contact between original ball
cells **175 and 176**, with three contact points and coefficient 0.3499999940:

- Midpoint relative normal spin: +163.7599994863 rad/s.
- Twisting impulse on cell 176: +0.000427475250979 N m s.
- Final normal-load-derived torque impulse cap: 0.000427475268982 N m s.
- Work at that contact: **+0.070003346881 J**.
- Maximum-dissipation variational gap: **0.140006696710 J**.

The impulse is within its bound but points along final midpoint slip. This is
disagreement between the final coupled result and the friction row, not a missing
cap, fracture heat, or a justified external energy input. The native normal row
is nearly satisfied here (max normal complementarity error 2.32098e-7 J), so a
normal-only convergence report is insufficient.

Pinned Jolt solves tangent friction, then twist, then normal contact using the
previous iteration's normal impulse to cap friction. Other rows and contacts can
change motion after a friction row is solved. This witness localizes the defect;
it does not prove that changing order, increasing iteration count or solving only
this pair will resolve the whole contact island.

## Measurement and units

`JoltWorld` records the actual supplied combined friction coefficient and each
contact point's distance to the native friction center. Those distances reproduce
the native float projection used for the twist cap. The existing saved native
impulses and force-phase observations remain authoritative.

For final tangent impulse p, midpoint tangent relative velocity u and disk cap C,
the variational gap is **p dot u + C |u|**, in joules. For twist impulse t,
midpoint relative spin w and interval cap T, it is **t w + T |w|**, also joules.
A feasible converged maximum-dissipation row has zero gap. Negative work alone
does not establish convergence. Impulses exceeding their final caps are reported
separately in N s or N m s; a negative signed gap cannot hide infeasibility.

The native caps are C=mu sum(normal impulses) and
T=mu sum(radius times normal impulse). Slip uses initial and actual pre-integration
solver velocities at frozen native contact geometry, matching the experimental
midpoint row. Static bodies contribute zero velocity. The reference contact model
does not use midpoint diagnostics. Finite geometry/material calibration remain
unqualified. These numerical terms are not labeled as heat.

Source: `src/physics/RigidStepWork.*`, `src/rigid/JoltWorld.*`,
`src/platform/VoxelImpactWorld.cpp`. A rejected trial retains one bounded worst
twist witness, including original cell IDs, normal, contact position, coefficient,
impulse/cap and before/solver spins. Rejected poses are not rendered. Accepted
snapshots accumulate maximum per-contact gaps and cap excesses.

## Comparative full-world evidence

Windows x64, MSVC Release CPU; same experiment as the preceding checkpoint:
40 x 40 cm, 4 mm, 8 x 8 / 64-cell sheet on edge supports with 32 cm gap;
1 kg constituent ball dropped 10 m, host h=1/960 s, 96 velocity iterations.
Sheet density/stiffness differences retain masses 1.6/0.448/5.0368/0.58688 kg and
moduli 70/12/211/9 GPa for glass/oak/iron/ice. Oak remains an elastic lab comparison
without grain or organic gameplay; iron has no permanent dents in this scene.

| Sheet / ball | Physical s | Wall s | Substeps | Max sliding gap J | Max twisting gap J | Unclosed energy J |
|---|---:|---:|---:|---:|---:|---:|
| Glass / iron | 2.000 | 124.879 | 68311 | 0.016411 | 0.033121 | -46.297776 |
| Oak / iron | 2.000 | 61.626 | 25715 | 0.000559 | 0.000116 | -42.845356 |
| Iron / iron | 2.000 | 77.342 | 30086 | 0.006147 | 0.000959 | -64.249153 |
| Ice / iron | 2.000 | 86.531 | 75292 | 0.006029 | 0.011728 | -18.353908 |
| Glass / glass | 1.470365; REFUSED | 63.445 | 26503 | 0.008892 | 0.351590 | -44.273274 |

Maxima are over accepted steps; the separate rejected witness above is not added
to them. Every final physical/work record matches the previous verified native
executable exactly after excluding timing and only the newly added diagnostics.
The separate four-material reference comparison matches every physical/work
record at 16-host-tick intervals through 2 s. Retained complete P/L residuals and
unexplained energy losses are unchanged; see the preceding checkpoint's table.
Neither preserved trajectories nor completed drops establish physical accuracy.
Timings share this host with verification and do not qualify a speed improvement.

## Iteration probe: not a solver fix

Same glass-sheet/glass-ball declaration, changing only native iteration count:

| Iterations | Refusal time s | Wall s | Substeps | Sheet / ball pieces | Rejected total twist work J | Worst twist gap J |
|---:|---:|---:|---:|---|---:|---:|
| 16 | 1.832482910 | 102.399 | 152830 | 23 / 29 | +0.000978759 | 0.002251568 |
| 96 | 1.470365397 | 59.915 | 26503 | 15 / 20 | +0.069670994 | 0.140006697 |
| 256 | 1.548152669 | 59.148 | 26896 | 21 / 21 | +0.002162156 | 0.004324312 |

All refuse the unchanged energy gate. Different histories and non-monotonic
refusal times do not show convergence. No iteration default or limit is changed.
This evidence requires a coupled contact/island repair, with friction and normal
stationarity measured together, rather than promoting a larger iteration count.

## Tests, website and next work

The existing registered `rigid_step_work_tests.cpp` now checks sticking, saturated
sliding/twist, reversed impulses, dissipative but unconverged interior rows,
cap violations, zero-friction free slip and invalid inputs. Actual native coupled
glass/oak/iron regressions check supplied coefficients, impulse caps and final
stationarity in both CPU runners. New stationarity checks use 5e-6 J in these
controlled float fixtures; existing energy and normal-contact bounds are unchanged.
The full-world diagnostic helper verifies rejected witness identities and exact
work/gap arithmetic against actual native and browser records; this is not a
passing accuracy gate.

Five focused CTests pass in 3.73 s: native face/contact oracles, rigid work,
actual gateway, bounded pipeline and playback. Five full material comparisons,
four-material reference parity, three iteration probes and five final experimental
physical/work record comparisons are separately verified. Source registration is
331/331, no exclusions. No full-repository, physical-phone, cross-OS or cross-GPU
qualification is claimed.

The 3D website's **Physics & record** shows normal/sliding/twisting disagreement
and the worst rejected cell pair, slip, work and impulse/cap. Download record
retains the complete witness. An ordinary browser glass/glass drop reaches the
same refusal and 20 ball components, without console errors/warnings. Its journal
is saved in `build/voxel-friction-convergence-browser-refusal.jsonl` (1,048 rows).

Implementation source revision: `30c9158d3b59a36cd22fd7805c705821e066778b`. The website reports its publication revision separately.

Verified native SHA256:
`6fdfee11ea7643c35d161ac84a81dd64b8430c7626e44a47f4ca725a10a88f8d`.
Build: `build/voxel-contact-audit`; output:
`build/voxel-friction-convergence/Release/banjo_voxel_world_run.exe`.
Evidence: `build/voxel-friction-convergence-{final-build,oracles,ctest,comparison,baseline,iterations,record-verification}.log`
and `build/voxel-friction-convergence-browser-failure.png`.

Next implement and qualify a coupled contact solve against these final-slip
witnesses, including tangential effective-mass coupling, twist/normal coupling
and island-wide interactions. A smaller residual in an isolated row is insufficient:
retain full material, timestep, spatial refinement and P/L/E gates. Then reduce
active solve/substep cost without changing laws. Persistent metal plasticity,
adaptive cells and validated authoring remain unfinished. The five goals stay active.
