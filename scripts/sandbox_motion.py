"""Contact, hinge, spring and prescribed-air mechanisms. No event scripting."""
import copy
import math
import machine_world as mw
from sandbox_mechanics import box, number, choice, tray, base

MATERIALS=['oak','glass','iron']

def dominoes(name,k,ctx):
    import machine_game as mg
    fragment=mg._dominoes(name,k,ctx)
    fragment['kits'][0]['material']=k.get('material','oak')
    # A setup angle, not a later trigger: gravity topples the first block.
    if k.get('first_tilt_deg',0):
        parts,joints=mw._kit_domino_row(fragment['kits'][0],[],name)
        first=parts[0]; angle=math.radians(k['first_tilt_deg']); h=k['tall_m']
        first['turn_deg']=[0,0,-k['first_tilt_deg']]
        first['at_m'][0]+=.5*h*math.sin(angle)
        first['at_m'][1]=fragment['kits'][0]['start_m'][1]+.5*(h*math.cos(angle)+.02*math.sin(angle))
        mw.turn_rows(mw.heading(*[k.get(v,0) for v in ('yaw_deg','pitch_deg','roll_deg')]),
                     fragment['kits'][0]['start_m'],parts+joints)
        return dict(parts=parts,joints=joints)
    return fragment

def loose_block(name,k,ctx):
    return {'parts':[box(name,[k.get('width_m',.2),k.get('height_m',.2),k.get('depth_m',.2)],
        [k.get('x_m',0),k.get('center_height_m',.1),k.get('z_m',0)],k.get('material','oak'),False)]}

def door(name,k,ctx):
    x,z=k.get('x_m',0),k.get('z_m',0); width=k.get('width_m',.6); h=k.get('height_m',.8)
    angle=math.radians(k.get('open_deg',0)); pivot=[x,h/2+.025,z]
    center=[x+width*.5*math.cos(angle),pivot[1],z-width*.5*math.sin(angle)]
    return dict(parts=[box(name+' jamb',[.08,h+.1,.08],[x-.065,(h+.1)/2,z],'concrete'),
        box(name+' leaf',[width,h,.04],center,k.get('material','oak'),False,turn_deg=[0,k.get('open_deg',0),0])],
        joints=[dict(name=name+' hinge',kind='hinge',a=name+' jamb',b=name+' leaf',at_m=pivot,
            axis=[0,1,0],lower_deg=-120,upper_deg=120,friction_n_m=k.get('friction_n_m',.01))])

def trapdoor(name,k,ctx):
    x,z=k.get('x_m',0),k.get('z_m',0); h=k.get('height_m',.65); w=k.get('length_m',.5)
    return dict(parts=[box(name+' stand',[.08,h,.08],[x-.065,h/2,z]),
        box(name+' leaf',[w,.04,.3],[x+w/2,h,z],k.get('material','oak'),False)],
        joints=[dict(name=name+' hinge',kind='hinge',a=name+' stand',b=name+' leaf',at_m=[x,h,z],
            axis=[0,0,1],lower_deg=-90,upper_deg=0,friction_n_m=k.get('friction_n_m',.01))])

def pendulum(name,k,ctx):
    x,z=k.get('x_m',0),k.get('z_m',0); h=k.get('height_m',1.3); length=k.get('length_m',.8)
    return dict(parts=[box(name+' post',[.06,h+.1,.06],[x,(h+.1)/2,z-.16]),
        {'name':name+' arm','shape':'compound','material':k.get('material','oak'),'at_m':[x,h,z],
         'turn_deg':[0,0,k.get('start_deg',45)],'parts':[
             dict(shape='box',size_m=[.03,length,.03],at_m=[0,-length/2,0]),
             dict(shape='box',size_m=[.14,.14,.14],at_m=[0,-length,0])]}],
        joints=[dict(name=name+' pivot',kind='hinge',a=name+' post',b=name+' arm',at_m=[x,h,z],axis=[0,0,1],
            lower_deg=-100,upper_deg=100,friction_n_m=k.get('friction_n_m',.001))])

