"""Ten authored construction lessons, using the workshop's qualified mechanisms.

Only assessment geometry and native measurement stations differ between lessons.
Player actions apply bounded forces through the ordinary live controls.
"""
import copy
import math
from functools import lru_cache

import machine_world as mw
import sandbox_pinball as p
from object_actions import hold

IDS=[f'pinball-{i:02d}' for i in range(1,11)]
CHAPTER='Project: Build a Pinball Machine'
# The complete table's run work varies slightly between Windows/Linux contact
# trajectories. Round its measured 12.592 MJ reference upward to three figures,
# as the energy benchmark specifies; goal geometry/time and its 1% test stay fixed.
PAR_ENERGY_J={1: 12592000, 2: 41932800, 3: 290608835, 4: 34944035, 5: 451551550, 6: 728980006, 7: 33.6, 8: 451551718, 9: 384912000, 10: 12600000}


def point(x,y,z):
    a=math.radians(p.SLOPE)
    return [x,p.HEIGHT+y*math.cos(a)+z*math.sin(a),-y*math.sin(a)+z*math.cos(a)]


def zone(part,x,z,width=.25,length=.25,y=.06,height=.18):
    return dict(in_zone=dict(part=part,at_m=point(x,y,z),size_m=[width,height,length]))


def span(joint,low,high):
    return dict(joints_in_range=[dict(joint=joint,min_deg=low,max_deg=high)])


def _tray(piece,start,keys,**stock):
    import machine_game as mg
    row=copy.deepcopy(next(t for t in mg.free_build()['tray'] if t['piece']==piece))
    row.update(count=1,cost=0,turning=False,start_at_defaults=True)
    row['across']='z_m' in row['knobs']
    if row['knobs'].get('angle_deg',{}).get('turning'):row['turns']=['angle_deg']
    for key,rule in row['knobs'].items():
        if key not in keys:rule['hidden']=True
    for key,value in dict(x_m=start[0],z_m=start[1],**stock).items():
        if key not in row['knobs']:continue
        rule=row['knobs'][key];rule['default']=value
        if key not in keys:
            if 'choices' in rule:rule['choices']=[value]
            else:rule.update(min=value,max=value)
    return row


def _merge(spec,fragment):
    import machine_game as mg
    mg.merge_fragment(spec,fragment)


def mount(spec):
    """Explicit ideal mountings react against the grounded table frame.

    These are rigid fixture constraints, not a resolved screw/thread model.
    The ball and all hinged/sliding members remain free to move.
    """
    saved=spec.setdefault('presentation',{}).setdefault('assembly_mounts',[])
    for j in spec['joints']:
        if j['kind']=='fix' and j['a']=='pinball table frame' and j['name'].endswith(' table mounting') and j['name'] not in saved:
            saved.append(j['name'])
    attached={'pinball table frame'}
    changed=True
    while changed:
        changed=False
        for j in spec['joints']:
            if j['kind']=='fix' and (j['a'] in attached or j['b'] in attached):
                old=len(attached);attached.update((j['a'],j['b']));changed|=len(attached)!=old
    for part in spec['parts']:
        if part.get('fixed') and part['name'] not in attached:
            spec['joints'].append(dict(name=part['name']+' table mounting',kind='fix',
                a='pinball table frame',b=part['name'],at_m=list(part['at_m'])))
            spec.setdefault('presentation',{}).setdefault('assembly_mounts',[]).append(part['name']+' table mounting')
            attached.add(part['name'])


def _fixture(spec,build,name,**knobs):
    _merge(spec,build(name,knobs,{}))


def return_gutter(spec):
    """A real two-sided drain collector below the front of the playfield.

    It catches a ball leaving either side lane and rolls it to the centre
    opening. This collects the ball; it is not an automatic elevator/reset.
    """
    for side in (-1,1):
        q=p.rigid(f'ball return slope {side}',[side*.4,.35,-1.57],[.8,.03,.56],
            'iron',turn=[0,0,side*25]);q['color_rgba']=0x40b77aff
        spec['parts'].append(q)
    for name,at,size in [('front',[0,.46,-1.87],[1.7,.36,.04]),
                          ('back',[0,.46,-1.27],[1.7,.36,.04]),
                          ('left',[-.83,.46,-1.57],[.04,.36,.56]),
                          ('right',[.83,.46,-1.57],[.04,.36,.56])]:
        spec['parts'].append(p.rigid('ball return '+name,at,size,'iron'))


