#include "physics/SpherePatchWorld.hpp"
#include "physics/SweptSphereTriangle.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
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
void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message));
}
double magnitude(Vec3 v) {
    return std::sqrt(dot(v, v));
}

SmallStrainLaw elastic(double young = 1.e6) {
    constexpr double poisson = .25;
    const double shear = young / (2 * (1 + poisson));
    return {.kind = SmallStrainLawKind::IsotropicElastic,
            .young_modulus_pa = {young, young, young},
            .poisson_xy_yz_zx = {poisson, poisson, poisson},
            .shear_xy_yz_zx_pa = {shear, shear, shear},
            .maximum_total_strain_norm = .08};
}
SmallStrainLaw j2() {
    SmallStrainLaw law;
    law.kind = SmallStrainLawKind::J2Plastic;
    law.j2 = {.young_modulus_pa = 1.e6,
              .poisson_ratio = .25,
              .initial_yield_stress_pa = 1200,
              .isotropic_hardening_modulus_pa = 2.e4,
              .maximum_total_strain_norm = .08};
    law.maximum_total_strain_norm = .08;
    return law;
}
PatchDefinition brick(SmallStrainLaw law, double density = 1000, bool supported = true) {
    auto d = makeTetrahedralBrick({.08, .02, .08}, {2, 1, 2}, {law, density});
    if (supported)
        for (std::size_t i = 0; i < d.reference_positions_m.size(); ++i)
            if (d.reference_positions_m[i].y == 0)
                d.fixed_components[i] = {true, true, true};
    return d;
}
DynamicPatchLoad zeroLoad(std::size_t n) {
    DynamicPatchLoad load;
    load.nodal_forces_n.resize(n);
    return load;
}
bool sameVectors(const std::vector<Vec3> &a, const std::vector<Vec3> &b) {
    if (a.size() != b.size())
        return false;
    for (std::size_t i = 0; i < a.size(); ++i)
        if (a[i].x != b[i].x || a[i].y != b[i].y || a[i].z != b[i].z)
            return false;
    return true;
}
bool sameSphere(const PatchSphere &a, const PatchSphere &b) {
    return a.center_m.x == b.center_m.x && a.center_m.y == b.center_m.y &&
           a.center_m.z == b.center_m.z && a.velocity_m_s.x == b.velocity_m_s.x &&
           a.velocity_m_s.y == b.velocity_m_s.y && a.velocity_m_s.z == b.velocity_m_s.z &&
           a.spin_rad_s.x == b.spin_rad_s.x && a.spin_rad_s.y == b.spin_rad_s.y &&
           a.spin_rad_s.z == b.spin_rad_s.z && a.radius_m == b.radius_m && a.mass_kg == b.mass_kg;
}
bool samePatch(const PatchState &a, const PatchState &b) {
    return sameVectors(a.displacements_m, b.displacements_m) &&
           a.material_points == b.material_points &&
           sameVectors(a.last_nodal_forces_n, b.last_nodal_forces_n) && a.revision == b.revision &&
           a.accumulated_trapezoidal_external_work_j == b.accumulated_trapezoidal_external_work_j &&
           a.accumulated_backward_euler_external_work_j ==
               b.accumulated_backward_euler_external_work_j;
}
bool sameDynamic(const DynamicPatchState &a, const DynamicPatchState &b) {
    return sameVectors(a.velocities_m_s, b.velocities_m_s) && a.time_s == b.time_s &&
           a.revision == b.revision &&
           a.accumulated_external_force_work_j == b.accumulated_external_force_work_j &&
           a.accumulated_support_impulse_n_s.x == b.accumulated_support_impulse_n_s.x &&
           a.accumulated_support_impulse_n_s.y == b.accumulated_support_impulse_n_s.y &&
           a.accumulated_support_impulse_n_s.z == b.accumulated_support_impulse_n_s.z;
}

SpherePatchAdvanceOptions controls(double scale = 1) {
    SpherePatchAdvanceOptions o;
    o.error = {.position_m = 2e-5 * scale,
               .velocity_m_s = .05 * scale,
               .strain = .005 * scale,
               .energy_disagreement_j = 2e-5 * scale,
               .absolute_energy_residual_j = 2e-5 * scale,
               .reference_time_s = .01};
    o.initial_trial_dt_s = 2e-4;
    o.maximum_trial_dt_s = 2e-4;
    o.minimum_trial_dt_s = 1e-8;
    return o;
}

