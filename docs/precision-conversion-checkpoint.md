# Explicit 32-to-64-bit position conversion

Local source `3bd8b740c88c8169092488b808d326177e075b04`, September 5, 2026; not pushed or merged. Full platform goal remains active.

The shared offline conversion library supports CreatorWorld and StarterWorld. `normalizeSavedWorldJson` uses the current build's normal compatibility and migration rules to produce a current v5 save. `upgradePositionPrecisionJson` runs only in a 64-bit-position build and accepts only v5 with recorded 32-bit positions and matching compiler/material/runtime profiles. Legacy or unrecorded precision must first be normalized in its compatible historical 32-bit build. Same-precision conversion, downgrade and profile changes reject.

An upgrade returns a review package containing the exact source document text, the converted world, both signatures, world kind, zero simulation steps and a state-preservation receipt. It changes the precision identity in a candidate, runs the full destination world validator, and requires the resulting JSON value to equal that candidate. Thus positions, velocities, geometry, resources, XP/stamina, history, receipts, drafts and revisions cannot silently change as part of conversion. No physical timestep, resource action or live publication occurs. The receipt documents that future trajectories may differ; it does not claim preserved solver caches, contact manifolds or corrected historical numerical errors. It is a separate review artifact, not a new persistent gameplay-history entry.

## Command-line workflow

Use the 32-bit-position binary when legacy normalization is needed:

```text
banjo_precision_convert normalize INPUT.json NEW_V5_32.json
```

Use the double-position binary for the explicit upgrade:

```text
banjo_precision_convert upgrade NEW_V5_32.json NEW_PACKAGE.json
```

The package's `converted_world` is the new save, while `source_document` retains the original input to the upgrade. Keep the original legacy file as well. Normalization and upgrade never overwrite an existing output; exclusive file creation also rejects a same-path request or a racing existing writer. Validation finishes before output creation. A failed storage write may leave an incomplete output file, so this export is not claimed to be crash-atomic or a live-world transaction. Input is bounded to 1 MiB/depth 24 with duplicate-key rejection; review packages are bounded to 4 MiB.

## Verification

Both complete builds pass: default Windows Release 24 CTest suites in 19.03 s; separate double-position headless Release 25 suites in 20.27 s, including the retained cohesive accuracy gate. The new suite takes 0.07/0.14 s respectively. Glass/oak/iron creator fixtures contain collected stock, a created object and one simulated tick; starter fixtures contain a real pickup and its gameplay receipt. Tests retain exact source text, compare all non-signature state, reload the converted world, leave live source state unchanged, and reject wrong host/identity, repeated upgrade, legacy direct upgrade, profile changes, missing precision, invalid material ledgers, duplicate keys, oversized and ambiguous inputs. On the 32-bit build the upgrade rejects rather than fabricating a 64-bit result.

Real CLI checks used the existing creator workspace's v4 save and starter workspace's v5 save. Both were normalized into new files with the 32-bit binary, converted with the 64-bit binary, extracted into new test saves and normalized/reloaded by the 64-bit binary. Every non-signature JSON value was retained; original input bytes remained unchanged. Repeat output, same input/output path and wrong-host upgrade all returned exit 1, preserving prior files. The CLI result artifact includes input SHA-256 values for reproducibility; these are checksums, not signatures or authenticity guarantees.

The converted copies and review packages are exported alongside this checkpoint. The running applications and their original workspace files have not been replaced. Windows 11 / MSVC 19.44 x64 Release / CMake 4.1.2 / Jolt 5.6; existing raylib settings are unchanged. No new native input or double-position UI verification is claimed.

Next build and verify the double-position application against converted workspace copies, make the supported default precision explicit, and retain recovery packages. Then continue finite-area joints, complete surface responses, physical work-source accounting and realistic branch cutting. The single-position cohesive accuracy failure remains documented; this conversion tool does not repair the old runtime. All 40 scorecard rows and all remaining full-goal gates remain retained.
