"""The rover on harder ground: trenches, mounds, shorelines and steep slopes.

On both generated valleys, the starter rover is given ordinary orders -- the
plain words a person types to it -- across ground made harder by ordinary
edits (a trench dug across its haul route, a mound heaped on it) and towards
places it may not be able to reach (the river's edge, a steep hillside).

Whatever it does, it must stay safe and say so:
  - it never ends tipped over (more than 35 degrees off upright);
  - it never ends standing in water deeper than its wheels' half-height;
  - every order ends within its time, either done or stopped with a reason
    it gives when asked, and after an order it could not finish it goes back
    to its rounds when told to go on.

What it actually achieved on each map is written to build/rover-routes so the
route families can be widened from evidence, not assumption.

    BANJO_LIVE_ENGINE=build/rel/Release/banjo_live_world_run.exe python tests/rover_route_tests.py -v
"""
import json
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
TIPPED_DEG = 35.0
WET_M = 0.12


@unittest.skipUnless(ENGINE and Path(ENGINE).is_file(), 'BANJO_LIVE_ENGINE is required')
class RoverRoutes(unittest.TestCase):
    setUp = agents.AutonomousGuests.setUp
    start = agents.AutonomousGuests.start
    stop = agents.AutonomousGuests.stop
    tearDown = agents.AutonomousGuests.tearDown
    get = hub.NamedWorlds.get
    post = hub.NamedWorlds.post
    join = hub.NamedWorlds.join

    # -- the world and the rover -------------------------------------------
    def open_map(self, terrain):
        world = self.post('/api/worlds', {'name': f'Routes {terrain}',
                                          'seeds': {'terrain': terrain, 'goods': 851269742}})['id']
        self.players = {world: self.join(world, 'Driver')}
        self.post('/api/world/open', {}, world)
        self.world, self.room_app = world, self.app.hub.get(world)
        programs = self.room_app.room.spec['machines']['programs']
        self.rover = next(p['name'] for p in programs if p.get('kind') == 'roam')

    def act(self, **body):
        return self.post('/api/live/act', {'session': self.room_app.live.session.id, **body}, self.world)

    def survey(self, x, z):
        return self.act(op='survey', at=[x, z])['survey']

    def body(self):
        state = self.room_app.live.session.state
        program = next(p for p in state['machines']['programs'] if p['name'] == self.rover)
        return next(b for b in state['bodies'] if b['name'] == program['body']), program

    def condition(self):
        body, program = self.body()
        w, x, y, z = body.get('orientation_wxyz') or [1, 0, 0, 0]
        up_y = 1 - 2 * (x * x + z * z)
        at = body['position_m']
        water = float((self.survey(at[0], at[2]).get('water') or {}).get('depth_m') or 0)
        return {'at_m': [round(v, 3) for v in at], 'tilt_deg': round(math.degrees(math.acos(max(-1, min(1, up_y)))), 1),
                'water_m': round(water, 3), 'power': bool(program.get('power')), 'asked': program.get('asked'),
                'routine': self.room_app.brains.brains[self.rover].routine.summary()}

    def talk(self, said=None, order=None, person=None):
        body = {'session': self.room_app.live.session.id, 'program': self.rover}
        if order: body['order'] = order
        else: body['said'] = said
        if person: body['person'] = person
        return self.post('/api/world/rover/talk', body, self.world)

    def person_at(self, x, z):
        floor = self.survey(x, z)['ground_m']
        return {'standing_m': [x, floor, z], 'eyes_m': [x, floor + 1.62, z], 'facing': [0, 0, -1]}

    def let_run(self, seconds, done=lambda: False):
        self.trace = []
        for i in range(int(seconds / .5)):
            self.room_app.clock._tick(.5)
            if i % 4 == 0:
                c = self.condition()
                self.trace.append([c['at_m'], c['water_m'], (c['asked'] or {}).get('doing'),
                                   self.room_app.brains.brains[self.rover].routine.summary()['notes'][-1:]])
            if done(): return True
        return False

    def safe(self, label):
        c = self.condition()
        self.assertLess(c['tilt_deg'], TIPPED_DEG, f'{label}: the rover tipped over: {c}')
        self.assertLess(c['water_m'], WET_M, f'{label}: the rover is standing in water: {c}')
        return c

    # -- ground for the scenarios -------------------------------------------
    def haul(self):
        places = self.room_app.brains.brains[self.rover].routine.places
        return places['vein'], places['smelter intake']

    def steepest_near(self, centre, radius=10.0):
        best = None
        for i in range(-10, 11):
            for j in range(-10, 11):
                x, z = centre[0] + i * radius / 10, centre[1] + j * radius / 10
                a, b = self.survey(x - .5, z), self.survey(x + .5, z)
                c, d = self.survey(x, z - .5), self.survey(x, z + .5)
                if any('ground_m' not in s or (s.get('water') or {}).get('depth_m', 0) > .01 for s in (a, b, c, d)): continue
                grade = math.degrees(math.atan(math.hypot(b['ground_m'] - a['ground_m'], d['ground_m'] - c['ground_m'])))
                if best is None or grade > best[0]: best = (grade, x, z)
        return best

    def shore_near(self, centre, radius=10.0):
        best = None
        for i in range(-20, 21):
            for j in range(-20, 21):
                x, z = centre[0] + i * radius / 20, centre[1] + j * radius / 20
                here = self.survey(x, z)
                if 'ground_m' not in here or (here.get('water') or {}).get('depth_m', 0) > .005: continue
                wet = any((self.survey(x + dx, z + dz).get('water') or {}).get('depth_m', 0) > .05
                          for dx, dz in ((.8, 0), (-.8, 0), (0, .8), (0, -.8)))
                if wet:
                    d = math.dist((x, z), centre)
                    if best is None or d < best[0]: best = (d, x, z)
        return best

    # -- the test ------------------------------------------------------------
    def test_rover_routes_stay_safe_and_end_on_both_valleys(self):
        out = ROOT / 'build/rover-routes'
        out.mkdir(parents=True, exist_ok=True)
        for terrain in tuple(int(t) for t in os.environ.get('ROVER_TERRAINS', '7,4').split(',')):
            with self.subTest(terrain=terrain):
                self.open_map(terrain)
                report = {'terrain': terrain, 'rover': self.rover, 'start': self.safe('start'), 'scenarios': {}}
                vein, intake = self.haul()
                goods = self.room_app.brains.goods
                pile = lambda: float(goods.by_name('smelter intake').get('holds', {}).get('copper ore', 0))
                mid = [(vein[0] + intake[0]) / 2, (vein[1] + intake[1]) / 2]
                along = [intake[0] - vein[0], intake[1] - vein[1]]
                n = math.hypot(*along) or 1
                across = [-along[1] / n, along[0] / n]

                # 1. A trench across the haul route, then the ordinary haul.
                self.act(op='dig', **{'from': [mid[0] - 2.5 * across[0], mid[1] - 2.5 * across[1]],
                                      'to': [mid[0] + 2.5 * across[0], mid[1] + 2.5 * across[1]]},
                         width_m=1.2, depth_m=.8)
                before = pile()
                self.assertTrue(self.talk(order='dig at vein and dump it at smelter intake')['ordered'])
                delivered = self.let_run(180, lambda: pile() > before)
                report['scenarios']['trench'] = {'delivered': delivered, 'end': self.safe('trench'),
                                                 'says': self.talk(said='why')['reply']}
                self.talk(said='cancel that')

                # 2. A mound of the trench's spoil heaped on the route.
                carried = self.room_app.live.session.send(op='survey', at=mid).get('carried') or {}
                sand, soil = float(carried.get('sand_m3') or 0), float(carried.get('soil_m3') or 0)
                if sand + soil > .05:
                    self.act(op='deposit', at=[mid[0] + .3 * along[0] / n, mid[1] + .3 * along[1] / n],
                             radius_m=1.0, sand_m3=sand, soil_m3=soil)
                before = pile()
                self.assertTrue(self.talk(order='dig at vein and dump it at smelter intake')['ordered'])
                delivered = self.let_run(180, lambda: pile() > before)
                report['scenarios']['mound'] = {'heaped_m3': round(sand + soil, 3), 'delivered': delivered,
                                                'end': self.safe('mound'), 'says': self.talk(said='why')['reply']}
                self.talk(said='cancel that')

                # 3. Called to the river's edge.
                shore = self.shore_near(self.condition()['at_m'][::2])
                if shore:
                    person = self.person_at(shore[1], shore[2])
                    self.talk(said='come here', person=person)
                    arrived = self.let_run(60, lambda: math.dist(self.condition()['at_m'][::2], (shore[1], shore[2])) < 2)
                    report['scenarios']['shore'] = {'target': shore[1:], 'arrived': arrived, 'end': self.safe('shore'),
                                                    'says': self.talk(said='why')['reply']}
                    self.talk(said='go on', person=person)

                # 4. Called up the steepest slope near it, then told to go on.
                steep = self.steepest_near(self.condition()['at_m'][::2])
                person = self.person_at(steep[1], steep[2])
                self.talk(said='come here', person=person)
                arrived = self.let_run(60, lambda: math.dist(self.condition()['at_m'][::2], (steep[1], steep[2])) < 2)
                (out / f'trace-slope-{terrain}.json').write_text(json.dumps(self.trace, indent=1), encoding='utf-8')
                end = self.safe('slope')
                report['scenarios']['slope'] = {'grade_deg': round(steep[0], 1), 'target': steep[1:],
                                                'arrived': arrived, 'end': end,
                                                'says': self.talk(said='why')['reply']}
                # 5. Recovery: told to go on, it returns to its rounds and moves.
                self.talk(said='go on', person=person)
                was = self.condition()['at_m']
                routine = self.room_app.brains.brains[self.rover].routine
                state = lambda: (routine.summary()['step'], round(routine.kg, 3), list(routine.notes)[-1:])
                before = state()
                # Back to its rounds: it drives on, or its routine does its next
                # step where it is (digging at a vein it had already reached).
                moved = self.let_run(30, lambda: math.dist(self.condition()['at_m'], was) > .5
                                     or (state() != before and 'blocked' not in str(state()[2])))
                report['scenarios']['recovery'] = {'moved': moved, 'end': self.condition(),
                                                   'says': self.talk(said='what are you doing')['reply']}
                (out / f'terrain-{terrain}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                self.safe('recovery')
                self.assertTrue(moved, f'terrain {terrain}: after go on the rover did not resume its rounds')


if __name__ == '__main__':
    unittest.main()