void freeFlightIsExactIndependentOfAdaptiveSegmentation() {
    auto d = brick(elastic(), 1000, false);
    PatchSphere sphere{{0, .2, 0}, {.3, -.2, .1}, {}, .012, .01};
    SpherePatchWorld world(d, sphere);
    constexpr double duration = .0037;
    auto report = world.advance(duration, zeroLoad(d.reference_positions_m.size()), controls(1e3));
    require(report.accepted && report.advanced_time_s == duration,
            "free flight must accept the full requested interval");
    near(world.sphere().center_m.x, sphere.center_m.x + duration * sphere.velocity_m_s.x, 1e-14,
         "free-flight x");
    near(world.sphere().center_m.y, sphere.center_m.y + duration * sphere.velocity_m_s.y, 1e-14,
         "free-flight y");
    near(world.sphere().center_m.z, sphere.center_m.z + duration * sphere.velocity_m_s.z, 1e-14,
         "free-flight z");
    require(report.absolute_energy_residual_j < 1e-14 &&
                magnitude(report.momentum_residual_kg_m_s) < 1e-13,
            "free-flight ledgers must close to roundoff");
    std::cout << "[INFO] free flight segments=" << report.accepted_segments
              << " calls=" << report.step_calls << '\n';
}

void velocityVerletConstantGravityIsExact() {
    auto d = brick(elastic(), 1000, true);
    constexpr Vec3 gravity{0, -9.81, 0};
    PatchSphere sphere{{0, .2, 0}, {.3, -.2, .1}, {}, .012, .01};
    SpherePatchWorld world(d, sphere, {.integrator = DynamicPatchIntegrator::VelocityVerlet});
    auto o = controls(1);
    o.error = {.position_m = 1e-10,
               .velocity_m_s = 1e-9,
               .strain = 1e-9,
               .energy_disagreement_j = 1e-10,
               .absolute_energy_residual_j = 1e-10,
               .reference_time_s = .01};
    o.initial_trial_dt_s = 1e-3;
    o.maximum_trial_dt_s = 1e-3;
    o.minimum_trial_dt_s = 1e-10;
    constexpr double duration = .0037;
    const auto report =
        world.advance(duration, zeroLoad(d.reference_positions_m.size()), o, {}, gravity);
    require(report.accepted && report.advanced_time_s == duration,
            "Velocity Verlet constant-gravity oracle must accept the full interval");
    const Vec3 expected =
        sphere.center_m + duration * sphere.velocity_m_s + .5 * duration * duration * gravity;
    near(world.sphere().center_m.x, expected.x, 2e-14, "Velocity Verlet gravity x");
    near(world.sphere().center_m.y, expected.y, 2e-14, "Velocity Verlet gravity y");
    near(world.sphere().center_m.z, expected.z, 2e-14, "Velocity Verlet gravity z");
    near(world.sphere().velocity_m_s.y, sphere.velocity_m_s.y + duration * gravity.y, 2e-14,
         "Velocity Verlet gravity velocity");
    require(report.absolute_energy_residual_j < 1e-11,
            "Velocity Verlet constant-force energy ledger must satisfy tight budget");
    std::cout << "[INFO] VV gravity segments=" << report.accepted_segments
              << " energy_abs=" << report.absolute_energy_residual_j << '\n';
}

SpherePatchAdvanceReport dropAdvance(double tolerance_scale) {
    auto d = brick(elastic());
    constexpr double radius = .012, mass = .056954;
    SpherePatchWorld world(d, {{.007, .0325, .009}, {}, {}, radius, mass}, {},
                           {.contact_margin_m = 1e-6, .maximum_penetration_m = 1e-5});
    auto load = zeroLoad(d.reference_positions_m.size());
    load.gravity_m_s2 = {0, -9.81, 0};
    auto o = controls(tolerance_scale);
    o.initial_trial_dt_s = 1e-4;
    o.maximum_trial_dt_s = 2e-4;
    return world.advance(.015, load, o, {}, {0, -9.81, 0});
}

