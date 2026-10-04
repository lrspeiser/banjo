import assert from "node:assert/strict";
import { createVoiceController } from "../playground/voice.js";

class FakeElement {
  constructor(tag="div") {
    this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.listeners={};
    this.hidden=false;this.textContent="";this.readyState=tag==="audio"?4:undefined;
  }
  setAttribute(name,value){this[name]=String(value);}
  addEventListener(name,fn){(this.listeners[name] ||= []).push(fn);}
  removeEventListener(name,fn){this.listeners[name]=(this.listeners[name]||[]).filter(x=>x!==fn);}
  dispatch(name,event={}){for(const fn of this.listeners[name]||[])fn(event);}
  querySelector(selector){return selector==="#ask-send" ? this.children.find(x=>x.id==="ask-send") : null;}
  insertBefore(node,before){const at=this.children.indexOf(before);if(at<0)this.children.push(node);else this.children.splice(at,0,node);}
  insertAdjacentElement(_where,node){this.after=node;}
  append(node){this.children.push(node);}
  remove(){this.removed=true;}
  play(){this.played=true;return Promise.resolve();}
  setPointerCapture(){}
}
const body=new FakeElement("body");
const documentEvents={};
globalThis.document={
  body,
  hidden:false,
  createElement:tag=>new FakeElement(tag),
  querySelector:()=>null,
  addEventListener:(name,fn)=>{(documentEvents[name] ||= []).push(fn);},
  removeEventListener:(name,fn)=>{documentEvents[name]=(documentEvents[name]||[]).filter(x=>x!==fn);},
};
globalThis.window=globalThis;
const windowEvents={};
globalThis.addEventListener=(name,fn)=>{(windowEvents[name] ||= []).push(fn);};
globalThis.removeEventListener=(name,fn)=>{windowEvents[name]=(windowEvents[name]||[]).filter(x=>x!==fn);};
const emitWindow=(name,event={})=>{for(const fn of windowEvents[name]||[])fn(event);};
globalThis.localStorage={
  values:new Map(),
  getItem(key){return this.values.get(key)??null;},
  setItem(key,value){this.values.set(key,String(value));},
};

let mediaRequests=0,replacedTrack=null;
const mic={enabled:false,stop(){this.stopped=true;}};
const media={getAudioTracks:()=>[mic],getTracks:()=>[mic]};
Object.defineProperty(globalThis,"navigator",{value:{mediaDevices:{getUserMedia:async()=>{
  mediaRequests++;return media;
}}},configurable:true});

class FakeChannel {
  constructor(){this.readyState="open";this.listeners={};this.sent=[];}
  addEventListener(name,fn){(this.listeners[name] ||= []).push(fn);}
  removeEventListener(name,fn){this.listeners[name]=(this.listeners[name]||[]).filter(x=>x!==fn);}
  send(raw){this.sent.push(JSON.parse(raw));}
  close(){this.readyState="closed";}
  message(event){for(const fn of this.listeners.message||[])fn({data:JSON.stringify(event)});}
}
let lastPeer=null;
class FakePeer {
  constructor(){lastPeer=this;this.channel=null;this.sender={replaceTrack:async track=>{replacedTrack=track;}};}
  addTransceiver(kind,options){assert.equal(kind,"audio");assert.equal(options.direction,"sendrecv");return {sender:this.sender};}
  createDataChannel(){this.channel=new FakeChannel();return this.channel;}
  async createOffer(){return {type:"offer",sdp:"offer-sdp"};}
  async setLocalDescription(){}
  async setRemoteDescription(answer){assert.equal(answer.type,"answer");assert.equal(answer.sdp,"answer-sdp");}
  close(){this.closed=true;}
}
globalThis.RTCPeerConnection=FakePeer;
globalThis.fetch=async(url,options)=>{
  assert.equal(String(url),"https://api.openai.com/v1/realtime/calls");
  assert.equal(options.headers.Authorization,"Bearer ephemeral");
  assert.equal(options.body,"offer-sdp");
  return {ok:true,status:200,text:async()=>"answer-sdp"};
};

const form=new FakeElement("form"),send=new FakeElement("button");send.id="ask-send";form.children.push(send);
const apiCalls=[],shown=[];
const api=async(path,body)=>{
  apiCalls.push([path,body]);
  if(path==="/api/world/voice/session")return {value:"ephemeral"};
  if(path==="/api/world/voice/ask")return {reply:"Use the copper mill.",mode:"fixture"};
  throw new Error("unexpected "+path);
};
const controller=createVoiceController({
  api,mount:form,canTalk:()=>true,getFocus:()=>"copper mill",
  onUser:text=>shown.push(["user",text]),onReply:text=>shown.push(["assistant",text]),
  preferenceKey:"test.voice-lens",
});

// Output-only speech negotiates audio without touching the microphone.
await controller.speak("Authenticated guidance.");
assert.equal(mediaRequests,0,"spoken guidance must not request microphone permission");
assert.equal(apiCalls[0][0],"/api/world/voice/session");
let response=lastPeer.channel.sent.find(x=>x.type==="response.create");
assert.equal(response.response.conversation,"none");
assert.match(response.response.instructions,/Authenticated guidance/);
lastPeer.channel.message({type:"response.done",response:{metadata:{banjo_speech:response.response.metadata.banjo_speech}}});

// Only push-to-talk acquires and installs the microphone track.
await controller.start();
assert.equal(mediaRequests,1);
assert.equal(replacedTrack,mic);
assert.equal(mic.enabled,true);
assert.equal(lastPeer.channel.sent.at(-1).type,"input_audio_buffer.clear");
controller.stop();
assert.equal(mic.enabled,false);
assert.equal(lastPeer.channel.sent.at(-1).type,"input_audio_buffer.commit");

// A completed transcript is grounded through Banjo's voice endpoint, including focus.
lastPeer.channel.message({type:"conversation.item.input_audio_transcription.completed",transcript:"Why is this stopped?"});
await new Promise(resolve=>setImmediate(resolve));
const ask=apiCalls.find(([path])=>path==="/api/world/voice/ask");
assert.equal(ask[1].focus,"copper mill");
assert.deepEqual(shown,[["user","Why is this stopped?"],["assistant","Use the copper mill."]]);
response=lastPeer.channel.sent.filter(x=>x.type==="response.create").at(-1);
lastPeer.channel.message({type:"response.done",response:{metadata:{banjo_speech:response.response.metadata.banjo_speech}}});

// Helpful lens narration is opt-in and semantically deduped.
controller.setLensMode("helpful");
const detail={identity:"pile:copper",rows:[{label:"Copper",value:"4 kg",action:"Collect",kind:"pile"}]};
const before=lastPeer.channel.sent.filter(x=>x.type==="response.create").length;
emitWindow("banjo-voice-hover",{detail});
await new Promise(resolve=>setImmediate(resolve));
const afterOne=lastPeer.channel.sent.filter(x=>x.type==="response.create").length;
assert.equal(afterOne,before+1);
response=lastPeer.channel.sent.filter(x=>x.type==="response.create").at(-1);
lastPeer.channel.message({type:"response.done",response:{metadata:{banjo_speech:response.response.metadata.banjo_speech}}});
emitWindow("banjo-voice-hover",{detail});
await new Promise(resolve=>setImmediate(resolve));
assert.equal(lastPeer.channel.sent.filter(x=>x.type==="response.create").length,afterOne,
  "unchanged hover target must not repeat");

controller.destroy();
assert.equal(mic.stopped,true);
console.log("PASS: output-only speech, push-to-talk microphone boundary, grounding and lens dedupe");
