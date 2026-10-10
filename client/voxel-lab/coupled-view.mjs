// Read-only geometry/flight observations. These never change simulated poses.
export function settingsDiffer(declaration,settings){return !declaration||Object.entries(settings).some(([key,value])=>declaration[key]!==value);}
export function remainingSteps(state){return state?Math.max(0,Math.round((2-state.time_s)/state.dt_s)):0;}
export function computePace(ratio){
  if(!Number.isFinite(ratio)||ratio<=0)return 'Not measured';
  if(ratio<1)return (1/ratio).toFixed(1)+'× slower than realtime';
  if(ratio===1)return 'Realtime';
  return ratio.toFixed(1)+'× faster than realtime';
}
// Native accepted-substep resultants, excluding gravity. Missing observations
// stay missing (e.g. a restored scene), rather than becoming fabricated zeros.
export function interactionLoads(frame){
  const rows=frame?.interaction_wrench_n_nm??frame?.substep_accounts?.at(-1)?.interaction_wrench_n_nm;
  if(!rows||rows.length!==frame.cells.length||rows.some(r=>!Array.isArray(r)||r.length!==6||r.some(v=>!Number.isFinite(v))))return null;
  return rows.map(r=>Math.hypot(...r.slice(0,3)));
}
export function loadColor(value,maximum){
  if(!Number.isFinite(value)||!Number.isFinite(maximum)||value<=0||maximum<=0)return [0.16,0.22,0.27];
  const t=Math.min(1,value/maximum);
  return t<=.5?[2*t,.5+t,1-2*t]:[1,2-2*t,0];
}
// Presentation of measured states only. Sampling drops redundant render frames,
// never creates a pose, advances physics, or extrapolates beyond delivered data.
export class AcceptedReplay {
  reset(initial){this.frames=initial?[initial]:[];this.latest=initial;this.time=initial?.time_s??0;this.clock=null;this.active=false;}
  constructor(){this.reset(null);}
  push(frame){
    if(!this.latest||frame.time_s<=this.latest.time_s)return;
    this.latest=frame;
    if(frame.time_s-this.frames.at(-1).time_s>=1/240-1e-10)this.frames.push(frame);
  }
  start(now){if(!this.frames.length)return;this.time=this.frames[0].time_s;this.clock=now;this.active=true;}
  stop(){this.active=false;}
  sample(now){
    if(!this.active)return null;
    this.time=Math.min(this.latest.time_s,this.time+Math.max(0,now-this.clock)/1000);this.clock=now;
    if(this.time>=this.latest.time_s)return this.latest;
    let lo=0,hi=this.frames.length;
    while(lo+1<hi){const mid=(lo+hi)>>1;if(this.frames[mid].time_s<=this.time)lo=mid;else hi=mid;}
    return this.frames[lo];
  }
}
function localPoint(point,cell) {
  const v=point.map((x,i)=>x-cell.position_m[i]),[w,x,y,z]=cell.quaternion_wxyz;
  const q=[-x,-y,-z],t=[2*(q[1]*v[2]-q[2]*v[1]),2*(q[2]*v[0]-q[0]*v[2]),2*(q[0]*v[1]-q[1]*v[0])];
  return [v[0]+w*t[0]+q[1]*t[2]-q[2]*t[1],v[1]+w*t[1]+q[2]*t[0]-q[0]*t[2],v[2]+w*t[2]+q[0]*t[1]-q[1]*t[0]];
}
export function ballObservation(state) {
  const ball=state.cells.find(c=>c.shape==='sphere');
  if(!ball)return null;
  let gap=Infinity,hit=null;
  for(const cell of state.cells) {
    if(cell===ball)continue;
    let distance;
    if(cell.shape==='plane')distance=ball.position_m[1]-cell.position_m[1];
    else if(cell.shape==='cube') {
      const d=localPoint(ball.position_m,cell).map((x,i)=>Math.abs(x)-cell.size_m[i]/2);
      distance=Math.hypot(...d.map(x=>Math.max(0,x)))+Math.min(0,Math.max(...d));
    } else continue;
    distance-=ball.radius_m;
    if(distance<gap){gap=distance;hit=cell;}
  }
  const down=-ball.velocity_m_s[1];
  return {ball,target:hit,gap_m:gap,down_m_s:down,contact:gap<=0,
    gravity_estimate_s:gap>0&&Number.isFinite(gap)?(-down+Math.sqrt(down*down+2*9.81*gap))/9.81:0};
}
export function cameraFrame(cells,mode) {
  // Include the ground in Full drop even when the ball is the only finite
  // object; otherwise overview becomes another close-up of the ball.
  let selected=mode==='ball'?cells.filter(c=>c.shape==='sphere'):cells.filter(c=>mode==='overview'||(c.shape!=='plane'&&c.shape!=='sphere'));
  if(!selected.length)selected=cells.filter(c=>c.shape==='plane');
  const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
  for(const cell of selected) {
    const r=cell.shape==='sphere'?cell.radius_m:cell.shape==='plane'?.15:Math.hypot(...cell.size_m)/2;
    cell.position_m.forEach((x,i)=>{lo[i]=Math.min(lo[i],x-r);hi[i]=Math.max(hi[i],x+r);});
  }
  const center=lo.map((x,i)=>(x+hi[i])/2),bound=Math.hypot(...hi.map((x,i)=>(x-lo[i])/2));
  return {center,radius:Math.max(mode==='ball'?.04:.08,bound/Math.sin(20*Math.PI/180)*1.15)};
}
export function dropMilestones(initial,state,impact){
  if(!initial||!state)return {before:'Not set up',contact:'Not calculated',after:'Not calculated'};
  const start=ballObservation(initial),now=ballObservation(state);
  return {before:start.gap_m.toFixed(2)+' m above target',
    contact:impact?'Observed at '+impact.time_s.toFixed(4)+' s':'Not observed',
    after:impact?(now.down_m_s<0?'Rebounding · '+(-now.down_m_s).toFixed(2)+' m/s':now.contact?'In contact':'Contact recorded · '+state.time_s.toFixed(3)+' s'):'Not reached'};
}
