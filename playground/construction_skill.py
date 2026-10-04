"""Evidence that a player set a thing down so it stands: "Setting things down".

Recorded when the player looks over an item they placed with the build guide
(construction_projects, the inspect step), and only from the running room:
the item's native body must be where it was set (within 15 cm, as the guide's
Placed check) and upright (within 10 degrees, as the stand trial in
workshop_install). Placing it, naming it or asking does not count. One
record per placement: looking it over again adds nothing.
"""
import hashlib
import math
import time

from mcp import progression

# Which registered design a placed item demonstrates, by the recipe it was
# made from (progression/designs.json).
DESIGNS = {'mine-lamp': 'camp-light', 'solar-array': 'camp-solar-panel'}
UPRIGHT_DEG = 10.0
WHERE_SET_M = .15


def _tilt_deg(body):
    w, x, y, z = body.get('orientation_wxyz') or [1, 0, 0, 0]
    up_y = 1 - 2 * (x * x + z * z)
    return math.degrees(math.acos(max(-1.0, min(1.0, up_y))))


def demonstrated(app, owner, project):
    """Record the evidence and earn what it opens. The names learned, or []."""
    design_id = DESIGNS.get(project.get('kind') or '')
    if not design_id:
        return []
    bodies = {b['name']: b for b in (app.live.session.state or {}).get('bodies', [])}
    body = bodies.get(project['body'])
    at = project.get('at_m')
    if not body or body.get('parked') or not at:
        return []
    moved = math.dist(body['position_m'], at)
    tilt = _tilt_deg(body)
    stands = moved < WHERE_SET_M and tilt <= UPRIGHT_DEG
    registry = app.registry()
    design = registry.designs[design_id]
    when = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    key = f"{app.world_id}:{owner}:{project['item']}:{at[0]:.3f},{at[1]:.3f},{at[2]:.3f}"
    record = {
        'id': 'ev-' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:10],
        'run': key, 'at': when, 'design': f"{design_id}@{design['revision']}",
        'object': project.get('name') or design['name'], 'source': 'placed',
        'test': 'stands-where-set', 'passes': stands,
        'action': 'set it down in World with the build guide, then look it over',
        'target': {'place': project.get('target', {}).get('body') or 'the ground'},
        'result': {'moved_m': round(moved, 4), 'tilt_deg': round(tilt, 2)},
        'models': ['native rigid placement and settling'],
        'limitations': ['a placement on the day it was made; it says nothing of how it weathers'],
        'said': (f"{project.get('name')} stands where it was set ({moved * 100:.0f} cm off, "
                 f"{tilt:.1f} degrees from upright)" if stands else
                 f"{project.get('name')} moved {moved * 100:.0f} cm or leans {tilt:.1f} degrees"),
        'claim': 'demonstrated: it stands where it was set' if stands else 'recorded: it did not stand',
        'scope': 'this placement, in this room'}
    journal = app.journal_for(owner)
    if not journal.add_evidence(record):
        return []
    return progression.earn(journal, registry, when)
