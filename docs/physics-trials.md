# Editable physics experiments and regression QA

September 19, 2026. Implemented first increment on base `f005056`.
Platform MCP **1.9.0**; legacy world MCP **1.6.0**; native ABI **25**.
This adds reusable experiment orchestration around existing native laws.
It does not change those laws or enable proposed joint-strength factors.

## Use the lab

Open **/mechanics-qa** from the Material QA page or Physics Lab. Select an
example, edit its JSON or ask the lab assistant to change it, validate, then
run. The assistant produces a validated declaration; it cannot execute code
or change the fixed regression catalog. Its proposal remains visible in the
editor until Run is pressed. Custom results are explicitly authored checks,
not engine qualification. The fixed suite runs from a separate button.

Playback uses recorded native body poses and dimensions. No scripted paths,
prescribed final velocities, precut fragments or result interpolation drive
the engine. Run artifacts retain the request, native command replies,
measurements, checkpoint snapshots, playback, source revision/dirty flag and
native executable SHA-256. Experiments have their own process and directory;
they do not replace the user's open world.

## Generic contract

`playground/physics_trials.py` validates and executes
`banjo.physics-trial.v1`. The same runner serves CLI, HTTP and MCP.
Fixtures are ordinary documents in
[regression.json](../examples/physics-trials/regression.json).
Object names are references, never switches selecting cart/door/bridge behavior.

Top-level required fields: `schema`, `title`, `cell_m`, `bodies`,
`steps`, `checks`. Optional `actuator` defaults to
`{"strength_n":100,"torque_n_m":10,"mass_kg":1}`.
Unknown fields, nonfinite values, booleans used as numbers, unknown references
and unsupported operations are rejected before starting a solver.

| Declaration | Meaning and bounds |
|---|---|
| Body `name` | Unique 1â€“48 character reference: starts with a letter, then letters, digits, space, underscore or hyphen |
| `shape`, `material` | box or sphere; an existing native material catalog id |
| `size_m` | Three dimensions, positive multiples of cell_m, at most 2 m each; sphere dimensions equal |
| `position_m`, optional `velocity_m_s` | World-space center in metres (each coordinate Â±10 m); initial velocity Â±10 m/s, default zero |
| Optional `anchored` | Boolean, default false; an external fixed support |
| `actuator` | Force 0â€“1000 N, torque 0â€“100 N m, virtual hand mass 0â€“50 kg; externally supplied work |
| `checks` | 1â€“32 final measurements, each with metric, optional body, inclusive min/max |

There are 1â€“16 bodies and at most 4096 bounding-box cells; cell_m is
0.02â€“0.1 m. Bodies start above the floor. Initial overlapping bounding boxes
are rejected conservatively, even for spheres. At most 48 operations and
5 simulated seconds are allowed, at a fixed 1/240 s timestep. Each advance
must be a positive whole number of timesteps. Native startup and blocked
reads share a 45-second wall deadline. Cancel/deadline terminate and reap
only the trial's owned child.

| Operation | Required fields besides op | Optional fields and native semantics |
|---|---|---|
| `fix` | a, b, at | axis defaults [0,1,0]; holds_tension_n and holds_shear_n default 0, meaning unlimited, maximum 1e9 N |
| `hinge` | a, b, at, axis | lower_deg/upper_deg default -180/180, must bracket zero within those bounds; friction_n_m default 0, maximum 1e6 |
| `slide` | a, b, at | axis defaults [0,1,0]; lower_m/upper_m default -1/1, bracket zero, at most 100 m travel; friction_n default 0, maximum 1e9 |
| `spring` | a, b, at_a, at_b | rest_m 0â€“100 (0 uses initial length); stiffness_n_m above 0 through 1e9, default 1000; damping_n_s_m 0â€“1e9, default 0 |
| `tie` | a, b, at_a, at_b | length_m 0â€“100 (0 uses initial separation); breaks_at_n 0â€“1e9 (0 unlimited); pulls only, slack exerts no force |
| `reeve` | a, b, at_a, at_b, over_a, over_b | Ideal pulley; ratio >0 through 100, default 1, multiplies B's run; length_m 0â€“500, default 0 uses initial runs |
| `unhinge` | joint | Release an earlier connection's symbolic id; native release removes the constraint, without deleting bodies |
| `sample` | label | Retain native bodies, joint readouts and measurements at this step; up to 16 unique labels |
| `wield` | name | grip is an optional world-space point, default body center |
| `move` | to | Target for an existing bounded grip; requests force, never assigns body position or velocity |
| `release` | â€” | Releases the bounded grip |
| `advance` | duration_s | Native time advancement; every tick and hand-force magnitude are observed |
| `checkpoint` | â€” | Native whole-world save, child restart and restore; release grip first; at most two |

