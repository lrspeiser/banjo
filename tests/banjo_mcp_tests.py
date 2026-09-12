"""The MCP server, driven the way a model client drives it.

Through the real protocol on a real subprocess: JSON-RPC lines in, JSON-RPC
lines out. Calling the handlers directly would test the physics, which is
tested elsewhere, and would miss everything that actually goes wrong at a
protocol boundary -- a notification answered when it should not be, a tool
schema a client will reject, an exception escaping as a crash instead of an
answer.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "banjo_mcp.py"
LIBRARY = next((p for p in [
    ROOT / "build/integration/Release/banjo.dll",
    ROOT / "build/integration/libbanjo.so",
    ROOT / "build/integration/Release/libbanjo.dylib",
] if p.is_file()), None)


class Client:
    """One server, spoken to the way a client does."""

    def __init__(self) -> None:
        import os
        environment = dict(os.environ)
        if LIBRARY:
            environment["BANJO_LIBRARY"] = str(LIBRARY)
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
            env=environment)
        self.next_id = 0

    def send(self, method: str, params: dict | None = None, notify: bool = False):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notify:
            self.next_id += 1
            message["id"] = self.next_id
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        if notify:
            return None
        line = self.process.stdout.readline()
        if not line:
            raise AssertionError(f"the server said nothing and stopped. stderr:\n"
                                 f"{self.process.stderr.read()[:2000]}")
        return json.loads(line)

    def call(self, tool: str, **arguments):
        """One tool call, unwrapped to what it actually answered."""
        reply = self.send("tools/call", {"name": tool, "arguments": arguments})
        result = reply["result"]
        text = result["content"][0]["text"]
        if result.get("isError"):
            raise AssertionError(f"{tool} refused: {text}")
        return json.loads(text)

    def refuse(self, tool: str, **arguments) -> str:
        reply = self.send("tools/call", {"name": tool, "arguments": arguments})
        result = reply["result"]
        assert result.get("isError"), f"{tool} was expected to refuse and did not"
        return result["content"][0]["text"]

    def close(self) -> None:
        try:
            self.process.stdin.close()
            self.process.wait(timeout=10)
        except Exception:
            self.process.kill()
        finally:
            for pipe in (self.process.stdout, self.process.stderr):
                try:
                    pipe.close()
                except Exception:
                    pass


@unittest.skipUnless(LIBRARY, "the C library is not built")
class TheHandshake(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.addCleanup(self.client.close)

    def test_it_introduces_itself(self):
        reply = self.client.send("initialize", {"protocolVersion": "2024-11-05",
                                                "capabilities": {},
                                                "clientInfo": {"name": "test",
                                                               "version": "0"}})
        result = reply["result"]
        self.assertEqual(result["serverInfo"]["name"], "banjo")
        self.assertIn("tools", result["capabilities"])
        self.assertIn("list_materials", result["instructions"])

    def test_a_notification_gets_no_reply(self):
        """And does not wedge the loop. Answering one is a protocol error, and a
        client that is waiting for nothing will wait for ever."""
        self.client.send("initialize", {"protocolVersion": "2024-11-05",
                                        "capabilities": {}, "clientInfo": {}})
        self.client.send("notifications/initialized", {}, notify=True)
        # The next request still gets its own answer, in order.
        reply = self.client.send("tools/list")
        self.assertIn("tools", reply["result"])

    def test_every_tool_has_a_schema_a_client_will_accept(self):
        tools = self.client.send("tools/list")["result"]["tools"]
        self.assertGreaterEqual(len(tools), 8)
        for tool in tools:
            self.assertTrue(tool["name"])
            self.assertGreater(len(tool["description"]), 40,
                               f"{tool['name']} has a description too short to act on")
            schema = tool["inputSchema"]
            self.assertEqual(schema["type"], "object")
            for name in schema.get("required", []):
                self.assertIn(name, schema.get("properties", {}),
                              f"{tool['name']} requires {name} and does not describe it")

    def test_an_unknown_method_is_an_error_and_not_a_crash(self):
        reply = self.client.send("nonsense/method")
        self.assertIn("error", reply)
        self.assertEqual(self.client.send("tools/list")["result"]["tools"][0]["name"],
                         "list_materials", "the server did not survive")


@unittest.skipUnless(LIBRARY, "the C library is not built")
class TheTools(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.addCleanup(self.client.close)
        self.client.send("initialize", {"protocolVersion": "2024-11-05",
                                        "capabilities": {}, "clientInfo": {}})

    def pane_world(self):
        """A glass pane bridged between two piers: the thing that breaks."""
        return self.client.call("create_world", cell_size_m=0.02, objects=[
            {"name": "left pier", "shape": "box", "material": "iron",
             "size_m": [0.08, 0.40, 0.20], "position_m": [-0.26, 0.20, 0],
             "anchored": True},
            {"name": "right pier", "shape": "box", "material": "iron",
             "size_m": [0.08, 0.40, 0.20], "position_m": [0.26, 0.20, 0],
             "anchored": True},
            {"name": "pane", "shape": "box", "material": "glass",
             "size_m": [0.60, 0.02, 0.20], "position_m": [0, 0.41, 0]},
        ])["world_id"]

    def test_the_materials_are_described_in_terms_of_what_they_do(self):
        answer = self.client.call("list_materials")
        names = {m["name"] for m in answer["materials"]}
        self.assertEqual(len(names), 8)
        for entry in answer["materials"]:
            self.assertGreater(len(entry["behaviour"]), 40,
                               f"{entry['name']} says nothing useful about itself")

    def test_a_world_opens_and_describes_itself(self):
        world_id = self.pane_world()
        answer = self.client.call("describe_world", world_id=world_id)
        names = {o["name"] for o in answer["objects"]}
        self.assertEqual(names, {"left pier", "right pier", "pane"})
        self.assertTrue(all(o["material"] for o in answer["objects"]),
                        "an object came back without saying what it is made of")

    def test_dropping_something_hard_enough_breaks_it_and_says_so(self):
        world_id = self.pane_world()
        answer = self.client.call("drop", world_id=world_id, fall_m=3.0,
                                  over_m=[0, 0, 0],
                                  object={"name": "iron ball", "shape": "sphere",
                                          "material": "iron", "size_m": [0.12] * 3})
        self.assertEqual(answer["dropped"]["onto"], "pane",
                         "the drop did not land on the pane it was aimed at")
        breaks = [e for e in answer["what_happened"] if e["what"] == "broke"]
        self.assertTrue(breaks, f"nothing broke: {answer['what_happened']}")
        self.assertGreater(breaks[0]["into_pieces"], 1)

    def test_a_gentle_drop_says_why_nothing_happened(self):
        """The answer someone actually needs. A tool that reports silence when a
        thing bounced off teaches nothing; one that says what it would have
        taken can be acted on."""
        world_id = self.pane_world()
        answer = self.client.call("drop", world_id=world_id, fall_m=0.3,
                                  over_m=[0, 0, 0],
                                  object={"name": "iron ball", "shape": "sphere",
                                          "material": "iron", "size_m": [0.12] * 3})
        self.assertEqual(answer["what_happened"], "nothing broke or bent")
        self.assertIn("why_nothing_happened", answer)
        hit = [h for h in answer["hardest_contacts"] if h["struck"] == "pane"]
        self.assertTrue(hit, "no contact with the pane was reported at all")
        self.assertLess(hit[0]["at_m_s"], hit[0]["breaks_above_m_s"],
                        "it was over the bar and still did not break, so the "
                        "explanation offered is the wrong one")

    def test_something_already_there_can_be_picked_up_and_moved(self):
        """Rearranging, rather than only adding.

        Until this existed the only way to put an object somewhere was to drop a
        NEW one from above: a model could add to a scene and never move anything
        in it.
        """
        world_id = self.pane_world()
        self.client.call("add_object", world_id=world_id,
                         object={"name": "iron ball", "shape": "sphere",
                                 "material": "iron", "size_m": [0.12] * 3,
                                 "position_m": [2.0, 0.06, 0]})
        held = self.client.call("pick_up", world_id=world_id, name="iron ball")
        self.assertEqual(held["holding"], "iron ball")
        self.client.call("place", world_id=world_id, to_m=[0, 3.0, 0])
        answer = self.client.call("let_go", world_id=world_id)
        self.assertEqual(answer["let_go_of"], "iron ball")
        breaks = [e for e in answer["what_happened"] if e["what"] == "broke"]
        self.assertTrue(breaks,
                        f"carried over the pane and dropped 3 m, nothing broke: "
                        f"{answer['what_happened']}")

    def gateway(self):
        """A post with a gate beside it, and something to shove it with.

        The gate is clear of the post in z rather than sharing its space: a leaf
        overlapping its own frame is jammed against it, and jammed is exactly
        what a working hinge looks like from the outside.
        """
        return self.client.call("create_world", cell_size_m=0.04, objects=[
            {"name": "post", "shape": "box", "material": "concrete",
             "size_m": [0.16, 2.0, 0.16], "position_m": [-0.08, 1.0, 0],
             "anchored": True},
            {"name": "gate", "shape": "box", "material": "oak",
             "size_m": [1.2, 1.6, 0.08], "position_m": [0.6, 1.0, 0.12]},
            {"name": "fist", "shape": "box", "material": "iron",
             "size_m": [0.2, 0.2, 0.2], "position_m": [0.6, 1.0, 1.2]},
        ])["world_id"]

    def test_a_gate_hung_on_a_pin_swings_when_something_pushes_it(self):
        """A mechanism, not a prop.

        The gate opens because a body was pushed into it off its centre line and
        the pin turned that into a torque. Nothing plays an animation, and there
        is no tool for "open the gate" -- which is the point: a model that wants
        it open has to push something into it.
        """
        world_id = self.gateway()
        self.assertEqual(self.client.call("joints", world_id=world_id)["joints"], [])
        hung = self.client.call("hinge", world_id=world_id, a="post", b="gate",
                                at_m=[0.0, 1.0, 0.12], axis=[0, 1, 0],
                                lower_deg=0.0, upper_deg=100.0)
        self.assertGreater(hung["joint"], 0)

        # Walk the fist into the gate a centimetre at a time. Further than the
        # gate is thick in one move and it goes straight through: a carried body
        # is placed, not swept.
        self.client.call("pick_up", world_id=world_id, name="fist")
        for i in range(1, 111):
            self.client.call("place", world_id=world_id,
                             to_m=[0.6, 1.0, 1.2 - i * 0.01])
        self.client.call("let_go", world_id=world_id)

        pins = self.client.call("joints", world_id=world_id)["joints"]
        self.assertEqual(len(pins), 1)
        self.assertTrue(pins[0]["attached"], "the gate came off its pin")
        self.assertEqual((pins[0]["a"], pins[0]["b"]), ("post", "gate"))
        self.assertGreater(abs(pins[0]["degrees"]), 10.0,
                           f"shoved square in the face and the gate turned "
                           f"{pins[0]['degrees']} degrees, so the pin is not a pin")
        self.assertLessEqual(abs(pins[0]["degrees"]), 100.0,
                             "the gate went past the stop it was given")

    def test_a_pin_can_be_stiffened_and_taken_out(self):
        world_id = self.gateway()
        joint = self.client.call("hinge", world_id=world_id, a="post", b="gate",
                                 at_m=[0.0, 1.0, 0.12])["joint"]
        self.client.call("hinge_friction", world_id=world_id, joint=joint,
                         friction_n_m=45.0)
        pins = self.client.call("joints", world_id=world_id)["joints"]
        self.assertAlmostEqual(pins[0]["friction_n_m"], 45.0, places=2)
        self.client.call("unhinge", world_id=world_id, joint=joint)
        self.assertEqual(self.client.call("joints", world_id=world_id)["joints"], [])

    def test_a_pin_refuses_what_it_cannot_hold(self):
        world_id = self.gateway()
        for why, wrong in (
            ("a body that is not there",
             {"a": "post", "b": "nothing at all", "at_m": [0, 1, 0]}),
            ("a body hung on itself",
             {"a": "gate", "b": "gate", "at_m": [0, 1, 0]}),
            ("an axis with no direction",
             {"a": "post", "b": "gate", "at_m": [0, 1, 0.12], "axis": [0, 0, 0]}),
        ):
            with self.assertRaises(Exception, msg=f"it accepted {why}"):
                self.client.call("hinge", world_id=world_id, **wrong)
        self.assertEqual(self.client.call("joints", world_id=world_id)["joints"], [],
                         "a refused pin was recorded anyway")

    def test_the_hand_refuses_clearly_rather_than_failing_quietly(self):
        world_id = self.pane_world()
        with self.assertRaises(Exception) as anchored:
            self.client.call("pick_up", world_id=world_id, name="left pier")
        self.assertIn("pier", str(anchored.exception),
                      "a refusal that does not name what was refused is no use")
        with self.assertRaises(Exception) as empty:
            self.client.call("place", world_id=world_id, to_m=[0, 1, 0])
        self.assertIn("pick_up", str(empty.exception),
                      "a refusal should say what to do instead")

    def test_the_floor_can_be_swept_and_the_haul_adds_up(self):
        """Where raw materials come from, and how the world keeps working.

        Past a couple of thousand bodies the reversible step a fracture needs
        cannot run, and the room quietly stops being able to break anything. So
        this is not tidying.
        """
        world_id = self.pane_world()
        self.client.call("drop", world_id=world_id, fall_m=3.0, over_m=[0, 0, 0],
                         object={"name": "iron ball", "shape": "sphere",
                                 "material": "iron", "size_m": [0.12] * 3})
        swept = self.client.call("collect", world_id=world_id,
                                 near_m=[0, 0, 0], radius_m=4.0)
        self.assertTrue(swept["picked_up"], "sweeping a shattered pane collected nothing")
        lot = swept["picked_up"][0]
        self.assertEqual(lot["material"], "glass")
        self.assertGreater(lot["grams"], 0.0, "it was collected but weighs nothing")
        self.assertGreater(lot["pieces"], 1)
        self.assertLess(swept["objects_now"], swept["objects_before"],
                        "a haul was reported but the world still holds the pieces")

        # And it accumulates, because that is what it is for.
        carried = self.client.call("carried", world_id=world_id)
        self.assertIn("glass", carried["carried"])
        self.assertAlmostEqual(carried["carried"]["glass"]["grams"], lot["grams"], places=1)
        self.assertGreater(carried["total_kilograms"], 0.0)

        again = self.client.call("collect", world_id=world_id,
                                 near_m=[0, 0, 0], radius_m=4.0)
        self.assertFalse(again["picked_up"], "the same debris was collected twice")

    def test_a_ray_says_what_is_under_something(self):
        world_id = self.pane_world()
        above = self.client.call("cast_ray", world_id=world_id,
                                 from_m=[0, 3, 0], direction=[0, -1, 0])
        self.assertTrue(above["hit"])
        self.assertEqual(above["object"], "pane")
        beside = self.client.call("cast_ray", world_id=world_id,
                                  from_m=[3, 3, 0], direction=[0, -1, 0])
        self.assertTrue(beside["hit"])
        self.assertTrue(beside["is_the_floor"], "beside the scene should be the floor")
        sky = self.client.call("cast_ray", world_id=world_id,
                               from_m=[0, 3, 0], direction=[0, 1, 0])
        self.assertFalse(sky["hit"])

    def test_adding_and_removing_objects(self):
        world_id = self.pane_world()
        self.client.call("add_object", world_id=world_id,
                         object={"name": "marble", "shape": "sphere",
                                 "material": "glass", "size_m": [0.06] * 3,
                                 "position_m": [1.0, 0.03, 0]})
        names = {o["name"] for o in
                 self.client.call("describe_world", world_id=world_id)["objects"]}
        self.assertIn("marble", names)
        self.client.call("remove_object", world_id=world_id, name="marble")
        names = {o["name"] for o in
                 self.client.call("describe_world", world_id=world_id)["objects"]}
        self.assertNotIn("marble", names)

    def test_a_world_can_be_closed_and_is_then_gone(self):
        world_id = self.pane_world()
        self.client.call("close_world", world_id=world_id)
        self.assertIn("no world", self.client.refuse("describe_world", world_id=world_id))

    def test_bad_input_is_refused_in_words_the_caller_can_act_on(self):
        world_id = self.pane_world()
        self.assertIn("cheese", self.client.refuse(
            "create_world", objects=[{"shape": "box", "material": "cheese",
                                      "size_m": [0.1, 0.1, 0.1],
                                      "position_m": [0, 1, 0]}]))
        self.assertIn("non-empty", self.client.refuse("create_world", objects=[]))
        self.assertIn("three numbers", self.client.refuse(
            "cast_ray", world_id=world_id, from_m=[0, 1], direction=[0, -1, 0]))
        # And the server is still answering afterwards.
        self.assertTrue(self.client.call("describe_world", world_id=world_id)["objects"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
