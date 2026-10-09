# Resident GPU observations, October 9

Implemented optimization of state reads in the experimental PhysX rigid
comparator. **Near realtime, bonded fracture and metal dents remain open.**
No material law, contact response, iteration count, timestep or safety bound
changes. The CPU material world and Newton comparator are retained.

## Kernel measurement changed the next action

[Actual Nsight evidence](evidence/physx-gpu/kernel-profile.json) profiles
0.1 physical seconds of the initial glass stack with zero restitution/friction,
1/1920 s, a 1 kg iron ball initially 10 m above it. This short range ends before
ball impact; stack/ground contacts already exist. CUDA profiler start/stop
excludes SDK/kernel warmup. Installed Nsight 2025.1 does not support this driver
and omits solver kernels, so that trace is withdrawn. The portable official
2026.3.2 profiler supports CUDA 13.3; no system driver/settings changes are
required. NVIDIA documents that support in its [release notes](https://developer.nvidia.com/nsight-systems/get-started).

The compatible trace contains all 192 expected integration and contact-summary
markers, 3,072 TGS island solve markers and 768 column copies. It shows actual
GPU dynamics, including narrowphase and constraint kernels. Summed device
kernel time is 0.172626 s; the non-overlapping union is 0.172547 s. Driver
`cuLaunchKernel` has 41,664 calls: 217 per substep. TGS island/block/static
solves account for about 66% of device kernel duration. CUDA API durations
overlap device work and cannot be added to kernel time as separate costs.
Profiling changes wall time, so these numbers are not a speed qualification.

The runtime still warns that not all CUDA events may be collected. Exact key
marker counts support this diagnosis; **exhaustive trace coverage is not
qualified**. Missing kernels in the obsolete trace were not evidence of CPU
fallback.

## What changes in the running world

PhysX now reuses two resident GPU buffers and stable pose/velocity bindings.
One GPU kernel packs the 7 pose plus 6 velocity coordinates into each original
substep trace. This replaces repeated state-column sessions, path dictionaries
and four copy launches. Actual contact-force/torque reads, all intermediate
states, admission gates and accepted-pose rendering remain intact. The slower
column read path remains an explicit reference in the Python profiler.
[The optimized short trace](evidence/physx-gpu/resident-kernel-profile.json)
retains all 192 expected integration/contact-summary markers and now has
192 pose/velocity packing kernels instead of 768 column-copy kernels. Its
remaining event warning is retained; exhaustive trace coverage remains
unqualified.

Bindings validate actual shape, dtype, resolved body order and native CUDA
device. The session never mutates/reparses topology. Bindings are destroyed
before stage/SDK teardown. Initialization refuses unsupported layouts or
devices; there is no CPU fallback or silently missing observation.

**SDK boundary:** ovphysx 0.6.3's tensor-binding API is deprecated. This is a
bounded optimization for the pinned runtime, not a claim of future API support.
Any SDK upgrade must replace or requalify it, including device/order/lifetime
and all-substep parity. Version checks remain strict. It is unsuitable for
future topology editing unless bindings are destroyed/recreated safely.

## Verification and measurements

The actual CUDA regression compares every accepted transform/velocity in all
3,840 refined stack substeps against the independent column read path for
each of glass, oak, iron and ice. Shadow reads are test-only and inflate test
timings; ordinary performance measurements run without them. Analytical pair,
normal-impulse, energy-gate, exact-refusal, capacity, protocol and lifecycle
checks remain required. Density changes mass/inertia; elasticity, wood grain,
fracture, plasticity and heat remain unsupported by this rigid comparator.

```powershell
build/gpu-runtime/Scripts/python.exe scripts/profile-gpu-contact.py --report build/resident-observations.json
build/gpu-runtime/Scripts/python.exe scripts/profile-gpu-contact.py --observation-mode columns --report build/column-reference.json
ctest --test-dir build/voxel-contact-audit -C Release --output-on-failure -R banjo_physx_contact_tests
python scripts/check-source-registration.py
```

For kernel tracing, use a compatible `nsys` and `--cuda-capture --material glass`
with `--capture-range=cudaProfilerApi`. This requires a single material per
trace; it changes no physics settings or gate. Exact commands and warnings
are retained in the evidence.

[Ordinary four-material benchmark](evidence/physx-gpu/resident-benchmark.json)
completes two physical seconds for each material, with identical final body
states and mechanical energies to the prior column checkpoint:

| Material | Prior columns wall s | Resident reads wall s |
| --- | ---: | ---: |
| Glass | 19.305 | 14.330 |
| Oak | 19.272 | 14.352 |
| Iron | 19.141 | 14.299 |
| Ice | 19.123 | 14.263 |

These single sequential Windows RTX 5090 runs show roughly 25-26% lower run
wall time, not a controlled statistical confidence interval or realtime
qualification. They exclude startup and browser IPC/publication. All use
27 original 12 cm cubes, the same refined step/iterations, zero bounce/friction
and unchanged mass/energy/normal-impulse admission bounds.

[Actual CUDA regression](evidence/physx-gpu/resident-regression.json) includes
all 15360 shadow-read comparisons and the retained analytical pairs/bounce
outcome/Newton refusal/SDK-capacity/protocol tests. All nine final cell states
and mechanical energies exactly match the previous report. Five scoped
CTests pass: PhysX 128.06 s (including shadow reads), Newton 25.93 s, gateway
3.36 s, pipeline 6.99 s and playback 0.04 s. The source guard passes 342/342
with no exclusions. These are scoped tests, not the whole repository or
cross-GPU/material-realism qualification.

## Next physical work

SDK step launches and TGS solving still dominate after cheaper observations.
The next resident material solver must batch shared CPU constitutive laws,
bond/plastic histories and coupled contact work, retain equivalent per-substep
audits on the GPU and publish accepted poses independently. Benchmark complete
glass/oak/iron/ice impacts and refinement, not just cheap independent coupons.
Do not replace current physics with an unaccounted spring/shatter preset or
claim the old axial lattice's speed qualifies the current six-mode world.
