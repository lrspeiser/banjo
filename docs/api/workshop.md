# Workshop and Product platform API

Workshop is Banjo's product-design surface. It designs one product or assembly in
an isolated workspace, measures it, reuses saved components, runs bounded tests,
compiles a reduced real-time physics contract, and materializes only the selected
candidate. The live outside world does not advance while Workshop tests run.

The important architectural rule is that **the sim is a client of the platform**:

```text
browser Workshop
    -> POST /api/workshop/*
    -> playground/workshop_api.py
    -> mcp/workshop.py + product physics + isolated test benches

Banjo platform MCP
    -> mcp/workshop_platform.py
    -> the same playground/workshop_api.py functions for browser-visible behavior
    -> the same product physics modules for generic ProductGraph operations
```

The browser does not own product geometry or physics rules. `mcp/workshop.py`
remains the authoritative Workshop geometry model; `mcp/product_graph.py` adds
physics semantics; `mcp/product_contract.py` compiles reduced runtime behavior.

## Schemas

| schema | meaning |
|---|---|
| `banjo.workshop.v1` | Workshop candidate/session responses |
| `banjo.workshop-platform.v1` | versioned platform capability/operation contract |
| `banjo.product-graph.v1` | product components, interfaces, relationships, energy, controls, contents, tests and evidence |
| `banjo.physics-contract.v1` | reduced real-time representation compiled from ProductGraph |
| `banjo.product-evidence.v1` | immutable engineering evidence and explicit validated ranges |
| `banjo.workshop-bench.v1` | one isolated Workshop test result |
| `banjo.workshop-library.v1` | persistent user-scoped component/product library |

A measured test does **not** become validation merely because it produced a
number. Only evidence whose acceptance status is explicitly `passed` may define
a validated range used by runtime reduction.

## HTTP API used by the sim

Every mutation is local and CSRF-protected by the playground server in the same
way as the rest of the sim. The Workshop page calls only these routes.

| method | endpoint | purpose |
|---|---|---|
| `POST` | `/api/workshop/open` | Open a product, saved design or personal-library assembly. Returns candidate wireframes, catalogs, My Library, pricebook, functional tests and saved test presets. |
| `POST` | `/api/workshop/candidates` | Generate candidates, edit components, reuse a library component, or run the bounded Workshop assistant over the current candidate. |
| `POST` | `/api/workshop/more` | Generate six deterministic nearby variants around a selected candidate. |
| `POST` | `/api/workshop/plan` | Materialize a candidate preview/BOM and optionally run its declared static-load trial or one functional bench test. |
| `POST` | `/api/workshop/library` | List/load/save components and assemblies, set material prices, and save functional-test presets. |
| `POST` | `/api/workshop/feedback` | Save rating/note/selection feedback and optionally persist the design. |
| `POST` | `/api/workshop/remembered` | Read saved feedback, designs, library items, pricebook and test presets. |

The HTTP routes remain backward-compatible. `mcp/workshop_platform.py` names the
same operations for MCP and other programmatic clients.

### Open

```json
{
  "kind": "table",
  "parameters": {},
  "world_revision": "optional immutable source revision",
  "target": "optional label"
}
```

Instead of `kind`, a client may reopen an existing design with
`saved_design_id`, or an assembly from My Library with `library_item_id`.

The response includes the candidate's exact part list and measured quantities
(mass, centre of mass, support footprint, tip margin/angle), declared tests,
material BOM, component catalog, personal library and test catalog.

### Edit / reuse / Workshop assistant

`/api/workshop/candidates` carries the current candidate specification plus one
of these optional operations.

Component edit:

```json
{
  "kind": "table",
  "design_id": "table-g3-v1",
  "parameters": {},
  "component_overrides": {},
  "component_edit": {
    "part_name": "leg-1",
    "action": "thinner",
    "scope": "similar",
    "amount": 0.12
  }
}
```

Reuse a saved component:

```json
{
  "kind": "cart",
  "design_id": "cart-g1-v1",
  "parameters": {},
  "component_overrides": {},
  "reuse_library_item": {
    "item_id": "lib-...",
    "part_name": "wheel-1",
    "scope": "similar"
  }
}
```

Conversational edit:

```json
{
  "kind": "table",
  "design_id": "table-g1-v1",
  "parameters": {},
  "component_overrides": {},
  "component_chat": {
    "part_name": "leg-1",
    "message": "make all four legs longer and thinner"
  }
}
```

The conversational adapter can inspect full design geometry, one component,
physics/load paths and My Library, then apply several bounded edits in one turn.
A failed turn leaves the candidate unchanged.

### Variants

`/api/workshop/candidates` accepts `sweeps` as parameter -> values to generate a
bounded Cartesian product. `/api/workshop/more` is the sim's one-click local
exploration around the selected product.

### Materialization and testing

The base request to `/api/workshop/plan` is a candidate specification plus an
optional `cell_size_m`. It returns a materialization plan and BOM. This is a
preview, **not a live-world commit**.

Run the assembly's declared load trial:

```json
{
  "kind": "table",
  "design_id": "table-g1-v1",
  "parameters": {},
  "component_overrides": {},
  "run_trial": true,
  "cell_size_m": 0.04,
  "duration_s": 2.0
}
```

The trial uses an isolated `banjo_live_world_run` session and reports measured
displacement, rotation and fractures. If the design has no acceptance tolerance,
its verdict is intentionally `not-declared`: the result is evidence, not an
invented pass/fail.

Run a functional bench test:

```json
{
  "kind": "cart",
  "design_id": "cart-g1-v1",
  "parameters": {},
  "component_overrides": {},
  "bench_test": {
    "test": "cart_roll",
    "config": {"speed_m_s": 0.8, "duration_s": 0.5}
  }
}
```

Current bench operations:

| test | scope | what it does |
|---|---|---|
| `runtime_contract` | any product | Build ProductGraph and compile its reduced PhysicsContract. |
| `force_probe` | any product | Apply an analytical point force to an exact component/point and report authored load paths and support reactions. |
| `cart_roll` | cart | Isolated engine trial with real bearing DOFs and rolling motion. |
| `kettle_heat` | kettle | Isolated thermochemical trial of contained water heated through the product's actual bottom geometry. |
| `machine_control` | general machine fixture | Run the battery/motor/controller path against the engine. |

### My Library

`POST /api/workshop/library` is action-based.

| action | required data | result |
|---|---|---|
| omitted | none | component families, products, saved designs, My Library, prices, tests and presets |
| `load` | `item_id` | exact current library item/version |
| `save_component` | candidate + `part_name`, optional `name` | versioned reusable component recipe with local ports/physics semantics |
| `save_design` | candidate + optional `name`/`item_id` | versioned assembly recipe |
| `set_price` | `material`, `price_per_kg`, optional `currency` | updated personal pricebook |
| `save_bench_preset` | `name`, `test`, `config` | saved test configuration |

Library records are owner-scoped and indexed by semantic namespaces such as
`physics`, `capability`, `interface`, `relationship`, `test`, `role` and
`family`. `mcp/workshop_platform.py` also exposes semantic tag search to the
platform MCP; the browser currently renders the complete My Library list.

## Product engineering API

The generic product layer is deliberately name-independent. A cart, kettle,
guillotine or future machine uses the same structures.

`mcp/workshop_platform.py` exposes these stable operations to the platform MCP:

- `inspect_product` — Workshop design -> ProductGraph -> PhysicsContract.
- `mate_product` — deterministically align two named interfaces and add an
  explicit relationship (`fixed`, `hinge`, `bearing`, `slider`, etc.).
- `runtime_decision` — decide whether a reduced PhysicsContract stays valid for
  an event or should refine locally.
- `record_evidence` — create an immutable evidence record; validated ranges are
  accepted only for passed acceptance criteria.
- `evidence_envelope` — gather separately validated intervals without filling
  untested gaps.

These operations are pure product engineering and do not alter the live world.

## MCP server

For the full platform, register **`banjo_platform_mcp.py`**, not the legacy
world-only entry point:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --target banjo_c banjo_live_world_run

claude mcp add banjo -- \
  env BANJO_LIBRARY=/path/to/libbanjo.so \
      BANJO_LIVE_ENGINE=/path/to/banjo_live_world_run \
  python /path/to/banjo/mcp/banjo_platform_mcp.py
