#include "physics/PatchPressure.hpp"

#include <algorithm>
#include <array>
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
    if (!condition) {
        throw TestFailure(std::string(message));
    }
}

void near(double actual, double expected, double absolute_tolerance,
          double relative_tolerance, std::string_view message) {
    if (!std::isfinite(actual) || !std::isfinite(expected) ||
        std::abs(actual - expected) >
            absolute_tolerance + relative_tolerance * std::abs(expected)) {
        throw TestFailure(std::string(message) + ": actual=" +
                          std::to_string(actual) + " expected=" +
                          std::to_string(expected));
    }
}

void nearVec(const Vec3 &actual, const Vec3 &expected, double absolute_tolerance,
             double relative_tolerance, std::string_view message) {
    near(actual.x, expected.x, absolute_tolerance, relative_tolerance, message);
    near(actual.y, expected.y, absolute_tolerance, relative_tolerance, message);
    near(actual.z, expected.z, absolute_tolerance, relative_tolerance, message);
}

SmallStrainLaw elasticLaw() {
    return {
        .kind = SmallStrainLawKind::IsotropicElastic,
        .young_modulus_pa = {70.e9, 0., 0.},
        .poisson_xy_yz_zx = {.22, 0., 0.},
        .maximum_total_strain_norm = .05,
    };
}

SmallStrainPatch makeBrick(std::array<unsigned, 3> resolution = {2, 2, 2}) {
    return SmallStrainPatch(makeTetrahedralBrick(
        {2., 2., 2.}, resolution, PatchMaterial{elasticLaw(), 2500.}));
}

PatchPressure topPressure(Vec3 center, Vec3 axis_u, Vec3 axis_v,
                          double half_width, double half_height,
                          double pressure,
                          PatchPressureProfile profile =
                              PatchPressureProfile::Uniform) {
    PatchPressure result;
    result.center_m = center;
    result.axis_u = axis_u;
    result.axis_v = axis_v;
    result.half_width_m = half_width;
    result.half_height_m = half_height;
    result.peak_pressure_pa = pressure;
    result.profile = profile;
    return result;
}

Vec3 pressureNormal(const PatchPressure &pressure) {
    return normalized(cross(pressure.axis_u, pressure.axis_v));
}

Vec3 sumForces(const std::vector<Vec3> &forces) {
    Vec3 result;
    for (const Vec3 force : forces) {
        result += force;
    }
    return result;
}

Vec3 forceMoment(const std::vector<Vec3> &positions,
                 const std::vector<Vec3> &forces) {
    require(positions.size() == forces.size(),
            "force moment inputs must have equal sizes");
    Vec3 result;
    for (std::size_t index = 0; index < positions.size(); ++index) {
        result += cross(positions[index], forces[index]);
    }
    return result;
}

bool sameVecExactly(const Vec3 &first, const Vec3 &second) {
    return first.x == second.x && first.y == second.y && first.z == second.z;
}

bool sameStateExactly(const PatchState &first, const PatchState &second) {
    if (first.displacements_m.size() != second.displacements_m.size() ||
        first.material_points != second.material_points ||
        first.last_nodal_forces_n.size() != second.last_nodal_forces_n.size() ||
        first.accumulated_trapezoidal_external_work_j !=
            second.accumulated_trapezoidal_external_work_j ||
        first.accumulated_backward_euler_external_work_j !=
            second.accumulated_backward_euler_external_work_j ||
        first.revision != second.revision) {
        return false;
    }
    for (std::size_t index = 0; index < first.displacements_m.size(); ++index) {
        if (!sameVecExactly(first.displacements_m[index],
                            second.displacements_m[index])) {
            return false;
        }
    }
    for (std::size_t index = 0; index < first.last_nodal_forces_n.size(); ++index) {
        if (!sameVecExactly(first.last_nodal_forces_n[index],
                            second.last_nodal_forces_n[index])) {
            return false;
        }
    }
    return true;
}

void requireInvalid(const std::function<void()> &function,
                    std::string_view message) {
    try {
        function();
    } catch (const std::invalid_argument &) {
        return;
    }
    throw TestFailure(std::string(message));
}

