# Shared material laws on CUDA — October 9, 2026

## Delivered / explicitly bounded

`/materials` is a live 3D controlled-loading inspector on canonical localhost
18893. Apply an opening to all four interfaces, inspect a material, unload to
zero force and reset histories. CUDA computes the actual constitutive response
after each action. Damage and plastic rest persist in resident arrays. The
ordinary desktop browser is exercised before publication; evidence is below.

This is **a material-law port, not a coupled dynamic world**. It has no physical
clock, gravity, flight, collision or automatic fragmentation. The CPU drop
world and existing GPU rigid yard remain available. Full material interactions,
useful near realtime and the larger platform goal remain open.

The diagram has two 10 mm cells per coupon and one 100 mm² interface. Actual
opening is recorded in metres. A labeled optional ×1000 opening magnification
helps inspect micrometre deformation; cells and masses stay unchanged. These
positions visualize imposed loading, not solver-generated flight. Broken
connections disappear only when the actual cohesive law separates. No shatter
animation, shards, fracture pulse or launch velocity is authored.

## One law source, two execution backends

- [CohesiveInterfaceKernel.hpp](../src/physics/CohesiveInterfaceKernel.hpp) contains
  the existing piecewise-linear normal traction/history and independently
  integrated opening work. The checked CPU wrapper still validates coefficients,
  history and overflow. No physical coefficient or acceptance tolerance changes.
- [ConnectorModeKernel.hpp](../src/material/ConnectorModeKernel.hpp) contains the
  existing scalar perfect-plastic return. The checked six-mode CPU compiler and
  history validation remain in `ConnectorPlasticity.cpp`.
- [gpu_material_laws.py](../scripts/gpu_material_laws.py) embeds these complete
  headers in CuPy RawModule/NVRTC, FP64 and `--fmad=false`. Complete source is part
  of CuPy's cache key. Coefficients, two history buffers and candidate faults stay
  on CUDA. Accepted updates swap buffers; refused candidates preserve the
  accepted GPU and host state. Only bounded coordinates enter the website API.
- [gpu_material_oracle_main.cpp](../src/app/gpu_material_oracle_main.cpp) is a
  **compiled CMake target** exporting the actual catalog/section coefficients and
  checked CPU histories. The generated website profiles must match its output.
  Display names do not select outcomes in the kernel; rename invariance is tested.

The protocol adds `strain` and `unload` only for this declared inspector. Trying
to start its dynamics clock or send a normal rigid scene a material-loading
command is refused. Existing GPU solver choices retain their original laws,
timesteps, iterations and complete substep records. Worker stdout remains JSON;
the actual gateway records requested loading and returned history arrays.

## Models / work

The glass/oak/ice normal cohesive coupons use the existing analytical test's
explicit interface stiffness `K = 2 × strength² / Gc`, giving damage onset at
one quarter of separation opening. This is **not** inferred bulk stiffness,
calibrated plate behavior or an oak grain constitutive law. Catalog densities
are glass 2500, oak 700, iron 7870 and ice 917 kg/m³. Young's moduli remain
70/12/211/9 GPa respectively, but they do not enter this explicit cohesive
stiffness. Oak remains a comparison coupon and is not introduced into gameplay.

Iron's connector coefficients use the existing 10 mm square section compiler.
All six modes are compared on CPU/GPU; the website currently applies normal
translation only. First normal yield is about 9.479 µm. A direct 30 µm opening
retains about 20.521 µm plastic rest, including after unloading. It is not a
continuum dent, J2 model, hardening or tearing law.

Cohesive loading work is independently integrated from force, with changes in
stored energy and irreversible fracture work checked against it. Complete
separation costs `area × Gc`: glass 0.0008 J, oak 0.1 J, ice 0.00015 J. Closing
does not heal or refund fracture work. Area partition retains total work.

Connector loading uses its existing split: integrate elastic loading at the
old rest, then return at fixed coordinate. Physical yield work and numerical
return excess are separate. A single 30 µm iron increment has roughly 0.094787 J
stored, 0.410427 J physical plastic dissipation and 0.444287 J **numerical excess**.
This substantial excess is not heat or physical accuracy. Finer loading must
reduce it; GPU 64/128-increment checks preserve rest/physical work and reduce
numerical loss. No momentum, angular momentum, environment or whole-pipeline
conservation claim follows from these controlled constitutive checks.

