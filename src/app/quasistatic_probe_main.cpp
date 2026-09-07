// Quasi-static fracture probe: a uniform-cube glass tile on a frame, struck by
// an iron ball, computed through to rest and written as a banjo.playback.v1
// recording the playground's 3D tab plays.
//
// Stages, each timed separately:
//   1. the ball falls in Jolt until it reaches the lattice's first contact node;
//   2. the quasi-static lane (fracture/QuasiStaticFracture.hpp) turns the
//      impact into a crack pattern with the shared failure criterion;
//   3. optionally, the dynamic implicit reference (physics/FractureStep.hpp)
//      runs the identical lattice and impact for accuracy comparison;
//   4. the connected components become Jolt rigid pieces and everything
//      settles to rest in Jolt.
// Nothing here precuts pieces, animates a shatter or launches a fragment.

#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "fracture/FragmentMassProperties.hpp"
#include "fracture/PieceGeometry.hpp"
#include "fracture/QuasiStaticFracture.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"
#include "physics/FractureStep.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "rigid/JoltWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace banjo;
using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

double seconds(Clock::time_point start) { return std::chrono::duration<double>(Clock::now() - start).count(); }

struct Options {
    unsigned cells_x{8}, cells_y{2}, cells_z{8};
    double cell_m{0.02};
    MaterialPreset tile{MaterialPreset::Glass};
    double ball_radius_m{0.04};
    double drop_m{0.39};
    double offset_x_m{0.0}, offset_z_m{0.0};
    double frame_height_m{0.30};
    double reference_dt_s{0.0};
    double reference_duration_s{1.0e-3};
    double reference_quiet_s{3.0e-4};
    unsigned reference_trials{1024};
    BondFailureTiming reference_timing{BondFailureTiming::StepRestart};
    std::string record_reference_path;
    double settle_maximum_s{6.0};
    double jolt_dt_s{1.0 / 120.0};
    double fps{60.0};
    double rest_speed_m_s{1.0e-3};
    double rest_angular_rad_s{1.0e-2};
    double rest_time_s{0.5};
    unsigned threads{0};
    std::string record_path, report_path;
    bool quiet{false};
    bool trace{false};
};

MaterialPreset presetFromName(const std::string &name) {
    if (name == "glass") return MaterialPreset::Glass;
    if (name == "oak" || name == "wood") return MaterialPreset::Oak;
    if (name == "iron") return MaterialPreset::Iron;
    throw std::invalid_argument("material must be glass, oak or iron");
}

Options parse(int argc, char **argv) {
    Options o;
    for (int i = 1; i < argc; ++i) {
        const std::string option = argv[i];
        if (option == "--quiet") { o.quiet = true; continue; }
        if (option == "--trace") { o.trace = true; continue; }
        if (++i >= argc) throw std::invalid_argument("missing value for " + option);
        const std::string value = argv[i];
        const auto number = [&]() {
            std::size_t used = 0;
            const double parsed = std::stod(value, &used);
            if (used != value.size() || !std::isfinite(parsed)) throw std::invalid_argument("bad number for " + option);
            return parsed;
        };
        const auto count = [&]() {
            const double parsed = number();
            if (parsed < 1 || parsed > 100000 || std::floor(parsed) != parsed) throw std::invalid_argument("bad count for " + option);
            return static_cast<unsigned>(parsed);
        };
        if (option == "--cells") {
            if (i + 2 >= argc) throw std::invalid_argument("--cells needs NX NY NZ");
            o.cells_x = count();
            i += 1; const std::string vy = argv[i]; o.cells_y = static_cast<unsigned>(std::stoul(vy));
            i += 1; const std::string vz = argv[i]; o.cells_z = static_cast<unsigned>(std::stoul(vz));
        } else if (option == "--cell") o.cell_m = number();
        else if (option == "--material") o.tile = presetFromName(value);
        else if (option == "--ball-radius") o.ball_radius_m = number();
        else if (option == "--drop") o.drop_m = number();
        else if (option == "--offset-x") o.offset_x_m = number();
        else if (option == "--offset-z") o.offset_z_m = number();
        else if (option == "--frame-height") o.frame_height_m = number();
        else if (option == "--reference-dt") o.reference_dt_s = number();
        else if (option == "--reference-duration") o.reference_duration_s = number();
        else if (option == "--reference-quiet") o.reference_quiet_s = number();
        else if (option == "--reference-trials") o.reference_trials = count();
        else if (option == "--reference-timing") {
            if (value == "end") o.reference_timing = BondFailureTiming::EndOfStep;
            else if (value == "restart") o.reference_timing = BondFailureTiming::StepRestart;
            else if (value == "bisect") o.reference_timing = BondFailureTiming::BisectedTime;
            else throw std::invalid_argument("reference timing must be end, restart or bisect");
        }
        else if (option == "--record-reference") o.record_reference_path = value;
        else if (option == "--settle-max") o.settle_maximum_s = number();
        else if (option == "--jolt-dt") o.jolt_dt_s = number();
        else if (option == "--fps") o.fps = number();
        else if (option == "--rest-speed") o.rest_speed_m_s = number();
        else if (option == "--rest-time") o.rest_time_s = number();
        else if (option == "--threads") o.threads = static_cast<unsigned>(number());
        else if (option == "--record") o.record_path = value;
        else if (option == "--report") o.report_path = value;
        else throw std::invalid_argument("unknown option " + option);
    }
    if (o.cells_x < 3 || o.cells_z < 3 || o.cells_y < 1) throw std::invalid_argument("the tile needs at least 3x1x3 cells (a rim and an interior)");
    if (!(o.cell_m > 0) || !(o.ball_radius_m > 0) || !(o.drop_m > 0) || !(o.frame_height_m > 0) || !(o.jolt_dt_s > 0) || !(o.fps > 0))
        throw std::invalid_argument("geometry, drop, step and fps must be positive");
    return o;
}

constexpr MatterBodyId kBall = 1;
constexpr MatterBodyId kFrameFirst = 2;
constexpr MatterBodyId kPieceFirst = 100;

struct Scene {
    Options options;
    MaterialDefinition tile_material, ball_material, frame_material;
    CompiledBrittleMaterial compiled;
    LatticeAsset asset;
    Vec3 tile_center{};
    Vec3 tile_size{};
    SupportPlaneFrame plane{};
    std::vector<std::uint32_t> eligible;
    std::vector<bool> mask;
    double ball_mass_kg{};
    Vec3 contact_center{};
    double ball_start_y{};
    double crack_transit_s{};
};

