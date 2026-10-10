import assert from 'node:assert/strict';
import * as THREE from '../playground/vendor/three.module.js';
import {ballObservation,cameraFrame,settingsDiffer,remainingSteps,computePace,dropMilestones,AcceptedReplay,interactionLoads,loadColor} from '../client/voxel-lab/coupled-view.mjs';
const plane={shape:'plane',position_m:[0,0,0],quaternion_wxyz:[1,0,0,0],size_m:[.3,.001,.3],radius_m:0};
const cube={shape:'cube',position_m:[0,.03,0],quaternion_wxyz:[1,0,0,0],size_m:[.03,.01,.03],radius_m:0};
const sphere={shape:'sphere',position_m:[0,10.045,0],quaternion_wxyz:[1,0,0,0],size_m:[.02,.02,.02],radius_m:.01,velocity_m_s:[0,0,0]};
const initial={cells:[plane,cube,sphere],time_s:0};
const snapshot=JSON.stringify(initial),o=ballObservation(initial);
assert.equal(o.gap_m,10);assert.equal(o.contact,false);assert.ok(Math.abs(o.gravity_estimate_s-Math.sqrt(20/9.81))<1e-14);
// Ten steps are 0.041667 s and only 8.516 mm of gravity-only fall.
const elapsed=10/240,fallen=.5*9.81*elapsed**2;
const later=structuredClone(initial);later.time_s=elapsed;later.cells[2].position_m[1]-=fallen;later.cells[2].velocity_m_s[1]=-9.81*elapsed;
assert.ok(Math.abs(ballObservation(later).gap_m-(10-fallen))<1e-14);
assert.ok(Math.abs(ballObservation(later).gravity_estimate_s-(o.gravity_estimate_s-elapsed))<1e-14);
assert.equal(JSON.stringify(initial),snapshot);
const supportOnly=structuredClone(initial);supportOnly.cells[1].position_m[1]=.004;
assert.equal(ballObservation(supportOnly).contact,false,'support/ground contact is not ball contact');
const contact=structuredClone(initial);contact.cells[2].position_m[1]=.044;
assert.ok(Math.abs(ballObservation(contact).gap_m+.001)<1e-14);assert.equal(ballObservation(contact).contact,true);
const rotated=structuredClone(initial);rotated.cells[1].size_m=[.04,.01,.03];rotated.cells[1].quaternion_wxyz=[Math.SQRT1_2,0,0,Math.SQRT1_2];rotated.cells[2].position_m[1]=.061;
assert.ok(Math.abs(ballObservation(rotated).gap_m-.001)<1e-14,'rotated OBB surface');
for(const aspect of [.5,1.3,2])for(const mode of ['target','ball','overview']) {
  const f=cameraFrame(initial.cells,mode),camera=new THREE.PerspectiveCamera(40,aspect,.0001,Math.max(100,f.radius*4));
  const r=f.radius*Math.max(1,1.3/aspect),yaw=.5,pitch=.55;
  camera.position.set(f.center[0]+Math.sin(yaw)*Math.cos(pitch)*r,f.center[1]+Math.sin(pitch)*r,f.center[2]+Math.cos(yaw)*Math.cos(pitch)*r);camera.lookAt(new THREE.Vector3(...f.center));camera.updateMatrixWorld();
  const indices=mode==='target'?[1]:mode==='ball'?[2]:[1,2];
  for(const i of indices){const p=new THREE.Vector3(...initial.cells[i].position_m).project(camera);assert.ok(Math.abs(p.x)<1&&Math.abs(p.y)<1&&p.z>-1&&p.z<1,[aspect,mode,i]);}
  if(mode==='target'){assert.ok(f.radius<.2,'10 m drop must not shrink the target view');}
  if(mode==='ball'){assert.ok(f.radius<.1,'ball focus must resolve the actual ball');}
}
assert.equal(JSON.stringify(initial),snapshot,'camera framing mutated physics');
// Ground-only drops formerly excluded the plane from overview, making it
// another ball close-up. Both references must remain inside the full view.
const groundOnly=[plane,sphere],f=cameraFrame(groundOnly,'overview');
assert.ok(f.center[1]>4&&f.center[1]<6&&f.radius>10);
assert.equal(dropMilestones(initial,later,null).after,'Not reached');
const bounced=structuredClone(initial);bounced.time_s=2;bounced.cells[2].velocity_m_s[1]=8;
assert.equal(dropMilestones(initial,bounced,{time_s:1.43}).after,'Rebounding · 8.00 m/s');
assert.equal(dropMilestones(initial,bounced,{time_s:1.43}).contact,'Observed at 1.4300 s');
assert.equal(settingsDiffer({height_m:.001,dt_s:1/240},{height_m:10,dt_s:1/240}),true);
assert.equal(settingsDiffer({height_m:10,dt_s:1/240,device:'cuda:0'},{height_m:10,dt_s:1/240}),false);
assert.equal(remainingSteps({time_s:2-1e-15,dt_s:1/1920}),0);
assert.equal(remainingSteps({time_s:0,dt_s:1/1920}),3840);
assert.equal(settingsDiffer({representation_policy:'coupled-reference'},{representation_policy:'partitioned-flight'}),true,'representation change requires a new scene');
assert.equal(computePace(1.425/43),'30.2× slower than realtime');
assert.equal(computePace(1),'Realtime');
assert.equal(computePace(3),'3.0× faster than realtime');
for(const ratio of [null,undefined,0,-1,Infinity,NaN])assert.equal(computePace(ratio),'Not measured');
console.log('PASS 10 m visibility, physical-time/flight estimates, true ball contact, rotated geometry and three camera aspects');

