"""Indexed retained diagnostics, not a simulation/paid-operation journal.

Rows must already have passed interaction_trace's allowlist and server-owned
provenance. Queries are scoped to the authenticated actor/world by the caller.
The JSON payload budget excludes SQLite/index overhead and reusable free pages.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

RETENTION_DAYS = 14
MAX_EVENTS = 100_000
MAX_PAYLOAD_BYTES = 128 * 1024 * 1024
MAX_EVENT_BYTES = 64 * 1024
MAX_PAGE = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL, actor TEXT NOT NULL, world TEXT NOT NULL,
    attempt TEXT, kind TEXT NOT NULL, build TEXT NOT NULL,
    payload TEXT NOT NULL, bytes INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS events_actor ON events(actor,world,sequence);
CREATE INDEX IF NOT EXISTS events_age ON events(at);
CREATE INDEX IF NOT EXISTS events_attempt ON events(actor,world,attempt,sequence);
CREATE TABLE IF NOT EXISTS retention (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    payload_bytes INTEGER NOT NULL, dropped_events INTEGER NOT NULL);
INSERT OR IGNORE INTO retention VALUES(1,0,0);
"""


def path_for(app):
    return Path(app.runs_path) / 'interaction-history.sqlite'


def append(app, row):
    payload = json.dumps(row, separators=(',', ':'), allow_nan=False)
    size = len(payload.encode('utf-8'))
    if size > MAX_EVENT_BYTES:
        raise ValueError('Diagnostic record exceeds retained-event budget')
    path = path_for(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=.1, isolation_level=None)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO events(at,actor,world,attempt,kind,build,payload,bytes) VALUES(?,?,?,?,?,?,?,?)',
                   (row['at'], row['actor'], row.get('world') or '', row.get('id'),
                    row['event'], row['build_id'], payload, size))
        db.execute('UPDATE retention SET payload_bytes=payload_bytes+? WHERE singleton=1', (size,))
        cutoff = (datetime.now(timezone.utc)-timedelta(days=RETENTION_DAYS)).isoformat(timespec='milliseconds')
        expired = db.execute('SELECT sequence,bytes FROM events WHERE at<?', (cutoff,)).fetchall()
        if expired:
            db.execute('DELETE FROM events WHERE at<?', (cutoff,))
            db.execute('UPDATE retention SET payload_bytes=payload_bytes-?,dropped_events=dropped_events+? WHERE singleton=1',
                       (sum(r[1] for r in expired), len(expired)))
        count = db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        retained = db.execute('SELECT payload_bytes FROM retention WHERE singleton=1').fetchone()[0]
        # Evict a bounded oldest prefix, in batches, until both limits hold.
        # Budgets prevent this loop from ranging over an unbounded history.
        while count > MAX_EVENTS or retained > MAX_PAYLOAD_BYTES:
            excess = db.execute('SELECT sequence,bytes FROM events ORDER BY sequence LIMIT 256').fetchall()
            removed = 0
            length = 0
            for sequence, amount in excess:
                removed += amount
                length += 1
                if count-length <= MAX_EVENTS and retained-removed <= MAX_PAYLOAD_BYTES:
                    break
            db.execute('DELETE FROM events WHERE sequence<=?', (sequence,))
            db.execute('UPDATE retention SET payload_bytes=payload_bytes-?,dropped_events=dropped_events+? WHERE singleton=1',
                       (removed, length))
            count -= length
            retained -= removed
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def history(app, actor_hash, *, before=None, limit=100, attempt=None):
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        raise ValueError(f'History limit is 1..{MAX_PAGE}')
    if before is not None and (type(before) is not int or before < 1):
        raise ValueError('History cursor is a positive sequence')
    if attempt is not None and (not isinstance(attempt, str) or not 1 <= len(attempt) <= 80):
        raise ValueError('Attempt is a bounded request ID')
    policy = {'days': RETENTION_DAYS, 'max_events': MAX_EVENTS,
              'max_payload_bytes': MAX_PAYLOAD_BYTES, 'max_page': MAX_PAGE}
    result = {'schema':'banjo.interaction-history.v1', 'policy':policy, 'events':[],
              'next_before':None, 'oldest_available':None, 'newest_available':None, 'retained_events':0}
    path = path_for(app)
    if not path.is_file():
        return result
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.1)
    try:
        # A single read transaction prevents retention races between page and
        # metadata. No other actor's diagnostic payload is selected.
        db.execute('BEGIN')
        # Idle worlds also obey the age limit; physical cleanup happens on append.
        cutoff = (datetime.now(timezone.utc)-timedelta(days=RETENTION_DAYS)).isoformat(timespec='milliseconds')
        base = 'actor=? AND world=? AND at>=?'
        parameters = [actor_hash, getattr(app,'world_id',None) or '', cutoff]
        meta = db.execute('SELECT MIN(at),MAX(at),COUNT(*) FROM events WHERE '+base, parameters).fetchone()
        result.update(oldest_available=meta[0],newest_available=meta[1],retained_events=meta[2])
        where = base
        if before is not None:
            where += ' AND sequence<?'; parameters.append(before)
        if attempt is not None:
            where += ' AND attempt=?'; parameters.append(attempt)
        rows = db.execute('SELECT sequence,payload FROM events WHERE '+where+' ORDER BY sequence DESC LIMIT ?',
                          (*parameters,limit+1)).fetchall()
        result['events'] = [{'sequence':r[0], **json.loads(r[1])} for r in rows[:limit]]
        if len(rows)>limit:
            result['next_before'] = rows[limit-1][0]
        return result
    finally:
        db.close()
