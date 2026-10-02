# Fixed head and handle checkpoint — October 1, 2026

## Status and scope

Implemented: an authored lattice head can have a separate lattice handle,
connected through active ordinary native fixings. Each body keeps its own
material, geometry and mass. The native point identifies both bodies; work
reports identify the held root and credit its holder. Detached, hinged,
one-way, missing and off-matter grip declarations refuse.

**R2 remains open.** This checkpoint qualifies the native authoring/use
prerequisite. It does not enable paid Workshop Make for mixed lattice groups.
The material-support guard still refuses that installation before spending or
substituting a constituent. Complete reviewed native allocation, paid
installation and the ordinary Lab → Save → funded Make → pickup/use journey
next. This is not a model-provider playthrough or calibrated joint-strength law.

Implementation was developed from published main `b9463f3`; the published
implementation revision is recorded below after verification and push.

## Native response

`tool_point` accepts optional `grip_body`. Declare actual constituents, their
finite ordinary fixings, then the point and interaction. Do not put different
materials under one lattice `join` label. The head's local point frame remains
head-local; actuator targets are transformed into the actual handle frame.
The handle receives one bounded external hand wrench. Native constraints and
terrain determine the later motion and any fixing failure.

Fixed assemblies use actual aggregate mass, center of mass and parallel-axis
inertia to size grip feedback. Damping measures the actual root grip motion,
not momentum-averaged motion that can hide relative motion. Controller
bandwidth is 20 rad/s for fixed assemblies; single-body 100 rad/s behavior is
unchanged. Limits remain 800 N and 60 N m. This is an explicit controller
assumption, not a new material law or imposed pose/velocity.

An active ordinary fixing owns the direct head/handle interface. Its touching
lattice hulls no longer get a competing Jolt collision response. Existing
hinged/sliding lattice contacts remain. Detachment restores the pair's contact
ownership. Terrain and unrelated object contacts remain active.

The free-body stroke projection explicitly refuses fixed assemblies because
it does not integrate their constraints. Use a jointed native trial instead.
No cached or analytical free-body result is represented as a fixing simulation.

## Matched measurements

Windows x64, MSVC 19.44 / VS 2022, Release CPU reference, native dt **1/240 s**,
body cells **40 mm**, flat dry soil columns **100 mm**, soil depth **400 mm**.
Oak handle: 800 × 40 × 40 mm. Head: 40 × 280 × 40 mm.
Fixture strengths are explicitly **5000 N axial / 5000 N shear** for every
material. No strength or test tolerance was raised to pass these experiments.

Same vertical readiness/contact/withdrawal experiment, with native bounded
pry/withdrawal where ground resistance prevents the short return:

| Head | Head mass kg | Oak handle kg | First closed soil kg | All ground work J | Hand work J | Unclosed work J |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 1.12000001 | 0.896000068 | 0.243 | 2.321392 | -12.241091 | 0.052239 |
| Oak | 0.313599997 | 0.896000068 | 0.049 | 0.807674 | -7.878323 | 0.045451 |
| Iron | 3.52575997 | 0.896000068 | 1.041 | 6.371438 | -26.203549 | 0.051397 |

Head densities are 2500/700/7870 kg/m³, respectively. The handle remains
700 kg/m³. Negative hand work includes lowering from the initial raised pose.
Unclosed work is hand work minus change in total native mechanical energy
(including gravitational potential) minus all recorded ground work.
It is reported, **not asserted to be zero or called full-pipeline conservation**:
contact/damping/integration/correction terms are not completely allocated.
No wood grain/plasticity, glass fracture calibration or metal joint realism is
claimed by this handling experiment. Terrain-volume residual is at most
3.56e-15 m³; summed actual removal matches the owner's native collected volume.
The peer receives zero.

Matched horizontal ground-resting pickup, reposition and point-down turn:

| Head | Peak axial N | Peak shear N | Hand work J | Unclosed work − change in mechanical energy J |
|---|---:|---:|---:|---:|
| Glass | 66.491156 | 207.424757 | 17.362817 | 0.536435 |
| Oak | 32.037853 | 61.549312 | 11.039821 | 0.377752 |
| Iron | 100.134636 | 596.977479 | 35.792540 | 0.656610 |

These are finite diagnostic residuals, not new conservation tolerances.
The previous browser pickup failed the unchanged 5000 N fixing when the seam
received competing responses. The retained matched pickup regression now
keeps the fixing attached and checks the hand force bound each step.

## Public controls and ownership

Python/C ABI, subprocess, in-process and MCP authoring/export/reopen/duplicate
retain the separate handle binding. ABI **26** appends grip metadata and adds
`banjo_make_joined_tool_point`; rebuild native consumers. Python checks the ABI
before registering new functions. Legacy snapshots without `grip_body` retain
their one-body meaning.

Carrying limits and native carrying diagnostics count the whole fixed assembly
once. Inventory does not add the head a second time. Holding, stowing, whole
restart and CarryAll reopen retain private ownership; a peer cannot take a
held head or another player's parked member. This is mass/ownership accounting,
not physical avatar or bag inertia (R5).

The browser uses ordinary E pickup, J Dig and Q Stow on an explicitly authored
QA fixture. It verifies positive native soil, head material, intact fixing,
4.42176 kg whole-tool accounting, private bag/page reload and server/native
restart. The held card lists both materials and whole-tool weight. This fixture
does not bypass the paid gameplay blocker or claim a funded build.

Use returns measured contacts from the entire preparation/stroke attempt.
Ground resistance can block a short return; a still-whole embedded point gets
the existing bounded withdrawal. An absent connected point disables the target
preview and directs the player to Lab rather than advertising an enabled Dig.

## Verification and artifacts

- Source registration: **287/287**, no exclusions.
- Six compiled CTest suites: live-world, room-carry, precise-rigid-parts,
  hand-stroke, ground-work and fixing. Ground-work includes **16 native cases**.
  Six-suite run: 34.78 s; ground-work: 1.78 s on this Windows host.
- **131** affected API/MCP/tool-use/knowledge/Inventory/quick-tool/two-lane checks,
  including actual Chrome rapid taps/hold, quiet save retry and stock restart.
- Public binding script: **five** check groups, including glass/oak/iron.
- Chrome native mixed-tool use/bag/restart regression, retained machine skill
  learning/navigation and screenshot inspection.

Local ignored evidence:
`build/resource-flow/mixed-native-ground-final.log`,
`mixed-native-final-tests.log`, `mixed-affected-tests.log`,
`mixed-binding-tests.log`, `mixed-browser-final-tests.log`;
screenshots `build/workshop-navigation/mixed-tool-native-use.png` and
`mixed-tool-native-bag-reload.png`.

Sources: [native world](../src/fastlattice/LiveWorld.cpp),
[native point](../src/fastlattice/ToolTerrain.cpp),
[matched tests](../tests/ground_work_tests.cpp),
[public lanes](../tests/live_lanes_agree_tests.py),
[browser journey](../tests/workshop_navigation_tests.py),
[MCP authoring](../mcp/banjo_mcp.py),
[shared Use](../playground/tool_use.py),
[C ABI](api/c-api.md), [model instructions](api/mcp.md).

The explicitly authored fixture has no saved recipe preview; Inventory's
generic thumbnail is not evidence of an assembled mixed-tool source picture.
Finish saved/paid design pictures with the full R2 player path.

Native GUI/raylib interaction, macOS, cross-GPU determinism, arbitrary mixed
tool reliability, fatigue/bending-joint failure and full physical conservation
are not established by these Windows browser/CPU checks.
