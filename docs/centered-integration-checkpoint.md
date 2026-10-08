# Centered elastic integration in the voxel laboratory

October 8, 2026. **Implemented experimental integrator foundation; complete
impact accuracy, useful speed and the full platform goal remain OPEN.** This
is not compliant surface contact. The default native-motor/reference contact
and its prior glass-ball failure are retained.

## Implemented equations and ownership

The reference native spring law uses backward Euler. Its stiffness term adds
integration damping even with material damping zero. The alternative uses the
same declared stiffness `k` and damping `c`, with a centered impulse row:

`J = -h [k q0 + (c/2 + h k/4) (v0 + v1)]`

and centered displacement `q1 = q0 + h (v0 + v1)/2`. A generated build-local
Jolt overlay exposes an optional pose-velocity callback. It supplies the actual
start/end velocity average during native integration, before the ordinary
bounds update; it does not correct final energy or scale accepted velocities.
Absent that callback, the pinned integration expressions remain unchanged.
Fetched sources are not edited; all consumers share the generated class layout.

The custom face constraint expresses this row through native softness (`k/4`,
`c/2`, `C=4 q0`, bias `v0`). Those are numerical row coefficients, not changes
to material properties. All rows still solve together with native contacts.
Rotation uses the existing SO(3) logarithmic strain differential frozen at the
start of the solve. That does **not** establish an exact nonlinear discrete
gradient over a finite rotation. Finite-rotation/coupled-contact energy is open.
The scalar and principal-axis oracles below are the validated boundary.

`face_law: "centered-log-gradient"` selects matching faces and pose integration
before bodies exist. Unknown declarations still refuse. `setCenteredIntegration`
is similarly configuration-only. Mixed connector/pose integration, live model
changes, CCD, kinematic bodies and unsupported joints refuse. It requires native
phase observations and only matching face connectors. Every step refreshes
start velocities; a rejected trial restores poses, native spring caches and
observations before retry. No shard pattern, launch motion or forced velocity
is authored.

Native displacement-based sleep zeroed a still-oscillating pair after 0.5 s in
the new oracle. The centered reference disables that time-based sleep so these
oscillations retain their energy. This is explicit, costs computation, and is
not a general energy-preserving sleep/island policy. Reference sleep is unchanged.
External native force/gyro integration and surface response are still separate
operators, so this is not yet a fully centered contact/material integrator.

## Analytical verification boundary

The native suite now has **88 scenarios**, in inline and thread-pool runners.
It retains all previous interface/contact/rollback scenarios and adds:

- Glass/oak/iron equal 0.1 m cubes, 1000 N/m linear spring, initial 1 cm
  extension and opposing 0.1 m/s velocities, dt 1/240 s for 240 steps.
  Damping is either 0 or declared 20 N s/m. Velocity/pose equations, declared
  damping work, total P/L and rejected-trial restoration are tested.
- The same density-dependent fixtures with a principal-axis 10 N m/rad
  torsion spring, opposing 0.1 rad/s spin, damping 0 or 0.02 N m s/rad,
  dt 1/240 s for 240 steps. These are declared spring oracles, not calibrated
  catalog stiffness or general finite-rotation validity.
- Binary-exact freefall: 8 m/s² gravity, dt 1/256 s for 256 steps, initial
  height 10 m and zero velocity. Final height 6 m, speed 8 m/s and energy
  residual zero. Exact binary inputs isolate integration from native float
  accumulation. Exploratory 9.81 m/s², 1/240 s stepping had +0.00110001 J
  total residual; it is **not** certified by the binary test.

Undamped translation energy errors are at most 6.66247e-8 J in these runs;
undamped torsion errors reach 8.80411e-8 J. The new translation bound is
2e-6 J over 240 steps and torsion bound 2e-7 J, accounting for native float
roundoff/rotation drift; binary freefall uses 1e-10 m/J. Damped errors and
actual losses are recorded in the oracle log. Existing energy gates and
reference tolerances are not relaxed.

## Actual coupled worlds

The diagnostic CTest runs common glass/oak/iron/ice sheets and a glass ball,
with all original cell IDs/masses, finite poses, actual contacts, honest
qualification, exact snapshot retention after refusal and work records. It
verifies reporting/refusal behavior, **not the full conservation/admission gate**.
A completed comparison is not accepted as calibrated material realism.

Conditions: Windows x64/MSVC Release CPU, continuous-small-rotation OFF;
40 × 40 cm, 4 mm, 8 × 8 / 64-cell sheet, 32 cm support gap; 1 kg constituent
ball dropped 10 m; host dt 1/960 s, 96 velocity iterations. Contact response is
explicitly inelastic unilateral. Same declared densities 2500/700/7870/917 kg/m³
and stiffnesses 70/12/211/9 GPa retain sheet masses 1.6/0.448/5.0368/0.58688 kg.
Oak remains an elastic density/stiffness comparison, with no grain/organic
physics or gameplay enablement; iron remains elastic without permanent dents.

