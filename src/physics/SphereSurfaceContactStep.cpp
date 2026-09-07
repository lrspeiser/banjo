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
SphereSurfaceContactStep::SphereSurfaceContactStep(
    const PatchDefinition &definition, const std::vector<double> &masses,
    const std::vector<std::array<unsigned, 3>> &triangles, const std::vector<Vec3> &positions,
    const std::vector<Vec3> &pre_kick_velocity, const PatchSphere &pre_kick_sphere,
    PatchSphere &candidate_sphere, double time_step, Vec3 external_force, bool velocity_verlet,
    const PatchContactOptions &options, SpherePatchReport &report)
    : d(definition), mass(masses), faces(triangles), x(positions),
      initial_velocity(pre_kick_velocity), initial_sphere(pre_kick_sphere),
      sphere(candidate_sphere), dt(time_step), external(external_force), verlet(velocity_verlet),
      contact_(options), out(report) {}
void SphereSurfaceContactStep::charge() {
    require(out.geometry_queries < contact_.maximum_geometry_queries,
            "Contact geometry work budget exceeded");
    ++out.geometry_queries;
}
void SphereSurfaceContactStep::impulse(unsigned selected, const std::array<double, 3> &weights,
                                       Vec3 normal, const std::vector<Vec3> &positions,
                                       std::vector<Vec3> &velocity, double event_time,
                                       bool final_stage) {
    require(out.impulse_contacts < contact_.maximum_contact_events,
            "Contact event work budget exceeded; refine timestep");
    const auto &ids = faces[selected];
    Vec3 point{};
    for (unsigned i = 0; i < 3; ++i)
        point += weights[i] * positions[ids[i]];
    const Vec3 lever = point - sphere.center_m;
    const Vec3 n = normalized(-lever, normal);
    const auto &physical_sphere = final_stage ? before_final_sphere : initial_sphere;
    const auto &physical_velocity = final_stage ? before_final_velocity : initial_velocity;
    Vec3 initial_material_velocity{};
    for (unsigned i = 0; i < 3; ++i)
        initial_material_velocity += weights[i] * physical_velocity[ids[i]];
    const Vec3 physical_relative = physical_sphere.velocity_m_s +
                                   cross(physical_sphere.spin_rad_s, lever) -
                                   initial_material_velocity;
    // A force kick into an already-resting normal constraint is a
    // reaction, not a fresh inelastic collision. In particular, two
    // Verlet half-kick projections must not manufacture heat in a
    // motionless, gravity-loaded contact. A swept arrival or an actual
    // incoming velocity still carries its irreversible impact loss.
    const double physical_normal_speed = dot(physical_relative, n);
    // A preceding contact can leave another face closing before the
    // second kick. That residual is incoming motion, not support work.
    const bool normal_reaction = (final_stage && physical_normal_speed >= -1.e-10) ||
                                 (event_time == 0 && std::abs(physical_normal_speed) <= 1.e-10);
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
                    value += weights[i] * weights[i] * axis(direction, a) * axis(direction, a) /
                             mass[ids[i]];
        return value;
    };
    const double normal_j = std::max(0., -dot(relative(), n) / inverse(n));
    require(normal_j > 0 && std::isfinite(normal_j), "Unresolved zero-impulse contact event");
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
                    set(velocity[ids[i]], a, axis(velocity[ids[i]], a) - component / mass[ids[i]]);
                }
            }
            out.contact_support_impulse_n_s += support;
            angular += cross(positions[ids[i]], free_impulse - support);
        }
        out.contact_angular_momentum_residual_kg_m2_s += angular;
    };
    apply(normal_j * n);
    double energy_after_normal = kinetic(sphere);
    for (unsigned i = 0; i < 3; ++i)
        energy_after_normal += .5 * mass[ids[i]] * lengthSquared(velocity[ids[i]]);
    const Vec3 rel = relative(), tangent = rel - dot(rel, n) * n;
    const double speed = length(tangent);
    bool static_reaction = false;
    if (speed > 1.e-12 && contact_.friction_coefficient > 0) {
        const Vec3 direction = tangent / speed;
        const double stopping_j = speed / inverse(direction);
        const double friction_limit = contact_.friction_coefficient * normal_j;
        const double j = std::min(stopping_j, friction_limit);
        const Vec3 physical_tangent = physical_relative - dot(physical_relative, n) * n;
        // Static friction can remove slip introduced solely by a force
        // kick. Retain this stage loss as numerical projection, not
        // sliding heat. Incoming/sliding motion or a saturated Coulomb
        // impulse keeps its physical dissipative work.
        static_reaction = normal_reaction && (final_stage || event_time == 0) &&
                          length(physical_tangent) <= 1.e-10 && stopping_j <= friction_limit;
        apply(-j * direction);
    }
    double energy_after = kinetic(sphere);
    for (unsigned i = 0; i < 3; ++i)
        energy_after += .5 * mass[ids[i]] * lengthSquared(velocity[ids[i]]);
    const double loss = energy_before - energy_after;
    require(loss >= -1.e-10 * std::max(1., energy_before), "Contact created kinetic energy");
    const double normal_loss = energy_before - energy_after_normal;
    const double friction_loss = energy_after_normal - energy_after;
    out.contact_dissipation_j +=
        (normal_reaction ? 0 : normal_loss) + (static_reaction ? 0 : friction_loss);
    if (normal_reaction)
        out.normal_constraint_projection_loss_j += normal_loss;
    if (static_reaction)
        out.tangential_constraint_projection_loss_j += friction_loss;
    ++out.impulse_contacts;
    if (out.contacts.size() < 64)
        out.contacts.push_back({selected, event_time, weights, point, n, applied, final_stage,
                                normal_reaction, static_reaction});
    if (final_stage)
        ++out.velocity_constraint_contacts;
}
void SphereSurfaceContactStep::exchange(std::vector<Vec3> &velocity, std::vector<Vec3> &drift) {
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
            const std::array<Vec3, 3> speeds{velocity[ids[0]], velocity[ids[1]], velocity[ids[2]]};
            if (!sweptBoxesOverlap(sphere, points, speeds, remaining, contact_.contact_margin_m))
                continue;
            require(out.geometry_iterations < contact_.maximum_geometry_iterations,
                    "Contact geometry iteration budget exceeded");
            charge();
            const auto hit = sweepSphereTriangle(
                sphere.center_m, sphere.velocity_m_s, sphere.radius_m, points, speeds, remaining,
                {contact_.contact_margin_m,
                 std::min(128u, contact_.maximum_geometry_iterations - out.geometry_iterations)});
            out.geometry_iterations += hit.iterations;
            require(out.geometry_iterations <= contact_.maximum_geometry_iterations,
                    "Contact geometry iteration budget exceeded");
            if (!hit.resolved) {
                std::ostringstream diagnostic;
                diagnostic << std::setprecision(17)
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
        impulse(selected, earliest.barycentric, earliest.normal_triangle_to_sphere, positions,
                velocity, elapsed, false);
    }
    // Preserve the actual end-of-drift contact velocity, before the
    // material and sphere receive their second Verlet force half-kick.
    if (verlet) {
        before_final_velocity = velocity;
        before_final_sphere = sphere;
    }
}
void SphereSurfaceContactStep::finalVelocity(std::vector<Vec3> &velocity,
                                             const std::vector<Vec3> &u) {
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
            if (dot(sphere.velocity_m_s - material_velocity, c.normal_triangle_to_query) >= -1.e-10)
                continue;
            impulse(f, c.barycentric, c.normal_triangle_to_query, positions, velocity, dt, true);
            changed = true;
        }
    } while (changed);
}
} // namespace banjo
