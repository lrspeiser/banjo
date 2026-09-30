# Market economy checkpoint

## Player loop

A generated game already begins with a solar array and a shared 20 MJ battery at 2 MJ initial charge. The array keeps charging that battery while the world runs. In the Workshop's **Market** tab, an authenticated player can bank 100 J at a time. Banking calls the native `draw` operation on the solar farm store, which reduces `charge_j` and increases its `given_j` by the same amount. The server leaves 5% of capacity for the world's machines. The player's saved balance is denominated in joules; it is a game claim on energy already withdrawn from that battery, not extra charge still present in the solver. No solar or material law was changed for this checkpoint.

The Market sells fixed mass lots of oak, iron, glass, rubber, copper and copper wire. Purchased stock belongs to the player's Workshop rack. Recipe checks and native Workshop installation can use that personal stock plus the existing shared world rack; installation spends personal stock first. A different player sees shared stock and their own purchases, never another player's purchased stock. Named games cannot raise rack quantities through the old authoring number boxes. World machines may still add their output to the shared rack.

Existing saved Workshop components and designs remain in the world's shared library. This checkpoint changes stock ownership, not legacy design ownership; a future personal-library migration needs an explicit sharing model.

The Market shows the first reachable technique in the existing tech graph and a ready built-in recipe whose material shortfall can be reduced by an offered lot. A purchase fills stock; it does **not** grant a skill or certify a design. The recipe still must pass its Workshop and world admission and be made and used. The tech journal remains world-level in this checkpoint, so the named skill is a shared-world recommendation. Per-player skill journals are a separate follow-up.

## Price and supply rule

Each world has its own finite shelf in SQLite. A lot has a declared base price in J and a starting quantity. The current quote is `ceil(base_J × (1 + 0.75 × sold_fraction))`, where `sold_fraction = (initial − remaining) / initial`. At zero stock the lot cannot be bought. One lot of every item is delivered by an external trader after each 120 s of simulated world time, up to its starting shelf capacity. The fresh delivery lowers the quote. The trader's goods are external supply; this is an explicit game economy boundary, **not** a claim that the physics engine mined or manufactured them. The starter solar array makes the currency supply renewable; the trader makes the goods shelf renewable. There is no resale, order book or player-created market listing yet.

| Lot | Mass | Base price | Initial shelf |
| --- | ---: | ---: | ---: |
| Oak stock | 0.5 kg | 120 J | 60 |
| Iron stock | 0.25 kg | 190 J | 48 |
| Glass stock | 0.25 kg | 170 J | 40 |
| Rubber stock | 0.25 kg | 170 J | 36 |
| Copper batch | 0.5 kg | 260 J | 36 |
| Copper wire coil | 0.5 kg | 330 J | 36 |

These are explicit game prices for an external supplier, not measured thermodynamic work or calibrated physical manufacturing costs.

The server recomputes each price inside the purchase transaction. The client sends the quote it saw; a changed price requires refresh. An order id makes a retry idempotent. Wallet debit, world shelf decrement, purchase receipt and personal rack credit commit in one SQLite transaction. Energy deposits use a room-save outbox: the native draw and a pending deposit are saved with one world snapshot, and a unique SQL receipt credits the wallet once. The snapshot's native store meter must include the draw before a pending deposit can be saved. A failed save leaves the draw and claim together in live memory for retry; a restart before a successful save restores the earlier charge and no claim.

## Storage and limits

`new-game.json` holds the native world and pending energy deposits. Each world's `banjo.db` holds market balances, stock, orders and settled deposit receipts, alongside Workshop racks. Player ids scope balances and purchased stock; the world id scopes the database path. Room saves and SQLite files need durable persistent storage together. This architecture runs one authoritative server process per world with local SQLite. It has **not** been qualified for multiple Render instances writing the same world, network filesystems, or a distributed market. A hosted scale-out design needs a single world simulation owner, a transactional network database for market/rack state, and a durable native-snapshot/outbox protocol.

## Verification and next gates

`tests/world_hub_tests.py` opens a generated native world, banks 200 J, checks the solar battery falls by 200 J, retries without a second debit, buys oak, checks personal and shared inventory views and restart, and verifies stale quotes are refused. Its browser journey opens Market from the named-world header and confirms the tab loads. `tests/market_tests.py` checks atomic purchase idempotency, personal-then-shared stock spending, disabled free rack editing in named games and world-time restocking. No constitutive solver changed, so these are economy/integration checks rather than material realism or full energy-conservation certification.

Next: player-owned charging connections rather than access to the shared starter grid, delivery based on world-produced goods, a broader seller/buyer market, personal tech journals, and multi-instance storage/transaction testing. The starter farm is shared infrastructure, not a separate owned panel in each avatar's bag.


**Inventory meters, September 30:** See [screen split and rate semantics](workshop-mode.md#inventory-resources-and-recipes-sources--september-30-2026). Inventory displays private spendable joules separately from shared native solar charge/generation and world motor draw. Banking remains manual; robot currency income is zero and goods output rate is unmetered.
