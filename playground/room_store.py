"""The rooms, kept on disk: a server started again opens them as they were left.

A room is what it was authored with -- its spec -- and what was said in it. The
chat's builds are in the spec (world_chat keeps it with export_spec after every
change), and so are the pits and heaps a spade or a pick made
(server.remember_ground). Both were held only in the server's memory, so every
restart of a server -- and the sims are restarted whenever work lands -- threw
away everything anyone had built. Now each change is written here, one file to
a room, and a room is read back the first time it is opened after a restart.

What is kept is the authored room and its conversation, and what the person has
(inventory.py): which things are in their bag and in their hands, so a restart
does not hand the bag's things back to the room. And the running world itself,
as the engine saves it (LiveWorld::snapshot, `world`): where everything is and
how it is moving or resting, what broke into what, dents and cuts, joints at
their angles, what is set aside, and what the hand holds -- so a restart gives
back the room as it stood (server.keep_world saves it; the first open after a
restart opens the room into it). A page reload does not come here: it rejoins
the running world (server._rejoin).

The format is banjo.room.v2: v1 with an optional `world`. A v1 room still reads,
as a room with no saved world, and so does a room with no inventory, as a person
with nothing. A saved world is used only for the spec it was saved from
(live_session.spec_digest): the chat's changes are a new spec, so a world saved
before them is dropped and the room opens from what the chat made. What the
engine will not put back whole is set aside -- written out beside the room with
why, never deleted -- and the room opens from its spec.

One folder to a server (build/playground-rooms/<port> by default), because the
three sims share one checkout and one person's world must not be another port's
test room. A file is written whole or not at all. A file that cannot be read,
or a room that will not open, is set aside with the time -- never deleted --
and the room opens as it was first made.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import world_room

log = logging.getLogger("banjo")

FORMAT = "banjo.room.v2"
# What is read: v1, kept before the running world was kept with its room, and v2.
READS = ("banjo.room.v1", "banjo.room.v2")


class RoomStore:
    def __init__(self, folder: Path | str) -> None:
        self.folder = Path(folder)
        self.lock = threading.Lock()

    def path_of(self, scene: str) -> Path:
        # Only the rooms on the menu are kept, under the names the menu has, so
        # a name is never more than a file name.
        if scene not in world_room.SCENES:
            raise ValueError(f"{scene!r} is not a room that is kept")
        return self.folder / f"{scene}.json"

    def save(self, room: Any) -> bool:
        """Write the room whole -- to a new file, then put in place -- or not at all."""
        if getattr(room, "scene", None) not in world_room.SCENES:
            return False
        record = {"format": FORMAT, "scene": room.scene, "saved_unix_s": round(time.time(), 3),
                  "spec": room.spec, "chat": room.chat}
        # What the person has: the record itself once it is in use
        # (inventory_room.inventory_of), else what was kept and not yet used.
        kept = getattr(room, "inventory", None)
        has = kept.record() if callable(getattr(kept, "record", None)) else getattr(room, "inventory_record", None)
        if isinstance(has, dict):
            record["inventory"] = has
        # The running world as it stood when last saved (server.keep_world),
        # written in the same file as the record of what the person has, so
        # the two are kept together or not at all.
        world = getattr(room, "world_record", None)
        if isinstance(world, dict):
            record["world"] = world
        text = json.dumps(record, allow_nan=False)
        path = self.path_of(room.scene)
        with self.lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(path.name + ".partial")
            partial.write_text(text, encoding="utf-8")
            os.replace(partial, path)
        return True

    def load(self, scene: str) -> Any:
        """The room as it was kept, or None when there is none -- or none that reads."""
        if scene not in world_room.SCENES:
            return None
        path = self.path_of(scene)
        with self.lock:
            if not path.is_file():
                return None
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if (not isinstance(record, dict) or record.get("format") not in READS
                        or record.get("scene") != scene
                        or not isinstance(record.get("spec"), dict)
                        or not isinstance(record["spec"].get("bodies"), list)
                        or not isinstance(record.get("chat", []), list)):
                    raise ValueError("it is not a kept room")
            except (OSError, ValueError) as problem:
                self._set_aside(path, str(problem))
                return None
        room = world_room.Room(scene)
        room.spec = record["spec"]
        room.chat = [turn for turn in record.get("chat", []) if isinstance(turn, dict)]
        room.kept_since = record.get("saved_unix_s")
        room.inventory_record = record["inventory"] if isinstance(record.get("inventory"), dict) else None
        room.world_record = record["world"] if isinstance(record.get("world"), dict) else None
        return room

    def set_aside_world(self, room: Any, why: str) -> None:
        """A saved world the engine would not put back whole: written out beside
        the room, with why -- never deleted -- and the room kept without it."""
        world = getattr(room, "world_record", None)
        room.world_record = None
        scene = getattr(room, "scene", None)
        if not isinstance(world, dict) or scene not in world_room.SCENES:
            return
        aside = self.folder / f"{scene}.world-set-aside-{time.strftime('%Y%m%d-%H%M%S')}.json"
        with self.lock:
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                aside.write_text(json.dumps({"why": why, "world": world}, allow_nan=False), encoding="utf-8")
                log.warning("rooms: the world kept with %s could not be put back (%s); kept as %s",
                            scene, why, aside.name)
            except (OSError, ValueError) as problem:
                log.warning("rooms: the world kept with %s could not be put back (%s) or set aside: %s",
                            scene, why, problem)
        self.save(room)

    def set_aside(self, scene: str, why: str) -> None:
        """A kept room that would not open: moved out of the way, never deleted."""
        with self.lock:
            path = self.path_of(scene)
            if path.is_file():
                self._set_aside(path, why)

    def _set_aside(self, path: Path, why: str) -> None:
        aside = path.with_name(f"{path.stem}.set-aside-{time.strftime('%Y%m%d-%H%M%S')}.json")
        try:
            os.replace(path, aside)
            log.warning("rooms: %s could not be used (%s); kept as %s", path.name, why, aside.name)
        except OSError as problem:
            log.warning("rooms: %s could not be used (%s) or moved aside: %s", path.name, why, problem)


def keep(app: Any, room: Any) -> None:
    """After anything that changes a room: write it down, if this server keeps rooms.

    A disk that will not take it is said in the log and changes nothing else: the
    room in memory is still the room."""
    store = getattr(app, "store", None)
    if store is None or room is None:
        return
    try:
        store.save(room)
    except (OSError, ValueError, TypeError) as problem:
        log.warning("rooms: could not keep %s: %s", getattr(room, "scene", "?"), problem)


def room_for(app: Any, scene: str, have: Any, fresh: bool) -> tuple[Any, bool]:
    """The room to open for `scene`, and whether it came off the disk.

    Fresh is the room as first made (kept as that once it opens). Otherwise the
    one this server already holds, then the one kept on disk, then the room as
    first made."""
    if fresh:
        return world_room.Room(scene), False
    if have is not None:
        return have, False
    store = getattr(app, "store", None)
    kept = store.load(scene) if store is not None else None
    if kept is not None:
        return kept, True
    return world_room.Room(scene), False
