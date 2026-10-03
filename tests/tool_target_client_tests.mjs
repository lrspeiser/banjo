import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFile} from 'node:fs/promises';
import * as THREE from '../playground/vendor/three.module.js';

const source=(await readFile(new URL('../playground/tools.js',import.meta.url),'utf8'))
  .replace('"/vendor/three.module.js"',JSON.stringify(new URL('../playground/vendor/three.module.js',import.meta.url).href));
const {makeTools}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

test('cursor clicks, queued taps, sidebar targets and held repeats retain their intended targets',async()=>{
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
    const picks=[],uses=[];
    const noop=()=>{};
    const tools=makeTools({world,camera,aimVector:()=>direction.clone(),
      whereIAm:()=>({eyes_m:camera.position.toArray()}),
      act:async(op,args)=>{assert.equal(op,'pick');picks.push(args);
        return {hit:true,point_m:[args.dir[0],0,args.dir[2]]};},
      api:async(path,body)=>{assert.equal(path,'/api/world/tool/use');uses.push(body);
        return await new Promise(resolve=>{finish=()=>resolve({said:'Collected',repeat:true});});},
      showUse:noop,say:noop,remember:noop,lastAction:noop,carryGround:noop,showNotebook:noop});
    const first=direction.toArray();tools.press();tools.release();
    direction.set(-.3,-.6,-1).normalize(); // movement before the scheduled stroke
    await runTimer();assert.deepEqual(picks[0].dir,first);
    assert.deepEqual(uses[0].at_m,[first[0],0,first[2]]);
    const second=direction.toArray();tools.press();tools.release();
    direction.set(.6,-.5,-1).normalize();const third=direction.toArray();tools.press();tools.release();
    assert.equal(uses.length,1,'pending native use must not overlap');
    finish();await flush();await runTimer();assert.deepEqual(picks[1].dir,second);
    finish();await flush();await runTimer();assert.deepEqual(picks[2].dir,third);
    finish();await flush();assert.equal(world.use.queued,0);
    const displayed=[.2,0,-1.1];tools.press({at_m:displayed,target_name:null});tools.release();
    displayed[0]=99;await runTimer();assert.equal(picks.length,3);
    assert.deepEqual(uses[3].at_m,[.2,0,-1.1],'sidebar retains the displayed point');
    finish();await flush();
    tools.press();await runTimer();finish();await flush();
    direction.set(-.5,-.7,-1).normalize();const repeated=direction.toArray();
    await runTimer();assert.deepEqual(picks.at(-1).dir,repeated,'held repeat follows current cursor');
    tools.stop();finish();await flush();assert.equal(world.use.queued,0);
    const before=uses.length;tools.press();tools.release();tools.stop();await runTimer();
    assert.equal(uses.length,before,'Stop discards queued targets');
  } finally {globalThis.setTimeout=oldSet;globalThis.clearTimeout=oldClear;}
});
