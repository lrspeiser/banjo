"""Bounded live CPU sheet experiments; no prerecorded outcomes or rendered damage."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid

MATERIALS = ('iron', 'aluminum', 'glass', 'ceramic', 'oak', 'rubber', 'ice', 'concrete')

class SheetManager:
    observation_limit = 80
    advance_steps = 1000

    def validate_create(self, request):
        if set(request) != {'op', 'material', 'pick', 'point_m'}: raise ValueError('Invalid sheet declaration')
        if request['material'] not in MATERIALS or request['pick'] not in MATERIALS: raise ValueError('Unknown material')
        p = request['point_m']
        if (not isinstance(p,list) or len(p)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in p)
            or p[1]!=0 or abs(p[0])>.008 or abs(p[2])>.012): raise ValueError('Hit the central working area')
        return dict(request, speed_m_s=6.0)

    def __init__(self, native, log_root=None):
        self.native = Path(native).resolve(strict=True)
        self.fingerprint = hashlib.sha256(self.native.read_bytes()).hexdigest()
        self.log_root = Path(log_root or Path(__file__).resolve().parents[1] / 'build/sheet-impact-logs')
        self.log_root.mkdir(parents=True, exist_ok=True)
        self.sessions = {}
        self.lock = threading.Lock()

    def request(self, request):
        if not isinstance(request, dict): raise ValueError('Expected an intention')
        op = request.get('op')
        with self.lock:
            for key, session in list(self.sessions.items()):
                if time.monotonic() - session['seen'] > 180:
                    self._stop(session); del self.sessions[key]
            if op == 'create':
                command = self.validate_create(request)
                if len(self.sessions)>=8: raise ValueError('Eight active specimens maximum; reset an existing specimen')
                child = subprocess.Popen([str(self.native), '--serve'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, bufsize=1)
                output = queue.Queue(maxsize=2)
                def read():
                    try:
                        for line in child.stdout: output.put(line)
                    finally: output.put(None)
                threading.Thread(target=read, daemon=True).start()
                key = uuid.uuid4().hex
                session = {'child':child, 'output':output, 'seen':time.monotonic(), 'sequence':0,
                           'log':self.log_root/(key+'.jsonl')}
                self.sessions[key] = session
            else:
                if set(request)!={'op','session'} or op not in ('advance','close'): raise ValueError('Invalid sheet intention')
                key=request['session']
                if not isinstance(key,str): raise ValueError('Invalid session identity')
                # Closing an expired/restarted session is safe and lets reset create a new one.
                if key not in self.sessions:
                    if op=='close' and len(key)==32 and all(c in '0123456789abcdef' for c in key):
                        return {'ok':True,'closed':True}
                    raise ValueError('Specimen expired; reset it')
                session=self.sessions[key]
                if op=='close':
                    self._stop(session);del self.sessions[key];return {'ok':True,'closed':True}
                if session['sequence']>=self.observation_limit: raise ValueError('Specimen observation limit; reset it')
                command={'op':'advance','steps':self.advance_steps}
            try:
                session['child'].stdin.write(json.dumps(command, allow_nan=False)+'\n');session['child'].stdin.flush()
                line=session['output'].get(timeout=15)
                if line is None or len(line)>500000: raise RuntimeError('Native sheet stopped')
                result=json.loads(line)
                session['sequence']+=1;session['seen']=time.monotonic()
                result.update(session=key, sequence=session['sequence'], native_sha256=self.fingerprint)
                with session['log'].open('a',encoding='utf-8') as log:
                    log.write(json.dumps({'request':command,'receipt':result},allow_nan=False)+'\n')
                return result
            except (OSError,queue.Empty,ValueError):
                self._stop(session);del self.sessions[key];raise RuntimeError('Native sheet refused observation')

    def _stop(self, session):
        child=session['child']
        child.terminate()
        try:child.wait(timeout=3)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
        child.stdin.close();child.stdout.close()

    def close(self):
        with self.lock:
            for session in self.sessions.values():self._stop(session)
            self.sessions.clear()
