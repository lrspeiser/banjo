import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import * as THREE from '../playground/vendor/three.module.js';
import {GROUND_APPEARANCE,materialAppearance,terrainCellAt,terrainHitPoint,terrainTargetPath,exposedRunKind,toolTargetFeedback,toolTargetColor,collectedToolMaterials,toolOutcomeFeedback, makeTargetHover,cellWaterData,columnTopData,walkColumnFaces,columnChunkIds,columnChunkBox} from '../playground/material_appearance.js';

test('wall selection works from all four directions and marks the clicked vertical band',()=>{
  const grid={nx:5,nz:5,dx:.25,x0:0,z0:0,surface:'columns'};
  for(const axis of [0,2])for(const sign of [-1,1]) {
    const point=[.5,1.375,.5],eyes=[.5,1.7,.5];
    point[axis]+=.125*sign;eyes[axis]+=sign;
    const at=terrainHitPoint(point,eyes,grid);
    assert.equal(terrainCellAt(at[0],at[2],grid),12,'solid side of each shared face');
    assert.deepEqual(terrainHitPoint(at,eyes,grid),at,'host cannot shift an already resolved point');
    const path=terrainTargetPath(at,grid,()=>2);
    const ys=path.filter((_,i)=>i%3===1);
    assert.equal(Math.min(...ys),1.25);assert.equal(Math.max(...ys),1.5);
    assert.ok(path.filter((_,i)=>i%3===axis).every(v=>Math.abs(v-point[axis]-.012*sign)<1e-10));
  }
  const receipt={open:false,kind:'broke rock out',work_j:26,at_m:[.5,1.375,.5],loosened_kg:37.5,loosened:{rock_m3:.015625}};
  assert.deepEqual(collectedToolMaterials({result:receipt}),{kg:37.5,materials:['rock']});
  assert.deepEqual(toolOutcomeFeedback({result:receipt}).collected,{kg:37.5,materials:['rock']});
});

test('the shipped world renders a green wall square with its fill on the face',()=>{
  const source=readFileSync(new URL('../playground/world.js',import.meta.url),'utf8');
  const code=source.slice(source.indexOf('const groundTargetGeometry='),source.indexOf('async function aim()'));
  const grid={nx:5,nz:5,dx:.25,x0:0,z0:0,surface:'columns'},at=[.623,1.375,.5],eyes=[1.5,1.7,.5];
  const target={observed_at_m:at,observed_from_m:eyes,observed_context:'wall',target:{material:'rock'},
    feedback:{ready:true,state:'ready'}};
  const world={groundAim:at,held:{pick:{}},use:{name:'pick',mode:'tool-ready',target}};
  const camera=new THREE.PerspectiveCamera();camera.position.fromArray(eyes);
  const crosshair={dataset:{}};
  const run=new Function('THREE','scene','world','ground','groundColumn','groundSeen','camera','$',
    'toolTargetFeedback','toolTargetColor','groundMadeOf','targetContext','terrainTargetPath','groundAt','recordInteraction',code+
    ';showGroundTarget();return {groundTarget,groundTargetFill};');
  const {groundTarget,groundTargetFill}=run(THREE,new THREE.Scene(),world,{grid},()=>({c:12,grid}),()=>true,camera,
    ()=>crosshair,toolTargetFeedback,toolTargetColor,()=> 'rock',()=> 'wall',terrainTargetPath,()=>2,()=>{});
  assert.equal(groundTarget.visible,true);assert.equal(crosshair.dataset.readiness,'ready');
  assert.equal(groundTarget.material.color.getHex(),0x62e595);
  assert.equal(groundTargetFill.material.opacity,.62);
  const vertices=groundTargetFill.geometry.attributes.position.array;
  assert.ok(Math.abs(vertices[0]-.637)<1e-6,'fill center stays on wall rather than floating behind it');
  assert.ok(Math.abs(vertices[1]-1.375)<1e-6);
});

test('a one-cell channel draws wet footprints without bridging dry excavation',()=>{
  for(const mode of ['smooth','columns','cuts']) {
    const grid={nx:3,nz:3,x0:0,z0:0,dx:.25,surface:mode};
    const heights=new Float32Array(9).fill(-1),water=new Float32Array(9).fill(NaN);
    water[1]=water[4]=water[7]=.5;
    const data=cellWaterData(grid,heights,water);
    assert.deepEqual([...data.cells],[1,4,7]);assert.equal(data.indices.length,18);
    for(let n=0;n<3;n++) {
      const points=data.positions.subarray(12*n,12*n+12);
      assert.equal(Math.min(points[0],points[3],points[6],points[9]),.125);
      assert.equal(Math.max(points[0],points[3],points[6],points[9]),.375);
      for(let v=0;v<4;v++)assert.equal(points[3*v+1],.5);
    }
    water[4]=NaN;assert.deepEqual([...cellWaterData(grid,heights,water).cells],[1,7]);
    water[4]=-.5;heights[4]=0;assert.deepEqual([...cellWaterData(grid,heights,water).cells],[1,7]);
    water.fill(NaN);assert.equal(cellWaterData(grid,heights,water).positions.length,0);
  }
});

