# Why glass did not shatter: measured mechanism in the voxel/bond lane

Worktree `banjo-agents/glass`, branch `agent/glass`, developed from `fbd8108`.
Windows 11, MSVC (Visual Studio 17 2022), Release, `-DBANJO_BUILD_LAB=OFF`,
build directory `build/agent`. Every number below is a measurement from a run in
that build. This document records **solver defects and their correction**. It
does **not** claim calibrated glass fracture, and it does not establish a
converged fragment count.

## Summary

The docs said glass "remains stopped at the energy-preserving fracture/contact
handoff". That describes the cohesive tetrahedral reference lane
(`banjo_cohesive_sphere_probe`), and it is still true there. It is not what
happens in the voxel/bond lane that `README.md` presents as the completed
transition and that `banjo_headless` exercises. That lane does not stop. It
produced 1280 "pieces", and every one of them was a numerical artifact.

Three separate defects were measured and corrected:

1. **The support plane, not the impact, broke every bond.** The post-solve
   position projection in `applySupportContact` teleported penetrating nodes out
   of the plane one at a time, outside the constraint solve, and
   `accumulateResolvedStrains` then read that displacement back as physical
   strain. Measured injection: **+1.754279e7 J** into a system whose entire
   mechanical energy is 2.475e4 J.
2. **Glass could not fail from its own declared strength.** The catalogue gives
   soda-lime glass 45 MPa tensile strength (failure strain 6.43e-4) and then
   multiplied the compiled failure strain by 8 and 16, putting bond failure at
   360-720 MPa. With the support artifact removed, the 8 m/s iron impact produced
   **zero** broken bonds.
3. **The failure criterion was direction-blind.** Each bond inherited the
   *maximum principal* strain of its endpoint nodes, so a bond perpendicular to a
   uniaxial tension failed on strain it does not carry, and every bond touching a
   highly strained node failed in the same step. The model could detach points,
   never form a crack surface.

And one defect was measured but **not** corrected:

4. **The second sphere/material contact pass is now the dominant energy source.**
   In a free-flight 8 m/s impact it injects **+81,840 J** cumulatively (largest
   single tick +15,801 J) into a 2.3e4 J system.

## Evidence 1: the shipped run is dust, not fragments

`banjo_headless` at `fbd8108`, defaults (0.25 m glass ball, 0.04 m voxels,
horizon 2, iron striker at 8 m/s, concrete support, material step 1/240 s,
1 substep, 8 constraint iterations):

```
glass nodes: 1285      intact bonds: 17097      mass: 163.6089 kg
Impact: speed=7.9859 m/s, energy=3959.3743 J
Fracture: broken bonds=17086, components=1280
Handoff: rigid fragments=64, debris particles=1216
Unassigned bond-removal energy=1.512032e+07 J
```

17086 of 17097 bonds fail. 1280 components from 1285 nodes means 1272 of them are
single voxels; the largest surviving component contains **3** nodes. The deleted
bond energy is 3818x the impact energy. Total system mechanical energy at t = 0 is
kinetic 2.308e4 J plus gravitational 1.671e3 J.

The per-stage ledger from `--audit-csv` names the source:

| Stage | cumulative delta-E (J) | cumulative delta-L (kg m^2/s) |
|---|---:|---:|
| gravity | +4.096530e+02 | 3.447232e+03 |
| pre_contact | -5.523203e+02 | 4.6e-13 |
| prediction | +1.680439e+08 | 7.2e-13 |
| constraints | -1.722819e+08 | 5.865710e+00 |
| damping | -1.171567e-02 | 2.3e-12 |
| post_contact | +1.804716e+06 | 7.534552e-01 |
| **support** | **+1.754279e+07** | **4.034275e+03** |
| damage | -1.512032e+07 | 0 |

## Evidence 2: turn the support off and the fracture disappears

Same experiment, same striker, `banjo_glass_diagnostic`, material step 1/240 s,
original code:

| support plane | gravity | broken bonds | components |
|---|---|---:|---:|
| on | on | 17090 / 17097 | 1278 |
| on | off | 7453 / 17097 | 502 |
| **off** | on | **0** | **1** |
| **off** | off | **0** | **1** |

A 515 kg iron ball at 8 m/s broke not one bond. Every fragment in the shipped
proof came from the floor projection.

