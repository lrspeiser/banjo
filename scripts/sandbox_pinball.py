"""An editable inclined pinball machine, assembled from native mechanisms.

SI units. Buttons apply operator force to hinged metal contacts. The circuit
supplies reversible DC hinge actuators; axial return springs oppose them.
No ball velocity, flipper angle or switch state is assigned during play.
"""
import copy
import math
import machine_world as mw
from object_actions import hold

SLOPE = 5
HEIGHT = .8


def rigid(name, at, size, material='oak', fixed=True, turn=None):
    return dict(name=name, shape='box', material=material, fixed=fixed,
                at_m=list(at), turn_deg=turn or [0,0,0],size_m=list(size))


def finish(spec, k):
    """Rigid transform of parts, axes, spring endpoints, terminals and forces."""
    matrix=mw.rotation([-k.get('slope_deg',SLOPE),0,0])
    parts=spec.get('parts',[])
    rows=list(spec.get('joints',[]))
    mw.turn_rows(matrix,[0,0,0],parts,rows)
    for d in spec.get('electrical',{}).get('devices',[]):
        d['terminals']={key:mw._mat_apply(matrix,at) for key,at in d['terminals'].items()}
        d['terminal_normals']={key:mw._mat_apply(matrix,axis) for key,axis in d.get('terminal_normals',{}).items()}
    for c in spec.get('player_controls',[]): c['force_n']=mw._mat_apply(matrix,c['force_n'])
    rise=[0,k.get('table_height_m',HEIGHT),0]
    mw.shift_rows(rise,parts+rows)
    for d in spec.get('electrical',{}).get('devices',[]):
        d['terminals']={key:[at[i]+rise[i] for i in range(3)] for key,at in d['terminals'].items()}
    return spec


def field(name,k,ctx):
    width=k.get('width_m',1.5); length=k.get('length_m',2.6)
    x,z=k.get('x_m',0),k.get('z_m',0)
    # Two actual bearing apertures admit the actuator wiring below the board.
    parts=[rigid(name+' upper surface',[x,0,z+(length/2-.68)/2],[width,.06,length/2+.68]),
           rigid(name+' lower surface',[x,0,z+(-length/2-.84)/2],[width,.06,length/2-.84]),
           rigid(name+' centre surface',[x,0,z-.76],[.72,.06,.16]),
           rigid(name+' left surface',[x-(width/2+.50)/2,0,z-.76],[width/2-.50,.06,.16]),
           rigid(name+' right surface',[x+(width/2+.50)/2,0,z-.76],[width/2-.50,.06,.16]),
           rigid(name+' left rail',[x-width/2-.025,.10,z],[.05,.26,length+.10]),
           rigid(name+' right rail',[x+width/2+.025,.10,z],[.05,.26,length+.10]),
           rigid(name+' back rail',[x,.10,z+length/2+.025],[width,.26,.05])]
    # Open near edge is the drain. Side aprons return missed shots toward it.
    for side in [-1,1]:
        parts.append(rigid(name+f' drain guide {side}',[x+side*.33,.10,z-1.17],[.40,.18,.04],
                           turn=[0,side*25,0]))
    cover=dict(name=name+' glass cover',shape='compound',material='glass',fixed=True,color_rgba=0xccecff18,
        at_m=[x,.24,z],parts=[dict(shape='box',at_m=[0,0,0],size_m=[width,.02,length])])
    frame=dict(name=name+' frame',shape='compound',material='oak',fixed=True,at_m=[x,0,z],parts=[
        dict(shape='box',at_m=[p['at_m'][0]-x,p['at_m'][1],p['at_m'][2]-z],
             size_m=p['size_m'],turn_deg=p.get('turn_deg',[0,0,0])) for p in parts])
    result=finish(dict(parts=[frame,cover],joints=[dict(name=name+' cover fixing',kind='fix',
        a=frame['name'],b=cover['name'],at_m=[x-width/2,.23,z])]),k)
    for sx in [-1,1]:
        for sz in [-1,1]:
            lx=x+sx*(width/2-.12);lz=z+sz*(length/2-.12)
            angle=math.radians(k.get('slope_deg',SLOPE))
            top=k.get('table_height_m',HEIGHT)+(lz-.04)*math.sin(angle)-.03*math.cos(angle)
            leg=rigid(name+f' leg {sx} {sz}',[lx,top/2,lz*math.cos(angle)],[.08,top,.08])
            result['parts'].append(leg)
            result['joints'].append(dict(name=leg['name']+' fixing',kind='fix',a=leg['name'],b=frame['name'],
                                         at_m=[lx,top,lz*math.cos(angle)]))
    return result