void requireResultantAndMoment(const SmallStrainPatch &patch,
                               const PatchPressure &pressure,
                               const PatchPressureLoad &result,
                               double expected_weighted_area,
                               double expected_area,
                               double expected_pressure,
                               std::string_view label) {
    const Vec3 normal = pressureNormal(pressure);
    const Vec3 expected_force =
        -normal * (expected_pressure * expected_weighted_area);
    const Vec3 expected_moment = cross(pressure.center_m, expected_force);
    near(result.loaded_area_m2, expected_area, 2.e-10, 2.e-10,
         std::string(label) + " loaded area");
    near(result.weighted_area_m2, expected_weighted_area, 2.e-10, 2.e-10,
         std::string(label) + " weighted area");
    nearVec(result.resultant_force_n, expected_force, 2.e-5, 2.e-12,
            std::string(label) + " resultant force");
    nearVec(result.reference_moment_n_m, expected_moment, 2.e-7, 2.e-12,
            std::string(label) + " reference moment");
    require(result.quadrature_points > 0U,
            std::string(label) + " must report quadrature work");
    require(result.load.nodal_forces_n.size() ==
                patch.definition().reference_positions_m.size(),
            std::string(label) + " must return one force per patch node");
    require(result.load.prescribed_displacements_m.size() ==
                patch.definition().reference_positions_m.size(),
            std::string(label) + " must preserve prescribed displacement layout");
    nearVec(sumForces(result.load.nodal_forces_n), result.resultant_force_n,
            2.e-5, 2.e-12, std::string(label) + " nodal resultant");
    nearVec(forceMoment(patch.definition().reference_positions_m,
                        result.load.nodal_forces_n),
            result.reference_moment_n_m, 2.e-7, 2.e-12,
            std::string(label) + " nodal moment");
    for (const Vec3 displacement : result.load.prescribed_displacements_m) {
        nearVec(displacement, {}, 0., 0.,
                std::string(label) + " pressure cannot prescribe displacement");
    }
}

void uniformPressureHasAnalyticalAreaForceAndMoment() {
    SmallStrainPatch patch = makeBrick({2, 2, 2});
    const PatchPressure pressure = topPressure(
        {.20, 2., .15}, {1., 0., 0.}, {0., 0., -1.}, .75, .70, 3.2e6);
    const double area = 4. * pressure.half_width_m * pressure.half_height_m;
    const PatchPressureLoad result = makePatchPressureLoad(patch, pressure);
    requireResultantAndMoment(patch, pressure, result, area, area,
                              pressure.peak_pressure_pa, "uniform pressure");
}

void smoothPressureHasAnalyticalEffectiveArea() {
    SmallStrainPatch patch = makeBrick({2, 2, 2});
    const PatchPressure pressure = topPressure(
        {-.15, 2., -.20}, {1., 0., 0.}, {0., 0., -1.}, .70, .65, 4.5e6,
        PatchPressureProfile::Smooth);
    const double area = 4. * pressure.half_width_m * pressure.half_height_m;
    const double effective_area =
        (16. * pressure.half_width_m / 15.) *
        (16. * pressure.half_height_m / 15.);
    const PatchPressureLoad result = makePatchPressureLoad(patch, pressure);
    requireResultantAndMoment(patch, pressure, result, effective_area, area,
                              pressure.peak_pressure_pa, "smooth pressure");
}

void nonAlignedRectangleAcrossGridPreservesLinearResultants() {
    SmallStrainPatch patch = makeBrick({6, 6, 6});
    const double angle = .37;
    const Vec3 axis_u{std::cos(angle), 0., std::sin(angle)};
    const Vec3 axis_v{std::sin(angle), 0., -std::cos(angle)};
    const PatchPressure pressure =
        topPressure({.15, 2., -.12}, axis_u, axis_v, .65, .55, 1.7e6);
    const double area = 4. * pressure.half_width_m * pressure.half_height_m;
    const PatchPressureLoad result = makePatchPressureLoad(patch, pressure);
    requireResultantAndMoment(patch, pressure, result, area, area,
                              pressure.peak_pressure_pa,
                              "nonaligned clipped pressure");
    require(result.quadrature_points > 6U,
            "nonaligned rectangle must cross multiple boundary triangles");

    const Vec3 translation{.31, -.27, .44};
    const Vec3 rotation{.12, -.08, .19};
    double translation_work = 0.;
    double rotation_work = 0.;
    for (std::size_t index = 0; index < result.load.nodal_forces_n.size(); ++index) {
        translation_work += dot(result.load.nodal_forces_n[index], translation);
        rotation_work += dot(result.load.nodal_forces_n[index],
                             cross(rotation,
                                   patch.definition().reference_positions_m[index]));
    }
    near(translation_work, dot(result.resultant_force_n, translation), 2.e-7,
         2.e-12, "nodal pressure forces must reproduce virtual translation work");
    near(rotation_work, dot(result.reference_moment_n_m, rotation), 2.e-9,
         2.e-12, "nodal pressure forces must reproduce virtual rotation work");
}

