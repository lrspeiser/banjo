"""Mounting wall inside the 3D world, using native contact and joints.

Wall-specific editor placement is planar; ordinary pieces retain all axes.
Version 2 has real track rails and no global front sheet. Historical version 1
retains its real transparent guard. Mounts are ideal supports, not a bolt model.
There is no runtime projection, assigned rolling speed or event sequencing.
"""
import copy
import math
import re

import machine_world as mw
import sandbox_electrics as se
import sandbox_mechanics as sm

PLANE = .30
WIDTH, HEIGHT, DEPTH = 6., 4., .62
FOUNDATION = ('workshop backing', 'workshop clear guard')


def surface():
    return dict(kind='wall', version=1, width_m=WIDTH, height_m=HEIGHT,
                plane_z_m=PLANE, depth_m=DEPTH)


def world_surface():
    return dict(surface(), version=2)


def base():
    return dict(schema='banjo.machine.v1', title='Wall workshop', cell_m=.02,
        build_surface=surface(), presentation=dict(camera='wall'),
        parts=[sm.box(FOUNDATION[0], [WIDTH, HEIGHT, .02], [0, HEIGHT/2, -.01], 'oak'),
               dict(name=FOUNDATION[1], shape='compound', material='glass', fixed=True,
                    at_m=[0, HEIGHT/2, DEPTH+.006], parts=[dict(shape='box',
                         size_m=[WIDTH, HEIGHT, .012], at_m=[0, 0, 0])])],
        kits=[], joints=[dict(name='workshop guard mounting',kind='fix',
            a=FOUNDATION[0],b=FOUNDATION[1],at_m=[0,HEIGHT/2,0])], stations=[])


def world_base():
    result=base()
    result.update(build_surface=world_surface(),presentation=dict(camera='wall_world'),title='Wall in the world')
    result['parts']=result['parts'][:1]
    result['joints']=[]
    return result


def panels(spec):
    """Editable parallel mounting faces; old saves keep their original wall."""
    return copy.deepcopy(spec.get('build_surface',{}).get('panels') or [
        dict(id=FOUNDATION[0],width_m=WIDTH,height_m=HEIGHT,x_m=0,z_m=0)])


def panel_part(panel):
    return sm.box(panel['id'],[panel['width_m'],panel['height_m'],.02],
                  [panel['x_m'],panel['height_m']/2,panel['z_m']-.01],'oak')


def panel_surface(rows):
    first=rows[0]
    return dict(world_surface(),width_m=first['width_m'],height_m=first['height_m'],
                plane_z_m=first['z_m']+PLANE,panels=copy.deepcopy(rows))


def _validate_panels(rows):
    if not isinstance(rows,list) or not 1<=len(rows)<=8:raise ValueError('Use one to eight mounting walls.')
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'id','width_m','height_m','x_m','z_m'}:
            raise ValueError('A mounting wall needs its size and ground position.')
        if not isinstance(row['id'],str) or not re.fullmatch(r'workshop backing|mounting wall [2-9]\d*',row['id']) or row['id'] in seen:
            raise ValueError('Every mounting wall needs a unique id.')
        seen.add(row['id'])
        for key,lo,hi in (('width_m',.5,12),('height_m',.5,10),('x_m',-16,16),('z_m',-16,16)):
            value=row[key]
            if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:
                raise ValueError(f'Wall {key} must be {lo} to {hi} metres.')
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            if abs(a['z_m']-b['z_m'])<.021 and abs(a['x_m']-b['x_m'])<(a['width_m']+b['width_m'])/2+.001:
                raise ValueError('The mounting walls overlap; move them apart.')


