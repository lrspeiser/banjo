"""Hollow gravity routes and grounded support frames.

The same compound wall geometry contacts native water parcels and rigid balls.
No path following, teleportation, pressure network or invented flow is used.
"""
import copy
import math
import machine_world as mw
import sandbox_water_launch as water

knob = water.knob
FACETS = 12
WALL_M = .02
PIPE_KINDS = ('pipe', 'pipe_elbow', 'pipe_reducer')


def _sub(at, size, turn=(0, 0, 0)):
    return dict(shape='box', at_m=at, size_m=size, turn_deg=list(turn))


def _shell(a, b, ra, rb, back=0, ahead=0):
    """Twelve tangent wall strips. A changing bore makes sloping reducer walls."""
    delta = [b[i]-a[i] for i in range(3)]
    length = math.hypot(*delta)
    along = [v/length for v in delta]
    # Routes run horizontally or downhill, never vertically in this builder.
    side = mw._mat_apply(mw.heading(math.degrees(math.atan2(-along[2], along[0])), 0, 0), [0, 0, 1])
    up = [side[1]*along[2]-side[2]*along[1], side[2]*along[0]-side[0]*along[2], side[0]*along[1]-side[1]*along[0]]
    out = []
    for i in range(FACETS):
        angle = 2*math.pi*i/FACETS
        radial = [math.cos(angle)*up[j]+math.sin(angle)*side[j] for j in range(3)]
        tangent = [-math.sin(angle)*up[j]+math.cos(angle)*side[j] for j in range(3)]
        aa = [a[j]+(ra+WALL_M/2)*radial[j] for j in range(3)]
        bb = [b[j]+(rb+WALL_M/2)*radial[j] for j in range(3)]
        strip_length = math.dist(aa, bb)
        x = [(bb[j]-aa[j])/strip_length for j in range(3)]
        y = [tangent[1]*x[2]-tangent[2]*x[1], tangent[2]*x[0]-tangent[0]*x[2], tangent[0]*x[1]-tangent[1]*x[0]]
        rotation = [[x[j], y[j], tangent[j]] for j in range(3)]
        out.append(_sub([(aa[j]+bb[j])/2+(ahead-back)*x[j]/2 for j in range(3)],
            [strip_length+back+ahead, WALL_M, 2*(max(ra, rb)+WALL_M)*math.tan(math.pi/FACETS)], mw.turn_of(rotation)))
    return out


def path(k, kind):
    """Local centerline, starting at the open inlet; lengths are true lengths."""
    if kind == 'pipe_elbow':
        turn = k.get('bend_deg', 90)
        radius = k.get('bend_radius_m', .5)
        if k.get('plane', 'horizontal') == 'downward':
            count = math.ceil(abs(turn)/22.5)
            return [[math.copysign(radius*(1-math.cos(math.radians(abs(turn)*i/count))), turn),
                     -radius*math.sin(math.radians(abs(turn)*i/count)), 0] for i in range(count+1)]
        sections, _, _ = mw.bend_path([0, 0, 0], 0, turn, radius, k.get('fall_m', .15))
        points = [[0, 0, 0]]
        for p, yaw, chord, fall in sections:
            angle = math.radians(yaw)
            points.append([p[0]+chord*math.cos(angle), p[1]-fall, p[2]-chord*math.sin(angle)])
        return points
    length = k.get('length_m', 1.2)
    slope = math.radians(k.get('drop_deg', 15))
    return [[0, 0, 0], [length*math.cos(slope), -length*math.sin(slope), 0]]


def _bed(ctx, x, z):
    raw = ctx.get('spec', {}).get('ground') or {}
    return water._routing_bed(ctx, x, z) if raw.get('kind') == 'flume' else 0


def _foot_bed(ctx, x, z, yaw, width, depth):
    rotation = mw.heading(yaw, 0, 0)
    probes = [mw._mat_apply(rotation, [dx, 0, dz]) for dx in (-width/2, 0, width/2)
              for dz in (-depth/2, 0, depth/2)]
    return max(_bed(ctx, x+p[0], z+p[2]) for p in probes)