def _base(title,stage):
    full=p.template()['base']
    owners=['pinball table']
    if stage>=3:owners+=['launch lane']
    if stage>=4:owners+=['launch turn']
    if stage>=5:owners+=['left inlane guide','right inlane guide']
    if stage>=7:owners+=['launcher']
    if stage>=7:owners+=['left flipper','left button','pinball supply']
    if stage>=9:owners+=['right flipper','right button']
    def owned(name):return any(name==n or name.startswith(n+' ') for n in owners)
    spec=copy.deepcopy(full)
    spec.update(title=title,stations=[])
    spec['parts']=[q for q in spec['parts'] if owned(q['name'])]
    if stage==1:spec['parts']=[q for q in spec['parts'] if not q['name'].endswith('glass cover')]
    names={q['name'] for q in spec['parts']}
    spec['joints']=[j for j in spec['joints'] if j['a'] in names and j['b'] in names]
    spec['electrical']['devices']=[d for d in spec['electrical']['devices'] if d['part'] in names]
    devices={d['name'] for d in spec['electrical']['devices']}
    spec['electrical']['wires']=[w for w in spec['electrical']['wires'] if all(w[k].rsplit(':',1)[0] in devices for k in ('a','b'))]
    spec['player_controls']=[c for c in spec['player_controls'] if c['part'] in names]
    spec['batteries']=[b for b in spec['batteries'] if b['in'] in names]
    return spec


