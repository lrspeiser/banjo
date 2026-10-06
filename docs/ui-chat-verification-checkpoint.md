# Lab, shared chat and guidance verification

October 5, 2026. Independent Windows host/UI follow-up to the
[typed Build checkpoint](build-lab-chat-checkpoint.md) and
[voice checkpoint](voice-shared-chat-checkpoint.md).
Verification base: main `249f350d`, with the host/test changes described here.
The integrating checkpoint records the final published revision and demo
installation; this note by itself does not claim either has happened.

## Repair

The old empty copper-intake regression expected `process-input`. Current
processing guidance deliberately offers `order-rover` when a declared digging
routine knows the missing material's seam and the destination intake. The
failure did not demonstrate that unrelated guidance had displaced processing.
The actual defect was that this more specific recommendation omitted the
missing-intake explanation. `process_guidance._next` now retains that blocker
for both `order-rover` and `await-delivery`.

The regression checks the actual compatible routine and intake, exact bounded
order text, unchanged unissued orders, current empty input, recipe and retained
blocker. It also covers an already busy delivery and the generic source-help
fallback when no compatible rover is available. No order, goods, skill,
processing batch or physical state is awarded by reading guidance.

## Measured checks

Windows 11, Python 3.13.5, Node.js and Chrome. Tests create temporary worlds
and browser profiles; the owner's world and ambient microphone are unused.
Native bundle: `C:/play/bin`. Runner SHA-256
`d547855a13889b13292952c928f64e0839a1304c3f216d6337506eeaa9b2e7a0`;
platform CLI SHA-256
`5a49e7f5d771756573acd034bc0f6cb61a06e7f9312fa02da0a6b8d1fb8c8817`.
This UI follow-up changes no native binary or material law.

| Check | Result |
| --- | --- |
| `game_guidance_tests` via `python -m unittest` | 11 passed, including the formerly failing empty intake case |
| `build_lab_chat_tests.py` | 4 passed in 24.157 s (final rebuilt native runner) |
| Saved source, carried source and responsive hubs in `workshop_navigation_tests.py` | 3 passed in 23.975 s |
| `voice_browser_tests.py` | 2 passed in 11.981 s |
| `voice_tests.py` | 4 passed |
| Voice client, voice controller and guidance renderer Node suites | 3 passed |

The paid journey selects an empty Lab's supported pick, edits its actual
geometry through chat, reloads the draft, saves it, reviews supplies/energy,
runs paid native work, collects the output into private Inventory, opens that
carried source in Lab and equips it through the ordinary World bag control.
The responsive journeys retain saved edits and ownership boundaries through
World/Progress/Build navigation. Pointer hit checks require the clicked element
to be reachable, including the landscape chat input.

World help begins hidden. F1 exposes a read-only next-action card without a
provider call. A deliberate Ask AI click produces one mocked provider call;
five subsequent authenticated status reads leave the count at one. This is a
call-boundary regression, not a provider-latency measurement.

The compact rover exposes one card and directs the same chat audience to the
real native rover endpoint. Typed `stop` yields the visible authoritative
reply and native `waiting`. Voice regressions use a mocked media/WebRTC
transport to enter the same Guide, candidate-edit and rover routes, retain
default Audio Off, exercise output On/Off/reload, authentication and failure
recovery, and report no browser runtime exceptions. The earlier live synthetic
audio result remains bounded by the voice checkpoint; no new live provider or
human listening test was run here.

Milestone PNGs, visually inspected under `build/workshop-navigation/`:
`build-lab-desktop.png`, `build-lab-landscape-chat.png`,
`paid-pick-equipped-landscape.png`, `rover-landscape-chat.png`,
`explicit-world-guide.png`, `selected.png`, `named-product.png`,
`hubs-progress-1440x900.png`, `hubs-progress-844x390.png` and
`hubs-progress-390x844.png`. Screenshots are local build evidence, not committed
artifacts. The completed browser journeys have zero runtime exceptions.
Navigation/reloads cancel some in-flight HTTP requests, producing the already
documented Windows connection-aborted diagnostics.

