# Workshop and Product platform API

The recorded material impact range, HTTP endpoints and five platform MCP tools are documented in [Material QA](../material-qa.md).

Contextual placement and saved interaction points: [contract](../placement-and-interaction-points.md).

Products now have a saved primary Use on Left mouse / J. See the [primary Use contract](../primary-use.md) for programming, API payloads, bounds and compatibility.

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

Named-world player surfaces also include `/api/workshop/goals` (personal
evidence-backed guidance through `starter_goals.view`) and
`/api/workshop/market` (quotes and transactions through `market.request`).
They use the existing server authentication, world lock and transaction guards;
they are HTTP capabilities, separate from isolated Workshop design calls.

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
| `POST` | `/api/workshop/inventory` | The Inventory tab: the material rack, the goods rack, the products standing in the world, the saved designs, the personal library, and every component family. Read-only. |
| `POST` | `/api/workshop/recipes` | The Recipes tab: for each template, its parts, materials against the rack, the goods its machines take, whether the rack covers it and what it can do; the open room's recipes and deposits. Read-only. |
| `POST` | `/api/workshop/drive` | Drive the design with the keys in a little world kept open: `{action: "start", candidate}` makes it and answers with the recording so far; `{action: "step", keys: {forward, back, left, right}, dt_s}` puts the keys to the thing (an ask on its program, or its wheels' controls) and runs that long, answering with the new frames and what it is doing; `{action: "stop"}` closes the room and answers with the whole recording. One drive at a time. |
| `POST` | `/api/workshop/skills` | The Skills tab: the person's notebook as achievements -- each technique known, within reach or not yet, what it opens, what is demonstrated, what is blocked. Read-only. |
| `POST` | `/api/workshop/progress` | Read what a chat turn has done so far, while it is still doing it. Takes `{"turn": "<the id sent with the request>"}` and changes nothing. |

A turn of the Workshop assistant is one `POST /api/workshop/candidates` that
answers when the whole thing is finished, and the work inside it is several
round trips to the model. The page makes an id, sends it as
`component_chat.turn`, and reads `/api/workshop/progress` about once a second so
the wait can say what is happening. Steps are kept for fifteen minutes and then
forgotten; asking about a turn nobody has heard of is not an error, it answers
with no steps.

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

### Build part by part

A design can be changed by adding parts, taking parts off and declaring how two
parts are fastened ([product-framework.md](../product-framework.md)). That
construction travels inside `component_overrides` under the reserved key
`"@construction"`, so a client that already round-trips the overrides keeps it
without learning a new field; no part may have a name beginning with `@`.

```json
"component_overrides": {
  "leg-1": {"material": "iron"},
  "@construction": {
    "schema": "banjo.workshop-construction.v1",
    "added":   [{"name": "post-1", "role": "post", "family": "post", "shape": "box",
                 "size_m": [0.04, 0.3, 0.04], "center_m": [0.1, 0.53, 0.1],
                 "rotation_deg": [0, 0, 0], "material": "oak"}],
    "removed": ["handle"],
    "joints":  [{"id": "joint-17", "kind": "fixed", "method": "bonded", "a": "deck", "b": "post-1"}],
    "joints_authored": true
  }
}
```

A joint's `kind` is `fixed` (the two move as one) or `bearing` (one turns in the
other about the joint's axis). Its `method` is `bonded` (glued, welded or fused
over the whole contact), `pressed` (a shaft held in a bore) or `bearing`. At
most one joint holds any two parts. Where a joint is, over what area, and about
which axis are measured from the parts as they stand and never stored.

`/api/workshop/candidates` takes `construct`, with the candidate specification:

| `action` | fields | effect |
|---|---|---|
| `preview` | `part`, `by`, `onto`, `at_m`, `twist_deg`, `depth_m`, `snap` | Answers `construct.part` (where it would go) and `construct.touching` (what it would meet). Returns no `candidates`; nothing changes. |
| `add` | as `preview`, plus `joint: {"kind": "fixed" | "bearing"}` or none for a loose part | Adds the part; `construct.select` names it. |
| `remove` | `part_name` | Takes the part off with the joints that held it and the edits made to it. |
| `fasten` | `a`, `b`, `kind`, optional `method` | Fastens two touching parts, or changes how they are fastened. |
| `unfasten` | `a`, `b` | Removes their joint. |
| `adopt` | | Writes a template's implied connections down as joints. Every other action does this first. |

