# Finite-stock fabrication

This checkpoint adds a generic lumped process and an atomic transfer into the
native world. It advances gameplay items 2, 3, 16 and 27. It does not complete
those broad capabilities or claim physical drilling, general assembly, casting,
repair, machining calibration or automated production.

Use the HTTP/MCP operations below against the existing main world or the separate
`fabrication` room. Explicitly declare the process once, quote a Workshop candidate,
start it, advance native time, then preview and place the finished workpiece.
Native terrain bounds placement. The old `/fabrication` page is removed (404);
the Lab exposes reviewed remake/start/progress/placement for a carried source
when a workbench is already configured and funded. Inventory exposes pending
stock recovery controls. Ordinary starter workbench declarations and UI stock/
charger funding remain unfinished. Another live world view can advance the shared
clock while a process runs.
Configuring a funded station retains surveying, excavation, tool use and machine
controls; free authoring operations remain restricted. The [30-item priority list](physics-gameplay-backlog.md) and
`GET /api/gameplay/capabilities` retain incomplete acceptance gates.

## Operating law and boundary

The process owns finite, initially cold material stocks, one work position, a
finite buffered energy supply, a heat capacity and a prescribed ambient boundary.
The buffer may be seeded explicitly or charged by the metered native transfer
below. It is not attached to a native circuit and cannot claim the same battery twice.
The process parameters are declared engineering inputs, not calibrated machining
properties. Nothing chooses a law from a product name.

A quote compiles the candidate's full Workshop Matter cell set. Product mass is
occupied cell count × cell volume × engine catalog density. Input stock must
cover that mass; completed offcuts retain the difference. Only supported,
connected, single-material lattice products are admitted, including authored fixed/bearing assemblies whose fixed groups compile separately. The
candidate must declare `parameters.primary_use`. Assemblies additionally name `primary_use_component` and map every interaction point ID to its owning component in `interaction_point_components`. Construction labels,
interaction points and the use program travel through the existing installer.

Required useful work is `stock_kg * work_j_kg`. Supplied energy is converted to
useful process work with `efficiency`; **all** supplied energy eventually heats
the station or crosses its ambient boundary. Useful work is a progress measure,
not another energy store. Output remains at the cold-stock reference temperature
293.15 K. Native output thermal state is admitted atomically at installation; station heat remains isolated. No warm feedstock or chip thermal distribution is claimed by this model.

For station heat H above ambient, heat capacity C and cooling conductance G:
`dH/dt = P - G*H/C`. Each constant-power segment is integrated analytically.
Supply exhaustion, work completion and the temperature ceiling split segments.
At the ceiling, admitted power cannot exceed cooling power. An insulated hot
station stalls. Native call batching does not alter the process law.

Only accepted native elapsed time advances work and cooling. Wall-clock absence
does nothing. The native runner uses 1/240 s steps in bounded half-second batches.
A native refinement/time-admission stop refuses completion of the requested wait.

## Transactions and persistence

Start reserves the whole workpiece immediately. Pause retains that material,
completed work, heat and spent energy. Resume continues from it. There is no
refund or reset operation. Only one job runs at once; another may occupy the
station while a paused workpiece is retained. At completion, offcuts enter a
separate material account and the finished product remains uninstalled.

Quote and preview do not spend stock. Preview verifies exact native geometry,
clearance and state carry. Commit repeats those checks, verifies the funded
candidate including its primary-use declaration, marks its mass as transferred
out, and writes the native world and process record in one atomic room save.
Only then does it replace the live process. A failed installation save leaves
the old native world and finished workpiece intact.

`revision` prevents concurrent starts from spending the same observed stock.
`request_id` makes configure/start/pause/resume/commit retry-safe; reuse it
unchanged after an uncertain response. Start/pause/resume retain all receipts
(up to 4096, then refuse); jobs are limited to 128 and never forgotten. Installation
receipts use the existing 64-receipt window, but an installed job permanently
prevents a second transfer after that window. A retry with changed fields refuses.
Wait is an elapsed-time action, not retry-safe: read state after a connection
failure before deciding whether to wait again.

The dedicated room refuses free authoring, fresh resets, incompatible saved
specifications and partial native restores. Scene switching and restart retain
both halves. Native installed material may subsequently move or fail under the
engine's existing laws; the process ledger records the transfer, not the later
world's heat or fracture energy. Local closure is not whole-world qualification.

