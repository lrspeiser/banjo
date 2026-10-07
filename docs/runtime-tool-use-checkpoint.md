# Native tool use: experimental controller checkpoint

October 6, 2026. Source baseline/main before this work: `08a05c2b`, which published [read-only admission](runtime-tool-admission-checkpoint.md). The isolated native controller is implemented; browser migration and useful sustained digging remain open. This is a partial W06 checkpoint, not completion of the W00–W17 rewrite.

Controller, tests and evidence published on GitHub main as `f85666f0`. The recorded local runner/library were built from that checkpoint's source changes; the trusted native protocol still does not attest compiled-source provenance. `C:/play` remains `c29d8ade` on port 18890.

## Implementation and ownership

`NativeToolUseController` consumes actual grip, tip, direction, connection, reach, target revision and native contact reports. It emits only desired actuator frames. Existing bounded hand force/torque, equal actor reactions, fixed joints and ground contacts determine actual motion. There are no body-pose/velocity assignments, cosmetic shards, fragment launch impulses, free work or material-name branches in this controller.

Begin recomputes native admission. The optional C++ preview token checks tool/point, region/column, material revision, hit and surface; its desired path is not trusted. A second use while active is refused. Each actor retains independent controller/carry state. Queries do not advance time. Action phases advance only after accepted native steps; controller and selected-target state participate in the hand rollback copy. The copy/retry oracle is not proof of full physical-pipeline rollback.

The short contact plan replaces the older thirteen-point swing preview with three desired grip targets: ready, maximum downward travel and lateral work. Ready is 60 mm above the selected surface, maximum travel is 140 mm, and lateral travel is 40 mm toward the actor. For column terrain, the actual contact is planned inside the selected cell at its center; the preview retains the original ray hit. This prevents ordinary actuator error at a boundary hit from selecting its neighbor. It does not broaden the cutting patch, resolve ambiguous edge rays or grant removal of a whole cube.

Requested speed is bounded by 4 m/s, available force/mass acceleration and an 80 m/s² ceiling, with braking and a 25 mm desired lead. Preparing requires measured tip/grip errors below 25 mm, point direction y below −0.98 and grip speed below 0.5 m/s. A measured bite at least 6 mm deep permits lateral work at the actual tip height. A native `broke out`/`broke rock out` contact starts withdrawal; reaching a visual path endpoint is not required to validate a physical breakout.

Preparing/contact/recovery timeouts are 2/1/2 native seconds. Existing active-stroke positional gain (100 rad/s) is also used for this controller; fixed-assembly idle positional gain remains 20 rad/s and wrist gain remains 20 rad/s. Force/torque caps are unchanged. This is an actuator choice, not a new strength or constitutive law. An initially horizontal tool requests a bounded 0.6 m lift before turning; that floor acquisition posture is not qualified by these upright fixtures.

Only Acting authorizes a new ground meeting. Recovery retains an existing resistance contact until the actual tip clears it; ordinary collision is restored by the retained contact implementation. Cancel stops new work and withdraws vertically from the actual buried tip. Drop interrupts authority immediately. A disconnected working point is `capability_changed`; an absent grip is `grip_released`. A terminated action refreshes only an already-open contact started before its end, then freezes its result. Later hand work, peer meetings or clearing closed contact logs cannot erase or inflate its result.

Reported work/impulses/yield come from native meetings. Positive yield is never promised at begin. Successful recovery captures the actual frame for reusable carry. Saving an active action is explicitly refused; durable midway action resume is not implemented.

The trusted native runner adds `tool-use-begin`/`tool-use-cancel` and `banjo.native-tool-use.v1` observations. Rust projects only the requesting actor's `own_tool_use`. Rust BeginUse/CancelUse contracts, pending outcomes, durable events and compiled functional-product import are still absent; these native operations are not exposed as arbitrary public passthrough. The browser still uses the retained host/controller.

## Matched material experiment

