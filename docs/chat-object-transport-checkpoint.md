# Room-chat object-result transport

This checkpoint advances goals 6 and 9 without changing a physics law, MCP
handler, tool schema, room edit, or native simulation.

## Implemented

The model receives a full named-object list first. After that, a successful
room-authoring response may send only added/changed object rows plus an explicit
list of removed names and the complete current count. Every row is compared,
not only the object the call intended to change: unintended movements and other
rebuild side effects remain visible. All non-object fields, including placement
corrections, lost joints and refusals, remain intact.

Explicit reads and unclassified tools return full responses. Errors, ambiguous
or duplicate names, oversized lists, and mutations without a full snapshot reset
the baseline. Small replies remain full when a delta would be larger. The
baseline is isolated to one chat turn and bounded to 4,096 named objects. Frozen
JSON comparisons preserve numeric/boolean type changes and in-place mutations.

Only model transport is compacted. Native/MCP results and the server's per-call
audit transcript remain complete. Each turn returns and files original/sent
UTF-8 byte counts, delta counts and omitted unchanged-object counts. These are
function-call output bytes, not model tokens, total prompt bytes or billed cost.
The model is told how to apply deltas and request a fresh full describe_world.

## Verification

The new tests reconstruct every snapshot exactly through a sequence of edits,
check adds/removals/secondary movements, source immutability, ambiguous identity,
small outputs, type changes, turn isolation and full read/error handling. A
scripted chat performs real native room additions and checks that the model gets
a delta while its audit log retains the full actual object list. No paid model
service is called and actual LLM task-success equivalence is not claimed.

Measured fixture: start with 50 named objects and add 30. The 30 tool responses
fall from 184,730 to 12,061 UTF-8 bytes (93.47% smaller); all 30 reconstructed
object maps equal their source. Twenty-nine outputs are deltas, omitting 1,885
unchanged rows across the sequence. This fixture is not a forecast of user costs.

Local Linux verification: all 50 room-chat history tests passed, including
native construction/build and the new delta-transport integration case (326.1 s).
All 17 tool-parity tests and all 19 trace/logging tests passed. Source registration,
Python compilation, and changed-file whitespace checks also passed. The native
engine is unchanged from main 971261c. No tolerance was changed.

## Remaining work

Geometry generation and fracture computation are unchanged. This does not add
rendered visual feedback to the model, complete functional construction trials,
or make Workshop-to-world installation transactional. Large-world resolution,
complete AI benchmarking and other roadmap work remain separate.

## Published verification

The GitHub Actions gate passed all 11 pure transport checks, 17 tool-parity checks, 19 trace/logging checks and the 183-test fast Workshop gate. The native transport case is explicitly skipped in this compiler-free gate; all 50 room-chat tests, including that native case and native structure building, passed in the local Linux verification recorded above.
Run: https://github.com/lrspeiser/banjo/actions/runs/35295793270