## Evidence 3: the artifact is a timestep artifact and it converges to zero

The projection depth per substep is approach speed times substep, and the
artificial bond stretch it creates is that depth divided by the shortest bond
(0.04 m). That predicts damage whenever

```
v * dt / L  >  damage_end_stretch    ->    dt > 1.0286e-2 * 0.04 / 8 = 51 us
```

Measured with the material step held at 1/240 s and only the substep count
varying (original code):

| substeps | substep dt | broken bonds | components |
|---:|---:|---:|---:|
| 1 | 4167 us | 13599 | 951 |
| 8 | 521 us | 709 | 42 |
| 32 | 130 us | 75 | 5 |
| 128 | **32.6 us** | **0** | **1** |
| 256 | 16.3 us | **0** | **1** |

The predicted 51 us threshold sits exactly between the last resolution that
fractures (130 us) and the first that does not (32.6 us).

A material-step refinement at 1 substep behaves the same way and shows the
fragment population (handoff windows held at fixed physical durations, original
code):

| material dt (s) | broken | components | largest (nodes) | singletons | components >= 8 nodes | removal (J) |
|---:|---:|---:|---:|---:|---:|---:|
| 4.167e-3 | 17090 | 1278 | 3 | 1272 | 0 | 1.51e7 |
| 2.083e-3 | 16197 | 1170 | 109 | 1163 | 1 | 8.51e6 |
| 1.042e-3 | 5059 | 331 | 954 | 329 | 1 | 2.07e6 |
| 5.208e-4 | 6272 | 404 | 879 | 400 | 1 | 1.60e6 |
| 2.604e-4 | 3412 | 214 | 1069 | 208 | 1 | 7.33e5 |
| 1.302e-4 | 1168 | 73 | 1213 | 72 | 1 | 2.34e5 |

The component count is monotone in the timestep and converges toward one intact
ball, not toward a fragment population. Note also that there is never more than
**one** component with eight or more voxels at any resolution: the model erodes
surface points and does not split.

## Evidence 4: the impact does exceed glass strength

With the support plane off and no gravity (free-floating target, 8 m/s iron
striker, original code), the resolved elastic response peaks at bond stretch
**3.33e-3** and then rings down elastically. Against the thresholds:

| quantity | value | source |
|---|---:|---|
| declared tensile strength | 45 MPa | `MaterialCatalog.cpp`, soda-lime glass |
| declared Young modulus | 70 GPa | same |
| physical failure strain | 6.43e-4 | 45e6 / 70e9 |
| compiled damage onset (was) | 5.14e-3 | physical x `damage_strain_multiplier` 8 |
| compiled complete break (was) | 1.029e-2 | physical x `break_strain_multiplier` 16 |
| measured peak bond stretch | 3.33e-3 | this experiment |

The impact exceeds the catalogue's own failure strain by 5.2x and the compiled
model recorded zero damage. The shared `SolverCalibration` defaults are 1.0 and
2.0; iron, aluminium, oak and rubber use them. Glass, ceramic, ice and concrete
carried inflations of 8/16, 5/10 and 6/12. **Glass has been returned to the
shared defaults.** Ceramic, ice and concrete were left alone because nothing
here measured them; that inconsistency remains open and is called out below.

## Evidence 5: the runtime is 2819x above its own resolution limit

`measureLatticeResolutionLimit` (new, in `matter/Lattice.hpp`) computes, per node,
`omega = sqrt(sum of incident bond stiffness / node mass)` and reports the
largest. `banjo_headless` now prints it next to the configured step:

```
fastest lattice mode: 4.6435e-06 s; explicit substep limit: 1.4781e-06 s;
configured material substep: 4.1667e-03 s (ratio 2.8190e+03)
```

XPBD's position solve is not conditionally stable, so exceeding this does not
diverge; it means the lattice cannot carry its own elastic wave, so any strain the
damage law reads is a discretization result. The physically relevant target is
the voxel wave transit `h/c = 0.04 / sqrt(70e9/2500) = 7.56 us`, which needs
about 551 substeps per 1/240 s material step. **No run in this study reaches
either limit.** The finest resolution measured here (256 substeps, 16.3 us) is
still 11x above the explicit limit and 2.2x above the CFL transit. That is the
single most important fact about every fragment count below.

## What was changed

