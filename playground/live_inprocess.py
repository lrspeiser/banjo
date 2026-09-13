"""The same live world, held in this process instead of a subprocess.

`live_session.Session` spawns `banjo_live_world_run` and talks JSON over a pipe.
That works, and it is what the playground has always done, but it is also the
only way anything outside the C++ tree could reach the engine -- which is a
strange thing to be true of a physics engine. The C library exists to fix that,
and this is the playground taking its own medicine: the same scenes, the same
physics, the same replies, with no process boundary and no JSON in the middle.

It answers to the same interface `Session` does -- `state`, `send(**command)`,
`close()` -- so the server does not know or care which one it is holding. That
is deliberate: two implementations of one interface can be run against the same
tests and compared reply for reply, which is the only honest way to claim the
in-process path does the same thing.

Turned on with `--live-inprocess` or `BANJO_LIVE_INPROCESS=1`. Off by default,
because the subprocess is the one that has been watched working: a world that
crashes takes the server down with it when it is in the same process, and the
server is what the owner is looking at.
"""
from __future__ import annotations

import math
import sys
import uuid
from pathlib import Path
from typing import Any

import fracture_lab

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bindings" / "python"))

# Imported lazily by `available()` so that a tree without the library built
# still starts: this is an option, not a requirement.
banjo: Any = None


def available() -> tuple[bool, str]:
    """Whether the C library can be loaded, and what went wrong if not."""
    global banjo
    try:
        if banjo is None:
            import banjo as module   # noqa: PLC0415
            banjo = module
        banjo.library()
        return True, ""
    except Exception as error:      # a missing library is a reason, not a crash
        return False, str(error)


