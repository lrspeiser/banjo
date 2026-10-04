"""Time each playtest player's opening from the world's own records.

For a world folder (build/playground-rooms/<port>/worlds/<id>), prints for every
player how many minutes after they joined they completed each opening goal:
own tool made, own tool used, first processed batch watched, camp lit, sun
charged. The times come from the saved goal receipts (starter_goal_progress in
the world's banjo.db) and the player's join time in the saved room, so they
are what the game recorded, not an observer's stopwatch.

    python tools/playtest_report.py build/playground-rooms/8765/worlds/<id> [--json out.json]

The protocol, targets and the recognition test this does not measure are in
docs/human-playtest-protocol.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

GOALS = (("make-own-tool", "Own tool made"), ("use-own-tool", "Own tool used"),
         ("observe-process", "First processed batch"), ("light-camp", "Camp lit"),
         ("charge-from-sun", "Sun charged a battery"))
TARGETS_MIN = {"make-own-tool": 5.0, "observe-process": 15.0}


def _when(text: str) -> float | None:
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def report(world: Path) -> list[dict]:
    rooms = sorted((world / "rooms").glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not rooms:
        raise SystemExit(f"no saved room under {world / 'rooms'}")
    saved = json.loads(rooms[-1].read_text(encoding="utf-8"))
    players = saved.get("players") or {}
    done: dict[str, dict[str, float]] = {}
    db = world / "banjo.db"
    if db.is_file():
        with sqlite3.connect(db) as conn:
            for owner, goal, at in conn.execute(
                    "SELECT owner_id, goal_id, completed_at FROM starter_goal_progress"):
                when = _when(at)
                if when is not None:
                    done.setdefault(owner, {})[goal] = min(when, done.get(owner, {}).get(goal, when))
    rows = []
    for ident, player in players.items():
        joined = player.get("joined_unix_s")
        row = {"player": player.get("name") or ident, "joined_unix_s": joined, "minutes": {}, "met": {}}
        for goal, _ in GOALS:
            at = done.get(ident, {}).get(goal)
            row["minutes"][goal] = None if at is None or joined is None else round((at - joined) / 60, 1)
        for goal, limit in TARGETS_MIN.items():
            minutes = row["minutes"].get(goal)
            row["met"][goal] = minutes is not None and minutes <= limit
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("world", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    rows = report(args.world)
    width = max([len(r["player"]) for r in rows] + [6])
    print("Player".ljust(width), *[label for _, label in GOALS], sep=" | ")
    for r in rows:
        cells = ["-" if r["minutes"][g] is None else f"{r['minutes'][g]} min" for g, _ in GOALS]
        print(r["player"].ljust(width), *cells, sep=" | ")
    if not any(r["joined_unix_s"] for r in rows):
        print("No join times: players who joined before join times were recorded cannot be timed.",
              file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
