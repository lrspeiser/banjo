"""Compile declared electrical terminals to the native operating network.

The graph remains construction. PhysicsContract keeps this executable model
alongside its geometry; mutable state belongs exclusively to the live world.
Ordinary electrical relationships without a declared model remain declarations.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def compile_circuits(document: dict[str, Any]) -> list[dict[str, Any]]:
    components = {c["id"]: c for c in document["components"]}
    ports = {f"{c['id']}.{p['id']}": p["kind"] for c in components.values()
             for p in c.get("interfaces", [])}
    parent = {p: p for p, kind in ports.items() if kind == "electrical"}

    def root(port: str) -> str:
        if port not in parent:
            raise ValueError(f"circuit terminal {port!r} is not a declared electrical interface")
        while parent[port] != port:
            port = parent[port]
        return port

    declarations = [r for r in document.get("energy", []) if r.get("kind") == "circuit"]
    if not declarations:
        return []
    for r in document.get("relationships", []):
        if r.get("kind") != "electrical":
            continue
        if not r.get("a_interface") or not r.get("b_interface"):
            raise ValueError("executable electrical connections need two named terminals")
        a, b = root(f"{r['a']}.{r['a_interface']}"), root(f"{r['b']}.{r['b_interface']}")
        # A junction is ideal; a physical wire is a branch with resistance.
        if r.get("properties"):
            raise ValueError("electrical connection properties need an explicit circuit branch model")
        parent[max(a, b)] = min(a, b)

    result = []
    ids: set[str] = set()
    used_ports: set[str] = set()
    for entry in declarations:
        network = deepcopy(entry["network"])
        if network.get("schema") != "banjo.circuit.v1":
            raise ValueError("unsupported circuit model")
        if not network.get("id") or network["id"] in ids:
            raise ValueError("circuit ids must be nonempty and unique")
        ids.add(network["id"])
        source = network["source"]
        if "store" in source or source.get("store_component") not in components:
            raise ValueError("construction needs a store_component, not a live store id")
        nodes: set[str] = set()

        def terminal(value: str) -> str:
            p = root(value)
            nodes.add(p)
            return p

        for key in ("positive", "negative"):
            source[key] = terminal(source[key])
        if source["positive"] == source["negative"]:
            raise ValueError("source terminals are joined directly")
        for branch in network["branches"]:
            if branch.get("component") not in components:
                raise ValueError("circuit branch lost its construction component")
            for key in ("a", "b"):
                branch[key] = terminal(branch[key])
            if branch["a"] == branch["b"]:
                raise ValueError("branch terminals are joined directly")
            if branch.get("kind") == "motor":
                if "motor" in branch or branch.get("motor_component") not in components:
                    raise ValueError("construction needs a motor_component, not a live motor id")
        for node in network["thermal_nodes"]:
            if node.get("component") not in components:
                raise ValueError("thermal node lost its construction component")
        if used_ports & nodes:
            raise ValueError("electrically connected products must use one shared circuit solve")
        used_ports.update(nodes)
        network["nodes"] = sorted(nodes)
        result.append(network)
    return result


def bind_circuit(contract: dict[str, Any], circuit_id: str, *,
                 stores: dict[str, int], motors: dict[str, int]) -> dict[str, Any]:
    """Resolve component identities without changing the contract or a world."""
    models = contract.get("operating_model", {}).get("circuits", [])
    found = [model for model in models if model["id"] == circuit_id]
    if len(found) != 1:
        raise ValueError(f"no unique circuit {circuit_id!r} in PhysicsContract")
    network = deepcopy(found[0])
    source = network["source"]
    source["store"] = stores[source.pop("store_component")]
    for branch in network["branches"]:
        if branch.get("kind") == "motor":
            branch["motor"] = motors[branch.pop("motor_component")]
    return network


def install_circuit(world: Any, contract: dict[str, Any], circuit_id: str, *,
                    stores: dict[str, int], motors: dict[str, int]) -> int:
    """Install once, never on inspection/restore; native ownership is authoritative."""
    return world.circuit(bind_circuit(contract, circuit_id, stores=stores, motors=motors))
