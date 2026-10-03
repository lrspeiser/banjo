# Visible resource flow — September 30, 2026

**R1 player input delivery, October 2:** [Verified input checkpoint](material-input-delivery-checkpoint.md) adds recipe-derived Inventory → hopper loading with private SQL escrow, paired receiving saves, retry/return recovery and stationary-machine controller selection. Chrome, failure/peer/restart and the complete rover → personal input → processed copper → saved lamp → Make/Use/restart journey pass. R1 remains open for raw-storage UI, ground-to-usable-stock, exhausted-input guidance and unassigned-load recovery; no native law or preview change.

**October 1 presentation update:** [Material thumbnails](material-preview-checkpoint.md) replace ground circles and floating source labels. At crosshair shows possible soil/sand, separate rover ore, whole products and actual output stock. Nearby Look changes camera direction; output Collect uses the existing personal durable collector.

## Implemented player loop

Recorded scoops send colored packets from worked ground into the rover. A visible
hopper cage/fill and the machine panel's quantity meter follow its actual
load. Recorded takes, dumps and docks show holder transfers. Supported batches
show inputs entering the machine and outputs moving to a visible pile.

In gravity mode, walk within **1.6 horizontal metres** of a finished machine
output, standing within 3 m above its ground: it collects automatically and the
recorded cubes fly toward your view. Fly/character-watch mode never auto-collects.
Manual Collect remains available within **2 m** for outputs and loose supplies;
processor inputs are hidden from this proximity button. Up to 25 kg per request
moves into that guest's personal Inventory. Catalog
materials feed personal build stock; other substances feed personal product
stock. Collection awards no technique. New generated games use **Smelter output**
without automatic shared credit. Existing saved `rack: true` piles retain their
shared-credit behavior and cannot also credit a collector. Automatic requests
are checked against current processor outputs on the server; an intake can
never be swept into personal stock by automatic collection. Existing stock is
not migrated. The general explicit transfer API still permits manual withdrawal.

Input contents now sit in open-topped visual hoppers at the declared input ports,
instead of loose cubes on the ground. Packet endpoints match these containers;
the existing rover dump/dock events continue to supply them. Output cubes stay
outside for collection. Bins and cubes remain ledger pictures, without native
collision, cargo volume or a dump-truck tipping joint.

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
fracture or arbitrary impulses. Cube count is schematic; the side panel carries the
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
| Chrome | Actual processing flights, input bins, colored output cubes/quantity, ordinary W approach automatically collects 1.5 kg into personal stock with collection flights; Fly approach leaves stock untouched. No runtime exception. |
| Automatic input protection | Processor intake automatic request refused without withdrawal/credit; output retry retains its receipt and credits once. |

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

October 1 extension: all 11 `world_goods_tests` cases pass in 87.1 s. The enhanced
Fly/ordinary-walking/hopper browser case also passes separately. New ignored
screenshots in `build/resource-flow/` show the hopper and actual collection
packets; older checked-in images above describe the September 30 manual flow.