def _beam_floor(solids, p, forward, across, along_half, across_half):
    """Lowest real wall point in the beam footprint, from clipped box faces."""
    heights = []
    planes = [(axis, sign, half) for axis, half in ((forward, along_half), (across, across_half)) for sign in (-1, 1)]
    for solid in solids:
        axes, halves, centre = mw._axes(solid), mw._half(solid), solid['at_m']
        def corner(values):
            return [centre[j]+sum(values[i]*halves[i]*axes[i][j] for i in range(3)) for j in range(3)]
        for fixed in range(3):
            other = [i for i in range(3) if i != fixed]
            for side in (-1, 1):
                face = []
                for a,b in ((-1,-1),(1,-1),(1,1),(-1,1)):
                    values=[0,0,0];values[fixed]=side;values[other[0]]=a;values[other[1]]=b
                    face.append(corner(values))
                for axis, sign, half in planes:
                    out=[]
                    for a,b in zip(face,face[1:]+face[:1]):
                        da=sign*sum((a[j]-p[j])*axis[j] for j in range(3))-half
                        db=sign*sum((b[j]-p[j])*axis[j] for j in range(3))-half
                        if da <= 1e-10:out.append(a)
                        if (da <= 0) != (db <= 0):out.append([a[j]+(b[j]-a[j])*da/(da-db) for j in range(3)])
                    face=out
                    if not face:break
                heights.extend(point[1] for point in face)
    if not heights:raise ValueError('The scaffolding must meet a pipe wall')
    return min(heights)


def _mounts(name, body, points, ctx, radius):
    """Two grounded trestles touch the real lower wall; a declared bolt holds it."""
    solids = mw.solids_of(body)
    parts, joints = [], []
    segments = ((points[0], points[1]), (points[-2], points[-1]))
    vertical = math.hypot(points[-1][0]-points[0][0], points[-1][2]-points[0][2]) < 1e-6
    if vertical: segments = segments[:1]
    for i, (a, b) in enumerate(segments):
        fraction = .25 if i == 0 else .75
        p = [a[j]+fraction*(b[j]-a[j]) for j in range(3)]
        if vertical: p[0] += radius+WALL_M/2
        yaw = math.degrees(math.atan2(-(b[2]-a[2]), b[0]-a[0]))
        if not vertical and abs(b[1]-a[1]) > 2*math.hypot(b[0]-a[0],b[2]-a[2]):yaw+=90
        across = mw._mat_apply(mw.heading(yaw, 0, 0), [0, 0, 1])
        forward = mw._mat_apply(mw.heading(yaw, 0, 0), [1, 0, 0])
        width = 2*radius+.24
        top = _beam_floor(solids, p, forward, across, .03, width/2)-.001
        subs = [_sub([0, -.02, 0], [.06, .04, width])]
        # A visible short mounting screw spans the clearance above the beam.
        # Its top approaches the actual lower wall without interpenetration.
        screw_top = _beam_floor(solids, p, forward, across, .006, .006)-.001
        screw_height = screw_top-top
        if screw_height > .001:subs.append(_sub([0, screw_height/2, 0], [.012, screw_height, .012]))
        for side in (-1, 1):
            z = side*(width/2-.03)
            xx, zz = p[0]+z*across[0], p[2]+z*across[2]
            foot = _foot_bed(ctx, xx, zz, yaw, .18, .16)
            # In a too-low proposal, retain a real leg so ordinary ground
            # penetration checks explain the refusal in the editor.
            height = max(.06, top-.04-foot)
            subs.extend([_sub([0, -.04-height/2, z], [.06, height, .06]),
                         _sub([0, foot-top+.02, z], [.18, .04, .16])])
        frame = dict(name=f'{name} scaffolding {i+1}', shape='compound', material='iron',
            at_m=[p[0], top, p[2]], turn_deg=[0, yaw, 0], fixed=True, parts=subs)
        parts.append(frame)
        joints.append(dict(name=f'{name} mounting bolt {i+1}', kind='fix', a=frame['name'], b=name,
            at_m=[p[0], screw_top, p[2]], axis=[0, 1, 0]))
    return parts, joints


