"""Retained history survives recent-view rotation; scopes and budgets hold."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'playground'))
import interaction_journal as journal
import interaction_trace as trace


class RetainedHistory(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app=SimpleNamespace(runs_path=Path(self.temp.name),world_id='world-one',
            build_manifest={'id':'fixture-build','configuration':{'clock_enabled':True,'inprocess':False}})

    def actor(self, name):
        return hashlib.sha256(name.encode()).hexdigest()[:16]

    def write(self, owner, attempt):
        self.assertTrue(trace.write(self.app,owner,'server',{'event':'tool-result','id':attempt,'removed_kg':.5}))

    def test_restart_and_multiple_file_rotations_preserve_all_attempts(self):
        with mock.patch.object(trace,'MAX_BYTES',1):
            for n in range(10):self.write('alice',f'request-{n}')
        restored=SimpleNamespace(runs_path=self.app.runs_path,world_id='world-one')
        newest=journal.history(restored,self.actor('alice'),limit=3)
        older=journal.history(restored,self.actor('alice'),limit=3,before=newest['next_before'])
        self.assertEqual(newest['retained_events'],10)
        self.assertEqual([r['id'] for r in newest['events']],['request-9','request-8','request-7'])
        self.assertEqual([r['id'] for r in older['events']],['request-6','request-5','request-4'])
        self.assertEqual(len((self.app.runs_path/'interaction-events.jsonl').read_text().splitlines()),1)

    def test_other_actor_and_world_rows_are_excluded(self):
        self.write('alice','alice-work');self.write('bob','bob-private')
        self.app.world_id='world-two';self.write('alice','another-world')
        self.app.world_id='world-one'
        rows=journal.history(self.app,self.actor('alice'),attempt='alice-work')
        self.assertEqual([r['id'] for r in rows['events']],['alice-work'])
        self.assertNotIn('bob-private',json.dumps(rows))
        self.assertNotIn('another-world',json.dumps(rows))

    def test_payload_and_count_limits_report_actual_available_history(self):
        with mock.patch.object(journal,'MAX_EVENTS',3):
            for n in range(5):self.write('alice',str(n))
        rows=journal.history(self.app,self.actor('alice'))
        self.assertEqual(rows['retained_events'],3)
        self.assertEqual([r['id'] for r in rows['events']],['4','3','2'])
        with mock.patch.object(journal,'MAX_PAYLOAD_BYTES',400):
            self.write('alice','new')
        with closing(sqlite3.connect(journal.path_for(self.app))) as db:
            self.assertLessEqual(db.execute('SELECT payload_bytes FROM retention').fetchone()[0],400)
            self.assertGreater(db.execute('SELECT dropped_events FROM retention').fetchone()[0],0)

    def test_expiration_and_invalid_pagination(self):
        old={'at':'2000-01-01T00:00:00.000+00:00','actor':self.actor('alice'),
             'world':'world-one','event':'tool-result','build_id':'old-build','id':'old'}
        journal.append(self.app,old)
        self.write('alice','current')
        rows=journal.history(self.app,self.actor('alice'))
        self.assertEqual([r['id'] for r in rows['events']],['current'])
        for kwargs in ({'limit':0},{'limit':201},{'before':-1},{'limit':True}):
            with self.assertRaises(ValueError):journal.history(self.app,self.actor('alice'),**kwargs)

    def test_journal_failure_cannot_cancel_gameplay(self):
        with mock.patch.object(journal,'append',side_effect=sqlite3.OperationalError('locked')):
            with self.assertLogs('banjo',level='WARNING'):
                self.assertFalse(trace.write(self.app,'alice','server',{'event':'tool-result'}))
        self.assertTrue((self.app.runs_path/'interaction-events.jsonl').is_file())

    def test_empty_read_does_not_create_a_database(self):
        self.assertEqual(journal.history(self.app,self.actor('alice'))['events'],[])
        self.assertFalse(journal.path_for(self.app).exists())

    def test_http_route_uses_authenticated_owner_and_refuses_query_override(self):
        import server
        from http.server import ThreadingHTTPServer
        self.write('alice','own-attempt');self.write('bob','private-attempt')
        host=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        host.app=self.app
        thread=threading.Thread(target=host.serve_forever,daemon=True)
        thread.start()
        def require(app, token):
            self.assertIs(app,self.app)
            if token!='fixture-token':raise ValueError('Player identity required')
            return 'alice'
        try:
            with mock.patch.object(server.player_world,'require',side_effect=require):
                base=f'http://127.0.0.1:{host.server_port}/api/world/interaction-history'
                with urlopen(Request(base+'?limit=1',headers={'X-Banjo-Player':'fixture-token'}),timeout=5) as response:
                    data=json.load(response)
                    self.assertEqual([r['id'] for r in data['events']],['own-attempt'])
                    self.assertEqual(response.headers['Cache-Control'],'no-store')
                for suffix, headers in [('',{}),('?actor=bob',{'X-Banjo-Player':'fixture-token'}),
                        ('?limit=1&limit=2',{'X-Banjo-Player':'fixture-token'}),
                        ('?before=0',{'X-Banjo-Player':'fixture-token'})]:
                    with self.assertRaises(HTTPError) as rejected:
                        urlopen(Request(base+suffix,headers=headers),timeout=5)
                    self.assertEqual(rejected.exception.code,400)
        finally:
            host.shutdown();host.server_close();thread.join(timeout=5)


if __name__=='__main__':unittest.main()