Scene buildScene(const Options &o) {
    Scene s;
    s.options = o;
    s.tile_material = makeReferenceMaterial(o.tile, 17);
    s.ball_material = makeReferenceMaterial(MaterialPreset::Iron, 17);
    s.frame_material = makeReferenceMaterial(MaterialPreset::Iron, 17);
    // Strength-derived failure on the elastic reference, exactly as the
    // implicit lane's probe compiles it, so both lanes read one surface.
    s.compiled = withStrengthDerivedFailure(compileElasticLatticeReference(s.tile_material, o.cell_m, 2), s.tile_material);
    s.asset = generateBoxLattice({o.cells_x, o.cells_y, o.cells_z, o.cell_m, 2}, s.compiled);
    s.tile_size = {o.cells_x * o.cell_m, o.cells_y * o.cell_m, o.cells_z * o.cell_m};
    s.tile_center = {0.0, o.frame_height_m + 0.5 * s.tile_size.y, 0.0};
    s.plane = makeSupportPlane({0.0, o.frame_height_m + 0.5 * o.cell_m, 0.0}, {0.0, 1.0, 0.0});
    s.mask.assign(s.asset.nodes.size(), false);
    for (std::uint32_t i = 0; i < s.asset.nodes.size(); ++i) {
        const GridCoord g = s.asset.nodes[i].grid;
        const bool rim = g.x == 0 || g.z == 0 || g.x + 1 == static_cast<int>(o.cells_x) || g.z + 1 == static_cast<int>(o.cells_z);
        if (g.y == 0 && rim) { s.eligible.push_back(i); s.mask[i] = true; }
    }
    s.ball_mass_kg = s.ball_material.density_kg_m3 * (4.0 / 3.0) * 3.14159265358979323846 * o.ball_radius_m * o.ball_radius_m * o.ball_radius_m;
    // First contact: the ball's centre path is vertical through the offset; the
    // node it reaches first sets the contact height.
    double contact_y = -std::numeric_limits<double>::infinity();
    for (const LatticeNodeRest &node : s.asset.nodes) {
        const Vec3 x = node.local_position_m + s.tile_center;
        const double dx = x.x - o.offset_x_m, dz = x.z - o.offset_z_m;
        const double rho2 = dx * dx + dz * dz;
        if (rho2 >= o.ball_radius_m * o.ball_radius_m) continue;
        contact_y = std::max(contact_y, x.y + std::sqrt(o.ball_radius_m * o.ball_radius_m - rho2));
    }
    if (!std::isfinite(contact_y)) throw std::invalid_argument("the ball path misses every lattice node");
    s.contact_center = {o.offset_x_m, contact_y, o.offset_z_m};
    s.ball_start_y = contact_y + o.drop_m;
    // Crack transit estimate: half the tile diagonal at 0.55 x the Rayleigh
    // speed of the tile material. This is a display interval for the recording,
    // not a computed quantity; the lane itself has no time in it.
    const double shear_modulus = s.tile_material.young_modulus_pa / (2.0 * (1.0 + s.tile_material.poisson_ratio));
    const double rayleigh = 0.93 * std::sqrt(shear_modulus / s.tile_material.density_kg_m3);
    s.crack_transit_s = 0.5 * std::hypot(s.tile_size.x, s.tile_size.z) / (0.55 * rayleigh);
    return s;
}

ActiveMatter makeMatter(const Scene &s) {
    ActiveMatter matter;
    matter.asset = &s.asset;
    matter.material = s.compiled;
    matter.bonds.resize(s.asset.bonds.size());
    for (const LatticeNodeRest &node : s.asset.nodes) {
        const Vec3 position = node.local_position_m + s.tile_center;
        matter.nodes.push_back({position, position, {}, node.represented_volume_m3 * s.compiled.density_kg_m3, {}});
        matter.reference_positions_world_m.push_back(position);
    }
    return matter;
}

std::uint32_t nodeAt(const Scene &s, int x, int y, int z) {
    return static_cast<std::uint32_t>(x + static_cast<int>(s.options.cells_x) * (y + static_cast<int>(s.options.cells_y) * z));
}

Json vec(const Vec3 &v) { return {v.x, v.y, v.z}; }
Json quat(const Quat &q) { return {q.w, q.x, q.y, q.z}; }

Json triangles(const FragmentSurfaceMesh &mesh) {
    Json out = Json::array();
    for (std::size_t i = 0; i + 2 < mesh.indices.size(); i += 3)
        out.push_back({vec(mesh.vertices[mesh.indices[i]].position_local_m), vec(mesh.vertices[mesh.indices[i + 1]].position_local_m),
                       vec(mesh.vertices[mesh.indices[i + 2]].position_local_m)});
    return out;
}

// --- fracture analysis -------------------------------------------------------

struct FractureSummary {
    std::size_t broken{};
    std::size_t components{};
    double largest_mass_fraction{};
    std::vector<double> piece_masses;
    Vec3 crack_centroid{};
    double crack_radius_of_gyration{};
    BondFailureModeCounts modes{};
    std::vector<bool> dead;
    std::vector<double> node_damage;
};

FractureSummary summarise(const ActiveMatter &matter, const Scene &s) {
    FractureSummary f;
    f.dead.assign(matter.bonds.size(), false);
    f.node_damage.assign(matter.nodes.size(), 0.0);
    Vec3 sum{};
    for (std::size_t b = 0; b < matter.bonds.size(); ++b) {
        if (matter.bonds[b].alive) continue;
        f.dead[b] = true;
        ++f.broken;
        const BondRest &rest = s.asset.bonds[b];
        sum += 0.5 * (matter.reference_positions_world_m[rest.node_a] + matter.reference_positions_world_m[rest.node_b]);
    }
    if (f.broken > 0) {
        f.crack_centroid = sum / static_cast<double>(f.broken);
        double gyration = 0;
        for (std::size_t b = 0; b < matter.bonds.size(); ++b) {
            if (matter.bonds[b].alive) continue;
            const BondRest &rest = s.asset.bonds[b];
            const Vec3 mid = 0.5 * (matter.reference_positions_world_m[rest.node_a] + matter.reference_positions_world_m[rest.node_b]);
            gyration += lengthSquared(mid - f.crack_centroid);
        }
        f.crack_radius_of_gyration = std::sqrt(gyration / static_cast<double>(f.broken));
    }
    for (std::uint32_t n = 0; n < matter.nodes.size(); ++n) {
        const std::uint32_t begin = s.asset.adjacency_offsets[n], end = s.asset.adjacency_offsets[n + 1];
        unsigned dead = 0;
        for (std::uint32_t a = begin; a < end; ++a) dead += f.dead[s.asset.adjacent_bond_indices[a]] ? 1U : 0U;
        f.node_damage[n] = end > begin ? static_cast<double>(dead) / static_cast<double>(end - begin) : 0.0;
    }
    const auto components = findConnectedComponents(matter);
    f.components = components.size();
    double total = 0;
    for (const auto &c : components) {
        double mass = 0;
        for (const std::uint32_t n : c.node_indices) mass += matter.nodes[n].mass_kg;
        f.piece_masses.push_back(mass);
        total += mass;
    }
    std::sort(f.piece_masses.rbegin(), f.piece_masses.rend());
    f.largest_mass_fraction = total > 0 && !f.piece_masses.empty() ? f.piece_masses.front() / total : 0.0;
    f.modes = countBondFailureModes(matter);
    return f;
}

Json summaryJson(const FractureSummary &f) {
    Json masses = Json::array();
    for (std::size_t i = 0; i < f.piece_masses.size() && i < 32; ++i) masses.push_back(f.piece_masses[i]);
    return {{"broken_bonds", f.broken}, {"components", f.components}, {"largest_mass_fraction", f.largest_mass_fraction},
            {"piece_masses_kg", masses}, {"crack_centroid_m", vec(f.crack_centroid)},
            {"crack_radius_of_gyration_m", f.crack_radius_of_gyration},
            {"failure_modes", {{"tensile", f.modes.tensile}, {"compressive", f.modes.compressive}, {"shear", f.modes.shear}}}};
}

