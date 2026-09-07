// banjo_modal_fracture_record: a uniform-cube tile, clamped around its edge,
// struck by an iron ball. The fracture window runs on the precomputed-basis
// lane (--lane modal) or on the implicit Newton/GMRES reference with the same
// shared criterion (--lane implicit). Pieces are the connected components
// left behind; they are handed to Jolt to fall and settle, and the whole
// interaction is written as a banjo.playback.v1 recording the playground's
// 3D tab plays. Every stage is timed and reported against simulated time.

#include "fracture/BondFailure.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentMassProperties.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"
#include "modal/ModalFracture.hpp"
#include "physics/FractureStep.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "rigid/JoltWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <sstream>
#include <tuple>
#include <numbers>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Json = nlohmann::json;
using namespace banjo;
using Clock = std::chrono::steady_clock;

double since(Clock::time_point start) { return std::chrono::duration<double>(Clock::now() - start).count(); }

void require(bool condition, const std::string &message) {
    if (!condition) throw std::runtime_error(message);
}

struct Options {
    std::string lane{"modal"};
    MaterialPreset preset{MaterialPreset::Glass};
    unsigned nx{8}, ny{2}, nz{8};
    double cell_m{0.02};
    double ball_radius_m{0.02};
    double speed_m_s{4.0};
    double gap_m{1.0e-3};
    double height_m{0.3};
    double window_s{2.0e-3};
    double sample_dt_s{1.0e-6};
    double reference_dt_s{1.0e-6};
    unsigned reference_trials{64};
    double clamp_mass_ratio{1.0e9};
    double window_gravity{0.0};
    double frame_interval_s{1.0e-4};
    double max_duration_s{3.0};
    double rigid_dt_s{1.0 / 240.0};
    double rigid_frame_dt_s{1.0 / 60.0};
    double rest_window_s{0.25};
    double rest_speed_m_s{1.0e-3};
    unsigned bond_frames{40};
    bool settle{true};
    bool check_basis{false};
    modal::BasisMode basis_mode{modal::BasisMode::Update};
    unsigned rebuild_at{6};
    double modes_fraction{1.0};
    bool contact_midpoint{true};
    std::string output;
    std::string dump_state;
};

Options parse(int argc, char **argv) {
    Options o;
    for (int i = 1; i < argc; ++i) {
        const std::string option = argv[i];
        require(i + 1 < argc, "option " + option + " needs a value");
        const std::string value = argv[++i];
        const auto number = [&]() {
            std::size_t used = 0;
            const double parsed = std::stod(value, &used);
            require(used == value.size() && std::isfinite(parsed), "invalid number for " + option);
            return parsed;
        };
        if (option == "--lane") { require(value == "modal" || value == "implicit", "lane must be modal or implicit"); o.lane = value; }
        else if (option == "--material") {
            if (value == "glass") o.preset = MaterialPreset::Glass;
            else if (value == "oak" || value == "wood") o.preset = MaterialPreset::Oak;
            else if (value == "iron") o.preset = MaterialPreset::Iron;
            else throw std::runtime_error("material must be glass, oak or iron");
        } else if (option == "--cells") {
            unsigned a = 0, b = 0, c = 0;
            char x1 = 0, x2 = 0;
            std::istringstream stream(value);
            stream >> a >> x1 >> b >> x2 >> c;
            // width x depth x thickness: "8x8x2" is 8 cells wide, 8 deep, 2 thick.
            require(bool(stream) && x1 == 'x' && x2 == 'x' && a >= 3 && b >= 3 && c >= 1,
                    "cells must be WIDTHxDEPTHxTHICKNESS with width and depth >= 3");
            o.nx = a; o.nz = b; o.ny = c;
        } else if (option == "--cell-size") o.cell_m = number();
        else if (option == "--ball-radius") o.ball_radius_m = number();
        else if (option == "--speed") o.speed_m_s = number();
        else if (option == "--gap") o.gap_m = number();
        else if (option == "--height") o.height_m = number();
        else if (option == "--window") o.window_s = number();
        else if (option == "--sample-dt") o.sample_dt_s = number();
        else if (option == "--reference-dt") o.reference_dt_s = number();
        else if (option == "--reference-trials") o.reference_trials = static_cast<unsigned>(number());
        else if (option == "--clamp-mass-ratio") o.clamp_mass_ratio = number();
        else if (option == "--window-gravity") o.window_gravity = number();
        else if (option == "--frame-interval") o.frame_interval_s = number();
        else if (option == "--max-duration") o.max_duration_s = number();
        else if (option == "--rigid-dt") o.rigid_dt_s = number();
        else if (option == "--rigid-frame-dt") o.rigid_frame_dt_s = number();
        else if (option == "--rest-window") o.rest_window_s = number();
        else if (option == "--rest-speed") o.rest_speed_m_s = number();
        else if (option == "--bond-frames") o.bond_frames = static_cast<unsigned>(number());
        else if (option == "--settle") o.settle = number() != 0.0;
        else if (option == "--check-basis") o.check_basis = number() != 0.0;
        else if (option == "--basis-mode") {
            require(value == "update" || value == "recompute" || value == "auto", "basis mode must be update, recompute or auto");
            o.basis_mode = value == "update" ? modal::BasisMode::Update
                : value == "recompute" ? modal::BasisMode::Recompute : modal::BasisMode::Auto;
        } else if (option == "--rebuild-at") o.rebuild_at = static_cast<unsigned>(number());
        else if (option == "--modes-fraction") { o.modes_fraction = number(); require(o.modes_fraction > 0 && o.modes_fraction <= 1, "modes fraction in (0,1]"); }
        else if (option == "--contact-midpoint") o.contact_midpoint = number() != 0.0;
        else if (option == "--dump-state") o.dump_state = value;
        else if (option == "--output") o.output = value;
        else throw std::runtime_error("unknown option " + option);
    }
    require(o.cell_m > 0 && o.ball_radius_m > 0 && o.speed_m_s >= 0 && o.window_s > 0 && o.sample_dt_s > 0 &&
            o.reference_dt_s > 0 && o.max_duration_s >= 0 && o.rigid_dt_s > 0, "scene values must be positive");
    // The engine's collision proxies assume cubic cells; this tool only makes them.
    return o;
}

