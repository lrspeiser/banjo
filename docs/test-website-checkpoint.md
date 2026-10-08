**Latest delivery, October 8:** The [contact audit](voxel-contact-audit-checkpoint.md) supersedes the original native checkpoint below. The live website now exposes actual normal/friction contact work, anchored support impulse, linear momentum residual and contact count. The manifest pins physics `5e01124f4401cb9e412e51a2c9953f75163f73c3`, SHA256 `6b22cfb5171602946ebc25759bfb09a2b763bc9683a1d388fc148a52a6c580bc`. Twelve analytical checks, eleven completed native experiments and six scoped CTest entries pass; the glass-ball refusal remains visible. The ordinary browser drop and archived contact diagnostics agree. This measurement update does not implement plasticity or close the full energy/angular momentum accounts.

# Test website delivery — October 8, 2026

## Implemented interface

The owner's checkpoint contract is recorded in [AGENTS.md](../AGENTS.md): each
user-facing update must reach the actual local test website with browser proof.

The original [checkpoint evidence](../client/voxel-lab/checkpoint.json) pinned native physics
revision `20d6e597c42e8ef1945efe8ca7b4759b4dc51afe` and the final verified executable
SHA256 `e46c7afabbaf117f6d0a94946a94fa0875817837be8d088062910494b6bc1660`.
This UI/gateway checkpoint adds no constitutive model or dynamics change.

The [gateway](../scripts/voxel-lab.py) exposes `/api/checkpoint` with the actual
native hash, checkpoint evidence, Git website revision, local edit flag and
server restart requirement. The native match is computed from executable bytes;
test evidence is not silently reassigned to a different binary. Session JSONL
headers retain the same build metadata alongside original native/asset hashes.
Metadata/asset responses use `Cache-Control: no-store`.

The [world](../client/voxel-lab/world.js) has a compact build button opening an
optional update panel: changes, passed/blocked checks, separate website/physics
revisions and the five remaining stages. It starts closed. A missing endpoint,
mismatched binary or pending server restart produces an explicit warning; test
results are then labeled as checkpoint-only evidence. A matched build confirms
identity, not a passing glass-ball experiment or calibrated physics.

Physics & record displays actual accepted native spring damping, numerical
elastic diagnostic, spring work residual and native computation time. It remains
explicitly an incomplete energy account. The expanded panel is on the right so
it does not intercept setup controls; opening either information panel closes
the other. A single Step reports acceptance rather than implying continued
simulation. A malformed character in the original HTML was repaired to valid
UTF-8.

## Verification scope

Gateway regression checks the metadata hash, no-store header, actual Git revision,
deliberate mismatched checkpoint rejection of verified status, independent native
sessions, bounded requests and exact stored response/build provenance. The existing
native binary is reused: no physics rerun is implied by these presentation changes.

Desktop browser verification exercises a deliberately stale binary then the
verified binary, opening/closing status, ordinary native Step/Drop and live
diagnostics. Landscape 844 × 390 layout has an accessible header and independently
scrollable setup/status panels; a real phone has not been qualified. Console
has no captured warnings/errors. The ordinary default glass drop completes at
2.000 physical seconds, 40 broken faces, 12 connected sheet pieces and all 107
original cells. The displayed 1.412 J spring damping, 48.755 J numerical elastic
term, 0.118 J spring residual and −92.923 J unclosed energy match the native audit;
the account is still incomplete. Before/Live restores the actual initial/final
states without replayed physics. Screenshots are local excluded evidence.

Five existing scoped CTest entries, including the extended gateway checks, pass
in 2.57 s. Source registration passes 326/326 with no exclusions; changed links
and whitespace checks pass. This is not a full repository regression.

Physics status and numerical/material limitations remain in the
[spring audit](voxel-spring-loss-checkpoint.md) and
[native world checkpoint](voxel-impact-world-checkpoint.md). The five-part physics
objective remains unfinished. Local logs/screenshots/binaries stay excluded from
Git. Restarting the disposable 18893 laboratory resets current experiments but
preserves their archived JSONL; unrelated player servers/worlds are left alone.
