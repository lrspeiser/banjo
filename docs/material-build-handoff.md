# Material-to-build handoff — October 2, 2026

The owner requested stopping at the current checkpoint and publishing to main.
The verified implementation is `0801d3f461333facafdadb2c97b2bd805e264dba`,
with publication record `2422ce4`, both already on GitHub main.
[Broken-rock storage evidence](material-build-storage-checkpoint.md) records
67 passing host/API checks, two native suites and source registration 297/297.
This handoff adds no implementation, physics validation or preview update.

## Unfinished acceptance experiment

A draft fresh-world HTTP/native journey at that implementation used generated
seed 851269740, an empty paid workbench, actual rover mining/delivery and copper
processing. It collected the output into one player's private stock, saved and
reloaded a full-size battery-powered mine lamp design, and funded its required
0.5 kg copper from that player's collected supplies. A second player retained
zero copper. Glass funding and finite iron purchases/restocking also ran.

The 133.808 s test failed during a later 500 J solar bank request at native time
488.99999999963745 s. The response was:

> The banked energy awaits a durable world save; retry this request id

The persistence reason was `Banked energy is not in the matching native snapshot`.
This is a failed acceptance result. Final lamp construction, operation and full
server restart were not reached or qualified. A meter/report precision mismatch
is a hypothesis; its cause has not been established. Preserve the receipt check
and exactly-once debit/credit behavior when investigating.

The unfinished test is preserved locally as the ignored patch
`build/checkpoints/material-build-acceptance-draft.patch`; it is not published
as a passing regression. Restore it with `git apply` when resuming, then run
`fabrication_remake_tests.LabRemake.test_fresh_mined_processed_personal_copper_funds_saved_lamp_use_and_server_restart`
with the recorded native runner/library environment from the storage checkpoint.
The local failure log is `build/resource-flow/material-build-lamp.log`.

## Next item

**Continue R1: fix the solar-bank durable-save mismatch, then finish the actual
collection → processing → private output → funded build/use → restart journey.**
Retain the original design dimensions and finite trader stock. Broader R1 work
still includes player delivery to machine inputs, ground-to-usable-stock paths,
exhausted-input guidance and earlier unassigned-load recovery. R1 is unfinished;
R3 damage/reuse and wear remain unfinished and paused. R4–R6 remain on the
[working list](player-experience-checklist.md#remaining-work).
