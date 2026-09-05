#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/ConservativeStep.hpp"
#include "physics/ConservativeAdvance.hpp"
#include "physics/CompliantStep.hpp"
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
        double h = .08, dt = 1.0 / 240.0, gap = .001, speed = 1, restitution = 1, gravity_magnitude = 0;
        double normal_stiffness = 0, normal_damping = 0, max_compression = 0;
        unsigned steps = 1, iterations = 256, linear_iterations = 400;
        bool global = true;
        bool floor = false, global_support = true;
        bool events = false, compliant = false, restitution_set = false, compliance_set = false;
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
                if (name != "raw" && name != "events" && name != "compliant")
                    throw std::invalid_argument("step mode must be raw, events, or compliant");
                events = name == "events";
                compliant = name == "compliant";
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
                (value == 0 && option != "--gap" && option != "--restitution" && option != "--normal-damping" &&
                 option != "--speed" && option != "--gravity"))
                throw std::invalid_argument("invalid nonnegative probe value");
            if (option == "--voxel-size") h = value;
            else if (option == "--dt") dt = value;
            else if (option == "--gap") gap = value;
            else if (option == "--speed") speed = value;
            else if (option == "--gravity") gravity_magnitude = value;
            else if (option == "--restitution" && value <= 1) { restitution = value; restitution_set = true; }
            else if (option == "--normal-stiffness") { normal_stiffness = value; compliance_set = true; }
            else if (option == "--normal-damping") { normal_damping = value; compliance_set = true; }
            else if (option == "--max-compression") { max_compression = value; compliance_set = true; }
            else if ((option == "--steps" || option == "--iterations" || option == "--linear-iterations") &&
                     value <= 100000 && std::floor(value) == value) {
                if (option == "--steps") steps = static_cast<unsigned>(value);
                else if (option == "--iterations") iterations = static_cast<unsigned>(value);
                else linear_iterations = static_cast<unsigned>(value);
            } else throw std::invalid_argument("unknown probe option or invalid integer count");
        }
        if (!events && restitution_set)
            throw std::invalid_argument("--restitution requires --step-mode events");
        if (!compliant && compliance_set) throw std::invalid_argument("normal-compliance parameters require --step-mode compliant");
        if (compliant && (!global || !global_support || normal_stiffness<=0 || max_compression<=0))
            throw std::invalid_argument("compliant mode requires global coupling, --normal-stiffness and --max-compression");
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
        const banjo::Vec3 gravity{0,-gravity_magnitude,0};
        const auto before = banjo::measureMaterialMechanics(matter,gravity);
        banjo::Vec3 support_impulse, support_angular_impulse;
        banjo::Vec3 gravity_angular_impulse, previous_moment = before.mass_first_moment_kg_m;
        double contact_loss = 0, impact_loss = 0, compliance_loss = 0, contact_energy = 0, initial_contact_energy = 0;
        std::cout << std::setprecision(12) << "Elastic reference probe: catalog=" << banjo::materialPresetName(preset)
                  << "; isotropic central-bond approximation; zero damage; no wood anisotropy or metal plasticity\n"
                  << "nodes=" << matter.nodes.size() << " bonds=" << matter.bonds.size() << " h=" << h
                  << " dt=" << dt << " requested_steps=" << steps << " solver=" << (global ? "newton" : "local") << '\n'
                  << "case=" << (floor ? "floor" : "free") << " floor_gap_m=" << gap << " floor_speed_m_s=" << speed
                  << " support_solver=" << (global && global_support ? "coupled" : "split")
                  << " step_mode=" << (events ? "events" : (compliant ? "compliant" : "raw")) << " gravity_m_s2=" << gravity_magnitude;
        if (events) std::cout << " prescribed_event_restitution=" << restitution;
        if (compliant) std::cout << " normal_stiffness_n_m=" << normal_stiffness << " compression_damping_kg_s=" << normal_damping
            << " max_compression_m=" << max_compression << "; explicit per-contact law, uncalibrated interface";
        std::cout << "\nstep,accepted,iterations,linear_iterations,velocity_residual_m_s,energy_residual_j,wall_ms,normal_loss_j,support_impulse_y,penetration_m,impact_loss_j,substeps,trials,impact_events,contact_energy_j,contact_damping_loss_j,modeled_compression_m\n";
        for (unsigned i = 0; i < steps; ++i) {
            const auto start = std::chrono::steady_clock::now();
            const banjo::ConservativeStepSettings step_settings{.maximum_iterations = iterations,
                .support = floor ? &support : nullptr, .global_elastic_solve = global,
                .maximum_linear_iterations = linear_iterations, .global_support_solve = global_support};
            banjo::ConservativeAdvanceResult advance;
            banjo::CompliantStepResult compliant_result;
            banjo::ConservativeStepResult result;
            if (events) {
                advance = banjo::tryConservativeAdvance(matter, dt, gravity, nullptr, {.step=step_settings,.normal_restitution=restitution});
                result = advance.balance;
            } else if (compliant) {
                compliant_result = banjo::tryCompliantStep(matter,dt,
                    {.solver=step_settings,.normal={normal_stiffness,normal_damping},.maximum_compression_m=max_compression},gravity);
                result = compliant_result.balance;
            } else result = banjo::tryConservativeStep(matter, dt, gravity, nullptr, step_settings);
            const auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
            std::cout << i << ',' << result.converged << ',' << result.iterations << ',' << result.linear_iterations << ','
                      << result.constitutive_velocity_residual_m_s << ',';
            if (result.balance_measured) std::cout << result.energy_residual_j;
            std::cout << ',' << elapsed << ',';
            if (result.balance_measured) std::cout << result.normal_contact_loss_j << ',' << result.support_impulse_kg_m_s.y
                                                 << ',' << result.maximum_penetration_m;
            else std::cout << ",,";
            std::cout << ',' << advance.impact_loss_j << ',' << (events ? advance.substeps : (result.converged ? 1 : 0))
                      << ',' << (events ? advance.trials : 1) << ',' << advance.impact_events << ','
                      << compliant_result.contact_energy_after_j << ',' << compliant_result.contact_damping_loss_j
                      << ',' << compliant_result.maximum_compression_m << '\n';
            if (!result.converged) {
                std::cout << "REJECTED: convergence/energy/contact contract not met; input state retained. Failed-row work/counters are unpublished trial diagnostics.\n";
                if (events) std::cout << "advance_failure=" << banjo::advanceFailureName(advance.failure)
                    << " last_trial_accepted=" << advance.last_trial.converged << " last_velocity_residual="
                    << advance.last_trial.constitutive_velocity_residual_m_s
                    << " remaining_s=" << advance.remaining_time_s << " last_dt_s=" << advance.last_trial_dt_s
                    << " gap_m=" << advance.last_new_gap_m << " bracket_s=[" << advance.event_lo_s << ',' << advance.event_hi_s
                    << "] bracket_gap_m=[" << advance.event_lo_gap_m << ',' << advance.event_hi_gap_m << "]\n";
                if (compliant) std::cout << "compliant_failure=" << banjo::compliantFailureName(compliant_result.failure) << '\n';
                return 2;
            }
            support_impulse += result.support_impulse_kg_m_s;
            support_angular_impulse += result.support_angular_impulse_kg_m2_s;
            contact_loss += result.normal_contact_loss_j;
            impact_loss += advance.impact_loss_j;
            compliance_loss += compliant_result.contact_damping_loss_j;
            contact_energy = compliant_result.contact_energy_after_j;
            if (i==0) initial_contact_energy = compliant_result.contact_energy_before_j;
            const auto moment = banjo::measureMaterialMechanics(matter,gravity).mass_first_moment_kg_m;
            gravity_angular_impulse += banjo::cross(.5*dt*(previous_moment+moment),gravity);
            previous_moment = moment;
        }
        const auto after = banjo::measureMaterialMechanics(matter,gravity);
        std::cout << "balance-P=" << banjo::length(after.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s - support_impulse - (dt*steps*before.mass_kg)*gravity)
                  << " balance-L=" << banjo::length(after.angular_momentum_kg_m2_s - before.angular_momentum_kg_m2_s - support_angular_impulse - gravity_angular_impulse)
                  << " balance-E=" << after.mechanicalEnergy() - before.mechanicalEnergy() + contact_loss + impact_loss + compliance_loss + contact_energy-initial_contact_energy
                  << " normal-loss=" << contact_loss << " impact-loss=" << impact_loss << " support-impulse-y=" << support_impulse.y
                  << " final-COM-vy=" << after.linear_momentum_kg_m_s.y / after.mass_kg
                  << " contact-energy=" << contact_energy << " compliance-loss=" << compliance_loss << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "Probe error: " << error.what() << '\n';
        return 1;
    }
}
