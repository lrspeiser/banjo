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
import math

ROOT = Path(__file__).resolve().parents[1]


class Worker:
    def __init__(self, native, runtime, material='iron', block_size=.1, prepared_tool=None):
        self.closed = False
        self.expected_returncode = 0
        self.temp = tempfile.TemporaryDirectory()
        self.sequence = 0
        self.events = []
        scene = Path(self.temp.name)/'scene.json'
        scene.write_text(json.dumps({'bodies':[
            {'name':'floor','shape':'box','material':'iron','dimensions_m':[8,.2,8],
             'center_m':[0,-.1,0],'anchored':True},
            {'name':'test-block','shape':'box','material':material,'dimensions_m':[block_size]*3,
             'center_m':[0,.3,1],'anchored':False}]}),encoding='utf-8')
        cell='0.05';extra=[]
        if prepared_tool:
            width={'pick':.12,'shovel':.28,'hoe':.20,'unfamiliar':.16}[prepared_tool]
            scene.write_text(json.dumps({'terrain':{'surface':'columns','generate':{'kind':'flat',
                'nx':32,'nz':32,'cell_m':.1,'soil_m':.75,'sand_m':0,'discharge_m3_s':0}},'bodies':[
                {'name':'head','shape':'box','material':material,'dimensions_m':[width,.08,.04],'center_m':[.65,1.1,.2]},
                {'name':'handle','shape':'box','material':material,'dimensions_m':[.04,.32,.04],'center_m':[.65,1.29,.2]}]}),encoding='utf-8')
            ops=[{'op':'fix','a':'handle','b':'head','at':[.65,1.14,.2],'axis':[0,1,0],
                    'holds_tension_n':5000,'holds_shear_n':5000},
                {'op':'tool_point','body':'head','tip':[.65,1.06,.2],'pointing':[0,-1,0],
                    'width_m':width,'thickness_m':.04,'angle_deg':30,'length_m':.1,
                    'grip':[.65,1.4,.2],'grip_body':'handle'}, {'op':'snapshot'}]
            seeded=subprocess.run([str(native),'--scene',str(scene),'--cell','.02'],
                input=''.join(json.dumps(op)+'\n' for op in ops),capture_output=True,text=True,encoding='utf-8',timeout=30)
            if seeded.returncode:raise AssertionError(seeded.stderr)
            frames=[json.loads(line) for line in seeded.stdout.splitlines()]
            if len(frames)!=4 or not all(frame.get('ok') for frame in frames) or 'snapshot' not in frames[-1]:
                raise AssertionError('Native prepared-tool setup failed')
            snapshot=Path(self.temp.name)/'prepared-native.json'
            snapshot.write_text(json.dumps(frames[-1]['snapshot']),encoding='utf-8')
            cell='.02';extra=['--initial-snapshot',str(snapshot)]
        self.child = subprocess.Popen([str(runtime),'--native',str(native),'--scene',str(scene),
            '--cell',cell,'--world','test-world','--actors','alice,bob',*extra],
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

    def use_action(self,snapshot,target=(.65,.75,.2),actor='alice'):
        p=snapshot['native_players'][actor];w,x,y,z=p['orientation_wxyz']
        up=[2*(x*y-w*z),1-2*(x*x+z*z),2*(y*z+w*x)]
        eye=[a+.77*b for a,b in zip(p['position_m'],up)]
        d=[b-a for a,b in zip(eye,target)];n=sum(v*v for v in d)**.5
        return {'kind':'begin_tool_use','ray':{'from_m':eye,'direction':[v/n for v in d],'max_distance_m':2}}

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

    def worker(self, material='iron', block_size=.1, prepared_tool=None):
        worker=Worker(self.native,self.runtime,material,block_size,prepared_tool)
        self.addCleanup(worker.close)
        self.assertEqual(worker.ready['status'],'ready')
        return worker

    def test_prepared_tools_use_real_native_phases_and_retain_retry_results(self):
        for material in ['glass','oak','iron']:
            for family in ['pick','shovel','hoe','unfamiliar']:
                with self.subTest(material=material,family=family):
                    worker=self.worker(material,prepared_tool=family)
                    try:
                        self.assertEqual(worker.ready['native']['native_tool_use_version'],1)
                        worker.join(feet=(0,.75,0))
                        worker.request({'kind':'move','velocity_m_s':[0,0,0],'heading_rad':0,'jump':False})
                        pickup=worker.pickup(worker.inspect()['outcome']['snapshot'],instance='handle')
                        self.assertEqual(pickup['outcome']['status'],'pending')
                        self.assertEqual(worker.completion()['outcome']['status'],'applied')
                        action=worker.use_action(worker.inspect()['outcome']['snapshot'])
                        seq=worker.sequence+1
                        begin=worker.request(action,ident='use-command')
                        self.assertEqual(begin['outcome']['status'],'pending')
                        self.assertEqual(begin['outcome']['snapshot']['own_tool_use']['phase'],'preparing')
                        done=worker.completion()['outcome']
                        self.assertEqual(done['command_id'],'use-command')
                        self.assertEqual(done['status'],'applied',done)
                        actual=done['tool_use_result']
                        self.assertFalse(actual['active']);self.assertFalse(actual['contact_pending'])
                        self.assertEqual(actual['phase'],'finished')
                        self.assertGreater(sum(actual['loosened_m3'].values()),0)
                        self.assertEqual(done['snapshot']['own_hand']['holding'],'handle')
                        retry=worker.request(action,ident='use-command',sequence=seq)['outcome']
                        self.assertEqual(retry['status'],'already_applied')
                        self.assertEqual(retry['tool_use_result'],actual)
                        print('RUNTIME_TOOL_EVIDENCE '+json.dumps({'material':material,'family':family,
                            'native_file_sha256':worker.ready['native']['selected_file_sha256'],'dt_s':1/240,
                            'scene_cell_m':.02,'terrain_column_m':.1,'result':actual},sort_keys=True))
                    finally:worker.close()

    def test_native_use_cancel_is_scoped_and_leave_waits_for_measured_completion(self):
        worker=self.worker('iron',prepared_tool='pick')
        worker.join(feet=(0,.75,0));worker.join('bob',(-1,.75,0))
        self.assertEqual(worker.pickup(worker.inspect()['outcome']['snapshot'],instance='handle')['outcome']['status'],'pending')
        self.assertEqual(worker.completion()['outcome']['status'],'applied')
        action=worker.use_action(worker.inspect()['outcome']['snapshot'])
        self.assertEqual(worker.request(action,ident='use-command')['outcome']['status'],'pending')
        cancel={'kind':'cancel_tool_use','use_command_id':'use-command'}
        self.assertEqual(worker.request(cancel,actor='bob')['outcome']['reason'],'target_changed')
        self.assertIsNone(worker.inspect('bob')['outcome']['snapshot']['own_tool_use'])
        self.assertEqual(worker.request({'kind':'leave'})['outcome']['reason'],'action_in_progress')
        stopped=worker.request(cancel)['outcome']
        self.assertEqual(stopped['status'],'applied')
        self.assertEqual(stopped['snapshot']['own_tool_use']['phase'],'recovering')
        done=worker.completion()['outcome']
        self.assertEqual(done['reason'],'cancelled');self.assertFalse(done['tool_use_result']['active'])
        self.assertFalse(done['tool_use_result']['contact_pending'])
        self.assertEqual(worker.request({'kind':'leave'})['outcome']['status'],'applied')

    def test_drop_during_native_contact_waits_for_its_final_measured_report(self):
        worker=self.worker('iron',prepared_tool='pick');worker.join(feet=(0,.75,0))
        worker.request({'kind':'move','velocity_m_s':[0,0,0],'heading_rad':0,'jump':False})
        worker.pickup(worker.inspect()['outcome']['snapshot'],instance='handle')
        self.assertEqual(worker.completion()['outcome']['status'],'applied')
        self.assertEqual(worker.request(worker.use_action(worker.inspect()['outcome']['snapshot']),ident='use-command')['outcome']['status'],'pending')
        deadline=time.monotonic()+3
        buried=None
        while time.monotonic()<deadline:
            s=worker.inspect()['outcome']['snapshot']['own_tool_use']
            if s and s['active'] and s['contact_pending'] and s['contact_work_j']>0:
                buried=s;break
            if s and not s['active']:break
        self.assertIsNotNone(buried,'Ordinary worker journey never reached a measured open bite')
        dropped=worker.request({'kind':'drop'})['outcome'];self.assertEqual(dropped['status'],'applied')
        self.assertEqual(dropped['snapshot']['own_hand']['holding'],'')
        done=worker.completion()['outcome'];self.assertEqual(done['command_id'],'use-command')
        self.assertEqual(done['reason'],'grip_released');self.assertFalse(done['tool_use_result']['contact_pending'])
        self.assertGreater(done['tool_use_result']['contact_work_j'],0)

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

    def test_native_tool_preview_is_scoped_and_reports_unconfigured_tools(self):
        worker=self.worker()
        self.assertEqual(worker.ready['native']['tool_use_admission_version'],1)
        worker.join('alice');worker.join('bob',(2,.05,0))
        def preview(actor):
            snapshot=worker.inspect(actor)['outcome']['snapshot']
            player=snapshot['native_players'][actor]
            w,x,y,z=player['orientation_wxyz']
            up=[2*(x*y-w*z),1-2*(x*x+z*z),2*(y*z+w*x)]
            eye=[a+.77*b for a,b in zip(player['position_m'],up)]
            return worker.request({'kind':'preview_tool_use','ray':{
                'from_m':eye,'direction':[0,-1,0],'max_distance_m':2}},actor=actor)['outcome']
        seen=preview('alice')
        self.assertEqual(seen['status'],'observed')
        self.assertEqual(seen['snapshot']['own_tool_preview']['reason'],'not_holding')
        self.assertIsNone(seen['snapshot']['own_tool_preview']['target_m'])
        self.assertFalse(seen['snapshot']['own_tool_preview']['measured_yield'])
        taken=worker.pickup(worker.inspect()['outcome']['snapshot'])
        self.assertEqual(taken['outcome']['status'],'pending')
        self.assertEqual(worker.completion()['outcome']['status'],'applied')
        self.assertEqual(preview('alice')['snapshot']['own_tool_preview']['reason'],'unsupported_capability')
        self.assertEqual(preview('bob')['snapshot']['own_tool_preview']['actor'],'bob')
        self.assertIsNone(worker.inspect('alice')['outcome']['snapshot']['own_tool_preview'])

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

    def test_pickup_carries_actual_matter_with_native_actor_travel(self):
        for material in ('glass','oak','iron'):
            with self.subTest(material=material):
                worker=self.worker(material);worker.join()
                self.assertEqual(worker.ready['native']['native_carry_version'],1)
                time.sleep(.1)
                before=worker.inspect()['outcome']['snapshot']
                self.assertEqual(worker.pickup(before)['outcome']['status'],'pending')
                held=worker.completion()['outcome']
                self.assertEqual(held['status'],'applied')
                start=held['snapshot'];since=start['observed_simulation_s']
                deadline=time.monotonic()+8
                current=start
                while current['observed_simulation_s']-since<1.5 and time.monotonic()<deadline:
                    result=worker.request({'kind':'move','velocity_m_s':[1.5,0,0],'heading_rad':0,'jump':False})['outcome']
                    self.assertEqual(result['status'],'applied')
                    current=result['snapshot']
                    self.assertEqual(current['own_hand']['holding'],'test-block')
                    self.assertTrue(current['own_hand']['carrying_with_native_player'])
                    time.sleep(.08)
                self.assertGreaterEqual(current['observed_simulation_s']-since,1.5)
                self.assertEqual(worker.request({'kind':'move','velocity_m_s':[0,0,0],'heading_rad':0,'jump':False})['outcome']['status'],'applied')
                travel=current['native_players']['alice']['position_m'][0]-start['native_players']['alice']['position_m'][0]
                self.assertGreater(travel,1.5)
                old=next(b for b in start['bodies'] if b['name']=='test-block')
                new=next(b for b in current['bodies'] if b['name']=='test-block')
                self.assertGreater(new['position_m'][0]-old['position_m'][0],1.5)
                self.assertEqual(new['mass_kg'],old['mass_kg'])
                hand=current['own_hand']
                self.assertLess(math.dist(hand['grip_m'],hand['target_m']),.1)
                self.assertFalse(worker.request({'kind':'drop'})['outcome']['snapshot']['own_hand']['carrying_with_native_player'])
                worker.close()
    def test_matched_material_fixture_retains_native_mass_and_same_timestep(self):
        masses={}
        for material in ('glass','oak','iron'):
            with self.subTest(material=material):
                worker=self.worker(material,block_size=.2);worker.join()
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

    def test_overloaded_physical_carry_is_refused_before_custody_changes(self):
        worker=self.worker('iron',block_size=.2);worker.join()
        time.sleep(.1)
        result=worker.pickup(worker.inspect()['outcome']['snapshot'])['outcome']
        self.assertEqual(result['status'],'rejected')
        self.assertEqual(result['reason'],'insufficient_strength')
        self.assertEqual(result['snapshot']['own_hand']['holding'],'')


if __name__=='__main__':unittest.main()
