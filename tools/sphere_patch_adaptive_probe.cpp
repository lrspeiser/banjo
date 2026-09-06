#include "physics/SpherePatchWorld.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>

using namespace banjo;
using nlohmann::json;
namespace {
json vector(Vec3 v) {
    return json::array({v.x, v.y, v.z});
}
json run(bool plastic, double energy_budget, unsigned refinement, bool verlet) {
    SmallStrainLaw law;
    law.kind = plastic ? SmallStrainLawKind::J2Plastic : SmallStrainLawKind::IsotropicElastic;
    law.young_modulus_pa = {1.e6, 1.e6, 1.e6};
    law.poisson_xy_yz_zx = {.25, .25, .25};
    law.shear_xy_yz_zx_pa = {4.e5, 4.e5, 4.e5};
    law.maximum_total_strain_norm = .08;
    law.j2 = {.young_modulus_pa = 1.e6,
              .poisson_ratio = .25,
              .initial_yield_stress_pa = 1200,
              .isotropic_hardening_modulus_pa = 20000,
              .maximum_total_strain_norm = .08};
    auto definition = makeTetrahedralBrick(
        {.08, .02, .08}, {2 * refinement, refinement, 2 * refinement}, {law, 1000});
    for (std::size_t i = 0; i < definition.reference_positions_m.size(); ++i)
        if (definition.reference_positions_m[i].y == 0)
            definition.fixed_components[i] = {true, true, true};
    constexpr double radius = .012;
    const double mass = 4. / 3 * std::acos(-1.) * radius * radius * radius * 7870;
    SpherePatchWorld world(
        definition, {{.007, .0325, .009}, {}, {}, radius, mass},
        {.integrator = verlet ? DynamicPatchIntegrator::VelocityVerlet
                              : DynamicPatchIntegrator::SymplecticEuler},
        {.friction_coefficient = .15, .contact_margin_m = 1.e-6, .maximum_penetration_m = 1.e-5});
    DynamicPatchLoad load;
    load.nodal_forces_n.resize(definition.reference_positions_m.size());
    load.gravity_m_s2 = {0, -9.81, 0};
    SpherePatchAdvanceOptions options;
    options.error = {.position_m = 1.e-4,
                     .velocity_m_s = 1.,
                     .strain = .1,
                     .energy_disagreement_j = 1.e-4,
                     .absolute_energy_residual_j = energy_budget,
                     .reference_time_s = .1};
    options.initial_trial_dt_s = std::min(1.e-4, world.material().stableTimeStepLimitS());
    options.maximum_trial_dt_s = world.material().stableTimeStepLimitS();
    options.minimum_trial_dt_s = 1.e-11;
    options.maximum_step_calls = 200000;
    options.maximum_reserved_element_visits = 100000000;
    options.maximum_geometry_queries = 100000000;
    options.maximum_geometry_iterations = 100000000;
    json result = {
        {"material", plastic ? "fictional_J2_E1MPa_yield1.2kPa" : "fictional_linear_elastic_E1MPa"},
        {"integrator", verlet ? "velocity_verlet" : "symplectic_euler"},
        {"density_kg_m3", 1000},
        {"young_modulus_pa", 1.e6},
        {"poisson_ratio", .25},
        {"yield_stress_pa", plastic ? 1200 : 0},
        {"hardening_modulus_pa", plastic ? 20000 : 0},
        {"mesh_refinement", refinement},
        {"sphere_radius_m", radius},
        {"sphere_mass_kg", mass},
        {"initial_clearance_m", .0005},
        {"gravity_m_s2", vector(load.gravity_m_s2)},
        {"requested_duration_s", .1},
        {"frame_interval_s", .001},
        {"error_limits",
         {{"position_m", options.error.position_m},
          {"velocity_m_s", options.error.velocity_m_s},
          {"strain", options.error.strain},
          {"energy_disagreement_j", options.error.energy_disagreement_j},
          {"absolute_energy_residual_j", energy_budget},
          {"reference_time_s", .1}}},
        {"frames", json::array()}};
    json mesh = {{"reference_positions_m", json::array()}, {"tetrahedra", json::array()}};
    for (auto v : definition.reference_positions_m)
        mesh["reference_positions_m"].push_back(vector(v));
    for (const auto &tet : definition.elements)
        mesh["tetrahedra"].push_back(tet.nodes);
    result["mesh"] = std::move(mesh);
    auto frame = [&] {
        json f = {{"time_s", world.material().state().time_s},
                  {"sphere_center_m", vector(world.sphere().center_m)},
                  {"sphere_velocity_m_s", vector(world.sphere().velocity_m_s)},
                  {"positions_m", json::array()}};
        for (auto p : world.material().patch().positionsM())
            f["positions_m"].push_back(vector(p));
        result["frames"].push_back(std::move(f));
    };
    frame();
    double elapsed = 0, absolute_residual = 0, signed_residual = 0, work = 0, contact_loss = 0,
           peak_rebound = 0, peak_u = 0;
    double minimum_step = 1, maximum_error = 0, contact_reserve_spent = 0;
    std::uint64_t calls = 0, segments = 0, rejections = 0, queries = 0, iterations = 0,
                  elements = 0, contacts = 0;
    bool accepted = true;
    const auto started = std::chrono::steady_clock::now();
    for (unsigned index = 1; index <= 100; ++index) {
        const double end = index * .001;
        if (calls >= 200000) {
            accepted = false;
            result["error"] = "Recording total step-call budget exhausted";
            break;
        }
        options.maximum_step_calls = static_cast<unsigned>(200000 - calls);
        const auto r = world.advance(end - elapsed, load, options, {}, load.gravity_m_s2);
        calls += r.step_calls;
        queries += r.geometry_queries;
        iterations += r.geometry_iterations;
        elements += r.reserved_element_visits;
        segments += r.accepted_segments;
        rejections += r.rejected_segments;
        if (!r.accepted) {
            accepted = false;
            result["failure"] = {
                {"error", r.error},
                {"last_trial_error", r.last_trial.error},
                {"tentative_duration_s", r.tentative_time_s},
                {"normalized_error", r.last_error.normalized},
                {"position_error_m", r.last_error.position_m},
                {"velocity_error_m_s", r.last_error.velocity_m_s},
                {"strain_error", r.last_error.strain},
                {"absolute_energy_residual_j", r.last_error.absolute_energy_residual_j},
                {"minimum_step_s", r.minimum_accepted_step_s},
                {"minimum_step_error",
                 {{"position_m", r.minimum_step_error.position_m},
                  {"velocity_m_s", r.minimum_step_error.velocity_m_s},
                  {"strain", r.minimum_step_error.strain},
                  {"energy_disagreement_j", r.minimum_step_error.energy_disagreement_j},
                  {"absolute_energy_residual_j", r.minimum_step_error.absolute_energy_residual_j},
                  {"normalized", r.minimum_step_error.normalized}}}};
            break;
        }
        elapsed = end;
        absolute_residual += r.absolute_energy_residual_j;
        signed_residual += r.signed_energy_residual_j;
        contact_reserve_spent += r.contact_energy_reserve_spent_j;
        work += r.external_work_j;
        contact_loss += r.contact_dissipation_j;
        contacts += r.impulse_contacts;
        minimum_step = std::min(minimum_step, r.minimum_accepted_step_s);
        maximum_error = std::max(maximum_error, r.maximum_accepted_error);
        options.initial_trial_dt_s = r.suggested_trial_dt_s;
        peak_rebound = std::max(peak_rebound, world.sphere().velocity_m_s.y);
        for (Vec3 u : world.material().patch().state().displacements_m)
            peak_u = std::max(peak_u, length(u));
        frame();
    }
    const auto final = world.material().report();
    result["summary"] = {{"accepted", accepted},
                         {"completed_duration_s", elapsed},
                         {"absolute_energy_residual_j", absolute_residual},
                         {"signed_energy_residual_j", signed_residual},
                         {"energy_budget_j", energy_budget},
                         {"external_work_j", work},
                         {"contact_dissipation_j", contact_loss},
                         {"contact_energy_reserve_spent_j", contact_reserve_spent},
                         {"plastic_dissipation_j", final.plastic_dissipation_j},
                         {"sampled_peak_upward_speed_m_s", peak_rebound},
                         {"sampled_peak_displacement_m", peak_u},
                         {"minimum_accepted_step_s", minimum_step},
                         {"maximum_accepted_error", maximum_error},
                         {"step_calls", calls},
                         {"tentative_segments", segments},
                         {"rejected_segments", rejections},
                         {"geometry_queries", queries},
                         {"geometry_iterations", iterations},
                         {"reserved_element_visits", elements},
                         {"accepted_contacts", contacts},
                         {"wall_ms", std::chrono::duration<double, std::milli>(
                                         std::chrono::steady_clock::now() - started)
                                         .count()}};
    return result;
}
} // namespace
int main(int argc, char **argv) {
    try {
        if (argc < 2)
            throw std::invalid_argument(
                "Usage: probe output.json [energy_budget_J] [mesh_refinement] [verlet|euler]");
        const double budget = argc > 2 ? std::stod(argv[2]) : 3.e-6;
        const unsigned refinement = argc > 3 ? static_cast<unsigned>(std::stoul(argv[3])) : 1;
        const std::string method = argc > 4 ? argv[4] : "verlet";
        if (method != "verlet" && method != "euler")
            throw std::invalid_argument("Unknown integrator");
        if (!std::isfinite(budget) || budget <= 0 || budget > 1 || refinement < 1 || refinement > 3)
            throw std::invalid_argument("Invalid energy budget or mesh refinement");
        json result = {{"schema", "banjo.sphere_patch_adaptive_probe.v1"},
                       {"scope", "small-strain CPU reference; local error indicators, not spatial "
                                 "or material calibration"},
                       {"cases", json::array()}};
        bool accepted = true;
        for (bool plastic : {false, true}) {
            auto item = run(plastic, budget, refinement, method == "verlet");
            accepted = accepted && item["summary"]["accepted"].get<bool>();
            std::cout << item["material"] << ": " << item["summary"].dump() << '\n';
            if (item.contains("failure"))
                std::cout << item["failure"].dump() << '\n';
            result["cases"].push_back(std::move(item));
        }
        std::ofstream file(argv[1]);
        if (!file)
            throw std::runtime_error("Cannot open output");
        file << result.dump() << '\n';
        return accepted ? 0 : 1;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
