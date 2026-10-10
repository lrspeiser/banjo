// Accepted-state replay only. The renderer never solves or prescribes motion.
export function acceptedFrameIndex(frames,timeS){
  if(!Array.isArray(frames)||!frames.length||!Number.isFinite(timeS))throw Error('Invalid accepted replay');
  let low=0,high=frames.length-1;
  while(low<high){const mid=Math.ceil((low+high)/2);if(frames[mid].time_s<=timeS)low=mid;else high=mid-1;}
  return low;
}
export function mechanismMotionFrame(data,aspect=1){
  const g=data.geometry,r=Math.hypot(g.length_m,g.width_m,g.thickness_m)/2;
  const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
  for(const f of data.frames)for(let j=0;j<3;j++){lo[j]=Math.min(lo[j],f.com_m[j]-r);hi[j]=Math.max(hi[j],f.com_m[j]+r);}
  return {center:lo.map((v,j)=>(v+hi[j])/2),distance:Math.max(2,Math.hypot(...hi.map((v,j)=>(v-lo[j])/2))/Math.sin(Math.PI/8)*1.15*Math.max(1,1/aspect))};
}
export function verifyMechanismReceipt(data){
  if(data?.schema!=='banjo-mechanism-reference-1'||data.abi!==1||!Array.isArray(data.frames)||!data.frames.length)throw Error('Missing native mechanism receipt');
  if(!/^[a-f0-9]{64}$/.test(data.native_sha256)||!/^[a-f0-9]{64}$/.test(data.source_sha256))throw Error('Missing native identity');
  const g=data.geometry;
  if(!g||![g.length_m,g.width_m,g.thickness_m,g.density_kg_m3,data.mass_kg,data.audit?.accepted_time_s,data.audit?.dt_s].every(x=>Number.isFinite(x)&&x>0))throw Error('Invalid physical geometry/clock');
  const mass=g.length_m*g.width_m*g.thickness_m*g.density_kg_m3;
  if(Math.abs(mass-data.mass_kg)>1e-10*(1+mass))throw Error('Occupied geometry/mass mismatch');
  let previous=-1;
  for(const f of data.frames){
    if(!Number.isFinite(f.time_s)||f.time_s<=previous||f.time_s<0||f.time_s>data.audit.accepted_time_s+1e-10)throw Error('Invalid accepted frame time');
    if(f.body_id!=='mechanism-bar'||f.matter_id!=='mechanism-bar:occupied-box')throw Error('Matter identity changed');
    if(!['equilibrium-sleep','articulated-hinge','rigid-free'].includes(f.mode)||!Number.isFinite(f.angle_rad)||!Number.isFinite(f.omega_rad_s)||!Number.isFinite(f.energy_j))throw Error('Invalid mechanical state');
    if(![f.com_m,f.velocity_m_s].every(v=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite)))throw Error('Missing physical 3D trajectory');
    if(f.mode!=='rigid-free'){
      if(Math.abs(f.com_m[0]-.5*g.length_m*Math.sin(f.angle_rad))>1e-10||Math.abs(f.com_m[1]-(1.5-.5*g.length_m*Math.cos(f.angle_rad)))>1e-10)throw Error('Pinned pose disagrees with joint state');
    }
    if(f.mode==='equilibrium-sleep'&&(f.angle_rad!==0||f.omega_rad_s!==0))throw Error('Unqualified sleep with omitted vibration');
    previous=f.time_s;
  }
  if(Math.abs(previous-data.audit.accepted_time_s)>1e-10)throw Error('Replay does not reach accepted time');
  return data;
}