double jaccard(const std::vector<bool> &a, const std::vector<bool> &b) {
    std::size_t both = 0, either = 0;
    for (std::size_t i = 0; i < a.size(); ++i) { both += (a[i] && b[i]) ? 1U : 0U; either += (a[i] || b[i]) ? 1U : 0U; }
    return either > 0 ? static_cast<double>(both) / static_cast<double>(either) : 1.0;
}

double correlation(const std::vector<double> &a, const std::vector<double> &b) {
    const double n = static_cast<double>(a.size());
    const double ma = std::accumulate(a.begin(), a.end(), 0.0) / n, mb = std::accumulate(b.begin(), b.end(), 0.0) / n;
    double sab = 0, saa = 0, sbb = 0;
    for (std::size_t i = 0; i < a.size(); ++i) { sab += (a[i] - ma) * (b[i] - mb); saa += (a[i] - ma) * (a[i] - ma); sbb += (b[i] - mb) * (b[i] - mb); }
    return saa > 0 && sbb > 0 ? sab / std::sqrt(saa * sbb) : 0.0;
}

Json compareJson(const FractureSummary &a, const FractureSummary &b) {
    return {{"broken_bond_jaccard", jaccard(a.dead, b.dead)}, {"node_damage_correlation", correlation(a.node_damage, b.node_damage)},
            {"broken_bonds", {a.broken, b.broken}}, {"components", {a.components, b.components}},
            {"largest_mass_fraction", {a.largest_mass_fraction, b.largest_mass_fraction}},
            {"crack_centroid_distance_m", length(a.crack_centroid - b.crack_centroid)},
            {"crack_radius_of_gyration_m", {a.crack_radius_of_gyration, b.crack_radius_of_gyration}}};
}

Json bondSetJson(const std::vector<std::uint32_t> &bonds, const Scene &s, const ActiveMatter &matter) {
    Json list = Json::array();
    double radial = 0, layer = 0;
    for (const std::uint32_t b : bonds) {
        const BondRest &rest = s.asset.bonds[b];
        const Vec3 mid = 0.5 * (matter.reference_positions_world_m[rest.node_a] + matter.reference_positions_world_m[rest.node_b]);
        radial += std::hypot(mid.x - s.options.offset_x_m, mid.z - s.options.offset_z_m);
        layer += 0.5 * (s.asset.nodes[rest.node_a].grid.y + s.asset.nodes[rest.node_b].grid.y);
        if (list.size() < 64) list.push_back({{"bond", b}, {"a", rest.node_a}, {"b", rest.node_b}, {"mid_m", vec(mid)},
            {"mode", matter.bonds[b].failure_mode == BondFailureMode::Tension ? "tension" : matter.bonds[b].failure_mode == BondFailureMode::Shear ? "shear" : "compression"}});
    }
    const double n = bonds.empty() ? 1.0 : static_cast<double>(bonds.size());
    return {{"count", bonds.size()}, {"mean_radial_distance_m", radial / n}, {"mean_layer", layer / n}, {"bonds", list}};
}

// --- the dynamic reference on the same lattice --------------------------------

struct ReferenceRun {
    bool ran{};
    bool completed{};
    std::string failure;
    double dt_s{};
    double simulated_s{};
    double wall_s{};
    unsigned steps{};
    unsigned solver_trials{};
    unsigned discarded_trials{};
    double first_failure_time_s{-1.0};
    double last_failure_time_s{-1.0};
    std::vector<std::uint32_t> first_failure_bonds;
    double removed_energy_j{};
    double energy_residual_j{};
    RigidSnapshot ball{};
    double dt_over_limit{};
    FractureSummary summary;
    Json steps_log = Json::array();
    ActiveMatter matter; // final state, node velocities included
};

ReferenceRun runReference(const Scene &s, const Vec3 &contact_velocity) {
    const Options &o = s.options;
    ReferenceRun r;
    r.ran = true;
    r.dt_s = o.reference_dt_s;
    r.matter = makeMatter(s);
    ActiveMatter &matter = r.matter;
    CoupledSphereState sphere;
    // A hair above contact so the reference's overlap validation accepts the state.
    sphere.motion.center_of_mass_world_m = s.contact_center + Vec3{0.0, 1.0e-9, 0.0};
    sphere.motion.linear_velocity_m_s = contact_velocity;
    sphere.radius_m = o.ball_radius_m;
    sphere.mass_kg = s.ball_mass_kg;
    sphere.inertia_kg_m2 = 0.4 * s.ball_mass_kg * o.ball_radius_m * o.ball_radius_m;
    const Vec3 gravity{0.0, -9.81, 0.0};
    const auto limit = measureLatticeResolutionLimit(s.asset, s.compiled);
    r.dt_over_limit = limit.explicit_substep_limit_s > 0 ? o.reference_dt_s / limit.explicit_substep_limit_s : 0.0;
    ConservativeStepSettings solver;
    solver.support = &s.plane;
    solver.support_node_mask = &s.mask;
    FractureStepSettings settings{.solver = solver, .timing = o.reference_timing,
                                  .maximum_solver_trials = o.reference_trials, .maximum_bisections = 8};
    std::vector<bool> alive(matter.bonds.size(), true);
    const auto start = Clock::now();
    double t = 0;
    while (t < o.reference_duration_s) {
        const auto result = tryFracturingStep(matter, o.reference_dt_s, gravity, &sphere, settings);
        if (!result.converged) {
            r.failure = result.failure == FractureStepFailure::SolverRejected ? "solver_rejected" : "trial_budget_exhausted";
            break;
        }
        ++r.steps;
        t += o.reference_dt_s;
        r.solver_trials += result.solver_trials;
        r.discarded_trials += result.discarded_trials;
        r.removed_energy_j += result.removed_bond_energy_j;
        r.energy_residual_j += result.energy_residual_j;
        std::vector<std::uint32_t> removed;
        for (std::uint32_t b = 0; b < matter.bonds.size(); ++b)
            if (alive[b] && !matter.bonds[b].alive) { alive[b] = false; removed.push_back(b); }
        if (!removed.empty()) {
            if (r.first_failure_time_s < 0) { r.first_failure_time_s = t; r.first_failure_bonds = removed; }
            r.last_failure_time_s = t;
        }
        if (r.steps_log.size() < 4000 && (!removed.empty() || r.steps % 50 == 0))
            r.steps_log.push_back({{"t_s", t}, {"removed", removed.size()}, {"total_broken", countBrokenBonds(matter)},
                {"ball_y_m", sphere.motion.center_of_mass_world_m.y}, {"ball_vy_m_s", sphere.motion.linear_velocity_m_s.y},
                {"trials", result.solver_trials}, {"wall_s", seconds(start)}});
        if (r.first_failure_time_s >= 0 && t - r.last_failure_time_s >= o.reference_quiet_s) { r.completed = true; break; }
    }
    if (t >= o.reference_duration_s) r.completed = r.failure.empty();
    r.simulated_s = t;
    r.wall_s = seconds(start);
    r.ball = sphere.motion;
    r.summary = summarise(matter, s);
    return r;
}

