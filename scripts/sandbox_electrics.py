"""Saved terminal graphs and placeable DC devices, solved by native Circuit.

Ideal topology is explicit; geometric crossings never connect. Each wire has a
fixed 0.01 ohm resistance. One finite supply owns all loads in its component.
"""
import copy
import math


def box(name, at, size, material='iron', fixed=True):
    return {'name': name, 'shape': 'box', 'material': material, 'at_m': at,
            'size_m': size, 'fixed': fixed}


def terminal_rows(name, x, y, z, switch=False):
    return {('in' if switch else 'plus'): [x - .08, y, z + .07],
            ('out' if switch else 'minus'): [x + .08, y, z + .07]}


def battery(name, k, ctx):
    x, z = k.get('x_m', 0), k.get('z_m', 0)
    capacity = k.get('capacity_j', 1000)
    part = name + ' housing'
    return {'parts': [box(part, [x, .08, z], [.2, .16, .14])],
            'batteries': [{'name': name + ' battery', 'in': part, 'capacity_j': capacity,
                           'charge_j': capacity * k.get('charge_percent', 100) / 100,
                           'voltage_v': k.get('voltage_v', 12), 'max_power_w': k.get('max_power_w', 200)}],
            'electrical': {'devices': [{'name': name, 'kind': 'battery', 'part': part,
                                        'battery': name + ' battery',
                                        'terminals': terminal_rows(name, x, .18, z)}]}}


def switch(name, k, ctx):
    x, z = k.get('x_m', 0), k.get('z_m', 0)
    part = name + ' housing'
    device = {'name': name, 'kind': 'switch', 'part': part,
              'closed': k.get('state', 'open') == 'closed',
              'terminals': terminal_rows(name, x, .13, z, True)}
    parts = [box(part, [x, .05, z], [.22, .1, .16], 'concrete')]
    joints = []
    if k.get('mode', 'manual') == 'paddle':
        paddle = name + ' paddle'
        parts.append(box(paddle, [x, .15, z], [.36, .04, .16], fixed=False))
        hinge = name + ' paddle axle'
        joints.append({'name': hinge, 'kind': 'hinge', 'a': part, 'b': paddle,
                       'at_m': [x, .15, z], 'axis': [0, 0, 1],
                       'lower_deg': -35, 'upper_deg': 35, 'friction_n_m': .002})
        device['hinge'] = hinge
        device['closed_at_or_below_deg'] = -k.get('threshold_deg', 8)
    else:
        parts.append(box(name + ' handle', [x + (.04 if device['closed'] else -.04), .15, z],
                         [.04, .1, .04], 'oak'))
    return {'parts': parts, 'joints': joints, 'electrical': {'devices': [device]}}


def bulb(name, k, ctx):
    x, z = k.get('x_m', 0), k.get('z_m', 0)
    y = k.get('height_m', .24)
    part = name + ' bulb'
    watts = {'small': 3, 'bright': 12}.get(k.get('preset', 'small'), 3)
    return {'parts': [box(name + ' base', [x, .04, z], [.2, .08, .16], 'concrete'),
                      box(name + ' stem', [x, y / 2, z], [.04, y, .04]),
                      {'name': part, 'shape': 'sphere', 'material': 'glass', 'size_m': [.1, .1, .1],
                       'at_m': [x, y + .05, z], 'fixed': True}],
            'electrical': {'devices': [{'name': name, 'kind': 'bulb', 'part': part,
                                        'terminals': terminal_rows(name, x, .1, z),
                                        'at_m': [x, y + .11, z], 'axis': [0, 1, 0],
                                        'watts': watts, 'rated_voltage_v': 12, 'efficiency': .2}]}}


def wire(name, k, ctx):
    return {'electrical': {'wires': [{'name': name, 'a': k.get('a_terminal', ''),
                                     'b': k.get('b_terminal', '')}]}}


def power_cable(name, k, ctx):
    """An ideal two-conductor charging lead; no cable loss or mass is modeled."""
    return {'electrical': {'power_cables': [{'name': name, 'a': k.get('a_port', ''),
                                            'b': k.get('b_port', '')}]}}