class InProcessSession:
    """One open world, living here.

    Every method mirrors an op of the line protocol, and every reply is shaped
    exactly like the subprocess's, because the browser and the server are
    written against that shape and neither should have to know the difference.
    """

    def __init__(self, spec: dict[str, Any], cell_m: float | None = None) -> None:
        ok, why = available()
        if not ok:
            raise ValueError(f"the in-process engine is not available: {why}")
        bodies = fracture_lab.as_objects(spec)
        if not bodies:
            raise ValueError("This scene has nothing in it to simulate.")
        spec = dict(spec, bodies=bodies)
        self.id = uuid.uuid4().hex
        self.spec = spec
        self.opened_at = 0.0
        scene = fracture_lab.scene_document(spec)
        self._cell_m = float(cell_m if cell_m is not None else spec["cell_m"])
        self._stepped_back = False
        try:
            self._world = banjo.World(scene, cell_size_m=self._cell_m)
        except Exception as error:
            raise ValueError(str(error)) from error
        self.state = self._describe(geometry=True)

    # -- the wire, without a wire -----------------------------------------
    @staticmethod
    def _number(value: float) -> float | None:
        """A float JSON can carry, or null.

        An impact can report an infinite threshold, and it means something: the
        speed at which this body could break is unbounded, so nothing can break
        it. A single cell with no bonds left to fail is the usual way to get
        one. The subprocess lane has always sent those as null -- nlohmann
        writes a non-finite double that way without comment -- so this sends
        null too, and the browser cannot tell the lanes apart. Python's json
        refuses inf outright, which is how this surfaced at all: the same value
        had been going quietly over the pipe the whole time.
        """
        return value if math.isfinite(value) else None

    def _describe(self, geometry: bool = False, extra: dict[str, Any] | None = None
                  ) -> dict[str, Any]:
        world = self._world
        bodies = []
        for body in world.bodies():
            bodies.append({
                "name": body.name,
                "material": body.material,
                "shape": body.shape,
                "dimensions_m": list(body.dimensions_m),
                "position_m": [self._number(v) for v in body.position_m],
                "orientation_wxyz": [self._number(v) for v in body.orientation_wxyz],
                "velocity_m_s": [self._number(v) for v in body.velocity_m_s],
                "mass_kg": self._number(body.mass_kg),
                "anchored": body.anchored,
                "held": body.held,
                "color_rgba": f"{body.rgba:08x}",
            })
        state: dict[str, Any] = {
            "ok": True,
            "t": self._number(world.time_s),
            # A step that was taken back did not happen: the world is one step
            # short of an impact and the host has a decision to make before time
            # moves again.
            "stepped_back": self._stepped_back,
            "cell_size_m": self._cell_m,
            "geometry": geometry,
            "held": world.held,
            "bodies": bodies,
            "impacts": [{"struck": i.struck, "by": i.by,
                         "closing_speed_m_s": self._number(i.closing_speed_m_s),
                         "threshold_speed_m_s": self._number(i.threshold_speed_m_s),
                         "dent_speed_m_s": self._number(i.dent_speed_m_s),
                         "would_dent": i.would_dent,
                         "energy_j": self._number(i.energy_j),
                         "would_break": i.would_break}
                        for i in world.impacts()],
            "breakable": world.breakable(),
        }
        heat = self._heat()
        if heat is not None:
            state["heat"] = heat
        # The hand, while it holds something and once a stroke has opened it --
        # the same block the subprocess lane puts on its replies.
        hand = world.hand()
        if hand.holding or hand.let_go_at_s >= 0.0 or hand.stroke_ended:
            state["hand"] = self._hand(hand)
        if extra:
            state.update(extra)
        return state

    def _hand(self, hand: "banjo.Hand") -> dict[str, Any]:
        out: dict[str, Any] = {
            "holding": hand.holding, "mode": hand.mode,
            "target_m": [self._number(v) for v in hand.target_m],
            "grip_m": [self._number(v) for v in hand.grip_m],
            "grip_velocity_m_s": [self._number(v) for v in hand.grip_velocity_m_s],
            "force_n": [self._number(v) for v in hand.force_n],
            "work_j": self._number(hand.work_j),
            "stroking": hand.stroking, "stroke_ended": hand.stroke_ended}
        if hand.stroking:
            out["stroke_along_m"] = self._number(hand.stroke_along_m)
            out["stroke_length_m"] = self._number(hand.stroke_length_m)
        if hand.let_go_at_s >= 0.0:
            out["let_go"] = {"body": hand.let_go_body,
                             "velocity_m_s": [self._number(v) for v in hand.let_go_velocity_m_s],
                             "at_s": self._number(hand.let_go_at_s),
                             "work_j": self._number(hand.let_go_work_j)}
        return out

    def _flight(self, flight: "banjo.Flight") -> dict[str, Any]:
        return {"points_m": [[self._number(v) for v in p] for p in flight.points_m],
                "hit": flight.hit, "hit_name": flight.hit_name,
                "hit_point_m": [self._number(v) for v in flight.hit_point_m],
                "hit_after_s": self._number(flight.hit_after_s),
                "hit_speed_m_s": self._number(flight.hit_speed_m_s)}

    def _heat(self) -> dict[str, Any] | None:
        """The same trimmed heat block the subprocess lane puts on its replies."""
        report = self._world.thermo_report()
        if not report.get("bodies") and not report.get("regions"):
            return None
        ambient = report["ambient"]["temperature_k"]
        bodies = [b for b in report["bodies"]
                  if b["reacting"] or b["heater_w"] > 0 or abs(b["temperature_k"] - ambient) >= 1.0]
        bodies.sort(key=lambda b: -(abs(b["temperature_k"] - ambient) + (1e4 if b["reacting"] else 0)))
        return {"t": report["time_s"], "ambient_k": ambient,
                "bodies": [{"name": b["name"], "t_k": round(b["temperature_k"], 1),
                            "core_k": round(b["core_temperature_k"], 1),
                            "fuel_kg": round(b["fuel_kg"], 4),
                            "power_w": round(b["heat_release_w"]),
                            "heater_w": round(b["heater_w"]),
                            "remaining_s": (round(b["remaining_s"]) if b["remaining_s"] is not None
                                            else None),
                            "reacting": b["reacting"]} for b in bodies[:48]],
                "regions": [{"name": r["name"], "piston": r["piston"],
                             "t_k": round(r["temperature_k"], 1), "p_pa": round(r["pressure_pa"]),
                             "v_m3": r["volume_m3"], "base_m": r["base_m"], "axis": r["axis"],
                             "area_m2": r["area_m2"], "height_m": r["height_m"],
                             "stroke_m": r["stroke_m"], "force_n": round(r["force_n"], 1),
                             "work_j": round(r["work_to_bodies_j"], 2),
                             "heater_w": round(r["heater_w"])} for r in report["regions"]],
                "ledger": {"stored_j": round(report["ledger"]["stored_j"]),
                           "residual_j": report["ledger"]["residual_j"],
                           "heater_in_j": round(report["ledger"]["heater_in_j"]),
                           "heat_out_j": round(report["ledger"]["heat_to_surroundings_j"])}}

    def send(self, **command: Any) -> dict[str, Any]:
        op = str(command.get("op", ""))
        world = self._world
        try:
            if op == "step":
                dt = float(command.get("dt", 1 / 60.0))
                # Where the hand is and which way it faces, sent with the step,
                # in the order the line protocol applies them.
                if command.get("hand_q") is not None:
                    world.aim_held(command["hand_q"])
                if command.get("hand") is not None:
                    world.move_held(command["hand"])
                # Stop the batch on a step that was taken back, exactly as the
                # line protocol does, and hand the decision back to the host.
                #
                # banjo_advance would settle the break here instead, and that is
                # the right call for a program that just wants a world running.
                # It is the wrong one for this: the playground TELLS the reader
                # what broke and how hard it was hit -- "iron ball hit glass
                # plate at 6.3 m/s, it broke into 8 pieces" -- and it can only
                # do that if it is the one that decides. Resolving the break in
                # here left the chat silent about the only interesting thing
                # that had happened.
                for _ in range(max(1, int(command.get("n", 1)))):
                    if world.step(dt) == banjo.BREAK_PENDING:
                        self._stepped_back = True
                        break
                    self._stepped_back = False
            elif op == "grab":
                world.grab(str(command.get("name", "")))
            elif op == "move":
                world.move_held(command.get("to") or [0.0, 0.0, 0.0])
            elif op == "release":
                world.release()
            elif op == "wield":
                # A grip, not a carry. Without a grip given, a body that carries
                # an edge is held where its blade says, as in the other lane.
                name = str(command.get("name", ""))
                grip = command.get("grip")
                if grip is None:
                    grip = next((b.grip_m for b in world.blades()
                                 if b.body == name and b.attached), None)
                if grip is None:
                    raise ValueError("wield needs a grip, or a body with an edge")
                world.wield(name, grip)
                self.state = self._describe(extra={"wielding": name})
                return self.state
            elif op == "hand":
                if command.get("strength_n") is not None:
                    world.hand_strength(float(command["strength_n"]))
                if command.get("torque_n_m") is not None:
                    world.hand_torque(float(command["torque_n_m"]))
                if command.get("mass_kg") is not None:
                    world.hand_mass(float(command["mass_kg"]))
            elif op == "stroke":
                world.stroke(command.get("path") or [], float(command.get("speed_m_s", 0.0)),
                             float(command.get("accel_m_s2", 0.0)),
                             float(command.get("lead_m", 0.05)),
                             bool(command.get("let_go", False)),
                             float(command.get("give_up_s", 2.0)))
                self.state = self._describe(extra={"stroking": True})
                return self.state
            elif op == "cancel_stroke":
                world.cancel_stroke()
            elif op == "preview_stroke":
                # Changes nothing, so it answers on its own, like pick.
                seen = world.preview_stroke(command.get("path") or [],
                                            float(command.get("speed_m_s", 0.0)),
                                            float(command.get("accel_m_s2", 0.0)),
                                            float(command.get("lead_m", 0.05)),
                                            float(command.get("give_up_s", 2.0)),
                                            float(command.get("horizon_s", 3.0)))
                return {"ok": True, "possible": seen.possible, "why": seen.why,
                        "reaches_end": seen.reaches_end,
                        "stroke_s": self._number(seen.stroke_s),
                        "work_j": self._number(seen.work_j),
                        "let_go_at_m": [self._number(v) for v in seen.let_go_at_m],
                        "let_go_velocity_m_s": [self._number(v)
                                                for v in seen.let_go_velocity_m_s],
                        "flight": self._flight(seen.flight)}
            elif op == "preview_flight":
                flight = world.preview_flight(command.get("from") or [0.0, 0.0, 0.0],
                                              command.get("velocity") or [0.0, 0.0, 0.0],
                                              float(command.get("horizon_s", 3.0)),
                                              str(command.get("ignoring", "")))
                return dict(self._flight(flight), ok=True)
            elif op == "fracture":
                pieces = world.fracture(str(command.get("name", "")),
                                        float(command.get("window_s", 0.003)))
                self.state = self._describe(geometry=True,
                                            extra={"pieces": pieces,
                                                   "outcome": world.last_outcome})
                return self.state
            elif op == "pick":
                # The one reply that does not carry the world: it changes
                # nothing and a pointer asks it on every mouse move.
                found = world.pick(command.get("from") or [0, 0, 0],
                                   command.get("dir") or [0, -1, 0],
                                   float(command.get("max_m", 1000.0)))
                return {"ok": True, "hit": found.hit, "name": found.name,
                        "distance_m": self._number(found.distance_m),
                        "point_m": [self._number(v) for v in found.point_m]}
            elif op == "heat":
                heater = world.heat(str(command.get("target", "")),
                                    float(command.get("power_w", 0.0)),
                                    float(command.get("seconds", 0.0)))
                self.state = self._describe(extra={"heater": heater})
                return self.state
            elif op == "thermo":
                report = world.thermo_report(bool(command.get("model", False)))
                report["ledger"]["mechanical_j"] = world.energy().mechanical_j
                return {"ok": True, "thermo": report}
            elif op == "vent":
                world.vent(str(command.get("region", "")), bool(command.get("open", True)))
            elif op != "poses":
                raise ValueError(f"unknown live operation: {op}")
        except Exception as error:
            raise ValueError(str(error)) from error
        self.state = self._describe(geometry=(op == "poses"))
        return self.state

    def close(self) -> None:
        try:
            self._world.close()
        except Exception:
            pass


def scene_for(spec: dict[str, Any]) -> dict[str, Any]:
    """The scene document a spec becomes, for comparing the two lanes."""
    bodies = fracture_lab.as_objects(spec)
    return fracture_lab.scene_document(dict(spec, bodies=bodies))
