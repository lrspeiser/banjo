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
    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_flat_push_button_drives_a_wired_motor_and_requires_charge(self):
        import sandbox_electrics as e
        for charge in (1000,0):
            with self.subTest(charge=charge),tempfile.TemporaryDirectory() as logs:
                spec=e.empty('Push to run');spec['physics_dt_s']=1/480
                for make,name,k in [(e.battery,'supply',dict(x_m=-.8,z_m=-.4)),
                    (e.push_button,'press',{}),(e.motor,'drive',dict(x_m=.8,z_m=.4))]:
                    mg.merge_fragment(spec,make(name,k,{}))
                spec['batteries'][0]['charge_j']=charge
                for n,a,b in [('feed','supply:plus','press:in'),('switched feed','press:out','drive:plus'),('return','drive:minus','supply:minus')]:e.link(spec,n,a,b)
                q=mw.MachineSession(mw.compile_spec(spec),ENGINE,Path(logs),paced=False)
                try:
                    advance(q,.2);q.player_control('press',True);r=advance(q,1.)
                    self.assertTrue(next(d['closed'] for d in r['electrical']['devices'] if d['name']=='press'))
                    angle=next(j['degrees'] for j in r['joints'] if j['name']=='drive axle')
                    if charge:self.assertGreater(abs(angle),30)
                    else:self.assertLess(abs(angle),1)
                    q.player_control('press',False);r=advance(q,.4)
                    self.assertFalse(next(d['closed'] for d in r['electrical']['devices'] if d['name']=='press'))
                    self.assertLess(abs(r['electrical']['networks'][0]['ledger']['electrical_residual_j']),1e-8)
                finally:q.close()

    def selector(self,material='aluminum',charge=1000,angle=-50):
        import sandbox_electrics as e
        s=e.selector_bench()
        replacement=e.rotary_selector('power selector',dict(handle_material=material,angle_deg=angle),{})
        s['parts']=[p for p in s['parts'] if not p['name'].startswith('power selector')]+replacement['parts']
        s['joints']=replacement['joints'];s['player_controls']=replacement['player_controls']
        for b in s['batteries']:b['charge_j']=charge
        e.link(s,'lamp return','lamp:minus','supply:minus')
        return s

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_rotary_selector_contact_power_materials_and_reverse_hand_input(self):
        records=[]
        for dt in (1/480,1/960):
            for material in ('glass','oak','iron'):
                with self.subTest(dt=dt,material=material),tempfile.TemporaryDirectory() as logs:
                    spec=self.selector(material);spec['physics_dt_s']=dt
                    q=mw.MachineSession(mw.compile_spec(spec),ENGINE,Path(logs),paced=False)
                    try:
                        def power(r):return next(d['power_w'] for d in r['electrical']['devices'] if d['name']=='lamp')
                        low=power(advance(q,.3))
                        q.player_control('power selector',True,1);advance(q,.6)
                        q.player_control('power selector',False);high=power(advance(q,.3))
                        raised=next(j['degrees'] for j in q.readouts['joints'] if j['name']=='power selector dial axle')
                        q.player_control('power selector',True,-1);advance(q,.6)
                        q.player_control('power selector',False);returned=power(advance(q,.3))
                        ledger=q.readouts['electrical']['networks'][0]['ledger']
                        records.append(dict(dt_s=dt,handle=material,low_w=low,high_w=high,returned_w=returned,
                            turn_deg=raised,ledger=ledger,operator_pulls=q.readouts.get('pulls')))
                        self.assertGreater(low,.2);self.assertLess(low,.5)
                        self.assertGreater(high,2.5);self.assertGreater(raised,85)
                        self.assertGreater(returned,.2);self.assertLess(returned,.5)
                        self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
                        self.assertFalse(q._test_pulled)
                    finally:q.close()
        print('ROTARY MATERIAL CONTACTS '+json.dumps(records),flush=True)

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_selector_gaps_empty_supply_and_invalid_operator_values(self):
        for angle,charge,low,high in [(-25,1000,0,1e-9),(0,1000,1.2,1.5),(50,0,0,1e-9)]:
            with self.subTest(angle=angle,charge=charge),tempfile.TemporaryDirectory() as logs:
                spec=self.selector(angle=angle,charge=charge)
                q=mw.MachineSession(mw.compile_spec(spec),ENGINE,Path(logs),paced=False)
                try:
                    r=advance(q,.4)
                    power=next(d['power_w'] for d in r['electrical']['devices'] if d['name']=='lamp')
                    self.assertGreaterEqual(power,low);self.assertLessEqual(power,high)
                    for value in (True,None,2,-2,float('nan')):
                        with self.assertRaises(ValueError):q.player_control('power selector',True,value)
                    self.assertFalse(q._pull_queue)
                finally:q.close()
        level=mg.level_by_id('easy-power-selector')
        with tempfile.TemporaryDirectory() as logs:
            self.assertEqual(mg.trial(level,level['solution'],ENGINE,Path(logs),runs=3,action_inputs=level['solution_actions'])['worked'],3)
            self.assertEqual(mg.trial(level,level['wrong'],ENGINE,Path(logs),runs=3,action_inputs=level['solution_actions'])['worked'],0)
            self.assertEqual(mg.trial(level,level['solution'],ENGINE,Path(logs),runs=1)['worked'],0)

    def level(self,material='aluminum',charge=10000):
        base=pinball.template()['base']
        if material!='aluminum':
            # Compare insulating/metallic handles pressing the SAME metal
            # switch. Glass and oak must not become conducting contact pads.
            x,z=.96,-.85
            mount=pinball.rigid('press guide',[x+.10,.40,z],[.16,.04,.08],'iron')
            handle=dict(name='press handle',shape='compound',material=material,fixed=False,
                at_m=[x+.045,.25,z],parts=[dict(shape='box',at_m=[0,0,0],size_m=[.04,.06,.06])])
            fixture=pinball.finish(dict(parts=[mount,handle],joints=[
                dict(name='press slide',kind='slide',a='press guide',b='press handle',at_m=[x+.045,.25,z],
                    axis=[0,1,0],lower_m=-.14,upper_m=.01,friction_n=.05),
                dict(name='press return',kind='spring',a='press guide',b='press handle',
                    # Support the iron handle's weight without letting it
                    # operate the shorter-throw contact before player input.
                    at_m=[x+.045,.38,z],at_b_m=[x+.045,.28,z],rest_m=.03,stiffness_n_m=250,damping_n_s_m=1.5)]),{})
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
            dict(piece='object_action',part='press button',label='Push',key='KeyA',push_y_n=-30,mode='turn',location='near')])
        r=machine_chat.respond_free('Add a physical button with an A action',mg.free_build(),[],call=lambda messages:(answer,{}))
        self.assertEqual(r['placements'][1]['part'],'your pinball_button 1 button')
        self.assertEqual(len(r['manual_actions']),1)
        self.assertEqual(mw.compile_spec(mg.compose(mg.free_build(),r['placements'])[0])['player_controls'][0]['key'],'KeyA')
        self.assertEqual(r['placements'][1]['location'],'near')
        self.assertEqual(r['manual_actions'][0]['mode'],'turn')

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
    def test_marble_layers_are_explicit_and_keep_the_cover_in_new_and_saved_tables(self):
        for old in [False,True]:
            spec=pinball.template()['base']
            if old:spec['presentation']['placement_inside']=['pinball table glass cover']
            level=mg.requested_level(dict(level='free',base=spec))
            placement=dict(piece='marble',x_m=0,z_m=-.2)
            ghost=mg.ghost(level,[placement],0)
            self.assertEqual(ghost['placement_layers']['index'],0)
            self.assertEqual([p['support'] for p in ghost['placement_layers']['positions']],
                ['pinball table glass cover','pinball table frame','ground'])
            placement['support_layer']=1
            compiled=mg._assemble(level,[placement])[3]
            parts={p['name']:p for p in compiled['parts']}
            ball=parts['your marble 1'];cover=parts['pinball table glass cover']
            self.assertEqual(ball['shape'],'compound')
            self.assertEqual(ball['parts'][0]['shape'],'sphere')
            self.assertLess(ball['at_m'][1],cover['at_m'][1]-.10)
            self.assertEqual(cover,mw.compile_spec(spec)['parts'][1], 'Placement must keep the actual glass collider')
            ordinary=mg._assemble(mg.free_build(),[dict(piece='marble',x_m=0,z_m=0)])[3]
            self.assertEqual(next(p for p in ordinary['parts'] if p['name']=='your marble 1')['shape'],'sphere')

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_marble_tool_contacts_the_deck_and_the_cover_still_retains_an_above_ball(self):
        angle=math.radians(pinball.SLOPE)
        for material in ['glass','oak','iron']:
            for above in [False,True]:
                spec=pinball.template()['base']
                level=mg.requested_level(dict(level='free',base=spec))
                k=dict(piece='marble',x_m=0,z_m=-.2,material=material,support_layer=0 if above else 1)
                compiled=mg._assemble(level,[k])[3]
                name='your marble 1';ball=next(p for p in compiled['parts'] if p['name']==name)
                hit='pinball table glass cover' if above else 'pinball table frame'
                compiled['stations']=[dict(title='Physical support',focus=[name,hit],done_when={'touches':[name,hit]})]
                with self.subTest(material=material,above=above),tempfile.TemporaryDirectory() as logs:
                    session=mw.MachineSession(compiled,ENGINE,Path(logs),paced=False)
                    try:
                        advance(session,.5)
                        x,y,z=session.bodies[name]['position_m']
                        local_y=math.cos(angle)*(y-pinball.HEIGHT)-math.sin(angle)*z
                        self.assertTrue(any(e['kind']=='body_contact' and {e['a'],e['b']}=={name,hit} for e in session.events))
                        if above:self.assertGreater(local_y,.25)
                        else:self.assertTrue(.03<local_y<.08,local_y)
                        print('PINBALL COVER '+json.dumps(dict(material=material,above=above,local_y_m=local_y)),flush=True)
                    finally:session.close()

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_short_throw_buttons_and_hollow_paddles_respond_then_return(self):
        with tempfile.TemporaryDirectory() as logs:
            session=mw.MachineSession(mw.compile_spec(pinball.template()['base']),ENGINE,Path(logs),paced=False)
            try:
                advance(session,.25)
                self.assertLess(session.bodies['left flipper paddle']['mass_kg'],1.3)
                rows=[]
                for cycle in range(3):
                    session.player_control('left button',True);session.player_control('right button',True)
                    start=session.t;first_contact=None;full=None
                    for _ in range(16):
                        r=advance(session,.01)
                        devices={d['name']:d for d in r['electrical']['devices']}
                        joints={j['name']:j for j in r['joints']}
                        if first_contact is None and all(devices[n]['closed'] for n in ['left button','right button']):first_contact=session.t-start
                        if full is None and min(abs(joints[n]['degrees']) for n in ['left flipper axle','right flipper axle'])>=50:full=session.t-start
                    self.assertIsNotNone(first_contact);self.assertLess(first_contact,.04)
                    self.assertIsNotNone(full);self.assertLess(full,.16)
                    session.player_control('left button',False);session.player_control('right button',False)
                    r=advance(session,.7)
                    self.assertTrue(all(abs(j['degrees'])<4 for j in r['joints'] if j['name'].endswith('flipper axle')))
                    ledger=r['electrical']['networks'][0]['ledger']
                    self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
                    rows.append(dict(cycle=cycle,contact_s=first_contact,travel_s=full,ledger=ledger))
                print('PINBALL RESPONSE '+json.dumps(rows),flush=True)
            finally:session.close()

    @unittest.skipUnless(ENGINE.is_file(),'native engine required')
    def test_balls_behind_either_flipper_reach_the_drain_without_a_spring_anchor_trap(self):
        for material in ['glass','oak','iron']:
            for dt in [1/480,1/960]:
                for side in [-1,1]:
                    spec=pinball.template()['base']
                    next(p for p in spec['parts'] if p['name']=='pinball').update(
                        pinball.ball('pinball',dict(x_m=side*.43,z_m=-.94,material=material),{})['parts'][0])
                    with self.subTest(material=material,dt=dt,side=side),tempfile.TemporaryDirectory() as logs:
                        session=mw.MachineSession(mw.compile_spec(spec),ENGINE,Path(logs),paced=False)
                        try:
                            advance(session,4,dt)
                            pos=session.bodies['pinball']['position_m']
                            self.assertLess(pos[1],.2,'A missed ball must drain, not rest against a return linkage')
                            print('PINBALL DRAIN '+json.dumps(dict(material=material,dt_s=dt,side=side,position_m=pos)),flush=True)
                        finally:session.close()

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
