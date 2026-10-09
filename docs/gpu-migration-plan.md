# GPU physics migration — October 8, 2026

## Decision and actual status

The owner now requires GPU calculation as the development direction. Keep the
CPU implementation as a reference and diagnostic fallback. This supersedes the
earlier optional-GPU roadmap policy; it does not imply that every client phone
needs CUDA. A GPU simulation host can eventually serve a browser renderer.

**Recommended candidate:** Warp kernels with Newton's GPU simulation facilities,
plus CuPy for arrays, reductions and execution of reusable CUDA kernels. Evaluate
PhysX GPU dynamics against the same contact fixture before committing the final
contact backend. These are architecture recommendations, not completed ports.
The subsequent [resident GPU contact checkpoint](gpu-contact-checkpoint.md) installs Newton 1.6.1 / Warp 1.18.0 and measures a separate rigid yard on the RTX 5090. The full block stack remains blocked.

**Implemented:** an opt-in CuPy probe compiles Banjo's existing axial bond
function directly from `LatticePhysics.hpp` and executes it on the RTX 5090.
Twelve analytical coupon cases pass across glass, oak, iron and ice. The CMake
test is opt-in and fails if the required GPU/toolchain is unavailable.

**Not implemented:** a GPU replacement for the current 3D world's Jolt/contact/
six-mode interface solve. The default material world remains the exact previous CPU
native binary; the separate `/gpu` rigid yard now consumes accepted CUDA states. This checkpoint changes neither its material laws nor its
performance. Full impact accuracy and near realtime are still open.

## What each library actually supplies

| Candidate | Useful capability | What Banjo must implement or validate |
|---|---|---|
| Jolt 5.6 (our pinned dependency) | CPU rigid bodies, contacts and constraints; GPU compute interfaces for DX12/Vulkan/Metal, used for strand/hair simulation | The existing rigid/contact/interface update is not moved to GPU by enabling compute. A custom compute-shader solver would still be a port. No automatic Jolt-to-CuPy translation exists in the examined interfaces. |
| CuPy | GPU arrays, sparse/math routines, reductions, CUDA streams and custom `RawKernel`/`RawModule`; CUDA array interface/DLPack sharing | It is a numerical runtime, not collision detection or a full physics engine. Sequential C++ callbacks and Jolt state must be redesigned into GPU data and kernels. |
| NVIDIA Warp + Newton | Warp compiles supported Python kernels for CPU/CUDA and provides geometry/FEM primitives. Newton extends the retired `warp.sim` system with GPU solvers and rigid/deformable/MPM examples | Implement Banjo's fracture, plastic history, material law selection, reactions and work accounting. Existing examples do not prove calibrated glass fracture or our six-mode contact law. A stock Newton run is a different solver until compared. |
| PhysX GPU | CUDA rigid-body/contact/constraint and broadphase acceleration; FEM soft bodies and PBD particles | Our modified Jolt interface/friction/history is not a drop-in API match. Inspect GPU extension points, precision, timestep behavior and capacity failure. Reject overflow rather than accepting discarded contacts. |
| Taichi | Python-embedded compiled kernels with CUDA/Vulkan/Metal backends and AOT export | Useful alternative for custom sparse kernels and future broader hardware support. Still requires collision, laws, state lifecycle and full validation; no direct Jolt/CuPy conversion. |

Primary references checked October 8:

