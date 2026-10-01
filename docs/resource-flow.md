# Visible resource flow — September 30, 2026

## Implemented player loop

Recorded scoops send colored packets from worked ground into the rover. A visible
hopper cage/percentage and the machine panel's quantity meter follow its actual
load. Recorded takes, dumps and docks show holder transfers. Supported batches
show inputs entering the machine and outputs moving to a labeled pile.

Walk within **2 horizontal metres**, standing within 3 m above its ground, and
press **Collect**. Up to 25 kg moves into that guest's personal Inventory. Catalog
materials feed personal build stock; other substances feed personal product
stock. Collection awards no technique. New generated games use **Smelter output**
without automatic shared credit. Existing saved `rack: true` piles retain their
shared-credit behavior and cannot also credit a collector. Other ordinary piles,
including raw supplies and intakes, can be collected. Existing stock is not migrated.

## Source of truth and limits

`machine_tools.py` emits activities after positive scoop/holder/batch transfers.
Empty, full, blocked and heating-only calls emit no material. Endpoints use
declared mouths or reported body/ground positions. `machine_goods.py` keeps a
transient 96-event ring with a fresh epoch. Every authenticated observer has its
own delivery marker; unchanged replies stay small. One guest cannot consume
another guest's hopper update.

`world.js` deduplicates events. Opening/rejoining establishes a baseline without
replaying past production. At most 192 flight packets are drawn; reduced-motion
preferences retain quantities and omit flights. Ground remains the heightfield.
Displayed cubes/cages are quantity pictures without solver mass, collision,
fracture or arbitrary impulses. Cube count is schematic; the label carries the
quantity. Goods still have no simulated heap volume. The ledger books a batch
immediately; the short animation pictures that transaction, not a new process solver.

`world_goods.py` authenticates the guest, checks the session/pose, and withdraws
from a real non-rack pile under the world's state lock. Withdrawal and collection
claim save in the **same atomic room file**. Only durable claims credit personal
SQL stock. A permanent SQL receipt and the credit commit together. Failed save
leaves an uncredited claim: retry the same request. A saved withdrawal with a
database failure replays after restart. Cross-guest request collisions are
refused, and a depleted pile cannot grant another collection.

Claims have a visible refusal limit of 2,048 per world; safe long-run compaction
remains open. Avatars are client-reported positions, not solver bodies or an
anti-cheat guarantee. This checkpoint does not establish closed chemistry,
full-world conservation, cargo strength, arbitrary generated rover routing,
distributed storage or hosting/GPU performance.

## Measured acceptance

Windows 11 / Python 3.13.5 / MSVC Release CPU runner, unchanged solver checkpoint
`f819e81`, **50 mm**, **dt = 1/240 s**. No native law or tolerance changed;
earlier glass/oak/iron gates remain applicable.

| Check | Observed result |
|---|---|
| Native mine fixture | Positive dig, delivery, input/output events; 1.47 kg copper wire at 132 native seconds. Legacy rack still credits. |
| Generated batch | Actual 5 kg copper ore → 1.5 kg copper, with matching input/output events. |
| Nearby pickup | 1.5 kg removed from output and credited to the acting guest only. Distant/above-ground requests refused. |
| Failures/restart | Failed save credits nothing; retry recovers once. Saved withdrawal survives failed SQL credit and restart. |
| Two concurrent collectors | One successful pickup; sum of private credits equals the single source quantity. |
| Raw oak | 25 kg enters personal build stock; shared 12.4 kg unchanged. |
| Chrome | Actual processing flights, colored output cubes/quantity, proximity Collect, depleted pile/private credit; no runtime exception. |

[Receipt](evidence/resource-flow/acceptance.json),
[ready output](evidence/resource-flow/output-ready.png),
[collected output](evidence/resource-flow/collected.png).
CTest registers `banjo_world_goods_tests`. Native mine, goods/ports, rover and
exact receiving/restart regressions remain covered.

Source: [pickup](../playground/world_goods.py), [recorded tools](../playground/machine_tools.py),
[observer delivery](../playground/rover_brain.py), [room save](../playground/room_store.py),
[renderer](../playground/world.js), [native/browser tests](../tests/world_goods_tests.py).
Next: personal stock delivery into machine intakes, safe receipt compaction,
machine permissions, broad generated delivery acceptance and measured
multiplayer network/low-end GPU costs.