// --- the recording -------------------------------------------------------------

struct FrameBar { MatterBodyId id; Vec3 center; Vec3 size; };

std::vector<FrameBar> frameBars(const Scene &scene) {
    const double h = scene.options.cell_m, height = scene.options.frame_height_m;
    const Vec3 size = scene.tile_size;
    return {{kFrameFirst + 0, {0.0, 0.5 * height, 0.5 * size.z - 0.5 * h}, {size.x, height, h}},
            {kFrameFirst + 1, {0.0, 0.5 * height, -(0.5 * size.z - 0.5 * h)}, {size.x, height, h}},
            {kFrameFirst + 2, {0.5 * size.x - 0.5 * h, 0.5 * height, 0.0}, {h, height, size.z - 2.0 * h}},
            {kFrameFirst + 3, {-(0.5 * size.x - 0.5 * h), 0.5 * height, 0.0}, {h, height, size.z - 2.0 * h}}};
}

void addStaticScene(JoltWorld &world, const Scene &scene, const std::vector<FrameBar> &bars, const Vec3 &gravity) {
    world.setGravity(gravity);
    world.addFloor();
    for (const FrameBar &bar : bars)
        world.addBox({.body_id = bar.id, .dimensions_m = bar.size, .material = scene.frame_material,
                      .state = {bar.center, {}, {}, {}}, .fixed = true});
}

Json pose(const std::string &id, const RigidSnapshot &snap, unsigned component) {
    return Json{{"id", id}, {"position_m", vec(snap.center_of_mass_world_m)}, {"orientation_wxyz", quat(snap.orientation_world)}, {"component_id", component}};
}

Json bondLines(const ActiveMatter &m, const Scene &scene) {
    Json list = Json::array();
    for (std::size_t b = 0; b < m.bonds.size(); ++b) {
        const BondRest &rest = scene.asset.bonds[b];
        list.push_back({{"a_m", vec(m.nodes[rest.node_a].position_world_m)}, {"b_m", vec(m.nodes[rest.node_b].position_world_m)},
                        {"live", m.bonds[b].alive}, {"damage", std::clamp(m.bonds[b].damage, 0.0, 1.0)}});
    }
    return list;
}

// The viewer reads colours as 0xRRGGBBAA, as the network lane packs them.
std::uint32_t rgba(std::uint32_t rgb) { return (rgb << 8) | 0xffU; }
std::uint32_t tileColour(MaterialPreset preset) {
    return rgba(preset == MaterialPreset::Glass ? 0x7fb2e5U : preset == MaterialPreset::Oak ? 0xc89a5bU : 0xa7a7a7U);
}

Json staticBodies(const Scene &scene, const std::vector<FrameBar> &bars, const ActiveMatter &intact) {
    const Options &o = scene.options;
    Json bodies = Json::array();
    bodies.push_back({{"id", "ball"}, {"object_id", kBall}, {"element_id", 0}, {"material_id", "iron"}, {"color_rgba", rgba(0x9a9a9aU)},
                      {"shape", "sphere"}, {"dimensions_m", {2 * o.ball_radius_m, 2 * o.ball_radius_m, 2 * o.ball_radius_m}}});
    for (std::size_t k = 0; k < bars.size(); ++k)
        bodies.push_back({{"id", "frame:" + std::to_string(k)}, {"object_id", bars[k].id}, {"element_id", 0}, {"material_id", "iron"},
                          {"color_rgba", rgba(0x555555U)}, {"shape", "box"}, {"dimensions_m", vec(bars[k].size)}});
    std::vector<std::uint32_t> all(intact.nodes.size());
    std::iota(all.begin(), all.end(), 0U);
    const auto mesh = buildExposedVoxelSurface(intact, all, scene.tile_center);
    bodies.push_back({{"id", "tile"}, {"object_id", 10}, {"element_id", 0}, {"material_id", std::string(materialPresetName(o.tile))},
                      {"color_rgba", tileColour(o.tile)}, {"shape", "mesh"}, {"dimensions_m", vec(scene.tile_size)}, {"local_triangles_m", triangles(mesh)}});
    return bodies;
}

// ---- Stage 1: the ball falls in Jolt until it reaches the lattice's contact node.
struct FallStage {
    Json frames = Json::array();
    RigidSnapshot contact{};
    double contact_time{};
    unsigned steps{};
    double wall{};
    double landing_error{};
};

FallStage runFall(const Scene &scene, const Options &o, const std::vector<FrameBar> &bars, const Json &intact_bonds) {
    const auto start = Clock::now();
    const Vec3 gravity{0.0, -9.81, 0.0};
    JoltWorld world(o.threads);
    addStaticScene(world, scene, bars, gravity);
    world.addBall({.body_id = kBall, .radius_m = o.ball_radius_m, .material = scene.ball_material,
                   .position_world_m = {o.offset_x_m, scene.ball_start_y, o.offset_z_m}});
    FallStage f;
    const auto capture = [&](double time, const Json *bonds) {
        Json poses = Json::array();
        poses.push_back(pose("ball", world.snapshot(kBall), 0));
        for (std::size_t k = 0; k < bars.size(); ++k) poses.push_back(pose("frame:" + std::to_string(k), {bars[k].center, {}, {}, {}}, 0));
        poses.push_back(pose("tile", {scene.tile_center, {}, {}, {}}, 0));
        f.frames.push_back({{"time_s", time}, {"poses", std::move(poses)}, {"bonds", bonds ? *bonds : Json::array()}, {"fracture_count", 0}});
    };
    double t = 0, next_frame = 1.0 / o.fps;
    capture(0.0, nullptr);
    for (;;) {
        const RigidSnapshot ball = world.snapshot(kBall);
        const double remaining = ball.center_of_mass_world_m.y - scene.contact_center.y;
        if (remaining <= 0) break;
        const double vy = ball.linear_velocity_m_s.y, g = -gravity.y;
        // Jolt integrates velocity first: y' = y + (vy - g dt) dt. Land exactly.
        const double dt_star = (vy + std::sqrt(vy * vy + 4.0 * g * remaining)) / (2.0 * g);
        const double dt = std::min(dt_star, o.jolt_dt_s);
        world.step(dt);
        t += dt;
        ++f.steps;
        if (t + 1.0e-12 >= next_frame && dt_star > o.jolt_dt_s) { capture(t, nullptr); next_frame += 1.0 / o.fps; }
        if (dt_star <= o.jolt_dt_s) break;
    }
    f.contact = world.snapshot(kBall);
    f.contact_time = t;
    f.landing_error = f.contact.center_of_mass_world_m.y - scene.contact_center.y;
    capture(t, &intact_bonds);
    f.wall = seconds(start);
    return f;
}

// ---- Stage 4: pieces into Jolt, settle to rest, record.
struct SettleStage {
    Json frames = Json::array();
    Json bodies = Json::array(); // the piece bodies
    std::size_t pieces{};
    unsigned box_pieces{}, compound_pieces{}, hull_fallbacks{};
    std::size_t largest_parts{};
    double ball_lift{};
    unsigned steps{};
    double simulated{};
    bool settled{};
    double final_speed{}, final_angular{};
    Vec3 ball_rest{};
    Json piece_rest = Json::array();
    double mechanical_energy{};
    double piece_kinetic_energy_in{};
    double end_time{};
    double wall{};
};

