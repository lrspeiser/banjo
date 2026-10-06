"""Supported selection/chat/draft and paid-output boundaries on real Windows native host."""
import json
import unittest
from unittest import mock
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'playground'),str(ROOT)]
import workshop_navigation_tests as navigation
import game_guidance
import workshop_chat


class NavigationCatalog(unittest.TestCase):
    def test_catalog_only_offers_known_sources_and_unknown_model_ids_cannot_navigate(self):
        from types import SimpleNamespace
        catalog=game_guidance.chat_actions({'carried':[{'id':'mine','name':'My pick','where':'right','material':'oak'}]},
            {'templates':[{'kind':'field-pick','name':'Personal field pick','readiness':{'ready_as_drawn':True},'enough':False}]},None)
        self.assertEqual('mine',next(a for a in catalog if a['id']=='carried:mine')['selection']['id'])
        responses=[{'status':'completed','output':[{'type':'function_call','call_id':'a','name':'select_source','arguments':'{"id":"invented"}'}]},
            {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'Choose a supported recipe.'}]}]}]
        seen=[]
        def provider(app,payload):seen.append(payload);return responses.pop(0)
        with mock.patch.object(workshop_chat,'_call_model',side_effect=provider):
            answer=game_guidance.answer(SimpleNamespace(api_key='test',model='test'),{'message':'Make a pick'},
                {'chat_actions':catalog,'observed_native_t_s':0})
        self.assertFalse(any(a.get('open') for a in answer['actions']))
        self.assertIn('Unknown source',seen[-1]['input'][-1]['output'])


class BuildLabChat(navigation.GameScreens):
    # Inherit helpers, not the older screen contract's test cases.
    pass

# Avoid rerunning the base class's entire unrelated solar/ground suite here.
for _name in dir(navigation.GameScreens):
    if _name.startswith('test_'):setattr(BuildLabChat,_name,None)


def test_selection_edit_save_review_reload_and_landscape(self):
    world,owner,app=self.setup_world();self.browser(world,owner)
    self.navigate(world,'workshop=1&tab=lab&material=rubber')
    self.assert_empty();self.click('#ws-first-tool')
    self.wait('document.querySelector("#ws-name").textContent.includes("field-pick")')
    self.wait('document.querySelector("#ws-draft-save")?.offsetParent!==null')
    self.assertIn('No supported recipe uses Rubber',self.page.evaluate('document.querySelector("#ws-recipe-filter-status").textContent'))
    self.assertTrue(self.page.evaluate('document.querySelector("[data-open-recipe]").offsetParent!==null'))
    self.click('[data-customize-item]')
    before=self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()')
    self.page.evaluate('document.querySelector("#ws-component-chat-text").value="Make the handle longer";document.querySelector("#ws-component-chat").requestSubmit()')
    self.wait('document.querySelector("#ws-lab-draft").textContent.includes("Draft saved")')
    after=self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()')
    self.assertNotEqual(before,after)
    self.page.send('Page.reload');self.wait('document.querySelector("#ws-lab-draft")?.textContent.includes("Draft restored")')
    self.assertIsNotNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
    self.click('#ws-draft-save');self.wait('document.querySelector("#ws-lab-draft").textContent.includes("Saved to Recipes")')
    self.click('#ws-draft-build');self.wait('!!document.querySelector("#ws-remake-prepare")')
    self.assertTrue(self.page.evaluate('document.querySelector("#ws-remake-start").disabled'))
    for _ in range(6):
        self.click('#ws-remake-prepare')
        self.wait('document.querySelector("#ws-remake")?.getAttribute("aria-busy")!=="true"')
        if self.page.evaluate('document.querySelector("#ws-remake-start") && !document.querySelector("#ws-remake-start").disabled'):break
        app.clock._tick(1)
    self.wait('document.querySelector("#ws-remake-start") && !document.querySelector("#ws-remake-start").disabled')
    self.click('#ws-remake-start');self.wait('!!document.querySelector("#ws-remake-step")')
    self.click('#ws-remake-step');self.wait('!!document.querySelector("#ws-remake-collect")')
    self.click('#ws-remake-collect');self.wait('!!document.querySelector("#ws-inv-grid [data-product]")')
    self.assertIn('field-pick',self.page.evaluate('document.querySelector("#ws-inv-grid").textContent').lower())
    self.click('#ws-inv-grid [data-product] button');self.wait('document.querySelector("#ws-draft-save")?.offsetParent!==null')
    self.screenshot('build-lab-desktop.png')
    self.page.send('Emulation.setDeviceMetricsOverride',{'width':844,'height':390,'deviceScaleFactor':1,'mobile':True})
    self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':True})
    self.click('[data-customize-item]');self.wait('document.body.classList.contains("ws-chat-open")')
    self.click('#ws-component-chat-text')
    self.screenshot('build-lab-landscape-chat.png')
    self.page.evaluate('document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}))')
    self.page.send('Page.navigate',{'url':self.base+f'/world?world={world}&recipe=field-pick%3APersonal+field+pick&material=rubber'})
    self.wait('window.banjoRoom?.ready()')
    self.assertTrue(self.page.evaluate('document.querySelector("#next-step").hidden'))
    self.assertNotIn('recipe=',self.page.evaluate('document.querySelector("[data-screen=world]").href'))
    self.screenshot('world-landscape-clean.png')
    rover=self.page.evaluate('window.banjoRoom.world.machines.programs.find(p=>p.kind==="roam")?.body')
    self.assertIsNotNone(rover)
    self.page.evaluate(f'window.banjoRoom.pick({json.dumps(rover)})')
    self.open_rail();self.wait('!!document.querySelector(".rover-card [data-rover-command]")')
    self.assertEqual(1,self.page.evaluate('Array.from(document.querySelectorAll(".rover-card")).filter(e=>e.offsetParent!==null).length'))
    self.click('.rover-card button:not([data-rover-command])')
    self.wait('document.querySelector("#chat-recipient").value.startsWith("robot:")')
    self.click('#ask-text')
    self.page.evaluate('document.querySelector("#ask-text").value="stop";document.querySelector("#ask").requestSubmit()')
    self.wait('document.querySelector("#chat").textContent.includes("Stopping. I will hold here") && !document.querySelector("#ask-send").disabled')
    self.assertEqual('waiting',self.page.evaluate('window.banjoRoom.world.machines.programs.find(p=>p.kind==="roam").asked?.doing'))
    self.screenshot('rover-landscape-chat.png')
    self.assertEqual([], [e for e in self.page.events if e.get('method')=='Runtime.exceptionThrown'])


