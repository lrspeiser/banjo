# Visible Workshop workspace and component inspection

Base: main `07aab26eb6ae7c9dbd3c740c1d877c9e848e14cb` plus reviewed
PR #22 at `bd54148d66445e2b9c50c2694cf5d9191c5f761c`.

## User-facing changes

The mode switch is in the top bar. Test has a large canvas and a separate
right-hand setup/result panel. Run, Pause and the timeline live below the canvas,
not in an overlay covering the object. Advanced limits and saved setups are
collapsed separately. Small screens stack the scene and controls.

Choosing a supported situation prepares its actual isolated scene at time zero.
The preview includes the test load/striker or the cart/thermal fixture, not only
the unmodified design. Native lattice geometry is checked before it is shown.
The exact-size rigid preview comes from the compiled rigid package and explicitly
is not marked native-verified until the existing Run adapter verifies it.
Run evaluates the existing bounded native experiment and shows its calculated
states automatically. Calculation has an elapsed-time indicator and keeps the
setup visible. Reset to setup is distinct from inspecting a completed result.
This is bounded calculation followed by inspectable results, **not streaming
live solver control** or a video feature. Late setup answers cannot replace a
newer candidate, test, or component inspection. Completed run responses also cannot
replace a component opened while calculating. Setup temporary files are cleaned
after the native session closes, including errors. The outside world is not advanced.

Opening a component shows a solid, isolated shape, with the camera fitted to its
rendered bounds instead of the whole product. Old section clipping, placement
ghosts and test views are cleared. Small objects can be zoomed into and the
camera's near plane scales with the view. Copy saves the part and shows it.
Clicking a saved component now inspects it without replacing a selected product
part. Replacement has its own explicit button; Back restores the unchanged
product. Saved skin/mechanical settings survive copy, inspection and reuse.
Physically edited recipes have no invented straight-part ports or strength
capabilities: they are explicitly marked as requiring retest.

## Existing PR integration

PR #22 supplies the actual drop/strike/load consequences, native hard-landing
and floor-supported-load corrections, cell geometry for resulting fragments,
and its ground-carry/water changes. The only merge conflict was the status
summary; both summaries are retained. See `world-consequences-checkpoint.md`
for the model assumptions and its original measurements. These are not new
material laws introduced by the workspace UI.

## Verification and limits

The new tests check that six lattice setups have native bodies at time zero,
never send an advance/step/fracture command, and agree with the corresponding
initial drop results for glass, oak and iron. Precise thin rigid setup and
invalid input cases are also covered. Component tests check owner isolation,
read-only inspection, physical-skin persistence and explicit reuse.

Browser regressions now use actual pointer hit testing for the new journeys,
check projected rendered geometry fits inside an unobstructed canvas, exercise
copy/inspection/return without a product revision, delayed setup responses,
load setup/run/reset and narrow-screen component framing. Screenshots are
verification artifacts, not product assets. Existing browser tests remain.

Local Linux native/fast checks are recorded in the work log. Local Chromium
navigation is blocked by administrator policy; browser qualification therefore
uses required Chrome tests on GitHub Actions before publication. No cross-platform
qualification is inferred from that run. The existing native scene/model limits
remain; unsupported custom/articulated tests are not replaced with canned scenes.
No test means general material certification. A copied physical recipe still
needs its geometry, interfaces and mechanical behavior checked on reuse.

## Published verification

The focused native, Workshop and required Chrome browser gate passed.
Run: https://github.com/lrspeiser/banjo/actions/runs/35402468116