def motor(name, k, ctx):
    x, z = k.get('x_m', 0), k.get('z_m', 0)
    part = name + ' housing'
    hinge = k.get('hinge', 'included axle')
    parts = [box(part, [x, .18, z - .22], [.2, .36, .2], 'concrete')]
    joints = []
    if hinge == 'included axle':
        rotor = name + ' rotor'
        parts.append(box(rotor, [x, .34, z], [.4, .16, .12], fixed=False))
        hinge = name + ' axle'
        joints.append({'name': hinge, 'kind': 'hinge', 'a': part, 'b': rotor,
                       'at_m': [x, .34, z], 'axis': [0, 0, 1], 'friction_n_m': .001})
    else:
        # A driven axle belongs to a grounded mechanics frame. The motor's
        # torque reacts on that hinge's real mount, never a prescribed speed.
        pass
    return {'parts': parts, 'joints': joints, 'electrical': {'devices': [{
        'name': name, 'kind': 'motor', 'part': part, 'terminals': terminal_rows(name, x, .2, z),
        'hinge': hinge, 'stall_torque_n_m': 2, 'no_load_rad_s': 8,
        'command': k.get('throttle', 1) * (1 if k.get('direction', 'forward') == 'forward' else -1),
        'brake_torque_n_m': 0, 'gear_ratio': 1}]}}


def ignition(name, k, ctx):
    x, z = k.get('x_m', 0), k.get('z_m', 0)
    target = k.get('target', 'included oak cord')
    parts = [box(name + ' housing', [x, .04, z], [.18, .08, .14], 'concrete')]
    if target == 'included oak cord':
        target = name + ' target'
        parts.append(box(target, [x, .18, z], [.02, .2, .02], 'oak'))
    return {'parts': parts, 'electrical': {'devices': [{
        'name': name, 'kind': 'coil', 'part': name + ' housing', 'heats': target,
        'terminals': terminal_rows(name, x, .12, z),
        'resistance_ohm': {'warm': 12, 'hot': .12}.get(k.get('preset', 'warm'), 12)}]}}


def connected(builder):
    def make(name, k, ctx):
        fragment = builder(name, k, ctx)
        links = (ctx or {}).get('tray', {}).get('connect_to', {})
        for terminal, endpoint in links.items():
            fragment.setdefault('electrical', {}).setdefault('wires', []).append(
                {'name': name + ' socket ' + terminal, 'a': name + ':' + terminal, 'b': endpoint})
        return fragment
    return make


PIECES = {key: connected(value) for key, value in
          {'battery': battery, 'switch': switch, 'bulb': bulb, 'wire': wire,
           'motor': motor, 'ignition': ignition, 'power_cable': power_cable}.items()}


def knob(default, minimum, maximum, step, label):
    return {'default': default, 'min': minimum, 'max': maximum, 'step': step, 'label': label}


POS = {'x_m': knob(0, -2, 2, .02, 'along (m)'), 'z_m': knob(0, -2, 2, .02, 'across (m)')}
TRAY = [
    {'piece': 'battery', 'label': 'Battery', 'count': 8, 'cost': 1, 'turning': False,
     'description': 'A finite 12 V energy store with two labelled terminals.',
     'knobs': {**POS, 'voltage_v': knob(12, 6, 24, 6, 'voltage (V)'),
               'capacity_j': knob(1000, 100, 10000, 100, 'capacity (J)'),
               'charge_percent': knob(100, 0, 100, 10, 'initial charge (%)'),
               'max_power_w': knob(200, 10, 2000, 10, 'maximum power (W)')}},
    {'piece': 'switch', 'label': 'Switch', 'count': 12, 'cost': 1, 'turning': False,
     'description': 'Open or close a loop manually, or with a marble-operated paddle.',
     'knobs': {**POS, 'mode': {'default': 'manual', 'choices': ['manual', 'paddle'], 'label': 'operated by'},
               'state': {'default': 'open', 'choices': ['open', 'closed'], 'label': 'initial state'},
               'threshold_deg': knob(8, 2, 25, 1, 'paddle travel (degrees)')}},
    {'piece': 'bulb', 'label': 'Bulb', 'count': 12, 'cost': 1, 'turning': False,
     'description': 'Light and brightness come from solved circuit power.',
     'knobs': {**POS, 'height_m': knob(.24, .16, .6, .02, 'post height (m)'),
               'preset': {'default': 'small', 'choices': ['small', 'bright'], 'label': 'rated bulb'}}},
    {'piece': 'wire', 'label': 'Wire', 'count': 60, 'cost': 0, 'turning': False,
     'description': 'Connect two labelled electrical terminals; crossing lines never connect.',
     'knobs': {**POS, 'a_terminal': {'default': '', 'terminal': True, 'label': 'from terminal'},
               'b_terminal': {'default': '', 'terminal': True, 'label': 'to terminal'}}},
    {'piece': 'power_cable', 'label': 'Power cable', 'count': 20, 'cost': 0, 'turning': False,
     'description': 'An ideal two-conductor lead from a solar output to a battery input. Cable losses and mass are not modeled.',
     'knobs': {**POS, 'a_port': {'default': '', 'power_port': 'output', 'label': 'from solar output'},
               'b_port': {'default': '', 'power_port': 'input', 'label': 'to power input'}}},
    {'piece': 'motor', 'label': 'Motor', 'count': 8, 'cost': 1, 'turning': False,
     'description': 'A powered axle that reacts against its real hinge mount.',
     'knobs': {**POS, 'hinge': {'default': 'included axle', 'hinge': True, 'label': 'driven axle'},
               'direction': {'default': 'forward', 'choices': ['forward', 'reverse'], 'label': 'direction'},
               'throttle': knob(1, 0, 1, .1, 'throttle')}},
    {'piece': 'ignition', 'label': 'Heating coil', 'count': 8, 'cost': 1, 'turning': False,
     'description': 'A wired coil deposits real Joule heat in its attached material.',
     'knobs': {**POS, 'target': {'default': 'included oak cord', 'part': True, 'label': 'attached target'},
               'preset': {'default': 'warm', 'choices': ['warm', 'hot'], 'label': 'coil preset'}}},
]


