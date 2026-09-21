"""Contextual placement: one read-only resolver for previews and authored Use.

What is placed is the part the hand grips. A thing of several parts comes with
it on its own joints (inventory.items_of): its other parts are never taken for
somewhere to put it or for the ground under it, and its weight is all of it."""
from __future__ import annotations
import math
import interaction_points
import inventory
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


def mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return [aw*bw-ax*bx-ay*by-az*bz, aw*bx+ax*bw+ay*bz-az*by,
            aw*by-ax*bz+ay*bw+az*bx, aw*bz+ax*by-ay*bx+az*bw]


def conj(q):
    return [q[0], -q[1], -q[2], -q[3]]


def unit(q):
    """A turn as the engine reports it, made a unit again: every number in its
    reply is rounded to 1e-5, so a still body's turn compared with itself came
    out 0.46 degrees -- more than the 0.45 execute allows between looks -- and a
    chair set square on the ground was held there, still, until the hand gave
    up."""
    size = math.sqrt(sum(v * v for v in q)) or 1.0
    return [v / size for v in q]


def _reach(body, q, axis):
    """How far a part reaches from its middle along a world axis (0 x, 1 y,
    2 z), turned by q."""
    dims = body.get("dimensions_m") or [0.0, 0.0, 0.0]
    if body.get("shape") == "sphere":
        return dims[0] / 2
    return sum(abs(rotate(q, [1 if j == k else 0 for j in range(3)])[axis])*dims[k]/2 for k in range(3))


def _part_span(part, q, axis):
    """Where one exact part begins and ends along a world axis, from its body's
    position, the body turned by q: a box by its corners, a cylinder (along its
    own y, sized {diameter, length, diameter}) by its rims."""
    turn = mul(q, part.get("rotation_wxyz") or [1, 0, 0, 0])
    middle = rotate(q, part["center_local_m"])[axis]
    d = part["dimensions_m"]
    if part.get("shape") == "cylinder":
        along = rotate(turn, [0, 1, 0])[axis]
        reach = d[1]/2*abs(along) + d[0]/2*math.sqrt(max(0.0, 1.0 - along*along))
    else:
        reach = sum(abs(rotate(turn, [1 if j == k else 0 for j in range(3)])[axis])*d[k]/2 for k in range(3))
    return middle - reach, middle + reach


def _span(body, q, axis):
    """How far a part reaches below and above its middle along a world axis (0
    x, 1 y, 2 z), turned by q. An exact body by its own parts: a round wheel
    reaches as far down however far it has turned on its axle, where the box
    round it reaches 41% further at 45 degrees -- and the engine sets a part
    down by its real shape (LiveWorld::placement), so a cart carried with its
    wheels turned was previewed at one height and refused at another. Anything
    else by its box."""
    parts = body.get("rigid_parts_local")
    if parts:
        spans = [_part_span(part, q, axis) for part in parts]
        return min(s[0] for s in spans), max(s[1] for s in spans)
    reach = _reach(body, q, axis)
    return -reach, reach


# What holds a part IN PLACE on the one the hand grips: fixed to it, on a pin
# through it, or in a groove in it. Those go down with it as one shape -- a
# chair's legs under its seat, a cart's wheels under its bed. What only hangs
# from it -- on a rope, a chain, a spring -- swings free and settles by itself:
# a mace's head is not part of where the mace is set down.
HELD_IN_PLACE = ("fixing", "hinge", "slider")


def own_parts(app, name):
    """Every part of the thing a body is part of (inventory.items_of): the part
    the hand grips, and whatever comes with it."""
    thing = next((i for i in inventory.items_of(app.room.spec) if name in i["bodies"]), None)
    return set(thing["bodies"]) if thing else {name}


