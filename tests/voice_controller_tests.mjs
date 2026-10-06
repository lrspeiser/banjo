import assert from 'node:assert/strict';
import {createVoiceController,setAudioOutput,audioOutputEnabled} from '../playground/voice.js';
class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.listeners={};}
  setAttribute(k,v){this[k]=String(v);}
  addEventListener(k,f){(this.listeners[k] ||= []).push(f);}
  removeEventListener(k,f){this.listeners[k]=(this.listeners[k] || []).filter(x=>x!==f);}
  fire(k,e={}){for(const f of this.listeners[k] || [])f(e);}
  append(e){this.children.push(e);}
  insertAdjacentElement(_k,e){this.after=e;}
  remove(){this.removed=true;}
  play(){return Promise.resolve();}
  setPointerCapture(){}
}
const events=new Element(),docEvents=new Element(),body=new Element();
globalThis.document={body,hidden:false,createElement:k=>new Element(k),querySelector:()=>null,
  addEventListener:(k,f)=>docEvents.addEventListener(k,f),removeEventListener:(k,f)=>docEvents.removeEventListener(k,f)};
globalThis.window=globalThis;
globalThis.addEventListener=(k,f)=>events.addEventListener(k,f);
globalThis.removeEventListener=(k,f)=>events.removeEventListener(k,f);
globalThis.dispatchEvent=e=>events.fire(e.type,e);
globalThis.CustomEvent=class{constructor(type,{detail}={}){this.type=type;this.detail=detail;}};
globalThis.localStorage={values:new Map(),getItem(k){return this.values.get(k)??null;},setItem(k,v){this.values.set(k,String(v));}};
let permissionError=null,pendingMedia=null,mediaRequests=0;
const tracks=[];
function media(){const track={enabled:true,stopped:false,stop(){this.stopped=true;this.enabled=false;}};tracks.push(track);
  return {getAudioTracks:()=>[track],getTracks:()=>[track]};}
Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:async()=>{
  mediaRequests++;if(permissionError)throw permissionError;return pendingMedia?await pendingMedia:media();}}}});
class Channel extends Element {
  constructor(){super();this.readyState='open';this.sent=[];}
  send(raw){this.sent.push(JSON.parse(raw));}
  close(){this.readyState='closed';this.fire('close');}
  message(e){this.fire('message',{data:JSON.stringify(e)});}
}
const peers=[];
class Peer {
  constructor(){peers.push(this);this.sender={replaceTrack:async t=>{this.track=t;}};}
  addTransceiver(k,o){assert.equal(k,'audio');assert.equal(o.direction,'sendrecv');return {sender:this.sender};}
  createDataChannel(){this.channel=new Channel();return this.channel;}
  async createOffer(){return {sdp:'offer'};}
  async setLocalDescription(){}
  async setRemoteDescription(o){assert.equal(o.sdp,'answer');}
  close(){this.closed=true;}
}
globalThis.RTCPeerConnection=Peer;
globalThis.fetch=async(url,o)=>{assert.equal(url,'https://api.openai.com/v1/realtime/calls');
  assert.equal(o.headers.Authorization,'Bearer ephemeral');return {ok:true,text:async()=>'answer'};};
const apiCalls=[],submitted=[];let pendingSecret=null;
const controller=createVoiceController({mount:new Element('form'),buttonMount:new Element('nav'),
  api:async(path,body)=>{apiCalls.push([path,body]);assert.equal(path,'/api/world/voice/session');
    return pendingSecret?await pendingSecret:{value:'ephemeral'};},
  submitText:async text=>{submitted.push(text);dispatchEvent(new CustomEvent('banjo-chat-finished',{detail:{reply:'Authoritative reply'}}));}});
const tick=()=>new Promise(r=>setImmediate(r));
const last=()=>peers.at(-1);
const responses=()=>last().channel.sent.filter(e=>e.type==='response.create');
const finishSpeech=()=>{const response=responses().at(-1)?.response;
  last().channel.message({type:'response.done',response:{metadata:response?.metadata}});};
