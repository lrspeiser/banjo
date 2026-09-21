"""Contextual placement: one read-only resolver for previews and authored Use."""
from __future__ import annotations
import math
import interaction_points
import world_chat

REACH_M = 3.0
MOVE_TOLERANCE_M = 0.03


def rotate(q, v):
    w, x, y, z = q
    return [(1-2*(y*y+z*z))*v[0]+2*(x*y-w*z)*v[1]+2*(x*z+w*y)*v[2],
            2*(x*y+w*z)*v[0]+(1-2*(x*x+z*z))*v[1]+2*(y*z-w*x)*v[2],
            2*(x*z-w*y)*v[0]+2*(y*z+w*x)*v[1]+(1-2*(x*x+y*y))*v[2]]


def yaw_of(body):
    x, _, z = rotate(body.get("orientation_wxyz", [1,0,0,0]), [1,0,0])
    return math.degrees(math.atan2(-z, x))


def resolve(app, body):
    if not isinstance(body, dict):
        raise ValueError("placement needs an object request")
    session = app.live.session
    if not session or body.get("session") != session.id:
        raise ValueError("placement belongs to a different world session")
    person = world_chat.where_the_person_is(body.get("person"))
    if person is None:
        raise ValueError("placement needs the person's position and facing")
    bodies = {b["name"]: b for b in (session.state or {}).get("bodies", [])}
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("placement needs an object name")
    mover = bodies.get(name)
    if mover is None or mover.get("anchored") or mover.get("parked"):
        raise ValueError("placement needs a movable object in the world")
    yaw = body.get("yaw_deg", yaw_of(mover))
    if type(yaw) not in (int, float) or not math.isfinite(yaw):
        raise ValueError("placement yaw_deg must be finite")
    feet, facing = person["standing_m"], person["facing"]
    eyes = person.get("eyes_m", [feet[0], feet[1]+1.62, feet[2]])
    front = [feet[k]+facing[k] for k in range(3)]
    # Where they are looking, when the page says and it is within reach and in
    # front of them: a thing goes down where the sight is, not a metre ahead of
    # the feet whatever the sight is on -- which drew the preview off to one
    # side of where the person was looking.
    aim = person.get("aim_m")
    # How far from `front` a receiving point may be and still be chosen. A
    # metre and a quarter when `front` is only a guess at intent (a metre ahead
    # of the feet); when the page says where the sight actually is, a surface
    # has to be under it or right beside it -- otherwise looking at the ground
    # placed the thing on a stool's seat a metre away.
    near = 1.25
    if aim is not None and math.dist(aim, eyes) <= REACH_M and \
            (aim[0]-feet[0])*facing[0]+(aim[2]-feet[2])*facing[2] >= 0.1:
        front = list(aim)
        near = 0.4
    def act(op, **args):
        return app.live.act({"session": session.id, "op": op, **args})
    def reachable(on):
        d = [on[k]-feet[k] for k in range(3)]
        return math.dist(on, eyes) <= REACH_M and d[0]*facing[0]+d[2]*facing[2] >= 0.1
    def check(on, onto, angle, key, label):
        if not reachable(on):
            return {"fits": False, "why": "that destination is out of reach"}
        result = act("place_check", name=name, on=on, onto=onto, yaw_deg=angle)
        if key != "ground" and result.get("supported_corners", 0) < 3:
            result.update(fits=False, why="the receiving area no longer supports the item")
        result.update(on=on, onto=onto, yaw_deg=angle,
                      target={"body": onto, "id": key, "on": on, "yaw_deg": angle},
                      label=label)
        return result

    # At most 32 local points per body; distance and capacity reject cheaply.
    candidates = []
    for record in app.room.spec.get("interaction_points", []):
        other = bodies.get(record["body"])
        if other is None or other["name"] == name or other.get("parked"):
            continue
        q = other.get("orientation_wxyz", [1,0,0,0])
        if rotate(q, [0,1,0])[1] < math.cos(math.radians(15)):
            continue  # tipped receptacles cannot promise an upright receiving area
        for point in record["points"]:
            if point["kind"] not in ("surface", "container"):
                continue
            offset = rotate(q, point["position_m"])
            on = [other["position_m"][k]+offset[k] for k in range(3)]
            if not reachable(on):
                continue
            horizontal = math.hypot(on[0]-front[0], on[2]-front[2])
            aimed = person.get("looking_at") == other["name"]
            if horizontal > near and not aimed:
                continue
            size = point["size_m"]
            dims = mover.get("dimensions_m", [math.inf]*3)
            # Item aligns to point yaw. Project its upright footprint into the
            # receiving body's frame; declared space does not enlarge geometry.
            angle = math.radians(point.get("yaw_deg", 0))
            need = [abs(math.cos(angle))*dims[0]+abs(math.sin(angle))*dims[2],
                    dims[1], abs(math.sin(angle))*dims[0]+abs(math.cos(angle))*dims[2]]
            if any(need[k] > size[k]+1e-6 for k in range(3)):
                continue
            if mover.get("mass_kg", math.inf) > point.get("max_mass_kg", math.inf):
                continue
            candidates.append((0 if aimed else 1, horizontal, other["name"], point["id"],
                               on, yaw_of(other)+point.get("yaw_deg", 0), point["label"]))
    expected = body.get("expected")
    if expected is not None and (not isinstance(expected, dict) or
            set(expected) != {"body", "id", "on", "yaw_deg"} or
            not isinstance(expected["body"], str) or not isinstance(expected["id"], str)):
        raise ValueError("expected must be the preview's target")
    if expected is not None:
        old = interaction_points.vector(expected["on"], "expected.on", limit=1000)
        old_yaw = expected["yaw_deg"]
        if type(old_yaw) not in (int, float) or not math.isfinite(old_yaw):
            raise ValueError("expected yaw_deg must be finite")
        if expected["id"] == "ground":
            answer = check(old, expected["body"], old_yaw, "ground", "Ground in front")
        else:
            found = next((c for c in candidates if c[2:4] == (expected["body"], expected["id"])), None)
            if found is None:
                return {"fits": False, "why": "that destination is no longer available; choose the new preview"}
            _, _, onto, key, on, angle, label = found
            if math.dist(old, on) > MOVE_TOLERANCE_M or abs((angle-old_yaw+180)%360-180) > 2:
                return {"fits": False, "why": "the destination moved; choose the new preview"}
            answer = check(on, onto, angle, key, label)
        return answer

    for _, _, onto, key, on, angle, label in sorted(candidates)[:8]:
        answer = check(on, onto, angle, key, label)
        if answer.get("fits") and answer.get("supported_corners", 0) >= 3:
            answer["why"] = "Place on " + label + " (" + onto + ")"
            return answer
    # Ground is found by a real downward ray. A body in front is an obstacle,
    # not an invented receptacle or permission to place on its bounding box.
    hit = act("pick", **{"from": [front[0], eyes[1], front[2]], "dir": [0,-1,0], "max_m": REACH_M})
    # Start below the held object's actual lower extent when it intercepts
    # this ray; never skip an unrelated obstacle.
    if hit.get("hit") and hit.get("name") == name:
        lower = mover["position_m"][1] - sum(abs(rotate(mover.get("orientation_wxyz",[1,0,0,0]),
                    [1 if j == k else 0 for j in range(3)])[1])*mover["dimensions_m"][k]/2 for k in range(3))
        hit = act("pick", **{"from": [front[0], lower-.01, front[2]], "dir": [0,-1,0], "max_m": REACH_M})
    if (not hit.get("hit") or (hit.get("name") in bodies and
            (not bodies[hit["name"]].get("anchored") or hit["point_m"][1] > feet[1]+.25))):
        return {"fits": False, "why": "no clear receiving point or ground in front"}
    # Named anchored ground slabs are valid support; keep their identity.
    onto = hit.get("name") or ""
    answer = check(hit["point_m"], onto, yaw, "ground", "Ground in front")
    if answer.get("target"):
        answer["target"]["id"] = "ground"
    return answer

