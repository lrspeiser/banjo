# Material lab: bounded fresh experiments

October 6, 2026; source base main `ae7abe1e`. This extends the
[first replacement client](material-lab-ui-checkpoint.md) from a fixed replay
viewer to deliberate, freshly computed CPU experiments. It advances the staged
UI and authoring boundaries in W12/W13; the full W00–W17 rewrite remains active.

## Try it

Open `http://127.0.0.1:18891/`, choose **Load strength**, then **Run experiment**.
Each request computes six new glass/oak/iron load-and-release/pull responses.
Select an interaction/material and play or scrub the exact returned samples.
Changing a control does not run a solver or replace the previous result.
No periodic provider/solver request, player-world mutation or outcome cache exists.

The load selector admits 25%, 50%, 100% or 125% of the original declared force
vectors. The result always labels the force actually computed, even while a
different request is pending or refused. Completion replaces the display only
after the versioned result/request/cell/topology contract passes. Busy/failed
requests retain the last result and permit a deliberate retry. Starting another
run starts from zero motion/damage, not from the last displayed damaged block.

This is a live **isolated experiment command** followed by sampled replay. It is
not continuous interaction with a game world, a saved material edit, or a general
custom material/product compiler. There is no finite source-body contact or new
constitutive model in this checkpoint. Oak remains laboratory-only.

## Command, execution and authority

- Request `banjo.material-lab-request.v1` contains exactly `schema` and numeric
  `force_scale`; unsupported fields, booleans, duplicates and other scales refuse.
- Recording v2 carries the admitted request. The old fixed v1 recording is
  explicitly incompatible; regenerating the disposable baseline is the migration.
  Player/save formats are untouched.
- Result `banjo.material-lab-result.v1` reports completion, a unique execution ID,
  wall duration and actual native/request/output fingerprints. The TypeScript
  boundary verifies the submitted scale and complete recording before installation.
  Fingerprints are reported provenance, not client cryptographic attestation or
  a proof that a checkout revision produced a binary.
- `POST /api/experiments` is the only execution route. It accepts at most 1,024
  bytes of JSON from the exact loopback Host/Origin and same-origin fetch context.
  Six named assets remain the only GET paths; private workspace files, arbitrary
  commands/paths, legacy routes and game mutations are unavailable.
- A nonblocking single execution slot rejects contention with HTTP 429, without
  a waiting queue. Each admitted job launches the fixed compiled recorder with
  temporary request/output files; no shell or client-supplied executable is used.
  The slot releases on success, failure or timeout. A subprocess has a six-second
  budget, bounded output and cleanup; client observation has an eight-second limit.
  A disconnected observer does not turn a laboratory run into a paid effect.
- Public session authorization and the Rust world owner are still unimplemented
  for this view. Exact loopback origin protection is not public-user authentication.
  This temporary laboratory adapter must be replaced by the common compiler/job
  gateway when its artifact, authorization and lifecycle gates qualify. It must
  never grow a second route for gameplay commands or stock/energy mutations.

## Matched physical measurements

Every scale retains the same geometry, materials, seed, clamps and clock described
in the [original physical conditions](material-lab-ui-checkpoint.md#declared-physical-conditions):
125 cells, 50 mm resolution, 100 ns steps, 512 loaded then 128 unloaded steps,
21 exact frames, 50 kJ cumulative positive-work ceiling, no gravity/damping.
Only the prescribed external force changes. There is no invented launch velocity.

| Pull load | Glass work J / failed bonds / free cells | Oak work J / failed bonds / free cells | Iron work J / failed bonds / free cells |
|---|---:|---:|---:|
| 25% | 219.684701 / 100 / 1 | 268.774230 / 9 / 0 | 3.790201 / 0 / 0 |
| 50% | 989.345937 / 100 / 1 | 2,856.963656 / 56 / 1 | 15.146507 / 0 / 0 |
| 100% | 4,110.255487 / 96 / 1 | 13,728.972518 / 56 / 1 | 197.689414 / 2 / 0 |
| 125% | 6,457.644802 / 96 / 1 | 22,008.911724 / 56 / 1 | 754.529328 / 10 / 0 |

Gentle-load cases remain connected without failed bonds at all admitted scales.
Failed-bond counts need not be monotonic: detachment changes the subsequent
dynamic loading history. These are observations of the existing uncalibrated
central-bond reference, not evidence of real glass fracture, oak grain or iron
plasticity. Full source/support/numerical energy and linear/angular accounts are
retained per frame, with unchanged 1e-8 SI residual gates. Maximum recorded energy
closure is 1.330136e-11 J after separately retained integration-error attribution.

[Evidence](evidence/material-lab/live-acceptance.json) includes all 24 material/input
cases, native/workspace fingerprints and source/support ledger residuals. Four
sequential six-case jobs took 1.02–1.08 s; observed HTTP decode totals took
1.21–1.31 s. Windows x64, Intel Core Ultra 9 285K (24 cores/logical processors),
MSVC 19.44.35228, SDK 10.0.26100, native Release, Python 3.13.5, Node 22.18.0,
TypeScript 5.9.3. Four local samples are not a latency percentile, realtime physics,
two-player capacity or a 10 ft excavation benchmark.

## Verification report

Story: choose load → bounded local API → fresh compiled CPU solver → validated
samples → visible response, with truthful refusal and retry.

| Boundary | Evidence |
|---|---|
| UI/input | Ordinary browser selects 50%; pending controls disable; displayed previous force stays accurate |
| Client/API | Server logs actual POST 200 and competing 429; cross-origin/rebinding/oversize/duplicate negatives refuse |
| API/solver | Actual native subprocesses run all admitted scales; initially identical cell state is retained; measured final work changes |
| Result/identity | Distinct executions return matching physical frames for identical CPU input; request/native fingerprints checked; mismatched client result refuses |
| Response/UI | 50% completes in 1.12 s; busy preserves it; retry completes at 125%; portrait run completes in 1.28 s and scrubs to frame 20 |

Ten actual-native/host tests, four Node contract groups, strict compilation,
three focused CTest entries and 311/311 source registration pass. The compiled
recorder target builds. Timeout handling uses an injected `TimeoutExpired` to
verify HTTP 504 and slot recovery; this is not a measured native six-second stall.

[Desktop result](evidence/material-lab/live-desktop.jpg),
[portrait result](evidence/material-lab/live-portrait.jpg) and
[busy refusal](evidence/material-lab/live-busy.jpg) record the ordinary browser.
The busy image predates a small refusal-wording cleanup. Final page has no console
errors/warnings; the earlier deliberate refusal produced the expected HTTP 429.
390×844 portrait and 844×390 landscape show no horizontal overflow. Physical
phone/touch and public deployment are not tested. The retained World on 18890 is
unchanged. Full regression is not green; four strict iron repeats remain failing.

## Remaining rewrite work

Qualify actual finite contact, release/collision/settling and conservative world
handoff; then expose the same bounded compiler/worker controls through the shared
World/Inventory/Build/Progress client. Complete authenticated ownership, durable
state, ordinary pickup/repeated use/collect/manufacture/restart and physical-phone
journeys before retiring the old game. Custom materials, generated shared DTOs,
terrain/water/wear, useful fast excavation, performance and all other audit gates
remain active. This experiment adapter closes none of those release requirements.
