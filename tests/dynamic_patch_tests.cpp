#include "physics/DynamicPatch.hpp"

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

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": actual=" +
            std::to_string(actual) + " expected=" + std::to_string(expected));
}

void nearVec(Vec3 actual, Vec3 expected, double tolerance, std::string_view message) {
    near(actual.x, expected.x, tolerance, message);
    near(actual.y, expected.y, tolerance, message);
    near(actual.z, expected.z, tolerance, message);
}

SmallStrainLaw elasticLaw(double young = 1.e6) {
    constexpr double poisson = .25;
    const double shear = young / (2 * (1 + poisson));
    return {.kind = SmallStrainLawKind::IsotropicElastic,
            .young_modulus_pa = {young, young, young},
            .poisson_xy_yz_zx = {poisson, poisson, poisson},
            .shear_xy_yz_zx_pa = {shear, shear, shear},
            .maximum_total_strain_norm = .1};
}

SmallStrainLaw j2Law() {
    constexpr double young = 1.e6, poisson = .25;
    const J2Material material{
        .young_modulus_pa = young,
        .poisson_ratio = poisson,
        .initial_yield_stress_pa = 1000,
        .isotropic_hardening_modulus_pa = 1.e4,
        .maximum_total_strain_norm = .1};
    return {.kind = SmallStrainLawKind::J2Plastic,
            .j2 = material,
            .young_modulus_pa = {young, young, young},
            .poisson_xy_yz_zx = {poisson, poisson, poisson},
            .shear_xy_yz_zx_pa = {young / (2 * (1 + poisson)),
                                   young / (2 * (1 + poisson)),
                                   young / (2 * (1 + poisson))},
            .maximum_total_strain_norm = .1};
}

PatchDefinition oneTet(SmallStrainLaw law, bool oscillator = false,
                       double density = 1000) {
    PatchDefinition definition;
    definition.reference_positions_m = {{0,0,0}, {1,0,0}, {0,1,0}, {0,0,1}};
    definition.elements = {{{0,1,2,3}, 0}};
    definition.materials = {{law, density}};
    definition.fixed_components.resize(4);
    if (oscillator) {
        for (auto &fixed : definition.fixed_components) fixed = {true,true,true};
        definition.fixed_components[1][0] = false;
    }
    return definition;
}

DynamicPatchLoad zeroLoad(std::size_t nodes) {
    DynamicPatchLoad load;
    load.nodal_forces_n.resize(nodes);
    return load;
}

bool sameVectorsExactly(const std::vector<Vec3> &a, const std::vector<Vec3> &b) {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i)
        if (a[i].x != b[i].x || a[i].y != b[i].y || a[i].z != b[i].z)
            return false;
    return true;
}

bool samePatchStateExactly(const PatchState &a, const PatchState &b) {
    return sameVectorsExactly(a.displacements_m, b.displacements_m) &&
        a.material_points == b.material_points &&
        sameVectorsExactly(a.last_nodal_forces_n, b.last_nodal_forces_n) &&
        a.accumulated_trapezoidal_external_work_j ==
            b.accumulated_trapezoidal_external_work_j &&
        a.accumulated_backward_euler_external_work_j ==
            b.accumulated_backward_euler_external_work_j &&
        a.revision == b.revision;
}

bool sameDynamicStateExactly(const DynamicPatchState &a,
                             const DynamicPatchState &b) {
    return sameVectorsExactly(a.velocities_m_s, b.velocities_m_s) &&
        a.time_s == b.time_s &&
        a.accumulated_external_force_work_j == b.accumulated_external_force_work_j &&
        a.accumulated_support_impulse_n_s.x == b.accumulated_support_impulse_n_s.x &&
        a.accumulated_support_impulse_n_s.y == b.accumulated_support_impulse_n_s.y &&
        a.accumulated_support_impulse_n_s.z == b.accumulated_support_impulse_n_s.z &&
        a.revision == b.revision;
}

