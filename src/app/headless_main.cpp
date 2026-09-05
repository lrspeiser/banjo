#include "sim/RollingBallExperiment.hpp"

#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <stdexcept>

int main() {
    try {
        banjo::RollingBallExperiment experiment;
        const auto &lattice = experiment.glassLattice();

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
        }
        if (experiment.phase() != banjo::ExperimentPhase::RigidFragments) {
            throw std::runtime_error("experiment did not reach rigid fragment handoff");
        }

        // Prove that the generated Jolt fragments continue to simulate after handoff.
        for (unsigned tick = 0; tick < 120U; ++tick) {
            experiment.stepFixed();
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

        std::cout << "PASS: emergent components were meshed and returned to Jolt.\n";
        return EXIT_SUCCESS;
    } catch (const std::exception &error) {
        std::cerr << "Fatal error: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
