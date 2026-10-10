import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {scalar,columnTransform,frameAtTime} from '../client/voxel-lab/flow-view.mjs';
assert.equal(scalar([.2,.6,.8],'speed',1000),5);
assert.equal(scalar([.2,0,0],'pressure',1000),1962);
assert.equal(scalar([.2,0,0],'depth',1000),.2);
assert.equal(scalar([0,0,0],'speed',1000),0);
assert.throws(()=>scalar([-.2,0,0],'depth',1000));
assert.throws(()=>scalar([.2,NaN,0],'depth',1000));
const c=columnTransform(0,48,24,.1,.2);assert.ok(Math.abs(c.position[0]+2.35)<1e-12);assert.ok(Math.abs(c.position[2]+1.15)<1e-12);assert.equal(c.position[1],.1);assert.equal(c.scale[1],.2);
assert.equal(columnTransform(0,48,24,.1,0).scale[0],0);
assert.throws(()=>columnTransform(1152,48,24,.1,.1));
const frames=[0,.1,.3].map(time_s=>({account:{time_s}}));assert.equal(frameAtTime(frames,.05),0);assert.equal(frameAtTime(frames,.29),1);assert.equal(frameAtTime(frames,20),2);assert.equal(frameAtTime(frames,0,2),0);
const html=fs.readFileSync(new URL('../client/voxel-lab/flowing-matter.html',import.meta.url),'utf8'),js=fs.readFileSync(new URL('../client/voxel-lab/flowing-matter.js',import.meta.url),'utf8');
const ids=[...html.matchAll(/id="([^"]+)"/g)].map(x=>x[1]);assert.equal(new Set(ids).size,ids.length);
for(const match of js.matchAll(/\$\('([^']+)'\)/g))assert.ok(ids.includes(match[1]),'Missing DOM control '+match[1]);
assert.ok(html.includes('href="/thermal-fields"'));assert.ok(html.includes('href="/mechanisms"'));
console.log('Flow physical observation mapping, accepted replay clock and controls pass');

const sceneControls=html.match(/<section[^>]*id="view"[^>]*>([\s\S]*?)<\/section>/)[1];
for(const id of ['initial', 'calculate', 'continue', 'play', 'pause'])assert(sceneControls.includes(`id="${id}"`),`${id} must stay next to the 3D view`);
assert.ok(!/[\u00c2\u00c3]/.test(html),'HTML labels must not contain encoding corruption');

// Execute actual UI request/controller functions with a deferred HTTP response.
// This checks payload ownership and rollback, not a duplicated implementation.
const controls=Object.fromEntries(ids.map(id=>[id,{disabled:false,value:id==='duration'?'2':id==='density'?'1000':id==='left'?'.2':'0',textContent:'',max:'120',reportValidity:()=>true}]));
const old={ok:true,checkpoint:{old:'checkpoint'},instance:{id:'persistent',matter_ids:['water'],control_volume_ids:['column'],accepted_time_s:2},frames:[{account:{time_s:0}},{account:{time_s:2}}]};
let respond,requests=[];
const context=vm.createContext({controls,old,fetch:async(url,options)=>{requests.push({url,payload:JSON.parse(options.body)});return new Promise(resolve=>respond=resolve);},matchMedia:()=>({matches:false}),view:{scrollIntoView(){}},console});
vm.runInContext(`const $=id=>controls[id],nx=48,nz=24,dx=.1;let data=old,index=1,busy=false,playing=true,drag=null,initial=[[.2,0,0]];function show(){} function play(){playing=true;} ${js.slice(js.indexOf('function reset()'),js.indexOf("renderer.domElement.addEventListener('pointerdown'"))} ${js.slice(js.indexOf('function setBusy'),js.indexOf('function play()'))} globalThis.controller={run:calculateFlow,reset,paint:brushAt,state:()=>({data,index,busy,playing})};`,context);
const pending=context.controller.run(true);
assert.equal(requests.length,1);assert.equal(requests[0].url,'/api/flow-reference');assert.deepEqual(requests[0].payload,{declaration:{duration_s:2,frames:121},checkpoint:old.checkpoint});
assert.equal(context.controller.state().data,old);
context.controller.reset();context.controller.paint({});assert.equal(context.controller.state().data,old,'programmatic reset/paint must refuse while busy');
for(const id of ['initial','calculate','continue','brush','left','right','density','duration','paint-depth'])assert.equal(controls[id].disabled,true,id+' must be locked during native request');
await context.controller.run(false);assert.equal(requests.length,1,'busy UI must not send a second request');
const next={...old,checkpoint:{new:'checkpoint'},native_sha256:'0123456789abcdef',source_sha256:'source',law:'native',limits:[],measured:{physical_s:2},instance:{...old.instance,accepted_time_s:4},frames:[{account:{time_s:2}},{account:{time_s:4}}]};
respond({ok:true,json:async()=>next});await pending;
assert.equal(context.controller.state().data,next);assert.equal(context.controller.state().busy,false);assert.equal(controls.continue.disabled,false);assert.equal(controls.scrub.max,'1');assert.ok(controls.status.textContent.includes('4.000 s'));
const refused=context.controller.run(true);respond({ok:false,json:async()=>({ok:false,error:'work limit'})});await refused;
assert.equal(context.controller.state().data,next,'refusal must retain last accepted flow');assert.ok(controls.status.textContent.includes('Last accepted flow retained'));
const invalid=context.controller.run(true);respond({ok:true,json:async()=>({...next,instance:{...next.instance,id:'different'}})});await invalid;
assert.equal(context.controller.state().data,next,'identity mismatch must not install new flow');
assert.ok(controls.status.textContent.includes('identity changed'));
console.log('Actual Continue UI payload, busy lock, stable identity/cumulative clock and refusal rollback pass');
