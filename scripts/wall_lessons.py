"""Small authored lessons using the sandbox's physical wall-mounted tools.

The wall constrains editing, not motion: marbles are free 3D bodies, tracks
have real rails, and paddle wheels use the ordinary native hinge/contact law.
"""
import copy

import sandbox_wall as wall


def _board(title):
    panel = dict(id='workshop backing', width_m=3, height_m=3, x_m=0, z_m=0)
    return dict(schema='banjo.machine.v1', title=title, cell_m=.02,
                build_surface=wall.panel_surface([panel]),
                parts=[wall.panel_part(panel)], kits=[], joints=[], stations=[])


def _fixture(spec, piece, name, **knobs):
    fragment = wall.WORLD_PIECES[piece](name, knobs, {'tray': {'open_world': True}})
    for key, rows in fragment.items():
        spec.setdefault(key, []).extend(rows)


def _tray(piece, start, **stock):
    row = copy.deepcopy(next(t for t in wall.tray() if t['piece'] == piece))
    row.update(count=1, wall_mounted=True, open_world=True, start_at_defaults=True)
    row['knobs']['wall'] = dict(choices=['workshop backing'], default='workshop backing', hidden=True)
    row['knobs']['x_m'].update(min=-1.25, max=1.25, default=start[0])
    row['knobs']['height_m'].update(min=.4, max=2.6, default=start[1])
    for key, value in stock.items():
        rule = row['knobs'][key]
        rule.update(default=value, hidden=True)
        rule.pop('turning', None)
        if 'choices' in rule:
            rule['choices'] = [value]
        else:
            rule.update(min=value, max=value)
    return row


def _lesson(identity, title, brief, machine, row, rule, focus, solution, wrong, hint, par):
    return dict(id=identity, title=title, difficulty='easy', teaches='gravity and contact',
                brief=brief, time_s=6, budget=100, par=100, style_pieces=1, par_energy_j=par,
                machine=machine, wall_mode=copy.deepcopy(machine['build_surface']), tray=[row],
                goal=dict(title=title, focus=focus, station=dict(done_when=rule)),
                hints=[brief, hint], solution=[dict(piece=row['piece'], x_m=solution[0], height_m=solution[1])],
                wrong=[dict(piece=row['piece'], x_m=wrong[0], height_m=wrong[1])])


def levels():
    track = _board('Roll along the wall')
    _fixture(track, 'wall_marble', 'marble', x_m=-.85, height_m=2.65, diameter_m=.08, material='glass')
    _fixture(track, 'wall_cup', 'catching cup', x_m=.95, height_m=1.2, width_m=.85)
    route = _lesson('easy-wall-track', 'Roll along the wall',
        'Slide the sloping track under the marble so it rolls right into the green cup. Drag only left/right and up/down; the track stays attached to the wall.',
        track, _tray('wall_track', [.25, 1.05], length_m=1.8, angle_deg=-20, end_stop='closed'),
        dict(in_zone=dict(part='marble', at_m=[.95, 1.28, .3], size_m=[.65, .12, .32])),
        ['marble', 'catching cup cup'], [-.2, 2], [.25, 1.05],
        'The high end must sit beneath the marble. The low end sends it toward the cup.', 414000000)

    peg = _board('Bounce off a peg')
    _fixture(peg, 'wall_marble', 'marble', x_m=-.3, height_m=2.65, diameter_m=.08, material='glass')
    _fixture(peg, 'wall_cup', 'catching cup', x_m=.65, height_m=.4, width_m=1.2)
    bounce = _lesson('easy-wall-peg', 'Bounce off a peg',
        'Slide the round peg just left of the falling marble to bounce it right into the green cup. The wall keeps placement on one plane.',
        peg, _tray('wall_peg', [.7, 1.4], diameter_m=.4),
        dict(in_zone=dict(part='marble', at_m=[.65, .48, .3], size_m=[1, .12, .32])),
        ['marble', 'catching cup cup'], [-.44, 1.85], [.7, 1.4],
        'A hit on the peg’s right shoulder pushes the marble right. A hit at its very top has almost no sideways push.', 292000000)

    wheel = _board('Turn a wall wheel')
    _fixture(wheel, 'wall_marble', 'marble', x_m=.18, height_m=2.65, diameter_m=.08, material='glass')
    _fixture(wheel, 'wall_cup', 'catching cup', x_m=.65, height_m=.4, width_m=1.15)
    turn = _lesson('easy-wall-wheel', 'Turn a wall wheel',
        'Move the paddle wheel under the marble, a little to one side of its axle. The falling marble must turn the wheel through a quarter turn. No motor or wiring is needed.',
        wheel, _tray('wall_water_wheel', [-.7, 1.35], radius_m=.3, paddles=8, phase_deg=0, friction_n_m=.002),
        dict(turned_deg=dict(joint='your wall_water_wheel 1 axle', deg=90)),
        ['marble', 'your wall_water_wheel 1 wheel'], [0, 1.6], [-.7, 1.35],
        'A marble falling beside the axle pushes a paddle and supplies torque. If it misses the paddles, the wheel stays still.', 193000000)
    return [route, bounce, turn]