void stricterBudgetForcesRefinement() {
    const auto loose = dropAdvance(4), tight = dropAdvance(.25);
    require(loose.accepted && tight.accepted, "both adaptive accuracy budgets must complete");
    require(tight.accepted_segments > loose.accepted_segments &&
                tight.minimum_accepted_step_s < loose.minimum_accepted_step_s,
            "stricter local error budget must force finer accepted segments");
    require(tight.maximum_accepted_error <= 1.0 + 1e-12,
            "accepted tight segments must satisfy normalized limit");
    std::cout << "[INFO] adaptive segments loose=" << loose.accepted_segments
              << " tight=" << tight.accepted_segments << " min_dt=" << loose.minimum_accepted_step_s
              << ',' << tight.minimum_accepted_step_s << '\n';
}

void intervalFailureRollsBackTentativeSegmentsExactly() {
    auto d = brick(elastic());
    SpherePatchWorld world(d, {{.007, .0325, .009}, {}, {}, .012, .056954});
    const auto sphere0 = world.sphere();
    const auto patch0 = world.material().patch().state();
    const auto dynamic0 = world.material().state();
    auto o = controls(.25);
    o.maximum_step_calls = 7;
    const auto report = world.advance(.02, zeroLoad(d.reference_positions_m.size()), o);
    require(!report.accepted && report.advanced_time_s == 0 && report.tentative_time_s > 0,
            "work exhaustion after tentative progress must reject the whole interval");
    require(report.step_calls <= o.maximum_step_calls && sameSphere(world.sphere(), sphere0) &&
                samePatch(world.material().patch().state(), patch0) &&
                sameDynamic(world.material().state(), dynamic0),
            "failed interval must restore every coupled state and obey its step-call bound");
    std::cout << "[INFO] rollback tentative_time=" << report.tentative_time_s << " error='"
              << report.error << "'\n";
}

void plasticHistorySurvivesRejectedContinuation() {
    auto d = brick(j2());
    SpherePatchWorld world(d, {{.007, .03200001, .009}, {0, -.3, 0}, {}, .012, .056954});
    const double dt = world.material().stableTimeStepLimitS() * .05;
    double plastic0 = 0;
    for (unsigned step = 0; step < 400 && plastic0 == 0; ++step) {
        require(world.step(dt, zeroLoad(d.reference_positions_m.size())).accepted,
                "J2 compression seed trajectory must accept");
        for (const auto &s : world.material().patch().state().material_points)
            plastic0 = std::max(plastic0, s.equivalent_plastic_strain);
    }
    if (!(plastic0 > 0))
        throw std::runtime_error("seed impact created no J2 history: max_eq_plastic=" +
                                 std::to_string(plastic0));
    const auto sphere0 = world.sphere();
    const auto patch0 = world.material().patch().state();
    const auto dynamic0 = world.material().state();
    auto o = controls(.1);
    o.maximum_reserved_element_visits = 1;
    const auto report = world.advance(.001, zeroLoad(d.reference_positions_m.size()), o);
    require(!report.accepted && sameSphere(world.sphere(), sphere0) &&
                samePatch(world.material().patch().state(), patch0) &&
                sameDynamic(world.material().state(), dynamic0),
            "failed adaptive continuation cannot erase or advance plastic history");
}

void velocityVerletRollbackRestoresCachedForceState() {
    auto d = brick(elastic());
    const PatchSphere sphere{{.007, .03200001, .009}, {0, -.2, 0}, {}, .012, .056954};
    const DynamicPatchOptions dynamics{.integrator = DynamicPatchIntegrator::VelocityVerlet};
    SpherePatchWorld failed(d, sphere, dynamics), control(d, sphere, dynamics);
    const double seed_dt = failed.material().stableTimeStepLimitS() * .04;
    require(failed.step(seed_dt, zeroLoad(d.reference_positions_m.size())).accepted &&
                control.step(seed_dt, zeroLoad(d.reference_positions_m.size())).accepted,
            "Velocity Verlet cache seed steps must accept");
    auto o = controls(.25);
    o.maximum_step_calls = 7;
    const auto rejected = failed.advance(.002, zeroLoad(d.reference_positions_m.size()), o);
    require(!rejected.accepted && rejected.tentative_time_s > 0,
            "Velocity Verlet rollback fixture must fail after tentative progress");
    const double followup_dt = failed.material().stableTimeStepLimitS() * .03;
    const auto after_failed = failed.step(followup_dt, zeroLoad(d.reference_positions_m.size()));
    const auto after_control = control.step(followup_dt, zeroLoad(d.reference_positions_m.size()));
    require(
        after_failed.accepted && after_control.accepted &&
            sameSphere(failed.sphere(), control.sphere()) &&
            samePatch(failed.material().patch().state(), control.material().patch().state()) &&
            sameDynamic(failed.material().state(), control.material().state()),
        "failed interval must restore Velocity Verlet cached forces for an identical continuation");
    near(after_failed.numerical_energy_balance_residual_j,
         after_control.numerical_energy_balance_residual_j, 0,
         "restored Velocity Verlet continuation energy report");
}

