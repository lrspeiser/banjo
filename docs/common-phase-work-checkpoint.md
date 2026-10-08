# Realtime pipeline: actual native work phases

October 8, 2026. Windows x64/MSVC Release CPU; default native-motor interfaces,
continuous-small-rotation OFF. This checkpoint advances measurement for the
near realtime pipeline. Solver speed, glass-ball accuracy, permanent metal
deformation, adaptive cells and declarative authoring remain open.

## What is implemented

The live path remains input → background native CPU worker → latest accepted
timestamped state → independent 3D renderer. The renderer interpolates two
accepted poses and snaps when topology changes. It authors no fracture or
launch motion. Calculation time and rendering fps are separate measurements.

Before optimizing local solves, the CPU reference now observes actual native
velocities before forces, after gyroscopic integration, after other forces,
after the velocity solver, and after native speed limits. A generated build-tree
[Jolt overlay](../cmake/JoltForceObservation.cmake) adds read-only callbacks at
these existing operations. Original force, constraint and limit expressions
are retained. Shared dependency checkouts are untouched; target consumers use
the same overlaid class layout. Unknown pinned source markers refuse configuration.

[JoltWorld](../src/rigid/JoltWorld.cpp) retains bounded per-body measurements,
including sleeping bodies without counting old impulses again. Trial rejection
restores these observations with the physics state. Geometry and actual native
mass/inertia are measured before Update, when the force/velocity solver frames
are fixed in this wrapper. This does not qualify arbitrary step listeners that
change geometry during Update, CCD impulses, or additional contact owners.

[RigidStepWork](../src/physics/RigidStepWork.cpp) reconstructs independently
observed spring/contact impulses against a shared midpoint of post-force and
post-solver velocities. Normal, friction and twist contacts and spring anchor
torques contribute once. Gravity uses its actual native force phase. Native
speed-limit changes, subsequent velocity changes, gyroscopic work, inertia
rotation and unexplained solver work remain separate signed terms.

The world records potential and elastic change, full-world angular residual,
and the latest rejected candidate's work, actual dt and energy increase. Rejected
candidate motion is never published as accepted motion. Cumulative accepted work
excludes rejected trials. Fracture work and discarded interface elastic energy
retain their previous separate ledgers; accepted pre-fracture elastic changes
must be combined with those ledgers when interpreting final energy.

This arithmetic identity is **not** proof of conservation or a calibrated law.
Unexplained impulse/work residuals remain visible. Contact work may legitimately
remove kinetic energy, but constitutive validity and timestep convergence must
still establish whether that loss is correct. Velocity caps are numerical
operations, not material heat. Earlier endpoint diagnostics are retained and
explicitly separated from the new shared-phase terms; do not add both accounts.

## Verification contract

- Pure oracles cover known mixed impulses, omitted-source detection, freefall
  integration loss, gyroscopic/inertia changes, actual limit work and later
  velocity clearing, plus invalid mass/tensor refusal.
- Native oracles exercise actual angular limiting, gravity, sleeping bodies and
  reversible trials in both inline and thread-pool runners. Interface/contact
  tests retain both native-motor and optional log-gradient paths.
- Full two-second glass/oak/iron/ice execution comparisons retain exact physics
  outputs; runtime profiler fields are excluded. A comparison against the prior
  executable can additionally exclude the new measurement field only.
- Eleven default material/control/refinement experiments assert retained cell
  IDs/masses, finite work, arithmetic closure and the unchanged energy gate. The
  glass-ball failure is retained with precise rejected-trial evidence.
- Gateway, delayed-worker Pause, archive equality and bounded playback tests
  cover the actual delivery path. These scoped tests do not certify the full
  repository, a physical phone, other operating systems or GPU determinism.

## Next calculation work

1. Resolve source-residual attribution and minimum-step energy refusal in the CPU
   reference; preserve reaction/torque, numerical and support accounts.
2. Build one coupled material/contact solve for finite-cell deformation and
   persistent metal yielding, rather than changing display geometry.
3. Schedule independent contact/interface islands and retain shared time and
   accounted transfers where islands interact. Compare complete trajectories,
   conservation and topology against the CPU reference through impact.
4. Split/coarsen locally near contact, damage and thin edges while transferring
   mass, inertia, momentum, energy and constitutive history. Profile first;
   parallelize independent islands before considering a GPU kernel.
5. Admit custom material/geometry declarations through the same bounded pipeline.
   LLMs can author or explain on demand; neither simulation nor rendering waits
   for an LLM call each frame.

Targets remain ≥0.8 physical seconds per wall second for representative impacts,
≥50 render fps and p95 controls under 100 ms. Existing glass calculation is far
below that speed target. This measurement checkpoint claims no speedup.

