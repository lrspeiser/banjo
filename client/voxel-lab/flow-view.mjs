// Observation only; physical evolution belongs to the native flow owner.
export function scalar(cell,mode,density,gravity=9.81){
  if(!Array.isArray(cell)||cell.length!==3||cell.some(v=>!Number.isFinite(v))||cell[0]<0||!Number.isFinite(density)||density<=0||!Number.isFinite(gravity)||gravity<0)throw Error('Invalid accepted flow observation');
  if(mode==='depth')return cell[0];
  if(mode==='pressure')return density*gravity*cell[0];
  if(mode==='speed')return cell[0]>0?Math.hypot(cell[1],cell[2])/cell[0]:0;
  throw Error('Unknown flow observation');
}
export function columnTransform(index,nx,nz,dx,depth){
  if(!Number.isInteger(index)||index<0||index>=nx*nz||!Number.isFinite(depth)||depth<0)throw Error('Invalid flow column');
  return {position:[(index%nx+.5-nx/2)*dx,depth/2,(Math.floor(index/nx)+.5-nz/2)*dx],scale:[depth>1e-7?1:0,Math.max(depth,1e-7),depth>1e-7?1:0]};
}
export function frameAtTime(frames,time,start=0){
  if(!frames.length||!Number.isFinite(time))throw Error('Missing accepted flow clock');
  let index=Math.max(0,Math.min(start,frames.length-1));
  while(index>0&&frames[index].account.time_s>time)index--;
  while(index+1<frames.length&&frames[index+1].account.time_s<=time)index++;
  return index; // hold final accepted state; no future extrapolation
}