def validate(spec):
    """A saved board has a versioned, fixed physical foundation."""
    if spec.get('build_surface') is None:
        return False
    declared=spec['build_surface']
    editable=declared.get('version')==2 and 'panels' in declared
    if editable:
        _validate_panels(declared['panels'])
        if declared!=panel_surface(declared['panels']):raise ValueError('The wall size and mounting faces disagree.')
    elif declared not in (surface(),world_surface()):
        raise ValueError('This wall workshop uses an unsupported mounting surface.')
    expected_base=world_base() if declared['version']==2 else base()
    if editable:expected_base['parts']=[panel_part(row) for row in declared['panels']]
    parts = {p.get('name'): p for p in spec.get('parts', [])}
    if declared['version']==2 and FOUNDATION[1] in parts:
        raise ValueError('The open wall world has no front retaining sheet.')
    for expected in expected_base['parts']:
        if parts.get(expected['name']) != expected:
            raise ValueError('The wall workshop needs its declared backing and retaining parts.')
    if any(j not in spec.get('joints',[]) for j in expected_base['joints']):
        raise ValueError('The wall workshop needs its guard mounting.')
    return True


def bounds_problems(compiled, mounted_owners=None, panel_rows=None):
    problems=[]
    for p in compiled['parts']:
        if not p['name'].startswith('your '):continue
        if mounted_owners is not None and not any(p['name']==name or p['name'].startswith(name+' ') for name in mounted_owners):continue
        panel=dict(width_m=WIDTH,height_m=HEIGHT,x_m=0,z_m=0)
        if isinstance(mounted_owners,dict) and panel_rows:
            owner=next(name for name in mounted_owners if p['name']==name or p['name'].startswith(name+' '))
            panel=next(row for row in panel_rows if row['id']==mounted_owners[owner])
        points=[pt for solid in mw.solids_of(p) for pt in mw.footprint_points(solid)]
        if any(abs(pt[0]-panel['x_m'])>panel['width_m']/2+.001 or pt[1]<0 or pt[1]>panel['height_m']+.001 or
               pt[2]<panel['z_m']-.001 or (mounted_owners is None and pt[2]>DEPTH+.001) for pt in points):
            problems.append(p['name']+' extends beyond the wall; move it inside the board')
    return problems


def place_on_panel(fragment,panel):
    """Translate declared fixtures, anchors and electrical sockets before running."""
    dz=panel['z_m']
    rows=[row for value in fragment.values() if isinstance(value,list) for row in value]
    devices=fragment.get('electrical',{}).get('devices',[])
    mw.shift_rows([0,0,dz],rows+devices)
    for device in devices:
        device['terminals']={key:[at[0],at[1],at[2]+dz] for key,at in device.get('terminals',{}).items()}
        if device.get('handle'):mw.shift_rows([0,0,dz],[device['handle']])
    return fragment