## Boundaries and next gates

This establishes the listed UI and authenticated routing behavior on the
retained native bundle. It is not full-suite, material-realism, conservation,
cross-platform physics, full construction or physical phone audio validation.
The source-registration guard must be rerun after concurrent native source
wiring and before the integrating checkpoint publishes. Physical phone/human
voice acceptance and broader roadmap gates remain open.

## Concurrent native matter UI follow-up

The integration also replaces a raw native body ID in successful equip notices
with the same authenticated product label shown by the hand and bag. The
ordinary selected/edit/paid collection/equip/targeted rover browser journey
passes after that polish (16.917 s on the retained bundle).

The new `physical_matter_ui_tests.mjs` executes the adapter with the actual
vendored Three.js math and scene classes. It checks native numeric material
classes, occupied cell sizes and local centers, supplied position/orientation,
real mesh ray hits and ignored receipt velocity. Compact native slabs are
visible immediately; one read-only metadata request upgrades them to native
cells. Compact pose refreshes preserve that metadata without per-frame
requests. Late metadata cannot rewind current poses or restore removed matter.
Failed collection retains the body and exact request ID for retry.

Tool tests check default Energy assist Off, object contact without a ground
reservation, completed empty-wallet refusal, and uncertain replies. Retrying
keeps the original ground point and `target_name: null` even when the next click
points at an object. A preflight refusal retains the reservation; only a cut
receipt clears it. Turning assistance Off while a reply remains uncertain
blocks further tool requests with a visible instruction to enable assistance
for that exact retry. The Menu preference persists after explicit selection
and reload. Successful native release feedback says “Loose … · click to
collect”; it does not claim that released matter entered Inventory.

The separate native browser fixture passed in 8.853 s against an immutable
copy of the rebuilt Windows runner (SHA-256
`44f74c1729e8c2bb01b9448a64c76c314e00500e3129cb821f1582d84d404026`).
It declares a flat 25 cm column map with 25 cm soil above rock, a supplied iron
cutter and two finite 1 MJ work budgets. Real native mesh pointer clicks
collected 25 kg soil and 37.5 kg rock through the authenticated HTTP route.
A joined peer saw no private stored lots. Selecting rock in Inventory opened
the Stone field pick source with its concrete arm and oak haft in Lab without
creating a manufacturing job. No browser runtime exceptions occurred.
This experiment verifies rendering, collection and source navigation; it is
not ordinary fresh-player supply or energy acceptance.

The browser exposed missing funded-room route admission for collection and
read-only geometry; those player routes were added. The renderer retains
confirmed collected IDs across native session rotation, so late compact or
full pose packets cannot restore a collected body. A separate regression
covers this late-packet case. Rock recipe filtering now matches its concrete
constituent instead of reporting that no recipe uses rock.

Milestone PNGs in `build/workshop-navigation/` include
`native-soil-click-collected.png`, `native-rock-loose-desktop.png`,
`native-rock-loose-landscape.png` (844 × 390),
`native-rock-click-collected.png`, `native-rock-pick-source-lab.png` and
`native-rock-pick-review-make.png`.
Visual inspection found a Stone field pick readiness mismatch between the
generic world grid and supported precise formation. The crafting agent
corrected its fixed-adapter validation; the final browser run verifies its
exact Ready card state and enabled Prepare control after opening Review Make.
This source-navigation test creates no job; actual paid formation and native
use are covered by the separate raw-crafting checkpoint.

### Private-ground regression follow-up

