#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/ConservativeStep.hpp"
#include "physics/MechanicalAccounting.hpp"
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

// Convergence/performance probe of the actual sampled elastic material. It is
// deliberately separate from the current lab: no damage, friction or activation
// is implied by a successful elastic reference step.
int main(int argc, char **argv) {
    try {
        double h = .08, dt = 1.0 / 240.0;
        unsigned steps = 1, iterations = 256;
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            if (++i >= argc) throw std::invalid_argument("missing probe option value");
            std::size_t used = 0;
            const double value = std::stod(argv[i], &used);
            if (used != std::string(argv[i]).size() || !std::isfinite(value) || value <= 0)
                throw std::invalid_argument("probe values must be finite and positive");
            if (option == "--voxel-size") h = value;
            else if (option == "--dt") dt = value;
            else if ((option == "--steps" || option == "--iterations") && value <= 100000 && std::floor(value) == value) {
                if (option == "--steps") steps = static_cast<unsigned>(value);
                else iterations = static_cast<unsigned>(value);
            } else throw std::invalid_argument("unknown probe option or invalid integer count");
        }
        const auto material = banjo::makeReferenceMaterial(banjo::MaterialPreset::Glass, 17);
        const auto compiled = banjo::compileBrittleMaterial(material, h, 2);
        const auto asset = banjo::generateSphereLattice({.25, h, 2, 3}, compiled);
        banjo::ActiveMatter matter;
        matter.asset = &asset;
        matter.material = compiled;
        matter.bonds.resize(asset.bonds.size());
        const banjo::Vec3 translation{.3, -.1, .2}, spin{1, -2, 3};
        for (const auto &node : asset.nodes) matter.nodes.push_back({node.local_position_m, {},
            translation + banjo::cross(spin, node.local_position_m),
            node.represented_volume_m3 * compiled.density_kg_m3, spin});
        const auto before = banjo::measureMaterialMechanics(matter);
        std::cout << std::setprecision(12) << "Elastic reference probe: actual glass preset, zero gravity/contact/damage\n"
                  << "nodes=" << matter.nodes.size() << " bonds=" << matter.bonds.size() << " h=" << h
                  << " dt=" << dt << " requested_steps=" << steps << '\n'
                  << "step,accepted,iterations,velocity_residual_m_s,energy_residual_j,wall_ms\n";
        for (unsigned i = 0; i < steps; ++i) {
            const auto start = std::chrono::steady_clock::now();
            const auto result = banjo::tryConservativeStep(matter, dt, {}, nullptr, {.maximum_iterations = iterations});
            const auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
            std::cout << i << ',' << result.converged << ',' << result.iterations << ','
                      << result.constitutive_velocity_residual_m_s << ',';
            if (result.balance_measured) std::cout << result.energy_residual_j;
            std::cout << ',' << elapsed << '\n';
            if (!result.converged) {
                std::cout << "REJECTED: convergence/energy/contact contract not met; input state retained.\n";
                return 2;
            }
        }
        const auto after = banjo::measureMaterialMechanics(matter);
        std::cout << "delta-P=" << banjo::length(after.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s)
                  << " delta-L=" << banjo::length(after.angular_momentum_kg_m2_s - before.angular_momentum_kg_m2_s)
                  << " delta-E=" << after.mechanicalEnergy() - before.mechanicalEnergy() << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "Probe error: " << error.what() << '\n';
        return 1;
    }
}
