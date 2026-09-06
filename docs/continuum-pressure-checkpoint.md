# Spatial pressure and springback reference

This checkpoint connects the J2 material law to a connected 3D quasistatic
tetrahedral mesh. Applied surface forces, internal stress and supports determine
the displacement field. Unloading leaves a residual iron shape and plastic
history. The separate native viewer draws these computed node positions.

This is an experimental pressure coupon, not a ball impact or calibrated dent.
It has no inertia, collision, finite rotation, fracture, tissue cutting or
thermal coupling. The existing network runtime remains a separate backend.
No full G01–G09 goal is complete.

Verification: the full Windows Release build succeeds and all **57 CTest
suites pass in 83.23 seconds**. The **33 mocked playground tests pass in
2.198 seconds** without an API call. Normal native viewing, material columns,
computed playback, frame stepping and labeled magnification were inspected;
the final viewer was rebuilt and its capture inspected after the footer fix.

## API and numerical contract

`SmallStrainLaw` admits isotropic linear elasticity, fixed-axis orthotropic
linear elasticity, and small-strain isotropic J2 with linear hardening. SI
parameters select the law; material names do not. Orthotropic compliance must
be positive definite. Physical tensor shear components use the double-
contraction factor of two; they are not engineering shear strains.

`SmallStrainPatch` accepts a reference mesh, per-element material indices,
density and fixed displacement components. It provides `solveLoad`,
`evaluate`, `positionsM`, boundary triangles, masses, state and `restoreState`.
`PatchLoad` contains nodal forces in newtons and prescribed displacements in
metres on constrained components. Free prescribed components must be zero.
`makeTetrahedralBrick` constructs a conforming six-tetrahedron-per-cell mesh.
Imported meshes require upstream nonintersection certification: local
orientation, duplicate-node and manifold checks do not prove global absence
of overlapping matter.

The constant-strain tetrahedra assemble internal forces as volume-weighted
stress times shape-function gradients. Newton iterations use the returned
constitutive tangent, a matrix-free stiffness product and diagonally
preconditioned conjugate gradients. Every trial integrates from the last
accepted plastic history. A line-search, iteration, strain, gradient or work
budget failure preserves the entire accepted state. Free-force convergence
uses only free applied loads and the initial free residual; a force on a fixed
component cannot loosen that tolerance.

