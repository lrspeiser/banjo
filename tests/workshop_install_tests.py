"""Prototype placement boundary/concurrency tests; native cases live separately."""
from __future__ import annotations
import base64
from copy import deepcopy
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground')]
import room_store, world_room, world_access, workshop_install as install

class InstallationBoundary(unittest.TestCase):
    def test_inventory_fabrication_cannot_be_silently_free(self):
        for mode in (None,'inventory','creative',False):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError,'Inventory-funded'):
                install.preview(SimpleNamespace(),{'mode':mode})

    def test_coordinates_are_strict_and_bounded_before_engine_work(self):
        for pos in ([True,0],[float('nan'),0],[0,float('inf')],[101,0],['3',0],[],[0,0,0],None):
            with self.subTest(pos=pos),self.assertRaisesRegex(ValueError,'coordinates'):
                install.preview(SimpleNamespace(),{'mode':'authoring','position_m':pos})

    def test_commit_cannot_accept_client_geometry_or_verdict(self):
        for field in ('spec','candidate','objects','passed','mode'):
            with self.assertRaisesRegex(ValueError,'fields'):
                install.commit(SimpleNamespace(),{'preview_id':'a'*32,'request_id':'b'*32,field:{}})

    def test_snapshot_refusal_and_old_binary_never_use_cached_world(self):
        with self.assertRaisesRegex(ValueError,'current complete snapshot'):
            install._snapshot(SimpleNamespace(snapshot=lambda:(None,'a cut is in progress')))
        with self.assertRaisesRegex(ValueError,'Rebuild'):
            install._snapshot(SimpleNamespace(snapshot=lambda:({'bodies':[]},'')))

    def test_source_is_bound_to_both_scene_and_session(self):
        room=SimpleNamespace(scene='yard',spec={});old=SimpleNamespace(id='s',spec_digest=install.live_session.spec_digest({}))
        for req in ({'scene':'yard','session':'old'},{'scene':'bench','session':'s'}):
            with self.assertRaisesRegex(ValueError,'source world'):
                install._source(room,old,req)

    def test_collision_checks_actual_moved_rotated_cells_and_skip_parked(self):
        body={'name':'old','dimensions_m':[.04,.04,.04],
              'offsets_b64':base64.b64encode(struct.pack('<ddd',0,0,0)).decode(),
              'pose':{'com_m':[3.02,.02,.02],'q_wxyz':[1,0,0,0]}}
        install._clearance({'bodies':[body]},{(0,0,0)},.04)
        with self.assertRaisesRegex(ValueError,'old'):
            install._clearance({'bodies':[body]},{(75,0,0)},.04)
        body['parked']={'mass_kg':1};install._clearance({'bodies':[body]},{(75,0,0)},.04)

    def test_strict_preservation_rejects_even_unrecognized_changed_state(self):
        before={'bodies':[{'name':'old'}],'parts':[], 'next':{'body':1},'future_energy':14}
        after={**deepcopy(before),'bodies':[{'name':'old'},{'name':'new'}],'next':{'body':2}}
        install._preserved(before,after,'new')
        for key,value in (('future_energy',13),('bodies',[{'name':'old','changed':1},{'name':'new'}])):
            corrupt=deepcopy(after);corrupt[key]=value
            with self.assertRaises(ValueError):install._preserved(before,corrupt,'new')

    def test_terrain_support_bounds_interior_peaks_and_rejects_outside_grid(self):
        terrain={"grid":{"nx":3,"nz":3,"cell_m":1,"x0_m":0,"z0_m":0},
                 "heights_b64":base64.b64encode(struct.pack("<9f",0,0,0,0,2,0,0,0,0)).decode(),
                 "ground_b64":"", "carried":{}}
        old=SimpleNamespace(spec={"terrain":{}},send=lambda **kw:{"terrain":terrain,"environment":{"ground":{}}})
        old.spec["terrain"]={"generate":{}}
        height=install._terrain_floor(old,([.2,0,.2],[1.8,1,1.8]))
        self.assertGreaterEqual(height,2)
        self.assertLess(height,2.002)
        with self.assertRaisesRegex(ValueError,"whole product"):
            install._terrain_floor(old,([-0.1,0,0],[1,1,1]))
        terrain["heights_b64"]=""
        with self.assertRaisesRegex(ValueError,"Incomplete"):
            install._terrain_floor(old,([0,0,0],[1,1,1]))

    def test_material_reference_geometry_must_survive_installation(self):
        before={'bodies':[{'name':'old'}], 'parts':[], 'next':{'body':1},
                'material_geometry':{'schema':'banjo.material-geometry.v1',
                                     'records':{'old':{'applied_m':0.001}}}}
        after=deepcopy(before)
        after['bodies'].append({'name':'new'})
        after['next']['body']=2
        after['material_geometry']['records']['new']={'applied_m':0}
        install._preserved(before,after,'new')
        for change in ('depth','missing','unknown','schema'):
            bad=deepcopy(after)
            records=bad['material_geometry']['records']
            if change=='depth': records['old']['applied_m']=0
            elif change=='missing': del records['old']
            elif change=='unknown': records['absent']={}
            else: bad['material_geometry']['schema']='unknown'
            with self.subTest(change=change), self.assertRaises(ValueError):
                install._preserved(before,bad,'new')

    def test_only_the_derived_hinge_readout_allows_float32_roundoff(self):
        a = [{'held':{'at':-.03883189707994461,'lower':-3,'upper':3},'anchor':[0,0,0]}]
        b = deepcopy(a); b[0]['held']['at'] = -.03883189335465431
        self.assertTrue(install._joint_readouts_match(a,b))
        b[0]['anchor'][0]=1e-15
        self.assertFalse(install._joint_readouts_match(a,b))
        b=deepcopy(a);b[0]['held']['at']=0
        self.assertFalse(install._joint_readouts_match(a,b))

    def test_expired_previews_are_dropped(self):
        app=SimpleNamespace(_workshop_install_previews={'old':{'expires':1},'new':{'expires':100}})
        with mock.patch.object(install.time,'monotonic',return_value=2):
            self.assertEqual(['new'],list(install._preview_cache(app)))

    def test_receipts_survive_restart_and_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=room_store.RoomStore(tmp);room=world_room.Room('yard')
            room.workshop_installs=[{'request_id':str(n),'preview_id':str(n)} for n in range(70)]
            store.save(room);got=store.load('yard').workshop_installs
            self.assertEqual(64,len(got));self.assertEqual('6',got[0]['request_id'])

class WorldTransactionGate(unittest.TestCase):
    def test_normal_operations_can_overlap_but_installation_is_exclusive(self):
        gate=world_access.WorldAccess();first=threading.Event();second=threading.Event();release=threading.Event();written=threading.Event()
        def reader(event):
            with gate.enter():event.set();release.wait(3)
        def writer():
            with gate.enter(exclusive=True):written.set()
        one=threading.Thread(target=reader,args=(first,));two=threading.Thread(target=reader,args=(second,))
        one.start();two.start();self.assertTrue(first.wait(2));self.assertTrue(second.wait(2))
        three=threading.Thread(target=writer);three.start()
        self.assertFalse(written.wait(.05));release.set()
        for thread in (one,two,three):thread.join(3);self.assertFalse(thread.is_alive())
        self.assertTrue(written.is_set())

    def test_failure_releases_exclusive_access(self):
        gate=world_access.WorldAccess()
        with self.assertRaisesRegex(ValueError,'test'):
            with gate.enter(exclusive=True):raise ValueError('test')
        with gate.enter():self.assertEqual(1,gate.readers)
        self.assertFalse(gate.writer)

if __name__=='__main__':unittest.main()
