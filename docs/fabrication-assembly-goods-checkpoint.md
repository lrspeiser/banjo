# Processed supplies in paid machine construction

October 1, 2026. Windows, main, based on `3ec8c4c`.
Implementation `d2d654d75fd2c6c7a3a5f1e0e533a72cb00b5f4a` is published on
GitHub main. Refreshed own 8770 preview passes fresh entry, initial pick geometry,
compact Inventory and prior-world reopening without JavaScript exceptions.

## Implemented

The configured paid machine path previously reserved native frame materials,
shaping energy and initial battery charge while bypassing the processed copper
and wire that the ordinary recipe listed. The same server-derived machine goods
schedule now supplies the reviewed quote. Start atomically reserves all raw and
processed supplies; a shortage leaves the job, materials and energy unchanged.

Lab shows compact copper/wire quantities, shortages, personal/shared funding
buttons and supply-finding links. Start stays disabled until supplies are funded.
Lost transfer acknowledgements retain the exact request through reload/retry.
AI construction uses the same quotes and its own processed inventory.

`fund_goods` uses the existing durable SQL escrow: debit and reservation commit
together; receiving-save failure retains escrow; recovery credits once; release
returns only uncredited supplies to the original rack. Source hashes, revisions,
authenticated ownership and receiving receipt validation prevent duplicate or
foreign spending. No new database table or native ABI is needed.

Processed imports use `banjo.fabrication-stock-transfer.v2`, `kind:goods` and
their own `goods_stock_kg` balance. Legacy raw v1 packets/jobs retain their meaning.
`assembly_goods_kg` is retained in each new job and installation receipt. The
audit separates processed input/reserved-or-transferred quantities and residuals
from native frame mass. Old installed jobs are not retroactively billed.
World MCP 1.20.0 / platform MCP 1.23.0 expose the same funding operation.

## Verified behavior

[Retained evidence](evidence/fabrication-assembly-goods-checkpoint.json).

- Fixed Fabrication QA: **66/66**, 74.104 s. Includes native installation/use,
  real-cut retention, energy/material closure, retry/restart and actual Chrome
  mouse funding. A fixture that changed station configuration after SQL funding
  correctly refused; its pre-funding shortage check now preserves that invariant.
- Paid AI checks: **4/4**, 25.442 s. The mixed fixture completes in 20 decisions:
  two raw and two processed transfers, native solar charging, work and installation.
  It uses explicitly authored test stock collected through ordinary nearby pickup;
  this does not establish fresh-world autonomous supply acquisition.
- Browser mixed housing: 4.02944 kg iron / 0.1792 kg oak, separately 0.5 kg
  copper, 420.864 J shaping estimate + 200 J battery charge. Actual funding,
  lost goods acknowledgement → reload → retry, Start and native placement pass.
  No JavaScript exceptions. The compact cost capture was visually inspected.
- SQL/native recovery: 3 kg personal / 4 kg peer wire, 0.6 kg transfer. Failed
  receiving save, exact release once, lost successful save acknowledgement,
  whole reopen and replay leave 2.4 kg personal / 4 kg peer and one 0.6 kg credit.
  Raw stock is unchanged; stale source hashes and peer replay refuse.
- Source registration **287/287**, no exclusions. No C++/solver/law/tolerance changes.
  The final malformed-packet input guard additionally passes the two model checks.

Matched exact machine: 0.003072 m³ native frame, 40 mm scenery,
`dt=1/240 s`; 25 kg feed / 2500 J authored shaping work plus 100 J initial
battery charge, separately 0.5 kg copper + 0.6 kg wire for every material:

| Frame material | Native allocated mass kg | Processed residual kg | Local material residual kg |
|---|---:|---:|---:|
| Glass | 7.68 | 0 | 0 |
| Oak | 2.1504 | 0 | 0 |
| Iron | 24.17664 | 0 | 0 |

Differences follow catalog density; mechanical float mass remains separately
bounded by the existing 2e-7 relative tolerance. Maximum cumulative local energy
residual is 3.638e-12 J. All three retain actual battery/motor use, failed-save
rollback and whole restart. No stiffness, grain, fatigue or realism claim is added.

Commands on existing Windows Release binaries in `build/agent-paid-machine`:

```powershell
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/agent-paid-machine/Release/banjo_live_world_run.exe).Path
$env:BANJO_LIBRARY=(Resolve-Path build/agent-paid-machine/Release/banjo.dll).Path
python scripts/fabrication_qa.py --engine build/agent-paid-machine/Release/banjo_live_world_run.exe --out build/resource-flow/assembly-goods-final-20261001
python tests/ai_player_tests.py -k paid -v
python scripts/check-source-registration.py
```

## Boundary and next gate

This is declared assembly input accounting. The native frame does not yet include
the goods' additional constituent mass, thermal state or mechanical response.
The shaping coefficient is still authored for frame feed only; incorporation
work and calibrated forming remain unmodeled. Receipts explicitly retain this
boundary. Local ledgers are not full-world conservation certification.

The complete fourteen-item player goal remains active: four verified, ten partial.
Next declare the ordinary fresh-world workbench with zero supplies, migrate the
canonical machine use programs and normal player/AI guards, then qualify complete
paid progression and an actually damaged tool through replacement/equip/use.
Current acceptance still explicitly configures its process; fresh-world enablement,
mixed lattice interfaces, exact tool points and repair laws are not completed here.