def flipper(name,k,ctx):
    x,z=k.get('x_m',-.43),k.get('z_m',-.76)
    side=1 if k.get('side','left')=='left' else -1
    length=k.get('length_m',.40)
    # Local origin is the bearing; exact paddle extends inwards from it.
    paddle=dict(name=name+' paddle',shape='compound',material='aluminum',fixed=False,
        at_m=[x,.06,z],parts=[dict(shape='box',at_m=[side*length/2,0,0],size_m=[length,.04,.075]),
            dict(shape='cylinder',at_m=[0,-.032,0],size_m=[.04,.044,.04])],turn_deg=[0,side*20,0])
    housing=dict(name=name+' bearing',shape='box',material='iron',fixed=True,
                 at_m=[x,-.04,z],size_m=[.12,.08,.12])
    parts=[housing,paddle,rigid(name+' spring anchor',[x,.06,z-.27],[.035,.04,.035],'iron')]
    hinge=name+' axle'
    # The fixed bearing reacts against the actuator, not against world velocity.
    joints=[dict(name=hinge,kind='hinge',a=housing['name'],b=paddle['name'],at_m=[x,.06,z],
                 axis=[0,1,0],lower_deg=-55 if side==1 else 0,upper_deg=0 if side==1 else 55,
                 friction_n_m=.004),
            dict(name=name+' return spring',kind='spring',a=name+' spring anchor',b=paddle['name'],
                 at_m=[x,.06,z-.27],at_b_m=[x+side*.12,.06,z-.044],rest_m=.20,
                 stiffness_n_m=k.get('return_n_m',35),damping_n_s_m=.3)]
    # Sockets face outward, outside the paddle's sweep.
    terminals={key:[x-side*.03,-.086,z+offset] for key,offset in [('plus',-.035),('minus',.035)]}
    return finish(dict(parts=parts,joints=joints,electrical=dict(devices=[dict(name=name,kind='motor',
        part=housing['name'],hinge=hinge,terminals=terminals,
        terminal_normals={key:[0,-1,0] for key in terminals},
        stall_torque_n_m=k.get('torque_n_m',12),no_load_rad_s=30,command=-side,
        brake_torque_n_m=0,gear_ratio=1)])),k)


def button(name,k,ctx):
    x,z=k.get('x_m',-.94),k.get('z_m',-.85)
    base=rigid(name+' base',[x,.06,z],[.14,.08,.16],'ceramic')
    pad=rigid(name+' pad',[x+.045,.1275,z],[.04,.02,.14],'iron')
    cap=dict(name=name+' button',shape='compound',material='aluminum',fixed=False,at_m=[x+.01,.20,z],
             parts=[dict(shape='box',at_m=[0,0,0],size_m=[.12,.01,.08])])
    post=rigid(name+' pivot post',[x-.09,.15,z],[.04,.12,.04],'iron')
    joints=[dict(name=name+' button hinge',kind='hinge',a=post['name'],b=cap['name'],
                 at_m=[x-.05,.20,z],axis=[0,0,1],lower_deg=-35,upper_deg=0,friction_n_m=.001),
            dict(name=name+' return spring',kind='spring',a=base['name'],b=cap['name'],
                 at_m=[x+.06,.10,z],at_b_m=[x+.06,.20,z],rest_m=.12,stiffness_n_m=150,damping_n_s_m=.7)]
    device=dict(name=name,kind='switch',part=base['name'],closed=False,
        touch=[cap['name'],pad['name']],terminal_parts={'in':cap['name'],'out':pad['name']},
        terminals={'in':[x-.05,.20,z-.044],'out':[x+.045,.1275,z+.075]},
        terminal_normals={'in':[0,0,-1],'out':[0,0,1]})
    return finish(dict(parts=[base,pad,cap,post],joints=joints,electrical=dict(devices=[device]),
        **hold(name,cap['name'],[0,-30,0],k.get('label','Press button'),k.get('key',''))),k)


