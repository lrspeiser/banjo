#include "physics/SmallStrainPatch.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace banjo;

struct TestFailure : std::runtime_error {
    using std::runtime_error::runtime_error;
};

void require(bool condition, std::string_view message) {
    if (!condition) throw TestFailure(std::string(message));
}

void near(double actual, double expected, double absolute_tolerance,
          double relative_tolerance, std::string_view message) {
    const double tolerance = absolute_tolerance + relative_tolerance * std::abs(expected);
    if (!std::isfinite(actual) || !std::isfinite(expected) ||
        std::abs(actual - expected) > tolerance) {
        throw TestFailure(std::string(message) + ": actual=" + std::to_string(actual) +
                          " expected=" + std::to_string(expected));
    }
}

void nearVec(const Vec3 &actual, const Vec3 &expected, double absolute_tolerance,
             double relative_tolerance, std::string_view message) {
    near(actual.x, expected.x, absolute_tolerance, relative_tolerance, message);
    near(actual.y, expected.y, absolute_tolerance, relative_tolerance, message);
    near(actual.z, expected.z, absolute_tolerance, relative_tolerance, message);
}

void nearTensor(const SymmetricTensor3 &actual, const SymmetricTensor3 &expected,
                double absolute_tolerance, double relative_tolerance,
                std::string_view message) {
    near(actual.xx, expected.xx, absolute_tolerance, relative_tolerance, message);
    near(actual.yy, expected.yy, absolute_tolerance, relative_tolerance, message);
    near(actual.zz, expected.zz, absolute_tolerance, relative_tolerance, message);
    near(actual.xy, expected.xy, absolute_tolerance, relative_tolerance, message);
    near(actual.yz, expected.yz, absolute_tolerance, relative_tolerance, message);
    near(actual.zx, expected.zx, absolute_tolerance, relative_tolerance, message);
}

SmallStrainLaw isotropic(double young_modulus_pa = 70.e9,
                         double poisson_ratio = .22) {
    return {
        .kind = SmallStrainLawKind::IsotropicElastic,
        .young_modulus_pa = {young_modulus_pa, 0., 0.},
        .poisson_xy_yz_zx = {poisson_ratio, 0., 0.},
        .maximum_total_strain_norm = .05,
    };
}

SmallStrainLaw oakLikeOrthotropic() {
    return {
        .kind = SmallStrainLawKind::OrthotropicElastic,
        .young_modulus_pa = {12.e9, 1.2e9, .8e9},
        .poisson_xy_yz_zx = {.10, .10, .005},
        .shear_xy_yz_zx_pa = {.80e9, .35e9, .55e9},
        .maximum_total_strain_norm = .05,
    };
}

SmallStrainLaw continuumOakOrthotropic() {
    return {
        .kind = SmallStrainLawKind::OrthotropicElastic,
        .young_modulus_pa = {.7e9, 12.e9, 1.e9},
        .poisson_xy_yz_zx = {.025, .30, .30},
        .shear_xy_yz_zx_pa = {.6e9, .7e9, .1e9},
        .maximum_total_strain_norm = .05,
    };
}

SmallStrainLaw illustrativeMetalJ2() {
    SmallStrainLaw law;
    law.kind = SmallStrainLawKind::J2Plastic;
    law.j2 = {
        .family = ContinuumConstitutiveFamily::SmallStrainIsotropicJ2,
        .young_modulus_pa = 211.e9,
        .poisson_ratio = .29,
        .initial_yield_stress_pa = 250.e6,
        .isotropic_hardening_modulus_pa = 1.e9,
        .maximum_total_strain_norm = .05,
    };
    law.maximum_total_strain_norm = .05;
    return law;
}

SmallStrainLaw continuumIronJ2() {
    SmallStrainLaw law = illustrativeMetalJ2();
    law.j2.poisson_ratio = .30;
    return law;
}

PatchDefinition oneTet(PatchMaterial material, bool fixed = false) {
    PatchDefinition definition;
    definition.reference_positions_m = {
        {0., 0., 0.}, {1., 0., 0.}, {0., 1., 0.}, {0., 0., 1.}};
    definition.elements = {{{0, 1, 2, 3}, 0}};
    definition.materials = {std::move(material)};
    definition.fixed_components.assign(4, {fixed, fixed, fixed});
    return definition;
}

PatchLoad emptyLoad(std::size_t nodes) {
    return {std::vector<Vec3>(nodes), std::vector<Vec3>(nodes)};
}

Vec3 affineDisplacement(const SymmetricTensor3 &strain, const Vec3 &position) {
    return {
        strain.xx * position.x + strain.xy * position.y + strain.zx * position.z,
        strain.xy * position.x + strain.yy * position.y + strain.yz * position.z,
        strain.zx * position.x + strain.yz * position.y + strain.zz * position.z,
    };
}

std::vector<Vec3> affineDisplacements(const std::vector<Vec3> &positions,
                                      const SymmetricTensor3 &strain) {
    std::vector<Vec3> result;
    result.reserve(positions.size());
    for (const auto &position : positions) result.push_back(affineDisplacement(strain, position));
    return result;
}

std::vector<Vec3> simpleShearDisplacements(const std::vector<Vec3> &positions,
                                           double engineering_shear) {
    std::vector<Vec3> result;
    result.reserve(positions.size());
    for (const auto &position : positions)
        result.push_back({engineering_shear * position.y, 0., 0.});
    return result;
}

Vec3 sum(const std::vector<Vec3> &values) {
    Vec3 result;
    for (const auto &value : values) result += value;
    return result;
}

Vec3 referenceMoment(const std::vector<Vec3> &positions,
                     const std::vector<Vec3> &forces) {
    require(positions.size() == forces.size(), "moment inputs must have matching sizes");
    Vec3 result;
    for (std::size_t i = 0; i < positions.size(); ++i)
        result += cross(positions[i], forces[i]);
    return result;
}

bool sameVecExactly(const Vec3 &a, const Vec3 &b) {
    return a.x == b.x && a.y == b.y && a.z == b.z;
}

bool sameStateExactly(const PatchState &a, const PatchState &b) {
    if (a.displacements_m.size() != b.displacements_m.size() ||
        a.material_points != b.material_points ||
        a.last_nodal_forces_n.size() != b.last_nodal_forces_n.size() ||
        a.accumulated_trapezoidal_external_work_j !=
            b.accumulated_trapezoidal_external_work_j ||
        a.accumulated_backward_euler_external_work_j !=
            b.accumulated_backward_euler_external_work_j ||
        a.revision != b.revision)
        return false;
    for (std::size_t i = 0; i < a.displacements_m.size(); ++i)
        if (!sameVecExactly(a.displacements_m[i], b.displacements_m[i])) return false;
    for (std::size_t i = 0; i < a.last_nodal_forces_n.size(); ++i)
        if (!sameVecExactly(a.last_nodal_forces_n[i], b.last_nodal_forces_n[i])) return false;
    return true;
}

