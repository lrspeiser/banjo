# Bounded pressure loading and an assembled continuum solve

Banjo still solves material volume beneath the visible skin. This checkpoint
adds an optional assembled stiffness backend to the existing quasistatic
tetrahedral reference and a public pressure-load builder. It changes how the
same equations are evaluated, not the material laws or displayed deformation.
The matrix-free reference remains the default and a comparison path.

Verification: the Windows MSVC 19.44 Release build succeeds. All 58 native
suites pass in 83.49 seconds. Additional nonzero-prescribed-state, partial-load
and invalid-profile test cases pass the subsequent three-suite focused rerun
(0.47 seconds). The 33 mocked playground tests pass in 2.164 seconds. A
ten-sample-per-backend benchmark smoke run accepts all four cases and preserves
repeated restored state; its timings are not performance qualification.

The complete platform goal and all 40 scorecard requirements remain open.
This reference has no inertia, collision, fracture, finite rotation or thermal
coupling. It is separate from the bonded-cell contact runtime. Its illustrated
glass and oak laws are elastic controls, not physical survival predictions.

## Public pressure API

`makePatchPressureLoad(patch, pressure)` builds `PatchLoad` nodal forces without
mutating the patch. `PatchPressure` declares a reference-space center in metres,
orthonormal in-plane axes, half widths in metres, a peak pressure in pascals and
either a uniform or smooth profile. The pressure acts along
`-cross(axis_u, axis_v)` on coplanar outward boundary triangles. The default
axes `(1,0,0)` and `(0,0,-1)` press downward onto a top face.

Triangles are clipped against the footprint before integration. Original face
shape functions are carried through clipping, so moving a rectangular edge
through an element changes the integrated load continuously instead of adding
or removing a whole triangle according to its centroid. The result reports
actual covered area, pressure-weighted area, force, reference-coordinate moment
and quadrature work. Partial surface coverage remains partial; empty coverage
rejects. Prescribed components retain their current accepted displacements.

