"""Puzzles on the machine: a level, a tray of pieces, a goal the engine checks.

A level is a machine (banjo.machine.v1) that is fixed -- the player cannot
move it -- plus a goal, a time limit, and a TRAY: the pieces the player may
add, each with a cost and a few knobs (where it goes, how high, how much
powder). The player's placements are composed into the level's machine and
the engine runs the whole thing; nothing about the outcome is decided here.

Scoring, from what the engine measured:
  goal     the goal happened within the time limit
  budget   the pieces cost no more than the level's par
  style    the chain used at least the level's number of different pieces

Reliability: a real chain of events is fragile. `trial` runs the same machine
several times with every loose part nudged by a millimetre or two, and says
in how many the goal happened -- which a player can try to raise.

Levels live in client/voxel-lab/levels.json.
"""
import copy
import json
import math
import random
from pathlib import Path

import machine_world as mw

ROOT = Path(__file__).resolve().parents[1]
LEVELS_PATH = ROOT / 'client/voxel-lab/levels.json'


def load_levels():
    return json.loads(LEVELS_PATH.read_text(encoding='utf-8'))['levels']


def level_by_id(level_id):
    for level in load_levels():
        if level['id'] == level_id:
            return level
    raise ValueError(f'There is no level called {level_id!s}')


# ---- the pieces ---------------------------------------------------------------
#
# Each piece type turns a placement's knobs into the machine's own kits and
# parts. The knobs a level allows, and their ranges, are in the level's tray;
# every value is checked against them before anything is built.

def _plank(name, k):
    """A bolted plank: its top surface at `top_m`, from x_from to x_to."""
    x0, x1 = sorted((k['x_from_m'], k['x_to_m']))
    thick = 0.04
    return {'parts': [{'name': name, 'shape': 'box', 'material': k.get('material', 'oak'),
                       'size_m': [round(x1 - x0, 4), thick, k.get('width_m', 0.3)],
                       'at_m': [round((x0 + x1) / 2, 4), k['top_m'] - thick / 2, k.get('z_m', 0.0)], 'fixed': True}]}


def _knife(name, k):
    return {'kits': [{'kit': 'knife_pendulum', 'name': name,
                      'pivot_m': [k['x_m'], k['pivot_height_m'], k.get('z_m', 0.0)], 'arm_m': k['arm_m'],
                      'swing_toward': k.get('swing_toward', '+x'), 'weight_kg': k.get('weight_kg', 0.0),
                      'edge_radius_m': k.get('edge_radius_m', 0.0002)}]}


def _cannon(name, k):
    kit = {'kit': 'cannon', 'name': name, 'at_m': [k['x_m'], k['bore_height_m'], k.get('z_m', 0.0)],
           'toward': k.get('toward', '+x'), 'powder_g': k['powder_g'],
           'ball': {'diameter_m': k.get('ball_diameter_m', 0.08), 'material': k.get('ball_material', 'iron')}}
    if k.get('fire_at_s') is not None:
        kit['fire_at_s'] = k['fire_at_s']
    return {'kits': [kit]}


def _steam(name, k):
    return {'kits': [{'kit': 'steam_engine', 'name': name, 'at_m': [k['x_m'], 0.0, k.get('z_m', 0.0)],
                      'heat_w': k['heat_kw'] * 1000.0, 'boiler_side': k.get('boiler_side', '-x')}]}


def _ramp(name, k):
    """A ramp with a ball at its top, running toward +x: its top at
    (x_m, top_height_m), down to its foot `run_m` further on at foot_height_m."""
    return {'kits': [{'kit': 'ramp', 'name': name, 'top_m': [k['x_m'], k['top_height_m'], k.get('z_m', 0.0)],
                      'bottom_m': [k['x_m'] + k['run_m'], k['foot_height_m'], k.get('z_m', 0.0)],
                      'width_m': 0.12, 'ball': {'material': k.get('ball_material', 'iron'), 'diameter_m': 0.08,
                                                'name': name + ' ball'}}]}


PIECES = {'plank': _plank, 'knife': _knife, 'cannon': _cannon, 'steam': _steam, 'ramp': _ramp}