void affinePatchHasExactStrainAndSelfEquilibratedInternalForces() {
    constexpr double young = 70.e9;
    constexpr double poisson = .22;
    SmallStrainPatch patch(oneTet({isotropic(young, poisson), 2500.}));
    const SymmetricTensor3 strain{
        .xx = 2.e-4, .yy = -1.e-4, .zz = 5.e-5,
        .xy = 7.e-5, .yz = -4.e-5, .zx = 3.e-5};
    const auto displacements = affineDisplacements(
        patch.definition().reference_positions_m, strain);
    const auto evaluation = patch.evaluate(displacements);

    require(evaluation.responses.size() == 1 && evaluation.internal_forces_n.size() == 4,
            "one tetrahedron must produce one constitutive response and four nodal forces");
    nearTensor(evaluation.responses[0].state.total_strain, strain, 2.e-18, 2.e-13,
               "P1 tetrahedron must reproduce a constant affine strain exactly");
    nearVec(sum(evaluation.internal_forces_n), {}, 1.e-6, 1.e-13,
            "affine internal nodal forces must have zero resultant");
    nearVec(referenceMoment(patch.definition().reference_positions_m,
                            evaluation.internal_forces_n),
            {}, 1.e-6, 1.e-13,
            "symmetric Cauchy stress must give zero reference torque on a P1 tetrahedron");

    const double lambda = young * poisson / ((1. + poisson) * (1. - 2. * poisson));
    const double shear = young / (2. * (1. + poisson));
    const double tr = trace(strain);
    const SymmetricTensor3 expected_stress{
        .xx = lambda * tr + 2. * shear * strain.xx,
        .yy = lambda * tr + 2. * shear * strain.yy,
        .zz = lambda * tr + 2. * shear * strain.zz,
        .xy = 2. * shear * strain.xy,
        .yz = 2. * shear * strain.yz,
        .zx = 2. * shear * strain.zx,
    };
    nearTensor(evaluation.responses[0].stress_pa, expected_stress, 1.e-5, 2.e-13,
               "isotropic affine stress must match Hooke's law");
    const double expected_energy = .5 * doubleContract(expected_stress, strain) / 6.;
    near(evaluation.stored_free_energy_j, expected_energy, 1.e-8, 2.e-13,
         "tetrahedron affine energy must equal volume times analytical energy density");
    near(patch.referenceVolumeM3(), 1. / 6., 1.e-15, 1.e-15,
         "reference tetrahedron volume");
    near(patch.massKg(), 2500. / 6., 1.e-12, 1.e-15,
         "reference mass must use density and undeformed volume");
    double nodal_mass = 0.;
    for (double value : patch.nodalMassesKg()) nodal_mass += value;
    near(nodal_mass, patch.massKg(), 1.e-12, 1.e-15,
         "lumped nodal masses must conserve material mass");
}

void prescribedAffineShearMatchesEnergyReactionsAndWork() {
    constexpr double young = 72.e9;
    constexpr double poisson = .20;
    constexpr double gamma = 8.e-4;
    const double shear_modulus = young / (2. * (1. + poisson));
    const double shear_stress = shear_modulus * gamma;
    const double volume = 1. / 6.;
    SmallStrainPatch patch(oneTet({isotropic(young, poisson), 2400.}, true));
    PatchLoad load = emptyLoad(4);
    load.prescribed_displacements_m = simpleShearDisplacements(
        patch.definition().reference_positions_m, gamma);
    const auto result = patch.solveLoad(load);
    require(result.accepted && result.reactions_n.size() == 4,
            "fully prescribed affine shear must be accepted and report every nodal reaction");

    const std::vector<Vec3> expected_reactions{
        {-volume * shear_stress, -volume * shear_stress, 0.},
        {0., volume * shear_stress, 0.},
        {volume * shear_stress, 0., 0.},
        {0., 0., 0.},
    };
    for (std::size_t i = 0; i < expected_reactions.size(); ++i)
        nearVec(result.reactions_n[i], expected_reactions[i], 1.e-5, 2.e-12,
                "prescribed affine reactions must equal volume times stress times shape gradient");
    nearVec(result.support_reaction_n, {}, 1.e-5, 1.e-13,
            "self-equilibrated affine reactions have no resultant");
    nearVec(result.reference_moment_residual_n_m, {}, 1.e-5, 1.e-13,
            "affine shear reactions have no net reference moment");
    const double expected_energy = .5 * shear_modulus * gamma * gamma * volume;
    near(result.stored_free_energy_j, expected_energy, 1.e-7, 2.e-12,
         "prescribed simple-shear energy must match one-half G gamma squared times volume");
    near(result.trapezoidal_external_work_increment_j, expected_energy, 1.e-7, 2.e-12,
         "linear ramp prescribed-boundary trapezoidal work must equal stored energy");
    near(result.backward_euler_external_work_increment_j, 2. * expected_energy,
         1.e-7, 2.e-12,
         "end-reaction backward-Euler work for a zero-to-linear ramp must equal twice stored energy");
    near(result.trapezoidal_work_residual_j, 0., 1.e-7, 2.e-12,
         "elastic affine shear must close trapezoidal work balance");
}

PatchDefinition axialBrick(PatchMaterial material) {
    PatchDefinition definition = makeTetrahedralBrick({1., 1., 1.}, {1, 1, 1},
                                                       std::move(material));
    const auto &positions = definition.reference_positions_m;
    for (std::size_t i = 0; i < positions.size(); ++i) {
        if (std::abs(positions[i].y) < 1.e-14) definition.fixed_components[i][1] = true;
        if (std::abs(positions[i].x + .5) < 1.e-14 &&
            std::abs(positions[i].y) < 1.e-14 &&
            std::abs(positions[i].z + .5) < 1.e-14) {
            definition.fixed_components[i][0] = true;
            definition.fixed_components[i][2] = true;
        }
        if (std::abs(positions[i].x - .5) < 1.e-14 &&
            std::abs(positions[i].y) < 1.e-14 &&
            std::abs(positions[i].z + .5) < 1.e-14)
            definition.fixed_components[i][2] = true;
    }
    return definition;
}

double triangleArea(const Vec3 &a, const Vec3 &b, const Vec3 &c) {
    return .5 * length(cross(b - a, c - a));
}