def pipe(name, k, ctx, kind='pipe'):
    points = path(k, kind)
    r = k.get('radius_m', .12)
    other = k.get('outlet_radius_m', .08) if kind == 'pipe_reducer' else r
    if kind == 'pipe_elbow' and k.get('bend_radius_m', .5) < 2*(r+WALL_M):
        raise ValueError('The bend radius must be at least twice the pipe’s outside radius')
    shells = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        # Slight overlap closes the seams of the faceted elbow, as on native bends.
        seam = (r+WALL_M)*math.tan(math.pi/16) if kind == 'pipe_elbow' else 0
        shells += _shell(a, b, r, other, seam if i else 0, seam if i<len(points)-2 else 0)
    at = [k.get('x_m', -.6), k.get('height_m', 1), k.get('z_m', .7)]
    rotation = mw.heading(k.get('yaw_deg', 0), 0, 0)
    body = dict(name=name, shape='compound', material=k.get('material', 'glass'), at_m=at,
        turn_deg=mw.turn_of(rotation), fixed=False, parts=shells)
    result = dict(parts=[body], joints=[])
    if k.get('support', 'scaffolding') == 'scaffolding':
        world_points = [[at[j]+mw._mat_apply(rotation, p)[j] for j in range(3)] for p in points]
        mounts, joints = _mounts(name, body, world_points, ctx, max(r, other))
        result['parts'] += mounts; result['joints'] += joints
    return result


def scaffold(name, k, ctx):
    x, z, top = k.get('x_m', 0), k.get('z_m', 0), k.get('height_m', .6)
    width, depth = k.get('width_m', .8), k.get('depth_m', .5)
    yaw = k.get('yaw_deg', 0); rotation = mw.heading(yaw, 0, 0)
    subs = [_sub([0, -.025, 0], [width, .05, depth])]
    for dx in (-width/2+.04, width/2-.04):
        for dz in (-depth/2+.04, depth/2-.04):
            offset = mw._mat_apply(rotation, [dx, 0, dz])
            bed = _foot_bed(ctx, x+offset[0], z+offset[2], yaw, .14, .14)
            height = top-.05-bed
            subs.extend([_sub([dx, -.05-height/2, dz], [.06, height, .06]),
                         _sub([dx, bed-top+.02, dz], [.14, .04, .14])])
    # Visible rails stiffen the anchored assembly without occupying the space above its deck.
    for side in (-1, 1): subs.append(_sub([0, -top*.65, side*(depth/2-.04)], [width, .04, .04]))
    return dict(parts=[dict(name=name, shape='compound', material=k.get('material', 'iron'),
        at_m=[x, top, z], turn_deg=mw.turn_of(rotation), fixed=True, parts=subs)])


def pipe_elbow(name, k, ctx): return pipe(name, k, ctx, 'pipe_elbow')
def pipe_reducer(name, k, ctx): return pipe(name, k, ctx, 'pipe_reducer')
PIECES = dict(pipe=pipe, pipe_elbow=pipe_elbow, pipe_reducer=pipe_reducer, scaffold=scaffold)

_common = dict(x_m=knob(-2, 2, .01, -.6, 'inlet along (m)'),
    z_m=knob(-1.5, 1.5, .01, .7, 'inlet across (m)'), height_m=knob(.45, 1.8, .01, 1, 'inlet height (m)'),
    radius_m=knob(.06, .2, .01, .12, 'inside radius (m)'),
    yaw_deg=dict(knob(-180, 180, 5, 0, 'aim'), turning=True, free=True),
    material=dict(choices=['glass', 'oak', 'iron'], default='glass', label='wall material'),
    support=dict(choices=['scaffolding', 'loose'], default='scaffolding', label='support'))
