"""Warmed CUDA candidate/phase timings. Not a physics or realtime certificate."""
import argparse,json,statistics,time
from pathlib import Path
import cupy as cp
from gpu_coupled_world import GpuCoupledWorld,source_hash
class MeasuredPhase:
    def __init__(self,kernel):self.kernel=kernel;self.events=[]
    def __call__(self,*a,**kw):
        start=cp.cuda.Event();end=cp.cuda.Event();start.record();self.kernel(*a,**kw);end.record();self.events.append((start,end))
    @property
    def attributes(self):return self.kernel.attributes
def main(args):
    rows=[]
    for material in ('glass','oak','iron','ice'):
        for pipeline in ('serial-reference','parallel'):
            w=GpuCoupledWorld(dict(material=material,pipeline=pipeline));e=w.eval
            original=e.bodies[:,14:20].reshape(-1);d=len(e.dynamic)
            candidates=cp.broadcast_to(original,(2*d,len(original))).copy();ids=cp.arange(d)
            epsilon=1e-12/e.active_weights;candidates[ids,e.dynamic]+=epsilon;candidates[d+ids,e.dynamic]-=epsilon
            if pipeline=='parallel':e.phases={name:MeasuredPhase(k) for name,k in e.phases.items()}
            for experiment in ('single','jacobian-full','jacobian-local'):
                if experiment=='jacobian-local' and pipeline!='parallel':continue
                def run():
                    return e.evaluate(original if experiment=='single' else candidates,1/960,
                        _jacobian_base=base if experiment=='jacobian-local' else None)
                base=e.evaluate(original,1/960);run();cp.cuda.get_current_stream().synchronize()
                gpu_ms=[];wall_ms=[];phase_ms={k:[] for k in e.phases}
                for _ in range(9):
                    if pipeline=='parallel':
                        for phase in e.phases.values():phase.events.clear()
                    start=cp.cuda.Event();end=cp.cuda.Event();wall=time.perf_counter();start.record();out=run();end.record();end.synchronize()
                    wall_ms.append(1000*(time.perf_counter()-wall));gpu_ms.append(cp.cuda.get_elapsed_time(start,end));assert not bool(cp.any(out['faults']))
                    if pipeline=='parallel':
                        for name,phase in e.phases.items():phase_ms[name].append(sum(cp.cuda.get_elapsed_time(a,b) for a,b in phase.events))
                rows.append(dict(material=material,pipeline=pipeline,experiment=experiment,candidates=1 if experiment=='single' else 2*d,
                    wall_median_ms=statistics.median(wall_ms),cuda_batch_median_ms=statistics.median(gpu_ms),
                    phase_median_ms={name:statistics.median(values) for name,values in phase_ms.items() if values},
                    attributes={name:kernel.attributes for name,kernel in e.phases.items()} if pipeline=='parallel' else e.kernel.attributes))
                print(material,pipeline,experiment,rows[-1]['wall_median_ms'],'ms',flush=True)
    result=dict(schema='banjo.cupy-pipeline-profile.v1',source_sha256=source_hash(),device=cp.cuda.runtime.getDeviceProperties(0)['name'].decode(),
        cuda_driver=cp.cuda.runtime.driverGetVersion(),repeats=9,rows=rows,realtime_qualified=False,
        scope='Warmed candidate equations; excludes Newton orchestration, accepted integration/audit, journals, gateway and rendering. CUDA batch time includes stream scheduling gaps; phase times measure device regions with event overhead.')
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);main(p.parse_args())
