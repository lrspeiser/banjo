# Rust tool use commands and retained native results

October 6, 2026. Experimental implementation following main `020e4f5d` and the [native controller checkpoint](runtime-tool-use-checkpoint.md). The isolated Rust worker now owns typed begin/cancel requests, waits for accepted native completion, and retains each original command's measured result. The browser remains on the retained host. Useful repeated excavation, durable state and the complete W00–W17 rewrite remain open.

Implementation, tests and structured evidence are published on GitHub main at `f88abc7df8dfa92b0336934f471a96f2a5d56960`. The subsequent [matched pit experiment](native-pit-clearance-checkpoint.md) records a controlled physical-width contrast and the remaining coupled-contact requirement.

## Command ownership and completion

`begin_tool_use` accepts only a bounded eye ray. Native code recomputes actor, grip, working-point, material, reach and target eligibility; clients cannot supply a tool point, motion path, work quantity, physics step or snapshot path. The native process must advertise `native_tool_use_version: 1`. The Rust adapter validates the typed `banjo.native-tool-use.v1` state, including phase, time, quantities and refusal vocabulary.

An accepted begin returns `pending`. The original command completes only after accepted native time, a matching tool/point/start identity, a finished physical phase, and closure of its open contact. Repeated begin while pickup/use is pending returns `action_in_progress`. Positive release with no native failure completes as `applied`; zero release is an explicit `no_contact` or `insufficient_work`, and native failures remain failures even if some material was released. The receipt retains `tool_use_result` separately from the latest actor-private snapshot. Retrying the original command cannot start another cut or replace its measurements with a later action.

`cancel_tool_use` names the original use command ID and is actor-scoped. Its `applied` acknowledgement means cutting authority has stopped and recovery has been requested. The original begin stays pending until physical closure, then reports `cancelled` with its actual measurements. Peer/stale IDs cannot cancel a newer use. Drop releases the actual grip while preserving the pending original result until its final native contact closes. Leave returns `action_in_progress` during this interval; cancel/drop, await closure, then leave. Gateway disconnect cleanup remains a separate requirement.

Malformed, missing or replaced native action state faults the worker and rejects all pending uses. A stalled use faults after 2,400 attempted ticks (10 nominal seconds at 1/240 s), without fabricating a successful recovery or accepted time. Pending pickups, uses and undelivered completions share a 64-entry admission bound. The existing 4,096 receipt limit and slow-observer/world shutdown behavior still require durable/coalesced replacement.

## Contact retention repair

The native runner clears closed ground contact logs after each reply. Recomputing a recovering action from those transient logs erased earlier cut results. The first real Rust/native tool matrix reproduced this failure in all twelve cases despite successful direct C++ cuts.

Ground meetings now receive monotonic IDs within the native process. Each use retains the latest report for each matching meeting, updates open meetings without double credit, and keeps closed measurements across runner replies. `contact_pending` distinguishes a terminated controller from a contact that still needs physical closure. C++ tests clear logs during recovery, repeat observations, and check that quantities/work remain stable. IDs are process-local, not durable events or restart identities. A use exceeding 1,024 retained meetings terminates with `capacity_exceeded`; this bound is an experimental reporting safeguard, not a qualified event-storage design. Constitutive laws, collision exemptions and actuator limits are unchanged by this repair.

## Prepared native fixtures

The trusted worker CLI accepts `--initial-snapshot PATH` for an exact native whole-state restore. Startup requires native time zero and no existing native actors. This supports compiled functional fixtures with native fixed joints and declared working/grip points; it does not resume player receipts, inventory or a running world. Snapshot paths are host configuration only, never player payloads. Native partial/fallback restore is refused. A versioned compiled-product registry, manufacturing import and durable world restart remain necessary.

## Verification

Windows, MSVC 19.44.35228, SDK 10.0.26100, Python 3.13.5 and Rust 1.99.0. Native Release; fixed dt 1/240 s. The [structured evidence](evidence/runtime-tool-use-2026-10-06.json) records selected executable/library hashes and the twelve worker results.

- 23 Rust tests pass, including multi-actor fault completion, snapshot startup restrictions, pending/closed outcomes, retries, scoped cancellation and malformed measurements. Formatting and Clippy pass.
- 16 actual-native worker integration tests pass. The functional test contains twelve glass/oak/iron × pick/shovel/hoe/unfamiliar geometry cases, using ordinary join, native pickup, typed use and original-command retry. Separate cases exercise cancel/leave and drop during an observed open bite.
- Five focused native suites pass: pickup admission, use admission, native tool use, hand stroke and ground work. Source registration passes 309/309 without exclusions.
- The strict `--require-repeat-yield` command still exits 1 for four iron fixtures. This failing gameplay gate is retained and documented, not treated as full regression success.

The worker fixture uses 20 mm material cells, 100 mm dry soil columns, 0.75 m soil depth, no water/discharge, 40 mm head depth and the four declared head widths from the native checkpoint. Glass/oak/iron have matched declared geometry, laws, resolution and timestep; mass differs by retained density. Actual worker scheduling gives different initial physical stepping histories, so these measurements do not establish identical trajectories or cross-run determinism. A normal zero-velocity move declares standing before pickup. Long idle posture remains unqualified. Oak remains a comparison laboratory material, excluded from inorganic gameplay.

All twelve first uses finish with positive native release and closed contacts. These are shallow dry-soil experiments, not rock progression, complete authored tool-family behavior, fracture/wear qualification or a 10 ft digging-speed result. Contact work and source quantity are retained; they do not close the complete energy/momentum/reaction pipeline. The prior large positive iron unclosed-work values remain an investigation gate. No conservation tolerance changes are made.

## Remaining work

1. Resolve the conflict between wide physical heads and narrow deep excavation patches while preserving ordinary collision and actual work; qualify repeated collection/use and sustained excavation speed.
2. Complete reaction, source/debris energy and numerical correction accounting; couple conservative terrain/material laws and adaptive representation through comparative tests.
3. Add durable intent/result/event storage, restart identities, private inventory and compiled-product import before browser migration.
4. Connect an authenticated gateway and topology-aware client, then verify actual desktop/touch pickup, carry, repeated use, collection, manufacture and reload.
5. Qualify ordinary interactive input, physical phones and the full regression/build set. Retire duplicated controllers only after migration gates pass.

No D01–D06 helper or R01–R12 subsystem is removed. `C:/play` remains the older demo on port 18890; this checkpoint neither installs the replacement nor resets player worlds.

## Reproduction

```powershell
& "$env:USERPROFILE/.cargo/bin/cargo.exe" build --target-dir build/rust-runtime
& "$env:USERPROFILE/.cargo/bin/cargo.exe" test --target-dir build/rust-runtime
& "$env:USERPROFILE/.cargo/bin/cargo.exe" fmt --check
& "$env:USERPROFILE/.cargo/bin/cargo.exe" clippy --target-dir build/rust-runtime --all-targets -- -D warnings
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/local-cell-tools/Release/banjo_live_world_run.exe).Path
$env:BANJO_RUNTIME_ENGINE=(Resolve-Path build/rust-runtime/debug/banjo-runtime.exe).Path
python tests/runtime_native_tests.py -v
ctest --test-dir build/local-cell-tools -C Release --output-on-failure -R '^banjo_(pickup_admission|tool_use_admission|native_tool_use|hand_stroke|ground_work)_tests$'
build/local-cell-tools/Release/banjo_native_tool_use_tests.exe --require-repeat-yield
python scripts/check-source-registration.py
```
