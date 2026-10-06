import assert from 'node:assert/strict';
import {test,beforeEach,afterEach} from 'node:test';
import {readFile} from 'node:fs/promises';
import * as THREE from '../playground/vendor/three.module.js';
import {toolTargetFeedback} from '../playground/material_appearance.js';

const source=(await readFile(new URL('../playground/tools.js',import.meta.url),'utf8'))
  .replace('"/vendor/three.module.js"',JSON.stringify(new URL('../playground/vendor/three.module.js',import.meta.url).href));
const {makeTools}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

// The shipped browser client reads the explicit assist preference and its
// per-world retry key. Give each extracted-function test a fresh browser
// storage scope so an absent browser global cannot silently abort a use.
let oldStorage,oldLocation;
beforeEach(()=>{
  oldStorage=globalThis.localStorage;oldLocation=globalThis.location;
  const values=new Map();
  globalThis.localStorage={getItem:key=>values.get(key)??null,
    setItem:(key,value)=>values.set(key,String(value)),removeItem:key=>values.delete(key)};
  globalThis.location={search:'?world=tool-target-fixture'};
});
afterEach(()=>{
  if(oldStorage===undefined)delete globalThis.localStorage;else globalThis.localStorage=oldStorage;
  if(oldLocation===undefined)delete globalThis.location;else globalThis.location=oldLocation;
});

test('a step requested before pickup cannot discard its new grip; a later genuine release can',()=>{
  const noop=()=>{};let refreshed=0;
  const world={held:null,use:{mode:'none'}};
  const tools=makeTools({world,camera:new THREE.PerspectiveCamera(),carryGround:noop,
    showHolding:noop,showUse:noop,lastAction:noop,refreshInventory:()=>refreshed++});
  const beforePickup=world.held;
  world.held={name:'pick',pick:{object:'Field pick'}};
  world.use={mode:'tool-ready',name:'Field pick'};
  const adopted=world.held;
  tools.follow({hand:{holding:''}},beforePickup);
  assert.equal(world.held,adopted);assert.equal(refreshed,0);
  tools.follow({hand:{holding:''}},adopted);
  assert.equal(world.held,null);assert.equal(refreshed,1);
});

test('native tool release clears the hand and queued uses once, without regripping',()=>{
  let refreshed=0;const messages=[];const noop=()=>{};
  const world={held:{name:'pick',pick:{object:'Field pick'}},use:{mode:'tool-ready',name:'Field pick',queued:1,down:true}};
  const tools=makeTools({world,camera:new THREE.PerspectiveCamera(),carryGround:noop,
    showHolding:noop,showUse:noop,lastAction:text=>messages.push(text),refreshInventory:()=>refreshed++});
  tools.follow({hand:{holding:'pick'}});assert.ok(world.held);
  tools.follow({hand:{}});assert.ok(world.held,'missing hand fields are not proof of release');
  tools.follow({hand:{holding:''},player_hands:{peer:{holding:'peer pick'}}});
  assert.equal(world.held,null);assert.equal(world.use.mode,'none');
  assert.equal(refreshed,1);assert.match(messages[0],/left your hand.*press E/);
  assert.deepEqual(tools.hand(),{hand:null,hand_q:null});
  tools.follow({hand:{holding:''}});assert.equal(messages.length,1);
});

