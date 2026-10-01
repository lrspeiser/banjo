# Native energy funding for fabrication — October 1, 2026

## Implemented boundary

The finite fabrication model now accepts a metered transfer from a real native
battery through the shared [HTTP/MCP contract](fabrication.md#native-battery-funding--october-1).
The source debit and receiving credit are saved together. A transfer is bounded
by accepted native time, charger input power, source output power and other
energy already delivered by that source. No wallet claim is used or credited.
Existing native physics laws, source limits and process work coefficients are
unchanged. New fields are optional on existing `banjo.fabrication.v1` saves.

This is a repair prerequisite, not a completed repair operation. The old damaged
item is never reset by this implementation. The next integration must reserve
matching real player stock, retain the original native body/history, bind the
selected Lab design and source revision, perform supported timed work, and admit
the resulting part with an atomic retry receipt. Generic bond healing, fatigue,
mixed-material interfaces and physical stock reference-state transport remain
unsupported. All fourteen player requirements remain in scope: four verified,
ten partial.

## Measured Windows native comparison

Windows/MSVC Release runner and library from the prior native checkpoint; this
change is Python/API bookkeeping and does not rebuild or change the solver.
The comparison uses identical 160 × 80 × 80 mm boxes, 40 mm native cells,
`dt=1/240 s`, 10 kg initial stock per job, authored 100 J/kg useful shaping work,
efficiency 1, station power 500 W and no ambient cooling. The fixture explicitly
authors a 4000 J native battery with a 300 W output limit and a 250 W charger.
The fabrication buffer starts at **0 J**.

| Material | Native output mass | Battery transfer | Useful work | Output temperature | Process energy residual | Work residual |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 2.56 kg | 1000 J | 1000 J | 293.15 K | 0 J | 0 J |
| Oak | 0.7168 kg | 1000 J | 1000 J | 293.15 K | -4.55e-13 J | 4.55e-13 J |
| Iron | 8.05888 kg | 1000 J | 1000 J | 293.15 K | -9.09e-13 J | 9.09e-13 J |

Each import follows at least four native seconds of charger time. Manufacture
then takes two native seconds at 500 W, and existing native geometry/thermal
admission installs the result. The final source holds 1000 J, its `given_j` is
3000 J, and the process has spent 3000 J into station heat. Actual source
transfer/meter residuals are zero in this fixture. Density changes product mass;
the shared stock/work coefficient is a declared test approximation, not a claim
that manufacturing these three substances takes equal physical work.

The test uses the existing 1e-7 J/kg assertion precision for output/accounting
rounding. No native physics law or preexisting tolerance was changed; accepted native time
accumulation leaves one intermediate remaining-energy value about 5.7e-11 J.
This is not calibrated cutting, wood grain, glass repair, iron plasticity,
continuous charging, placement-work qualification or whole-world conservation.

## Executable evidence

`tests/fabrication_energy_tests.py` covers eight pure/native/HTTP cases:

- Imported work, station heat, exhausted supply and serialized retry closure.
- Invalid packets, over-power transfers, overlapping receipts and unmatched
  native source snapshots.
- Failed connection/transfer saves, unchanged complete source world, native
  session replacement, whole reopen and original-session retry.
- Stale meters, shared revision races, insufficient charge and reconnecting
  without reusing past elapsed time.
- Other source consumers use the same output envelope: 600 J delivered during
  a two-second 300 W interval leaves no charger allowance.
- Process state remains readable when a stroke/break prevents a complete
  native transfer snapshot; energy readiness is explicitly unavailable.
- Battery-funded native glass/oak/iron products, measured masses and thermal
  admission.
- HTTP and MCP calls in one main-world fixture, matched persistent source and
  process receipts, and rejoin.

The main-world HTTP fixture explicitly authors a finite-output native battery.
Existing legacy sources declared with zero/unbounded output are refused rather
than silently assigned new physical parameters. Held/parked battery connection
is refused by the adapter; a broader ordinary-player battery/cable journey is
still required before claiming that behavior is qualified.

The isolated Fabrication QA runner and CI now execute this file. Initial full
run: **43/43 pass in 22.331 s**. Final run: **44/44 pass in 21.363 s**, including retained fabrication, native assembly,
HTTP and actual MCP protocol checks. Report:
`build/resource-flow/battery-funding-20261001-final/report.json` (ignored local
artifact). It records base revision `5bc8743` with a dirty working tree and native
binary/library hashes; publishing revision is recorded below after verification.

The isolated HTTP QA launch/status/cancel checks also pass (2 cases, 23.094 s)
and leave the live fixture unchanged. Room-store regressions pass (25 cases,
15.034 s); API documentation checks pass (12 cases, 0.180 s). Source registration
remains 287/287, and Python syntax checks pass. No new C++ source or ABI is added.

Reproduce:

```powershell
$env:BANJO_LIBRARY=(Resolve-Path build/agent-progression/Release/banjo.dll).Path
python scripts/fabrication_qa.py --engine build/agent-progression/Release/banjo_live_world_run.exe --out build/resource-flow/battery-funding-qa
python scripts/check-source-registration.py
```

Use a fresh output directory. The suite owns temporary rooms and does not spend
the player's resources. The current player screens remain on the previous
condition checkpoint until the Workshop repair integration is implemented.

## Published checkpoint and live preview

Implementation `7b58f7f` is published on GitHub main by an ordinary fast-forward
push. Native runner/library remain the prior condition build; Python/API sources
are this checkpoint. Refreshed preview:
`http://127.0.0.1:8770/world?world=1df55505671743cdb6a7507fad17fa1b`.
Chrome verifies fresh entry, visible pick Condition 100%, unconfigured fabrication
state, native energy-source readiness and zero JavaScript exceptions. Reviewed
capture/readout: `build/resource-flow/battery-funding-preview.png` and `.json`.
This check creates no fabrication supplies and spends no battery energy.

The fresh generated starter world exposes three stores, all with native
zero/unbounded output declarations. A finite-output source declaration therefore
also remains necessary for the ordinary Workshop repair integration; this
checkpoint's positive charger journeys use explicitly authored fixture batteries.
Local doc-target check passes for 1603 links; all affected checks above pass.
No ordinary-player repair button or complete durability acceptance is claimed.
