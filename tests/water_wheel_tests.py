"""Actual fluid/rigid backend gates; no visual expectation can replace native evidence."""
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import unittest

BINARY=Path(sys.argv.pop(1)).resolve()
ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=[]

def experiment(paddle='oak',water=True,offset=.36,dt=1/240,seconds=1.6):
    child=subprocess.Popen([str(BINARY),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def send(command):
        child.stdin.write(json.dumps(command)+'\n');child.stdin.flush()
        value=json.loads(child.stdout.readline())
        if not value['ok']:raise AssertionError(value.get('error'))
        return value
    try:
        initial=send(dict(op='create',experiment='water-wheel',paddle=paddle,water=water,offset_m=offset,dt_s=dt))['state']
        start=time.perf_counter();minimum_water=math.inf
        for _ in range(round(seconds/dt/4)):
            receipt=send(dict(op='advance',steps=4));final=receipt['state']
            for frame in receipt['frames']:
                for cell in frame['instances']:
                    if cell['material']=='water':minimum_water=min(minimum_water,cell['position_m'][1])
        child.stdin.write(json.dumps(dict(op='advance',steps=4))+'\n');child.stdin.flush()
        refused=json.loads(child.stdout.readline())
        if refused['ok'] or not refused['state']['report']['state_valid']:raise AssertionError('Duration refusal must preserve a valid final state')
        result=dict(paddle=paddle,water=water,offset_m=offset,dt_s=dt,wall_s=time.perf_counter()-start,
                    minimum_water_y_m=minimum_water if water else None,initial=initial,final=final)
        EVIDENCE.append(result);return result
    finally:
        child.terminate();child.wait(timeout=3);child.stdin.close();child.stdout.close()

class WaterWheelTests(unittest.TestCase):
    def test_declared_kernel_normalization_and_native_initial_density_energy(self):
        command=dict(op='create',experiment='water-wheel',paddle='oak',water=True,offset_m=.36)
        run=subprocess.run([str(BINARY),'--serve'],input=json.dumps(command)+'\n',capture_output=True,text=True,timeout=5)
        value=json.loads(run.stdout);self.assertTrue(value['ok'],value)
        s=value['state'];model=s['report']['fluid_model'];h=model['kernel_support_m'];rho0=model['density_kg_m3'];mass=rho0*model['particle_volume_m3'];c=model['sound_speed_m_s']
        def kernel(r):
            q=r/h
            return 0 if q>=1 else 21/(2*math.pi*h**3)*(1-q)**4*(1+4*q)
        n=1000;dr=h/n
        integral=dr/3*sum((1 if i in (0,n) else 4 if i%2 else 2)*4*math.pi*(i*dr)**2*kernel(i*dr) for i in range(n+1))
        self.assertAlmostEqual(integral,1,places=9)
        cells=[i for i in s['instances'] if i['material']=='water']
        density=[sum(mass*kernel(math.dist(a['position_m'],b['position_m'])) for b in cells) for a in cells]
        self.assertAlmostEqual(max(density),s['report']['maximum_density_kg_m3'],places=8)
        energy=sum(mass*c*c*(math.log(r/rho0)+rho0/r-1) for r in density if r>rho0)
        self.assertAlmostEqual(energy,s['report']['fluid_internal_energy_j'],places=8)

    def test_actual_fluid_contacts_turn_material_mass_wheels_and_keep_particles(self):
        for name in ('glass','oak','iron'):
            r=experiment(name);a,b=r['initial'],r['final'];report=b['report']
            self.assertTrue(report['state_valid'])
            self.assertEqual(report['water_particles'],80)
            self.assertAlmostEqual(report['water_mass_kg'],a['report']['water_mass_kg'],places=6)
            self.assertLess(r['minimum_water_y_m'],1,'Water must actually fall to the wheel')
            self.assertLess(report['wheel_angle_rad'],-.05,'Off-axis falling water must turn the unpowered wheel')
            self.assertGreater(report['wheel_kinetic_energy_j'],1e-5)
            self.assertGreater(report['water_wheel_contact_events'],0)
            self.assertLess(report['pair_force_residual_n'],1e-10)
            self.assertLess(report['pair_torque_residual_n_m'],1e-10)
            self.assertGreaterEqual(report['fluid_viscous_work_j'],0)
            self.assertFalse(b['qualification']['release_ready'])
            self.assertEqual(len(a['instances']),len(b['instances']))
            self.assertEqual([c['element_id'] for c in a['instances']],[c['element_id'] for c in b['instances']])
    def test_dry_and_missed_stream_controls_and_mirrored_contact_direction(self):
        dry=experiment(water=False)['final']['report']
        miss=experiment(offset=.95)['final']['report']
        mirror=experiment(offset=-.36)['final']['report']
        self.assertLess(abs(dry['wheel_angle_rad']),1e-4)
        self.assertLess(abs(miss['wheel_angle_rad']),1e-4)
        self.assertGreater(mirror['wheel_angle_rad'],.05)
    def test_host_cadence_retains_direction_and_mass_on_same_internal_clock(self):
        fine=experiment(dt=1/480)['final']['report']
        self.assertLess(fine['wheel_angle_rad'],-.05)
        self.assertAlmostEqual(fine['water_mass_kg'],80*.064,places=5)
        self.assertLess(fine['maximum_courant'],.5)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WaterWheelTests))
    (ROOT/'build/water-wheel-results.json').write_text(json.dumps(dict(integration_passed=result.wasSuccessful(),release_ready=False,experiments=EVIDENCE),indent=2))
    sys.exit(not result.wasSuccessful())
