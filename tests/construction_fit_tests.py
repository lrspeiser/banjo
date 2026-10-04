"""A foundation pad fitted to a slope stands level; one as drawn tilts with it.

The pad's four footings are cut to the ground under each (construction_fit),
saved as a new version of the design, and installed upright as made rather
than turned to the slope (workshop_install _seat_as_made). Both pads are
built from oak the player collected, in a generated world.

    BANJO_LIVE_ENGINE=build/rel/Release/banjo_live_world_run.exe python tests/construction_fit_tests.py
"""
import math
from pathlib import Path
import sys
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'playground'), str(ROOT)]
import ai_player_tests as fixture


def tilt_deg(body):
    w, x, y, z = body.get('orientation_wxyz') or [1, 0, 0, 0]
    return math.degrees(math.acos(max(-1, min(1, 1 - 2 * (x * x + z * z)))))


@unittest.skipUnless(fixture.hub.RUNNER.is_file() and fixture.hub.ENGINE.is_file(), 'native world engine not built')
class FittedPad(unittest.TestCase):
    setUp = fixture.AutonomousGuests.setUp
    tearDown = fixture.AutonomousGuests.tearDown
    start = fixture.AutonomousGuests.start
    stop = fixture.AutonomousGuests.stop
    get = fixture.AutonomousGuests.get
    setup_world = fixture.AutonomousGuests.setup_world
    join = fixture.AutonomousGuests.join

    def post(self, *args, **kwargs):
        try:
            return fixture.AutonomousGuests.post(self, *args, **kwargs)
        except urllib.error.HTTPError as error:
            error.msg += ': ' + error.read().decode('utf-8')
            raise

    def ground(self, app, world, x, z):
        return self.post('/api/live/act', {'session': app.live.session.id, 'op': 'survey', 'at': [x, z]},
                         world)['survey']['ground_m']

    def slopes(self, app, world, count):
        """Spots where the ground falls 8-14 cm across 0.6 m (about 9 degrees),
        dry, at least 2.5 m apart and clear of everything standing."""
        bodies = [b['position_m'] for b in app.live.session.state['bodies']]
        found = []
        for i in range(-14, 15, 2):
            for j in range(-14, 15, 2):
                x, z = i * .5, j * .5
                if any(math.hypot(b[0] - x, b[2] - z) < 2.5 for b in bodies + found):
                    continue
                corners = [self.post('/api/live/act', {'session': app.live.session.id, 'op': 'survey',
                    'at': [x + dx, z + dz]}, world)['survey'] for dx in (-.45, .45) for dz in (-.45, .45)]
                if any(float((c.get('water') or {}).get('depth_m', 0)) > .005 for c in corners):
                    continue      # dry ground only
                heights = [self.ground(app, world, x + dx, z + dz) for dx in (-.3, .3) for dz in (-.3, .3)]
                if .08 < max(heights) - min(heights) < .14:
                    found.append([x, 0, z])
                    if len(found) == count:
                        return [[f[0], f[2]] for f in found]
        self.skipTest('no moderate slope clear of things in this world')

    def build(self, app, world, candidate, spot, ident):
        ctx = self.post('/api/world/workshop/context', {}, world)
        preview = self.post('/api/world/workshop/preview', {'session': ctx['session'], 'scene': ctx['scene'],
            'candidate': candidate, 'mode': 'authoring', 'position_m': spot}, world)
        built = self.post('/api/world/workshop/commit', {'session': preview['session'], 'scene': preview['scene'],
            'preview_id': preview['preview_id'], 'request_id': ident}, world)
        for _ in range(4):
            self.post('/api/live/act', {'session': built['session'], 'op': 'step', 'dt': 1 / 240, 'n': 120}, world)
        return next(b for b in app.live.session.state['bodies'] if b['name'] == built['root_body'])

    def test_a_fitted_pad_stands_level_where_one_as_drawn_tilts(self):
        from mcp import workshop
        world, owner, app = self.setup_world(legacy_process=True)
        for pile in [p for p in app.brains.goods.stockpiles if (p.get('holds') or {}).get('oak', 0) > 0
                     and not p.get('rack')][:2]:
            x, z = pile['at_m']
            self.post('/api/world/goods/collect', {'session': app.live.session.id, 'pile': pile['name'],
                'request_id': 'fit-oak-' + pile['name'].replace(' ', '-'),
                'person': {'eyes_m': [x, self.ground(app, world, x, z) + 1.62, z], 'facing': [0, 0, -1]}}, world)
        pad = workshop.assemble('foundation-pad', parameters={'width_m': .8, 'depth_m': .8, 'thickness_m': .08,
                                                               'footing_section_m': .1, 'material': 'oak'})
        drawn = {'kind': pad.kind, 'parameters': dict(pad.parameters),
                 'component_overrides': dict(pad.lineage.get('component_overrides') or {})}
        plain_spot, fitted_spot = self.slopes(app, world, 2)
        # As drawn it is turned to the slope: it stands tilted, or tips over
        # and is refused.
        try:
            plain = tilt_deg(self.build(app, world, drawn, plain_spot, 'pad-as-drawn'))
        except urllib.error.HTTPError as error:
            self.assertIn('would not stand here', error.msg)
            plain = None
        fit = self.post('/api/world/workshop/fit_to_ground', {'candidate': drawn, 'position_m': fitted_spot,
                                                               'save': True, 'label': 'Fitted pad'}, world)
        self.assertEqual(4, len(fit['footings_m']))
        self.assertAlmostEqual(.05, min(fit['footings_m']), 6)
        self.assertGreater(max(fit['footings_m']), .1)
        self.assertEqual('Fitted pad', fit['library_item']['name'])
        self.assertIn('cm', fit['said'])
        fitted = self.build(app, world, fit['candidate'], fitted_spot, 'pad-fitted')
        said = 'refused, it tipped over' if plain is None else f'{plain:.2f} deg'
        print(f"\n    as drawn: {said}; fitted {fit['footings_m']}: {tilt_deg(fitted):.2f} deg")
        if plain is not None:
            self.assertGreater(plain, 4.0, 'a pad as drawn is turned to the slope')
        self.assertLess(tilt_deg(fitted), 1.5, 'a fitted pad stands level')
        # Only a pad has footings, and a position is [x, z].
        stool = self.post('/api/workshop/goals', {'chain': 'first-workshop-v1'}, world)['recipe']
        with self.assertRaisesRegex(urllib.error.HTTPError, 'Only a foundation pad'):
            self.post('/api/world/workshop/fit_to_ground', {'candidate': stool, 'position_m': fitted_spot}, world)
        with self.assertRaisesRegex(urllib.error.HTTPError, 'position_m'):
            self.post('/api/world/workshop/fit_to_ground', {'candidate': drawn, 'position_m': [1]}, world)


