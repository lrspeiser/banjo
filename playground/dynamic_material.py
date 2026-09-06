"""Bounded authoring and native execution of coupled small-strain impacts.

Labels never choose a law. The material-point descriptor supplies coefficients;
this route separately admits geometry, contact, time and work budgets.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "authoring"))
from material_behavior import MaterialBehavior


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _number_schema(low, high):
    return {"type": "number", "minimum": low, "maximum": high}


def _array_schema(size, item):
    return {"type": "array", "minItems": size, "maxItems": size, "items": item}


_POSITIVE = _number_schema(1e-12, 1e15)
_STRAIN = _number_schema(1e-8, .1)
_ISOTROPIC = {"young_modulus_pa": {**_POSITIVE, "description": "Young's modulus in PASCALS. 1 MPa = 1000000 Pa; never write 1 to mean 1 MPa."},
              "poisson_ratio": _number_schema(-.99, .49),
              "maximum_total_strain_norm": _STRAIN}
_PARAMETERS = {
    "isotropic_elastic": _ISOTROPIC,
    "orthotropic_elastic": {
        "young_modulus_pa": _array_schema(3, _POSITIVE),
        "poisson_xy_yz_zx": _array_schema(3, _number_schema(-.99, .49)),
        "shear_xy_yz_zx_pa": _array_schema(3, _POSITIVE),
        "maximum_total_strain_norm": _STRAIN},
    "j2_plastic": {**_ISOTROPIC, "initial_yield_stress_pa": _POSITIVE,
                   "isotropic_hardening_modulus_pa": _number_schema(0, 1e15)},
}
MATERIAL_SCHEMA = {"anyOf": [_object({
    "material_id": {"type": "string", "minLength": 1, "maxLength": 80},
    "name": {"type": "string", "minLength": 1, "maxLength": 120},
    "density_kg_m3": _number_schema(1, 30000),
    "mechanical_law": {"type": "string", "enum": [law]},
    "parameters": _object(parameters),
}) for law, parameters in _PARAMETERS.items()]}
IMPACT_SCHEMA = _object({
    "materials": {"type": "array", "minItems": 1, "maxItems": 3, "items": MATERIAL_SCHEMA},
    "dimensions_m": _array_schema(3, _number_schema(.01, .2)),
    "mesh_refinement": {"type": "integer", "minimum": 1, "maximum": 2},
    "sphere": _object({
        "radius_m": _number_schema(.002, .03),
        "density_kg_m3": _number_schema(1, 30000),
        "clearance_m": _number_schema(0, .005),
        "offset_xz_m": _array_schema(2, _number_schema(-.1, .1)),
        "speed_m_s": _number_schema(0, .2),
    }),
    "energy_budget_j": _number_schema(1e-9, 1e-3),
    "max_step_calls": {"type": "integer", "minimum": 3, "maximum": 200000},
})


def _validate_schema(value, schema):
    """Validate this small closed schema independently of model enforcement."""
    if "anyOf" in schema:
        for candidate in schema["anyOf"]:
            try:
                _validate_schema(value, candidate)
                return
            except ValueError:
                pass
        raise ValueError("Material must match one supported law and its exact SI parameters")
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["properties"]):
            raise ValueError("Unknown or missing dynamic impact fields")
        for key, child in schema["properties"].items():
            _validate_schema(value[key], child)
    elif kind == "array":
        if not isinstance(value, list) or not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise ValueError("Dynamic impact array has an invalid length")
        for item in value:
            _validate_schema(item, schema["items"])
    elif kind in ("number", "integer"):
        if type(value) not in ((int,) if kind == "integer" else (int, float)) or not math.isfinite(value):
            raise ValueError("Dynamic impact values must be finite SI numbers")
        if not schema["minimum"] <= value <= schema["maximum"]:
            raise ValueError("Dynamic impact value exceeds its declared admission bounds")
    elif kind == "string":
        if not isinstance(value, str) or not value.strip() or len(value) > schema.get("maxLength", 120):
            raise ValueError("Invalid dynamic material label")
        if any(ord(c) < 32 for c in value):
            raise ValueError("Invalid dynamic material label")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Unsupported dynamic material law")


def validate_impact(impact):
    _validate_schema(impact, IMPACT_SCHEMA)
    ids = set()
    for material in impact["materials"]:
        MaterialBehavior(**material)
        if material["material_id"] in ids:
            raise ValueError("Dynamic material IDs must be unique")
        ids.add(material["material_id"])
    sphere = impact["sphere"]
    for dim, offset in zip((impact["dimensions_m"][0], impact["dimensions_m"][2]), sphere["offset_xz_m"]):
        if abs(offset) + sphere["radius_m"] > dim / 2:
            raise ValueError("The sphere footprint must start inside the target surface")
    return impact


def native_request(impact, duration_s):
    validate_impact(impact)
    if type(duration_s) not in (int, float) or not math.isfinite(duration_s) or not .001 <= duration_s <= .1:
        raise ValueError("Dynamic material duration must be .001..0.1 seconds")
    result = deepcopy(impact)
    result.update(schema="banjo.dynamic-material-request.v1", duration_s=duration_s)
    result["materials"] = [MaterialBehavior(**material).to_dict() for material in impact["materials"]]
    return result


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate native recording key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("Nonfinite native recording value")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def validate_recording(recording, request):
    if not isinstance(recording, dict) or recording.get("schema") != "banjo.dynamic-material-playback.v1":
        raise ValueError("Native impact recording schema mismatch")
    if recording.get("request") != request or recording.get("physical_response_validated") is not False:
        raise ValueError("Native impact recording does not match the authored request")
    cases = recording.get("cases")
    if not isinstance(cases, list) or len(cases) != len(request["materials"]):
        raise ValueError("Native impact recording has incorrect material coverage")
    for case, material in zip(cases, request["materials"]):
        if case.get("material_id") != material["material_id"] or case.get("material") != material:
            raise ValueError("Native impact recording changed material properties")
        if case.get("status") not in ("complete", "solver_limit"):
            raise ValueError("Native impact recording status is invalid")
        mesh, frames = case.get("mesh", {}), case.get("frames")
        reference = mesh.get("reference_positions_m", [])
        if not 1 <= len(reference) <= 512 or not isinstance(frames, list) or not 1 <= len(frames) <= 102:
            raise ValueError("Native impact recording exceeds geometry/frame budget")
        previous = -1
        for frame in frames:
            t = frame.get("time_s")
            if type(t) not in (int, float) or not math.isfinite(t) or not previous < t <= request["duration_s"] + 1e-10:
                raise ValueError("Native impact recording time is invalid")
            previous = t
            vectors = [frame.get("sphere_center_m"), frame.get("sphere_velocity_m_s")]
            positions = frame.get("positions_m", [])
            if len(positions) != len(reference):
                raise ValueError("Native impact recording lost material nodes")
            for vector in vectors + positions:
                if not isinstance(vector, list) or len(vector) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
                    raise ValueError("Native impact recording contains invalid positions")
        if frames[0]["time_s"] != 0 or abs(case.get("summary", {}).get("completed_duration_s", -1) - previous) > 1e-10:
            raise ValueError("Native impact recording completion disagrees with frames")
        if case["status"] == "complete" and abs(previous - request["duration_s"]) > 1e-10:
            raise ValueError("Native impact recording claims incomplete time as complete")
    expected = "complete" if all(c["status"] == "complete" for c in cases) else "solver_limit"
    if recording.get("status") != expected:
        raise ValueError("Native impact recording aggregate status is invalid")
    return recording


def execute_impact(executable, request):
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise ValueError("Build banjo_dynamic_material_cli to run coupled material impacts")
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > 262144:
        raise ValueError("Dynamic impact input exceeds 256 KiB")
    try:
        result = subprocess.run([str(executable)], input=encoded, capture_output=True, timeout=75, check=False)
    except subprocess.TimeoutExpired:
        raise ValueError("Dynamic impact exceeded its 75-second execution budget") from None
    if result.returncode or len(result.stdout) > 64 * 1024 * 1024:
        raise ValueError("Native impact rejected the input or exceeded its output budget")
    recording = validate_recording(_strict_json(result.stdout), request)
    provenance = {"request_sha256": hashlib.sha256(encoded).hexdigest(),
                  "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                  "recording_sha256": hashlib.sha256(result.stdout).hexdigest()}
    return recording, provenance