def test_game_chat_selects_real_recipe_and_failed_chat_keeps_controls(self):
    world,owner,app=self.setup_world();app.api_key='test';self.browser(world,owner)
    self.navigate(world,'workshop=1&tab=inventory');self.click('.game-bottom-tabs [aria-controls=ws-chat-home]')
    turns=[{'status':'completed','output':[{'type':'function_call','call_id':'pick','name':'select_source',
        'arguments':json.dumps({'id':'recipe:field-pick:Personal field pick'})}]},
        {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'I opened the supported pick draft. Make still needs supplies.'}]}]}]
    with mock.patch.object(workshop_chat,'_call_model',side_effect=lambda *_:turns.pop(0)):
        self.page.evaluate('document.querySelector("#ws-component-chat-text").value="Use what I have to make a pick";document.querySelector("#ws-component-chat").requestSubmit()')
        self.wait('document.querySelector("#ws-lab-draft")?.offsetParent!==null')
    self.assertIn('field-pick',self.page.evaluate('document.querySelector("#ws-name").textContent'))
    with mock.patch.object(workshop_chat,'_call_model',side_effect=ValueError('Controlled chat failure')):
        self.page.evaluate('document.querySelector("#ws-component-chat-text").value="Make the handle longer";document.querySelector("#ws-component-chat").requestSubmit()')
        self.wait('document.querySelector("#ws-chat-log").textContent.includes("Controlled chat failure")')
    self.assertFalse(self.page.evaluate('document.querySelector("#ws-component-chat-text").disabled'))
    self.assertTrue(self.page.evaluate('document.querySelector("#ws-draft-save").offsetParent!==null'))

BuildLabChat.test_selection_edit_save_review_reload_and_landscape=test_selection_edit_save_review_reload_and_landscape
BuildLabChat.test_game_chat_selects_real_recipe_and_failed_chat_keeps_controls=test_game_chat_selects_real_recipe_and_failed_chat_keeps_controls

if __name__=='__main__':unittest.main()
