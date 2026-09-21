"""Real transport journeys: native state survives API inspection and restart."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp"))
sys.path.insert(0, str(ROOT / "bindings" / "python"))
from tests import banjo_mcp_tests as protocol
from tests.product_circuit_tests import product
from mcp.product_contract import compile_contract
from mcp.product_circuit import bind_circuit
from circuit_api import CIRCUIT_SCHEMA, validate
import banjo_mcp

# Who each server says it is in its handshake: what its script declares, read
# here rather than written out, because every release bumps it (the literal
# "1.2.0" this test once held went stale at the next release). The world
# server's own declaration is taken before the platform wrapper is imported,
# since the wrapper renames the core's server in place.
DECLARED = {"banjo_mcp.py": dict(banjo_mcp.SERVER)}
import banjo_platform_mcp
DECLARED["banjo_platform_mcp.py"] = dict(banjo_platform_mcp.core.SERVER)

SCENE = {"bodies": [
    {"name": "post", "shape": "box", "material": "iron", "dimensions_m": [.1, .8, .1],
     "center_m": [.5, .4, 0], "anchored": True},
    {"name": "wheel", "shape": "box", "material": "iron", "dimensions_m": [.4, .1, .4],
     "center_m": [.5, 1, 0]}]}


def declaration(store, motor):
    return bind_circuit(compile_contract(product()), "drive", stores={"battery": store},
                        motors={"motor": motor})


class PublicMachineAPI(unittest.TestCase):
    def test_shared_schema_rejects_readonly_misspelled_and_nonfinite_input(self):
        network = declaration(1, 1)
        validate(network, CIRCUIT_SCHEMA)
        for change in ({"ledger": {}}, {"ambient_k": float("nan")}, {"ambient_k": True},
                       {"ambient_k": 10**400}, {"nodes": [[], []]},
                       {"nodes": ["x", "x"]}, {"branches": [{}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(dict(network, **change), CIRCUIT_SCHEMA)

    def test_both_mcp_servers_operate_inspect_refuse_edits_and_resume(self):
        for server in ("banjo_mcp.py", "banjo_platform_mcp.py"):
            with self.subTest(server=server), patch.object(protocol, "SERVER", ROOT / "mcp" / server):
                client = protocol.Client()
                try:
                    self.journey(client, DECLARED[server],
                                 product_install=server.startswith("banjo_platform"))
                finally:
                    client.close()

    def journey(self, client, declared, product_install):
        initialized = client.send("initialize")["result"]
        self.assertEqual(initialized["serverInfo"], declared)
        tools = {t["name"]: t for t in client.send("tools/list")["result"]["tools"]}
        self.assertEqual(tools["circuit"]["inputSchema"]["properties"]["network"], CIRCUIT_SCHEMA)
        objects = [{**{k: v for k, v in body.items() if k not in ("dimensions_m", "center_m")},
                    "size_m": body["dimensions_m"], "position_m": body["center_m"]}
                   for body in SCENE["bodies"]]
        wid = client.call("create_world", objects=objects, cell_size_m=.05)["world_id"]
        client.call("hinge", world_id=wid, a="post", b="wheel", at_m=[.5, 1, 0], axis=[0, 1, 0])
        store = client.call("store", world_id=wid, name="battery", body="post", capacity_j=1000,
                            max_power_w=30)["store_id"]
        motor = client.call("motor", world_id=wid, on=["post", "wheel"], store="battery",
                            stall_torque_n_m=10, no_load_rpm=300 / math.pi)["motor_id"]
        network = declaration(store, motor)
        self.assertIn("unsupported", client.refuse("circuit", world_id=wid,
                                                   network=dict(network, ledger={})))
        self.assertEqual(client.call("circuits", world_id=wid), {"circuits": []})
        if product_install:
            circuit = client.call("install_circuit", world_id=wid, product_graph=product(),
                                  circuit_id="drive", stores={"battery": "battery"},
                                  motors={"motor": "wheel"})["circuit"]
        else:
            circuit = client.call("circuit", world_id=wid, network=network)["circuit"]
        self.assertEqual(circuit, 1)
        client.call("drive", world_id=wid, part="wheel", command=1)
        ran = client.call("run", world_id=wid, seconds=.25)
        self.assertGreater(ran["machines"]["motors"][0]["speed_rad_s"], 0)
        state = client.call("circuits", world_id=wid)
        self.assertEqual(state["circuits"], ran["machines"]["circuits"])
        self.assertGreater(state["circuits"][0]["thermal_nodes"][1]["temperature_k"], 293.15)
        self.assertGreater(state["circuits"][0]["branches"][1]["used_a2_s"], 0)
        for tool, args in (("circuit", {"network": network}),
                           ("circuit_switch", {"circuit": 1, "branch": "switch", "closed": "false"}),
                           ("circuit_switch", {"circuit": -1, "branch": "switch", "closed": False}),
                           ("circuit_switch", {"circuit": 1, "branch": "fuse", "closed": True}),
                           ("remove_object", {"name": "post"}),
                           ("add_object", {"object": dict(objects[0], name="extra")})):
            client.refuse(tool, world_id=wid, **args)
            self.assertEqual(client.call("circuits", world_id=wid), state)
        client.call("circuit_switch", world_id=wid, circuit=circuit, branch="switch", closed=False)
        state = client.call("circuits", world_id=wid)
        checkpoint = client.call("snapshot_world", world_id=wid)["checkpoint"]
        tampered = deepcopy(checkpoint)
        tampered["payload"]["entry"]["cell_m"] = .04
        self.assertIn("edited", client.refuse("restore_world", checkpoint=tampered))
        client.call("close_world", world_id=wid)
        # No server-global state may be needed to resume this envelope.
        client.close()
        client.__init__()
        restored = client.call("restore_world", checkpoint=checkpoint)
        wid = restored["world_id"]
        self.assertEqual(restored["restored"]["tier"], "whole")
        self.assertEqual(restored["circuits"], state["circuits"])
        before = client.call("describe_world", world_id=wid)["machines"]["stores"][0]["charge_j"]
        ran = client.call("run", world_id=wid, seconds=.025)
        self.assertEqual(ran["machines"]["stores"][0]["charge_j"], before)
        client.call("circuit_switch", world_id=wid, circuit=1, branch="switch", closed=True)
        ran = client.call("run", world_id=wid, seconds=.025)
        self.assertLess(ran["machines"]["stores"][0]["charge_j"], before)
        client.call("clear_world", world_id=wid)
        client.call("close_world", world_id=wid)

    def test_a_blown_fuse_survives_mcp_server_restart(self):
        client = protocol.Client()
        self.addCleanup(client.close)
        wid = client.call("create_world", cell_size_m=.05, objects=[{
            "name": "box", "shape": "box", "material": "iron", "size_m": [.1, .1, .1],
            "position_m": [0, .05, 0], "anchored": True}])["world_id"]
        store = client.call("store", world_id=wid, name="battery", body="box", capacity_j=100)["store_id"]
        network = {"schema": "banjo.circuit.v1", "id": "fused", "nodes": ["p", "n"],
                   "source": {"store": store, "positive": "p", "negative": "n",
                              "resistance_ohm": .1, "thermal": "case"},
                   "thermal_nodes": [{"id": "case", "component": "box", "capacity_j_k": 10}],
                   "branches": [{"id": "fuse", "kind": "fuse", "component": "fuse",
                                 "a": "p", "b": "n", "thermal": "case", "resistance_ohm": 1,
                                 "fuse_a2_s": .001}]}
        client.call("circuit", world_id=wid, network=network)
        client.call("run", world_id=wid, seconds=.01)
        before = client.call("circuits", world_id=wid)
        self.assertTrue(before["circuits"][0]["branches"][0]["failed"])
        saved = client.call("snapshot_world", world_id=wid)["checkpoint"]
        client.close()
        client.__init__()
        wid = client.call("restore_world", checkpoint=saved)["world_id"]
        self.assertEqual(client.call("circuits", world_id=wid), before)
        client.refuse("circuit_switch", world_id=wid, circuit=1, branch="fuse", closed=True)
        client.call("run", world_id=wid, seconds=.01)
        after = client.call("circuits", world_id=wid)["circuits"][0]
        self.assertTrue(after["branches"][0]["failed"])
        self.assertEqual(after["ledger"]["source_j"], before["circuits"][0]["ledger"]["source_j"])

    def test_python_switch_validation_does_not_coerce_strings_or_wrap_handles(self):
        import banjo
        with banjo.World(SCENE, cell_size_m=.05) as world:
            for handle, branch, closed in ((-1, "switch", True), (2**32+1, "switch", True),
                                           (1, "switch\0hidden", True), (1, "switch", "false")):
                with self.assertRaises(ValueError):
                    world.circuit_switch(handle, branch, closed)


class RunnerCircuitAPI(unittest.TestCase):
    def test_line_protocol_and_snapshot_keep_circuit_state(self):
        engine = os.environ.get("BANJO_LIVE_ENGINE")
        if not engine:
            self.skipTest("set BANJO_LIVE_ENGINE for runner parity")
        with tempfile.TemporaryDirectory() as folder:
            scene = Path(folder) / "scene.json"
            scene.write_text(json.dumps(SCENE), encoding="utf-8")
            snapshot = Path(folder) / "snapshot.json"

            def open_runner(restore=False):
                p = subprocess.Popen([engine, "--scene", str(scene), "--cell", ".05",
                                      *(["--snapshot", str(snapshot)] if restore else [])],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8")
                def close():
                    if p.poll() is None:
                        p.stdin.write('{"op":"quit"}\n'); p.stdin.flush()
                    p.wait(timeout=10)
                    for stream in (p.stdin, p.stdout, p.stderr): stream.close()
                self.addCleanup(close)
                return p, json.loads(p.stdout.readline())

            p, _ = open_runner()
            def call(**command):
                p.stdin.write(json.dumps(command) + "\n"); p.stdin.flush()
                answer = json.loads(p.stdout.readline())
                self.assertTrue(answer.get("ok"), answer)
                return answer
            pin = call(op="hinge", a="post", b="wheel", at=[.5, 1, 0], axis=[0, 1, 0])["joint"]
            store = call(op="store", name="battery", body="post", capacity_j=1000, max_power_w=30)["store"]
            motor = call(op="motor", joint=pin, store=store, stall_torque_n_m=10, no_load_rad_s=10)["motor"]
            handle = call(op="circuit", network=declaration(store, motor))["circuit"]
            call(op="drive", motor=motor, command=1)
            ran = call(op="step", dt=1/480, n=60)
            state = call(op="circuits")["circuits"]
            self.assertEqual(ran["machines"]["circuits"], state)
            self.assertGreater(state[0]["ledger"]["source_j"], 0)
            call(op="circuit_switch", circuit=handle, branch="switch", closed=False)
            state = call(op="circuits")["circuits"]
            snapshot.write_text(json.dumps(call(op="snapshot")["snapshot"]), encoding="utf-8")
            p.stdin.write('{"op":"quit"}\n'); p.stdin.flush(); p.wait(timeout=10)
            p, opened = open_runner(True)
            self.assertEqual(opened["machines"]["circuits"], state)
            self.assertEqual(call(op="circuits")["circuits"], state)


if __name__ == "__main__":
    unittest.main()
