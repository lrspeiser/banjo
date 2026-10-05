// Presentation only. Run order is terrain::RunKind; colors never select a law
// or promise a collectible material. Samples use the same identity as terrain.
export const GROUND_APPEARANCE = Object.freeze([
  {name:"rock", color:"8996a6", pattern:"fractures"},
  {name:"soil", color:"875132", pattern:"mottled"},
  {name:"sand", color:"e2c77b", pattern:"speckle"},
  {name:"loose soil", color:"a36a43", pattern:"mottled"},
  {name:"weathered rock", color:"aaa58c", pattern:"fractures"},
  {name:"clay", color:"a46684", pattern:"bands"},
  {name:"copper ore", color:"638c72", pattern:"inclusions"},
  {name:"oxidised copper ore", color:"b97038", pattern:"inclusions"},
].map(Object.freeze));

const samples = new Map(GROUND_APPEARANCE.map(row => [row.name, row]));
samples.set("ore",GROUND_APPEARANCE[6]);
samples.set("oxidised ore",GROUND_APPEARANCE[7]);
export function materialAppearance(name) {
  return samples.get(String(name || "").toLowerCase()) || null;
}

// Grid origin is a column CENTER, shared with the collider and native survey.
// The +half-cell boundary is deliberately owned by the next column.
export function terrainCellAt(x, z, grid) {
  const i = Math.floor((x-grid.x0)/grid.dx+.5);
  const j = Math.floor((z-grid.z0)/grid.dx+.5);
  return i>=0 && j>=0 && i<grid.nx && j<grid.nz ? j*grid.nx+i : -1;
}

export function columnTopData(grid, heights, colors) {
  const count=grid.nx*grid.nz,positions=new Float32Array(12*count),paint=new Float32Array(12*count);
  const indices=new Uint32Array(6*count),half=grid.dx/2;
  for(let c=0;c<count;c++) {
    const x=grid.x0+(c%grid.nx)*grid.dx,z=grid.z0+Math.floor(c/grid.nx)*grid.dx,y=heights[c];
    positions.set([x-half,y,z-half,x-half,y,z+half,x+half,y,z+half,x+half,y,z-half],12*c);
    for(let v=0;v<4;v++)paint.set(colors.subarray(3*c,3*c+3),12*c+3*v);
    indices.set([4*c,4*c+1,4*c+2,4*c,4*c+2,4*c+3],6*c);
  }
  return {positions,colors:paint,indices};
}

// Boundary of the layered-column union, including voids. Heights are native
// float32; packed internal layer boundaries retain their declared 1 mm wire
// precision. Material bands subdivide faces without inventing solid volumes.
export function columnChunkBox(grid,id,size=32) {
  const across=Math.ceil(grid.nx/size),i0=id%across*size,j0=Math.floor(id/across)*size;
  return [i0,j0,Math.min(size,grid.nx-i0),Math.min(size,grid.nz-j0)];
}

// Geometry depends on the edited column and its immediate neighbors. Color
// changes need only their own chunks. Rendering chunk size is independent of
// the native collider's chunk ownership and does not change material cells.
export function columnChunkIds(grid,box=[0,0,grid.nx,grid.nz],halo=1,size=32) {
  const [i,j,ni,nj]=box,ids=new Set();if(ni<=0 || nj<=0)return ids;
  const across=Math.ceil(grid.nx/size);
  for(let z=Math.floor(Math.max(0,j-halo)/size);z<=Math.floor(Math.min(grid.nz-1,j+nj-1+halo)/size);z++)
    for(let x=Math.floor(Math.max(0,i-halo)/size);x<=Math.floor(Math.min(grid.nx-1,i+ni-1+halo)/size);x++)
      ids.add(z*across+x);
  return ids;
}

