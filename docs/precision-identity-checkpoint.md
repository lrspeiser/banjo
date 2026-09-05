# Saved runtime position precision

Local source `78871772d248cf4b702921c555e6ace6a82cef79`, September 5, 2026. Not pushed or merged; full goal active.

CreatorWorld and StarterWorld now serialize version 5. The shared physics signature includes `position_bits`, derived from the compiled Jolt `Real` type through `JoltWorld::positionPrecisionBits()`. CreatorWorld retains its existing compiler/runtime/profile signature and adds precision. StarterWorld now records that same material/runtime signature in addition to its existing gameplay rules, resources, motion, receipts and remembered designs/assemblies. Creator inspection and rigid recipe-test reports also carry the updated signature. This is not a complete solver/cache fingerprint.

Version-5 loading requires exact signature-value equality before constructing the world. A 32-bit world rejects in a 64-bit build and vice versa; missing/unknown signature fields and changed material profiles reject. Normal same-configuration save/load and candidate transactions retain state, inventory, authoring history, gameplay receipts and draft revisions. The application remains on its existing 32-bit configuration for now.

## Legacy compatibility boundary

Versions 1 through 4 omit position precision. Their existing structural migration remains supported only in the historical 32-bit application configuration, producing v5 metadata without introducing progress or resources. A double-position build rejects those unrecorded-precision saves before construction. This is a compatibility policy for legacy files, not evidence that an arbitrary old file actually came from a 32-bit binary; experimental legacy 64-bit files cannot be distinguished from the old metadata. Explicit conversion/provenance is still required before promoting double positions. No converter or permission to silently reinterpret a saved world is added in this checkpoint.

Creator v1-v3 migrations retain their existing history/draft semantics; v4-v5 both retain assembly declarations and revisions. Starter v5 has 14 top-level fields, including physics_signature; v4 remains 13 and earlier migrations retain their previous shape. The gameplay rules string is unchanged because the precision metadata does not redefine stamina, experience or cutting rules.

## Verification

Both complete builds pass: default Windows Release 23 suites in 18.56 s; separate double-position headless Release 24 suites in 20.53 s, including the runtime cohesive accuracy gate. Creator fixtures collect and create glass/oak/iron objects, then check matching-precision roundtrip, changed/missing/unknown identity rejection, legacy v4 behavior and unchanged live state. Existing three-material assembly/history tests remain, with v1-v3 migration tested in the supported 32-bit configuration and explicit rejection tested in 64-bit. Starter tests check shared identity, opposite precision, missing precision, changed density and legacy v1-v4 behavior; existing three-material resource/draft/transaction checks remain.

A separate four-way CLI check used real newly built 32- and 64-bit executables and newly saved v5 worlds containing collected glass, oak and iron lots:

| Saved bits | Reader bits | Result |
|---:|---:|---|
| 32 | 32 | Exit 0; exact JSON roundtrip |
| 32 | 64 | Exit 1; signature mismatch before output save |
| 64 | 32 | Exit 1; signature mismatch before output save |
| 64 | 64 | Exit 0; exact JSON roundtrip |

All input save files remained byte-identical during the checks; mismatching loads preserved an existing output sentinel unchanged. These CLI checks cover CreatorWorld. Starter cross-precision rejection is covered by signature mutation in backend tests, not a separate pair of native cross-build launches.

The default starter and workshop were stopped for relinking and restarted successfully using their existing workspaces. No new native input verification or double-position UI promotion is claimed. Windows 11, MSVC 19.44 x64 Release, CMake 4.1.2, Jolt 5.6, raylib 6; required frame-control, busy-wait and static-MSVC-runtime flags remain OFF. The prior 11/12 single-position cohesive accuracy failures remain relevant; this metadata change does not repair them.

Next implement an explicit, reviewable precision conversion that retains source state and records changed physics identity, then promote and verify the double-position application. Preserve full material/motion/resource checks and saved-state compatibility. Live joint/surface coupling, physical manufacturing energy, realistic cutting, full cache identity and every remaining goal gate are still open; all 40 scorecard rows are retained.
