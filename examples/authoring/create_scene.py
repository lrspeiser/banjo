"""Generate a matched iron-ball panel scene, validate it and optionally run it."""
from pathlib import Path
import argparse
import json
from banjo_authoring import EngineCLI, make_object, make_package, write_package


def panel_scene(speed_m_s: float = 6):
    objects = []
    for lane, (preset, x) in enumerate([
        ("glass_panel", -.4), ("wood_panel", 0), ("iron_panel", .4)
    ]):
        objects += [
            make_object(preset, 2 * lane + 1, position_m=[x, .2, 0]),
            make_object("iron_ball", 2 * lane + 2, position_m=[x + .015, .21, .2],
                        velocity_m_s=[0, 0, -speed_m_s]),
        ]
    return make_package(
        objects, name=f"Authored glass / wood / iron comparison at {speed_m_s:g} m/s",
        ground={"half_length_m": 2, "half_width_m": 2, "friction": .4},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New package file; no overwrite")
    parser.add_argument("--speed", type=float, default=6)
    parser.add_argument("--steps", type=int, default=0, help="0 validates; 1..24000 runs a fresh world")
    args = parser.parse_args()
    if not 0 <= args.steps <= 24000:
        parser.error("steps must be 0..24000")
    if not 0 <= args.speed <= 30:
        parser.error("speed must be 0..30 m/s")
    path = write_package(panel_scene(args.speed), args.output)
    engine = EngineCLI(args.engine)
    report = engine.run(path, args.steps) if args.steps else engine.validate(path)
    print(json.dumps(report, indent=2))
