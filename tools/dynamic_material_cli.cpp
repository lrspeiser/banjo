#include "MaterialJson.hpp"
#include "physics/SpherePatchWorld.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <limits>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

using namespace banjo;
using banjo::material_json::Json;
namespace {
constexpr std::size_t kMaximumInputBytes = 256 * 1024;
constexpr std::size_t kMaximumOutputBytes = 64 * 1024 * 1024;
constexpr std::uint64_t kMaximumElementVisits = 100000000;
constexpr std::uint64_t kMaximumGeometryQueries = 100000000;
constexpr std::uint64_t kMaximumGeometryIterations = 100000000;

Json vec(Vec3 value) { return Json::array({value.x, value.y, value.z}); }

struct Request {
    Json original;
    std::vector<material_json::Material> materials;
    Vec3 dimensions;
    unsigned refinement{};
    double radius{}, sphere_density{}, clearance{}, offset_x{}, offset_z{}, speed{};
    double duration{}, energy_budget{};
    unsigned maximum_step_calls{};
};

double bounded(const Json &value, double low, double high, const char *message) {
    const double number = material_json::finiteNumber(value);
    material_json::require(number >= low && number <= high, message);
    return number;
}

unsigned boundedInteger(const Json &value, unsigned low, unsigned high, const char *message) {
    material_json::require(value.is_number_integer(), message);
    const auto number = value.get<std::int64_t>();
    material_json::require(number >= low && number <= high, message);
    return static_cast<unsigned>(number);
}

Request parseRequest(const Json &json) {
    material_json::exactKeys(json, {"schema", "materials", "dimensions_m", "mesh_refinement",
                                    "sphere", "duration_s", "energy_budget_j",
                                    "max_step_calls"});
    material_json::require(json["schema"] == "banjo.dynamic-material-request.v1",
                           "Unsupported request schema");
    const auto &materials = json["materials"];
    material_json::require(materials.is_array() && !materials.empty() && materials.size() <= 3,
                           "Materials must contain 1..3 descriptors");
    Request result;
    result.original = json;
    for (const auto &descriptor : materials) {
        auto material = material_json::parseMaterial(descriptor);
        const double maximum_strain = material.law.kind == SmallStrainLawKind::J2Plastic
            ? material.law.j2.maximum_total_strain_norm
            : material.law.maximum_total_strain_norm;
        material_json::require(material.density_kg_m3 >= 1 && material.density_kg_m3 <= 30000,
                               "Dynamic material density must be 1..30000 kg/m3");
        material_json::require(maximum_strain <= .1,
                               "Dynamic maximum_total_strain_norm must be at most 0.1");
        result.materials.push_back(std::move(material));
    }
    for (std::size_t i = 0; i < result.materials.size(); ++i)
        for (std::size_t j = i + 1; j < result.materials.size(); ++j)
            material_json::require(result.materials[i].id != result.materials[j].id,
                                   "Duplicate material_id");
    const auto dimensions = material_json::triple(json["dimensions_m"]);
    result.dimensions = {dimensions[0], dimensions[1], dimensions[2]};
    for (double entry : dimensions)
        material_json::require(entry >= .01 && entry <= .2, "Invalid brick dimension");
    result.refinement = boundedInteger(json["mesh_refinement"], 1, 2,
                                       "Invalid mesh refinement");
    const auto &sphere = json["sphere"];
    material_json::exactKeys(sphere, {"radius_m", "density_kg_m3", "clearance_m",
                                      "offset_xz_m", "speed_m_s"});
    result.radius = bounded(sphere["radius_m"], .002, .03, "Invalid sphere radius");
    result.sphere_density = bounded(sphere["density_kg_m3"], 1, 30000,
                                    "Invalid sphere density");
    result.clearance = bounded(sphere["clearance_m"], 0, .005,
                               "Invalid sphere clearance");
    const auto offset = sphere["offset_xz_m"];
    material_json::require(offset.is_array() && offset.size() == 2,
                           "Sphere offset_xz_m requires two coordinates");
    result.offset_x = material_json::finiteNumber(offset[0]);
    result.offset_z = material_json::finiteNumber(offset[1]);
    material_json::require(std::abs(result.offset_x) <= result.dimensions.x * .5 - result.radius &&
                               std::abs(result.offset_z) <= result.dimensions.z * .5 - result.radius,
                           "Sphere footprint lies outside brick top");
    result.speed = bounded(sphere["speed_m_s"], 0, .2, "Invalid sphere speed");
    result.duration = bounded(json["duration_s"], .001, .1, "Invalid duration");
    result.energy_budget = bounded(json["energy_budget_j"], 1.e-9, 1.e-3,
                                   "Invalid energy budget");
    result.maximum_step_calls = boundedInteger(json["max_step_calls"], 3, 200000,
                                               "Invalid step-call budget");
    return result;
}

double maximumPlasticStrain(const DynamicPatch &patch) {
    double maximum = 0;
    for (const auto &state : patch.patch().state().material_points)
        maximum = std::max(maximum, state.equivalent_plastic_strain);
    return maximum;
}

Json errorEstimate(const SpherePatchErrorEstimate &error) {
    return {{"position_m", error.position_m},
            {"velocity_m_s", error.velocity_m_s},
            {"strain", error.strain},
            {"energy_disagreement_j", error.energy_disagreement_j},
            {"absolute_energy_residual_j", error.absolute_energy_residual_j},
            {"normalized", error.normalized}};
}

Json runCase(const Request &request, const material_json::Material &material) {
    const auto resolution = std::array<unsigned, 3>{2 * request.refinement,
                                                     request.refinement,
                                                     2 * request.refinement};
    auto definition = makeTetrahedralBrick(request.dimensions, resolution,
                                           {material.law, material.density_kg_m3});
    for (std::size_t i = 0; i < definition.reference_positions_m.size(); ++i)
        if (definition.reference_positions_m[i].y == 0)
            definition.fixed_components[i] = {true, true, true};
    const double pi = std::acos(-1.);
    const double sphere_mass = 4. / 3 * pi * request.radius * request.radius * request.radius *
                               request.sphere_density;
    const Vec3 center{request.offset_x,
                      request.dimensions.y + request.radius + request.clearance,
                      request.offset_z};
    SpherePatchWorld world(
        definition, {center, {0, -request.speed, 0}, {}, request.radius, sphere_mass},
        {.integrator = DynamicPatchIntegrator::VelocityVerlet},
        {.friction_coefficient = .15,
         .contact_margin_m = 1.e-6,
         .maximum_penetration_m = 1.e-5});
    DynamicPatchLoad load;
    load.nodal_forces_n.resize(definition.reference_positions_m.size());
    load.gravity_m_s2 = {0, -9.81, 0};
    SpherePatchAdvanceOptions options;
    options.error = {.position_m = 1.e-4,
                     .velocity_m_s = 1.,
                     .strain = .1,
                     .energy_disagreement_j = 1.e-4,
                     .absolute_energy_residual_j = request.energy_budget,
                     .reference_time_s = .1};
    options.initial_trial_dt_s = std::min(1.e-4, world.material().stableTimeStepLimitS());
    options.maximum_trial_dt_s = world.material().stableTimeStepLimitS();
    options.minimum_trial_dt_s = 1.e-11;
    options.maximum_step_calls = request.maximum_step_calls;
    options.maximum_reserved_element_visits = kMaximumElementVisits;
    options.maximum_geometry_queries = kMaximumGeometryQueries;
    options.maximum_geometry_iterations = kMaximumGeometryIterations;

    Json result{{"material_id", material.id},
                {"material", material.descriptor},
                {"status", "complete"},
                {"mesh", {{"reference_positions_m", Json::array()},
                           {"tetrahedra", Json::array()},
                           {"boundary_triangles", Json::array()}}},
                {"sphere_radius_m", request.radius},
                {"sphere_mass_kg", sphere_mass},
                {"frames", Json::array()}};
    for (Vec3 position : definition.reference_positions_m)
        result["mesh"]["reference_positions_m"].push_back(vec(position));
    for (const auto &tet : definition.elements)
        result["mesh"]["tetrahedra"].push_back(tet.nodes);
    for (const auto &triangle : world.material().patch().boundaryTriangles())
        result["mesh"]["boundary_triangles"].push_back(triangle);
    auto frame = [&] {
        Json item{{"time_s", world.material().state().time_s},
                  {"sphere_center_m", vec(world.sphere().center_m)},
                  {"sphere_velocity_m_s", vec(world.sphere().velocity_m_s)},
                  {"positions_m", Json::array()},
                  {"maximum_equivalent_plastic_strain", maximumPlasticStrain(world.material())},
                  {"plastic_dissipation_j", world.material().report().plastic_dissipation_j}};
        for (Vec3 position : world.material().patch().positionsM())
            item["positions_m"].push_back(vec(position));
        result["frames"].push_back(std::move(item));
    };
    frame();
    const double frame_interval = std::min(.001, request.duration);
    double elapsed = 0, absolute_residual = 0, signed_residual = 0, external_work = 0,
           contact_dissipation = 0, contact_reserve = 0, peak_upward = 0,
           peak_displacement = 0, minimum_step = 0, maximum_error = 0, suggested_dt =
               options.initial_trial_dt_s;
    std::uint64_t calls = 0, accepted_segments = 0, rejected_segments = 0,
                  element_visits = 0, geometry_queries = 0, geometry_iterations = 0,
                  contacts = 0;
    SpherePatchAdvanceReport failure;
    std::string failure_error;
    const auto started = std::chrono::steady_clock::now();
    for (unsigned frame_index = 1; elapsed < request.duration; ++frame_index) {
        if (calls >= request.maximum_step_calls || element_visits >= kMaximumElementVisits ||
            geometry_queries >= kMaximumGeometryQueries ||
            geometry_iterations >= kMaximumGeometryIterations) {
            failure_error = "Recording cumulative work budget exhausted";
            break;
        }
        const double target = std::min(request.duration, frame_index * frame_interval);
        options.maximum_step_calls = static_cast<unsigned>(request.maximum_step_calls - calls);
        options.maximum_reserved_element_visits = kMaximumElementVisits - element_visits;
        options.maximum_geometry_queries = kMaximumGeometryQueries - geometry_queries;
        options.maximum_geometry_iterations = kMaximumGeometryIterations - geometry_iterations;
        options.initial_trial_dt_s = suggested_dt;
        const auto advance = world.advance(target - elapsed, load, options, {}, load.gravity_m_s2);
        calls += advance.step_calls;
        accepted_segments += advance.accepted_segments;
        rejected_segments += advance.rejected_segments;
        element_visits += advance.reserved_element_visits;
        geometry_queries += advance.geometry_queries;
        geometry_iterations += advance.geometry_iterations;
        if (!advance.accepted) {
            failure = advance;
            failure_error = advance.error;
            break;
        }
        contacts += advance.impulse_contacts;
        elapsed = target;
        absolute_residual += advance.absolute_energy_residual_j;
        signed_residual += advance.signed_energy_residual_j;
        external_work += advance.external_work_j;
        contact_dissipation += advance.contact_dissipation_j;
        contact_reserve += advance.contact_energy_reserve_spent_j;
        if (minimum_step == 0 || advance.minimum_accepted_step_s < minimum_step)
            minimum_step = advance.minimum_accepted_step_s;
        maximum_error = std::max(maximum_error, advance.maximum_accepted_error);
        suggested_dt = advance.suggested_trial_dt_s;
        peak_upward = std::max(peak_upward, world.sphere().velocity_m_s.y);
        for (Vec3 displacement : world.material().patch().state().displacements_m)
            peak_displacement = std::max(peak_displacement, length(displacement));
        frame();
    }
    const bool complete = failure_error.empty() && elapsed >= request.duration;
    result["status"] = complete ? "complete" : "solver_limit";
    if (!complete) result["error"] = failure_error;
    const auto final = world.material().report();
    result["summary"] = {
        {"requested_duration_s", request.duration}, {"completed_duration_s", elapsed},
        {"absolute_energy_residual_j", absolute_residual},
        {"signed_energy_residual_j", signed_residual}, {"energy_budget_j", request.energy_budget},
        {"external_work_j", external_work}, {"contact_dissipation_j", contact_dissipation},
        {"contact_energy_reserve_spent_j", contact_reserve},
        {"plastic_dissipation_j", final.plastic_dissipation_j},
        {"sampled_peak_upward_speed_m_s", peak_upward},
        {"sampled_peak_displacement_m", peak_displacement},
        {"minimum_accepted_step_s", minimum_step}, {"maximum_accepted_error", maximum_error},
        {"suggested_trial_dt_s", suggested_dt}, {"step_calls", calls},
        {"accepted_segments", accepted_segments}, {"rejected_segments", rejected_segments},
        {"geometry_queries", geometry_queries}, {"geometry_iterations", geometry_iterations},
        {"reserved_element_visits", element_visits}, {"accepted_contacts", contacts},
        {"last_error", errorEstimate(failure.last_error)},
        {"minimum_step_error", errorEstimate(failure.minimum_step_error)},
        {"wall_ms", std::chrono::duration<double, std::milli>(
                        std::chrono::steady_clock::now() - started).count()}};
    return result;
}
} // namespace