PatchLoad axialTraction(const SmallStrainPatch &patch, double stress_pa) {
    const auto &positions = patch.definition().reference_positions_m;
    PatchLoad load = emptyLoad(positions.size());
    double loaded_area = 0.;
    for (const auto &triangle : patch.boundaryTriangles()) {
        if (std::abs(positions[triangle[0]].y - 1.) > 1.e-14 ||
            std::abs(positions[triangle[1]].y - 1.) > 1.e-14 ||
            std::abs(positions[triangle[2]].y - 1.) > 1.e-14)
            continue;
        const double area = triangleArea(positions[triangle[0]], positions[triangle[1]],
                                         positions[triangle[2]]);
        loaded_area += area;
        for (unsigned node : triangle) load.nodal_forces_n[node].y += stress_pa * area / 3.;
    }
    near(loaded_area, 1., 1.e-14, 1.e-14,
         "unit brick loaded face must have unit triangulated area");
    return load;
}

PatchSolveOptions tightSolveOptions() {
    PatchSolveOptions options;
    options.relative_force_tolerance = 2.e-10;
    options.absolute_force_tolerance_n = 1.e-5;
    return options;
}

void freeAxialTractionProducesPoissonContractionAndBalancedReactions() {
    constexpr double young = 100.e9;
    constexpr double poisson = .25;
    constexpr double stress = 1.e6;
    SmallStrainPatch patch(axialBrick({isotropic(young, poisson), 5000.}));
    const PatchLoad load = axialTraction(patch, stress);
    const auto result = patch.solveLoad(load, tightSolveOptions());
    require(result.accepted, "small uniaxial elastic traction must converge");

    const double axial_strain = stress / young;
    for (std::size_t i = 0; i < patch.definition().reference_positions_m.size(); ++i) {
        const Vec3 &x = patch.definition().reference_positions_m[i];
        const Vec3 expected{-poisson * axial_strain * (x.x + .5), axial_strain * x.y,
                            -poisson * axial_strain * (x.z + .5)};
        nearVec(patch.state().displacements_m[i], expected, 2.e-11, 2.e-7,
                "traction-free sides must permit analytical Poisson contraction");
    }
    nearVec(result.applied_force_n, {0., stress, 0.}, 2.e-5, 2.e-10,
            "consistent face traction must report its exact resultant");
    nearVec(result.support_reaction_n, {0., -stress, 0.}, 2.e-5, 2.e-10,
            "support reactions must balance the external resultant");
    nearVec(result.applied_force_n + result.support_reaction_n, {}, 2.e-5, 2.e-10,
            "quasistatic global force balance");
    nearVec(result.reference_moment_residual_n_m, {}, 2.e-5, 2.e-10,
            "support and applied tractions must close reference moment balance");
    near(result.free_force_residual_n, 0., result.force_tolerance_n, 0.,
         "free-degree residual must satisfy the solver's reported tolerance");
    const double expected_energy = .5 * stress * axial_strain;
    near(result.stored_free_energy_j, expected_energy, 1.e-7, 2.e-7,
         "uniaxial unit-brick energy must equal one-half stress times strain");
}

void fixedComponentLoadCannotLoosenFreeEquilibriumTolerance() {
    constexpr double young = 100.e9;
    constexpr double free_stress = 100.;
    constexpr double fixed_force = 1.e11;
    SmallStrainPatch patch(axialBrick({isotropic(young, .25), 5000.}));
    PatchLoad load = axialTraction(patch, free_stress);
    std::size_t fixed_x_node = patch.definition().fixed_components.size();
    for (std::size_t i = 0; i < patch.definition().fixed_components.size(); ++i)
        if (patch.definition().fixed_components[i][0]) {
            fixed_x_node = i;
            break;
        }
    require(fixed_x_node < load.nodal_forces_n.size(),
            "tolerance fixture needs a fixed transverse component");
    load.nodal_forces_n[fixed_x_node].x = fixed_force;
    PatchSolveOptions options;
    options.relative_force_tolerance = 1.e-8;
    options.absolute_force_tolerance_n = 1.e-7;
    const auto result = patch.solveLoad(load, options);
    require(result.accepted,
            "large load on a fixed component must not obstruct the free axial solve");
    require(result.force_tolerance_n < 2.e-6,
            "reported free-force tolerance must be scaled only by loads on free components");

    double top_displacement = 0.;
    unsigned top_nodes = 0;
    const auto &positions = patch.definition().reference_positions_m;
    for (std::size_t i = 0; i < positions.size(); ++i)
        if (std::abs(positions[i].y - 1.) < 1.e-14) {
            top_displacement += patch.state().displacements_m[i].y;
            ++top_nodes;
        }
    require(top_nodes > 0, "tolerance fixture must contain a loaded top face");
    top_displacement /= top_nodes;
    near(top_displacement, free_stress / young, 2.e-15, 2.e-7,
         "fixed-component force must not permit acceptance before free traction equilibrates");
    near(result.free_force_residual_n, 0., result.force_tolerance_n, 0.,
         "accepted state must meet the independently scaled free-force tolerance");
    nearVec(result.applied_force_n + result.support_reaction_n, {},
            2.e-5, 2.e-15,
            "reaction must balance both the huge fixed load and modest free traction");
}

void elasticUnloadReturnsGeometryAndMaterialState() {
    SmallStrainPatch patch(oneTet({isotropic(), 2500.}, true));
    const PatchState original = patch.state();
    PatchLoad load = emptyLoad(4);
    load.prescribed_displacements_m = simpleShearDisplacements(
        patch.definition().reference_positions_m, 7.e-4);
    require(patch.solveLoad(load).accepted, "elastic load must be accepted");
    const auto unloaded = patch.solveLoad(emptyLoad(4));
    require(unloaded.accepted, "elastic unload must be accepted");
    require(patch.state().displacements_m.size() == original.displacements_m.size() &&
            patch.state().material_points.size() == original.material_points.size(),
            "elastic unload preserves state topology");
    for (std::size_t i = 0; i < original.displacements_m.size(); ++i)
        nearVec(patch.state().displacements_m[i], original.displacements_m[i],
                1.e-15, 0., "elastic displacement must return to its original value");
    for (std::size_t i = 0; i < original.material_points.size(); ++i)
        require(patch.state().material_points[i] == original.material_points[i],
                "elastic material-point strain/history must return exactly to virgin state");
    near(unloaded.stored_free_energy_j, 0., 1.e-10, 0.,
         "fully unloaded elastic patch has zero stored energy");
    near(unloaded.plastic_dissipation_j, 0., 0., 0.,
         "elastic load cycle cannot manufacture plastic dissipation");
    near(patch.state().accumulated_trapezoidal_external_work_j, 0., 1.e-7, 0.,
         "linear elastic loading and unloading close accumulated trapezoidal work");
}