def carried_shape(app, name):
    """The parts that go down with the gripped one, as they stand now: the
    gripped part first, then what is fixed, pinned or slid to it."""
    joints = [j for j in app.room.spec.get("joints") or []
              if isinstance(j, dict) and j.get("kind", "hinge") in HELD_IN_PLACE]
    names, todo = [name], [name]
    while todo:
        part = todo.pop()
        for j in joints:
            for a, b in ((j.get("a"), j.get("b")), (j.get("b"), j.get("a"))):
                if a == part and b and b not in names:
                    names.append(b)
                    todo.append(b)
    bodies = {b["name"]: b for b in (app.live.session.state or {}).get("bodies", [])}
    return [bodies[n] for n in names
            if n in bodies and not bodies[n].get("anchored") and bodies[n].get("position_m")]


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
    # Every part of the thing in the hand -- the gripped one and what hangs on
    # it -- and what all of them weigh.
    own = own_parts(app, name)
    parts = [b for b in (session.state or {}).get("bodies", []) if b.get("name") in own]
    whole_kg = sum(float(b.get("mass_kg") or 0.0) for b in parts) or mover.get("mass_kg", math.inf)
    shape = carried_shape(app, name) if len(own) > 1 else [mover]
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
    def engine_check(part, on, onto, angle, square=True):
        # Set square to the ground under it (LiveWorld::placement), unless it
        # is one part of a bigger shape, which is asked as it stands in that
        # shape.
        got = act("place_check", name=part, on=on, onto=onto, yaw_deg=angle, square=square)
        # Its own other parts are not in its way: they go down with it, or hang
        # from it -- a mace's head lying where its handle goes is its head.
        if any(t.get("name") in own for t in got.get("touching") or []):
            got["touching"] = [t for t in got["touching"] if t.get("name") not in own]
            if not got["touching"] and got.get("rests_on"):
                # What the engine would have said with nothing in the way.
                got["fits"] = True
                got["why"] = ("it fits, but little of it is on the " + got["rests_on"] + ": it may tip off"
                              if got.get("supported_corners", 0) < 3 else
                              "it fits here, on the " + got["rests_on"])
        return got

    def whole_shape(first, on, onto):
        """The engine answers for one body (LiveWorld::placement). A thing of
        several parts held in place on each other goes down as ONE shape: turned
        as the gripped part would be, its footprint's middle over the point, its
        LOWEST part on the surface -- a chair's legs, not its seat, on the ground
        -- and every part asked about where it would then be."""
        g = shape[0]
        turn = mul(first["facing"], conj(g.get("orientation_wxyz", [1, 0, 0, 0])))
        placed = []
        for p in shape:
            q = mul(turn, p.get("orientation_wxyz", [1, 0, 0, 0]))
            off = rotate(turn, [p["position_m"][k]-g["position_m"][k] for k in range(3)])
            placed.append((p, off, q))
        lowest = min(off[1]+_span(p, q, 1)[0] for p, off, q in placed)
        mid = [(min(off[k]+_span(p, q, k)[0] for p, off, q in placed) +
                max(off[k]+_span(p, q, k)[1] for p, off, q in placed)) / 2 for k in (0, 2)]
        centre = [on[0]-mid[0], on[1]-lowest+.002, on[2]-mid[1]]
        for _ in range(2):
            answers, lift = [], 0.0
            for p, off, q in placed:
                at = [centre[k]+off[k] for k in range(3)]
                down = -_span(p, q, 1)[0]
                got = engine_check(p["name"], [at[0], at[1]-down, at[2]], onto, yaw_of({"orientation_wxyz": q}),
                                   square=False)
                if got.get("why") == "that is too steep to set it on":
                    return dict(first, fits=False, why=got["why"])
                # How far the engine had to lift this part clear of what it is on.
                lift = max(lift, (got.get("at_m") or at)[1]-at[1]-.002)
                answers.append((p, at, q, off[1]-down-lowest, got))
            if lift <= .003:
                break
            centre[1] += lift    # uneven ground: the whole shape, lifted as one
        touching = [t for *_, got in answers for t in got.get("touching") or []]
        feet = [got for *_, height, got in answers if height < .01]
        resting = [got for got in feet if got.get("rests_on")]
        corners = len(resting) if len(feet) >= 3 else sum(got.get("supported_corners", 0) for got in feet)
        rests_on = resting[0]["rests_on"] if resting else ""
        out = dict(first, at_m=[round(v, 5) for v in centre], rests_on=rests_on,
                   supported_corners=min(4, corners), touching=touching,
                   parts=[{"name": p["name"], "at_m": [round(v, 5) for v in at],
                           "facing": [round(v, 6) for v in q],
                           "dimensions_m": p.get("dimensions_m"), "shape": p.get("shape", "box")}
                          for p, at, q, _, _ in answers])
        # Whether it would fall over on a slope is the engine's reading of ONE
        # body (LiveWorld::placement): of the gripped part alone -- a chair's
        # flat seat, never tall -- it would say nothing true of the chair, so
        # the whole shape's answer does not carry it.
        out.pop("tipping_used", None)
        out.pop("may_fall_over", None)
        if touching:
            what = touching[0].get("name", "something")
            out.update(fits=False, why=(f"the {what} is too uneven there" if what in ("ground", "floor")
                                        else f"it would go into the {what}"))
        elif not resting:
            out.update(fits=False, why="there is nothing under it to rest on")
        elif corners < 3:
            out.update(fits=True, why=f"it fits, but little of it is on the {rests_on}: it may tip off")
        else:
            out.update(fits=True, why=f"it fits here, on the {rests_on}")
        return out

    def check(on, onto, angle, key, label):
        if not reachable(on):
            return {"fits": False, "why": "that destination is out of reach"}
        # A thing of several parts goes down as one shape, turned as its
        # gripped part stands upright (whole_shape); one thing is set square.
        result = engine_check(name, on, onto, angle, square=len(shape) == 1)
        if len(shape) > 1 and result.get("facing"):
            result = whole_shape(result, on, onto)
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
        # Not onto itself: a thing's own parts are not somewhere to put it.
        if other is None or other["name"] in own or other.get("parked"):
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
            if whole_kg > point.get("max_mass_kg", math.inf):
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
    # this ray -- all of it: the ray can meet a mace's head hanging below the
    # handle in the hand -- and never skip an unrelated obstacle.
    if hit.get("hit") and hit.get("name") in own:
        def bottom(b):
            q = b.get("orientation_wxyz", [1, 0, 0, 0])
            # An exact body by its own parts: a wheel turned on its axle reaches
            # no lower. A body of cells by its box, never less: its cells stand
            # out past a smooth outline (a ball of them past its sphere), and a
            # ray started inside the mace's head found the head, not the ground.
            if b.get("rigid_parts_local"):
                return b["position_m"][1] + _span(b, q, 1)[0]
            return b["position_m"][1] - sum(abs(rotate(q, [1 if j == k else 0 for j in range(3)])[1])
                                            * b["dimensions_m"][k]/2 for k in range(3))
        lower = min(bottom(b) for b in parts if b.get("dimensions_m")) if parts else bottom(mover)
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
    # How far off square to the ground it may be let go of (the preview's
    # facing): 8.6 degrees for a thing that stands on a broad base, a third of
    # its tipping angle for a tall thin one. At 8.6 degrees a 1.8 m shelf unit
    # on a 0.28 m base -- which tips at about 9 -- was let go leaning, and fell
    # over towards the person a second later.
    dims = current().get("dimensions_m") or [1.0, 1.0, 1.0]
    tips = math.atan2(min(dims[0], dims[2]) / 2, max(dims[1] / 2, 1e-3))
    # On a slope less of that is left: what tips it from resting square there
    # takes a lift of R (1 - cos((1 - used) tips)), which shrinks as the square
    # of what the slope leaves, while what a let-go adds does not -- the swing
    # down from being off square grows with the angle, and the hand's speed
    # and spin carry energy of their own. So the angle allowed shrinks with
    # that square, and the speed and spin with what is left: the let-go keeps
    # the same share of the margin on a slope as on flat ground. `used` is the
    # engine's tipping_used, 0 for what is not tall.
    left = 1.0 - min(max(float(plan.get("tipping_used") or 0.0), 0.0), 0.95)
    half_turn = min(.075, tips / 6) * left * left
    # What hangs from it has to have settled too. A mace's head still swinging
    # on its chain when the handle was let go dragged the handle after it:
    # measured in the Explorer (tests/explore_visual_qa.py), a handle set down
    # exactly on the preview was pulled 0.47 m off it. So the hand keeps it on
    # the spot while the rest comes to rest -- for a while: a part that will not
    # settle by then is let go with it rather than the put-down refused.
    rest = own_parts(app, name) - {name}
    settle_until = time.monotonic() + (2.5 if rest else 0.0)
    # And the time to be that square and still: running out sets it down on the
    # ground in front instead (server.put_it_down), which no tall thing survives.
    until = time.monotonic()+(3.0 if rest else 2.0)/left
    was = None
    facing = unit(plan["facing"])
    while time.monotonic() < until:
        b = current()
        q = unit(b["orientation_wxyz"])
        aligned = abs(sum(q[k]*facing[k] for k in range(4))) >= math.cos(half_turn)
        # And STILL: let go of a thing that is still swinging and it goes on
        # swinging. The hand reports how fast the point it grips is moving;
        # the turn is compared across two looks 30 ms apart.
        grip = ((session.state or {}).get("hand") or {}).get("grip_velocity_m_s") or [0.0, 0.0, 0.0]
        still = math.hypot(*grip) < .1 * left and was is not None and \
            abs(sum(q[k]*was[k] for k in range(4))) >= math.cos(.004 * left)
        was = q
        if math.dist(b["position_m"], end) <= .05 and aligned and still:
            swinging = [p for p in session.state.get("bodies", []) if p.get("name") in rest and
                        math.hypot(*(p.get("velocity_m_s") or [0.0, 0.0, 0.0])) >= .1]
            if swinging and time.monotonic() < settle_until:
                time.sleep(.03)
                continue
            now = resolve(app, {**request, "expected": plan["target"]})
            if not now.get("fits"):
                return "", now["why"]
            act("release")
            return "placed " + name + " on " + plan["label"], None
        time.sleep(.03)
    act("cancel_stroke")
    return "", "the object could not reach the preview; it is still held"
