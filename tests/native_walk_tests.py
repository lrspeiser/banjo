"""A player's native body, walked through the server as the page walks it.

The host derives the actor from the authenticated player and spawns the body
once at that player's own reported stance; each request asks for a velocity
and a facing held 0.5 s. On a generated valley the body must go where it is
walked, stay upright and on the ground, stop when asked, and stand still when
the requests stop. Its walk work is the engine's own account.

    BANJO_LIVE_ENGINE=build/walk/Release/banjo_live_world_run.exe python tests/native_walk_tests.py -v
"""
import math
import time
import os
from pathlib import Path
import sys
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'playground'), str(ROOT)]
import ai_player_tests as agents
import world_hub_tests as hub

ENGINE = os.environ.get('BANJO_LIVE_ENGINE')


def tilt_deg(native):
    w, x, y, z = native['orientation_wxyz']
    return math.degrees(math.acos(max(-1, min(1, 1 - 2 * (x * x + z * z)))))


@unittest.skipUnless(ENGINE and Path(ENGINE).is_file(), 'BANJO_LIVE_ENGINE is required')
class NativeWalk(unittest.TestCase):
    setUp = agents.AutonomousGuests.setUp
    start = agents.AutonomousGuests.start
    stop = agents.AutonomousGuests.stop
    tearDown = agents.AutonomousGuests.tearDown
    get = hub.NamedWorlds.get
    post = hub.NamedWorlds.post
    join = hub.NamedWorlds.join

    def test_a_player_walks_their_own_native_body_and_it_stops(self):
        world = self.post('/api/worlds', {'name': 'Walk', 'seeds': {'terrain': 7, 'goods': 851269742}})['id']
        me = self.join(world, 'Walker')
        self.players = {world: me}
        opened = self.post('/api/world/open', {}, world)
        app = self.app.hub.get(world)
        sid = opened['session']
        # Stand somewhere first: the host spawns the body where the player is.
        x, z = -6.0, 2.0
        floor = self.post('/api/live/act', {'session': sid, 'op': 'survey', 'at': [x, z]}, world)['survey']['ground_m']
        person = {'standing_m': [x, floor, z], 'eyes_m': [x, floor + 1.62, z], 'facing': [1, 0, 0]}
        self.post('/api/live/act', {'session': sid, 'op': 'step', 'dt': 1 / 240, 'n': 1, 'person': person}, world)
        # A request may not name another actor or a place to appear.
        with self.assertRaises(Exception):
            self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': [0, 0, 0],
                                                 'heading_rad': 0, 'actor': 'someone else'}, world)
        def walk(v, seconds, heading=math.pi / 2):
            reply = None
            for _ in range(int(seconds / .25)):
                reply = self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': v,
                                                             'heading_rad': heading}, world)
                app.clock._tick(.25)
            return self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': v,
                                                        'heading_rad': heading}, world)['native']
        stood = walk([0, 0, 0], 1.0)
        self.assertTrue(stood['walk']['supported'], stood)
        self.assertLess(tilt_deg(stood), 3)
        self.assertLess(math.hypot(stood['position_m'][0] - x, stood['position_m'][2] - z), .3,
                        'spawned where the player stood')
        moved = walk([1.0, 0, 0], 3.0)
        went = moved['position_m'][0] - stood['position_m'][0]
        self.assertGreater(went, 1.5, f'walked {went:.2f} m in 3 s at 1 m/s')
        self.assertLess(tilt_deg(moved), 5)
        # Its walk work is kept; on ground that falls away it brakes, so the
        # sign is the ground's business, not the test's.
        self.assertNotEqual(moved['walk']['work_j'], stood['walk']['work_j'])
        stopped = walk([0, 0, 0], 1.5)
        self.assertLess(math.hypot(*stopped['velocity_m_s']), .1, 'it stops when asked')
        # No more requests: a passive body, which stays standing where it is.
        for _ in range(8):
            app.clock._tick(.25)
        rest = (app.live.session.state.get('native_players') or {})[me['id']]
        self.assertLess(math.dist(rest['position_m'], stopped['position_m']), .1)

    def test_a_player_who_has_left_takes_their_body_with_them(self):
        # A body left standing where its player last was is in everyone's
        # way (a walker tripped over eight of them, 2026-10-04).
        from unittest import mock
        import native_body
        import player_world
        world = self.post('/api/worlds', {'name': 'Leave', 'seeds': {'terrain': 7, 'goods': 851269742}})['id']
        first, second = self.join(world, 'First'), self.join(world, 'Second')
        self.players = {world: first}
        sid = self.post('/api/world/open', {}, world)['session']
        app = self.app.hub.get(world)
        def stand_and_walk(who, x):
            self.players[world] = who
            floor = self.post('/api/live/act', {'session': sid, 'op': 'survey', 'at': [x, 2.0]}, world)['survey']['ground_m']
            person = {'standing_m': [x, floor, 2.0], 'eyes_m': [x, floor + 1.62, 2.0], 'facing': [1, 0, 0]}
            self.post('/api/live/act', {'session': sid, 'op': 'step', 'dt': 1 / 240, 'n': 1, 'person': person}, world)
            return self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': [0, 0, 0], 'heading_rad': 0}, world)
        stand_and_walk(first, -6.0)
        stand_and_walk(second, -3.0)
        bodies = lambda: set((app.live.session.send(op='step', dt=1 / 240, n=1) or {}).get('native_players') or {})
        self.assertEqual({first['id'], second['id']}, bodies())
        # A moment later both are still here; long after the first was last
        # seen, the next walk by anyone takes the first one's body away.
        self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': [0, 0, 0], 'heading_rad': 0}, world)
        self.assertEqual({first['id'], second['id']}, bodies())
        later = time.time() + player_world.ACTIVE_S + 5
        with mock.patch.object(native_body.time, 'time', return_value=later):
            self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': [0, 0, 0], 'heading_rad': 0}, world)
        self.assertEqual({second['id']}, bodies())

    def test_a_body_lost_under_the_world_is_stood_up_again(self):
        # Thrown off the map, a body fell for ever and was saved there.
        world = self.post('/api/worlds', {'name': 'Lost', 'seeds': {'terrain': 7, 'goods': 851269742}})['id']
        me = self.join(world, 'Faller')
        self.players = {world: me}
        sid = self.post('/api/world/open', {}, world)['session']
        app = self.app.hub.get(world)
        floor = self.post('/api/live/act', {'session': sid, 'op': 'survey', 'at': [-6.0, 2.0]}, world)['survey']['ground_m']
        person = {'standing_m': [-6.0, floor, 2.0], 'eyes_m': [-6.0, floor + 1.62, 2.0], 'facing': [1, 0, 0]}
        self.post('/api/live/act', {'session': sid, 'op': 'step', 'dt': 1 / 240, 'n': 1, 'person': person}, world)
        self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': [0, 0, 0], 'heading_rad': 0}, world)
        # Put it far under the ground, as a fall off the edge leaves it.
        app.live.session.send(op='player-remove', actor=me['id'])
        app.live.session.send(op='player-spawn', actor=me['id'], feet_m=[-6.0, -9.0, 2.0])
        app.live.session.send(op='step', dt=1 / 240, n=1)
        import native_body
        native_body._LOOKED.clear()
        reply = self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': [0, 0, 0], 'heading_rad': 0}, world)
        at = reply['native']['position_m']
        ground = self.post('/api/live/act', {'session': sid, 'op': 'survey', 'at': [0.0, 0.0]}, world)['survey']['ground_m']
        self.assertLess(math.hypot(at[0], at[2]), .5, f'back where a new player starts: {at}')
        self.assertGreater(at[1], ground, 'standing on the ground, not under it')

    def test_a_native_body_survives_an_install_and_a_restart(self):
        # An install rebuilds the room from its snapshot; a restart reopens
        # it from the saved world. The body must be where it stood both times.
        world, me, app = agents.AutonomousGuests.setup_world(self, legacy_process=True)
        sid = app.live.session.id
        x, z = -3.0, 2.5
        floor = self.post('/api/live/act', {'session': sid, 'op': 'survey', 'at': [x, z]}, world)['survey']['ground_m']
        person = {'standing_m': [x, floor, z], 'eyes_m': [x, floor + 1.62, z], 'facing': [1, 0, 0]}
        self.post('/api/live/act', {'session': sid, 'op': 'step', 'dt': 1 / 240, 'n': 1, 'person': person}, world)
        for _ in range(6):
            stood = self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': [0, 0, 0],
                                                         'heading_rad': 0}, world)['native']
            app.clock._tick(.25)
        self.assertTrue(stood['walk']['supported'], stood)
        def mine(app):
            return (app.live.session.state.get('native_players') or {}).get(me['id'])
        before = mine(app)
        recipe = self.post('/api/workshop/goals', {'chain': 'first-camp-v1'}, world)['recipe']
        context = self.post('/api/world/workshop/context', {}, world)
        # The terrain is chosen at random; the stand trial refuses a slope, so
        # try a few spots clear of the body, as the AI players do.
        refusals = []
        for spot in ([3, 0], [3, 3], [0, 4], [4, -2], [-1, -3], [5, 2]):
            try:
                preview = self.post('/api/world/workshop/preview', {'session': context['session'], 'scene': context['scene'],
                    'candidate': recipe, 'mode': 'authoring', 'position_m': spot}, world)
                break
            except urllib.error.HTTPError as error:
                refusals.append(error.read().decode()[:160])
        else:
            self.fail('; '.join(refusals))
        try:
            built = self.post('/api/world/workshop/commit', {'session': preview['session'], 'scene': preview['scene'],
                'preview_id': preview['preview_id'], 'request_id': 'native-body-install'}, world)
        except urllib.error.HTTPError as error:
            self.fail(error.read().decode())
        self.assertNotEqual(sid, built['session'], 'the install rebuilt the room')
        after = mine(app)
        self.assertIsNotNone(after, 'the body is still in the rebuilt room')
        self.assertLess(math.dist(after['position_m'], before['position_m']), .01)
        self.assertLess(tilt_deg(after), 3)
        # And it walks on in the rebuilt room.
        sid = built['session']
        for _ in range(8):
            moved = self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': [1, 0, 0],
                                                         'heading_rad': math.pi / 2}, world)['native']
            app.clock._tick(.25)
        self.assertGreater(moved['position_m'][0] - after['position_m'][0], .5)
        self.assertTrue(agents.server.keep_world(app, 'native body restart'))
        kept = mine(app)
        self.stop(); self.start(); self.players = {world: me}
        self.post('/api/world/player/join', {'token': me['token']}, world)
        self.post('/api/world/open', {}, world)
        app = self.app.hub.get(world)
        back = mine(app)
        self.assertIsNotNone(back, 'the body is back after a restart')
        self.assertLess(math.dist(back['position_m'], kept['position_m']), .05)
        self.assertLess(tilt_deg(back), 5)

    @unittest.skipUnless(os.environ.get('BANJO_BROWSER_TESTS') == 'required' or agents.qa_browser.CHROME.is_file(),
                         'Chrome is required')
    def test_a_new_player_starts_as_a_body_and_can_switch_to_god_mode(self):
        import json
        import time
        world, me, app = agents.AutonomousGuests.setup_world(self)
        chrome = agents.qa_browser.Chrome(1280, 800)
        self.addCleanup(chrome.close)
        page = chrome.page
        page.send('Page.enable')
        # As a new player: nothing chosen yet, so the game's own default.
        page.send('Page.addScriptToEvaluateOnNewDocument', {'source':
            f'localStorage.setItem("banjo.player.{world}",{json.dumps(me["token"])});'
            'localStorage.removeItem("banjo.movement");'
            # Hold the first stance report, then refuse walking explicitly.
            # Neither condition may substitute a nonphysical camera walk.
            'window.__walkRequests=0;window.__walkRefusals=0;window.__forceWalkRefusal=true;'
            'window.__initialPoseWaiting=false;'
            'const poseGate=new Promise(resolve=>window.__releaseInitialPose=resolve);'
            'const originalFetch=window.fetch;let gated=false;'
            'window.fetch=async(...args)=>{const path=String(args[0]);'
            'if(path==="/api/live/act" && !gated && args[1]?.body'
            ' && JSON.parse(args[1].body).op==="step"){'
            'gated=true;window.__initialPoseWaiting=true;await poseGate;}'
            'if(path==="/api/world/player/walk"){window.__walkRequests++;'
            'if(window.__forceWalkRefusal){window.__walkRefusals++;'
            'return new Response(JSON.stringify({error:"Body admission temporarily refused"}),'
            '{status:400,headers:{"Content-Type":"application/json"}});}}'
            'return originalFetch(...args);};'})
        page.send('Page.navigate', {'url': self.base + f'/world?world={world}'})
        def wait(expression, seconds=40):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                try:
                    if page.evaluate('Boolean(' + expression + ')'):
                        return
                except (RuntimeError, TimeoutError):
                    pass
                time.sleep(.1)
            self.fail('did not reach ' + expression)
        wait('window.banjoRoom?.ready()')
        self.assertEqual('native', page.evaluate('document.querySelector("#game-menu-movement select").value'))
        self.assertIn('Body', page.evaluate('document.querySelector("#game-menu-movement select").selectedOptions[0].textContent'))
        wait('window.__initialPoseWaiting')
        page.evaluate('window.__from=banjoRoom.camera.position.clone();'
                      'dispatchEvent(new KeyboardEvent("keydown",{code:"KeyW",key:"w"}))')
        time.sleep(.4)
        self.assertEqual(0, page.evaluate('window.__walkRequests'), 'native spawn raced the unacknowledged stance')
        self.assertLess(page.evaluate('banjoRoom.camera.position.distanceTo(__from)'), .001,
                        'waiting for the first stance moved an unbodied camera')
        self.assertIsNone((app.live.session.state.get('native_players') or {}).get(me['id']))
        page.evaluate('window.__releaseInitialPose()')
        wait('banjoRoom.status().movement.refused')
        self.assertEqual('Body admission temporarily refused', page.evaluate('banjoRoom.status().movement.refused'))
        time.sleep(.4)
        self.assertLess(page.evaluate('banjoRoom.camera.position.distanceTo(__from)'), .001,
                        'refused native admission fell back to camera walking')
        self.assertIsNone((app.live.session.state.get('native_players') or {}).get(me['id']))
        page.evaluate('window.__forceWalkRefusal=false')
        wait('banjoRoom.status().movement.native?.position_m', 10)
        native_start = (app.live.session.state.get('native_players') or {}).get(me['id'])
        self.assertIsNotNone(native_start, 'the recovered page acquired the real native body')
        page.evaluate('window.__from=banjoRoom.camera.position.clone()')
        # Walking moves the body, and the eye goes with it.
        time.sleep(3)
        page.evaluate('dispatchEvent(new KeyboardEvent("keyup",{code:"KeyW",key:"w"}))')
        wait('Math.hypot(banjoRoom.camera.position.x-__from.x,banjoRoom.camera.position.z-__from.z)>1', 10)
        native = (app.live.session.state.get('native_players') or {}).get(me['id'])
        self.assertIsNotNone(native, 'the page walked a native body')
        self.assertGreater(math.hypot(native['position_m'][0]-native_start['position_m'][0],
                                      native['position_m'][2]-native_start['position_m'][2]), 1,
                           'the native actor itself moved, not only its rendered eye')
        # God mode, from the Menu: the camera flies free of the body.
        page.evaluate('(s=>{s.value="fly";s.dispatchEvent(new Event("change",{bubbles:true}))})'
                      '(document.querySelector("#game-menu-movement select"))')
        page.evaluate('window.__y=banjoRoom.camera.position.y;dispatchEvent(new KeyboardEvent("keydown",{code:"Space",key:" "}))')
        wait('banjoRoom.camera.position.y>__y+1', 10)
        page.evaluate('dispatchEvent(new KeyboardEvent("keyup",{code:"Space",key:" "}))')
        self.assertIn('God mode', page.evaluate('document.querySelector("[data-movement]").textContent'))

if __name__ == '__main__':
    unittest.main()
