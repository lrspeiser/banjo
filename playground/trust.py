"""Does the engine's answer to this experiment mean anything?

Two independent checks, both reported next to every computed case.

1. Temporal resolution. The engine already computes the largest timestep its own
   spring network can represent (`temporal_resolution.maximum_step_s`). The
   package format bounds `fixed_dt_s` to [1/4800, 1/240] s, which for a stiff
   material is orders of magnitude too coarse, so this ratio is the honest
   measure of how far outside its own validity a run sits. A boolean "resolved:
   false" hides that a run can be 3x or 3000x short.

2. The at-rest control. Take the authored scene, remove gravity, the ground and
   every striker, and zero every velocity and spin. The exact answer is that
   nothing moves and every energy stays at zero. Measured on 2026-09-06, the
   network does not deliver that: an unpinned glass panel at the finest
   admissible step breaks 2141 of its bonds and fracture-disabled iron reaches
   1.19e9 J and 1505% axial strain from a 0 J start, monotonically worse as the
   step is refined. See docs/convergence-study-checkpoint.md.

   So a control that breaks bonds or creates energy means the paired experiment
   is measuring that instability at least as much as it is measuring the impact.
   This is a contamination check, not a conservation proof: a clean control
   bounds the at-rest instability only, and says nothing about whether the
   loaded run conserves energy.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

# Energy below this is reported as zero: it is the residual of accumulating
# single-precision spring work over thousands of steps, not created energy.
NEGLIGIBLE_ENERGY_J = 1.0e-6


def resolution_verdict(package: dict[str, Any], report: dict[str, Any]) -> dict[str, Any] | None:
    """How far the authored step sits from the step the engine says it needs."""
    temporal = (report or {}).get("temporal_resolution") or {}
    used = (package or {}).get("fixed_dt_s")
    required = temporal.get("maximum_step_s")
    if not isinstance(used, (int, float)) or not isinstance(required, (int, float)) or required <= 0:
        return None
    verdict = {
        "used_dt_s": float(used),
        "required_dt_s": float(required),
        "shortfall": float(used) / float(required),
        "required_substeps": temporal.get("required_substeps"),
        "resolved": temporal.get("resolved"),
    }
    # 1/4800 s is the smallest step the package schema accepts, so this says
    # whether the experiment is reachable at all rather than merely unresolved.
    verdict["reachable_in_schema"] = float(required) >= 1.0 / 4800.0
    return verdict


def energy_verdict(report: dict[str, Any]) -> dict[str, Any]:
    """Energy the run reports against the energy it started with."""
    report = report or {}
    out: dict[str, Any] = {}
    for key in ("initial_energy_j", "mechanical_energy_j", "elastic_energy_j",
                "unseparated_energy_change_j", "energy_residual_j",
                "maximum_observed_axial_strain", "broken_links", "connected_components"):
        if isinstance(report.get(key), (int, float)):
            out[key] = report[key]
    initial = out.get("initial_energy_j")
    change = out.get("unseparated_energy_change_j")
    if isinstance(initial, (int, float)) and isinstance(change, (int, float)) and initial > NEGLIGIBLE_ENERGY_J:
        out["change_fraction_of_initial"] = abs(change) / initial
    return out


def at_rest_control_package(package: dict[str, Any]) -> dict[str, Any]:
    """The same scene with nothing left to drive it.

    Materials, mesh resolution, pinning, timestep and solver iterations are kept
    exactly as authored, because those are what the check is about. Gravity, the
    ground, every non-network object and every initial velocity and spin are
    removed, so the only remaining behaviour is the lattice acting on itself.
    """
    control = deepcopy(package)
    control["name"] = f"At-rest control: {package.get('name', 'experiment')}"
    control["gravity_m_s2"] = [0.0, 0.0, 0.0]
    control["ground"] = None
    kept = []
    for obj in control.get("objects", []):
        # A rigid striker cannot deform and has nothing to strike once it is
        # stationary, so drop it rather than leaving it resting in the scene.
        if obj.get("representation") != "network":
            continue
        obj["velocity_m_s"] = [0.0, 0.0, 0.0]
        obj["spin_rad_s"] = [0.0, 0.0, 0.0]
        kept.append(obj)
    control["objects"] = kept
    if not kept:
        raise ValueError("This case has no deformable object, so it has no at-rest control")
    return control


def control_verdict(report: dict[str, Any]) -> dict[str, Any]:
    """Read an at-rest control run. Anything non-zero here is manufactured."""
    energy = energy_verdict(report)
    broken = energy.get("broken_links") or 0
    elastic = abs(energy.get("elastic_energy_j") or 0.0)
    mechanical = abs(energy.get("mechanical_energy_j") or 0.0)
    strain = abs(energy.get("maximum_observed_axial_strain") or 0.0)
    created = max(elastic, mechanical)
    clean = broken == 0 and created <= NEGLIGIBLE_ENERGY_J
    if clean:
        summary = "Clean. The lattice stayed still and created no measurable energy, so this scene is not contaminated by the at-rest instability."
    elif broken:
        summary = (f"CONTAMINATED. With no gravity, no ground, no striker and zero initial velocity, "
                   f"the lattice broke {broken} of its own bonds and created {created:.4g} J. "
                   f"Bond breakage in the paired experiment is not attributable to the impact.")
    else:
        summary = (f"CONTAMINATED. With nothing acting on it the lattice created {created:.4g} J "
                   f"and reached {strain:.4g} axial strain from rest. No bonds broke, but the "
                   f"energy ledger of the paired experiment is not trustworthy.")
    return {"clean": clean, "broken_links": broken, "created_energy_j": created,
            "maximum_axial_strain": strain, "summary": summary, "metrics": energy}
