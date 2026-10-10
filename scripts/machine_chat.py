"""Chat that builds machines.

A request in words becomes a machine declaration (machine_world, schema
banjo.machine.v1). The model only writes the declaration: which parts, kits,
joints, batteries, circuits and torches, and where. It never writes motion or
outcomes. The server checks the declaration (nothing below the ground, nothing
overlapping, every name real) and the engine calculates everything that
happens. A declaration the checks refuse goes back to the model once, with the
reasons, so it can change its values; if it is still refused, the person sees
the reasons and nothing is built.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib import error, request

import machine_world as mw

ROOT = Path(__file__).resolve().parents[1]
MAX_MESSAGE = 2000
MAX_HISTORY = 6


class ChatUnavailable(RuntimeError):
    """No model is configured: a person can still build by editing the JSON."""


def configuration():
    """OPENAI_API_KEY and OPENAI_MODEL from the environment, else this
    checkout's own .env. The key is read, never logged or returned."""
    values = {}
    path = ROOT / '.env'
    if path.is_file() and path.stat().st_size <= 65536:
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = (s.strip() for s in line.split('=', 1))
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            values.setdefault(key, value)
    return (os.environ.get('OPENAI_API_KEY') or values.get('OPENAI_API_KEY', ''),
            os.environ.get('OPENAI_MODEL') or values.get('OPENAI_MODEL', 'gpt-5-mini'))