def edit_panel(base_spec,placements,panel_id,changes=None,add=False,edit_key=None):
    """An undoable setup edit, leaving the running world and input untouched."""
    import machine_game as mg
    if not validate(base_spec) or base_spec['build_surface']['version']!=2:
        raise ValueError('Open this wall into the 3D world before editing its size.')
    result=copy.deepcopy(base_spec);rows=panels(result);placed=copy.deepcopy(placements)
    if add:
        used={row['id'] for row in rows};number=2
        while 'mounting wall '+str(number) in used:number+=1
        panel_id='mounting wall '+str(number)
        right=max(row['x_m']+row['width_m']/2 for row in rows)
        rows.append(dict(id=panel_id,width_m=3.,height_m=3.,x_m=right+2,z_m=rows[-1]['z_m']))
    selected=next((row for row in rows if row['id']==panel_id),None)
    if selected is None:raise ValueError('Choose a mounting wall in this design.')
    old=copy.deepcopy(selected)
    if changes:
        if not isinstance(changes,dict) or set(changes)-{'x_m','z_m','width_m','height_m'}:
            raise ValueError('Change wall width, height or ground position.')
        selected.update(changes)
    _validate_panels(rows)
    wall_types=set(WORLD_PIECES)
    for p in placed:
        if p['piece'] in wall_types and p.get('wall',FOUNDATION[0])==panel_id:
            p['x_m']=p.get('x_m',0)+selected['x_m']-old['x_m']
    names={row['id'] for row in rows}
    result['parts']=[p for p in result.get('parts',[]) if p['name'] not in names]+[panel_part(row) for row in rows]
    result['build_surface']=panel_surface(rows)
    level=mg.requested_level(dict(level='free',base=result))
    _,checked,_,compiled=mg._assemble(level,placed,lenient=True)
    problems=compiled.get('problems',[])+mg.clashes_of(compiled)
    owners={f'your {p["piece"]} {i+1}' for i,p in enumerate(checked)
            if p['piece'] in wall_types and p.get('wall',FOUNDATION[0])==panel_id}
    parts=[p for p in compiled['parts'] if p['name']==panel_id or mg.owner(p) in owners]
    guide=None
    if edit_key in ('width_m','wall_height_m'):
        x,z=selected['x_m'],selected['z_m'];w,h=selected['width_m'],selected['height_m']
        arrows=([dict(at=[x+w/2,h/2,z],direction=[1,0,0]),dict(at=[x-w/2,h/2,z],direction=[-1,0,0])]
                if edit_key=='width_m' else [dict(at=[x,h,z],direction=[0,1,0]),dict(at=[x,0,z],direction=[0,-1,0])])
        guide=dict(key=edit_key,focus=[panel_id],arrows=arrows,marker=None)
    return dict(base=result,placements=placed,parts=parts,selected=dict(id='wall:'+panel_id,parts=[p['name'] for p in parts]),
        wall=selected,fits=not problems,problems=problems[:4],cost=0,sun=[],edit_guide=guide,
        electrical_preview=compiled.get('electrical',{}),battery_preview=compiled.get('batteries',[]))


def mount(name, x, y, rear):
    # The rear of every bracket touches the backing; it ends just inside the
    # supported solid. Internal overlap belongs to the same apparatus.
    depth = max(.02, rear+.01)
    return dict(name=name,shape='compound',material='iron',fixed=True,at_m=[x,y,depth/2],
                parts=[dict(shape='box',size_m=[.04,.04,depth],at_m=[0,0,0])])


def track(name, k, ctx):
    x, y = k['x_m'], k['height_m']
    length, angle = k.get('length_m', 1.4), k.get('angle_deg', -16)
    shapes=[dict(shape='box',size_m=[length,.04,.56],at_m=[0,0,0])]
    if (ctx or {}).get('tray',{}).get('open_world'):
        shapes.extend(dict(shape='box',size_m=[length,.10,.02],at_m=[0,.06,side*.27]) for side in (-1,1))
    if k.get('end_stop','closed')=='closed':
        shapes.append(dict(shape='box',size_m=[.04,.28,.56],
            at_m=[(-1 if angle<=0 else 1)*(length/2-.02),.12,0]))
    return {'parts': [dict(name=name+' track', shape='compound', material='oak', fixed=True,
        at_m=[x,y,PLANE], turn_deg=[0,0,angle], parts=shapes), mount(name+' bracket',x,y,.02)]}


def funnel(name, k, ctx):
    x,y=k['x_m'],k['height_m']; width=k.get('width_m',.7)
    run=(width-.14)/2; drop=.24; length=math.hypot(run,drop)
    angle=math.degrees(math.atan2(drop,run))
    shapes=[dict(shape='box',size_m=[length,.04,.56],
        at_m=[side*(width+.14)/4,0,0],turn_deg=[0,0,side*angle]) for side in (-1,1)]
    # A rear crossbar makes the two sloping faces one connected fixture.
    # It is behind the marble lane rather than filling the outlet hole.
    shapes.append(dict(shape='box',size_m=[width,.04,.04],at_m=[0,drop/2,-.26]))
    return {'parts':[dict(name=name+' funnel',shape='compound',material='oak',fixed=True,
        at_m=[x,y,PLANE],parts=shapes),mount(name+' bracket',x-width/3,y,.02)]}