def trampoline(name,k,ctx):
    x,z=k.get('x_m',0),k.get('z_m',0); width=k.get('width_m',.5); stiffness=k.get('stiffness_n_m',8000)
    mat=k.get('material','rubber'); mass={'oak':700,'glass':2500,'iron':7870,'rubber':1100}[mat]*width*width*.02
    # Unloaded equilibrium: no hidden preload launches a waiting ball.
    height=.4-mass*9.81/stiffness
    parts=[box(name+' base',[width+.1,.08,width+.1],[x,.04,z]),
        box(name+' deck',[width,.02,width],[x,height,z],mat,False),
        box(name+' guide',[.04,.6,.04],[x+width/2+.07,.3,z])]
    joints=[dict(name=name+' slide',kind='slide',a=name+' guide',b=name+' deck',at_m=[x,height,z],
        axis=[0,1,0],lower_m=.11-height,upper_m=.65-height,friction_n=0)]
    for i,(dx,dz) in enumerate([(-1,-1),(-1,1),(1,-1),(1,1)]):
        joints.append(dict(name=name+f' spring {i+1}',kind='spring',a=name+' base',b=name+' deck',
            at_m=[x+dx*width*.35,.08,z+dz*width*.35],at_b_m=[x+dx*width*.35,height-.02,z+dz*width*.35],
            rest_m=.3,stiffness_n_m=stiffness/4,damping_n_s_m=k.get('damping_n_s_m',2)/4))
    return dict(parts=parts,joints=joints)

def flywheel(name,k,ctx):
    x,z=k.get('x_m',0),k.get('z_m',0); r=k.get('radius_m',.25); h=r+.15
    return dict(parts=[box(name+' stand',[.08,h,.08],[x,h/2,z-.1]),
        dict(name=name+' wheel',shape='compound',material=k.get('material','iron'),at_m=[x,h,z],parts=[
            dict(shape='cylinder',size_m=[2*r,.04,2*r],at_m=[0,0,0],turn_deg=[90,0,0]),
            dict(shape='box',size_m=[.015,r,.01],at_m=[0,r/2,.025])])],
        joints=[dict(name=name+' axle',kind='hinge',a=name+' stand',b=name+' wheel',at_m=[x,h,z],
            axis=[0,0,1],friction_n_m=k.get('friction_n_m',.001))])

def wind(name,k,ctx):
    x,z=k.get('x_m',0),k.get('z_m',0); angle=math.radians(k.get('direction_deg',0)); speed=k.get('speed_m_s',8)
    return dict(parts=[box(name+' source',[.18,.08,.18],[x,.04,z],'iron')],airflows=[dict(
        name=name+' air',**{'in':name+' source'},center_m=[x,.8,z],size_m=[k.get('width_m',2),1.6,k.get('width_m',2)],
        velocity_m_s=[speed*math.cos(angle),0,-speed*math.sin(angle)])])

PIECES=dict(dominoes=dominoes,loose_block=loose_block,door=door,trapdoor=trapdoor,pendulum=pendulum,trampoline=trampoline,flywheel=flywheel,wind=wind)
TRAY=[
    tray('dominoes','Domino row',dict(count=number('Number of dominoes',1,20,6,1),spacing_m=number('Spacing (m)',.05,.4,.1),
        tall_m=number('Height (m)',.1,.5,.24),material=choice('Material',MATERIALS,'oak'),first_tilt_deg=number('First domino lean',0,40,0,1)),turns=['yaw_deg']),
    tray('loose_block','Loose block',dict(width_m=number('Width (m)',.06,.5,.2),height_m=number('Height (m)',.06,.5,.2),
        depth_m=number('Depth (m)',.06,.5,.2),center_height_m=number('Center height (m)',.03,2,.1),material=choice('Material',MATERIALS,'oak')),turning=False),
    tray('door','Hinged door',dict(width_m=number('Door width (m)',.2,.9,.6),height_m=number('Door height (m)',.2,1.2,.8),
        open_deg=number('Starting opening',-90,90,0,1),friction_n_m=number('Hinge resistance (N m)',0,1,.01,.01),material=choice('Material',MATERIALS,'oak')),turning=False),
    tray('trapdoor','Trapdoor',dict(length_m=number('Flap length (m)',.2,.7,.5),height_m=number('Hinge height (m)',.35,1,.65),
        friction_n_m=number('Hinge resistance (N m)',0,200,.01,.01),material=choice('Material',MATERIALS,'oak')),turning=False),
    tray('pendulum','Pendulum',dict(length_m=number('Arm length (m)',.3,.9,.8),height_m=number('Pivot height (m)',1.1,1.8,1.3),
        start_deg=number('Starting swing angle',-70,70,45,1),friction_n_m=number('Bearing resistance (N m)',0,.1,.001,.001),material=choice('Material',MATERIALS,'oak')),turning=False),
    tray('trampoline','Spring trampoline',dict(width_m=number('Deck width (m)',.3,.7,.5),stiffness_n_m=number('Total spring stiffness (N/m)',2000,20000,8000,100),
        damping_n_s_m=number('Total damping (N s/m)',0,80,2,1),material=choice('Deck material',MATERIALS+['rubber'],'rubber')),turning=False),
    tray('flywheel','Flywheel',dict(radius_m=number('Wheel radius (m)',.12,.4,.25),friction_n_m=number('Bearing resistance (N m)',0,.1,.001,.001),
        material=choice('Wheel material',MATERIALS,'iron')),turning=False),
    tray('wind','Open airflow',dict(speed_m_s=number('Air speed (m/s)',0,20,8,1),direction_deg=number('Air direction',-180,180,0,5),
        width_m=number('Field width (m)',.5,4,2,.1)),turning=False)]

