"""HTTP host aliases and same-origin API requests for the deployed game."""
import argparse
import concurrent.futures
import http.client
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('banjo_game_server', ROOT / 'scripts/voxel-lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--engine')
args, remaining = parser.parse_known_args()
ENGINE = Path(args.engine or os.environ.get('BANJO_LIVE_ENGINE', ''))


class Configuration(unittest.TestCase):
    def test_test_site_redirect_target_is_operator_configured_https_only(self):
        self.assertIsNone(lab.test_site_url(None))
        self.assertEqual(lab.test_site_url('https://banjo-test.onrender.com/play/'), 'https://banjo-test.onrender.com/play')
        for value in ('http://other.example/play', 'https://secret@banjo.is/play',
                      'https://banjo.is/play?visitor=private', 'https://banjo.is/#private', 'https://banjo.is/ bad'):
            with self.assertRaises(ValueError):lab.test_site_url(value)

    def test_single_setting_and_aliases_are_combined_and_normalized(self):
        self.assertEqual(lab.public_hostnames('legacy.example', ' Banjo.is,WWW.BANJO.IS.,banjo.is '),
                         frozenset(('legacy.example', 'banjo.is', 'www.banjo.is')))

    def test_configuration_requires_explicit_hostnames(self):
        for value in ('https://banjo.is', '*.banjo.is', 'banjo.is:443', 'user@banjo.is', 'banjo.is/path'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lab.public_hostnames(value)


class BugReports(unittest.TestCase):
    def test_delivery_diagnostics_preserve_old_outbox_and_exclude_provider_secrets(self):
        import bug_reports
        import sqlite3
        import urllib.error
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reports.sqlite3'
            identifier=str(uuid.uuid4())
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE reports (id TEXT PRIMARY KEY,payload TEXT NOT NULL,created REAL NOT NULL,sent_url TEXT,attempts INTEGER NOT NULL DEFAULT 0,retry_at REAL NOT NULL DEFAULT 0)')
                db.execute('INSERT INTO reports(id,payload,created,attempts,retry_at) VALUES(?,?,0,2,9999999999)',(identifier,json.dumps(dict(text='A test report',level='easy-cut'))))
            db.close()
            store=bug_reports.Reports(path,'test-only-key')
            with patch('bug_reports.urllib.request.urlopen',side_effect=urllib.error.HTTPError(bug_reports.API_URL,401,'secret-provider-message',None,None)):
                store.flush()
                result=store.status(identifier)
            self.assertEqual(result['delivery'],'pending')
            self.assertEqual(store.summary()['last_error'],'Linear HTTP 401')
            self.assertEqual(store.summary()['pending'],1)
            self.assertNotIn('secret',json.dumps(store.summary()))

    def test_pending_reports_survive_restart_and_timeout_recovery_does_not_duplicate_linear_issue(self):
        import bug_reports
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reports.sqlite3'
            report_id=str(uuid.uuid4())
            note=dict(text='The cutting guide did not turn green',level='easy-cut',placements=[],screen=[390,844])
            store=bug_reports.Reports(path)
            self.assertEqual(store.submit(report_id,note)['delivery'],'pending')
            issues={}; creates=[]
            def remote(query,variables):
                if 'BanjoProject' in query:return {'project':{'id':bug_reports.PROJECT_ID,'teams':{'nodes':[{'id':'team-1'}]}}}
                if 'BanjoReport' in query:return {'issue':issues.get(variables['id'])}
                issue=variables['input'];creates.append(issue)
                self.assertEqual(uuid.UUID(issue['id']).version,4,'Linear rejects issue-create IDs with a different UUID version')
                issues[issue['id']]={'id':issue['id'],'url':'https://linear.app/horizon3/issue/TEST-1/bug','team':{'id':'team-1'},'project':{'id':bug_reports.PROJECT_ID}}
                raise bug_reports.LinearUnavailable('Response lost after issue creation')
            reopened=bug_reports.Reports(path,'test-only-key',project_id=bug_reports.PROJECT_ID)
            reopened.graphql=remote
            reopened.flush()
            self.assertEqual(reopened.status(report_id)['delivery'],'pending')
            recovered=bug_reports.Reports(path,'test-only-key',project_id=bug_reports.PROJECT_ID);recovered.graphql=remote
            with recovered.connect() as db:db.execute('UPDATE reports SET retry_at=0')
            recovered.flush()
            self.assertEqual(recovered.status(report_id)['delivery'],'sent')
            recovered.submit(report_id,note)
            self.assertEqual(len(creates),1)
            self.assertEqual(creates[0]['projectId'],bug_reports.PROJECT_ID)
            self.assertEqual(creates[0]['teamId'],'team-1')
            self.assertNotEqual(creates[0]['id'],report_id,'a caller cannot nominate an arbitrary existing Linear issue')
            self.assertIn('https://banjo.is/play?level=easy-cut',creates[0]['description'])
            with self.assertRaises(ValueError):recovered.submit(report_id,dict(note,text='A different report'))

    def test_default_reports_go_to_banjo_team_without_the_archived_project(self):
        import bug_reports
        with tempfile.TemporaryDirectory() as folder:
            store=bug_reports.Reports(Path(folder)/'reports.sqlite3','test-only-key')
            requests=[]
            def remote(query,variables):
                requests.append((query,variables))
                if 'BanjoTeam' in query:return {'team':{'id':bug_reports.TEAM_ID}}
                issue=variables['input']
                return {'issueCreate':{'success':True,'issue':{'id':issue['id'],'url':'https://linear.app/horizon3/issue/BAN-1/bug','team':{'id':bug_reports.TEAM_ID},'project':None}}}
            store.graphql=remote
            result=store.submit(str(uuid.uuid4()),dict(text='A test report',level='easy-cut'))
            self.assertEqual(result['delivery'],'sent')
            created=requests[-1][1]['input']
            self.assertEqual(created['teamId'],bug_reports.TEAM_ID)
            self.assertNotIn('projectId',created)
            self.assertEqual(uuid.UUID(created['id']).version,4)
            self.assertEqual(store.summary()['pending'],0)

    def test_graphql_errors_do_not_count_as_delivery_and_private_return_links_are_excluded(self):
        import bug_reports
        import io
        with tempfile.TemporaryDirectory() as folder:
            store=bug_reports.Reports(Path(folder)/'reports.sqlite3','test-only-key')
            response=json.dumps({'errors':[{'message':'secret-provider-message','extensions':{'type':'forbidden'}}],'data':{'issueCreate':{'success':True}}}).encode()
            with patch('bug_reports.urllib.request.urlopen',return_value=io.BytesIO(response)) as send:
                with self.assertRaisesRegex(bug_reports.LinearUnavailable,r'Linear rejected project lookup \(forbidden\)'):store.graphql('query BanjoProject {project(id:"fixture"){id}}',{})
                request=send.call_args.args[0]
                self.assertEqual(request.full_url,'https://api.linear.app/graphql')
                self.assertEqual(request.get_header('Authorization'),'test-only-key')
            described=store.description(dict(text='Bug',level='free',replay_link='https://banjo.is/machine?return=private-key',placements=[]))
            self.assertNotIn('private-key',described)
            self.assertIn('https://banjo.is/machine',described)


class Requests(unittest.TestCase):
    cookie_name='banjo-visitor'
    def test_completion_score_does_not_charge_for_later_live_playback(self):
        import machine_game
        level=machine_game.level_by_id('easy-wall-loop')
        def command(data):
            status,body,_=self.request(['127.0.0.1'],'POST','/api/machine',payload=data)
            result=json.loads(body)
            self.assertEqual(status,200,result)
            return result
        opened=command(dict(op='level_open',level=level['id'],placements=level['solution']))
        session=self.server.machines.get(opened['session'])
        try:
            with session.lock:session.paced=False
            command(dict(op='play',session=opened['session'],running=True))
            deadline=time.monotonic()+10
            with session.lock:
                while session.t<1.5 and not session.error and time.monotonic()<deadline:
                    session.lock.wait(.05)
                session.playing=False
                self.assertIsNone(session.error)
                self.assertGreaterEqual(session.t,1.5)
                snapshot=session.goal_snapshot
                self.assertIsNotNone(snapshot)
                self.assertLess(snapshot['t'],.5)
                current=machine_game.energy_of(session.compiled,session.readouts,session.t)['j']
            score=command(dict(op='level_score',session=opened['session']))
            self.assertEqual(score['stars'],3,score)
            self.assertLess(score['energy_j'],current/2)
            # The endpoint's score is independent of when it is requested.
            again=command(dict(op='level_score',session=opened['session']))
            self.assertEqual(again['energy_j'],score['energy_j'])
        finally:
            session.close()

    def test_try_it_stops_its_background_preview_and_late_requests_stay_cancelled(self):
        import machine_game
        from types import SimpleNamespace
        owner=str(uuid.uuid4());entered=threading.Event()
        def preview(*args,preview_job=None,**kwargs):
            entered.set()
            if not preview_job.event.wait(5):raise AssertionError('Try It did not cancel the rehearsal')
            return {'cancelled':True,'complete':False,'paths':[]}
        def post(body):
            status,data,_=self.request(['127.0.0.1'],'POST','/api/machine',payload=body)
            return status,json.loads(data)
        request={'op':'level_preview','level':'cut','placements':[],
                 'preview_owner':owner,'preview_epoch':1}
        with patch.object(machine_game,'preview',side_effect=preview),concurrent.futures.ThreadPoolExecutor() as pool:
            pending=pool.submit(post,request)
            self.assertTrue(entered.wait(5),'the preview was not admitted')
            with patch.object(self.server.machines,'get',return_value=SimpleNamespace(play=lambda *a:{'ok':True})):
                status,result=post({'op':'play','running':True,'session':'test',
                                    'preview_owner':owner,'preview_epoch':2})
                self.assertEqual(status,200,result)
            status,result=pending.result(timeout=5)
            self.assertEqual(status,200,result)
            self.assertTrue(result['cancelled'])
            self.assertFalse(result['complete'])
            # An older HTTP request arriving after Try It cannot restart work.
            status,result=post(request)
            self.assertEqual(status,200,result)
            self.assertTrue(result['cancelled'])
            self.assertFalse(self.server.preview_jobs.jobs)

    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():
            raise RuntimeError('pass --engine or BANJO_LIVE_ENGINE: the verified game executable')
        cls.logs = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.server = lab.Server(('127.0.0.1', 0), ENGINE, Path(cls.logs.name), site='game', public=True,
                                public_host='banjo-f1sv.onrender.com', public_hosts='banjo.is,www.banjo.is',
                                profile_db=Path(cls.logs.name)/'profiles.sqlite3')
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.machines.close_all()
        cls.server.server_close()
        cls.logs.cleanup()

    def request(self, hosts, method='GET', path='/play', origin=None, extra=None, payload=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
        body = (payload if isinstance(payload, bytes) else
                json.dumps(payload if payload is not None else {'op': 'levels'}).encode()) if method == 'POST' else b''
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for host in hosts:
            connection.putheader('Host', host)
        if origin is not None:
            connection.putheader('Origin', origin)
        for key, value in (extra or {}).items():
            connection.putheader(key, value)
        connection.putheader('Content-Length', str(len(body)))
        connection.endheaders(body)
        response = connection.getresponse()
        result = response.status, response.read(), response.getheaders()
        connection.close()
        return result

    def profile(self, payload, extra=None, host='127.0.0.1', origin=None):
        status, body, headers = self.request([host], 'POST', '/api/profile', origin, extra, payload)
        self.assertEqual(dict(headers)['Referrer-Policy'], 'no-referrer')
        return status, json.loads(body), dict(headers)

    def test_switch_browser_is_test_only_and_validates_before_replacing(self):
        host=self.server.machines;host.close_all();previous_limit=host.limit;host.limit=1
        def command(data):
            status,body,_=self.request(['127.0.0.1'],'POST','/api/machine',payload=data)
            return status,json.loads(body)
        try:
            status,opened=command(dict(op='level_open',level='easy-weight',placements=[]))
            self.assertEqual(status,200)
            self.assertEqual(command(dict(op='level_open',level='easy-weight',placements=[]))[0],503)
            take=dict(op='level_open',level='easy-weight',placements=[],take_over=True)
            if self.server.environment=='test':
                self.assertEqual(command(dict(take,placements=[{'piece':'not-a-piece'}]))[0],422)
                self.assertEqual(command(dict(op='frame',session=opened['session'],after=0))[0],200)
                status,replaced=command(take);self.assertEqual(status,200)
                self.assertEqual(command(dict(op='frame',session=opened['session'],after=0))[0],410)
                self.assertEqual(command(dict(op='frame',session=replaced['session'],after=0))[0],200)
            else:
                self.assertEqual(command(take)[0],400)
                self.assertEqual(command(dict(op='frame',session=opened['session'],after=0))[0],200)
            self.assertEqual(len(host.sessions),1)
        finally:host.close_all();host.limit=previous_limit

    def test_profile_reopen_and_stale_device_do_not_overwrite(self):
        status, opened, headers = self.profile({'op': 'open'})
        self.assertEqual(status, 200)
        self.assertEqual(str(uuid.UUID(opened['visitor'])), opened['visitor'])
        self.assertEqual((opened['revision'], opened['profile'], opened['created']), (0, {}, True))
        self.assertTrue(opened['storage']['persistent'])
        cookie = headers['Set-Cookie']
        for attribute in ('Path=/', 'Max-Age=31536000', 'SameSite=Lax', 'HttpOnly'):
            self.assertIn(attribute, cookie)
        self.assertNotIn('Secure', cookie)
        visitor = opened['visitor']
        profile = {'designs': [{'name': 'Marble path', 'versions': [{'placements': []}]}], 'wins': ['cut']}
        status, saved, headers = self.profile({'op': 'save', 'visitor': visitor, 'revision': 0, 'profile': profile})
        self.assertEqual((status, saved['revision'], saved['profile']), (200, 1, profile))
        self.assertNotIn('Set-Cookie', headers)
        status, second, _ = self.profile({'op': 'open', 'visitor': visitor})
        self.assertEqual((status, second['profile'], second['created']), (200, profile, False))
        status, stale, _ = self.profile({'op': 'save', 'visitor': visitor, 'revision': 0, 'profile': {'wins': []}})
        self.assertEqual((status, stale['revision'], stale['profile']), (409, 1, profile))
        self.assertEqual(self.profile({'op': 'open', 'visitor': visitor})[1]['profile'], profile)

    def test_profile_explicit_cookie_cached_precedence_and_missing_identity(self):
        ids = [str(uuid.uuid4()) for _ in range(3)]
        for visitor in ids:
            self.assertEqual(self.profile({'op': 'create', 'visitor': visitor, 'profile': {'id': visitor}})[0], 200)
        cookie = {'Cookie': self.cookie_name+'=' + ids[1]}
        self.assertEqual(self.profile({'op': 'open', 'visitor': ids[0], 'cached_visitor': ids[2]}, cookie)[1]['visitor'], ids[0])
        self.assertEqual(self.profile({'op': 'open', 'cached_visitor': ids[2]}, cookie)[1]['visitor'], ids[1])
        self.assertEqual(self.profile({'op': 'open', 'cached_visitor': ids[2]})[1]['visitor'], ids[2])
        unknown = str(uuid.uuid4())
        status, missing, _ = self.profile({'op': 'open', 'visitor': unknown}, cookie)
        self.assertEqual((status, missing['visitor']), (404, unknown))
        # A cookie the server does not know is stale (another server on the
        # same host, or a lost database): the browser's cached identity opens
        # and replaces it, rather than the page being refused on every reload.
        status, opened, headers = self.profile({'op': 'open', 'cached_visitor': ids[0]}, {'Cookie': self.cookie_name+'=' + unknown})
        self.assertEqual((status, opened['visitor']), (200, ids[0]))
        self.assertIn(self.cookie_name+'=' + ids[0], headers.get('Set-Cookie', ''))
        status, imported, _ = self.profile({'op': 'open', 'cached_visitor': unknown})
        self.assertEqual((status, imported['visitor'], imported['created']), (200, unknown, True))

    def test_profile_import_is_create_only_and_profiles_are_isolated(self):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        self.assertEqual(self.profile({'op': 'create', 'visitor': a, 'profile': {'design': 'a'}})[0], 200)
        status, conflict, headers = self.profile({'op': 'create', 'visitor': a, 'profile': {'design': 'replace'}})
        self.assertEqual((status, conflict['revision'], conflict['profile']), (409, 1, {'design': 'a'}))
        self.assertNotIn('Set-Cookie', headers)
        status, created, _ = self.profile({'op': 'create', 'visitor': b, 'profile': {'design': 'b'}})
        self.assertEqual((status, created['revision']), (200, 1))
        self.assertEqual(self.profile({'op': 'open', 'visitor': a})[1]['profile'], {'design': 'a'})
        self.assertEqual(self.profile({'op': 'open', 'visitor': b})[1]['profile'], {'design': 'b'})

    def test_profile_simultaneous_device_saves_have_exactly_one_winner(self):
        opened = self.profile({'op': 'open'})[1]
        barrier = threading.Barrier(2)
        def save(label):
            barrier.wait(timeout=10)
            return self.profile({'op': 'save', 'visitor': opened['visitor'], 'revision': 0, 'profile': {'device': label}})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ('a', 'b')))
        self.assertEqual(sorted(result[0] for result in results), [200, 409])
        winner = next(result[1] for result in results if result[0] == 200)
        conflict = next(result[1] for result in results if result[0] == 409)
        self.assertEqual(conflict['profile'], winner['profile'])
        self.assertEqual(self.profile({'op': 'open', 'visitor': opened['visitor']})[1]['profile'], winner['profile'])

    def test_profile_secure_cookie_and_origin_guards(self):
        opened = self.profile({'op': 'open'})[1]
        payload = {'op': 'open', 'visitor': opened['visitor']}
        self.assertIn('Secure', self.profile(payload, host='banjo.is', origin='https://banjo.is')[2]['Set-Cookie'])
        self.assertIn('Secure', self.profile(payload, {'X-Forwarded-Proto': 'https'})[2]['Set-Cookie'])
        status, _, _ = self.profile(payload, host='banjo.is', origin='https://evil.example')
        self.assertEqual(status, 400)

    def test_profile_validation_and_independent_body_limits(self):
        opened = self.profile({'op': 'open'})[1]
        base = {'op': 'save', 'visitor': opened['visitor'], 'revision': 0, 'profile': {}}
        for change in ({'visitor': 'not-a-uuid'}, {'revision': True}, {'revision': -1}, {'profile': []}):
            self.assertEqual(self.profile(dict(base, **change))[0], 400)
        self.assertEqual(self.profile(b'{"op":"save","profile":{"x":NaN}}')[0], 400)
        missing = str(uuid.uuid4())
        status, result, _ = self.profile(dict(base, visitor=missing))
        self.assertEqual((status, result['visitor']), (404, missing))
        large = {'draft': 'x' * 2_100_000}
        self.assertEqual(self.profile(dict(base, profile=large))[0], 200)
        self.assertEqual(self.profile(dict(base, revision=1, profile={'draft': 'x' * 8_000_000}))[0], 400)
        self.assertEqual(self.profile({'op': 'open', 'visitor': opened['visitor']})[1]['profile'], large)
        # Reject excessive Content-Length before reading a body. Neither cap is
        # implemented by retries, nor by silently truncating saved designs.
        for path, length in (('/api/profile', 8_100_001), ('/api/machine', 2_010_001)):
            connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
            connection.request('POST', path, body=None, headers={'Content-Length': str(length)})
            response = connection.getresponse()
            self.assertEqual(response.status, 413)
            response.read()
            connection.close()

    def test_profile_creation_budget_does_not_charge_existing_imports(self):
        visitor = str(uuid.uuid4())
        payload = {'op': 'create', 'visitor': visitor, 'profile': {'legacy': True}}
        self.assertEqual(self.profile(payload)[0], 200)
        original = self.server.profile_creations
        self.server.profile_creations = lab.Allowance(1, 100, 'new visitor profiles')
        try:
            self.assertEqual(self.profile(payload)[0], 409)
            self.assertEqual(self.profile({'op': 'open'})[0], 200)
            self.assertEqual(self.profile({'op': 'open'})[0], 429)
            self.assertEqual(self.profile({'op': 'open', 'visitor': visitor})[0], 200)
        finally:
            self.server.profile_creations = original

    def test_pages_and_assets_accept_each_exact_alias_and_loopback(self):
        for host in ('banjo.is', 'www.banjo.is', 'banjo-f1sv.onrender.com', 'BANJO.IS:443',
                     'banjo.is.', 'localhost', '127.0.0.1', '[::1]:18893'):
            for path in ('/play', '/machine', '/machine.js', '/api/checkpoint'):
                with self.subTest(host=host, path=path):
                    self.assertEqual(self.request([host], path=path)[0], 200)
        status, _, headers = self.request(['banjo.is'], path='/')
        self.assertEqual(status, 303)
        self.assertEqual(dict(headers)['Location'], '/play')

    def test_simultaneous_bootstrap_scripts_return_every_complete_body(self):
        # Each browser's bootstrap needs the entire module before setup can
        # start. Exercise the real listener and handler, with no connection
        # retries: a refused/reset script cannot become a ready game.
        expected = (ROOT / 'client/voxel-lab/machine.js').read_bytes()
        for burst in range(3):
            barrier = threading.Barrier(65)
            def client():
                barrier.wait(timeout=10)
                return self.request(['127.0.0.1'], path='/machine.js')
            with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
                requests = [pool.submit(client) for _ in range(64)]
                barrier.wait(timeout=10)
                results = [request.result(timeout=10) for request in requests]
            for index, (status, body, headers) in enumerate(results):
                with self.subTest(burst=burst, request=index):
                    self.assertEqual(status, 200)
                    self.assertEqual(body, expected)
                    self.assertEqual(int(dict(headers)['Content-Length']), len(expected))
            # The same listener must remain usable after all three bursts.
            self.assertEqual(self.request(['127.0.0.1'], path='/play')[0], 200)

    def test_unknown_spoofed_and_malformed_hosts_are_refused(self):
        for hosts in ([], ['evil.example'], ['banjo.is.evil.example'], ['evil@banjo.is'],
                      ['banjo.is/path'], ['banjo.is:invalid'], ['[broken'], ['banjo.is evil'],
                      ['banjo.is', 'evil.example']):
            with self.subTest(hosts=hosts):
                status, body, _ = self.request(hosts, extra={'X-Forwarded-Host': 'banjo.is'})
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(body)['error'], 'Host refused')

    def test_same_origin_api_works_on_each_alias(self):
        for host in ('banjo.is', 'www.banjo.is', 'banjo-f1sv.onrender.com'):
            with self.subTest(host=host):
                status, body, _ = self.request([host], 'POST', '/api/machine', 'https://' + host)
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)['ok'])

    def test_bug_report_is_durably_queued_without_credentials_and_retry_keeps_its_id(self):
        report_id=str(uuid.uuid4())
        payload=dict(op='feedback',report_id=report_id,text='The knife guide missed the cord',level='easy-cut',placements=[],screen=[390,844])
        for _ in range(2):
            status,body,_=self.request(['banjo.is'],'POST','/api/machine','https://banjo.is',payload=payload)
            self.assertEqual(status,200)
            response=json.loads(body)
            self.assertEqual(response['delivery'],'pending')
            self.assertEqual(response['report_id'],report_id)
        with self.server.bug_reports.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reports WHERE id=?',(report_id,)).fetchone()[0],1)

    def test_allowing_aliases_does_not_allow_cross_origin_api_calls(self):
        for host, origin in (('banjo.is', 'https://evil.example'),
                             ('banjo.is', 'https://www.banjo.is'),
                             ('banjo.is', 'https://banjo-f1sv.onrender.com'),
                             ('evil.example', 'https://evil.example')):
            with self.subTest(host=host, origin=origin):
                status, body, _ = self.request([host], 'POST', '/api/machine', origin)
                self.assertEqual(status, 400)
                self.assertIn('refused', json.loads(body)['error'])


