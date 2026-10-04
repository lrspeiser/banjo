"""Can every recipe really be made: the audit on both generated valleys.

Every starter recipe a new player is pointed at must pass on both valleys:
its shape compiles, every material has a non-Market source in the world,
every process on the way is powered, it does something, and a run-out source
has another. The full book is written to build/recipe-audit so the catalog's
gaps are a list to work through, not a surprise.

    BANJO_LIVE_ENGINE=build/rel/Release/banjo_live_world_run.exe python tests/recipe_audit_tests.py -v
"""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'playground'), str(ROOT)]
import ai_player_tests as agents
import world_hub_tests as hub

STARTERS = ('Personal field pick', 'Camp stool', 'Work table', 'Camp light', 'Camp solar panel',
            # Catalog furniture built from exact parts, recommended over the cell versions.
            'Camp chair', 'Camp shelf')
ENGINE = os.environ.get('BANJO_LIVE_ENGINE')


@unittest.skipUnless(ENGINE and Path(ENGINE).is_file(), 'BANJO_LIVE_ENGINE is required')
class RecipeAudit(unittest.TestCase):
    setUp = agents.AutonomousGuests.setUp
    start = agents.AutonomousGuests.start
    stop = agents.AutonomousGuests.stop
    tearDown = agents.AutonomousGuests.tearDown
    get = hub.NamedWorlds.get
    post = hub.NamedWorlds.post
    join = hub.NamedWorlds.join

    def test_every_starter_recipe_can_really_be_made_on_both_valleys(self):
        import recipe_audit
        out = ROOT / 'build/recipe-audit'
        out.mkdir(parents=True, exist_ok=True)
        failed = {}
        for terrain, goods in ((7, 851269742), (4, 1)):
            world = self.post('/api/worlds', {'name': 'Audit', 'seeds': {'terrain': terrain, 'goods': goods}})['id']
            self.players = {world: self.join(world, 'Auditor')}
            self.post('/api/world/open', {}, world)
            rows = recipe_audit.audit(self.app.hub.get(world))
            (out / f'terrain-{terrain}.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
            by_name = {r['name']: r for r in rows}
            for name in STARTERS:
                self.assertIn(name, by_name, f'{name} is missing from the Recipes book')
                if not by_name[name]['ok']:
                    failed[f'{name} (terrain {terrain})'] = by_name[name]['issues']
        self.assertEqual({}, failed)


if __name__ == '__main__':
    unittest.main()