Exploratory serial comparisons found oak/iron/ice completed two seconds, while
iron-ball/glass-sheet refused at 1.903077443 s and glass-ball/glass-sheet refused
at 1.428241984 s. Both stopped at the unchanged depth-14 energy gate. The final
verified measurements and exact executable hash are recorded below and in the
website manifest. The new option is not promoted to the default.

The centered numerical elastic term is zero **for its frozen linear row**.
Geometry/rotational residuals and actual contact work remain signed diagnostics;
zeroing that formula does not imply zero numerical loss in the full world.
Full P/L/E residuals remain unqualified. Contact is still an instantaneous
inelastic constraint, with no normal indentation energy/compliance.

## Next required correction

Couple actual contact normal compliance with the material solve and use an
energy-consistent finite-rotation/geometry integrator. Its contact potential,
reactions/torques, damping and external work must enter the same ledger. Native
float cancellation/pose precision must be separated from nonlinear geometry
error. This build still uses the pinned 1e-6 rad angular-increment dead zone;
the existing continuous-rotation compile option remains OFF because its prior
full-world comparison regressed. The next bounded correction can apply
continuous pose integration to the centered path specifically, leaving the
reference untouched, then repeat contact/geometry refinement. It must not be
called a fix until the full-world gates pass. Passing isolated springs is not enough: both glass-ball and the matched
four-material worlds must complete with bounded full-system residuals and
refinement evidence. No tolerance relaxation or kinetic-energy rescale is planned.

Then reduce active/global substep work without silently changing these laws.
Persistent metal yielding/tearing, adaptive mass/history transfers and validated
custom material/geometry authoring remain required by the full active goal.

The 3D website exposes Centered under Physics & record / Interface solver,
with explicit limits and native accepted states/refusals. It still displays the
reference by default. Source registration remains **331/331**, no exclusions.
Source, tested native hash, scoped test results and the running build identity
are pinned by `client/voxel-lab/checkpoint.json` after verification. Local
artifacts stay in `build/voxel-centered-*`; no build products enter Git.

## Verified checkpoint evidence

Eight scoped CTests pass in **483.19 s** (parallel 2): 88 native interface/
contact scenarios, rigid work, reference worlds with retained refusal, the
six prior unilateral experiments, five centered reporting/refusal diagnostics,
gateway, delivery pipeline and playback. The centered diagnostic has three
completed drops and two retained refusals; **its physical accuracy gate is OPEN**.
Four-material comparison against the published unilateral executable matches
physical and work records at 120 observations through two seconds; only
profiler fields and the contact qualification label are excluded. No full-
repository, phone, other-OS or cross-GPU validation is claimed.

| Sheet / ball | Physical s | Wall s | Substeps | Sheet / ball pieces | Energy deficit J | Declared spring damping J | Contact work J | P residual N s | L residual N m s | Admission |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| glass / iron | 1.903077443 | 83.718 | 58,399 | 19 / 1 | -99.190209 | 35.172092 | -70.179092 | 0.0033660186 | 0.0015954004 | REFUSED |
| oak / iron | 2.000000000 | 59.081 | 25,087 | 1 / 1 | -43.001001 | 21.311731 | -26.364363 | 0.0020697687 | 9.9255213e-05 | Completed, unqualified |
| iron / iron | 2.000000000 | 75.802 | 30,795 | 1 / 1 | -55.430024 | 41.995080 | -21.704685 | 0.0020779242 | 0.0003822469 | Completed, unqualified |
| ice / iron | 2.000000000 | 50.326 | 56,996 | 64 / 1 | -86.423146 | 21.164650 | -70.387708 | 0.0028981562 | 0.0051831049 | Completed, unqualified |
| glass / glass | 1.428241984 | 57.575 | 22,306 | 12 / 1 | -10.713573 | 10.273253 | -9.818349 | 0.0022779327 | 0.00012820576 | REFUSED |

Wall timings here share the scoped run; they are not a speedup measurement.
Full P/L/E residuals in this table remain unresolved, not new admission bounds.
Declared damping is a model term, not calibration; the numerical residuals
are not renamed as physical heat. The glass-ball energy deficit at refusal is
not a two-second comparison with the earlier -96 J completed experiment.

Verified native SHA256:
`10620873f31bf13e869494a306ebc5769b7c7524b1aa38195e5923d43e53f62b`.
Records: `build/voxel-centered-final-results.json`, `build/voxel-centered-ctest.log`,
`build/voxel-centered-baseline.log`, `build/voxel-centered-oracles.log`. The
earlier `build/voxel-centered-probe.json` contains exploratory runs, including
an instantaneous-reference-contact glass-ball refusal at 1.428401311 s; it
is not a replacement for the final verified build's scoped results.
