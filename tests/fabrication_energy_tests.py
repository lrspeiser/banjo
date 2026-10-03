"""Native battery funding: power windows, paired persistence and fabrication."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "tests")]
from fabrication_tests import settings, candidate
from mcp import fabrication as model
import fabrication_room as api
import live_session, room_store, world_room, workshop_install
from workbench_tests import WorkbenchTestCase
ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None


class EnergyLedger(unittest.TestCase):
    def fixture(self):
        state = model.new(settings(energy_j=0), 0)
        state["energy_connection"] = {"scene": "fabrication", "store": 1,
            "name": "battery", "body": "marker stone", "power_w": 250., "since_s": 0., "given_j": 0.}
        model.advance(state, 2)
        before = {"id": 1, "name": "battery", "body": "marker stone", "capacity_j": 2000.,
            "charge_j": 2000., "given_j": 0., "taken_j": 0., "short_j": 0.,
            "voltage_v": 24., "max_power_w": 300.}
        after = {**before, "charge_j": 1500., "given_j": 500.}
        packet = {"schema": "banjo.fabrication-energy-transfer.v1", "scene": "fabrication",
            "started_s": 0., "time_s": 2., "given_started_j": 0., "power_w": 250., "joules": 500., "before": before, "after": after}
        body = {"op": "fund_energy", "joules": 500., "store_hash": model.digest(before),
            "revision": 0, "request_id": "energy-lot-0001"}
        return state, body, packet

    def test_import_spending_and_serialized_retry_close_the_energy_boundary(self):
        state, body, packet = self.fixture(); original = deepcopy(state)
        funded, replayed = model.receive_energy(state, body, packet)
        self.assertFalse(replayed); self.assertEqual(state, original)
        self.assertEqual(funded["energy_j"], 500)
        self.assertEqual(model.audit(funded)["native_energy_received_j"], 500)
        self.assertEqual(model.audit(funded)["energy_residual_j"], 0)
        loaded = json.loads(json.dumps(funded, sort_keys=True))
        self.assertEqual(model.receive_energy(loaded, body, packet), (loaded, True))
        with self.assertRaisesRegex(ValueError, "different"):
            model.receive_energy(loaded, {**body, "joules": 499}, packet)
        quote = api.compile_quote(candidate(), 10, .04, loaded)
        working, _ = model.mutate(loaded, {"op": "start", "request_id": "funded-job-0001", "revision": 1}, quote=quote)
        model.advance(working, 4)
        self.assertEqual(working["energy_j"], 0)
        self.assertEqual(working["spent_j"], 500)
        self.assertEqual(working["station_heat_j"], 500)
        self.assertEqual(working["jobs"]["funded-job-0001"]["status"], "running")
        self.assertEqual(model.audit(working)["energy_residual_j"], 0)
        model.validate_state(working)

    def test_bad_receipt_power_timing_and_source_snapshots_are_refused(self):
        state, body, packet = self.fixture()
        for key, value in (("power_w", 400), ("started_s", 1), ("joules", 501), ("time_s", 1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                model.receive_energy(state, body, {**packet, key: value})
        funded, _ = model.receive_energy(state, body, packet)
        for field in ("charge_j", "given_j", "taken_j", "short_j", "body"):
            bad = deepcopy(funded)
            bad["energy_imports"][body["request_id"]]["after"][field] = "other" if field == "body" else 1
            with self.subTest(field=field), self.assertRaises(ValueError): model.validate_state(bad)
        model.validate_energy_sources(funded, {"energy_stores": [packet["after"]]}, "fabrication")
        for snapshot, scene in (({"energy_stores": [packet["before"]]}, "fabrication"), ({}, "fabrication"),
                                ({"energy_stores": [packet["after"]]}, "world")):
            with self.assertRaises(ValueError): model.validate_energy_sources(funded, snapshot, scene)
        bad = deepcopy(funded); bad["energy_imports"]["duplicate-0001"] = deepcopy(packet)
        bad["receipts"]["duplicate-0001"] = "forged"; bad["energy_j"] += 500
        with self.assertRaisesRegex(ValueError, "Overlapping"): model.validate_state(bad)


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "Native battery tests require BANJO_LIVE_ENGINE")
class NativeEnergy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.live = live_session.Live(); self.addCleanup(self.live.shutdown)
        self.room = world_room.Room("fabrication")
        self.room.spec["machines"] = {"stores": [{"name": "measured battery", "body": "marker stone",
            "capacity_j": 4000., "charge_j": 4000., "max_power_w": 300., "voltage_v": 24.}]}
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room,
            engine_path=ENGINE, runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"))
        self.live.open(self.app, {"spec": self.room.spec})
        self.call("configure", settings=settings(energy_j=0), request_id="energy-config-0001")

    def context(self): return {"scene": self.room.scene, "session": self.live.session.id}
    def call(self, operation, **fields): return api.request(self.app, operation, {**self.context(), **fields})
    def source(self): return self.call("state")["energy_sources"][0]
    def connect(self, ident="charger-connect-0001", power=250):
        source = self.source()
        return self.call("connect_energy", store=source["id"], store_hash=source["store_hash"], power_w=power,
            revision=self.room.fabrication_record["revision"], request_id=ident)
    def step(self, seconds): return api.wait(self.app, {**self.context(), "seconds": seconds})
    def request(self, joules=500, ident="battery-import-0001"):
        return {**self.context(), "joules": joules, "store_hash": self.source()["store_hash"],
            "revision": self.room.fabrication_record["revision"], "request_id": ident}

    def test_limits_failed_save_restart_retry_and_meter_tamper(self):
        before = workshop_install._snapshot(self.live); funds = deepcopy(self.room.fabrication_record)
        with self.assertRaises(ValueError): self.connect(power=301)
        with mock.patch.object(self.app.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError): self.connect()
        self.assertEqual(before, workshop_install._snapshot(self.live)); self.assertEqual(funds, self.room.fabrication_record)
        self.connect(); request = self.request()
        with self.assertRaisesRegex(ValueError, "power limit"): api.request(self.app, "fund_energy", request)
        self.step(2); request = self.request()
        original = workshop_install._snapshot(self.live); funds = deepcopy(self.room.fabrication_record); old = self.live.session
        with mock.patch.object(self.app.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError): api.request(self.app, "fund_energy", request)
        self.assertIs(self.live.session, old); self.assertEqual(original, workshop_install._snapshot(self.live))
        self.assertEqual(self.room.fabrication_record, funds)
        result = api.request(self.app, "fund_energy", request)
        self.assertFalse(result["replayed"]); self.assertTrue(old._closed)
        actual = workshop_install._snapshot(self.live); expected = deepcopy(original)
        expected["energy_stores"][0].update(charge_j=3500., given_j=500.)
        self.assertEqual(actual, expected)
        self.assertEqual(self.room.fabrication_record["energy_j"], 500)
        self.assertEqual(self.source()["transfer_available_j"], 0)
        self.assertTrue(api.request(self.app, "fund_energy", request)["replayed"])
        with self.assertRaisesRegex(ValueError, "different"):
            api.request(self.app, "fund_energy", {**request, "joules": 499})
        saved = self.app.store.load("fabrication")
        self.live.open(self.app, {"spec": saved.spec, "snapshot": saved.world_record})
        self.room = self.app.room = saved
        self.assertEqual(self.live.session.state["restored"]["tier"], "whole")
        self.assertTrue(api.request(self.app, "fund_energy", request)["replayed"])
        self.assertEqual(workshop_install._snapshot(self.live), actual)
        with self.assertRaisesRegex(ValueError, "power limit"):
            api.request(self.app, "fund_energy", self.request(1, "battery-import-0002"))
        # Detect a receiving ledger paired with the old source meter on reload.
        path = self.app.store.path_of("fabrication"); record = json.loads(path.read_text())
        record["world"]["energy_stores"][0]["given_j"] = 0
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "meter is behind"): self.app.store.load("fabrication")

    def test_stale_source_shared_revision_reconnect_and_insufficient_supply(self):
        self.connect(); self.step(2)
        stale = self.request()
        self.live.session.send(op="draw", store=1, joules=1)
        before = workshop_install._snapshot(self.live); state = deepcopy(self.room.fabrication_record)
        with self.assertRaisesRegex(ValueError, "source changed"): api.request(self.app, "fund_energy", stale)
        self.assertEqual(before, workshop_install._snapshot(self.live)); self.assertEqual(state, self.room.fabrication_record)
        self.connect("charger-connect-0002")
        self.assertEqual(self.source()["transfer_available_j"], 0)
        with self.assertRaisesRegex(ValueError, "revision"):
            api.request(self.app, "fund_energy", {**self.request(), "revision": 1})
        self.step(10); self.step(10)
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            api.request(self.app, "fund_energy", self.request(4000))

    def test_other_consumers_share_source_power_and_reconnect_cannot_reuse_time(self):
        self.connect(); self.step(2)
        self.live.session.send(op="draw", store=1, joules=600)
        self.assertEqual(self.source()["transfer_available_j"], 0)
        before = workshop_install._snapshot(self.live); state = deepcopy(self.room.fabrication_record)
        with self.assertRaisesRegex(ValueError, "Source power limit"):
            api.request(self.app, "fund_energy", self.request(1))
        self.assertEqual(before, workshop_install._snapshot(self.live)); self.assertEqual(state, self.room.fabrication_record)
        self.step(2)
        self.assertAlmostEqual(self.source()["transfer_available_j"], 600, places=7)
        api.request(self.app, "fund_energy", self.request())
        self.assertEqual(self.source()["charge_j"], 2900)
        self.assertEqual(self.room.fabrication_record["energy_j"], 500)
        self.assertEqual(self.source()["transfer_available_j"], 0)
        self.connect("charger-connect-0002")
        self.assertEqual(self.source()["transfer_available_j"], 0)

    def test_live_store_binding_preserves_current_limits_exact_debit_and_retry(self):
        source=self.source(); binding=source['store_binding_hash']
        self.live.session.send(op='draw',store=source['id'],joules=1.)
        self.call('connect_energy',store=source['id'],store_hash=binding,power_w=250.,
            revision=self.room.fabrication_record['revision'],request_id='binding-connect-0001')
        self.step(2)
        self.live.session.send(op='draw',store=source['id'],joules=1.)
        request={**self.context(),'store_hash':binding,'joules':500.,
            'revision':self.room.fabrication_record['revision'],'request_id':'binding-fund-0001'}
        before=workshop_install._snapshot(self.live)
        api.request(self.app,'fund_energy',request)
        after=workshop_install._snapshot(self.live)
        self.assertAlmostEqual(before['energy_stores'][0]['charge_j']-after['energy_stores'][0]['charge_j'],500.)
        self.assertEqual(self.room.fabrication_record['energy_j'],500.)
        self.assertTrue(api.request(self.app,'fund_energy',request)['replayed'])
        self.assertEqual(after,workshop_install._snapshot(self.live))
        self.assertEqual(model.audit(self.room.fabrication_record)['native_transfer_residual_j'],0.)
        for field,value in [('capacity_j',4001.),('body','other'),('max_power_w',301.),('voltage_v',25.),('name','other'),('id',2)]:
            altered={**source,field:value}
            self.assertNotEqual(binding,model.energy_source_binding(altered))
            with self.assertRaisesRegex(ValueError,'source changed'):
                self.call('fund_energy',store_hash=model.energy_source_binding(altered),joules=1.,
                    revision=self.room.fabrication_record['revision'],request_id='binding-altered-'+field)
            self.assertEqual(after,workshop_install._snapshot(self.live))
        for joules,why in [(4000.,'Insufficient'),(1.,'power limit')]:
            rejected={**self.context(),'store_hash':binding,'joules':joules,
                'revision':self.room.fabrication_record['revision'],'request_id':f'binding-reject-{int(joules)}'}
            with self.assertRaisesRegex(ValueError,why):api.request(self.app,'fund_energy',rejected)
            self.assertEqual(after,workshop_install._snapshot(self.live))

    def test_process_state_stays_readable_when_native_transfer_snapshot_is_unavailable(self):
        before = deepcopy(self.room.fabrication_record)
        with mock.patch.object(self.live, "snapshot", return_value=(None, "native stroke in progress")):
            reading = self.call("state")
        self.assertEqual(reading["energy_sources"], [])
        self.assertEqual(reading["energy_source_status"], {"state": "unavailable", "reason": "native stroke in progress"})
        self.assertEqual(reading["state"]["stock_kg"], before["stock_kg"])
        self.assertEqual(self.room.fabrication_record, before)

    def test_battery_funded_native_products_glass_oak_iron(self):
        measurements = []
        self.connect()
        for index, material in enumerate(("glass", "oak", "iron")):
            self.step(4)
            before = self.source()
            api.request(self.app, "fund_energy", self.request(1000, "product-energy-"+material))
            ident = "battery-job-"+material
            self.call("start", candidate=candidate(material), stock_kg=10,
                revision=self.room.fabrication_record["revision"], request_id=ident)
            self.step(2)
            preview = api.preview(self.app, {**self.context(), "job_id": ident, "position_m": [index*.5, 0]})
            receipt = api.commit(self.app, {**self.context(), "job_id": ident,
                "preview_id": preview["preview_id"], "request_id": "battery-install-"+material})
            output = next(b for b in self.live.session.state["bodies"] if b["name"] == receipt["root_body"])
            state = self.room.fabrication_record; audit = model.audit(state)
            self.assertAlmostEqual(audit["energy_residual_j"], 0, places=7)
            self.assertAlmostEqual(audit["work_residual_j"], 0, places=7)
            self.assertAlmostEqual(state["energy_j"], 0, places=7)
            self.assertEqual(before["charge_j"]-self.source()["charge_j"], 1000)
            self.assertAlmostEqual(output["mass_kg"], state["jobs"][ident]["product_kg"], places=7)
            measurements.append({"material": material, "mass_kg": output["mass_kg"],
                "source_draw_j": 1000., "useful_work_j": state["jobs"][ident]["work_j"],
                "output_temperature_k": receipt["thermal_transfer"]["temperature_k"],
                "energy_residual_j": audit["energy_residual_j"], "work_residual_j": audit["work_residual_j"]})
        self.assertEqual(self.source()["charge_j"], 1000)
        self.assertAlmostEqual(self.room.fabrication_record["spent_j"], 3000, places=7)
        self.native_evidence = measurements
        print("BATTERY_FABRICATION_EVIDENCE " + json.dumps(measurements, sort_keys=True))


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "HTTP battery tests require BANJO_LIVE_ENGINE")
class EnergyHTTP(WorkbenchTestCase):
    def test_same_http_and_mcp_charger_meter_receipts_and_rejoin(self):
        import fabrication_mcp_tools as tools
        from circuit_api import validate
        app = self.start(); app.live = live_session.Live(); app.engine_path = ENGINE
        self.addCleanup(app.live.shutdown)
        opened = self.post(app, "/api/world/open", {"scene": "world"})
        # Explicitly author a finite-output battery in this isolated fixture.
        # Legacy scene batteries use native 0 = unbounded output; the bounded
        # charger refuses those instead of inventing a physical power limit.
        host = next(b for b in app.room.spec["bodies"] if b.get("anchored"))
        app.room.spec.setdefault("machines", {}).setdefault("stores", []).append({
            "name": "HTTP fixture battery", "body": host["name"], "capacity_j": 2000.,
            "charge_j": 2000., "max_power_w": 300., "voltage_v": 24.})
        authored = app.live.open(app, {"spec": app.room.spec})
        ctx = {"scene": "world", "session": authored["session"]}
        self.post(app, "/api/world/fabrication/configure", {**ctx,
            "settings": settings(energy_j=0), "request_id": "http-energy-config-0001"})
        state = self.post(app, "/api/world/fabrication/state", ctx)
        source = next(s for s in state["energy_sources"] if s["max_power_w"] > 0)
        self.assertGreater(source["charge_j"], 500)
        connect = {**ctx, "store": source["id"], "store_hash": source["store_hash"], "power_w": 250,
            "revision": state["state"]["revision"], "request_id": "http-energy-connect-0001"}
        schemas = {t["name"]: t["inputSchema"] for t in tools.TOOLS}
        validate(connect, schemas["fabrication_connect_energy"], "arguments")
        with mock.patch.dict(os.environ, {"BANJO_PLAYGROUND_URL": f"http://127.0.0.1:{app.port}"}):
            self.assertFalse(tools.call("fabrication_connect_energy", connect)["replayed"])
            tools.call("fabrication_wait", {**ctx, "seconds": 2})
            reading = tools.call("fabrication_state", ctx)
            now = next(s for s in reading["energy_sources"] if s["connected"])
            request = {**ctx, "store_hash": now["store_hash"], "joules": 500,
                "revision": reading["state"]["revision"], "request_id": "http-energy-import-0001"}
            validate(request, schemas["fabrication_fund_energy"], "arguments")
            first = tools.call("fabrication_fund_energy", request)
            self.assertNotEqual(first["session"], ctx["session"])
            self.assertTrue(tools.call("fabrication_fund_energy", request)["replayed"])
            self.assertEqual(first["state"]["energy_j"], 500)
            self.assertEqual(first["state"]["audit"]["native_transfer_residual_j"], 0)
            saved = app.store.load("world")
            self.assertEqual(saved.fabrication_record, app.room.fabrication_record)
            meter = next(m for m in saved.world_record["energy_stores"] if m["id"] == source["id"])
            self.assertEqual(meter["charge_j"], now["charge_j"]-500)
            self.assertEqual(meter["given_j"], now["given_j"]+500)
            reopened = self.post(app, "/api/world/open", {"scene": "world", "again": True})
            self.assertEqual(reopened["restored"]["tier"], "whole")
            self.assertTrue(tools.call("fabrication_fund_energy", request)["replayed"])
            self.assertEqual(app.room.fabrication_record["energy_j"], 500)


if __name__ == "__main__": unittest.main()
