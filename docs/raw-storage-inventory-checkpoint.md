# Inventory raw storage and unassigned recovery — October 2, 2026

## Implemented

Inventory shows carried sand, soil and broken rock as thumbnail/quantity cards.
**Store** moves that material into personal raw storage. Stored cards offer
**Retrieve** for up to 5 kg, the remaining quantity or free carrying capacity,
whichever is smaller; a full bag disables retrieval. These are saved ledger
lots, not physical bins or finished fabrication stock. Material cards still
link to filtered Recipes.

**World load · unassigned** has **Recover to storage** on each material.
Recovery debits only the older anonymous native account and creates a personal
lot with `source_actor: ""`. It never infers the original gatherer or takes a
peer's load. Existing lots without owner metadata remain explicitly shared,
labelled **Shared · original owner unknown**; retrieval records its actual
recipient. New private lots are hidden from peers' Inventory and refuse peer
retrieval or receipt replay.

The authenticated fabrication route binds the player to native carrying.
Actor contexts survive staged session replacement and clear on exit. Optional,
validated `raw_lot_ownership` / `raw_return_owners` extend older saves without
changing their bulk packet quantities, density, form or thermal declarations.
The bounded MCP `fabrication_recover_ground` uses the same transaction.

Pending browser transfers keep their exact quantities/revision/request ID in
session storage. A compact **Retry transfer** action survives page reload;
other material transfers wait for that retry. Native debit, raw lot and owner
persist together. On a lost save acknowledgement, the adapter accepts the
staged world only if reading disk proves the exact native snapshot, receiving
ledger and spec. It still reports the acknowledgement failure; subsequent
retry replays once. This prevents shutdown from overwriting a committed
receiving state with the older live state. Genuine save failures retain the
original world and balances.

## Verification and limits

Windows / Python 3.13 / Chrome / existing MSVC Release CPU engines in separate
`build/agent-object-strike/Release`; native runner from `fa84f14`, library from
the earlier storage build. No C++ source, material law, timestep, force limit
or physics tolerance changes. Generated scene uses 50 mm cells / 1/240 s.

Twenty-one affected checks pass in 30.810 s. They cover authenticated Store/Retrieve, private peer refusal before
replay, disk failure/retry, capacity refusal, lost durable-save acknowledgement,
graceful full server restart and exact provenance. Actual Chrome clicks Store,
reloads a failed pending transfer, clicks Retry/Retrieve and recovers both
unassigned sand and soil; quantities and private ownership match the server.
Existing private-ground and native raw rock/soil/sand rollback/reopen checks
remain in the regression run. Source registration is 297/297, no exclusions;
Python compilation and JavaScript syntax checks pass.

Evidence: `build/resource-flow/raw-storage-regression.log` and
`build/resource-flow/raw-storage-inventory.png` (ignored local artifacts).
The screenshot was visually inspected. Browser closure can abort an outstanding
Market response; checked runtime exceptions are empty. Source fixtures use the
bounded native terrain-edit dig lane, not a newly qualified player harvesting
method. The retained breaker regression uses actual native rock work.

Raw storage preserves existing local volume/mass accounts; physical containers,
cargo consequences, heat transport and conversion into useful manufactured
stock remain separately bounded. This completes the requested Inventory storage
and older unassigned-load controls, not all of R1. Next are supported
ground-to-usable-stock routes and exhausted-input guidance. R3 remains paused.
Existing preview servers were not restarted.
