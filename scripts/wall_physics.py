"""Wall placement adapters for the existing three-dimensional native laws.

These declare solids, supports, sources and connections, never trajectories.
Air is a prescribed external flow; boilers use the existing lumped thermal
model. A generator is the reversible DC motor law with no charged supply.
"""
import copy
import math

import machine_world as mw
import sandbox_mechanics as sm
import sandbox_motion as motion
import sandbox_plumbing as plumbing

PLANE = .3


def bracket(name, x, y, rear=.15):
    depth=max(.02,rear+.01)
    return dict(name=name,shape='compound',material='iron',fixed=True,
        at_m=[x,y,depth/2],parts=[dict(shape='box',size_m=[.04,.04,depth],at_m=[0,0,0])])


def generator(name,k,ctx):
    x,y=k['x_m'],k['height_m']
    hinge=k.get('hinge')
    rotor={}
    if not hinge:
        import sandbox_wall as wall
        rotor=wall.water_wheel(name,k,ctx)
        hinge=name+' axle'
    housing=dict(name=name+' housing',shape='compound',material='iron',fixed=True,
        at_m=[x,y,.08],parts=[
            *[dict(shape='box',size_m=[.06,.20,.10],at_m=[side*.07,0,0]) for side in (-1,1)],
            *[dict(shape='box',size_m=[.08,.06,.10],at_m=[0,side*.07,0]) for side in (-1,1)],
            dict(shape='box',size_m=[.04,.34,.06],at_m=[-.08,.26,-.02]),
            dict(shape='box',size_m=[.52,.04,.06],at_m=[-.32,.43,-.02])])
    # Voltage here calibrates k=12/no_load and R=12^2/(stall*no_load).
    # This port remains empty and is disconnected by Circuit::solve. EMF
    # comes only from measured shaft speed, with equal/opposite load torque.
    reference=name+' winding reference'
    result=dict(parts=[housing,bracket(name+' housing bracket',x+.07,y,.03)],
        batteries=[dict(name=reference,**{'in':housing['name']},capacity_j=1,
            charge_j=0,voltage_v=12,max_power_w=0)],
        electrical=dict(devices=[dict(name=name,kind='generator',part=housing['name'],
            battery=reference,hinge=hinge,
            terminals={'plus':[x-.54,y+.43,.12],'minus':[x-.40,y+.43,.12]},
            terminal_normals={'plus':[0,0,1],'minus':[0,0,1]},
            stall_torque_n_m=.04,no_load_rad_s=8,command=1,
            brake_torque_n_m=0,gear_ratio=k.get('gear_ratio',1))]))
    result['parts']+=rotor.get('parts',[])
    result['joints']=rotor.get('joints',[])
    return result


def air(name,k,ctx):
    x,y=k['x_m'],k['height_m'];angle=math.radians(k.get('direction_deg',0))
    axis=[math.cos(angle),math.sin(angle),0];length=k.get('length_m',1.6)
    source=sm.box(name+' nozzle',[.16,.12,.16],[x,y,PLANE],'iron',
        turn_deg=[0,0,k.get('direction_deg',0)])
    return dict(parts=[source,bracket(name+' bracket',x,y,.21)],
        airflows=[dict(name=name+' air',**{'in':source['name']},
            center_m=[x+axis[0]*(length/2+.1),y+axis[1]*(length/2+.1),PLANE],
            size_m=[length, length, .5],
            velocity_m_s=[v*k.get('speed_m_s',12) for v in axis])])


def suspension(builder, pivot_height, support_suffix):
    """Replace a floor stand with a rear bracket, preserving native joints."""
    def build(name,k,ctx):
        local=dict(k,z_m=PLANE,height_m=pivot_height)
        result=builder(name,local,ctx)
        delta=k['height_m']-pivot_height
        mw.shift_rows([0,delta,0],result.get('parts',[])+result.get('joints',[]))
        stand=next(p for p in result['parts'] if p['name']==name+' '+support_suffix)
        stand.clear();stand.update(bracket(name+' '+support_suffix,k['x_m'],k['height_m'],.14))
        return result
    return build


