# Native actor-relative carry: experimental rewrite checkpoint

October 6, 2026. Implementation published to GitHub main at **`ddcc584b636e2de0c3903fe06927b4bf9dc4ed8f`**, after source baseline `3a9df0f1`, follows the [audit](banjo-rewrite-audit.md#23-current-review-rewrite-progress-and-remaining-defects) and [native pickup](runtime-pickup-checkpoint.md). This implements another W05/W06 slice in the isolated Rust/native worker. The browser demo and old controller subsystems remain in place.

## Implemented model

Native pickup opts into `native-actor-carry-v1` after the same ray/assembly/grip admission and bounded physical wield. The controller captures the **actual** grip offset and rigid wrist orientation relative to the native actor. It preserves the pickup posture; it does not automatically lift a floor tool into a new ergonomic pose.

Each native substep transforms those desired frames from the actor's actual body pose. Desired grip velocity includes the actor's translation and angular lever velocity. Desired wrist spin follows actual actor spin. The shared `GripPull` law damps against that desired spin; its existing world-fixed default remains zero. No held-body pose, linear velocity or angular velocity is assigned by this carry path. Existing bounded grip force/torque and equal actor reactions move the item. Gravity, contacts and finite strength can obstruct it.

The actor's heading feedback accounts for the carried assembly's actual yaw inertia about the actor, summing member inertia and the parallel-axis contribution. This scales the existing unloaded heading gains without increasing the existing total torque cap. It is a declared controller approximation for a body-relative held load, not a constitutive law or a claim that the assembly is physically welded to the avatar.

Read-only pickup admission now checks necessary quasi-static weight and horizontal load-moment limits using the actual assembly masses, centres, gravity and existing caps. An overweight or overleveraged load returns `insufficient_strength` before custody changes. The 0.2 m iron cube weighs 62.96 kg and, at its fixture's approximately one-metre lever, exceeds the 400 Nm body bound; it is refused. This check does not certify dynamic balance, joint integrity, collision clearance or supported use. Large ledger Inventory remains a separate storage requirement.

Editor/laboratory wield stays world-relative unless explicitly opted in. Successful explicit move/aim/stroke commands relinquish carry authority; an invalid stroke does not replace it. Release and actor removal clear the physical hand. Per-actor hand contexts include carry state in reversible step snapshots. Saved hands carry a versioned local frame; whole reopen restores it idle. Old hands without this field retain their previous world-relative behavior. Unknown/invalid carry frames or a missing actor fail exact reopening; no fresh-world fallback is accepted by the new regression.

The native runner reports `native_carry_version=1`, actual hand observations expose `carrying_with_native_player`, and Rust requires that version alongside pickup admission. Pickup remains pending until accepted physical stepping confirms custody. This does not add a durable receipt/transfer journal or a browser gateway. Engine downgrade of a carry save is not qualified; retain the matching native build.

## Comparative evidence

Windows / MSVC 19.44.35228 / SDK 10.0.26100 / Python 3.13.5 / Rust 1.99.0. Native Release, Rust dev; existing CPU floating-point profile and Jolt pin retained. No material constitutive, terrain extraction, contact law, friction coefficient or physical cap was changed.

The same carry fixture uses a 120 × 80 × 120 mm head, 40 × 400 × 40 mm handle, declared connected grip, existing fixed joint, anchored iron floor, 40 mm cells and dt **1/240 s**. It walks at a requested 1.5 m/s for two native seconds, then walks at 0.3 m/s while requesting a 90-degree turn for two seconds. Actor and actual tool orientation must both turn; custody is checked on every step. Measured output from the final native run:

| Material | Assembly mass kg | X travel m after both phases | Final grip error m | Assembly mass change kg | Measured hand work J |
|---|---:|---:|---:|---:|---:|
| Glass | 4.4800 | 2.99985 | 0.000735839 | 0 | 0.976264 |
| Oak | 1.2544 | 3.00093 | 0.000736485 | 0 | 0.279539 |
| Iron | 14.10304 | 2.98705 | 0.00523184 | 0 | 7.51567 |

Material density/inertia differences are retained. This experiment measures intact rigid carry, not stiffness, grain, plasticity, fracture, wear or fatigue. The floor is an anchored rigid support, not excavatable terrain. It does not establish zero cutting on a new worker's terrain journey; that remains a W06 gate.

New carry position gates are 20 mm after the turn phase and 100 mm in the moving worker fixture; these are interaction tolerances, not conservation tolerances. The desired-frame comparison allows 20 mm for observing the target set before the final substep against the actor's pose after it. Force remains capped at the declared 800 N in the comparative fixture. Existing analytical/constitutive tolerances were not relaxed.

Additional checks cover two real actors carrying distinct bodies in opposite directions; one actor's wrist command/removal leaves the other's hand intact; enabling carry writes no held pose/velocity; exact save/reopen resumes body-relative travel; old world-relative saves remain whole; unsupported saved carry refuses; move/aim/drop relinquish competing authority. Twelve existing pick/shovel/hoe/uncatalogued pickup fixtures at 20 mm cells remain. They are pickup/grip fixtures, not proof of all four tools' productive behavior.

Twelve Rust contract/orchestration tests and twelve real-native worker tests pass, including portable 0.1 m cubes in all three materials, retained matched 0.2 m mass fixtures (20 / 5.6 / 62.96 kg), overload refusal, ownership, retry, crash and owned shutdown. The two registered Rust/native CTest gates and three native pickup/hand/ground suites pass. Formatting, Clippy and source registration (306/306, no exclusions) pass. This is a focused checkpoint, not the full regression or browser/physical-phone acceptance of the new worker.

## Retained browser startup regression

The wider five-case native-walk suite initially failed its new-player journey: its camera moved, but no native actor existed. Repeats passed, so the failure required a controlled reproduction. Holding the first stance report while serving the baseline `3a9df0f1` client against the current native engine produced a premature native request and failed the new assertion. The client had attempted native spawn before the host knew a stance, then silently substituted camera walking during its refusal interval.

The client now waits for the current session's acknowledged stance, does not step an opening replacement, ignores old-session walk results, and stays on the real-body movement path during refusals/retry. The reason remains visible through ordinary action feedback and the diagnostic status. Explicit camera modes remain Menu choices. This removes conflicting fallback authority; it does not connect the browser to the Rust worker or change native physics.

The strengthened real-browser journey holds initial pose delivery, injects a body-admission refusal, asserts zero unbodied camera movement, restores the real endpoint, then checks actual native actor travel and explicit God mode. All five native-walk host/browser cases pass after this repair. The earlier intermittent failure is resolved by a reproduced ordering condition, rather than by loosening a delay or assertion. This is automated Chrome on Windows, not a normal interactive native window or a physical phone result.

All five retained World navigation cases also pass: joined-tool click/chat, cursor/movement transitions, mobile controls from first paint, actual default-body desktop pickup and landscape touch pickup with native custody/reload. The navigation run prints Windows connection-abort exceptions for requests abandoned during browser navigation/closing; assertions pass, but this is not a claim of clean transport diagnostics. The broader release suite and normal interactive native window remain untested at this checkpoint.

## Conservation and remaining physics boundaries

The carry path applies existing hand forces at the real grip and opposite force/torque to the actor. Heading actuation remains a bounded external controller accounted by the existing walk work/impulse fields. Force reactions are implemented; whole-pipeline energy/momentum closure is **not established** by assembly mass sums or hand work alone. A carry conservation experiment still needs actor reaction work, floor/support/contact impulse and dissipation, numerical corrections and the full mechanical-state change in one ledger.

Retained same-condition ground/hand references pass without tolerance changes. The ground drop residuals at 40 mm / dt 1/240 remain glass −0.004325528 J, oak −0.000610494 J, iron −0.027121319 J, within their reported damping bounds. Existing mixed head/oak-handle **unclosed work** remains −0.444883845 / −0.289081497 / −0.0448162138 J. Existing horizontal lifting also reports unclosed work 0.536434654 / 0.377751507 / 0.656609728 J. These are unresolved accounting boundaries, not zeroed or certified by this carry checkpoint.

The earlier carry test exposed slow turning with a fixed unloaded heading gain; adding actual load inertia corrected the moving-turn fixture. A standing turn can still be blocked by passive foot friction in the retained locomotion model. The test now explicitly qualifies **turning while walking**, and that standing-yaw boundary remains open. Neither camera look nor in-place foot turning has been qualified through a new browser.

Next implement native target admission/use/recovery and retained action events; qualify safe acquisition/carry posture and clearance, standing yaw, lost/reconfigured grips, shared terrain use and full reaction/work accounting. Then add stable product/artifact import, durable custody/receipts/checkpoints and ordinary desktop/touch/client journeys. Do not retire Python preparation or browser readiness until those equivalence gates pass. Fast productive digging, anchored constitutive terrain, wet laws and general wear remain required.

## Reproduce

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_live_world_run banjo_c banjo_pickup_admission_tests banjo_hand_stroke_tests banjo_ground_work_tests --parallel 4
cmake --build build/rewrite-foundation --config Release --target banjo_rust_runtime
ctest --test-dir build/local-cell-tools -C Release --output-on-failure -R "^banjo_(pickup_admission|hand_stroke|ground_work)_tests$"
ctest --test-dir build/rewrite-foundation -C Release --output-on-failure -R "^banjo_(rust_runtime|runtime_native)_tests$"
python scripts/check-source-registration.py
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/local-cell-tools/Release/banjo_live_world_run.exe).Path
python tests/native_walk_tests.py -v
python tests/world_navigation_tests.py -v
```

These reuse the isolated configured Windows builds documented in the preceding worker checkpoint; they do not restart the user's demo. Build/source identity is recorded separately from the runtime's currently unrecorded compiled-source provenance.

Local artifact SHA256:

- `build/local-cell-tools/Release/banjo_live_world_run.exe`: `df987e7d33665c26b34e61e22c6b45c520284e0dda899ca6548b947907d5afe7`
- `build/local-cell-tools/Release/banjo.dll`: `45b2894c68dba6edfa5c293035a81ad4257786050cf70e27008e93f128f68835`

Implementation/source revision: `ddcc584b636e2de0c3903fe06927b4bf9dc4ed8f`, pushed by ordinary fast-forward to GitHub main. This publication note is a subsequent documentation commit. The `C:/play` demo is unchanged; main publication does not install this native build there. Local passes do not assert that hosted CI has finished this revision.
