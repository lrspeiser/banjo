"""Bounded loopback sandbox transport to the Rust-owned native world.

The browser supplies intentions, never native operations, clocks or actor IDs.
Fixtures are declared geometry and a native joint/tool point, not cut outcomes.
"""
from __future__ import annotations
import collections
import datetime
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


class WorldUnavailable(ValueError):
    """Public, bounded lifecycle refusal; never includes native exception text."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def vector(value, bound=20):
    if (not isinstance(value, list) or len(value) != 3 or
            any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > bound for v in value)):
        raise ValueError("Expected a bounded three-dimensional vector")
    return value


class TestWorld:
    def __init__(self, native, runtime, family, material, model="retained-soil", ground_material="concrete", log_root=None):
        self.temp = tempfile.TemporaryDirectory(prefix="banjo-3d-")
        self.child = None
        self.closed = False
        self.lock = threading.Lock()
        self.sequence = 0
        self.last_seen = time.monotonic()
        self.events = collections.deque(maxlen=8)
        self.receipts = collections.OrderedDict()
        self.world = "sandbox-" + uuid.uuid4().hex
        self.log_root = Path(log_root or Path(__file__).resolve().parents[1] / "build/world-impact-logs")
        self.log_root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_root / (self.world + ".jsonl")
        self.log_bytes = 0
        self.log_sequence = 0
        self.log_error = None
        self.impacts = []
        self.pending_impact = None
        self.session = uuid.uuid4().hex
        self.family, self.material = family, material
        self.model, self.ground_material = model, ground_material
        self.runtime_sha256 = hashlib.sha256(Path(runtime).read_bytes()).hexdigest()
        self.native_sha256 = hashlib.sha256(Path(native).read_bytes()).hexdigest()
        self._log("world-declaration", {"family":family,"material":material,"model":model,
            "ground_material":ground_material,"native_sha256":self.native_sha256,
            "runtime_sha256":self.runtime_sha256,"fracture_connected":False})
        width = FAMILIES[family]
        root = Path(self.temp.name)
        scene = root / "scene.json"
        declaration={"terrain": {"surface": "columns", "generate": {
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
        ]}
        if model in {"rigid-grains","rigid-slab"}:
            # A declared loose assembly of native collision bodies. No height
            # field, soil work rule, dig op, fragment launch or hidden deletion.
            del declaration["terrain"]
            declaration["bodies"][2]["dimensions_m"]=[.40,.32,.40]
            declaration["bodies"][2]["center_m"]=[.65,.90,.2]
            declaration["bodies"].append({"name":"bedrock-base","shape":"box","material":"concrete",
                "anchored":True,"dimensions_m":[2,.02,2],"center_m":[0,.01,0]})
            for body in declaration["bodies"][:5]:
                body["center_m"][1]-=.53
            # Keep the acquisition stand behind the sample, out of the swing.
            for body in declaration["bodies"][:3]:body["center_m"][2]=.85
            if model == "rigid-slab":
                # One intact body, not a prefragmented plate or a fracture claim.
                declaration["bodies"].append({"name":"ground-slab","shape":"box",
                    "material":ground_material,"dimensions_m":[1.2,.1,1.2],"center_m":[0,.07,0]})
            else:
                for layer in range(2):
                    for z in range(10):
                        for x in range(10):
                            declaration["bodies"].append({"name":f"grain-{layer}-{z}-{x}","shape":"box",
                                "material":ground_material,"dimensions_m":[.1,.1,.1],
                                "center_m":[-.54+x*.12,.07+layer*.1,-.54+z*.12]})
        if model in {"rigid-grains","rigid-slab"}:
            # Exact native collision primitives: no dormant lattice, fracture
            # trigger, launch velocity or hidden material removal for a grain.
            rigid=[b for b in declaration["bodies"] if b["name"].startswith("grain-") or b["name"] in {"glass-block","iron-block","ground-slab"}]
            declaration["bodies"]=[b for b in declaration["bodies"] if b not in rigid]
            for b in rigid:
                if b["name"]=="glass-block":b["center_m"]=[-.42,.28,.42]
                if b["name"]=="iron-block":b["center_m"]=[-.42,.28,0]
            declaration["precise_rigid_bodies"]=[{"name":b["name"],"material":b["material"],
                "position_m":b["center_m"],"parts":[{"shape":"box","dimensions_m":b["dimensions_m"],"center_local_m":[0,0,0]}]} for b in rigid]
        scene.write_text(json.dumps(declaration),encoding="utf-8")
        tool_z=.85 if model in {"rigid-grains","rigid-slab"} else .2
        offset=-.53 if model in {"rigid-grains","rigid-slab"} else 0
        ops = [
            {"op": "fix", "a": "handle", "b": "head", "at": [.65, 1.14+offset, tool_z],
             "axis": [0, 1, 0], "holds_tension_n": 5000, "holds_shear_n": 5000},
            {"op": "tool_point", "body": "head", "tip": [.65, 1.06+offset, tool_z],
             "pointing": [0, -1, 0], "width_m": width, "thickness_m": .04,
             "angle_deg": 30, "length_m": .1, "grip": [.65, 1.4+offset, tool_z], "grip_body": "handle"},
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
            # Start on the declared fixed base beside the loose test bed.
            # Standing on loose grains coupled the avatar's balance actuator
            # into the very sample being tested before any deliberate strike.
            feet = [0, .022, .82] if model in {"rigid-grains","rigid-slab"} else [0, .75, 0]
            joined = self.command({"kind": "join", "feet_m": feet}, host=True)
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
            raise WorldUnavailable("stopped")
        self.child.stdin.write(json.dumps(request, allow_nan=False)+"\n")
        self.child.stdin.flush()
        while True:
            frame = self.frames.get(timeout=15)
            if frame is None:
                raise WorldUnavailable("stopped")
            if frame["schema"] == "banjo.worker-completion.v1":
                self.events.append(frame["outcome"])
                self._log("worker-completion", {"outcome":{k:v for k,v in frame["outcome"].items() if k != "snapshot"}})
            else:
                return frame

    def command(self, payload, host=False):
        self.sequence += 1
        request = {"principal": "player", "host_action": host, "command": {
            "schema": "banjo.command.v1", "world_id": self.world, "actor_id": "player",
            "command_id": "input-"+str(self.sequence), "input_sequence": self.sequence,
            "expected_revision": None, "payload": payload}}
        try:
            return self.rpc(request)
        except (WorldUnavailable,queue.Empty,OSError) as error:
            self._log("native-command-failed", {"command_id":request["command"]["command_id"],
                "payload":payload,"failure_code":getattr(error,"code",type(error).__name__)})
            raise

    def _log(self, stage, data):
        # Persistent diagnostic evidence, separate from the disposable worker.
        # Never record the session capability or credentials. A bounded archive
        # refuses additional evidence explicitly; physics continues unchanged.
        if self.log_error: return
        row = {"schema":"banjo.impact-trace.v1","world_id":self.world,
            "sequence":self.log_sequence+1,"recorded_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "stage":stage,**data}
        line = (json.dumps(row,allow_nan=False,separators=(",",":"))+"\n").encode("utf-8")
        if self.log_bytes + len(line) > 128*1024*1024:
            self.log_error = "Diagnostic archive reached 128 MiB; subsequent evidence is not saved."
            return
        try:
            with self.log_path.open("ab") as stream: stream.write(line)
            self.log_bytes += len(line)
            self.log_sequence += 1
        except OSError:
            self.log_error = "Diagnostic archive could not be written; subsequent evidence is not saved."

    def _capture_impact(self, snapshot, clock):
        pending = self.pending_impact
        hit = snapshot.get("own_physical_hit")
        if not pending or not hit or hit.get("started_s") != pending["started_s"]: return
        body = next((b for b in snapshot["bodies"] if b["name"] == hit["target"]), None)
        self._log("native-observation", {"impact_id":pending["impact_id"],"clock":clock,
            "physical_hit":hit,"target_body":body,"own_hand":snapshot.get("own_hand")})
        if hit["active"]: return
        before = {b["name"]:b for b in pending.pop("before")["bodies"]}
        after = {b["name"]:b for b in snapshot["bodies"]}
        new_names = sorted(after.keys()-before.keys())
        removed_names = sorted(before.keys()-after.keys())
        pending["actual"] = {"physical_hit":hit,"target_body":body,
            "observed_new_bodies":new_names,"observed_removed_bodies":removed_names,
            "observed_body_mass_change_kg":sum(b["mass_kg"] for b in after.values())-sum(b["mass_kg"] for b in before.values()),
            "broken_bonds":None,"fracture_energy_j":None,"contact_impulse_n_s":None,
            "full_energy_balance_j":None}
        pending["status"] = "completed"
        pending["clock"] = clock
        pending["explanation"] = (
            "The selected target was contacted. It is an intact rigid body: no fracture law is connected."
            if hit["contacted"] else
            "The tool encountered an obstruction before reaching the selected target."
            if hit.get("obstruction") else
            "The native swing ended without confirmed contact on the selected target: " + (hit.get("reason") or "no_contact"))
        pending["limitations"] = ["Hand work is signed actuator work, not energy deposited in the target.",
            "No calibrated breakage prediction, bond damage or whole-system energy balance is available.",
            "Pose/mass observations and native contact detection do not certify conservation or material realism."]
        self._log("impact-completed", {"report":pending,"snapshot":snapshot,"clock":clock})
        self.impacts.append(pending)
        self.pending_impact = None

    def log_page(self, offset):
        if type(offset) is not int or not 0 <= offset <= self.log_bytes:
            raise ValueError("Invalid diagnostic offset")
        with self.log_path.open("rb") as stream:
            if offset:
                stream.seek(offset-1)
                if stream.read(1) != b"\n": raise ValueError("Diagnostic offset must be a record boundary")
            stream.seek(offset)
            rows = []
            for _ in range(64):
                line = stream.readline()
                if not line: break
                rows.append(json.loads(line))
            end = stream.tell()
        return {"records":rows,"next_offset":end,"complete":end>=self.log_bytes,
            "world_id":self.world,"log_error":self.log_error}

    def observe(self):
        frame = self.rpc({"observe_actor": "player"})
        if "snapshot" not in frame:
            raise RuntimeError("World observation refused")
        self._capture_impact(frame["snapshot"],frame["clock"])
        return {"session": self.session, "snapshot": frame["snapshot"], "clock": frame["clock"],
                "events": list(self.events), "family": self.family, "material": self.material,
                "model":self.model,"ground_material":self.ground_material,
                "native": self.ready["native"], "runtime_sha256": self.runtime_sha256,
                "impact_report": self.impacts[-1] if self.impacts else None,
                "impact_count":len(self.impacts),"log_error":self.log_error}

    def apply(self, request):
        action = request["action"]
        allowed = {"observe": {"action", "session"}, "impact-log":{"action","session","offset"},
                   "impact-history":{"action","session","offset"}, "preview": {"action", "session", "target"},
                   "preview-hit":{"action","session","target"},"hit":{"action","session","id","target"},
                   "move": {"action", "session", "id", "velocity", "heading"},
                   "pickup": {"action", "session", "id", "instance"},
                   "use": {"action", "session", "id", "target"}, "drop": {"action", "session", "id"}}
        if action not in allowed or set(request) != allowed[action]:
            raise ValueError("Unsupported world intention")
        with self.lock:
            self.last_seen = time.monotonic()
            if action == "observe": return self.observe()
            if action == "impact-log": return self.log_page(request["offset"])
            if action == "impact-history":
                offset = request["offset"]
                if type(offset) is not int or not 0 <= offset <= len(self.impacts): raise ValueError("Invalid history offset")
                return {"reports":self.impacts[offset:offset+32],"next_offset":min(offset+32,len(self.impacts)),
                    "complete":offset+32>=len(self.impacts)}
            ident = request.get("id")
            if action not in {"preview","preview-hit"}:
                if not isinstance(ident, str) or len(ident) != 32 or any(c not in "0123456789abcdef" for c in ident):
                    raise ValueError("Expected an input identity")
                if ident in self.receipts:
                    original, result = self.receipts[ident]
                    if original != request: raise ValueError("Input identity reused with different intention")
                    return dict(self.observe(), outcome=result)
                if len(self.receipts) >= 4000:
                    raise WorldUnavailable("input_budget")
            observed = self.observe()
            state = observed["snapshot"]
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
                    if request["instance"] not in {b["name"] for b in state["bodies"] if not b.get("anchored")}:
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
                payload = {"kind": {"pickup": "pickup", "preview": "preview_tool_use", "use": "begin_tool_use",
                    "preview-hit":"preview_hit","hit":"hit"}[action],
                           "ray": {"from_m": eye, "direction": [v/length for v in direction], "max_distance_m": 2}}
                if action == "pickup": payload["instance_id"] = request["instance"]
            report = None
            if action == "hit":
                preview_payload = dict(payload,kind="preview_hit")
                preflight = self.command(preview_payload)["outcome"]
                preview = preflight.get("snapshot",{}).get("own_hit_preview")
                report = {"schema":"banjo.impact-report.v1","impact_id":ident,"world_id":self.world,
                    "requested_target_m":target,"ray":payload["ray"],"before_clock":observed["clock"],
                    "expectation":{"native_preview":preview,"prediction_kind":"admission-only",
                        "fracture_supported":False,"fracture_prediction":None,
                        "description":"A reachable target permits a native swing; contact is not guaranteed. Intact rigid bodies cannot fracture in this world."}}
                self._log("impact-requested", {"report":report,"snapshot":state})
            result = self.command(payload)["outcome"]
            summary = {k:v for k,v in result.items() if k != "snapshot"}
            if report:
                report["command_outcome"] = summary
                hit = result.get("snapshot",{}).get("own_physical_hit")
                if summary["status"] == "applied" and hit and hit["active"]:
                    report.update(status="active",started_s=hit["started_s"],before=state)
                    self.pending_impact = report
                    self._log("impact-admitted", {"impact_id":ident,"outcome":summary,"physical_hit":hit})
                else:
                    report.update(status="refused",actual=None,
                        explanation="The native engine refused the requested swing: " + (summary.get("reason") or summary["status"]))
                    self.impacts.append(report)
                    self._log("impact-refused", {"report":report})
            elif action not in {"preview","preview-hit"}:
                self._log("player-command", {"input_id":ident,"payload":payload,"outcome":summary})
            if ident: self.receipts[ident] = (dict(request), summary)
            # poses removes the one-response preview field: return that exact
            # native preview alongside the fresh, complete render observation.
            response = dict(self.observe(), outcome=summary)
            if action == "preview": response["preview"] = result["snapshot"]["own_tool_preview"]
            if action == "preview-hit": response["preview"] = result["snapshot"]["own_hit_preview"]
            return response

    def close(self):
        if self.closed: return
        self.closed = True
        if self.pending_impact:
            report = self.pending_impact
            report.pop("before",None)
            report.update(status="interrupted",actual=None,explanation="The test world closed before a completed native impact observation.")
            self.impacts.append(report)
            self._log("impact-interrupted", {"report":report})
            self.pending_impact = None
        self._log("world-closed", {"impact_count":len(self.impacts)})
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
    def __init__(self, native, runtime, log_root=None):
        self.native = Path(native).resolve(strict=True)
        self.runtime = Path(runtime).resolve(strict=True)
        self.log_root = log_root
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
            if (not {"action","family","material"} <= set(request) or
                set(request)-{"action","family","material","model","ground_material"} or
                request["family"] not in FAMILIES or request["material"] not in {"iron", "glass", "oak"} or
                request.get("model","retained-soil") not in {"retained-soil","rigid-grains","rigid-slab"} or
                request.get("ground_material","concrete") not in {"concrete","glass","oak","iron"}):
                raise ValueError("Choose a declared laboratory tool")
            with self.lock:
                for ident, world in list(self.worlds.items()):
                    if time.monotonic()-world.last_seen > 90:
                        world.close(); del self.worlds[ident]
                if len(self.worlds) >= 2: raise ValueError("Two test worlds are already open; close one first")
                world = TestWorld(self.native, self.runtime, request["family"], request["material"],
                    request.get("model","retained-soil"),request.get("ground_material","concrete"),self.log_root)
                self.worlds[world.session] = world
                with world.lock: return world.observe()
        ident = request.get("session")
        if not isinstance(ident, str): raise ValueError("Expected a test world session")
        with self.lock:
            world = self.worlds.get(ident)
            if world is None:
                # Closing an already expired disposable session is safe and
                # lets a fresh-world request recover instead of getting stuck.
                if request["action"] == "close" and set(request) == {"action","session"}:
                    return {"closed": True}
                raise WorldUnavailable("expired")
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
