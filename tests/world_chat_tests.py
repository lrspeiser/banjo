"""Authenticated chat audiences, durable broadcasts and World browser flow."""
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'playground'),str(ROOT)]
import ai_player_tests as fixture
import workshop_navigation_tests as navigation
import workshop_chat
import player_world
import player_messages


@unittest.skipUnless(fixture.hub.RUNNER.is_file() and fixture.hub.ENGINE.is_file(),'native world engine not built')
class ChatAudiences(unittest.TestCase):
    setUp=fixture.AutonomousGuests.setUp
    tearDown=fixture.AutonomousGuests.tearDown
    start=fixture.AutonomousGuests.start
    stop=fixture.AutonomousGuests.stop
    get=fixture.AutonomousGuests.get
    post=fixture.AutonomousGuests.post
    join=fixture.AutonomousGuests.join
    setup_world=fixture.AutonomousGuests.setup_world

    def test_same_world_delivery_authentication_and_restart_deduplication(self):
        world,owner,app=self.setup_world();peer=self.join(world,'Neighbor')
        request={'action':'send','message':'Where is the workbench?','request_id':'player-message-1'}
        sent=self.post('/api/world/messages',request,world)
        self.assertEqual('Human',sent['messages'][0]['name'])
        read=self.post('/api/world/messages',{'action':'list'},world,peer['token'])
        self.assertEqual(sent['messages'],read['messages'])
        for token,body in [('invalid-token',{'action':'list'}),
                           (peer['token'],request),
                           (owner['token'],{**request,'message':'different'})]:
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/messages',body,world,token)
        self.assertEqual([],self.post('/api/world/messages',{'after_id':read['cursor']},world)['messages'])
        self.stop();self.start()
        repeated=self.post('/api/world/messages',request,world)
        self.assertTrue(repeated['repeated']);self.assertEqual(sent['messages'],repeated['messages'])

    def test_other_worlds_are_isolated_and_messages_are_bounded(self):
        world,owner,app=self.setup_world()
        sent=self.post('/api/world/messages',{'action':'send','message':'Only this world','request_id':'local-message'},world)
        try:other=self.post('/api/worlds',{'name':'Other'})['id']
        except urllib.error.HTTPError as exc:self.fail('Second world creation: '+exc.read().decode())
        self.players[other]=self.join(other,'Elsewhere')
        self.assertEqual([],self.post('/api/world/messages',{'action':'list'},other)['messages'])
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/messages',{'action':'list'},other,owner['token'])
        for bad in ({'action':'send','message':'x'*1001,'request_id':'long-message'},
                    {'action':'send','message':'Hi','request_id':'spoof-name','name':'Admin'},
                    {'action':'list','after_id':True}):
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/messages',bad,world)
        with mock.patch.object(player_messages,'time',SimpleNamespace(time=lambda:sent['messages'][0]['created_at']+10)):
            for i in range(5):self.post('/api/world/messages',{'action':'send','message':'Hi','request_id':f'limited-{i}'},world)
            with self.assertRaises(urllib.error.HTTPError):
                self.post('/api/world/messages',{'action':'send','message':'Too fast','request_id':'limited-extra'},world)

    def test_character_uses_own_state_without_control_or_private_tokens(self):
        world,owner,app=self.setup_world();character=self.join(world,'Ada')
        with player_world.lock_of(app):
            profile=player_world.records(app)[character['id']]
            profile['ai']={'status':'blocked','message':'Waiting for energy','history':[], 'memory':{},'controller':owner['id']}
        before=json.dumps(profile,sort_keys=True)
        self.post('/api/workshop/market',{'action':'bank','joules':500,'request_id':'character-chat-bank'},world)
        app.api_key='test';seen=[]
        def provider(app,payload):
            seen.append(payload)
            return {'status':'completed','output':[{'content':[{'type':'output_text','text':'I am waiting for energy.'}]}]}
        with mock.patch.object(workshop_chat,'_call_model',side_effect=provider):
            answer=self.post('/api/world/character/chat',{'id':character['id'],'message':'How are you doing?'},world)
        self.assertEqual('Ada',answer['name']);self.assertEqual(before,json.dumps(profile,sort_keys=True))
        context=json.loads(seen[0]['input'][-1]['content'])['server_observations']
        self.assertEqual(0,context['wallet_j']);self.assertEqual('blocked',context['speaker']['status'])
        self.assertEqual([],seen[0]['tools'])
        self.assertNotIn(owner['token'],json.dumps(seen));self.assertNotIn(character['token'],json.dumps(seen))
        for ident in ([],owner['id']):
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/character/chat',{'id':ident,'message':'Hi'},world)

    def test_action_history_is_private_on_open_and_rejoin(self):
        world,owner,app=self.setup_world();peer=self.join(world,'Neighbor')
        app.room.chat=[{'asked':'legacy shared text','replied':'legacy'}]
        player_world.records(app)[owner['id']]['action_chat']=[{'asked':'private question','replied':'private reply'}]
        own=self.post('/api/world/open',{},world)
        other=self.post('/api/world/open',{},world,peer['token'])
        self.assertEqual('private question',own['chat'][0]['asked']);self.assertEqual([],other['chat'])
        histories=[]
        def actions(*args,**kwargs):
            histories.append(json.loads(json.dumps(kwargs['history'])))
            return {'reply':'Read your own action history','did':[]}
        with mock.patch.object(fixture.server.world_chat,'ask',side_effect=actions):
            for token,message in ((owner['token'],'My action'),(peer['token'],'Peer action')):
                self.post('/api/world/ask',{'session':app.live.session.id,'message':message},world,token)
        self.assertEqual('private question',histories[0][0]['asked']);self.assertEqual([],histories[1])
        self.stop();self.start()
        self.assertEqual('My action',self.post('/api/world/open',{},world)['chat'][-1]['asked'])
        self.assertEqual('Peer action',self.post('/api/world/open',{},world,peer['token'])['chat'][-1]['asked'])


