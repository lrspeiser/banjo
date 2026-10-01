"""Source/receiving invariants, exact machine runtime and durable save failure."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"playground"),str(ROOT)]
from mcp import ground_transfers as ledger, fabrication
import machine_routine
import room_store
import server
import world_room
import rover_brain
import live_session


def packet(volume):
    return {"schema":"banjo.bulk-material.v1","source":"excavated_ground",
            "form":"granular","thermal_state":"unmodeled",
            "contents":[{"substance":"soil","volume_m3":volume,"mass_kg":volume*1600}]}


def withdraw(book,holder,volume,ident):
    return ledger.accept(ledger.prepare(book,holder,"withdraw",{"soil_m3":volume},ident),
                         holder,"withdraw",ident,{"material_packet":packet(volume)})


class ReceivingLedger(unittest.TestCase):
    def test_two_holders_and_fabrication_share_exact_native_totals(self):
        book=withdraw(None,"machine:a",.0123456789,"a")
        book=withdraw(book,"machine:b",.02,"b")
        before=deepcopy(book)
        with self.assertRaisesRegex(ValueError,"exceeds"):
            ledger.prepare(book,"machine:b","return",{"soil_m3":.03},"over")
        self.assertEqual(before,book)
        book=ledger.accept(ledger.prepare(book,"machine:a","return",{"soil_m3":.01},"back"),
            "machine:a","return","back",{"ground_returned":{"sand_m3":0.,"soil_m3":.01,"rock_m3":0.}})
        state={"raw_lots":{"raw":packet(.001)}}
        native={"ground":{"exported":{"soil_m3":.0333456789},"returned":{"soil_m3":.01}}}
        fabrication.validate_ground_stock(state,native,book)
        with self.assertRaisesRegex(ValueError,"ground receipts"):
            fabrication.validate_ground_stock(state,native)
        self.assertAlmostEqual(.0023456789,ledger.totals(book)["holders"]["machine:a"]["soil_m3"],places=15)

    def test_duplicate_corrupt_density_and_unsupported_rock_are_refused(self):
        book=withdraw(None,"machine:a",.01,"a")
        with self.assertRaisesRegex(ValueError,"already"):
            ledger.prepare(book,"machine:a","withdraw",{"soil_m3":.01},"a")
        for alter in (lambda b:b["receipts"].append(deepcopy(b["receipts"][0])),
                      lambda b:b["receipts"][0]["packet"]["contents"][0].update(mass_kg=1),
                      lambda b:b["receipts"][0]["quantities"].update(soil_m3=.02)):
            bad=deepcopy(book); alter(bad)
            with self.assertRaises(ValueError): ledger.totals(bad)
        with self.assertRaisesRegex(ValueError,"rock"):
            ledger.prepare(None,"machine:a","withdraw",{"rock_m3":.01},"rock")


class RuntimeAndSave(unittest.TestCase):
    def test_durable_goal_reader_serializes_with_checkpoint_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            store=room_store.RoomStore(folder);room=world_room.Room('yard')
            room.world_record={'t_s':1};store.save(room)
            begun=threading.Event();release=threading.Event();written=threading.Event();read=[]
            original=Path.read_text
            def reading(path,*args,**kwargs):
                begun.set();self.assertTrue(release.wait(2));return original(path,*args,**kwargs)
            def writing():
                room.world_record={'t_s':2};store.save(room);written.set()
            reader=threading.Thread(target=lambda:read.append(store.read_record('yard')))
            writer=threading.Thread(target=writing)
            with mock.patch.object(Path,'read_text',reading):
                reader.start();self.assertTrue(begun.wait(1));writer.start()
                self.assertFalse(written.wait(.05),'writer replaced an open goal reader')
                release.set();reader.join(timeout=2);writer.join(timeout=2)
            self.assertFalse(reader.is_alive());self.assertFalse(writer.is_alive())
            self.assertEqual(1,read[0]['world']['t_s'])
            self.assertEqual(2,store.read_record('yard')['world']['t_s'])

    def test_ground_edit_does_not_fall_back_to_a_stale_physical_checkpoint(self):
        room=world_room.Room('new-game')
        app=SimpleNamespace(room=room,live_holder='world',
            live=SimpleNamespace(session=SimpleNamespace(spec=room.spec)))
        command={'op':'dig','from':[0,0],'width_m':.5,'depth_m':.1}
        with mock.patch.object(server,'keep_world',return_value=False), \
                mock.patch.object(server.room_store,'keep') as stale:
            server.remember_ground(app,command,{'dug':{'depth_m':.05}})
        stale.assert_not_called()
        self.assertEqual(.05,room.spec['terrain']['edits'][-1]['dig']['depth_m'])

    def test_native_checkpoint_blocks_new_replies_until_source_save_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            room=world_room.Room('yard'); store=room_store.RoomStore(folder)
            live=live_session.Live()
            live.session=SimpleNamespace(_lock=threading.RLock(),t=1.0)
            live.snapshot=lambda:({'t_s':live.session.t},'')
            app=SimpleNamespace(room=room,store=store,live_holder='world',live=live)
            begun=threading.Event(); advanced=threading.Event()
            def reply():
                begun.set()
                # Direct Session.send callers also share this boundary.
                with live.session._lock:
                    live.session.t=2.0; advanced.set()
            original=store.save
            worker=threading.Thread(target=reply)
            def saving(record):
                worker.start(); self.assertTrue(begun.wait(1))
                self.assertFalse(advanced.wait(.05),'native state changed during source save')
                return original(record)
            with mock.patch.object(store,'save',side_effect=saving):
                self.assertTrue(server.keep_world(app,'atomic source checkpoint'))
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertTrue(advanced.is_set())
            self.assertEqual(1.0,store.load('yard').world_record['t_s'])
            self.assertTrue(server.keep_world(app,'later reply'))
            self.assertEqual(2.0,store.load('yard').world_record['t_s'])

    def test_appending_a_scene_keeps_machine_goods_attached_to_the_new_spec(self):
        spec=world_room.Room("tests-dig").spec
        spec["goods"]={"stockpiles":[],"deposits":[],"recipes":[]}
        brains=rover_brain.Brains(lambda:None); brains.opened(spec)
        original=brains.of("rover").routine
        original.load_in(0,.01,16)
        changed=deepcopy(spec)
        brains.rebind(changed)
        self.assertIs(original,brains.of("rover").routine)
        self.assertIs(changed,brains.goods.spec)
        self.assertIs(changed["goods"],brains.goods.block)
        self.assertEqual(16,brains.of("rover").routine.kg)

    def test_exact_hopper_running_order_and_declaration_survive_restart(self):
        declaration={"kind":"dig","places":{"dig site":[1,2],"depot":[3,4]},"hopper_kg":40}
        original=machine_routine.Routine("any new name",declaration)
        original.load_in(.00123456789,.00234567891,(.00123456789+.00234567891)*1600)
        original.order("wait here",[{"do":"hold_still","args":{"for_s":1},"until":"done"}])
        original.frame.issued={"did":"waiting"}; original.frame.issued_t=10.123456789
        record=original.record()
        restored=machine_routine.Routine("any new name",declaration); restored.restore(record)
        self.assertEqual(record,restored.record())
        with self.assertRaisesRegex(ValueError,"declaration"):
            machine_routine.Routine("any new name",dict(declaration,hopper_kg=20)).restore(record)
        bad=deepcopy(record); bad["soil_m3"]=10
        with self.assertRaisesRegex(ValueError,"mass"): restored.restore(bad)
        self.assertEqual(record,restored.record())

    def test_failed_replace_keeps_old_checkpoint_and_returns_false_with_status(self):
        with tempfile.TemporaryDirectory() as folder:
            store=room_store.RoomStore(folder); room=world_room.Room("yard")
            saved={"t_s":1.0}
            room.world_record=saved; self.assertTrue(store.save(room))
            old=store.path_of("yard").read_bytes()
            app=SimpleNamespace(room=room,store=store,live_holder="world",
                live=SimpleNamespace(session=object(),snapshot=lambda:({"t_s":2.0},"")))
            with mock.patch("room_store.os.replace",side_effect=OSError("disk full")):
                self.assertFalse(server.keep_world(app,"fault injection"))
            self.assertEqual("failed",room.persistence["state"])
            self.assertEqual(1.0,room.persistence["saved_t_s"])
            self.assertEqual(old,store.path_of("yard").read_bytes())
            self.assertTrue(server.keep_world(app,"recovered"))
            self.assertEqual("saved",room.persistence["state"])
            self.assertEqual(2.0,room.world_saved_t)


if __name__=="__main__": unittest.main()
