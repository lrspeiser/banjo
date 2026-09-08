// banjo_fracture_algo1: Algorithm 1 of the fracture-lane comparison.
//
// A glass plate of uniform cubic cells, supported on two ledges or clamped at
// its edges, struck by an iron ball. The plate's impulse-response library is
// computed once at object creation and cached on disk; an impact is then
// answered from it -- one matrix-vector product says whether anything can break
// and from when, and the cascade advances by Woodbury crack updates that never
// touch an eigenvector. Pieces are the connected components left behind; they
// are handed to Jolt to fall and settle, and the interaction is written as a
// banjo.playback.v1 recording the playground's 3D tab plays.
//
// `--reference` runs the explicit lattice (fastlattice, CPU, double) on the
// same scene instead, so the two lanes can be compared from one command.
//
// Nothing here precuts shards, animates a shatter, applies an explosion impulse
// or authors a fragment velocity. The failure criterion is fracture/BondFailure
// unchanged.

#include "algo1/CrackCascade.hpp"
#include "algo1/ImpulseLibrary.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "fracture/BondFailure.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentMassProperties.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"
#include "rigid/JoltWorld.hpp"

#include <nlohmann/json.hpp>

#ifdef _OPENMP
#include <omp.h>
#endif

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <numbers>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>

namespace {

using Json = nlohmann::json;
using namespace banjo;
using Clock = std::chrono::steady_clock;

double since(Clock::time_point start) { return std::chrono::duration<double>(Clock::now() - start).count(); }

void require(bool condition, const std::string &message) {
    if (!condition) throw std::runtime_error(message);
}

constexpr double kGravity = 9.81;
constexpr double kRealtimeLimit = 1.1;
constexpr std::uint64_t kMaterialSeed = 971;   // the reference lane's default
constexpr unsigned kHorizon = 2;
constexpr double kLedgeWidth = 0.04;
constexpr double kLedgeHeight = 0.12;
constexpr double kBallGap = 0.002;

struct Options {
    double plate[3]{0.25, 0.20, 0.01};
    double cell_m{0.01};
    double ball_diameter_m{0.06};
    double drop_m{2.0};
    double speed_m_s{-1.0};
    double offset_x{}, offset_z{};
    std::string support{"ledges"};
    double duration_s{2.0};
    std::string output;
    std::filesystem::path cache{"build/fracture-cache"};
    bool reference{false};
    // Lane controls, all reported.
    std::string material{"glass"};
    double window_s{6.0e-3};
    double sample_dt_s{1.0e-6};
    double damping_ratio{0.0};
    std::string contact{"tracked"};
    double restitution{0.0};
    double quiet_s{1.5e-3};
    std::size_t compliance_budget_mb{1024};
    unsigned frames{240};
    bool no_cache{false};
    unsigned max_bodies{200};
    // Dense products are memory-bound; more threads than this only contend,
    // and other lanes share this machine. 0 leaves OpenMP's own default.
    unsigned threads{6};
    double schur_floor{1.0e-3};
    double correction_cap_m{2.0e-2};
    std::size_t maximum_released{512};
};

double number(const std::string &value) {
    std::size_t used = 0;
    const double result = std::stod(value, &used);
    if (used != value.size() || !std::isfinite(result)) throw std::runtime_error("bad number: " + value);
    return result;
}

MaterialPreset presetFromName(std::string_view name) {
    if (name == "glass") return MaterialPreset::Glass;
    if (name == "oak") return MaterialPreset::Oak;
    if (name == "iron") return MaterialPreset::Iron;
    if (name == "concrete") return MaterialPreset::Concrete;
    if (name == "ceramic") return MaterialPreset::Ceramic;
    if (name == "ice") return MaterialPreset::Ice;
    throw std::runtime_error("unknown material: " + std::string(name));
}

void usage() {
    std::cout <<
        "usage: banjo_fracture_algo1 [options]\n"
        "  --plate L W T          plate length, width, thickness in metres\n"
        "  --cell H               uniform cubic cell size in metres\n"
        "  --ball D               ball diameter in metres\n"
        "  --drop H | --speed V   drop height or impact speed\n"
        "  --offset X Z           strike offset from the plate centre\n"
        "  --support ledges|clamped\n"
        "  --duration S           simulated seconds through settling (default 2)\n"
        "  --output PATH          banjo.playback.v1 recording\n"
        "  --cache DIR            precompute cache (default build/fracture-cache)\n"
        "  --reference            run the explicit lattice on the same scene instead\n"
        "  --material glass|oak|iron   plate material (default glass)\n"
        "  --contact tracked|impulse   contact model (default tracked)\n"
        "  --window S --sample-dt S --zeta Z --quiet S --restitution E\n"
        "  --compliance-mb N --frames N --no-cache --max-bodies N\n";
}

Options parse(int argc, char **argv) {
    Options o;
    bool have_speed = false, have_drop = false;
    for (int i = 1; i < argc; ++i) {
        const std::string_view option = argv[i];
        const auto value = [&]() -> std::string {
            if (++i >= argc) throw std::runtime_error("missing value for " + std::string(option));
            return argv[i];
        };
        if (option == "--help" || option == "-h") { usage(); std::exit(0); }
        else if (option == "--plate") { o.plate[0] = number(value()); o.plate[1] = number(value()); o.plate[2] = number(value()); }
        else if (option == "--cell") o.cell_m = number(value());
        else if (option == "--ball") o.ball_diameter_m = number(value());
        else if (option == "--drop") { o.drop_m = number(value()); have_drop = true; }
        else if (option == "--speed") { o.speed_m_s = number(value()); have_speed = true; }
        else if (option == "--offset") { o.offset_x = number(value()); o.offset_z = number(value()); }
        else if (option == "--support") o.support = value();
        else if (option == "--duration") o.duration_s = number(value());
        else if (option == "--output") o.output = value();
        else if (option == "--cache") o.cache = value();
        else if (option == "--reference") o.reference = true;
        else if (option == "--material") o.material = value();
        else if (option == "--contact") o.contact = value();
        else if (option == "--window") o.window_s = number(value());
        else if (option == "--sample-dt") o.sample_dt_s = number(value());
        else if (option == "--zeta") o.damping_ratio = number(value());
        else if (option == "--quiet") o.quiet_s = number(value());
        else if (option == "--restitution") o.restitution = number(value());
        else if (option == "--compliance-mb") o.compliance_budget_mb = static_cast<std::size_t>(number(value()));
        else if (option == "--frames") o.frames = static_cast<unsigned>(number(value()));
        else if (option == "--no-cache") o.no_cache = true;
        else if (option == "--max-bodies") o.max_bodies = static_cast<unsigned>(number(value()));
        else if (option == "--threads") o.threads = static_cast<unsigned>(number(value()));
        else if (option == "--schur-floor") o.schur_floor = number(value());
        else if (option == "--correction-cap") o.correction_cap_m = number(value());
        else if (option == "--max-released") o.maximum_released = static_cast<std::size_t>(number(value()));
        else throw std::runtime_error("unknown option: " + std::string(option));
    }
    if (have_speed && o.speed_m_s >= 0.0) o.drop_m = o.speed_m_s * o.speed_m_s / (2.0 * kGravity);
    else o.speed_m_s = std::sqrt(2.0 * kGravity * o.drop_m);
    (void)have_drop;
    require(o.support == "ledges" || o.support == "clamped", "--support must be ledges or clamped");
    require(o.contact == "tracked" || o.contact == "impulse", "--contact must be tracked or impulse");
    require(o.cell_m > 0.0 && o.duration_s > 0.0, "cell size and duration must be positive");
    return o;
}

unsigned cellsAlong(double extent, double cell, const char *axis) {
    const double count = extent / cell;
    const double rounded = std::round(count);
    require(rounded >= 1.0 && std::abs(count - rounded) <= 1.0e-6 * std::max(1.0, rounded),
            std::string("the plate's ") + axis + " extent must be a whole number of uniform cubic cells");
    return static_cast<unsigned>(rounded);
}

// ---- scene ------------------------------------------------------------------

struct Scene {
    LatticeAsset asset;
    ActiveMatter matter;
    CompiledBrittleMaterial compiled;
    MaterialDefinition plate_material, ball_material, ground_material;
    std::vector<std::uint8_t> dof_free;
    std::vector<char> held_node;      // a cell the support holds in every axis
    std::vector<char> supported_node; // a cell resting on a ledge
    algo1::Ball ball;
    unsigned nx{}, ny{}, nz{};
    double tile_bottom_y{}, tile_top_y{};
    std::vector<fastlattice::StaticBox> ledges;
};

Scene buildScene(const Options &o) {
    Scene s;
    s.nx = cellsAlong(o.plate[0], o.cell_m, "length");
    s.nz = cellsAlong(o.plate[1], o.cell_m, "width");
    s.ny = cellsAlong(o.plate[2], o.cell_m, "thickness");
    const MaterialPreset preset = presetFromName(o.material);
    s.plate_material = makeReferenceMaterial(preset, kMaterialSeed);
    s.ball_material = makeReferenceMaterial(MaterialPreset::Iron, kMaterialSeed);
    s.ground_material = makeReferenceMaterial(MaterialPreset::Concrete, kMaterialSeed);
    s.compiled = withStrengthDerivedFailure(
        compileElasticLatticeReference(s.plate_material, o.cell_m, kHorizon), s.plate_material);
    s.asset = generateBoxLattice({s.nx, s.ny, s.nz, o.cell_m, kHorizon}, s.compiled);

    s.tile_bottom_y = o.support == "ledges" ? kLedgeHeight : kLedgeHeight;
    s.tile_top_y = s.tile_bottom_y + o.plate[2];
    const Vec3 centre{0.0, s.tile_bottom_y + 0.5 * o.plate[2], 0.0};
    s.matter.body_id = 2;
    s.matter.asset = &s.asset;
    s.matter.material = s.compiled;
    for (const LatticeNodeRest &node : s.asset.nodes) {
        const Vec3 position = centre + (node.local_position_m - s.asset.rest_center_of_mass_m);
        s.matter.nodes.push_back({position, position, {}, node.represented_volume_m3 * s.compiled.density_kg_m3, {}});
        s.matter.reference_positions_world_m.push_back(position);
    }
    s.matter.bonds.resize(s.asset.bonds.size());

    if (o.support == "ledges") {
        // Ledges under the ends of the long (x) axis, half under the plate,
        // spanning the whole width: the reference lane's bridge layout.
        const double depth = o.plate[1] + 2.0 * o.cell_m;
        for (const double sign : {-1.0, 1.0})
            s.ledges.push_back({{sign * 0.5 * o.plate[0], 0.5 * kLedgeHeight, 0.0},
                                {2.0 * kLedgeWidth, kLedgeHeight, depth}});
    }

    s.dof_free.assign(3U * s.asset.nodes.size(), 1U);
    s.held_node.assign(s.asset.nodes.size(), 0);
    s.supported_node.assign(s.asset.nodes.size(), 0);
    for (std::uint32_t node = 0; node < s.asset.nodes.size(); ++node) {
        const GridCoord grid = s.asset.nodes[node].grid;
        if (o.support == "clamped") {
            const bool held = grid.x == 0 || grid.z == 0 || grid.x + 1 == static_cast<int>(s.nx) ||
                              grid.z + 1 == static_cast<int>(s.nz);
            if (!held) continue;
            s.held_node[node] = 1;
            for (unsigned axis = 0; axis < 3U; ++axis) s.dof_free[3U * node + axis] = 0U;
        } else {
            // A cell whose footprint sits over a ledge, in the bottom layer.
            if (grid.y != 0) continue;
            const double x = s.matter.reference_positions_world_m[node].x;
            if (std::abs(x) < 0.5 * o.plate[0] - kLedgeWidth) continue;
            s.supported_node[node] = 1;
            s.dof_free[3U * node + 1U] = 0U;  // held in y only: the ledge is frictionless
        }
    }

    s.ball.radius_m = 0.5 * o.ball_diameter_m;
    s.ball.contact_radius_m = s.ball.radius_m + 0.5 * o.cell_m;
    s.ball.mass_kg = s.ball_material.density_kg_m3 * 4.0 / 3.0 * std::numbers::pi *
                     std::pow(s.ball.radius_m, 3.0);
    s.ball.center_m = {o.offset_x, s.tile_top_y + s.ball.radius_m + kBallGap, o.offset_z};
    s.ball.velocity_m_s = {0.0, -o.speed_m_s, 0.0};
    return s;
}

// ---- handoff: components become rigid bodies --------------------------------

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
    const auto local = [&](double x, double y, double z) {
        const auto &first = asset.nodes.front();
        const Vec3 origin = first.local_position_m -
            Vec3{(first.grid.x + 0.5) * h, (first.grid.y + 0.5) * h, (first.grid.z + 0.5) * h};
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
    std::vector<std::uint32_t> nodes;
    Vec3 rest_center{};
};

struct Handoff {
    std::vector<HandoffBody> bodies;
    std::vector<std::uint32_t> component_of_node;
    std::size_t fragments{}, static_components{}, unsimulated_components{}, parts{};
    double coarsening_loss_j{}, fragment_kinetic_j{}, largest_fragment_mass_kg{};
};

Handoff handToJolt(JoltWorld &rigid, Scene &scene, const Options &o, const Vec3 &plate_offset) {
    Handoff h;
    auto components = findConnectedComponents(scene.matter);
    h.component_of_node.assign(scene.matter.nodes.size(), 0U);
    for (const auto &c : components) for (const auto node : c.node_indices) h.component_of_node[node] = c.id;
    MatterBodyId next_dynamic = 1000, next_static = 100000;
    unsigned budget = o.max_bodies;
    for (const auto &c : components) {
        bool has_held = false;
        for (const auto node : c.node_indices) has_held = has_held || scene.held_node[node] != 0;
        const auto boxes = mergeCells(scene.asset, c.node_indices, o.cell_m);
        Vec3 rest_center{};
        for (const auto node : c.node_indices) rest_center += scene.matter.reference_positions_world_m[node];
        rest_center = rest_center / static_cast<double>(c.node_indices.size());
        HandoffBody body;
        body.nodes = c.node_indices;
        body.rest_center = rest_center;
        if (boxes.size() > 64 || budget == 0) {
            // Jolt compounds take 64 parts and the world takes a few hundred
            // bodies. A piece past either limit stays where the window left it
            // and is counted, not silently dropped or merged into another.
            ++h.unsimulated_components;
            body.dynamic = false;
            body.id = 0;
            h.bodies.push_back(std::move(body));
            continue;
        }
        --budget;
        h.parts += boxes.size();
        if (has_held) {
            ++h.static_components;
            body.dynamic = false;
            body.id = next_static;
            for (const auto &box : boxes) {
                RigidBoxDescription description;
                description.body_id = next_static++;
                description.dimensions_m = box.dimensions;
                description.material = scene.plate_material;
                description.state.center_of_mass_world_m = box.center_rest_local + plate_offset;
                description.fixed = true;
                rigid.addBox(description);
            }
        } else {
            ++h.fragments;
            const auto properties = calculateFragmentMassProperties(scene.matter, c.node_indices);
            h.coarsening_loss_j += properties.coarsening_kinetic_loss_j;
            h.fragment_kinetic_j += properties.rigid_kinetic_energy_j;
            h.largest_fragment_mass_kg = std::max(h.largest_fragment_mass_kg, properties.mass_kg);
            RigidCompoundDescription description;
            description.body_id = next_dynamic++;
            description.material = scene.plate_material;
            for (const auto &box : boxes) {
                RigidPrimitive geometry;
                geometry.kind = PrimitiveKind::Box;
                geometry.dimensions_m = box.dimensions;
                description.parts.push_back({geometry, box.center_rest_local + plate_offset - rest_center});
            }
            description.state.center_of_mass_world_m = properties.center_of_mass_world_m;
            description.state.linear_velocity_m_s = properties.linear_velocity_m_s;
            description.state.angular_velocity_rad_s = properties.angular_velocity_rad_s;
            description.mass_kg = properties.mass_kg;
            description.inertia_local_kg_m2 = properties.inertia_world_kg_m2;
            rigid.addCompound(description);
            body.dynamic = true;
            body.id = description.body_id;
        }
        h.bodies.push_back(std::move(body));
    }
    return h;
}

// ---- recording ---------------------------------------------------------------

Json vec(const Vec3 &v) { return Json{v.x, v.y, v.z}; }
Json quat(const Quat &q) { return Json{q.w, q.x, q.y, q.z}; }

struct SettleFrame {
    double time_s{};
    std::vector<Vec3> positions;
    std::vector<Quat> orientations;
    Vec3 ball_center{};
    Quat ball_orientation{};
};

} // namespace

