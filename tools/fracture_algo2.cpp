// banjo_fracture_algo2: Algorithm 2, the event-driven Griffith cascade on a
// precomputed crack-influence matrix. No time stepping anywhere in the fracture
// phase: the plate is diagonalised once at creation, the peak dynamic strain per
// unit impulse is tabulated per strikeable cell, and an impact is a table lookup
// plus an O(bonds)-per-event cascade. The pieces are connected components and
// go to Jolt to fall and settle; the whole interaction is written as a
// banjo.playback.v1 recording the playground's 3D tab plays.
//
// --reference runs the explicit lattice (banjo_fastlattice, CPU, double) on the
// same scene built from the same command line and writes the same recording and
// report shape, so the two lanes cannot differ by a scene detail.

#include "fastlattice/TileImpactScene.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentMassProperties.hpp"
#include "griffith/GriffithCascade.hpp"
#include "rigid/JoltWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace {
using Json = nlohmann::json;
using namespace banjo;
using namespace banjo::griffith;
using Clock = std::chrono::steady_clock;

double since(Clock::time_point start) { return std::chrono::duration<double>(Clock::now() - start).count(); }

void require(bool condition, const std::string &message) {
    if (!condition) throw std::runtime_error(message);
}

// The explicit lattice's fracture-window length on the 500-cell contract scene,
// measured with `banjo_fracture_algo2 --reference` (13.764 ms; see the
// checkpoint). It is the stated
// denominator of realtime.fracture_window_ratio: this lane's own window has no
// duration at all, so a ratio against its own window would be meaningless.
constexpr double kReferenceWindowS = 1.3764e-2;
constexpr double kRealtimeLimit = 1.1;
constexpr double kGravity = 9.81;

struct Options {
    double length_m{0.25}, width_m{0.20}, thickness_m{0.01};
    double cell_m{0.01};
    double ball_diameter_m{0.06};
    double drop_m{2.0};
    double speed_m_s{-1.0};
    double offset_x_m{0.0}, offset_z_m{0.0};
    SupportKind support{SupportKind::Ledges};
    MaterialPreset material{MaterialPreset::Glass};
    double duration_s{2.0};
    std::string output;
    std::string cache;
    bool reference{false};
    // Extras beyond the shared contract; every one has a default that keeps the
    // contract's behaviour, so the Fracture lab panel never passes them.
    CriterionKind criterion{CriterionKind::Griffith};
    ContactMassKind contact_mass{ContactMassKind::Footprint};
    double reference_window_s{kReferenceWindowS};
    double all_strikes_budget_s{90.0};
    bool all_strikes{false};
    bool single_strike{false};
    unsigned reference_frames{400};
    unsigned record_frames{160};
    double rigid_dt_s{1.0 / 240.0};
    double frame_dt_s{1.0 / 60.0};
    double rest_speed_m_s{0.01};
    double rest_hold_s{0.30};
    std::size_t max_precompute_bytes{1500ull * 1024ull * 1024ull};
    bool settle{true};
};

double number(const std::string &text, const std::string &option) {
    std::size_t used = 0;
    const double value = std::stod(text, &used);
    require(used == text.size() && std::isfinite(value), "invalid number for " + option);
    return value;
}

Options parse(int argc, char **argv) {
    Options o;
    bool speed_given = false;
    for (int i = 1; i < argc; ++i) {
        const std::string option = argv[i];
        const auto value = [&]() -> std::string {
            require(i + 1 < argc, "option " + option + " needs a value");
            return argv[++i];
        };
        if (option == "--plate") {
            o.length_m = number(value(), option);
            o.width_m = number(value(), option);
            o.thickness_m = number(value(), option);
        } else if (option == "--cell") o.cell_m = number(value(), option);
        else if (option == "--ball") o.ball_diameter_m = number(value(), option);
        else if (option == "--drop") o.drop_m = number(value(), option);
        else if (option == "--speed") { o.speed_m_s = number(value(), option); speed_given = true; }
        else if (option == "--offset") { o.offset_x_m = number(value(), option); o.offset_z_m = number(value(), option); }
        else if (option == "--support") {
            const std::string kind = value();
            require(kind == "ledges" || kind == "clamped", "support must be ledges or clamped");
            o.support = kind == "ledges" ? SupportKind::Ledges : SupportKind::Clamped;
        } else if (option == "--material") {
            const std::string kind = value();
            if (kind == "glass") o.material = MaterialPreset::Glass;
            else if (kind == "oak" || kind == "wood") o.material = MaterialPreset::Oak;
            else if (kind == "iron") o.material = MaterialPreset::Iron;
            else throw std::runtime_error("material must be glass, oak or iron");
        } else if (option == "--duration") o.duration_s = number(value(), option);
        else if (option == "--output") o.output = value();
        else if (option == "--cache") o.cache = value();
        else if (option == "--reference") o.reference = true;
        else if (option == "--criterion") {
            const std::string kind = value();
            require(kind == "griffith" || kind == "strain", "criterion must be griffith or strain");
            o.criterion = kind == "griffith" ? CriterionKind::Griffith : CriterionKind::Strain;
        } else if (option == "--contact-mass") {
            const std::string kind = value();
            require(kind == "footprint" || kind == "plate", "contact mass must be footprint or plate");
            o.contact_mass = kind == "footprint" ? ContactMassKind::Footprint : ContactMassKind::Plate;
        } else if (option == "--reference-window") o.reference_window_s = number(value(), option);
        else if (option == "--strike-budget") o.all_strikes_budget_s = number(value(), option);
        else if (option == "--all-strikes") o.all_strikes = true;
        else if (option == "--single-strike") o.single_strike = true;
        else if (option == "--reference-frames") o.reference_frames = static_cast<unsigned>(number(value(), option));
        else if (option == "--record-frames") o.record_frames = static_cast<unsigned>(number(value(), option));
        else if (option == "--max-bytes") o.max_precompute_bytes =
            static_cast<std::size_t>(number(value(), option)) * 1024ull * 1024ull;
        else if (option == "--no-settle") o.settle = false;
        else if (option == "--help" || option == "-h") {
            std::cout << "usage: banjo_fracture_algo2 --plate L W T --cell H --ball D "
                         "[--drop H | --speed V] --offset X Z --support ledges|clamped "
                         "--duration S --output PATH --cache DIR [--reference]\n";
            std::exit(0);
        } else throw std::runtime_error("unknown option " + option);
    }
    if (!speed_given) {
        require(o.drop_m >= 0.0, "drop height must not be negative");
        o.speed_m_s = std::sqrt(2.0 * kGravity * o.drop_m);
    } else {
        require(o.speed_m_s >= 0.0, "impact speed must not be negative");
        o.drop_m = o.speed_m_s * o.speed_m_s / (2.0 * kGravity);
    }
    require(o.duration_s > 0.0, "duration must be positive");
    require(o.cell_m > 0.0 && o.ball_diameter_m > 0.0, "cell size and ball diameter must be positive");
    return o;
}

