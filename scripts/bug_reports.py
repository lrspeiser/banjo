"""Durable, anonymous bug-report delivery to the owner's Linear project.

Only a player's explicit report is queued. Credentials stay on the server;
editor snapshots contain no profile return token, cookie or visitor address.
"""
import json
import sqlite3
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

PROJECT_ID = '9e5cee1b-625f-4961-be40-22efa4ab791d'
PROJECT_URL = 'https://linear.app/horizon3/project/' + PROJECT_ID + '/overview'
API_URL = 'https://api.linear.app/graphql'


class LinearUnavailable(Exception):
    pass


class Reports:
    def __init__(self, path, key='', project_id=PROJECT_ID, team_id=''):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.key, self.project_id, self.team_id = key, str(uuid.UUID(project_id)), team_id
        self.team_resolved = False
        self.delivery_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker = None
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, payload TEXT NOT NULL, '
                       'created REAL NOT NULL, sent_url TEXT, attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self, report_id):
        with self.connect() as db:
            row = db.execute('SELECT sent_url FROM reports WHERE id=?', (report_id,)).fetchone()
        return dict(report_id=report_id, delivery='sent' if row and row[0] else 'pending',
                    **({'issue_url': row[0]} if row and row[0] else {}))

    def summary(self):
        with self.connect() as db:
            pending = db.execute('SELECT COUNT(*) FROM reports WHERE sent_url IS NULL').fetchone()[0]
        return dict(configured=bool(self.key), pending=pending)

    def submit(self, report_id, note):
        report_id = str(uuid.UUID(report_id))
        payload = json.dumps(note, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        if len(payload.encode()) > 60000:
            raise ValueError('This report is too large; report a smaller setup')
        with self.connect() as db:
            # Serialize the identity check with insertion, including concurrent
            # retries arriving on different HTTP worker threads.
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT payload FROM reports WHERE id=?', (report_id,)).fetchone()
            stable = lambda data: {k: v for k, v in data.items() if k not in ('at', 'site')}
            if old and stable(json.loads(old[0])) != stable(note):
                raise ValueError('The report changed; send it with a new report ID')
            if not old and db.execute('SELECT COUNT(*) FROM reports').fetchone()[0] >= 5000:
                raise ValueError('The bug-report inbox is full; keep your text and try later')
            db.execute('INSERT OR IGNORE INTO reports (id,payload,created) VALUES (?,?,?)', (report_id, payload, time.time()))
        self.flush(report_id)
        return self.status(report_id)

    def graphql(self, query, variables):
        request = urllib.request.Request(API_URL, json.dumps(dict(query=query, variables=variables)).encode(),
                                         {'Content-Type': 'application/json', 'Authorization': self.key})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                result = json.loads(response.read(1024*1024))
            if not isinstance(result, dict) or result.get('errors') or not isinstance(result.get('data'), dict):
                raise LinearUnavailable('Linear rejected the request')
            return result['data']
        except (OSError, ValueError, TypeError) as error:
            raise LinearUnavailable('Linear delivery is unavailable') from error

    def resolve_team(self):
        project = self.graphql('query BanjoProject($id:String!){project(id:$id){id teams{nodes{id}}}}',
                               {'id': self.project_id}).get('project')
        if not project or project.get('id') != self.project_id:
            raise LinearUnavailable('Linear project is unavailable')
        teams = [team['id'] for team in project.get('teams', {}).get('nodes', [])]
        if self.team_id:
            if self.team_id not in teams:
                raise LinearUnavailable('Configured team is not in the project')
        elif len(teams) == 1:
            self.team_id = teams[0]
        else:
            raise LinearUnavailable('Configure BANJO_LINEAR_TEAM_ID for this project')
        self.team_resolved = True

    def description(self, note):
        level = note.get('level') or 'free'
        link = 'https://banjo.is/' + ('machine' if level == 'free' else 'play?level=' + quote(level, safe=''))
        # An exported setup is useful; a private profile return link is not.
        replay = note.get('replay_link', '')
        parsed = urlsplit(replay)
        if parsed.scheme == 'https' and parsed.netloc == 'banjo.is' and parsed.path == '/machine' and parsed.fragment.startswith('build=') and not parsed.query:
            link = replay
        details = {k: note.get(k) for k in ('level', 'site', 'screen', 'touch', 'placements', 'base', 'last_run', 'world_t')}
        return note['text'] + '\n\n[Open Banjo setup](' + link + ')\n\nGame context:\n```json\n' + json.dumps(details, indent=2, ensure_ascii=False) + '\n```'

    def deliver(self, report_id, note, attempts):
        if not self.team_resolved:
            self.resolve_team()
        # Use a derived ID, never a caller's arbitrary existing Linear issue ID.
        issue_id = str(uuid.uuid5(uuid.UUID(self.project_id), report_id))
        if attempts:
            # A timeout may occur after Linear created the issue. Recover that
            # exact UUID on retry instead of filing the same report twice.
            try:
                existing = self.graphql('query BanjoReport($id:String!){issue(id:$id){id url project{id}}}', {'id': issue_id}).get('issue')
            except LinearUnavailable:
                existing = None
            if existing and (existing.get('project') or {}).get('id') == self.project_id:
                return self.issue_url(existing, issue_id)
        title = 'Banjo: ' + note['text'].splitlines()[0][:150]
        data = self.graphql('mutation BanjoBug($input:IssueCreateInput!){issueCreate(input:$input){success issue{id url project{id}}}}',
                            {'input': dict(id=issue_id, title=title, description=self.description(note),
                                           teamId=self.team_id, projectId=self.project_id)})
        created = data.get('issueCreate') or {}
        if not created.get('success') or not created.get('issue'):
            raise LinearUnavailable('Linear did not confirm issue creation')
        return self.issue_url(created['issue'], issue_id)

    def issue_url(self, issue, expected_id):
        url = issue.get('url', '')
        parsed = urlsplit(url)
        if issue.get('id') != expected_id or (issue.get('project') or {}).get('id') != self.project_id or parsed.scheme != 'https' or parsed.netloc != 'linear.app':
            raise LinearUnavailable('Linear returned an unexpected issue')
        return url

    def flush(self, report_id=None):
        if not self.key or not self.delivery_lock.acquire(blocking=False):
            return
        try:
            with self.connect() as db:
                rows = db.execute('SELECT id,payload,attempts FROM reports WHERE sent_url IS NULL AND retry_at<=? '
                                  + ('AND id=? ' if report_id else '') + 'ORDER BY created LIMIT 10',
                                  (time.time(), report_id) if report_id else (time.time(),)).fetchall()
            for identifier, payload, attempts in rows:
                if self.stop_event.is_set():
                    return
                try:
                    url = self.deliver(identifier, json.loads(payload), attempts)
                    with self.connect() as db:
                        db.execute('UPDATE reports SET sent_url=? WHERE id=?', (url, identifier))
                except (LinearUnavailable, ValueError, TypeError, KeyError):
                    with self.connect() as db:
                        db.execute('UPDATE reports SET attempts=attempts+1,retry_at=? WHERE id=?',
                                   (time.time()+min(3600, 60*2**min(attempts, 6)), identifier))
        finally:
            self.delivery_lock.release()

    def start(self):
        if not self.key or self.worker:
            return
        def work():
            while not self.stop_event.is_set():
                try:
                    self.flush()
                except sqlite3.Error:
                    pass  # Keep durable records for the next pass.
                self.stop_event.wait(60)
        self.worker = threading.Thread(target=work, daemon=True, name='banjo-bug-reports')
        self.worker.start()

    def close(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=1)
