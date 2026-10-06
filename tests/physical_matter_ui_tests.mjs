import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import * as THREE from '../playground/vendor/three.module.js';

const threeURL=new URL('../playground/vendor/three.module.js',import.meta.url).href;
async function load(name) {
  const source=(await readFile(new URL('../playground/'+name,import.meta.url),'utf8'))
    .replace(/(['"])\/vendor\/three.module.js\1/,JSON.stringify(threeURL));
  return import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
}
const storage=new Map();
globalThis.localStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)};
globalThis.location={search:'?world=renderer-regression'};

const {makePhysicalGround,looseGroundLabel}=await load('physical_matter.js');
assert.equal(looseGroundLabel({physical_ground:true},{kg:25,materials:['soil']},kg=>`${kg} kg`),
  'Loose soil · 25 kg · click to collect');
assert.equal(looseGroundLabel({cut:{body_id:8,mass_kg:37.5,ground:'rock'}},null,kg=>`${kg} kg`),
  'Loose rock · 37.5 kg · click to collect');
assert.equal(looseGroundLabel({physical_ground:true},{kg:0,materials:['soil']},String),null);
const scene=new THREE.Scene(),world={session:'native-session'};
const sent=[],notices=[];
let fail=true;
const adapter=makePhysicalGround({scene,world,camera:new THREE.PerspectiveCamera(),
  whereIAm:()=>({eyes_m:[0,1,3]}),lastAction:text=>notices.push(text),
  api:async(path,body)=>{
    sent.push({path,body});
    if(fail)throw Error('Save reply lost');
    return {ok:true,session:'saved-native-session',packet:{mass_kg:12,cells:[{run_kind:0,material:'concrete'}]}};
  }});
const body={id:7,source_center_m:[10,2,0],pose:{center_m:[0,1,0],orientation_wxyz:[1,0,0,0]},
  velocity_m_s:[999,999,999],cells:[
    {run_kind:0,material:'concrete',source_center_m:[10,2,0],size_m:[.5,.25,.75]},
    {run_kind:1,material:'soil',source_center_m:[10.5,2.25,0],size_m:[.25,.25,.25]}]};
adapter.follow({schema:'banjo.ground-debris.v1',bodies:[body]});
const group=adapter.bodies.get(7).group;
assert.deepEqual(group.position.toArray(),body.pose.center_m);
assert.equal(group.children[0].material.color.getHex(),0x8d9197);
assert.equal(group.children[1].material.color.getHex(),0x745037);
const matrix=new THREE.Matrix4();group.children[0].getMatrixAt(0,matrix);
const position=new THREE.Vector3(),quaternion=new THREE.Quaternion(),scale=new THREE.Vector3();
matrix.decompose(position,quaternion,scale);
assert.deepEqual(position.toArray(),[0,0,0]);assert.deepEqual(scale.toArray(),[.5,.25,.75]);
group.children[1].getMatrixAt(0,matrix);matrix.decompose(position,quaternion,scale);
assert.deepEqual(position.toArray(),[.5,.25,0]);
// High receipt velocity creates no launch animation. Repeated packets stay
// at the supplied native pose; only an actual new pose moves the group.
adapter.follow({schema:'banjo.ground-debris.v1',bodies:[body]});
assert.deepEqual(group.position.toArray(),[0,1,0]);
const moved={...body,pose:{center_m:[1,1,0],orientation_wxyz:[Math.SQRT1_2,0,Math.SQRT1_2,0]}};
adapter.follow({schema:'banjo.ground-debris.v1',bodies:[moved]});
assert.deepEqual(group.position.toArray(),[1,1,0]);
assert.deepEqual(group.quaternion.toArray(),[0,Math.SQRT1_2,0,Math.SQRT1_2]);
assert.equal(adapter.pick(new THREE.Vector3(1,1,2),new THREE.Vector3(0,0,-1),3).id,7);
await assert.rejects(adapter.collect({id:7}),/Save reply lost/);
assert.equal(adapter.bodies.has(7),true,'Failed collection keeps native geometry');
const pending=sent[0].body.request_id;assert.equal(storage.size,1);
fail=false;await adapter.collect({id:7});
assert.equal(sent[1].body.request_id,pending,'Uncertain collection retries the same receipt');
assert.equal(adapter.bodies.size,0);assert.equal(storage.size,0);
assert.equal(world.session,'saved-native-session');assert.match(notices[0],/Collected rock/);
adapter.follow({schema:'banjo.ground-debris.v1',bodies:[body]});
adapter.follow({schema:'banjo.ground-debris.v1',bodies:[{...body,cells:undefined,
  slabs:[{run_kind:0,source_center_m:[10,2,0],size_m:[.5,.25,.75]}]}]});
assert.equal(adapter.bodies.size,0,'Late full or compact ticks cannot resurrect confirmed collected IDs after session rotation');

let releaseMetadata,metadataCalls=0;
const compact={id:8,source_center_m:[0,0,0],pose:{center_m:[0,1,0],orientation_wxyz:[1,0,0,0]},
  cell_count:5,slabs:[{run_kind:2,material:'sand',source_center_m:[0,0,0],size_m:[.25,.05,.05]}]};
const detailed={...compact,cells:Array.from({length:5},(_,i)=>({run_kind:2,material:'sand',
  source_center_m:[-.1+.05*i,0,0],size_m:[.05,.05,.05]}))};
const compactAdapter=makePhysicalGround({scene:new THREE.Scene(),world:{session:'compact-session'},
  api:async()=>{metadataCalls++;return new Promise(resolve=>releaseMetadata=resolve);}});
compactAdapter.follow({schema:'banjo.ground-debris.v1',bodies:[compact]});
const compactGroup=compactAdapter.bodies.get(8).group;
assert.equal(compactGroup.children[0].count,1,'Compact native slab is visible immediately');
assert.equal(compactGroup.children[0].material.color.getHex(),0xd2b877);
compactAdapter.follow({schema:'banjo.ground-debris.v1',bodies:[{...compact,pose:{...compact.pose,center_m:[3,1,0]}}]});
releaseMetadata({ground_debris:{schema:'banjo.ground-debris.v1',bodies:[detailed]}});
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(compactGroup.children[0].count,5,'Full native cells upgrade the same body geometry');
assert.deepEqual(compactGroup.position.toArray(),[3,1,0],'Metadata cannot rewind a newer native pose');
for(let i=0;i<20;i++)compactAdapter.follow({schema:'banjo.ground-debris.v1',bodies:[compact]});
assert.equal(metadataCalls,1,'Ordinary compact poses cannot poll geometry every frame');
assert.equal(compactAdapter.bodies.get(8).body.cells.length,5,'Compact poses preserve full native metadata');
compactAdapter.follow({schema:'banjo.ground-debris.v1',bodies:[{...compact,id:9}]});
compactAdapter.follow({schema:'banjo.ground-debris.v1',bodies:[]});
releaseMetadata({ground_debris:{schema:'banjo.ground-debris.v1',bodies:[{...detailed,id:9}]}});
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(compactAdapter.bodies.size,0,'Late metadata cannot resurrect removed matter');

const {makeTools}=await load('tools.js');
const requests=[];
let reject=false;
let preflight=false;
const toolWorld={session:'tool-session',held:{name:'pick haft',pick:{}},
  use:{mode:'tool-ready',target:{cadence_hz:10000}}};
const noOp=()=>{};
const tool=makeTools({world:toolWorld,scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(),
  act:async()=>{throw Error('Explicit targets must not repick');},
  api:async(path,body)=>{requests.push(body);if(reject)throw Error('Cut save pending');return preflight?
    {refused:'Move closer to the original target',action:'Cut',repeat:false}:
    {refused:'No banked energy',action:'Cut',repeat:false,cut:{supported:false,kind:'no energy'}};},
  whereIAm:()=>({eyes_m:[0,1,0]}),showUse:noOp,say:noOp,remember:noOp,lastAction:noOp,
  carryGround:noOp,showInventory:noOp,groundTargetPoint:at=>at.map(value=>value+.01)});
async function stroke(at_m,target_name=null) {
  toolWorld.use.mode='tool-ready';tool.press({at_m,target_name});tool.release();
  for(let n=0;n<100 && (toolWorld.use.timer || toolWorld.use.mode==='tool-working');n++)
    await new Promise(resolve=>setTimeout(resolve,2));
  assert.equal(toolWorld.use.mode,'tool-ready');
}
await stroke([1,0,1]);
assert.equal(requests.at(-1).energy_assist,false);assert.equal(storage.size,0);
storage.set('banjo.energy-assist','on');await stroke([1,0,1],'actual-object');
assert.equal(requests.at(-1).energy_assist,false);assert.equal(requests.at(-1).target_name,'actual-object');
assert.equal(storage.size,1,'Object contact cannot allocate a ground work request');
await stroke([1,0,1]);
assert.equal(requests.at(-1).energy_assist,true);assert.equal(requests.at(-1).target_name,null);
assert.equal(storage.size,1,'A completed empty-wallet refusal clears pending cut');
reject=true;await stroke([2,0,2]);
const original=requests.at(-1);assert.equal(storage.size,2);
reject=false;preflight=true;await stroke([99,99,99],'unrelated-object');
assert.deepEqual(requests.at(-1).at_m,original.at_m);
assert.equal(requests.at(-1).request_id,original.request_id);
assert.equal(requests.at(-1).target_name,null);
assert.equal(storage.size,2,'A preflight refusal cannot resolve a lost paid reply');
preflight=false;await stroke([99,99,99],'unrelated-object');
assert.equal(requests.at(-1).request_id,original.request_id);
assert.equal(storage.size,1);
reject=true;await stroke([3,0,3]);
storage.set('banjo.energy-assist','off');const count=requests.length;
await stroke([99,99,99],'unrelated-object');assert.equal(requests.length,count);
assert.match(toolWorld.use.result,/Turn Energy assist on to retry/);
assert.equal(storage.size,2,'Turning assistance off cannot discard an uncertain debit');
tool.stop();
console.log('PASS: exact native cells/poses, durable collection, explicit assist, empty-wallet refusal and retained ground targets');