void realMaterialsUseCommonAdaptiveControls() {
    SmallStrainLaw oak{.kind = SmallStrainLawKind::OrthotropicElastic,
                       .young_modulus_pa = {12e9, 1.2e9, .8e9},
                       .poisson_xy_yz_zx = {.10, .10, .005},
                       .shear_xy_yz_zx_pa = {.8e9, .35e9, .55e9},
                       .maximum_total_strain_norm = .05};
    SmallStrainLaw iron;
    iron.kind = SmallStrainLawKind::J2Plastic;
    iron.j2 = {.young_modulus_pa = 211e9,
               .poisson_ratio = .3,
               .initial_yield_stress_pa = 250e6,
               .isotropic_hardening_modulus_pa = 1e9,
               .maximum_total_strain_norm = .05};
    iron.maximum_total_strain_norm = .05;
    struct Case {
        const char *name;
        SmallStrainLaw law;
        double density;
    };
    const std::vector<Case> cases{
        {"glass", elastic(70e9), 2500}, {"oak", oak, 700}, {"iron", iron, 7870}};
    SpherePatchAdvanceOptions common;
    common.error = {.position_m = 1e-6,
                    .velocity_m_s = 1,
                    .strain = .01,
                    .energy_disagreement_j = 1e-3,
                    .absolute_energy_residual_j = 1e-3,
                    .reference_time_s = 1e-6};
    common.initial_trial_dt_s = 5e-8;
    common.maximum_trial_dt_s = 5e-8;
    common.minimum_trial_dt_s = 1e-11;
    for (const auto integrator :
         {DynamicPatchIntegrator::SymplecticEuler, DynamicPatchIntegrator::VelocityVerlet})
        for (const auto &c : cases) {
            auto d = brick(c.law, c.density);
            SpherePatchWorld world(d, {{.007, .032000001, .009}, {0, -.1, 0}, {}, .012, .056954},
                                   {.integrator = integrator});
            const auto report =
                world.advance(2e-7, zeroLoad(d.reference_positions_m.size()), common);
            if (!(report.accepted && report.impulse_contacts > 0))
                throw std::runtime_error(
                    std::string(c.name) +
                    " adaptive contact: accepted=" + std::to_string(report.accepted) +
                    " contacts=" + std::to_string(report.impulse_contacts) + " error='" +
                    report.error + "' normalized=" + std::to_string(report.last_error.normalized));
            require(magnitude(report.momentum_residual_kg_m_s) < 1e-9,
                    "real material adaptive momentum ledger");
            std::cout << "[INFO] adaptive "
                      << (integrator == DynamicPatchIntegrator::VelocityVerlet ? "VV "
                                                                               : "symplectic ")
                      << c.name << " segments=" << report.accepted_segments
                      << " energy_abs=" << report.absolute_energy_residual_j << '\n';
        }
}