export function walkColumnFaces(grid, heights, runs, floor, visit, box=[0,0,grid.nx,grid.nz]) {
  const intervals=new Map();
  const solid=(i,j)=>{
    if(i<0 || j<0 || i>=grid.nx || j>=grid.nz)return [];
    const c=j*grid.nx+i;if(intervals.has(c))return intervals.get(c);
    const out=[];let lo=floor;
    for(let k=0;k<runs.count[c];k++) {
      const n=c*runs.stride+k,hi=k===runs.count[c]-1 ? heights[c] : Math.min(heights[c],runs.top[n]);
      if(runs.kind[n]!==8 && hi-lo>1e-7) {
        if(out.length && Math.abs(out.at(-1)[1]-lo)<1e-7)out.at(-1)[1]=hi;
        else out.push([lo,hi]);
      }
      lo=hi;if(lo>=heights[c])break;
    }
    intervals.set(c,out);return out;
  };
  const quad=(column,points,y,top=false,reverse=false)=>visit({column,points:reverse ?
    [points[0],points[3],points[2],points[1]] : points,kind:exposedRunKind(runs,column,y,0),top});
  const [i0,j0,ni,nj]=box;
  for(let j=j0;j<j0+nj;j++)for(let i=i0;i<i0+ni;i++) {
    const c=j*grid.nx+i,own=solid(i,j),x=grid.x0+(i-.5)*grid.dx,z=grid.z0+(j-.5)*grid.dx,d=grid.dx;
    for(const [lo,hi] of own) {
      quad(c,[[x,hi,z],[x,hi,z+d],[x+d,hi,z+d],[x+d,hi,z]],hi-.001,Math.abs(hi-heights[c])<1e-7);
      if(lo>floor+1e-7)quad(c,[[x,lo,z],[x,lo,z+d],[x+d,lo,z+d],[x+d,lo,z]],lo+.001,false,true);
    }
    for(const [di,dj] of [[-1,0],[1,0],[0,-1],[0,1]]) {
      const neighbor=solid(i+di,j+dj);
      const wall=(lo,hi)=>{
        if(hi-lo<=1e-7)return;
        let from=lo;
        for(let k=0;k<runs.count[c];k++) {
          const n=c*runs.stride+k,to=k===runs.count[c]-1 ? hi : Math.min(hi,runs.top[n]);
          if(to-from>1e-7 && runs.kind[n]!==8) {
            const at=di ? x+(di>0?d:0) : z+(dj>0?d:0);
            const points=di ? [[at,from,z],[at,to,z],[at,to,z+d],[at,from,z+d]] :
              [[x,from,at],[x+d,from,at],[x+d,to,at],[x,to,at]];
            quad(c,points,(from+to)/2,false,di<0 || dj<0);
          }
          from=Math.max(from,to);if(from>=hi)break;
        }
      };
      for(const [lo,hi] of own) {
        let from=lo;
        for(const [nlo,nhi] of neighbor) {
          if(nhi<=from || nlo>=hi)continue;
          wall(from,Math.min(hi,nlo));from=Math.max(from,Math.min(hi,nhi));
        }
        wall(from,hi);
      }
    }
  }
}

// A readiness observation belongs to one sight point and observer pose. Adjacent
// cells can contain different materials even when less than 35 cm apart.
export function toolTargetFeedback({point, grid, tool, target, eyes, name=null, surface=null, context=null}) {
  const pending={tool:tool || null,ready:false,state:tool ? "checking" : "tool-needed",
    action:tool ? "Checking target" : "Hold a digging tool",screen:tool ? null : "inventory",
    materials:[],reason:null};
  if(!tool)return pending;
  const at=target?.observed_at_m, observed=target?.observed_from_m;
  if(!point || !at || !observed || !eyes || (target.observed_name || null)!==name)return pending;
  if((target.observed_context ?? null)!==context)return pending;
  if(!name && grid) {
    const cell=terrainCellAt(point[0],point[2],grid);
    if(cell<0 || cell!==terrainCellAt(at[0],at[2],grid))return pending;
    if(surface && target.target?.material && surface!==target.target.material)return pending;
  }
  // The ground is judged by its cell (above); a thing by the point on it. The
  // eye sways with the body, so it is held to 25 cm, not 3: at 3 cm the square
  // sat on "checking" and turned green only now and then (the owner, 2026-10-04).
  if((name || !grid) && Math.hypot(...point.map((v,i)=>v-at[i]))>.03)return pending;
  if(!name && grid && Math.abs(point[1]-at[1])>.03)return pending;   // the cell was dug since
  if(Math.hypot(...eyes.map((v,i)=>v-observed[i]))>.25)return pending;
  return target.feedback || pending;
}

// Both World and the sidebar use the same fresh native readiness observation.
export function toolTargetColor(feedback) {
  if(feedback.ready)return 0x62e595;
  if(feedback.state==='blocked')return 0xf17f79;
  if(['checking','working'].includes(feedback.state))return 0xe7bf65;
  return 0xe7eff5;
}

// A collected amount comes from a closed native receipt, never a preview or
// guessed per-material density. Keep the engine report available separately.
export function collectedToolMaterials(answer) {
  if(Array.isArray(answer?.results) && answer.results.length) {
    if(answer.refused)return null;
    const rows=answer.results.map(result=>collectedToolMaterials({result})).filter(Boolean);
    return rows.length ? {kg:rows.reduce((sum,r)=>sum+r.kg,0),materials:[...new Set(rows.flatMap(r=>r.materials))]} : null;
  }
  const receipt=answer?.result, kg=receipt?.loosened_kg;
  if(answer?.refused || !receipt || receipt.open!==false || receipt.kind!=="broke out"
    || !Number.isFinite(kg) || kg<=0)return null;
  const materials=["sand","soil"].filter(name=>Number(receipt.loosened?.[`${name}_m3`])>0);
  return materials.length ? {kg,materials} : null;
}

