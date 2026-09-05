# Live compiled material runtime v1

Experimental implementation, September 5, 2026. The new `compiled-impact-v1`
backend runs the bowl and comparative drop scenes live. This is a deliberately
reduced material model, not a claim that the earlier reference solver now runs
the same physics faster. The source checkpoint is the commit introducing this
note; the exported evidence manifest records its exact published revision.

## What now exists

- `src/platform/CompiledObject.*` compiles material-derived mass, COM, full
  inertia, a seeded spatial strength field, structural links and a reusable
  factorization. Spheres use 19 quadrature samples; boxes use 27 cubical cells.
- `src/platform/CompiledRuntime.*` keeps ordinary motion in rigid bodies. An
  observed impact with sufficient measured response and work allowance activates
  a 64-step local linear pulse predictor. It fails eligible links individually,
  re-solves the changed network, and retains surviving connections and damage.
- `src/rigid/JoltWorld.*` remains the contact response owner. Connected pieces
  become rigid compound bodies with inherited velocity and spin, preserving
  compiled mass/inertia without fragment launch kicks.
- `PlatformWorld` admits the new backend through the existing bounded SI JSON
  contract. `load`, `step`, `renderInstances`, `renderBonds`, `reportJson` and
  `packageJson` stay independent of rendering and inventory. Reports expose
  contact/fracture events, per-fragment poses and velocities, source sample
  membership, material results, transfer errors, timings and limits. A separated
  source object's COM/velocity are aggregated; its spin is null because pieces
  have independent rotations.
- `banjo_runtime_lab` displays eight initial-state packages from
  `assets/runtime-v1`. Release/pause, reset, next/previous experiment, quarter
  speed, frame stepping, structural inspection, report export and screenshot
  capture are available. There is no recorded trajectory or LLM call in stepping.

## Precisely which model is being tested

The compiler forms a central-force network from face and diagonal neighbors.
Link stiffness is `E*A/length`; separation work is `Gc*A`. The current area
rule is `cell_volume^(2/3)/6`. These are declared discretization choices,
not a calibrated continuum representation. A deterministic seed perturbs
strength through a smooth spatial field; it does not choose a shatter pattern.

The response factor solves `M + dt_local^2*K`. The currently named
`response_duration_s` is **one predictor step**, not the whole pulse:
`dt_local = pi/8 * sqrt(cell_mass/(E*cell_spacing))`. Each activation advances
64 steps. At each step, tensile strength and predicted elastic energy gate
failure; the strongest eligible energy/work ratio is selected. Removing a link
invalidates the factor, so the following solve uses the changed structure.
The contacted component can fracture again later using its surviving links.

The predictor's displacement and velocity are virtual local states. They do
not become a second contact impulse or physical elastic launch energy. The
predictor evolves during one activation; only flaws, connectivity and damage
persist between impacts. Boundary coupling to the supporting surface and
physical elastic-wave evolution remain future work.

Fracture work reclassifies a bounded portion of the same step's measured rigid
mechanical-energy loss. The allowance excludes the analytical semi-implicit
free-fall loss and is also bounded by an estimated normal collision loss.
Activation requires a measured normal momentum change, which prevents a
speculative contact callback alone from breaking a rolling ball. This is an
approximate attribution: concurrent contacts and numerical losses are not
fully separated. **The full energy residual is null**, not zero. No complete
external reaction/energy ledger is claimed.

Smooth intact spheres switch to coarse sample-sphere fragment proxies after
separation. Their mass and full inertia remain preserved, but their collision
surface changes. Box fragment cells tile the original box. Neither topology
is a high-resolution fracture surface; fragments may look beaded or blocky.

Glass enables the experimental brittle law. Oak and iron use their own
density and contact parameters but remain rigid: grain, plastic deformation,
and their fracture are unsupported. Material model capabilities, not display
names, select the implemented law. Required unsupported capabilities are
rejected.

## Measured comparative trials

Windows, MSVC Release, Jolt double positions / float velocities, Intel Core
Ultra 9 285K CPU. Each package ran for 3 simulated seconds at `1/480 s`, three
times. Physics timing includes rigid contact, local solves and fragment
replacement; it excludes loading, JSON reporting and rendering. Runs had
ordinary desktop scheduling, not an isolated benchmark environment.

Drop labels are **upper-body initial center heights above ground**. For the
45 mm spheres, the nominal centered travel to the lower sphere is height
minus 135 mm (45 mm lower-center height plus 90 mm center separation).
The 4 mm horizontal offset allows contact geometry to deflect
the falling body without a fabricated sideways impulse.

