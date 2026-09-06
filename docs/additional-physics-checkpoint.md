# Bounded thermal activation and experimental damage trials

September 6, 2026; developed from main `293db93`. Windows MSVC 1944 Release,
Jolt 5.6 with double positions, raylib 6. This checkpoint adds working sparse
thermal activation and mechanical diagnostic infrastructure. It does not
complete the physics platform or validate the material-network fracture model.

## Implemented

`SparseThermalWorld` can opt a region into bounded six-face cold-neighbor
activation. A rotating probe cursor and candidate queue inspect only nearby
addresses. Promotion retains stored mass, thermal/latent energy, fuel, oxygen
and products, with a separate cold-to-active ledger. Newly admitted cells
conduct on the region's clock. The scheduler stages only the local region and
new index nodes, charges logical staging/probe/initialization/solve operations,
and publishes the entire job atomically. Legacy insulated regions retain their
direct step path. Limits remain 512 cells per region and 32768 active cells
globally. The blocked-region receipt counts unique regions per call.

Deferred, uninspected and other-region faces remain insulated approximations.
Reported omitted heat rates are instantaneous estimates, not a global error
bound. There is no demotion, implicit region merge, cross-clock heat transfer,
flow, radiation or mechanical weakening. Fuel reaction uses illustrative
constants and finite local oxygen, without airflow or validated combustion.

`material-network-v2` gains optional endpoint damage trials: attempt a coupled
contact/spring step, rewind and bisect if a sampled material increment exceeds
its target, then commit accepted material state before continuing. The new
Jolt spring transaction preserves configuration, removal lifetimes, exact
constraint order, contact caches, bodies, events and solver time. An outer
rejection also restores material history, work, topology, skin revisions and
the public tick. Changed spring settings now reset cached warm-start impulses;
identical float configurations preserve them.

The API defaults to **strict rejection** on an unresolved depth limit.
`on_limit: "report"` is an explicit diagnostic option. It exposes actual
accepted maxima and violations, and can produce unstable, nonphysical results.
The algorithm samples endpoints and does not detect every transient peak or
estimate full state/contact/work error. It snapshots the entire admitted
network, so this is not automatic local mechanical refinement.

## Comparative thermal results

The checked-in `assets/world-v1/thermal-frontier.json` uses 1 cm voxels,
.05 s thermal steps, a 5 K wake threshold, 256 face probes and at most 8
admissions per region job. Glass, oak and iron each start with four 650 K
cells in 293.15 K material. Heater work uses the model's solid-mass heat
capacity; the finite trapped-oxygen reservoir adds mass without changing that
declared reference capacity. The water case starts with four 363.15 K liquid
cells beside pure ice at 273.15 K, so neighboring ice melts during playback.

At 10 s, glass/oak/iron/water have 40/40/240/16 active cells respectively.
Their peak temperatures are approximately 603.74/1554.12/311.19/350.06 K.
Oak has released 4480 J from finite fuel. Water has 4.657 g liquid, up from
4 g initially. Mass and chemical-plus-thermal energy transfer are accounted
for; the maximum summed active energy residual is about 1.04e-9 J.

Three serial repeats at each storage size gave identical accepted local
physics. With 336 active cells, median headless advance p95 was approximately
0.36–0.37 ms at 16384, 1048576 and 16777216 stored voxels. This measures
thermal jobs, excludes rendering, and does not represent millions of active
physics bodies. A deliberately insufficient 1000-operation budget retained
88 active cells and reported three late regions, about 9.85 s maximum lag,
and pending candidate age instead of dropping requested time. Payload
accounting includes pending face records but excludes allocator/capacity
overhead. Wall deadlines are soft checks between bounded atomic jobs.

Reproduce with `examples/authoring/measure_thermal_frontier.py --engine
<banjo_world_cli> --output <new-directory> --repeats 3`. The script also checks
matched initial seed temperatures, exact storage-independent outcomes,
energy residuals, zero cold-world scans and unique blocked-region receipts.

## Mechanical findings and failed accuracy gate

