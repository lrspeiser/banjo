"""Compare native CPU batch outputs with the retained serial CUDA evaluator."""
import argparse,os,sys,json
from pathlib import Path
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from cpu_coupled_world import CpuCoupledWorld,implementation_hash
from gpu_coupled_world import GpuCoupledWorld,source_hash
p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(a.library.resolve());rows=[];rng=np.random.default_rng(4367)
for material in ('glass','oak','iron','ice'):
    c=CpuCoupledWorld(dict(material=material,height_m=.001,dt_s=1/240));g=GpuCoupledWorld(dict(material=material,height_m=.001,dt_s=1/240,pipeline='serial-reference'))
    v=rng.normal(size=(8,c.eval.n,6))*1e-6;v[:,c.eval.bodies[:,1]==0,:]=0
    cpu=c.eval.evaluate(v,1/960);gpu=g.eval.evaluate(cp.asarray(v),1/960);maximum=0.
    assert np.array_equal(cpu['faults'],cp.asnumpy(gpu['faults']))
    for field in ('poses','residual','history','forces','ledger'):
        expected=cp.asnumpy(gpu[field]);actual=cpu[field]
        maximum=max(maximum,float(np.max(abs(actual-expected)/np.maximum(1.,abs(expected)),initial=0)))
        # Existing independent CPU/CUDA oracle tolerance; unchanged.
        assert np.allclose(actual,expected,rtol=2e-10,atol=2e-10),(material,field,maximum)
    for phase in (.25,.0625):
        x=c.eval.contact_schedule(1/240,phase);y=g.eval.contact_schedule(1/240,phase)
        assert x['pair']==y['pair']
        for field in ('step_s','frequency_rad_s','excitation_m_s'):assert np.isclose(x[field],y[field],rtol=2e-10,atol=2e-10)
    rows.append(dict(material=material,candidates=8,max_scaled_difference=maximum));print(material,maximum,flush=True)
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(dict(cpu_implementation=implementation_hash(),cuda_source=source_hash(),comparisons=rows),indent=2)+'\n',encoding='utf-8')
print('PASS same four-material private trials and contact scheduling on CPU/CUDA',flush=True)
