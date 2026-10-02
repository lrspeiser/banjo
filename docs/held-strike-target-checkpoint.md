# Native fixed-source / continuous CPU target — October 2, 2026

## Implemented contract and experimental boundary

The [fixed-source contact phase](held-strike-fixed-contact-checkpoint.md) now has
immutable preparation and checked commit APIs. Preparation reads actual source
motion, mass/inertia, ordinary fixing tree/anchors, body/shape identities and
native tick without changing anything. Commit rejects a different world, changed
point, elapsed tick, changed source state/shape or topology; it recomputes current
admission, ownership, speed and numerical budgets before the first write. Shape
references keep their identities alive; the plan is an immediate transfer, not an
automatic cached simulation outcome or a future trajectory.

The serial double CPU backend exposes the current schedule-order point and a
validated external velocity transfer. It records delivered linear/angular impulse
and signed target kinetic change, with cumulative overflow preflight. Positions,
previous displacements, strain samples, bond damage/aliveness/failure/plastic
history, working caches, finite loads, captures and accumulated steps stay intact.
No target upload, pose correction, subcell spin law or elapsed-time reset occurs.
The signed work enters an enabled target energy ceiling with external force work;
do not also count the same incoming source energy in that ceiling.

`applyNativeFixedPointTransfer` prepares both sides before either write, then
commits on one host thread between steps. Its contact horizon is the target's
uploaded timestep. Unsupported float/parallel/GPU target transfer refuses before
the source changes. The adapter itself advances no time; its caller must own every
source/target witness and proxy pair and advance both systems on one accepted clock.
This is currently used only by the registered native/CPU tests.

**Normal held-tool object use is still unimplemented.** The experiment below uses
a freely moving, declared ideal fixed assembly, not the live hand controller or
a finite-strength fixing. Native cached joint loads are still separate from
external joint receipts. Finite joint failure, hand work, whole-step rollback,
LiveWorld pending fracture/grip/history, object-click routing and paid damage/reuse
are unqualified. R3 and all five remaining player goals remain open. No browser,
C ABI, LLM prompt, app flow, running preview binary or deployment changes occur.

## Matched experiment and material assumptions

Windows x64 / VS 2022 / MSVC 19.44.35228.0 / MSBuild 17.14.51, Release CPU,
`BANJO_BUILD_LAB=OFF`, `build/agent-paid-machine`; baseline `da55b93` plus the
implementation revision recorded below. Catalog seed 17, 40 mm grid, horizon 1.

The source has a native 80 mm iron cube (4.02944 kg authored mass) and a
240×40×40 mm oak handle (0.2688 kg), centred at (0,0,0) and (-0.16,0,0) m,
joined at (-0.04,0,0) m by an ordinary ideal weld (declared strength limits zero).
Both start at (6,0,0) m/s with zero spin. No hand force, gravity or damping is
applied. Actual native float mass/tensor/motion are used throughout; the source
is not released, merged, reset or represented by free lattice points.

Each target is a 120 mm cube of 27 live 40 mm cells centred at (0.095,0,0) m.
Its actual current nodes are queried against the native head every substep with
a 16 mm envelope / 10 micrometre search; the handle query must remain empty in
this fixture. Contact material combines the actual head leaf and target catalog
values. All source/proxy and joined-seam responses are externally owned. The
far static proxy is admission identity only and receives no target dynamics.

The target uses the existing elastic reference + strength-derived failure and
explicit axial plastic-flow compiler. Four constraint iterations, displacement
arithmetic in double, no damping/sphere/support/node-contact law. Density is
glass/oak/iron 2500/700/7870 kg/m³; modulus 70/12/211 GPa. Declared axial yield
and hardening enter the existing plastic return; oak is not renamed into a brittle
preset. Grain, full anisotropy, calibrated fracture/joint failure and realistic
impact constitutive behavior are unsupported; catalog properties are not proof
of those laws. This fixture does not calibrate a voxel resolution or physical tool.

At each shared t_n, contact transfers into actual source/target velocities, then
one actual native step and one target substep advance by the same dt. Status and
native step count are checked continuously. The loop does not upload between
steps; bond failures, damage, plastic state and pending loads persist. The base
experiment uses 2048×100 ns; the finer uses 4096×50 ns, both 204.8 microseconds.

## Measured outcomes — not full physics qualification

| Target / dt | Applied contacts | Broken bonds | Peak damage | Plastic work, J | Contact loss, J | Target-step unallocated energy, J |
|---|---:|---:|---:|---:|---:|---:|
| Glass / 100 ns | 1941 | 16 | 1 | 0 | 8.316543712 | −2.86799337267 |
| Oak / 100 ns | 3505 | 0 | 0 | 0 | 5.1941050442 | −1.60146458432 |
| Iron / 100 ns | 1466 | 0 | 0.053954161704 | 1.41572197266 | 19.4884703591 | −10.2802706609 |
| Glass / 50 ns | 3889 | 12 | 1 | 0 | 8.24075159674 | −1.61118191086 |
| Oak / 50 ns | 7267 | 0 | 0 | 0 | 5.13494873948 | −0.856792546052 |
| Iron / 50 ns | 3035 | 0 | 0.0316583923995 | 1.76179765982 | 19.4932813784 | −5.72258212086 |

