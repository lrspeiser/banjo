# Contact performance trial and retained regression checks

October 8, 2026. A trial to skip redundant friction solves passed analytical
checks and three complete impact comparisons, but changed the ice trajectory
at 1.45 physical seconds. The optimization was withdrawn and the original
contact evaluation restored. No simulation speed improvement is published.
Stronger whole-world comparisons and rendering fixes are retained.
Full accuracy, realtime speed, metal plasticity, adaptive cells and custom
authoring remain open.

## Withdrawn optimization

The solver first eliminates the unrestricted twist variable and solves the
remaining tangent disk problem. If the resulting twist lies within its allowed
interval, that solution is already the minimum over the restricted domain;
neither twist endpoint can improve it mathematically. The trial returned that
solution directly. If twisting is disabled, both interval endpoints coincide,
so the trial solved the disk problem once instead of twice. Active twist-boundary
cases retained the original endpoint enumeration. The baseline's floating-point
candidate evaluation is not proven identical to these shortcuts. The precise
numerical source of the ice difference has not been isolated.

The published code restores the complete original candidate enumeration and
64-iteration disk root calculation. Input refusal, impulse caps, constitutive
inputs, timestep, iteration limits and the energy admission gate are unchanged.
The parity assertion has not been relaxed. Native normal and subsequent island
rows still require convergence work.

## Analytical and native checks

The independent variational-inequality suite covers 4,224 disk/interval
problems, including tangent/twist coupling, zero caps, interior solutions and
active boundaries. It retains nonpositive kinetic work, cap feasibility,
tangent-basis invariance and invalid/overflowing-input refusal checks.
The native glass/oak/iron anisotropic and spin/sliding reversal controls run in
both inline and thread-pool modes with the existing conservation and
stationarity bounds.

After restoring contact evaluation, six focused CTests pass in 8.26 seconds: friction minimization, rigid work,
native face/contact controls, gateway, journal/pipeline and pose playback.
Source registration passes: 333 of 333 compiled sources, no exclusions.
These scoped checks do not establish full material realism or realtime speed.

## Local solver benchmark

Windows MSVC 2022 Release, precise CPU floating-point profile. Five runs of
each binary, 51,200 solves per case, identical inputs and matching checksums.
Timings are reported rather than used as CI pass thresholds. These numbers
describe the withdrawn trial, not the running published physics.

| Frozen problem | Baseline median ms | Optimized median ms | Ratio |
|---|---:|---:|---:|
| Sticking with admissible twist | 3.0247 | 1.9213 | 1.574 |
| Sliding with twisting disabled | 45.8620 | 25.4281 | 1.804 |
| Sliding with active twist boundary | 91.4152 | 89.8481 | 1.017 |

The last difference is too small to claim a useful improvement. Local helper
speedups do not imply the same improvement for a complete impact.

## Full impact comparison

Both trial and preserved coupled-friction binaries used inline execution and
identical declarations. Every 16 host ticks, the comparison required exact
physical, topology, impulse and work records; only wall-clock profiling fields
were excluded. Glass/iron, oak/iron and iron/iron completed two seconds with
exact parity. Ice/iron failed at 1.4500000000001938 s; glass/glass was not reached.

| Withdrawn trial | Baseline wall s | Trial wall s | Physical ledger change J |
|---|---:|---:|---:|
| Glass / iron | 165.3895 | 156.2254 | -64.834357 |
| Oak / iron | 69.3535 | 66.7955 | -43.016985 |
| Iron / iron | 114.3131 | 99.6962 | -61.647994 |

At the first failed ice sample, cell 62 differed in position by about 6.77e-9 m
in x and in spin by about 1.67e-6 rad/s in z. The contact work record also
differed. This is a numerical parity failure, not evidence of a new calibrated
material response. No broad speed or conservation qualification follows from
the three passing comparisons. The physical energy and momentum residuals
remain those of the preceding unqualified coupled-friction checkpoint.

