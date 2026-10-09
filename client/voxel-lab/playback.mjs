// Presentation only: two accepted native states, bounded interpolation and
// no extrapolation. Topology/material/geometry changes snap to the new state.
// Vertical change of the original central quarter of a sheet's plan area.
// Follow stable cell ids through fracture; missing matter is not a zero dent.
export function sheetCenterHeightChange(initial,current){
  const sheet=initial?.cells.filter(c=>c.object===1)??[];
  if(!sheet.length||!current)return null;
  const bounds=[0,2].map(axis=>[Math.min(...sheet.map(c=>c.position_m[axis]-c.size_m[axis]/2)),Math.max(...sheet.map(c=>c.position_m[axis]+c.size_m[axis]/2))]);
  const cells=new Map(current.cells.map(c=>[c.id,c]));let change=0,volume=0;
  for(const before of sheet){
    if(![0,2].every((axis,i)=>Math.abs(before.position_m[axis]-(bounds[i][0]+bounds[i][1])/2)<=(bounds[i][1]-bounds[i][0])/4))continue;
    const after=cells.get(before.id);if(!after||after.object!==1)return null;
    const weight=before.size_m.reduce((a,b)=>a*b,1);
    change+=weight*(after.position_m[1]-before.position_m[1]);volume+=weight;
  }
  return volume>0?change/volume:null;
}
export class NativePlayback {
  constructor(){this.reset();}
  reset(state=null,now=0){this.previous=this.latest=state;this.arrived=now;this.duration=0;this.compatible=false;}
  push(state,now){
    if(!this.latest){this.reset(state,now);return true;}
    if(state.time_s<=this.latest.time_s)return false;
    const old=this.latest;
    this.compatible=old.cells.length===state.cells.length && old.events.length===state.events.length &&
      old.cells.every((a,i)=>{const b=state.cells[i];return a.id===b.id && a.component===b.component && a.material===b.material && a.mass_kg===b.mass_kg && a.fixed===b.fixed && a.size_m.every((x,j)=>x===b.size_m[j]);});
    this.previous=old;this.latest=state;this.duration=Math.max(16,Math.min(100,now-this.arrived));this.arrived=now;return true;
  }
  sample(now){
    if(!this.latest)return null;
    const alpha=this.compatible?Math.max(0,Math.min(1,(now-this.arrived)/this.duration)):1;
    return {from:this.previous,to:this.latest,alpha,time_s:this.previous.time_s+(this.latest.time_s-this.previous.time_s)*alpha};
  }
  get bufferedStates(){return this.latest?(this.previous===this.latest?1:2):0;}
}
