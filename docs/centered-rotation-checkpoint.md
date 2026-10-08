# Continuous rotation in the centered voxel integrator

October 8, 2026. **Implemented numerical correction; full-world accuracy and
speed remain unqualified.** This continues the
[centered integrator](centered-integration-checkpoint.md), not a new contact,
fracture or plasticity law. The full five-part physics goal remains active.

## Correction and scope

The pinned native rotation step ignores increments at or below 1e-6 rad. At
smaller timesteps, angular velocity and spring impulses continue changing while
the orientation stops integrating. The centered path now uses the same native
axis-angle quaternion update and normalization for every positive representable
increment. Exactly zero increments remain unchanged. This is the integration
operator itself, not an after-the-fact pose or energy correction.

The build-local force/pose overlay supplies a distinct inline body method and
calls it only when centered pose integration is enabled. It changes only body
orientation; the native centre of mass is retained. Default integration and
position-constraint corrections keep their original expressions. The separate
global continuous-rotation option remains OFF. Its overlay now composes with
the new method instead of shadowing the shared body declaration.

Source: `cmake/JoltForceObservation.cmake`, `cmake/JoltSmallRotation.cmake`, and
the compiled registered `tests/voxel_face_spring_tests.cpp` target. Fetched Jolt
sources are unchanged. All Jolt consumers receive the same generated headers.
No prescribed fracture, launch motion, velocity rescaling, forced rolling or
material-name response is added. Native float orientation/velocity precision
and frozen finite-rotation spring gradients remain limitations.

## Analytical experiments

Windows x64, MSVC Release CPU, Jolt 5.6.0. Glass/oak/iron use the same 0.1 m
cubes, zero gravity and initial x spin 0.000128 rad/s. Catalog density remains
2500/700/7870 kg/m3; mass is 2.5/0.7/7.87 kg before native float conversion.
The free-spin experiment does not load the declared material stiffness and
does not validate fracture, metal yield or wood grain.

Each fixture runs one second with 64, 256 and 1024 steps in both inline and
thread-pool execution. Per-step increments are 2e-6, 5e-7 and 1.25e-7 rad.
At the two finer steps the old native cutoff would freeze the orientation.
The test also confirms that the pinned reference still freezes at 256 steps
when the global experimental option is OFF.

All refined centered runs reach 0.000128 rad with maximum angle error
8.58065e-10 rad. The new angle bound is 2e-9 rad over one second, reflecting
native float quaternion accumulation; no earlier tolerance is relaxed. Centre
change is zero, spin error is below 1e-10 rad/s, kinetic change is at most
3.88051e-17 J, and angular-momentum change is below 1e-12 N m s. Rejected trial
orientation is restored exactly. These are six new material/runner groups
alongside the existing 88 scenarios, not a full-world conservation claim.

The retained 240-step principal-axis torsion experiment improves as follows:

| Material | Undamped energy error J, before | After | Damped error J, after |
|---|---:|---:|---:|
| Glass | 5.36605e-10 | 5.36605e-10 | 2.67463e-11 |
| Oak | 3.14226e-11 | 3.14226e-11 | 2.57639e-12 |
| Iron | 8.80411e-8 | 2.96343e-10 | 8.22817e-11 |

Its declared 10 N m/rad spring, damping 0 or 0.02 N m s/rad and dt 1/240 s
remain unchanged. Existing translation, contact, recovery and binary freefall
oracles pass. Ordinary 9.81 m/s2 gravity, arbitrary finite rotations and
coupled surface contacts remain outside this isolated validation boundary.

## Full-world evidence

Eight scoped CTests pass in 473.80 s (parallel 2): retained reference worlds,
six unilateral experiments, five centered reporting/refusal diagnostics, native
face/work oracles, gateway, pipeline and playback. The strengthened reference
dead-zone assertion was then rebuilt and the complete native oracle suite
rerun successfully. A safe refusal test is not physical admission. The depth-14
and 0.1 J energy gates remain unchanged.

