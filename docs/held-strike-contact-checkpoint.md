# Finite rigid contact and native reaction transfer — October 2, 2026

## Implemented boundary

`evaluatePointRigidContact` exchanges an instantaneous impulse between a
translational material point and a finite rigid body with its complete world
inertia tensor. The source retains material-derived mass, axial inertia and
spin; it is not converted into a point rod or an isotropic sphere. Normal and
Coulomb friction impulses include equal/opposite angular reaction. Inputs are
immutable; no pose, material, bond damage or artificial launch is assigned.

`JoltWorld::applyExternalPointContact` applies the accepted reaction to an
actual native body and the external point. It preflights the native float
velocities, speed limits and separate SI energy/linear/angular roundoff budgets
before either write. The receipt separates the double contact candidate from
actual native read-back and records numerical energy and momentum errors.
It does not relabel numerical residual as heat or correct velocities to hide it.

This is an integration primitive, **not ordinary tool/object destruction**.
Only its tests call it. The live fracture worker, held hand, finite fixing
constraints, target geometry search and player clicks are not connected.
R3 and the other four remaining player goals stay open. The running 8770
preview retains its previously qualified R2 binaries; no C ABI or UI changes.

## Law, units and limitations

The supplied unit normal points from rigid source toward point. The signed gap
is in metres and `dt_s` is a speculative-contact horizon, not an elapsed world
step. Both reaction impulses act at the point's centre. The target envelope has
no rotational contact DOF; its retained subcell spin is unchanged. Source inertia
includes intrinsic finite-volume inertia. This is a shared-centre point-contact
approximation, not exact voxel surface traction or a constitutive fracture model.

For arm `r`, source tensor `I`, point mass `m` and source mass `M`, the full
effective inverse mass maps direction `d` to
`D d = (1/m + 1/M) d + (I^-1 (r cross d)) cross r`.
A sticking impulse solves all three relative-velocity constraints and must fit
the static cone. Sliding satisfies the normal target and
`J_t = -mu_dynamic J_n * unit(final tangential slip)`, using the full tensor.
The bounded angular root solver uses up to 24 Newton attempts, then 64 angular
segments with up to 48 bracket splits; unresolved response refuses.

Outside the speculative horizon there is no attraction. Within a positive gap,
closing velocity may remain `-gap/dt`; at touching contact the restitution
target uses the declared coefficient above the 0.5 m/s threshold. Overlap does
not generate a positional impulse or kinetic energy. Restitution with friction
and an anisotropic effective mass can produce an energy-gaining candidate even
with coefficients in [0,1]. That combination explicitly refuses; no coefficient
is silently reduced. A future broader impact law must resolve this limitation.

Core tensors must be finite, symmetric within `1e-12` after scaling and positive
definite with scaled determinant above `1e-14`. The work audit permits
`1e-12 + 1e-10*(|K_before|+|K_after|+|impulse_work|)` J for arithmetic;
velocity constraints use `1e-10` of the relative-speed scale. These are new
primitive bounds; existing contact and constitutive tolerances are unchanged.

The native boundary symmetrizes world-tensor skew only within the existing
float-relative `1e-6` allowance and retains the raw tensor in measured accounts.
It requires explicit External ownership of the complete source/target proxy
pair. The caller must supply the target's **entire** contact response and avoid
advancing that proxy as a second physical target. Proxy motion is not updated by
this kick. Static/pinned/locked source motion, invalid ownership, speed limits,
bad inputs or exceeded roundoff budgets refuse before writes. Native reversible
and spring trials refuse because their recorder does not own the external point.
Active native joints are retained, but their later reactions and elapsed time
are not solved or qualified by an instantaneous kick.

## Matched measurements

Windows x64 / VS 2022, MSVC 19.44.35228.0 (MSBuild 17.14.51), Release CPU,
`BANJO_BUILD_LAB=OFF`, `build/agent-paid-machine`; baseline `e98c594` plus the
implementation revision recorded below. Catalog seed 17 throughout.

Target is one 40 mm material point, with mass `density*h^3`; declared contact
horizon `dt=1/240 s`, gap zero, normal (0,0,1). The same iron source box is
(0.4,0.08,0.06) m, mass 15.1104 kg, rotated 30 degrees about Y. Initial source
COM is (1,0.5,-0.5) m, velocity (-1,0.2,0.4) m/s, chosen spin (1,-2,0.3)
rad/s. Point offset is (0.12,0.03,0.02) m; relative velocity (3,0.5,-2) m/s.
Point spin (3,-1,2) rad/s is retained without contact torque. No gravity,
damping, bond solve or positional integration acts during the contact phase.
Geometry witnesses are supplied analytically; no authored-shape collision
admission is being qualified. Contact coefficients come from the retained
material compiler, not display-name branching.

| Target | Density kg/m³ | Point mass kg | Static/dynamic friction | Restitution | Normal impulse N s | Tangent impulse N s | Double contact loss J |
|---|---:|---:|---:|---:|---:|---:|---:|
| Glass | 2500 | 0.16 | 0.519615 / 0.396863 | 0.719532 | 0.533818 | 0.211852 | 0.651784015185 |
| Oak | 700 | 0.0448 | 0.609918 / 0.434741 | 0.465263 | 0.130158 | 0.0565849 | 0.205821650474 |
| Iron | 7870 | 0.50368 | 0.6 / 0.45 | 0.562774 | 1.43675 | 0.646537 | 2.1612750525 |