void uniformTranslationHasZeroStrainAndConstantMomentum() {
    DynamicPatch dynamic(oneTet(elasticLaw()));
    const Vec3 velocity{.7, -.2, .4};
    dynamic.setVelocitiesMPerS(std::vector<Vec3>(4, velocity));
    const double dt = dynamic.stableTimeStepLimitS() * .25;
    for (unsigned step = 0; step < 20; ++step)
        require(dynamic.step(dt, zeroLoad(4)).accepted,
                "uniform translation step must be accepted");
    for (Vec3 displacement : dynamic.patch().state().displacements_m)
        nearVec(displacement, velocity * (20 * dt), 1.e-13,
                "uniform translation must remain affine-constant");
    near(dynamic.report().stored_free_energy_j, 0, 1.e-18,
         "uniform translation must have zero strain energy");
    nearVec(dynamic.report().linear_momentum_kg_m_s,
            dynamic.patch().massKg() * velocity, 1.e-11,
            "uniform translation momentum must remain constant");
}

void freeFallMatchesSymplecticEulerMomentum() {
    DynamicPatch dynamic(oneTet(elasticLaw()));
    DynamicPatchLoad load = zeroLoad(4);
    load.gravity_m_s2 = {0, -9.81, 0};
    const double dt = dynamic.stableTimeStepLimitS() * .2;
    constexpr unsigned steps = 12;
    DynamicPatchReport result;
    for (unsigned i = 0; i < steps; ++i) {
        result = dynamic.step(dt, load);
        require(result.accepted, "free-fall step must be accepted");
    }
    nearVec(result.linear_momentum_kg_m_s,
            dynamic.patch().massKg() * load.gravity_m_s2 * (steps * dt),
            1.e-10, "gravity impulse must equal momentum change");
    nearVec(result.linear_momentum_balance_residual_kg_m_s, {}, 1.e-12,
            "free-fall momentum ledger must close to roundoff");
    const double expected_y = -.5 * 9.81 * dt * dt * steps * (steps + 1);
    for (Vec3 displacement : dynamic.patch().state().displacements_m)
        near(displacement.y, expected_y, 1.e-13,
             "free fall must match symplectic Euler position sequence");
}

void rejectedStepsRollBackEveryStateField() {
    DynamicPatch dynamic(oneTet(elasticLaw()));
    dynamic.setVelocitiesMPerS(std::vector<Vec3>(4, {.1,0,0}));
    const PatchState patch_before = dynamic.patch().state();
    const DynamicPatchState dynamic_before = dynamic.state();
    auto bad = zeroLoad(4);
    bad.nodal_forces_n[2].x = std::numeric_limits<double>::quiet_NaN();
    require(!dynamic.step(dynamic.stableTimeStepLimitS() * .5, bad).accepted,
            "nonfinite force must reject");
    require(samePatchStateExactly(dynamic.patch().state(), patch_before) &&
            sameDynamicStateExactly(dynamic.state(), dynamic_before),
            "invalid load rejection must preserve dynamic and material state exactly");
    require(!dynamic.step(dynamic.stableTimeStepLimitS() * 1.01, zeroLoad(4)).accepted,
            "oversized stable time step must reject");
    require(samePatchStateExactly(dynamic.patch().state(), patch_before) &&
            sameDynamicStateExactly(dynamic.state(), dynamic_before),
            "stability rejection must preserve state exactly");

    require(dynamic.step(dynamic.stableTimeStepLimitS() * .25, zeroLoad(4)).accepted,
            "fixture valid step must be accepted");
    bool rejected_late_velocity = false;
    try { dynamic.setVelocitiesMPerS(std::vector<Vec3>(4)); }
    catch (const std::invalid_argument &) { rejected_late_velocity = true; }
    require(rejected_late_velocity,
            "velocity replacement after stepping must reject unaccounted momentum injection");
}

double oscillatorError(unsigned divisor, double duration, double reference_x,
                       double reference_v) {
    DynamicPatch dynamic(oneTet(elasticLaw(), true));
    std::vector<Vec3> velocity(4); velocity[1].x = .01;
    dynamic.setVelocitiesMPerS(velocity);
    const double requested = dynamic.stableTimeStepLimitS() / divisor;
    const unsigned steps = static_cast<unsigned>(std::ceil(duration / requested));
    const double dt = duration / steps;
    for (unsigned i = 0; i < steps; ++i)
        require(dynamic.step(dt, zeroLoad(4)).accepted, "oscillator step must be accepted");
    const double x = dynamic.patch().state().displacements_m[1].x;
    const double v = dynamic.state().velocities_m_s[1].x;
    return std::hypot(x - reference_x,
                      dynamic.stableTimeStepLimitS() * (v - reference_v));
}

