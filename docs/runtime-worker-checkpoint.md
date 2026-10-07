# Rust world worker: native-backed experimental checkpoint

October 6, 2026. Source baseline `abd3b152` follows the [audit](banjo-rewrite-audit.md), [contracts/build identity](runtime-rewrite-checkpoint.md) and [retained diagnostics](interaction-history-checkpoint.md). This implements a bounded W04 worker slice. It does not replace the browser's Python host, complete W04–W06 or retire the existing clock.

## Implemented

`runtime/src/main.rs` starts one owned native process and accepts typed requests over **trusted host stdin**. `world.rs` is the sole mutable command/time owner; `native.rs` translates its admitted operations into the existing C++ runner protocol. Native Jolt/material laws stay in C++; no Rust physics crate or alternate simulation fallback is introduced.

- The worker owns a 60 Hz deadline and requests four native steps of **1/240 s** per batch. Requests cannot specify step duration/count. Accepted ticks derive from the native time delta; short/rolled-back batches do not become successful time. An impossible time delta or kernel exit faults the worker. Slow deadlines are counted; no large-dt jump or unlimited catch-up is used.
- Commands carry actor/world/request IDs, input sequence and optional command revision. The trusted principal must match the payload scope. Host-only Join creates a real native avatar; Inspect observes it, Move sets a bounded 250 ms native walking intent, Drop checks the native hand is empty, and Leave releases/removes the native actor. Physics time and command revision are separate counters.
- A bounded 64-request input queue, 16 KiB frame limit, 32 MiB native reply limit and bounded 8-frame/2 MiB-per-frame output path prevent unbounded pipe accumulation. Native replies have a 10-second timeout. Overlong input is drained as one refusal. A stalled output closes this experimental world rather than accumulating results indefinitely.
- Up to 4,096 in-memory command receipts retain retry identity; conflicting IDs are refused and exhaustion refuses new commands rather than forgetting previous effects. **This is not durable idempotency.** The original receipt tick/time accompanies an observation explicitly stamped with its current tick/time. No paid fabrication, inventory transfer or market operations are admitted.
- Observations project public body poses and native avatars plus only the requesting actor's hand. Other hands/cargo/private carried accounts are not forwarded. The local ready frame records the native PID and selected executable-file SHA256; compiled-source provenance and actual ABI remain unrecorded.
- Startup/timeout/shutdown owns one child handle. There is no process-name kill or arbitrary native operation pass-through. Cargo and the named CMake target compile the new modules/binary. CTest and native-build CI register the real integration gate; missing required artifacts fail rather than skip it.

**Pickup is deliberately rejected with `unsupported_capability`.** W05 must provide native read-only eligibility and actual grip confirmation. This worker does not report success merely because the legacy `wield` operation accepts a name.

## Verification and boundaries

Windows / MSVC 19.44 / SDK 10.0.26100 / Python 3.13.5 / Rust 1.99.0. Rust uses the dev profile; the reused native runner is Release:

- Ten Rust contract/orchestration checks pass, including authority, private projection, retries/conflicts, native rollback/fault accounting, revisions and receipt exhaustion. Formatting and Clippy with warnings denied pass.
- Eight required real-native integration tests pass: idle clock, opposite-direction movement by two independent 70 kg actors, retry/conflict/authority/departure, overlong/invalid input, honest unsupported pickup, owned shutdown preserving an unrelated process, kernel death without fallback and matched material fixtures.
- Identical 0.2 m cubes at 0.05 m native resolution retain **glass 20 kg, oak 5.6 kg, iron 62.96 kg**, with the same dt. This checks native material-derived mass/orchestration only. It does not validate bending, grain, fracture, wear, locomotion reactions, stiffness differences or full momentum/energy conservation. No material law/tolerance or native source/binary changed.
- Five focused CTest entries pass. Source registration remains 305/305. This is not the full native/browser/phone regression. The existing Workshop CI Camp stool mass assertion remains unresolved.
- Selected native file: `build/local-cell-tools/Release/banjo_live_world_run.exe`, SHA256 `e2be0e0a22ef0ba630cf2d055b3d54080dcf516ae60239bc956ae5524a5fcbd7`. Its build-source provenance is not inferred from today's checkout. CI is configured to build its own native target for this integration gate.

The CLI pipe trusts its host; it is **not an authentication server**. A future gateway must authenticate principals and reserve host actions. There is no browser bridge, exact save/reload, durable event journal, player inventory, use controller, renderer resync or move coalescing yet. Observations may omit geometry on native pose-only replies; a client geometry/delta store is still required. Native waits/refusals/contacts need a retained event adapter before UI integration. The running `C:/play` demo is unchanged.

## Reproduce

```powershell
cmake -S . -B build/rewrite-foundation -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_HEADLESS=OFF -DBANJO_BUILD_PRECOMPUTE=OFF -DBANJO_BUILD_RUST_RUNTIME=ON "-DBANJO_RUNTIME_NATIVE_EXECUTABLE=C:/Users/henry/Documents/ChatGPT/Banjo/build/local-cell-tools/Release/banjo_live_world_run.exe"
cmake --build build/rewrite-foundation --config Release --target banjo_rust_runtime
ctest --test-dir build/rewrite-foundation -C Release --output-on-failure -R "^banjo_(rust_runtime|runtime_native|regression_runner|build_manifest|interaction_journal)_tests$"
python scripts/check-source-registration.py
```

When the normal CMake native runner target exists, its target path is selected automatically; the external executable option is only for isolated reuse. The next checkpoint is W05 native admission and confirmed generic pickup/drop, followed by W06 shared tool-use control. Existing runtimes remain until equivalent ordinary human/touch, multiplayer, persistence and performance gates pass.