assert.equal(audioOutputEnabled(),false);
await controller.speak('Off by default');assert.equal(apiCalls.length,0);assert.equal(mediaRequests,0);
setAudioOutput(true);assert.equal(apiCalls.length,0,'Audio setting alone makes no calls');
await controller.speak('Measured text');assert.equal(mediaRequests,0);
assert.equal(responses().at(-1).response.conversation,'none');
assert.match(responses().at(-1).response.instructions,/Measured text/);
setAudioOutput(false);assert.equal(body.children.at(-1).muted,true);
assert.equal(last().channel.sent.at(-1).type,'output_audio_buffer.clear');
setAudioOutput(true);await controller.speak('Controlled failing speech');
last().channel.message({type:'error',error:{message:'provider failure'}});
assert.equal(controller.button.dataset.voiceState,'error');
assert.equal(last().channel.sent.at(-1).type,'output_audio_buffer.clear','Provider failure cancels pending output');
setAudioOutput(false);

await controller.start();assert.equal(tracks.at(-1).enabled,true);
controller.stop();assert.equal(tracks.at(-1).stopped,true);
assert.equal(last().channel.sent.at(-1).type,'input_audio_buffer.commit');
last().channel.message({type:'conversation.item.input_audio_transcription.completed',item_id:'one',transcript:'Make the handle longer'});
await tick();assert.deepEqual(submitted,['Make the handle longer']);
assert.equal(responses().length,2,'Muted successful chat stays text without synthesis');
last().channel.message({type:'conversation.item.input_audio_transcription.completed',item_id:'one',transcript:'duplicate'});
await tick();assert.equal(submitted.length,1);
await controller.start();controller.stop();
last().channel.message({type:'conversation.item.input_audio_transcription.completed',item_id:'two',transcript:'Make the handle longer'});
await tick();assert.equal(submitted.length,2,'Same words in a new committed turn are allowed');

for(const kind of ['pointercancel','lostpointercapture','blur','hidden']) {
  const e={button:0,pointerId:8,preventDefault(){}};
  controller.button.fire('pointerdown',e);await tick();
  const commits=last().channel.sent.filter(x=>x.type==='input_audio_buffer.commit').length;
  if(kind==='blur')events.fire('blur');else if(kind==='hidden'){document.hidden=true;docEvents.fire('visibilitychange');document.hidden=false;}
  else controller.button.fire(kind,e);
  assert.equal(tracks.at(-1).stopped,true);
  assert.equal(last().channel.sent.filter(x=>x.type==='input_audio_buffer.commit').length,commits,'Cancel must not send actions');
  last().channel.message({type:'conversation.item.input_audio_transcription.completed',item_id:kind,transcript:'late cancelled'});
  await tick();assert.equal(submitted.length,2);
}
const key={code:'KeyY',preventDefault(){},target:{closest:()=>true}};
const before=mediaRequests;events.fire('keydown',key);await tick();assert.equal(mediaRequests,before);
events.fire('keydown',{...key,target:{closest:()=>false}});await tick();assert.equal(tracks.at(-1).enabled,true);
events.fire('keyup',key);assert.equal(tracks.at(-1).stopped,true,'Y release works after focus enters text');
last().channel.message({type:'conversation.item.input_audio_transcription.failed'});assert.equal(controller.button.dataset.voiceState,'error');

permissionError=Error('Permission denied');await controller.start();assert.equal(controller.button.dataset.voiceState,'error');
permissionError=null;
let resolveMedia;pendingMedia=new Promise(r=>{resolveMedia=r;});const starting=controller.start();await tick();
controller.cancel();const late=media();resolveMedia(late);await starting;pendingMedia=null;
assert.equal(late.getAudioTracks()[0].stopped,true,'Late permission result cannot reopen cancelled capture');

await controller.start();const old=last();old.channel.close();assert.equal(tracks.at(-1).stopped,true);
const calls=apiCalls.length;await tick();assert.equal(apiCalls.length,calls,'Disconnect must not automatically call again');
await controller.start();assert.notEqual(last(),old);controller.cancel();
controller.destroy();assert.equal(last().closed,true);

let resolveSecret;pendingSecret=new Promise(r=>{resolveSecret=r;});
const quick=createVoiceController({mount:new Element('form'),api:async()=>await pendingSecret,submitText:async()=>{}});
const quickStart=quick.start();quick.stop();const requests=mediaRequests;resolveSecret({value:'ephemeral'});await quickStart;
assert.equal(mediaRequests,requests,'Release before connection must not request a microphone');quick.destroy();pendingSecret=null;
console.log('PASS: mute, exact reply output, typed routing, duplicate/cancel boundaries, pointer/Y, permission and reconnect');