void fullVelocityVerletImpactMeetsAbsoluteEnergyBudget() {
    for (bool plastic : {false, true}) {
        const auto law = plastic ? j2() : elastic();
        auto d = brick(law);
        constexpr double radius = .012;
        const double mass = 4. / 3 * std::acos(-1.) * radius * radius * radius * 7870;
        SpherePatchWorld world(
            d, {{.007, .0325, .009}, {}, {}, radius, mass},
            {.integrator = DynamicPatchIntegrator::VelocityVerlet},
            {.friction_coefficient = .15, .contact_margin_m = 1e-6, .maximum_penetration_m = 1e-5});
        auto load = zeroLoad(d.reference_positions_m.size());
        load.gravity_m_s2 = {0, -9.81, 0};
        SpherePatchAdvanceOptions o;
        o.error = {.position_m = 1e-4,
                   .velocity_m_s = 1,
                   .strain = .1,
                   .energy_disagreement_j = 1e-4,
                   .absolute_energy_residual_j = 3e-6,
                   .reference_time_s = .1};
        o.initial_trial_dt_s = std::min(1e-4, world.material().stableTimeStepLimitS());
        o.maximum_trial_dt_s = world.material().stableTimeStepLimitS();
        o.minimum_trial_dt_s = 1e-11;
        o.maximum_reserved_element_visits = 100000000;
        o.maximum_geometry_queries = 100000000;
        o.maximum_geometry_iterations = 100000000;
        double elapsed = 0, absolute_residual = 0, maximum_motion = 0;
        std::uint64_t calls = 0, contacts = 0;
        for (unsigned chunk = 1; chunk <= 100; ++chunk) {
            require(calls < 200000, "full VV regression must stay inside global step-call budget");
            o.maximum_step_calls = static_cast<unsigned>(200000 - calls);
            const double end = chunk * .001;
            const auto report = world.advance(end - elapsed, load, o, {}, load.gravity_m_s2);
            require(report.accepted,
                    "full VV impact chunk must accept under declared error budget");
            calls += report.step_calls;
            contacts += report.impulse_contacts;
            absolute_residual += report.absolute_energy_residual_j;
            elapsed = end;
            o.initial_trial_dt_s = report.suggested_trial_dt_s;
            for (Vec3 u : world.material().patch().state().displacements_m)
                maximum_motion = std::max(maximum_motion, length(u));
        }
        require(elapsed == .1 && calls <= 200000 && contacts > 0 && maximum_motion > 1e-8,
                "full VV impact must complete, contact, and deform actual patch geometry within "
                "work bound");
        require(absolute_residual <= 3e-6, "sum of absolute interval energy residuals must remain "
                                           "inside explicit 3 microjoule budget");
        double maximum_plastic = 0;
        for (const auto &state : world.material().patch().state().material_points)
            maximum_plastic = std::max(maximum_plastic, state.equivalent_plastic_strain);
        require(plastic ? maximum_plastic > 0 : maximum_plastic == 0,
                "fictional elastic/J2 histories must match their declared constitutive kinds");

        const auto positions = world.material().patch().positionsM();
        const auto &velocities = world.material().velocitiesMPerS();
        double minimum_gap = std::numeric_limits<double>::infinity(), closing_at_min = 0;
        for (const auto &face : world.material().patch().boundaryTriangles()) {
            const std::array<Vec3, 3> triangle{positions[face[0]], positions[face[1]],
                                               positions[face[2]]};
            const auto closest = closestPointOnTriangle(world.sphere().center_m, triangle);
            require(closest.resolved, "final VV surface geometry must remain queryable");
            const double gap = closest.distance_m - radius;
            if (gap < minimum_gap) {
                minimum_gap = gap;
                Vec3 surface_velocity{};
                for (unsigned i = 0; i < 3; ++i)
                    surface_velocity += closest.barycentric[i] * velocities[face[i]];
                const Vec3 lever = closest.position_world_m - world.sphere().center_m;
                const Vec3 relative = world.sphere().velocity_m_s +
                                      cross(world.sphere().spin_rad_s, lever) - surface_velocity;
                closing_at_min = dot(relative, closest.normal_triangle_to_query);
            }
        }
        if (minimum_gap <= 2e-6)
            require(closing_at_min >= -1e-5,
                    "final touching VV state cannot retain significant inward normal velocity");
        std::cout << "[INFO] full VV " << (plastic ? "fictional J2" : "fictional elastic")
                  << " calls=" << calls << " contacts=" << contacts
                  << " abs_energy=" << absolute_residual << " peak_u=" << maximum_motion
                  << " final_gap=" << minimum_gap << " final_vn=" << closing_at_min << '\n';
    }
}
} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"free flight oracle", freeFlightIsExactIndependentOfAdaptiveSegmentation},
        {"Velocity Verlet constant gravity oracle", velocityVerletConstantGravityIsExact},
        {"stricter budget refines", stricterBudgetForcesRefinement},
        {"interval rollback after tentative progress",
         intervalFailureRollsBackTentativeSegmentsExactly},
        {"plastic history rollback", plasticHistorySurvivesRejectedContinuation},
        {"Velocity Verlet cached-force rollback", velocityVerletRollbackRestoresCachedForceState},
        {"glass oak iron common adaptive controls", realMaterialsUseCommonAdaptiveControls},
        {"full Velocity Verlet impact budget", fullVelocityVerletImpactMeetsAbsoluteEnergyBudget}};
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
