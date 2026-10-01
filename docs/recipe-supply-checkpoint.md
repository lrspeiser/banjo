# Recipe supply checkpoint — October 1, 2026

Implementation publication is recorded after the verified checkpoint push.
Player item 7 advances but remains partial; the full fourteen-item goal stays
active (4 verified, 9 partial, durability/repair pending).

## Implemented player flow

Click a recipe thumbnail or expand Materials & build details. Compact rows
show required/held quantities, personal/shared stock, predicted debit and missing
mass. Actual native grid/readiness reasons remain available; ordinary Workshop
Make has no skill gate, so the card truthfully says None required.

Missing supplies now carry server-resolved acquisition routes:

- Existing material piles show current available mass and a Locate pile in World link.
- Extraction areas show remaining reserve, programmed mining equipment and a World link.
- Processes show their current machine, actual hopper inputs and configured output.
  Absent equipment explicitly says Processing machine required.
- Check Market opens and highlights the actual traded offer. It does not promise
  stock, affordability or free energy; Market retains those checks.
- Substances without a world or trader route say No source in this world or Market.

World resource links turn the view toward the actual source and pin a card with
its current substance/mass, distance and collection/mining route. They do not
move the player or collect material. A pile that feeds a machine is labelled as
an input; manual collection is distinct from automatic finished-output pickup.
Nearby collection uses the retained personal durable claim/SQL receipt path.
Exhausted piles are omitted from refreshed acquisition routes.

The new Market button initially called the Workshop edit-history object instead
of `window.history`; the browser test caught this and the handler was corrected
before publication. No native contact/material/terrain/energy law was changed.

## Measured acceptance

Windows 11, Python 3.13, installed Chrome 1440 × 900, existing MSVC Release
native runner from `a64c1e5`. CMake registers `tests/recipe_guidance_tests.py` as
`banjo_recipe_guidance_tests`; both cases pass in 11.22 s (CTest total 11.24 s).

The ordinary browser journey performs actual mouse clicks:

1. Table needs 30.7776 kg oak; shared stock is 12.4 kg, personal stock 0.
   Make is disabled, 18.3776 kg is missing, and an actual oak pile is offered.
2. Locate opens the World source card without teleporting the player. The test
   observer then stands beside that actual pile on native-surveyed ground.
3. Collect credits 25 kg to this player. Stock becomes 37.4 kg combined and
   the ordinary Table Make button becomes enabled.
4. Paid native placement succeeds with one install receipt. Make spends all
   25 kg personal oak plus 5.7776 kg shared oak, leaving 6.6224 kg shared.
   The final Recipes refresh shows that new stock before the next card is read.
5. Rover details show missing glass/iron/wire processing equipment and 20 kg
   copper ore in the existing copper processor's hopper. Check Market highlights
   Copper wire coil and preserves its actual price/stock/wallet checks.

The API case verifies predicted personal/shared shortages, exact existing pile
mass, actual machine input identity/stock and another player's unchanged private
shortage. Repeated real collection exhausts the oak pile; its route disappears
while the actual oak Market offer remains. Amounts use existing wire/BOM
precision and tolerance; collection/Make tolerances are unchanged.

Other affected checks: all 15 resource/player/browser cases pass in 104.040 s;
9 Workshop tab/readiness/saved-design cases pass in 1.062 s; the personal solar
Market/restart case passes in 5.319 s. Native source registration: 286/286,
zero deliberate exclusions. Final browser journey records zero JavaScript
exceptions. Reviewed screenshots and receipt evidence are ignored under
`build/resource-flow/recipe-guidance*.png` / `recipe-guidance.json`.

```sh
ctest --test-dir build/agent-progression -C Release -R '^banjo_recipe_guidance_tests$' --output-on-failure
```

## Remaining acceptance

Item 7 still needs recursive guidance from an empty processor hopper back to
its required raw supply, an ordinary process/output-to-build journey, and
broader saved-design shortage coverage. The current routes are live facts,
not a proof of path reachability, perpetual resources, machine readiness or
supported material strength. Decorative extraction areas remain goods-ledger
reserves, not native ore-cell composition.

Item 8 still needs ordinary tool discovery/equip/use, real capacity refusal and
empty/store/use verification. Its native tool stroke and existing direct ground
edit paths must be distinguished when qualifying the player journey. The other
open avatar, rover, mixed-material pick, physical cargo and damage/repair gates
remain in the complete goal.
