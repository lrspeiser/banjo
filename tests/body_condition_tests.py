"""Native condition HTTP, private carried products and ordinary browser views."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import time
import unittest
import urllib.error
import world_goods_tests as flow

ROOT=Path(__file__).resolve().parents[1]

class BodyCondition(unittest.TestCase):
    setUp=flow.GoodsJourney.setUp
    def tearDown(self):
        # Stop the browser's polling before the isolated server/database.
        if getattr(self,'chrome',None) is not None:self.chrome.close()
        flow.GoodsJourney.tearDown(self)
    start=flow.GoodsJourney.start
    stop=flow.GoodsJourney.stop
    get=flow.GoodsJourney.get
    post=flow.GoodsJourney.post
    join=flow.GoodsJourney.join
    setup_world=flow.GoodsJourney.setup_world

    def take_pick(self,world,app):
        sid=app.live.session.id
        floor=self.post('/api/live/act',{'session':sid,'op':'survey','at':[-.9,.025]},world)['survey']['ground_m']
        person={'standing_m':[-.9,floor,.025],'eyes_m':[-.9,floor+1.62,.025],
                'facing':[1,0,0],'look_direction':[1.2,-1.62,0]}
        shown=self.post('/api/world/inventory/shown',{'session':sid},world)
        result=self.post('/api/world/inventory',{'session':sid,'op':'take_up','item':'field pick',
            'request':'condition-take','revision':shown['record']['revision'],'person':person},world)
        self.assertTrue(result['ok'],result)
        return person

    def test_read_only_bounded_private_carried_and_parked_readings(self):
        world,owner,app=self.setup_world();person=self.take_pick(world,app);sid=app.live.session.id
        self.post('/api/live/act',{'session':sid,'op':'poses'},world)
        snapshot,why=app.live.snapshot();self.assertIsNotNone(snapshot,why)
        before=deepcopy(snapshot)
        row=self.post('/api/live/act',{'session':sid,'op':'condition','names':['field pick']},world)['condition']
        self.assertEqual('banjo.body-condition.v1',row['schema'])
        self.assertEqual('measured',row['bodies'][0]['state']);self.assertEqual(1,row['bodies'][0]['fraction'])
        self.assertFalse(row['fatigue_supported']);self.assertFalse(row['repair_supported'])
        after,why=app.live.snapshot();self.assertEqual(before,after,'condition query mutated physical snapshot')
        for names in ([],['field pick']*2,['x'*161],[None],['é'*81],[str(i) for i in range(65)]):
            with self.subTest(names=names),self.assertRaises(urllib.error.HTTPError) as refused:
                self.post('/api/live/act',{'session':sid,'op':'condition','names':names},world)
            self.assertEqual(400,refused.exception.code)
        inv=self.post('/api/workshop/inventory',{},world)
        pick=next(t for t in inv['carried'] if t['id']=='field pick')
        self.assertEqual(row['bodies'],pick['condition'])
        peer=self.join(world,'Condition peer')
        self.assertEqual([],self.post('/api/workshop/inventory',{},world,peer['token'])['carried'])
        shown=self.post('/api/world/inventory/shown',{'session':sid},world)
        self.post('/api/world/inventory',{'session':sid,'op':'stow','item':'field pick',
            'request':'condition-stow','revision':shown['record']['revision'],'person':person},world)
        packed=self.post('/api/workshop/inventory',{},world)['carried'][0]
        self.assertTrue(packed['condition'][0]['parked']);self.assertEqual(1,packed['condition'][0]['fraction'])
        self.assertTrue(flow.server.keep_world(app,'condition bag persistence'))
        self.stop();self.start()
        self.post('/api/world/player/join',{'token':owner['token']},world)
        self.post('/api/world/open',{},world)
        self.assertEqual(packed['condition'],self.post('/api/workshop/inventory',{},world)['carried'][0]['condition'])

    def test_world_inventory_lab_and_empty_lab_show_native_condition(self):
        if not flow.qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,owner,app=self.setup_world();self.take_pick(world,app)
        chrome=flow.qa_browser.Chrome(1280,800);self.chrome=chrome;self.addCleanup(chrome.close)
        p=chrome.page;p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])});'})
        def wait(expr,seconds=30):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('document.body.innerText.slice(-1500)')))
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
        wait('window.banjoRoom?.ready()');p.evaluate('banjoRoom.pick("field pick","cells")')
        wait('document.querySelector("#picked .body-condition meter")?.value===1')
        p.evaluate('banjoRoom.pick("solar farm","cells")')
        wait('document.querySelector("#picked .body-condition")?.dataset.conditionState==="unmodeled"')
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=inventory'})
        wait('document.querySelector("#ws-inv-grid .body-condition meter")?.value===1')
        p.evaluate('document.querySelector("#ws-inv-grid .ws-action").click()')
        wait('document.querySelector("#ws-carried-condition")?.hidden===false && document.querySelector("#ws-carried-condition meter")?.value===1')
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'condition-lab.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=lab'})
        wait('document.querySelector("#design-workshop")?.classList.contains("lab-empty")')
        self.assertTrue(p.evaluate('document.querySelector("#ws-carried-condition").hidden'))
        self.assertEqual([],[e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])

if __name__=='__main__':unittest.main()
