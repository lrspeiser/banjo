# Tetrahedron contact checkpoint

Updated 2026-09-06 on branch `agent/tetra` (parent commit `fbd8108`). Environment:
Windows 11, MSVC 19.44.35228.0, Visual Studio 17 2022 generator, x64 Release,
`-DBANJO_BUILD_LAB=OFF`, Jolt v5.6.0, `DOUBLE_PRECISION=ON`. Build directory
`build/agent`.

## What is retained and verified

`TetrahedronContactImpulse` is built into `banjo_core` and covered by
`banjo_tetrahedron_contact_impulse_tests`. It is a pure impulse resolver over two
supplied tetrahedron sides and a caller-supplied unit normal: it does not perform
any contact query, and it does not imply fracture or cutting. Approaching contacts
produce a normal impulse; separating and static contacts stay inactive.

`SweptSegmentTriangle`, `PairedFacetContact` and `SpherePatchSnapshotCodec` are
built into `banjo_core` and covered by `banjo_swept_segment_triangle_tests`,
`banjo_paired_facet_contact_tests`, `banjo_facet_closure_energy_tests` and
`banjo_sphere_patch_snapshot_codec_tests`.

`TetrahedronContact` is now built into `banjo_runtime` and covered by
`banjo_tetrahedron_contact_tests`, registered inside the existing
`if(TARGET banjo_runtime)` block. It is Jolt-dependent (`JPH::GJKClosestPoint`,
`JPH::EPAPenetrationDepth`) so it does not belong in the Jolt-free `banjo_core`.
The suite is 85/85 passing, up from the 84/84 baseline; the added test is the
only difference. `tests/cohesive_playback_tests.py` (8) and
`tests/thermal_material_server_tests.py` (7) were not re-run for this change,
which touches no Python-facing surface.

`banjo_tetrahedron_contact_tests` reports:

```
[PASS] separated touching
[PASS] face edge overlap
[PASS] rigid transform
[PASS] invalid
```

No tolerance in `tests/tetrahedron_contact_tests.cpp` was changed, and the test
file is untouched. The barycentric gate (-2e-5), the reconstruction tolerance
(3e-5 m) and the normal-parallelism tolerance (2e-5) are all as they were.

## What the three recorded defects turned out to be

### 1. Separated pairs were unresolved - fixed

Confirmed as diagnosed. With a zero convex radius,
`EPAPenetrationDepth::GetPenetrationDepthStepGJK` hands GJK `inMaxDistSq = 0`, so
`GJKClosestPoint::GetClosestPoints` takes its early exit at the first support
point that proves any positive separation and returns `FLT_MAX` *before*
evaluating `CalculatePointAAndB`. Jolt documents this: "NotColliding: returned if
the objects don't collide, in this case outPointA/outPointB are invalid." The
query now re-runs `GJKClosestPoint::GetClosestPoints` on that branch with an
uncapped `inMaxDistSq`, which reaches the witness computation.

Measured, unit tetrahedron against itself translated by (2, 0, 0): witness points
(1, 0, 0) and (2, 0, 0), separation 1 m, normal (1, 0, 0), barycentric
(0, 1, 0, 0) and (1, 0, 0, 0) - all exact.

### 2. Exactly-touching pairs were unresolved - fixed, semantics chosen

**A pair that shares only boundary points resolves as a contact: `resolved` and
`hit` true, `penetration_depth_m` and `separation_distance_m` both zero.** It is
not rejected as degenerate. Three reasons, recorded because the checkpoint
explicitly left this open:

- It is the common limit of both neighbouring regimes. Separation decreasing to
  zero and depth decreasing to zero both converge on it, so rejecting it would
  put an unresolvable hole in the answer exactly at the instant contact begins -
  the instant a contact solver most needs an answer. A resolver stepping a body
  into contact would see `resolved == false` for the crossing step and silently
  drop the contact.
- `resolved == false` is reserved in this module for inputs the query cannot
  describe: non-finite, out of range, or zero-volume. A touching pair is a
  well-posed configuration with a unique witness point and a well-defined zero
  depth. Only the normal is under-determined.
- It keeps `hit` a closed predicate meaning "the tetrahedra intersect as closed
  convex sets", which two shapes sharing a point do.

The mechanism: GJK returns `Indeterminate` and `GetPenetrationDepthStepEPA` then
declines. That refusal is not a failure to interpret - every EPA exit path in
Jolt v5.6.0 is a refusal to build a hull enclosing the origin, and Jolt's own
comment says the hull is degenerate "if the shapes touch in 1 point (or plane)".
The GJK step has already placed a witness pair on the shared boundary, so the
query keeps it.

The cost of this choice is that the contact normal at zero depth is not unique -
the touch admits a whole cone of separating directions. The query reports the
normalised centroid offset of B minus A: a deterministic representative of that
cone, equivariant under rigid motion, oriented from A towards B so that
`dot(v_b - v_a, n) < 0` still means "closing", which is the sign
`evaluateTetrahedronContactImpulse` reads. This is stated in the header;
callers must not treat a zero-depth normal as unique.

Measured, unit tetrahedron against itself:

| translation | kind | witness pair | reported normal |
| --- | --- | --- | --- |
| (1, 0, 0) | vertex on vertex | (1, 0, 0) twice, identical | (1, 0, 0) |
| (0.5, 0.5, 0) | vertex on edge | (0.5, 0.5, 0) twice, identical | (0.7071, 0.7071, 0) |
| (0, 0, 1) | vertex on vertex | (0, 0, 1) twice, identical | (0, 0, 1) |

