#include "physics/CohesiveSphereWorld.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;

SmallStrainLaw bulkLaw() {
    return {.kind = SmallStrainLawKind::IsotropicElastic,
            .young_modulus_pa = {1.e6, 0, 0},
            .poisson_xy_yz_zx = {.25, 0, 0},
            .maximum_total_strain_norm = .12};
}

CohesiveFacetLaw facetLaw() {
    return {.stiffness_pa_per_m = 1.e9,
            .strength_pa = 1.e4,
            .fracture_energy_j_m2 = .1,
            .compression_stiffness_pa_per_m = 1.e9,
            .tangential_stiffness_pa_per_m = 2.e8};
}

void vectorJson(std::ostream &out, Vec3 value) {
    out << '[' << value.x << ',' << value.y << ',' << value.z << ']';
}

std::string escape(const std::string &value) {
    std::string out;
    for (const char c : value) {
        if (c == '"' || c == '\\') out += '\\';
        if (c == '\n') out += "\\n";
        else if (c != '\r') out += c;
    }
    return out;
}

void writeCase(std::ostream &out, const char *name, double speed, bool corotated, bool closure,
               double step_fraction) {
    const auto definition = makeTetrahedralBrick(
        {.08, .02, .08}, {1, 1, 1}, {bulkLaw(), 1000.});
    const auto topology = compileFractureTopology(definition);
    const auto cohesive = facetLaw();
    std::vector<CohesiveFacetLaw> laws(topology.internal_facets.size(), cohesive);
    constexpr double radius = .012, sphere_density = 7870.;
    const double sphere_mass = 4. / 3. * std::acos(-1.) * radius * radius * radius * sphere_density;
    PatchSphere sphere{{.007, .02 + radius + 2.e-5, .009}, {0, -speed, 0}, {},
                       radius, sphere_mass};
    CohesiveDynamicPatchOptions dynamics;
    if (corotated) dynamics.kinematics = CohesiveKinematics::Corotated;
    dynamics.finite_facet_closure_contact = closure;
    dynamics.maximum_displacement_gradient_norm = .12;
    dynamics.maximum_absolute_energy_residual_j = 2.e-4;
    dynamics.maximum_time_step_s = 2.e-4;
    PatchContactOptions contact;
    contact.friction_coefficient = .1;
    contact.contact_margin_m = 1.e-6;
    contact.maximum_penetration_m = 1.e-5;
    contact.maximum_contact_events = 128;
    contact.maximum_geometry_queries = 20000;
    contact.maximum_geometry_iterations = 100000;
    CohesiveSphereWorld world(definition, sphere, laws, dynamics, contact);
    constexpr double duration = .008;
    const double base_dt = step_fraction * world.material().stableTimeStepLimitS();
    const unsigned expected_steps = static_cast<unsigned>(std::ceil(duration / base_dt));
    const unsigned stride = std::max(1U, expected_steps / 100U);
    const auto started = std::chrono::steady_clock::now();
    bool accepted = true, first_frame = true, fracture_frame_written = false;
    std::string error;
    std::optional<CohesiveContactHandoff> contact_handoff;
    double elapsed = 0., cumulative_energy_residual = 0.;
    double cumulative_absolute_energy_residual = 0., maximum_damage = 0.;
    unsigned steps = 0, contacts = 0, last_step_contacts = 0;
    unsigned maximum_components = 1, maximum_separated = 0;
    unsigned maximum_compressed_separated = 0;
    double maximum_closure_compression = 0;
    std::uint64_t closure_queries = 0;
    std::uint64_t geometry_queries = 0, geometry_iterations = 0;

    out << "{\"name\":\"" << name << "\",\"scope\":\"fictional explicit SI cohesive impact\""
        << ",\"finite_facet_closure_contact\":" << (closure ? "true" : "false")
        << ",\"maximum_closure_compression_fraction\":" << dynamics.maximum_closure_compression_fraction
        << ",\"bulk\":{\"law\":\"" << (corotated ? "corotated_isotropic" : "isotropic_elastic")
        << "\",\"young_modulus_pa\":1000000,"
        << "\"poisson_ratio\":0.25,\"density_kg_m3\":1000}"
        << ",\"interface\":{\"stiffness_pa_per_m\":1000000000,"
        << "\"tangential_stiffness_pa_per_m\":200000000,\"strength_pa\":10000,"
        << "\"fracture_energy_j_m2\":0.1}"
        << ",\"sphere\":{\"radius_m\":" << radius << ",\"density_kg_m3\":"
        << sphere_density << ",\"mass_kg\":" << sphere_mass
        << ",\"initial_speed_m_s\":" << speed << "},\"requested_duration_s\":"
        << duration << ",\"stable_time_step_s\":" << world.material().stableTimeStepLimitS()
        << ",\"time_step_s\":" << base_dt
        << ",\"limitations\":[\"" << (corotated ? "Corotated bulk and objective facets; reference timestep cap is not a nonlinear stability certificate" : "Small-displacement bulk; no finite-rotation fragment evolution") << "\","
        << "\"no fragment self-contact\",\"no calibrated cutting or material fracture claim\"]"
        << ",\"mesh\":{\"reference_positions_m\":[";
    const auto &local_reference = world.material().topology().duplicated_definition.reference_positions_m;
    for (std::size_t i = 0; i < local_reference.size(); ++i) {
        if (i) out << ',';
        vectorJson(out, local_reference[i]);
    }
    out << "],\"tetrahedra\":[";
    const auto &elements = world.material().topology().duplicated_definition.elements;
    for (std::size_t i = 0; i < elements.size(); ++i) {
        if (i) out << ',';
        const auto &n = elements[i].nodes;
        out << '[' << n[0] << ',' << n[1] << ',' << n[2] << ',' << n[3] << ']';
    }
    out << "],\"boundary_triangles\":[";
    const auto &boundary = world.material().topology().original_exterior_faces;
    for (std::size_t i = 0; i < boundary.size(); ++i) {
        if (i) out << ',';
        out << '[' << boundary[i].local_nodes[0] << ',' << boundary[i].local_nodes[1]
            << ',' << boundary[i].local_nodes[2] << ']';
    }
    out << "]},\"frames\":[";

    out << "{\"time_s\":0,\"sphere_center_m\":";
    vectorJson(out, world.sphere().center_m);
    out << ",\"sphere_velocity_m_s\":";
    vectorJson(out, world.sphere().velocity_m_s);
    out << ",\"positions_m\":[";
    const auto initial_positions = world.material().positionsM();
    for (std::size_t i = 0; i < initial_positions.size(); ++i) {
        if (i) out << ',';
        vectorJson(out, initial_positions[i]);
    }
    out << "],\"contacts\":0,\"maximum_damage\":0,\"fully_separated_facets\":0,\"components\":1,"
        << "\"component_by_tetrahedron\":[";
    for (std::size_t i = 0; i < world.material().state().separation.component_by_tetrahedron.size(); ++i) {
        if (i) out << ',';
        out << world.material().state().separation.component_by_tetrahedron[i];
    }
    out << "],\"newly_exposed_faces\":[],\"fracture_dissipation_j\":0,"
        << "\"energy_residual_j\":0}";
    first_frame = false;
    double last_written_time = 0.;

    while (elapsed < duration && steps < 30000) {
        const double dt = std::min(base_dt, duration - elapsed);
        const auto report = world.step(dt,
            std::vector<Vec3>(world.material().state().velocities_m_s.size()));
        if (!report.accepted) {
            accepted = false;
            error = report.error;
            contact_handoff = report.material.contact_handoff_required;
            break;
        }
        elapsed += dt;
        ++steps;
        contacts += report.contact.impulse_contacts;
        maximum_compressed_separated = std::max(maximum_compressed_separated,
                                                report.material.compressed_separated_facets);
        maximum_closure_compression = std::max(maximum_closure_compression,
                                               report.material.maximum_closure_compression_m);
        closure_queries += report.material.closure_projection_queries;
        last_step_contacts = report.contact.impulse_contacts;
        geometry_queries += report.contact.geometry_queries;
        geometry_iterations += report.contact.geometry_iterations;
        cumulative_energy_residual += report.contact.numerical_energy_balance_residual_j;
        cumulative_absolute_energy_residual +=
            std::abs(report.contact.numerical_energy_balance_residual_j);
        maximum_components = std::max(maximum_components,
            static_cast<unsigned>(world.material().state().separation.components.size()));
        maximum_separated = std::max(maximum_separated,
                                     report.material.fully_separated_facets);
        for (const auto &facet : world.material().state().corotated_facet_states)
            for (const auto &point : facet.integration_points)
                maximum_damage = std::max(maximum_damage,
                    evaluateCohesiveInterface({cohesive.stiffness_pa_per_m, cohesive.strength_pa,
                        cohesive.fracture_energy_j_m2, 1., 0.}, point).damage);
        for (const auto &facet : world.material().state().facet_states)
            for (const auto &point : facet.integration_points)
                maximum_damage = std::max(maximum_damage,
                    evaluateCohesiveInterface({cohesive.stiffness_pa_per_m,
                                               cohesive.strength_pa,
                                               cohesive.fracture_energy_j_m2, 1.,
                                               cohesive.compression_stiffness_pa_per_m}, point).damage);
        const bool first_fracture = !fracture_frame_written &&
                                    report.material.fracture_dissipation_increment_j > 0.;
        if ((steps - 1) % stride == 0 || elapsed == duration || first_fracture) {
            if (!first_frame) out << ',';
            first_frame = false;
            out << "{\"time_s\":" << elapsed << ",\"sphere_center_m\":";
            vectorJson(out, world.sphere().center_m);
            out << ",\"sphere_velocity_m_s\":";
            vectorJson(out, world.sphere().velocity_m_s);
            out << ",\"positions_m\":[";
            const auto positions = world.material().positionsM();
            for (std::size_t i = 0; i < positions.size(); ++i) {
                if (i) out << ',';
                vectorJson(out, positions[i]);
            }
            out << "],\"contacts\":" << report.contact.impulse_contacts
                << ",\"maximum_damage\":" << maximum_damage
                << ",\"fully_separated_facets\":" << report.material.fully_separated_facets
                << ",\"components\":" << world.material().state().separation.components.size()
                << ",\"component_by_tetrahedron\":[";
            const auto &component_ids =
                world.material().state().separation.component_by_tetrahedron;
            for (std::size_t i = 0; i < component_ids.size(); ++i) {
                if (i) out << ',';
                out << component_ids[i];
            }
            out << "],\"newly_exposed_faces\":[";
            const auto &exposed = world.material().state().separation.newly_exposed_faces;
            for (std::size_t i = 0; i < exposed.size(); ++i) {
                if (i) out << ',';
                out << '[' << exposed[i].local_nodes[0] << ',' << exposed[i].local_nodes[1]
                    << ',' << exposed[i].local_nodes[2] << ']';
            }
            out << ']'
                << ",\"fracture_dissipation_j\":" << report.material.fracture_dissipation_j
                << ",\"energy_residual_j\":"
                << report.contact.numerical_energy_balance_residual_j << '}';
            fracture_frame_written = fracture_frame_written || first_fracture;
            last_written_time = elapsed;
        }
    }
    if (accepted && elapsed < duration) {
        accepted = false;
        error = "probe step limit reached before requested duration";
    }
    // Preserve the exact final accepted state when it was not already sampled.
    if (elapsed > last_written_time) {
        out << ",{\"time_s\":" << elapsed << ",\"sphere_center_m\":";
        vectorJson(out, world.sphere().center_m);
        out << ",\"sphere_velocity_m_s\":";
        vectorJson(out, world.sphere().velocity_m_s);
        out << ",\"positions_m\":[";
        const auto final_positions = world.material().positionsM();
        for (std::size_t i = 0; i < final_positions.size(); ++i) {
            if (i) out << ',';
            vectorJson(out, final_positions[i]);
        }
        out << "],\"contacts\":" << last_step_contacts
            << ",\"maximum_damage\":" << maximum_damage
            << ",\"fully_separated_facets\":"
            << world.material().report().fully_separated_facets
            << ",\"components\":" << world.material().state().separation.components.size()
            << ",\"component_by_tetrahedron\":[";
        const auto &final_components =
            world.material().state().separation.component_by_tetrahedron;
        for (std::size_t i = 0; i < final_components.size(); ++i) {
            if (i) out << ',';
            out << final_components[i];
        }
        out << "],\"newly_exposed_faces\":[";
        const auto &final_exposed = world.material().state().separation.newly_exposed_faces;
        for (std::size_t i = 0; i < final_exposed.size(); ++i) {
            if (i) out << ',';
            out << '[' << final_exposed[i].local_nodes[0] << ','
                << final_exposed[i].local_nodes[1] << ','
                << final_exposed[i].local_nodes[2] << ']';
        }
        out << "],\"fracture_dissipation_j\":"
            << world.material().report().fracture_dissipation_j << "}";
    }
    const double wall_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - started).count();
    out << "],\"summary\":{\"status\":\"" << (accepted ? "complete" : "solver_limit")
        << "\",\"error\":\"" << escape(error) << "\",\"completed_duration_s\":" << elapsed
        << ",\"steps\":" << steps << ",\"accepted_contacts\":" << contacts
        << ",\"maximum_damage\":" << maximum_damage
        << ",\"maximum_fully_separated_facets\":" << maximum_separated
        << ",\"maximum_components\":" << maximum_components
        << ",\"maximum_compressed_separated_facets\":" << maximum_compressed_separated
        << ",\"maximum_closure_compression_m\":" << maximum_closure_compression
        << ",\"closure_projection_queries\":" << closure_queries
        << ",\"interface_contact_stored_energy_final_j\":"
        << world.material().report().interface_contact_stored_energy_j
        << ",\"newly_exposed_faces_final\":"
        << world.material().state().separation.newly_exposed_faces.size()
        << ",\"geometry_queries\":" << geometry_queries
        << ",\"geometry_iterations\":" << geometry_iterations
        << ",\"cumulative_energy_residual_j\":" << cumulative_energy_residual
        << ",\"cumulative_absolute_energy_residual_j\":"
        << cumulative_absolute_energy_residual
        << ",\"wall_ms\":" << wall_ms;
    if (contact_handoff)
        out << ",\"rejected_contact_handoff\":{\"facet_index\":"
            << contact_handoff->facet_index << ",\"retained_compression_energy_j\":"
            << contact_handoff->retained_compression_energy_j << '}';
    out << "}}";
}

} // namespace