Publication evidence and per-material measurements follow below.

## Measured checkpoint

Same conditions: 40 × 40 cm, 4 mm, 8 × 8 sheet on two edge supports with a
32 cm gap; 1 kg iron cell ball dropped 10 m; host dt 1/960 s, 96 velocity
iterations and unchanged global swept-distance/energy refinement. All rows
complete two physical seconds. Density and stiffness come from the retained
catalog: sheet masses are 1.600 kg glass, 0.448 kg oak, 5.0368 kg iron and
0.58688 kg ice. Declared density is 2500 / 700 / 7870 / 917 kg/m³ and Young's
modulus is 70 / 12 / 211 / 9 GPa respectively; interface coefficients use those
properties with the common geometry. Oak grain/plasticity,
permanent metal deformation, calibrated fracture and continuum refinement
are not implemented by this experiment.

| Sheet | Wall s | Substeps | Pieces | Spring work J | Contact work J | Unclosed E J |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 38.427 | 41,823 | 12 | -51.448874 | -44.380105 | -92.923298 |
| Oak | 7.742 | 6,410 | 1 | -20.182656 | -23.918989 | -44.166886 |
| Iron | 6.485 | 5,224 | 1 | -60.359767 | -22.498740 | -82.828571 |
| Ice | 41.376 | 73,631 | 62 | -41.084746 | -62.541600 | -103.151846 |

Limits remove **zero** work in all four default runs; measuring them rules out
this proposed explanation of the deficits. Subsequent velocity-change work is
under 4e-11 J. The shared-phase algebraic residuals are under 2.2e-12 J. Those
identities cannot certify the force law. Accumulated solver angular-source
residual norms remain 0.03219 / 0.02334 / 0.10562 / 0.002115 N·m·s. Full-world
angular residual norms are 0.00026077 / 0.0000024483 / 0.0000029034 /
0.00018377 N·m·s. Source attribution and integration accuracy remain open;
these values are reported rather than admitted under a new broad tolerance.

The default glass-ball run refuses at 1.427663485 s. The final rejected trial
has dt **6.357828776e-8 s**, depth 14, before 94.227130125 J and candidate
94.228949933 J. Contact work is +0.001799386 J, spring work -0.000181357 J,
and elastic change +0.000190467 J. Gravity work and potential change nearly
cancel; limit work is zero. This localizes the increase to contact/elastic
integration, but does not establish its numerical cause or fix it. The last
accepted state remains unchanged by refusal. The UI shows precise trial dt,
avoiding the old human error string's six-decimal rounding to zero.

Eight scoped CTests pass in **490.50 s**: rigid step work, native face springs,
optional log-gradient experiments, full runner parity, eleven default world
cases plus retained refusal, gateway, pipeline and playback. Current inline
and thread-pool runners agree on every physical/measurement output at 120
observations through each full two-second impact; profiler fields alone are
excluded. An earlier force-only probe compared all four impacts against the
published binary with exact old fields; the subsequent limit observer has
fresh current-runner parity, not a second old-executable parity claim.

Source registration is **331/331**, no exclusions. All new sources compile
in CMake targets. JavaScript syntax, Python compilation, UTF-8 and added docs
links pass. Native SHA256:
`c536066952a088fb90c42d51c49a489900c3378ff4d2ead26ff622f7e8d3cae0`.
Source/published revision is pinned in the website's checkpoint manifest after
the verified source commit. Local evidence is in `build/voxel-phase-results.json`
and the scoped CTest log; build artifacts are excluded from Git.


## Dormant spring follow-up

The CPU reference now distinguishes an actual scheduled spring solve from a
retained native lambda. A spring whose two dynamic endpoints are asleep keeps
its nonzero cached impulse. That cache is not a newly applied impulse, so it
must not enter this interval's work or source-residual audit. Nor may dividing
that old lambda by a smaller interval selected for an unrelated fast fragment
create a new fracture stress. Stored strain energy is still measured; a real
solve on waking restores ordinary stress evaluation. This changes no force,
velocity, constitutive coefficient, tolerance or energy admission expression.

Schedule observations are optional when native phase observation is disabled.
The voxel world requires them explicitly. Enabled constraints are considered
scheduled when either endpoint participates in the observed native integration
phase. The scope is the wrapper's unchanged enabled face constraints, with no
mid-Update authoring/listener geometry changes or additional contact owner.

A native first-step refusal exposed a rollback defect in the new observation
lookup: restoring an empty phase vector without its populated trial lookup
could access freed/out-of-range storage before the next Update. Trials now
restore the lookup with its vector. Native oracles exercise first-step refusal,
nonzero dormant cache, wake, and rejection after waking, in both execution
runners and both interface laws. This regression must pass before publication;
the crashing candidate was never installed in the live lab or published.

