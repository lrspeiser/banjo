# Workshop prototype installation checkpoint

Base: `23cbc854d5504d0aaca0df33fcc62ef9d2f9147e` on main.
This advances goal 3 with an explicit first adapter, plus the state-preservation,
UI and regression portions of goals 1, 2 and 10. It does not complete inventory-
funded fabrication or general articulated/mixed-material installation.

## What is implemented

Workshop Details now has **Place prototype in world**. Open a flat-floor room
(such as the yard), leave it paused, select a design, acknowledge authoring mode,
choose world X/Z, preview, and confirm. The returned link rejoins the running
room with the new physical object; this is not a saved recipe alone or a test
fixture in a different world.

The initial adapter creates one **monolithic, single-material structural solid**.
It rejects missing/disconnected components, mechanisms, containers, mixed
materials, terrain/water, declared gas regions and timed heaters. It reports
that strength has NOT been certified and does NOT pretend to manufacture from
inventory. No inventory, soil or fabrication-energy ledger is debited. Resource-
funded installation remains unsupported, rather than silently giving it zero cost.

The compiler uses the room's existing cell resolution. Exact canonical Matter
is translated once by an integer grid offset, with the full object's bottom on
the floor; physical curve endcaps are retained. Requested and applied placement
are both shown. The occupied cells are encoded losslessly into joined boxes,
round-trip checked, admitted by the existing scene validator, and verified against
the actual native cell offsets and material BEFORE any simulation advance.
Conservative current-pose collision bounds include both the occupied cells and
the rigid collision envelope. They may refuse a fit through a hole; they must
not place into an occupied object. New joints or support on another body are
outside this adapter.

## Transaction and persistence

Preview owns a temporary native session, carries the original state into the
candidate scene, verifies it, then closes it. It neither replaces the original
session nor writes the room. Its server-side token binds the candidate, world
session, scene, full physical snapshot, spec, inventory, geometry and placement.
The token lasts five minutes, with at most eight retained previews per server.
Client-supplied geometry or a claimed passing verdict cannot substitute for it.

Commit requires that same source state, repeats staging and checks, then writes
the complete room/snapshot/inventory/receipt with the existing atomic room-store
replacement. Only AFTER that succeeds does it publish the new live session and
close the old one. A native verification or disk failure leaves the old session,
room and inventory intact. HTTP world operations are excluded during the
transaction (ordinary operations remain concurrent with each other); direct
native calls are excluded by the session lock. Writer admission times out rather
than waiting indefinitely behind a busy request. Authentication precedes the
world-access gate. No fallback to an older snapshot or a reset-from-spec is allowed.

The most recent 64 installation receipts are persisted with the room. Retrying
the same request/token returns its receipt rather than adding a second object,
including after server restart. Concurrent retries are also tested. Old preview
tokens that lack a receipt cannot be re-executed after restart.

Every existing serialized body and topology record, motor, control, stored energy,
hand state, damage and plastic state is checked. A native hinge's `held.at` is a
DERIVED single-precision angle readout: rebuilding the identical poses was
measured to alter it by one float32 ULP (3.725290298e-9 rad in the exercised hoist).
Only that readout allows up to four float32 ULP; its limits, anchors, reference
frames and all other compared fields remain exact. No solver tolerance or
material law was changed. Contact warm-start memory is not carried, so future
step-for-step identity is not promised.

A new read-only `carry_readiness` snapshot field reports pending heaters and gas
regions. This catches a scheduled heater even BEFORE its first step (when the
ordinary body report still says heater power zero). Installation refuses old
binaries lacking this field and refuses state the carry adapter cannot preserve.
An already completed heater's stored body heat is preserved by the changed-scene
carry. The pre-existing ordinary full-restart thermal limitations remain; this
checkpoint does not change that restart implementation or preserve omitted
thermal audit history.

## Verification

Local Linux checks: 12 new pure boundary/concurrency tests and 15 native
installation tests. Cases cover exact glass/oak/iron prototypes, unchanged preview,
actual post-install stepping, physical curves and grid translation, stale state
and inventory, wrong session, expiration, collision, rejected unsupported designs,
failed disk/native checks, a parked inventory item, a held item, a running hoist's
joints/controller/battery/clock, completed heating, scheduled-heater refusal,
persisted receipts/restart, and simultaneous retries. Existing Workshop and room-
store checks are also run; the publication gate records its executed results.

The local browser serves the application with HTTP 200, but managed Chromium
blocks localhost navigation (`ERR_BLOCKED_BY_ADMINISTRATOR`). Browser verification
must therefore pass on GitHub Actions before publication. Three added Chrome
regressions exercise preview/consent/confirm/retry and return to the rendered live
world; a stale-world refusal; and an out-of-order preview after selecting a
different product. The eight previous browser regressions remain required.

The existing native room-carry and thermochemistry suites pass locally. The
broader native live-world suite reported no fracture in its second-break scenario;
the unchanged main revision passed that same scenario and its complete live-world
suite. The patched build subsequently passed its complete live-world suite in isolation
as well (local exit 0); no assertion was weakened. The earlier failure is retained
in the evidence rather than being described as a uniformly green full-suite run. This is not a full CTest or cross-platform claim.

## Next gates

Inventory-backed fabrication needs a real material/process/energy transaction,
not merely the current whole-item hands/bag model. General installation must
carry explicit material interfaces and articulated mechanisms, add terrain-
support placement, preserve all transient thermochemical state, and associate
validated capability evidence with the installed runtime object. Those remain
open. The current prototype creation is deliberately and visibly authoring-only.

## Published verification

The GitHub Actions gate passed the existing native carry and thermochemistry
suites, the 195-test fast Workshop gate, seven native bench tests, 15 native
installation tests and all 11 required Chrome browser regressions. Room-store
and authenticated HTTP regression suites also passed. This is a focused gate,
not a full CTest or cross-platform claim.
Run: https://github.com/lrspeiser/banjo/actions/runs/35301195695
