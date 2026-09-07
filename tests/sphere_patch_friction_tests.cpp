#include "physics/SpherePatchWorld.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;
void require(bool value, std::string_view message) {
    if (!value)
        throw std::runtime_error(std::string(message));
}
void near(double a, double b, double tolerance, std::string_view message) {
    if (!std::isfinite(a) || std::abs(a - b) > tolerance)
        throw std::runtime_error(std::string(message));
}
double kinetic(const PatchSphere &s) {
    const double inertia = .4 * s.mass_kg * s.radius_m * s.radius_m;
    return .5 * s.mass_kg * lengthSquared(s.velocity_m_s) +
           .5 * inertia * lengthSquared(s.spin_rad_s);
}
SmallStrainLaw elastic() {
    constexpr double e = 1e6, p = .25, g = e / (2 * (1 + p));
    return {.kind = SmallStrainLawKind::IsotropicElastic,
            .young_modulus_pa = {e, e, e},
            .poisson_xy_yz_zx = {p, p, p},
            .shear_xy_yz_zx_pa = {g, g, g},
            .maximum_total_strain_norm = .08};
}
PatchDefinition plane() {
    auto d = makeTetrahedralBrick({.2, .02, .2}, {2, 1, 2}, {elastic(), 1000});
    for (auto &fixed : d.fixed_components)
        fixed = {true, true, true};
    return d;
}
PatchDefinition deformablePlane() {
    auto d = makeTetrahedralBrick({.2, .02, .2}, {2, 1, 2}, {elastic(), 1000});
    for (std::size_t i = 0; i < d.reference_positions_m.size(); ++i)
        if (d.reference_positions_m[i].y == 0)
            d.fixed_components[i] = {true, true, true};
    return d;
}
DynamicPatchLoad zeroLoad(std::size_t n) {
    DynamicPatchLoad l;
    l.nodal_forces_n.resize(n);
    return l;
}
constexpr double radius = .012, margin = 1e-6, mass = .04;
constexpr Vec3 gravity{0, -9.81, 0};
PatchSphere resting(Vec3 velocity = {}, Vec3 spin = {}) {
    return {{0, .02 + radius + margin, 0}, velocity, spin, radius, mass};
}
struct Totals {
    double work{}, physical_dissipation{}, tangent_projection{}, normal_projection{};
    Vec3 impulse{};
    bool static_reaction{}, sliding{};
};
void add(Totals &total, const SpherePatchReport &r) {
    total.work += r.external_work_j;
    total.physical_dissipation += r.contact_dissipation_j;
    total.tangent_projection += r.tangential_constraint_projection_loss_j;
    total.normal_projection += r.normal_constraint_projection_loss_j;
    for (const auto &e : r.contacts) {
        total.impulse += e.impulse_to_sphere_n_s;
        total.static_reaction = total.static_reaction || e.static_friction_reaction;
        total.sliding = total.sliding ||
                        (!e.static_friction_reaction && std::abs(e.impulse_to_sphere_n_s.x) > 0);
    }
}

void drivenStaticFrictionProducesAnalyticPureRolling() {
    auto d = plane();
    SpherePatchWorld world(
        d, resting(), {.integrator = DynamicPatchIntegrator::VelocityVerlet},
        {.friction_coefficient = 1.2, .contact_margin_m = margin, .maximum_penetration_m = 1e-5});
    constexpr double force = 1, dt = 1e-4;
    constexpr unsigned steps = 100;
    const double lever = radius + margin, inertia = .4 * mass * radius * radius;
    const double acceleration = force / (mass + inertia / (lever * lever));
    Totals total;
    for (unsigned i = 0; i < steps; ++i) {
        const auto r =
            world.step(dt, zeroLoad(d.reference_positions_m.size()), {force, 0, 0}, gravity);
        require(r.accepted, "driven rolling step must accept");
        add(total, r);
    }
    const double time = steps * dt;
    near(world.sphere().velocity_m_s.x, acceleration * time, 2e-10, "analytic rolling velocity");
    near(world.sphere().center_m.x, .5 * acceleration * time * time, 2e-12,
         "analytic rolling position");
    const double slip = world.sphere().velocity_m_s.x + lever * world.sphere().spin_rad_s.z;
    near(slip, 0, 2e-11, "static friction contact-point slip");
    require(total.static_reaction && !total.sliding,
            "adequate Coulomb bound must use static friction reactions");
    near(total.physical_dissipation, 0, 1e-15, "pure rolling physical dissipation");
    near(kinetic(world.sphere()) - total.work, 0, 2e-10, "pure rolling kinetic/work ledger");
    near(mass * world.sphere().velocity_m_s.x - force * time - total.impulse.x, 0, 2e-12,
         "rolling horizontal impulse momentum");
    near(mass * world.sphere().velocity_m_s.y - mass * gravity.y * time - total.impulse.y, 0, 2e-12,
         "rolling normal reaction momentum");
    std::cout << "[INFO] rolling a=" << acceleration << " slip=" << slip
              << " tangent_projection=" << total.tangent_projection << '\n';
}

