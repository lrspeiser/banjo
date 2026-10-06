# Pick wear and fresh-player shovel audit — October 6, 2026

Tested main `193ac7beb148ea38e3781357cadafe983e9b880a`, Windows/Python 3.13 and Chrome, with the unchanged native Release bundle. This is a current capability audit, not a new shovel implementation, wear law or lifetime qualification. The owner demo was not modified; the isolated provider configuration was blank.

## Actual player path

The existing paid mixed-metal pick browser regression ran in a fresh 25 cm-column world with terrain seed 4 and goods seed 851269742. Two deliberate collection requests obtained **10.9 kg iron and 57.3 kg aluminum** from finite starter piles. Their HTTP durations were **0.158 s and 0.103 s**. The fixture supplies nearby player poses; these timings exclude walking, discovery and human interaction and are not a gathering-time estimate. No mining or trader purchase was needed for this bootstrap supply.

The browser prepared supplies, made the 5.65125 kg aluminum/iron pick, collected it into private Inventory, equipped it, studied it and earned Gathering through actual ordinary hand work. A separate funded cut retained its own accounting. This existing paid-pick fixture completed in **20.500 s** of automation. Its actual fabrication job required **565.125 J**, recorded the same work, and has a **1.13025 s simulated minimum forming duration** at the declared 500 W station. This does not describe a shovel's time or a timed human playthrough.

After the tested uses, native condition reports both pick constituents at fraction **1.0**, no damaged/broken bonds, no dent, and an attached fixing. It explicitly reports `fatigue_supported: false` and `repair_supported: false`. Ordinary use has no abrasive wear, edge-blunting or fatigue law; supported impact/connection damage is a different mechanism. A short intact-tool observation does not predict its lifetime or establish that it cannot break.

## Shovel blocker

The active catalog contains no shovel/spade recipe. A custom source was then declared through the existing construction/ground-tool schema: a 600 × 30 × 30 mm aluminum handle and a touching, fixed 200 × 3 × 180 mm iron blade, with actual blade/grip frames and Study primary use. Its authored density-based bill is **1.458 kg aluminum + 0.84996 kg iron = 2.30796 kg**. These are source dimensions and a theoretical material bill, not native occupied mass or an admitted product.

The ordinary paid Make review at the world's **50 mm solid-cell grid** refused it in **0.0213 s**:

> Every fixed constituent needs its own occupied cells.

The source is saveable, but its thin components cannot both be represented by this grid. The refusal created no fabrication job and spent no workbench stock. No completion time exists for this shovel path. Bulking the blade into a 50 mm slab or pretending a pick is a shovel would not validate the proposed tool. A finer supported local tool representation, an admitted shovel source and a complete paid build/use journey are required before quoting its manufacturing or gathering time.

## Evidence and remaining acceptance

[Recorded source, native refusal, stock, job and condition readings](evidence/shovel-wear-audit-2026-10-06.json) retain the tested revision, native runner SHA256 and timing boundaries. The local diagnostic reuses [the registered paid-pick browser test](../tests/playable_recipes_tests.py); `build/shovel-player-audit.log` records its final successful audit in **23.237 s**. Earlier diagnostic source/receipt errors were harness mistakes, corrected without changing production code, and remain in local logs. "Audit passes" means the paid pick and explicit shovel refusal were observed; it does not mean shovel construction works.

Next measure an admitted shovel's native material bill, obtain its finite materials by ordinary input, fund and complete manufacture, equip/use/restart it, and time the full human and phone path. Lifetime wear, affordable rock digging and the 10 ft-hole acceptance gate remain unfinished. No native law, tolerance, strength, resource grant or UI behavior was changed by this audit.
