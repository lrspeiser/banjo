"""Named-world guests: persistent identities and visible, separate positions.

A world link admits a guest to the world. A second, private token identifies
that guest's avatar and possessions across reloads. Neither token is an account
or a claim that client-reported walking is a physical body in the solver.
"""
from __future__ import annotations

from copy import deepcopy

import math
import re
import secrets
import threading
import time
import uuid
from typing import Any

TOKEN = re.compile(r"[0-9a-f]{64}", re.ASCII)
ACTIVE_S = 12.0
MAX_PROFILES = 32
COLORS = ("#e6a14b", "#66b8b2", "#ae91d0", "#dc7891", "#8caf6b", "#78a4d8")


class TerrainView:
    """One bounded native geometry snapshot, acknowledged separately by each view.

    Native dirty rectangles are consumed by *any* reply, including a tool or
    clock. Invalidation hears every reply. Geometry is read lazily after a
    change, shared by viewers, and contains no private carried account.
    """
    def __init__(self):
        self.lock=threading.RLock()
        self.session=None;self.revision=0;self.geometry=None

    def reset(self, session):
        if self.session!=session:
            self.session=session;self.revision=0;self.geometry=None

    def observe(self, session, reply):
        if not reply.get('terrain_changed') and not reply.get('terrain'):return
        with self.lock:
            self.reset(session.id)
            if (not reply.get('terrain_changed') and self.geometry is not None
                    and {k:v for k,v in reply['terrain'].items() if k!='carried'}==self.geometry):
                return
            self.revision+=1;self.geometry=None

    @staticmethod
    def validate(seen):
        if seen is not None and (not isinstance(seen,dict) or set(seen)!={'session','revision'}
                or not isinstance(seen['session'],str) or len(seen['session'])>100
                or type(seen['revision']) is not int or not 0<=seen['revision']<=2**53-1):
            raise ValueError('Terrain acknowledgement requires a session and nonnegative revision')

    def attach(self, live, seen, answer):
        # Native listeners run under the Live/Session locks, then acquire ours.
        # Keep that order while capturing too; otherwise a clock reply and a
        # viewer waiting for geometry can deadlock each other.
        with live.checkpoint(), self.lock:
            session=live.session
            self.reset(session.id)
            stamp={'session':self.session,'revision':self.revision}
            if seen!=stamp:
                if self.geometry is None:
                    # The ordinary native read also invalidates through observe.
                    # The reentrant lock excludes a delayed listener overwriting
                    # this snapshot. Later mutations invalidate it again.
                    block=live.act({'session':session.id,'op':'terrain'})['terrain']
                    self.geometry={k:deepcopy(v) for k,v in block.items() if k!='carried'}
                stamp={'session':self.session,'revision':self.revision}
                answer['terrain']=deepcopy(self.geometry)
                answer.pop('terrain_changed',None)
            answer['terrain_version']=stamp


def lock_of(app: Any) -> threading.RLock:
    lock = getattr(app, "players_lock", None)
    if lock is None:
        lock = app.players_lock = threading.RLock()
    return lock


def records(app: Any) -> dict[str, dict[str, Any]]:
    room = app.room
    players = getattr(room, "player_records", None)
    if not isinstance(players, dict):
        players = room.player_records = {}
    return players


def _public_profile(player: dict[str, Any]) -> dict[str, Any]:
    return {"id": player["id"], "token": player["token"],
            "name": player["name"], "color": player["color"],
            "pose": player.get("pose")}


def resume(app: Any, token: Any = None, name: Any = None) -> dict[str, Any] | None:
    """Authenticate unchanged membership without writing a live-world checkpoint.

    None means a new guest or an actual name change still needs persistence.
    A bad token must never create a replacement identity or save the world.
    """
    if not getattr(app, "world_id", None):
        raise ValueError("Player profiles belong to a named world")
    if name is not None and (not isinstance(name, str) or not 1 <= len(name.strip()) <= 32):
        raise ValueError("Avatar name must be 1 to 32 characters")
    if not token:
        return None
    with lock_of(app):
        existing = next((p for p in records(app).values() if isinstance(token, str)
                         and TOKEN.fullmatch(token)
                         and secrets.compare_digest(p.get("token", ""), token)), None)
        if existing is None:
            raise ValueError("This player token is not in this world; the saved inventory was not replaced")
        return _public_profile(existing) if name is None or name.strip() == existing["name"] else None


