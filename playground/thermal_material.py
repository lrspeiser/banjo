"""Strict authoring boundary for bounded native solid thermal experiments.

All material and reaction behavior comes from explicit numeric SI descriptors.
Names are retained as labels and never select a law.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any

REQUEST_SCHEMA = "banjo.thermal-experiment-request.v1"
RESPONSE_SCHEMA = "banjo.thermal-experiment-response.v1"
MAX_INPUT_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
EXECUTION_TIMEOUT_S = 75
LIMITATIONS = (
    "insulated fixed-grid solid thermal reference",
    "no airflow, smoke, radiation, moisture transport or calibrated combustion",
    "no mechanical deformation, contact, fracture or thermal expansion coupling",
    "phase change and reaction cannot be combined",
)


def _schema_object(properties: dict) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _schema_number(low: float, high: float) -> dict:
    return {"type": "number", "minimum": low, "maximum": high}


_POSITIVE = _schema_number(1e-12, 1e15)
_BASE_MATERIAL = {
    "id": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
    "name": {"type": "string", "minLength": 1, "maxLength": 128},
    "density_kg_m3": _schema_number(1e-12, 30_000),
    "heat_capacity_j_kg_k": _POSITIVE,
    "conductivity_w_m_k": _schema_number(0, 1e15),
}
_REACTION = {
    "fuel_fraction": _schema_number(0, 1),
    "oxygen_per_kg_solid": _schema_number(0, 10),
    "reaction": _schema_object({
        "activation_temperature_k": _schema_number(0, 10_000),
        "rate_per_s": _POSITIVE,
        "heat_of_combustion_j_kg": _POSITIVE,
        "oxygen_per_kg_fuel": _POSITIVE,
    }),
}
_PHASE = {"phase_change": _schema_object({
    "liquid_heat_capacity_j_kg_k": _POSITIVE,
    "melting_temperature_k": _schema_number(1e-12, 10_000),
    "latent_heat_j_kg": _schema_number(0, 1e15),
})}
_INTEGER_TRIPLE = {"type": "array", "minItems": 3, "maxItems": 3,
                   "items": {"type": "integer"}}
THERMAL_EXPERIMENT_SCHEMA = _schema_object({
    "voxel_size_m": _schema_number(.001, 10),
    "materials": {"type": "array", "minItems": 1, "maxItems": 16,
                  "items": {"anyOf": [_schema_object(_BASE_MATERIAL),
                                       _schema_object({**_BASE_MATERIAL, **_REACTION}),
                                       _schema_object({**_BASE_MATERIAL, **_PHASE})]}},
    "cells": {"type": "array", "minItems": 1, "maxItems": 16,
              "items": {"anyOf": [
                  _schema_object({"chunk": _INTEGER_TRIPLE, "local": _INTEGER_TRIPLE,
                                  "material": {"type": "integer"},
                                  "temperature_k": _schema_number(0, 10_000)}),
                  _schema_object({"chunk": _INTEGER_TRIPLE, "local": _INTEGER_TRIPLE,
                                  "material": {"type": "integer"},
                                  "temperature_k": _schema_number(0, 10_000),
                                  "liquid_fraction_at_melt": _schema_number(0, 1)})]}},
    "heater": _schema_object({"cell_index": {"type": "integer"},
                              "energy_j": _schema_number(0, 1e12),
                              "maximum_energy_j": _schema_number(0, 1e12)}),
    "step_s": _schema_number(.001, .25),
    "horizon_s": _schema_number(.001, 10),
    "limits": _schema_object({
        "maximum_jobs": {"type": "integer", "minimum": 1, "maximum": 4096},
        "maximum_cell_operations": {"type": "integer", "minimum": 1,
                                    "maximum": 10_000_000},
        "maximum_wall_ms": _schema_number(.001, 1000),
        "maximum_frames": {"type": "integer", "minimum": 2, "maximum": 1024},
    }),
})


def _object(value: Any, allowed: set[str], required: set[str] | None = None, message="Invalid thermal object") -> dict:
    if not isinstance(value, dict) or set(value) - allowed or not (required or allowed) <= set(value):
        raise ValueError(message)
    return value


def _number(value: Any, low: float, high: float, message="Thermal SI number outside bounds") -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(message)
    return float(value)


def _integer(value: Any, low: int, high: int, message="Thermal integer outside bounds") -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(message)
    return value


def _triple(value: Any, low: int, high: int) -> list[int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("Thermal cell coordinates require integer triples")
    return [_integer(entry, low, high) for entry in value]


def _material(value: Any) -> dict:
    allowed = {"id", "name", "density_kg_m3", "heat_capacity_j_kg_k",
               "conductivity_w_m_k", "fuel_fraction", "oxygen_per_kg_solid",
               "reaction", "phase_change"}
    required = {"id", "name", "density_kg_m3", "heat_capacity_j_kg_k",
                "conductivity_w_m_k"}
    value = _object(value, allowed, required, "Unknown or missing thermal material field")
    _integer(value["id"], 1, 1_000_000)
    name = value["name"]
    if not isinstance(name, str) or not name or len(name) > 128 or any(ord(c) < 32 for c in name):
        raise ValueError("Invalid thermal material label")
    _number(value["density_kg_m3"], math.nextafter(0.0, 1.0), 30_000)
    _number(value["heat_capacity_j_kg_k"], math.nextafter(0.0, 1.0), 1e15)
    _number(value["conductivity_w_m_k"], 0, 1e15)
    _number(value.get("fuel_fraction", 0), 0, 1)
    _number(value.get("oxygen_per_kg_solid", 0), 0, 10)
    if "reaction" in value:
        reaction = _object(value["reaction"],
            {"activation_temperature_k", "rate_per_s", "heat_of_combustion_j_kg",
             "oxygen_per_kg_fuel"}, message="Unknown or missing thermal reaction field")
        _number(reaction["activation_temperature_k"], 0, 10_000)
        for field in ("rate_per_s", "heat_of_combustion_j_kg", "oxygen_per_kg_fuel"):
            _number(reaction[field], math.nextafter(0.0, 1.0), 1e15)
        if "fuel_fraction" not in value or "oxygen_per_kg_solid" not in value:
            raise ValueError("Reactive material requires explicit fuel and oxygen inventory")
    if "phase_change" in value:
        phase = _object(value["phase_change"],
            {"liquid_heat_capacity_j_kg_k", "melting_temperature_k", "latent_heat_j_kg"},
            message="Unknown or missing thermal phase-change field")
        _number(phase["liquid_heat_capacity_j_kg_k"], math.nextafter(0.0, 1.0), 1e15)
        _number(phase["melting_temperature_k"], math.nextafter(0.0, 1.0), 10_000)
        _number(phase["latent_heat_j_kg"], 0, 1e15)
    if "reaction" in value and "phase_change" in value:
        raise ValueError("Combined reaction and phase change is unsupported")
    return value


def validate_experiment(experiment: Any) -> dict:
    fields = {"voxel_size_m", "materials", "cells", "heater", "step_s",
              "horizon_s", "limits"}
    experiment = _object(experiment, fields, message="Unknown or missing thermal experiment field")
    _number(experiment["voxel_size_m"], .001, 10)
    materials = experiment["materials"]
    if not isinstance(materials, list) or not 1 <= len(materials) <= 16:
        raise ValueError("Thermal experiment requires 1..16 materials")
    ids = set()
    for material in materials:
        _material(material)
        if material["id"] in ids:
            raise ValueError("Thermal material IDs must be unique")
        ids.add(material["id"])
    cells = experiment["cells"]
    if not isinstance(cells, list) or not 1 <= len(cells) <= 16:
        raise ValueError("Thermal experiment requires 1..16 cells")
    addresses = set()
    chunk_declarations = {}
    for cell in cells:
        cell = _object(cell, {"chunk", "local", "material", "temperature_k",
                             "liquid_fraction_at_melt"},
                       {"chunk", "local", "material", "temperature_k"},
                       "Unknown or missing thermal cell field")
        chunk = tuple(_triple(cell["chunk"], -1_000_000, 1_000_000))
        local = tuple(_triple(cell["local"], 0, 15))
        if (chunk, local) in addresses:
            raise ValueError("Thermal cells must have unique addresses")
        addresses.add((chunk, local))
        material = _integer(cell["material"], 1, 1_000_000)
        if material not in ids:
            raise ValueError("Thermal cell references unknown material")
        temperature = _number(cell["temperature_k"], 0, 10_000)
        liquid = _number(cell.get("liquid_fraction_at_melt", 0), 0, 1)
        declaration = (material, temperature, liquid)
        if chunk in chunk_declarations and chunk_declarations[chunk] != declaration:
            raise ValueError("Cells in one compact chunk require identical initial state")
        chunk_declarations[chunk] = declaration
        selected = next(item for item in materials if item["id"] == material)
        if liquid and "phase_change" not in selected:
            raise ValueError("Liquid fraction requires a phase-change material")
    heater = _object(experiment["heater"], {"cell_index", "energy_j", "maximum_energy_j"},
                     message="Unknown or missing thermal heater field")
    _integer(heater["cell_index"], 0, len(cells) - 1)
    _number(heater["energy_j"], 0, 1e12)
    _number(heater["maximum_energy_j"], 0, 1e12)
    dt = _number(experiment["step_s"], .001, .25)
    horizon = _number(experiment["horizon_s"], .001, 10)
    count = horizon / dt
    if abs(count - round(count)) > 1e-10 * max(1, count):
        raise ValueError("Thermal horizon must contain whole fixed steps")
    limits = _object(experiment["limits"], {"maximum_jobs", "maximum_cell_operations",
                                            "maximum_wall_ms", "maximum_frames"},
                     message="Unknown or missing thermal work-limit field")
    _integer(limits["maximum_jobs"], 1, 4096)
    _integer(limits["maximum_cell_operations"], 1, 10_000_000)
    _number(limits["maximum_wall_ms"], .001, 1000)
    _integer(limits["maximum_frames"], 2, 1024)
    return experiment


def native_request(experiment: Any) -> dict:
    validate_experiment(experiment)
    request = deepcopy(experiment)
    request["schema"] = REQUEST_SCHEMA
    return request


def _strict_json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate native thermal response field")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(
                          ValueError("Nonfinite native thermal response value")))


def _finite_tree(value: Any) -> None:
    if type(value) is float and not math.isfinite(value):
        raise ValueError("Native thermal response contains nonfinite values")
    if isinstance(value, dict):
        for child in value.values():
            _finite_tree(child)
    elif isinstance(value, list):
        for child in value:
            _finite_tree(child)


def validate_response(response: Any, request: dict) -> dict:
    required = {"schema", "status", "request", "frames", "completed_time_s",
                "requested_horizon_s", "remaining_duration_s", "scheduler_backlog_s",
                "work", "final_ledger", "limitations"}
    response = _object(response, required | {"error"}, required,
                       "Unknown or missing native thermal response field")
    _finite_tree(response)
    if response["schema"] != RESPONSE_SCHEMA or response["request"] != request:
        raise ValueError("Native thermal response does not match the authored request")
    if response["status"] not in ("complete", "solver_limit"):
        raise ValueError("Native thermal response status is invalid")
    if response["status"] == "solver_limit" and not isinstance(response.get("error"), str):
        raise ValueError("Limited native thermal response requires an error")
    horizon = request["horizon_s"]
    completed = _number(response["completed_time_s"], 0, horizon + 1e-10)
    remaining = _number(response["remaining_duration_s"], 0, horizon)
    _number(response["scheduler_backlog_s"], 0, horizon)
    if abs(completed + remaining - horizon) > 1e-9:
        raise ValueError("Native thermal completion accounting is inconsistent")
    if response["status"] == "complete" and (remaining != 0 or completed + 1e-10 < horizon):
        raise ValueError("Native thermal response claims incomplete work as complete")
    frames = response["frames"]
    if not isinstance(frames, list) or not 1 <= len(frames) <= request["limits"]["maximum_frames"]:
        raise ValueError("Native thermal frame count is outside the authored bound")
    previous = -1.0
    for frame in frames:
        if not isinstance(frame, dict) or set(frame) != {"time_s", "cells", "ledger"}:
            raise ValueError("Native thermal frame layout is invalid")
        time = _number(frame["time_s"], 0, horizon + 1e-10)
        if time <= previous:
            raise ValueError("Native thermal frame times must increase")
        previous = time
        if not isinstance(frame["cells"], list) or len(frame["cells"]) != len(request["cells"]):
            raise ValueError("Native thermal frame cell coverage changed")
        if not isinstance(frame["ledger"], dict):
            raise ValueError("Native thermal frame ledger is missing")
    if abs(previous - completed) > 1e-9:
        raise ValueError("Native thermal final frame disagrees with completion")
    if not isinstance(response["final_ledger"], dict) or response["final_ledger"] != frames[-1]["ledger"]:
        raise ValueError("Native thermal final ledger changed")
    if not isinstance(response["limitations"], list) or not all(
            isinstance(item, str) for item in response["limitations"]):
        raise ValueError("Native thermal limitations are invalid")
    for limitation in LIMITATIONS[:2] + LIMITATIONS[3:]:
        if limitation not in response["limitations"]:
            raise ValueError("Native thermal response omits a declared limitation")
    return response


def execute_experiment(executable: str | Path, experiment: Any) -> tuple[dict, dict]:
    request = native_request(experiment)
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise ValueError("Build banjo_thermal_experiment_cli to run thermal experiments")
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_INPUT_BYTES:
        raise ValueError("Thermal experiment input exceeds 256 KiB")
    try:
        process = subprocess.run([str(executable)], input=encoded, capture_output=True,
                                 timeout=EXECUTION_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        raise ValueError("Thermal experiment exceeded its 75-second execution budget") from None
    if process.returncode:
        raise ValueError("Native thermal experiment rejected the request")
    if len(process.stdout) > MAX_OUTPUT_BYTES:
        raise ValueError("Native thermal response exceeds 8 MiB")
    response = deepcopy(validate_response(_strict_json(process.stdout), request))
    for limitation in LIMITATIONS:
        if limitation not in response["limitations"]:
            response["limitations"].append(limitation)
    provenance = {
        "request_sha256": hashlib.sha256(encoded).hexdigest(),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "response_sha256": hashlib.sha256(process.stdout).hexdigest(),
        "native_schema": RESPONSE_SCHEMA,
    }
    return response, provenance
