#include "physics/SpherePatchWorld.hpp"

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

void require(bool condition, std::string_view message) {
    if (!condition)
        throw std::runtime_error(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": actual=" + std::to_string(actual) +
                                 " expected=" + std::to_string(expected));
}

double magnitude(Vec3 value) {
    return std::sqrt(dot(value, value));
}

SmallStrainLaw elasticLaw(double young = 5.e5) {
    constexpr double poisson = .25;
    const double shear = young / (2 * (1 + poisson));
    return {.kind = SmallStrainLawKind::IsotropicElastic,
            .young_modulus_pa = {young, young, young},
            .poisson_xy_yz_zx = {poisson, poisson, poisson},
            .shear_xy_yz_zx_pa = {shear, shear, shear},
            .maximum_total_strain_norm = .08};
}

PatchDefinition brickWithMaterial(bool supported, PatchMaterial material) {
    auto definition = makeTetrahedralBrick({.08, .02, .08}, {2, 1, 2}, material);
    if (supported) {
        for (std::size_t i = 0; i < definition.reference_positions_m.size(); ++i)
            if (definition.reference_positions_m[i].y == 0)
                definition.fixed_components[i] = {true, true, true};
    }
    return definition;
}

PatchDefinition brick(bool supported, double young = 5.e5, double density = 1000) {
    return brickWithMaterial(supported, {elasticLaw(young), density});
}

PatchDefinition fullyFixedBrick() {
    auto definition = brick(false);
    for (auto &fixed : definition.fixed_components)
        fixed = {true, true, true};
    return definition;
}

DynamicPatchLoad zeroLoad(std::size_t count) {
    DynamicPatchLoad load;
    load.nodal_forces_n.resize(count);
    return load;
}

PatchSphere approachingSphere(Vec3 velocity = {0, -.2, 0}) {
    return {{.007, .03200001, .009}, velocity, {}, .012, .002};
}

bool sameVectorsExactly(const std::vector<Vec3> &a, const std::vector<Vec3> &b) {
    if (a.size() != b.size())
        return false;
    for (std::size_t i = 0; i < a.size(); ++i)
        if (a[i].x != b[i].x || a[i].y != b[i].y || a[i].z != b[i].z)
            return false;
    return true;
}

bool sameSphereExactly(const PatchSphere &a, const PatchSphere &b) {
    return a.center_m.x == b.center_m.x && a.center_m.y == b.center_m.y &&
           a.center_m.z == b.center_m.z && a.velocity_m_s.x == b.velocity_m_s.x &&
           a.velocity_m_s.y == b.velocity_m_s.y && a.velocity_m_s.z == b.velocity_m_s.z &&
           a.spin_rad_s.x == b.spin_rad_s.x && a.spin_rad_s.y == b.spin_rad_s.y &&
           a.spin_rad_s.z == b.spin_rad_s.z && a.radius_m == b.radius_m && a.mass_kg == b.mass_kg;
}

bool samePatchStateExactly(const PatchState &a, const PatchState &b) {
    return sameVectorsExactly(a.displacements_m, b.displacements_m) &&
           a.material_points == b.material_points &&
           sameVectorsExactly(a.last_nodal_forces_n, b.last_nodal_forces_n) &&
           a.accumulated_trapezoidal_external_work_j == b.accumulated_trapezoidal_external_work_j &&
           a.accumulated_backward_euler_external_work_j ==
               b.accumulated_backward_euler_external_work_j &&
           a.revision == b.revision;
}

bool sameDynamicStateExactly(const DynamicPatchState &a, const DynamicPatchState &b) {
    return sameVectorsExactly(a.velocities_m_s, b.velocities_m_s) && a.time_s == b.time_s &&
           a.revision == b.revision &&
           a.accumulated_external_force_work_j == b.accumulated_external_force_work_j &&
           a.accumulated_support_impulse_n_s.x == b.accumulated_support_impulse_n_s.x &&
           a.accumulated_support_impulse_n_s.y == b.accumulated_support_impulse_n_s.y &&
           a.accumulated_support_impulse_n_s.z == b.accumulated_support_impulse_n_s.z;
}