test('shipped water updates retain only wet cells across drying and changing topology',()=>{
  const source=readFileSync(new URL('../playground/world.js',import.meta.url),'utf8');
  const code=source.slice(source.indexOf('function extendShore'),source.indexOf('function stepFoam'));
  const grid={nx:3,nz:1,dx:.25,x0:0,z0:0};
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(0),3));
  const ground={grid,heights:new Float32Array(3),water:new THREE.Mesh(geometry),waterCells:new Uint32Array(0)};
  const {drawWater,animateWater,currentSurface}=new Function('ground','THREE','cellWaterData','bytesOf','WATER_SHALLOW',
    'WATER_DEEP','clamp','WATER_EASE_MS','showWater','placeBeyond',code+'\nreturn {drawWater,animateWater,currentSurface};')(
      ground,THREE,cellWaterData,x=>Uint8Array.from(Buffer.from(x,'base64')),new THREE.Color('#66ccee'),
      new THREE.Color('#113355'),(x,a,b)=>Math.max(a,Math.min(b,x)),300,()=>{},()=>{});
  const packet=values=>({box:[0,0,3,1],base_m:0,
    surface_mm_b64:Buffer.from(new Uint16Array(values).buffer).toString('base64'),
    flow_b64:Buffer.from(new Int8Array(6).buffer).toString('base64')});
  drawWater(packet([500,0,0]));animateWater(ground.arrived+300);
  assert.deepEqual([...ground.waterCells],[0]);assert.equal(currentSurface()[0],.5);
  assert.ok(Number.isNaN(currentSurface()[1]),'a dry neighboring cell has no fabricated water');
  let disposed=false;ground.water.geometry.addEventListener('dispose',()=>disposed=true);
  drawWater(packet([0,700,0]));animateWater(ground.arrived+300);
  assert.ok(disposed,'replaced water buffers are released');
  assert.deepEqual([...ground.waterCells],[1]);
  assert.ok(Number.isNaN(currentSurface()[0]));assert.ok(Math.abs(currentSurface()[1]-.7)<1e-6);
  assert.ok([...ground.water.geometry.attributes.position.array].every(Number.isFinite));
  drawWater(packet([0,0,0]));animateWater(ground.arrived+300);
  assert.equal(ground.water.geometry.attributes.position.count,0);
  assert.equal(ground.water.geometry.boundingSphere.radius,0);
});

test('outcome feedback reports native receipts without inventing debris',()=>{
  const answer={result:{open:false,kind:'broke out',loosened_kg:1.5,
    at_m:[1,0,2],loosened:{sand_m3:.001,soil_m3:0}}};
  const effect=toolOutcomeFeedback(answer);
  assert.deepEqual(effect.at,[1,0,2]);assert.equal(effect.collected.kg,1.5);
  assert.deepEqual(Object.keys(effect).sort(),['at','collected']);
  assert.equal(toolOutcomeFeedback({...answer,refused:'Load full'}),null);
  assert.equal(toolOutcomeFeedback({result:{...answer.result,open:true}}),null);
  assert.equal(toolOutcomeFeedback({result:{schema:'banjo.object-strike.v1',impacts:[]}}),null);
  assert.equal(toolOutcomeFeedback({result:{schema:'banjo.object-strike.v1',impacts:[{}]}}).collected,null);
  assert.equal(toolOutcomeFeedback({result:{...answer.result,loosened_kg:10000}}).collected.kg,10000);
});

test('stock receipts never create flight bodies in the shipped renderer',()=>{
  const source=readFileSync(new URL('../playground/world.js',import.meta.url),'utf8');
  const code=source.slice(source.indexOf('function goodsVisuals('),source.indexOf('const resourceVisuals ='));
  const document={createElement:()=>({addEventListener(){},dataset:{}}),body:{append(){}}};
  const visuals=new Function('THREE','document','titled','heldSaid',code+';return goodsVisuals;')(
    THREE,document,x=>x,x=>String(x));
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera();camera.position.set(10,2,10);
  const view=visuals({scene,camera,groundAt:()=>0,body:()=>null,ports:()=>[],
    colour:()=> '#999999',collect:()=>{throw Error('drawing is not collection');},readonly:()=>true});
  const pile={name:'soil stock',at_m:[0,0],holds_kg:{soil:25},excavated:'soil'};
  const baseline={stockpiles:[pile],activities:[],activity_epoch:1};
  view.follow(baseline,true);view.advance(0);
  const root=scene.getObjectByName('resource-packets');
  assert.equal(root.children.length,1);
  const positions=root.children.map(mesh=>mesh.position.toArray());
  const events=['excavate','mine','input','output','collect'].map((kind,id)=>({id,kind,
    goods_kg:{soil:25},from:{point_m:[0,2,0]},to:{pile:pile.name}}));
  const next={...baseline,activities:events};
  view.follow(next);view.advance(1200);view.follow(next);view.advance(2000);
  assert.equal(root.children.length,1,'receipts cannot mint flying fragment meshes');
  assert.deepEqual(root.children.map(mesh=>mesh.position.toArray()),positions);
  assert.ok(root.children.every(mesh=>!mesh.userData.transferKind));
  assert.equal(pile.holds_kg.soil,25,'rendering cannot debit or credit material');
});

