"""Reproducible native assembly and hand-strike experiment; no scripted damage."""
from __future__ import annotations
import argparse, json, os, sys, threading, time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"mcp"),str(ROOT/"playground")]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--engine",type=Path,required=True)
    ap.add_argument("--out",type=Path,default=ROOT/"build/assembly-impact")
    ap.add_argument("--panel-material",choices=["glass","oak","iron"],default="glass")
    args=ap.parse_args()
    engine=args.engine.resolve(); out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    os.environ["BANJO_LIBRARY"]=str(engine.parent/"banjo.dll")
    import banjo_mcp as m, room_world, world_room, live_session, room_store, server
    transcript=[]
    def tool(operation,**kw):
        answer=m.HANDLERS[operation](kw)
        transcript.append({"tool":operation,"arguments":kw,"answer":m.json_safe(answer)})
        return answer
    def box(name,material,size,at,anchored=False):
        return dict(name=name,shape="box",material=material,size_m=size,position_m=at,anchored=anchored)
    def author(material="glass"):
        objects=[]
        for i,x in enumerate((-1.04,-.46,.46,1.04)):
            objects.append(box("frame "+str(i),"oak",[.04,1.4,.06],[x,.7,0],True))
        objects.append(box("lintel","oak",[2.16,.04,.06],[0,1.44,0],True))
        for side,x in (("left",-.75),("right",.75)):
            objects.append(box(side+" pane",material,[.44,.8,.02],[x,.76,0]))
            for row in range(2):
                for col in range(2):
                    objects.append(box(f"{side} brick {row}-{col}","concrete",[.24,.12,.12],
                                       [x+(col-.5)*.25,.06+row*.125,0]))
        objects.append(box("door","oak",[.8,1.28,.04],[0,.72,.1]))
        for i,y in enumerate((.35,1.05)):
            objects.append(box("iron hinge "+str(i),"iron",[.04,.08,.04],[-.46,y,.1],True))
        # A real two-material tool. Joined cells would silently homogenize material.
        objects.append(box("sledgehammer","oak",[.04,.64,.04],[-.75,1.12,.65]))
        objects.append(box("sledge head","iron",[.16,.08,.08],[-.75,.76,.65]))
        wid=tool("create_world",objects=objects,cell_size_m=.02)["world_id"]
        entry=m.WORLDS[wid]; entry["room"]={**world_room.yard(),"cell_m":.02}
        for side in ("left","right"):
            frame="frame 0" if side=="left" else "frame 3"
            x=-.75 if side=="left" else .75
            tool("fix",world_id=wid,a=frame,b=side+" pane",at_m=[x,.38,0],
                 axis=[0,0,1],holds_tension_n=2500,holds_shear_n=2500)
            for row in range(2):
                for col in range(2):
                    name=f"{side} brick {row}-{col}"
                    parent=frame if row==0 else f"{side} brick 0-{col}"
                    tool("fix",world_id=wid,a=parent,b=name,at_m=[x+(col-.5)*.25,row*.125,0],
                         axis=[0,1,0],holds_tension_n=1500,holds_shear_n=1500)
        for i,y in enumerate((.35,1.05)):
            tool("hinge",world_id=wid,a="iron hinge "+str(i),b="door",at_m=[-.42,y,.1],
                 axis=[0,1,0],lower_deg=-105,upper_deg=105,friction_n_m=.3)
        tool("fix",world_id=wid,a="sledgehammer",b="sledge head",at_m=[-.75,.8,.65],
             axis=[0,1,0],holds_tension_n=10000,holds_shear_n=10000)
        tool("offer_actions",world_id=wid,name="sledgehammer",actions=[
            {"label":"Strike with sledgehammer","primary":True,
             "steps":[{"do":"strike","distance_m":.8,"speed_m_s":5}]}])
        tool("offer_actions",world_id=wid,name="door",actions=[
            {"label":"Open door","primary":True,"steps":[{"do":"turn","degrees":70},{"do":"let_go"}]}])
        for obj in objects:
            tool("define_interaction_points",world_id=wid,name=obj["name"],points=[])
        # Positions here are body-local COM coordinates.
        tool("define_interaction_points",world_id=wid,name="sledgehammer",points=[
            {"id":"handle","kind":"grip","position_m":[0,.14,0]},
            {"id":"swing","kind":"use","position_m":[0,.14,0]}])
        spec=room_world.export_spec(entry)
        tool("close_world",world_id=wid)
        return spec
    spec=author(args.panel_material)
    (out/"authoring.json").write_text(json.dumps(transcript,indent=2))
    (out/"spec.json").write_text(json.dumps(spec,indent=2))
    live=live_session.Live(); room=world_room.Room("yard");room.spec=spec
    app=SimpleNamespace(live=live,room=room,engine_path=engine,runs_path=out/"runs",live_holder="world")
    live.open(app,{"spec":spec})
    events=[]; frames=[]; results=[]
    def act(op,**kw):
        return live.act({"session":live.session.id,"op":op,**kw})
    def record(reply):
        for k in ("impacts","finished","outcome","pieces","stepped_back","working_on"):
            if reply.get(k):events.append({"t":reply.get("t"),k:deepcopy(reply[k])})
        frames.append({"t":live.session.state.get("t"),"hand":deepcopy(live.session.state.get("hand")),
                       "bodies":[{k:b[k] for k in ("name","material","mass_kg","position_m","orientation_wxyz","velocity_m_s","dent_mm") if k in b}
                                 for b in live.session.state.get("bodies",[])]})
        if reply.get("breakable") and not reply.get("working_on"):
            name=reply["breakable"][0]
            result=act("fracture",name=name,wait=False)
            events.append({"t":reply.get("t"),"fracture_requested":name,
                           "result":{k:v for k,v in result.items() if k not in ("bodies","geometry")}})
    def tick(n=4):
        a=act("step",dt=1/240,n=n);record(a);return a
    def advance(seconds):
        until=float(live.session.state.get("t",0))+seconds
        deadline=time.monotonic()+120
        while float(live.session.state.get("t",0))<until:
            tick()
            if time.monotonic()>deadline:raise RuntimeError("native stepping exceeded 120 seconds")
            if live.session.state.get("working_on"):time.sleep(.01)
    def state():
        a=act("poses")
        return {"t":a.get("t"),"bodies":frames[-1]["bodies"] if frames else a.get("bodies"),
                "joints":act("joints")}
    def save(tag):
        until=time.monotonic()+15
        while (live.session.state.get("working_on") or live.session.state.get("breakable")) and time.monotonic()<until:
            tick();time.sleep(.01)
        saved,why=live.snapshot()
        if saved is None:
            events.append({"snapshot_refused":tag,"why":why})
            print(json.dumps({"snapshot_refused":tag,"why":why}),flush=True)
            return False
        (out/(tag+"-snapshot.json")).write_text(json.dumps(saved))
        room.world_record=saved
        room.chat=[{"who":"room","text":"Engine-built masonry, glass, hinged oak door, and an iron-head/oak-handle sledgehammer. J uses the held hammer. This is a coarse-grid experiment; frame/hinge mounts are anchored, fixing strengths are declared test values."}]
        room_store.RoomStore(out/(tag+"-rooms")).save(room)
        return True
    def stroke(path,speed=1,accel=2):
        a=act("stroke",path=path,speed_m_s=speed,accel_m_s2=accel,lead_m=.05,give_up_s=8,let_go=False)
        deadline=time.monotonic()+90
        while live.session.state.get("hand",{}).get("stroking"):
            tick()
            if time.monotonic()>deadline:raise RuntimeError("stroke timed out")
        return deepcopy(live.session.state.get("hand",{}))
    def run_use(name,person):
        stop=threading.Event();errors=[]
        def clock():
            try:
                while not stop.is_set():
                    tick();time.sleep(.005)
            except Exception as e:errors.append(str(e))
        t=threading.Thread(target=clock);t.start()
        began=time.monotonic()
        try:answer=server.run_action(app,{"object":name,"primary":True,"person":person})
        finally:stop.set();t.join(10)
        if errors:raise RuntimeError(str(errors))
        return {"answer":answer,"wall_seconds":time.monotonic()-began}
    try:
        act("wield",name="sledgehammer",grip=[-.75,1.26,.65])
        advance(.5)
        initial=state();save("intact")
        # Test the actual hinges by a bounded hand at the door's free edge.
        act("release")
        door_result=run_use("door",{"standing_m":[0,0,1.8],"eyes_m":[0,1.62,1.8],"facing":[0,0,-1]})
        act("release");advance(.4)
        results.append({"phase":"door operation","hand":door_result,"state":state()})
        # Carry the same assembled tool between targets with the bounded hand.
        toolbody=next(b for b in live.session.state["bodies"] if b["name"]=="sledgehammer")
        # Holding at COM avoids assuming the fallen tool's present orientation.
        act("wield",name="sledgehammer",grip=toolbody["position_m"])
        act("step",dt=1/240,n=1,hand_q=[1,0,0,0])
        for label,x,y in (("left pane",-.75,.76),("right pane",.75,.76),("right brick 1-0",.625,.185)):
            grip=live.session.state["hand"]["grip_m"]
            destination=[x,y+.36,.65]
            carried=stroke([grip,[grip[0],max(grip[1],1.3),.85],[x,max(destination[1],1.3),.85],destination])
            before=state();start_event=len(events)
            answer=run_use("sledgehammer",{"standing_m":[x,0,1.8],"eyes_m":[x,1.62,1.8],
                           "facing":[0,0,-1],"look_direction":[0,0,-1]})
            advance(.3)
            results.append({"phase":"strike "+label,"carry":carried,"use":answer,
                            "before":before,"after":state(),"events":events[start_event:]})
            print(json.dumps({"phase":label,"use":answer,"event_count":len(events)-start_event,
                              "bodies":len(live.session.state["bodies"])}),flush=True)
        act("cancel_stroke");act("release");advance(.5);saved_final=save("damaged")
        report={"source":"365f43a","cell_m":.02,"dt_s":1/240,"panel_material":args.panel_material,"initial":initial,
                "results":results,"final":state(),"events":events,"saved_final":saved_final}
        (out/"report.json").write_text(json.dumps(report,indent=2))
        (out/"frames.json").write_text(json.dumps(frames))
        print("Saved "+str(out),flush=True)
    finally:
        (out/"partial-events.json").write_text(json.dumps(events,indent=2))
        (out/"partial-results.json").write_text(json.dumps(results,indent=2))
        live.shutdown()
if __name__=="__main__":main()