def plunger(name,k,ctx):
    x,z=k.get('x_m',.63),k.get('z_m',-1.20)
    anchor=dict(name=name+' spring seat',shape='compound',material='iron',fixed=True,
        at_m=[x,.052,z-.34],parts=[
            dict(shape='box',at_m=[side*.045,0,0],size_m=[.03,.12,.04]) for side in [-1,1]]+[
            dict(shape='box',at_m=[0,side*.045,0],size_m=[.06,.03,.04]) for side in [-1,1]])
    support=rigid(name+' mounting',[x,.132,z-.34],[.12,.04,.04],'iron')
    pusher=rigid(name+' pusher',[x,.052,z],[.02,.04,.02],'aluminum',False)
    size=pusher.pop('size_m')
    pusher.update(shape='compound',parts=[dict(shape='box',at_m=[0,0,0],size_m=size),
        dict(shape='box',at_m=[0,0,-.26],size_m=[.02,.02,.50])])
    joints=[dict(name=name+' seat mounting',kind='fix',a=support['name'],b=anchor['name'],at_m=[x,.112,z-.34]),
            dict(name=name+' guide',kind='slide',a=anchor['name'],b=pusher['name'],at_m=pusher['at_m'],
                 axis=[0,0,1],lower_m=-.28,upper_m=.12,friction_n=.05),
            dict(name=name+' launcher spring',kind='spring',a=anchor['name'],b=pusher['name'],
                 at_m=[x,.052,z-.32],at_b_m=[x,.052,z-.02],rest_m=.30,
                 stiffness_n_m=k.get('stiffness_n_m',400),damping_n_s_m=.35)]
    # A 32 mm throat retains a 40 mm ball while the 20 mm nose passes through.
    # Exact posts avoid world-cell rounding closing this intentional aperture.
    throat=dict(name=name+' ball stop',shape='compound',material='iron',fixed=True,at_m=[x,0,z+.035],parts=[
        dict(shape='box',at_m=[side*.026,.09,0],size_m=[.02,.12,.04]) for side in [-1,1]]+[
        dict(shape='box',at_m=[0,.16,0],size_m=[.092,.02,.04])])
    throat_mount=rigid(name+' stop mounting',[x+.066,.13,z+.035],[.04,.08,.04],'iron')
    joints.append(dict(name=name+' stop joint',kind='fix',a=throat_mount['name'],b=throat['name'],at_m=[x+.046,.16,z+.035]))
    stops=[throat,throat_mount]
    return finish(dict(parts=[anchor,support,pusher,*stops],joints=joints,
        **hold(name,pusher['name'],[0,0,-120],'Pull launcher · release to shoot',k.get('key',''))),k)


def bumper(name,k,ctx):
    x,z=k.get('x_m',0),k.get('z_m',.5);radius=k.get('radius_m',.13)
    # A passive rubber bumper: material contact returns only impact energy.
    part=dict(name=name,shape='sphere',material='rubber',fixed=True,at_m=[x,.10,z],size_m=[2*radius]*3)
    return finish(dict(parts=[part]),k)


def rail(name,k,ctx):
    return finish(dict(parts=[rigid(name,[k.get('x_m',0),.11,k.get('z_m',0)],
        [k.get('length_m',.5),.20,.04],turn=[0,k.get('angle_deg',0),0])]),k)


def ball(name,k,ctx):
    diameter=k.get('diameter_m',.04)
    return finish(dict(parts=[dict(name=name,shape='compound',material=k.get('material','iron'),fixed=False,
        at_m=[k.get('x_m',.63),.032+diameter/2,k.get('z_m',-1.13)],
        parts=[dict(shape='sphere',at_m=[0,0,0],size_m=[diameter]*3)])]),k)


