# Player material funding for fabrication — October 1, 2026

## Implemented boundary

The shared [HTTP/MCP contract](fabrication.md#player-rack-funding--october-1) now
accepts actual catalog material from the authenticated player's rack or an
explicitly chosen shared rack. An exact source hash and receiving revision bind
initial authorization. No client may choose a peer owner. The receiving station
is shared; transferred personal stock becomes available to its users.

SQL atomically debits source mass and writes a durable reservation. The current
native snapshot, station credit and original receipt then save in the room file.
These are two storage systems: failure after debit keeps escrow, rather than
claiming an unchanged source balance. Retry/read/reopen credits an authorized
reservation once at current native time. Previous work is not funded retroactively.
Applied source records missing from an older receiving history refuse. Receipt
budgets are bounded; spent credits are never evicted or replayed as new supply.

Inventory exposes only the requesting player's pending material thumbnails and
mass, with **Finish transfer** and **Return to stock**. Return checks live and
durable receiving credits, including a save whose acknowledgement was lost,
before refunding its original source once. Ordinary Inventory has no additional
section when there is no pending transfer. Read-only Workshop context remains
available in funded rooms; unfunded authoring installation remains blocked.

Initial process stock may be empty and energy zero. The stock packet declares
`cold-inventory-reservoir-v1`: mass/provenance bookkeeping with an explicit cold
reference approximation, not measured temperature, motion or location. Raw
soil/sand/ore is not converted to solid stock. Stock transport/placement work,
avatar reactions and whole-world physical conservation remain unqualified.

## Measured Windows native comparison

Windows/MSVC Release/Python 3.13.5/Chrome; existing native runner and `banjo.dll`.
No C++ source, material law, native tolerance or ABI changes. Matched 160 × 80 ×
80 mm boxes, 40 mm cells and native `dt=1/240 s`; authored process 100 J/kg,
efficiency 1, 500 W, no cooling. Process seed stock **empty**, energy **0 J**.
The fixture authors a 4000 J/300 W native battery and a 250 W charger. Each job
uses 10 kg from the actual SQL rack, receives 1000 J after four native seconds,
and performs two native seconds of work before native admission at 293.15 K.

| Material | Rack debit | Native product | Offcuts | Native import | Local mass residual | Local energy residual |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 10 kg | 2.56 kg | 7.44 kg | 1000 J | 0 kg | 0 J |
| Oak | 10 kg | 0.7168 kg | 9.2832 kg | 1000 J | 0 kg | -4.55e-13 J |
| Iron | 10 kg | 8.05888 kg | 1.94112 kg | 1000 J | 0 kg | -9.09e-13 J |

Catalog density drives different output mass. Equal shaping coefficients are
declared test approximations, not calibrated glass/oak/iron work or constitutive
repair laws. Existing numerical accounting precision is retained.

## Retained actual damage

A 100 mm oak cube and a real 6 m/s iron edge use 10 mm cells, native gravity and
`dt=1/240 s`. The isolated falling stroke starts at 20 m to stay clear of the
floor; it is distinct from the zero-gravity native condition oracle. Actual
cutting severs 104/12,876 bonds, connectivity 0.9919229574401989. The edge is
withdrawn and the old body parked. No bond state or velocity is reset to create
damage or recovery. Contact-fracture requests during this stroke are declined;
this case does not qualify fracture handling.

One real rack kilogram and 100 J native battery energy then manufacture a
separate 0.7 kg oak part with 0.3 kg offcuts. The complete old parked body and
its measured damage remain unchanged through native admission. The new part has
zero broken bonds; its thermal/connectivity index differs from 1 by float roundoff
(2.2e-16). This is new-part manufacture with retained damage, **not completed
selected-item repair or native bond healing**. Glass/iron comparisons remain in
the matched manufacturing and existing cutting/condition regression sets.

## Executable player and failure evidence

`tests/fabrication_stock_tests.py`, wired into the isolated Fabrication QA suite
and CI, covers nine pure/native/HTTP/MCP/browser cases:

- Empty initial supplies, exact import/material audit, serialization and tamper refusal.
- Failed receiving save: exact source debit, visible escrow, unchanged native
  state and one-time return. Native restart credits once without rewinding bodies.
- A saved receiving file with lost acknowledgement cannot refund credited stock.
- Separate Alice/Bob racks, stale hashes, shortages, forged owner and older
  receiving history refusal. Pending reservations are private.
- Matched zero-seed glass/oak/iron native manufacture and retained real oak cut.
- Ordinary generated-world oak collection credits 25 kg. A failed 1 kg transfer
  displays a thumbnail; Chrome clicks Return and restores 25 kg. A second failed
  transfer displays again; Finish credits 1 kg, leaving personal 24 kg and shared
  12.4 kg. A fixture-authored finite battery funds a native 0.7 kg product. SQL
  balances, job/output and original collection receipts survive whole server
  restart and retry. Explicit shared funding then debits 1 kg shared only.
- MCP schema-validated reserve/return/credit calls use the same HTTP account;
  original requests neither duplicate debit nor credit. Both actual MCP protocol
  servers advertise the new tools. World 1.15.0, platform 1.18.0, ABI 25.

The full suite exposed a double acquisition of the non-reentrant Inventory lock
in a new commit wrapper. A thread trace located the lock; source validation now
runs inside the existing installation transaction. The full HTTP/native suite
passes after the fix. Collection claims and durable outbox acknowledgements are
preserved across both funding saves and native installation.

Initial corrected full QA: 52/52 in 30.703 s. Expanded final QA: **53/53 in
33.696 s**, base `7671656` with a dirty worktree. Publication revision is
recorded below after publishing. Local evidence:
`build/resource-flow/player-stock-20261001-publish/report.json` (ignored), plus
visually inspected `build/resource-flow/stock-reservation.png`. Reports include
source revision/dirty status and executable/library hashes. Chrome checks report
zero JavaScript exceptions. Readiness waits include completed energy readings
before navigation, to avoid aborting outstanding browser requests.

After the full run, pending recovery status was tightened to include the native
reason when a complete snapshot is unavailable. The affected nine-case stock
suite passes again in 10.326 s, including that refusal and the complete browser
journey. No manufactured credit appears during the unfinished stroke.

Refreshed own preview 8770: fresh generated entry, intact pick reading, no
configured process, four actual stores (zero finite-output starter sources),
16 stock-source readings, no pending reservations, hidden empty recovery section
and zero JavaScript exceptions. Inventory screenshot inspected. Starter batteries
still need explicit finite output capabilities for ordinary repair.

Affected checks: isolated QA launch/status/cancel 2 pass in 35.304 s; room save
25 pass in 15.136 s; Workshop tabs 9 pass in 1.103 s; API documentation 12 pass
in 0.181 s. Source registration 287/287. Python/JavaScript syntax checks pass.
These are measured Windows results, not macOS/Linux or cross-GPU qualification.

Reproduce with matching native binaries:

```powershell
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/agent-progression/Release/banjo_live_world_run.exe).Path
$env:BANJO_LIBRARY=(Resolve-Path build/agent-progression/Release/banjo.dll).Path
python scripts/fabrication_qa.py --engine $env:BANJO_LIVE_ENGINE --out build/resource-flow/player-stock-new-run
python tests/fabrication_qa_tests.py -v
python scripts/check-source-registration.py
```

CI supplies its installed Chrome path and software rendering flags for this lane.
Missing Chrome fails this acceptance rather than silently omitting the UI journey.
The suite uses temporary worlds and never consumes the player's live stock.

## Next acceptance

Bind selected carried Lab source and exact recipe revision to supported remake,
declare a finite starter battery/station capability, show material/energy/time
costs, and complete remake-to-equip-to-use with failure/retry/restart evidence.
Retain old native damage/history. Mixed-material interfaces, native fatigue/joint
health and physical inventory transport remain separate gates. All fourteen
player requirements stay active: **four verified, ten partial**.