The four original scene controls still run. At 2/6/12 m/s, glass/oak/iron
panel break counts are now 0/0/0, 0/0/0 and 0/9/0; the knife/tissue control
has 18 broken links. The spring-cache correction changed the 12 m/s oak
count from the previous checkpoint's 24 to 9. That is a numerical correction,
not a calibration result.

Three repeated equal-time 3 s comparisons produced these deterministic
same-build outcomes. All adaptive rows below explicitly used diagnostic
`on_limit: "report"`; the checked-in studio trials now use strict rejection.

| Scene / step / depth | Glass / oak / iron broken links, or tissue links | Limited substeps | Median physics total | Median step p95 |
|---|---:|---:|---:|---:|
| Panels 12 m/s, 1/480 s, off | 0 / 9 / 0 | 0 | 780 ms | .980 ms |
| Panels 12 m/s, 1/480 s, 2 | 5 / 61 / 0 | 10 | 2043 ms | 2.301 ms |
| Panels 12 m/s, 1/480 s, 4 | 475 / 446 / 0 | 82 | 2023 ms | 1.946 ms |
| Panels 12 m/s, 1/960 s, 4 | 473 / 349 / 0 | 204 | 3884 ms | 1.778 ms |
| Knife/tissue, 1/480 s, off | 18 | 0 | 1342 ms | 1.301 ms |
| Knife/tissue, 1/480 s, 2 | 20 | 56 | 2842 ms | 3.208 ms |
| Knife/tissue, 1/480 s, 4 | 22 | 44 | 3179 ms | 2.807 ms |
| Knife/tissue, 1/960 s, 4 | 27 | 2 | 5667 ms | 3.214 ms |

**Deeper panel refinement fails energy accuracy.** The depth-4, 1/480 s
panel run starts at 543.82 J, finishes with 17200.48 J mechanical energy,
and reports +20531.54 J unseparated energy change after the other stores.
Accepted brittle opening overshoot reaches 16.89 times its threshold, versus
a .05 target. More fragments here are evidence of failure, not realistic
shattering. Peak single steps reached about 52 ms. A live diagnostic 6 m/s
case also produced excessive fragmentation. Full conservation is not closed;
the report deliberately leaves `energy_residual_j` null.

`assets/damage-integration/` now contains strict depth-2 visual trials. The
2 m/s trial completes; 6/12 m/s and the tissue trial stop with an explicit
limit error and roll back the offending tick. The unrestricted matrix remains
reproducible through `measure_damage_integration.py` for diagnosing the defect.

## Verification and visual evidence

All 52 CTest suites passed together in 83.28 s. Focused suites passed again
after final strict-default, receipt and diagnostic changes. New coverage
includes exact glass/oak/iron Jolt rollback replay; accepted inner changes
followed by outer rejection; spring changes versus a clean neutral coupled
chain at 2/24 iterations (zero measured state/impulse difference); complete
network-history and skin rollback; default-versus-depth-zero equivalence;
strict policy bounds; and mixed thermal, phase, stale-command, negative
cross-chunk, storage and preactivated-domain oracles.

Native heat-lab input was verified: pause, reset to 16 initial cells with
matched 650 K material seeds, release, further ice melting, pause and save.
The saved live run reached about 30.71 s, 390 active cells and 5.73 g liquid,
with no late regions and energy residual about 1.5e-9 J. The studio Release
button was also observed advancing the 12 m/s panel diagnostic. Rendering
does not establish material realism or input-latency/GPU guarantees.

## Next gates and retained scope

- G02: embed a state/work error estimator, resolve contact and stress-wave
  peaks, and qualify time/space/iteration refinement. Add physical glass
  manufacturing state, including residual stress for tempered glass, and
  richer wood bending/shear/grain behavior. Never infer physical truth from
  the relative broken-link counts in this coarse lattice.
- G03: bound omitted boundary heat error, refine wake thresholds and field
  timesteps, then add conservative cooling/demotion and cross-clock exchange.
- G04/G05: unify state and transfer ledgers, then qualify local mechanical
  activation and mixed-world budgets. Thermal storage scaling does not pass
  the mechanical performance gate.

All M01–M30 and P01–P10 remain retained. G01/G02/G03/G05 remain active;
G04/G06 remain queued. No full goal is complete.