| Target / dt | Raw combined linear residual, N s | Raw combined angular residual, kg m²/s | Native-step unallocated energy, J | Signed native transfer roundoff sum, J |
|---|---:|---:|---:|---:|
| Glass / 100 ns | 1.24612423563e−7 | 5.19787351837e−8 | 1.01661040475e−7 | 8.2536864228e−6 |
| Oak / 100 ns | 8.44312147122e−9 | 2.57651108825e−8 | 7.06116054516e−10 | 1.822025319e−4 |
| Iron / 100 ns | 4.13432579118e−7 | 2.9154194397e−6 | 1.84194960773e−6 | 1.74454613655e−6 |
| Glass / 50 ns | 1.99778580182e−7 | 1.37082547881e−8 | 2.02506908131e−7 | 1.78813986853e−5 |
| Oak / 50 ns | 3.97271371537e−9 | 2.78269742922e−10 | 2.45377407282e−9 | 5.82533873962e−5 |
| Iron / 50 ns | 1.4827460229e−6 | 9.32322129663e−7 | 5.15635606757e−6 | 1.06569069498e−6 |

The global residual subtracts named contact/reconciliation losses, removed bond
energy, plastic/damping work and signed contact-transfer roundoff; angular also
subtracts measured noncoincident-anchor couples. Separate before/after samples
attribute remaining changes to the free native step and the unforced target step.
This attribution is a measured accounting boundary, not proof that the target's
unallocated energy is a valid physical dissipation or that its angular drift is
acceptable. No compensation impulse, heat or velocity correction is added.

Target energy loss decreases at the smaller dt but remains substantial. Glass
topology changes 16→12 broken bonds. Iron plastic work also changes. **Energy,
angular conservation and topology convergence are unclosed qualification failures.**
Do not promote the loop to validated held-impact gameplay or silently reuse its
outcomes at another dt/resolution. Spatial-resolution and broader loading studies
remain outstanding; passing contact/transfer tests does not close those gates.

Contact phase work residual is at most 4.65730e−14 J. Native transfer uses the
existing per-contact 1e−5 SI budgets. Individual free native-step linear/angular
errors are at most 1.34261e−7 N s / 1.21524e−8 kg m²/s in the final plastic-law
fixtures. Target linear drift
after measured native-step accounts is at most 1.93821e−10 N s. The target angular
change remains unclosed, reaching 3.14051e−6 kg m²/s in the base iron case.

Exploratory aggregate 1e−6 linear/angular bounds failed: iron's target angular
drift exceeds that at 100 ns, and accumulated native linear rounding exceeds
it at 50 ns. They are not widened into a conservation pass. The retained tests
qualify exact contact/history transfers and explicit arithmetic accounts: native
per-step bounds 1e−6 N s / 1e−7 kg m²/s, target linear bound 1e−9 after separately
measured native-step error, phase work bound 1e−12 J, accounting attribution
1e−10 SI. Raw residuals stay visible; no earlier solver tolerance/law changes.

The audited loop takes approximately 0.269..0.278 s per base fixture and
0.525..0.534 s per finer fixture on this host, roughly 1315..1357 / 2563..2607
wall seconds per simulated second. These measurements include repeated geometry,
preparation/revalidation, native steps and target-state/energy snapshots. This is
an expensive reference experiment, not a production benchmark or real-time route.
Optimize measured phases only after preserving their laws/accounts and accuracy.

## Verification and next work

Registered tests cover immutable preparation, wrong-world/point/tick/pose/shape/
ownership/topology invalidation, serial target history/capture/load retention,
signed kinetic/impulse oracles, cumulative overflow and stale-point refusal,
negative contact work reducing an enabled energy ceiling, and explicit refusal
for unqualified float/parallel backends. The six matched loops verify actual
source/target clock continuity, mass retention, native/target material responses,
all fixture witnesses, separate phase attribution and decreasing target energy
defect at the finer timestep. There is no manufactured damage or fragment motion.

All 13 affected compiled CTest targets pass in 13.59 s: native lattice contact,
native/point rigid/fixed assembly contact, pair impulse, contact ownership,
conservative/tetrahedron contact, external lattice loads, fast lattice, plasticity,
ground work and hand stroke. Source registration passes 295/295, no exclusions;
`git diff --check` passes. New target final build has no warnings; existing broad
builds retain earlier shadow/unused/getenv and signed/unsigned warnings. Logs are under ignored
`build/resource-flow/coupled-*.log`. No normal-input/browser, graphical, GPU,
cross-platform or full-pipeline conservation qualification is claimed.

Next localize and resolve/explicitly account the target's integration/projection/
velocity/failure angular and energy changes, keeping material/timestep/topology
comparisons. Couple the actual bounded native hand and finite fixing response,
whole-step rollback and accepted time with the worker. Then wire normal named-object
tool targets and grip/history reconstruction through damage/save/restart, and
complete paid repair/replacement/use. R1 supply routes and R4–R6 remain unchanged.

Sources: [native preparation](../src/rigid/JoltWorld.cpp),
[immutable API](../src/rigid/JoltWorld.hpp),
[target transfer contract](../src/fastlattice/FastLattice.hpp),
[CPU target implementation](../src/fastlattice/CpuLatticeBackend.cpp),
[coupling adapter](../src/fastlattice/NativeFixedContact.cpp),
[measured tests](../tests/native_lattice_contact_tests.cpp).

## Publication

Implementation publication is pending the final fetch and ordinary main push.
This is an experimental integration checkpoint; player object destruction stays
open and preview binaries are unchanged. No production deployment is included.
