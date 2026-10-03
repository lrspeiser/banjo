# Gathered sand to glass and a usable lamp — October 2, 2026

Published implementation: `dc70c036db0192e814683f15dcdf8a2f8a49173e` on GitHub main.

## Implemented

Stored ground lots can load a compatible machine input directly. The private
raw debit and receiving hopper claim save in one room transaction. A genuine
save failure retains both original balances; an acknowledgement lost after an
exact durable save adopts the receiving state and retries once. Source owners
are checked before replay. Room load/save refuses orphaned raw input receipts.
Original cumulative native export receipts remain available for ground audits;
remaining storage subtracts delivered packets as well as native retrievals.

Select the furnace, choose **Melt glass**, and use **Load stored** beside its
input. Recipe choices use the declared room recipes and the existing chamber,
element and wall-loss ceiling. Changing recipe requires a stopped nearby
machine and completion of the current batch duration. It preserves the hopper,
energy store, chamber temperature, execution history and original declaration.
An optional process choice in machine runtime retains it across restart; older
v1 runtime records keep their original recipe. Recipes reports current choices.

The selected-machine panel shows thumbnails, hopper/storage quantities, process
work per kilogram, required/current chamber temperature and heating power.
Pending raw input retries survive page reload. Empty inputs direct players to
store already carried material, gather missing ground material, collect mined
inputs or inspect supply routes. Depleted deposits say **Source exhausted**;
the crosshair directs players toward another source. Viewing grants no supplies.

## Verification and boundaries

Windows, Python 3.13, Chrome, existing MSVC Release CPU engines in the separate
`build/agent-object-strike/Release` directory. Runner from `fa84f14`, native
library from the earlier storage build. Default scene 50 mm cells, terrain
250 mm cells, native dt 1/240 s. No native material/solver law, strength,
geometry, timestep or physics tolerance changes.

The focused failure/restart route sends 7 kg of stored sand into the starting
furnace. Its actual native battery draws 275,600 J including chamber warming,
against the declared 5,600 J process work. Output is 5.95 kg glass; 13 kg remains
in the original 20 kg lot. Disk refusal, peer refusal, exact retry, a lost save
acknowledgement, full shutdown/restart and private output credit are checked.

The player acceptance uses actual Field pick work to gather sand, Store, select
the starting furnace, load sand, pay native heat/work, collect personal glass,
fund a saved original-size mine lamp, Make, place and switch it on. Other inputs
use actual rover-processed copper and finite solar-paid Market iron. Glass is
not bought in this route. Whole server restart and replay check the exact
personal material account, native ground history, funded ledger, output energy
store and private peer inventory. Display rounding is not used for this audit.

The measured player route gathers 7.817217079 kg in two native work receipts,
loads 7.817217 kg and produces 6.644634 kg of glass. The furnace draws
226,253.7736 J after the preceding copper run. Manufacture uses 4.32 kg glass,
12.68644 kg iron, 0.5 kg processed copper and 2,200.644 J including a 500 J
output battery. The 10 W lamp runs for 2 s; its retained charge is
479.9999999999909 J and given energy 20.00000000000002 J. Fabrication material,
assembly-copper and work residuals are zero; local energy residual is
2.84217e-13 J and native transfer residual 8.77662e-11 J. These are local
accounts, not a complete native-world or chemical conservation result.

Seventy-two storage/fabrication/machine checks pass in 126.042 s. The latest
browser and guidance repeat passes in 25.872 s: actual clicks select glass,
load private storage, recover a failed transfer after reload, and show empty
input guidance to a peer without exposing the owner's lot. Screenshots were
visually inspected; checked browser runtime exceptions are empty. Browser
closure can abort an outstanding Market HTTP response in the local log.
Python compilation, JavaScript syntax and source registration (297/297,
no exclusions) pass. Both complete old/new lamp acceptance checks pass in
306.169 s. Together the targeted runs cover 74 distinct checks; the latest
guidance repeat covers two of those again. The broader exploratory 96-check
run passed 94 and failed the two retained baseline rover checks described below.

Evidence files are ignored local artifacts under `build/resource-flow`:
`stored-sand-glass.json`, `gathered-sand-build-lamp.json`,
`sand-current-regression.log`, `sand-build-acceptance.log`,
`input-guidance-current.log`, `stored-sand-input.png`, `empty-sand-input.png`.

Two broader rover checks fail on both the changed tree and an untouched archive
of GitHub main `1d441a3`: `routine_language_tests.InTheMine`'s ordered port
journey does not finish in its declared run, and the rover recovery browser
check does not receive its packing refusal after Q. Baseline evidence is
`build/resource-flow/baseline-main/baseline-failures.log`. These are retained
R4 defects, not removed tests or passing gates for this checkpoint.

Glass yield (0.85 kg/kg), process work (800 J/kg), waste and recipe duration
(3 s/kg) are the existing declared game ledger model. Actual native gas heating
is charged separately; lining/product thermal mass, transported thermal state,
chemistry and complete pipeline mass/energy conservation remain unmodeled.
This qualifies the supported sand route, not physical glass manufacture or all
R1 supply chains. R3 damage/repair/wear remains paused. Preview servers retain
their previously loaded Python modules and were not restarted.

## Next

Audit remaining built-in and saved recipe supply routes: identify obtainable
inputs, compatible processors, unavailable mechanisms and actionable blockers.
Then address the two retained rover defects and broaden terrain routes under
R4. Native cargo/avatars and wider LLM progression remain R5/R6.
