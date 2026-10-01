# AI construction through paid jobs — October 1, 2026

Published implementation: `ae20a233d16e4221a46a4b8dd9a2eae321900d6f` on
GitHub main, remote revision verified after the ordinary fast-forward push.
Own 8770 preview was restarted with this implementation and unchanged binaries.
Chrome entry/Inventory/field-pick take/stow/carried and empty Lab checks pass
with one finite starter source, no pending transfers and zero JavaScript
exceptions. Its process remains undeclared, with an explicit Lab refusal.
Preview: `http://127.0.0.1:8770/world?world=96aac084e2544620ba40d4b0204a7c74`.

## Implemented

In configured worlds, AI **Build** now uses the same reviewed Make, real stock
funding, finite native charging, work and placement APIs as the Lab. It cannot
call legacy authoring preview/commit to bypass the funded guard. Unconfigured
worlds retain their existing build flow while default workbench/machine
integration remains incomplete.

A character durably retains the candidate, stable job id and exact pending
write arguments before sending them. Unknown failures keep those arguments
for replay. Explicit pre-spend stale-source/expired-plan/expired-preview
refusals refresh against current state. Accepted Start and placement receipts
survive cache loss and server restart. Pending work is offered even after its
material has left the rack; another recipe cannot silently replace that job.

One decision advances one phase: review, stock, battery connection, charging,
energy transfer, Start, native work or placement. Receipts name the phase;
the model prompt says charging/work is not a finished product. The controller
settles its pending job before declaring a completed goal chain. Pause prevents
the next operation; already committed work/transactions are retained.

The bot funds from **its own material rack**, not the creator's or unrelated
shared rack. Previously funded station supplies remain shared. A source needs
actual charge and a positive output rating; wait advances accepted native time
rather than minting energy. Supported compiled geometry, frozen material,
ownership, capacity and placement still gate the real native output.

Sources: [controller](../playground/ai_player.py),
[observed action catalog](../playground/ai_actions.py),
[HTTP/native restart regression](../tests/ai_player_tests.py).
The existing CMake `banjo_ai_player_tests` target runs these added cases.

## Measured boundary

Windows/Python 3.13 and the unchanged MSVC Release native binaries. A generated
world's real oak pile supplies the AI's 25 kg personal collection. The explicit
test workbench begins with zero stock/energy, 500 W and authored 100 J/kg.
The actual generated 10 kW solar battery funds a native 50 mm oak field pick:
**1.925 kg / 192.5 J**, `dt=1/240 s`.

The test loses acknowledgements after actual stock, energy, Start and placement
commits, restarting the real server after each. It also interrupts before
placement and restarts, requiring a new preview. Exact pending requests reload;
there is one stock import, one energy import, one owned job and one native
output. The original personal balance falls by exactly 1.925 kg; the human and
shared racks are unchanged. A foreign player cannot pause the AI's job.
Manufacture awards no learned technique. A stop between review and funding
spends nothing. Review itself leaves the process unchanged.

An explicitly rigid solar design refuses before any debit, job or placement;
the bot never falls back to unpaid authoring. This establishes refusal and
retained intent, **not paid machine manufacture**. The compiler still supports
single-material lattice solids/qualified bearings, with mixed interfaces and
exact rigid forming outside its admitted scope.

Ignored evidence: `build/ai-player/paid-make.json`, generated at base
`e11e9651d07641b6aa158fe8e1a0e547eec1a8d8` plus this source scope.
The native runner/library hashes are unchanged from the
[starter-source checkpoint](fabrication-starter-power-checkpoint.md).
This is direct execution of offered controller capabilities with native/HTTP
outcomes; it does not qualify autonomous live-LLM planning or a configured
fresh-world complete tech-tree run. No provider calls are made by this lane.

No material law, solver tolerance or native API change. Existing matched
glass/oak/iron fabrication evidence remains in the starter-source checkpoint;
this controller test adds an oak player journey without replacing that set.

Verification: paid/controller/refusal/completion policy lane passes **9/9 in
15.403 s**. The completion case checks controller policy separately from actual
native admission; it waits for the pending installation receipt before stopping.
The existing two-terrain reference progression, substituted-model progression,
pause/foreign control and ordinary Chrome Menu/Watch lane passes **4/4 in
258.979 s**. Both ordinary maps finish their declared chains in 34 decisions
and learn using-ground-tools / smelting-copper; the human state stays separate.
These unconfigured runs retain their existing material-paid authoring build,
not the configured energy-funded journey. One navigation request was aborted by
Chrome; the browser case and JavaScript exception assertions pass. Source
registration remains **287/287**; Python compilation and local doc links pass.

Focused reproduction with the existing native build:

```powershell
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/agent-progression/Release/banjo_live_world_run.exe).Path
python tests/ai_player_tests.py ControllerBoundaries AutonomousGuests.test_ai_paid_make_uses_own_collected_stock_solar_and_recovers_lost_writes_on_restart AutonomousGuests.test_paid_ai_refuses_unsupported_machine_without_free_install_or_supply_debit -v
python scripts/check-source-registration.py
```

## Next acceptance

Integrate exact rigid and supported machine fabrication, matching material and
energy accounting, then declare the ordinary workbench without blocking valid
player/AI builds. Run complete paid autonomous goal chains, normal browser Make
and actual damaged-tool replacement-to-use. Replenishment, broader tech-tree
planning, mixed interfaces, fatigue/joints and physical transport remain open.
All fourteen player requirements stay active: **four verified, ten partial**.
