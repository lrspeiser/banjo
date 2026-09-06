# Banjo chat playground

Describe a physical experiment, inspect the generated Banjo declaration, run the
native engine, and inspect its computed states in the page's **3D Playback** tab. GPT authors
bounded data; it does not execute code or advance the physics clock.

Build the current Windows Release configuration, then run from the repository:

```powershell
cmake --build build/win-joint-double --config Release --parallel 4
python playground/server.py --port 8765
```

On Windows, `./playground/Start-Playground.ps1` starts the local server in the
background and opens the page, or reuses an already running playground.
Use `-NoBrowser` to start only the service.

Open `http://127.0.0.1:8765`. The local server reads `OPENAI_API_KEY` from the
ignored repository `.env` or its process environment. `OPENAI_MODEL` optionally
selects a compatible Responses/Structured Outputs model; the default is
`gpt-5-mini`. The key is never sent to the browser or included in model input,
packages, reports or access logs. There is no API key entry box in this page.

The [full project goal](../docs/project-goal-2026-09-06.md) is also available in
the **Project goal** tab. The goal contains nine workstreams and preserves all
40 mechanics/platform requirements.

## Try it

New composable routes are available. Try:

- “Drop an 80 mm iron ball from 0.2 m onto free rigid glass, oak and iron targets, 0.24 by 0.36 by 0.04 m, with an x offset of 0.02 m. Add a height slider.”
- “Try an uncalibrated volumetric 6 mm panel drop: glass, oak and iron, width 0.12 m, length 0.16 m, clamped edges, resolution 4 by 4 by 2, 80 mm iron ball from 0.05 m, duration 0.3 s. Show diagnostic limits.”
- “Create two 80 mm iron cubes moving toward each other at 1 m/s in zero gravity, with spin 4 rad/s about y. Run 0.4 s.”

The 6 mm case is now admitted by the new builder, but currently stops at a
numerical damage limit. It is not a shell solver or validated shatter result.
See [the executed plan and failure evidence](../docs/general-experiment-checkpoint.md).

- “Compare an iron ball hitting glass, wood and iron panels at 2 m/s for 1 second.”
- “Now compare speeds of 2 and 6 m/s.”
- “Drop an iron cube from 25 cm onto glass, wood and iron; use rigid controls.”
- “Test a knife against the tomato proxy and keep the material controls.”
- “Show the 6 mm tempered-glass reference and its missing validation gates.”
- “Run the permanent deformation and compact save/reload reference.”
- “Run the spatial pressure and springback test for glass, wood and iron.”
- “Show the heat frontier through glass, wood, iron and water/ice.”

Leave **Show 3D playback when ready** checked. The page automatically opens the
computed experiment. Drag to orbit, scroll to zoom, play/pause, step or scrub
to inspect an outcome. Components shows internal structure; reference shape
and labeled displacement magnification aid the pressure experiment.

Ask for controls as part of the prompt, for example: “Run the illustrative
glass/oak/iron pressure reference at 200 MPa, resolution 4, 16 increments.
Add a Watch response button and a pressure slider from 100 to 800 MPa.”
GPT authors a bounded `ui` declaration. Physical sliders use **Apply and rerun**
to create a fresh native calculation without another model call. Display controls
only inspect already computed states. Arbitrary generated HTML or JavaScript is
not executed. Network recordings and their reports come from the same run.

**Open native studio** remains an optional separate execution for network scenes.
Thermal has its own native view; material-point and published glass references
return reports without invented 3D motion. Pressure replay is quasistatic load
presentation, not elapsed physical time or an impact simulation.

## Executed language and boundaries

`experiment_language.py` defines `banjo-playground-1` and a strict JSON Schema.
It compiles template sweeps or explicit preset-object layouts through
`make_object`, `make_package`, `write_package`, and `EngineCLI` in the existing
public authoring client. The native loader remains the final capability and
physics admission gate. Inspect **Language** for the actual `banjo-network-2`
package and **Results** for solver output. A GPT message is not simulation
evidence.