Json vec(const Vec3 &v) { return Json::array({v.x, v.y, v.z}); }
Json quat(const Quat &q) { return Json::array({q.w, q.x, q.y, q.z}); }

constexpr std::uint32_t kGlassColor = 0x9fd8ffffu;
constexpr std::uint32_t kIronColor = 0x6f7380ffu;
constexpr std::uint32_t kLedgeColor = 0x8b8f95ffu;

// ---------------------------------------------------------------------------
// Frames shared by both lanes
// ---------------------------------------------------------------------------

struct Frame {
    double time_s{};
    std::vector<Vec3> positions;
    std::vector<Quat> orientations;
    std::vector<std::uint32_t> component;
    Vec3 ball_center{};
    Quat ball_orientation{};
    std::vector<std::uint8_t> bond_alive; // empty when the frame carries no bond lines
    std::size_t broken{};
};

struct SceneDescription {
    double cell_m{};
    double ball_radius_m{};
    std::vector<StaticBox> ledges;
    std::vector<std::pair<std::uint32_t, std::uint32_t>> bond_nodes;
    std::size_t cells{};
    MaterialPreset plate_preset{MaterialPreset::Glass};
};

void writeRecording(const std::filesystem::path &path, const SceneDescription &scene,
                    const std::vector<Frame> &frames, const Json &report) {
    Json bodies = Json::array();
    const std::uint32_t plate_color = scene.plate_preset == MaterialPreset::Oak ? 0xc8a165ffu
                                    : scene.plate_preset == MaterialPreset::Iron ? 0xa7a9b0ffu
                                                                                 : kGlassColor;
    for (std::size_t i = 0; i < scene.cells; ++i)
        bodies.push_back({{"id", "1:" + std::to_string(i)}, {"object_id", 1}, {"element_id", i},
                          {"material_id", std::string(materialPresetName(scene.plate_preset))},
                          {"color_rgba", plate_color}, {"shape", "box"},
                          {"dimensions_m", Json::array({scene.cell_m, scene.cell_m, scene.cell_m})}});
    bodies.push_back({{"id", "2:0"}, {"object_id", 2}, {"element_id", 0}, {"material_id", "iron"},
                      {"color_rgba", kIronColor}, {"shape", "sphere"},
                      {"dimensions_m", Json::array({2 * scene.ball_radius_m, 2 * scene.ball_radius_m,
                                                    2 * scene.ball_radius_m})}});
    for (std::size_t k = 0; k < scene.ledges.size(); ++k)
        bodies.push_back({{"id", "ledge:" + std::to_string(k)}, {"object_id", 900 + k}, {"element_id", 0},
                          {"material_id", "concrete"}, {"color_rgba", kLedgeColor}, {"shape", "box"},
                          {"dimensions_m", vec(scene.ledges[k].dimensions_m)}});

    Json out_frames = Json::array();
    for (const Frame &frame : frames) {
        Json poses = Json::array();
        for (std::size_t i = 0; i < frame.positions.size(); ++i)
            poses.push_back({{"id", "1:" + std::to_string(i)}, {"position_m", vec(frame.positions[i])},
                             {"orientation_wxyz", quat(i < frame.orientations.size() ? frame.orientations[i] : Quat{})},
                             {"component_id", frame.component.empty() ? 0u : frame.component[i]}});
        poses.push_back({{"id", "2:0"}, {"position_m", vec(frame.ball_center)},
                         {"orientation_wxyz", quat(frame.ball_orientation)}, {"component_id", 0}});
        for (std::size_t k = 0; k < scene.ledges.size(); ++k)
            poses.push_back({{"id", "ledge:" + std::to_string(k)}, {"position_m", vec(scene.ledges[k].center_m)},
                             {"orientation_wxyz", Json::array({1.0, 0.0, 0.0, 0.0})}, {"component_id", 0}});
        Json entry{{"time_s", frame.time_s}, {"poses", std::move(poses)}, {"fracture_count", frame.broken}};
        if (!frame.bond_alive.empty()) {
            Json bonds = Json::array();
            for (std::size_t b = 0; b < scene.bond_nodes.size(); ++b)
                bonds.push_back({{"a_m", vec(frame.positions[scene.bond_nodes[b].first])},
                                 {"b_m", vec(frame.positions[scene.bond_nodes[b].second])},
                                 {"live", frame.bond_alive[b] != 0}, {"damage", frame.bond_alive[b] != 0 ? 0.0 : 1.0}});
            entry["bonds"] = std::move(bonds);
        }
        out_frames.push_back(std::move(entry));
    }
    const double ground = 1.0;
    Json supports = Json::array({
        Json::array({Json::array({-ground, 0.0, -ground}), Json::array({ground, 0.0, -ground}),
                     Json::array({ground, 0.0, ground})}),
        Json::array({Json::array({-ground, 0.0, -ground}), Json::array({ground, 0.0, ground}),
                     Json::array({-ground, 0.0, ground})})});
    Json artifact{{"schema", "banjo.playback.v1"}, {"mode", "network"}, {"units", "SI"},
                  {"bodies", std::move(bodies)}, {"supports", std::move(supports)},
                  {"frames", std::move(out_frames)},
                  {"sampling", {{"stride_steps", 1}, {"maximum_frames", 0}, {"interpolation", "none"}}},
                  {"physical_response_validated", false},
                  {"status", "complete"}, {"error", ""}, {"report", report}};
    artifact["requested_steps"] = artifact["frames"].size();
    artifact["completed_steps"] = artifact["frames"].size();
    artifact["sampling"]["maximum_frames"] = artifact["frames"].size();
    std::string serialized = artifact.dump();
    constexpr std::size_t kBudget = 60U * 1024U * 1024U;
    if (serialized.size() > kBudget) {
        std::size_t last_with_bonds = 0;
        for (std::size_t i = 0; i < artifact["frames"].size(); ++i)
            if (artifact["frames"][i].contains("bonds")) last_with_bonds = i;
        for (std::size_t i = 0; i < artifact["frames"].size(); ++i)
            if (i != last_with_bonds) artifact["frames"][i].erase("bonds");
        artifact["sampling"]["bond_lines"] = "last frame that carried them only (byte budget)";
        serialized = artifact.dump();
    }
    // Then thin the frames, first and last always kept, until it fits. The
    // report is never cut.
    unsigned thinned = 1;
    while (serialized.size() > kBudget && artifact["frames"].size() > 8) {
        Json kept = Json::array();
        const std::size_t count = artifact["frames"].size();
        for (std::size_t i = 0; i < count; ++i)
            if (i == 0 || i + 1 == count || i % 2 == 0) kept.push_back(artifact["frames"][i]);
        artifact["frames"] = std::move(kept);
        thinned *= 2;
        artifact["sampling"]["frame_stride"] = thinned;
        serialized = artifact.dump();
    }
    require(serialized.size() <= kBudget, "the recording exceeds the 60 MiB playback budget");
    std::ofstream file(path, std::ios::binary);
    require(bool(file), "cannot open " + path.string());
    file.write(serialized.data(), static_cast<std::streamsize>(serialized.size()));
}

