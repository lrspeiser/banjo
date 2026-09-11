#include "fastlattice/TileImpactScene.hpp"
#include "matter/LatticeMerge.hpp"

#include "fastlattice/Refracture.hpp"
#include "fracture/BondFailure.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "fracture/ImpactEvent.hpp"
#include "material/MaterialCompiler.hpp"
#include "rigid/JoltWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <limits>
#include <numbers>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <set>
#include <tuple>
#include <vector>

namespace banjo::fastlattice {
namespace {

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

double seconds(Clock::time_point from, Clock::time_point to) {
    return std::chrono::duration<double>(to - from).count();
}

V3<double> toV3(const Vec3 &v) { return {v.x, v.y, v.z}; }

// x then y then z, degrees. Used to place a tilted body's cells and to
// orient the shape it collides as, so the two always agree.
Vec3 rotateDegrees(const Vec3 &v, const Vec3 &degrees) {
    const double to_rad = std::acos(-1.0) / 180.0;
    Vec3 p = v;
    const double cx = std::cos(degrees.x * to_rad), sx = std::sin(degrees.x * to_rad);
    p = {p.x, p.y * cx - p.z * sx, p.y * sx + p.z * cx};
    const double cy = std::cos(degrees.y * to_rad), sy = std::sin(degrees.y * to_rad);
    p = {p.x * cy + p.z * sy, p.y, -p.x * sy + p.z * cy};
    const double cz = std::cos(degrees.z * to_rad), sz = std::sin(degrees.z * to_rad);
    p = {p.x * cz - p.y * sz, p.x * sz + p.y * cz, p.z};
    return p;
}

// Declared in the header: see there for why it is shared.
} // namespace

void rotationQuaternion(const Vec3 &degrees, double out[4]) {
    const double h = std::acos(-1.0) / 360.0;
    const double cx = std::cos(degrees.x * h), sx = std::sin(degrees.x * h);
    const double cy = std::cos(degrees.y * h), sy = std::sin(degrees.y * h);
    const double cz = std::cos(degrees.z * h), sz = std::sin(degrees.z * h);
    out[0] = cz * cy * cx - sz * sy * sx;
    out[1] = cz * cy * sx + sz * sy * cx;
    out[2] = cz * sy * cx - sz * cy * sx;
    out[3] = sz * cy * cx + cz * sy * sx;
}

namespace {
Vec3 toVec3(const V3<double> &v) { return {v.x, v.y, v.z}; }

SupportPlane<double> makePlane(const Vec3 &point, const CombinedContactMaterial &contact, double node_radius) {
    const SupportPlaneFrame frame = makeSupportPlane(point, {0.0, 1.0, 0.0});
    SupportPlane<double> plane{};
    plane.point = toV3(frame.point_world_m);
    plane.normal = toV3(frame.normal_world);
    plane.tangent = toV3(frame.tangent_world);
    plane.bitangent = toV3(frame.bitangent_world);
    plane.restitution = contact.restitution;
    plane.static_friction = contact.static_friction;
    plane.dynamic_friction = contact.dynamic_friction;
    plane.node_radius = node_radius;
    plane.reach_capped = 0;
    plane.footprint_count = 0;
    return plane;
}

void addFootprint(SupportPlane<double> &plane, double center_t, double center_b, double half_t, double half_b) {
    if (plane.footprint_count >= kMaxFootprints) throw std::logic_error("too many support footprints");
    plane.footprints[plane.footprint_count++] = {center_t, center_b, half_t, half_b};
    // Only a finite footprint has an edge a node can pass; see
    // LatticePhysics.hpp projectSupportPosition.
    if (std::isfinite(half_t) || std::isfinite(half_b)) plane.reach_capped = 1;
}

} // namespace

// Declared in the header: the material names a scene file may use.
MaterialPreset presetFromName(std::string_view name) {
    if (name == "glass") return MaterialPreset::Glass;
    if (name == "oak") return MaterialPreset::Oak;
    if (name == "iron") return MaterialPreset::Iron;
    if (name == "concrete") return MaterialPreset::Concrete;
    if (name == "ceramic" || name == "alumina ceramic") return MaterialPreset::Ceramic;
    if (name == "ice") return MaterialPreset::Ice;
    if (name == "aluminum" || name == "aluminium") return MaterialPreset::Aluminum;
    if (name == "rubber") return MaterialPreset::Rubber;
    throw std::invalid_argument("unknown material: " + std::string(name));
}

// Declared in the header: the scene file format, shared so that every lane
// that reads one agrees on what it says.
std::vector<SceneBody> readSceneFile(const std::string &path) {
    std::ifstream input(path);
    if (!input) throw std::invalid_argument("could not open scene " + path);
    const nlohmann::json document = nlohmann::json::parse(input);
    const auto &list = document.contains("bodies") ? document.at("bodies") : document;
    if (!list.is_array() || list.empty()) throw std::invalid_argument("a scene needs a non-empty bodies array");
    const auto vector3 = [](const nlohmann::json &node, const char *key, Vec3 fallback) {
        if (!node.contains(key)) return fallback;
        const auto &v = node.at(key);
        if (!v.is_array() || v.size() != 3) throw std::invalid_argument(std::string(key) + " needs three numbers");
        return Vec3{v[0].get<double>(), v[1].get<double>(), v[2].get<double>()};
    };
    std::vector<SceneBody> bodies;
    for (const auto &node : list) {
        SceneBody body;
        body.name = node.value("name", std::string("body"));
        const std::string shape = node.value("shape", std::string("box"));
        if (shape == "sphere") body.shape = BodyShape::Sphere;
        else if (shape == "box") body.shape = BodyShape::Box;
        else if (shape == "cone") body.shape = BodyShape::Cone;
        else throw std::invalid_argument("unknown shape: " + shape);
        body.material = presetFromName(node.value("material", std::string("glass")));
        body.dimensions_m = vector3(node, "dimensions_m", Vec3{0.1, 0.1, 0.1});
        body.center_m = vector3(node, "center_m", Vec3{});
        body.velocity_m_s = vector3(node, "velocity_m_s", Vec3{});
        // Bodies sharing a join name are voxelised onto the shared grid and
        // unioned, so a cell both claim is built once and bonds cross the seam.
        body.join = node.value("join", std::string());
        body.spin_rad_s = vector3(node, "spin_rad_s", Vec3{});
        body.rotation_deg = vector3(node, "rotation_deg", Vec3{});
        body.anchored = node.value("anchored", false);
        // Cut this shape out of its join group instead of adding it.
        body.subtract = node.value("subtract", false);
        // "roll": true derives the spin that rolls without slipping at the
        // speed already given, which is the sign nobody gets right by hand.
        if (node.value("roll", false)) {
            const double radius = 0.5 * body.dimensions_m.x;
            if (radius > 0.0)
                body.spin_rad_s = {body.velocity_m_s.z / radius, 0.0, -body.velocity_m_s.x / radius};
        }
        if (node.contains("color_rgba"))
            body.color_rgba = static_cast<std::uint32_t>(
                std::stoul(node.at("color_rgba").get<std::string>(), nullptr, 16));
        bodies.push_back(std::move(body));
    }
    return bodies;
}

// Declared in the header: see there for why these two are shared.
StepSettings<double> buildSettings(const TileImpactSetup &setup, const Vec3 &origin) {
    const TileImpactRequest &r = setup.request;
    StepSettings<double> s{};
    s.dt = setup.dt_s;
    s.gravity = toV3(r.gravity_m_s2);
    s.constraint_iterations = std::max(1U, r.constraint_iterations);
    s.damping_fraction = setup.compiled.bond_damping > 0.0
        ? 1.0 - std::exp(-setup.compiled.bond_damping * setup.dt_s) : 0.0;
    // A many-object scene has no rigid striker: every object is lattice, and
    // the one that was "dropped" is simply the one given a velocity.
    s.sphere_enabled = setup.multi_body ? 0 : 1;
    s.direct_arithmetic = r.precision == Precision::Double ? 1 : 0;
    s.contact.static_friction = setup.ball_tile.static_friction;
    s.contact.dynamic_friction = setup.ball_tile.dynamic_friction;
    s.contact.restitution = setup.ball_tile.restitution;
    s.contact.restitution_speed_threshold = 0.5;
    s.contact.node_contact_radius = r.node_contact_radius_factor * r.cell_size_m;
    s.contact.contact_margin = 1.0e-5;
    s.contact.prefilter_slack = 0.05 * r.ball_radius_m;
    s.audit_energy = r.audit_energy ? 1 : 0;
    s.plastic_yield_stretch = setup.compiled.yield_stretch;
    s.plastic_hardening = setup.compiled.plastic_hardening_ratio;
    // Node-node contact. The cell is a cube of side `cell`; its contact sphere
    // is the inscribed one, the same radius the support planes hold a cell
    // centre above a surface with, so two cells touch exactly one cell apart --
    // the lattice spacing -- and the rest configuration sits on the threshold.
    // The pair coefficients are tile against tile.
    s.node_contact.mode = r.node_contact == NodeContactMode::Off ? kNodeContactOff
        : (r.node_contact == NodeContactMode::Measure ? kNodeContactMeasure : kNodeContactOn);
    s.node_contact.radius = r.node_contact_radius_factor * r.cell_size_m;
    s.node_contact.skin = r.node_contact_skin_factor * r.cell_size_m;
    s.node_contact.margin = 1.0e-5;
    s.node_contact.restitution = setup.tile_tile.restitution;
    s.node_contact.restitution_speed_threshold = 0.5;
    s.node_contact.static_friction = setup.tile_tile.static_friction;
    s.node_contact.dynamic_friction = setup.tile_tile.dynamic_friction;
    s.node_contact.bucket_mask =
        latticeContactBucketMask(static_cast<std::uint32_t>(setup.matter.nodes.size()));
    const double infinity = std::numeric_limits<double>::infinity();
    // Nodes are cell centres, so a node rests half a cell above a surface.
    const double node_radius = 0.5 * r.cell_size_m;
    if (r.layout == SceneLayout::Flat) {
        SupportPlane<double> ground = makePlane(Vec3{0.0, setup.ground_y, 0.0} - origin, setup.tile_ground, node_radius);
        addFootprint(ground, 0.0, 0.0, infinity, infinity);
        s.support.plane_count = 1;
        s.support.planes[0] = ground;
    } else {
        SupportPlane<double> ledges = makePlane(Vec3{0.0, setup.support_y, 0.0} - origin, setup.tile_ground, node_radius);
        for (const StaticBox &ledge : setup.ledges) {
            const Vec3 relative = ledge.center_m - origin;
            addFootprint(ledges, relative.x, relative.z, 0.5 * ledge.dimensions_m.x, 0.5 * ledge.dimensions_m.z);
        }
        SupportPlane<double> ground = makePlane(Vec3{0.0, setup.ground_y, 0.0} - origin, setup.tile_ground, node_radius);
        addFootprint(ground, 0.0, 0.0, infinity, infinity);
        s.support.plane_count = 2;
        s.support.planes[0] = ledges;
        s.support.planes[1] = ground;
    }
    return s;
}

namespace {
std::uint64_t stepsFor(double milliseconds, double dt) {
    if (milliseconds <= 0.0) return 0;
    return static_cast<std::uint64_t>(std::ceil(milliseconds * 1.0e-3 / dt));
}

} // namespace

std::unique_ptr<LatticeBackend> makeBackend(const TileImpactRequest &r, const LatticeSchedule &schedule) {
    if (r.backend == BackendKind::Cuda)
        return makeCudaLatticeBackend(schedule, r.precision, r.threads_per_block);
    if (r.backend == BackendKind::CpuParallel)
        return makeParallelCpuLatticeBackend(schedule, r.precision, r.cpu_threads);
    return makeCpuLatticeBackend(schedule, r.precision);
}

namespace {
Vec3 nodePosition(const LatticeState &state, std::uint32_t i) {
    return state.origin + Vec3{state.x0[3 * i] + state.u[3 * i], state.x0[3 * i + 1] + state.u[3 * i + 1],
                               state.x0[3 * i + 2] + state.u[3 * i + 2]};
}

// Jolt's impact collector is filled from its worker threads under a mutex, so
// the order events arrive in is a thread-completion order. Every re-entry
// decision is taken on this total order instead, which is a function of the
// contacts themselves: same scene, same choice, on every backend and every run.
bool impactOrder(const ImpactEvent &a, const ImpactEvent &b) {
    if (a.body_a != b.body_a) return a.body_a < b.body_a;
    if (a.body_b != b.body_b) return a.body_b < b.body_b;
    const Vec3 &pa = a.contact_point_world_m, &pb = b.contact_point_world_m;
    if (pa.x != pb.x) return pa.x < pb.x;
    if (pa.y != pb.y) return pa.y < pb.y;
    if (pa.z != pb.z) return pa.z < pb.z;
    if (a.closing_speed_m_s != b.closing_speed_m_s) return a.closing_speed_m_s > b.closing_speed_m_s;
    const Vec3 &na = a.normal_a_to_b, &nb = b.normal_a_to_b;
    if (na.x != nb.x) return na.x < nb.x;
    if (na.y != nb.y) return na.y < nb.y;
    if (na.z != nb.z) return na.z < nb.z;
    return a.available_normal_energy_j > b.available_normal_energy_j;
}

std::vector<std::uint32_t> componentIds(const ActiveMatter &matter, std::size_t *count,
                                        std::size_t *largest_cells, double *largest_mass) {
    const auto components = findConnectedComponents(matter);
    std::vector<std::uint32_t> ids(matter.nodes.size(), 0U);
    for (const auto &component : components)
        for (const std::uint32_t node : component.node_indices) ids[node] = component.id;
    if (count) *count = components.size();
    if (largest_cells) *largest_cells = components.empty() ? 0 : components.front().node_indices.size();
    if (largest_mass) {
        double mass = 0.0;
        if (!components.empty())
            for (const std::uint32_t node : components.front().node_indices) mass += matter.nodes[node].mass_kg;
        *largest_mass = mass;
    }
    return ids;
}

} // namespace

std::unique_ptr<TileImpactSetup> buildTileImpactSetup(const TileImpactRequest &request) {
    auto setup = std::make_unique<TileImpactSetup>();
    TileImpactSetup &s = *setup;
    s.request = request;
    const TileImpactRequest &r = s.request;
    s.multi_body = !r.bodies.empty();
    if (!(r.cell_size_m > 0.0) || !(r.dt_factor > 0.0))
        throw std::invalid_argument("the scene needs a positive cell size and a positive dt factor");
    if (!s.multi_body &&
        (!(r.ball_radius_m > 0.0) ||
         !(r.tile_dimensions_m.x > 0.0) || !(r.tile_dimensions_m.y > 0.0) || !(r.tile_dimensions_m.z > 0.0)))
        throw std::invalid_argument("tile impact request needs positive sizes and a positive dt factor");

    s.tile_material = makeReferenceMaterial(r.tile_material, r.material_seed);
    s.tile_material.failure_law = r.failure_law;
    if (r.hardening_ratio >= 0.0) s.tile_material.hardening_ratio = r.hardening_ratio;
    s.ball_material = makeReferenceMaterial(r.ball_material, r.material_seed);
    s.ground_material = makeReferenceMaterial(r.ground_material, r.material_seed);
    if (r.catalog_material) {
        if (s.tile_material.model != MaterialModel::BrittleBond)
            throw std::invalid_argument("the catalog route needs a BrittleBond preset; use the reference route");
        s.compiled = compileBrittleMaterial(s.tile_material, r.cell_size_m, r.neighbor_horizon_cells);
    } else {
        // withFailureLaw is withStrengthDerivedFailure when the request keeps
        // the strain-threshold law: the same thresholds, bit for bit.
        s.compiled = withFailureLaw(
            compileElasticLatticeReference(s.tile_material, r.cell_size_m, r.neighbor_horizon_cells),
            s.tile_material, r.cell_size_m, r.neighbor_horizon_cells);
    }
    // The plastic law is added last and only when asked for: it sets
    // yield_stretch, which is the one switch StepSettings reads, and it touches
    // no threshold of either failure law.
    if (r.plasticity) s.compiled = withPlasticFlow(s.compiled, s.tile_material);
    if (s.multi_body) {
        // Each body is generated on its own, with its own material, and the
        // results are concatenated. No bond crosses a body, so the objects stay
        // separate; node contact is what lets them meet.
        s.part_assets.reserve(r.bodies.size());
        s.part_materials.reserve(r.bodies.size());
        s.part_definitions.reserve(r.bodies.size());
        double substep_limit = std::numeric_limits<double>::infinity();
        // Bodies are grouped by their join name first. An empty name is its own
        // group of one, which is every scene that does not ask to fuse
        // anything, and those are built exactly as before.
        std::vector<std::vector<std::size_t>> groups;
        std::vector<std::string> group_names;
        for (std::size_t i = 0; i < r.bodies.size(); ++i) {
            const std::string &name = r.bodies[i].join;
            std::size_t found = group_names.size();
            if (!name.empty())
                for (std::size_t g = 0; g < group_names.size(); ++g)
                    if (group_names[g] == name) { found = g; break; }
            if (found == group_names.size()) { group_names.push_back(name); groups.emplace_back(); }
            groups[found].push_back(i);
        }
        s.part_bodies = groups;
        for (const std::vector<std::size_t> &group : groups) {
        // The group takes its material and its name from the first body that
        // adds material, never from one that only cuts.
        std::size_t lead = group.front();
        for (const std::size_t index : group)
            if (!r.bodies[index].subtract) { lead = index; break; }
        const SceneBody &body = r.bodies[lead];
            MaterialDefinition definition = makeReferenceMaterial(body.material, r.material_seed);
            definition.failure_law = r.failure_law;
            if (r.hardening_ratio >= 0.0) definition.hardening_ratio = r.hardening_ratio;
            CompiledBrittleMaterial compiled = withFailureLaw(
                compileElasticLatticeReference(definition, r.cell_size_m, r.neighbor_horizon_cells),
                definition, r.cell_size_m, r.neighbor_horizon_cells);
            if (r.plasticity) compiled = withPlasticFlow(compiled, definition);
            LatticeAsset asset;
            // A sphere goes through the voxel path too, not only a join.
            // generateSphereLattice samples partial occupancy, which leaves rim
            // cells with a fraction of a cell's mass and a sparse, degenerate
            // neighbourhood. Those read fabricated strain and fail on the first
            // substep: a 100 mm iron ball at 10 mm cells broke 5,791 of its
            // 9,477 bonds sitting still on the ground, with 1,263 rank-deficient
            // node reads and its first failure at 0.000 ms, while the same iron
            // as a cube broke none and read exactly zero strain. Whole cells
            // only, above half occupancy, gives the uniform masses the box
            // generator has always had. The staircase it leaves on the surface
            // costs nothing now that a whole body collides as the shape it was
            // authored as.
            const bool tilted = body.rotation_deg.x != 0.0 || body.rotation_deg.y != 0.0 ||
                                body.rotation_deg.z != 0.0;
            const bool voxelised = group.size() > 1 || body.shape != BodyShape::Box || tilted;
            if (voxelised) {
                // Voxelise every shape in the group onto the one shared grid
                // and take the union. A cell two shapes both claim appears
                // once: that is what removing the overlap means here, and it is
                // what lets bonds cross the seam and make them one object.
                std::vector<GridCoord> cells;
                std::vector<GridCoord> removed;
                for (const std::size_t index : group) {
                    const SceneBody &part = r.bodies[index];
                    const double widest = std::max(part.dimensions_m.x, part.dimensions_m.z);
                    const Vec3 half =
                        part.shape == BodyShape::Sphere
                            ? Vec3{0.5 * part.dimensions_m.x, 0.5 * part.dimensions_m.x,
                                   0.5 * part.dimensions_m.x}
                        : part.shape == BodyShape::Cone
                            ? Vec3{0.5 * widest, 0.5 * part.dimensions_m.y, 0.5 * widest}
                            : Vec3{0.5 * part.dimensions_m.x, 0.5 * part.dimensions_m.y,
                                   0.5 * part.dimensions_m.z};
                    const double radius = 0.5 * part.dimensions_m.x;
                    // A tilted box reaches further than its own half extents,
                    // so the search covers its diagonal.
                    const double reach = length(half);
                    const auto lo = [&](double centre, double) {
                        return static_cast<int>(std::floor((centre - reach) / r.cell_size_m));
                    };
                    const auto hi = [&](double centre, double) {
                        return static_cast<int>(std::ceil((centre + reach) / r.cell_size_m));
                    };
                    for (int gx = lo(part.center_m.x, half.x); gx <= hi(part.center_m.x, half.x); ++gx)
                    for (int gy = lo(part.center_m.y, half.y); gy <= hi(part.center_m.y, half.y); ++gy)
                    for (int gz = lo(part.center_m.z, half.z); gz <= hi(part.center_m.z, half.z); ++gz) {
                        const Vec3 centre{(gx + 0.5) * r.cell_size_m,
                                          (gy + 0.5) * r.cell_size_m,
                                          (gz + 0.5) * r.cell_size_m};
                        // Test the cell in the body's own frame, so a tilted
                        // box keeps its true extents and only its cells change.
                    const Vec3 local = rotateDegrees(centre - part.center_m,
                                                         {-part.rotation_deg.x, -part.rotation_deg.y,
                                                          -part.rotation_deg.z});
                    bool inside = false;
                    if (part.shape == BodyShape::Sphere) {
                        inside = length(local) <= radius;
                    } else if (part.shape == BodyShape::Cone) {
                        // Its width runs from the bottom diameter to the top
                        // one, so an upside-down cone is simply a wider top.
                        const double h = part.dimensions_m.y;
                        if (std::abs(local.y) <= 0.5 * h) {
                            const double t = h > 0.0 ? (local.y + 0.5 * h) / h : 0.0;
                            const double r = 0.5 * (part.dimensions_m.z +
                                                    t * (part.dimensions_m.x - part.dimensions_m.z));
                            inside = std::hypot(local.x, local.z) <= r;
                        }
                    } else {
                        inside = std::abs(local.x) <= half.x && std::abs(local.y) <= half.y &&
                                 std::abs(local.z) <= half.z;
                    }
                        if (!inside) continue;
                        if (part.subtract) removed.push_back({gx, gy, gz});
                        else cells.push_back({gx, gy, gz});
                    }
                }
                if (!removed.empty()) {
                    // What is cut is cut wherever it lands, so the order the
                    // bodies were written in does not change the shape.
                    // An ordered set of plain triples: this needs no hash and
                    // borrows no type from the generators.
                    std::set<std::tuple<int, int, int>> gone;
                    for (const GridCoord &c : removed) gone.emplace(c.x, c.y, c.z);
                    std::vector<GridCoord> kept;
                    kept.reserve(cells.size());
                    for (const GridCoord &c : cells)
                        if (!gone.contains({c.x, c.y, c.z})) kept.push_back(c);
                    cells.swap(kept);
                }
                if (cells.empty())
                    throw std::invalid_argument("joined group \"" + body.join +
                                                "\" has nothing left after what it cuts away");
                asset = generateVoxelLattice({std::move(cells), r.cell_size_m, r.neighbor_horizon_cells},
                                             compiled);
            } else {
                asset =
                    body.shape == BodyShape::Sphere
                        ? generateSphereLattice({0.5 * body.dimensions_m.x, r.cell_size_m,
                                                 r.neighbor_horizon_cells, 3},
                                                compiled)
                        : generateBoxTileLattice({body.dimensions_m, r.cell_size_m, r.neighbor_horizon_cells},
                                                 compiled);
            }
            if (asset.nodes.empty())
                throw std::invalid_argument("body \"" + body.name + "\" is smaller than one cell");
            // One lattice has one clock, so the scene steps at the smallest
            // bound any of its objects asks for. A stiff light object sets it.
            const LatticeResolutionLimit part_limit = measureLatticeResolutionLimit(asset, compiled);
            if (part_limit.explicit_substep_limit_s > 0.0)
                substep_limit = std::min(substep_limit, part_limit.explicit_substep_limit_s);
            s.part_definitions.push_back(definition);
            s.part_materials.push_back(compiled);
            s.part_assets.push_back(std::move(asset));
        }
        std::vector<LatticePart> parts;
        parts.reserve(r.bodies.size());
        for (std::size_t g = 0; g < groups.size(); ++g) {
            // A union is built in world cells already, so it is placed at the
            // centre it came out with; a single shape is placed where it asked.
            const Vec3 centre = groups[g].size() > 1
                ? s.part_assets[g].rest_center_of_mass_m
                : r.bodies[groups[g].front()].center_m;
            parts.push_back({&s.part_assets[g], centre, s.part_materials[g].density_kg_m3});
        }
        MergedLattice merged = mergeLattices(parts);
        s.asset = std::move(merged.asset);
        s.part_of_node = std::move(merged.part_of_node);
        s.node_mass_kg = std::move(merged.node_mass_kg);
        // The scalar settings -- bond damping and the plastic yield law -- are
        // one number for the whole lattice, so they come from the first body.
        // Every per-bond and per-node quantity is that body's own.
        s.compiled = s.part_materials.front();
        s.tile_material = s.part_definitions.front();
        s.limit = measureLatticeResolutionLimit(s.asset, s.compiled);
        s.limit.explicit_substep_limit_s = substep_limit;
        s.layout = {};
    } else {
    s.asset = generateBoxTileLattice({r.tile_dimensions_m, r.cell_size_m, r.neighbor_horizon_cells},
                                 s.compiled, &s.layout);
    s.limit = measureLatticeResolutionLimit(s.asset, s.compiled);
    }
    if (!(s.limit.explicit_substep_limit_s > 0.0))
        throw std::runtime_error("lattice has no resolution limit; is the material stiffness zero?");
    if (r.loose_cells) {
        // The substep limit above is the bonded lattice's, so the loose heap is
        // stepped at the same rate as the material it is made of.
        s.asset.bonds.clear();
        s.asset.adjacent_bond_indices.clear();
        s.asset.adjacency_offsets.assign(s.asset.nodes.size() + 1U, 0U);
    }
    s.dt_s = r.dt_factor * s.limit.explicit_substep_limit_s;

    s.ground_y = 0.0;
    s.support_y = r.layout == SceneLayout::Flat ? 0.0 : r.ledge_height_m;
    s.tile_bottom_y = s.support_y + r.tile_drop_m;
    s.tile_top_y = s.tile_bottom_y + r.tile_dimensions_m.y;
    // A merged lattice already carries scene coordinates in its rest positions,
    // so placing about its own centre of mass leaves every body where the
    // caller put it.
    const Vec3 tile_center = s.multi_body
        ? s.asset.rest_center_of_mass_m
        : Vec3{0.0, s.tile_bottom_y + 0.5 * r.tile_dimensions_m.y, 0.0};
    s.origin = tile_center;
    if (r.layout == SceneLayout::Bridge) {
        // Ledges under the ends of the tile's long (x) axis, half under the
        // tile and half outside it, spanning the whole z width.
        const double ledge_depth = r.tile_dimensions_m.z + 2.0 * r.cell_size_m;
        for (const double sign : {-1.0, 1.0}) {
            s.ledges.push_back({{sign * 0.5 * r.tile_dimensions_m.x, 0.5 * r.ledge_height_m, 0.0},
                                {2.0 * r.ledge_width_m, r.ledge_height_m, ledge_depth}});
        }
    }

    ActiveMatter &matter = s.matter;
    matter.body_id = 2;
    matter.asset = &s.asset;
    matter.material = s.compiled;
    matter.nodes.reserve(s.asset.nodes.size());
    matter.reference_positions_world_m.reserve(s.asset.nodes.size());
    for (std::size_t i = 0; i < s.asset.nodes.size(); ++i) {
        const LatticeNodeRest &node = s.asset.nodes[i];
        const Vec3 position = tile_center + (node.local_position_m - s.asset.rest_center_of_mass_m);
        // Mass is per node so that one lattice can hold several densities; a
        // single-tile scene gets exactly what it always got.
        const double mass = s.multi_body ? s.node_mass_kg[i]
                                         : node.represented_volume_m3 * s.compiled.density_kg_m3;
        // The object that was "dropped" is the one that starts with a velocity,
        // and a spin carries every node around the body's centre with it.
        Vec3 velocity{};
        Vec3 cell_spin{};
        if (s.multi_body) {
            const std::uint32_t group = s.part_of_node[i];
            const SceneBody &owner = r.bodies[s.part_bodies[group].front()];
            velocity = owner.velocity_m_s + cross(owner.spin_rad_s, position - owner.center_m);
            // Every point of a rigidly turning body turns with it, cells
            // included. The handoff's inertia counts each cell's own spin
            // (m h^2 / 6 on the diagonal) but its angular momentum only counts
            // the spin a cell is actually carrying, so leaving this at zero
            // divides by an inertia the momentum was never given.
            cell_spin = owner.spin_rad_s;
        }
        matter.nodes.push_back({position, position, velocity, mass, cell_spin});
        matter.reference_positions_world_m.push_back(position);
    }
    matter.bonds.resize(s.asset.bonds.size());

    s.ball_tile = combineContactMaterials(compileContactMaterial(s.ball_material), compileContactMaterial(s.tile_material));
    s.tile_ground = combineContactMaterials(compileContactMaterial(s.tile_material), compileContactMaterial(s.ground_material));
    s.ball_ground = combineContactMaterials(compileContactMaterial(s.ball_material), compileContactMaterial(s.ground_material));
    s.tile_tile = combineContactMaterials(compileContactMaterial(s.tile_material), compileContactMaterial(s.tile_material));

    const double volume = 4.0 / 3.0 * std::numbers::pi * std::pow(r.ball_radius_m, 3.0);
    s.sphere_world.center = {r.ball_offset_x_m, s.tile_top_y + r.ball_radius_m + r.ball_gap_m, r.ball_offset_z_m};
    s.sphere_world.velocity = {0.0, -r.ball_speed_m_s, 0.0};
    s.sphere_world.angular_velocity = {0.0, 0.0, 0.0};
    s.sphere_world.radius = r.ball_radius_m;
    s.sphere_world.mass = volume * s.ball_material.density_kg_m3;
    s.sphere_world.inertia = 0.4 * s.sphere_world.mass * r.ball_radius_m * r.ball_radius_m;

    s.settings_scene = buildSettings(s, s.origin);
    s.settings_world = buildSettings(s, Vec3{});

    if (s.multi_body) {
        // Slab decomposition reads a box's z layers, which a merged lattice has
        // no single version of. The one-block schedule works for any lattice
        // and still colours the bonds, which is where the parallelism is.
        s.schedule = buildLatticeSchedule(s.asset);
    } else {
        std::vector<std::uint32_t> slabs = boxLatticeSlabs(s.layout, r.neighbor_horizon_cells, std::max(1U, r.blocks));
        s.schedule = buildLatticeSchedule(s.asset, slabs);
    }

    s.quiet_steps = stepsFor(r.quiet_ms, s.dt_s);
    s.min_steps = stepsFor(r.min_ms, s.dt_s);
    s.max_steps = std::max<std::uint64_t>(1, stepsFor(r.max_ms, s.dt_s));
    s.no_failure_steps = stepsFor(r.no_failure_ms, s.dt_s);
    s.energy_flat_steps = stepsFor(r.energy_flat_ms, s.dt_s);
    s.calm_steps = stepsFor(r.calm_ms, s.dt_s);
    return setup;
}

TileImpactResult runTileImpact(const TileImpactRequest &request, std::string *log) {
    const auto wall_begin = Clock::now();
    auto setup_ptr = buildTileImpactSetup(request);
    TileImpactSetup &setup = *setup_ptr;
    const TileImpactRequest &r = setup.request;
    TileImpactResult result;
    TileImpactMeasurements &m = result.measurements;
    std::ostringstream notes;

    LatticeState state = buildLatticeState(setup.matter, setup.schedule, setup.origin);
    SphereState<double> sphere = setup.sphere_world;
    sphere.center = sphere.center - toV3(setup.origin);
    std::unique_ptr<LatticeBackend> backend = makeBackend(r, setup.schedule);
    m.backend_name = backend->name();
    m.cells = setup.asset.nodes.size();
    m.bonds = setup.asset.bonds.size();
    m.colors = setup.schedule.color_count;
    m.blocks = setup.schedule.block_count;
    m.boundary_bonds = setup.schedule.boundary_bond_count;
    m.cell_size_m = r.cell_size_m;
    m.tile_mass_kg = setup.asset.total_mass_kg;
    m.ball_mass_kg = setup.sphere_world.mass;
    m.dt_s = setup.dt_s;
    m.substep_limit_s = setup.limit.explicit_substep_limit_s;
    m.fastest_period_s = setup.limit.fastest_mode_period_s;

    // Lattice phase.
    const auto lattice_begin = Clock::now();
    backend->upload(state, setup.settings_scene, sphere);
    RunControl control{};
    control.max_steps = setup.max_steps;
    control.quiet_steps = setup.quiet_steps;
    control.min_steps = setup.min_steps;
    control.no_failure_steps = setup.no_failure_steps;
    control.energy_flat_steps = setup.energy_flat_steps;
    control.energy_flat_fraction = setup.request.energy_flat_fraction;
    control.calm_steps = setup.calm_steps;
    control.calm_damage_margin = setup.request.calm_damage_margin;
    control.max_frames = std::max(1U, r.lattice_frames);
    control.capture_stride = std::max<std::uint64_t>(1, setup.max_steps / control.max_frames);
    control.steps_per_launch = r.steps_per_launch;
    const RunStatus status = backend->run(control);
    std::vector<FrameCapture> captures = backend->takeFrames();
    backend->download(state, sphere);
    const auto lattice_end = Clock::now();

    m.lattice_steps = status.total_steps;
    m.lattice_simulated_s = static_cast<double>(status.total_steps) * setup.dt_s;
    m.lattice_wall_s = seconds(lattice_begin, lattice_end);
    m.lattice_kernel_s = status.kernel_seconds;
    m.launches = status.launches;
    m.exit_reason = status.exit_reason;
    m.failure_rounds = status.failure_rounds;
    m.broken_bonds = status.broken_bonds;
    m.removed_energy_j = status.removed_energy_j;
    m.contact = status.contact;
    m.node_contact = status.node_contact;
    m.damping_dissipated_j = status.damping_dissipated_j;
    m.striker_dissipated_j = status.striker_dissipated_j;
    m.energy_audited = status.energy_audited;
    if (status.last_failure_step != std::numeric_limits<std::uint64_t>::max())
        m.last_failure_s = static_cast<double>(status.last_failure_step) * setup.dt_s;
    if (status.first_failure_step != std::numeric_limits<std::uint64_t>::max())
        m.first_failure_s = static_cast<double>(status.first_failure_step) * setup.dt_s;
    for (unsigned p = 0; p < kPhaseCount; ++p) m.phase_seconds[p] = status.phase_seconds[p];
    m.shared_memory_positions = status.shared_memory_positions;
    m.shared_memory_bytes = status.shared_memory_bytes;
    m.max_tensile_stretch = status.max_tensile_stretch;
    m.max_damage = status.max_damage;
    m.max_compressive_strain = status.max_compressive_strain;
    m.max_shear_strain = status.max_shear_strain;
    m.rank_deficient_nodes = status.rank_deficient_nodes;
    m.plasticity_enabled = setup.compiled.yield_stretch > 0.0;
    m.yield_stretch = setup.compiled.yield_stretch;
    m.plastic_hardening_ratio = setup.compiled.plastic_hardening_ratio;
    m.yield_strength_pa = setup.tile_material.yield_strength_pa;
    m.plastic_work_j = status.plastic_work_j;
    m.max_plastic_stretch = status.max_plastic_stretch;
    for (std::size_t k = 0; k < state.plastic_extension.size(); ++k) {
        const double p = state.plastic_extension[k];
        if (p == 0.0) continue;
        ++m.plastic_bonds;
        m.plastic_extension_total_m += std::abs(p);
    }
    m.elastic_energy_j = latticeStateElasticEnergy(state);
    m.lattice_kinetic_j = latticeStateKineticEnergy(state);
    m.initial_kinetic_j = 0.5 * setup.sphere_world.mass *
        (setup.sphere_world.velocity.x * setup.sphere_world.velocity.x +
         setup.sphere_world.velocity.y * setup.sphere_world.velocity.y +
         setup.sphere_world.velocity.z * setup.sphere_world.velocity.z);
    m.bond_updates_per_s = m.lattice_wall_s > 0.0
        ? static_cast<double>(m.bonds) * static_cast<double>(status.total_steps) / m.lattice_wall_s : 0.0;
    m.failure_law = std::string(bondFailureLawName(setup.compiled.failure_law));
    m.critical_stretch = setup.compiled.damage_end_stretch;
    m.energy_scaled_stretch = setup.compiled.energy_scaled_stretch;
    m.strength_stretch = withStrengthDerivedFailure(
        compileElasticLatticeReference(setup.tile_material, r.cell_size_m, r.neighbor_horizon_cells),
        setup.tile_material).damage_end_stretch;
    m.strength_bound_active = setup.compiled.strength_bound_active;
    {
        const LatticeHorizonGeometry g = latticeHorizonGeometry(r.neighbor_horizon_cells);
        m.lattice_crack_energy_j_m2 = g.crossings_100 * setup.tile_material.young_modulus_pa * r.cell_size_m *
            m.critical_stretch * m.critical_stretch / (2.0 * static_cast<double>(r.neighbor_horizon_cells));
    }
    {
        const std::vector<std::uint32_t> first = backend->firstFailureBonds();
        m.first_failure_bonds = first.size();
        if (!first.empty()) {
            Vec3 centroid{};
            for (const std::uint32_t k : first) {
                const BondRest &bond = setup.asset.bonds[setup.schedule.bond_order[k]];
                centroid += 0.5 * (setup.matter.reference_positions_world_m[bond.node_a] +
                                   setup.matter.reference_positions_world_m[bond.node_b]);
            }
            centroid = centroid / static_cast<double>(first.size());
            m.first_failure_centroid_m = centroid;
            m.first_failure_depth_m = setup.tile_top_y - centroid.y;
            m.first_failure_radius_m = std::hypot(centroid.x - r.ball_offset_x_m, centroid.z - r.ball_offset_z_m);
        }
    }

    // Frames of the lattice phase; the first failure time comes from them.
    const Vec3 origin = setup.origin;
    const std::size_t N = m.cells, B = m.bonds;
    std::uint32_t previous_broken = 0;
    for (const FrameCapture &capture : captures) {
        RecordedFrame frame;
        frame.time_s = static_cast<double>(capture.step) * setup.dt_s;
        frame.phase = "lattice";
        frame.cell_positions.resize(N);
        frame.cell_orientations.assign(N, Quat{});
        for (std::size_t i = 0; i < N; ++i)
            frame.cell_positions[i] = origin + Vec3{state.x0[3 * i] + capture.u[3 * i],
                                                    state.x0[3 * i + 1] + capture.u[3 * i + 1],
                                                    state.x0[3 * i + 2] + capture.u[3 * i + 2]};
        frame.ball_center = origin + toVec3(capture.sphere.center);
        frame.bond_alive.resize(B);
        frame.bond_damage.resize(B);
        std::uint32_t broken = 0;
        for (std::size_t k = 0; k < B; ++k) {
            const std::uint32_t o = setup.schedule.bond_order[k];
            frame.bond_alive[o] = capture.alive[k];
            frame.bond_damage[o] = capture.damage[k];
            if (!capture.alive[k]) ++broken;
        }
        previous_broken = broken;
        frame.fracture_count = broken;
        // Component ids from the captured aliveness.
        ActiveMatter snapshot = setup.matter;
        for (std::size_t o = 0; o < B; ++o) snapshot.bonds[o].alive = frame.bond_alive[o] != 0;
        frame.component_ids = componentIds(snapshot, nullptr, nullptr, nullptr);
        result.frames.push_back(std::move(frame));
    }
    (void)previous_broken;

    // The unloaded shape. Same solver, same state, loads removed: the striker
    // off, gravity zero, the support planes gone, node contact off and a strong
    // radial bond damping, run until the plate stops. What is left is the shape
    // the material holds under no load, which is what a dent is. With plasticity
    // off every bond returns to its original rest length and the plate relaxes
    // flat, which is the control.
    if (r.relax_steps > 0) {
        LatticeState relaxed = state;
        std::fill(relaxed.v.begin(), relaxed.v.end(), 0.0);
        StepSettings<double> relax = setup.settings_scene;
        relax.gravity = {0.0, 0.0, 0.0};
        relax.sphere_enabled = 0;
        relax.damping_fraction = std::clamp(r.relax_damping_fraction, 0.0, 1.0);
        relax.node_contact.mode = kNodeContactOff;
        relax.support.plane_count = 0;
        relax.audit_energy = 0;
        std::unique_ptr<LatticeBackend> probe = makeBackend(r, setup.schedule);
        SphereState<double> parked = sphere;
        probe->upload(relaxed, relax, parked);
        RunControl relax_control{};
        relax_control.max_steps = r.relax_steps;
        relax_control.steps_per_launch = r.steps_per_launch;
        const RunStatus relax_status = probe->run(relax_control);
        probe->download(relaxed, parked);
        m.relax_steps = relax_status.total_steps;
        m.relax_broken_bonds = relax_status.broken_bonds;
        m.relax_plastic_work_j = relax_status.plastic_work_j;
        m.relax_elastic_energy_j = latticeStateElasticEnergy(relaxed);
        m.relax_kinetic_j = latticeStateKineticEnergy(relaxed);
        // Heights against each node's own reference height, referred to the mean
        // of the two end columns so a rigid drift of the now-free plate cancels.
        const auto profile = [&](const std::vector<double> &u) {
            double x_low = std::numeric_limits<double>::infinity(), x_high = -x_low;
            for (std::size_t i = 0; i < N; ++i) {
                x_low = std::min(x_low, state.x0[3 * i]);
                x_high = std::max(x_high, state.x0[3 * i]);
            }
            double ends = 0.0;
            std::size_t end_count = 0;
            std::size_t strike = 0;
            double best = std::numeric_limits<double>::infinity();
            for (std::size_t i = 0; i < N; ++i) {
                const double x = state.x0[3 * i], z = state.x0[3 * i + 2];
                if (x <= x_low + 1.0e-9 || x >= x_high - 1.0e-9) { ends += u[3 * i + 1]; ++end_count; }
                const double radius = std::hypot(origin.x + x - r.ball_offset_x_m,
                                                 origin.z + z - r.ball_offset_z_m);
                const double key = radius - 1.0e-6 * state.x0[3 * i + 1];
                if (key < best) { best = key; strike = i; }
            }
            const double reference = end_count > 0 ? ends / static_cast<double>(end_count) : 0.0;
            double deepest = 0.0;
            for (std::size_t i = 0; i < N; ++i) deepest = std::max(deepest, reference - u[3 * i + 1]);
            return std::pair<double, double>{reference - u[3 * strike + 1], deepest};
        };
        const auto after = profile(relaxed.u);
        const auto before = profile(state.u);
        m.permanent_dent_m = after.first;
        m.permanent_max_dip_m = after.second;
        m.loaded_dent_m = before.first;
    }

    // Permanent deformation. The reference material route compiles no bond
    // damping, so a struck plate that does not break rings for the whole
    // lattice phase; a single frame is therefore not a deflection. What is
    // reported is the MEAN over the last third of the captured lattice frames,
    // with half the peak-to-peak of the same window alongside it as the size of
    // the ringing the mean is taken through. An elastic plate rings about zero;
    // a plate that has flowed rings about its dent.
    {
        std::vector<std::size_t> lattice_frames;
        for (std::size_t f = 0; f < result.frames.size(); ++f)
            if (result.frames[f].phase == "lattice") lattice_frames.push_back(f);
        if (lattice_frames.size() >= 3) {
            // The node nearest the strike axis, highest one where several tie.
            std::size_t strike = 0;
            double best = std::numeric_limits<double>::infinity();
            for (std::size_t i = 0; i < N; ++i) {
                const Vec3 rest = origin + Vec3{state.x0[3 * i], state.x0[3 * i + 1], state.x0[3 * i + 2]};
                const double radius = std::hypot(rest.x - r.ball_offset_x_m, rest.z - r.ball_offset_z_m);
                const double key = radius - 1.0e-6 * rest.y;
                if (key < best) { best = key; strike = i; }
            }
            const std::size_t first = lattice_frames.size() - lattice_frames.size() / 3;
            double sum_strike = 0.0, sum_plate = 0.0;
            double low = std::numeric_limits<double>::infinity(), high = -low;
            std::size_t used = 0;
            for (std::size_t k = first; k < lattice_frames.size(); ++k) {
                const RecordedFrame &frame = result.frames[lattice_frames[k]];
                if (frame.cell_positions.size() != N) continue;
                const double strike_y = frame.cell_positions[strike].y -
                    (origin.y + state.x0[3 * strike + 1]);
                double plate = 0.0;
                for (std::size_t i = 0; i < N; ++i)
                    plate += frame.cell_positions[i].y - (origin.y + state.x0[3 * i + 1]);
                plate /= static_cast<double>(N);
                sum_strike += strike_y;
                sum_plate += plate;
                low = std::min(low, strike_y - plate);
                high = std::max(high, strike_y - plate);
                ++used;
            }
            if (used > 0) {
                m.dent_frames = used;
                m.strike_deflection_mean_m = sum_strike / static_cast<double>(used);
                m.plate_deflection_mean_m = sum_plate / static_cast<double>(used);
                m.dent_depth_m = m.plate_deflection_mean_m - m.strike_deflection_mean_m;
                m.strike_deflection_amplitude_m = 0.5 * (high - low);
            }
        }
    }

    // Handoff: connected components -> rigid fragments -> Jolt.
    const auto handoff_begin = Clock::now();
    writeBackLatticeState(state, setup.schedule, setup.matter);
    // The permanent extension a bond carries is state, not a derived quantity,
    // and ActiveBondState has nowhere to put it, so it is kept here in the
    // asset's own bond order. A re-entry reads it back, which is what stops a
    // plate that has already flowed from coming back unyielded.
    std::vector<double> plastic_extension_m(B, 0.0), plastic_strain_m(B, 0.0);
    for (std::size_t k = 0; k < B; ++k) {
        plastic_extension_m[setup.schedule.bond_order[k]] = state.plastic_extension[k];
        plastic_strain_m[setup.schedule.bond_order[k]] = state.plastic_strain[k];
    }
    const auto components = findConnectedComponents(setup.matter);
    m.components = components.size();
    if (!components.empty()) {
        m.largest_piece_cells = components.front().node_indices.size();
        for (const std::uint32_t node : components.front().node_indices)
            m.largest_piece_mass_kg += setup.matter.nodes[node].mass_kg;
    }
    {
        const BondFailureModeCounts modes = countBondFailureModes(setup.matter);
        m.tensile_failures = modes.tensile;
        m.compressive_failures = modes.compressive;
        m.shear_failures = modes.shear;
        double small_mass = 0.0;
        for (const auto &component : components) {
            double mass = 0.0;
            for (const std::uint32_t node : component.node_indices) mass += setup.matter.nodes[node].mass_kg;
            if (mass >= 0.01 * m.tile_mass_kg) ++m.pieces_over_1pct; else small_mass += mass;
            if (mass >= 0.05 * m.tile_mass_kg) ++m.pieces_over_5pct;
        }
        m.mass_fraction_under_1pct = m.tile_mass_kg > 0.0 ? small_mass / m.tile_mass_kg : 0.0;
    }
    FragmentBuildResult build = buildFragmentRepresentations(setup.matter, components, {
        .first_body_id = 1000,
        .maximum_rigid_fragments = std::max<std::size_t>(1, components.size()),
        .minimum_nodes_per_rigid_fragment = 1,
        .maximum_collision_points = 192,
        .friction = setup.tile_ground.dynamic_friction,
        .restitution = setup.tile_ground.restitution,
    });
    // A component that is exactly one whole authored body collides as the shape
    // that was asked for rather than as a hull of its cells. Only while it is
    // whole: the moment it loses a cell it is a broken piece and the hull is its
    // real surface. Joined groups keep the hull, since their shape is the union
    // and no primitive describes it.
    if (setup.multi_body) {
        std::vector<std::size_t> part_size(setup.part_bodies.size(), 0);
        for (const std::uint32_t part : setup.part_of_node) ++part_size[part];
        std::size_t fragment_index = 0;
        for (const auto &component : components) {
            if (fragment_index >= build.rigid_fragments.size()) break;
            RigidFragmentDescription &fragment = build.rigid_fragments[fragment_index];
            if (fragment.source_node_count != component.node_indices.size()) continue;
            ++fragment_index;
            if (component.node_indices.empty()) continue;
            const std::uint32_t part = setup.part_of_node[component.node_indices.front()];
            bool whole = part_size[part] == component.node_indices.size();
            for (const std::uint32_t node : component.node_indices)
                if (setup.part_of_node[node] != part) { whole = false; break; }
            if (!whole) continue;
            // Anchoring belongs to the group, however many shapes made it: a
            // bowl is three shapes joined and is still scenery. Only the
            // authored collision primitive needs a single shape, because a
            // union is not a box or a sphere.
            const SceneBody &lead = r.bodies[setup.part_bodies[part].front()];
            fragment.anchored = lead.anchored;
            for (const std::size_t index : setup.part_bodies[part])
                if (r.bodies[index].anchored) fragment.anchored = true;
            if (setup.part_bodies[part].size() != 1) continue;
            const SceneBody &body = lead;
            // A cone is convex, so the hull of its cells is already its true
            // surface and it needs no authored primitive.
            if (body.shape == BodyShape::Cone) continue;
            fragment.primitive = body.shape == BodyShape::Sphere ? FragmentPrimitive::Sphere
                                                                 : FragmentPrimitive::Box;
            fragment.primitive_dimensions_m = body.dimensions_m;
            rotationQuaternion(body.rotation_deg, fragment.primitive_rotation_wxyz);
        }
    }
    m.rigid_fragments = build.rigid_fragments.size();
    m.debris_particles = build.debris_particles.size();

    // Jolt's contact capacity is an allocation, not a law: a crushed tile
    // hands over hundreds of pieces and the default 8192 constraints
    // overflowed at about 300 of them (Jolt then refuses the step rather
    // than dropping contacts). Sized from the piece count within the
    // world's own bounds; the default worker count is kept.
    const auto clampCapacity = [](std::size_t value, unsigned low, unsigned high) {
        return static_cast<unsigned>(std::clamp<std::size_t>(value, low, high));
    };
    const RigidContactCapacity capacity{
        clampCapacity(64U * components.size(), 16384U, 262144U),
        clampCapacity(128U * components.size(), 8192U, 65536U)};
    JoltWorld world(std::clamp(std::thread::hardware_concurrency(), 1U, 64U), capacity);
    world.setGravity(r.gravity_m_s2);
    if (r.refracture) {
        // Observation only: the collector reads the manifolds Jolt has already
        // solved and changes no contact law, setting or response. It is turned
        // on ONLY here, so a run without re-fracture does not even build the
        // events. The detailed mode is what makes the ground's persisted
        // contacts visible -- a fragment landing on a corner is a persisted
        // support contact, not a fresh one.
        world.setImpactObservationsEnabled(true);
        world.setDetailedImpactObservations(true);
    }
    world.addSupportSurface({
        .frame = makeSupportPlane({0.0, setup.ground_y, 0.0}, {0.0, 1.0, 0.0}),
        .material = setup.ground_material,
        .half_length_tangent_m = 4.0,
        .half_length_bitangent_m = 4.0,
        .thickness_m = 0.5,
    });
    MatterBodyId next_static = 900;
    for (const StaticBox &ledge : setup.ledges) {
        world.addBox({.body_id = next_static++, .dimensions_m = ledge.dimensions_m,
                      .material = setup.ground_material,
                      .state = {.center_of_mass_world_m = ledge.center_m}, .fixed = true});
    }
    constexpr MatterBodyId kBallId = 1;
    const Vec3 ball_center = origin + toVec3(sphere.center);
    // The rigid striker belongs to the single-tile lane. A many-object scene
    // has no striker -- whatever is moving is one of its own bodies -- and this
    // was adding one anyway: an invisible ball that the recorder does not draw
    // (the "ball" body is written only when !many) but that Jolt still
    // simulates. The contact ledger found it landing on a bowling lane at
    // 4.05 m/s with 12.5 N.s of impulse, in a scene nobody put a ball in.
    if (!setup.multi_body)
        world.addBall({.body_id = kBallId, .radius_m = r.ball_radius_m, .material = setup.ball_material,
                       .position_world_m = ball_center, .linear_velocity_m_s = toVec3(sphere.velocity),
                       .angular_velocity_rad_s = toVec3(sphere.angular_velocity),
                       .mass_override_kg = setup.sphere_world.mass, .sphere_inertia_factor = 0.4});
    world.addFragments(build.rigid_fragments);
    // Cell -> piece mapping and the cells' offsets in the piece's frame. A
    // "piece" is a rigid body that owns a set of the tile's cells; the handoff
    // makes one per component and a re-entry replaces one by the pieces it
    // became, so the recording and the trigger keep working across both.
    struct RigidPiece {
        MatterBodyId body_id{};
        std::uint32_t component_id{};
        std::vector<std::uint32_t> nodes;
        std::vector<Vec3> offsets;
        // The trigger's per-fragment constants, computed once here so that a
        // contact costs four multiplies and a compare.
        FragmentFractureLimits limits{};
    };
    std::vector<RigidPiece> pieces;
    std::vector<std::int32_t> cell_fragment(N, -1);
    std::vector<Vec3> cell_offset(N);
    std::vector<std::uint32_t> handoff_component = componentIds(setup.matter, nullptr, nullptr, nullptr);
    std::vector<std::uint32_t> live_component = handoff_component;
    {
        std::size_t fragment_index = 0;
        // buildFragmentRepresentations visits components sorted the same way
        // findConnectedComponents already sorted them; rigid ones keep that order.
        for (const auto &component : components) {
            if (fragment_index >= build.rigid_fragments.size()) break;
            const RigidFragmentDescription &fragment = build.rigid_fragments[fragment_index];
            if (fragment.source_node_count != component.node_indices.size()) continue;
            RigidPiece piece;
            piece.body_id = fragment.body_id;
            piece.component_id = component.id;
            for (const std::uint32_t node : component.node_indices) {
                cell_fragment[node] = static_cast<std::int32_t>(fragment_index);
                cell_offset[node] = setup.matter.nodes[node].position_world_m -
                                    fragment.mass_properties.center_of_mass_world_m;
                piece.nodes.push_back(node);
                piece.offsets.push_back(cell_offset[node]);
            }
            if (r.refracture)
                piece.limits = fragmentFractureLimits(setup.matter, piece.nodes,
                                                      setup.tile_material.density_kg_m3,
                                                      setup.tile_material.young_modulus_pa);
            pieces.push_back(std::move(piece));
            ++fragment_index;
        }
    }
    std::unordered_map<MatterBodyId, std::size_t> piece_of_body;
    for (std::size_t p = 0; p < pieces.size(); ++p) piece_of_body[pieces[p].body_id] = p;
    // Every rigid body under the name the request gave it, so a contact can be
    // reported as "ball (iron) reached pin3 (glass)" rather than by body id. A
    // piece that broke off something keeps its parent's name with a marker,
    // because "a piece of the plate landed" is the true statement.
    std::unordered_map<MatterBodyId, std::string> label_of_body;
    for (const RigidPiece &piece : pieces) {
        std::string name = setup.multi_body
                               ? std::string("piece")
                               : std::string(materialPresetName(r.tile_material)) + " tile";
        if (setup.multi_body && !piece.nodes.empty() &&
            piece.nodes.front() < setup.part_of_node.size()) {
            const std::uint32_t part = setup.part_of_node[piece.nodes.front()];
            if (part < setup.part_bodies.size() && !setup.part_bodies[part].empty()) {
                const SceneBody &body = r.bodies[setup.part_bodies[part].front()];
                name = body.name + " (" + std::string(materialPresetName(body.material)) + ")";
                // A component smaller than the part it came from is a fragment.
                std::size_t part_nodes = 0;
                for (const std::uint32_t owner : setup.part_of_node)
                    if (owner == part) ++part_nodes;
                if (piece.nodes.size() < part_nodes) name += " [piece]";
            }
        }
        label_of_body[piece.body_id] = name;
    }
    // The rigid strikers exist only in the single-tile lane. A many-object scene
    // has none, and its pieces are numbered from 1, so naming those ids here
    // would rename a piece after a ball that is not in the scene.
    if (!setup.multi_body) {
        label_of_body[kBallId] = std::string(materialPresetName(r.ball_material)) + " ball";
        // kSecondBallId is declared further down with the second striker; 2 is
        // its value and the ledger only needs the name.
        label_of_body[2] =
            std::string(materialPresetName(r.second_ball_material)) + " second ball";
    }
    // Every contact this run has seen, keyed by the unordered pair of names.
    std::map<std::pair<std::string, std::string>, ContactPair> contact_ledger;
    const auto noteContacts = [&](const std::vector<ImpactEvent> &events, double at_time_s) {
        for (const ImpactEvent &ev : events) {
            const auto first = label_of_body.find(ev.body_a);
            const auto second = label_of_body.find(ev.body_b);
            // Anything still unlabelled is named for what it is rather than
            // guessed at. Calling an unknown body "the ground" would be exactly
            // the kind of plausible-but-unmeasured claim this channel exists to
            // avoid, so it says so instead.
            const auto name_of = [&](MatterBodyId id,
                                     std::unordered_map<MatterBodyId, std::string>::const_iterator it) {
                if (it != label_of_body.end()) return it->second;
                if (id == kSupportSurfaceMatterId) return std::string("the ground");
                if (id >= 900U && id < 900U + setup.ledges.size()) return std::string("a ledge");
                // Carrying the id keeps this honest and self-diagnosing: it
                // names what it knows and says which body it could not name.
                return "unnamed body #" + std::to_string(id);
            };
            const std::string a = name_of(ev.body_a, first);
            const std::string b = name_of(ev.body_b, second);
            if (a == b) continue;
            auto key = std::minmax(a, b);
            auto [entry, inserted] = contact_ledger.try_emplace(
                std::pair<std::string, std::string>{key.first, key.second});
            ContactPair &pair = entry->second;
            if (inserted) {
                pair.a = key.first;
                pair.b = key.second;
                pair.first_time_s = at_time_s;
            }
            pair.peak_closing_speed_m_s =
                std::max(pair.peak_closing_speed_m_s, ev.closing_speed_m_s);
            pair.peak_impulse_n_s =
                std::max(pair.peak_impulse_n_s, ev.estimated_normal_impulse_n_s);
            pair.peak_energy_j =
                std::max(pair.peak_energy_j, ev.available_normal_energy_j);
            ++pair.events;
        }
    };
    // Debris (components beyond the rigid budget) is integrated ballistically
    // against the ground only; with the budget equal to the component count
    // there is none.
    struct Debris { Vec3 position, velocity; std::vector<std::uint32_t> nodes; std::vector<Vec3> offsets; };
    std::vector<Debris> debris;
    {
        std::size_t k = 0;
        for (const auto &component : components) {
            bool rigid = false;
            for (const std::uint32_t node : component.node_indices) rigid = rigid || cell_fragment[node] >= 0;
            if (rigid) continue;
            if (k >= build.debris_particles.size()) break;
            Debris d;
            d.position = build.debris_particles[k].position_world_m;
            d.velocity = build.debris_particles[k].velocity_m_s;
            for (const std::uint32_t node : component.node_indices) {
                d.nodes.push_back(node);
                d.offsets.push_back(setup.matter.nodes[node].position_world_m - d.position);
            }
            debris.push_back(std::move(d));
            ++k;
        }
    }
    const auto handoff_end = Clock::now();
    m.handoff_wall_s = seconds(handoff_begin, handoff_end);

    // Final lattice frame at handoff.
    {
        RecordedFrame frame;
        frame.time_s = m.lattice_simulated_s;
        frame.phase = "lattice";
        frame.cell_positions.resize(N);
        frame.cell_orientations.assign(N, Quat{});
        for (std::size_t i = 0; i < N; ++i) frame.cell_positions[i] = setup.matter.nodes[i].position_world_m;
        frame.ball_center = ball_center;
        frame.bond_alive.resize(B);
        frame.bond_damage.resize(B);
        for (std::size_t o = 0; o < B; ++o) {
            frame.bond_alive[o] = setup.matter.bonds[o].alive ? 1U : 0U;
            frame.bond_damage[o] = static_cast<float>(setup.matter.bonds[o].damage);
        }
        frame.fracture_count = status.broken_bonds;
        frame.component_ids = handoff_component;
        result.frames.push_back(std::move(frame));
    }

    // Rigid phase: step Jolt until everything is at rest or the limit, with two
    // things the phase could not do before -- a second striker, and a fragment
    // that goes back into the lattice when a contact could break it.
    const auto rigid_begin = Clock::now();
    const double rigid_dt = r.rigid_step_s;
    constexpr MatterBodyId kSecondBallId = 2;
    const bool second_strike = r.second_ball_radius_m > 0.0 && r.second_ball_speed_m_s > 0.0;
    const std::uint64_t settle_steps = static_cast<std::uint64_t>(std::ceil(r.settle_limit_s / rigid_dt));
    // Without a second strike this is the settle limit exactly, so every
    // earlier scene keeps its step count, its frame stride and its frames.
    const std::uint64_t rigid_limit_steps = second_strike ? 2U * settle_steps : settle_steps;
    const std::uint64_t rigid_stride = std::max<std::uint64_t>(1, rigid_limit_steps / std::max(1U, r.rigid_frames));
    double still_since = -1.0;
    double rigid_time = 0.0;
    std::uint32_t broken_total = status.broken_bonds;
    RefractureReport &report = m.refracture;
    report.enabled = r.refracture;
    MatterBodyId next_body_id = 1000U + static_cast<MatterBodyId>(build.rigid_fragments.size());
    const MaterialDefinition second_material = makeReferenceMaterial(r.second_ball_material, r.material_seed);
    const double second_mass = 4.0 / 3.0 * std::numbers::pi * std::pow(r.second_ball_radius_m, 3.0) *
                               second_material.density_kg_m3;
    bool second_inserted = false;
    if (second_strike) {
        m.second_ball_mass_kg = second_mass;
        m.second_ball_speed_m_s = r.second_ball_speed_m_s;
    }
    // Acoustic impedances, z = sqrt(rho E): the only property of the OTHER body
    // the trigger needs (Refracture.hpp).
    const double ball_impedance =
        acousticImpedance(setup.ball_material.density_kg_m3, setup.ball_material.young_modulus_pa);
    const double second_impedance =
        acousticImpedance(second_material.density_kg_m3, second_material.young_modulus_pa);
    const double ground_impedance =
        acousticImpedance(setup.ground_material.density_kg_m3, setup.ground_material.young_modulus_pa);

    // Observation only, opt-in: every contact above 5 m/s, so a scene that
    // refuses to break can be read rather than guessed at.
    const bool refracture_debug = r.refracture && r.refracture_trace;
    const auto fill_rigid_cells = [&](RecordedFrame &frame, std::int64_t skip_piece) {
        for (std::size_t f = 0; f < pieces.size(); ++f) {
            if (static_cast<std::int64_t>(f) == skip_piece) continue;
            const RigidSnapshot snap = world.snapshot(pieces[f].body_id);
            for (std::size_t k = 0; k < pieces[f].nodes.size(); ++k) {
                const std::uint32_t i = pieces[f].nodes[k];
                frame.cell_positions[i] =
                    snap.center_of_mass_world_m + snap.orientation_world.rotate(pieces[f].offsets[k]);
                frame.cell_orientations[i] = snap.orientation_world;
            }
        }
        for (const Debris &d : debris)
            for (std::size_t k = 0; k < d.nodes.size(); ++k)
                frame.cell_positions[d.nodes[k]] = d.position + d.offsets[k];
    };
    const auto capture_rigid = [&](double time_offset) {
        RecordedFrame frame;
        frame.time_s = m.lattice_simulated_s + time_offset;
        frame.phase = "rigid";
        frame.cell_positions.resize(N);
        frame.cell_orientations.assign(N, Quat{});
        fill_rigid_cells(frame, -1);
        if (world.contains(kBallId)) {
            const RigidSnapshot ball = world.snapshot(kBallId);
            frame.ball_center = ball.center_of_mass_world_m;
            frame.ball_orientation = ball.orientation_world;
        }
        frame.component_ids = live_component;
        frame.fracture_count = broken_total;
        result.frames.push_back(std::move(frame));
    };
    // The second ball is placed directly above the highest cell under its axis
    // and dropped, exactly as the first ball is placed above the tile. Nothing
    // is done to the fragments: no velocity, no impulse, no repositioning.
    const auto insert_second_ball = [&]() {
        RecordedFrame probe;
        probe.cell_positions.assign(N, Vec3{});
        probe.cell_orientations.assign(N, Quat{});
        fill_rigid_cells(probe, -1);
        double top = setup.ground_y;
        const double reach = r.second_ball_radius_m + r.cell_size_m;
        for (std::size_t i = 0; i < N; ++i) {
            if (cell_fragment[i] < 0) continue;
            const Vec3 &p = probe.cell_positions[i];
            if (std::hypot(p.x - r.second_ball_offset_x_m, p.z - r.second_ball_offset_z_m) > reach) continue;
            top = std::max(top, p.y + 0.5 * r.cell_size_m);
        }
        // ... nor inside a striker that is already resting under the axis.
        for (const MatterBodyId id : {kBallId, kSecondBallId}) {
            if (!world.contains(id)) continue;
            const RigidSnapshot ball = world.snapshot(id);
            const double radius = id == kBallId ? r.ball_radius_m : r.second_ball_radius_m;
            if (std::hypot(ball.center_of_mass_world_m.x - r.second_ball_offset_x_m,
                           ball.center_of_mass_world_m.z - r.second_ball_offset_z_m) > reach + radius)
                continue;
            top = std::max(top, ball.center_of_mass_world_m.y + radius);
        }
        world.addBall({.body_id = kSecondBallId, .radius_m = r.second_ball_radius_m,
                       .material = second_material,
                       .position_world_m = {r.second_ball_offset_x_m,
                                            top + r.second_ball_radius_m + r.second_ball_gap_m,
                                            r.second_ball_offset_z_m},
                       .linear_velocity_m_s = {0.0, -r.second_ball_speed_m_s, 0.0},
                       .angular_velocity_rad_s = {},
                       .mass_override_kg = second_mass, .sphere_inertia_factor = 0.4});
        second_inserted = true;
        m.second_strike_time_s = m.lattice_simulated_s + rigid_time;
        m.second_ball_start_y_m = top + r.second_ball_radius_m + r.second_ball_gap_m;
        still_since = -1.0;
    };

    // ---- The trigger, over one rigid step's contacts ----------------------
    struct Candidate {
        bool have{};
        std::size_t piece{};
        MatterBodyId partner{kInvalidMatterBodyId};
        RefractureAdmission admission{};
        double speed{}, energy{}, margin{};
    };
    // The cheap pre-gate: the largest closing speed the world could produce this
    // step against the lowest admission threshold any live-bonded piece has. It
    // uses the same bound as the trigger, so it can only skip steps in which no
    // contact could have been admitted -- and it is what keeps a settled pile
    // from paying for a rollback it does not need.
    const double stiffest_partner =
        std::max(std::max(ball_impedance, second_impedance), ground_impedance);
    const double piece_reach_m = 0.5 * length(r.tile_dimensions_m);
    const auto refracture_possible = [&]() {
        double lowest_threshold = std::numeric_limits<double>::infinity();
        double fastest = 0.0;
        for (const RigidPiece &piece : pieces) {
            const RigidSnapshot snap = world.snapshot(piece.body_id);
            fastest = std::max(fastest, length(snap.linear_velocity_m_s) +
                                            length(snap.angular_velocity_rad_s) * piece_reach_m);
            if (piece.limits.live_bonds == 0) continue;
            lowest_threshold = std::min(lowest_threshold,
                admitRefracture(piece.limits, stiffest_partner, 0.0, 0.0).threshold_speed_m_s);
        }
        for (const MatterBodyId id : {kBallId, kSecondBallId})
            if (world.contains(id)) fastest = std::max(fastest, length(world.snapshot(id).linear_velocity_m_s));
        return 2.0 * fastest >= lowest_threshold;
    };
    const auto evaluate_impacts = [&](std::vector<ImpactEvent> impacts) {
        Candidate chosen{};
        if (impacts.empty()) return chosen;
        std::sort(impacts.begin(), impacts.end(), impactOrder);
        if (refracture_debug) {
            for (const ImpactEvent &ev : impacts)
                if (ev.closing_speed_m_s > 5.0)
                    std::fprintf(stderr, "t=%.4f a=%llu b=%llu v=%.3f e=%.4f\n", rigid_time,
                                 (unsigned long long)ev.body_a, (unsigned long long)ev.body_b,
                                 ev.closing_speed_m_s, ev.available_normal_energy_j);
        }
        for (const ImpactEvent &ev : impacts) {
            const auto a = piece_of_body.find(ev.body_a);
            const auto b = piece_of_body.find(ev.body_b);
            const bool a_piece = a != piece_of_body.end();
            const bool b_piece = b != piece_of_body.end();
            if (!a_piece && !b_piece) continue; // a striker on the ground: not a fragment's contact
            ++report.contacts_tested;
            if (a_piece && b_piece) { ++report.refused_unsupported; continue; }
            const std::size_t index = a_piece ? a->second : b->second;
            const MatterBodyId other = a_piece ? ev.body_b : ev.body_a;
            const double other_impedance = other == kBallId ? ball_impedance
                : (other == kSecondBallId ? second_impedance : ground_impedance);
            const RefractureAdmission admission = admitRefracture(
                pieces[index].limits, other_impedance, ev.closing_speed_m_s, ev.available_normal_energy_j);
            report.max_closing_speed_any_m_s =
                std::max(report.max_closing_speed_any_m_s, ev.closing_speed_m_s);
            if (admission.verdict != RefractureVerdict::NoLiveBond) {
                report.max_closing_speed_m_s = std::max(report.max_closing_speed_m_s, ev.closing_speed_m_s);
                report.max_margin = std::max(report.max_margin,
                    admission.estimated_peak_stretch / pieces[index].limits.minimum_removal_stretch);
            }
            switch (admission.verdict) {
            case RefractureVerdict::NoLiveBond: ++report.rejected_no_bond; continue;
            case RefractureVerdict::BelowStressBound: ++report.rejected_stress; continue;
            case RefractureVerdict::BelowEnergyBound: ++report.rejected_energy; continue;
            case RefractureVerdict::Admitted: break;
            }
            const double margin = admission.estimated_peak_stretch /
                                  pieces[index].limits.minimum_removal_stretch;
            if (!chosen.have || margin > chosen.margin) {
                chosen.have = true;
                chosen.margin = margin;
                chosen.piece = index;
                chosen.partner = other;
                chosen.admission = admission;
                chosen.speed = ev.closing_speed_m_s;
                chosen.energy = ev.available_normal_energy_j;
            }
        }
        return chosen;
    };

    // ---- One re-entry ----------------------------------------------------
    // Runs from the state BEFORE the rigid step in which the contact was seen
    // (the caller rolls that step back), so the lattice, not Jolt, resolves the
    // impact. Returns the rigid steps it consumed; 0 when nothing ran.
    const auto run_refracture = [&](const Candidate &candidate) -> unsigned {
        const std::size_t chosen_piece = candidate.piece;
        const MatterBodyId chosen_partner = candidate.partner;
        ++report.admitted;

        // The budget, refused visibly.
        const std::uint64_t chunk_steps =
            std::max<std::uint64_t>(1, static_cast<std::uint64_t>(std::llround(rigid_dt / setup.dt_s)));
        if (report.events.size() >= r.refracture_max_events) { ++report.refused_budget_events; return 0U; }
        if (report.substeps + chunk_steps > r.refracture_max_steps) { ++report.refused_budget_steps; return 0U; }
        if (pieces[chosen_piece].nodes.size() > r.refracture_max_cells) { ++report.refused_too_large; return 0U; }

        const auto event_begin = Clock::now();
        RefractureEventReport event{};
        event.time_s = m.lattice_simulated_s + rigid_time;
        event.body_id = pieces[chosen_piece].body_id;
        event.cells = pieces[chosen_piece].nodes.size();
        event.live_bonds_in = pieces[chosen_piece].limits.live_bonds;
        event.closing_speed_m_s = candidate.speed;
        event.threshold_speed_m_s = candidate.admission.threshold_speed_m_s;
        event.peak_stretch = candidate.admission.estimated_peak_stretch;
        event.minimum_removal_stretch = pieces[chosen_piece].limits.minimum_removal_stretch;
        event.available_energy_j = candidate.energy;
        event.minimum_removal_energy_j = pieces[chosen_piece].limits.minimum_removal_energy_j;
        const bool striker_partner = chosen_partner == kBallId || chosen_partner == kSecondBallId;
        event.partner = chosen_partner == kBallId ? "striker"
            : (chosen_partner == kSecondBallId ? "second-striker" : "support");
        event.striker_in_island = striker_partner;

        // 1. Rebuild the lattice for this fragment, at its rigid pose, with its
        //    damage, its broken bonds and its permanent extension.
        const RigidSnapshot snap = world.snapshot(pieces[chosen_piece].body_id);
        // The rigid solver tolerates a penetration the lattice's support
        // projection does not: a cell centre below the floor is projected back
        // up THROUGH its bonds, which is the mechanism that injected kilojoules
        // before the finite-footprint rule (docs/fast-gpu-checkpoint.md 2.8).
        // The conversion therefore lifts the island out of the floor first --
        // a rigid translation, so no momentum, no kinetic energy and no
        // internal state changes, only gravitational potential, which is
        // reported. A lift larger than half a cell is refused instead.
        //
        // Every support plane counts, not just the ground: a piece resting on a
        // ledge is sunk into the ledge, and the reach cap that keeps a finite
        // footprint from teleporting a node at rest stops capping once the
        // node's approach speed is high enough (reach = 8 |v| dt), which is
        // exactly what a second strike produces. Measured on an intact iron
        // plate struck at 20 m/s: 361 kJ of bond energy removed from a 422 J
        // scene, where the same plate struck at 20 m/s in the FIRST phase
        // breaks no bond at all.
        double lift = 0.0;
        {
            const SupportSet<double> &support = setup.settings_world.support;
            for (std::size_t k = 0; k < pieces[chosen_piece].nodes.size(); ++k) {
                const Vec3 position = snap.center_of_mass_world_m +
                                      snap.orientation_world.rotate(pieces[chosen_piece].offsets[k]);
                for (std::uint32_t p = 0; p < support.plane_count; ++p) {
                    const SupportPlane<double> &plane = support.planes[p];
                    // The lift is a translation along +y; a plane that does not
                    // face up cannot be corrected this way and is left alone.
                    if (plane.normal.y < 0.999) continue;
                    if (!insideFootprints(plane, toV3(position))) continue;
                    const double depth = dot(toV3(position) - plane.point, plane.normal) - plane.node_radius;
                    lift = std::max(lift, -depth);
                }
            }
        }
        event.entry_support_penetration_m = lift;
        if (lift > 0.5 * r.cell_size_m) { ++report.refused_support_penetration; return 0U; }
        const FragmentPose pose{snap.center_of_mass_world_m + Vec3{0.0, lift, 0.0}, snap.orientation_world,
                                snap.linear_velocity_m_s, snap.angular_velocity_rad_s};
        FragmentLattice island = buildFragmentLattice(
            setup.matter, pieces[chosen_piece].nodes, cell_offset, pose, plastic_extension_m, plastic_strain_m);
        LatticeState island_state = buildLatticeState(island.matter, island.schedule, island.origin);
        for (std::size_t k = 0; k < island_state.bond_count; ++k) {
            const std::uint32_t o = island.schedule.bond_order[k];
            island_state.plastic_extension[k] = island.plastic_extension_m[o];
            island_state.plastic_strain[k] = island.plastic_strain_m[o];
        }
        const double cell = r.cell_size_m;
        event.elastic_in_j = latticeStateElasticEnergy(island_state);
        for (std::size_t i = 0; i < island_state.node_count; ++i)
            event.entry_max_displacement_m = std::max(event.entry_max_displacement_m,
                length(Vec3{island_state.u[3 * i], island_state.u[3 * i + 1], island_state.u[3 * i + 2]}));

        // 2. The entry ledger: the lattice against the engine's own reading of
        //    the same cells as one rigid body.
        {
            std::vector<std::uint32_t> all(island.matter.nodes.size());
            for (std::size_t i = 0; i < all.size(); ++i) all[i] = static_cast<std::uint32_t>(i);
            const FragmentMassProperties props = calculateFragmentMassProperties(island.matter, all);
            const MechanicalLedger lattice_in =
                latticeLedger(island_state, island.origin, island.carried_spin_rad_s, cell);
            const MechanicalLedger rigid_in = rigidLedger(
                props.mass_kg, props.center_of_mass_world_m, props.linear_velocity_m_s,
                props.inertia_world_kg_m2, props.angular_velocity_rad_s, island.origin);
            event.entry_momentum_residual_kg_m_s =
                length(lattice_in.linear_momentum_kg_m_s - rigid_in.linear_momentum_kg_m_s);
            event.entry_angular_residual_kg_m2_s =
                length(lattice_in.angular_momentum_kg_m2_s - rigid_in.angular_momentum_kg_m2_s);
            event.entry_energy_residual_j = lattice_in.kinetic_energy_j - rigid_in.kinetic_energy_j;
        }

        // 3. The island: this fragment, the striker that hit it if it was a
        //    striker, and the same support planes the first phase used.
        StepSettings<double> island_settings = buildSettings(setup, island.origin);
        island_settings.node_contact.bucket_mask =
            latticeContactBucketMask(static_cast<std::uint32_t>(island.matter.nodes.size()));
        island_settings.sphere_enabled = striker_partner ? 1U : 0U;
        SphereState<double> island_sphere = setup.sphere_world;
        double striker_mass = 0.0;
        Vec3 striker_position_in{};
        if (striker_partner) {
            const RigidSnapshot ball = world.snapshot(chosen_partner);
            const double radius = chosen_partner == kBallId ? r.ball_radius_m : r.second_ball_radius_m;
            striker_mass = chosen_partner == kBallId ? setup.sphere_world.mass : second_mass;
            island_sphere.center = toV3(ball.center_of_mass_world_m - island.origin);
            island_sphere.velocity = toV3(ball.linear_velocity_m_s);
            island_sphere.angular_velocity = toV3(ball.angular_velocity_rad_s);
            island_sphere.radius = radius;
            island_sphere.mass = striker_mass;
            island_sphere.inertia = 0.4 * striker_mass * radius * radius;
            // The prefilter only has to exceed how far the sphere centre can
            // move inside one pass, so it follows THIS striker's radius rather
            // than the first ball's.
            island_settings.contact.prefilter_slack = 0.05 * radius;
            striker_position_in = ball.center_of_mass_world_m;
        } else {
            // No striker: park the unused sphere far above the island so the
            // ball/support pass has nothing to find and its accumulators stay
            // clean. `sphere_enabled` is 0, so it never touches a node.
            island_sphere.center = {0.0, 1.0e4, 0.0};
            island_sphere.velocity = {0.0, 0.0, 0.0};
            island_sphere.angular_velocity = {0.0, 0.0, 0.0};
        }

        // The same disagreement on the striker's side. Jolt's collision proxy
        // for a fragment is a convex hull of at most 192 sampled cell corners,
        // which sits INSIDE the true box of cells, so the rigid solver lets a
        // striker reach a depth the lattice's node-sphere contact would never
        // have allowed: 1.36 mm on an intact iron plate, measured. Handing that
        // overlap to the contact pass is a position correction of millimetres
        // in one substep -- 17.9 kJ of bond energy removed from a 422 J scene,
        // where the same plate struck at the same speed and place in the FIRST
        // phase removes 55 J. The striker is therefore backed off along the
        // contact normal until it just touches. A rigid translation of the
        // striker alone: no momentum, no kinetic energy, and it costs the ball
        // the microseconds it takes to close the gap again.
        if (striker_partner) {
            const double touch = island_sphere.radius + island_settings.contact.node_contact_radius;
            const auto deepest = [&](Vec3 &axis) {
                double worst = 0.0;
                for (std::size_t i = 0; i < island_state.node_count; ++i) {
                    const Vec3 node{island_state.x0[3 * i] + island_state.u[3 * i],
                                    island_state.x0[3 * i + 1] + island_state.u[3 * i + 1],
                                    island_state.x0[3 * i + 2] + island_state.u[3 * i + 2]};
                    const Vec3 offset = toVec3(island_sphere.center) - node;
                    const double distance = length(offset);
                    if (touch - distance > worst && distance > 1.0e-12) {
                        worst = touch - distance;
                        axis = offset / distance;
                    }
                }
                return worst;
            };
            for (int pass = 0; pass < 8; ++pass) {
                Vec3 axis{};
                const double overlap = deepest(axis);
                if (!(overlap > 0.0)) break;
                island_sphere.center = island_sphere.center + toV3(overlap * axis);
                event.entry_striker_backoff_m += overlap;
            }
            if (event.entry_striker_backoff_m > 0.5 * r.cell_size_m) {
                ++report.refused_striker_overlap;
                return 0U; // nothing has left the rigid world yet
            }
            double gap = std::numeric_limits<double>::infinity();
            for (std::size_t i = 0; i < island_state.node_count; ++i) {
                const Vec3 node{island_state.x0[3 * i] + island_state.u[3 * i],
                                island_state.x0[3 * i + 1] + island_state.u[3 * i + 1],
                                island_state.x0[3 * i + 2] + island_state.u[3 * i + 2]};
                gap = std::min(gap, length(node - toVec3(island_sphere.center)) - touch);
            }
            event.entry_striker_gap_m = gap;
        }
        // The island is accepted: take its bodies out of the rigid world for
        // the length of the window.
        if (striker_partner) world.removeAndDestroy(chosen_partner);
        world.removeAndDestroy(pieces[chosen_piece].body_id);

        // Mass-weighted position now, for the gravity work over the window.
        const auto weighted_position = [&](const LatticeState &s) {
            Vec3 total{};
            for (std::size_t i = 0; i < s.node_count; ++i)
                total += s.mass[i] * (s.origin + Vec3{s.x0[3 * i], s.x0[3 * i + 1], s.x0[3 * i + 2]} +
                                      Vec3{s.u[3 * i], s.u[3 * i + 1], s.u[3 * i + 2]});
            return total;
        };
        const Vec3 weighted_in = weighted_position(island_state);
        const MechanicalLedger lattice_in_window =
            latticeLedger(island_state, island.origin, island.carried_spin_rad_s, cell);
        const Vec3 striker_velocity_in = toVec3(island_sphere.velocity);
        const Vec3 striker_angular_in = toVec3(island_sphere.angular_velocity);
        const double striker_inertia = island_sphere.inertia;

        // 4. Run the window: one rigid step's worth of substeps, then one rigid
        //    step of the rest of the world, so the two clocks stay together.
        std::unique_ptr<LatticeBackend> island_backend = makeBackend(r, island.schedule);
        island_backend->upload(island_state, island_settings, island_sphere);
        RunControl chunk{};
        chunk.max_steps = chunk_steps;
        chunk.steps_per_launch = r.steps_per_launch;
        std::uint32_t last_broken = 0;
        unsigned quiet = 0, used = 0;
        for (unsigned w = 0; w < std::max(1U, r.refracture_window_steps); ++w) {
            if (report.substeps + chunk_steps > r.refracture_max_steps) { ++report.refused_budget_steps; break; }
            const RunStatus chunk_status = island_backend->run(chunk);
            report.substeps += chunk_steps;
            world.step(rigid_dt);
            for (Debris &d : debris) {
                d.velocity += rigid_dt * r.gravity_m_s2;
                d.position += rigid_dt * d.velocity;
                if (d.position.y < setup.ground_y) { d.position.y = setup.ground_y; d.velocity = {}; }
            }
            rigid_time += rigid_dt;
            ++m.rigid_steps;
            ++used;
            island_backend->download(island_state, island_sphere);
            // A frame per rigid step of the window, so the second break is
            // watchable rather than a jump between two rest poses.
            {
                RecordedFrame frame;
                frame.time_s = m.lattice_simulated_s + rigid_time;
                frame.phase = "rigid";
                frame.cell_positions.resize(N);
                frame.cell_orientations.assign(N, Quat{});
                // The island's body is out of the world for the window; its
                // cells come from the lattice below.
                fill_rigid_cells(frame, static_cast<std::int64_t>(chosen_piece));
                for (std::size_t i = 0; i < island.parent_node.size(); ++i) {
                    const std::uint32_t p = island.parent_node[i];
                    frame.cell_positions[p] =
                        island_state.origin +
                        Vec3{island_state.x0[3 * i] + island_state.u[3 * i],
                             island_state.x0[3 * i + 1] + island_state.u[3 * i + 1],
                             island_state.x0[3 * i + 2] + island_state.u[3 * i + 2]};
                    frame.cell_orientations[p] = snap.orientation_world;
                }
                if (striker_partner) {
                    frame.ball_center = island.origin + toVec3(island_sphere.center);
                } else if (world.contains(kBallId)) {
                    frame.ball_center = world.snapshot(kBallId).center_of_mass_world_m;
                }
                frame.component_ids = live_component;
                frame.fracture_count = broken_total + chunk_status.broken_bonds;
                result.frames.push_back(std::move(frame));
            }
            if (chunk_status.broken_bonds == last_broken) ++quiet; else quiet = 0;
            last_broken = chunk_status.broken_bonds;
            if (r.refracture_quiet_steps > 0 && quiet >= r.refracture_quiet_steps) break;
        }
        const RunStatus &island_status = island_backend->status();
        event.substeps = island_status.total_steps;
        event.rigid_steps = used;
        event.window_s = static_cast<double>(island_status.total_steps) * setup.dt_s;
        event.clock_residual_s = event.window_s - static_cast<double>(used) * rigid_dt;
        event.broken_bonds = island_status.broken_bonds;
        event.removed_energy_j = island_status.removed_energy_j;
        event.plastic_work_j = island_status.plastic_work_j;
        event.contact_dissipated_j = island_status.contact.dissipated_kinetic_energy_j;
        event.node_contact_dissipated_j = island_status.node_contact.dissipated_kinetic_energy_j;
        event.damping_dissipated_j = island_status.damping_dissipated_j;
        event.elastic_out_j = latticeStateElasticEnergy(island_state);

        // 5. Back to the rigid world: the fragment's own connected components.
        writeBackLatticeState(island_state, island.schedule, island.matter);
        for (std::size_t k = 0; k < island_state.bond_count; ++k) {
            const std::uint32_t local = island.schedule.bond_order[k];
            const std::uint32_t parent = island.parent_bond[local];
            island.plastic_extension_m[local] = island_state.plastic_extension[k];
            island.plastic_strain_m[local] = island_state.plastic_strain[k];
            plastic_extension_m[parent] = island_state.plastic_extension[k];
            plastic_strain_m[parent] = island_state.plastic_strain[k];
        }
        for (std::size_t local = 0; local < island.matter.bonds.size(); ++local)
            setup.matter.bonds[island.parent_bond[local]] = island.matter.bonds[local];
        for (std::size_t i = 0; i < island.parent_node.size(); ++i)
            setup.matter.nodes[island.parent_node[i]] = island.matter.nodes[i];
        const auto island_components = findConnectedComponents(island.matter);
        const FragmentBuildResult rebuilt = buildFragmentRepresentations(island.matter, island_components, {
            .first_body_id = next_body_id,
            .maximum_rigid_fragments = std::max<std::size_t>(1, island_components.size()),
            .minimum_nodes_per_rigid_fragment = 1,
            .maximum_collision_points = 192,
            .friction = setup.tile_ground.dynamic_friction,
            .restitution = setup.tile_ground.restitution,
        });
        next_body_id += static_cast<MatterBodyId>(rebuilt.rigid_fragments.size()) + 1U;

        // 6. The exit ledger, before the world is touched.
        MechanicalLedger rigid_out{};
        rigid_out.about_m = island.origin;
        double coarsening = 0.0;
        {
            std::size_t fragment_index = 0;
            for (const auto &component : island_components) {
                if (fragment_index >= rebuilt.rigid_fragments.size()) break;
                const RigidFragmentDescription &fragment = rebuilt.rigid_fragments[fragment_index];
                if (fragment.source_node_count != component.node_indices.size()) continue;
                const FragmentMassProperties &props = fragment.mass_properties;
                const MechanicalLedger piece_ledger = rigidLedger(
                    props.mass_kg, props.center_of_mass_world_m, props.linear_velocity_m_s,
                    props.inertia_world_kg_m2, props.angular_velocity_rad_s, island.origin);
                rigid_out.mass_kg += piece_ledger.mass_kg;
                rigid_out.linear_momentum_kg_m_s += piece_ledger.linear_momentum_kg_m_s;
                rigid_out.angular_momentum_kg_m2_s += piece_ledger.angular_momentum_kg_m2_s;
                rigid_out.kinetic_energy_j += piece_ledger.kinetic_energy_j;
                coarsening += props.coarsening_kinetic_loss_j;
                ++fragment_index;
            }
        }
        const MechanicalLedger lattice_out =
            latticeLedger(island_state, island.origin, island.carried_spin_rad_s, cell);
        event.exit_momentum_residual_kg_m_s =
            length(lattice_out.linear_momentum_kg_m_s - rigid_out.linear_momentum_kg_m_s);
        event.exit_angular_residual_kg_m2_s =
            length(lattice_out.angular_momentum_kg_m2_s - rigid_out.angular_momentum_kg_m2_s);
        event.exit_coarsening_loss_j = coarsening;
        event.exit_energy_residual_j = lattice_out.kinetic_energy_j - rigid_out.kinetic_energy_j - coarsening;

        // The window ledger. What is left over is the supports' impulse and
        // work: the support projection and its velocity response are external
        // to this island and are the one term nothing here measures directly.
        {
            const Vec3 striker_velocity_out = toVec3(island_sphere.velocity);
            const Vec3 striker_position_out = island.origin + toVec3(island_sphere.center);
            const Vec3 momentum_in = lattice_in_window.linear_momentum_kg_m_s + striker_mass * striker_velocity_in;
            const Vec3 momentum_out = lattice_out.linear_momentum_kg_m_s + striker_mass * striker_velocity_out;
            const double total_mass = lattice_out.mass_kg + striker_mass;
            const Vec3 gravity_impulse = total_mass * event.window_s * r.gravity_m_s2;
            event.window_external_impulse_n_s = length(momentum_out - momentum_in - gravity_impulse);
            const double striker_energy_in =
                0.5 * striker_mass * lengthSquared(striker_velocity_in) +
                0.5 * striker_inertia * lengthSquared(striker_angular_in);
            const double striker_energy_out =
                0.5 * striker_mass * lengthSquared(striker_velocity_out) +
                0.5 * striker_inertia * lengthSquared(toVec3(island_sphere.angular_velocity));
            const Vec3 weighted_out = weighted_position(island_state);
            const double gravity_work =
                dot(r.gravity_m_s2, (weighted_out - weighted_in) +
                                        striker_mass * (striker_position_out - striker_position_in));
            const double energy_in =
                lattice_in_window.kinetic_energy_j + event.elastic_in_j + striker_energy_in;
            const double energy_out =
                lattice_out.kinetic_energy_j + event.elastic_out_j + striker_energy_out;
            event.window_energy_residual_j =
                energy_in + gravity_work - energy_out - event.removed_energy_j - event.plastic_work_j -
                event.contact_dissipated_j - event.node_contact_dissipated_j - event.damping_dissipated_j;
        }

        // 7. Publish the new pieces, and put the striker back where the lattice
        //    left it.
        std::vector<RigidPiece> kept;
        kept.reserve(pieces.size() + island_components.size());
        for (std::size_t p = 0; p < pieces.size(); ++p)
            if (p != chosen_piece) kept.push_back(std::move(pieces[p]));
        std::uint32_t next_component = 0;
        for (const RigidPiece &piece : kept) next_component = std::max(next_component, piece.component_id + 1U);
        {
            std::size_t fragment_index = 0;
            for (const auto &component : island_components) {
                if (fragment_index >= rebuilt.rigid_fragments.size()) break;
                const RigidFragmentDescription &fragment = rebuilt.rigid_fragments[fragment_index];
                if (fragment.source_node_count != component.node_indices.size()) continue;
                RigidPiece piece;
                piece.body_id = fragment.body_id;
                piece.component_id = next_component++;
                for (const std::uint32_t local : component.node_indices) {
                    const std::uint32_t parent = island.parent_node[local];
                    piece.nodes.push_back(parent);
                    piece.offsets.push_back(island.matter.nodes[local].position_world_m -
                                            fragment.mass_properties.center_of_mass_world_m);
                }
                piece.limits = fragmentFractureLimits(setup.matter, piece.nodes,
                                                      setup.tile_material.density_kg_m3,
                                                      setup.tile_material.young_modulus_pa);
                kept.push_back(std::move(piece));
                ++fragment_index;
            }
        }
        pieces = std::move(kept);
        piece_of_body.clear();
        // A cell whose component did not become a rigid body belongs to nothing
        // now; say so rather than leave it pointing at a piece it is not in.
        for (const std::uint32_t node : island.parent_node) cell_fragment[node] = -1;
        for (std::size_t p = 0; p < pieces.size(); ++p) {
            piece_of_body[pieces[p].body_id] = p;
            for (std::size_t k = 0; k < pieces[p].nodes.size(); ++k) {
                const std::uint32_t node = pieces[p].nodes[k];
                cell_fragment[node] = static_cast<std::int32_t>(p);
                cell_offset[node] = pieces[p].offsets[k];
                live_component[node] = pieces[p].component_id;
            }
        }
        world.addFragments(rebuilt.rigid_fragments);
        if (striker_partner) {
            const double radius = chosen_partner == kBallId ? r.ball_radius_m : r.second_ball_radius_m;
            world.addBall({.body_id = chosen_partner, .radius_m = radius,
                           .material = chosen_partner == kBallId ? setup.ball_material : second_material,
                           .position_world_m = island.origin + toVec3(island_sphere.center),
                           .linear_velocity_m_s = toVec3(island_sphere.velocity),
                           .angular_velocity_rad_s = toVec3(island_sphere.angular_velocity),
                           .mass_override_kg = striker_mass, .sphere_inertia_factor = 0.4});
        }
        broken_total += island_status.broken_bonds;
        event.pieces_out = island_components.size();
        event.wall_s = seconds(event_begin, Clock::now());
        report.broken_bonds += island_status.broken_bonds;
        report.pieces_created += island_components.size();
        report.removed_energy_j += island_status.removed_energy_j;
        report.plastic_work_j += island_status.plastic_work_j;
        report.simulated_s += event.window_s;
        report.wall_s += event.wall_s;
        report.worst_entry_momentum_residual_kg_m_s =
            std::max(report.worst_entry_momentum_residual_kg_m_s, event.entry_momentum_residual_kg_m_s);
        report.worst_entry_energy_residual_j =
            std::max(report.worst_entry_energy_residual_j, std::abs(event.entry_energy_residual_j));
        report.worst_exit_momentum_residual_kg_m_s =
            std::max(report.worst_exit_momentum_residual_kg_m_s, event.exit_momentum_residual_kg_m_s);
        report.worst_exit_energy_residual_j =
            std::max(report.worst_exit_energy_residual_j, std::abs(event.exit_energy_residual_j));
        report.events.push_back(std::move(event));
        still_since = -1.0;
        // Contacts observed during the window belong to a world the island was
        // not in; drop them rather than judge a fragment on them.
        (void)world.drainImpacts();
        return used;
    };

    // The bodies a reversible trial has to record: the pieces, the strikers,
    // the ledges and the ground. JoltWorld caps a trial at 256.
    const auto rollback_available = [&]() {
        return pieces.size() + setup.ledges.size() + 4U <= 250U;
    };
    for (std::uint64_t step = 0; step < rigid_limit_steps; ++step) {
        // A rigid step that ends in a contact hard enough to break the piece is
        // rolled back and replayed in the lattice, because Jolt has already
        // resolved the impact by the time the contact is reported: acting on
        // the state after the step would hand the lattice a ball that has
        // already bounced. The rollback is entered only when the trigger's own
        // bound says an admission is possible at all this step.
        Candidate candidate{};
        bool rolled_back = false;
        if (r.refracture && refracture_possible()) {
            if (!rollback_available()) {
                world.step(rigid_dt);
                std::vector<ImpactEvent> observed = world.drainImpacts();
                noteContacts(observed, rigid_time + rigid_dt);
                candidate = evaluate_impacts(std::move(observed));
                if (candidate.have) { ++report.refused_no_rollback; candidate.have = false; }
            } else {
                ++report.trial_steps;
                std::vector<ImpactEvent> observed;
                const bool committed = world.runReversibleTrial([&]() {
                    world.step(rigid_dt);
                    observed = world.drainImpacts();
                    candidate = evaluate_impacts(observed);
                    return !candidate.have;
                });
                // A rolled-back trial never happened, so its contacts did not
                // either; only a committed step's contacts go in the ledger.
                if (committed) noteContacts(observed, rigid_time + rigid_dt);
                rolled_back = !committed;
                if (rolled_back) ++report.rollbacks;
            }
        } else {
            world.step(rigid_dt);
            // Drain unconditionally. With refracture off this was never called,
            // so the collector's event vector grew for the length of the run.
            std::vector<ImpactEvent> observed = world.drainImpacts();
            noteContacts(observed, rigid_time + rigid_dt);
            if (r.refracture) (void)evaluate_impacts(std::move(observed));
        }
        if (!rolled_back) {
            for (Debris &d : debris) {
                d.velocity += rigid_dt * r.gravity_m_s2;
                d.position += rigid_dt * d.velocity;
                if (d.position.y < setup.ground_y) { d.position.y = setup.ground_y; d.velocity = {}; }
            }
            rigid_time += rigid_dt;
            ++m.rigid_steps;
        }
        unsigned consumed = 0;
        if (candidate.have) consumed = run_refracture(candidate);
        if (rolled_back && consumed == 0U) {
            // The re-entry was refused after the rollback; take the step the
            // trial threw away so the world still advances.
            world.step(rigid_dt);
            noteContacts(world.drainImpacts(), rigid_time + rigid_dt);
            for (Debris &d : debris) {
                d.velocity += rigid_dt * r.gravity_m_s2;
                d.position += rigid_dt * d.velocity;
                if (d.position.y < setup.ground_y) { d.position.y = setup.ground_y; d.velocity = {}; }
            }
            rigid_time += rigid_dt;
            ++m.rigid_steps;
        }
        if (consumed > 0U) {
            step += consumed - (rolled_back ? 1U : 0U);
            capture_rigid(rigid_time);
        }
        bool still = true;
        for (const RigidPiece &piece : pieces) {
            const RigidSnapshot snap = world.snapshot(piece.body_id);
            if (length(snap.linear_velocity_m_s) > r.rest_speed_m_s ||
                length(snap.angular_velocity_rad_s) > r.rest_angular_rad_s) { still = false; break; }
        }
        if (still) {
            if (still_since < 0.0) still_since = rigid_time;
        } else {
            still_since = -1.0;
        }
        if ((step + 1) % rigid_stride == 0) capture_rigid(rigid_time);
        const bool settled = still && rigid_time - still_since >= r.rest_hold_s;
        if (second_strike && !second_inserted &&
            (settled || (r.second_strike_at_s >= 0.0 ? rigid_time >= r.second_strike_at_s
                                                     : rigid_time >= r.second_strike_wait_s))) {
            insert_second_ball();
            capture_rigid(rigid_time);
            continue;
        }
        if (settled) {
            m.came_to_rest = true;
            m.rest_time_s = m.lattice_simulated_s + still_since;
            break;
        }
    }
    if (world.contains(kBallId)) {
        const RigidSnapshot ball = world.snapshot(kBallId);
        m.ball_speed_at_end_m_s = length(ball.linear_velocity_m_s);
        m.ball_height_at_end_m = ball.center_of_mass_world_m.y;
    }
    m.pieces_at_end = pieces.size() + debris.size();
    m.broken_bonds_total = broken_total;
    if (result.frames.back().phase != "rigid" || result.frames.back().time_s < m.lattice_simulated_s + rigid_time)
        capture_rigid(rigid_time);
    const auto rigid_end = Clock::now();
    m.rigid_simulated_s = rigid_time;
    m.rigid_wall_s = seconds(rigid_begin, rigid_end);

    m.simulated_total_s = m.lattice_simulated_s + m.rigid_simulated_s;
    m.wall_total_s = seconds(wall_begin, rigid_end);
    m.realtime_ratio = m.simulated_total_s > 0.0 ? m.wall_total_s / m.simulated_total_s : 0.0;
    m.rule_met = m.realtime_ratio <= 1.1;

    result.tile_dimensions_m = r.tile_dimensions_m;
    result.cell_size_m = r.cell_size_m;
    result.ball_radius_m = r.ball_radius_m;
    result.tile_material_name = std::string(materialPresetName(r.tile_material));
    result.ball_material_name = std::string(materialPresetName(r.ball_material));
    result.ground_material_name = std::string(materialPresetName(r.ground_material));
    result.ledges = setup.ledges;
    result.ground_y = setup.ground_y;
    result.bodies = r.bodies;
    result.part_of_node = setup.part_of_node;
    result.part_bodies = setup.part_bodies;
    result.contacts.reserve(contact_ledger.size());
    for (auto &[key, pair] : contact_ledger) result.contacts.push_back(std::move(pair));
    result.bond_nodes.reserve(B);
    for (const BondRest &bond : setup.asset.bonds) result.bond_nodes.emplace_back(bond.node_a, bond.node_b);
    if (log) *log += notes.str();
    return result;
}

namespace {

Json refractureJson(const RefractureReport &f) {
    Json events = Json::array();
    for (const RefractureEventReport &e : f.events) {
        events.push_back({
            {"time_s", e.time_s}, {"body_id", e.body_id}, {"partner", e.partner},
            {"cells", e.cells}, {"live_bonds_in", e.live_bonds_in},
            {"trigger", {
                {"closing_speed_m_s", e.closing_speed_m_s},
                {"threshold_speed_m_s", e.threshold_speed_m_s},
                {"peak_stretch", e.peak_stretch},
                {"minimum_removal_stretch", e.minimum_removal_stretch},
                {"available_energy_j", e.available_energy_j},
                {"minimum_removal_energy_j", e.minimum_removal_energy_j}}},
            {"window", {
                {"substeps", e.substeps}, {"rigid_steps", e.rigid_steps},
                {"simulated_s", e.window_s}, {"wall_s", e.wall_s},
                {"clock_residual_s", e.clock_residual_s},
                {"entry_support_penetration_m", e.entry_support_penetration_m},
                {"entry_max_displacement_m", e.entry_max_displacement_m},
                {"entry_striker_gap_m", e.entry_striker_gap_m},
                {"entry_striker_backoff_m", e.entry_striker_backoff_m},
                {"striker_in_island", e.striker_in_island}}},
            {"result", {
                {"broken_bonds", e.broken_bonds}, {"pieces_out", e.pieces_out},
                {"removed_energy_j", e.removed_energy_j}, {"plastic_work_j", e.plastic_work_j},
                {"contact_dissipated_j", e.contact_dissipated_j},
                {"node_contact_dissipated_j", e.node_contact_dissipated_j},
                {"damping_dissipated_j", e.damping_dissipated_j},
                {"elastic_in_j", e.elastic_in_j}, {"elastic_out_j", e.elastic_out_j}}},
            {"ledger", {
                {"entry_momentum_residual_kg_m_s", e.entry_momentum_residual_kg_m_s},
                {"entry_angular_residual_kg_m2_s", e.entry_angular_residual_kg_m2_s},
                {"entry_energy_residual_j", e.entry_energy_residual_j},
                {"exit_momentum_residual_kg_m_s", e.exit_momentum_residual_kg_m_s},
                {"exit_angular_residual_kg_m2_s", e.exit_angular_residual_kg_m2_s},
                {"exit_coarsening_loss_j", e.exit_coarsening_loss_j},
                {"exit_energy_residual_j", e.exit_energy_residual_j},
                {"window_external_impulse_n_s", e.window_external_impulse_n_s},
                {"window_unaccounted_work_j", e.window_energy_residual_j}}},
        });
    }
    return Json{
        {"enabled", f.enabled},
        {"contacts_tested", f.contacts_tested}, {"admitted", f.admitted},
        {"rejected", {
            {"no_live_bond", f.rejected_no_bond}, {"below_stress_bound", f.rejected_stress},
            {"below_energy_bound", f.rejected_energy},
            {"max_closing_speed_m_s", f.max_closing_speed_m_s},
            {"max_closing_speed_any_m_s", f.max_closing_speed_any_m_s},
            {"max_margin", f.max_margin}}},
        {"refused", {
            {"budget_events", f.refused_budget_events}, {"budget_steps", f.refused_budget_steps},
            {"unsupported_partner", f.refused_unsupported}, {"too_many_cells", f.refused_too_large},
            {"support_penetration", f.refused_support_penetration},
            {"striker_overlap", f.refused_striker_overlap},
            {"no_rollback", f.refused_no_rollback}}},
        {"rollbacks", f.rollbacks}, {"trial_steps", f.trial_steps},
        {"substeps", f.substeps}, {"simulated_s", f.simulated_s}, {"wall_s", f.wall_s},
        {"broken_bonds", f.broken_bonds}, {"pieces_created", f.pieces_created},
        {"removed_energy_j", f.removed_energy_j}, {"plastic_work_j", f.plastic_work_j},
        {"worst_residual", {
            {"entry_momentum_kg_m_s", f.worst_entry_momentum_residual_kg_m_s},
            {"entry_energy_j", f.worst_entry_energy_residual_j},
            {"exit_momentum_kg_m_s", f.worst_exit_momentum_residual_kg_m_s},
            {"exit_energy_j", f.worst_exit_energy_residual_j}}},
        {"events", events},
    };
}

} // namespace

std::string measurementsJson(const TileImpactMeasurements &m) {
    Json phases = Json::object();
    for (unsigned p = 0; p < kPhaseCount; ++p) phases[latticePhaseName(p)] = m.phase_seconds[p];
    Json j{
        {"phase_seconds", phases},
        {"shared_memory_positions", m.shared_memory_positions},
        {"shared_memory_bytes", m.shared_memory_bytes},
        {"max_tensile_stretch", m.max_tensile_stretch}, {"max_damage", m.max_damage},
        {"max_compressive_strain", m.max_compressive_strain},
        {"max_shear_strain", m.max_shear_strain},
        {"rank_deficient_nodes", m.rank_deficient_nodes},
        {"backend", m.backend_name},
        {"cells", m.cells}, {"bonds", m.bonds}, {"colors", m.colors}, {"blocks", m.blocks},
        {"boundary_bonds", m.boundary_bonds},
        {"cell_size_m", m.cell_size_m}, {"tile_mass_kg", m.tile_mass_kg}, {"ball_mass_kg", m.ball_mass_kg},
        {"dt_s", m.dt_s}, {"substep_limit_s", m.substep_limit_s}, {"fastest_period_s", m.fastest_period_s},
        {"lattice", {
            {"steps", m.lattice_steps}, {"simulated_s", m.lattice_simulated_s},
            {"wall_s", m.lattice_wall_s}, {"kernel_s", m.lattice_kernel_s}, {"launches", m.launches},
            {"exit_reason", m.exit_reason}, {"failure_rounds", m.failure_rounds},
            {"broken_bonds", m.broken_bonds}, {"first_failure_s", m.first_failure_s},
            {"last_failure_s", m.last_failure_s}, {"removed_energy_j", m.removed_energy_j},
            {"bond_updates_per_s", m.bond_updates_per_s},
            {"failure_law", m.failure_law},
            {"critical_stretch", m.critical_stretch},
            {"energy_scaled_stretch", m.energy_scaled_stretch},
            {"strength_stretch", m.strength_stretch},
            {"strength_bound_active", m.strength_bound_active},
            {"lattice_crack_energy_j_m2", m.lattice_crack_energy_j_m2},
            {"tensile_failures", m.tensile_failures},
            {"compressive_failures", m.compressive_failures},
            {"shear_failures", m.shear_failures},
            {"first_failure", {
                {"bonds", m.first_failure_bonds},
                {"centroid_m", {m.first_failure_centroid_m.x, m.first_failure_centroid_m.y, m.first_failure_centroid_m.z}},
                {"depth_below_top_m", m.first_failure_depth_m},
                {"radius_from_strike_m", m.first_failure_radius_m}}},
            {"contact", {
                {"impulse_contacts", m.contact.impulse_contacts},
                {"impulse_to_material_n_s", {m.contact.impulse_to_material_x, m.contact.impulse_to_material_y, m.contact.impulse_to_material_z}},
                {"dissipated_kinetic_energy_j", m.contact.dissipated_kinetic_energy_j},
                {"maximum_penetration_m", m.contact.maximum_penetration_m},
                {"maximum_position_correction_m", m.contact.maximum_position_correction_m},
                {"maximum_center_shift_m", m.contact.maximum_center_shift_m},
                {"ball_support_events", m.contact.ball_support_events}}},
            {"node_contact", {
                {"contacts", m.node_contact.contacts},
                {"pair_tests", m.node_contact.pair_tests},
                {"rebuilds", m.node_contact.rebuilds},
                {"pairs_listed", m.node_contact.pairs_listed},
                {"pair_overflow", m.node_contact.pair_overflow},
                {"dissipated_kinetic_energy_j", m.node_contact.dissipated_kinetic_energy_j},
                {"maximum_overlap_m", m.node_contact.maximum_overlap_m},
                {"maximum_position_correction_m", m.node_contact.maximum_position_correction_m},
                {"momentum_residual_n_s", {m.node_contact.momentum_residual_x,
                                           m.node_contact.momentum_residual_y,
                                           m.node_contact.momentum_residual_z}}}},
            {"dissipated_kinetic_energy_j", {
                {"audited", m.energy_audited},
                {"node_contact", m.node_contact.dissipated_kinetic_energy_j},
                {"striker_contact", m.energy_audited ? m.striker_dissipated_j
                                                     : m.contact.dissipated_kinetic_energy_j},
                {"bond_damping", m.damping_dissipated_j},
                {"plastic_work", m.plastic_work_j},
                {"fracture", m.removed_energy_j}}},
            {"plasticity", {
                {"enabled", m.plasticity_enabled},
                {"yield_strength_pa", m.yield_strength_pa},
                {"yield_stretch", m.yield_stretch},
                {"hardening_ratio", m.plastic_hardening_ratio},
                {"plastic_work_j", m.plastic_work_j},
                {"max_plastic_stretch", m.max_plastic_stretch},
                {"plastic_bonds", m.plastic_bonds},
                {"plastic_extension_total_m", m.plastic_extension_total_m}}},
            {"energy", {
                {"initial_kinetic_j", m.initial_kinetic_j},
                {"elastic_stored_j", m.elastic_energy_j},
                {"lattice_kinetic_j", m.lattice_kinetic_j}}},
            {"deformation", {
                {"relax_steps", m.relax_steps},
                {"relax_broken_bonds", m.relax_broken_bonds},
                {"relax_plastic_work_j", m.relax_plastic_work_j},
                {"relax_elastic_energy_j", m.relax_elastic_energy_j},
                {"relax_kinetic_j", m.relax_kinetic_j},
                {"permanent_dent_m", m.permanent_dent_m},
                {"permanent_max_dip_m", m.permanent_max_dip_m},
                {"loaded_dent_m", m.loaded_dent_m},
                {"frames", m.dent_frames},
                {"strike_deflection_mean_m", m.strike_deflection_mean_m},
                {"strike_deflection_amplitude_m", m.strike_deflection_amplitude_m},
                {"plate_deflection_mean_m", m.plate_deflection_mean_m},
                {"dent_depth_m", m.dent_depth_m}}}}},
        {"handoff", {
            {"components", m.components}, {"rigid_fragments", m.rigid_fragments},
            {"debris_particles", m.debris_particles}, {"largest_piece_mass_kg", m.largest_piece_mass_kg},
            {"largest_piece_cells", m.largest_piece_cells}, {"wall_s", m.handoff_wall_s},
            {"pieces_over_1pct", m.pieces_over_1pct}, {"pieces_over_5pct", m.pieces_over_5pct},
            {"mass_fraction_under_1pct", m.mass_fraction_under_1pct}}},
        {"rigid", {
            {"simulated_s", m.rigid_simulated_s}, {"wall_s", m.rigid_wall_s}, {"steps", m.rigid_steps},
            {"came_to_rest", m.came_to_rest}, {"rest_time_s", m.rest_time_s},
            {"ball_speed_at_end_m_s", m.ball_speed_at_end_m_s},
            {"ball_height_at_end_m", m.ball_height_at_end_m},
            {"pieces_at_end", m.pieces_at_end}, {"broken_bonds_total", m.broken_bonds_total},
            {"second_strike_time_s", m.second_strike_time_s},
            {"second_ball_mass_kg", m.second_ball_mass_kg},
            {"second_ball_speed_m_s", m.second_ball_speed_m_s},
            {"second_ball_start_y_m", m.second_ball_start_y_m}}},
        {"refracture", refractureJson(m.refracture)},
        {"simulated_total_s", m.simulated_total_s}, {"wall_total_s", m.wall_total_s},
        {"realtime_ratio", m.realtime_ratio}, {"rule_met", m.rule_met},
        {"recording_wall_s", m.recording_wall_s},
    };
    return j.dump();
}

void writePlayback(const TileImpactResult &result, const std::filesystem::path &path,
                   const std::string *report_json) {
    const auto vec = [](const Vec3 &v) { return Json{v.x, v.y, v.z}; };
    const auto quat = [](const Quat &q) { return Json{q.w, q.x, q.y, q.z}; };
    const std::size_t N = result.frames.empty() ? 0 : result.frames.front().cell_positions.size();
    const std::size_t B = result.bond_nodes.size();
    // A cell belongs to the object it was generated in. In a single-tile scene
    // that is the tile and every cell reads the same; in a many-object scene it
    // is what lets the viewer tell an oak block from the glass under it, and it
    // is also what says there is no rigid striker to draw.
    const bool many = !result.bodies.empty() && result.part_of_node.size() == N;
    // The playground accepts 64 MiB per recording, so the frames are thinned to
    // a budget and bond lines are kept only for the lattice phase (a rigid
    // frame carries no bond state of its own) and only while they fit. Thinning
    // happens here, after the simulation: it never changes what was computed.
    //
    // The cost per frame is measured, not guessed. A flat 130 bytes an item was
    // the estimate before, and it is roughly 1.7x low once doubles serialize at
    // full precision: a 4,000-cell recording budgeted at 26 MB came out over 64
    // and the run was thrown away at the last step, after the physics had
    // already been paid for. One frame is built and dumped here to price the
    // rest.
    constexpr std::size_t kBudgetBytes = 48U * 1024U * 1024U;
    // A sphere built from cubes is drawn as cubes, and at any cell size a viewer
    // reads that as a lump rather than a ball. The lane already knows better:
    // the handoff gives a whole un-joined sphere an authored collision primitive
    // (FragmentPrimitive::Sphere) so Jolt rolls it properly. That knowledge was
    // being thrown away at the drawing step, which left "make the ball round"
    // with no answer except a smaller cell -- and a smaller cell is what puts a
    // scene over the cell cap.
    //
    // So a part that is one un-joined sphere and never loses a bond is drawn as
    // one sphere of the diameter that was asked for, in place of its cells. The
    // conditions are the collision path's, for the same reason: the moment it
    // breaks, the cells are its real surface and no primitive describes it.
    // Bond lines carry their own endpoints, so they are unaffected.
    std::vector<char> draw_whole(result.part_bodies.size(), 0);
    std::vector<std::vector<std::size_t>> whole_cells(result.part_bodies.size());
    std::vector<BodyShape> whole_shape(result.part_bodies.size(), BodyShape::Box);
    std::vector<std::array<double, 4>> whole_rotation(result.part_bodies.size(),
                                                     std::array<double, 4>{1.0, 0.0, 0.0, 0.0});
    if (many) {
        // Bonds do not heal, so the last frame that carries bond state says
        // whether anything inside a part ever failed.
        const std::vector<std::uint8_t> *final_alive = nullptr;
        for (const RecordedFrame &frame : result.frames)
            if (frame.bond_alive.size() == B) final_alive = &frame.bond_alive;
        std::vector<char> part_broke(result.part_bodies.size(), 0);
        if (final_alive != nullptr)
            for (std::size_t o = 0; o < B; ++o) {
                if ((*final_alive)[o] != 0) continue;
                const auto [a, b] = result.bond_nodes[o];
                if (a < N) part_broke[result.part_of_node[a]] = 1;
                if (b < N) part_broke[result.part_of_node[b]] = 1;
            }
        for (std::size_t g = 0; g < result.part_bodies.size(); ++g) {
            if (part_broke[g] || result.part_bodies[g].size() != 1) continue;
            const SceneBody &body = result.bodies[result.part_bodies[g].front()];
            // A cone's cell hull is already its true surface and it carries no
            // authored primitive; a join is a union and no primitive describes
            // one. Everything else was authored as one convex shape, and the
            // cells are an approximation OF it.
            if (body.shape != BodyShape::Sphere && body.shape != BodyShape::Box) continue;
            draw_whole[g] = 1;
            whole_shape[g] = body.shape;
            rotationQuaternion(body.rotation_deg, whole_rotation[g].data());
        }
        for (std::size_t i = 0; i < N; ++i) {
            const std::uint32_t g = result.part_of_node[i];
            if (g < draw_whole.size() && draw_whole[g]) whole_cells[g].push_back(i);
        }
        for (std::size_t g = 0; g < draw_whole.size(); ++g) {
            // A sphere of one cell is a cube either way, and drawing it round
            // would claim a shape the lattice does not have. A box of one cell
            // IS that cube, so it keeps its primitive.
            const bool too_coarse =
                whole_shape[g] == BodyShape::Sphere && whole_cells[g].size() < 2;
            if (whole_cells[g].empty() || too_coarse) {
                draw_whole[g] = 0;
                whole_cells[g].clear();
            }
        }
    }
    // The centroid of a rigid part transforms with it, so one representative
    // pose per frame is exact for as long as the part stays whole.
    const auto wholeCentre = [&](const RecordedFrame &frame, std::size_t group) {
        double cx = 0.0, cy = 0.0, cz = 0.0;
        for (const std::size_t cell : whole_cells[group]) {
            cx += frame.cell_positions[cell].x;
            cy += frame.cell_positions[cell].y;
            cz += frame.cell_positions[cell].z;
        }
        const double n = static_cast<double>(whole_cells[group].size());
        return Vec3{cx / n, cy / n, cz / n};
    };
    // A box has to be turned the way it was authored as well as the way the
    // part is lying, so the two rotations compose. A sphere does not care, but
    // composing costs nothing and keeps one code path. This is the same order
    // the collision shape uses: the authored rotation is applied inside the
    // shape, then the body's own transform on top.
    const auto composeQuat = [](const std::array<double, 4> &lhs, const double *rhs) {
        return std::array<double, 4>{
            lhs[0] * rhs[0] - lhs[1] * rhs[1] - lhs[2] * rhs[2] - lhs[3] * rhs[3],
            lhs[0] * rhs[1] + lhs[1] * rhs[0] + lhs[2] * rhs[3] - lhs[3] * rhs[2],
            lhs[0] * rhs[2] - lhs[1] * rhs[3] + lhs[2] * rhs[0] + lhs[3] * rhs[1],
            lhs[0] * rhs[3] + lhs[1] * rhs[2] - lhs[2] * rhs[1] + lhs[3] * rhs[0]};
    };
    const auto posesFor = [&](const RecordedFrame &frame) {
        Json poses = Json::array();
        for (std::size_t i = 0; i < N; ++i) {
            if (many) {
                const std::uint32_t g = result.part_of_node[i];
                if (g < draw_whole.size() && draw_whole[g]) continue;
            }
            poses.push_back({{"id", "cell:" + std::to_string(i)}, {"position_m", vec(frame.cell_positions[i])},
                             {"orientation_wxyz", quat(frame.cell_orientations[i])},
                             {"component_id", frame.component_ids.empty() ? 0U : frame.component_ids[i]}});
        }
        for (std::size_t g = 0; g < draw_whole.size(); ++g) {
            if (!draw_whole[g]) continue;
            const std::size_t lead = whole_cells[g].front();
            const Quat &lying = frame.cell_orientations[lead];
            const std::array<double, 4> part{lying.w, lying.x, lying.y, lying.z};
            const std::array<double, 4> turned = composeQuat(part, whole_rotation[g].data());
            poses.push_back({{"id", "whole:" + std::to_string(g)},
                             {"position_m", vec(wholeCentre(frame, g))},
                             {"orientation_wxyz", Json{turned[0], turned[1], turned[2], turned[3]}},
                             {"component_id", frame.component_ids.empty() ? 0U : frame.component_ids[lead]}});
        }
        if (!many)
            poses.push_back({{"id", "ball"}, {"position_m", vec(frame.ball_center)},
                             {"orientation_wxyz", quat(frame.ball_orientation)}, {"component_id", 0}});
        for (std::size_t k = 0; k < result.ledges.size(); ++k)
            poses.push_back({{"id", "ledge:" + std::to_string(k)}, {"position_m", vec(result.ledges[k].center_m)},
                             {"orientation_wxyz", Json{1, 0, 0, 0}}, {"component_id", 0}});
        return poses;
    };
    const auto bondsFor = [&](const RecordedFrame &frame) {
        Json bonds = Json::array();
        if (frame.phase == "lattice" && frame.bond_alive.size() == B)
            for (std::size_t o = 0; o < B; ++o) {
                const auto [a, b] = result.bond_nodes[o];
                bonds.push_back({{"a_m", vec(frame.cell_positions[a])}, {"b_m", vec(frame.cell_positions[b])},
                                 {"live", frame.bond_alive[o] != 0},
                                 {"damage", static_cast<double>(frame.bond_damage[o])}});
            }
        return bonds;
    };
    std::size_t pose_bytes = 1;
    std::size_t bond_bytes = 0;
    if (!result.frames.empty()) {
        // Not the first frame. At rest every coordinate is a round multiple of
        // the cell size and serializes in a few characters; once the plate has
        // moved they are full-precision doubles and cost twice as much. Sample
        // across the run and price the widest frame, or the budget is set by
        // the cheapest one and the recording overruns after it is too late.
        const std::size_t last = result.frames.size() - 1;
        for (const std::size_t f : {std::size_t(0), last / 3, (2 * last) / 3, last}) {
            const std::size_t bytes = posesFor(result.frames[f]).dump().size();
            pose_bytes = std::max(pose_bytes, bytes);
            if (result.frames[f].phase == "lattice" && result.frames[f].bond_alive.size() == B)
                bond_bytes = std::max(bond_bytes, bondsFor(result.frames[f]).dump().size());
        }
        if (bond_bytes == 0)
            for (const RecordedFrame &frame : result.frames)
                if (frame.phase == "lattice" && frame.bond_alive.size() == B) {
                    bond_bytes = bondsFor(frame).dump().size();
                    break;
                }
    }
    // Leave room for each frame's envelope, and take the bodies table off the
    // top: it is one entry per cell and is not free at four thousand of them.
    const std::size_t frame_bytes = pose_bytes + 96;
    const std::size_t fixed_bytes = 160 * (N + 1 + result.ledges.size()) + 64 * 1024;
    std::vector<std::size_t> kept;
    {
        const std::size_t spare = kBudgetBytes > fixed_bytes ? kBudgetBytes - fixed_bytes : frame_bytes * 8;
        const std::size_t budget_frames = std::max<std::size_t>(8, spare / frame_bytes);
        const std::size_t total = result.frames.size();
        const std::size_t stride = total <= budget_frames ? 1 : (total + budget_frames - 1) / budget_frames;
        std::size_t last_lattice = total;
        for (std::size_t f = 0; f < total; ++f)
            if (result.frames[f].phase == "lattice") last_lattice = f;
        for (std::size_t f = 0; f < total; ++f)
            if (f % stride == 0 || f + 1 == total || f == last_lattice) kept.push_back(f);
    }
    std::size_t lattice_frames_kept = 0;
    for (const std::size_t f : kept) lattice_frames_kept += result.frames[f].phase == "lattice" ? 1 : 0;
    const bool record_bonds =
        bond_bytes * lattice_frames_kept + kept.size() * frame_bytes + fixed_bytes <= kBudgetBytes;
    Json bodies = Json::array();
    const double h = result.cell_size_m;
    for (std::size_t i = 0; i < N; ++i) {
        const std::uint32_t group = many ? result.part_of_node[i] : 0U;
        if (group < draw_whole.size() && draw_whole[group]) continue;
        // A joined part is several bodies; the first one names and colours it.
        const std::size_t part = group < result.part_bodies.size() && !result.part_bodies[group].empty()
                                     ? result.part_bodies[group].front() : group;
        const std::string material = many ? std::string(materialPresetName(result.bodies[part].material))
                                          : result.tile_material_name;
        bodies.push_back({{"id", "cell:" + std::to_string(i)},
                          {"object_id", many ? 100 + static_cast<int>(group) : 2},
                          {"element_id", i},
                          {"material_id", many ? result.bodies[part].name + " (" + material + ")" : material},
                          {"color_rgba", many ? result.bodies[part].color_rgba : 0x9fd3ffffU},
                          {"shape", "box"}, {"dimensions_m", Json{h, h, h}}});
    }
    for (std::size_t g = 0; g < draw_whole.size(); ++g) {
        if (!draw_whole[g]) continue;
        const SceneBody &body = result.bodies[result.part_bodies[g].front()];
        const std::string material{materialPresetName(body.material)};
        bodies.push_back({{"id", "whole:" + std::to_string(g)},
                          {"object_id", 100 + static_cast<int>(g)},
                          {"element_id", 0},
                          {"material_id", body.name + " (" + material + ")"},
                          {"color_rgba", body.color_rgba},
                          {"shape", whole_shape[g] == BodyShape::Sphere ? "sphere" : "box"},
                          {"dimensions_m", vec(body.dimensions_m)}});
    }
    // A many-object scene has no rigid striker to draw.
    if (!many)
    bodies.push_back({{"id", "ball"}, {"object_id", 1}, {"element_id", 0},
                      {"material_id", result.ball_material_name}, {"color_rgba", 0x8a8f99ffU},
                      {"shape", "sphere"},
                      {"dimensions_m", Json{2 * result.ball_radius_m, 2 * result.ball_radius_m, 2 * result.ball_radius_m}}});
    for (std::size_t k = 0; k < result.ledges.size(); ++k) {
        bodies.push_back({{"id", "ledge:" + std::to_string(k)}, {"object_id", 900 + k}, {"element_id", 0},
                          {"material_id", result.ground_material_name}, {"color_rgba", 0x7a7a7affU},
                          {"shape", "box"}, {"dimensions_m", vec(result.ledges[k].dimensions_m)}});
    }
    const double g = 1.0;
    Json supports = Json::array();
    supports.push_back({vec({-g, result.ground_y, -g}), vec({g, result.ground_y, -g}), vec({g, result.ground_y, g})});
    supports.push_back({vec({-g, result.ground_y, -g}), vec({g, result.ground_y, g}), vec({-g, result.ground_y, g})});

    Json frames = Json::array();
    for (const std::size_t kept_index : kept) {
        const RecordedFrame &frame = result.frames[kept_index];
        Json poses = posesFor(frame);
        Json bonds = record_bonds ? bondsFor(frame) : Json::array();
        frames.push_back({{"time_s", frame.time_s}, {"phase", frame.phase}, {"poses", std::move(poses)},
                          {"bonds", std::move(bonds)}, {"fracture_count", frame.fracture_count}});
    }
    // Who touched whom, by the names the request used. Measured from Jolt's own
    // contact callbacks rather than inferred from how close two bodies came --
    // an inferred contact is a guess, and this is the channel a model is meant
    // to trust.
    Json contacts = Json::array();
    for (const ContactPair &pair : result.contacts)
        contacts.push_back({{"a", pair.a}, {"b", pair.b},
                            {"first_time_s", pair.first_time_s},
                            {"peak_closing_speed_m_s", pair.peak_closing_speed_m_s},
                            {"peak_impulse_n_s", pair.peak_impulse_n_s},
                            {"peak_energy_j", pair.peak_energy_j},
                            {"events", pair.events}});
    Json artifact{{"schema", "banjo.playback.v1"}, {"mode", "network"}, {"units", "SI"},
                  {"bodies", std::move(bodies)}, {"supports", std::move(supports)},
                  {"contacts", std::move(contacts)}, {"frames", std::move(frames)},
                  {"requested_steps", result.measurements.lattice_steps + result.measurements.rigid_steps},
                  {"completed_steps", result.measurements.lattice_steps + result.measurements.rigid_steps},
                  {"sampling", {{"stride_steps", 0}, {"maximum_frames", kept.size()}, {"interpolation", "none"},
                                {"captured_frames", result.frames.size()}, {"bond_lines", record_bonds}}},
                  {"physical_response_validated", false},
                  {"status", "complete"}, {"error", ""},
                  {"report", Json::parse(report_json != nullptr ? *report_json
                                              : measurementsJson(result.measurements))}};
    const std::string serialized = artifact.dump();
    if (serialized.size() > 64U * 1024U * 1024U) throw std::runtime_error("playback exceeds 64 MiB");
    std::ofstream output(path, std::ios::binary);
    if (!output) throw std::runtime_error("could not open playback output " + path.string());
    output.write(serialized.data(), static_cast<std::streamsize>(serialized.size()));
}

SolverComparison compareWithBrittleBondSolver(
    const TileImpactRequest &request, std::uint64_t steps, Precision fast_precision,
    BackendKind fast_backend, bool permuted_reference, std::string *log) {
    if (request.layout != SceneLayout::Flat)
        throw std::invalid_argument("the BrittleBondSolver comparison needs the flat layout: "
                                    "the CPU solver has one support footprint");
    TileImpactRequest fast_request = request;
    fast_request.precision = fast_precision;
    fast_request.backend = fast_backend;
    // BrittleBondSolver has no node-to-node contact, so the comparison runs both
    // lanes without it: this measurement is about the sweep order and the
    // arithmetic, and enabling on one side only would compare two physics.
    fast_request.node_contact = NodeContactMode::Off;
    auto reference_setup = buildTileImpactSetup(request);
    auto fast_setup = buildTileImpactSetup(fast_request);
    const double dt = reference_setup->dt_s;
    SolverComparison c;
    c.steps = steps;
    c.dt_s = dt;
    c.history_stride = std::max<std::uint64_t>(1, steps / 50);

    // Reference: BrittleBondSolver, one substep and one iteration per call,
    // with the same sphere protocol around it. Its sweep order is the bond
    // order of the asset it is given.
    LatticeAsset permuted_asset;
    ActiveMatter permuted_matter;
    std::vector<std::uint32_t> reference_to_original(reference_setup->asset.bonds.size());
    ActiveMatter *reference_matter = &reference_setup->matter;
    for (std::uint32_t o = 0; o < reference_to_original.size(); ++o) reference_to_original[o] = o;
    if (permuted_reference) {
        const LatticeSchedule &schedule = reference_setup->schedule;
        permuted_asset = reference_setup->asset;
        permuted_asset.bonds.clear();
        for (std::uint32_t k = 0; k < schedule.bond_order.size(); ++k) {
            permuted_asset.bonds.push_back(reference_setup->asset.bonds[schedule.bond_order[k]]);
            reference_to_original[k] = schedule.bond_order[k];
        }
        std::vector<std::uint32_t> degree(permuted_asset.nodes.size(), 0U);
        for (const BondRest &bond : permuted_asset.bonds) { ++degree[bond.node_a]; ++degree[bond.node_b]; }
        permuted_asset.adjacency_offsets.assign(permuted_asset.nodes.size() + 1U, 0U);
        for (std::size_t n = 0; n < permuted_asset.nodes.size(); ++n)
            permuted_asset.adjacency_offsets[n + 1U] = permuted_asset.adjacency_offsets[n] + degree[n];
        permuted_asset.adjacent_bond_indices.resize(permuted_asset.adjacency_offsets.back());
        std::vector<std::uint32_t> cursor = permuted_asset.adjacency_offsets;
        for (std::uint32_t k = 0; k < permuted_asset.bonds.size(); ++k) {
            permuted_asset.adjacent_bond_indices[cursor[permuted_asset.bonds[k].node_a]++] = k;
            permuted_asset.adjacent_bond_indices[cursor[permuted_asset.bonds[k].node_b]++] = k;
        }
        permuted_matter = reference_setup->matter;
        permuted_matter.asset = &permuted_asset;
        reference_matter = &permuted_matter;
    }
    {
        TileImpactSetup &s = *reference_setup;
        ActiveMatter &matter = *reference_matter;
        const StepSettings<double> &S = s.settings_world;
        BrittleBondSolver solver({
            .substeps = 1,
            .constraint_iterations = std::max(1U, request.constraint_iterations),
            .use_support_plane = true,
            // The CPU solver sees the plane raised by the node radius: the
            // same rule this lane applies per node.
            .support_plane = makeSupportPlane(
                {0.0, s.ground_y + S.support.planes[0].node_radius, 0.0}, {0.0, 1.0, 0.0}),
            .surface_dynamic_friction = s.tile_ground.dynamic_friction,
            .surface_restitution = s.tile_ground.restitution,
            .surface_static_friction = s.tile_ground.static_friction,
            .support_enabled = true,
            .support_in_constraint_solve = true,
        });
        CoupledSphereState sphere{{toVec3(s.sphere_world.center), {}, toVec3(s.sphere_world.velocity), {}},
                                  s.sphere_world.radius, s.sphere_world.mass, s.sphere_world.inertia};
        const SphereMaterialContactSettings contact{
            .static_friction = S.contact.static_friction,
            .dynamic_friction = S.contact.dynamic_friction,
            .restitution = S.contact.restitution,
            .restitution_speed_threshold_m_s = S.contact.restitution_speed_threshold,
            .node_contact_radius_m = S.contact.node_contact_radius,
            .contact_margin_m = S.contact.contact_margin,
        };
        ContactAccumulators acc{};
        clearContactAccumulators(acc);
        const auto begin = Clock::now();
        SolverComparison::Lane &lane = c.reference;
        lane.name = permuted_reference ? "BrittleBondSolver schedule-order" : "BrittleBondSolver index-order";
        for (std::uint64_t step = 0; step < steps; ++step) {
            sphere.motion.linear_velocity_m_s += dt * request.gravity_m_s2;
            const MaterialStepStats stats = solver.step(matter, dt, request.gravity_m_s2, &sphere, contact);
            lane.removed_energy_j += stats.unassigned_bond_removal_energy_j;
            if (stats.broken_bonds_this_step > 0 && lane.first_failure_step < 0) {
                lane.first_failure_step = static_cast<std::int64_t>(step);
                for (std::uint32_t k = 0; k < matter.bonds.size(); ++k)
                    if (!matter.bonds[k].alive) lane.first_failure_bonds.push_back(reference_to_original[k]);
                std::sort(lane.first_failure_bonds.begin(), lane.first_failure_bonds.end());
            }
            sphere.motion.center_of_mass_world_m += dt * sphere.motion.linear_velocity_m_s;
            SphereState<double> ball{toV3(sphere.motion.center_of_mass_world_m), toV3(sphere.motion.linear_velocity_m_s),
                                     toV3(sphere.motion.angular_velocity_rad_s), sphere.radius_m, sphere.mass_kg, sphere.inertia_kg_m2};
            sphereSupportContact(S, ball, acc);
            sphere.motion.center_of_mass_world_m = toVec3(ball.center);
            sphere.motion.linear_velocity_m_s = toVec3(ball.velocity);
            if ((step + 1) % c.history_stride == 0) lane.broken_history.push_back(static_cast<std::uint32_t>(stats.total_broken_bonds));
        }
        lane.wall_s = seconds(begin, Clock::now());
        lane.broken_bonds = static_cast<std::uint32_t>(countBrokenBonds(matter));
        std::size_t count = 0, largest = 0;
        double largest_mass = 0.0;
        (void)componentIds(matter, &count, &largest, &largest_mass);
        lane.components = count;
        lane.largest_piece_cells = largest;
        lane.largest_piece_mass_kg = largest_mass;
        lane.bond_updates_per_s = lane.wall_s > 0.0
            ? static_cast<double>(matter.bonds.size()) * static_cast<double>(steps) / lane.wall_s : 0.0;
    }
    // Fast lane, same protocol.
    {
        TileImpactSetup &s = *fast_setup;
        LatticeState state = buildLatticeState(s.matter, s.schedule, s.origin);
        SphereState<double> sphere = s.sphere_world;
        sphere.center = sphere.center - toV3(s.origin);
        std::unique_ptr<LatticeBackend> backend = makeBackend(s.request, s.schedule);
        SolverComparison::Lane &lane = c.fast;
        lane.name = backend->name() + " colour-order";
        const auto begin = Clock::now();
        backend->upload(state, s.settings_scene, sphere);
        RunControl control{};
        control.capture_stride = c.history_stride;
        control.max_frames = static_cast<unsigned>(steps / c.history_stride + 1);
        control.steps_per_launch = s.request.steps_per_launch;
        // Two legs: through the reference's first failure step, so the bonds
        // dead at that point are exactly this lane's first failure set when
        // its first failure lands on the same step (the backend reports the
        // step itself), then the rest of the window from that state.
        const std::uint64_t first_leg = c.reference.first_failure_step >= 0
            ? std::min<std::uint64_t>(steps, static_cast<std::uint64_t>(c.reference.first_failure_step) + 1) : steps;
        control.max_steps = first_leg;
        RunStatus status = backend->run(control);
        if (status.broken_bonds > 0) {
            LatticeState probe = state;
            SphereState<double> probe_sphere = sphere;
            backend->download(probe, probe_sphere);
            lane.first_failure_step = static_cast<std::int64_t>(status.first_failure_step);
            for (std::size_t k = 0; k < probe.alive.size(); ++k)
                if (!probe.alive[k]) lane.first_failure_bonds.push_back(s.schedule.bond_order[k]);
        }
        if (first_leg < steps) {
            control.max_steps = steps - first_leg;
            status = backend->run(control);
        }
        std::vector<FrameCapture> captures = backend->takeFrames();
        backend->download(state, sphere);
        lane.wall_s = seconds(begin, Clock::now());
        writeBackLatticeState(state, s.schedule, s.matter);
        lane.removed_energy_j = status.removed_energy_j;
        lane.broken_bonds = status.broken_bonds;
        for (const FrameCapture &capture : captures) {
            std::uint32_t broken = 0;
            for (std::size_t k = 0; k < capture.alive.size(); ++k) if (!capture.alive[k]) ++broken;
            if (capture.step > 0) lane.broken_history.push_back(broken);
        }
        if (lane.first_failure_step < 0 && status.broken_bonds > 0) {
            // The reference never failed but this lane did: report the lane's
            // own first step with everything dead at the end of the window.
            lane.first_failure_step = static_cast<std::int64_t>(status.first_failure_step);
            for (std::uint32_t o = 0; o < s.matter.bonds.size(); ++o)
                if (!s.matter.bonds[o].alive) lane.first_failure_bonds.push_back(o);
        }
        std::sort(lane.first_failure_bonds.begin(), lane.first_failure_bonds.end());
        std::size_t count = 0, largest = 0;
        double largest_mass = 0.0;
        (void)componentIds(s.matter, &count, &largest, &largest_mass);
        lane.components = count;
        lane.largest_piece_cells = largest;
        lane.largest_piece_mass_kg = largest_mass;
        lane.bond_updates_per_s = lane.wall_s > 0.0
            ? static_cast<double>(s.matter.bonds.size()) * static_cast<double>(steps) / lane.wall_s : 0.0;
    }
    // State differences.
    const ActiveMatter &a = *reference_matter, &b = fast_setup->matter;
    for (std::size_t i = 0; i < a.nodes.size(); ++i) {
        c.max_position_difference_m = std::max(c.max_position_difference_m,
            length(a.nodes[i].position_world_m - b.nodes[i].position_world_m));
        c.max_velocity_difference_m_s = std::max(c.max_velocity_difference_m_s,
            length(a.nodes[i].velocity_m_s - b.nodes[i].velocity_m_s));
    }
    for (std::size_t k = 0; k < a.bonds.size(); ++k)
        if (a.bonds[k].alive != b.bonds[reference_to_original[k]].alive) ++c.alive_mismatches;
    {
        std::vector<std::uint32_t> diff;
        std::set_symmetric_difference(c.reference.first_failure_bonds.begin(), c.reference.first_failure_bonds.end(),
                                      c.fast.first_failure_bonds.begin(), c.fast.first_failure_bonds.end(),
                                      std::back_inserter(diff));
        c.first_failure_set_symmetric_difference = diff.size();
    }
    if (log) *log += "comparison complete\n";
    return c;
}

std::string comparisonJson(const SolverComparison &c) {
    const auto lane = [](const SolverComparison::Lane &l) {
        return Json{{"name", l.name}, {"first_failure_step", l.first_failure_step},
                    {"first_failure_bond_count", l.first_failure_bonds.size()},
                    {"broken_bonds", l.broken_bonds}, {"components", l.components},
                    {"largest_piece_cells", l.largest_piece_cells}, {"largest_piece_mass_kg", l.largest_piece_mass_kg},
                    {"removed_energy_j", l.removed_energy_j}, {"wall_s", l.wall_s},
                    {"bond_updates_per_s", l.bond_updates_per_s}, {"broken_history", l.broken_history}};
    };
    Json j{{"steps", c.steps}, {"dt_s", c.dt_s}, {"history_stride", c.history_stride},
           {"reference", lane(c.reference)}, {"fast", lane(c.fast)},
           {"max_position_difference_m", c.max_position_difference_m},
           {"max_velocity_difference_m_s", c.max_velocity_difference_m_s},
           {"alive_mismatches", c.alive_mismatches},
           {"first_failure_set_symmetric_difference", c.first_failure_set_symmetric_difference}};
    return j.dump();
}

} // namespace banjo::fastlattice