The baseline comparison excludes only profiler fields and three corrected
diagnostics: maximum spring equation residual, solver linear-source residual
and solver angular-source residual. All cell poses/velocities/spins, masses,
IDs, topology, fracture events, clocks, adaptive substeps, rejected counts,
energies, remaining audit fields and precise rejected-candidate records must
match at every 16 host ticks through glass/oak/iron/ice impacts. Tiny changes
to the summed linear-source diagnostic follow removing cancelling dormant
pairs; the physical linear momentum remains compared exactly.

The losses remain a solver/model problem. The shared-phase glass balance can
be separated into spring work plus elastic change, contact work, gravity plus
potential change, gyro/other-force terms, and the small remaining signed
numerical/source terms. Fracture work and discarded elastic energy enter the
same balance through the accumulated pre-fracture elastic change. This
identifies where the approximately 93 J deficit occurs; it does not establish
that those losses are valid material heat. Earlier endpoint estimates of
implicit elastic loss are still numerical diagnostics, not extra losses to
add to the shared-phase ledger. The next solver change must address coupled
contact/material evolution without suppressing the energy gate or inventing
heat. Glass-ball refusal, useful calculation speed, permanent metal dents,
adaptive spatial resolution and validated custom authoring remain open.


### Verified follow-up evidence

Windows x64/MSVC Release, continuous-small-rotation OFF; same geometry,
material catalog, host dt 1/960 s, 96 velocity iterations, 10 m / 1 kg iron
ball and 8 × 8 / 4 mm sheet declared above. No tolerance changes.

| Sheet | Wall s | Substeps | Pieces | Corrected solver angular-source residual N·m·s | Unclosed E J |
|---|---:|---:|---:|---:|---:|
| Glass | 39.209 | 41,823 | 12 | 1.44983e-5 | -92.923298 |
| Oak | 7.807 | 6,410 | 1 | 1.06481e-5 | -44.166886 |
| Iron | 6.633 | 5,224 | 1 | 4.80849e-5 | -82.828571 |
| Ice | 41.300 | 73,631 | 62 | 8.52462e-7 | -103.151846 |

The prior residual norms were 0.03219 / 0.02334 / 0.10562 / 0.002115 N·m·s.
The corrected values remain visible and nonzero. Full-world angular residuals,
energies, actual trajectories and fracture outcomes are unchanged in the
four-material baseline comparison. Smaller audit residuals are not an
improvement in the physical trajectory or a conservation certificate.
Comparative checks ran concurrently; their wall timings establish no speedup.
The glass calculation is still approximately 39 s for two physical seconds.

Glass's shared-phase energy change decomposes as follows (J): spring work plus
elastic change **-48.542372**, contact work **-44.380105**, gravity plus
potential change **-0.029277**, gyro plus other-force terms **+0.029693**,
and remaining solver/rotation/limit/post-integration terms **-0.001237**.
The sum is -92.923298 J. The approximately 48.75 J earlier implicit-elastic
estimate and 1.41 J material-damping estimate are endpoint diagnostics under
a locally linear spring interpretation. They are not independently additive
to this balance, and finite-rotation/contact convergence is unqualified.

Six scoped CTests pass in **215.89 s**: rigid work, 44 native interface/contact/
phase scenarios, eleven completed comparative/control/refinement worlds plus
the retained glass-ball refusal, gateway, pipeline and playback. Fine glass
sheets complete to 1.5 s with 18 pieces / 144 cells and 37 pieces / 256 cells,
retaining all original IDs and material-derived masses. First-step rollback
now works instead of crashing. The four-material prior-executable comparison
passes all 120 observations through two physical seconds with only the stated
three corrected audit fields and profiler fields excluded. This is not the
full repository regression, phone qualification or another OS/GPU test.

Glass-ball refusal is exactly retained: 1.427663485209286 s, depth 14,
dt 6.357828776041667e-8 s, before 94.22713012520605 J and candidate
94.2289499333797 J. Rejected contact work remains +0.00179938643 J.
No admission tolerance, gate, fracture energy or native contact law is relaxed.

Source registration: **331/331**, no exclusions. CMake compiles the affected
sources/tests. Native SHA256:
`4b082084fdb9fcfa0d586710b7c86a3b8cf0545a7f450821198669238cbc3ac9`.
Local evidence: `build/voxel-schedule-fixed-results.json`,
`build/voxel-schedule-fixed-ctest.log` and
`build/voxel-schedule-fixed-baseline.log`; artifacts stay out of Git.
The website manifest pins the verified source revision and executable hash.