struct Scene {
    LatticeAsset asset;
    ActiveMatter matter;
    std::vector<std::uint32_t> free_nodes;
    std::vector<char> fixed;
    CompiledBrittleMaterial compiled;
    MaterialDefinition tile_material;
    MaterialDefinition iron;
    modal::ModalBall ball;
    Vec3 offset;
    double top_node_y{};
};

Scene buildScene(const Options &o, bool heavy_clamps) {
    Scene s;
    s.tile_material = makeReferenceMaterial(o.preset, 17);
    s.iron = makeReferenceMaterial(MaterialPreset::Iron, 17);
    s.compiled = withStrengthDerivedFailure(
        compileElasticLatticeReference(s.tile_material, o.cell_m, 2), s.tile_material);
    s.asset = generateBoxLattice({o.nx, o.ny, o.nz, o.cell_m, 2}, s.compiled);
    s.matter.asset = &s.asset;
    s.matter.material = s.compiled;
    s.matter.bonds.resize(s.asset.bonds.size());
    s.offset = {0.0, o.height_m, 0.0};
    s.fixed.assign(s.asset.nodes.size(), 0);
    s.top_node_y = -1e300;
    for (std::uint32_t i = 0; i < s.asset.nodes.size(); ++i) {
        const auto &node = s.asset.nodes[i];
        const bool fixed = node.grid.x == 0 || node.grid.z == 0 ||
            node.grid.x + 1 == static_cast<int>(o.nx) || node.grid.z + 1 == static_cast<int>(o.nz);
        s.fixed[i] = fixed ? 1 : 0;
        double mass = node.represented_volume_m3 * s.compiled.density_kg_m3;
        if (fixed && heavy_clamps) mass *= o.clamp_mass_ratio;
        const Vec3 position = node.local_position_m + s.offset;
        s.matter.nodes.push_back({position, position, {}, mass, {}});
        s.matter.reference_positions_world_m.push_back(position);
        if (!fixed) s.free_nodes.push_back(i);
        s.top_node_y = std::max(s.top_node_y, position.y);
    }
    require(!s.free_nodes.empty(), "the clamped ring leaves no free cells; use at least 3 cells across");
    s.ball.radius_m = o.ball_radius_m;
    s.ball.contact_radius_m = o.ball_radius_m + 0.5 * o.cell_m;
    s.ball.mass_kg = s.iron.density_kg_m3 * 4.0 / 3.0 * std::numbers::pi * std::pow(o.ball_radius_m, 3);
    s.ball.inertia_kg_m2 = 0.4 * s.ball.mass_kg * o.ball_radius_m * o.ball_radius_m;
    // On the tile's axis, with the nearest free node exactly gap_m outside the
    // contact radius. An even cell count has no node on the axis, so the first
    // contact is off-axis and this is the honest approach distance.
    {
        const double reach = s.ball.contact_radius_m + o.gap_m;
        double y = -1e300;
        for (const std::uint32_t node : s.free_nodes) {
            const Vec3 p = s.matter.reference_positions_world_m[node];
            const double radial2 = p.x * p.x + p.z * p.z;
            if (radial2 < reach * reach) y = std::max(y, p.y + std::sqrt(reach * reach - radial2));
        }
        require(y > -1e299, "no free node lies under the ball");
        s.ball.motion.center_of_mass_world_m = {0.0, y, 0.0};
    }
    s.ball.motion.linear_velocity_m_s = {0.0, -o.speed_m_s, 0.0};
    return s;
}

// One recorded state of the fracture window, for either lane.
struct WindowFrame {
    double time_s{};
    std::vector<Vec3> positions;
    std::vector<std::uint32_t> component;
    RigidSnapshot ball{};
    std::vector<std::uint8_t> bond_alive;
    std::vector<float> bond_damage;
};

struct Round {
    double time_s{};
    std::vector<std::uint32_t> bonds;
    std::size_t tensile{}, compressive{}, shear{};
    double removed_energy_j{};
    std::size_t components_after{};
    double update_wall_s{};
    double basis_residual{}, basis_orthogonality{}, basis_value_error{};
    std::size_t retained_modes{};
    bool rebuilt{};
    double trigger_over_threshold{};
    unsigned fewest_live_neighbours{};
};

struct WindowOutcome {
    std::vector<WindowFrame> frames;
    std::vector<Round> rounds;
    Json detail;
    double simulated_s{};
    double wall_s{};
    double basis_wall_s{};
    bool stopped_early{};
    std::string stop_reason;
};

void labelComponents(const ActiveMatter &matter, std::vector<std::uint32_t> &component) {
    component.assign(matter.nodes.size(), 0U);
    for (const auto &c : findConnectedComponents(matter))
        for (const auto node : c.node_indices) component[node] = c.id;
}

