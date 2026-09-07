# Playground admission and cost checkpoint

Date: 2026-09-07. Branch `agent/playground-rebuild`, local only.
Scope: authoring and UI. No solver behaviour, material constant or tolerance was
changed. Admission is not calibration; every native report in this checkpoint
still says `physical_response_validated: false`.

## The defect

The authoring layer knew one of the network engine's limits, the 1 mm collision
radius, and none of the others. The planner was told nothing about cell shape,
cell budgets or cost, and its documented drop default (`resolution [4,4,2]` on a
`[.24,.36,.04]` target) produced 4.5:1 cells. The engine gives every network
cell a spherical collision proxy of radius `0.49 * min(spacing)` while that cell
carries the mass and inertia of the whole box (`src/platform/NetworkWorld.cpp`
line ~236), so at 4.5:1 the proxy spans 22% of the cell's widest side and
fragments pass through each other. The playground could therefore author scenes
the engine refuses, and scenes it accepts but should not.

Separately, the network's stability clock (`network_substepping`) makes cost a
function of the smallest cell, and nothing told the user what a run would cost
before they waited for it.

## Limits now mirrored in `playground/network_admission.py`

| Limit | Value | Enforced by |
| --- | --- | --- |
| Resolution per axis | 2..16 (2..12 through the drop/scene routes) | `NetworkWorld.cpp` `integer(o["resolution"][i],2,16)` |
| Cells per object | 800 | `require(nx*ny*nz<=800, ...)` |
| Cells per world | 1024 | `require(w.nodes.size()<1024, ...)` |
| Cells in the playground | 850 | `drop_builder`, `scene_composer`, `compile_plan` |
| Cell aspect ratio | 2.0:1 | `banjo_authoring.validate_network_geometry` |
| Collision proxy radius | >= 1 mm, i.e. spacing >= 2.0408 mm | `require(radius>=.001, ...)` |
| Substeps per host tick | <= 8192, `ceil(omega*dt/0.2)` | `kMaximumStabilitySubsteps`, `kStabilityPhaseRadians` |
| Recording | <= 64 MiB, <= ~122 frames | `tools/playground_record.cpp` |

**Face:thickness ceiling.** The consequence usually quoted is 16/2 = 8:1, which
assumes strictly cubic cells. The admission rule tolerates cells up to 2:1, and
that tolerance multiplies: `Dmax/Dmin <= aspect * nmax/nmin`, so the real ceiling
is **16:1 through the engine and 12:1 through the drop and scene routes**. Both
figures are reported. Either way a real windowpane (30:1 and up) is not
expressible from uniform cells, and the playground now says so instead of
building something else. With the drop route's 283-cell-per-lane budget the
thinnest buildable drop target is 8 mm at 80 x 80 mm sides, and 30 mm at the
default 240 x 360 mm face.

## The substep model is exact

`network_admission.package_substeps` rebuilds the lattice the engine builds --
the 18-neighbour stencil, `stiffness = E_dir * volume^(2/3)/6 / rest_length`,
`mass = density * volume` -- and evaluates
`omega = sqrt(2 * max_i sum_j k_ij/m_i)`, `substeps = ceil(omega*dt/0.2)`.

It reproduces the substep count in **13 of 13** native reports exactly:

| Recording | Cells | Model | Native |
| --- | --- | --- | --- |
| drop-sweep 8 mm x3 heights | 192 | 1587 | 1587 |
| drop-sweep 12 mm x3 heights | 192 | 1377 | 1377 |
| drop-sweep 20 mm x3 heights | 192 | 1176 | 1176 |
| calibration small-32 | 32 | 1299 | 1299 |
| calibration mid-108 | 108 | 1514 | 1514 |
| calibration cube-125 | 125 | 1514 | 1514 |
| calibration large-256 | 256 | 1514 | 1514 |

The boundary matters: with two cells through the thickness every node is on a
face and loses one z neighbour and half its z diagonals. Using the interior
stencil for the 8 mm plate predicts 2024 rather than the measured 1587, so the
model walks the actual grid.

`tests/network_admission_tests.py` keeps a native parity case that runs one tick
through `banjo_platform_cli` and compares against `network_substepping`.

## The wall-time model, and how wrong it is

Timed end to end on this machine (Windows, `build/win-joint-double/Release`),
four near-cubic glass recordings:

| Cells | Bonds | Steps x substeps | Measured | Model | Error |
| --- | --- | --- | --- | --- | --- |
| 32 | 148 | 77,940 | 25.2 s | 27.9 s | +10.7% |
| 108 | 642 | 90,840 | 116.7 s | 109.7 s | -6.0% |
| 125 | 780 | 90,840 | 135.0 s | 127.0 s | -6.0% |
| 256 | 1704 | 90,840 | 253.5 s | 260.0 s | +2.6% |

