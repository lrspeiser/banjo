"""Native pinball qualification: forces, contacts, finite power and springs."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import machine_world as mw
import machine_game as mg
import sandbox_pinball as pinball
import object_actions
import machine_chat

parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--engine')
args,rest=parser.parse_known_args();ENGINE=Path(args.engine or os.environ.get('BANJO_LIVE_ENGINE','')).resolve()


def advance(session, seconds, dt=1/240):
    """Paused native stepping: use the same validated force queue as HTTP."""
    dt=min(dt,session.compiled.get('physics_dt_s',dt))
    with session.lock:
        queued,session._pull_queue=session._pull_queue,{}
        if queued:session._pulled=True
        for body,(at,force) in queued.items():session.engine.op(op='pull',body=body,at=at,force=force)
        remaining=round(seconds/dt)
        while remaining:
            n=min(remaining,round((1/60)/dt));remaining-=n
            reply=session.engine.op(op='step',dt=dt,n=n,moved=True)
            session._ingest(reply)
            if reply.get('breakable'):
                for name in reply['breakable']:
                    session._ingest(session.engine.op(op='fracture',name=name,wait=True),full=True)
        session._probe()
    return session.readouts


class ObjectActions(unittest.TestCase):
    def level(self,material='aluminum',charge=10000):
        base=pinball.template()['base']
        if material!='aluminum':
            # Compare insulating/metallic handles pressing the SAME metal
            # switch. Glass and oak must not become conducting contact pads.
            x,z=.96,-.85
            mount=pinball.rigid('press guide',[x+.10,.40,z],[.16,.04,.08],'iron')
            handle=dict(name='press handle',shape='compound',material=material,fixed=False,
                at_m=[x+.045,.28,z],parts=[dict(shape='box',at_m=[0,0,0],size_m=[.04,.06,.06])])
            fixture=pinball.finish(dict(parts=[mount,handle],joints=[
                dict(name='press slide',kind='slide',a='press guide',b='press handle',at_m=[x+.045,.28,z],
                    axis=[0,1,0],lower_m=-.14,upper_m=.01,friction_n=.05),
                dict(name='press return',kind='spring',a='press guide',b='press handle',
                    at_m=[x+.045,.38,z],at_b_m=[x+.045,.31,z],rest_m=.03,stiffness_n_m=150,damping_n_s_m=1.5)]),{})
            mg.merge_fragment(base,fixture)
        base['batteries'][0]['charge_j']=charge
        return mg.requested_level(dict(level='free',base=base))

    def test_player_and_word_builder_use_the_same_saved_catalog_adapter(self):
        level=self.level()
        rows=object_actions.configure(level,[],'left button button','Tap','KeyA',[0,-30,0])
        answer=dict(reply='Hold Tap during Run to press the wired button.',add=[dict(piece='object_action',
            part='left button button',label='Tap',key='KeyA',push_y_n=-30)])
        result=machine_chat.respond_free('Give the left button a Tap action on A',level,[],call=lambda messages:(answer,{}))
        self.assertEqual(result['placements'],rows)
        self.assertIn('object_action',machine_chat.free_prompt(level))
        self.assertIn('button text',machine_chat.free_prompt(level))
        schema=machine_chat.free_response_schema(level)
        self.assertIn('object_action',json.dumps(schema))
        self.assertIn('left button button',[r['part'] for r in machine_chat.free_environment(level,[])['action_targets']])
        spec=mg.compose(level,rows)[0];c=mw.compile_spec(spec)
        self.assertEqual(len(c['player_controls']),3)
        bound=next(r for r in c['player_controls'] if r['part']=='left button button')
        self.assertEqual(bound['label'],'Tap');self.assertEqual(bound['key'],'KeyA')
        self.assertEqual(bound['replaces'],'left button')
        self.assertEqual(bound['location'],'auto')
        for location in object_actions.LOCATIONS:
            configured=object_actions.configure(level,[],'left button button','Tap','KeyA',[0,-30,0],location)
            action=next(t['control'] for t in object_actions.targets(mw.compile_spec(mg.compose(level,configured)[0])) if t['part']=='left button button')
            self.assertEqual(action['location'],location)
        original=next(r for r in level['machine']['player_controls'] if r['name']=='left button')
        self.assertEqual(bound['force_n'],original['force_n'])
        self.assertEqual(object_actions.configure(level,rows,'left button button','Again','KeyQ',[0,-20,0])[0]['label'],'Again')
        self.assertEqual(mw.compile_spec(mg.compose(level,[])[0])['player_controls'][0]['name'],'left button')

    def test_invalid_controls_cannot_bypass_the_physical_handle_contract(self):
        level=self.level()
        for target,label,key,force in [
            ('pinball','Push','KeyA',[0,-30,0]),('pinball table frame','Push','KeyA',[0,-30,0]),
            ('left button button','','KeyA',[0,-30,0]),('left button button','x'*61,'KeyA',[0,-30,0]),
            ('left button button','Push','KeyA',[0,0,0]),('left button button','Push','KeyA',[0,-121,0]),
            ('left button button','Push','KeyA',[100,100,0]),('left button button','Push','Escape',[0,-30,0]),
            ('left button button','Push','ArrowRight',[0,-30,0]),('left button button','Push','KeyA',[0,float('nan'),0])]:
            with self.subTest(target=target,label=label,key=key,force=force),self.assertRaises(ValueError):
                object_actions.configure(level,[],target,label,key,force)
        with self.assertRaises(ValueError):object_actions.configure(mg.level_by_id('easy-switch'),[],'handle','Push','',[0,-30,0])
        for rows in ({'piece':'object_action'},[None]):
            with self.assertRaises(ValueError):object_actions.configure(level,rows,'left button button','Push','KeyA',[0,-30,0])
        with self.assertRaises(ValueError):object_actions.configure(level,[],'left button button','Push','KeyA',[0,-30,0],'centre')
        row=object_actions.configure(level,[],'left button button','Tap','KeyA',[0,-30,0])[0]
        with self.assertRaises(ValueError):mg.compose(level,[row,dict(row,label='Duplicate',key='KeyD')])
        broken=copy.deepcopy(level['machine']);broken['player_controls'][0]['replaces']='not a declared action'
        with self.assertRaises(mw.MachineRefused):mw.compile_spec(broken)

    def test_builder_resolves_an_action_target_from_an_added_tool_alias(self):
        answer=dict(reply='Hold Push during Run.',add=[dict(piece='pinball_button',id='press',x_m=0,z_m=0),
            dict(piece='object_action',part='press button',label='Push',key='KeyA',push_y_n=-30)])
        r=machine_chat.respond_free('Add a physical button with an A action',mg.free_build(),[],call=lambda messages:(answer,{}))
        self.assertEqual(r['placements'][1]['part'],'your pinball_button 1 button')
        self.assertEqual(len(r['manual_actions']),1)
        self.assertEqual(mw.compile_spec(mg.compose(mg.free_build(),r['placements'])[0])['player_controls'][0]['key'],'KeyA')
        self.assertEqual(r['placements'][1]['location'],'auto')

    def test_removing_prepared_apparatus_prunes_its_actions(self):
        import sandbox_edit
        base=self.level()['machine']
        owner=next(o for o in sandbox_edit.objects(base) if 'left button button' in o['parts'])
        removed,_,compiled=sandbox_edit.edit(base,owner['id'],remove=True)
        self.assertFalse(any(c['part']=='left button button' for c in compiled['player_controls']))
        self.assertFalse(any(c['part']=='left button button' for c in removed['player_controls']))

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_custom_actions_press_real_material_contacts_and_require_the_power_loop(self):
        records=[]
        for material,charge,push in [('glass',10000,-30),('oak',10000,-30),('iron',10000,-30),
                                     ('iron',0,-30),('iron',10000,30)]:
            with self.subTest(material=material,charge=charge,push=push),tempfile.TemporaryDirectory() as logs:
                level=self.level(material,charge)
                rows=object_actions.configure(level,[],'press handle','Push','KeyA',[0,push,0])
                compiled=mw.compile_spec(mg.compose(level,rows)[0])
                session=mw.MachineSession(compiled,ENGINE,Path(logs),paced=False)
                try:
                    advance(session,.3);session.player_control('your object_action 1',True)
                    pressed=copy.deepcopy(advance(session,.5))
                    session.player_control('your object_action 1',False);released=copy.deepcopy(advance(session,.7))
                    contact=next(d for d in pressed['electrical']['devices'] if d['name']=='left button')['closed']
                    angle=next(j for j in pressed['joints'] if j['name']=='left flipper axle')['degrees']
                    final=next(j for j in released['joints'] if j['name']=='left flipper axle')['degrees']
                    ledger=released['electrical']['networks'][0]['ledger']
                    records.append(dict(material=material,charge_j=charge,push_n=push,closed=contact,
                        flipper_deg=angle,returned_deg=final,ledger=ledger,operator_pulls=released.get('pulls'),dt_s=1/480))
                    self.assertEqual(contact,push<0)
                    if charge and push<0:self.assertGreater(angle,35)
                    else:self.assertLess(abs(angle),3)
                    self.assertLess(abs(final),4)
                    self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
                    self.assertFalse(session._test_pulled)
                finally:session.close()
        print('OBJECT ACTION CONTACTS '+json.dumps(records),flush=True)


class Pinball(unittest.TestCase):
    def test_editable_starter_and_all_eight_tools_compile(self):
        template=pinball.template();before=copy.deepcopy(template)
        compiled=mw.compile_spec(template['base'])
        self.assertEqual(len(compiled['player_controls']),3)
        self.assertEqual(len(compiled['electrical']['wires']),6)
        self.assertEqual(template,before)
        self.assertEqual(len({r['piece'] for r in pinball.TRAY}),8)
        level=mg.requested_level(dict(level='free',base=template['base']))
        for row in pinball.TRAY:
            self.assertTrue(all(rule.get('label') for rule in row['knobs'].values()),row['piece'])
            self.assertIn(row['piece'],[t['piece'] for t in level['tray']])
            fragment=pinball.PIECES[row['piece']]('test '+row['piece'],
                {k:r['default'] for k,r in row['knobs'].items()}, {})
            mw.compile_spec(dict(schema=mw.SCHEMA,**fragment))

    def test_controls_reject_invalid_or_unbounded_interventions(self):
        base=pinball.template()['base']
        for change in [dict(force_n=[0,-121,0]),dict(part='pinball'),dict(key='Escape')]:
            bad=copy.deepcopy(base);bad['player_controls'][0].update(change)
            with self.assertRaises(mw.MachineRefused):mw.compile_spec(bad)

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_buttons_make_contact_power_flippers_and_springs_return_them(self):
        for charge in [10000,0]:
            with self.subTest(charge=charge),tempfile.TemporaryDirectory() as logs:
                spec=pinball.template()['base'];spec['batteries'][0]['charge_j']=charge
                session=mw.MachineSession(mw.compile_spec(spec),ENGINE,Path(logs),paced=False)
                try:
                    advance(session,.3)
                    session.player_control('left button',True);session.player_control('right button',True)
                    pressed=copy.deepcopy(advance(session,.3))
                    session.player_control('left button',False);session.player_control('right button',False)
                    released=copy.deepcopy(advance(session,.7))
                    print('PINBALL BUTTONS '+json.dumps(dict(charge=charge,
                        pressed=[j for j in pressed['joints'] if j['kind']=='hinge'],
                        released=[j for j in released['joints'] if j['kind']=='hinge'],
                        devices=pressed['electrical']['devices'],ledger=released['electrical']['networks'][0]['ledger'],
                        cables=[dict(name=c['name'],connected=c['connected'],peak=c['peak_terminal_force_n']) for c in pressed.get('mechanical_cables',[])])),flush=True)
                    self.assertFalse(session._test_pulled)
                    joints={j['name']:j for j in pressed['joints']}
                    for name in ['left button','right button']:
                        self.assertTrue(next(d for d in pressed['electrical']['devices'] if d['name']==name)['closed'])
                        self.assertFalse(next(d for d in released['electrical']['devices'] if d['name']==name)['closed'])
                    if charge:
                        self.assertGreater(joints['left flipper axle']['degrees'],35)
                        self.assertLess(joints['right flipper axle']['degrees'],-35)
                    else:
                        self.assertLess(abs(joints['left flipper axle']['degrees']),3)
                        self.assertLess(abs(joints['right flipper axle']['degrees']),3)
                    for j in released['joints']:
                        if j['name'].endswith('flipper axle'):self.assertLess(abs(j['degrees']),4)
                    for network in released['electrical'].get('networks',[]):
                        self.assertLess(abs(network['ledger']['electrical_residual_j']),1e-8)
                finally:session.close()

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_manual_launcher_transfers_spring_energy_to_material_balls(self):
        records=[]
        for material in ['glass','oak','iron']:
            for dt in [1/480,1/960]:
                with tempfile.TemporaryDirectory() as logs:
                    spec=pinball.template()['base'];spec['stations']=[]
                    next(p for p in spec['parts'] if p['name']=='pinball')['material']=material
                    session=mw.MachineSession(mw.compile_spec(spec),ENGINE,Path(logs),paced=False)
                    try:
                        advance(session,.2,dt)
                        before=list(session.bodies['pinball']['position_m'])
                        session.player_control('launcher',True);held=copy.deepcopy(advance(session,.5,dt))
                        spring=next(j for j in held['joints'] if j['name']=='launcher launcher spring')
                        session.player_control('launcher',False)
                        furthest=before[2];peak=0;leftmost=before[0]
                        for _ in range(120):
                            advance(session,.05,dt)
                            body=session.bodies.get('pinball',{})
                            point=body.get('position_m',before);angle=math.radians(pinball.SLOPE)
                            local_y=math.cos(angle)*(point[1]-pinball.HEIGHT)-math.sin(angle)*point[2]
                            local_z=math.sin(angle)*(point[1]-pinball.HEIGHT)+math.cos(angle)*point[2]
                            if .025<=local_y<=.24 and -1.3<=local_z<=1.3:
                                furthest=max(furthest,point[2]);leftmost=min(leftmost,point[0])
                            peak=max(peak,math.hypot(*body.get('velocity_m_s',[0,0,0])))
                        records.append(dict(material=material,dt_s=dt,stored_j=spring.get('stored_j'),
                            travel_m=furthest-before[2],leftmost_m=leftmost,peak_speed_m_s=peak,pulls=session.readouts.get('pulls')))
                        print('PINBALL LAUNCH '+json.dumps(records[-1]),flush=True)
                        self.assertGreater(spring['stored_j'],5)
                        if material=='iron':
                            self.assertGreater(furthest-before[2],2)
                            self.assertLess(leftmost,.3,'The launched ball must leave its lane and enter the playfield')
                        self.assertFalse(session._test_pulled)
                    finally:session.close()
        print('PINBALL MATERIALS '+json.dumps(records),flush=True)

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_powered_flipper_actually_hits_the_ball_and_an_open_supply_cannot(self):
        outcomes=[]
        for charge in [10000,0]:
            with tempfile.TemporaryDirectory() as logs:
                spec=pinball.template()['base'];spec['batteries'][0]['charge_j']=charge
                old=next(p for p in spec['parts'] if p['name']=='pinball')
                old.update(pinball.ball('pinball',dict(x_m=.16,z_m=-.79),{})['parts'][0])
                session=mw.MachineSession(mw.compile_spec(spec),ENGINE,Path(logs),paced=False)
                try:
                    advance(session,.1);start=session.bodies['pinball']['position_m'][2]
                    session.player_control('left button',True)
                    furthest=start
                    for _ in range(30):
                        advance(session,.02);furthest=max(furthest,session.bodies['pinball']['position_m'][2])
                    contacts=[e for e in session.events if e['kind']=='body_contact' and
                              {e['a'],e['b']}=={'pinball','left flipper paddle'}]
                    outcomes.append(dict(charge_j=charge,upfield_m=furthest-start,contacts=contacts,
                                         ledger=session.readouts['electrical']['networks'][0]['ledger']))
                    if charge:
                        self.assertTrue(contacts,'The paddle must make native contact with the ball')
                        self.assertGreater(furthest-start,.15)
                    else:self.assertLess(furthest-start,.03)
                finally:session.close()
        print('PINBALL FLIPPER CONTACT '+json.dumps(outcomes),flush=True)

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_outer_lane_routes_material_balls_into_flipper_reach(self):
        """A joined guide deflects through contact, rather than plugging a drain."""
        records=[]
        for material in ['glass','oak','iron']:
            for dt in [1/480,1/960]:
                for original in [False,True]:
                    with self.subTest(material=material,dt=dt,original=original),tempfile.TemporaryDirectory() as logs:
                        spec=pinball.template()['base']
                        next(p for p in spec['parts'] if p['name']=='pinball').update(
                            pinball.ball('pinball',dict(x_m=-.72,z_m=.35,material=material),{})['parts'][0])
                        if original:
                            next(p for p in spec['parts'] if p['name']=='left inlane guide').update(
                                pinball.rail('left inlane guide',dict(x_m=-.34,z_m=-.25,length_m=.40,angle_deg=45),{})['parts'][0])
                        spec['stations']=[dict(title='Guide contact',focus=['pinball','left inlane guide'],
                            done_when={'touches':['pinball','left inlane guide']})]
                        session=mw.MachineSession(mw.compile_spec(spec),ENGINE,Path(logs),paced=False)
                        try:
                            angle=math.radians(pinball.SLOPE);crossing=None
                            for _ in range(160):
                                advance(session,.05,dt)
                                x,y,z=session.bodies['pinball']['position_m']
                                local_z=math.sin(angle)*(y-pinball.HEIGHT)+math.cos(angle)*z
                                if local_z<=-.70:
                                    crossing=x;break
                            contacts=[e for e in session.events if e['kind']=='body_contact' and
                                {e['a'],e['b']}=={'pinball','left inlane guide'}]
                            ledger=session.readouts['electrical']['networks'][0]['ledger']
                            records.append(dict(material=material,dt_s=dt,original=original,
                                crossing_x_m=crossing,time_s=session.t,guide_contacts=len(contacts),ledger=ledger))
                            print('PINBALL OUTER LANE '+json.dumps(records[-1]),flush=True)
                            self.assertIsNotNone(crossing,'A retained ball must continue downhill, not wedge against a rail end')
                            if original:self.assertLess(crossing,-.65)
                            else:
                                self.assertGreater(crossing,-.43,'The ball must enter the flipper sweep')
                                self.assertLess(crossing,-.02)
                                self.assertTrue(contacts)
                            self.assertFalse(session._test_pulled)
                            self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
                        finally:session.close()

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_a_lost_button_lease_stops_its_force(self):
        import time
        with tempfile.TemporaryDirectory() as logs:
            session=mw.MachineSession(mw.compile_spec(pinball.template()['base']),ENGINE,Path(logs),paced=True)
            try:
                session.player_control('left button',True);session.play(True)
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    with session.lock:
                        if session.t>2.3:break
                    time.sleep(.03)
                self.assertIsNone(session.error)
                with session.lock:
                    device=next(d for d in session.readouts['electrical']['devices'] if d['name']=='left button')
                    self.assertFalse(device['closed'])
                    self.assertNotIn('left button button',session._switch_force_until)
            finally:session.close()


if __name__=='__main__':unittest.main(argv=[sys.argv[0],*rest])
