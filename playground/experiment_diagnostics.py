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
