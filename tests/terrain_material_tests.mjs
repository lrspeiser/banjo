import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import * as THREE from '../playground/vendor/three.module.js';
import {GROUND_APPEARANCE,materialAppearance,terrainCellAt,terrainTargetPath,exposedRunKind} from '../playground/material_appearance.js';
import {terrainMaterial} from '../playground/terrain_material.js';

test('shipped full-terrain catchup reuses the mesh and streams variable runs once',()=>{
  const source=readFileSync(new URL('../playground/world.js',import.meta.url),'utf8');
  const part=(start,end)=>source.slice(source.indexOf('function '+start),source.indexOf('function '+end));
  const code=part('decodeRuns','runsRoom')+part('patchRuns','standingOn')+
    part('patchTerrain','extendShore');
  let rebuilt=0,paints=0,normals=0;
  const ground={grid:{nx:3,nz:2,dx:.25,x0:0,z0:0},floor:-3,
    runs:{stride:4,count:new Uint8Array(6),kind:new Uint8Array(24),top:new Float32Array(24)},
    heights:new Float32Array(6),surfaces:new Uint8Array(6),water:{identity:'keep water'},
    seen:new Uint8Array([1,0,1,1,1,1]),materialCells:{update:()=>paints++},mesh:{geometry:{
      attributes:{position:{array:new Float32Array(18)},color:{array:new Float32Array(18)}},
      computeVertexNormals:()=>normals++,computeBoundingSphere:()=>{}}}};
  const bytesOf=x=>new Uint8Array(Buffer.from(x,'base64'));
  const {refreshTerrain}=new Function('ground','bytesOf','paintGround','drawTerrain',code+
    '\nreturn {refreshTerrain};')(ground,bytesOf,()=>{},()=>rebuilt++);
  const heights=Buffer.from(new Float32Array([1,2,3,4,5,6]).buffer).toString('base64');
  const raw=[];
  for(let c=0;c<6;c++) {
    const n=c===3?5:2;raw.push(n);
    for(let k=0;k<n;k++)raw.push(k===n-1?(c%2?1:2):0,100+k*20,0);
  }
  const block={grid:{nx:3,nz:2,cell_m:.25,x0_m:0,z0_m:0},floor_m:-3,
    heights_b64:heights,ground_b64:Buffer.from([2,1,2,1,2,1]).toString('base64'),
    runs_b64:Buffer.from(raw).toString('base64')};
  const mesh=ground.mesh,water=ground.water,seen=ground.seen;
  refreshTerrain(block);
  assert.equal(rebuilt,0);assert.equal(paints,6);assert.equal(normals,1);
  assert.equal(ground.mesh,mesh);assert.equal(ground.water,water);assert.equal(ground.seen,seen);
  assert.deepEqual([...ground.heights],[1,2,3,4,5,6]);assert.equal(ground.runs.count[3],5);
  for(let c=0;c<6;c++)assert.equal(ground.runs.kind[c*ground.runs.stride+ground.runs.count[c]-1],c%2?1:2);
  assert.equal(ground.facesStale,true);
  refreshTerrain({...block,grid:{...block.grid,cell_m:.5}});assert.equal(rebuilt,1);
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
