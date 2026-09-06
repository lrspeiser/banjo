# Experiment physics gaps and next integration

Baseline audit before the new composable routes. See [the subsequent implementation](general-experiment-checkpoint.md) for current authoring capabilities and the experimental6mm admission change.

Audited September 6, 2026 from the current source tree. This is a bounded
read-only audit of the experiment platform; it does not add a physics claim or
qualify a realtime solver.

## What the current backend actually supports

### Implemented

- The playground accepts `panel_impact`, `plate_drop`, `rigid_drop`,
  `knife_cut`, `custom_objects`, the fixed thermal/material references, the
  fixed continuum pressure reference, and an explicit `unsupported` result.
  The request is structured data and is validated before native execution.
  Evidence: `playground/experiment_language.py`,
  `playground/server.py`, `playground/README.md`.
- Rigid custom scenes can contain up to twelve preset objects with bounded
  positions, velocities and dimensions. The network runtime supports rigid
  spheres and boxes, plus network boxes/ellipsoids; wedges remain rigid.
  Evidence: `playground/experiment_language.py`,
  `examples/authoring/banjo_authoring.py`, `src/platform/NetworkWorld.cpp`.
- The fixed pressure route performs small-strain quasistatic load/unload on
  matched glass/oak/iron coupons. It reports displacement, reactions, elastic
  and plastic work, and retained history. This is an implemented reference
  computation, not a dynamic impact path. Evidence:
  `docs/continuum-pressure-checkpoint.md`, `tools/continuum_patch_probe.cpp`,
  `src/physics/SmallStrainPatch.cpp`.
- The compiled-impact backend accepts an integer per-object seed and uses it
  in the compiled material field. Same seed and topology are deterministic;
  changing seed changes the field. Evidence: `src/platform/PlatformWorld.cpp`,
  `src/platform/CompiledRuntime.cpp`, `tests/compiled_object_tests.cpp`.

### Experimental or bounded

- Network panels use an occupied-cell cohesive lattice with optional boundary
  pinning. Each network axis is admitted at resolution 2..16, each object is
  capped at 800 cells, and the runtime world is capped at 1,024 cells and
  20,000 links. The playground applies a stricter 850-cell package admission
  bound, at most four sweep cases, three simulated seconds per mechanical case,
  one active job, and a 75-second native process timeout. Evidence:
  `src/platform/NetworkWorld.cpp`, `src/platform/PlatformWorld.cpp`,
  `playground/experiment_language.py`, `playground/README.md`.
- Network damage can update cohesive state, break links, preserve connected
  components, and report plastic/fracture bookkeeping. It is explicitly an
  experimental central-force directional lattice: no continuum calibration,
  no spatial convergence, no local refinement or rigid re-coarsening, and no
  complete contact/energy closure. Strict damage integration rejects unresolved
  trials instead of inventing fragments. Evidence: `src/platform/NetworkWorld.cpp`,
  `docs/network-runtime-checkpoint.md`, `docs/embedded-playground-checkpoint.md`.
- The pressure coupon allows only even resolutions 4..12, 2..64 load increments,
  and peak pressure 1..1e9 Pa. Its geometry and supports are fixed at 40 x 20 x
  40 mm, with a central 20 x 20 mm patch and bottom clamp. Mesh studies show
  strong displacement dependence; high-load oak can terminate at a declared
  strain/gradient limit. Evidence: `playground/experiment_language.py`,
  `playground/server.py`, `docs/continuum-pressure-checkpoint.md`.
- Playback is recorded native output with browser controls. The browser does
  not integrate a live world, and `realtime_guaranteed` is false. Timing fields
  are diagnostic single-run measurements rather than p95/p99 qualification.
  Evidence: `playground/README.md`, `docs/embedded-playground-checkpoint.md`,
  `src/platform/PlatformWorld.cpp`.

### Missing or explicitly unsupported

- Thin or tempered-glass impact/shatter is not admitted by the current
  playground panel route. Its wrapper requires panel thickness 0.012..0.15 m
  and panel sides 0.08..1 m; the direct network loader accepts dimensions down
  to 0.004 m, so a 6 mm declaration can be syntactically admitted in a direct
  package at a coarse resolution. That does not make it a thin-shell model:
  cell size, contact proxy size and unresolved elastic-wave peaks still bound
  the result, and no calibrated shatter law exists. The 6 mm tempered-glass
  item is therefore a documentation/reference request only in the current
  product route. No thicker panel may be silently substituted. Evidence:
  `playground/experiment_language.py`, `src/platform/NetworkWorld.cpp`,
  `playground/README.md`,
  `docs/glass-drop-benchmark.md`.