TEMPLATES=[
 dict(name='Domino chain',description='Gravity tips a leaning first domino; contacts carry the chain. Change spacing or material.',base=base('Domino chain'),placements=[dict(piece='dominoes',x_m=-.6,first_tilt_deg=15)]),
 dict(name='Wind opens a door',description='An open-air field pushes a real door on its vertical hinge. Try edge-on wind or more hinge resistance.',base=base('Wind opens a door'),placements=[dict(piece='door',x_m=-.3),dict(piece='wind',x_m=0,z_m=.5,direction_deg=90,speed_m_s=12)]),
 dict(name='Spring trampoline',description='A falling glass marble compresses a spring-supported deck and rebounds. Change stiffness and damping.',base=base('Spring trampoline'),placements=[dict(piece='trampoline'),dict(piece='marble',placement='at height',height_m=1.2,diameter_m=.1,material='glass')]),
 dict(name='Pendulum and blocks',description='A raised pendulum strikes a loose block by contact. Adjust its release angle or move the block out of reach.',base=base('Pendulum and blocks'),placements=[dict(piece='pendulum',height_m=1.1,length_m=.9),dict(piece='loose_block',x_m=-.2,width_m=.1,height_m=.35,depth_m=.18,center_height_m=.18)]),
 dict(name='Gravity trapdoor',description='A hinged flap falls under its own weight. Hinge resistance can hold it; no invisible trigger releases it.',base=base('Gravity trapdoor'),placements=[dict(piece='trapdoor')]),
 dict(name='Flywheel workbench',description='A passive wheel on a free axle. Add a motor and wire its supply, or drive it through contact.',base=base('Flywheel workbench'),placements=[dict(piece='flywheel')]),
 dict(name='Stack loose blocks',description='Independent blocks support one another through contact. Move a lower block to test the stack.',base=base('Stack loose blocks'),placements=[dict(piece='loose_block',center_height_m=.101),dict(piece='loose_block',center_height_m=.305),dict(piece='loose_block',center_height_m=.509)])]
EASY_LEVELS=[]

# A complete wired drive shows how a flywheel gets energy, rather than
# silently assigning spin. Players can disconnect either wire to compare.
import sandbox_electrics as se
_fly=base('Flywheel workbench')
se.merge(_fly,flywheel('wheel',{},{}))
se.merge(_fly,se.battery('supply',dict(x_m=-.6,z_m=-.3),{}))
se.merge(_fly,se.motor('drive',dict(x_m=0,z_m=-.3,hinge='wheel axle'),{}))
se.link(_fly,'motor feed','supply:plus','drive:plus')
se.link(_fly,'motor return','drive:minus','supply:minus')
_template=next(t for t in TEMPLATES if t['name']=='Flywheel workbench')
_template.update(base=_fly,placements=[],description='A finite wired battery powers a motor on the wheel axle. Remove a wire to compare; move and edit the prepared parts.')
