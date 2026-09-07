#include "physics/CohesiveSphereWorld.hpp"
#include "physics/SphereSurfaceContactStep.hpp"
#include "physics/SweptSphereTriangle.hpp"
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>
namespace banjo {
namespace {
void require(bool valid, const char *message) {
    if (!valid)
        throw std::invalid_argument(message);
}
bool finite(Vec3 v) {
    return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
}
double inertia(const PatchSphere &s) {
    return .4 * s.mass_kg * s.radius_m * s.radius_m;
}
double kinetic(const PatchSphere &s) {
    return .5 * s.mass_kg * lengthSquared(s.velocity_m_s) +
           .5 * inertia(s) * lengthSquared(s.spin_rad_s);
}
bool centerInside(Vec3 p, const std::vector<Vec3> &x, const PatchDefinition &d) {
    for (const auto &tet : d.elements) {
        const auto a = x[tet.nodes[0]], b = x[tet.nodes[1]] - a, c = x[tet.nodes[2]] - a,
                   e = x[tet.nodes[3]] - a, q = p - a;
        const double det = dot(b, cross(c, e));
        require(det > 0 && std::isfinite(det), "Invalid deformed tetrahedron");
        const double u = dot(q, cross(c, e)) / det, v = dot(b, cross(q, e)) / det,
                     w = dot(b, cross(c, q)) / det;
        if (u >= 0 && v >= 0 && w >= 0 && u + v + w <= 1)
            return true;
    }
    return false;
}
} // namespace
namespace {
std::vector<std::array<unsigned, 3>> surfaceFaces(const FractureTopology &topology,
                                                  const FractureSeparation &separation) {
    std::vector<std::array<unsigned, 3>> faces;
    faces.reserve(topology.original_exterior_faces.size() + separation.newly_exposed_faces.size());
    for (const auto &face : topology.original_exterior_faces)
        faces.push_back(face.local_nodes);
    for (const auto &face : separation.newly_exposed_faces)
        faces.push_back(face.local_nodes);
    return faces;
}
} // namespace
CohesiveSphereWorld::CohesiveSphereWorld(PatchDefinition definition, PatchSphere sphere,
                                         std::vector<CohesiveFacetLaw> laws,
                                         CohesiveDynamicPatchOptions dynamics,
                                         PatchContactOptions contact)
    : patch_(std::move(definition), std::move(laws), dynamics), sphere_(sphere), contact_(contact),
      energy_limit_(dynamics.maximum_absolute_energy_residual_j) {
    require(finite(sphere.center_m) && length(sphere.center_m) <= 1000 &&
                finite(sphere.velocity_m_s) && length(sphere.velocity_m_s) <= 1.e6 &&
                finite(sphere.spin_rad_s) && length(sphere.spin_rad_s) <= 1.e6,
            "Invalid sphere state");
    require(std::isfinite(sphere.radius_m) && sphere.radius_m >= 1.e-5 && sphere.radius_m <= 10 &&
                std::isfinite(sphere.mass_kg) && sphere.mass_kg > 0 && sphere.mass_kg <= 1.e9,
            "Invalid sphere mass or radius");
    require(std::isfinite(contact.friction_coefficient) && contact.friction_coefficient >= 0 &&
                contact.friction_coefficient <= 2,
            "Invalid contact friction");
    require(std::isfinite(contact.contact_margin_m) && contact.contact_margin_m > 0 &&
                contact.contact_margin_m <= 1.e-3 && std::isfinite(contact.maximum_penetration_m) &&
                contact.maximum_penetration_m >= contact.contact_margin_m &&
                contact.maximum_penetration_m <= sphere.radius_m * .01,
            "Invalid contact geometric tolerance");
    require(contact.maximum_contact_events >= 1 && contact.maximum_contact_events <= 4096 &&
                contact.maximum_geometry_queries >= 1 &&
                contact.maximum_geometry_queries <= 1000000 &&
                contact.maximum_geometry_iterations >= 1 &&
                contact.maximum_geometry_iterations <= 10000000,
            "Invalid contact work budget");
    const auto x = patch_.positionsM();
    require(!centerInside(sphere.center_m, x, patch_.topology().duplicated_definition),
            "Sphere center starts inside material");
    for (const auto &face : surfaceFaces(patch_.topology(), patch_.state().separation)) {
        const auto closest =
            closestPointOnTriangle(sphere.center_m, {x[face[0]], x[face[1]], x[face[2]]});
        require(closest.resolved &&
                    closest.distance_m >= sphere.radius_m - contact.maximum_penetration_m,
                "Sphere starts with unresolved overlap");
    }
}
CohesiveSphereReport CohesiveSphereWorld::step(double dt, const std::vector<Vec3> &nodal_forces,
                                               Vec3 material_gravity, Vec3 sphere_force,
                                               Vec3 sphere_gravity) {
    CohesiveSphereReport result;
    auto &out = result.contact;
    out.minimum_gap_m = std::numeric_limits<double>::infinity();
    try {
        require(std::isfinite(dt) && dt > 0 && dt <= patch_.stableTimeStepLimitS(),
                "Coupled cohesive step exceeds material stability limit");
        require(finite(sphere_force) && length(sphere_force) <= 1e12 && finite(sphere_gravity) &&
                    length(sphere_gravity) <= 1e6,
                "Invalid cohesive sphere force");
        const auto before = patch_.report();
        const auto x = patch_.positionsM();
        const auto &d = patch_.topology().duplicated_definition;
        const auto &mass = patch_.nodalMassesKg();
        auto faces = surfaceFaces(patch_.topology(), patch_.state().separation);
        auto sphere = sphere_;
        const Vec3 external = sphere_force + sphere.mass_kg * sphere_gravity;
        sphere.velocity_m_s += .5 * dt * external / sphere.mass_kg;
        require(finite(sphere.velocity_m_s) && length(sphere.velocity_m_s) <= 1e6,
                "Cohesive sphere kicked velocity exceeds validity bound");
        SphereSurfaceContactStep contact_step(d, mass, faces, x, patch_.state().velocities_m_s,
                                              sphere_, sphere, dt, external, true, contact_, out);
        auto drift = [&](std::vector<Vec3> &velocity, std::vector<Vec3> &increments) {
            contact_step.exchange(velocity, increments);
        };
        auto final_velocity = [&](std::vector<Vec3> &velocity,
                                  const CohesiveDynamicPatchState &candidate) {
            faces = surfaceFaces(patch_.topology(), candidate.separation);
            contact_step.finalVelocity(velocity, candidate.displacements_m);
        };
        auto verify = [&](const CohesiveDynamicPatchState &candidate,
                          const CohesiveDynamicPatchReport &material) {
            require(finite(sphere.center_m) && length(sphere.center_m) <= 1000 &&
                        finite(sphere.velocity_m_s) && length(sphere.velocity_m_s) <= 1e6 &&
                        finite(sphere.spin_rad_s) && length(sphere.spin_rad_s) <= 1e6,
                    "Cohesive sphere state exceeds validity bounds");
            auto positions = d.reference_positions_m;
            for (std::size_t i = 0; i < positions.size(); ++i)
                positions[i] += candidate.displacements_m[i];
            if (patch_.kinematics() == CohesiveKinematics::Corotated &&
                candidate.separation.components.size() > 1) {
                require(out.geometry_queries < contact_.maximum_geometry_queries &&
                            out.geometry_iterations < contact_.maximum_geometry_iterations,
                        "Fragment overlap audit budget exhausted");
                const FractureOverlapLimits limits{contact_.maximum_penetration_m,
                    contact_.maximum_geometry_queries - out.geometry_queries,
                    contact_.maximum_geometry_iterations - out.geometry_iterations};
                std::vector<unsigned> owned_facets;
                for (unsigned id : material.closure_contact_facets) {
                    const auto &facet = patch_.topology().internal_facets.at(id);
                    if (candidate.separation.component_by_tetrahedron[facet.side_a.tetrahedron] !=
                        candidate.separation.component_by_tetrahedron[facet.side_b.tetrahedron])
                        owned_facets.push_back(id);
                }
                result.fragment_overlap = detectFractureOverlap(patch_.topology(), positions,
                    candidate.separation, limits, owned_facets);
                out.geometry_queries += result.fragment_overlap.tetrahedron_pairs;
                out.geometry_iterations += result.fragment_overlap.sat_axes;
                require(result.fragment_overlap.resolved, "Fragment overlap audit budget exhausted");
                require(!result.fragment_overlap.unowned_interpenetrating,
                        "Fragment contact required: disconnected material interpenetrates");
            }
            require(!centerInside(sphere.center_m, positions, d), "Sphere entered cohesive matter");
            for (const auto &face : faces) {
                require(out.geometry_queries < contact_.maximum_geometry_queries,
                        "Cohesive final geometry budget exhausted");
                ++out.geometry_queries;
                const auto closest = closestPointOnTriangle(
                    sphere.center_m, {positions[face[0]], positions[face[1]], positions[face[2]]});
                require(closest.resolved, "Unresolved exposed cohesive contact face");
                const double gap = closest.distance_m - sphere.radius_m;
                out.minimum_gap_m = std::min(out.minimum_gap_m, gap);
                require(gap >= -contact_.maximum_penetration_m,
                        "Cohesive contact penetration limit exceeded");
            }
            out.sphere_kinetic_energy_j = kinetic(sphere);
            out.external_work_j = material.external_work_increment_j +
                                  dot(external, sphere.center_m - sphere_.center_m);
            out.numerical_energy_balance_residual_j =
                kinetic(sphere) - kinetic(sphere_) + material.kinetic_energy_j -
                before.kinetic_energy_j + material.bulk_stored_energy_j -
                before.bulk_stored_energy_j + material.cohesive_stored_energy_j -
                before.cohesive_stored_energy_j + material.interface_contact_stored_energy_j -
                before.interface_contact_stored_energy_j + material.fracture_dissipation_j -
                before.fracture_dissipation_j + material.plastic_dissipation_j -
                before.plastic_dissipation_j + out.contact_dissipation_j - out.external_work_j;
            Vec3 patch_external{};
            for (std::size_t i = 0; i < mass.size(); ++i)
                patch_external += dt * (nodal_forces[i] + mass[i] * material_gravity);
            out.linear_momentum_balance_residual_kg_m_s =
                sphere.mass_kg * (sphere.velocity_m_s - sphere_.velocity_m_s) +
                material.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s - dt * external -
                patch_external - material.support_impulse_n_s - out.contact_support_impulse_n_s;
            require(std::isfinite(out.numerical_energy_balance_residual_j) &&
                        finite(out.linear_momentum_balance_residual_kg_m_s),
                    "Nonfinite cohesive contact ledger");
            require(std::abs(out.numerical_energy_balance_residual_j) <= energy_limit_,
                    "Cohesive sphere raw energy residual exceeds step budget");
        };
        result.material =
            patch_.stepImpl(dt, nodal_forces, material_gravity, drift, final_velocity, verify);
        if (!result.material.accepted) {
            result.error = result.material.error;
            out.error = result.error;
            return result;
        }
        sphere_ = sphere;
        result.accepted = true;
        out.accepted = true;
    } catch (const std::exception &e) {
        result.error = e.what();
        out.error = result.error;
    }
    return result;
}
} // namespace banjo
