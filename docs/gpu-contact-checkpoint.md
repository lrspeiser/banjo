# Resident GPU contact yard — October 8, 2026

## What can be tested

The local lab now has **`/gpu`**, linked from the CPU material lab. Set up a
10 m ball drop, run two physical seconds, and see actual CUDA-calculated drop
and rebound. **Follow ball** makes the small, physically sized sphere easier
to inspect; it changes the camera only. Two-body impacts and a gravity-only
control are also available. The 27-block stack is explicitly a blocked
diagnostic: a rejected calculation stops and retains its last accepted scene.

This is an experimental **rigid-contact stage**, not a port of Banjo's bonded
material world. The original `/` remains the unchanged verified native CPU
reference. No GPU fracture, elastic sheet, permanent dent, grain, thermal or
fluid behavior is claimed. Spheres are solid rigid shapes, not bonded voxel
balls; blocks are free solid cubes, not connected sheet constituents.

## Implementation and boundary

- [Resident solver](../scripts/gpu_contact_world.py): Newton 1.6.1, Warp 1.18.0,
  NumPy 2.5.3, Windows x64, RTX 5090, CUDA device `cuda:0`, FP32. Pinned isolated
  [requirements](../scripts/gpu-requirements.txt); Warp reports toolkit 13.4 /
  driver API 13.3. This is a different contact law from the native Jolt model.
- The shape builder derives mass/inertia from geometry and numeric density:
  glass 2500, oak 700, iron 7870, ice 917 kg/mÂ³. A 1 kg ball consequently has a
  different radius for each density. Elastic stiffness and material damage are
  not implemented here; names do not select fracture outcomes.
- XPBD uses 16 iterations, explicit zero angular damping, disabled per-body
  contact-count weighting, and four restitution iterations. Uniform contact
  relaxation is declared: 0.1 in drops/stack, 1 in the analytical pair controls.
  Global restitution/friction are numeric authored parameters, not calibrated
  substance properties. Newton combines shape coefficients by arithmetic mean.
- GPU pose, velocity and collision buffers persist across steps. CUDA graphs
  execute collision, the contact solve and substep observations. No repeated
  CPU Jolt solve, prescribed post-impact velocity, shatter animation, pose
  clamping or arbitrary fragment launch is added. CuPy's existing shared-source
  bond probe is separate; the bonded laws have not been connected to this yard.
- The [JSON-lines worker](../scripts/gpu-contact-worker.py) admits bounded
  declarations only. A GPU request cannot silently fall back to CPU. The
  explicitly selected CPU path is used for matched library regression only.
- The [gateway](../scripts/voxel-lab.py) owns separate CPU/GPU session types.
  `/api/gpu` streams immutable accepted frames; `/api/world` remains CPU.
  Every GPU substep's transform, velocity and contact count is journaled,
  including batches between published frames. Initial declarations, versions,
  source hash, refusal witness and final accepted time are retained.
- The independent [3D renderer](../client/voxel-lab/gpu.js) uses actual sphere/
  cube geometry and solver poses. It interpolates two accepted states without
  extrapolation. Simulation runs with fixed physical dt; the gateway targets
  30 publications/s and uses 32-step resident GPU batches.

## Admission is not full conservation

Each substep checks finite pose/velocity values and intermediate/final collision
buffer counts on CUDA. Overflows refuse the batch rather than merely printing
a warning and dropping contacts. The materialized substep states then audit
`K_translation + K_rotation + gravitational potential` using actual FP32
states and double-precision reductions. Isotropic sphere/cube inertia is
required; unsupported geometry is not admitted.

Positive substep change above `1e-5 * max(1 J, |previous E|) + 1e-6 J` refuses
the entire batch. This is a new bounded rigid-stage gate with the existing
native gate's numerical form, not a relaxation of native acceptance. No energy
clamp is applied. Pose/velocity buffers are restored, previously accepted
time/trace retained, and the experiment stops until a fresh worker is created.
Resuming unqualified hidden solver history after refusal is prohibited.

Total mass, momentum, orbital/spin angular momentum and mechanical energy are
measured. **The support reaction and contact/numerical loss account is still
incomplete.** Newton's reported XPBD contact wrenches exclude its subsequent
restitution solve; they are labelled incomplete rather than presented as a
closed ground reaction ledger. Pair conservation without ground is useful but
does not prove the whole pipeline. Global losses are not labelled material heat.

## Measured results and tests

[Exact measured report](evidence/gpu-contact/results.json), including executable,
test, worker and physics source SHA256; repository base
`9e31656e05718e7d4a26877da74cdd4878e12cc5` plus the fingerprinted implementation.
The native CPU website executable remains SHA256
`eb3527a07fda2a0c181ff11683eb907a16045bf0fcae66e4db58f703e7df9ee4`, source
`e12eb688a470e3a092038442ef1950ce5b52a30b`.

