# Rigid component transfer and initial free flight

October 8, 2026. Implemented experimental representation transfer; near realtime and material accuracy remain **OPEN**. Source parent `d5a988f3c3bf4e46e216eab61414310166d6f829`; publication revision is recorded in the follow-up below. The material-law baseline remains `bbb00f2ccada0179dd48d53eef9115089f6dcd9f`.

## What you can test

In the 3D lab choose **Motion → Rigid free flight · experimental**, then **Drop ball**. The original 32 occupied ball cells remain visible while one native compound carries their free flight. The readout changes from **Rigid · 32 cells / 1 body** to **Detailed · 32 native cells** before impact. Native constraints then produce the visible material response. Before/Live compare the actual starting and accepted states; the Physics & record drawer includes signed measured transfer residuals. Reference all-cell motion remains the default.

This is the initial unloaded-ball stage, **not** recovered post-fracture performance. Glass is slower in the experiment and fracture differs. Its failed speed/accuracy qualification is explicitly retained as a blocked gate, not promoted to reference behavior. No tolerance was loosened.

## Implementation and transfer boundary

[`RigidComponent`](../src/rigid/RigidComponent.hpp) measures each source body's actual native mass, world inertia, pose and velocities. It builds the aggregate center, parallel-axis inertia, linear momentum and intrinsic angular momentum. Aggregate spin comes from that measured tensor; the difference between source and rigid kinetic energy is reported. Appreciable nonrigid kinetic energy or caller-supplied stored elastic energy refuses collapse. Default nonrigid budget is 1e-9 J; transfer budgets are 1e-6 kg, 1e-5 N·s, 1e-5 N·m·s and 1e-5 J. These are representation roundoff budgets, not physical fracture tolerances.

The proxy is the occupied-box **union**, with each cell's material and rotation. It does not replace a gap by a convex hull. Declared dimensions and material-derived mass must match the native source within float roundoff. This is a trusted host adapter for declared boxes, not admission of arbitrary shapes or a new constitutive law. The host remains responsible for measuring elastic energy and deciding when material continuation can be suspended; the transfer primitive does not independently prove a component is unloaded.

[`JoltWorld`](../src/rigid/JoltWorld.hpp) now parks a closed dynamic component with face constraints, keeping original bodies and native local/rest state alive while removing constraints from the solver. External joints, pins, distance springs, static bodies, duplicates and partial restoration refuse before mutation. Restoring all endpoints writes the supplied finite poses **and velocities**, then reattaches the same constraints and invalidates stale warm-start impulses. Parked source IDs cannot be reused for newly created boxes, balls, compounds or fragments. Configuration changes still refuse inside reversible trials. Destruction releases retained constraints before their bodies.

[`VoxelImpactWorld`](../src/platform/VoxelImpactWorld.cpp) opts into the initial ball transfer through `hybrid_free_flight: true`. A conservative enclosing swept bound schedules early restoration with a 20 mm margin. This bound only activates detailed work; it never supplies a contact response or relaxes the original detailed motion/energy gates. If a native candidate unexpectedly contacts the proxy, that entire trial is rolled back, cells are restored at the same physical time, and the interval runs again through the detailed path. Actuator commands also restore detailed motion before forces are applied. Native work accounting uses the actual owner mass/inertia rather than counting the parked cells again. Rendered cell poses and velocities are derived from the accepted owner transform; no shatter animation or launch velocity is added.

The current automatic adapter collapses only the initial unloaded ball and leaves it detailed after the first activation. It does not yet re-coarsen fractured components, retain evolving elastic modes during reduced continuation, or implement local contact islands. General transfer tests cover repeated collapse/elapsed-motion/restore cycles, but those are not proof of automatic second-impact reactivation or refracture in a coarsened game world.

## Matched material experiments

Iron ball, material-derived 1 kg, 10 m drop; 0.4 m square, 4 mm sheet, 8×8 cells, 32 cm support gap; nominal dt 1/960 s, two physical seconds. Glass/oak/iron/ice density is 2500/700/7870/917 kg/m³ and Young's modulus 70/12/211/9 GPa. Total authored dynamic mass is 2.600/1.448/6.0368/1.58688 kg. Oak and reference iron remain elastic comparisons; no grain, ductile tearing or calibrated material realism is implied.

| Sheet | Experimental wall s | Accepted substeps | Pieces / broken faces | Signed unclosed energy J |
|---|---:|---:|---:|---:|
| Glass | 52.581 | 72,788 | 19 / 52 | -89.990181 |
| Oak | 5.679 | 5,928 | 1 / 0 | -44.347461 |
| Iron | 4.748 | 4,846 | 1 / 0 | -84.183899 |
| Ice | 22.742 | 46,060 | 64 / 112 | -103.201358 |