Cost per internal solve is proportional to the cell count across that 8x range,
so the model is one constant: **11.18 us per network cell per internal solve**,
times cells x substeps x steps. Adding a per-bond term makes the fit worse.
Two further recordings made through the finished builder path, start to
finish in the browser and the server, substep count exact in both:

| Scene | Steps | Measured | Model | Error |
| --- | --- | --- | --- | --- |
| glass 80x80x40 mm, [2,2,2], 3 m/s | 115 | 6.5 s | 5.9 s | +10.9% |
| glass 240x360x40 mm, [6,9,2], 2 m/s (the shipped default) | 115 | 91.0 s | 109.3 s | -16.7% |

The constant is a throughput measurement of one machine, not physics. It
**over-predicts strongly anisotropic lattices**: the nine drop-sweep recordings
at 7.5:1 to 3:1 come in 65-107% below it, because non-cubic collision proxies
never touch and those scenes pay almost no cell-to-cell contact cost. That
geometry is no longer authorable, and erring conservative on the geometry that
is authorable is the right direction. The UI shows a +-35% band, not a point.

## What the playground now does

1. **The planner is told the limits and the reason for each** (`SYSTEM` in
   `playground/experiment_language.py`): cubic cells and why the proxy makes it
   necessary, the resolution bounds, the face:thickness consequence with the
   windowpane example, the three cell budgets, the spacing floor, and that cost
   scales as 1/spacing with the measured 1587-substep example. Its drop default
   is now `[6,9,2]` (40 x 40 x 20 mm cells) instead of `[4,4,2]`.
2. **Every plan is admitted before it is compiled** (`admit_plan`). A repairable
   mesh is snapped to the nearest admissible resolution -- nearest by change to
   what was asked, then by cell count, so a repair does not quietly become an
   expensive run -- and the change is recorded on the plan in `admission_notes`
   and shown in the UI. Dimensions are never changed. An unrepairable geometry
   is refused by name with both ways out.
3. **Cost is computed before the run** and shown in the job card and the builder
   panel: substeps per tick, internal solves, estimated wall time with a band,
   and the estimated recording size against the recorder's 64 MiB ceiling (which
   it otherwise enforces only after doing all the work).
4. **A builder panel** (`Builder` tab) exposes material, target size, resolution,
   support, striker kind/size/speed/offset, duration and host tick rate, with
   live cell count, spacing, aspect, coverage, slenderness and cost. Every value
   shown comes from `POST /api/builder/preview` rather than a copy of the rules
   in JavaScript, and `POST /api/packages/run` re-checks admission server-side,
   so the Run button cannot start a scene the engine would refuse.

## Worked example

Requested: 240 x 360 x 4 mm glass at `[6,9,2]` -- a windowpane.

```
Drop target: [0.24, 0.36, 0.004] m is 90.0:1 face-to-thickness. Cells have to
stay within 2:1 of cubic to collide correctly, and each axis takes 2..12 cells,
so a uniform-cell object cannot exceed 12:1 (6:1 with strictly cubic cells).
The nearest buildable versions are 0.03 m thick at this face size, or a 0.048 m
face at this thickness. No substitute geometry was run.
```

Requested: 240 x 360 x 40 mm glass at `[4,4,2]` -- repairable.

```
cell_aspect_ratio / snapped: Drop target: resolution [4, 4, 2] would have made
4.50:1 cells, and the engine gives every cell a spherical collision proxy of
radius 0.49 x the smallest spacing while it carries the mass of the whole box,
so those cells would have collided over only 22% of their widest side. Snapped
to [6, 9, 2] (2.00:1, 108 cells). The requested dimensions were not changed.
```

## What still does not work

- **Admission is not calibration.** Nothing here makes a fracture result
  trustworthy. The at-rest control in the Results tab remains the check that
  matters, and the report still says `physical_response_validated: false`.
- **The 2:1 cell tolerance is itself unvalidated.** It comes from the range the
  shipped presets happen to use (1.0 to 2.0), not from a measurement of when the
  proxy stops representing its cell. The right experiment is a sweep of aspect
  ratio against momentum transfer through a fragment boundary; it has not been
  run.
- **Cost ignores contact and fragmentation.** The constant was fitted to scenes
  that mostly stay intact. A scene that shatters into many contacting fragments
  will cost more than the estimate, so it is a floor.
- **The wall-time constant is machine-specific** and will be wrong on other
  hardware. The substep count, which is the part that varies over orders of
  magnitude, is not.
- **The legacy `custom_objects` route can still exceed the world budget** when a
  single preset is duplicated many times: admission repairs each object's mesh
  and enforces the 850-cell total, but the route's own twelve-object cap is what
  bounds it, not a per-object cost check.
- `tests/playground_record_tests.py` still times out on its 480-step network
  case after the stability-clock change, and `tests/playground_logging_tests.py`
  only imports when run from `tests/`. Both predate this branch.
