"""Nearby recovery uses the native bounded grip, with a durable acknowledgement."""
from __future__ import annotations

import math
from uuid import uuid4

import player_world
import world_chat
from live_session import LiveError

REACH_M = 2.0


def request(app, player, body, keep):
    if not player:
        raise ValueError("Join a world before recovering a rover")
    session = app.live.session
    if session is None:
        raise ValueError("The world is not open")
    action = body.get("recovery")
    if not isinstance(action,str) or action not in {"start", "release"}:
        raise ValueError("Recovery is start or release")
    program_id = body.get("program")
    if not isinstance(program_id, int) or isinstance(program_id, bool):
        raise ValueError("Select a rover to recover")
    # Fresh native poses/parts/hand ownership, under the caller's world state lock.
    app.live.act({"session":session.id,"op":"poses","actor":player})
    state = session.state
    program = next((p for p in state.get("machines",{}).get("programs",[])
                    if p["id"] == program_id and p.get("kind") == "roam"), None)
    if not program:
        raise ValueError("Select a wheeled rover to recover")
    root = program["body"]
    parts = set(program.get("parts") or []) | {root}
    own = (state.get("player_hands") or {}).get(player) or {}

    def act(op, **args):
        return app.live.act({"session":session.id,"actor":player,"op":op,**args})

    def save():
        if not keep(app,"player rover recovery"):
            raise OSError("The recovery checkpoint could not be saved")

    if action == "release":
        if own.get("holding") and not (own["holding"] == root and own.get("mode") == "grip"):
            raise ValueError("Your hand is holding another item")
        if own.get("holding"):
            act("release")
        try:
            save()
        except OSError as error:
            raise OSError("Rover released, but this change was not saved. Retry Release before leaving.") from error
        return {"recovering":False,"program":program,"hand":{},"state":session.state}

    if own.get("holding") and not (own["holding"] == root and own.get("mode") == "grip"):
        raise ValueError("Put down what you are holding before recovering the rover")
    hands = dict(state.get("player_hands") or {})
    if any(ident != player and hand.get("holding") in parts for ident,hand in hands.items()):
        raise ValueError("Another player is holding part of this rover")
    rover = next((b for b in state.get("bodies",[]) if b["name"] == root), None)
    if not rover or rover.get("anchored") or rover.get("parked"):
        raise ValueError("That rover is not available in the world")
    already = own.get("holding") == root and own.get("mode") == "grip"
    carried = (state.get("terrain") or {}).get("carried") or {}
    if not already and carried.get("available_kg",math.inf)<rover.get("mass_kg",0):
        raise ValueError("Empty some carried ground material or your bag before taking hold of the rover")
    person = world_chat.where_the_person_is(body.get("person"))
    if not person or not person.get("eyes_m"):
        raise ValueError("Approach the rover before taking hold")
    eyes = person["eyes_m"]
    position = rover["position_m"]
    direction = [position[i]-eyes[i] for i in range(3)]
    hit = act("pick", **{"from":eyes,"dir":direction,"max_m":REACH_M})
    if not hit.get("hit") or hit.get("name") != root:
        raise ValueError("Get within 2 m of the chassis with a clear view to take hold")
    grip = hit["point_m"]
    if math.dist(grip,eyes)>REACH_M+1e-6:
        raise ValueError("Get within 2 m of the chassis to take hold")
    player_world.update_pose(app,player,person)
    act("run",program=program_id,power=False,sender="recovery "+uuid4().hex,seq=1)
    if not already:
        try:
            act("wield",name=root,grip=grip)
        except LiveError as error:
            save()
            raise ValueError("Rover stopped, but the native grip was refused: "+str(error)) from error
    try:
        save()
    except OSError as error:
        # No step has happened under the state lock. A failed first acquisition
        # leaves no invisible grip; the program stays stopped for a safe retry.
        if not already:
            act("release")
        raise OSError("Recovery was not saved. Rover stopped; " +
                      ("your existing grip remains." if already else "grip released. Retry taking hold.")) from error
    hand = (session.state.get("player_hands") or {}).get(player) or {}
    force = act("hand")
    mass = sum(b.get("mass_kg",0) for b in state.get("bodies",[]) if b["name"] in parts)
    stopped = next(p for p in session.state["machines"]["programs"] if p["id"] == program_id)
    return {"recovering":True,"program":stopped,"hand":hand,"assembly_mass_kg":mass,
            "strength_n":force.get("strength_n"),"torque_n_m":force.get("torque_n_m"),
            "state":session.state}
