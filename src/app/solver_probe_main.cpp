#include "material/MaterialCatalog.hpp"
#include "matter/Lattice.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/ConservativeStep.hpp"
#include "physics/FractureStep.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "physics/ConservativeAdvance.hpp"
#include "physics/CompliantStep.hpp"
#include "physics/CompliantAdvance.hpp"
#include "physics/MechanicalAccounting.hpp"
#include <chrono>
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

// Convergence/performance probe of the actual sampled elastic material. It is
// deliberately separate from the current lab: no damage, friction or activation
// is implied by a successful elastic reference step.
int main(int argc, char **argv) {
    try {
        double h = .08, dt = 1.0 / 240.0, gap = .001, speed = 1, restitution = 1, gravity_magnitude = 0;
        double normal_stiffness = 0, normal_damping = 0, max_compression = 0;
        unsigned steps = 1, iterations = 256, linear_iterations = 400, sample_every = 1;
        double stretch_rate = 0;
        unsigned fracture_trials = 64, bisections = 8;
        bool fracture = false;
        banjo::BondFailureTiming timing = banjo::BondFailureTiming::StepRestart;
        std::string trajectory_path;
        bool sample_every_set = false;
        bool global = true;
        bool floor = false, global_support = true;
        bool events = false, compliant = false, adaptive = false, restitution_set = false, compliance_set = false;
        bool adaptive_options = false;
        double error_scale=1;
        banjo::CompliantAdvanceSettings adaptive_settings;
        banjo::MaterialPreset preset = banjo::MaterialPreset::Glass;
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            if (++i >= argc) throw std::invalid_argument("missing probe option value");
            if (option == "--trajectory") { trajectory_path = argv[i]; continue; }
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
                if (name != "raw" && name != "events" && name != "compliant" && name != "adaptive" && name != "fracture")
                    throw std::invalid_argument("step mode must be raw, events, compliant, adaptive, or fracture");
                events = name == "events";
                adaptive = name == "adaptive";
                compliant = name == "compliant" || adaptive;
                fracture = name == "fracture";
                continue;
            }
            if (option == "--fracture-timing") {
                const std::string name = argv[i];
                if (name == "end") timing = banjo::BondFailureTiming::EndOfStep;
                else if (name == "restart") timing = banjo::BondFailureTiming::StepRestart;
                else if (name == "bisect") timing = banjo::BondFailureTiming::BisectedTime;
                else throw std::invalid_argument("fracture timing must be end, restart, or bisect");
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
            else if (option == "--stretch-rate") stretch_rate = value;
            else if (option == "--error-scale") { error_scale=value; adaptive_options=true; }
            else if (option == "--error-reference-time") { adaptive_settings.error.reference_time_s=value; adaptive_options=true; }
            else if (option == "--max-trial-dt") { adaptive_settings.maximum_trial_dt_s=value; adaptive_options=true; }
            else if (option == "--min-trial-dt") { adaptive_settings.minimum_trial_dt_s=value; adaptive_options=true; }
            else if ((option == "--steps" || option == "--iterations" || option == "--linear-iterations" || option == "--sample-every" ||
                      option == "--trial-budget" || option == "--fracture-trials" || option == "--bisections") &&
                     value <= 100000 && std::floor(value) == value) {
                if (option == "--steps") steps = static_cast<unsigned>(value);
                else if (option == "--iterations") iterations = static_cast<unsigned>(value);
                else if (option == "--linear-iterations") linear_iterations = static_cast<unsigned>(value);
                else if (option == "--trial-budget") { adaptive_settings.maximum_trials=static_cast<unsigned>(value); adaptive_options=true; }
                else if (option == "--fracture-trials") fracture_trials = static_cast<unsigned>(value);
                else if (option == "--bisections") bisections = static_cast<unsigned>(value);
                else { sample_every=static_cast<unsigned>(value); sample_every_set=true; }
            } else throw std::invalid_argument("unknown probe option or invalid integer count");
        }
        if (fracture && (events || compliant)) throw std::invalid_argument("fracture mode is its own step mode");
        if (fracture && !global) throw std::invalid_argument("fracture mode drives the global Newton solve");
        if (!events && restitution_set)
            throw std::invalid_argument("--restitution requires --step-mode events");
        if (!compliant && compliance_set) throw std::invalid_argument("normal-compliance parameters require --step-mode compliant");
        if (compliant && (!global || !global_support || normal_stiffness<=0 || max_compression<=0))
            throw std::invalid_argument("compliant mode requires global coupling, --normal-stiffness and --max-compression");
        if (sample_every_set && trajectory_path.empty()) throw std::invalid_argument("--sample-every requires --trajectory");
        if (adaptive_options && !adaptive) throw std::invalid_argument("adaptive error/trial options require --step-mode adaptive");
        adaptive_settings.error.position_m*=error_scale;
        adaptive_settings.error.velocity_m_s*=error_scale;
        adaptive_settings.error.bond_strain*=error_scale;
        adaptive_settings.error.damping_work_j*=error_scale;
        adaptive_settings.initial_trial_dt_s=adaptive_settings.maximum_trial_dt_s;
        std::ofstream trajectory;
        if (!trajectory_path.empty()) {
            trajectory.exceptions(std::ios::badbit | std::ios::failbit);
            trajectory.open(trajectory_path);
            trajectory << std::setprecision(std::numeric_limits<double>::max_digits10)
                << "time_s,node,mass_kg,x_m,y_m,z_m,vx_m_s,vy_m_s,vz_m_s,wx_rad_s,wy_rad_s,wz_rad_s\n";
        }
        const auto material = banjo::makeReferenceMaterial(preset, 17);
        // Fracture needs a failure surface. The strength-derived thresholds keep
        // the elastic reference's zero damping and uniform (unvaried) strength so
        // a material comparison is not confounded; see MaterialCompiler.hpp for
        // what this does and does not claim about oak and iron.
        const auto compiled = fracture
            ? banjo::withStrengthDerivedFailure(banjo::compileElasticLatticeReference(material, h, 2), material)
            : banjo::compileElasticLatticeReference(material, h, 2);
        const auto asset = banjo::generateSphereLattice({.25, h, 2, 3}, compiled);
        banjo::ActiveMatter matter;
        matter.asset = &asset;
        matter.material = compiled;
        matter.bonds.resize(asset.bonds.size());
        const banjo::Vec3 translation = floor ? banjo::Vec3{.3, -speed, .2} : banjo::Vec3{.3, -.1, .2};
        const banjo::Vec3 spin = floor ? banjo::Vec3{} : banjo::Vec3{1, -2, 3};
        for (const auto &node : asset.nodes) {
            // Authored initial state: a uniaxial expansion rate about the lattice
            // origin loads the body in tension without a contact event. Nothing
            // here assigns fragment velocities; it is the intact body's start.
            const banjo::Vec3 stretch{stretch_rate * node.local_position_m.x, 0, 0};
            matter.nodes.push_back({node.local_position_m, {},
                translation + stretch + banjo::cross(spin, node.local_position_m),
                node.represented_volume_m3 * compiled.density_kg_m3, spin});
            matter.reference_positions_world_m.push_back(node.local_position_m);
        }
        const auto write_trajectory = [&](double time) {
            if (trajectory_path.empty()) return;
            for (std::size_t n=0;n<matter.nodes.size();++n) {
                const auto &node=matter.nodes[n];
                const auto p=node.position_world_m, v=node.velocity_m_s, w=node.spin_angular_velocity_rad_s;
                trajectory << time << ',' << n << ',' << node.mass_kg << ',' << p.x << ',' << p.y << ',' << p.z
                    << ',' << v.x << ',' << v.y << ',' << v.z << ',' << w.x << ',' << w.y << ',' << w.z << '\n';
            }
        };
        write_trajectory(0);
        double minimum_y = matter.nodes.front().position_world_m.y;
        for (const auto &node : matter.nodes) minimum_y = std::min(minimum_y, node.position_world_m.y);
        const auto support = banjo::makeSupportPlane({0, minimum_y - gap, 0}, {0, 1, 0});
        const banjo::Vec3 gravity{0,-gravity_magnitude,0};
        const auto before = banjo::measureMaterialMechanics(matter,gravity);
        banjo::Vec3 support_impulse, support_angular_impulse;
        banjo::Vec3 gravity_angular_impulse, previous_moment = before.mass_first_moment_kg_m;
        double contact_loss = 0, impact_loss = 0, compliance_loss = 0, contact_energy = 0, initial_contact_energy = 0;
        double removed_bond_energy = 0;
        std::size_t broken_bonds = 0;
        unsigned fracture_trials_used = 0, discarded_trials_used = 0;
        std::cout << std::setprecision(12) << "Elastic reference probe: catalog=" << banjo::materialPresetName(preset)
                  << "; isotropic central-bond approximation; "
                  << (fracture ? "strength-derived bond failure" : "zero damage")
                  << "; no wood anisotropy or metal plasticity\n"
                  << "nodes=" << matter.nodes.size() << " bonds=" << matter.bonds.size() << " h=" << h
                  << " dt=" << dt << " requested_steps=" << steps << " solver=" << (global ? "newton" : "local") << '\n'
                  << "case=" << (floor ? "floor" : "free") << " floor_gap_m=" << gap << " floor_speed_m_s=" << speed
                  << " support_solver=" << (global && global_support ? "coupled" : "split")
                  << " step_mode=" << (events ? "events" : (adaptive ? "adaptive" : (compliant ? "compliant" : (fracture ? "fracture" : "raw"))))
                  << " gravity_m_s2=" << gravity_magnitude << " stretch_rate_1_s=" << stretch_rate;
        if (fracture) std::cout << "\nfracture_timing=" << (timing == banjo::BondFailureTiming::EndOfStep ? "end"
                : (timing == banjo::BondFailureTiming::StepRestart ? "restart" : "bisect"))
            << " fracture_trials=" << fracture_trials << " max_bisections=" << bisections
            << " tensile_damage_start=" << compiled.damage_start_stretch << " tensile_break=" << compiled.damage_end_stretch
            << " shear_damage_start=" << compiled.shear_damage_start_strain << " shear_break=" << compiled.shear_damage_end_strain
            << " compression_damage_start=" << compiled.compression_damage_start_strain
            << "; strength-derived isotropic failure surface, uncalibrated against laboratory data";
        {
            // The step a fracture criterion is read at, against the step this
            // lattice needs to carry its own elastic wave. Above the limit the
            // strain the criterion sees is a discretisation result.
            const auto limit = banjo::measureLatticeResolutionLimit(asset, compiled);
            std::cout << "\nlattice_fastest_mode_period_s=" << limit.fastest_mode_period_s
                      << " explicit_substep_limit_s=" << limit.explicit_substep_limit_s
                      << " dt_over_substep_limit=" << (limit.explicit_substep_limit_s > 0 ? dt / limit.explicit_substep_limit_s : 0);
        }
        if (events) std::cout << " prescribed_event_restitution=" << restitution;
        if (compliant) std::cout << " normal_stiffness_n_m=" << normal_stiffness << " compression_damping_kg_s=" << normal_damping
            << " max_compression_m=" << max_compression << "; explicit per-contact law, uncalibrated interface";
        if (adaptive) std::cout << "\nerror_position_m=" << adaptive_settings.error.position_m
            << " error_velocity_m_s=" << adaptive_settings.error.velocity_m_s << " error_bond_strain=" << adaptive_settings.error.bond_strain
            << " error_damping_work_j=" << adaptive_settings.error.damping_work_j << " error_reference_time_s=" << adaptive_settings.error.reference_time_s
            << " max_trial_dt_s=" << adaptive_settings.maximum_trial_dt_s << " min_trial_dt_s=" << adaptive_settings.minimum_trial_dt_s
            << " maximum_trials=" << adaptive_settings.maximum_trials << "; local full-vs-two-half indicators; no exact-solution guarantee";
        std::cout << "\nstep,accepted,iterations,linear_iterations,velocity_residual_m_s,energy_residual_j,wall_ms,normal_loss_j,support_impulse_y,penetration_m,impact_loss_j,substeps,trials,impact_events,contact_energy_j,contact_damping_loss_j,modeled_compression_m,body_elastic_energy_j,internal_kinetic_energy_j,com_y_m,com_vy_m_s,rejected_segments,max_accepted_error,min_accepted_step_s,broken_bonds,total_broken,live_bonds,components,largest_component,removed_bond_energy_j,solver_trials,discarded_trials,fracture_bisections,max_tensile_strain,max_shear_strain\n";
        for (unsigned i = 0; i < steps; ++i) {
            const auto start = std::chrono::steady_clock::now();
            const banjo::ConservativeStepSettings step_settings{.maximum_iterations = iterations,
                .support = floor ? &support : nullptr, .global_elastic_solve = global,
                .maximum_linear_iterations = linear_iterations, .global_support_solve = global_support};
            banjo::ConservativeAdvanceResult advance;
            banjo::CompliantStepResult compliant_result;
            banjo::CompliantAdvanceResult adaptive_result;
            banjo::ConservativeStepResult result;
            banjo::FractureStepResult fracture_result;
            if (fracture) {
                fracture_result = banjo::tryFracturingStep(matter, dt, gravity, nullptr,
                    {.solver = step_settings, .timing = timing,
                     .maximum_solver_trials = fracture_trials, .maximum_bisections = bisections});
                result = fracture_result.last_trial;
                result.converged = fracture_result.converged;
                result.balance_measured = fracture_result.converged;
                result.iterations = fracture_result.newton_iterations;
                result.linear_iterations = fracture_result.linear_iterations;
                result.energy_residual_j = fracture_result.energy_residual_j;
                result.normal_contact_loss_j = fracture_result.normal_contact_loss_j;
                result.support_impulse_kg_m_s = fracture_result.support_impulse_kg_m_s;
                result.support_angular_impulse_kg_m2_s = fracture_result.support_angular_impulse_kg_m2_s;
                result.maximum_penetration_m = fracture_result.maximum_penetration_m;
            } else if (events) {
                advance = banjo::tryConservativeAdvance(matter, dt, gravity, nullptr, {.step=step_settings,.normal_restitution=restitution});
                result = advance.balance;
            } else if (adaptive) {
                adaptive_settings.step={.solver=step_settings,.normal={normal_stiffness,normal_damping},.maximum_compression_m=max_compression};
                adaptive_result=banjo::tryCompliantAdvance(matter,dt,adaptive_settings,gravity);
                compliant_result=adaptive_result.step;
                result=compliant_result.balance;
                if (result.converged) adaptive_settings.initial_trial_dt_s=adaptive_result.suggested_trial_dt_s;
            } else if (compliant) {
                compliant_result = banjo::tryCompliantStep(matter,dt,
                    {.solver=step_settings,.normal={normal_stiffness,normal_damping},.maximum_compression_m=max_compression},gravity);
                result = compliant_result.balance;
            } else result = banjo::tryConservativeStep(matter, dt, gravity, nullptr, step_settings);
            const auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
            const auto measured = banjo::measureMaterialMechanics(matter,gravity);
            std::cout << i << ',' << result.converged << ',' << result.iterations << ',' << result.linear_iterations << ','
                      << result.constitutive_velocity_residual_m_s << ',';
            if (result.balance_measured) std::cout << result.energy_residual_j;
            std::cout << ',' << elapsed << ',';
            if (result.balance_measured) std::cout << result.normal_contact_loss_j << ',' << result.support_impulse_kg_m_s.y
                                                 << ',' << result.maximum_penetration_m;
            else std::cout << ",,";
            std::cout << ',' << advance.impact_loss_j << ',' << (events ? advance.substeps : (adaptive ? 2*adaptive_result.accepted_segments : (result.converged ? 1 : 0)))
                      << ',' << (events ? advance.trials : (adaptive ? adaptive_result.trials : 1)) << ',' << advance.impact_events << ','
                      << compliant_result.contact_energy_after_j << ',' << compliant_result.contact_damping_loss_j
                      << ',' << compliant_result.maximum_compression_m << ',';
            if (result.converged) {
                const double bulk = .5*banjo::lengthSquared(measured.linear_momentum_kg_m_s)/measured.mass_kg;
                std::cout << measured.elastic_energy_j << ',' << measured.kinetic_energy_j-bulk << ','
                    << measured.mass_first_moment_kg_m.y/measured.mass_kg << ',' << measured.linear_momentum_kg_m_s.y/measured.mass_kg;
            } else std::cout << ",,,";
            std::cout << ',' << adaptive_result.rejected_segments << ',' << adaptive_result.maximum_accepted_error
                << ',' << adaptive_result.minimum_accepted_step_s;
            if (fracture && fracture_result.converged) {
                const auto components = banjo::findConnectedComponents(matter);
                std::cout << ',' << fracture_result.broken_bonds << ',' << (matter.bonds.size() - fracture_result.live_bonds)
                    << ',' << fracture_result.live_bonds << ',' << components.size()
                    << ',' << (components.empty() ? 0 : components.front().node_indices.size())
                    << ',' << fracture_result.removed_bond_energy_j << ',' << fracture_result.solver_trials
                    << ',' << fracture_result.discarded_trials << ',' << fracture_result.bisections
                    << ',' << fracture_result.maximum_tensile_stretch << ',' << fracture_result.maximum_shear_strain;
            } else std::cout << ",,,,,,,,,,";
            std::cout << '\n';
            if (!result.converged) {
                if (fracture) std::cout << "fracture_failure=" << (fracture_result.failure == banjo::FractureStepFailure::SolverRejected
                        ? "solver_rejected" : "trial_budget_exhausted")
                    << " solver_trials=" << fracture_result.solver_trials
                    << " discarded_trials=" << fracture_result.discarded_trials
                    << " last_trial_converged=" << fracture_result.last_trial.converged
                    << " last_velocity_residual=" << fracture_result.last_trial.constitutive_velocity_residual_m_s << '\n';
                std::cout << "REJECTED: convergence/energy/contact contract not met; input state retained. Failed-row work/counters are unpublished trial diagnostics.\n";
                if (events) std::cout << "advance_failure=" << banjo::advanceFailureName(advance.failure)
                    << " last_trial_accepted=" << advance.last_trial.converged << " last_velocity_residual="
                    << advance.last_trial.constitutive_velocity_residual_m_s
                    << " remaining_s=" << advance.remaining_time_s << " last_dt_s=" << advance.last_trial_dt_s
                    << " gap_m=" << advance.last_new_gap_m << " bracket_s=[" << advance.event_lo_s << ',' << advance.event_hi_s
                    << "] bracket_gap_m=[" << advance.event_lo_gap_m << ',' << advance.event_hi_gap_m << "]\n";
                if (adaptive) std::cout << "adaptive_failure=" << banjo::compliantAdvanceFailureName(adaptive_result.failure)
                    << " last_raw_failure=" << banjo::compliantFailureName(adaptive_result.last_trial.failure)
                    << " remaining_s=" << adaptive_result.remaining_time_s << " trial_dt_s=" << adaptive_result.last_trial_dt_s
                    << " error=" << adaptive_result.last_error.normalized
                    << " last_E=" << adaptive_result.last_trial.balance.energy_residual_j
                    << " last_P=" << banjo::length(adaptive_result.last_trial.balance.linear_momentum_residual_kg_m_s)
                    << " last_L=" << banjo::length(adaptive_result.last_trial.balance.angular_momentum_residual_kg_m2_s) << '\n';
                else if (compliant) std::cout << "compliant_failure=" << banjo::compliantFailureName(compliant_result.failure) << '\n';
                return 2;
            }
            support_impulse += result.support_impulse_kg_m_s;
            support_angular_impulse += result.support_angular_impulse_kg_m2_s;
            contact_loss += result.normal_contact_loss_j;
            impact_loss += advance.impact_loss_j;
            compliance_loss += compliant_result.contact_damping_loss_j;
            removed_bond_energy += fracture_result.removed_bond_energy_j;
            broken_bonds += fracture_result.broken_bonds;
            fracture_trials_used += fracture_result.solver_trials;
            discarded_trials_used += fracture_result.discarded_trials;
            contact_energy = compliant_result.contact_energy_after_j;
            if (i==0) initial_contact_energy = compliant_result.contact_energy_before_j;
            const auto moment = measured.mass_first_moment_kg_m;
            gravity_angular_impulse += banjo::cross(.5*dt*(previous_moment+moment),gravity);
            previous_moment = moment;
            if ((i+1)%sample_every==0 || i+1==steps) write_trajectory((i+1)*dt);
        }
        const auto after = banjo::measureMaterialMechanics(matter,gravity);
        std::cout << "balance-P=" << banjo::length(after.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s - support_impulse - (dt*steps*before.mass_kg)*gravity)
                  << " balance-L=" << banjo::length(after.angular_momentum_kg_m2_s - before.angular_momentum_kg_m2_s - support_angular_impulse - gravity_angular_impulse)
                  << " balance-E=" << after.mechanicalEnergy() - before.mechanicalEnergy() + contact_loss + impact_loss + compliance_loss + contact_energy-initial_contact_energy + removed_bond_energy
                  << " normal-loss=" << contact_loss << " impact-loss=" << impact_loss << " support-impulse-y=" << support_impulse.y
                  << " final-COM-vy=" << after.linear_momentum_kg_m_s.y / after.mass_kg
                  << " contact-energy=" << contact_energy << " compliance-loss=" << compliance_loss
                  << " removed-bond-energy=" << removed_bond_energy;
        if (fracture) {
            const auto components = banjo::findConnectedComponents(matter);
            std::size_t largest = components.empty() ? 0 : components.front().node_indices.size();
            // Distinguish a real fragment from a lattice-surface crumb: report the
            // mass that left the largest component and the node masses involved.
            double detached_mass = 0, total_mass = 0, minimum_detached = 0, maximum_detached = 0;
            std::size_t detached_nodes = 0;
            for (const auto &node : matter.nodes) total_mass += node.mass_kg;
            for (std::size_t c = 1; c < components.size(); ++c)
                for (const auto n : components[c].node_indices) {
                    const double mass = matter.nodes[n].mass_kg;
                    detached_mass += mass;
                    ++detached_nodes;
                    if (minimum_detached == 0 || mass < minimum_detached) minimum_detached = mass;
                    maximum_detached = std::max(maximum_detached, mass);
                }
            double minimum_node_mass = matter.nodes.empty() ? 0 : matter.nodes.front().mass_kg;
            double maximum_node_mass = minimum_node_mass;
            for (const auto &node : matter.nodes) maximum_node_mass = std::max(maximum_node_mass, node.mass_kg);
            for (const auto &node : matter.nodes) minimum_node_mass = std::min(minimum_node_mass, node.mass_kg);
            std::cout << " broken-bonds=" << broken_bonds << " live-bonds=" << (matter.bonds.size() - banjo::countBrokenBonds(matter))
                      << " components=" << components.size() << " largest-component=" << largest
                      << " detached-nodes=" << detached_nodes
                      << " detached-mass-fraction=" << (total_mass > 0 ? detached_mass / total_mass : 0)
                      << " detached-node-mass-range=[" << minimum_detached << ',' << maximum_detached << ']'
                      << " lattice-node-mass-range=[" << minimum_node_mass << ',' << maximum_node_mass << ']'
                      << " lattice-node-mass-mean=" << (total_mass / static_cast<double>(matter.nodes.size()))
                      << " tensile-failures=" << banjo::countBondFailureModes(matter).tensile
                      << " compressive-failures=" << banjo::countBondFailureModes(matter).compressive
                      << " shear-failures=" << banjo::countBondFailureModes(matter).shear
                      << " solver-trials=" << fracture_trials_used << " discarded-trials=" << discarded_trials_used;
        }
        std::cout << '\n';
        if (!trajectory_path.empty()) trajectory.close();
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "Probe error: " << error.what() << '\n';
        return 1;
    }
}