Windows; MSVC 19.44.35228, SDK 10.0.26100, Python 3.13.5, Rust 1.99.0. Native Release, dt = 1/240 s, 20 mm material cells, 100 mm columns, flat dry soil 0.75 m deep, no water/discharge. Head/handle are intact joined rigid components with 5,000 N/Nm fixing limits; handle is 40 × 320 × 40 mm. Four fixture widths are 120/280/200/160 mm (pick/shovel/hoe/unfamiliar), head height 80 mm and depth 40 mm, matching its declared point thickness. These vary actual geometry but remain common ground-contact configurations, not qualification of complete authored tool families.

Historical read-only fixtures retain the original 120 mm head depth and their unchanged mass/query measurements. Initial broad-head physical trials were blocked; productive fixtures explicitly use the 40 mm head. Collision exemptions were not enlarged to hide that failure. Narrowing this experiment does not establish that arbitrary broad assemblies are productive. Glass/oak/iron use the same conditions. Mass differences follow retained densities; these intact tests do not compare constitutive stiffness, grain, plasticity or fracture. Oak is a laboratory comparison, not restored to inorganic gameplay.

First complete native cycles from [recorded output](evidence/native-tool-use-2026-10-06.txt):

| Material / geometry | Tool mass kg | Native s | Contact work J | Released m³ | Raw unclosed work J |
|---|---:|---:|---:|---:|---:|
| Glass / pick | 2.24 | 0.183333 | 3.27504 | 0.0000405063 | −1.74765 |
| Glass / shovel | 3.52 | 0.208333 | 8.61270 | 0.0000773705 | −4.85644 |
| Glass / hoe | 2.88 | 0.191667 | 3.67905 | 0.0000226174 | −1.68411 |
| Glass / unfamiliar | 2.56 | 0.187500 | 3.74510 | 0.0000289828 | −1.95307 |
| Oak / pick | 0.6272 | 0.154167 | 1.44714 | 0.0000100275 | −1.27850 |
| Oak / shovel | 0.9856 | 0.158333 | 2.76637 | 0.0000152720 | −2.46051 |
| Oak / hoe | 0.8064 | 0.158333 | 2.17502 | 0.0000120382 | −1.95875 |
| Oak / unfamiliar | 0.7168 | 0.154167 | 1.83961 | 0.0000110170 | −1.65371 |
| Iron / pick | 7.05152 | 0.395833 | 9.84505 | 0.000424898 | +29.4727 |
| Iron / shovel | 11.0810 | 0.533333 | 12.8478 | 0.000396865 | +66.0836 |
| Iron / hoe | 9.06624 | 0.475000 | 11.9801 | 0.000450987 | +64.2150 |
| Iron / unfamiliar | 8.05888 | 0.429167 | 8.24432 | 0.000333592 | +57.3834 |

All twelve first cycles cut, recover, retain the whole grip and restore carry. Per-cycle tool mass difference <1e−10 kg; released source-cell volume/report difference <1e−9 m³, cell/body mass difference <1e−8 kg and terrain volume residual <1e−9 m³. One native second of idle carry produces no additional excavation. First-cycle wall costs in the recorded local run are 8.5–24.6 ms under competing verification workloads; this excludes orchestration, collection, rendering and ordinary input, and is not p95 or a gameplay speed claim.

