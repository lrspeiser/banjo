# Coupled endpoint friction with material bounce — October 8, 2026

## Implemented experimental correction

The native CPU world accepts an explicit `contact_law: material-block-friction`.
It uses the already compiled full 3 by 3 tangent/twist minimizer with endpoint
velocity gradients and the original Coulomb disk/twist caps. Native normal rows
retain the existing material-derived restitution. No midpoint friction bias,
post-hoc energy clamp, prescribed spin, precut fragment or launch velocity is
introduced. The default `material-restitution` world is retained.

Configuration happens before bodies/history exist. The same callback and native
constraint code apply to all materials and geometry; names do not pick an impact
animation. Glass and ice use the existing brittle interfaces; oak and iron use
their existing elastic interfaces. Oak grain and continuum metal plasticity are
not supplied by this contact correction. Normal rows, other contacts and springs
still solve iteratively; this is not a simultaneous island solve or full accuracy
qualification.

The 3D test website adds **Coupled friction + bounce · experimental** and a
**Physics step** input (1/960 or 1/1920 s). This input changes the declared native
calculation timestep; it does not change playback speed. Before/Live uses actual
initial/accepted cell poses. The native hash and explicit capability gate the new
selector. Other published running scenes/binaries are preserved.

## Reproduced defect and actual force phases

The previous reference glass/iron refined drop refuses at
1.4280320167542477 s, 4,059 accepted substeps, 10 sheet pieces / 36 failed faces.
Its candidate dt is 3.178914388020833e-8 s at depth 14. Candidate energy changes
96.7748071292405 → 96.7821604847986 J. The unchanged gate rolls this candidate
back; it is never rendered.

A read-only witness on the terminal rejected candidate splits the actual
common-force/solver contact work into:

| Normal | Sliding | Twisting | Sum |
|---:|---:|---:|---:|
| -0.000549316126 J | -0.002786684936 J | +0.010685443186 J | +0.007349442124 J |

There are 106 native patches. Original cells 139/140 contribute
+0.005917872069 J twisting work: projected relative spin after force is
+313.815098 rad/s and after solve +322.125995 rad/s, with a **positive**
1.8611385e-5 N·m·s impulse on B. This contradicts passive friction; it is not a
sign reversal driven by the preceding spring phase. The existing analytical
work account and independent summed contact witness agree. Complete records
remain in ignored `build/voxel-endpoint-block/failure-glass-material-restitution-1920.json`.

The witness records all-patch work totals and up to 256 individual patches,
including native IDs, geometry, impulses and actual force/solver spins. It runs
only on a terminal refused candidate, leaving ordinary accepted/temporarily
rejected reference records unchanged. The browser reports the three work
sources in the inspection drawer; Download record retains the details.

## Comparative measurements and limits

Matched conditions: 1 kg iron ball, 10 m drop; 400 by 400 by 4 mm sheet,
8 by 8 cells, 320 mm support gap; gravity 9.81 m/s²; 96 velocity / 4 position
iterations; original 107 visible/native cells; 2 physical seconds. Precise CPU,
Windows x64 / MSVC Release / SDK 10.0.26100, Intel Core Ultra 9 285K.
Separate CMake tree `build/voxel-contact-audit`, final executables
`build/voxel-endpoint-final/Release`; lab/CUDA/Rust OFF.

Densities/Young moduli remain glass 2500 kg/m³ / 70 GPa, oak 700 / 12 GPa,
iron 7870 / 211 GPa and ice 917 / 9 GPa. Sheet masses are 1.6, 0.448, 5.0368
and 0.58688 kg. These influence actual inertia and existing stiffness; declared
properties do not prove constitutive realism.

Final registered native regression (timings are diagnostic, not an isolated speed benchmark):

| Sheet | Host dt | Wall s | Accepted substeps | Pieces / failed faces | Unclosed energy J |
|---|---|---:|---:|---:|---:|
| Glass | 1/960 | 44.38 | 43,232 | 15 / 44 | -87.122997 |
| Oak | 1/960 | 9.97 | 6,351 | 1 / 0 | -44.911981 |
| Iron | 1/960 | 6.84 | 5,126 | 1 / 0 | -83.383632 |
| Ice | 1/960 | 39.24 | 50,049 | 61 / 109 | -103.743707 |
| Glass | 1/1920 | 43.04 | 39,832 | 16 / 44 | -100.461169 |
| Oak | 1/1920 | 10.44 | 7,617 | 1 / 0 | -44.888600 |
| Iron | 1/1920 | 7.63 | 6,660 | 1 / 0 | -83.238650 |
| Ice | 1/1920 | 66.70 | 75,257 | 64 / 112 | -73.446923 |

The retained refined glass failure completes in the optional mode. Different
fragment counts and large timestep-dependent energy deficits still fail a
convergence/conservation claim. Numerical loss is not thermal energy. These
wall timings are diagnostic measurements, not a paired speed claim: glass stays
roughly 0.05× realtime. Adaptive cells, connected local solves, full continuum
fracture/plasticity accuracy and qualified thermal/fluid/power laws remain open.

## Compiled and full-world regression

The existing native face/contact executable now checks endpoint and midpoint
anisotropic tangent/twist patches for glass, oak, iron **and ice**, in both inline
and thread-pool runners. Endpoint final stationarity gaps are
3.03613e-8 / 2.52140e-8 / 8.02035e-8 / 1.76408e-8 J;
actual common-phase friction works are
-1.77476 / -0.422151 / -5.02403 / -0.622810 J. The 5e-6 J native controlled
bound is unchanged. Analytical normal bounce checks retain each material's
restitution, kinetic loss and pair linear/angular momentum.

