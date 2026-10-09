# GPU finite-frame material force bridge

October 9, 2026. Implemented calculation and actual SDK delivery, **not** an
admitted coupled material/contact world. The near realtime platform goal remains
active. Source is published with this document on main; the measured working
tree was based on `d600ad9afff6f80316e7d1ee0e5a2cd006279e77` and is identified by
the source hash in [the evidence](evidence/gpu-material-frames/results.json).

## What is now implemented

- [FiniteFrameKernel.hpp](../src/physics/FiniteFrameKernel.hpp) is shared CPU/CUDA
  code for finite body/anchor frames, the existing shortest SO(3) logarithm and
  its differential, and conjugate body forces/torques.
- [MaterialWrench.cpp](../src/physics/MaterialWrench.cpp) supplies the checked CPU
  adapter. Nonfinite frames/loads, nonunit quaternions and the nonunique pi
  branch refuse. The existing checked `rotationStrain` now uses the shared
  calculation with its original validation.
- [gpu_material_frames.py](../scripts/gpu_material_frames.py) keeps geometry,
  coordinates, loads and wrenches in FP64 CUDA arrays. The existing shared
  cohesive/plastic histories provide loads. Coordinates can enter
  `ResidentLaws.update` directly from CUDA; no host coordinate roundtrip is
  required. Audit/output readbacks remain explicit.
- The bridge writes accumulated COM forces/torques, in N and N m, to actual
  PhysX DirectGPU `wrench` buffers. It validates CUDA residency, dtype, body
  ordering and complete row coverage before committing. It synchronizes each
  fill before SDK commit consumes the borrowed buffer. Application at COM
  avoids adding an already-accounted lever arm twice. It does not set body
  poses/velocities or animate USD after initialization.
- `/materials` shows actual force directions and both body reactions, with
  zero torque for centered normal loading. Arrow length is explicitly fixed
  for visibility; gap magnification remains labeled. This page is still a
  controlled loading inspector without a physical clock. `/gpu` remains the
  existing rigid-contact laboratory.

## Why equal and opposite forces alone are insufficient

For translation strain `q = R_a^T (p_b - p_a)`, the material frame rotates with
body A. Differentiating the energy produces both force and a frame torque.
The common current B anchor in the wrench calculation includes that derivative,
as in the existing native `LogFaceSpring` row. Applying each force only at its
own anchor omits `gap cross force`, creating angular momentum for shear.
Rotation loads use the existing SO(3) differential, rather than a small-angle
orientation approximation. Plastic rest/damage affect loads through the shared
laws; this geometry adapter adds no new constitutive law.

## Verification and measured boundary

Environment: Windows 11, MSVC 19.44 Release `/fp:precise`, RTX 5090, driver 610.88,
CuPy 13.5.1, NumPy 2.5.3, ovphysx 0.6.3, Warp 1.18.0. CUDA material kernels use
FP64 and `--fmad=false`; actual PhysX state and wrench inputs use FP32. Tests do
not establish another OS/GPU or physical-phone behavior.

- 1024 random finite offset/rotated CPU/CUDA frames: maximum coordinate error
  `4.44e-16`, wrench error `5.68e-14`; relative/absolute comparison tolerances
  are recorded in the regression source.
- Exact force-sum residual zero; world torque residual at most `5.12e-13 N m`.
  Common rigid translation/rotation retains strain and rotates wrenches.
- Independent central differences of anisotropic elastic energy test all 12
  body translation/rotation directions in 24 finite configurations, including
  nonzero retained rest. Maximum absolute gradient error `1.37e-5`; the test
  permits `2e-5 * max(1, abs(derivative))` for a `1e-6` perturbation. This is a
  finite-difference oracle tolerance, not a change to a world energy gate.
- A missing-frame-torque mutation leaves a `1333.95 N m` witness in the chosen
  test. Nonfinite/nonunit and pi-branch input refusal also pass.
- 10000 checked CPU rotations are bitwise equal to the pre-extraction source
  compiled from `d600ad9a` in a private separate baseline target.
