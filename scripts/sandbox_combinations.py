"""Combined easy machine: sunlight supplies a previously empty motor battery."""
import copy
import sandbox_electrics as electrics
import sandbox_mechanics as mechanics

PIECES = {}
TRAY = []


def charge_and_lift():
    base = electrics.empty('Charge then lift')
    electrics.merge(base, electrics.battery('supply', {'x_m': -.6, 'capacity_j': 1000,
                                                      'charge_percent': 0}, {}))
    electrics.merge(base, electrics.motor('drive', {'x_m': 0, 'hinge': 'drive axle'}, {}))
    # An offset oak lifting arm, rather than a balanced rotor that could
    # satisfy an angle goal using minute gravitational/numerical motion.
    base['parts'] += [mechanics.box('drive frame', [.08, .84, .08], [0, .42, -.12]),
                      mechanics.box('flag', [.5, .06, .12], [.15, .8, 0], 'oak', False)]
    base['joints'] = [{'name': 'drive axle', 'kind': 'hinge', 'a': 'drive frame', 'b': 'flag',
                       'at_m': [0, .8, 0], 'axis': [0, 0, 1], 'friction_n_m': .001,
                       'ratchet': {'at_or_above_deg': 0}}]
    drive = next(d for d in base['electrical']['devices'] if d['name'] == 'drive')
    drive.update(stall_torque_n_m=5, no_load_rad_s=6)
    electrics.link(base, 'motor feed', 'supply:plus', 'drive:plus')
    electrics.link(base, 'motor return', 'drive:minus', 'supply:minus')
    # A visible parallel light makes the available source power matter: a
    # flat panel cannot maintain enough bus voltage against this real load.
    electrics.merge(base, electrics.bulb('charge light', {'x_m': -1, 'z_m': .5}, {}))
    next(d for d in base['electrical']['devices'] if d['name'] == 'charge light')['watts'] = 30
    electrics.link(base, 'light feed', 'supply:plus', 'charge light:plus')
    electrics.link(base, 'light return', 'charge light:minus', 'supply:minus')
    base['title'] = 'Charge then lift'
    base['sun'] = {'azimuth_deg': 180, 'elevation_deg': 20, 'irradiance_w_m2': 1000}
    row = copy.deepcopy(next(t for t in mechanics.TRAY if t['piece'] == 'solar'))
    row.update(count=1, sandbox_builder=True)
    row['knobs']['battery']['default'] = 'supply battery'
    row['knobs']['x_m']['default'] = .8
    solution = {'piece': 'solar', 'x_m': .8, 'battery': 'supply battery', 'yaw_deg': -90, 'pitch_deg': 70}
    level = dict(id='easy-charge-lift', title='Charge then lift', difficulty='easy', teaches='sunlight, storage and motor torque',
                 brief='The motor battery starts empty. Aim the connected panel at the low sun to power the axle and lift its flag.',
                 machine=base, tray=[row], solution=[solution], wrong=[dict(solution, pitch_deg=0)],
                 time_s=4, budget=1000, par=1000, style_pieces=1,
                 par_energy_j=192000000,
                 hints=['The panel needs light; the motor has no starting charge.',
                        'The parallel bulb shares its battery. Aim the panel to supply enough real power for both loads.'],
                 goal=dict(title='Raise the motor flag', station=dict(done_when={'rose_m': {'part': 'flag', 'm': .05}})))
    return level


EASY_LEVELS = [charge_and_lift()]
TEMPLATES = [dict(name='Sun powers the flag', description='An empty battery supplies a motor that raises an offset oak arm. A parallel bulb shares the available solar power.',
                  base=copy.deepcopy(EASY_LEVELS[0]['machine']), placements=copy.deepcopy(EASY_LEVELS[0]['solution']),
                  pieces=['solar', 'motor', 'battery', 'wire'])]