def target(name,k,ctx):
    x,z=k.get('x_m',0),k.get('z_m',.8)
    post=rigid(name+' post',[x+.10,.15,z],[.04,.24,.04],'iron')
    plate=rigid(name+' target',[x,.12,z],[.12,.14,.02],'aluminum',False)
    return finish(dict(parts=[post,plate],joints=[dict(name=name+' axle',kind='hinge',
        a=post['name'],b=plate['name'],at_m=[x,.20,z],axis=[1,0,0],lower_deg=-65,upper_deg=65,friction_n_m=.002)]),k)


PIECES={'pinball_field':field,'pinball_flipper':flipper,'pinball_button':button,
        'pinball_plunger':plunger,'pinball_bumper':bumper,'pinball_rail':rail,
        'pinball_ball':ball,'pinball_target':target}
TEMPLATES=[]  # The dedicated Pinball starter is separate from the five examples.
POS=dict(x_m=dict(min=-3,max=3,step=.01,default=0,label='across (m)'),
         z_m=dict(min=-3,max=3,step=.01,default=0,label='along table (m)'))


def row(piece,title,knobs,description):
    labels=dict(side='Flipper side',length_m='Length (m)',width_m='Width (m)',
        torque_n_m='Stall torque (N m)',return_n_m='Return spring (N/m)',
        stiffness_n_m='Spring stiffness (N/m)',radius_m='Radius (m)',
        angle_deg='Rail heading (degrees)',diameter_m='Ball diameter (m)',material='Material')
    knobs=copy.deepcopy(knobs)
    for key,rule in knobs.items():rule.setdefault('label',labels[key])
    return dict(piece=piece,title=title,description=description,cost=0,count=20,
                sandbox_builder=True,across=False,turning=False,knobs=dict(copy.deepcopy(POS),**knobs))


TRAY=[
    row('pinball_field','Pinball playfield',dict(width_m=dict(default=1.5,min=1.2,max=2,step=.1),
        length_m=dict(default=2.6,min=2.6,max=4,step=.1)), 'An inclined wooden surface, side rails and an open drain.'),
    row('pinball_flipper','Powered pinball flipper',dict(side=dict(default='left',choices=['left','right']),
        length_m=dict(default=.40,min=.25,max=.5,step=.01),torque_n_m=dict(default=12,min=1,max=12,step=1),
        return_n_m=dict(default=35,min=10,max=80,step=5)), 'Wire a button and battery to the motor. Its spring returns the paddle when power opens.'),
    row('pinball_button','Spring-return button',{}, 'A hinged metal button closes real conductor contacts while you hold it.'),
    row('pinball_plunger','Pinball spring launcher',dict(stiffness_n_m=dict(default=400,min=100,max=500,step=20)),
        'Hold to compress the spring; release to launch through contact with the ball.'),
    row('pinball_bumper','Rubber pinball bumper',dict(radius_m=dict(default=.13,min=.08,max=.2,step=.01)),
        'A passive material bumper. It cannot add energy to an impact.'),
    row('pinball_rail','Pinball guide rail',dict(length_m=dict(default=.5,min=.1,max=1.5,step=.05),
        angle_deg=dict(default=0,min=-180,max=180,step=5,turning=True)), 'A solid guide on the inclined surface.'),
    row('pinball_ball','Smooth pinball',dict(diameter_m=dict(default=.04,min=.03,max=.08,step=.005),
        material=dict(default='iron',choices=['iron','glass','oak'])), 'An exact rigid sphere with material-derived mass and inertia.'),
    row('pinball_target','Hanging pinball target',{}, 'An impact swings this target on a bearing; gravity returns it.')]


