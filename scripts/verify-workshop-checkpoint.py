#!/usr/bin/env python3
"""Run the existing Workshop gate plus optional native/browser checks.

No cloud model calls. Writes machine-readable evidence under build/.
Example: BANJO_CHROME=/usr/bin/google-chrome python scripts/verify-workshop-checkpoint.py \
  --engine build/workshop-ci/banjo_live_world_run --browser
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--engine', type=Path)
parser.add_argument('--browser', action='store_true')
args = parser.parse_args()
if args.browser and not args.engine:
    parser.error('--browser requires --engine')
env = {**os.environ, 'OPENAI_API_KEY': ''}
if args.engine:
    if not args.engine.is_file(): parser.error('engine file does not exist')
    env['BANJO_LIVE_ENGINE'] = str(args.engine.resolve())
if args.browser: env['BANJO_BROWSER_TESTS'] = 'required'
ci = (ROOT/'.github/workflows/ci.yml').read_text()
fast = ci.split('  workshop-fast:')[1].split('  build-test-and-capture:')[0]
files = re.findall(r'python3 (tests/[^ ]+) -v', fast)
if not files: raise RuntimeError('No Workshop test suites found in the existing CI gate')
commands = [[sys.executable, 'scripts/check-source-registration.py'], ['node','--check','playground/workshop.js']]
commands += [[sys.executable, f, '-v'] for f in files]
if args.engine:
    commands.append([sys.executable,'tests/workshop_bench_engine_tests.py','-v'])
    commands.append([sys.executable,'tests/workshop_install_engine_tests.py','-v'])
if args.browser: commands.append([sys.executable,'tests/workshop_browser_tests.py','-v'])
results=[]
for command in commands:
    print('\n===', ' '.join(command), '===', flush=True)
    start=time.monotonic()
    proc=subprocess.run(command,cwd=ROOT,env=env,check=False)
    results.append({'command':command,'exit':proc.returncode,'seconds':round(time.monotonic()-start,3)})
    if proc.returncode: break
out=ROOT/'build/workshop-verification.json';out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({'checks':results,'passed':all(r['exit']==0 for r in results)},indent=2)+'\n')
sys.exit(0 if all(r['exit']==0 for r in results) else 1)
