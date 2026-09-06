"""Execute property-based strain paths in the native reference backend."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import time
from material_behavior import MaterialBehavior

def evaluate_material_path(executable: str | Path, material: MaterialBehavior, strains: list) -> dict:
    """Run absolute total-strain samples, with history retained within this path.

    Tensor order: xx, yy, zz, xy, yz, zx (physical shear). This API supplies no
    geometry, impact, fracture, finite strain or rubber memory.
    """
    if not isinstance(material,MaterialBehavior): raise ValueError("Expected validated MaterialBehavior")
    if not isinstance(strains,list) or not 1<=len(strains)<=256: raise ValueError("Expected 1..256 strain samples")
    payload=json.dumps({"material":material.to_dict(),"strains":strains},allow_nan=False,separators=(",",":"))
    if len(payload.encode())>262144: raise ValueError("Material path exceeds input budget")
    exe=Path(executable).resolve(strict=True)
    start=time.perf_counter()
    result=subprocess.run([str(exe)],input=payload,text=True,capture_output=True,timeout=15,check=False)
    if result.returncode: raise ValueError("Native material path rejected; check coefficients, strain validity and capabilities")
    data=json.loads(result.stdout)
    if data.get("schema")!="banjo.material-response.v1" or data.get("status")!="complete": raise ValueError("Invalid native response")
    data["execution"]={"material_physical_hash":material.physical_hash,"input_sha256":hashlib.sha256(payload.encode()).hexdigest(),"executable_sha256":hashlib.sha256(exe.read_bytes()).hexdigest(),"wall_s":time.perf_counter()-start}
    return data
