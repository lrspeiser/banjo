# Constrained fixed-assembly point contact — October 2, 2026

## Implemented and measured boundary

`evaluatePointFixedAssemblyContact` couples one translational material point
to a finite assembly through its fixed velocity constraints during contact.
`JoltWorld::applyExternalFixedPointContact` reads the complete source tree,
each constituent's actual mass/world inertia/motion, and each ordinary native
fixing's two attachment points. It transfers the accepted impulses into every
member with measured float errors. The handle reacts in this contact phase.

This extends the [native shape/contact boundary](held-strike-shape-checkpoint.md).
The earlier single-head contact followed by a native fixing step remains a
separate regression; it is not reinterpreted as simultaneous constrained contact.

**Only tests call the new boundary. Ordinary held-tool destruction is still
unimplemented.** No LiveWorld, browser, C ABI, LLM authoring contract, running
preview or production deployment changes are included. R3 and the five
remaining player goals stay open.

## Model, units and limits

The CPU reference admits 1..256 finite dynamic bodies and exactly N−1 links
forming a tree. Each ideal six-DOF fixed link equates angular velocities and
its two attachment-point velocities. Cyclic graphs, invalid indices, bad
mass/tensors, overflow and unsupported passive contact candidates refuse.
No position/orientation correction, strength/failure, hand force or time
integration occurs here. No-contact results retain the original source states.

For a link from parent p to child c, its kinematic offsets satisfy
`s_c = s_p + (P_p−C_p) − (P_c−C_c)`, where P are actual attachment positions
and C are physical centres. Mass-centred offsets `r_i = s_i − sum(m*s)/M`
yield `I_eff = sum(I_i + m_i*(|r_i|²*Id−r_i*r_iᵀ))`. The contact uses this
full tensor, including each body's intrinsic/axial inertia. The reduced frame
is not a new physical body or geometry; physical poses and masses are retained.

Existing incompatible source velocities are reconciled by the ideal constraint
impulses. Their measured kinetic loss has a separate receipt. Normal restitution
and Coulomb friction operate on that compatible state using the unchanged
[finite point/rigid contact law](held-strike-contact-checkpoint.md). Physical
source velocities are reconstructed from the impulse solution once per accepted
contact. No launch velocity, damage counter, shard or motion animation is added.

Each fixing reports impulse on its authored B endpoint in N s, free angular
impulse in kg m²/s, and signed impulse work in joules. Reconciliation and contact
receipts are separate. Compatible ideal fixing contact work is zero; reconciliation
work equals negative measured reconciliation loss. Noncoincident anchors retain
their actual `sum((P_b−P_a)×J_b)` couple in the angular ledger; they are not
silently moved or merged. Double work bounds retain `1e−12 + 1e−10*energy_scale`.
The shared SPD tensor inverse preserves the previous conditioning tolerances.

Native admission requires every source member to be unpinned, unrestricted and
dynamic, with External ownership of its proxy pair and of joined seams. Ordinary
two-way enabled fixings only; springs, other joint kinds, one-way/disabled links,
loops, target membership, excess capacity and native trials refuse. The external
point is not part of the native trial recorder. All members, float speeds and SI
roundoff budgets are checked before any member or point is written. The native
world tensor's small skew is symmetrized only for solving under the existing
1e−6 relative bound; raw tensors remain in measured native accounts.

**External joint receipts do not rewrite Jolt's cached constraint lambda.** The
caller must combine them with subsequent native loads on one accepted clock and
implement strength/failure handling before gameplay use. A finite declared fixing
strength is not enforced by this instantaneous ideal contact primitive.

## Matched experiment

Windows x64, VS 2022 / MSVC 19.44.35228.0 / MSBuild 17.14.51, Release CPU,
`BANJO_BUILD_LAB=OFF`, `build/agent-paid-machine`; baseline `b3721ef` plus the
implementation revision recorded below. Material catalog seed 17 is retained.

Each head is an 80 mm cube, with a 240×40×40 mm oak handle centred at
(-0.16,0,0) m and an ordinary fixing at (-0.04,0,0) m. The source starts at
(2,0,0) m/s with zero spin. A stationary 40 mm oak point (0.0448 kg) has a
16 mm contact envelope centred at (0.055,0.01,0) m. The actual head surface
supplies a +X normal and approximately −1 mm gap; horizon is 1/240 s.
The normal/native free-step fixture retains declared 5000 N axial/shear limits,
zero damping and zero gravity. Catalog contact friction/restitution are used.

