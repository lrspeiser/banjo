# Banjo chat playground

Describe a physical experiment, inspect the generated Banjo declaration, run the
native engine, and open the same initial package in the 3D studio. GPT authors
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

- “Compare an iron ball hitting glass, wood and iron panels at 2 m/s for 1 second.”
- “Now compare speeds of 2 and 6 m/s.”
- “Drop an iron cube from 25 cm onto glass, wood and iron; use rigid controls.”
- “Test a knife against the tomato proxy and keep the material controls.”
- “Show the 6 mm tempered-glass reference and its missing validation gates.”
- “Run the permanent deformation and compact save/reload reference.”
- “Show the heat frontier through glass, wood, iron and water/ice.”

**Open native studio when ready** opens a fresh native scene. Press **Release**
there to run it; use **Next/Previous** for a generated sweep. The headless report
and the studio are separate executions of the same initial package, with the
same duration rounded to whole physics steps. Native reports and screenshots
are written beside each other in the job's `native` directory. The
thermal reference has its own **Open studio** button. The J2 material-point and
published glass references return reports rather than invented 3D outcomes.

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
ignored `build/playground-runs/`; server/browser session indexes do not restore
automatically after restart. This is a local development service, not a public
multiuser deployment.

All generated network damage trials use strict refinement-limit rejection.
Unresolved high-energy trials can halt. The GUI/report says so rather than
substituting a shatter animation. Live J2 dents, live-world compact persistence,
gameplay repair and stochastic material integration remain future adapters.
The [glass reference](../docs/glass-drop-benchmark.md) records experimental
first-fracture data and apparatus uncertainty; it is not a passed simulation.
Thermal and state references run fixed fixtures; their names do not authorize
arbitrary thermal geometry or new constitutive parameters.

## Local HTTP contract

| Request | Purpose |
|---|---|
| `GET /api/status` | Engine/model availability, capabilities and a local session token; never the GPT key |
| `GET /api/goal` | The full current goal as Markdown |
| `POST /api/chat` | Submit `{message, previous_plan, request_id, auto_open}`; receive a job ID |
| `GET /api/jobs/{id}` | Poll status, generated plan, cases, reports, limits and timing |
| `GET /api/jobs/{id}/package/{case_index}` | Export the exact generated package |
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