| Experiment | Glass broken links / final components | CPU physics for 3 s (range) | Step p95 (range) | Largest step |
|---|---:|---:|---:|---:|
| Iron drop, 0.15 m | 1 / 1 | 166.59–179.78 ms | 0.302–0.374 ms | 4.584 ms |
| Iron drop, 0.5 m | 56 / 4 | 163.82–201.24 ms | 0.281–0.456 ms | 6.427 ms |
| Iron drop, 1.5 m | 61 / 3 | 181.92–192.95 ms | 0.295–0.427 ms | 13.505 ms |
| Iron drop, 3 m | 63 / 5 | 209.50–214.13 ms | 0.379–0.421 ms | 14.561 ms |
| Cube drop, 1.5 m | 94 / 6 | 140.13–140.48 ms | 0.280–0.299 ms | 6.542 ms |
| Bowl | 52 / 4 | 311.11–332.65 ms | 0.619–0.676 ms | 9.583 ms |
| Zero-gravity free flight | 0 / 1 | 134.05–142.69 ms | 0.210–0.264 ms | 1.312 ms |
| 96-object load, 32 glass objects | 1086 / 56 total | 462.70–548.79 ms | 0.996–1.279 ms | 17.267 ms |

Outcomes matched across the three repetitions on this machine. This does
not establish cross-platform determinism. Oak and iron retained all links and
one component per source object in every trial. Free flight performed zero
local solves. The bowl had no failures in the first 0.5 s; its first failure
at 0.73125 s was attributed to the iron body contacting glass.

The largest measured fragment-transfer energy discrepancy across the 24
runs was `1.795e-7 J`. This measures representation handoff only, not full
trajectory conservation. Tests separately bound handoff mass, linear momentum
and energy. The 96-object fixture reported 211 budget-limited activations;
this combined counter includes insufficient available fracture work as well
as solver-count limits. It is not a count of missed rendering deadlines.

The admission limit is 128 initial objects, with at most 16 local activations,
64 predictor steps per activation and 64 accepted link failures per world
step. Excess damage stays unresolved and connectivity is retained. These
count limits do not guarantee a wall-clock deadline. Occasional long steps are retained in the table rather than discarded.
Thousands of simultaneous material interactions have not been validated.

## Verification and running it

All **36 CTest suites passed** (81.72 s). After the final fragment-state
report correction, the three affected compiler/runtime/platform suites passed
again (1.64 s). Coverage includes the new suites and the
existing reference, contact, inventory, creator and platform regressions.
New checks cover analytical sphere/box mass and inertia, seed stability,
progressive damage with changed-structure solves, irreversible links, free
flight, material boundaries, bowl contact attribution, handoff errors and
unsupported/oversized package rejection. A 1 micrometer free-flight position
bound permits accumulated float velocity/timestep rounding over 3 s; it is
not evidence of exact arithmetic or full physics convergence.

Native Windows inspection verified release, pause, quarter speed, one-frame
stepping and structure display. The 1.5 m drop displayed 61 failed links and
8 rigid bodies (3 glass components plus 5 unbroken comparison bodies), with
60 FPS observed. Measured average throughput and this focused native run are
evidence for the v1 slice, not proof of a game-wide frame budget.

```powershell
cmake --build build/win-joint-double --config Release --target banjo_runtime_lab banjo_platform_cli --parallel 4
ctest --test-dir build/win-joint-double -C Release --output-on-failure
python scripts/runtime_v1_matrix.py --repeat 3
& build/win-joint-double/Release/banjo_runtime_lab.exe assets/runtime-v1 03-iron-drop-1.5m.json
```

The matrix writes full reports and `summary.json` under
`build/runtime-v1-validation`. The lab exports `build/runtime-v1-report.json`
and `build/runtime-v1-lab.png`. These are local artifacts, excluded from Git.
The initial package export is not a live-state save.

## Next acceptance gates

1. Calibrate local response, work allocation, support coupling and resolution
   against the reference solver and physical data. Vary radius, speed, offset,
   shape, seed and support; retain glass/oak/iron in every applicable matrix.
2. Replace contact-loss estimation with attributable contact reactions and
   close the coupled work/momentum ledger, including transfer and numerical
   residuals. Separate work-limit and compute-limit telemetry.
3. Preserve collision geometry through splitting and add sparse local
   refinement/re-coarsening, stable fragment lineage and live-state saves.
4. Benchmark frame-level p95/p99 at increasing simultaneous-impact counts;
   compare inactive-world cost with active fracture cost. Optimize measured
   solver overhead before claiming thousands of material interactions.
5. Add wood grain/splitting and iron plasticity as actual constitutive laws.
   Only then train bounded local surrogates, with applicability checks and a
   measured fallback. No learned model or new programming language is required
   by this v1 runtime.

The retained platform requirements and next actions remain in the
[40-row mechanics scorecard](mechanics-scorecard.md).