void fastApproachDoesNotTunnelAndImpulseIsRepulsive() {
    auto definition = fullyFixedBrick();
    SpherePatchWorld world(definition, approachingSphere({0, -500, 0}));
    const double dt = world.material().stableTimeStepLimitS() * .2;
    require(500 * dt > .02 + 2 * .012,
            "fixture ballistic path must cross the entire patch and sphere diameter");
    const auto report = world.step(dt, zeroLoad(definition.reference_positions_m.size()));
    require(report.accepted, "bounded swept impact must be accepted");
    require(report.impulse_contacts > 0 && !report.contacts.empty(),
            "swept impact must produce a recorded contact");
    require(report.minimum_gap_m >= -1.01e-7,
            "accepted sphere must not tunnel through the triangle face");
    require(report.contacts.front().estimated_time_s >= 0 &&
                report.contacts.front().estimated_time_s <= dt,
            "contact time must lie inside the step");
    require(report.contacts.front().impulse_to_sphere_n_s.y > 0,
            "top-face contact impulse must oppose the approaching velocity");
    require(world.sphere().center_m.y >= .02 + world.sphere().radius_m - 1.01e-7,
            "fully fixed face must stop the sphere above its top surface");
    require(report.material.stored_free_energy_j == 0 && report.material.kinetic_energy_j == 0,
            "fully fixed no-tunnel control cannot hide impact energy in deformation");
    std::cout << "[INFO] swept face dt=" << dt << " gap=" << report.minimum_gap_m
              << " impulse_y=" << report.contacts.front().impulse_to_sphere_n_s.y
              << " queries=" << report.geometry_queries << '\n';
}

void freePatchReceivesEqualMomentumAndLosesNoNegativeContactEnergy() {
    auto definition = brick(false);
    const PatchSphere initial = approachingSphere({0, -.35, 0});
    SpherePatchWorld world(definition, initial);
    const double dt = world.material().stableTimeStepLimitS() * .2;
    const auto report = world.step(dt, zeroLoad(definition.reference_positions_m.size()));
    require(report.accepted && report.impulse_contacts > 0,
            "free-patch impact must be accepted and coupled");
    const Vec3 sphere_delta =
        (world.sphere().velocity_m_s - initial.velocity_m_s) * initial.mass_kg;
    require(sphere_delta.y > 0 && report.material.linear_momentum_kg_m_s.y < 0,
            "sphere and free patch must receive opposite momentum changes");
    require(magnitude(report.linear_momentum_balance_residual_kg_m_s) < 1e-11,
            "closed free system momentum ledger must balance near roundoff");
    require(report.contact_dissipation_j >= -1e-15,
            "zero-restitution unilateral contact cannot report negative dissipation");
    std::cout << "[INFO] free transfer sphere_dp_y=" << sphere_delta.y
              << " patch_p_y=" << report.material.linear_momentum_kg_m_s.y
              << " dissipation=" << report.contact_dissipation_j
              << " momentum_residual=" << magnitude(report.linear_momentum_balance_residual_kg_m_s)
              << '\n';
}

void supportedPatchDevelopsReactionAndElasticResponse() {
    auto definition = brick(true);
    SpherePatchWorld world(definition, approachingSphere({0, -.25, 0}));
    const double dt = world.material().stableTimeStepLimitS() * .15;
    Vec3 contact_impulse{}, support_impulse{};
    double maximum_energy = 0;
    unsigned contacts = 0;
    for (unsigned i = 0; i < 24; ++i) {
        const auto report = world.step(dt, zeroLoad(definition.reference_positions_m.size()));
        require(report.accepted, "supported contact trajectory must remain in the explicit bound");
        contact_impulse = contact_impulse + report.material.coupling_impulse_n_s;
        support_impulse = support_impulse + report.material.support_impulse_n_s;
        maximum_energy = std::max(maximum_energy, report.material.stored_free_energy_j);
        contacts += report.impulse_contacts;
    }
    require(contacts > 0, "supported trajectory must make contact");
    require(contact_impulse.y < 0, "patch must receive downward contact impulse");
    require(support_impulse.y > 0, "fixed base must react against the impact load");
    require(maximum_energy > 0, "contact must excite actual elastic deformation energy");
    std::cout << "[INFO] support balance contact_y=" << contact_impulse.y
              << " support_y=" << support_impulse.y << " peak_elastic_energy=" << maximum_energy
              << '\n';
}

void tangentialContactTransfersSpinWithoutAddingEnergy() {
    auto definition = brick(true);
    const PatchSphere initial = approachingSphere({.12, -.3, 0});
    SpherePatchWorld world(definition, initial, {}, {.friction_coefficient = .6});
    const double initial_ke =
        .5 * initial.mass_kg * dot(initial.velocity_m_s, initial.velocity_m_s);
    const double dt = world.material().stableTimeStepLimitS() * .2;
    const auto report = world.step(dt, zeroLoad(definition.reference_positions_m.size()));
    require(report.accepted && report.impulse_contacts > 0,
            "oblique frictional impact must contact");
    require(std::abs(world.sphere().spin_rad_s.z) > 0,
            "tangential impulse must generate sphere spin");
    require(std::abs(world.sphere().velocity_m_s.x) < std::abs(initial.velocity_m_s.x),
            "friction must reduce sphere tangential translation");
    require(report.sphere_kinetic_energy_j <= initial_ke + 1e-13,
            "passive contact must not add sphere kinetic energy");
    std::cout << "[INFO] friction vx=" << world.sphere().velocity_m_s.x
              << " spin_z=" << world.sphere().spin_rad_s.z
              << " sphere_ke=" << report.sphere_kinetic_energy_j << '\n';
}