def project_build(records,step):
    """Export editable physical assemblies, retaining the player's adjustments.

    Lessons remain independent practice rigs. The saved table accumulates the
    taught subsystems; assessment catchers and targets never enter the build.
    """
    import machine_game as mg
    if type(step) is not int or not 1<=step<=10 or not isinstance(records,dict):
        raise ValueError('Choose a Pinball project step from 1 to 10')
    lessons={row['id']:row for row in mg.load_levels() if row.get('project')}
    settings={}
    for identity,placed in records.items():
        if identity not in IDS or IDS.index(identity)>=step:continue
        checked,_=mg.check_placements(lessons[identity],placed)
        checked=[{k:v for k,v in q.items() if k!='cost'} for q in checked]
        mg.compose(lessons[identity],checked)
        settings[IDS.index(identity)+1]=checked
    full=p.template()['base'];spec=copy.deepcopy(full)
    owners=['pinball table']
    if step>=2:owners+=['left inlane guide']
    if step>=3:owners+=['launch lane','launcher']
    if step>=4:owners+=['launch turn']
    if step>=5:owners+=['left flipper']
    if step>=6:owners+=['left button','pinball supply']
    if step>=8:owners+=['right flipper','right button']
    if step>=9:owners+=['upper bumper','left target']
    def owned(name):return any(name==n or name.startswith(n+' ') for n in owners)
    spec['parts']=[q for q in spec['parts'] if owned(q['name'])]
    if step==1:spec['parts']=[q for q in spec['parts'] if not q['name'].endswith('glass cover')]
    names={q['name'] for q in spec['parts']}
    spec['joints']=[j for j in spec['joints'] if j['a'] in names and j['b'] in names]
    spec['player_controls']=[c for c in spec['player_controls'] if c['part'] in names]
    spec['electrical']['devices']=[d for d in spec['electrical']['devices'] if d['part'] in names and (step>=7 or d['kind']!='motor')]
    devices={d['name'] for d in spec['electrical']['devices']}
    spec['electrical']['wires']=[w for w in spec['electrical']['wires'] if all(w[k].rsplit(':',1)[0] in devices for k in ('a','b'))]
    spec['batteries']=[b for b in spec['batteries'] if b['in'] in names]
    spec['stations']=[];spec['title']='My Pinball project'
    spec.setdefault('presentation',{})['pinball_project_step']=step
    # Compile each actual winning assembly and rename its stable ownership.
    for n,owner in [(2,'left inlane guide'),(4,'launch turn'),(5,'left flipper'),(6,'left button'),(8,'right flipper'),(9,'upper bumper')]:
        if n not in settings:continue
        lesson=lessons[IDS[n-1]];placed=settings[n]
        built=mg.compose(lesson,placed)[0]
        prefix=f'your {placed[0]["piece"]} 1'
        if n==5:
            built=p.flipper(prefix,placed[0],{})
            if step<7:built['electrical']['devices']=[]
        def rename(value):
            if isinstance(value,str) and (value==prefix or value.startswith(prefix+' ') or value.startswith(prefix+':')):return owner+value[len(prefix):]
            if isinstance(value,list):return [rename(v) for v in value]
            if isinstance(value,dict):return {k:rename(v) for k,v in value.items()}
            return copy.deepcopy(value)
        def belongs(name):return name==owner or name.startswith(owner+' ')
        for key in ('parts','joints','player_controls'):
            old=[q for q in spec.get(key,[]) if not belongs(q['name'])]
            replacement=[rename(q) for q in built.get(key,[]) if q['name']==prefix or q['name'].startswith(prefix+' ')]
            spec[key]=old+replacement
        spec['electrical']['devices']=[d for d in spec['electrical']['devices'] if d['name']!=owner]+[
            rename(d) for d in built.get('electrical',{}).get('devices',[]) if d['name']==prefix and (step>=7 or d['kind']!='motor')]
    if 3 in settings:
        # Preserve the actual launcher position, spring and held action.
        built=mg.compose(lessons[IDS[2]],settings[3])[0];prefix='your pinball_plunger 1'
        import json
        for key in ('parts','joints','player_controls'):
            spec[key]=[q for q in spec.get(key,[]) if not q['name'].startswith('launcher')]+[
                json.loads(json.dumps(q).replace(prefix,'launcher')) for q in built.get(key,[]) if q['name']==prefix or q['name'].startswith(prefix+' ')]
    if step in (5,6) and 5 in settings:
        rig=mg.compose(lessons[IDS[4]],settings[5])[0]
        import json
        for key in ('parts','joints','player_controls'):
            for q in rig.get(key,[]):
                if q['name'].startswith('hand '):
                    q=json.loads(json.dumps(q).replace('your pinball_flipper 1','left flipper'))
                    if key=='player_controls':q['key']='KeyA'
                    spec.setdefault(key,[]).append(q)
    if step==6 and 6 in settings:
        rig=mg.compose(lessons[IDS[5]],settings[6])[0]
        import json
        spec['parts']+=copy.deepcopy([q for q in rig['parts'] if q['name']=='contact indicator'])
        spec['electrical']['devices']+=copy.deepcopy([d for d in rig['electrical']['devices'] if d['name']=='contact lamp'])
        spec['electrical']['wires']=[json.loads(json.dumps(w).replace('your pinball_button 1','left button')) for w in rig['electrical']['wires']]
    ball=settings.get(10,settings.get(1,[{}]))[0] if step==1 or step==10 else {}
    _fixture(spec,p.ball,'pinball',**{k:v for k,v in ball.items() if k!='piece'})
    # Wire paths follow any changed button position through the ordinary router.
    if 6 in settings and settings[6][0].get('x_m',.96)!=.96:
        for wire in spec['electrical']['wires']:wire.pop('mechanical',None)
    for c in spec['player_controls']:
        if c['name']=='left button':c.update(label='Left flipper',key='ArrowLeft')
        if c['name']=='launcher':c['key']='Space'
    if step==10:return_gutter(spec)
    mount(spec)
    mw.compile_spec(spec)
    return dict(base=spec,placements=[])