def join(app: Any, token: Any = None, name: Any = None) -> dict[str, Any]:
    if not getattr(app, "world_id", None):
        raise ValueError("Player profiles belong to a named world")
    if name is not None and (not isinstance(name, str) or not 1 <= len(name.strip()) <= 32):
        raise ValueError("Avatar name must be 1 to 32 characters")
    with lock_of(app):
        returning = resume(app, token, name)
        if returning is not None:
            return returning
        players = records(app)
        existing = next((p for p in players.values() if TOKEN.fullmatch(str(token or ""))
                         and secrets.compare_digest(p.get("token", ""), token)), None)
        created = existing is None
        old_name = existing.get("name") if existing else None
        old_inventory = getattr(app.room, "inventory", None)
        old_inventory_record = getattr(app.room, "inventory_record", None)
        if existing is None:
            if token:
                raise ValueError("This player token is not in this world; the saved inventory was not replaced")
            if len(players) >= MAX_PROFILES:
                raise ValueError("This world has reached its 32 guest profiles")
            ident = uuid.uuid4().hex
            # Worlds created before player profiles had one room inventory.
            # The first guest who returns claims that record once; subsequent
            # guests begin empty rather than seeing the same bag.
            legacy = getattr(app.room, "inventory", None)
            inventory_record = (legacy.record() if not players and
                                callable(getattr(legacy, "record", None)) else
                                getattr(app.room, "inventory_record", None) if not players else None)
            existing = {"id": ident, "token": secrets.token_hex(32),
                        "name": name.strip() if name else f"Player {len(players) + 1}",
                        "color": COLORS[len(players) % len(COLORS)],
                        "inventory": inventory_record if isinstance(inventory_record, dict) else {},
                        "pose": None}
            players[ident] = existing
            if inventory_record is not None:
                app.room.inventory_record = None
                app.room.inventory = None
        elif name is not None:
            existing["name"] = name.strip()
        try:
            if not app.store.save(app.room):
                raise OSError("Room store did not save this player")
        except (OSError, TypeError, ValueError) as error:
            if created:
                players.pop(existing["id"], None)
                app.room.inventory = old_inventory
                app.room.inventory_record = old_inventory_record
            else:
                existing["name"] = old_name
            raise ValueError("The player could not be saved") from error
        return _public_profile(existing)


def require(app: Any, token: Any) -> str:
    if not getattr(app, "world_id", None):
        return ""
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ValueError("Join this world before acting in it")
    with lock_of(app):
        player = next((p for p in records(app).values()
                       if secrets.compare_digest(str(p.get("token", "")), token)), None)
        if player is None:
            raise ValueError("This player token is not in this world; join again")
        return player["id"]


def update_pose(app: Any, ident: str, person: Any) -> None:
    if not ident or not isinstance(person, dict):
        return
    eyes, facing = person.get("eyes_m"), person.get("facing")
    if not (isinstance(eyes, list) and isinstance(facing, list)
            and len(eyes) == len(facing) == 3):
        return
    try:
        eye = [float(v) for v in eyes]
        face = [float(v) for v in facing]
    except (TypeError, ValueError):
        return
    if not all(math.isfinite(v) for v in eye + face):
        return
    if abs(eye[0]) > 100 or abs(eye[2]) > 100 or not -10 <= eye[1] <= 80:
        return
    norm = math.hypot(face[0], face[2])
    if norm < 0.1:
        return
    with lock_of(app):
        player = records(app).get(ident)
        if player is not None:
            player["pose"] = {"eyes_m": [round(v, 3) for v in eye],
                              "facing": [round(face[0] / norm, 3), 0,
                                         round(face[2] / norm, 3)]}
            look = person.get("look_direction")
            if isinstance(look, list) and len(look) == 3:
                try:
                    aim = [float(v) for v in look]
                    length = math.hypot(*aim)
                    if all(math.isfinite(v) for v in aim) and length > .1:
                        player["pose"]["look_direction"] = [round(v / length, 4) for v in aim]
                except (ValueError, TypeError): pass
            player["seen_unix_s"] = time.time()


def visible(app: Any) -> list[dict[str, Any]]:
    now = time.time()
    with lock_of(app):
        return [{"id": p["id"], "name": p["name"], "color": p["color"],
                 "pose": p["pose"]}
                for p in records(app).values()
                if isinstance(p.get("pose"), dict) and now - p.get("seen_unix_s", 0) < ACTIVE_S]


def personalize_hand(state: dict[str, Any], player_id: str) -> None:
    """Show this guest only their own hand in the existing single-hand UI."""
    if player_id:
        state["hand"] = (state.get("player_hands") or {}).get(player_id) or {}
        state["hand_owner"] = player_id
        accounts=state.get('player_carried')
        if isinstance(accounts,dict):
            carried=accounts.get(player_id)
            if not isinstance(carried,dict):
                limit=(state.get('carried') or {}).get('limit_kg',80.)
                carried={'sand_m3':0.,'soil_m3':0.,'rock_m3':0.,'sand_kg':0.,'soil_kg':0.,
                         'rock_kg':0.,'objects_kg':0.,'total_kg':0.,'limit_kg':limit,'available_kg':limit,'over_limit_kg':0.}
            state['carried']=dict(carried)
            if isinstance(state.get('terrain'),dict):state['terrain']={**state['terrain'],'carried':dict(carried)}
