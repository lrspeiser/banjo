import fs from 'node:fs';import assert from 'node:assert/strict';import vm from 'node:vm';
const html=fs.readFileSync(new URL('../client/voxel-lab/thermal-fields.html',import.meta.url),'utf8'),js=fs.readFileSync(new URL('../client/voxel-lab/thermal-fields.js',import.meta.url),'utf8');
const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);assert.equal(new Set(ids).size,ids.length);
for(const m of js.matchAll(/\$\('([^']+)'\)/g))assert(ids.includes(m[1]),`missing ${m[1]}`);
assert(js.includes("fetch('/api/thermal-fields'"));assert(js.includes('c.temperature_k'));assert(js.includes('c.liquid_fraction'));assert(js.includes('c.products_kg'));assert(js.includes('new THREE.BoxGeometry(c.size_m,c.size_m,c.size_m)'));assert(html.includes('geometry stays fixed'));assert(html.includes('no flame animation'));assert(!js.includes('Math.random'));
// Execute the actual readiness guard with a minimal DOM: loading/refused sessions
// must never advertise advancing or exporting a nonexistent native state.
const buttons=Object.fromEntries(['reset','step','run','save','open','ice-test','fuel-test','stop'].map(id=>[id,{disabled:false}]));
const context=vm.createContext({busy:false,running:false,session:null,$:id=>buttons[id]});
vm.runInContext(js.match(/function controls\(\)\{[^\n]+\}/)[0],context);
for(const id of ['run','step','save'])assert(new RegExp(`id="${id}" disabled`).test(html),`${id} starts disabled before module/session loading`);
vm.runInContext('controls()',context);for(const id of ['run','step','save'])assert(buttons[id].disabled);
assert(!buttons.reset.disabled,'a failed setup remains retryable');
context.session='native-session';vm.runInContext('controls()',context);assert(!buttons.run.disabled);
context.busy=true;vm.runInContext('controls()',context);assert(buttons.run.disabled);assert(buttons.reset.disabled);
context.busy=false;context.running=true;vm.runInContext('controls()',context);assert(buttons.run.disabled);assert(!buttons.stop.disabled);
console.log('3D field native observables, unsupported-law labels and executable session readiness guards passed');

const sceneControls=html.match(/<div[^>]*id="view"[^>]*>([\s\S]*?)<output id="clock">/)[1];
for(const id of ['run', 'step', 'stop', 'reset', 'ice-test', 'fuel-test', 'save', 'open'])assert(sceneControls.includes(`id="${id}"`),`${id} must stay next to the 3D view`);
let leave,beacon;const cleanup=vm.createContext({session:'owned-native-field',Blob,JSON,window:{addEventListener:(event,fn)=>{assert.equal(event,'pagehide');leave=fn;}},navigator:{sendBeacon:(url,body)=>{beacon={url,body};}}});
vm.runInContext(js.match(/window.addEventListener\('pagehide',[^\n]+/)[0],cleanup);leave();assert.equal(beacon.url,'/api/thermal-fields');assert.deepEqual(JSON.parse(await beacon.body.text()),{op:'close',session:'owned-native-field'});
beacon=null;cleanup.session=null;leave();assert.equal(beacon,null,'navigation must not close an unrelated session');