Vec3 rotateY(const Vec3 &value, double angle) {
    const double cosine = std::cos(angle);
    const double sine = std::sin(angle);
    return {cosine * value.x + sine * value.z, value.y,
            -sine * value.x + cosine * value.z};
}

void rigidTranslationAndRotationPreservePressureCovariance() {
    const double angle = .61;
    const Vec3 translation{1.2, -.4, .7};
    PatchDefinition definition = makeTetrahedralBrick(
        {2., 2., 2.}, {4, 4, 4}, PatchMaterial{elasticLaw(), 2500.});
    for (Vec3 &position : definition.reference_positions_m) {
        position = rotateY(position, angle) + translation;
    }
    SmallStrainPatch patch(std::move(definition));
    const PatchPressure pressure = topPressure(
        rotateY({.12, 2., -.16}, angle) + translation,
        rotateY({1., 0., 0.}, angle), rotateY({0., 0., -1.}, angle), .61, .57,
        2.4e6);
    const double area = 4. * pressure.half_width_m * pressure.half_height_m;
    const PatchPressureLoad result = makePatchPressureLoad(patch, pressure);
    requireResultantAndMoment(patch, pressure, result, area, area,
                              pressure.peak_pressure_pa,
                              "rigidly transformed pressure");
    nearVec(result.resultant_force_n,
            -pressureNormal(pressure) * (pressure.peak_pressure_pa * area),
            2.e-5, 2.e-12, "rigid transform must rotate pressure force");
}

void pressurePreservesFixedDisplacementsAndFreeZeros() {
    PatchDefinition definition = makeTetrahedralBrick(
        {2., 2., 2.}, {2, 2, 2}, PatchMaterial{elasticLaw(), 2500.});
    for (std::size_t index = 0; index < definition.reference_positions_m.size();
         ++index) {
        if (definition.reference_positions_m[index].y == 0.) {
            definition.fixed_components[index] = {true, true, true};
        }
    }
    SmallStrainPatch patch(std::move(definition));
    PatchLoad prescribed;
    const auto &positions = patch.definition().reference_positions_m;
    prescribed.nodal_forces_n.resize(positions.size());
    prescribed.prescribed_displacements_m.resize(positions.size());
    for (std::size_t index = 0; index < positions.size(); ++index) {
        if (positions[index].y == 0.) {
            prescribed.prescribed_displacements_m[index] =
                {2.e-6, -1.e-6, 3.e-6};
        }
    }
    const PatchSolveResult solved = patch.solveLoad(prescribed);
    if (!solved.accepted) {
        throw TestFailure("small prescribed bottom displacement was rejected: " +
                          solved.error);
    }
    const PatchState before = patch.state();
    const PatchPressure pressure = topPressure(
        {0., 2., 0.}, {1., 0., 0.}, {0., 0., -1.}, .50, .50, 1.e6);
    const PatchPressureLoad result = makePatchPressureLoad(patch, pressure);
    for (std::size_t index = 0; index < positions.size(); ++index) {
        const auto fixed = patch.definition().fixed_components[index];
        const Vec3 expected{
            fixed[0] ? before.displacements_m[index].x : 0.,
            fixed[1] ? before.displacements_m[index].y : 0.,
            fixed[2] ? before.displacements_m[index].z : 0.,
        };
        require(sameVecExactly(result.load.prescribed_displacements_m[index],
                               expected),
                "pressure load must copy fixed state and zero free components");
    }
    require(sameStateExactly(before, patch.state()),
            "pressure load construction must not mutate a prescribed state");
}

