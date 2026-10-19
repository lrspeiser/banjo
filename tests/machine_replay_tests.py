"""Prepared playback preserves native frames, identity, topology and goals."""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import machine_replay as replay
import machine_game
import machine_world

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--engine', type=Path)
args, rest = parser.parse_known_args()


def frame(seq, t, bodies, **extra):
    return json.dumps({**dict(ok=True,seq=seq,t=t,bodies=bodies,readouts={'stations':[]},events=[],
        removed=[],playing=False,full=seq==1,pace={'behind_s':0},runtime={}),**extra}).encode()


class Prepared(unittest.TestCase):
    def test_cached_run_is_scoped_to_owner_engine_setup_and_age(self):
        cache=replay.PreparedRuns();compiled={'parts':[]};frames=[b'frame']
        token=cache.keep('visitor','page',compiled,frames,'engine')
        self.assertIsNone(cache.take(token,'other','page',compiled,'engine'))
        self.assertIsNone(cache.take(token,'visitor','other-page',compiled,'engine'))
        self.assertEqual(cache.take(token,'visitor','page',compiled,'engine'),frames)
        self.assertIsNone(cache.take(token,'visitor','page',compiled,'engine'))
        for changed,engine in (({'parts':[1]},'engine'),(compiled,'new-engine')):
            token=cache.keep('visitor','page',compiled,frames,'engine')
            self.assertIsNone(cache.take(token,'visitor','page',changed,engine))
        with patch('machine_replay.time.monotonic',return_value=0):
            token=cache.keep('visitor','page',compiled,frames,'engine')
        with patch('machine_replay.time.monotonic',return_value=301):
            self.assertIsNone(cache.take(token,'visitor','page',compiled,'engine'))

    def test_play_pause_and_topology_use_only_recorded_measurements(self):
        frames=[frame(1,0,[dict(name='board',position_m=[0,1,0],cells_local_m=[[0,0,0]])]),
                frame(2,.1,[dict(name='board',position_m=[0,.8,0])]),
                frame(3,.2,[dict(name='fragment',position_m=[0,.5,0],cells_local_m=[[0,0,0]])],removed=['board'])]
        with patch('machine_replay.time.monotonic',return_value=0):
            session=replay.ReplaySession({},frames);session.play(True)
        with patch('machine_replay.time.monotonic',return_value=.15):
            result=session.frame(1,0)
            self.assertEqual(result['t'],.1)
            self.assertNotIn('cells_local_m',result['bodies'][0])
            session.play(False)
        with patch('machine_replay.time.monotonic',return_value=10):
            self.assertEqual(session.frame(0,0)['t'],.1)
            self.assertEqual(session.frame(0,0)['bodies'][0]['cells_local_m'],[[0,0,0]])
            session.play(True)
        with patch('machine_replay.time.monotonic',return_value=11):
            result=session.frame(0,0)
            self.assertEqual([b['name'] for b in result['bodies']],['fragment'])
            self.assertFalse(result['playing'])
            self.assertEqual(result['removed'],['board'])

    def test_manual_and_settling_setups_remain_live(self):
        base={'joints':[],'electrical':{},'circuits':[]}
        self.assertTrue(replay.eligible({},base))
        for level,change in (({'free':True},{}),({'release_to_start':True},{}),({},dict(spouts=[{}])),
                             ({},dict(ropes=[{}])),({},dict(electrical={'wires':[{}]})),
                             ({},dict(electrical={'devices':[{'handle':{'part':'switch'}}]})),
                             ({},dict(joints=[{'name':'spring restraint'}]))):
            self.assertFalse(replay.eligible(level,{**base,**change}))

    def test_large_playback_jump_keeps_the_first_measured_goal_ledger(self):
        def readings(done,given):
            return dict(stations=[dict(done=done,at_s=.3 if done else None)],
                        machines=dict(batteries=[dict(name='cell',given_j=given)]))
        frames=[frame(1,0,[],readouts=readings(False,0)),
                frame(2,.3,[],readouts=readings(True,.9)),
                frame(3,2,[],readouts=readings(True,6))]
        with patch('machine_replay.time.monotonic',return_value=0):
            session=replay.ReplaySession({},frames)
            self.assertIsNone(session.goal_snapshot)
            session.play(True)
        with patch('machine_replay.time.monotonic',return_value=10):
            session.frame(0,0)
        self.assertEqual(session.t,2)
        self.assertEqual(session.readouts['machines']['batteries'][0]['given_j'],6)
        self.assertEqual(session.goal_snapshot['t'],.3)
        self.assertEqual(session.goal_snapshot['readouts']['machines']['batteries'][0]['given_j'],.9)
        session.readouts['machines']['batteries'][0]['given_j']=9
        self.assertEqual(session.goal_snapshot['readouts']['machines']['batteries'][0]['given_j'],.9)

    @unittest.skipUnless(args.engine and args.engine.is_file(),'native engine required')
    def test_native_gap_recording_matches_goal_and_energy_without_rerunning(self):
        level=machine_game.level_by_id('gap');job=machine_world.PreviewJob()
        with tempfile.TemporaryDirectory() as logs:
            result=machine_game.preview(level,level['solution'],args.engine,Path(logs),preview_job=job)
        self.assertTrue(result['complete']);self.assertIsNotNone(result['goal_at_s'])
        self.assertTrue(job.replay_frames)
        with patch('machine_replay.time.monotonic',return_value=0):
            session=replay.ReplaySession(job.replay_compiled,job.replay_frames);session.play(True)
        with patch('machine_replay.time.monotonic',return_value=100):
            final=session.frame(0,0)
        self.assertAlmostEqual(final['readouts']['stations'][0]['at_s'],result['goal_at_s'],places=9)
        self.assertTrue(final['readouts']['stations'][0]['done'])
        self.assertIsNotNone(session.goal_snapshot)
        self.assertEqual(session.goal_snapshot['readouts']['stations'][0]['at_s'],result['goal_at_s'])
        score=machine_game.energy_of(session.compiled,session.readouts,session.t)
        self.assertEqual(score['run']['j'],0)
        self.assertGreater(score['pieces_j'],0)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]]+rest,verbosity=2)
