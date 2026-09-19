"""Public circuit declaration schema shared by MCP discovery and validation.

Native code remains authoritative for topology, ownership and physical laws.
This dependency-free boundary rejects misspelled/read-only fields before an
MCP caller can mistake a report or snapshot for a fresh declaration.
"""
from __future__ import annotations

import math
from typing import Any


def obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


NAME = {"type": "string", "minLength": 1}
ID = {"type": "integer", "minimum": 1, "maximum": 4294967295}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
NONNEGATIVE = {"type": "number", "minimum": 0}
RESISTANCE = {"type": "number", "minimum": 1e-9, "maximum": 1e12,
              "description": "Resistance in ohms. Motor resistance is derived; omit it there."}
BRANCH = obj({
    "id": NAME, "component": NAME, "a": NAME, "b": NAME, "thermal": NAME,
    "kind": {"type": "string", "enum": ["wire", "resistor", "switch", "fuse", "motor"]},
    "resistance_ohm": RESISTANCE,
    "alpha_per_k": dict(NONNEGATIVE, description="Resistance temperature coefficient, 1/K; default 0."),
    "reference_k": dict(POSITIVE, description="Resistance reference temperature in K; default 293.15."),
    "trip_k": dict(NONNEGATIVE, description="Irreversible temperature trip in K; 0 disables it."),
    "fuse_a2_s": dict(NONNEGATIVE, description="Fuse I-squared-time limit in A^2 s; positive for a fuse."),
    "gear_ratio": {"type": "number", "exclusiveMinimum": 0, "maximum": 1e6,
                   "description": "Motor speed/output speed; default 1. Ideal, lossless ratio."},
    "motor": dict(ID, description="Existing native motor id, required for kind motor."),
    "closed": {"type": "boolean", "default": True},
}, ["id", "kind", "component", "a", "b", "thermal"])
CIRCUIT_SCHEMA = obj({
    "schema": {"type": "string", "enum": ["banjo.circuit.v1"]},
    "id": NAME,
    "nodes": {"type": "array", "items": NAME, "minItems": 2, "maxItems": 128,
              "uniqueItems": True},
    "ambient_k": dict(POSITIVE, description="Prescribed thermal surroundings in K; default 293.15."),
    "source": obj({"store": ID, "positive": NAME, "negative": NAME,
                   "resistance_ohm": RESISTANCE, "thermal": NAME},
                  ["store", "positive", "negative", "resistance_ohm", "thermal"]),
    "branches": {"type": "array", "items": BRANCH, "maxItems": 256},
    "thermal_nodes": {"type": "array", "minItems": 1, "maxItems": 128, "items": obj({
        "id": NAME, "component": NAME, "capacity_j_k": POSITIVE,
        "temperature_k": POSITIVE, "ambient_w_k": NONNEGATIVE,
    }, ["id", "component", "capacity_j_k"])},
    "thermal_links": {"type": "array", "maxItems": 256, "items": obj({
        "a": NAME, "b": NAME, "conductance_w_k": NONNEGATIVE,
    }, ["a", "b", "conductance_w_k"])},
}, ["schema", "id", "nodes", "source", "branches", "thermal_nodes"])


def validate(value: Any, schema: dict, path: str = "network") -> None:
    """Validate the JSON Schema subset used above, without a server dependency."""
    kind = schema.get("type")
    good = {"object": isinstance(value, dict), "array": isinstance(value, list),
            "string": isinstance(value, str), "boolean": isinstance(value, bool),
            "number": type(value) in (int, float), "integer": type(value) is int}
    if kind and not good[kind]:
        raise ValueError(f"{path} must be {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']}")
    if kind == "object":
        missing = set(schema.get("required", [])) - value.keys()
        unknown = value.keys() - schema.get("properties", {}).keys()
        if missing:
            raise ValueError(f"{path} missing {', '.join(sorted(missing))}")
        if unknown and schema.get("additionalProperties") is False:
            raise ValueError(f"{path} unsupported fields: {', '.join(sorted(unknown))}")
        for key, item in value.items():
            if key in schema.get("properties", {}):
                validate(item, schema["properties"][key], f"{path}.{key}")
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", math.inf):
            raise ValueError(f"{path} has an unsupported number of items")
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")
        if schema.get("uniqueItems") and len(set(value)) != len(value):
            raise ValueError(f"{path} needs unique items")
    elif kind == "string" and len(value) < schema.get("minLength", 0):
        raise ValueError(f"{path} must not be empty")
    elif kind in ("number", "integer"):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if (not finite or value < schema.get("minimum", -math.inf)
                or value > schema.get("maximum", math.inf)
                or value <= schema.get("exclusiveMinimum", -math.inf)):
            raise ValueError(f"{path} is outside its documented finite range")