SettleStage runSettle(const Scene &scene, const Options &o, const std::vector<FrameBar> &bars, ActiveMatter &matter,
    const RigidSnapshot &ball_in, double t0, std::size_t fracture_count) {
    const auto start = Clock::now();
    const Vec3 gravity{0.0, -9.81, 0.0};
    JoltWorld world(o.threads);
    addStaticScene(world, scene, bars, gravity);
    world.addBall({.body_id = kBall, .radius_m = o.ball_radius_m, .material = scene.ball_material,
                   .position_world_m = ball_in.center_of_mass_world_m});
    SettleStage st;
    const auto components = findConnectedComponents(matter);
    struct CellBox { Vec3 min, max; };
    std::vector<CellBox> cell_boxes;
    std::vector<MatterBodyId> pieces;
    for (std::size_t k = 0; k < components.size(); ++k) {
        const auto &component = components[k];
        const MatterBodyId id = kPieceFirst + static_cast<MatterBodyId>(k);
        // Mass, centre, inertia and the rigid motion the nodes carry (zero for
        // the quasi-static lane, the fragment velocities for the reference).
        const FragmentMassProperties props = calculateFragmentMassProperties(matter, component.node_indices);
        st.piece_kinetic_energy_in += props.rigid_kinetic_energy_j;
        std::vector<GridCoord> cells;
        for (const std::uint32_t n : component.node_indices) {
            cells.push_back(scene.asset.nodes[n].grid);
            const Vec3 p = matter.nodes[n].position_world_m;
            cell_boxes.push_back({p - Vec3{0.5 * o.cell_m, 0.5 * o.cell_m, 0.5 * o.cell_m}, p + Vec3{0.5 * o.cell_m, 0.5 * o.cell_m, 0.5 * o.cell_m}});
        }
        const auto boxes = mergeCellsIntoBoxes(cells);
        st.largest_parts = std::max(st.largest_parts, boxes.size());
        std::vector<RigidCompoundPart> parts;
        for (const VoxelBox &box : boxes) {
            const Vec3 lo = matter.nodes[nodeAt(scene, box.minimum.x, box.minimum.y, box.minimum.z)].position_world_m;
            const Vec3 hi = matter.nodes[nodeAt(scene, box.maximum.x, box.maximum.y, box.maximum.z)].position_world_m;
            const Vec3 size{(box.maximum.x - box.minimum.x + 1) * o.cell_m, (box.maximum.y - box.minimum.y + 1) * o.cell_m,
                            (box.maximum.z - box.minimum.z + 1) * o.cell_m};
            parts.push_back({RigidPrimitive{PrimitiveKind::Box, 0.0, size}, 0.5 * (lo + hi) - props.center_of_mass_world_m});
        }
        const RigidSnapshot state{props.center_of_mass_world_m, {}, props.linear_velocity_m_s, props.angular_velocity_rad_s};
        if (parts.size() == 1) {
            world.addBox({.body_id = id, .dimensions_m = parts.front().geometry.dimensions_m, .material = scene.tile_material,
                          .state = {props.center_of_mass_world_m + parts.front().center_local_m, {}, props.linear_velocity_m_s, props.angular_velocity_rad_s},
                          .fixed = false});
            ++st.box_pieces;
        } else if (parts.size() <= 64) {
            world.addCompound({id, parts, scene.tile_material, state, props.mass_kg, props.inertia_world_kg_m2});
            ++st.compound_pieces;
        } else {
            // More boxes than a compound may carry: a bounded convex proxy of
            // the piece's surface, as the legacy fragment path builds it.
            FragmentBuildSettings settings;
            settings.first_body_id = id;
            settings.maximum_rigid_fragments = 1;
            settings.minimum_nodes_per_rigid_fragment = 1;
            const auto built = buildFragmentRepresentations(matter, std::vector<FragmentComponent>{component}, settings);
            world.addFragments(built.rigid_fragments);
            ++st.hull_fallbacks;
        }
        pieces.push_back(id);
        const auto mesh = buildExposedVoxelSurface(matter, component.node_indices, props.center_of_mass_world_m);
        st.bodies.push_back({{"id", "piece:" + std::to_string(k)}, {"object_id", id}, {"element_id", 0},
                             {"material_id", std::string(materialPresetName(o.tile))}, {"color_rgba", tileColour(o.tile)}, {"shape", "mesh"},
                             {"dimensions_m", vec(scene.tile_size)}, {"local_triangles_m", triangles(mesh)}});
    }
    st.pieces = pieces.size();
    // The ball must not start inside a piece's cells: lattice contact is against
    // node points, half a cell below the cell surface, so lift it clear.
    Vec3 ball_center = ball_in.center_of_mass_world_m;
    {
        double required = -std::numeric_limits<double>::infinity();
        for (const CellBox &box : cell_boxes) {
            const double dx = std::max({box.min.x - ball_center.x, 0.0, ball_center.x - box.max.x});
            const double dz = std::max({box.min.z - ball_center.z, 0.0, ball_center.z - box.max.z});
            const double rho2 = dx * dx + dz * dz;
            if (rho2 >= o.ball_radius_m * o.ball_radius_m) continue;
            required = std::max(required, box.max.y + std::sqrt(o.ball_radius_m * o.ball_radius_m - rho2));
        }
        if (required > ball_center.y) ball_center.y = required;
    }
    st.ball_lift = ball_center.y - ball_in.center_of_mass_world_m.y;
    world.applyRigidState(kBall, {ball_center, {}, ball_in.linear_velocity_m_s, ball_in.angular_velocity_rad_s});

    const auto capture = [&](double time, const Json *bonds) {
        Json poses = Json::array();
        poses.push_back(pose("ball", world.snapshot(kBall), 0));
        for (std::size_t k = 0; k < bars.size(); ++k) poses.push_back(pose("frame:" + std::to_string(k), {bars[k].center, {}, {}, {}}, 0));
        for (std::size_t k = 0; k < pieces.size(); ++k) poses.push_back(pose("piece:" + std::to_string(k), world.snapshot(pieces[k]), static_cast<unsigned>(k)));
        st.frames.push_back({{"time_s", time}, {"poses", std::move(poses)}, {"bonds", bonds ? *bonds : Json::array()}, {"fracture_count", fracture_count}});
    };
    const Json fracture_bonds = bondLines(matter, scene);
    double sim_time = t0;
    capture(sim_time, &fracture_bonds);
    double next_frame = sim_time + 1.0 / o.fps;
    double still_since = -1.0;
    while (st.simulated < o.settle_maximum_s) {
        world.step(o.jolt_dt_s);
        st.simulated += o.jolt_dt_s;
        sim_time += o.jolt_dt_s;
        ++st.steps;
        if (sim_time + 1.0e-12 >= next_frame) { capture(sim_time, nullptr); next_frame += 1.0 / o.fps; }
        double speed = length(world.snapshot(kBall).linear_velocity_m_s), angular = length(world.snapshot(kBall).angular_velocity_rad_s);
        for (const MatterBodyId id : pieces) {
            const RigidSnapshot snap = world.snapshot(id);
            speed = std::max(speed, length(snap.linear_velocity_m_s));
            angular = std::max(angular, length(snap.angular_velocity_rad_s));
        }
        st.final_speed = speed; st.final_angular = angular;
        if (speed < o.rest_speed_m_s && angular < o.rest_angular_rad_s) {
            if (still_since < 0) still_since = st.simulated;
            else if (st.simulated - still_since >= o.rest_time_s) { st.settled = true; break; }
        } else still_since = -1.0;
    }
    if (st.frames.back().at("time_s").get<double>() != sim_time) capture(sim_time, nullptr);
    st.end_time = sim_time;
    st.ball_rest = world.snapshot(kBall).center_of_mass_world_m;
    for (const MatterBodyId id : pieces) st.piece_rest.push_back(vec(world.snapshot(id).center_of_mass_world_m));
    st.mechanical_energy = world.mechanicalTotals(gravity).mechanicalEnergy();
    st.wall = seconds(start);
    return st;
}

