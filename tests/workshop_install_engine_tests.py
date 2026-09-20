"""Actual native carry, persistence and rollback tests for Workshop installation."""
from __future__ import annotations
from copy import deepcopy
import json
import itertools
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
import workshop_articulation
from mcp import workshop_components
ENGINE=Path(os.environ['BANJO_LIVE_ENGINE']).resolve() if os.environ.get('BANJO_LIVE_ENGINE') else None

@unittest.skipUnless(ENGINE and ENGINE.is_file(),'BANJO_LIVE_ENGINE is required')
class NativeInstallation(unittest.TestCase):
    def test_articulated_staging_preserves_old_motion_heat_and_constraints(self):
        sys.path.insert(0,str(ROOT/'tests'))
        from workshop_install_tests import articulated_candidate
        evidence=[]
        for material, (preactivated, output_k) in itertools.product(('glass','oak','iron'), ((False,293.15),(True,293.15),(False,330.))):
            design,overrides=workshop_components.design_from_spec(articulated_candidate(material))
            old=workshop_articulation.compile_design(design,overrides,root='old')
            for body in old['bodies']:
                body['center_mm'][0]-=3000
                body['anchored']=body['join']==old['component_to_body']['support']
                body['temperature_k']=350.
            for joint in old['joints']:joint['at_mm'][0]-=3000
            self.open({'algorithm':'lattice','cell_m':.04,'duration_s':1.,'bodies':old['bodies'],'joints':old['joints']})
            self.live.session.send(op='step',dt=1/240,n=24)
            before=self.snap()
            added=workshop_articulation.compile_design(design,overrides,root='new')
            for body in added['bodies']:
                body['anchored']=body['join']==added['component_to_body']['support']
            spec=deepcopy(self.room.spec)
            spec['bodies']+=added['bodies'];spec['joints']+=added['joints']
            roots={g['root_body'] for g in added['groups']}
            staged,saved=install._stage(self.app,self.live,self.live.session,spec,before,added,roots,[0,0,0])
            try:
                self.assertEqual(self.snap(),before)
                install._preserved(before,saved,roots,added_joints=added['joints'])
                self.assertEqual(len(saved['bodies']),4)
                self.assertEqual(len(saved['joints']),2)
                for field,value in [('axis_local_a',[0,1,0]),('a','old-g0'),('lower',0),('attached',False),('friction',1)]:
                    corrupt=deepcopy(saved);corrupt['joints'][-1][field]=value
                    with self.assertRaises(ValueError):install._preserved(before,corrupt,roots,added_joints=added['joints'])
                corrupt=deepcopy(saved);corrupt['joints'][-1]['point_local_a'][0]+=.01
                with self.assertRaisesRegex(ValueError,'attachment point'):install._preserved(before,corrupt,roots,added_joints=added['joints'])
                corrupt=deepcopy(saved);corrupt['joints'][0]['friction']=1
                with self.assertRaisesRegex(ValueError,'existing joints'):install._preserved(before,corrupt,roots,added_joints=added['joints'])
                corrupt=deepcopy(saved);corrupt['next']['joint']+=1
                with self.assertRaisesRegex(ValueError,'identifiers'):install._preserved(before,corrupt,roots,added_joints=added['joints'])
                corrupt=deepcopy(saved);corrupt['joints'][-1]['held']['upper']=0.
                with self.assertRaisesRegex(ValueError,'solver limits'):install._preserved(before,corrupt,roots,added_joints=added['joints'])
                outputs={g['root_body']:g['mass_kg'] for g in added['groups']}
                if preactivated:
                    staged.session.send(op='declare',json={'contents':[{'body':root,'temperature_k':293.15} for root in sorted(roots)]})
                    saved=install._snapshot(staged)
                transfers,saved=install._admit_fabricated_outputs(staged,saved,outputs,output_k)
                install._preserved(before,saved,roots,added_joints=added['joints'],thermal_transfer=transfers)
                self.assertEqual(len(transfers),2)
                if output_k==293.15:
                    self.assertTrue(all((t['replaced_kg']>0)==preactivated for t in transfers))
                else:
                    self.assertGreater(transfers[1]['replaced_kg'],0)
                self.assertAlmostEqual(sum(t['mass_kg'] for t in transfers),sum(outputs.values()),delta=sum(outputs.values())*1e-6)
                with self.assertRaisesRegex(ValueError,'explicit transfer'):
                    install._preserved(before,saved,roots,added_joints=added['joints'],thermal_transfer=transfers[:1])
                with self.assertRaisesRegex(ValueError,'Duplicate'):
                    install._preserved(before,saved,roots,added_joints=added['joints'],thermal_transfer=transfers+transfers[:1])
                corrupt_transfers=deepcopy(transfers);corrupt_transfers[0]['replaced_j']+=1.
                with self.assertRaisesRegex(ValueError,'ledger'):
                    install._preserved(before,saved,roots,added_joints=added['joints'],thermal_transfer=corrupt_transfers)
                for field in ('mass_kg','internal_energy_j'):
                    corrupt_transfers=deepcopy(transfers);corrupt_transfers[0][field]+=1.
                    with self.assertRaisesRegex(ValueError,'receipt'):
                        install._preserved(before,saved,roots,added_joints=added['joints'],thermal_transfer=corrupt_transfers)
                staged.open(self.app,{'spec':spec,'snapshot':saved})
                reopened=install._snapshot(staged)
                self.assertEqual(staged.session.state['restored']['tier'],'whole')
                install._preserved(saved,reopened,set())
                staged.session.send(op='step',dt=1/240,n=24)
                final=staged.session.send(op='poses')
                arm=next(b for b in final['bodies'] if b['name']==added['component_to_body']['arm'])
                self.assertLess(arm['position_m'][1],.999)
                self.assertEqual(len(install._snapshot(staged)['joints']),2)
                evidence.append({'material':material,'preactivated':preactivated,'output_temperature_k':output_k,'old_bodies_preserved':2,'added_bodies':2,
                                 'old_joints_preserved':1,'added_joints':1,'whole_restart':True,
                                 'thermal_transfers':transfers,
                                 'new_arm_y_m_after_0_1_s':arm['position_m'][1]})
            finally:staged.shutdown()
        self.native_evidence=evidence
        print('articulated staging:',json.dumps(evidence))

    def test_compiled_bearing_moves_under_gravity_without_fusing_parts(self):
        import sys
        sys.path.insert(0,str(ROOT/'tests'))
        from workshop_install_tests import articulated_candidate
        measurements=[]
        for material in ('glass','oak','iron'):
            design,overrides=workshop_components.design_from_spec(articulated_candidate(material))
            compiled=workshop_articulation.compile_design(design,overrides,root='bearing-trial')
            support=compiled['component_to_body']['support'];arm=compiled['component_to_body']['arm']
            for body in compiled['bodies']:
                body['anchored']=body['join']==support
            spec={'algorithm':'lattice','cell_m':.04,'duration_s':1.,'bodies':compiled['bodies'],
                  'joints':compiled['joints'],'interfaces':compiled['interfaces']}
            self.open(spec)
            before=self.snap()
            self.assertEqual(len(before['bodies']),2)
            for group in compiled['groups']:
                sparse.verify_engine_matter(before,group['matter'],group['root_body'])
            start={b['name']:b for b in self.live.session.state['bodies']}
            self.live.session.send(op='step',dt=1/240,n=24)
            state=self.live.session.send(op='poses')
            end={b['name']:b for b in state['bodies']}
            self.assertEqual(start[support]['position_m'],end[support]['position_m'])
            self.assertLess(end[arm]['position_m'][1],start[arm]['position_m'][1]-.001)
            self.assertNotEqual(end[arm]['orientation_wxyz'],start[arm]['orientation_wxyz'])
            import math
            pivot=[v/1000 for v in compiled['joints'][0]['at_mm']]
            self.assertAlmostEqual(math.dist(start[arm]['position_m'],pivot),
                                   math.dist(end[arm]['position_m'],pivot),delta=.0005)
            moving=next(g for g in compiled['groups'] if g['root_body']==arm)
            self.assertAlmostEqual(end[arm]['mass_kg'],moving['mass_kg'],delta=moving['mass_kg']*1e-6)
            self.assertEqual(len(self.snap()['joints']),1)
            measurements.append({'material':material,'mass_kg':end[arm]['mass_kg'],
                                 'drop_m':start[arm]['position_m'][1]-end[arm]['position_m'][1]})
            # Removing the connection changes the motion: the arm now falls
            # rather than tracing the bearing's circle.
            self.open({**spec,'joints':[]})
            self.live.session.send(op='step',dt=1/240,n=24)
            free=next(b for b in self.live.session.send(op='poses')['bodies'] if b['name']==arm)
            self.assertLess(free['position_m'][1],end[arm]['position_m'][1]-.01)
            measurements[-1]['unconnected_drop_m']=start[arm]['position_m'][1]-free['position_m'][1]
            measurements[-1]['pivot_radius_error_m']=abs(math.dist(start[arm]['position_m'],pivot)-math.dist(end[arm]['position_m'],pivot))
        self.assertLess(max(r['drop_m'] for r in measurements)-min(r['drop_m'] for r in measurements),.001)
        self.native_evidence=measurements
        print('compiled bearing:',json.dumps(measurements))

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


    def test_native_terrain_install_keeps_excavation_and_rejects_changed_ground(self):
        import server
        self.room=world_room.Room("world");self.app.room=self.room
        self.open()
        command={"op":"dig","from":[13,-7],"to":[13,-7],"width_m":.5,"depth_m":.05}
        answer=self.live.act({"session":self.live.session.id,**command})
        server.remember_ground(self.app,command,answer)
        ground=install._terrain_state(self.live.session)
        self.assertGreater(ground["carried"]["soil_kg"]+ground["carried"]["sand_kg"],0)
        before=self.snap()
        from fabrication_tests import candidate
        request={"scene":"world","session":self.live.session.id,"mode":"authoring",
                 "candidate":candidate(),"position_m":[13,-7]}
        self.assertGreater(ground["material_accounting"]["unsettled_columns"],0)
        self.assertEqual(self.room.spec["terrain"],self.live.session.spec["terrain"])
        # Install immediately: the frontier and old collision patches must
        # survive, rather than replaying the dig until the terrain is at rest.
        preview=install.preview(self.app,request)
        self.assertEqual(before,self.snap())
        result=install.commit(self.app,{"scene":"world","session":self.live.session.id,
                              "preview_id":preview["preview_id"],"request_id":"terrain-author-0001"})
        install._preserved(before,self.snap(),result["root_body"])
        self.assertEqual(ground,install._terrain_state(self.live.session))
        # A changed ground query from the staged engine must refuse before swap.
        request["session"]=self.live.session.id;request["position_m"]=[15,-7]
        real=install._terrain_state
        old=self.live.session
        def altered(session):
            value=real(session)
            if session is not old: value["heights_b64"]="changed"
            return value
        with mock.patch.object(install,"_terrain_state",side_effect=altered):
            with self.assertRaisesRegex(ValueError,"changed terrain"):
                install.preview(self.app,request)
        self.assertIs(self.live.session,old)
        self.assertEqual(ground,install._terrain_state(old))

    def test_pending_ground_restart_retains_fractional_clock_and_continuation(self):
        self.room=world_room.Room("world");self.app.room=self.room
        self.open()
        self.live.session.send(op="dig",**{"from":[13,-7],"to":[13,-7],"width_m":.5,"depth_m":.05})
        self.live.session.send(op="step",dt=1/240,n=1)
        saved=self.snap()
        self.assertGreater(saved["ground"]["ground_behind_s"],0)
        resumed=live_session.Live();self.addCleanup(resumed.shutdown)
        resumed.open(self.app,{"spec":self.room.spec,"snapshot":saved})
        self.assertEqual(saved["ground"],install._snapshot(resumed)["ground"])
        for steps in (1,3,5,11,23):
            self.live.session.send(op="step",dt=1/240,n=steps)
            resumed.session.send(op="step",dt=1/240,n=steps)
            self.assertEqual(self.snap()["ground"],install._snapshot(resumed)["ground"])
            self.assertEqual(install._terrain_state(self.live.session),install._terrain_state(resumed.session))

    def test_corrupt_ground_snapshot_is_refused_without_replaying_edits(self):
        self.room=world_room.Room("world");self.app.room=self.room
        self.open();saved=self.snap()
        for key,value in (("time_s",None),("frontier",[0,0]),("frontier",[.5]),
                          ("commits",-1),("colliders",[]),("sand","invalid"),
                          ("exported",{"rock_m3":0,"sand_m3":1,"soil_m3":0})):
            with self.subTest(key=key,value=value):
                bad=deepcopy(saved)
                if value is None:del bad["ground"][key]
                else:bad["ground"][key]=value
                resumed=live_session.Live()
                try:
                    with self.assertRaises(live_session.LiveError):
                        resumed.open(self.app,{"spec":self.room.spec,"snapshot":bad})
                finally:resumed.shutdown()
                self.assertEqual(saved,self.snap())

    def test_ground_withdrawal_preserves_raw_substances_and_accounts_each_transfer(self):
        self.room=world_room.Room("world");self.app.room=self.room
        self.room.spec["terrain"]={"generate":{"kind":"flat","nx":64,"nz":64,
            "cell_m":.25,"sand_m":.02,"soil_m":.2}}
        self.open()
        self.live.session.send(op="dig",**{"from":[0,0],"to":[0,0],"width_m":.5,"depth_m":.1})
        before=self.snap();have=before["ground"]["carried"]
        self.assertGreater(have["sand_m3"],0)
        self.assertGreater(have["soil_m3"],0)
        moved={k:have[k]/2 for k in ("sand_m3","soil_m3")}
        answer=self.live.session.send(op="ground_withdraw",**moved)
        packet=answer["material_packet"]
        self.assertEqual(packet["schema"],"banjo.bulk-material.v1")
        self.assertEqual(packet["form"],"granular")
        self.assertEqual(packet["thermal_state"],"unmodeled")
        for content in packet["contents"]:
            substance=content["substance"]
            self.assertIn(substance,("sand","soil"))
            self.assertEqual(content["volume_m3"],moved[substance+"_m3"])
            self.assertEqual(content["mass_kg"],content["volume_m3"]*1600)
        after=self.snap()
        for key in before:
            if key!="ground":self.assertEqual(before[key],after[key],key)
        for key,value in moved.items():
            self.assertEqual(after["ground"]["carried"][key]+after["ground"]["exported"][key],have[key])
        resumed=live_session.Live();self.addCleanup(resumed.shutdown)
        resumed.open(self.app,{"spec":self.room.spec,"snapshot":after})
        self.assertEqual(after["ground"],install._snapshot(resumed)["ground"])
        for invalid in ({"sand_m3":-1,"soil_m3":0},{"sand_m3":0,"soil_m3":0},
                        {"sand_m3":have["sand_m3"]+1,"soil_m3":0}):
            with self.assertRaises(live_session.LiveError):resumed.session.send(op="ground_withdraw",**invalid)
            self.assertEqual(after,install._snapshot(resumed))
        resumed.session.send(op="ground_withdraw",**moved)
        empty=install._snapshot(resumed)["ground"]
        self.assertEqual(empty["carried"],{"rock_m3":0.,"sand_m3":0.,"soil_m3":0.})
        self.assertEqual(empty["exported"],have)
        with self.assertRaises(live_session.LiveError):resumed.session.send(op="ground_withdraw",**moved)

    def test_native_carry_budget_combines_objects_and_ground(self):
        for material in ("glass","oak","iron"):
            with self.subTest(material=material):
                self.open({"algorithm":"lattice","cell_m":.04,
                    "bodies":[{"name":name,"shape":"box","material":material,
                        "size_mm":[120,120,120],"center_mm":[x,1000,0]} for name,x in (("one",0),("two",400))],
                    "terrain":{"generate":{"kind":"flat","nx":32,"nz":32,"cell_m":.25,"soil_m":.2,"sand_m":.02}}})
                def send(op,**kw):return self.live.session.send(op=op,**kw)
                def burden():return send("environment")["environment"]["ground"]["carried"]
                mass=next(b["mass_kg"] for b in self.live.session.state["bodies"] if b["name"]=="one")
                send("carry_limit",kg=mass*1.5)
                send("wield",name="one",grip=[0,1,0])
                # The admission budget uses Jolt's native mass (float32), not
                # the geometric mass printed in the ordinary pose report.
                self.assertAlmostEqual(burden()["objects_kg"],mass,delta=1e-6)
                mass=burden()["objects_kg"];send("carry_limit",kg=mass*1.5)
                self.assertEqual(burden()["limit_kg"],mass*1.5)
                self.assertAlmostEqual(burden()["available_kg"],mass*.5)
                before=self.snap()
                with self.assertRaises(live_session.LiveError):send("park",name="two")
                self.assertEqual(before,self.snap())
                send("dig",**{"from":[1,1],"to":[1,1],"width_m":2,"depth_m":.2})
                self.assertAlmostEqual(burden()["total_kg"],mass*1.5,places=8)
                send("park",name="one")
                self.assertAlmostEqual(burden()["objects_kg"],mass)
                full=self.snap()
                with self.assertRaises(live_session.LiveError):send("wield",name="two",grip=[.4,1,0])
                self.assertEqual(full,self.snap())
                ground=burden();amounts={k:ground[k] for k in ("sand_m3","soil_m3")}
                send("ground_withdraw",**amounts)
                send("ground_return",**amounts)
                self.assertAlmostEqual(burden()["total_kg"],mass*1.5,places=8)
                # Replay the native saved masses; no recipe-derived refilling.
                saved=self.snap();resumed=live_session.Live();self.addCleanup(resumed.shutdown)
                resumed.open(self.app,{"spec":self.room.spec,"snapshot":saved})
                report=resumed.session.send(op="environment")["environment"]["ground"]["carried"]
                self.assertAlmostEqual(report["objects_kg"],mass)
                self.assertAlmostEqual(report["total_kg"],mass*1.5,places=8)
                send("unpark",name="one",at=[0,1,0])
                self.assertAlmostEqual(burden()["objects_kg"],0)
                send("wield",name="two",grip=[.4,1,0])
                self.assertAlmostEqual(burden()["objects_kg"],mass)

    def test_returned_ground_is_bounded_persistent_and_depositable(self):
        self.room=world_room.Room("world");self.app.room=self.room
        self.room.spec["terrain"]={"generate":{"kind":"flat","nx":32,"nz":32,
            "cell_m":.25,"sand_m":.02,"soil_m":.2}}
        self.open()
        self.live.session.send(op="dig",**{"from":[0,0],"to":[0,0],"width_m":.5,"depth_m":.1})
        before=self.snap();have={k:before["ground"]["carried"][k] for k in ("sand_m3","soil_m3")}
        self.live.session.send(op="ground_withdraw",**have)
        self.live.session.send(op="carry_limit",kg=0)
        empty=self.snap()
        with self.assertRaisesRegex(live_session.LiveError,"capacity"):
            self.live.session.send(op="ground_return",**have)
        self.assertEqual(empty,self.snap())
        self.live.session.send(op="carry_limit",kg=80)
        for bad in ({"sand_m3":-1,"soil_m3":0},{"sand_m3":0,"soil_m3":0},{"sand_m3":1,"soil_m3":0}):
            checkpoint=self.snap()
            with self.assertRaises(live_session.LiveError):self.live.session.send(op="ground_return",**bad)
            self.assertEqual(checkpoint,self.snap())
        self.live.session.send(op="ground_return",**have)
        returned=self.snap()
        self.assertEqual(returned["ground"]["carried"],before["ground"]["carried"])
        self.assertEqual(returned["ground"]["returned"],returned["ground"]["exported"])
        for key in before:
            if key!="ground":self.assertEqual(before[key],returned[key],key)
        with self.assertRaises(live_session.LiveError):self.live.session.send(op="ground_return",**have)
        resumed=live_session.Live();self.addCleanup(resumed.shutdown)
        resumed.open(self.app,{"spec":self.room.spec,"snapshot":returned})
        self.assertEqual(returned["ground"],install._snapshot(resumed)["ground"])
        resumed.session.send(op="deposit",at=[1,1],radius_m=.5,from_carried=True,**have)
        final=install._snapshot(resumed)["ground"]
        self.assertEqual(final["carried"],{"rock_m3":0.,"soil_m3":0.,"sand_m3":0.})
        for key,amount in have.items():self.assertAlmostEqual(final["ledger"]["deposited"][key],amount)
        for change in (None,{"sand_m3":1.,"soil_m3":0.,"rock_m3":0.},
                       {"sand_m3":-1.,"soil_m3":0.,"rock_m3":0.}):
            bad=deepcopy(returned)
            if change is None:bad["ground"].pop("returned")
            else:bad["ground"]["returned"]=change
            rejected=live_session.Live()
            try:
                with self.assertRaises(live_session.LiveError):rejected.open(self.app,{"spec":self.room.spec,"snapshot":bad})
            finally:rejected.shutdown()

    def test_ground_v2_exports_migrate_without_losing_transfer_history(self):
        self.room=world_room.Room("world");self.app.room=self.room
        self.room.spec["terrain"]={"generate":{"kind":"flat","nx":32,"nz":32,
            "cell_m":.25,"sand_m":.02,"soil_m":.2}}
        self.open()
        self.live.session.send(op="dig",**{"from":[0,0],"to":[0,0],"width_m":.5,"depth_m":.1})
        have=self.snap()["ground"]["carried"]
        self.live.session.send(op="ground_withdraw",sand_m3=have["sand_m3"],soil_m3=have["soil_m3"])
        original=self.snap();legacy=deepcopy(original)
        legacy["ground"]["schema"]="banjo.ground-state.v2";legacy["ground"].pop("returned")
        resumed=live_session.Live();self.addCleanup(resumed.shutdown)
        resumed.open(self.app,{"spec":self.room.spec,"snapshot":legacy})
        self.assertEqual(original["ground"],install._snapshot(resumed)["ground"])

    def test_ground_v1_save_migrates_with_zero_exports(self):
        self.room=world_room.Room("world");self.app.room=self.room;self.open()
        saved=self.snap();saved["ground"]["schema"]="banjo.ground-state.v1"
        saved["ground"].pop("exported");saved["ground"].pop("returned")
        resumed=live_session.Live();self.addCleanup(resumed.shutdown)
        resumed.open(self.app,{"spec":self.room.spec,"snapshot":saved})
        migrated=install._snapshot(resumed)["ground"]
        self.assertEqual(migrated["schema"],"banjo.ground-state.v3")
        self.assertEqual(migrated["exported"],{"rock_m3":0.,"sand_m3":0.,"soil_m3":0.})
        for key in saved["ground"]:
            if key!="schema":self.assertEqual(saved["ground"][key],migrated[key],key)

    def test_precise_rigid_terrain_remains_explicitly_refused(self):
        from fabrication_tests import candidate
        self.room=world_room.Room("world");self.app.room=self.room
        self.room.spec={"algorithm":"lattice","cell_m":.04,
            "bodies":[{"name":"marker","shape":"box","material":"iron","size_mm":[80,80,80],
                       "center_mm":[0,2000,0],"anchored":True}],
            "terrain":deepcopy(world_room.world()["terrain"])}
        self.open()
        product=candidate()
        product["component_overrides"]["part"]={"mechanics":{"model":"rigid"}}
        before=self.snap()
        request={"scene":"world","session":self.live.session.id,"mode":"authoring",
                 "candidate":product,"position_m":[13,-7]}
        with self.assertRaisesRegex(ValueError,"do not yet support terrain"):
            install.preview(self.app,request)
        self.assertEqual(before,self.snap())

    def test_programmed_use_survives_native_install_restart_and_runs(self):
        import server
        import threading
        import time
        program = {"label": "Push table", "steps": [{"do": "push_forward", "distance_m": .2, "speed_m_s": .4}]}
        candidate = {"kind": "table", "parameters": {"primary_use": program}}
        result = self.do_commit(self.preview(candidate=candidate))
        root = result["root_body"]
        saved = self.app.store.load("yard")
        action = next(a for a in saved.spec["actions"] if a["body"] == root)
        self.assertTrue(action["primary"])
        self.assertEqual(action["steps"], program["steps"])
        self.assertEqual(action["label"], program["label"])
        # Real native stepping accompanies the HTTP-style gesture, just as the
        # browser does. A blocked heavy table may honestly refuse displacement.
        stop = threading.Event()
        errors = []
        def tick():
            try:
                while not stop.is_set():
                    self.live.act({"session": self.live.session.id, "op": "step", "dt": 1/120, "n": 2})
                    time.sleep(.004)
            except Exception as error:
                errors.append(str(error))
        runner = threading.Thread(target=tick)
        runner.start()
        try:
            answer = server.run_action(self.app, {"object": root, "primary": True,
                                       "person": {"standing_m": [3, 0, 2], "facing": [0, 0, -1]}})
        finally:
            stop.set()
            runner.join(10)
        self.assertFalse(errors)
        self.assertFalse(runner.is_alive())
        self.assertEqual(answer["action"], "Push table")
        self.assertTrue(answer.get("done") or answer.get("refused"), answer)
        self.assertFalse((self.live.session.state.get("hand") or {}).get("holding"))

    def test_interaction_points_follow_native_com_in_both_installers(self):
        from mcp import workshop, interaction_points
        for rigid in (False, True):
            with self.subTest(rigid=rigid):
                self.open(world_room.yard())
                self.ctx=install.context(self.app,{})
                design=workshop.assemble("table")
                candidate={"kind":"table","parameters":{}}
                if rigid:
                    candidate["component_overrides"]={p.name:{"mechanics":{"model":"rigid"}} for p in design.parts}
                preview=self.preview(candidate=candidate,position=(3,2 if rigid else 0))
                result=self.do_commit(preview,request="points-rigid" if rigid else "points-lattice")
                root=result["root_body"]
                saved=self.app.store.load("yard")
                record=next(r for r in saved.spec["interaction_points"] if r["body"]==root)
                point=next(p for p in record["points"] if p["id"]=="top")
                pose=next(b for b in self.snap()["bodies"] if b["name"]==root)
                source=next(p for p in interaction_points.for_design(design) if p["id"]=="top")
                actual=[pose["pose"]["com_m"][a]+point["position_m"][a] for a in range(3)]
                expected=[source["position_m"][a]+preview["applied_translation_m"][a] for a in range(3)]
                for a,b in zip(actual,expected): self.assertAlmostEqual(a,b,places=6)
                self.assertEqual(record,next(r for r in self.room.spec["interaction_points"] if r["body"]==root))


    def test_an_installed_product_carries_its_parts_into_the_room(self):
        """#20 in a live room. A product used to arrive as one anonymous heap of
        cells, so nothing in the room could tell an interface bond from an
        interior one and every joint in it was solid wood. Its cells now keep
        which component they are, all the way onto the floor of the yard.

        No joint is DECLARED today: the owner's call of 2026-09-19 leaves every
        law whole, so nothing about how the table breaks changes. What is built
        is the road the numbers will travel when they are set."""
        first=self.do_commit(self.preview(candidate=self.built()));root=first['root_body']
        spec=self.room.spec
        self.assertEqual({f'{root}/top'}|{f'{root}/leg-{i}' for i in range(1,5)},
                         {b['part'] for b in spec['bodies'] if b.get('part')})
        self.assertNotIn('interfaces',spec)
        # Every label carries the root, so a second table of the same design is
        # its own object: a joint in one could never be read as a joint in the
        # other once the two are standing in one room.
        self.ctx=install.context(self.app,{})
        second=self.do_commit(self.preview(position=(7,0),candidate=self.built()),
                              request='install-request-2')['root_body']
        self.assertNotEqual(root,second)
        roots=[b['part'].split('/')[0] for b in self.room.spec['bodies'] if b.get('part')]
        self.assertEqual({root,second},set(roots))
        self.assertEqual(5,len({b['part'] for b in self.room.spec['bodies']
                                if b.get('part','').startswith(f'{second}/')}))
        # And what is written to disk is what comes back, labels and all.
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

    def test_scheduled_heater_is_preserved_even_before_first_step(self):
        old=self.live.session;old.send(op='heat',target='marker stone',power_w=100,seconds=1)
        raw,_=self.live.snapshot();self.assertEqual(1,raw['carry_readiness']['pending_heaters'])
        preview=self.preview();self.do_commit(preview)
        install._preserved(raw,self.snap(),preview['root_body'])
        self.assertEqual(raw['heat'],self.snap()['heat'])
        self.live.session.send(op='step',dt=1/120,n=12)
        self.assertGreater(self.live.session.state['t'],raw['t_s'])

    def test_live_gas_and_scene_heater_survive_atomic_installation(self):
        spec=world_room.yard()
        spec["thermo"]={"gas_regions":[{"name":"tank","contents":{"argon":1},
            "volume_m3":.1,"temperature_k":400,"pressure_pa":150000,"vent_area_m2":.00001}],
            "heaters":[{"target":"tank","power_w":100,"seconds":10}]}
        self.open(spec)
        self.live.session.send(op="step",dt=1/120,n=12)
        before=self.snap()
        p=self.preview();self.do_commit(p)
        install._preserved(before,self.snap(),p["root_body"])
        self.assertEqual(before["heat"],self.snap()["heat"])
        self.live.session.send(op="step",dt=1/120,n=12)
        after=self.snap()
        self.assertGreater(after["heat"]["network"]["time_s"],before["heat"]["network"]["time_s"])
        self.assertGreater(after["heat"]["network"]["ledger"]["heater_in_j"],
                           before["heat"]["network"]["ledger"]["heater_in_j"])

    def test_new_parts_join_hot_network_with_accounted_energy_and_mass(self):
        for material in ("glass","oak","iron"):
            with self.subTest(material=material):
                spec=world_room.yard()
                next(b for b in spec["bodies"] if b["name"]=="marker stone")["temperature_k"]=900
                self.open(spec)
                self.live.session.send(op="step",dt=1/120,n=12)
                before=self.snap()
                p=self.preview(material=material);self.do_commit(p,request="thermal-"+material)
                after=self.snap()
                install._preserved(before,after,p["root_body"])
                self.assertIn(p["root_body"],[l["body"] for l in after["heat"]["lumps"]])
                self.assertNotEqual(before["heat"]["network"]["ledger"]["joined_kg"],
                                    after["heat"]["network"]["ledger"]["joined_kg"])
                for field in ("heater_in_j","joined_j"):
                    bad=deepcopy(after);bad["heat"]["network"]["ledger"][field]+=1
                    with self.assertRaises(ValueError):
                        install._preserved(before,bad,p["root_body"])
                bad=deepcopy(after)
                old_name=before["heat"]["lumps"][0]["body"]
                next(l for l in bad["heat"]["lumps"] if l["body"]==old_name)["surface"]["internal_energy_j"]+=1
                with self.assertRaises(ValueError):
                    install._preserved(before,bad,p["root_body"])
                self.live.session.send(op="step",dt=1/120,n=12)

    def test_old_native_thermal_capability_is_still_refused(self):
        self.live.session.send(op="heat",target="marker stone",power_w=100,seconds=1)
        snapshot=self.live.snapshot()[0]
        snapshot["carry_readiness"].pop("thermal_network_version",None)
        with mock.patch.object(self.live,"snapshot",return_value=(snapshot,None)):
            with self.assertRaisesRegex(ValueError,"complete thermal carry"):
                self.preview()

    def test_physical_curve_and_requested_position_use_whole_grid_translation(self):
        candidate={'kind':'table','component_overrides':{'leg-1':{'skin':{'profile':'curve','bend_m':.04,'physical':True}}}}
        p=self.preview(candidate=candidate,position=(3.011,.011))
        self.assertEqual([75,0],p['placement_grid'][::2]);self.assertEqual(0,p['bounds_m'][0][1]);self.do_commit(p)
        self.assertTrue(p['engine_grid_verified'])

if __name__=='__main__':
    if not ENGINE and os.environ.get('BANJO_BROWSER_TESTS')=='required':raise RuntimeError('Native installation checks require an engine')
    unittest.main()
