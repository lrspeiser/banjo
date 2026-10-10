import assert from 'node:assert/strict';
import fs from 'node:fs';
import {acceptedFrameIndex,verifyMechanismReceipt,mechanismMotionFrame} from '../client/voxel-lab/mechanisms-view.mjs';
const frame=(t,a=0,mode='articulated-hinge')=>({time_s:t,angle_rad:a,omega_rad_s:0,com_m:[.5*Math.sin(a),1.5-.5*Math.cos(a),0],velocity_m_s:[0,0,0],energy_j:1,mode,body_id:'mechanism-bar',matter_id:'mechanism-bar:occupied-box'});
const receipt={schema:'banjo-mechanism-reference-1',abi:1,native_sha256:'a'.repeat(64),source_sha256:'b'.repeat(64),geometry:{length_m:1,width_m:.1,thickness_m:.1,density_kg_m3:1000},mass_kg:10,audit:{accepted_time_s:1,dt_s:.01},frames:[frame(0),frame(.2,.1),frame(1,.2)]};
assert.equal(verifyMechanismReceipt(receipt),receipt);
assert.equal(acceptedFrameIndex(receipt.frames,-1),0);
assert.equal(acceptedFrameIndex(receipt.frames,.1999),0);
assert.equal(acceptedFrameIndex(receipt.frames,.2),1);
assert.equal(acceptedFrameIndex(receipt.frames,.999),1);
assert.equal(acceptedFrameIndex(receipt.frames,999),2); // Never extrapolate beyond accepted state.
for(const mutate of [r=>r.frames[1].com_m[0]=5,r=>r.mass_kg=2,r=>r.frames[1].mode='equilibrium-sleep',r=>r.frames[1].time_s=-1,r=>r.frames[1].velocity_m_s=null,r=>r.native_sha256='',r=>r.frames.pop(),r=>r.frames[0].matter_id='other']){
 const copy=structuredClone(receipt);mutate(copy);assert.throws(()=>verifyMechanismReceipt(copy));
}
const html=fs.readFileSync(new URL('../client/voxel-lab/mechanisms.html',import.meta.url),'utf8'),js=fs.readFileSync(new URL('../client/voxel-lab/mechanisms.js',import.meta.url),'utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(x=>x[1]);assert.equal(new Set(ids).size,ids.length);
for(const m of js.matchAll(/\$\('([^']+)'\)/g))assert.ok(ids.includes(m[1]),'Missing UI element '+m[1]);
console.log('Mechanism actual-pose, identity, sleep and physical-time replay checks passed');
const falling=structuredClone(receipt);falling.frames.push({...frame(2,0,'rigid-free'),com_m:[0,-4,0]});
for(const aspect of [1.8,.85]){const f=mechanismMotionFrame(falling,aspect);assert.ok(f.center[1]<0);assert.ok(f.distance>8);for(const state of falling.frames){const d=Math.hypot(...state.com_m.map((v,j)=>v-f.center[j]))+.51;assert.ok(d<f.distance*Math.sin(Math.PI/8)*Math.min(1,aspect),'full accepted fall must fit the fixed camera');}}
assert.ok(js.includes('if(followBody)target.fromArray'),'default camera must not cancel visible free fall');
console.log('Full physical fall remains visible at desktop and phone aspects');