def cup(name,k,ctx):
    x,y=k['x_m'],k['height_m'];width=k.get('width_m',.6)
    return {'parts':[dict(name=name+' cup',shape='compound',material='oak',fixed=True,
        at_m=[x,y,PLANE],parts=[dict(shape='box',size_m=[width,.04,.56],at_m=[0,0,0])]+
        [dict(shape='box',size_m=[.04,.36,.56],at_m=[side*(width-.04)/2,.16,0]) for side in (-1,1)]),
        mount(name+' bracket',x,y,.02)]}


def peg(name,k,ctx):
    x,y=k['x_m'],k['height_m']; diameter=k.get('diameter_m',.16)
    return {'parts':[dict(name=name+' peg',shape='compound',material=k.get('material','oak'),
        fixed=True,at_m=[x,y,PLANE],parts=[dict(shape='cylinder',size_m=[diameter,.24,diameter],
        at_m=[0,0,0],turn_deg=[90,0,0])]),mount(name+' bracket',x,y,PLANE-.12)]}


def lever(name,k,ctx):
    x,y=k['x_m'],k['height_m'];length=k.get('length_m',.7)
    initial=k.get('angle_deg',0)
    return {'parts':[mount(name+' bracket',x,y,PLANE-.14),
        dict(name=name+' lever',shape='compound',material='oak',at_m=[x,y,PLANE],
             turn_deg=[0,0,initial],parts=[dict(shape='box',
             size_m=[length,.04,.24],at_m=[0,0,0])])],
        'joints':[dict(name=name+' axle',kind='hinge',a=name+' bracket',b=name+' lever',
            at_m=[x,y,PLANE],axis=[0,0,1],lower_deg=-35-initial,upper_deg=35-initial,friction_n_m=.001)]}


def marble(name,k,ctx):
    d=k.get('diameter_m',.08)
    return {'parts':[dict(name=name,shape='sphere',material=k.get('material','glass'),
        size_m=[d]*3,at_m=[k['x_m'],k['height_m'],PLANE])]}


def gear(name,k,ctx):
    result=sm.gear(name,dict(k,z_m=PLANE),ctx)
    result['parts'][0]=mount(name+' post',k['x_m'],k['height_m'],PLANE-.04)
    return result


def motor(name,k,ctx):
    result=gear(name,k,ctx)
    x,y=k['x_m'],k['height_m']
    # Surface jacks above the rotor's swept disk; fixed rear housing takes
    # reaction torque. Electrical torque uses the existing native DC model.
    radius=k.get('teeth',12)*k.get('module_m',.024)/2+.02
    part=name+' housing'; jy=y+radius+.12
    result['parts'] += [sm.box(part,[.2,.12,.14],[x,jy,.10],'concrete'),
                         mount(name+' housing mount',x,jy,.03)]
    result['electrical']={'devices':[dict(name=name,kind='motor',part=part,
        terminals={key:[x+side*.07,jy,.175] for key,side in [('plus',-1),('minus',1)]},
        terminal_normals={'plus':[0,0,1],'minus':[0,0,1]},hinge=name+' axle',
        stall_torque_n_m=.08,no_load_rad_s=8,command=k.get('throttle',1),
        brake_torque_n_m=0,gear_ratio=1)]}
    return result


def wire(name,k,ctx):
    result=se.wire(name,k,ctx)
    result['electrical']['wires'][0]['mechanical']=dict(construction_plane='xy')
    return result


