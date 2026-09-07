# Rigid contact restitution checkpoint

Recorded 2026-09-07. Environment: Windows 11, MSVC 19.44.35228.0, Visual Studio
17 2022 generator, x64 Release, Jolt v5.6.0. Backend `material-network-v2`.

## The defect

Every contact in the network lane was perfectly elastic. Measured on a rigid
80 mm iron ball dropped 0.10 m onto a rigid glass plate:

| host step | first rebound / drop height | effective restitution |
|---|---:|---:|
| 1/480 s | 1.000 | 1.000 |
| 1/4800 s | 1.000 | 1.000 |

Identical at both steps, so this is not penetration correction at a coarse
step; it is the restitution the engine was actually applying. Both materials
declared restitution 0.

The route: `combineContactMaterials` (`src/material/MaterialCompiler.cpp`)
derives the combined restitution from the compliance-weighted contact damping
ratio and reads nothing else -- it ignores each side's declared `restitution`
and the `derive_restitution_from_damping` flag. The network lane's
`contactMaterial()` (`src/platform/NetworkWorld.cpp`) built its contact
definition with `restitution = 0`, `contact_damping_ratio = 0` and
`derive_restitution_from_damping = false`. The first and third of those were
never read; the second was, and under the damping model zero damping is a
perfectly elastic contact. So the intent -- inelastic cell contacts -- was
inverted for every rigid body and every lattice cell the lane created,
including every fragment-fragment and striker-fragment contact in every
fracture scene recorded before this checkpoint.

## The change

- `NetworkMaterial` gains `contact_damping_ratio`, declared per material in the
  package, separate from the internal bond `damping_ratio` as AGENTS.md
  requires. When a package omits it the engine uses its general
  `MaterialDefinition` default of 0.05 and the report says so per material
  (`contact_materials[].defaulted`), so a silent zero cannot recur.
- `contactMaterial()` carries that value into the rigid lane with
  `derive_restitution_from_damping = true`, matching how every other material in
  the engine is compiled.
- The report gains `contact_materials`: each material's declared contact
  damping and the self-contact restitution the model derives from it.
- The authoring catalog (`examples/authoring/presets.json`) declares the values
  the reference catalog already used: glass 0.08, iron 0.18, oak 0.24.

The combiner's disregard of a declared `restitution` is recorded, not fixed:
after this change nothing in the engine sets `derive_restitution_from_damping`
to false, so the unread path has no remaining caller. A future explicit
restitution needs the combiner to honour it, or the flag should be removed.

## Measured after

Same scene, 0.39 m drop, glass 0.08 and iron 0.18 declared:

| quantity | before | after |
|---|---:|---:|
| first rebound / drop height | 1.000 | 0.523 |
| effective restitution, iron on glass | 1.000 | **0.723** (model predicts 0.715) |
| bounces in 3 s | 5, still bouncing | 7, then still |
| within 2 mm of rest height from | never | **1.35 s** |
| movement in the final 0.25 s | 181 mm | **0.000 mm** |
| mechanical energy, 9.738 J in | 9.696 J | 1.666 J (resting potential) |
| plate displacement / tilt | 0 / 0 | 0 / 0 |
| ball penetration into plate | 0 | 0 |

Wall time 0.053 s for 3.0 s simulated, 0.018x realtime.

## What this does not establish

- The contact damping values are the reference catalog's, not measurements of
  glass or iron. Restitution 0.72 for iron on glass is plausible, not
  calibrated.
- Every fracture result recorded before this checkpoint used perfectly elastic
  fragment contacts. Their fragment counts were already known not to converge;
  this adds a second reason not to quote them.
- `combineContactMaterials` still cannot express a declared restitution.