def system_prompt():
    kits = '\n'.join(f'- {name}: {text}' for name, text in mw.KIT_HELP.items())
    return f"""You build machines in Banjo, a physics world. You write ONLY a declaration of what exists and where.
The engine calculates every motion, contact, hinge, electric current, temperature, burn and break. Never describe an
outcome as certain: say what you built and what the engine will decide.

World: metres, kilograms, seconds, newtons, volts, ohms, kelvin. y is up; the ground is level at y = 0, except a
flume trench when "ground" declares one (water flows in it, down +x).
Materials: {', '.join(mw.MATERIALS)}. Only oak burns. Glass, ice and ceramic can break; oak and iron can too under
large loads. Bodies are built from cubic cells of cell_m (0.02 m): every size is a whole number of cells, at least one.

Declaration (JSON object, schema "{mw.SCHEMA}"):
{{"schema": "{mw.SCHEMA}", "title": str, "cell_m": 0.02,
  "ground": null, or {{"kind": "flume", "nx": 100, "nz": 60, "cell_m": 0.1, "trench_z_m": n, "trench_width_m": n,
             "trench_depth_m": n, "trench_slope": n, "discharge_m3_s": n (water in at the west end),
             "reservoir_to_x_m": n, "reservoir_level_m": n (still water up to that x, surface below 0)}}
             -- the ground then spans x and z within +-(n-1)*cell_m/2; every part must stand on it,
  "kits": [ {{"kit": <kit name>, "name": str, ...kit fields}} ],
  "parts": [ {{"name": str, "shape": "box"|"sphere"|"cone", "material": str, "size_m": [x, y, z],
              "at_m": [x, y, z] (centre), "turn_deg": [x, y, z] (about x, then y, then z), "fixed": bool,
              "velocity_m_s": [x, y, z]}} ],
  "joints": [ {{"name": str, "kind": "hinge", "a": part, "b": part, "at_m": [..], "axis": [..], "lower_deg": n,
               "upper_deg": n, "friction_n_m": n}},
             {{"name": str, "kind": "fix", "a": part, "b": part, "at_m": [..], "axis": [..], "holds_shear_n": n,
               "holds_tension_n": n, "member": a or b (the part the fixing is made of; heat weakens it)}},
             {{"name": str, "kind": "tie", "a": part, "b": part, "at_m": [..], "at_b_m": [..], "length_m": n,
               "breaks_at_n": n}},
             {{"name": str, "kind": "spring", "a": part, "b": part, "at_m": [..], "at_b_m": [..], "rest_m": n,
               "stiffness_n_m": n, "damping_n_s_m": n}},
             {{"name": str, "kind": "slide", "a": fixed guide part, "b": part, "at_m": [..], "axis": [..],
               "lower_m": n, "upper_m": n, "friction_n": n}} (b moves only along the axis, between the limits),
             {{"name": str, "kind": "drum", "drum": a part that turns on its own hinge, "load": part,
               "centre_m": [..] (a point on the drum's axle), "axis": [..], "radius_m": n, "load_point_m": [..]
               (where the rope is tied on the load), "winds": 1 or -1, "spare_m": n}} (a rope that winds onto the
               drum as it turns the "winds" way, pulling the load; it pulls and never pushes),
             {{"name": str, "kind": "gear", "a": hinge joint name, "b": hinge joint name, "teeth_a": n, "teeth_b": n,
               "chain": false, "strips_at_n_m": n}} (two wheels on their own hinges turning together at the ratio of
               their teeth: meshed teeth turn them opposite ways, a chain the same way; declare it after both
               hinges),
             {{"name": str, "kind": "pulley", "a": part, "b": part, "at_m": [..] (rope end on a), "at_b_m": [..]
               (rope end on b), "over_a_m": [..], "over_b_m": [..] (two fixed points the rope runs over),
               "ratio": n, "length_m": n}} (a block and tackle: b moves 1/ratio as far as a and feels ratio times
               the rope's tension; a counterweight of load/ratio balances the load) ],
  "batteries": [ {{"name": str, "in": part, "capacity_j": n, "voltage_v": n, "max_power_w": n,
                  "charge_j": n (what it holds at the start; 0 for an empty one a solar panel fills)}} ],
  "circuits": [ {{"name": str, "battery": battery name,
                 "switch": {{"hinge": hinge joint name, "closed_at_or_above_deg": n}}, or
                           {{"photocell": light sensor name, "closed_at_or_above_w": n}}, or null (always closed),
                 "coil": {{"heats": part, "resistance_ohm": n}},
                 "motor": {{"hinge": hinge joint name, "stall_torque_n_m": n, "no_load_rad_s": n,
                            "brake_torque_n_m": n, "gear_ratio": n, "command": 1 (full ahead) to -1 (astern)}}}}
               ] (a load is a coil, a motor, or both; the switch works them together),
  "sun": {{"elevation_deg": n, "azimuth_deg": n, "irradiance_w_m2": n}} (sunlight; the engine thins it through the
         air and casts shadows; "light" below traces it through glass and off mirrors),
  "solar_panels": [ {{"name": str, "part": part, "battery": battery name, "normal": [0, 1, 0] (the way its cells
                    face), "area_m2": n, "efficiency": 0.2}} ] (needs a sun; charges the battery with what falls on
                    it, nothing while something shades it),
  "plasticity": true (metal and wood yield and keep a permanent dent; needed for a dented station),
  "blades": [ {{"part": part (made of cells, not compound), "heel_m": [..], "tip_m": [..] (the edge, a line ON the
              part's surface), "facing": [..] (the way the edge faces, out of the part), "edge_radius_m": 0.0002}} ]
             (an edge cuts oak and rubber when it leads into them hard enough; a knife_pendulum kit makes one),
  "torches": [ {{"target": part, "power_w": n, "seconds": n}} ],
  "spouts": [ {{"name": str, "at_m": [x, y, z] (the mouth, in the air over the flume's ground), "direction": [0, -1, 0],
              "speed_m_s": n, "discharge_l_s": n (0.05-20), "from_s": n, "until_s": n}} ]
             -- poured water falls as parcels, pushes what it lands on and joins the stream; needs ground kind
             flume (a water_wheel kit's "pour" makes one for you),
  "stations": [ {{"title": str, "shows": str, "law": str, "maturity": "calculated"|"experimental",
                 "done_when": one of {{"hits": [part, part]}}, {{"hinge_beyond_deg": {{"joint": name, "deg": n}}}},
                 {{"turned_deg": {{"joint": hinge name, "deg": n}}}} (total turning, e.g. a wheel),
                 {{"slid_m": {{"joint": slide name, "m": n}}}}, {{"switch_closed": circuit}},
                 {{"hotter_than_k": {{"part": name, "k": n}}}}, {{"parted": part}}, {{"broke": part}},
                 {{"dented": part}} (a permanent set the engine measured: iron needs a hit above about 5 m/s and
                 dents a tenth of a millimetre at 16 m/s), {{"rose_m": {{"part": name, "m": n}}}} (its centre
                 rose that far), {{"moved_m": {{"part": name, "m": n}}}} (it moved that far from where it began),
                 {{"cut": part}} (an edge cut it through),
                 {{"lit_w": {{"photocell": name, "w": n}}}}, {{"shaded_w": {{"photocell": name, "w": n}}}},
                 "focus": [part]}} ] }}
A part may also be "shape": "compound": one exact rigid body of "parts": [{{"shape": "box"|"cylinder", "size_m":
[x, y, z] (a cylinder is [diameter, length, diameter] along its own y), "at_m": local centre, "turn_deg": local}}].

Kits expand into ordinary parts and joints; prefer them for layout:
{kits}
A circuit's coil heats the part it is wound on (heat flows in as I^2 R). A switch that follows a hinge is closed while
that hinge's measured angle is at or beyond its reading; the engine measures the angle every step. A motor turns its
hinge with a torque that falls from its stall torque to nothing at its no-load speed, from its battery's charge.
Steam and powder: a steam_engine kit's boiler boils with a firebox (heat_w) or a coil wound on its boiler; a cannon
kit fires when its charge is hot, from a primer at fire_at_s or a coil wound on "<name> charge" (measured: a 0.1 ohm
coil on a 24 V battery fires it 0.4 s after its switch closes, a 0.5 ohm coil 0.8 s after).

Light (the engine follows rays of light; it reflects, bends, focuses, warms and works sensors):
{mw.LIGHT_HELP}

Rules the server enforces (a declaration that breaks one is refused and sent back to you):
- Nothing goes into the ground: a part's lowest point is at or above the ground under it (y = 0, or the trench bed
  inside a flume trench). A part standing on level ground has at_m y = half its height.
- No two parts overlap unless both are fixed. Leave 2-20 mm gaps between parts that should touch when things move.
- Every name is unique; joints, batteries, circuits and stations name parts that exist.
- At most {mw.MAX_PARTS} parts; keep within {mw.WORLD_HALF_M:g} m of the origin.
- A rope is a "tie" JOINT between two parts, never a part. Anything that should hold still (posts, beams, supports,
  ramps, shelves) needs "fixed": true, or it falls.
- Dominoes 0.4 m tall need to be closer than their height to knock each other over; a falling body pushes a lever
  only if it lands ON the lever's top, not against its end.
- Check heights: at_m is a part's CENTRE, so a block of height h resting on a surface at height y has at_m y = y + h/2.
After your declaration passes these checks the server may run it once in the engine and send you the measured events;
then change the layout so the requested stations really happen.

Edit the CURRENT declaration you are given: keep what the person did not ask to change, add or change what they
asked for, and give every new step a station. Answer with ONE JSON object:
{{"reply": "two or three plain sentences to the person: what you built or changed, and what the engine will decide",
  "spec": the complete new declaration}}"""