All coast for 1.425 physical seconds, then restore before contact. All 107 original cell IDs/masses remain; the active native owner count changes 107 → 76 → 107. These are complete runs, not truncated speed estimates. Glass reference has 12 pieces/40 faces and about 35–37 wall seconds; ice reference has 62/110. The change in fracture and losses precludes an accuracy or universal speed claim. Different compound/cell float pose evolution and integration schedules must be compared under timestep/spatial refinement; a small transfer residual alone does not establish matching trajectories.

Default collapse energy change is zero and restoration change -1.4211e-14 J; mass and linear momentum changes are zero, angular norm about 1.04e-17 N·m·s. Mixed-mass/rotated native round trips produce maximum absolute mass residual 1.046e-7 kg, energy 6.28e-8 J, linear norm 1.171e-7 N·s and angular norm 3.498e-7 N·m·s. These numbers admit those transfer fixtures only.

Full pipeline residual norms N·s / N·m·s: glass 0.002896 / 0.000683; oak 0.00005146 / 0.000003327; iron 0.00013269 / 0.000009225; ice 0.001853 / 0.000053161. Large signed energy deficits remain numerical/unexplained accounts, **not heat**. Full conservation, calibrated fracture/deformation and refinement are not admitted.

## Verification and environment

Windows x64, Intel Core Ultra 9 285K, MSVC Release, Windows SDK 10.0.26100, precise CPU floating point. Lab/CUDA/Rust OFF; native inline execution, separate CMake tree `build/voxel-contact-audit`, output `build/voxel-hybrid/Release`.

- Eight glass/oak/iron/ice mixed-mass and rotated native transfers, native/log-gradient face frames and retained plastic rest. Nonzero-rest cases are representation-only round trips with no accepted elapsed rigid continuation.
- Two elapsed free-flight handoffs preserve velocities and occupied air gaps; duplicate IDs, incomplete components, appreciable relative velocity and trial mutation refuse.
- Four complete experimental 10 m drops and four 10 cm/0.3 s lifecycle tests retain original cell mass, restore detailed native owners and observe real contacts; high glass/ice drops actually fracture.
- Four complete **default-mode** two-second comparisons against the prior published binary retain every physical/work field at each 16 host ticks. This parity applies to reference mode, not the experimental trajectory.
- Scoped compiled/native/gateway/pipeline/playback tests and source-registration guard; no full repository/long capacity, phone, cross-GPU or macOS claim.

The initial complete-drop and default-parity binary SHA-256 is `be91c3e66b8d15be340720031b54b0ec6e693d92fe8976ef1d1555ab1656bb14`. Subsequent changes only add native source-dimension/mass, parked-ID, pending-force and constitutive-edit preflight validation and expanded transfer tests; final binary SHA-256 is `83da8b8838c5ec80197b0bb9594ba8cfaf8892befb9baa080931c4d12fd2c272`. Final **16/16 scoped CTests pass in 27.42 s**, source registration is **342/342**, and the normal browser Drop/Before/Live flow passes. A centered-force command during coast restores detail before force application; its native phase impulse residual is below 1e-5 N·s. The final pending-force/edit/source-validation component and native lifecycle targets pass **2/2 in 8.72 s** after those preflight additions. The automatic adapter still assumes its initial ball is unloaded; host-level loaded-body and rotating-mode admission remain future work. Exact private result states remain in ignored `build/voxel-hybrid/material-full.json`.

```text
python scripts/check-source-registration.py
cmake --build build/voxel-contact-audit --config Release --target banjo_voxel_world_run banjo_rigid_component_tests --parallel 4
python tests/voxel_hybrid_test.py build/voxel-hybrid/Release/banjo_voxel_world_run.exe --full --output build/voxel-hybrid/material-full.json
python tests/voxel_execution_test.py build/voxel-hybrid/Release/banjo_voxel_world_run.exe build/voxel-observation/Release/banjo_voxel_world_run.exe --strict-inline-baseline --alternate-request-order
```

## Next required work

1. Qualify post-fracture continuation: retain geometry, damage/plastic history and any remaining elastic modes; never silently freeze appreciable deformation or discard kinetic energy. Exclude unrelated rigid flight from the detailed material timestep without missing contact.
2. Re-enter detailed work for **every later load/contact**, including fragment-versus-fragment impacts, before any proxy response. Show two successive impacts in the same 3D world with measured transfer/source accounts.
3. Resolve coupled contact/interface energy losses and finite geometry; demonstrate timestep and spatial convergence across glass, oak, iron and ice. Retain all existing energy refusal gates.
4. Complete local active solves and adaptive occupied cells, then measure full calculation/delivery/rendering at ≥1 physical second per wall second with responsive controls.
5. Add and qualify the remaining material/thermal/fluid/burning/power laws with visible free-form 3D demonstrations and unit-bearing bounded authoring. The full active goal remains unfinished.