def _goal_target(spec,x,z,width=.3):
    """An inset catch box with an actual opening in the wooden playfield.

    Coordinates are local to the inclined deck. The original raised floor
    made a 25 mm step in front of a 40 mm marble; the new box is below it.
    Assessment geometry is excluded from the exported project.
    """
    opening=(x-width/2-.025,x+width/2+.025,z-.175,z+.15)
    frame=next(part for part in spec['parts'] if part['name']=='pinball table frame')
    deck=[]
    for part in frame['parts']:
        # Cut only the flat deck slabs; retain rails, guides and shaft holes.
        if part['shape']!='box' or part['at_m'][1]!=0 or part.get('turn_deg',[0,0,0])!=[0,0,0]:
            deck.append(part);continue
        px,py,pz=part['at_m'];sx,sy,sz=part['size_m']
        left,right=max(px-sx/2,opening[0]),min(px+sx/2,opening[1])
        back,front=max(pz-sz/2,opening[2]),min(pz+sz/2,opening[3])
        if left>=right or back>=front:deck.append(part);continue
        for a,b,c,d in [(px-sx/2,left,pz-sz/2,pz+sz/2),(right,px+sx/2,pz-sz/2,pz+sz/2),
                        (left,right,pz-sz/2,back),(left,right,front,pz+sz/2)]:
            if b-a>1e-8 and d-c>1e-8:
                deck.append(dict(part,at_m=[(a+b)/2,py,(c+d)/2],size_m=[b-a,sy,d-c]))
    frame['parts']=deck
    for suffix,at,size in [('floor',[x,-.08,z],[width,.02,.3]),
                            ('end',[x,-.03,z-.1625],[width+.05,.12,.025]),
                            ('left',[x-width/2-.0125,-.03,z],[.025,.12,.3]),
                            ('right',[x+width/2+.0125,-.03,z],[.025,.12,.3])]:
        fragment=p.finish(dict(parts=[p.rigid('lesson catcher '+suffix,at,size,'iron')]),{})
        fragment['parts'][0]['color_rgba']=0x40b77aff
        _merge(spec,fragment)


def _caught(part,x,z,width):
    # Count a marble inside the physical box, below the deck, moving slowly
    # for a continuous interval. Passing its front edge is not a catch.
    return dict(in_zone=dict(part=part,at_m=point(x,-.05,z),size_m=[width,.08,.3],
                             hold_s=.4,max_speed_m_s=.06))


def _lesson(i,title,brief,spec,tray,rule,focus,solution,wrong,controls,actions=None,steps=None,time_s=8):
    row=dict(id=IDS[i-1],title=title,brief=brief,difficulty='easy',teaches=brief.split('.')[0],
        time_s=time_s,budget=100,par=100,style_pieces=1,par_energy_j=PAR_ENERGY_J.get(i,1),machine=spec,tray=tray,
        goal=dict(title=title,focus=focus,station=dict(done_when=rule),checkpoints=steps or []),
        hints=[brief,'Place the highlighted part first. Select Run, then use the labelled held controls beside the table.'],
        project=dict(id='pinball',step=i,total=10),custom_base=True,solution=solution,wrong=wrong,
        solution_actions=actions or [],lesson_controls=controls,camera_min_m=4)
    if 'in_zone' in rule:row['goal']['area']={k:v for k,v in rule['in_zone'].items() if k!='part'}
    return row


def actions(name,start=.2,release=.7):
    # Refresh the ordinary one-second held-input lease during longer tests.
    rows=[dict(name=name,at_s=start,pressed=True),dict(name=name,at_s=release,pressed=False)]
    return rows


def levels():
    return copy.deepcopy(_levels())


