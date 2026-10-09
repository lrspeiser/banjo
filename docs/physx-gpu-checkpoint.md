# PhysX GPU contact comparison — October 8, 2026

## What the user can test

Open **`http://127.0.0.1:18893/gpu`**. The GPU solver menu now offers Newton
XPBD and PhysX TGS. **Set up stack · no bounce / friction** creates 27 free
120 mm cubes and a density-derived 1 kg iron sphere 10 m above them. **Inspect
blocks** frames the actual cubes; **Run 2 s** calculates their response and
streams accepted solver poses. They remain rigid: this is not fracture or a
connected sheet. The original CPU material lab remains available at `/`.

The refined control (dt = 1/1920 s, restitution/friction = 0) completes for
glass, oak, iron and ice. The default Newton stack still refuses energy
creation even without bounce/friction, before ball impact. Keep that failed
case: changing the engine must be supported by comparative evidence.

This does **not** finish the GPU migration or qualify material realism or
near realtime. Detailed SDK state/contact reads and audits still take about
19 wall seconds for two physical seconds in isolated refined controls.

## Implemented, with boundaries

- [PhysX comparator](../scripts/physx_contact_world.py), NVIDIA `ovphysx` 0.6.3,
  `ovstage` 0.2.0.377349, Warp 1.18.0, NumPy 2.5.3; pinned
  [runtime](../scripts/gpu-requirements.txt), Windows x64 / RTX 5090. The
  [official standalone SDK](https://github.com/NVIDIA-Omniverse/PhysX/blob/main/ovphysx/docs/developer_guide.md)
  supplies GPU rigid contacts; it does not translate Jolt code into CuPy.
- GPU dynamics, GPU broadphase and DirectGPU reads are explicitly requested.
  Every actual pose/velocity tensor must be on the requested CUDA device;
  CPU-only policy or host state reads refuse setup. Only uniform spheres and
  cubes with isotropic inertia are admitted. Density determines radius/mass/
  inertia; actual solver mass/inertia are queried and checked, not assumed
  from authoring. No arbitrary USD paths or downloaded scenes enter the API.
- TGS uses 16 position and four velocity iterations, zero linear/angular
  damping, sleep/stabilization thresholds zero, zero rest offset and 2 mm
  contact offset. Global restitution/friction are numeric declarations with
  average combination; they are not calibrated substance properties. No CCD,
  elastic, bonded fracture, plastic history, grain or thermal law is added.
- The SDK initializes by integrating a tiny warmup. Only before the declared
  experiment starts, initial pose/velocity are restored through its supported
  GPU write API and checked. Subsequent motion is never prescribed. Warmup
  contact history is not a qualified full solver restart/handoff.
- One worker process owns one SDK/stage; no concurrent calls to that SDK.
  Every accepted substep records actual GPU poses/velocities, contact count
  and normal-force impulse/torque accounts. Read views remain alive until
  CUDA copies complete. Renderer and simulation remain independent.
- [Worker](../scripts/gpu-contact-worker.py) reserves the JSON pipe and directs
  native diagnostics to stderr (including Windows standard-handle writes).
  SDK capacity/truncation/errors stop admission. Contact reads refuse counts
  reaching the bounded capacity rather than accepting silently truncated data.
- The existing mechanical-energy gate is unchanged. On failure the displayed
  scene/time stay exactly at the last accepted state, and the solver stops.
  **Hidden PhysX state is not restored or resumed**; the record states this.
  SDK/read exceptions also stop the experiment.

## Measured behavior versus physical qualification

[Scoped comparative report](evidence/physx-gpu/results.json) records actual
versions/device, source/test/worker hashes, repository base, declarations,
final states, timings and failures. The native CPU executable remains SHA256
`eb3527a07fda2a0c181ff11683eb907a16045bf0fcae66e4db58f703e7df9ee4`, source
`e12eb688a470e3a092038442ef1950ce5b52a30b`; it is unchanged.

Same 27 cubes / 1 kg iron sphere / 10 m / gravity 9.81 m/s² / two seconds,
dt = 1/1920 s, zero bounce/friction: the four material controls complete.
Density values remain 2500, 700, 7870, 917 kg/m³ for glass/oak/iron/ice.
Differences here are mass/inertia, **not** stiffness, oak grain or damage.
The ball comes to rest on the cubes rather than breaking them. Mechanical
loss includes inelastic contact, numerical integration and settling of the
initial 0.2 mm gaps; it is not labelled heat.

| Cube material | Dynamic mass | Mechanical change | Max normal-only per-step P residual | Calculation/read/audit wall time |
|---|---|---|---|---|
| glass | 117.640 kg | −98.332374 J | 1.42e−6 N·s | 19.675 s |
| oak | 33.6592 kg | −98.140838 J | 2.42e−6 N·s | 19.458 s |
| iron | 368.18272 kg | −98.823156 J | 7.06e−7 N·s | 19.672 s |
| ice | 43.78355 kg | −98.128600 J | 7.43e−7 N·s | 19.614 s |

The integrated coarse glass bouncing stack completes this measured run, losing
64.778617 J, but its normal-only P residual reaches 1.254 N·s when friction
acts. That is an incomplete account, not a momentum-conservation result. All
four refined isolated pairs retain the expected 0.5/1.5 m/s and 0.75 J loss
within the unchanged accuracy bounds.

At 1/960 s an earlier same-law zero-bounce control refused oak at 1.567 s
and ice at 1.400 s; glass and iron completed. Refined controls complete but
this is not spatial convergence or a full material-model admission.

An initial un-restored warmup probe with bounce 0.5/friction 0.3 produced a
glass-stack positive gain of 0.01811 J near impact, exceeding the gate. Its
normal-only momentum ledger also omitted tangential impulses. The integrated
adapter restores the authored start and observes the actual gated outcome;
it must not force that earlier failure time. The test's first fixed-time
expectation failed and was corrected without changing the solver or gate.
Passing an energy gate in one bouncing stack is not a complete contact proof.

The [coarse iron pair witness](evidence/physx-gpu/coarse-iron-pair-withdrawal.json)
retains another actual failed oracle: at 1/960 s the identical iron spheres
leave at 0.518512/1.481488 m/s, losing 0.768170 J instead of 0.5/1.5 m/s and
0.75 J. A private PGS comparison and refined TGS both match that oracle. The
public TGS pair now requires 1/1920 s; the failed coarse capability is
withdrawn, not admitted by loosening 2e-4 m/s / J accuracy bounds. Stack TGS
remains explicitly identified; no silent solver substitution occurs.

Normal impulse balance includes gravity and the actual whole-world momentum
change. Refined friction-free controls retain per-step linear residuals below
1e-5 N·s. The trace also reports normal torque and an angular residual using
start-position gravity torque; positional solver corrections remain visible.
**Friction is not included in these normal-force reads.** Full contact work,
support torque, numerical loss and energy accounts remain incomplete. The
public qualification flags remain false; isolated pair conservation does not
certify the whole pipeline.
PhysX reported-point counts include the two sensor reports for internal
dynamic-body contacts; they are not unique-pair counts. Normal impulses are
summed over every sensor, so equal/opposite internal contributions cancel
rather than being counted as an external source.

## Verification and next steps

[Actual CUDA regression](../tests/physx_contact_test.py) is registered in CMake
as `banjo_physx_contact_tests`, opt-in through `BANJO_NEWTON_PYTHON`. It tests
all four refined stack controls, four refined analytical equal-mass sphere impacts,
actual gated bounce outcomes, exact scene retention on refusal, injected SDK
capacity faults, JSON-only transport and unsupported-command preservation.
The Newton contact, existing gateway, pipeline and playback suites are retained.
Final scoped CTest results: PhysX 134.30 s; Newton 34.82 s; gateway 3.75 s;
pipeline 7.19 s; playback 0.04 s — all five pass. Earlier failed coarse-pair
and fixed-refusal-time checks are resolved by explicit withdrawal and corrected
test expectations, respectively, not by larger tolerances. Normal browser
setup/run/inspection completes all 3,840 substeps on the private gateway. The
actual ball rests on the original cubes; edge outlines show each rigid
constituent. End-to-end speed is about 0.08x, solver/read/audit about 0.10x.
Portrait 390x844 and landscape 844x390 have no horizontal overflow. These are
browser layout checks, not a physical-phone or mobile-GPU qualification.
Source-registration guard: 342/342 C++ files, no exclusions. These are scoped
checks, not the entire repository regression or cross-GPU determinism.

[October 9 phase measurements](gpu-phase-profile-checkpoint.md) now isolate synchronized SDK stepping as 60.5% of the measured coarse glass control, with observation 35.7%. Four-iteration and coarse CCD shortcuts are withdrawn; no speedup is claimed.

Next measure kernel/launch/wait costs within SDK stepping, batch resident
observations without dropping substeps, and complete friction/reaction/work
accounts. Resolve rebound/position-correction validity and refine coupled
contacts. Then port Banjo's bonded material/history laws into the resident
pipeline with glass/oak/iron/ice comparisons and real 3D fracture/dents. Keep
CuPy for shared-source custom kernels/reductions and preserve CPU reference
oracles; do not advertise stock rigid cubes as material voxels.