test('dig square is green only for a fresh ready observation; refusals are red',()=>{
  const point=[.25,0,.25],eyes=[0,1.62,0],grid={x0:0,z0:0,dx:.25,nx:3,nz:3};
  const target={observed_at_m:point,observed_from_m:eyes,observed_context:'sand',
    target:{material:'sand'},feedback:{ready:true,state:'ready'}};
  const feedback=(extra={})=>toolTargetFeedback({point,eyes,grid,tool:'Authored hoe',target,
    surface:'sand',context:'sand',...extra});
  assert.equal(toolTargetColor(feedback()),0x62e595);
  for(const extra of [{point:[.5,0,.25]},{eyes:[0,1.62,.4]},{context:'soil'},
    {target:{...target,feedback:{ready:false,state:'blocked',action:'Move closer'}}}])
    assert.notEqual(toolTargetColor(feedback(extra)),0x62e595);
  assert.equal(toolTargetColor({ready:false,state:'blocked'}),0xf17f79);
  assert.equal(toolTargetColor({ready:false,state:'checking'}),0xe7bf65);
  assert.equal(toolTargetColor({ready:false,state:'warning'}),0xe7bf65);
});
import {terrainMaterial} from '../playground/terrain_material.js';
import {baselineHeightAt,cutHeightAt,walkCutSurface,cutWallBands,cutRimSegments} from '../playground/cut_surface.js';

test('smooth hills and local cuts retain exact depth, volume and chunk seam ownership',()=>{
  const g={nx:65,nz:5,dx:.25,x0:0,z0:0};
  const base=Float32Array.from({length:g.nx*g.nz},(_,k)=>.2*(k%g.nx)*g.dx+.1*Math.floor(k/g.nx)*g.dx);
  const heights=base.slice(),c=2*g.nx+31,x=31*g.dx,z=2*g.dx;
  const before=[];walkCutSurface(g,base,heights,f=>before.push(f));
  assert.equal(before.filter(f=>!f.top).length,0,'no untouched hill steps');
  heights[c]-=.2;
  assert.ok(Math.abs(cutHeightAt(g,base,heights,x+.1,z)-baselineHeightAt(g,base,x+.1,z)+.2)<1e-7);
  assert.equal(cutHeightAt(g,base,heights,x+.13,z),baselineHeightAt(g,base,x+.13,z),'neighbor unchanged');
  const all=[];walkCutSurface(g,base,heights,f=>all.push(f));
  assert.equal(all.filter(f=>!f.top).length,16,'four walls, two halves, two triangles');
  assert.equal(before.flatMap(f=>cutRimSegments(g,base,base,f)).length,0,'no natural hill outlines');
  for(const f of all.filter(f=>!f.top)) {
    const edges=cutRimSegments(g,base,heights,f);
    assert.equal(edges.length,4,'two physical edges; no diagonal');
    for(const p of edges)assert.ok(f.points.includes(p),'outline adds no depth or detached edges');
  }
  const chunks=[];for(let i=0;i<g.nx;i+=32)walkCutSurface(g,base,heights,f=>chunks.push(f),[i,0,32,g.nz]);
  const ordered=faces=>faces.map(f=>JSON.stringify(f)).sort();assert.deepEqual(ordered(chunks),ordered(all));
  const area=faces=>faces.filter(f=>f.top).reduce((s,{points:[a,b,c]})=>s+Math.abs((b[0]-a[0])*(c[2]-a[2])-(b[2]-a[2])*(c[0]-a[0]))/2,0);
  assert.equal(area(all),g.nx*g.nz*g.dx*g.dx,'complete column area without overlap');
  const volume=faces=>faces.filter(f=>f.top).reduce((s,{points:[a,b,c]})=>s+Math.abs((b[0]-a[0])*(c[2]-a[2])-(b[2]-a[2])*(c[0]-a[0]))/2*(a[1]+b[1]+c[1])/3,0);
  assert.ok(Math.abs(volume(before)-volume(all)-g.dx*g.dx*.2)<1e-8,'rendered cut equals volume removed');
});

test('cut walls expose actual bands and target stays inside selected sharp cell',()=>{
  const face={column:0,points:[[0,0,0],[0,1,0],[0,1,1]]};
  const runs={count:[2],stride:2,top:[.5,1],kind:[1,2]},bands=[];
  cutWallBands(face,runs,-1,(kind,points)=>bands.push({kind,points}));
  assert.deepEqual([...new Set(bands.map(f=>f.kind))],[1,2]);
  for(const f of bands)assert.ok(f.points.every(p=>f.kind===1?p[1]<=.5:p[1]>=.5));
  const g={nx:4,nz:4,dx:.25,x0:0,z0:0,surface:'cuts'},base=new Float32Array(16),h=base.slice();h[5]=-.2;
  const path=terrainTargetPath([.25,-.2,.25],g,(x,z)=>cutHeightAt(g,base,h,x,z));
  for(let k=1;k<path.length;k+=3)assert.ok(Math.abs(path[k]+.188)<1e-7,'target follows cut floor, not rim');
});

