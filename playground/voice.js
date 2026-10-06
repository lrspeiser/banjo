// Realtime transports speech. Every transcript uses the selected typed chat.
const REALTIME_CALLS = 'https://api.openai.com/v1/realtime/calls';
export const AUDIO_PREFERENCE = 'banjo.audio-output';
export function audioOutputEnabled() {
  try { return localStorage.getItem(AUDIO_PREFERENCE) === 'on'; } catch { return false; }
}
export function setAudioOutput(enabled) {
  try { localStorage.setItem(AUDIO_PREFERENCE, enabled ? 'on' : 'off'); } catch {}
  dispatchEvent(new CustomEvent('banjo-audio-output', {detail:{enabled:!!enabled}}));
}
function editableTarget(target) {
  return !!target?.closest?.('input,textarea,select,[contenteditable=true]');
}
function waitForChannel(channel, timeoutMs=10000) {
  if(channel.readyState === 'open')return Promise.resolve();
  return new Promise((resolve,reject)=>{
    const cleanup=()=>{clearTimeout(timer);for(const [name,fn] of handlers)channel.removeEventListener(name,fn);};
    const handlers=[['open',()=>{cleanup();resolve();}],['close',()=>{cleanup();reject(Error('Voice disconnected'));}],
      ['error',()=>{cleanup();reject(Error('Voice connection failed'));}]];
    const timer=setTimeout(()=>{cleanup();reject(Error('Voice connection did not open'));},timeoutMs);
    for(const [name,fn] of handlers)channel.addEventListener(name,fn);
  });
}

