#include "modal/ModalFracture.hpp"

#include "fracture/ConnectedComponents.hpp"
#include "physics/ConservativeStepInternal.hpp"
#include "physics/MechanicalAccounting.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <numbers>
#include <stdexcept>
#include <unordered_map>

namespace banjo::modal {
namespace {

using Clock = std::chrono::steady_clock;

double since(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

struct ModalState {
    std::vector<double> q;
    std::vector<double> qdot;
    RigidSnapshot ball{};
};

// Closed-form advance of every mode by dt under a constant modal force.
void evolve(const ModalBasis &basis, const std::vector<double> &force, const ModalState &in, double dt,
            ModalState &out) {
    const std::size_t n = basis.modes();
    out.q.resize(n);
    out.qdot.resize(n);
    const auto &omega2 = basis.omegaSquared();
    for (std::size_t k = 0; k < n; ++k) {
        const double q = in.q[k], qdot = in.qdot[k], f = force[k];
        if (basis.isRigidMode(k)) {
            out.q[k] = q + qdot * dt + 0.5 * f * dt * dt;
            out.qdot[k] = qdot + f * dt;
        } else {
            const double w2 = omega2[k];
            const double w = std::sqrt(w2);
            const double s = f / w2;
            const double c = std::cos(w * dt), sn = std::sin(w * dt);
            const double a = q - s;
            out.q[k] = s + a * c + qdot / w * sn;
            out.qdot[k] = -a * w * sn + qdot * c;
        }
    }
    out.ball = in.ball;
}

// sin(w dt)/w per mode: the displacement at dt from a unit modal velocity at 0.
void impulseWeights(const ModalBasis &basis, double dt, std::vector<double> &weights) {
    const std::size_t n = basis.modes();
    weights.resize(n);
    const auto &omega2 = basis.omegaSquared();
    for (std::size_t k = 0; k < n; ++k) {
        if (basis.isRigidMode(k)) weights[k] = dt;
        else {
            const double w = std::sqrt(omega2[k]);
            weights[k] = std::sin(w * dt) / w;
        }
    }
}

// 3x3 block of the impulse response: displacement of free node j at dt from a
// unit impulse at free node k applied at 0.
Mat3 impulseResponse(const ModalBasis &basis, const std::vector<double> &weights,
                     std::uint32_t j, std::uint32_t k) {
    const std::size_t n = basis.modes();
    const DenseMatrix &phi = basis.phi();
    Mat3 g;
    for (unsigned a = 0; a < 3; ++a) {
        const double *rj = phi.row(3 * j + a);
        for (unsigned b = 0; b < 3; ++b) {
            const double *rk = phi.row(3 * k + b);
            double sum = 0.0;
            for (std::size_t i = 0; i < n; ++i) sum += weights[i] * rj[i] * rk[i];
            g.m[a][b] = sum;
        }
    }
    return g;
}

double modalEnergy(const ModalBasis &basis, const std::vector<double> &force, const ModalState &state) {
    const std::size_t n = basis.modes();
    const auto &omega2 = basis.omegaSquared();
    double kinetic = 0.0, elastic = 0.0, potential = 0.0;
    for (std::size_t k = 0; k < n; ++k) {
        kinetic += 0.5 * state.qdot[k] * state.qdot[k];
        if (!basis.isRigidMode(k)) elastic += 0.5 * omega2[k] * state.q[k] * state.q[k];
        potential -= force[k] * state.q[k];
    }
    return kinetic + elastic + potential;
}

double ballEnergy(const ModalBall &ball, const RigidSnapshot &motion, const Vec3 &gravity) {
    return 0.5 * ball.mass_kg * lengthSquared(motion.linear_velocity_m_s) -
           ball.mass_kg * dot(gravity, motion.center_of_mass_world_m) +
           0.5 * ball.inertia_kg_m2 * lengthSquared(motion.angular_velocity_rad_s);
}

double modalElasticEnergy(const ModalBasis &basis, const std::vector<double> &q) {
    double elastic = 0.0;
    const auto &omega2 = basis.omegaSquared();
    for (std::size_t k = 0; k < basis.modes(); ++k)
        if (!basis.isRigidMode(k)) elastic += 0.5 * omega2[k] * q[k] * q[k];
    return elastic;
}

void applyPositions(ActiveMatter &matter, const std::vector<Vec3> &positions) {
    for (std::size_t i = 0; i < matter.nodes.size(); ++i) matter.nodes[i].position_world_m = positions[i];
}

} // namespace

ModalFractureResult runModalImpact(ActiveMatter &matter, const std::vector<std::uint32_t> &free_nodes,
                                   ModalBall &ball, const ModalFractureSettings &settings) {
    if (!(settings.sample_dt_s > 0.0) || !std::isfinite(settings.sample_dt_s) ||
        !(settings.window_s > 0.0) || !std::isfinite(settings.window_s) ||
        settings.maximum_trials_per_interval == 0U || settings.maximum_contact_sweeps == 0U ||
        !(settings.frame_interval_s > 0.0))
        throw std::invalid_argument("modal fracture settings need positive intervals and budgets");
    if (!(ball.mass_kg > 0.0) || !(ball.contact_radius_m > 0.0) || !(ball.radius_m > 0.0) ||
        !(ball.inertia_kg_m2 > 0.0) || !std::isfinite(lengthSquared(ball.motion.center_of_mass_world_m)) ||
        !std::isfinite(lengthSquared(ball.motion.linear_velocity_m_s)))
        throw std::invalid_argument("modal fracture needs a finite ball with positive mass and radii");
    if (matter.asset == nullptr || matter.bonds.size() != matter.asset->bonds.size())
        throw std::invalid_argument("modal fracture needs matching lattice state");

    const auto total_start = Clock::now();
    ModalFractureResult result;
    ModalBuildTimings build;
    ModalBasisOptions basis_options;
    basis_options.retained_fraction = settings.retained_mode_fraction;
    ModalBasis basis(matter, free_nodes, basis_options, &build);
    result.timings.basis_assemble_s = build.assemble_s;
    result.timings.basis_decompose_s = build.decompose_s;
    result.modes = basis.modes();
    result.fastest_period_s = 2.0 * std::numbers::pi / std::sqrt(basis.omegaSquaredMaxAtCreation());
    const std::size_t n = basis.modes();
    const std::size_t node_count = matter.nodes.size();
    const Vec3 gravity = settings.gravity_m_s2;

    // Modal gravity force f = phi^T M g.
    std::vector<double> weighted(basis.dofs());
    for (std::size_t f = 0; f < basis.freeNodes().size(); ++f) {
        const double m = basis.freeNodeMasses()[f];
        weighted[3 * f] = m * gravity.x;
        weighted[3 * f + 1] = m * gravity.y;
        weighted[3 * f + 2] = m * gravity.z;
    }
    std::vector<double> force;
    basis.projectForce(weighted, force);

    ModalState state;
    state.q.assign(n, 0.0);
    state.qdot.assign(n, 0.0);
    state.ball = ball.motion;
    if (settings.start_from_static_sag)
        for (std::size_t k = 0; k < n; ++k)
            if (!basis.isRigidMode(k)) state.q[k] = force[k] / basis.omegaSquared()[k];

    std::vector<Vec3> positions_t(node_count), positions_end(node_count);
    std::vector<double> field;
    const auto fieldPositions = [&](const std::vector<double> &q, std::vector<Vec3> &positions) {
        const auto start = Clock::now();
        basis.displacement(q, field);
        for (std::size_t i = 0; i < node_count; ++i) positions[i] = matter.reference_positions_world_m[i];
        for (std::size_t f = 0; f < basis.freeNodes().size(); ++f) {
            const std::uint32_t node = basis.freeNodes()[f];
            positions[node] += Vec3{field[3 * f], field[3 * f + 1], field[3 * f + 2]};
        }
        result.timings.field_s += since(start);
    };
    fieldPositions(state.q, positions_t);
    applyPositions(matter, positions_t);
    for (auto &node : matter.nodes) node.velocity_m_s = {};

    std::vector<std::uint32_t> component_of_node(node_count, 0U);
    const auto labelComponents = [&]() {
        const auto start = Clock::now();
        const auto components = findConnectedComponents(matter);
        for (const auto &component : components)
            for (const std::uint32_t node : component.node_indices) component_of_node[node] = component.id;
        result.components = components.size();
        result.largest_component = components.empty() ? 0 : components.front().node_indices.size();
        result.timings.components_s += since(start);
        return components.size();
    };
    labelComponents();

    const auto captureFrame = [&](double time, const std::vector<Vec3> &positions, const RigidSnapshot &motion) {
        const auto start = Clock::now();
        ModalFrame frame{time, positions, component_of_node, motion, countBrokenBonds(matter), {}, {}};
        frame.bond_alive.reserve(matter.bonds.size());
        frame.bond_damage.reserve(matter.bonds.size());
        for (const auto &bond : matter.bonds) {
            frame.bond_alive.push_back(bond.alive ? 1U : 0U);
            frame.bond_damage.push_back(static_cast<float>(bond.damage));
        }
        result.frames.push_back(std::move(frame));
        result.timings.frames_s += since(start);
    };
    captureFrame(0.0, positions_t, state.ball);

    result.ledger.energy_start_j = modalEnergy(basis, force, state) + ballEnergy(ball, state.ball, gravity);

    const double cell = matter.asset->recipe.voxel_size_m;
    const double near_margin = ball.contact_radius_m + 2.0 * cell;
    std::vector<double> weights;
    std::vector<std::uint32_t> near_nodes, active;
    std::vector<double> lambda;
    std::vector<Vec3> near_predicted;
    std::vector<Mat3> diagonal_response;
    std::unordered_map<std::uint64_t, Mat3> pair_response;
    std::vector<std::uint32_t> removed;
    std::vector<BondFailureMode> removed_modes;
    std::vector<ActiveBondState> bonds_at_interval_start;
    ModalState predicted, working;
    std::vector<std::vector<double> *> carried{&state.q, &state.qdot, &force};
    bool contact_seen = false;
    // The start sample of an interval was the previous interval's accepted end
    // sample under the same topology, so it is re-evaluated only after the
    // topology changed (and once at the very start).
    bool start_sample_pending = true;
    double last_frame_time = 0.0;
    double time = 0.0;
    std::vector<unsigned> live_neighbours(node_count, 0U);
    const auto countLiveNeighbours = [&]() {
        std::fill(live_neighbours.begin(), live_neighbours.end(), 0U);
        for (std::size_t b = 0; b < matter.bonds.size(); ++b) {
            if (!matter.bonds[b].alive) continue;
            ++live_neighbours[matter.asset->bonds[b].node_a];
            ++live_neighbours[matter.asset->bonds[b].node_b];
        }
    };

    while (time < settings.window_s) {
        // Rounding must not leave a microscopic tail interval: over such an
        // interval every impulse response is roundoff-sized and a
        // roundoff-sized gap correction becomes an enormous impulse. The
        // stepped reference applies the same guard to its remaining time.
        const double remaining = settings.window_s - time;
        if (remaining <= 1.0e-9 * settings.sample_dt_s) break;
        const double dt = std::min(settings.sample_dt_s, remaining);
        bonds_at_interval_start = matter.bonds;
        unsigned interval_trials = 0;
        while (true) {
            if (interval_trials >= settings.maximum_trials_per_interval) {
                result.interval_budget_exhausted = true;
                break;
            }
            ++interval_trials;
            ++result.trials;

            // ---- free prediction ------------------------------------------
            // The contact impulse acts at `impulse_time` into the interval;
            // `working` holds the state at that instant, where impulses are
            // added, and `predicted` the end of the interval.
            const double impulse_time = settings.contact_impulse_at_midpoint ? 0.5 * dt : 0.0;
            const double after_impulse = dt - impulse_time;
            auto stage = Clock::now();
            if (impulse_time > 0.0) evolve(basis, force, state, impulse_time, working);
            else working = state;
            evolve(basis, force, working, after_impulse, predicted);
            result.timings.evolve_s += since(stage);
            working.ball = state.ball;
            working.ball.center_of_mass_world_m = state.ball.center_of_mass_world_m +
                impulse_time * state.ball.linear_velocity_m_s + (0.5 * impulse_time * impulse_time) * gravity;
            working.ball.linear_velocity_m_s = state.ball.linear_velocity_m_s + impulse_time * gravity;
            RigidSnapshot ball_end = state.ball;
            ball_end.center_of_mass_world_m = state.ball.center_of_mass_world_m +
                dt * state.ball.linear_velocity_m_s + (0.5 * dt * dt) * gravity;
            ball_end.linear_velocity_m_s = state.ball.linear_velocity_m_s + dt * gravity;

            // ---- contact: impulses at the interval start put every node that
            // would penetrate at its end onto the sphere surface -------------
            stage = Clock::now();
            near_nodes.clear();
            for (std::size_t f = 0; f < basis.freeNodes().size(); ++f) {
                const std::uint32_t node = basis.freeNodes()[f];
                if (length(positions_t[node] - state.ball.center_of_mass_world_m) < near_margin)
                    near_nodes.push_back(static_cast<std::uint32_t>(f));
            }
            double energy_before_impulse = 0.0, energy_after_impulse = 0.0;
            bool contact_this_interval = false;
            if (!near_nodes.empty()) {
                impulseWeights(basis, after_impulse, weights);
                near_predicted.resize(near_nodes.size());
                for (std::size_t c = 0; c < near_nodes.size(); ++c)
                    near_predicted[c] = matter.reference_positions_world_m[basis.freeNodes()[near_nodes[c]]] +
                                        basis.nodeDisplacement(predicted.q, near_nodes[c]);
                const double rc2 = ball.contact_radius_m * ball.contact_radius_m;
                active.clear();
                for (std::size_t c = 0; c < near_nodes.size(); ++c)
                    if (lengthSquared(near_predicted[c] - ball_end.center_of_mass_world_m) < rc2)
                        active.push_back(static_cast<std::uint32_t>(c));
                if (!active.empty()) {
                    contact_this_interval = true;
                    contact_seen = true;
                    ++result.contact_samples;
                    energy_before_impulse = modalEnergy(basis, force, working) + ballEnergy(ball, working.ball, gravity);
                    lambda.assign(near_nodes.size(), 0.0);
                    diagonal_response.resize(near_nodes.size());
                    pair_response.clear();
                    std::vector<char> is_active(near_nodes.size(), 0);
                    for (const std::uint32_t c : active) {
                        diagonal_response[c] = impulseResponse(basis, weights, near_nodes[c], near_nodes[c]);
                        is_active[c] = 1;
                    }
                    const auto response = [&](std::uint32_t row, std::uint32_t column) -> const Mat3 & {
                        if (row == column) return diagonal_response[row];
                        const std::uint64_t key = (static_cast<std::uint64_t>(row) << 32U) | column;
                        auto found = pair_response.find(key);
                        if (found == pair_response.end())
                            found = pair_response.emplace(key,
                                impulseResponse(basis, weights, near_nodes[row], near_nodes[column])).first;
                        return found->second;
                    };
                    const double inverse_ball_mass = 1.0 / ball.mass_kg;
                    const double admit_radius2 = rc2 * (1.0 - 2.0 * settings.contact_impulse_tolerance);
                    // Outer passes: resolve the active set, then re-predict every
                    // near node from the modal state and admit any that the
                    // impulses pushed into the sphere. The reference checks every
                    // node on every iteration; this is the same guarantee.
                    unsigned pass = 0;
                    for (; pass < settings.maximum_contact_passes; ++pass) {
                        unsigned sweep = 0;
                        for (; sweep < settings.maximum_contact_sweeps; ++sweep) {
                            double worst = 0.0;
                            for (const std::uint32_t c : active) {
                                const std::uint32_t node = basis.freeNodes()[near_nodes[c]];
                                const Vec3 p0 = positions_t[node] - state.ball.center_of_mass_world_m;
                                const Vec3 p1 = near_predicted[c] - ball_end.center_of_mass_world_m;
                                const Vec3 normal = normalized(p0 + p1);
                                const double projection = dot(p1, normal);
                                const double distance = -projection + std::sqrt(std::max(0.0,
                                    projection * projection + rc2 - lengthSquared(p1)));
                                const double node_response = dot(normal, diagonal_response[c] * normal);
                                if (node_response < 0.0) {
                                    ++result.negative_response_events;
                                    result.most_negative_response = std::min(result.most_negative_response, node_response);
                                }
                                double w = node_response + after_impulse * inverse_ball_mass;
                                if (!(w > 0.0)) w = after_impulse * (1.0 / basis.freeNodeMasses()[near_nodes[c]] + inverse_ball_mass);
                                double delta = distance / w;
                                if (lambda[c] + delta < 0.0) delta = -lambda[c];
                                if (delta == 0.0) continue;
                                lambda[c] += delta;
                                if (std::abs(delta) > result.largest_impulse_n_s) {
                                    result.largest_impulse_n_s = std::abs(delta);
                                    result.largest_impulse_response_w = w;
                                    result.largest_impulse_distance_m = distance;
                                    result.largest_impulse_time_s = time;
                                    result.largest_impulse_node = node;
                                    result.largest_impulse_pass = pass;
                                    result.largest_impulse_sweep = sweep;
                                    result.largest_impulse_node_response = node_response;
                                    const auto &o2 = basis.omegaSquared();
                                    result.largest_impulse_omega2_max = *std::max_element(o2.begin(), o2.end());
                                    result.largest_impulse_omega2_min = *std::min_element(o2.begin(), o2.end());
                                    result.largest_impulse_weight_min = *std::min_element(weights.begin(), weights.end());
                                    result.largest_impulse_diag_trace = diagonal_response[c].m[0][0] +
                                        diagonal_response[c].m[1][1] + diagonal_response[c].m[2][2];
                                }
                                const Vec3 impulse = delta * normal;
                                basis.addNodeImpulse(working.qdot, near_nodes[c], impulse);
                                working.ball.linear_velocity_m_s -= inverse_ball_mass * impulse;
                                for (const std::uint32_t k : active)
                                    near_predicted[k] += response(k, c) * impulse;
                                ball_end.center_of_mass_world_m -= (after_impulse * inverse_ball_mass) * impulse;
                                worst = std::max(worst, std::abs(delta) * w);
                            }
                            if (worst <= settings.contact_impulse_tolerance * ball.contact_radius_m) break;
                        }
                        result.maximum_sweeps_used = std::max(result.maximum_sweeps_used, sweep);
                        if (sweep >= settings.maximum_contact_sweeps) ++result.sweep_budget_exhausted;
                        // Exact end state under the impulses so far, for every near node.
                        evolve(basis, force, working, after_impulse, predicted);
                        bool admitted = false;
                        for (std::size_t c = 0; c < near_nodes.size(); ++c) {
                            near_predicted[c] = matter.reference_positions_world_m[basis.freeNodes()[near_nodes[c]]] +
                                                basis.nodeDisplacement(predicted.q, near_nodes[c]);
                            if (is_active[c]) continue;
                            if (lengthSquared(near_predicted[c] - ball_end.center_of_mass_world_m) < admit_radius2) {
                                active.push_back(static_cast<std::uint32_t>(c));
                                is_active[c] = 1;
                                diagonal_response[c] = impulseResponse(basis, weights, near_nodes[c], near_nodes[c]);
                                admitted = true;
                            }
                        }
                        if (!admitted) break;
                    }
                    if (pass >= settings.maximum_contact_passes) ++result.contact_passes_exhausted;
                    result.peak_contact_nodes = std::max(result.peak_contact_nodes, active.size());
                    ball_end.linear_velocity_m_s = working.ball.linear_velocity_m_s + after_impulse * gravity;
                    energy_after_impulse = modalEnergy(basis, force, working) + ballEnergy(ball, working.ball, gravity);
                    evolve(basis, force, working, after_impulse, predicted);
                }
            }
            result.timings.contact_s += since(stage);

            fieldPositions(predicted.q, positions_end);
            {
                const double rc = ball.contact_radius_m;
                double deepest = 0.0;
                for (const std::uint32_t node : basis.freeNodes()) {
                    const double penetration = rc - length(positions_end[node] - ball_end.center_of_mass_world_m);
                    deepest = std::max(deepest, penetration);
                }
                if (deepest > 4.0 * settings.contact_impulse_tolerance * rc) {
                    ++result.penetration_violations;
                    result.maximum_end_penetration_m = std::max(result.maximum_end_penetration_m, deepest);
                }
            }

            // ---- the shared failure criterion at both interval ends -------
            stage = Clock::now();
            resetBondStrainPeaks(matter);
            if (start_sample_pending) {
                applyPositions(matter, positions_t);
                accumulateBondStrainPeaks(matter);
            }
            applyPositions(matter, positions_end);
            accumulateBondStrainPeaks(matter);
            removed.clear();
            const auto summary = applyBondFailure(matter, &removed);
            result.maximum_tensile_stretch = std::max(result.maximum_tensile_stretch, summary.maximum_tensile_stretch);
            result.maximum_compressive_strain = std::max(result.maximum_compressive_strain, summary.maximum_compressive_strain);
            result.maximum_shear_strain = std::max(result.maximum_shear_strain, summary.maximum_shear_strain);
            result.timings.criterion_s += since(stage);

            if (removed.empty()) {
                state = predicted;
                state.ball = ball_end;
                state.ball.orientation_world = detail::advanceSphereOrientation(
                    state.ball.orientation_world, state.ball.angular_velocity_rad_s, dt);
                positions_t.swap(positions_end);
                if (contact_this_interval) result.ledger.contact_loss_j += energy_before_impulse - energy_after_impulse;
                else if (contact_seen && result.ball_separation_time_s < 0.0) result.ball_separation_time_s = time + dt;
                time += dt;
                ++result.samples;
                start_sample_pending = false;
                if (result.samples % 64 == 0 || contact_this_interval) {
                    basis.displacement(state.qdot, field);
                    for (std::size_t f = 0; f < basis.freeNodes().size(); ++f)
                        result.peak_node_speed_m_s = std::max(result.peak_node_speed_m_s,
                            length(Vec3{field[3 * f], field[3 * f + 1], field[3 * f + 2]}));
                }
                break;
            }

            // ---- the interval is inadmissible: remove at its start --------
            ++result.discarded_trials;
            applyPositions(matter, positions_t);
            matter.bonds = bonds_at_interval_start;
            // The restore discarded the trial's bond states, so the failure
            // mode of each removed bond is re-evaluated from the same two
            // samples the trial used.
            removed_modes.assign(removed.size(), BondFailureMode::Tension);
            {
                applyPositions(matter, positions_end);
                resetBondStrainPeaks(matter);
                applyPositions(matter, positions_t);
                accumulateBondStrainPeaks(matter);
                applyPositions(matter, positions_end);
                accumulateBondStrainPeaks(matter);
                for (std::size_t r = 0; r < removed.size(); ++r)
                    removed_modes[r] = evaluateBondDamage(matter.bonds[removed[r]], matter.asset->bonds[removed[r]]).mode;
                applyPositions(matter, positions_t);
            }
            ModalRound round;
            round.time_s = time;
            round.interval_trial = interval_trials;
            round.bonds = removed;
            round.modes = removed_modes;
            countLiveNeighbours();
            round.fewest_live_neighbours = std::numeric_limits<unsigned>::max();
            for (std::size_t r = 0; r < removed.size(); ++r) {
                const auto &state_b = matter.bonds[removed[r]];
                const auto &rest_b = matter.asset->bonds[removed[r]];
                const double over = std::max({state_b.peak_tensile_stretch / rest_b.damage_end_stretch,
                    state_b.peak_compressive_strain / rest_b.compression_damage_end_strain,
                    state_b.peak_shear_strain / rest_b.shear_damage_end_strain});
                round.trigger_over_threshold = std::max(round.trigger_over_threshold, over);
                round.fewest_live_neighbours = std::min({round.fewest_live_neighbours,
                    live_neighbours[rest_b.node_a], live_neighbours[rest_b.node_b]});
            }
            const auto removal = removeBondsAtCurrentState(matter, removed, removed_modes);
            start_sample_pending = true;
            round.removed_bond_energy_j = removal.removed_elastic_energy_j;
            bonds_at_interval_start = matter.bonds;

            stage = Clock::now();
            // Linearised stored energy of the removed bonds at the start state.
            basis.displacement(state.q, field);
            for (const std::uint32_t bond : removed) {
                const BondGradient g = basis.bondGradient(matter, bond);
                double extension = 0.0;
                for (unsigned i = 0; i < g.count; ++i) extension += g.value[i] * field[g.dof[i]];
                round.removed_linear_energy_j += 0.5 * g.stiffness_n_m * extension * extension;
            }
            const bool rebuild_now = settings.basis_mode == BasisMode::Recompute ||
                (settings.basis_mode == BasisMode::Auto && removed.size() >= settings.rebuild_at_bonds_per_round);
            if (!rebuild_now) {
                for (const std::uint32_t bond : removed) {
                    const auto stats = basis.removeBond(matter, bond, carried);
                    round.retained_modes_total += stats.retained;
                    round.deflated_total += stats.deflated_small + stats.deflated_equal;
                }
            } else {
                ModalBuildTimings rebuild;
                basis.rebuild(matter, carried, &rebuild);
                round.rebuilt = true;
            }
            round.update_wall_s = since(stage);
            result.timings.update_s += round.update_wall_s;
            if (settings.check_basis) {
                round.basis_residual = basis.residualAgainst(matter);
                round.basis_orthogonality = basis.orthogonalityDefect();
                const auto fresh = decomposeSymmetric(basis.assembleScaledStiffness(matter));
                std::vector<double> mine = basis.omegaSquared();
                std::sort(mine.begin(), mine.end());
                const double scale = std::max(1.0, fresh.values.back());
                for (std::size_t k = 0; k < mine.size(); ++k)
                    round.basis_value_error = std::max(round.basis_value_error,
                        std::abs(mine[k] - fresh.values[k]) / scale);
            }
            result.ledger.removed_linear_energy_j += round.removed_linear_energy_j;
            result.ledger.removed_bond_energy_j += round.removed_bond_energy_j;
            round.components_after = labelComponents();
            result.rounds.push_back(std::move(round));
            if (result.first_failure_time_s < 0.0) result.first_failure_time_s = time;
            result.last_failure_time_s = time;
            captureFrame(time, positions_t, state.ball);
            last_frame_time = time;
        }
        if (result.interval_budget_exhausted) break;
        if (time - last_frame_time >= settings.frame_interval_s - 1e-15) {
            captureFrame(time, positions_t, state.ball);
            last_frame_time = time;
        }
    }
    if (result.frames.back().time_s < time) captureFrame(time, positions_t, state.ball);

    // ---- publish the end state ---------------------------------------------
    applyPositions(matter, positions_t);
    basis.displacement(state.qdot, field);
    for (auto &node : matter.nodes) node.velocity_m_s = {};
    for (std::size_t f = 0; f < basis.freeNodes().size(); ++f)
        matter.nodes[basis.freeNodes()[f]].velocity_m_s = {field[3 * f], field[3 * f + 1], field[3 * f + 2]};
    ball.motion = state.ball;
    result.simulated_s = time;
    result.broken_bonds = countBrokenBonds(matter);
    result.rigid_modes_end = basis.rigidModeCount();
    result.ledger.energy_end_j = modalEnergy(basis, force, state) + ballEnergy(ball, state.ball, gravity);
    result.ledger.residual_j = result.ledger.energy_end_j - result.ledger.energy_start_j +
        result.ledger.removed_linear_energy_j + result.ledger.contact_loss_j;
    result.ledger.elastic_energy_end_modal_j = modalElasticEnergy(basis, state.q);
    result.ledger.elastic_energy_end_lattice_j = measureMaterialMechanics(matter).elastic_energy_j;
    result.timings.total_s = since(total_start);
    return result;
}

} // namespace banjo::modal