int main(int argc, char **argv) {
    try {
        const Options o = parse(argc, argv);
#ifdef _OPENMP
        if (o.threads > 0) omp_set_num_threads(static_cast<int>(o.threads));
#endif
        const auto wall_start = Clock::now();

        if (o.reference) {
            // The explicit lattice on the same scene, CPU backend, double.
            require(o.support == "ledges", "the reference lane supports the plate on two ledges only");
            fastlattice::TileImpactRequest request;
            request.tile_material = presetFromName(o.material);
            request.ball_material = MaterialPreset::Iron;
            request.tile_dimensions_m = {o.plate[0], o.plate[2], o.plate[1]};
            request.cell_size_m = o.cell_m;
            request.neighbor_horizon_cells = kHorizon;
            request.ball_radius_m = 0.5 * o.ball_diameter_m;
            request.ball_speed_m_s = o.speed_m_s;
            request.ball_gap_m = kBallGap;
            request.ball_offset_x_m = o.offset_x;
            request.ball_offset_z_m = o.offset_z;
            request.layout = fastlattice::SceneLayout::Bridge;
            request.ledge_width_m = kLedgeWidth;
            request.ledge_height_m = kLedgeHeight;
            request.backend = fastlattice::BackendKind::Cpu;
            request.precision = fastlattice::Precision::Double;
            request.settle_limit_s = o.duration_s;
            request.material_seed = kMaterialSeed;
            std::string log;
            fastlattice::TileImpactResult result = fastlattice::runTileImpact(request, &log);
            const auto &m = result.measurements;
            // The reference's first-failure *set*, which runTileImpact does not
            // report: rerun the lattice phase alone, stopped one substep after
            // the failure step the full run found, and read the bonds dead in
            // its handoff frame. The lane is deterministic, so this reproduces
            // the same first round; it costs a few hundred substeps.
            std::vector<std::uint32_t> first_failure_bonds;
            if (m.first_failure_s > 0.0 && m.dt_s > 0.0) {
                fastlattice::TileImpactRequest probe = request;
                probe.quiet_ms = 0.0;
                probe.min_ms = 0.0;
                probe.no_failure_ms = 0.0;
                probe.max_ms = 1000.0 * (m.first_failure_s + 0.5 * m.dt_s);
                probe.settle_limit_s = 0.0;
                probe.lattice_frames = 1;
                probe.rigid_frames = 1;
                std::string probe_log;
                const fastlattice::TileImpactResult probe_result = fastlattice::runTileImpact(probe, &probe_log);
                for (auto frame = probe_result.frames.rbegin(); frame != probe_result.frames.rend(); ++frame) {
                    if (frame->phase != "lattice" || frame->bond_alive.empty()) continue;
                    for (std::uint32_t bond = 0; bond < frame->bond_alive.size(); ++bond)
                        if (frame->bond_alive[bond] == 0U) first_failure_bonds.push_back(bond);
                    break;
                }
            }
            if (!o.output.empty()) {
                fastlattice::writePlayback(result, o.output);
                Json artifact = Json::parse(std::ifstream(o.output, std::ios::binary));
                Json &report = artifact["report"];
                report["lane"] = "reference-explicit-lattice";
                report["cells"] = m.cells;
                report["bonds"] = m.bonds;
                report["precompute_s"] = 0.0;
                report["precompute_cached"] = false;
                report["precompute_bytes"] = 0;
                report["compute_wall_s"] = m.wall_total_s;
                report["simulated_s"] = m.simulated_total_s;
                report["realtime"] = {{"ratio", m.realtime_ratio}, {"simulated_s", m.simulated_total_s},
                                      {"compute_wall_s", m.wall_total_s},
                                      {"fracture_window_ratio", m.lattice_simulated_s > 0.0 ? m.lattice_wall_s / m.lattice_simulated_s : 0.0},
                                      {"window_simulated_s", m.lattice_simulated_s}, {"limit", kRealtimeLimit}};
                report["contact"] = {{"impulse_n_s", length(Vec3{m.contact.impulse_to_material_x,
                                                                 m.contact.impulse_to_material_y,
                                                                 m.contact.impulse_to_material_z})},
                                     {"model", "explicit per-substep sphere contact against every node (fastlattice)"}};
                report["first_failure"] = {{"time_s", m.first_failure_s}, {"bond_indices", first_failure_bonds}};
                report["rounds"] = m.failure_rounds;
                report["broken_bonds"] = m.broken_bonds;
                report["components"] = m.components;
                report["largest_component_cells"] = m.largest_piece_cells;
                report["largest_component_mass_kg"] = m.largest_piece_mass_kg;
                report["removed_energy_j"] = m.removed_energy_j;
                report["screen"] = {{"candidate_bonds", nullptr}, {"wall_s", 0.0}};
                std::ofstream out(o.output, std::ios::binary);
                const std::string text = artifact.dump();
                out.write(text.data(), static_cast<std::streamsize>(text.size()));
            }
            Json summary{{"lane", "reference-explicit-lattice"}, {"cells", m.cells}, {"bonds", m.bonds},
                         {"broken_bonds", m.broken_bonds}, {"rounds", m.failure_rounds},
                         {"first_failure_s", m.first_failure_s},
                         {"first_failure_bonds", first_failure_bonds.size()}, {"components", m.components},
                         {"largest_component_cells", m.largest_piece_cells},
                         {"removed_energy_j", m.removed_energy_j},
                         {"compute_wall_s", m.wall_total_s}, {"simulated_s", m.simulated_total_s},
                         {"ratio", m.realtime_ratio}, {"output", o.output}};
            std::cout << summary.dump() << '\n';
            return 0;
        }

        // ---- scene and library ------------------------------------------------
        const auto scene_start = Clock::now();
        Scene scene = buildScene(o);
        const double scene_wall = since(scene_start);
        const std::size_t cells = scene.matter.nodes.size();
        const std::size_t bonds = scene.matter.bonds.size();

        const auto precompute_start = Clock::now();
        algo1::LibraryOptions library_options;
        library_options.compliance_budget_bytes = o.compliance_budget_mb * 1024ULL * 1024ULL;
        const std::string key = algo1::libraryKey(o.material, scene.nx, scene.ny, scene.nz, o.cell_m,
                                                  kHorizon, kMaterialSeed, o.support, kLedgeWidth);
        const algo1::ImpulseLibrary library = algo1::ImpulseLibrary::create(
            scene.matter, scene.dof_free, library_options, key, o.no_cache ? std::filesystem::path{} : o.cache);
        const double precompute_wall = since(precompute_start);
        const algo1::LibraryStats &stats = library.stats();

        // ---- the window -------------------------------------------------------
        const auto compute_start = Clock::now();
        algo1::CascadeSettings settings;
        settings.sample_dt_s = o.sample_dt_s;
        settings.window_s = o.window_s;
        settings.damping_ratio = o.damping_ratio;
        settings.contact = o.contact == "impulse" ? algo1::ContactModel::SingleImpulse
                                                  : algo1::ContactModel::Tracked;
        settings.restitution = o.restitution;
        settings.quiet_s = o.quiet_s;
        settings.cell_m = o.cell_m;
        settings.maximum_frames = o.frames;
        settings.schur_floor = o.schur_floor;
        settings.correction_cap_m = o.correction_cap_m;
        settings.maximum_released = o.maximum_released;
        algo1::Ball ball = scene.ball;
        algo1::CascadeResult cascade = algo1::runCrackCascade(scene.matter, library, ball, settings);

        // ---- pieces fall and settle -------------------------------------------
        const Vec3 plate_offset{0.0, scene.tile_bottom_y + 0.5 * o.plate[2], 0.0};
        std::vector<SettleFrame> settle_frames;
        double settle_wall = 0.0, settle_simulated = 0.0, handoff_wall = 0.0;
        double settled_at = -1.0;
        Handoff handoff;
        std::size_t rigid_steps = 0;
        {
            const auto handoff_start = Clock::now();
            JoltWorld rigid(0);
            rigid.addFloor();
            MatterBodyId next_static_support = 900000;
            for (const auto &ledge : scene.ledges) {
                RigidBoxDescription description;
                description.body_id = next_static_support++;
                description.dimensions_m = ledge.dimensions_m;
                description.material = scene.ground_material;
                description.state.center_of_mass_world_m = ledge.center_m;
                description.fixed = true;
                rigid.addBox(description);
            }
            RigidBallDescription ball_body;
            ball_body.body_id = 2;
            ball_body.radius_m = ball.radius_m;
            ball_body.material = scene.ball_material;
            ball_body.position_world_m = ball.center_m;
            ball_body.linear_velocity_m_s = ball.velocity_m_s;
            rigid.addBall(ball_body);
            handoff = handToJolt(rigid, scene, o, plate_offset);
            handoff_wall = since(handoff_start);

            const auto settle_start = Clock::now();
            std::vector<MatterBodyId> dynamic_ids{2};
            for (const auto &body : handoff.bodies) if (body.dynamic) dynamic_ids.push_back(body.id);
            const double rigid_dt = 1.0 / 240.0;
            const double frame_dt = 1.0 / 60.0;
            const double limit = std::max(0.0, o.duration_s - cascade.simulated_s);
            const auto capture = [&](double time) {
                SettleFrame frame;
                frame.time_s = cascade.simulated_s + time;
                frame.positions.resize(scene.matter.nodes.size());
                frame.orientations.assign(scene.matter.nodes.size(), Quat{1.0, 0.0, 0.0, 0.0});
                for (const auto &body : handoff.bodies) {
                    if (!body.dynamic) {
                        for (const auto node : body.nodes)
                            frame.positions[node] = body.id == 0 ? scene.matter.nodes[node].position_world_m
                                                                 : scene.matter.reference_positions_world_m[node];
                        continue;
                    }
                    const auto snap = rigid.snapshot(body.id);
                    for (const auto node : body.nodes) {
                        frame.positions[node] = snap.center_of_mass_world_m +
                            snap.orientation_world.rotate(scene.matter.reference_positions_world_m[node] - body.rest_center);
                        frame.orientations[node] = snap.orientation_world;
                    }
                }
                const auto ball_snap = rigid.snapshot(2);
                frame.ball_center = ball_snap.center_of_mass_world_m;
                frame.ball_orientation = ball_snap.orientation_world;
                settle_frames.push_back(std::move(frame));
            };
            double time = 0.0, at_rest_for = 0.0, last_frame = 0.0;
            capture(0.0);
            while (time < limit - 1.0e-12) {
                rigid.step(rigid_dt);
                time += rigid_dt;
                ++rigid_steps;
                double speed = 0.0, spin = 0.0;
                for (const auto id : dynamic_ids) {
                    const auto snap = rigid.snapshot(id);
                    speed = std::max(speed, length(snap.linear_velocity_m_s));
                    spin = std::max(spin, length(snap.angular_velocity_rad_s));
                }
                if (speed < 0.01 && spin < 0.1) at_rest_for += rigid_dt; else at_rest_for = 0.0;
                if (time - last_frame >= frame_dt - 1.0e-12) { capture(time); last_frame = time; }
                if (at_rest_for >= 0.3) { settled_at = time - at_rest_for; break; }
            }
            if (last_frame < time) capture(time);
            settle_wall = since(settle_start);
            settle_simulated = time;
        }
        const double compute_wall = since(compute_start);
        const double simulated = cascade.simulated_s + settle_simulated;

        // ---- report ------------------------------------------------------------
        std::vector<std::uint32_t> broken;
        for (std::uint32_t b = 0; b < scene.matter.bonds.size(); ++b)
            if (!scene.matter.bonds[b].alive) broken.push_back(b);
        Json rounds = Json::array();
        for (const auto &round : cascade.rounds)
            rounds.push_back({{"time_s", round.time_s}, {"bonds", round.bonds},
                              {"removed_energy_j", round.removed_energy_j},
                              {"released_total", round.released_total},
                              {"components_after", round.components_after},
                              {"update_wall_s", round.update_wall_s},
                              {"largest_correction_m", round.largest_correction_m}});
        const auto counts = countBondFailureModes(scene.matter);
        Json report{
            {"lane", "algo1-impulse-woodbury"},
            {"status", "complete"},
            {"physical_response_validated", false},
            {"cells", cells},
            {"bonds", bonds},
            {"precompute_s", precompute_wall},
            {"precompute_cached", stats.cached},
            {"precompute_bytes", stats.cache_bytes},
            {"compute_wall_s", compute_wall},
            {"simulated_s", simulated},
            {"realtime", {{"ratio", simulated > 0.0 ? compute_wall / simulated : 0.0},
                          {"simulated_s", simulated},
                          {"compute_wall_s", compute_wall},
                          {"fracture_window_ratio", cascade.simulated_s > 0.0
                               ? (cascade.timings.total_s) / cascade.simulated_s : 0.0},
                          {"window_simulated_s", cascade.simulated_s},
                          {"limit", kRealtimeLimit}}},
            {"contact", {{"impulse_n_s", cascade.contact.impulse_n_s},
                         {"model", cascade.contact.model},
                         {"axial_impulse_n_s", cascade.contact.axial_impulse_n_s},
                         {"scalar_impulse_n_s", cascade.contact.total_impulse_magnitude_n_s},
                         {"cells_touched", cascade.contact.contact_nodes},
                         {"events", cascade.contact.events},
                         {"duration_s", cascade.contact.duration_s},
                         {"maximum_penetration_m", cascade.contact.maximum_penetration_m},
                         {"penetration_recovery", settings.penetration_recovery},
                         {"penetration_recovery_speed_fraction", settings.penetration_recovery_speed_fraction},
                         {"largest_node_displacement_m", cascade.contact.largest_node_displacement_m},
                         {"ball_speed_end_m_s", cascade.contact.ball_speed_end_m_s},
                         {"wall_s", cascade.contact.wall_s}}},
            {"first_failure", cascade.first_failure_time_s < 0.0
                 ? Json{{"time_s", nullptr}, {"bond_indices", Json::array()}}
                 : Json{{"time_s", cascade.first_failure_time_s}, {"bond_indices", cascade.first_failure_bonds}}},
            {"rounds", cascade.rounds.size()},
            {"broken_bonds", cascade.broken_bonds},
            {"components", cascade.components},
            {"largest_component_cells", cascade.largest_component_cells},
            {"largest_component_mass_kg", cascade.largest_component_mass_kg},
            {"removed_energy_j", cascade.removed_energy_j},
            {"screen", {{"candidate_bonds", cascade.screen.candidate_bonds},
                        {"wall_s", cascade.screen.wall_s},
                        {"bonds_screened", cascade.screen.bonds_screened},
                        {"anything_can_break", cascade.screen.anything_can_break},
                        {"earliest_possible_failure_s", cascade.screen.earliest_possible_failure_s},
                        {"largest_bound_over_threshold", cascade.screen.largest_bound_ratio}}},
            {"scene", {{"material", o.material}, {"plate_m", {o.plate[0], o.plate[1], o.plate[2]}},
                       {"cells_per_axis", {scene.nx, scene.nz, scene.ny}}, {"cell_m", o.cell_m},
                       {"support", o.support}, {"ledge_width_m", kLedgeWidth}, {"ledge_height_m", kLedgeHeight},
                       {"ball", {{"material", "iron"}, {"diameter_m", o.ball_diameter_m},
                                 {"contact_radius_m", scene.ball.contact_radius_m},
                                 {"mass_kg", scene.ball.mass_kg}, {"speed_m_s", o.speed_m_s},
                                 {"drop_m", o.drop_m}, {"gap_m", kBallGap}}},
                       {"offset_m", {o.offset_x, o.offset_z}},
                       {"plate_mass_kg", scene.asset.total_mass_kg}}},
            {"library", {{"dofs", stats.dofs}, {"modes", stats.modes},
                         {"rigid_modes", stats.rigid_modes}, {"mechanism_modes", stats.mechanism_modes},
                         {"assemble_s", stats.assemble_s}, {"decompose_s", stats.decompose_s},
                         {"amplitude_s", stats.amplitude_s}, {"compliance_s", stats.compliance_s},
                         {"cache_read_s", stats.cache_read_s}, {"cache_write_s", stats.cache_write_s},
                         {"phi_bytes", stats.phi_bytes}, {"amplitude_bytes", stats.amplitude_bytes},
                         {"compliance_bytes", stats.compliance_bytes},
                         {"compliance_stored", stats.compliance_stored},
                         {"cache_path", stats.cache_path},
                         {"omega_max_rad_s", stats.omega_max_rad_s},
                         {"omega_min_elastic_rad_s", stats.omega_min_elastic_rad_s},
                         {"fastest_period_s", stats.fastest_period_s},
                         {"threads", o.threads}}},
            {"window", {{"sample_dt_s", o.sample_dt_s}, {"window_s", o.window_s},
                        {"damping_ratio", o.damping_ratio}, {"quiet_s", o.quiet_s},
                        {"samples", cascade.samples}, {"skipped_samples", cascade.skipped_samples},
                        {"simulated_s", cascade.simulated_s},
                        {"singular_releases", cascade.singular_releases},
                        {"capped_releases", cascade.capped_releases},
                        {"released_bonds", cascade.released_bonds},
                        {"maximum_released", settings.maximum_released},
                        {"schur_floor", settings.schur_floor},
                        {"correction_cap_m", settings.correction_cap_m},
                        {"maximum_tensile_stretch", cascade.maximum_tensile_stretch},
                        {"maximum_compressive_strain", cascade.maximum_compressive_strain},
                        {"maximum_shear_strain", cascade.maximum_shear_strain},
                        {"tensile_break_strain", scene.compiled.damage_end_stretch},
                        {"shear_break_strain", scene.compiled.shear_damage_end_strain},
                        {"compression_break_strain", scene.compiled.compression_damage_end_strain}}},
            {"failure_modes", {{"tensile", counts.tensile}, {"compressive", counts.compressive},
                               {"shear", counts.shear}}},
            {"round_detail", rounds},
            {"broken_bond_indices", broken},
            {"handoff", {{"fragments", handoff.fragments}, {"static_components", handoff.static_components},
                         {"unsimulated_components", handoff.unsimulated_components},
                         {"collision_boxes", handoff.parts},
                         {"largest_fragment_mass_kg", handoff.largest_fragment_mass_kg},
                         {"fragment_rigid_kinetic_j", handoff.fragment_kinetic_j},
                         {"coarsening_kinetic_loss_j", handoff.coarsening_loss_j},
                         {"wall_s", handoff_wall}}},
            {"settle", {{"simulated_s", settle_simulated}, {"steps", rigid_steps},
                        {"settled", settled_at >= 0.0}, {"settled_time_s", settled_at},
                        {"wall_s", settle_wall}}},
            {"timings_s", {{"scene_build", scene_wall}, {"precompute", precompute_wall},
                           {"contact", cascade.timings.contact_s}, {"screen", cascade.timings.screen_s},
                           {"field", cascade.timings.field_s}, {"criterion", cascade.timings.criterion_s},
                           {"woodbury", cascade.timings.woodbury_s}, {"frames", cascade.timings.frames_s},
                           {"window_total", cascade.timings.total_s},
                           {"handoff", handoff_wall}, {"settle", settle_wall},
                           {"compute_total", compute_wall}}},
            {"elapsed_s", simulated},
            {"wall_ms", 1000.0 * compute_wall},
            {"mass_kg", scene.asset.total_mass_kg},
        };

        // ---- playback ----------------------------------------------------------
        double json_wall = 0.0;
        if (!o.output.empty()) {
            const auto json_start = Clock::now();
            const auto output_path = std::filesystem::absolute(o.output).lexically_normal();
            std::error_code code;
            std::filesystem::create_directories(output_path.parent_path(), code);
            Json bodies = Json::array();
            for (std::size_t i = 0; i < cells; ++i)
                bodies.push_back({{"id", "cell:" + std::to_string(i)}, {"object_id", 2}, {"element_id", i},
                                  {"material_id", o.material}, {"color_rgba", 0x9fd3ffffU},
                                  {"shape", "box"}, {"dimensions_m", Json{o.cell_m, o.cell_m, o.cell_m}}});
            bodies.push_back({{"id", "ball"}, {"object_id", 1}, {"element_id", 0}, {"material_id", "iron"},
                              {"color_rgba", 0x8a8f99ffU}, {"shape", "sphere"},
                              {"dimensions_m", Json{o.ball_diameter_m, o.ball_diameter_m, o.ball_diameter_m}}});
            for (std::size_t k = 0; k < scene.ledges.size(); ++k)
                bodies.push_back({{"id", "ledge:" + std::to_string(k)}, {"object_id", 900 + k}, {"element_id", 0},
                                  {"material_id", "concrete"}, {"color_rgba", 0x7a7a7affU}, {"shape", "box"},
                                  {"dimensions_m", vec(scene.ledges[k].dimensions_m)}});
            const double extent = 1.0;
            Json supports = Json::array();
            supports.push_back({vec({-extent, 0.0, -extent}), vec({extent, 0.0, -extent}), vec({extent, 0.0, extent})});
            supports.push_back({vec({-extent, 0.0, -extent}), vec({extent, 0.0, extent}), vec({-extent, 0.0, extent})});

            Json frames = Json::array();
            const std::size_t window_frames = cascade.frames.size();
            const std::size_t bond_stride = std::max<std::size_t>(1, (window_frames + 39) / 40);
            for (std::size_t index = 0; index < window_frames; ++index) {
                const auto &frame = cascade.frames[index];
                Json poses = Json::array();
                for (std::size_t node = 0; node < cells; ++node)
                    poses.push_back({{"id", "cell:" + std::to_string(node)}, {"position_m", vec(frame.positions[node])},
                                     {"orientation_wxyz", Json{1.0, 0.0, 0.0, 0.0}},
                                     {"component_id", frame.component[node]}});
                poses.push_back({{"id", "ball"}, {"position_m", vec(frame.ball_center)},
                                 {"orientation_wxyz", Json{1.0, 0.0, 0.0, 0.0}}, {"component_id", 0}});
                for (std::size_t k = 0; k < scene.ledges.size(); ++k)
                    poses.push_back({{"id", "ledge:" + std::to_string(k)},
                                     {"position_m", vec(scene.ledges[k].center_m)},
                                     {"orientation_wxyz", Json{1.0, 0.0, 0.0, 0.0}}, {"component_id", 0}});
                Json entry{{"time_s", frame.time_s}, {"phase", "lattice"}, {"poses", std::move(poses)},
                           {"fracture_count", frame.broken}};
                if (index % bond_stride == 0 || index + 1 == window_frames) {
                    Json lines = Json::array();
                    for (std::size_t b = 0; b < bonds; ++b) {
                        const auto &rest = scene.asset.bonds[b];
                        lines.push_back({{"a_m", vec(frame.positions[rest.node_a])},
                                         {"b_m", vec(frame.positions[rest.node_b])},
                                         {"live", frame.bond_alive[b] != 0},
                                         {"damage", static_cast<double>(frame.bond_damage[b])}});
                    }
                    entry["bonds"] = std::move(lines);
                }
                frames.push_back(std::move(entry));
            }
            for (const auto &frame : settle_frames) {
                Json poses = Json::array();
                for (std::size_t node = 0; node < cells; ++node)
                    poses.push_back({{"id", "cell:" + std::to_string(node)}, {"position_m", vec(frame.positions[node])},
                                     {"orientation_wxyz", quat(frame.orientations[node])},
                                     {"component_id", handoff.component_of_node[node]}});
                poses.push_back({{"id", "ball"}, {"position_m", vec(frame.ball_center)},
                                 {"orientation_wxyz", quat(frame.ball_orientation)}, {"component_id", 0}});
                for (std::size_t k = 0; k < scene.ledges.size(); ++k)
                    poses.push_back({{"id", "ledge:" + std::to_string(k)},
                                     {"position_m", vec(scene.ledges[k].center_m)},
                                     {"orientation_wxyz", Json{1.0, 0.0, 0.0, 0.0}}, {"component_id", 0}});
                frames.push_back({{"time_s", frame.time_s}, {"phase", "rigid"}, {"poses", std::move(poses)},
                                  {"fracture_count", cascade.broken_bonds}});
            }
            Json artifact{{"schema", "banjo.playback.v1"}, {"mode", "network"}, {"units", "SI"},
                          {"bodies", std::move(bodies)}, {"supports", std::move(supports)},
                          {"frames", std::move(frames)},
                          {"sampling", {{"stride_steps", 1}, {"interpolation", "none"},
                                        {"window_frames", window_frames}, {"settle_frames", settle_frames.size()}}},
                          {"physical_response_validated", false},
                          {"status", "complete"}, {"error", ""}, {"report", report}};
            artifact["requested_steps"] = artifact["frames"].size();
            artifact["completed_steps"] = artifact["frames"].size();
            std::string serialized = artifact.dump();
            constexpr std::size_t kBudget = 48U * 1024U * 1024U;
            if (serialized.size() > kBudget) {
                auto &all = artifact["frames"];
                for (std::size_t i = 0; i + 1 < window_frames && i < all.size(); ++i) all[i].erase("bonds");
                artifact["sampling"]["bond_lines"] = "last fracture frame only (byte budget)";
                serialized = artifact.dump();
                if (serialized.size() > kBudget) {
                    Json thinned = Json::array();
                    for (std::size_t i = 0; i < all.size(); ++i)
                        if (i == 0 || i + 1 == all.size() || i % 4 == 0) thinned.push_back(all[i]);
                    artifact["frames"] = std::move(thinned);
                    artifact["sampling"]["frames"] = "every fourth (byte budget)";
                    serialized = artifact.dump();
                }
                require(serialized.size() <= 64U * 1024U * 1024U, "recording exceeds the playback budget");
            }
            std::ofstream out(output_path, std::ios::binary);
            require(bool(out), "cannot open output " + output_path.string());
            out.write(serialized.data(), static_cast<std::streamsize>(serialized.size()));
            json_wall = since(json_start);
        }

        Json summary{{"lane", "algo1-impulse-woodbury"}, {"cells", cells}, {"bonds", bonds},
                     {"precompute_s", precompute_wall}, {"precompute_cached", stats.cached},
                     {"precompute_bytes", stats.cache_bytes},
                     {"mechanism_modes", stats.mechanism_modes},
                     {"screen_candidates", cascade.screen.candidate_bonds},
                     {"screen_wall_s", cascade.screen.wall_s},
                     {"rounds", cascade.rounds.size()}, {"broken_bonds", cascade.broken_bonds},
                     {"components", cascade.components},
                     {"largest_component_cells", cascade.largest_component_cells},
                     {"removed_energy_j", cascade.removed_energy_j},
                     {"first_failure_s", cascade.first_failure_time_s},
                     {"contact_impulse_n_s", cascade.contact.impulse_n_s},
                     {"window_wall_s", cascade.timings.total_s},
                     {"compute_wall_s", compute_wall}, {"simulated_s", simulated},
                     {"ratio", simulated > 0.0 ? compute_wall / simulated : 0.0},
                     {"total_wall_s", since(wall_start)}, {"json_wall_s", json_wall},
                     {"output", o.output}};
        std::cout << summary.dump() << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "banjo_fracture_algo1: " << error.what() << '\n';
        std::cout << Json{{"status", "error"}, {"error", error.what()}}.dump() << '\n';
        return 1;
    }
}