1. **Support non-penetration is solved inside the constraint sweep**
   (`BrittleSolverSettings::support_in_constraint_solve`, default true).
   `projectSupportPosition` runs after each bond sweep so the correction is
   redistributed through the lattice by the following iterations;
   `applySupportVelocity` then replaces the normal velocity implied by the
   projection with the restitution target measured from the approach velocity, so
   the projection cannot act as an energy source, and Coulomb friction is charged
   against the actual normal velocity change. The legacy path is preserved behind
   the flag and is still pinned by a test.
2. **Glass failure strain follows the declared strengths.** The 8x/16x
   multipliers were removed from soda-lime glass in `MaterialCatalog.cpp`.
3. **The bond failure criterion is resolved along the bond.** The nonlocal node
   strain is retained as the full Green-Lagrange tensor; each bond is judged by
   `n^T E n` (normal) and by the transverse part of `E n` (shear) for its own
   reference direction, instead of by the node's maximum principal value.
4. **The lattice reports its own resolution limit** (`measureLatticeResolutionLimit`,
   surfaced through `ExperimentStats::target_resolution_limit` and printed by
   `banjo_headless` and `banjo_glass_diagnostic`).

Supporting, non-behavioural: `tools/glass_shatter_diagnostic.cpp` (target
`banjo_glass_diagnostic`); `ExperimentSettings::material_substeps` and
`material_constraint_iterations`, defaulting to the values the runtime already
used (1 and 8), so resolution can be varied without changing the law.

## Measured effect

`banjo_headless`, unchanged defaults, before and after:

| quantity | before | after |
|---|---:|---:|
| broken bonds | 17086 / 17097 | 16932 / 17097 |
| connected components | 1280 | 1124 |
| largest component | 3 nodes | 8 nodes |
| unassigned bond-removal energy | 1.512032e+07 J | 1.893809e+05 J |
| coarsening elastic loss | 4.941828e+00 J | 1.030247e-02 J |
| handoff audit delta-E | -4.943370e+00 J | -2.493747e-01 J |
| support-stage energy per tick | ~ +7e5 J | -4 to -34 J |
| mass error | -3.7e-12 kg | -3.5e-12 kg |

Phantom energy is down 80x and the support stage now removes energy through
friction and restitution instead of injecting it. The shipped material step is
unchanged and is still 2819x the resolution limit, so its fragment count remains
a resolution artifact.

With all corrections and increasing substeps (iron striker, 8 m/s, concrete
support, gravity on):

| substeps | broken | components | largest (nodes) | singletons | >= 8 nodes | removal (J) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 16932 | 1124 | 8 | 1016 | 1 | 1.89e5 |
| 8 | 16834 | 1038 | 10 | 907 | **4** | 6.95e4 |
| 32 | 7795 | 401 | 814 | 353 | 1 | 3.38e4 |

Multi-voxel fragments appear for the first time (four components of eight or
more voxels at 8 substeps), and the fracture is now driven by the impact rather
than the floor: the free-flight control that previously produced zero broken
bonds now produces 8567 broken bonds and 466 components at 8 substeps.

## Material comparison

Identical scenario for every row: 0.25 m target sphere, 0.04 m voxels, horizon 2,
iron striker at 8 m/s, concrete support at 0 degrees, gravity 9.81 m/s^2, material
step 1/240 s with 32 substeps and 8 constraint iterations, handoff windows
0.75 / 0.25 / 2.0 s.

| target | model | declared sigma_t / E | compiled damage onset | impact (J) | broken bonds | components | largest (nodes) | removal (J) |
|---|---|---|---:|---:|---:|---:|---:|---:|
| **glass** | BrittleBond | 45 MPa / 70 GPa | 6.43e-4 | 3959 | 7795 / 17097 | **401** | 814 | 3.38e4 |
| **oak** | RigidOnly | 90 MPa / 12 GPa | none | 1341 | 0 / 0 | — | — | 0 |
| **iron** | RigidOnly | 250 MPa / 211 GPa | none | 8211 | 0 / 0 | — | — | 0 |
| alumina ceramic | BrittleBond | 300 MPa / 300 GPa | 5.00e-3 | 5442 | 40 / 17097 | **2** | 1283 | 8.99e4 |

Read honestly:

- **Oak and iron have no fracture path in this lane at all.** Both are declared
  `MaterialModel::RigidOnly`, so the same experiment compiles no lattice, no
  bonds and no components for them, and the material phase is never entered. They
  can be compared as strikers and supports but not as fracturing targets. Turning
  them into brittle presets to obtain a comparison is forbidden and was not done.
  This is the honest state of the comparison, not a passing result.
- Glass and alumina ceramic are a real property-driven contrast: ceramic receives
  a **larger** impact (5442 J vs 3959 J, it is denser) and still breaks 40 bonds
  into 2 components where glass breaks 7795 into 401. But only part of that gap
  is the declared strength. Ceramic's physical failure strain is 1.00e-3 against
  glass's 6.43e-4 (a factor 1.56), while its compiled onset is 5.00e-3 against
  6.43e-4 (a factor 7.78) because ceramic still carries a 5x multiplier. The
  comparison is therefore **not** on equal footing and should not be quoted as
  evidence that the strength law alone separates the two materials.
- Ceramic's removal energy (8.99e4 J) is larger than glass's despite 195x fewer
  broken bonds, because its bonds are stiffer and its threshold higher, so each
  break deletes far more stored energy. This is the same open ledger defect.

### Same glass target, different striker material

This is the cleaner of the two comparisons, because the fracturing material is
held fixed and only the striker's declared properties change. Identical 8 m/s
release speed, identical geometry, identical 32-substep resolution:

| striker | declared density | impact (J) | broken bonds | components | largest (nodes) | >= 8 nodes | removal (J) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **iron** | 7870 kg/m^3 | 3959 | 7795 / 17097 | **401** | 814 | 1 | 3.38e4 |
| **oak** | 700 kg/m^3 | 1139 | 2573 / 17097 | **102** | 1156 | 2 | 8.49e3 |

The 11x denser iron striker delivers 3.5x the impact energy and leaves the glass
in 4x as many components with a core less than three quarters the size. Nothing
but the striker's declared density and contact properties differs. This is a
property-driven fragmentation difference between iron and oak on the same glass,
under the same declared conditions, and it is the strongest comparative evidence
in this checkpoint. It is still not calibrated, and it is still measured at a
resolution 88x above the lattice limit.

## Impact-speed response

Glass target, 8 substeps, otherwise identical:

| striker speed | impact (J) | broken | components | largest | >= 8 nodes | removal (J) |
|---:|---:|---:|---:|---:|---:|---:|
| 2 m/s | 234 | 16742 | 960 | 15 | 6 | 5.01e4 |
| 4 m/s | 979 | 16806 | 1009 | 25 | 3 | 6.48e4 |
| 8 m/s | 3959 | 16834 | 1038 | 10 | 4 | 6.95e4 |
| 16 m/s | 15880 | 16789 | 995 | 9 | 3 | 7.14e4 |

**There is almost no dose response**, and this is a negative result that must not
be papered over. A 68x change in impact energy changes the broken-bond count by
0.5 %. At this resolution the lattice is saturated: once the first bonds fail the
under-resolved solve carries the damage front through the whole ball regardless of
how hard it was hit. Nothing here should be quoted as calibrated glass behaviour.

## Where the remaining energy comes from

Cumulative stage sums for a free-flight 8 m/s impact (no support, no gravity), 8
substeps, all corrections applied, over 105 ticks:

| stage | cumulative (J) | largest single tick (J) |
|---|---:|---:|
| prediction | +812,482 | +401,616 |
| constraints | -848,417 | -406,844 |
| **post_contact (sphere/material)** | **+81,840** | **+15,801** |
| support | 0 | 0 |
| damage (bond removal) | -50,378 | -10,572 |

The predictor/corrector pair is a net **sink** of -35,935 J. After the support
fix, the dominant remaining energy **source** is the second sphere/material
contact pass, `solveSphereMaterialContacts(..., true)`, which injects 81.8 kJ
into a system whose total mechanical energy is about 23 kJ. That is the next
thing to fix in this lane, and it was not fixed here.

## What still does not work

- **No converged fragment count.** Component counts remain monotone in the
  timestep and no run in this study is resolved. Nothing here establishes how
  many pieces a glass ball should break into.
- **No dose response.** See the speed table above.
- **The energy ledger is still open by more than an order of magnitude**, now
  dominated by the sphere/material contact post-pass.