The two isolated nonbrowser private-ground failures now pass in 5.245 s with
the final runner SHA-256
`44f74c1729e8c2bb01b9448a64c76c314e00500e3129cb821f1582d84d404026`.
The capacity/restart test now checks the current exact ground snapshot v6 and
its debris v1 payload; its independent loads, spoof refusals, whole restore and
ledger residual assertions remain. The partial processing-preview test
invalidates the plain guidance cache around its observation mock and asserts
that the mock ran. It retains the exact 0.5 kg result, checks intact input
facts, and retains the private peer/source and unchanged-state assertions.
The old 0.5-versus-5 kg failure was reproduced against source archive
`249f350d` with the retained older demo runner: the cached 5 kg view skipped
the mock. No host behavior was changed for these two test corrections.

Commands use `BANJO_LIVE_ENGINE=C:/play/bin/banjo_live_world_run.exe`,
`BANJO_LIBRARY=C:/play/bin/banjo.dll`, `BANJO_BROWSER_TESTS=required` and
`PYTHONPATH=tests;playground;.` for `python -m unittest game_guidance_tests -v`.
Other suites execute their named files with `-v`; Node suites use
`node --experimental-default-type=module --test` with
`tests/voice_client_tests.mjs`, `tests/voice_controller_tests.mjs` and
`tests/player_guidance_ui.mjs`.

## Full regression follow-up — October 5, 2026

The generated layout's two-seed horizontal-clearance failure was reproduced
against source archive `249f350d` and current source `c25f53b6` using the same
immutable final native runner `44f74c17…404026`. The generator deliberately
places each mill/smelter over its own separately installed foundation pad.
The test now identifies those exact generated source pairs and checks their
vertical separation. The new support-pair check allows `1e-6 m`: the observed
initial mill contact roundoff was `2.83585e-7 m`. Comparable signed-gap checks
use `1e-6 m` in `tests/native_point_contact_tests.cpp:202`, `:207`, `:221`,
`:271` and `:275`; restored position uses the same tolerance in
`tests/precise_rigid_live_tests.py:500`. Unrelated `0.3499 m` horizontal
clearance, hauling corridor and processor reach assertions are unchanged.
Both generated seeds pass in 1.774 s (`build/generated-layout-prepared.log`).

The menu fixture now enters the shared Inventory hub; the goal fixture uses
Progress and opens the Chapters drawer with a real pointer click. Its actual
banking, six oak purchases, paid stool preparation/build, World packing,
labels, persisted completion and reload assertions remain. The updated
journey exposed an actual Lab Make defect: its first sloped placement refused
with 26 degrees of tipping during the unchanged native 2 s stability check.
Lab Make now retries the existing eight candidate spots for the same explicit
support refusal already handled by catalog Make. It commits only an accepted
native preview; if all spots refuse, it returns the final error and retains
the ready paid job.

The actual fixed journey passed in 19.313 s. Native preview refused `[3, 0]`
(26 degrees tipping), `[3, 1.6]` (154 cm sliding), and `[3, -1.6]` (19 degrees
tipping), then accepted `[4.6, 0]`. No terrain pin, stability tolerance change,
free material, or simulation-clock acceleration was added. Evidence is in
`build/goal-placement-observations.json`, `build/starter-goals-prepared.log`
and the `build/starter-goals/` milestone screenshots. The owner world and demo
were not used.

Two supplemental navigation runs had dynamic-import fetch failures under the
broader concurrent run. In isolation, the empty Lab/missing item/reload case
passed and neither module-fetch exception reproduced. Saved selection first
failed to reach its real Save button, then passed its unchanged Save,
restored draft, clear/reload and console checks in an isolated diagnostic run
(11.330 s). These transient failures remain recorded in
`build/workshop-module-fetch-isolated.log` and
`build/workshop-save-probe.log`; no console assertion was removed and no
production asset or layout repair is claimed from those results.