def compile_power(spec, names, battery_names, problems):
    """Resolve explicit charging destinations without mutating saved declarations.

    A source may charge one store, and a store accepts one source. Parallel
    charging electronics, cable heating, sag and transmission loss are outside
    this model. Collection, saturation and consumption remain native laws.
    """
    raw = spec.get('electrical', {}) or {}
    if not isinstance(raw, dict):
        return {'power_ports': [], 'power_cables': []}, {}
    if any(not isinstance(raw.get(key, []), list) for key in ('power_ports', 'power_cables')):
        problems.append('electrical power_ports and power_cables must be arrays')
        return {'power_ports': [], 'power_cables': []}, {}
    ports, cables, overrides = {}, [], {}
    panels = {}
    for i, panel in enumerate(spec.get('solar_panels', []) or []):
        if not isinstance(panel, dict):
            continue
        name = panel.get('name') or f'panel {i + 1}'
        if not isinstance(name, str) or name in panels:
            problems.append('solar panel names must be strings and unique'); continue
        panels[name] = panel

    def valid_point(point):
        return (isinstance(point, list) and len(point) == 3 and
                all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in point))

    for p in raw.get('power_ports', []):
        if not isinstance(p, dict):
            problems.append('power ports must be objects'); continue
        name, kind = p.get('name'), p.get('kind')
        if not isinstance(name, str) or not name or name in ports:
            problems.append('power port names must be nonempty and unique'); continue
        if kind not in ('input', 'output') or not isinstance(p.get('part'), str) or p['part'] not in names or not valid_point(p.get('at_m')):
            problems.append(f'power port {name}: needs a housing, finite world position and input/output kind'); continue
        if kind == 'input' and (not isinstance(p.get('battery'), str) or p['battery'] not in battery_names):
            problems.append(f'power port {name}: input battery must name a finite store'); continue
        if kind == 'output' and (not isinstance(p.get('solar_panel'), str) or p['solar_panel'] not in panels or panels[p['solar_panel']].get('part') != p['part']):
            problems.append(f'power port {name}: output must name its solar panel'); continue
        ports[name] = copy.deepcopy(p)
    for panel, p in panels.items():
        if isinstance(p.get('part'), str) and p['part'] in names:
            name = panel + ':power'
            ports.setdefault(name, {'name': name, 'kind': 'output', 'solar_panel': panel,
                                    'part': p['part'], 'at_m': list(names[p['part']]['at_m'])})
    for device in raw.get('devices', []) if isinstance(raw.get('devices', []), list) else []:
        if not isinstance(device, dict) or device.get('kind') != 'battery' or device.get('part') not in names:
            continue
        terminals = device.get('terminals', {})
        pts = list(terminals.values()) if isinstance(terminals, dict) else []
        if pts and all(valid_point(p) for p in pts) and isinstance(device.get('name'), str):
            name = device['name'] + ':power'
            ports.setdefault(name, {'name': name, 'kind': 'input', 'battery': device.get('battery'),
                                    'part': device['part'], 'at_m': [sum(p[i] for p in pts) / len(pts) for i in range(3)]})
    used_sources, used_stores, cable_names = set(), set(), set()
    if len(ports) > 128 or len(raw.get('power_cables', [])) > 64:
        problems.append('electrical supports at most 128 power ports and 64 power cables')
    for cable in raw.get('power_cables', []):
        if not isinstance(cable, dict):
            problems.append('power cables must be objects'); continue
        name = cable.get('name')
        a = ports.get(cable.get('a')) if isinstance(cable.get('a'), str) else None
        b = ports.get(cable.get('b')) if isinstance(cable.get('b'), str) else None
        if not isinstance(name, str) or not name or name in cable_names:
            problems.append('power cable names must be nonempty and unique'); continue
        cable_names.add(name)
        if not a or not b or a['kind'] != 'output' or b['kind'] != 'input':
            problems.append(f'power cable {name}: connect an existing solar output to an existing power input'); continue
        source, store = a['solar_panel'], b['battery']
        if source in used_sources or store in used_stores:
            problems.append(f'power cable {name}: each solar output and battery input accepts one cable'); continue
        used_sources.add(source); used_stores.add(store)
        overrides[source] = store
        cables.append({'name': name, 'a': a['name'], 'b': b['name']})
    # Refuse implicit and explicit multi-source charging as well: otherwise a
    # second panel could bypass the unsupported parallel-source restriction.
    stores = {}
    for panel, p in panels.items():
        store = overrides.get(panel, p.get('battery'))
        if not isinstance(store, str):
            continue
        stores.setdefault(store, []).append(panel)
    for store, sources in stores.items():
        if len(sources) > 1 and any(source in overrides for source in sources):
            problems.append(f'power input {store}: parallel solar sources are not supported')
    return {'power_ports': list(ports.values()), 'power_cables': cables}, overrides


