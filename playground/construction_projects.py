"""Private placement intent, bounded native site suggestions and resume.

This stores a selected owned physical item and checked destination, never a
world pose, free stock, a structural certificate or earned skill. Every view
re-reads ownership and every destination is checked against current physics.
Ordinary Inventory and native hand operations still perform the actual work.
"""
from copy import deepcopy
import json
import math

import inventory_room
import placement
import player_world
import workshop_library
import world_chat

SCHEMA = 'banjo.construction-project.v1'
MAX_RECEIPTS = 64


def _key(app, owner):
    if not getattr(app, 'world_id', None) or owner not in player_world.records(app):
        raise ValueError('Join a named world before choosing construction')
    return app.world_id, owner, app.room.scene


def _db(app):
    return workshop_library._connect(app)


def _load(db, key):
    db.execute('CREATE TABLE IF NOT EXISTS construction_projects '
        '(world_id TEXT NOT NULL, owner_id TEXT NOT NULL, scene TEXT NOT NULL, '
        'payload_json TEXT NOT NULL, PRIMARY KEY(world_id,owner_id,scene))')
    row = db.execute('SELECT payload_json FROM construction_projects '
        'WHERE world_id=? AND owner_id=? AND scene=?', key).fetchone()
    return json.loads(row['payload_json']) if row else {'revision': 0, 'project': None, 'receipts': {}}


def selected(app, owner):
    with _db(app) as db:
        return _load(db, _key(app, owner))


def clear(app, owner):
    import uuid
    record = selected(app, owner)
    if record['project']:
        request(app, owner, {'action':'clear','revision':record['revision'],'request_id':uuid.uuid4().hex})


def _person(app, owner, supplied=None):
    if supplied is not None:
        person = world_chat.where_the_person_is(supplied)
        if person is None:
            raise ValueError('Construction needs a finite current position and facing')
        return person
    pose = player_world.records(app)[owner].get('pose')
    if not pose:
        return None
    return world_chat.where_the_person_is({**pose,
        'standing_m': [pose['eyes_m'][0], pose['eyes_m'][1] - 1.62, pose['eyes_m'][2]]})


def _owned(app, owner, item):
    shown = inventory_room.shown(app, owner)
    for where, thing in [*shown['hands'].items(), *[('stowed', t) for t in shown['stowed']]]:
        if thing and thing['id'] == item:
            return where, thing
    return None, None


def _moving_name(app, owner, thing):
    holding = inventory_room._hand_of(app, owner).get('holding')
    return holding if holding in [thing['name'], *(thing.get('parts') or [])] else thing['name']


def _native(app, owner, name, person, *, expected=None):
    with app.live.as_actor(owner):
        return placement.resolve(app, {'session': app.live.session.id,
            'name': name, 'person': person, **({'expected': expected} if expected else {})})


def usable(answer):
    return bool(answer.get('fits') and answer.get('target') and
        answer.get('supported_corners', 0) >= 3 and not answer.get('may_fall_over'))


def suggest(app, owner, name, person, previous=None):
    """At most nine ordinary preview checks within the player's hand reach.

    No searching across the map or moving the player. A declined current aim
    is retained as the blocker; the first supported nearby answer is returned.
    """
    initial = _native(app, owner, name, person)
    candidates = [initial]
    feet, face = person['standing_m'], person['facing']
    eyes = person.get('eyes_m', [feet[0], feet[1] + 1.62, feet[2]])
    right = [-face[2], 0, face[0]]
    for ahead, side in ((1, -.55), (1, .55), (1.5, 0), (.65, 0),
                        (1.5, -.55), (1.5, .55), (1, -1), (1, 1)):
        aim = [feet[k] + face[k] * ahead + right[k] * side for k in range(3)]
        aim[1] = feet[1]
        if math.dist(eyes, aim) > placement.REACH_M:
            continue
        # A precise ground aim prevents unrelated receiving points snapping in.
        aimed = {**person, 'aim_m': aim, 'looking_at': ''}
        if usable(initial) and previous is None:
            break
        candidates.append(_native(app, owner, name, aimed))
        candidate = candidates[-1]
        if usable(candidate) and not _same_site(candidate.get('target'), previous):
            return candidate, initial.get('why')
    for candidate in candidates:
        if usable(candidate) and not _same_site(candidate.get('target'), previous):
            return candidate, initial.get('why')
    # Another location must not silently return the previous location as new.
    return None, initial.get('why') or 'No supported spot within reach. Move or prepare the ground.'


def _same_site(a, b):
    return bool(a and b and a['body'] == b['body'] and
                math.dist(a['on'], b['on']) < .2)