class StagingRequests(Requests):
    """Both real HTTP servers, one actual SQLite database, separate identities."""
    cookie_name='banjo-test-visitor'

    def test_production_cookie_cannot_select_a_test_profile(self):
        live=str(uuid.uuid4());test=str(uuid.uuid4())
        self.upstream.profiles.create(live,{'design':'Live design'})
        status,opened,headers=self.profile({'op':'open','cached_visitor':test},{'Cookie':'banjo-visitor='+live})
        self.assertEqual((status,opened['visitor'],opened['profile']),(200,test,{}))
        self.assertTrue(headers['Set-Cookie'].startswith('banjo-test-visitor='))
        self.assertNotIn('Domain=',headers['Set-Cookie'])
        self.assertEqual(self.upstream.profiles.open(visitor=live)['profile'],{'design':'Live design'})
    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():raise RuntimeError('pass --engine: the verified executable')
        cls.logs=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        folder=Path(cls.logs.name)
        cls.upstream=lab.Server(('127.0.0.1',0),ENGINE,folder/'production',site='game',public=True,
            profile_db=folder/'shared.sqlite3')
        cls.upstream.profile_creations=lab.Allowance(1000,10000,'test profiles')
        threading.Thread(target=cls.upstream.serve_forever,daemon=True).start()
        cls.server=lab.Server(('127.0.0.1',0),ENGINE,folder/'test',site='game',public=True,
            environment='test',profile_upstream=f'http://127.0.0.1:{cls.upstream.server_address[1]}/api/profile',
            public_hosts='banjo.is,www.banjo.is,banjo-f1sv.onrender.com,banjo-test.onrender.com')
        cls.server.profile_creations=lab.Allowance(1000,10000,'test profiles')
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server,cls.upstream):
            server.shutdown();server.machines.close_all();server.server_close()
        cls.logs.cleanup()

    def test_test_saves_live_in_the_same_database_without_overwriting_production_rows(self):
        import anonymous_profiles
        visitor=str(uuid.uuid4())
        self.upstream.profiles.create(visitor,{'design':'Live design','wins':['cut']})
        status,opened,_=self.profile({'op':'open','cached_visitor':visitor})
        self.assertEqual((status,opened['profile']),(200,{}))
        status,saved,_=self.profile({'op':'save','visitor':visitor,'revision':0,'profile':{'design':'Test design'}})
        self.assertEqual(status,200)
        self.assertEqual(self.upstream.profiles.open(visitor=visitor)['profile']['design'],'Live design')
        mapped=self.server.profiles.remote_id(visitor)
        self.assertNotEqual(mapped,visitor)
        self.assertEqual(self.upstream.profiles.open(visitor=mapped)['profile'],{'design':'Test design'})
        reopened=anonymous_profiles.RemoteProfileStore(self.server.profiles.url,Path(self.logs.name)/'restarted/proxy.sqlite3')
        self.assertEqual(reopened.open(visitor=visitor)['profile'],saved['profile'])
        self.assertEqual(reopened.open(visitor=visitor)['revision'],1)
        self.assertEqual(saved['storage'],{'persistent':True,'shared':True,'namespace':'test'})

    def test_test_badge_checkpoint_and_entry_route(self):
        status,body,_=self.request(['banjo-test.onrender.com'])
        self.assertEqual(status,200)
        self.assertIn(b'data-banjo-environment="test"',body)
        self.assertIn(b'id="environment-badge">TEST',body)
        status,body,_=self.request(['127.0.0.1'],path='/api/checkpoint')
        checkpoint=json.loads(body)
        self.assertEqual(checkpoint['environment'],'test')
        self.assertEqual(checkpoint['profiles'],{'shared':True,'namespace':'test'})
        original=self.upstream.test_url
        self.upstream.test_url='https://banjo-test.onrender.com/play'
        try:
            connection=http.client.HTTPConnection('127.0.0.1',self.upstream.server_address[1])
            connection.request('GET','/test?next=https://evil.example&visitor=private')
            response=connection.getresponse();response.read();connection.close()
            self.assertEqual(response.status,303)
            self.assertEqual(response.getheader('Location'),self.upstream.test_url)
            self.assertNotIn('private',response.getheader('Location'))
        finally:self.upstream.test_url=original
        self.assertEqual(self.request(['127.0.0.1'],path='/test')[0],503)

    def test_unavailable_storage_refuses_writes_and_never_falls_back_to_local_saves(self):
        import urllib.error
        status,opened,_=self.profile({'op':'open'})
        with patch.object(self.server.profiles.opener,'open',side_effect=urllib.error.URLError('secret upstream detail')):
            status,result,_=self.profile({'op':'save','visitor':opened['visitor'],'revision':0,'profile':{'lost':True}})
        self.assertEqual(status,503)
        self.assertNotIn('secret',json.dumps(result))
        self.assertFalse(self.server.profiles.path.exists())
        self.assertEqual(self.profile({'op':'open','visitor':opened['visitor']})[1]['profile'],{})

    def test_remote_profile_redirects_do_not_forward_bearer_credentials(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        arrivals=[]
        class Trap(BaseHTTPRequestHandler):
            def do_POST(self):arrivals.append(True);self.send_response(500);self.end_headers()
            def log_message(self,*args):pass
        trap=ThreadingHTTPServer(('127.0.0.1',0),Trap)
        threading.Thread(target=trap.serve_forever,daemon=True).start()
        original=lab.Handler.do_POST
        upstream=self.upstream
        def redirect(handler):
            if handler.server is upstream:
                handler.rfile.read(int(handler.headers.get('Content-Length','0')))
                handler.send(307,b'{}',headers={'Location':f'http://127.0.0.1:{trap.server_address[1]}/api/profile'})
            else:original(handler)
        try:
            with patch.object(lab.Handler,'do_POST',redirect):status,_,_=self.profile({'op':'open'})
            self.assertEqual(status,503)
            self.assertEqual(arrivals,[])
        finally:trap.shutdown();trap.server_close()


if __name__ == '__main__':
    unittest.main(argv=[__file__, *remaining], verbosity=2)