## Verification / evidence

Windows 11, MSVC 19.44, RTX 5090, CuPy 13.5.1, NumPy 2.5.3; isolated pinned GPU
runtime expanded in `scripts/gpu-requirements.txt`. No silent CPU fallback.
Native drop executable remains byte-identical at SHA256
`eb3527a07fda2a0c181ff11683eb907a16045bf0fcae66e4db58f703e7df9ee4`.
Parent revision is `3e5d558fe254b7c989b8916d21e5992624d0ed8a`; the coherent outgoing
revision is recorded in Git and the user-facing report after publication.

[Actual comparative/parity record](evidence/gpu-material-laws/parity.json) includes:

- 61,520 CPU/GPU updates, zero scaled error in the measured cases.
- 61,520 **exact** checked CPU comparisons against the prior `3e5d558f` law
  implementations compiled in an isolated baseline target.
- Common glass/oak/iron/ice loading, persistent reversal/cycles, 4096 independent
  cohesive histories and 4096 full six-mode plastic histories, area partition,
  rename invariance, malformed inputs and injected nonfinite GPU candidate
  recovery. Maximum measured incremental work residual about 2.132e-14 J.
- Real production HTTP → worker → CUDA → accepted history → compressed record.
- Warm controlled-update measurements include upload, readback and host gates.
  Kernel timing is separately measured with CUDA events. These are **not physical
  seconds per wall second** and are not full-world realtime qualification.

Build/check commands:

```powershell
cmake -S . -B build/voxel-contact-audit
cmake --build build/voxel-contact-audit --config Release --target banjo_gpu_material_oracle --parallel 4
ctest --test-dir build/voxel-contact-audit -C Release -R 'banjo_gpu_material_laws_tests' --output-on-failure
python scripts/check-source-registration.py
```

Seventeen rebuilt/scoped suites pass: eleven existing cohesive/connector suites,
GPU material laws, gateway/pipeline/playback and both Newton/PhysX contact suites.
The final law run also passes the extra unloading-refinement and later-recovery
checks. Existing PhysX shadow comparisons still retain every substep. Ordinary
browser loading/unloading and responsive evidence is recorded below. This is not the full repository regression,
physical phone, other GPU or other operating-system qualification.

## Next required integration

1. Feed finite-cell relative coordinates and six-mode frames from resident bodies
   into these laws, retaining complete material/rest history. Reuse the law source;
   do not replace it with a name preset or joint break-force threshold.
2. Couple equal/opposite forces/torques with the authoritative contact solve.
   Account physical loading work, plastic/fracture work, normal/friction reactions
   and numerical corrections. No duplicate contact owner or one-way handoff.
3. Admit actual 3D glass/oak/iron/ice impact/rebound/unloading/refinement controls
   before adding a dynamic GPU fracture choice to the drop world.
4. Profile resident solve/launch/readback costs on that admitted world. The
   previous rigid PhysX control still costs about 14.3 wall s for 2 physical s.
   Thermal/fluid/power models, adaptive spatial detail and editable authoring are
   still required by the broader goal.

## Final measured follow-up

The final isolated nine-repeat warm controls on this RTX 5090 measure:

| Interfaces | Complete warm update, median ms | CUDA kernel, median ms |
|---:|---:|---:|
| 4 | 0.108 | 0.022 |
| 4096 | 0.756 | 0.045 |
| 65536 | 13.096 | 0.205 |

These are controlled updates, not dynamic seconds. No world speed claim follows.
Readback and the host audit dominate at 65,536 interfaces; moving the validated
audits/reductions onto CUDA is a next optimization after coupled integration.
GPU 64/128-step iron loading retains 20.521 µm rest and 0.410427 J physical
dissipation; numerical excess reduces from 0.010109 to 0.005060 J.

The ordinary desktop browser confirms common 30 µm opening, zero-force unload,
persistent iron rest and non-healing cohesive history. Responsive checks use
390×844 portrait and 844×390 landscape desktop-browser viewports; they are not
physical phone or mobile GPU qualification. The canonical server is restarted
after the source checkpoint, and its actual source hashes/revision are verified.
