# Debug: the bench the coding agents work from

`http://127.0.0.1:<port>/debug`, linked from the world's header. It is not the
game. A person playing opens the world and the Workshop in it and never needs
this page; it exists so that the things an agent needs — every room, what the
engine says about itself, the suites that measure it — are one click away
instead of being remembered.

**There is one Debug page, and new debugging screens go on it.** That is the
rule it exists under. The site used to be seven pages because each job that
needed a screen got one: a fracture lab, an Explorer, a fabrication page and
three QA pages. Six of them were deleted; what they were actually used for is
here. If you build something that needs a screen to be watched, add a section
to `playground/debug.{html,js,css}` rather than a page beside it.

## Starting it

```bash
python playground/server.py --port 8765 --engine build/integration/Release/banjo_platform_cli.exe
```

It listens on `127.0.0.1` only. Rooms are kept per port in
`build/playground-rooms/<port>`, so two servers on two ports never touch each
other's world — run your own port rather than restarting somebody else's.

| Address | What it is |
|---|---|
| `/` and `/world` | the world |
| `/world?workshop=1` | the Workshop, as a tab of the same page |
| `/world?scene=<room>` | any room |
| `/debug` | this |

## What is on it

**The rooms.** Every scene the server can open, from `/api/scenes`, each a link
to `/world?scene=<name>`. The world's own menu offers two of them; the rest were
reachable only by typing an address. They are split into places and trial rooms
by the `tests-` prefix, which is the server's own naming rather than a judgement
about what is inside. `world` is the real one — `yard` is a single body and
proves nothing.

**The engine.** `/api/status`, as labelled values: whether the engine and the
studio are there, whether a room is open, the chat model and whether a key and
Jev are configured, and what the build will not claim. When a suite refuses to
start, the answer is nearly always one of these saying no.

**The QA suites.** The four suites, what each holds, and the runs on this
server. Three of them have a catalogue and run one case you pick; fabrication
has no catalogue and runs its whole suite in one go.

| Suite | Cases | Needs | Started with |
|---|---|---|---|
| `material-qa` | 96 — a plate of one material struck at one speed | `banjo_fast_lattice_run` beside the engine | `{"case_ids": [...]}` |
| `mechanics-qa` | 44 — whole-body trials: what holds, what carries, what gives way | the native live world runner | `{"case_ids": [...]}` |
| `tool-qa` | 6 — a tool into ground | the native live world runner | `{"case_ids": [...]}` |
| `fabrication-qa` | its whole fixed suite, under a 120 s budget | the native live runner and the shared library beside it | `{}` |

These are the measurements the deleted QA pages drew. **CI does not use this
page**: it runs `scripts/material_qa.py`, `mechanics_qa.py`, `tool_qa.py` and
`fabrication_qa.py`, which never needed a browser. The buttons here are for
when you want one case now and watched.

**The routes**, so you can drive any of it without a browser.

## Driving it without a browser

Every GET is plain. Every POST needs the local session token:

```bash
TOKEN=$(curl -s http://127.0.0.1:8765/api/status | python -c "import json,sys; print(json.load(sys.stdin)['csrf_token'])")
curl -s -X POST http://127.0.0.1:8765/api/world/open \
  -H "Content-Type: application/json" -H "X-Banjo-Token: $TOKEN" \
  -d '{"scene": "world"}'
```

The header is `X-Banjo-Token`, **not** `X-CSRF-Token`; without it the answer is
403. The server also refuses a request whose `Host` or `Origin` is not its own.

| Route | What it gives |
|---|---|
| `GET /api/status` | the engine, the chat, and the token every POST needs |
| `GET /api/scenes` | every room this server can open |
| `GET /api/materials` | what each material is, from the engine's own catalogue |
| `GET /api/<suite>` | a suite's catalogue (not `fabrication-qa`, which has none) |
| `GET /api/<suite>/runs` | that suite's runs, newest first |
| `GET /api/<suite>/runs/<id>` | one run's report: `status`, `total`, `completed`, `results` |
| `POST /api/<suite>/run` | start it; `202` with the new run's `id` |
| `POST /api/<suite>/cancel` | `{"run_id": "..."}` |
| `POST /api/world/open` | `{"scene": "world"}` |
| `POST /api/live/act` | `{"session", "op": "step", "dt", "n"}` |

`<suite>` is `material-qa`, `mechanics-qa`, `tool-qa` or `fabrication-qa`. A run
id is 32 hex characters. A suite refuses a second run while one is going.

A run's report carries a `status`. Treat `starting` and `running` as "still
going" and anything else as finished — the terminal values are spread across
the managers and the `scripts/` that do the measuring (`passed`, `complete`,
`failed`, `error`, `cancelled`, with `cancelling` in between), so testing for
the two live ones is the check that does not rot. Poll the report rather than
assuming the thread's pace.

## Adding to it

Four things to know before you change the page:

1. **Read what you show; do not write it down.** The page holds no list of
   scenes and no list of cases — it asks `/api/scenes` and the catalogues. A
   list written into a page goes stale the moment the source moves and cannot
   be told that it has. Add an endpoint before you add a hardcoded table.
2. **No inline `<script>` or `<style>`.** The Content-Security-Policy is
   `script-src 'self'; style-src 'self'`, with named hashes only for
   `world.html`'s own inline blocks. `debug.html` has none, so it needs no
   hash — keep it that way and it keeps working.
3. **Serving a file means adding it to the allowlist** in `server.py`'s
   `do_GET` (`allowed`), which is an explicit map. A file not in it is a 404
   however real it is on disk.
4. **The guard is a test.**
   `tests/playground_tests.py::test_static_allowlist_and_environment_paths`
   asserts the world, the Workshop and the three `/debug` files serve, that the
   world's header links to both of the others, and that all nineteen deleted
   addresses still 404. A second test asserts every address that serves
   `world.html` — `/`, `/world`, `/world.html` — carries its inline hashes.
   That one exists because `/` was once left out and the root served a page the
   browser then refused to run.

## What it is not

It does not replace the MCP servers. A model driving Banjo should use
[mcp.md](mcp.md) — the tools there build worlds, run them and report what
happened, with a vocabulary meant for a model. Debug is a screen for a person
watching a run, and the HTTP routes behind it.

It also does not host the old experiment console. `/api/jobs`, `/api/fracture`
and `/api/scene` still answer, and MCP, `scripts/` and the tests still use them,
but no page reaches them any more.
