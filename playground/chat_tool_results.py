"""Bounded, lossless object-list deltas for one room-chat turn.

The native/MCP response and server audit log stay complete. Only the JSON sent
back to the model may omit unchanged named objects, and only after that same
turn has sent a full baseline. Explicit reads still return the whole list.
No coordinates, warnings, joints, or physical results are fabricated here.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

MAX_TRACKED_OBJECTS = 4096

GUIDANCE = (
    "TOOL OBJECT LISTS. A tool's objects array is complete unless object_listing.mode is delta. "
    "In a delta, objects contains only added or changed objects since the previous objects "
    "result in this turn; remove object_listing.removed_names and retain the unchanged ones. "
    "The count of the whole current list is object_listing.total_count. This is transport "
    "compression, not a change to physics. Other fields, including corrections and lost joints, "
    "remain the tool's actual answer. Call describe_world for a complete fresh list."
)


class ObjectResultTransport:
    """Keep at most one named-object snapshot, isolated to a single ask()."""

    def __init__(self, mutations: Iterable[str]) -> None:
        self._mutations = frozenset(mutations)
        self._previous: dict[str, str] | None = None
        self._calls = 0
        self._delta_calls = 0
        self._original_bytes = 0
        self._sent_bytes = 0
        self._omitted_objects = 0

    @staticmethod
    def _snapshot(value: Any) -> dict[str, dict[str, Any]] | None:
        if not isinstance(value, list) or len(value) > MAX_TRACKED_OBJECTS:
            return None
        result: dict[str, dict[str, Any]] = {}
        for row in value:
            if not isinstance(row, dict):
                return None
            name = row.get("name")
            if not isinstance(name, str) or not name or name in result:
                # Fragments may have ambiguous names: never guess an identity.
                return None
            result[name] = row
        return result

    def encode(self, tool: str, answer: dict[str, Any]) -> str:
        """Serialize a response; only use a delta when it actually saves bytes."""
        original = json.dumps(answer, allow_nan=False)
        sent = original
        self._calls += 1
        self._original_bytes += len(original.encode("utf-8"))
        if "error" in answer or "object_listing" in answer:
            self._previous = None
        elif "objects" in answer:
            current = self._snapshot(answer["objects"])
            frozen = (None if current is None else {
                name: json.dumps(row, sort_keys=True, allow_nan=False) for name, row in current.items()})
            if current is not None and self._previous is not None and tool in self._mutations:
                changed = [row for name, row in current.items()
                           if name not in self._previous or frozen[name] != self._previous[name]]
                removed = sorted(set(self._previous) - set(current))
                unchanged = len(current) - len(changed)
                compact = {**answer, "objects": changed, "object_listing": {
                    "mode": "delta", "basis": "previous-objects-result-in-this-turn",
                    "removed_names": removed, "total_count": len(current),
                    "unchanged_count": unchanged,
                }}
                candidate = json.dumps(compact, allow_nan=False)
                if len(candidate.encode("utf-8")) < len(original.encode("utf-8")):
                    sent = candidate
                    self._delta_calls += 1
                    self._omitted_objects += unchanged
            # A complete read refreshes the baseline but is never compressed.
            # Freeze the source rows: a handler may mutate them in-place later.
            self._previous = frozen
        elif tool in self._mutations:
            # A mutation without a full objects array cannot establish the next
            # baseline. Be conservative even if it probably touched only metadata.
            self._previous = None
        self._sent_bytes += len(sent.encode("utf-8"))
        return sent

    def described(self) -> dict[str, Any]:
        return {
            "schema": "banjo.chat-tool-transport.v1", "calls": self._calls,
            "delta_calls": self._delta_calls, "original_json_bytes": self._original_bytes,
            "sent_json_bytes": self._sent_bytes,
            "saved_json_bytes": self._original_bytes - self._sent_bytes,
            "unchanged_objects_omitted": self._omitted_objects,
            "basis": "UTF-8 function-call outputs; not model tokens or billed cost",
        }