void spatialJ2LoadUnloadRetainsResidualStrainAndHistory() {
    const SmallStrainLaw law = illustrativeMetalJ2();
    SmallStrainPatch patch(oneTet({law, 7870.}, true));
    PatchLoad load = emptyLoad(4);
    load.prescribed_displacements_m = simpleShearDisplacements(
        patch.definition().reference_positions_m, .006);
    const auto loaded = patch.solveLoad(load);
    require(loaded.accepted && patch.state().material_points.size() == 1,
            "prescribed plastic shear must produce one committed spatial material point");
    const J2State plastic_state = patch.state().material_points[0];
    require(plastic_state.equivalent_plastic_strain > 0. &&
            plastic_state.plastic_dissipation_j_m3 > 0.,
            "above-yield spatial shear must create irreversible J2 history");

    PatchLoad unload = emptyLoad(4);
    unload.prescribed_displacements_m = affineDisplacements(
        patch.definition().reference_positions_m, plastic_state.plastic_strain);
    const auto unloaded = patch.solveLoad(unload);
    require(unloaded.accepted, "unloading prescribed patch to its plastic strain must converge");
    const J2State &residual = patch.state().material_points[0];
    nearTensor(residual.total_strain, residual.plastic_strain, 2.e-15, 2.e-12,
               "zero-stress unload must retain the permanent spatial strain field");
    near(residual.equivalent_plastic_strain, plastic_state.equivalent_plastic_strain,
         1.e-15, 1.e-13, "elastic unload cannot heal equivalent plastic strain");
    near(residual.plastic_dissipation_j_m3, plastic_state.plastic_dissipation_j_m3,
         1.e-7, 1.e-13, "elastic unload cannot refund physical plastic dissipation");
    const double expected_hardening_energy =
        .5 * law.j2.isotropic_hardening_modulus_pa *
        residual.equivalent_plastic_strain * residual.equivalent_plastic_strain / 6.;
    near(unloaded.stored_free_energy_j, expected_hardening_energy, 1.e-6, 2.e-12,
         "zero-stress residual retains hardening free energy but no elastic energy");
    nearVec(unloaded.support_reaction_n, {}, 1.e-5, 1.e-12,
            "zero-stress residual shape needs no support resultant");
}

void failedSolveAndInvalidLoadLeaveEveryStateFieldExact() {
    SmallStrainPatch patch(axialBrick({isotropic(), 2500.}));
    require(patch.solveLoad(axialTraction(patch, 2.e5), tightSolveOptions()).accepted,
            "rollback test needs a nontrivial accepted base state");
    const PatchState before_budget = patch.state();
    auto options = tightSolveOptions();
    options.maximum_element_visits = 1;
    bool rejected = false;
    try {
        rejected = !patch.solveLoad(axialTraction(patch, 8.e5), options).accepted;
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "insufficient element-visit budget must reject the load transaction");
    require(sameStateExactly(patch.state(), before_budget),
            "budget rejection must leave displacement, material, load, work and revision exact");

    const PatchState before_invalid = patch.state();
    PatchLoad invalid = axialTraction(patch, 4.e5);
    invalid.nodal_forces_n.pop_back();
    rejected = false;
    try {
        rejected = !patch.solveLoad(invalid).accepted;
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "wrong-size nodal load must reject before solving");
    require(sameStateExactly(patch.state(), before_invalid),
            "invalid load must leave the full authoritative state bit-exact");

    invalid = axialTraction(patch, 4.e5);
    invalid.nodal_forces_n[0].y = std::numeric_limits<double>::quiet_NaN();
    rejected = !patch.solveLoad(invalid).accepted;
    require(rejected, "nonfinite nodal load must reject before solving");
    require(sameStateExactly(patch.state(), before_invalid),
            "nonfinite load must leave the full authoritative state bit-exact");
}

void restoreChecksKinematicHistoryAndReplaysNextLoad() {
    const PatchDefinition definition = axialBrick({isotropic(), 2500.});
    SmallStrainPatch direct(definition);
    const PatchLoad first = axialTraction(direct, 2.e5);
    const PatchLoad next = axialTraction(direct, 7.e5);
    require(direct.solveLoad(first, tightSolveOptions()).accepted,
            "restore parity needs an accepted checkpoint");
    const PatchState checkpoint = direct.state();
    const auto direct_result = direct.solveLoad(next, tightSolveOptions());
    require(direct_result.accepted, "direct continuation must converge");
    const PatchState direct_state = direct.state();

    SmallStrainPatch restored(definition);
    restored.restoreState(checkpoint, 1.e-4);
    require(sameStateExactly(restored.state(), checkpoint),
            "valid restore must preserve every persisted state field exactly");

    PatchState inconsistent = checkpoint;
    std::size_t free_node = 0;
    while (free_node < definition.fixed_components.size() &&
           definition.fixed_components[free_node] == std::array<bool, 3>{true, true, true})
        ++free_node;
    require(free_node < inconsistent.displacements_m.size(),
            "restore consistency test needs a node with a free component");
    inconsistent.displacements_m[free_node].x += 2.e-6;
    const PatchState before_bad_restore = restored.state();
    bool threw = false;
    try {
        restored.restoreState(inconsistent, 1.e-4);
    } catch (const std::invalid_argument &) {
        threw = true;
    }
    require(threw, "restore must reject displacement/material-strain inconsistency");
    require(sameStateExactly(restored.state(), before_bad_restore),
            "failed restore must not partially replace authoritative state");

    const auto restored_result = restored.solveLoad(next, tightSolveOptions());
    require(restored_result.accepted, "restored continuation must converge");
    require(restored.state().revision == direct_state.revision &&
            restored.state().material_points.size() == direct_state.material_points.size(),
            "restored continuation must preserve revision and material topology parity");
    for (std::size_t i = 0; i < direct_state.displacements_m.size(); ++i)
        nearVec(restored.state().displacements_m[i], direct_state.displacements_m[i],
                2.e-13, 2.e-11, "restore followed by next load must replay displacement state");
    for (std::size_t i = 0; i < direct_state.material_points.size(); ++i) {
        nearTensor(restored.state().material_points[i].total_strain,
                   direct_state.material_points[i].total_strain,
                   2.e-13, 2.e-11, "restore followed by next load must replay material strain");
        nearTensor(restored.state().material_points[i].plastic_strain,
                   direct_state.material_points[i].plastic_strain,
                   2.e-13, 2.e-11, "restore followed by next load must replay plastic strain");
    }
    near(restored_result.stored_free_energy_j, direct_result.stored_free_energy_j,
         1.e-9, 2.e-11, "restore continuation must replay stored energy");
    nearVec(restored_result.support_reaction_n, direct_result.support_reaction_n,
            1.e-7, 2.e-11, "restore continuation must replay reactions");
}