def compile_electrical(spec, names, joints, battery_names, problems):
    raw = spec.get('electrical', {}) or {}
    if not isinstance(raw, dict):
        problems.append('electrical must contain devices and wires'); return {}
    if any(not isinstance(raw.get(key, []), list) for key in ('devices', 'wires')):
        problems.append('electrical devices and wires must be arrays'); return {}
    devices, wires, terminals = [], [], {}
    ids = set()
    hinges = {j['name'] for j in joints if j['kind'] == 'hinge'}
    def number(row, key, default, low, high):
        value = row.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
            problems.append(f'electrical {row.get("name")}: {key} must be {low}..{high}'); return default
        return value
    if len(raw.get('devices', [])) > 64 or len(raw.get('wires', [])) > 128:
        problems.append('electrical supports at most 64 devices and 128 wires'); return {}
    for item in raw.get('devices', []):
        if not isinstance(item, dict):
            problems.append('electrical devices must be objects'); continue
        d = copy.deepcopy(item)
        name, kind = d.get('name'), d.get('kind')
        if not isinstance(name, str) or not name or name in ids:
            problems.append('electrical device names must be nonempty and unique'); continue
        ids.add(name)
        if kind not in ('battery', 'switch', 'bulb', 'motor', 'coil') or not isinstance(d.get('part'), str) or d['part'] not in names:
            problems.append(f'electrical {name}: unsupported kind or missing housing'); continue
        keys = ('in', 'out') if kind == 'switch' else ('plus', 'minus')
        if not isinstance(d.get('terminals'), dict) or set(d['terminals']) != set(keys):
            problems.append(f'electrical {name}: needs {" and ".join(keys)} terminals'); continue
        for key, xyz in d['terminals'].items():
            if not isinstance(xyz, list) or len(xyz) != 3 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in xyz):
                problems.append(f'electrical {name}: terminal positions are finite world coordinates'); continue
            terminals[name + ':' + key] = xyz
        if kind == 'battery' and (not isinstance(d.get('battery'), str) or d['battery'] not in battery_names):
            problems.append(f'electrical {name}: battery names its energy store')
        if kind == 'bulb':
            d['watts'] = number(d, 'watts', 3, .01, 1000)
            d['rated_voltage_v'] = number(d, 'rated_voltage_v', 12, 1, 1000)
            d['efficiency'] = number(d, 'efficiency', .2, 0, 1)
        if kind == 'coil':
            if not isinstance(d.get('heats'), str) or d['heats'] not in names: problems.append(f'electrical {name}: coil target is missing')
            d['resistance_ohm'] = number(d, 'resistance_ohm', 12, .01, 1e6)
        if kind == 'switch':
            if not isinstance(d.get('closed', False), bool): problems.append(f'electrical {name}: closed is boolean')
            if d.get('hinge'):
                if d['hinge'] not in hinges: problems.append(f'electrical {name}: paddle hinge is missing')
                d['closed_at_or_below_deg'] = number(d, 'closed_at_or_below_deg', -8, -179, 179)
        if kind == 'motor':
            if not isinstance(d.get('hinge'), str) or d['hinge'] not in hinges: problems.append(f'electrical {name}: driven hinge is missing')
            for key, default, low, high in [('stall_torque_n_m', 1, .01, 1e5), ('no_load_rad_s', 8, .01, 1e4),
                                          ('command', 1, -1, 1), ('gear_ratio', 1, .01, 1e4), ('brake_torque_n_m', 0, 0, 1e5)]:
                d[key] = number(d, key, default, low, high)
        devices.append(d)
    for w in raw.get('wires', []):
        if not isinstance(w, dict) or not isinstance(w.get('name'), str) or not w['name'] or w['name'] in ids:
            problems.append('electrical wire names must be nonempty and unique'); continue
        ids.add(w['name'])
        if not isinstance(w.get('a'), str) or not isinstance(w.get('b'), str) or w['a'] not in terminals or w['b'] not in terminals or w['a'] == w['b']:
            problems.append(f'electrical {w["name"]}: choose two different existing terminals'); continue
        wires.append({key: w[key] for key in ('name', 'a', 'b')})
    parent = {t: t for t in terminals}
    def find(t):
        while parent[t] != t: t = parent[t]
        return t
    def join(a, b): parent[find(a)] = find(b)
    for d in devices:
        ts = [d['name'] + ':' + k for k in d['terminals']]
        if all(t in parent for t in ts): join(*ts)
    for w in wires: join(w['a'], w['b'])
    groups = {}
    for d in devices:
        ts = [d['name'] + ':' + k for k in d['terminals']]
        if all(t in parent for t in ts): groups.setdefault(find(ts[0]), []).append(d)
    networks = []
    occupied = {c.get('battery') for c in spec.get('circuits', [])}
    for root, ds in groups.items():
        sources = [d for d in ds if d['kind'] == 'battery']
        if len(sources) > 1:
            problems.append('electrical: batteries cannot be interconnected; each graph has one supply'); continue
        if not sources: continue
        b = sources[0]
        if b['battery'] in occupied:
            problems.append(f'electrical: {b["battery"]} already supplies another circuit'); continue
        occupied.add(b['battery'])
        networks.append({'name': 'electrical ' + b['name'], 'battery': b['battery'], 'source': b,
                         'devices': ds, 'wires': [w for w in wires if find(w['a']) == root]})
    return {'devices': devices, 'wires': wires, 'networks': networks}