def lift(name,k,ctx):
    """One electrically driven, limited-travel carrier with an open cradle.

    Rotation, retention and unloading are ordinary hinge/contact/gravity.
    The rear rotor leaves a separate depth lane for the cantilevered chute.
    A physical stop prevents the carrier swinging into its own outlet.
    """
    x,y=k['x_m'],k['height_m'];r=k.get('radius_m',.4)
    u=r/math.sqrt(2); z=PLANE
    pocket=[dict(shape='box',size_m=[.20,.025,.18],at_m=[-u,-u-.06,0]),
        *[dict(shape='box',size_m=[.025,.14,.18],at_m=[-u+side*.10,-u,0]) for side in (-1,1)],
        dict(shape='box',size_m=[.20,.14,.02],at_m=[-u,-u,-.10]),
        *[dict(shape='box',size_m=[.20,.02,.02],at_m=[-u,-u+dy,.10]) for dy in (-.0375,.0325)],
        *[dict(shape='box',size_m=[.012,.14,.02],at_m=[-u+side*.094,-u,.10]) for side in (-1,1)]]
    shapes=[dict(shape='cylinder',size_m=[2*r,.018,2*r],at_m=[0,0,-.20],turn_deg=[90,0,0]),
        dict(shape='box',size_m=[.035,.035,.20],at_m=[-u,-u,-.10])]+pocket
    # Counterweight stock is sized from the cradle's oak volume. It balances
    # the apparatus; the source still supplies the marble's gravitational work.
    volume=sum(math.prod(p['size_m']) for p in pocket)
    shapes.append(dict(shape='box',size_m=[.16,.16,volume/(.16*.16)],at_m=[u,u,-.20]))
    rotor=dict(name=name+' wheel',shape='compound',material='oak',at_m=[x,y,z],parts=shapes)
    # Inside the swept rim at the left; leaves at the right below the final
    # raised cradle. Front lane clears the rear disk and counterweight.
    start=-.16;end=r+.55;drop=.12;length=math.hypot(end-start,drop)
    slope=-math.degrees(math.atan2(drop,end-start));cx=(start+end)/2
    chute=dict(name=name+' outlet',shape='compound',material='oak',fixed=True,
        at_m=[x+cx,y+.14-drop/2,z],turn_deg=[0,0,slope],parts=[
            dict(shape='box',size_m=[length,.025,.18],at_m=[0,0,0]),
            dict(shape='box',size_m=[length,.12,.02],at_m=[0,.05,-.10]),
            *[dict(shape='box',size_m=[length,.02,.02],at_m=[0,dy,.10]) for dy in (.02,.09)],
            *[dict(shape='box',size_m=[.012,.12,.02],at_m=[side*(length/2-.006),.05,.10]) for side in (-1,1)]])
    if k.get('end_stop','closed')=='closed':
        chute['parts'].append(dict(shape='box',size_m=[.025,.12,.18],at_m=[length/2-.0125,.05,0]))
    hx=x-r-.32;hy=y+.18
    housing=sm.box(name+' housing',[.18,.14,.14],[hx,hy,.10],'concrete')
    return dict(parts=[sm.box(name+' axle bracket',[.04,.04,.08],[x,y,.04],'iron'),rotor,chute,
        sm.box(name+' outlet bracket',[.04,.04,.21],[x+end-.08,y+.03,.105],'iron'),housing,
        mount(name+' housing bracket',hx,hy,.03)],
        joints=[dict(name=name+' axle',kind='hinge',a=name+' axle bracket',b=name+' wheel',
            at_m=[x,y,.10],axis=[0,0,1],lower_deg=-180,upper_deg=0,friction_n_m=.002),
            dict(name=name+' outlet mounting',kind='fix',a=name+' outlet bracket',b=name+' outlet',
                at_m=[x+end-.08,y+.03,.21])],
        electrical=dict(devices=[dict(name=name,kind='motor',part=housing['name'],
            terminals={key:[hx+side*.055,hy,.175] for key,side in [('plus',-1),('minus',1)]},
            terminal_normals={'plus':[0,0,1],'minus':[0,0,1]},hinge=name+' axle',
            stall_torque_n_m=6,no_load_rad_s=.9,command=-k.get('throttle',1),
            brake_torque_n_m=0,gear_ratio=1)]))


