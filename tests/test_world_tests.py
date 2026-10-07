"""3D sandbox HTTP -> Rust owner -> actual native integration; no fake engine.

Qualifies transport, actual geometry, custody and honest response presentation.
Does not certify useful digging speed or the unconnected material-contact law.
"""
import base64
import functools
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]

def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

WORLD=module('sandbox',ROOT/'scripts/test-world.py')
LAB=module('lab',ROOT/'scripts/material-lab.py')

class TestWorldGateway(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native=Path(os.environ.get('BANJO_LIVE_ENGINE','missing-native'))
        runtime=Path(os.environ.get('BANJO_RUNTIME_ENGINE','missing-runtime'))
        if not native.is_file() or not runtime.is_file():
            raise AssertionError('Supply actual BANJO_LIVE_ENGINE and BANJO_RUNTIME_ENGINE; cannot skip')
        cls.manager=WORLD.WorldManager(native,runtime)
        cls.temp=tempfile.TemporaryDirectory()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(LAB.LabHandler,directory=cls.temp.name))
        cls.server.world_manager=cls.manager
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.manager.close();cls.thread.join(5);cls.temp.cleanup()

    def post(self,value,origin=None):
        request=urllib.request.Request(self.base+'/api/world',data=json.dumps(value).encode(),headers={
            'Content-Type':'application/json','Origin':origin or self.base})
        with urllib.request.urlopen(request,timeout=20) as response:return json.load(response)

    def create(self,family='pick',material='iron'):
        result=self.post({'action':'create','family':family,'material':material})
        session=result['session']
        self.addCleanup(lambda:self.post({'action':'close','session':session}))
        return result

    def act(self,session,action,**extra):
        return self.post({'session':session,'action':action,'id':uuid.uuid4().hex,**extra})

    def observe(self,session):return self.post({'session':session,'action':'observe'})

    def wait(self,session,predicate,seconds=6):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            self.act(session,'move',velocity=[0,0,0],heading=0)
            result=self.observe(session)
            if predicate(result):return result
            time.sleep(.14)
        self.fail('Native pending state did not close within the sandbox test budget')

    def test_ground_geometry_is_native_complete_private_and_readable_without_receipts(self):
        world=self.create();session=world['session']
        terrain=world['snapshot']['terrain'];grid=terrain['grid']
        self.assertEqual(grid['cell_m'],.1)
        self.assertEqual(len(base64.b64decode(terrain['heights_b64'])),grid['nx']*grid['nz']*4)
        self.assertEqual(set(terrain),{'grid','surface','heights_b64','ground_b64','runs_b64','floor_m'})
        self.assertNotIn('player_hands',world['snapshot'])
        self.assertEqual(world['clock']['dt_s'],1/240)
        for _ in range(20):world=self.observe(session)
        self.assertEqual(self.manager.worlds[session].sequence,2,'Read polls must not allocate command receipts')
        self.assertGreater(world['clock']['simulation_s'],0)

    def test_pickup_drop_and_worlds_have_independent_actual_avatars_and_hands(self):
        a=self.create();b=self.create();first=a['session'];second=b['session']
        time.sleep(.3) # ordinary pickup after the item has settled on its stand
        picked=self.act(first,'pickup',instance='handle')
        self.assertEqual(picked['outcome']['status'],'pending')
        held=self.wait(first,lambda r:any(e['status']=='applied' for e in r['events']))
        self.assertEqual(held['snapshot']['own_hand']['holding'],'handle')
        self.assertEqual(self.observe(second)['snapshot']['own_hand']['holding'],'')
        before=held['snapshot']['native_players']['player']['position_m']
        for _ in range(4):
            self.act(first,'move',velocity=[.5,0,0],heading=math.pi/2);time.sleep(.14)
        after=self.observe(first)['snapshot']['native_players']['player']['position_m']
        self.assertGreater(math.dist(before,after),.1)
        dropped=self.act(first,'drop')
        self.assertEqual(dropped['snapshot']['own_hand']['holding'],'')
        self.assertTrue(any(b['name']=='handle' for b in dropped['snapshot']['bodies']))
        self.assertLess(abs(self.observe(second)['snapshot']['native_players']['player']['position_m'][0]),.01)

    def test_native_preview_and_completion_report_actual_yield_or_refusal(self):
        world=self.create();session=world['session']
        self.act(session,'pickup',instance='handle')
        self.wait(session,lambda r:any(e['status']=='applied' for e in r['events']))
        target=[.65,.75,.65]
        preview=self.post({'action':'preview','session':session,'target':target})['preview']
        self.assertTrue(preview['admitted']);self.assertFalse(preview['measured_yield'])
        self.assertTrue(preview['entry_clearance']['clear'])
        initial=self.observe(session)['snapshot']['terrain']['heights_b64']
        request={'action':'use','session':session,'id':uuid.uuid4().hex,'target':target}
        begun=self.post(request);self.assertEqual(begun['outcome']['status'],'pending')
        done=self.wait(session,lambda r:any(e.get('tool_use_result') is not None for e in r['events']),seconds=10)
        event=next(e for e in done['events'] if e.get('tool_use_result') is not None)
        actual=event['tool_use_result']
        self.assertFalse(actual['active']);self.assertFalse(actual['contact_pending'])
        self.assertEqual(actual['target_m'],target)
        self.assertTrue(all(v>=0 for v in actual['loosened_m3'].values()))
        # A controller refusal is a real failed test stroke, never fabricated
        # visible progress. Deeper/sustained use has a separate failing gate.
        if sum(actual['loosened_m3'].values())>0:
            self.assertNotEqual(initial,done['snapshot']['terrain']['heights_b64'])
        else:
            self.assertEqual(event['status'],'rejected');self.assertIsNotNone(event['reason'])
        retry=self.post(request)
        self.assertEqual(retry['outcome']['command_id'],begun['outcome']['command_id'])
        self.assertEqual(len([e for e in retry['events'] if e.get('tool_use_result')]),1)
        print('SANDBOX_STROKE_EVIDENCE '+json.dumps({'family':'pick','material':'iron','native':world['native'],
            'dt_s':world['clock']['dt_s'],'terrain_cell_m':.1,'tool_cell_m':.02,'result':actual},sort_keys=True))

    def test_matched_tool_families_have_real_geometry_material_mass_and_generic_pickup(self):
        masses={}
        for material in ('glass','oak','iron'):
            for family,width in WORLD.FAMILIES.items():
                with self.subTest(material=material,family=family):
                    world=self.post({'action':'create','family':family,'material':material});session=world['session']
                    try:
                        head=next(b for b in world['snapshot']['bodies'] if b['name']=='head')
                        self.assertEqual(head['dimensions_m'],[width,.08,.04]);self.assertEqual(head['material'],material)
                        self.assertEqual(world['clock']['dt_s'],1/240)
                        masses[material,family]=head['mass_kg']
                        self.act(session,'pickup',instance='handle')
                        self.wait(session,lambda r:r['snapshot']['own_hand']['holding']=='handle' and bool(r['events']))
                    finally:self.post({'action':'close','session':session})
        for family in WORLD.FAMILIES:
            self.assertLess(masses['oak',family],masses['glass',family]);self.assertLess(masses['glass',family],masses['iron',family])
        print('SANDBOX_MASS_EVIDENCE '+json.dumps({f'{m}/{f}':v for (m,f),v in masses.items()},sort_keys=True))

    def granular(self,family='pick',material='iron',ground='concrete'):
        world=self.post({'action':'create','family':family,'material':material,
                         'model':'rigid-grains','ground_material':ground})
        return world

    def physical_hit(self,world,target):
        session=world['session']
        self.act(session,'pickup',instance='handle')
        held=self.wait(session,lambda r:r['snapshot']['own_hand']['holding']=='handle' and bool(r['events']))
        preview=self.post({'action':'preview-hit','session':session,'target':target})['preview']
        self.assertTrue(preview['admitted'],preview)
        request={'action':'hit','session':session,'id':uuid.uuid4().hex,'target':target}
        begun=self.post(request)
        self.assertEqual(begun['outcome']['status'],'applied') # actuator intent, not completion
        initial=begun['snapshot']['own_physical_hit']['started_s']
        done=self.wait(session,lambda r:r['snapshot']['own_physical_hit'] and not r['snapshot']['own_physical_hit']['active'],seconds=12)
        hit=done['snapshot']['own_physical_hit']
        self.assertEqual(hit['target'],preview['target']);self.assertTrue(hit['contacted'],{'family':world['family'],'hit':hit})
        self.assertTrue(math.isfinite(hit['hand_work_j']))
        self.assertGreater(hit['ended_s'],hit['started_s'])
        self.assertEqual(self.post(request)['snapshot']['own_physical_hit']['started_s'],initial)
        self.assertEqual(done['snapshot']['own_hand']['holding'],'handle')
        return done

    def test_intact_slab_swing_is_native_and_does_not_invent_fracture(self):
        records=[]
        for material in ('glass','oak','iron'):
            world=self.post({'action':'create','family':'pick','material':'iron',
                             'model':'rigid-slab','ground_material':material})
            session=world['session']
            try:
                slab=next(b for b in world['snapshot']['bodies'] if b['name']=='ground-slab')
                self.assertEqual(slab['mechanical_model'],'precise-rigid-v1')
                self.assertEqual(slab['dimensions_m'],[1.2,.1,1.2])
                self.assertFalse(any(b['name'].startswith('grain-') for b in world['snapshot']['bodies']))
                before={b['name']:b['mass_kg'] for b in world['snapshot']['bodies']}
                done=self.physical_hit(world,[.3,.12,.3])
                hit=done['snapshot']['own_physical_hit']
                self.assertGreater(hit['contact_speed_m_s'],.1,'no measurable closing impact')
                self.assertEqual(hit['contact_part'],'head','the handle, not the working head, struck the slab')
                self.assertGreater(hit['swing_rotation_rad'],.3,'translated without a real rotating swing')
                self.assertGreater(hit['peak_tip_speed_m_s'],1,'the tool never developed impact motion')
                self.assertFalse(hit['intrinsic_fracture_supported'])
                self.assertEqual(hit['phase'],'ended')
                after={b['name']:b['mass_kg'] for b in done['snapshot']['bodies']}
                self.assertEqual(before,after,'rigid slab contact fabricated fragments or removed mass')
                records.append({'material':material,'mass_kg':slab['mass_kg'],
                    'dt_s':done['clock']['dt_s'],'hit':hit,'mass_residual_kg':sum(after.values())-sum(before.values())})
            finally:self.post({'action':'close','session':session})
        print('INTACT_SLAB_SWING_EVIDENCE '+json.dumps(records,sort_keys=True))

    def test_repeated_clear_slab_swings_use_all_configured_tool_heads(self):
        for family in WORLD.FAMILIES:
            world=self.post({'action':'create','family':family,'material':'iron',
                             'model':'rigid-slab','ground_material':'glass'})
            session=world['session']
            try:
                self.act(session,'pickup',instance='head')
                self.wait(session,lambda r:r['snapshot']['own_hand']['holding']=='head' and bool(r['events']))
                for attempt in range(2):
                    self.act(session,'hit',target=[.3,.12,.3])
                    done=self.wait(session,lambda r:r['snapshot']['own_physical_hit'] and not r['snapshot']['own_physical_hit']['active'],seconds=12)
                    hit=done['snapshot']['own_physical_hit']
                    self.assertTrue(hit['contacted'],{'family':family,'attempt':attempt,'hit':hit})
                    self.assertEqual(hit['contact_part'],'head')
                    self.assertGreater(hit['swing_rotation_rad'],.3)
                    self.assertEqual(done['snapshot']['own_hand']['holding'],'head')
                    self.assertEqual(set(done['snapshot']['own_hand']['held_parts']),{'head','handle'})
                    print('PAIRED_SLAB_SWING '+json.dumps({'family':family,'attempt':attempt,'hit':hit},sort_keys=True))
            finally:self.post({'action':'close','session':session})

    def test_rigid_grains_use_native_mass_contacts_and_preserve_all_material(self):
        masses={};records=[]
        for material in ('glass','oak','iron'):
            world=self.granular(ground=material);session=world['session']
            try:
                self.assertNotIn('terrain',world['snapshot'])
                grains=[b for b in world['snapshot']['bodies'] if b['name'].startswith('grain-')]
                self.assertEqual(len(grains),200)
                self.assertTrue(all(b['mechanical_model']=='precise-rigid-v1' for b in grains))
                masses[material]=grains[0]['mass_kg']
                before={b['name']:b['mass_kg'] for b in world['snapshot']['bodies']}
                done=self.physical_hit(world,[.42,.22,.54])
                after={b['name']:b['mass_kg'] for b in done['snapshot']['bodies']}
                self.assertEqual(before.keys(),after.keys())
                self.assertAlmostEqual(sum(before.values()),sum(after.values()),places=6)
                self.assertTrue(all(e.get('tool_use_result') is None for e in done['events']))
                records.append({'material':material,'grain_kg':masses[material],'dt_s':done['clock']['dt_s'],
                    'grain_m':.1,'packing_spacing_m':.12,'mass_residual_kg':sum(after.values())-sum(before.values()),
                    'hit':done['snapshot']['own_physical_hit'],'native':world['native']})
            finally:self.post({'action':'close','session':session})
        self.assertLess(masses['oak'],masses['glass']);self.assertLess(masses['glass'],masses['iron'])
        print('RIGID_GRAIN_EVIDENCE '+json.dumps(records,sort_keys=True))

    def test_all_configured_families_can_hit_grains_and_solid_targets_use_the_same_path(self):
        records=[]
        for family in WORLD.FAMILIES:
            world=self.granular(family=family)
            try:
                done=self.physical_hit(world,[.42,.22,.54])
                records.append({'family':family,'hit':done['snapshot']['own_physical_hit']})
            finally:self.post({'action':'close','session':world['session']})
        for target in ([-.42,.34,.42],[-.42,.34,0],[.65,.53,.85]):
            world=self.granular()
            try:
                done=self.physical_hit(world,target)
                records.append({'family':'pick','hit':done['snapshot']['own_physical_hit']})
            finally:self.post({'action':'close','session':world['session']})
        print('PHYSICAL_TARGET_EVIDENCE '+json.dumps(records,sort_keys=True))

    def test_origin_session_allowlist_limits_and_retry_cannot_grant_authority(self):
        with self.assertRaises(urllib.error.HTTPError) as refused:
            self.post({'action':'create','family':'pick','material':'iron'},'http://untrusted.invalid')
        self.assertEqual(refused.exception.code,403)
        world=self.create();session=world['session']
        invalid=[{'action':'observe','session':session,'actor':'someone-else'},
                 {'action':'step','session':session,'dt':100},
                 {'action':'pickup','session':session,'id':uuid.uuid4().hex,'instance':'tool-stand'},
                 {'action':'move','session':session,'id':uuid.uuid4().hex,'velocity':[0,1,0],'heading':0},
                 {'action':'create','family':'bow','material':'iron'}]
        for value in invalid:
            with self.assertRaises(urllib.error.HTTPError) as refused:self.post(value)
            self.assertEqual(refused.exception.code,400)
        request={'action':'move','session':session,'id':uuid.uuid4().hex,'velocity':[0,0,0],'heading':0}
        original=self.post(request);retry=self.post(request)
        self.assertEqual(original['outcome'],retry['outcome'])
        with self.assertRaises(urllib.error.HTTPError):self.post(dict(request,heading=1))
        other=self.create()
        with self.assertRaises(urllib.error.HTTPError):self.post({'action':'create','family':'pick','material':'iron'})
        self.assertNotEqual(session,other['session'])

    def test_expired_and_exhausted_sessions_report_recovery_and_can_restart(self):
        world=self.granular();session=world['session']
        # Host lease clock only; native physical time/geometry are unchanged.
        self.manager.worlds[session].last_seen=time.monotonic()-91
        fresh=self.granular();new_session=fresh['session']
        try:
            with self.assertRaises(urllib.error.HTTPError) as refused:self.observe(session)
            self.assertEqual(refused.exception.code,409)
            self.assertEqual(json.load(refused.exception)['code'],'expired')
            self.assertEqual(self.post({'action':'close','session':session}),{'closed':True})
            self.assertEqual(self.post({'action':'close','session':session}),{'closed':True})
            native_world=self.manager.worlds[new_session]
            native_world.receipts.update({f'{i:032x}':({}, {}) for i in range(4000)})
            with self.assertRaises(urllib.error.HTTPError) as refused:
                self.act(new_session,'pickup',instance='handle')
            self.assertEqual(refused.exception.code,409)
            self.assertEqual(json.load(refused.exception)['code'],'input_budget')
            self.assertEqual(self.observe(new_session)['snapshot']['own_hand']['holding'],'')
        finally:self.post({'action':'close','session':new_session})

    def test_clicked_component_acquires_the_whole_native_tool_for_each_family(self):
        for family in WORLD.FAMILIES:
            world=self.granular(family=family);session=world['session']
            try:
                outcome=self.act(session,'pickup',instance='head')['outcome']
                self.assertTrue(any(j['attached'] and {j['a'],j['b']}=={'head','handle'}
                                    for j in world['snapshot']['joints']))
                self.assertTrue(any(p['body']=='head' and p['grip_body']=='handle'
                                    for p in world['snapshot']['tool_points']))
                self.assertEqual(outcome['status'],'pending',outcome)
                held=self.wait(session,lambda r:any(e['status']=='applied' for e in r['events']))
                self.assertEqual(held['snapshot']['own_hand']['holding'],'head')
                self.assertEqual(set(held['snapshot']['own_hand']['held_parts']),{'head','handle'})
                def recovered(r):
                    w,x,y,z=r['snapshot']['native_players']['player']['orientation_wxyz']
                    self.assertGreater(1-2*(x*x+z*z),math.cos(.6),'Strike knocked the native player into fallen posture')
                    return r['snapshot']['own_physical_hit'] and not r['snapshot']['own_physical_hit']['active']
                for attempt in range(2):
                    preview=self.post({'action':'preview-hit','session':session,'target':[.42,.22,.54]})['preview']
                    self.assertTrue(preview['admitted'],preview)
                    self.act(session,'hit',target=[.42,.22,.54])
                    done=self.wait(session,recovered,seconds=12)
                    hit=done['snapshot']['own_physical_hit']
                    if not hit['contacted']:
                        # A wide intact head can meet surrounding grains over
                        # the second, lower target. Do not demand penetration
                        # of rigid matter or count neighbour motion as a hit.
                        self.assertEqual(hit['reason'],'target_blocked',{'family':family,'attempt':attempt,'hit':hit})
                        self.assertTrue(hit['obstruction'])
                        self.assertGreater(hit['obstruction_speed_m_s'],.01)
                    print('PAIRED_GRAIN_SWING '+json.dumps({'family':family,'attempt':attempt,'hit':hit},sort_keys=True))
                    self.assertEqual(done['snapshot']['own_hand']['holding'],'head')
                self.assertEqual(self.act(session,'drop')['snapshot']['own_hand']['holding'],'')
            finally:self.post({'action':'close','session':session})

    def test_matched_pickup_has_stable_native_stance_beside_the_sample(self):
        for material in ('glass','oak','iron'):
            world=self.granular(material=material);session=world['session']
            try:
                self.act(session,'pickup',instance='handle')
                self.wait(session,lambda r:any(e['status']=='applied' for e in r['events']))
                until=time.monotonic()+2
                peak_tilt=0;peak_drift=0
                while time.monotonic()<until:
                    self.act(session,'move',velocity=[0,0,0],heading=0)
                    observation=self.observe(session);player=observation['snapshot']['native_players']['player']
                    w,x,y,z=player['orientation_wxyz']
                    peak_tilt=max(peak_tilt,math.acos(max(-1,min(1,1-2*(x*x+z*z)))))
                    peak_drift=max(peak_drift,math.hypot(player['position_m'][0],player['position_m'][2]-.82))
                    self.assertEqual(observation['snapshot']['own_hand']['holding'],'handle')
                    time.sleep(.14)
                self.assertLess(peak_tilt,.15,'Pickup tipped the native avatar more than 8.6 degrees')
                self.assertLess(peak_drift,.05,'Stationary pickup moved the native avatar over 5 cm')
                print('PICKUP_STANCE_EVIDENCE '+json.dumps({'material':material,'dt_s':world['clock']['dt_s'],
                    'peak_tilt_rad':peak_tilt,'peak_drift_m':peak_drift,'native':world['native']}))
            finally:self.post({'action':'close','session':session})

if __name__=='__main__':unittest.main()
