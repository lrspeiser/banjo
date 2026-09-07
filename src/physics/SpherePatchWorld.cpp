#include "physics/SpherePatchWorld.hpp"
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
SpherePatchWorld::SpherePatchWorld(PatchDefinition definition, PatchSphere sphere,
                                   DynamicPatchOptions dynamics, PatchContactOptions contact)
    : patch_(std::move(definition), dynamics), sphere_(sphere), contact_(contact) {
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
    const auto x = patch_.patch().positionsM();
    require(!centerInside(sphere.center_m, x, patch_.patch().definition()),
            "Sphere center starts inside material");
    for (const auto &face : patch_.patch().boundaryTriangles()) {
        const auto closest =
            closestPointOnTriangle(sphere.center_m, {x[face[0]], x[face[1]], x[face[2]]});
        require(closest.resolved &&
                    closest.distance_m >= sphere.radius_m - contact.maximum_penetration_m,
                "Sphere starts with unresolved overlap");
    }
}
SpherePatchReport SpherePatchWorld::step(double dt, const DynamicPatchLoad &load, Vec3 sphere_force,
                                         Vec3 gravity) {
    SpherePatchReport out;
    out.minimum_gap_m = std::numeric_limits<double>::infinity();
    try {
        require(std::isfinite(dt) && dt > 0 && dt <= patch_.stableTimeStepLimitS(),
                "Coupled step exceeds material stability limit");
        require(finite(sphere_force) && length(sphere_force) <= 1.e12 && finite(gravity) &&
                    length(gravity) <= 1.e6,
                "Invalid sphere external force");
        const auto x = patch_.patch().positionsM();
        const auto &d = patch_.patch().definition();
        const auto &mass = patch_.patch().nodalMassesKg();
        const auto &faces = patch_.patch().boundaryTriangles();
        const auto before = patch_.report();
        const double sphere_energy_before = kinetic(sphere_);
        const Vec3 sphere_momentum_before = sphere_.mass_kg * sphere_.velocity_m_s;
        auto sphere = sphere_;
        const Vec3 external = sphere_force + sphere.mass_kg * gravity;
        const bool verlet = patch_.integrator() == DynamicPatchIntegrator::VelocityVerlet;
        sphere.velocity_m_s += (verlet ? .5 : 1.) * dt * external / sphere.mass_kg;
        require(finite(sphere.velocity_m_s) && length(sphere.velocity_m_s) <= 1.e6,
                "Sphere velocity exceeds validity bound");
        SphereSurfaceContactStep contact_step(d, mass, faces, x, patch_.state().velocities_m_s,
                                              sphere_, sphere, dt, external, verlet, contact_, out);
        auto exchange = [&](std::vector<Vec3> &velocity, std::vector<Vec3> &drift) {
            contact_step.exchange(velocity, drift);
        };
        auto final_velocity = [&](std::vector<Vec3> &velocity, const std::vector<Vec3> &u) {
            contact_step.finalVelocity(velocity, u);
        };
        auto charge = [&] {
            require(out.geometry_queries < contact_.maximum_geometry_queries,
                    "Contact geometry work budget exceeded");
            ++out.geometry_queries;
        };
        auto verify = [&](const std::vector<Vec3> &u, const DynamicPatchReport &material_report) {
            require(finite(sphere.velocity_m_s) && length(sphere.velocity_m_s) <= 1.e6,
                    "Sphere final velocity exceeds validity bound");
            require(finite(sphere.center_m) && length(sphere.center_m) <= 1000,
                    "Sphere position exceeds bounds");
            std::vector<Vec3> final_positions(u.size());
            for (std::size_t i = 0; i < u.size(); ++i)
                final_positions[i] = d.reference_positions_m[i] + u[i];
            require(!centerInside(sphere.center_m, final_positions, d),
                    "Sphere entered material; refine timestep");
            for (const auto &face : faces) {
                charge();
                const auto c = closestPointOnTriangle(
                    sphere.center_m,
                    {final_positions[face[0]], final_positions[face[1]], final_positions[face[2]]});
                require(c.resolved, "Invalid contact surface after deformation");
                const double gap = c.distance_m - sphere.radius_m;
                out.minimum_gap_m = std::min(out.minimum_gap_m, gap);
                require(gap >= -contact_.maximum_penetration_m,
                        "Contact penetration tolerance exceeded; refine timestep");
            }
            require(std::isfinite(out.contact_dissipation_j) &&
                        std::isfinite(out.normal_constraint_projection_loss_j) &&
                        std::isfinite(out.tangential_constraint_projection_loss_j) &&
                        finite(out.contact_support_impulse_n_s),
                    "Nonfinite contact ledger");
            out.sphere_kinetic_energy_j = kinetic(sphere);
            out.external_work_j = material_report.external_force_work_increment_j +
                                  dot(external, sphere.center_m - sphere_.center_m);
            out.numerical_energy_balance_residual_j =
                out.sphere_kinetic_energy_j - sphere_energy_before +
                material_report.kinetic_energy_j - before.kinetic_energy_j +
                material_report.stored_free_energy_j - before.stored_free_energy_j +
                material_report.plastic_dissipation_j - before.plastic_dissipation_j +
                out.contact_dissipation_j - out.external_work_j;
            Vec3 patch_external{};
            for (std::size_t i = 0; i < mass.size(); ++i)
                patch_external += dt * (load.nodal_forces_n[i] + mass[i] * load.gravity_m_s2);
            out.linear_momentum_balance_residual_kg_m_s =
                sphere.mass_kg * sphere.velocity_m_s - sphere_momentum_before +
                material_report.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s -
                dt * external - patch_external - material_report.support_impulse_n_s -
                out.contact_support_impulse_n_s;

            require(std::isfinite(out.numerical_energy_balance_residual_j) &&
                        std::isfinite(out.sphere_kinetic_energy_j) &&
                        finite(out.linear_momentum_balance_residual_kg_m_s),
                    "Nonfinite combined contact report");
        };
        out.material = patch_.stepImpl(dt, load, exchange, verify, final_velocity);
        if (!out.material.accepted) {
            out.error = out.material.error;
            return out;
        }
        sphere_ = sphere;
        out.accepted = true;
    } catch (const std::exception &e) {
        out.error = e.what();
    }
    return out;
}
} // namespace banjo
