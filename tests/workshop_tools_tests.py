"""Generic component-frame tool declarations and actual native installation."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import os
import math
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground'),str(ROOT/'tests')]
from mcp import workshop_components, workshop_tools, workshop_construction
import workshop_chat
import workshop_install_engine_tests as native
if os.environ.get('BANJO_GROUND_TOOL_TESTS')=='required' and not (native.ENGINE and native.ENGINE.is_file()):
    raise RuntimeError('The required native ground-tool runner is missing')


def candidate(material='oak'):
    # 50 mm native cells: an 800 mm haft and 300 mm arm, meeting face to face.
    # Test design built through the existing custom component API, not grants
    # or a tool-name shortcut. Compare with the production recipe separately.
    parts=[{'name':'haft','role':'handle','family':'beam','shape':'box',
        'size_m':[.8,.05,.05],'center_m':[0,.025,.175],'rotation_deg':[0,0,0],'material':material},
        {'name':'arm','role':'tool-head','family':'beam','shape':'box',
        'size_m':[.05,.05,.3],'center_m':[.375,.025,0],'rotation_deg':[0,0,0],'material':material}]
    tool={'point':{'component':'arm','tip_local_m':[0,0,-.15],'direction_local':[0,0,-1],
                  'width_m':.05,'thickness_m':.05,'angle_deg':30,'length_m':.2},
          'grip':{'component':'haft','position_local_m':[-.35,0,0]}}
    return {'kind':'custom','design_id':'test-field-pick','purpose':'Field pick',
        'parameters':{'ground_tool':tool,'primary_use':{'label':'Study tool','steps':[{'do':'inspect'}]}},
        'component_overrides':{workshop_construction.CONSTRUCTION_KEY:{'added':parts,'joints_authored':True}}}


class ComponentFrames(unittest.TestCase):
    def test_starter_recipe_has_the_same_geometry_and_declared_grip(self):
        from mcp import workshop, interaction_points
        design = workshop.assemble('field-pick', design_id='starter')
        custom, _ = workshop_components.design_from_spec(candidate())
        wanted, actual = workshop_tools.frame(custom), workshop_tools.frame(design)
        for field in ('tip_m','grip_m','pointing'):
            for a,b in zip(wanted[field],actual[field]): self.assertAlmostEqual(a,b)
        grip=next(p['position_m'] for p in interaction_points.for_design(design) if p['kind']=='grip')
        for a,b in zip([-.35,.025,.175],grip): self.assertAlmostEqual(a,b)
        for material in ('glass','oak','iron'):
            made = workshop.assemble('field-pick', design_id='starter', parameters={'material':material})
            self.assertEqual({material}, {p.material for p in made.parts})

    def test_declaration_moves_with_components_and_survives_recipe_roundtrip(self):
        import workshop_install
        design,overrides=workshop_components.design_from_spec(candidate())
        frame=workshop_tools.frame(design)
        self.assertEqual([.375,.025,-.15],frame['tip_m'])
        self.assertEqual([-.35,.025,.175],frame['grip_m'])
        recipe=workshop_install.recipe_of(design,overrides)
        back,_=workshop_components.design_from_spec(recipe)
        self.assertEqual(frame,workshop_tools.frame(back))
        changed=deepcopy(recipe)
        changed['component_overrides']['arm']={'center_m':[1,.025,0],'rotation_deg':[0,90,0]}
        rotated,_=workshop_components.design_from_spec(changed)
        at=workshop_tools.frame(rotated)
        self.assertAlmostEqual(.85,at['tip_m'][0])
        self.assertAlmostEqual(-1,at['pointing'][0])

    def test_bad_fields_numbers_missing_components_and_off_matter_grip_are_refused(self):
        for kind in ('code','mass','nan','bool','zero','missing','grip-off','tip-off','swing-override'):
            bad=candidate(); tool=bad['parameters']['ground_tool']
            if kind=='code':tool['code']='execute me'
            if kind=='mass':tool['point']['mass_kg']=1
            if kind=='nan':tool['point']['width_m']=float('nan')
            if kind=='bool':tool['point']['length_m']=True
            if kind=='zero':tool['point']['direction_local']=[0,0,0]
            if kind=='missing':tool['point']['component']='absent'
            if kind=='grip-off':tool['grip']['position_local_m']=[8,0,0]
            if kind=='tip-off':tool['point']['tip_local_m']=[0,0,-.4]
            if kind=='swing-override':tool['use']={'impulse_j':10000}
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                workshop_components.design_from_spec(bad)

    def test_model_tool_refreshes_the_editable_candidate(self):
        spec=candidate(); declaration=spec['parameters'].pop('ground_tool')
        with tempfile.TemporaryDirectory() as tmp:
            app=SimpleNamespace(workshop_store=Path(tmp),api_key='')
            state=workshop_chat._State(app,spec,None,['oak'],[])
            answer=state.execute('define_ground_tool',declaration)
            self.assertIn('ground_tool',spec['parameters'])
            self.assertEqual(workshop_tools.checked(declaration),spec['parameters']['ground_tool'])
            self.assertIn('native admission',answer['summary'])


@unittest.skipUnless(native.ENGINE and native.ENGINE.is_file(),'BANJO_LIVE_ENGINE is required')
class GroundToolInstallation(unittest.TestCase):
    # Reuse fixture lifecycle helpers, not the unrelated parent test suite.
    setUp=native.NativeInstallation.setUp
    open=native.NativeInstallation.open
    snap=native.NativeInstallation.snap
    preview=native.NativeInstallation.preview
    request=native.NativeInstallation.request
    do_commit=native.NativeInstallation.do_commit
    def test_generated_worlds_admit_the_recipe_tool_beside_spawn_and_restore_it(self):
        sys.path.insert(0,str(ROOT/'tools'))
        import build_new_world as builder, build_explore_world as terrain, world_seed
        import inventory, inventory_room
        for terrain_seed, goods_seed in ((7,851269742),(4,1)):
            ground=terrain.read_ground(native.ENGINE,terrain_seed)
            made=world_seed.new_world(ground,seed=goods_seed,start_xz=builder.ARRIVE_AT)
            spec=builder.compose(ground,made,terrain_seed)
            self.open(spec)
            session=self.live.session
            state=session.state
            profile=next(p for p in self.room.spec['interactions'] if p['tool']=='field pick')
            item=next(i for i in inventory.items_of(self.room.spec) if 'field pick' in i['bodies'])
            body=next(b for b in state['bodies'] if b['name']=='field pick')
            self.assertAlmostEqual(1.925,body['mass_kg'])
            self.assertLessEqual(math.hypot(body['position_m'][0],body['position_m'][2]),1.8)
            self.assertFalse(world_seed.wet_near(ground,body['position_m'][0],body['position_m'][2],.4))
            root,grip=inventory_room.hold_point(self.app,item,'field pick')
            declared=self.room.spec['tool_points'][0]
            self.assertEqual('field pick',root)
            # Player poses serialize each coordinate to five decimal places;
            # this is a display bound, not a native point-frame tolerance.
            self.assertLess(math.dist(grip,[v/1000 for v in declared['grip_mm']]),1e-5)
            self.assertEqual(set(item['bodies']),set(profile['parts']))
            self.live.act({'session':session.id,'op':'wield','name':root,'grip':grip})
            self.assertEqual(root,session.state['hand']['holding'])
            snapshot=self.snap()
            opened=self.live.open(self.app,{'spec':self.room.spec,'snapshot':snapshot})
            self.assertEqual('whole',opened['restored']['tier'])
            self.assertEqual(snapshot['tool_points'],self.snap()['tool_points'])
            self.assertEqual(snapshot['bodies'],self.snap()['bodies'])
            print('generated starter tool:',{'terrain_seed':terrain_seed,'goods_seed':goods_seed,
                'mass_kg':body['mass_kg'],'at_m':body['position_m'],'native_point_attached':snapshot['tool_points'][0]['attached']})

    def test_declarative_tools_install_preserve_points_and_refuse_false_tips(self):
        import world_room
        for material in ('glass','oak','iron'):
            spec=world_room.yard();spec['cell_m']=.05
            for body in spec['bodies']:body['size_mm']=[100,100,100]
            spec['precise_rigid_bodies']=[{'name':'equipment','material':'iron','position_m':[-2,.01,0],
                'parts':[{'dimensions_m':[.02]*3,'center_local_m':[0,0,0]}]}]
            self.open(spec)
            before=self.snap()
            preview=self.preview(candidate=candidate(material),position=(3,0))
            receipt=self.do_commit(preview,'tool-'+material)
            after=self.snap();point=after['tool_points'][-1]
            self.assertEqual(.05,point['width_m'])
            self.assertEqual('installed',receipt['status'])
            self.assertEqual(1,len(after['tool_points'])-len(before.get('tool_points',[])))
            roots={b['name'] for b in after['bodies']} - {b['name'] for b in before['bodies']}
            added=next(b for b in after['bodies'] if b['name']==point['body'])
            self.assertEqual(roots,{point['body']})
            self.assertEqual(added['body_id'],point['body_id'])
            expected=.00275*{'glass':2500,'oak':700,'iron':7870}[material]
            self.assertAlmostEqual(expected,next(b['mass_kg'] for b in self.live.session.state['bodies'] if b['name']==point['body']))
            definition=next(p for p in self.room.spec['tool_points'] if p['body']==point['body'])
            import workshop_install as install
            install._preserved(before,after,roots,added_tool_points=[definition])
            for field,value in (('width_m',.06),('tip_local',[5,0,0]),('body','equipment'),('attached',False),
                                ('frame_nodes_b64',''),('frame_offsets_b64',''),('width_local',[0,0,0])):
                corrupt=deepcopy(after);corrupt['tool_points'][-1][field]=value
                with self.subTest(material=material,field=field),self.assertRaises(ValueError):
                    install._preserved(before,corrupt,roots,added_tool_points=[definition])
            kept=deepcopy(after['tool_points'])
            self.ctx=install.context(self.app,{})
            table=self.preview(position=(5,0),candidate={'kind':'table','parameters':{
                'height_m':.75,'top_thickness_m':.05,'leg_section_m':.05,'leg_inset_m':.1}})
            self.do_commit(table,'table-'+material)
            self.assertEqual(kept,self.snap()['tool_points'])
            saved=self.snap()
            opened=self.live.open(self.app,{'spec':self.room.spec,'snapshot':saved})
            self.assertEqual('whole',opened['restored']['tier'])
            self.assertEqual(kept,self.snap()['tool_points'])
            self.assertEqual(saved['bodies'],self.snap()['bodies'])
            self.ctx=install.context(self.app,{})
        false=candidate();false['parameters']['ground_tool']['point']['direction_local']=[0,0,1]
        with self.assertRaisesRegex(ValueError,'tool'):
            self.preview(candidate=false,position=(7,0))

    def test_installed_oak_tool_uses_the_existing_bounded_hand_and_ground_model(self):
        import world_room, tool_use, workshop_install as install
        spec=world_room.yard();spec['cell_m']=.05
        for body in spec['bodies']:body['size_mm']=[100,100,100]
        spec['terrain']={'generate':{'kind':'flat','nx':120,'nz':120,'cell_m':.1,
            'soil_m':.4,'sand_m':0,'discharge_m3_s':0}}
        spec['precise_rigid_bodies']=[{'name':'equipment','material':'iron','position_m':[-3,.01,-3],
            'parts':[{'dimensions_m':[.02]*3,'center_local_m':[0,0,0]}]}]
        self.open(spec)
        preview=self.preview(candidate=candidate(),position=(0,1.2))
        self.do_commit(preview,'physical-tool')
        session=self.live.session
        self.app.reply_listeners=[]
        def hear(session,reply):
            for listener in list(self.app.reply_listeners):listener(session,reply)
        session.on_reply=hear
        point=self.room.spec['tool_points'][-1]
        grip=[v/1000 for v in point['grip_mm']]
        self.live.act({'session':session.id,'op':'wield','name':point['body'],'grip':grip})
        before=(session.state.get('carried') or {}).get('soil_kg',0)
        request={'person':{'standing_m':[-.9,.4,.025],'eyes_m':[-.9,2.02,.025],
                           'facing':[1,0,0]},'at_m':[.3,.4,.025]}
        result=[];errors=[]
        def use():
            try:result.append(tool_use.run(self.app,request))
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=use,daemon=True);worker.start()
        deadline=time.monotonic()+22
        while worker.is_alive() and time.monotonic()<deadline:
            self.live.act({'session':session.id,'op':'step','dt':1/240,'n':12})
            time.sleep(.015)
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive(),'bounded tool use did not finish')
        self.assertEqual([],errors)
        self.assertNotIn('refused',result[0],result[0])
        record=result[0].get('result') or {}
        self.assertFalse(record.get('open',True),result[0])
        self.assertTrue(record.get('supported'),result[0])
        self.assertGreater(record.get('loosened_kg',0),0,result[0])
        self.assertGreater(record.get('work_j',0),0)
        delta_kg=result[0]['carried']['soil_kg']-before
        self.assertAlmostEqual(record['loosened']['soil_m3'],delta_kg/1600,delta=1e-12)
        # The human-facing mass field is serialized by tidy() at five decimal
        # places; source volume and the carried account remain unrounded.
        self.assertAlmostEqual(record['loosened_kg'],delta_kg,delta=5e-6)
        print('declared oak tool physical use:',{'cells':22,'mass_kg':1.925,'dt':1/240,
            'kind':record['kind'],'soil_m3':record['loosened']['soil_m3'],
            'loosened_kg':record['loosened_kg'],'work_j':record['work_j'],
            'carried_volume_residual_m3':record['loosened']['soil_m3']-delta_kg/1600})


if __name__=='__main__':unittest.main()