def build_electrical(engine, compiled, store_ids, joint_ids):
    circuits = {}
    for n in compiled.get('electrical', {}).get('networks', []):
        source = n['source']; branches = []; heats = []
        nodes = [d['name'] + ':' + t for d in n['devices'] for t in d['terminals']]
        heats.append({'id': 'supply', 'component': source['battery'], 'capacity_j_k': 2000, 'ambient_w_k': 1})
        for d in n['devices']:
            if d['kind'] == 'battery': continue
            keys = list(d['terminals'])
            row = {'id': d['name'], 'component': d['name'], 'a': d['name'] + ':' + keys[0],
                   'b': d['name'] + ':' + keys[1], 'thermal': d['name']}
            heats.append({'id': d['name'], 'component': d['name'], 'capacity_j_k': 100, 'ambient_w_k': 1})
            if d['kind'] == 'switch':
                row.update(kind='switch', resistance_ohm=.001, closed=d.get('closed', False))
                if d.get('hinge'): row['follows_hinge'] = {'joint': joint_ids[d['hinge']], 'closed_at_or_below_deg': d['closed_at_or_below_deg']}
            elif d['kind'] == 'coil':
                row.update(kind='resistor', resistance_ohm=d['resistance_ohm'], heats_body=d['heats'])
            elif d['kind'] == 'bulb':
                at = d.get('at_m', compiled['parts'][next(i for i, p in enumerate(compiled['parts']) if p['name'] == d['part'])]['at_m'])
                lamp = engine.op(op='lamp', name=d['name'], body=d['part'], store=0, watts=d['watts'],
                                 at_m=at, efficacy_lm_w=683)['lamp']
                engine.op(op='lamp_light', name=d['name'] + ' light', lamp=lamp, axis=d.get('axis', [0, 1, 0]),
                          half_angle_deg=179, radiant_efficacy_lm_w=683, rays=48, max_bounces=4)
                row.update(kind='bulb', lamp=lamp, resistance_ohm=d['rated_voltage_v'] ** 2 / d['watts'], efficiency=d['efficiency'])
            elif d['kind'] == 'motor':
                motor_id = engine.op(op='motor', joint=joint_ids[d['hinge']], store=store_ids[n['battery']],
                                     stall_torque_n_m=d['stall_torque_n_m'], no_load_rad_s=d['no_load_rad_s'],
                                     brake_torque_n_m=d['brake_torque_n_m'])['motor']
                engine.op(op='drive', motor=motor_id, command=d['command'])
                row.update(kind='motor', motor=motor_id, gear_ratio=d['gear_ratio'])
            branches.append(row)
        for w in n['wires']:
            branches.append({'id': w['name'], 'component': w['name'], 'kind': 'wire', 'a': w['a'], 'b': w['b'],
                             'resistance_ohm': .01, 'thermal': 'supply'})
        network = {'schema': 'banjo.circuit.v1', 'id': n['name'], 'nodes': nodes,
                   'source': {'store': store_ids[n['battery']], 'positive': source['name'] + ':plus',
                              'negative': source['name'] + ':minus', 'resistance_ohm': .05, 'thermal': 'supply'},
                   'thermal_nodes': heats, 'branches': branches}
        circuits[n['name']] = engine.op(op='circuit', network=network)['circuit']
    return circuits


