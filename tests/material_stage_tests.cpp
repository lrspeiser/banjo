#include "fracture/BrittleBondSolver.hpp"
#include "physics/MechanicalAccounting.hpp"

#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
using namespace banjo;
void require(bool result, const char *message) {
    if (!result) throw std::runtime_error(message);
}
void near(double actual, double expected, double tolerance, const char *message) {
    require(std::isfinite(actual) && std::abs(actual - expected) <= tolerance, message);
}
struct Pair {
    LatticeAsset asset;
    ActiveMatter matter;
    Pair() {
        asset.recipe.voxel_size_m = .01;
        asset.nodes.resize(2);
        asset.bonds.push_back({.node_a = 0, .node_b = 1, .rest_length_m = 1,
            .compliance = 1e-5, .damage_start_stretch = .001, .damage_end_stretch = .002,
            .compression_damage_start_strain = std::numeric_limits<double>::infinity(),
            .compression_damage_end_strain = std::numeric_limits<double>::infinity(),
            .shear_damage_start_strain = std::numeric_limits<double>::infinity(),
            .shear_damage_end_strain = std::numeric_limits<double>::infinity()});
        asset.adjacency_offsets = {0, 1, 2};
        asset.adjacent_bond_indices = {0, 0};
        matter.asset = &asset;
        matter.nodes = {{{-.5, 0, 0}, {}, {-.2, 0, 0}, 1, {}},
                        {{ .5, 0, 0}, {}, { .2, 0, 0}, 1, {}}};
        matter.reference_positions_world_m = {{-.5, 0, 0}, {.5, 0, 0}};
        matter.bonds.resize(1);
    }
};

void predictedStrainIsNotFailureState() {
    for (const double dt : {.0025, .005, .01, .02}) {
    for (const unsigned iterations : {1U, 4U, 12U}) {
    Pair pair;
    BrittleBondSolver solver({.substeps = 1, .constraint_iterations = iterations,
        .support_enabled = false, .audit_stages = true});
    const auto before = measureMaterialMechanics(pair.matter);
    const auto stats = solver.step(pair.matter, dt, {});
    // Independent one-dimensional backward-Euler spring solution, m1=m2=1.
    const double extension = dt * .4 / (1.0 + 2.0 * dt * dt / 1e-5);
    near(length(pair.matter.nodes[1].position_world_m - pair.matter.nodes[0].position_world_m) - 1,
         extension, 1e-12, "spring position must match the implicit reference");
    require(stats.maximum_tensile_stretch < .001, "only solved strain may drive damage");
    require(pair.matter.bonds[0].alive && pair.matter.bonds[0].damage == 0,
            "a predictor above failure cannot break a solved elastic bond");
    const auto after = measureMaterialMechanics(pair.matter);
    require(after.mechanicalEnergy() <= before.mechanicalEnergy() + 1e-12,
            "passive implicit spring update must not create energy");
    const double expected_kinetic = std::pow(extension / (2 * dt), 2);
    const double expected_elastic = .5 * extension * extension / 1e-5;
    near(after.kinetic_energy_j, expected_kinetic, 1e-12, "implicit reference kinetic energy");
    near(after.elastic_energy_j, expected_elastic, 1e-12, "implicit reference stored energy");
    const auto &prediction = stats.stage_changes[static_cast<std::size_t>(MaterialStage::Prediction)];
    near(prediction.elastic_energy_j, .5 * std::pow(dt * .4, 2) / 1e-5, 1e-10,
         "temporary predicted spring energy must be visible");
    MaterialStageChange sum;
    for (const auto &stage : stats.stage_changes) sum += stage;
    near(sum.mechanicalEnergy(), after.mechanicalEnergy() - before.mechanicalEnergy(), 1e-10,
         "all numerical stages must telescope to the measured step change");
    near(length(sum.linear_momentum_kg_m_s), 0, 1e-12, "isolated spring linear momentum");
    near(length(sum.angular_momentum_kg_m2_s), 0, 1e-12, "collinear spring angular momentum");
    }
    }
}

void resolvedFailureStillBreaks() {
    Pair pair;
    pair.matter.nodes[1].position_world_m.x += .01;
    pair.matter.nodes[0].velocity_m_s = {};
    pair.matter.nodes[1].velocity_m_s = {};
    BrittleBondSolver solver({.substeps = 1, .constraint_iterations = 1,
        .support_enabled = false, .audit_stages = true});
    const auto stats = solver.step(pair.matter, 1e-5, {});
    require(!pair.matter.bonds[0].alive && stats.broken_bonds_this_step == 1,
            "resolved strain above the failure limit must still break");
    near(stats.unassigned_bond_removal_energy_j,
         .5 * std::pow(.01 / (1 + 2e-5), 2) / 1e-5, 1e-10,
         "removed energy must equal spring energy at solved failure state");
    near(stats.stage_changes[static_cast<std::size_t>(MaterialStage::Damage)].mechanicalEnergy(),
         -stats.unassigned_bond_removal_energy_j, 1e-12, "damage stage must expose removed energy");
}