## HTTP and MCP

Every POST uses the existing same-origin `X-Banjo-Token` from `GET /api/status`.
Open with `POST /api/world/open {"scene":"fabrication"}` for the dedicated room,
or use an existing persistent room such as `world`; keep the returned `scene`
and `session`. All routes below begin `/api/world/fabrication/` and require
that current `scene` and `session`. Unknown fields refuse.

| Route suffix | MCP tool | Additional required fields / result |
|---|---|---|
| — | `fabrication_open` | No arguments. Opens/rejoins the same browser room without supplying resources. |
| `state` | `fabrication_state` | None. Returns `configured`, `cell_m`, process state and audit without advancing time. |
| `configure` | `fabrication_configure` | `settings`, `request_id`. Explicit one-time initial resources and law. |
| `quote` | `fabrication_quote` | `candidate`, `stock_kg`. Exact material mass, offcuts, required work, minimum duration, available stock, affordable flag. |
| `start` | `fabrication_start` | `candidate`, `stock_kg`, `revision`, `request_id`. Trusted compilation and reservation; request ID is the job ID. |
| `pause` | `fabrication_pause` | `job_id`, `revision`, `request_id`. Keeps the intermediate workpiece. |
| `resume` | `fabrication_resume` | `job_id`, `revision`, `request_id`. Continues retained work. |
| `recover` | `fabrication_recover` | `material`, `mass_kg` (0.000001..10000), `revision`, `request_id`. Moves available cold offcuts into same-material stock, with no work/energy refund. |
| `retrieve_ground` | `fabrication_retrieve_ground` | `lot_id`, `sand_m3`, `soil_m3`, `revision`, `request_id`. Positive total bounded by `raw_inventory` and native carrying capacity. Saves the return receipt and native credit together; returns replacement `session`, `state`, `replayed`. |
| `store_ground` | `fabrication_store_ground` | `sand_m3`, `soil_m3` (each 0..10000, sum positive and no greater than carried), `revision`, `request_id`. Atomically saves raw lots and native debit; returns new `session`, process `state`, and `replayed`. |
| `connect_energy` | `fabrication_connect_energy` | Native `store` ID, current `store_hash`, `power_w`, `revision`, `request_id`. Starts one bounded charger interval; saves identity without spending energy. |
| `fund_energy` | `fabrication_fund_energy` | Current `store_hash`, positive `joules` (0.000001..1e9), `revision`, `request_id`. Debits the connected native battery and credits the process atomically; returns replacement `session`, `state`, `replayed`. |
| `fund_stock` | `fabrication_fund_stock` | Canonical `material`, `mass_kg` (0.000001..10000), `pool` (`personal` or explicit `shared`), current `rack_hash`, `revision`, `request_id`. Reserves real rack stock, then credits shared station stock once. Failed receiving saves retain visible escrow. |
| `release_stock` | `fabrication_release_stock` | `reservation_id`, `request_id`. Returns only an uncredited reservation to its original owner; refuses credited stock. Returns `released`, `replayed`, `session`, `stock_sources`, `stock_reservations`. |
| `plan_remake` | `fabrication_plan_remake` | `source_item` (current hands/bag ID), `candidate` (frozen Lab draft). Read-only source binding, exact native quote, stock/energy shortages, occupancy and `plan_id`; reports unavailable if no process is declared. |
| `start_remake` | `fabrication_start_remake` | `plan_id`, `revision`, `request_id`. Validates current owned source, reserves stock and requires enough finite energy. Returns `job_id`, `state`, `replayed`, `original_retained`. Retry the original request after uncertainty. |
| `wait` | `fabrication_wait` | Integer `seconds` in 1..10. Advances native physics and process, saves both; returns `cell_m` and native poses with geometry too. |
| `preview` | `fabrication_preview` | `job_id`, `position_m:[x,z]`. Returns native-checked placement and `preview_id`. |
| `commit` | `fabrication_commit` | `job_id`, `preview_id`, `request_id`. Returns installed root, new session and charged-resource receipt. |

Both MCP servers proxy the same HTTP world through `BANJO_PLAYGROUND_URL`
(loopback HTTP only, default port 8765). They do not create a second material
inventory. World MCP is 1.16.0, platform MCP 1.19.0; native ABI remains 25.
Python callers use `playground/fabrication_room.py` for the same validated room
operations. `mcp/fabrication.py` owns the pure operating model. No new native C
API is advertised for this host-side process.

