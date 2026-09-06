#include "physics/SpherePatchWorld.hpp"
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
double axis(Vec3 v, unsigned a) {
    return a == 0 ? v.x : a == 1 ? v.y : v.z;
}
void set(Vec3 &v, unsigned a, double x) {
    if (a == 0)
        v.x = x;
    else if (a == 1)
        v.y = x;
    else
        v.z = x;
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
bool sweptBoxesOverlap(const PatchSphere &s, const std::array<Vec3, 3> &p,
                       const std::array<Vec3, 3> &v, double dt, double margin) {
    for (unsigned a = 0; a < 3; ++a) {
        double low = std::numeric_limits<double>::infinity(), high = -low;
        for (unsigned i = 0; i < 3; ++i) {
            low = std::min({low, axis(p[i], a), axis(p[i] + dt * v[i], a)});
            high = std::max({high, axis(p[i], a), axis(p[i] + dt * v[i], a)});
        }
        const double start = axis(s.center_m, a), end = axis(s.center_m + dt * s.velocity_m_s, a);
        if (std::max(start, end) + s.radius_m + margin < low ||
            std::min(start, end) - s.radius_m - margin > high)
            return false;
    }
    return true;
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
        auto charge = [&] {
            require(out.geometry_queries < contact_.maximum_geometry_queries,
                    "Contact geometry work budget exceeded");
            ++out.geometry_queries;
        };
        auto impulse = [&](unsigned selected, const std::array<double, 3> &weights, Vec3 normal,
                           const std::vector<Vec3> &positions, std::vector<Vec3> &velocity,
                           double event_time, bool final_stage) {
            require(out.impulse_contacts < contact_.maximum_contact_events,
                    "Contact event work budget exceeded; refine timestep");
            const auto &ids = faces[selected];
            Vec3 point{};
            for (unsigned i = 0; i < 3; ++i)
                point += weights[i] * positions[ids[i]];
            const Vec3 lever = point - sphere.center_m;
            const Vec3 n = normalized(-lever, normal);
            auto relative = [&] {
                Vec3 v{};
                for (unsigned i = 0; i < 3; ++i)
                    v += weights[i] * velocity[ids[i]];
                return sphere.velocity_m_s + cross(sphere.spin_rad_s, lever) - v;
            };
            auto inverse = [&](Vec3 direction) {
                double value =
                    1 / sphere.mass_kg + lengthSquared(cross(lever, direction)) / inertia(sphere);
                for (unsigned i = 0; i < 3; ++i)
                    for (unsigned a = 0; a < 3; ++a)
                        if (!d.fixed_components[ids[i]][a])
                            value += weights[i] * weights[i] * axis(direction, a) *
                                     axis(direction, a) / mass[ids[i]];
                return value;
            };
            const double normal_j = std::max(0., -dot(relative(), n) / inverse(n));
            require(normal_j > 0 && std::isfinite(normal_j),
                    "Unresolved zero-impulse contact event");
            double energy_before = kinetic(sphere);
            for (unsigned i = 0; i < 3; ++i)
                energy_before += .5 * mass[ids[i]] * lengthSquared(velocity[ids[i]]);
            Vec3 applied{};
            auto apply = [&](Vec3 impulse) {
                applied += impulse;
                sphere.velocity_m_s += impulse / sphere.mass_kg;
                sphere.spin_rad_s += cross(lever, impulse) / inertia(sphere);
                Vec3 angular = cross(sphere.center_m, impulse) + cross(lever, impulse);
                for (unsigned i = 0; i < 3; ++i) {
                    Vec3 free_impulse{}, support{};
                    for (unsigned a = 0; a < 3; ++a) {
                        const double component = weights[i] * axis(impulse, a);
                        if (d.fixed_components[ids[i]][a])
                            set(support, a, component);
                        else {
                            set(free_impulse, a, -component);
                            set(velocity[ids[i]], a,
                                axis(velocity[ids[i]], a) - component / mass[ids[i]]);
                        }
                    }
                    out.contact_support_impulse_n_s += support;
                    angular += cross(positions[ids[i]], free_impulse - support);
                }
                out.contact_angular_momentum_residual_kg_m2_s += angular;
            };
            apply(normal_j * n);
            const Vec3 rel = relative(), tangent = rel - dot(rel, n) * n;
            const double speed = length(tangent);
            if (speed > 1.e-12 && contact_.friction_coefficient > 0) {
                const Vec3 direction = tangent / speed;
                const double j =
                    std::min(speed / inverse(direction), contact_.friction_coefficient * normal_j);
                apply(-j * direction);
            }
            double energy_after = kinetic(sphere);
            for (unsigned i = 0; i < 3; ++i)
                energy_after += .5 * mass[ids[i]] * lengthSquared(velocity[ids[i]]);
            const double loss = energy_before - energy_after;
            require(loss >= -1.e-10 * std::max(1., energy_before),
                    "Contact created kinetic energy");
            out.contact_dissipation_j += loss;
            ++out.impulse_contacts;
            if (out.contacts.size() < 64)
                out.contacts.push_back(
                    {selected, event_time, weights, point, n, applied, final_stage});
            if (final_stage)
                ++out.velocity_constraint_contacts;
        };
        auto exchange = [&](std::vector<Vec3> &velocity, std::vector<Vec3> &drift) {
            auto positions = x;
            double elapsed = 0;
            auto advance = [&](double amount) {
                for (std::size_t i = 0; i < positions.size(); ++i) {
                    const auto delta = amount * velocity[i];
                    positions[i] += delta;
                    drift[i] += delta;
                }
                sphere.center_m += amount * sphere.velocity_m_s;
                elapsed += amount;
            };
            while (elapsed < dt) {
                const double remaining = dt - elapsed;
                bool found = false;
                unsigned selected = 0;
                SweptSphereTriangleResult earliest;
                earliest.time_s = remaining;
                for (unsigned f = 0; f < faces.size(); ++f) {
                    const auto &ids = faces[f];
                    const std::array<Vec3, 3> points{positions[ids[0]], positions[ids[1]],
                                                     positions[ids[2]]};
                    const std::array<Vec3, 3> speeds{velocity[ids[0]], velocity[ids[1]],
                                                     velocity[ids[2]]};
                    if (!sweptBoxesOverlap(sphere, points, speeds, remaining,
                                           contact_.contact_margin_m))
                        continue;
                    require(out.geometry_iterations < contact_.maximum_geometry_iterations,
                            "Contact geometry iteration budget exceeded");
                    charge();
                    const auto hit =
                        sweepSphereTriangle(sphere.center_m, sphere.velocity_m_s, sphere.radius_m,
                                            points, speeds, remaining,
                                            {contact_.contact_margin_m,
                                             std::min(128u, contact_.maximum_geometry_iterations -
                                                                out.geometry_iterations)});
                    out.geometry_iterations += hit.iterations;
                    require(out.geometry_iterations <= contact_.maximum_geometry_iterations,
                            "Contact geometry iteration budget exceeded");
                    if (!hit.resolved) {
                        std::ostringstream diagnostic;
                        diagnostic
                            << std::setprecision(17)
                            << "Swept contact geometry unresolved: triangle=" << f
                            << " iterations=" << hit.iterations << " query_time_s=" << hit.time_s
                            << " distance_m=" << hit.distance_m << " duration_s=" << remaining
                            << " radius_m=" << sphere.radius_m << " center=";
                        auto vector = [&](Vec3 value) {
                            diagnostic << '[' << value.x << ',' << value.y << ',' << value.z << ']';
                        };
                        vector(sphere.center_m);
                        diagnostic << " sphere_velocity=";
                        vector(sphere.velocity_m_s);
                        diagnostic << " vertices=";
                        for (auto point : points)
                            vector(point);
                        diagnostic << " vertex_velocities=";
                        for (auto speed : speeds)
                            vector(speed);
                        throw std::runtime_error(diagnostic.str());
                    }
                    if (!hit.hit)
                        continue;
                    Vec3 surface_velocity{};
                    for (unsigned i = 0; i < 3; ++i)
                        surface_velocity += hit.barycentric[i] * speeds[i];
                    // A sphere's spin has no normal surface speed. Non-closing
                    // grazing/resting events require no impulse and must not
                    // prevent searching later faces along the remaining path.
                    const double closing =
                        dot(sphere.velocity_m_s - surface_velocity, hit.normal_triangle_to_sphere);
                    if (closing >= -1.e-10)
                        continue;
                    if (!found || hit.time_s < earliest.time_s) {
                        found = true;
                        selected = f;
                        earliest = hit;
                    }
                }
                if (!found) {
                    advance(remaining);
                    break;
                }
                advance(earliest.time_s);
                impulse(selected, earliest.barycentric, earliest.normal_triangle_to_sphere,
                        positions, velocity, elapsed, false);
            }
        };
        auto final_velocity = [&](std::vector<Vec3> &velocity, const std::vector<Vec3> &u) {
            if (!verlet)
                return;
            sphere.velocity_m_s += .5 * dt * external / sphere.mass_kg;
            std::vector<Vec3> positions(u.size());
            for (std::size_t i = 0; i < u.size(); ++i)
                positions[i] = d.reference_positions_m[i] + u[i];
            // The second force kick must leave touching surfaces with no
            // unresolved closing velocity. This only changes velocity through
            // the same passive contact impulse, never by moving positions.
            bool changed;
            do {
                changed = false;
                for (unsigned f = 0; f < faces.size(); ++f) {
                    const auto &ids = faces[f];
                    charge();
                    const auto c = closestPointOnTriangle(
                        sphere.center_m, {positions[ids[0]], positions[ids[1]], positions[ids[2]]});
                    require(c.resolved, "Invalid surface in final velocity constraint");
                    const double roundoff =
                        32 * std::numeric_limits<double>::epsilon() * std::max(1., sphere.radius_m);
                    if (c.distance_m > sphere.radius_m + contact_.contact_margin_m + roundoff)
                        continue;
                    Vec3 material_velocity{};
                    for (unsigned i = 0; i < 3; ++i)
                        material_velocity += c.barycentric[i] * velocity[ids[i]];
                    if (dot(sphere.velocity_m_s - material_velocity, c.normal_triangle_to_query) >=
                        -1.e-10)
                        continue;
                    impulse(f, c.barycentric, c.normal_triangle_to_query, positions, velocity, dt,
                            true);
                    changed = true;
                }
            } while (changed);
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
