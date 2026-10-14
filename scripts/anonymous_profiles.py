"""Anonymous bearer UUID profiles with durable, compare-and-swap revisions.

Only SHA-256 keys are stored. The UUID is an access token, not a public player
name. SQLite transactions reject concurrent stale saves instead of replacing
another device's newer profile. This stores initial designs, not live engines.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlsplit

MAX_PROFILE_BYTES = 8_000_000
MAX_REQUEST_BYTES = 8_100_000
DEFAULT_TOTAL_BYTES = 512_000_000
MAX_DATABASE_BYTES = 640_000_000
COOKIE_NAME = 'banjo-visitor'
TEST_COOKIE_NAME = 'banjo-test-visitor'


class ProfileError(ValueError):
    status = 400
    def __init__(self, message, **data):
        super().__init__(message)
        self.data = data


class ProfileMissing(ProfileError):
    status = 404


class ProfileConflict(ProfileError):
    status = 409


class ProfileCapacity(ProfileError):
    status = 507


class ProfileRateLimited(ProfileError):
    status = 429


class ProfileUnavailable(ProfileError):
    status = 503


def visitor_id(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', value):
        raise ProfileError('Visitor must be a UUID.')
    parsed = uuid.UUID(value)
    if parsed.variant != uuid.RFC_4122 or parsed.version != 4:
        raise ProfileError('Visitor must be a UUIDv4.')
    return str(parsed)


def encoded_profile(profile):
    if not isinstance(profile, dict):
        raise ProfileError('Profile must be a JSON object.')
    try:
        text = json.dumps(profile, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        size = len(text.encode('utf-8'))
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise ProfileError('Profile must contain valid JSON values.') from None
    if size > MAX_PROFILE_BYTES:
        raise ProfileError('Profile exceeds the 8 MB limit.')
    return text, size


def storage_persistent(path, render=None):
    """A local file survives restarts; Render needs a distinct mounted disk."""
    if not (os.environ.get('RENDER') if render is None else render):
        return True
    parent = Path(path).resolve().parent
    # The container's root is always a mount, and is not durable Render storage.
    while parent != parent.parent:
        if os.path.ismount(parent):
            return True
        parent = parent.parent
    return False


class ProfileStore:
    def __init__(self, path, max_total_bytes=None):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_total_bytes = int(max_total_bytes if max_total_bytes is not None else
                                   os.environ.get('BANJO_PROFILE_MAX_BYTES', DEFAULT_TOTAL_BYTES))
        if self.max_total_bytes < 2:
            raise ValueError('Profile storage capacity must be at least two bytes.')
        self.lock = threading.RLock()
        with self._connection() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA journal_size_limit=16000000')
            connection.execute('''CREATE TABLE IF NOT EXISTS profiles (
                key_sha256 TEXT PRIMARY KEY,
                revision INTEGER NOT NULL CHECK(revision >= 0),
                profile_json TEXT NOT NULL,
                profile_bytes INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            connection.execute('PRAGMA synchronous=FULL')
            page_size = connection.execute('PRAGMA page_size').fetchone()[0]
            connection.execute(f'PRAGMA max_page_count={MAX_DATABASE_BYTES//page_size}')
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self):
        with self.lock, self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            try:
                yield connection
                connection.execute('COMMIT')
            except BaseException:
                if connection.in_transaction:
                    connection.execute('ROLLBACK')
                raise

    @staticmethod
    def _key(visitor):
        return hashlib.sha256(visitor.encode('ascii')).hexdigest()

    def _find(self, connection, visitor):
        return connection.execute('SELECT revision,profile_json FROM profiles WHERE key_sha256=?',
                                  (self._key(visitor),)).fetchone()

    @staticmethod
    def _reply(visitor, row, created=False):
        return dict(visitor=visitor, revision=row[0], profile=json.loads(row[1]), created=created)

    def _capacity(self, connection, new_bytes, replacing_bytes=0):
        occupied = connection.execute('SELECT COALESCE(SUM(profile_bytes),0) FROM profiles').fetchone()[0]
        if occupied - replacing_bytes + new_bytes > self.max_total_bytes:
            raise ProfileCapacity('Profile storage is full; your previous saved version was kept.')

    def open(self, visitor=None, cached_visitor=None, cookie_visitor=None, before_create=None):
        # Explicit/cookie identifiers must already exist. A cached UUID is a
        # permitted migration identity; a new browser gets a random UUID4.
        if visitor is not None:
            selected, must_exist = visitor_id(visitor), True
        elif cookie_visitor is not None:
            selected, must_exist = visitor_id(cookie_visitor), True
        elif cached_visitor is not None:
            selected, must_exist = visitor_id(cached_visitor), False
        else:
            selected, must_exist = str(uuid.uuid4()), False
        with self._transaction() as connection:
            row = self._find(connection, selected)
            if row is not None:
                return self._reply(selected, row)
            if must_exist:
                raise ProfileMissing('That visitor profile was not found.', visitor=selected)
            self._capacity(connection, 2)
            if before_create:
                before_create()
            connection.execute('INSERT INTO profiles(key_sha256,revision,profile_json,profile_bytes) VALUES(?,0,?,2)',
                               (self._key(selected), '{}'))
            return self._reply(selected, (0, '{}'), True)

    def create(self, visitor, profile, before_create=None):
        selected = visitor_id(visitor)
        text, size = encoded_profile(profile)
        with self._transaction() as connection:
            row = self._find(connection, selected)
            if row is not None:
                raise ProfileConflict('That visitor profile already exists.', **self._reply(selected, row))
            self._capacity(connection, size)
            if before_create:
                before_create()
            connection.execute('INSERT INTO profiles(key_sha256,revision,profile_json,profile_bytes) VALUES(?,1,?,?)',
                               (self._key(selected), text, size))
            return self._reply(selected, (1, text), True)

    def save(self, visitor, revision, profile):
        selected = visitor_id(visitor)
        if type(revision) is not int or not 0 <= revision < 2**63-1:
            raise ProfileError('Revision must be a nonnegative integer.')
        text, size = encoded_profile(profile)
        with self._transaction() as connection:
            row = self._find(connection, selected)
            if row is None:
                raise ProfileMissing('That visitor profile was not found.', visitor=selected)
            if row[0] != revision:
                raise ProfileConflict('This profile changed on another device; your saved version was kept.',
                                      **self._reply(selected, row))
            self._capacity(connection, size, len(row[1].encode('utf-8')))
            connection.execute('UPDATE profiles SET revision=?,profile_json=?,profile_bytes=?,updated_at=CURRENT_TIMESTAMP WHERE key_sha256=?',
                               (revision+1, text, size, self._key(selected)))
            return self._reply(selected, (revision+1, text))


class _NoProfileRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class RemoteProfileStore:
    """Use the existing save API; keep test identities separate in its database.

    No database file or provider secret crosses services. Namespaced UUIDs are
    deterministic bearer credentials, not an authorization boundary against
    someone who already knows the original bearer. The default namespace keeps
    ordinary test edits from addressing production rows. CAS remains upstream.
    """
    def __init__(self, url, state_path, namespace='test'):
        parsed = urlsplit(url)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                parsed.path != '/api/profile' or
                (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'))):
            raise ValueError('Profile upstream must be an HTTPS /api/profile URL (HTTP only on loopback).')
        parsed.port
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', namespace):
            raise ValueError('Profile namespace must be a short lowercase name.')
        self.url, self.namespace = url, namespace
        self.origin = f'{parsed.scheme}://{parsed.netloc}'
        self.path = Path(state_path).resolve()  # local report outbox, never the remote database
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.opener = urllib.request.build_opener(_NoProfileRedirect())

    def remote_id(self, visitor):
        selected = visitor_id(visitor)
        if self.namespace == 'production':
            return selected
        digest = hashlib.sha256(f'banjo-profile-namespace-v1:{self.namespace}:{selected}'.encode('ascii')).digest()
        return str(uuid.UUID(bytes=digest[:16], version=4))

    def _request(self, selected, op, **data):
        remote = self.remote_id(selected)
        cached = data.pop('_cached', False)
        payload = dict(op=op, **data)
        payload['cached_visitor' if cached else 'visitor'] = remote
        request = urllib.request.Request(self.url, json.dumps(payload, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode('utf-8'),
            {'Content-Type': 'application/json', 'Origin': self.origin})
        status = 200
        try:
            try:
                response = self.opener.open(request, timeout=20)
            except urllib.error.HTTPError as error:
                response, status = error, error.code
            with response:
                body = response.read(MAX_REQUEST_BYTES + 1)
            if len(body) > MAX_REQUEST_BYTES:
                raise ValueError('Oversized upstream reply')
            reply = json.loads(body, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON')))
            if not isinstance(reply, dict) or reply.get('visitor') != remote:
                # Capacity/rate errors need not echo an identity.
                if status in (429, 507):
                    error_type = ProfileRateLimited if status == 429 else ProfileCapacity
                    raise error_type('Shared profile storage is busy or full; your previous save was kept.')
                raise ValueError('Invalid upstream identity')
            reply['visitor'] = selected
            fields = {key: reply[key] for key in ('visitor', 'revision', 'profile', 'created', 'storage') if key in reply}
            if status == 404:
                raise ProfileMissing('That test profile was not found.', visitor=selected)
            if status not in (200, 409) or type(reply.get('revision')) is not int or reply['revision'] < 0:
                raise ValueError('Invalid upstream result')
            try:
                encoded_profile(reply.get('profile'))
            except ProfileError:
                raise ValueError('Invalid upstream profile') from None
            if status == 409:
                raise ProfileConflict('This profile changed on another device; your saved version was kept.', **fields)
            if reply.get('ok') is not True:
                raise ValueError('Unsuccessful upstream result')
            storage = reply.get('storage')
            if not isinstance(storage, dict):
                raise ValueError('Invalid upstream storage metadata')
            fields['storage'] = dict(persistent=storage.get('persistent') is True,
                                     shared=True, namespace=self.namespace)
            return fields
        except ProfileError:
            raise
        except (OSError, ValueError, TypeError, KeyError, urllib.error.URLError):
            raise ProfileUnavailable('Shared profile storage is unavailable; your local draft was kept.') from None

    def open(self, visitor=None, cached_visitor=None, cookie_visitor=None, before_create=None):
        identity = next((value for value in (visitor, cookie_visitor, cached_visitor) if value is not None), None)
        selected = visitor_id(identity) if identity is not None else str(uuid.uuid4())
        try:
            return self._request(selected, 'open')
        except ProfileMissing:
            if visitor is not None or cookie_visitor is not None:
                raise
        if before_create:
            before_create()
        return self._request(selected, 'open', _cached=True)

    def create(self, visitor, profile, before_create=None):
        selected = visitor_id(visitor)
        encoded_profile(profile)
        try:
            row = self._request(selected, 'open')
        except ProfileMissing:
            row = None
        if row is not None:
            raise ProfileConflict('That visitor profile already exists.', **row)
        if before_create:
            before_create()
        return self._request(selected, 'create', profile=profile)

    def save(self, visitor, revision, profile):
        selected = visitor_id(visitor)
        if type(revision) is not int or not 0 <= revision < 2**63-1:
            raise ProfileError('Revision must be a nonnegative integer.')
        encoded_profile(profile)
        return self._request(selected, 'save', revision=revision, profile=profile)
