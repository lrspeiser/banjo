# Gameplay interaction diagnostics — October 6, 2026

## Observed problem

Audited main `29d42790` and the port-18890 demo running `3a2d5d6f`.
In the owner's existing world `d36ec8d4d52d49be9906973033b000a5`, stderr contains
five tool requests between 13:25:34 and 13:25:44 local time, taking 1519, 2042,
2063, 2043 and 2048 ms. The visible last result is “The tool is still moving
into position.” A later observed target is ready. Neither stderr nor
`room-frames.jsonl` preserves those clicks' targets/readiness/native outcomes.
The old evidence therefore does **not** establish that the failed click and
later green observation refer to the same target. Those clicks cannot be
reconstructed retrospectively.

An earlier 3,444,414 ms browser frame spans tab inactivity; it is not a measured
solver step of that duration. Frame reports already distinguish hidden tabs.

## Implementation

- Shared tools retain the exact mouse/touch press ray while queued. Keyboard
  actions and held repeats sample current sight; only one click may wait.
- Preview acceptance uses the same cell, layer, material, context and 25 cm
  observer validity as the drawn green target. The earlier additional 3 cm
  rejection discarded otherwise valid observations.
- Browser traces record target state changes/hidden targets, discarded or
  failed previews, pointer/keyboard presses, queue replacement, use start
  and displayed responses. A shared interaction ID links each use to the
  server. Preview readiness is an observation, not a material-release promise.
- Server traces independently record authenticated request receipt, current
  native hand/player, tool preflight, target/material/desired grip, refusal
  or native result, work/mass fields and timings, before sending a response.
  Exceptions and response disconnects retain distinct evidence. Browser
  provenance cannot overwrite server provenance.
- Turning/positioning refusals include actual point/grip, desired point/grip,
  direction, measured gaps, phase, wall duration and native elapsed time.
  This measures the bounded hand; it does not issue corrective commands.

Logs are local to each world's runs directory: `interaction-events.jsonl`
plus one `interaction-events.previous.jsonl`. Rotation starts at 8 MiB, with
one bounded batch of overshoot. Browser batches have at most 64 events and
12,000 serialized characters, prioritize uses over hover chatter, count
discarded events and retry within the same page/session after transport
failures. Events can still be lost if a page closes before its next four-second
report. Server outcomes do not depend on that report. Actor IDs are hashed;
session/auth tokens, headers, chat and arbitrary nested fields are excluded
by an explicit allowlist, and credential-shaped strings are redacted. Failed
logging does not cancel gameplay and warns at most once per minute per app.
No LLM call is added. A source fingerprint distinguishes the installed code.

## Verification

Windows, Python 3.13, MSVC Release, `build/local-cell-tools`, Lab off and
unchanged native binaries. Eight registered suites pass in 81.87 s: terrain
material, tool target client, native walk, Workshop ground tools, world
navigation, material delivery, tool use and room trace. The existing ground
tool suite retains glass/oak/iron comparisons. Added transport compaction and
response-disconnect cases pass in a four-suite rerun (6.16 s). JS syntax,
changed-file whitespace and 305/305 C++ registration pass.

Actual desktop and landscape-touch navigation cases use a normal native body
and live clock: walk away/back to pick up, retain the pick across reload,
then click distant ground. Each verifies a visible refusal and six matching
press/start/request/preflight/result/reply events, authenticated actor identity
and retained native hand. Existing native source-cell digging cases remain.
The added refusal checks do not teleport the player/tool or fabricate outcomes.
Unit checks cover valid small observer movement, changed cell/layer invalidation,
retained queued mouse rays, large-reply compaction, rotation, failed writes,
positioning failure measurements and disconnected responses.

## Boundaries and next work

Host/UI logging and input repair introduce no material law. Green still means
an admitted attempt; it does not certify reach through the full preparation
path or guarantee a cut. The cube-preview horizontal range and native
arm/working-point geometry still need a shared read-only readiness check.
Analyse the next linked failed attempt before changing forces or tolerances.
Native positioning, fast 10 ft excavation, constitutive fracture, full
momentum/energy closure, wear, water excavation, physical-phone acceptance and
the full regression audit remain open. No new physical validation is claimed.
