# Retained interaction history: rewrite checkpoint

October 6, 2026, Windows / Python 3.13.5. Extends the published Rust/build-discovery foundation at `7997bc1972d46020d84e1eada451de2ae1b5c569`. W02 now has an indexed diagnostic history; it is not the future simulation or paid-operation journal.

## Implemented

`playground/interaction_journal.py` retains already allowlisted, server-stamped interaction records in `runs/interaction-history.sqlite`. The existing current/previous JSONL files remain a recent view. SQLite writes are transactional; restart and repeated JSONL rotation preserve retained attempts. Logger failure is reported with a rate-limited warning and does not cancel gameplay.

The explicit policy is **14 days, 100,000 records and 128 MiB of JSON payload**, whichever limit is reached first. A single record is limited to 64 KiB; pages are 1–200 events. The payload budget excludes SQLite/index overhead and reusable free pages. Oldest-prefix eviction removes only what is needed to meet the budgets. Age limits also apply to reads from idle worlds; cleanup occurs on the next append. These are bounded diagnostics, not unlimited historical retention.

`GET /api/world/interaction-history` accepts `limit`, `before` and `attempt` once each. A named world's authenticated player identity determines the scope; a query cannot select another actor. Pages return descending sequences, a continuation cursor, actual oldest/newest available timestamps, retained count and policy. Host/origin, access gate and no-store rules remain in force. Cursor pagination can be used to export the retained records; no history UI or dedicated exporter has been added.

Records carry the server build ID introduced at `7997bc19`. Secrets/prompts are excluded by the existing trace allowlist; client observations remain labelled browser observations, not native truth. Source registration and CMake/CI registration include the new tests.

## Verification

- Seven journal tests pass: repeated rotation/restart, cursor pages, actor/world separation, count/payload budgets, expiry/invalid pagination, empty read, logging failure and the real HTTP route. The HTTP fixture supplies a mocked authenticated principal to isolate route scope; it does not independently certify the authentication implementation.
- The existing room trace suite passes all 26 checks after integration.
- Four focused CTest entries pass in `build/rewrite-foundation`: runner, build manifest, journal and Rust contracts. Source guard passes 305/305. No native laws or binaries changed.
- GitHub CI at `7997bc19` passes the new Rust and source-registration jobs; the broader Workshop job fails its existing Camp stool mass assertion (`2.5088` expected, `3.9311` actual in `workshop_tabs_tests.py:155`). That test/product contract is outside this diagnostic change and remains unresolved; no full CI green is claimed.
- An isolated 1,000-record Windows run measured append median 5.90 ms, p95 8.30 ms, a 200-record page 8.33 ms and a 368,640-byte database. This is a small local diagnostic benchmark, not concurrent-load or simulation performance qualification. Appends currently run synchronously under the trace lock; moving diagnostics off the interaction request needs bounded delivery/failure semantics.

## Open boundaries

Older JSONL files are not imported, and unrecorded historical failures cannot be reconstructed. Read-only history does not imply exact simulation replay, inventory/economy transactions or durable command idempotency. The expanded native readiness fields and viewer/export workflow from W02 remain open. The running `C:/play` demo is unchanged; this checkpoint does not fix pickup, excavation or phone behavior. W04 next introduces one Rust clock/command owner around the actual native process.

```powershell
python tests/interaction_journal_tests.py -v
python tests/room_trace_tests.py -q
ctest --test-dir build/rewrite-foundation -C Release --output-on-failure -R "^banjo_(rust_runtime|regression_runner|build_manifest|interaction_journal)_tests$"
python scripts/check-source-registration.py
```
