# Native admission and confirmed Rust pickup

October 6, 2026; source parent `4db96843`. Published implementation on main: `e8b43ca3537920e2055006afee31f5417e11e840`. Extends the [Rust worker](runtime-worker-checkpoint.md) with an experimental W05 physical pickup slice. Browser integration, carry/use control and save/reload remain open. The running `C:/play` demo is unchanged.

## Changes

`LiveWorld::pickupAdmission` is a read-only query on the selected native actor. It validates a finite unit ray of at most 2 m, checks its origin against the actor's actual eye position, resolves the visible native hit and scene instance, checks existing hand/other-player ownership, rejects anchored fixed assemblies and applies the existing physical cargo limit when present. The native avatar model is currently the existing 1.7 m/70 kg cylinder: eye offset 0.77 m above its centre, permitted origin discrepancy 0.2 m. These are declared model/input bounds, not support for arbitrary avatar geometry.

Configured tool points on the fixed assembly supply their validated connected grip; attached blade grips are a fallback, and ordinary unconfigured props use the actual hit surface. No pick/shovel/hoe/display-name branch grants eligibility. The same native shoulder/1.8 m arm helper governs admission, legacy `wield` and subsequent physical arm release. `wield` now refuses an unreachable native grip before changing custody. Laboratory/editor hands without a native avatar retain their existing semantics; that interface must not become the ordinary-player path.

The runner adds `pickup-check` and `pickup` operations and reports `pickup_admission_version=1`. The Rust adapter checks that capability before admitting pickup. A missing capability is an explicit refusal. The atomic native pickup operation rechecks eligibility immediately before wielding, between simulation steps.

Rust reports an admitted pickup as **pending**. Only an accepted physical batch that still reports that actor holding the requested instance emits a correlated **applied** completion. Lost grip is rejected; native rollback retains pending rather than granting success. Repeated rollback expires and releases the unconfirmed hold after 480 attempted ticks (120 four-step batches); this is an attempt bound, not a two-second wall-time guarantee. Drop/Leave cancel pending pickup, and a retry preserves the cancellation instead of resurrecting it. Completion/pending capacity is bounded to 64; existing in-memory receipt/restart limits still apply. There is no durable transaction claim.

## Verification

Windows / MSVC 19.44 / SDK 10.0.26100, Python 3.13.5, Rust 1.99.0. Native Release, Rust dev. The native runner and shared C library compile with the existing audited CPU floating-point profile. The new C++ file is registered and compiled as `banjo_pickup_admission_tests`; the source guard passes **306/306**.

- **Twelve Rust checks pass**, including pending/accepted-time confirmation, Drop cancellation, retry after cancellation, lost grip and repeated rollback expiry.
- **Ten real-native worker tests pass**, including matched glass/oak/iron prop pickup, a later physical observation retaining the hold, actual Drop, contested ownership and another player retrieving after Drop. Existing clock, independent movement, input refusal, kernel crash and owned shutdown checks remain.
- **Three native CTest suites pass**: new admission, existing hand stroke and existing ground work. Admission covers an object visible within 2 m but beyond physical arm reach; spoofed origin, missing target, non-unit/oversized ray, unchanged query snapshot/custody, early legacy-wield refusal and fixed-assembly contention. Generic labelled pick/shovel/hoe/uncatalogued fixtures all resolve the declared handle grip and retain it through an actual native step.

The matched fixed head/handle fixtures use 0.02 m native resolution and dt 1/240 s. Head width is 0.20 m except the 0.28 m shovel; other geometry and native actor conditions match. Measured assembly masses:

| Material | Pick / hoe / uncatalogued fixture | Wide shovel fixture | Pickup/release mass residual |
|---|---:|---:|---:|
| glass | 6.4 kg | 7.68 kg | 0 kg |
| oak | 1.792 kg | 2.1504 kg | 0 kg |
| iron | 20.1472 kg | 24.1766 kg (rounded) | 0 kg |

Read-only admission preserves the complete native snapshot byte-for-byte in these fixtures. Density differences produce the expected mass differences; these checks do not measure stiffness, grain, strength, fracture or digging productivity. Oak remains a material-reference laboratory fixture, not a new organic gameplay item.

The retained ground-work regression at dt 1/240 s / 0.04 m resolution reports its existing drop energy residuals and integrator/damping bounds:

| Material | Energy residual | Existing damping bound |
|---|---:|---:|
| glass | −0.004325528 J | 0.008098328 J |
| oak | −0.000610494 J | 0.001395404 J |
| iron | −0.027121319 J | 0.058831232 J |

The same retained mixed-head/oak-handle fixtures still report **unclosed work** of −0.444883845 J, −0.289081497 J and −0.0448162138 J respectively. Passing those regressions is not full-pipeline momentum/energy closure. No tolerances, constitutive law or contact force model were changed; this checkpoint changes admission/custody acknowledgement. Native test output remains under `build/local-cell-tools/Testing/Temporary/LastTest.log`.

Selected rebuilt runner SHA256: `60b44a74109e0381b05b71409a033e7d39e7393d73e04864febfc5c258898081`. It was built from this working-tree checkpoint; runtime metadata still does not infer compiled-source provenance or actual ABI from the checkout.

## Remaining gates

The native fixture demonstrates generic configured **pickup**, not the productive use of every tool family or a full LLM authoring journey through this new worker. The Rust worker currently opens native scenes without the old host's full authoring/bootstrap pipeline. Names remain transitional instance references; stable product IDs, declaration import and custody/save migration are still W07/W08 work.

W06 next needs body-relative carry/working frames, one native preview/use state machine, retained actual completion/release events and finite tool work coupled to the constitutive terrain reference. No fake launch velocities, shatter animation or position teleport was added. Thin constitutive laws, full transfers, fast sustained digging and the 10 ft shaft remain open. Browser/touch/phone, ordinary input loop, save/reload and full regression acceptance still precede replacing the demo or deleting its old controllers.

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_live_world_run banjo_c banjo_pickup_admission_tests banjo_hand_stroke_tests banjo_ground_work_tests --parallel 4
ctest --test-dir build/local-cell-tools -C Release --output-on-failure -R "^banjo_(pickup_admission|hand_stroke|ground_work)_tests$"
cmake --build build/rewrite-foundation --config Release --target banjo_rust_runtime
ctest --test-dir build/rewrite-foundation -C Release --output-on-failure -R "^banjo_(rust_runtime|runtime_native)_tests$"
python scripts/check-source-registration.py
```