void matchedGlassOakIronControlsRemainStableBelowYield() {
    struct Case {
        std::string_view name;
        SmallStrainLaw law;
        double expected_axial_modulus_pa;
    };
    const std::vector<Case> cases{
        {"glass isotropic elastic", isotropic(70.e9, .22), 70.e9},
        {"oak orthotropic elastic", oakLikeOrthotropic(), 1.2e9},
        {"iron J2 below yield", illustrativeMetalJ2(), 211.e9},
    };
    constexpr double stress = 1.e6;
    std::vector<double> axial_displacements;
    for (const auto &entry : cases) {
        SmallStrainPatch patch(axialBrick({entry.law, 1000.}));
        const auto result = patch.solveLoad(axialTraction(patch, stress), tightSolveOptions());
        require(result.accepted && result.free_force_residual_n <= result.force_tolerance_n,
                std::string(entry.name) + " must converge under the same below-yield traction");
        require(result.stored_free_energy_j > 0. && result.plastic_dissipation_j == 0.,
                std::string(entry.name) + " must retain positive elastic energy without dissipation");
        nearVec(result.applied_force_n + result.support_reaction_n, {},
                2.e-5, 2.e-10, "matched material control must conserve resultant force");
        const auto &positions = patch.definition().reference_positions_m;
        double face_displacement = 0.;
        unsigned face_nodes = 0;
        for (std::size_t i = 0; i < positions.size(); ++i)
            if (std::abs(positions[i].y - 1.) < 1.e-14) {
                face_displacement += patch.state().displacements_m[i].y;
                ++face_nodes;
            }
        face_displacement /= face_nodes;
        near(face_displacement, stress / entry.expected_axial_modulus_pa,
             2.e-11, 2.e-7, "matched traction response must use the declared axial modulus");
        axial_displacements.push_back(face_displacement);
        for (const auto &point : patch.state().material_points)
            require(point.equivalent_plastic_strain == 0. &&
                    point.plastic_dissipation_j_m3 == 0.,
                    "below-yield matched controls must not accumulate plastic history");
    }
    require(axial_displacements[1] > axial_displacements[0] &&
            axial_displacements[0] > axial_displacements[2],
            "declared oak, glass and iron axial moduli must order compliance without name tuning");
}

PatchSolveOptions backendOptions(PatchLinearBackend backend) {
    auto options = tightSolveOptions();
    options.linear_backend = backend;
    options.maximum_element_visits = 12000000;
    return options;
}

PatchDefinition pressurePatch(PatchMaterial material) {
    PatchDefinition definition = makeTetrahedralBrick(
        {.04, .02, .04}, {4, 2, 4}, std::move(material));
    for (std::size_t i = 0; i < definition.reference_positions_m.size(); ++i)
        if (std::abs(definition.reference_positions_m[i].y) < 1.e-14)
            definition.fixed_components[i] = {true, true, true};
    return definition;
}

PatchLoad centralPressure(const SmallStrainPatch &patch, double pressure_pa) {
    const auto &positions = patch.definition().reference_positions_m;
    PatchLoad load = emptyLoad(positions.size());
    double loaded_area = 0.;
    for (const auto &triangle : patch.boundaryTriangles()) {
        const Vec3 &a = positions[triangle[0]];
        const Vec3 &b = positions[triangle[1]];
        const Vec3 &c = positions[triangle[2]];
        const Vec3 center = (a + b + c) / 3.;
        if (std::abs(a.y - .02) > 1.e-14 || std::abs(b.y - .02) > 1.e-14 ||
            std::abs(c.y - .02) > 1.e-14 || std::abs(center.x) > .01000000000001 ||
            std::abs(center.z) > .01000000000001)
            continue;
        const double area = triangleArea(a, b, c);
        loaded_area += area;
        for (unsigned node : triangle)
            load.nodal_forces_n[node].y -= pressure_pa * area / 3.;
    }
    near(loaded_area, .0004, 1.e-16, 1.e-13,
         "central pressure fixture must cover the fixed 20 by 20 millimetre area");
    nearVec(sum(load.nodal_forces_n), {0., -pressure_pa * loaded_area, 0.},
            1.e-8, 2.e-13,
            "distributed pressure nodal forces must recover pressure times loaded area");
    return load;
}

double maximumEquivalentPlasticStrain(const PatchState &state) {
    double result = 0.;
    for (const auto &point : state.material_points)
        result = std::max(result, point.equivalent_plastic_strain);
    return result;
}

void compareBackendStates(const PatchState &reference, const PatchState &assembled,
                          std::string_view message) {
    require(reference.revision == assembled.revision &&
            reference.displacements_m.size() == assembled.displacements_m.size() &&
            reference.material_points.size() == assembled.material_points.size() &&
            reference.last_nodal_forces_n.size() == assembled.last_nodal_forces_n.size(),
            std::string(message) + ": state layout/revision parity");
    // Five nanometres in displacement corresponds to roughly 5e-7 strain on
    // this fixture's 10 mm cells. The absolute strain/history tolerance follows
    // that resolvable displacement difference; the 2e-7 relative allowance is
    // small enough to expose a missing block or physical-shear factor.
    for (std::size_t i = 0; i < reference.displacements_m.size(); ++i) {
        nearVec(assembled.displacements_m[i], reference.displacements_m[i],
                5.e-9, 2.e-7, message);
        require(sameVecExactly(assembled.last_nodal_forces_n[i],
                               reference.last_nodal_forces_n[i]),
                std::string(message) + ": both backends must commit the identical declared load");
    }
    for (std::size_t i = 0; i < reference.material_points.size(); ++i) {
        const auto &a = assembled.material_points[i];
        const auto &r = reference.material_points[i];
        nearTensor(a.total_strain, r.total_strain, 5.e-7, 2.e-7, message);
        nearTensor(a.plastic_strain, r.plastic_strain, 5.e-7, 2.e-7, message);
        near(a.equivalent_plastic_strain, r.equivalent_plastic_strain,
             5.e-7, 2.e-7, message);
        near(a.plastic_dissipation_j_m3, r.plastic_dissipation_j_m3,
             1.e-2, 2.e-6, message);
    }
    near(assembled.accumulated_trapezoidal_external_work_j,
         reference.accumulated_trapezoidal_external_work_j,
         1.e-5, 2.e-6, message);
    near(assembled.accumulated_backward_euler_external_work_j,
         reference.accumulated_backward_euler_external_work_j,
         1.e-5, 2.e-6, message);
}