void elasticOscillationRefinesWithTimeStep() {
    DynamicPatch scale(oneTet(elasticLaw(), true));
    constexpr double young = 1.e6, poisson = .25, density = 1000, initial_v = .01;
    const double lambda = young * poisson / ((1 + poisson) * (1 - 2 * poisson));
    const double mu = young / (2 * (1 + poisson));
    // For the unit tetrahedron with only node 1 x free,
    // k=(lambda+2mu)/6 and lumped m=rho/24.
    const double omega = std::sqrt(4 * (lambda + 2 * mu) / density);
    const double duration = scale.stableTimeStepLimitS() * 20;
    const double exact_x = initial_v * std::sin(omega * duration) / omega;
    const double exact_v = initial_v * std::cos(omega * duration);
    const double coarse = oscillatorError(4, duration, exact_x, exact_v);
    const double fine = oscillatorError(16, duration, exact_x, exact_v);
    std::cout << "[INFO] elastic oscillator dt limits: coarse="
              << scale.stableTimeStepLimitS() / 4 << " fine="
              << scale.stableTimeStepLimitS() / 16 << " errors="
              << coarse << ',' << fine << '\n';
    require(fine < coarse,
            "elastic oscillator trajectory error must decrease under time refinement");
}

void matchedMaterialTranslationControls() {
    SmallStrainLaw oak{
        .kind = SmallStrainLawKind::OrthotropicElastic,
        .young_modulus_pa = {12.e9, 1.2e9, .8e9},
        .poisson_xy_yz_zx = {.10, .10, .005},
        .shear_xy_yz_zx_pa = {.80e9, .35e9, .55e9},
        .maximum_total_strain_norm = .05};
    SmallStrainLaw iron;
    iron.kind = SmallStrainLawKind::J2Plastic;
    iron.j2 = {.young_modulus_pa = 211.e9,
               .poisson_ratio = .30,
               .initial_yield_stress_pa = 250.e6,
               .isotropic_hardening_modulus_pa = 1.e9,
               .maximum_total_strain_norm = .05};
    iron.maximum_total_strain_norm = .05;
    struct Case { const char *name; SmallStrainLaw law; double density; };
    const std::vector<Case> cases{
        {"glass", elasticLaw(70.e9), 2500},
        {"oak", oak, 700},
        {"iron", iron, 7870},
    };
    constexpr Vec3 velocity{1.e-3, -2.e-3, .5e-3};
    for (const auto &entry : cases) {
        DynamicPatch dynamic(oneTet(entry.law, false, entry.density));
        dynamic.setVelocitiesMPerS(std::vector<Vec3>(4, velocity));
        const double dt = dynamic.stableTimeStepLimitS() * .1;
        const auto result = dynamic.step(dt, zeroLoad(4));
        require(result.accepted && result.stored_free_energy_j == 0 &&
                    result.plastic_dissipation_j == 0,
                std::string(entry.name) +
                    " numerical constitutive translation control must remain strain-free");
        nearVec(result.linear_momentum_kg_m_s,
                dynamic.patch().massKg() * velocity, 1.e-12,
                "matched material translation momentum");
        std::cout << "[INFO] " << entry.name << " stable dt limit="
                  << dynamic.stableTimeStepLimitS() << " s\n";
    }
}

void j2StepCommitsPositivePlasticHistory() {
    DynamicPatch dynamic(oneTet(j2Law(), true));
    const double dt = dynamic.stableTimeStepLimitS() * .25;
    std::vector<Vec3> velocity(4); velocity[1].x = .02 / dt;
    dynamic.setVelocitiesMPerS(velocity);
    const auto result = dynamic.step(dt, zeroLoad(4));
    require(result.accepted, "bounded J2 loading step must be accepted");
    require(dynamic.patch().state().material_points[0].equivalent_plastic_strain > 0 &&
            result.plastic_dissipation_j > 0,
            "J2 dynamic step must retain positive plastic history and dissipation");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"uniform translation and momentum", uniformTranslationHasZeroStrainAndConstantMomentum},
        {"free fall momentum", freeFallMatchesSymplecticEulerMomentum},
        {"transactional rejected step", rejectedStepsRollBackEveryStateField},
        {"elastic oscillation refinement", elasticOscillationRefinesWithTimeStep},
        {"glass oak iron translation controls", matchedMaterialTranslationControls},
        {"J2 persistent plastic history", j2StepCommitsPositivePlasticHistory},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "[PASS] " << name << '\n'; }
        catch (const std::exception &error) {
            ++failures; std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size() << " tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
