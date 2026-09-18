"""Bounded live precise-rigid admission and real native placement/persistence."""
from __future__ import annotations
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'playground')]
import fracture_lab, inventory, live_session, precise_rigid, room_store, world_room, workshop_install as install
from mcp import workshop_components, workshop_rigid
ENGINE = Path(os.environ['BANJO_LIVE_ENGINE']).resolve() if os.environ.get('BANJO_LIVE_ENGINE') else None


def candidate(material='oak'):
    c = {'kind':'table','design_id':'thin-live-table', 'parameters':{'material':material,'top_thickness_m':.005,'leg_section_m':.015}}
    d, _ = workshop_components.design_from_spec(c)
    c['component_overrides'] = {p.name:{'mechanics':{'model':'rigid'}} for p in d.parts}
    return c


def artifact(material='oak'):
    d,o = workshop_components.design_from_spec(candidate(material))
    return workshop_rigid.compile_rigid(d,o)


def box(name='box', pos=(0,.5,0), material='iron'):
    return {'name':name,'material':material,'position_m':list(pos),
            'parts':[{'dimensions_m':[.02,.02,.02],'center_local_m':[0,0,0]}]}


class PreciseAdmission(unittest.TestCase):
    def test_thin_geometry_and_mass_frame_are_independent_of_room_grid(self):
        for material in ('glass','oak','iron'):
            a=artifact(material);b,_=precise_rigid.placement(a,'thin',[3.123,0])
            for h in (.04,.02):
                spec=world_room.yard();spec['cell_m']=h
                out=precise_rigid.normalise([b],spec)[0]
                self.assertEqual(b,out)
                self.assertEqual(5,len(out['parts']))
                self.assertEqual(.005,out['parts'][0]['dimensions_m'][1])
                self.assertAlmostEqual(3.123,out['position_m'][0])
                lo,hi=precise_rigid.bounds(out['parts'],out['position_m'],out['orientation_wxyz'])
                self.assertAlmostEqual(.002,lo[1]);self.assertAlmostEqual(.762,hi[1])

    def test_dynamic_lattice_and_advanced_physics_are_refused_not_downgraded(self):
        spec=world_room.yard();spec['bodies'][0]['anchored']=False
        with self.assertRaisesRegex(ValueError,'anchored scenery'):precise_rigid.normalise([box()],spec)
        for key in ('terrain','thermo','joints','machines','water','actions'):
            spec=world_room.yard();spec[key]=[{}]
            with self.subTest(key=key), self.assertRaises(ValueError):precise_rigid.normalise([box()],spec)

    def test_bad_geometry_and_unknown_fields_never_fall_back(self):
        cases=[]
        for change in ({'mass_kg':1}, {'material':'unknown'}, {'position_m':[True,0,0]}, {'orientation_wxyz':[2,0,0,0]}):
            cases.append({**box(),**change})
        for d in ([0,1,1],[float('nan'),1,1],[.0001,.02,.02]):
            b=box();b['parts'][0]['dimensions_m']=d;cases.append(b)
        b=box();b['parts'][0]['center_local_m']=[.1,0,0];cases.append(b)
        b=box();b['parts']*=2;cases.append(b)
        for b in cases:
            with self.subTest(body=b),self.assertRaises(ValueError):precise_rigid.normalise([b],world_room.yard())
        with self.assertRaises(ValueError):precise_rigid.normalise([box(),box()],world_room.yard())

    def test_budget_and_disconnected_components_are_refused(self):
        with self.assertRaises(ValueError):precise_rigid.normalise([box(str(i)) for i in range(33)],world_room.yard())
        b=box();b['parts']=[{'dimensions_m':[.02]*3,'center_local_m':[x,0,0]} for x in (-.1,.1)]
        with self.assertRaisesRegex(ValueError,'face connected'):precise_rigid.normalise([b],world_room.yard())

    def test_validation_and_scene_document_preserve_precise_geometry(self):
        spec=world_room.yard();spec['precise_rigid_bodies']=[box()]
        normalized=fracture_lab.validate(spec)
        doc=fracture_lab.scene_document(normalized)
        self.assertEqual(normalized['precise_rigid_bodies'],doc['precise_rigid_bodies'])
        self.assertEqual([.02]*3,doc['precise_rigid_bodies'][0]['parts'][0]['dimensions_m'])


