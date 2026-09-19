"""Stateful machine adapters for both Banjo MCP servers. No alternate physics."""
from __future__ import annotations

from copy import deepcopy
from functools import wraps
import hashlib
import json
import uuid

from circuit_api import CIRCUIT_SCHEMA, ID, NAME, obj, validate


WORLD = {"world_id": NAME}
TOOLS = [
    {"name": "circuit", "description":
     "Attach one shared DC/thermal network to an existing store and ALL its motors. "
     "Create store/motor first; their store_id/motor_id bind the network. Supports "
     "wires, resistors, switches, fuses, motor gearing and heat nodes/links. "
     "No charging, general fluids or ideal speed source. Returns a circuit handle. "
     "Additive only; use snapshot_world/restore_world to resume, never redeclare a report. "
     "See docs/api/machine-networks.md for units, limits and conservation residuals.",
     "inputSchema": obj({**WORLD, "network": CIRCUIT_SCHEMA}, ["world_id", "network"])},
    {"name": "install_circuit", "description":
     "Compile a ProductGraph and install one declared operating circuit on existing "
     "world parts. stores maps component ids to store names; motors maps component ids "
     "to the part turned by one motor. Geometry, store and motor creation must precede "
     "installation. Preserves component labels. Does not manufacture parts or reset state.",
     "inputSchema": obj({**WORLD, "product_graph": {"type": "object"}, "circuit_id": NAME,
                         "stores": {"type": "object", "additionalProperties": NAME},
                         "motors": {"type": "object", "additionalProperties": NAME}},
                        ["world_id", "product_graph", "circuit_id", "stores", "motors"])},
    {"name": "circuit_switch", "description":
     "Open or close a declared switch branch by circuit handle and branch id. "
     "Takes effect on the next accepted step; cannot repair a failed branch or fuse.",
     "inputSchema": obj({**WORLD, "circuit": ID, "branch": NAME, "closed": {"type": "boolean"}},
                        ["world_id", "circuit", "branch", "closed"])},
    {"name": "circuits", "description":
     "Read every circuit's declaration and current state without advancing or resetting it: "
     "node volts, branch amps, torque and support reaction, temperatures K, switch/fuse "
     "damage, and source/heat/shaft/ambient joules plus numerical residuals. "
     "Each circuit field is its native positive handle, distinct from its string id.",
     "inputSchema": obj(WORLD, ["world_id"])},
    {"name": "snapshot_world", "description":
     "Read a resumable whole-world checkpoint including MCP names, circuit heat/fuse history, "
     "battery charge and native mechanical state. Returns checkpoint; store it as JSON and "
     "pass it unchanged to restore_world. Refuses while native work cannot be snapshotted.",
     "inputSchema": obj(WORLD, ["world_id"])},
    {"name": "restore_world", "description":
     "Resume an unchanged checkpoint returned by snapshot_world into a new world id. "
     "Does not redeclare machines, refill batteries, clear heat or repair fuses. "
     "Refuses incompatible ABI, edited checkpoints and any incomplete native restore. "
     "Close the old world first if transferring ownership rather than making a sandbox copy.",
     "inputSchema": obj({"checkpoint": {"type": "object"}}, ["checkpoint"])},
]


def reports(world):
    return [dict(state, circuit=index) for index, state in enumerate(world.circuits(), 1)]


def has_circuits(entry):
    world = entry.get("world")
    return world is not None and bool(world.circuits())


