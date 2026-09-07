# Tetrahedron contact checkpoint

Recorded 2026-09-06. Environment: Windows 11, MSVC 19.44.35228.0, Visual Studio 17
2022 generator, x64 Release, `-DBANJO_BUILD_LAB=OFF`, Jolt v5.6.0,
`DOUBLE_PRECISION=ON`. Build directory `build/agent-checkin`.

## What is retained and verified

`TetrahedronContactImpulse` is built into `banjo_core` and covered by
`banjo_tetrahedron_contact_impulse_tests`. It is a pure impulse resolver over two
supplied tetrahedron sides and a caller-supplied unit normal: it does not perform
any contact query, and it does not imply fracture or cutting. Approaching contacts
produce a normal impulse; separating and static contacts stay inactive.

`SweptSegmentTriangle`, `PairedFacetContact` and `SpherePatchSnapshotCodec` are
built into `banjo_core` and covered by `banjo_swept_segment_triangle_tests`,
`banjo_paired_facet_contact_tests`, `banjo_facet_closure_energy_tests` and
`banjo_sphere_patch_snapshot_codec_tests`. The full suite is 84/84 passing, plus
`tests/cohesive_playback_tests.py` (8) and `tests/thermal_material_server_tests.py` (7).

## What is committed but deliberately NOT in the build

`src/physics/TetrahedronContact.{hpp,cpp}` and `tests/tetrahedron_contact_tests.cpp`
are committed as source only. They are not referenced by `CMakeLists.txt`, so they
do not compile in any target and `banjo_tetrahedron_contact_tests` does not exist as
a ctest entry. This is intentional: the module does not pass its own test.

The code is Jolt-dependent (`JPH::EPAPenetrationDepth`), so when it is wired in it
belongs in `banjo_runtime`, not the Jolt-free `banjo_core`; its test must link
`banjo_runtime` inside the existing `if(TARGET banjo_runtime)` block.

### Measured defects

Wiring the module into `banjo_runtime` and running its test gives 2 failures of 4
(`rigid transform` and `invalid` pass):

1. **Separated tetrahedra are unresolved.** For the unit tetrahedron against itself
   translated by (2, 0, 0), `GetPenetrationDepthStepGJK` returns
   `EStatus::NotColliding` and leaves `outPointA`/`outPointB` at (0, 0, 0) — it does
   not write witness points on that path. `tetrahedronContact` assumes they are
   valid, so barycentric recovery against the translated tetrahedron fails and the
   function takes `return {}`. Separated queries need
   `GJKClosestPoint::GetClosestPoints` rather than the returned arguments of the
   penetration-depth step.

2. **Exactly-touching configurations are unresolved.** For the translation
   (0.5, 0.5, 0), vertex (0.5, 0.5, 0) lies exactly on the plane x+y+z=1 of the
   first tetrahedron. GJK returns `EStatus::Indeterminate` and the subsequent
   `GetPenetrationDepthStepEPA` call fails, so the query returns unresolved. The
   overlapping translation (0.8, 0.05, 0.05) also returns `Indeterminate` from GJK
   but is recovered by EPA, giving depth 0.0577350364 m.

Separately, the `return {}` failure paths discard `narrow_phase_calls`, so a failed
query reports zero narrow-phase calls and the counter cannot be used to audit cost
on exactly the paths where it matters.

### Next step

Fix the separated-case witness points via `GJKClosestPoint::GetClosestPoints`,
decide and document the intended behaviour for exact face-touching (resolve as
separation of zero, or reject as degenerate), and preserve `narrow_phase_calls`
across failure returns. Do not relax the barycentric or normal tolerances in
`tests/tetrahedron_contact_tests.cpp` to make the existing test pass. Then move
`src/physics/TetrahedronContact.cpp` into `banjo_runtime` and register the test.

No contact query, fracture, cutting or impulse claim is made for tetrahedron pairs
in this checkpoint.