- **The lattice is stiffer than the material it claims to represent.** With
  horizon 2 each node carries 16 bonds in the positive half-set, and an affine
  uniaxial stretch stores `0.861 E eps^2` per unit volume against `0.5 E eps^2`
  for the declared modulus: about 1.7x too stiff. Nothing corrects this.
- **Fracture is strength-based, not energy-based.** There is no `Gc` calibration.
  At a 40 mm voxel the bond-based peridynamic critical stretch matching glass's
  8 J/m^2 fracture energy is `sqrt(4 pi Gc / (9 E delta))` = 4.5e-5, fourteen
  times smaller than the strength-based 6.43e-4. The two criteria disagree by
  more than an order of magnitude at this discretization and neither is validated
  against laboratory glass data.
- **Ceramic, ice and concrete still carry failure-strain multipliers** of 5/10,
  6/12 and 6/12 while glass, iron, aluminium, oak and rubber use 1/2. That is a
  catalogue inconsistency; it was not changed because no experiment here measures
  those materials.
- **Oak and iron cannot fracture at all** in this lane (RigidOnly).
- **The cohesive tetrahedral lane is unchanged** and still stops where the
  previous checkpoints said; see below.

## The other lane: the cohesive tetrahedral reference

`banjo_cohesive_sphere_probe`, unchanged by this work, measured at `fbd8108`:

| run | status | accepted time | stop |
|---|---|---:|---|
| `--corotated`, 1 m/s | solver limit | 0.320469 ms | Severed interface retains compression energy; contact handoff required (facet 5, 3.99315e-5 J) |
| `--corotated-contact`, 1 m/s | solver limit | 0.433575 ms | Fragment contact required: disconnected material interpenetrates |

The `finite_facet_closure_contact` path added in `06ad38b` does clear the first
rejection: it reaches 1 fully separated facet and 2 newly exposed faces with a
5.2578e-5 m maximum closure compression and 14 projection queries, before hitting
the next wall. **The documented blocker has therefore already moved one step**:
it is no longer "a severed interface still behaves as a spring in compression",
it is now "two disconnected components overlap and there is no fragment-fragment
contact response". The `docs/finite-rotation-parallel-checkpoint.md` description
predates that commit. Both 0.03 m/s controls complete 8 ms intact with a
3.7911e-7 J absolute energy residual. That lane still uses a fictional 1 MPa
material and six tetrahedra, so it cannot produce a glass fragment population
regardless of the contact work.

## Concrete next steps, in order

1. **Fix the sphere/material contact post-pass energy injection** (+81.8 kJ,
   measured above). Until that is closed no fragment count from this lane can be
   trusted even at a resolved timestep.
2. **Give the active solver a resolution-derived substep.** The limit is now
   computed (`measureLatticeResolutionLimit`) but nothing consumes it. Either
   derive the substep count from it or reject/flag an unresolved run explicitly.
   At the shipped 1/240 s step that means about 2819 substeps, roughly 9e10 bond
   solves per simulated second for this lattice: the cost, not the correctness,
   is what makes this hard, and that is worth stating in the roadmap.
3. **Then, and only then, re-run the refinement sweep and report a fragment size
   histogram** rather than a count. Convergence means the histogram stops moving.
4. **Then compare strength-based and Gc-based critical stretch at two voxel
   sizes.** That is the first honest calibration question this model can be asked.
5. Separately, decide whether ceramic/ice/concrete keep their multipliers, with a
   measurement rather than by precedent.

## Verification

- **85 of 85 CTest suites pass** in `build/agent` Release. The baseline was 84;
  one suite was added (`banjo_bond_failure_orientation_tests`), none removed, and
  no tolerance was loosened. `banjo_material_stage_tests` now runs its support
  case twice, once with the legacy projection (every previous assertion kept
  unchanged) and once with the constrained solve, and additionally requires both
  to reach the same final node position and velocity.
- Python: 161 tests collected, 157 pass, 17 skip, 4 error. The four errors are in
  `tests/material_behavior_native_tests.py`, which hardcodes
  `build/win-joint-double/Release/banjo_material_behavior_probe.exe`; that build
  directory does not exist in this worktree. The failure predates this work and
  is unrelated to it.
- **Not verified:** interactive viewer behaviour (`BANJO_BUILD_LAB=OFF` here),
  any non-Windows platform, any real-time claim, and any claim of physical
  realism. This is an experimental prototype with a measured but still open
  conservation ledger.