- Seven scoped CTests pass: rotation strain, rebuilt native face springs,
  GPU material laws, GPU finite frames, gateway, pipeline and playback.
  The material-law suite retains all 61520 checked CPU/CUDA history comparisons.
  `check-source-registration.py`: 344/344, no exclusions. The new checked C++
  adapter is compiled into `banjo_core`; the oracle and GPU regression are real
  CMake targets/tests. The running CPU world binary is unchanged.

### Actual GPU force-delivery experiment

Each material uses the same two 1 kg spheres at x = +/-0.2 m, initially moving
2/0 m/s, zero gravity/friction/restitution. Density determines each sphere's
radius/inertia. A declared virtual 100 mm2 connector applies normal load at an
offset anchor (y = 0.01 m, z = 0.02 m); it is not a bonded sphere geometry model.
The common 50 nm declared opening evaluates as 55.9605 nm because the SDK
positions are FP32. Actual opening and all poses are retained, not overwritten
to hide that precision effect. The experiment uses one `1/1920 s` frozen-load
delivery step; the following step verifies the SDK consumed/cleared the input.

| Material | Force A (N) | Applied-load work residual (J) | P residual (N s) | L residual (N m s) |
| --- | ---: | ---: | ---: | ---: |
| Glass | 2833.00 | 2.09e-7 | 0 | 8.26e-13 |
| Oak | 90.656 | 2.42e-8 | 1.12e-8 | 3.37e-15 |
| Iron | 118.077 | -1.04e-7 | 5.59e-8 | 5.02e-14 |
| Ice | 7.4614 | 1.59e-7 | 7.92e-8 | 3.08e-17 |

The frozen-input work account independently uses midpoint linear/angular
velocities. Its tolerances reflect actual FP32 SDK input/state (`3e-5` scaled
work, `2e-6` P/L), not full-pipeline material conservation.

**Retained failure:** independently evaluating end-frame material energy/history
finds gains of glass `6.43075 J`, oak `0.0972311 J`, iron `1487.41046 J` (including
its separately recorded numerical return excess), ice `0.00779197 J`.
All exceed the unchanged scale gate, approximately `2.1e-5 J`. None is admitted
as coupled simulation. Accepted GPU material history stays unchanged during
this hypothetical candidate evaluation. This is a test-side refusal witness,
not a claim that the hidden SDK candidate can be rolled back or resumed.

This distinguishes a correct force API from a correct material integrator.
Freezing stiff forces for the large rigid timestep is withdrawn. No reduction
of stiffness, invented energy sink, force cap or animation conceals the failure.

### Performance scope

Warm median of nine finite-frame/wrench evaluations after three warmups:
1024 interfaces `0.473 ms`, 4096 `0.540 ms`, 65536 `0.507 ms` in the isolated run.
These include CUDA branch/finite checks and exclude initial uploads, compilation,
full readback, constitutive updates, body gather, collisions, integration and
rendering. They have no physical time denominator and do not qualify realtime.

## Required next work

1. Couple resident material forces/history to body motion implicitly, including
   shared contacts/reactions; pass these retained failures without changing the
   material law. Use finite 3D assemblies and actual contact, not independent
   pair coupons as a full-world substitute.
2. Race-safe body force/torque gather, island/local iterations, and explicit
   full M/P/L/E, external work and numerical-loss accounts. Each contact has one
   authoritative response. SDK candidate rollback or fail-stop must be honest.
3. Resolve FP32 pose precision versus tiny cohesive openings; perform timestep
   and geometry refinement on glass/oak/iron/ice. Density/stiffness differences
   must remain properties. Oak grain, continuum plasticity/tearing, thermal,
   fluid and power laws are still unsupported in this GPU stage.
4. Integrate admitted states into the existing 3D world, preserving histories,
   topology, ordinary controls and the rendering-independent physical clock.
   Measure complete-world speed only after every substep's accuracy gates pass.

Run the scoped bridge regression through CTest or directly:

```powershell
build/gpu-runtime/Scripts/python.exe tests/gpu_material_frames_test.py --oracle build/voxel-endpoint-final/Release/banjo_gpu_material_oracle.exe --report build/gpu-material-frames/results.json
python scripts/check-source-registration.py
```
