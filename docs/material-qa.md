# Material impact range and refinement boundary

Start with the gentle/hard [demonstration sets](qa-demonstrations.md), or follow
**Use a pick** to recorded tool use. New material runs verify centered opening
geometry; playback now frames the full trajectory and describes the outcome.

The material QA area is at **/qa**, linked from the Physics lab, World and Workshop. It records
controlled native impacts. Select material, thickness and speed, orbit the
specimen, slow the crack frames, step frame by frame and inspect measurements.
It uses the detailed lattice solver in isolated processes without opening or
resetting the live world. No scripted fragments; game laws and limits unchanged.

## Publishing to a local sim

Use the same server for Workshop, World and the material range. Open `/qa`
from its navigation. The viewer opens the newest full matrix by
default among completed matrices; the run picker includes case counts and retains later partial runs. A newer
completed full run remains the default even when it fails, so regressions stay visible.

Build `banjo_platform_cli`, `banjo_live_world_run` and
`banjo_fast_lattice_run` together. Pass the platform executable with
`--engine`; the QA runner must be beside it. The server discovers evidence
under `<runs>/material-qa/<run-id>/`. Copy complete run directories there to
publish existing recordings; copying does not re-run or re-date the evidence.
Use the original `--rooms` and `--runs` directories when updating a local
server so saved worlds and the Workshop library remain available. Do not
overwrite existing evidence or room files with a demonstration.

The local September 19 publication uses port 8793, with all 96 baseline
recordings and selected repeat runs. This is a local UI/deployment checkpoint;
the model boundaries and qualification limits below still apply. The published
server passed a fresh browser-triggered glass impact against the baseline;
playback, World/Workshop navigation and the saved building room were checked.
The source checkpoint passed 12 QA tests, nine API/documentation checks and
the source-registration guard. Existing saved data paths were retained.

## One intact brick, detail when needed

Yes: an intact brick should normally be **one rigid body** with its real shape,
mass, centre of mass, inertia, temperature, connection loads and persistent
damage state. A literal oversized deforming voxel would erase bending modes
and change the meaning of its material law.

LiveWorld already uses rigid motion and admits detailed fracture after load or
impact screening. But it builds fine nodes, bonds and plastic-history arrays at
world creation. This checkpoint does **not** implement lazy allocation.
See [the wall and 160k experiment](building-sledgehammer-checkpoint.md) for the
measured cost of that distinction.

The remaining refinement contract is:

1. Keep cheap stress/load/damage checks active while rigid. Refine when damage
   becomes plausible, before accepting the damaging step. A brick may crack
   internally while still being one connected object.
2. Allocate detail for the affected brick and relevant contacts under explicit
   cell and work budgets. Preserve component identities and joint anchors.
3. Transfer mass, momentum, stored energy, temperature, damage and plastic
   history. Account for unresolved internal motion when reducing detail again.
4. Retain cracked connected bodies as well as separated pieces. Store damage
   sparsely or as durable detailed state. Changing detail cannot repair it.
5. Expose pending/refused refinement on budget exhaustion, retaining state.
   Do not force a shatter or apply a duplicate contact impulse.
6. Compare against eager reference runs before enabling lazy allocation.
   Add live trigger, static load, repeated strike, mount reaction, save/reload,
   handoff conservation and budget-exhaustion tests.

This suite supplies reference damage experiments. It does not test every
refinement transfer or the live trigger. The glass discrepancy and building
cascade/save refusal from the wall checkpoint remain open.

## Fixed experiment

All eight current catalog materials are included: glass, oak, iron, concrete,
ceramic, ice, aluminum and rubber.

| Parameter | Value |
|---|---|
| Sample plan | 120 × 120 mm |
| Thicknesses | 20, 40, 80 mm |
| Cell spacing | 10 mm; 2, 4, 8 cells through thickness |
| Striker | 40 mm diameter iron sphere; native density determines mass |
| Initial downward speeds | 1, 4, 12, 30 m/s |
| Initial clearance | 2 mm above specimen |
| Support | Two ledges, 80 mm high and 20 mm wide |
| Solver | CPU double reference, horizon 2 cells, dt factor 0.5 |
| Damage law | Strain threshold; axial plastic flow off |
| Exit controls | 3 ms removed-energy plateau; 5 ms calm screen |
| Rigid aftermath | Up to 0.35 s; not required to come to rest |
| Bound | 90 wall seconds per native process; one process at a time |

There are 96 independent specimens. Speeds are initial conditions, not
continually imposed velocities. Reports contain striker mass, initial kinetic
energy, accumulated contact impulse, damage, fragments, largest mass fraction,
removed bond energy, timestep and compute time. **Peak impact force is
unavailable**, not zero. Dividing impulse by an arbitrary time is not a peak
force measurement.

Plastic flow is off to match this elastic/damage reference lane. These tests
do not establish realistic metal denting, oak grain, rubber hyperelasticity,
fatigue, firing/mortar properties or thermal fracture. Thinner glass needs a
finer fixture and a convergence study. Concrete is not calibrated fired clay.

The first fixture used a 1 ms calm screen. All 24 cases at 1 m/s exited detail
before striker contact and correctly failed. The QA fixture now waits longer;
the product's exit rules are unchanged. Raw failed evidence is retained locally.

## Run after physics changes

Build the native runner, then from the repository root:

~~~sh
python scripts/material_qa.py --engine build/ci/banjo_fast_lattice_run --out build/material-qa/new-run
~~~

On Windows use the Release banjo_fast_lattice_run.exe (or an adjacent engine).
--case glass-20mm-12mps selects one case and may be repeated. Omit for all 96.