WindowOutcome runModalWindow(Scene &scene, const Options &o) {
    modal::ModalFractureSettings settings;
    settings.sample_dt_s = o.sample_dt_s;
    settings.window_s = o.window_s;
    settings.gravity_m_s2 = {0.0, -o.window_gravity, 0.0};
    settings.basis_mode = o.basis_mode;
    settings.rebuild_at_bonds_per_round = o.rebuild_at;
    settings.retained_mode_fraction = o.modes_fraction;
    settings.check_basis = o.check_basis;
    settings.contact_impulse_at_midpoint = o.contact_midpoint;
    settings.frame_interval_s = o.frame_interval_s;
    settings.start_from_static_sag = false;
    const auto start = Clock::now();
    auto result = modal::runModalImpact(scene.matter, scene.free_nodes, scene.ball, settings);
    WindowOutcome out;
    out.wall_s = since(start);
    out.basis_wall_s = result.timings.basis_assemble_s + result.timings.basis_decompose_s;
    out.simulated_s = result.simulated_s;
    out.stopped_early = result.interval_budget_exhausted;
    if (out.stopped_early) out.stop_reason = "interval trial budget exhausted";
    for (auto &frame : result.frames)
        out.frames.push_back({frame.time_s, std::move(frame.node_positions_m), std::move(frame.component_of_node),
                              frame.ball, std::move(frame.bond_alive), std::move(frame.bond_damage)});
    for (const auto &round : result.rounds) {
        Round r;
        r.time_s = round.time_s;
        r.bonds = round.bonds;
        for (const auto mode : round.modes) {
            if (mode == BondFailureMode::Tension) ++r.tensile;
            else if (mode == BondFailureMode::Compression) ++r.compressive;
            else if (mode == BondFailureMode::Shear) ++r.shear;
        }
        r.removed_energy_j = round.removed_bond_energy_j;
        r.components_after = round.components_after;
        r.update_wall_s = round.update_wall_s;
        r.basis_residual = round.basis_residual;
        r.basis_orthogonality = round.basis_orthogonality;
        r.basis_value_error = round.basis_value_error;
        r.retained_modes = round.retained_modes_total;
        r.rebuilt = round.rebuilt;
        r.trigger_over_threshold = round.trigger_over_threshold;
        r.fewest_live_neighbours = round.fewest_live_neighbours;
        out.rounds.push_back(std::move(r));
    }
    const auto &t = result.timings;
    out.detail = {
        {"lane", "modal"},
        {"basis_mode", o.basis_mode == modal::BasisMode::Update ? "rank-one-update" : o.basis_mode == modal::BasisMode::Recompute ? "recompute" : "auto"},
        {"contact_impulse", o.contact_midpoint ? "midpoint" : "start"},
        {"modes_fraction", o.modes_fraction},
        {"modes", result.modes},
        {"rigid_modes_end", result.rigid_modes_end},
        {"fastest_period_s", result.fastest_period_s},
        {"sample_dt_s", o.sample_dt_s},
        {"samples", result.samples},
        {"trials", result.trials},
        {"discarded_trials", result.discarded_trials},
        {"contact_samples", result.contact_samples},
        {"peak_contact_nodes", result.peak_contact_nodes},
        {"penetration_violations", result.penetration_violations},
        {"maximum_end_penetration_m", result.maximum_end_penetration_m},
        {"peak_node_speed_m_s", result.peak_node_speed_m_s},
        {"contact_passes_exhausted", result.contact_passes_exhausted},
        {"largest_impulse", {{"n_s", result.largest_impulse_n_s}, {"w", result.largest_impulse_response_w},
                             {"distance_m", result.largest_impulse_distance_m}, {"time_s", result.largest_impulse_time_s},
                             {"node", result.largest_impulse_node}, {"pass", result.largest_impulse_pass},
                             {"sweep", result.largest_impulse_sweep}, {"node_response", result.largest_impulse_node_response},
                             {"omega2_max", result.largest_impulse_omega2_max}, {"omega2_min", result.largest_impulse_omega2_min},
                             {"weight_min", result.largest_impulse_weight_min}, {"diag_trace", result.largest_impulse_diag_trace}}},
        {"negative_response_events", result.negative_response_events},
        {"most_negative_response", result.most_negative_response},
        {"maximum_sweeps_used", result.maximum_sweeps_used},
        {"sweep_budget_exhausted", result.sweep_budget_exhausted},
        {"maximum_tensile_stretch", result.maximum_tensile_stretch},
        {"maximum_compressive_strain", result.maximum_compressive_strain},
        {"maximum_shear_strain", result.maximum_shear_strain},
        {"ball_end_velocity_m_s", {scene.ball.motion.linear_velocity_m_s.x, scene.ball.motion.linear_velocity_m_s.y, scene.ball.motion.linear_velocity_m_s.z}},
        {"first_failure_time_s", result.first_failure_time_s},
        {"last_failure_time_s", result.last_failure_time_s},
        {"ball_separation_time_s", result.ball_separation_time_s},
        {"interval_budget_exhausted", result.interval_budget_exhausted},
        {"ledger", {{"energy_start_j", result.ledger.energy_start_j}, {"energy_end_j", result.ledger.energy_end_j},
                    {"removed_linear_energy_j", result.ledger.removed_linear_energy_j},
                    {"removed_bond_energy_j", result.ledger.removed_bond_energy_j},
                    {"contact_loss_j", result.ledger.contact_loss_j}, {"residual_j", result.ledger.residual_j},
                    {"elastic_energy_end_modal_j", result.ledger.elastic_energy_end_modal_j},
                    {"elastic_energy_end_lattice_j", result.ledger.elastic_energy_end_lattice_j}}},
        {"timings_s", {{"basis_assemble", t.basis_assemble_s}, {"basis_decompose", t.basis_decompose_s},
                       {"evolve", t.evolve_s}, {"field", t.field_s}, {"contact", t.contact_s},
                       {"criterion", t.criterion_s}, {"basis_update", t.update_s}, {"components", t.components_s},
                       {"frames", t.frames_s}, {"total", t.total_s}}},
    };
    return out;
}