def template():
    import machine_game as mg
    spec=dict(schema=mw.SCHEMA,title='Pinball',cell_m=.02,physics_dt_s=1/480,parts=[],joints=[],batteries=[],
              electrical=dict(devices=[],wires=[]),stations=[],presentation={'camera':'overview','activity':'pinball',
                'selection_passthrough':['pinball table glass cover']})
    for build,name,k in [(field,'pinball table',{}),
        (flipper,'left flipper',dict(x_m=.43,z_m=-.76,side='right')),
        (flipper,'right flipper',dict(x_m=-.43,z_m=-.76,side='left')),
        (button,'left button',dict(x_m=.96,z_m=-.85,label='Left flipper',key='ArrowLeft')),
        (button,'right button',dict(x_m=-.96,z_m=-.85,label='Right flipper',key='ArrowRight')),
        (plunger,'launcher',dict(key='Space')),
        (rail,'launch lane',dict(x_m=.51,z_m=-.275,length_m=1.85,angle_deg=90)),
        (rail,'launch turn',dict(x_m=.49,z_m=1.08,length_m=.60,angle_deg=45)),
        # Meet the outer rail opposite the launcher upstream of the flipper.
        # The launch-lane side must leave the shooter lane unobstructed.
        (rail,'right inlane guide',dict(x_m=.34,z_m=-.25,length_m=.40,angle_deg=-45)),
        (rail,'left inlane guide',dict(x_m=-.56,z_m=-.16,length_m=.72,angle_deg=55)),
        (bumper,'upper bumper',dict(x_m=0,z_m=.65)),
        (bumper,'left bumper',dict(x_m=-.31,z_m=.20,radius_m=.11)),
        (bumper,'right bumper',dict(x_m=.26,z_m=.05,radius_m=.11)),
        (target,'left target',dict(x_m=-.4,z_m=.9)),
        (target,'right target',dict(x_m=.25,z_m=.9))]:
        mg.merge_fragment(spec,build(name,k,{}))
    # The supply and its wiring are outside the ball's working surface.
    supply=finish(dict(parts=[rigid('pinball supply housing',[-1.15,.13,.25],[.20,.20,.28],'iron')],
        electrical=dict(devices=[dict(name='pinball supply',kind='battery',part='pinball supply housing',
            battery='pinball battery',terminals={'plus':[-1.256,.13,.20],'minus':[-1.256,.13,.30]},
            terminal_normals={'plus':[-1,0,0],'minus':[-1,0,0]})])),{})
    supply['batteries']=[dict(name='pinball battery',**{'in':'pinball supply housing'},
        capacity_j=10000,charge_j=10000,voltage_v=24,max_power_w=1000)]
    mg.merge_fragment(spec,supply)
    terminals={d['name']+':'+key:at for d in spec['electrical']['devices'] for key,at in d['terminals'].items()}
    normals={d['name']+':'+key:axis for d in spec['electrical']['devices'] for key,axis in d.get('terminal_normals',{}).items()}
    for side in ['left','right']:
        for a,b in [('pinball supply:plus',side+' button:in'),(side+' button:out',side+' flipper:plus'),
                    (side+' flipper:minus','pinball supply:minus')]:
            lane=len(spec['electrical']['wires']);pa,pb=terminals[a],terminals[b]
            # Service loops run below the deck; bearing apertures are real holes.
            low=.42-lane*.012
            ea=[pa[i]+.10*normals[a][i] for i in range(3)]
            eb=[pb[i]+.10*normals[b][i] for i in range(3)]
            path=[pa,ea,[ea[0],low,ea[2]],[(ea[0]+eb[0])/2,low-.08,(ea[2]+eb[2])/2],
                  [eb[0],low,eb[2]],eb,pb]
            span=sum(math.dist(p,q) for p,q in zip(path,path[1:]))
            spec['electrical']['wires'].append(dict(name=f'{side} lead {lane+1}',
                a=a,b=b,length_m=span,area_mm2=2.5,mechanical=dict(path_m=path,retention_n=200,segment_m=.08)))
    mg.merge_fragment(spec,ball('pinball',{},{}))
    for hit in ['upper bumper','left bumper','right bumper','left flipper paddle','right flipper paddle','left target target','right target target']:
        spec['stations'].append(dict(title='Touch '+hit,focus=['pinball',hit],done_when={'touches':['pinball',hit]}))
    return dict(name='Pinball',description='Hold the launcher, release, and use the powered flippers during Run. Reset loads another ball.',
                base=spec,placements=[],pieces=list(PIECES))
