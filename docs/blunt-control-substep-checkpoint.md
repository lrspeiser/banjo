# Blunt-control assertion under the stability clock

Recorded 2026-09-07 on `agent/integration` (`4e49f30` and after). Environment:
Windows 11, MSVC 19.44, Visual Studio 17 2022 x64 Release, Jolt v5.6.0, backend
`material-network-v2`.

## What failed

`banjo_network_runtime_tests` fails on the integration branch with

    [FAIL] equal-volume blunt tool control must retain intact soft tissue

(`tests/network_runtime_tests.cpp`, `sharpLocalDamageAndBluntControl`): after
720 host ticks of `assets/runtime-v2/02-blunt-four-materials.json` the
soft-tissue target must report 0 broken links, 0 damaged links and one
component. It reports damage. The suite took 16,785 s at low priority; every
other suite on the branch passes (skin 10,480 s, showcase, adaptive, capacity,
86 quick suites, source registration).

The assertion dates from `61c5edc`, when the network lane ran one internal
solve per host tick. It has not been run since `5603b8a` put the lane on its
own stability clock, which is when the price of this suite went from seconds to
hours; that checkpoint's claim "coverage is unchanged; only the price is" is
false for this assertion.

## What it is not

It is not the contact-damping change (`287c1c7`). In a world holding only the
tissue target and its tool, 720 ticks at the lane's own required 5 substeps per
tick:

| contact damping | tissue broken / damaged links | peak axial strain |
|---|---:|---:|
| 0.05 (the new default) | 0 / 0 | 0.317 |
| 0 (every contact perfectly elastic, the behaviour before `287c1c7`) | 26 / 34 | 0.631 |

The fix reduces damage; the old elastic contacts were the ones tearing tissue.

## What it is

In the suite's world the glass target sets the substep count for everything
(thousands per tick), so the tissue is integrated far finer than its own waves
require. The outcome does not converge with that count. Tissue and tool only,
with the substep count forced by a coarse glass target in the same world
(`build/blunt-probe/tissue_plus_glass{2,3}.json`; the glass never damages):

| substeps per tick | forced by | tissue broken / damaged | peak axial strain | first damage | tool rests at height, lateral drift |
|---:|---|---:|---:|---:|---|
| 5 | tissue alone | 0 / 0 | 0.317 | never | 0.050 m, 0.12 m |
| 901 | glass 2x2x2 (80 mm cells) | 0 / 1 | 0.394 | 0.082 s | 0.015 m, 0.26 m |
| 2,271 | glass 3x3x3 (53 mm cells) | 0 / 1 | 0.530 | 0.276 s | 0.021 m (still moving), 0.21 m |
| 4,699 | a 2x2x2 iron pacer (15 mm cells) placed 1.5 m away | 0 / 3 | 0.537 | 0.272 s | 0.050 m, 0.19 m |

The reconstruction residual stays inside the gate throughout (0.63, 0.35, 0.19,
0.35 of the irreversible extension), so the springs are resolved; the strain
that grows is real lattice state. Between 2,271 and 4,699 substeps the peak
strain settles at 0.53-0.54 and the first damage at 0.27 s, i.e. the resolved
answer for this scene is "damaged during the topple", not "intact".

The reason is the scene, not a solver defect that a smaller step would cure.
The tool is a 30 x 120 x 100 mm iron block dropped at 1 m/s from 0.235 m above
a soft-tissue **ellipsoid** (E 40 kPa, strength 15 kPa, failure strain about
0.375), 25 mm off the ball's centre. A tall block landing off-centre on a ball
topples: in every run it ends 0.12-0.26 m to the side, lying on one face or
another. Which face, and how hard the block's edge drags across the ball on the
way down, depends on the contact resolution, and the peak strain (0.317 at the
coarsest, within 15% of failure) sits on the wrong side of that sensitivity
once the contact is resolved. A control whose outcome is a toppling trajectory
cannot certify "blunt loading leaves tissue intact"; it certifies one
trajectory.

## What this means

- `main` is not fast-forwarded to the integration branch: a red hour-long suite
  is not a verified checkpoint, whatever the reason. The work stays on
  `agent/integration` and the lane branches.
- Local `main` (`5603b8a`) is in the same state; this suite has not passed
  since `origin/main` (`1d2d89f`), where the lane ran one substep per tick.
- The tolerance is not to be loosened and the assertion is not to be deleted.
  The control needs to become a control: the same equal-volume tool dropped
  centrally onto a flat tissue slab (or the ball held so it cannot topple), so
  that the only thing tested is blunt loading. The sharp case of the same pair
  (`01-sharp-four-materials.json`) must be re-verified at the resolved substep
  count in the same change, and the pair re-run in full (hours). That is a
  fixture change with a stated reason, made in its own commit, and it is not
  done here.

## Reproduce

    # probes (tissue + tool; optionally a glass pacer), 720 ticks each
    python - <<'EOF'   # writes build/blunt-probe/*.json from the fixture, see this checkpoint's tables
    EOF
    build/integration/Release/banjo_playground_record.exe --package build/blunt-probe/tissue_default_damping.json --steps 720 --output rec_default.json
    build/integration/Release/banjo_playground_record.exe --package build/blunt-probe/tissue_zero_damping.json    --steps 720 --output rec_zero.json
    build/integration/Release/banjo_playground_record.exe --package build/blunt-probe/tissue_plus_glass2.json     --steps 720 --output rec_glass2.json
    build/integration/Release/banjo_playground_record.exe --package build/blunt-probe/tissue_plus_glass3.json     --steps 720 --output rec_glass3.json
build/integration/Release/banjo_playground_record.exe --package build/blunt-probe/tissue_pacer3600.json       --steps 720 --output rec_pacer.json

The probe packages are the fixture with objects 7 and 8 (and object 1 at the
stated resolution) kept and the unused materials dropped; nothing else changes.
Read `report.objects[id=7]`, `report.network_substepping.substeps_per_host_tick`,
`report.maximum_observed_axial_strain` and
`report.reaction_reconstruction.maximum_residual_over_irreversible_extension`.
