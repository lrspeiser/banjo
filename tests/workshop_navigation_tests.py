"""Inventory selection, an empty Lab and shared right-side navigation."""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "playground"), str(ROOT)]
import ai_player_tests as guests
import qa_browser


@unittest.skipUnless(guests.hub.RUNNER.is_file() and guests.hub.ENGINE.is_file(), "native world engine not built")
class GameScreens(unittest.TestCase):
    get, post, join = guests.AutonomousGuests.get, guests.AutonomousGuests.post, guests.AutonomousGuests.join
    setUp = guests.AutonomousGuests.setUp
    start, stop, setup_world = guests.AutonomousGuests.start, guests.AutonomousGuests.stop, guests.AutonomousGuests.setup_world

    def tearDown(self):
        # Stop browser polling before removing the server's SQLite directory.
        if getattr(self,"chrome",None): self.chrome.close()
        guests.AutonomousGuests.tearDown(self)

    def browser(self, world, owner):
        if not qa_browser.CHROME.is_file():
            if os.environ.get("BANJO_BROWSER_TESTS") == "required": self.fail("Chrome is required")
            self.skipTest("Chrome not installed")
        chrome = qa_browser.Chrome(1440, 900); self.addCleanup(chrome.close)
        self.chrome = chrome
        self.page = chrome.page
        self.page.send("Page.enable"); self.page.send("Runtime.enable")
        self.page.send("Page.navigate", {"url":self.base + "/api/status"})
        self.wait('location.pathname === "/api/status"')
        self.page.evaluate(f'localStorage.setItem("banjo.player.{world}", {json.dumps(owner["token"])})')
        return self.page

    def wait(self, expression, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if self.page.evaluate(expression): return
            except (RuntimeError, TimeoutError): pass
            time.sleep(.1)
        self.fail("Browser did not reach " + expression + "; " + str(self.page.evaluate('({notice:document.querySelector("#ws-notice")?.textContent,url:location.href,stage:document.querySelector("#workshop-stage")?.dataset,name:document.querySelector("#ws-name")?.textContent,draft:document.querySelector("#ws-lab-draft")?.textContent})')) + '; ' + str([e for e in self.page.events if e.get('method')=='Runtime.exceptionThrown']))

    def navigate(self, world, query):
        self.page.send("Page.navigate", {"url":self.base + f"/world?world={world}&" + query})
        self.wait('!!document.querySelector("#ws-screen-status") && !!document.querySelector("#ws-chat-log")')

    def click(self, selector):
        # A real pointer click: it must land on the element itself, not on
        # whatever covers it or on a list still growing around it.
        target = json.dumps(selector)
        self.wait(f'(()=>{{const e=document.querySelector({target});if(!e)return false;e.scrollIntoView({{block:"center"}});'
                  f'const r=e.getBoundingClientRect(),h=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);'
                  f'return r.width>0 && r.height>0 && !!h && (h===e || e.contains(h))}})()')
        point = self.page.evaluate(f'(()=>{{const e=document.querySelector({target}),r=e.getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()')
        for event in ("mousePressed", "mouseReleased"):
            self.page.send("Input.dispatchMouseEvent", {"type":event, **point, "button":"left", "clickCount":1})

    def wait_rail_shown(self):
        # The World right rail slides in; wait until it is fully on screen.
        self.wait('!document.body.classList.contains("panel-away") && '
                  'Math.abs(document.querySelector("#panel").getBoundingClientRect().right - innerWidth) < 1')

    def open_rail(self):
        # Details in the bottom navigation opens the folded right rail.
        self.click('#panel-details'); self.wait_rail_shown()

    def assert_empty(self):
        self.wait('document.querySelector("#workshop-stage").dataset.showing === "empty"')
        self.assertIsNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
        self.assertTrue(self.page.evaluate('document.querySelector("#ws-empty").offsetParent !== null'))
        self.assertFalse(self.page.evaluate('document.querySelector("#ws-component-chat-text").disabled'))

    def screenshot(self, name):
        out = ROOT / "build/workshop-navigation"; out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(base64.b64decode(self.page.send("Page.captureScreenshot")["data"]))

    def test_market_chat_reads_game_state_without_a_lab_selection(self):
        import workshop_chat
        world,owner,app=self.setup_world();app.api_key='test-key'
        self.browser(world,owner)
        self.navigate(world,'workshop=1&tab=market')
        self.wait('!document.querySelector("#ws-component-chat-text").disabled')
        seen=[]
        def provider(app,payload):
            seen.append(json.loads(payload['input'][-1]['content']))
            return {'status':'completed','output':[{'content':[{'type':'output_text',
                'text':'Your wallet is 0 J. Shared solar charge is separate. Use Market → Bank.'}]}]}
        with mock.patch.object(workshop_chat,'_call_model',side_effect=provider):
            self.page.evaluate('document.querySelector("#ws-component-chat-text").value="Why am I not collecting energy?";document.querySelector("#ws-component-chat").requestSubmit()')
            self.wait('document.querySelector("#ws-chat-log").textContent.includes("Shared solar charge is separate")')
        self.assertEqual('market',seen[0]['screen'])
        self.assertEqual(0,seen[0]['server_observations']['wallet_j'])
        self.assertTrue(self.page.evaluate('document.querySelector("#design-workshop").classList.contains("lab-empty")'))
        self.assertFalse(self.page.evaluate('document.querySelector("#ws-component-chat-text").disabled'))
        self.screenshot('market-game-chat.png')

    def test_owned_solar_array_paid_build_market_inventory_and_peer(self):
        import math
        import fabrication_stock_tests as funded
        import server
        # New worlds pick one of two terrains at random. On terrain 4 the
        # fixed [-2,0] spot is uneven: the 0.2 m array tips about 34 degrees
        # and its own frame shades its panel. Pin the terrain the fixture was
        # written for (as the reveal tests below do) and check it is upright.
        with mock.patch.object(server.secrets,'randbelow',side_effect=[1,851269741]):
            world,owner,app=self.setup_world(legacy_process=True)
        peer=self.join(world,'Solar peer')
        def post(path,body):
            try:return self.post(path,body,world)
            except guests.urllib.error.HTTPError as error:self.fail(path+': '+error.read().decode())
        def context():return {'scene':app.room.scene,'session':app.live.session.id}
        def wait_sim(seconds):
            while seconds:
                n=min(10,seconds);post('/api/world/fabrication/wait',{**context(),'seconds':n});seconds-=n
        # Explicit finite authored fixture supplies; manufacturing still pays
        # actual material/assembly goods and native energy, with no free item.
        pile=app.brains.goods.put(0,0,{'oak':40.,'glass':5.,'copper':.5,'copper wire':.1},named='solar build fixture')['onto']
        floor=app.live.act({**context(),'op':'survey','at':[0,0]})['survey']['ground_m']
        for index in range(3):
            if not any(app.brains.goods.by_name(pile).get('holds',{}).values()):break
            post('/api/world/goods/collect',{'session':app.live.session.id,'pile':pile,'request_id':f'solar-collect-{index}',
                'person':{'eyes_m':[0,floor+1.62,0],'facing':[0,0,-1]}})
        post('/api/world/fabrication/configure',{**context(),'settings':funded.settings(stock_kg={},energy_j=0),
            'request_id':'solar-configure'})
        candidate={'kind':'solar-array','parameters':{'panels':1,'panel_w_m':.2,'panel_d_m':.2,
            'frame_height_m':.2,'capacity_j':100.,'charge_j':0.}}
        plan=post('/api/world/fabrication/plan_make',{**context(),'candidate':candidate})
        from mcp import fabrication
        for goods, needs in ((False,fabrication.materials(plan['quote'],'stock')),(True,plan['quote']['assembly_goods_kg'])):
            for material,mass in needs.items():
                state=post('/api/world/fabrication/state',context())
                source=next(s for s in state['goods_sources' if goods else 'stock_sources']
                            if s['material']==material and s['pool']=='personal')
                self.assertGreaterEqual(source['mass_kg']+1e-9,mass,material)
                post('/api/world/fabrication/fund_goods' if goods else '/api/world/fabrication/fund_stock',
                    {**context(),'material':material,'mass_kg':mass,'pool':'personal','rack_hash':source['rack_hash'],
                     'revision':state['state']['revision'],'request_id':'solar-fund-'+material.replace(' ','-')})
        state=post('/api/world/fabrication/state',context());source=next(s for s in state['energy_sources'] if s['max_power_w']>=250.)
        post('/api/world/fabrication/connect_energy',{**context(),'store':source['id'],'store_hash':source['store_hash'],
            'power_w':250.,'revision':state['state']['revision'],'request_id':'solar-connect'})
        wait_sim(math.ceil(plan['quote']['supply_required_j']/250.))
        state=post('/api/world/fabrication/state',context());source=next(s for s in state['energy_sources'] if s['connected'])
        post('/api/world/fabrication/fund_energy',{**context(),'store_hash':source['store_hash'],
            'joules':plan['quote']['supply_required_j'],'revision':state['state']['revision'],'request_id':'solar-energy'})
        plan=post('/api/world/fabrication/plan_make',{**context(),'candidate':candidate})
        started=post('/api/world/fabrication/start_make',{**context(),'plan_id':plan['plan_id'],'revision':plan['revision'],'request_id':'solar-build'})
        wait_sim(math.ceil(started['state']['jobs']['solar-build']['minimum_duration_s']))
        preview=post('/api/world/fabrication/preview',{**context(),'job_id':'solar-build','position_m':[-2,0]})
        installed=post('/api/world/fabrication/commit',{**context(),'job_id':'solar-build','preview_id':preview['preview_id'],'request_id':'solar-install'})
        app.live.session.send(op='sun',day_s=600,noon_elevation_deg=70.,hour=12.,irradiance_w_m2=1000.)
        app.live.act({'session':app.live.session.id,'op':'poses'})
        for _ in range(40):app.clock._tick(.25)
        panels=[p for p in app.live.act({'session':app.live.session.id,'op':'poses'})['machines']['panels']
                if p['body']==installed['root_body']]
        self.assertEqual(1,len(panels))
        self.assertGreater(panels[0]['normal'][1],.99,panels[0])
        self.assertFalse(panels[0]['shaded'],panels[0])
        wallet=post('/api/workshop/market',{'action':'view'})
        self.assertGreater(wallet['balance_j'],0);self.assertEqual(1,len(wallet['automatic_sources']))
        other=self.post('/api/workshop/market',{'action':'view'},world,peer['token'])
        self.assertEqual(0,other['balance_j']);self.assertEqual([],other['automatic_sources'])
        self.browser(world,owner);self.navigate(world,'workshop=1&tab=market')
        self.wait('document.querySelector("#ws-market-energy")?.textContent.includes("Automatic")')
        self.assertIn('Reserve',self.page.evaluate('document.querySelector("#ws-market-energy").textContent'))
        self.screenshot('solar-auto-bank-market.png')
        self.click('.game-tabs [data-screen="inventory"]')
        self.wait('document.querySelector("#ws-inv-energy")?.textContent.includes("1 arrays")')
        self.screenshot('solar-auto-bank-inventory.png')
        self.assertEqual([], [e for e in self.page.events if e.get('method')=='Runtime.exceptionThrown'])
        self.page.send('Page.navigate',{'url':'about:blank'});self.stop();self.start()
        self.post('/api/world/player/join',{'token':owner['token']},world)
        self.post('/api/world/open',{},world)
        restored=self.post('/api/workshop/market',{'action':'view'},world)
        self.assertEqual(wallet['balance_j'],restored['balance_j'])
        self.assertEqual(1,len(restored['automatic_sources']))

    def test_authored_iron_head_and_wood_handle_pickup_dig_bag_and_reload(self):
        import server
        sys.path.insert(0,str(ROOT/'tools'))
        import build_new_world
        spec={
            'algorithm':'lattice','cell_m':.04,
            'terrain':{'generate':{'kind':'flat','nx':48,'nz':48,'cell_m':.1,
                'soil_m':.4,'sand_m':0,'discharge_m3_s':0}},
            'bodies':[
                {'name':'handle','shape':'box','material':'oak',
                 'size_mm':[800,40,40],'center_mm':[0,420,1220]},
                {'name':'head','shape':'box','material':'iron',
                 'size_mm':[40,40,280],'center_mm':[380,420,1060]}],
            'joints':[{'kind':'fixing','a':'handle','b':'head','at_mm':[380,420,1200],
                'axis':[0,0,1],'holds_tension_n':5000,'holds_shear_n':5000}],
            'tool_points':[{'body':'head','grip_body':'handle','tip_mm':[380,420,920],
                'pointing':[0,0,-1],'grip_mm':[-360,420,1220],
                'width_mm':40,'thickness_mm':40,'angle_deg':30,'length_mm':200}],
            'interactions':[{'object':'Mixed pick','template':'swing-and-lever',
                'parts':['handle','head'],'tool':'handle'}]}
        # Explicit authored QA tool, not a paid Make or free gameplay build.
        with mock.patch.object(build_new_world,'compose',return_value=spec):
            try:
                world,owner,app=self.setup_world(legacy_process=True)
            except guests.urllib.error.HTTPError as error:
                self.fail(error.read().decode())
        peer=self.join(world,'Peer')
        page=self.browser(world,owner)
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}'})
        def wait(expression,seconds=30):
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                if page.evaluate('Boolean('+expression+')'):return
                app.clock._tick(.05)
                time.sleep(.05)
            self.fail('Mixed-tool browser did not reach '+expression+'; '+str(page.evaluate(
                '({use:banjoRoom?.use(),held:banjoRoom?.held(),status:banjoRoom?.status()})'))+
                '; joints: '+str(app.live.session.send(op='joints')))
        def key(code,text):
            for kind in ('keyDown','keyUp'):
                page.send('Input.dispatchKeyEvent',{'type':kind,'code':code,'key':text,
                    'windowsVirtualKeyCode':ord(text.upper())})
        wait('!!window.banjoRoom?.ready() && document.querySelector("#panel-state").textContent==="Live."')
        # Let the ground-resting authored assembly settle before aiming.
        for _ in range(20):
            app.clock._tick(.05)
            time.sleep(.02)
        self.assertTrue(app.live.session.send(op='tool_points')['tool_points'][0]['grip_connected'],
            app.live.session.send(op='joints'))
        page.evaluate('(()=>{const r=banjoRoom,p=r.world.bodies.get("handle").mesh.position;'
            'r.standAt(-.9,r.groundAt(-.9,.02)+1.62,.02);r.lookAt(p.x,p.y,p.z)})()')
        wait('["handle","head"].includes(banjoRoom.world.aim?.name)')
        key('KeyE','e')
        wait('banjoRoom.held()?.name==="handle" && banjoRoom.use().mode==="tool-ready"')
        page.evaluate('banjoRoom.lookAt(.3,banjoRoom.groundAt(.3,.02),.02)')
        wait('banjoRoom.use().target?.enabled && banjoRoom.use().target.ready && banjoRoom.use().target.target?.distance_m>=1.15')
        key('KeyJ','j')
        wait('banjoRoom.use().mode==="tool-ready" && !!banjoRoom.use().last?.result')
        answer=page.evaluate('banjoRoom.use().last')
        result=answer['result']
        self.assertGreater(result['loosened_kg'],0,result)
        self.assertEqual(result['tool'],'handle')
        self.assertEqual(result['actor'],owner['id'],'the head work belongs to its holder')
        # Named worlds heap measured excavation into nearby material piles
        # (5af65746) instead of leaving it in the digger's carried account.
        piles={}
        for pile in answer.get('excavation_piles') or []:
            self.assertEqual('soil',pile['material'])
            piles[pile['pile']]=piles.get(pile['pile'],0)+pile['kg']
        self.assertAlmostEqual(sum(r['loosened_kg'] for r in answer.get('results') or [result]),
                               sum(piles.values()),delta=5e-6)
        def piled(app):
            return {name:app.brains.goods.by_name(name)['holds'].get('soil',0) for name in piles}
        self.assertEqual(piles.keys(),piled(app).keys())
        for name,kg in piled(app).items(): self.assertAlmostEqual(piles[name],kg,delta=5e-6)
        points=app.live.act({'session':app.live.session.id,'op':'tool_points'})['tool_points']
        self.assertEqual((points[0]['material'],points[0]['grip_body']),('iron','handle'))
        self.assertTrue(points[0]['grip_connected'])
        import inventory_room
        self.assertAlmostEqual(inventory_room._carried(app,owner['id'])['objects_kg'],4.42176,places=5)
        wait('document.querySelector("#details-facts").textContent.includes("iron") && document.querySelector("#details-facts").textContent.includes("4.42 kg")')
        self.assertNotIn('soil 0.0 kg',page.evaluate('document.querySelector("#world-load-meter small").textContent'))
        self.screenshot('mixed-tool-native-use.png')
        key('KeyQ','q')
        wait('!banjoRoom.held()')
        snapshot=app.live.session.send(op='snapshot')['snapshot']
        if isinstance(snapshot,str): snapshot=json.loads(snapshot)
        self.assertEqual({'handle','head'},{b['name'] for b in snapshot['bodies'] if 'parked' in b})
        page.send('Page.reload',{})
        # Both authored bodies are now privately parked. This fixture has no
        # other objects; roomReady's drawable-body guard is intentionally false.
        wait('!!window.banjoRoom?.status().session && document.querySelector("#panel-state").textContent==="Live."')
        accounts=app.live.session.state['player_carried']
        self.assertEqual(accounts[owner['id']].get('soil_kg',0),0,'dug soil was moved to its pile')
        self.assertEqual(accounts.get(peer['id'],{}).get('soil_kg',0),0)
        self.assertAlmostEqual(accounts[owner['id']]['objects_kg'],4.42176,places=5)
        for name,kg in piled(app).items(): self.assertAlmostEqual(piles[name],kg,delta=5e-6)
        self.assertFalse([e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
        # Exercise the saved server/native world, not only a page refresh.
        page.send('Page.navigate',{'url':'about:blank'})
        self.wait('location.href==="about:blank"')
        self.stop();self.start();app=self.app.hub.get(world)
        self.post('/api/world/open',{},world)
        accounts=app.live.session.state['player_carried']
        self.assertEqual(accounts[owner['id']].get('soil_kg',0),0)
        self.assertEqual(accounts.get(peer['id'],{}).get('soil_kg',0),0)
        self.assertAlmostEqual(accounts[owner['id']]['objects_kg'],4.42176,places=5)
        for name,kg in piled(app).items(): self.assertAlmostEqual(piles[name],kg,delta=5e-6)
        parked_point=app.live.session.send(op='tool_points')['tool_points'][0]
        self.assertEqual(parked_point['grip_body'],'handle')
        self.assertFalse(parked_point['grip_connected'],'parked members are not actively wieldable')
        self.navigate(world,'workshop=1&tab=inventory')
        self.wait('document.querySelector("#ws-pane-inventory").textContent.toLowerCase().includes("mixed pick")')
        self.screenshot('mixed-tool-native-bag-reload.png')
        shown=self.post('/api/world/inventory/shown',{'session':app.live.session.id},world)
        item=shown['stowed'][0]
        equipped=self.post('/api/world/inventory',{'session':app.live.session.id,'request':'mixed-native-equip-after-restart',
            'op':'equip','item':item['id'],'revision':shown['record']['revision'],
            'person':{'standing_m':[-.9,.4,.02],'eyes_m':[-.9,2.02,.02],'facing':[1,0,0]}},world)
        self.assertTrue(equipped['ok'],equipped)
        self.assertTrue(app.live.session.send(op='tool_points')['tool_points'][0]['grip_connected'])

    def test_watch_batch_button_earns_personal_skill_and_skills_link_to_real_equipment(self):
        import machine_witness
        world, owner, app = self.setup_world(); self.browser(world,owner)
        source = next(m for m in machine_witness.machines(app) if m["recipe"] == "smelt copper")
        self.page.send("Page.navigate", {"url":self.base + f"/world?world={world}"})
        self.wait('window.banjoRoom?.ready()',seconds=60)
        at = source["at_m"]
        self.page.evaluate(f'banjoRoom.standAt({at[0]},{at[1]+1.2},{at[2]+2}); banjoRoom.lookAt({at[0]},{at[1]},{at[2]})')
        # World's visible Menu is the shared bottom navigation (68bad3ca); the
        # rail header's copy is folded away with the rail.
        self.click('#world-quickbar [data-game-menu]')
        # The menu fills its Characters section asynchronously, above World
        # diagnostics; a click during that reflow presses one row and releases
        # on another. Click once the list has loaded, and check it opened.
        self.wait('document.querySelector("#game-menu").open && !!document.querySelector("#game-menu-ai-status").textContent')
        self.click('[data-world-menu="room"] summary')
        self.wait('document.querySelector("[data-world-menu=room]").open')
        selector = f'[aria-label="Control {source["machine"]}"]'
        self.wait(f'!!document.querySelector({json.dumps(selector)})')
        self.click(selector)
        self.page.evaluate('document.querySelector("#game-menu").close()')
        self.wait('document.querySelector("#mp-watch-batch")?.offsetParent !== null')
        # Controls opens the machine panel in the rail, unfolding it.
        self.wait_rail_shown()
        self.click("#mp-watch-batch")
        self.wait('document.querySelector("#mp-ack").textContent.includes("Stay nearby")')
        self.screenshot("watch-next-batch.png")
        for _ in range(200):
            app.clock._tick(.2)
            if "smelting-copper" in guests.server.journal_of(app,owner["id"]).knows(): break
        self.assertIn("smelting-copper",guests.server.journal_of(app,owner["id"]).knows())
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])
        self.navigate(world,"workshop=1&tab=skills")
        self.wait('!!document.querySelector("[data-technique=rough-shaping-wood]")')
        self.click('[data-technique="rough-shaping-wood"]')
        self.wait('document.querySelector("#ws-tree-about").textContent.includes("Missing example")')
        self.assertIn('Not available in this world yet',self.page.evaluate('document.querySelector("#ws-tree-about").innerText'))
        self.assertIn('You cannot unlock it by collecting supplies',self.page.evaluate('document.querySelector("#ws-tree-about").innerText'))
        self.assertFalse(self.page.evaluate('document.querySelector("#ws-skills-diagnostics").open'))
        self.assertNotIn("you were given",self.page.evaluate('document.querySelector("#ws-tree-about").textContent'))
        self.assertIn("Making not available yet",self.page.evaluate('document.querySelector("#ws-tree-about").textContent'))
        self.assertNotIn("shape-wood-v1",self.page.evaluate('document.querySelector("#ws-tree-about").textContent'))
        self.click('[data-technique="smelting-copper"]')
        self.assertIn('Learned ✓ · No further action needed',self.page.evaluate('document.querySelector("#ws-tree-about").innerText'))
        self.assertTrue(self.page.evaluate('!!document.querySelector("a.ws-link[href*=focus]")'))
        self.screenshot("world-aware-skills.png")
        self.click('a.ws-link[href*=focus]')
        self.wait('window.banjoRoom?.ready() && location.search.includes("focus=")',seconds=60)
        self.assertIn("focus=",self.page.evaluate('location.search'))
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_failed_bank_notice_is_visible_and_reload_retry_draws_only_once(self):
        world,owner,app=self.setup_world(); self.browser(world,owner)
        self.navigate(world,"workshop=1&tab=market")
        self.wait('document.querySelectorAll("#ws-market-offers li").length > 0 && !document.querySelector("#ws-market-bank").disabled')
        charge=next(s["given_j"] for s in app.live.session.state["machines"]["stores"] if s["body"]=="solar farm")
        with mock.patch.object(app.store,"_save",side_effect=OSError("test disk unavailable")):
            self.click("#ws-market-bank")
            self.wait('document.querySelector("#world-save-status")?.offsetParent !== null && document.querySelector("#world-save-status").textContent.includes("test disk unavailable")')
            self.wait('document.querySelector("#ws-market-bank").textContent.startsWith("Retry") && !document.querySelector("#ws-market-bank").disabled')
            self.screenshot("save-failure.png")
        self.navigate(world,"workshop=1&tab=market")
        self.wait('document.querySelector("#ws-market-bank")?.textContent === "Retry bank 100 J"')
        self.click("#ws-market-bank")
        self.wait('document.querySelector("#ws-market-balance").textContent === "100 J" && document.querySelector("#world-save-status").hidden')
        given=next(s["given_j"] for s in app.live.session.state["machines"]["stores"] if s["body"]=="solar farm")
        self.assertAlmostEqual(100,given-charge,places=6)
        self.assertFalse([e for e in self.page.events if e.get("method")=="Runtime.exceptionThrown"])
        self.screenshot("save-recovered.png")

    def test_world_selection_reveals_reported_structure_then_restores_skin_without_stepping(self):
        import server
        with mock.patch.object(server.secrets,'randbelow',side_effect=[1,851269741]):
            world, owner, app = self.setup_world()
        self.browser(world, owner)
        self.page.send("Page.navigate", {"url":self.base + f"/world?world={world}&hold=1"})
        self.wait('window.banjoRoom?.ready()', seconds=60)
        session = app.live.session.id
        before = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        self.page.evaluate('window.revealTarget=[...banjoRoom.world.bodies].find(([n,e])=>e.mechanicalModel!=="precise-rigid-v1")?.[0]')
        self.assertTrue(self.page.evaluate('!!window.revealTarget'), "fixture needs reported cell geometry")
        self.page.evaluate('(()=>{const r=banjoRoom,p=r.world.bodies.get(revealTarget).mesh.position;r.standAt(p.x+.3,p.y+.25,p.z+.35);r.lookAt(p.x,p.y,p.z)})()')
        self.page.evaluate('window.originalSkin=banjoRoom.world.bodies.get(revealTarget).mesh.material; banjoRoom.pick(revealTarget,"cells")')
        self.wait('banjoRoom.reveal()?.kind === "cells" && banjoRoom.reveal().amount > .95')
        # Read the actual GPU vertex buffer. Each native cell gets twelve
        # orthogonal edges centred on that cell, with no triangle diagonals.
        self.assertTrue(self.page.evaluate('(()=>{const r=banjoRoom,mesh=r.scene.getObjectByName("selection-structure-reveal").children[0],cells=r.reveal().cellCentres,a=mesh.geometry.attributes.position.array,h=r.world.cellSize/2;return a.length===cells.length*72 && cells.every((p,i)=>{const mean=[0,0,0];for(let k=0;k<72;k++) {const v=a[i*72+k];if(Math.abs(Math.abs(v-p[k%3])-h)>1e-6)return false;mean[k%3]+=v/24;}for(let k=0;k<72;k+=6)if([0,1,2].filter(j=>Math.abs(a[i*72+k+j]-a[i*72+k+3+j])>1e-6).length!==1)return false;return p.every((v,k)=>Math.abs(v-mean[k])<1e-6)})})()'))
        self.assertLess(self.page.evaluate('banjoRoom.reveal().skinOpacity'), .3)
        self.assertTrue(self.page.evaluate('banjoRoom.world.bodies.get(revealTarget).mesh.material === originalSkin'))
        self.assertIn("Tool dependent", self.page.evaluate('document.querySelector("#picked").textContent'))
        # Frame interpolation and movement carry the reveal with the same body.
        self.assertTrue(self.page.evaluate('(()=>{const r=banjoRoom,g=r.scene.getObjectByName("selection-structure-reveal"),m=r.world.bodies.get(revealTarget).mesh;return g.matrix.equals(m.matrixWorld)})()'))
        self.screenshot("world-cell-reveal.png")
        self.wait('banjoRoom.reveal() === null', seconds=6)
        self.assertTrue(self.page.evaluate('banjoRoom.world.bodies.get(revealTarget).mesh.material === originalSkin && !banjoRoom.scene.getObjectByName("selection-structure-reveal")'))
        self.page.evaluate('[...document.querySelectorAll("#picked button")].find(b=>b.textContent==="Show native cells").click()')
        self.wait('!!banjoRoom.reveal()')
        # The pinned card lives in the right rail, which starts folded
        # (dcd94bae); Details opens it, then its close button dismisses.
        self.open_rail()
        self.click('#pk-close'); self.wait('banjoRoom.reveal() === null && document.querySelector("#picked").hidden')
        # Switching selection disposes the old overlay rather than stacking it.
        self.page.evaluate('banjoRoom.pick(revealTarget); banjoRoom.pick("solar farm")')
        self.page.evaluate('(()=>{const r=banjoRoom,p=r.world.bodies.get("solar farm").mesh.position;r.standAt(p.x+2,p.y+2,p.z+3);r.lookAt(p.x,p.y,p.z)})()')
        self.assertEqual("solar farm", self.page.evaluate('banjoRoom.picked().name'))
        self.assertEqual(0, self.page.evaluate('banjoRoom.scene.children.filter(c=>c.name === "selection-structure-reveal").length'))
        # The solar farm in the native starter room is a precise assembly.
        self.assertIsNone(self.page.evaluate('banjoRoom.reveal()'))
        self.assertGreater(self.page.evaluate('document.querySelectorAll("#picked .pk-component-grid img").length'),0)
        self.assertIn("No cell fracture", self.page.evaluate('document.querySelector("#picked").textContent'))
        self.screenshot("world-part-reveal.png")
        self.page.evaluate('banjoRoom.pick(null)')
        after = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        for key in ("t", "machines", "bodies"):
            self.assertEqual(before[key], after[key], key + " changed during inspection")
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_ground_reveal_uses_native_layers_and_reduced_motion_and_escape_clear_it(self):
        import server
        with mock.patch.object(server.secrets,'randbelow',side_effect=[1,851269741]):
            world, owner, app = self.setup_world()
        self.browser(world, owner)
        self.page.send("Emulation.setEmulatedMedia", {"features":[{"name":"prefers-reduced-motion", "value":"reduce"}]})
        self.page.send("Page.navigate", {"url":self.base + f"/world?world={world}&hold=1"})
        self.wait('window.banjoRoom?.ready()', seconds=60)
        session = app.live.session.id
        before = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        # Normal cursor/pointer events: Alt+click inspects the native terrain
        # under the centre without executing an interaction action.
        self.page.evaluate('const r=banjoRoom,y=r.groundAt(0,0);r.standAt(0,y+2,2);r.lookAt(0,y,0)')
        point = self.page.evaluate('(()=>{const r=document.querySelector("#stage").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
        self.page.send("Input.dispatchMouseEvent", {"type":"mouseMoved", **point, "modifiers":1})
        self.wait('!!banjoRoom.world.groundAim')
        for event in ("mousePressed", "mouseReleased"):
            self.page.send("Input.dispatchMouseEvent", {"type":event, **point, "button":"left", "clickCount":1, "modifiers":1})
        self.wait('banjoRoom.reveal()?.kind === "layers" && banjoRoom.reveal().amount === 1')
        layers = self.page.evaluate('banjoRoom.reveal().layers')
        self.assertTrue(layers)
        self.assertTrue(self.page.evaluate('(()=>{const r=banjoRoom,b=r.reveal().layers.filter(b=>!b.hole),m=r.scene.getObjectByName("selection-structure-reveal").children,g=r.groundDrawn();return m.length===b.length && b.every((bed,i)=>{m[i].geometry.computeBoundingBox();const s=m[i].geometry.boundingBox.getSize(new r.THREE.Vector3());return Math.abs(s.y-bed.thick_m)<1e-5 && Math.abs(m[i].position.y-(bed.top_m-bed.thick_m/2))<1e-6 && Math.abs(s.x-g.dx)<1e-6})})()'))
        self.assertEqual(len(layers), self.page.evaluate('document.querySelectorAll("#picked .pk-bed").length'))
        # The bed-count row was replaced by a named "Ground layers" core log
        # (f978d1af); every reported bed is labelled in it.
        said = self.page.evaluate('document.querySelector("#picked").textContent')
        self.assertIn("Ground layers", said)
        for bed in layers: self.assertIn("dug out" if bed.get("hole") else bed["name"], said)
        self.assertNotIn("kg", self.page.evaluate('document.querySelector("#picked").textContent'))
        self.screenshot("world-ground-reveal.png")
        # Since 3e2b508d Esc switches explore/cursor mode and keeps the pin;
        # the pinned card's close button (in the Details rail) clears it.
        cursor = self.page.evaluate('document.querySelector("#cursor-mode").getAttribute("aria-pressed")')
        self.page.send("Input.dispatchKeyEvent", {"type":"keyDown", "code":"Escape", "key":"Escape"})
        self.page.send("Input.dispatchKeyEvent", {"type":"keyUp", "code":"Escape", "key":"Escape"})
        self.wait('document.querySelector("#cursor-mode").getAttribute("aria-pressed") !== ' + json.dumps(cursor))
        self.assertFalse(self.page.evaluate('document.querySelector("#picked").hidden'))
        self.open_rail()
        self.click('#pk-close')
        self.wait('banjoRoom.reveal() === null && document.querySelector("#picked").hidden')
        after = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        for key in ("t", "machines", "ground"):
            self.assertEqual(before.get(key), after.get(key), key + " changed during inspection")
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_material_cards_open_filtered_recipes_and_all_materials_restores_catalog(self):
        world, owner, app = self.setup_world()
        table = self.post("/api/workshop/candidates", {"kind":"table", "generation":0}, world)["candidates"][0]
        saved = self.post("/api/workshop/feedback", {"kind":"table", "design_id":table["design_id"],
            "parameters":table["parameters"], "component_overrides":table.get("component_overrides", {}),
            "save_design":True, "label":"Oak filter design"}, world)["design"]["design_id"]
        stock = self.post("/api/workshop/inventory", {}, world)
        self.browser(world, owner); self.navigate(world, "workshop=1&tab=inventory")
        self.wait('document.querySelectorAll("#ws-inv-stock .ws-tile").length > 0')
        self.assertTrue(self.page.evaluate('[...document.querySelectorAll("#ws-inv-stock .ws-tile")].every(c => !c.disabled && getComputedStyle(c).userSelect === "none" && c.querySelector(".ws-tile-count").parentElement === c && getComputedStyle(c.querySelector(".ws-tile-count")).position === "static")'))
        self.assertEqual(f'{next(r["mass_kg"] for r in stock["materials"] if r["material"] == "oak"):g} kg', self.page.evaluate('document.querySelector("#ws-inv-stock [data-resource=oak] .ws-tile-count").textContent'))
        self.assertIn('Personal',self.page.evaluate('document.querySelector("#ws-inv-stock [data-resource=oak]").textContent'))
        self.assertIn('Shared',self.page.evaluate('document.querySelector("#ws-inv-stock [data-resource=oak]").textContent'))
        self.screenshot("material-quantities.png")
        self.click('#ws-inv-stock [data-resource="oak"]')
        self.wait('new URLSearchParams(location.search).get("tab") === "recipes" && document.querySelectorAll("#ws-recipe-filter button").length > 1 && !!document.querySelector("#ws-rec-saved [data-recipe]")')
        self.assertEqual("oak", self.page.evaluate('new URLSearchParams(location.search).get("material")'))
        self.assertTrue(self.page.evaluate('[...document.querySelectorAll("#ws-pane-recipes [data-recipe]")].filter(c=>!c.hidden).every(c=>JSON.parse(c.dataset.materials).includes("oak"))'))
        self.assertTrue(self.page.evaluate(f'!!document.querySelector("[data-recipe=\\"{saved}\\"]:not([hidden])")'))
        total = self.page.evaluate('document.querySelectorAll("#ws-pane-recipes [data-recipe]").length')
        shown = self.page.evaluate('document.querySelectorAll("#ws-pane-recipes [data-recipe]:not([hidden])").length')
        self.assertGreater(shown, 0); self.assertLess(shown, total)
        self.assertIsNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
        self.screenshot("oak-recipes.png")
        self.page.send("Page.reload")
        self.wait('document.querySelector("#ws-recipe-filter [data-recipe-material=oak]")?.getAttribute("aria-pressed") === "true"')
        self.click('[data-recipe-material="glass"]')
        self.assertEqual("glass", self.page.evaluate('new URLSearchParams(location.search).get("material")'))
        self.assertTrue(self.page.evaluate('[...document.querySelectorAll("#ws-pane-recipes [data-recipe]:not([hidden])")].every(c=>JSON.parse(c.dataset.materials).includes("glass"))'))
        self.click('[data-recipe-material=""]')
        self.assertFalse(self.page.evaluate('new URLSearchParams(location.search).has("material")'))
        self.assertEqual(total, self.page.evaluate('document.querySelectorAll("#ws-pane-recipes [data-recipe]:not([hidden])").length'))
        self.assertFalse(self.page.evaluate('document.querySelector("#ws-rec-blocks-section").hidden'))
        self.page.send("Page.reload"); self.wait('document.querySelectorAll("#ws-recipe-filter button").length > 1')
        self.assertEqual("true", self.page.evaluate('document.querySelector("[data-recipe-material=\\"\\"]").getAttribute("aria-pressed")'))
        self.navigate(world, "workshop=1&tab=recipes&material=unavailable-material")
        self.wait('document.querySelector("#ws-recipe-filter-status")?.textContent.includes("No matches")')
        self.assertFalse(self.page.evaluate('document.querySelectorAll("#ws-pane-recipes [data-recipe]:not([hidden])").length'))
        self.click('[data-recipe-material=""]')
        self.assertEqual(total, self.page.evaluate('document.querySelectorAll("#ws-pane-recipes [data-recipe]:not([hidden])").length'))
        after = self.post("/api/workshop/inventory", {}, world)
        for key in ("materials", "goods", "carried"): self.assertEqual(stock[key], after[key])
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_inventory_shows_private_wallet_and_native_meters_without_spending_or_stepping(self):
        world, owner, app = self.setup_world()
        self.post("/api/workshop/market", {"action":"bank", "joules":200,
            "request_id":"inventory-meter-fixture"}, world)
        session = app.live.session.id
        self.post("/api/live/act", {"session":session, "op":"step", "dt":1/240, "n":1}, world)
        before = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        self.assertGreater(sum(p["power_w"] for p in before["machines"]["panels"]), 0)
        self.browser(world, owner); self.navigate(world, "workshop=1&tab=inventory")
        self.wait('!!document.querySelector("#ws-inv-energy").dataset.updated')
        def displayed():
            return self.page.evaluate('[...document.querySelectorAll(".ws-energy-card")].map(c => ({title:c.querySelector("h4").textContent,values:Object.fromEntries([...c.querySelectorAll(".ws-recipe-value")].map(v=>[v.querySelector("span").textContent,v.querySelector("b").textContent]))}))')
        cards = displayed()
        self.assertEqual("200 J", cards[0]["values"]["Spendable"])
        self.assertEqual("0 arrays", cards[0]["values"]["Auto bank"])
        self.assertEqual("0 J/s", cards[0]["values"]["Solar input"])
        solar = next(s for s in before["machines"]["stores"] if s["body"] == "solar farm")
        num = lambda text: float(text.split(" J")[0].replace(",", ""))
        self.assertAlmostEqual(solar["charge_j"], num(cards[1]["values"]["Stored"]), delta=.051)
        self.assertAlmostEqual(sum(p["power_w"] for p in before["machines"]["panels"] if p["store"]==solar["id"]), num(cards[1]["values"]["Generating now"]), delta=.051)
        self.assertEqual("Not metered", cards[2]["values"]["Goods rate"])
        self.assertEqual("0 J/s", cards[2]["values"]["Currency income"])
        self.assertFalse(self.page.evaluate('!!document.querySelector("#ws-pane-inventory [data-building-block], #ws-pane-inventory [data-lab-source], #ws-pane-inventory input")'))
        self.assertNotRegex(self.page.evaluate('document.querySelector("#ws-pane-inventory").textContent'), r'width_m|Saved designs|Building blocks')
        self.screenshot("inventory-energy.png")
        stamp = self.page.evaluate('document.querySelector("#ws-inv-energy").dataset.updated')
        self.wait('document.querySelector("#ws-inv-energy").dataset.updated !== ' + json.dumps(stamp), seconds=12)
        after = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        self.assertEqual(before["t"], after["t"])
        self.assertEqual(before["machines"], after["machines"])
        self.assertEqual(200, self.post("/api/workshop/market", {}, world)["balance_j"])
        other = self.join(world, "Other wallet")
        self.page.evaluate(f'localStorage.setItem("banjo.player.{world}", {json.dumps(other["token"])})')
        self.navigate(world, "workshop=1&tab=inventory")
        self.wait('!!document.querySelector("#ws-inv-energy").dataset.updated')
        self.assertEqual("0 J", displayed()[0]["values"]["Spendable"])
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_empty_lab_ignores_templates_memory_and_missing_inventory(self):
        world, owner, app = self.setup_world(); self.browser(world, owner)
        self.page.evaluate('localStorage.setItem("banjo.workshop.opened", JSON.stringify({kind:"cart"}))')
        self.navigate(world, "workshop=1&tab=lab&kind=table")
        self.assert_empty()
        self.assertEqual(["World", "Inventory", "Lab", "Skills", "Recipes", "Market", "Goals"],
            self.page.evaluate('[...document.querySelectorAll(".game-tabs [data-screen]")].map(e=>e.textContent)'))
        self.assertTrue(self.page.evaluate('document.querySelector(".ws-left").getBoundingClientRect().left >= document.querySelector("#workshop-stage").getBoundingClientRect().right - 1'))
        self.screenshot("empty.png")
        self.navigate(world, "workshop=1&tab=lab&carry=missing-item")
        # Empty geometry is shown before the asynchronous source lookup has
        # removed an invalid carried-item route. Wait for that completed state.
        self.wait('!location.search.includes("carry=")')
        self.assert_empty()
        self.assertFalse(self.page.evaluate('location.search.includes("carry=")'))
        self.page.send("Page.reload"); self.assert_empty()
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_saved_selection_and_world_tabs_preserve_player_and_clear_explicitly(self):
        world, owner, app = self.setup_world()
        # New worlds start with generated installations (starter machines and
        # their foundation pads, 23e48727). Selecting and editing a design must
        # leave that installed set exactly as it was.
        installs = json.loads(json.dumps(app.room.workshop_installs))
        source = self.post("/api/workshop/candidates", {"kind":"table", "generation":0}, world)
        candidate = source["candidates"][0]
        saved = self.post("/api/workshop/feedback", {"kind":"table", "generation":0,
            "design_id":candidate["design_id"], "parameters":candidate["parameters"],
            "component_overrides":candidate.get("component_overrides", {}), "save_design":True,
            "label":"My selected table"}, world)["design"]["design_id"]
        self.browser(world, owner); self.navigate(world, "workshop=1&tab=recipes")
        self.wait(f'!!document.querySelector("[data-lab-source=saved][data-item=\\"{saved}\\"]")')
        self.assertEqual(1, self.page.evaluate(f'document.querySelectorAll("[data-recipe=\\"{saved}\\"]").length'))
        self.assertTrue(self.page.evaluate(f'!!document.querySelector("[data-lab-source=saved][data-item=\\"{saved}\\"]").closest("#ws-rec-saved")'))
        self.click(f'[data-lab-source="saved"][data-item="{saved}"]')
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        self.assertEqual(saved, self.page.evaluate('new URLSearchParams(location.search).get("design")'))
        # Add a real component. A World round trip and reload must retain the
        # unsaved draft without installing it or spending any supplies.
        top=next(part for part in candidate['parts'] if part['name']=='top')
        at=[top['center_m'][0]+.1,top['center_m'][1]+top['size_m'][1]/2,top['center_m'][2]]
        self.page.evaluate('''(()=>{const select=document.querySelector('#ws-build-what');
            select.value='family:post';select.dispatchEvent(new Event('change',{bubbles:true}));
            document.querySelector('#ws-build-length').value='.3';
            document.querySelector('#ws-build-place').click();})()''')
        point=self.page.evaluate('document.querySelector("#workshop-stage").pagePointOf(%s)'%json.dumps(at))
        for event in ('mousePressed','mouseReleased'):
            self.page.send('Input.dispatchMouseEvent',{'type':event,'x':point[0],'y':point[1],'button':'left','clickCount':1})
        self.wait('document.querySelector("#ws-build-adjust")?.hidden===false')
        self.page.evaluate('document.querySelector("#ws-build-add").click()')
        count=len(candidate['parts'])+1
        self.wait(f'document.querySelector("#ws-part-count").textContent==="{count}"')
        self.wait('document.querySelector("#ws-lab-draft").textContent.includes("Draft saved in this browser")')
        self.assertEqual(installs, app.room.workshop_installs)
        self.assertFalse(app.room.fabrication_record['jobs'])
        self.screenshot("selected.png")
        self.click('.ws-bar-link')
        self.wait('!!window.banjoRoom?.status().ready')
        self.assertEqual(owner["id"], self.page.evaluate('window.banjoRoom.status().player_id'))
        self.assertEqual(7, self.page.evaluate('document.querySelectorAll(".game-tabs [data-screen]").length'))
        self.click('.game-tabs [data-screen="skills"]')
        self.wait('document.querySelector("#ws-pane-skills")?.hidden === false && !!document.querySelector("#ws-tree button")')
        self.click('.game-tabs [data-screen="lab"]')
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        self.wait(f'document.querySelector("#ws-part-count").textContent==="{count}"')
        self.assertIn('Draft restored',self.page.evaluate('document.querySelector("#ws-lab-draft").textContent'))
        self.page.send("Page.reload"); self.wait(f'document.querySelector("#ws-part-count")?.textContent==="{count}"')
        self.click('#ws-draft-save')
        self.wait('document.querySelector("#ws-lab-draft").textContent.includes("Saved to Recipes")')
        selected=self.page.evaluate('new URLSearchParams(location.search).get("design")')
        stored=self.post('/api/workshop/open',{'saved_design_id':selected},world)
        self.assertEqual(count,len(stored['candidates'][0]['parts']))
        self.assertEqual(installs, app.room.workshop_installs)
        self.assertFalse(self.page.evaluate('Object.keys(localStorage).some(k=>k.startsWith("banjo.lab-draft."))'))
        self.click("#ws-clear-lab"); self.assert_empty()
        self.page.send("Page.reload"); self.assert_empty()
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_recipes_building_blocks_create_saved_designs_without_spending_stock(self):
        world, owner, app = self.setup_world(); self.browser(world, owner)
        before = self.post("/api/workshop/inventory", {}, world)
        self.navigate(world, "workshop=1&tab=recipes")
        self.wait('document.querySelectorAll("[data-building-block]").length === 16')
        self.assertNotRegex(self.page.evaluate('document.querySelector("#ws-pane-recipes").textContent'),
                            r'width_m|height_m|depth_m|splay_deg|lean_x|component_overrides')
        self.assertEqual(["Frames & supports", "Surfaces & panels", "Wheels & axles", "Machine housings"],
            self.page.evaluate('[...document.querySelectorAll("#ws-rec-blocks h4")].map(e=>e.textContent)'))
        self.assertEqual(16, self.page.evaluate('document.querySelectorAll("#ws-rec-blocks canvas[data-preview=ready]").length'))
        self.assertIn("AI design is not connected", self.page.evaluate('document.querySelector("#ws-rec-ai-help").textContent'))
        self.assertIsNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
        # Every offered block really starts a source design; none relies on an
        # invented machine behavior or physical inventory to appear on screen.
        families = self.page.evaluate('[...document.querySelectorAll("[data-building-block]")].map(e=>e.dataset.buildingBlock)')
        ids = set()
        for family in families:
            previous = self.page.evaluate('new URLSearchParams(location.search).get("library")')
            self.click(f'[data-building-block="{family}"]')
            self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0 && document.querySelector(".ws-viewport").hidden === false && new URLSearchParams(location.search).has("library") && new URLSearchParams(location.search).get("library") !== ' + json.dumps(previous))
            ids.add(self.page.evaluate('new URLSearchParams(location.search).get("library")'))
            self.assertEqual("1", self.page.evaluate('document.querySelector("#ws-part-count").textContent'))
            self.assertFalse(self.page.evaluate('document.querySelector("#ws-component-chat-text").disabled'))
            self.click('.game-tabs [data-screen="recipes"]')
            self.wait('document.querySelectorAll("[data-building-block]").length === 16')
        self.assertEqual(16, len(ids))
        after = self.post("/api/workshop/inventory", {}, world)
        for key in ("carried", "materials", "goods", "in_world"): self.assertEqual(before[key], after[key])
        self.assertEqual(16, len(after["designs"]))
        self.wait('document.querySelectorAll("#ws-rec-saved canvas[data-preview=ready]").length === 16')
        self.screenshot("inventory-categories.png")
        self.page.evaluate('document.querySelector("#ws-pane-recipes").scrollTop = 0')
        self.screenshot("inventory-overview.png")
        # Saved component cards create a new editable design, leaving the
        # reusable original intact and keeping the selected item on reload.
        table = self.post("/api/workshop/candidates", {"kind":"table", "generation":0}, world)["candidates"][0]
        component = self.post("/api/workshop/library", {"action":"save_component", "kind":"table",
            "parameters":table["parameters"], "component_overrides":table.get("component_overrides", {}),
            "part_name":"top", "name":"Reusable tabletop"}, world)["library_item"]
        self.navigate(world, "workshop=1&tab=recipes")
        self.wait(f'!!document.querySelector("[data-lab-component=\\"{component["item_id"]}\\"]")')
        self.click(f'[data-lab-component="{component["item_id"]}"]')
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        selected = self.page.evaluate('new URLSearchParams(location.search).get("library")')
        self.page.send("Page.reload"); self.wait('document.querySelector("#workshop-stage")?.visibleGeometry()?.meshes > 0')
        self.assertEqual(selected, self.page.evaluate('new URLSearchParams(location.search).get("library")'))
        unchanged = self.post("/api/workshop/library", {"action":"load", "item_id":component["item_id"]}, world)["library_item"]
        self.assertEqual(component["payload"], unchanged["payload"])
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_recipe_make_reports_world_output_and_adds_independent_copies(self):
        # The card's direct Make serves worlds without a configured workbench
        # process. Fresh worlds are paid (b3051290): their Make opens the Lab's
        # reviewed workbench flow, covered by fabrication_remake_tests.
        world, owner, app = self.setup_world(legacy_process=True); self.browser(world, owner)
        before = self.post("/api/workshop/inventory", {}, world)
        # Generated starter installations are already present (23e48727).
        installed = {r["root_body"] for r in app.room.workshop_installs}
        self.navigate(world, "workshop=1&tab=recipes")
        card = '[data-recipe="stool:Camp stool"]'
        self.wait(f'!!document.querySelector({json.dumps(card)})')
        self.wait('document.querySelectorAll("#ws-recipes-templates canvas[data-preview=ready]").length >= 10')
        self.assertIsNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
        self.assertIn("SkillNone required", self.page.evaluate(f'document.querySelector({json.dumps(card)}).textContent'))
        bodies = set()
        for _ in range(2):
            self.click(card + ' .ws-recipe-acts button')
            self.wait(f'document.querySelector({json.dumps(card + " .ws-recipe-result a")})?.dataset.madeBody && document.querySelector({json.dumps(card + " .ws-recipe-acts button")})?.disabled === false')
            bodies.add(self.page.evaluate(f'document.querySelector({json.dumps(card + " .ws-recipe-result a")}).dataset.madeBody'))
            self.assertIn("tab=recipes", self.page.evaluate('location.search'))
            self.assertIsNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
        self.assertEqual(2, len(bodies), "Make replaced the previous copy")
        after = self.post("/api/workshop/inventory", {}, world)
        self.assertEqual(before["carried"], after["carried"])
        oak = lambda rows: next(r["mass_kg"] for r in rows if r["material"] == "oak")
        self.assertAlmostEqual(2 * 2.5088, oak(before["materials"]) - oak(after["materials"]), places=4)
        made = [r for r in app.room.workshop_installs if r["root_body"] not in installed]
        self.assertEqual(bodies, {r["root_body"] for r in made})
        self.assertEqual(2, len(made))
        self.assertTrue(all(r.get("owner_id") == owner["id"] for r in made))
        self.screenshot("recipes-made.png")
        self.click(card + ' .ws-recipe-result a')
        self.wait('location.pathname === "/world" && !new URLSearchParams(location.search).has("workshop")')
        self.assertEqual(world, self.page.evaluate('new URLSearchParams(location.search).get("world")'))
        self.wait('window.banjoRoom?.status().ready && window.banjoRoom.world.bodies.has(new URLSearchParams(location.search).get("focus"))')
        self.assertEqual(owner["id"], self.page.evaluate('window.banjoRoom.status().player_id'))
        self.assertTrue(self.page.evaluate('(()=>{const r=window.banjoRoom,c=r.camera,m=r.world.bodies.get(new URLSearchParams(location.search).get("focus")).mesh,p=m.getWorldPosition(c.position.clone()).sub(c.position).normalize();return c.getWorldDirection(c.position.clone()).dot(p) > .99})()'))
        self.screenshot("recipe-world.png")
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_recipe_make_shows_a_stock_race_refusal_on_the_card(self):
        # Direct card Make, as above: a world without a configured process.
        world, owner, app = self.setup_world(legacy_process=True); self.browser(world, owner)
        installs = json.loads(json.dumps(app.room.workshop_installs))
        table = self.post("/api/workshop/candidates", {"kind":"table", "generation":0}, world)["candidates"][0]
        saved = self.post("/api/workshop/feedback", {"kind":"table", "design_id":table["design_id"],
            "parameters":table["parameters"], "component_overrides":table.get("component_overrides", {}),
            "save_design":True, "label":"Keep my Lab item"}, world)["design"]["design_id"]
        self.navigate(world, "workshop=1&tab=recipes")
        selected = f'[data-lab-source="saved"][data-item="{saved}"]'
        self.wait(f'!!document.querySelector({json.dumps(selected)})'); self.click(selected)
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        meshes = self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry().meshes')
        self.click('.game-tabs [data-screen="recipes"]')
        card = '[data-recipe="stool:Camp stool"]'
        self.wait(f'document.querySelector({json.dumps(card + " .ws-recipe-acts button")})?.disabled === false')
        # Another actor can spend shared stock after this page displayed it.
        with guests.server.workshop_library._connect(app) as db:
            db.execute("UPDATE workshop_material_rack SET mass_kg=0 WHERE material='oak'")
        self.click(card + ' .ws-recipe-acts button')
        self.wait(f'document.querySelector({json.dumps(card + " .ws-recipe-result")})?.dataset.bad === "yes" && document.querySelector({json.dumps(card + " .ws-recipe-acts button")})?.disabled === true')
        self.assertIn("Nothing has been spent", self.page.evaluate(f'document.querySelector({json.dumps(card + " .ws-recipe-result")}).textContent'))
        self.assertIn("tab=recipes", self.page.evaluate('location.search'))
        self.assertEqual(installs, app.room.workshop_installs)
        self.assertEqual(saved, self.page.evaluate('new URLSearchParams(location.search).get("design")'))
        self.assertEqual(meshes, self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry().meshes'))
        self.screenshot("recipes-short.png")

    def test_carried_item_requires_own_inventory_and_lab_leaves_it_unchanged(self):
        # This fixture authors its carried stool directly; it tests ownership
        # and Lab isolation, not the paid manufacturing supply pipeline.
        world, owner, app = self.setup_world(legacy_process=True)
        # The active opening chain is now the personal field pick (f15cd75b);
        # the Camp stool fixture is the first-camp chain's admitted recipe.
        recipe = self.post("/api/workshop/goals", {"chain":"first-camp-v1"}, world)["recipe"]
        context = self.post("/api/world/workshop/context", {}, world)
        preview = self.post("/api/world/workshop/preview", {"session":context["session"], "scene":context["scene"],
            "candidate":recipe, "mode":"authoring", "position_m":[3, 0]}, world)
        built = self.post("/api/world/workshop/commit", {"session":preview["session"], "scene":preview["scene"],
            "preview_id":preview["preview_id"], "request_id":"navigation-fixture"}, world)
        taken = self.post("/api/world/inventory", {"session":built["session"], "op":"take",
            "item":built["root_body"], "request":"navigation-take"}, world)
        self.assertTrue(taken["ok"], taken)
        carried = self.post("/api/workshop/inventory", {}, world)["carried"][0]
        before = self.post("/api/world/inventory/shown", {"session":built["session"]}, world)["record"]
        self.browser(world, owner); self.navigate(world, "workshop=1&tab=inventory")
        self.wait('document.querySelector(".ws-product-card .ws-tile-name")?.textContent === "Camp stool" && document.querySelector(".ws-product-card canvas")?.dataset.preview === "ready"')
        self.assertFalse(self.page.evaluate('document.querySelector(".ws-product-debug").open'))
        self.assertIn('Hold / place in World',self.page.evaluate('document.querySelector(".ws-product-card").textContent'))
        self.assertEqual('2.51 kg',self.page.evaluate('document.querySelector(".ws-product-card .ws-tile-count").textContent'))
        self.wait('!!document.querySelector("#ws-inv-energy").dataset.updated')
        self.screenshot('named-product.png')
        self.wait('!!document.querySelector(".ws-tile:not([disabled])")')
        self.click(".ws-tile:not([disabled])")
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        self.assertEqual(str(carried["id"]), self.page.evaluate('new URLSearchParams(location.search).get("carry")'))
        self.assertEqual("5", self.page.evaluate('document.querySelector("#ws-part-count").textContent'))
        self.assertEqual("2.509 kg", self.page.evaluate('document.querySelector("#ws-mass").textContent'))
        self.click('#ws-lab-components [data-component]')
        component=self.page.evaluate('document.querySelector("#ws-component-info").dataset.component')
        self.page.evaluate('(()=>{const e=document.querySelector("#ws-part-material");e.value="iron";e.dispatchEvent(new Event("change",{bubbles:true}))})()')
        self.wait('document.querySelector("#ws-lab-draft").textContent.includes("Draft saved in this browser")')
        self.page.send('Page.reload')
        self.wait('document.querySelector("#ws-lab-draft")?.textContent.includes("Draft restored")')
        self.assertIn('iron',self.page.evaluate(f'document.querySelector("[data-component={component}]").textContent'))
        self.click("#ws-clear-lab"); self.assert_empty()
        after = self.post("/api/world/inventory/shown", {"session":built["session"]}, world)["record"]
        self.assertEqual(before, after)
        equipped = self.post("/api/world/inventory", {"session":built["session"], "op":"equip",
            "item":carried["id"], "request":"navigation-equip", "person":{"standing_m":[3, 0, 0],
            "eyes_m":[3, 1.62, 0], "facing":[0, 0, -1], "look_direction":[0, 0, -1]}}, world)
        self.assertTrue(equipped["ok"], equipped)
        hand_before = self.post("/api/world/inventory/shown", {"session":built["session"]}, world)["record"]
        self.navigate(world, "workshop=1&tab=inventory")
        self.wait('!!document.querySelector(".ws-tile:not([disabled])")')
        self.click(".ws-tile:not([disabled])")
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        self.click("#ws-clear-lab"); self.assert_empty()
        self.assertEqual(hand_before, self.post("/api/world/inventory/shown", {"session":built["session"]}, world)["record"])
        other = self.join(world, "Other guest")
        self.page.evaluate(f'localStorage.setItem("banjo.player.{world}", {json.dumps(other["token"])})')
        self.navigate(world, "workshop=1&tab=lab&carry=" + str(carried["id"]))
        self.assert_empty()


if __name__ == "__main__": unittest.main()
