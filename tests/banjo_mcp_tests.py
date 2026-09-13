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
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "banjo_mcp.py"
# BANJO_LIBRARY first: ctest sets it to the library it just built, and without
# it every test here skipped as "not built" in any tree but build/integration --
# which ctest counted as a pass.
LIBRARY = next((p for p in [
    *([Path(os.environ["BANJO_LIBRARY"])] if os.environ.get("BANJO_LIBRARY") else []),
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

    def test_a_raised_grate_falls_when_you_let_go(self):
        """A slide is a joint, not an animation.

        Nothing in the engine knows what a portcullis is: the grate falls
        because it is iron free to move down a vertical line with gravity still
        acting on it.
        """
        world_id = self.client.call("create_world", cell_size_m=0.04, objects=[
            {"name": "left jamb", "shape": "box", "material": "concrete",
             "size_m": [0.16, 3.0, 0.16], "position_m": [-0.8, 1.5, 0], "anchored": True},
            {"name": "grate", "shape": "box", "material": "iron",
             "size_m": [1.2, 1.6, 0.12], "position_m": [0, 0.8, 0.2]},
        ])["world_id"]
        made = self.client.call("slide", world_id=world_id, a="left jamb", b="grate",
                                at_m=[0, 0.8, 0.2], axis=[0, 1, 0],
                                lower_m=0.0, upper_m=1.5)
        self.assertGreater(made["joint"], 0)
        grooves = self.client.call("joints", world_id=world_id)["joints"]
        self.assertEqual(grooves[0]["kind"], "slider")
        # A slide is reported in METRES, and says so in the key.
        self.assertIn("moved_m", grooves[0])
        self.assertNotIn("degrees", grooves[0])

        self.client.call("pick_up", world_id=world_id, name="grate")
        for i in range(1, 101):
            self.client.call("place", world_id=world_id, to_m=[0, 0.8 + i * 0.01, 0.2])
        up = self.client.call("joints", world_id=world_id)["joints"][0]["moved_m"]
        self.assertGreater(up, 0.8, "hauling did not lift the grate")
        self.client.call("let_go", world_id=world_id)
        down = self.client.call("joints", world_id=world_id)["joints"][0]["moved_m"]
        self.assertLess(down, 0.2,
                        f"the grate was let go {up} m up and is still at {down}")

    def test_a_rope_pulls_but_does_not_push(self):
        """The one asymmetry that makes a rope a rope, through the tools.

        Tied under a beam the weight hangs. There is no tool for "make it
        hang" -- it hangs because a link is pulling up on it, and if the same
        link could push, the weight would be held out at arm's length instead
        of swinging free.
        """
        world_id = self.client.call("create_world", cell_size_m=0.04, objects=[
            {"name": "beam", "shape": "box", "material": "oak",
             "size_m": [2.0, 0.2, 0.2], "position_m": [0, 4.0, 0], "anchored": True},
            {"name": "weight", "shape": "box", "material": "iron",
             "size_m": [0.2, 0.2, 0.2], "position_m": [0, 3.0, 0]},
        ])["world_id"]
        made = self.client.call("tie", world_id=world_id, a="beam", b="weight",
                                at_a_m=[0, 3.9, 0], at_b_m=[0, 3.0, 0])
        self.assertGreater(made["joint"], 0)
        rope = self.client.call("joints", world_id=world_id)["joints"][0]
        self.assertEqual(rope["kind"], "link")
        # A link is reported in metres and newtons, and says so in the key.
        self.assertIn("tension_n", rope)
        self.assertNotIn("degrees", rope)

        self.client.call("run", world_id=world_id, seconds=2.0)
        held = self.client.call("describe_world", world_id=world_id)
        weight = next(b for b in held["objects"] if b["name"] == "weight")
        self.assertGreater(weight["position_m"][1], 2.9,
                           "the weight fell through its own rope")
        # 0.2 m of iron is 618 N, and that is what the rope should be carrying.
        carrying = self.client.call("joints", world_id=world_id)["joints"][0]["tension_n"]
        self.assertGreater(carrying, 300.0,
                           f"the rope holds a 618 N weight and reports {carrying} N")

    def test_a_rope_can_be_overloaded(self):
        world_id = self.client.call("create_world", cell_size_m=0.04, objects=[
            {"name": "beam", "shape": "box", "material": "oak",
             "size_m": [2.0, 0.2, 0.2], "position_m": [0, 4.0, 0], "anchored": True},
            {"name": "weight", "shape": "box", "material": "iron",
             "size_m": [0.2, 0.2, 0.2], "position_m": [0, 3.0, 0]},
        ])["world_id"]
        self.client.call("tie", world_id=world_id, a="beam", b="weight",
                         at_a_m=[0, 3.9, 0], at_b_m=[0, 3.0, 0],
                         breaks_at_n=150.0)         # a 618 N weight on it
        self.client.call("run", world_id=world_id, seconds=2.0)
        rope = self.client.call("joints", world_id=world_id)["joints"][0]
        self.assertFalse(rope["attached"], "the rope held four times its rating")
        weight = next(b for b in self.client.call(
            "describe_world", world_id=world_id)["objects"] if b["name"] == "weight")
        self.assertLess(weight["position_m"][1], 2.0,
                        "the rope parted but the weight did not fall")

    def test_a_fixing_holds_and_a_latch_lets_go(self):
        """Two bodies as one piece, and then not.

        There is no tool for "open the latch" -- the latch is a joint, and
        letting it go is `unhinge`. What changes is what the assembly IS.
        """
        world_id = self.client.call("create_world", cell_size_m=0.05, objects=[
            {"name": "wall", "shape": "box", "material": "oak",
             "size_m": [0.2, 3.0, 1.0], "position_m": [0, 1.5, 0], "anchored": True},
            {"name": "bracket", "shape": "box", "material": "iron",
             "size_m": [0.2, 0.2, 0.2], "position_m": [0.25, 2.0, 0]},
        ])["world_id"]
        made = self.client.call("fix", world_id=world_id, a="wall", b="bracket",
                                at_m=[0.15, 2.0, 0.0], axis=[1, 0, 0])
        self.assertGreater(made["joint"], 0)
        held = self.client.call("joints", world_id=world_id)["joints"][0]
        self.assertEqual(held["kind"], "fixing")
        # Tension and shear are separate keys, because they fail separately.
        self.assertIn("tension_n", held)
        self.assertIn("shear_n", held)

        self.client.call("run", world_id=world_id, seconds=2.0)
        hanging = next(b for b in self.client.call(
            "describe_world", world_id=world_id)["objects"] if b["name"] == "bracket")
        self.assertGreater(hanging["position_m"][1], 1.9,
                           "the bracket fell off a weld")
        # A hanging weight is entirely shear, so that is where the load shows.
        carrying = self.client.call("joints", world_id=world_id)["joints"][0]
        self.assertGreater(carrying["shear_n"], 300.0,
                           f"a 618 N bracket reports {carrying['shear_n']} N of shear")

        self.client.call("unhinge", world_id=world_id, joint=made["joint"])
        self.client.call("run", world_id=world_id, seconds=2.0)
        dropped = next(b for b in self.client.call(
            "describe_world", world_id=world_id)["objects"] if b["name"] == "bracket")
        self.assertLess(dropped["position_m"][1], 1.0,
                        "releasing the fixing did not drop the bracket")

    def test_a_hoist_lifts_the_other_end(self):
        """A pulley through the tools, and the direction of its ratio.

        The ratio multiplies B's run, so a counterweight at b arrives at a
        DIVIDED by it -- which is the thing that is easy to get backwards and
        expensive to discover in a courtyard.
        """
        world_id = self.client.call("create_world", cell_size_m=0.05, objects=[
            {"name": "beam", "shape": "box", "material": "oak",
             "size_m": [3.0, 0.2, 0.2], "position_m": [0, 5.0, 0], "anchored": True},
            {"name": "load", "shape": "box", "material": "iron",
             "size_m": [0.2, 0.2, 0.2], "position_m": [-1.0, 3.0, 0]},
            {"name": "counterweight", "shape": "box", "material": "iron",
             "size_m": [0.2, 0.2, 0.2], "position_m": [1.0, 3.0, 0]},
        ])["world_id"]
        made = self.client.call("reeve", world_id=world_id, a="load",
                                b="counterweight",
                                at_a_m=[-1.0, 3.0, 0.0], at_b_m=[1.0, 3.0, 0.0],
                                over_a_m=[-1.0, 4.9, 0.0], over_b_m=[1.0, 4.9, 0.0],
                                ratio=1.0)
        self.assertGreater(made["joint"], 0)
        rove = self.client.call("joints", world_id=world_id)["joints"][0]
        self.assertEqual(rove["kind"], "pulley")
        # Reported in metres, and it says so in the key.
        self.assertIn("rope_m", rove)
        self.assertIn("ratio", rove)

        # Equal weights at 1:1 balance: neither end runs away.
        was = next(b for b in self.client.call(
            "describe_world", world_id=world_id)["objects"] if b["name"] == "load")
        self.client.call("run", world_id=world_id, seconds=2.0)
        now = next(b for b in self.client.call(
            "describe_world", world_id=world_id)["objects"] if b["name"] == "load")
        self.assertLess(abs(now["position_m"][1] - was["position_m"][1]), 0.1,
                        "two equal weights on a 1:1 rope did not balance")
        self.assertGreater(
            self.client.call("joints", world_id=world_id)["joints"][0]["tension_n"],
            100.0, "the rope is holding two 618 N weights and reports nothing")

    def test_a_spring_stores_what_is_done_to_it(self):
        """An elastic element through the tools, with its model reported.

        There is no "shoot" tool and no arrow speed anywhere: what a spring
        gives back is what was put into it, and `joints` reports both the model
        it declares and what it currently holds.
        """
        world_id = self.client.call("create_world", cell_size_m=0.05, objects=[
            {"name": "post", "shape": "box", "material": "iron",
             "size_m": [0.2, 0.2, 0.2], "position_m": [0, 2.0, 0], "anchored": True},
            {"name": "block", "shape": "box", "material": "iron",
             "size_m": [0.2, 0.2, 0.2], "position_m": [1.0, 2.0, 0]},
        ])["world_id"]
        made = self.client.call("spring", world_id=world_id, a="post", b="block",
                                at_a_m=[0.1, 2.0, 0.0], at_b_m=[0.9, 2.0, 0.0],
                                stiffness_n_m=2000.0, damping_n_s_m=200.0)
        self.assertGreater(made["joint"], 0)
        limb = self.client.call("joints", world_id=world_id)["joints"][0]
        self.assertEqual(limb["kind"], "elastic")
        self.assertAlmostEqual(limb["stiffness_n_m"], 2000.0, places=2)
        # Built at its own rest length, so it holds nothing yet.
        self.assertLess(abs(limb["force_n"]), 1.0)
        self.assertLess(limb["stored_j"], 0.01)

        # Pull it out and it holds energy -- half k x squared, from the model.
        self.client.call("pick_up", world_id=world_id, name="block")
        for i in range(1, 61):
            self.client.call("place", world_id=world_id,
                             to_m=[1.0 + i * 0.005, 2.0, 0.0])
        drawn = self.client.call("joints", world_id=world_id)["joints"][0]
        stretched = drawn["length_m"] - drawn["rest_m"]
        self.assertGreater(stretched, 0.05, "the spring was not drawn at all")
        # Compared loosely on purpose: `length_m` comes back rounded to a tenth
        # of a millimetre, and at this stiffness a tenth of a millimetre is
        # 0.06 J. The tool rounds for the reader; the test must not then demand
        # more places than it left.
        self.assertAlmostEqual(drawn["stored_j"] / (0.5 * 2000.0 * stretched ** 2),
                               1.0, places=3)
        self.assertAlmostEqual(drawn["force_n"] / (2000.0 * stretched), 1.0, places=3)

    def test_a_loaded_shelf_is_reported_without_being_struck(self):
        """Sustained load through the tools.

        Nothing strikes the shelf. It is asked about from statics, and it is the
        only way a thing at rest under a pile is ever noticed.
        """
        objects = [
            {"name": "left pier", "shape": "box", "material": "iron",
             "size_m": [0.2, 0.4, 0.3], "position_m": [-0.6, 0.2, 0],
             "anchored": True},
            {"name": "right pier", "shape": "box", "material": "iron",
             "size_m": [0.2, 0.4, 0.3], "position_m": [0.6, 0.2, 0],
             "anchored": True},
            {"name": "shelf", "shape": "box", "material": "concrete",
             "size_m": [1.4, 0.1, 0.3], "position_m": [0, 0.45, 0]},
        ]
        for i in range(5):
            objects.append(
                {"name": f"crate {i + 1}", "shape": "box", "material": "iron",
                 "size_m": [0.3, 0.3, 0.3], "position_m": [0, 0.5 + 0.3 * (0.5 + i), 0]})
        world_id = self.client.call("create_world", cell_size_m=0.05,
                                    objects=objects)["world_id"]
        self.assertEqual(self.client.call("overloaded", world_id=world_id)["overloaded"],
                         [], "a shelf was overloaded before anything settled on it")
        self.client.call("run", world_id=world_id, seconds=2.0)
        sagging = self.client.call("overloaded", world_id=world_id)["overloaded"]
        self.assertEqual(len(sagging), 1, f"expected one overloaded thing: {sagging}")
        self.assertEqual(sagging[0]["object"], "shelf")
        self.assertGreater(sagging[0]["stress_mpa"], sagging[0]["holds_mpa"],
                           "it was reported without being over its strength")
        self.assertGreater(sagging[0]["carrying_n"], 1000.0)
        self.assertGreater(sagging[0]["span_m"], 0.5)

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

    def test_an_edge_presses_through_oak_and_a_flat_does_not(self):
        """The distinction the cutting model rests on, through the tools: the
        same iron plate, the same hand, the same oak. Edge down, the hand's
        800 N is more than the 300 N the 20 mm batten resists with, and it goes
        through. Flat down, the same push is an ordinary contact and nothing is
        cut. docs/cutting-model.md."""
        def press(edge_down: bool):
            size = [0.01, 0.10, 0.25] if edge_down else [0.10, 0.01, 0.25]
            world_id = self.client.call("create_world", cell_size_m=0.01, objects=[
                {"name": "batten", "shape": "box", "material": "oak",
                 "size_m": [0.2, 0.02, 0.02], "position_m": [0, 0.01, 0]},
                {"name": "plate", "shape": "box", "material": "iron",
                 "size_m": size, "position_m": [0, 0.02 + size[1] / 2, 0]},
            ])["world_id"]
            if edge_down:
                edge = {"heel_m": [0, 0.02, -0.1], "tip_m": [0, 0.02, 0.1],
                        "facing": [0, -1, 0], "grip_m": [0, 0.12, 0]}
            else:
                # The same edge along the plate's side, facing sideways: what
                # meets the oak is a flat.
                edge = {"heel_m": [0.05, 0.025, -0.1], "tip_m": [0.05, 0.025, 0.1],
                        "facing": [1, 0, 0], "grip_m": [0, 0.025, 0]}
            made = self.client.call("blade", world_id=world_id, body="plate",
                                    thickness_m=0.01, edge_radius_m=0.0002, bevel_deg=30.0,
                                    **edge)
            self.assertGreater(made["blade"], 0)
            self.client.call("wield", world_id=world_id, name="plate")
            grip = edge["grip_m"]
            return self.client.call("swing", world_id=world_id,
                                    to_m=[grip[0], grip[1] - 0.2, grip[2]],
                                    seconds=1.0, then_s=0.5)

        edge = press(True)
        names = {o["name"] for o in edge["objects"]}
        self.assertTrue({"batten piece 1", "batten piece 2"} <= names,
                        f"an 800 N press on the edge did not cut through: {sorted(names)}")
        cuts = edge["cuts"] if isinstance(edge["cuts"], list) else []
        bit = [c for c in cuts if c["met"].startswith("batten") and "cut_mm2" in c]
        self.assertTrue(bit and bit[0]["kind"] == "press",
                        f"a slow push was not reported as a press: {cuts}")
        self.assertTrue(any(c.get("came_apart") for c in bit), f"no cut says it separated: {bit}")
        # 20 mm of oak at R = 15 kJ/m^2 is 6 J; separation comes when the last
        # row of bonds goes, which is from three quarters of the section.
        work = sum(c["work_j"] for c in bit)
        self.assertGreater(work, 0.7 * 6.0, f"it came apart for only {work} J")
        self.assertLess(work, 1.15 * 6.0, f"it cost {work} J, more than the section")

        flat = press(False)
        names = {o["name"] for o in flat["objects"]}
        self.assertIn("batten", names, "the flat of the plate cut the batten")
        cuts = flat["cuts"] if isinstance(flat["cuts"], list) else []
        self.assertFalse([c for c in cuts if c.get("bonds_severed")],
                         f"the flat severed bonds: {cuts}")

    def test_a_swing_through_a_rope_cuts_it_and_its_flat_does_not(self):
        """What the playground's chat does to try a cut in its own copy: build a
        rope of rubber segments with a weight on it and an aluminium sword on
        a rest, take the sword, and swing it through the middle of the rope --
        round a shoulder, edge leading. Then the same swing with the edge facing
        the floor, so the flat leads. docs/cutting-model.md."""
        def rope_and_sword(edge_facing):
            objects = [{"name": "rope beam", "shape": "box", "material": "oak",
                        "size_m": [0.24, 0.08, 0.08], "position_m": [-0.5, 2.04, 1.4],
                        "anchored": True}]
            objects += [{"name": f"rope {k}", "shape": "box", "material": "rubber",
                         "size_m": [0.04, 0.12, 0.04], "position_m": [-0.5, 2.06 - 0.12 * k, 1.4]}
                        for k in range(1, 7)]
            objects += [
                {"name": "weight", "shape": "box", "material": "iron",
                 "size_m": [0.08, 0.08, 0.08], "position_m": [-0.5, 1.24, 1.4]},
                {"name": "rest left", "shape": "box", "material": "oak",
                 "size_m": [0.08, 0.08, 0.08], "position_m": [-0.24, 0.96, 1.9], "anchored": True},
                {"name": "rest right", "shape": "box", "material": "oak",
                 "size_m": [0.08, 0.08, 0.08], "position_m": [0.24, 0.96, 1.9], "anchored": True},
                {"name": "sword", "shape": "box", "material": "aluminum",
                 "size_m": [0.64, 0.04, 0.04], "position_m": [0.0, 1.02, 1.9]}]
            world_id = self.client.call("create_world", cell_size_m=0.04, objects=objects)["world_id"]
            ends = [("rope beam", "rope 1", 2.0)] + \
                   [(f"rope {k}", f"rope {k + 1}", 2.0 - 0.12 * k) for k in range(1, 6)] + \
                   [("rope 6", "weight", 1.28)]
            for a, b, join in ends:
                self.client.call("tie", world_id=world_id, a=a, b=b,
                                 at_a_m=[-0.5, join + 0.02, 1.4], at_b_m=[-0.5, join - 0.02, 1.4])
            self.client.call("blade", world_id=world_id, body="sword",
                             heel_m=[0.2, 1.02, 1.88], tip_m=[-0.3, 1.02, 1.88], facing=[0, 0, -1],
                             thickness_m=0.04, edge_radius_m=0.0002, bevel_deg=30,
                             grip_m=[0.28, 1.02, 1.9])
            self.client.call("wield", world_id=world_id, name="sword")
            return self.client.call("swing", world_id=world_id, through_m=[-0.5, 1.58, 1.4],
                                    pointing=[0, 0, -1], edge_facing=edge_facing,
                                    seconds=0.13, then_s=1.5)

        def weight_y(answer):
            return next(o["position_m"][1] for o in answer["objects"] if o["name"] == "weight")

        edge = rope_and_sword([-1, 0, 0])
        cuts = edge["cuts"] if isinstance(edge["cuts"], list) else []
        bit = [c for c in cuts if c["met"].startswith("rope") and c.get("bonds_severed")]
        self.assertTrue(bit, f"the edge-first swing did not cut the rope: {edge['cuts']}")
        self.assertTrue(any(c.get("came_apart") for c in bit), f"the rope did not part: {bit}")
        self.assertLess(weight_y(edge), 0.3, "the rope was cut and the weight did not fall")
        for c in bit:
            self.assertAlmostEqual(c["work_j"] / (c["cut_mm2"] * 1e-6), c["resistance_j_m2"],
                                   delta=0.01 * c["resistance_j_m2"])

        flat = rope_and_sword([0, -1, 0])
        cuts = flat["cuts"] if isinstance(flat["cuts"], list) else []
        self.assertFalse([c for c in cuts if c.get("bonds_severed") or c.get("rope_links_cut")],
                         f"the flat cut the rope: {cuts}")
        self.assertGreater(weight_y(flat), 1.0, "the weight fell under the flat")

    def test_an_edge_that_is_not_on_its_body_is_refused(self):
        world_id = self.client.call("create_world", cell_size_m=0.01, objects=[
            {"name": "plate", "shape": "box", "material": "iron",
             "size_m": [0.01, 0.10, 0.25], "position_m": [0, 0.05, 0]}])["world_id"]
        said = self.client.refuse("blade", world_id=world_id, body="plate",
                                  heel_m=[0, 0.5, -0.1], tip_m=[0, 0.5, 0.1],
                                  facing=[0, -1, 0])
        self.assertGreater(len(said), 10, "refused without saying why")

    def test_an_edge_facing_into_its_body_is_refused(self):
        """An edge on a bar's far face, declared facing back into the bar, leads
        with the bar's other face: a model built a sword that way, and swung edge
        first it glanced off the rope it was meant to cut. It is refused, saying
        why, and the same edge facing out of the bar is taken."""
        world_id = self.client.call("create_world", cell_size_m=0.04, objects=[
            {"name": "sword", "shape": "box", "material": "aluminum",
             "size_m": [0.64, 0.04, 0.04], "position_m": [0, 1.02, -0.6]}])["world_id"]
        edge = dict(world_id=world_id, body="sword", heel_m=[0.2, 1.02, -0.62],
                    tip_m=[-0.3, 1.02, -0.62], thickness_m=0.04, grip_m=[0.28, 1.02, -0.6])
        said = self.client.refuse("blade", facing=[0, 0, 1], **edge)
        self.assertIn("faces into", said)
        self.assertIn("blade", self.client.call("blade", facing=[0, 0, -1], **edge))

    def test_a_rope_made_off_in_the_air_is_warned_about(self):
        """A model hung a weight 0.24 m below the end of its rope and tied it from
        a point in the air under the last segment: the point rode on the segment
        like the end of a stiff arm, and a blow to the rope flung the weight
        about. A rope made off away from its body is warned about; one made off
        in its matter is not."""
        world_id = self.client.call("create_world", cell_size_m=0.04, objects=[
            {"name": "beam", "shape": "box", "material": "oak", "size_m": [0.24, 0.08, 0.08],
             "position_m": [0, 2.04, 0], "anchored": True},
            {"name": "segment", "shape": "box", "material": "rubber",
             "size_m": [0.04, 0.12, 0.04], "position_m": [0, 1.94, 0]},
            {"name": "weight", "shape": "box", "material": "iron", "size_m": [0.08, 0.08, 0.08],
             "position_m": [0, 1.60, 0]}])["world_id"]
        good = self.client.call("tie", world_id=world_id, a="beam", b="segment",
                                at_a_m=[0, 2.02, 0], at_b_m=[0, 1.98, 0])
        self.assertFalse([w for w in good.get("warnings", []) if "outside" in w], good)
        bad = self.client.call("tie", world_id=world_id, a="segment", b="weight",
                               at_a_m=[0, 1.66, 0], at_b_m=[0, 1.62, 0])
        said = " ".join(bad.get("warnings", []))
        self.assertIn("at_a_m is 0.22 m outside segment", said)
        self.assertNotIn("at_b_m", said)

    def test_a_world_can_be_closed_and_is_then_gone(self):
        world_id = self.pane_world()
        self.client.call("close_world", world_id=world_id)
        self.assertIn("no world", self.client.refuse("describe_world", world_id=world_id))

    def gate_and_ball(self):
        """A post and a gate beside it, clear of each other, and nothing joined."""
        return self.client.call("create_world", cell_size_m=0.04, objects=[
            {"name": "post", "shape": "box", "material": "concrete",
             "size_m": [0.16, 2.0, 0.16], "position_m": [-0.08, 1.0, 0.0],
             "anchored": True},
            {"name": "gate", "shape": "box", "material": "oak",
             "size_m": [1.2, 1.6, 0.08], "position_m": [0.6, 1.0, 0.12]},
            {"name": "ball", "shape": "sphere", "material": "iron",
             "size_m": [0.2, 0.2, 0.2], "position_m": [2.5, 0.1, 2.5]},
        ])["world_id"]

    def test_a_hinge_survives_the_world_being_opened_again(self):
        """Adding an object reopens the world from its scene. The scene used to
        hold bodies only, so the gate's hinge silently vanished at the next
        edit and the gate fell over -- with nothing anywhere to say so."""
        world_id = self.gate_and_ball()
        pin = self.client.call("hinge", world_id=world_id, a="post", b="gate",
                               at_m=[0.0, 1.0, 0.12], axis=[0, 1, 0])["joint"]
        added = self.client.call("add_object", world_id=world_id, object={
            "name": "second ball", "shape": "sphere", "material": "iron",
            "size_m": [0.2, 0.2, 0.2], "position_m": [2.5, 0.1, -2.5]})
        self.assertEqual(added["joints"], 1)
        pins = self.client.call("joints", world_id=world_id)["joints"]
        self.assertEqual([p["joint"] for p in pins], [pin],
                         "the hinge did not come back, or came back under another id")
        self.assertTrue(pins[0]["attached"])
        # And it HOLDS: hung, the gate stays up; loose, it would fall and topple.
        self.client.call("run", world_id=world_id, seconds=1.0)
        gate = next(o for o in self.client.call("describe_world", world_id=world_id)
                    ["objects"] if o["name"] == "gate")
        self.assertGreater(gate["position_m"][1], 0.95,
                           f"the gate is at {gate['position_m']}: nothing held it up")

    def test_a_joint_keeps_its_id_and_its_settings_across_rebuilds(self):
        """The id a caller was given still means the same pin after the world
        has been opened again, and what was set on it is kept."""
        world_id = self.gate_and_ball()
        pin = self.client.call("hinge", world_id=world_id, a="post", b="gate",
                               at_m=[0.0, 1.0, 0.12], axis=[0, 1, 0])["joint"]
        self.client.call("hinge_friction", world_id=world_id, joint=pin,
                         friction_n_m=40.0)
        self.client.call("move_object", world_id=world_id, name="ball",
                         position_m=[2.0, 0.1, 2.0])
        again = self.client.call("joints", world_id=world_id)["joints"]
        self.assertEqual(again[0]["joint"], pin)
        self.assertAlmostEqual(again[0]["friction_n_m"], 40.0, places=1)
        self.client.call("unhinge", world_id=world_id, joint=pin)
        self.client.call("move_object", world_id=world_id, name="ball",
                         position_m=[2.5, 0.1, 2.5])
        self.assertEqual(self.client.call("joints", world_id=world_id)["joints"], [],
                         "a pin that was taken out came back at the next rebuild")

    def test_removing_a_thing_takes_its_joints_with_it_and_says_so(self):
        world_id = self.gate_and_ball()
        self.client.call("hinge", world_id=world_id, a="post", b="gate",
                         at_m=[0.0, 1.0, 0.12], axis=[0, 1, 0])
        removed = self.client.call("remove_object", world_id=world_id, name="gate")
        self.assertEqual(len(removed["joints_removed_with_it"]), 1)
        self.assertIn("hinge", removed["joints_removed_with_it"][0])
        self.assertEqual(self.client.call("joints", world_id=world_id)["joints"], [])

    def test_moving_is_an_edit_and_a_joined_thing_says_why_it_cannot(self):
        """move_object re-authors the world; it is not a push. A joined thing
        cannot be moved that way, because its joint is made at fixed points."""
        world_id = self.gate_and_ball()
        self.client.call("move_object", world_id=world_id, name="ball",
                         position_m=[1.5, 0.1, 2.0])
        ball = next(o for o in self.client.call("describe_world", world_id=world_id)
                    ["objects"] if o["name"] == "ball")
        for got, wanted in zip(ball["position_m"], [1.5, 0.1, 2.0]):
            self.assertAlmostEqual(got, wanted, places=2)
        self.client.call("hinge", world_id=world_id, a="post", b="gate",
                         at_m=[0.0, 1.0, 0.12], axis=[0, 1, 0])
        said = self.client.refuse("move_object", world_id=world_id, name="gate",
                                  position_m=[3.0, 1.0, 0.0])
        self.assertIn("unhinge", said)
        self.assertIn("hinge", said)

    def test_a_world_can_be_cleared_and_built_again(self):
        world_id = self.gate_and_ball()
        self.client.call("hinge", world_id=world_id, a="post", b="gate",
                         at_m=[0.0, 1.0, 0.12], axis=[0, 1, 0])
        cleared = self.client.call("clear_world", world_id=world_id)
        self.assertEqual((cleared["cleared_objects"], cleared["cleared_joints"]), (3, 1))
        self.assertEqual(self.client.call("describe_world", world_id=world_id)["objects"],
                         [])
        # Empty is a state with words for it, not a crash.
        self.assertIn("empty", self.client.refuse("run", world_id=world_id, seconds=0.5))
        self.assertIn("empty", self.client.refuse("pick_up", world_id=world_id,
                                                  name="ball"))
        self.client.call("add_object", world_id=world_id, object={
            "name": "block", "shape": "box", "material": "oak",
            "size_m": [0.2, 0.2, 0.2], "position_m": [0.0, 0.1, 0.0]})
        self.client.call("run", world_id=world_id, seconds=0.5)
        self.assertEqual([o["name"] for o in self.client.call(
            "describe_world", world_id=world_id)["objects"]], ["block"])

    def test_two_things_cannot_share_a_name(self):
        """Joints and every later call find things by name, so a second "ball"
        would quietly make the first one unreachable."""
        world_id = self.gate_and_ball()
        self.assertIn("already", self.client.refuse(
            "add_object", world_id=world_id, object={
                "name": "ball", "shape": "sphere", "material": "iron",
                "size_m": [0.2, 0.2, 0.2], "position_m": [-2.0, 0.1, -2.0]}))

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

    def valley(self):
        """A world with the generated valley under it: made once, cached."""
        world_id = self.client.call("create_world", cell_size_m=0.04, objects=[
            {"name": "marker stone", "shape": "box", "material": "concrete",
             "size_m": [0.08, 0.08, 0.08], "position_m": [-18, -2.6, -14],
             "anchored": True}])["world_id"]
        return world_id, self.client.call("make_terrain", world_id=world_id, kind="valley")

    def test_an_object_given_x_and_z_is_set_down_on_what_is_under_it(self):
        """[x, z] is "put it there": on the floor, or on top of what is already
        there, and it stays put. [x, y, z] is still exactly there."""
        world_id = self.client.call("create_world", cell_size_m=0.04, objects=[
            {"name": "table", "shape": "box", "material": "oak", "size_m": [0.8, 0.4, 0.8],
             "position_m": [0.0, 0.2, 0.0], "anchored": True}])["world_id"]
        floor = self.client.call("add_object", world_id=world_id, object={
            "name": "crate", "shape": "box", "material": "oak", "size_m": [0.32, 0.32, 0.32],
            "position_m": [1.5, -1.0]})
        self.assertEqual(floor["set_down"]["on"], "the floor")
        self.assertAlmostEqual(floor["set_down"]["centre_y_m"], 0.16, delta=0.005)
        table = self.client.call("add_object", world_id=world_id, object={
            "name": "ball", "shape": "sphere", "material": "rubber",
            "size_m": [0.12, 0.12, 0.12], "position_m": [0.1, 0.1]})
        self.assertEqual(table["set_down"]["on"], "table")
        self.assertAlmostEqual(table["set_down"]["its_top_m"], 0.4, delta=0.005)
        self.assertAlmostEqual(table["set_down"]["centre_y_m"], 0.46, delta=0.005)
        self.client.call("run", world_id=world_id, seconds=1.0)
        ball = next(o for o in self.client.call("describe_world", world_id=world_id)["objects"]
                    if o["name"] == "ball")
        self.assertAlmostEqual(ball["position_m"][1], 0.46, delta=0.01,
                               msg="set down on the table, it should still be on it")
        held_up = self.client.call("add_object", world_id=world_id, object={
            "name": "held up", "shape": "sphere", "material": "rubber",
            "size_m": [0.12, 0.12, 0.12], "position_m": [-1.5, 2.0, 0.0]})
        self.assertNotIn("set_down", held_up)
        self.assertEqual(next(o for o in held_up["objects"] if o["name"] == "held up")
                         ["position_m"][1], 2.0)

    def test_a_place_given_beside_the_object_is_taken_and_a_missing_one_explained(self):
        """A model often puts position_m next to the object rather than in it. It
        is taken from there; and with no place at all the refusal says where it
        goes and in what form -- the old one said "three numbers", which sent a
        model round in circles once [x, z] was allowed."""
        world_id = self.client.call("create_world", cell_size_m=0.04, objects=[
            {"name": "marker", "shape": "box", "material": "concrete",
             "size_m": [0.08, 0.08, 0.08], "position_m": [3.0, 0.04, 3.0],
             "anchored": True}])["world_id"]
        beside = self.client.call("add_object", world_id=world_id, position_m=[0.5, -0.5],
                                  object={"name": "ball", "shape": "sphere",
                                          "material": "rubber", "size_m": [0.12, 0.12, 0.12]})
        self.assertEqual(beside["set_down"]["on"], "the floor")
        said = self.client.refuse("add_object", world_id=world_id, object={
            "name": "crate", "shape": "box", "material": "oak", "size_m": [0.32, 0.32, 0.32]})
        self.assertIn("inside object", said)
        self.assertIn("[x, z]", said)

    def test_on_the_valley_x_and_z_sets_a_thing_on_the_ground_and_says_water(self):
        """On generated ground the height under a point is the one number a caller
        cannot know: [x, z] finds it, dry or under the river, and says which."""
        world_id, _ = self.valley()
        dry = self.client.call("add_object", world_id=world_id, object={
            "name": "ball", "shape": "sphere", "material": "rubber",
            "size_m": [0.12, 0.12, 0.12], "position_m": [-9.12, 4.75]})
        ground = self.client.call("survey", world_id=world_id, at_m=[-9.12, 4.75])
        self.assertEqual(dry["set_down"]["on"], "the ground")
        self.assertAlmostEqual(dry["set_down"]["its_top_m"], ground["ground_m"], delta=0.01)
        self.assertNotIn("in_water", dry)
        wet = self.client.call("add_object", world_id=world_id, object={
            "name": "stone", "shape": "box", "material": "concrete",
            "size_m": [0.16, 0.16, 0.16], "position_m": [3.0, 2.0]})
        self.assertIn("in_water", wet, "set down in the river, and the answer did not say so")
        self.assertGreater(wet["in_water"]["depth_m"], 0.1)
        self.assertLess(wet["set_down"]["its_top_m"], wet["in_water"]["surface_m"],
                        "it should rest on the river's bed, under the water")

    def test_a_river_backs_up_behind_a_dam_and_a_pond_drains_down_a_channel(self):
        """The ground and the water are physics a model can use: a survey finds
        the river, blocks set across it back it up, and a channel dug from the
        pond lets it out. Every level here is the engine's."""
        world_id, made = self.valley()
        self.assertEqual(made["ground"]["kind"], "valley")
        pond = made["water"]["ponds"][0]
        across = self.client.call("survey", world_id=world_id, from_m=[0.62, 0.25],
                                  to_m=[0.62, 6.25], every_m=0.25)
        wet = [row for row in across["along"] if row[4] > 0.02]
        self.assertTrue(wet, "no river where the valley says it runs")

        def upstream(state):
            return min(state["the_river_runs"]["every_2_m"], key=lambda p: abs(p[0] + 2.38))[2]

        before = upstream(self.client.call("water_state", world_id=world_id))
        z, k = wet[0][1] - 0.48, 0
        while z <= wet[-1][1] + 0.48:
            k += 1
            placed = self.client.call("add_object", world_id=world_id, object={
                "name": f"dam stone {k}", "shape": "box", "material": "concrete",
                "size_m": [0.48, 0.96, 0.48], "position_m": [0.62, 0.5, z]})
            self.assertIn("seated_on_the_ground", placed, "a block asked for inside the ground")
            z += 0.48
        self.client.call("run", world_id=world_id, seconds=20)
        after = self.client.call("water_state", world_id=world_id)
        self.assertGreater(upstream(after) - before, 0.05, "the river did not back up behind the dam")
        self.assertLess(abs(after["ledger"]["unaccounted_m3"]), 1e-6)

        # Ground does not come from nowhere: nothing has been dug yet.
        self.assertIn("nowhere", self.client.refuse("fill", world_id=world_id, at_m=[5, 5],
                                                    volume_m3=0.5, material="soil"))
        dug = self.client.call("dig", world_id=world_id, from_m=pond["at_m"],
                               to_m=[pond["at_m"][0], pond["at_m"][1] + 5.0], width_m=0.8,
                               depth_m=0.7)
        self.assertGreater(dug["dug_m3"], 1.0)
        ran = self.client.call("run", world_id=world_id, seconds=20)
        now = ran["water"]["ponds"][0]
        self.assertTrue(now["level_m"] is None or now["level_m"] < pond["level_m"] - 0.1,
                        f"the pond did not drain: {pond['level_m']} -> {now['level_m']}")

    def test_oak_in_the_river_floats_and_drifts_downstream(self):
        world_id, made = self.valley()
        x, z, level = made["water"]["the_river_runs"]["every_2_m"][3][:3]
        added = self.client.call("add_object", world_id=world_id, object={
            "name": "oak log", "shape": "box", "material": "oak",
            "size_m": [0.96, 0.24, 0.24], "position_m": [x, level + 0.3, z]})
        self.assertIn("in_water", added)
        ran = self.client.call("run", world_id=world_id, seconds=15)
        log = next(o for o in ran["objects"] if o["name"] == "oak log")
        self.assertGreater(log["position_m"][0] - x, 1.0, "the current did not carry it")
        held = {w["object"]: w for w in ran["water"]["in_the_water"]}
        self.assertTrue(held["oak log"]["floats"], held["oak log"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