`banjo_voxel_endpoint_friction_tests` is registered in CMake with a 600 s bound.
It reproduces the reference refusal and independently verifies the work sources,
then requires eight actual native high-drop runs to **complete**, at both
specified timesteps. It checks original cells/masses, finite poses/velocities,
signed work closure, unchanged energy bound and measured material response.
A safely refused optional run does not pass that completion test. Passing these
regressions is not calibration, full energy conservation or realtime admission.

## Next work toward near realtime

1. Resolve normal/contact/interface island consistency and the large energy
   deficits; retain glass/oak/iron/ice timestep and spatial comparisons.
2. Keep connected material dynamics local rather than letting one thin spinning
   cell split the whole world. Account mass, momentum, elastic/plastic history and
   external work during cluster continuation and later-impact reactivation.
3. Add conserved adaptive occupied cells and qualify sustained ≥1 simulated
   second per wall second with the same material laws and observable 3D impacts.
4. Extend the shared pipeline to qualified heat, fluids, burning and power,
   visible free-form demonstrations and unit-bearing custom authoring.

## Reproduce

```text
python scripts/check-source-registration.py
cmake --build build/voxel-contact-audit --config Release --target banjo_voxel_world_run banjo_voxel_face_spring_tests --parallel 4
python tests/voxel_endpoint_friction_test.py build/voxel-endpoint-final/Release/banjo_voxel_world_run.exe
python tests/voxel_execution_test.py build/voxel-endpoint-final/Release/banjo_voxel_world_run.exe build/voxel-flight/Release/banjo_voxel_world_run.exe --strict-inline-baseline --alternate-request-order
python scripts/voxel-lab.py --native build/voxel-endpoint-final/Release/banjo_voxel_world_run.exe --port 18926
```

## Final verification and delivery evidence

**12/12 scoped CTests pass in 255.03 s**. The newly registered full-world test
passes in 231.72 s, including its retained negative reference case and eight
complete optional impacts. Source registration is **342/342**, no exclusions;
JavaScript syntax, Python compilation and changed-link/UTF-8/diff checks pass.
Native SHA-256: `eb3527a07fda2a0c181ff11683eb907a16045bf0fcae66e4db58f703e7df9ee4`.
Final native outcomes/work are in ignored
`build/voxel-endpoint-final/full-regression-results.json`.

Four complete default-mode prior-binary comparisons against published native
`79a0ff1372639e4768100a799bb4ec49e58208b2106618bb90881574004e27b0`
retain **every physical/work field at every 16-host-tick output** through two
seconds; profiling alone is excluded and request order alternates. No new
contact-witness field appears on ordinary reference accepted/temporary rejection
records. Exact default preservation is not experimental physics admission.
Private comparison log: `build/voxel-endpoint-final/default-parity.log`.

The ordinary browser refined glass Drop completes at 2 s with **16 pieces,
44 broken faces and 39,832 accepted substeps**, matching the compiled fixture.
Before restores 1/64 cells, zero failed faces and 0 s; Live restores the accepted
result. Screenshots are in `build/voxel-endpoint-final/browser-before.png` and
`browser-after.png`. The measured browser delivery is about **0.04× realtime**
with 60 renderer fps; host verification jobs overlap, so this is not an isolated
speed comparison. Its native stage profile records 36.101 s Jolt update out of
37.25 s total native step time, and original sheet cell 147 drives 87.6% of 35,990
motion split proposals. This strengthens the next action: connected local solves,
not more rendering animation. Large numerical loss and finite contact errors
remain explicit.

The scoped run excludes the unrelated legacy `long` material-network capacity
suite. An initial accidental selection of that suite was stopped after process
identity verification; its ordinary native observation/rollback counterpart is
included and passes. An initial build command named nonexistent capacity/rollback
targets; the actual registered capacity/component targets were built successfully.
Neither interruption is reported as a physical regression pass. No full-repo,
long-suite, phone, macOS or cross-GPU qualification is claimed.

### Retained momentum quantities

The table records final dynamic totals and source residual magnitudes, not a
conservation certificate. Native gravity, support reactions, numerical limits and
rotation terms remain separate in the complete per-material work records.

| Sheet / host dt | |P| N·s | |L| kg·m²/s | Solver linear source residual N·s | Full angular source residual N·m·s |
|---|---:|---:|---:|---:|
| glass / 1/960 | 3.934568 | 4.960063 | 9.22798e-05 | 0.0006621666 |
| oak / 1/960 | 3.975435 | 0.2228993 | 8.084308e-06 | 1.603685e-05 |
| iron / 1/960 | 1.268982 | 0.1076613 | 0.000174894 | 9.734988e-06 |
| ice / 1/960 | 0.2720995 | 0.1674994 | 7.279013e-06 | 2.161254e-05 |
| glass / 1/1920 | 1.199478 | 0.7032626 | 1.510564e-05 | 2.359408e-05 |
| oak / 1/1920 | 3.942514 | 0.2572404 | 1.319611e-05 | 2.946475e-06 |
| iron / 1/1920 | 0.6393364 | 0.05727018 | 0.0001179279 | 2.977388e-06 |
| ice / 1/1920 | 4.283099 | 5.313154 | 5.819442e-05 | 0.001075303 |

## Published checkpoint

Source, compiled regression registration, 3D controls and measured evidence are
on GitHub **main** at `e12eb688a470e3a092038442ef1950ce5b52a30b`. This follow-up records that
exact physics source revision in the website manifest; it does not change the
tested native binary or physical laws. The current 18926 server runs the native
SHA-256 above. The earlier 18924 scene is preserved.