for(const surface of ['smooth','columns','cuts'])test(surface+' full-terrain catchup reuses the mesh and streams variable runs once',()=>{
  const source=readFileSync(new URL('../playground/world.js',import.meta.url),'utf8');
  const part=(start,end)=>source.slice(source.indexOf('function '+start),source.indexOf('function '+end));
  const code=part('markColumnFaces','buildColumnFaces')+part('decodeRuns','runsRoom')+part('patchRuns','standingOn')+
    part('patchTerrain','extendShore');
  let rebuilt=0,paints=0,normals=0;
  const vertices=surface==='columns'?4:1;
  const ground={grid:{nx:3,nz:2,dx:.25,x0:0,z0:0,surface},floor:-3,
    runs:{stride:4,count:new Uint8Array(6),kind:new Uint8Array(24),top:new Float32Array(24)},
    heights:new Float32Array(6),surfaces:new Uint8Array(6),water:{identity:'keep water'},
    dirtyFaceChunks:new Set(),
    seen:new Uint8Array([1,0,1,1,1,1]),materialCells:{update:()=>paints++},mesh:{geometry:{
      attributes:{position:{array:new Float32Array(18*vertices)},color:{array:new Float32Array(18*vertices)}},
      computeVertexNormals:()=>normals++,computeBoundingSphere:()=>{}}}};
  ground.colors=surface==='columns'?new Float32Array(18):ground.mesh.geometry.attributes.color.array;
  const bytesOf=x=>new Uint8Array(Buffer.from(x,'base64'));
  // Grown regions (docs/streamed-regions.md) are drawn by their own module;
  // this valley has none.
  const groundRegions={refresh:()=>{},count:0,clear:()=>{}};
  const {refreshTerrain}=new Function('ground','bytesOf','paintGround','drawTerrain','columnChunkIds','groundRegions',code+
    '\nreturn {refreshTerrain};')(ground,bytesOf,()=>{},()=>rebuilt++,columnChunkIds,groundRegions);
  const heights=Buffer.from(new Float32Array([1,2,3,4,5,6]).buffer).toString('base64');
  const raw=[];
  for(let c=0;c<6;c++) {
    const n=c===3?5:2;raw.push(n);
    for(let k=0;k<n;k++)raw.push(k===n-1?(c%2?1:2):0,100+k*20,0);
  }
  const block={surface,grid:{nx:3,nz:2,cell_m:.25,x0_m:0,z0_m:0},floor_m:-3,
    heights_b64:heights,ground_b64:Buffer.from([2,1,2,1,2,1]).toString('base64'),
    runs_b64:Buffer.from(raw).toString('base64')};
  const mesh=ground.mesh,water=ground.water,seen=ground.seen;
  refreshTerrain(block);
  assert.equal(rebuilt,0);assert.equal(paints,6);assert.equal(normals,surface==='smooth'?1:0);
  assert.equal(ground.mesh,mesh);assert.equal(ground.water,water);assert.equal(ground.seen,seen);
  assert.deepEqual([...ground.heights],[1,2,3,4,5,6]);assert.equal(ground.runs.count[3],5);
  for(let c=0;c<6;c++)for(let v=0;v<vertices;v++)
    assert.equal(ground.mesh.geometry.attributes.position.array[3*(c*vertices+v)+1],c+1);
  for(let c=0;c<6;c++)assert.equal(ground.runs.kind[c*ground.runs.stride+ground.runs.count[c]-1],c%2?1:2);
  assert.equal(ground.facesStale,true);
  ground.facesStale=false;ground.dirtyFaceChunks.clear();refreshTerrain(block);
  assert.equal(ground.facesStale,false,'unchanged catchup does not rebuild faces');
  assert.equal(paints,6,'unchanged catchup does not repaint the palette');
  refreshTerrain({...block,grid:{...block.grid,cell_m:.5}});assert.equal(rebuilt,1);
  refreshTerrain({...block,surface:surface==='smooth'?'columns':'smooth'});assert.equal(rebuilt,2);
});

