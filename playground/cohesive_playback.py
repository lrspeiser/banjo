"""Strict adapter from native cohesive impact evidence to dynamic viewer playback."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

NATIVE_SCHEMAS = {
    "banjo.cohesive-sphere-probe.v1": ("isotropic_elastic", False),
    "banjo.cohesive-sphere-probe.v2": ("corotated_isotropic", False),
    "banjo.cohesive-sphere-probe.v3": ("corotated_isotropic", True),
}
VIEWER_SCHEMA = "banjo.dynamic-material-playback.v1"
MAX_BYTES = 64 * 1024 * 1024
MAX_CASES = 8
MAX_FRAMES = 1002
MAX_NODES = 4096
MAX_TETS = 16384
MAX_TRIANGLES = 65536


def _object(value: Any, fields: set[str], required: set[str] | None = None) -> dict:
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError("unexpected cohesive playback fields")
    missing = (required or fields) - set(value)
    if missing:
        raise ValueError(f"missing cohesive playback field: {sorted(missing)[0]}")
    return value


def _number(value: Any, minimum: float = -math.inf, maximum: float = math.inf) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected finite cohesive numeric value")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError("cohesive numeric value outside bounds")
    return result


def _integer(value: Any, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError("cohesive integer value outside bounds")
    return value


def _vector(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("cohesive vector requires three entries")
    return [_number(entry, -1000, 1000) for entry in value]


def _topology(values: Any, width: int, node_count: int, maximum: int) -> list[list[int]]:
    if not isinstance(values, list) or len(values) > maximum:
        raise ValueError("cohesive topology count outside bounds")
    result = []
    for value in values:
        if not isinstance(value, list) or len(value) != width:
            raise ValueError("malformed cohesive topology")
        indices = [_integer(index, node_count - 1) for index in value]
        if len(set(indices)) != width:
            raise ValueError("degenerate cohesive topology")
        result.append(indices)
    return result


def _nonnegative_summary(summary: dict, field: str, integer: bool = False) -> Any:
    value = summary[field]
    return _integer(value, 1_000_000_000) if integer else _number(value, 0)


def _adapt_case(case: Any, native_schema: str) -> dict:
    allowed = {"name", "scope", "bulk", "interface", "sphere", "requested_duration_s",
               "stable_time_step_s", "time_step_s", "limitations", "mesh", "frames",
               "summary", "finite_facet_closure_contact",
               "maximum_closure_compression_fraction"}
    legacy_optional = ({"finite_facet_closure_contact",
                        "maximum_closure_compression_fraction"}
                       if native_schema.endswith(".v1") else set())
    case = _object(case, allowed, allowed - legacy_optional)
    if not isinstance(case["name"], str) or not case["name"]:
        raise ValueError("invalid cohesive case name")
    bulk = _object(case["bulk"], {"law", "young_modulus_pa", "poisson_ratio",
                                  "density_kg_m3"})
    interface = _object(case["interface"], {"stiffness_pa_per_m",
                                             "tangential_stiffness_pa_per_m", "strength_pa",
                                             "fracture_energy_j_m2"})
    sphere = _object(case["sphere"], {"radius_m", "density_kg_m3", "mass_kg",
                                      "initial_speed_m_s"})
    for field in ("young_modulus_pa", "density_kg_m3"):
        _number(bulk[field], 0)
    _number(bulk["poisson_ratio"], -1, .5)
    expected_law, expected_closure = NATIVE_SCHEMAS[native_schema]
    if bulk["law"] != expected_law:
        raise ValueError("cohesive bulk law does not match native schema")
    declared_closure = case.get("finite_facet_closure_contact", False)
    if not isinstance(declared_closure, bool) or declared_closure != expected_closure:
        raise ValueError("facet closure mode does not match native schema")
    overlap_fraction = _number(case.get("maximum_closure_compression_fraction", 0.), 0, 1)
    for value in interface.values():
        _number(value, 0)
    radius = _number(sphere["radius_m"], 1e-9, 10)
    mass = _number(sphere["mass_kg"], 1e-12, 1e9)
    _number(sphere["density_kg_m3"], 0)
    _number(sphere["initial_speed_m_s"], 0, 1e4)
    requested = _number(case["requested_duration_s"], 0, 100)
    _number(case["stable_time_step_s"], 0, 1)
    _number(case["time_step_s"], 0, 1)
    if not isinstance(case["scope"], str) or not isinstance(case["limitations"], list) or not all(
            isinstance(item, str) for item in case["limitations"]):
        raise ValueError("invalid cohesive scope or limitations")

    mesh = _object(case["mesh"], {"reference_positions_m", "tetrahedra",
                                  "boundary_triangles"})
    reference = mesh["reference_positions_m"]
    if not isinstance(reference, list) or not 4 <= len(reference) <= MAX_NODES:
        raise ValueError("cohesive node count outside bounds")
    reference = [_vector(value) for value in reference]
    tetrahedra = _topology(mesh["tetrahedra"], 4, len(reference), MAX_TETS)
    if not tetrahedra:
        raise ValueError("cohesive mesh requires tetrahedra")
    original_boundaries = _topology(mesh["boundary_triangles"], 3, len(reference),
                                    MAX_TRIANGLES)

    native_frames = case["frames"]
    if not isinstance(native_frames, list) or not 1 <= len(native_frames) <= MAX_FRAMES:
        raise ValueError("cohesive frame count outside bounds")
    frames = []
    previous_time = -math.inf
    for native in native_frames:
        frame_fields = {"time_s", "sphere_center_m", "sphere_velocity_m_s", "positions_m",
                        "contacts", "maximum_damage", "fully_separated_facets", "components",
                        "component_by_tetrahedron", "newly_exposed_faces",
                        "fracture_dissipation_j", "energy_residual_j",
                        "bulk_stored_energy_j", "cohesive_stored_energy_j",
                        "interface_contact_stored_energy_j", "compressed_separated_facets"}
        optional_frame_fields = {"energy_residual_j", "bulk_stored_energy_j",
                                 "cohesive_stored_energy_j",
                                 "interface_contact_stored_energy_j",
                                 "compressed_separated_facets"}
        native = _object(native, frame_fields, frame_fields - optional_frame_fields)
        time = _number(native["time_s"], 0, requested)
        if time <= previous_time:
            raise ValueError("cohesive frame times must increase strictly")
        previous_time = time
        positions = native["positions_m"]
        if not isinstance(positions, list) or len(positions) != len(reference):
            raise ValueError("cohesive frame node layout changed")
        positions = [_vector(value) for value in positions]
        exposed = _topology(native["newly_exposed_faces"], 3, len(reference), MAX_TRIANGLES)
        if len(original_boundaries) + len(exposed) > MAX_TRIANGLES:
            raise ValueError("cohesive boundary triangle count outside bounds")
        boundaries = copy.deepcopy(original_boundaries) + copy.deepcopy(exposed)
        component_ids = native["component_by_tetrahedron"]
        if not isinstance(component_ids, list) or len(component_ids) != len(tetrahedra):
            raise ValueError("cohesive component layout changed")
        component_ids = [_integer(value, len(tetrahedra) - 1) for value in component_ids]
        components = _integer(native["components"], len(tetrahedra))
        if components < 1 or len(set(component_ids)) != components:
            raise ValueError("inconsistent cohesive component count")
        frame = copy.deepcopy(native)
        frame.update({"time_s": time, "positions_m": positions,
                      "sphere_center_m": _vector(native["sphere_center_m"]),
                      "sphere_velocity_m_s": _vector(native["sphere_velocity_m_s"]),
                      "boundary_triangles": boundaries, "newly_exposed_faces": exposed,
                      "component_by_tetrahedron": component_ids,
                      "maximum_equivalent_plastic_strain": 0.0,
                      "plastic_dissipation_j": 0.0})
        _integer(native["contacts"], 1_000_000)
        _number(native["maximum_damage"], 0, 1 + 1e-12)
        _integer(native["fully_separated_facets"], MAX_TRIANGLES)
        _number(native["fracture_dissipation_j"], 0, 1e12)
        if "energy_residual_j" in native:
            _number(native["energy_residual_j"], -1e12, 1e12)
        for field in ("bulk_stored_energy_j", "cohesive_stored_energy_j",
                      "interface_contact_stored_energy_j"):
            if field in native:
                _number(native[field], 0, 1e12)
        if "compressed_separated_facets" in native:
            _integer(native["compressed_separated_facets"], MAX_TRIANGLES)
        frames.append(frame)

    summary_fields = {"status", "error", "completed_duration_s", "steps",
                      "accepted_contacts", "maximum_damage",
                      "maximum_fully_separated_facets", "maximum_components",
                      "newly_exposed_faces_final", "geometry_queries",
                      "geometry_iterations", "cumulative_energy_residual_j",
                      "cumulative_absolute_energy_residual_j", "wall_ms",
                      "maximum_compressed_separated_facets",
                      "maximum_closure_compression_m", "closure_projection_queries",
                      "interface_contact_stored_energy_final_j",
                      "rejected_contact_handoff"}
    closure_summary_fields = {"maximum_compressed_separated_facets",
                              "maximum_closure_compression_m",
                              "closure_projection_queries",
                              "interface_contact_stored_energy_final_j"}
    required_summary = summary_fields - {"rejected_contact_handoff"}
    if native_schema != "banjo.cohesive-sphere-probe.v3":
        required_summary -= closure_summary_fields
    summary = _object(case["summary"], summary_fields, required_summary)
    status = summary["status"]
    if status not in {"complete", "solver_limit"} or not isinstance(summary["error"], str):
        raise ValueError("invalid cohesive completion status")
    completed = _number(summary["completed_duration_s"], 0, requested)
    if abs(frames[-1]["time_s"] - completed) > 1e-12:
        raise ValueError("cohesive final frame does not match completed duration")
    if status == "complete" and abs(completed - requested) > 1e-12:
        raise ValueError("cohesive complete case did not reach requested duration")
    for field in ("steps", "accepted_contacts", "maximum_fully_separated_facets",
                  "maximum_components", "newly_exposed_faces_final", "geometry_queries",
                  "geometry_iterations"):
        _nonnegative_summary(summary, field, True)
    for field in ("maximum_compressed_separated_facets", "closure_projection_queries"):
        if field in summary:
            _nonnegative_summary(summary, field, True)
    for field in ("maximum_damage", "cumulative_absolute_energy_residual_j", "wall_ms"):
        _nonnegative_summary(summary, field)
    for field in ("maximum_closure_compression_m",
                  "interface_contact_stored_energy_final_j"):
        if field in summary:
            _nonnegative_summary(summary, field)
    _number(summary["cumulative_energy_residual_j"], -1e12, 1e12)
    if "rejected_contact_handoff" in summary:
        handoff = _object(summary["rejected_contact_handoff"],
                          {"facet_index", "retained_compression_energy_j"})
        _integer(handoff["facet_index"], MAX_TRIANGLES)
        _number(handoff["retained_compression_energy_j"], 0, 1e12)

    return {"material_id": f"fictional-cohesive-{case['name']}",
            "material": {"material_id": f"fictional-cohesive-{case['name']}",
                         "name": case["name"], "units": "SI",
                         "mechanical_law": copy.deepcopy(bulk),
                         "cohesive_interface": copy.deepcopy(interface),
                         "physical_response_validated": False},
            "status": status,
            "mesh": {"reference_positions_m": reference, "tetrahedra": tetrahedra,
                     "boundary_triangles": copy.deepcopy(original_boundaries)},
            "sphere_radius_m": radius, "sphere_mass_kg": mass,
            "frames": frames, "summary": copy.deepcopy(summary),
            "requested_duration_s": requested, "completed_duration_s": completed,
            "error": summary["error"] if status == "solver_limit" else "",
            "native_scope": case["scope"], "limitations": copy.deepcopy(case["limitations"]),
            "declared_bulk_mode": bulk["law"],
            "finite_facet_closure_contact": expected_closure,
            "maximum_closure_compression_fraction": overlap_fraction}


def adapt_cohesive_playback(recording: Any) -> dict:
    recording = _object(recording, {"schema", "cases"})
    if recording["schema"] not in NATIVE_SCHEMAS:
        raise ValueError("unsupported cohesive native schema")
    if not isinstance(recording["cases"], list) or not 1 <= len(recording["cases"]) <= MAX_CASES:
        raise ValueError("cohesive case count outside bounds")
    native_schema = recording["schema"]
    cases = [_adapt_case(case, native_schema) for case in recording["cases"]]
    status = "complete" if all(case["status"] == "complete" for case in cases) else "solver_limit"
    return {"schema": VIEWER_SCHEMA, "native_schema": native_schema,
            "origin": "native launched-sphere cohesive development reference recording",
            "physical_response_validated": False, "status": status,
            "scope": "Fictional SI launched-sphere cohesive development reference playback; "
                     "no calibrated glass, GPT-authored material, cutting, or general fracture claim",
            "cases": cases}


def load_and_adapt(path: Path) -> dict:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("cohesive recording exceeds byte limit")
    return adapt_cohesive_playback(json.loads(path.read_text(encoding="utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    adapted = load_and_adapt(args.input)
    text = json.dumps(adapted, separators=(",", ":"), allow_nan=False)
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("adapted cohesive playback exceeds byte limit")
    args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