class LevelRefused(ValueError):
    def __init__(self, problems):
        super().__init__('; '.join(problems))
        self.problems = problems


def check_placements(level, placements):
    """Every placement names a tray piece the level offers, no more of each
    than the tray holds, every knob within its range. Returns the placements
    with defaults filled in and their total cost."""
    problems, out, used, cost = [], [], {}, 0.0
    tray = {t['piece']: t for t in level['tray']}
    if not isinstance(placements, list):
        raise LevelRefused(['placements is a list'])
    for i, p in enumerate(placements):
        what = f'piece {i + 1}'
        if not isinstance(p, dict) or p.get('piece') not in tray:
            problems.append(f'{what}: piece is one of {", ".join(tray)}')
            continue
        t = tray[p['piece']]
        used[p['piece']] = used.get(p['piece'], 0) + 1
        if used[p['piece']] > t.get('count', 1):
            problems.append(f'{what}: the tray holds {t.get("count", 1)} {p["piece"]}')
        knobs = {}
        for key, rule in t['knobs'].items():
            value = p.get(key, rule.get('default'))
            if 'choices' in rule:
                if value not in rule['choices']:
                    problems.append(f'{what}: {key} is one of {", ".join(map(str, rule["choices"]))}')
                knobs[key] = value
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                problems.append(f'{what}: {key} must be a number')
                continue
            if not rule['min'] <= value <= rule['max']:
                problems.append(f'{what}: {key} is {rule["min"]} to {rule["max"]}')
            knobs[key] = float(value)
        extra = set(p) - set(t['knobs']) - {'piece'}
        if extra:
            problems.append(f'{what}: {", ".join(sorted(extra))} cannot be set on a {p["piece"]}')
        price = t['cost']
        if 'cost_per' in t:
            # Priced by a knob: a plank by its length, a firebox by its power.
            per = t['cost_per']
            amount = (abs(knobs.get('x_to_m', 0) - knobs.get('x_from_m', 0)) if per['knob'] == 'length'
                      else knobs.get(per['knob'], 0))
            price += per['each'] * amount / per['unit']
        cost += price
        out.append(dict(knobs, piece=p['piece'], cost=round(price, 1)))
    if cost > level['budget'] + 1e-9:
        problems.append(f'the pieces cost {cost:.0f}; the budget is {level["budget"]}')
    if problems:
        raise LevelRefused(problems)
    return out, round(cost, 1)


def compose(level, placements):
    """The level's machine with the player's pieces in it, and the goal as a
    station. Raises LevelRefused (the tray) or mw.MachineRefused (the
    machine: overlaps, nothing in the ground, ...)."""
    checked, cost = check_placements(level, placements)
    spec = copy.deepcopy(level['machine'])
    spec.setdefault('kits', [])
    spec.setdefault('parts', [])
    spec['title'] = level['title']
    for i, p in enumerate(checked):
        knobs = {k: v for k, v in p.items() if k not in ('piece', 'cost')}
        made = PIECES[p['piece']](f'your {p["piece"]} {i + 1}', knobs)
        spec['kits'] += made.get('kits', [])
        spec['parts'] += made.get('parts', [])
    goal = level['goal']['station']['done_when']
    rule = next(iter(goal.values()))
    wanted = rule.get('part') if isinstance(rule, dict) else rule
    if isinstance(wanted, str):
        names = {p['name'] for p in mw.compile_spec(dict(spec, stations=[]))['parts']}
        if wanted not in names:
            raise LevelRefused([level['goal'].get('needs', f'the goal is about {wanted}, which is not here yet')])
    spec['stations'] = [dict(level['goal']['station'], title=level['goal']['title'], focus=level['goal'].get('focus', []))]
    return spec, checked, cost


def stars(level, checked, cost, goal_at_s, helped=False):
    """What a run earned, from what the engine measured."""
    kinds = {p['piece'] for p in checked}
    got = {'goal': goal_at_s is not None and goal_at_s <= level['time_s'],
           'budget': cost <= level['par'],
           'style': len(kinds) >= level.get('style_pieces', 1)}
    count = sum(got.values()) if got['goal'] else 0
    if helped:
        # The chat placed the pieces: the goal still counts, the rest less so.
        count = min(count, 1)
    return {'stars': count, 'earned': got, 'cost': cost, 'par': level['par'], 'goal_at_s': goal_at_s,
            'helped': helped}