Instead of `at_m`, a client that cannot click names the face: `onto_face`, and
`offset_m` `[x, y, z]` from that face's middle in the product's axes (whatever
part of it leaves the face is ignored).

`part` is `{"family", "parameters", "material", "length_m"}` (a strut family
needs `length_m`) or `{"library_item_id"}` for a component saved in My Library.
`by` is the new part's face that goes against the other part (`face-y-` is its
bottom; `face-x-`, `face-x+`, `face-y+`, `face-z-`, `face-z+`). `onto` names the
part that was clicked and `at_m` the point clicked on it, in product metres. The
part lands square on the nearest face to that point, grows out of it, settles
on the face's middle or flush to its edge unless `snap` is false, is turned
about the face by `twist_deg` and sunk into it by `depth_m`.

Until a template has joints of its own, its connections are implied by what
touches and `construction.joints_authored` is false. After the first
construction they are declared and nothing is inferred; a joint whose parts an
edit pulled apart is kept and reported `open`. A built design has no parameter
variants: `sweeps` yields the one candidate and `/api/workshop/more` refuses.

Every candidate carries `construction`:

```json
{"joints_authored": true, "added": ["post-1"], "removed": [],
 "joints": [{"id": "joint-17", "kind": "fixed", "method": "bonded", "a": "deck", "b": "post-1", "open": false,
             "interface": {"form": "planar", "area_m2": 0.0016, "centre_m": [0.1, 0.38, 0.1],
                           "normal": [0, 1, 0], "on": "deck", "against": "post-1", "mitred": false,
                           "i_uu_m4": 2.13e-7, "i_vv_m4": 2.13e-7}}],
 "unfastened": [], "touching_unfastened": []}
```

An interface is `planar` (two faces; `mitred` when a raked member's end is cut
to sit flat, which bears over its section divided by the cosine of the rake) or
`cylindrical` (`shaft`, `housing`, `axis`, `diameter_m`, `engaged_m`, `through`).

A design built from nothing is `kind: "custom"`. It is opened with its first
part, which is set on the floor at the middle:

```json
{"kind": "custom", "first_part": {"family": "surface", "material": "oak", "parameters": {"width_m": 0.8}}}
```

`custom` is not among the `assemblies` the bench lists, because on its own it
has no parts to show.

### What drives it

A design says what a thing is made of and how its parts are fastened. This says
what makes it go. It travels the same way `@construction` does, inside
`component_overrides` under the reserved key `"@machines"`, so a client that
already round-trips the overrides carries it without learning a new field.
Schema `banjo.workshop-machines.v1`; at most 32 of each kind; the top-level
fields are exactly `schema`, `stores`, `motors`, `panels`, `lamps`, `controls`,
`chambers` and `programs`, and anything else is refused by name.

Everything is named by COMPONENT, because that is what a person is looking at on
the bench. A motor names the two components its pin joins, exactly as the room
names a motor by the two things its pin joins; installing turns those into the
bodies the compiler made.

```json
"component_overrides": {
  "@machines": {
    "schema": "banjo.workshop-machines.v1",
    "stores":   [{"name": "battery", "in": "deck", "capacity_j": 5000, "charge_j": 5000, "voltage_v": 24}],
    "panels":   [{"name": "solar panel", "on": "deck", "store": "battery", "area_m2": 0.25, "efficiency": 0.2}],
    "lamps":    [{"name": "lamp", "on": "globe", "watts": 20, "efficacy_lm_w": 120, "on_at_first": true}],
    "motors":   [{"name": "left motor", "turns": ["bearing-mount-11", "axle-1-stub-1"], "store": "battery",
                  "stall_torque_n_m": 20, "no_load_rpm": 60, "brake_torque_n_m": 40}],
    "controls": [{"name": "left wheel", "turns": ["bearing-mount-11", "axle-1-stub-1"]}],
    "chambers": [{"name": "chamber", "in": "lining-floor", "volume_m3": 0.048,
                  "wall_conductance_w_k": 3.0}],
    "programs": [{"kind": "roam", "left": "left wheel", "right": "right wheel",
                  "rest_below": 0.25, "rest_until": 0.6,
                  "sensors": [{"kind": "water", "on": "deck", "at_m": [0.2, 0, 0.3], "depth_m": 0.003}]}]
  }
}
```