def readouts(graph, native):
    branches = {b['id']: b for c in native for b in c['branches']}
    return {'devices': [dict(name=d['name'], kind=d['kind'], closed=branches.get(d['name'], {}).get('closed'),
                            current_a=branches.get(d['name'], {}).get('current_a', 0),
                            power_w=branches.get(d['name'], {}).get('power_w', 0),
                            emitted_w=branches.get(d['name'], {}).get('emitted_w', 0)) for d in graph.get('devices', [])],
            'wires': [dict(w, current_a=branches.get(w['name'], {}).get('current_a', 0)) for w in graph.get('wires', [])],
            'networks': [c for c in native if c['id'].startswith('electrical ')]}


def merge(spec, fragment):
    for key in ('parts', 'joints', 'batteries', 'kits'):
        spec.setdefault(key, []).extend(fragment.get(key, []))
    for key in ('devices', 'wires'):
        spec.setdefault('electrical', {}).setdefault(key, []).extend(fragment.get('electrical', {}).get(key, []))
    return spec


def empty(title):
    return {'schema': 'banjo.machine.v1', 'title': title, 'cell_m': .02, 'parts': [], 'stations': []}


def link(spec, name, a, b):
    spec['electrical'].setdefault('wires', []).append({'name': name, 'a': a, 'b': b})
    return spec


def manual_loop(closed=True, second_bulb=False, charge_j=1000):
    s = empty('Build your first circuit')
    merge(s, battery('supply', {'x_m': -.6, 'capacity_j': 1000, 'charge_percent': charge_j / 10}, {}))
    merge(s, switch('control', {'x_m': 0, 'state': 'closed' if closed else 'open'}, {}))
    merge(s, bulb('lamp', {'x_m': .6}, {}))
    for name, a, b in [('supply wire', 'supply:plus', 'control:in'), ('switched wire', 'control:out', 'lamp:plus'),
                       ('return wire', 'lamp:minus', 'supply:minus')]: link(s, name, a, b)
    if second_bulb:
        merge(s, bulb('second lamp', {'x_m': .6, 'z_m': .4}, {}))
        link(s, 'second feed', 'control:out', 'second lamp:plus')
        link(s, 'second return', 'second lamp:minus', 'supply:minus')
    return s


def marble_light():
    s = manual_loop()
    d = next(d for d in s['electrical']['devices'] if d['name'] == 'control')
    # Replace the manual housing with the general mechanically operated switch.
    s['parts'] = [p for p in s['parts'] if not p['name'].startswith('control ')]
    s['electrical']['devices'].remove(d)
    merge(s, switch('control', {'mode': 'paddle', 'x_m': 0, 'threshold_deg': 5}, {}))
    s['parts'].append({'name': 'trigger marble', 'shape': 'sphere', 'material': 'iron',
                       'size_m': [.1, .1, .1], 'at_m': [.12, .55, 0], 'fixed': False})
    return s


def motor_loop(command=1, charge_j=1000):
    s = empty('Motor and finite supply')
    merge(s, battery('supply', {'x_m': -.6, 'capacity_j': 1000, 'charge_percent': charge_j / 10}, {}))
    merge(s, motor('drive', {'x_m': 0, 'direction': 'forward' if command > 0 else 'reverse'}, {}))
    link(s, 'motor feed', 'supply:plus', 'drive:plus')
    link(s, 'motor return', 'drive:minus', 'supply:minus')
    return s