def electrical(builder):
    def build(name,k,ctx):
        # Native declarations retain actual terminal positions, contact pads,
        # handle points and joint anchors when lifted onto the board.
        result=builder(name,dict(k,z_m=PLANE,height_m=.24),ctx)
        dy=k['height_m']-.08
        rows=[p for key,value in result.items() if isinstance(value,list) for p in value]
        rows += result.get('electrical',{}).get('devices',[])
        mw.shift_rows([0,dy,0],rows)
        for device in result.get('electrical',{}).get('devices',[]):
            for key,at in device.get('terminals',{}).items():
                device['terminals'][key]=[at[0],at[1]+dy,at[2]]
            if device.get('handle'):
                mw.shift_rows([0,dy,0],[device['handle']])
        for p in list(result.get('parts',[]))[:1]:
            if p.get('fixed'):
                depth=p.get('size_m',[.1,.1,.16])[2]
                result['parts'].append(mount(p['name']+' bracket',p['at_m'][0],p['at_m'][1],p['at_m'][2]-depth/2))
        return result
    return build


def mounted(builder):
    def build(name,k,ctx):
        result=builder(name,k,ctx)
        fixed=[p for p in result.get('parts',[]) if p.get('fixed') and p['shape']=='compound'
               and not any(j.get('kind')=='fix' and j.get('b')==p['name'] for j in result.get('joints',[]))]
        if fixed:
            # Precise compound input currently has no anchored-body flag.
            # Pin it through the native fixed-joint law to a physical bracket;
            # never freeze its pose in playback or assign compensating forces.
            anchor=name+' wall bolts'
            result['parts'].append(sm.box(anchor,[.04,.04,.04],[k['x_m'],k['height_m'],.02],'iron'))
            for p in fixed:
                result.setdefault('joints',[]).append(dict(name=p['name']+' mounting',kind='fix',
                    a=anchor,b=p['name'],at_m=p['at_m']))
        return result
    return build


PIECES=dict(wall_track=track,wall_funnel=funnel,wall_cup=cup,wall_peg=peg,
    wall_lever=lever,wall_lift=lift,marble=marble,gear=gear,motor=motor,wire=wire,
    **{key:electrical(getattr(se,key)) for key in ('battery','switch','bulb','resistor','capacitor')})
PIECES={key:mounted(builder) for key,builder in PIECES.items()}

# Explicit names distinguish a wall-mounted battery/gear from the same
# ordinary device on the floor. Legacy v1 records retain their builders.
WORLD_ALIASES={key:'wall_'+key for key in ('marble','gear','motor','battery','switch','bulb','resistor','capacitor')}
WORLD_PIECES={WORLD_ALIASES.get(key,key):builder for key,builder in PIECES.items() if key!='wire'}


def world_tray(ordinary,base_spec=None):
    boards=panels(base_spec or {})
    result=[]
    for row in tray():
        if row['piece']=='wire':continue
        original=row['piece'];row['piece']=WORLD_ALIASES.get(original,original)
        row['wall_mounted']=True
        row['open_world']=True
        row['knobs']['wall']=dict(choices=[p['id'] for p in boards],default=boards[0]['id'],hidden=True)
        row['knobs']['x_m'].update(min=-22,max=22)
        row['knobs']['height_m'].update(max=10)
        if original in WORLD_ALIASES and 'wall' not in row['title'].lower().split():
            row['title']='Wall '+row['title'].lower()
        result.append(row)
    normal=copy.deepcopy(ordinary)
    for row in normal:
        for key in ('x_m','z_m'):
            rule=row['knobs'].get(key)
            if rule and 'min' in rule:rule.update(min=-10,max=10)
        for key in ('top_height_m','pivot_height_m','bore_height_m','drop_from_m','foot_height_m','center_height_m'):
            rule=row['knobs'].get(key)
            if rule and 'max' in rule:rule['max']=max(rule['max'],4.5)
    next(row for row in normal if row['piece']=='track')['knobs']['width_m']=sm.number('Track width (m)',.08,.56,.18,.02)
    # Keep the workshop's compact stock for nearby wall sockets. Stock length
    # remains editable for connections out into the surrounding world.
    next(row for row in normal if row['piece']=='wire')['knobs']['length_m']['default']=2
    return result+normal


