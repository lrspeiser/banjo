"""A field-operated rocker: hinge angles, real forces and finite DC energy."""
import base64
import copy
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from contextlib import contextmanager

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import machine_world as mw
import sandbox_electrics as e

ENGINE=Path(os.environ.get('BANJO_LIVE_ENGINE',ROOT/'build/agent-integration/empty-native/banjo_live_world_run.exe'))
if '--engine' in sys.argv:
    i=sys.argv.index('--engine');ENGINE=Path(sys.argv[i+1]).resolve();del sys.argv[i:i+2]


def fixture(material='oak',closed=False):
    spec=e.empty('Mechanical field switch')
    e.merge(spec,e.battery('supply',{'x_m':-.6},{}))
    e.merge(spec,e.switch('control',dict(handle_material=material,state='closed' if closed else 'open'),{}))
    e.merge(spec,e.bulb('lamp',{'x_m':.6},{}))
    for name,a,b in [('feed','supply:plus','control:in'),('switched','control:out','lamp:plus'),
                     ('return','lamp:minus','supply:minus')]:e.link(spec,name,a,b)
    return spec


def state(engine):
    return next(b for b in engine.op(op='snapshot')['snapshot']['bodies'] if b['name']=='control handle')


def rotate(q,v):
    w,x,y,z=q;u=[x,y,z]
    cross=lambda a,b:[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    t=[2*a for a in cross(u,v)];c=cross(u,t)
    return [v[i]+w*t[i]+c[i] for i in range(3)]


def point(body,local):
    p=body['pose'];r=rotate(p['q_wxyz'],local)
    return [p['com_m'][i]+r[i] for i in range(3)]


def angle(body):
    q=body['pose']['q_wxyz'];return 2*math.atan2(q[3],q[0])


def circuits(engine):
    c=engine.op(op='circuits')['circuits'][0]
    return c,next(b for b in c['branches'] if b['id']=='control'),next(b for b in c['branches'] if b['id']=='lamp')


def advance(engine,seconds,dt):
    for _ in range(round(seconds/dt)):
        r=engine.op(op='step',dt=dt,n=1,moved=False)
        if r.get('stepped_back'):raise AssertionError('rocker entered an unexpected fracture trial')


@contextmanager
def opened(spec):
    compiled=mw.compile_spec(spec)
    with tempfile.TemporaryDirectory(prefix='banjo-mechanical-switch-') as logs:
        engine,_,_=mw.build_engine(ENGINE,compiled,Path(logs))
        try:
            initial=state(engine)
            grip=next(d['handle']['at_m'] for d in spec['electrical']['devices'] if d['name']=='control')
            local=[grip[i]-initial['pose']['com_m'][i] for i in range(3)]
            yield engine,compiled,initial,local
        finally:engine.close()


def pulse(engine,local,sign,dt,seconds=.25):
    engine.op(op='pull',body='control handle',at=point(state(engine),local),force=[0,sign*8,0])
    advance(engine,seconds,dt)
    engine.op(op='pull',body='control handle',at=point(state(engine),local),force=[0,0,0])


class MechanicalSwitch(unittest.TestCase):
    def setUp(self):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE')=='required':self.fail('native engine required')
            self.skipTest('native engine unavailable')

    def test_manual_handle_is_loose_and_electrical_state_follows_its_measured_hinge(self):
        for closed in (False,True):
            spec=fixture(closed=closed);original=copy.deepcopy(spec)
            handle=next(p for p in spec['parts'] if p['name']=='control handle')
            self.assertFalse(handle['fixed']);self.assertEqual(handle['turn_deg'],[0,0,-25 if closed else 25])
            device=next(d for d in spec['electrical']['devices'] if d['name']=='control')
            self.assertEqual(device['hinge'],'control rocker hinge')
            self.assertEqual(device['closed_at_or_below_deg'],25 if closed else -25)
            # Contradict the initial boolean; physics must override it.
            device['closed']=not closed
            with opened(spec) as (engine,_,_,_):
                advance(engine,.1,1/240);_,switch,lamp=circuits(engine)
                self.assertEqual(switch['closed'],closed)
                self.assertGreater(lamp['power_w'],2) if closed else self.assertLess(abs(lamp['power_w']),1e-8)
                with self.assertRaisesRegex(ValueError,'worked by its hinge'):
                    engine.op(op='circuit_switch',circuit=1,branch='control',closed=not closed)
            original_device=next(d for d in original['electrical']['devices'] if d['name']=='control')
            self.assertEqual(original_device['closed'],closed)

    def test_real_up_down_forces_switch_and_friction_keeps_state_in_all_materials(self):
        for material in ('glass','oak','iron'):
            for dt in (1/240,1/480):
                with self.subTest(material=material,dt=dt),opened(fixture(material)) as (engine,_,initial,local):
                    advance(engine,1,dt)
                    self.assertLess(abs(angle(state(engine))),1e-4)
                    self.assertFalse(circuits(engine)[1]['closed'])
                    pulse(engine,local,-1,dt);advance(engine,1,dt)
                    self.assertTrue(circuits(engine)[1]['closed'])
                    self.assertGreater(circuits(engine)[2]['power_w'],2)
                    closed_angle=angle(state(engine))
                    self.assertAlmostEqual(closed_angle,math.radians(-50),delta=.001)
                    advance(engine,2,dt)
                    self.assertAlmostEqual(angle(state(engine)),closed_angle,delta=1e-4)
                    pulse(engine,local,1,dt);advance(engine,1,dt)
                    self.assertFalse(circuits(engine)[1]['closed'])
                    self.assertLess(abs(circuits(engine)[2]['power_w']),1e-8)
                    self.assertAlmostEqual(angle(state(engine)),0,delta=.001)
                    print('ROCKER ACTION',material,dt,'closed_rad',closed_angle,'pulls',engine.op(op='pulls')['pulls'])

    def test_paddle_geometry_and_measured_threshold_are_unchanged(self):
        fragment=e.switch('paddle',dict(mode='paddle',threshold_deg=5),{})
        self.assertEqual(len(fragment['parts']),2)
        self.assertEqual(fragment['parts'][1]['size_m'],[.36,.04,.16])
        self.assertEqual(fragment['joints'][0]['friction_n_m'],.002)
        self.assertEqual(fragment['electrical']['devices'][0]['closed_at_or_below_deg'],-5)
        self.assertNotIn('handle',fragment['electrical']['devices'][0])

    def test_retained_fixed_manual_declaration_is_still_readable(self):
        spec=fixture(closed=True)
        spec['parts']=[p for p in spec['parts'] if p['name'] not in ('control handle','control post','control axle')]
        spec['parts'].append(e.box('control handle',[.04,.15,0],[.04,.1,.04],'oak'))
        spec['joints']=[]
        device=next(d for d in spec['electrical']['devices'] if d['name']=='control')
        for key in ('hinge','closed_at_or_below_deg','handle'):device.pop(key)
        raw=json.dumps(spec,sort_keys=True)
        compiled=mw.compile_spec(spec)
        self.assertEqual(json.dumps(spec,sort_keys=True),raw)
        with tempfile.TemporaryDirectory() as logs:
            engine,_,_=mw.build_engine(ENGINE,compiled,Path(logs))
            try:
                advance(engine,.1,1/240)
                self.assertGreater(circuits(engine)[2]['power_w'],2)
            finally:engine.close()

    def test_pre_stop_work_material_mass_and_electrical_receipts_with_timestep_refinement(self):
        for material,density in [('glass',2500),('oak',700),('iron',7870)]:
            rows=[]
            for dt in (1/240,1/480):
                with self.subTest(material=material,dt=dt),opened(fixture(material)) as (engine,compiled,initial,local):
                    offsets=struct.unpack('<'+'d'*(len(base64.b64decode(initial['offsets_b64']))//8),
                        base64.b64decode(initial['offsets_b64']))
                    nodes=len(offsets)//3;cell=compiled['cell_m'];mass=nodes*cell**3*density
                    displayed=next(p for p in engine.first['bodies'] if p['name']=='control handle')['mass_kg']
                    self.assertAlmostEqual(displayed,mass,delta=5.1e-6)
                    # Authoritative lattice mass/inertia, including each cube's
                    # own inertia. Rotation is only about the z hinge.
                    inertia=sum(density*cell**3*(offsets[i]**2+offsets[i+1]**2+cell**2/6)
                                for i in range(0,len(offsets),3))
                    engine.op(op='pull',body='control handle',at=point(initial,local),force=[0,-8,0])
                    last=initial;work=0;last_increment=0
                    for _ in range(round(.025/dt)):
                        advance(engine,dt,dt);now=state(engine)
                        last_increment=-8*(point(now,local)[1]-point(last,local)[1])
                        work+=last_increment;last=now
                    self.assertLess(abs(angle(last)),math.radians(30),'audit must finish before the mechanical stop')
                    pose=last['pose'];velocity=pose['v_m_s'];omega=pose['w_rad_s'][2]
                    kinetic=.5*mass*sum(v*v for v in velocity)+.5*inertia*omega*omega
                    potential=mass*9.81*(pose['com_m'][1]-initial['pose']['com_m'][1])
                    friction=.08*abs(angle(last))
                    engine.op(op='pull',body='control handle',at=point(last,local),force=[0,0,0])
                    booked=engine.op(op='pulls')['pulls'][0]['work_j']
                    self.assertAlmostEqual(booked+last_increment,work,delta=5.1e-6)
                    ledger=circuits(engine)[0]['ledger'];store=engine.op(op='overloaded')['machines']['stores'][0]
                    self.assertAlmostEqual(store['given_j'],ledger['source_j'],delta=1e-8)
                    self.assertAlmostEqual(store['charge_j']+store['given_j'],1000,delta=1e-8)
                    self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
                    residual=work-kinetic-potential-friction
                    row=dict(material=material,dt_s=dt,cells=nodes,mass_kg=mass,external_work_j=work,
                        native_pull_booked_j=booked,unbooked_release_step_j=last_increment,
                        kinetic_j=kinetic,potential_delta_j=potential,hinge_friction_j=friction,
                        damping_and_numerical_residual_j=residual)
                    rows.append(row);print('ROCKER AUDIT',json.dumps(row))
            self.assertLessEqual(abs(rows[1]['damping_and_numerical_residual_j']),
                .7*abs(rows[0]['damping_and_numerical_residual_j'])+1e-5)


if __name__=='__main__':unittest.main()