@lru_cache(maxsize=1)
def _levels():
    rows=[]
    spec=_base('Let gravity play',1);_goal_target(spec,0,-.9,.45)
    rows.append(_lesson(1,'Let gravity play',
        'Place a marble uphill of the green catcher. Gravity rolls it down the tilted deck; it must drop into the recessed box and stay there.',
        spec,[_tray('pinball_ball',[-.5,.8],['x_m','z_m'])],_caught('your pinball_ball 1',0,-.9,.45),
        ['lesson catcher floor'],[dict(piece='pinball_ball',x_m=0,z_m=.8)],
        [dict(piece='pinball_ball',x_m=-.5,z_m=.8)],{'pinball_ball':['x_m','z_m']}))

    # Leave room beside the side wall so a rail on ordinary centimetre/grid
    # increments hits its face, rather than needing a sub-millimetre end fit.
    spec=_base('Keep it on the table',2);_fixture(spec,p.ball,'lesson ball',x_m=-.60,z_m=.5)
    _goal_target(spec,-.16,-.85,.4)
    rows.append(_lesson(2,'Keep it on the table',
        'Place a slanted guide across the left side lane. Steer the marble into the opening of the green catcher so it drops in and stays there. The clear guard keeps it on the table.',
        spec,[_tray('pinball_rail',[0,.2],['x_m','z_m','angle_deg'],length_m=.72)],
        _caught('lesson ball',-.16,-.85,.4),['lesson ball','lesson catcher floor'],
        [dict(piece='pinball_rail',x_m=-.5,z_m=-.15,angle_deg=55)],
        [dict(piece='pinball_rail',x_m=.2,z_m=.3,angle_deg=0)],{'pinball_rail':['x_m','z_m','angle_deg']}))

    spec=_base('Build the spring launch',3);_fixture(spec,p.ball,'lesson ball')
    rows.append(_lesson(3,'Build the spring launch',
        'Put the launcher behind the ball in the narrow right lane. In Run, hold Pull launcher to compress its spring, then release to send the ball to the upper green marker.',
        spec,[_tray('pinball_plunger',[.63,-1.32],['z_m'])],zone('lesson ball',.63,.8,.16,.35),
        ['lesson ball'],[dict(piece='pinball_plunger',z_m=-1.2)],
        [dict(piece='pinball_plunger',z_m=-1.5)],{'pinball_plunger':['z_m']},actions('your pinball_plunger 1'),time_s=8))

    spec=_base('Guide the return',3);_fixture(spec,p.ball,'lesson ball');_fixture(spec,p.plunger,'launcher')
    rows.append(_lesson(4,'Guide the return',
        'Place the diagonal turn at the top of the launch lane. Run, pull and release the launcher: your rail must redirect the rising ball toward the middle of the table.',
        spec,[_tray('pinball_rail',[.2,.6],['x_m','z_m','angle_deg'],length_m=.6)],
        zone('lesson ball',.15,.65,.6,.6),['lesson ball'],
        [dict(piece='pinball_rail',x_m=.43,z_m=.9,angle_deg=30)],
        [dict(piece='pinball_rail',x_m=-.4,z_m=.7,angle_deg=0)],{'pinball_rail':['x_m','z_m','angle_deg']},
        actions('launcher'),steps=[dict(title='Hit the launch turn',done_when=dict(touches=['lesson ball','your pinball_rail 1']))],time_s=12))

    spec=_base('Make a returning paddle',5)
    rows.append(_lesson(5,'Make a returning paddle',
        'Add the paddle at its bearing. In Run, hold Lift paddle, then let go. Your hand supplies the first stroke; its return spring must bring it back. No battery powers this lesson.',
        spec,[_tray('pinball_flipper',[.43,-.76],['return_n_m'],side='right')],
        span('your pinball_flipper 1 axle',-4,4),['your pinball_flipper 1 paddle'],
        [dict(piece='pinball_flipper',return_n_m=35)],
        [dict(piece='pinball_flipper',return_n_m=35)],{'pinball_flipper':['return_n_m']},
        actions('hand paddle',.2,.7),steps=[dict(title='Lift the paddle',done_when=dict(hinge_beyond_deg=dict(joint='your pinball_flipper 1 axle',deg=40)))],time_s=5))

    spec=_base('Close a real contact',6)
    # Copy the finite supply without bringing a powered paddle into this lesson.
    full=p.template()['base']
    for key in ('parts','batteries'):
        spec[key].extend(copy.deepcopy([q for q in full[key] if q.get('name','').startswith('pinball supply') or q.get('name')=='pinball battery']))
    spec['electrical']['devices'].append(copy.deepcopy(next(d for d in full['electrical']['devices'] if d['name']=='pinball supply')))
    lamp=p.finish(dict(parts=[p.rigid('contact indicator',[-1.15,.30,.6],[.12,.12,.12],'glass')],
        electrical=dict(devices=[dict(name='contact lamp',kind='bulb',part='contact indicator',resistance_ohm=48,
            rated_voltage_v=24,watts=12,terminals={'plus':[-1.23,.3,.57],'minus':[-1.23,.3,.63]})])),{})
    _merge(spec,lamp)
    rows.append(_lesson(6,'Close a real contact',
        'Add the spring-return button. In Run, hold Press button until the indicator lights, then release it. The metal contacts must separate and turn the lamp off again.',
        spec,[_tray('pinball_button',[.96,-.85],['x_m'])],
        dict(load_power_below_w=dict(device='contact lamp',at_least_w=.1,for_s=.2)),['contact indicator'],
        [dict(piece='pinball_button',x_m=.96)],[dict(piece='pinball_button',x_m=.96)],{'pinball_button':['x_m']},
        actions('your pinball_button 1',.2,.7),steps=[dict(title='Light the indicator',done_when=dict(load_power_w=dict(device='contact lamp',at_least_w=5,for_s=.15)))],time_s=5))

    spec=_base('Power the first flipper',7)
    # Draw the missing RETURN lead. There is no invisible shared ground.
    spec['electrical']['wires']=[w for w in spec['electrical']['wires'] if w['a']!='left flipper:minus']
    _fixture(spec,p.ball,'lesson ball',x_m=.10,z_m=-.78)
    stock=next(w['length_m'] for w in p.template()['base']['electrical']['wires'] if w['a']=='left flipper:minus')
    lead=_tray('wire',[0,0],['a_terminal','b_terminal'],size='low resistance',length_m=stock)
    lead['knobs'].pop('x_m',None);lead['knobs'].pop('z_m',None)
    rows.append(_lesson(7,'Power the first flipper',
        'Click the flipper’s minus socket, then the supply’s minus socket to draw its return wire. Run and hold Left flipper to strike the ball toward the green marker. Both leads are required.',
        spec,[lead],zone('lesson ball',.10,-.40,.65,.4),['lesson ball'],
        [dict(piece='wire',a_terminal='left flipper:minus',b_terminal='pinball supply:minus')],
        [],{'wire':['a_terminal','b_terminal']},actions('left button',.2,.7),time_s=5))

    spec=_base('Two independent flippers',7)
    _fixture(spec,p.ball,'pinball')
    rows.append(_lesson(8,'Two independent flippers',
        'Add the other paddle in the second bearing. Its prepared leads form a separate parallel loop. In Run, hold Left, release it, then hold Right and release. Each paddle must move while the other rests.',
        spec,[_tray('pinball_flipper',[-.43,-.76],['length_m'],side='left')],
        span('your pinball_flipper 1 axle',-4,4),['left flipper paddle','your pinball_flipper 1 paddle'],
        [dict(piece='pinball_flipper',length_m=.4)],
        [dict(piece='pinball_flipper',length_m=.4)],{'pinball_flipper':['length_m']},
        actions('left button',.2,.5)+actions('right button',1.2,1.5),steps=[
            dict(title='Left alone',done_when=dict(joints_in_range=[dict(joint='left flipper axle',min_deg=40,max_deg=60),dict(joint='your pinball_flipper 1 axle',min_deg=-4,max_deg=4)])),
            dict(title='Right alone',done_when=dict(joints_in_range=[dict(joint='left flipper axle',min_deg=-4,max_deg=4),dict(joint='your pinball_flipper 1 axle',min_deg=-60,max_deg=-40)]))],time_s=7))

    spec=_base('Add bumpers and targets',9);_fixture(spec,p.ball,'lesson ball',x_m=.07,z_m=.9)
    _fixture(spec,p.target,'practice target',x_m=-.3,z_m=-.15)
    rows.append(_lesson(9,'Add bumpers and targets',
        'Place the rubber bumper under one side of the falling marble. Deflect it into the hanging target. Rubber returns some impact energy; this bumper has no hidden motor.',
        spec,[_tray('pinball_bumper',[.35,.4],['x_m','z_m','radius_m'])],
        dict(touches=['lesson ball','practice target target']),['lesson ball','practice target target'],
        [dict(piece='pinball_bumper',x_m=.13,z_m=.3,radius_m=.13)],
        [dict(piece='pinball_bumper',x_m=-.4,z_m=.3,radius_m=.13)],{'pinball_bumper':['x_m','z_m','radius_m']},
        steps=[dict(title='Bounce off your bumper',done_when=dict(touches=['lesson ball','your pinball_bumper 1']))],time_s=12))

    spec=p.template()['base'];spec['stations']=[]
    removed={'pinball','left bumper','right bumper','right target post','right target target','right inlane guide'}
    spec['parts']=[q for q in spec['parts'] if q['name'] not in removed]
    spec['joints']=[j for j in spec['joints'] if j['a'] not in removed and j['b'] not in removed]
    # Keep this beginner table open beside the shooter wall. The workshop's
    # optional short right guide can form a V pocket against that wall.
    return_gutter(spec)
    rows.append(_lesson(10,'Your own table',
        'Load your ball in the shooter lane. Run, hold and release the launcher, then use the flippers. Reach the upper marker and collect the ball in the green return gutter. Your table is saved in Sandbox; Reset reloads it.',
        spec,[_tray('pinball_ball',[.3,-1.1],['x_m','z_m'])],
        dict(in_zone=dict(part='your pinball_ball 1',at_m=[0,.2,-1.6],size_m=[.5,.6,.5])),
        ['your pinball_ball 1'],[dict(piece='pinball_ball',x_m=.63,z_m=-1.13)],
        [dict(piece='pinball_ball',x_m=.3,z_m=-1.1)],{'pinball_ball':['x_m','z_m']},
        actions('launcher')+[a for t in (3,5,7,9,11) for name in ('left button','right button')
            for a in actions(name,t,t+.2)],steps=[
            dict(title='Reach the top',done_when=zone('your pinball_ball 1',.63,.8,.2,.4))],time_s=25))
    for row in rows:
        previous=None
        for step in row['goal']['checkpoints']:
            if previous:step['after']=[previous]
            previous=step['title']
        if previous:row['goal']['station']['after']=[previous]
    return rows


