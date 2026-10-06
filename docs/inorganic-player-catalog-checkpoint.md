# Inorganic player catalog and paid tool checkpoint

## Scope and physical boundary

Implementation on the working tree based on `c67f1339919eadfd2a51b18339512610b5f9de48`, Windows/Python 3.13, October 5, 2026. Integration and publication revision are recorded by the parent checkpoint. Owner demo data was not used by these tests.

`playground/playable_recipes.py` supplies actual inorganic game sources and a checked game progression graph. Historical MCP assemblies, oak/glass/iron comparison fixtures and research material prices remain available outside active games. Active catalogs, named sources, saved-design listings, material controls, market, defaults and opening goals use the game policy. Organic saved files are preserved and filtered by the shared policy; they are not rewritten.

The compact field pick has an aluminum haft and iron arm. Both members align to the 50 mm native grid: 8 aluminum cells (2.7 kg) plus 3 iron cells (2.95125 kg), totaling **5.65125 kg**. Its two native groups are joined by a finite fixing; the progression matcher describes a connected assembly with `one_piece=False`. Actual native Study and positive use are required for knowledge. The source does not confer strength, wear, plasticity or fracture realism.

Exact rigid furniture uses genuine iron density with smaller sections. Camp stool mass is **3.931065 kg**, camp light **2.1167 kg**, and small camp solar source **21.063705 kg**. Thin rigid iron plates and members do not claim elastic bending laws. The generated solar farm has separately measured native mass **214.426406 kg**; see [generated-world evidence](inorganic-generated-world-checkpoint.md). Its requested 10,000 W limit is bound before assembly constructs the machine parameters.

The direct assembly density map now recognizes canonical `aluminum` at 2700 kg/m³ and `ice` at 917 kg/m³. This corrects mass costing without changing the material law or the historical aliases and oak/glass/iron entries.

## Finite supplies and progression

Active Market offers iron in **1 kg lots, initial stock 48, initial price 760 J**. Scarcity adjusts later quotes; planning and purchasing use the same scoped lot. This retains the historical 760 J/kg rate while permitting the genuine metal starter and furniture masses. Aluminum offers 0.5 kg lots, initial stock 48, 190 J. Recovered native-world metal stock and trader purchases retain their explicit source and quantities. Coal remains an allowed raw resource, not a newly invented native preset.

The paid tool opening consumes actual iron, aluminum and metered battery work. Buying is optional when loose recovered stock is present. The earlier camp checklist uses four purchased iron lots; a guest who legitimately banks or buys stock can earn those supply goals without earning unrelated build or packing goals.

## Verification

Native bundle: `build/ui-native-verification-bin`, runner SHA-256 `44F74C1729E8C2BB01B9448A64C76C314E00500E3129CB821F1582D84D404026`. Browser tests ran with `BANJO_BROWSER_TESTS=required`; player transactions used isolated temporary worlds and actual HTTP/native responses. Other agents had separate tests running, so timings here are suite durations, not isolated performance measurements.

| Check | Result | Evidence |
| --- | --- | --- |
| Playable source/catalog + complete paid browser tool journey | 4/4 passed, 20.822 s | `build/playable-recipes-current-full.log` |
| Starter goals, two players, actual Market/Make/World browser controls, packed products and restart | 4/4 passed, 63.006 s | `build/inorganic-starter-goals-final.log` |
| Full goal chains: real ordinary use, two seeds/two players, paid surface placement, watched batch, private peer and restart | 10/10 passed, 77.325 s | `build/inorganic-goal-chains-publish-gate.log` |
| Market ledger and actual native solar banking | 14/14 passed, 3.288 s | `build/inorganic-market-full.log` |
| Canonical density and retained catalog comparisons | 8/8 passed, 0.134 s | `build/inorganic-material-catalog.log` (parent catalog registration also passed) |
| Source registration, Python compilation and diff whitespace | Passed | `build/inorganic-player-source-registration.log` |

The paid browser journey collects finite recovered metals, selects the compact source, prepares supplies, starts actual work, completes native fabrication, adds the owned product to Inventory, equips it, studies the whole fixed assembly, and performs an ordinary hand stroke. The recorded ordinary result removed **2.27176 kg sand**, with **4.23177 J** measured work, whole tool and closed native result. This completed the owned-tool goal and learned Gathering by hand. A separate explicitly funded cut released **24.82004999 kg**, consumed **482.2615235 J**, debited **483 J** with **0.7384765 J** wallet rounding, and returned an actual loose native body. Funded work does not substitute for ordinary functional learning evidence. Recorded values belong to this one scene and request, not a universal yield claim.

Evidence JSON: `build/playable-recipes/paid-metal-tool-use.json`. Visually inspected screenshots:

- `build/workshop-navigation/inorganic-compact-tool-source.png`
- `build/workshop-navigation/inorganic-paid-tool-inventory.png`
- `build/workshop-navigation/inorganic-tool-gathering-earned.png`

## Resolved checks and retained failures

Initial paid-tool attempts exposed a machine rating binding bug: supplied parameters were merged after assembly, leaving the native battery rating at its default. The helper now merges before assembly. Mixed-tool Study and durable trusted-source receipt binding were repaired separately in `player_learning.py` and `room_store.py`; the successful browser run exercised both.

The first starter migration still banked only one 500 J draw before a 760+ J iron quote. The exact refusal, `You need more banked energy for this item`, is retained in `build/inorganic-starter-purchase-error.log`. The fixture now reads the current balance and quote, banking finite native energy until covered. The third bench's old single spot tipped 172 degrees in the native two-second preview. Its fixture now tries the same bounded ordered spot approach as normal placement and retains that native admission gate.

The fresh goal-chain suite initially passed 6/10. Native Study/use now succeeded, but smooth terrain 4 / goods seed 1 could not fit clay and sand machine work sites, blocking ceramic, concrete and glass routes. Other random smooth terrain 4 worlds exhausted all generator retries for clay. Exact evidence is retained in `build/inorganic-goal-chains-full.log` and `build/inorganic-goal-seed-audit.log`. The generator owner corrected required seam placement order before recovered metal stock and used actual dry/drivable standing sites for found stock, preserving mining-site flatness and clearance requirements. Its expanded 31-check suite and six-seed native opening matrix passed; the final player goal-chain rerun passed all 10 methods in 77.325 s. No source-admission, stability, ownership, finite stock, metered work or durable learning assertions were removed.

The later 9/10 goal-chain run retained the full paid two-group tool across restart, but its old single-body fixture compared the bag ID to the recipe root. The actual bag selects the iron head as canonical ID and retains both head and aluminum haft. The updated assertion checks the complete paid receipt part set, correct label, whole assembly and measured 5.65125 kg mass. The exact diagnostic is retained in `build/inorganic-goal-packed-tool-audit.log`; no native or inventory production change was needed.

The final personal opening fixture also checks full-precision SQLite stock conservation using the actual paid job's `stock_materials_kg`, then compares Inventory to the exact four-decimal rendering of that ledger quantity. The previous approximate comparison failed at a rounding midpoint (2.74875 kg theoretical versus 2.7487 kg shown). This changes presentation verification, not stock quantities or physics tolerances. Its focused two-seed/two-player/restart check passed in 27.085 s (`build/inorganic-goal-personal-final.log`), followed by the authoritative full 10/10 publishing gate. Navigation-cancelled HTTP `ConnectionAbortedError` traces remain visible in that passing suite log; no console or native gate was suppressed.
