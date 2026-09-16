#!/usr/bin/env python3
"""Print a few cheap Workshop Mode candidates and one materialization plan.

Run from the repository root:

    python scripts/workshop-demo.py

This demo never opens Banjo's physics engine and never mutates a live world.
It exists to make the first workshop slice easy to inspect locally before the
browser view and scratch-world test runner land.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.workshop import (
    ComponentLibrary,
    WorkshopSession,
    feedback,
    materialize,
    rectangular_four_leg_frame,
    variants,
)


def main() -> None:
    session = WorkshopSession(
        session_id="demo-workshop",
        world_revision="demo-frozen-world-r1",
        target="new table",
    )
    library = ComponentLibrary()
    base = rectangular_four_leg_frame(
        design_id="work-table",
        purpose="a stable workshop table",
        top_size_m=(1.20, 0.05, 0.70),
        top_height_m=0.78,
        material="oak",
        library=library,
    )
    candidates = variants(base, {
        "leg_style": ["straight", "splayed", "tapered"],
        "top_profile": ["square", "rounded"],
    })

    chosen = candidates[1]
    print("SESSION")
    print(json.dumps({
        "session_id": session.session_id,
        "world_revision": session.world_revision,
        "target": session.target,
        "outside_paused": session.outside_paused,
        "component_families": library.families(),
    }, indent=2))

    print("\nBASE WIREFRAME")
    print(json.dumps(base.wireframe(), indent=2))

    print("\nVARIANTS")
    for candidate in candidates:
        print(json.dumps({
            "design_id": candidate.design_id,
            "changes": candidate.lineage["changes"],
        }, sort_keys=True))

    print("\nUSER FEEDBACK")
    print(json.dumps(feedback(
        chosen,
        rating=5,
        selected=True,
        note="Use this direction; next make the legs visually lighter.",
    ), indent=2))

    print("\nMATERIALIZATION PLAN")
    print(json.dumps(materialize(chosen, cell_size_m=0.04), indent=2))


if __name__ == "__main__":
    main()
