"""Declared material laws and occupied grids; no outcome/fragment templates."""
from pathlib import Path
import copy
import json
import math

destination=Path(__file__).resolve().parents[1]/"assets/runtime-v2"
destination.mkdir(parents=True,exist_ok=True)

def material(name,density,modulus,strength,toughness,damping,color,fracture=True,yield_stress=0,failure="cohesive"):
    expand=lambda x: [x]*3 if isinstance(x,(float,int)) else x
    return dict(id=name,density_kg_m3=density,young_modulus_pa=expand(modulus),tensile_strength_pa=expand(strength),
                fracture_energy_j_m2=expand(toughness),damping_ratio=damping,friction=.4,yield_strength_pa=yield_stress,
                fracture_enabled=fracture,failure_law=failure,color_rgb=color,
                provenance="Experimental directional axial lattice parameters. Not a calibrated continuum or prediction of real fruit/wood cutting.")

materials=[material("glass",2500,70e9,45e6,8,.025,0x71d8e1,failure="brittle"),
           material("oak",700,[.7e9,12e9,1e9],[4e6,90e6,5e6],[1500,20000,1500],.15,0xc89452),
           material("iron",7870,211e9,250e6,1e5,.04,0xa7b7c6,False),
           material("soft-tissue",1000,4e4,1.5e4,150,.4,0xe96c56),
           material("ductile-demo",7870,4e6,3e6,1e4,.2,0x929ad6,False,1e5)]

def scene(name):
    return dict(package_version=2,physics_abi="banjo-network-2",backend="material-network-v2",name=name,units="SI",
                required_capabilities=["cell-deformation","cohesive-damage"],fixed_dt_s=1/480,max_steps_per_call=240,
                solver_iterations=24,gravity_m_s2=[0,-9.81,0],ground=dict(half_length_m=2,half_width_m=2,friction=.4),materials=copy.deepcopy(materials),objects=[])

def body(identifier,name,substance,shape,dimensions,position,resolution=None,velocity=None,orientation=None,pinned=False):
    o=dict(id=identifier,name=name,material=substance,shape=shape,dimensions_m=dimensions,
           representation="network" if resolution else "rigid",position_m=position,orientation_wxyz=orientation or [1,0,0,0],
           velocity_m_s=velocity or [0,0,0],spin_rad_s=[0,0,0])
    if resolution: o.update(resolution=resolution,pin_boundary=pinned)
    return o

def save(name,s): (destination/name).write_text(json.dumps(s,indent=2)+"\n",encoding="utf-8")

for ordinal,(name,shape,dims) in enumerate([("Sharp wedge","wedge",[.06,.12,.10]),("Blunt equal-volume block","box",[.03,.12,.10])],1):
    s=scene(name+" / glass, oak, iron, soft tissue")
    for i,substance in enumerate(["glass","oak","iron","soft-tissue"]):
        x=(i-1.5)*.32
        s["objects"] += [body(2*i+1,substance+" target",substance,"ellipsoid",[.16,.16,.16],[x,.085,0],[5,5,5]),
                          body(2*i+2,"iron tool","iron",shape,dims,[x+.025,.32,0],velocity=[0,-1,0])]
    save(f"{ordinal:02d}-{'sharp' if ordinal==1 else 'blunt'}-four-materials.json",s)

s=scene("Local axe strike / clamped oak panel / free iron wedge")
s["objects"]=[body(1,"oak panel","oak","box",[.30,.40,.06],[0,.22,0],[9,12,2],pinned=True),
              body(2,"iron axe head","iron","wedge",[.07,.14,.09],[.035,.26,.22],velocity=[0,0,-12],orientation=[math.sqrt(.5),math.sqrt(.5),0,0])]
save("03-axe-oak-panel.json",s)

s=scene("Soft tissue / offset cut and gravity / freely falling tool")
s["objects"]=[body(1,"soft tissue volume","soft-tissue","ellipsoid",[.18,.16,.16],[0,.085,0],[7,6,6]),
              body(2,"iron blade","iron","wedge",[.025,.10,.14],[.035,.26,0],velocity=[0,-4,0])]
save("04-soft-tissue-offset-cut.json",s)

s=scene("Continuous first impact / iron on glass, oak and iron cubes")
for i,substance in enumerate(["glass","oak","iron"]):
    x=(i-1)*.36
    s["objects"] += [body(2*i+1,substance+" cube",substance,"box",[.09,.09,.09],[x,.047,0],[3,3,3]),
                     body(2*i+2,"iron cube","iron","box",[.09,.09,.09],[x+.004,.55,0])]
save("05-continuous-cube-drop.json",s)

s=scene("Four materials / supported at rest / no tool")
for i,substance in enumerate(["glass","oak","iron","soft-tissue"]):
    s["objects"].append(body(i+1,substance,substance,"ellipsoid",[.16,.16,.16],[(i-1.5)*.32,.085,0],[5,5,5]))
save("06-rest-control.json",s)

s=scene("Permanent local deformation / ductile demonstrator")
s["objects"]=[body(1,"ductile coupon","ductile-demo","box",[.24,.30,.05],[0,.17,0],[8,10,2],pinned=True),
              body(2,"iron punch","iron","box",[.045,.045,.10],[.025,.18,.20],velocity=[0,0,-2])]
save("07-ductile-indentation.json",s)

s=scene("Free flight / glass, oak, iron, soft tissue")
s["ground"]=None;s["gravity_m_s2"]=[0,0,0]
for i,substance in enumerate(["glass","oak","iron","soft-tissue"]):
    s["objects"].append(body(i+1,substance,substance,"box",[.09,.09,.09],[(i-1.5)*.3,.2,0],[3,3,3],velocity=[0,0,.3]))
save("08-free-flight.json",s)
print("Wrote 8 material-network-v2 packages")