- Collision-driven J2 dents are not integrated with dynamic contact, and the
  pressure coupon has no inertia, collision or fracture. Evidence:
  `docs/continuum-pressure-checkpoint.md`,
  `docs/embedded-playground-checkpoint.md`.
- Calibrated cutting, complete tomato slicing, full wood grain/plasticity,
  hinge failure, fluids, pulp/skin pressure, airflow and arbitrary liquid flow
  are unsupported. The existing knife/tomato route is a coarse proxy and
  reports partial damage only. Evidence: `playground/experiment_language.py`,
  `src/platform/NetworkWorld.cpp`, `playground/README.md`.
- Seeded stochastic requests are not part of the playground schema: the
  generated `custom_objects` declaration has no `seed` field, while seeds are
  accepted only by `compiled-impact-v1`. A request asking for a reproducible
  random field therefore needs a new bounded seed field and backend routing;
  it must not be implied by a request ID. Evidence:
  `playground/experiment_language.py`, `src/platform/PlatformWorld.cpp`.

## Shortest sound next integration

The shortest path that connects impact, deformation and fracture is a single
small, seedable clamped-panel fixture on the existing network runtime, with a
shared per-tick transaction and one report schema. Keep the current matched
glass/oak/iron panel geometry and `pin_boundary`; add an explicit integer seed
to the playground declaration, pass it through package compilation, and record
the seed, resolution, cell/link counts, contact impulse, displacement, broken
links, plastic/fracture work, rollback/limit status and residuals. Use the
existing strict rejection policy when a trial cannot resolve.

That integration should first exercise a rigid projectile contacting the active
panel, then apply the resulting contact load to the same panel cells, then
advance cohesive/plastic state and rebuild the surviving skin. The acceptance
fixture should include no-break, deformation-only and fracture cases under the
same declared geometry for glass, oak and iron. It should compare two spatial
resolutions and two timesteps, and report when the result is unresolved. This
joins existing mechanisms without pretending the pressure coupon is dynamic or
that the current lattice is a calibrated thin plate.

Do not make thin-plate shatter or calibrated cutting part of this first step.
They require separate calibrated laws, geometry/contact resolution and
convergence evidence. Do not label the resulting playback realtime until a
repeatable wall-clock budget is measured for the complete path.

## Eight seedable request categories for a general experiment interface

These are request categories for the eventual bounded language. “Seedable”
means the request carries an explicit integer seed and reports it; only the
compiled backend currently implements that field. Categories marked
experimental should return native limit diagnostics rather than a visual
fallback.

| Category | Example request shape | Current status |
|---|---|---|
| 1. Custom rigid layout | “Seed 17: place an iron ball, glass box and oak box with these SI poses and velocities.” | Implemented through `custom_objects`; seed plumbing missing in playground. |
| 2. Rigid drop | “Seed 17: drop an iron cube from 0.25 m onto matched rigid glass/oak/iron boxes.” | Implemented bounded `rigid_drop`; fracture disabled by design. |
| 3. Clamped panel impact | “Seed 17: impact matched pinned panels at 2 and 6 m/s; report contact, deformation and damage.” | Experimental `panel_impact`; current lattice is not calibrated or spatially converged. |
| 4. Clamped panel drop | “Seed 17: drop an iron ball from 0.25 and 1 m onto pinned panels.” | Experimental `plate_drop`; bounded height 0..2 m and strict solver limits. |
| 5. Spatial pressure | “Seed 17: run 200 MPa pressure load/unload and report springback.” | Implemented fixed quasistatic reference; seed has no physical effect there. |
| 6. Calibrated cutting | “Seed 17: cut a 6 mm tempered pane or calibrated tomato and report the cut path.” | Unsupported; current knife/tomato is a coarse partial-damage proxy. |
| 7. Thin-plate shatter | “Seed 17: impact a 6 mm tempered window and predict shards.” | Unsupported/reference-only; no thin-glass substitution or shatter animation. |
| 8. Fluids and coupled fields | “Seed 17: pour water through a damaged panel or add airflow/pressure coupling.” | Unsupported; thermal frontier is a fixed reference and has no fluid flow or mechanical weakening. |

The common request contract should retain the existing SI bounds, explicit
unsupported status, fresh-run identity and native report provenance. A seed
must be part of the compiled physical key whenever it affects generated matter;
it cannot be treated as a display or playback control.