void compareBackendResults(const PatchSolveResult &reference,
                           const PatchSolveResult &assembled,
                           double applied_force_scale, std::string_view message) {
    require(reference.accepted && assembled.accepted,
            std::string(message) + ": both backend solves must be accepted");
    require(reference.linear_backend == PatchLinearBackend::MatrixFreeReference &&
            assembled.linear_backend == PatchLinearBackend::AssembledBlockCsr,
            std::string(message) + ": result must identify the selected backend");
    require(reference.free_force_residual_n <= reference.force_tolerance_n &&
            assembled.free_force_residual_n <= assembled.force_tolerance_n,
            std::string(message) + ": each backend must independently satisfy equilibrium");
    nearVec(assembled.applied_force_n, reference.applied_force_n,
            1.e-8, 1.e-13, message);
    const double reaction_tolerance = 8. * std::max(
        reference.force_tolerance_n, assembled.force_tolerance_n);
    nearVec(assembled.support_reaction_n, reference.support_reaction_n,
            reaction_tolerance, 2.e-7, message);
    nearVec(assembled.reference_moment_residual_n_m,
            reference.reference_moment_residual_n_m,
            reaction_tolerance * .05, 2.e-7, message);
    require(reference.reactions_n.size() == assembled.reactions_n.size(),
            std::string(message) + ": reaction vector layout parity");
    for (std::size_t i = 0; i < reference.reactions_n.size(); ++i)
        nearVec(assembled.reactions_n[i], reference.reactions_n[i],
                reaction_tolerance, 2.e-7, message);
    near(assembled.stored_free_energy_j, reference.stored_free_energy_j,
         1.e-5, 2.e-6, message);
    near(assembled.plastic_dissipation_j, reference.plastic_dissipation_j,
         1.e-5, 2.e-6, message);
    near(assembled.trapezoidal_external_work_increment_j,
         reference.trapezoidal_external_work_increment_j,
         1.e-5, 2.e-6, message);
    near(assembled.backward_euler_external_work_increment_j,
         reference.backward_euler_external_work_increment_j,
         1.e-5, 2.e-6, message);
    near(assembled.stored_free_energy_increment_j,
         reference.stored_free_energy_increment_j,
         1.e-5, 2.e-6, message);
    near(assembled.plastic_dissipation_increment_j,
         reference.plastic_dissipation_increment_j,
         1.e-5, 2.e-6, message);
    near(assembled.trapezoidal_work_residual_j,
         reference.trapezoidal_work_residual_j,
         1.e-5, 2.e-6, message);
    near(assembled.backward_euler_balance_residual_j,
         reference.backward_euler_balance_residual_j,
         1.e-5, 2.e-6, message);
    near(assembled.constitutive_backward_euler_excess_j,
         reference.constitutive_backward_euler_excess_j,
         1.e-5, 2.e-6, message);
    nearVec(reference.applied_force_n + reference.support_reaction_n, {},
            reaction_tolerance, 2.e-7, message);
    nearVec(assembled.applied_force_n + assembled.support_reaction_n, {},
            reaction_tolerance, 2.e-7, message);
    require(length(reference.applied_force_n) <= applied_force_scale * 1.000001 &&
            length(assembled.applied_force_n) <= applied_force_scale * 1.000001,
            std::string(message) + ": applied resultant stays within fixture scale");
}

void matchedGlassOakIronPressureCyclesMatchAcrossLinearBackends() {
    struct Case {
        std::string_view name;
        PatchMaterial material;
    };
    const std::vector<Case> cases{
        {"glass", {isotropic(70.e9, .22), 2500.}},
        {"oak", {continuumOakOrthotropic(), 700.}},
        {"iron", {continuumIronJ2(), 7870.}},
    };
    constexpr double peak_pressure_pa = 100.e6;
    constexpr unsigned increments = 8;
    for (const auto &entry : cases) {
        const PatchDefinition definition = pressurePatch(entry.material);
        SmallStrainPatch reference(definition), assembled(definition);
        bool saw_matrix_free_matvec = false;
        bool saw_assembled_blocks = false;
        for (unsigned step = 1; step <= 2 * increments; ++step) {
            const double fraction = step <= increments ? double(step) / increments :
                double(2 * increments - step) / increments;
            const PatchLoad load = centralPressure(reference,
                peak_pressure_pa * fraction);
            const auto matrix_result = reference.solveLoad(
                load, backendOptions(PatchLinearBackend::MatrixFreeReference));
            const auto assembled_result = assembled.solveLoad(
                load, backendOptions(PatchLinearBackend::AssembledBlockCsr));
            compareBackendResults(matrix_result, assembled_result,
                peak_pressure_pa * .0004,
                std::string(entry.name) + " spatial pressure step");
            compareBackendStates(reference.state(), assembled.state(),
                std::string(entry.name) + " spatial pressure history");
            saw_matrix_free_matvec = saw_matrix_free_matvec ||
                matrix_result.matrix_free_matvec_element_visits > 0;
            saw_assembled_blocks = saw_assembled_blocks ||
                (assembled_result.tangent_block_count > 0 &&
                 assembled_result.tangent_assembly_element_visits > 0 &&
                 assembled_result.assembled_matvec_block_visits > 0);
        }
        require(saw_matrix_free_matvec && saw_assembled_blocks,
                std::string(entry.name) +
                    " cycle must exercise matrix-free products and assembled block products");
        require(maximumEquivalentPlasticStrain(reference.state()) == 0. &&
                maximumEquivalentPlasticStrain(assembled.state()) == 0.,
                std::string(entry.name) +
                    " matched 100 MPa pressure cycle must remain elastic");
    }
}

void ironPlasticPressureCycleMatchesAcrossLinearBackends() {
    const PatchDefinition definition = pressurePatch({continuumIronJ2(), 7870.});
    SmallStrainPatch reference(definition), assembled(definition);
    constexpr double peak_pressure_pa = 800.e6;
    constexpr unsigned increments = 32;
    for (unsigned step = 1; step <= 2 * increments; ++step) {
        const double fraction = step <= increments ? double(step) / increments :
            double(2 * increments - step) / increments;
        const PatchLoad load = centralPressure(reference, peak_pressure_pa * fraction);
        const auto matrix_result = reference.solveLoad(
            load, backendOptions(PatchLinearBackend::MatrixFreeReference));
        const auto assembled_result = assembled.solveLoad(
            load, backendOptions(PatchLinearBackend::AssembledBlockCsr));
        compareBackendResults(matrix_result, assembled_result,
            peak_pressure_pa * .0004, "iron 800 MPa spatial pressure step");
        compareBackendStates(reference.state(), assembled.state(),
            "iron 800 MPa spatial pressure history");
        if (step == increments / 2)
            require(maximumEquivalentPlasticStrain(reference.state()) == 0. &&
                    maximumEquivalentPlasticStrain(assembled.state()) == 0.,
                    "documented coarse fixture must still be elastic at 400 MPa");
    }
    require(maximumEquivalentPlasticStrain(reference.state()) > 0. &&
            maximumEquivalentPlasticStrain(assembled.state()) > 0.,
            "the separate 800 MPa iron cycle must retain plastic history after unloading");
}

