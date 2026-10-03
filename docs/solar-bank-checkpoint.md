# Automatic solar banking checkpoint — October 2, 2026

## Implemented

Player-built solar arrays include an automatic bank connection on their battery. The same optional `bank_reserve_fraction` declaration is available through the bounded Lab `add_power_part` store tool for LLM-created machines. The range is 0.05–1.0; the built-in array defaults to 0.05. Machine descriptions identify the connection. It is host economy metadata, stripped from native machine declarations, and does not claim a modeled physical connector or export-power law.

Installation binds the connection to the authenticated builder, actual native store ID/name/body and panel IDs/name/bodies. It persists separately from the bounded 64-entry installation history. Older paid built-in arrays with retained ownership and component mappings acquire the default connection at a checkpoint. Sources without that evidence are not assigned to a visitor. The shared starter farm continues to use the explicitly labeled manual Bank button.

At a saveable world checkpoint, automatic exports are whole joules bounded by both:

- Collected sunlight minus the store's total given energy: other machine/fabrication work has first claim, and previously spent sunlight cannot cash out starting battery charge.
- Actual remaining charge above the declared battery reserve.

The native `draw` receipt must match the selected source and requested joules. The debit, pending deposit and connection counters are saved with the native snapshot before SQLite credits the private wallet. Unique deposit receipts make retries and crash recovery idempotent. A failed save retains the paired in-memory debit/claim; restarting before it was saved restores the previous native state and discards the unsaved claim. A saved claim can settle after a crash before SQL credit. Manual deposits recognize receipts already settled by a checkpoint.

The server clock uses the same checkpoint path while no page is watching. A closed/unopened world or stopped server earns no fabricated offline income. Market and Inventory show owned array banking, solar input, storage/reserve and total banked energy; displayed solar input is generation, not a promised wallet income rate. The shared solar Inventory card measures its own store's panels. AI Guide observations and instructions explain these rules. Market refreshes wallet/source readings every five seconds without initiating transfers.

## Verification

Windows / Python 3.13 / Chrome / existing native Release binaries under `build/agent-object-strike/Release`; source base `89cbb019b45fb5e7dec1b867d5efec04fddb7a93` plus this checkpoint. Native laws/binaries are unchanged.

- 14 Market checks: seven existing market/accounting cases plus seven automatic native cases covering two owners, reserve, starting charge, other work, no-sun income, source disappearance, legacy binding, invalid bindings, save failure, restart and crash between native save and SQL credit.
- 11 Workshop authoring/tab checks, including chat-authored connection bounds and native export exclusion.
- One finite paid native solar-array build/installation/reopen check.
- Three private guidance contract/HTTP/concurrency checks.
- Three Chrome journeys: paid array → private Market/Inventory displays → full server restart, existing private meter reads, and failed manual-bank reload/retry.
- One existing native personal Market purchase/banking/restart check.
- Four existing opening-goal checks, including the ordinary Market → Recipes → World browser journey.

37 focused checks pass. The explicit two-source experiment at dt=1/240 s credits 76 J and 26 J to separate wallets, leaves the 50 J reserve intact, and measures a maximum store-charge-plus-wallet-minus-initial-charge-minus-collected-sunlight residual of 1.99e-13 J. No other loads run in that residual experiment. Manufacturing tests consume finite authored fixture supplies and actual native work energy; they do not qualify fresh-map acquisition of every array input. JavaScript/Python syntax, UTF-8 decoding, source registration (297/297), local document links and diff whitespace are checked.

Browser evidence: `build/workshop-navigation/solar-auto-bank-market.png` and `solar-auto-bank-inventory.png`. Preview 8771 is restarted with the existing user world retained.

## Boundaries and next work

This is a measured energy-to-currency receiving path. It adds no material law, general full-pipeline conservation claim, real electrical bank connector, robot sales, source trading, offline time catch-up, authentication overhaul or fleet-scale hosting qualification. Solar-input readings are instantaneous. Physical reserve/export priority can be configured in recipes; there is no new wiring UI. Older sources missing ownership/component evidence require explicit recovery rather than automatic assignment. Broader recipe supply, wear/repair, autonomous first-goal decision recovery and R1–R6 remain at their existing status.

Source: [Market](../playground/market.py), [checkpoint](../playground/server.py), [room store](../playground/room_store.py), [installation](../playground/workshop_install.py), [machine declarations](../mcp/workshop_machines.py), [products](../mcp/workshop_products.py), [Lab tool](../playground/workshop_chat.py), [guidance](../playground/game_guidance.py), [screens](../playground/workshop.js).
