# Runtime rewrite: first implementation checkpoint

October 6, 2026. Based on the [rewrite audit](banjo-rewrite-audit.md), source baseline `64fafe56`. This checkpoint begins W00/W01 and W03. The replacement world worker and native pickup/use state machine remain next work; the Rust crate is not yet a playable game or a replacement for the current Python host.

## Implemented

- **Build identity:** `playground/build_manifest.py` hashes selected application/native source, served client assets including Three.js, and actual selected native binaries. `/api/build` and `/api/status` expose the credential-free manifest. Interaction traces carry its server-authoritative ID. Source capture occurs outside stepping; changing effective host mode refreshes configuration without rereading source.
- **Honest native provenance:** actual file hashes are recorded independently of checkout revision. Compiled-native source/numeric provenance and actual loaded ABI remain explicitly unrecorded; the current header's expected ABI is separate. A checkout revision does not certify the binary's source.
- **Safe regression runner:** `scripts/regression.sh` delegates to cross-platform `scripts/regression.py`. List/check modes discover CTest JSON without building or stopping processes. Check/run admission rejects unresolved test executables and missing declared native artifacts, including inline CMake environments. Ordinary/extended/filter/disabled exclusions are recorded. Actual runs retain discovery, JUnit and exit-code artifacts. Interruption cleanup targets only the runner's child tree.
- **Rust contracts:** a pinned Rust 1.99 workspace compiles versioned commands, IDs, SI rays/movement intents, actor/world authorization checks, explicit refusal/status values and outcomes. Unknown fields/operations, nonfinite/out-of-range inputs, oversized requests and client-supplied simulation steps are rejected. Join spawn requires a trusted host, not a client teleport permission. Native physics is not reimplemented in these types.
- **Build/test registration:** `BANJO_BUILD_RUST_RUNTIME=ON` creates the CMake `banjo_rust_runtime` target and CTest Rust contract gate. Host foundation tests run in CTest and the source-registration CI job; a separate CI job compiles/tests/formats/lints Rust. Build outputs stay under ignored `build/`; lockfile and toolchain are committed.

## Verification

Windows, MSVC 19.44 / SDK 10.0.26100, Python 3.13.5, Rust 1.99.0:

1. Configured `build/rewrite-foundation`, with native laboratories disabled and Rust runtime enabled. Built the named CMake Rust target successfully.
2. Three focused CTest entries pass: regression runner, build manifest and Rust contracts. The runner suite includes an intentional failing isolated CTest fixture to prove failure propagation; that fixture's expected failure is not a Banjo regression failure.
3. The manifest suite changes source, client dependency and native bytes independently; checks secrets/local paths remain absent; serves `/api/build` through a real isolated HTTP server with Host refusal; and checks effective configuration updates.
4. Existing room trace suite passes 26 checks, including correlated refusals, delivery failure, redaction and bounded retention. It now verifies a server build ID on browser observations.
5. Cargo contract tests, formatting and Clippy with warnings denied pass. Source registration remains 305/305. No native laws or binary behavior changed.

This is focused verification, not the full native/browser/phone regression. Discovery of the old partial native build still reports unready tests. The running `C:/play` demo has not been replaced by the Rust crate. The existing 8 MB/current-plus-previous diagnostic retention is not repaired by merely adding a build ID.

## Commands

```powershell
cmake -S . -B build/rewrite-foundation -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_HEADLESS=OFF -DBANJO_BUILD_PRECOMPUTE=OFF -DBANJO_BUILD_RUST_RUNTIME=ON
cmake --build build/rewrite-foundation --config Release --target banjo_rust_runtime
ctest --test-dir build/rewrite-foundation -C Release --output-on-failure -R "^banjo_(rust_runtime|regression_runner|build_manifest)_tests$"
python scripts/regression.py --build-dir build/local-cell-tools --list
python scripts/regression.py --build-dir build/local-cell-tools --check
cargo test --workspace --locked
cargo fmt --all --check
cargo clippy --workspace --all-targets --locked -- -D warnings
```

Rust is available through `%USERPROFILE%/.cargo/bin` on this Windows machine; its installation did not modify PATH. Use the absolute Cargo path until the shell is configured. The partial-build `--check` intentionally returns failure when selected native targets are unavailable. `--all` includes long/performance tests; a filtered ordinary run does not certify them.

## Next checkpoint

Finish W02 with indexed retained interaction records and redacted private history/export. Then implement W04's Rust world worker owning one clock and bounded command queue around the actual native process. Establish actor-scoped native spawn/move/pickup/drop observations and stable result/retry handling. Add native read-only pickup/use admission and the W05/W06 state machine before claiming the rewritten player loop works. Keep human/phone, thin laws, constitutive terrain and sustained digging speed as independent open gates.