class ExactFurniture(FittedPad):
    """The Camp chair and Camp shelf are made of exact parts, so their thin
    parts are what they are drawn as; built on level ground, each stands."""
    test_a_fitted_pad_stands_level_where_one_as_drawn_tilts = None   # run once, above

    def test_exact_furniture_stands_where_it_is_built(self):
        import goal_chains
        world, owner, app = self.setup_world(legacy_process=True)
        for pile in [p for p in app.brains.goods.stockpiles if (p.get('holds') or {}).get('oak', 0) > 0
                     and not p.get('rack')][:2]:
            x, z = pile['at_m']
            self.post('/api/world/goods/collect', {'session': app.live.session.id, 'pile': pile['name'],
                'request_id': 'furniture-oak-' + pile['name'].replace(' ', '-'),
                'person': {'eyes_m': [x, self.ground(app, world, x, z) + 1.62, z], 'facing': [0, 0, -1]}}, world)
        bodies = [b['position_m'] for b in app.live.session.state['bodies']]
        spots = []
        for i in range(-14, 15, 2):
            for j in range(-14, 15, 2):
                x, z = i * .5, j * .5
                if any(math.hypot(b[0] - x, b[2] - z) < 2.5 for b in bodies) or                         any(math.hypot(s[0] - x, s[1] - z) < 2.5 for s in spots):
                    continue
                heights = [self.ground(app, world, x + dx, z + dz) for dx in (-.5, .5) for dz in (-.5, .5)]
                if max(heights) - min(heights) < .03:
                    spots.append([x, z])
        self.assertGreaterEqual(len(spots), 2, 'no level ground for two pieces')
        for (kind, ident), spot in zip((('chair', 'starter-camp-chair'), ('shelf-unit', 'starter-camp-shelf')), spots):
            body = self.build(app, world, goal_chains.exact_furniture_recipe(kind, ident), spot, 'furniture-' + kind)
            self.assertTrue(body.get('rigid_parts_local'), f'{kind} is exact parts, not cells')
            self.assertLess(tilt_deg(body), 2.0, f'{kind} stands')


if __name__ == '__main__':
    unittest.main()
