"""Saved terminal graphs and placeable DC devices, solved by native Circuit.

Ideal topology is explicit; geometric crossings never connect. Each wire has a
legacy 0.01 ohm resistance, or copper resistance from declared length and area.
One finite supply owns all loads in its component.
"""
import copy
import math
import sandbox_battery_socket as socket
import mechanical_cables

# Build the archived recipes first; new pieces below use measured metal contact.
CONTACT_SWITCHES = False


def box(name, at, size, material='iron', fixed=True):
    return {'name': name, 'shape': 'box', 'material': material, 'at_m': at,
            'size_m': size, 'fixed': fixed}


def terminal_rows(name, x, y, z, switch=False):
    return {('in' if switch else 'plus'): [x - .08, y, z + .07],
            ('out' if switch else 'minus'): [x + .08, y, z + .07]}


def motor_terminals(housing):
    """Connection points on the fixed, axis-aligned motor housing's rear."""
    x,y,z=housing['at_m'];width,height,depth=housing['size_m']
    return {key:[x+side*width/3,y+min(.02,height/4),z-depth/2-.005]
            for key,side in [('plus',-1),('minus',1)]}


def battery(name, k, ctx):
    if k.get('mount') == 'contact pack':
        return socket.battery(name, k, ctx)
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
    if (ctx or {}).get('tray', {}).get('legacy_manual') and k.get('mode','manual')!='paddle':
        return legacy_manual_switch(name, k, ctx)
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
        # Fixed housing jacks clear the underside of the legacy paddle's
        # swept volume. The newer metal-contact versions override these pads.
        device['terminals'] = {key:[x+side*.08,.07,z+.09]
                               for key,side in [('in',-1),('out',1)]}
        device['terminal_normals'] = {'in':[0,0,1],'out':[0,0,1]}
    else:
        # The rocker is an ordinary body, held by its own frictional hinge.
        # Its centre of mass is on the axle: gravity does not choose a state.
        # The hinge is made in the initial facing, so its readings are relative
        # to that facing; the electrical threshold is the physical horizontal.
        initial_deg = -25 if device['closed'] else 25
        angle = math.radians(initial_deg)
        handle, axle, hinge = name + ' handle', name + ' axle', name + ' rocker hinge'
        material = k.get('handle_material', 'oak')
        if material not in ('glass', 'oak', 'iron'):
            raise ValueError('Rocker material must be glass, oak or iron.')
        parts += [box(name + ' post', [x, .12, z - .12], [.04, .24, .04], 'concrete'),
                  box(axle, [x, .22, z - .07], [.02, .02, .08]),
                  dict(box(handle, [x, .22, z], [.20, .04, .06], material, False),
                       turn_deg=[0, 0, initial_deg])]
        joints.append(dict(name=hinge, kind='hinge', a=axle, b=handle,
            at_m=[x, .22, z - .03], axis=[0, 0, 1], lower_deg=-25-initial_deg,
            upper_deg=25-initial_deg, friction_n_m=.08))
        device['hinge'] = hinge
        device['closed_at_or_below_deg'] = -initial_deg
        device['handle'] = dict(part=handle,
            at_m=[x + .08 * math.cos(angle), .22 + .08 * math.sin(angle), z])
    result = {'parts': parts, 'joints': joints, 'electrical': {'devices': [device]}}
    if CONTACT_SWITCHES and not (ctx or {}).get('tray', {}).get('legacy_contacts'):
        add_switch_contacts(result, device)
        if k.get('mode') == 'paddle' and k.get('mechanism_version', 2) == 3:
            press_paddle(result, device)
    return result


def press_paddle(spec, device):
    """An exposed press deck on one side of a gravity counterbalanced hinge.

    All boxes belong to connected compounds; contact, mass and hinge torque
    decide closure. The lower counterbalance is deliberately not a press deck.
    The open frame leaves clearance for both it and the metal contact stem.
    """
    moving = next(p for p in spec['parts'] if p['name'] == device['name']+' paddle')
    moving.update(shape='compound', parts=[
        dict(shape='box', at_m=[.10,0,0], size_m=[.16,.04,.12]),
        dict(shape='box', at_m=[-.13,-.06,0], size_m=[.16,.10,.06]),
        dict(shape='box', at_m=[0,0,0], size_m=[.04,.02,.08]),
        dict(shape='box', at_m=[-.03,-.025,0], size_m=[.04,.07,.06]),
        dict(shape='box', at_m=[.19,.02,0], size_m=[.02,.04,.16]),
        dict(shape='box', at_m=[.10,.02,-.07], size_m=[.16,.04,.02]),
        dict(shape='box', at_m=[.10,.02,.07], size_m=[.16,.04,.02]),
        dict(shape='box', at_m=[.01,.02,0], size_m=[.02,.04,.12])])
    moving.pop('size_m', None)
    housing = next(p for p in spec['parts'] if p['name'] == device['part'])
    x, _, z = housing['at_m']
    housing.update(shape='compound', at_m=[x,0,z], parts=[
        dict(shape='box', at_m=[0,.01,0], size_m=[.26,.02,.24]),
        dict(shape='box', at_m=[0,.08,-.10], size_m=[.04,.14,.04]),
        dict(shape='box', at_m=[-.08,.08,-.10], size_m=[.04,.14,.04])])
    housing.pop('size_m', None)


def add_switch_contacts(spec, device):
    """A leaf fixed to the rocker touches a supported metal output pad.

    Native body contact closes the branch, not its angle or a drawn animation.
    Iron conductors and concrete supports are separate from the handle material.
    The existing 1 mm contact observation and 0.001 ohm lumped interface apply.
    """
    hinge = next(j for j in spec['joints'] if j['name'] == device['hinge'])
    moving = next(p for p in spec['parts'] if p['name'] == hinge['b'])
    x, y, z = moving['at_m']
    initial = moving.get('turn_deg', [0, 0, 0])[2]
    manual = bool(device.get('handle'))
    # Keep the already measured frictional manual rocker. Contact hardware on
    # it needs a separate calibration; do not turn a drawing into a switch law.
    if manual: return
    # A narrower paddle makes room for its separate contact hardware rather
    # than adding an overlapping second conductor to the old solid slab.
    moving['size_m']=[.38,.04,.12]
    close_deg = device['closed_at_or_below_deg']
    r = .12
    zi = z + .16
    angle = math.radians(close_deg)
    leaf, pad, post = (device['name'] + suffix for suffix in (' contact leaf', ' contact pad', ' contact post'))
    # The pad lies one full conductor thickness below the leaf at closure.
    end = [x + r * math.cos(angle), y + r * math.sin(angle), zi]
    normal = [-math.sin(angle), math.cos(angle), 0]
    pad_at = [end[i] - .02 * normal[i] for i in range(3)]
    support_top = pad_at[1] - .01 * abs(math.cos(angle)) - .02 * abs(math.sin(angle))
    edge = .063
    stem_length = .13-edge
    spec['parts'] += [dict(name=leaf, shape='compound', material='iron', at_m=[x,y,zi], fixed=False,
        turn_deg=[0,0,initial], parts=[
            dict(shape='box',at_m=[0,0,0],size_m=[2*r+.08,.02,.06]),
            dict(shape='box',at_m=[0,0,(edge+.13)/2-.16],size_m=[.02,.02,stem_length])]),
        dict(box(pad, pad_at, [.04, .02, .06]), turn_deg=[0, 0, close_deg]),
        box(post, [pad_at[0], support_top/2, zi], [.04, support_top, .06], 'concrete')]
    spec['joints'].append(dict(name=device['name']+' leaf mounting', kind='fix', a=moving['name'], b=leaf,
                              at_m=[x, y, z]))
    device['touch'] = [leaf, pad]
    device['terminal_parts'] = {'in':leaf, 'out':pad}
    # Put the flexible inlet at the conductive pivot rather than at the
    # counterweight tip. Its weight must not operate an unloaded press deck.
    # Surface solder pads stay accessible in both historical paddle versions.
    device['terminals'] = {'in': [x,y,zi+.033], 'out': [pad_at[0],pad_at[1],pad_at[2]+.033]}
    device['terminal_normals'] = {'in':[0,0,1],'out':[0,0,1]}


def legacy_manual_switch(name, k, ctx):
    """Original raw declaration for v1 recipes; compilation adds a real rocker."""
    x,z=k.get('x_m',0),k.get('z_m',0)
    closed=k.get('state','open')=='closed'
    return {'parts':[box(name+' housing',[x,.05,z],[.22,.1,.16],'concrete'),
                     box(name+' handle',[x+(.04 if closed else -.04),.15,z],[.04,.1,.04],'oak')],
            'joints':[], 'electrical':{'devices':[dict(name=name,kind='switch',part=name+' housing',
                       closed=closed,terminals=terminal_rows(name,x,.13,z,True))]}}