WindowOutcome runImplicitWindow(Scene &scene, const Options &o) {
    CoupledSphereState sphere{scene.ball.motion, scene.ball.contact_radius_m, scene.ball.mass_kg, scene.ball.inertia_kg_m2};
    FractureStepSettings settings;
    settings.timing = BondFailureTiming::StepRestart;
    settings.maximum_solver_trials = o.reference_trials;
    const Vec3 gravity{0.0, -o.window_gravity, 0.0};
    WindowOutcome out;
    std::vector<std::uint32_t> component;
    labelComponents(scene.matter, component);
    const auto capture = [&](double time) {
        WindowFrame frame;
        frame.time_s = time;
        for (const auto &node : scene.matter.nodes) frame.positions.push_back(node.position_world_m);
        frame.component = component;
        frame.ball = sphere.motion;
        for (const auto &bond : scene.matter.bonds) {
            frame.bond_alive.push_back(bond.alive ? 1U : 0U);
            frame.bond_damage.push_back(static_cast<float>(bond.damage));
        }
        out.frames.push_back(std::move(frame));
    };
    capture(0.0);
    double time = 0.0, last_frame = 0.0, removed_energy = 0.0, energy_residual = 0.0, contact_loss = 0.0;
    unsigned steps = 0, trials = 0, discarded = 0, newton = 0, krylov = 0;
    double max_tensile = 0.0, max_shear = 0.0, max_compressive = 0.0;
    std::vector<char> alive_before(scene.matter.bonds.size(), 1);
    const auto start = Clock::now();
    const auto mechanics_start = measureMaterialMechanics(scene.matter, gravity);
    while (time < o.window_s - 1e-15 * o.window_s) {
        const double dt = std::min(o.reference_dt_s, o.window_s - time);
        for (std::size_t b = 0; b < alive_before.size(); ++b) alive_before[b] = scene.matter.bonds[b].alive ? 1 : 0;
        const auto result = tryFracturingStep(scene.matter, dt, gravity, &sphere, settings);
        ++steps;
        trials += result.solver_trials;
        discarded += result.discarded_trials;
        if (!result.converged) {
            out.stopped_early = true;
            const auto &last = result.last_trial;
            char detail[512];
            std::snprintf(detail, sizeof detail,
                " (step %u, trial newton %u krylov %u, velocity residual %.3e m/s, energy residual %.3e J, "
                "|P residual| %.3e, |L residual| %.3e, penetration %.3e m, contact loss %.3e J, audited %d)",
                steps, last.iterations, last.linear_iterations, last.constitutive_velocity_residual_m_s,
                last.energy_residual_j, length(last.linear_momentum_residual_kg_m_s),
                length(last.angular_momentum_residual_kg_m2_s), last.maximum_penetration_m,
                last.normal_contact_loss_j, int(last.balance_measured));
            out.stop_reason = (result.failure == FractureStepFailure::SolverRejected
                ? std::string("implicit solver rejected the step") : std::string("implicit trial budget exhausted")) + detail;
            break;
        }
        newton += result.newton_iterations;
        krylov += result.linear_iterations;
        max_tensile = std::max(max_tensile, result.maximum_tensile_stretch);
        max_shear = std::max(max_shear, result.maximum_shear_strain);
        max_compressive = std::max(max_compressive, result.maximum_compressive_strain);
        removed_energy += result.removed_bond_energy_j;
        energy_residual += result.energy_residual_j;
        contact_loss += result.normal_contact_loss_j;
        if (result.broken_bonds > 0) {
            Round r;
            r.time_s = time;
            {
                std::vector<unsigned> live(scene.matter.nodes.size(), 0U);
                for (std::size_t b = 0; b < alive_before.size(); ++b)
                    if (alive_before[b]) { ++live[scene.asset.bonds[b].node_a]; ++live[scene.asset.bonds[b].node_b]; }
                r.fewest_live_neighbours = std::numeric_limits<unsigned>::max();
                for (std::size_t b = 0; b < alive_before.size(); ++b)
                    if (alive_before[b] && !scene.matter.bonds[b].alive)
                        r.fewest_live_neighbours = std::min({r.fewest_live_neighbours, live[scene.asset.bonds[b].node_a], live[scene.asset.bonds[b].node_b]});
                r.trigger_over_threshold = std::max({result.maximum_tensile_stretch / scene.compiled.damage_end_stretch,
                    result.maximum_shear_strain / scene.compiled.shear_damage_end_strain,
                    result.maximum_compressive_strain / scene.compiled.compression_damage_end_strain});
            }
            for (std::size_t b = 0; b < alive_before.size(); ++b)
                if (alive_before[b] && !scene.matter.bonds[b].alive) {
                    r.bonds.push_back(static_cast<std::uint32_t>(b));
                    const auto mode = scene.matter.bonds[b].failure_mode;
                    if (mode == BondFailureMode::Tension) ++r.tensile;
                    else if (mode == BondFailureMode::Compression) ++r.compressive;
                    else if (mode == BondFailureMode::Shear) ++r.shear;
                }
            r.removed_energy_j = result.removed_bond_energy_j;
            labelComponents(scene.matter, component);
            r.components_after = findConnectedComponents(scene.matter).size();
            out.rounds.push_back(std::move(r));
            capture(time + dt);
            last_frame = time + dt;
        }
        time += dt;
        if (time - last_frame >= o.frame_interval_s - 1e-15) { capture(time); last_frame = time; }
    }
    out.wall_s = since(start);
    if (out.frames.back().time_s < time) capture(time);
    out.simulated_s = time;
    scene.ball.motion = sphere.motion;
    const auto mechanics_end = measureMaterialMechanics(scene.matter, gravity);
    out.detail = {
        {"lane", "implicit"},
        {"reference_dt_s", o.reference_dt_s},
        {"steps", steps},
        {"solver_trials", trials},
        {"discarded_trials", discarded},
        {"newton_iterations", newton},
        {"krylov_iterations", krylov},
        {"clamp_mass_ratio", o.clamp_mass_ratio},
        {"maximum_tensile_stretch", max_tensile},
        {"maximum_shear_strain", max_shear},
        {"maximum_compressive_strain", max_compressive},
        {"ball_end_velocity_m_s", {sphere.motion.linear_velocity_m_s.x, sphere.motion.linear_velocity_m_s.y, sphere.motion.linear_velocity_m_s.z}},
        {"ledger", {{"removed_bond_energy_j", removed_energy}, {"energy_residual_sum_j", energy_residual},
                    {"normal_contact_loss_j", contact_loss},
                    {"lattice_mechanical_energy_start_j", mechanics_start.mechanicalEnergy()},
                    {"lattice_mechanical_energy_end_j", mechanics_end.mechanicalEnergy()}}},
    };
    return out;
}

// ---- handoff: components become rigid bodies ------------------------------

struct CellBox {
    Vec3 center_rest_local;
    Vec3 dimensions;
};

