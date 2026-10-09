// Read-only geometry/flight observations. These never change simulated poses.
export function settingsDiffer(declaration,settings){return !declaration||Object.entries(settings).some(([key,value])=>declaration[key]!==value);}
export function remainingSteps(state){return state?Math.max(0,Math.round((2-state.time_s)/state.dt_s)):0;}
export function computePace(ratio){
  if(!Number.isFinite(ratio)||ratio<=0)return 'Not measured';
  if(ratio<1)return (1/ratio).toFixed(1)+'× slower than realtime';
  if(ratio===1)return 'Realtime';
  return ratio.toFixed(1)+'× faster than realtime';
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
  let selected=mode==='ball'?cells.filter(c=>c.shape==='sphere'):cells.filter(c=>c.shape!=='plane'&&(mode==='overview'||c.shape!=='sphere'));
  if(!selected.length)selected=cells.filter(c=>c.shape==='plane');
  const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
  for(const cell of selected) {
    const r=cell.shape==='sphere'?cell.radius_m:cell.shape==='plane'?.15:Math.hypot(...cell.size_m)/2;
    cell.position_m.forEach((x,i)=>{lo[i]=Math.min(lo[i],x-r);hi[i]=Math.max(hi[i],x+r);});
  }
  const center=lo.map((x,i)=>(x+hi[i])/2),bound=Math.hypot(...hi.map((x,i)=>(x-lo[i])/2));
  return {center,radius:Math.max(mode==='ball'?.04:.08,bound/Math.sin(20*Math.PI/180)*1.15)};
}
