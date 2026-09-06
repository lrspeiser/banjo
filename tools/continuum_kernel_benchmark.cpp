#include "physics/PatchPressure.hpp"
#include "physics/SmallStrainPatch.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

using namespace banjo;
using json = nlohmann::json;

constexpr unsigned kRampSteps = 32U;
constexpr unsigned kBaseStep = 24U;
constexpr unsigned kTargetStep = 25U;
constexpr unsigned kWarmupRuns = 3U;
constexpr std::uint64_t kMaximumElementVisits = 12'000'000U;

struct Options {
    unsigned resolution{8U};
    unsigned samples{100U};
    std::filesystem::path output;
};

struct SampleTiming {
    double restore_ms{};
    double solve_ms{};
    double combined_ms{};
};

struct BackendRun {
    PatchState final_state;
    PatchEvaluation final_evaluation;
    PatchSolveResult final_result;
    std::vector<SampleTiming> samples;
    bool all_accepted{};
    bool repeated_state_exact{};
    bool state_exact_all{};
    std::size_t states_checked{};
};

[[noreturn]] void invalid(const std::string &message) {
    throw std::invalid_argument(message);
}

PatchMaterial material(unsigned id) {
    PatchMaterial result;
    auto &law = result.law;
    law.maximum_total_strain_norm = .05;
    if (id == 0U) {
        result.density_kg_m3 = 2500.;
        law.kind = SmallStrainLawKind::IsotropicElastic;
        law.young_modulus_pa[0] = 70.e9;
        law.poisson_xy_yz_zx[0] = .22;
    } else if (id == 1U) {
        result.density_kg_m3 = 700.;
        law.kind = SmallStrainLawKind::OrthotropicElastic;
        law.young_modulus_pa = {.7e9, 12.e9, 1.e9};
        law.poisson_xy_yz_zx = {.025, .30, .30};
        law.shear_xy_yz_zx_pa = {.6e9, .7e9, .1e9};
    } else {
        result.density_kg_m3 = 7870.;
        law.kind = SmallStrainLawKind::J2Plastic;
        law.j2 = {ContinuumConstitutiveFamily::SmallStrainIsotropicJ2,
                  211.e9, .30, 250.e6, 1.e9, .05};
    }
    return result;
}

std::string materialId(unsigned id) {
    constexpr std::array<std::string_view, 3> ids{"glass", "oak", "iron"};
    return std::string(ids.at(id));
}

PatchDefinition definitionFor(unsigned material_id, unsigned resolution) {
    PatchDefinition definition = makeTetrahedralBrick(
        {.04, .02, .04}, {resolution, std::max(1U, resolution / 2U), resolution},
        material(material_id));
    for (std::size_t index = 0; index < definition.reference_positions_m.size();
         ++index) {
        if (definition.reference_positions_m[index].y == 0.) {
            definition.fixed_components[index] = {true, true, true};
        }
    }
    return definition;
}

PatchPressure pressureFor(double peak_pressure_pa) {
    PatchPressure pressure;
    pressure.center_m = {0., .02, 0.};
    pressure.peak_pressure_pa = peak_pressure_pa;
    pressure.profile = PatchPressureProfile::Uniform;
    return pressure;
}

PatchSolveOptions solveOptions(PatchLinearBackend backend) {
    PatchSolveOptions options;
    options.maximum_element_visits = kMaximumElementVisits;
    options.maximum_tangent_block_visits = 64'000'000U;
    options.linear_backend = backend;
    return options;
}

PatchLoad scaledLoad(const PatchLoad &source, double scale) {
    PatchLoad result = source;
    for (Vec3 &force : result.nodal_forces_n) {
        force *= scale;
    }
    return result;
}

void requireAccepted(const PatchSolveResult &result, std::string_view material_id,
                     std::string_view backend, std::string_view stage) {
    if (!result.accepted) {
        throw std::runtime_error(std::string(material_id) + " / " +
                                 std::string(backend) + " " + std::string(stage) +
                                 " rejected: " + result.error);
    }
}

bool finite(double value) { return std::isfinite(value); }

