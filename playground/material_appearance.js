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

// Nine vertices include the midpoint of each side: each side can cross two
// of the collider's triangles. The marker follows the surface, never a flat
// invented tile or an excavation promise.
export function terrainTargetPath(point, grid, heightAt) {
  const index=terrainCellAt(point[0],point[2],grid);
  if(index<0)return null;
  const x=grid.x0+(index%grid.nx)*grid.dx, z=grid.z0+Math.floor(index/grid.nx)*grid.dx;
  const half=grid.dx/2;
  return [[-1,-1],[0,-1],[1,-1],[1,0],[1,1],[0,1],[-1,1],[-1,0],[-1,-1]]
    .flatMap(([i,j])=>{
      const px=Math.max(grid.x0,Math.min(grid.x0+(grid.nx-1)*grid.dx,x+i*half));
      const pz=Math.max(grid.z0,Math.min(grid.z0+(grid.nz-1)*grid.dx,z+j*half));
      return [px,heightAt(px,pz)+.012,pz];
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
