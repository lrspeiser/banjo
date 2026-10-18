"""Immutable, playable public snapshots, separate from private visitor profiles.

The existing visitor capability authorizes sharing a saved design. Public
responses never contain it (or a profile); copies become ordinary private saves.
Test's local store lives beside test-logs, outside replaceable source packages.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from anonymous_profiles import ProfileError, ProfileMissing, ProfileCapacity, visitor_id

MAX_SNAPSHOT_BYTES = 1_000_000
MAX_TOTAL_BYTES = 128_000_000
PAGE_SIZE = 12


def identifier(value):
    try:
        return visitor_id(value)
    except ProfileError:
        raise ProfileError('Choose an existing course.') from None


def snapshot(design, description):
    if not isinstance(description, str) or len(description) > 240:
        raise ProfileError('Describe your course in 240 characters or fewer.')
    draft = design.get('draft')
    if not isinstance(draft, dict) or not isinstance(draft.get('placements'), list):
        raise ProfileError('Save a design before sharing it.')
    # Whitelist the setup, never its private version history or profile data.
    draft = {key: draft[key] for key in ('base', 'placements', 'goal') if key in draft}
    name = design.get('name')
    if not isinstance(name, str) or not name.strip():
        raise ProfileError('Give your course a name before sharing it.')
    try:
        size = len(json.dumps(draft, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise ProfileError('The course must contain valid JSON.') from None
    if size > MAX_SNAPSHOT_BYTES:
        raise ProfileError('This course is too large to share.')
    # Validate the same geometry, connections and goal that Run will use.
    import machine_game
    from machine_world import compile_spec
    try:
        level = machine_game.requested_level(dict(level='free', **draft))
        spec = machine_game.compose(level, draft['placements'])[0]
        compile_spec(spec)
    except (ValueError, TypeError, KeyError) as error:
        raise ProfileError('This setup cannot run yet: ' + str(error)) from None
    # A static projection of assembled geometry, including pieces expanded by
    # the server, makes gallery cards useful without opening native worlds.
    preview = dict(base={key:spec[key] for key in ('parts','ground','electrical') if key in spec}, placements=[])
    if (draft.get('base') or {}).get('build_surface'):
        preview['base']['build_surface'] = draft['base']['build_surface']
    data = dict(name=name.strip()[:60], description=description.strip(), draft=draft, preview=preview)
    try:
        encoded = json.dumps(data, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ProfileError('The course must contain valid JSON.') from None
    if len(encoded.encode('utf-8')) > MAX_SNAPSHOT_BYTES:
        raise ProfileError('This course is too large to share.')
    return encoded


class CourseStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS courses (
                id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL, design_id TEXT NOT NULL,
                digest TEXT NOT NULL, snapshot_json TEXT NOT NULL, bytes INTEGER NOT NULL,
                listed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(owner_hash, design_id, digest))''')
            db.execute('CREATE INDEX IF NOT EXISTS courses_owner ON courses(owner_hash,design_id)')
            db.execute('CREATE INDEX IF NOT EXISTS courses_listed ON courses(listed,created_at,id)')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA max_page_count=40000')
        return db

    @staticmethod
    def owner(visitor):
        return hashlib.sha256(visitor_id(visitor).encode('ascii')).hexdigest()

    @staticmethod
    def public(row, detail=True):
        data = json.loads(row['snapshot_json'])
        if not detail and 'preview' in data:
            data.pop('draft', None)
        return dict(id=row['id'], **data, published=bool(row['listed']), created_at=row['created_at'])

    def get(self, course_id):
        with closing(self._connect()) as db:
            row = db.execute('SELECT * FROM courses WHERE id=?', (identifier(course_id),)).fetchone()
        if row is None:
            raise ProfileMissing('That shared course was not found.')
        return self.public(row)

    def browse(self, cursor=None, query=''):
        if not isinstance(query, str) or len(query) > 80:
            raise ProfileError('Search must be 80 characters or fewer.')
        before = ''
        if cursor is not None:
            if not isinstance(cursor, str) or len(cursor) > 60 or '|' not in cursor:
                raise ProfileError('Invalid gallery page.')
            date, before = cursor.split('|', 1)
            identifier(before)
        with closing(self._connect()) as db:
            if before:
                rows = db.execute('''SELECT * FROM courses WHERE listed=1
                    AND instr(lower(json_extract(snapshot_json,'$.name')),lower(?))>0
                    AND (created_at,id)<(?,?) ORDER BY created_at DESC,id DESC LIMIT ?''',
                    (query, date, before, PAGE_SIZE + 1)).fetchall()
            else:
                rows = db.execute('''SELECT * FROM courses WHERE listed=1
                    AND instr(lower(json_extract(snapshot_json,'$.name')),lower(?))>0
                    ORDER BY created_at DESC,id DESC LIMIT ?''', (query, PAGE_SIZE + 1)).fetchall()
        page = rows[:PAGE_SIZE]
        return dict(courses=[self.public(row, detail=False) for row in page],
                    next_cursor=(page[-1]['created_at'] + '|' + page[-1]['id']) if len(rows) > PAGE_SIZE else None)

    def share(self, visitor, design, description='', publish=False):
        if type(publish) is not bool:
            raise ProfileError('Publish must be true or false.')
        owner, design_id = self.owner(visitor), identifier(design.get('id'))
        encoded = snapshot(design, description)
        digest = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row = db.execute('SELECT * FROM courses WHERE owner_hash=? AND design_id=? AND digest=?',
                                 (owner, design_id, digest)).fetchone()
                if row is None:
                    size = len(encoded.encode('utf-8'))
                    if db.execute('SELECT COALESCE(SUM(bytes),0) FROM courses').fetchone()[0] + size > MAX_TOTAL_BYTES:
                        raise ProfileCapacity('Shared course storage is full; your private design is safe.')
                    course_id = str(uuid.uuid4())
                    db.execute('INSERT INTO courses(id,owner_hash,design_id,digest,snapshot_json,bytes) VALUES(?,?,?,?,?,?)',
                               (course_id, owner, design_id, digest, encoded, size))
                else:
                    course_id = row['id']
                if publish:
                    # A new version replaces its gallery card, never an old link's setup.
                    db.execute('UPDATE courses SET listed=0 WHERE owner_hash=? AND design_id=?', (owner, design_id))
                    db.execute('UPDATE courses SET listed=1 WHERE id=?', (course_id,))
                row = db.execute('SELECT * FROM courses WHERE id=?', (course_id,)).fetchone()
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise
        return self.public(row)

    def mine(self, visitor):
        with closing(self._connect()) as db:
            rows = db.execute('SELECT * FROM courses WHERE owner_hash=? AND listed=1 ORDER BY created_at DESC,id DESC',
                              (self.owner(visitor),)).fetchall()
        result = []
        for row in rows:
            data = json.loads(row['snapshot_json'])
            result.append(dict(id=row['id'],name=data['name'],description=data['description'],design_id=row['design_id']))
        return result

    def unpublish(self, visitor, design_id):
        with closing(self._connect()) as db:
            db.execute('UPDATE courses SET listed=0 WHERE owner_hash=? AND design_id=?',
                       (self.owner(visitor), identifier(design_id)))