```

On Windows, point those variables at `banjo.dll` and
`banjo_live_world_run.exe`.

`BANJO_LIBRARY` is required by the existing world/physics tools. Pure Workshop
design, ProductGraph, PhysicsContract, force-probe and library operations do not
need the live executable. Engine-backed Workshop tests do; when
`BANJO_LIVE_ENGINE` is absent they refuse with that setup instruction rather
than silently substituting a fake test.

The personal MCP library defaults to `build/mcp-workshop`. Override with:

- `BANJO_WORKSHOP_HOME` — storage root.
- `BANJO_WORKSHOP_OWNER` — owner namespace for the SQLite library.
- `OPENAI_API_KEY` / `OPENAI_MODEL` — optional, only for the Workshop assistant
  conversational edit; structured MCP edit tools do not require a model call.

## MCP tools

The platform server exposes every tool from the existing world MCP plus these
Workshop/Product tools.

| tool | what it does |
|---|---|
| `workshop_catalog` | Product/component catalog, test catalog, personal library, pricebook and platform contract. |
| `workshop_open` | Open a product, saved design or library assembly and return measured candidates. |
| `workshop_edit` | Resize/material-edit components, reuse a saved component, or optionally run the bounded Workshop assistant. |
| `workshop_variants` | Generate parameter sweeps or deterministic more-like-this candidates. |
| `workshop_inspect` | Compile a Workshop design or ProductGraph to ProductGraph + PhysicsContract. |
| `workshop_test` | Run runtime-contract, force-probe, cart, kettle, machine or declared-load tests in isolation. |
| `workshop_materialize` | Return materialization plan and BOM without changing the live world. |
| `workshop_library` | List/load/search/save the physics-tagged library, prices and test presets. |
| `workshop_history` | Read saved feedback and history together with saved designs, personal library, prices and test presets, through the same remembered surface the sim uses. |
| `workshop_mate` | Deterministically mate two ProductGraph interfaces and declare their relationship. |
| `workshop_runtime` | Ask the adaptive runtime policy whether reduced physics is still valid or should refine. |
| `workshop_evidence` | Record engineering evidence or aggregate explicit validated intervals. |
| `workshop_feedback` | Save Workshop feedback and optionally persist the design. |

The MCP wrapper extends the existing `banjo_mcp.py` process in place. It does
not fork the world physics implementation: `tools/list` is the union of the
existing world tools and the table above, and `tools/call` dispatches both in the
same JSON-RPC process.

## Sim as a client

`playground/workshop.js` is intentionally a renderer/client. Its Workshop
requests are restricted to the documented `/api/workshop/*` routes above. It
must not import `mcp/workshop.py`, ProductGraph or test implementation details.
The server decides geometry, measurements, legal edits, tests and persistence;
the page renders the returned candidate and sends user intent back through the
API.

That separation is now tested: adding a new browser Workshop endpoint or a new
Workshop MCP tool without documenting it fails the API-doc parity suite.

## Consistency and optional simulation traces

Physical skin edits invalidate wireframe-based engineering evidence. Their
canonical Matter measurements include mass, centre of mass, cell inertia,
support hull and conservative face-connectivity diagnostics. A disconnected
geometry is flagged; a face-connected geometry is not a strength certificate.
The `visual` plan response adds `matter_measured`, `matter_bom` and
`matter_component_mass_kg`, computed before exterior filtering.

`bench_test.config.record_trace` (boolean, default true) controls retention of
numerical states for inspection, not whether the test runs. The direct
`run_trial` request also accepts `record_trace`. False omits `playback`. Traces
are bounded and report effective sampling, maximum state gap and event overflow.
No video is encoded and the outside world does not advance. Exact static-load
results verify native grid occupancy before advancing and report any whole-body
integer-grid placement offset used to seat the product on the floor.

Saved designs preserve component and skin overrides. Physically edited plans
use a Matter fingerprint; legacy primitive descriptions are under
`wireframe_objects`, with `objects` empty until an exact-Matter installation
adapter exists. Do not treat those primitive descriptions as a tested build.
See [the checkpoint](../workshop-consistency-checkpoint.md) for verification
and remaining boundaries.
