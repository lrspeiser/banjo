"""A picture of each thing a person has, kept by the server.

The pages used to draw a carried thing from whatever they could find: the mesh
if it was standing in the world, a copy one browser had kept for the session,
or a coloured box. A thing just made usually showed the box, and a picture made
in one browser was never seen in another.

Now a page that can draw a thing properly (the Workshop when it makes one, or
any page that has the thing in view) renders it into a small square PNG and
sends it here. It is kept in the world's workshop database (banjo.db), one per
thing, keyed by the world, the room and the thing's item id; a newer picture
replaces the older one.

Every picture has a revision: the first 12 hex digits of the SHA-256 of its
bytes. What the pages read every few seconds (inventory_room.shown and the
Workshop's carried list) carries only that revision, `thumbnail_rev`. A page
asks for the picture itself (`read`) only when the revision is one it has not
got, so the five-second inventory poll stays small.

Only the person who has a thing may picture it: it is in one of their hands or
in their bag, or they made it in the Workshop and it is standing in the room.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import threading
from typing import Any

PREFIX = "data:image/png;base64,"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: The largest picture kept, counted as the data URL's length in characters.
#: A 128 px square of a made thing is usually 8-30 KB.
MAX_DATA_URL = 64 * 1024
#: The largest request body /api/workshop/thumbnail accepts: the picture and a
#: little JSON around it.
MAX_BODY = MAX_DATA_URL + 2048
#: How many pictures one read may ask for.
MAX_READ = 40

_LOCK = threading.Lock()


def _world(app: Any) -> str:
    return str(getattr(app, "world_id", None) or "")


def _scene(app: Any) -> str:
    room = getattr(app, "room", None)
    return str(getattr(room, "scene", None) or "")


def _connect(app: Any):
    import workshop_library
    return workshop_library._connect(app)


def _ensure(db) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS item_thumbnails (
                    world_id TEXT NOT NULL,
                    scene TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    png_data_url TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(world_id, scene, item_id))""")


def _revisions(app: Any) -> dict[tuple[str, str], str]:
    """Every kept picture's revision for this world, read once and then kept
    up to date in memory: inventory_room.shown asks for it on every poll."""
    with _LOCK:
        kept = getattr(app, "item_picture_revisions", None)
        if kept is not None:
            return kept
        kept = {}
        try:
            with _connect(app) as db:
                _ensure(db)
                for row in db.execute("SELECT scene, item_id, revision FROM item_thumbnails WHERE world_id=?",
                                      (_world(app),)):
                    kept[(row["scene"], row["item_id"])] = row["revision"]
        except Exception:
            # No database (a test app without one) means no pictures yet,
            # never a failed inventory read.
            return {}
        app.item_picture_revisions = kept
        return kept


def revision_of(app: Any, item_id: Any) -> str | None:
    """The kept picture's revision for a thing in the open room, or None."""
    if not item_id:
        return None
    return _revisions(app).get((_scene(app), str(item_id)))


