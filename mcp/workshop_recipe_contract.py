"""Derived recipe identity and review obligations, never manufacturing authority.

The editable Workshop source remains authoritative. This report neither changes
legacy saved sources nor accepts an LLM's assertion as a completed native trial.
Its hashes bind observations to both the resolved source and manufacturing
settings. Existing bench fingerprints remain distinct, without guessed migration.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from math import isfinite
from typing import Any

from mcp import engine_materials, workshop_graph, workshop_rigid, workshop_placement, workshop_tools

SCHEMA = "banjo.workshop-recipe-contract.v1"
EVIDENCE_SCHEMA = "banjo.workshop-recipe-evidence.v1"
PROCESS_FIELDS = {"power_w", "work_j_kg", "efficiency", "heat_capacity_j_k",
                  "cooling_w_k", "max_temperature_k"}


def _json(value: Any) -> Any:
    """Copy finite JSON; never hash repr(), NaN, or an arbitrary Python object."""
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


def _cell(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not isfinite(value) or not .002 <= value <= .5:
        raise ValueError(label + " must be finite between 0.002 and 0.5 metres")
    return float(value)


def _manufacturing(design: Any, overrides: dict, settings: Any) -> dict:
    settings = {} if settings is None else settings
    allowed = {"cell_size_m", "workshop_cell_size_m", "process_settings"}
    if not isinstance(settings, dict) or set(settings) - allowed:
        raise ValueError("manufacturing accepts cell_size_m, workshop_cell_size_m and process_settings")
    process = settings.get("process_settings")
    if process is not None:
        if not isinstance(process, dict) or set(process) - PROCESS_FIELDS:
            raise ValueError("process_settings must contain declared fabrication coefficients only")
        for key, value in process.items():
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError(key + " must be a finite nonnegative number")
            if key != "cooling_w_k" and value == 0:
                raise ValueError(key + " must be positive")
            if key == "efficiency" and value > 1:
                raise ValueError("efficiency cannot exceed 1")
    local = overrides.get("@local_cells")
    models = sorted(workshop_rigid.requested_models(design, overrides))
    return {"representation": "local-material-cells" if local is not None else
                               "rigid" if models == ["rigid"] else
                               "mixed-mechanics" if len(models) > 1 else "lattice",
            "component_models": models,
            "cell_size_m": _cell(settings.get("cell_size_m"), "cell_size_m"),
            "workshop_cell_size_m": _cell(settings.get("workshop_cell_size_m"), "workshop_cell_size_m"),
            "local_cells_request": _json(local),
            "process_model": "declared-lumped-fabrication",
            "process_settings": _json(process),
            "settings_status": "declared" if process else "requires_paid_quote",
            "native_admission": "required",
            "resource_reservation": "not_performed"}


def _has_number(value: Any) -> bool:
    if type(value) in (int, float):
        return isfinite(value)
    if isinstance(value, dict):
        return any(_has_number(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_number(v) for v in value)
    return False


def _observations(records: Any, source_hash: str, contract_hash: str) -> tuple[list, list]:
    if records is None:
        return [], []
    if not isinstance(records, list) or len(records) > 100:
        raise ValueError("evidence must be a list of at most 100 observations")
    current, rejected = [], []
    allowed = {"schema", "source_hash", "contract_hash", "test", "origin", "completed",
               "result", "requested", "measured", "environment", "limitations"}
    for index, record in enumerate(records):
        reason = None
        try:
            row = _json(record)
            if not isinstance(row, dict) or set(row) - allowed or row.get("schema") != EVIDENCE_SCHEMA:
                reason = "not a versioned recipe observation; legacy bench results retain their own fingerprint"
            elif row.get("source_hash") != source_hash or row.get("contract_hash") != contract_hash:
                reason = "source or manufacturing revision differs"
            elif (not isinstance(row.get("test"), str) or not row["test"].strip() or
                  row.get("origin") not in {"native", "analytical", "manual"} or
                  row.get("completed") is not True or row.get("result") not in {"passed", "failed", "measured"} or
                  not isinstance(row.get("measured"), dict) or not _has_number(row["measured"]) or
                  not isinstance(row.get("environment"), dict) or not row["environment"] or
                  not isinstance(row.get("requested"), dict) or not isinstance(row.get("limitations"), list)):
                reason = "requires a completed bounded observation, numerical measurements and experiment conditions"
        except (TypeError, ValueError):
            row, reason = {}, "observation must be finite JSON"
        if reason:
            rejected.append({"index": index, "reason": reason})
        else:
            # Callers supply observations, not authority to certify a product.
            current.append({**row, "provenance_verified": False,
                            "qualification_granted": False})
    return current, rejected


def derive(design: Any, overrides: Any = None, *, manufacturing: Any = None,
           evidence: Any = None) -> dict[str, Any]:
    """Report the resolved design, shared by catalog and authored candidates.

    ``design`` must be the caller's already-resolved candidate. ``overrides``
    retains its source declarations, including any explicit representation.
    Nothing here compiles, manufactures, spends resources, or awards knowledge.
    """
    patches = _json(overrides if overrides is not None else
                    (design.lineage or {}).get("component_overrides") or {})
    if not isinstance(patches, dict):
        raise ValueError("recipe overrides must be an object")
    parts = []
    for part in design.parts:
        material = engine_materials.canonical(part.material) if engine_materials.known(part.material) else None
        preset = engine_materials.MATERIALS.get(material) if material else None
        parts.append({"name": part.name, "role": part.role, "family": part.family, "shape": part.shape,
                      "size_m": list(part.size_m), "center_m": list(part.center_m),
                      "rotation_deg": list(part.rotation_deg), "material": part.material,
                      "catalog_material": material, "material_preset": deepcopy(preset),
                      "material_status": "catalog-preset" if preset else "unsupported-legacy-name"})
    # Includes declarations and inferred contacts, each retaining derived/kind.
    # A contact or a proposed failure mode is never promoted to certified fixing.
    graph = workshop_graph.product(design).described()
    connections = graph.get("relationships") or []
    source = _json({"design_id": design.design_id, "kind": design.kind, "purpose": design.purpose,
                    "parameters": dict(design.parameters), "component_overrides": patches,
                    "components": parts, "connections": connections,
                    "declared_tests": design.tests})
    source_hash = _hash(source)
    settings = _manufacturing(design, patches, manufacturing)
    contract_hash = _hash({"schema": SCHEMA, "source": source, "manufacturing": settings})
    observations, rejected = _observations(evidence, source_hash, contract_hash)
    requirements = [
        {"id": "native-admission", "requirement": "Admit the exact geometry, materials and connections in the destination representation."},
        {"id": "finite-resources", "requirement": "Review and reserve actual source stock, assembly supplies and finite manufacturing work/energy."},
        {"id": "functional-trial", "requirement": "Measure the intended use in declared installation conditions; Lab results do not qualify another grid."},
    ]
    requirements += [{"id": f"declared-test-{i + 1}", "requirement": _json(test)}
                     for i, test in enumerate(design.tests)]
    installation = workshop_placement.for_design(design)
    requirements += [{"id": "declared-installation", "requirement": _json(installation)}]
    for item in requirements:
        item["status"] = "requires_review"
    return {"schema": SCHEMA,
            "source": {"design_id": design.design_id, "kind": design.kind, "purpose": design.purpose,
                       "hash": source_hash, "revision": source_hash, "identity_basis": "resolved-source-sha256"},
            "contract_hash": contract_hash, "geometry_materials": parts, "connections": _json(connections),
            "geometry_basis": "editable source primitives; occupied native matter and paid bill require compilation",
            "editable_source": {k: deepcopy(source[k]) for k in
                                ("design_id", "kind", "purpose", "parameters", "component_overrides")},
            "intended_use": _json({k: v for k, v in design.parameters.items()
                                   if k in {"primary_use", "primary_use_component", "ground_tool",
                                            "interaction_points", "interaction_point_components"}}),
            "manufacturing": settings,
            "tool_authoring": _json(workshop_tools.authoring_contract(design)),
            "qualification": {"status": "unqualified", "requirements": requirements,
                              "declared_tests": _json(design.tests), "measured_evidence": observations,
                              "rejected_evidence": rejected, "skill_enforcement": "not_implemented_by_this_report"},
            "limitations": ["Derived authoring report; geometry fit alone is not native admission or a functional qualification.",
                            "Process coefficients and connection declarations are not calibrated manufacturing or joint-strength evidence.",
                            "This report adds no bending, internal fracture, wear, fatigue, repair or skill law.",
                            "Caller-supplied observations are not authenticated native receipts; legacy bench fingerprints are not recipe identities."]}