// Deliberate dwell, reset by a different target, pointer drift or camera move.
// Refreshes of the same readiness data do not restart it.
export function makeTargetHover(delayMs=1500) {
  let anchor=null;
  return (now,sight)=>{
    if(!sight){anchor=null;return false;}
    if(!anchor || sight.key!==anchor.key || Math.hypot(sight.x-anchor.x,sight.y-anchor.y)>12
      || Math.hypot(...sight.eyes.map((v,i)=>v-anchor.eyes[i]))>.03)
      anchor={...sight,eyes:sight.eyes.slice(),since:now};
    return now-anchor.since>=delayMs;
  };
}

// Small display packets describe confirmed collection; they are not simulated
// debris, fragment bodies or an extra inventory transfer.
export function toolOutcomeFeedback(answer) {
  if(answer?.refused)return null;
  const result=answer?.result,collected=collectedToolMaterials(answer);
  const hit=!!collected || (result?.open===false && Number(result.work_j)>0)
    || (result?.schema==='banjo.object-strike.v1' && result.impacts?.length>0);
  if(!hit)return null;
  const count=collected ? Math.min(12,Math.max(1,Math.ceil(collected.kg*3))) : 0;
  return {at:result?.at_m || null,collected,
    packets:Array.from({length:count},(_,i)=>collected.materials[i%collected.materials.length])};
}

// Nine vertices include the midpoint of each side: each side can cross two
// of the collider's triangles. The marker follows the surface, never a flat
// invented tile or an excavation promise.
export function terrainTargetPath(point, grid, heightAt) {
  const index=terrainCellAt(point[0],point[2],grid);
  if(index<0)return null;
  const x=grid.x0+(index%grid.nx)*grid.dx, z=grid.z0+Math.floor(index/grid.nx)*grid.dx;
  const half=grid.dx/2;
  if(grid.surface==="columns")return [[-1,-1],[1,-1],[1,1],[-1,1],[-1,-1]]
    .flatMap(([i,j])=>[x+i*half,point[1]+.012,z+j*half]);
  return [[-1,-1],[0,-1],[1,-1],[1,0],[1,1],[0,1],[-1,1],[-1,0],[-1,-1]]
    .flatMap(([i,j])=>{
      const px=grid.surface==="cuts" ? x+i*half : Math.max(grid.x0,Math.min(grid.x0+(grid.nx-1)*grid.dx,x+i*half));
      const pz=grid.surface==="cuts" ? z+j*half : Math.max(grid.z0,Math.min(grid.z0+(grid.nz-1)*grid.dx,z+j*half));
      // Stay just inside the selected cell at a discontinuous cut boundary.
      const inset=grid.surface==="cuts" ? grid.dx*1e-5 : 0;
      const hx=px===x ? px : px+Math.sign(x-px)*inset;
      const hz=pz===z ? pz : pz+Math.sign(z-pz)*inset;
      return [px,heightAt(hx,hz)+.012,pz];
    });
}

// Material on an exposed solid face, including the floor/roof of a void.
// The packed run heights are millimetres, so use that precision at a boundary.
export function exposedRunKind(runs, column, y, fallback) {
  if(!runs || !runs.count[column])return fallback;
  for(let k=0;k<runs.count[column];k++) {
    const at=column*runs.stride+k;
    if(y<=runs.top[at]+.001 && runs.kind[at]!==8)return runs.kind[at];
  }
  return fallback;
}

export function samplePattern(pen, appearance, x, y, width, height) {
  pen.save(); pen.beginPath(); pen.rect(x,y,width,height); pen.clip();
  pen.strokeStyle="rgba(20,24,30,.35)"; pen.fillStyle="rgba(20,24,30,.30)";
  pen.lineWidth=1;
  if (appearance.pattern==="bands") {
    for(let n=-height;n<width+height;n+=5) {
      pen.beginPath();pen.moveTo(x+n,y);pen.lineTo(x+n+height,y+height);pen.stroke();
    }
  } else if (appearance.pattern==="fractures") {
    pen.beginPath();pen.moveTo(x+width*.2,y);pen.lineTo(x+width*.45,y+height*.5);
    pen.lineTo(x+width*.3,y+height);pen.moveTo(x+width*.45,y+height*.5);
    pen.lineTo(x+width,y+height*.65);pen.stroke();
  } else if (appearance.pattern==="inclusions") {
    for(let n=0;n<7;n++) {
      pen.fillStyle=n%2 ? "#d6aa62" : "#34473d";
      pen.fillRect(x+(n*7+2)%width,y+(n*11+3)%height,3,3);
    }
  } else {
    for(let n=0;n<18;n++) {
      const size=appearance.pattern==="speckle"?1:2;
      pen.fillRect(x+(n*7+2)%width,y+(n*11+3)%height,size,size);
    }
  }
  pen.restore();
}