export function createVoiceController({api,mount,buttonMount,canTalk=()=>true,
  submitText,onStatus=()=>{}}={}) {
  if(typeof api !== 'function' || typeof submitText !== 'function')throw Error('Voice needs the game API and typed chat');
  const form=mount || document.querySelector('#ask');
  if(!form)throw Error('Voice needs the chat form');
  const button=document.createElement('button');button.type='button';button.id='voice-talk';
  button.title='Press and hold to talk · hold Y on the keyboard';button.setAttribute('aria-label',button.title);
  const status=document.createElement('small');status.id='voice-status';status.setAttribute('role','status');
  status.setAttribute('aria-live','polite');status.hidden=true;
  (buttonMount || form).append(button);form.insertAdjacentElement('afterend',status);
  let peer=null,channel=null,transceiver=null,media=null,mic=null,remoteAudio=null,connecting=null;
  let holding=false,listening=false,transcribing=false,asking=false,speaking=false,closed=false;
  let pointer=null,press=0,speechCounter=0,activeSpeech=null,transcriptionTimer=null,idleTimer=null;
  const seenItems=new Set();
  function setStatus(state,text='') {
    button.dataset.voiceState=state;button.setAttribute('aria-pressed',String(state==='listening'));
    button.textContent=state==='listening'?'Release':state==='connecting'?'…':state==='thinking'?'…':'🎙';
    status.textContent=text;status.hidden=!text;onStatus({state,text});
  }
  function emit(event) {
    if(channel?.readyState!=='open')throw Error('Voice connection is not ready');
    channel.send(JSON.stringify(event));
  }
  function stopInput() {
    if(mic)mic.enabled=false;
    for(const track of media?.getTracks?.() || [])track.stop();
    media=null;mic=null;listening=false;
    transceiver?.sender?.replaceTrack(null)?.catch(()=>{});
  }
  function stopSpeech() {
    if(speaking && channel?.readyState==='open') {
      emit({type:'response.cancel'});emit({type:'output_audio_buffer.clear'});
    }
    speaking=false;activeSpeech=null;
  }
  function cleanupConnection() {
    clearTimeout(idleTimer);clearTimeout(transcriptionTimer);stopInput();
    const oldChannel=channel;channel=null;oldChannel?.close();peer?.close();peer=null;transceiver=null;
    if(remoteAudio){remoteAudio.srcObject=null;remoteAudio.remove();}remoteAudio=null;
    connecting=null;transcribing=false;speaking=false;activeSpeech=null;
  }
  function idle() {
    clearTimeout(idleTimer);
    if(!holding && !transcribing && !asking && !speaking)
      idleTimer=setTimeout(()=>{cleanupConnection();if(!closed && button.dataset.voiceState!=='error')setStatus('idle');},30000);
  }
  async function handleTranscript(event) {
    if(!transcribing || closed)return;
    if(event.item_id && seenItems.has(event.item_id))return;
    if(event.item_id){seenItems.add(event.item_id);if(seenItems.size>40)seenItems.delete(seenItems.values().next().value);}
    clearTimeout(transcriptionTimer);transcribing=false;
    const text=String(event.transcript || '').trim();
    if(!text){setStatus('idle');idle();return;}
    asking=true;setStatus('thinking','Sending to the selected chat…');
    try {
      if(!canTalk())throw Error('This chat is busy or unavailable. Try again.');
      await submitText(text);
      if(!closed && !speaking)setStatus('idle');
    } catch(error) {if(!closed)setStatus('error',error.message || String(error));}
    finally {asking=false;idle();}
  }
  function handleEvent(message) {
    let event;try{event=JSON.parse(message.data);}catch{return;}
    if(event.type==='conversation.item.input_audio_transcription.completed'){void handleTranscript(event);return;}
    if(event.type==='conversation.item.input_audio_transcription.failed') {
      clearTimeout(transcriptionTimer);transcribing=false;setStatus('error','Could not transcribe that. Hold to retry.');idle();return;
    }
    if(event.type==='response.done' && event.response?.metadata?.banjo_speech===activeSpeech) {
      speaking=false;activeSpeech=null;setStatus('idle');idle();return;
    }
    if(event.type==='error') {
      clearTimeout(transcriptionTimer);holding=false;transcribing=false;stopInput();
      stopSpeech();
      setStatus('error','Voice service refused this turn. Hold to retry, or type your message.');idle();
    }
  }
  async function connect() {
    if(closed)throw Error('Voice is closed');
    if(channel?.readyState==='open')return;
    if(connecting)return connecting;
    if(!window.RTCPeerConnection)throw Error('This browser does not support voice');
    if(!canTalk())throw Error('Open your own chat before using voice');
    if(peer || channel || media)cleanupConnection();
    connecting=(async()=>{
      setStatus('connecting','Connecting voice…');
      const secret=await api('/api/world/voice/session',{});
      if(closed)throw Error('Voice is closed');
      if(!secret?.value)throw Error('No voice client secret was returned');
      peer=new RTCPeerConnection();const currentPeer=peer;
      remoteAudio=document.createElement('audio');remoteAudio.autoplay=true;remoteAudio.hidden=true;
      remoteAudio.muted=!audioOutputEnabled();document.body.append(remoteAudio);
      peer.ontrack=event=>{if(peer!==currentPeer || !remoteAudio)return;
        remoteAudio.srcObject=event.streams[0] || new MediaStream([event.track]);remoteAudio.play?.().catch(()=>{});};
      transceiver=peer.addTransceiver('audio',{direction:'sendrecv'});
      channel=peer.createDataChannel('oai-events');const currentChannel=channel;
      channel.addEventListener('message',handleEvent);
      channel.addEventListener('close',()=>{if(channel!==currentChannel || closed)return;
        holding=false;++press;cleanupConnection();setStatus('error','Voice disconnected. Hold to reconnect.');});
      const offer=await peer.createOffer();await peer.setLocalDescription(offer);
      const response=await fetch(REALTIME_CALLS,{method:'POST',body:offer.sdp,
        headers:{Authorization:'Bearer '+secret.value,'Content-Type':'application/sdp'}});
      if(!response.ok)throw Error(`Voice connection failed (HTTP ${response.status})`);
      const answer=await response.text();
      if(closed || peer!==currentPeer)throw Error('Voice connection was cancelled');
      await peer.setRemoteDescription({type:'answer',sdp:answer});await waitForChannel(channel);setStatus('idle');
    })().catch(error=>{cleanupConnection();if(!closed)setStatus('error',error.message || String(error));throw error;})
      .finally(()=>{connecting=null;});
    return connecting;
  }
  async function start() {
    if(holding || transcribing || asking || closed)return;
    if(!canTalk()){setStatus('error','Chat is busy or this view is read-only. Wait or open your own character.');return;}
    holding=true;const token=++press;clearTimeout(idleTimer);
    try {
      await connect();
      if(!holding || token!==press || closed){idle();return;}
      if(!navigator.mediaDevices?.getUserMedia)throw Error('Microphone requires a supported secure browser');
      const acquired=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
      const track=acquired.getAudioTracks()[0];
      if(track)track.enabled=false;
      if(!track || !holding || token!==press || closed || !transceiver?.sender) {
        for(const t of acquired.getTracks())t.stop();idle();return;
      }
      await transceiver.sender.replaceTrack(track);
      if(!holding || token!==press || closed){for(const t of acquired.getTracks())t.stop();idle();return;}
      media=acquired;mic=track;stopSpeech();emit({type:'input_audio_buffer.clear'});
      mic.enabled=true;listening=true;setStatus('listening','Listening… release to send to this chat.');
    } catch(error) {holding=false;stopInput();if(!closed)setStatus('error',error.message || String(error));idle();}
  }
  function stop() {
    if(!holding)return;
    holding=false;++press;
    if(!listening || channel?.readyState!=='open'){stopInput();setStatus('idle');idle();return;}
    stopInput();transcribing=true;emit({type:'input_audio_buffer.commit'});setStatus('thinking','Transcribing…');
    transcriptionTimer=setTimeout(()=>{transcribing=false;setStatus('error','Transcription timed out. Hold to retry.');idle();},20000);
  }
  function cancel() {
    if(!holding)return;
    holding=false;++press;stopInput();
    if(channel?.readyState==='open')emit({type:'input_audio_buffer.clear'});
    setStatus('idle');idle();
  }
  async function speak(text) {
    text=String(text || '').trim();
    if(!text || closed || !audioOutputEnabled())return;
    clearTimeout(idleTimer);await connect();
    if(closed || !audioOutputEnabled())return;
    stopSpeech();activeSpeech=`banjo-${++speechCounter}`;speaking=true;setStatus('speaking','Speaking the chat reply.');
    emit({type:'response.create',response:{conversation:'none',input:[],output_modalities:['audio'],
      metadata:{banjo_speech:activeSpeech},instructions:'Read exactly this Banjo chat reply. Add no words or advice.\n'+JSON.stringify(text)}});
  }
  const replyEvent=event=>{if(!event.detail?.error && event.detail?.reply)
    void speak(event.detail.reply).catch(error=>setStatus('error',error.message || String(error)));};
  const outputEvent=event=>{if(remoteAudio)remoteAudio.muted=!event.detail?.enabled;
    if(!event.detail?.enabled){stopSpeech();if(!holding && !asking && !transcribing)setStatus('idle');idle();}};
  addEventListener('banjo-chat-finished',replyEvent);addEventListener('banjo-audio-output',outputEvent);
  button.addEventListener('pointerdown',event=>{if(event.button!==0 || holding)return;
    event.preventDefault();pointer=event.pointerId;button.setPointerCapture?.(pointer);void start();});
  button.addEventListener('pointerup',event=>{if(pointer!==event.pointerId)return;event.preventDefault();pointer=null;stop();});
  for(const name of ['pointercancel','lostpointercapture'])button.addEventListener(name,event=>{
    if(pointer!==event.pointerId)return;pointer=null;cancel();});
  button.addEventListener('keydown',event=>{if(!['Space','Enter'].includes(event.code) || event.repeat)return;event.preventDefault();void start();});
  button.addEventListener('keyup',event=>{if(!['Space','Enter'].includes(event.code))return;event.preventDefault();stop();});
  const keydown=event=>{if(event.code!=='KeyY' || event.repeat || event.altKey || event.ctrlKey || event.metaKey || editableTarget(event.target))return;
    event.preventDefault();void start();};
  const keyup=event=>{if(event.code!=='KeyY' || !holding)return;event.preventDefault();stop();};
  const blur=()=>{pointer=null;cancel();};
  const hidden=()=>{if(document.hidden)blur();};
  addEventListener('keydown',keydown);addEventListener('keyup',keyup);addEventListener('blur',blur);
  document.addEventListener('visibilitychange',hidden);
  function destroy() {
    if(closed)return;closed=true;holding=false;++press;cleanupConnection();button.remove();status.remove();
    removeEventListener('keydown',keydown);removeEventListener('keyup',keyup);removeEventListener('blur',blur);
    removeEventListener('banjo-chat-finished',replyEvent);removeEventListener('banjo-audio-output',outputEvent);
    removeEventListener('pagehide',destroy);document.removeEventListener('visibilitychange',hidden);
  }
  addEventListener('pagehide',destroy);setStatus('idle');
  return {button,status,start,stop,cancel,speak,destroy};
}
