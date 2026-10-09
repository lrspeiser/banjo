"""Bounded JSON-lines bridge; CPU reference stays independent of the website."""
import contextlib
import atexit
import json
import os
import sys
from cpu_coupled_world import CpuCoupledWorld


def main():
    # Native SDK diagnostics can bypass Python redirect_stdout. Reserve the
    # original pipe for protocol replies and redirect the process stdout to
    # stderr, including Windows libraries using GetStdHandle rather than CRT.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()),'w',encoding='utf8',buffering=1)
    os.dup2(sys.stderr.fileno(),sys.stdout.fileno())
    if os.name == 'nt':
        import ctypes
        import msvcrt
        ctypes.windll.kernel32.SetStdHandle(ctypes.c_ulong(-11),ctypes.c_void_p(msvcrt.get_osfhandle(sys.stderr.fileno())))
    world = None
    for line in sys.stdin:
        try:
            if len(line.encode('utf8')) > 2_010_000:
                raise ValueError("Request size invalid")
            command = json.loads(line)
            if not isinstance(command, dict):
                raise ValueError("Command must be an object")
            op = command.get("op")
            if op!='restore' and len(line)>4096:raise ValueError('Request size invalid')
            with contextlib.redirect_stdout(sys.stderr):
                if op == "create" and set(command) == {"op", "declaration"}:
                    if not isinstance(command["declaration"], dict):
                        raise ValueError("Declaration must be an object")
                    if world is not None:
                        raise ValueError("One experiment per worker; close and create to reset")
                    d=dict(command['declaration'])
                    if d.pop('solver_backend','cpu-implicit-body')!='cpu-implicit-body':raise ValueError('CPU endpoint requires its explicit CPU backend')
                    world=CpuCoupledWorld(d)
                    state = world.snapshot()
                elif op == "advance" and set(command) == {"op", "steps"} and world:
                    if not hasattr(world, 'advance'):
                        raise ValueError('Controlled material loading has no dynamics clock')
                    state = world.advance(command["steps"])
                elif op == 'strain' and set(command) == {'op','opening_m'} and world and hasattr(world,'strain'):
                    state = world.strain(command['opening_m'])
                elif op == 'unload' and set(command) == {'op'} and world and hasattr(world,'strain'):
                    state = world.strain(unload=True)
                elif op == "snapshot" and set(command) == {"op"} and world:
                    state = world.snapshot()
                elif op == 'export' and set(command)=={'op'} and world and hasattr(world,'export_checkpoint'):
                    print(json.dumps(dict(ok=True,checkpoint=world.export_checkpoint()),separators=(',',':'),allow_nan=False),file=protocol,flush=True)
                    continue
                elif op == 'restore' and set(command)=={'op','checkpoint'}:
                    candidate=CpuCoupledWorld.from_checkpoint(command['checkpoint'])
                    state=candidate.snapshot()
                    world=candidate
                else:
                    raise ValueError("Unsupported CPU coupled command")
            reply = dict(ok=True, state=state)
        except (ValueError, TypeError, KeyError, RuntimeError, ImportError, MemoryError, OverflowError) as error:
            reply = dict(ok=False, error=str(error))
            if world is not None:
                reply["state"] = world.snapshot()
        print(json.dumps(reply, separators=(",", ":"), allow_nan=False), file=protocol, flush=True)


if __name__ == "__main__":
    main()