PatchDefinition mixedMaterialPatch() {
    PatchDefinition definition = axialBrick({isotropic(70.e9, .22), 2500.});
    definition.materials = {
        {isotropic(70.e9, .22), 2500.},
        {oakLikeOrthotropic(), 700.},
        {illustrativeMetalJ2(), 7870.},
    };
    for (std::size_t i = 0; i < definition.elements.size(); ++i)
        definition.elements[i].material = static_cast<unsigned>(i % definition.materials.size());
    return definition;
}

PatchLoad mixedTractionAndBoundaryDisplacement(const SmallStrainPatch &patch) {
    const auto &positions = patch.definition().reference_positions_m;
    PatchLoad load = emptyLoad(positions.size());
    constexpr Vec3 traction_pa{1.e5, 2.e5, -7.e4};
    for (const auto &triangle : patch.boundaryTriangles()) {
        if (std::abs(positions[triangle[0]].y - 1.) > 1.e-14 ||
            std::abs(positions[triangle[1]].y - 1.) > 1.e-14 ||
            std::abs(positions[triangle[2]].y - 1.) > 1.e-14)
            continue;
        const double area = triangleArea(positions[triangle[0]], positions[triangle[1]],
                                         positions[triangle[2]]);
        for (unsigned node : triangle)
            load.nodal_forces_n[node] += traction_pa * (area / 3.);
    }
    for (std::size_t i = 0; i < positions.size(); ++i) {
        const auto &fixed = patch.definition().fixed_components[i];
        if (fixed[0]) load.prescribed_displacements_m[i].x = 2.e-6;
        if (fixed[2]) load.prescribed_displacements_m[i].z = -1.e-6;
    }
    return load;
}

void mixedMaterialsAndPartialConstraintsMatchAcrossBackends() {
    const PatchDefinition definition = mixedMaterialPatch();
    SmallStrainPatch reference(definition), assembled(definition);
    const PatchLoad load = mixedTractionAndBoundaryDisplacement(reference);
    const auto matrix_result = reference.solveLoad(
        load, backendOptions(PatchLinearBackend::MatrixFreeReference));
    const auto assembled_result = assembled.solveLoad(
        load, backendOptions(PatchLinearBackend::AssembledBlockCsr));
    compareBackendResults(matrix_result, assembled_result, length(Vec3{1.e5, 2.e5, -7.e4}),
                          "mixed per-element law and partial-component constraints");
    compareBackendStates(reference.state(), assembled.state(),
                         "mixed per-element law and partial-component constraints");
    require(assembled_result.tangent_block_count > definition.reference_positions_m.size(),
            "mixed assembled solve must contain off-diagonal node-coupling blocks");
    const auto evaluation = assembled.evaluate(assembled.state().displacements_m);
    bool has_shear = false;
    for (const auto &response : evaluation.responses)
        has_shear = has_shear || std::abs(response.state.total_strain.xy) > 1.e-10 ||
            std::abs(response.state.total_strain.yz) > 1.e-10 ||
            std::abs(response.state.total_strain.zx) > 1.e-10;
    require(has_shear,
            "mixed traction fixture must exercise physical tensor shear components");
}

void bothBackendBudgetFailuresPreserveExactPriorState() {
    const PatchDefinition definition = mixedMaterialPatch();
    const PatchLoad base_load = [&] {
        SmallStrainPatch geometry(definition);
        return mixedTractionAndBoundaryDisplacement(geometry);
    }();
    for (PatchLinearBackend backend : {PatchLinearBackend::MatrixFreeReference,
                                       PatchLinearBackend::AssembledBlockCsr}) {
        SmallStrainPatch patch(definition);
        require(patch.solveLoad(base_load, backendOptions(backend)).accepted,
                "backend rollback fixture needs a nontrivial accepted prior state");
        const PatchState before = patch.state();
        PatchLoad changed = base_load;
        for (auto &force : changed.nodal_forces_n) force *= 1.5;
        auto options = backendOptions(backend);
        options.maximum_element_visits = 1;
        const auto rejected = patch.solveLoad(changed, options);
        require(!rejected.accepted && !rejected.error.empty(),
                "both backends must report a bounded-work rejection");
        require(sameStateExactly(patch.state(), before),
                "both backend budget failures must preserve every prior state scalar exactly");
    }
}

void assembledBlockBudgetFailurePreservesExactPriorState() {
    const PatchDefinition definition = mixedMaterialPatch();
    SmallStrainPatch patch(definition);
    const PatchLoad base_load = mixedTractionAndBoundaryDisplacement(patch);
    require(patch.solveLoad(
                base_load,
                backendOptions(PatchLinearBackend::AssembledBlockCsr)).accepted,
            "assembled block-budget fixture needs a nontrivial accepted prior state");
    const PatchState before = patch.state();
    PatchLoad changed = base_load;
    for (auto &force : changed.nodal_forces_n) force *= 1.5;
    auto options = backendOptions(PatchLinearBackend::AssembledBlockCsr);
    options.maximum_tangent_block_visits = 1;
    const auto rejected = patch.solveLoad(changed, options);
    require(!rejected.accepted && !rejected.error.empty(),
            "assembled backend must report its independent block-work rejection");
    require(sameStateExactly(patch.state(), before),
            "assembled block-work rejection must preserve every prior state scalar exactly");
}