def spring(name,k,ctx):
    result=sm.latched_spring(name,dict(k,z_m=PLANE,load='external'),
        dict(parts=[dict(name='external',fixed=False)]))
    delta=k['height_m']-.04
    mw.shift_rows([0,delta,0],result['parts']+result['joints'])
    result['parts'].append(bracket(name+' wall bracket',k['x_m'],k['height_m'],.15))
    result['parts'].append(bracket(name+' guide bracket',k['x_m'],k['height_m']-.02,.47))
    return result


def pipe(name,k,ctx,kind='pipe'):
    settings=dict(k,z_m=PLANE,support='loose',plane='downward',yaw_deg=0)
    result=plumbing.pipe(name,settings,ctx,kind)
    points=plumbing.path(settings,kind)
    for i,point in enumerate((points[0],points[-1])):
        x,y=k['x_m']+point[0],k['height_m']+point[1]
        anchor=name+f' bracket {i+1}'
        rear=PLANE-k.get('radius_m',.12)-plumbing.WALL_M
        result['parts'].append(bracket(anchor,x,y,rear-.01))
        result['joints'].append(dict(name=anchor+' bolt',kind='fix',a=anchor,b=name,
            at_m=[x,y,PLANE]))
    return result


def mirror(name,k,ctx):
    size=k.get('size_m',.3);angle=k.get('angle_deg',45)
    return dict(parts=[sm.box(name,[.02,size,size],[k['x_m'],k['height_m'],PLANE],
        'aluminum',turn_deg=[0,0,angle]),bracket(name+' bracket',k['x_m'],k['height_m'],.15)],mirrors=[name])


def lens(name,k,ctx):
    return dict(parts=[bracket(name+' bracket',k['x_m'],k['height_m'],.2)],
        kits=[dict(kit='lens',name=name,at_m=[k['x_m'],k['height_m'],PLANE],
        axis=[1,0,0],shape=k.get('shape','convex'),radius_m=k.get('radius_m',.3),
        diameter_m=k.get('diameter_m',.25))])


def laser(name,k,ctx):
    x,y=k['x_m'],k['height_m'];a=math.radians(k.get('direction_deg',0))
    battery=name+' battery';part=name+' battery case'
    return dict(parts=[sm.box(part,[.12]*3,[x,y-.18,PLANE],'iron'),
        bracket(name+' bracket',x,y,.28),bracket(name+' battery bracket',x,y-.18,.24)],
        batteries=[dict(name=battery,**{'in':part},capacity_j=10000,charge_j=10000,voltage_v=12)],
        kits=[dict(kit='laser',name=name,at_m=[x,y,PLANE],aim=[math.cos(a),math.sin(a),0],
            battery=battery,watts=k.get('watts',10),efficiency=.9,beam_width_m=k.get('beam_width_m',.02))])


def boiler(name,k,ctx):
    # Existing boiler starts at boiling temperature. The heater is an
    # explicitly supplied external firebox, not an automatically lit wood fire.
    x,y=k['x_m'],k['height_m']
    return dict(kits=[dict(kit='steam_engine',name=name,at_m=[x,y,PLANE],
            heat_w=k.get('heat_kw',0)*1000,boiler_side='-x')],
        parts=[bracket(name+' cylinder bracket',x,y+.15,.15),
               bracket(name+' boiler bracket',x-.28,y+.08,.22)])


def solar(name,k,ctx):
    x,y=k['x_m'],k['height_m'];angle=k.get('tilt_deg',0)
    normal=[0,math.sin(math.radians(angle)),math.cos(math.radians(angle))]
    store=name+' local battery'
    return dict(parts=[sm.box(name,[.4,.4,.02],[x,y,PLANE],'glass',turn_deg=[-angle,0,0]),
        bracket(name+' bracket',x,y,.29)],
        batteries=[dict(name=store,**{'in':name},capacity_j=10000,charge_j=0,voltage_v=12)],
        solar_panels=[dict(name=name,part=name,battery=store,normal=normal,area_m2=.16,efficiency=.2)],
        electrical=dict(power_ports=[dict(name=name+':power',kind='output',solar_panel=name,
            part=name,at_m=[x-.22,y,.32])]))


