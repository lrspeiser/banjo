"""Native starting-world upgrade transactions and conservation of saved state."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]
import live_session
import room_store
import world_room
import world_upgrades as upgrades
sys.path.insert(0, str(ROOT / 'tools'))
import upgrade_cube_world

ENGINE = Path(os.environ.get("BANJO_LIVE_ENGINE", ROOT / "build/ci/banjo_live_world_run"))


class CubeUpgradeRecord(unittest.TestCase):
    def record(self):
        spec = {'terrain': {'generate': {'kind': 'valley', 'seed': 4},
                            'edits': [{'dig': {'depth_m': .007}}]}, 'bodies': []}
        return {'spec': spec, 'world': {'spec_digest': live_session.spec_digest(spec), 't_s': 42,
            'ground': {'surface': 'smooth', 'grid': [156,125,.25,-19.375,-15.5],
                       'soil': 'unchanged', 'ledger': {'dug': 12.93}}, 'future_field': {'keep': True}},
            'players': {'alice': {'inventory': ['pick'], 'raw': {'sand': 12.93}}},
            'fabrication': {'energy_j': 1234}, 'future_account': {'keep': True}}

    def test_upgrade_changes_only_paired_surface_digest_and_receipt(self):
        original = self.record()
        before = deepcopy(original)
        changed = upgrades.cube_digging_record(original)
        self.assertEqual(original, before)
        self.assertEqual(changed['spec']['terrain']['surface'], 'columns')
        self.assertEqual(changed['world']['ground']['surface'], 'columns')
        self.assertEqual(changed['world']['spec_digest'], live_session.spec_digest(changed['spec']))
        self.assertEqual(upgrades.cube_digging_record(changed), changed, 'an upgrade cannot repeat')
        del changed['spec']['terrain']['surface']
        changed['world']['ground']['surface'] = 'smooth'
        changed['world']['spec_digest'] = before['world']['spec_digest']
        del changed['world_upgrades']
        self.assertEqual(changed, before, 'all material, player, energy and future state retained')

    def test_mismatched_source_and_ground_refuse_instead_of_resetting(self):
        for key in ('digest', 'surface', 'missing'):
            record = self.record()
            if key == 'digest':record['world']['spec_digest'] = 'wrong'
            if key == 'surface':record['world']['ground']['surface'] = 'cuts'
            if key == 'missing':record['world'].pop('ground')
            with self.subTest(key=key), self.assertRaises(ValueError):
                upgrades.cube_digging_record(record)


@unittest.skipUnless(ENGINE.is_file(), "Build the native world runner")
class NativeUpgrades(unittest.TestCase):
    def test_cube_wire_receipts_keep_progress_rock_volume_mass_and_owner(self):
        # Static legacy wire calls supply no work. Paid reduced cuts use an
        # explicit finite source; oak retains its native hardness refusal.
        for material in ('glass','oak','iron'):
            with self.subTest(material=material):
                spec={'algorithm':'lattice','cell_m':.04,'duration_s':1,
                    'terrain':{'surface':'columns','generate':{'kind':'flat','nx':20,'nz':20,
                        'cell_m':.25,'soil_m':0,'sand_m':0,'discharge_m3_s':0}},
                    'bodies':[{'name':'pick','shape':'box','material':material,
                        'size_mm':[900,40,40],'center_mm':[0,100,0]}]}
                self.app.live.open(self.app,{'spec':spec})
                def send(**request):
                    with self.app.live.as_actor('alice'):
                        return self.app.live.session.send(**request)
                send(op='tool_point',body='pick',tip=[.45,.1,0],pointing=[1,0,0],
                    width_m=.04,thickness_m=.04,angle_deg=30,length_m=.04,grip=[-.4,.1,0])
                send(op='wield',name='pick',grip=[-.4,.1,0])
                initial=self.snapshot()['ground']
                for _ in range(10):
                    answer=send(op='strike-cell',at_m=[1,-.375,1])
                    receipt=answer['ground_work'][-1];cut=answer['ground_cut']
                    self.assertEqual('alice',receipt['actor']);self.assertFalse(receipt['open'])
                    self.assertEqual(0,receipt['broken_share']);self.assertEqual(0,receipt['loosened']['rock_m3'])
                    self.assertEqual(0,cut['requested_work_j']);self.assertEqual(0,cut['consumed_work_j'])
                    self.assertFalse(cut['supported'])
                self.assertEqual(initial,self.snapshot()['ground'],'Legacy calls cannot invent paid work, progress or matter')
                self.assertEqual([],send(op='ground-debris')['ground_debris']['bodies'])
                spent=0.
                for n in range(1,11):
                    source=f'wire-reservoir:{material}:{n}'
                    command={'op':'strike-cell','at_m':[1,-.375,1],'work_j':50000.,'work_source':source}
                    answer=send(**command);cut=answer['ground_cut'];receipt=answer['ground_work'][-1]
                    self.assertEqual('alice',receipt['actor']);self.assertFalse(receipt['open'])
                    self.assertEqual(source,cut['work_source']);self.assertEqual(50000.,cut['requested_work_j'])
                    if material=='oak':
                        self.assertFalse(cut['supported']);self.assertEqual(0,cut['consumed_work_j'])
                        self.assertEqual(0,receipt['broken_share']);self.assertEqual(0,receipt['loosened']['rock_m3'])
                        continue
                    self.assertTrue(cut['supported'],cut);self.assertAlmostEqual(468750.,cut['required_work_j'])
                    self.assertAlmostEqual(min(50000.,468750.-spent),cut['consumed_work_j'])
                    spent+=cut['consumed_work_j']
                    self.assertAlmostEqual(min(1.,spent/468750.),cut['broken_share'])
                    if n<10:self.assertEqual(0,cut['loosened']['rock_m3'])
                    else:
                        self.assertAlmostEqual(.25**3,cut['loosened']['rock_m3'])
                        self.assertAlmostEqual(37.5,cut['mass_kg'])
                        self.assertEqual('cut component released',cut['kind'])
                    if n==5:
                        partial=self.snapshot()
                        reopened=self.app.live.open(self.app,{'spec':spec,'snapshot':partial})
                        self.assertEqual('whole',reopened['restored']['tier'])
                        self.assertEqual(partial['ground'],self.snapshot()['ground'])
                        self.assertEqual(cut,send(**command)['ground_cut'],'Reopen must retain exact funded receipt')
                        self.assertEqual(partial['ground'],self.snapshot()['ground'],'Replay cannot consume work twice')
                if material=='oak':
                    self.assertEqual(initial,self.snapshot()['ground'],'An inadmissible tool cannot spend work or change terrain')
                    self.assertEqual([],send(op='ground-debris')['ground_debris']['bodies'])
                    continue
                self.assertAlmostEqual(468750.,spent)
                bodies=send(op='ground-debris')['ground_debris']['bodies'];self.assertEqual(1,len(bodies))
                component=bodies[0];self.assertEqual(125,len(component['cells']))
                self.assertEqual(125,len({cell['id'] for cell in component['cells']}))
                self.assertAlmostEqual(.25**3,sum(c['volume_m3'] for c in component['cells']))
                self.assertAlmostEqual(37.5,sum(c['mass_kg'] for c in component['cells']))
                self.assertAlmostEqual(spent,component['source_work_j'])
                for cell in component['cells']:
                    self.assertAlmostEqual(cell['density_kg_m3']*cell['volume_m3'],cell['mass_kg'])
                complete=self.snapshot()
                reopened=self.app.live.open(self.app,{'spec':spec,'snapshot':complete})
                self.assertEqual('whole',reopened['restored']['tier'])
                self.assertEqual(complete['ground'],self.snapshot()['ground'])
                self.assertEqual(bodies,send(op='ground-debris')['ground_debris']['bodies'])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.room = world_room.Room("world")
        self.package = upgrades.catalog("world")[0]
        self.names = {b["name"] for b in self.package["bodies"]}
        self.room.spec["bodies"] = [b for b in self.room.spec["bodies"] if b["name"] not in self.names]
        self.room.spec["joints"] = [j for j in self.room.spec["joints"]
                                   if j["a"] not in self.names and j["b"] not in self.names]
        self.room.spec["actions"] = [a for a in self.room.spec["actions"] if a["body"] not in self.names]
        self.room.spec.pop("machines", None)
        # Test a settled/supported thermal boundary. Active schedules have
        # their own rejection test below because native carry omits them.
        self.room.spec.pop("thermo", None)
        self.app = SimpleNamespace(room=self.room, live=live_session.Live(),
            engine_path=ENGINE, runs_path=Path(self.tmp.name) / "runs",
            store=room_store.RoomStore(Path(self.tmp.name) / "rooms"), live_holder="world",
            live_inprocess=False, on_live_reply=None)
        self.addCleanup(self.app.live.shutdown)
        self.opened = self.app.live.open(self.app, {"spec": self.room.spec})

    def snapshot(self):
        value, reason = self.app.live.snapshot()
        self.assertIsNotNone(value, reason)
        return value

    def step(self, seconds):
        for _ in range(round(seconds * 30)):
            self.app.live.session.send(op="step", dt=1 / 240, n=8)

    def test_cube_upgrade_keeps_dug_ground_water_bodies_and_accounts(self):
        for surface in ('smooth', 'cuts'):
            with self.subTest(surface=surface):
                spec = deepcopy(self.room.spec)
                spec['terrain']['surface'] = surface
                self.app.live.open(self.app, {'spec': spec})
                self.app.live.session.send(op='dig', **{'from': [2,1], 'to': [2,1], 'width_m': .125, 'depth_m': .25})
                before = self.snapshot()
                self.room.spec = spec
                self.room.world_record = before
                self.assertTrue(self.app.store.save(self.room))
                record = json.loads(self.app.store.path_of(self.room.scene).read_text(encoding='utf-8'))
                candidate = upgrades.cube_digging_record(record)
                upgrade_cube_world.verify(candidate, ENGINE.parent)
                self.assertEqual(candidate['world']['ground']['ledger'], before['ground']['ledger'])
                self.assertEqual(candidate['world']['water'], before['water'])
                opened = self.app.live.open(self.app, {'spec': candidate['spec'], 'snapshot': candidate['world']})
                self.assertEqual(opened['restored']['tier'], 'whole')
                self.assertEqual(opened['terrain']['surface'], 'columns')
                self.assertEqual(opened['t'], before['t_s'])

    def test_addition_preserves_running_world_and_restart_receipt(self):
        self.step(.2)
        before = self.snapshot()
        old = self.app.live.session
        opened, receipt = upgrades.apply_one(self.app, self.package)
        self.assertEqual(receipt["status"], "installed")
        self.assertIsNot(old, self.app.live.session)
        after = self.snapshot()
        upgrades.verify(before, after, self.names, self.package)
        self.assertEqual(after["water"], before["water"])
        self.assertEqual(after["t_s"], before["t_s"])
        self.assertTrue(any(b["name"] == "hoist: crate" for b in opened["bodies"]))
        # Operate the added machine, then prove repeat calls cannot refill it.
        motor = self.app.live.session.state["machines"]["motors"][0]
        self.app.live.session.send(op="drive", motor=motor["id"], command=1)
        self.step(.5)
        spent = self.snapshot()
        self.assertLess(spent["energy_stores"][0]["charge_j"], 5000)
        self.assertIsNone(upgrades.apply_one(self.app, self.package)[0])
        self.assertEqual(self.snapshot(), spent)
        self.room.world_record = spent
        self.app.store.save(self.room)
        loaded = self.app.store.load("world")
        self.assertIn(self.package["id"], loaded.world_upgrades)
        self.app.room = loaded
        self.app.live.open(self.app, {"spec": loaded.spec, "snapshot": loaded.world_record})
        charge = self.snapshot()["energy_stores"][0]["charge_j"]
        upgrades.apply_one(self.app, self.package)
        self.assertEqual(self.snapshot()["energy_stores"][0]["charge_j"], charge)

    def test_failed_save_keeps_original_process_and_world(self):
        before, old, spec = self.snapshot(), self.app.live.session, deepcopy(self.room.spec)
        with mock.patch.object(self.app.store, "save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                upgrades.apply_one(self.app, self.package)
        self.assertIs(self.app.live.session, old)
        self.assertEqual(self.room.spec, spec)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(getattr(self.room, "world_upgrades", {}))

    def test_partial_existing_equipment_is_not_replaced(self):
        self.room.spec["bodies"].append(deepcopy(self.package["bodies"][0]))
        self.app.live.open(self.app, {"spec": self.room.spec})
        before = self.snapshot()
        answer = upgrades.apply(self.app, {})
        self.assertEqual(answer["world_upgrades"][0]["status"], "pending")
        self.assertIn("part", answer["world_upgrades"][0]["reason"])
        self.assertEqual(self.snapshot(), before)

    def test_active_heater_is_not_erased(self):
        self.app.live.session.send(op="heat", target="oak crate", power_w=100, seconds=10)
        before = self.snapshot()
        answer = upgrades.apply(self.app, {})
        self.assertEqual(answer["world_upgrades"][0]["status"], "installed")
        upgrades.verify(before, self.snapshot(), self.names, self.package)
        self.assertEqual(self.snapshot()["heat"], before["heat"])

    def test_existing_equipment_is_recorded_without_refilling(self):
        self.room.spec = world_room.world()
        self.room.spec.pop("thermo", None)
        self.app.live.open(self.app, {"spec": self.room.spec})
        self.app.live.session.send(op="drive", motor=1, command=1)
        self.step(.5)
        before = self.snapshot()
        opened, receipt = upgrades.apply_one(self.app, self.package)
        self.assertIsNone(opened)
        self.assertEqual(receipt["status"], "present")
        self.assertEqual(self.snapshot(), before)
        # Removal after receipt is an intentional player edit, not a reason
        # to hand out the same starting resources again.
        self.room.spec["bodies"] = [b for b in self.room.spec["bodies"] if b["name"] not in self.names]
        self.assertIsNone(upgrades.apply_one(self.app, self.package)[0])
        self.assertEqual(self.snapshot(), before)

    def test_collision_refusal_uses_current_geometry(self):
        intruder = deepcopy(self.package["bodies"][2])
        intruder["name"] = "player build"
        self.room.spec["bodies"].append(intruder)
        self.app.live.open(self.app, {"spec": self.room.spec})
        before = self.snapshot()
        answer = upgrades.apply(self.app, {})
        self.assertEqual(answer["world_upgrades"][0]["status"], "pending")
        self.assertRegex(answer["world_upgrades"][0]["reason"], "overlap|same cells")
        self.assertEqual(self.snapshot(), before)

    def test_http_and_mcp_share_the_upgrade_and_return_current_session(self):
        from http.server import ThreadingHTTPServer
        from urllib import request
        import server
        import world_upgrade_mcp_tools
        self.app.live.session.send(op="heat", target="oak crate", power_w=100, seconds=10)
        active_heat = self.snapshot()["heat"]
        with mock.patch.object(server, "local_configuration", return_value=("", "unused")):
            host = server.Playground(ENGINE, ENGINE, self.app.runs_path)
        self.addCleanup(host.pool.shutdown, wait=True)
        host.live = self.app.live
        host.room, host.rooms, host.store = self.room, {"world": self.room}, self.app.store
        host.live_holder, host.live_inprocess = "world", False
        host.password, host.public_host = None, None
        host.world_lock = threading.Lock()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.app = host
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        url = f"http://127.0.0.1:{httpd.server_port}"
        body = json.dumps({"scene": "world"}).encode()
        req = request.Request(url + "/api/world/open", data=body,
            headers={"Content-Type": "application/json", "X-Banjo-Token": host.csrf_token})
        with request.urlopen(req, timeout=15) as response:
            opened = json.load(response)
        self.assertEqual(opened["world_upgrades"][0]["status"], "installed")
        self.assertEqual(active_heat, self.snapshot()["heat"])
        self.assertEqual(opened["session"], host.live.session.id)
        core = SimpleNamespace(TOOLS=[], HANDLERS={}, Refused=ValueError)
        world_upgrade_mcp_tools.register(core)
        before = self.snapshot()
        with mock.patch.dict(os.environ, {"BANJO_PLAYGROUND_URL": url}):
            mcp = core.HANDLERS["world_open_saved"]({})
        self.assertEqual(mcp["world_upgrades"][0]["status"], "already_applied")
        self.assertEqual(mcp["session"], host.live.session.id)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
