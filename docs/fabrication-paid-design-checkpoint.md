# Reviewed paid designs — October 1, 2026

## Implemented

Configured worlds now route Recipes **Make** and Lab **Make it** through the
reviewed material/energy/work panel. New recipes, building-block drafts and
saved designs can review **Make** without nominating a carried item. Carried
items keep **Remake**, including current source topology/condition checks and
the original retained. The Lab remains empty until an explicit item/design
selection.

Review does not debit stock or energy, reserve work, or install anything.
Funding retains explicit personal/shared choice, real native battery limits and
lost-response retries. Start requires enough buffered energy and current stock;
Run consumes the declared work; Place admits the native output. A saved design
is never treated as an existing physical item with a fabricated health reading.

New-item plans freeze the exact candidate and bind the authenticated player.
The accepted job and installation receipt durably retain `make_source` owner
and draft hash. Another player cannot start a private plan or control/place the
job. Wrong make/remake operation, expiry and corrupted saved draft bindings
refuse. Existing source-bound remakes and request retries remain compatible.

HTTP and both MCPs expose the same `plan_make` / `start_make` contract. World
MCP is 1.17.0 and platform MCP 1.20.0; native ABI remains 25. No native source,
law, tolerance, body healing or display-name material preset change.

Sources: [reviewed plan adapter](../playground/fabrication_remake.py),
[process ledger](../mcp/fabrication.py), [Lab/Recipes UI](../playground/workshop.js)
and [native/browser regression](../tests/fabrication_remake_tests.py).

## Evidence and boundaries

Windows/MSVC Release, unchanged native runner/library, 40 mm cells and
`dt=1/240 s`. Matched glass/oak/iron fixed geometry consumes respectively
2.56 / 0.7168 / 8.05888 kg and 256 / 71.68 / 805.888 J under the declared
100 J/kg shaping estimate. All three produce the correct native mass, retain
the frozen material after caller-side mutation, survive whole-world reopen and
replay the accepted Start once. The make owner/hash are durable. These costs
are authored approximations, not glass cutting, wood grain or iron forming laws.

Chrome extends the actual configured funding-to-use journey: save the recovered
field-pick design, open Recipes, choose **Make**, review without any debit,
explicitly fund stock and energy, Start, Run and Place. The new 50 mm / 1.925 kg
oak pick costs another 192.5 J. No carried source is bound. Peer pause is refused
for the actual ownership reason; the old parked field pick stays unchanged.
JavaScript exceptions remain zero. The existing actual native stroke and
lost-stock/energy acknowledgement retries stay in this same acceptance case.
Screenshot: ignored `build/resource-flow/lab-paid-saved-design.png`.

Focused native/browser lane: **6/6 pass in 26.751 s**. API documentation parity:
**12/12 pass in 0.192 s**. Workshop tabs: **9/9 pass in 1.048 s**. Full fixed suite:
**59/59 pass in 62.292 s**, recorded in ignored
`build/resource-flow/paid-make-20261001/report.json` at base `b8f95ea` plus this
dirty source scope, with unchanged runner/library hashes. Native source registration remains
287/287; no C++ additions need registration.

The affected ordinary unconfigured shortage/collect/Make and recursive route
lane passes **3/3 in 23.656 s**, preserving the previous stock debit. One
thumbnail response was aborted by Chrome during navigation; no failing case
or changed physics is inferred from that server socket log. Refreshed own 8770
Chrome entry/condition/Inventory/carried Lab/empty Lab checks pass with zero
JavaScript exceptions and no implicit process or finite source. Fresh preview:
`http://127.0.0.1:8770/world?world=36f566f0ee0544c187be5386a2fc394d`.

Ordinary unconfigured fresh worlds retain their previous authoring Make, which
debits stock but has no manufacturing energy law. No default finite source or
process is silently granted. Next connect an explicit finite starter capability
and migrate ordinary Make, AI progression and supported machine manufacture
together; activating the funded-room guard prematurely would block those paths.
Supported mixed-material interfaces, exact rigid forming, damaged-tool-to-use,
fatigue/joints, physical transport and full conservation remain separate gates.
All fourteen requirements stay active: **four verified, ten partial**.
