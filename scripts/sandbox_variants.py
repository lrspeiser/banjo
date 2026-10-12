"""Versioned physical recipes for Easy challenges, with native preflight.

Constructing a recipe is cheap and deterministic; it does not prove a win.
Only preflight() returns a recipe marked validated. Seeds use an unsigned
32-bit integer, suitable for a share URL. Changing a recipe policy requires
a family version bump so previously shared designs retain their meaning.
"""
import copy
import hashlib
import math
import time
from pathlib import Path

VERSION = 1
FAMILY_VERSIONS = {family: 2 for family in ('easy-power', 'easy-switch', 'easy-bulb', 'easy-loop')}
FAMILY_VERSIONS['easy-switch'] = 3
MAX_ATTEMPTS = 3

# Each family changes one physical input. Prepared-piece parameters are
# fixed in the tray, so both the correct and wrong controls see the same
# generated apparatus. All goal rules, tolerances and deadlines stay intact.
POLICIES = {
    'easy-cut': ('kit', 'weight', 'rope_m', (.28, .29, .31, .32)),
    'easy-mirror': ('kit', 'source', 'watts', (8, 9, 11, 12)),
    'easy-lens': ('kit', 'source', 'watts', (9, 9.5, 10.5, 11)),
    'easy-solar': ('sun', None, 'elevation_deg', (12, 16, 18, 22)),
    'easy-tackle': ('piece', 'tackle', 'drop_from_m', (.9, .95, 1.05, 1.1)),
    'easy-spring': ('piece', 'spring', 'height_m', (.41, .42, .43, .44)),
    'easy-gears': ('piece', 'gears', 'friction_n_m', (.01, .015, .025, .03)),
    'easy-weight': ('kit', 'lever', 'length_m', (.66, .68, .72, .74)),
    'easy-water-wheel': ('piece', 'water_wheel', 'discharge_l_s', (1.5, 2.5, 3)),
    'easy-power': ('device', 'lamp', 'watts', (3.5, 4, 4.5, 5)),
    'easy-switch': ('battery', 'supply battery', 'voltage_v', (11, 11.5, 12.5, 13)),
    'easy-bulb': ('battery', 'supply battery', 'voltage_v', (11, 11.5, 12.5, 13)),
    'easy-loop': ('device', 'lamp', 'watts', (3.5, 4, 4.5, 5)),
    'easy-motor': ('battery', 'supply battery', 'voltage_v', (11, 11.5, 12.5, 13)),
    'easy-water-receiver': ('piece', 'water_tank', 'fill_l', (3.5, 4.5, 5, 5.5)),
    'easy-heat': ('battery', 'supply battery', 'voltage_v', (46, 47, 49, 50)),
    'easy-catapult': ('piece', 'catapult', 'cock_deg', (28, 29, 31, 32)),
    'easy-marble-light': ('part', 'trigger marble', 'height_m', (.48, .51, .59, .62)),
    'easy-water-gate': ('piece', 'water_wheel', 'discharge_l_s', (1.5, 2.5, 3)),
    'easy-charge-lift': ('sun', None, 'elevation_deg', (14, 16, 18, 22)),
    'easy-river-lift': ('ground', None, 'discharge_m3_s', (.095, .105, .11, .12)),
}

PARAMETER_LABELS = {
    'rope_m': 'Cord length (m)', 'watts': 'Optical or load power (W)',
    'elevation_deg': 'Sun elevation (degrees)', 'drop_from_m': 'Counterweight height (m)',
    'height_m': 'Starting height (m)', 'friction_n_m': 'Bearing friction (N m)',
    'length_m': 'Lever length (m)', 'discharge_l_s': 'Water supply (L/s)',
    'voltage_v': 'Supply voltage (V)', 'fill_l': 'Starting water (L)',
    'cock_deg': 'Cock angle (degrees)',
    'discharge_m3_s': 'River inflow (m³/s)',
}


def _seed(seed):
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 0xffffffff:
        raise ValueError('Challenge seed must be an unsigned 32-bit integer.')
    return seed


def family_version(family_id):
    if family_id not in POLICIES:
        raise ValueError('Only authored Easy families support seeded variants.')
    return FAMILY_VERSIONS.get(family_id, VERSION)