bool finite(Vec3 value) {
    return finite(value.x) && finite(value.y) && finite(value.z);
}

bool finite(const SymmetricTensor3 &value) {
    return finite(value.xx) && finite(value.yy) && finite(value.zz) &&
           finite(value.xy) && finite(value.yz) && finite(value.zx);
}

bool finite(const J2State &value) {
    return finite(value.total_strain) && finite(value.plastic_strain) &&
           finite(value.equivalent_plastic_strain) &&
           finite(value.plastic_dissipation_j_m3);
}

bool finite(const PatchState &state) {
    if (!finite(state.accumulated_trapezoidal_external_work_j) ||
        !finite(state.accumulated_backward_euler_external_work_j)) {
        return false;
    }
    for (const Vec3 value : state.displacements_m) {
        if (!finite(value)) return false;
    }
    for (const J2State value : state.material_points) {
        if (!finite(value)) return false;
    }
    for (const Vec3 value : state.last_nodal_forces_n) {
        if (!finite(value)) return false;
    }
    return true;
}

bool finite(const SmallStrainResponse &response) {
    if (!finite(response.state) || !finite(response.stress_pa) ||
        !finite(response.stored_free_energy_j_m3) ||
        !finite(response.plastic_dissipation_j_m3) ||
        !finite(response.backward_euler_work_excess_j_m3)) {
        return false;
    }
    for (const SymmetricTensor3 tangent : response.tangent_columns) {
        if (!finite(tangent)) return false;
    }
    return true;
}

bool finite(const PatchEvaluation &evaluation) {
    if (!finite(evaluation.stored_free_energy_j) ||
        !finite(evaluation.plastic_dissipation_j) ||
        !finite(evaluation.backward_euler_work_excess_j) ||
        !finite(evaluation.maximum_displacement_gradient_norm)) {
        return false;
    }
    for (const Vec3 force : evaluation.internal_forces_n) {
        if (!finite(force)) return false;
    }
    for (const SmallStrainResponse &response : evaluation.responses) {
        if (!finite(response)) return false;
    }
    return true;
}

bool finite(const PatchSolveResult &result) {
    return finite(result.wall_ms) && finite(result.free_force_residual_n) &&
           finite(result.force_tolerance_n) &&
           finite(result.stored_free_energy_j) &&
           finite(result.plastic_dissipation_j) &&
           finite(result.trapezoidal_external_work_increment_j) &&
           finite(result.backward_euler_external_work_increment_j) &&
           finite(result.stored_free_energy_increment_j) &&
           finite(result.plastic_dissipation_increment_j) &&
           finite(result.trapezoidal_work_residual_j) &&
           finite(result.backward_euler_balance_residual_j) &&
           finite(result.constitutive_backward_euler_excess_j) &&
           finite(result.maximum_displacement_gradient_norm) &&
           finite(result.applied_force_n) && finite(result.support_reaction_n) &&
           finite(result.reference_moment_residual_n_m) &&
           std::all_of(result.reactions_n.begin(), result.reactions_n.end(),
                       [](Vec3 value) { return finite(value); });
}

bool sameVecExactly(Vec3 first, Vec3 second) {
    return first.x == second.x && first.y == second.y && first.z == second.z;
}

bool sameTensorExactly(const SymmetricTensor3 &first,
                       const SymmetricTensor3 &second) {
    return first.xx == second.xx && first.yy == second.yy &&
           first.zz == second.zz && first.xy == second.xy &&
           first.yz == second.yz && first.zx == second.zx;
}

bool sameJ2StateExactly(const J2State &first, const J2State &second) {
    return sameTensorExactly(first.total_strain, second.total_strain) &&
           sameTensorExactly(first.plastic_strain, second.plastic_strain) &&
           first.equivalent_plastic_strain == second.equivalent_plastic_strain &&
           first.plastic_dissipation_j_m3 == second.plastic_dissipation_j_m3;
}