def view(app, owner, *, person=None):
    record = selected(app, owner)
    project = record['project']
    out = {'schema': SCHEMA, 'revision': record['revision'], 'project': None}
    if not project:
        return out
    project = deepcopy(project)
    where, thing = _owned(app, owner, project['item'])
    project.update(where=where, site=None, status='Unavailable')
    if thing:
        project['name'] = thing.get('label') or thing['name']
        moving = _moving_name(app, owner, thing)
        recipe = thing.get('recipe')
        if recipe:
            from mcp import workshop_components, workshop_placement
            design, _ = workshop_components.design_from_spec(recipe)
            project['installation'] = workshop_placement.for_design(design)
        if where == 'stowed':
            project.update(status='Equip', next_label='Hold ' + project['name'])
        else:
            project.update(status='Choose site', next_label='Find a supported spot')
            here = _person(app, owner, person)
            target = project.get('target')
            if target and here and getattr(app.live, 'session', None):
                try:
                    if moving != project['body']:
                        raise ValueError('The held component changed; choose another spot')
                    answer = _native(app, owner, moving, here, expected=target)
                    project['site'] = answer
                    project.update(status='Place' if usable(answer) else 'Site changed',
                        next_label='Place here' if usable(answer) else 'Choose another spot',
                        blocker=None if usable(answer) else answer.get('why'))
                except ValueError as error:
                    project.update(status='Site changed', next_label='Choose another spot', blocker=str(error))
    else:
        # Inspect actual released pose, never accepting a client completion flag.
        bodies = {b['name']: b for b in (getattr(app.live.session, 'state', None) or {}).get('bodies', [])}
        peer = any(_owned(app, who, project['item'])[1]
                   for who in player_world.records(app) if who != owner)
        body = bodies.get(project['body'])
        at = project.get('at_m')
        if not peer and body and not body.get('parked') and at and math.dist(body['position_m'], at) < .15:
            project.update(status='Placed', next_label='Inspect placed item',
                blocker='Placement observed. Settling, access and operation still need checks.')
        else:
            project.update(next_label='Open Inventory', blocker='This item is no longer in your hands or bag.')
    project['steps'] = [
        {'id': 'hold', 'label': 'Hold item', 'status': 'current' if project['status']=='Equip' else 'done' if where or project['status']=='Placed' else 'blocked'},
        {'id': 'site', 'label': 'Choose supported spot', 'status': 'done' if project['status'] in ('Place','Placed') else 'current' if where and where!='stowed' else 'pending'},
        {'id': 'place', 'label': 'Place item', 'status': 'done' if project['status']=='Placed' else 'current' if project['status']=='Place' else 'pending'},
        {'id': 'inspect', 'label': 'Check settling and access', 'status': 'current' if project['status']=='Placed' else 'pending'},
    ]
    out['project'] = project
    return out


def request(app, owner, body):
    if not isinstance(body, dict) or set(body)-{'action','item','revision','request_id','person'}:
        raise ValueError('Construction accepts a selected item and action, not supplied game state')
    action = body.get('action', 'view')
    if action not in ('view','select','clear','suggest'):
        raise ValueError('Unknown construction action')
    if action=='view':
        if set(body)-{'action','person'}:
            raise ValueError('A construction view needs no write fields')
        return view(app, owner, person=body.get('person'))
    ident = body.get('request_id')
    revision = body.get('revision')
    if not isinstance(ident,str) or not 1<=len(ident)<=100 or type(revision) is not int or revision<0:
        raise ValueError('Construction writes require a bounded request id and current revision')
    if ('item' in body)!=(action=='select'):
        raise ValueError('Select one of your physical items')
    if 'item' in body and (not isinstance(body['item'],str) or not 1<=len(body['item'])<=160):
        raise ValueError('Invalid construction item')
    # The pose is not part of the retained intent-write fingerprint; moving
    # while recovering a lost reply must replay the same selected-site receipt.
    fingerprint = json.dumps({k:v for k,v in body.items() if k!='person'}, sort_keys=True)
    key = _key(app, owner)
    with _db(app) as db:
        db.execute('BEGIN IMMEDIATE')
        record = _load(db, key)
        prior = record['receipts'].get(ident)
        if prior:
            if prior['fingerprint']!=fingerprint:
                raise ValueError('Construction request id was already used for different intent')
            return deepcopy(prior['answer'])
        if record['revision']!=revision:
            raise ValueError('Construction revision changed; refresh your next step')
        if action=='clear':
            record['project'] = None
        elif action=='select':
            where, thing = _owned(app, owner, body['item'])
            if not thing:
                raise ValueError('Select your own item from hands or bag')
            record['project'] = {'item':thing['id'], 'body':_moving_name(app,owner,thing),
                'name':thing.get('label') or thing['name'], 'target':None, 'at_m':None}
        else:
            project = record['project']
            where, thing = _owned(app, owner, project['item']) if project else (None,None)
            if not thing or where=='stowed':
                raise ValueError('Hold your selected item before checking a site')
            person = _person(app, owner, body.get('person'))
            if not person:
                raise ValueError('Open World to check a site within reach')
            moving = _moving_name(app, owner, thing)
            answer, blocker = suggest(app, owner, moving, person, project.get('target'))
            if not answer:
                return {'schema':SCHEMA,'revision':revision,'project':deepcopy(project),
                    'site_found':False,'blocker':blocker}
            project.update(body=moving,target=answer['target'], at_m=answer['at_m'])
        record['revision'] += 1
        answer = {'schema':SCHEMA,'revision':record['revision'],'project':deepcopy(record['project'])}
        record['receipts'][ident] = {'fingerprint':fingerprint,'answer':answer}
        record['receipts'] = dict(list(record['receipts'].items())[-MAX_RECEIPTS:])
        db.execute('INSERT INTO construction_projects VALUES (?,?,?,?) '
            'ON CONFLICT(world_id,owner_id,scene) DO UPDATE SET payload_json=excluded.payload_json',
            (*key,json.dumps(record,allow_nan=False)))
        return deepcopy(answer)


def guidance(app, owner):
    context = view(app, owner)
    project = context['project']
    if not project:
        return None
    status = project['status']
    screen = 'inventory' if status=='Unavailable' else 'world'
    return {'schema':'banjo.player-guidance.v1','chain_id':None,'goal':None,
        'project':{'name':project['name'],'focused':True,'source':'construction'},
        'construction_project':context, 'build_readiness':None,
        'next_action':{'verb':'construction','label':project['next_label'],
            'status':'Blocked' if status in ('Site changed','Unavailable') else 'Available',
            'destination':{'screen':screen,'place':project['item'],
                **({'focus':project['body']} if status=='Placed' else {})},
            'blockers':[project['blocker']] if project.get('blocker') else []},
        'limits':'Saved intent. Native placement rechecks reach, collisions and support; no structural certificate.'}
