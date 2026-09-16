"""Generic physical product graph shared by Workshop, imports and runtime compilation.

A ProductGraph describes *what a product physically is*, not what product name it
has.  A cart, kettle, guillotine, merry-go-round or future complex machine uses
the same primitives: components, interfaces, relationships, energy, controls,
contents, tests and evidence.

Geometry remains owned by its authoring source.  This graph carries enough
semantic geometry and physics intent for deterministic mating, engineering tests
and a later reduced runtime PhysicsContract without asking an LLM to invent XYZ
coordinates or product-specific rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Iterable

PRODUCT_SCHEMA = "banjo.product-graph.v1"

RELATION_KINDS = {
    "physical-contact", "supports", "fixed", "hinge", "slider", "bearing",
    "rope", "pulley", "drum", "spring", "gear", "rack", "contains",
    "thermal-contact", "electrical", "control", "flow",
}


def _vec3(value: Iterable[Any] | None, name: str) -> tuple[float, float, float] | None:
    if value is None:
        return None
    out = tuple(float(v) for v in value)
    if len(out) != 3 or not all(isfinite(v) for v in out):
        raise ValueError(f"{name} must contain three finite numbers")
    return out  # type: ignore[return-value]


def _tags(values: Iterable[Any] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(sorted({str(v).strip() for v in values if str(v).strip()}))


@dataclass(frozen=True)
class ProductInterface:
    interface_id: str
    kind: str
    point_m: tuple[float, float, float] | None = None
    axis: tuple[float, float, float] | None = None
    normal: tuple[float, float, float] | None = None
    tags: tuple[str, ...] = ()
    properties: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "ProductInterface":
        if not self.interface_id or not self.kind:
            raise ValueError("a product interface needs an id and kind")
        _vec3(self.point_m, f"{self.interface_id}.point_m")
        _vec3(self.axis, f"{self.interface_id}.axis")
        _vec3(self.normal, f"{self.interface_id}.normal")
        return self

    def described(self) -> dict[str, Any]:
        self.validate()
        out: dict[str, Any] = {"id": self.interface_id, "kind": self.kind}
        if self.point_m is not None: out["point_m"] = list(self.point_m)
        if self.axis is not None: out["axis"] = list(self.axis)
        if self.normal is not None: out["normal"] = list(self.normal)
        if self.tags: out["tags"] = list(self.tags)
        if self.properties: out["properties"] = dict(self.properties)
        return out


@dataclass(frozen=True)
class ProductComponent:
    component_id: str
    role: str
    family: str | None = None
    material: str | None = None
    geometry: dict[str, Any] = field(default_factory=dict)
    interfaces: tuple[ProductInterface, ...] = ()
    physics_tags: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    properties: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "ProductComponent":
        if not self.component_id or not self.role:
            raise ValueError("a product component needs an id and role")
        ids = [port.interface_id for port in self.interfaces]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.component_id}: interface ids must be unique")
        for port in self.interfaces: port.validate()
        mass = self.geometry.get("mass_kg")
        if mass is not None and (not isfinite(float(mass)) or float(mass) < 0):
            raise ValueError(f"{self.component_id}: mass_kg must be finite and nonnegative")
        return self

    def described(self) -> dict[str, Any]:
        self.validate()
        out: dict[str, Any] = {
            "id": self.component_id,
            "role": self.role,
            "geometry": dict(self.geometry),
            "interfaces": [port.described() for port in self.interfaces],
            "physics_tags": list(self.physics_tags),
            "capabilities": list(self.capabilities),
        }
        if self.family: out["family"] = self.family
        if self.material: out["material"] = self.material
        if self.properties: out["properties"] = dict(self.properties)
        return out


@dataclass(frozen=True)
class ProductRelationship:
    relationship_id: str
    kind: str
    a: str
    b: str
    a_interface: str | None = None
    b_interface: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    derived: bool = False

    def described(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.relationship_id, "kind": self.kind,
                               "a": self.a, "b": self.b, "derived": self.derived}
        if self.a_interface: out["a_interface"] = self.a_interface
        if self.b_interface: out["b_interface"] = self.b_interface
        if self.properties: out["properties"] = dict(self.properties)
        return out


@dataclass
class ProductGraph:
    product_id: str
    purpose: str = "physical product"
    components: list[ProductComponent] = field(default_factory=list)
    relationships: list[ProductRelationship] = field(default_factory=list)
    energy: list[dict[str, Any]] = field(default_factory=list)
    controls: list[dict[str, Any]] = field(default_factory=list)
    contents: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    manufacturing: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def component(self, component_id: str) -> ProductComponent:
        for component in self.components:
            if component.component_id == component_id:
                return component
        raise KeyError(f"there is no component {component_id!r}")

    def validate(self) -> "ProductGraph":
        if not self.product_id:
            raise ValueError("product_id is required")
        ids = [component.component_id for component in self.components]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("a product needs uniquely named components")
        known = set(ids)
        interface_ids = {component.component_id: {p.interface_id for p in component.interfaces}
                         for component in self.components}
        for component in self.components: component.validate()
        relation_ids = [relation.relationship_id for relation in self.relationships]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("relationship ids must be unique")
        for relation in self.relationships:
            if relation.kind not in RELATION_KINDS:
                raise ValueError(f"unknown relationship kind {relation.kind!r}")
            if relation.a not in known or relation.b not in known:
                raise ValueError(f"{relation.relationship_id}: relationship endpoints must exist")
            if relation.a == relation.b:
                raise ValueError(f"{relation.relationship_id}: a relationship needs two components")
            if relation.a_interface and relation.a_interface not in interface_ids[relation.a]:
                raise ValueError(f"{relation.relationship_id}: missing interface {relation.a}.{relation.a_interface}")
            if relation.b_interface and relation.b_interface not in interface_ids[relation.b]:
                raise ValueError(f"{relation.relationship_id}: missing interface {relation.b}.{relation.b_interface}")
        return self

    def described(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": PRODUCT_SCHEMA,
            "product_id": self.product_id,
            "purpose": self.purpose,
            "components": [component.described() for component in self.components],
            "relationships": [relation.described() for relation in self.relationships],
            "energy": list(self.energy),
            "controls": list(self.controls),
            "contents": list(self.contents),
            "tests": list(self.tests),
            "evidence": list(self.evidence),
            "manufacturing": list(self.manufacturing),
            "metadata": dict(self.metadata),
            "physics_tags": physics_tags(self),
        }


def interface(interface_id: str, kind: str, *, point_m: Iterable[Any] | None = None,
              axis: Iterable[Any] | None = None, normal: Iterable[Any] | None = None,
              tags: Iterable[Any] = (), properties: dict[str, Any] | None = None) -> ProductInterface:
    return ProductInterface(interface_id, kind, _vec3(point_m, "point_m"),
                            _vec3(axis, "axis"), _vec3(normal, "normal"),
                            _tags(tags), dict(properties or {})).validate()


def component(component_id: str, role: str, *, family: str | None = None,
              material: str | None = None, geometry: dict[str, Any] | None = None,
              interfaces: Iterable[ProductInterface] = (), physics_tags: Iterable[Any] = (),
              capabilities: Iterable[Any] = (), properties: dict[str, Any] | None = None) -> ProductComponent:
    return ProductComponent(component_id, role, family, material, dict(geometry or {}),
                            tuple(interfaces), _tags(physics_tags), _tags(capabilities),
                            dict(properties or {})).validate()


def relationship(relationship_id: str, kind: str, a: str, b: str, *,
                 a_interface: str | None = None, b_interface: str | None = None,
                 properties: dict[str, Any] | None = None, derived: bool = False) -> ProductRelationship:
    return ProductRelationship(relationship_id, kind, a, b, a_interface, b_interface,
                               dict(properties or {}), bool(derived))


def physics_tags(graph: ProductGraph) -> dict[str, list[str]]:
    """Indexable semantics for a personal/team product library."""
    physics = {tag for component in graph.components for tag in component.physics_tags}
    capabilities = {tag for component in graph.components for tag in component.capabilities}
    interfaces = {port.kind for component in graph.components for port in component.interfaces}
    roles = {component.role for component in graph.components}
    families = {component.family for component in graph.components if component.family}
    relationships = {relation.kind for relation in graph.relationships}
    tests = {str(test.get("kind") or test.get("test")) for test in graph.tests
             if test.get("kind") or test.get("test")}
    return {
        "physics": sorted(physics), "capability": sorted(capabilities),
        "interface": sorted(interfaces), "relationship": sorted(relationships),
        "role": sorted(roles), "family": sorted(families), "test": sorted(tests),
    }