test('a roof-removal packet moves all four top vertices to the real floor and rebuilds its void faces',()=>{
  const source=readFileSync(new URL('../playground/world.js',import.meta.url),'utf8');
  const part=(a,b)=>source.slice(source.indexOf('function '+a),source.indexOf('function '+b));
  const code=part('markColumnFaces','buildColumnFaces')+part('decodeRuns','runsRoom')+part('patchRuns','standingOn')+part('patchTerrain','refreshTerrain');
  const g={nx:1,nz:1,dx:.25,x0:0,z0:0,surface:'columns'};
  const top=columnTopData(g,new Float32Array([.75]),new Float32Array([1,1,1]));
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.BufferAttribute(top.positions,3));
  geometry.setAttribute('color',new THREE.BufferAttribute(top.colors,3));
  const ground={grid:g,floor:0,mesh:{geometry},heights:new Float32Array([.75]),surfaces:new Uint8Array([1]),
    colors:new Float32Array([1,1,1]),runs:{stride:4,count:new Uint8Array([3]),kind:new Uint8Array([1,8,1,0]),top:new Float32Array([.25,.5,.75,0])},
    dirtyFaceChunks:new Set(),materialCells:{update(){}}};
  const patch=new Function('ground','bytesOf','paintGround','columnChunkIds','runsRoom',code+';return patchTerrain;')(
    ground,x=>new Uint8Array(Buffer.from(x,'base64')),()=>{},columnChunkIds,()=>{});
  patch({box:[0,0,1,1],heights_b64:Buffer.from(new Float32Array([.25]).buffer).toString('base64'),
    ground_b64:Buffer.from([1]).toString('base64'),runs_b64:Buffer.from([1,1,250,0]).toString('base64')});
  for(let v=0;v<4;v++)assert.equal(geometry.attributes.position.array[3*v+1],.25,'no top vertex stays above the hole');
  const faces=[];walkColumnFaces(g,ground.heights,ground.runs,0,f=>faces.push(f));
  assert.ok(faces.every(f=>f.points.every(p=>p[1]<=.25)),'no old roof/ceiling face remains');
  assert.deepEqual([...ground.dirtyFaceChunks],[0]);assert.equal(ground.runs.count[0],1);
  assert.equal(geometry.attributes.position.version,1,'changed positions are uploaded');
});

test('material columns have flat tops with outward winding and true cell bounds',()=>{
  const grid={nx:3,nz:2,dx:.25,x0:-1,z0:-2,surface:'columns'},H=new Float32Array([1,2,3,4,5,6]);
  const colors=new Float32Array(18).fill(.5),data=columnTopData(grid,H,colors);
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(data.positions,3));
  geometry.setIndex(new THREE.BufferAttribute(data.indices,1));geometry.computeVertexNormals();
  const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());mesh.updateMatrixWorld();
  for(let c=0;c<6;c++) {
    const x=grid.x0+c%3*.25,z=grid.z0+Math.floor(c/3)*.25;
    for(const off of [-.1,0,.1]) {
      const ray=new THREE.Raycaster(new THREE.Vector3(x+off,10,z),new THREE.Vector3(0,-1,0));
      assert.equal(ray.intersectObject(mesh)[0].point.y,H[c]);
    }
  }
  const path=terrainTargetPath([-1,1,-2],grid,()=>999);
  assert.deepEqual(path.slice(0,3),[-1.125,1.012,-2.125]);
});

test('column cut faces keep voids open, preserve material bands and their union volume',()=>{
  const grid={nx:3,nz:2,dx:.25,x0:0,z0:0},H=new Float32Array(6).fill(1);
  const runs={stride:3,count:new Uint8Array(6).fill(1),kind:new Uint8Array(18),top:new Float32Array(18)};
  for(let c=0;c<6;c++)runs.top[3*c]=1;
  runs.count[1]=3;runs.kind.set([0,8,1],3);runs.top.set([.4,.6,1],3);
  const faces=[];walkColumnFaces(grid,H,runs,0,face=>faces.push(face));
  assert.equal(faces.filter(f=>f.top).length,6);assert.ok(faces.some(f=>!f.top && f.kind===1));
  const pos=[];let volume=0;
  for(const face of faces)for(const tri of [[0,1,2],[0,2,3]]) {
    const [a,b,c]=tri.map(i=>new THREE.Vector3(...face.points[i]));
    volume+=a.dot(b.clone().cross(c))/6;
    pos.push(...a.toArray(),...b.toArray(),...c.toArray());
  }
  assert.ok(Math.abs(volume-(6*.25*.25-.2*.25*.25))<1e-8);
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(pos),3));
  const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());mesh.updateMatrixWorld();
  for(const [direction,y] of [[-1,.4],[1,.6]]) {
    const ray=new THREE.Raycaster(new THREE.Vector3(.25,.5,0),new THREE.Vector3(0,direction,0));
    assert.ok(Math.abs(ray.intersectObject(mesh)[0].point.y-y)<1e-7);
  }
  const wall=new THREE.Raycaster(new THREE.Vector3(.25,.5,0),new THREE.Vector3(1,0,0)).intersectObject(mesh)[0];
  assert.equal(wall.distance,.125,'void stops where the neighboring solid starts');
});