Same 1 kg ball, 10 m drop, global restitution 0.5 / friction 0.3, stationary
plane, gravity 9.81 m/sÂ², two physical seconds, both dt = 1/960 and 1/1920 s:

| Ball | dt | Final center height | Mechanical change | Calculation/readback/audit wall time |
|---|---|---|---|---|
| glass | 1/960 s | 2.442513 m | -73.614572 J | 1.149 s |
| glass | 1/1920 s | 2.444784 m | -73.591870 J | 2.080 s |
| oak | 1/960 s | 2.466673 m | -73.614564 J | 1.199 s |
| oak | 1/1920 s | 2.468943 m | -73.591879 J | 2.037 s |
| iron | 1/960 s | 2.427993 m | -73.614572 J | 1.200 s |
| iron | 1/1920 s | 2.430263 m | -73.591875 J | 2.155 s |
| ice | 1/960 s | 2.460658 m | -73.614572 J | 1.079 s |
| ice | 1/1920 s | 2.462929 m | -73.591870 J | 2.088 s |

The independent ballistic rebound oracle bounds height error to 12 mm at
1/960 s and 6 mm at 1/1920 s; energy loss must be within 0.1 J of the prescribed
inelastic loss, 73.575 J. These allow discrete contact timing/FP32 integration
error for this isolated fixture, not material-realism certification. Halving dt
changes final heights by about 2.3 mm. No spatial convergence is claimed.

The equal 1 kg free-body pair starts at 2 m/s and 0, e = 0.5, friction = 0:
the analytic final velocities are 0.5 and 1.5 m/s, energy loss 0.75 J.
Glass/oak/iron/ice target cases retain momentum within 2e-5 N·s and satisfy
velocity/energy bounds 2e-4 m/s / 2e-4 J. Off-center friction creates actual
spin, with pair linear/angular residuals bounded by 5e-4 N·s / N·m·s. An
explicit same-library CPU pair and mixed CUDA graph batch schedule compare
positions/velocities; this does not claim cross-GPU determinism.

The HTTP stream completes two physical seconds in about two wall seconds,
including publication/logging. Cold graph capture takes roughly 150 ms and
batch p95 about 27 ms in this run. The refined drop takes roughly two wall
seconds even without publication. **Only the isolated coarse fixture is close
to realtime; the full world is not qualified.** Startup/JIT is reported
separately; these are single-workstation measurements, not a matched native
Jolt speedup or production concurrency guarantee.

Scoped verification: [GPU regression](../tests/gpu_contact_test.py) passes,
including density/mass, analytic drops/pairs, off-center torque, gravity control,
CPU/graph parity, collision-capacity refusal, retained-state rollback, HTTP
backend isolation and all 1920 journaled substeps. Existing gateway, pipeline
and playback regressions pass (three additional CTests). Source registration:
342/342, no exclusions. Normal browser controls are tested separately. No new
native physical laws or full repository regression are claimed by these checks.

## Failed candidates retained

The full 27-cube glass stack plus 1 kg iron ball from 10 m refuses at a positive
intermediate energy gain at both timesteps. Exact witnesses are in the report;
the failure tick/gain can vary with GPU contact ordering and batch scheduling.
The earlier 16-step HTTP assertion wrongly assumed the same failure tick as a
32-step graph; the regression now runs the bounded full experiment and checks
the actual last accepted state when refusal occurs. Tolerances were not raised.

An initial contact-relaxation 1 trial produced roughly **+31.9 kJ** over two
seconds and is withdrawn. Relaxation 0.1 improved the final total but did not
eliminate intermediate energy creation; endpoint energy alone missed the defect.
A VBD exploratory trial overflowed its 64-contact per-body buffer and failed
an energy check. That adapter was withdrawn entirely; the public worker does
not expose it. These failed calculations are not advertised as working physics.

## Run and next gates

```text
python -m venv build/gpu-runtime
build/gpu-runtime/Scripts/python.exe -m pip install -r scripts/gpu-requirements.txt
cmake -S . -B build/voxel-contact-audit -DBANJO_NEWTON_PYTHON=<absolute isolated Python path>
ctest --test-dir build/voxel-contact-audit -C Release -R ^banjo_gpu_contact_tests$ --output-on-failure
python scripts/check-source-registration.py
python scripts/voxel-lab.py --native build/voxel-endpoint-final/Release/banjo_voxel_world_run.exe --gpu-python build/gpu-runtime/Scripts/python.exe --port 18893
```

Next: resolve coupled multi-contact work/convergence and compare a PhysX GPU
fixture. Account all constraint/restitution reactions and separate numerical
losses. Port coupled bonded state/material histories into the resident pipeline;
qualify glass/oak/iron/ice fracture/plastic response, thin/high-speed geometry
and timestep/spatial refinement. Then adaptive cells, broader interactions,
thermal/fluid/power laws and load-tested remote GPU simulation. The CPU material
world remains available while those gates are open.