void gravityAndSupportHaveDistinctBudgets() {
    Pair pair;
    pair.asset.nodes.resize(1);
    pair.asset.bonds.clear();
    pair.asset.adjacency_offsets = {0, 0};
    pair.asset.adjacent_bond_indices.clear();
    pair.matter.nodes = {{{0, -.01, 0}, {}, {2, -1, 0}, 1, {}}};
    pair.matter.reference_positions_world_m = {{0, -.01, 0}};
    pair.matter.bonds.clear();
    BrittleBondSolver solver({.substeps = 1, .constraint_iterations = 1,
        .use_support_plane = true, .support_plane = makeSupportPlane({}, {0, 1, 0}),
        .surface_dynamic_friction = .2, .surface_restitution = .5,
        .surface_static_friction = .3, .support_enabled = true, .audit_stages = true});
    const Vec3 gravity{0, -10, 0};
    const auto before = measureMaterialMechanics(pair.matter, gravity);
    const auto stats = solver.step(pair.matter, .001, gravity);
    const auto after = measureMaterialMechanics(pair.matter, gravity);
    const auto &kick = stats.stage_changes[static_cast<std::size_t>(MaterialStage::Gravity)];
    const auto &drift = stats.stage_changes[static_cast<std::size_t>(MaterialStage::Prediction)];
    const auto &support = stats.stage_changes[static_cast<std::size_t>(MaterialStage::Support)];
    near(kick.linear_momentum_kg_m_s.y, -.01, 1e-12, "material gravitational impulse");
    near(kick.kinetic_energy_j, .5 * (1.01 * 1.01 - 1), 1e-12, "gravity kick work");
    near(drift.gravity_potential_energy_j, -.0101, 1e-12, "gravity potential during drift");
    near(kick.mechanicalEnergy() + drift.mechanicalEnergy(), -.00005, 1e-12,
         "semi-implicit gravity integration loss");
    near(support.linear_momentum_kg_m_s.x, -.303, 1e-12, "support friction impulse");
    near(support.linear_momentum_kg_m_s.y, 1.515, 1e-12, "support normal impulse");
    near(support.gravity_potential_energy_j, .1101, 1e-12, "support correction changes potential");
    MaterialStageChange sum;
    for (const auto &stage : stats.stage_changes) sum += stage;
    const auto actual = MaterialStageChange::between(before, after);
    near(sum.mechanicalEnergy(), actual.mechanicalEnergy(), 1e-12, "supported step energy closure");
    near(length(sum.angular_momentum_kg_m2_s - actual.angular_momentum_kg_m2_s), 0, 1e-12,
         "supported step angular ledger closure");
}

void auditDoesNotChangePhysics() {
    Pair observed;
    Pair plain;
    BrittleBondSolver with_audit({.substeps = 2, .constraint_iterations = 3,
        .support_enabled = false, .audit_stages = true});
    BrittleBondSolver without_audit({.substeps = 2, .constraint_iterations = 3, .support_enabled = false});
    const auto measured = with_audit.step(observed.matter, .01, {});
    const auto unmeasured = without_audit.step(plain.matter, .01, {});
    require(measured.stages_measured && !unmeasured.stages_measured, "audit availability is explicit");
    for (std::size_t i = 0; i < plain.matter.nodes.size(); ++i) {
        near(length(observed.matter.nodes[i].position_world_m - plain.matter.nodes[i].position_world_m),
             0, 0, "audit must not affect positions");
        near(length(observed.matter.nodes[i].velocity_m_s - plain.matter.nodes[i].velocity_m_s),
             0, 0, "audit must not affect velocities");
    }
}

void contactAuditIncludesFiniteSphereReaction() {
    Pair pair;
    pair.asset.nodes.resize(1);
    pair.asset.bonds.clear();
    pair.asset.adjacency_offsets = {0, 0};
    pair.asset.adjacent_bond_indices.clear();
    pair.matter.nodes = {{{1, 0, 0}, {}, {-1, 2, 0}, 1, {}}};
    pair.matter.reference_positions_world_m = {{1, 0, 0}};
    pair.matter.bonds.clear();
    CoupledSphereState sphere{{}, 1, 2, .8};
    BrittleBondSolver solver({.substeps = 1, .constraint_iterations = 1,
        .support_enabled = false, .audit_stages = true});
    const auto stats = solver.step(pair.matter, .001, {}, &sphere,
        {.static_friction = .6, .dynamic_friction = .5, .restitution = .2});
    const auto &contact = stats.stage_changes[static_cast<std::size_t>(MaterialStage::PreContact)];
    // Normal impulse .8; sliding friction impulse .4. Translational and
    // rotational KE after the impulse is 1.6 J versus the initial 2.5 J.
    near(contact.kinetic_energy_j, -.9, 1e-12, "contact includes sphere translational and spin energy");
    near(length(contact.linear_momentum_kg_m_s), 0, 1e-12, "contact ledger includes linear reaction");
    near(length(contact.angular_momentum_kg_m2_s), 0, 1e-12, "contact ledger includes angular reaction");
}
}
int main() {
    try {
        predictedStrainIsNotFailureState();
        std::cout << "[PASS] predictor strain does not cause failure\n";
        resolvedFailureStillBreaks();
        std::cout << "[PASS] solved failure retains measured removed energy\n";
        gravityAndSupportHaveDistinctBudgets();
        std::cout << "[PASS] gravity and support stage references\n";
        auditDoesNotChangePhysics();
        std::cout << "[PASS] optional audit preserves the trajectory\n";
        contactAuditIncludesFiniteSphereReaction();
        std::cout << "[PASS] contact audit includes the finite sphere reaction\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
