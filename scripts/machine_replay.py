"""Bounded playback of native measurements for an unchanged automatic setup.

The engine produces every frame. This module only records and times their
delivery; it never predicts a pose, changes a goal, or operates a control.
"""
import copy
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict

RUN_BYTES = 16 * 1024 * 1024
CACHE_BYTES = 64 * 1024 * 1024


def eligible(level, compiled):
    graph = compiled.get('electrical') or {}
    return not (level.get('free') or level.get('release_to_start') or compiled.get('spouts') or
                compiled.get('ropes') or compiled.get('strands') or graph.get('wires') or graph.get('power_cables') or
                any(c.get('leads') for c in compiled.get('circuits', [])) or
                any(d.get('handle') for d in graph.get('devices', [])) or
                any(j['name'].endswith(' restraint') for j in compiled.get('joints', [])))


def signature(compiled):
    return hashlib.sha256(json.dumps(compiled, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Recorder:
    def __init__(self):
        self.frames, self.size, self.after, self.t, self.refused = [], 0, 0, -1, False

    def capture(self, session, force=False):
        if self.refused or not force and session.t - self.t < .05 - 1e-9:
            return
        frame = session.frame(self.after, 0)
        raw = json.dumps(frame, separators=(',', ':'), allow_nan=False).encode()
        if self.size + len(raw) > RUN_BYTES:
            self.frames.clear()
            self.refused = True
            return
        self.frames.append(raw)
        self.size += len(raw)
        self.after, self.t = frame['seq'], session.t


class PreparedRuns:
    """One result per visitor/page, five minutes, at most 64 MiB total."""
    def __init__(self):
        self.rows = OrderedDict()
        self.lock = threading.Lock()

    def keep(self, visitor, owner, compiled, frames, engine):
        if not frames:
            return None
        with self.lock:
            now = time.monotonic()
            for key, row in list(self.rows.items()):
                if now-row['at'] > 300 or (row['visitor'], row['owner']) == (visitor, owner):
                    del self.rows[key]
            token = str(uuid.uuid4())
            self.rows[token] = dict(visitor=visitor, owner=owner, signature=signature(compiled),
                                    frames=frames, engine=engine, at=now, size=sum(map(len, frames)))
            while sum(r['size'] for r in self.rows.values()) > CACHE_BYTES:
                self.rows.popitem(last=False)
            return token if token in self.rows else None

    def take(self, token, visitor, owner, compiled, engine):
        if not isinstance(token, str):
            return None
        with self.lock:
            row = self.rows.get(token)
            if not row or row['visitor'] != visitor or row['owner'] != owner:
                return None
            del self.rows[token]
            if time.monotonic()-row['at'] > 300 or row['engine'] != engine or row['signature'] != signature(compiled):
                return None
            return row['frames']


class ReplaySession:
    """The normal session interface backed by a completed native rehearsal."""
    def __init__(self, compiled, frames):
        self.compiled, self.frames = compiled, frames
        self.id = str(uuid.uuid4())
        self.last_used = self.last_action = time.monotonic()
        self.playing, self.closed, self._test_pulled = False, False, False
        self.speed, self.t, self.cursor, self.index = 1, 0, 0, -1
        self.bodies, self.removed, self.events, self.readouts = {}, {}, [], {}
        self.lock = threading.RLock()
        self.duration = json.loads(frames[-1])['t']
        self._apply(json.loads(frames[0]))
        self.index = 0

    def _apply(self, frame):
        self.latest = frame
        self.t = frame['t']
        for name in frame.get('removed', []):
            self.bodies.pop(name, None)
            self.removed[name] = frame['seq']
        for body in frame['bodies']:
            old = self.bodies.get(body['name'], {})
            self.bodies[body['name']] = {**old, **body, '_seq': frame['seq'],
                '_cells_seq': frame['seq'] if 'cells_local_m' in body else old.get('_cells_seq', 0)}
        self.events.extend(frame.get('events', []))
        self.readouts = frame['readouts']

    def _advance(self):
        now = time.monotonic()
        if self.playing:
            self.cursor = min(self.duration, self.cursor + (now-self.at)*self.speed)
        self.at = now
        while self.index+1 < len(self.frames):
            frame = json.loads(self.frames[self.index+1])
            if frame['t'] > self.cursor + 1e-8:
                break
            self._apply(frame)
            self.index += 1
        if self.cursor >= self.duration:
            self.playing = False

    def play(self, running, speed=None):
        with self.lock:
            if speed is not None:
                if type(speed) not in (int, float) or not .1 <= speed <= 4:
                    raise ValueError('Playback speed must be 0.1 to 4')
                self.speed = speed
            self._advance()
            self.playing = bool(running and self.cursor < self.duration)
            self.last_action = time.monotonic()
            return self.frame(0, 0)

    def frame(self, after, wait_ms):
        with self.lock:
            self._advance()
            self.last_used = time.monotonic()
            bodies = [{k:v for k,v in b.items() if not k.startswith('_') and
                       (k != 'cells_local_m' or b['_cells_seq'] > after)}
                      for b in self.bodies.values() if b['_seq'] > after or after == 0]
            return {**copy.deepcopy(self.latest), 'session':self.id, 'playing':self.playing, 'speed':self.speed,
                    'prepared_playback':True, 'full':after == 0, 'bodies':copy.deepcopy(bodies),
                    'events':[e for e in self.events if e['seq'] > after],
                    'removed':[n for n,s in self.removed.items() if s > after]}

    def close(self):
        self.closed = True
        self.playing = False
        self.frames = []

    def __getattr__(self, name):
        if name in ('pull','mechanical_switch_pull','electrical_switch','water_opening','water_valve','release_joint'):
            raise ValueError('This recorded run has no live controls. Return to Build to change the machine.')
        raise AttributeError(name)