int main() {
    try {
        std::string input;
        char character;
        while (std::cin.get(character)) {
            material_json::require(input.size() < kMaximumInputBytes, "Input exceeds 256 KiB");
            input.push_back(character);
        }
        const Request request = parseRequest(material_json::parseStrict(input));
        Json output{{"schema", "banjo.dynamic-material-playback.v1"},
                    {"physical_response_validated", false},
                    {"status", "complete"},
                    {"request", request.original},
                    {"scope", "CPU small-strain tetrahedral reference with sphere contact; no "
                              "fracture, finite strain, spatial convergence or material calibration"},
                    {"solver_options", {{"integrator", "velocity_verlet"},
                                        {"gravity_m_s2", vec({0, -9.81, 0})},
                                        {"friction_coefficient", .15},
                                        {"contact_margin_m", 1.e-6},
                                        {"maximum_penetration_m", 1.e-5},
                                        {"frame_interval_s", std::min(.001, request.duration)},
                                        {"error_limits", {{"position_m", 1.e-4},
                                                          {"velocity_m_s", 1.},
                                                          {"strain", .1},
                                                          {"energy_disagreement_j", 1.e-4},
                                                          {"absolute_energy_residual_j", request.energy_budget},
                                                          {"reference_time_s", .1}}},
                                        {"minimum_trial_dt_s", 1.e-11},
                                        {"maximum_step_calls", request.maximum_step_calls},
                                        {"maximum_reserved_element_visits", kMaximumElementVisits},
                                        {"maximum_geometry_queries", kMaximumGeometryQueries},
                                        {"maximum_geometry_iterations", kMaximumGeometryIterations}}},
                    {"cases", Json::array()}};
        for (const auto &material : request.materials) {
            auto item = runCase(request, material);
            if (item["status"] != "complete") output["status"] = "solver_limit";
            output["cases"].push_back(std::move(item));
        }
        const std::string serialized = output.dump();
        material_json::require(serialized.size() <= kMaximumOutputBytes,
                               "Output exceeds 64 MiB");
        std::cout << serialized << '\n';
        return 0;
    } catch (const std::exception &) {
        std::cout << Json({{"status", "rejected"},
                          {"error", "Invalid dynamic material request or bounded output"}}).dump()
                  << '\n';
        return 1;
    }
}