def _call(api_key, model, messages, max_tokens=20000, want='spec'):
    payload = {'model': model, 'store': False, 'max_output_tokens': max_tokens, 'reasoning': {'effort': 'low'},
               'input': messages, 'text': {'format': {'type': 'json_object'}}}
    req = request.Request('https://api.openai.com/v1/responses', data=json.dumps(payload).encode(), method='POST',
                          headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'})
    try:
        with request.urlopen(req, timeout=150) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except error.HTTPError as exc:
        # The upstream body may echo inputs; never log or return it.
        raise ChatUnavailable(f'The model request failed (HTTP {exc.code}); check the key, model access and limits') from None
    except (error.URLError, TimeoutError):
        raise ChatUnavailable('Could not reach the model; nothing was retried') from None
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('The model answer was too large')
    result = json.loads(raw)
    if result.get('status') != 'completed':
        raise ValueError('The model did not finish its answer; try a shorter request')
    texts = []
    for item in result.get('output', []):
        for content in item.get('content', []) or []:
            if content.get('type') == 'refusal':
                raise ValueError('The model declined this request')
            if content.get('type') == 'output_text':
                texts.append(content.get('text', ''))
    answer = json.loads(''.join(texts))
    if want == 'spec' and (not isinstance(answer, dict) or not isinstance(answer.get('spec'), dict)):
        raise ValueError('The model did not return a machine declaration')
    return answer, result.get('usage', {})


# ---- puzzles ---------------------------------------------------------------------

def level_prompt(level, mode):
    """The rules of one puzzle for the model: the goal, the tray and its knobs,
    and what it may answer. It never sees the level's solution."""
    tray = []
    for t in level['tray']:
        knobs = []
        for key, rule in t['knobs'].items():
            if 'choices' in rule:
                knobs.append(f'{key} ({rule.get("label", key)}): one of {rule["choices"]}')
            else:
                knobs.append(f'{key} ({rule.get("label", key)}): {rule["min"]} to {rule["max"]}')
        price = f'{t["cost"]}' + (f' + {t["cost_per"]["each"]} per {t["cost_per"]["unit"]:g} of '
                                   f'{t["cost_per"]["knob"]}' if 'cost_per' in t else '')
        tray.append(f'- {t["piece"]} (up to {t.get("count", 1)}; costs {price}): ' + '; '.join(knobs))
    tray = '\n'.join(tray)
    offered = [t['piece'] for t in level['tray']]
    pieces = '\n'.join(f'- {name}: {PIECE_HELP[name]}' for name in offered if name in PIECE_HELP)
    if mode == 'build':
        answer = ('Answer with ONE JSON object: {"reply": "one or two plain sentences to the player about what you '
                  'placed and what the engine will decide", "options": [[{"piece": tray piece, knob: value, ...}], '
                  '...]} -- up to three DIFFERENT ways to place the pieces, best first; the engine rehearses each and '
                  'uses the first that reaches the goal. Vary the knobs that matter most between them. Use only tray '
                  'pieces and knobs, within their ranges and the budget.')
    else:
        answer = ('Answer with ONE JSON object: {"reply": "a hint of one to three plain sentences"}. A hint points '
                  'the player toward what to change, from what the engine measured in their last run when there '
                  'is one (where the thing went, how fast, what it hit). Do not give every knob\'s value; let the '
                  'player find them.')
    return f"""You help a player with a physics puzzle in Banjo. The engine calculates everything: you never decide
an outcome. Metres, kilograms, seconds; y is up and the ground is at y = 0.

The level: {level['title']}. {level['brief']}
Goal: {level['goal']['title']} within {level['time_s']} s. Budget {level['budget']}, par {level['par']}.
What is known about this level (measured): {' '.join(level.get('hints', []))}
The player may add only these pieces (the tray):
{tray}
What each piece is:
{pieces}
{TURNING_HELP if any('yaw_deg' in t['knobs'] or 'pitch_deg' in t['knobs'] for t in level['tray']) else ''}
{answer}"""


PIECE_HELP = {
    'plank': 'a loose oak plank 2 cm thick and 0.3 m wide, cut to length_m and set down with its middle at x_m: it '
             'is lowered onto the highest thing under it and rests there; gravity holds it, nothing bolts it',
    'knife': 'a knife pendulum held out level and let go: its pivot at (x_m, pivot_height_m, z_m), arm_m long, '
             'swinging toward swing_toward. At the bottom of its swing the blade is about arm_m + 0.03 m below the '
             'pivot, its sharp edge about 0.06 m ahead of the pivot, 0.2 m wide across the swing. It cuts oak and '
             'rubber, not iron',
    'cannon': 'a cannon firing level toward +x: its muzzle at (x_m, bore_height_m, z_m), the barrel behind it; '
              'fire_at_s is when its primer lights it; powder_g of powder throws its 2.1 kg iron ball at very '
              'roughly 9 m/s for 1 g and 20 m/s for 2 g. The ball drops as it flies',
    'steam': 'a steam engine: a cylinder at (x_m, z_m) on the ground with a piston on top, the piston at about '
             '0.34 m up; heat_kw boils water under it and the piston rises about 1.2 cm/s per kW',
    'ramp': 'a ramp toward +x with an iron ball at its top: its top at (x_m, top_height_m, z_m), its foot run_m '
            'further on at foot_height_m. The ball rolls down and flies on from the foot',
    'mirror': 'a polished aluminium mirror 0.2 m square standing upright at (x_m, z_m), turned angle_deg about the '
              'vertical: at 0 its face looks along x; turned 45 a beam along +x leaves along +z, turned -45 a beam '
              'along +z leaves along -x. Light reflects off its face, 1 cm in front of its middle, and it keeps 92% '
              'of the light',
    'solar': 'a solar panel 0.5 m square on a post, its middle at (x_m, height_m, z_m), wired to the level\'s '
             'battery. Flat it faces up; yaw_deg turns it about the vertical (a positive turn takes +x toward -z), '
             'then pitch_deg tips its +x edge up, so its face looks toward -x turned by yaw. It stores a fifth of the '
             'sunlight on its face: most when it faces the sun squarely, none in shadow',
}
TURNING_HELP = ('Every piece can also be moved across with z_m and turned any way: yaw_deg about the vertical (a '
                'positive turn takes +x toward -z), then pitch_deg tips its +x end up, then roll_deg turns it about '
                'its length. Turning costs nothing; leave them at 0 unless turning helps.')


def _placements_answer(answer):
    if not isinstance(answer, dict) or not isinstance(answer.get('reply'), str):
        raise ValueError('The model did not answer')
    return answer


def respond_level(message, level, placements, mode='hint', last_run=None, call=None, rehearse=None):
    """A hint, or the tray's pieces placed for the player ("build"), checked
    against the level and rehearsed in the engine like any chat build."""
    import machine_game as mg
    if not isinstance(message, str) or not message.strip():
        message = 'Give me a hint.' if mode == 'hint' else 'Place the pieces for me.'
    if len(message) > MAX_MESSAGE:
        raise ValueError(f'Keep a request under {MAX_MESSAGE} characters')
    if mode not in ('hint', 'build'):
        raise ValueError('mode is hint or build')
    if call is None:
        api_key, model = configuration()
        if not api_key:
            raise ChatUnavailable('No model is configured on this server (OPENAI_API_KEY)')
        call = lambda messages: _call(api_key, model, messages, want='reply')
    spec = None
    try:
        spec = mg.compose(level, placements)[0]
    except (mg.LevelRefused, mw.MachineRefused):
        spec = level['machine']
    messages = [{'role': 'system', 'content': level_prompt(level, mode)},
                {'role': 'user', 'content': json.dumps({'request': message, 'placements': placements,
                                                        'fixed_layout': layout(spec) if spec else None,
                                                        'last_run': last_run})}]
    answer, usage = call(messages)
    answer = _placements_answer(answer)
    if mode == 'hint':
        return {'ok': True, 'reply': answer['reply'], 'usage': usage}
    # Up to three different ways, each rehearsed in the engine; the first
    # that reaches the goal is the one used. A model cannot tune a shot or a
    # swing from words alone; the engine can say which of its ideas works.
    def options(a):
        found = a.get('options') if isinstance(a.get('options'), list) else [a.get('placements')]
        return [[fit(p) for p in o] for o in found if isinstance(o, list)][:3]

    tray = {t['piece']: t for t in level['tray']}

    def fit(p):
        # A knob just outside its range is brought to the nearest end of it,
        # and a knob the piece does not have is left out: the player could do
        # exactly that with the sliders. A piece not on the tray is left as it
        # is, for the tray's own refusal to explain.
        if not isinstance(p, dict) or p.get('piece') not in tray:
            return p
        out = {'piece': p['piece']}
        for key, rule in tray[p['piece']]['knobs'].items():
            if key not in p:
                continue
            value = p[key]
            if 'choices' not in rule and isinstance(value, (int, float)) and not isinstance(value, bool):
                value = min(rule['max'], max(rule['min'], value))
            out[key] = value
        return out

    tried = []
    for revision in range(2):
        for placed in options(answer):
            try:
                spec, checked, cost = mg.compose(level, placed)
                compiled = mw.compile_spec(spec)
            except (mg.LevelRefused, mw.MachineRefused) as e:
                tried.append({'placements': placed, 'refused': e.problems})
                continue
            if rehearse is None:
                return {'ok': True, 'reply': answer['reply'], 'placements': checked, 'cost': cost, 'helped': True,
                        'usage': usage}
            r = rehearse(compiled)
            row = (r.get('stations') or [{}])[0]
            if row.get('done'):
                return {'ok': True, 'reply': answer['reply'], 'placements': checked, 'cost': cost, 'helped': True,
                        'usage': usage, 'tried': len(tried) + 1,
                        'rehearsal': {'goal_at_s': row.get('at_s'), 'events': [e['text'] for e in r['events'][:20]]}}
            tried.append({'placements': placed, 'goal': 'did not happen', 'miss': mg.miss_m(level, r),
                          'events': [e['text'] for e in r['events'][:12]], 'closest': r.get('closest_approach'),
                          'nearest_to_goal_m': r.get('zone_nearest_m')})
        if revision:
            break
        # Every way it tried, and what the engine measured of each.
        messages += [{'role': 'assistant', 'content': json.dumps(answer)},
                     {'role': 'user', 'content': json.dumps({'measured': tried[-3:],
                                                             'ask': 'Change the knobs from what was measured and '
                                                                    'give up to three new options.'})}]
        answer, more = call(messages)
        answer = _placements_answer(answer)
        usage = _added(usage, more)
    # Nothing it tried reached the goal. Its nearest idea is then finished
    # by the engine: one knob at a time, kept when the goal comes nearer.
    built = [t for t in tried if 'refused' not in t]
    if not built:
        raise mg.LevelRefused(tried[-1]['refused'] if tried else ['The model placed nothing'])
    nearest = min(built, key=lambda t: t['miss'])
    placed, r, runs = mg.refine(level, nearest['placements'], rehearse, budget=48, scatter=16)
    spec, checked, cost = mg.compose(level, placed)
    row = (r.get('stations') or [{}])[0]
    reached = mg.miss_m(level, r) == 0
    note = (f' Its ideas missed; the engine then tried {runs} small changes to the nearest and '
            + ('found one that works.' if reached else 'got closer but not there.'))
    return {'ok': True, 'reply': answer['reply'] + note, 'placements': checked, 'cost': cost, 'helped': True,
            'usage': usage, 'tried': len(tried) + runs,
            'rehearsal': {'goal_at_s': row.get('at_s') if reached else None,
                          'events': [e['text'] for e in r['events'][:20]]}}



def layout(spec):
    """Where the current machine already is, so new things go somewhere clear:
    each kit's and part's box, and a free lane beside it all."""
    try:
        compiled = mw.compile_spec(spec)
    except mw.MachineRefused:
        return None
    groups = {}
    for p in compiled['parts']:
        key = p.get('kit') or p['name']
        axes, h = mw._axes(p), mw._half(p)
        extent = [sum(abs(axes[j][i]) * h[j] for j in range(3)) for i in range(3)]
        lo = [p['at_m'][i] - extent[i] for i in range(3)]
        hi = [p['at_m'][i] + extent[i] for i in range(3)]
        g = groups.setdefault(key, [lo, hi])
        g[0] = [min(a, b) for a, b in zip(g[0], lo)]
        g[1] = [max(a, b) for a, b in zip(g[1], hi)]
    ground = compiled.get('ground')
    if ground is not None:
        # The trench is taken: water runs there.
        half = 0.5 * ground['trench_width_m']
        x1 = ground['x0_m'] + (ground['nx'] - 1) * ground['cell_m']
        groups['the flume trench (water)'] = [[ground['x0_m'], -ground['trench_depth_m'] - 0.1, ground['trench_z_m'] - half],
                                             [x1, 0.0, ground['trench_z_m'] + half]]
    if not groups:
        return {'occupied': None, 'free_lane': 'anywhere'}
    lo = [min(g[0][i] for g in groups.values()) for i in range(3)]
    hi = [max(g[1][i] for g in groups.values()) for i in range(3)]
    r = lambda v: [round(x, 2) for x in v]
    if ground is not None:
        edge = ground['z0_m'] + (ground['nz'] - 1) * ground['cell_m']
        lane_from, lane_to = hi[2] + 0.4, min(hi[2] + 3.0, edge - 0.2)
        if lane_to - lane_from < 0.6:
            lane_from, lane_to = ground['z0_m'] + 0.2, lo[2] - 0.4
    else:
        lane_from, lane_to = hi[2] + 0.5, hi[2] + 3.0
    return {'occupied_from_m': r(lo), 'occupied_to_m': r(hi),
            'things': {k: {'from_m': r(v[0]), 'to_m': r(v[1])} for k, v in groups.items()},
            'free_lane': f'z from {lane_from:.2f} to {lane_to:.2f} m (any x from {lo[0]:.2f} to {hi[0]:.2f}) '
                         'is empty; build new things there unless they must touch existing ones'}


def _added(usage, more):
    return {k: usage.get(k, 0) + more.get(k, 0) for k in set(usage) | set(more)
            if isinstance(usage.get(k, 0), (int, float)) and isinstance(more.get(k, 0), (int, float))}


def _checked(call, messages, answer, usage):
    """Compile the answer; if the checks refuse it, send the reasons back once."""
    try:
        return answer, mw.compile_spec(answer['spec']), [], usage, 1
    except mw.MachineRefused as refused:
        messages += [{'role': 'assistant', 'content': json.dumps(answer)},
                     {'role': 'user', 'content': json.dumps({'refused': refused.problems,
                      'instruction': 'Change the declaration so every problem is fixed and keep the request. '
                                     'Your reply describes the whole build to the person, not only the fix.'})}]
        answer, more = call(messages)
        usage = _added(usage, more)
        try:
            return answer, mw.compile_spec(answer['spec']), [], usage, 2
        except mw.MachineRefused as again:
            return answer, None, again.problems, usage, 2


def _new_stations(compiled, previous):
    before = {s.get('title') for s in (previous.get('stations') or []) if isinstance(s, dict)}
    return [i for i, s in enumerate(compiled['stations']) if s.get('done_when') and s['title'] not in before]


# How many times the engine's measured rehearsal goes back to the model.
MAX_REVISIONS = 2


def respond(message, spec=None, history=None, call=None, rehearse=None):
    """Turn a request into a checked declaration. `call` replaces the model
    (tests); it receives the message list and returns (answer, usage).
    `rehearse(compiled)` runs the machine once in the engine; when a station
    the request added did not happen, the measured events go back to the
    model once so it can revise its layout, as an engineer would."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError('Say what you would like to build')
    if len(message) > MAX_MESSAGE:
        raise ValueError(f'Keep a request under {MAX_MESSAGE} characters')
    current = spec if isinstance(spec, dict) else mw.default_spec()
    turns = []
    for h in (history or [])[-MAX_HISTORY:]:
        if isinstance(h, dict) and h.get('role') in ('user', 'assistant') and isinstance(h.get('text'), str):
            turns.append({'role': h['role'], 'content': h['text'][:MAX_MESSAGE]})
    if call is None:
        api_key, model = configuration()
        if not api_key:
            raise ChatUnavailable('No model is configured on this server (OPENAI_API_KEY)')
        call = lambda messages: _call(api_key, model, messages)
    else:
        model = 'test'
    messages = [{'role': 'system', 'content': system_prompt()}] + turns + [
        {'role': 'user', 'content': json.dumps({'request': message, 'current_declaration': current,
                                                'layout': layout(current)})}]
    started = time.perf_counter()
    answer, usage = call(messages)
    answer, compiled, problems, usage, attempts = _checked(call, messages, answer, usage)
    rehearsal = None
    if compiled is not None and rehearse is not None:
        rehearsal = rehearse(compiled)
        # Up to MAX_REVISIONS times: what the engine measured goes back, with
        # where everything now stands, and the model revises its layout.
        for revision in range(MAX_REVISIONS):
            added = _new_stations(compiled, current)
            missed = [compiled['stations'][i]['title'] for i in added
                      if i < len(rehearsal['stations']) and not rehearsal['stations'][i]['done']]
            if not missed:
                break
            messages += [{'role': 'assistant', 'content': json.dumps(answer)},
                         {'role': 'user', 'content': json.dumps({
                             'rehearsal': {'world_time_s': rehearsal['world_time_s'], 'stations': rehearsal['stations'],
                                           'closest_approach': rehearsal.get('closest_approach', []),
                                           'events': rehearsal['events'][:50]},
                             'layout': layout(answer['spec']),
                             'instruction': 'The engine ran your machine. These new stations did not happen: '
                                            + ', '.join(missed) + '. Using the measured events and where each '
                                            'thing stands (layout), change positions, sizes, materials or joints so '
                                            'they can; keep everything else. Your reply describes the whole build and '
                                            'what the rehearsal showed.'})}]
            revised, more = call(messages)
            usage = _added(usage, more)
            revised, again, again_problems, usage, extra = _checked(call, messages, revised, usage)
            attempts += extra
            if again is None:
                rehearsal['revision_refused'] = again_problems
                break
            answer, compiled = revised, again
            rehearsal = rehearse(compiled)
    summary = None
    if rehearsal is not None:
        added = _new_stations(compiled, current)
        summary = {'world_time_s': rehearsal['world_time_s'], 'wall_s': rehearsal['wall_s'],
                   'new_stations': [{'title': compiled['stations'][i]['title'],
                                     'happened': bool(i < len(rehearsal['stations']) and rehearsal['stations'][i]['done']),
                                     'at_s': rehearsal['stations'][i]['at_s'] if i < len(rehearsal['stations']) else None}
                                    for i in added],
                   'error': rehearsal.get('error')}
    return {'ok': True, 'reply': str(answer.get('reply', ''))[:2000], 'spec': answer['spec'],
            'buildable': compiled is not None, 'problems': problems,
            'notes': compiled['notes'] if compiled else [], 'parts': len(compiled['parts']) if compiled else None,
            'attempts': attempts, 'model': model, 'seconds': round(time.perf_counter() - started, 2),
            'rehearsal': summary, 'usage': {k: v for k, v in usage.items() if isinstance(v, (int, float))}}
