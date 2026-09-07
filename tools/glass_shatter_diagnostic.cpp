// Diagnostic instrumentation for the voxel/bond fracture lane.
//
// This tool measures, per fixed tick, what the active material solver actually
// does: bond survival, emergent component counts and sizes, node kinematics,
// and the signed per-stage mechanical-energy changes. It changes no material
// law and makes no physical claim by itself; it exists so that statements about
// fragmentation can be replaced by measured mechanism.
//
// The handoff windows in ExperimentSettings are counted in material steps, so
// refining the material step also shortens them in physical time. This tool
// therefore expresses them as physical durations, which keeps a timestep
// refinement study comparing the same experiment.

#include "fracture/ConnectedComponents.hpp"
#include "sim/RollingBallExperiment.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

namespace {

using namespace banjo;

struct NodeSummary {
    double maximum_speed_m_s{};
    double maximum_displacement_m{};
};

NodeSummary summarizeNodes(const ActiveMatter *matter) {
    NodeSummary summary;
    if (matter == nullptr) return summary;
    for (std::size_t i = 0; i < matter->nodes.size(); ++i) {
        const auto &node = matter->nodes[i];
        summary.maximum_speed_m_s = std::max(summary.maximum_speed_m_s, length(node.velocity_m_s));
        if (i < matter->reference_positions_world_m.size())
            summary.maximum_displacement_m = std::max(summary.maximum_displacement_m,
                length(node.position_world_m - matter->reference_positions_world_m[i]));
    }
    return summary;
}

struct ComponentSummary {
    std::size_t count{};
    std::size_t largest_nodes{};
    std::size_t singletons{};
    std::size_t at_least_eight{};
};

ComponentSummary summarizeComponents(const ActiveMatter *matter) {
    ComponentSummary summary;
    if (matter == nullptr) return summary;
    const auto components = findConnectedComponents(*matter);
    summary.count = components.size();
    for (const auto &component : components) {
        summary.largest_nodes = std::max(summary.largest_nodes, component.node_indices.size());
        if (component.node_indices.size() == 1) ++summary.singletons;
        if (component.node_indices.size() >= 8) ++summary.at_least_eight;
    }
    return summary;
}

double numericOption(const std::string &value) {
    std::size_t used = 0;
    const double result = std::stod(value, &used);
    if (used != value.size() || !std::isfinite(result)) throw std::invalid_argument("bad number");
    return result;
}

MaterialPreset presetFromName(std::string_view name) {
    if (name == "glass") return MaterialPreset::Glass;
    if (name == "oak") return MaterialPreset::Oak;
    if (name == "iron") return MaterialPreset::Iron;
    if (name == "ceramic") return MaterialPreset::Ceramic;
    if (name == "ice") return MaterialPreset::Ice;
    if (name == "concrete") return MaterialPreset::Concrete;
    throw std::invalid_argument("unknown material name: " + std::string(name));
}

} // namespace

