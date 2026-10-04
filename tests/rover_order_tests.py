"""Ore delivered by actually mining it: guidance orders the rover, it digs and hauls.

When a furnace's batch is short of an ore that lies in a seam, and a digging
machine already knows that seam and the furnace's intake, guidance offers the
plain order a person could type ("dig at vein and dump it at smelter intake").
Given through the rover's talk endpoint, the routine runs it; the test then
lets the world run and checks ore arrives in the intake from the seam, by the
rover's own dig and dump -- nothing is credited.

    BANJO_LIVE_ENGINE=build/rel/Release/banjo_live_world_run.exe python tests/rover_order_tests.py -v
"""
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
class RoverOrder(unittest.TestCase):
    setUp = agents.AutonomousGuests.setUp
    start = agents.AutonomousGuests.start
    stop = agents.AutonomousGuests.stop
    tearDown = agents.AutonomousGuests.tearDown
    get = hub.NamedWorlds.get
    post = hub.NamedWorlds.post
    join = hub.NamedWorlds.join

    def test_short_ore_is_ordered_dug_and_delivered_by_the_rover(self):
        import process_guidance
        world = self.post('/api/worlds', {'name': 'Ore by rover', 'seeds': {'terrain': 7, 'goods': 851269742}})['id']
        owner = self.join(world, 'Smelter')
        self.players = {world: owner}
        self.post('/api/world/open', {}, world)
        app = self.app.hub.get(world)
        goods = app.brains.goods
        intake = goods.by_name('smelter intake')
        # A fixture that empties the intake: removes ore, grants nothing.
        intake.get('holds', {}).pop('copper ore', None)
        rows = [r for r in process_guidance.choices(app, owner['id']) if r['recipe'] == 'smelt copper']
        self.assertTrue(rows, 'the smelter offers no copper batch')
        action = rows[0]['next_action']
        self.assertEqual('order-rover', action['verb'], action)
        order = action['rover']
        self.assertEqual('dig at vein and dump it at smelter intake', order['said'])
        seam = next(d for d in goods.deposits if d['substance'] == 'copper ore')
        left_before = goods.reserve_kg(seam)
        reply = self.post('/api/world/rover/talk', {'session': app.live.session.id,
                                                   'program': order['program'], 'order': order['said']}, world)
        self.assertTrue(reply['ordered'], reply)
        # The ordered job is now queued: guidance waits instead of ordering again.
        again = [r for r in process_guidance.choices(app, owner['id']) if r['recipe'] == 'smelt copper'][0]
        self.assertEqual('await-delivery', again['next_action']['verb'], again['next_action'])
        delivered = 0.
        for _ in range(240):                      # up to 120 s of world time
            app.clock._tick(.5)
            delivered = float(goods.by_name('smelter intake').get('holds', {}).get('copper ore', 0))
            if delivered > 0:
                break
        self.assertGreater(delivered, 0, 'no ore reached the intake')
        # It came out of the seam, not from nowhere.
        self.assertLess(goods.reserve_kg(seam), left_before)


if __name__ == '__main__':
    unittest.main()