Connection points, grip and target are world-space vectors in metres, with
coordinates Â±10. Axes are nonzero direction vectors. Connections reference
two distinct bodies and must be declared before any advance. Remaining
scalar operation fields must be finite numbers within Â±1e9 before the tighter
native validation above. These are laboratory initial conditions, not a
runtime welding/repair/manufacturing process.

Any connection operation may have an optional `id`: a unique 1â€“48 character
identifier starting with a letter, followed by letters/digits/underscore/hyphen.
`unhinge.joint` and joint checks refer to this ID, never a guessed native handle.
Sample labels use the same syntax. A check may have `sample` to read that earlier
observation instead of the final state. Unknown or forward references refuse.
Joint checks specify `joint` instead of `body`. Supported metrics are
`joint_attached` (0/1), `joint_tension_n` (fix/tie/reeve), `joint_span_m`
(spring/slide/tie/reeve), `joint_length_m` (tie/reeve), `joint_ratio` (reeve),
`joint_force_n` and `joint_stored_j` (spring). Unsupported metric/type pairs
refuse. A deliberately released joint reads attached=0; missing force data is
unavailable, never silently fabricated as zero. Results include `samples` and
`connection_ids`. Checkpoint validation additionally preserves rope length,
rating, ratio and fixed pulley routing points.

The 21 added comparative cases bring the suite to **44**: glass/oak/iron ropes
under load, slack, overload and deliberate release; and 2:1 ideal pulleys with
balanced, heavy and light counterweights. Equal geometry uses catalog density;
rope ratings scale with the declared weight. A .1-second slack test checks the
free fall against gravity before rope engagement. Native guide lines follow
attachment points and poses; they do not model cable sag or collision geometry.
Ideal pulley routing points are prescribed external supports, with no wheel
inertia, wrap friction or support-body reaction claim. Powered drum qualification
and general load-rated mount coupling remain separate work.

Body metrics: `mass_kg`, `speed_m_s`, `translational_kinetic_j`,
`position_x_m`, `position_y_m`, `position_z_m`,
`displacement_x_m`, `displacement_y_m`, `displacement_z_m`.
Displacement is relative to the initial pose. Kinetic energy is translation
only; it excludes rotation.

Global metrics: `elapsed_s`, `dynamic_mass_residual_kg`,
`active_joints`, `broken_joints`, `max_grip_force_n`,
`checkpoints`, `checkpoint_error`.
Mass residual is the sum of native reported dynamic masses after minus before;
anchored bodies report zero. It is not a full material inventory.
Checkpoint error is the maximum absolute numeric component difference across
time (s), dynamic mass (kg), position (m), velocity (m/s) and quaternion components.
The runner separately requires each to be â‰¤1e-7, unchanged body identities,
whole-world restoration and preserved joint identity/attachment/failure history.
This is a bounded restart check, not full thermodynamic state equivalence.
Force must stay within its cap plus 1e-5 N; dynamic mass may differ by at most
1e-8 kg; native elapsed time must agree with each requested tick within 1e-7 s.

## HTTP and MCP

POST requests use the existing Host/CSRF/access checks and X-Banjo-Token from
GET /api/status. The 32 KiB request-body limit remains in force.

| HTTP route | Contract |
|---|---|
| GET /api/mechanics-qa | Operations, limits, metrics, examples, fixed suite hash and native engine availability |
| POST /api/mechanics-qa/validate | {document}; returns valid:true and normalized document, no native execution |
| POST /api/mechanics-qa/plan | {message,document}; configured lab model returns document or null, explanation, model, response_id, usage and executed:false |
| POST /api/mechanics-qa/run | {} for all fixed cases, {case_ids:[...]} for a nonempty unique subset, or {document} for a custom trial; returns 202 with run id/status |
| GET /api/mechanics-qa/runs | Saved run summaries |
| GET /api/mechanics-qa/runs/{run_id} | Progress and measured results |
| GET /api/mechanics-qa/runs/{run_id}/{case_id} | Case result |
| GET /api/mechanics-qa/runs/{run_id}/{case_id}/request | Normalized executed declaration |
| GET /api/mechanics-qa/runs/{run_id}/{case_id}/playback | Native recorded poses and geometry |
| POST /api/mechanics-qa/cancel | {run_id}; requests cancellation of this manager's active run |

