# Regression audit, October 5, 2026

## Status: in progress

The demo is available on port 18890. This is **not a full-suite green result**.
The audit began at `c25f53b6aebcdd3cdaedc70eccc93a6c0c2be79f`; verified
fixture and API-contract repairs were subsequently applied. Native binaries
and laws are unchanged by those repairs. Initial failures and corrected reruns
are retained separately rather than relabeled as original passes.

## Environment and coverage

- Windows, MSVC Release, CMake Visual Studio 2022; `BANJO_BUILD_LAB=OFF`.
- Every configured target built with
  `cmake --build build/agent-column-terrain --config Release --parallel 4`.
- Source registration passes: all 304 C++ sources are registered, no exclusions.
- All 237 registered CTest groups were launched without label exclusions.
  Six extended physics groups and the performance gate are included.
- Remaining ordinary groups also run separately so long simulations do not
  prevent gameplay verification. Results must be deduplicated by test name.
- CI suites and repository assertion suites outside CTest run from an isolated
  tracked-source archive, with browser checks required and current native
  Release binaries. This archive has no `.env` or Git credential fallback;
  external provider traffic is blocked. Optional CAD dependencies and live
  provider trials are reported separately, never counted as passes.

Build output is `build/pickaxe-preview/Release`. The live runner SHA-256 is
`44F74C1729E8C2BB01B9448A64C76C314E00500E3129CB821F1582D84D404026`, matching
the owner's installed native bundle. Lab window/input, Linux capture, real
phone/human audio and cross-GPU determinism are not qualified by this run.

## Verified repairs

| Finding | Repair and evidence | Boundary |
|---|---|---|
| Column tests counted legacy host piles | Count native cells/mass, require no Inventory credit before collection, then verify private collection/replay/restart | Four affected registered groups pass in 49.40 s, including API/client checks below; source-cell totals are not full momentum/energy closure |
| Client extraction fixtures lacked browser dependencies | Provide storage/location and the native-piece picker; retain queue, hover, touch, release and native collection priority assertions | All ten client cases pass |
| Existing thumbnail routes absent from public contract | Register and document the actual authenticated HTTP endpoints and bounds | Unchanged API documentation suite passes |
| Upgrade test required exactly ten free rock hits | Require no invented work from legacy calls; exercise finite funded work and save/replay under glass/oak/iron | Full upgrade suite passes 11/11 in 7.850 s |
| Legacy migration tests required obsolete v5 schema | Expect v6 while preserving every mass/history/ownership check; reject invented cells, work and carriers | Full installation suite passes 40/40 in 17.572 s |

The comparative upgrade test retains the same declared tool geometry and rock
target for glass, oak and iron: 25 cm ground cells, 5 cm source cells and 50 kJ
funded requests. Glass/iron complete the 0.015625 m³ / 37.5 kg cut at 468,750 J;
oak is refused without consuming work. Static unfunded wire commands advance
none of these quantities. This tests the existing experimental work-cut and
hardness gates, not calibrated constitutive fracture or tool wear.

The generated-layout fixture now distinguishes authored processor foundations
from unrelated assemblies. Existing 0.3499 m clearance, route and reach checks
remain. A new support-only vertical assertion allows 1 micrometre of native
contact roundoff (observed 0.283585 micrometres), consistent with existing native
point-contact tolerances. The earlier main archive reproduces the original
foundation failure with the same runtime.

## Actual placement defect

Lab placement stopped at the first native stability refusal, although it already
had eight candidate spots. It now retries the explicit "would not stand here"
refusal, as the existing catalog Make path does. Native stability checks, paid
job ownership and the final error after all candidate failures remain intact.

An actual goal journey refused three spots (26° tipping, 154 cm sliding and 19°
tipping), accepted the fourth, then packed the item into Inventory and retained
goal completion after reload. Full tracked world-hub and starter-goal suites
pass 4/4 each in 29.232 s and 43.743 s; the layout method passes both seeds in
1.773 s. See the [UI checkpoint](ui-chat-verification-checkpoint.md) for evidence.
Inventory/Progress selector fixtures follow the consolidated navigation without
restoring actions in Goals.

## Ordinary and supplemental run follow-up

All **230 ordinary registered groups** have now completed across the primary
run and the separate remaining batch: **222 initial passes and eight initial
failures**, deduplicated by test name. The remaining batch itself finished
54/58 in 1,085.52 s. All eight failed groups now have verified affected reruns.
The AI-player Market method passes in 4.979 s and its native-owned, read-only
watched character journey passes in 120.166 s with corrected accessible-name
and source-selection assertions. This is a repaired
coverage record, not a fresh all-green run on a single published revision.

Recipe guidance passes its full three cases in 18.023 s after following the
explicit Materials & build details disclosure. The two affected private-ground
browser cases pass in 11.089 s after waiting for finished page startup before
clicking. Their original failures and the actual subsequent HTTP 503 are retained.
The uncertain Store request keeps its exact ID, material and volume through
reload, creates one matching lot on Retry and clears pending state only after
success. The other seven private-ground cases passed in the original full group;
the two-case rerun is not described as a new full nine-case run.

One extended group, network-adaptive, passed in 713.78 s; other extended groups
and the final performance gate are still pending. Supplemental coverage exposed
additional older browser journey failures. The combined world-page journey hit
its 900 s outer limit after attempting 104 of 105 discovered cases, including
imported Workshop cases. Its failures and incomplete coverage are retained in
`build/full-regression-extra/world-page-incomplete.json`; individual recovery
runs retain their original per-method bounds. No timed-out suite is counted as
a pass.

## Still pending

- Final ordinary, supplemental and extended totals, including every skip,
  timeout or unresolved failure.
- Performance gate after competing test workloads finish; an under-load
  measurement is not an isolated performance qualification.
- Two navigation module-fetch failures did not reproduce in isolated checks;
  a transient real Save hit-test failure is retained for follow-up.
- The existing mounted-target strike timing gate and other newly exposed
  failures must remain visible until resolved with supported inputs.
- Adaptive compression, affordable rapid rock progression and the timed 10 ft
  excavation gate remain unimplemented or unqualified. Constitutive ground
  fracture, granular/wet coupling and full pipeline conservation remain open;
  separately paused R3 work stays paused.

Local evidence is in `build/full-regression-progress.log`,
`build/remaining-ordinary-progress.log`, `build/regression-repair-results.xml`
and `build/full-regression-extra/`. Private worlds, credentials and build
artifacts are excluded from commits.
