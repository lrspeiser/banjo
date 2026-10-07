# Intact slab and native swing checkpoint — October 7, 2026

## Why the old motion looked like pushing

The sandbox's physical-hit path lifted the grip, translated down, then drove sideways. It did not command wrist rotation. Its grains were already separate exact rigid bodies; their movement was collision and friction, not cracks developing in a solid.

The native live impact path deliberately declines intrinsic fracture for a held tool. Its older lattice island cannot retain the hand, finite actor reaction and target together. Precise rigid bodies contain no deformable internal cells at all. Removing this refusal, invoking an unrelated recorded crack, or replacing a glass slab with loose cubes would not fix that coupling.

## Implemented experiment

The disposable 18891 world starts with **one intact glass slab**, 1.2 × 0.1 × 1.2 m, on the fixed base. Other ground materials and the retained 200-grain fixture remain selectable. Slab mass comes from native material density. There are no predetermined shards, fracture animation, hidden removal or launch impulses. The slab is explicitly a rigid collision test and stays intact.

Physical-hit admission uses actual actor-eye visibility, fixed assembly, declared working point/grip, supported load and arm reach. It reuses the native geometric swing planner. Pickup can begin on any fixed component; ambiguous capabilities and detached connections refuse. The hand lifts clear, winds up, swings along a continuous arc with changing wrist targets and withdraws after the actual native target contact. The support stand is behind the sample so it does not obstruct the ordinary working arc. The isolated iron block is brought to z = 0 m, within the opening stance's swing area. Planning reserves 150 mm inside the existing 1.8 m reach boundary for servo/actor error; it does not enlarge the actual arm.

Both linear and angular targets are bounded force/torque wishes. Angular feed-forward follows the declared orientation path; it does not assign angular velocity. The moving wrist controller uses 60 rad/s, retaining the previous 20 rad/s idle carry rate and the declared 60 N m torque cap. The commanded swing is 3 m/s with 20 m/s² acceleration, rather than the older planner's 400 m/s² wish. The shared physical-hit controller also caps the hand force by the native player's remaining posture torque divided by the actual grip-to-player lever arm, reserving the declared wrist-torque budget. This is a conservative actuator policy, not a material law or a proof of balance on arbitrary supports. The same cap feeds actual force and desired stroke acceleration. Preparation has a distance-derived timeout and measured orientation/speed readiness. The swing tracks the original selected point in its target's actual moving/rotating frame. Path progress is measured relative to that same point; target point velocity feeds a desired hand velocity, never an assigned body velocity. This bounds misses when neighbouring contacts move a grain during the wind-up. A moving target can still outrun the actuator or arm. Contact or blockage stops the strike and initiates physical withdrawal; recovery adopts the actual pose for carry.

Native observations retain phase, measured contact component/closing speed, peak tip speed, actual swing rotation and signed hand work. The browser draws actual native poses as a ghost during the action and reports impact speed. It says intrinsic fracture is unsupported. Glass transparency is a drawing choice, not an optical/constitutive material law.

An unsuccessful swing now records the actual native obstruction and closing speed. It does not count indirect movement of the selected body as contact. The earlier two-grain regression demanded a 280 mm shovel head reach a lower grain through surrounding rigid grains spaced 120 mm apart; the observed second swing meets a neighbouring grain instead. That expectation is explicitly resolved as `target_blocked`, requiring a measured native obstruction, retained custody and upright player. A separate repeated-clear-slab regression requires two positive head contacts for every configured family. This does not relax the retained strict repeated-excavation or convergence gates.

## Verification

Base main `177c6b09d80f42211c4f9555bb465c23bca1265d`; Windows x64/MSVC Release, `build/local-cell-tools`; unchanged Rust debug owner, `build/rust-runtime`. Final scope/results are recorded below after the regression and browser run.

`python tests/test_world_tests.py -v` passes all 12 actual Rust/native gateway groups in 91.815 s. It retains ordinary allowlist/retry/session/pickup checks and all four configured families against grains; glass, iron and anchored scenery remain hittable. Two consecutive clear slab swings for pick/shovel/hoe/custom all contact with the actual head, retain both connected components and exceed 0.3 rad measured rotation. No unnamed missed contact or lost grip is admitted as success. The wider shovel's obstructed second lower-grain attempt records `grain-1-8-9`, closing speed 3.133 m/s and no selected target contact; indirect target displacement is only 1.4 mm.

The matched intact-slab experiment uses the same iron pick, geometry, support, declared swing and 1/240 s native step. Tool cells are 0.02 m. All three slabs keep the same body identities and exact exported mass sums; this is mass retention, not a full conservation qualification.

| Ground material | Slab mass (kg) | Head closing speed (m/s) | Actual swing rotation (rad) | Peak point speed (m/s) | Mass residual (kg) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Glass | 359.99999 | 1.81280 | 0.83251 | 4.11310 | 0 |
| Oak | 100.80001 | 1.76734 | 0.83894 | 4.10269 | 0 |
| Iron | 1133.28004 | 1.77596 | 0.83763 | 4.10296 | 0 |

Expected density differences are present. Stiffness, grain, plasticity and failure are unsupported in this rigid experiment. Native executable SHA-256: `50510f0f0b8cfd6f853b6ddc22678d3c80e8a29695f01f7c3613b7c05a0fd48a`; unchanged Rust owner SHA-256: `220c06eb2410ca5dbce44cfed81da7319de5f1a777fa536591c8b14b018fe266`.

The rebuilt `banjo_native_tool_use_tests`, `banjo_pickup_admission_tests`, `banjo_hand_stroke_tests`, `banjo_ground_work_tests` and existing `banjo_test_world_input_tests` all pass through CTest (8.57 s). `python tests/runtime_native_tests.py -v` passes all 17 actual-worker groups (25.867 s). Source registration passes 315/315 with zero exclusions; Python compile, JavaScript syntax and changed-file whitespace checks pass. The Rust source/binary is unchanged; its standalone 26-test suite and the full repository regression were not rerun for this checkpoint. Retained failures below remain explicit.

The restarted loopback server serves the same executable on `http://127.0.0.1:18891/world.html`. Ordinary in-app browser input acquires the connected pick by its handle, then clicks the glass slab; the UI shows lifting and actual native-pose ghost movement, followed by confirmed target contact at 1.90 m/s, 0.0 cm rounded slab travel and retained Pick custody. Screenshot evidence is locally available in `build/material-lab/glass-swing-tested.jpg` (ignored artifact). Browser error capture is empty after this run. Landscape viewport 844 × 390 exposes all four selectors and Start world through the scrolling setup; the temporary override is restored. This is browser verification, not physical-phone acceptance. The owned demo process is 32444; saved-world server/state are untouched.

## Remaining work

This does **not** produce glass cracks, fragments or excavated volume. Density/friction/restitution of exact rigid bodies do not implement glass stiffness/failure, oak grain/plasticity or iron yielding. Full momentum/angular-momentum/energy closure remains unqualified; gravity, actuator work, fixed support reactions, losses and numerical correction need one full ledger. Mass retention alone is insufficient.

The strict sustained contact convergence and four iron same-column repeat excavation gates remain unchanged and unresolved. Next connect a converged finite-source/hand/target constitutive solve to actual target activation and history-preserving topology replacement. Qualify glass/oak/iron under matched swing conditions, fracture work and all reactions, finite neighbouring support and settling, then useful repeated excavation speed. No retained saved world or production deployment is changed.
