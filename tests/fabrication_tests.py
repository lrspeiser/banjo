"""Finite-stock manufacturing, native publication and durable transaction regression."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"playground"),str(ROOT/"tests")]
from mcp import fabrication as model, engine_materials
import fabrication_room as room_api
import live_session, room_store, world_room, workshop_install
ENGINE=Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None

def settings(**changes):
    return {"mode":"authoring","stock_kg":{"glass":30,"oak":30,"iron":30},
            "energy_j":10000,"power_w":500,"work_j_kg":100,**changes}

def candidate(material="oak"):
    return {"kind":"custom","parameters":{"primary_use":{"label":"Push","steps":[
        {"do":"push_forward","distance_m":.2,"speed_m_s":.4}]}},
        "component_overrides":{"@construction":{"added":[{"name":"part","role":"panel",
            "family":"panel","shape":"box","size_m":[.16,.08,.08],"center_m":[0,.04,0],
            "rotation_deg":[0,0,0],"material":material}],"joints_authored":True}}}

def start(state,material="oak",stock=10):
    q=room_api.compile_quote(candidate(material),stock,.04,state)
    body={"op":"start","candidate":candidate(material),"stock_kg":stock,
          "revision":state["revision"],"request_id":"job-"+material+"-0001"}
    return model.mutate(state,body,quote=q)[0],body

class ProcessModel(unittest.TestCase):
    def test_ground_audit_distinguishes_transfer_and_external_material(self):
        zero={"sand_m3":0.,"soil_m3":0.,"rock_m3":0.}
        ground={"ledger":{"dug":{**zero,"sand_m3":.03},
            "deposited":{**zero,"sand_m3":.01}},
            "carried":{**zero,"sand_m3":.01},"exported":{**zero,"sand_m3":.01},"residual":zero}
        state={"raw_lots":{"lot":{"schema":"banjo.bulk-material.v1","source":"excavated_ground",
            "form":"granular","thermal_state":"unmodeled",
            "contents":[{"substance":"sand","volume_m3":.01,"mass_kg":16.}]}}}
        before=deepcopy([state,ground])
        a=model.ground_audit(state,ground)
        self.assertEqual(a["status"],"matched")
        self.assertEqual(a["substances"]["sand"]["collection_status"],"balanced")
        self.assertEqual([state,ground],before)
        # An authored heap cannot be presented as a proven closed budget.
        ground["ledger"]["deposited"]["sand_m3"]+=.005
        a=model.ground_audit(state,ground)
        self.assertEqual(a["status"],"matched")
        self.assertEqual(a["substances"]["sand"]["collection_status"],"external_input_or_error")
        self.assertAlmostEqual(a["substances"]["sand"]["net_external_or_untracked_m3"],.005)
        ground["ledger"]["deposited"]["sand_m3"]=0
        self.assertEqual(model.ground_audit(state,ground)["substances"]["sand"]["collection_status"],"unaccounted_destination")
        missing=deepcopy(state);missing["raw_lots"]={}
        self.assertEqual(model.ground_audit(missing,ground)["status"],"mismatch")
        wrong=deepcopy(state);wrong["raw_lots"]["lot"]["contents"][0]["mass_kg"]=17
        self.assertEqual(model.ground_audit(wrong,ground)["status"],"mismatch")
        self.assertEqual(model.ground_audit(state,{})["status"],"unavailable")

    def test_recovery_conserves_material_and_does_not_refund_work(self):
        for material in ("glass", "oak", "iron"):
            with self.subTest(material=material):
                s,job=start(model.new(settings(stock_kg={material:10}),0),material)
                request={"op":"recover","material":material,"mass_kg":1,
                         "revision":s["revision"],"request_id":"recover-0001"}
                with self.assertRaisesRegex(ValueError,"Insufficient offcuts"):
                    model.mutate(s,request)
                model.advance(s,2)
                before=deepcopy(s); amount=s["waste_kg"][material]
                request["mass_kg"]=amount
                out,replayed=model.mutate(s,request)
                self.assertFalse(replayed);self.assertEqual(s,before)
                self.assertEqual(out["waste_kg"][material],0)
                self.assertEqual(out["stock_kg"][material],amount)
                for key in ("energy_j","station_heat_j","spent_j","ambient_j","jobs","time_s"):
                    self.assertEqual(out[key],before[key])
                replay,flag=model.mutate(json.loads(json.dumps(out)),request)
                self.assertTrue(flag);self.assertEqual(replay,out)
                with self.assertRaisesRegex(ValueError,"revision"):
                    model.mutate(out,{**request,"request_id":"recover-0002"})
                with self.assertRaisesRegex(ValueError,"Insufficient offcuts"):
                    model.mutate(out,{**request,"request_id":"recover-0002","revision":out["revision"]})
                # Recovered stock can fund new work, but cannot bypass its cost.
                smaller=candidate(material)
                part=smaller["component_overrides"]["@construction"]["added"][0]
                part.update(size_m=[.04,.04,.04],center_m=[.02,.02,.02])
                q=room_api.compile_quote(smaller,amount,.04,out)
                out,_=model.mutate(out,{"op":"start","request_id":"reused-stock-0001","revision":out["revision"]},quote=q)
                self.assertEqual(out["stock_kg"][material],0)
                self.assertEqual(out["jobs"]["reused-stock-0001"]["work_j"],0)
                model.advance(out,4)
                self.assertAlmostEqual(out["spent_j"],1000+amount*100)
                self.close(out)

    def test_recovery_rejects_invalid_amounts_and_changed_retries(self):
        s,_=start(model.new(settings(),0));model.advance(s,2);before=deepcopy(s)
        req={"op":"recover","material":"oak","mass_kg":1,"revision":s["revision"],"request_id":"recover-0001"}
        for bad in (0,-1,True,math.nan,math.inf,10001,10):
            with self.assertRaises(ValueError):model.mutate(s,{**req,"mass_kg":bad})
        with self.assertRaises(ValueError):model.mutate(s,{**req,"material":"unknown"})
        self.assertEqual(s,before)
        out,_=model.mutate(s,req)
        with self.assertRaisesRegex(ValueError,"different"):
            model.mutate(out,{**req,"mass_kg":2})

    def close(self,state):
        a=model.audit(state)
        for v in a["material_residual_kg"].values():self.assertAlmostEqual(v,0,places=9)
        self.assertAlmostEqual(a["energy_residual_j"],0,places=7)
        self.assertAlmostEqual(a["work_residual_j"],0,places=7)
        model.validate_state(state)

    def test_exact_catalog_geometry_and_material_work_accounting(self):
        for material in ("glass","oak","iron"):
            with self.subTest(material=material):
                s,req=start(model.new(settings(),0),material)
                self.assertAlmostEqual(s["stock_kg"][material],20)
                j=s["jobs"][req["request_id"]]
                self.assertAlmostEqual(j["product_kg"],.16*.08*.08*engine_materials.density(material))
                model.advance(s,1)
                self.assertEqual(j["status"],"running");self.assertAlmostEqual(j["work_j"],500)
                model.advance(s,2)
                self.assertEqual(j["status"],"ready")
                self.assertAlmostEqual(s["waste_kg"][material]+j["product_kg"],10)
                self.assertAlmostEqual(s["energy_j"],9000)
                self.assertAlmostEqual(s["station_heat_j"],1000)
                self.close(s)

    def test_pausing_retains_workpiece_and_resume_does_not_refund(self):
        s,req=start(model.new(settings(cooling_w_k=10),0))
        model.advance(s,.5)
        j=s["jobs"][req["request_id"]]; work=j["work_j"]
        p={"op":"pause","job_id":req["request_id"],"request_id":"pause-0001","revision":s["revision"]}
        s,_=model.mutate(s,p);energy=s["energy_j"]
        model.advance(s,20)
        self.assertEqual(s["jobs"][req["request_id"]]["work_j"],work)
        self.assertEqual(s["stock_kg"]["oak"],20);self.assertEqual(s["energy_j"],energy)
        self.assertGreater(s["ambient_j"],0)
        s=json.loads(json.dumps(s));self.close(s)
        s,_=model.mutate(s,{**p,"op":"resume","revision":s["revision"],"request_id":"resume-0001"})
        model.advance(s,22);self.assertEqual(s["jobs"][req["request_id"]]["status"],"ready");self.close(s)

    def test_supply_and_temperature_limits_do_not_invent_finished_parts(self):
        for config,expected in ((settings(energy_j=120,efficiency=.5),60),
                (settings(heat_capacity_j_k=1000,max_temperature_k=293.25),100)):
            s,req=start(model.new(config,0));model.advance(s,10)
            self.assertEqual(s["jobs"][req["request_id"]]["status"],"running")
            self.assertAlmostEqual(s["jobs"][req["request_id"]]["work_j"],expected)
            self.assertEqual(s["waste_kg"],{});self.close(s)

    def test_native_batch_size_does_not_change_work_or_heat(self):
        for c in (settings(cooling_w_k=125),settings(cooling_w_k=100,heat_capacity_j_k=1000,max_temperature_k=294)):
            a,_=start(model.new(c,0));b=deepcopy(a)
            model.advance(a,20)
            for tick in range(1,4801):model.advance(b,tick/240)
            for key in ("spent_j","energy_j","station_heat_j","ambient_j"):
                self.assertAlmostEqual(a[key],b[key],places=6)
            self.close(a);self.close(b)

    def test_retry_stale_revision_and_shared_stock(self):
        s=model.new(settings(),0);q=room_api.compile_quote(candidate(),10,.04,s)
        req={"op":"start","candidate":candidate(),"stock_kg":10,"revision":0,"request_id":"start-0001"}
        first,_=model.mutate(s,req,quote=q);again,replayed=model.mutate(first,req,quote=q)
        self.assertTrue(replayed);self.assertEqual(first,again)
        with self.assertRaisesRegex(ValueError,"different"):model.mutate(first,{**req,"stock_kg":11},quote=q)
        with self.assertRaisesRegex(ValueError,"revision"):model.mutate(first,{**req,"request_id":"start-0002"},quote=q)
        with self.assertRaisesRegex(ValueError,"occupied"):model.mutate(first,{**req,"request_id":"start-0002","revision":1},quote=q)
        poor=model.new(settings(stock_kg={"oak":.5}),0)
        with self.assertRaisesRegex(ValueError,"Insufficient"):model.mutate(poor,req,quote=q)
        self.assertEqual(poor["stock_kg"]["oak"],.5)

    def test_strict_inputs_and_no_clock_rewind_or_save_refill(self):
        for change in ({"power_w":True},{"energy_j":math.inf},{"efficiency":0},{"mode":"survival"},{"unknown":1}):
            with self.assertRaises(ValueError):model.new(settings(**change),0)
        s,req=start(model.new(settings(),3))
        with self.assertRaises(ValueError):model.advance(s,2)
        model.advance(s,4);before=deepcopy(s);model.advance(s,4);self.assertEqual(before,s)
        bad=deepcopy(s);bad["energy_j"]+=1
        with self.assertRaisesRegex(ValueError,"ledger"):model.validate_state(bad)
        bad=deepcopy(s);bad["stock_kg"]["oak"]+=1
        with self.assertRaisesRegex(ValueError,"ledger"):model.validate_state(bad)
        without=candidate();without["parameters"]={}
        with self.assertRaisesRegex(ValueError,"primary_use"):room_api.compile_quote(without,10,.04,s)

    def test_transfer_is_exact_and_single_use(self):
        s,req=start(model.new(settings(),0));j=s["jobs"][req["request_id"]]
        p={"matter_physics_hash":j["matter_physics_hash"],"mass_kg":j["product_kg"],"root_body":"native"}
        with self.assertRaisesRegex(ValueError,"finished"):model.transfer(s,req["request_id"],p,"install-0001")
        model.advance(s,2)
        with self.assertRaisesRegex(ValueError,"differs"):model.transfer(s,req["request_id"],{**p,"mass_kg":20},"install-0001")
        out=model.transfer(s,req["request_id"],p,"install-0001")
        self.close(out)
        with self.assertRaisesRegex(ValueError,"finished"):model.transfer(out,req["request_id"],p,"install-0002")

@unittest.skipUnless(ENGINE and ENGINE.is_file(),"BANJO_LIVE_ENGINE is required; CI supplies it")
class NativeFabrication(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.live=live_session.Live();self.addCleanup(self.live.shutdown)
        self.room=world_room.Room("fabrication")
        self.app=SimpleNamespace(live=self.live,live_holder="world",room=self.room,engine_path=ENGINE,
            runs_path=root/"runs",store=room_store.RoomStore(root/"rooms"))
        self.live.open(self.app,{"spec":self.room.spec})
        self.call("configure",settings=settings(),request_id="configure-0001")
    def context(self):return {"scene":"fabrication","session":self.live.session.id}
    def call(self,op,**body):return room_api.request(self.app,op,{**self.context(),**body})
    def step(self,n=1):return room_api.wait(self.app,{**self.context(),"seconds":n})
    def begin(self,material="oak",ident="job-native-0001"):
        return self.call("start",candidate=candidate(material),stock_kg=10,
            revision=self.room.fabrication_record["revision"],request_id=ident)

    def excavate(self):
        self.room.spec["terrain"]={"generate":{"kind":"flat","nx":32,"nz":32,
            "cell_m":.25,"soil_m":.2,"sand_m":.02}}
        self.live.open(self.app,{"spec":self.room.spec})
        self.live.session.send(op="dig",**{"from":[0,0],"to":[0,0],"width_m":.5,"depth_m":.1})

    def test_store_ground_commits_both_accounts_and_retries_after_restart(self):
        self.excavate();before=workshop_install._snapshot(self.live)
        carried=before["ground"]["carried"]
        request={**self.context(),"sand_m3":carried["sand_m3"],"soil_m3":carried["soil_m3"],
            "revision":self.room.fabrication_record["revision"],"request_id":"store-ground-0001"}
        original=deepcopy(self.room.fabrication_record);old=self.live.session
        with mock.patch.object(self.app.store,"save",side_effect=OSError("disk full")):
            with self.assertRaises(OSError):room_api.request(self.app,"store_ground",request)
        self.assertIs(old,self.live.session)
        self.assertEqual(before,workshop_install._snapshot(self.live))
        self.assertEqual(original,self.room.fabrication_record)
        result=room_api.request(self.app,"store_ground",request)
        self.assertFalse(result["replayed"]);self.assertTrue(old._closed)
        self.assertTrue(room_api.request(self.app,"store_ground",request)["replayed"])
        state=self.room.fabrication_record
        self.assertEqual(state["stock_kg"],original["stock_kg"])
        self.assertEqual(state["energy_j"],original["energy_j"])
        self.assertEqual(len(state["raw_lots"]),1)
        saved=self.app.store.load("fabrication")
        self.assertEqual(saved.fabrication_record,state)
        self.assertEqual(saved.world_record,workshop_install._snapshot(self.live))
        self.assertEqual(saved.world_record["ground"]["carried"],{"rock_m3":0.,"sand_m3":0.,"soil_m3":0.})
        self.live.open(self.app,{"spec":saved.spec,"snapshot":saved.world_record})
        self.room.fabrication_record=deepcopy(saved.fabrication_record)
        self.assertTrue(room_api.request(self.app,"store_ground",request)["replayed"])
        with self.assertRaisesRegex(ValueError,"different"):
            room_api.request(self.app,"store_ground",{**request,"sand_m3":0})
        with self.assertRaisesRegex(ValueError,"Insufficient"):
            self.call("store_ground",sand_m3=.001,soil_m3=0,revision=state["revision"],request_id="store-ground-0002")

    def test_retrieval_is_atomic_partial_restartable_and_can_be_deposited(self):
        self.excavate();native=workshop_install._snapshot(self.live)
        have={k:native["ground"]["carried"][k] for k in ("sand_m3","soil_m3")}
        self.call("store_ground",**have,revision=self.room.fabrication_record["revision"],request_id="stored-return-0001")
        req={**self.context(),"lot_id":"stored-return-0001",**{k:v/2 for k,v in have.items()},
             "revision":self.room.fabrication_record["revision"],"request_id":"retrieve-0001"}
        before=workshop_install._snapshot(self.live);state=deepcopy(self.room.fabrication_record);old=self.live.session
        with mock.patch.object(self.app.store,"save",side_effect=OSError("disk full")):
            with self.assertRaises(OSError):room_api.request(self.app,"retrieve_ground",req)
        self.assertIs(old,self.live.session);self.assertEqual(before,workshop_install._snapshot(self.live))
        self.assertEqual(state,self.room.fabrication_record)
        result=room_api.request(self.app,"retrieve_ground",req)
        self.assertFalse(result["replayed"])
        self.assertTrue(room_api.request(self.app,"retrieve_ground",req)["replayed"])
        saved=self.app.store.load("fabrication")
        self.live.open(self.app,{"spec":saved.spec,"snapshot":saved.world_record});self.room=self.app.room=saved
        self.assertTrue(room_api.request(self.app,"retrieve_ground",req)["replayed"])
        with self.assertRaisesRegex(ValueError,"different"):
            room_api.request(self.app,"retrieve_ground",{**req,"soil_m3":0})
        remaining=model.raw_inventory(self.room.fabrication_record)["stored-return-0001"]
        amounts={item["substance"]+"_m3":item["volume_m3"] for item in remaining}
        self.call("retrieve_ground",lot_id="stored-return-0001",**amounts,
                  revision=self.room.fabrication_record["revision"],request_id="retrieve-0002")
        out=self.call("state")
        self.assertEqual(out["ground_audit"]["status"],"matched")
        for substance in ("sand","soil"):
            row=out["ground_audit"]["substances"][substance]
            self.assertAlmostEqual(row["carried_m3"],have[substance+"_m3"])
            self.assertAlmostEqual(row["stored_m3"],0)
            self.assertEqual(row["collection_status"],"balanced")
        with self.assertRaisesRegex(ValueError,"Insufficient"):
            self.call("retrieve_ground",lot_id="stored-return-0001",sand_m3=.001,soil_m3=0,
                revision=self.room.fabrication_record["revision"],request_id="retrieve-0003")
        # A second storage cycle has cumulative exports greater than excavation;
        # prior returns are subtracted, so the same matter is never duplicated.
        self.call("store_ground",**have,revision=self.room.fabrication_record["revision"],request_id="stored-return-0002")
        self.call("retrieve_ground",lot_id="stored-return-0002",**have,
            revision=self.room.fabrication_record["revision"],request_id="retrieve-cycle-0002")
        self.live.act({"session":self.live.session.id,"op":"deposit","at":[1,1],"radius_m":.5,**have})
        out=self.call("state")
        for row in out["ground_audit"]["substances"].values():
            self.assertEqual(row["carried_m3"],0)
            self.assertEqual(row["collection_status"],"balanced")
        for key in ("stock_kg","energy_j","jobs","spent_j"):
            self.assertEqual(state[key],self.room.fabrication_record[key])

    def test_retrieval_capacity_and_corrupt_receipts_are_refused(self):
        self.excavate();source=workshop_install._snapshot(self.live)
        have={k:source["ground"]["carried"][k] for k in ("sand_m3","soil_m3")}
        self.call("store_ground",**have,revision=self.room.fabrication_record["revision"],request_id="capacity-lot-0001")
        self.live.act({"session":self.live.session.id,"op":"dig","from":[1,1],"to":[1,1],"width_m":2,"depth_m":.2})
        before=workshop_install._snapshot(self.live);record=deepcopy(self.room.fabrication_record)
        with self.assertRaisesRegex(live_session.LiveError,"capacity"):
            self.call("retrieve_ground",lot_id="capacity-lot-0001",**have,
                revision=record["revision"],request_id="capacity-return-0001")
        self.assertEqual(before,workshop_install._snapshot(self.live));self.assertEqual(record,self.room.fabrication_record)
        # A forged return on either side must fail the durable cross-check.
        good=deepcopy(record)
        request={"op":"retrieve_ground","lot_id":"capacity-lot-0001",**have,
            "revision":good["revision"],"request_id":"model-return-0001"}
        returned,_=model.return_bulk(good,request)
        with self.assertRaisesRegex(ValueError,"native ground receipts"):
            model.validate_ground_stock(returned,before)
        bad=deepcopy(returned);bad["raw_returns"]["model-return-0001"]["packet"]["contents"][0]["volume_m3"]*=2
        with self.assertRaises(ValueError):model.validate_state(bad)
        bad=deepcopy(returned);bad["raw_returns"]["model-return-0001"]["lot_id"]="missing-lot-0001"
        with self.assertRaises(ValueError):model.validate_state(bad)

    def test_raw_stock_save_rejects_missing_or_changed_source_and_destination(self):
        self.excavate();s=workshop_install._snapshot(self.live)
        self.call("store_ground",sand_m3=s["ground"]["carried"]["sand_m3"],soil_m3=0,
            revision=self.room.fabrication_record["revision"],request_id="store-ground-0001")
        path=self.app.store.path_of("fabrication");original=json.loads(path.read_text(encoding="utf-8"))
        for target in ("raw_lots","source","mass"):
            bad=deepcopy(original)
            if target=="raw_lots":bad["fabrication"].pop("raw_lots")
            elif target=="source":bad["world"]["ground"]["exported"]["sand_m3"]=0
            else:bad["fabrication"]["raw_lots"]["store-ground-0001"]["contents"][0]["mass_kg"]*=2
            path.write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(ValueError):self.app.store.load("fabrication")
        path.write_text(json.dumps(original),encoding="utf-8")
    def test_recovered_stock_save_failure_restart_and_native_state(self):
        self.begin();self.step(2)
        before=deepcopy(self.room.fabrication_record);native=workshop_install._snapshot(self.live)
        request={"material":"oak","mass_kg":before["waste_kg"]["oak"],
                 "revision":before["revision"],"request_id":"recover-native-0001"}
        with mock.patch.object(self.app.store,"save",side_effect=OSError("disk full")):
            with self.assertRaises(OSError):self.call("recover",**request)
        self.assertEqual(self.room.fabrication_record,before)
        self.assertEqual(workshop_install._snapshot(self.live),native)
        answer=self.call("recover",**request)
        self.assertEqual(answer["state"]["waste_kg"]["oak"],0)
        loaded=self.app.store.load("fabrication")
        self.assertEqual(loaded.world_record,native)
        self.live.open(self.app,{"spec":loaded.spec,"snapshot":loaded.world_record})
        self.room=self.app.room=loaded
        self.assertTrue(self.call("recover",**request)["replayed"])
        self.assertEqual(self.room.fabrication_record["stock_kg"]["oak"],30-before["jobs"]["job-native-0001"]["product_kg"])
    def test_glass_oak_iron_work_restart_native_mass_and_duplicate_install(self):
        measured=[]
        for i,material in enumerate(("glass","oak","iron")):
            ident="job-native-"+material
            self.begin(material,ident);self.step()
            self.call("pause",job_id=ident,revision=self.room.fabrication_record["revision"],request_id="pause-"+material+"-0001")
            before=deepcopy(self.room.fabrication_record);saved=self.app.store.load("fabrication")
            self.live.open(self.app,{"spec":saved.spec,"snapshot":saved.world_record})
            self.assertEqual(self.live.session.state["restored"]["tier"],"whole")
            self.room=self.app.room=saved;self.assertEqual(self.room.fabrication_record,before)
            self.step();self.assertAlmostEqual(self.room.fabrication_record["jobs"][ident]["work_j"],500,places=7)
            self.call("resume",job_id=ident,revision=self.room.fabrication_record["revision"],request_id="resume-"+material+"-0001")
            self.step()
            p=room_api.preview(self.app,{**self.context(),"job_id":ident,"position_m":[i*.5,0]})
            original=workshop_install._snapshot(self.live)
            req={**self.context(),"job_id":ident,"preview_id":p["preview_id"],"request_id":"install-"+material+"-0001"}
            result=room_api.commit(self.app,req)
            self.assertTrue(result["resources_charged"])
            self.assertTrue(room_api.commit(self.app,req)["replayed"])
            workshop_install._preserved(original,workshop_install._snapshot(self.live),result["root_body"])
            body=next(b for b in self.live.session.state["bodies"] if b["name"]==result["root_body"])
            expected=self.room.fabrication_record["jobs"][ident]["product_kg"]
            self.assertAlmostEqual(body["mass_kg"],expected,places=7)
            self.assertEqual(len(self.live.session.state["bodies"]),i+2)
            loaded=self.app.store.load("fabrication")
            self.assertEqual(loaded.fabrication_record,self.room.fabrication_record)
            self.assertEqual(loaded.world_record,workshop_install._snapshot(self.live))
            measured.append({"material":material,"mass_kg":body["mass_kg"],"cells":p["cells"],
                             "audit":model.audit(self.room.fabrication_record)})
        self.native_evidence=measured
        print("native fabrication:",json.dumps(measured))

    def test_failed_start_and_install_saves_leave_stock_native_world_and_output(self):
        before=deepcopy(self.room.fabrication_record);native=workshop_install._snapshot(self.live)
        with mock.patch.object(self.app.store,"save",side_effect=OSError("disk full")):
            with self.assertRaises(OSError):self.begin()
        self.assertEqual(before,self.room.fabrication_record);self.assertEqual(native,workshop_install._snapshot(self.live))
        self.begin();self.step(2)
        p=room_api.preview(self.app,{**self.context(),"job_id":"job-native-0001","position_m":[0,0]})
        before=deepcopy(self.room.fabrication_record);old=self.live.session
        request={**self.context(),"job_id":"job-native-0001","preview_id":p["preview_id"],"request_id":"install-0001"}
        with mock.patch.object(self.app.store,"save",side_effect=OSError("disk full")):
            with self.assertRaises(OSError):room_api.commit(self.app,request)
        self.assertIs(old,self.live.session);self.assertEqual(before,self.room.fabrication_record)
        self.assertEqual(len(self.live.session.state["bodies"]),1)
        self.assertEqual(room_api.commit(self.app,request)["status"],"installed")

    def test_changed_use_or_stale_preview_cannot_consume_a_workpiece(self):
        self.begin();self.step(2)
        changed=candidate();changed["parameters"]["primary_use"]["label"]="Changed"
        p=workshop_install.preview(self.app,{**self.context(),"mode":"authoring","candidate":changed,"position_m":[0,0]})
        req={**self.context(),"job_id":"job-native-0001","preview_id":p["preview_id"],"request_id":"install-0001"}
        with self.assertRaisesRegex(ValueError,"funded design"):room_api.commit(self.app,req)
        p=room_api.preview(self.app,{**self.context(),"job_id":"job-native-0001","position_m":[0,0]})
        self.step()
        with self.assertRaisesRegex(ValueError,"changed after preview"):
            room_api.commit(self.app,{**req,"preview_id":p["preview_id"]})
        self.assertEqual(self.room.fabrication_record["jobs"]["job-native-0001"]["status"],"ready")
        with self.assertRaisesRegex(ValueError,"already supplied"):self.call("configure",settings=settings(energy_j=100000),request_id="configure-0002")

    def test_funded_save_refuses_either_missing_half_or_changed_clock(self):
        path=self.app.store.path_of("fabrication")
        original=json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(original["fabrication_required"])
        for field in ("fabrication","world"):
            broken=deepcopy(original);del broken[field]
            path.write_text(json.dumps(broken),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"requires"):self.app.store.load("fabrication")
        broken=deepcopy(original);broken["world"]["t_s"]+=1
        path.write_text(json.dumps(broken),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"matching"):self.app.store.load("fabrication")
        path.write_text(json.dumps(original),encoding="utf-8")
        loaded=self.app.store.load("fabrication");loaded.fabrication_record=None
        with self.assertRaisesRegex(ValueError,"ledger"):self.app.store.save(loaded)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),original)


from workbench_tests import WorkbenchTestCase
@unittest.skipUnless(ENGINE and ENGINE.is_file(),"Native HTTP/MCP QA requires BANJO_LIVE_ENGINE")
class NativeHTTP(WorkbenchTestCase):
    def native_server(self):
        app=self.start();app.live=live_session.Live();app.engine_path=ENGINE
        self.addCleanup(app.live.shutdown)
        return app

    def test_mcp_stores_main_world_ground_and_replays_original_session(self):
        app=self.native_server();opened=self.post(app,"/api/world/open",{"scene":"world"})
        ctx={"scene":"world","session":opened["session"]}
        self.post(app,"/api/world/fabrication/configure",{**ctx,"settings":settings(),"request_id":"raw-config-0001"})
        self.post(app,"/api/live/act",{"session":ctx["session"],"op":"dig","from":[13,-7],"to":[13,-7],"width_m":.5,"depth_m":.05})
        source=self.post(app,"/api/world/fabrication/state",ctx)
        carried=source["carried_ground"]
        self.assertEqual(source["ground_audit"]["status"],"matched")
        for row in source["ground_audit"]["substances"].values():
            self.assertEqual(row["collection_status"],"balanced")
        req={**ctx,"sand_m3":carried["sand_m3"],"soil_m3":carried["soil_m3"],
            "revision":source["state"]["revision"],"request_id":"raw-store-0001"}
        import fabrication_mcp_tools as tools
        from circuit_api import validate
        schema=next(t["inputSchema"] for t in tools.TOOLS if t["name"]=="fabrication_store_ground")
        validate(req,schema,"arguments")
        with mock.patch.dict(os.environ,{"BANJO_PLAYGROUND_URL":f"http://127.0.0.1:{app.port}"}):
            first=tools.call("fabrication_store_ground",req)
            self.assertNotEqual(first["session"],ctx["session"])
            self.assertTrue(tools.call("fabrication_store_ground",req)["replayed"])
        with mock.patch.dict(os.environ,{"BANJO_PLAYGROUND_URL":f"http://127.0.0.1:{app.port}"}):
            measured=tools.call("fabrication_state",{**ctx,"session":first["session"]})
        audit=measured["ground_audit"]
        self.assertEqual(audit["status"],"matched")
        for substance in ("sand","soil"):
            row=audit["substances"][substance]
            self.assertEqual(row["carried_m3"],0)
            self.assertAlmostEqual(row["stored_kg"],carried[substance+"_kg"])
            self.assertAlmostEqual(row["transfer_residual_m3"],0)
            self.assertEqual(row["collection_status"],"balanced")
        saved=app.store.load("world")
        self.assertEqual(len(saved.fabrication_record["raw_lots"]),1)
        self.assertEqual(saved.world_record,workshop_install._snapshot(app.live))
        self.assertTrue(saved.world_upgrades)
        retrieve={"scene":"world","session":first["session"],"lot_id":"raw-store-0001",
            "sand_m3":req["sand_m3"],"soil_m3":req["soil_m3"],
            "revision":measured["state"]["revision"],"request_id":"mcp-retrieve-0001"}
        schema=next(t["inputSchema"] for t in tools.TOOLS if t["name"]=="fabrication_retrieve_ground")
        validate(retrieve,schema,"arguments")
        with mock.patch.dict(os.environ,{"BANJO_PLAYGROUND_URL":f"http://127.0.0.1:{app.port}"}):
            taken=tools.call("fabrication_retrieve_ground",retrieve)
            self.assertTrue(tools.call("fabrication_retrieve_ground",retrieve)["replayed"])
            measured=tools.call("fabrication_state",{"scene":"world","session":taken["session"]})
        self.assertEqual(measured["ground_audit"]["status"],"matched")
        for substance in ("sand","soil"):
            row=measured["ground_audit"]["substances"][substance]
            self.assertEqual(row["stored_m3"],0)
            self.assertAlmostEqual(row["carried_m3"],req[substance+"_m3"])

    def test_main_world_funded_outputs_preserve_terrain_water_and_stock(self):
        app=self.native_server()
        opened=self.post(app,"/api/world/open",{"scene":"world"})
        ctx={"scene":"world","session":opened["session"]}
        def call(op,**args):
            return self.post(app,"/api/world/fabrication/"+op,{**ctx,**args})
        call("configure",settings=settings(),request_id="terrain-config-0001")
        for i,material in enumerate(("glass","oak","iron")):
            job="terrain-job-"+material
            call("start",candidate=candidate(material),stock_kg=10,
                 revision=app.room.fabrication_record["revision"],request_id=job)
            call("wait",seconds=2)
            terrain=workshop_install._terrain_state(app.live.session)
            before=workshop_install._snapshot(app.live)
            p=call("preview",job_id=job,position_m=[13+i*.5,-7])
            self.assertGreater(p["bounds_m"][0][1],0)
            with self.assertRaisesRegex(ValueError,"material-funded"):
                workshop_install.commit(app,{**ctx,"preview_id":p["preview_id"],"request_id":"unfunded-"+material})
            result=call("commit",job_id=job,preview_id=p["preview_id"],request_id="terrain-install-"+material)
            ctx["session"]=result["session"]
            after=workshop_install._snapshot(app.live)
            workshop_install._preserved(before,after,result["root_body"])
            self.assertEqual(workshop_install._terrain_state(app.live.session),terrain)
            self.assertTrue(result["resources_charged"])
            self.assertEqual(app.room.fabrication_record["jobs"][job]["status"],"installed")
            native=next(b for b in app.live.session.state["bodies"] if b["name"]==result["root_body"])
            expected=app.room.fabrication_record["jobs"][job]["product_kg"]
            self.assertAlmostEqual(native["mass_kg"],expected,places=7)
            import fabrication_mcp_tools as tools
            from circuit_api import validate
            request={**ctx,"material":material,"mass_kg":(10-expected)/2,
                     "revision":app.room.fabrication_record["revision"],"request_id":"recover-main-"+material}
            schema=next(t["inputSchema"] for t in tools.TOOLS if t["name"]=="fabrication_recover")
            validate(request,schema,"arguments")
            with mock.patch.dict(os.environ,{"BANJO_PLAYGROUND_URL":f"http://127.0.0.1:{app.port}"}):
                recovered=tools.call("fabrication_recover",request)
                self.assertTrue(tools.call("fabrication_recover",request)["replayed"])
            self.assertAlmostEqual(recovered["state"]["stock_kg"][material],20+request["mass_kg"])
            self.assertAlmostEqual(recovered["state"]["waste_kg"][material],request["mass_kg"])
            self.assertEqual(workshop_install._snapshot(app.live),after)
        saved=app.store.load("world")
        self.assertEqual(saved.fabrication_record,app.room.fabrication_record)
        self.assertEqual(saved.world_record,workshop_install._snapshot(app.live))
        self.assertTrue(saved.world_upgrades)
        self.assertAlmostEqual(model.audit(saved.fabrication_record)["energy_residual_j"],0,places=7)

    def test_main_world_process_preserves_receipts_and_cannot_reset(self):
        app=self.native_server()
        opened=self.post(app,"/api/world/open",{"scene":"world"})
        ctx={"scene":"world","session":opened["session"]}
        receipts=deepcopy(app.room.world_upgrades)
        self.assertTrue(receipts, "main-world startup receipts are required for this regression")
        import fabrication_mcp_tools as tools
        from circuit_api import validate
        with mock.patch.dict(os.environ,{"BANJO_PLAYGROUND_URL":f"http://127.0.0.1:{app.port}"}):
            def call(op,**args):
                args={**ctx,**args}
                schema=next(t["inputSchema"] for t in tools.TOOLS if t["name"]=="fabrication_"+op)
                validate(args,schema,"arguments")
                return tools.call("fabrication_"+op,args)
            call("configure",settings=settings(),request_id="main-config-0001")
            surveyed=self.post(app,"/api/live/act",{"session":ctx["session"],"op":"survey","at":[13,-7]})
            self.assertTrue(surveyed["survey"]["on_the_ground"])
            control=app.live.session.state["machines"]["controls"][0]
            operated=self.post(app,"/api/world/machine",{"session":ctx["session"],"control":control["id"],
                              "sender":"funded-world-test","seq":1,"power":False})
            self.assertEqual(operated["operated"],"applied")
            self.post(app,"/api/live/act",{"session":ctx["session"],"op":"dig",
                      "from":[13,-7],"to":[13,-7],"width_m":.5,"depth_m":.02})
            self.assertEqual(app.store.load("world").world_upgrades,receipts)
            call("start",candidate=candidate(),stock_kg=10,revision=0,request_id="main-job-0001")
            call("wait",seconds=1)
            state=call("state")["state"]
            call("pause",job_id="main-job-0001",revision=state["revision"],request_id="main-pause-0001")
            before=deepcopy(app.room.fabrication_record)
            native=workshop_install._snapshot(app.live)
            again=self.post(app,"/api/world/open",{"scene":"world","again":True})
            self.assertEqual(again["restored"]["tier"],"whole")
            self.assertEqual(app.room.fabrication_record,before)
            self.assertEqual(workshop_install._snapshot(app.live)["t_s"],native["t_s"])
            self.assertEqual(app.store.load("world").world_upgrades,receipts)
            with self.assertRaises(ValueError):
                tools._post("/api/world/open",{"scene":"world","fresh":True})
            # Remove the cached room to exercise disk-backed reset protection.
            with self.assertRaisesRegex(ValueError,"material history"):
                room_store.room_for(app,"world",None,True)
            self.assertEqual(app.store.load("world").fabrication_record,before)
            ctx["session"]=app.live.session.id
            with self.assertRaisesRegex(ValueError,"already supplied"):
                call("configure",settings=settings(),request_id="main-config-0002")
            self.assertEqual(app.room.fabrication_record,before)
            durable=json.loads(app.store.path_of("world").read_text())
            with mock.patch.object(app.live,"open",side_effect=ValueError("native restore refused")),                     mock.patch.object(app.store,"set_aside_world") as discarded:
                with self.assertRaisesRegex(ValueError,"native restore refused"):
                    tools._post("/api/world/open",{"scene":"world","again":True})
                discarded.assert_not_called()
            after_failed=json.loads(app.store.path_of("world").read_text())
            durable.pop("saved_unix_s"); after_failed.pop("saved_unix_s")
            self.assertEqual(after_failed,durable)

    def test_http_mcp_restart_and_room_switch_keep_both_halves(self):
        app=self.native_server()
        import fabrication_mcp_tools as tools
        from circuit_api import validate
        from concurrent.futures import ThreadPoolExecutor
        with mock.patch.dict(os.environ,{"BANJO_PLAYGROUND_URL":f"http://127.0.0.1:{app.port}"}):
            opened=tools.call("fabrication_open",{})
            ctx={k:opened[k] for k in ("scene","session")}
            def call(op,**body):
                args={**ctx,**body}
                tool=next(t for t in tools.TOOLS if t["name"]=="fabrication_"+op)
                validate(args,tool["inputSchema"],"arguments")
                return tools.call(tool["name"],args)
            self.assertFalse(call("state")["configured"])
            call("configure",settings=settings(),request_id="config-http-0001")
            q=call("quote",candidate=candidate(),stock_kg=10)
            self.assertTrue(q["affordable"])
            # Two people attempt to spend the same revision: only one succeeds.
            def attempt(ident):
                try:return call("start",candidate=candidate(),stock_kg=10,request_id=ident,revision=0)
                except ValueError:return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                answers=list(pool.map(attempt,["job-http-0001","job-http-0002"]))
            self.assertEqual(sum(a is not None for a in answers),1)
            state=call("wait",seconds=1)["state"]
            job=next(iter(state["jobs"]))
            state=call("pause",job_id=job,revision=state["revision"],request_id="pause-http-0001")["state"]
            yard=self.post(app,"/api/world/open",{"scene":"yard"})
            self.post(app,"/api/live/act",{"session":yard["session"],"op":"step","dt":1/240,"n":120})
            yard_before=workshop_install._snapshot(app.live)
            reopened=self.post(app,"/api/world/open",{"scene":"fabrication"})
            ctx["session"]=reopened["session"]
            self.assertEqual(call("state")["state"],state)
            returned_yard=self.post(app,"/api/world/open",{"scene":"yard"})
            self.assertEqual(returned_yard["restored"]["tier"],"whole")
            self.assertEqual(workshop_install._snapshot(app.live),yard_before)
            reopened=self.post(app,"/api/world/open",{"scene":"fabrication"})
            ctx["session"]=reopened["session"]
            # Drop the process's room cache, reopen from the durable paired save.
            app.live.shutdown();app.room=None;app.rooms={};app.live_holder=None
            reopened=self.post(app,"/api/world/open",{"scene":"fabrication"})
            ctx["session"]=reopened["session"]
            self.assertEqual(reopened["restored"]["tier"],"whole")
            self.assertEqual(call("state")["state"],state)
            state=call("resume",job_id=job,revision=state["revision"],request_id="resume-http-0001")["state"]
            call("wait",seconds=1)
            p=call("preview",job_id=job,position_m=[0,0])
            r=call("commit",job_id=job,preview_id=p["preview_id"],request_id="install-http-0001")
            ctx["session"]=r["session"]
            self.assertEqual(call("state")["state"]["jobs"][job]["status"],"installed")
            status,_,raw=self.request(app,"POST","/api/world/open",{"scene":"fabrication","fresh":True})
            self.assertEqual(status,400,raw)
            status,_,raw=self.request(app,"POST","/api/world/ask",{"message":"spawn free stock"})
            self.assertEqual(status,400,raw)
            status,_,raw=self.request(app,"GET","/fabrication")
            self.assertEqual(status,200);self.assertIn(b"fabrication.js",raw)
            checklist=self.get(app,"/api/gameplay/capabilities")
            self.assertEqual({i["id"] for i in checklist["items"]},set(range(1,31)))

    def test_actual_platform_and_legacy_protocol_publish_fabrication_tools(self):
        app=self.native_server()
        import banjo_mcp_tests as protocol
        with mock.patch.dict(os.environ,{"BANJO_PLAYGROUND_URL":f"http://127.0.0.1:{app.port}"}):
            for entrypoint in ("banjo_mcp.py","banjo_platform_mcp.py"):
                with self.subTest(server=entrypoint),mock.patch.object(protocol,"SERVER",ROOT/"mcp"/entrypoint):
                    client=protocol.Client()
                    try:
                        client.send("initialize",{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"fabrication-qa","version":"1"}})
                        names=[t["name"] for t in client.send("tools/list")["result"]["tools"]]
                        self.assertEqual(len(names),len(set(names)));self.assertIn("fabrication_start",names)
                        self.assertIn("fabrication_qa_run",names)
                        self.assertEqual(client.call("fabrication_qa_status"),{"runs":[]})
                        context=client.call("fabrication_open")
                        read=client.call("fabrication_state",session=context["session"],scene="fabrication")
                        self.assertFalse(read["configured"])
                        client.refuse("fabrication_configure",session=context["session"],scene="fabrication",
                            request_id="refuse-config-0001",settings={"mode":"free"})
                    finally:client.close()


if __name__=="__main__":unittest.main()