int main(int argc, char **argv) {
    try {
        if (argc > 4) throw std::invalid_argument("Usage: probe [output [--corotated [step_fraction]]]");
        const std::string path = argc > 1 ? argv[1] : "cohesive-sphere-probe.json";
        const bool closure = argc > 2 && std::string(argv[2]) == "--corotated-contact";
        const bool corotated = closure || (argc > 2 && std::string(argv[2]) == "--corotated");
        if (argc > 2 && !corotated) throw std::invalid_argument("Expected --corotated or --corotated-contact");
        std::size_t consumed = 0;
        const double step_fraction = argc > 3 ? std::stod(argv[3], &consumed) : .2;
        if (argc > 3 && consumed != std::string(argv[3]).size())
            throw std::invalid_argument("Invalid step fraction");
        if (!std::isfinite(step_fraction) || step_fraction <= 0 || step_fraction > .2)
            throw std::invalid_argument("Step fraction must be in (0, 0.2]");
        std::ofstream output(path);
        if (!output) throw std::runtime_error("cannot open probe output");
        output << std::setprecision(17)
               << "{\"schema\":\"banjo.cohesive-sphere-probe." << (closure ? "v3" : corotated ? "v2" : "v1") << "\",\"cases\":[";
        writeCase(output, "low_impact_control", .03, corotated, closure, step_fraction);
        output << ',';
        writeCase(output, "higher_impact", 1.0, corotated, closure, step_fraction);
        output << "]}";
        std::cout << path << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
