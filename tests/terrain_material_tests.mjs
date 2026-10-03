import assert from 'node:assert/strict';
import {test} from 'node:test';
import * as THREE from '../playground/vendor/three.module.js';
import {GROUND_APPEARANCE,materialAppearance,terrainCellAt,terrainTargetPath,exposedRunKind} from '../playground/material_appearance.js';
import {terrainMaterial} from '../playground/terrain_material.js';

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