def refuse_rebuild(core, entry):
    if has_circuits(entry):
        raise core.Refused("This world has stateful circuits. Edited-scene state remapping is not "
                           "implemented; this edit would reset charge, heat or fuse damage. "
                           "Use circuit_switch/drive/run, or snapshot_world and restore_world "
                           "unchanged. clear_world explicitly discards the entire world.")


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def register(core):
    def circuit(args):
        entry = core._world(args["world_id"])
        if entry.get("check") is not None:
            raise ValueError("Circuit authoring in the browser room awaits state-preserving room "
                             "editing; use the standalone world MCP or native API.")
        validate(args["network"], CIRCUIT_SCHEMA)
        world = core._live(entry)
        handle = world.circuit(args["network"])
        return {"circuit": handle, "state": reports(world)[handle - 1]}

    def install(args):
        from product_contract import compile_contract
        from product_circuit import bind_circuit
        entry = core._world(args["world_id"])
        stores, motors = {}, {}
        for component, name in args["stores"].items():
            store = core._store_named(entry, name)
            if store is None:
                raise ValueError(f"no store named {name!r} for component {component!r}")
            stores[component] = store["live"]
        for component, part in args["motors"].items():
            found = core._motors_turning(entry, part)
            if len(found) != 1:
                raise ValueError(f"component {component!r} needs one motor turning {part!r}")
            motors[component] = found[0]["live"]
        contract = compile_contract(args["product_graph"])
        network = bind_circuit(contract, args["circuit_id"], stores=stores, motors=motors)
        return circuit({"world_id": args["world_id"], "network": network})

    def switch(args):
        world = core._live(core._world(args["world_id"]))
        world.circuit_switch(args["circuit"], args["branch"], args["closed"])
        return {"circuit": args["circuit"], "branch": args["branch"], "closed": args["closed"]}

    def inspect(args):
        return {"circuits": reports(core._live(core._world(args["world_id"])))}

    def snapshot(args):
        entry = core._world(args["world_id"])
        if entry.get("check") is not None:
            raise ValueError("Use the browser room's own persistence for its world.")
        world = core._live(entry)
        native = world.snapshot()
        if native is None:
            raise ValueError(world.last_refusal or "native snapshot unavailable")
        metadata = {k: v for k, v in entry.items() if k not in ("world", "check")}
        payload = {"schema": "banjo.mcp-world.v1", "abi": core.banjo.ABI_VERSION,
                   "entry": metadata, "native": native}
        return {"checkpoint": {"payload": payload, "sha256": _digest(payload)}}

    def restore(args):
        checkpoint = args["checkpoint"]
        payload = checkpoint["payload"]
        if checkpoint["sha256"] != _digest(payload):
            raise ValueError("checkpoint was edited; restore requires the unchanged checkpoint")
        if payload["schema"] != "banjo.mcp-world.v1" or payload["abi"] != core.banjo.ABI_VERSION:
            raise ValueError("unsupported checkpoint schema or ABI")
        if len(core.WORLDS) >= core.MAX_WORLDS:
            raise ValueError("close a world before restoring another")
        entry = deepcopy(payload["entry"])
        if "world" in entry or "check" in entry:
            raise ValueError("checkpoint metadata contains runtime fields")
        world = core.banjo.World(entry["scene"], cell_size_m=entry["cell_m"], snapshot=payload["native"])
        restored = world.restored()
        if restored.get("tier") != "whole":
            world.close()
            raise ValueError(f"whole-world restore required: {restored}")
        world_id = uuid.uuid4().hex[:8]
        entry["world"] = world
        core.WORLDS[world_id] = entry
        return {"world_id": world_id, "restored": restored, "circuits": reports(world)}

    functions = {"circuit": circuit, "install_circuit": install, "circuit_switch": switch,
                 "circuits": inspect, "snapshot_world": snapshot, "restore_world": restore}
    for tool in TOOLS:
        def wrap(handler, schema):
            @wraps(handler)
            def call(args):
                try:
                    validate(args, schema, "arguments")
                    return handler(args)
                except core.Refused:
                    raise
                except (ValueError, TypeError, KeyError, core.banjo.BanjoError) as error:
                    raise core.Refused(str(error)) from None
            return call
        core.HANDLERS[tool["name"]] = wrap(functions[tool["name"]], tool["inputSchema"])
    core.TOOLS.extend(deepcopy(TOOLS))

    # These authoring paths can mutate metadata before reaching _rebuild or
    # run a temporary trial. Refuse at the boundary, before either can happen.
    for name in ("add_object", "remove_object", "move_object", "turn_object", "drop",
                 "duplicate", "build_recipe", "build_structure", "interaction", "enclose_gas",
                 "heat", "tool_point", "make_terrain", "cut_block"):
        def guarded(handler):
            @wraps(handler)
            def call(args):
                refuse_rebuild(core, core._world(args.get("world_id")))
                return handler(args)
            return call
        core.HANDLERS[name] = guarded(core.HANDLERS[name])
