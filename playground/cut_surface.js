// Same cell-local displacement and original triangle split as TerrainField.
// The baseline is native generated float32 data, not a browser reconstruction.
export function baselineHeightAt(g, base, x, z) {
  const fx=Math.max(0,Math.min(g.nx-1,(x-g.x0)/g.dx));
  const fz=Math.max(0,Math.min(g.nz-1,(z-g.z0)/g.dx));
  const i=Math.min(g.nx-2,Math.floor(fx)),j=Math.min(g.nz-2,Math.floor(fz)),u=fx-i,v=fz-j;
  const a=base[j*g.nx+i],b=base[j*g.nx+i+1],c=base[(j+1)*g.nx+i],d=base[(j+1)*g.nx+i+1];
  return u>=v ? a+u*(b-a)+v*(d-b) : a+v*(c-a)+u*(d-c);
}

export function cutHeightAt(g, base, heights, x, z, owner=null) {
  const i=Math.max(0,Math.min(g.nx-1,Math.floor((x-g.x0)/g.dx+.5)));
  const j=Math.max(0,Math.min(g.nz-1,Math.floor((z-g.z0)/g.dx+.5)));
  const c=owner ?? j*g.nx+i;
  return baselineHeightAt(g,base,x,z)+(heights[c]-base[c]);
}

// Bounds own complete cells. Wall ownership belongs to the higher displacement,
// so a seam edit rebuilds its neighboring chunks without duplicating faces.
export function walkCutSurface(g, base, heights, emit, box=[0,0,g.nx,g.nz]) {
  const ring=[[-1,-1],[-1,0],[-1,1],[0,1],[1,1],[1,0],[1,-1],[0,-1]];
  for(let j=box[1];j<Math.min(g.nz,box[1]+box[3]);j++)
    for(let i=box[0];i<Math.min(g.nx,box[0]+box[2]);i++) {
      const column=j*g.nx+i,d=heights[column]-base[column],x=g.x0+i*g.dx,z=g.z0+j*g.dx;
      const point=(a,b,offset)=>{
        const px=x+a*g.dx/2,pz=z+b*g.dx/2;
        return [px,baselineHeightAt(g,base,px,pz)+offset,pz];
      };
      const center=point(0,0,d);
      for(let k=0;k<8;k++) {
        const a=point(...ring[k],d),b=point(...ring[(k+1)%8],d);
        if(Math.abs((a[0]-center[0])*(b[2]-center[2])-(a[2]-center[2])*(b[0]-center[0]))>1e-12)
          emit({column,top:true,points:[center,a,b]});
      }
      for(const [di,dj] of [[-1,0],[1,0],[0,-1],[0,1]]) {
        if(i+di<0 || j+dj<0 || i+di>=g.nx || j+dj>=g.nz)continue;
        const neighbor=(j+dj)*g.nx+i+di,other=heights[neighbor]-base[neighbor];
        if(d<=other+1e-7)continue;
        for(let half=0;half<2;half++) {
          const begin=half-1,end=half;
          const a=di?point(di,begin,other):point(begin,dj,other);
          const b=di?point(di,begin,d):point(begin,dj,d);
          const c=di?point(di,end,d):point(end,dj,d);
          const e=di?point(di,end,other):point(end,dj,other);
          const triangles=((di && di<0) || (!di && dj>0)) ? [[a,c,b],[a,e,c]] : [[a,b,c],[a,c,e]];
          for(const points of triangles)emit({column,top:false,points});
        }
      }
    }
}

// Clip actual wall triangles at horizontal material-run boundaries. Preserve
// their winding and geometry; no extra pit depth, debris or material is added.
export function cutWallBands(face, runs, floor, emit) {
  const clip=(poly,y,above)=>{
    const out=[];
    for(let i=0;i<poly.length;i++) {
      const a=poly[i],b=poly[(i+1)%poly.length];
      const aa=above?a[1]>=y:a[1]<=y,bb=above?b[1]>=y:b[1]<=y;
      if(aa)out.push(a);
      if(aa!==bb){const t=(y-a[1])/(b[1]-a[1]);out.push(a.map((v,k)=>v+t*(b[k]-v)));}
    }
    return out;
  };
  let lo=floor;
  const count=runs.count[face.column];
  for(let k=0;k<count;k++) {
    const at=face.column*runs.stride+k;
    const hi=k===count-1?Infinity:runs.top[at];
    if(runs.kind[at]!==8) {
      const polygon=clip(clip(face.points,lo,true),hi,false);
      for(let v=1;v+1<polygon.length;v++)emit(runs.kind[at],[polygon[0],polygon[v],polygon[v+1]]);
    }
    lo=hi;
  }
}

// Outline the real upper/lower rim and upright edges, never the triangulation
// diagonal. Tiny settling differences do not create a carpet of outlines.
export function cutRimSegments(g,base,heights,face) {
  if(face.top)return [];
  const p=face.points,delta=p.map(v=>v[1]-cutHeightAt(g,base,heights,v[0],v[2],face.column));
  if(Math.max(...delta)-Math.min(...delta)<.005)return [];
  const segments=[];
  for(let i=0;i<3;i++) {
    const j=(i+1)%3;
    const sameLevel=Math.abs(delta[i]-delta[j])<1e-6;
    const upright=Math.hypot(p[i][0]-p[j][0],p[i][2]-p[j][2])<1e-8;
    if(sameLevel || upright)segments.push(p[i],p[j]);
  }
  return segments;
}