// Merge cells into boxes: runs along x, then runs of identical x-extent along z.
std::vector<CellBox> mergeCells(const LatticeAsset &asset, const std::vector<std::uint32_t> &nodes, double h) {
    struct Run { int y, z, x0, x1; };
    std::map<std::pair<int, int>, std::vector<int>> rows;
    for (const auto node : nodes) {
        const auto &g = asset.nodes[node].grid;
        rows[{g.y, g.z}].push_back(g.x);
    }
    std::vector<Run> runs;
    for (auto &[key, xs] : rows) {
        std::sort(xs.begin(), xs.end());
        int x0 = xs.front(), x1 = xs.front();
        for (std::size_t i = 1; i <= xs.size(); ++i) {
            if (i < xs.size() && xs[i] == x1 + 1) { x1 = xs[i]; continue; }
            runs.push_back({key.first, key.second, x0, x1});
            if (i < xs.size()) { x0 = xs[i]; x1 = xs[i]; }
        }
    }
    // Merge consecutive-z runs with the same (y, x0, x1).
    std::sort(runs.begin(), runs.end(), [](const Run &a, const Run &b) {
        return std::tie(a.y, a.x0, a.x1, a.z) < std::tie(b.y, b.x0, b.x1, b.z);
    });
    struct Slab { int y, x0, x1, z0, z1; };
    std::vector<Slab> slabs;
    for (const auto &run : runs) {
        if (!slabs.empty()) {
            auto &s = slabs.back();
            if (s.y == run.y && s.x0 == run.x0 && s.x1 == run.x1 && s.z1 + 1 == run.z) { s.z1 = run.z; continue; }
        }
        slabs.push_back({run.y, run.x0, run.x1, run.z, run.z});
    }
    // Grid (x,y,z) -> local centre: the box lattice centres cell (x,y,z) at ((x+.5)h - X/2, ...).
    const auto local = [&](double x, double y, double z) {
        const auto &first = asset.nodes.front();
        const Vec3 origin = first.local_position_m - Vec3{(first.grid.x + 0.5) * h, (first.grid.y + 0.5) * h, (first.grid.z + 0.5) * h};
        return origin + Vec3{(x + 0.5) * h, (y + 0.5) * h, (z + 0.5) * h};
    };
    std::vector<CellBox> boxes;
    for (const auto &s : slabs)
        boxes.push_back({local(0.5 * (s.x0 + s.x1), s.y, 0.5 * (s.z0 + s.z1)),
                         {(s.x1 - s.x0 + 1) * h, h, (s.z1 - s.z0 + 1) * h}});
    return boxes;
}

struct HandoffBody {
    MatterBodyId id{};
    bool dynamic{};
    std::uint32_t component{};
    std::vector<std::uint32_t> nodes;
    Vec3 rest_center; // rest-geometry centre of mass in world (rest) coordinates
    double mass_kg{};
};

struct Handoff {
    std::vector<HandoffBody> bodies;
    std::vector<std::uint32_t> component_of_node;
    std::size_t fragments{}, static_components{}, fragment_cells{}, static_cells{}, parts{};
    double coarsening_loss_j{};
    double fragment_mass_kg{};
    double fragment_kinetic_j{};
    double largest_fragment_mass_kg{};
};

Handoff handToJolt(JoltWorld &rigid, const Scene &scene, const Options &o) {
    Handoff h;
    const auto components = findConnectedComponents(scene.matter);
    h.component_of_node.assign(scene.matter.nodes.size(), 0U);
    for (const auto &c : components) for (const auto node : c.node_indices) h.component_of_node[node] = c.id;
    MatterBodyId next_dynamic = 1000, next_static = 100000;
    for (const auto &c : components) {
        bool has_fixed = false;
        for (const auto node : c.node_indices) has_fixed = has_fixed || scene.fixed[node];
        const auto boxes = mergeCells(scene.asset, c.node_indices, o.cell_m);
        h.parts += boxes.size();
        Vec3 rest_center{};
        for (const auto node : c.node_indices) rest_center += scene.matter.reference_positions_world_m[node];
        rest_center = rest_center / static_cast<double>(c.node_indices.size());
        HandoffBody body;
        body.component = c.id;
        body.nodes = c.node_indices;
        body.rest_center = rest_center;
        if (has_fixed) {
            ++h.static_components;
            h.static_cells += c.node_indices.size();
            body.dynamic = false;
            body.id = next_static;
            for (const auto &box : boxes) {
                RigidBoxDescription description;
                description.body_id = next_static++;
                description.dimensions_m = box.dimensions;
                description.material = scene.tile_material;
                description.state.center_of_mass_world_m = box.center_rest_local + scene.offset;
                description.fixed = true;
                rigid.addBox(description);
            }
        } else {
            ++h.fragments;
            h.fragment_cells += c.node_indices.size();
            const auto properties = calculateFragmentMassProperties(scene.matter, c.node_indices);
            h.coarsening_loss_j += properties.coarsening_kinetic_loss_j;
            h.fragment_mass_kg += properties.mass_kg;
            h.fragment_kinetic_j += properties.rigid_kinetic_energy_j;
            h.largest_fragment_mass_kg = std::max(h.largest_fragment_mass_kg, properties.mass_kg);
            require(boxes.size() <= 64, "a fragment of " + std::to_string(c.node_indices.size()) +
                    " cells needs " + std::to_string(boxes.size()) + " boxes; Jolt compounds take 64");
            RigidCompoundDescription description;
            description.body_id = next_dynamic++;
            description.material = scene.tile_material;
            for (const auto &box : boxes) {
                RigidPrimitive geometry;
                geometry.kind = PrimitiveKind::Box;
                geometry.dimensions_m = box.dimensions;
                description.parts.push_back({geometry, box.center_rest_local + scene.offset - rest_center});
            }
            description.state.center_of_mass_world_m = properties.center_of_mass_world_m;
            description.state.linear_velocity_m_s = properties.linear_velocity_m_s;
            description.state.angular_velocity_rad_s = properties.angular_velocity_rad_s;
            description.mass_kg = properties.mass_kg;
            description.inertia_local_kg_m2 = properties.inertia_world_kg_m2;
            rigid.addCompound(description);
            body.dynamic = true;
            body.id = description.body_id;
            body.mass_kg = properties.mass_kg;
        }
        h.bodies.push_back(std::move(body));
    }
    return h;
}

// ---- recording --------------------------------------------------------------

Json vec(const Vec3 &v) { return {v.x, v.y, v.z}; }
Json quat(const Quat &q) { return {q.w, q.x, q.y, q.z}; }

std::uint32_t tileColor(MaterialPreset preset) {
    switch (preset) {
    case MaterialPreset::Glass: return 0x9fd8ffff;
    case MaterialPreset::Oak: return 0xc8a165ff;
    case MaterialPreset::Iron: return 0xa7a9b0ff;
    default: return 0xccccccff;
    }
}

} // namespace

