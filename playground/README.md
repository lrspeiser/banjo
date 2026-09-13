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

## Can this result be believed?

Every computed case now carries a trust panel, because a scene that runs cleanly
is not the same as a scene that means anything.

- **Timestep vs. required.** The engine computes the largest step its own spring
  network can represent. The panel reports the authored step against that bound
  as a ratio, so a run that is 669x too coarse no longer reads the same as one
  that is 1.2x too coarse. Where the required step is below the schema floor of
  1/4800 s, the panel says so: no admissible package can resolve that material.
- **Unexplained energy change**, as a fraction of the energy the scene started with.
- **Run at-rest control.** Re-runs that exact scene with gravity, the ground,
  every striker and every initial velocity removed. The correct answer is that
  nothing happens. If the control breaks bonds or creates energy, the paired
  experiment is measuring that instability at least as much as the impact, and
  the panel marks it CONTAMINATED. See
  [the convergence study](../docs/convergence-study-checkpoint.md) for the
  measurements this check exists to catch.

## Predict-then-measure suite

`playground/physics_suite.py` runs a battery of physics tasks in four sealed
stages: the scene is authored from a checked-in specification, the model states
what should happen **before** the engine runs (the prediction is hashed and
written to disk at that point, so it cannot be revised once the answer is
known), the engine and its at-rest control run, and only then is the sealed
prediction graded against the measurement.

Two verdicts are reported and never merged:

- **INVARIANTS** are deterministic and consult no model. Energy appearing in a
  scene that started at rest is wrong whatever any model believes. This is the
  real oracle.
- **PREDICTION** is the model's expectation. This catches "runs cleanly but
  behaves nothing like glass", which no invariant encodes.

Keeping them apart is the point: a model that predicts wrongly, or grades its
own wrong prediction generously, shows up as a disagreement between the columns.

```sh
python playground/physics_suite.py                      # full battery
python playground/physics_suite.py --filter rest        # one group
python playground/physics_suite.py --no-model           # invariants only, no API key needed
```

The suite exits non-zero while any invariant fails. It is not a readiness
certificate on its own: it bounds the at-rest instability and the reported
ledger, and says nothing about spatial convergence or material calibration.

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

## The room on /world, and its chat

`/world` is a room to walk around in, picked at the bottom right. It opens on
**the test rooms** — every build the QA proves, side by side (below) — and also
has **the bench**, **the courtyard**, **an empty yard**, **the armoury**, where
there is a sword to take up and things to cut with it, and **a valley with a
river**, where the ground can be dug and the water dammed (below). Its chat box builds with the MCP
server's own tools: the same names, schemas and handlers as `mcp/banjo_mcp.py`,
run on the room held as an MCP world (`playground/room_world.py`). Anything the
MCP can do, the chat can do, and `tests/chat_tool_parity_tests.py` fails if a
tool reaches the MCP and not the chat without a written reason.

The chat tries what it built before it answers — in its own copy of the world it
can pick things up, pull on them and let time pass — and every turn is logged
with the calls it made and anything that was refused, one file per turn under
`build/playground-logs/chat/`.

It is told where you are. Every request carries where you are standing, which
way you face and what the crosshair is on, so "give me a ball" puts one within
reach in front of you and "put it over there" goes where you are looking. And a
thing it puts somewhere is set down on whatever is under that point — the
ground, the floor or a table — rather than left in the air: the MCP's
`add_object` takes `[x, z]` for that and works the height out itself, and says
when what it set down is in water.

Whether it can actually build things is measured by asking it — the QA suite:

```powershell
python tests/qa.py                        # every case, two trials each, then the pictures
python tests/qa.py --recipes              # the proof builds only: no model, no cost
python tests/qa.py --cases bow,tower --trials 1
```

Each case is a sentence a person might type — a gate, a winch, a hoist, a
latch, a bow, a pendulum, dominoes, glass and ice that break, a hearth, a heated
piston, a rope and a panel to cut with a sword, and the rest
(`tests/agent_build_tests.py`, `tests/qa_cases.py`). The real
chat builds it with the MCP's tools; the engine then opens the room it left and
USES what was built — shoves, turns, hauls, looses, heats, swings, watches — and measures
the result against what physics says it must be: a pendulum's period from its
length, where a thrown ball must be, that a spring carries what hangs on it.
Every case also has a recipe, the same thing built by hand through the MCP, so a
failure lands in the right place: a recipe that fails is the engine or the
check, a recipe that passes while the chat fails is the chat or its guide.

