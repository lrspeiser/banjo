"""Authored wall activities composed from supported native mechanisms."""
import copy
import math


def levels():
    from wall_lessons import _board, _fixture, _tray, _lesson
    import sandbox_wall as wall
    result=[]

    def activity(ident,title,brief,spec,row,rule,solution,wrong,focus,seconds=6):
        lv=_lesson('easy-wall-'+ident,title,brief,spec,row,rule,focus,
            [solution.get('x_m',0),solution.get('height_m',1.5)],
            [wrong.get('x_m',0),wrong.get('height_m',1.5)],brief,1)
        lv['solution']=[dict(piece=row['piece'],**solution)]
        lv['wrong']=[dict(piece=row['piece'],**wrong)]
        lv['time_s']=seconds
        lv['custom_base']=True
        result.append(lv)
        return lv

    def water_board(title):
        spec=_board(title)
        spec['ground']=dict(kind='flume',nx=40,nz=24,cell_m=.1,trench_z_m=.3,
            trench_width_m=1.2,trench_depth_m=.35,trench_slope=.005,discharge_m3_s=0)
        return spec

    lift=_board('Lift and release the marble')
    _fixture(lift,'wall_lift','carrier',x_m=0,height_m=1.4)
    _fixture(lift,'wall_battery','supply',x_m=-1.1,height_m=.7)
    for key in ('plus','minus'):
        _fixture(lift,'wire','motor '+key,a_terminal='supply:'+key,b_terminal='carrier:'+key,length_m=2)
    u=.4/math.sqrt(2)
    activity('lift','Lift and release the marble',
        'Put the marble in the low open cradle. The wired motor turns the wheel, carries it upward and tips it onto the upper track. Reset reloads this one-pass lift.',
        lift,_tray('wall_marble',[.7,.7],diameter_m=.06,material='glass',placement='at height'),
        dict(in_zone=dict(part='your wall_marble 1',at_m=[.7,1.5,.3],size_m=[.5,.22,.16])),
        dict(x_m=-u,height_m=1.4-u+.14),dict(x_m=.7,height_m=.7),['carrier wheel','carrier outlet'],seconds=10)

    hydraulic=water_board('Water lifts a marble')
    _fixture(hydraulic,'wall_water_lift','carrier',x_m=0,height_m=1.4)
    _fixture(hydraulic,'wall_marble','marble',x_m=-u,height_m=1.4-u+.14,diameter_m=.06,material='glass')
    row=_tray('wall_water_tank',[.9,2.3],fill_l=8,outlet_model='gravity')
    # A separate forward lane clears the cradle. The editor still needs only
    # x/y placement; real paddles, shaft and falling water are all 3D solids.
    row['knobs']['plane_offset_m']=dict(min=.4,max=.4,default=.4,step=.01,hidden=True)
    # The standard mounted tank is translated by a native kit-free declaration
    # adapter; z_m is a fixed construction offset, not a run-time projection.
    activity('water-lift','Water lifts a marble',
        'Move the tank above the right-hand paddles and open its tap. Falling water turns the shared shaft, raising the marble in its cradle and tipping it onto the upper track.',
        hydraulic,row,dict(in_zone=dict(part='marble',at_m=[.7,1.5,.3],size_m=[.5,.22,.16])),
        dict(x_m=.24,height_m=2.3,opening_percent=100),dict(x_m=.9,height_m=2.3,opening_percent=100),
        ['carrier wheel','carrier outlet'],seconds=12)

    power=water_board('Water lights the lamp')
    _fixture(power,'wall_generator','dynamo',x_m=0,height_m=1.3,radius_m=.3,gear_ratio=1)
    _fixture(power,'wall_bulb','lamp',x_m=-.95,height_m=1,preset='small')
    # A declared 12 V / 0.3 W indicator, sized for this small water supply.
    power['electrical']['devices'][-1]['watts']=.3
    for key in ('plus','minus'):
        _fixture(power,'wire','lamp '+key,a_terminal='dynamo:'+key,b_terminal='lamp:'+key,length_m=1.5)
    activity('generator','Water lights the lamp',
        'Put the tank above the wheel’s right paddles and open the tap. The coupled generator converts shaft work into electricity. Its two wires power the lamp; there is no charged battery.',
        power,_tray('wall_water_tank',[-.9,2.3],fill_l=8,outlet_model='gravity'),
        dict(load_power_w=dict(device='lamp',at_least_w=.05,for_s=.1)),
        dict(x_m=.15,height_m=2.3,opening_percent=100),dict(x_m=-.9,height_m=2.3,opening_percent=100),
        ['dynamo wheel','dynamo housing','lamp bulb'],seconds=10)

    air=_board('Air pushes the marble')
    _fixture(air,'wall_track','runway',x_m=0,height_m=.9,length_m=2,angle_deg=0,end_stop='open')
    _fixture(air,'wall_marble','marble',x_m=-.45,height_m=.96,diameter_m=.08,material='oak')
    _fixture(air,'wall_cup','catcher',x_m=1.15,height_m=.7,width_m=.65)
    activity('air','Air pushes the marble',
        'The level track will not roll the marble by itself. Point the air nozzle right and increase air speed so drag pushes the marble into the cup. The nozzle is an external air supply.',
        air,_tray('wall_air',[-1.1,1],length_m=2,direction_deg=0),
        dict(in_zone=dict(part='marble',at_m=[1.15,.78,.3],size_m=[.45,.12,.32])),
        dict(x_m=-1.1,height_m=1,speed_m_s=20),dict(x_m=-1.1,height_m=1,speed_m_s=0),
        ['marble','catcher cup'],seconds=8)

    steam=_board('Steam raises the piston')
    activity('steam','Steam raises the piston',
        'Place the boiler and piston. Increase firebox heat to boil water and raise the piston ten centimetres. Pressure and piston motion are measured; the boiler starts at boiling temperature.',
        steam,_tray('wall_boiler',[0,1]),dict(rose_m=dict(part='your wall_boiler 1 piston',m=.1)),
        dict(x_m=0,height_m=1,heat_kw=10),dict(x_m=0,height_m=1,heat_kw=0),
        ['your wall_boiler 1 boiler','your wall_boiler 1 piston'],seconds=8)

    flap=_board('Open the wall trapdoor')
    _fixture(flap,'wall_marble','marble',x_m=.24,height_m=1.9,diameter_m=.08,material='glass')
    _fixture(flap,'wall_cup','catcher',x_m=.4,height_m=.4,width_m=1)
    activity('trapdoor','Open the wall trapdoor',
        'Place the hinged flap under the marble. Reduce hinge resistance so the flap’s own weight opens it and lets the marble fall into the cup.',
        flap,_tray('wall_trapdoor',[0,1.4],length_m=.5,material='oak'),
        dict(hinge_beyond_deg=dict(joint='your wall_trapdoor 1 hinge',deg=-60)),
        dict(x_m=0,height_m=1.4,friction_n_m=0),dict(x_m=0,height_m=1.4,friction_n_m=10),
        ['your wall_trapdoor 1 leaf','catcher cup'])

    swing=_board('Swing into the target')
    _fixture(swing,'wall_marble','target marble',x_m=-.2,height_m=1.55,diameter_m=.12,material='glass')
    swing['parts'].append(dict(name='target slide rail',shape='box',material='iron',fixed=True,
        size_m=[1.2,.04,.04],at_m=[-.5,1.55,.08]))
    swing['parts'].append(wall.mount('target slide bracket',-.5,1.55,.07))
    swing['joints'].append(dict(name='target slide',kind='slide',a='target slide rail',b='target marble',
        at_m=[-.2,1.55,.3],axis=[1,0,0],lower_m=-.9,upper_m=.1,friction_n=0))
    pendulum=activity('pendulum','Swing into the target',
        'Add the pendulum at the gold mount; its position is already lined up. Increase Release angle to raise the square bob to the right, then Place and Run. It swings left and hits the blue target along its rail, past the green mark.',
        swing,_tray('wall_pendulum',[0,2.2],length_m=.7,material='oak',friction_n_m=.001),
        dict(moved_m=dict(part='target marble',m=.15)),
        dict(x_m=0,height_m=2.2,start_deg=50),dict(x_m=0,height_m=2.2,start_deg=0),
        ['your wall_pendulum 1 arm','target marble'])
    # Editing annotations only. Neither the target body nor the native slide,
    # contact, goal, deadline or energy par is changed by these guides.
    pendulum['camera_area']=dict(at_m=[-.15,1.95,.3],size_m=[2,1.25,.5])
    pendulum['setup_guides']=[
        dict(kind='ring',at_m=[0,2.2,.4],radius_m=.07,color='#ffd36a',
             title='Hang the pivot here',text='Add the pendulum; raise its bob to the right.',when_missing='wall_pendulum'),
        dict(kind='ring',part='target marble',at_m=[-.2,1.55,.4],radius_m=.09,color='#65d9ff',
             title='Push the blue target left',text='Centre past green mark · 15 cm.'),
        dict(kind='mark',at_m=[-.35,1.55,.42],height_m=.26,color='#5fe08f')]

    spring=_board('Release the wall spring')
    _fixture(spring,'wall_marble','marble',x_m=0,height_m=1.38,diameter_m=.08,material='glass')
    launch=activity('spring','Release the wall spring',
        'Place the spring directly under the marble. Lengthen its relaxed-length handles to store more push, then Run and press Release spring. The push plate must contact the marble.',
        spring,_tray('wall_spring',[0,1],compressed_m=.2,damping_n_s_m=1),
        dict(rose_m=dict(part='marble',m=.3)),
        dict(x_m=0,height_m=1,rest_m=.6,stiffness_n_m=200),dict(x_m=.8,height_m=1,rest_m=.6,stiffness_n_m=200),
        ['marble','your wall_spring 1 push plate'])
    launch['solution_releases']=['your wall_spring 1 restraint']

    optics=_board('Reflect light up the wall')
    _fixture(optics,'wall_laser','beam',x_m=-1,height_m=1,watts=10)
    optics['parts'].append(dict(name='sensor',shape='box',material='concrete',fixed=True,
        size_m=[.2,.02,.2],at_m=[0,2.4,.3]))
    optics['parts'].append(wall.mount('sensor bracket',0,2.4,.2))
    optics['light']=dict(photocells=[dict(name='target',on='sensor',at_m=[0,2.389,.3],normal=[0,-1,0],area_m2=.02)])
    activity('mirror','Reflect light up the wall',
        'Put the mirror in the horizontal beam and turn its face to send light upward into the sensor. The beam preview stays visible while you adjust it.',
        optics,_tray('wall_mirror',[.7,1.6],size_m=.3),dict(lit_w=dict(photocell='target',w=.2)),
        dict(x_m=0,height_m=1,angle_deg=-45),dict(x_m=.7,height_m=1.6,angle_deg=0),['sensor'])

    focus=_board('Focus light on the wall')
    _fixture(focus,'wall_laser','beam',x_m=-.8,height_m=1.5,watts=10,beam_width_m=.12)
    focus['parts'] += [dict(name='sensor',shape='box',material='concrete',fixed=True,
        size_m=[.02,.12,.12],at_m=[.3,1.5,.3]),wall.mount('sensor bracket',.3,1.5,.24)]
    focus['light']=dict(photocells=[dict(name='target',on='sensor',at_m=[.29,1.5,.3],normal=[-1,0,0],area_m2=.0004)])
    activity('lens','Focus light on the wall',
        'Place the convex lens in the broad beam. Change its face radius to concentrate light on the small sensor. Watch the traced rays as the actual lens curvature changes.',
        focus,_tray('wall_lens',[-.3,2.2],diameter_m=.25,shape='convex'),dict(lit_w=dict(photocell='target',w=2)),
        dict(x_m=0,height_m=1.5,radius_m=.2),dict(x_m=-.3,height_m=2.2,radius_m=.3),['sensor'])

    gears=_board('Connect the wall gears')
    _fixture(gears,'wall_motor','drive',x_m=-.31,height_m=1.5,teeth=12)
    _fixture(gears,'wall_gear','target',x_m=.45,height_m=1.5,teeth=24)
    gears['electrical']['devices'][-1]['stall_torque_n_m']=4
    _fixture(gears,'wall_battery','supply',x_m=-1.1,height_m=.6)
    for key in ('plus','minus'):
        _fixture(gears,'wire','motor '+key,a_terminal='supply:'+key,b_terminal='drive:'+key,length_m=2)
    gear_row=_tray('wall_gear',[-.8,2.4],module_m=.024)
    gear_row['knobs']['phase_deg']['default']=10
    gear_row['knobs']['tooth_width_ratio']=dict(default=.9,min=.9,max=.9,hidden=True,label='Tooth width / module')
    activity('gears','Connect the wall gears',
        'Place one gear in the gap between the powered small gear and the big wheel. Match height and teeth so contacts transfer torque. Your gear has no motor of its own.',
        gears,gear_row,dict(turned_deg=dict(joint='target axle',deg=180)),
        dict(x_m=0,height_m=1.5,teeth=12,phase_deg=10),dict(x_m=0,height_m=2.4,teeth=12,phase_deg=10),['target wheel'],seconds=8)

    pipe=_board('Roll through a wall pipe')
    _fixture(pipe,'wall_marble','marble',x_m=-.8,height_m=2.2,diameter_m=.08,material='glass')
    _fixture(pipe,'wall_cup','catcher',x_m=.4,height_m=.5,width_m=1.1)
    activity('pipe','Roll through a wall pipe',
        'Move the hollow pipe inlet under the marble. The downhill tube must carry it to the cup. Its inside radius changes actual clearance; no path-following moves the marble.',
        pipe,_tray('wall_pipe',[-.8,2.5],length_m=1.3,drop_deg=25,radius_m=.12,material='glass'),
        dict(in_zone=dict(part='marble',at_m=[.4,.58,.3],size_m=[.9,.12,.32])),
        dict(x_m=-.8,height_m=1.9),dict(x_m=-.8,height_m=2.5),['marble','catcher cup'],seconds=8)

    for kind in ('resistor','capacitor'):
        title='Limit current on the wall' if kind=='resistor' else 'Store charge on the wall'
        spec=_board(title)
        _fixture(spec,'wall_battery','supply',x_m=-1,height_m=.6)
        if kind=='resistor':
            _fixture(spec,'wall_bulb','lamp',x_m=1,height_m=.6,preset='small')
            _fixture(spec,'wire','lamp return',a_terminal='lamp:minus',b_terminal='supply:minus',length_m=3)
            connects={'a':'supply:plus','b':'lamp:plus'}
            rule=dict(load_power_w=dict(device='lamp',at_least_w=2,for_s=.3))
            good,bad=dict(resistance_ohm=4),dict(resistance_ohm=48)
            brief='Place the prewired resistor and lower its resistance until the lamp receives 2 watts. The voltage and current labels show the series voltage drop.'
        else:
            _fixture(spec,'wall_resistor','charging resistor',x_m=-.5,height_m=1,resistance_ohm=12)
            _fixture(spec,'wire','charging feed',a_terminal='supply:plus',b_terminal='charging resistor:a',length_m=2)
            connects={'a':'charging resistor:b','b':'supply:minus'}
            rule=dict(capacitor_energy_j=dict(device='your wall_capacitor 1',at_least_j=4,for_s=.1))
            good,bad=dict(capacitance_f=.1),dict(capacitance_f=.005)
            brief='Place the prewired capacitor and increase its capacitance to store four joules before time runs out. The live meter shows charge, volts and stored energy.'
        row=_tray('wall_'+kind,[.2,1.8]);row['connect_to']=connects
        if kind=='capacitor':row['knobs']['capacitance_f']['default']=.005
        row['knobs']['x_m'].update(min=.2,max=.2)
        row['knobs']['height_m'].update(min=1.8,max=1.8)
        activity(kind,title,brief,spec,row,rule,dict(x_m=.2,height_m=1.8,**good),
            dict(x_m=.2,height_m=1.8,**bad),['lamp bulb'] if kind=='resistor' else ['your wall_capacitor 1 housing'])

    sunlight=_board('Catch sunlight on the wall')
    sunlight['sun']=dict(elevation_deg=35,azimuth_deg=0,irradiance_w_m2=1000)
    _fixture(sunlight,'wall_battery','receiver',x_m=-.9,height_m=.7,charge_percent=0)
    panel=_tray('wall_solar',[.5,1.8])
    solar=activity('solar','Catch sunlight on the wall',
        'Tilt the panel toward the sun and connect its Output ring to the battery’s Input. Its meter shows captured watts; only a connected cable delivers energy to the battery.',
        sunlight,panel,dict(charged_j=dict(battery='receiver battery',at_least_j=20)),
        dict(x_m=.5,height_m=1.8,tilt_deg=35),dict(x_m=.5,height_m=1.8,tilt_deg=-90),
        ['receiver housing','your wall_solar 1'],seconds=4)
    import sandbox_electrics as electrics
    cable=copy.deepcopy(next(row for row in electrics.TRAY if row['piece']=='power_cable'))
    cable.update(count=1,sandbox_builder=True)
    solar['tray'].append(cable)
    solar['solution'].append(dict(piece='power_cable',a_port='your wall_solar 1:power',b_port='receiver:power'))
    solar['wrong']=copy.deepcopy(solar['solution']);solar['wrong'][0]['tilt_deg']=-90

    parallel=_board('Two wall lamps in parallel')
    _fixture(parallel,'wall_battery','supply',x_m=-1,height_m=1.5)
    for lamp,y in [('upper lamp',2.2),('lower lamp',.7)]:
        _fixture(parallel,'wall_bulb',lamp,x_m=.7,height_m=y,preset='small')
        _fixture(parallel,'wire',lamp+' return',a_terminal=lamp+':minus',b_terminal='supply:minus',length_m=3)
    wire=copy.deepcopy(next(row for row in wall.tray() if row['piece']=='wire'))
    wire.update(count=2,wall_wire=True)
    wire['knobs']['length_m'].update(min=5,max=5,default=5,hidden=True)
    lv=activity('parallel','Two wall lamps in parallel',
        'The returns are ready. Draw a feed from battery plus to each lamp plus. Both lamps need their own path across the supply; putting them in series shares the voltage.',
        parallel,wire,dict(load_power_w=dict(devices=['upper lamp','lower lamp'],at_least_w=2,for_s=.3)),
        {},{},['upper lamp bulb','lower lamp bulb'])
    lv['solution']=[dict(piece='wire',a_terminal='supply:plus',b_terminal=lamp+':plus') for lamp in ('upper lamp','lower lamp')]
    lv['wrong']=[dict(piece='wire',a_terminal='supply:plus',b_terminal='upper lamp:plus')]
    # Visible height target for the boiler before its stock is placed.
    next(l for l in result if l['id']=='easy-wall-steam')['goal']['area']=dict(at_m=[0,1.45,.3],size_m=[.36,.02,.36])
    next(l for l in result if l['id']=='easy-wall-spring')['goal']['area']=dict(at_m=[0,1.68,.3],size_m=[.2,.02,.2])
    next(l for l in result if l['id']=='easy-wall-spring')['tray'][0]['knobs']['rest_m']['default']=.25
    next(l for l in result if l['id']=='easy-wall-trapdoor')['tray'][0]['knobs']['friction_n_m']=dict(
        choices=[0,10],default=10,label='Hinge resistance (N·m)')
    boiler_row=next(l for l in result if l['id']=='easy-wall-steam')['tray'][0]
    boiler_row['knobs']['x_m'].update(min=0,max=0)
    boiler_row['knobs']['height_m'].update(min=1,max=1)
    pipe_row=next(l for l in result if l['id']=='easy-wall-pipe')['tray'][0]
    pipe_row['knobs']['x_m']['max']=.1
    pipe_row['knobs']['height_m']['min']=.9
    next(l for l in result if l['id']=='easy-wall-gears')['tray'][0]['turns']=['phase_deg']
    pars=dict(lift=4250000,**{'water-lift':545000000},generator=293000000,air=687000000,
        steam=6710000000,trapdoor=104000000,pendulum=84400000,spring=352000000,
        mirror=817000000,lens=333000000,gears=1090000000,pipe=992000000,
        resistor=265000000,capacitor=315000000,solar=228000000,parallel=2.1)
    for lv in result:
        lv['teaches']=lv['title'].lower()
        lv['par_energy_j']=pars[lv['id'].removeprefix('easy-wall-')]
    return result
