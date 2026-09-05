# Bounded physical tests for creator recipes

Source `cf73e5e5c6826cef7f8b63a68c8ef74ffc635b60`, local `codex/physics-foundation`, September 5, 2026. Not pushed or merged. The full platform goal remains active.

The creator API now exposes `test_recipe`; the starter designer offers **TEST ON 10 DEGREE RAMP**. It tests a virtual copy in a separate Jolt world without collecting or spending material, granting XP, creating a live object or advancing the API caller's clock. The starter runs one background test at a time while its normal world continues. Resource-short saved designs can be tested before they can be built. Results are stored as JSON in the starter workspace.

## Explicit test contract

The version-1 `concrete-incline-v1` fixture retains geometry, material and orientation, but explicitly substitutes tangent -2 m, lane 0, clearance 0.002 m and zero initial linear/angular velocity. Gravity is [0,-9.81,0] m/s² and the finite concrete support has half-extents 8 by 3 m. The report contains both the original and fixture recipes; fixture initialization is not physical manufacture or relocation of a live object.

The strict test specification contains `test_version`, `fixture`, `ticks`, `slope_degrees`, `minimum_travel_m`, `maximum_final_slip_m_s`, and `require_rolling`. Bounds are 24–1200 ticks at 1/240 s, slope 0–20 degrees, travel threshold 0–10 m and slip threshold 0–5 m/s. The UI chooses 480 ticks, 10 degrees, minimum travel 0.3 m and maximum final slip 0.02 m/s. It additionally requires measured rolling for spheres; boxes use travel/contact/slip criteria. A box request with a sphere-rolling predicate returns `unsupported` rather than silently substituting a sphere.

Passing requires each declared endpoint predicate: travel, final near-top support, final slip and (if requested) the existing sphere rolling classification. Rolling classification retains its own 0.02 m/s tolerance even if a caller asks for a looser slip limit. A valid object can fail its function. Reports include material/compiler/runtime signature, mass, inertia, sampled position/orientation/velocities, support samples, travel, slip and mechanical energy every 24 ticks plus the final tick, at most 51 samples. Mechanical energy change is explicitly not a closed work/dissipation ledger.

## Evidence

Windows Release build and all 16 CTest suites pass (12.28 s). Tests cover glass/oak/iron mass, rolling, endpoint failure, matched-volume box travel, unsupported box rolling, trace bounds, malformed specifications and unchanged live world. Nine reproducible JSON CLI cases give three sphere passes, three flat-box travel failures and three unsupported box-rolling results; full live inspection before and after is identical.

| Substance | 8 cm sphere travel, m | Final slip, m/s | Equal-volume box travel, m |
|---|---:|---:|---:|
| Glass | 2.239693 | 0.007284 | 0.000297 |
| Oak | 2.118447 | 0.006899 | 0.000297 |
| Iron | 2.226095 | 0.007157 | 0.000297 |

Conditions are the UI fixture above; boxes are oriented with a face parallel to the incline. Their volume and mass match the sphere of the same substance. Material contact profiles differ, so the small travel differences are not evidence that density alone changes gravitational acceleration. These comparisons show supported rigid shape/contact behavior, not calibrated material realism.

Native verification clicked the new test control for the previously saved real LLM oak-ball design. It returned `passed`, travel 2.118 m and final slip 0.0069 m/s, saved a report, and kept zero inventory/XP and 100 stamina. No new LLM call was required. This is native test-control evidence; the full walk/gather/cut/custom-build progression remains pending.

## Limits and next steps

This is one bounded fixture and endpoint test family. It does not certify general intended function, continuous rolling, assemblies, cutting, deformation, fracture, damage, physical energy or arbitrary actions. Box diagnostics sample vertices near the top plane and do not measure edge/side contact manifolds. Existing detailed-solver energy defects remain. Test work is bounded by steps/output, not a hard wall-clock deadline; the background UI job has no cancel control and shutdown may wait for it. JSON batches can accumulate bounded test work. Reports currently remain separate from the saved proposal and are not automatically fed back to the LLM. Add versioned test-result references, explicit feedback/revision, job cancellation and further fixtures under the full API/physics plan.

Reproduce via `banjo_creator_cli --commands FILE.json`, using `{"type":"test_recipe","recipe":RECIPE,"test":SPECIFICATION}`. Successful execution wraps a test result in `ok:true` even when its status is `failed` or `unsupported`; clients must inspect both layers. The exported commands and reports provide complete examples. Build/test environment remains Windows 11 Pro 26200, MSVC 19.44 x64 Release, CMake 4.1.2, Core Ultra 9 285K, RTX 5090/NVIDIA 580.88, OpenGL 3.3, Jolt 5.6 and raylib 6.