Every check is held to the realtime rule — stopped the moment its engine falls
behind 1.1x, not reported afterwards — and ends by letting the room come to rest
and saying how it looks: still moving, sunk through the floor, flown off. Every
build is saved, and photographed in the real page by headless Chrome as it opens
and after it has run (`tests/qa_browser.py`). A run writes
`build/agent-regression/<time>/`: `index.html` (the report, with the pictures),
`summary.txt`, `report.json`, and each build as `<case>-<trial>.spec.json` (trial
0 is the recipe).

- `--retry RUN` asks again, into the same run, for trials that never reached the model.
- `--recheck RUN` judges a run again with the checks as they are now, from the
  rooms it saved — no model.
- `--photos RUN` takes a run's pictures again; `--share` also writes
  `<run>/share/`, the report with small pictures, for sending.
- `--rooms` writes the test rooms (below).

Trials cost a model conversation each — 140k to 230k tokens in, as measured — so
the suite is run on purpose, not from ctest.

### The test rooms

`python tests/qa.py --rooms` builds every recipe through the MCP exactly as the
QA does and lays them out side by side, each part named after its case — aim at
one and the page says, say, "hoist: iron weight" — with a concrete stop wherever
a thrown or rolling ball would carry on into the next build. They are written to
`playground/rooms/`, and the room opens on the first:

- **Tests: gates and wheels** (13,920 cells) — the hinged gate, and the castle
  gates worked by a winch and by a capstan.
- **Tests: latches, pulleys, ropes and springs** (10,780) — the latched gate, the
  counterweighted portcullis, the hoist, the seesaw, the bow, the tether, the
  pendulum, the spring, and a rope and an oak panel to cut, each with a sword on
  a rest in front of it.
- **Tests: breaking, motion and heat** (12,872) — the plank bridge, ice, the
  dent, the pane on a pin, the tower, dominoes, the bounce, sliding, the throw,
  the heated piston, the hearth and the iron bar.

Three rooms, because a room may hold 16,000 cells and still run at realtime and
together they hold 37,572. The overloaded shelf is in none of them — it slows
any room it is in to a crawl while the engine works out its break — and taking
the courtyard's bar off is an edit to the courtyard, which is its own room. So
are the four valley builds — the dam, the drained pond, the log and the dug-out
boulder — which are built in the valley, a room of its own (below). Run
`--rooms` again whenever a recipe changes.

### Taking up a sword

A body with an edge declared on it — the MCP's `blade` tool,
[docs/cutting-model.md](../docs/cutting-model.md) — can be taken up and swung.
Click it to take it by its grip: a hand with 800 N and 60 N m holds it in front
of you, pointing where you look, and dragging the view swings it — as fast as
that hand can manage, and no faster. Right-click turns the edge a quarter turn
(left, down, right, up); swung sideways with the edge facing down, the flat
leads. Whether what the edge meets is cut is the engine's answer — the edge's
geometry, the two materials, how fast and how hard they meet — never a name,
and the flat cuts nothing. Click again to let go.

The armoury is built for it, at 10 mm cells: a sword on a rest, a rope with a
weight on it, an oak panel hung from a lintel and a loaded batten across two
piers. How to make each cut by hand — where to stand and how far and fast to
drag — is written in `armoury()` in `playground/world_room.py`. Measured in the
page: from where the room's own test stands, a flick of the view 60 degrees to
the left in 0.15 s took the armoury's iron sword through the rope edge-first at
9.8 m/s, and the weight fell to the floor.

The test room's two swords are the QA recipes' — 40 mm aluminium bars, the
thinnest a 40 mm room makes — and where you stand matters as much as how fast
you turn. From the armoury test's own stance, moved to the test room's rope —
0.5 m to its right and 1.2 m back, eye 1.62 m up, looking level at a point
0.6 m right of the rope — the same 0.15 s flick took the bar through the rope
edge-first at 10.3 m/s, and the weight fell. From 1.15 m, aimed 30 degrees
right of the rope with the eye at 1.81 m, it glanced off one segment and then
led with the flat, and the rope held. A steady push through the rope cuts it
too, edge-first at 0.7 m/s.

