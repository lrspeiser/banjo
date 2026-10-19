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
    builder = wall.WORLD_PIECES.get(piece) or wall.PIECES[piece]
    fragment = builder(name, knobs, {'tray': {'open_world': True}})
    def append(target, source):
        for key, rows in source.items():
            if isinstance(rows, dict):
                append(target.setdefault(key, {}), rows)
            else:
                target.setdefault(key, []).extend(copy.deepcopy(rows))
    append(spec, fragment)


def _tray(piece, start, **stock):
    source = next((key for key, value in wall.WORLD_ALIASES.items() if value == piece), piece)
    row = copy.deepcopy(next(t for t in wall.tray() if t['piece'] == source))
    row['piece'] = piece
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
    drop = _board('Drop into the cup')
    _fixture(drop, 'wall_cup', 'catching cup', x_m=.55, height_m=.4, width_m=.9)
    marble = _tray('wall_marble', [-.9, 2.5], diameter_m=.08, material='glass', placement='at height')
    marble['knobs']['height_m'].update(min=1.8)
    falling = _lesson('easy-wall-drop', 'Drop into the cup',
        'Drag the marble above the green cup, then Place and Run. Gravity drops it straight down. You only need to move across the wall.',
        drop, marble,
        dict(in_zone=dict(part='your wall_marble 1', at_m=[.55, .48, .3], size_m=[.7, .12, .32])),
        ['your wall_marble 1', 'catching cup cup'], [.55, 2.5], [-.9, 2.5],
        'The preview shows the falling path. Put that path through the open top of the cup.', 10100000)

    track = _board('Roll along the wall')
    _fixture(track, 'wall_marble', 'marble', x_m=-.85, height_m=2.65, diameter_m=.08, material='glass')
    _fixture(track, 'wall_cup', 'catching cup', x_m=.95, height_m=1.2, width_m=.85)
    route = _lesson('easy-wall-track', 'Roll along the wall',
        'Slide the sloping track under the marble so it rolls right into the green cup. Drag only left/right and up/down; the track stays attached to the wall.',
        track, _tray('wall_track', [.25, 1.05], length_m=1.8, angle_deg=-20, end_stop='closed'),
        dict(in_zone=dict(part='marble', at_m=[.95, 1.28, .3], size_m=[.65, .12, .32])),
        ['marble', 'catching cup cup'], [-.2, 2], [.25, 1.05],
        'The high end must sit beneath the marble. The low end sends it toward the cup.', 414000000)

    funnel = _board('Center the funnel')
    _fixture(funnel, 'wall_marble', 'marble', x_m=-.4, height_m=2.15, diameter_m=.08, material='glass')
    _fixture(funnel, 'wall_cup', 'catching cup', x_m=0, height_m=.4, width_m=.6)
    collecting = _lesson('easy-wall-funnel', 'Center the funnel',
        'Put the wide funnel under the marble and its narrow opening above the green cup. Its sloping sides guide the marble toward the middle.',
        funnel, _tray('wall_funnel', [.75, 1.4], width_m=1.2),
        dict(in_zone=dict(part='marble', at_m=[0, .48, .3], size_m=[.4, .12, .32])),
        ['marble', 'catching cup cup'], [0, 1.8], [.75, 1.4],
        'Both openings matter: the wide mouth catches the marble, and the narrow outlet must point into the cup.', 226000000)
    # Keep the cantilever's rear bracket on the 3 m backing at both limits.
    collecting['tray'][0]['knobs']['x_m'].update(min=-.8, max=.8)

    peg = _board('Bounce off a peg')
    _fixture(peg, 'wall_marble', 'marble', x_m=-.3, height_m=2.65, diameter_m=.08, material='glass')
    _fixture(peg, 'wall_cup', 'catching cup', x_m=.65, height_m=.4, width_m=1.2)
    bounce = _lesson('easy-wall-peg', 'Bounce off a peg',
        'Slide the round peg just left of the falling marble to bounce it right into the green cup. The wall keeps placement on one plane.',
        peg, _tray('wall_peg', [.7, 1.4], diameter_m=.4),
        dict(in_zone=dict(part='marble', at_m=[.65, .48, .3], size_m=[1, .12, .32])),
        ['marble', 'catching cup cup'], [-.44, 1.85], [.7, 1.4],
        'A hit on the peg’s right shoulder pushes the marble right. A hit at its very top has almost no sideways push.', 292000000)

    lever = _board('Tip the wall seesaw')
    _fixture(lever, 'wall_marble', 'marble', x_m=.3, height_m=2.65, diameter_m=.08, material='glass')
    tipping = _lesson('easy-wall-seesaw', 'Tip the wall seesaw',
        'Slide the seesaw so the marble lands on one end, away from the pivot. Its falling weight must tip the seesaw through 20 degrees.',
        lever, _tray('wall_lever', [-.75, 1.2], length_m=.9, angle_deg=0),
        dict(turned_deg=dict(joint='your wall_lever 1 axle', deg=20)),
        ['marble', 'your wall_lever 1 lever'], [0, 1.6], [-.75, 1.2],
        'A hit near the middle gives little turning force. Put one end beneath the falling path.', 130000000)

    wheel = _board('Turn a wall wheel')
    _fixture(wheel, 'wall_marble', 'marble', x_m=.18, height_m=2.65, diameter_m=.08, material='glass')
    _fixture(wheel, 'wall_cup', 'catching cup', x_m=.65, height_m=.4, width_m=1.15)
    turn = _lesson('easy-wall-wheel', 'Turn a wall wheel',
        'Move the paddle wheel under the marble, a little to one side of its axle. The falling marble must turn the wheel through a quarter turn. No motor or wiring is needed.',
        wheel, _tray('wall_water_wheel', [-.7, 1.35], radius_m=.3, paddles=8, phase_deg=0, friction_n_m=.002),
        dict(turned_deg=dict(joint='your wall_water_wheel 1 axle', deg=90)),
        ['marble', 'your wall_water_wheel 1 wheel'], [0, 1.6], [-.7, 1.35],
        'A marble falling beside the axle pushes a paddle and supplies torque. If it misses the paddles, the wheel stays still.', 193000000)
    circuit = _board('Connect the wall circuit')
    _fixture(circuit, 'wall_battery', 'wall battery', x_m=-.65, height_m=1)
    _fixture(circuit, 'wall_bulb', 'wall lamp', x_m=.65, height_m=1.8, preset='small')
    _fixture(circuit, 'wire', 'positive lead', a_terminal='wall battery:plus',
             b_terminal='wall lamp:plus', length_m=2.4)
    lead = copy.deepcopy(next(row for row in wall.tray() if row['piece'] == 'wire'))
    lead.update(count=1, wall_wire=True)
    for key, value in (('size','low resistance'),('length_m',2.4)):
        lead['knobs'][key].update(default=value, hidden=True)
    lead['knobs']['length_m'].update(min=2.4,max=2.4)
    lead['knobs']['size']['choices']=['low resistance']
    connect = dict(id='easy-wall-loop', title='Connect the wall circuit', difficulty='easy',
        teaches='a complete electrical loop', brief='The positive lead is ready. Click the lamp’s minus socket, then the battery’s minus socket to add the return wire. Run it to light the lamp.',
        time_s=6,budget=100,par=100,style_pieces=1,par_energy_j=1.05,
        machine=circuit,wall_mode=copy.deepcopy(circuit['build_surface']),tray=[lead],
        goal=dict(title='Light the wall lamp',focus=['wall lamp bulb'],
            station=dict(done_when=dict(load_power_w=dict(device='wall lamp',at_least_w=2,for_s=.3)))),
        hints=['Click the two minus sockets to close the return path.','A wire crossing another wire does not make a connection.'],
        solution=[dict(piece='wire',a_terminal='wall lamp:minus',b_terminal='wall battery:minus')],
        wrong=[dict(piece='wire',a_terminal='wall lamp:minus',b_terminal='wall lamp:plus')])

    press = _board('A marble lights the wall lamp')
    _fixture(press,'wall_battery','wall battery',x_m=-1,height_m=.7)
    _fixture(press,'wall_switch','press switch',x_m=0,height_m=1.2,mode='paddle',mechanism_version=3,threshold_deg=5)
    _fixture(press,'wall_bulb','wall lamp',x_m=1,height_m=.7,preset='small')
    for name,a,b,length in [('lamp lead','press switch:out','wall lamp:plus',2),
                           ('return lead','wall lamp:minus','wall battery:minus',3),
                           ('supply lead','wall battery:plus','press switch:in',2)]:
        _fixture(press,'wire',name,a_terminal=a,b_terminal=b,length_m=length)
    actuate = _lesson('easy-wall-switch','A marble lights the wall lamp',
        'Put the marble above the switch’s broad press deck. When it falls, the deck brings two metal contacts together and completes the wired lamp circuit.',
        press,_tray('wall_marble',[-.9,1.8],diameter_m=.10,material='iron',placement='at height'),
        dict(load_power_w=dict(device='wall lamp',at_least_w=2,for_s=.1)),
        ['press switch paddle','wall lamp bulb'],[.12,1.8],[-.9,1.8],
        'Use the broad deck to the right of the pivot. The wires stay dark until the metal contacts meet.',104000000)
    actuate['tray'][0]['knobs']['height_m']['min']=1.6

    def water_board(title):
        spec=_board(title)
        spec['ground']=dict(kind='flume',nx=40,nz=20,cell_m=.1,trench_z_m=.3,
            trench_width_m=.6,trench_depth_m=.35,trench_slope=.005,discharge_m3_s=0)
        return spec
    fill=water_board('Fill the wall receiver')
    _fixture(fill,'wall_water_collector','receiving box',x_m=.55,height_m=.5,width_m=.9)
    filling=_lesson('easy-wall-fill','Fill the wall receiver',
        'Move the tank above the receiver. Open its tap wide enough to collect 1 litre in 6 seconds. The tank holds a finite supply; its flow slows as it empties.',
        fill,_tray('wall_water_tank',[-.8,2.3],fill_l=4,outlet_model='gravity'),
        dict(water_in_zone_l=dict(at_m=[.55,.68,.3],size_m=[.8,.32,.48],l=1,for_s=.3)),
        ['receiving box cup','receiving box window'],[.55,2.3],[-.8,2.3],
        'The falling stream must enter the receiver. Tap opening controls how much arrives before the deadline.',293000000)
    filling['solution'][0]['opening_percent']=100
    filling['wrong'][0]['opening_percent']=100

    stream=water_board('Water drives the wall wheel')
    _fixture(stream,'wall_water_tank','water source',x_m=.15,height_m=2.3,fill_l=4,opening_percent=100)
    driving=_lesson('easy-wall-current','Water drives the wall wheel',
        'Put the paddle wheel under the falling stream, just to one side of its axle. Water must push its paddles through a quarter turn. The source runs dry.',
        stream,_tray('wall_water_wheel',[-.8,1.2],radius_m=.3,paddles=8,phase_deg=0,friction_n_m=.002),
        dict(turned_deg=dict(joint='your wall_water_wheel 1 axle',deg=90)),
        ['your wall_water_wheel 1 wheel','water source tank'],[0,1.3],[-.8,1.2],
        'The stream needs a lever arm: a hit beside the centre gives the axle turning force.',193000000)
    return [falling, route, collecting, bounce, tipping, turn, connect, actuate, filling, driving]
