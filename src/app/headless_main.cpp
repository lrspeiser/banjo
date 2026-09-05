#include "sim/RollingBallExperiment.hpp"

#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <fstream>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {
void writeAuditRow(std::ostream &out, const banjo::RollingBallExperiment &experiment) {
    const auto totals = experiment.mechanicalTotals();
    const auto &stats = experiment.stats();
    const auto com = totals.centerOfMass();
    const auto vector = [&](banjo::Vec3 v) { out << ',' << v.x << ',' << v.y << ',' << v.z; };
    out << std::setprecision(17) << stats.fixed_ticks << ',' << stats.simulated_time_s << ','
        << static_cast<unsigned>(stats.phase) << ',' << totals.mass_kg;
    vector(com);
    vector(totals.linear_momentum_kg_m_s);
    vector(totals.angular_momentum_kg_m2_s);
    out << ',' << totals.kinetic_energy_j << ',' << totals.elastic_energy_j << ','
        << totals.gravitational_potential_energy_j << ',' << stats.coupled_contact_dissipation_j << ','
        << stats.internal_damping_loss_j << ',' << stats.coarsening_kinetic_loss_j << ','
        << stats.coarsening_elastic_loss_j << ',' << stats.unassigned_bond_removal_energy_j << ','
        << stats.constraint_mechanical_energy_delta_j;
    vector(stats.contact_correction_angular_momentum_delta_kg_m2_s);
    vector(stats.constraint_angular_momentum_delta_kg_m2_s);
    out << '\n';
    if (!out) throw std::runtime_error("failed to write mechanical audit CSV");
}
void printTransfer(const char *name, const banjo::RepresentationTransferAudit &audit) {
    if (!audit.measured) throw std::runtime_error("missing representation transfer audit");
    std::cout << std::scientific << std::setprecision(6) << name
              << ": delta-m=" << audit.after.mass_kg - audit.before.mass_kg << " kg"
              << ", delta-COM=" << banjo::length(audit.after.centerOfMass() - audit.before.centerOfMass()) << " m"
              << ", delta-P=" << banjo::length(audit.after.linear_momentum_kg_m_s - audit.before.linear_momentum_kg_m_s) << " N*s"
              << ", delta-L=" << banjo::length(audit.after.angular_momentum_kg_m2_s - audit.before.angular_momentum_kg_m2_s) << " kg*m^2/s"
              << ", delta-E=" << audit.after.mechanicalEnergy() - audit.before.mechanicalEnergy() << " J\n";
}
double numericOption(const std::string &value) {
    std::size_t used = 0;
    const double result = std::stod(value, &used);
    if (used != value.size() || !std::isfinite(result)) throw std::invalid_argument("invalid numeric option");
    return result;
}
}

