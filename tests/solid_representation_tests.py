"""Occupied geometry, analytical mechanics, retained-state and HTTP oracles.

No contact/deformation qualification: the reference deliberately refuses it.
"""
import argparse
import copy
import importlib.util
import json
import math
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import solid_representation as solid
from object_registry import canonical,digest


def refused(fn):
    try: fn()
    except (ValueError,TypeError,KeyError):return
    raise AssertionError('Unsupported input admitted')


def geometry():
    measured=[]
    for level in (2,3,4):
        d=solid.compile_ball(.05,'glass',level);cells=d['cells'];p=d['mass_properties'];r=.05;delta=d['geometry']['boundary_distance_bound_m']
        volume=math.fsum((2*c['half_size_m'][0])**3 for c in cells);rho=2500
        # The registry sums up to 4096 FP64 terms in reference order. This
        # analytical fsum oracle permits accumulated roundoff, not lost volume.
        assert math.isclose(p['volume_m3'],volume,rel_tol=2e-13,abs_tol=1e-19)
        assert 4*math.pi*max(0,r-delta)**3/3<=volume<=4*math.pi*(r+delta)**3/3
        # Independent cube + parallel-axis tensor about the symmetry origin.
        tensor=np.zeros((3,3));sizes=set()
        for c in cells:
            h=c['half_size_m'][0];m=rho*(2*h)**3;x,y,z=c['reference_position_m'];sizes.add(h)
            tensor+=m*np.array([[2*h*h/3+y*y+z*z,-x*y,-x*z],[-x*y,2*h*h/3+x*x+z*z,-y*z],[-x*z,-y*z,2*h*h/3+x*x+y*y]])
            assert np.linalg.norm(np.abs(c['reference_position_m'])+h)<=r+delta+1e-16
        assert np.allclose(p['inertia_kg_m2'],tensor,rtol=2e-14,atol=1e-17)
        assert np.linalg.norm(p['center_of_mass_m'])<1e-16
        # Shared faces may connect unequal leaves, but never span air.
        lookup={c['id']:c for c in cells}
        for f in d['interfaces']:
            a,b=lookup[f['a']],lookup[f['b']];ha=a['half_size_m'][0];hb=b['half_size_m'][0];axis=f['axis']
            assert abs(abs(a['reference_position_m'][axis]-b['reference_position_m'][axis])-ha-hb)<1e-16
            area=1.
            for j in range(3):
                if j!=axis:area*=min(a['reference_position_m'][j]+ha,b['reference_position_m'][j]+hb)-max(a['reference_position_m'][j]-ha,b['reference_position_m'][j]-hb)
            assert area>0 and abs(area-f['area_m2'])<1e-17 and f['solver_binding'] is None
        measured.append(dict(level=level,elements=len(cells),interfaces=len(d['interfaces']),cell_sizes_m=sorted(sizes),mass_kg=p['mass_kg'],
            relative_volume_error=(volume-4*math.pi*r**3/3)/(4*math.pi*r**3/3),relative_inertia_error=(tensor[0,0]-.4*rho*4*math.pi*r**5/3)/(.4*rho*4*math.pi*r**5/3)))
    assert abs(measured[-1]['relative_volume_error'])<abs(measured[0]['relative_volume_error'])
    # Center occupancy is not monotone: coarse inertia happens to be close.
    # Refinement must improve the medium case; retain every measured error.
    assert abs(measured[-1]['relative_inertia_error'])<abs(measured[1]['relative_inertia_error'])
    assert len(measured[-1]['cell_sizes_m'])>1
    # Oversized requests refuse instead of secretly coarsening or changing mass.
    for args in ((.05,'glass',5),(.05,'unknown',3),(.05,'glass',True),(float('nan'),'glass',3)):
        refused(lambda:solid.compile_ball(*args))
    return measured