void initialSlidingHasPhysicalFrictionLossAndSpin() {
    auto d = plane();
    const auto initial = resting({.1, 0, 0});
    SpherePatchWorld world(
        d, initial, {.integrator = DynamicPatchIntegrator::VelocityVerlet},
        {.friction_coefficient = .05, .contact_margin_m = margin, .maximum_penetration_m = 1e-5});
    const auto r = world.step(1e-3, zeroLoad(d.reference_positions_m.size()), {}, gravity);
    require(r.accepted && r.contact_dissipation_j > 0,
            "initial sliding must produce physical friction dissipation");
    require(world.sphere().velocity_m_s.x < initial.velocity_m_s.x &&
                world.sphere().spin_rad_s.z < 0,
            "sliding friction must reduce translation and generate rolling spin");
    near(kinetic(world.sphere()) - kinetic(initial) + r.contact_dissipation_j - r.external_work_j,
         0, 2e-12, "sliding kinetic+dissipation-work ledger");
    require(r.tangential_constraint_projection_loss_j == 0,
            "Coulomb sliding loss cannot be recorded as reversible static projection");
}

void coulombBoundDistinguishesStaticReactionAndSaturation() {
    auto run = [](double friction) {
        auto d = plane();
        SpherePatchWorld world(d, resting(), {.integrator = DynamicPatchIntegrator::VelocityVerlet},
                               {.friction_coefficient = friction,
                                .contact_margin_m = margin,
                                .maximum_penetration_m = 1e-5});
        const auto r =
            world.step(1e-4, zeroLoad(d.reference_positions_m.size()), {1, 0, 0}, gravity);
        require(r.accepted, "Coulomb comparison step must accept");
        Totals t;
        add(t, r);
        return t;
    };
    const auto below = run(1.2), saturated = run(.1);
    require(below.static_reaction && !below.sliding && below.physical_dissipation == 0,
            "below-bound kick must be a lossless static reaction");
    require(saturated.sliding && saturated.physical_dissipation > 0,
            "insufficient Coulomb bound must saturate and dissipate sliding energy");
    near(std::abs(saturated.impulse.x) / saturated.impulse.y, .1, 2e-8,
         "saturated tangential/normal impulse ratio");
}

void initialPureRollRemainsLossFreeWithoutHorizontalForce() {
    const double lever = radius + margin, speed = .1;
    auto d = plane();
    const auto initial = resting({speed, 0, 0}, {0, 0, -speed / lever});
    SpherePatchWorld world(
        d, initial, {.integrator = DynamicPatchIntegrator::VelocityVerlet},
        {.friction_coefficient = .8, .contact_margin_m = margin, .maximum_penetration_m = 1e-5});
    Totals total;
    constexpr double dt = 1e-4;
    constexpr unsigned steps = 100;
    for (unsigned i = 0; i < steps; ++i) {
        const auto r = world.step(dt, zeroLoad(d.reference_positions_m.size()), {}, gravity);
        require(r.accepted, "unforced pure-roll step must accept");
        add(total, r);
    }
    near(world.sphere().velocity_m_s.x, speed, 2e-12, "unforced rolling speed");
    near(world.sphere().spin_rad_s.z, -speed / lever, 2e-10, "unforced rolling spin");
    near(world.sphere().velocity_m_s.x + lever * world.sphere().spin_rad_s.z, 0, 2e-12,
         "unforced rolling contact slip");
    near(total.physical_dissipation, 0, 1e-15, "unforced pure-roll dissipation");
    near(kinetic(world.sphere()), kinetic(initial), 2e-13, "unforced pure-roll kinetic energy");
}

void staticFrictionTransfersMomentumIntoDeformableFace() {
    auto d = deformablePlane();
    SpherePatchWorld world(
        d, resting(), {.integrator = DynamicPatchIntegrator::VelocityVerlet},
        {.friction_coefficient = 1.2, .contact_margin_m = margin, .maximum_penetration_m = 1e-5});
    constexpr double force = 1., dt = 1e-5;
    const auto report =
        world.step(dt, zeroLoad(d.reference_positions_m.size()), {force, 0, 0}, gravity);
    require(report.accepted, "driven deformable-face contact must accept");
    Totals total;
    add(total, report);
    require(total.static_reaction && !total.sliding,
            "adequate friction must classify force-kick slip as a static reaction");
    near(total.physical_dissipation, 0, 1e-15,
         "static transfer into deformable matter is not sliding heat");
    require(total.tangent_projection > 0,
            "discrete static velocity projection must remain visible numerically");
    bool moving_top = false;
    for (std::size_t i = 0; i < d.reference_positions_m.size(); ++i)
        if (d.reference_positions_m[i].y == .02)
            moving_top = moving_top || std::abs(world.material().state().velocities_m_s[i].x) > 0;
    require(moving_top, "equal-and-opposite static friction impulse must move free surface nodes");
    const Vec3 patch_momentum = report.material.linear_momentum_kg_m_s;
    require(patch_momentum.x > 0 && total.impulse.x < 0,
            "patch and sphere must receive opposite tangential contact impulses");
    near(report.linear_momentum_balance_residual_kg_m_s.x, 0, 2e-12,
         "deformable tangential transfer whole-system momentum ledger");
    near(patch_momentum.x + total.impulse.x - report.material.support_impulse_n_s.x, 0, 2e-12,
         "patch momentum includes only contact transfer and support reaction");
}
} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"driven analytic pure rolling", drivenStaticFrictionProducesAnalyticPureRolling},
        {"initial sliding physical dissipation", initialSlidingHasPhysicalFrictionLossAndSpin},
        {"Coulomb static versus saturation", coulombBoundDistinguishesStaticReactionAndSaturation},
        {"unforced initial pure roll", initialPureRollRemainsLossFreeWithoutHorizontalForce},
        {"deformable-face static transfer", staticFrictionTransfersMomentumIntoDeformableFace}};
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &e) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << e.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size() << " tests passed\n";
    return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