int main(int argc, char **argv) {
    try {
        banjo::ExperimentSettings settings;
        std::filesystem::path audit_path;
        for (int i = 1; i < argc; ++i) {
            const std::string_view option = argv[i];
            if (option == "--isolated") {
                settings.support_enabled = false;
                settings.gravity_m_s2 = {};
            } else if (option == "--audit-csv" || option == "--target-speed" || option == "--voxel-size") {
                if (++i >= argc) throw std::invalid_argument("missing option value");
                if (option == "--audit-csv") audit_path = argv[i];
                else if (option == "--target-speed") settings.target_initial_speed_m_s = numericOption(argv[i]);
                else settings.voxel_size_m = numericOption(argv[i]);
            } else throw std::invalid_argument("unknown headless option: " + std::string(option));
        }
        banjo::RollingBallExperiment experiment(settings);
        const auto &lattice = experiment.glassLattice();
        std::ofstream audit;
        if (!audit_path.empty()) {
            if (audit_path.has_parent_path()) std::filesystem::create_directories(audit_path.parent_path());
            audit.open(audit_path);
            if (!audit) throw std::runtime_error("could not open mechanical audit CSV");
            audit << "tick,time_s,phase,mass_kg,com_x_m,com_y_m,com_z_m,"
                     "px_kg_m_s,py_kg_m_s,pz_kg_m_s,lx_kg_m2_s,ly_kg_m2_s,lz_kg_m2_s,"
                     "kinetic_j,elastic_j,gravity_potential_j,material_contact_loss_j,internal_damping_loss_j,"
                     "coarsening_kinetic_loss_j,coarsening_elastic_loss_j,unassigned_bond_removal_j,"
                     "constraint_mechanical_delta_j,correction_lx,correction_ly,correction_lz,"
                     "constraint_lx,constraint_ly,constraint_lz\n";
            writeAuditRow(audit, experiment);
        }

        std::cout << std::fixed << std::setprecision(4);
        std::cout << "Banjo rolling-ball material laboratory (headless)\n";
        std::cout << "  glass nodes: " << lattice.nodes.size() << '\n';
        std::cout << "  intact bonds: " << lattice.bonds.size() << '\n';
        std::cout << "  represented mass: " << lattice.total_mass_kg << " kg\n";

        constexpr unsigned kMaximumTicks = 2000U;
        unsigned ticks = 0U;
        while (experiment.phase() != banjo::ExperimentPhase::RigidFragments &&
               ticks < kMaximumTicks) {
            experiment.stepFixed();
            ++ticks;
            if (audit.is_open()) writeAuditRow(audit, experiment);
        }
        if (experiment.phase() != banjo::ExperimentPhase::RigidFragments) {
            throw std::runtime_error("experiment did not reach rigid fragment handoff");
        }

        // Prove that the generated Jolt fragments continue to simulate after handoff.
        for (unsigned tick = 0; tick < 120U; ++tick) {
            experiment.stepFixed();
            if (audit.is_open()) writeAuditRow(audit, experiment);
        }

        const banjo::ExperimentStats &stats = experiment.stats();
        std::cout << "Impact: speed=" << stats.impact_speed_m_s
                  << " m/s, energy=" << stats.impact_energy_j
                  << " J, threshold=" << stats.activation_threshold_j
                  << " J, normalized=" << stats.normalized_impact_energy << '\n';
        std::cout << "Contact-driven: impulses=" << stats.coupled_contact_points
                  << ", transfer=" << stats.coupled_impulse_n_s
                  << " N*s, contact dissipation=" << stats.coupled_contact_dissipation_j << " J\n";
        if (!stats.activation_response_deferred || stats.coupled_contact_points == 0U) {
            throw std::runtime_error("contact-driven activation/coupling was not exercised");
        }
        std::cout << "Fracture: broken bonds=" << stats.broken_bonds
                  << ", components=" << stats.connected_components << '\n';
        std::cout << "Handoff: rigid fragments=" << stats.rigid_fragments
                  << ", debris particles=" << stats.debris_particles << '\n';
        std::cout << "Mass: source=" << stats.represented_glass_mass_kg
                  << " kg, fragments=" << stats.fragment_mass_kg
                  << " kg, error=" << stats.mass_error_kg << " kg\n";

        if (stats.rigid_fragments == 0U) {
            throw std::runtime_error("fracture produced no Jolt rigid fragments");
        }
        if (std::abs(stats.mass_error_kg) > 1.0e-8) {
            throw std::runtime_error("fragment handoff failed mass conservation check");
        }
        for (const auto &fragment : experiment.fragmentBuild().rigid_fragments) {
            if (!experiment.rigidSnapshot(fragment.body_id)) {
                throw std::runtime_error("a generated rigid fragment is missing from Jolt");
            }
        }

        printTransfer("Activation audit", stats.activation_transfer);
        printTransfer("Handoff audit", stats.fragment_transfer);
        std::cout << "Coarsening: kinetic loss=" << stats.coarsening_kinetic_loss_j
                  << " J, elastic loss=" << stats.coarsening_elastic_loss_j << " J\n"
                  << "Unassigned bond-removal energy=" << stats.unassigned_bond_removal_energy_j << " J\n"
                  << "Numerical angular changes: contact correction="
                  << banjo::length(stats.contact_correction_angular_momentum_delta_kg_m2_s)
                  << ", constraint solve=" << banjo::length(stats.constraint_angular_momentum_delta_kg_m2_s)
                  << " kg*m^2/s\n";
        if (audit.is_open()) { audit.flush(); if (!audit) throw std::runtime_error("failed to flush audit CSV"); }
        std::cout << "PASS: emergent components were meshed and returned to Jolt.\n"
                     "Full-step conservation remains unvalidated; these are measured state and transfer diagnostics.\n";
        return EXIT_SUCCESS;
    } catch (const std::exception &error) {
        std::cerr << "Fatal error: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
