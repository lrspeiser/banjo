# Explicit CPU physics lab for Render

October 9, 2026. Implementation and scoped verification checkpoint; strong
fracture and the complete eight-family platform remain open.

## What the user can test

The public destination is https://banjo-f1sv.onrender.com/coupled. Render's
`banjo` service follows `lrspeiser/banjo` main. Its previous deployment already
followed main, but Docker started the old playground server. The new default
starts the physics lab and exposes its real CPU reference, explicitly labeled.
Existing login/host settings are retained. Actual deployment must be checked
after the publishing commit becomes live; a source push alone is not proof.

Choose a ball material/mass and a 10 m height, then **Drop & rebound**. Before,
contact and after show accepted states. Save/open retains exact current state
and material history on the same implementation. Inspect elements opens the
occupied-geometry transfer reference; it does not calculate internal fracture.
Connected-sheet controls remain experimental. Reliable cracks/dents/holes are
not delivered by this checkpoint.

## One implementation, explicit backends

`coupled_world.py` owns the canonical arrays, registry, atomic admission,
reaction/work/P/L accounts, rollback and saved continuation for both backends.
`coupled_solver.py` owns the existing bounded Newton controller. The new
`banjo_coupled_cpu` CMake shared target compiles `CoupledCpuApi.cpp`, calling
the same `CoupledGpuKernel.hpp` material and contact trial as CUDA. NumPy
provides the CPU array/linear algebra adapter. Bounds are unchanged: 32 bodies,
128 interfaces, 384 private candidates. Invalid declarations refuse before
native response writes; no arbitrary code is accepted.

`coupled_representations.py` owns the existing isolated-sphere policy.
`CoupledFlightKernel.hpp` contains the unchanged midpoint gravity/Cayley flight
and swept separation equations, compiled by both CPU and CUDA wrappers. The
material island keeps solving. No sleeping, damping, tolerance relaxation,
fracture animation, impulse substitution or cross-time response reuse was
introduced. Existing GPU low-energy baseline states for glass/oak/iron/ice
remain exactly equal across three accepted host ticks per material.

CPU source hashes normalize text line endings across checkout platforms. CPU
scene identity additionally includes native library bytes and NumPy version.
Cross-backend/cross-platform saved continuation is refused. Docker records an
image receipt separately from physical qualification. The Render API key stays
in the ignored local environment file; it is not shipped or committed.

## Measured controls

The same 0.1 kg ball drops 10 m onto a fixed iron plane. Four catalog materials,
240/960 Hz host steps and 0.25/0.0625 rad contact refinement produce 16 controls.
An independent continuous gravity/linear-compliance oracle bounds position and
velocity errors; the existing tolerances remain unchanged. All accepted
substeps retain support reactions and full P/L/energy accounts.

| Environment | Two physical seconds, 240 Hz controls | 960 Hz controls |
|---|---:|---:|
| Windows, MSVC 19.44, Python 3.13, NumPy 2.2.6 | about 0.15-0.18 wall s | about 0.55-0.60 s |
| WSL Ubuntu 24.04, GCC 13.3, Python 3.12, NumPy 1.26.4 | about 0.18-0.39 wall s | about 0.70-1.21 s |

These are measured local controls, not Render timings or full-world realtime
qualification. Contact-phase refinement reduces errors by more than twofold
at each host timestep; fine-phase position error stays below 0.4 micrometres
and speed error below 0.01 m/s. Maximum global energy residual over these
controls is 3.96e-9 J. The 10 m iron control reaches contact at approximately
1.428 physical s and rebounds upward at 8.394 m/s at two seconds.

Four matched 1 mm, 10 g, nine-cell sheet controls also pass on Windows and
Linux with density/stiffness-derived mass/inertia, support contact, unchanged
work/P/L gates, saved continuation and exact resumed CPU state. These controls
do not demonstrate strong fracture. CPU/CUDA batch trials for eight candidates
per material and two contact schedules match exactly in the measured Windows
comparison; cross-GPU determinism is not claimed.

Scoped tests include native contact, CPU coupled/high-drop/gateway/parity and
the retained GPU coupled/representation/high-drop/pipeline/registry, view,
gateway, pipeline and playback regressions. The source registration guard
reports 346/346 compiled sources. Evidence is under
[evidence/cpu-hosted-lab](evidence/cpu-hosted-lab/). This is not a full repository
CI pass: the earlier unrelated runtime lint/test-hub failures remain open.

Browser checks exercise a normal 10 m drop to contact and rebound. Hosted
gateway tests exercise password login, Host/origin rejection including HTTPS,
isolated scenes, CPU metadata, export/restore, exact journal and explicit refusal
of unsupported CUDA requests. No Docker daemon was available locally; Linux
targets and runtime were built/tested in WSL and the actual Render build still
needs its deployment receipt.

## Remaining gates

Complete strong glass/oak/iron/ice sheet impacts; connect detailed ball matter
to admitted contact/deformation and convergence/refinement tests; reduce awake
island cost without changing laws; general friction/CCD; complete sleeping,
articulated, reduced-solid, fluid, thermal and chemical bindings. CPU public
availability closes a deployment gap; it does not close these physics gates.
