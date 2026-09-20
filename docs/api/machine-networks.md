# Machine API and MCP reference

Contextual placement and saved interaction points: [contract](../placement-and-interaction-points.md).

September 19, 2026. Native ABI **25**, world MCP **1.13.0**, platform MCP **1.16.0**.
This reference covers the executable functions and the boundaries of the fifteen
requested machine capabilities. It does not turn planned solvers into callable
appliances. Model laws and measured numerical errors are in
[machine-circuits.md](../machine-circuits.md); remaining implementation is tracked
in [machine-network-roadmap.md](../machine-network-roadmap.md).

Editable native physics experiments and regression QA: [recipe/API contract](../physics-trials.md).

## Surfaces and ownership

| Operation | C ABI | Python | MCP (both servers) | Native runner operation |
|---|---|---|---|---|
| Finite supply | `banjo_make_energy_store` | `World.energy_store` | `store` | `store` |
| Motor on a hinge | `banjo_make_motor` | `World.motor` | `motor` | `motor` |
| Command / brake | `banjo_drive_motor` | `World.drive_motor` | `drive` | `drive` |
| Declare circuit | `banjo_make_circuit` | `World.circuit` | `circuit` | `circuit` |
| Bind product circuit | use resolved declaration above | `product_circuit.bind_circuit`, `install_circuit` | `install_circuit` | use resolved declaration above |
| Switch | `banjo_circuit_switch` | `World.circuit_switch` | `circuit_switch` | `circuit_switch` |
| Circuit state and ledger | `banjo_circuits` | `World.circuits` | `circuits`; also `run`, `describe_world` | `circuits`; also `machines.circuits` in normal replies |
| Machine observations | `banjo_energy_stores`, `banjo_motors`, `banjo_drum_ropes`, `banjo_controls` | `energy_stores`, `motors`, `drum_ropes`, `controls` | `run`, `describe_world`, `joints` | `step`, `poses` |
| Hoist/shaft controller | `banjo_make_control`, `banjo_operate` | `control`, `operate` | `control`, `operate` | `control`, `operate` |
| Save / resume | `banjo_snapshot`, `banjo_open_snapshot`, `banjo_restored` | `snapshot`, `World(..., snapshot=...)`, `restored` | `snapshot_world`, `restore_world` | `snapshot`, startup `--snapshot FILE` |

The world owns all mutable physical state. Store ids, motor ids and circuit
handles are positive integers local to that world. `store` returns `store_id`;
`motor` returns `motor_id`. Machine reports also include these ids. A circuit's
string `id` is its construction label; its integer **handle** is returned by
creation. C/Python/runner report arrays are in handle order (index + 1). MCP adds
a `circuit` handle to each report. Handles survive an unchanged whole-world
restore. Do not bind ids from another world.

The two stdio entry points are `mcp/banjo_mcp.py` and
`mcp/banjo_platform_mcp.py`. The latter adds all Workshop/Product tools to the
same world tools and handlers. `tools/list` publishes the full nested circuit
input schema from [circuit_api.py](../../mcp/circuit_api.py), with types, required
fields, bounds and unknown-field rejection. No extra Python package is required.

The browser room's authoring copy cannot yet install or edit circuits while
preserving the separate live room. These six MCP tools are explicitly excluded
there, with reasons in `room_world.NOT_FOR_THE_ROOM`; they work in standalone
MCP worlds. The optional legacy in-process playground adapter does not implement
machine commands. Use the native runner or C/Python world API for these machines.
No new Workshop HTTP route or browser control is claimed by this checkpoint.

## Circuit declaration

Create geometry, hinges, stores and motors first, then attach the circuit before
running it. All motors spending a store must belong to its one circuit. A store
cannot have two circuit owners or later acquire a bypassing direct-store motor.
No delete, replace, refill or repair operation is provided. The existing direct
store motor path is retained until explicitly attached.

This minimal resistive circuit is also a complete MCP tool argument after
substituting the returned world and store ids:

```json
{
  "world_id": "returned-world-id",
  "network": {
    "schema": "banjo.circuit.v1",
    "id": "heater",
    "nodes": ["positive", "switched", "negative"],
    "source": {
      "store": 1, "positive": "positive", "negative": "negative",
      "resistance_ohm": 0.1, "thermal": "case"
    },
    "thermal_nodes": [
      {"id": "case", "component": "battery", "capacity_j_k": 100},
      {"id": "element", "component": "heater", "capacity_j_k": 10, "ambient_w_k": 1}
    ],
    "thermal_links": [],
    "branches": [
      {"id": "power", "kind": "switch", "component": "switch",
       "a": "positive", "b": "switched", "resistance_ohm": 0.01, "thermal": "case"},
      {"id": "element", "kind": "resistor", "component": "heater",
       "a": "switched", "b": "negative", "resistance_ohm": 12, "thermal": "element"}
    ]
  }
}
```

| Field | Contract and default |
|---|---|
| `schema`, `id` | `banjo.circuit.v1`; nonempty construction label |
| `nodes` | Distinct nonempty node names; 2–128. A junction uses the same name. |
| `ambient_k` | Positive kelvin; 293.15. Prescribed infinite thermal surroundings. |
| `source.store` | Existing positive uint32 store id; source joules remain in that store. |
| `source.positive`, `negative` | Different nodes from `nodes`. |
| `source.resistance_ohm`, `thermal` | 1e-9–1e12 ohms; thermal node receiving internal/regulator losses. |
| `thermal_nodes` | 1–128 nodes. Unique `id`, source `component`, positive `capacity_j_k` (J/K). |
| Node `temperature_k`, `ambient_w_k` | Positive initial K (defaults to ambient); nonnegative ambient conductance W/K (0). |
| `thermal_links` | 0–256 links (default empty), each `a`, `b` names different thermal nodes; `conductance_w_k` >= 0. |
| `branches` | 0–256. Unique `id`, source `component`, different electrical `a`, `b`, and a loss destination `thermal`. |
| Branch `kind` | `wire`, `resistor`, `switch`, `fuse`, `motor`. |
| `resistance_ohm` | Required positive 1e-9–1e12 for non-motors. Omit for motors: derived from declared motor parameters. |
| `motor`, `gear_ratio` | Existing motor id required for motor branch; positive ratio <= 1e6 (1). Ratio = motor speed / output speed. Other kinds cannot name a motor or use a non-unit ratio. |
| `alpha_per_k`, `reference_k` | Nonnegative resistance coefficient 1/K (0); positive reference K (293.15). |
| `closed` | Boolean, true. `circuit_switch` changes only branches of kind `switch`. |
| `fuse_a2_s` | Positive A²s rating required for fuse; 0 otherwise unless a threshold is deliberately declared. |
| `trip_k` | Nonnegative thermal trip K; 0 disables. A trip/fuse failure is irreversible. |

All numbers must be finite. At most 32 circuits may be attached to a world.
Native validation also checks topology, thermal references, ownership, motor
store membership and valid temperature-dependent resistance. MCP rejects
unknown keys, including output fields such as `ledger`, `last`, `failed` and
`used_a2_s`. A **report is not a resume declaration**. Use the native snapshot
or the MCP checkpoint to preserve history.

## Calls, errors and restart

```python
# `network` is a declaration using already-created store/motor ids.
circuit = world.circuit(network)
world.circuit_switch(circuit, "power", False)
report = world.circuits()           # read-only; no step, cooling or repair
saved = world.snapshot()
if saved is None:
    raise RuntimeError(world.last_refusal)
# Keep the same scene and cell size with saved; close the original for a resume.
```

Python raises `BanjoError` for native refusal and `ValueError` for invalid switch
argument types/ranges. `closed` must be an actual boolean, not `"false"` or 1.
C creation returns a positive id or negative status. C switch returns `BANJO_OK`
or negative status; `closed` must be 0 or 1. `banjo_circuits` returns a JSON array
string, or NULL with `banjo_last_error`. The string belongs to the world until
its next circuit query or destruction. Copy it if keeping it longer.

