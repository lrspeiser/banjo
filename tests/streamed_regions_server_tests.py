"""The ground grows as a player walks toward its edge, through the real server.

A named world on 25 cm columns is let grow (docs/streamed-regions.md). A
player's native body walked toward the valley's east edge makes the engine add
the region beside it; the server writes the region into the room's spec and
saves the world at once. Dug out there, saved, and the server stopped and
started again, the region is back with the hole in it.

    BANJO_LIVE_ENGINE=build/r/Release/banjo_live_world_run.exe python tests/streamed_regions_server_tests.py -v
"""
import math
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'playground'), str(ROOT)]
import ai_player_tests as agents
import world_hub_tests as hub

ENGINE = os.environ.get('BANJO_LIVE_ENGINE')


@unittest.skipUnless(ENGINE and Path(ENGINE).is_file(), 'BANJO_LIVE_ENGINE is required')
class StreamedRegions(unittest.TestCase):
    setUp = agents.AutonomousGuests.setUp
    start = agents.AutonomousGuests.start
    stop = agents.AutonomousGuests.stop
    tearDown = agents.AutonomousGuests.tearDown
    get = hub.NamedWorlds.get
    post = hub.NamedWorlds.post
    join = hub.NamedWorlds.join

    def survey(self, sid, world, x, z):
        return self.post('/api/live/act', {'session': sid, 'op': 'survey', 'at': [x, z]}, world)['survey']

    def test_walking_near_the_edge_grows_the_world_and_it_survives_a_restart(self):
        world = self.post('/api/worlds', {'name': 'Edge', 'surface': 'columns',
                                          'seeds': {'terrain': 7, 'goods': 851269742}})['id']
        me = self.join(world, 'Walker')
        self.players = {world: me}
        opened = self.post('/api/world/open', {}, world)
        sid = opened['session']
        app = self.app.hub.get(world)
        self.assertTrue(app.room.spec['terrain'].get('stream'), 'a named world on columns is let grow')
        whole = app.live.act({'session': sid, 'op': 'terrain'})['terrain']
        self.assertTrue(whole['streaming'])
        self.assertEqual([], whole['regions'], 'nothing beyond the valley yet')
        grid = whole['grid']
        edge_x = grid['x0_m'] + (grid['nx'] - 0.5) * grid['cell_m']
        # Off the edge there is no ground yet.
        self.assertFalse(self.survey(sid, world, edge_x + 3, 0.0)['on_the_ground'])
        # Stand 12 m in from the east edge, then walk east: the world grows
        # once the body is within 10 m of the edge.
        x, z = edge_x - 12.0, 0.0
        floor = self.survey(sid, world, x, z)['ground_m']
        person = {'standing_m': [x, floor, z], 'eyes_m': [x, floor + 1.62, z], 'facing': [1, 0, 0]}
        self.post('/api/live/act', {'session': sid, 'op': 'step', 'dt': 1 / 240, 'n': 1, 'person': person}, world)
        def walk(v, seconds):
            native = None
            for _ in range(int(seconds / .25)):
                native = self.post('/api/world/player/walk', {'session': sid, 'velocity_m_s': v,
                                                              'heading_rad': math.pi / 2}, world)['native']
                app.clock._tick(.25)
            return native
        native = walk([0, 0, 0], 0.5)
        self.assertNotIn('regions', {k: v for k, v in app.room.spec['terrain'].items() if v})
        native = walk([2.0, 0, 0], 2.5)
        self.assertGreater(native['position_m'][0], edge_x - 10.0, f'walked toward the edge: {native["position_m"]}')
        self.assertIn([1, 0], app.room.spec['terrain'].get('regions', []), 'the region east was grown and written down')
        # The ground is there now, and its survey says whose it is.
        out_there = self.survey(sid, world, edge_x + 3, z)
        self.assertTrue(out_there['on_the_ground'], out_there)
        self.assertEqual([1, 0], out_there['region'])
        # And the whole ground a page is sent has it.
        whole = app.live.act({'session': sid, 'op': 'terrain'})['terrain']
        self.assertIn([1, 0], [r['at'] for r in whole['regions']])
        # The world was saved as soon as it grew.
        self.assertFalse(getattr(app.room, 'regions_unsaved', False), 'saved once it grew')
        # Dig out there, and save.
        dx, dz = edge_x + 6.0, z + 2.0
        before = self.survey(sid, world, dx, dz)['ground_m']
        dug = app.live.act({'session': sid, 'op': 'dig', 'from': [dx, dz], 'to': [dx, dz], 'width_m': 0.75,
                            'depth_m': 0.3})
        self.assertGreater(dug['dug']['columns'], 0, dug.get('dug'))
        # As deep as what came out could be carried (the dig says how deep).
        went = dug['dug']['depth_m']
        self.assertGreater(went, 0.0)
        after = self.survey(sid, world, dx, dz)['ground_m']
        self.assertAlmostEqual(after, before - went, places=6)
        self.assertTrue(agents.server.keep_world(app, 'streamed region dug'))
        # Stopped and started again: the region, and the hole in it, are back.
        self.stop(); self.start(); self.players = {world: me}
        self.post('/api/world/player/join', {'token': me['token']}, world)
        sid = self.post('/api/world/open', {}, world)['session']
        app = self.app.hub.get(world)
        back = self.survey(sid, world, dx, dz)
        self.assertTrue(back['on_the_ground'], back)
        self.assertEqual([1, 0], back['region'])
        self.assertAlmostEqual(back['ground_m'], after, places=6)
        whole = app.live.act({'session': sid, 'op': 'terrain'})['terrain']
        self.assertIn([1, 0], [r['at'] for r in whole['regions']])
        # And the body is still out near the edge, standing on the ground.
        native = (app.live.session.state.get('native_players') or {}).get(me['id'])
        self.assertIsNotNone(native, 'the body is back')
        under = self.survey(sid, world, native['position_m'][0], native['position_m'][2])
        self.assertTrue(under['on_the_ground'])
        self.assertGreater(native['position_m'][1], under['ground_m'], 'on the ground, not under it')


if __name__ == '__main__':
    unittest.main()
