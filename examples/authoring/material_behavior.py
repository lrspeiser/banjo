"""Strict, name-independent material behavior declarations.

This module describes the parameters accepted by Banjo's small-strain
reference laws.  It does not run a constitutive update or imply support for
contact, dents, fracture, finite strain, or rate-dependent behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, Mapping, Sequence


SUPPORTED_LAWS = frozenset({
    "isotropic_elastic", "orthotropic_elastic", "j2_plastic",
})
SUPPORTED_BACKEND_CAPABILITIES = frozenset({"small_strain_reference"})
UNSUPPORTED_BACKEND_CAPABILITIES = frozenset({
    "dynamic_contact", "dents", "fracture", "finite_strain", "viscoelasticity",
})


class UnsupportedBehaviorError(ValueError):
    """Raised when a declaration requests behavior this backend does not provide."""


@dataclass(frozen=True)
class CapabilityAssessment:
    supported: bool
    backend: str
    supported_capabilities: tuple[str, ...]
    unsupported_capabilities: tuple[str, ...]
    limitations: tuple[str, ...]

    def require_supported(self) -> None:
        if not self.supported:
            names = ", ".join(self.unsupported_capabilities)
            raise UnsupportedBehaviorError(f"unsupported material behavior: {names}")


@dataclass(frozen=True)
class MaterialBehavior:
    """One SI density and one validated small-strain mechanical law.

    ``material_id`` and ``name`` are display/authoring identity.  They are
    deliberately excluded from ``physical_hash`` so renaming or re-keying a
    physically identical material does not change its physics identity.
    """

    material_id: str
    name: str
    density_kg_m3: float
    mechanical_law: str
    parameters: Mapping[str, Any]
    required_capabilities: tuple[str, ...] = ("small_strain_reference",)

    def __post_init__(self) -> None:
        _validate_text(self.material_id, "material_id")
        _validate_text(self.name, "name")
        density = _positive(self.density_kg_m3, "density_kg_m3")
        if density > 1e9:
            raise ValueError("density_kg_m3 must be at most 1e9")
        if self.mechanical_law not in SUPPORTED_LAWS:
            raise UnsupportedBehaviorError(
                f"unsupported mechanical law: {self.mechanical_law!r}")
        params = _validate_parameters(self.mechanical_law, self.parameters)
        capabilities = _string_tuple(self.required_capabilities, "required_capabilities")
        if capabilities != ("small_strain_reference",):
            assessment = assess_backend_capability(capabilities)
            assessment.require_supported()
            raise UnsupportedBehaviorError(
                "required_capabilities must be exactly ('small_strain_reference',)")
        assessment = assess_backend_capability(capabilities)
        assessment.require_supported()
        object.__setattr__(self, "density_kg_m3", density)
        object.__setattr__(self, "parameters", MappingProxyType(params))
        object.__setattr__(self, "required_capabilities", capabilities)

    @property
    def physical_hash(self) -> str:
        payload = {
            "density_kg_m3": self.density_kg_m3,
            "mechanical_law": self.mechanical_law,
            "parameters": dict(self.parameters),
            "units": "SI",
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "name": self.name,
            "units": "SI",
            "density_kg_m3": self.density_kg_m3,
            "mechanical_law": self.mechanical_law,
            "parameters": _mutable_parameters(self.parameters),
            "required_capabilities": list(self.required_capabilities),
            "physical_hash": self.physical_hash,
        }


def assess_backend_capability(
    required_capabilities: Sequence[str],
) -> CapabilityAssessment:
    """Report support without substituting a different material law."""
    requested = _string_tuple(required_capabilities, "required_capabilities")
    unsupported = tuple(sorted(set(requested) - SUPPORTED_BACKEND_CAPABILITIES))
    limitations = (
        "quasistatic small-strain material-point reference only",
        "dynamic contact and dent geometry are not integrated",
        "fracture, finite-strain kinematics, and viscoelasticity are unsupported",
    )
    return CapabilityAssessment(
        supported=not unsupported,
        backend="banjo_small_strain_reference",
        supported_capabilities=tuple(
            sorted(set(requested) & SUPPORTED_BACKEND_CAPABILITIES)),
        unsupported_capabilities=unsupported,
        limitations=limitations,
    )


def _validate_parameters(law: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("parameters must be a mapping")
    validators = {
        "isotropic_elastic": _isotropic_parameters,
        "orthotropic_elastic": _orthotropic_parameters,
        "j2_plastic": _j2_parameters,
    }
    return validators[law](dict(raw))


def _exact_keys(values: Mapping[str, Any], expected: set[str], law: str) -> None:
    if set(values) != expected:
        missing = sorted(expected - set(values))
        extra = sorted(set(values) - expected)
        raise ValueError(f"{law} parameters mismatch; missing={missing}, extra={extra}")


def _isotropic_parameters(values: dict[str, Any]) -> dict[str, float]:
    keys = {"young_modulus_pa", "poisson_ratio", "maximum_total_strain_norm"}
    _exact_keys(values, keys, "isotropic_elastic")
    return {
        "young_modulus_pa": _positive(values["young_modulus_pa"], "young_modulus_pa"),
        "poisson_ratio": _isotropic_poisson(values["poisson_ratio"]),
        "maximum_total_strain_norm": _positive(
            values["maximum_total_strain_norm"], "maximum_total_strain_norm"),
    }


def _j2_parameters(values: dict[str, Any]) -> dict[str, float]:
    keys = {
        "young_modulus_pa", "poisson_ratio", "initial_yield_stress_pa",
        "isotropic_hardening_modulus_pa", "maximum_total_strain_norm",
    }
    _exact_keys(values, keys, "j2_plastic")
    result = _isotropic_parameters({key: values[key] for key in (
        "young_modulus_pa", "poisson_ratio", "maximum_total_strain_norm")})
    result["initial_yield_stress_pa"] = _positive(
        values["initial_yield_stress_pa"], "initial_yield_stress_pa")
    result["isotropic_hardening_modulus_pa"] = _nonnegative(
        values["isotropic_hardening_modulus_pa"], "isotropic_hardening_modulus_pa")
    return result


def _orthotropic_parameters(values: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "young_modulus_pa", "poisson_xy_yz_zx", "shear_xy_yz_zx_pa",
        "maximum_total_strain_norm",
    }
    _exact_keys(values, keys, "orthotropic_elastic")
    young = _triple(values["young_modulus_pa"], "young_modulus_pa", _positive)
    poisson = _triple(values["poisson_xy_yz_zx"], "poisson_xy_yz_zx", _finite)
    shear = _triple(values["shear_xy_yz_zx_pa"], "shear_xy_yz_zx_pa", _positive)
    # This matches SmallStrainLaw's reciprocal, symmetric normal compliance.
    compliance = (
        (1 / young[0], -poisson[0] / young[0], -poisson[2] / young[2]),
        (-poisson[0] / young[0], 1 / young[1], -poisson[1] / young[1]),
        (-poisson[2] / young[2], -poisson[1] / young[1], 1 / young[2]),
    )
    minor2 = compliance[0][0] * compliance[1][1] - compliance[0][1] ** 2
    determinant = (
        compliance[0][0] * (compliance[1][1] * compliance[2][2] - compliance[1][2] ** 2)
        - compliance[0][1] * (compliance[0][1] * compliance[2][2] - compliance[1][2] * compliance[0][2])
        + compliance[0][2] * (compliance[0][1] * compliance[1][2] - compliance[1][1] * compliance[0][2])
    )
    if minor2 <= 0 or determinant <= 0 or not math.isfinite(determinant):
        raise ValueError("orthotropic normal compliance must be positive definite")
    return {
        "young_modulus_pa": young,
        "poisson_xy_yz_zx": poisson,
        "shear_xy_yz_zx_pa": shear,
        "maximum_total_strain_norm": _positive(
            values["maximum_total_strain_norm"], "maximum_total_strain_norm"),
    }


def _triple(value: Any, field: str, validator: Any) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise ValueError(f"{field} must contain exactly three values")
    return tuple(validator(item, f"{field}[{index}]") for index, item in enumerate(value))


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _positive(value: Any, field: str) -> float:
    number = _finite(value, field)
    if number <= 0:
        raise ValueError(f"{field} must be positive")
    return number


def _nonnegative(value: Any, field: str) -> float:
    number = _finite(value, field)
    if number < 0:
        raise ValueError(f"{field} must be nonnegative")
    return number


def _isotropic_poisson(value: Any) -> float:
    number = _finite(value, "poisson_ratio")
    if not -1 < number < 0.5:
        raise ValueError("poisson_ratio must be greater than -1 and less than 0.5")
    return number


def _validate_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _string_tuple(values: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{field} must be a sequence of strings")
    result = tuple(values)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{field} must contain non-empty strings")
    if len(set(result)) != len(result):
        raise ValueError(f"{field} must not contain duplicates")
    return result


def _mutable_parameters(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-shaped copy without exposing immutable stored tuples."""
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in values.items()
    }