def _version(family_id, version):
    current = family_version(family_id)
    version = current if version is None else version
    supported = tuple(range(1, current + 1))
    if isinstance(version, bool) or not isinstance(version, int) or version not in supported:
        raise ValueError('Unsupported challenge recipe version.')
    return version


def identity(family_id, seed, attempt=0, *, version=None):
    if family_id not in POLICIES:
        raise ValueError('Only authored Easy families support seeded variants.')
    if attempt is not None and (isinstance(attempt, bool) or not isinstance(attempt, int) or not 0 <= attempt < MAX_ATTEMPTS):
        raise ValueError('Unsupported challenge recipe attempt.')
    version = _version(family_id, version)
    return f'{family_id}--v{version}--{_seed(seed):08x}--{attempt if attempt is not None else "c"}'


def parse(identifier):
    """Decode an exact shared recipe, including its accepted retry/fallback."""
    try:
        family, version, seed, attempt = identifier.split('--')
        if not version.startswith('v') or len(seed) != 8:
            raise ValueError()
        version = int(version[1:])
        seed = int(seed, 16)
        attempt = None if attempt == 'c' else int(attempt)
        if identity(family, seed, attempt, version=version) != identifier:
            raise ValueError()
        return {'family': family, 'seed': seed, 'attempt': attempt, 'version': version}
    except (AttributeError, TypeError, ValueError):
        raise ValueError('Unsupported generated challenge ID.') from None


def _metadata(family, seed, attempt, fallback=False, *, version=None):
    return {'family': family, 'seed': seed, 'version': _version(family, version),
            'attempt': attempt, 'fallback': fallback, 'validated': False}


def _apparatus(family_level, version):
    """Preserve v1 declarations; compilation may migrate old manual handles.

    Their identifiers, initial states, terminal graph and seeded parameter
    choices stay intact. The current compiler upgrades fixed manual handles
    to movable rockers without changing the saved declaration itself.
    """
    result = copy.deepcopy(family_level)
    family = family_level['id']
    if family == 'easy-switch' and version < 3:
        # Keep both earlier recipes' starting-pose choice and solution.
        result['tray'][0]['knobs']['state']['choices'] = ['open', 'closed']
        result['tray'][0]['knobs']['mode']['choices'] = ['manual', 'paddle']
        result['solution'] = [{'piece': 'switch', 'state': 'closed'}]
        result.pop('solution_inputs', None)
        result['brief'] = 'Place the wired switch, then drag its field handle downward to close the lamp circuit. Its initial state sets its starting physical position.'
        result['hints'][0] = result['brief']
    if family not in FAMILY_VERSIONS or version != 1:
        return result
    import sandbox_electrics as electrical
    if family != 'easy-power':
        if family == 'easy-switch':
            base = electrical.empty('Close the switch')
            electrical.merge(base, electrical.battery('supply', {'x_m': -.6}, {}))
            electrical.merge(base, electrical.bulb('lamp', {'x_m': .6}, {}))
            electrical.link(base, 'return wire', 'lamp:minus', 'supply:minus')
            row = electrical.tray('switch', legacy_manual=True,
                connect_to={'in': 'supply:plus', 'out': 'lamp:plus'})
            row['knobs'] = {key: row['knobs'][key] for key in ('x_m', 'z_m', 'mode', 'state', 'threshold_deg')}
            result.update(machine=base, tray=[row], solution=[{'piece': 'switch', 'state': 'closed'}],
                wrong=[{'piece': 'switch', 'state': 'open'}], par_energy_j=9200000,
                brief='Set the manual switch to closed, then place it into the prepared circuit socket.')
        else:
            base = electrical.empty('Light the bulb' if family == 'easy-bulb' else 'Build your first circuit')
            electrical.merge(base, electrical.battery('supply', {'x_m': -.6}, {}))
            electrical.merge(base, electrical.legacy_manual_switch('control', {'state': 'closed'}, {}))
            electrical.link(base, 'supply wire', 'supply:plus', 'control:in')
            if family == 'easy-loop':
                electrical.merge(base, electrical.bulb('lamp', {'x_m': .6}, {}))
                electrical.link(base, 'switched wire', 'control:out', 'lamp:plus')
            result['machine'] = base
        result['hints'] = [result['brief'], 'Inspect the measured power, charge and physical positions. An open loop cannot power the load.']
        return result
    base = electrical.empty('Give it power')
    electrical.merge(base, electrical.bulb('lamp', {'x_m': .6}, {}))
    row = electrical.tray('battery', connect_to={'plus': 'lamp:plus', 'minus': 'lamp:minus'})
    # The original tray had only these knobs; later mobile-pack defaults must
    # never turn an old share into a falling or material-selectable battery.
    keys = ('x_m', 'z_m', 'voltage_v', 'capacity_j', 'charge_percent', 'max_power_w')
    row['knobs'] = {key: row['knobs'][key] for key in keys}
    row['knobs']['x_m']['default'] = -.5
    result.update(machine=base, tray=[row], solution=[{'piece': 'battery', 'x_m': -.5}],
                  wrong=[{'piece': 'battery', 'x_m': -.5, 'charge_percent': 0}],
                  brief='Place a charged battery in the prepared two-terminal socket to keep the lamp on.',
                  par_energy_j=882000000)
    result['hints'] = [result['brief'], 'Inspect the measured power, charge and physical positions. An open loop cannot power the load.']
    return result


