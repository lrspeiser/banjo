# Native tool-target admission: experimental rewrite checkpoint

October 6, 2026, source baseline `02a764bb`. This is a W06 prerequisite in the isolated Rust/native worker. The browser demo still uses the retained host. Preparation, acting, recovery and their physical outcome events are not implemented by this checkpoint.

## Subsequent controller checkpoint

Admission was published on main at `08a05c2b`. [The subsequent native-use checkpoint](runtime-tool-use-checkpoint.md) replaces the thirteen-point desired preview with a three-point short contact plan and implements native phases. Historical tables below describe the frozen earlier experiment. Repeat clearance, typed Rust use/import and browser migration remain open.

## Implemented behavior

`LiveWorld::toolUseAdmission` is a read-only native query. It shares pickup's ray validation: a joined native actor, finite normalized direction, maximum two-metre ray and origin within 0.2 m of the actual actor's eyes. It requires a wielded assembly, necessary actual weight/load-moment support, no competing stroke and exactly one attached, connected tool point belonging to its held root. Tool display names select no behavior.

The first actual ray hit decides the target. Own avatar and held assembly are ignored; another solid body blocks the ground behind it. The query reads terrain region, column, matter revision and actual surface height. Only exposed top targets within 25 mm of that height are supported here. Wall and tunnel hits are refused rather than silently redirected to an unrelated top. Actual point hardness and the existing ground regime determine whether the native law admits contact. Wet regimes and too-soft points on rock return explicit reasons.

An admitted query returns the existing native desired stroke plan, with every planned grip target checked against the physical shoulder reach. This is a desired actuator path, **not** simulation, obstacle-sweep clearance certification, contact, granted work or promised yield. It still uses the older swing planner's thirteen-point path; the new short-contact preparation/use/recovery controller remains next.

The runner advertises `tool_use_admission_version=1`. Rust exposes only the typed `PreviewToolUse` action and validates a versioned `ToolPreview` response. Actor scope, finite units, supported reasons and result consistency are checked. No hit stays `null`, with absent terrain fields, instead of displaying invented coordinates or column zero. An eligibility refusal is a successfully observed fact, not a successful tool action. Looking does not increment the world revision or simulation time. Retry IDs do not repeat the native query; only the requesting actor sees its preview.

The transitional native adapter still retains the latest reply rather than a durable preview/event history. Existing hot receipt capacity remains 4,096; repeated observations consume it. Generated native/TypeScript schemas, stable artifact import, retained topology, worker event journaling, authenticated browser ingress and durable receipts remain open.

## Verification and quantitative scope

Windows / MSVC 19.44.35228 / SDK 10.0.26100 / Python 3.13.5 / Rust 1.99.0; native Release and Rust dev. No constitutive, contact, extraction, friction or strength law changed. Preview itself has **no timestep**. The scene uses 20 mm material cells and 100 mm terrain columns; each fixture declares its actual connected head, handle and point.

All twelve matched material/family queries preserve the complete native snapshot byte-for-byte, simulation time zero, carry authority and empty contact/debris/removal accounts. Each returns thirteen desired path points. Measured mean query times below are twenty calls per fixture, one local run; they exclude process, queue and network overhead and are not latency percentiles.

| Material | Pick / shovel / hoe / unfamiliar assembly mass kg | Mean query time range ms |
|---|---|---|
| Glass | 4.16 / 8.00 / 6.08 / 5.12 | 0.005960–0.007280 |
| Oak | 1.1648 / 2.24 / 1.7024 / 1.4336 | 0.005500–0.011150 |
| Iron | 13.0957 / 25.184 / 19.1398 / 16.1178 | 0.005510–0.005605 |

Different masses follow the retained densities. These are eligibility tests, **not** stiffness, grain, plasticity, fracture, wear, productive tool-family use or fast excavation measurements. Oak remains a comparison laboratory material, not restored to inorganic gameplay. Zero removal in a query proves no mutation; it does not close a physical conservation ledger.

Negative native cases cover spoofed origin, nonunit direction, excess reach, empty sky, multiple points, empty hand, absent actor, solid occlusion, an oak point on rock and water-covered terrain. A test occluder initially used 150 mm dimensions on a 20 mm grid and failed fixture compilation; it now uses 160 mm, preserving the occlusion assertion without changing source geometry admission.

Fifteen Rust contract/orchestration tests and thirteen actual-native worker tests pass. The worker test confirms empty-hand and unconfigured-body refusals through the real protocol, private actor projection and successful native pickup. It does not import an authored functional product: that capability remains C10. Four registered native suites cover new admission plus retained pickup, hand stroke and ground work. Formatting, Clippy and 307/307 source registration pass. An early integration run used the previously linked native executable while its replacement was still building and failed typed response validation; after linking completed, the full thirteen-case run passed. No fake native fallback or relaxed assertion was used.

Retained material work/conservation boundaries are recorded in [carry](runtime-carry-checkpoint.md#conservation-and-remaining-physics-boundaries). New preview checks introduce no work, momentum, topology or material transfer. Full actor/support/contact/numerical closure, wet laws, safe acquisition clearance, standing yaw, idle excavation prevention through the new worker and sustained digging speed remain required. Neither full regression, interactive native-window nor physical-phone qualification is claimed.

## Reproduce and next gate

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_tool_use_admission_tests banjo_pickup_admission_tests banjo_hand_stroke_tests banjo_ground_work_tests banjo_live_world_run banjo_c --parallel 4
ctest --test-dir build/local-cell-tools -C Release --output-on-failure -R "^banjo_(tool_use_admission|pickup_admission|hand_stroke|ground_work)_tests$"
& "$env:USERPROFILE/.cargo/bin/cargo.exe" test --workspace --locked
& "$env:USERPROFILE/.cargo/bin/cargo.exe" build --workspace --locked
& "$env:USERPROFILE/.cargo/bin/cargo.exe" clippy --workspace --locked --all-targets -- -D warnings
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/local-cell-tools/Release/banjo_live_world_run.exe).Path
$env:BANJO_RUNTIME_ENGINE=(Resolve-Path build/rust-runtime/debug/banjo-runtime.exe).Path
python tests/runtime_native_tests.py -v
python scripts/check-source-registration.py
```

Local artifact SHA256: native runner `759887c0a0917c6b7a4c8c3476da369b1c5eaee1dedc38f4541fcf7bd741a8e`; shared library `b1f0e88e912c7de1f2783f9beeabac938c167c5f1bdaac6ac65ec52135737e37`. Compiled-source provenance remains unrecorded in the protocol; a file hash is not that provenance.

Next use this admission at action start, revalidate target revision, implement native-time preparation/contact/recovery with bounded actual hand forces, keep idle carry from cutting, and emit measured outcomes. Qualify repeated pick/shovel/hoe/unfamiliar journeys and cancellation/peers/rollback before retiring Python preparation or browser readiness (R02/R03). The full W00–W17 scope remains active. No D01–D06 helper or R01–R12 subsystem is deleted here. Main publication does not install the new worker into `C:/play` or restart/reset the owner's world.