def connect_lesson(level,spec,checked):
    """Prepared lesson leads are real cables, added only once endpoints exist."""
    i=(level.get('project') or {}).get('step')
    if not checked:return
    if i==7:
        original=next(w for w in p.template()['base']['electrical']['wires'] if w['a']=='left flipper:minus')
        for w in spec['electrical']['wires']:
            if {w['a'],w['b']}=={original['a'],original['b']}:
                name=w['name'];w.clear();w.update(copy.deepcopy(original),name=name)
        return
    if i not in (5,6,8):return
    if i==5:
        device='your pinball_flipper 1'
        spec['electrical']['devices']=[d for d in spec['electrical']['devices'] if d['name']!=device]
        # A separate hand grip at the paddle tip gives a real lever arm.
        grip=p.finish(dict(parts=[dict(name='hand grip',shape='compound',material='aluminum',fixed=False,
            at_m=[.148,.105,-.862],parts=[dict(shape='sphere',at_m=[0,0,0],size_m=[.04]*3)])],
            joints=[dict(name='hand grip fixing',kind='slide',a=device+' paddle',b='hand grip',at_m=[.148,.105,-.862],axis=[0,1,0],lower_m=0,upper_m=0)],
            **hold('hand paddle','hand grip',[0,0,18],'Lift paddle','Space')), {})
        _merge(spec,grip)
        return
    if i==8:
        _fixture(spec,p.button,'right button',x_m=-.96,z_m=-.85,label='Right flipper',key='ArrowRight')
        for w in p.template()['base']['electrical']['wires']:
            if w['name'].startswith('right '):
                w=copy.deepcopy(w)
                for key in ('a','b'):w[key]=w[key].replace('right flipper:','your pinball_flipper 1:')
                spec['electrical']['wires'].append(w)
        return
    pairs=[('pinball supply:plus','your pinball_button 1:in'),('your pinball_button 1:out','contact lamp:plus'),('contact lamp:minus','pinball supply:minus')]
    terminals={d['name']+':'+key:at for d in spec['electrical']['devices'] for key,at in d['terminals'].items()}
    for n,(a,b) in enumerate(pairs):
        pa,pb=terminals[a],terminals[b]
        path=[pa,[pa[0],.35-n*.015,pa[2]],[pb[0],.35-n*.015,pb[2]],pb]
        spec['electrical']['wires'].append(dict(name='lesson lead '+str(n),a=a,b=b,
            length_m=sum(math.dist(x,y) for x,y in zip(path,path[1:])),area_mm2=2.5,
            mechanical=dict(path_m=path,retention_n=200,segment_m=.08)))