Raw unclosed work is `mechanicalEnergyAfter − mechanicalEnergyBefore − handNetWork − actorWalkWork`. It omits other actor/support/reaction work, environmental/contact/damping/numerical accounts and source-to-debris potential transfer. **It is not a conservation residual.** Large positive iron values remain an investigation gate; volume/mass closure and bounded forces cannot certify complete energy transfer. Earlier [carry/work boundaries](runtime-carry-checkpoint.md#conservation-and-remaining-physics-boundaries) remain open. No conservation tolerance was relaxed.

Measured buried cancellations recover with zero release at the chosen early interruption. Drops during the same declared early contact close with native releases of 0.000629784/0.000292492/0.000579316 m³ for glass/oak/iron. Terminal reports equal released cells/terrain quantities and stop accumulating idle work. Bob's cancel cannot stop Alice's use; stale preview admission changes neither time nor carry.

## Repeated excavation remains a failing acceptance gate

The regression also performs real native collection from the actor's eyes, verifies exact cell identity/private native mass, then aims into the **same** column. Eight glass/oak repeats cut and recover. All four iron repeats finish with explicit `no_contact` and zero yield. No contact or material was fabricated to make them pass.

The deeper first iron cuts expose a geometry/patch conflict: 120–280 mm heads can rest on surrounding terrain while the controlled cutting patch is only 100 mm wide. Released fragments can also obstruct an uncollected hole. Ordinary collision must retain those obstructions; disabling neighboring collision or launching debris would conceal the defect. A centered target fixes boundary drift, but does not solve patch geometry.

The scoped CTest checks bounded termination, actual grip/custody, truthful refusals and quantity accounts, and prints each open repeat gate. The **separate strict acceptance command** below exits 1 for these four cases. That failed gameplay gate is explicitly retained and resolved for this publication only as an experimental boundary; useful repeated digging is not declared finished. Do not infer full-suite green from scoped CTest.

Next qualify actual swept head/patch clearance and supported finite multi-cell contact/attachment response, or provide an explicit preflight refusal with an actionable clearance plan. Follow with actual authored pick/shovel/hoe geometry, rock contact, sustained input and the dimensioned 10 ft excavation journey. Do not merely tune fixture widths, loosen assertions or assign fragment motion. The controller does not implement the required constitutive terrain replacement.

## Verification and reproduction

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_native_tool_use_tests banjo_tool_use_admission_tests banjo_pickup_admission_tests banjo_hand_stroke_tests banjo_ground_work_tests banjo_live_world_run banjo_c --parallel 4
ctest --test-dir build/local-cell-tools -C Release --output-on-failure -R "^banjo_(native_tool_use|tool_use_admission|pickup_admission|hand_stroke|ground_work)_tests$"
# Strict gameplay gate: currently FAILS four same-column iron repeats.
& build/local-cell-tools/Release/banjo_native_tool_use_tests.exe --require-repeat-yield
& "$env:USERPROFILE/.cargo/bin/cargo.exe" test --workspace --locked
& "$env:USERPROFILE/.cargo/bin/cargo.exe" clippy --workspace --locked --all-targets -- -D warnings
& "$env:USERPROFILE/.cargo/bin/cargo.exe" fmt --all -- --check
& "$env:USERPROFILE/.cargo/bin/cargo.exe" build --workspace --locked
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/local-cell-tools/Release/banjo_live_world_run.exe).Path
$env:BANJO_RUNTIME_ENGINE=(Resolve-Path build/rust-runtime/debug/banjo-runtime.exe).Path
python tests/runtime_native_tests.py -v
python scripts/check-source-registration.py
```

Verified after final linking: 15 Rust tests, 13 actual-native worker integration cases (18.907 s), five focused native CTest suites (8.24 s) and 309/309 source registration pass. Formatting, Clippy and local document-link targets also pass. The strict repeat command exits 1 for four iron cases, as recorded above. The worker integration exercises existing typed actions/private state; native functional tool cycles are the compiled C++ suite, not Rust/browser end-to-end gameplay. Real native-window/input, physical phone, full regression and replacement browser acceptance remain unverified. No D01–D06 helper or R01–R12 subsystem is retired. Main publishing does not install into `C:/play` or reset the owner's world.

Local rebuilt artifact SHA256: native runner `26effa78d291d6012bc699adf5f3d0845a691d6e8c9d820bf1d052b0452ec821`; shared library `12230fff44f34ed8ea1714606420afed02e2b7c1a7527fc7a491f1837ec61248`. These identify files, not complete compiled-source/ABI provenance.
