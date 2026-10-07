# Whole-tool entry observation: experimental rewrite checkpoint

October 6, 2026. Source baseline `2195a948`. This advances native target inspection for W06; it does **not** resolve repeated excavation or replace the browser engine. The retained World on 18890 and material laboratory on 18891 continue running their earlier binaries. Published revision is recorded below after verification.

## Implementation and physical meaning

`NativeToolClearance.cpp`, registered in `banjo_fastlattice_scene`, queries Jolt's actual collision shapes for every member of the current fixed tool assembly. It transplants the measured relative poses into the declared held-root orientation and grip frame at first surface entry: the existing ready grip lowered by 60 mm. Compound voids remain voids; a bounds box does not replace the native shape. Internal assembly pairs are excluded; terrain, avatars and other products remain queryable. The response reports the deepest external overlap, its native component/body IDs and world-space witness. Only overlaps greater than the existing 3 mm observation tolerance count. At most 64 distinct bodies are accepted.

This is a static observation, with no timestep, motion, impulse, contact work or granted material release. It predicts a meeting rather than deciding whether a stroke can finish. It does not certify preparation, rotation, lateral travel, recovery, deformable geometry or the next proxy rebuild. The current measured assembly transforms are retained; future flexible behavior is not inferred.

An initial implementation refused every overlap. The comparative test demonstrated that this would incorrectly block two successful glass repeats. That veto was removed before publication. Actual native contact, work and yield remain authoritative. The existing four iron repeats still execute and fail the strict acceptance gate. No material-name branch, constitutive change, narrowed head, collision exemption, arbitrary launch or pose/velocity assignment was added.

The native runner now advertises `tool_use_admission_version=2` and emits `banjo.tool-preview.v2` with nullable `entry_clearance`. Rust requires this version and validates bounded part counts, finite witness/depth, nonzero body identity and consistent ground/body identity. A predicted overlap may accompany an admitted request; `measured_yield` remains false. Earlier refusals do not invent an entry observation. Previews remain actor-private, with existing retry and command ownership. This is an explicit protocol change; older v1 workers/runners must be upgraded together.

## Comparative evidence

[Structured results and executable hashes](evidence/tool-entry-observation-2026-10-06.json) record Windows x64, MSVC 19.44.35228 Release, Rust 1.99.0 dev and Python 3.13.5. All materials use 20 mm tool cells, 100 mm terrain columns and the same declared geometry. Queries advance no time; physical cycles use dt = 1/240 s. Oak remains a comparison laboratory material, excluded from playable inorganic worlds.

In a prepared 100 mm column, 60 mm below its neighbours:

| Material | 40 mm head release m³ / contact work J | 280 mm head observation / actual outcome |
|---|---|---|
| Glass | 0.0000233632 / 0.883691 | 57.476 mm overlap / zero release, `no_contact` |
| Oak | 0.00000986754 / 0.604264 | 57.476 mm overlap / zero release, `no_contact` |
| Iron | 0.000138564 / 2.306467 | 57.476 mm overlap / zero release, `no_contact` |

Prepared-query snapshots are byte-for-byte unchanged. Twelve flat-ground queries retain zero time/work/removal/debris and the existing material-derived assembly masses. Matched compound-shape cases check an open fork, actual leaf contact, a rotated offset grip, internal-pair exclusion, unchanged body state and duplicate-member refusal. Twenty-query means range 0.00661–0.021775 ms in the final local observation; these exclude transport and are not qualified latency percentiles.

Repeat entry overlaps occur for glass pick/shovel (4.051/7.738 mm) and all four iron families (7.906–12.821 mm). Glass still completes all four repeats; oak all four. Iron still releases zero on its four repeats. Static overlap alone is therefore not an outcome classifier. Tests retain tool mass, source/debris quantity closure, recovered grip, cancellation and actual physical termination checks. Those checks do not close momentum/energy transfers: the previously reported large raw iron unclosed mechanical/work values remain an investigation gate. No conservation tolerance changed.

## Verification and remaining work

- Two rebuilt native CTest entries pass: admission and native use. The strict `banjo_native_tool_use_tests --require-repeat-yield` deliberately exits 1 for the four unresolved iron cases.
- 23 Rust tests, formatting and Clippy pass. 17 actual-native worker tests pass, including twelve first tool cycles and three material-specific prepared-pit previews through Rust, with private actor projection.
- Source registration passes 312/312, with no exclusions. Selected executable hashes and full comparison measurements are retained in the evidence file.
- Full regression, interactive World migration, physical phones, fast digging and full W00–W17 qualification remain open. No new UI usability claim follows from these native tests.

Next implement conservative contact over the actual working footprint and neighbouring anchored material, carry exact constituent histories through native collision/settling, and close support/hand/contact/release/numerical accounts. Then require positive repeated excavation and measure the player's 10 ft digging task before advertising useful speed. Durable state, gateway/client migration and remaining material laws are separate unfinished stages.