def physical_manual_switches(spec):
    """Upgrade old fixed manual declarations without rewriting saved designs.

    The initial state and terminal identities remain; physical bodies replace
    the decorative handle, and native hinge travel subsequently controls it.
    """
    raw=spec.get('electrical') or {}
    if not isinstance(raw,dict) or not isinstance(raw.get('devices',[]),list): return spec
    devices=[d for d in raw.get('devices',[]) if isinstance(d,dict) and d.get('kind')=='switch'
             and not d.get('hinge') and not d.get('touch') and isinstance(d.get('name'),str) and isinstance(d.get('closed',False),bool)]
    if not devices or not isinstance(spec.get('parts',[]),list): return spec
    result=copy.deepcopy(spec)
    for original in devices:
        housing=next((p for p in result.get('parts',[]) if isinstance(p,dict) and p.get('name')==original.get('part')),None)
        at=housing.get('at_m') if housing else None
        if not isinstance(at,list) or len(at)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in at): continue
        fragment=switch(original['name'],dict(x_m=at[0],z_m=at[2],state='closed' if original.get('closed') else 'open'),{'tray':{'legacy_contacts':True}})
        handle=original['name']+' handle'
        old_handle=next((p for p in result.get('parts',[]) if isinstance(p,dict) and p.get('name')==handle),None)
        if old_handle and 'material' in old_handle:
            next(p for p in fragment['parts'] if p['name']==handle)['material']=old_handle['material']
        result['parts']=[p for p in result.get('parts',[]) if not(isinstance(p,dict) and p.get('name')==handle)]
        result['parts'].extend(p for p in fragment['parts'] if p['name']!=original['name']+' housing')
        if result.get('joints') is None: result['joints']=[]
        if not isinstance(result['joints'],list): continue
        result['joints'].extend(fragment['joints'])
        device=next(d for d in result['electrical']['devices'] if isinstance(d,dict) and d.get('name')==original['name'])
        generated=fragment['electrical']['devices'][0]
        for key in ('hinge','handle','closed_at_or_below_deg'): device[key]=generated[key]
    return result


def bulb(name, k, ctx):
    x, z = k.get('x_m', 0), k.get('z_m', 0)
    y = k.get('height_m', .24)
    part = name + ' bulb'
    watts = {'small': 3, 'bright': 12}.get(k.get('preset', 'small'), 3)
    diameter = .1
    # A declared family of rated bulbs, not a material-law prediction from
    # glass size. Older presets keep their original geometry and resistance.
    if k.get('size','preset') != 'preset':
        watts,diameter = {'small':(2.5,.1),'medium':(6,.13),'large':(12,.16)}[k['size']]
    return {'parts': [box(name + ' base', [x, .04, z], [.2, .08, .16], 'concrete'),
                      box(name + ' stem', [x, y / 2, z], [.04, y, .04]),
                      {'name': part, 'shape': 'sphere', 'material': 'glass',
                       'at_m': [x, y + diameter/2, z], 'size_m':[diameter]*3, 'fixed': True}],
            'electrical': {'devices': [{'name': name, 'kind': 'bulb', 'part': part,
                                        'terminals': terminal_rows(name, x, .1, z),
                                        'at_m': [x, y + diameter + .01, z], 'axis': [0, 1, 0],
                                        'watts': watts, 'rated_voltage_v': 12, 'efficiency': .2}]}}


def resistor(name, k, ctx):
    x,z=k.get('x_m',0),k.get('z_m',0)
    part=name+' housing'
    return {'parts':[box(part,[x,.08,z],[.24,.16,.12],k.get('housing_material','glass'))],
        'electrical':{'devices':[dict(name=name,kind='resistor',part=part,
            terminals={'a':[x-.15,.08,z],'b':[x+.15,.08,z]},
            resistance_ohm=k.get('resistance_ohm',48))]}}


def capacitor(name, k, ctx):
    x,z=k.get('x_m',0),k.get('z_m',0)
    part=name+' housing'
    # A rated nonpolar two-terminal part. Geometry/material set housing mass;
    # capacitance is a declared component rating, not a bulk glass/oak law.
    return {'parts':[box(part,[x,.12,z],[.18,.24,.14],k.get('housing_material','glass'))],
        'electrical':{'devices':[dict(name=name,kind='capacitor',part=part,
            terminals={'a':[x-.12,.12,z],'b':[x+.12,.12,z]},
            capacitance_f=k.get('capacitance_f',.1),resistance_ohm=k.get('esr_ohm',.1),
            leakage_ohm=k.get('leakage_ohm',1e6))]}}


def wire(name, k, ctx):
    row = {'name': name, 'a': k.get('a_terminal', ''), 'b': k.get('b_terminal', '')}
    # Manufactured stock includes real service-coil slack. Every centimetre
    # contributes native mass, contact and copper resistance.
    row.update(length_m=k.get('length_m', 5),
               area_mm2={'low resistance':2.5,'thin': .01, 'standard': .5, 'thick': 2.5}[k.get('size', 'low resistance')])
    return {'electrical': {'wires': [row]}}


def power_cable(name, k, ctx):
    """A native two-core charging lead with material mass and copper loss."""
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
        # Fixed rear housing connections, clear of the rotor's swept volume.
        # Native cable rods attach here, clear of the rotor's swept volume.
        'name': name, 'kind': 'motor', 'part': part, 'terminals': motor_terminals(parts[0]),
        'hinge': hinge, 'stall_torque_n_m': 2, 'no_load_rad_s': 8,
        'command': k.get('throttle', 1) * (1 if k.get('direction', 'forward') == 'forward' else -1),
        'brake_torque_n_m': 0, 'gear_ratio': 1}]}}


def ignition(name, k, ctx):
    if k.get('attachment_version', 1) == 2:
        return clipped_heater(name,k,ctx)
    x, z = k.get('x_m', 0), k.get('z_m', 0)
    target = k.get('target', 'included oak cord')
    parts = [box(name + ' housing', [x, .04, z], [.18, .08, .14], 'concrete')]
    if target == 'included oak cord':
        target = name + ' target'
        parts.append(box(target, [x, .18, z], [.02, .2, .02], 'oak'))
    return {'parts': parts, 'electrical': {'devices': [{
        'name': name, 'kind': 'coil', 'part': name + ' housing', 'heats': target,
        'terminals': terminal_rows(name, x, .12, z),
        'terminal_normals':{'plus':[0,1,0],'minus':[0,1,0]},
        'resistance_ohm': {'warm': 12, 'hot': .12}.get(k.get('preset', 'warm'), 12)}]}}


def clipped_heater(name,k,ctx):
    """A hollow heater clip fixed to its explicitly selected material body.

    Native winding heat is still the existing lumped body-energy coupling.
    The fix mount supplies real attachment reactions, not a remote pose.
    An unattached clip directs its heat to its own material body.
    """
    target=k.get('target','')
    try:available=ctx['parts'] if ctx else []
    except KeyError:available=[]
    extras=[]
    if target=='included oak cord':
        target=name+' target'
        extras=[box(target,[k.get('x_m',0),.18,k.get('z_m',0)],[.02,.2,.02],'oak',False)]
        available=[*available,*extras]
    body=next((p for p in available if p['name']==target),None)
    if target and (body is None or body['shape']!='box'):
        raise ValueError('Clip the heater onto a box-shaped material body.')
    at=list(body['at_m']) if body else [k.get('x_m',0),.05,k.get('z_m',0)]
    dx,dz=(body['size_m'][0],body['size_m'][2]) if body else (.02,.02)
    turn=list(body.get('turn_deg',[0,0,0])) if body else [0,0,0]
    part=name+' housing'
    pieces=[dict(shape='box',at_m=[side*(dx/2+.01),0,0],size_m=[.02,.06,dz+.04]) for side in (-1,1)]+[
        dict(shape='box',at_m=[0,0,side*(dz/2+.01)],size_m=[dx,.06,.02]) for side in (-1,1)]
    def world(local):
        import machine_world as mw
        w,x,y,z=mw.quaternion_of_turn(turn)
        vx,vy,vz=local;tx,ty,tz=2*(y*vz-z*vy),2*(z*vx-x*vz),2*(x*vy-y*vx)
        return [at[0]+vx+w*tx+y*tz-z*ty,at[1]+vy+w*ty+z*tx-x*tz,at[2]+vz+w*tz+x*ty-y*tx]
    device=dict(name=name,kind='coil',part=part,attachment_version=2,clipped_to=target if body else '',heats=target if body else part,
        resistance_ohm={'warm':12,'hot':.12}.get(k.get('preset','warm'),12),
        terminals={key:world([side*(dx/2+.03),0,dz/2+.035]) for key,side in [('plus',-1),('minus',1)]})
    # Four ordinary cell bodies form the hollow clip. Exact compounds cannot
    # participate in native heating yet; these bars retain native heat/mass.
    names=[part,name+' opposite bar',name+' front bridge',name+' back bridge']
    parts=[dict(box(n,world(p['at_m']),p['size_m'],fixed=False),turn_deg=turn) for n,p in zip(names,pieces)]
    device['mechanical_parts']=names
    device['terminal_parts']={'plus':names[0],'minus':names[1]}
    direction=[world([0,0,.1])[i]-at[i] for i in range(3)]
    device['terminal_normals']={'plus':direction,'minus':direction}
    joints=[dict(name=name+' '+label,kind='fix',a=names[a],b=names[b],at_m=world(point))
        for label,a,b,point in [('front bond',0,2,[-dx/2,0,dz/2+.01]),
            ('back bond',0,3,[-dx/2,0,-dz/2-.01]),('right bond',2,1,[dx/2,0,dz/2+.01])]]
    if body:
        device['heats']=target
        joints.append(dict(name=name+' clip',kind='fix',a=target,b=part,at_m=world([-dx/2,0,0])))
    return dict(parts=extras+parts,joints=joints,electrical={'devices':[device]})


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
           'motor': motor, 'ignition': ignition, 'power_cable': power_cable,
           'resistor':resistor,'capacitor':capacitor}.items()}


