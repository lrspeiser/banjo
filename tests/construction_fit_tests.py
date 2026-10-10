"""A foundation pad fitted to a slope stands level; one as drawn tilts with it.

The pad's four footings are cut to the ground under each (construction_fit),
saved as a new version of the design, and installed upright as made rather
than turned to the slope (workshop_install _seat_as_made).

The pads are the game's own catalog pad: concrete, 0.4 m square and 0.05 m
thick on 0.1 m footings, 24 kg as drawn. Both pads were oak gathered from the
world's piles until playable worlds became inorganic (caeb6424); a playable
world has no oak and refuses it. Concrete has no pile and no trader -- it is
made in the world -- and a new world's rack starts with 40 kg of it
(workshop_library.DEFAULT_RACK), enough for one pad and not two. So the pad as
drawn and the fitted pad are each made in a new world of their own.

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

# The catalog pad (FOUNDATION_PARAMETERS' least size, in its own material).
PAD = {'width_m': .4, 'depth_m': .4, 'thickness_m': .05, 'footing_section_m': .1, 'material': 'concrete'}


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
    advance = fixture.AutonomousGuests.advance

    def post(self, *args, **kwargs):
        try:
            return fixture.AutonomousGuests.post(self, *args, **kwargs)
        except urllib.error.HTTPError as error:
            error.msg += ': ' + error.read().decode('utf-8')
            raise

    def survey(self, app, world, x, z):
        return self.post('/api/live/act', {'session': app.live.session.id, 'op': 'survey', 'at': [x, z]},
                         world)['survey']

    def ground(self, app, world, x, z):
        return self.survey(app, world, x, z)['ground_m']

    def slope(self, app, world, parameters):
        """A spot where the ground under the pad's four footings falls 6 to
        10 cm (about ten degrees across them), dry under the whole pad, and at
        least 2.5 m clear of everything standing."""
        import construction_fit
        bodies = [b['position_m'] for b in app.live.session.state['bodies']]
        reach = max(parameters['width_m'], parameters['depth_m']) / 2 + .05
        for i in range(-14, 15, 2):
            for j in range(-14, 15, 2):
                x, z = i * .5, j * .5
                if any(math.hypot(b[0] - x, b[2] - z) < 2.5 for b in bodies):
                    continue
                corners = [self.survey(app, world, x + dx, z + dz) for dx in (-reach, reach) for dz in (-reach, reach)]
                if any(float((c.get('water') or {}).get('depth_m', 0)) > .005 for c in corners):
                    continue      # dry ground only
                heights = [self.ground(app, world, fx, fz)
                           for fx, fz in construction_fit.footing_middles(parameters, [x, z])]
                if .06 < max(heights) - min(heights) < .10:
                    return [x, z]
        self.skipTest('no moderate slope clear of things in this world')

    def make(self, app, world, candidate, spot, ident):
        """Make `candidate` at `spot` as a player does: preview it, gather what
        the preview says the rack is short of from the world's own finite
        sources (its piles, then its trader: goal_chains_tests.acquire_material),
        make it, and let it stand for two seconds of the world's time."""
        import goal_chains_tests as chains
        player = self.players[world]['token']
        for gathered in range(12):
            ctx = self.post('/api/world/workshop/context', {}, world)
            preview = self.post('/api/world/workshop/preview', {'session': ctx['session'], 'scene': ctx['scene'],
                'candidate': candidate, 'mode': 'authoring', 'position_m': spot}, world)
            missing = preview['needs']['missing']
            if not missing:
                break
            for row in missing:
                held = self.post('/api/workshop/inventory', {}, world)['materials']
                have = next((m['personal_kg'] for m in held if m['material'] == row['material']), 0.)
                # A few kilograms at a time keeps each gathering inside the
                # helper's own bound of 32 actions (a trader's lot is 1 kg).
                chains.acquire_material(self, world, player, row['material'], have + min(row['short_kg'], 6.),
                                        f"{ident}-{row['material'].replace(' ', '-')}-{gathered}")
        else:
            self.fail(f'{ident} is still short after gathering: {missing}')
        built = self.post('/api/world/workshop/commit', {'session': preview['session'], 'scene': preview['scene'],
            'preview_id': preview['preview_id'], 'request_id': ident}, world)
        self.advance(world, built['session'], 2.)
        return next(b for b in app.live.session.state['bodies'] if b['name'] == built['root_body'])

    def test_a_fitted_pad_stands_level_where_one_as_drawn_tilts(self):
        from mcp import workshop
        pad = workshop.assemble('foundation-pad', parameters=PAD)
        drawn = {'kind': pad.kind, 'parameters': dict(pad.parameters),
                 'component_overrides': dict(pad.lineage.get('component_overrides') or {})}
        # As drawn it is turned to the slope: it stands tilted, or tips over
        # and is refused.
        world, owner, app = self.setup_world(legacy_process=True)
        plain_spot = self.slope(app, world, drawn['parameters'])
        try:
            plain = tilt_deg(self.make(app, world, drawn, plain_spot, 'pad-as-drawn'))
        except urllib.error.HTTPError as error:
            self.assertIn('would not stand here', error.msg)
            plain = None
        # Fitted, in a world of its own: its rack has the concrete for one pad.
        world, owner, app = self.setup_world(legacy_process=True)
        fitted_spot = self.slope(app, world, drawn['parameters'])
        fit = self.post('/api/world/workshop/fit_to_ground', {'candidate': drawn, 'position_m': fitted_spot,
                                                               'save': True, 'label': 'Fitted pad'}, world)
        self.assertEqual(4, len(fit['footings_m']))
        self.assertAlmostEqual(.05, min(fit['footings_m']), 6)
        self.assertGreater(max(fit['footings_m']), .1)
        self.assertEqual('Fitted pad', fit['library_item']['name'])
        self.assertIn('cm', fit['said'])
        fitted = self.make(app, world, fit['candidate'], fitted_spot, 'pad-fitted')
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
    parts are what they are drawn as; built on level ground, each stands.
    They are iron, as a playable world makes them (playable_recipes), from the
    iron the world holds: its rack, its piles and its trader."""
    test_a_fitted_pad_stands_level_where_one_as_drawn_tilts = None   # run once, above

    def test_exact_furniture_stands_where_it_is_built(self):
        import goal_chains
        world, owner, app = self.setup_world(legacy_process=True)
        bodies = [b['position_m'] for b in app.live.session.state['bodies']]
        spots = []
        for i in range(-14, 15, 2):
            for j in range(-14, 15, 2):
                x, z = i * .5, j * .5
                if any(math.hypot(b[0] - x, b[2] - z) < 2.5 for b in bodies) or \
                        any(math.hypot(s[0] - x, s[1] - z) < 2.5 for s in spots):
                    continue
                heights = [self.ground(app, world, x + dx, z + dz) for dx in (-.5, .5) for dz in (-.5, .5)]
                if max(heights) - min(heights) < .03:
                    spots.append([x, z])
        self.assertGreaterEqual(len(spots), 2, 'no level ground for two pieces')
        for (kind, ident), spot in zip((('chair', 'starter-camp-chair'), ('shelf-unit', 'starter-camp-shelf')), spots):
            body = self.make(app, world, goal_chains.exact_furniture_recipe(kind, ident), spot, 'furniture-' + kind)
            self.assertTrue(body.get('rigid_parts_local'), f'{kind} is exact parts, not cells')
            self.assertLess(tilt_deg(body), 2.0, f'{kind} stands')


if __name__ == '__main__':
    unittest.main()