test('render chunks preserve every face and material across cut and void seams',()=>{
  const g={nx:65,nz:34,dx:.25,x0:-8,z0:-4},H=new Float32Array(g.nx*g.nz);
  const runs={stride:3,count:new Uint8Array(H.length).fill(1),kind:new Uint8Array(3*H.length),top:new Float32Array(3*H.length)};
  for(let c=0;c<H.length;c++){H[c]=1+(c%g.nx%5)*.1;runs.top[3*c]=H[c];runs.kind[3*c]=c%3;}
  for(const i of [31,32]) {const c=12*g.nx+i;runs.count[c]=3;runs.kind.set([0,8,1],3*c);runs.top.set([.3,.6,H[c]],3*c);}
  const full=[],chunks=[];walkColumnFaces(g,H,runs,0,f=>full.push(JSON.stringify(f)));
  for(const id of columnChunkIds(g))walkColumnFaces(g,H,runs,0,f=>chunks.push(JSON.stringify(f)),columnChunkBox(g,id));
  assert.deepEqual(chunks.sort(),full.sort(),'chunking adds no artificial edge wall, missing face or changed kind');
  assert.deepEqual([...columnChunkIds(g,[31,12,1,1])],[0,1]);
  assert.deepEqual([...columnChunkIds(g,[31,31,1,1])],[0,1,3,4]);
  assert.deepEqual([...columnChunkIds(g,[64,33,1,1])],[4,5]);
  assert.deepEqual([...columnChunkIds(g,[31,12,1,1],0)],[0],'exploration repaints only the owning chunk');
});

for(const surface of ['columns','cuts'])test(surface+' shipped chunk renderer replaces edited neighbors, keeps distant meshes and disposes replaced geometry',()=>{
  const source=readFileSync(new URL('../playground/world.js',import.meta.url),'utf8');
  const code=source.slice(source.indexOf('function markColumnFaces'),source.indexOf('function buildFaces'));
  const g={nx:65,nz:34,dx:.25,x0:0,z0:0,surface},H=new Float32Array(g.nx*g.nz);
  const runs={stride:1,count:new Uint8Array(H.length).fill(1),kind:new Uint8Array(H.length),top:new Float32Array(H.length)};
  for(let c=0;c<H.length;c++)H[c]=runs.top[c]=1;
  const ground={grid:g,runs,heights:H,baseline:H.slice(),materialCells:{material:new THREE.MeshStandardMaterial()},floor:0,faceChunks:new Map(),dirtyFaceChunks:new Set(),faceMaterial:null};
  const scene=new THREE.Scene(),trace={terrain:[]};
  const {markColumnFaces,buildColumnFaces,buildCutFaces}=new Function('ground','scene','trace','THREE','dress','groundSeen',
    'GROUND_COLOURS','GROUND_UNSEEN','walkColumnFaces','columnChunkIds','columnChunkBox',
    'baselineHeightAt','walkCutSurface','cutWallBands','cutRimSegments',code+
    '\nreturn {markColumnFaces,buildColumnFaces,buildCutFaces};')(ground,scene,trace,THREE,x=>x,()=>true,
      [new THREE.Color('#8996a6')],new THREE.Color('#2b2f36'),walkColumnFaces,columnChunkIds,columnChunkBox,
      baselineHeightAt,walkCutSurface,cutWallBands,cutRimSegments);
  const build=surface==='cuts'?buildCutFaces:buildColumnFaces;
  markColumnFaces([0,0,g.nx,g.nz],0);build();
  assert.equal(ground.faceChunks.size,6);const before=new Map(ground.faceChunks);
  const disposed=[];for(const [id,mesh] of before)mesh.geometry.addEventListener('dispose',()=>disposed.push(id));
  const c=12*g.nx+31;H[c]=.2;markColumnFaces([31,12,1,1]);build();
  assert.deepEqual(disposed,[0,1]);
  for(const id of [2,3,4,5])assert.equal(ground.faceChunks.get(id),before.get(id));
  assert.equal(scene.children.length,6,'replacement does not retain stale meshes');
  const rays=[];for(const mesh of ground.faceChunks.values()){mesh.updateMatrixWorld();rays.push(mesh);}
  const ray=new THREE.Raycaster(new THREE.Vector3(31*.25,.5,12*.25),new THREE.Vector3(1,0,0));
  assert.equal(ray.intersectObjects(rays)[0].distance,.125,'new seam wall is present');
  assert.equal(trace.terrain[1].chunks,2);
  assert.ok(trace.terrain[1].vertices<trace.terrain[0].vertices);
  for(const mesh of ground.faceChunks.values())mesh.geometry.dispose();ground.faceMaterial.dispose();ground.materialCells.material.dispose();
});

