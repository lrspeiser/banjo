#!/usr/bin/env python3
"""Run fixed fabrication QA against a required native engine and retain evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import time

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args()
    engine=args.engine.resolve()
    if not engine.is_file():parser.error("Native live runner does not exist")
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    os.environ["BANJO_LIVE_ENGINE"]=str(engine)
    sys.path[:0]=[str(ROOT),str(ROOT/"tests"),str(ROOT/"playground")]
    import fabrication_tests
    from workshop_install_tests import ArticulationCompiler
    from workshop_install_engine_tests import NativeInstallation
    from material_qa import write_json
    started=time.time()
    cases=[]
    class Result(unittest.TextTestResult):
        def addSuccess(self,test):
            super().addSuccess(test)
            cases.append({"id":test.id(),"status":"passed",**({"measurements":test.native_evidence} if hasattr(test,"native_evidence") else {})})
        def addError(self,test,err):
            super().addError(test,err);cases.append({"id":test.id(),"status":"error","error":self._exc_info_to_string(err,test)})
        def addFailure(self,test,err):
            super().addFailure(test,err);cases.append({"id":test.id(),"status":"failed","error":self._exc_info_to_string(err,test)})
        def addSkip(self,test,reason):
            super().addSkip(test,reason);cases.append({"id":test.id(),"status":"skipped","reason":reason})
    suite=unittest.defaultTestLoader.loadTestsFromModule(fabrication_tests)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ArticulationCompiler))
    suite.addTest(NativeInstallation("test_compiled_bearing_moves_under_gravity_without_fusing_parts"))
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
    head=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True).stdout.strip()
    dirty=subprocess.run(["git","status","--porcelain"],cwd=ROOT,capture_output=True,text=True).stdout.strip()
    library=Path(os.environ["BANJO_LIBRARY"]).resolve() if os.environ.get("BANJO_LIBRARY") else None
    report={"schema":"banjo.fabrication-qa.v1","status":"passed" if result.wasSuccessful() and not result.skipped else "failed",
        "id":out.name,"started_unix_s":started,"finished_unix_s":time.time(),
        "total":result.testsRun,"completed":result.testsRun,"tests_run":result.testsRun,"results":cases,"source_revision":head,
        "engine_sha256":hashlib.sha256(engine.read_bytes()).hexdigest(),
        "source_dirty":bool(dirty),
        "library_sha256":hashlib.sha256(library.read_bytes()).hexdigest() if library and library.is_file() else None,
        "boundary":"Native/host integration and declared process accounting; no calibrated machining or whole-world qualification."}
    write_json(out/"report.json",report)
    return 0 if report["status"]=="passed" else 1
if __name__=="__main__":raise SystemExit(main())
