#include "physics/CohesiveDynamicPatch.hpp"

#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

using namespace banjo;

namespace banjo {
class CohesiveDynamicPatchTestAccess {
  public:
    static CohesiveDynamicPatchReport step(
        CohesiveDynamicPatch &patch, double dt, const std::vector<Vec3> &forces,
        const std::function<void(std::vector<Vec3> &, std::vector<Vec3> &)> &drift,
        const std::function<void(const CohesiveDynamicPatchState &,
                                 const CohesiveDynamicPatchReport &)> &verify = {}) {
        return patch.stepImpl(dt, forces, {}, drift, {}, verify);
    }
};
} // namespace banjo

namespace {

void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

void near(double actual, double expected, double tolerance, const char *message) {
    check(std::isfinite(actual) && std::abs(actual - expected) <= tolerance, message);
}

SmallStrainLaw elasticLaw() {
    return {
        .kind = SmallStrainLawKind::IsotropicElastic,
        .young_modulus_pa = {1.e5, 0, 0},
        .poisson_xy_yz_zx = {0.2, 0, 0},
        .maximum_total_strain_norm = 0.2,
    };
}

PatchDefinition twoTets() {
    PatchDefinition definition;
    definition.reference_positions_m = {
        {0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}, {0, 0, -1}};
    definition.elements = {{{0, 1, 2, 3}, 0}, {{0, 2, 1, 4}, 0}};
    definition.materials = {{elasticLaw(), 12.0}};
    definition.fixed_components.resize(definition.reference_positions_m.size());
    return definition;
}

CohesiveFacetLaw cohesiveLaw() {
    return {
        .stiffness_pa_per_m = 1.e4,
        .strength_pa = 100,
        .fracture_energy_j_m2 = 2,
        .compression_stiffness_pa_per_m = 1.e4,
        .tangential_stiffness_pa_per_m = 5.e3,
    };
}

CohesiveDynamicPatchOptions options(double energy_budget = 0.2) {
    CohesiveDynamicPatchOptions result;
    result.maximum_time_step_s = 1.e-2;
    result.maximum_displacement_gradient_norm = 0.2;
    result.maximum_absolute_energy_residual_j = energy_budget;
    return result;
}

std::vector<Vec3> openingLoad(const CohesiveDynamicPatch &patch, double force_per_node) {
    std::vector<Vec3> forces(patch.state().velocities_m_s.size());
    const auto &facet = patch.topology().internal_facets.front();
    const Vec3 normal = facet.reference_normal_a;
    for (unsigned node : patch.topology().duplicated_definition.elements[facet.side_a.tetrahedron].nodes)
        forces[node] -= force_per_node * normal;
    for (unsigned node : patch.topology().duplicated_definition.elements[facet.side_b.tetrahedron].nodes)
        forces[node] += force_per_node * normal;
    return forces;
}

struct RunResult {
    double separation_time{};
    double work{};
    double total_energy{};
    double maximum_step_residual{};
};

RunResult runOpening(double dt) {
    CohesiveDynamicPatch patch(twoTets(), {cohesiveLaw()}, options());
    const auto forces = openingLoad(patch, 80.0);
    RunResult out;
    for (unsigned step = 0; step < 2000 && out.separation_time == 0; ++step) {
        const auto report = patch.step(dt, forces);
        check(report.accepted, report.error.c_str());
        check(report.tet_evaluations == 2 && report.facet_evaluations == 1 &&
                  report.nodal_scatters == 6,
              "dynamic step must report bounded bulk and cohesive work");
        out.maximum_step_residual =
            std::max(out.maximum_step_residual, std::abs(report.numerical_energy_residual_j));
        if (report.fully_separated_facets == 1)
            out.separation_time = patch.state().time_s;
    }
    check(out.separation_time > 0, "force-driven two-tet coupon must fracture locally");
    check(patch.state().separation.components.size() == 2 &&
              patch.state().separation.newly_exposed_faces.size() == 2,
          "accepted facet failure must split connectivity and expose both sides");
    const auto report = patch.report();
    near(report.fracture_dissipation_j,
         cohesiveLaw().fracture_energy_j_m2 * 0.5, 1e-10,
         "accepted local fracture must dissipate Gc times facet area");
    out.work = report.accumulated_external_work_j;
    out.total_energy = report.kinetic_energy_j + report.bulk_stored_energy_j +
                       report.cohesive_stored_energy_j + report.fracture_dissipation_j;
    return out;
}

} // namespace