test('shipped exploration repaints changed cells even when the known count stays constant',()=>{
  const source=readFileSync(new URL('../playground/world.js',import.meta.url),'utf8');
  const part=(start,end)=>source.slice(source.indexOf('function '+start),source.indexOf('function '+end));
  const g={nx:65,nz:34,dx:.25,x0:0,z0:0,surface:'columns'},count=g.nx*g.nz;
  const seen=new Uint8Array(count).fill(1),colors=new Float32Array(3*count),attribute=new THREE.BufferAttribute(new Float32Array(12*count),3);
  const sight={nx:g.nx,nz:g.nz,cell_m:.25,x0_m:0,z0_m:0,known:count};
  const painted=[];
  const ground={grid:g,seen,seenGrid:sight,colors,surfaces:new Uint8Array(count).fill(1),runs:null,
    mesh:{geometry:{attributes:{color:attribute}}},materialCells:{update:k=>painted.push(k)},dirtyFaceChunks:new Set()};
  const code=part('groundSeen','groundKind')+part('groundKind','decodeRuns')+
    part('markColumnFaces','buildColumnFaces')+part('showSeen','drawTerrain');
  const {showSeen}=new Function('ground','bytesOf','GROUND_COLOURS','GROUND_UNSEEN','columnChunkIds','minimap',code+
    '\nreturn {showSeen};')(ground,x=>Uint8Array.from(Buffer.from(x,'base64')),
      [new THREE.Color('#8996a6'),new THREE.Color('#875132')],new THREE.Color('#2b2f36'),columnChunkIds,{dirty:false});
  const first=seen.slice(),a=12*g.nx+31,b=a+1;first[a]=0;
  const block={...sight,known_cells:count-1,cells:count,seen_b64:Buffer.from(first).toString('base64')};
  showSeen(block);assert.deepEqual(painted,[a]);assert.deepEqual([...ground.dirtyFaceChunks],[0]);
  ground.dirtyFaceChunks.clear();painted.length=0;const second=seen.slice();second[b]=0;
  showSeen({...block,seen_b64:Buffer.from(second).toString('base64')});
  assert.deepEqual(painted,[a,b]);assert.deepEqual([...ground.dirtyFaceChunks],[0,1]);
  const version=attribute.version;ground.dirtyFaceChunks.clear();painted.length=0;
  showSeen({...block,seen_b64:Buffer.from(second).toString('base64')});
  assert.equal(attribute.version,version);assert.deepEqual(painted,[]);assert.equal(ground.dirtyFaceChunks.size,0);
});

test('visible material identities remain distinct and samples resolve native ore names',()=>{
  assert.equal(materialAppearance('ore'),materialAppearance('copper ore'));
  assert.equal(materialAppearance('oxidised ore'),GROUND_APPEARANCE[7]);
  assert.equal(materialAppearance('unimplemented gold'),null);
  const primary=[0,1,2,5,6].map(i=>new THREE.Color('#'+GROUND_APPEARANCE[i].color));
  for(let i=0;i<primary.length;i++)for(let j=i+1;j<primary.length;j++) {
    const a=primary[i],b=primary[j];
    assert.ok(Math.hypot(a.r-b.r,a.g-b.g,a.b-b.b)>.15,'primary materials need separate linear color values');
  }
  assert.equal(new Set([0,1,2,5,6].map(i=>GROUND_APPEARANCE[i].pattern)).size,5,
    'color is reinforced by a different pattern for each primary ground material');
});

test('tool feedback cannot follow a neighboring cell, changed layer or moved observer',()=>{
  const grid={x0:0,z0:0,dx:.25,nx:3,nz:3}, point=[.124,1,.25],eyes=[0,2,0];
  const feedback={tool:'Custom spade',ready:true,state:'ready',action:'Loosen',materials:['sand']};
  const target={feedback,observed_at_m:point,observed_from_m:eyes,observed_name:null,
    target:{material:'sand'}};
  const model={grid,point,eyes,tool:'Custom spade',target,surface:'sand'};
  assert.equal(toolTargetFeedback(model),feedback);
  for(const change of [{point:[.126,1,.25]},{point:[.124,.96,.25]},
    {eyes:[0,2,.4]},{surface:'soil'},{context:'changed run depths'},
    {target:{...target,observed_from_m:null}}]) {
    const next=toolTargetFeedback({...model,...change});
    assert.equal(next.ready,false);assert.equal(next.state,'checking');assert.deepEqual(next.materials,[]);
  }
  const full={...target,target:null,feedback:{...feedback,ready:false,state:'blocked',action:'Free load space',materials:[]}};
  assert.equal(toolTargetFeedback({...model,target:full}).action,'Free load space',
    'early native load refusal still belongs to its observed sight point');
  const absent=toolTargetFeedback({...model,tool:null});
  assert.equal(absent.action,'Hold a digging tool');assert.equal(absent.screen,'inventory');assert.equal(absent.ready,false);
});

test('object readiness belongs to the observed object and preserves the server refusal',()=>{
  const point=[0,1,0],eyes=[0,2,0];
  const feedback={tool:'Custom pick',ready:false,state:'blocked',action:'Cannot strike',materials:[],reason:'Out of reach'};
  const target={feedback,observed_at_m:point,observed_from_m:eyes,observed_name:'lamp'};
  const model={point,eyes,tool:'Custom pick',target,name:'lamp'};
  assert.equal(toolTargetFeedback(model),feedback);
  assert.equal(toolTargetFeedback({...model,name:'rover'}).state,'checking');
});

test('collection feedback requires a closed native receipt and retains its actual measured mass',()=>{
  const result={kind:'broke out',open:false,loosened_kg:.08,loosened:{soil_m3:.00005}};
  assert.deepEqual(collectedToolMaterials({result}),{kg:.08,materials:['soil']});
  assert.deepEqual(collectedToolMaterials({result:{...result,loosened:{soil_m3:.00005,sand_m3:.0001}}}),
    {kg:.08,materials:['sand','soil']},'display never recalculates mass from guessed densities');
  for(const change of [{open:true},{kind:'met no ground'},{loosened_kg:0},{loosened_kg:NaN},{loosened:{}}])
    assert.equal(collectedToolMaterials({result:{...result,...change}}),null);
  assert.equal(collectedToolMaterials({result,refused:'Load full'}),null);
  assert.equal(collectedToolMaterials({gather:{materials:['sand'],kg:10}}),null);
});