Double phase linear residual is at most 7.53408e-16 N s, angular residual
7.17046e-16 kg m²/s and work residual 2.66454e-15 J, bounded by 1e-12 in
these tests. Sliding takes three root evaluations per material. Densities
change the actual masses; catalog moduli 70/12/211 GPa are retained but no
stiffness response is solved here. These data do not qualify bending, fracture,
grain, plasticity, wear or calibrated joint strength.

The native counterpart reads the source's actual 15.1104008985 kg mass and
world tensor. Tests accept at most 1e-5 J, 1e-5 N s and 1e-5 kg m²/s
arithmetic residual per kick, with no correction. These are explicit new
fixture budgets, not changes to existing solver tolerances.

| Target | Native double-law loss J | Measured numerical energy J | Linear error N s | Angular error kg m²/s | Delivered normal-target error m/s |
|---|---:|---:|---:|---:|---:|
| Glass | 0.651784016156 | 1.13173897e-7 | 1.61939101e-7 | 5.73415878e-8 | -3.57644759e-9 |
| Oak | 0.205821650564 | -4.03287922e-7 | 4.73112112e-7 | 4.77684251e-7 | -1.04200086e-8 |
| Iron | 2.16127506203 | 5.66809364e-8 | 2.27927939e-7 | 2.59442507e-7 | -7.36441642e-9 |

Two successive contacts use the changed native source state without resetting
its pose or spin; their measured impulse/angular/energy receipts add correctly.
An overlapping proxy verifies that the subsequent native source step receives
no duplicate pair response. With damping/gravity off, accepted recoil drives
native position on the next `1/240 s` step. This does not integrate the external
target or qualify a synchronized deformable/native trajectory.

A separate finite oak rod (0.6,0.04,0.04) m has mass 0.672 kg and positive
axial inertia 0.0001792 kg m². A measured off-centre contact changes its chosen
axial spin from 2 to -9.14689439 rad/s while retaining phase momentum/energy
accounts. A collinear point rod would have omitted that inertia.

## Verification

Nine core named cases cover the elastic oracle, existing sphere limit, matched
materials, anisotropic sliding/sticking, finite rod, separation/overlap,
coordinate rotation/translation/boost, energy-gaining restitution refusal and
invalid inputs. Native tests cover matched read-back, actual float receipts,
overlapping pair ownership, subsequent motion, ordered contacts and transactional
refusal for each roundoff budget, ownership, pins/static motion, trials, speed
limits and malformed inputs. The static-source fixture initially failed during
setup because it declared initial motion; it was corrected to a stationary
static source. No physics acceptance tolerance was relaxed.

```powershell
cmake --build build/agent-paid-machine --config Release --target banjo_native_point_contact_tests banjo_point_rigid_contact_tests banjo_pair_impulse_tests banjo_contact_ownership_tests banjo_conservative_contact_tests banjo_tetrahedron_contact_impulse_tests --parallel 4
cmake --build build/agent-paid-machine --config Release --target banjo_lattice_external_load_tests banjo_fast_lattice_tests banjo_lattice_plasticity_tests banjo_ground_work_tests banjo_hand_stroke_tests --parallel 4
ctest --test-dir build/agent-paid-machine -C Release -R '^banjo_(native_point_contact|point_rigid_contact|pair_impulse|contact_ownership|conservative_contact|tetrahedron_contact_impulse|lattice_external_load|fast_lattice|lattice_plasticity|ground_work|hand_stroke)_tests$' --output-on-failure
python scripts/check-source-registration.py
git diff --check
```

All 11 affected CTest targets pass, 11.85 s total on this Windows run. The core
contact target takes 0.02 s and native contact target 0.03 s; these tiny-suite
wall times are not a game-scale performance claim. Source registration is
291/291. No graphical/normal-input test, production
deployment, macOS/Linux or cross-GPU qualification is claimed by this boundary.
The earlier bonded-load and whole-pipeline residuals remain open.

Sources: [double contact](../src/physics/PointRigidContact.cpp),
[public units/result](../src/physics/PointRigidContact.hpp),
[native transfer](../src/rigid/JoltWorld.cpp),
[core oracles](../tests/point_rigid_contact_tests.cpp),
[native measurements](../tests/native_point_contact_tests.cpp) and
[registered targets](../CMakeLists.txt).

## Next integration

Supply native shape witnesses for all relevant target points with one pair
owner; preserve the held fixed assembly and actual constraint load paths.
Advance hand/controller, native fixings and target fracture on the same accepted
clock, including hand/joint work and all source reactions. Remap surviving grips
after damage. Then enable ordinary object-target tool input and qualify matched
glass/oak/iron repeated strikes, separate players, detached heads, failed saves,
restart and the paid damaged-tool reuse journey. Exact rigid internal fracture
remains unsupported; manufactured lattice geometry is not exempt from damage.

## Publication

Pending the final regression and ordinary fast-forward publication to main.