- [Jolt 5.6 release: compute interfaces and GPU hair](https://github.com/jrouwe/JoltPhysics/releases/tag/v5.6.0)
- [Jolt architecture](https://github.com/jrouwe/JoltPhysics/blob/master/Docs/Architecture.md)
- [CuPy custom kernels](https://docs.cupy.dev/en/stable/user_guide/kernel.html)
- [CuPy interoperability](https://docs.cupy.dev/en/stable/user_guide/interoperability.html)
- [CuPy performance](https://docs.cupy.dev/en/stable/user_guide/performance.html)
- [Warp documentation](https://nvidia.github.io/warp/stable/)
- [Newton project and examples](https://github.com/newton-physics/newton)
- [PhysX GPU simulation](https://nvidia-omniverse.github.io/PhysX/physx/5.4.1/docs/GPURigidBodies.html)
- [Taichi compiled kernels](https://docs.taichi-lang.org/docs/hello_world)

Versions and interfaces must be pinned when the candidate backend is installed.
The latest web examples are not automatically compatible with every wheel.

## Reuse already in Banjo

[The prior CUDA lane](fast-gpu-checkpoint.md) shares host/device functions and
uses a persistent cooperative kernel and graph-colored constraint schedule.
Its historical 192-cell tile completed 1.895 physical seconds in 0.38 wall
seconds. That result is from a different experiment, contact representation,
fracture criterion, resolution and rigid handoff. It is not a measurement of
the current thin-sheet world. The older lane also missed its target at larger
glass resolutions and had unqualified material/whole-pipeline behavior.

Reuse its shared law code, coloring, GPU buffers and measurements where
applicable. Do not secretly substitute its sphere-per-node contacts, one-way
rigid handoff or axial XPBD law for the current six-mode native model. Every
backend and law revision must be identified in recordings and the website.

The current bottleneck is native stepping, not Three.js. The previous refined
glass browser trace measured 36.101 s in Jolt update out of 37.25 s of native
step time. Moving only damage evaluation or rendering to the GPU leaves most
of that cost. Excessive global substeps and serialized constraints must also
be addressed; more GPU throughput does not enlarge a stable timestep by itself.

## First actual CuPy result

Source: [probe](../scripts/cupy-physics-probe.py). Evidence:
[measured report](evidence/gpu-migration/cupy-probe.json).

Windows x64, Python 3.13, CuPy 13.5.1, CUDA runtime 12.9, driver API 13.3,
RTX 5090 (sm_120); nvcc 12.9 and MSVC 14.44 developer environment.
Repository base `f67b5e49c0a829d43c29e3b975b862eec42f4816`, with this new probe.
The report hashes the actual shared source. CuPy's kernel cache key includes
that hash so edits to the included header cannot reuse stale compiled physics.

Same 20 mm axial coupon at dt = 1/1920 s; density / Young's modulus:
glass 2500 kg/m³ / 70 GPa, oak 700 / 12, iron 7870 / 211, ice 917 / 9.
Compliance is explicitly L/(E*A). Each row is an independent two-node bond,
not a shared scene. All endpoints have density-derived mass; selected tests
include fixed endpoints, dead bonds, retained rest offsets, prior multipliers
and a degenerate zero-length early return. These synthetic rest offsets do not
claim a constitutive metal plasticity or oak grain law.

The independent oracle uses length-form XPBD; the compiled function uses its
existing cancellation-resistant displacement form. New probe bounds are
1e-12 m pose error, 1e-12 kg·m multiplier error, 1e-14 kg·m free-pair weighted
position residual, and 1e-10 J maximum first-projection elastic gain. They are
roundoff checks for these bounded coupons, not changes to native world gates.
This is a positional projection test: weighted COM and decreasing recoverable
energy are not a complete dynamics momentum/energy audit. There are no evolving
velocities, collisions, fragments, damping, thermal laws or world history here.

Measured warm timings are nine medians, with 100 independent evaluations per
resident GPU measurement. The end-to-end number includes upload, one evaluation,
download and synchronization. Compilation/startup is excluded. GPU clock/load
vary; these are a compatibility microbenchmark, not a matched native C++ speedup.

| Independent bonds | Resident GPU evaluation, material range | Upload + evaluate + download, material range |
|---|---|---|
| 128 | 0.009-0.014 ms | 0.133-0.193 ms |
| 4096 | 0.009-0.014 ms | 0.201-0.232 ms |
| 65536 | 0.018-0.023 ms | 1.673-1.721 ms |

The exact report records every per-material value and the NumPy oracle timing.
The tiny transferred batch is slower than that NumPy oracle. This confirms the
need to retain simulation state on the GPU rather than shuttle it per substep.
It does not predict the full native world's speed or prove fracture accuracy.

Commands (Windows, normal x64 VS developer environment):

```text
python scripts/cupy-physics-probe.py --report build/cupy-probe/results.json
cmake -S . -B build/voxel-contact-audit -DBANJO_TEST_CUPY=ON
ctest --test-dir build/voxel-contact-audit -C Release -R ^banjo_cupy_physics_probe$ --output-on-failure
python scripts/check-source-registration.py
```

Without CuPy/CUDA, leave `BANJO_TEST_CUPY=OFF`; an explicitly requested GPU test
must fail instead of silently running the CPU. CuPy owns this probe compilation;
`BANJO_BUILD_CUDA` independently controls the existing native CUDA lane.
An initial wrapper compile failed on a const pointer; the corrected probe
passes. No failed kernel or simulated outcome has been promoted to the world.

## Required migration stages and visible acceptance

1. **GPU solver boundary.** Define backend-neutral material/state/command/frame
   contracts: stable IDs, units, topology revision, accepted physical time,
   law/version/precision, native failures and full work accounts. Keep the
   independent renderer and bounded published-frame pipeline. User can select
   CPU reference versus explicitly experimental GPU without changing the scene.
2. **One GPU contact yard.** Install/pin Warp/Newton and evaluate the equivalent
   PhysX GPU fixture. Run ball/plane and two-body impacts, off-center torque,
   sliding/spin, fixed support reactions, high-speed thin geometry and capacity
   rejection. Show actual trajectories with before/during/after states. Compare
   common-phase impulse/work, normal restitution and Coulomb bounds. Select the
   contact owner from measured complete results, not library marketing.
3. **Resident coupled material solve.** Pack positions, orientations, momenta,
   inertia, connectivity, rest/plastic/damage/thermal history and material tables
   into GPU buffers. Batch disjoint constraints using tested coloring or a
   documented parallel solver. Contacts and interfaces that exchange forces
   belong to one coupled GPU solve. Keep an island's trial, accept/refuse,
   reactions and rollback coherent. Do not run two responses for one contact or
   copy back to CPU Jolt every microstep.
4. **Real damage and persistent pieces.** Port supported laws and topology
   updates, including connected components and later-impact reactivation. Run
   matched glass/oak/iron/ice sheets at both timesteps and refined resolution.
   User sees computed glass/ice separation and supported elastic/plastic metal
   response, not an outcome chosen by material name. Retain CPU comparisons and
   explicit unsupported-law labels. Require full conservation and convergence;
   current CPU accuracy failures are counterexamples, not gold truths to copy.
5. **Realtime admission and continued gameplay.** Measure complete isolated
   scenes plus many interacting objects: GPU compute, transfers, snapshot work,
   commands, p50/p95 latency, memory and total physical/wall rate. Target at
   least 1x sustained calculation and responsive Pause/Reset; publish measured
   bounds, GPU identity and backend hashes. Async snapshots at presentation
   cadence transfer only accepted state. Later add qualified heat/fluid/power
   kernels with the same coupled work and rendering contracts.

LLMs edit bounded, unit-bearing declarations and select reviewed law primitives.
They do not upload arbitrary GPU source as world content. The trusted CuPy probe
compiles repository code only. Future server acceleration, multiplayer and
cross-GPU reproducibility remain planned, not delivered by this test.

## Checkpoint verification

The registered GPU probe passes (12 cases, CTest 2.52 s). Three unchanged
gateway/pipeline/playback CTests pass in 10.11 s. Source registration is
342/342 with zero exclusions; Python compilation, changed-file whitespace,
JSON evidence and local document links pass. This is four scoped test entries,
not a rerun of the full repository or a new whole-impact physics qualification.

The website records the GPU primitive separately from the visible CPU world.
Its native executable remains SHA256
`eb3527a07fda2a0c181ff11683eb907a16045bf0fcae66e4db58f703e7df9ee4`,
physics source `e12eb688a470e3a092038442ef1950ce5b52a30b`.
