"""Native emergent mechanics and declared open-air load accounting."""
import copy
import json
import math
import os
import sys
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import machine_game as mg
import machine_world as mw
import sandbox_motion as sm
ENGINE=Path(os.environ.get('BANJO_LIVE_ENGINE',ROOT/'build/agent-msvc-test2/Release/banjo_live_world_run.exe'))
if '--engine' in sys.argv:
    i=sys.argv.index('--engine');ENGINE=Path(sys.argv[i+1]);del sys.argv[i:i+2]

def assembled(example,changes=None):
    example=copy.deepcopy(example)
    if changes:example['placements'][0].update(changes)
    return mg.compose(dict(mg.free_build(),machine=example['base'],custom_base=True),example['placements'])[0]

def example(name):return next(t for t in sm.TEMPLATES if t['name']==name)

class Declaration(unittest.TestCase):
    def test_all_examples_compile_and_all_materials_have_same_geometry(self):
        for t in sm.TEMPLATES:mw.compile_spec(assembled(t))
        for piece,builder in sm.PIECES.items():
            if piece in ('wind','dominoes'):continue
            row=next(r for r in sm.TRAY if r['piece']==piece)
            for material in sm.MATERIALS:
                knobs={k:v['default'] for k,v in row['knobs'].items()};knobs['material']=material
                spec=sm.base(piece);spec.update(builder('test '+piece,knobs,{}));mw.compile_spec(spec)

    def test_airflow_follows_edit_and_is_pruned_on_remove(self):
        import sandbox_edit as edit
        spec=sm.base('Air');spec.update(sm.wind('source',{},{}))
        obj=edit.objects(spec)[0]
        moved,_,compiled=edit.edit(spec,obj['id'],[.2,0,.3])
        self.assertEqual(compiled['airflows'][0]['center_m'],[.2,.8,.3])
        removed,_,compiled=edit.edit(moved,obj['id'],remove=True)
        self.assertEqual(compiled['airflows'],[])

    def test_overlapping_airfields_are_refused(self):
        spec=sm.base('Air');spec.update(sm.wind('source',{},{}))
        other=sm.wind('second',dict(x_m=.3),{})
        spec['parts']+=other['parts'];spec['airflows']+=other['airflows']
        with self.assertRaises(mw.MachineRefused):mw.compile_spec(spec)

