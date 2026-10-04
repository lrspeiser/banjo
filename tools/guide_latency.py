"""Measure how long the proactive guide takes to explain a next step.

Real provider calls with the local .env key, the same as the game makes: one
explanation of a saved construction project's next step, asked `--calls`
times in each mode. "single" is one call with a long timeout, to see the
provider's own spread; "priority" asks for the provider's priority tier;
"game" is what the game does (proactive_guidance: nothing after 2 s). Reports each duration, the
nearest-rank p50 and p95 and how many answered within two seconds.

    python tools/guide_latency.py --calls 30
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'playground'), str(ROOT / 'mcp'), str(ROOT)]
import proactive_guidance  # noqa: E402
import server  # noqa: E402

# One of the game's own construction observations (proactive_guidance.observation
# of a held camp light whose site is being prepared).
GUIDANCE = {
    'project': {'name': 'Camp light', 'focused': True, 'source': 'construction'},
    'next_action': {'verb': 'construction', 'label': 'Check the ground again', 'status': 'Available',
                    'destination': {'screen': 'world', 'place': 'item-3f2a'},
                    'blockers': []},
    'build_readiness': None,
    'construction_project': {'project': {
        'name': 'Camp light', 'status': 'Prepare ground', 'blocker': None,
        'preparation': {'done': False, 'why': None, 'squares': [{'dig_m': .08, 'rock': False}] * 5},
        'steps': [{'id': 'prepare', 'label': 'Prepare the ground', 'status': 'current'},
                  {'id': 'hold', 'label': 'Hold item', 'status': 'pending'},
                  {'id': 'site', 'label': 'Choose supported spot', 'status': 'pending'},
                  {'id': 'place', 'label': 'Place item', 'status': 'pending'},
                  {'id': 'inspect', 'label': 'View components and use', 'status': 'pending'}],
        'installation': {'kind': 'mine-lamp', 'connections': [], 'placement_checked': False,
                         'limits': 'Installation intent. Native placement, settling and operation still require checks.'}}},
    'limits': 'Saved intent. Native placement rechecks reach, collisions and support; no structural certificate.',
}


def rank(values, q):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--calls', type=int, default=30)
    parser.add_argument('--modes', default='single,priority,game')
    parser.add_argument('--gap-s', type=float, default=1.0)
    args = parser.parse_args()
    key, _ = server.local_configuration()
    if not key:
        raise SystemExit('No OPENAI_API_KEY in the environment or the local .env')
    context = proactive_guidance.observation(GUIDANCE)
    report = {'model': None, 'modes': {}}
    for mode in args.modes.split(','):
        app = type('App', (), {})()
        app.api_key = key
        if mode in ('single', 'priority'):
            app.guidance_deadline_s, app.guidance_hedge_s = 10.0, 10.0
        if mode == 'priority':
            app.guidance_service_tier = 'priority'
        rows = []
        for _ in range(args.calls):
            began = time.monotonic()
            try:
                got = proactive_guidance.explain(app, context)
                rows.append({'s': round(time.monotonic() - began, 4), 'ok': True,
                             'hedged': got.get('hedged', False), 'text': got['text']})
                report['model'] = got['model']
            except Exception as error:
                rows.append({'s': round(time.monotonic() - began, 4), 'ok': False, 'why': str(error)[:120]})
            print(mode, rows[-1]['s'], rows[-1].get('hedged', ''), rows[-1].get('why', ''), flush=True)
            time.sleep(args.gap_s)
        waits = [r['s'] for r in rows]
        report['modes'][mode] = {
            'calls': len(rows), 'answered': sum(r['ok'] for r in rows),
            'answered_within_2s': sum(r['ok'] and r['s'] <= 2.0 for r in rows),
            'hedged': sum(r.get('hedged', False) for r in rows),
            'p50_s': rank(waits, .5), 'p95_s': rank(waits, .95), 'max_s': max(waits), 'rows': rows}
    out = ROOT / 'build' / 'guide-latency.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for mode, m in report['modes'].items():
        print(f"{mode}: {m['answered']}/{m['calls']} answered, {m['answered_within_2s']} within 2 s, "
              f"{m['hedged']} hedged, p50 {m['p50_s']} s, p95 {m['p95_s']} s, max {m['max_s']} s")


if __name__ == '__main__':
    main()
