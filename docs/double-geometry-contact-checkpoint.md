# CPU pose geometry and paired contact accuracy — October 7, 2026

## Implementation and physical ownership

Experimental CPU reference from main `d38bc3889d60c3d3f9223058608d31dd18c91150`,
Windows x64 / MSVC Release, default Jolt rotation. This connects the
[double source](double-rigid-source-checkpoint.md) to actual native geometry at
its current poses and adds full/two-half-step accuracy control. The
[complete live world objective](world-physics-action-plan.md) remains active.
These changes are not installed in the running browser world.

`JoltWorld::bindMaterialShape` captures native world/body/shape/material identity
and actual mass, inertia and motion. `materialShapeContactsAtPose` uses that
actual shape at a supplied **center of mass** and unit orientation. It shares
the existing GJK/EPA and supporting-face clipping implementation, per-leaf
material lookup, void preservation and total witness budget. No source pose,
velocity or native clock is written. Geometry is queried anew at every contact
phase, not copied from an earlier trajectory or cached fracture outcome.

The native body must remain unchanged during this geometry binding: stepping,
native trial restore, replacement, reshape or mass/inertia/motion changes
invalidate it. Empty/foreign bindings, nonfinite/nonunit poses, excessive local
range and witness overflow refuse the complete query. This is a serial host
API between steps, not concurrent native mutation support. Constraints, pending
forces, damping and joint configuration are not imported by a shape binding.
It does not transfer custody or qualify native-to-CPU dynamics handoff.

The externally supplied COM stays double. Source COM minus envelope COM is
computed before conversion to the native relative collision frame. Native
rotation, shape dimensions and GJK/EPA still use float precision. Returned
metadata identifies the external pose, actual float query rotation and relative
offset rounding. This is **not double collision geometry** or swept discovery.

`advanceDoubleFixedTargetControlled` runs restored full and two-half trials from
the same actual source/material state. The accepted result commits two half
steps only if surviving bond topology/failure modes agree exactly and all shared
SI comparisons are <= 1. Bounded refinement or any exception restores both
states, histories, loads and clocks. Its internal owned step shares the existing
force-boundary integrator; it does not nest material trials.

`ContactAccuracy.hpp` extracts existing native state/ledger comparisons instead
of introducing a second set of material checks. Native default composition and
bounds are retained. Shared default bounds: position 10 nm, velocity/angular
velocity 1e-4 SI, orientation 1e-5 rad, damage/history/plastic strain 1e-5,
plastic extension 10 nm, energy 1 microjoule, impulse 1 micro-newton-second and
angular impulse 1e-7 kg m²/s; minimum substep 1 ps. CPU comparisons also retain
world spin momentum, actual external source work/impulses, free-drift numerical
transfers and per-fixing reactions. No strength or constitutive law changes.

## Clock defect found and repaired

The first six sustained CPU runs stopped after 183–370 accepted intervals at
5.05–7.9625 microseconds: the source's ordinary elapsed-time summation diverged
from the material backend's compensated sum. The existing absolute-clock
agreement bound correctly refused continued stepping.

The source now uses the same compensated accepted-clock arithmetic. Dynamics
still use the requested physical dt; the summation correction is not a force,
energy correction or altered integration interval. Copy/rollback retains the
clock compensation. A 1,024-variable-interval regression (2,048 accepted half
steps) checks exact paired clock agreement and total elapsed duration. The
clock bound is unchanged. All six final cases reach their explicit 500 and
2,000 interval limits without the prior clock refusal.

An initial mixed-material compound geometry test also failed because its
fixture treated the geometric midpoint as the mass center. The test now uses
the material-derived COM to locate the void and leaves; no geometry tolerance
was enlarged.

## Matched evidence and retained failures

[Machine-readable rows, before/after clocks and source/executable fingerprints](evidence/material-lab/double-geometry-contact-results-20261007.json).

Same conditions as the sustained force-boundary comparison: 40 mm cells,
120 mm target cube, 27 nodes and nine far-face clamps; 80 mm iron tool head with
40/120 mm widths and a 240 x 40 x 40 mm laboratory oak handle; initial source
velocity (6, 0.2, 0.1) m/s, zero gravity/damping, proposed interval 100 ns.
Every phase queries the actual moved/rotated head and checks that the handle
and clamps are not omitted from the contact fixture.

CPU member mass/inertia come from actual accepted native states. Native shapes
are retained as an unstepped geometry library. The CPU fixing is a declared
ideal rigid connection with exactly coincident anchors, not a snapped/imported
native joint. This changes the dynamics reference from native constraints and
float velocities; comparisons below do not certify a representation transition.