@unittest.skipUnless(fixture.hub.RUNNER.is_file() and fixture.hub.ENGINE.is_file(),'native world engine not built')
class WorldChatBrowser(unittest.TestCase):
    setUp=navigation.GameScreens.setUp
    tearDown=navigation.GameScreens.tearDown
    start=navigation.GameScreens.start
    stop=navigation.GameScreens.stop
    get=navigation.GameScreens.get
    post=navigation.GameScreens.post
    join=navigation.GameScreens.join
    setup_world=navigation.GameScreens.setup_world
    browser=navigation.GameScreens.browser
    wait=navigation.GameScreens.wait
    screenshot=navigation.GameScreens.screenshot

    def test_guide_and_two_players_have_separate_channels(self):
        world,owner,app=self.setup_world();peer=self.join(world,'Neighbor');app.api_key='test'
        self.browser(world,owner)
        self.page.send('Page.navigate',{'url':self.base+f'/world?world={world}'})
        self.wait('window.banjoRoom?.ready() && !!document.querySelector("#chat-recipient")')
        self.assertEqual('guide',self.page.evaluate('document.querySelector("#chat-recipient").value'))
        seen=[]
        def provider(app,payload):
            seen.append(json.loads(payload['input'][-1]['content']))
            return {'status':'completed','output':[{'content':[{'type':'output_text','text':'Use Market → Bank for your energy.'}]}]}
        with mock.patch.object(workshop_chat,'_call_model',side_effect=provider):
            self.page.evaluate('document.querySelector("#ask-text").value="Why am I not collecting energy?";document.querySelector("#ask").requestSubmit()')
            self.wait('document.querySelector("#chat").textContent.includes("Use Market")')
        self.assertEqual('world',seen[0]['screen']);self.assertEqual(0,seen[0]['server_observations']['wallet_j'])
        self.assertEqual([],self.post('/api/world/messages',{'action':'list'},world,peer['token'])['messages'])
        self.page.evaluate('document.querySelector("#chat-recipient").value="players";document.querySelector("#chat-recipient").dispatchEvent(new Event("change"));document.querySelector("#ask-text").value="Hello neighbor";document.querySelector("#ask").requestSubmit()')
        self.wait('document.querySelector("#chat").textContent.includes("Hello neighbor")')
        self.assertNotIn('Use Market',self.page.evaluate('document.querySelector("#chat").textContent'))
        self.assertEqual('Hello neighbor',self.post('/api/world/messages',{'action':'list'},world,peer['token'])['messages'][0]['message'])
        # A second authenticated player responds; its untrusted content remains text.
        self.post('/api/world/messages',{'action':'send','message':'<img src=x onerror=alert(1)> Hi Human','request_id':'neighbor-response'},world,peer['token'])
        self.wait('document.querySelector("#chat").textContent.includes("Hi Human")')
        self.assertEqual(0,self.page.evaluate('document.querySelectorAll("#chat img").length'))
        self.assertEqual(1,self.page.evaluate('Array.from(document.querySelectorAll("#chat .turn")).filter(t=>t.textContent.includes("Hello neighbor")).length'))
        self.screenshot('world-player-chat.png')
        self.page.evaluate('''(()=>{const original=window.fetch;window.fetch=async(...args)=>{
            const response=await original(...args);
            if(String(args[0])==='/api/world/messages'&&JSON.parse(args[1]?.body||'{}').action==='send'){
                window.fetch=original;throw Error('Simulated lost acknowledgement')}
            return response};document.querySelector('#ask-text').value='Retry safely';
            document.querySelector('#ask').requestSubmit()})()''')
        self.wait('!document.querySelector("#ask").nextElementSibling.hidden && !window.banjoRoom.world.asking')
        self.page.evaluate('document.querySelector("#ask").nextElementSibling.click()')
        self.wait('document.querySelector("#ask").nextElementSibling.hidden && !window.banjoRoom.world.asking')
        listed=self.post('/api/world/messages',{'action':'list'},world,peer['token'])['messages']
        self.assertEqual(1,len([m for m in listed if m['message']=='Retry safely']))
        self.page.evaluate('document.querySelector("#chat-recipient").value="guide";document.querySelector("#chat-recipient").dispatchEvent(new Event("change"))')
        self.assertIn('Use Market',self.page.evaluate('document.querySelector("#chat").textContent'))
        self.assertNotIn('Hello neighbor',self.page.evaluate('document.querySelector("#chat").textContent'))
        self.wait('Array.from(document.querySelector("#chat-recipient").options).some(o=>o.value.startsWith("robot:"))')
        self.page.evaluate('''(()=>{const recipient=document.querySelector('#chat-recipient');
            recipient.value=Array.from(recipient.options).find(o=>o.value.startsWith('robot:')).value;
            recipient.dispatchEvent(new Event('change'));document.querySelector('#ask-text').value='What are you doing?';
            document.querySelector('#ask').requestSubmit()})()''')
        self.wait('!window.banjoRoom.world.asking && document.querySelector("#chat").querySelectorAll(".turn").length>=2')
        self.assertNotIn('Trouble',self.page.evaluate('document.querySelector("#chat").textContent'))


if __name__=='__main__':unittest.main()