This v1 admits at most four sweep cases, twelve custom objects, a conservative
850-cell upper bound, three simulated seconds per mechanical case, one active
job and 100 jobs per server session. Each GPT request has a bounded input,
output and timeout; there is no automatic paid retry. Each native process has
a 75-second timeout. Reusing an identical request ID returns the same job;
different content with that ID rejects. Jobs and packages are recorded under
ignored `build/playground-runs/`. Browser refresh restores the latest job while
the server session remains active; `?job=<id>` opens a specific session result.
Known terminal jobs and their recordings now reload from disk after server restart.
Restored native-window launching is disabled; embedded playback remains available.
This is a local development service, not a public
multiuser deployment.

All generated network damage trials use strict refinement-limit rejection.
Unresolved high-energy trials can halt. The GUI/report says so rather than
substituting a shatter animation. Collision-driven J2 dents, live-world compact persistence,
gameplay repair and stochastic material integration remain future adapters.
The [glass reference](../docs/glass-drop-benchmark.md) records experimental
first-fracture data and apparatus uncertainty; it is not a passed simulation.
Thermal and state references run fixed fixtures; their names do not authorize
arbitrary thermal geometry or new constitutive parameters.
The `continuum_pressure_reference` route has fixed geometry: 40 × 20 × 40 mm
glass/oak/iron coupons, a central 20 × 20 mm pressure patch, bottom clamp,
with default 4/2/4 cell mesh, 32 increments per loading/unloading branch and 800 MPa peak.
The optional `pressure` declaration accepts `peak_pressure_pa` (1–1e9),
even `resolution` (4–12), `increments` (2–64), and `profile` (`uniform` or `smooth`).
It executes native small-strain equilibrium and preserves plastic history;
it is not spatially converged or calibrated. Wood reaches a validity limit in
this setup; Results reports that limit and its last accepted state. Speed and
height arrays must be empty; generic duration, projectile and panel fields do
not change this fixed reference. See the [API, refinement and limitations](../docs/continuum-pressure-checkpoint.md).

## Local HTTP contract

| Request | Purpose |
|---|---|
| `GET /api/status` | Engine/model availability, capabilities and a local session token; never the GPT key |
| `GET /api/goal` | The full current goal as Markdown |
| `GET /api/schema` | Executable language schema and admission budgets |
| `POST /api/chat` | Submit `{message, previous_plan, request_id, auto_open}`; receive a job ID |
| `GET /api/jobs/{id}` | Poll status, generated plan, cases, reports, limits and timing |
| `GET /api/jobs/{id}/package/{case_index}` | Export the exact generated package |
| `GET /api/jobs/{id}/playback/{case_index}` | Bounded server-owned native recording |
| `POST /api/jobs/{id}/rerun` | Apply `{case_index, action, value, request_id}` from a declared physical control; no model call |
| `POST /api/jobs/{id}/open` | Open `{case_index}` in the native studio |

POSTs require `Content-Type: application/json` and `X-Banjo-Token` from status.
Use a fresh request ID for a new request and reuse that ID/body to deduplicate
an uncertain submission. `previous_plan` is the last structured plan for a
revision, or null. Case indices start at zero. Capability/validation errors
reject before native mutation. Inspect case status separately from job status:
an experiment can finish with a `solver_limit` diagnostic case.

Plans are model proposals. Inspect the actual experiment type, geometry and
package when precision matters; a model can misinterpret a request. Physical
validity and execution status are engine evidence. Unsupported capabilities,
unimplemented inventory/energy transactions and complete world save/repair
cannot be enabled by prompt wording.

## Verification

```powershell
python tests/playground_tests.py -v
node --check playground/app.js
ctest --test-dir build/win-joint-double -C Release --output-on-failure
build/win-joint-double/Release/banjo_object_state_probe.exe
```

Mocked planner/HTTP tests never contact OpenAI. Real chat verification is an
explicit browser submission using the configured key. Inspect the resulting
plan, actual package, native report and native window; check unsupported input,
follow-up changes and strict solver failures separately.

OpenAI integration follows the official [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
and [GPT-5 mini model documentation](https://developers.openai.com/api/docs/models/gpt-5-mini).
