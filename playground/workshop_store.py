"""Durable Workshop design records.

The Workshop explores many transient candidates, but an explicitly saved design
must outlive the browser and the server process.  This store keeps only the
semantic recipe needed to rebuild a design -- assembly kind, parameters,
purpose and lineage -- plus immutable evidence that identifies what was saved.

Geometry is deliberately regenerated through ``mcp.workshop.assemble`` when a
record is loaded.  That keeps ``mcp/workshop.py`` the one design model instead
of serializing a second private copy of its parts.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import threading
import time
from typing import Any

from mcp.workshop import WORKSHOP_SCHEMA, WorkshopDesign, assemble, materialize

SAVED_SCHEMA = "banjo.workshop.saved-design.v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_MAX_RECORD_BYTES = 512 * 1024
_lock = threading.Lock()


def safe_design_id(value: Any) -> str:
    design_id = str(value or "")
    if not _SAFE_ID.fullmatch(design_id):
        raise ValueError("design_id must be 1-81 letters, digits, dot, dash or underscore")
    return design_id


def _folder(root: Path) -> Path:
    folder = Path(root) / "designs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _path(root: Path, design_id: str) -> Path:
    return _folder(root) / f"{safe_design_id(design_id)}.json"


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"there is no saved Workshop design {path.stem}")
    if path.stat().st_size > _MAX_RECORD_BYTES:
        raise ValueError(f"saved Workshop design {path.stem} exceeds the record limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != SAVED_SCHEMA:
        raise ValueError(f"saved Workshop design {path.stem} has an unsupported format")
    return value


def save(root: Path, design: WorkshopDesign, *,
         label: str = "", parent_design_id: str | None = None,
         world_revision: str | None = None) -> dict[str, Any]:
    """Save or revise one semantic design recipe atomically."""
    design.validate()
    design_id = safe_design_id(design.design_id)
    if not design.kind:
        raise ValueError("only a named Workshop assembly can be saved")
    path = _path(root, design_id)
    with _lock:
        before = _read(path) if path.exists() else None
        revision = int((before or {}).get("revision") or 0) + 1
        plan = materialize(design)
        record = {
            "schema": SAVED_SCHEMA,
            "workshop_schema": WORKSHOP_SCHEMA,
            "design_id": design_id,
            "revision": revision,
            "kind": design.kind,
            "label": str(label or design_id)[:160],
            "purpose": design.purpose,
            "parameters": dict(design.parameters),
            "lineage": {
                **dict(design.lineage),
                **({"parent_design_id": safe_design_id(parent_design_id)}
                   if parent_design_id else {}),
            },
            "world_revision": str(world_revision)[:200] if world_revision else None,
            "fingerprint": plan["fingerprint"],
            "measured": design.measure(),
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        encoded = json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if len(encoded.encode("utf-8")) > _MAX_RECORD_BYTES:
            raise ValueError("saved Workshop design exceeds the record limit")
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(encoded, encoding="utf-8")
        tmp.replace(path)
    return record


def load(root: Path, design_id: str) -> tuple[dict[str, Any], WorkshopDesign]:
    """Read a saved recipe and rebuild it through the current Workshop model."""
    record = _read(_path(root, design_id))
    design = assemble(
        str(record["kind"]),
        design_id=str(record["design_id"]),
        purpose=str(record.get("purpose") or ""),
        parameters=dict(record.get("parameters") or {}),
    )
    design.lineage = dict(record.get("lineage") or {})
    return record, design


def list_saved(root: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    """Newest saved recipes, as summaries suitable for the Library pane."""
    rows: list[dict[str, Any]] = []
    for path in _folder(root).glob("*.json"):
        try:
            record = _read(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        rows.append({
            key: record.get(key)
            for key in ("design_id", "revision", "kind", "label", "purpose",
                        "parameters", "lineage", "world_revision", "fingerprint",
                        "measured", "saved_at")
        })
    rows.sort(key=lambda r: (str(r.get("saved_at") or ""), str(r.get("design_id") or "")),
              reverse=True)
    return rows[:max(0, min(1000, int(limit)))]
