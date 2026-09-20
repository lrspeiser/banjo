"""Bounded, isolated execution of the fixed fabrication qualification suite."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
import material_qa as artifacts
from mechanics_qa import binary

ROOT=Path(__file__).resolve().parents[1]
_LOCK=threading.Lock()

def stop_tree(process):
    if process.poll() is not None:return
    if os.name=="nt":
        subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    else:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    if process.poll() is None:process.kill()
    process.wait(timeout=10)

class Manager(artifacts.Manager):
    def __init__(self,app):
        super().__init__(app);self.root=Path(app.runs_path)/"fabrication-qa"
    def start(self,body):
        if body != {}:raise ValueError("Fabrication QA runs its fixed suite; use an empty object")
        engine=binary(self.app.engine_path)
        if not engine or not engine.is_file():raise ValueError("Build the native live runner first")
        library=next((engine.parent/name for name in ("banjo.dll","libbanjo.so","libbanjo.dylib")
                      if (engine.parent/name).is_file()),None)
        if library is None:raise ValueError("Build the shared native library beside the live runner")
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError("Fabrication QA is already running")
            self.run_id=uuid.uuid4().hex;self.cancel_event=threading.Event()
            self.pending={"schema":"banjo.fabrication-qa.v1","id":self.run_id,"status":"starting",
                          "total":0,"completed":0,"results":[],"started_unix_s":time.time()}
            folder=self.folder(self.run_id)
            def work():
                process=None
                try:
                    self.root.mkdir(parents=True,exist_ok=True)
                    env={**os.environ,"BANJO_LIBRARY":str(library),"BANJO_WORKSHOP_HOME":str(folder/"mcp")}
                    kwargs=({"creationflags":getattr(subprocess,"CREATE_NO_WINDOW",0)|subprocess.CREATE_NEW_PROCESS_GROUP}
                            if os.name=="nt" else {"start_new_session":True})
                    with (self.root/(self.run_id+".log")).open("w",encoding="utf-8") as log:
                        process=subprocess.Popen([sys.executable,str(ROOT/"scripts/fabrication_qa.py"),
                            "--engine",str(engine),"--out",str(folder)],cwd=ROOT,env=env,
                            stdin=subprocess.DEVNULL,stdout=log,stderr=log,**kwargs)
                        deadline=time.monotonic()+120
                        while process.poll() is None:
                            if self.cancel_event.wait(.1) or time.monotonic()>=deadline:
                                stop_tree(process)
                                raise ValueError("cancelled" if self.cancel_event.is_set() else "Fabrication QA exceeded 120 seconds")
                        if not (folder/"report.json").is_file():raise ValueError("QA did not produce a final report")
                        report=artifacts.read_json(folder/"report.json")
                        if process.returncode and report.get("status")=="passed":raise ValueError("QA process failed after reporting success")
                except Exception as exc:
                    if process is not None:stop_tree(process)
                    artifacts.write_json(folder/"report.json",{**self.pending,
                        "status":"cancelled" if self.cancel_event.is_set() else "failed","error":str(exc)})
            self.thread=threading.Thread(target=work,name="banjo-fabrication-qa",daemon=True)
            self.thread.start()
            return dict(self.pending)

def manager(app):
    with _LOCK:
        if not hasattr(app,"fabrication_qa"):app.fabrication_qa=Manager(app)
        return app.fabrication_qa
