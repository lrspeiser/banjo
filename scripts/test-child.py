"""Apply hosted test-process limits before executing a trusted branch build."""
import os
from pathlib import Path
import sys

if sys.platform == 'linux':
    import resource
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)

root = Path(sys.argv[1]).resolve()
os.chdir(root)
if os.name == 'nt':
    # Windows exec starts a replacement PID, which would lose the supervisor's
    # owned process handle. Keep this PID for local testing and tree cleanup.
    import runpy
    sys.argv = [str(root/'scripts/voxel-lab.py'), *sys.argv[2:]]
    runpy.run_path(sys.argv[0], run_name='__main__')
else:
    os.execv(sys.executable, [sys.executable, '-u', str(root/'scripts/voxel-lab.py'), *sys.argv[2:]])