def construct(family_level, seed, *, attempt=0, version=None):
    """Deep-copy a canonical family and change a single bounded input.

    Private solution/wrong arrays remain private; callers must use the game
    public serializer. attempt is an internal deterministic retry index.
    """
    seed = _seed(seed)
    family = family_level['id']
    if family_level.get('variant') or family not in POLICIES:
        raise ValueError('Construct requires an authored canonical Easy family.')
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 0 <= attempt < MAX_ATTEMPTS:
        raise ValueError(f'Retry index must be between 0 and {MAX_ATTEMPTS - 1}.')
    version = _version(family, version)
    result = _apparatus(family_level, version)
    result['id'] = identity(family, seed, attempt, version=version)
    kind, name, parameter, values = POLICIES[family]
    digest = hashlib.sha256(f'banjo-easy:{version}:{family}:{seed}'.encode('ascii')).digest()
    value = values[(int.from_bytes(digest[:8], 'big') + attempt) % len(values)]
    if kind == 'piece':
        row = next(row for row in result['tray'] if row['piece'] == name)
        rule = row['knobs'][parameter]
        rule.update(min=value, max=value, default=value)
        # A step only affects UI rounding. Use a step that represents the
        # generated value, including the half-centimetre spring presets.
        rule['step'] = min(rule.get('step', .01), .001)
        rule['label'] = rule.get('label', parameter) + ' (prepared for this challenge)'
        for answer in ('solution', 'wrong'):
            for placement in result.get(answer, []):
                if placement['piece'] == name:
                    placement[parameter] = value
    elif kind == 'ground':
        result['machine']['ground'][parameter] = value
    elif kind == 'sun':
        result['machine']['sun'][parameter] = value
        for placement in result['solution']:
            if placement['piece'] == 'solar':
                placement['pitch_deg'] = 90 - value
    else:
        collection = {'kit': result['machine'].get('kits', []),
                      'battery': result['machine'].get('batteries', []),
                      'part': result['machine'].get('parts', []),
                      'device': result['machine'].get('electrical', {}).get('devices', [])}[kind]
        item = next(item for item in collection if item['name'] == name)
        if parameter == 'height_m':
            item['at_m'][1] = value
        else:
            item[parameter] = value
    result['variant'] = dict(_metadata(family, seed, attempt, version=version), parameter=parameter,
                             parameter_label=PARAMETER_LABELS[parameter],
                             kind=kind, value=value)
    return result


def _trial(level, placements, native, logs, *, handle_inputs=None):
    import machine_game as game
    import machine_world as world
    # A missing inserted part is an absent physical goal, not a declaration
    # failure. Still run the empty apparatus in the native engine.
    spec, _, _ = game.compose(level, placements, leave_out_goal=True)
    compiled = world.compile_spec(spec)
    outcomes = []
    for nudge in range(3):
        run = world.rehearse(game.nudged(compiled, nudge + 1) if nudge else compiled,
                             native, logs, seconds=level['time_s'] + .5, wall_limit_s=120,
                             handle_inputs=handle_inputs)
        station = (run.get('stations') or [{}])[0]
        reached = station.get('at_s') if station.get('done') else None
        error = run.get('error')
        if not error and reached is None and run['world_time_s'] < level['time_s']:
            error = 'Native rehearsal stopped before the challenge deadline.'
        energy = game.energy_of(compiled, run.get('readouts'), run['world_time_s'])
        outcomes.append({'goal_at_s': reached, 'error': error, 'energy_j': energy['j']})
    return {'runs': 3, 'worked': sum(o['goal_at_s'] is not None and
            o['goal_at_s'] <= level['time_s'] for o in outcomes), 'results': outcomes}