int main(int argc, char **argv) {
    try {
        const Options o = parse(argc, argv);
        const auto wall_start = Clock::now();

        // ---- scene ------------------------------------------------------------
        const auto scene_start = Clock::now();
        Scene scene = buildScene(o, o.lane == "implicit");
        const double scene_wall = since(scene_start);
        const auto limit = measureLatticeResolutionLimit(scene.asset, scene.compiled);

        // ---- fracture window --------------------------------------------------
        WindowOutcome window = o.lane == "modal" ? runModalWindow(scene, o) : runImplicitWindow(scene, o);

        if (!o.dump_state.empty()) {
            Json nodes = Json::array();
            for (std::uint32_t i = 0; i < scene.matter.nodes.size(); ++i) {
                const auto &node = scene.matter.nodes[i];
                nodes.push_back({{"position_m", vec(node.position_world_m)}, {"velocity_m_s", vec(node.velocity_m_s)},
                                 {"fixed", scene.fixed[i] != 0}});
            }
            std::vector<std::uint32_t> dead;
            for (std::uint32_t b = 0; b < scene.matter.bonds.size(); ++b) if (!scene.matter.bonds[b].alive) dead.push_back(b);
            Json dump{{"lane", o.lane}, {"time_s", window.simulated_s}, {"nodes", nodes}, {"broken_bonds", dead},
                      {"ball", {{"position_m", vec(scene.ball.motion.center_of_mass_world_m)},
                                {"velocity_m_s", vec(scene.ball.motion.linear_velocity_m_s)}}}};
            std::ofstream out(o.dump_state, std::ios::binary);
            const std::string text = dump.dump();
            out.write(text.data(), static_cast<std::streamsize>(text.size()));
        }

        // ---- pieces fall and settle ------------------------------------------
        std::vector<WindowFrame> settle_frames;
        Json settle_report;
        double settle_wall = 0.0, settle_simulated = 0.0, handoff_wall = 0.0;
        Handoff handoff;
        {
            const auto handoff_start = Clock::now();
            JoltWorld rigid(0);
            rigid.addFloor();
            RigidBallDescription ball;
            ball.body_id = 2;
            ball.radius_m = scene.ball.radius_m;
            ball.material = scene.iron;
            ball.position_world_m = scene.ball.motion.center_of_mass_world_m;
            ball.linear_velocity_m_s = scene.ball.motion.linear_velocity_m_s;
            ball.angular_velocity_rad_s = scene.ball.motion.angular_velocity_rad_s;
            rigid.addBall(ball);
            handoff = handToJolt(rigid, scene, o);
            handoff_wall = since(handoff_start);

            const auto settle_start = Clock::now();
            std::vector<MatterBodyId> dynamic_ids{2};
            for (const auto &body : handoff.bodies) if (body.dynamic) dynamic_ids.push_back(body.id);
            const auto capture = [&](double time) {
                WindowFrame frame;
                frame.time_s = window.simulated_s + time;
                frame.positions.resize(scene.matter.nodes.size());
                frame.component = handoff.component_of_node;
                for (const auto &body : handoff.bodies) {
                    if (!body.dynamic) {
                        for (const auto node : body.nodes)
                            frame.positions[node] = scene.matter.reference_positions_world_m[node];
                        continue;
                    }
                    const auto snap = rigid.snapshot(body.id);
                    for (const auto node : body.nodes)
                        frame.positions[node] = snap.center_of_mass_world_m +
                            snap.orientation_world.rotate(scene.matter.reference_positions_world_m[node] - body.rest_center);
                }
                frame.ball = rigid.snapshot(2);
                settle_frames.push_back(std::move(frame));
            };
            double time = 0.0, at_rest_for = 0.0, last_frame = -1.0, settled_at = -1.0, peak_speed = 0.0;
            unsigned steps = 0;
            if (o.settle) {
                capture(0.0);
                last_frame = 0.0;
                while (time < o.max_duration_s - 1e-12) {
                    rigid.step(o.rigid_dt_s);
                    time += o.rigid_dt_s;
                    ++steps;
                    double speed = 0.0, spin = 0.0;
                    for (const auto id : dynamic_ids) {
                        const auto snap = rigid.snapshot(id);
                        speed = std::max(speed, length(snap.linear_velocity_m_s));
                        spin = std::max(spin, length(snap.angular_velocity_rad_s));
                    }
                    peak_speed = std::max(peak_speed, speed);
                    if (speed < o.rest_speed_m_s && spin < 100.0 * o.rest_speed_m_s) at_rest_for += o.rigid_dt_s;
                    else at_rest_for = 0.0;
                    if (time - last_frame >= o.rigid_frame_dt_s - 1e-12) { capture(time); last_frame = time; }
                    if (at_rest_for >= o.rest_window_s) { settled_at = time - at_rest_for; break; }
                }
                if (last_frame < time) capture(time);
            }
            settle_wall = since(settle_start);
            settle_simulated = time;
            const auto totals = rigid.mechanicalTotals({0.0, -9.81, 0.0});
            settle_report = {
                {"enabled", o.settle},
                {"rigid_dt_s", o.rigid_dt_s},
                {"steps", steps},
                {"simulated_s", time},
                {"settled", settled_at >= 0.0},
                {"settled_time_s", settled_at},
                {"rest_window_s", o.rest_window_s},
                {"rest_speed_m_s", o.rest_speed_m_s},
                {"peak_fragment_speed_m_s", peak_speed},
                {"final_kinetic_energy_j", totals.kinetic_energy_j},
                {"bodies", dynamic_ids.size()},
                {"fragments", handoff.fragments},
                {"static_components", handoff.static_components},
                {"fragment_cells", handoff.fragment_cells},
                {"static_cells", handoff.static_cells},
                {"collision_boxes", handoff.parts},
                {"fragment_mass_kg", handoff.fragment_mass_kg},
                {"largest_fragment_mass_kg", handoff.largest_fragment_mass_kg},
                {"fragment_rigid_kinetic_j", handoff.fragment_kinetic_j},
                {"coarsening_kinetic_loss_j", handoff.coarsening_loss_j},
                {"wall_s", settle_wall},
                {"handoff_wall_s", handoff_wall},
            };
        }
        const double compute_wall = since(wall_start);

        // ---- report ---------------------------------------------------------
        const double simulated = window.simulated_s + settle_simulated;
        const double fracture_wall = window.wall_s;
        std::vector<std::uint32_t> broken;
        for (std::uint32_t b = 0; b < scene.matter.bonds.size(); ++b) if (!scene.matter.bonds[b].alive) broken.push_back(b);
        const auto components = findConnectedComponents(scene.matter);
        Json rounds = Json::array();
        for (const auto &r : window.rounds) {
            Json entry{{"time_s", r.time_s}, {"bonds", r.bonds}, {"tensile", r.tensile}, {"compressive", r.compressive},
                       {"shear", r.shear}, {"removed_energy_j", r.removed_energy_j}, {"components_after", r.components_after}};
            entry["trigger_over_threshold"] = r.trigger_over_threshold;
            entry["fewest_live_neighbours"] = r.fewest_live_neighbours;
            if (o.lane == "modal") {
                entry["update_wall_s"] = r.update_wall_s;
                entry["retained_modes"] = r.retained_modes;
                entry["rebuilt"] = r.rebuilt;
                if (o.check_basis) {
                    entry["basis_residual"] = r.basis_residual;
                    entry["basis_orthogonality"] = r.basis_orthogonality;
                    entry["basis_value_error"] = r.basis_value_error;
                }
            }
            rounds.push_back(std::move(entry));
        }
        double total_mass = 0.0;
        for (const auto &node : scene.matter.nodes) if (!scene.fixed[&node - scene.matter.nodes.data()]) total_mass += node.mass_kg;
        Json report{
            {"lane", o.lane},
            {"status", window.stopped_early ? "solver_limit" : "complete"},
            {"stop_reason", window.stop_reason},
            {"physical_response_validated", false},
            {"scene", {{"material", materialPresetName(o.preset)}, {"cells_width_depth_thickness", {o.nx, o.nz, o.ny}}, {"cell_m", o.cell_m},
                       {"tile_m_width_depth_thickness", {o.nx * o.cell_m, o.nz * o.cell_m, o.ny * o.cell_m}}, {"height_m", o.height_m},
                       {"clamped", "perimeter ring of cells, every layer"},
                       {"ball", {{"material", "iron"}, {"radius_m", o.ball_radius_m}, {"contact_radius_m", scene.ball.contact_radius_m},
                                 {"mass_kg", scene.ball.mass_kg}, {"speed_m_s", o.speed_m_s}, {"gap_m", o.gap_m}}},
                       {"window_gravity_m_s2", o.window_gravity}, {"settle_gravity_m_s2", 9.81}}},
            {"lattice", {{"nodes", scene.matter.nodes.size()}, {"bonds", scene.matter.bonds.size()},
                         {"free_nodes", scene.free_nodes.size()}, {"fixed_nodes", scene.matter.nodes.size() - scene.free_nodes.size()},
                         {"free_dofs", 3 * scene.free_nodes.size()},
                         {"node_mass_kg", scene.compiled.density_kg_m3 * o.cell_m * o.cell_m * o.cell_m},
                         {"explicit_substep_limit_s", limit.explicit_substep_limit_s},
                         {"fastest_mode_period_estimate_s", limit.fastest_mode_period_s},
                         {"tensile_break_strain", scene.compiled.damage_end_stretch},
                         {"shear_break_strain", scene.compiled.shear_damage_end_strain},
                         {"compression_break_strain", scene.compiled.compression_damage_end_strain}}},
            {"window", window.detail},
            {"rounds", rounds},
            {"round_count", window.rounds.size()},
            {"first_failure", window.rounds.empty() ? Json(nullptr) : Json{{"time_s", window.rounds.front().time_s}, {"bonds", window.rounds.front().bonds}}},
            {"broken_bonds", broken.size()},
            {"broken_bond_indices", broken},
            {"failure_modes", {{"tensile", countBondFailureModes(scene.matter).tensile},
                               {"compressive", countBondFailureModes(scene.matter).compressive},
                               {"shear", countBondFailureModes(scene.matter).shear}}},
            {"components", components.size()},
            {"largest_component", components.empty() ? 0 : components.front().node_indices.size()},
            {"fracture_count", window.rounds.size()},
            {"settle", settle_report},
            {"timings_s", {{"scene_build", scene_wall}, {"basis_build", window.basis_wall_s},
                           {"fracture_window", fracture_wall}, {"handoff", handoff_wall}, {"settle", settle_wall},
                           {"compute_total", compute_wall}}},
            {"realtime", {{"simulated_s", simulated}, {"window_simulated_s", window.simulated_s},
                          {"settle_simulated_s", settle_simulated}, {"compute_wall_s", compute_wall},
                          {"ratio", simulated > 0 ? compute_wall / simulated : 0.0},
                          {"ratio_excluding_basis_build", simulated > 0 ? (compute_wall - window.basis_wall_s) / simulated : 0.0},
                          {"fracture_window_ratio", window.simulated_s > 0 ? fracture_wall / window.simulated_s : 0.0},
                          {"rule", "wall <= 1.1 x simulated"}, {"meets_rule", simulated > 0 && compute_wall <= 1.1 * simulated}}},
            {"elapsed_s", simulated},
            {"wall_ms", 1000.0 * compute_wall},
            {"mass_kg", total_mass},
        };

        // ---- playback -------------------------------------------------------
        Json artifact;
        double json_wall = 0.0;
        if (!o.output.empty()) {
            const auto json_start = Clock::now();
            const auto output_path = std::filesystem::absolute(o.output).lexically_normal();
            require(!std::filesystem::exists(output_path), "output path already exists");
            Json bodies = Json::array();
            const std::uint32_t color = tileColor(o.preset);
            for (std::uint32_t i = 0; i < scene.matter.nodes.size(); ++i)
                bodies.push_back({{"id", "1:" + std::to_string(i)}, {"object_id", 1}, {"element_id", i},
                                  {"material_id", std::string(materialPresetName(o.preset))}, {"color_rgba", color},
                                  {"shape", "box"}, {"dimensions_m", {o.cell_m, o.cell_m, o.cell_m}}});
            bodies.push_back({{"id", "2:0"}, {"object_id", 2}, {"element_id", 0}, {"material_id", "iron"},
                              {"color_rgba", 0x6f7380ffU}, {"shape", "sphere"},
                              {"dimensions_m", {2 * o.ball_radius_m, 2 * o.ball_radius_m, 2 * o.ball_radius_m}}});
            const double ground = 1.0;
            Json supports = {{{-ground, 0.0, -ground}, {ground, 0.0, -ground}, {ground, 0.0, ground}},
                             {{-ground, 0.0, -ground}, {ground, 0.0, ground}, {-ground, 0.0, ground}}};
            Json frames = Json::array();
            const std::size_t window_frames = window.frames.size();
            const std::size_t bond_stride = std::max<std::size_t>(1, (window_frames + o.bond_frames - 1) / std::max(1U, o.bond_frames));
            const auto emit = [&](const WindowFrame &f, bool with_bonds, std::size_t broken_count) {
                Json poses = Json::array();
                for (std::uint32_t i = 0; i < f.positions.size(); ++i)
                    poses.push_back({{"id", "1:" + std::to_string(i)}, {"position_m", vec(f.positions[i])},
                                     {"orientation_wxyz", {1.0, 0.0, 0.0, 0.0}}, {"component_id", f.component[i]}});
                poses.push_back({{"id", "2:0"}, {"position_m", vec(f.ball.center_of_mass_world_m)},
                                 {"orientation_wxyz", quat(f.ball.orientation_world)}, {"component_id", 0}});
                Json frame{{"time_s", f.time_s}, {"poses", std::move(poses)}, {"fracture_count", broken_count}};
                if (with_bonds) {
                    Json bonds = Json::array();
                    for (std::size_t b = 0; b < scene.asset.bonds.size(); ++b) {
                        const auto &rest = scene.asset.bonds[b];
                        bonds.push_back({{"a_m", vec(f.positions[rest.node_a])}, {"b_m", vec(f.positions[rest.node_b])},
                                         {"live", f.bond_alive[b] != 0}, {"damage", std::min(1.0, std::max(0.0, double(f.bond_damage[b])))}});
                    }
                    frame["bonds"] = std::move(bonds);
                }
                frames.push_back(std::move(frame));
            };
            for (std::size_t i = 0; i < window_frames; ++i) {
                const auto &f = window.frames[i];
                std::size_t broken_count = 0;
                for (const auto alive : f.bond_alive) broken_count += alive ? 0 : 1;
                emit(f, i % bond_stride == 0 || i + 1 == window_frames, broken_count);
            }
            for (std::size_t i = 0; i < settle_frames.size(); ++i) {
                WindowFrame f = settle_frames[i];
                // Rigid poses: give every cell its body's orientation.
                Json poses = Json::array();
                std::vector<Quat> orientation(f.positions.size());
                (void)orientation;
                for (std::uint32_t node = 0; node < f.positions.size(); ++node)
                    poses.push_back({{"id", "1:" + std::to_string(node)}, {"position_m", vec(f.positions[node])},
                                     {"orientation_wxyz", {1.0, 0.0, 0.0, 0.0}}, {"component_id", f.component[node]}});
                poses.push_back({{"id", "2:0"}, {"position_m", vec(f.ball.center_of_mass_world_m)},
                                 {"orientation_wxyz", quat(f.ball.orientation_world)}, {"component_id", 0}});
                frames.push_back({{"time_s", f.time_s}, {"poses", std::move(poses)}, {"fracture_count", broken.size()}});
            }
            artifact = {{"schema", "banjo.playback.v1"}, {"mode", "network"}, {"units", "SI"},
                        {"bodies", std::move(bodies)}, {"supports", supports}, {"frames", std::move(frames)},
                        {"requested_steps", 0}, {"completed_steps", 0},
                        {"sampling", {{"stride_steps", 1}, {"maximum_frames", 122}, {"interpolation", "none"}}},
                        {"physical_response_validated", false},
                        {"status", report["status"]}, {"error", window.stop_reason}, {"report", report}};
            artifact["requested_steps"] = artifact["frames"].size();
            artifact["completed_steps"] = artifact["frames"].size();
            std::string serialized = artifact.dump();
            constexpr std::size_t kBudget = 64U * 1024U * 1024U;
            if (serialized.size() > kBudget) {
                // Bond lines are the bulk of a dense cascade's recording. Keep
                // them on the first and last window frames only, then thin the
                // cascade frames, before giving up. The report is never cut.
                auto &all = artifact["frames"];
                for (std::size_t i = 1; i + 1 < window_frames && i < all.size(); ++i) all[i].erase("bonds");
                artifact["sampling"]["bond_lines"] = "first and last fracture frames only (byte budget)";
                serialized = artifact.dump();
                if (serialized.size() > kBudget) {
                    Json thinned = Json::array();
                    for (std::size_t i = 0; i < all.size(); ++i)
                        if (i == 0 || i + 1 == all.size() || i >= window_frames || i % 4 == 0) thinned.push_back(all[i]);
                    artifact["frames"] = std::move(thinned);
                    artifact["sampling"]["fracture_frames"] = "every fourth (byte budget)";
                    serialized = artifact.dump();
                }
                require(serialized.size() <= kBudget, "recording exceeds the 64 MiB playback budget even without bond lines");
            }
            std::ofstream output(output_path, std::ios::binary);
            require(bool(output), "cannot open output");
            output.write(serialized.data(), static_cast<std::streamsize>(serialized.size()));
            json_wall = since(json_start);
        }
        Json summary{{"lane", o.lane}, {"status", report["status"]}, {"material", materialPresetName(o.preset)},
                     {"cells", {o.nx, o.nz, o.ny}}, {"free_dofs", 3 * scene.free_nodes.size()},
                     {"rounds", window.rounds.size()}, {"broken_bonds", broken.size()}, {"components", components.size()},
                     {"largest_component", components.empty() ? 0 : components.front().node_indices.size()},
                     {"first_failure_time_s", window.rounds.empty() ? -1.0 : window.rounds.front().time_s},
                     {"simulated_s", simulated}, {"compute_wall_s", compute_wall}, {"ratio", simulated > 0 ? compute_wall / simulated : 0.0},
                     {"basis_build_s", window.basis_wall_s}, {"fracture_window_wall_s", fracture_wall},
                     {"settle_wall_s", settle_wall}, {"settled", settle_report.value("settled", false)},
                     {"settled_time_s", settle_report.value("settled_time_s", -1.0)}, {"json_wall_s", json_wall},
                     {"window", window.detail},
                     {"output", o.output}, {"stop_reason", window.stop_reason}};
        std::cout << summary.dump() << '\n';
        return window.stopped_early ? 2 : 0;
    } catch (const std::exception &error) {
        std::cout << Json{{"status", "error"}, {"error", error.what()}}.dump() << '\n';
        return 1;
    }
}