int main(int argc, char **argv) {
    try {
        ExperimentSettings settings;
        // Physical-time equivalents of the shipped step-counted defaults at the
        // 1/240 s material step, so refinement studies keep the same experiment.
        double minimum_material_time_s = 180.0 / 240.0;
        double stable_material_time_s = 60.0 / 240.0;
        double maximum_material_time_s = 480.0 / 240.0;
        unsigned maximum_ticks = 400;
        unsigned print_stride = 1;
        bool quiet = false;
        for (int i = 1; i < argc; ++i) {
            const std::string_view option = argv[i];
            const auto value = [&]() -> std::string {
                if (++i >= argc) throw std::invalid_argument("missing option value");
                return argv[i];
            };
            if (option == "--target") settings.target_material = presetFromName(value());
            else if (option == "--striker") settings.striker_material = presetFromName(value());
            else if (option == "--surface") settings.surface_material = presetFromName(value());
            else if (option == "--speed") settings.iron_speed_m_s = numericOption(value());
            else if (option == "--voxel-size") settings.voxel_size_m = numericOption(value());
            else if (option == "--material-step") settings.material_step_s = numericOption(value());
            else if (option == "--substeps") settings.material_substeps =
                static_cast<unsigned>(numericOption(value()));
            else if (option == "--iterations") settings.material_constraint_iterations =
                static_cast<unsigned>(numericOption(value()));
            else if (option == "--stable-time") stable_material_time_s = numericOption(value());
            else if (option == "--minimum-time") minimum_material_time_s = numericOption(value());
            else if (option == "--maximum-time") maximum_material_time_s = numericOption(value());
            else if (option == "--ticks") maximum_ticks = static_cast<unsigned>(numericOption(value()));
            else if (option == "--stride") print_stride = std::max(1U,
                static_cast<unsigned>(numericOption(value())));
            else if (option == "--quiet") quiet = true;
            else if (option == "--no-support") settings.support_enabled = false;
            else if (option == "--no-gravity") settings.gravity_m_s2 = {};
            else if (option == "--isolated") { settings.support_enabled = false; settings.gravity_m_s2 = {}; }
            else throw std::invalid_argument("unknown option: " + std::string(option));
        }
        const auto steps = [&](double seconds) {
            return std::max(1U, static_cast<unsigned>(std::llround(seconds / settings.material_step_s)));
        };
        settings.minimum_material_steps = steps(minimum_material_time_s);
        settings.stable_material_steps_before_handoff = steps(stable_material_time_s);
        settings.maximum_material_steps = steps(maximum_material_time_s);
        settings.audit_material_stages = true;

        RollingBallExperiment experiment(settings);
        std::cout << std::setprecision(6);
        std::cout << "target=" << materialPresetName(settings.target_material)
                  << " striker=" << materialPresetName(settings.striker_material)
                  << " speed=" << settings.iron_speed_m_s
                  << " voxel=" << settings.voxel_size_m
                  << " material_dt=" << settings.material_step_s
                  << " substeps=" << settings.material_substeps
                  << " iterations=" << settings.material_constraint_iterations
                  << " support=" << (settings.support_enabled ? 1 : 0)
                  << " windows_s=" << minimum_material_time_s << '/' << stable_material_time_s
                  << '/' << maximum_material_time_s << '\n';
        const auto *lattice = experiment.targetLattice();
        if (lattice != nullptr)
            std::cout << "nodes=" << lattice->nodes.size() << " bonds=" << lattice->bonds.size()
                      << " mass=" << lattice->total_mass_kg << " kg\n";
        else
            std::cout << "nodes=0 bonds=0 (target material is not a brittle-bond model)\n";
        {
            const auto &limit = experiment.stats().target_resolution_limit;
            const double substep = settings.material_step_s /
                                   std::max(1U, settings.material_substeps);
            std::cout << "fastest_mode_period_s=" << limit.fastest_mode_period_s
                      << " explicit_substep_limit_s=" << limit.explicit_substep_limit_s
                      << " configured_substep_s=" << substep << " ratio="
                      << (limit.explicit_substep_limit_s > 0
                              ? substep / limit.explicit_substep_limit_s : 0.0)
                      << std::endl;
        }

        if (!quiet)
            std::cout << "tick,time_s,phase,live_bonds,broken,components,largest_nodes,singletons,"
                         "components_ge8,max_stretch,kinetic_j,elastic_j,max_speed_m_s,max_disp_m,"
                         "removal_j,d_removal_j,d_prediction_j,d_constraints_j,d_post_contact_j,"
                         "d_support_j,d_damage_j\n";
        MaterialStageChanges previous_stages{};
        double previous_removal = 0;
        ComponentSummary final_components;
        for (unsigned tick = 0; tick < maximum_ticks; ++tick) {
            experiment.stepFixed();
            const auto &stats = experiment.stats();
            const auto *matter = experiment.activeMatter();
            const auto summary = summarizeNodes(matter);
            const auto components = summarizeComponents(matter);
            if (components.count > 0) final_components = components;
            const auto stage = [&](MaterialStage which) {
                const auto index = static_cast<std::size_t>(which);
                return stats.material_stage_changes[index].mechanicalEnergy() -
                       previous_stages[index].mechanicalEnergy();
            };
            if (!quiet && (tick % print_stride == 0 || stats.phase == ExperimentPhase::RigidFragments)) {
                std::cout << tick << ',' << stats.simulated_time_s << ','
                          << static_cast<unsigned>(stats.phase) << ','
                          << (matter != nullptr ? matter->bonds.size() - stats.broken_bonds : 0) << ','
                          << stats.broken_bonds << ',' << components.count << ','
                          << components.largest_nodes << ',' << components.singletons << ','
                          << components.at_least_eight << ',' << stats.maximum_tensile_stretch << ','
                          << stats.active_kinetic_energy_j << ',' << stats.active_elastic_energy_j << ','
                          << summary.maximum_speed_m_s << ',' << summary.maximum_displacement_m << ','
                          << stats.unassigned_bond_removal_energy_j << ','
                          << stats.unassigned_bond_removal_energy_j - previous_removal << ','
                          << stage(MaterialStage::Prediction) << ',' << stage(MaterialStage::Constraints) << ','
                          << stage(MaterialStage::PostContact) << ',' << stage(MaterialStage::Support) << ','
                          << stage(MaterialStage::Damage) << '\n';
            }
            previous_stages = stats.material_stage_changes;
            previous_removal = stats.unassigned_bond_removal_energy_j;
            if (stats.phase == ExperimentPhase::RigidFragments) break;
        }
        const auto &stats = experiment.stats();
        std::cout << "SUMMARY dt=" << settings.material_step_s
                  << " substeps=" << settings.material_substeps
                  << " phase=" << static_cast<unsigned>(stats.phase)
                  << " t=" << stats.simulated_time_s
                  << " broken=" << stats.broken_bonds << '/' << stats.total_bonds
                  << " components=" << stats.connected_components
                  << " largest_nodes=" << final_components.largest_nodes
                  << " singletons=" << final_components.singletons
                  << " components_ge8=" << final_components.at_least_eight
                  << " rigid_fragments=" << stats.rigid_fragments
                  << " debris=" << stats.debris_particles
                  << " impact_j=" << stats.impact_energy_j
                  << " removal_j=" << stats.unassigned_bond_removal_energy_j
                  << " mass_error_kg=" << stats.mass_error_kg << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