MCP tool calls use ordinary JSON-RPC `tools/call`:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"circuit_switch","arguments":{"world_id":"returned-world-id","circuit":1,"branch":"power","closed":false}}}
```

Successful tool content is a JSON string in `result.content[0].text`. Refusals
set `result.isError: true` and explain the failed condition. A refused circuit
declaration or switch leaves the previous network intact. `circuits` takes only
`world_id` and returns `{"circuits":[...]}`. `snapshot_world` takes `world_id`
and returns `checkpoint`. Pass that unchanged as the `checkpoint` argument to
`restore_world`; it returns a **new** `world_id`, `restored`, and `circuits`.
Close the old world first when transferring ownership. A sandbox copy is not a
material transfer between worlds.

The MCP checkpoint contains native state, JSON metadata and a SHA-256 integrity
check. This detects accidental edits, not malicious tampering or authenticity.
ABI mismatch, incomplete native restore, or edited checkpoint is refused.
Snapshot refusal while native work is pending does not reset the world.
Edited-scene remapping is unsupported: authoring operations that would rebuild
a circuit world refuse before modification. `clear_world` explicitly discards
the entire world's contents; it is not a circuit repair command.

For a product, MCP `install_circuit` takes `world_id`, `product_graph`,
`circuit_id`, `stores` (component id → existing store name), and `motors`
(component id → part turned by a unique existing motor). It compiles through
the same `compile_contract` and binds through `bind_circuit` as Python. It
creates no geometry or material. Use the complete graph in
[circuit_product.json](../../examples/authoring/circuit_product.json); the Python
journey is [circuit_drive.py](../../examples/authoring/circuit_drive.py).

The runner accepts newline-delimited JSON, with `network` identical to Python:

```json
{"op":"circuit","network":{"schema":"banjo.circuit.v1","id":"..."}}
{"op":"circuit_switch","circuit":1,"branch":"power","closed":false}
{"op":"circuits"}
```

The first line abbreviates the declaration; supply all required fields above.
Creation returns `circuit`; inspection returns `circuits`. Other replies include
the same array at `machines.circuits`, including the opening reply when resumed
with `--scene FILE --cell SIZE --snapshot FILE`. `snapshot` returns the native
snapshot, not the MCP envelope. The two formats are intentionally distinct.

## Observations and limits

Reports include the declaration and current thermal temperatures, switch state,
`failed`, and accumulated `used_a2_s`. After an accepted step each branch also
has `current_a`, `motor_current_a`, `torque_n_m` and `housing_reaction_n_m`.
Branch current is positive from `a` to `b`; housing reaction is opposite output
torque. `last.voltage_v` follows `nodes`; `source_current_a`, `power_limited` and
`max_kcl_a` report supply loading and current-balance error.

`ledger` contains `elapsed_s`, `source_j`, `heat_j`, `shaft_j`, `ambient_j`,
`electrical_residual_j`, `thermal_residual_j` and `coupling_residual_j`.
Shaft work and environmental exchange are signed. Use the **circuit** ledger
for the complete network; a motor's ledger excludes wire and source heat.
Local electrical/thermal closure is not proof of full-world conservation.
Explicit coupling has a measured timestep-dependent numerical residual; it is
reported separately from physical heat. See the [evidence](../machine-circuits.md).

Circuit heat nodes currently exchange with one another and prescribed ambient,
not arbitrary thermochemical bodies. The gear ratio is ideal; there is no clutch,
backlash or gearbox loss law. Reverse battery charging is blocked. A back-driven
motor can supply connected loads. The step must satisfy the native coupling
guard (at most 1/60 s and potentially smaller for damping/speed); a refused step
does not commit circuit state. MCP `run` uses 1/480 s, which can still be too
large for extreme declared motors. Use smaller native/Python steps in that case.

## All fifteen requested areas

These are executable entry points to existing foundations, not claims that
their deferred extensions are implemented. C signatures and units are in
[c-api.md](c-api.md), MCP schemas in `tools/list`, and product APIs in
[workshop.md](workshop.md).

| Area | Available public functions / tools | Still unavailable |
|---|---|---|
| 1. Electrical circuits | Circuit functions above: resistive wires, junctions, switches, fuses, shared power-limited source and motors | Multiple supplies, capacitors, inductors, diodes, general electronics |
| 2. Storage / generation | `banjo_make_energy_store`; Python `energy_store`; MCP `store`; back-driven circuit motor can feed connected loads | Recharge, generator/charger/converter components, SOC-dependent voltage and charge acceptance |
| 3. Electromechanical / magnetic | `banjo_make_motor`, `banjo_drive_motor`; `motor`, `drive`; electrical load, torque and support reaction | Solenoids, electromagnets, linear electrical actuators and magnetic couplings |
| 4. Transmission | `banjo_hinge`, `banjo_reeve`, `banjo_drum`, `banjo_spring`; matching Python and MCP `hinge`, `reeve`, `drum`, `spring`; circuit `gear_ratio` | General connected shafts, clutch, differential, belt, chain, rack and screw models |
| 5. Flexible parts / connections | Existing lattice fracture/statics, `banjo_fix`, `banjo_joint_member`, `banjo_bodies_mechanics`; MCP `fix`, `overloaded`, `thermal_state`; Workshop joint screens | General beam/shaft/plate/shell runtime and complete bearing/bending/torsion capacities |
| 6. Internal thermal networks | Circuit `thermal_nodes`, `thermal_links`; `banjo_declare`, `banjo_heat`, `banjo_thermo_report`; Python `declare`, `heat`, `thermo_report`; MCP `heat`, `thermal_state` | General thermal ports coupled across circuit and thermochemical body networks |
| 7. Thermal distortion | `banjo_mechanics_report`; Python `body_mechanics`, `mechanics_report`; MCP `thermal_state` for existing weakening/recession | Expansion, differential expansion, thermal stress and general permanent deformation |
| 8. Phase / vessels | Separate sparse enthalpy solver exists internally; no general live-world phase-transfer API | Live melting/pouring/boiling/condensation and material-containing vessel inventories |
| 9. Liquid / gas networks | Terrain/water C API; Python `water`, `environment_report`; MCP `water_state`; `banjo_declare`, `banjo_gas_regions`, `banjo_vent`; Python `gas_regions`, `vent`; MCP `enclose_gas`, `thermal_state` | General pipes/pumps/tanks/valves and connected mass/composition/enthalpy transfer |
| 10. Hydraulics / pneumatics | Declared gas piston via `banjo_declare` / `World.declare`, MCP `enclose_gas` | Hydraulic pumps/cylinders, accumulators, seals, relief valves, choked flow and vessel wall loading |
| 11. Thermodynamic cycles | Existing heat/chemistry/gas reporting and piston work | Reusable boilers/condensers/compressors/heat pumps and connected cycle solver |
| 12. Manufacturing | `banjo_declare`, `banjo_energy_ledger`; finite reactions, Python `declare` / `energy`; Workshop materialization is authoring | Energy-accounted manufacturing/processes with persistent work in progress |
| 13. Sensors / controllers | `banjo_make_control`, `banjo_operate`, `banjo_controls`; Python `control`, `operate`, `controls`; MCP `control`, `operate`, machine readings | Generic typed sensor/signal graph and bounded programmable controllers |
| 14. Environment / harvesting | Terrain/water APIs; prescribed thermal ambient; MCP `make_terrain`, `survey`, `water_state`, `set_river` | Finite enclosed air, airflow/fans, general aerodynamic drag and solar collection |
| 15. Lifetime | Existing irreversible thermal damage and circuit fuse history in reports/snapshots | General fatigue, wear, creep and corrosion laws |

Electrical, shaft, thermal, fluid, material and control connector declarations
in ProductGraph/PhysicsContract are not all executable solvers. Unsupported
domains remain marked in the contract. Proposed weak-joint reductions stay
inactive; this API work does not enable them.

## Verification

`tests/machine_api_tests.py` exercises both real MCP subprocesses: discovery,
direct and product circuit installation, drive/run/read, invalid-input and
duplicate-owner refusals, edit refusal without state changes, switching, and
whole-world restart with identical circuit history. It also covers Python input
types and the native runner's commands and restart. `tests/api_docs_tests.py`
checks C function documentation, Python binding coverage, both MCP tool lists,
Workshop routes, ABI/version parity and this circuit schema's documented fields.
`tests/chat_tool_parity_tests.py` checks room exclusions remain explicit.
These are API regressions, not a fresh full-engine qualification.

Measured on Windows with MSVC Release, built from main `45ab4e3`: seven focused
CTest suites passed in 7.84 s (circuit, product circuit, machine API, API docs,
joint binding, motor, machine control), plus 17 chat-tool parity tests and nine
legacy MCP handshake/machine regressions. The native runner build and mandatory
floating-point audit passed. All 275 C++ sources are registered. The earlier
uncompleted broad fracture/FFI run remains outside this passing scope.
Integrated the concurrent API documentation repair `aec206f` before publishing;
its ABI history is retained and the documentation parity checks rerun.
