"""Required integration gate: Rust world owner -> actual native process.

No skip/fake-native fallback. The native fixture exercises existing rigid body
and locomotion behavior, not fracture-law or excavation qualification.
"""
import hashlib
import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Worker:
    def __init__(self, native, runtime, material='iron'):
        self.closed = False
        self.expected_returncode = 0
        self.temp = tempfile.TemporaryDirectory()
        self.sequence = 0
        self.events = []
        scene = Path(self.temp.name)/'scene.json'
        scene.write_text(json.dumps({'bodies':[
            {'name':'floor','shape':'box','material':'iron','dimensions_m':[8,.2,8],
             'center_m':[0,-.1,0],'anchored':True},
            {'name':'test-block','shape':'box','material':material,'dimensions_m':[.2,.2,.2],
             'center_m':[0,.3,1],'anchored':False}]}),encoding='utf-8')
        self.child = subprocess.Popen([str(runtime),'--native',str(native),'--scene',str(scene),
            '--cell','0.05','--world','test-world','--actors','alice,bob'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        self.frames = queue.Queue()
        def reader():
            try:
                for line in self.child.stdout:self.frames.put(json.loads(line))
            finally:self.frames.put(None)
        self.reader = threading.Thread(target=reader,daemon=True)
        self.reader.start()
        try:self.ready = self.receive()
        except BaseException:self.close();raise

    def receive(self):
        result=self.frames.get(timeout=15)
        if result is None:raise AssertionError('Worker ended before its response')
        return result

    def request(self, action, *, actor='alice', principal=None, host=False, ident=None, sequence=None):
        self.sequence += 1
        command={'schema':'banjo.command.v1','world_id':'test-world','actor_id':actor,
            'command_id':ident or f'request-{self.sequence}','input_sequence':sequence or self.sequence,
            'expected_revision':None,'payload':action}
        message={'principal':principal or actor,'host_action':host,'command':command}
        self.raw(json.dumps(message))
        while True:
            frame=self.receive()
            if frame['schema']=='banjo.worker-completion.v1':self.events.append(frame)
            else:return frame

    def raw(self,line):
        self.child.stdin.write(line+'\n');self.child.stdin.flush()

    def join(self,actor='alice',feet=(0,.05,0)):
        return self.request({'kind':'join','feet_m':feet},actor=actor,host=True)['outcome']

    def inspect(self,actor='alice'):
        return self.request({'kind':'inspect'},actor=actor)

    def pickup(self, snapshot, actor='alice', instance='test-block'):
        body=next(b for b in snapshot['bodies'] if b['name']==instance)
        player=snapshot['native_players'][actor]
        w,x,y,z=player['orientation_wxyz']
        up=[2*(x*y-w*z),1-2*(x*x+z*z),2*(y*z+w*x)]
        eye=[a+.77*b for a,b in zip(player['position_m'],up)]
        direction=[b-a for a,b in zip(eye,body['position_m'])]
        norm=sum(v*v for v in direction)**.5
        return self.request({'kind':'pickup','instance_id':instance,'ray':{
            'from_m':eye,'direction':[v/norm for v in direction],'max_distance_m':2}},actor=actor)

    def completion(self):
        if self.events:return self.events.pop(0)
        return self.receive()

    def close(self):
        if self.closed:return
        self.closed = True
        if self.child.poll() is None:
            self.child.stdin.close()
            try:self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill();self.child.wait(timeout=5)
        self.reader.join(timeout=5)
        self.stderr=self.child.stderr.read()
        for stream in [self.child.stdin,self.child.stdout,self.child.stderr]:stream.close()
        self.temp.cleanup()
        if self.child.returncode != self.expected_returncode:raise AssertionError(f'Worker exited {self.child.returncode}: {self.stderr}')


def alive(pid):
    if os.name == 'nt':
        handle=ctypes.windll.kernel32.OpenProcess(0x00100000,False,pid)
        if not handle:return False
        try:return ctypes.windll.kernel32.WaitForSingleObject(handle,0)==258
        finally:ctypes.windll.kernel32.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False


class NativeOwner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native=Path(os.environ.get('BANJO_LIVE_ENGINE','missing-required-native'))
        cls.runtime=Path(os.environ.get('BANJO_RUNTIME_ENGINE','missing-required-runtime'))
        if not cls.native.is_file() or not cls.runtime.is_file():
            raise AssertionError('Build both native and Rust targets and supply BANJO_LIVE_ENGINE/BANJO_RUNTIME_ENGINE; this gate cannot skip')

    def worker(self, material='iron'):
        worker=Worker(self.native,self.runtime,material)
        self.addCleanup(worker.close)
        self.assertEqual(worker.ready['status'],'ready')
        return worker

    def test_owned_clock_runs_without_client_steps_and_identity_matches_file(self):
        worker=self.worker()
        self.assertEqual(worker.ready['native']['selected_file_sha256'],hashlib.sha256(self.native.read_bytes()).hexdigest())
        self.assertEqual(worker.join()['status'],'applied')
        before=worker.inspect()
        time.sleep(.12)
        after=worker.inspect()
        self.assertGreater(after['clock']['tick'],before['clock']['tick'])
        self.assertAlmostEqual(after['clock']['simulation_s'],after['clock']['tick']/240,places=7)
        self.assertEqual(after['clock']['dt_s'],1/240)
        self.assertEqual(after['clock']['steps_per_batch'],4)

    def test_shutdown_reaps_owned_native_and_preserves_unrelated_process(self):
        unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
        def close_unrelated():
            if unrelated.poll() is None:unrelated.terminate()
            unrelated.wait(timeout=5)
        self.addCleanup(close_unrelated)
        worker=self.worker();native_pid=worker.ready['native']['pid']
        self.assertTrue(alive(native_pid));worker.close()
        self.assertFalse(alive(native_pid));self.assertIsNone(unrelated.poll())

    def test_native_exit_faults_worker_without_fake_state_fallback(self):
        worker=self.worker();worker.join()
        worker.expected_returncode=1
        native_pid=worker.ready['native']['pid']
        self.assertTrue(alive(native_pid))
        os.kill(native_pid,15)  # Only the child identified by this worker.
        self.assertEqual(worker.child.wait(timeout=15),1)
        worker.close()
        self.assertIn('World clock fault: KernelUnavailable',worker.stderr)

    def test_independent_players_walk_under_native_control(self):
        worker=self.worker()
        worker.join('alice',(-1,.05,0));worker.join('bob',(1,.05,0))
        time.sleep(.15)
        initial=worker.inspect()['outcome']['snapshot']['native_players']
        a=worker.request({'kind':'move','velocity_m_s':[-3,0,0],'heading_rad':0,'jump':False},actor='alice')
        b=worker.request({'kind':'move','velocity_m_s':[3,0,0],'heading_rad':0,'jump':False},actor='bob')
        self.assertEqual(a['outcome']['status'],'applied');self.assertEqual(b['outcome']['status'],'applied')
        time.sleep(.2)
        current=worker.inspect()['outcome']['snapshot']['native_players']
        self.assertLess(current['alice']['position_m'][0],initial['alice']['position_m'][0]-.05)
        self.assertGreater(current['bob']['position_m'][0],initial['bob']['position_m'][0]+.05)
        self.assertNotEqual(current['alice']['body_id'],current['bob']['body_id'])
        self.assertEqual(current['alice']['mass_kg'],70)

    def test_retry_conflict_scope_and_departure_have_native_outcomes(self):
        worker=self.worker()
        first=worker.request({'kind':'join','feet_m':[0,.05,0]},host=True,ident='join-once',sequence=1)['outcome']
        again=worker.request({'kind':'join','feet_m':[0,.05,0]},host=True,ident='join-once',sequence=1)['outcome']
        self.assertEqual(again['status'],'already_applied');self.assertEqual(again['revision'],first['revision'])
        conflict=worker.request({'kind':'inspect'},ident='join-once')['outcome']
        self.assertEqual(conflict['reason'],'conflicting_command_id')
        denied=worker.request({'kind':'inspect'},principal='bob')['outcome']
        self.assertEqual(denied['reason'],'wrong_actor');self.assertIsNone(denied['snapshot'])
        dropped=worker.request({'kind':'drop'})['outcome']
        self.assertEqual(dropped['status'],'applied');self.assertEqual(dropped['snapshot']['own_hand']['holding'],'')
        departed=worker.request({'kind':'leave'})['outcome']
        self.assertEqual(departed['status'],'applied');self.assertNotIn('alice',departed['snapshot']['native_players'])

    def test_invalid_frames_cannot_step_or_poison_following_input(self):
        worker=self.worker();worker.join()
        invalid=worker.request({'kind':'step','dt':10,'n':10000})
        self.assertEqual(invalid['reason'],'invalid_input')
        worker.raw('x'*20000)
        self.assertEqual(worker.receive()['reason'],'invalid_input')
        self.assertEqual(worker.inspect()['outcome']['status'],'observed')
        self.assertIsNone(worker.inspect()['clock']['fault'])

    def test_wrong_ray_is_an_explicit_refusal_not_false_success(self):
        worker=self.worker();worker.join()
        result=worker.request({'kind':'pickup','instance_id':'test-block','ray':{
            'from_m':[0,1.67,0],'direction':[0,0,1],'max_distance_m':2}})['outcome']
        self.assertEqual(result['status'],'rejected');self.assertEqual(result['reason'],'target_changed')
        self.assertEqual(result['snapshot']['own_hand']['holding'],'')

    def test_generic_pickup_is_pending_until_native_batch_then_drop_is_confirmed(self):
        for material in ('glass','oak','iron'):
            with self.subTest(material=material):
                worker=self.worker(material);worker.join()
                time.sleep(.1)
                snapshot=worker.inspect()['outcome']['snapshot']
                pending=worker.pickup(snapshot)['outcome']
                self.assertEqual(pending['status'],'pending')
                complete=worker.completion()['outcome']
                self.assertEqual(complete['command_id'],pending['command_id'])
                self.assertEqual(complete['status'],'applied')
                self.assertGreater(complete['tick'],pending['tick'])
                self.assertEqual(complete['snapshot']['own_hand']['holding'],'test-block')
                time.sleep(.05)
                self.assertEqual(worker.inspect()['outcome']['snapshot']['own_hand']['holding'],'test-block')
                drop=worker.request({'kind':'drop'})['outcome']
                self.assertEqual(drop['status'],'applied');self.assertEqual(drop['snapshot']['own_hand']['holding'],'')
                worker.close()

    def test_two_players_cannot_take_each_others_held_object_but_can_retrieve_after_drop(self):
        worker=self.worker();worker.join();worker.join('bob',(.5,.05,0))
        time.sleep(.1)
        pending=worker.pickup(worker.inspect()['outcome']['snapshot'])['outcome']
        self.assertEqual(pending['status'],'pending')
        self.assertEqual(worker.completion()['outcome']['status'],'applied')
        other=worker.inspect('bob')['outcome']['snapshot']
        blocked=worker.pickup(other,'bob')['outcome']
        self.assertEqual(blocked['reason'],'held_by_another_actor')
        self.assertEqual(blocked['snapshot']['own_hand']['holding'],'')
        self.assertEqual(worker.request({'kind':'drop'})['outcome']['status'],'applied')
        other=worker.inspect('bob')['outcome']['snapshot']
        self.assertEqual(worker.pickup(other,'bob')['outcome']['status'],'pending')
        self.assertEqual(worker.completion()['outcome']['status'],'applied')

    def test_matched_material_fixture_retains_native_mass_and_same_timestep(self):
        masses={}
        for material in ('glass','oak','iron'):
            with self.subTest(material=material):
                worker=self.worker(material);worker.join()
                observed=worker.inspect()
                block=next(b for b in observed['outcome']['snapshot']['bodies'] if b['name']=='test-block')
                self.assertEqual(block['material'],material)
                self.assertEqual(observed['clock']['dt_s'],1/240)
                self.assertEqual(block['dimensions_m'],[.2,.2,.2])
                masses[material]=block['mass_kg']
                worker.close()
                # close is idempotent for addCleanup below.
        self.assertLess(masses['oak'],masses['glass']);self.assertLess(masses['glass'],masses['iron'])
        print('Matched fixture masses kg:',json.dumps(masses,sort_keys=True))


if __name__=='__main__':unittest.main()
