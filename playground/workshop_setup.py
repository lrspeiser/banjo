"""Inspect the actual isolated experiment at t=0, without advancing physics.

Scene factories are shared with the run path. No preview touches the live room
or claims a strength verdict. The temporary native session is always closed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import tempfile

import live_session
import workshop_bench_core as core
import workshop_motion as motion
import workshop_recording
import workshop_sparse_trial as sparse
from mcp import workshop_matter_metrics, workshop_rigid


def _little_world(app: Any, candidate: Any, config: dict[str, Any]) -> dict[str, Any]:
    """The little world at t=0: the thing made, the test set up on it, nothing stepped.

    This costs what making the thing costs, because it IS making the thing. It
    is worth that: the setup a person looks at before pressing run is the room
    the run happens in, down to where the weight hangs and how far up the block
    is aimed, rather than a drawing of a different scene.
    """
    import workshop_bench
    import workshop_test_room as little
    if candidate is None:
        raise ValueError("Trying a thing in a little world needs the design it is made from")
    how = workshop_bench._how(config)
    with little.Bench(app, sun=how.get("sun"), day=how.get("day"), items=how.get("items") or ()) as room:
        made = room.make(candidate)
        did = room.set_up(load_kg=how["load_kg"], on=how["on"], drop_m=how["drop_m"],
                          slide_m_s=how["slide_m_s"], strike=how["strike"])
        poses = room.live.session.send(op="poses")
        frame = workshop_recording.frame(poses)
        if not frame or not frame["bodies"]:
            raise ValueError("The little world came up with nothing standing in it")
        frame["t_s"] = 0.0
        frame["bodies"] = [b for b in frame["bodies"] if little._worth_watching(b)]
        said = [f"{made.get('mass_kg', 0):.1f} kg on {little.GROUND_M * 1000:.0f} mm of ground"]
        if did.get("drop_m"):
            said.append(f"held {did['drop_m']:.2f} m up")
        if did.get("load_kg"):
            said.append(f"{did['load_kg']:g} kg hanging over its {did.get('on') or 'top'}")
        if did.get("slide_m_s"):
            said.append(f"starting at {did['slide_m_s']:g} m/s")
        if did.get("strike"):
            said.append(f"a {did['strike']['kg']:g} kg block aimed at it")
        geometry = {k: v for k, v in little._geometry(poses, float(room.room.spec["cell_m"])).items()
                    if not k.startswith(little.MARKER + "#")}
        return {"schema": "banjo.workshop-setup.v1", "phase": "setup", "test": "try_in_a_room",
                "frames": [frame], "geometry": geometry,
                "requested": dict(config), "geometry_basis": "native-test-setup",
                "native_verified": True, "physics_advanced": False, "ground_m": little.GROUND_M,
                "summary": ", ".join(said) + ". Nothing has moved yet."}


def preview(app: Any, design, request: Any, *, candidate: Any = None) -> dict[str, Any]:
    if not isinstance(request, dict) or set(request) - {"test", "config"}:
        raise ValueError("bench_preview requires test and config only")
    test, config = str(request.get("test") or ""), request.get("config", {})
    if not isinstance(config, dict):
        raise ValueError("bench_preview.config must be an object")
    if test == "try_in_a_room":
        return _little_world(app, candidate, config)
    if test == "rigid_motion":
        artifact = workshop_rigid.compile_rigid(design)
        package = workshop_rigid.package(artifact, drop_height_m=motion.number(config,"drop_height_m",.2,0,2),
                                         horizontal_speed_m_s=motion.number(config,"horizontal_speed_m_s",0,-2,2))
        com = package["objects"][0]["position_m"]
        bodies = [{"name": p["component"], "object_id": 1, "shape": "box",
                   "position_m": [com[a] + p["center_local_m"][a] for a in range(3)],
                   "orientation_wxyz": [1, 0, 0, 0], "dimensions_m": p["dimensions_m"],
                   "material": artifact["material"], "revision": 0} for p in artifact["components"]]
        # No native run is needed to display the compiled rigid setup. Label it
        # accurately; the Run path verifies it against native shapes and mass.
        return {"schema": "banjo.workshop-setup.v1", "test": test, "phase": "setup",
                "basis": "compiled-precise-rigid-shapes", "native_verified": False,
                "physics_advanced": False, "frames": [{"t_s": 0, "bodies": bodies}],
                "geometry_basis": "compiled-precise-rigid-shapes", "requested": dict(config),
                "summary": f"{len(bodies)} exact-size rigid shapes. No internal bending or fracture model."}

    workshop_rigid.require_lattice(design, "This test setup")
    matter, root, shift = None, None, (0, 0, 0)
    if test in motion.TESTS:
        setup = motion.scene(design, test, config)
        spec, matter, root, shift = setup["spec"], setup["matter"], setup["root"], setup["shift"]
        if test == "drop_product":
            summary = f"Release the product {setup['applied_height_m']:g} m above the floor."
        elif test == "impact_product":
            striker = setup["striker"]
            summary = f"{striker['actual_kg']:.2f} kg striker at {striker['speed_m_s']:g} m/s ({striker['energy_j']:.1f} J)."
        else:
            summary = f"Start at {setup['speed_m_s']:g} m/s along +X; friction and contact determine the motion."
    elif test == "declared_static_load":
        trial = next((t for t in design.tests if t.get("kind") == "static_load"), None)
        if trial is None:
            raise ValueError("This design has no supported load target")
        load = motion.number(config, "load_kg", float(trial.get("load_kg", 0)), .1, 1000)
        h = motion.number(config, "cell_size_m", .04, .005, .1)
        setup = sparse.prototype_scene(design, load_kg=load, on=str(trial.get("on") or "top"), cell_size_m=h)
        spec, matter, root, shift = setup["spec"], setup["matter"], setup["root_body"], setup["placement_grid"]
        summary = f"{setup['actual_load_kg']:.2f} kg weight on {setup['load_on']}. The weight is part of this scene."
    elif test == "cart_roll":
        workshop_matter_metrics.require_wire_geometry(design, test)
        speed = core._number(config, "speed_m_s", .8, .1, 3)
        spec, _, _ = core._cart_spec(design, speed)
        summary = f"Cart starts at {speed:g} m/s. Real bearings; reduced wheel and chassis collision shapes."
    elif test == "kettle_heat":
        workshop_matter_metrics.require_wire_geometry(design, test)
        setup = core.kettle_setup(design, config)
        spec = setup["spec"]
        summary = f"{setup['water_kg']:g} kg contained water; {setup['power']:g} W heater. Temperature model, not fluid sloshing."
    else:
        raise ValueError("No visible simulation setup is available for this test")
    engine = Path(app.engine_path)
    if not engine.is_file():
        raise ValueError("Build banjo_live_world_run before using the test workspace")
    folder = Path(app.runs_path) / "workshop-setup"
    folder.mkdir(parents=True, exist_ok=True)
    scratch = tempfile.TemporaryDirectory(prefix="preview-", dir=folder)
    session = None
    try:
        session = live_session.Session(engine, spec, Path(scratch.name))
        if spec.get("joints"):
            hung = live_session.Live._hang(session, spec["joints"])
            if hung.get("refused"):
                raise ValueError("The preview could not attach the test joints")
        state = session.send(op="poses")
        if test == "kettle_heat":
            state["thermo"] = session.send(op="thermo").get("thermo") or {}
        snapshot = session.send(op="snapshot").get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("The native engine did not provide a test setup snapshot")
        if matter:
            sparse.verify_engine_matter(snapshot, matter, root, placement_grid=shift)
        geometry = {}
        sparse.piece_geometry(snapshot, float(spec["cell_m"]), geometry)
        initial = workshop_recording.frame(state)
        if not initial or not initial["bodies"] or initial["t_s"] != 0:
            raise ValueError("The native setup was not an unadvanced populated scene")
        return {"schema": "banjo.workshop-setup.v1", "phase": "setup", "test": test,
                "frames": [initial], "geometry": geometry, "requested": dict(config),
                "geometry_basis": "native-test-setup", "native_verified": True,
                "physics_advanced": False, "summary": summary,
                "matter_physics_hash": matter["physics_hash"] if matter else None}
    finally:
        try:
            if session is not None:
                session.close()
        finally:
            scratch.cleanup()