Head densities are glass 2500, oak 700 and iron 7870 kg/m³. Authored head masses
are 1.28/0.3584/4.02944 kg; the handle is 0.2688 kg. Native float mass/tensor
read-back is retained rather than replaced by those exact authored values.
Catalog stiffness remains 70/12/211 GPa; stiffness and bonds do not participate
in this instantaneous contact model. No brittle-oak, grain/plasticity, calibrated
fracture or material-realism claim follows from these contact measurements.

| Native phase | Glass head | Oak head | Iron head |
|---|---:|---:|---:|
| Normal impulse, N s | 0.130634878142 | 0.122007775801 | 0.129886346136 |
| Fixing contact impulse magnitude, N s | 0.0233169796081 | 0.0525475340368 | 0.00918587291612 |
| Contact kinetic loss, J | 0.0651993091792 | 0.0658928206197 | 0.0694550017407 |
| Reconciliation loss, J | 0 | 0 | 0 |
| Signed native numerical energy, J | 1.46717060695e−7 | −3.48702743624e−8 | 1.16654410964e−7 |
| Linear momentum error magnitude, N s | 7.65876990541e−8 | 1.93164644028e−8 | 5.92222289914e−8 |
| Angular error after measured anchor couple, kg m²/s | 1.33101682887e−11 | 2.86379485664e−11 | 7.49501047163e−13 |

Native transfer budgets are each 1e−5 in their corresponding SI units, unchanged
from the earlier finite contact fixture. Core matched work residual is at most
3.33067e−16 J, linear at most 4.44093e−16 N s and angular at most 2.16841e−19
kg m²/s. Numerical errors remain signed measurements, separate from physical loss.

One subsequent free native fixed step retains momentum within 1e−5 SI and has
unallocated kinetic changes 0/0/1.04627417841e−12 J. That limited free step does
not establish a held trajectory, warm-start behavior under repeated loaded steps
or full-pipeline conservation. The older loaded sequential experiment's much
larger unallocated energy remains recorded in its checkpoint.

## Verification and next work

Six core cases cover single-body reduction, an independent elastic normal
effective-inertia oracle, glass/oak/iron contact, a known 1 J axial reconciliation
loss, noncoincident-anchor couple without pose correction, a branched source,
member/link permutations and rotations/boosts/translations, invalid graph/mass/
tensor/no-contact preservation, and the 256-member limit with overflow refusal.
Native cases read rotated attachment witnesses, verify actual immediate handle
reaction and constituent mass/pose preservation, and audit two ordered contacts'
cumulative momentum, angular/couple and kinetic/work accounts without resetting
source motion. Inadequate budgets, ownership/seams, pins/static bodies, one-way
fixings, distance springs, loops, speed limits and trials refuse atomically.

All 12 affected compiled CTest targets pass in 12.20 s: fixed assembly contact,
point rigid/native point contact, pair impulse, contact ownership, conservative
and tetrahedron contact, external lattice loads, fast lattice, lattice plasticity,
ground work and hand stroke. `python scripts/check-source-registration.py` passes
293/293, no deliberate exclusions; `git diff --check` passes. Local logs are under
ignored `build/resource-flow/fixed-contact-*.log` / `fixed-native-results.log`.
No earlier physics tolerance or material law changed. No graphical/normal-input,
cross-platform or GPU qualification is claimed for this test-only boundary.

Next couple the CPU target integration and actual native hand/source evolution
on the same accepted substep clock, retaining contact loss, joint impulses,
constraint/numerical accounts and hand work. Then connect named-object tool
targeting, fracture/history and grip remapping through damage/save/restart,
followed by the full R3 paid repair/replacement/use acceptance. Exact rigid
objects without an internal fracture law remain an explicit unsupported case.

Sources: [CPU fixed contact](../src/physics/FixedAssemblyContact.cpp),
[unit-bearing model](../src/physics/FixedAssemblyContact.hpp),
[native transfer](../src/rigid/JoltWorld.cpp),
[native API](../src/rigid/JoltWorld.hpp),
[analytical/core tests](../tests/fixed_assembly_contact_tests.cpp),
[native tests](../tests/native_point_contact_tests.cpp).

## Publication

Implementation `1a713a56487a04c8d4557506f7f939ece0dd85ce` is published on
GitHub main by an ordinary fast-forward push. The recorded tests were compiled
from those exact implementation sources; this following publication record
changes only documentation. Preview 8770 remains HTTP 200 with unchanged R2
`banjo_live_world_run.exe` and `banjo.dll` hashes. No deployment is included.
Ordinary held-tool object destruction and the five remaining player goals are
still open; this publication qualifies only the constrained contact phase.
