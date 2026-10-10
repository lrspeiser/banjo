"""Opening-goal playthrough over real HTTP + native simulation, no free stock.

The bounded agent chooses its next action from observed goals, market quotes
and refusals. This is a reproducible planner, not an LLM-success judgement.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
import time
import unittest
import urllib.error
import uuid
from types import SimpleNamespace
from unittest import mock
import tempfile

def create_world(client,body):
    try:return client.post('/api/worlds',body)
    except urllib.error.HTTPError as failure:
        raise AssertionError(failure.read().decode()) from failure

def make_paid(client,world,player,candidate,position,ident):
    context=client.post('/api/world/workshop/context',{},world,player)
    common={k:context[k] for k in ('session','scene')}
    def call(path,body,world_id,player_token):
        try:reply=client.post(path,body,world_id,player_token)
        except urllib.error.HTTPError as failure:
            raise AssertionError(failure.read().decode()) from failure
        if reply.get('session'):common['session']=reply['session']
        return reply
    plan=call('/api/world/fabrication/plan_make',{**common,'candidate':candidate},world,player)
    for material,kg in plan['missing_materials_kg'].items():
        if kg<=1e-10:continue
        funding=call('/api/world/fabrication/state',common,world,player)
        source=next(s for s in funding['stock_sources'] if s['pool']=='personal' and s['material']==material)
        if source['mass_kg']<kg:raise AssertionError('Personal inventory cannot cover '+material)
        call('/api/world/fabrication/fund_stock',{**common,'material':material,'mass_kg':kg,'pool':'personal',
            'rack_hash':source['rack_hash'],'revision':funding['state']['revision'],'request_id':ident+'-stock-'+material},world,player)
    funding=call('/api/world/fabrication/state',common,world,player)
    source=next(s for s in funding['energy_sources'] if s['body']=='solar farm')
    power=min(source['max_power_w'],funding['state']['config']['power_w'])
    call('/api/world/fabrication/connect_energy',{**common,'store':source['id'],'store_hash':source['store_hash'],
        'power_w':power,'revision':funding['state']['revision'],'request_id':ident+'-connect'},world,player)
    # Energy arrives at the connected power, so wait as long as it takes
    # rather than assuming one second covers any build.
    seconds=max(1,math.ceil(max(0,plan['quote']['supply_required_j']-funding['state']['energy_j'])/power))
    while seconds:
        step=min(10,seconds);call('/api/world/fabrication/wait',{**common,'seconds':step},world,player);seconds-=step
    funding=call('/api/world/fabrication/state',common,world,player)
    source=next(s for s in funding['energy_sources'] if s['connected'])
    need=max(0,plan['quote']['supply_required_j']-funding['state']['energy_j'])
    if need:
        call('/api/world/fabrication/fund_energy',{**common,'store_hash':source['store_hash'],'joules':need,
            'revision':funding['state']['revision'],'request_id':ident+'-energy'},world,player)
    funding=call('/api/world/fabrication/state',common,world,player)
    started=call('/api/world/fabrication/start_make',{**common,'plan_id':plan['plan_id'],
        'revision':funding['state']['revision'],'request_id':ident},world,player)
    remaining=max(1,math.ceil(plan['quote']['minimum_duration_s']))
    while remaining:
        seconds=min(10,remaining)
        call('/api/world/fabrication/wait',{**common,'seconds':seconds},world,player);remaining-=seconds
    # A list of spots is tried in order, as a player moves on from a spot the
    # preview refuses (for instance one where the thing would not stand).
    spots=position if position and isinstance(position[0],(list,tuple)) else [position]
    for spot in spots:
        try:
            preview=call('/api/world/fabrication/preview',{**common,'job_id':ident,'position_m':list(spot)},world,player)
            break
        except AssertionError as refused:
            if spot is spots[-1] or 'would not stand' not in str(refused):raise
    before=call('/api/world/inventory/shown',{'session':common['session']},world,player)
    built=call('/api/world/fabrication/commit',{**common,'job_id':ident,'preview_id':preview['preview_id'],
        'request_id':ident+'-place'},world,player)
    after=call('/api/world/inventory/shown',{'session':built['session']},world,player)
    if before['record']!=after['record']:raise AssertionError('Placement changed the player bag')
    return built

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "playground"), str(ROOT)]
import world_hub_tests as hub
import qa_browser
import starter_goals
import room_store


def play_first_camp(client, world, player):
    """An agent reads server evidence, then executes only normal player APIs."""
    trace = []
    for _ in range(32):
        goals = client.post("/api/workshop/goals", {"chain":starter_goals.CHAIN}, world, player)
        step = goals["next_goal"]
        if step is None:
            return {"complete": True, "trace": trace, "goals": goals}
        key = uuid.uuid4().hex
        if step == "bank-solar":
            reply = client.post("/api/workshop/market", {"action": "bank", "joules": 500,
                                                       "request_id": key}, world, player)
        elif step == "stock-iron":
            market = client.post("/api/workshop/market", {}, world, player)
            iron = next(o for o in market["offers"] if o["id"] == "iron-stock")
            if market["balance_j"] < iron["price_j"]:
                reply = client.post("/api/workshop/market", {"action": "bank", "joules": 500,
                                                           "request_id": key}, world, player)
            else:
                if not iron["remaining"]:
                    raise AssertionError("Iron sold out; goal awaits trader restock")
                reply = client.post("/api/workshop/market", {"action": "buy", "item_id": iron["id"],
                    "quoted_price_j": iron["price_j"], "request_id": key}, world, player)
        elif step == "build-camp":
            reply=make_paid(client,world,player,goals['recipe'],[[3,0],[3.5,2.5],[3.5,-3.],[2,0],[3,1],[3,-1]],key)
            if not reply["native_precise_geometry_verified"] or not reply["resources_charged"]:
                raise AssertionError("Build did not pass native admission and resource debit")
        elif step == "carry-camp":
            reply = client.post("/api/world/inventory", {"session": goals["session"], "op": "take",
                "item": goals["camp_body"], "request": key}, world, player)
            if not reply["ok"]:
                raise AssertionError(reply)
        else:
            raise AssertionError(f"No supported action for {step}")
        trace.append({"goal": step, "request_id": key,
                      "balance_j": reply.get("balance_j"), "status": reply.get("status"),
                      "mass_kg": reply.get("mass_kg"), "ok": reply.get("ok")})
    raise AssertionError("Opening goals exceeded the bounded 32-action budget")


@unittest.skipUnless(hub.RUNNER.is_file() and hub.ENGINE.is_file(), "native world engine not built")
class StarterGoals(unittest.TestCase):
    setUp, tearDown = hub.NamedWorlds.setUp, hub.NamedWorlds.tearDown
    start, stop = hub.NamedWorlds.start, hub.NamedWorlds.stop
    get, post, join = hub.NamedWorlds.get, hub.NamedWorlds.post, hub.NamedWorlds.join

    def test_two_players_complete_from_earned_energy_and_keep_progress_after_restart(self):
        world = create_world(self, {"name": "First camp"})["id"]
        alice, bob = self.join(world, "Alice"), self.join(world, "Bob")
        self.players = {world: alice}
        opened = self.post("/api/world/open", {}, world)
        source = next(s for s in opened["machines"]["stores"] if s["body"] == "solar farm")
        result = play_first_camp(self, world, alice["token"])
        self.assertTrue(result["complete"])
        self.assertAlmostEqual(3.931065, result["goals"]["recipe_mass_kg"])
        # Only purchased personal stock is used; the communal rack is intact.
        rack = self.post("/api/workshop/inventory", {}, world)
        iron = next(r for r in rack["materials"] if r["material"] == "iron")
        # The Inventory API rounds rack quantities to four decimal places.
        self.assertEqual(round(4.-3.931065,4), iron["personal_kg"])
        self.assertAlmostEqual(6.2, iron["shared_kg"])
        bob_view = self.post("/api/workshop/goals", {"chain":starter_goals.CHAIN}, world, bob["token"])
        self.assertEqual("bank-solar", bob_view["next_goal"])
        self.assertTrue(all(not g["complete"] for g in bob_view["goals"]))
        second = play_first_camp(self, world, bob["token"])
        self.assertTrue(second["complete"])
        self.assertNotEqual(result["goals"]["camp_body"], second["goals"]["camp_body"])
        for player,completed in ((alice,result),(bob,second)):
            product=self.post('/api/workshop/inventory',{},world,player['token'])['carried'][0]
            self.assertEqual('Camp stool',product['label'])
            self.assertEqual(completed['goals']['camp_body'],product['name'])
            self.assertAlmostEqual(3.931065,product['kg'],places=4)
        # Both guests' packed precise assemblies must remain byte-for-byte
        # intact while another recipe is admitted into the shared scene.
        room_path=Path(self.temp.name)/"rooms"/"worlds"/world/"rooms"/"new-game.json"
        before=json.loads(room_path.read_text())
        bench=starter_goals.recipe(); bench["kind"]="bench"; bench["design_id"]="packed-bench-regression"
        bench["parameters"].update(width_m=.48,height_m=.3)
        # Buy the additional real stock for the larger third product.
        self.post('/api/workshop/market',{'action':'bank','joules':500,'request_id':'packed-bench-bank'},world)
        for index in range(10):
            market=self.post('/api/workshop/market',{},world)
            iron=next(o for o in market['offers'] if o['id']=='iron-stock')
            bank_index=0
            while market['balance_j']<iron['price_j']:
                self.post('/api/workshop/market',{'action':'bank','joules':500,
                    'request_id':f'packed-bench-extra-bank-{index}-{bank_index}'},world)
                bank_index+=1
                market=self.post('/api/workshop/market',{},world)
                iron=next(o for o in market['offers'] if o['id']=='iron-stock')
            self.post('/api/workshop/market',{'action':'buy','item_id':iron['id'],'quoted_price_j':iron['price_j'],
                'request_id':f'packed-bench-iron-{index}'},world)
        before=json.loads(room_path.read_text())
        built=make_paid(self,world,alice['token'],bench,[[4.5,0],[3,0],[3.5,2.5],[3.5,-3.],[2,0],[3,1],[3,-1]],'multi-packed-bench')
        after=json.loads(room_path.read_text())
        self.assertEqual(before["players"],after["players"])
        by_name={b["name"]:b for b in after["world"]["bodies"]}
        for b in before["world"]["bodies"]:
            if not b.get('parked'):continue
            self.assertEqual(b,by_name[b["name"]],"staging changed existing body state")
        for body in (result["goals"]["camp_body"],second["goals"]["camp_body"]):
            self.assertTrue(by_name[body]["parked"])
        import hashlib
        digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
        parked=[b for b in before['world']['bodies'] if b.get('parked')]
        report={'schema':'banjo.product-presentation-acceptance.v2','players':2,
            'native_dt_s':1/240,'scene_cell_m':.05,
            'parked_bodies_sha256_before':digest(parked),
            'parked_bodies_sha256_after':digest([by_name[b['name']] for b in parked]),
            'boundary':'Parked products retain exact state; unparked bodies advance during funded native work.',
            'player_records_unchanged':before['players']==after['players'],
            'products':[{'label':'Camp stool','native_body':body,
                         'parked_mass_kg':by_name[body]['parked']['mass_kg']}
                        for body in (result['goals']['camp_body'],second['goals']['camp_body'])]}
        self.assertGreater(built["mass_kg"],result["goals"]["recipe_mass_kg"])
        native = self.post("/api/world/open", {}, world)
        charge = next(s["charge_j"] for s in native["machines"]["stores"] if s["id"] == source["id"])
        process=self.post('/api/world/fabrication/state',{'session':native['session'],'scene':'new-game'},world)['state']
        self.assertEqual(3,len(process['jobs']))
        self.assertTrue(all(j['status']=='installed' for j in process['jobs'].values()))
        self.assertGreater(process['audit']['native_energy_received_j'],0)
        # Another player's recipe cannot be reported as my build by name alone.
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/workshop/goals", {"complete": True}, world)
        self.stop(); self.start()
        for player in (alice, bob):
            self.post("/api/world/player/join", {"token": player["token"]}, world)
            self.post("/api/world/open", {}, world, player["token"])
            restored = self.post("/api/workshop/goals", {"chain":starter_goals.CHAIN}, world, player["token"])
            self.assertTrue(restored["complete"])
            bag = self.post("/api/world/inventory/shown", {"session": restored["session"]}, world, player["token"])
            self.assertIn(restored["camp_body"], bag["record"]["stowed"])
            self.assertEqual('Camp stool',next(x for x in bag['stowed'] if x and x['name']==restored['camp_body'])['label'])
            self.assertEqual('Camp stool',bag['labels'][restored['camp_body']])
        report['both_names_and_bags_retained_after_restart']=True
        output=ROOT/'build/product-labels';output.mkdir(parents=True,exist_ok=True)
        (output/'acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')

    def test_wrong_geometry_or_another_builders_receipt_does_not_earn_goal(self):
        world = create_world(self, {"name": "Evidence"})["id"]
        alice = self.join(world, "Alice"); self.players = {world: alice}
        self.post("/api/world/open", {}, world)
        context = self.post("/api/world/workshop/context", {}, world)
        candidate = starter_goals.recipe()
        candidate["parameters"]["width_m"] = .3
        self.post('/api/workshop/market',{'action':'bank','joules':500,'request_id':'wrong-stool-bank'},world)
        for index in range(5):
            market=self.post('/api/workshop/market',{},world)
            iron=next(o for o in market['offers'] if o['id']=='iron-stock')
            bank_index=0
            while market['balance_j']<iron['price_j']:
                self.post('/api/workshop/market',{'action':'bank','joules':500,
                    'request_id':f'wrong-stool-bank-{index}-{bank_index}'},world)
                bank_index+=1
                market=self.post('/api/workshop/market',{},world)
                iron=next(o for o in market['offers'] if o['id']=='iron-stock')
            try:
                self.post('/api/workshop/market',{'action':'buy','item_id':iron['id'],'quoted_price_j':iron['price_j'],
                    'request_id':f'wrong-stool-iron-{index}'},world)
            except urllib.error.HTTPError as failure:
                raise AssertionError(failure.read().decode()) from failure
        # The world's terrain and goods are drawn afresh for every game, and a
        # spot one draw leaves flat another leaves on a slope or a heap, where
        # the 0.3 m stool is refused ("it tipped 170 degrees"). A player moves
        # on from that spot; so does this, as the packed bench above does.
        make_paid(self,world,alice['token'],candidate,[[3,0],[4.5,0],[3.5,2.5],[3.5,-3.],[2,0],[3,1],[3,-1]],
                  'wrong-stool-geometry')
        self.assertFalse(self.post("/api/workshop/goals", {"chain":starter_goals.CHAIN}, world)["goals"][2]["complete"])

    def test_browser_completes_goals_in_market_recipes_and_world(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get("BANJO_BROWSER_TESTS") == "required": self.fail("Chrome is required")
            self.skipTest("Chrome not installed")
        world = create_world(self, {"name": "Browser camp"})["id"]
        chrome = qa_browser.Chrome(1280, 800); self.addCleanup(chrome.close)
        page = chrome.page; page.send("Page.enable"); page.send("Runtime.enable")
        def wait_for(expression):
            until = time.monotonic() + 30
            while time.monotonic() < until:
                try:
                    if page.evaluate(expression): return
                except (RuntimeError, TimeoutError): pass
                time.sleep(.15)
            self.fail(f"Browser did not reach {expression}; status=" + str(page.evaluate(
                'document.body.innerText.slice(-2200)')))
        def click(selector):
            pick=f'[...document.querySelectorAll({json.dumps(selector)})].find(e=>e.offsetParent!==null)'
            wait_for(f'!!({pick}) && !({pick}).disabled')
            page.evaluate(f'({pick}).scrollIntoView({{block:"center"}})')
            wait_for(f'(()=>{{const e={pick},r=e.getBoundingClientRect(),h=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !!h&&(h===e||e.contains(h))}})()')
            point=page.evaluate(f'(()=>{{const e={pick},r=e.getBoundingClientRect(),h=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {{x:r.x+r.width/2,y:r.y+r.height/2,reachable:!!h&&(h===e||e.contains(h))}}}})()')
            self.assertTrue(point.pop('reachable'),'Click target must be reachable')
            for event in ("mousePressed", "mouseReleased"):
                page.send("Input.dispatchMouseEvent", {"type":event, **point, "button":"left", "clickCount":1})
        def screenshot(name):
            import base64
            out=ROOT / "build" / "starter-goals"; out.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(base64.b64decode(page.send("Page.captureScreenshot")["data"]))
        page.send("Page.navigate", {"url":self.base + f"/world?world={world}"})
        wait_for('window.banjoRoom?.status().ready')
        self.assertIn('Ask about energy',page.evaluate('document.querySelector("#ask-text").placeholder'))
        player=page.evaluate(f'localStorage.getItem("banjo.player.{world}")')
        click('.game-tabs [data-screen="progress"]')
        wait_for('!!document.querySelector("[data-goal=get-tool-metal]")')
        click('#ws-goal-chapters > summary')
        click('[aria-label="Goal chapters"] button:last-child')
        wait_for('!!document.querySelector("[data-goal-go=bank-solar]")')
        self.assertEqual(0, page.evaluate('document.querySelectorAll("[data-goal-action],[data-goal-bank]").length'))
        self.assertIn("In Inventory", page.evaluate('document.querySelector("[data-goal=bank-solar] .ws-goal-how").textContent'))
        self.assertTrue(page.evaluate('document.querySelector("[data-goal=bank-solar] details").open'))
        screenshot("guide.png")
        before=self.post("/api/workshop/goals", {"chain":starter_goals.CHAIN}, world, player)
        click('[data-goal-go="bank-solar"]')
        wait_for('document.querySelector("#ws-market-bank")?.textContent === "Bank 500 J · Shared farm"')
        navigated=self.post("/api/workshop/goals", {"chain":starter_goals.CHAIN}, world, player)
        self.assertEqual(before["balance_j"], navigated["balance_j"])
        self.assertEqual(before["goals"], navigated["goals"], "A Goals link completed a goal")
        click('#ws-market-bank')
        wait_for('document.querySelector("#ws-market-balance").textContent === "500 J"')
        click('.game-tabs [data-screen="progress"]')
        wait_for('document.querySelector("[data-goal=bank-solar]")?.dataset.complete === "true"')
        click('[data-goal-go="stock-iron"]')
        wait_for('document.querySelector("#ws-market-bank")?.textContent === "Bank 500 J · Shared farm"')
        # Real bank transactions fund the four dynamically quoted iron lots.
        click('#ws-market-bank')
        wait_for('document.querySelector("#ws-market-balance").textContent === "1,000 J"')
        for count in range(4):
            while page.evaluate('document.querySelector("[data-market-item=iron-stock] button").disabled'):
                click("#ws-market-bank")
                wait_for('!document.querySelector("#ws-market-bank").disabled')
            click('[data-market-item="iron-stock"] button')
            # Orders by their "<price> J · <time>" line: with none yet, the list
            # holds one "No purchases yet." item, which counted as the first.
            wait_for('[...document.querySelectorAll("#ws-market-orders > li")]'
                     f'.filter(li => li.textContent.includes(" J · ")).length === {count+1}')
            wait_for('!document.querySelector("#ws-market-bank").disabled')
        click('.game-tabs [data-screen="progress"]')
        wait_for('document.querySelector("[data-goal=stock-iron]")?.dataset.complete === "true"')
        # An unrelated material filter must not hide the guided iron recipe.
        page.evaluate('(()=>{const u=new URL(location.href);u.searchParams.set("material","glass");window.history.replaceState(null,"",u)})()')
        click('[data-goal-go="build-camp"]')
        self.assertFalse(page.evaluate('new URLSearchParams(location.search).has("material")'))
        camp_selector = '[data-recipe="stool:Camp stool"]'
        wait_for(f'!!document.querySelector({json.dumps(camp_selector + ".ws-goal-target")})')
        click('[data-recipe="stool:Camp stool"] .ws-recipe-acts button')
        # The separate transfers are folded away under "Supply details" since
        # 3544fd2b; one "Prepare supplies" takes the iron from personal stock
        # first, connects the battery and charges. A click charges for at most
        # five seconds and then offers "Continue charging".
        wait_for('!!document.querySelector("#ws-remake-stock-personal")')
        for _ in range(8):
            click('#ws-remake-prepare')
            wait_for('!document.querySelector("#ws-remake-start").disabled || '
                     '!!document.querySelector("#ws-remake-prepare:not(:disabled)")')
            if page.evaluate('!document.querySelector("#ws-remake-start").disabled'): break
        wait_for('!document.querySelector("#ws-remake-start").disabled')
        click('#ws-remake-start')
        wait_for('!!document.querySelector("#ws-remake-step")')
        click('#ws-remake-step')
        wait_for('!!document.querySelector("#ws-remake-place")')
        click('#ws-remake-place')
        wait_for('document.querySelector("#ws-remake a")?.textContent === "Collect in World"')
        click('.game-tabs [data-screen="progress"]')
        wait_for('document.querySelector("[data-goal=build-camp]")?.dataset.complete === "true"')
        click('[data-goal-go="carry-camp"]')
        wait_for('window.banjoRoom?.status().ready && window.banjoRoom.world.bodies.has(new URLSearchParams(location.search).get("focus"))')
        wait_for('window.banjoRoom.world.aim?.name === new URLSearchParams(location.search).get("focus")')
        # The regular World Q binding performs native inventory take. Goals
        # has no action that can substitute for this interaction.
        for event in ("keyDown", "keyUp"):
            page.send("Input.dispatchKeyEvent", {"type":event, "key":"q", "code":"KeyQ", "windowsVirtualKeyCode":81})
        wait_for('window.banjoRoom.world.inventory?.record?.stowed?.includes(new URLSearchParams(location.search).get("focus"))')
        wait_for('window.banjoRoom.world.inventory?.labels?.[new URLSearchParams(location.search).get("focus")] === "Camp stool"')
        wait_for('document.querySelector("#mini-products").textContent.includes("Camp stool")')
        self.assertEqual(0,page.evaluate('document.querySelectorAll("#mini-products details").length'))
        screenshot("packed-in-world.png")
        # Goals opens on the active chapter (f15cd75b); the camp is the
        # earlier one, chosen the same way as at the start.
        click('.game-tabs [data-screen="progress"]')
        click('#ws-goal-chapters > summary')
        click('[aria-label="Goal chapters"] button:last-child')
        wait_for('document.querySelector("#ws-goals-progress")?.textContent.includes("Chapter complete")')
        self.assertTrue(self.post("/api/workshop/goals", {"chain":starter_goals.CHAIN}, world, player)["complete"])
        page.send("Page.reload")
        wait_for('document.querySelector("#ws-goals-progress")?.textContent.includes("Chapter complete")')
        self.assertEqual(0, page.evaluate('document.querySelectorAll("[data-goal-action],[data-goal-bank]").length'))
        self.assertFalse([e for e in page.events if e.get("method") == "Runtime.exceptionThrown"])
        screenshot("completed.png")

    def test_unsaved_inventory_does_not_award_packing(self):
        with tempfile.TemporaryDirectory() as temp:
            store = room_store.RoomStore(Path(temp))
            body = "workshop-camp"
            receipt = {"status": "installed", "owner_id": "alice", "root_body": body,
                       "request_id": "native-build", "resources_charged": True,
                       "matter_physics_hash": starter_goals._recipe()[1]}
            room = SimpleNamespace(scene="new-game", spec={"precise_rigid_bodies": [{"name": body}]},
                chat=[], workshop_installs=[receipt], player_records={"alice": {"inventory": {}}})
            store.save(room)
            app = SimpleNamespace(world_id="world", room=room, store=store,
                live_holder="world", live=SimpleNamespace(session=SimpleNamespace(id="native")),
                runs_path=Path(temp) / "runs")
            shown = {"record": {"stowed": [body], "hands": {}, "revision": 1}}
            with mock.patch.object(starter_goals.inventory_room, "shown", return_value=shown):
                self.assertFalse(starter_goals.view(app, "alice", {"chain":starter_goals.CHAIN})["goals"][3]["complete"])
                room.player_records["alice"]["inventory"] = shown["record"]
                store.save(room)
                self.assertTrue(starter_goals.view(app, "alice", {"chain":starter_goals.CHAIN})["goals"][3]["complete"])


if __name__ == "__main__": unittest.main()
