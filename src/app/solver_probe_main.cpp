#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/ConservativeStep.hpp"
#include "physics/ConservativeAdvance.hpp"
#include "physics/MechanicalAccounting.hpp"
#include <chrono>
#include <algorithm>
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
        double h = .08, dt = 1.0 / 240.0, gap = .001, speed = 1, restitution = 1;
        unsigned steps = 1, iterations = 256, linear_iterations = 400;
        bool global = true;
        bool floor = false, global_support = true;
        bool events = false;
        banjo::MaterialPreset preset = banjo::MaterialPreset::Glass;
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            if (++i >= argc) throw std::invalid_argument("missing probe option value");
            if (option == "--material") {
                const std::string name = argv[i];
                if (name == "glass") preset = banjo::MaterialPreset::Glass;
                else if (name == "oak" || name == "wood") preset = banjo::MaterialPreset::Oak;
                else if (name == "iron") preset = banjo::MaterialPreset::Iron;
                else throw std::invalid_argument("material must be glass, oak (wood), or iron");
                continue;
            }
            if (option == "--step-mode") {
                const std::string name = argv[i];
                if (name != "raw" && name != "events") throw std::invalid_argument("step mode must be raw or events");
                events = name == "events";
                continue;
            }
            if (option == "--solver") {
                const std::string solver = argv[i];
                if (solver != "newton" && solver != "local")
                    throw std::invalid_argument("solver must be newton or local");
                global = solver == "newton";
                continue;
            }
            if (option == "--case") {
                const std::string name = argv[i];
                if (name != "free" && name != "floor") throw std::invalid_argument("case must be free or floor");
                floor = name == "floor";
                continue;
            }
            if (option == "--support-solver") {
                const std::string name = argv[i];
                if (name != "coupled" && name != "split") throw std::invalid_argument("support solver must be coupled or split");
                global_support = name == "coupled";
                continue;
            }
            std::size_t used = 0;
            const double value = std::stod(argv[i], &used);
            if (used != std::string(argv[i]).size() || !std::isfinite(value) || value < 0 ||
                (value == 0 && option != "--gap" && option != "--restitution"))
                throw std::invalid_argument("probe values must be finite and positive (gap/restitution may be zero)");
            if (option == "--voxel-size") h = value;
            else if (option == "--dt") dt = value;
            else if (option == "--gap") gap = value;
            else if (option == "--speed") speed = value;
            else if (option == "--restitution" && value <= 1) restitution = value;
            else if ((option == "--steps" || option == "--iterations" || option == "--linear-iterations") &&
                     value <= 100000 && std::floor(value) == value) {
                if (option == "--steps") steps = static_cast<unsigned>(value);
                else if (option == "--iterations") iterations = static_cast<unsigned>(value);
                else linear_iterations = static_cast<unsigned>(value);
            } else throw std::invalid_argument("unknown probe option or invalid integer count");
        }
        if (!events && restitution != 1)
            throw std::invalid_argument("--restitution requires --step-mode events");
        const auto material = banjo::makeReferenceMaterial(preset, 17);
        const auto compiled = banjo::compileElasticLatticeReference(material, h, 2);
        const auto asset = banjo::generateSphereLattice({.25, h, 2, 3}, compiled);
        banjo::ActiveMatter matter;
        matter.asset = &asset;
        matter.material = compiled;
        matter.bonds.resize(asset.bonds.size());
        const banjo::Vec3 translation = floor ? banjo::Vec3{.3, -speed, .2} : banjo::Vec3{.3, -.1, .2};
        const banjo::Vec3 spin = floor ? banjo::Vec3{} : banjo::Vec3{1, -2, 3};
        for (const auto &node : asset.nodes) matter.nodes.push_back({node.local_position_m, {},
            translation + banjo::cross(spin, node.local_position_m),
            node.represented_volume_m3 * compiled.density_kg_m3, spin});
        double minimum_y = matter.nodes.front().position_world_m.y;
        for (const auto &node : matter.nodes) minimum_y = std::min(minimum_y, node.position_world_m.y);
        const auto support = banjo::makeSupportPlane({0, minimum_y - gap, 0}, {0, 1, 0});
        const auto before = banjo::measureMaterialMechanics(matter);
        banjo::Vec3 support_impulse, support_angular_impulse;
        double contact_loss = 0, impact_loss = 0;
        std::cout << std::setprecision(12) << "Elastic reference probe: catalog=" << banjo::materialPresetName(preset)
                  << "; isotropic central-bond approximation; zero gravity/damage; no wood anisotropy or metal plasticity\n"
                  << "nodes=" << matter.nodes.size() << " bonds=" << matter.bonds.size() << " h=" << h
                  << " dt=" << dt << " requested_steps=" << steps << " solver=" << (global ? "newton" : "local") << '\n'
                  << "case=" << (floor ? "floor" : "free") << " floor_gap_m=" << gap << " floor_speed_m_s=" << speed
                  << " support_solver=" << (global && global_support ? "coupled" : "split")
                  << " step_mode=" << (events ? "events" : "raw") << " prescribed_event_restitution=" << restitution << '\n'
                  << "step,accepted,iterations,linear_iterations,velocity_residual_m_s,energy_residual_j,wall_ms,normal_loss_j,support_impulse_y,penetration_m,impact_loss_j,substeps,trials,impact_events\n";
        for (unsigned i = 0; i < steps; ++i) {
            const auto start = std::chrono::steady_clock::now();
            const banjo::ConservativeStepSettings step_settings{.maximum_iterations = iterations,
                .support = floor ? &support : nullptr, .global_elastic_solve = global,
                .maximum_linear_iterations = linear_iterations, .global_support_solve = global_support};
            banjo::ConservativeAdvanceResult advance;
            banjo::ConservativeStepResult result;
            if (events) {
                advance = banjo::tryConservativeAdvance(matter, dt, {}, nullptr, {.step=step_settings,.normal_restitution=restitution});
                result = advance.balance;
            } else result = banjo::tryConservativeStep(matter, dt, {}, nullptr, step_settings);
            const auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
            std::cout << i << ',' << result.converged << ',' << result.iterations << ',' << result.linear_iterations << ','
                      << result.constitutive_velocity_residual_m_s << ',';
            if (result.balance_measured) std::cout << result.energy_residual_j;
            std::cout << ',' << elapsed << ',';
            if (result.balance_measured) std::cout << result.normal_contact_loss_j << ',' << result.support_impulse_kg_m_s.y
                                                 << ',' << result.maximum_penetration_m;
            else std::cout << ",,";
            std::cout << ',' << advance.impact_loss_j << ',' << (events ? advance.substeps : (result.converged ? 1 : 0))
                      << ',' << (events ? advance.trials : 1) << ',' << advance.impact_events << '\n';
            if (!result.converged) {
                std::cout << "REJECTED: convergence/energy/contact contract not met; input state retained. Failed-row work/counters are unpublished trial diagnostics.\n";
                if (events) std::cout << "advance_failure=" << banjo::advanceFailureName(advance.failure)
                    << " last_trial_accepted=" << advance.last_trial.converged << " last_velocity_residual="
                    << advance.last_trial.constitutive_velocity_residual_m_s
                    << " remaining_s=" << advance.remaining_time_s << " last_dt_s=" << advance.last_trial_dt_s
                    << " gap_m=" << advance.last_new_gap_m << " bracket_s=[" << advance.event_lo_s << ',' << advance.event_hi_s
                    << "] bracket_gap_m=[" << advance.event_lo_gap_m << ',' << advance.event_hi_gap_m << "]\n";
                return 2;
            }
            support_impulse += result.support_impulse_kg_m_s;
            support_angular_impulse += result.support_angular_impulse_kg_m2_s;
            contact_loss += result.normal_contact_loss_j;
            impact_loss += advance.impact_loss_j;
        }
        const auto after = banjo::measureMaterialMechanics(matter);
        std::cout << "balance-P=" << banjo::length(after.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s - support_impulse)
                  << " balance-L=" << banjo::length(after.angular_momentum_kg_m2_s - before.angular_momentum_kg_m2_s - support_angular_impulse)
                  << " balance-E=" << after.mechanicalEnergy() - before.mechanicalEnergy() + contact_loss + impact_loss
                  << " normal-loss=" << contact_loss << " impact-loss=" << impact_loss << " support-impulse-y=" << support_impulse.y
                  << " final-COM-vy=" << after.linear_momentum_kg_m_s.y / after.mass_kg << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "Probe error: " << error.what() << '\n';
        return 1;
    }
}
