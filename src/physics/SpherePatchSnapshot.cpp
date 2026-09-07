#include "physics/SpherePatchSnapshot.hpp"

#include "physics/SweptSphereTriangle.hpp"

#include <cmath>
#include <stdexcept>
#include <utility>

namespace banjo {
namespace {

void require(bool condition, const char *message) {
    if (!condition) throw std::invalid_argument(message);
}

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

bool same(Vec3 a, Vec3 b) {
    return a.x == b.x && a.y == b.y && a.z == b.z;
}

bool same(const SmallStrainLaw &a, const SmallStrainLaw &b) {
    return a.kind == b.kind && a.j2.family == b.j2.family &&
           a.j2.young_modulus_pa == b.j2.young_modulus_pa &&
           a.j2.poisson_ratio == b.j2.poisson_ratio &&
           a.j2.initial_yield_stress_pa == b.j2.initial_yield_stress_pa &&
           a.j2.isotropic_hardening_modulus_pa == b.j2.isotropic_hardening_modulus_pa &&
           a.j2.maximum_total_strain_norm == b.j2.maximum_total_strain_norm &&
           a.young_modulus_pa == b.young_modulus_pa &&
           a.poisson_xy_yz_zx == b.poisson_xy_yz_zx &&
           a.shear_xy_yz_zx_pa == b.shear_xy_yz_zx_pa &&
           a.maximum_total_strain_norm == b.maximum_total_strain_norm;
}

bool same(const PatchDefinition &a, const PatchDefinition &b) {
    if (a.reference_positions_m.size() != b.reference_positions_m.size() ||
        a.elements.size() != b.elements.size() || a.materials.size() != b.materials.size() ||
        a.fixed_components != b.fixed_components)
        return false;
    for (std::size_t i = 0; i < a.reference_positions_m.size(); ++i)
        if (!same(a.reference_positions_m[i], b.reference_positions_m[i])) return false;
    for (std::size_t i = 0; i < a.elements.size(); ++i)
        if (a.elements[i].nodes != b.elements[i].nodes ||
            a.elements[i].material != b.elements[i].material)
            return false;
    for (std::size_t i = 0; i < a.materials.size(); ++i)
        if (a.materials[i].density_kg_m3 != b.materials[i].density_kg_m3 ||
            !same(a.materials[i].law, b.materials[i].law))
            return false;
    return true;
}

bool same(const DynamicPatchOptions &a, const DynamicPatchOptions &b) {
    return a.stability_safety_factor == b.stability_safety_factor &&
           a.maximum_displacement_gradient_norm == b.maximum_displacement_gradient_norm &&
           a.maximum_time_step_s == b.maximum_time_step_s && a.integrator == b.integrator;
}

bool same(const PatchContactOptions &a, const PatchContactOptions &b) {
    return a.friction_coefficient == b.friction_coefficient &&
           a.contact_margin_m == b.contact_margin_m &&
           a.maximum_penetration_m == b.maximum_penetration_m &&
           a.maximum_contact_events == b.maximum_contact_events &&
           a.maximum_geometry_queries == b.maximum_geometry_queries &&
           a.maximum_geometry_iterations == b.maximum_geometry_iterations;
}

bool centerInside(Vec3 point, const std::vector<Vec3> &positions,
                  const PatchDefinition &definition) {
    for (const auto &tet : definition.elements) {
        const Vec3 a = positions[tet.nodes[0]];
        const Vec3 b = positions[tet.nodes[1]] - a;
        const Vec3 c = positions[tet.nodes[2]] - a;
        const Vec3 d = positions[tet.nodes[3]] - a;
        const Vec3 q = point - a;
        const double determinant = dot(b, cross(c, d));
        require(std::isfinite(determinant) && determinant > 0,
                "Snapshot has invalid deformed tetrahedron");
        const double u = dot(q, cross(c, d)) / determinant;
        const double v = dot(b, cross(q, d)) / determinant;
        const double w = dot(b, cross(c, q)) / determinant;
        if (u >= 0 && v >= 0 && w >= 0 && u + v + w <= 1) return true;
    }
    return false;
}

} // namespace

SpherePatchSnapshot SpherePatchWorld::snapshot() const {
    SpherePatchSnapshot result;
    result.definition = patch_.patch().definition();
    result.dynamics = patch_.options_;
    result.contact = contact_;
    result.patch = patch_.patch().state();
    result.dynamic = patch_.state_;
    result.accepted_evaluation = *patch_.accepted_evaluation_;
    result.sphere = sphere_;
    return result;
}

void SpherePatchWorld::restoreSnapshot(const SpherePatchSnapshot &snapshot) {
    require(snapshot.version == 1, "Unsupported sphere-patch snapshot version");
    require(same(snapshot.definition, patch_.patch().definition()),
            "Sphere-patch snapshot definition is incompatible");
    require(same(snapshot.dynamics, patch_.options_),
            "Sphere-patch snapshot dynamics are incompatible");
    require(same(snapshot.contact, contact_),
            "Sphere-patch snapshot contact options are incompatible");
    require(finite(snapshot.sphere.center_m) && length(snapshot.sphere.center_m) <= 1000 &&
                finite(snapshot.sphere.velocity_m_s) &&
                length(snapshot.sphere.velocity_m_s) <= 1.e6 &&
                finite(snapshot.sphere.spin_rad_s) &&
                length(snapshot.sphere.spin_rad_s) <= 1.e6 &&
                std::isfinite(snapshot.sphere.radius_m) &&
                snapshot.sphere.radius_m == sphere_.radius_m &&
                std::isfinite(snapshot.sphere.mass_kg) &&
                snapshot.sphere.mass_kg == sphere_.mass_kg,
            "Sphere-patch snapshot sphere is invalid or incompatible");

    auto prepared = patch_.prepareRestore(snapshot.patch, snapshot.dynamic,
                                          snapshot.accepted_evaluation);
    std::vector<Vec3> positions = snapshot.definition.reference_positions_m;
    for (std::size_t i = 0; i < positions.size(); ++i)
        positions[i] += snapshot.patch.displacements_m[i];
    require(!centerInside(snapshot.sphere.center_m, positions, snapshot.definition),
            "Snapshot sphere center lies inside deformed patch");
    for (const auto &face : patch_.patch().boundaryTriangles()) {
        const auto closest = closestPointOnTriangle(
            snapshot.sphere.center_m,
            {positions[face[0]], positions[face[1]], positions[face[2]]});
        require(closest.resolved &&
                    closest.distance_m >= snapshot.sphere.radius_m -
                                                  contact_.maximum_penetration_m,
                "Snapshot sphere overlaps deformed patch beyond tolerance");
    }
    patch_.commitRestore(std::move(prepared));
    sphere_ = snapshot.sphere;
}

} // namespace banjo