**A store** sits `in` a component and holds joules: `capacity_j` 1 to 1e12,
`charge_j` from 0 (default 0), `voltage_v` 0.1 to 1e5 (default 24). A store told
to hold more than it can is refused before anything is built.

**A motor** names the two components its pin joins in `turns`, the `store` it
draws on, `stall_torque_n_m` 0.001 to 1e6 and `no_load_rpm` 0.01 to 1e5, and
optionally `brake_torque_n_m` (default 0). That pin must be a BEARING: a motor
on a joint bonded solid is refused by name, because a bonded joint cannot turn.
A motor may carry a `rotor` -- a declared propeller -- as
`{"thrust_n_per_rad2": 1e-6..100, "drag_n_m_per_rad2": 0..100}`, which is what
makes a machine fly.

**A panel** is a solar panel: it sits `on` a component, charges a `store`, and
has `area_m2` 1e-4 to 1e4 and `efficiency` 0.001 to 1 (default 0.2). `at_m` and
`normal` say where on its component it lies and which way it faces, in the
design's frame; left out, the installer takes the component's top. What it
collects depends on where the sun is, so a panel is only as good as the hour.

**A lamp** sits `on` a component and gives light (docs/machine-world.md, "Light
underground"). `watts` 0.01 to 1e5 (default 20) is what it asks for switched on,
`efficacy_lm_w` 0.1 to 1000 (default 120) is the lumens it gives for each watt it
gets, and `on_at_first` says whether it comes out switched on (default true).
`at_m` says where on its component it hangs, in the design's frame; left out, the
installer takes the component's top. It names NO store and NO cable: a lamp comes
out of the Workshop unwired and dark, and lights when somebody runs a cable to
it. One on a product that carries its own battery may name that `store`.

**A control** is the named handle for a pin, and it is how anything works a
motor: the page's panel, the room's chat and the API all operate a control or a
program, and a program works controls by name. Nothing commands a motor
directly, so a motor with no control on its pin can never be told anything --
Check Validity adds one rather than leaving it dead, and says so among its
changes.

**A chamber** is the inside of a furnace: the gas its walls enclose, which is
the thing that gets hot and the thing a charge sits in. It is not a body -- it
is the space where no body is -- so it reaches the room as a gas region rather
than as machinery, and `in` names the component whose walls make it, so the
design can be checked against its own parts. `volume_m3` is 1e-4 to 1e3.

`wall_conductance_w_k` (1e-3 to 1e5) is how fast heat leaves through the
lining, and it is the number that decides what the furnace can DO. With an
element of P watts the chamber settles at `ambient + P/U`, so a leaky furnace
cannot smelt iron however long you wait: on a 0.4 x 0.4 x 0.3 m chamber, 40 mm
of insulating castable is 6.0 W/K and tops out at 853 C -- not enough to burn
lime at 900 -- while 80 mm is 3.0 W/K and reaches 1687 C, which smelts iron at
1538. A product works its own conductance out from the lining it was built
with; declared here, it is only checked for being a number. At most 8, because
that is what a room will take in gas regions.

**A program** is what the machine does on its own, and a product runs at most
one. Its `kind` is `roam`, `sit`, `hover` or `still`, with `setting` 0 to 1
(default 1):

A still program may also work a furnace: `chamber` names which of the
product's chambers its element heats, and `element_w` (1 to 1e6) is what that
element puts in. The element is the program's to switch on -- it fires when a
recipe wants heat and stops once the chamber is at temperature -- which is why
its rating lives here and not among a room's heaters, those being started the
moment a room opens and run for a fixed time. `element_w` without a `chamber`
is refused, and so is a `chamber` the product has not got.

| kind | what it does | what it needs |
|---|---|---|
| `roam` | wanders and turns away from water | `left`, `right` controls |
| `sit` | drives to a thing the room already holds | `left`, `right`, `toward` (the room's name for it), `close_m` 0.01..100 (default 1), optional `pose` control with `pose_deg` -360..360 (default 90) |
| `hover` | flies and holds a height | `rotors`: exactly four rotor controls, in order round the machine from above, and `hover_m` 0.3..50 (default 1.5) |
| `still` | stays put and keeps its charge | `store` |

Any program may add `climb_deg` 0 to 89, the steepest ground it will take (not
`hover`), and a resting pair: `rest_below` is the share of charge it stops at and
`rest_until` the share it sets off again at. `rest_until` needs `rest_below` and
may not be below it -- a machine rests until it holds MORE than it rested at.

**Sensors** -- `sensors`, at most 16 per program -- are what it reads: `kind`
`water` or `ground`, `on` a
component, `at_m` three numbers, and `depth_m` 0.001 to 10 (default 0.003). A
roaming machine turns away from what its sensors see rather than driving into it.
`stops` is 1 ahead (default), -1 behind. Water reads depth. Ground reads a signed
drop (+) or step (-) from the chassis tangent plane to the actual terrain
triangles and trips at an absolute difference above `depth_m`. Suggested rover
ground threshold: 0.12 m. Fit probes across the wheel width ahead and behind.
Continuous slopes remain distinct from abrupt holes; sensors add no traction.
Intentional human driving orders retain their existing reflex override.

**A routine** is the work a machine does between places, declared on the program
as `routine`. Its `kind` is `dig`, `haul`, `process`, `custom` or `roam`:

- `dig` and `haul` each need a `hopper_kg` above 0 (0.1 to 1000).
- `process` needs a `recipe` and an `intake` and an `output`, each a name the
  room knows; `batch_kg` 0.01 to 1000 says how much it does at a time.
- `custom` IS its `steps`, a list of `{do, args, until, repeat, retries}`; the
  other kinds have their steps written already, and giving steps to them is
  refused.
- `places` maps at most 16 names to `[x, z]` in the room's metres, within
  +/-1000, and is how a machine is told where to work. `work_j_per_kg` 0 to
  10000 is what a scoop costs. `watch` is a list of `{when, do, then}`, and
  `recipes` are the recipes it brings to a room that lacks them.

A machine that gets nowhere notices and gets itself out; which machines have that
reflex, and everything the world does with all of this once it is installed, is in
[machine-world.md](../machine-world.md).

### Which joint a push would break first

The `force_probe` bench test (`/api/workshop/plan` with `bench_test`) takes
`push` (`down`, `up`, `+x`, `-x`, `+z`, `-z`; or an explicit `direction`) and
`standing` (`resting` on the floor, or `free` in mid-air), and answers a second
layer, `joint_screen` (`banjo.joint-screen.v1`, `evidence: "analytical-screen"`):

| field | meaning |
|---|---|
| `joints` | Every closed joint, worst first: `load` (what it transmits, in its own frame), `utilisation` (one is all of its strength), `would_be` (`pulled apart`, `crushed`, `sheared`, `sheared across the shaft`, `crushed in its bore`, `pulled out`, `twisted loose`), and `verdict`. |
| `verdict` | `holds` below half, `uncertain` from half to one, `gives way` at one or more, `unrated` when a material has no declared strength. |
| `first_to_give` | The force, along this same line, at which the first joint reaches its strength, and which joint. |
| `gives_way`, `comes_apart_into` | The joints past their strength, and the groups of parts left when they have gone. |
| `standing` | `free`, `resting on the floor`, `tipping, on <parts>`, `lifted clear of the floor`, any of the middle two with `, and sliding: …`. The floor pushes and never pulls, and grips up to `floor_friction` (0.5) times what presses on it. |
| `stops_standing_square` | The force along this line up to which it stays put, and what it `does` past that: `tips`, `slides`, `tips and slides`, `lifts off the floor`. Null when it never stops. |
| `floor` | What the floor does at each foot that bears: `part`, `at_m`, `force_n`. |
| `acceleration_m_s2` | The acceleration of the product's centre of mass under the push. |

A template that has not shown its joints answers `{"available": false, "why": …}`.
What a joint can carry is the weaker material's declared strength over the
measured contact (`mcp/product_joints.py`); the model, its assumptions and what
it does not cover are in [product-framework.md](../product-framework.md). It is
a calculation, not an engine trial, and the sim offers it in Build, not in Test.

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

Platform MCP **1.17.0** also exposes the world circuit tools and full-state
checkpoint tools documented in [machine-networks.md](machine-networks.md).
`install_circuit` compiles a supplied ProductGraph and binds one operating
network to already-created world stores/motors. This is separate from Workshop
geometry preview and does not manufacture material or reset a running machine.

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
| `workshop_build` | Build part by part: preview or add a part against a named face of another, take a part off, fasten or unfasten two parts, or adopt a template's implied joints. The same `construct` operations as the sim, with `joint_kind`/`joint_method` in place of the nested joint. |
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

## One test: `try_in_a_room`

The bench offers one simulation. It makes the design in a small world -- flat
ground of 400 mm of soil 16 m across, gravity, and a sky with the sun somewhere
in it -- by calling `workshop_install`, the same code the world installs with,
and then does to it whatever the config asks. The room is thrown away
afterwards and the live world is never touched.

```json
{"kind":"table","bench_test":{"test":"try_in_a_room",
 "config":{"seconds":6,"load_kg":120,"drop_m":0,"slide_m_s":0,
           "strike_kg":0,"strike_speed_m_s":8,"strike_height_fraction":1,
           "hour":12,"turn_on":true,
           "evaluate_limits":false,"max_moved_m":0.01,
           "max_turned_deg":5,"max_breaks":0}}}
```

* `load_kg` sets an iron cube of that mass on it, on the part named by `on`
  (API only) or on the whole thing. It is a body, not a declared force: it
  falls the last millimetre, presses with its own weight through real contact,
  and can slide off.
* `drop_m` lets it go from that far above where it stands.
* `slide_m_s` starts it moving along +X; the ground's friction is what stops it.
* `strike_kg` throws an iron cube at it at `strike_speed_m_s`, aimed at
  `strike_height_fraction` of its height (0 feet, 1 top).
* `hour` moves the sun; 12 is noon, 23 is the dark.
* `turn_on` starts the thing's own program, if it has one.

The result carries `measured` -- `moved_m`, `turned_deg`, `fell_over`,
`broke`, `dented`, `failures`, `stores`, `panels`, `programs` -- and a
`playback` timeline at 30 frames a second with each body's own engine geometry.
`broke` holds only the failure runs where the body actually came apart;
`failures` holds every run the engine asked for, because being overloaded is
not the same as breaking.

Offered for the kinds the installer can actually make: `table`, `bench`, and
anything drawn part by part through the chat (`custom`). A `cart` and a
`kettle` are refused by the installation adapter, and a `chair`, `stool` or
`shelf-unit` never compiles out of its template at all.

`evaluate_limits` opts in to a verdict against `max_moved_m`, `max_turned_deg`
and `max_breaks`; without it the result is `not-declared` and no pass is
claimed.

## The retired rigs

`declared_static_load`, `drop_product`, `slide_product`, `impact_product` and
`rigid_motion` floated the design's cells in a spec with no ground under them.
Every one of them is a setting of `try_in_a_room` now. They are marked
`category: retired` with `superseded_by: try_in_a_room`, are not offered in the
Test tab, and still run from the API so their own tests hold them to what they
measured. What follows describes those.

## Explicit static-load acceptance limits

`bench_test.acceptance_limits` (or `bench_test.config.acceptance_limits`, usable
through the existing MCP `config` argument and saved test presets) optionally
names `max_displacement_m`, `max_rotation_deg`, `max_fractures`, and/or
`min_actual_load_kg`. Bounds must be finite, nonnegative JSON numbers; fracture
limits must be whole counts. Empty, unknown, or invalid limits are refused
before a native session starts. This first acceptance adapter supports only
`declared_static_load`; it does not certify the reference hoist or other benches.

```json
{"kind":"table","bench_test":{"test":"declared_static_load",
 "config":{"duration_s":2.0,"cell_size_m":0.04,"record_trace":false,
 "acceptance_limits":{"max_displacement_m":0.01,"max_rotation_deg":2.0,
                      "max_fractures":0,"min_actual_load_kg":99.0}}}}
```

The Test panel exposes an unchecked **Evaluate the limits below** control.
Checking it declares the three displayed endpoint/fracture limits. No unchecked
example value becomes a pass criterion. Changing controls invalidates the old
verdict and discards an outstanding response for earlier settings.

The verdict names each check and carries the native Matter hash, resolution,
actual whole-cell load and duration. Missing/nonfinite measurements never mean
zero. Native grid verification, surviving product/load bodies, and completed
simulation time are required. A passing test applies only to that exact run;
end displacement is rigid-body centre displacement, not maximum beam deflection.
No untested load interval is inferred. A request can tighten, never weaken,
`acceptance_limits` already declared on a design's static-load test.

`product_evidence.from_bench` imports `not-declared` as an observation, preserving
the original status and native geometry provenance. Its nested measurements,
conditions and acceptance checks are copies, not aliases to mutable test output.

## Explicit live-world prototype installation

Unlike the pure `/api/workshop/*` design routes, the following world routes are
explicit capabilities. They use the same host, login and CSRF protection as
other live-world changes. See [the checkpoint](../workshop-install-checkpoint.md).

`POST /api/world/workshop/context {}` identifies the current `scene`, `session`
and `cell_size_m`; it never opens or resets a room.

`POST /api/world/workshop/preview` takes exactly these fields:

```json
{
  "scene": "yard",
  "session": "current-live-session-id",
  "mode": "authoring",
  "candidate": {"kind": "table", "parameters": {"material": "oak"}},
  "position_m": [3.0, 0.0]
}
```

X/Z are finite numbers within +/-100 m. Y is resolved by a whole-object integer-
grid translation above the native terrain envelope (or flat floor). The room resolution is not changed. The
candidate accepts the ordinary design recipe and component overrides. The result
reports `preview_id`, actual geometry hash/cells/mass, requested/applied placement,
native verification and limitations. It is NOT an installation or a strength
certificate. `mode` must explicitly be `authoring`; funded workpieces use the
[separate fabrication transaction](../fabrication.md). Articulated/mixed-material
products remain unsupported by this adapter. Native lattice installation checks
the complete footprint against terrain bounds, preserves current water, compares
terrain heights/surfaces/carried stock and ground material accounts, and refuses
any changed old state. Pending soil settling may refuse because legacy terrain
edit replay settles edits before reopening. Precise rigid terrain remains
explicitly unsupported by its separate native admission path.

`POST /api/world/workshop/commit` takes only `scene`, the source `session`,
`preview_id`, and a unique `request_id` (8-80 ASCII letters/digits/hyphen/underscore).
It refuses an expired, missing or stale preview. Retrying the SAME request and
preview returns the persisted installed receipt (`replayed: true`) without
creating another object. A request ID cannot be reused for a different preview.
The last 64 receipts are retained. A successful response has `status: installed`,
the new `session`, and `root_body` identifying the real installed solid. Rejoin
that scene through the world page to use it. Changing Workshop controls or the
selected candidate invalidates pending preview UI responses.

## Visible preset experiments

`bench_test.test` additionally accepts `drop_product` and `slide_product` for
connected, single-material structural solids. Config accepts `cell_size_m`
(default 0.04 m, range 0.005-0.1 m), `duration_s` (default 1.5 s, range 0.1-3 s),
and either `height_m` (default 0.2 m, range 0.04-2 m) or `speed_m_s` (default
1 m/s, range 0.1-3 m/s). Values must be finite numbers. Drop height is translated
onto the existing integer grid and both requested/applied heights are reported.
The result includes verified native geometry and optional numerical display
states; no arbitrary force program or unsupported acceptance limit is implied.

`declared_static_load` config can optionally override `load_kg` (0.1-1000 kg),
retaining the authored load target and any stricter declared acceptance limits.
Blank browser input uses the declared load. Actual quantized mass is reported.

Catalog entries distinguish `category: simulation` from `analysis`, and
`subject: selected-product` from `reference-fixture`. The browser offers only
supported selected-product simulations, with states always requested. Legacy
analysis/reference API operations have not been deleted. See the
[visible-tests checkpoint](../workshop-visible-tests-checkpoint.md) for limits.

## Visible experiment setup and saved component inspection

`POST /api/workshop/plan` accepts `bench_preview: {test, config}` alongside
the current candidate recipe. It returns `bench_preview` with schema
`banjo.workshop-setup.v1`, a single time-zero frame, geometry, summary and explicit
`native_verified` / `physics_advanced` fields. It does not produce a verdict or
advance the live world. The scene factories are shared with Run. Unsupported
setups fail explicitly. The rigid setup is compiled, not native-verified.

`POST /api/workshop/library {action: "inspect_component", item_id: "..."}`
returns the owner-scoped saved component and `component_preview` (one centered
part and its skin) with `read_only: true`. It does not return or mutate a product
candidate. Reuse continues through the existing explicit `reuse_library_item`
candidate operation. Physical skin recipes retain their settings and require
retest; obsolete primitive ports are not exported as physical interfaces.
