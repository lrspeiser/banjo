"""Voice enters real typed routes in isolated worlds; never an ambient mic."""
import json
import unittest
from unittest import mock
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'playground'),str(ROOT)]
import workshop_navigation_tests as navigation
import workshop_chat
import voice_api
import game_guidance
from urllib import request, error

FAKE_TRANSPORT='''(()=>{
  const state=window.__voiceTest={tracks:[],requests:[],channel:null};
  navigator.mediaDevices.getUserMedia=async()=>{
    const track={enabled:true,stopped:false,stop(){this.stopped=true;this.enabled=false}};state.tracks.push(track);
    return {getAudioTracks:()=>[track],getTracks:()=>[track]};
  };
  window.RTCPeerConnection=class {
    addTransceiver(){return {sender:{replaceTrack:async()=>{}}}}
    createDataChannel(){const handlers={};return state.channel={readyState:'open',sent:[],
      addEventListener(k,f){(handlers[k] ||= []).push(f)},removeEventListener(){},
      send(s){this.sent.push(JSON.parse(s))},close(){this.readyState='closed'},
      message(e){for(const f of handlers.message || [])f({data:JSON.stringify(e)})}};}
    async createOffer(){return {sdp:'synthetic-offer'}} async setLocalDescription(){}
    async setRemoteDescription(){} close(){}
  };
  const nativeFetch=fetch;
  window.fetch=(url,options)=>{
    state.requests.push(String(url));
    if(String(url)==='https://api.openai.com/v1/realtime/calls')return Promise.resolve(new Response('synthetic-answer'));
    return nativeFetch(url,options);
  };
})()'''

class VoiceBrowser(navigation.GameScreens):
    pass
for _name in dir(navigation.GameScreens):
    if _name.startswith('test_'):setattr(VoiceBrowser,_name,None)

def hold(self,text,*,touch=False):
    point=self.page.evaluate('(()=>{const r=document.querySelector("#voice-talk").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
    if touch:self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{**point,'id':1}]})
    else:self.page.send('Input.dispatchMouseEvent',{'type':'mousePressed',**point,'button':'left','clickCount':1})
    try:self.wait('document.querySelector("#voice-talk").dataset.voiceState==="listening"')
    except AssertionError:
        self.fail(str(self.page.evaluate('({state:document.querySelector("#voice-talk")?.dataset.voiceState,status:document.querySelector("#voice-status")?.textContent,tracks:window.__voiceTest.tracks,requests:window.__voiceTest.requests})')))
    if touch:self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
    else:self.page.send('Input.dispatchMouseEvent',{'type':'mouseReleased',**point,'button':'left','clickCount':1})
    self.wait('window.__voiceTest.tracks.at(-1)?.stopped')
    self.page.evaluate('window.__voiceTest.channel.message('+json.dumps({
        'type':'conversation.item.input_audio_transcription.completed','item_id':text,'transcript':text})+')')

