"""Bounded, deterministic diagnostics for native playground recordings.

The output is intended as compact input for later analysis.  It only derives
claims supported by the package and sampled playback positions; it performs no
I/O and does not treat proximity as solver contact or material validation.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


SCHEMA = "banjo.experiment-diagnostics.v1"
_DYNAMIC_MATERIAL_SCHEMA = "banjo.dynamic-material-playback.v1"
_MAX_ITEMS = 64
_MAX_DEPTH = 8
_MAX_STRING = 4096


def _finite_number(value: Any) -> float | None:
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    return None


def _vec3(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 3:
        return None
    result = [_finite_number(item) for item in value]
    return None if any(item is None for item in result) else result  # type: ignore[return-value]


def _package_sha256(package: Any) -> str:
    encoded = json.dumps(package, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _numeric_descriptor(value: Any) -> Any:
    """Keep numeric material inputs while excluding labels from identity."""
    if type(value) in (int, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_numeric_descriptor(item) for item in value
                if _numeric_descriptor(item) is not None]
    if isinstance(value, dict):
        return {str(key): numeric for key, item in value.items()
                if (numeric := _numeric_descriptor(item)) is not None}
    return None


def _material_evidence_descriptor(material: dict[str, Any]) -> dict[str, Any]:
    """Law plus numeric SI inputs; excludes names, IDs and supplied hashes."""
    result = {"mechanical_law": material.get("mechanical_law")}
    for key in ("density_kg_m3", "parameters"):
        numeric = _numeric_descriptor(material.get(key))
        if numeric is not None:
            result[key] = numeric
    return result


def _bounded_json(value: Any, depth: int = 0) -> Any:
    """Copy JSON data with explicit depth, item, key and string bounds."""
    if depth >= _MAX_DEPTH:
        return {"truncated": True}
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value if len(value) <= _MAX_STRING else value[:_MAX_STRING]
    if isinstance(value, list):
        result = [_bounded_json(item, depth + 1) for item in value[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            result.append({"truncated_items": len(value) - _MAX_ITEMS})
        return result
    if isinstance(value, dict):
        result = {}
        keys = list(value)[:_MAX_ITEMS]
        for key in keys:
            result[str(key)[:_MAX_STRING]] = _bounded_json(value[key], depth + 1)
        if len(value) > _MAX_ITEMS:
            result["_truncated_keys"] = len(value) - _MAX_ITEMS
        return result
    return str(value)[:_MAX_STRING]


def _drop_height(package: dict[str, Any]) -> float | None:
    """Recover authored projectile-bottom clearance from a compiled package."""
    objects = {obj.get("id"): obj for obj in package.get("objects", []) if isinstance(obj, dict)}
    heights = []
    for target_id, projectile_id in ((1, 2), (3, 4), (5, 6)):
        target, projectile = objects.get(target_id), objects.get(projectile_id)
        if not isinstance(target, dict) or not isinstance(projectile, dict):
            continue
        tp, pp = _vec3(target.get("position_m")), _vec3(projectile.get("position_m"))
        td, pd = _vec3(target.get("dimensions_m")), _vec3(projectile.get("dimensions_m"))
        if None not in (tp, pp, td, pd):
            heights.append(pp[1] - pd[1] / 2 - (tp[1] + td[2] / 2))  # type: ignore[index]
    if not heights or max(heights) - min(heights) > 1e-9:
        return None
    return sum(heights) / len(heights)


def _result(name: str, status: str, observation: str, scope: str,
            evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    item = {"check": name, "status": status, "observation": observation, "scope": scope}
    if evidence:
        item["evidence"] = evidence
    return item


def _scene_summary(package: dict[str, Any]) -> dict[str, Any]:
    objects = package.get("objects") if isinstance(package.get("objects"), list) else []
    materials = package.get("materials") if isinstance(package.get("materials"), list) else []
    summary = []
    for obj in objects[:12]:
        if not isinstance(obj, dict):
            continue
        summary.append({key: obj.get(key) for key in
                        ("id", "name", "material", "shape", "dimensions_m", "representation")})
    material_ids = [str(item.get("id"))[:_MAX_STRING] for item in materials[:_MAX_ITEMS]
                    if isinstance(item, dict) and isinstance(item.get("id"), str)]
    return {
        "object_count": len(objects),
        "material_count": len(materials),
        "material_ids": material_ids,
        "objects": summary,
        "objects_truncated": len(objects) > 12,
    }


def _dynamic_material_diagnostics(package: dict[str, Any],
                                  recording: dict[str, Any]) -> dict[str, Any]:
    """Compact native evidence for the bounded dynamic-material experiment."""
    request = recording.get("request") if isinstance(recording.get("request"), dict) else {}
    requested_duration = _finite_number(request.get("duration_s"))
    budget = _finite_number(request.get("energy_budget_j"))
    sphere = request.get("sphere") if isinstance(request.get("sphere"), dict) else {}
    clearance = _finite_number(sphere.get("clearance_m"))
    speed = _finite_number(sphere.get("speed_m_s"))
    flight = None
    if clearance is not None and clearance >= 0 and speed is not None and speed >= 0:
        flight = (math.sqrt(speed * speed + 2 * 9.81 * clearance) - speed) / 9.81

    input_materials = request.get("materials") if isinstance(request.get("materials"), list) else []
    material_inputs = []
    for material in input_materials[:3]:
        if isinstance(material, dict):
            numeric = _material_evidence_descriptor(material)
            material_inputs.append({"material_id": _bounded_json(material.get("material_id")),
                                    "numeric": _bounded_json(numeric),
                                    "sha256": _package_sha256(numeric)})

    cases = recording.get("cases") if isinstance(recording.get("cases"), list) else []
    compact_cases = []
    checks = []
    for index, case in enumerate(cases[:3]):
        if not isinstance(case, dict):
            continue
        summary = case.get("summary") if isinstance(case.get("summary"), dict) else {}
        status = case.get("status") if case.get("status") in ("complete", "solver_limit") else "solver_limit"
        completed = _finite_number(summary.get("completed_duration_s"))
        requested = _finite_number(summary.get("requested_duration_s"))
        if requested is None:
            requested = requested_duration
        contacts = summary.get("accepted_contacts") if type(summary.get("accepted_contacts")) is int else None
        absolute_residual = _finite_number(summary.get("absolute_energy_residual_j"))
        case_budget = _finite_number(summary.get("energy_budget_j"))
        if case_budget is None:
            case_budget = budget
        scaled_budget = (case_budget * requested / .1
                         if case_budget is not None and requested is not None else None)
        plastic_dissipation = _finite_number(summary.get("plastic_dissipation_j"))
        frames = case.get("frames") if isinstance(case.get("frames"), list) else []
        maximum_plastic = 0.0
        for frame in frames:
            if isinstance(frame, dict):
                value = _finite_number(frame.get("maximum_equivalent_plastic_strain"))
                if value is not None:
                    maximum_plastic = max(maximum_plastic, value)
        material = case.get("material") if isinstance(case.get("material"), dict) else {}
        evidence = {
            "material_id": _bounded_json(case.get("material_id")),
            "material": _bounded_json(material),
            "material_numeric_sha256": _package_sha256(_material_evidence_descriptor(material)),
            "status": status,
            "error": _bounded_json(case.get("error", "")),
            "completed_duration_s": completed,
            "requested_duration_s": requested,
            "accepted_contacts": contacts,
            "contact_evidence": "native_solver_counter" if contacts is not None else "unavailable",
            "absolute_energy_residual_j": absolute_residual,
            "contact_dissipation_j": _finite_number(summary.get("contact_dissipation_j")),
            "normal_constraint_projection_loss_j": _finite_number(summary.get("normal_constraint_projection_loss_j")),
            "tangential_constraint_projection_loss_j": _finite_number(summary.get("tangential_constraint_projection_loss_j")),
            "normal_projection_scope": "Numerical force-kick projection diagnostic; not irreversible heat. The raw physical energy residual remains checked.",
            "tangential_projection_scope": "Numerical sticking-friction force-kick projection; not sliding heat. Incoming slip and saturated Coulomb friction remain physical dissipation; the raw physical energy residual remains checked.",
            "stopped_advance": _bounded_json(summary.get("stopped_advance")),
            "scaled_energy_budget_j": scaled_budget,
            "energy_budget_met": (absolute_residual <= scaled_budget
                                  if absolute_residual is not None and scaled_budget is not None else None),
            "step_calls": summary.get("step_calls") if type(summary.get("step_calls")) is int else None,
            "wall_ms": _finite_number(summary.get("wall_ms")),
            "plastic_dissipation_j": plastic_dissipation,
            "maximum_equivalent_plastic_strain": maximum_plastic,
            "observed_plastic_response": maximum_plastic > 0 or (plastic_dissipation or 0) > 0,
            "permanent_dent_supported": False,
            "sampled_peak_upward_speed_m_s": _finite_number(summary.get("sampled_peak_upward_speed_m_s")),
            "sampled_peak_displacement_m": _finite_number(summary.get("sampled_peak_displacement_m")),
        }
        compact_cases.append(evidence)
        complete = status == "complete" and completed is not None and requested is not None and completed >= requested - 1e-12
        checks.append(_result(f"case_{index}_completion", "pass" if complete else "fail",
                              "requested_duration_completed" if complete else "solver_stopped_before_requested_duration",
                              "native adaptive solver status and duration counters",
                              {"material_id": evidence["material_id"], "completed_duration_s": completed,
                               "requested_duration_s": requested}))
        contact_status = "pass" if contacts is not None and contacts > 0 else ("fail" if contacts == 0 else "unknown")
        checks.append(_result(f"case_{index}_contact", contact_status,
                              "native_solver_reported_contact" if contact_status == "pass" else
                              "native_solver_reported_zero_contacts" if contact_status == "fail" else
                              "native_contact_counter_unavailable",
                              "native accepted-contact counter; sampled proximity is not used"))

    timing = {"estimated_pre_contact_flight_s": flight,
              "requested_duration_s": requested_duration,
              "estimated_post_flight_observation_s": (requested_duration - flight
                                                       if requested_duration is not None and flight is not None else None),
              "model": "constant gravity from authored clearance and downward speed"}
    return {
        "schema": SCHEMA,
        "source_schema": _DYNAMIC_MATERIAL_SCHEMA,
        "native_facts": {"status": _bounded_json(recording.get("status")),
                         "physical_response_validated": recording.get("physical_response_validated"),
                         "request": _bounded_json({key: request.get(key) for key in
                            ("duration_s", "energy_budget_j", "max_step_calls", "dimensions_m",
                             "mesh_refinement", "sphere")}),
                         "cases": compact_cases,
                         "cases_truncated": len(cases) > 3},
        "package": {"sha256": _package_sha256(package),
                    "input_materials": material_inputs,
                    "input_materials_truncated": len(input_materials) > 3},
        "expectations": [{"kind": "flight_window", **timing}],
        "checks": checks,
        "validity": {"physical_response_validated": False},
        "limitations": [
            "Accepted-contact counts are native solver evidence; sampled proximity is not contact evidence.",
            "Observed plastic strain or dissipation does not establish a permanent dent.",
            "Wall time is diagnostic timing and is not a realtime-performance claim.",
            "The dynamic patch does not model fracture, so fragment absence is not a failure criterion.",
        ],
    }


def _poses_by_frame(recording: dict[str, Any]) -> list[tuple[float, dict[str, list[float]]]]:
    result = []
    frames = recording.get("frames") if isinstance(recording.get("frames"), list) else []
    # Recorder frames are already contract-bounded (currently at most 122).
    # Consume the complete trajectory: output-size bounds must never change the
    # physical observation window used by diagnostics.
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        time_s = _finite_number(frame.get("time_s"))
        poses = frame.get("poses")
        if time_s is None or not isinstance(poses, list):
            continue
        mapped = {}
        for pose in poses:
            if isinstance(pose, dict) and isinstance(pose.get("id"), str):
                position = _vec3(pose.get("position_m"))
                if position is not None:
                    mapped[pose["id"]] = position
        result.append((time_s, mapped))
    return result


def _object_body_ids(recording: dict[str, Any]) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    bodies = recording.get("bodies") if isinstance(recording.get("bodies"), list) else []
    for body in bodies:
        if not isinstance(body, dict) or type(body.get("object_id")) is not int or not isinstance(body.get("id"), str):
            continue
        result.setdefault(body["object_id"], []).append(body["id"])
    return result


def _rigid_lane_checks(plan: dict[str, Any], package: dict[str, Any],
                       recording: dict[str, Any]) -> list[dict[str, Any]]:
    spec = plan.get("drop")
    if plan.get("experiment") != "drop_test" or not isinstance(spec, dict):
        return []
    if spec.get("representation") != "rigid" or spec.get("projectile") != "iron_ball":
        return [_result("lane_clearance", "unknown",
                        "Unsupported for geometric lane inference; rigid spherical projectiles are required.",
                        "sampled poses; no solver contact proof")]
    objects = {obj.get("id"): obj for obj in package.get("objects", []) if isinstance(obj, dict)}
    body_ids = _object_body_ids(recording)
    frames = _poses_by_frame(recording)
    checks = []
    for lane, (target_id, projectile_id) in enumerate(((1, 2), (3, 4), (5, 6))):
        target, projectile = objects.get(target_id), objects.get(projectile_id)
        if not isinstance(target, dict) or not isinstance(projectile, dict):
            checks.append(_result(f"lane_{lane}_clearance", "unknown", "Authored lane objects are missing.",
                                  "sampled poses; no solver contact proof"))
            continue
        td, pd = _vec3(target.get("dimensions_m")), _vec3(projectile.get("dimensions_m"))
        tids, pids = body_ids.get(target_id, []), body_ids.get(projectile_id, [])
        if td is None or pd is None or not tids or not pids:
            checks.append(_result(f"lane_{lane}_clearance", "unknown", "Body descriptors or dimensions are missing.",
                                  "sampled poses; no solver contact proof"))
            continue
        radius = pd[0] / 2
        gaps, projectile_y = [], []
        for time_s, poses in frames:
            tp, pp = poses.get(tids[0]), poses.get(pids[0])
            if tp is None or pp is None:
                continue
            # The target may tilt after impact. This is deliberately an AABB-style
            # approximation using its sampled center and authored thickness.
            horizontal = abs(pp[0] - tp[0]) <= td[0] / 2 + radius and abs(pp[2] - tp[2]) <= td[1] / 2 + radius
            projectile_y.append((time_s, pp[1]))
            if horizontal:
                gaps.append((pp[1] - radius) - (tp[1] + td[2] / 2))
        reversal = any(projectile_y[i][1] - projectile_y[i-1][1] < 0 and
                       projectile_y[i+1][1] - projectile_y[i][1] > 0
                       for i in range(1, len(projectile_y) - 1))
        minimum = min(gaps) if gaps else None
        status = "pass" if minimum is not None and minimum <= max(.002, radius * .05) else ("fail" if minimum is not None else "unknown")
        observation = ("Sampled axis-aligned gap reached the proximity tolerance."
                       if status == "pass" else "Sampled axis-aligned gap did not reach the proximity tolerance."
                       if status == "fail" else "No horizontally overlapping sampled pose was available.")
        checks.append(_result(f"lane_{lane}_clearance", status, observation,
                              "axis-aligned sampled-position approximation; target tilt is not modeled; no solver contact proof",
                              {"target_object_id": target_id, "projectile_object_id": projectile_id,
                               "minimum_vertical_gap_m": minimum, "sampled_velocity_reversal": reversal}))
    return checks


def build_diagnostics(plan: dict[str, Any], package: dict[str, Any],
                      recording: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded JSON-compatible diagnostics dictionary."""
    if recording.get("schema") == _DYNAMIC_MATERIAL_SCHEMA:
        return _dynamic_material_diagnostics(package, recording)
    requested = recording.get("requested_steps") if type(recording.get("requested_steps")) is int else None
    completed = recording.get("completed_steps") if type(recording.get("completed_steps")) is int else None
    frames = recording.get("frames") if isinstance(recording.get("frames"), list) else []
    final_time = _finite_number(frames[-1].get("time_s")) if frames and isinstance(frames[-1], dict) else None
    if final_time is None and isinstance(recording.get("report"), dict):
        final_time = _finite_number(recording["report"].get("elapsed_s"))
    duration = _finite_number(plan.get("duration_s"))
    expectations: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    spec = plan.get("drop")
    if plan.get("experiment") == "drop_test" and isinstance(spec, dict):
        heights = spec.get("heights_m") if isinstance(spec.get("heights_m"), list) else []
        height = _drop_height(package)
        height_source = "compiled_package_initial_clearance" if height is not None else None
        if height is None and len(heights) == 1:
            height = _finite_number(heights[0])
            height_source = "single_plan_height"
        flight = math.sqrt(2 * height / 9.81) if height is not None and height >= 0 else None
        expectations.append({"kind": "drop_flight", "height_m": height,
                             "estimated_flight_time_s": flight, "requested_duration_s": duration,
                             "height_source": height_source,
                             "model": "sqrt(2*height/9.81), ignoring drag and target motion"})
        if duration is None or flight is None:
            checks.append(_result("observation_window", "unknown", "Duration or drop height is unavailable.", "free-fall timing estimate"))
        elif duration < flight:
            checks.append(_result("observation_window", "fail", "too_short",
                                  "free-fall timing estimate", {"duration_s": duration, "estimated_flight_time_s": flight}))
        else:
            checks.append(_result("observation_window", "pass", "duration_reaches_estimated_fall",
                                  "free-fall timing estimate", {"duration_s": duration, "estimated_flight_time_s": flight}))
    if requested is None or completed is None:
        checks.append(_result("execution_completion", "unknown", "Requested or completed step count is unavailable.", "native recorder counters"))
    elif completed < requested:
        checks.append(_result("execution_completion", "fail", "execution_stopped",
                              "native recorder counters", {"requested_steps": requested, "completed_steps": completed}))
    else:
        checks.append(_result("execution_completion", "pass", "requested_steps_completed",
                              "native recorder counters", {"requested_steps": requested, "completed_steps": completed}))
    checks.extend(_rigid_lane_checks(plan, package, recording))
    report = recording.get("report") if isinstance(recording.get("report"), dict) else {}
    temporal = report.get("temporal_resolution")
    state_valid = report.get("state_valid") if type(report.get("state_valid")) is bool else None
    response_valid = recording.get("physical_response_validated")
    if type(response_valid) is not bool:
        response_valid = report.get("physical_response_validated")
    if type(response_valid) is not bool:
        response_valid = None
    material_valid = None
    if isinstance(temporal, dict) and type(temporal.get("material_validation")) is bool:
        material_valid = temporal["material_validation"]
    elif type(report.get("material_validation")) is bool:
        material_valid = report["material_validation"]
    return {
        "schema": SCHEMA,
        "native_facts": {"status": _bounded_json(recording.get("status")),
                         "error": _bounded_json(recording.get("error", "")),
                         "requested_steps": requested, "completed_steps": completed,
                         "final_time_s": final_time, "report": _bounded_json(report)},
        "validity": {"temporal_resolution": _bounded_json(temporal) if isinstance(temporal, dict) else None,
                     "state_valid": state_valid, "material_validation": material_valid,
                     "physical_response_validated": response_valid},
        "package": {"sha256": _package_sha256(package), "scene": _scene_summary(package)},
        "expectations": expectations[:_MAX_ITEMS], "checks": checks[:_MAX_ITEMS],
        "limitations": ["Sampled positions cannot establish solver contact or contact forces.",
                        "No validated material behavior is inferred from motion."]
    }
