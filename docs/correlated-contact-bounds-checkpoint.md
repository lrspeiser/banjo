# Correlated native contact bounds

October 9, 2026. Implemented read-only CPU geometry and conditional affine bounds; **reduced execution, strong sheet impact and realtime remain open**. Base: main `1e3fa2509c4f07f4c8a2dbbde77613b2a43b4a76`. This checkpoint follows the [object representation design](object-representation-design.md) and [persistent-field checkpoint](persistent-fields-and-lab-controls-checkpoint.md).

## What a user can test

Open `/coupled`, expand **Inspect / save / tests** beside the 3D scene, and choose **Inspect vibration basis**. The supported glass sheet is displayed and all 54 vibration modes are prepared privately. The inspector shows the unchanged physical time, checked interval, uncertain contact sites, gap-width reduction and calculation cost. Preparing the basis does not advance or alter the world. **Reduced motion: Not admitted** remains explicit. Run/replay/reset controls remain beside the scene on desktop, phone portrait and landscape.

This is an inspection test, not a completed smash demonstration. For falling and rebound, choose **Fall & rebound** and **Drop & rebound · 2 s**. A connected sheet's unresolved contact/trajectory gates must be closed before its reduced motion can replace the detailed solver.

## Implementation and assumptions

- `src/physics/CoupledCpuApi.cpp` adds a bounded read-only 34-double/site differential from the existing native contact geometry. It retains canonical pair gradients, the actual sample lever, target-local coordinates and compensated axial gaps. Capacity/nonfinite/allocation refusal does not modify caller output. No force law, coefficient or convergence tolerance changed.
- `scripts/coupled_modes.py` projects relative translation and target-local sample motion into the complete basis before interval evaluation. Exactly equal frequencies are combined before taking extrema, preserving shared-motion cancellation. Nearby unequal frequencies remain separate.
- Continuous extrema include interior oscillation, zero modes and bounded unstable modes. Local box signed-distance bounds remain valid through face/edge/corner and coordinate-sign changes. A finite Cayley rotation remainder and target-frame cross term are included; rotation is not silently linearized away.
- The new bounds intersect the existing absolute-travel bounds. Expensive correlated checks are applied to the previously uncertain sites. Geometry/state/history keys must still match the preparation exactly.
- These are conditional bounds on the declared all-mode affine/Cayley path, with FP64/libm/matrix-product allowances and outward rounding. They are **not** a formal directed-libm certificate or a bound on the nonlinear world trajectory. Broad SAT changes, unilateral contact events and constitutive branch changes remain separate gates.

The independently reviewed finite rotation allowance uses `||C(t)-I-[t]x|| <= |t|²/2` and `||C(t)-I|| <= min(|t|,2)`. Target-local motion includes relative translation, source lever rotation and target-frame rotation. Source/target common motion is retained in the linear observations; the nonlinear rotation remainder is deliberately retained.

## Comparative evidence

Matched native CPU experiment: nine connected 10 mm cells, fixed supports, 0.1 kg iron ball with 10 m initial gap, gravity 9.81 m/s², 1/240 s host step, partitioned flight, existing reference contact law. Inspect both the initial state and the state after one accepted detailed host step. All 54 modes remain. Each interval checks 2,808 native sites: 2,692 remain separated and **116 remain uncertain**, before and after the tighter calculation.

| Sheet | Initial width / old width | Loaded width / old width | Linux envelope cost, initial / loaded |
|---|---:|---:|---:|
| Glass | 0.084770 | 0.067048 | 7.93 / 7.63 ms |
| Oak | 0.078903 | 0.064524 | 7.50 / 7.94 ms |
| Iron | 0.072095 | 0.065872 | 7.62 / 10.10 ms |
| Ice | 0.066049 | 0.063174 | 7.87 / 7.79 ms |

Loaded uncertain-site widths are about 93–94% narrower, **without reducing the uncertain-site count**. Linux measured envelope costs were 7.50–10.10 ms and full basis preparation 0.22–0.25 s in these individual runs. The stronger inspection costs more than the prior absolute envelope; it is not a runtime speedup. Density-derived sheet masses differ (glass 0.0225 kg, oak 0.0063 kg, iron 0.07083 kg, ice 0.008253 kg), as do stiffness/frequencies. Oak retains its existing declared law: this does not establish grain, anisotropy or a new wood constitutive model.

Preparing/inspecting preserves native body/history state exactly; the subsequent detailed step is exactly equal to an uninspected control. The affine reference's energy residual is recorded separately from native full-world work/P/L diagnostics. A read-only observation supplies no new momentum/energy transfer and does not qualify a reduced/detailed handoff. [Raw receipts and verification scope](evidence/correlated-contact-bounds/verification.json) retain per-material residuals and timings.

## Verification scope

Windows 11, MSVC Release, separate headless build `build/contact-observations`. Seven scoped CTests pass: native coupled contact, CPU local Jacobian, CPU modes, new contact observation, CPU world, high-drop control and coupled view. Actual HTTP CPU sessions and native field gateway checks also pass. Source registration is **354/354**; the changed native implementation is compiled and the new Python regression is a CMake test.

The new observation suite checks 6,912 independent native derivatives, canonical translation/torque invariance, reversed sample ownership, fixed noncubic targets, box/plane feature changes, invalid-output sentinels, exact/near-frequency cases and continuous paths with small and large finite Cayley turns. Independent Linux Release observation and four-material modes suites also pass. No cross-platform bitwise or cross-GPU claim follows. This is not a full repository regression run.

An initial Windows CPU-world run correctly refused because the source changed during that run. The final five-suite rerun against frozen physical sources passed (83.06 s total); the two other scoped suites had passed against the same native implementation. No gate was weakened.

Local browser verification shows the new measured output beside the actual sheet at unchanged time zero. Portrait 390×844 and landscape 844×390 retain run/reset controls inside the visible 3D panel. Screenshots are ignored local evidence in `build/contact-observations/`. Hosted verification is recorded after publication; earlier controls/fields revision `1e3fa250` was already confirmed live on Render with ten actual native HTTP checks.

## Remaining gates

1. Resolve unilateral contact events and use valid one-sided branches; the current central native tangent can average open/closed contact.
2. Bound nonlinear error against native accepted trajectories and construct consistent endpoint history without hiding damage/plastic changes.
3. Audit complete fixed reactions, work, momentum and angular momentum for an actual admitted reduced/detailed transfer.
4. Demonstrate and qualify strong glass/oak/iron/ice sheet impacts and detailed ball/fragment evolution; measure complete hosted HTTP/3D delivery before declaring realtime.
5. Complete the other representation transfers and coupled 3D flow/phase/general-joint/thermal/reaction behavior in the design.