void partialSurfaceCoverageReportsClippedAreaAndCentroid() {
    SmallStrainPatch patch = makeBrick({4, 4, 4});
    const PatchPressure pressure = topPressure(
        {.90, 2., 0.}, {1., 0., 0.}, {0., 0., -1.}, .50, .50, 2.e6);
    const PatchPressureLoad result = makePatchPressureLoad(patch, pressure);
    const double area = .60;
    const Vec3 expected_force{0., -pressure.peak_pressure_pa * area, 0.};
    const Vec3 expected_moment = cross(Vec3{.70, 2., 0.}, expected_force);
    near(result.loaded_area_m2, area, 2.e-10, 2.e-10,
         "partial footprint area");
    near(result.weighted_area_m2, area, 2.e-10, 2.e-10,
         "partial uniform footprint weighted area");
    nearVec(result.resultant_force_n, expected_force, 2.e-5, 2.e-12,
            "partial footprint resultant");
    nearVec(result.reference_moment_n_m, expected_moment, 2.e-7, 2.e-12,
            "partial footprint clipped centroid moment");
}

void invalidPressureIsRejectedWithoutPatchMutation() {
    SmallStrainPatch patch = makeBrick({2, 2, 2});
    const PatchState before = patch.state();
    const PatchPressure valid = topPressure(
        {}, {1., 0., 0.}, {0., 0., -1.}, .50, .50, 1.e6);
    auto requireUnchanged = [&] {
        require(sameStateExactly(before, patch.state()),
                "invalid pressure construction must not mutate patch state");
    };

    PatchPressure zero_axis = valid;
    zero_axis.axis_u = {};
    requireInvalid([&] { (void)makePatchPressureLoad(patch, zero_axis); },
                   "zero pressure axis must be rejected");
    requireUnchanged();

    PatchPressure invalid_profile = valid;
    invalid_profile.profile = static_cast<PatchPressureProfile>(255);
    requireInvalid([&] { (void)makePatchPressureLoad(patch, invalid_profile); },
                   "unknown pressure profile must be rejected");
    requireUnchanged();

    PatchPressure nonorthogonal = valid;
    nonorthogonal.axis_v = {1., 0., 0.};
    requireInvalid([&] { (void)makePatchPressureLoad(patch, nonorthogonal); },
                   "nonorthogonal pressure axes must be rejected");
    requireUnchanged();

    PatchPressure nonfinite = valid;
    nonfinite.peak_pressure_pa = std::numeric_limits<double>::quiet_NaN();
    requireInvalid([&] { (void)makePatchPressureLoad(patch, nonfinite); },
                   "nonfinite pressure must be rejected");
    requireUnchanged();

    PatchPressure nonpositive_width = valid;
    nonpositive_width.half_width_m = 0.;
    requireInvalid([&] { (void)makePatchPressureLoad(patch, nonpositive_width); },
                   "nonpositive pressure width must be rejected");
    requireUnchanged();

    PatchPressure outside = valid;
    outside.center_m.y = 2.5;
    requireInvalid([&] { (void)makePatchPressureLoad(patch, outside); },
                   "pressure with no boundary intersection must be rejected");
    requireUnchanged();
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"uniform pressure analytical resultant and moment",
         uniformPressureHasAnalyticalAreaForceAndMoment},
        {"smooth pressure analytical effective area",
         smoothPressureHasAnalyticalEffectiveArea},
        {"nonaligned clipped pressure linear resultants",
         nonAlignedRectangleAcrossGridPreservesLinearResultants},
        {"rigid pressure translation and rotation covariance",
         rigidTranslationAndRotationPreservePressureCovariance},
        {"pressure fixed displacement preservation",
         pressurePreservesFixedDisplacementsAndFreeZeros},
        {"partial pressure surface clipping",
         partialSurfaceCoverageReportsClippedAreaAndCentroid},
        {"invalid pressure rollback and validation",
         invalidPressureIsRejectedWithoutPatchMutation},
    };

    unsigned passed = 0U;
    for (const auto &[name, test] : tests) {
        try {
            test();
            ++passed;
            std::cout << "PASS " << name << '\n';
        } catch (const std::exception &error) {
            std::cerr << "FAIL " << name << ": " << error.what() << '\n';
            return EXIT_FAILURE;
        }
    }
    std::cout << passed << " patch-pressure tests passed\n";
    return EXIT_SUCCESS;
}