The (0.5, 0.5, 0) normal was checked against the geometry by hand: the touch
point is B's corner vertex resting on A's edge between (1, 0, 0) and (0, 1, 0),
and (1, 1, 0)/sqrt(2) lies inside both A's outward normal cone at that edge and
the negated normal cone of B at that vertex, so the reported representative is a
genuine separating direction and not merely a finite placeholder.

The same (0.5, 0.5, 0) touch rotated by the test's quaternion and translated to
(3, -2, 0.4) reports the normal (0.030371780849729503, 0.96349872620572141,
0.26598450993989908) against the analytically rotated (1, 1, 0)/sqrt(2) of
(0.03037178084972994, 0.96349872620572141, 0.26598450993989908) - equivariant to
4.4e-16.

That rigid-motion case also caught a defect that the test suite does not cover.
Taking the normal from the witness gap, as the overlapping branch does, is wrong
for a touch: at a coordinate magnitude of 3 m the two witness points of a
touching pair differ by exactly one float ulp (2.4e-7 m) in a single axis, and
normalising that returned (1, 0, 0) - an axis-aligned vector with no relation to
the contact. The touching branch therefore never uses the gap direction.

To keep a genuine EPA numerical failure from being reported as a zero-depth
touch, the touching branch also requires the two witness points to coincide to
1e-4 of the largest input coordinate. Observed residuals are 0 exactly at the
origin and 2.4e-7 m for the case above, where the bound stands at 3.6e-4 m.

### 3. `narrow_phase_calls` discarded on failure - fixed

Every `return {}` was replaced by a return of the partially filled result, so the
counter survives all failure paths. Demonstrated on a real failing solver path
rather than by inspection: a unit pair overlapping by (0.8, 0.05, 0.05) swept out
to 600 m along x fails the barycentric gate and reports `resolved = 0` with
`narrow_phase_calls = 1`.

The counter counts bounded narrow-phase *passes over the pair*, not Jolt entry
points, and this is now stated in the header. One query performs at most one pass
and never loops, subdivides or retries, so the value is 1 for any query that
reached the solver and 0 for one rejected on its inputs alone - inputs rejected
before the solver ran genuinely cost nothing, which the measurements confirm
(degenerate and out-of-range inputs both report 0). Summed over a batch it counts
pairs actually tested.

What that definition hides, recorded so nobody reads more into the number than is
there: the separated branch runs the GJK support loop twice, once capped and once
uncapped, and both are inside the single counted pass. The capped run is cheap -
it exits at the first support point proving separation - but it is not free, and
the counter does not distinguish it. Making the counter a Jolt-entry counter is
not possible while keeping it at 1 on both branches: `GetPenetrationDepthStepEPA`
can only be seeded from the private `GJKClosestPoint` inside the same
`EPAPenetrationDepth`, so whichever query runs first, the other branch needs a
second traversal.

## Measured accuracy limit

`kMaximumCoordinateM` (1000 m) is an input sanity gate, not an accuracy
guarantee. The solvers are single precision, so witness-point error grows with
coordinate magnitude while the barycentric gate stays fixed at 2e-5 of the
tetrahedron's own size. What limits the query is the ratio.

Unit tetrahedron pair overlapping by (0.8, 0.05, 0.05), swept along x, most
negative barycentric weight:

| offset | most negative weight | resolved |
| --- | --- | --- |
| 0 m | -3.0e-8 | yes |
| 100 m | 0 | yes |
| 300 m | -1.2e-5 | yes |
| 400 m | -1.2e-5 | yes |
| 600 m | -4.9e-5 | **no** |
| 900 m | -4.9e-5 | **no** |

A 100 m tetrahedron in the same relative configuration at 600 m is at -4.2e-7 and
resolves, which confirms the ratio rather than the absolute distance is what
matters. A pair resolves while it sits within roughly 500 of its own edge lengths
of the origin. Beyond that the query declines rather than returning a witness
point it cannot place, and callers needing wider worlds must rebase the pair near
the origin. Separated pairs are unaffected at these distances because their
witness points land on vertices, which are exactly representable.

The penetration depth itself is accurate to about 1e-6 m at unit scale: EPA
returns 0.057735036382477435 m for the (0.8, 0.05, 0.05) overlap against the
analytical 0.1/sqrt(3) = 0.057735026918962574 m.

## Remaining defects and next tests

- The `EStatus::Colliding` branch is unreachable with zero convex radii and is
  therefore handled but unexercised. It is written to fall into the touching
  branch. If a caller ever supplies a non-zero convex radius, that branch needs a
  test before it is trusted.
- No test covers the touching semantics under rigid motion, the accuracy limit
  sweep, or the preserved counter on a failing solver path. All three are
  measured above from a scratch probe that was removed; they are not regression
  tests. Adding them to `tests/tetrahedron_contact_tests.cpp` is the obvious next
  step, and would have caught the ulp-noise normal.
- The touching-branch witness-agreement bound (1e-4 relative) is set from three
  measured residuals at two coordinate scales. It is not derived from a bound on
  Jolt's barycentric reconstruction error, so it is calibration, not a proof.
- No material dependence is involved: this is pure contact geometry over supplied
  vertex positions, so the glass/oak/iron comparison required for
  material-dependent physics does not apply and was not run.

No contact query, fracture, cutting or impulse claim is made for tetrahedron
pairs beyond what is listed above. The query returns geometry only; it never
implies fracture, cutting, or an impulse.
