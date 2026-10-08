# Voxel contact impulse audit — October 8, 2026

## Implemented measurement, experimental world

The [native wrapper](../src/rigid/JoltWorld.cpp) now has an opt-in discrete
contact audit. It joins the actual callbacks from this Update to Jolt 5.6.0's
saved contact impulses. Normal impulses act at the native contact midpoints;
friction acts at their mean, in the solver's two tangent directions. Twist
impulses are also retained. The readback contains solver impulses, not the older
collision-response estimates. No contact response or material law is changed.

The reader is pinned to the installed Jolt contact-state format. Point counts,
missing manifolds and bounded recorder size are checked; a mismatch refuses the
audit instead of substituting an estimate. Dormant cached impulses are excluded.
Sensors are excluded. CCD contact auditing is unsupported and explicitly refuses.
Use a reversible trial to restore native state when an audit fails. Refused
trials restore observations as well as the solver's state. The existing rolling
resistance reader uses the shared parser and retains its prior fallback policy;
the new audit does not use that fallback.

The [voxel world](../src/platform/VoxelImpactWorld.cpp) enables this measurement
for every accepted native substep. It accumulates normal/friction/twist endpoint
work, reactions on the anchored supports/floor, and moments of those reactions
about the world origin. Endpoint work uses the final velocities with the
start-of-solve lever arms. These terms are diagnostics, not a complete energy
balance: angular quadratic updates, finite-rotation transport, gyroscopic
integration, sleeping and constitutive/integration consistency remain open.

Gravity is counted only for dynamic bodies active at the start of Update, using
native gravity/factor/duration and actual solver mass. Initially counting gravity
on all occupied cells produced a false large vertical momentum residual once
cells slept; that approach was removed. The retained linear residual compares
measured momentum change with scheduled gravity and actual support reactions.
Float update roundoff and deactivation may still contribute. It is not a full
angular-momentum or energy certification. The world applies no other external
forces in this experiment; this gravity-only account is not a general force API.

## Analytical tests and measurement scope

[Face-spring tests](../tests/voxel_face_spring_tests.cpp) retain the seven prior
translation/torsion/orientation cases and add four contact cases plus an active
versus sleeping gravity case: twelve checks in total. Contact cases compare
actual impulses with changes in both bodies' linear momentum and spin, exercise
frictionless/frictional and dynamic/anchored pairs, and close the fixed-frame
endpoint-work plus velocity-quadratic identity. Momentum/spin residual tolerance
is 2e-6 N·s / N·m·s, contact energy 3e-6 J. The measured frictional dynamic-pair
energy residual is -1.561e-8 J; the others are below 5e-15 J. The gravity oracle
uses 1e-10 N·s. These are neutral rigid-box oracles, not material constitutive
validation. Rollback, stale sleeping cache exclusion and CCD refusal are tested.

The [production-path regression](../tests/voxel_world_test.py) retains the same
glass/oak/iron/ice 1 kg iron-ball, 10 m drop, 0.4 × 0.4 × 0.004 m sheet,
8 × 8 × 1 cells, 0.32 m support gap, 1/960 s host step, 96 velocity/4 position
iterations and adaptive substeps. It also retains no-ball/missed-drop controls,
alternative balls, 12/16 sheet resolution and the known glass-ball refusal.
Contact fields and original cell identity/mass must remain finite/retained.
No material strength, fracture, positive-energy tolerance or iteration count
was changed to pass these checks. Metals/oak remain elastic; oak is the retained
comparison reference, with grain and plasticity unsupported.

Final build, comparative measurements and website delivery are recorded with the
published checkpoint below. This is Windows x64 / MSVC Release CPU evidence;
other platforms, cross-GPU determinism and real material calibration are not
qualified. Source registration must pass 326/326 before publishing.

## Website delivery and next work

### Same-condition measured results

| Sheet | Normal endpoint work (J) | Friction endpoint work (J) | Twist work (J) | Support impulse magnitude (N·s) | Linear residual magnitude (N·s) | Wall time (s) |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 39.113698 | -8.667309 | -0.396340 | 33.833398 | 0.002550530 | 46.43 |
| Oak | 6.920380 | -18.881502 | -0.191725 | 28.383512 | 0.000221430 | 9.58 |
| Iron | 38.909792 | -3.661911 | -0.064097 | 72.663469 | 0.000209460 | 9.46 |
| Ice | 79.994968 | -13.465379 | -0.146762 | 25.187004 | 0.002694887 | 51.14 |

Each reaches two physical seconds. These are cumulative accepted-step endpoint
terms, not collision-energy losses; a positive normal term is possible with
restitution. They must not be added to the spring diagnostic terms as if they
were independent energy sinks. Large unclosed energy remains unchanged:
glass -92.923298 J, oak -44.166886 J, iron -82.828571 J, ice -103.151846 J.
All final object states and substep counts exactly match the pre-audit reference;
only measurement fields/timing changed. Build activity overlapped the early
comparison run, so these times are execution observations, not evidence of a
speed improvement. The added observation has a cost; useful speed remains open.

Six rebuilt scoped CTest entries pass in 8.38 s: the twelve-check face/contact
suite, spring trial, scene joint, joint interface, gateway and rolling resistance.
The latter covers the shared contact-parser refactor. This is not a full
repository regression. Source registration passes 326/326, no exclusions.
All eleven production-path experiments complete with finite contact fields and
retained constituent identity/mass; the glass-ball impact refusal and its exact
last accepted state remain covered. The ordinary browser preview completes the
default drop with 40 broken faces, 12 pieces and 107 cells. Its contact work and
0.002551 N·s residual match the archived native JSONL, Before resets the measured
view to the initial zero-contact state, and captured browser warnings/errors are
empty. This does not imply a real-phone input qualification.

Exact commands: `cmake --build build/voxel-contact-audit --config Release` with
targets `banjo_voxel_face_spring_tests`, `banjo_voxel_world_run`,
`banjo_rolling_resistance_tests`, `banjo_spring_trial_tests`,
`banjo_scene_joint_tests`, `banjo_joint_interface_tests`; corresponding scoped
`ctest --test-dir build/voxel-contact-audit -C Release --output-on-failure -R
'^banjo_(voxel_face_spring|voxel_gateway|spring_trial|scene_joint|joint_interface|rolling_resistance)_tests$'`;
`python tests/voxel_world_test.py --native build/voxel-contact-audit/Release/banjo_voxel_world_run.exe`;
`python scripts/check-source-registration.py`. Build logs/JSONL/screenshots are
local excluded evidence, not committed artifacts.

The [test website](../client/voxel-lab/index.html) adds compact live contact work,
support impulse magnitude, momentum residual and measured contact-point count
under **Physics & record**. Vector reactions, twist work and cumulative gravity
remain in the downloaded native record. The build panel pins the tested binary
through [checkpoint evidence](../client/voxel-lab/checkpoint.json); stale executables
cannot inherit these results. The delivery protocol remains in
[website verification](test-website-checkpoint.md).

The five-part objective remains active: resolve the glass-ball failure and full
energy account, improve speed, implement persistent metal yielding/dents/tearing,
adaptive spatial resolution, and validated custom material/geometry authoring.
This checkpoint adds evidence needed for the first task; it does not complete
any missing constitutive model or turn those stages into validated behavior.