Json settleJson(const SettleStage &st) {
    return {{"pieces", st.pieces}, {"box_pieces", st.box_pieces}, {"compound_pieces", st.compound_pieces}, {"hull_fallbacks", st.hull_fallbacks},
            {"largest_piece_parts", st.largest_parts}, {"ball_lift_m", st.ball_lift}, {"steps", st.steps}, {"simulated_s", st.simulated},
            {"settled", st.settled}, {"final_max_speed_m_s", st.final_speed}, {"final_max_angular_rad_s", st.final_angular},
            {"ball_rest_m", vec(st.ball_rest)}, {"piece_rest_m", st.piece_rest}, {"mechanical_energy_j", st.mechanical_energy},
            {"piece_kinetic_energy_in_j", st.piece_kinetic_energy_in}, {"end_time_s", st.end_time}, {"wall_s", st.wall}};
}

std::size_t writeRecording(const std::string &path, const Json &bodies, const Json &fall_frames, const SettleStage &st,
    const FallStage &fall, const Json &report, const std::string &status, const std::string &error) {
    Json artifact{{"schema", "banjo.playback.v1"}, {"mode", "network"}, {"units", "SI"}, {"bodies", bodies},
                  {"supports", Json::array()}, {"frames", Json::array()}, {"physical_response_validated", false}};
    const double floor_extent = 0.6;
    artifact["supports"] = {{{-floor_extent, 0.0, -floor_extent}, {floor_extent, 0.0, -floor_extent}, {floor_extent, 0.0, floor_extent}},
                            {{-floor_extent, 0.0, -floor_extent}, {floor_extent, 0.0, floor_extent}, {-floor_extent, 0.0, floor_extent}}};
    for (const Json &frame : fall_frames) artifact["frames"].push_back(frame);
    for (const Json &frame : st.frames) artifact["frames"].push_back(frame);
    artifact["requested_steps"] = fall.steps + st.steps;
    artifact["completed_steps"] = fall.steps + st.steps;
    artifact["sampling"] = {{"stride_steps", 1}, {"maximum_frames", artifact["frames"].size()}, {"interpolation", "none"}};
    artifact["status"] = status;
    artifact["error"] = error;
    artifact["report"] = report;
    const std::string serialized = artifact.dump();
    if (serialized.size() > 64U * 1024U * 1024U) throw std::runtime_error("recording exceeds the 64 MiB playback budget");
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("cannot write recording " + path);
    out << serialized;
    return serialized.size();
}