test('a refused registered pickup never falls through to an untracked native grip',async()=>{
  const full=(await readFile(new URL('../playground/world.js',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
  const code=full.slice(full.indexOf('async function takeIntoHand('),full.indexOf('// A hand in the middle',full.indexOf('async function takeIntoHand(')));
  const messages=[];let reply={ok:false,why:'That item belongs to another player'};
  const take=new Function('inventoryChange','lastAction',code+';return takeIntoHand;')(
    async()=>reply,text=>messages.push(text));
  assert.equal(await take('pick'),null);assert.equal(messages[0],reply.why);
  reply={ok:false,unknown:true};assert.equal(await take('loose fragment'),'not kept');
  reply={ok:true};assert.equal(await take('own pick'),'held');
});

test('bag pickup finds a nearby thin tool even when the centre ray misses its handle',async()=>{
  const full=(await readFile(new URL('../playground/world.js',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
  const code=full.slice(full.indexOf('async function toTheBag()'),full.indexOf('// 1-9:',full.indexOf('async function toTheBag()')));
  const requests=[];
  const pack=new Function('world','handBusy','tools','inventoryChange','titled','recordHolds','lastAction','sweepPiece','heldName',code+';return toTheBag;')(
    {held:null,aim:null,bodies:new Map([['pick',{}]])},()=>false,{nearTool:()=>({tool:'pick'})},
    async(...args)=>{requests.push(args);return {ok:true};},x=>x,()=>false,()=>{},()=>{},()=> '');
  await pack();assert.equal(requests[0][0],'take');assert.equal(requests[0][1],'pick');
});

test('an empty hand collects a pile, rechecking exact-ray occlusion and reach; a pick digs past it',async()=>{
  // A Windows checkout has CRLF line ends; the markers below are written with LF.
  const full=(await readFile(new URL('../playground/world.js',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
  const code=full.slice(full.indexOf('canvas.addEventListener("pointerdown", (e) => {'),full.indexOf('canvas.addEventListener("pointermove", (e) => {'));
  for(const mode of ['clear','occluded','far','input','pick','native']) {
    let callback, collected=0, nativeCollected=0, strokes=0;const requests=[],messages=[];
    const camera=new THREE.PerspectiveCamera();camera.position.set(0,1.62,0);
    const direction=new THREE.Vector3(1,-1,0).normalize();
    const pile={name:'soil pile',at_m:mode==='far'?[3,0]:[1,0]};
    const visual={pick:()=>({pile,distance:1.8,role:mode==='input'?'input':'stock'}),collectPile:async()=>{collected++;}};
    const nativeMatter={pick:(from,dir,max)=>{
      assert.deepEqual(from.toArray(),camera.position.toArray());
      assert.deepEqual(dir.toArray(),direction.toArray());assert.equal(max,4);
      return mode==='native'?{id:8,distance:1}:null;
    },collect:async hit=>{assert.equal(hit.id,8);nativeCollected++;}};
    const install=new Function('canvas','camera','aimVector','resourceVisuals','act','THREE','pressPrimary','lastAction','physicalGround','recordInteraction','$',
      'let cursorFree=false,resumeClick=false,primaryUsed=false,cursor,drag;const watchedId=null,looking=false;'+
      // With a digging tool in hand a click digs; a pile is for an empty hand
      // (the owner, 2026-10-04: digging past a pile collected it instead).
      'const world={held:'+(['pick','native'].includes(mode)?'{pick:{}}':'null')+'};'+
      'const cursorAt=e=>({px:e.clientX,py:e.clientY}),markAt=()=>{},offerStick=()=>{},setCursorFree=()=>{};'+
      full.slice(full.indexOf('function pointerToolTarget('),full.indexOf('function pressPrimary('))+code);
    install({addEventListener:(_,fn)=>{callback=fn;},setPointerCapture(){}},camera,()=>direction.clone(),visual,
      async(op,args)=>{requests.push(args);return mode==='occluded'?{hit:true,point_m:[.1,1.52,0]}:{hit:false};},THREE,
      ()=>{strokes++;return true;},message=>messages.push(message),nativeMatter,()=>{},()=>({dataset:{}}));
    callback({button:0,clientX:100,clientY:200});await new Promise(setImmediate);
    assert.equal(collected,mode==='clear'?1:0);
    assert.equal(nativeCollected,mode==='native'?1:0);
    if(mode==='native'){
      assert.equal(requests.length,1,'native collection rechecks exact-ray tool occlusion');
      assert.equal(requests[0].past_held,true);
      assert.equal(strokes,0,'a native piece click collects before using an equipped pick');continue;
    }
    if(mode==='pick'){assert.equal(requests.length,0,'a held pick does not stop at a pile');continue;}
    if(mode!=='input')assert.deepEqual(requests[0].dir,direction.toArray(),'native check uses the click ray');
    if(mode==='far')assert.match(messages[0],/within 2 m/);
  }
});

test('idle contact hand ignores hover targets before and after use',()=>{
  const camera=new THREE.PerspectiveCamera();camera.position.set(0,1.62,0);
  const world={held:{pick:{},axes:{x:new THREE.Vector3(1,0,0),y:new THREE.Vector3(0,-1,0),z:new THREE.Vector3(0,0,-1)}},
    use:{mode:'tool-ready',target:{gesture:'contact',ready:{hand:[1,-1,-1]}}}};
  const tools=makeTools({world,camera,whereIAm:()=>({eyes_m:camera.position.toArray()})});
  const pose=tools.hand();
  world.use.positioned=true;world.use.target.ready={hand:[-1,-4,1]};
  assert.deepEqual(tools.hand(),{hand:null,hand_q:null},'after use the native withdrawal remains in charge');
  world.use.rest=[1,.5,-1];world.use.restEyes=[0,1.62,0];
  assert.deepEqual(tools.hand(),{hand:[1,.5,-1],hand_q:null});
  camera.position.x=2;
  assert.deepEqual(tools.hand().hand,[3,.5,-1],'walking carries the resting hand without following hover');
  assert.equal(pose.hand_q.length,4,'carry requests a bounded wrist orientation above terrain');
  world.use.mode='tool-working';assert.deepEqual(tools.hand(),{hand:null,hand_q:null});
});

test('first-person render hides only held tool parts and restores visibility on failure',async()=>{
  // A Windows checkout has CRLF line ends; the markers below are written with LF.
  const full=(await readFile(new URL('../playground/world.js',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
  const code=full.slice(full.indexOf('function render()'),full.indexOf('// ---------------------------------------------------------------------------\n// The panel',full.indexOf('function render()')));
  const handle={visible:true},head={visible:true},peer={visible:true},pickedBox={visible:true};
  const pin={visible:true,userData:{follows:'head'}},peerPin={visible:true,userData:{follows:'peer'}},rope={visible:true};
  const world={held:{name:'handle',pick:{parts:['handle','head']}},joints:[{id:1,a:'head',b:'handle'}],bodies:new Map([
    ['handle',{mesh:handle}],['head',{mesh:head}],['peer',{mesh:peer}]])};
  const render=new Function('world','watchedId','pickedBox','picked','heldInTheWay','revealing','renderer','scene','camera','trace','pinGroup','ropeLines',code+';return render;')(
    world,null,pickedBox,{name:'handle'},()=>null,null,{render(){
      assert.equal(handle.visible,false);assert.equal(head.visible,false);assert.equal(pickedBox.visible,false);
      assert.equal(pin.visible,false);assert.equal(rope.visible,false);assert.equal(peerPin.visible,true);
      assert.equal(peer.visible,true);throw Error('test render failure');
    }},{},{},{renders:[]},{children:[pin,peerPin]},new Map([[1,rope]]));
  assert.throws(render,/test render failure/);
  for(const mesh of [handle,head,peer,pickedBox,pin,peerPin,rope])assert.equal(mesh.visible,true);
});

test('closed native outcomes are shown as they arrive and are not replayed by the final reply',async()=>{
  const oldSet=globalThis.setTimeout,oldClear=globalThis.clearTimeout;
  let timer,finish;const effects=[];
  globalThis.setTimeout=run=>{timer=run;return 1;};globalThis.clearTimeout=()=>{};
  try {
    const camera=new THREE.PerspectiveCamera();camera.position.set(0,1.62,0);
    const world={held:{name:'pick',pick:{}},use:{mode:'tool-ready',target:{cadence_hz:4}}};
    const noop=()=>{},receipt={tool:'pick',point:1,at_s:2,at_m:[1,0,0],open:false,kind:'broke out'};
    const tools=makeTools({world,camera,whereIAm:()=>({eyes_m:camera.position.toArray()}),
      api:()=>new Promise(resolve=>{finish=resolve;}),showUse:noop,showNotebook:noop,carryGround:noop,
      remember:noop,lastAction:noop,say:noop,showToolOutcome:(answer,point)=>effects.push({answer,point})});
    tools.press({at_m:[1,0,0]});tools.release();timer();await new Promise(setImmediate);
    tools.follow({ground_work:[{...receipt,open:true},{...receipt,tool:'peer'}]});assert.equal(effects.length,0);
    tools.follow({tool_outcomes:[receipt],ground_work:[receipt]});assert.equal(effects.length,1);
    tools.follow({ground_work:[receipt]});assert.equal(effects.length,1);
    finish({result:receipt,results:[receipt],gesture:'contact',rest_hand_m:[1,.5,0],said:'Done'});
    await new Promise(setImmediate);assert.equal(effects.length,1,'final reply must not duplicate streamed outcomes');
    assert.deepEqual(tools.hand().hand,[1,.5,0]);
  } finally {globalThis.setTimeout=oldSet;globalThis.clearTimeout=oldClear;}
});

test('queued keyboard actions follow sight; explicit pointer clicks retain their ray; all uses carry correlated diagnostics',async()=>{
  const oldSet=globalThis.setTimeout,oldClear=globalThis.clearTimeout;
  const timers=[];
  globalThis.setTimeout=run=>{const timer={run};timers.push(timer);return timer;};
  globalThis.clearTimeout=timer=>{if(timer)timer.cancelled=true;};
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  const runTimer=async()=>{const timer=timers.shift();assert.ok(timer);if(!timer.cancelled)timer.run();await flush();};
  try {
    const camera=new THREE.PerspectiveCamera();camera.position.set(0,1.62,0);
    let direction=new THREE.Vector3(.4,-.7,-1).normalize(),finish=null;
    const world={session:'test',held:{pick:{},name:'pick'},use:{mode:'tool-ready',target:{cadence_hz:4}}};
    const picks=[],uses=[],events=[];
    const noop=()=>{};
    const tools=makeTools({world,camera,aimVector:()=>direction.clone(),
      recordInteraction:event=>events.push(event),
      whereIAm:()=>({eyes_m:camera.position.toArray()}),
      act:async(op,args)=>{assert.equal(op,'pick');picks.push(args);
        return {hit:true,point_m:[args.dir[0],0,args.dir[2]]};},
      api:async(path,body)=>{assert.equal(path,'/api/world/tool/use');uses.push(body);
        return await new Promise(resolve=>{finish=()=>resolve({said:'Collected',repeat:true});});},
      showUse:noop,say:noop,remember:noop,lastAction:noop,carryGround:noop,showNotebook:noop});
    // The owner, 2026-10-04: clicks must not "queue up way behind me". A
    // waiting click aims where you look when it runs, and taps made while a
    // use is under way become one, not a backlog replayed at old aims.
    tools.press();tools.release();
    direction.set(-.3,-.6,-1).normalize();const moved=direction.toArray();
    await runTimer();assert.deepEqual(picks[0].dir,moved,'a waiting click aims where you look when it runs');
    assert.deepEqual(uses[0].at_m,[moved[0],0,moved[2]]);
    tools.press();tools.release();
    direction.set(.6,-.5,-1).normalize();const third=direction.toArray();tools.press();tools.release();
    assert.equal(uses.length,1,'pending native use must not overlap');
    finish();await flush();await runTimer();assert.deepEqual(picks[1].dir,third,'taps during a use become one, at the current aim');
    finish();await flush();assert.equal(world.use.queued,0);
    assert.equal(uses.length,2,'no taps are replayed behind the player');
    const displayed=[.2,0,-1.1];tools.press({at_m:displayed,target_name:null});tools.release();
    displayed[0]=99;await runTimer();assert.equal(picks.length,2);
    assert.deepEqual(uses[2].at_m,[.2,0,-1.1],'sidebar retains the displayed point');
    finish();await flush();
    const touch={from:[1,1.62,2],dir:[.7,-.6,-.4]};
    const expectedTouch=structuredClone(touch);
    tools.press(touch);tools.release();touch.dir[0]=99;
    direction.set(0,0,-1);await runTimer();
    assert.deepEqual(picks.at(-1).from,expectedTouch.from,'touch retains the finger ray origin');
    assert.deepEqual(picks.at(-1).dir,expectedTouch.dir,'lifting a finger cannot replace its ray with the crosshair');
    finish();await flush();
    // The actual World pointer adapter must retain mouse as well as touch
    // coordinates. Move both source vectors before the queued use runs.
    const full=(await readFile(new URL('../playground/world.js',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
    const adapter=full.slice(full.indexOf('function pointerToolTarget('),full.indexOf('function pressPrimary('));
    const pointer=new Function(adapter+';return pointerToolTarget;')()({pointerType:'mouse'},camera.position,direction);
    const expectedMouse=structuredClone(pointer);
    tools.press(pointer);tools.release();camera.position.x+=.1;direction.set(.1,-.9,.3);
    await runTimer();assert.deepEqual(picks.at(-1).from,expectedMouse.from);
    assert.deepEqual(picks.at(-1).dir,expectedMouse.dir);
    finish();await flush();
    const latest=uses.at(-1);
    assert.ok(latest.interaction_id);
    assert.equal(events.findLast(e=>e.event==='tool-press').id,latest.interaction_id);
    assert.equal(events.findLast(e=>e.event==='tool-start').id,latest.interaction_id);
    assert.equal(events.findLast(e=>e.event==='tool-reply').id,latest.interaction_id);
    tools.press();await runTimer();finish();await flush();
    direction.set(-.5,-.7,-1).normalize();const repeated=direction.toArray();
    await runTimer();assert.deepEqual(picks.at(-1).dir,repeated,'held repeat follows current cursor');
    tools.stop();finish();await flush();assert.equal(world.use.queued,0);
    const before=uses.length;tools.press();tools.release();tools.stop();await runTimer();
    assert.equal(uses.length,before,'Stop discards queued targets');
  } finally {globalThis.setTimeout=oldSet;globalThis.clearTimeout=oldClear;}
});

test('preview acceptance and green display share cell/layer and observer tolerances',async()=>{
  const full=(await readFile(new URL('../playground/world.js',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
  const code=full.slice(full.indexOf('function targetCurrent('),full.indexOf('function showMaterialPreview('));
  const camera=new THREE.PerspectiveCamera();camera.position.set(0,1.62,0);
  const grid={nx:20,nz:20,x0:-2,z0:-2,dx:.25};
  const world={session:'test',groundAim:[0,0,-1],held:{name:'novel cutter',pick:{}},
    use:{name:'novel cutter',mode:'tool-ready',target:null}};
  const targetCurrent=new Function('toolTargetFeedback','world','camera','groundColumn','groundMadeOf','targetContext',
    code+';return targetCurrent;')(toolTargetFeedback,world,camera,()=>({grid}),()=> 'sand',()=> 'same layer');
  let reply;const events=[];
  const tools=makeTools({world,camera,whereIAm:()=>({eyes_m:camera.position.toArray()}),
    targetCurrent,targetContext:()=> 'same layer',showUse(){},recordInteraction:e=>events.push(e),
    api:()=>new Promise(resolve=>reply=resolve)});
  await new Promise(resolve=>setTimeout(resolve,220));
  tools.followAim();camera.position.x=.10;world.groundAim=[.04,0,-1];
  reply({enabled:true,target:{material:'sand'},feedback:{state:'ready',ready:true}});
  await new Promise(setImmediate);
  assert.ok(world.use.target,'same-cell preview survives 10 cm body sway and 4 cm cursor shift');
  assert.equal(targetCurrent(world.use.target,world.groundAim),true);
  world.groundAim=[.3,0,-1];assert.equal(targetCurrent(world.use.target,world.groundAim),false,'another cell is checking');
  world.groundAim=[.04,-.25,-1];assert.equal(targetCurrent(world.use.target,world.groundAim),false,'another layer is checking');
  world.groundAim=[.04,0,-1];camera.position.x=.3;
  assert.equal(targetCurrent(world.use.target,world.groundAim),false,'moving out of the observed range invalidates readiness');
  assert.equal(events.at(-1).state,'ready');
});

test('interaction diagnostics are bounded and retain clicks ahead of hover chatter',async()=>{
  const full=(await readFile(new URL('../playground/world.js',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
  const code=full.slice(full.indexOf('function recordInteraction('),full.indexOf('function traceFrame('));
  const trace={interactions:[],droppedInteractions:0};
  const record=new Function('trace','world',code+';return recordInteraction;')(trace,{clock:4});
  for(let i=0;i<64;i++)record({event:'target-state',at_m:[i,0,0]});
  record({event:'tool-reply',id:'important',result:{loosened_kg:1.25,cells:Array(40000).fill({id:1})},
    reason:'x'.repeat(5000)});
  assert.equal(trace.interactions.length,64);assert.equal(trace.droppedInteractions,1);
  const last=trace.interactions.at(-1);
  assert.equal(last.id,'important');assert.equal(last.result.loosened_kg,1.25);
  assert.equal(last.result.cells,undefined);assert.equal(last.reason.length,360);
  assert.ok(JSON.stringify(trace.interactions).length<12000,'large native topology stays off the telemetry transport');
});

test('a touch press disables edge looking immediately and releases its cursor after the tool captures the ray',async()=>{
  const full=(await readFile(new URL('../playground/world.js',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
  const at=full.slice(full.indexOf('function cursorAt(e)'),full.indexOf('// The direction a pick',full.indexOf('function cursorAt(e)')));
  const cursorAt=new Function('canvas',at+';return cursorAt;')({getBoundingClientRect:()=>({left:10,top:20,width:800,height:400})});
  const touch=cursorAt({clientX:610,clientY:320,pointerType:'touch'});
  assert.deepEqual(touch,{x:.5,y:-.5,px:600,py:300,touch:true});
  assert.equal(cursorAt({clientX:610,clientY:320,pointerType:'mouse'}).touch,false);
  const start=full.indexOf('canvas.addEventListener("pointerup", (e) => {');
  const code=full.slice(start,full.indexOf('\n});',start)+4);
  let run,released=0;
  const state=new Function('canvas','releasePrimary','markAt','recordInteraction',
    'let resumeClick=false,cursorFree=false,primaryUsed=true,drag={},cursor={touch:true};'+code+';return ()=>({cursor,drag,primaryUsed});')(
      {addEventListener:(_,fn)=>run=fn,releasePointerCapture(){}},()=>released++,()=>{},()=>{});
  run({button:0,pointerId:1,pointerType:'touch'});
  assert.equal(released,1);assert.deepEqual(state(),{cursor:null,drag:null,primaryUsed:false});
});

async function touchGestureHarness() {
  const full=(await readFile(new URL('../playground/world.js',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
  const events={},turns=[],clicks=[];
  const extract=type=>{const start=full.indexOf(`canvas.addEventListener("${type}", (e) => {`);
    return start<0?'':full.slice(start,full.indexOf('\n});',start)+4);};
  const initial={pointerId:1,touch:true,startX:100,startY:100,x:100,y:100,moved:false,
    ray:{from:[0,1.6,0],dir:[0,-.5,-1]}};
  const noop=()=>{};
  const state=new Function('canvas','world','cursorAt','markAt','offerStick','$','groundTarget',
    'turn','clickWorld','releasePrimary','tools','cancelWindUp','recordInteraction',
    'let cursorFree=false,resumeClick=false,primaryUsed=false,cursor={touch:true};'+
    `let drag=${JSON.stringify(initial)};`+
    extract('pointermove')+extract('pointerup')+extract('pointercancel')+
    ';return ()=>({drag,cursor,primaryUsed});')(
    {addEventListener:(type,fn)=>events[type]=fn,releasePointerCapture:noop},
    {held:null,use:{mode:'none'}},()=>({touch:true}),noop,noop,()=>({dataset:{}}),{},
    (x,y)=>turns.push([x,y]),ray=>clicks.push(ray),noop,{stop:noop},noop,noop);
  const event=(x,y,id=1)=>({clientX:x,clientY:y,pointerId:id,pointerType:'touch',button:0});
  return {events,turns,clicks,state,event,initial};
}

test('finger jitter retains the press ray and does not rotate or cancel pickup',async()=>{
  const h=await touchGestureHarness();
  h.events.pointermove(h.event(105,104));
  assert.deepEqual(h.turns,[],'normal finger movement within 12 CSS pixels must remain a tap');
  h.events.pointerup(h.event(105,104));
  assert.deepEqual(h.clicks,[h.initial.ray]);
});

test('slow cumulative touch dragging looks without picking up; another finger cannot end it',async()=>{
  const h=await touchGestureHarness();
  h.events.pointermove(h.event(190,180,2));
  assert.deepEqual(h.turns,[],'another finger cannot turn the active drag');
  assert.deepEqual(h.state().drag,h.initial);
  for(let x=102;x<=116;x+=2)h.events.pointermove(h.event(x,100));
  assert.equal(h.state().drag.moved,true,'small moves accumulate from the original press');
  h.events.pointerup(h.event(116,100,2));
  assert.ok(h.state().drag,'another pointer cannot release the active gesture');
  h.events.pointerup(h.event(116,100));
  assert.deepEqual(h.clicks,[]);
  assert.ok(h.turns.length>0);
});

test('a cancelled touch does not leave an active gesture or pick anything up',async()=>{
  const h=await touchGestureHarness();
  assert.equal(typeof h.events.pointercancel,'function');
  h.events.pointercancel(h.event(100,100,2));assert.ok(h.state().drag);
  h.events.pointercancel(h.event(100,100));assert.equal(h.state().drag,null);
  h.events.pointerup(h.event(100,100));assert.deepEqual(h.clicks,[]);
});