test('column boundaries agree at negative coordinates and reject both outer axes',()=>{
  const g={x0:-1,z0:-2,dx:.25,nx:3,nz:2};
  assert.equal(terrainCellAt(-1,-2,g),0);
  assert.equal(terrainCellAt(-.876,-2,g),0);
  assert.equal(terrainCellAt(-.875,-2,g),1);
  assert.equal(terrainCellAt(-.75,-1.75,g),4);
  assert.equal(terrainCellAt(-1.126,-2,g),-1);
  assert.equal(terrainCellAt(-1,-1.624,g),-1);
});

test('target perimeter follows an analytical sloping surface rather than a flat tile',()=>{
  const g={x0:0,z0:0,dx:.25,nx:3,nz:3};
  const at=[.25,0,.25],height=(x,z)=>2*x+3*z;
  const path=terrainTargetPath(at,g,height);
  assert.equal(path.length,27);
  assert.deepEqual(path.slice(0,3),[.125,.637,.125]);
  assert.deepEqual(path.slice(-3),path.slice(0,3));
  for(let k=0;k<path.length;k+=3)assert.ok(Math.abs(path[k+1]-height(path[k],path[k+2])-.012)<1e-12);
  assert.equal(terrainTargetPath([0,0,99],g,height),null);
  const edge=terrainTargetPath([0,0,0],g,height);
  for(let k=0;k<edge.length;k+=3)assert.ok(edge[k]>=0 && edge[k+2]>=0);
});

test('exposed bands and underground floors/roofs identify their solid material',()=>{
  const runs={stride:4,count:[4],kind:[0,6,8,1],top:[-2,0,1,2]};
  assert.equal(exposedRunKind(runs,0,-3,2),0);
  assert.equal(exposedRunKind(runs,0,-1,2),6);
  assert.equal(exposedRunKind(runs,0,0,2),6,'void floor is the solid underneath');
  assert.equal(exposedRunKind(runs,0,1,2),1,'void roof is the solid above');
  assert.equal(exposedRunKind(runs,0,2,2),1);
  assert.equal(exposedRunKind(null,0,2,2),2);
});

test('palette edits and exploration updates retain sharp nearest-column lookup without changing input geometry',()=>{
  const grid={x0:0,z0:0,dx:.25,nx:2,nz:2};
  const colors=new Float32Array([.2,.1,.05,.8,.6,.2,.2,.4,.3,.1,.1,.1]);
  const before=colors.slice(),kinds=[1,2,6,0],seen=[true,true,true,false];
  const surface=terrainMaterial(grid,colors,i=>kinds[i],i=>seen[i]);
  const texture=surface.material.userData.terrainTexture;
  assert.equal(texture.magFilter,THREE.NearestFilter);
  assert.equal(texture.minFilter,THREE.NearestFilter);
  assert.equal(texture.generateMipmaps,false);
  assert.deepEqual([...texture.image.data],[51,26,13,1,204,153,51,2,51,102,77,6,26,26,26,255]);
  seen[3]=true;kinds[3]=5;colors.set([.4,.1,.3],9);surface.update(3);
  assert.deepEqual([...texture.image.data.slice(12)],[102,26,77,5]);
  assert.deepEqual(colors.slice(0,9),before.slice(0,9));
  assert.equal(grid.dx,.25);
  let disposed=false;texture.addEventListener('dispose',()=>disposed=true);surface.dispose();
  assert.ok(disposed);surface.material.dispose();
});


test('target dwell waits 1.5s; data refresh does not flicker; movement and leaving reset it',()=>{
  const dwell=makeTargetHover(),sight={key:'sand:1',x:50,y:50,eyes:[0,1.62,0]};
  assert.equal(dwell(0,sight),false);assert.equal(dwell(1499,sight),false);
  assert.equal(dwell(1500,{...sight,readiness:'ready'}),true);
  assert.equal(dwell(2000,{...sight,x:55}),true,'small pointer jitter is tolerated');
  assert.equal(dwell(2100,{...sight,x:70}),false);
  assert.equal(dwell(4000,{...sight,key:'other'}),false);
  assert.equal(dwell(5600,{...sight,key:'other'}),true);
  assert.equal(dwell(5700,{...sight,key:'other',eyes:[.1,1.62,0]}),false);
  assert.equal(dwell(7000,null),false);assert.equal(dwell(9000,sight),false);
});

test('collection totals closed native meetings within a use rather than just the last one',()=>{
  const first={open:false,kind:'broke out',loosened_kg:2,loosened:{sand_m3:.001}};
  const second={...first,loosened_kg:1,loosened:{soil_m3:.001}};
  assert.deepEqual(collectedToolMaterials({result:second,results:[first,second,{...first,open:true}]}),
    {kg:3,materials:['sand','soil']});
  assert.equal(collectedToolMaterials({results:[first],refused:'blocked'}),null);
});
