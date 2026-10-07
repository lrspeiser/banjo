"""Bounded loopback sandbox transport to the Rust-owned native world.

The browser supplies intentions, never native operations, clocks or actor IDs.
Fixtures are declared geometry and a native joint/tool point, not cut outcomes.
"""
from __future__ import annotations
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading
import time
import uuid

FAMILIES = {"pick": .12, "shovel": .28, "hoe": .20, "custom": .16}


def vector(value, bound=20):
    if (not isinstance(value, list) or len(value) != 3 or
            any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > bound for v in value)):
        raise ValueError("Expected a bounded three-dimensional vector")
    return value


class TestWorld:
    def __init__(self, native, runtime, family, material):
        self.temp = tempfile.TemporaryDirectory(prefix="banjo-3d-")
        self.child = None
        self.closed = False
        self.lock = threading.Lock()
        self.sequence = 0
        self.last_seen = time.monotonic()
        self.events = collections.deque(maxlen=8)
        self.receipts = collections.OrderedDict()
        self.world = "sandbox-" + uuid.uuid4().hex
        self.session = uuid.uuid4().hex
        self.family, self.material = family, material
        self.runtime_sha256 = hashlib.sha256(Path(runtime).read_bytes()).hexdigest()
        width = FAMILIES[family]
        root = Path(self.temp.name)
        scene = root / "scene.json"
        scene.write_text(json.dumps({"terrain": {"surface": "columns", "generate": {
            "kind": "flat", "nx": 32, "nz": 32, "cell_m": .1,
            "soil_m": .75, "sand_m": 0, "discharge_m3_s": 0}}, "bodies": [
            {"name": "head", "shape": "box", "material": material,
             "dimensions_m": [width, .08, .04], "center_m": [.65, 1.1, .2]},
            {"name": "handle", "shape": "box", "material": material,
             "dimensions_m": [.04, .32, .04], "center_m": [.65, 1.29, .2]},
            {"name": "tool-stand", "shape": "box", "material": "iron", "anchored": True,
             "dimensions_m": [.40, .32, .40], "center_m": [.65, .90, .2]},
            {"name": "glass-block", "shape": "box", "material": "glass",
             "dimensions_m": [.12]*3, "center_m": [-.65, .81, .5]},
            {"name": "iron-block", "shape": "box", "material": "iron",
             "dimensions_m": [.12]*3, "center_m": [-.65, .81, -.3]}
        ]}), encoding="utf-8")
        ops = [
            {"op": "fix", "a": "handle", "b": "head", "at": [.65, 1.14, .2],
             "axis": [0, 1, 0], "holds_tension_n": 5000, "holds_shear_n": 5000},
            {"op": "tool_point", "body": "head", "tip": [.65, 1.06, .2],
             "pointing": [0, -1, 0], "width_m": width, "thickness_m": .04,
             "angle_deg": 30, "length_m": .1, "grip": [.65, 1.4, .2], "grip_body": "handle"},
            {"op": "snapshot"}]
        env = dict(os.environ)
        env.pop("OPENAI_API_KEY", None)
        try:
            seeded = subprocess.run([str(native), "--scene", str(scene), "--cell", ".02"],
                input="".join(json.dumps(op)+"\n" for op in ops), capture_output=True,
                text=True, encoding="utf-8", timeout=15, env=env)
            frames = [json.loads(line) for line in seeded.stdout.splitlines()]
            if seeded.returncode or len(frames) != 4 or not all(f.get("ok") for f in frames):
                raise RuntimeError("Native fixture initialization failed: " + seeded.stderr[-2000:] + str([f.get("error") for f in frames]))
            initial = root / "initial.json"
            initial.write_text(json.dumps(frames[-1]["snapshot"]), encoding="utf-8")
            self.errors = open(root / "worker-errors.txt", "w+", encoding="utf-8")
            self.child = subprocess.Popen([str(runtime), "--native", str(native), "--scene", str(scene),
                "--cell", ".02", "--world", self.world, "--actors", "player",
                "--initial-snapshot", str(initial)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.errors, text=True, encoding="utf-8", env=env,
                start_new_session=os.name != "nt",
                creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0)
            self.frames = queue.Queue(maxsize=64)
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            self.ready = self.frames.get(timeout=15)
            if self.ready is None or self.ready.get("status") != "ready":
                raise RuntimeError("Rust world owner did not start")
            joined = self.command({"kind": "join", "feet_m": [0, .75, 0]}, host=True)
            if joined["outcome"]["status"] != "applied":
                raise RuntimeError("Native avatar admission refused")
            self.command({"kind": "move", "velocity_m_s": [0, 0, 0], "heading_rad": 0, "jump": False})
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.child.stdout:
                self.frames.put(json.loads(line), timeout=3)
        except (ValueError, queue.Full):
            pass
        finally:
            try: self.frames.put(None, timeout=1)
            except queue.Full: pass

    def rpc(self, request):
        if self.closed or self.child.poll() is not None:
            raise RuntimeError("World stopped; start a fresh test world")
        self.child.stdin.write(json.dumps(request, allow_nan=False)+"\n")
        self.child.stdin.flush()
        while True:
            frame = self.frames.get(timeout=15)
            if frame is None:
                raise RuntimeError("Native world ended; start a fresh test world")
            if frame["schema"] == "banjo.worker-completion.v1":
                self.events.append(frame["outcome"])
            else:
                return frame

    def command(self, payload, host=False):
        self.sequence += 1
        return self.rpc({"principal": "player", "host_action": host, "command": {
            "schema": "banjo.command.v1", "world_id": self.world, "actor_id": "player",
            "command_id": "input-"+str(self.sequence), "input_sequence": self.sequence,
            "expected_revision": None, "payload": payload}})

    def observe(self):
        frame = self.rpc({"observe_actor": "player"})
        if "snapshot" not in frame:
            raise RuntimeError("World observation refused")
        return {"session": self.session, "snapshot": frame["snapshot"], "clock": frame["clock"],
                "events": list(self.events), "family": self.family, "material": self.material,
                "native": self.ready["native"], "runtime_sha256": self.runtime_sha256}

    def apply(self, request):
        action = request["action"]
        allowed = {"observe": {"action", "session"}, "preview": {"action", "session", "target"},
                   "move": {"action", "session", "id", "velocity", "heading"},
                   "pickup": {"action", "session", "id", "instance"},
                   "use": {"action", "session", "id", "target"}, "drop": {"action", "session", "id"}}
        if action not in allowed or set(request) != allowed[action]:
            raise ValueError("Unsupported world intention")
        with self.lock:
            self.last_seen = time.monotonic()
            if action == "observe": return self.observe()
            ident = request.get("id")
            if action != "preview":
                if not isinstance(ident, str) or len(ident) != 32 or any(c not in "0123456789abcdef" for c in ident):
                    raise ValueError("Expected an input identity")
                if ident in self.receipts:
                    original, result = self.receipts[ident]
                    if original != request: raise ValueError("Input identity reused with different intention")
                    return dict(self.observe(), outcome=result)
                if len(self.receipts) >= 4000:
                    raise ValueError("Sandbox input budget reached; start a new test world")
            state = self.observe()["snapshot"]
            if action == "move":
                velocity = vector(request["velocity"], 2)
                heading = request["heading"]
                if type(heading) not in (int, float) or not math.isfinite(heading) or abs(heading) > 7:
                    raise ValueError("Invalid heading")
                if velocity[1] != 0: raise ValueError("Walking cannot supply vertical velocity")
                payload = {"kind": "move", "velocity_m_s": velocity, "heading_rad": heading, "jump": False}
            elif action == "drop":
                payload = {"kind": "drop"}
            else:
                if action == "pickup":
                    if request["instance"] not in {"head", "handle", "glass-block", "iron-block"}:
                        raise ValueError("Choose a body in the test world")
                    body = next(b for b in state["bodies"] if b["name"] == request["instance"])
                    target = body["position_m"]
                else:
                    target = vector(request["target"])
                p = state["native_players"]["player"]
                w, x, y, z = p["orientation_wxyz"]
                up = [2*(x*y-w*z), 1-2*(x*x+z*z), 2*(y*z+w*x)]
                eye = [a+.77*b for a, b in zip(p["position_m"], up)]
                direction = [b-a for a, b in zip(eye, target)]
                length = math.sqrt(sum(v*v for v in direction))
                if length < .001: raise ValueError("Target overlaps eye")
                payload = {"kind": {"pickup": "pickup", "preview": "preview_tool_use", "use": "begin_tool_use"}[action],
                           "ray": {"from_m": eye, "direction": [v/length for v in direction], "max_distance_m": 2}}
                if action == "pickup": payload["instance_id"] = request["instance"]
            result = self.command(payload)["outcome"]
            summary = {k:v for k,v in result.items() if k != "snapshot"}
            if ident: self.receipts[ident] = (dict(request), summary)
            # poses removes the one-response preview field: return that exact
            # native preview alongside the fresh, complete render observation.
            response = dict(self.observe(), outcome=summary)
            if action == "preview": response["preview"] = result["snapshot"]["own_tool_preview"]
            return response

    def close(self):
        if self.closed: return
        self.closed = True
        if self.child:
            if self.child.poll() is None:
                self.child.stdin.close()
                try: self.child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Terminate only this sandbox's process tree on a stalled
                    # shutdown, so the native child cannot become an orphan.
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(self.child.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                    else:
                        try: os.killpg(self.child.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                    if self.child.poll() is None: self.child.kill()
                    self.child.wait(timeout=5)
            if hasattr(self, "reader"): self.reader.join(timeout=2)
            for stream in (self.child.stdin, self.child.stdout): stream.close()
        if hasattr(self, "errors"): self.errors.close()
        self.temp.cleanup()


class WorldManager:
    def __init__(self, native, runtime):
        self.native = Path(native).resolve(strict=True)
        self.runtime = Path(runtime).resolve(strict=True)
        self.worlds = {}
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.reaper = threading.Thread(target=self._expire, daemon=True)
        self.reaper.start()

    def _expire(self):
        while not self.stopped.wait(10):
            with self.lock:
                for ident, world in list(self.worlds.items()):
                    with world.lock:
                        if time.monotonic()-world.last_seen > 90:
                            world.close(); del self.worlds[ident]

    def request(self, request):
        if not isinstance(request, dict) or not isinstance(request.get("action"), str):
            raise ValueError("Expected a world intention")
        if request["action"] == "create":
            if set(request) != {"action", "family", "material"} or request["family"] not in FAMILIES or request["material"] not in {"iron", "glass", "oak"}:
                raise ValueError("Choose a declared laboratory tool")
            with self.lock:
                for ident, world in list(self.worlds.items()):
                    if time.monotonic()-world.last_seen > 90:
                        world.close(); del self.worlds[ident]
                if len(self.worlds) >= 2: raise ValueError("Two test worlds are already open; close one first")
                world = TestWorld(self.native, self.runtime, request["family"], request["material"])
                self.worlds[world.session] = world
                with world.lock: return world.observe()
        ident = request.get("session")
        if not isinstance(ident, str): raise ValueError("Expected a test world session")
        with self.lock:
            world = self.worlds.get(ident)
            if world is None: raise ValueError("Test world expired; start a new world")
            if request["action"] == "close":
                if set(request) != {"action", "session"}: raise ValueError("Invalid close intention")
                with world.lock: world.close()
                del self.worlds[ident]
                return {"closed": True}
        return world.apply(request)

    def close(self):
        self.stopped.set()
        with self.lock:
            for world in self.worlds.values():
                with world.lock: world.close()
            self.worlds.clear()
        self.reaper.join(timeout=2)
