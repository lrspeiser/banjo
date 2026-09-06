#include "physics/SpherePatchWorld.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;

SmallStrainLaw elasticLaw() {
    constexpr double young = 1.e6, poisson = .25;
    const double shear = young / (2 * (1 + poisson));
    return {.kind = SmallStrainLawKind::IsotropicElastic,
            .young_modulus_pa = {young, young, young},
            .poisson_xy_yz_zx = {poisson, poisson, poisson},
            .shear_xy_yz_zx_pa = {shear, shear, shear},
            .maximum_total_strain_norm = .08};
}

SmallStrainLaw j2Law() {
    SmallStrainLaw law;
    law.kind = SmallStrainLawKind::J2Plastic;
    law.j2 = {.young_modulus_pa = 1.e6,
              .poisson_ratio = .25,
              .initial_yield_stress_pa = 1200,
              .isotropic_hardening_modulus_pa = 2.e4,
              .maximum_total_strain_norm = .08};
    law.maximum_total_strain_norm = .08;
    return law;
}

PatchDefinition supportedBrick(const SmallStrainLaw &law, unsigned refinement) {
    auto d = makeTetrahedralBrick({.08, .02, .08}, {2 * refinement, refinement, 2 * refinement},
                                  {law, 1000});
    for (std::size_t i = 0; i < d.reference_positions_m.size(); ++i)
        if (d.reference_positions_m[i].y == 0)
            d.fixed_components[i] = {true, true, true};
    return d;
}

DynamicPatchLoad zeroLoad(std::size_t n) {
    DynamicPatchLoad load;
    load.nodal_forces_n.resize(n);
    return load;
}

void vectorJson(std::ostream &out, Vec3 v) {
    out << '[' << v.x << ',' << v.y << ',' << v.z << ']';
}

std::string escaped(const std::string &value) {
    std::string out;
    for (char c : value) {
        if (c == '"' || c == '\\')
            out += '\\';
        if (c == '\n')
            out += "\\n";
        else if (c != '\r')
            out += c;
    }
    return out;
}

struct Metrics {
    bool accepted{true}, contacted{};
    std::string error;
    double dt{}, completed_duration{}, elapsed_ms{}, peak_stored{}, plastic_dissipation{};
    double peak_rebound_velocity{};
    double maximum_displacement{}, final_displacement{}, maximum_equivalent_plastic_strain{};
    double contact_dissipation{}, accumulated_external_work{}, cumulative_energy_residual{};
    double initial_mechanical_energy{}, final_mechanical_energy{}, maximum_angular_residual{};
    double maximum_energy_residual{}, maximum_momentum_residual{};
    Vec3 accumulated_coupling_impulse{}, accumulated_angular_residual{};
    unsigned completed_steps{}, contacts{};
    std::uint64_t geometry_queries{}, geometry_iterations{};
};