void frictionlessEdgeNormalsDoNotCreateSpin() {
    auto definition = brick(true);
    constexpr double offset = .012 / 1.4142135623730951 + 1e-8;
    PatchSphere sphere{{.04 + offset, .02 + offset, .009}, {-1, -1, 0}, {}, .012, .002};
    SpherePatchWorld world(definition, sphere);
    const double dt = world.material().stableTimeStepLimitS() * .2;
    const auto report = world.step(dt, zeroLoad(definition.reference_positions_m.size()));
    require(report.accepted && report.impulse_contacts > 0,
            "diagonal approach must contact the rounded top edge");
    require(magnitude(world.sphere().spin_rad_s) < 1e-10,
            "frictionless normal impulses through the sphere center cannot induce spin");
    std::cout << "[INFO] frictionless edge contacts=" << report.impulse_contacts
              << " spin_norm=" << magnitude(world.sphere().spin_rad_s) << '\n';
}

void rejectedInvalidAndOverlappingStepsRollBackExactly() {
    auto definition = brick(true);
    SpherePatchWorld world(definition, approachingSphere());
    const auto sphere_before = world.sphere();
    const auto patch_before = world.material().patch().state();
    const auto dynamic_before = world.material().state();
    const auto invalid = world.step(std::numeric_limits<double>::quiet_NaN(),
                                    zeroLoad(definition.reference_positions_m.size()));
    require(!invalid.accepted, "nonfinite time step must reject");
    require(sameSphereExactly(world.sphere(), sphere_before) &&
                samePatchStateExactly(world.material().patch().state(), patch_before) &&
                sameDynamicStateExactly(world.material().state(), dynamic_before),
            "invalid step must preserve sphere and patch state exactly");

    SpherePatchWorld late(definition, approachingSphere({0, -4, 0}), {},
                          {.maximum_geometry_queries = 25});
    const auto late_sphere_before = late.sphere();
    const auto late_patch_before = late.material().patch().state();
    const auto late_dynamic_before = late.material().state();
    const auto late_report = late.step(late.material().stableTimeStepLimitS() * .2,
                                       zeroLoad(definition.reference_positions_m.size()));
    require(!late_report.accepted && late_report.impulse_contacts > 0,
            "geometry-budget failure must occur after tentative contact impulse work");
    require(sameSphereExactly(late.sphere(), late_sphere_before) &&
                samePatchStateExactly(late.material().patch().state(), late_patch_before) &&
                sameDynamicStateExactly(late.material().state(), late_dynamic_before),
            "late coupled failure must roll back sphere, velocity, material history, ledgers, and "
            "revisions");

    SpherePatchWorld iteration_limited(definition, approachingSphere({0, -4, 0}), {},
                                       {.maximum_geometry_iterations = 1});
    const auto iteration_sphere_before = iteration_limited.sphere();
    const auto iteration_patch_before = iteration_limited.material().patch().state();
    const auto iteration_dynamic_before = iteration_limited.material().state();
    const auto iteration_report =
        iteration_limited.step(iteration_limited.material().stableTimeStepLimitS() * .2,
                               zeroLoad(definition.reference_positions_m.size()));
    require(!iteration_report.accepted,
            "sweep-iteration exhaustion must reject rather than become a miss");
    require(
        sameSphereExactly(iteration_limited.sphere(), iteration_sphere_before) &&
            samePatchStateExactly(iteration_limited.material().patch().state(),
                                  iteration_patch_before) &&
            sameDynamicStateExactly(iteration_limited.material().state(), iteration_dynamic_before),
        "sweep-iteration exhaustion must preserve all coupled state");

    bool invalid_iteration_budget = false;
    try {
        SpherePatchWorld invalid_budget(definition, approachingSphere(), {},
                                        {.maximum_geometry_iterations = 0});
    } catch (const std::invalid_argument &) {
        invalid_iteration_budget = true;
    }
    require(invalid_iteration_budget, "zero sweep-iteration budget must reject at construction");

    PatchSphere overlap = approachingSphere();
    overlap.center_m.y = .02 + overlap.radius_m - 1e-4;
    bool overlap_rejected = false;
    std::string overlap_error;
    try {
        SpherePatchWorld overlapped(definition, overlap);
    } catch (const std::invalid_argument &error) {
        overlap_rejected = true;
        overlap_error = error.what();
    }
    require(overlap_rejected,
            "invalid initial overlap must reject before any coupled state exists");
    std::cout << "[INFO] rollback errors: invalid='" << invalid.error << "' late='"
              << late_report.error << "' iterations='" << iteration_report.error << "' overlap='"
              << overlap_error << "'\n";
}

