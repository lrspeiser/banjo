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

parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--engine')
args,rest=parser.parse_known_args();ENGINE=Path(args.engine or os.environ.get('BANJO_LIVE_ENGINE',''))


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