Metrics runCase(std::ostream &out, const char *name, const SmallStrainLaw &law,
                double time_step_fraction, unsigned refinement) {
    constexpr double radius = .012, iron_density = 7870;
    const double sphere_mass =
        (4.0 / 3.0) * std::acos(-1.0) * radius * radius * radius * iron_density;
    auto definition = supportedBrick(law, refinement);
    constexpr double clearance = .0005;
    constexpr Vec3 gravity{0, -9.81, 0};
    PatchSphere sphere{{.007, .02 + radius + clearance, .009}, {}, {}, radius, sphere_mass};
    SpherePatchWorld world(
        definition, sphere, {},
        {.friction_coefficient = .15, .contact_margin_m = 1.e-6, .maximum_penetration_m = 1.e-5});
    Metrics m;
    m.dt = world.material().stableTimeStepLimitS() * time_step_fraction;
    m.initial_mechanical_energy = .5 * sphere.mass_kg * lengthSquared(sphere.velocity_m_s);
    const auto started = std::chrono::steady_clock::now();

    out << "{\"name\":\"" << name << "\",\"scenario\":\"submillimeter_gravity_drop\""
        << ",\"material_scope\":\"fictional numerical constitutive comparison\""
        << ",\"material\":{\"density_kg_m3\":1000,\"young_modulus_pa\":1000000,"
        << "\"poisson_ratio\":0.25,\"kind\":\""
        << (law.kind == SmallStrainLawKind::J2Plastic ? "J2Plastic" : "IsotropicElastic") << "\"";
    if (law.kind == SmallStrainLawKind::J2Plastic)
        out << ",\"initial_yield_stress_pa\":" << law.j2.initial_yield_stress_pa
            << ",\"isotropic_hardening_modulus_pa\":" << law.j2.isotropic_hardening_modulus_pa;
    out << "}"
        << ",\"initial_clearance_m\":" << clearance << ",\"gravity_m_s2\":";
    vectorJson(out, gravity);
    out << ",\"sphere_mass_kg\":" << sphere_mass << ",\"sphere_radius_m\":" << radius
        << ",\"dt_s\":" << m.dt << ",\"mesh\":{";
    out << "\"reference_positions_m\":[";
    for (std::size_t i = 0; i < definition.reference_positions_m.size(); ++i) {
        if (i)
            out << ',';
        vectorJson(out, definition.reference_positions_m[i]);
    }
    out << "],\"tetrahedra\":[";
    for (std::size_t i = 0; i < definition.elements.size(); ++i) {
        if (i)
            out << ',';
        const auto &n = definition.elements[i].nodes;
        out << '[' << n[0] << ',' << n[1] << ',' << n[2] << ',' << n[3] << ']';
    }
    out << "]},\"frames\":[";

    bool first_frame = true, rebound_frame_written = false;
    unsigned last_frame_step = 0;
    constexpr double requested_duration_s = .1;
    const unsigned steps = static_cast<unsigned>(std::ceil(requested_duration_s / m.dt));
    const unsigned sample_stride = std::max(1u, steps / 180u);
    for (unsigned step = 0; step < steps; ++step) {
        if (m.completed_duration >= requested_duration_s)
            break;
        auto load = zeroLoad(definition.reference_positions_m.size());
        load.gravity_m_s2 = gravity;
        const double step_dt = std::min(m.dt, requested_duration_s - m.completed_duration);
        const auto report = world.step(step_dt, load, {}, gravity);
        if (!report.accepted) {
            m.accepted = false;
            m.error = report.error;
            break;
        }
        ++m.completed_steps;
        m.completed_duration += step_dt;
        m.geometry_queries += report.geometry_queries;
        m.geometry_iterations += report.geometry_iterations;
        m.contacts += report.impulse_contacts;
        m.contacted = m.contacted || report.impulse_contacts > 0;
        m.peak_stored = std::max(m.peak_stored, report.material.stored_free_energy_j);
        m.plastic_dissipation = report.material.plastic_dissipation_j;
        for (const auto &state : world.material().patch().state().material_points)
            m.maximum_equivalent_plastic_strain =
                std::max(m.maximum_equivalent_plastic_strain, state.equivalent_plastic_strain);
        m.contact_dissipation += report.contact_dissipation_j;
        m.accumulated_external_work += report.external_work_j;
        m.cumulative_energy_residual += report.numerical_energy_balance_residual_j;
        m.accumulated_angular_residual += report.contact_angular_momentum_residual_kg_m2_s;
        m.maximum_angular_residual = std::max(
            m.maximum_angular_residual, length(report.contact_angular_momentum_residual_kg_m2_s));
        m.accumulated_coupling_impulse += report.material.coupling_impulse_n_s;
        m.maximum_energy_residual = std::max(m.maximum_energy_residual,
                                             std::abs(report.numerical_energy_balance_residual_j));
        m.maximum_momentum_residual = std::max(
            m.maximum_momentum_residual, length(report.linear_momentum_balance_residual_kg_m_s));
        double maximum_u = 0;
        for (Vec3 u : world.material().patch().state().displacements_m)
            maximum_u = std::max(maximum_u, length(u));
        m.maximum_displacement = std::max(m.maximum_displacement, maximum_u);
        if (m.contacted)
            m.peak_rebound_velocity =
                std::max(m.peak_rebound_velocity, world.sphere().velocity_m_s.y);
        const bool first_rebound =
            !rebound_frame_written && m.contacted && world.sphere().velocity_m_s.y > .03;
        if (step % sample_stride == 0 || step + 1 == steps || first_rebound) {
            if (!first_frame)
                out << ',';
            first_frame = false;
            out << "{\"step\":" << step + 1 << ",\"time_s\":" << world.material().state().time_s
                << ",\"sphere_center_m\":";
            vectorJson(out, world.sphere().center_m);
            out << ",\"sphere_velocity_m_s\":";
            vectorJson(out, world.sphere().velocity_m_s);
            out << ",\"positions_m\":[";
            const auto positions = world.material().patch().positionsM();
            for (std::size_t i = 0; i < positions.size(); ++i) {
                if (i)
                    out << ',';
                vectorJson(out, positions[i]);
            }
            out << "],\"stored_energy_j\":" << report.material.stored_free_energy_j
                << ",\"plastic_dissipation_j\":" << report.material.plastic_dissipation_j
                << ",\"contact_dissipation_j\":" << report.contact_dissipation_j
                << ",\"coupling_impulse_n_s\":";
            vectorJson(out, report.material.coupling_impulse_n_s);
            out << ",\"momentum_residual_kg_m_s\":";
            vectorJson(out, report.linear_momentum_balance_residual_kg_m_s);
            out << '}';
            last_frame_step = step + 1;
            rebound_frame_written = rebound_frame_written || first_rebound;
        }
    }
    // Always preserve the exact last accepted state, including on failure.
    if (m.completed_steps > 0 && last_frame_step != m.completed_steps) {
        if (!first_frame)
            out << ',';
        out << "{\"step\":" << m.completed_steps
            << ",\"time_s\":" << world.material().state().time_s << ",\"sphere_center_m\":";
        vectorJson(out, world.sphere().center_m);
        out << ",\"sphere_velocity_m_s\":";
        vectorJson(out, world.sphere().velocity_m_s);
        out << ",\"positions_m\":[";
        const auto positions = world.material().patch().positionsM();
        for (std::size_t i = 0; i < positions.size(); ++i) {
            if (i)
                out << ',';
            vectorJson(out, positions[i]);
        }
        out << "]} ";
    }
    const auto final_material = world.material().report();
    const double sphere_inertia = .4 * sphere_mass * radius * radius;
    m.final_mechanical_energy = final_material.kinetic_energy_j +
                                final_material.stored_free_energy_j +
                                .5 * sphere_mass * lengthSquared(world.sphere().velocity_m_s) +
                                .5 * sphere_inertia * lengthSquared(world.sphere().spin_rad_s);
    for (Vec3 u : world.material().patch().state().displacements_m)
        m.final_displacement = std::max(m.final_displacement, length(u));
    m.elapsed_ms =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started)
            .count();
    out << "],\"summary\":{\"accepted\":" << (m.accepted ? "true" : "false") << ",\"error\":\""
        << escaped(m.error) << "\",\"requested_duration_s\":" << requested_duration_s
        << ",\"completed_duration_s\":" << m.completed_duration
        << ",\"completed_steps\":" << m.completed_steps << ",\"contacts\":" << m.contacts
        << ",\"geometry_queries\":" << m.geometry_queries
        << ",\"geometry_iterations\":" << m.geometry_iterations
        << ",\"peak_rebound_velocity_m_s\":" << m.peak_rebound_velocity
        << ",\"peak_stored_energy_j\":" << m.peak_stored
        << ",\"plastic_dissipation_j\":" << m.plastic_dissipation
        << ",\"maximum_displacement_m\":" << m.maximum_displacement
        << ",\"final_displacement_m\":" << m.final_displacement
        << ",\"maximum_equivalent_plastic_strain\":" << m.maximum_equivalent_plastic_strain
        << ",\"contact_dissipation_j\":" << m.contact_dissipation
        << ",\"initial_mechanical_energy_j\":" << m.initial_mechanical_energy
        << ",\"final_mechanical_energy_j\":" << m.final_mechanical_energy
        << ",\"accumulated_external_work_j\":" << m.accumulated_external_work
        << ",\"cumulative_energy_residual_j\":" << m.cumulative_energy_residual
        << ",\"normalized_cumulative_energy_residual\":"
        << std::abs(m.cumulative_energy_residual) /
               std::max(1e-30, std::abs(m.accumulated_external_work) + m.contact_dissipation +
                                   m.final_mechanical_energy)
        << ",\"accumulated_coupling_impulse_n_s\":";
    vectorJson(out, m.accumulated_coupling_impulse);
    out << ",\"maximum_energy_residual_j\":" << m.maximum_energy_residual
        << ",\"maximum_momentum_residual_kg_m_s\":" << m.maximum_momentum_residual
        << ",\"accumulated_contact_angular_residual_kg_m2_s\":";
    vectorJson(out, m.accumulated_angular_residual);
    out << ",\"maximum_contact_angular_residual_kg_m2_s\":" << m.maximum_angular_residual
        << ",\"elapsed_wall_ms\":" << m.elapsed_ms << "}}";
    return m;
}
} // namespace

