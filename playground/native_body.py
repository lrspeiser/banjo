"""A player's native body: spawned by the host where the player stands, walked by them.

Experimental (docs/native-walk-checkpoint.md). The engine's native actor is a
70 kg upright cylinder with its own walk controller (LiveWorld
setNativePlayerWalk): grounded, traction-limited, upright, with work and
reaction accounts. This module is the host's half:

  - the actor is the authenticated player, never a name the page chooses;
  - the body is spawned once, at the player's own last reported stance on the
    ground under it, never at a position the request names;
  - each request asks for a horizontal velocity and a facing for at most
    0.3 s, so a page that stops sending leaves a passive body, not a runaway.

The page moves its camera with the body from these replies. The AI players'
reported-pose walking is unchanged until they are bound to the same requests.
"""
from __future__ import annotations

import math
import time
from contextlib import nullcontext
from typing import Any

# How long one walk request holds. The page renews it every 80 ms and sends
# a stop when the keys are let go, so this only matters when a reply is
# slow: the body keeps walking through a stall of up to half a second
# instead of stopping and starting (the engine allows at most 0.5 s).
WALK_HOLD_S = 0.5
MOST_SPEED_M_S = 6.0
# A jump off the ground: a metre's worth, a little more than a person
# (the owner, 2026-10-04: bodies are slightly superhuman).
JUMP_M_S = 4.4
EYES_ABOVE_FEET_M = 1.62
LOST_BELOW_M = 3.0          # this far under the ground at its spot, a body is lost
_LOOKED: dict[str, float] = {}   # when each player's body was last checked for being lost


def _vector(value: Any, what: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{what} is three numbers")
    out = [float(v) for v in value]
    if not all(math.isfinite(v) for v in out):
        raise ValueError(f"{what} must be finite")
    return out


def walk(app: Any, player_id: str, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or set(body) - {"session", "velocity_m_s", "heading_rad", "jump"}:
        raise ValueError("A walk is {session, velocity_m_s, heading_rad, jump?}")
    if "jump" in body and type(body["jump"]) is not bool:
        raise ValueError("jump is true or false")
    if not player_id:
        raise ValueError("Join this world before walking in it")
    velocity = _vector(body.get("velocity_m_s"), "velocity_m_s")
    velocity[1] = 0.0
    if math.hypot(velocity[0], velocity[2]) > MOST_SPEED_M_S:
        raise ValueError(f"A walk is at most {MOST_SPEED_M_S:g} m/s")
    heading = float(body.get("heading_rad", 0.0))
    if not math.isfinite(heading):
        raise ValueError("heading_rad must be finite")
    import player_world
    live = app.live
    with getattr(live, "_lock", nullcontext()):
        session = live.session
        if session is None or body.get("session") != session.id:
            raise ValueError("That live world is no longer open; start a new one")
        natives = (session.state or {}).get("native_players") or {}
        # A player who has left takes their body with them; one left standing
        # where they last were is in everyone else's way.
        now = time.time()
        for actor, record in player_world.records(app).items():
            if (actor != player_id and actor in natives
                    and now - float(record.get("seen_unix_s", 0)) > player_world.ACTIVE_S):
                session.send(op="player-remove", actor=actor)
        # A body under the ground, or off the edge of the world, is lost: it
        # is taken away and stood up again where a new player starts. One
        # thrown off the map fell for ever and saved there (2026-10-04).
        lost = False
        mine = natives.get(player_id)
        if (isinstance(mine, dict) and isinstance(mine.get("position_m"), list)
                and now - _LOOKED.get(player_id, 0.0) >= 1.0):
            _LOOKED[player_id] = now
            x, y, z = (float(v) for v in mine["position_m"])
            under = (session.send(op="survey", at=[x, z]).get("survey") or {}).get("ground_m")
            if under is None or y < float(under) - LOST_BELOW_M:
                session.send(op="player-remove", actor=player_id)
                natives = {k: v for k, v in natives.items() if k != player_id}
                lost = True
        if player_id not in natives:
            pose = (player_world.records(app).get(player_id) or {}).get("pose") or {}
            eyes = [0.0, 0.0, 0.0] if lost else pose.get("eyes_m")
            if not isinstance(eyes, list) or len(eyes) != 3:
                raise ValueError("Stand somewhere in the world before taking a native body")
            ground = (session.send(op="survey", at=[eyes[0], eyes[2]]).get("survey") or {}).get("ground_m")
            feet_y = max(float(eyes[1]) - EYES_ABOVE_FEET_M, float(ground) + 0.02 if ground is not None else -1e9)
            session.send(op="player-spawn", actor=player_id, feet_m=[eyes[0], feet_y, eyes[2]])
        reply = session.send(op="player-walk", actor=player_id, velocity_m_s=velocity,
                             heading_rad=heading, duration_s=WALK_HOLD_S,
                             **({"jump_m_s": JUMP_M_S} if body.get("jump") else {}))
        native = ((reply or {}).get("native_players") or (session.state or {}).get("native_players") or {}).get(player_id)
    return {"native": native, "eyes_above_center_m": EYES_ABOVE_FEET_M - 0.85}