// ---------------------------------------------------------------------------
// Handoff: connected components become rigid bodies
// ---------------------------------------------------------------------------

struct CellBox { Vec3 center_rest_local; Vec3 dimensions; };

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
    const auto &first = asset.nodes.front();
    const Vec3 origin = first.local_position_m -
        Vec3{(first.grid.x + 0.5) * h, (first.grid.y + 0.5) * h, (first.grid.z + 0.5) * h};
    const auto local = [&](double x, double y, double z) {
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
    std::size_t fragments{}, static_components{}, oversized_pieces{}, collision_boxes{};
    double fragment_mass_kg{}, largest_fragment_mass_kg{};
    double dropped_momentum_n_s{};
};

Handoff handToJolt(JoltWorld &rigid, const PlateModel &plate) {
    Handoff h;
    const auto components = findConnectedComponents(plate.matter);
    h.component_of_node.assign(plate.matter.nodes.size(), 0U);
    for (const auto &c : components)
        for (const auto node : c.node_indices) h.component_of_node[node] = c.id;
    MatterBodyId next_dynamic = 1000, next_static = 100000;
    for (const auto &c : components) {
        bool has_fixed = false;
        for (const auto node : c.node_indices) has_fixed = has_fixed || plate.fixed[node];
        auto boxes = mergeCells(plate.asset, c.node_indices, plate.request.cell_m);
        Vec3 rest_center{};
        for (const auto node : c.node_indices) rest_center += plate.matter.reference_positions_world_m[node];
        rest_center = rest_center / static_cast<double>(c.node_indices.size());
        HandoffBody body;
        body.nodes = c.node_indices;
        body.rest_center = rest_center;
        if (has_fixed) {
            ++h.static_components;
            body.dynamic = false;
            body.id = next_static;
            for (const auto &box : boxes) {
                RigidBoxDescription description;
                description.body_id = next_static++;
                description.dimensions_m = box.dimensions;
                description.material = plate.plate_material;
                description.state.center_of_mass_world_m = box.center_rest_local + plate.origin;
                description.fixed = true;
                rigid.addBox(description);
                ++h.collision_boxes;
            }
        } else {
            ++h.fragments;
            const auto properties = calculateFragmentMassProperties(plate.matter, c.node_indices);
            h.fragment_mass_kg += properties.mass_kg;
            h.largest_fragment_mass_kg = std::max(h.largest_fragment_mass_kg, properties.mass_kg);
            if (boxes.size() > 64) {
                // Jolt compounds take 64 parts. A ragged piece that needs more
                // keeps its true mass and inertia and gets its bounding box as
                // the collision silhouette; the coarsening is counted, not hidden.
                ++h.oversized_pieces;
                Vec3 low{1e300, 1e300, 1e300}, high{-1e300, -1e300, -1e300};
                for (const auto &box : boxes) {
                    low = {std::min(low.x, box.center_rest_local.x - 0.5 * box.dimensions.x),
                           std::min(low.y, box.center_rest_local.y - 0.5 * box.dimensions.y),
                           std::min(low.z, box.center_rest_local.z - 0.5 * box.dimensions.z)};
                    high = {std::max(high.x, box.center_rest_local.x + 0.5 * box.dimensions.x),
                            std::max(high.y, box.center_rest_local.y + 0.5 * box.dimensions.y),
                            std::max(high.z, box.center_rest_local.z + 0.5 * box.dimensions.z)};
                }
                boxes.assign(1, {(low + high) * 0.5, high - low});
            }
            RigidCompoundDescription description;
            description.body_id = next_dynamic++;
            description.material = plate.plate_material;
            for (const auto &box : boxes) {
                RigidPrimitive geometry;
                geometry.kind = PrimitiveKind::Box;
                geometry.dimensions_m = box.dimensions;
                description.parts.push_back({geometry, box.center_rest_local + plate.origin - rest_center});
                ++h.collision_boxes;
            }
            // Pieces start from rest: this lane never authors a fragment
            // velocity, and it has no time history from which to earn one. The
            // momentum the contact model put into the plate is therefore
            // dropped at the handoff, and the amount is reported.
            description.state.center_of_mass_world_m = properties.center_of_mass_world_m;
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

} // namespace

// ---------------------------------------------------------------------------

int main(int argc, char **argv) {
    Options o;
    try {
        o = parse(argc, argv);
    } catch (const std::exception &error) {
        std::cerr << "banjo_fracture_algo2: " << error.what() << '\n';
        return 2;
    }
    try {
        const auto wall_start = Clock::now();
        Json report;
        SceneDescription scene;
        std::vector<Frame> frames;

        if (o.reference) {
            require(o.support == SupportKind::Ledges,
                    "the reference lane supports the plate on two ledges only");
            fastlattice::TileImpactRequest request;
            request.tile_material = o.material;
            request.ball_material = MaterialPreset::Iron;
            request.tile_dimensions_m = {o.length_m, o.thickness_m, o.width_m};
            request.cell_size_m = o.cell_m;
            request.neighbor_horizon_cells = 2;
            request.ball_radius_m = 0.5 * o.ball_diameter_m;
            request.ball_speed_m_s = o.speed_m_s;
            request.ball_offset_x_m = o.offset_x_m;
            request.ball_offset_z_m = o.offset_z_m;
            request.layout = fastlattice::SceneLayout::Bridge;
            request.backend = fastlattice::BackendKind::Cpu;
            request.precision = fastlattice::Precision::Double;
            request.settle_limit_s = o.duration_s;
            request.lattice_frames = o.reference_frames;
            request.rigid_frames = static_cast<unsigned>(std::max(2.0, o.duration_s * 60.0));
            const auto result = fastlattice::runTileImpact(request);
            const auto &m = result.measurements;
            scene.cell_m = result.cell_size_m;
            scene.ball_radius_m = result.ball_radius_m;
            scene.ledges.reserve(result.ledges.size());
            for (const auto &ledge : result.ledges) scene.ledges.push_back({ledge.center_m, ledge.dimensions_m});
            scene.bond_nodes = result.bond_nodes;
            scene.cells = m.cells;
            // First failure: the reference does not expose its first failure
            // round, so this is the dead set in the earliest recorded lattice
            // frame that has one. With --reference-frames 400 the frame spacing
            // is a few tens of microseconds.
            std::vector<std::uint32_t> first_failure;
            double first_failure_frame_s = -1.0;
            for (const auto &frame : result.frames) {
                if (frame.bond_alive.empty()) continue;
                std::vector<std::uint32_t> dead;
                for (std::uint32_t b = 0; b < frame.bond_alive.size(); ++b)
                    if (!frame.bond_alive[b]) dead.push_back(b);
                if (dead.empty()) continue;
                first_failure = std::move(dead);
                first_failure_frame_s = frame.time_s;
                break;
            }
            // The lattice phase is recorded densely so the first-failure set
            // above is tight, but only a subsample is written: 400 frames of a
            // 1,000-cell plate do not fit the playback budget.
            std::size_t lattice_count = 0;
            for (const auto &source : result.frames) lattice_count += source.phase == "lattice" ? 1 : 0;
            const std::size_t stride = std::max<std::size_t>(
                1, (lattice_count + o.record_frames - 1) / std::max(1U, o.record_frames));
            std::size_t index = 0, emitted = 0;
            for (const auto &source : result.frames) {
                const bool lattice = source.phase == "lattice";
                const bool keep = !lattice || index % stride == 0 || index + 1 == lattice_count;
                if (lattice) ++index;
                if (!keep) continue;
                Frame frame;
                frame.time_s = source.time_s;
                frame.positions = source.cell_positions;
                frame.orientations = source.cell_orientations;
                frame.component = source.component_ids;
                frame.ball_center = source.ball_center;
                frame.ball_orientation = source.ball_orientation;
                frame.broken = source.fracture_count;
                // Bond lines only where they say something: the intact plate,
                // the first frame with damage, and the last lattice frame.
                const bool wanted_bonds = !source.bond_alive.empty() &&
                    (emitted == 0 || std::abs(source.time_s - first_failure_frame_s) < 1.0e-12 ||
                     index == lattice_count);
                if (wanted_bonds) frame.bond_alive = source.bond_alive;
                ++emitted;
                frames.push_back(std::move(frame));
            }
            const double compute_wall = since(wall_start);
            const double impulse = std::abs(m.contact.impulse_to_material_y);
            report = {
                {"lane", "reference-explicit-lattice"},
                {"lane_detail", "banjo_fastlattice CPU backend, double precision, colour-ordered "
                                "Gauss-Seidel, shared criterion, every substep resolved"},
                {"cells", m.cells}, {"bonds", m.bonds},
                {"precompute_s", 0.0}, {"precompute_cached", false}, {"precompute_bytes", 0},
                {"compute_wall_s", compute_wall}, {"simulated_s", m.simulated_total_s},
                {"realtime", {{"ratio", m.simulated_total_s > 0 ? compute_wall / m.simulated_total_s : 0.0},
                              {"simulated_s", m.simulated_total_s}, {"compute_wall_s", compute_wall},
                              {"fracture_window_ratio", m.lattice_simulated_s > 0 ? m.lattice_wall_s / m.lattice_simulated_s : 0.0},
                              {"window_simulated_s", m.lattice_simulated_s},
                              {"window_note", "this lane's own fracture window, resolved substep by substep"},
                              {"limit", kRealtimeLimit}}},
                {"contact", {{"impulse_n_s", impulse}, {"energy_budget_j", m.contact.dissipated_kinetic_energy_j},
                             {"model", "resolved node-by-node sphere contact over the whole lattice phase; "
                                       "impulse_n_s is the accumulated normal impulse into the material and "
                                       "energy_budget_j the kinetic energy the contact dissipated"}}},
                {"first_failure", {{"bond_indices", first_failure}, {"time_s", m.first_failure_s},
                                   {"frame_time_s", first_failure_frame_s},
                                   {"note", "the dead set in the earliest recorded lattice frame; the reference "
                                            "lane does not expose its first failure round directly"}}},
                {"events", m.failure_rounds}, {"broken_bonds", m.broken_bonds},
                {"energy_spent_j", m.removed_energy_j},
                {"components", m.components},
                {"largest_component_cells", m.largest_piece_cells},
                {"largest_component_mass_kg", m.largest_piece_mass_kg},
                {"removed_energy_j", m.removed_energy_j},
                {"lattice", {{"steps", m.lattice_steps}, {"dt_s", m.dt_s},
                             {"simulated_s", m.lattice_simulated_s}, {"wall_s", m.lattice_wall_s},
                             {"bond_updates_per_s", m.bond_updates_per_s},
                             {"substep_limit_s", m.substep_limit_s}}},
                {"rigid", {{"pieces", m.rigid_fragments}, {"simulated_s", m.rigid_simulated_s},
                           {"wall_s", m.rigid_wall_s}, {"came_to_rest", m.came_to_rest},
                           {"rest_time_s", m.rest_time_s}}},
                {"physical_response_validated", false},
            };
            scene.plate_preset = o.material;
        } else {
            // ---- Algorithm 2 -------------------------------------------------
            PlateRequest request;
            request.length_m = o.length_m;
            request.width_m = o.width_m;
            request.thickness_m = o.thickness_m;
            request.cell_m = o.cell_m;
            request.ball_diameter_m = o.ball_diameter_m;
            request.support = o.support;
            request.plate_material = o.material;
            const auto build_start = Clock::now();
            auto plate = buildPlate(request);
            const double build_s = since(build_start);

            const ContactModel contact =
                buildContact(*plate, o.offset_x_m, o.offset_z_m, o.speed_m_s, o.contact_mass);

            PrecomputeOptions precompute_options;
            precompute_options.cache_dir = o.cache;
            precompute_options.all_strikes_budget_s = o.all_strikes_budget_s;
            precompute_options.force_all_strikes = o.all_strikes;
            precompute_options.force_single_strike = o.single_strike;
            precompute_options.maximum_bytes = o.max_precompute_bytes;
            const auto tables = precompute(*plate, precompute_options, contact.strike_row);

            CascadeOptions cascade_options;
            cascade_options.criterion = o.criterion;
            const auto cascade = runCascade(*plate, tables, contact, cascade_options);

            // ---- pieces fall and settle -------------------------------------
            scene.cell_m = o.cell_m;
            scene.ball_radius_m = 0.5 * o.ball_diameter_m;
            scene.ledges = plate->ledges;
            scene.cells = plate->matter.nodes.size();
            scene.plate_preset = request.plate_material;
            for (const auto &bond : plate->asset.bonds) scene.bond_nodes.emplace_back(bond.node_a, bond.node_b);

            std::vector<std::uint8_t> alive_start(plate->matter.bonds.size(), 1);
            std::vector<std::uint8_t> alive_end(plate->matter.bonds.size(), 1);
            for (std::size_t b = 0; b < plate->matter.bonds.size(); ++b)
                alive_end[b] = plate->matter.bonds[b].alive ? 1 : 0;

            const auto handoff_start = Clock::now();
            // Jolt's default contact budget is sized for a handful of bodies. A
            // cascade that makes hundreds of pieces overruns it and the step is
            // refused rather than silently dropping contacts, so the budget is
            // sized from the piece count before the world is built.
            const std::size_t piece_count = findConnectedComponents(plate->matter).size();
            RigidContactCapacity capacity;
            capacity.body_pairs = static_cast<unsigned>(
                std::clamp<std::size_t>(1024 * piece_count, 16384, 262144));
            capacity.constraints = static_cast<unsigned>(
                std::clamp<std::size_t>(512 * piece_count, 8192, 65536));
            JoltWorld rigid(0, capacity);
            rigid.addFloor();
            RigidBallDescription ball;
            ball.body_id = 2;
            ball.radius_m = scene.ball_radius_m;
            ball.material = plate->ball_material;
            ball.position_world_m = {contact.strike_node == PlateModel::kNoIndex ? o.offset_x_m
                                         : plate->matter.reference_positions_world_m[contact.strike_node].x,
                                     plate->plate_top_y + scene.ball_radius_m,
                                     contact.strike_node == PlateModel::kNoIndex ? o.offset_z_m
                                         : plate->matter.reference_positions_world_m[contact.strike_node].z};
            ball.linear_velocity_m_s = {0.0, -contact.ball_speed_after_m_s, 0.0};
            rigid.addBall(ball);
            for (const auto &ledge : plate->ledges) {
                RigidBoxDescription description;
                description.body_id = 900000 + static_cast<MatterBodyId>(&ledge - plate->ledges.data());
                description.dimensions_m = ledge.dimensions_m;
                description.material = makeReferenceMaterial(MaterialPreset::Concrete, request.seed);
                description.state.center_of_mass_world_m = ledge.center_m;
                description.fixed = true;
                rigid.addBox(description);
            }
            const Handoff handoff = handToJolt(rigid, *plate);
            const double handoff_s = since(handoff_start);

            const auto capture = [&](double time, const std::vector<std::uint8_t> *bonds) {
                Frame frame;
                frame.time_s = time;
                frame.positions.resize(plate->matter.nodes.size());
                frame.orientations.assign(plate->matter.nodes.size(), Quat{});
                frame.component = handoff.component_of_node;
                frame.broken = cascade.events.size();
                for (const auto &body : handoff.bodies) {
                    if (!body.dynamic) {
                        for (const auto node : body.nodes)
                            frame.positions[node] = plate->matter.reference_positions_world_m[node];
                        continue;
                    }
                    const auto snap = rigid.snapshot(body.id);
                    for (const auto node : body.nodes) {
                        frame.positions[node] = snap.center_of_mass_world_m +
                            snap.orientation_world.rotate(plate->matter.reference_positions_world_m[node] - body.rest_center);
                        frame.orientations[node] = snap.orientation_world;
                    }
                }
                const auto snap = rigid.snapshot(2);
                frame.ball_center = snap.center_of_mass_world_m;
                frame.ball_orientation = snap.orientation_world;
                if (bonds) frame.bond_alive = *bonds;
                frames.push_back(std::move(frame));
            };

            // The cascade takes no simulated time at all: frame 0 is the intact
            // plate under load, frame 1 the same instant with the cascade's
            // bonds removed. Everything after is Jolt.
            {
                Frame intact;
                intact.time_s = 0.0;
                intact.positions = plate->matter.reference_positions_world_m;
                intact.orientations.assign(plate->matter.nodes.size(), Quat{});
                intact.component.assign(plate->matter.nodes.size(), 0U);
                intact.ball_center = ball.position_world_m;
                intact.bond_alive = alive_start;
                intact.broken = 0;
                frames.push_back(std::move(intact));
            }
            capture(1.0e-6, &alive_end);

            const auto settle_start = Clock::now();
            double time = 0.0, last_frame = 0.0, at_rest_for = 0.0, settled_at = -1.0, peak_speed = 0.0;
            std::uint64_t steps = 0;
            std::vector<MatterBodyId> dynamic_ids{2};
            for (const auto &body : handoff.bodies) if (body.dynamic) dynamic_ids.push_back(body.id);
            if (o.settle) {
                while (time < o.duration_s - 1e-12) {
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
                    if (speed < o.rest_speed_m_s && spin < 10.0 * o.rest_speed_m_s) at_rest_for += o.rigid_dt_s;
                    else at_rest_for = 0.0;
                    if (time - last_frame >= o.frame_dt_s - 1e-12) { capture(time, nullptr); last_frame = time; }
                    if (at_rest_for >= o.rest_hold_s) { settled_at = time - at_rest_for; break; }
                }
                if (last_frame < time) capture(time, &alive_end);
            }
            const double settle_s = since(settle_start);
            const double compute_wall = since(wall_start);
            const double simulated = time;

            const auto &stats = tables.stats;
            const double precompute_s = stats.eigen_s + stats.influence_s + stats.peak_s +
                                        stats.cache_read_s + stats.cache_write_s;
            Json first_failure_cells = Json::array();
            for (const auto b : cascade.first_failure) {
                const auto &rest = plate->asset.bonds[b];
                const auto &ga = plate->asset.nodes[rest.node_a].grid;
                const auto &gb = plate->asset.nodes[rest.node_b].grid;
                first_failure_cells.push_back(Json::array({Json::array({ga.x, ga.y, ga.z}),
                                                           Json::array({gb.x, gb.y, gb.z})}));
            }
            Json events = Json::array();
            for (std::size_t i = 0; i < cascade.events.size() && i < 400; ++i) {
                const auto &e = cascade.events[i];
                events.push_back({{"bond", e.bond}, {"drive", e.drive}, {"strain", e.strain},
                                  {"released_force_n", e.released_force_n},
                                  {"crack_work_j", e.crack_work_j}, {"stored_energy_j", e.stored_energy_j}});
            }
            report = {
                {"lane", "algo2-griffith-events"},
                {"lane_detail", "event-driven Griffith cascade on a precomputed crack-influence matrix; "
                                "no time stepping in the fracture phase"},
                {"criterion", criterionName(o.criterion)},
                {"cells", plate->matter.nodes.size()},
                {"bonds", plate->matter.bonds.size()},
                {"precompute_s", precompute_s},
                {"precompute_cached", stats.tables_cached && stats.strike_cached},
                {"precompute_bytes", stats.bytes},
                {"compute_wall_s", compute_wall},
                {"simulated_s", simulated},
                {"realtime", {{"ratio", simulated > 0 ? compute_wall / simulated : 0.0},
                              {"simulated_s", simulated}, {"compute_wall_s", compute_wall},
                              {"fracture_window_ratio", cascade.cascade_wall_s / o.reference_window_s},
                              {"window_simulated_s", o.reference_window_s},
                              {"window_note", "this lane's fracture phase has no simulated duration at all, so the "
                                              "denominator is the reference explicit lattice's own fracture window "
                                              "on this scene (--reference-window, default measured on the default "
                                              "scene); the numerator is this lane's cascade wall time"},
                              {"limit", kRealtimeLimit}}},
                {"contact", {{"impulse_n_s", contact.impulse_n_s},
                             {"energy_budget_j", contact.energy_budget_j},
                             {"model", contact.model},
                             {"effective_mass", contactMassName(contact.mass_kind)},
                             {"ball_mass_kg", contact.ball_mass_kg},
                             {"speed_m_s", contact.speed_m_s},
                             {"contact_radius_m", contact.contact_radius_m},
                             {"footprint_cells", contact.patch_nodes.size()},
                             {"footprint_effective_mass_kg", contact.patch_mass_kg},
                             {"unsupported_plate_mass_kg", contact.free_mass_kg},
                             {"reduced_mass_footprint_kg", contact.reduced_mass_patch_kg},
                             {"reduced_mass_plate_kg", contact.reduced_mass_plate_kg},
                             {"ball_speed_after_m_s", contact.ball_speed_after_m_s},
                             {"strike_cell", contact.strike_node},
                             {"strike_snap_m", contact.strike_snap_m}}},
                {"first_failure", {{"bond_indices", cascade.first_failure},
                                   {"bond_cells", first_failure_cells},
                                   {"peak_drive", cascade.first_failure_peak_drive},
                                   {"note", "every bond at or above the criterion under the initial load, before "
                                            "any redistribution; the cascade then breaks one bond per event, "
                                            "largest drive first, ties to the lower bond index"}}},
                {"events", cascade.events.size()},
                {"cascade_wall_s", cascade.cascade_wall_s},
                {"broken_bonds", cascade.events.size()},
                {"energy_spent_j", cascade.energy_spent_j},
                {"components", cascade.components},
                {"largest_component_cells", cascade.largest_component_cells},
                {"largest_component_mass_kg", cascade.largest_component_mass_kg},
                {"removed_energy_j", cascade.removed_energy_j},
                {"energy_ledger", {{"budget_j", cascade.energy_budget_j},
                                   {"crack_work_spent_j", cascade.energy_spent_j},
                                   {"remaining_j", cascade.energy_remaining_j},
                                   {"residual_j", cascade.energy_budget_j - cascade.energy_spent_j -
                                                  cascade.energy_remaining_j},
                                   {"removed_bond_stored_energy_j", cascade.removed_energy_j},
                                   {"budget_exhausted", cascade.budget_exhausted}}},
                {"precompute", {{"tables_cached", stats.tables_cached},
                                {"strike_column_cached", stats.strike_cached},
                                {"strikes_complete", stats.strikes_complete},
                                {"modes", stats.modes},
                                {"strike_cells", stats.strike_cells},
                                {"strike_cells_ready", stats.strike_cells_ready},
                                {"eigen_s", stats.eigen_s}, {"influence_s", stats.influence_s},
                                {"peak_s", stats.peak_s}, {"cache_read_s", stats.cache_read_s},
                                {"cache_write_s", stats.cache_write_s},
                                {"peak_window_s", stats.peak_window_s},
                                {"peak_sample_dt_s", stats.peak_sample_dt_s},
                                {"peak_samples", stats.peak_samples},
                                {"bytes", stats.bytes}, {"path", stats.path}, {"note", stats.note}}},
                {"cascade", {{"wall_s", cascade.cascade_wall_s},
                             {"maximum_initial_strain", cascade.maximum_initial_strain},
                             {"break_strain", plate->compiled.damage_end_stretch},
                             {"fracture_energy_j_m2", plate->compiled.fracture_energy_j_m2},
                             {"griffith_break_strain_unit_bond",
                              std::sqrt(2.0 * plate->compiled.fracture_energy_j_m2 * plate->bond_area_m2.front() /
                                        (plate->bond_stiffness_n_m.front() * plate->bond_length_m.front() *
                                         plate->bond_length_m.front()))},
                             {"influence_singular_used", cascade.influence_singular_used},
                             {"events", events},
                             {"events_truncated", cascade.events.size() > 400}}},
                {"handoff", {{"contact_body_pairs", capacity.body_pairs},
                             {"contact_constraints", capacity.constraints},
                             {"fragments", handoff.fragments},
                             {"static_components", handoff.static_components},
                             {"collision_boxes", handoff.collision_boxes},
                             {"oversized_pieces", handoff.oversized_pieces},
                             {"fragment_mass_kg", handoff.fragment_mass_kg},
                             {"largest_fragment_mass_kg", handoff.largest_fragment_mass_kg},
                             {"piece_initial_velocity", "rest"},
                             {"dropped_momentum_n_s", contact.impulse_n_s},
                             {"note", "pieces start from rest; the contact model's impulse into the plate is "
                                      "therefore dropped at the handoff and reported as dropped_momentum_n_s"},
                             {"wall_s", handoff_s}}},
                {"settle", {{"enabled", o.settle}, {"steps", steps}, {"simulated_s", time},
                            {"settled", settled_at >= 0.0}, {"settled_time_s", settled_at},
                            {"peak_piece_speed_m_s", peak_speed}, {"wall_s", settle_s},
                            {"rigid_dt_s", o.rigid_dt_s}}},
                {"scene", {{"plate_m", Json::array({o.length_m, o.width_m, o.thickness_m})},
                           {"cells_per_axis", Json::array({plate->layout.nx, plate->layout.ny, plate->layout.nz})},
                           {"cell_m", o.cell_m}, {"ball_diameter_m", o.ball_diameter_m},
                           {"drop_m", o.drop_m}, {"speed_m_s", o.speed_m_s},
                           {"offset_m", Json::array({o.offset_x_m, o.offset_z_m})},
                           {"support", supportName(o.support)},
                           {"material", materialPresetName(request.plate_material)},
                           {"free_cells", plate->free_nodes.size()},
                           {"held_cells", plate->matter.nodes.size() - plate->free_nodes.size()},
                           {"bond_area_normalisation", plate->area_normalisation},
                           {"scene_build_s", build_s}}},
                {"physical_response_validated", false},
            };
        }

        if (!o.output.empty()) {
            const auto path = std::filesystem::absolute(o.output).lexically_normal();
            std::error_code error;
            std::filesystem::create_directories(path.parent_path(), error);
            writeRecording(path, scene, frames, report);
        }
        Json summary = report;
        if (summary.contains("cascade")) summary["cascade"].erase("events");
        std::cout << summary.dump() << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "banjo_fracture_algo2: " << error.what() << '\n';
        return 1;
    }
}