The panel beside it cuts the same way. From the armoury's panel stance moved to
it — the blade lifted clear first, then 1.3 m in front of the panel with the
eye 0.14 m above its middle, looking level at a point 0.45 m to its right — one
flick of 34 degrees in 0.12 s took the bar through the 40 mm oak edge-first at
7.3 m/s, 12,516 mm² for 56 J: the lower piece fell to the floor and the upper
still hangs from the lintel.

### The valley

*A valley with a river* is generated ground with a river running west to east
and a pond beside it. The ground and the water are the engine's own heights
and depths, drawn as they are; the foam on the river is carried by the engine's
velocity field. Aim at the water and the label says how deep it is and how fast
it is moving. The Water panel says what is standing, what the river brings in
and takes out, how many columns the solver is computing, and what is
unaccounted for — zero to within rounding, or something is wrong. **Dig here**
digs a pit where the crosshair is on the ground, 0.8 m across and 0.4 m deep;
sandy sides slump into it, and the pit is still there when the room is opened
again.

Everything in it is built by asking. In this order the room holds all of it,
12,960 of its 16,000 cells:

1. "Dam the river with stone blocks so the water backs up behind them."
2. "Dig a channel to drain the pond."
3. "Put an oak log in the river."
4. "Put a big stone boulder on the river bank, where I can dig the ground out
   from under it." — then aim at the ground right beside it and press **Dig
   here**.

Measured in the page on 2026-09-12: asked for the dam, the chat set nine
concrete blocks across the river (fixed in place), and in the room the water
standing rose from 29.5 m³ to 36.2 m³ in 69 s while the outflow fell from 0.35
to about 0.22–0.25 m³/s, with 10⁻¹² m³ unaccounted.
[docs/terrain-and-water.md](../docs/terrain-and-water.md) has the rest: the
channel, the log and the boulder measured, what it costs — a minute of the
valley in 4.7 s — and what is not modelled: a floating body makes no waves,
fronts are smeared, and no sediment moves while anyone is there.

### Opening a saved build

`/world?qa=<run>/<case>-<trial>` opens any build a run saved, as a room of its
own, to be tried by hand; the report links each one. `&hold=1` opens it drawn
and held, its clock stopped until `banjoRoom.resume()` — which is how the
pictures begin at the moment the build does. `window.banjoRoom` also has
`ready()`, `status()`, `hold()`, `lookAt()` and `standAt()`, for driving the
page from outside it.

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
| `POST /api/world/open` | Open the room on /world: `{scene}` (one of the rooms above) or `{qa: "<run>/<case>-<trial>"}` (a saved QA build); `fresh: true` builds it again from scratch |
| `POST /api/world/ask` | One chat turn in the open room: `{message, story, person}` — `person` is where you are (`standing_m`, `eyes_m`, `facing`, `looking_at`, `looking_at_m`), checked and passed to the chat as `the_person`; a room the chat changed is opened again from what it left |
| `POST /api/live/act` | Step the open room, or take hold of, move, let go of or heat something in it. In a room with ground: `dig` and `deposit` change it (and are kept, so a reopened room still has them), `survey` says what is at a point, `discharge` sets the river, and `environment`, `environment_state` and `terrain` read the ground and the water |

The server answers in HTTP/1.1 and keeps a connection open between requests.
Under 1.0 every reply closed its connection and the room's page opened a new one
for every step; on Windows a long look ran the machine out of socket buffers
(`net::ERR_NO_BUFFER_SPACE`) and the room stopped.

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
python tests/qa_open_tests.py
python tests/qa.py --recipes
node --check playground/app.js
node --check playground/world.js
ctest --test-dir build/win-joint-double -C Release --output-on-failure
build/win-joint-double/Release/banjo_object_state_probe.exe
```

Mocked planner/HTTP tests never contact OpenAI. Real chat verification is an
explicit browser submission using the configured key. Inspect the resulting
plan, actual package, native report and native window; check unsupported input,
follow-up changes and strict solver failures separately.

OpenAI integration follows the official [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
and [GPT-5 mini model documentation](https://developers.openai.com/api/docs/models/gpt-5-mini).

## Measured evidence and GPT review

In 3D playback, scroll the sidebar below authored controls to **View measured evidence** or **Analyze this run with GPT**. Analysis uses the server-only configured key, saves the exact evidence and result, and reuses saved reviews. See [checkpoint and API details](../docs/experiment-review-checkpoint.md).
