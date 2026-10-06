"""Bounded, local gameplay diagnostics; never a source of simulation commands.

Browser observations and authenticated server outcomes are explicitly separate.
Only declared diagnostic fields are filed: no request headers, session tokens,
chat transcripts, credentials or arbitrary client dictionaries.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import threading
import time
import uuid

MAX_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 64
_lock = threading.Lock()
_attempt = ContextVar('banjo_tool_attempt', default=None)
_code_id = None
_SCALAR = {'id', 'event', 'tool', 'target_name', 'input', 'state', 'mode', 'reason',
           'enabled', 'ready', 'refused', 'action', 'said', 'phase', 'ring_state',
           'material', 'elapsed_ms', 'preview_age_ms', 'queue_replaced', 'discarded',
           'native_s', 'native_elapsed_s', 'tip_gap_m', 'grip_gap_m', 'prepare_ms',
           'stroke_ms', 'close_ms', 'kind', 'point', 'at_s', 'open', 'loosened_kg',
           'cut_work_J', 'input_work_J', 'working_point_connected', 'tool_whole',
           'stroke_ended', 'stroking', 'holding', 'request_received', 'dropped',
           'status', 'error_type', 'client_ms', 'physical_ground', 'energy_assist',
           'distance_m', 'penetration_m', 'loosened_m3', 'ground_work_J',
           'hand_work_J', 'removed_kg', 'replayed', 'hand_work_j', 'ground_work_j',
           'work_j', 'break_work_j', 'cutting_work_j', 'required_work_j', 'charged_j',
           'mass_kg', 'volume_m3', 'broken_share', 'body_id', 'supported'}
_VECTOR = {'at_m', 'eyes_m', 'from_m', 'direction', 'tip_m', 'grip_m',
           'wish_hand_m', 'wish_tip_m', 'pointing', 'position_m', 'velocity_m_s',
           'target_m', 'force_n', 'grip_velocity_m_s'}
_OBJECT = {'preview', 'target', 'hand', 'native_player', 'diagnostics', 'timing', 'result'}
_OBJECT.add('cut')


def _finite(value):
    try:
        return isinstance(value, (float, int)) and math.isfinite(value)
    except OverflowError:
        return False


def _safe(value, depth=0):
    if not isinstance(value, dict) or depth > 3:
        return {}
    out = {}
    for key, val in value.items():
        if key in _SCALAR:
            if val is None or isinstance(val, bool):
                out[key] = val
            elif _finite(val):
                out[key] = val
            elif isinstance(val, str):
                # Never retain a pasted credential, even in an allowed error.
                out[key] = re.sub(r'sk-[A-Za-z0-9_-]+', '[redacted]', val[:360])
        elif key in _VECTOR and isinstance(val, (list, tuple)) and len(val) == 3:
            if all(_finite(v) for v in val):
                out[key] = [round(v, 6) for v in val]
        elif key=='orientation_wxyz' and isinstance(val,(list,tuple)) and len(val)==4:
            if all(_finite(v) for v in val):out[key]=[round(v,6) for v in val]
        elif key in _OBJECT and isinstance(val, dict):
            out[key] = _safe(val, depth + 1)
        elif key == 'results' and isinstance(val, list):
            out[key] = [_safe(v, depth + 1) for v in val[:16]]
    return out


def write(app, player, source, event):
    global _code_id
    row = _safe(event)
    if not row.get('event'):
        return False
    try:
        with _lock:
            if _code_id is None:
                root = Path(__file__).parent
                _code_id = hashlib.sha256(b''.join((root / name).read_bytes()
                    for name in ('interaction_trace.py', 'tool_use.py', 'tools.js', 'world.js'))).hexdigest()[:16]
            # Provenance cannot be supplied by a browser event.
            row.update(at=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                       source=source, world=getattr(app, 'world_id', None),
                       actor=hashlib.sha256(str(player or 'laboratory').encode()).hexdigest()[:16],
                       code_id=_code_id)
            where = app.runs_path / 'interaction-events.jsonl'
            where.parent.mkdir(parents=True, exist_ok=True)
            if where.exists() and where.stat().st_size >= MAX_BYTES:
                where.replace(where.with_suffix('.previous.jsonl'))
            with where.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n')
        return True
    except OSError:
        # Limit notices as well as the file. A missing/unwritable diagnostics
        # directory must not flood the normal gameplay log or fail a stroke.
        now=time.monotonic()
        if now-getattr(app,'_interaction_trace_warned_at',-60)>=60:
            app._interaction_trace_warned_at=now
            logging.getLogger('banjo').warning('Interaction diagnostics could not be written', exc_info=True)
        return False


def browser(app, player, events):
    if not isinstance(events, list):
        return
    for event in events[:MAX_EVENTS]:
        write(app, player, 'browser', event)


def snapshot(app, player):
    session = getattr(getattr(app, 'live', None), 'session', None)
    state = (getattr(session, 'state', None) or {})
    hand = (state.get('player_hands') or {}).get(player) if player else state.get('hand')
    return {'native_s': state.get('t'), 'hand': hand or {},
            'native_player': (state.get('native_players') or {}).get(player) or {}}


@contextmanager
def attempt(app, player, body):
    # Log before preflight/geometry checks; exceptions must leave an outcome.
    body = body if isinstance(body, dict) else {}
    ident = body.get('interaction_id')
    ident = ident if isinstance(ident, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', ident) else uuid.uuid4().hex
    item = {'app': app, 'player': player, 'id': ident, 'started': time.monotonic(), 'finished': False}
    token = _attempt.set(item)
    write(app, player, 'server', {'event': 'tool-request', 'id': ident,
        'at_m': body.get('at_m'), 'target_name': body.get('target_name'),
        'eyes_m': (body.get('person') or {}).get('eyes_m') if isinstance(body.get('person'), dict) else None,
        'energy_assist': body.get('energy_assist') is True, **snapshot(app, player)})
    try:
        yield item
    except Exception as exc:
        if item['finished']:
            write(app,player,'server',{'event':'tool-delivery-error','id':ident,
                  'error_type':type(exc).__name__,'reason':str(exc)})
        else:
            outcome({'status': 'error', 'error_type': type(exc).__name__, 'reason': str(exc)})
        raise
    finally:
        if not item['finished']:
            outcome({'status': 'no-result', 'reason': 'Handler ended without a tool result'})
        _attempt.reset(token)


def preflight(answer):
    item = _attempt.get()
    if item:
        write(item['app'], item['player'], 'server', {'event': 'tool-preflight', 'id': item['id'],
              'tool': answer.get('tool'), 'enabled': answer.get('enabled'),
              'reason': answer.get('reason'), 'ring_state': (answer.get('ring') or {}).get('state'),
              'target': answer.get('target'), 'preview': answer.get('feedback'),
              'wish_hand_m': (answer.get('ready') or {}).get('hand')})


def outcome(answer):
    item = _attempt.get()
    if item:
        item['finished'] = True
        write(item['app'], item['player'], 'server', {**answer,
              'event': 'tool-result', 'id': item['id'],
              'elapsed_ms': round(1000 * (time.monotonic() - item['started']), 1),
              **snapshot(item['app'], item['player'])})