def nudged(compiled, seed, metres=0.0015):
    """The same machine with every loose part moved by up to `metres` in each
    direction: the run-to-run wobble a real machine has."""
    rng = random.Random(seed)
    out = copy.deepcopy(compiled)
    for p in out['parts']:
        if not p['fixed']:
            p['at_m'] = [v + rng.uniform(-metres, metres) for v in p['at_m']]
    return out


def trial(level, placements, exe, logs, runs=3):
    """Run the machine `runs` times, nudged, and say in how many the goal
    happened in time. Unpaced: as fast as the engine goes."""
    spec, checked, cost = compose(level, placements)
    compiled = mw.compile_spec(spec)
    results = []
    for seed in range(runs):
        r = mw.rehearse(nudged(compiled, seed + 1) if seed else compiled, exe, logs,
                        seconds=level['time_s'] + 0.5, wall_limit_s=120)
        row = r['stations'][0] if r['stations'] else {}
        at = row.get('at_s') if row.get('done') else None
        results.append({'goal_at_s': at, 'error': r.get('error'),
                        'closest': (r.get('closest_approach') or [None])[0]})
    worked = sum(1 for x in results if x['goal_at_s'] is not None and x['goal_at_s'] <= level['time_s'])
    return {'runs': runs, 'worked': worked, 'results': results, 'cost': cost}


def miss_m(level, rehearsal):
    """How far from the goal a rehearsal ended up: 0 when the goal happened
    in time, otherwise how near the goal zone the part came (or 1 m when the
    goal is not a zone)."""
    row = (rehearsal.get('stations') or [{}])[0]
    if row.get('done') and row.get('at_s') is not None and row['at_s'] <= level['time_s']:
        return 0.0
    near = rehearsal.get('zone_nearest_m') or {}
    return near.get(level['goal']['title'], 1.0) + 0.001


def refine(level, placements, rehearse, budget=24):
    """Starting from `placements`, move one knob at a time and keep a move
    when the engine says the goal came nearer -- a plain coordinate search,
    every step of it a real run. Returns (placements, rehearsal, runs) for the
    best found; the goal happened when miss_m of it is 0."""
    best = [{k: v for k, v in p.items() if k != 'cost'} for p in placements]
    spec, _, _ = compose(level, best)
    best_run = rehearse(mw.compile_spec(spec))
    best_miss, runs = miss_m(level, best_run), 1
    tray = {t['piece']: t for t in level['tray']}
    knobs = [(i, key, rule) for i, p in enumerate(best) for key, rule in tray[p['piece']]['knobs'].items()
             if 'choices' not in rule]
    for fraction in (0.12, 0.05, 0.02):
        improved = True
        while improved and best_miss > 0 and runs < budget:
            improved = False
            for i, key, rule in knobs:
                for sign in (1, -1):
                    if best_miss == 0 or runs >= budget:
                        break
                    trial_p = copy.deepcopy(best)
                    step = sign * fraction * (rule['max'] - rule['min'])
                    trial_p[i][key] = round(min(rule['max'], max(rule['min'], trial_p[i][key] + step)), 4)
                    if trial_p[i][key] == best[i][key]:
                        continue
                    try:
                        spec, _, _ = compose(level, trial_p)
                        compiled = mw.compile_spec(spec)
                    except (LevelRefused, mw.MachineRefused):
                        continue
                    run = rehearse(compiled)
                    runs += 1
                    miss = miss_m(level, run)
                    if miss < best_miss - 1e-4:
                        best, best_run, best_miss, improved = trial_p, run, miss, True
                        break
        if best_miss == 0:
            break
    return best, best_run, runs


def public(level):
    """What the page needs to show a level: never its solution."""
    return {k: level[k] for k in ('id', 'title', 'brief', 'teaches', 'time_s', 'budget', 'par', 'style_pieces',
                                  'tray', 'goal', 'hints') if k in level}