Run ids are generated 32-character lowercase hexadecimal names, not paths.
Case ids come from the fixed catalog or custom. One mechanics run is active per
server manager; saved artifacts live under runs/mechanics-qa. After server
restart, an unfinished run is reported as unattached, never passed.

| Platform MCP tool | Input/result |
|---|---|
| `physics_trial_catalog` | {} â†’ same catalog |
| `physics_trial_validate` | {document} â†’ same validator |
| `physics_trial_run` | {} / {case_ids} / {document} â†’ same asynchronous manager |
| `physics_trial_status` | {run_id} â†’ report; omit run_id to list runs |
| `physics_trial_case` | {run_id,case_id,artifact?}; artifact is result, request or playback |
| `physics_trial_cancel` | {run_id} â†’ cancel active owned trial |

These six tools are registered in mcp/banjo_platform_mcp.py; the legacy world
MCP remains unchanged. An external LLM uses catalog â†’ edit â†’ validate â†’ run â†’
status â†’ case, using the same physical contract as the browser. The browser's
optional model proposal endpoint is an editor convenience, not a separate solver.
The model never rewrites regression fixtures or grants itself unbounded commands.

## Regression gate and evidence

[Committed measured checkpoint](evidence/mechanics-qa-checkpoint.json).

The original 23 fixed native cases cover glass/oak/iron for supported loads, weak and
strong fixings, falling-body restart, hinges, sliders and springs, plus oak
and iron under the same 20 N hand. Checks retain deliberately specified
geometric/force/time bounds; results do not train their own acceptance limits.

Windows native Release, 1/240 s: all 23 passed in
build/mechanics-probe/final-v1. Oak rose 0.16666 m under 20 N; the equal-sized
iron block fell. A 1 N glass fixing reported pullout at 12.55575 N, with its
failure reason retained through restart. The initial hinge fixture was corrected
to place the mount behind the pin after its geometry blocked rotation; its
acceptance bounds were not loosened. This is an adapter/regression checkpoint,
not fresh full-engine qualification or calibrated real-world strength.

Run exactly the same lane after rebuilding physics:

```sh
BANJO_LIBRARY=build/ci/libbanjo.so BANJO_TRIAL_ENGINE=build/ci/banjo_live_world_run python tests/physics_trials_tests.py -v
python scripts/mechanics_qa.py --engine build/ci/banjo_live_world_run --out build/ci/mechanics-qa
```

Use .exe on Windows and a fresh output directory. Failure is a nonzero CLI exit.
CI builds the native engine first, runs all 44 plus the existing 96-case material
range, and uploads both lanes' evidence even on failure. The fixed fixtures
are versioned; intentional changes to laws or acceptance bounds require review.
Unit tests also cover malformed input, planner validation/no execution, HTTP/MCP
parity, isolation from the live room, cancellation and hung-child cleanup.

A material refinement request stops this lane as unresolved. Detailed
fracture remains in [Material QA](material-qa.md). No claim is made for grain,
general bending failure, fatigue, resource-paid construction, repair, lazy cell
allocation or full coupled energy closure. The next increments follow the
[player capability backlog](physics-gameplay-backlog.md).

Browser verification: the full 23-case suite passed through HTTP; the real
configured assistant changed only title and strength from 20 N to 5 N, keeping
all checks unchanged. The native result fell 0.18003 m and failed the lift check
as intended. Run selection, persistence, result display and native playback
were exercised with no browser warnings/errors observed. All 20 building
bodies restored at t=3563.1583333025196 s with zero pose/velocity difference.

Thirteen focused tests now include actual stdio MCP initialize/list/validate/run/
status/case requests, native oak/iron execution and result/playback agreement.
Twelve existing material-QA and 34 playground tests also pass. The protocol test
requires BANJO_TRIAL_ENGINE and BANJO_LIBRARY; CI supplies both, so it cannot
silently skip native coverage. Shared artifacts tolerate transient Windows
file-sharing conflicts for at most 190 ms and retain genuine I/O errors.

## Gameplay completion status

Platform MCP `physics_gameplay_status` and HTTP `GET /api/gameplay/capabilities` return the same 30-ID priority checklist, completion counts, partial evidence and remaining acceptance gates. They do not run physics or mark a capability complete from a narrow demonstration. [Finite-stock fabrication](fabrication.md) has its own native transaction/accounting QA lane.