def validate(candidate, native, logs):
    """Measure correct, empty and wrong controls, with three nudges each.

    Engine/declaration errors fail preflight even if the errored control did
    not reach its goal. No tolerance, goal or deadline is relaxed here.
    """
    native = Path(native).resolve()
    if not native.is_file():
        raise FileNotFoundError(native)
    logs = Path(logs)
    logs.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    receipt = {'valid': False, 'engine_sha256': hashlib.sha256(native.read_bytes()).hexdigest(),
               'scenarios': {}}
    for label, placements in [('solution', candidate['solution']), ('empty', []),
                               ('wrong', candidate.get('wrong', []))]:
        try:
            receipt['scenarios'][label] = _trial(candidate, placements, native, logs,
                **({'handle_inputs':candidate['solution_inputs']}
                   if label=='solution' and candidate.get('solution_inputs') else {}))
        except Exception as error:
            receipt['scenarios'][label] = {'runs': 0, 'worked': 0,
                                           'error': f'{type(error).__name__}: {error}'}
    scenarios = receipt['scenarios']
    clean = all(s['runs'] == 3 and not s.get('error') and
                not any(r.get('error') for r in s.get('results', [])) for s in scenarios.values())
    receipt['valid'] = clean and scenarios['solution']['worked'] == 3 and \
        scenarios['empty']['worked'] == 0 and scenarios['wrong']['worked'] == 0
    if receipt['valid']:
        receipt['mean_energy_j'] = sum(r['energy_j'] for r in scenarios['solution']['results']) / 3
    receipt['wall_s'] = round(time.perf_counter() - started, 6)
    return receipt


class VariantRefused(RuntimeError):
    """Neither the generated recipes nor the canonical fallback passed."""
    def __init__(self, receipts):
        super().__init__('Generated challenge and canonical fallback failed native preflight.')
        self.receipts = receipts


def preflight(family_level, seed, native, logs, *, max_attempts=MAX_ATTEMPTS):
    """Return a measured recipe or refuse; never return an untested fallback.

    A successful result has variant.validation and variant.attempts receipts.
    Canonical fallback is explicitly marked, retaining the requested share
    identity and seed. At most three candidates plus one fallback are tried.
    Native failures propagate as diagnostics rather than a playable success.
    """
    seed = _seed(seed)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise ValueError(f'max_attempts must be between 1 and {MAX_ATTEMPTS}.')
    receipts = []
    candidates = [construct(family_level, seed, attempt=i) for i in range(max_attempts)]
    fallback = reconstruct(family_level, seed, None)
    candidates.append(fallback)
    for candidate in candidates:
        receipt = validate(candidate, native, logs)
        receipts.append(dict(attempt=candidate['variant']['attempt'],
                             fallback=candidate['variant']['fallback'], **receipt))
        if not receipt['valid']:
            continue
        # Material-derived fabrication and energy consumed are measured for
        # this actual recipe, rather than borrowing its family's old score.
        energy = receipt['mean_energy_j']
        quantum = 10 ** (math.floor(math.log10(max(energy, 1e-12))) - 2)
        candidate['par_energy_j'] = math.ceil(energy / quantum) * quantum
        candidate['variant'].update(validated=True, validation=receipt, attempts=receipts,
                                    measured_energy_j=energy)
        return candidate
    raise VariantRefused(receipts)


def reconstruct(family_level, seed, attempt, *, version=None):
    """Recreate an exact recipe; callers must validate it before first use."""
    if attempt is not None:
        return construct(family_level, seed, attempt=attempt, version=version)
    seed = _seed(seed)
    version = _version(family_level['id'], version)
    fallback = _apparatus(family_level, version)
    fallback['id'] = identity(family_level['id'], seed, None, version=version)
    fallback['variant'] = _metadata(family_level['id'], seed, None, fallback=True, version=version)
    return fallback
