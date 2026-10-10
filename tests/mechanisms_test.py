"""Independent pendulum, applied-work, release, sleep/wake and material controls."""
import ctypes
import json
import math
import platform
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from mechanisms import run_experiment

def main(library, evidence_path=None):
    evidence={}
    for material in ("glass","oak","iron","ice"):
        base={"material":material,"duration_s":2.,"angle_deg":35.}
        run=run_experiment(base,library)
        a=run["audit"]
        assert abs(a["energy_residual_j"])<1e-8
        assert a["sleep_steps"]==0
        assert a["max_momentum_residual_ns"]<1e-10 and a["max_angular_residual_nms"]<1e-10
        # Same shape and g: ideal pendulum angular path is density independent.
        if evidence:
            first=next(iter(evidence.values()))
            assert abs(run["final_state"][1]-first["final_angle_rad"])<1e-12
        evidence[material]={**a,"mass_kg":run["mass_kg"],"final_angle_rad":run["final_state"][1]}
        driven=run_experiment({**base,"gravity_m_s2":0.,"angle_deg":0.,"torque_nm":.2},library)
        expected=.5*.2*4/driven["inertia_pin_kg_m2"]
        assert abs(driven["final_state"][1]-expected)<2e-11
        assert abs(driven["audit"]["external_work_j"]-.2*expected)<2e-11
        assert abs(driven["audit"]["energy_residual_j"])<1e-10
        # Equilibrium remains exact; load wakes without deleting stored velocity.
        sleep=run_experiment({**base,"angle_deg":0.},library)
        assert sleep["audit"]["sleep_steps"]==960
        assert sleep["final_state"][1:3]==[0.,0.]
        wake=run_experiment({**base,"angle_deg":0.,"load_time_s":.5,"force_x_n":.3},library)
        assert wake["audit"]["sleep_steps"]==240
        assert any(t["to"]==1 and t["reason"]=="load changed" for t in wake["transitions"])
        release=run_experiment({**base,"angle_deg":0.,"release_time_s":.5},library)
        assert release["final_state"][7]==2
        assert abs(release["final_state"][4]-(1.-.5*9.81*1.5**2))<1e-11
        assert abs(release["final_state"][6]+9.81*1.5)<1e-11
        assert release["audit"]["sleep_steps"]==240
        evidence[material]["release_energy_residual_j"]=release["audit"]["energy_residual_j"]
        # Release while moving must transfer COM velocity and intrinsic spin, not reset.
        at_release=run_experiment({**base,"duration_s":.5},library)["final_state"]
        moving_release=run_experiment({**base,"release_time_s":.5},library)
        final=moving_release["final_state"]
        assert abs(final[3]-(at_release[3]+1.5*at_release[5]))<1e-10
        assert abs(final[4]-(at_release[4]+1.5*at_release[6]-.5*9.81*1.5**2))<1e-10
        assert abs(final[2]-at_release[2])<1e-12
        assert abs(moving_release["audit"]["energy_residual_j"])<1e-8
        evidence[material]["moving_release_energy_residual_j"]=moving_release["audit"]["energy_residual_j"]
    # Timestep convergence against a common-time refined trajectory.
    angles=[]
    for dt in (1/120,1/240,1/480,1/1920):
        angles.append(run_experiment({"angle_deg":70.,"dt_s":dt,"duration_s":2.},library)["final_state"][1])
    errors=[abs(x-angles[-1]) for x in angles[:-1]]
    assert errors[0]/errors[1]>3.8 and errors[1]/errors[2]>3.8
    # Small-angle independent linear pendulum oracle; finite amplitude tolerance explicit.
    small=run_experiment({"angle_deg":.001,"duration_s":1.},library)
    freq=math.sqrt(small["mass_kg"]*9.81*.5/small["inertia_pin_kg_m2"])
    expected=math.radians(.001)*math.cos(freq)
    assert abs(small["final_state"][1]-expected)<4e-10
    radial=run_experiment({"gravity_m_s2":0.,"angle_deg":0.,"force_y_n":-5.},library)
    assert radial["final_state"][1:3]==[0.,0.]
    # Retained tiny vibration is awake, never numerically clipped into sleep.
    assert run_experiment({"angle_deg":1e-10,"duration_s":.1},library)["audit"]["sleep_steps"]==0
    for bad in ({"bogus":1},{"dt_s":1},{"density_kg_m3":-1},{"release_time_s":.5001},{"force_x_n":float("nan")}):
        try:run_experiment(bad,library)
        except ValueError:pass
        else:raise AssertionError(f"admitted invalid {bad}")
    native=ctypes.CDLL(str(Path(library).resolve()))
    native.banjo_mechanism_step.argtypes=[ctypes.POINTER(ctypes.c_double)]*4
    p=(ctypes.c_double*10)(1,1,1,1,9.81,0,0,0,1,1)
    state=(ctypes.c_double*8)(0,0,0,0,1,0,0,0)
    out=(ctypes.c_double*8)(*([123.]*8));receipt=(ctypes.c_double*16)(*([123.]*16))
    assert native.banjo_mechanism_step(p,state,out,receipt)!=0
    assert list(out)==[123.]*8 and list(receipt)==[123.]*16
    p[9]=1/480
    assert native.banjo_mechanism_step(p,state,out,receipt)==-9 # Direct ABI inconsistent inertia refuses.
    assert list(out)==[123.]*8 and list(receipt)==[123.]*16
    result={"materials":evidence,"common_time_refinement_errors_rad":errors,"small_angle_error_rad":abs(small["final_state"][1]-expected),
            "native_sha256":run["native_sha256"],"source_sha256":run["source_sha256"],
            "environment":{"platform":platform.platform(),"python":platform.python_version()},
            "conditions":{"length_m":1,"width_m":.12,"thickness_m":.05,"gravity_m_s2":9.81,"initial_angle_deg":35,"dt_s":1/480,"duration_s":2}}
    if evidence_path:
        dest=Path(evidence_path);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))
    print("Mechanism reference analytical, material, work, sleep/wake and refusal checks passed")

if __name__=="__main__":main(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None)