int main(int argc, char **argv) {
    try {
        const double time_step_fraction = argc > 2 ? std::stod(argv[2]) : .05;
        if (!std::isfinite(time_step_fraction) || time_step_fraction < .005 ||
            time_step_fraction > 1)
            throw std::invalid_argument("Time-step fraction must be in [0.005,1]");
        const unsigned refinement = argc > 3 ? static_cast<unsigned>(std::stoul(argv[3])) : 1;
        if (refinement < 1 || refinement > 3)
            throw std::invalid_argument("Mesh refinement must be 1..3");
        std::ofstream file;
        std::ostream *output = &std::cout;
        if (argc > 1) {
            file.open(argv[1]);
            if (!file)
                throw std::runtime_error("Cannot open probe output path");
            output = &file;
        }
        *output << std::setprecision(17) << "{\"schema\":\"banjo.sphere_patch_probe.v1\","
                << "\"time_step_fraction\":" << time_step_fraction
                << ",\"mesh_refinement\":" << refinement << ",\"cases\":[";
        const Metrics elastic =
            runCase(*output, "linear_elastic_E1MPa", elasticLaw(), time_step_fraction, refinement);
        *output << ',';
        const Metrics plastic =
            runCase(*output, "J2_E1MPa_yield1.2kPa", j2Law(), time_step_fraction, refinement);
        *output << "]}" << '\n';
        std::cerr << std::setprecision(6) << "elastic: accepted=" << elastic.accepted
                  << " peak_rebound_m_s=" << elastic.peak_rebound_velocity
                  << " peak_u_m=" << elastic.maximum_displacement
                  << "\nJ2: accepted=" << plastic.accepted
                  << " peak_rebound_m_s=" << plastic.peak_rebound_velocity
                  << " plastic_j=" << plastic.plastic_dissipation
                  << " final_u_m=" << plastic.final_displacement
                  << " max_eq_plastic_strain=" << plastic.maximum_equivalent_plastic_strain << '\n';
        if (!elastic.accepted || !plastic.accepted || !elastic.contacted || !plastic.contacted)
            return EXIT_FAILURE;
        return EXIT_SUCCESS;
    } catch (const std::exception &error) {
        std::cerr << "sphere patch probe failed: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
