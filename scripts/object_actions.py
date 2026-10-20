"""Named operator inputs attached to physical handles, shared by editor and LLM.

An action supplies bounded hand force. It never sets a pose, switch state or
motor output. An adapter is saved as an ordinary, reference-aware tray entry.
"""
import copy
import math
import machine_world as mw

KEYS=('', 'Space', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'KeyA', 'KeyD', 'KeyW', 'KeyS', 'KeyE', 'KeyQ')
LOCATIONS=('auto','object','near','surface','dock')
MODES=('hold','turn')
TEMPLATES=[]


def hold(name, part, force, label, key='', replaces='', location='dock', mode='hold'):
    row=dict(name=name,part=part,force_n=list(force),label=label,key=key,location=location,mode=mode)
    if replaces:row['replaces']=replaces
    return dict(player_controls=[row])


def binding(name,k,ctx):
    part=next((p for p in ctx['parts'] if p['name']==k.get('part')),None)
    if not part:raise mw.MachineRefused(['Choose an existing moving handle for this action'])
    local=[k.get('push_x_n',0),k.get('push_y_n',-30),k.get('push_z_n',0)]
    force=mw._mat_apply(mw.rotation(part.get('turn_deg',[0,0,0])),local)
    existing=next((c for c in ctx['spec'].get('player_controls',[]) if c.get('part')==part['name'] and not c.get('replaces')),None)
    return hold(name,part['name'],force,k.get('label','Press handle'),k.get('key',''),existing['name'] if existing else '',k.get('location','auto'),k.get('mode','hold'))


PIECES={'object_action':binding}
TRAY=[dict(piece='object_action',title='Object action',description='A held button applies hand force to a real hinged or sliding handle; use Design → Object actions.',
    count=12,cost=0,logical=True,turning=False,across=False,
    knobs=dict(part=dict(default='',part=True,label='Moving handle'),
        label=dict(default='Press handle',text_max=60,label='Button label'),
        key=dict(default='',choices=list(KEYS),label='Keyboard shortcut'),
        location=dict(default='auto',choices=list(LOCATIONS),label='Button location'),
        mode=dict(default='hold',choices=list(MODES),label='Hold button or turning handle'),
        **{f'push_{axis}_n':dict(default=-30 if axis=='y' else 0,min=-120,max=120,step=1,
            label=f'Push {axis.upper()} (N, handle axes)') for axis in 'xyz'}))]


def targets(compiled):
    moving={j['b'] for j in compiled['joints'] if j['kind'] in ('hinge','slide')}
    result=[]
    for p in compiled['parts']:
        if p['fixed'] or p['name'] not in moving:continue
        control=next((c for c in compiled.get('player_controls',[]) if c['part']==p['name']),None)
        local=[0,-30,0]
        if control:
            matrix=mw.rotation(p.get('turn_deg',[0,0,0]))
            local=[sum(matrix[j][i]*control['force_n'][j] for j in range(3)) for i in range(3)]
        result.append(dict(part=p['name'],control=copy.deepcopy(control),
            force_local_n=[round(v,6) for v in local]))
    return result


def configure(level,placements,part,label,key,force,location='auto',mode='hold'):
    """Validate the same catalog adapter used by add/edit in the word builder."""
    import machine_game as mg
    if not level.get('free'):raise ValueError('Create object actions in the Sandbox')
    if not isinstance(force,list) or len(force)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in force):
        raise ValueError('Choose a finite three-axis hand force')
    checked,_=mg.check_placements(level,placements)
    proposed=[{k:v for k,v in p.items() if k!='cost'} for p in checked]
    row=dict(piece='object_action',part=part,label=label,key=key,location=location,mode=mode,
        **{f'push_{axis}_n':force[i] for i,axis in enumerate('xyz')})
    index=next((i for i,p in enumerate(proposed) if p['piece']=='object_action' and p.get('part')==part),None)
    if index is None:proposed.append(row)
    else:proposed[index]=row
    _,checked,_=mg.compose(level,proposed)
    return [{k:v for k,v in p.items() if k!='cost'} for p in checked]