PIECES=dict(wall_generator=generator,wall_air=air,wall_spring=spring,
    wall_pendulum=suspension(motion.pendulum,1.3,'post'),
    wall_trapdoor=suspension(motion.trapdoor,.65,'stand'),
    wall_pipe=pipe,wall_pipe_elbow=lambda n,k,c:pipe(n,k,c,'pipe_elbow'),
    wall_pipe_reducer=lambda n,k,c:pipe(n,k,c,'pipe_reducer'),
    wall_mirror=mirror,wall_lens=lens,wall_laser=laser,wall_boiler=boiler,wall_solar=solar)


def tray():
    n,c=sm.number,sm.choice
    entries=[
        ('wall_generator','Water wheel generator',dict(radius_m=n('Wheel radius (m)',.15,.5,.3,.025),
            gear_ratio=n('Shaft ratio',.25,1,1,.25))),
        ('wall_air','Wall air nozzle',dict(speed_m_s=n('Air speed (m/s)',0,20,0,1),
            direction_deg=n('Air direction (°)',-180,180,0,5),length_m=n('Air region reach (m)',.5,2,1.6,.1))),
        ('wall_spring','Wall spring launcher',dict(rest_m=n('Relaxed length (m)',.25,.65,.5,.025),
            compressed_m=n('Held length (m)',.1,.25,.2,.025),
            stiffness_n_m=n('Stiffness (N/m)',50,500,200,25),damping_n_s_m=n('Damping (N s/m)',0,10,1,.5))),
        ('wall_pendulum','Wall pendulum',dict(length_m=n('Arm length (m)',.3,.9,.7,.05),
            start_deg=n('Release angle (°)',-70,70,0,5),friction_n_m=n('Axle friction (N·m)',0,.1,.001,.001),
            material=c('Material',['oak','glass','iron'],'oak'))),
        ('wall_trapdoor','Wall trapdoor',dict(length_m=n('Flap length (m)',.2,.7,.5,.05),
            friction_n_m=n('Hinge resistance (N·m)',0,20,10,.1),material=c('Material',['oak','glass','iron'],'oak'))),
        ('wall_mirror','Wall mirror',dict(size_m=n('Mirror size (m)',.2,.6,.3,.05),angle_deg=n('Face angle (°)',-90,90,0,1))),
        ('wall_lens','Wall lens',dict(radius_m=n('Focus / face radius (m)',.2,.8,.3,.025),
            diameter_m=n('Lens diameter (m)',.15,.35,.25,.025),shape=c('Lens shape',['convex','concave'],'convex'))),
        ('wall_laser','Wall laser',dict(direction_deg=n('Beam direction (°)',-180,180,0,1),
            watts=n('Electrical power (W)',1,1000,10,1),beam_width_m=n('Beam spread at 1 m (m)',.002,.3,.02,.002))),
        ('wall_boiler','Wall boiler and piston',dict(heat_kw=n('Firebox heat (kW)',0,20,0,1))),
        ('wall_solar','Wall solar panel',dict(tilt_deg=n('Panel tilt toward the sun (°)',-90,90,0,5))),
    ]
    for kind,title in [('wall_pipe','Wall pipe'),('wall_pipe_elbow','Wall pipe elbow'),('wall_pipe_reducer','Wall pipe reducer')]:
        knobs=dict(radius_m=n('Inside radius (m)',.06,.2,.12,.01),material=c('Pipe material',['glass','oak','iron'],'glass'))
        if kind=='wall_pipe_elbow':
            knobs.update(bend_radius_m=n('Bend radius (m)',.3,.8,.5,.05),bend_deg=c('Bend direction',[-90,-45,45,90],90))
        else:knobs.update(length_m=n('Pipe length (m)',.3,2,1.2,.05),drop_deg=n('Downhill slope (°)',5,60,20,1))
        if kind=='wall_pipe_reducer':knobs['outlet_radius_m']=n('Outlet inside radius (m)',.03,.15,.08,.01)
        entries.append((kind,title,knobs))
    return [dict(piece=kind,title=title,knobs=dict(knobs,
        x_m=n('Left / right (m)',-2.8,2.8,0),height_m=n('Height (m)',.4,3.5,1.5)),
        across=False,turning=False,sandbox_builder=True,cost=0,count=30) for kind,title,knobs in entries]
