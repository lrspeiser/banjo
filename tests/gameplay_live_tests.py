"""Real native/browser-HTTP/MCP roundtrip. Requires built banjo and live runner."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib import request, error

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"mcp"), str(ROOT/"playground")]
import expedition_mcp_tools as mcp


class LiveExpedition(unittest.TestCase):
    def test_native_clock_full_batch_switch_restart_and_mcp(self):
        with tempfile.TemporaryDirectory(prefix="banjo-expedition-") as folder:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1",0))
                port=sock.getsockname()[1]
            url=f"http://127.0.0.1:{port}"
            previous=os.environ.get("BANJO_PLAYGROUND_URL")
            os.environ["BANJO_PLAYGROUND_URL"]=url
            log=open(Path(folder)/"server.log","w")
            process=None
            # The platform CLI beside the live runner, named as this platform
            # names programs: the server looks for banjo_live_world_run with
            # the engine's own suffix, so a Linux build needs none.
            live_engine=Path(os.environ["BANJO_LIVE_ENGINE"])
            engine=live_engine.with_name("banjo_platform_cli"+live_engine.suffix)
            def start():
                proc=subprocess.Popen([sys.executable,str(ROOT/"playground/server.py"),
                    "--port",str(port),"--rooms",str(Path(folder)/"rooms"),
                    "--runs",str(Path(folder)/"runs"), "--engine",str(engine)],cwd=ROOT,stdout=log,stderr=log,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                for _ in range(150):
                    if proc.poll() is not None: raise RuntimeError("server exited")
                    try:
                        with request.urlopen(url+"/api/status",timeout=.5): return proc
                    except (OSError,error.URLError): time.sleep(.1)
                proc.terminate()
                raise RuntimeError("server did not start")
            def post(path, body):
                return mcp._post(path,body)
            try:
                process=start()
                opened=post("/api/world/open",{"scene":"expedition"})
                session=opened["session"]
                state=opened["gameplay"]
                self.assertEqual(state["generation"]["status"],"viable")
                def step(seconds=1):
                    answer=None
                    for _ in range(seconds):
                        answer=post("/api/live/act",{"session":session,"op":"step","dt":1/120,"n":120})
                    return answer["gameplay"]
                def act(op, **extra):
                    return post("/api/world/gameplay",{"session":session,"op":"action",
                        "action":{"action":op,"request_id":f"a-{time.monotonic_ns()}",
                                  "at_m":state["spawn_m"],**extra}})["gameplay"]
                for kind,kg in (("stone",2),("dry_wood",1),("wet_wood",1)):
                    node=next(n for n in state["nodes"] if n["kind"]==kind)
                    state=act("gather",node=node["id"],kg=kg,at_m=node["at_m"])
                    state=step()
                state=act("build")
                state=act("load")
                state=act("fuel")
                state=act("light")
                state=step(35)
                self.assertGreater(state["dryer"]["heat_j"],0)
                self.assertGreater(state["dryer"]["water_kg"],0)
                state=act("extinguish")  # acknowledged action durably saves both halves
                before=state
                # Scene switching must preserve the engine clock even in this process.
                post("/api/world/open",{"scene":"valley"})
                reopened=post("/api/world/open",{"scene":"expedition"})
                session=reopened["session"]
                self.assertEqual(reopened["gameplay"],before)
                # Termination simulates losing the server after an acknowledged save.
                process.terminate()
                process.wait(timeout=15)
                process=start()
                reopened=post("/api/world/open",{"scene":"expedition"})
                session=reopened["session"]
                self.assertEqual(reopened["restored"]["tier"],"whole")
                self.assertEqual(reopened["gameplay"],before)
                state=act("light")
                state=step(500)
                self.assertLess(state["dryer"]["water_kg"],1e-9)
                self.assertGreater(state["dryer"]["fuel_kg"],0)
                state=step(900)
                state=act("collect")
                self.assertAlmostEqual(state["inventory_kg"]["dry_wood"],1.1)
                self.assertLess(abs(state["audit"]["energy_residual_j"]),1e-5)
                self.assertLess(abs(state["audit"]["material_residual_kg"]),1e-9)
                # Both MCP distributions publish real handlers to this same HTTP world.
                import banjo_mcp, banjo_platform_mcp
                for core in (banjo_mcp,banjo_platform_mcp):
                    answer=core.HANDLERS["expedition_state"]({"session":session})
                    self.assertEqual(answer["gameplay"],state)
                    self.assertIn("expedition_action",{t["name"] for t in core.TOOLS})
                waited=banjo_platform_mcp.HANDLERS["expedition_wait"]({"session":session,"seconds":1})
                self.assertAlmostEqual(waited["gameplay"]["time_s"]-state["time_s"],1.0,places=6)
                print("native expedition:",json.dumps({"time_s":state["time_s"],"audit":state["audit"]}))
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
                log.close()
                if previous is None: os.environ.pop("BANJO_PLAYGROUND_URL",None)
                else: os.environ["BANJO_PLAYGROUND_URL"]=previous


if __name__=="__main__": unittest.main()
