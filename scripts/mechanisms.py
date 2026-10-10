"""Bounded SI articulated/sleep reference adapter; no rendering or outcome presets."""
from __future__ import annotations
import ctypes
import hashlib
import math
from pathlib import Path
import time

MATERIALS = {"glass":2500., "oak":700., "iron":7870., "ice":917.}
ROOT=Path(__file__).resolve().parents[1]

def _number(value,name,low,high):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError(f"{name} must be finite in [{low}, {high}] SI")
    return float(value)

def run_experiment(payload, library):
    allowed={"material","density_kg_m3","length_m","width_m","thickness_m","angle_deg","omega_rad_s",
             "gravity_m_s2","force_x_n","force_y_n","torque_nm","load_time_s","release_time_s","duration_s","dt_s"}
    if not isinstance(payload,dict) or set(payload)-allowed:raise ValueError("Unknown mechanism fields")
    material=payload.get("material","iron")
    if material not in MATERIALS:raise ValueError("Material must be glass, oak, iron or ice")
    density=_number(payload.get("density_kg_m3",MATERIALS[material]),"density",100,30000)
    length=_number(payload.get("length_m",1.),"length",.1,2.)
    width=_number(payload.get("width_m",.12),"width",.01,.5)
    thick=_number(payload.get("thickness_m",.05),"thickness",.005,.5)
    a=math.radians(_number(payload.get("angle_deg",35.),"angle",-150,150))
    omega=_number(payload.get("omega_rad_s",0.),"omega",-10,10)
    g=_number(payload.get("gravity_m_s2",9.81),"gravity",0,20)
    fx=_number(payload.get("force_x_n",0.),"force_x",-1000,1000)
    fy=_number(payload.get("force_y_n",0.),"force_y",-1000,1000)
    drive=_number(payload.get("torque_nm",0.),"torque",-1000,1000)
    load_time=_number(payload.get("load_time_s",0.),"load_time",0,10)
    release_time=_number(payload.get("release_time_s",10.),"release_time",0,10)
    duration=_number(payload.get("duration_s",3.),"duration",.01,5)
    dt=_number(payload.get("dt_s",1/480),"dt",1/1920,1/120)
    steps=round(duration/dt)
    if abs(steps*dt-duration)>1e-10:raise ValueError("Duration must contain a whole number of steps")
    for event,name in [(load_time,"load_time"),(release_time,"release_time")]:
        if abs(event/dt-round(event/dt))>1e-8:raise ValueError(f"{name} must align with dt")
    mass=density*length*width*thick
    ic=mass*(length*length+width*width)/12
    ip=ic+mass*(length*.5)**2
    libpath=Path(library).resolve()
    native=ctypes.CDLL(str(libpath))
    native.banjo_mechanism_abi.restype=ctypes.c_int
    if native.banjo_mechanism_abi()!=1:raise ValueError("Mechanism ABI mismatch")
    arr8=ctypes.c_double*8;arr10=ctypes.c_double*10;arr16=ctypes.c_double*16
    native.banjo_mechanism_step.argtypes=[ctypes.POINTER(ctypes.c_double)]*4
    native.banjo_mechanism_step.restype=ctypes.c_int
    state=arr8(0,a,omega,length*.5*math.sin(a),1.5-length*.5*math.cos(a),
               length*.5*math.cos(a)*omega,length*.5*math.sin(a)*omega,1)
    initial=list(state);frames=[];receipts=[];transitions=[];start=time.perf_counter()
    energy0=.5*ip*omega**2+mass*g*state[4]
    total_work=0.;max_res=0.;reaction=[0.,0.];sleep_steps=0;max_p=0.;max_l=0.
    stride=max(1,math.ceil(steps/1200))
    def frame():
        return {"time_s":state[0],"angle_rad":state[1],"omega_rad_s":state[2],
                "com_m":[state[3],state[4],0.],"velocity_m_s":[state[5],state[6],0.],
                "mode":["equilibrium-sleep","articulated-hinge","rigid-free"][int(state[7])],
                "body_id":"mechanism-bar","matter_id":"mechanism-bar:occupied-box",
                "energy_j":.5*mass*(state[5]**2+state[6]**2)+.5*ic*state[2]**2+mass*g*state[4]}
    frames.append(frame())
    for step in range(steps):
        if time.perf_counter()-start>10:raise RuntimeError("Mechanism work limit; no partial result accepted")
        loaded=step*dt>=load_time-1e-12
        support=step*dt<release_time-1e-12
        p=arr10(mass,ip,ic,length,g,fx if loaded else 0,fy if loaded else 0,drive if loaded else 0,int(support),dt)
        candidate=arr8();r=arr16()
        code=native.banjo_mechanism_step(p,state,candidate,r)
        if code:raise RuntimeError(f"Native mechanism refused interval {step}: code {code}; reduce dt or force")
        tolerance=2e-10*(1+abs(energy0)+abs(total_work)+abs(r[2]))
        if abs(r[3])>tolerance:raise RuntimeError("Native mechanism energy gate failed")
        previous=int(state[7]);state=candidate
        if int(state[7])!=previous:transitions.append({"time_s":step*dt,"from":previous,"to":int(state[7]),
            "reason":"support removed" if not support else "load changed" if loaded and (fx or fy or drive) else "exact stable equilibrium"})
        sleep_steps+=int(state[7]==0)
        total_work+=r[2];max_res=max(max_res,abs(r[3]));reaction[0]+=r[4];reaction[1]+=r[5]
        max_p=max(max_p,abs(r[13]),abs(r[14]));max_l=max(max_l,abs(r[15]))
        if max_p>1e-9*(1+mass) or max_l>1e-9*(1+mass):raise RuntimeError("Momentum/reaction gate failed")
        if step%stride==0 or step==steps-1:
            frames.append(frame());receipts.append({"time_s":state[0],"energy_residual_j":r[3],"support_impulse_ns":[r[4],r[5],0],
                "external_impulse_ns":[r[6],r[7],0],"joint_angular_impulse_nms":r[8],"external_work_j":r[2],
                "position_equation_residual_rad":r[9],"iterations":int(r[10]),
                "support_angular_impulse_nms":[0,0,r[11]],"external_angular_impulse_nms":[0,0,r[12]],
                "momentum_residual_ns":[r[13],r[14],0],"angular_residual_nms":[0,0,r[15]]})
    elapsed=time.perf_counter()-start
    final=frame()
    drift=final["energy_j"]-energy0-total_work
    if abs(drift)>2e-8*(1+abs(energy0)+abs(total_work)):raise RuntimeError("Whole-run energy gate failed")
    source_hash=hashlib.sha256((ROOT/"src/physics/MechanismCpuApi.cpp").read_bytes()+(ROOT/"scripts/mechanisms.py").read_bytes()).hexdigest()
    return {"schema":"banjo-mechanism-reference-1","source_sha256":source_hash,
        "native_sha256":hashlib.sha256(libpath.read_bytes()).hexdigest(),"abi":1,"material":material,
        "source_files":["src/physics/MechanismCpuApi.cpp","scripts/mechanisms.py"],
        "binary_name":libpath.name,
        "geometry":{"length_m":length,"width_m":width,"thickness_m":thick,"density_kg_m3":density},
        "mass_kg":mass,"inertia_pin_kg_m2":ip,"inertia_com_kg_m2":ic,"initial_state":initial,"final_state":list(state),
        "frames":frames,"receipts":receipts,"transitions":transitions,
        "audit":{"energy_residual_j":drift,"max_step_energy_residual_j":max_res,"external_work_j":total_work,
                 "support_impulse_ns":reaction,"sleep_steps":sleep_steps,"sleep_omitted_motion_bound_m":0.,
                 "max_momentum_residual_ns":max_p,"max_angular_residual_nms":max_l,
                 "accepted_time_s":state[0],"calculation_wall_s":elapsed,"wall_per_sim_second":elapsed/state[0],"dt_s":dt},
        "limits":["Ideal unbreakable fixed-axis joint; rigid rectangular bar; no deformable attachments or contact",
                  "Sleep only exact stable equilibrium; all vibration retained otherwise",
                  "Support removal continues actual free rigid motion; reattachment refused",
                  "Discrete-gradient mean torque; continuous-trajectory accuracy needs timestep refinement",
                  "No fluid drive, thermal coupling, plasticity, grain, fracture or general multi-body joint graph"]}
