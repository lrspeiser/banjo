"""Actual native carry, persistence and rollback tests for Workshop installation."""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground')]
import inventory,live_session,room_store,world_room,workshop_install as install
import workshop_sparse_trial as sparse
import workshop_bench_core
ENGINE=Path(os.environ['BANJO_LIVE_ENGINE']).resolve() if os.environ.get('BANJO_LIVE_ENGINE') else None

@unittest.skipUnless(ENGINE and ENGINE.is_file(),'BANJO_LIVE_ENGINE is required')
class NativeInstallation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.live=live_session.Live();self.addCleanup(self.live.shutdown)
        self.room=world_room.Room('yard');self.room.inventory=inventory.Inventory()
        self.app=SimpleNamespace(live=self.live,live_holder='world',room=self.room,engine_path=ENGINE,
          runs_path=root/'runs',store=room_store.RoomStore(root/'rooms'))
        self.open()

    def open(self,spec=None):
        if spec is not None:self.room.spec=spec
        self.live.open(self.app,{'spec':self.room.spec})
        self.ctx=install.context(self.app,{})

    def snap(self):return install._snapshot(self.live)
    def preview(self,material='oak',position=(3,0),candidate=None):
        return install.preview(self.app,{'session':self.ctx['session'],'scene':'yard','mode':'authoring',
          'position_m':list(position),'candidate':candidate or {'kind':'table','parameters':{'material':material}}})
    def request(self,p,request='install-request-1'):
        return {'scene':'yard','session':self.ctx['session'],'preview_id':p['preview_id'],'request_id':request}
    def do_commit(self,p,request='install-request-1'):return install.commit(self.app,self.request(p,request))

    def built(self,material='oak'):
        """A table whose joints are its own, as building it part by part leaves
        it: a bare template says nothing about how it was put together."""
        from mcp import workshop_components,workshop_construction
        spec={'kind':'table','design_id':'t','parameters':{'material':material}}
        design=workshop_components.design_from_spec(spec)[0]
        return {**spec,'component_overrides':{workshop_construction.CONSTRUCTION_KEY:
                                              workshop_construction.adopted(design)}}

    def test_preview_and_install_glass_oak_iron_use_exact_matter_and_keep_original(self):
        for index,material in enumerate(('glass','oak','iron')):
            with self.subTest(material=material):
                self.ctx=install.context(self.app,{})
                old=self.live.session;before=self.snap();record=self.room.inventory.record()
                p=self.preview(material,position=(3+index*2,0))
                self.assertIs(old,self.live.session);self.assertEqual(before,self.snap())
                self.assertFalse(self.app.store.path_of('yard').exists() if index==0 else False)
                result=self.do_commit(p,request=f'install-request-{index}')
                self.assertEqual('installed',result['status']);self.assertTrue(old._closed)
                self.assertEqual(record,self.room.inventory.record())
                install._preserved(before,self.snap(),result['root_body'])
                self.assertTrue(result['engine_grid_verified']);self.assertFalse(result['resources_charged'])
                loaded=self.app.store.load('yard');self.assertEqual(self.room.spec,loaded.spec)
                self.assertEqual(self.snap(),loaded.world_record)
                # Installed solid is actually in the running engine, not just
                # in a saved recipe or a separate demonstration scene.
                reply=self.live.act({'session':self.live.session.id,'op':'step','dt':1/120,'n':2})
                self.assertIn(result['root_body'],[b['name'] for b in reply['bodies']])

    def test_an_installed_product_carries_its_joints_into_the_room(self):
        """#20 in a live room. A product used to arrive as one heap of cells, so
        every joint in it was as strong as the solid wood. Its cells now keep
        which component they are and the joints declared in the Workshop come
        with them, so a blow lands on a table that is glued, not carved."""
        # A template installed as it comes declares no joints: its parts are
        # labelled, but nothing says how they were put together, and inventing
        # that would be asserting a construction nobody chose. Joints arrive
        # once the design's own are (workshop_construction.adopted) -- which is
        # what building it part by part in the Workshop makes.
        plain=self.do_commit(self.preview(position=(11,0)),request='install-plain')
        self.assertNotIn('interfaces',self.room.spec)
        self.assertTrue({b['part'] for b in self.room.spec['bodies'] if b.get('part')})
        self.assertTrue(plain['root_body'])
        self.ctx=install.context(self.app,{})
        result=self.do_commit(self.preview(candidate=self.built()));root=result['root_body']
        spec=self.room.spec
        self.assertEqual({f'{root}/top'}|{f'{root}/leg-{i}' for i in range(1,5)},
                         {b['part'] for b in spec['bodies'] if b.get('part')}-
                         {b['part'] for b in spec['bodies']
                          if b.get('part','').startswith(plain['root_body'])})
        self.assertEqual(4,len(spec['interfaces']))
        for face in spec['interfaces']:
            self.assertEqual(f'{root}/top',face['a'])
            self.assertEqual((.25,.25,1.0),(face['tension'],face['shear'],face['compression']))
        # Every label carries the root, so a second table of the same design is
        # its own object with its own four joints, not a second claim on these.
        self.ctx=install.context(self.app,{})
        second=self.do_commit(self.preview(position=(7,0),candidate=self.built()),
                              request='install-request-2')['root_body']
        self.assertNotEqual(root,second)
        roots=[f['a'].split('/')[0] for f in self.room.spec['interfaces']]
        self.assertEqual({root:4,second:4},{r:roots.count(r) for r in set(roots)})
        # And what is written to disk is what comes back, joints and all.
        self.assertEqual(self.room.spec,self.app.store.load('yard').spec)

    def test_retry_and_restart_return_one_persistent_receipt(self):
        p=self.preview();req=self.request(p);first=install.commit(self.app,req)
        after=self.snap();spec=deepcopy(self.room.spec)
        again=install.commit(self.app,req);self.assertTrue(again['replayed']);self.assertEqual(after,self.snap());self.assertEqual(spec,self.room.spec)
        room=self.app.store.load('yard');self.live.shutdown();self.app.room=self.room=room
        self.live.open(self.app,{'spec':room.spec,'snapshot':room.world_record})
        again=install.commit(self.app,req);self.assertTrue(again['replayed']);self.assertEqual(first['root_body'],again['root_body'])
        self.assertEqual(1,len(room.workshop_installs))
        with self.assertRaisesRegex(ValueError,'different installation'):
            install.commit(self.app,{**req,'preview_id':'otherpreview1234'})

    def test_concurrent_retries_install_once(self):
        from concurrent.futures import ThreadPoolExecutor
        p=self.preview();req=self.request(p)
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers=list(pool.map(lambda _:install.commit(self.app,req),range(2)))
        self.assertEqual([False,True],sorted(a['replayed'] for a in answers))
        self.assertEqual(1,len(self.room.workshop_installs))
        self.assertEqual(1,sum(b['name']==p['root_body'] for b in self.snap()['bodies']))

    def test_state_or_inventory_change_makes_preview_stale(self):
        for change in ('step','inventory'):
            with self.subTest(change=change):
                self.ctx=install.context(self.app,{});p=self.preview();old=self.live.session
                if change=='step':old.send(op='step',dt=1/120,n=1)
                else:self.room.inventory.revision+=1
                before=self.snap();spec=deepcopy(self.room.spec)
                with self.assertRaisesRegex(ValueError,'changed after preview'):self.do_commit(p)
                self.assertIs(old,self.live.session);self.assertEqual(before,self.snap());self.assertEqual(spec,self.room.spec)

    def test_session_switch_and_expiry_are_refused(self):
        p=self.preview();req=self.request(p)
        self.live.rejoin(self.app)
        with self.assertRaisesRegex(ValueError,'source world'):install.commit(self.app,req)
        self.ctx=install.context(self.app,{});p=self.preview()
        self.app._workshop_install_previews[p['preview_id']]['expires']=0
        with self.assertRaisesRegex(ValueError,'expired'):self.do_commit(p)

    def test_collision_refusal_preserves_original(self):
        before=self.snap();old=self.live.session
        with self.assertRaisesRegex(ValueError,'overlaps|touches'):self.preview(position=(-5,-5))
        self.assertEqual(before,self.snap());self.assertIs(old,self.live.session)

    def test_mixed_material_articulated_and_disconnected_candidates_are_refused(self):
        for candidate in (
          {'kind':'table','component_overrides':{'leg-1':{'material':'iron'}}},
          {'kind':'cart'},
          {'kind':'table','component_overrides':{'top':{'skin':{'profile':'curve','bend_m':1,'physical':True}}}}):
            with self.subTest(candidate=candidate):
                before=self.snap()
                with self.assertRaises(ValueError):self.preview(candidate=candidate)
                self.assertEqual(before,self.snap())

    def test_disk_and_native_verification_failure_never_replace_original(self):
        p=self.preview();old=self.live.session;before=self.snap();spec=deepcopy(self.room.spec)
        for where in ('disk','native'):
            with self.subTest(where=where):
                target=mock.patch.object(self.app.store,'save',side_effect=OSError('disk full')) if where=='disk' else mock.patch.object(sparse,'verify_engine_matter',side_effect=ValueError('native mismatch'))
                with target,self.assertRaises((ValueError,OSError)):self.do_commit(p)
                self.assertIs(old,self.live.session);self.assertFalse(old._closed)
                self.assertEqual(before,self.snap());self.assertEqual(spec,self.room.spec)
                self.assertFalse(self.app.store.path_of('yard').exists())
        self.assertEqual('installed',self.do_commit(p)['status'])

    def test_unknown_binary_and_busy_snapshot_are_not_fallbacks(self):
        before=self.snap();old=self.live.session
        for saved,why in ((None,'break in progress'),({'bodies':[]},'')):
            with mock.patch.object(self.live,'snapshot',return_value=(saved,why)),self.assertRaises(ValueError):self.preview()
            self.assertIs(old,self.live.session)
        self.assertEqual(before,self.snap())

    def test_parked_inventory_item_remains_parked_and_owned(self):
        spec=world_room.yard();spec['bodies'].append({'name':'kept','shape':'box','material':'iron','size_mm':[80]*3,'center_mm':[0,40,0]})
        self.open(spec);self.live.session.send(op='park',name='kept');self.room.inventory.stowed=['kept']
        before=self.snap();p=self.preview();self.do_commit(p);install._preserved(before,self.snap(),p['root_body'])
        self.assertEqual(['kept'],self.room.inventory.stowed)
        self.assertTrue(next(b for b in self.snap()['bodies'] if b['name']=='kept')['parked'])

    def test_running_machine_keeps_joints_battery_control_and_clock(self):
        self.open(workshop_bench_core._hoist_spec(20));old=self.live.session
        control=old.state['machines']['controls'][0]['id']
        old.send(op='operate',control=control,sender='install-test',seq=1,power=True,direction=1,setting=.4)
        old.send(op='step',dt=1/120,n=12)
        before=self.snap();p=self.preview(position=(4,0));self.do_commit(p)
        install._preserved(before,self.snap(),p['root_body'])
        self.assertGreater(before['t_s'],0);self.assertTrue(before['joints']);self.assertTrue(before['energy_stores'])

    def test_completed_heating_keeps_stored_heat_without_reset(self):
        old=self.live.session
        old.send(op='heat',target='marker stone',power_w=100,seconds=.1)
        old.send(op='step',dt=1/120,n=24)
        before=self.snap();self.assertTrue(before['heat']['lumps'])
        p=self.preview();self.do_commit(p)
        install._preserved(before,self.snap(),p['root_body'])
        self.assertEqual(before['heat']['lumps'][0], self.snap()['heat']['lumps'][0])

    def test_held_object_keeps_its_pose_and_hand_state(self):
        spec=world_room.yard();spec['bodies'].append({'name':'held','shape':'box','material':'iron','size_mm':[80]*3,'center_mm':[0,40,0]})
        self.open(spec);old=self.live.session
        old.send(op='grab',name='held');old.send(op='move',to=[0,1,0]);old.send(op='step',dt=1/120,n=12)
        before=self.snap();self.assertEqual('held',before['hand']['holding'])
        p=self.preview();self.do_commit(p);install._preserved(before,self.snap(),p['root_body'])
        self.assertEqual(before['hand'],self.snap()['hand'])

    def test_scheduled_heater_is_refused_even_before_first_step(self):
        old=self.live.session;old.send(op='heat',target='marker stone',power_w=100,seconds=1)
        raw,_=self.live.snapshot();self.assertEqual(1,raw['carry_readiness']['pending_heaters'])
        with self.assertRaisesRegex(ValueError,'pending heaters'):self.preview()
        self.assertIs(old,self.live.session)
        self.assertEqual(raw,self.live.snapshot()[0])

    def test_physical_curve_and_requested_position_use_whole_grid_translation(self):
        candidate={'kind':'table','component_overrides':{'leg-1':{'skin':{'profile':'curve','bend_m':.04,'physical':True}}}}
        p=self.preview(candidate=candidate,position=(3.011,.011))
        self.assertEqual([75,0],p['placement_grid'][::2]);self.assertEqual(0,p['bounds_m'][0][1]);self.do_commit(p)
        self.assertTrue(p['engine_grid_verified'])

if __name__=='__main__':
    if not ENGINE and os.environ.get('BANJO_BROWSER_TESTS')=='required':raise RuntimeError('Native installation checks require an engine')
    unittest.main()