def test_voice_routes_guide_lab_and_rover_with_audio_off(self):
    world,owner,app=self.setup_world();self.browser(world,owner)
    self.page.send('Page.addScriptToEvaluateOnNewDocument',{'source':FAKE_TRANSPORT})
    self.navigate(world,'workshop=1&tab=inventory')
    self.assertEqual('off',self.page.evaluate('document.querySelector("#game-menu-audio select").value'))
    app.api_key='provider-fixture'
    turns=[{'status':'completed','output':[{'type':'function_call','call_id':'pick','name':'select_source',
        'arguments':json.dumps({'id':'recipe:field-pick:Personal field pick'})}]},
        {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'The supported pick draft is open.'}]}]}]
    with mock.patch.object(voice_api,'client_secret',return_value={'value':'synthetic-ephemeral'}), \
         mock.patch.object(workshop_chat,'_call_model',side_effect=lambda *_:turns.pop(0)):
        hold(self,'Use what I have to make a pick')
        self.wait('!!document.querySelector("#ws-draft-save") && document.querySelector("#ws-draft-save").offsetParent!==null && document.querySelector("#voice-talk").dataset.voiceState==="idle"')
    app.api_key=''
    before=self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()')
    hold(self,'Make the handle longer')
    self.wait('document.querySelector("#ws-lab-draft").textContent.includes("Draft saved") && document.querySelector("#voice-talk").dataset.voiceState==="idle"')
    self.assertNotEqual(before,self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
    self.assertFalse(app.room.fabrication_record['jobs'])
    self.assertEqual(0,self.page.evaluate('window.__voiceTest.channel.sent.filter(e=>e.type==="response.create").length'))
    self.assertFalse(self.page.evaluate('window.__voiceTest.requests.some(u=>u.includes("/voice/ask"))'))
    self.page.send('Emulation.setDeviceMetricsOverride',{'width':844,'height':390,'deviceScaleFactor':1,'mobile':True})
    self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':True})
    self.screenshot('voice-lab-landscape.png')
    self.page.send('Page.navigate',{'url':self.base+f'/world?world={world}'})
    self.wait('window.banjoRoom?.ready()')
    # The rover's own controls, opened as a player opens them: look at it
    # and press E. Details, which this opened, went with the inspector rail
    # (eaf9e306).
    self.page.evaluate('(()=>{const r=banjoRoom,b=r.world.machines.programs.find(p=>p.kind==="roam").body,'
                       'p=r.world.bodies.get(b).mesh.position;r.standAt(p.x+.8,p.y+1.1,p.z+.5);r.lookAt(p.x,p.y,p.z);})()')
    self.wait('(()=>{const r=banjoRoom,q=r.world.machines.programs.find(p=>p.kind==="roam"),'
              'p=r.world.bodies.get(q.body).mesh.position;r.lookAt(p.x,p.y,p.z);return q.parts.includes(r.world.aim?.name)})()')
    for kind in ('keyDown','keyUp'):
        self.page.send('Input.dispatchKeyEvent',{'type':kind,'code':'KeyE','key':'e','windowsVirtualKeyCode':69})
    self.wait('document.body.classList.contains("machine-open")');self.wait_rail_shown()
    self.click('#machine-panel .rover-card button:not([data-rover-command])')
    with mock.patch.object(voice_api,'client_secret',return_value={'value':'synthetic-ephemeral'}):
        hold(self,'stop',touch=True)
        self.wait('document.querySelector("#chat").textContent.includes("Stopping. I will hold here") && document.querySelector("#voice-talk").dataset.voiceState==="idle"')
    self.assertEqual('waiting',self.page.evaluate('banjoRoom.world.machines.programs.find(p=>p.kind==="roam").asked?.doing'))
    self.screenshot('voice-rover-landscape.png')
    self.page.evaluate('document.querySelector("#game-menu-audio select").value="on";document.querySelector("#game-menu-audio select").dispatchEvent(new Event("change"))')
    self.page.evaluate('document.querySelector("#ask-text").value="what are you doing?";document.querySelector("#ask").requestSubmit()')
    self.wait('window.__voiceTest.channel.sent.some(e=>e.type==="response.create")')
    response=self.page.evaluate('window.__voiceTest.channel.sent.filter(e=>e.type==="response.create").at(-1).response')
    self.assertEqual('none',response['conversation'])
    self.assertIn('Banjo chat reply',response['instructions'])
    self.page.evaluate('document.querySelector("#game-menu-audio select").value="off";document.querySelector("#game-menu-audio select").dispatchEvent(new Event("change"))')
    self.assertTrue(self.page.evaluate('document.querySelector("audio").muted'))
    self.page.send('Page.reload');self.wait('window.banjoRoom?.ready()')
    self.assertEqual('off',self.page.evaluate('document.querySelector("#game-menu-audio select").value'))
    with mock.patch.object(voice_api,'client_secret',side_effect=ValueError('Controlled voice failure')):
        self.click('#voice-talk');self.wait('document.querySelector("#voice-status").textContent.includes("Controlled voice failure")')
    self.assertFalse(self.page.evaluate('document.querySelector("#ask-text").disabled'))
    self.assertEqual([], [e for e in self.page.events if e.get('method')=='Runtime.exceptionThrown'])

VoiceBrowser.test_voice_routes_guide_lab_and_rover_with_audio_off=test_voice_routes_guide_lab_and_rover_with_audio_off

def test_voice_transport_policy_authentication_and_shared_guide_memory(self):
    world,owner,app=self.setup_world()
    with request.urlopen(self.base+f'/world?world={world}') as response:
        policy=response.headers['Content-Security-Policy']
    self.assertIn("connect-src 'self' https://api.openai.com;",policy)
    self.assertIn("media-src 'self' blob:;",policy)
    self.assertNotIn('unsafe-inline',policy)
    with mock.patch.object(voice_api,'client_secret',return_value={'value':'fixture'}) as mint:
        for token,body in ((owner['token'],{'model':'forged'}),('invalid-player',{})):
            with self.subTest(body=body),self.assertRaises(error.HTTPError):
                self.post('/api/world/voice/session',body,world,token)
        mint.assert_not_called()
        self.assertEqual('fixture',self.post('/api/world/voice/session',{},world)['value'])
    observed=[]
    def answer(app,body,context):
        observed.append(body)
        return {'reply':'Current authenticated guide answer.','mode':'fixture'}
    with mock.patch.object(game_guidance,'answer',side_effect=answer):
        self.post('/api/world/help',{'message':'What now?','screen':'world'},world)
        self.post('/api/world/help',{'message':'Why?','screen':'build'},world)
        peer=self.join(world,'Private voice peer')
        self.post('/api/world/help',{'message':'What now?'},world,peer['token'])
    self.assertEqual([],observed[0]['history'])
    self.assertEqual(['user','assistant'],[row['role'] for row in observed[1]['history']])
    self.assertEqual('What now?',observed[1]['history'][0]['content'])
    self.assertEqual([],observed[2]['history'])
    self.assertEqual(4,self.post('/api/world/voice/memory',{},world)['remembered'])
    self.assertEqual(2,self.post('/api/world/voice/memory',{},world,peer['token'])['remembered'])

VoiceBrowser.test_voice_transport_policy_authentication_and_shared_guide_memory=test_voice_transport_policy_authentication_and_shared_guide_memory
if __name__=='__main__':unittest.main()