void realMaterialContactsShareOneResolvedTimeStep() {
    SmallStrainLaw oak{.kind = SmallStrainLawKind::OrthotropicElastic,
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
    struct Case {
        const char *name;
        SmallStrainLaw law;
        double density;
    };
    const std::vector<Case> cases{
        {"glass", elasticLaw(70.e9), 2500}, {"oak", oak, 700}, {"iron", iron, 7870}};
    double common_dt = std::numeric_limits<double>::infinity();
    constexpr double radius = .012, iron_density = 7870;
    const double sphere_mass =
        (4.0 / 3.0) * std::acos(-1.0) * radius * radius * radius * iron_density;
    PatchSphere sphere{{.007, .02 + radius + 1e-9, .009}, {0, -.1, 0}, {}, radius, sphere_mass};
    for (const auto &entry : cases) {
        auto definition = brickWithMaterial(true, {entry.law, entry.density});
        SpherePatchWorld world(definition, sphere);
        common_dt = std::min(common_dt, world.material().stableTimeStepLimitS() * .05);
    }
    for (const auto &entry : cases) {
        auto definition = brickWithMaterial(true, {entry.law, entry.density});
        SpherePatchWorld world(definition, sphere);
        const auto report =
            world.step(common_dt, zeroLoad(definition.reference_positions_m.size()));
        require(report.accepted && report.impulse_contacts > 0,
                "real-material finite-mass sphere control must resolve contact");
        require(report.contact_dissipation_j >= -1e-15 &&
                    magnitude(report.linear_momentum_balance_residual_kg_m_s) < 1e-10,
                "real-material contact ledgers must remain passive and balanced");
        std::cout << "[INFO] " << entry.name << " density=" << entry.density
                  << " stable_dt=" << world.material().stableTimeStepLimitS()
                  << " common_dt=" << common_dt
                  << " impulse_y=" << report.contacts.front().impulse_to_sphere_n_s.y << '\n';
    }
}

double fullDropNormalizedEnergyResidual(double fraction) {
    auto definition = brick(true, 1.e6, 1000);
    constexpr double radius = .012, density = 7870, duration = .1;
    const double mass = (4.0 / 3.0) * std::acos(-1.0) * radius * radius * radius * density;
    SpherePatchWorld world(definition, {{.007, .0325, .009}, {}, {}, radius, mass}, {},
                           {.contact_margin_m = 1e-6, .maximum_penetration_m = 1e-5});
    const double nominal_dt = world.material().stableTimeStepLimitS() * fraction;
    double elapsed = 0, residual = 0, external_work = 0, contact_loss = 0;
    SpherePatchReport report;
    while (elapsed < duration) {
        const double dt = std::min(nominal_dt, duration - elapsed);
        auto load = zeroLoad(definition.reference_positions_m.size());
        load.gravity_m_s2 = {0, -9.81, 0};
        report = world.step(dt, load, {}, {0, -9.81, 0});
        require(report.accepted, "full-duration refinement trajectory must complete");
        elapsed += dt;
        residual += report.numerical_energy_balance_residual_j;
        external_work += report.external_work_j;
        contact_loss += report.contact_dissipation_j;
    }
    const double final_energy = report.sphere_kinetic_energy_j + report.material.kinetic_energy_j +
                                report.material.stored_free_energy_j;
    return std::abs(residual) /
           std::max(1e-30, std::abs(external_work) + contact_loss + final_energy);
}

void fullDropEnergyLedgerConvergesWithTimeStep() {
    const double coarse = fullDropNormalizedEnergyResidual(.05);
    const double fine = fullDropNormalizedEnergyResidual(.0125);
    std::cout << "[INFO] full 0.1 s normalized energy residual dt=.05: " << coarse
              << " dt=.0125: " << fine << '\n';
    require(fine < coarse * .5,
            "full coupled trajectory energy ledger must improve materially under refinement");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"swept supported face prevents tunneling", fastApproachDoesNotTunnelAndImpulseIsRepulsive},
        {"free patch momentum and contact energy",
         freePatchReceivesEqualMomentumAndLosesNoNegativeContactEnergy},
        {"support reaction and elastic response", supportedPatchDevelopsReactionAndElasticResponse},
        {"friction transfers tangential motion to spin",
         tangentialContactTransfersSpinWithoutAddingEnergy},
        {"frictionless edge normals preserve zero spin", frictionlessEdgeNormalsDoNotCreateSpin},
        {"coupled rejection rollback", rejectedInvalidAndOverlappingStepsRollBackExactly},
        {"glass oak iron resolved contact controls", realMaterialContactsShareOneResolvedTimeStep},
        {"full drop energy refinement", fullDropEnergyLedgerConvergesWithTimeStep},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size() << " tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
