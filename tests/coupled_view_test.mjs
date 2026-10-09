import assert from 'node:assert/strict';
import * as THREE from '../playground/vendor/three.module.js';
import {ballObservation,cameraFrame,settingsDiffer,remainingSteps,computePace} from '../client/voxel-lab/coupled-view.mjs';
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
