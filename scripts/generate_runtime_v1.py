"""Reproducible, material-comparative initial packages; no stored trajectories."""
import json
import math
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / "assets" / "runtime-v1"
destination.mkdir(parents=True, exist_ok=True)

def body(identifier, material, position, shape="sphere", velocity=None):
    result = dict(id=identifier, material=material, shape=shape,
                  position_m=position, orientation_wxyz=[1, 0, 0, 0],
                  velocity_m_s=velocity or [0, 0, 0], spin_rad_s=[0, 0, 0], seed=1729)
    result.update(radius_m=.045) if shape == "sphere" else result.update(dimensions_m=[.09, .09, .09])
    return result

def scene(name):
    return dict(package_version=1, physics_abi="banjo-platform-1", name=name,
                units="SI", backend="compiled-impact-v1",
                required_capabilities=["compiled-response", "persistent-damage"],
                fixed_dt_s=1/480, max_steps_per_call=240, gravity_m_s2=[0, -9.81, 0],
                bowl=None, objects=[])

def save(name, package):
    (destination / name).write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")

for number, height in enumerate([.15, .5, 1.5, 3.0], 1):
    s = scene(f"Live iron drop / glass, wood, iron / {height:g} m")
    s["ground"] = dict(half_length_m=1.4, half_width_m=.7, thickness_m=.2, surface="concrete")
    for pair, material in enumerate(["glass", "oak", "iron"]):
        x = (pair-1)*.4
        s["objects"] += [body(2*pair+1, material, [x, .045, 0]), body(2*pair+2, "iron", [x+.004, height, 0])]
    save(f"{number:02d}-iron-drop-{height:g}m.json", s)

s = scene("Live cube drop / glass, wood, iron / 1.5 m")
s["ground"] = dict(half_length_m=1.4, half_width_m=.7, thickness_m=.2, surface="concrete")
for pair, material in enumerate(["glass", "oak", "iron"]):
    x = (pair-1)*.4
    s["objects"] += [body(2*pair+1, material, [x, .045, 0], "box"), body(2*pair+2, "iron", [x+.004, 1.5, 0], "box")]
save("05-cube-drop-1.5m.json", s)

s = scene("Live bowl / glass, wood, iron")
s["bowl"] = dict(radius_m=1.2, depth_m=.55, tilt_degrees=0, surface="concrete")
for i, material in enumerate(["glass", "oak", "iron"]):
    x = [-.7, 0, .7][i]; z = [0, .7, 0][i]
    a = .55/1.2**2
    scale = .045/math.sqrt(1+4*a*a*(x*x+z*z))
    s["objects"].append(body(i+1, material, [x-2*a*x*scale, a*(x*x+z*z)+scale, z-2*a*z*scale]))
save("06-bowl-three-materials.json", s)

s = scene("Live free flight / zero local solves")
s["gravity_m_s2"] = [0, 0, 0]
for i, material in enumerate(["glass", "oak", "iron"]):
    s["objects"].append(body(i+1, material, [(i-1)*.4, .5, 0], velocity=[0, 0, .4]))
save("07-free-flight.json", s)

s = scene("Live load test / 96 objects / glass, wood, iron")
s["ground"] = dict(half_length_m=4, half_width_m=4, thickness_m=.2, surface="concrete")
for i in range(96):
    material = ["glass", "oak", "iron"][i%3]
    s["objects"].append(body(i+1, material, [(i%12-5.5)*.25, .2+(i//12)*.2, (i//12-3.5)*.25]))
save("08-load-96-objects.json", s)
print(f"Wrote 8 initial-state packages to {destination}")