The weak elasticity formulation follows the standard balance described in
[MFEM's elasticity example](https://mfem.org/annotated/ex2/). The J2 return
mapping and algorithmic tangent are checked against the derivation in
[Bleyer's plasticity tutorial](https://bleyerj.github.io/comet-fenicsx/tours/nonlinear_problems/plasticity/plasticity.html).
P1 tetrahedra can exhibit volumetric locking during nearly incompressible
plastic flow. Neither a small force residual nor a passing material-point
test establishes spatial accuracy.

Reactions equal internal minus applied force on constrained components.
Reports separate stored elastic/hardening energy, cumulative physical plastic
dissipation, trapezoidal external-work error, backward-Euler quadrature excess
and its balance residual. Moments use reference coordinates, consistent with
the small-strain formulation. They are not a finite-configuration angular-
momentum or dynamic-impact conservation claim.

The finer mesh exposed subtraction cancellation in the old J2 energy increment.
It now uses the exact quadratic elastic-energy secant and accepted represented
strain increment, plus the hardening increment. A one-ULP unload/reload test
from a plastic state prevents regression; no yield threshold or tolerance was
relaxed to hide the defect.

## Reproduce the experiment

Build `banjo_continuum_cli` and `banjo_continuum_lab`, then run from the repo:

```powershell
.\build\win-joint-double\Release\banjo_continuum_cli.exe --resolution 4 --increments 32 --peak-pressure-pa 800000000 --output build/pressure-new.json
.\build\win-joint-double\Release\banjo_continuum_lab.exe build/pressure-new.json
```

The output path must be new. The CLI admits resolutions 4, 8 or 12 and 2–100
increments per loading/unloading branch. Pressure must be finite in (0, 1e9]
Pa. The central 20 × 20 mm pressure footprint aligns with every admitted mesh;
the compiler checks its integrated area is 0.0004 m². It is not a point force.

All three coupons are 40 × 20 × 40 mm, fully clamped on the bottom, with the
same downward central top-face pressure ramp followed by unloading. There is
no gravity in this quasistatic test. Density determines mass but not this
force-controlled equilibrium. The illustrative, uncalibrated parameters are:

| Control | Density kg/m³ | Elastic parameters | Further law |
|---|---:|---|---|
| Glass | 2,500 | E = 70 GPa, nu = 0.22 | Isotropic elastic only; no strength/failure law |
| Oak | 700 | Ex/Ey/Ez = 0.7/12/1 GPa; nu_xy/yz/zx = 0.025/0.30/0.30; Gxy/yz/zx = 0.6/0.7/0.1 GPa | Fixed aligned orthotropic elasticity; no splitting/crushing |
| Iron | 7,870 | E = 211 GPa, nu = 0.30 | J2 yield 250 MPa, isotropic hardening 1 GPa |

The strain norm limit is 0.05 and full displacement-gradient norm limit is
0.1. These are numerical model-admission limits, not measured failure strains.
Elastic glass/oak survival at a high pressure must not be interpreted as real
glass or wood surviving it.

## Measured refinement and limits

Windows MSVC 19.44 Release, same declared pressure footprint and supports:

| Mesh x/y/z | Tetrahedra | Iron residual displacement at 800 MPa | Maximum equivalent plastic strain | Plastic dissipation |
|---|---:|---:|---:|---:|
| 4/2/4 | 192 | 34.409 µm | 0.003822 | 3.175 J |
| 8/4/8 | 1,536 | 162.203 µm | 0.017189 | 23.490 J |
| 12/6/12 | 5,184 | 348.400 µm | 0.035464 | 55.384 J |

All use 32 increments per branch. This strong mesh dependence means the dent
magnitude is **not spatially converged**. At 400 MPa the coarse iron mesh stays
elastic, while the finer meshes yield slightly; the onset itself remains
resolution-sensitive. Sharp traction edges, clamped boundaries, discretization
and locking require separate investigations rather than an assumed diagnosis.

At fixed 4/2/4 mesh and 800 MPa:

| Increments per branch | Iron residual displacement | Total trapezoidal work residual |
|---:|---:|---:|
| 16 | 34.582 µm | -0.011382 J |
| 32 | 34.409 µm | -0.002341 J |
| 64 | 34.313 µm | -0.000582 J |
| 100 | 34.277 µm | -0.000252 J |

Load-increment refinement improves this fixed-mesh path but does not resolve
the spatial error. The largest backward-Euler balance residual over the nine
400/800 MPa setups was 2.59e-9 J; that is discrete bookkeeping consistency,
not a substitute for the physical work/refinement gates.

At 100 MPa all three materials complete load/unload on all three meshes with
zero plastic strain. The largest residual displacement is below 1.6e-14 m.
At 800 MPa oak reaches the declared strain/gradient limits and retains its
last valid loaded shape. It does not complete unloading. The report records
the rejected requested load separately from the accepted load and shape.

Full spatial displacement/material/load state is serialized to JSON and read
back against the same immutable mesh/law/constraints. Every tested round trip
is exact and the next-load state agrees with uninterrupted execution. Some
near-limit oak continuation attempts reject in both copies. This is not a
compact spatial codec, wrong-mesh authentication, gameplay repair or world
reactivation; those remain G07 work. Timing fields are single-run diagnostic
measurements, not p95/p99 real-time qualification.

## Chat and visible inspection

Ask the playground: **“Run the spatial pressure and springback test for glass,
wood and iron.”** The bounded `continuum_pressure_reference` route selects the
fixed 4/2/4 mesh, 32 increments and 800 MPa fixture. The server runs the native
CLI, exposes its report and opens the computed sequence in the continuum lab.
GPT cannot change constitutive parameters, commands or paths through this
route. Unused generic plan fields do not change the fixed reference setup.

The viewer displays actual displacements and an undeformed reference mesh.
Play/pause/reset/frame stepping replay accepted solver output; display
magnification is explicitly labeled and never changes physics. A limited case
holds its last valid shape while other material sequences continue. A failed
trial's residual is identified separately from the retained geometry.

The next numerical gate is a smoother, specified pressure/support benchmark
with displacement, reaction and energy convergence and a locking-resistant
formulation comparison. Then qualify dynamic contact, state transfer and
calibrated material parameters before presenting metal-on-metal impacts as
validated dents. Brittle glass, wood damage and finite-strain tissue require
their own laws and comparative evidence.

Live job `da66b2b4bd814676b1da0b890aa52a21` used the existing ignored `.env`
and `gpt-5-mini`: 1,514 tokens, 6.822 seconds planning, 7.369 seconds total.
The generated declaration selected the pressure reference; glass and iron
produced 65 frames each and oak produced 23 including its rejected trial.
The native window opened and Results showed `reference_limited` with the
material statuses. The full physical report equals the independently run
CLI report after excluding only `solve_wall_ms`. Browser checks found no
page errors. Model text remains a proposal; the native report is the evidence.
