"""Native routed-rope lessons, including assembly and negative controls."""
import argparse
import copy
import pathlib
import sys
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import machine_game as game
import machine_world as world

parser=argparse.ArgumentParser();parser.add_argument('--engine',required=True)
args,remaining=parser.parse_known_args();ENGINE=pathlib.Path(args.engine).resolve()


class RoutedRopes(unittest.TestCase):
    def test_lessons_have_physical_routes_and_keep_the_original_goal_and_deadline(self):
        for identity,seconds in [('easy-thread',2),('easy-tackle',2),('tackle',8)]:
            level=game.level_by_id(identity)
            compiled=world.compile_spec(game.compose(level,level['solution'])[0])
            self.assertEqual(level['time_s'],seconds)
            self.assertEqual(len(compiled['strands']),1)
            self.assertFalse(any(j['kind']=='pulley' for j in compiled['joints']))
            self.assertTrue(any(j['kind']=='hinge' for j in compiled['joints']))
            if identity=='easy-tackle':self.assertEqual(level['goal']['station']['done_when'],{'rose_m':{'part':'crate','m':.25}})
            if identity=='tackle':self.assertEqual(level['goal']['station']['done_when']['in_zone'],
                {'part':'crate','at_m':[.4,.65,0],'size_m':[.3,.2,.3]})

    def test_new_routes_win_when_nudged_and_wrong_routes_or_weights_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            for identity in ('easy-thread','easy-tackle','tackle'):
                level=game.level_by_id(identity)
                result=game.trial(level,level['solution'],ENGINE,pathlib.Path(directory),runs=3)
                self.assertEqual(result['worked'],3,(identity,result))
                compiled=world.compile_spec(game.compose(level,level['wrong'])[0])
                result=world.rehearse(compiled,ENGINE,pathlib.Path(directory),seconds=level['time_s'],wall_limit_s=120)
                self.assertIsNone(result['error'],(identity,result['error']))
                self.assertFalse(result['stations'][0]['done'],identity)

    def test_rope_validation_refuses_buried_routes_unattached_ends_and_unknown_materials(self):
        level=game.level_by_id('easy-thread')
        spec=game.compose(level,level['solution'])[0]
        for mutate in (lambda s:s['strands'][0].update(density_kg_m3=1),
                       lambda s:s['strands'][0].update(a_body='missing'),
                       lambda s:s['strands'][0]['path_m'].__setitem__(0,[0,0,0]),
                       lambda s:s['strands'][0]['path_m'].__setitem__(12,[0,1.6,0])):
            bad=copy.deepcopy(spec);mutate(bad)
            with self.assertRaises(world.MachineRefused):world.compile_spec(bad)

    def test_quarter_turned_assembly_uses_the_same_native_load_transfer(self):
        level=copy.deepcopy(game.level_by_id('easy-tackle'))
        for part in level['machine']['parts']:
            x,y,z=part['at_m'];part['at_m']=[z,y,-x];part['turn_deg']=[0,90,0]
        for p in level['solution']:
            if 'x_m' in p:p['x_m'],p['z_m']=p['z_m'],-p['x_m'];p['yaw_deg']=90
            for key in ('at_m','at_b_m'):
                if key in p:x,y,z=p[key];p[key]=[z,y,-x]
        with tempfile.TemporaryDirectory() as directory:
            result=game.trial(level,level['solution'],ENGINE,pathlib.Path(directory),runs=1)
        self.assertEqual(result['worked'],1,result)

    def test_assembly_checks_inventory_and_reports_real_overlaps(self):
        level=game.level_by_id('easy-thread')
        good=game.assembly_ghost(level,level['solution'],0)
        self.assertTrue(good['fits'],good['problems'])
        self.assertEqual(len(good['strands']),1)
        with self.assertRaises(game.LevelRefused):game.assembly_ghost(level,[{'piece':'battery'}],0)


if __name__=='__main__':unittest.main(argv=[sys.argv[0],*remaining],verbosity=2)