int run(const Options &o) {
    const auto total_start = Clock::now();
    const Scene scene = buildScene(o);
    const std::vector<FrameBar> bars = frameBars(scene);
    Json report;
    report["scene"] = {{"cells", {o.cells_x, o.cells_y, o.cells_z}}, {"cell_m", o.cell_m}, {"tile_material", materialPresetName(o.tile)},
        {"nodes", scene.asset.nodes.size()}, {"bonds", scene.asset.bonds.size()}, {"tile_mass_kg", scene.asset.total_mass_kg},
        {"ball_radius_m", o.ball_radius_m}, {"ball_mass_kg", scene.ball_mass_kg}, {"drop_m", o.drop_m},
        {"impact_offset_m", {o.offset_x_m, o.offset_z_m}}, {"frame_height_m", o.frame_height_m},
        {"support_nodes", scene.eligible.size()}, {"contact_center_m", vec(scene.contact_center)},
        {"crack_transit_display_s", scene.crack_transit_s},
        {"thresholds", {{"tensile_break", scene.compiled.damage_end_stretch}, {"shear_break", scene.compiled.shear_damage_end_strain},
                        {"compressive_break", scene.compiled.compression_damage_end_strain}}}};
    {
        const auto limit = measureLatticeResolutionLimit(scene.asset, scene.compiled);
        report["scene"]["lattice_explicit_substep_limit_s"] = limit.explicit_substep_limit_s;
    }
    ActiveMatter matter = makeMatter(scene);
    const Json static_bodies = staticBodies(scene, bars, matter);

    // ---- Stage 1: the fall. ----------------------------------------------------
    const FallStage fall = runFall(scene, o, bars, bondLines(matter, scene));
    report["fall"] = {{"steps", fall.steps}, {"contact_time_s", fall.contact_time}, {"ball_center_m", vec(fall.contact.center_of_mass_world_m)},
                      {"ball_velocity_m_s", vec(fall.contact.linear_velocity_m_s)}, {"landing_error_m", fall.landing_error}, {"wall_s", fall.wall}};

    // ---- Stage 2: the quasi-static lane. -------------------------------------
    const auto stage2 = Clock::now();
    QuasiStaticImpactScene qs;
    qs.gravity_m_s2 = {0.0, -9.81, 0.0};
    qs.support = scene.plane;
    qs.support_nodes = scene.eligible;
    qs.ball_center_m = scene.contact_center;
    qs.ball_direction = normalized(fall.contact.linear_velocity_m_s, {0.0, -1.0, 0.0});
    qs.ball_radius_m = o.ball_radius_m;
    qs.ball_mass_kg = scene.ball_mass_kg;
    qs.ball_speed_m_s = length(fall.contact.linear_velocity_m_s);
    qs.maximum_travel_m = scene.tile_size.y + o.cell_m;
    QuasiStaticImpactSettings qs_settings;
    qs_settings.trace = o.trace;
    const QuasiStaticImpactResult qsr = runQuasiStaticImpact(matter, qs, qs_settings);
    const double stage2_wall = seconds(stage2);
    const FractureSummary qs_summary = summarise(matter, scene);
    Json events = Json::array();
    for (std::size_t i = 0; i < qsr.log.size() && i < 5000; ++i) {
        const auto &e = qsr.log[i];
        events.push_back({{"travel_m", e.travel_m}, {"rounds", e.rounds}, {"bonds_removed", e.bonds_removed}, {"force_n", e.contact_force_n},
                          {"work_j", e.ball_work_j}, {"stored_j", e.stored_elastic_j}, {"components", e.components}, {"frozen", e.frozen_components}});
    }
    const double closure = qsr.ball_work_j - (qsr.potential_end_j - qsr.potential_start_j) - qsr.removed_bond_energy_linear_j - qsr.released_energy_j - qsr.relaxation_energy_j;
    report["quasistatic"] = {{"converged", qsr.converged}, {"stop", quasiStaticStopName(qsr.stop)}, {"events", qsr.events}, {"rounds", qsr.rounds},
        {"static_solves", qsr.static_solves}, {"linear_iterations", qsr.linear_iterations}, {"active_set_iterations", qsr.active_set_iterations},
        {"travel_m", qsr.travel_m}, {"ball_center_m", vec(qsr.ball_center_m)}, {"ball_velocity_m_s", vec(qsr.ball_velocity_m_s)},
        {"ledger", {{"kinetic_in_j", qsr.kinetic_energy_in_j}, {"ball_work_j", qsr.ball_work_j}, {"kinetic_out_j", qsr.kinetic_energy_out_j},
                    {"potential_start_j", qsr.potential_start_j}, {"potential_end_j", qsr.potential_end_j}, {"stored_elastic_j", qsr.stored_elastic_j},
                    {"removed_bond_energy_j", qsr.removed_bond_energy_j}, {"removed_bond_energy_linear_j", qsr.removed_bond_energy_linear_j},
                    {"released_j", qsr.released_energy_j}, {"relaxation_j", qsr.relaxation_energy_j}, {"segment_work_mismatch_j", qsr.segment_work_mismatch_j},
                    {"closure_j", closure}}},
        {"support", {{"max_normal_n", qsr.maximum_support_normal_force_n}, {"total_normal_n", qsr.total_support_normal_force_n},
                     {"pinned_rigid_force_n", qsr.pinned_rigid_force_n}, {"pinned_rigid_torque_n_m", qsr.pinned_rigid_torque_n_m},
                     {"required_friction", qsr.required_friction_coefficient}}},
        {"pinned_mechanism_directions", qsr.pinned_mechanism_directions}, {"pinned_mechanism_modes", qsr.pinned_mechanism_modes},
        {"pinned_mechanism_force_n", qsr.pinned_mechanism_force_n},
        {"first_failure", bondSetJson(qsr.first_failure_bonds, scene, matter)}, {"first_failure_travel_m", qsr.first_failure_travel_m},
        {"first_failure_force_n", qsr.first_failure_force_n}, {"frozen_components", qsr.frozen_components},
        {"summary", summaryJson(qs_summary)}, {"wall_s", stage2_wall},
        {"wall_breakdown_s", {{"solve", qsr.solve_wall_s}, {"criterion", qsr.criterion_wall_s}, {"topology", qsr.topology_wall_s}}},
        {"event_log", events}};

    // ---- Stage 3 (optional): the dynamic reference. --------------------------
    ReferenceRun reference;
    if (o.reference_dt_s > 0) {
        reference = runReference(scene, fall.contact.linear_velocity_m_s);
        report["reference"] = {{"dt_s", reference.dt_s}, {"dt_over_lattice_limit", reference.dt_over_limit}, {"completed", reference.completed},
            {"timing", o.reference_timing == BondFailureTiming::EndOfStep ? "end" : o.reference_timing == BondFailureTiming::StepRestart ? "restart" : "bisect"},
            {"failure", reference.failure}, {"steps", reference.steps}, {"simulated_s", reference.simulated_s}, {"wall_s", reference.wall_s},
            {"solver_trials", reference.solver_trials}, {"discarded_trials", reference.discarded_trials},
            {"first_failure_time_s", reference.first_failure_time_s}, {"last_failure_time_s", reference.last_failure_time_s},
            {"removed_bond_energy_j", reference.removed_energy_j}, {"energy_residual_j", reference.energy_residual_j},
            {"ball_center_m", vec(reference.ball.center_of_mass_world_m)}, {"ball_velocity_m_s", vec(reference.ball.linear_velocity_m_s)},
            {"summary", summaryJson(reference.summary)},
            {"first_failure", bondSetJson(reference.first_failure_bonds, scene, matter)}, {"steps_log", reference.steps_log},
            {"realtime_factor", reference.simulated_s > 0 ? reference.wall_s / reference.simulated_s : 0.0}};
        Json cmp = compareJson(qs_summary, reference.summary);
        std::vector<bool> qs_first(matter.bonds.size(), false), ref_first(matter.bonds.size(), false);
        for (const auto b : qsr.first_failure_bonds) qs_first[b] = true;
        for (const auto b : reference.first_failure_bonds) ref_first[b] = true;
        cmp["first_failure_jaccard"] = jaccard(qs_first, ref_first);
        cmp["removed_bond_energy_j"] = {qsr.removed_bond_energy_j, reference.removed_energy_j};
        report["comparison"] = cmp;
    }

    // ---- Stage 4: the quasi-static pieces settle in Jolt. -------------------
    const double fracture_time = fall.contact_time + scene.crack_transit_s;
    SettleStage settle = runSettle(scene, o, bars, matter, {qsr.ball_center_m, {}, qsr.ball_velocity_m_s, {}}, fracture_time, qs_summary.broken);
    report["settle"] = settleJson(settle);

    // ---- Recording and accounting. ---------------------------------------------
    const double simulated_total = settle.end_time;
    const double wall_pipeline = fall.wall + stage2_wall + settle.wall;
    const auto write_start = Clock::now();
    std::size_t record_bytes = 0;
    const std::string status = qsr.converged ? "complete" : "solver_limit";
    const std::string error = qsr.converged ? "" : std::string("quasi-static lane stopped: ") + quasiStaticStopName(qsr.stop);
    Json summary_report{{"fracture_count", qs_summary.broken}, {"broken_bonds", qs_summary.broken}, {"elapsed_s", simulated_total},
        {"wall_ms", 1000.0 * wall_pipeline}, {"mass_kg", scene.asset.total_mass_kg}, {"energy_j", qsr.kinetic_energy_in_j},
        {"status", status}, {"components", qs_summary.components}, {"lane", "quasi-static"}};
    Json qs_bodies = static_bodies;
    for (const Json &body : settle.bodies) qs_bodies.push_back(body);
    if (!o.record_path.empty()) record_bytes = writeRecording(o.record_path, qs_bodies, fall.frames, settle, fall, summary_report, status, error);
    const double write_wall = seconds(write_start);
    const double wall_total = wall_pipeline + write_wall;
    Json realtime{{"simulated_s", simulated_total}, {"wall_pipeline_s", wall_pipeline}, {"wall_with_recording_s", wall_total},
        {"ratio_pipeline", wall_pipeline / simulated_total}, {"ratio_with_recording", wall_total / simulated_total},
        {"rule_met_1_1x", wall_total / simulated_total <= 1.1},
        {"stages_s", {{"fall", fall.wall}, {"fracture", stage2_wall}, {"settle", settle.wall}, {"recording", write_wall}}},
        {"frames", fall.frames.size() + settle.frames.size()}, {"record_bytes", record_bytes}};
    report["realtime"] = realtime;
    if (!o.record_path.empty()) {
        // Rewrite with the realtime block in the recording's report; the
        // measured write time above is the one reported.
        summary_report["realtime"] = realtime;
        writeRecording(o.record_path, qs_bodies, fall.frames, settle, fall, summary_report, status, error);
    }

    // ---- The reference's own pieces, settled in Jolt, as a second recording. -
    if (reference.ran && !o.record_reference_path.empty()) {
        const auto start = Clock::now();
        SettleStage ref_settle = runSettle(scene, o, bars, reference.matter, reference.ball, fall.contact_time + reference.simulated_s, reference.summary.broken);
        Json ref_report{{"fracture_count", reference.summary.broken}, {"broken_bonds", reference.summary.broken}, {"elapsed_s", ref_settle.end_time},
            {"wall_ms", 1000.0 * (fall.wall + reference.wall_s + ref_settle.wall)}, {"mass_kg", scene.asset.total_mass_kg},
            {"energy_j", qsr.kinetic_energy_in_j}, {"status", reference.completed ? "complete" : "solver_limit"},
            {"components", reference.summary.components}, {"lane", "dynamic implicit reference"},
            {"reference_wall_s", reference.wall_s}, {"reference_simulated_s", reference.simulated_s},
            {"realtime", {{"simulated_s", ref_settle.end_time}, {"wall_with_recording_s", fall.wall + reference.wall_s + ref_settle.wall},
                          {"ratio_with_recording", (fall.wall + reference.wall_s + ref_settle.wall) / ref_settle.end_time}}}};
        Json bodies = static_bodies;
        for (const Json &body : ref_settle.bodies) bodies.push_back(body);
        writeRecording(o.record_reference_path, bodies, fall.frames, ref_settle, fall, ref_report,
            reference.completed ? "complete" : "solver_limit", reference.completed ? "" : "reference stopped: " + reference.failure);
        report["reference_settle"] = settleJson(ref_settle);
        report["reference_settle"]["recording_wall_s"] = seconds(start);
    }
    report["process_wall_s"] = seconds(total_start);
    if (!o.report_path.empty()) {
        std::ofstream out(o.report_path, std::ios::binary);
        if (!out) throw std::runtime_error("cannot write report");
        out << report.dump(1);
    }

    std::cout << std::setprecision(6);
    std::cout << "scene: " << o.cells_x << "x" << o.cells_y << "x" << o.cells_z << " " << materialPresetName(o.tile) << " cells of " << o.cell_m
              << " m (" << scene.asset.nodes.size() << " nodes, " << scene.asset.bonds.size() << " bonds), iron ball r=" << o.ball_radius_m
              << " m dropped " << o.drop_m << " m, contact at " << fall.contact_time << " s, " << length(fall.contact.linear_velocity_m_s) << " m/s\n";
    std::cout << "quasistatic: stop=" << quasiStaticStopName(qsr.stop) << " events=" << qsr.events << " rounds=" << qsr.rounds
              << " solves=" << qsr.static_solves << " pcg_iterations=" << qsr.linear_iterations << " broken=" << qs_summary.broken
              << "/" << scene.asset.bonds.size() << " pieces=" << qs_summary.components << " frozen=" << qsr.frozen_components
              << " largest_mass_fraction=" << qs_summary.largest_mass_fraction << " travel_m=" << qsr.travel_m << "\n";
    std::cout << "ledger: KE_in=" << qsr.kinetic_energy_in_j << " work=" << qsr.ball_work_j << " KE_out=" << qsr.kinetic_energy_out_j
              << " stored=" << qsr.stored_elastic_j << " removed=" << qsr.removed_bond_energy_j << " (linear " << qsr.removed_bond_energy_linear_j
              << ") released=" << qsr.released_energy_j << " relaxation=" << qsr.relaxation_energy_j
              << " closure=" << closure << " segment_mismatch=" << qsr.segment_work_mismatch_j
              << " required_friction=" << qsr.required_friction_coefficient << " pinned_mechanisms=" << qsr.pinned_mechanism_directions
              << "+" << qsr.pinned_mechanism_modes << "\n";
    std::cout << "first failure: " << qsr.first_failure_bonds.size() << " bond(s) at travel " << qsr.first_failure_travel_m << " m, force "
              << qsr.first_failure_force_n << " N, mean radial " << report["quasistatic"]["first_failure"]["mean_radial_distance_m"].get<double>()
              << " m, mean layer " << report["quasistatic"]["first_failure"]["mean_layer"].get<double>() << "\n";
    if (reference.ran) {
        std::cout << "reference: dt=" << reference.dt_s << " (" << reference.dt_over_limit << "x lattice limit) steps=" << reference.steps
                  << " simulated=" << reference.simulated_s << " s wall=" << reference.wall_s << " s (" << reference.wall_s / std::max(reference.simulated_s, 1e-300)
                  << "x realtime) completed=" << reference.completed << " failure='" << reference.failure << "' broken=" << reference.summary.broken
                  << " pieces=" << reference.summary.components << " largest_mass_fraction=" << reference.summary.largest_mass_fraction
                  << " removed=" << reference.removed_energy_j << " first_failure_t=" << reference.first_failure_time_s
                  << " last_failure_t=" << reference.last_failure_time_s << " trials=" << reference.solver_trials << " discarded=" << reference.discarded_trials
                  << " ball_v_y=" << reference.ball.linear_velocity_m_s.y << "\n";
        const Json &cmp = report["comparison"];
        std::cout << "comparison: broken_jaccard=" << cmp["broken_bond_jaccard"].get<double>() << " damage_correlation=" << cmp["node_damage_correlation"].get<double>()
                  << " first_failure_jaccard=" << cmp["first_failure_jaccard"].get<double>() << " crack_centroid_distance=" << cmp["crack_centroid_distance_m"].get<double>()
                  << " gyration=[" << cmp["crack_radius_of_gyration_m"][0].get<double>() << "," << cmp["crack_radius_of_gyration_m"][1].get<double>() << "]\n";
        if (report.contains("reference_settle")) {
            const Json &rs = report["reference_settle"];
            std::cout << "reference settle: pieces=" << rs["pieces"].get<std::size_t>() << " settled=" << rs["settled"].get<bool>() << " after "
                      << rs["simulated_s"].get<double>() << " s, piece KE in " << rs["piece_kinetic_energy_in_j"].get<double>() << " J, wall " << rs["wall_s"].get<double>() << " s\n";
        }
    }
    std::cout << "settle: pieces=" << settle.pieces << " (" << settle.box_pieces << " boxes, " << settle.compound_pieces << " compounds, " << settle.hull_fallbacks
              << " hull fallbacks) settled=" << settle.settled << " after " << settle.simulated << " s, final max speed " << settle.final_speed << " m/s\n";
    std::cout << "realtime: simulated=" << simulated_total << " s wall=" << wall_total << " s ratio=" << wall_total / simulated_total
              << " (fall " << fall.wall << ", fracture " << stage2_wall << ", settle " << settle.wall << ", recording " << write_wall
              << ") rule_1.1x=" << (wall_total / simulated_total <= 1.1 ? "MET" : "NOT MET") << " frames=" << fall.frames.size() + settle.frames.size() << "\n";
    return qsr.converged ? 0 : 2;
}

} // namespace

int main(int argc, char **argv) {
    try {
        return run(parse(argc, argv));
    } catch (const std::exception &error) {
        std::cerr << "quasistatic probe error: " << error.what() << '\n';
        return 1;
    }
}