def world_draft(base_spec,placements,goal=None):
    """Explicit editable-copy conversion; never mutate a shared snapshot."""
    if not validate(base_spec):raise ValueError('Choose an existing wall design to open into the 3D world.')
    if base_spec['build_surface']['version']==2:
        return dict(base=copy.deepcopy(base_spec),placements=copy.deepcopy(placements),**({'goal':copy.deepcopy(goal)} if goal else {}))
    renamed={f'your {p["piece"]} {i+1}':f'your {WORLD_ALIASES.get(p["piece"],p["piece"])} {i+1}' for i,p in enumerate(placements)}
    def references(value):
        if isinstance(value,dict):return {key:references(item) for key,item in value.items()}
        if isinstance(value,list):return [references(item) for item in value]
        if isinstance(value,str):
            return re.sub(r'^your \S+ \d+(?=\b|:)',lambda match:renamed.get(match[0],match[0]),value)
        return value
    rows=references(copy.deepcopy(placements))
    for row in rows:row['piece']=WORLD_ALIASES.get(row['piece'],row['piece'])
    foundation=references(copy.deepcopy(base_spec))
    foundation['parts']=[p for p in foundation['parts'] if p['name']!=FOUNDATION[1]]
    foundation['joints']=[j for j in foundation.get('joints',[]) if j.get('name')!='workshop guard mounting']
    foundation.update(build_surface=world_surface(),presentation=dict(camera='wall_world'))
    result=dict(base=foundation,placements=rows)
    if goal:
        result['goal']=references(copy.deepcopy(goal))
        zone=result['goal'].get('done_when',{}).get('in_zone',{})
        if zone.get('piece') in WORLD_ALIASES:zone['piece']=WORLD_ALIASES[zone['piece']]
    return result


def world_template(ordinary):
    source=template();draft=world_draft(source['base'],source['placements'])
    draft['placements']=draft['placements'][:4]+[
        dict(piece='track',x_m=.55,z_m=.15,top_height_m=1.05,run_m=1.6,drop_m=.60,yaw_deg=-90,width_m=.56,end='stop')]
    return dict(name='Wall in the world',description='Snap mounted pieces onto a wall, then build outward with the full 3D library.',
                **draft,tray=world_tray(ordinary))


def world_lift_assembly(x=0,y=1.6,offset=0):
    rows,check=lift_assembly(x,y,offset)
    def rename(value):
        if isinstance(value,dict):return {key:rename(item) for key,item in value.items()}
        if isinstance(value,list):return [rename(item) for item in value]
        if isinstance(value,str):return re.sub(r'^your (marble|gear|motor|battery|switch|bulb|resistor|capacitor)(?= \d+)',lambda m:'your '+WORLD_ALIASES[m[1]],value)
        return value
    rows=rename(rows)
    for row in rows:row['piece']=WORLD_ALIASES.get(row['piece'],row['piece'])
    return rows,rename(check)


