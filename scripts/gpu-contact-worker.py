"""Bounded JSON-lines bridge; CUDA physics stays independent of the website."""
import contextlib
import json
import sys
from gpu_contact_world import GpuContactWorld


def main():
    world = None
    for line in sys.stdin:
        try:
            if len(line) > 4096:
                raise ValueError("Request size invalid")
            command = json.loads(line)
            if not isinstance(command, dict):
                raise ValueError("Command must be an object")
            op = command.get("op")
            with contextlib.redirect_stdout(sys.stderr):
                if op == "create" and set(command) == {"op", "declaration"}:
                    if not isinstance(command["declaration"], dict):
                        raise ValueError("Declaration must be an object")
                    if world is not None:
                        raise ValueError("One experiment per worker; close and create to reset")
                    if command["declaration"].get("device", "cuda:0") != "cuda:0":
                        raise ValueError("The GPU endpoint requires CUDA; no CPU fallback")
                    world = GpuContactWorld(command["declaration"])
                    state = world.snapshot()
                elif op == "advance" and set(command) == {"op", "steps"} and world:
                    state = world.advance(command["steps"])
                elif op == "snapshot" and set(command) == {"op"} and world:
                    state = world.snapshot()
                else:
                    raise ValueError("Unsupported GPU command")
            reply = dict(ok=True, state=state)
        except (ValueError, TypeError, KeyError, RuntimeError) as error:
            reply = dict(ok=False, error=str(error))
            if world is not None:
                reply["state"] = world.snapshot()
        print(json.dumps(reply, separators=(",", ":"), allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