def execute(app, name, person, stroke, expected=None, speed=.8, direct=False):
    """Place with the bounded native hand; the host continues physics ticks.

    `speed` is the hand's, along the path, in m/s. The default is the Use
    action's measured pace; a page putting something down where a person is
    looking asks for more (server.put_it_down).

    `direct` lets the hand go straight down to just above the spot when the
    spot is below it, instead of across at its own height and then down --
    about a quarter less path from the hip to the ground in front. A spot
    ABOVE the hand still goes up first, so it cannot clip the edge of a table
    it is being lifted onto."""
    import time
    session = app.live.session
    hand = (session.state or {}).get("hand") or {}
    if not hand.get("holding") or (hand.get("name") or hand.get("holding")) != name:
        return "", "pick up the object before placing it"
    request = {"session": session.id, "name": name, "person": person}
    if expected is not None: request["expected"] = expected
    plan = resolve(app, request)
    if not plan.get("fits"):
        return "", plan["why"]
    def act(op, **args):
        return app.live.act({"session": session.id, "op": op, **args})
    def current():
        return next(b for b in session.state["bodies"] if b["name"] == name)
    start = list(current()["position_m"])
    # Re-grip at COM, so the path and the checked destination use the same
    # reference. Wield/hand_q apply finite forces and torques, never set a pose.
    act("wield", name=name, grip=start)
    act("step", dt=1/240, n=1, hand_q=plan["facing"])
    end = plan["at_m"]
    over = max(start[1], end[1]+.2)
    if direct and start[1] >= end[1]+.2:
        path = [start, [end[0],end[1]+.2,end[2]], end]
    else:
        path = [start, [start[0],over,start[2]], [end[0],over,end[2]], end]
    outcome = stroke(app, path, speed)
    if outcome not in ("reached", "blocked"):
        act("cancel_stroke")
        return "", "placement stroke " + outcome + "; the item is still held"
    # How far off upright it may be let go of: 8.6 degrees for a thing that
    # stands on a broad base, a third of its tipping angle for a tall thin one.
    # At 8.6 degrees a 1.8 m shelf unit on a 0.28 m base -- which tips at about
    # 9 -- was let go leaning, and fell over towards the person a second later.
    dims = current().get("dimensions_m") or [1.0, 1.0, 1.0]
    tips = math.atan2(min(dims[0], dims[2]) / 2, max(dims[1] / 2, 1e-3))
    half_turn = min(.075, tips / 6)
    until = time.monotonic()+2.0
    was = None
    while time.monotonic() < until:
        b = current()
        q = b["orientation_wxyz"]
        aligned = abs(sum(q[k]*plan["facing"][k] for k in range(4))) >= math.cos(half_turn)
        # And STILL: let go of a thing that is still swinging and it goes on
        # swinging. The hand reports how fast the point it grips is moving;
        # the turn is compared across two looks 30 ms apart.
        grip = ((session.state or {}).get("hand") or {}).get("grip_velocity_m_s") or [0.0, 0.0, 0.0]
        still = math.hypot(*grip) < .1 and was is not None and \
            abs(sum(q[k]*was[k] for k in range(4))) >= math.cos(.004)
        was = q
        if math.dist(b["position_m"], end) <= .05 and aligned and still:
            now = resolve(app, {**request, "expected": plan["target"]})
            if not now.get("fits"):
                return "", now["why"]
            act("release")
            return "placed " + name + " on " + plan["label"], None
        time.sleep(.03)
    act("cancel_stroke")
    return "", "the object could not reach the preview; it is still held"