@unittest.skipUnless(ENGINE and ENGINE.is_file(), 'BANJO_LIVE_ENGINE is required')
class NativePreciseInstallation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.live=live_session.Live();self.addCleanup(self.live.shutdown)
        self.room=world_room.Room('yard');self.room.inventory=inventory.Inventory()
        self.app=SimpleNamespace(live=self.live,live_holder='world',room=self.room,engine_path=ENGINE,
            runs_path=root/'runs',store=room_store.RoomStore(root/'rooms'))
        self.live.open(self.app,{'spec':self.room.spec})
    def snap(self):return install._snapshot(self.live)
    def preview(self, material='oak', x=3.123):
        ctx=install.context(self.app,{})
        return install.preview(self.app,{'session':ctx['session'],'scene':'yard','mode':'authoring',
            'position_m':[x,0],'candidate':candidate(material)})
    def request(self,p,key='rigid-install-1'):
        return {'scene':'yard','session':p['session'],'preview_id':p['preview_id'],'request_id':key}
    def commit(self,p,key='rigid-install-1'):return install.commit(self.app,self.request(p,key))

    def test_three_material_installation_uses_actual_native_mass_and_exact_shapes(self):
        for i,material in enumerate(('glass','oak','iron')):
            before=self.snap();old=self.live.session;record=self.room.inventory.record()
            p=self.preview(material,3.123+i*2);self.assertEqual(before,self.snap());self.assertIs(old,self.live.session)
            a=artifact(material);self.assertEqual(0,p['cells']);self.assertEqual(5,p['collision_boxes'])
            result=self.commit(p,f'rigid-install-{i}');saved=self.snap()
            install._preserved(before,saved,p['root_body'])
            b=next(b for b in saved['bodies'] if b['name']==p['root_body'])
            self.assertEqual('',b['nodes_b64']);self.assertEqual('',b['offsets_b64'])
            self.assertAlmostEqual(a['mass_kg'],b['precise_mass_kg'],delta=a['mass_kg']*5e-6)
            self.assertEqual(record,self.room.inventory.record());self.assertTrue(old._closed)
            state=self.live.session.send(op='poses')
            body=next(b for b in state['bodies'] if b['name']==p['root_body'])
            self.assertEqual('precise-rigid-v1',body['mechanical_model']);self.assertEqual(5,len(body['rigid_boxes_local']))
            self.assertEqual(.005,body['rigid_boxes_local'][0]['dimensions_m'][1]);self.assertFalse(body['internal_failure_supported'])
            self.assertTrue(result['native_precise_geometry_verified']);self.assertFalse(result['strength_certified'])

    def test_motion_and_persistent_restart_keep_source_pose_and_unique_receipt(self):
        p=self.preview();req=self.request(p);first=install.commit(self.app,req)
        self.live.session.send(op='step',dt=1/240,n=240)
        current=self.snap();b=next(b for b in current['bodies'] if b['name']==p['root_body'])
        self.assertLess(b['pose']['com_m'][1],self.room.spec['precise_rigid_bodies'][0]['position_m'][1])
        self.room.world_record=current;self.app.store.save(self.room)
        self.live.shutdown();self.app.room=self.room=self.app.store.load('yard')
        opened=self.live.open(self.app,{'spec':self.room.spec,'snapshot':self.room.world_record})
        self.assertEqual('whole',opened['restored']['tier'])
        self.assertEqual(current,self.snap())
        replay=install.commit(self.app,req);self.assertTrue(replay['replayed']);self.assertEqual(first['root_body'],replay['root_body'])
        self.assertEqual(1,len(self.room.spec['precise_rigid_bodies']))

    def test_second_installation_keeps_moving_precise_body_and_elapsed_time(self):
        p=self.preview();self.commit(p)
        self.live.session.send(op='step',dt=1/240,n=5)
        before=self.snap();p2=self.preview(x=6.321);self.commit(p2,'rigid-install-2')
        install._preserved(before,self.snap(),p2['root_body'])

    def test_rotating_moving_compound_restarts_and_carries_without_pose_reset(self):
        a=artifact();b,_=precise_rigid.placement(a,'rotating',[0,0]);b['position_m'][1]+=3
        b['velocity_m_s']=[.15,0,.07];b['spin_rad_s']=[0,1.5,0]
        spec=world_room.yard();spec['precise_rigid_bodies']=[b];self.room.spec=spec
        self.live.open(self.app,{'spec':spec});self.live.session.send(op='step',dt=1/240,n=24)
        before=self.snap();body=next(x for x in before['bodies'] if x['name']=='rotating')
        self.assertNotEqual([1,0,0,0],body['pose']['q_wxyz'])
        self.assertNotEqual([0,0,0],body['pose']['w_rad_s'])
        p=self.preview(x=6);self.commit(p);install._preserved(before,self.snap(),p['root_body'])
        before=self.snap();self.live.shutdown();self.live.open(self.app,{'spec':self.room.spec,'snapshot':before})
        self.assertEqual(before,self.snap())

    def test_collision_stale_preview_and_disk_failure_do_not_change_world(self):
        p=self.preview();self.commit(p)
        before=self.snap();old=self.live.session
        with self.assertRaisesRegex(ValueError,'overlaps'):self.preview()
        self.assertEqual(before,self.snap());self.assertIs(old,self.live.session)
        p2=self.preview(x=6)
        with patch.object(self.app.store,'save',side_effect=OSError('disk full')),self.assertRaises(OSError):self.commit(p2,'rigid-install-2')
        self.assertEqual(before,self.snap());self.assertIs(old,self.live.session)
        self.live.session.send(op='step',dt=1/240,n=1)
        before=self.snap()
        with self.assertRaisesRegex(ValueError,'changed after preview'):self.commit(p2,'rigid-install-2')
        self.assertEqual(before,self.snap())

    def test_dynamic_lattice_and_old_binary_are_refused_before_installation(self):
        original=self.snap()
        old=deepcopy(original);old['carry_readiness'].pop('precise_rigid_version')
        with patch.object(install,'_snapshot',return_value=old),self.assertRaisesRegex(ValueError,'Rebuild'):self.preview()
        self.assertEqual(original,self.snap())
        spec=world_room.yard();spec['bodies'].append({'name':'dynamic','shape':'box','material':'oak','size_mm':[80]*3,'center_mm':[0,100,0]})
        self.room.spec=spec;self.live.open(self.app,{'spec':spec});before=self.snap()
        with self.assertRaisesRegex(ValueError,'anchored scenery'):self.preview()
        self.assertEqual(before,self.snap())

    def test_native_picking_sees_the_thin_top_and_the_open_space_between_legs(self):
        p=self.preview();self.commit(p)
        top=self.live.session.send(op='pick', **{'from':[3.123,1,0],'dir':[0,-1,0],'max_m':1})
        self.assertTrue(top['hit']);self.assertEqual(p['root_body'],top['name'])
        self.assertAlmostEqual(.762,top['point_m'][1],delta=1e-5)
        hole=self.live.session.send(op='pick', **{'from':[3.123,.3,-1],'dir':[0,0,1],'max_m':2})
        self.assertFalse(hole['hit'],hole)

    def test_small_precise_body_lands_on_actual_five_millimetre_tabletop(self):
        table,_=precise_rigid.placement(artifact(),'table',[0,0])
        spec=world_room.yard();spec['precise_rigid_bodies']=[table,box('cube',(0,1,0))]
        self.room.spec=spec;self.live.open(self.app,{'spec':spec})
        self.live.session.send(op='step',dt=1/240,n=240)
        bodies={b['name']:b for b in self.snap()['bodies']}
        self.assertAlmostEqual(.77,bodies['cube']['pose']['com_m'][1],delta=.001)
        self.assertEqual('',bodies['table']['nodes_b64'])

    def test_held_precise_body_and_hand_survive_installation_and_restart(self):
        p=self.preview();self.commit(p)
        self.live.session.send(op='grab',name=p['root_body'])
        self.live.session.send(op='move',to=[3,1.5,0])
        self.live.session.send(op='step',dt=1/240,n=12)
        before=self.snap();self.assertEqual(p['root_body'],before['hand']['holding'])
        p2=self.preview(x=6);self.commit(p2,'rigid-install-2')
        install._preserved(before,self.snap(),p2['root_body'])
        current=self.snap();self.live.shutdown()
        self.live.open(self.app,{'spec':self.room.spec,'snapshot':current})
        self.assertEqual(current,self.snap())

    def test_unsupported_failure_heat_and_inventory_operations_are_explicit(self):
        p=self.preview();self.commit(p);before=self.snap()
        for op,kwargs in [('fracture',{'name':p['root_body']}),('park',{'name':p['root_body']}),
                          ('heat',{'target':p['root_body'],'power_w':100,'seconds':1})]:
            with self.subTest(op=op),self.assertRaisesRegex(live_session.LiveError,'precise-rigid|precise rigid'):
                self.live.session.send(op=op,**kwargs)
            self.assertEqual(before,self.snap())

    def test_native_geometry_validator_independently_rejects_bad_raw_scenes(self):
        spec=world_room.yard();spec['precise_rigid_bodies']=[box()]
        doc=fracture_lab.scene_document(fracture_lab.validate(spec))
        for index,change in enumerate(('tiny','overlap','unknown','off-com','disconnected','bad-quaternion')):
            bad=deepcopy(doc);b=bad['precise_rigid_bodies'][0]
            if change=='tiny':b['parts'][0]['dimensions_m'][0]=.0001
            if change=='overlap':b['parts']*=2
            if change=='unknown':b['mass_kg']=1
            if change=='off-com':b['parts'][0]['center_local_m'][0]=.1
            if change=='disconnected':b['parts']=[{'dimensions_m':[.02]*3,'center_local_m':[x,0,0]} for x in (-.1,.1)]
            if change=='bad-quaternion':b['orientation_wxyz']=[0,0,0,0]
            path=Path(self.tmp.name)/f'bad-{index}.json';path.write_text(json.dumps(bad))
            result=subprocess.run([str(ENGINE),'--scene',str(path),'--cell','.04'],input='',text=True,capture_output=True,timeout=10)
            self.assertNotEqual(0,result.returncode,(change,result.stdout))
            self.assertIn('precise',result.stderr.lower()+result.stdout.lower())

    def test_live_native_mass_and_inertia_agree_with_independent_initial_energy(self):
        # At t=0 there is no contact/solver work. An independent analytic oracle
        # checks the ACTUAL native mass/inertia, not duplicated descriptive JSON.
        for material in ('glass','oak','iron'):
            a=artifact(material);body,_=precise_rigid.placement(a,'table',[0,0])
            body['position_m'][1]+=3;body['velocity_m_s']=[.5,0,0];body['spin_rad_s']=[0,1.5,0]
            spec=world_room.yard();spec['precise_rigid_bodies']=[body]
            self.room.spec=spec;self.live.open(self.app,{'spec':spec})
            energy=self.live.session.send(op='thermo')['thermo']['ledger']['mechanical_j']
            expected=a['mass_kg']*(.5*.5**2+9.81*body['position_m'][1])+.5*a['inertia_kg_m2'][1][1]*1.5**2
            self.assertAlmostEqual(expected,energy,delta=abs(expected)*5e-6)

    def test_changed_saved_precise_definition_never_silently_resets_to_source(self):
        p=self.preview();self.commit(p);saved=self.snap();bad=deepcopy(saved)
        target=next(b for b in bad['bodies'] if b['name']==p['root_body'])
        target['precise_rigid_definition']['parts'][0]['dimensions_m'][1]=.006
        staging=live_session.Live();self.addCleanup(staging.shutdown)
        scratch=SimpleNamespace(engine_path=ENGINE,runs_path=Path(self.tmp.name)/'scratch',live_inprocess=False,on_live_reply=None)
        with self.assertRaises((ValueError,RuntimeError)):staging.open(scratch,{'spec':self.room.spec,'snapshot':bad})
        self.assertEqual(saved,self.snap())

if __name__=='__main__':
    if os.environ.get('BANJO_PRECISE_LIVE_TESTS')=='required' and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError('BANJO_LIVE_ENGINE must be built for required live precise-rigid tests')
    unittest.main()
