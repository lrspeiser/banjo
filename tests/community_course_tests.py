"""Public snapshots never grant their creator's private save capability."""
from contextlib import closing
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from anonymous_profiles import ProfileError, ProfileMissing
from community_courses import CourseStore


class Courses(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CourseStore(Path(self.temp.name)/'community.sqlite3')
        self.visitor = str(uuid.uuid4())
        self.design = dict(id=str(uuid.uuid4()), name='Marble adventure',
                           draft=dict(base=None, placements=[dict(piece='marble', x_m=0, z_m=0, height_m=1)]),
                           versions=[dict(private='history')])

    def test_share_is_immutable_unlisted_deduplicated_and_survives_restart(self):
        first = self.store.share(self.visitor, self.design, 'Watch it roll')
        self.assertFalse(first['published']); self.assertEqual(self.store.browse()['courses'], [])
        self.assertEqual(first, self.store.share(self.visitor, self.design, 'Watch it roll'))
        self.design['draft']['placements'][0]['x_m'] = .3
        second = self.store.share(self.visitor, self.design)
        self.assertNotEqual(first['id'], second['id'])
        again = CourseStore(self.store.path).get(first['id'])
        self.assertEqual(again['draft']['placements'][0]['x_m'], 0)
        self.assertNotIn(self.visitor, json.dumps(again));self.assertNotIn('versions', again)
        self.assertTrue(again['preview']['base']['parts'])
        self.assertNotIn(self.visitor.encode(), self.store.path.read_bytes())

    def test_publish_update_unpublish_and_ownership_leave_old_links_playable(self):
        first = self.store.share(self.visitor, self.design, publish=True)
        self.assertEqual([row['id'] for row in self.store.browse()['courses']], [first['id']])
        stranger = str(uuid.uuid4())
        self.store.unpublish(stranger, self.design['id'])
        self.assertTrue(self.store.get(first['id'])['published'])
        self.assertEqual(self.store.mine(stranger), [])
        self.design['name'] = 'Marble adventure 2'
        second = self.store.share(self.visitor, self.design, publish=True)
        self.assertEqual([row['id'] for row in self.store.browse()['courses']], [second['id']])
        self.assertEqual(self.store.get(first['id'])['name'], 'Marble adventure')
        self.assertEqual(self.store.mine(self.visitor)[0]['design_id'], self.design['id'])
        self.store.unpublish(self.visitor, self.design['id'])
        self.assertEqual(self.store.browse()['courses'], [])
        self.assertEqual(self.store.get(second['id'])['draft'], second['draft'])

    def test_browse_search_paginates_without_duplicates_or_private_snapshots(self):
        ids = set()
        for i in range(15):
            self.design.update(id=str(uuid.uuid4()), name=f'Course {i}')
            ids.add(self.store.share(self.visitor, self.design, publish=True)['id'])
        self.design.update(id=str(uuid.uuid4()), name='Secret course')
        secret = self.store.share(self.visitor, self.design)
        first = self.store.browse(); second = self.store.browse(first['next_cursor'])
        self.assertEqual(len(first['courses']), 12);self.assertEqual(len(second['courses']), 3)
        self.assertNotIn('draft',first['courses'][0]);self.assertIn('preview',first['courses'][0])
        self.assertEqual({row['id'] for row in first['courses'] + second['courses']}, ids)
        self.assertIsNone(second['next_cursor'])
        self.assertEqual(len(self.store.browse(query='COURSE 14')['courses']), 1)
        self.assertEqual(self.store.browse(query='Secret')['courses'], [])
        self.assertNotIn(secret['id'], ids)

    def test_invalid_geometry_goals_and_ids_are_refused_before_storage(self):
        for change in (dict(placements=[dict(piece='unknown')]),dict(goal=dict(bad=True))):
            bad = copy.deepcopy(self.design);bad['draft'].update(change)
            with self.assertRaises(ProfileError):self.store.share(self.visitor, bad, publish=True)
        with self.assertRaises(ProfileError):self.store.share(self.visitor,self.design,'x'*241)
        with self.assertRaises(ProfileError):self.store.share(self.visitor,self.design,publish='yes')
        with self.assertRaises(ProfileError):self.store.get('not-an-id')
        with self.assertRaises(ProfileMissing):self.store.get(str(uuid.uuid4()))
        self.assertEqual(self.store.browse()['courses'], [])

    def test_separate_test_storage_never_opens_or_migrates_production_profiles(self):
        self.store.share(self.visitor,self.design,publish=True)
        test = CourseStore(Path(self.temp.name)/'test-logs'/'community.sqlite3')
        self.assertEqual(test.browse()['courses'], [])
        test.share(self.visitor,self.design,publish=True)
        test.unpublish(self.visitor,self.design['id'])
        self.assertEqual(len(self.store.browse()['courses']), 1)


class CourseHTTP(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        spec=importlib.util.spec_from_file_location('community_lab', ROOT/'scripts/voxel-lab.py')
        lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab)
        self.server=lab.Server(('127.0.0.1',0),Path(sys.executable),Path(self.temp.name)/'logs',
                               site='game',public=True,profile_db=Path(self.temp.name)/'profiles.sqlite3')
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        def close():
            self.server.shutdown();self.server.server_close();thread.join(timeout=5)
        self.addCleanup(close)
        self.base='http://127.0.0.1:'+str(self.server.server_address[1])

    def request(self, path, body, origin=None):
        request=urllib.request.Request(self.base+path,json.dumps(body).encode(),
                    {'Content-Type':'application/json','Origin':origin or self.base})
        try:response=urllib.request.urlopen(request,timeout=10)
        except urllib.error.HTTPError as error:response=error
        with response:return response.status,json.loads(response.read())

    def test_server_takes_only_the_owners_saved_design_and_public_reads_need_no_profile(self):
        _,opened=self.request('/api/profile',dict(op='open'));visitor=opened['visitor']
        design=dict(id=str(uuid.uuid4()),name='A public marble',draft=dict(base=None,
                     placements=[dict(piece='marble',x_m=0,z_m=0,height_m=1)]))
        _,saved=self.request('/api/profile',dict(op='save',visitor=visitor,revision=0,
                             profile=dict(sandbox=dict(items=[design]),private_note='keep private')))
        status,shared=self.request('/api/community',dict(op='share',visitor=visitor,revision=saved['revision'],design_id=design['id'],publish=True,
                                                        draft=dict(name='forged')))
        self.assertEqual(status,200,shared);course=shared['course']
        self.assertEqual(course['name'],design['name']);self.assertNotIn(visitor,json.dumps(shared))
        _,other=self.request('/api/profile',dict(op='open'))
        status,_=self.request('/api/community',dict(op='share',visitor=other['visitor'],revision=0,design_id=design['id'],publish=True))
        self.assertEqual(status,404)
        status,_=self.request('/api/community',dict(op='share',visitor=visitor,revision=0,design_id=design['id']))
        self.assertEqual(status,409)
        for op in (dict(op='get',id=course['id']),dict(op='browse')):
            status,reply=self.request('/api/community',op);self.assertEqual(status,200,reply)
            self.assertNotIn('private_note',json.dumps(reply));self.assertNotIn(visitor,json.dumps(reply))
        status,_=self.request('/api/community',dict(op='unpublish',visitor=visitor,design_id=design['id']),origin='https://other.example')
        self.assertEqual(status,400)
        self.assertEqual(self.server.profiles.open(visitor)['revision'],saved['revision'])
        with urllib.request.urlopen(self.base+'/community') as response:
            self.assertEqual(response.status,200);self.assertIn(b'community-gallery',urllib.request.urlopen(self.base+'/machine.js').read())


if __name__ == '__main__':
    unittest.main()
