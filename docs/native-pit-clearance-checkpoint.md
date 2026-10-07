# Tool width and narrow pit clearance

October 6, 2026. Source baseline `f88abc7d` on main. This comparative native regression identifies why the current tool controller can admit a target and then perform no work. A 40 mm head reaches and cuts a prepared 100 mm wide pit; a 280 mm head stops on its untouched surroundings in glass, oak and iron. Production laws, controllers and the demo are unchanged. The full-width physical contact and terrain rewrite remain required.

Tests, evidence and CI fixture repairs are published on GitHub main at `5aa3c7a8`. Native production artifacts remain those recorded by the Rust tool-use checkpoint; only the two affected native test targets are rebuilt here.

## Declared experiment

Windows/MSVC 19.44.35228, SDK 10.0.26100; native Release, dt 1/240 s, 20 mm tool cells and 100 mm dry-soil columns. Start with the existing upright fixed head/handle fixture on 0.75 m flat soil, no water/discharge. The initial pit is one column 60 mm below its neighbours, at x 0.65 m, z 0.15 m. This is explicitly prepared geometry via the existing native dig API, not a claim that a tool physically excavated the setup. Its removed quantity enters the existing bulk ledger and is excluded from the measured action result.

Only head and declared working width change: 40 mm versus 280 mm. Head height is 80 mm, depth 40 mm; handle is 40 × 320 × 40 mm. Fixed connections and actuator/terrain settings are unchanged. Materials retain their densities, so width also changes physical mass. The experiment compares complete geometry/mass changes, not width with artificially fixed inertia. It does not compare material stiffness, fracture, grain or wear.

| Material | Head width mm | Tool mass kg | Lowest tip m | Contact work J | Released m³ | Native seconds | Outcome |
|---|---:|---:|---:|---:|---:|---:|---|
| Glass | 40 | 1.60000 | 0.667403 | 0.883691 | 0.0000233632 | 0.166667 | Cut and recover |
| Glass | 280 | 3.52000 | 0.749999 | 0 | 0 | 1.129167 | No contact |
| Oak | 40 | 0.44800 | 0.671896 | 0.604264 | 0.00000986754 | 0.162500 | Cut and recover |
| Oak | 280 | 0.98560 | 0.749993 | 0 | 0 | 1.141667 | No contact |
| Iron | 40 | 5.03680 | 0.647558 | 2.30647 | 0.000138564 | 0.275000 | Cut and recover |
| Iron | 280 | 11.08096 | 0.750000 | 0 | 0 | 1.154167 | No contact |

The requested floor is y 0.69 m and surrounding terrain is y 0.75 m. Every broad head remains at that surrounding surface and never creates a measured bite in the target. All narrow heads cross the requested floor, retain the grip, release actual native constituent cells and recover. The [structured evidence](evidence/native-pit-clearance-2026-10-06.json) records exact results and selected test/native artifact hashes.

Tool mass changes remain below 1e−10 kg; released-cell volume versus reported action volume differs by less than 1e−9 m³, cell/body mass by less than 1e−8 kg, and terrain volume residual by less than 1e−9 m³. These quantity checks do not close full momentum, angular momentum or energy accounting. The prior [unclosed-work gate](runtime-tool-use-checkpoint.md#matched-material-experiment) remains open; no conservation tolerance changes are made.

## Source cause and required rewrite

`ToolTerrain::finish` restricts player-controlled column detachment to the selected column. `ToolTerrain::meet` uses the centre tip's column surface to activate the reduced point response. The complete physical head may collide with higher surrounding columns before that centre tip reaches the chosen surface. The new contrast supports this geometry mismatch as a cause of the repeated-iron failure; it does not prove every no-contact case has that cause.

Narrowing every tool or disabling surrounding collisions would preserve the mismatch. The replacement must use the actual working geometry and contacted material patch:

1. Derive the candidate contact footprint from the physical head/cells and declared working frame. The clicked target anchors intent; show/check the actual bounded footprint and retained terrain revisions.
2. Activate the contacted patch with neighbouring attachment and material history. The higher contacted edges need their own supported response; the centre cannot receive invented work from unmodelled surrounding contacts.
3. Assign one response per contact, with finite tool/actor reactions and torques. Integrate work and constitutive state before releasing genuinely disconnected matter. Keep nonworking tool surfaces in ordinary collision.
4. Transfer exact released cells and their complete physical state to native components. Recontact, settling, collection and further digging must use those same constituents.
5. Keep the existing wide-head repeat tests, this prepared-pit contrast, matched glass/oak/iron accounting and desktop/touch requested-target tests. Add orientation/uneven ground/obstruction/refinement tests and the declared sustained-use/10 ft excavation gate.

These are W06/W08/W09 requirements, not implemented capabilities in this checkpoint. The existing free solid-patch reference needs boundary attachment and finite source coupling before it can replace the reduced terrain adapter. Soil/sand and rock require declared supported laws; a solid fracture model cannot silently stand in for granular flow.

## Verification and CI audit

Both native fixture users are rebuilt: `banjo_native_tool_use_tests` and `banjo_tool_use_admission_tests`. Their scoped CTest entries pass in 1.79 s, including the new six-case contrast. Source registration passes 309/309. Strict `banjo_native_tool_use_tests --require-repeat-yield` still exits 1 with the original four iron repeat failures. The assertions and scenarios are retained.

The preceding GitHub [native-controller CI run](https://github.com/lrspeiser/banjo/actions/runs/37562441113) failed Workshop's stale Camp stool mass expectation (2.5088 kg versus actual 3.9311 kg). The current inorganic recipe has a 240 × 240 × 5 mm iron top and four 15 × 15 × 235 mm legs: 0.0004995 m³ × 7,870 kg/m³ = 3.931065 kg. The repaired test asserts the iron material, all five dimensions and this analytical volume/density calculation with the original four-decimal tolerance. All eleven Workshop tabs tests pass locally; no product recipe or material constant changes are made.

That same CI run recorded 124 core passes and one failed `banjo_knowledge_tests` entry before terminating with exit 143 while `banjo_valley_live_tests` was starting (249 tests selected). Three synthetic guidance sessions omitted the `state` attribute now read by native-grid advice, causing four errors and a dependent query-count failure. The fixtures now declare empty state for the unsnapped cases, and a new case checks actual grid-centre advice coordinates before native resource survey. All 54 knowledge tests pass with the rebuilt local native library. The later exit 143 cause remains unidentified and the core run is incomplete. Later jobs were skipped. The `f88abc7d` run was pending when inspected. Local scoped passes are not a full CI/regression result; CI process termination and the unexecuted gates remain open.

No helper/subsystem retirement, browser migration, interactive-window or physical-phone qualification is claimed. Main publication and the older `C:/play` demo remain separate.