def transfers():
    cases=[]
    for material in ('glass','oak','iron','ice'):
        d=solid.compile_ball(.05,material,3)
        q=[math.cos(.6),math.sin(.6)/math.sqrt(3),math.sin(.6)/math.sqrt(3),math.sin(.6)/math.sqrt(3)]
        state=solid.initial_state(d,position=[3,8,-2],orientation=q,velocity=[.5,-4,2],spin=[2,-3,1])
        # Retained history is a transfer fixture, not a constitutive loading run.
        state['interfaces'][0]['history'][6]=.4;state['interfaces'][0]['history'][10]=.002
        state['retained_fields']={'temperature_kelvin':[300.,301.], 'species_mass_kg':{'test-species':.001}}
        pristine=canonical(state);rigid,receipt=solid.collapse(d,state);restored=solid.expand(d,rigid)
        assert restored['instance_id']==rigid['instance_id']==state['instance_id']!=solid.initial_state(d)['instance_id']
        assert canonical(state)==pristine and restored['interfaces']==state['interfaces'] and restored['retained_fields']==state['retained_fields']
        for a,b in zip(state['cells'],restored['cells']):
            for k in ('position_m','velocity_m_s','spin_rad_s','quaternion_wxyz'):assert np.allclose(a[k],b[k],rtol=0,atol=2e-14),k
        before=solid.mechanics(d,state,gravity=[.3,-9.81,-.4]);duration=.125
        flown=solid.free_flight(d,rigid,duration,gravity=[.3,-9.81,-.4]);after=solid.mechanics(d,solid.expand(d,flown),gravity=[.3,-9.81,-.4])
        m=before['mass_kg'];g=np.array([.3,-9.81,-.4]);c=np.array(before['center_m']);v=np.array(rigid['velocity_m_s'])
        impulse=m*g*duration;torque=np.cross(c*duration+.5*v*duration**2,m*g)
        assert np.linalg.norm(np.array(after['momentum_n_s'])-before['momentum_n_s']-impulse)<2e-11
        assert np.linalg.norm(np.array(after['angular_momentum_n_m_s'])-before['angular_momentum_n_m_s']-torque)<2e-10
        assert abs(after['kinetic_j']+after['gravity_j']-before['kinetic_j']-before['gravity_j'])<2e-10
        # Current geometry is retained, not regenerated from the intact recipe.
        modified=copy.deepcopy(state);modified['cells'][0]['position_m'][0]+=.001
        for cell in modified['cells']:cell['velocity_m_s']=[0.,0.,0.];cell['spin_rad_s']=[0.,0.,0.]
        changed,_=solid.collapse(d,modified);again=solid.expand(d,changed)
        assert np.allclose(again['cells'][0]['position_m'],modified['cells'][0]['position_m'],atol=1e-14)
        changed['spin_rad_s']=[0.,2.,0.];refused(lambda:solid.free_flight(d,changed,.1))
        cases.append(dict(material=material,density_kg_m3=d['material_profile']['density_kg_m3'],young_pa=d['material_profile']['young_pa'],
            mass_kg=m,transfer=receipt,dt_s=duration,flight_energy_residual_j=after['kinetic_j']+after['gravity_j']-before['kinetic_j']-before['gravity_j'],
            retained_history_and_fields=True,scope='Mapping/analytical mechanics only; declared stiffness does not implement internal forces'))
    d=solid.compile_ball(.05,'glass',2);state=solid.initial_state(d)
    for change in (lambda s:s.update(elastic_energy_j=1e-4),lambda s:s['cells'][0]['velocity_m_s'].__setitem__(0,1.),lambda s:s['interfaces'][0].update(active=False),lambda s:s['cells'].pop()):
        bad=copy.deepcopy(state);change(bad);saved=canonical(bad);refused(lambda:solid.collapse(d,bad));assert canonical(bad)==saved
    rigid,_=solid.collapse(d,state);bad=copy.deepcopy(rigid);bad['mass_kg']*=2;refused(lambda:solid.expand(d,bad));bad=copy.deepcopy(rigid);bad['cells'].pop();refused(lambda:solid.expand(d,bad))
    altered=copy.deepcopy(d);altered['material_profile']['density_kg_m3']*=2;refused(lambda:solid.initial_state(altered))
    altered['definition_sha256']=digest({k:v for k,v in altered.items() if k!='definition_sha256'});refused(lambda:solid.initial_state(altered))
    return cases


def drops():
    runs=[]
    for material in ('glass','oak','iron','ice'):
        r=solid.experiment(dict(material=material,radius_m=.05,level=3,height_m=10,frames=12));d=r['definition'];t=r['measured']['physical_s'];before=r['rigid_states'][0];after=r['rigid_states'][-1]
        assert abs(after['position_m'][1]-(before['position_m'][1]-.5*9.81*t*t))<2e-14
        assert abs(after['velocity_m_s'][1]+9.81*t)<2e-14
        assert np.linalg.norm(r['measured']['momentum_residual_n_s'])<2e-11 and np.linalg.norm(r['measured']['angular_residual_n_m_s'])<2e-11 and abs(r['measured']['energy_residual_j'])<2e-10
        assert r['initial']['interfaces']==r['final']['interfaces'] and len(r['final']['cells'])==len(d['cells'])
        bound=max(np.linalg.norm(c['reference_position_m'])+np.linalg.norm(c['half_size_m']) for c in d['cells'])
        assert after['position_m'][1]-bound>=.2-1e-14
        runs.append(dict(material=material,elements=len(d['cells']),interfaces=len(d['interfaces']),**r['measured']))
    zero=solid.experiment(dict(height_m=.2,level=2,frames=1));assert zero['measured']['physical_s']==0 and zero['initial']['instance_id']==zero['final']['instance_id']
    return runs


def gateway(native):
    spec=importlib.util.spec_from_file_location('solid_gateway',ROOT/'scripts/voxel-lab.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    with tempfile.TemporaryDirectory() as temp:
        server=m.Server(('127.0.0.1',0),native,Path(temp));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url='http://127.0.0.1:'+str(server.server_port)
        def request(data,origin=None):
            body=json.dumps(data).encode();headers={'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            return urllib.request.urlopen(urllib.request.Request(url+'/api/representation',data=body,headers=headers),timeout=20)
        try:
            page=urllib.request.urlopen(url+'/representations').read().decode();assert 'No contact or fracture solver' in page and 'id="view"' in page
            script=urllib.request.urlopen(url+'/representations.js').read().decode();assert '/three.module.js' in script
            response=request({'declaration':{'material':'iron','level':2,'frames':3}});r=json.load(response)
            assert r['ok'] and r['source_sha256']==solid.source_hash() and r['compiler_binding'].startswith('reference-only')
            for data,origin in (({'declaration':{'level':5}},None),({'declaration':{'fracture':True}},None),({'declaration':{}},'https://foreign.example')):
                try:request(data,origin);raise AssertionError('Bad request admitted')
                except urllib.error.HTTPError as e:assert e.code==400 and not json.load(e)['ok']
            assert not server.sessions
        finally:server.shutdown();thread.join();server.server_close()
    return {'actual_http_compiler':True,'cross_origin_and_unknown_law_refused':True,'no_gpu_or_native_session_mutation':True}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--native',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=dict(source_sha256=solid.source_hash(),geometry=geometry(),transfers=transfers(),drops=drops(),gateway=gateway(a.native.resolve(strict=True)),
        scope='CPU occupied geometry/conservative transfer/uniform-gravity reference. Internal/contact/field solvers and full realtime remain open.')
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