TRAY = []
for kind in ('pipe', 'pipe_elbow', 'pipe_reducer'):
    knobs = copy.deepcopy(_common)
    if kind == 'pipe_elbow':
        knobs.update(bend_radius_m=knob(.3, .8, .05, .5, 'bend radius (m)'),
            bend_deg=dict(choices=[-90, -45, 45, 90], default=90, label='corner angle'),
            plane=dict(choices=['horizontal', 'downward'], default='horizontal', label='bend plane'),
            fall_m=knob(.05, .35, .01, .15, 'fall around corner (m)'))
    else:
        knobs.update(length_m=knob(.3, 2, .05, 1.2, 'pipe length (m)'),
            drop_deg=knob(5, 90, 1, 15, 'downhill angle'))
        if kind == 'pipe_reducer': knobs['outlet_radius_m'] = knob(.03, .2, .01, .08, 'outlet inside radius (m)')
    TRAY.append(dict(piece=kind, count=99, cost=0, turns=['yaw_deg'], knobs=knobs))
TRAY.append(dict(piece='scaffold', count=99, cost=0, turns=['yaw_deg'], knobs=dict(
    x_m=knob(-2, 2, .01, 0, 'position (m)'), z_m=knob(-1.5, 1.5, .01, 0, 'across (m)'),
    height_m=knob(.15, 1.5, .01, .6, 'platform height (m)'), width_m=knob(.3, 1.6, .05, .8, 'platform width (m)'),
    depth_m=knob(.25, 1.2, .05, .5, 'platform depth (m)'),
    yaw_deg=dict(knob(-180, 180, 5, 0, 'aim'), turning=True, free=True),
    material=dict(choices=['iron', 'oak', 'glass'], default='iron', label='frame material'))))
TEMPLATES = []

_water_base = copy.deepcopy(water.CHANNEL_BASE)
_water_base['title'] = 'Water through hollow pipes'
_water_setup = [dict(piece='water_tank',x_m=-.7,z_m=.7,height_m=1.4,outlet_model='gravity',
                    opening_percent=65,fill_l=4),
    dict(piece='pipe_elbow',x_m=-.7,z_m=.7,height_m=1.3,plane='downward',bend_radius_m=.5),
    dict(piece='pipe_reducer',x_m=-.185,z_m=.7,height_m=.797,length_m=.5,drop_deg=5,
         radius_m=.12,outlet_radius_m=.08),
    dict(piece='water_collector',x_m=.9,z_m=.7,floor_m=.25)]
TEMPLATES.append(dict(id='pipe-water',name='Water through pipes',
    description='Open the tank tap. Gravity takes water through a transparent elbow and reducer into a separate container.',
    base=_water_base,placements=_water_setup))

_ball_base = copy.deepcopy(water.DRY_BASE)
_ball_base['title']='Marble through a pipe'
_ball_setup=[dict(piece='pipe',x_m=-.8,z_m=0,height_m=1,length_m=1.2,drop_deg=15,radius_m=.12),
             dict(piece='marble',x_m=-.71875,z_m=0,height_m=.94668,placement='at height',diameter_m=.08,material='glass')]
# A waiting physical bin catches the ball; it does not follow a prescribed route.
_ball_base['parts']=[water._box('catcher floor',[1.25,.03,0],[1.3,.06,.5],'concrete',True),
    water._box('catcher front',[.58,.22,0],[.04,.44,.54],'concrete',True),
    water._box('catcher end',[1.92,.22,0],[.04,.44,.54],'concrete',True),
    *[water._box('catcher side '+str(side),[1.25,.22,side*.27],[1.3,.44,.04],'concrete',True) for side in (-1,1)]]
TEMPLATES.append(dict(id='pipe-marble',name='Marble through a pipe',
    description='A loose marble rolls inside the transparent pipe and into the waiting bin. Change its bore or remove scaffolding.',
    base=_ball_base,placements=_ball_setup))

_support_base=copy.deepcopy(water.DRY_BASE)
_support_base['title']='Hold up a loose board'
_support_base['parts']=[water._box('loose board',[0,.622,0],[.65,.04,.18],'oak'),
    dict(name='waiting marble',shape='sphere',material='glass',at_m=[0,.687,0],size_m=[.08]*3,fixed=False)]
TEMPLATES.append(dict(id='scaffold-board',name='Support a loose board',
    description='The separate platform holds the board and marble by contact. Remove it to watch them fall.',
    base=_support_base,placements=[dict(piece='scaffold',height_m=.6,width_m=.8,depth_m=.5)]))