The comparison harness now supports bounded individual cases and writes both
actual replies, the declaration, command and differences to a failure witness.
The rejected binary is preserved locally for reproduction. The restored build matches the original exactly through the ice counterexample
at 1392 host ticks (1.45 s), including every impulse and work field. Re-running
the rejected binary reproduces 66 differences and preserves a 298,327-byte
failure witness containing both actual replies. The original solver source
under src/ is identical to published revision 69875643. Existing full-drop
evidence is inherited; a new five-case full run is not claimed after restoration.

The declared experiment remains a 400 by 400 by 4 mm, 64-cell sheet across a
320 mm support gap, struck by a 1 kg ball dropped from 10 m. Host timestep is
1/960 s with unchanged adaptive refinement, 96 velocity and 4 position
iterations. There are 32 ball cells and 11 fixed support/floor cells. Declared
sheet density/stiffness are glass 2500 kg/m3 / 70 GPa, oak 700 / 12, iron 7870 /
211 and ice 917 / 9. Oak and iron remain elastic-only comparisons; oak grain
and metal yielding/tearing are not implemented by this optimization. Glass and
ice retain their existing brittle-interface model and its calibration limits.

## Browser and rendering

Viewport resizing and projection updates now run when dimensions change,
instead of every animation frame. Instanced cell rendering and interpolation
between accepted native states are retained. No rendering speedup is claimed.

Browser testing exposed a preexisting whole-rig camera defect: the 10 m ball
was outside the fixed framing. Whole-rig framing now derives its center and
distance from the initial transformed cell bounds and the viewport field of
view. Desktop 1280 by 720 and landscape 844 by 390 views, 10 m and 10 cm setup,
native stepping, Before/Live and Run/Pause were exercised. The short-drop
pause retained 0.101 physical seconds and 952 accepted substeps. Browser console
errors/warnings were absent. This is desktop responsive-layout coverage, not
physical-phone or GPU qualification. Private screenshots carry the accurate
unpublished/native-checkpoint warning that was present during testing.

## Remaining calculation work

The scene still refines all bodies according to its fastest cell and a global
thin-feature distance limit. Each trial snapshots native state, and each
observed contact step serializes the contact cache to recover impulses. Native
stepping includes these observers; its aggregate timer cannot distinguish
collision detection from solving and accounting.

Next: split those timing categories, measure rejected-trial and audit cost,
then develop local contact/island stepping with accounted exchanges. Fine cells
near impacts and thin edges require conservative transfer of mass, inertia,
elastic energy and damage history. Preserve the uniform CPU reference and
material comparisons throughout.

## Reproduction

Build tree: `build/voxel-contact-audit`; executable directory:
`build/voxel-friction-fastpath/Release`.

```powershell
cmake --build build/voxel-contact-audit --config Release --target banjo_contact_friction_block_tests banjo_voxel_face_spring_tests banjo_rigid_step_work_tests banjo_voxel_world_run --parallel 4
build/voxel-friction-fastpath/Release/banjo_contact_friction_block_tests.exe --benchmark
python tests/voxel_execution_test.py build/voxel-friction-fastpath/Release/banjo_voxel_world_run.exe build/voxel-coupled-friction-final/Release/banjo_voxel_world_run.exe --friction-fastpath-baseline
python scripts/check-source-registration.py
```

Evidence: `build/voxel-friction-fastpath-{build,ctest,baseline-microbenchmark,microbenchmark,parity}.log`.
Rejected trial native SHA256: `c9e8caa134facd7f3005fdb983d3b06655a0ea88b465b1ffc327343270b040f0`.
Restored native SHA256: `43131a17e44f92d07bbe2397d020875f086d77a353ff7b10d56af25bf1a571ae`.
The withdrawn optimization was local revision `c115a6e4f333ad418d88d6c55932b75e48a61fc0`;
geometry-based whole-rig camera: `328c8c3c`.

Restoration implementation revision: ddf187e492680ff0b978d6d15e49a49f790b7a12.
Evidence for the resolved trial failure: uild/voxel-friction-fastpath-{restored-build,restored-ctest,restored-ice,rejected-ice}.log and uild/voxel-friction-fastpath-rejected-witness.json.