Targets retain glass 2500 kg/m³ / 70 GPa, oak 700 / 12 GPa, iron 7870 / 211 GPa.
Target masses are 4.32 / 1.2096 / 13.59936 kg. Narrow/broad actual source masses
are 2.2835199755 / 6.3129599429 kg. Oak remains an uncalibrated isotropic axial
lattice laboratory comparison, not gameplay wood or grain realism. The existing
strength surface and declared axial plastic flow are retained; no general
metal plasticity, fatigue or calibrated fracture claim is added.

| Target | Head width | Time after 500 intervals | Time after 2,000 | 2,000-run wall time | Broken bonds |
|---|---:|---:|---:|---:|---:|
| Glass | 40 mm | 6.794531 µs | 9.138281 µs | 3.25 s | 0 |
| Oak | 40 mm | 8.775 µs | 16.0125 µs | 2.65 s | 0 |
| Iron | 40 mm | 7.754492 µs | 10.098242 µs | 4.17 s | 0 |
| Glass | 120 mm | 6.328125 µs | 8.671875 µs | 44.49 s | 0 |
| Oak | 120 mm | 8.65625 µs | 14.509375 µs | 58.47 s | 0 |
| Iron | 120 mm | 6.480859 µs | 8.824609 µs | 55.78 s | 0 |

Required duration remains **204.8 microseconds with actual fracture**. All six
cases fail that acceptance gate by exhausting the explicit diagnostic interval
limit. The diagnostic returns exit 1, records zero broken bonds and does not
declare a shorter-duration success. It does not relax work/state/topology bounds.
The old native broad-iron 13.4059-microjoule captured discrepancy has **not** been
replayed through an audited native-to-CPU transition and its gate stays open.

Across the 2,000-interval runs, largest attributed whole-system energy/linear/
angular residuals are 2.22e-11 J / 1.02e-13 N s / 1.89e-16 kg m²/s, within the
retained 1e-10 J / 1e-9 SI attribution bounds. Accounts include source drift and
contact roundoff, target integration/bond corrections, fixed-support reactions,
external transfers and contact/material losses. Mass is retained. This is full
pipeline attribution, not proof that numerical energy is physical or that local
accuracy guarantees calibrated fracture. Performance is far from gameplay.

The last accepted comparisons are limited by contact work/dissipation rather
than the removed native source-velocity rounding refusal. The six accepted
normalized errors range 0.159–0.524. More accepted steps alone are not a speed
repair; the next integrator work must improve physically attributed accuracy.

## Verification and next gate

Registered `banjo_double_geometry_contact_tests` tests actual current-pose
source/material coupling, six full/fine phase exception positions, unchanged
clocks/history on refusal, exact committed half steps, loaded fixing/work
receipts and long variable clocks. Expanded native point tests cover matched
glass/oak/iron rotated and distant poses, same-pose witness equality, compound
voids/per-leaf materials, malformed/foreign/stale bindings and no native writes.
Sixteen rebuilt scoped CTest entries pass in 52.71 s, including native/material
contact, source, cohesive/Creator, outcome, Verlet, external loads and
constituent/patch coverage. Exact results are recorded in the evidence file. Source
registration is **320/320** across 31 CMake files, with zero exclusions.
This is scoped Windows headless verification, not full regression, physical
phone testing, a new interactive/render loop or browser fracture qualification.

Next:

1. Retain these actual-pose queries and shared audits while repairing sustained
   contact/material time integration. Measure refinement of contact work,
   dissipation and state, and improve broad-patch solve cost without changing
   physical laws or increasing bounds. Finish all six 204.8-µs fracture gates.
2. Audit native-to-CPU mass/tensor/anchor/constraint transition and replay the
   captured source failure; no silent anchor snapping or tensor projection.
3. Wire qualified contact, fracture and persistent constituent debris to
   ordinary held-tool actions in the same live 3D world. Useful digging remains
   required, followed by deformation/structures/mechanisms and water/heat/
   energy/pressure. No outcome playback satisfies that goal.

```powershell
cmake --build build/local-cell-tools --config Release --parallel 4 --target banjo_double_geometry_contact_tests banjo_native_point_contact_tests
ctest --test-dir build/local-cell-tools -C Release -R '^banjo_(double_geometry_contact_tests|native_point_contact_tests)$' --output-on-failure
./build/local-cell-tools/Release/banjo_double_geometry_contact_tests.exe --sustained 2000
python scripts/check-source-registration.py
```

The sustained command intentionally exits 1 while those gates are open.
Raw logs stay ignored in `build/material-lab/double-geometry-*.log`; secrets and
local binaries are not committed. Publication revision is recorded in Git and
the checkpoint report. Running demos and saved player worlds are unchanged.