int main() {
    try {
        CohesiveDynamicPatch control(twoTets(), {cohesiveLaw()}, options(1e-8));
        std::vector<Vec3> common_velocity(control.state().velocities_m_s.size(),
                                          {0.1, -0.2, 0.05});
        control.setVelocitiesMPerS(common_velocity);
        const auto initial = control.report();
        const std::vector<Vec3> no_forces(common_velocity.size());
        for (unsigned i = 0; i < 20; ++i) {
            const auto step = control.step(1e-4, no_forces);
            check(step.accepted, step.error.c_str());
        }
        const auto translated = control.report();
        near(translated.kinetic_energy_j, initial.kinetic_energy_j, 1e-12,
             "undamaged rigid translation must preserve kinetic energy");
        near(translated.bulk_stored_energy_j + translated.cohesive_stored_energy_j,
             0.0, 1e-12, "common translation must not strain bulk or facets");
        near(translated.fracture_dissipation_j, 0.0, 0.0,
             "undamaged dynamic control must not fracture");

        auto supported_definition = twoTets();
        for (auto &fixed : supported_definition.fixed_components)
            fixed = {true, true, true};
        CohesiveDynamicPatch supported(supported_definition, {cohesiveLaw()}, options(1e-8));
        const Vec3 gravity{0, -9.81, 0};
        const std::vector<Vec3> supported_load(supported.state().velocities_m_s.size());
        const auto support_step = supported.step(1e-4, supported_load, gravity);
        check(support_step.accepted, support_step.error.c_str());
        near(length(support_step.support_impulse_n_s +
                    1e-4 * supported.massKg() * gravity),
             0.0, 1e-12,
             "fixed support impulse must balance the full gravity impulse");
        near(length(support_step.momentum_residual_kg_m_s), 0.0, 1e-12,
             "support impulse must be included in momentum balance");
        near(support_step.external_work_increment_j, 0.0, 0.0,
             "fixed loads must perform no displacement work");

        CohesiveDynamicPatch hook_rollback(twoTets(), {cohesiveLaw()}, options());
        const auto hook_before = hook_rollback.state();
        const std::vector<Vec3> hook_load(hook_before.velocities_m_s.size());
        const auto invalid_hook = CohesiveDynamicPatchTestAccess::step(
            hook_rollback, 1e-4, hook_load,
            [&](std::vector<Vec3> &velocities, std::vector<Vec3> &drift) {
                drift.assign(velocities.size(), Vec3{});
                velocities[0].x = std::numeric_limits<double>::infinity();
            });
        check(!invalid_hook.accepted && hook_rollback.state().revision == hook_before.revision,
              "nonfinite drift-hook velocity must reject before candidate evaluation");
        const auto throwing_hook = CohesiveDynamicPatchTestAccess::step(
            hook_rollback, 1e-4, hook_load,
            [&](std::vector<Vec3> &velocities, std::vector<Vec3> &drift) {
                drift.assign(velocities.size(), Vec3{});
            },
            [&](const CohesiveDynamicPatchState &, const CohesiveDynamicPatchReport &) {
                throw std::runtime_error("test verifier rejection");
            });
        check(!throwing_hook.accepted && hook_rollback.state().revision == hook_before.revision &&
                  hook_rollback.state().time_s == hook_before.time_s,
              "verifier exception must roll back motion, history, time, and ledgers");

        CohesiveDynamicPatch rollback(twoTets(), {cohesiveLaw()}, options(1e-14));
        const auto before = rollback.state();
        const auto rejected = rollback.step(
            0.9 * rollback.stableTimeStepLimitS(), openingLoad(rollback, 80.0));
        check(!rejected.accepted,
              "over-budget endpoint-force integration must reject transactionally");
        bool unchanged_displacements =
            rollback.state().displacements_m.size() == before.displacements_m.size();
        for (std::size_t i = 0; i < before.displacements_m.size(); ++i)
            unchanged_displacements = unchanged_displacements &&
                                      length(rollback.state().displacements_m[i] -
                                             before.displacements_m[i]) == 0;
        check(rollback.state().revision == before.revision &&
                  rollback.state().time_s == before.time_s && unchanged_displacements &&
                  rollback.state().facet_states[0].integration_points[0].maximum_opening_m ==
                      before.facet_states[0].integration_points[0].maximum_opening_m,
              "rejected energy trial must roll back time, motion, and facet history");
        const auto unstable = rollback.step(2 * rollback.stableTimeStepLimitS(),
                                            openingLoad(rollback, 80.0));
        check(!unstable.accepted && rollback.state().revision == before.revision,
              "stability-budget rejection must leave accepted state unchanged");

        const auto coarse = runOpening(2e-4);
        const auto fine = runOpening(1e-4);
        near(coarse.separation_time, fine.separation_time, 6e-4,
             "force-driven fracture time must refine under timestep halving");
        near(coarse.work, coarse.total_energy, 0.3,
             "coarse accepted trajectory must retain its measured work ledger");
        near(fine.work, fine.total_energy, 0.15,
             "refined accepted trajectory must improve the work ledger");
        check(fine.maximum_step_residual <= coarse.maximum_step_residual * 1.1,
              "timestep refinement must not worsen maximum endpoint-force work error");

        bool rejected_j2 = false;
        try {
            auto invalid = twoTets();
            invalid.materials[0].law = {};
            invalid.materials[0].law.kind = SmallStrainLawKind::J2Plastic;
            invalid.materials[0].law.j2 = {.young_modulus_pa = 1.e5,
                                           .poisson_ratio = 0.2,
                                           .initial_yield_stress_pa = 1000,
                                           .isotropic_hardening_modulus_pa = 0,
                                           .maximum_total_strain_norm = 0.2};
            (void)CohesiveDynamicPatch(invalid, {cohesiveLaw()}, options());
        } catch (const std::invalid_argument &) {
            rejected_j2 = true;
        }
        check(rejected_j2, "unsupported J2 bulk history must reject explicitly");

        std::cout << "[PASS] cohesive dynamic force/fracture/control/rollback/refinement\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
