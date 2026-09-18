# Workshop consistency checkpoint — September 17, 2026 Pacific

## Scope and source

This checkpoint builds on PR #15 (`e222241a796c484624507e5ef9877b6f8714b773`),
not on the source-bundle preparation branch. It advances roadmap goals 1, 2,
5, 7, 9 and the regression portion of 10. It does not complete the ten-goal
roadmap, change a material law, or claim calibrated real-world material behavior.
PR #16's separate inspection views are not included in this patch.

## Implemented

- Physical skin edits compute mass, component allocation, centre of mass,
  cubic-cell inertia, support hull, and geometry-connectivity diagnostics from
  the canonical occupied cells. Exterior-only display cannot change these
  properties. Missing parts/disconnected cell islands produce warnings, not a
  sound-product claim. Face connectivity is not a claim about the bond graph.
- Old wireframe load paths and reduced contracts cannot validate physical-skin
  edits. The API requires retesting and refuses unsupported primitive-based
  engineering operations. Materialization previews keep their old primitive
  descriptions under `wireframe_objects`, not executable `objects`, when a
  physical-skin installation adapter is still needed. Their fingerprint, BOM
  and measurements refer to canonical Matter, not the old straight parts.
- Exact static-load tests verify the native engine's actual cell offsets and
  material against the canonical grid before advancing time. The whole product
  is seated on the test floor by one reported integer-grid translation; its
  curved end caps are not clipped or separately repositioned. Trial metadata
  includes both the canonical hash and `engine_grid_verified`.
- Skin sampling scans transformed part bounds and builds the curve samples once
  per component. Large asymmetric bends are no longer clipped by a symmetric
  half-width bound. The reported half-cell diagonal is a grid sampling bound,
  not a calibrated surface/curve error or mechanical-accuracy guarantee.
- Edited designs now appear in Saved designs as well as My Library. Geometry
  and skin overrides survive reopen, including earlier lineage-carried edits.
  Physical recipes are tagged as requiring retest. SQLite connections close
  deterministically after use.
- Errors are visible above Build/Test/Details. Product/variant changes clear
  stale Matter, test results, selection and skin controls. Failed rebuilds
  explicitly have no current result. Late candidate/geometry responses cannot
  replace a newer selection. The requested trace has the measured displacement
  fields rather than silently displaying a missing value as zero.
- Isolated tests optionally retain a **simulation trace**: numerical physics
  states, not video. The `record_trace` boolean defaults to true for existing
  inspection clients and can be turned off without skipping the physics test.
  The live world is neither recorded nor advanced by these tests.
- Traces sample intermediate accepted states at the same solver timestep,
  initially about 30 Hz; transport batch size changes, not the material law.
  Retained states are capped at 600 by deterministic whole-span thinning.
  Effective spacing and maximum gap are reported. Events have a separate
  bounded list with an overflow flag. Subsystem replies do not erase poses.
- Session-specific recorder injection replaces the process-global Session
  monkey-patch. Cart, kettle and controller tests can supply traces without
  intercepting another session. The controller test explicitly identifies the
  reference hoist rather than claiming to test the selected product's geometry.
- Static-load inspection draws verified native cells while topology is
  unchanged. Changed topology and generic fixtures use explicitly labelled
  reduced collision proxies, never an intact skin drawn over separated pieces.

## Verification

Local environment: Linux, Python 3.13.5, Node 22.16.0, GCC 14.2.0, Release build,
`banjo-cpu-precise-v1`. Native C++ source and material laws are unchanged.

The local Workshop run completed 22 existing Python suites, 170 tests, and six
native-engine acceptance tests. Native cases include glass/oak/iron at 20 mm
and 40 mm, native cell/material mismatch rejection, exact-cell static-load
inspection, moving cart bearings, heated contained water, powered hoist work,
and identical measured cart results with trace capture enabled and disabled.
Pure tests include cell inertia, hull-vs-bounding-box balance, missing members,
physical-vs-cosmetic changes, saved overrides, bounded trace/event storage,
retained endpoints and subsystem snapshots. No tolerance was relaxed.

The local browser environment rejected navigation by administrator policy.
`tests/workshop_browser_tests.py` is therefore an explicit GitHub Actions gate
before publication: visible failures, stale-state clearing, current physical
measurements, saved edited recipes, out-of-order responses, and cart trace
inspection. It is also imported by the existing full browser CI suite.
The required mode fails rather than skips if Chrome or the native runner is
missing. `scripts/verify-workshop-checkpoint.py` records the executed checks.

## Limits / next gates

This is not a Workshop-to-live-world transaction implementation. Fixed
mixed-material fused lattices, full physical-skin ProductGraph interfaces,
generic functional certification, damage-aware detailed remeshing, CAD
installation, world-scale adaptive cells and complete restart/publishing
remain open. A geometric warning is not a fracture verdict. Static loads
without declared tolerances still return `not-declared`, never a fabricated
pass. Trial evidence alone is not an installation permission.

## Published verification evidence

The GitHub Actions checkpoint gate passed all 22 Workshop Python suites, six native-engine tests, and five required Chrome browser regressions. This is a focused checkpoint gate, not a complete native CTest run.

Run: https://github.com/lrspeiser/banjo/actions/runs/35292216840