The smooth profile is `p_peak (1-(u/a)^2)^2 (1-(v/b)^2)^2` within the rectangle.
Its full pressure-weighted area is `(16a/15)(16b/15)`, or `64/225` of the
geometric area. Constant pressure uses exact triangle integration. Smooth
pressure uses a 6 by 6 Gauss rule on a square-to-triangle map: the transformed
integrand has degree at most 10 and 9 in the two coordinates, within the
degree-11 rule. See the [Duffy mapping derivation](https://finite-element.github.io/1_quadrature.html)
and [Gauss-Legendre polynomial exactness](https://numpy.org/doc/2.2/reference/generated/numpy.polynomial.legendre.leggauss.html).

Admission bounds are explicit: center length at most 1,000 m, half widths
1e-8 to 10 m, peak pressure 0 to 1e12 Pa, unit/orthogonal axes within 1e-12,
coplanarity within 1e-10 m and per-node force at most 1e12 N. Nonfinite inputs
and unknown profiles reject. These are API limits, not material validity
ranges. This load builder does not infer contact force from an impact and is
not a follower-pressure law on a rotating surface.

## Assembled backend and work limits

`PatchSolveOptions.linear_backend = PatchLinearBackend::AssembledBlockCsr`
selects the alternative. Immutable element adjacency compiles a nodal graph of
3 by 3 blocks. Each Newton iteration assembles the same frozen-history
algorithmic tangent, including physical tensor shear factors, into that graph.
Conjugate gradients then multiply stored blocks instead of traversing every
element and reapplying its tangent. The diagonal preconditioner, material
return mapping, line search, residual tolerances and accepted-state commit
remain the same. The full tangent is assembled without imposing symmetry.

`maximum_element_visits` counts actual element passes. The separate
`maximum_tangent_block_visits` defaults to 64,000,000 stored-block visits per
solve and is checked before every assembled product. Reports distinguish
assembly visits, matrix-free element products and assembled block products;
the counters are not interchangeable. Exhaustion preserves accepted geometry,
plastic history, loads, work ledgers and revision. This work cap is not a
wall-clock deadline or a world scheduler.

Graph construction happens once per patch for either backend. Stored tangent
blocks are allocated and rebuilt per Newton iteration; this checkpoint does
not claim allocation-free updates or a measured whole-world memory budget.

## Crossed mesh and load-increment evidence

The fixture is a 40 by 20 by 40 mm brick, bottom fully clamped, with a central
20 mm square top pressure. Meshes are x/y/z = n/(n/2)/n. All experiments retain
glass, oak and iron under identical loads; iron has the J2 law described in the
[preceding pressure checkpoint](continuum-pressure-checkpoint.md).

At 800 MPa uniform peak pressure, with 64 load and 64 unload increments:

| Mesh n | Tetrahedra | Iron outcome | Residual displacement | Plastic dissipation |
|---:|---:|---|---:|---:|
| 4 | 192 | Completed unload | 34.313 micrometres | 3.168 J |
| 8 | 1,536 | Completed unload | 161.514 micrometres | 23.384 J |
| 12 | 5,184 | Completed unload | 347.249 micrometres | 55.174 J |
| 16 | 12,288 | Block-work limit during loading | Not measured | Not measured |

For the n=16 case, the last accepted load fraction was 0.953125; its retained
419.449 micrometre displacement is a **loaded shape**, not residual springback.
At 32 and 100 increments the same mesh also reaches the block-work cap before
peak load. These failures are recorded rather than increasing the budget to
present a completed cycle. Glass completes these cycles. Oak reaches declared
small-strain/displacement-gradient limits and does not complete unloading.

Increasing load increments from 32 to 100 changes iron residual displacement
from 34.409 to 34.277 micrometres on n=4, from 162.203 to 161.257 on n=8,
and from 348.400 to 346.824 on n=12. That improves the load path but leaves the
strong spatial sensitivity unresolved. A small discrete energy-balance error
does not resolve this problem.

A second study compares uniform 200 MPa with smooth 703.125 MPa, both having
an 80,000 N resultant over the same rectangle. These are **different pressure
fields** with matched force, not interchangeable versions of one experiment.
All uniform controls complete and iron stays elastic. Smooth-load iron has
residual displacement about 0 / 2.162 / 4.538 / 6.646 micrometres on n=4/8/12/16
and dissipation 0 / 0.03087 / 0.09651 / 0.14189 J. Smooth-load oak reaches the
declared validity limit on the three finer meshes. Smoothing the load therefore
does not establish convergence or isolate the cause of the original error.

Across the complete n=8, 32-increment, 800 MPa paths, backend differences are
at most 4.03e-15 m in displacement, 2.16e-14 in equivalent plastic strain,
4.45e-12 J in stored energy and 5.90e-12 J in plastic dissipation. Both retain
the same accepted/limited frames. Each backend's full JSON state round-trip
and next-load state agree exactly with its uninterrupted copy. Across-backend
comparisons allow floating-point roundoff and are not bitwise claims.

## Benchmark harness

`banjo_continuum_kernel_benchmark --resolution 4 --samples 100 --output <new-file>`
measures restore, solve and combined p50/p95/p99 using nearest-rank percentiles.
Resolutions 4/8/12 and 10..1,000 timed samples are accepted. Each case establishes
a common matrix-free history through increment 24 of 32, then restores it
before each backend solves increment 25. Three warmups precede timed samples;
every observed state is checked for finite fields and exact same-backend
repeatability outside the timed interval. Glass/oak/iron use 100 MPa peak
controls, followed by a separate 800 MPa iron history. Reports include parity
metrics for displacement, strain, history, reactions, tangent and work.

The constructor, pressure integration, verification, rendering and world
scheduler are outside those timings. Matrix-free runs before assembled in each
case. The harness is built and smoke-tested; repeated isolated measurements
remain pending while the user examines the native 3D experiment. No p95/p99
performance conclusion is claimed by this checkpoint.

Rejected frames retain geometry and material history, while uncomputed
reaction/moment/work balances are omitted. Force residual and iteration/work
counters describe the failed requested load and are labeled separately. The
viewer already labels failed-attempt residuals; it does not draw failed trials
as accepted geometry.

## Reproduction and remaining gates

Build `banjo_continuum_cli`, `banjo_continuum_kernel_benchmark` and the native
`banjo_continuum_lab`. CLI options now include:

```text
--resolution <even integer 4..16>
--increments <2..100 per load/unload branch>
--peak-pressure-pa <positive value up to 1e9>
--pressure-profile uniform|smooth
--linear-backend matrix-free|assembled
--frames full|summary
--output <new file>
```

Defaults and the chat reference remain n=4, 32 increments, uniform 800 MPa,
matrix-free and full frames. Full reports retain the native viewer schema;
summary reports have their own schema and cannot be opened as geometry. File
output is compact JSON; scalar summaries retain accepted/limited status,
displacement, yielded reference volume, integrated equivalent plastic strain,
energy and work counters. Yielded volume uses equivalent plastic strain above
1e-10. Summary output still performs full state round-trip verification; it is
not a compact spatial persistence codec.

The next G02 gate is element-orientation and locking-resistant formulation
comparison against the same load/support problem, with displacement, yielded
volume, dissipation, reaction and work convergence criteria declared before
new sweeps. Then qualify dynamic contact and calibrated material parameters.
G05 still needs bounded active islands, transfer/error accounting and measured
mixed-world p95/p99 performance. No pressure-kernel timing establishes that
thousands of changing contacts can run in real time.
