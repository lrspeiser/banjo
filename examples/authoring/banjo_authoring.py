"""Pure initial-state authoring helpers and a stateless Banjo CLI client.

The engine owns validation and physics. Every validate/run/skin call creates a
fresh world; use the C++ PlatformWorld API for a persistent live simulation.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
from typing import Any

CATALOG = Path(__file__).with_name("presets.json")
OBJECT_FIELDS = {
    "id", "name", "material", "shape", "representation", "dimensions_m",
    "resolution", "position_m", "orientation_wxyz", "velocity_m_s",
    "spin_rad_s", "pin_boundary", "grain_wxyz",
}


def catalog() -> dict[str, Any]:
    """Return an independent copy of the experimental starter catalog."""
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def make_material(preset: str, **overrides: Any) -> dict[str, Any]:
    """Copy a property preset. Supply provenance for newly measured constants."""
    materials = {m["id"]: m for m in catalog()["materials"]}
    result = deepcopy(materials[preset])
    unknown = overrides.keys() - result.keys()
    if unknown:
        raise ValueError(f"Unknown material fields: {sorted(unknown)}")
    result.update(deepcopy(overrides))
    return result


def make_object(preset: str, object_id: int, **overrides: Any) -> dict[str, Any]:
    """Create an object declaration, not a live engine body.

    Override supported JSON fields using SI values. IDs must be unique within
    the package. To create another shape, construct a declaration directly.
    """
    if type(object_id) is not int or not 1 <= object_id <= 1_000_000:
        raise ValueError("object_id must be an integer in 1..1000000")
    if "id" in overrides or overrides.keys() - OBJECT_FIELDS:
        raise ValueError("Use object_id for identity and only supported object fields")
    result = deepcopy(catalog()["object_presets"][preset])
    result["id"] = object_id
    result.update(deepcopy(overrides))
    return result


def make_package(
    objects: list[dict[str, Any]], *,
    materials: list[dict[str, Any]] | None = None,
    name: str = "Authored material scene",
    fixed_dt_s: float = 1 / 480,
    max_steps_per_call: int = 240,
    solver_iterations: int = 24,
    temporal_policy: str = "diagnose",
    gravity_m_s2: tuple[float, float, float] = (0, -9.81, 0),
    ground: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a v2 initial-state package. No ground is added implicitly."""
    materials = deepcopy(catalog()["materials"] if materials is None else materials)
    capabilities = {o["shape"] for o in objects} | {"gravity", "contact", "render-instances"}
    if ground is not None:
        capabilities.add("finite-ground")
    if any(o["representation"] == "network" for o in objects):
        capabilities |= {"cell-deformation", "cohesive-damage", "directional-lattice", "blocky-cell-skins"}
    if any(m.get("yield_strength_pa", 0) > 0 for m in materials):
        capabilities.add("axial-plasticity")
    return {
        "package_version": 2, "physics_abi": "banjo-network-2",
        "backend": "material-network-v2", "units": "SI", "name": name,
        "required_capabilities": sorted(capabilities),
        "fixed_dt_s": fixed_dt_s, "max_steps_per_call": max_steps_per_call,
        "solver_iterations": solver_iterations, "temporal_policy": temporal_policy,
        "gravity_m_s2": list(gravity_m_s2), "ground": deepcopy(ground),
        "materials": materials, "objects": deepcopy(objects),
    }


def write_package(package: dict[str, Any], path: str | Path) -> Path:
    """Write a new JSON file; fail if the target already exists or values are NaN."""
    text = json.dumps(package, indent=2, allow_nan=False) + "\n"
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as output:
        output.write(text)
    return target


class EngineError(RuntimeError):
    def __init__(self, returncode: int, report: dict[str, Any]):
        self.returncode = returncode
        self.report = report
        super().__init__(report.get("error") or report.get("fault") or f"Engine exited {returncode}")


class EngineCLI:
    """One process and one new simulation per operation; no HTTP or session state."""
    def __init__(self, executable: str | Path, *, timeout_s: float = 120):
        self.executable = str(Path(executable).resolve())
        self.timeout_s = timeout_s

    def _call(self, *args: object) -> dict[str, Any]:
        result = subprocess.run(
            [self.executable, *(str(a) for a in args)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=self.timeout_s, check=False,
        )
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Engine did not return JSON (exit {result.returncode})") from error
        if result.returncode != 0 or report.get("fault"):
            raise EngineError(result.returncode, report)
        return report

    def capabilities(self) -> dict[str, Any]:
        return self._call("--capabilities")

    def validate(self, package_path: str | Path) -> dict[str, Any]:
        """Construct and report initial state without stepping; not calibration."""
        return self._call("--validate", Path(package_path).resolve())

    def run(self, package_path: str | Path, steps: int) -> dict[str, Any]:
        """Load initial state afresh, advance 1..24000 fixed steps, return report."""
        self._check_steps(steps, minimum=1)
        return self._call("--run", Path(package_path).resolve(), steps)

    def export_skin(self, package_path: str | Path, steps: int, output_path: str | Path) -> dict[str, Any]:
        """Load afresh and export derived triangles to a new file, not a savegame."""
        self._check_steps(steps, minimum=0)
        return self._call("--skin", Path(package_path).resolve(), steps, Path(output_path).resolve())

    @staticmethod
    def _check_steps(steps: int, minimum: int) -> None:
        if type(steps) is not int or not minimum <= steps <= 24000:
            raise ValueError(f"steps must be an integer in {minimum}..24000")