def _decode(data_url: Any) -> bytes:
    if not isinstance(data_url, str) or not data_url.startswith(PREFIX):
        raise ValueError("A thumbnail must be a data:image/png;base64, URL")
    if len(data_url) > MAX_DATA_URL:
        raise ValueError(f"A thumbnail must be under {MAX_DATA_URL // 1024} KB")
    try:
        raw = base64.b64decode(data_url[len(PREFIX):], validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("The thumbnail is not valid base64") from None
    if not raw.startswith(PNG_SIGNATURE):
        raise ValueError("The thumbnail is not a PNG")
    return raw


def _owned_item(app: Any, player_id: str, asked: str) -> dict[str, Any]:
    """The thing `asked` names (its item id, or the name of any of its parts),
    if this person has it; refused otherwise."""
    import inventory_room
    import workshop_library
    room = getattr(app, "room", None)
    if room is None or not getattr(room, "spec", None):
        raise ValueError("Open a room before picturing its things")
    items = inventory_room.items_of(app)
    thing = next((i for i in items if i["id"] == asked), None) or \
        next((i for i in items if asked in i["bodies"]), None)
    if thing is None:
        raise ValueError("There is no such thing in this room")
    record = inventory_room.inventory_of(app, player_id).record()
    carried = {str(v) for v in (record.get("hands") or {}).values() if v} | \
        {str(v) for v in (record.get("stowed") or []) if v}
    if thing["id"] in carried:
        return thing
    # Made by this person and standing in the room, not yet picked up.
    me = workshop_library.rack_owner_id(app)
    names = set(thing["bodies"])
    for receipt in getattr(room, "workshop_installs", None) or []:
        if not isinstance(receipt, dict) or receipt.get("status") != "installed":
            continue
        made = set(receipt.get("root_bodies") or []) | set((receipt.get("component_to_body") or {}).values())
        if receipt.get("root_body"):
            made.add(receipt["root_body"])
        # Made by them -- unless someone else has since picked it up.
        if names & made and str(receipt.get("owner_id") or "") == me \
                and not _carried_by_someone_else(app, player_id, thing["id"]):
            return thing
    raise ValueError("Only the person who has this thing may picture it")


def _carried_by_someone_else(app: Any, player_id: str, item_id: str) -> bool:
    import inventory_room
    import player_world
    if not getattr(app, "world_id", None):
        return False
    for other in player_world.records(app):
        if other == player_id:
            continue
        try:
            record = inventory_room.inventory_of(app, other).record()
        except ValueError:
            continue
        if item_id in {str(v) for v in (record.get("hands") or {}).values() if v} | \
                {str(v) for v in (record.get("stowed") or []) if v}:
            return True
    return False


def store(app: Any, player_id: str, body: Any) -> dict[str, Any]:
    """POST /api/workshop/thumbnail {item_id, png_data_url}: keep a picture."""
    if not isinstance(body, dict) or set(body) != {"item_id", "png_data_url"}:
        raise ValueError("Send item_id and png_data_url")
    asked = body["item_id"]
    if not isinstance(asked, str) or not asked or len(asked) > 160:
        raise ValueError("item_id must be a short string")
    raw = _decode(body["png_data_url"])
    thing = _owned_item(app, player_id, asked)
    import time
    revision = hashlib.sha256(raw).hexdigest()[:12]
    scene = _scene(app)
    owner = player_id or "owner"
    revisions = _revisions(app)
    with _connect(app) as db:
        _ensure(db)
        db.execute("""INSERT INTO item_thumbnails
                        (world_id, scene, item_id, owner_id, revision, png_data_url, updated_at)
                      VALUES (?, ?, ?, ?, ?, ?, ?)
                      ON CONFLICT(world_id, scene, item_id) DO UPDATE SET
                        owner_id=excluded.owner_id, revision=excluded.revision,
                        png_data_url=excluded.png_data_url, updated_at=excluded.updated_at""",
                   (_world(app), scene, thing["id"], owner, revision, body["png_data_url"],
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    with _LOCK:
        revisions[(scene, thing["id"])] = revision
    return {"ok": True, "item_id": thing["id"], "thumbnail_rev": revision}


def read(app: Any, body: Any) -> dict[str, Any]:
    """POST /api/workshop/thumbnails {items:[item ids]}: the kept pictures of
    things in the open room, by item id, with their revisions. A thing with no
    picture is left out."""
    if not isinstance(body, dict) or set(body) != {"items"} or not isinstance(body["items"], list) \
            or len(body["items"]) > MAX_READ or not all(isinstance(i, str) and 0 < len(i) <= 160 for i in body["items"]):
        raise ValueError(f"Send items: a list of up to {MAX_READ} item ids")
    wanted = list(dict.fromkeys(body["items"]))
    out: dict[str, Any] = {}
    if not wanted:
        return {"thumbnails": out}
    with _connect(app) as db:
        _ensure(db)
        marks = ",".join("?" for _ in wanted)
        for row in db.execute(f"""SELECT item_id, revision, png_data_url FROM item_thumbnails
                                  WHERE world_id=? AND scene=? AND item_id IN ({marks})""",
                              (_world(app), _scene(app), *wanted)):
            out[row["item_id"]] = {"thumbnail_rev": row["revision"], "png_data_url": row["png_data_url"]}
    return {"thumbnails": out}
