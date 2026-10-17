"""Persistent anonymous profiles and atomic concurrent-device saves."""
import concurrent.futures
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import anonymous_profiles as profiles


class Profiles(unittest.TestCase):
    def setUp(self):
        self.logs=tempfile.TemporaryDirectory()
        self.addCleanup(self.logs.cleanup)
        self.path=Path(self.logs.name)/'profiles.sqlite3'
        self.store=profiles.ProfileStore(self.path)

    def test_reopen_persists_designs_versions_and_revision_using_only_hashed_key(self):
        row=self.store.open();token=row['visitor']
        self.assertEqual(row['revision'],0);self.assertEqual(row['profile'],{});self.assertTrue(row['created'])
        profile={'name':'Puzzle builder','levels':{'gap':{'stars':3}},'sandbox':{'items':[
            {'name':'My river','draft':{'placements':[{'piece':'water_wheel'}]},
             'versions':[{'number':1,'draft':{'placements':[]}}]}]}}
        saved=self.store.save(token,0,profile)
        self.assertEqual(saved['revision'],1)
        restored=profiles.ProfileStore(self.path).open(visitor=token)
        self.assertEqual(restored['profile'],profile);self.assertEqual(restored['revision'],1)
        with closing(sqlite3.connect(self.path)) as connection:
            key=connection.execute('SELECT key_sha256 FROM profiles').fetchone()[0]
            self.assertEqual(key,hashlib.sha256(token.encode()).hexdigest())
            self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0],'wal')
        self.assertNotIn(token.encode(),self.path.read_bytes())

    def test_cookie_precedence_explicit_restore_and_cached_migration(self):
        a,b=str(uuid.uuid4()),str(uuid.uuid4())
        self.store.create(a,{'name':'A'});self.store.create(b,{'name':'B'})
        self.assertEqual(self.store.open(a,cached_visitor=b,cookie_visitor=b)['visitor'],a)
        self.assertEqual(self.store.open(cached_visitor=a,cookie_visitor=b)['visitor'],b)
        cached=str(uuid.uuid4());row=self.store.open(cached_visitor=cached)
        self.assertEqual(row['visitor'],cached);self.assertTrue(row['created'])
        unknown=str(uuid.uuid4())
        with self.assertRaises(profiles.ProfileMissing) as caught:self.store.open(unknown)
        self.assertEqual(caught.exception.data['visitor'],unknown)
        # A cookie this server does not know is stale (another server on the
        # same host, or a lost database): the browser's cached identity opens,
        # and is made again when it is gone, so the page never stops loading.
        self.assertEqual(self.store.open(cookie_visitor=unknown,cached_visitor=a)['visitor'],a)
        again=self.store.open(cookie_visitor=unknown,cached_visitor=cached)
        self.assertEqual(again['visitor'],cached);self.assertFalse(again['created'])
        lost=str(uuid.uuid4());fresh=self.store.open(cookie_visitor=unknown,cached_visitor=lost)
        self.assertEqual(fresh['visitor'],lost);self.assertTrue(fresh['created'])
        new=self.store.open(cookie_visitor=unknown)
        self.assertNotIn(new['visitor'],(unknown,a,b,cached,lost));self.assertTrue(new['created'])
        with self.assertRaises(profiles.ProfileMissing):self.store.open(unknown)

    def test_concurrent_devices_cannot_clobber_each_other(self):
        token=self.store.open()['visitor'];other=profiles.ProfileStore(self.path)
        barrier=threading.Barrier(8)
        def save(index):
            barrier.wait(timeout=10)
            try:return ('saved',(self.store if index%2 else other).save(token,0,{'device':index}))
            except profiles.ProfileConflict as error:return ('conflict',error.data)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(save,range(8)))
        winners=[r for status,r in rows if status=='saved']
        self.assertEqual(len(winners),1)
        conflicts=[r for status,r in rows if status=='conflict']
        self.assertEqual(len(conflicts),7)
        for conflict in conflicts:
            self.assertEqual(conflict['revision'],1);self.assertEqual(conflict['profile'],winners[0]['profile'])
        self.assertEqual(other.open(visitor=token)['profile'],winners[0]['profile'])

    def test_create_existing_is_conflict_and_never_debits_creation_callback(self):
        token=str(uuid.uuid4());calls=[]
        row=self.store.create(token,{'name':'Imported'},before_create=lambda:calls.append('created'))
        self.assertEqual(row['revision'],1);self.assertEqual(calls,['created'])
        with self.assertRaises(profiles.ProfileConflict) as caught:
            self.store.create(token,{'name':'Overwrite'},before_create=lambda:calls.append('wrong'))
        self.assertEqual(calls,['created']);self.assertEqual(caught.exception.data['profile'],{'name':'Imported'})
        with self.assertRaisesRegex(RuntimeError,'budget'):
            self.store.open(cached_visitor=str(uuid.uuid4()),before_create=lambda:(_ for _ in ()).throw(RuntimeError('budget')))

    def test_uuids_revisions_json_and_unknown_ids_are_validated_without_echoing_tokens(self):
        token=self.store.open()['visitor']
        self.assertEqual(self.store.open(visitor=token.upper())['visitor'],token)
        for bad in ('',token.replace('-',''),'https://banjo.is/'+token, 'not-a-uuid',str(uuid.uuid1()),None,42,True):
            with self.subTest(value_type=type(bad).__name__),self.assertRaises(profiles.ProfileError):
                self.store.save(bad,0,{})
        for bad in (-1,True,0.0,None,'0',2**63):
            with self.assertRaises(profiles.ProfileError):self.store.save(token,bad,{})
        for bad in ([],None,{'x':float('nan')},{'x':object()}):
            with self.assertRaises(profiles.ProfileError):self.store.save(token,0,bad)
        unknown=str(uuid.uuid4())
        with self.assertRaises(profiles.ProfileMissing):self.store.save(unknown,0,{})
        self.assertEqual(self.store.open(visitor=token)['revision'],0)

    def test_utf8_size_cap_accepts_exact_boundary_and_rejects_overflow_atomically(self):
        token=self.store.open()['visitor']
        overhead=len(json.dumps({'blob':''},separators=(',',':')).encode())
        exact={'blob':'x'*(profiles.MAX_PROFILE_BYTES-overhead)}
        self.assertEqual(len(profiles.encoded_profile(exact)[0].encode()),profiles.MAX_PROFILE_BYTES)
        self.store.save(token,0,exact)
        with self.assertRaises(profiles.ProfileError):self.store.save(token,1,{'blob':exact['blob']+'x'})
        with self.assertRaises(profiles.ProfileError):self.store.save(token,1,{'blob':'💧'*(profiles.MAX_PROFILE_BYTES//4)})
        row=self.store.open(visitor=token);self.assertEqual(row['revision'],1);self.assertEqual(row['profile'],exact)

    def test_profiles_are_isolated_and_total_capacity_never_erases_prior_state(self):
        a=self.store.open()['visitor'];b=self.store.open()['visitor']
        self.store.save(a,0,{'name':'A'});self.store.save(b,0,{'name':'B'})
        self.assertEqual(self.store.open(visitor=a)['profile'],{'name':'A'})
        self.assertEqual(self.store.open(visitor=b)['profile'],{'name':'B'})
        limited=profiles.ProfileStore(self.path,max_total_bytes=64)
        with self.assertRaises(profiles.ProfileCapacity):limited.save(a,1,{'blob':'x'*64})
        self.assertEqual(limited.open(visitor=a)['profile'],{'name':'A'})
        with limited._connection() as connection:
            page_size=connection.execute('PRAGMA page_size').fetchone()[0]
            self.assertLessEqual(connection.execute('PRAGMA max_page_count').fetchone()[0]*page_size,profiles.MAX_DATABASE_BYTES)

    def test_render_readiness_requires_a_distinct_mount_and_local_is_persistent(self):
        self.assertTrue(profiles.storage_persistent(self.path,render=False))
        with patch('anonymous_profiles.os.path.ismount',side_effect=lambda path:Path(path)==Path(path).parent):
            self.assertFalse(profiles.storage_persistent(self.path,render=True),'root mount is ephemeral')
        with patch('anonymous_profiles.os.path.ismount',side_effect=lambda path:Path(path)==self.path.parent):
            self.assertTrue(profiles.storage_persistent(self.path,render=True))


if __name__=='__main__':unittest.main(verbosity=2)