def tray():
    names=dict(wall_track='Wall track',wall_funnel='Wall funnel',wall_cup='Catching cup',
        wall_peg='Deflector peg',wall_lever='Wall seesaw',marble='Marble',gear='Wall gear',
        wall_lift='Marble lift wheel',
        motor='Powered wall gear',battery='Battery',switch='Switch',bulb='Light bulb',
        wire='Wire',resistor='Resistor',capacitor='Capacitor')
    knobs=dict(
        wall_track=dict(length_m=sm.number('Track length (m)',.3,2,1.4),angle_deg=sm.number('Slope (°)',-70,70,-16,1),
            end_stop=sm.choice('High-end stop',['closed','open'],'closed')),
        wall_funnel=dict(width_m=sm.number('Funnel width (m)',.3,1.4,.7)),
        wall_cup=dict(width_m=sm.number('Cup width (m)',.2,1.2,.6)),
        wall_peg=dict(diameter_m=sm.number('Peg diameter (m)',.08,.4,.16)),
        wall_lever=dict(length_m=sm.number('Seesaw length (m)',.3,1.2,.7),angle_deg=sm.number('Starting tilt (°)',-30,30,0,1)),
        wall_lift=dict(radius_m=sm.number('Lift radius (m)',.35,.55,.4,.025),
            throttle=sm.number('Motor power',0,1,1,.1),
            end_stop=sm.choice('Outlet stop',['closed','open'],'closed')),
        marble=dict(diameter_m=sm.choice('Diameter (m)',[.06,.08,.1],.08),material=sm.choice('Material',['glass','oak','iron'],'glass')),
        gear=dict(teeth=sm.number('Teeth',6,32,12,1),module_m=sm.number('Tooth size (m)',.012,.04,.024,.002),
            phase_deg=sm.number('Tooth alignment (°)',-180,180,0,1)),
        motor=dict(teeth=sm.number('Teeth',6,32,12,1),module_m=sm.number('Tooth size (m)',.012,.04,.024,.002),
            phase_deg=sm.number('Tooth alignment (°)',-180,180,0,1),throttle=sm.number('Motor power',-1,1,1,.1)))
    original={row['piece']:copy.deepcopy(row) for row in se.TRAY}
    result=[]
    for piece,title in names.items():
        if piece in knobs:
            row=dict(piece=piece,title=title,knobs=knobs[piece])
        else:
            row=original[piece];row['title']=title
            # Wall mounting replaces ground coordinates and selectable remote
            # fixtures; the same electrical ratings and wiring remain.
            for key in ('x_m','z_m','height_m','mount','hinge'):
                row['knobs'].pop(key,None)
            if piece=='switch':
                row['knobs']['mode']=dict(choices=['manual','paddle'],default='paddle',label='Switch handle')
        if piece!='wire':
            row['knobs'].update(x_m=sm.number('Left / right (m)',-2.8,2.8,0),
                height_m=sm.number('Height (m)',.1,3.9,2))
        if piece=='marble':
            row['knobs']['placement']=dict(choices=['at height'],default='at height',hidden=True)
        if piece=='wire':row['knobs']['length_m']['default']=2
        for key,rule in row['knobs'].items():
            if key in ('angle_deg','phase_deg'):rule['turning']=True
        row.update(across=False,turning=False,sandbox_builder=True,cost=0,count=30)
        if piece=='gear':row['primary_knobs']=['teeth','module_m','height_m']
        result.append(row)
    return result


def template():
    return dict(name='Wall workshop',description='Build a marble machine by dragging mounted pieces left, right, up and down.',
        base=base(),placements=[
            dict(piece='marble',x_m=-1.9,height_m=3.6),
            dict(piece='wall_track',x_m=-1.15,height_m=3.15,length_m=1.9,angle_deg=-16),
            dict(piece='wall_track',x_m=.40,height_m=2.45,length_m=1.6,angle_deg=16),
            dict(piece='wall_track',x_m=-.70,height_m=1.65,length_m=1.9,angle_deg=-16),
            dict(piece='wall_cup',x_m=.85,height_m=.75,width_m=.8)],tray=tray())


def lift_assembly(x=0,y=1.6,offset=0):
    """Reusable apparatus, expanded into normal editable placements and wires.

    This declares geometry/connections only. The caller must rehearse the
    resulting scene before reporting that the marble was actually lifted.
    """
    lift_name=f'your wall_lift {offset+1}'
    battery_name=f'your battery {offset+3}'
    rows=[dict(piece='wall_lift',x_m=x,height_m=y),
        dict(piece='marble',diameter_m=.06,material='glass',x_m=x-.4/math.sqrt(2),
             height_m=y-.4/math.sqrt(2)+.14),
        dict(piece='battery',x_m=x-1.3,height_m=y-.4),
        dict(piece='wire',a_terminal=battery_name+':plus',b_terminal=lift_name+':plus',length_m=2),
        dict(piece='wire',a_terminal=battery_name+':minus',b_terminal=lift_name+':minus',length_m=2)]
    check=dict(marble=f'your marble {offset+2}',carrier=lift_name+' wheel',outlet=lift_name+' outlet',
        initial_height_m=rows[1]['height_m'])
    return rows,check
