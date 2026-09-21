"""Contextual destinations, physical admission, and saved authoring metadata."""
from copy import deepcopy
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/"playground"), str(ROOT/"mcp")]
import interaction_points as points
import placement
import fracture_lab
import world_room
import live_session
import room_world
from mcp import workshop, workshop_graph, product_contract
from mcp import interaction_points as workshop_points

CARGO = {"id": "cargo", "kind": "container", "label": "Cart interior",
         "position_m": [0,.2,0], "size_m": [.7,.6,.7], "max_mass_kg": 10}
PERSON = {"standing_m": [0,0,2], "eyes_m": [0,1.62,2], "facing": [0,0,-1]}
ENGINE = os.environ.get("BANJO_LIVE_ENGINE")


class PointsContract(unittest.TestCase):
    def test_invalid_declarations_do_not_mutate_input(self):
        for change in ({"position_m":[0,math.nan,0]}, {"size_m":[1,-1,1]},
                       {"kind":"teleport"}, {"id":"ground"}, {"max_mass_kg":True}, {"velocity_m_s":3}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                points.checked([{**CARGO, **change}])
        with self.assertRaises(ValueError): points.checked([CARGO,CARGO])
        self.assertEqual(len(points.checked([CARGO])), 3)

    def test_workshop_default_points_and_authored_points_survive_rebuild(self):
        d = workshop.assemble("cart")
        deck = next(p for p in workshop_points.for_design(d) if p["id"] == "deck")
        self.assertAlmostEqual(deck["position_m"][1], d.parameters["deck_height_m"])
        d = workshop.assemble("table", parameters={"interaction_points":[CARGO],
                               "primary_use":{"label":"Place gently","steps":[{"do":"place"}]}})
        rebuilt = workshop.assemble("table", parameters={**d.parameters, "width_m":1.4})
        graph = workshop_graph.product(rebuilt).described()
        contract = product_contract.compile_contract(graph)
        self.assertEqual(next(c for c in graph["controls"] if c["kind"]=="interaction-points")["points"][0]["id"], "cargo")
        self.assertEqual(contract["controls"], graph["controls"])
        mapped = workshop_points.installed(rebuilt, "placed", [.2,.3,.4])
        self.assertEqual(mapped["points"][0]["position_m"], [-.2, -.09999999999999998, -.4])

    def test_saved_room_default_points_and_stale_body_rejected(self):
        spec = dict(world_room.Room("yard").spec)
        checked = fracture_lab.validate(spec)
        self.assertTrue(checked["interaction_points"])
        self.assertTrue(all({"use","grip"} <= {p["kind"] for p in r["points"]}
                            for r in checked["interaction_points"]))
        spec["interaction_points"] = [{"body":"missing", "points":[CARGO]}]
        with self.assertRaises(ValueError): fracture_lab.validate(spec)

    def test_workshop_chat_authors_points_atomically(self):
        import workshop_chat
        # Same public conversational tool path as the saved Use program.
        candidate = {"kind":"table","parameters":{},"component_overrides":{}}
        with patch.object(workshop_chat, "_refresh"):
            agent = workshop_chat._State(SimpleNamespace(), candidate, None, ["oak"], [])
            answer = agent.execute("define_interaction_points", {"points":[CARGO]})
            self.assertEqual(answer["points"][0]["id"],"cargo")
            before = deepcopy(agent.design.parameters)
            with self.assertRaises(ValueError):
                agent.execute("define_interaction_points", {"points":[{**CARGO,"size_m":[0,1,1]}]})
            self.assertEqual(before,agent.design.parameters)



class FakeLive:
    def __init__(self):
        self.session = SimpleNamespace(id="s", state={"bodies":[
            {"name":"item", "position_m":[.5,1,1.5], "dimensions_m":[.2,.2,.2], "mass_kg":1,
             "orientation_wxyz":[1,0,0,0]},
            {"name":"cart", "position_m":[0,.2,1], "dimensions_m":[.8,.4,.8],
             "orientation_wxyz":[1,0,0,0]}]})
        self.calls = []
        self.block = False
    def act(self, req):
        self.calls.append(req)
        if req["op"] == "pick":
            return {"hit":True, "point_m":[req["from"][0],0,req["from"][2]], "name":""}
        if req["op"] == "place_check":
            return {"fits":not(self.block and req["onto"]=="cart"), "why":"blocked" if self.block else "fits",
                    "supported_corners":4, "at_m":[req["on"][0],req["on"][1]+.102,req["on"][2]],
                    "facing":[1,0,0,0]}
        raise AssertionError(req)


class DestinationResolution(unittest.TestCase):
    def setUp(self):
        self.live = FakeLive()
        self.app = SimpleNamespace(live=self.live, room=SimpleNamespace(spec={
            "interaction_points":[{"body":"cart", "points":points.checked([CARGO])}]}))
        self.request = {"session":"s", "name":"item", "person":PERSON}
    def test_prefers_cargo_and_preview_is_read_only(self):
        before = deepcopy(self.live.session.state)
        answer = placement.resolve(self.app,self.request)
        self.assertEqual(answer["target"]["id"],"cargo")
        self.assertEqual(answer["on"],[0,.4,1])
        self.assertEqual(before,self.live.session.state)
        self.assertEqual({c["op"] for c in self.live.calls},{"place_check"})
    def test_capacity_blockage_and_behind_fall_back_to_ground(self):
        for kind in ("size","mass","block","behind"):
            with self.subTest(kind=kind):
                self.setUp()
                mover, cart = self.live.session.state["bodies"]
                if kind=="size": mover["dimensions_m"]=[2,.2,.2]
                if kind=="mass": mover["mass_kg"]=11
                if kind=="block": self.live.block=True
                if kind=="behind": cart["position_m"][2]=2.3
                self.assertEqual(placement.resolve(self.app,self.request)["target"]["id"],"ground")
    def test_rotated_local_point_and_stale_confirmation(self):
        cart=self.live.session.state["bodies"][1]
        cart["orientation_wxyz"]=[math.sqrt(.5),0,math.sqrt(.5),0]
        self.app.room.spec["interaction_points"][0]["points"][0]["position_m"]=[.1,.2,0]
        answer=placement.resolve(self.app,self.request)
        self.assertAlmostEqual(answer["on"][2],.9)
        self.assertAlmostEqual(answer["yaw_deg"],90)
        cart["position_m"][0]+=.1
        refused=placement.resolve(self.app,{**self.request,"expected":answer["target"]})
        self.assertFalse(refused["fits"])
        self.assertIn("moved",refused["why"])
    def test_no_silent_retarget_when_cargo_fills(self):
        answer=placement.resolve(self.app,self.request)
        self.live.block=True
        refused=placement.resolve(self.app,{**self.request,"expected":answer["target"]})
        self.assertFalse(refused["fits"])
    def test_ground_confirmation_and_wrong_session(self):
        self.app.room.spec["interaction_points"]=[]
        a=placement.resolve(self.app,self.request)
        self.assertTrue(placement.resolve(self.app,{**self.request,"expected":a["target"]})["fits"])
        with self.assertRaises(ValueError):
            placement.resolve(self.app,{**self.request,"session":"old"})


@unittest.skipUnless(os.environ.get("BANJO_LIBRARY"), "BANJO_LIBRARY required")
class MCPPoints(unittest.TestCase):
    def test_authoring_roundtrip_copy_and_atomic_rejection(self):
        spec = dict(world_room.Room("yard").spec)
        spec["bodies"].append({"name":"cart","shape":"box","material":"oak",
                              "size_mm":[400,400,400],"center_mm":[0,200,0]})
        wid = room_world.open_room(spec); self.addCleanup(room_world.close_room,wid)
        kept = room_world.call(wid,"define_interaction_points",{"name":"cart","points":[CARGO]})
        self.assertNotIn("error",kept)
        before = deepcopy(room_world.entry_of(wid)["interaction_points"])
        bad = room_world.call(wid,"define_interaction_points",{"name":"cart","points":[{**CARGO,"size_m":[-1,1,1]}]})
        self.assertIn("error",bad)
        self.assertEqual(before,room_world.entry_of(wid)["interaction_points"])
        copied = room_world.call(wid,"duplicate",{"names":["cart"],"prefix":"copy","offset_m":[2,0,0]})
        self.assertNotIn("error",copied,copied)
        exported = room_world.export_spec(room_world.entry_of(wid))
        again = room_world.open_room(exported); self.addCleanup(room_world.close_room,again)
        read = room_world.call(again,"define_interaction_points",{"name":"cart"})
        self.assertEqual(kept["points"],read["points"])
        copy = room_world.call(again,"define_interaction_points",{"name":copied["copied"][0]})
        self.assertEqual(kept["points"],copy["points"])


@unittest.skipUnless(ENGINE and Path(ENGINE).is_file(), "BANJO_LIVE_ENGINE required")
class NativePlacement(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        live=live_session.Live(); self.addCleanup(live.shutdown)
        room=world_room.Room("yard")
        room.spec["cell_m"]=.05
        room.spec["bodies"]=[
            {"name":"slab","shape":"box","material":"concrete","size_mm":[3000,100,3000],
             "center_mm":[0,50,500],"anchored":True},
            {"name":"cart","shape":"box","material":"oak","size_mm":[800,400,800],
             "center_mm":[0,300,0],"anchored":True},
            {"name":"item","shape":"box","material":"oak","size_mm":[100,100,100],
             "center_mm":[600,800,1000]}]
        room.spec["interaction_points"]=[{"body":"cart","points":points.checked([CARGO])}]
        self.app=SimpleNamespace(live=live, room=room, engine_path=Path(ENGINE),
                                 runs_path=Path(tmp.name)/"runs",live_holder="world")
        live.open(self.app,{"spec":room.spec})
        self.person={**PERSON,"standing_m":[0,.1,1.5],"eyes_m":[0,1.72,1.5]}
        self.req={"session":live.session.id,"name":"item","person":self.person}
    def test_native_geometry_rejects_invented_receiver_and_accepts_real_top(self):
        a=placement.resolve(self.app,self.req)
        self.assertTrue(a["fits"],a)
        self.assertEqual(a["onto"],"cart")
        self.assertAlmostEqual(a["at_m"][1],.552,places=3)
        self.app.room.spec["interaction_points"][0]["points"][0]["position_m"][1]=.5
        a=placement.resolve(self.app,self.req)
        self.assertFalse(a.get("onto")=="cart" and a["target"]["id"]=="cargo")
    def test_saved_place_program_reaches_real_receiver(self):
        import server
        live=self.app.live; sid=live.session.id
        live.act({"session":sid,"op":"wield","name":"item","grip":[.6,.8,1]})
        self.app.room.spec["actions"]=[{"body":"item","primary":True,"label":"Place gently","steps":[{"do":"place"}]}]
        stop=threading.Event(); errors=[]
        def tick():
            try:
                while not stop.is_set():
                    live.act({"session":sid,"op":"step","dt":1/240,"n":4})
                    time.sleep(.01)
            except Exception as e: errors.append(str(e))
        t=threading.Thread(target=tick); t.start()
        try: a=server.run_action(self.app,{"object":"item","primary":True,"person":self.person})
        finally: stop.set(); t.join(5)
        self.assertFalse(errors)
        self.assertFalse(a.get("refused"),a)
        self.assertFalse(live.session.state["hand"]["holding"])
        b=next(b for b in live.session.state["bodies"] if b["name"]=="item")
        self.assertLess(math.dist(b["position_m"],[0,.552,0]),.05)

    def test_real_compound_container_floor_and_occupied_space(self):
        spec=deepcopy(self.app.room.spec)
        cart=next(b for b in spec["bodies"] if b["name"]=="cart")
        cart.update(size_mm=[800,100,800],center_mm=[0,450,0],join="cart")
        for i,x in enumerate((-.375,.375)):
            spec["bodies"].append({"name":"wall"+str(i),"shape":"box","material":"oak",
                "size_mm":[50,300,800],"center_mm":[x*1000,650,0],"join":"cart","anchored":True})
        self.app.room.spec=spec
        self.app.live.open(self.app,{"spec":spec})
        state=self.app.live.session.state
        body=next(b for b in state["bodies"] if b["name"]=="cart")
        spec["interaction_points"][0]["points"][0]["position_m"]=[0,.5-body["position_m"][1],0]
        req={**self.req,"session":self.app.live.session.id}
        a=placement.resolve(self.app,req)
        self.assertEqual(a["target"]["id"],"cargo",a)
        self.assertAlmostEqual(a["at_m"][1],.552,places=3)
        spec["bodies"].append({"name":"cargo already here","shape":"box","material":"oak",
             "size_mm":[200,200,200],"center_mm":[0,600,0]})
        self.app.live.open(self.app,{"spec":spec})
        req["session"]=self.app.live.session.id
        a=placement.resolve(self.app,req)
        self.assertFalse(a.get("target",{}).get("id")=="cargo",a)


@unittest.skipUnless(ENGINE and Path(ENGINE).is_file(), "BANJO_LIVE_ENGINE required")
class TallThingOnASlope(unittest.TestCase):
    """A bookcase 0.9 m wide, 1.8 m tall and 0.3 m deep goes over across its
    narrow side on a slope of 0.15 / 0.9 (9.5 degrees). The engine says so of
    6 degrees and refuses 12 (tests/placement_tests.cpp); this is that answer
    reaching the page, which draws the preview amber on `may_fall_over`."""
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        live=live_session.Live(); self.addCleanup(live.shutdown)
        room=world_room.Room("yard")
        room.spec["cell_m"]=.05
        room.spec["bodies"]=[
            {"name":"bookcase","shape":"box","material":"oak","size_mm":[900,1800,300],
             "center_mm":[0,900,-3000]}]+[
            {"name":f"ramp {d}","shape":"box","material":"concrete","size_mm":[1500,100,1500],
             "center_mm":[x,600,0],"rotation_deg":[d,0,0],"anchored":True}
            for x,d in ((-1500,6),(1500,12))]
        room.spec["interaction_points"]=[]
        self.app=SimpleNamespace(live=live, room=room, engine_path=Path(ENGINE),
                                 runs_path=Path(tmp.name)/"runs",live_holder="world")
        live.open(self.app,{"spec":room.spec})
        self.sid=live.session.id
    def ask(self, op, **args):
        return self.app.live.act({"session":self.sid,"op":op,**args})
    def test_the_reply_says_how_near_it_is_to_falling_over(self):
        for x,degrees,fits in ((-1.5,6,True),(1.5,12,False)):
            with self.subTest(degrees=degrees):
                top=self.ask("pick",**{"from":[x,3,0],"dir":[0,-1,0]})
                self.assertEqual(top["name"],f"ramp {degrees}")
                a=self.ask("place_check",name="bookcase",on=top["point_m"],onto=top["name"])
                self.assertIs(a["fits"],fits,a)
                self.assertIs(a["may_fall_over"],True,a)
                self.assertAlmostEqual(a["tipping_used"],.9*math.tan(math.radians(degrees))/.15,places=2)
                self.assertIn("fall over",a["why"])
    def test_it_is_set_square_to_the_slope_unless_asked_upright(self):
        # The 6 degree ramp is turned about x: its top faces (0, cos 6, sin 6).
        # Square to it, the bookcase's own up is the ramp's (to the reply's 1e-5
        # rounding); asked upright -- as a part of a bigger shape is -- it is not
        # turned off the vertical at all.
        top=self.ask("pick",**{"from":[-1.5,3,0],"dir":[0,-1,0]})
        ramp=[0,math.cos(math.radians(6)),math.sin(math.radians(6))]
        a=self.ask("place_check",name="bookcase",on=top["point_m"],onto=top["name"])
        up=placement.rotate(a["facing"],[0,1,0])
        self.assertGreater(sum(u*r for u,r in zip(up,ramp)),math.cos(math.radians(.05)),a)
        self.assertEqual(a["supported_corners"],4,a)
        b=self.ask("place_check",name="bookcase",on=top["point_m"],onto=top["name"],square=False)
        self.assertAlmostEqual(placement.rotate(b["facing"],[0,1,0])[1],1.0,places=9)
    def test_the_preview_carries_it(self):
        # Standing in front of the 6 degree ramp, looking at its middle: its
        # top is under 0.25 m above the feet, so the resolver takes it as ground.
        person={"standing_m":[-1.5,.5,1.2],"eyes_m":[-1.5,2.12,1.2],"facing":[0,0,-1],
                "aim_m":[-1.5,.65,0]}
        a=placement.resolve(self.app,{"session":self.sid,"name":"bookcase","person":person})
        self.assertEqual((a["target"]["id"],a["onto"]),("ground","ramp 6"),a)
        self.assertTrue(a["fits"] and a["may_fall_over"],a)
        self.assertEqual(a["why"],"it fits, but it is tall for that slope: it may fall over")
        # And the preview stands it square to the ramp, which the hand follows.
        self.assertAlmostEqual(placement.rotate(a["facing"],[0,1,0])[2],math.sin(math.radians(6)),places=4)



if __name__=="__main__": unittest.main()