void assembledRestoreContinuationMatchesUninterruptedPlasticPath() {
    const PatchDefinition definition = pressurePatch({continuumIronJ2(), 7870.});
    SmallStrainPatch uninterrupted(definition);
    const auto options = backendOptions(PatchLinearBackend::AssembledBlockCsr);
    constexpr double peak_pressure_pa = 800.e6;
    for (double fraction : {.125, .25, .375, .50, .625, .75})
        require(uninterrupted.solveLoad(centralPressure(uninterrupted,
                                                        peak_pressure_pa * fraction),
                                        options).accepted,
                "assembled restore fixture loading must converge");
    const PatchState checkpoint = uninterrupted.state();

    const std::vector<double> continuation{.875, 1., .875, .75, .625, .50};
    PatchSolveResult direct_result;
    for (double fraction : continuation) {
        direct_result = uninterrupted.solveLoad(
            centralPressure(uninterrupted, peak_pressure_pa * fraction), options);
        require(direct_result.accepted,
                "uninterrupted assembled plastic continuation must converge");
    }

    SmallStrainPatch restored(definition);
    restored.restoreState(checkpoint, .01);
    PatchSolveResult restored_result;
    for (double fraction : continuation) {
        restored_result = restored.solveLoad(
            centralPressure(restored, peak_pressure_pa * fraction), options);
        require(restored_result.accepted,
                "restored assembled plastic continuation must converge");
    }
    compareBackendStates(uninterrupted.state(), restored.state(),
                         "assembled restored continuation parity");
    near(restored_result.stored_free_energy_j, direct_result.stored_free_energy_j,
         1.e-8, 2.e-10, "assembled restore must replay stored energy");
    near(restored_result.plastic_dissipation_j, direct_result.plastic_dissipation_j,
         1.e-8, 2.e-10, "assembled restore must replay plastic dissipation");
    nearVec(restored_result.support_reaction_n, direct_result.support_reaction_n,
            1.e-5, 2.e-10, "assembled restore must replay support reactions");
    require(maximumEquivalentPlasticStrain(restored.state()) > 0.,
            "assembled restore continuation fixture must traverse a plastic iron state");
}

template <class Function>
void requireInvalid(Function &&function, std::string_view message) {
    try {
        function();
    } catch (const std::invalid_argument &) {
        return;
    }
    throw TestFailure(std::string(message));
}

void constructorRejectsInvalidReferenceMeshes() {
    const PatchMaterial material{isotropic(), 1000.};
    auto negative = oneTet(material);
    std::swap(negative.elements[0].nodes[1], negative.elements[0].nodes[2]);
    requireInvalid([&] { SmallStrainPatch patch(negative); },
                   "negative reference volume must be rejected rather than silently reoriented");

    auto singular = oneTet(material);
    singular.reference_positions_m[3] = {1., 1., 0.};
    requireInvalid([&] { SmallStrainPatch patch(singular); },
                   "singular reference tetrahedron must be rejected");

    auto bad_node = oneTet(material);
    bad_node.elements[0].nodes[3] = 4;
    requireInvalid([&] { SmallStrainPatch patch(bad_node); },
                   "out-of-range mesh node index must be rejected");

    auto bad_material = oneTet(material);
    bad_material.elements[0].material = 1;
    requireInvalid([&] { SmallStrainPatch patch(bad_material); },
                   "out-of-range material index must be rejected");

    auto bad_constraints = oneTet(material);
    bad_constraints.fixed_components.pop_back();
    requireInvalid([&] { SmallStrainPatch patch(bad_constraints); },
                   "constraint vector must match mesh node count");

    auto negative_density = oneTet(material);
    negative_density.materials[0].density_kg_m3 = -1.;
    requireInvalid([&] { SmallStrainPatch patch(negative_density); },
                   "negative density must be rejected before publishing mass");

    auto far_node = oneTet(material);
    far_node.reference_positions_m[1] = {1001., 0., 0.};
    requireInvalid([&] { SmallStrainPatch patch(far_node); },
                   "reference coordinates outside the declared mesh bound must be rejected");
}

void constructorRejectsSameSideSharedFaceAndCoincidentNodes() {
    const PatchMaterial material{isotropic(), 1000.};
    PatchDefinition same_side;
    same_side.reference_positions_m = {
        {0., 0., 0.}, {1., 0., 0.}, {0., 1., 0.},
        {0., 0., 1.}, {.2, .2, 2.}};
    same_side.elements = {
        {{0, 1, 2, 3}, 0},
        {{0, 1, 2, 4}, 0},
    };
    same_side.materials = {material};
    same_side.fixed_components.resize(same_side.reference_positions_m.size());
    requireInvalid([&] { SmallStrainPatch patch(same_side); },
                   "two positive-volume tetrahedra sharing a face on the same side must be rejected");

    PatchDefinition coincident;
    coincident.reference_positions_m = {
        {0., 0., 0.}, {1., 0., 0.}, {0., 1., 0.}, {0., 0., 1.},
        {0., 0., 0.}, {2., 0., 0.}, {0., 2., 0.}, {0., 0., 2.}};
    coincident.elements = {
        {{0, 1, 2, 3}, 0},
        {{4, 5, 6, 7}, 0},
    };
    coincident.materials = {material};
    coincident.fixed_components.resize(coincident.reference_positions_m.size());
    requireInvalid([&] { SmallStrainPatch patch(coincident); },
                   "distinct mesh node IDs with exactly coincident coordinates must be rejected");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"affine P1 patch and self-equilibrated internal forces",
         affinePatchHasExactStrainAndSelfEquilibratedInternalForces},
        {"prescribed affine shear energy reactions and work",
         prescribedAffineShearMatchesEnergyReactionsAndWork},
        {"uniaxial traction Poisson contraction and global balance",
         freeAxialTractionProducesPoissonContractionAndBalancedReactions},
        {"fixed-component load excluded from free tolerance scale",
         fixedComponentLoadCannotLoosenFreeEquilibriumTolerance},
        {"elastic spatial load-unload return", elasticUnloadReturnsGeometryAndMaterialState},
        {"spatial J2 residual strain and history", spatialJ2LoadUnloadRetainsResidualStrainAndHistory},
        {"transaction rollback on budget and invalid load",
         failedSolveAndInvalidLoadLeaveEveryStateFieldExact},
        {"restore consistency and next-load parity",
         restoreChecksKinematicHistoryAndReplaysNextLoad},
        {"matched glass oak iron below-yield controls",
         matchedGlassOakIronControlsRemainStableBelowYield},
        {"matched 100 MPa glass oak iron pressure-cycle backend parity",
         matchedGlassOakIronPressureCyclesMatchAcrossLinearBackends},
        {"800 MPa iron plastic pressure-cycle backend parity",
         ironPlasticPressureCycleMatchesAcrossLinearBackends},
        {"mixed-law partial-constraint backend parity",
         mixedMaterialsAndPartialConstraintsMatchAcrossBackends},
        {"both linear backends roll back bounded-work rejection",
         bothBackendBudgetFailuresPreserveExactPriorState},
        {"assembled block-work limit rolls back exactly",
         assembledBlockBudgetFailurePreservesExactPriorState},
        {"assembled backend restore continuation parity",
         assembledRestoreContinuationMatchesUninterruptedPlasticPath},
        {"invalid reference mesh rejection", constructorRejectsInvalidReferenceMeshes},
        {"shared-face orientation and coincident-node rejection",
         constructorRejectsSameSideSharedFaceAndCoincidentNodes},
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