### Settings

| Field | Units / bounds / default |
|---|---|
| `mode` | Required `"authoring"`; labels the initial resource boundary. |
| `stock_kg` | Required map of catalog material to 0..10000 kg; empty map allowed, duplicate aliases refuse. |
| `energy_j` | Required 0..1e9 J initial isolated supply. |
| `power_w` | Required .001..1e6 W maximum input. |
| `work_j_kg` | Required .001..1e9 J/kg useful shaping work. |
| `efficiency` | .001..1, default 1. |
| `heat_capacity_j_k` | 1..1e9 J/K, default 10000. |
| `cooling_w_k` | 0..1e6 W/K to 293.15 K ambient, default 0. |
| `max_temperature_k` | 293.16..2000 K, default 473.15. |

A candidate uses the existing Workshop `kind`, `parameters` and
`component_overrides` document, including a valid `primary_use`. At present,
monolithic products use the existing fixed structural roles; articulated products use the [fixed/bearing assembly compiler](workshop-articulation.md#funded-assembly-installation-september-20). Positions
are within ±100 m. The native scene and 16000-cell admission limits still apply.
Preview expiry and stale native/world/inventory guards remain unchanged.

### Readouts and audits

The state includes `time_s`, `revision`, `config`, available `stock_kg`,
`waste_kg`, `transferred_kg`, remaining `energy_j`, `spent_j`,
`station_heat_j`, `ambient_j`, `temperature_k` and `jobs`.
Each job retains its candidate, material, stock/product quantities,
`matter_physics_hash`, `cell_m`, `cells`, `required_j`, `work_j`,
`supplied_j`, `fraction`, `status` and operating `condition`.
States are running, paused, ready or installed. Exhausted supply and a thermal
limit explain stalled progress rather than manufacturing an output.

The audit reports per-material `material_residual_kg`, `energy_residual_j`
and `work_residual_j`. The closed quantities are:
initial material + rack imports = available + unfinished/finished workpieces + offcuts +
transferred outputs; initial supply + metered native imports = remaining supply + station heat +
ambient heat; spent supply = sum of job supplied energy.

### Native battery funding — October 1

`fabrication_state` additionally returns `energy_sources`: native store meters,
`store_hash`, `connected`, `elapsed_s` and `transfer_available_j`. The hash is
computed from the complete native saved meter, not rounded UI values. Configure
with `energy_j:0` to demonstrate that all subsequent process energy comes from
the selected native store. No market wallet claim can fund this transfer.

`energy_source_status` reports `ready` or `unavailable` with the native reason.
During a stroke or unresolved break the process state remains readable, while
source meters/transfer readiness are unavailable until a complete snapshot exists.

Connect with a rate no greater than the source's positive `max_power_w` and the
station's `power_w`. Connection starts at actual accepted native time with zero
credit. Advance time, read current source meters, then request a transfer:

```
available J = min(current charge,
                  charger W * elapsed s,
                  source max W * elapsed s - other source deliveries J)
```

Other source deliveries come from native `given_j` counters since connection or
last successful transfer. Reconnecting starts a new interval; every transfer
discards unused time. Retry receipts are checked before session, meter or
revision freshness, so the original request survives source-session replacement
and a full reopen. Changing any request field under an existing ID refuses.

The adapter restores a complete native snapshot in a temporary process, draws
the requested energy, and compares the entire result with the original plus
only the permitted source `charge_j`/`given_j` changes. It saves that source and
the receiving ledger in one atomic room file before swapping the live process.
Failed saves leave both original states untouched. Save/load refuse missing or
rewound native source meters; old fabrication saves with no imports still load.

Process state retains `energy_connection` and `energy_imports`. Each import uses
`banjo.fabrication-energy-transfer.v1` with scene/source identity, start/end
native time, declared rate, initial source delivery counter and before/after
meters. The audit adds `native_energy_received_j`, `native_transfer_residual_j`
and `native_meter_residual_j`, preserving the original process heat/work audit.

This is an explicit batched charger approximation. Energy becomes available to
the process at transfer acceptance, never retroactively. No continuous current,
cable loss or voltage conversion is modeled. Held/parked source batteries and
native stores with `max_power_w:0` (unbounded native authoring output) refuse.
Legacy world scenes contain such stores; this checkpoint does not assign them
invented limits or certify ordinary Workshop repair. Stations still require
explicit authoring stock and process coefficients. See [measured checks and next
repair steps](fabrication-energy-checkpoint.md).

### Player rack funding — October 1

Configure with `stock_kg:{}` and `energy_j:0` to start with no authored supplies.
`fabrication_state` returns exact `stock_sources` with `material`, `mass_kg`,
`pool`, `source_owner` and `rack_hash`. The authenticated player is the personal
source; a client cannot name another owner. Selecting shared stock is explicit.
Transferred stock belongs to the shared station, so other players may use it.

`fund_stock` first checks current revision, exact source hash and available mass.
SQL atomically debits the rack and records a reservation. A complete current
native snapshot and receiving receipt are then saved to the room file. This is
a recoverable two-store transfer, not a cross-database atomic commit. Failure
after the source debit leaves material **reserved**, rather than restoring a
balance that may already have been credited. Read/retry/reopen merges that
authorized credit into current-time station stock once. Work before credit is
not funded retroactively. Previously applied imports missing from an older
receiving save refuse; no spent material is recreated.

`stock_reservations` exposes only the caller's pending transfers. Inventory
shows material thumbnails and mass under **Reserved for fabrication**, with
**Finish transfer** and **Return to stock**. `release_stock` checks both live
and durable receiving receipts before refunding the original rack once. A lost
save acknowledgement cannot refund already credited material. No return is
available after manufacture. `stock_recovery_status` reports `ready` or a
save-failure `pending` reason; outstanding reservations remain visible when a
native snapshot is unavailable. Receipt budgets are bounded and never evicted.

Each `stock_imports` entry retains `banjo.fabrication-stock-transfer.v1`, scene,
source/requesting identity, canonical material, mass and
`reference_state:"cold-inventory-reservoir-v1"`. The audit adds
`rack_material_received_kg` to material input closure. This is an explicit cold
reservoir approximation: the rack holds mass/provenance, not measured motion,
temperature or location. Stock transport, placement work, avatar reactions and
whole-world energy conservation remain unqualified. Raw sand/soil/ore is not
silently converted to catalog solid stock. Existing raw-ground APIs remain.

No old damaged native body is reclaimed, reset or healed by these transfers.
See [real stock, retained-cut and browser evidence](fabrication-stock-checkpoint.md).

## Selected-item remake — October 1

Select a carried item in Inventory, open the Lab, and choose **Review remake**.
For an already declared/funded process, the panel shows exact material mass,
energy, minimum duration and station shortages. **Start remake** spends/reserves
the shared station's stock. A progress meter, **Resume remake** for paused work,
**Run 1 s**, **Place in World** and
**Collect in World** use the existing native wait/placement/admission operations.
Reload retains the pending request/job; uncertain start/install retries retain
their original IDs. An empty Lab or saved design has no carried-source remake.
Further funding from personal/shared racks and native chargers still uses the
API; ordinary starter worlds have no implicit process or invented finite source.

`plan_remake` returns `banjo.remake-plan.v1`, `source`, `quote`, `revision`,
`station_stock_kg`, `station_energy_j`, `missing_stock_kg`, `missing_energy_j`,
`stock_sources`, `occupied`, `changes_world:false` and `original_retained:true`.
Plans expire after 300 seconds and are bounded at 32 per world. Unsupported or
incomplete geometry refuses. A source in an unresolved fracture cannot plan.

The durable job/installation `remake_source` uses `banjo.remake-source.v1`:
owner, source item/body identities, diagnostic readings, source topology/kerf
signature, current native body hash and exact `draft_hash`. It is authenticated,
not an LLM-supplied ownership assertion. Moving the source between hand and bag,
changing topology/condition or changing the workbench requires a fresh plan.
The original request survives a native replacement session and a whole reopen.
Only its initiating player may pause/resume, preview or commit the remake.

Remake produces a separate body from new stock; the original is neither healed,
removed nor refunded. Supported energy is the declared lumped work estimate.
No bond-restoration, fatigue, joint repair, transport work or forming calibration
is added. Real cut-source and matched glass/oak/iron evidence is recorded in
[selected-source checkpoint](fabrication-remake-checkpoint.md). All fourteen
player requirements remain active; full ordinary repair-to-use is unfinished.

## Regression lane

Run `python scripts/fabrication_qa.py --engine <banjo_live_world_run> --out <folder>`.
Set `BANJO_LIBRARY` to the matching native shared library. The output folder must
not already exist. Reports include source revision, dirty-worktree status and
native executable/library hashes, plus each check and comparative measurements.
The native engine and shared library are required in CI. This suite runs whenever
physics CI runs, alongside the 23 mechanics and 96 material-impact fixtures.

The server offers a fixed-suite QA runner, recorded reports and cancellation
through the endpoints below. It launches isolated native processes and temporary rooms;
the player's live world and resources are not used by the tests. One run per
server, 120-second deadline, owned child processes reaped on cancellation.

| HTTP | MCP tool | Arguments / result |
| --- | --- | --- |
| POST `/api/fabrication-qa/run` | `fabrication_qa_run` | Empty object. Returns 202 with `id` and starting status. |
| POST `/api/fabrication-qa/status` | `fabrication_qa_status` | Optional `run_id`; report if given, recent runs if omitted. |
| POST `/api/fabrication-qa/cancel` | `fabrication_qa_cancel` | Required `run_id`; cancels only the active owned run. |
| GET `/api/fabrication-qa/runs` | — | Recent recorded runs. |
| GET `/api/fabrication-qa/runs/{run_id}` | — | Full test report including measurements and errors. |

These endpoints require no world session. POST requests require the same
loopback token as other sim mutations. Run IDs are 32 lowercase hexadecimal
characters; no user-provided script or arbitrary command is accepted. Reports
are replaced atomically. Missing either half of a funded room save is refused,
including removal of the fabrication ledger when `fabrication_required` is set.
Normal room switching also saves and restores the room being left, including
authoring rooms such as the building yard. Explicit `again`/`fresh` still restart
authoring rooms; those reset requests remain forbidden for funded rooms.

The fixed comparative native case makes identical 160 × 80 × 80 mm parts at a
40 mm cell size: glass 2.56 kg, oak .7168 kg, iron 8.05888 kg. Each starts from
10 kg stock, requires 1000 J useful work and uses a 500 W supply. It pauses
halfway, restarts the native process and room, resumes, installs once, retries
the installation, and checks exact prior-world state and output mass. General
model, supply-empty, thermal-limit, call-batching, insufficient-stock, concurrent
start, failed-save, stale-preview, changed-use, HTTP and actual MCP protocol tests
cover adverse cases. Native mass tolerance is 1e-7 kg; measured ledger residuals
are below 2e-12 J and 1e-9 kg in this fixture. These are integration and accounting
checks, not calibrated manufacture or fresh full-engine qualification.


## Main-world process integration (source checkpoint)

Finite-stock configuration, quoting, work, pause/resume and persistence now use
the current persistent room, including the main world. MCP world 1.8.0 and
platform 1.11.0 accept that room's `scene` and `session` for the existing process
operations; `fabrication_open` still opens the dedicated fabrication room.

This is an intermediate integration: terrain placement and articulated products
remain unsupported, and the main-world station UI and recovered-stock connection
are still to be built. No resources are automatically seeded. Configuration is
an explicit one-time authoring action with a finite isolated supply, not harvested
material or native-battery generation. The running user's world has not been
configured or changed for this test.

A configured room retains its native clock, physical state and fabrication
ledger together. `again` reopens retained state; `fresh` is refused for funded
rooms in memory or on disk. Failed restores cannot fall back to a fresh world.
Process saves preserve world-upgrade receipts so equipment cannot be supplied
again due to manufacturing activity. Funded rooms retain the existing restricted
authoring-operation policy while main-world physical interaction integration is
unfinished.

A real native HTTP/MCP regression configures an isolated main world, reserves
stock, spends one second of work, pauses, reopens, verifies unchanged work and
startup receipts, and rejects reset/refill attempts. The 14 fabrication tests
also retain comparative glass/oak/iron native outputs and actual stdio tool
discovery in both servers. This does not complete capability 3 or 16.


## Native terrain placement (source checkpoint)

Manufactured lattice outputs can now be placed in the main world using the
same preview/commit operations. The requested horizontal location remains
`position_m: [x,z]`. The installer reads the current native terrain grid and
takes the maximum of covering terrain vertices over the product's horizontal
envelope. It adds at least 1 mm for float32 decoding uncertainty, then raises
the whole lattice product to the next cell-aligned elevation. It never changes
its cells, density or mass to fit the ground. Gravity settles it after transfer;
the preview is not a stability or anchoring guarantee.

The footprint must fit inside the simulated terrain. Staging supplies current
water state explicitly and compares terrain grid/heights/surface materials,
carried excavated material and the ground ledger/volumes, alongside all existing
native physical-state checks. A funded room cannot bypass fabrication by using
the ordinary authoring commit.

Actual HTTP/native tests manufacture glass, oak and iron outputs on the main
world's raised terrace, preserving all prior state and the paid process ledger.
A separate native test digs terrain, verifies that pending-settling loss is
refused, lets the original world settle, and then installs while retaining the
excavation and carried soil. Injected altered staging terrain is refused.

Limits: native terrain reopening currently replays edits to rest, so installation
must refuse if pending soil settling would change. Exact frontier/timing
persistence remains required. Precise rigid products still refuse terrain.
Connected articulation, recovered-stock input and the main-world manufacturing
UI remain unfinished. These operations are documented by world MCP 1.9.0 and
platform MCP 1.12.0; no native ABI change was needed.

## Reusing retained offcuts

The operating-state table offers **Recover [material] offcuts** for material
already retained by a completed process. This moves the measured quantity from
`waste_kg` to `stock_kg` under the same durable transaction and receipt rules as
other fabrication mutations. A partial transfer is available through the API.
The original job, native objects, spent energy, station heat and clock are
unchanged by the transfer itself. New manufacture still consumes work and supply.
A stale revision, changed retry, unavailable quantity or failed durable save
cannot duplicate the material. Receipts survive reopening.

This is bin handling within the declared cold, homogeneous lumped-stock model.
It does not remove an installed part, undo damage, recover contaminated debris,
join offcut geometry, convert mined sand/soil, or provide a calibrated recycling
process. Those require their own physical operations and material states.
World MCP 1.10.0 and platform MCP 1.13.1 expose `fabrication_recover`; native ABI
25 and the v1 save layout are unchanged.


## Stored excavated materials

`state` additionally returns `carried_ground` with native sand/soil m3 and kg.
The Raw materials panel can transfer the current carried quantities into saved
`state.raw_lots`. Each lot is keyed by the request ID and retains the native
bulk-material packet: substance, volume, mass, source, granular form and explicit
unmodeled thermal state. Sand is not glass, soil is not concrete, and neither
can be spent by the existing finished-stock shaping process. There is no physical
container, proximity check, handling work or heat transport model in this
storage account yet. Crafted objects are not eligible sources.

The server opens an isolated whole snapshot, checks all existing state, debits
only that staged source, accepts its packet and checks exported volumes against
all received ground lots. It saves the complete source, stock and receipt in
one room file before swapping sessions. Failed saves retain the original process
and inventory. Matching retries return the previous result even with the old
source session; changed arguments refuse. Use the returned session for later
commands. Browser retries survive reconnect, including when no carried material
remains because the first request succeeded but its reply was lost.

Room save and load both require native cumulative ground exports to match the
stored lots (volume tolerance 1e-10 m3 absolute / 1e-12 relative); declared bulk
mass is checked against native 1600 kg/m3 sand and soil density. New snapshots
require the ground-state-v2 runtime. Older runtimes refuse before withdrawing.
The finished-stock and energy ledger remains unchanged by raw storage. Stored
lots survive fabrication operations and reopening without becoming initial
stock or being supplied twice. The material-processing and container goals
remain open.

### Excavated material diagnostics

`POST /api/world/fabrication/state` and MCP `fabrication_state` additionally return `ground_audit`, computed from the current native environment report and receiving lots without advancing time or changing receipts. `status` is `matched`, `mismatch`, or `unavailable` (no terrain). Each sand/soil row reports excavated, deposited, carried, exported and stored volumes in m3, stored kg, transfer residual m3, density residual kg and native terrain residual m3.

`net_external_or_untracked_m3 = deposited + carried + exported - returned - excavated`. Values within `1e-10 + 1e-12 * max(excavated, deposited, carried, exported)` m3 are labeled balanced; positive values are `external_input_or_error`, negative values `unaccounted_destination`. This is a diagnostic, not a fabricated import history: authored terrain heaps can supply outside material. Transfer closure compares native exports with stored volumes and mass against the declared native bulk density (1600 kg/m3), with mass tolerance `1e-10 + 1e-12 * stored_kg`. Matching transfers alone do not certify the terrain, rock-body, energy or thermal boundaries. The browser exposes the report under **Excavated material balance**.

### Retrieving excavated material

Ground-state v3 retains cumulative `exported` and `returned` quantities separately. It reads v1/v2 snapshots with zero returns. Returns cannot exceed exports, create negative quantities, or exceed native carrying capacity. Native internal `ground_return` must only be used inside a durable adapter transaction; it does not accept client-provided material identities.

Fabrication retains immutable original `raw_lots` plus `raw_returns` keyed by request ID (source `lot_id` and a substance-preserving packet). `raw_inventory` in each reported state gives remaining contents per lot. Empty lots remain as provenance, not available stock. Saves compare original lots against cumulative exports and return receipts against cumulative native returns. The API returns a replacement session; use it for subsequent calls. An identical request ID is replayable with its original session, including after restart. Changed requests and overdraw refuse; a failed save leaves the running world and original lot unchanged.

The browser accepts a mass to retrieve from each lot; mixed lots are retrieved in their remaining proportions. API/MCP callers may select sand and soil independently. Retrieved material can use the existing native carried-material deposit action. No object is consumed and no material conversion, thermal transport, physical container or handling-work model is added.

### Shared carrying budget

In native terrain worlds, the configured carrying limit now covers excavated sand/soil plus the actual solver mass of held and parked/stored objects. Digging (including tool breakout) is capped to the remaining mass capacity; raw retrieval and taking an additional object refuse when full. Moving an already held object into storage does not count it twice. Dropping an object releases its share. Stored objects retain their native saved mass; construction recipes are not used to recreate missing matter.

`carried_ground` and native environment/terrain reports add `objects_kg`, `total_kg`, `available_kg` and `over_limit_kg`. Existing `sand_kg`, `soil_kg` and `limit_kg` remain. The browser's load meter and movement modifier include objects once. The native mass can differ slightly from the geometry report because the rigid solver stores mass in float32; the comparison test permits 1e-6 kg between those representations, while quantity-transfer checks remain unchanged.

This is an admission budget, not a new player-body or cargo-support solver. Existing overweight saves are retained and reported rather than deleting objects. Terrain-free laboratory scenes retain their prior unbounded storage policy. Fatigue, anatomical carrying, articulated cargo and bag thermal evolution remain incomplete.

### Cold-output thermal transfer (September 20)

Funded installation now initializes the new body's native material parcel at the process's existing cold-stock reference, 293.15 K. The staging world records the parcel's material mass and internal energy; `thermal_transfer` in the durable installation receipt records these values and the replaced temporary parcel (if one was admitted during geometry staging). That temporary parcel leaves the native thermal ledger before the process output enters. Existing body parcels and prior ledger history remain protected by the installation verifier. Admission uses a relative mass tolerance of 1e-6 (plus 1e-9 kg absolute) for native rigid-body precision and an absolute temperature tolerance of 1e-8 K. Failure to declare, verify or save discards the staged world and leaves the finished workpiece available.

The energy value includes the thermochemical model's reference energy of the already-funded material. It is not free electrical work and does not refill a supply. The fabrication work ledger remains the existing stock/workpieces/station/supply boundary; this receipt is not proof of whole-world energy closure. Glass, oak and iron tests cover immediate storage, exact thermal restart, a 330 K room, and a separately preactivated output parcel. Browser QA runs those tests. Existing already-installed untracked objects are not retroactively cooled or assigned invented history.

The main-world demonstration consumed 0.1792 kg oak and 17.92 J of finite supply, installed the output and left it in bag slot 2. Its thermal reading survives reopening. BAG shows approximate whole-degree Celsius, avoiding apparent surface/core differences caused solely by converting the wire's rounded Kelvin values. [Measured deployment](evidence/fabricated-heat-deployment.json), [before](evidence/fabricated-heat-before.png), [after](evidence/fabricated-heat-after.png).