Conditions match the prior centered checkpoint: 40 x 40 cm, 4 mm, 8 x 8 / 64
sheet cells; 32 cm support gap; 1 kg ball dropped 10 m; host dt 1/960 s, 96
velocity iterations, unilateral normal contact. Sheet masses are
1.6/0.448/5.0368/0.58688 kg for glass/oak/iron/ice; stiffness remains
70/12/211/9 GPa and density 2500/700/7870/917 kg/m3. Original cell IDs/masses
and the last accepted state after refusal are retained. Oak remains an elastic
comparison without grain/organic gameplay; iron has no persistent plasticity.

Four-material default-build comparison against the prior published executable
matches physical and work records at every 16 host ticks through two seconds.
Only profiler fields and the unchanged contact qualification label are excluded.
The combined global-rotation/centered overlay also configures and compiles the
Jolt target in a separate directory; this checks header composition, not full
physics qualification of the previously regressing global option. It stays OFF.
No full-repository, physical-phone, other-OS or cross-GPU validation is claimed.

| Sheet / ball | Physical s | Wall s | Substeps | Sheet / ball pieces | Unclosed E J | Declared damping J | Contact work J | P residual N s | L residual N m s | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| glass / iron | 2.000000000 | 157.888 | 101195 | 26 / 1 | -41.983014 | 18.904441 | -34.828416 | 0.004295226 | 0.022722545 | Completed, unqualified |
| oak / iron | 2.000000000 | 64.394 | 27050 | 1 / 1 | -42.993918 | 22.349349 | -25.918157 | 0.002184121 | 0.000184082 | Completed, unqualified |
| iron / iron | 2.000000000 | 76.851 | 30677 | 1 / 1 | -55.959663 | 43.750217 | -18.813392 | 0.002446179 | 0.000491405 | Completed, unqualified |
| ice / iron | 1.935725403 | 114.190 | 103561 | 64 / 1 | +0.099999588 | 14.538593 | -21.028805 | 0.006199853 | 0.061773081 | REFUSED |
| glass / glass | 1.428182093 | 60.306 | 22617 | 13 / 1 | -10.725080 | 10.724648 | -9.887268 | 0.002127893 | 0.000123485 | REFUSED |

These norms and deficits are unresolved measurements, not new acceptance
bounds. Timings share the scoped batch; no speedup is claimed. The iron-ball /
glass-sheet comparison now completes, but the previously completed centered
ice comparison hits the cumulative energy gate. This regression remains
visible; the corrected rotation does not justify relaxing or removing the gate.
The optional centered model stays experimental and default behavior is retained.

The rejected glass-ball step has h=6.357828776e-8 s, energy increment
0.001088691 J and measured contact work +0.001209840 J. Its spring work is
-0.000493420 J and elastic increment +0.000382217 J. Full-run spring residual
is 9.836004 J; the ice geometry-change diagnostic reaches +33.230439 J.
Those terms identify further defects; they are not physical heat. In particular,
an endpoint unilateral velocity constraint is not automatically compatible with
midpoint pose integration: for a fixed linear contact normal, the predicted
gap is `gap0 + h*(vn0+vn1)/2`, rather than `gap0 + h*vn1`. A consistent
surface law/solve and finite-geometry refinement must test this mismatch. This
observation does not prove that it explains every loss or the complete refusal.

Native SHA256 of the tested candidate:
`7ca74c0883a7b7a8e75b383c72af8309a6e203ea8de7cdf11abcf6298b7e1450`.
Build/oracle artifacts: `build/voxel-centered-rotation-build.log` and
`build/voxel-centered-rotation-oracles.log`; full records are
`build/voxel-centered-rotation-final-results.json` and
`build/voxel-centered-rotation-ctest.log`; default parity is in
`build/voxel-centered-rotation-baseline.log` and combined-header compilation in
`build/voxel-centered-rotation-global-build.log`. Compiled source registration is
331/331 with no exclusions. The live website is updated only after the verified
native and source revision are pinned in its checkpoint manifest.

## Remaining work

Coupled normal compliance must retain its actual indentation potential,
reactions, damping and friction. Finite-rotation/geometry integration must
account for its work without replacing unexplained losses with heat. Correct
full-world energy and refinement come before promoting this experimental model.
Useful speed, permanent metal dents/yield/tearing, adaptive cell mass/history
transfer and bounded material/geometry authoring remain required. The player
world and saved games are not migrated or reset by this laboratory checkpoint.