def heater_loop(material='oak', hot=True):
    s = empty('Heat and release')
    merge(s, battery('supply', {'x_m': -.6, 'capacity_j': 100000, 'max_power_w': 10000, 'voltage_v': 48}, {}))
    s['kits'] = [{'kit': 'hanging_weight', 'name': 'weight', 'post_m': [.8, 0, 0], 'drop_m': 1,
                  'peg_size_m': .02, 'peg_length_m': .3, 'weight_size_m': .16, 'weight_material': 'iron',
                  'side': '+z', 'holds_shear_n': 800, 'hang': 'rope', 'rope_m': .3}]
    merge(s, ignition('heater', {'x_m': 0, 'target': 'weight rope', 'preset': 'hot' if hot else 'warm'}, {}))
    link(s, 'heater feed', 'supply:plus', 'heater:plus'); link(s, 'heater return', 'heater:minus', 'supply:minus')
    if material != 'oak':
        # For controlled heating comparisons use identical declared boxes;
        # this is separate from the hanging cord's combustion demonstration.
        s['kits'] = []
        s['parts'].append(box('weight rope', [.8, .15, 0], [.04, .3, .04], material))
    return s


TEMPLATES = [
    {'name': 'Build your first circuit', 'description': 'A manual switch lights a finite-supply bulb. Inspect the terminals and shared energy ledger.',
     'base': manual_loop(), 'placements': []},
    {'name': 'Two bulbs one battery', 'description': 'Two parallel bulb branches share one battery and its current limit.',
     'base': manual_loop(second_bulb=True), 'placements': []},
    {'name': 'Marble turns on a light', 'description': 'An iron marble tilts a real hinged paddle and closes the bulb circuit.',
     'base': marble_light(), 'placements': []},
    {'name': 'Motor and finite supply', 'description': 'Battery current drives an axle; its real mount takes the reaction torque.',
     'base': motor_loop(), 'placements': []},
    {'name': 'Burn the cord', 'description': 'A battery coil heats an oak cord until it weakens and the hanging weight falls.',
     'base': heater_loop(), 'placements': []},
]


def tray(piece, **changes):
    row = copy.deepcopy(next(t for t in TRAY if t['piece'] == piece))
    row.update(count=1, sandbox_builder=True, **changes)
    return row


def easy(identifier, title, brief, base, row, solution, rule, wrong, seconds=4):
    return {'id': identifier, 'title': title, 'teaches': 'electricity', 'difficulty': 'easy',
            'brief': brief, 'time_s': seconds, 'budget': 1000, 'par': 1000, 'style_pieces': 1,
            'turning': False, 'machine': base, 'tray': [row], 'solution': [solution], 'wrong': [wrong],
            'hints': [brief, 'Inspect the measured power, charge and physical positions. An open loop cannot power the load.'],
            'goal': {'title': title, 'station': {'done_when': rule}, 'focus': []}}