// Fast calculation must still show actual intermediate poses at physical pace.
const {AcceptedReplay:Replay}=await import('../client/voxel-lab/coupled-view.mjs');
const replay=new Replay();replay.reset(initial);
for(let i=1;i<=480;i++){const frame=structuredClone(initial);frame.time_s=i/240;frame.cells[2].position_m[1]=10-.5*9.81*frame.time_s**2;replay.push(frame);}
replay.start(1000);let shown=replay.sample(1500);
assert.equal(shown.time_s,.5);assert.equal(shown.cells[2].position_m[1],10-.5*9.81*.5**2);
assert.equal(replay.sample(3000).time_s,2);assert.equal(replay.sample(9000).time_s,2,'no extrapolation');
assert.ok(replay.frames.length<=481);
replay.reset(initial);replay.push(later);replay.start(0);
assert.equal(replay.sample(1000),later,'stall at latest measured data');
replay.push(contact); // contact time is zero; stale frames must not replace latest.
assert.equal(replay.latest,later);
replay.stop();assert.equal(replay.sample(2000),null);
assert.equal(JSON.stringify(initial),snapshot,'playback cannot change native state');
console.log('PASS physical-paced exact accepted-frame replay, bounded sampling, stalled delivery and no extrapolation');

// Regression for the reported phone failure: overview fits the ball but makes
// it subpixel. The default ball frame must resolve the actual sphere.
for(const [width,height] of [[390,464],[844,320]]){
  const frame=cameraFrame([plane,sphere],'ball'),r=frame.radius*Math.max(1,1.3/(width/height));
  const pixels=height*sphere.radius_m/(r*Math.tan(20*Math.PI/180));
  assert.ok(pixels>40,`ball diameter ${pixels}px must be visible on ${width}x${height}`);
}
const {readFileSync}=await import('node:fs');
const html=readFileSync(new URL('../client/voxel-lab/coupled.html',import.meta.url),'utf8');
const ids=[...html.matchAll(/ id="([^"]+)"/g)].map(m=>m[1]);
assert.equal(new Set(ids).size,ids.length,'duplicate controls can silently leave the visible button disabled');
const client=readFileSync(new URL('../client/voxel-lab/coupled.js',import.meta.url),'utf8');
for(const ref of client.matchAll(/\$\('([^']+)'\)/g))assert.ok(ids.includes(ref[1]),`missing UI control ${ref[1]} prevents startup`);
for(const id of ['reset','full-drop','replay','stop'])assert.ok(html.indexOf(`id="${id}"`)<html.indexOf('<aside>'),'primary action must remain beside the mobile scene');
console.log('PASS actual-ball pixel visibility at phone aspects and unique scene-adjacent controls');
// Actual accepted loads, including the fixed reaction, map to their own cells.
// Torque remains in the receipt; the displayed quantity is force in N only.
const loaded={...initial,interaction_wrench_n_nm:[[0,-10,0,0,0,0],[3,4,0,99,0,0],[0,10,0,0,0,0]]};
const savedLoad=JSON.stringify(loaded);
assert.deepEqual(interactionLoads(loaded),[10,5,10]);
assert.deepEqual(interactionLoads({...initial,substep_accounts:[{interaction_wrench_n_nm:loaded.interaction_wrench_n_nm}]}),[10,5,10]);
assert.equal(interactionLoads(initial),null,'no guessed stress/heat from poses or material names');
assert.equal(interactionLoads({...loaded,interaction_wrench_n_nm:[[NaN,0,0,0,0,0]]}),null);
assert.equal(interactionLoads({...loaded,interaction_wrench_n_nm:loaded.interaction_wrench_n_nm.slice(1)}),null,'mapping mismatch');
assert.deepEqual(loadColor(10,10),[1,0,0]);assert.deepEqual(loadColor(5,10),[1,1,0]);
assert.deepEqual(loadColor(20,10),[1,0,0]);assert.deepEqual(loadColor(0,10),loadColor(NaN,10));
assert.equal(JSON.stringify(loaded),savedLoad,'heat map must never modify accepted physics');
console.log('PASS accepted load/matter mapping, fixed reactions, missing-data refusal and read-only load colors');