The command compares against
[evidence/material-qa-baseline.json](evidence/material-qa-baseline.json), exiting
nonzero on numerical/recording failure or a change outside the regression bands.
CI runs the complete matrix on every push and pull request after the native
build and retains evidence even on failure. Remote CI execution is separate
evidence from local Windows runs.

Each run saves a fixture hash, source checkout revision and dirty flag,
executable SHA-256, requests, stdout/stderr, native reports, geometry recordings
and case results. The executable is not assumed to match the checkout revision.
The runner refuses to overwrite an evidence directory. --no-baseline measures
an initial run; it **does not accept or update a baseline**.

Hard checks cover finite output, expected cell count, positive masses, initial
striker kinetic energy, actual contact, valid damage counts, no contact-buffer
overflow and ordered playback preserving every specimen-cell identity.
Cell identities represent retained material volume, not a complete energy or
momentum audit.

Outcome changes (intact/cracked/fragmented) and these differences require review.
The allowed difference is the larger of the absolute and relative band:

| Quantity | Absolute band | Relative band |
|---|---:|---:|
| Specimen and striker mass | 1e-9 kg | 1e-9 |
| Broken-bond fraction | 0.03 | 20% |
| Largest mass fraction | 0.10 | 15% |
| Removed bond energy | 0.03 J | 20% |
| Contact impulse magnitude | 0.03 N·s | 20% |

These broad change-detection bands are not calibration error bars. Exact
fragment count is displayed, not used as a converged oracle. Review recordings
and physical changes before committing a replacement baseline; a different
fixture requires a new reviewed baseline. Warnings, including the known
negative signed striker-loss diagnostic, remain visible. Passing is not proof
of full-system conservation or material realism.

## Measured checkpoint, September 19

Windows Release native runner, CPU double; source checkout a98b75a and the
executable hash are retained with the baseline. All 96 cases completed and
passed the numerical/recording checks in 418.54 wall seconds (sum of case times).
There were 60 intact, 11 cracked-but-connected and 25 fragmented results.
The raw recordings total about 600 MiB; CI artifact compression reduces transfer
size but the evidence remains an intentionally bounded laboratory workload.

| Material | Intact | Cracked, one piece | Fragmented |
|---|---:|---:|---:|
| glass | 6 | 2 | 4 |
| oak | 6 | 2 | 4 |
| iron | 9 | 3 | 0 |
| concrete | 2 | 0 | 10 |
| ceramic | 12 | 0 | 0 |
| ice | 4 | 1 | 7 |
| aluminum | 9 | 3 | 0 |
| rubber | 12 | 0 | 0 |

The signed striker-loss diagnostic was negative in 87 cases and is explicitly
shown as a warning. These results do not close the energy ledger. No constitutive
law was changed to make a specimen break. Passing here means the stated
structural checks passed; it does not certify realism.

Twelve QA lifecycle/API tests, nine API/documentation checks, 34 playground checks,
seven workbench checks and the 275-source registration guard passed locally.
Eleven native repeat cases covering all eight materials, all three thicknesses
and a corrected low-speed impact passed comparison against the baseline.
Browser verification rendered and played native glass fragments with no console
warnings/errors. Running a selected case from the browser completed and matched
the baseline. Remote CI and full-engine qualification are separate work.

## HTTP API

Browser, CLI and platform MCP share the backend. Normal Host/origin checks,
password gate and X-Banjo-Token authentication apply. POST bodies are JSON.

| Method and path | Payload / result |
|---|---|
| `GET /api/material-qa` | Matrix, fixture, limits, engine/baseline availability |
| `GET /api/material-qa/runs` | Most recent 50 saved runs |
| `POST /api/material-qa/run` | {} or {"case_ids":["glass-20mm-12mps"]}; 202 id/status |
| `GET /api/material-qa/runs/<id>` | Progress, active case, results and provenance |
| `GET /api/material-qa/runs/<id>/<case>` | Measurements, issues and baseline changes |
| `GET /api/material-qa/runs/<id>/<case>/native` | Unmodified native report |
| `GET /api/material-qa/runs/<id>/<case>/playback` | banjo.playback.v1 recording, at most 64 MiB |
| `POST /api/material-qa/cancel` | {"run_id":"<id>"}; stop child, retain completed evidence |

IDs are 32 lowercase hex characters; cases must come from the catalog.
Clients cannot supply executables, paths, geometry or unlimited work.
One suite may run per application. Duplicate starts are refused. Cancellation
kills and reaps the child and keeps evidence. Graceful shutdown cancels the
suite. Running reports owned by another process (including CLI or a previous
server) are shown as unattached: the viewer cannot assert that runner stopped.
Statuses distinguish passed, review_required, failed, error, cancelled and
unattached. Missing engines/baselines, stale fixtures, bad inputs, timeouts,
nonfinite results and missing recordings cannot become a pass.

## MCP tools

The **platform MCP** adds these tools; the legacy world-only MCP does not.
Set BANJO_LIVE_ENGINE to the live executable with banjo_fast_lattice_run beside
it. BANJO_WORKSHOP_HOME controls its evidence root. To inspect the same saved
files in /qa, point the HTTP server's --runs at that MCP runs directory.

| Tool | Arguments and behavior |
|---|---|
| `material_qa_catalog` | No arguments; matrix and availability |
| `material_qa_run` | Optional case_ids; asynchronous isolated execution |
| `material_qa_status` | Optional run_id; progress or saved runs |
| `material_qa_case` | run_id, case_id; measurements, issues and changes |
| `material_qa_cancel` | run_id; cancel the active suite |

Python entry points in playground/material_qa.py are catalog, select, run_suite
and manager. No C ABI changed; adaptive allocation remains planned.
