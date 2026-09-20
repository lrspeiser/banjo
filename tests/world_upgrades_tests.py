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

ENGINE = Path(os.environ.get("BANJO_LIVE_ENGINE", ROOT / "build/ci/banjo_live_world_run"))


@unittest.skipUnless(ENGINE.is_file(), "Build the native world runner")
class NativeUpgrades(unittest.TestCase):
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