def knob(default, minimum, maximum, step, label):
    return {'default': default, 'min': minimum, 'max': maximum, 'step': step, 'label': label}


POS = {'x_m': knob(0, -2, 2, .02, 'along (m)'), 'z_m': knob(0, -2, 2, .02, 'across (m)')}
TRAY = [
    {'piece':'resistor','label':'Resistor','count':20,'cost':1,'turning':False,
     'description':'A two-terminal rated resistance. Wiring decides series or parallel; native current determines voltage drop and heat.',
     'knobs':{**POS,'resistance_ohm':knob(48,1,1000,1,'resistance (ohms)'),
              'housing_material':{'default':'glass','choices':['glass','oak','iron'],'label':'housing material'}}},
    {'piece':'capacitor','label':'Capacitor','count':12,'cost':1,'turning':False,
     'description':'A nonpolar capacitor stores charge and energy. Current charges or discharges it; no initial charge is supplied.',
     'knobs':{**POS,'capacitance_f':knob(.1,.005,1,.005,'capacitance (F)'),
              'esr_ohm':knob(.1,.01,10,.01,'internal resistance (ohms)'),
              'leakage_ohm':knob(1000000,1000,1000000,1000,'leakage resistance (ohms)'),
              'housing_material':{'default':'glass','choices':['glass','oak','iron'],'label':'housing material'}}},
    {'piece': 'battery', 'label': 'Battery', 'count': 8, 'cost': 1, 'turning': False,
     'description': 'A finite 12 V energy store with two labelled terminals.',
     'knobs': {**POS, 'mount': {'default':'fixed','choices':['fixed','contact pack'],'label':'battery mount'},
               'height_m': knob(.4,.24,1,.02,'release height (m)'),
               'yaw_deg': knob(0,-180,180,15,'pack rotation (degrees)'),
               'housing_material': {'default':'iron','choices':['glass','oak','iron'],'label':'pack housing'},
               'voltage_v': knob(12, 6, 24, 6, 'voltage (V)'),
               'capacity_j': knob(1000, 100, 10000, 100, 'capacity (J)'),
               'charge_percent': knob(100, 0, 100, 10, 'initial charge (%)'),
               'max_power_w': knob(200, 10, 2000, 10, 'maximum power (W)')}},
    {'piece': 'switch', 'label': 'Switch', 'count': 12, 'cost': 1, 'turning': False,
     'description': 'Drag the physical rocker on the field, or let a marble tip the paddle; hinge travel opens or closes the loop.',
     'knobs': {**POS, 'mode': {'default': 'manual', 'choices': ['manual', 'paddle'], 'label': 'operated by'},
               'state': {'default': 'open', 'choices': ['open', 'closed'], 'label': 'initial state'},
               'handle_material': {'default':'oak','choices':['glass','oak','iron'],'label':'handle material'},
               'threshold_deg': knob(8, 2, 25, 1, 'paddle travel (degrees)')}},
    {'piece': 'bulb', 'label': 'Bulb', 'count': 12, 'cost': 1, 'turning': False,
     'description': 'Light and brightness come from solved circuit power.',
     'knobs': {**POS, 'height_m': knob(.24, .16, .6, .02, 'post height (m)'),
               'preset': {'default': 'small', 'choices': ['small', 'bright'], 'label': 'rated bulb'},
               'size': {'default':'preset','choices':['preset','large','medium','small'],'label':'bulb size'}}},
    {'piece': 'wire', 'label': 'Wire', 'count': 60, 'cost': 0, 'turning': False,
     'description': 'Connect two terminals. Thin or long copper wires lose more voltage and heat up; crossings never connect.',
     'knobs': {**POS, 'a_terminal': {'default': '', 'terminal': True, 'label': 'from terminal'},
               'b_terminal': {'default': '', 'terminal': True, 'label': 'to terminal'},
               'size': {'default':'low resistance','choices':['low resistance','thin','standard','thick'],'label':'wire thickness'},
               'length_m':knob(5,.1,10,.1,'stock length including slack (m)')}},
    {'piece': 'power_cable', 'label': 'Power cable', 'count': 20, 'cost': 0, 'turning': False,
     'description': 'A two-core charging cord from a solar output to a battery input. It falls, contacts solids and loses power in its copper.',
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


def compile_power(spec, names, battery_names, problems, parts=None,occupied=()):
    """Resolve explicit charging destinations without mutating saved declarations.

    A source may charge one store, and a store accepts one source. Parallel
    charging electronics are outside this model. Native two-core leads supply
    mass, contact, sag, terminal pullout and resistive loss. Collection,
    saturation and consumption remain native laws.
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
            body=names[p['part']]
            normal=p.get('normal',[0,1,0])
            if not valid_point(normal):normal=[0,1,0]
            norm=math.hypot(*normal) or 1
            normal=[v/norm for v in normal]
            reach=max(sum((q[i]-body['at_m'][i])*normal[i] for i in range(3)) for q in mechanical_cables.shape_points(body))
            ports.setdefault(name, {'name': name, 'kind': 'output', 'solar_panel': panel,
                                    'part': p['part'], 'at_m': [body['at_m'][i]-(reach+.004)*normal[i] for i in range(3)]})
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
        row={'name': name, 'a': a['name'], 'b': b['name']}
        try:
            normal=panels[source].get('normal',[0,1,0])
            if not valid_point(normal):normal=[0,1,0]
            norm=math.hypot(*normal) or 1
            exits=dict(exit_a_m=[a['at_m'][i]-.15*normal[i]/norm for i in range(3)],
                       conductor_count=2,solar_panel=source)
            physical,span,area=mechanical_cables.connection(name,a['part'],a['at_m'],b['part'],b['at_m'],
                parts or [],len(cables),exits,
                occupied=list(occupied)+[w['mechanical'] for w in cables if 'mechanical' in w])
            row.update(mechanical=physical,length_m=span,area_mm2=area,resistance_ohm=.0172*2*span/area)
        except (ValueError,KeyError,TypeError) as exc:problems.append(f'power cable {name}: {exc}')
        cables.append(row)
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


def compile_electrical(spec, names, joints, battery_names, problems, parts=None):
    raw = spec.get('electrical', {}) or {}
    if not isinstance(raw, dict):
        problems.append('electrical must contain devices and wires'); return {}
    if any(not isinstance(raw.get(key, []), list) for key in ('devices', 'wires', 'contacts')):
        problems.append('electrical devices, wires and contacts must be arrays'); return {}
    devices, wires, contacts, terminals = [], [], [], {}
    bodies = {p['name']:p for p in parts or []}
    ids = set()
    hinges = {j['name'] for j in joints if j['kind'] == 'hinge'}
    def number(row, key, default, low, high):
        value = row.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
            problems.append(f'electrical {row.get("name")}: {key} must be {low}..{high}'); return default
        return value
    if len(raw.get('devices', [])) > 64 or len(raw.get('wires', [])) > 128 or len(raw.get('contacts', [])) > 128:
        problems.append('electrical supports at most 64 devices, 128 wires and 128 contacts'); return {}
    for item in raw.get('devices', []):
        if not isinstance(item, dict):
            problems.append('electrical devices must be objects'); continue
        d = copy.deepcopy(item)
        name, kind = d.get('name'), d.get('kind')
        if not isinstance(name, str) or not name or name in ids:
            problems.append('electrical device names must be nonempty and unique'); continue
        ids.add(name)
        if kind not in ('battery', 'switch', 'bulb', 'motor', 'generator', 'coil', 'socket','resistor','capacitor') or not isinstance(d.get('part'), str) or d['part'] not in names:
            problems.append(f'electrical {name}: unsupported kind or missing housing'); continue
        keys = ('in', 'out') if kind == 'switch' else (('a','b') if kind in ('resistor','capacitor') else ('plus', 'minus'))
        if not isinstance(d.get('terminals'), dict) or set(d['terminals']) != set(keys):
            problems.append(f'electrical {name}: needs {" and ".join(keys)} terminals'); continue
        for key, xyz in d['terminals'].items():
            if not isinstance(xyz, list) or len(xyz) != 3 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in xyz):
                problems.append(f'electrical {name}: terminal positions are finite world coordinates'); continue
            terminals[name + ':' + key] = xyz
        bindings = d.get('terminal_parts', {})
        if not isinstance(bindings, dict) or any(key not in keys or not isinstance(part,str) or part not in names
                                               for key,part in bindings.items()):
            problems.append(f'electrical {name}: terminal_parts must bind declared terminals to existing bodies')
        if kind in ('battery','generator') and (not isinstance(d.get('battery'), str) or d['battery'] not in battery_names):
            problems.append(f'electrical {name}: battery names its energy store')
        if kind=='generator':
            reference=next((b for b in spec.get('batteries',[]) if b.get('name')==d.get('battery')),None)
            if reference and reference.get('charge_j',reference.get('capacity_j'))!=0:
                problems.append(f'electrical {name}: a generator reference must start with zero energy')
        if kind == 'bulb':
            d['watts'] = number(d, 'watts', 3, .01, 1000)
            d['rated_voltage_v'] = number(d, 'rated_voltage_v', 12, 1, 1000)
            d['efficiency'] = number(d, 'efficiency', .2, 0, 1)
        if kind in ('resistor','capacitor'):
            d['resistance_ohm']=number(d,'resistance_ohm',48 if kind=='resistor' else .1,.01,1e6)
        if kind=='capacitor':
            d['capacitance_f']=number(d,'capacitance_f',.1,1e-6,100)
            d['leakage_ohm']=number(d,'leakage_ohm',1e6,1000,1e12)
            if any(key in d for key in ('initial_voltage_v','capacitor_voltage_v','stored_j','charge_c')):
                problems.append(f'electrical {name}: initial charge is zero; runtime charge belongs to the native snapshot')
        if kind == 'coil':
            if not isinstance(d.get('heats'), str) or d['heats'] not in names: problems.append(f'electrical {name}: coil target is missing')
            if d.get('attachment_version')==2:
                if d.get('clipped_to'):
                    if d['heats']!=d['clipped_to'] or not any(j['kind']=='fix' and {j.get('a'),j.get('b')}=={d['part'],d['heats']} for j in joints):
                        problems.append(f'electrical {name}: a clipped heater needs its physical fix mount')
                elif d.get('heats')!=d['part']:
                    problems.append(f'electrical {name}: an unattached heater can only heat itself')
            d['resistance_ohm'] = number(d, 'resistance_ohm', 12, .01, 1e6)
        if kind == 'switch':
            if not isinstance(d.get('closed', False), bool): problems.append(f'electrical {name}: closed is boolean')
            if d.get('hinge'):
                if d['hinge'] not in hinges: problems.append(f'electrical {name}: paddle hinge is missing')
                d['closed_at_or_below_deg'] = number(d, 'closed_at_or_below_deg', -8, -179, 179)
            if 'touch' in d:
                touch = d['touch']
                if (not isinstance(touch, list) or len(touch)!=2 or
                    not all(isinstance(p,str) and p in bodies for p in touch) or touch[0]==touch[1]):
                    problems.append(f'electrical {name}: switch needs two distinct contact bodies')
                elif any(bodies[p]['material'] not in ('iron','aluminum') for p in touch):
                    problems.append(f'electrical {name}: switch contacts must be iron or aluminum')
                elif [bindings.get(key) for key in ('in','out')] != touch:
                    problems.append(f'electrical {name}: switch contacts must carry its in/out terminals')
            if 'handle' in d:
                h=d['handle']
                joint=next((j for j in joints if j['name']==d.get('hinge')),None)
                if (not isinstance(h,dict) or not isinstance(h.get('part'),str) or h['part'] not in names or
                    not isinstance(h.get('at_m'),list) or len(h['at_m'])!=3 or
                    not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in h['at_m']) or
                    not joint or joint.get('b')!=h['part'] or (bodies and bodies[h['part']]['fixed'])):
                    problems.append(f'electrical {name}: handle must belong to its loose hinged body')
        if kind in ('motor','generator'):
            if not isinstance(d.get('hinge'), str) or d['hinge'] not in hinges: problems.append(f'electrical {name}: driven hinge is missing')
            for key, default, low, high in [('stall_torque_n_m', 1, .01, 1e5), ('no_load_rad_s', 8, .01, 1e4),
                                          ('command', 1, -1, 1), ('gear_ratio', 1, .01, 1e4), ('brake_torque_n_m', 0, 0, 1e5)]:
                d[key] = number(d, key, default, low, high)
        devices.append(d)
    counts={};seated={}
    for item in raw.get('wires',[]):
        if not isinstance(item,dict):continue
        for end in ('a','b'):
            key=item.get(end)
            if isinstance(key,str):counts[key]=counts.get(key,0)+1
    layouts={};reservations=[]
    for index,item in enumerate(raw.get('wires',[])):
        if not isinstance(item,dict) or not all(isinstance(item.get(k),str) and item[k] in terminals for k in ('a','b')):continue
        seats={}
        for end in ('a','b'):
            key=item[end];slot=seated.get(key,0);seated[key]=slot+1
            seats[end]=(slot-(counts[key]-1)/2)*.012
        layouts[index]=seats
        try:
            _,pa,_,pb,settings=mechanical_cables.terminal_layout(item,devices,parts or [],seats)
            radius=float(settings.get('radius_m',.003))
            if not math.isfinite(radius) or not .001<=radius<=.03:continue
            for field,point in (('exit_a_m',pa),('exit_b_m',pb)):
                exit_=settings.get(field)
                if exit_ is not None:
                    reservations.append((index,dict(name='reserved socket',path_m=[point,exit_],radius_m=radius)))
        except (ValueError,KeyError,TypeError):pass  # main validation reports it
    for index,w in enumerate(raw.get('wires', [])):
        if not isinstance(w, dict) or not isinstance(w.get('name'), str) or not w['name'] or w['name'] in ids:
            problems.append('electrical wire names must be nonempty and unique'); continue
        ids.add(w['name'])
        if not isinstance(w.get('a'), str) or not isinstance(w.get('b'), str) or w['a'] not in terminals or w['b'] not in terminals or w['a'] == w['b']:
            problems.append(f'electrical {w["name"]}: choose two different existing terminals'); continue
        row = {key: w[key] for key in ('name', 'a', 'b')}
        if 'length_m' in w or 'area_mm2' in w:
            row['length_m'] = number(w,'length_m',5,.1,100)
            row['area_mm2'] = number(w,'area_mm2',.5,.001,100)
            # Copper at 20 C: rho = 0.0172 ohm mm^2 / m. The native
            # branch books I^2 R heat and the battery supplies every joule.
            row['resistance_ohm'] = .0172 * row['length_m'] / row['area_mm2']
        row['mechanical']=copy.deepcopy(w.get('mechanical',{}))
        try:
            seats=layouts.get(index,{})
            prior=[old['mechanical'] for old in wires if isinstance(old.get('mechanical'),dict) and 'path_m' in old['mechanical']]
            # Keep future plug corridors clear while fitting earlier cords.
            # These are construction reservations, never phantom rigid bodies.
            prior.extend(c for owner,c in reservations if owner!=index)
            cable,span,area=mechanical_cables.prepare(row,devices,parts or [],len(wires),
                prior,seats)
            row.update(mechanical=cable,length_m=span,area_mm2=area,resistance_ohm=.0172*span/area)
        except (ValueError,KeyError,TypeError) as exc:problems.append(f'electrical {w["name"]}: {exc}')
        wires.append(row)
    for item in raw.get('contacts', []):
        if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not item['name'] or item['name'] in ids:
            problems.append('electrical contact names must be nonempty and unique'); continue
        ids.add(item['name'])
        touch = item.get('touch')
        if (not isinstance(item.get('a'),str) or not isinstance(item.get('b'),str) or
            item['a'] not in terminals or item['b'] not in terminals or item['a']==item['b'] or
            not isinstance(touch,list) or len(touch)!=2 or not all(isinstance(p,str) and p in names for p in touch) or touch[0]==touch[1]):
            problems.append(f'electrical {item["name"]}: contact needs two terminals and two existing distinct contact bodies'); continue
        if bodies and any(bodies[p]['material'] not in ('iron','aluminum') for p in touch):
            problems.append(f'electrical {item["name"]}: conducting contact bodies must be iron or aluminum'); continue
        terminal_bodies = {d['name']+':'+key:part for d in devices
                           if isinstance(d.get('terminal_parts',{}),dict)
                           for key,part in d.get('terminal_parts',{}).items()}
        if any(terminal_bodies.get(item[key]) != part for key,part in zip(('a','b'),touch)):
            problems.append(f'electrical {item["name"]}: contact bodies must carry the declared terminals'); continue
        contacts.append(dict(name=item['name'],a=item['a'],b=item['b'],touch=list(touch),
                             resistance_ohm=number(item,'resistance_ohm',.001,.00001,1000)))
    parent = {t: t for t in terminals}
    def find(t):
        while parent[t] != t: t = parent[t]
        return t
    def join(a, b): parent[find(a)] = find(b)
    for d in devices:
        ts = [d['name'] + ':' + k for k in d['terminals']]
        if d['kind']!='socket' and all(t in parent for t in ts): join(*ts)
    for w in wires: join(w['a'], w['b'])
    for c in contacts: join(c['a'],c['b'])
    groups = {}
    for d in devices:
        ts = [d['name'] + ':' + k for k in d['terminals']]
        if all(t in parent for t in ts):
            for root in {find(t) for t in ts}: groups.setdefault(root, []).append(d)
    networks = []
    occupied = {c.get('battery') for c in spec.get('circuits', [])}
    for root, ds in groups.items():
        sources = [d for d in ds if d['kind'] == 'battery']
        generators = [d for d in ds if d['kind'] == 'generator']
        if len(sources) > 1:
            problems.append('electrical: batteries cannot be interconnected; each graph has one supply'); continue
        if sources and generators:
            problems.append('electrical: generator loads use a separate circuit; battery charging needs a charge controller'); continue
        if not sources and not generators: continue
        # A generator-only island uses a zero-energy, disconnected reference
        # port. The native reversible DC branch supplies EMF and opposing
        # shaft torque; the reference cannot supply a single joule.
        b = (sources or generators)[0]
        if b['battery'] in occupied:
            problems.append(f'electrical: {b["battery"]} already supplies another circuit'); continue
        occupied.add(b['battery'])
        networks.append({'name': 'electrical ' + b['name'], 'battery': b['battery'], 'source': b,
                         'devices': ds, 'wires': [w for w in wires if find(w['a']) == root],
                         'contacts':[c for c in contacts if find(c['a'])==root]})
    return {'devices': devices, 'wires': wires, 'contacts':contacts, 'networks': networks}


def build_electrical(engine, compiled, store_ids, joint_ids):
    circuits = {}
    physical=set()
    for n in compiled.get('electrical', {}).get('networks', []):
        source = n['source']; branches = []; heats = []
        nodes = [d['name'] + ':' + t for d in n['devices'] for t in d['terminals']]
        heats.append({'id': 'supply', 'component': source['battery'], 'capacity_j_k': 2000, 'ambient_w_k': 1})
        for d in n['devices']:
            if d['kind'] in ('battery','socket'): continue
            keys = list(d['terminals'])
            row = {'id': d['name'], 'component': d['name'], 'a': d['name'] + ':' + keys[0],
                   'b': d['name'] + ':' + keys[1], 'thermal': d['name']}
            heats.append({'id': d['name'], 'component': d['name'], 'capacity_j_k': 100, 'ambient_w_k': 1})
            if d['kind'] == 'switch':
                row.update(kind='switch', resistance_ohm=.001, closed=d.get('closed', False))
                if d.get('touch'): row['follows_contact'] = dict(zip(('a','b'),d['touch']))
                elif d.get('hinge'): row['follows_hinge'] = {'joint': joint_ids[d['hinge']], 'closed_at_or_below_deg': d['closed_at_or_below_deg']}
            elif d['kind'] == 'coil':
                row.update(kind='resistor', resistance_ohm=d['resistance_ohm'])
                if d.get('heats'):row['heats_body']=d['heats']
            elif d['kind']=='resistor':
                row.update(kind='resistor',resistance_ohm=d['resistance_ohm'])
            elif d['kind']=='capacitor':
                row.update(kind='capacitor',resistance_ohm=d['resistance_ohm'],capacitance_f=d['capacitance_f'])
                branches.append(dict(id=d['name']+' leakage',component=d['name'],kind='resistor',
                    a=row['a'],b=row['b'],thermal=d['name'],resistance_ohm=d['leakage_ohm']))
            elif d['kind'] == 'bulb':
                at = d.get('at_m', compiled['parts'][next(i for i, p in enumerate(compiled['parts']) if p['name'] == d['part'])]['at_m'])
                lamp = engine.op(op='lamp', name=d['name'], body=d['part'], store=0, watts=d['watts'],
                                 at_m=at, efficacy_lm_w=683)['lamp']
                engine.op(op='lamp_light', name=d['name'] + ' light', lamp=lamp, axis=d.get('axis', [0, 1, 0]),
                          half_angle_deg=179, radiant_efficacy_lm_w=683, rays=48, max_bounces=4)
                row.update(kind='bulb', lamp=lamp, resistance_ohm=d['rated_voltage_v'] ** 2 / d['watts'], efficiency=d['efficiency'])
            elif d['kind'] in ('motor','generator'):
                motor_id = engine.op(op='motor', joint=joint_ids[d['hinge']], store=store_ids[n['battery']],
                                     stall_torque_n_m=d['stall_torque_n_m'], no_load_rad_s=d['no_load_rad_s'],
                                     brake_torque_n_m=d['brake_torque_n_m'])['motor']
                engine.op(op='drive', motor=motor_id, command=d['command'])
                row.update(kind='motor', motor=motor_id, gear_ratio=d['gear_ratio'])
            branches.append(row)
        for w in n['wires']:
            branches.append({'id': w['name'], 'component': w['name'], 'kind': 'wire', 'a': w['a'], 'b': w['b'],
                             'resistance_ohm': w.get('resistance_ohm', .01), 'thermal': 'supply'})
        for c in n.get('contacts',[]):
            branches.append(dict(id=c['name'],component=c['name'],kind='switch',a=c['a'],b=c['b'],
                resistance_ohm=c['resistance_ohm'],thermal='supply',closed=False,
                follows_contact=dict(zip(('a','b'),c['touch']))))
        network = {'schema': 'banjo.circuit.v1', 'id': n['name'], 'nodes': nodes,
                   'source': {'store': store_ids[n['battery']], 'positive': source['name'] + ':plus',
                              'negative': source['name'] + ':minus', 'resistance_ohm': .05, 'thermal': 'supply'},
                   'thermal_nodes': heats, 'branches': branches}
        circuits[n['name']] = engine.op(op='circuit', network=network)['circuit']
        for w in n['wires']:
            if 'mechanical' in w:
                engine.op(op='mechanical_cable',cable=dict(w['mechanical'],circuit=circuits[n['name']]))
                physical.add(w['name'])
    # A lead still weighs something when no supply is connected. Geometry and
    # contact are independent of membership in a powered electrical island.
    for w in compiled.get('electrical',{}).get('wires',[]):
        if 'mechanical' in w and w['name'] not in physical:
            engine.op(op='mechanical_cable',cable=dict(w['mechanical'],circuit=0))
    for w in compiled.get('electrical',{}).get('power_cables',[]):
        engine.op(op='mechanical_cable',cable=dict(w['mechanical'],circuit=0))
    return circuits


def readouts(graph, native, batteries=()):
    branches = {b['id']: b for c in native for b in c['branches']}
    node_volts = {name:value for c in native for name,value in zip(c.get('nodes',[]),c.get('last',{}).get('voltage_v',[]))}
    def device_voltage(d):
        keys = list(d['terminals'])
        return node_volts.get(d['name']+':'+keys[0],0)-node_volts.get(d['name']+':'+keys[1],0)
    wire_power={}
    stores={b['name']:b for b in batteries}
    wire_supply={w['name']:dict(supply_voltage_v=stores[n['battery']]['voltage_v'],
                              supply_max_power_w=stores[n['battery']]['max_power_w'],show_supply_limit=index==0)
                 for n in graph.get('networks',[]) if n['battery'] in stores and n['source']['kind']=='battery'
                 for index,w in enumerate(n['wires'])}
    for network in native:
        volts=dict(zip(network.get('nodes',[]),network.get('last',{}).get('voltage_v',[])))
        reference=volts.get(network.get('source',{}).get('negative'),0)
        for branch in network.get('branches',[]):
            if branch.get('kind')!='wire':continue
            current=branch.get('current_a',0)
            upstream=branch.get('a') if current>=0 else branch.get('b')
            wire_power[branch['id']]=dict(through_w=current*(volts.get(upstream,reference)-reference),
                loss_w=branch.get('power_w',0),
                return_path=network.get('source',{}).get('negative') in (branch.get('a'),branch.get('b')))
    return {'devices': [dict(name=d['name'], kind=d['kind'], closed=branches.get(d['name'], {}).get('closed'),
                            voltage_v=device_voltage(d),
                            current_a=branches.get(d['name'], {}).get('current_a', 0),
                            power_w=branches.get(d['name'], {}).get('power_w', 0),
                            capacitor_voltage_v=branches.get(d['name'],{}).get('capacitor_voltage_v',0),
                            stored_j=branches.get(d['name'],{}).get('stored_j',0),
                            charge_c=branches.get(d['name'],{}).get('charge_c',0),
                            emitted_w=branches.get(d['name'], {}).get('emitted_w', 0)) for d in graph.get('devices', [])],
            'wires': [dict(w, current_a=branches.get(w['name'], {}).get('current_a', 0),
                           **wire_supply.get(w['name'],{}),
                           **wire_power.get(w['name'],{})) for w in graph.get('wires', [])],
            'contacts':[dict(c,closed=branches.get(c['name'],{}).get('closed',False),
                             current_a=branches.get(c['name'],{}).get('current_a',0),
                             power_w=branches.get(c['name'],{}).get('power_w',0)) for c in graph.get('contacts',[])],
            'networks': [c for c in native if c['id'].startswith('electrical ')]}


def power_requirements(compiled,bodies,measured,motors,native,heat=()):
    """Display-only static estimates; never a motor command or win rule.

    Use native mass/COM and declared geometry. Only simple grounded hinges
    and vertical drum lifts get a starting-watts estimate. Contacts, springs,
    geared loads, acceleration and supply/wire losses are not inferred.
    """
    result=[];joints={j['name']:j for j in compiled['joints']}
    devices={d['name']:d for d in measured.get('devices',[])}
    branches={b['id']:b for c in native for b in c['branches']}
    declarations=[(d['name'],d['part'],d,devices.get(d['name'],{}),branches.get(d['name'],{}))
                  for d in compiled.get('electrical',{}).get('devices',[]) if d['kind'] in ('motor','bulb','resistor','capacitor','coil')]
    for c in compiled.get('circuits',[]):
        if c.get('motor'):
            branch=next((b for n in native if n['id']==c['name'] for b in n['branches'] if b['id']=='motor'),{})
            declarations.append((c['name'],None,c['motor'],branch,branch))
    motor_states={m['id']:m for m in motors}
    for name,part,declaration,reading,branch in declarations:
        row=dict(name=name,part=part,input_w=reading.get('power_w',0))
        if declaration.get('kind')=='coil':
            row.update(requirement='heater',resistance_ohm=declaration['resistance_ohm'],heats=declaration.get('heats'),
                clipped_to=declaration.get('clipped_to') if declaration.get('attachment_version')==2 else declaration.get('heats'),
                voltage_v=reading.get('voltage_v',0),current_a=reading.get('current_a',0))
            warming=next((h for h in heat if h['name']==declaration.get('heats')),None)
            if warming:row.update(material_temperature_k=warming['temperature_k'],burning=warming['reacting'])
        elif declaration.get('kind')=='bulb':
            row.update(rated_w=declaration['watts'],rated_voltage_v=declaration['rated_voltage_v'],
                       voltage_v=reading.get('voltage_v',0),requirement='rated')
            for station in compiled.get('stations',[]):
                goal=(station.get('done_when') or {}).get('load_power_w',{})
                if name in goal.get('devices',[goal.get('device')]):row.update(required_w=goal['at_least_w'],requirement='goal')
        elif declaration.get('kind') in ('capacitor','resistor'):
            row.update(requirement=declaration['kind'],voltage_v=reading.get('voltage_v',0),
                current_a=reading.get('current_a',0),resistance_ohm=declaration['resistance_ohm'])
            if declaration['kind']=='capacitor':
                row.update(capacitance_f=declaration['capacitance_f'],stored_j=reading.get('stored_j',0),
                    capacitor_voltage_v=reading.get('capacitor_voltage_v',0))
                for station in compiled.get('stations',[]):
                    goal=(station.get('done_when') or {}).get('capacitor_energy_j',{})
                    if goal.get('device')==name:row['required_j']=goal['at_least_j']
        else:
            hinge=joints.get(declaration.get('hinge'),{})
            body=bodies.get(hinge.get('b'),{})
            row.update(part=hinge.get('b'),requirement='variable',
                       rated_torque_n_m=declaration['stall_torque_n_m']*declaration.get('gear_ratio',1))
            state=motor_states.get(branch.get('motor'),{})
            row.update(torque_n_m=state.get('torque_n_m',0),speed_rad_s=state.get('speed_rad_s',0))
            other=[j for j in compiled['joints'] if j['name']!=hinge.get('name') and
                   (body.get('name') in (j.get('a'),j.get('b'),j.get('drum')) or
                    j['kind']=='gear' and hinge.get('name') in (j.get('a'),j.get('b')))]
            drums=[j for j in other if j['kind']=='drum']
            simple=bool(body and bodies.get(hinge.get('a'),{}).get('anchored') and
                        all(j['kind']=='drum' for j in other) and
                        (body.get('shape')!='compound' or drums))
            if simple:
                axis=hinge['axis'];length=math.sqrt(sum(v*v for v in axis));axis=[v/length for v in axis]
                lever=[body['position_m'][i]-hinge['at_m'][i] for i in range(3)]
                force=[0,-9.81*body['mass_kg'],0]
                cross=[lever[1]*force[2]-lever[2]*force[1],lever[2]*force[0]-lever[0]*force[2],lever[0]*force[1]-lever[1]*force[0]]
                sign=1 if declaration.get('command',1)>=0 else -1
                resistance=max(0,-sign*sum(axis[i]*cross[i] for i in range(3)))+hinge.get('friction_n_m',0)
                for drum in drums:
                    load=bodies.get(drum['load'],{})
                    extra=[j for j in compiled['joints'] if j['name']!=drum['name'] and
                           drum['load'] in (j.get('a'),j.get('b'),j.get('load'))]
                    if not load or load.get('anchored') or extra or sign*drum['winds']<=0:simple=False;break
                    resistance+=load['mass_kg']*9.81*drum['radius_m']
                    row['part']=drum['load']
                if simple and resistance>.01:
                    ratio=declaration.get('gear_ratio',1)
                    row.update(requirement='start_estimate',required_torque_n_m=resistance,
                        required_w=(resistance/ratio)**2*declaration['no_load_rad_s']/declaration['stall_torque_n_m'],
                        exceeds_motor=resistance>row['rated_torque_n_m'])
        body=bodies.get(row['part'],{})
        if body:row['at_m']=list(body['position_m']);result.append(row)
    return result


def merge(spec, fragment):
    for key in ('parts', 'joints', 'batteries', 'kits'):
        spec.setdefault(key, []).extend(fragment.get(key, []))
    for key in ('devices', 'wires', 'contacts'):
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
    s['joints'] = [j for j in s.get('joints',[]) if not j['name'].startswith('control ')]
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
    s = empty('Give it power'); merge(s, bulb('lamp', {'x_m': .6}, {})); merge(s,socket.holder())
    link(s,'holder positive lead','battery holder:plus','lamp:plus')
    link(s,'holder return lead','lamp:minus','battery holder:minus')
    row = tray('battery', contact_holder=socket.holder_metadata())
    row['knobs']['x_m']['default'] = -.5
    row['knobs']['mount'].update(default='contact pack',choices=['contact pack'])
    levels.append(easy('easy-power', 'Give it power', 'Drop the charged battery onto both metal pads in the holder. Both contacts must complete the lamp circuit.',
                       s, row, {'piece': 'battery', 'x_m': -.5, 'z_m':0, 'mount':'contact pack','height_m':.4},
                       {'load_power_w': {'device': 'lamp', 'at_least_w': 2, 'for_s': .5}},
                       {'piece': 'battery', 'x_m': .6, 'z_m':0, 'mount':'contact pack','height_m':.4}))
    # Preserve the contact-pack lesson for earlier shares and its Sandbox
    # example. The current beginner lesson tests voltage and a complete loop.
    global LEGACY_CONTACT_POWER
    LEGACY_CONTACT_POWER = copy.deepcopy(levels[-1])
    LEGACY_CONTACT_POWER['par_energy_j'] = 375000000
    s = empty('Give it power'); merge(s, bulb('lamp', {'x_m': .6}, {}))
    row = tray('battery',across=False)
    row['knobs'] = {'voltage_v':row['knobs']['voltage_v']}
    row['knobs']['voltage_v'].update(default=6,min=6,max=12)
    lead = tray('wire',across=False); lead['count']=2
    lead['knobs'] = {key:lead['knobs'][key] for key in ('a_terminal','b_terminal','size','length_m')}
    lead['knobs']['size']['default'] = 'thin'
    lead['knobs']['size']['choices'] = ['thin','standard','thick']
    lead['knobs']['length_m'].update(default=5,min=5,max=5,hidden=True)
    solution = [{'piece':'battery','voltage_v':12},
                {'piece':'wire','a_terminal':'your battery 1:plus','b_terminal':'lamp:plus','size':'standard'},
                {'piece':'wire','a_terminal':'lamp:minus','b_terminal':'your battery 1:minus','size':'standard'}]
    levels[-1] = easy('easy-power','Give it power',
        'Choose 12 V for the lamp. Connect battery + to lamp + and lamp − to battery −. Use thicker wires if voltage loss leaves it dim.',
        s,row,solution[0],{'load_power_w':{'device':'lamp','at_least_w':2,'for_s':.5}},solution[0])
    levels[-1].update(tray=[row,lead],solution=solution,
        wrong=[dict(p,voltage_v=6) if p['piece']=='battery' else copy.deepcopy(p) for p in solution],style_pieces=3)
    s = empty('Close the switch'); merge(s, battery('supply', {'x_m': -.6}, {})); merge(s, bulb('lamp', {'x_m': .6}, {}))
    link(s, 'return wire', 'lamp:minus', 'supply:minus')
    levels.append(easy('easy-switch', 'Close the switch', 'Place the wired switch, then drag its field handle downward to close the lamp circuit. Its initial state sets its starting physical position.',
                       s, tray('switch', connect_to={'in': 'supply:plus', 'out': 'lamp:plus'}),
                       {'piece': 'switch', 'state': 'closed'}, {'load_power_w': {'device': 'lamp', 'at_least_w': 2, 'for_s': .5}},
                       {'piece': 'switch', 'state': 'open'}))
    # This lesson teaches field operation, so it cannot be completed by
    # selecting an already-closed starting pose (Sandbox retains that option).
    levels[-1]['tray'][0]['knobs']['state'].update(default='open', choices=['open'])
    levels[-1]['tray'][0]['knobs']['mode'].update(default='manual', choices=['manual'])
    levels[-1]['solution'] = [{'piece': 'switch', 'state': 'open'}]
    levels[-1]['solution_inputs'] = [dict(name='your switch 1', force_n=[0,-8,0])]
    levels[-1]['brief'] = 'Place the prewired switch. Select Run above the scene, then drag its highlighted handle downward to light the lamp.'
    levels[-1]['hints'][0] = levels[-1]['brief']
    s = empty('Light the bulb'); merge(s, battery('supply', {'x_m': -.6}, {})); merge(s, switch('control', {'state': 'closed'}, {}))
    link(s, 'supply wire', 'supply:plus', 'control:in')
    levels.append(easy('easy-bulb', 'Light the bulb', 'Add a prewired bulb and run the prepared circuit. Visible leads already join the closed switch and supply; moving the bulb does not make or break a connection.',
                       s, tray('bulb', connect_to={'plus': 'control:out', 'minus': 'supply:minus'}),
                       {'piece': 'bulb', 'x_m': .6}, {'load_power_w': {'device': 'your bulb 1', 'at_least_w': 2, 'for_s': .5}},
                       {'piece': 'bulb', 'x_m': .6, 'preset': 'small'}, seconds=4))
    # A wrong bulb location alone does not open an explicit wire graph. Its
    # wrong control is an open supply in the copied scenario, tested separately.
    levels[-1]['wrong'] = []
    global LEGACY_BULB_LEVEL
    LEGACY_BULB_LEVEL = copy.deepcopy(levels[-1])
    LEGACY_BULB_LEVEL['tray'][0]['knobs'].pop('size')
    LEGACY_BULB_LEVEL['par_energy_j'] = 102000000
    s = empty('Light the bulb')
    merge(s,battery('supply',{'x_m':-.6,'max_power_w':2.5},{}))
    merge(s,switch('control',{'state':'closed'},{}))
    link(s,'supply wire','supply:plus','control:in')
    row=tray('bulb',connect_to={'plus':'control:out','minus':'supply:minus'},
             start_at_defaults=True,focus_knob='size')
    row['knobs']={key:row['knobs'][key] for key in ('x_m','z_m','size')}
    row['knobs']['x_m']['default']=.6
    row['knobs']['size'].update(default='large',choices=['large','medium','small'])
    levels[-1]=easy('easy-bulb','Light the bulb',
        'Compare the bulb’s 12 V power rating with the wires’ shared supply limit. Shrink the bulb until enough power reaches it.',
        s,row,{'piece':'bulb','x_m':.6,'size':'small'},
        {'load_power_w':{'device':'your bulb 1','at_least_w':2,'for_s':.5}},
        {'piece':'bulb','x_m':.6,'size':'large'})
    s = manual_loop(); s['electrical']['wires'].pop()
    levels.append(easy('easy-loop', 'Finish the loop', 'Click lamp −, then supply − to draw the missing return wire. Run it to light the bulb. Crossing wires do not connect.',
                       s, tray('wire'), {'piece': 'wire', 'a_terminal': 'lamp:minus', 'b_terminal': 'supply:minus'},
                       {'load_power_w': {'device': 'lamp', 'at_least_w': 2, 'for_s': .5}},
                       {'piece': 'wire', 'a_terminal': 'lamp:minus', 'b_terminal': 'lamp:plus'}))
    s = empty('Turn the axle'); merge(s, battery('supply', {'x_m': -.6}, {}))
    levels.append(easy('easy-motor', 'Turn the axle', 'Add the prewired motor and choose its direction to turn the flag. Its visible leads reach the supply; its location does not connect it.',
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
LEGACY_MOTOR_LEVEL = copy.deepcopy(next(row for row in EASY_LEVELS if row['id']=='easy-motor'))
_motor_lesson = next(row for row in EASY_LEVELS if row['id']=='easy-motor')
_motor_lesson['tray'][0].update(start_at_defaults=True, focus_knob='direction')
_motor_lesson['tray'][0]['knobs']['direction']['default'] = 'reverse'
_PARS = {'easy-power': 882000000, 'easy-switch': 18700000, 'easy-bulb': 102000000,
         'easy-loop': 1.75, 'easy-motor': 1550000000, 'easy-heat': 4690000, 'easy-marble-light': 462000000}
for _level in EASY_LEVELS:
    _level['par_energy_j'] = _PARS[_level['id']]
for _template, _pieces in zip(TEMPLATES, [['battery', 'switch', 'bulb', 'wire'], ['battery', 'bulb', 'wire'],
                                       ['switch', 'bulb'], ['motor', 'battery'], ['ignition', 'battery']]):
    _template['pieces'] = _pieces
TEMPLATES.append({'name':'Drop a battery into its holder',
                  'description':'A loose battery falls onto two metal pads. Lift it away to break the lamp circuit.',
                  'base':copy.deepcopy(LEGACY_CONTACT_POWER['machine']),
                  'placements':copy.deepcopy(LEGACY_CONTACT_POWER['solution']),
                  'pieces':['battery','bulb','wire']})

LEGACY_SWITCH_LEVELS = {row['id']:copy.deepcopy(row) for row in EASY_LEVELS
                       if row['id']=='easy-marble-light'}
for _row in LEGACY_SWITCH_LEVELS.values():
    # The old near-side miss can rebound from a physical lead into the deck.
    # Use a clear lateral miss for the negative rehearsal, with the same goal.
    _row['wrong']=[dict(piece='switch',mode='paddle',z_m=.5,threshold_deg=5)]
    for _tray in _row['tray']:
        if _tray['piece']=='switch': _tray['legacy_contacts']=True
CONTACT_SWITCHES = True
for _spec in [row['machine'] for row in EASY_LEVELS] + [row['base'] for row in TEMPLATES]:
    for _device in (_spec.get('electrical') or {}).get('devices',[]):
        if _device['kind']=='switch' and _device.get('hinge'): add_switch_contacts(_spec,_device)
_marble_lesson=next(row for row in EASY_LEVELS if row['id']=='easy-marble-light')
_marble_lesson['tray'][0]['knobs']['threshold_deg']['default']=5
_marble_lesson['tray'][0]['knobs']['mode']['choices']=['paddle']
_marble_lesson['brief']='Place the paddle beneath the marble. Its iron contact leaf must touch the separate iron output pad to complete the wired bulb loop.'

# Missing versions in old saves keep the measured, balanced v2 paddle.
# Fresh tray pieces explicitly carry v3; recipe URLs preserve both older laws.
LEGACY_CONTACT_PADDLE_LEVEL = copy.deepcopy(_marble_lesson)
_switch_tray = next(row for row in TRAY if row['piece']=='switch')
_switch_tray['knobs']['mechanism_version'] = dict(default=3, legacy_default=2,
    min=2, max=3, step=1, hidden=True, label='switch construction version')
_switch_tray['description'] = 'Drag the manual rocker, or press the broad paddle deck to bring its metal leaf onto the output pad.'
_marble_lesson['tray'][0]['description'] = 'Press the broad deck with the marble. The attached metal leaf must meet the separate output pad.'
_marble_lesson['tray'][0]['knobs']['mechanism_version'] = copy.deepcopy(_switch_tray['knobs']['mechanism_version'])
for _placement in _marble_lesson['solution'] + _marble_lesson['wrong']:
    _placement['mechanism_version'] = 3
# A lateral miss stays clear of the battery and lamp. With physical cords and
# the wider deck, the old +30 cm placement can catch the bouncing marble.
_marble_lesson['wrong'][0].update(x_m=0,z_m=.6)
_marble_lesson['par_energy_j'] = 575000000  # Measured new deck/frame/curb construction, rounded up.
_marble_lesson['brief'] = 'Place the broad press deck beneath the marble. Pressing it lowers the metal leaf onto the output pad and completes the lamp circuit.'
_marble_lesson['hints'][0] = _marble_lesson['brief']
_marble_template = next(row for row in TEMPLATES if row['name']=='Marble turns on a light')
_marble_device = next(d for d in _marble_template['base']['electrical']['devices'] if d['kind']=='switch')
press_paddle(_marble_template['base'], _marble_device)
_marble_template['description'] = 'A marble presses the broad deck. A separate metal leaf meets its output pad to light the wired lamp.'

_heat_lesson=next(row for row in EASY_LEVELS if row['id']=='easy-heat')
LEGACY_HEAT_LEVEL=copy.deepcopy(_heat_lesson)
_heater_tray=next(row for row in TRAY if row['piece']=='ignition')
_heater_tray['knobs']['attachment_version']=dict(default=2,legacy_default=1,min=1,max=2,step=1,hidden=True,label='heater construction version')
_heater_tray['knobs']['target'].update(default='',legacy_default='included oak cord',scene_attach=True)
_heater_tray['description']='Clip the hollow heater onto material in the scene, then connect both power leads. Current supplies native Joule heat.'
_heat_row=tray('ignition',start_at_defaults=True,focus_knob='preset')
_heat_wire=tray('wire');_heat_wire['count']=2
_heat_lesson['tray']=[_heat_row,_heat_wire]
_heat_lesson['solution']=[dict(piece='ignition',attachment_version=2,target='weight rope',preset='hot'),
    dict(piece='wire',a_terminal='supply:plus',b_terminal='your ignition 1:plus'),
    dict(piece='wire',a_terminal='your ignition 1:minus',b_terminal='supply:minus')]
_heat_lesson['wrong']=copy.deepcopy(_heat_lesson['solution']);_heat_lesson['wrong'][0]['preset']='warm'
_heat_lesson['brief']='Clip the heater onto the hanging cord. Connect battery + to heater + and heater − to battery −. Choose hot to weaken the cord and release the weight.'
_heat_lesson['hints']=[_heat_lesson['brief'],'The hollow clip surrounds the cord. Without both power leads, current and heating are zero. Watch measured watts and cord temperature.']
_heat_lesson['style_pieces']=3
_heat_lesson['par_energy_j']=37900000  # New iron clip construction and measured source use, rounded up.
_burn_template=next(row for row in TEMPLATES if row['name']=='Burn the cord')
_burn_template['base']['parts']=[p for p in _burn_template['base']['parts'] if not p['name'].startswith('heater ')]
_burn_template['base']['electrical']['devices']=[d for d in _burn_template['base']['electrical']['devices'] if d['name']!='heater']
_burn_template['base']['electrical']['wires']=[]
_burn_template['placements']=copy.deepcopy(_heat_lesson['solution'])
_burn_template['pieces']=['ignition','battery','wire']
_burn_template['description']='A visible heater clip surrounds the hanging cord. Two physical power leads supply Joule heat until the cord weakens and drops the load.'


def advanced_electronics():
    levels=[]
    s=empty('Limit the voltage drop')
    merge(s,battery('supply',{'x_m':-.7},{}));merge(s,bulb('lamp',{'x_m':.7},{}))
    link(s,'lamp return','lamp:minus','supply:minus')
    row=tray('resistor',connect_to={'a':'supply:plus','b':'lamp:plus'},start_at_defaults=True,focus_knob='resistance_ohm')
    lv=easy('advanced-resistor','Limit the voltage drop',
        'The lamp needs at least 2 W. Reduce the series resistor until enough voltage reaches the lamp.',
        s,row,{'piece':'resistor','resistance_ohm':4},
        {'load_power_w':{'device':'lamp','at_least_w':2,'for_s':.5}},
        {'piece':'resistor','resistance_ohm':48})
    levels.append(lv)
    s=empty('Series or parallel?')
    merge(s,battery('supply',{'x_m':-.7},{}))
    merge(s,bulb('first lamp',{'x_m':.5,'z_m':-.3},{}));merge(s,bulb('second lamp',{'x_m':.5,'z_m':.3},{}))
    row=tray('wire');row['count']=4
    solution=[dict(piece='wire',a_terminal='supply:'+key,b_terminal=lamp+':'+key)
        for lamp in ('first lamp','second lamp') for key in ('plus','minus')]
    wrong=[dict(piece='wire',a_terminal=a,b_terminal=b) for a,b in
        [('supply:plus','first lamp:plus'),('first lamp:minus','second lamp:plus'),('second lamp:minus','supply:minus')]]
    lv=easy('advanced-parallel','Series or parallel?',
        'Both 12 V lamps must receive at least 2 W each. Draw their feeds and returns. A series chain splits the voltage; parallel branches each receive the supply voltage.',
        s,row,solution[0],{'load_power_w':{'devices':['first lamp','second lamp'],'at_least_w':2,'for_s':.5}},wrong[0])
    lv['solution']=solution;lv['wrong']=wrong;lv['style_pieces']=1
    levels.append(lv)
    s=empty('Store the charge')
    merge(s,battery('supply',{'x_m':-.7},{}));merge(s,resistor('charging resistor',{'x_m':-.3,'resistance_ohm':12},{}))
    link(s,'resistor feed','supply:plus','charging resistor:a')
    row=tray('capacitor',connect_to={'a':'charging resistor:b','b':'supply:minus'},
        start_at_defaults=True,focus_knob='capacitance_f')
    row['knobs']['x_m']['default']=.3
    row['knobs']['capacitance_f']['default']=.005
    lv=easy('advanced-capacitor','Store the charge',
        'Store at least 4 J in the capacitor within 4 seconds. Increase its capacitance and watch measured volts, current and stored energy rise through the charging resistor.',
        s,row,{'piece':'capacitor','x_m':.3,'capacitance_f':.1},
        {'capacitor_energy_j':{'device':'your capacitor 1','at_least_j':4,'for_s':.1}},
        {'piece':'capacitor','x_m':.3,'capacitance_f':.005})
    levels.append(lv)
    for lv in levels:
        lv['difficulty']='advanced'
        lv['par_energy_j']={'advanced-resistor':173000000,'advanced-parallel':3.5,
                            'advanced-capacitor':227000000}[lv['id']]
    return levels


EASY_LEVELS.extend(advanced_electronics())


def capacitor_workbench():
    s=empty('Charge and release')
    merge(s,battery('supply',{'x_m':-.8},{}))
    merge(s,switch('control',{'x_m':-.4,'state':'closed'},{}))
    merge(s,resistor('charging resistor',{'x_m':0,'resistance_ohm':12},{}))
    merge(s,capacitor('storage',{'x_m':.4,'z_m':-.3},{}))
    merge(s,bulb('lamp',{'x_m':.7,'z_m':.3},{}))
    for index,(a,b) in enumerate([('supply:plus','control:in'),('control:out','charging resistor:a'),
        ('charging resistor:b','storage:a'),('storage:b','supply:minus'),('storage:a','lamp:plus'),('lamp:minus','storage:b')]):
        link(s,'lead '+str(index+1),a,b)
    return s


TEMPLATES.extend([
    dict(name='Charge and release',description='Run to charge the nonpolar capacitor. Drag the switch open: stored energy keeps the lamp glowing while it discharges. Reset starts uncharged.',
         base=capacitor_workbench(),placements=[],pieces=['resistor','capacitor','battery','switch','bulb','wire']),
    dict(name='Series and parallel bench',description='Wire two separate 12 V lamps in series or parallel and compare their measured volts, amps and brightness.',
         base=copy.deepcopy(next(lv['machine'] for lv in EASY_LEVELS if lv['id']=='advanced-parallel')),placements=[],
         pieces=['resistor','capacitor','bulb','battery','wire'])])
_marble_lesson['hints'][0]=_marble_lesson['brief']