bool samePatchStateExactly(const PatchState &first, const PatchState &second) {
    if (!finite(first) || !finite(second) ||
        first.displacements_m.size() != second.displacements_m.size() ||
        first.material_points.size() != second.material_points.size() ||
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
    for (std::size_t index = 0; index < first.material_points.size(); ++index) {
        if (!sameJ2StateExactly(first.material_points[index],
                                second.material_points[index])) {
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

double percentile(std::vector<double> values, double fraction) {
    if (values.empty()) {
        throw std::logic_error("cannot calculate percentile of empty samples");
    }
    std::sort(values.begin(), values.end());
    const std::size_t rank = static_cast<std::size_t>(std::ceil(
        fraction * static_cast<double>(values.size())));
    return values[std::clamp(rank == 0U ? 0U : rank - 1U,
                             std::size_t{0}, values.size() - 1U)];
}

json timingJson(const std::vector<SampleTiming> &samples) {
    std::vector<double> restore, solve, combined;
    restore.reserve(samples.size());
    solve.reserve(samples.size());
    combined.reserve(samples.size());
    for (const SampleTiming sample : samples) {
        restore.push_back(sample.restore_ms);
        solve.push_back(sample.solve_ms);
        combined.push_back(sample.combined_ms);
    }
    const auto percentiles = [](const std::vector<double> &values) {
        return json{{"p50_ms", percentile(values, .50)},
                    {"p95_ms", percentile(values, .95)},
                    {"p99_ms", percentile(values, .99)}};
    };
    return {{"restore", percentiles(restore)},
            {"solve", percentiles(solve)},
            {"combined", percentiles(combined)}};
}

double maxVecDifference(const std::vector<Vec3> &first,
                        const std::vector<Vec3> &second) {
    if (first.size() != second.size()) {
        throw std::logic_error("backend displacement layouts differ");
    }
    double result = 0.;
    for (std::size_t index = 0; index < first.size(); ++index) {
        result = std::max(result, std::abs(first[index].x - second[index].x));
        result = std::max(result, std::abs(first[index].y - second[index].y));
        result = std::max(result, std::abs(first[index].z - second[index].z));
    }
    return result;
}

double maxTensorDifference(const SymmetricTensor3 &first,
                           const SymmetricTensor3 &second) {
    return std::max({std::abs(first.xx - second.xx),
                     std::abs(first.yy - second.yy),
                     std::abs(first.zz - second.zz),
                     std::abs(first.xy - second.xy),
                     std::abs(first.yz - second.yz),
                     std::abs(first.zx - second.zx)});
}

double maxStateStrainDifference(const PatchState &first,
                                const PatchState &second) {
    if (first.material_points.size() != second.material_points.size()) {
        throw std::logic_error("backend material-point layouts differ");
    }
    double result = 0.;
    for (std::size_t index = 0; index < first.material_points.size(); ++index) {
        result = std::max(result,
                          maxTensorDifference(first.material_points[index].total_strain,
                                              second.material_points[index].total_strain));
    }
    return result;
}

double maxPlasticStrainDifference(const PatchState &first,
                                  const PatchState &second) {
    if (first.material_points.size() != second.material_points.size()) {
        throw std::logic_error("backend material-point layouts differ");
    }
    double result = 0.;
    for (std::size_t index = 0; index < first.material_points.size(); ++index) {
        result = std::max(
            result,
            maxTensorDifference(first.material_points[index].plastic_strain,
                                second.material_points[index].plastic_strain));
    }
    return result;
}

double maxEquivalentPlasticStrainDifference(const PatchState &first,
                                            const PatchState &second) {
    if (first.material_points.size() != second.material_points.size()) {
        throw std::logic_error("backend material-point layouts differ");
    }
    double result = 0.;
    for (std::size_t index = 0; index < first.material_points.size(); ++index) {
        result = std::max(
            result,
            std::abs(first.material_points[index].equivalent_plastic_strain -
                     second.material_points[index].equivalent_plastic_strain));
    }
    return result;
}

double maxTangentDifference(const PatchEvaluation &first,
                            const PatchEvaluation &second) {
    if (first.responses.size() != second.responses.size()) {
        throw std::logic_error("backend response layouts differ");
    }
    double result = 0.;
    for (std::size_t response = 0; response < first.responses.size(); ++response) {
        for (std::size_t column = 0; column < first.responses[response].tangent_columns.size();
             ++column) {
            result = std::max(result,
                              maxTensorDifference(
                                  first.responses[response].tangent_columns[column],
                                  second.responses[response].tangent_columns[column]));
        }
    }
    return result;
}

double maxReactionDifference(const PatchSolveResult &first,
                             const PatchSolveResult &second) {
    return maxVecDifference(first.reactions_n, second.reactions_n);
}

json resultStats(const BackendRun &run, unsigned warmups, unsigned samples,
                 PatchLinearBackend backend) {
    const auto &result = run.final_result;
    return {
        {"backend", backend == PatchLinearBackend::MatrixFreeReference
                         ? "matrix-free"
                         : "assembled-block-csr"},
        {"warmup_runs", warmups},
        {"timed_samples", samples},
        {"all_accepted", run.all_accepted},
        {"accepted", result.accepted},
        {"last_newton_iterations", result.newton_iterations},
        {"last_cg_iterations", result.cg_iterations},
        {"last_line_search_trials", result.line_search_trials},
        {"last_element_visits", result.element_visits},
        {"last_tangent_block_count", result.tangent_block_count},
        {"last_tangent_assembly_element_visits",
         result.tangent_assembly_element_visits},
        {"last_matrix_free_matvec_element_visits",
         result.matrix_free_matvec_element_visits},
        {"last_assembled_matvec_block_visits",
         result.assembled_matvec_block_visits},
        {"last_solver_wall_ms", result.wall_ms},
        {"metrics", timingJson(run.samples)},
        {"repeated_state_exact", run.repeated_state_exact},
        {"states_checked", run.states_checked},
        {"state_exact_all", run.state_exact_all},
    };
}

BackendRun benchmarkBackend(const PatchDefinition &definition,
                            const PatchState &base_state,
                            const PatchLoad &target_load,
                            PatchLinearBackend backend,
                            std::string_view material_id,
                            unsigned samples) {
    SmallStrainPatch patch(definition);
    const PatchSolveOptions options = solveOptions(backend);
    patch.restoreState(base_state, .01);
    BackendRun run;
    run.samples.reserve(samples);
    run.state_exact_all = true;
    PatchState first_accepted_state;
    bool have_first_accepted_state = false;
    auto trial = [&] {
        const auto restore_started = std::chrono::steady_clock::now();
        patch.restoreState(base_state, .01);
        const auto restore_finished = std::chrono::steady_clock::now();
        const auto solve_started = restore_finished;
        const PatchSolveResult result = patch.solveLoad(target_load, options);
        const auto solve_finished = std::chrono::steady_clock::now();
        if (!finite(result)) {
            throw std::runtime_error(std::string(material_id) +
                                     " produced nonfinite solve fields");
        }
        requireAccepted(result, material_id,
                        backend == PatchLinearBackend::MatrixFreeReference
                            ? "matrix-free"
                            : "assembled-block-csr",
                        "target solve");
        const PatchState observed_state = patch.state();
        const PatchEvaluation observed_evaluation =
            patch.evaluate(observed_state.displacements_m);
        if (!finite(observed_state) || !finite(observed_evaluation)) {
            throw std::runtime_error(std::string(material_id) +
                                     " produced nonfinite post-solve state");
        }
        ++run.states_checked;
        if (!have_first_accepted_state) {
            first_accepted_state = observed_state;
            have_first_accepted_state = true;
        } else if (!samePatchStateExactly(first_accepted_state,
                                          observed_state)) {
            run.state_exact_all = false;
            throw std::runtime_error(std::string(material_id) +
                                     " repeated accepted state was not exact");
        }
        return std::pair<SampleTiming, PatchSolveResult>{
            {std::chrono::duration<double, std::milli>(restore_finished -
                                                       restore_started)
                     .count(),
             std::chrono::duration<double, std::milli>(solve_finished -
                                                       solve_started)
                     .count(),
             std::chrono::duration<double, std::milli>(solve_finished -
                                                       restore_started)
                     .count()},
            result};
    };
    for (unsigned warmup = 0; warmup < kWarmupRuns; ++warmup) {
        (void)trial();
    }
    run.all_accepted = true;
    for (unsigned sample = 0; sample < samples; ++sample) {
        auto [timing, result] = trial();
        run.samples.push_back(timing);
        run.final_result = result;
    }
    run.final_state = patch.state();
    if (!finite(run.final_state)) {
        throw std::runtime_error(std::string(material_id) +
                                 " produced nonfinite backend state");
    }
    run.final_evaluation = patch.evaluate(run.final_state.displacements_m);
    const auto first = trial();
    const PatchState first_state = patch.state();
    const auto second = trial();
    const PatchState second_state = patch.state();
    run.repeated_state_exact = samePatchStateExactly(first_state, second_state);
    if (!run.repeated_state_exact || !first.second.accepted || !second.second.accepted) {
        throw std::runtime_error(std::string(material_id) +
                                 " repeated backend state was not exact");
    }
    return run;
}

json parityJson(const BackendRun &matrix_free, const BackendRun &assembled) {
    return {
        {"max_displacement_difference_m",
         maxVecDifference(matrix_free.final_state.displacements_m,
                          assembled.final_state.displacements_m)},
        {"max_total_strain_difference",
         maxStateStrainDifference(matrix_free.final_state,
                                  assembled.final_state)},
        {"max_plastic_strain_tensor_difference",
         maxPlasticStrainDifference(matrix_free.final_state,
                                    assembled.final_state)},
        {"max_equivalent_plastic_strain_difference",
         maxEquivalentPlasticStrainDifference(matrix_free.final_state,
                                              assembled.final_state)},
        {"max_tangent_D_difference_pa",
         maxTangentDifference(matrix_free.final_evaluation,
                              assembled.final_evaluation)},
        {"stored_free_energy_difference_j",
         std::abs(matrix_free.final_evaluation.stored_free_energy_j -
                  assembled.final_evaluation.stored_free_energy_j)},
        {"plastic_dissipation_difference_j",
         std::abs(matrix_free.final_evaluation.plastic_dissipation_j -
                  assembled.final_evaluation.plastic_dissipation_j)},
        {"trapezoidal_work_difference_j",
         std::abs(matrix_free.final_state.accumulated_trapezoidal_external_work_j -
                  assembled.final_state.accumulated_trapezoidal_external_work_j)},
        {"backward_euler_work_difference_j",
         std::abs(matrix_free.final_state.accumulated_backward_euler_external_work_j -
                  assembled.final_state.accumulated_backward_euler_external_work_j)},
        {"max_reaction_difference_n",
         maxReactionDifference(matrix_free.final_result, assembled.final_result)},
        {"applied_force_difference_n",
         length(matrix_free.final_result.applied_force_n -
                assembled.final_result.applied_force_n)},
        {"support_reaction_difference_n",
         length(matrix_free.final_result.support_reaction_n -
                assembled.final_result.support_reaction_n)},
        {"free_force_residual_difference_n",
         std::abs(matrix_free.final_result.free_force_residual_n -
                  assembled.final_result.free_force_residual_n)},
        {"trapezoidal_work_residual_difference_j",
         std::abs(matrix_free.final_result.trapezoidal_work_residual_j -
                  assembled.final_result.trapezoidal_work_residual_j)},
        {"backward_euler_balance_residual_difference_j",
         std::abs(matrix_free.final_result.backward_euler_balance_residual_j -
                  assembled.final_result.backward_euler_balance_residual_j)},
        {"constitutive_backward_euler_excess_difference_j",
         std::abs(matrix_free.final_result.constitutive_backward_euler_excess_j -
                  assembled.final_result.constitutive_backward_euler_excess_j)},
        {"reference_moment_residual_difference_n_m",
         length(matrix_free.final_result.reference_moment_residual_n_m -
                assembled.final_result.reference_moment_residual_n_m)},
    };
}

json benchmarkCase(unsigned material_id, double peak_pressure_pa,
                   unsigned resolution, unsigned samples) {
    const PatchDefinition definition = definitionFor(material_id, resolution);
    SmallStrainPatch base_patch(definition);
    const PatchPressureLoad pressure_load =
        makePatchPressureLoad(base_patch, pressureFor(peak_pressure_pa));
    if (!finite(pressure_load.resultant_force_n) ||
        !finite(pressure_load.reference_moment_n_m) ||
        !finite(pressure_load.loaded_area_m2) ||
        pressure_load.loaded_area_m2 <= 0.) {
        throw std::runtime_error("pressure load produced invalid geometry metrics");
    }
    const PatchLoad unit_load = pressure_load.load;
    const PatchSolveOptions base_options =
        solveOptions(PatchLinearBackend::MatrixFreeReference);
    PatchSolveResult base_result;
    for (unsigned step = 1U; step <= kBaseStep; ++step) {
        base_result = base_patch.solveLoad(
            scaledLoad(unit_load, static_cast<double>(step) /
                                    static_cast<double>(kRampSteps)),
            base_options);
        requireAccepted(base_result, materialId(material_id), "matrix-free",
                        "common base ramp");
    }
    const PatchState base_state = base_patch.state();
    if (!finite(base_state)) {
        throw std::runtime_error("common base contains nonfinite state");
    }
    const PatchLoad target_load = scaledLoad(
        unit_load, static_cast<double>(kTargetStep) / static_cast<double>(kRampSteps));
    const BackendRun matrix_free = benchmarkBackend(
        definition, base_state, target_load, PatchLinearBackend::MatrixFreeReference,
        materialId(material_id), samples);
    const BackendRun assembled = benchmarkBackend(
        definition, base_state, target_load, PatchLinearBackend::AssembledBlockCsr,
        materialId(material_id), samples);

    return {
        {"material_id", materialId(material_id)},
        {"peak_pressure_pa", peak_pressure_pa},
        {"base_pressure_fraction", static_cast<double>(kBaseStep) /
                                        static_cast<double>(kRampSteps)},
        {"target_pressure_fraction", static_cast<double>(kTargetStep) /
                                          static_cast<double>(kRampSteps)},
        {"loaded_area_m2", pressure_load.loaded_area_m2},
        {"weighted_area_m2", pressure_load.weighted_area_m2},
        {"reference_volume_m3", base_patch.referenceVolumeM3()},
        {"mass_kg", base_patch.massKg()},
        {"nodes", definition.reference_positions_m.size()},
        {"tetrahedra", definition.elements.size()},
        {"budgets", json{{"maximum_element_visits", kMaximumElementVisits},
                          {"maximum_tangent_block_visits",
                           base_options.maximum_tangent_block_visits},
                          {"maximum_newton_iterations",
                           base_options.maximum_newton_iterations},
                          {"maximum_cg_iterations",
                           base_options.maximum_cg_iterations},
                          {"maximum_line_search_steps",
                           base_options.maximum_line_search_steps},
                          {"relative_force_tolerance",
                           base_options.relative_force_tolerance},
                          {"absolute_force_tolerance_n",
                           base_options.absolute_force_tolerance_n},
                          {"maximum_displacement_gradient_norm",
                           base_options.maximum_displacement_gradient_norm}}},
        {"common_base", json{{"accepted", base_result.accepted},
                              {"steps", kBaseStep},
                              {"revision", base_state.revision},
                              {"newton_iterations", base_result.newton_iterations},
                              {"cg_iterations", base_result.cg_iterations},
                              {"element_visits", base_result.element_visits}}},
        {"backends", json::array(
                         {resultStats(matrix_free, kWarmupRuns, samples,
                                      PatchLinearBackend::MatrixFreeReference),
                          resultStats(assembled, kWarmupRuns, samples,
                                      PatchLinearBackend::AssembledBlockCsr)})},
        {"backend_state_parity", parityJson(matrix_free, assembled)},
    };
}

std::string platformName() {
#if defined(_WIN32)
    return "windows";
#elif defined(__APPLE__)
    return "macos";
#elif defined(__linux__)
    return "linux";
#else
    return "unknown";
#endif
}

std::string compilerName() {
#if defined(_MSC_VER)
    return "msvc-" + std::to_string(_MSC_VER);
#elif defined(__clang__)
    return "clang-" + std::to_string(__clang_major__) + "." +
           std::to_string(__clang_minor__);
#elif defined(__GNUC__)
    return "gcc-" + std::to_string(__GNUC__) + "." +
           std::to_string(__GNUC_MINOR__);
#else
    return "unknown";
#endif
}

Options parseOptions(int argc, char **argv) {
    Options options;
    bool output_seen = false;
    for (int index = 1; index < argc; ++index) {
        const std::string flag = argv[index];
        if (index + 1 >= argc) {
            invalid("missing value for " + flag);
        }
        const std::string value = argv[++index];
        std::size_t consumed = 0U;
        if (flag == "--resolution") {
            const auto parsed = std::stoul(value, &consumed);
            if (consumed != value.size() ||
                (parsed != 4U && parsed != 8U && parsed != 12U)) {
                invalid("--resolution must be 4, 8, or 12");
            }
            options.resolution = static_cast<unsigned>(parsed);
        } else if (flag == "--samples") {
            const auto parsed = std::stoul(value, &consumed);
            if (consumed != value.size() || parsed < 10U || parsed > 1000U) {
                invalid("--samples must be in [10,1000]");
            }
            options.samples = static_cast<unsigned>(parsed);
        } else if (flag == "--output") {
            if (output_seen || value.empty()) {
                invalid("--output must be specified once with a new path");
            }
            options.output = value;
            output_seen = true;
        } else {
            invalid("unknown option: " + flag);
        }
    }
    if (!output_seen) {
        invalid("--output is required");
    }
    if (std::filesystem::exists(options.output)) {
        invalid("output must be a new path: " + options.output.string());
    }
    return options;
}

} // namespace

int main(int argc, char **argv) {
    try {
        const Options options = parseOptions(argc, argv);
        json report{
            {"schema", "banjo.continuum-kernel-benchmark.v1"},
            {"physics_abi", "banjo-quasistatic-tet-1"},
            {"physical_response_validated", false},
            {"real_time_qualified", false},
            {"scope", "Repeated restored-history quasistatic load increments; timings exclude patch construction, pressure integration, state verification, rendering and world scheduling. Matrix-free runs before assembled in each case."},
            {"toolchain", {{"platform", platformName()},
                            {"compiler", compilerName()},
                            {"cxx_standard", 23}}},
            {"configuration", json{{"resolution", options.resolution},
                                    {"samples", options.samples},
                                    {"warmup_runs", kWarmupRuns},
                                    {"ramp_steps", kRampSteps},
                                    {"base_step", kBaseStep},
                                    {"target_step", kTargetStep},
                                    {"maximum_element_visits",
                                     kMaximumElementVisits},
                                    {"geometry_m", {0.04, 0.02, 0.04}},
                                    {"bottom_boundary", "y == 0 fully clamped"},
                                    {"pressure", "central 20 mm square, uniform"}}},
            {"cases", json::array()},
        };
        const std::array<std::pair<unsigned, double>, 4> cases{{
            {0U, 100.e6}, {1U, 100.e6}, {2U, 100.e6}, {2U, 800.e6}}};
        for (const auto [material_id, peak_pressure_pa] : cases) {
            report["cases"].push_back(benchmarkCase(
                material_id, peak_pressure_pa, options.resolution, options.samples));
        }
        std::ofstream output(options.output,
                             std::ios::binary | std::ios::out | std::ios::noreplace);
        if (!output) {
            throw std::runtime_error("cannot create new benchmark output: " +
                                     options.output.string());
        }
        output << report.dump(2) << '\n';
        output.close();
        if (!output) {
            throw std::runtime_error("cannot write benchmark output: " +
                                     options.output.string());
        }
        std::cout << json{{"output", options.output.string()},
                          {"cases", report["cases"].size()},
                          {"samples", options.samples}}
                         .dump()
                  << '\n';
        return EXIT_SUCCESS;
    } catch (const std::exception &exception) {
        std::cerr << "continuum kernel benchmark error: " << exception.what()
                  << '\n';
        return EXIT_FAILURE;
    }
}