The final checks ran the applied **tracked files**, with
`BANJO_BROWSER_TESTS=required` and the immutable final native bundle under
`build/ui-native-verification-bin/`, without request overrides. Full
`tests/world_hub_tests.py` passes 4/4 in 29.232 s; full
`tests/starter_goals_tests.py` passes 4/4 in 43.743 s. The generated layout
method passes both seeds in 1.773 s. Logs are
`build/world-hub-tracked-full-final.log`,
`build/starter-goals-tracked-full-final.log` and
`build/generated-layout-tracked-final.log`. The relevant source copy, base
revision, working diff and SHA-256 manifest are retained in
`build/ui-regression-tracked-snapshot/`. These targeted checks do not establish
that the broader full regression run has completed.

### Recipe supply guidance follow-up

The remaining ordinary recipe-guidance browser failure expected a canvas
click to open a materials drawer. In the consolidated Build screen the canvas
correctly selects that recipe into Lab; the separate **Materials & build
details** summary owns its supply disclosure. The fixture now uses that
summary at all four disclosure points, without a production change.

Full tracked `tests/recipe_guidance_tests.py -v` passes **3/3 in 18.023 s**
against published source `868d6c9b` plus this fixture correction, with
`BANJO_BROWSER_TESTS=required`,
`BANJO_LIVE_ENGINE=build/pickaxe-preview/Release/banjo_live_world_run.exe` and
`BANJO_LIBRARY=build/pickaxe-preview/Release/banjo.dll`. The runner SHA-256 is
`44f74c1729e8c2bb01b9448a64c76c314e00500e3129cb821f1582d84d404026`.
The original legacy recipe-supply scope remains: actual shortage disclosure,
World pile location without teleporting, collection into private stock,
material-debited Make, unchanged shared stock, native installation count,
hopper/yield/deposit guidance, targeted wire-coil market offer and absence of
browser runtime exceptions. Exact transaction and provenance assertions were
retained. Fresh finite-workbench formation remains covered by its separate
fabrication and starter-goal suites.

Evidence is `build/recipe-guidance-tracked-full-final.log`,
`build/resource-flow/recipe-guidance.json` and its shortage, supplied, made,
ore-source and market screenshots. The owner world and demo were untouched.

### Private-ground browser fixture follow-up

Both affected tracked browser methods in `tests/private_ground_tests.py`
pass **2/2 in 11.089 s** with browser verification required and the current
Release runner/DLL (runner SHA-256 `44f74c17…404026`). This is a targeted
two-method result, not a new full-suite claim.

The private account view now checks the actual **Ground load** section
heading. It retains the exact per-material quantities, 80 kg total, Store
controls, separate unassigned account and peer-privacy assertions. The old
heading was sought inside the cards container, which contains material cards
and quantities rather than a heading.

The original Store test clicked during initial Inventory startup. An ignored
diagnostic observed pointer down/up/click retargeted to `#ws-centre`, zero
receiving Store HTTP requests, zero save-failure mock calls and no pending
transfer. The fixture now waits for the declared page startup-ready flag,
an enabled control without an inert ancestor, and a reachable real pointer
target before clicking. This corrects the fixture's early click; no production
storage or retry behavior was changed. Intermediate artifact attempts had
mistakenly attached these helper waits to the separate glass-input method;
the final tracked diff contains no change to that method.

With the corrected actual Store click, the receiving save reports HTTP 503
and the save-failure mock runs once. Retry appears, survives reload with the
exact original operation, material, volume and request ID, then creates one
stored lot with that request ID. The pending record clears after successful
retry. Existing retrieve, anonymous-load recovery, private peer, quantity,
rollback and browser-exception checks remain. A blank notice in the early
503 audit was captured after Retry had appeared and before the guard finished
its notice update; the subsequent reload/retry journey passes.

Evidence: `build/private-ground-tracked-browser-final.log`,
`build/private-ground-store-success-audit.json`,
`build/private-ground-store-earlyclick-summary.json` (an explicit summary of
the earlier diagnostic, not a raw replay), the retained failing
`build/private-ground-store-audit.log`, and
`build/resource-flow/raw-storage-inventory.png` /
`build/resource-flow/private-ground-inventory.png`. No owner world or demo
process was used.