def easy_levels():
    levels = []
    s = empty('Give it power'); merge(s, bulb('lamp', {'x_m': .6}, {}))
    row = tray('battery', connect_to={'plus': 'lamp:plus', 'minus': 'lamp:minus'})
    row['knobs']['x_m']['default'] = -.5
    levels.append(easy('easy-power', 'Give it power', 'Place a charged battery in the prepared two-terminal socket to keep the lamp on.',
                       s, row, {'piece': 'battery', 'x_m': -.5},
                       {'load_power_w': {'device': 'lamp', 'at_least_w': 2, 'for_s': .5}},
                       {'piece': 'battery', 'x_m': -.5, 'charge_percent': 0}))
    s = empty('Close the switch'); merge(s, battery('supply', {'x_m': -.6}, {})); merge(s, bulb('lamp', {'x_m': .6}, {}))
    link(s, 'return wire', 'lamp:minus', 'supply:minus')
    levels.append(easy('easy-switch', 'Close the switch', 'Set the manual switch to closed, then place it into the prepared circuit socket.',
                       s, tray('switch', connect_to={'in': 'supply:plus', 'out': 'lamp:plus'}),
                       {'piece': 'switch', 'state': 'closed'}, {'load_power_w': {'device': 'lamp', 'at_least_w': 2, 'for_s': .5}},
                       {'piece': 'switch', 'state': 'open'}))
    s = empty('Light the bulb'); merge(s, battery('supply', {'x_m': -.6}, {})); merge(s, switch('control', {'state': 'closed'}, {}))
    link(s, 'supply wire', 'supply:plus', 'control:in')
    levels.append(easy('easy-bulb', 'Light the bulb', 'Put a bulb into the prepared switched socket and run the circuit.',
                       s, tray('bulb', connect_to={'plus': 'control:out', 'minus': 'supply:minus'}),
                       {'piece': 'bulb', 'x_m': .6}, {'load_power_w': {'device': 'your bulb 1', 'at_least_w': 2, 'for_s': .5}},
                       {'piece': 'bulb', 'x_m': .6, 'preset': 'small'}, seconds=4))
    # A wrong bulb location is harmless in an ideal explicit wire graph. Its
    # wrong control is an open supply in the copied scenario, tested separately.
    levels[-1]['wrong'] = []
    s = manual_loop(); s['electrical']['wires'].pop()
    levels.append(easy('easy-loop', 'Finish the loop', 'Click lamp −, then supply − to draw the missing return wire. Run it to light the bulb. Crossing wires do not connect.',
                       s, tray('wire'), {'piece': 'wire', 'a_terminal': 'lamp:minus', 'b_terminal': 'supply:minus'},
                       {'load_power_w': {'device': 'lamp', 'at_least_w': 2, 'for_s': .5}},
                       {'piece': 'wire', 'a_terminal': 'lamp:minus', 'b_terminal': 'lamp:plus'}))
    s = empty('Turn the axle'); merge(s, battery('supply', {'x_m': -.6}, {}))
    levels.append(easy('easy-motor', 'Turn the axle', 'Place the motor into the prepared power socket, facing forward, to turn its flag.',
                       s, tray('motor', connect_to={'plus': 'supply:plus', 'minus': 'supply:minus'}),
                       {'piece': 'motor', 'direction': 'forward'}, {'hinge_beyond_deg': {'joint': 'your motor 1 axle', 'deg': 20}},
                       {'piece': 'motor', 'direction': 'reverse'}, seconds=1))
    s = heater_loop(); s['electrical']['devices'] = [d for d in s['electrical']['devices'] if d['kind'] != 'coil']
    s['parts'] = [p for p in s['parts'] if not p['name'].startswith('heater ')]
    s['electrical']['wires'] = []
    row = tray('ignition', connect_to={'plus': 'supply:plus', 'minus': 'supply:minus'})
    row['knobs']['target']['default'] = 'weight rope'
    levels.append(easy('easy-heat', 'Heat to release', 'Attach the hot coil to the prepared oak cord. Current must heat and weaken it before the weight falls.',
                       s, row, {'piece': 'ignition', 'target': 'weight rope', 'preset': 'hot'},
                       {'parted': 'weight rope'}, {'piece': 'ignition', 'target': 'weight rope', 'preset': 'warm'}, seconds=12))
    s = empty('Marble turns on a light'); merge(s, battery('supply', {'x_m': -.6}, {})); merge(s, bulb('lamp', {'x_m': .6}, {}))
    link(s, 'return wire', 'lamp:minus', 'supply:minus')
    s['parts'].append({'name': 'trigger marble', 'shape': 'sphere', 'material': 'iron',
                       'size_m': [.1, .1, .1], 'at_m': [.12, .55, 0], 'fixed': False})
    row = tray('switch', connect_to={'in': 'supply:plus', 'out': 'lamp:plus'})
    row['knobs']['mode']['default'] = 'paddle'
    levels.append(easy('easy-marble-light', 'Marble turns on a light',
                       'Set a paddle switch beneath the falling marble. Its real hinge closes the circuit when the right side tips down.',
                       s, row, {'piece': 'switch', 'mode': 'paddle', 'threshold_deg': 5},
                       {'load_power_w': {'device': 'lamp', 'at_least_w': 2, 'for_s': .1}},
                       {'piece': 'switch', 'mode': 'paddle', 'x_m': -.3, 'threshold_deg': 5}, seconds=3))
    return levels


EASY_LEVELS = easy_levels()
_PARS = {'easy-power': 882000000, 'easy-switch': 9200000, 'easy-bulb': 102000000,
         'easy-loop': 2, 'easy-motor': 1550000000, 'easy-heat': 4690000, 'easy-marble-light': 462000000}
for _level in EASY_LEVELS:
    _level['par_energy_j'] = _PARS[_level['id']]
for _template, _pieces in zip(TEMPLATES, [['battery', 'switch', 'bulb', 'wire'], ['battery', 'bulb', 'wire'],
                                       ['switch', 'bulb'], ['motor', 'battery'], ['ignition', 'battery']]):
    _template['pieces'] = _pieces
