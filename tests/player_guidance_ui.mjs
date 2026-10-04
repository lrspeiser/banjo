// Exercise the real renderer across delayed, stale and preference responses.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

class Element {
  constructor(tag) {this.tag=tag;this.children=[];this.dataset={};this.isConnected=true;}
  append(node) {this.children.push(node);}
  replaceChildren(...nodes) {this.children=nodes;}
  setAttribute() {}
  classList={add() {}};
  get textContent() {return (this.text || '')+this.children.map(c=>c.textContent).join('');}
  set textContent(text) {this.text=text;}
  querySelector(selector) {
    return this.children.find(c=>selector==='.player-guide-tip' && c.className==='player-guide-tip');
  }
}
globalThis.document={createElement:tag=>new Element(tag)};
globalThis.location={href:'http://localhost/world?world=test'};
const events={},dispatched=[];
globalThis.addEventListener=(name,run)=>{events[name]=run;};
globalThis.CustomEvent=class {constructor(type,options={}){this.type=type;this.detail=options.detail;}};
globalThis.dispatchEvent=event=>{dispatched.push(event);return true;};
const source=await readFile(new URL('../playground/player_guidance.js',import.meta.url),'utf8');
const {renderPlayerGuidance}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const root=new Element('section');
const data={goal:{id:'place',title:'Build'},next_action:{verb:'construction',label:'Place here',
  destination:{screen:'world'},status:'Available',blockers:[]}};
const pending=[];
const api=(path,body)=>new Promise(resolve=>pending.push({body,resolve}));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const reply=(request,status='ready',extra={})=>request.resolve({key:'a'.repeat(24),status,
  text:'Place your item on the checked spot.',enabled:true,next_action:data.next_action,...extra});
renderPlayerGuidance(root,data,api);
const initial=pending.shift();assert.equal(initial.body.action,'status');
reply(initial);await flush();
const area=root.querySelector('.player-guide-tip'),tip=area.children[1];
assert.match(area.textContent,/Place your item/);
const speaker=area.children.find(c=>c.textContent==='Speak');
assert.ok(speaker,'ready guidance should expose a Speak control');
speaker.onclick();
assert.equal(dispatched.at(-1).type,'banjo-voice-speak');
assert.equal(dispatched.at(-1).detail.source,'guide-button');
assert.match(dispatched.at(-1).detail.text,/Place your item/);
// F1 speaks even when the same explanation is already painted.
events.keydown({key:'F1',repeat:false,preventDefault(){}});const replay=pending.shift();
reply(replay);await flush();
assert.equal(dispatched.at(-1).detail.source,'f1');
assert.match(dispatched.at(-1).detail.text,/Place your item/);
// Repeated live refreshes cannot collapse or repaint the current ready tip,
// including while a network read is outstanding or returns a transient state.
for(let n=0;n<30;n++) {
  renderPlayerGuidance(root,{...data,observed_native_t_s:n},api);
  assert.equal(root.querySelector('.player-guide-tip'),area);
  assert.equal(area.children[1],tip);
  assert.equal(pending.length,0,'unchanged refresh must not request advice');
  root.children.find(c=>c.textContent==='Ask AI · F1').onclick();
  reply(pending.shift(),n%2?'ready':'fallback');await flush();
  assert.equal(area.children[1],tip);
}
// A late ordinary refresh must not resurrect advice after explicit dismissal.
events.keydown({key:'F1',preventDefault(){}});const older=pending.shift();
assert.equal(older.body.action,'request');
area.children.find(c=>c.textContent==='Hide tip').onclick();
const dismiss=pending.shift();assert.equal(dismiss.body.action,'dismiss');
reply(dismiss,'dismissed');await flush();assert.equal(area.children.length,0);
reply(older);await flush();assert.equal(area.children.length,0);
renderPlayerGuidance(root,data,api);assert.equal(pending.length,0);await flush();
assert.equal(area.children.length,0);
// Quiet remains a deliberate persistent control, never an intermittent tip.
events.keydown({key:'F1',preventDefault(){}});reply(pending.shift());await flush();
const quiet=area.children.find(c=>c.textContent==='Quiet guide');quiet.onclick();
reply(pending.shift(),'quiet',{enabled:false});await flush();
assert.equal(area.textContent,'Enable guide');
renderPlayerGuidance(root,data,api);assert.equal(root.querySelector('.player-guide-tip'),area);
assert.equal(pending.length,0);await flush();
assert.equal(area.textContent,'Enable guide');
// A changed task clears the old explanation immediately. Its delayed reply
// cannot attach stale advice to the new task.
events.keydown({key:'F1',preventDefault(){}});const late=pending.shift();
const changed={...data,next_action:{...data.next_action,label:'Collect material'}};
renderPlayerGuidance(root,changed,api);
const nextArea=root.querySelector('.player-guide-tip');assert.notEqual(nextArea,area);
assert.equal(nextArea.children.length,0);
reply(late);await flush();assert.equal(nextArea.children.length,0);
reply(pending.shift(),'ready',{key:'b'.repeat(24),next_action:changed.next_action,text:'Collect the material.'});
await flush();assert.match(nextArea.textContent,/Collect the material/);
console.log('PASS: stable refresh, transient state, dismissal race, quiet, changed task and stale response');