class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE')=='required':raise AssertionError('native engine is required')
            raise unittest.SkipTest('native engine unavailable')

    def run_spec(self,spec,seconds=1,dt=1/240):
        with tempfile.TemporaryDirectory() as td:
            engine,_,_=mw.build_engine(ENGINE,mw.compile_spec(spec),td)
            try:
                first=engine.first;frames=[];start=time.perf_counter()
                for _ in range(round(seconds/dt)):
                    frames.append(engine.op(op='step',dt=dt,n=1,moved=False))
                return first,frames,engine.op(op='joints'),engine.op(op='airflow_loads'),time.perf_counter()-start
            finally:engine.close()

    def test_domino_contact_chain_stops_when_spacing_is_too_wide(self):
        for mat in sm.MATERIALS:
            good=assembled(example('Domino chain'),dict(material=mat))
            _,frames,_,_,_=self.run_spec(good,2)
            last=next(b for b in frames[-1]['bodies'] if b['name']=='your dominoes 1 6')
            self.assertLess(last['position_m'][1],.09,mat)
            bad=assembled(example('Domino chain'),dict(material=mat,spacing_m=.4))
            _,frames,_,_,_=self.run_spec(bad,2)
            last=next(b for b in frames[-1]['bodies'] if b['name']=='your dominoes 1 6')
            self.assertGreater(last['position_m'][1],.10,mat)

    def test_hinged_door_responds_to_wind_and_zero_air_does_not_open_it(self):
        for mat in sm.MATERIALS:
            spec=assembled(example('Wind opens a door'),dict(material=mat))
            _,_,joints,loads,_=self.run_spec(spec,1)
            angle=joints['joints'][0]['degrees']
            self.assertGreater(abs(angle),5,mat)
            self.assertGreater(sum(p['work_j'] for p in loads['loads']),0)
            spec['airflows'][0]['velocity_m_s']=[0,0,0]
            _,_,joints,_,_=self.run_spec(spec,1)
            self.assertLess(abs(joints['joints'][0]['degrees']),.2,mat)

    def test_trampoline_deck_compresses_and_ball_rebounds_without_kick(self):
        spec=assembled(example('Spring trampoline'))
        first,frames,_,_,_=self.run_spec(spec,2)
        heights=[next(b for b in f['bodies'] if b['name']=='your marble 2')['position_m'][1] for f in frames]
        deck=[next(b for b in f['bodies'] if b['name']=='your trampoline 1 deck')['position_m'][1] for f in frames]
        hit=next(i for i in range(1,len(heights)-1) if heights[i]<heights[i-1] and heights[i+1]>heights[i] and i>60)
        self.assertLess(min(deck),.39)
        self.assertGreater(max(heights[hit:]),heights[hit]+.08)
        self.assertLess(max(heights[hit:]),1.21)

    def test_pendulum_strikes_block_and_trapdoor_respects_bearing_resistance(self):
        for mat in sm.MATERIALS:
            spec=assembled(example('Pendulum and blocks'),dict(material=mat))
            _,frames,_,_,_=self.run_spec(spec,1.2)
            block=next(b for b in frames[-1]['bodies'] if b['name']=='your loose_block 2')
            self.assertGreater(abs(block['position_m'][0]+.2),.03,mat)
            spec=assembled(example('Gravity trapdoor'),dict(material=mat))
            _,_,j,_,_=self.run_spec(spec,.5)
            self.assertGreater(abs(j['joints'][0]['degrees']),10,mat)
        spec=assembled(example('Gravity trapdoor'),dict(friction_n_m=20))
        _,_,j,_,_=self.run_spec(spec,.5)
        self.assertLess(abs(j['joints'][0]['degrees']),1)

    def test_flywheel_requires_closed_wires_and_native_saved_wind_continues(self):
        spec=assembled(example('Flywheel workbench'))
        _,_,j,_,_=self.run_spec(spec,.5)
        self.assertGreater(abs(j['joints'][0]['degrees']),2)
        spec['electrical']['wires'].pop()
        _,_,j,_,_=self.run_spec(spec,.5)
        self.assertLess(abs(j['joints'][0]['degrees']),.2)
        spec=assembled(example('Wind opens a door'))
        with tempfile.TemporaryDirectory() as td:
            e,_,_=mw.build_engine(ENGINE,mw.compile_spec(spec),td)
            try:
                e.op(op='step',dt=1/240,n=24,moved=False)
                saved=e.op(op='snapshot')['snapshot']
                path=Path(td)/'saved.json';path.write_text(json.dumps(saved),encoding='utf-8')
                expected=e.op(op='step',dt=1/240,n=12,moved=False)
                expected_load=e.op(op='airflow_loads')
                with subprocess.Popen([str(ENGINE),'--scene',str(e.scene_path),'--cell','.02','--snapshot',str(path)],
                                      stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) as p:
                    opening=json.loads(p.stdout.readline());self.assertTrue(opening['ok'])
                    def op(**args):p.stdin.write(json.dumps(args)+'\n');p.stdin.flush();return json.loads(p.stdout.readline())
                    actual=op(op='step',dt=1/240,n=12,moved=False)
                    loads=op(op='airflow_loads')
                    for a,b in zip(actual['bodies'],expected['bodies']):
                        for x,y in zip(a['position_m'],b['position_m']):self.assertAlmostEqual(x,y,places=4)
                    self.assertAlmostEqual(sum(a['work_j'] for a in loads['loads']),sum(a['work_j'] for a in expected_load['loads']),places=4)
                    op(op='poses');p.stdin.write('{"op":"quit"}\n');p.stdin.flush();p.wait(timeout=5)
            finally:e.close()

    def test_airflow_mass_momentum_external_work_and_dt_residuals(self):
        results=[]
        for material,density in [('oak',700),('glass',2500),('iron',7870)]:
            for dt in [1/240,1/480]:
                spec=sm.base('Air audit')
                spec['parts']=[sm.box('arbitrary name',[.2]*3,[0,2,0],material,False),sm.box('source',[.1]*3,[-1,.05,0],'iron')]
                spec['airflows']=[dict(name='external air',**{'in':'source'},center_m=[0,2,0],size_m=[6,4,4],velocity_m_s=[8,0,0])]
                with tempfile.TemporaryDirectory() as td:
                    engine,_,_=mw.build_engine(ENGINE,mw.compile_spec(spec),td)
                    try:
                        b=next(b for b in engine.first['bodies'] if b['name']=='arbitrary name');mass=b['mass_kg'];y0=b['position_m'][1]
                        self.assertAlmostEqual(mass,density*.008,delta=density*.008*.001)
                        impulse=[0,0,0];damping_impulse=[0,0,0];damping_loss=numerical_loss=0;last=b;started=time.perf_counter()
                        for _ in range(round(.2/dt)):
                            f=engine.op(op='step',dt=dt,n=1,moved=False)
                            load=next(p for p in engine.op(op='airflow_loads')['loads'] if p['body']=='arbitrary name')
                            for i in range(3):impulse[i]+=load['force_n'][i]*dt
                            previous=last
                            last=next(b for b in f['bodies'] if b['name']=='arbitrary name')
                            # Existing cuboid solver drag is 0.02/s, separate
                            # from the new area/relative-speed air load.
                            keep=1-.02*dt
                            for i in range(3):damping_impulse[i]+=mass*(1-1/keep)*last['velocity_m_s'][i]
                            damping_loss+=mass*(1/keep-1)*sum(v*v for v in last['velocity_m_s'])
                            numerical_loss+=.5*mass*sum((a-b)**2 for a,b in zip(last['velocity_m_s'],previous['velocity_m_s']))
                        v=last['velocity_m_s'];y=last['position_m'][1]
                        momentum=[mass*v[i]-impulse[i]-damping_impulse[i]-(0 if i!=1 else -mass*9.81*.2) for i in range(3)]
                        energy=.5*mass*sum(a*a for a in v)+mass*9.81*(y-y0)-load['work_j']
                        result=dict(material=material,dt_s=dt,cell_m=.02,mass_kg=mass,external_work_j=load['work_j'],background_drag_loss_j=damping_loss,numerical_loss_j=numerical_loss,momentum_residual_n_s=momentum,energy_residual_j=energy,closed_residual_j=energy+damping_loss+numerical_loss,wall_s=time.perf_counter()-started)
                        results.append(result)
                        self.assertLess(max(abs(a) for a in momentum),.02)
                        self.assertLess(abs(result['closed_residual_j']),mass*.0001)
                    finally:engine.close()
        print('AIRFLOW_AUDIT '+json.dumps(results),flush=True)

if __name__=='__main__':unittest.main()
