#include "fastlattice/TileImpactScene.hpp"

#include "fracture/BondFailure.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "material/MaterialCompiler.hpp"
#include "rigid/JoltWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
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
#include <vector>

namespace banjo::fastlattice {
namespace {

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

double seconds(Clock::time_point from, Clock::time_point to) {
    return std::chrono::duration<double>(to - from).count();
}

V3<double> toV3(const Vec3 &v) { return {v.x, v.y, v.z}; }
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

StepSettings<double> buildSettings(const TileImpactSetup &setup, const Vec3 &origin) {
    const TileImpactRequest &r = setup.request;
    StepSettings<double> s{};
    s.dt = setup.dt_s;
    s.gravity = toV3(r.gravity_m_s2);
    s.constraint_iterations = std::max(1U, r.constraint_iterations);
    s.damping_fraction = setup.compiled.bond_damping > 0.0
        ? 1.0 - std::exp(-setup.compiled.bond_damping * setup.dt_s) : 0.0;
    s.sphere_enabled = 1;
    s.direct_arithmetic = r.precision == Precision::Double ? 1 : 0;
    s.contact.static_friction = setup.ball_tile.static_friction;
    s.contact.dynamic_friction = setup.ball_tile.dynamic_friction;
    s.contact.restitution = setup.ball_tile.restitution;
    s.contact.restitution_speed_threshold = 0.5;
    s.contact.node_contact_radius = r.node_contact_radius_factor * r.cell_size_m;
    s.contact.contact_margin = 1.0e-5;
    s.contact.prefilter_slack = 0.05 * r.ball_radius_m;
    const double infinity = std::numeric_limits<double>::infinity();
    // Nodes are cell centres, so a node rests half a cell above a surface.
    const double node_radius = 0.5 * r.cell_size_m;
    if (r.layout == SceneLayout::Flat) {
        SupportPlane<double> ground = makePlane(Vec3{0.0, setup.ground_y, 0.0} - origin, setup.tile_ground, node_radius);
        addFootprint(ground, 0.0, 0.0, infinity, infinity);
        s.support.plane_count = 1;
        s.support.planes[0] = ground;
    } else {
        SupportPlane<double> ledges = makePlane(Vec3{0.0, setup.tile_bottom_y, 0.0} - origin, setup.tile_ground, node_radius);
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

std::uint64_t stepsFor(double milliseconds, double dt) {
    if (milliseconds <= 0.0) return 0;
    return static_cast<std::uint64_t>(std::ceil(milliseconds * 1.0e-3 / dt));
}

std::unique_ptr<LatticeBackend> makeBackend(const TileImpactRequest &r, const LatticeSchedule &schedule) {
    if (r.backend == BackendKind::Cuda)
        return makeCudaLatticeBackend(schedule, r.precision, r.threads_per_block);
    return makeCpuLatticeBackend(schedule, r.precision);
}

Vec3 nodePosition(const LatticeState &state, std::uint32_t i) {
    return state.origin + Vec3{state.x0[3 * i] + state.u[3 * i], state.x0[3 * i + 1] + state.u[3 * i + 1],
                               state.x0[3 * i + 2] + state.u[3 * i + 2]};
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
    if (!(r.cell_size_m > 0.0) || !(r.ball_radius_m > 0.0) || !(r.dt_factor > 0.0) ||
        !(r.tile_dimensions_m.x > 0.0) || !(r.tile_dimensions_m.y > 0.0) || !(r.tile_dimensions_m.z > 0.0))
        throw std::invalid_argument("tile impact request needs positive sizes and a positive dt factor");

    s.tile_material = makeReferenceMaterial(r.tile_material, r.material_seed);
    s.tile_material.failure_law = r.failure_law;
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
    s.asset = generateBoxTileLattice({r.tile_dimensions_m, r.cell_size_m, r.neighbor_horizon_cells},
                                 s.compiled, &s.layout);
    s.limit = measureLatticeResolutionLimit(s.asset, s.compiled);
    if (!(s.limit.explicit_substep_limit_s > 0.0))
        throw std::runtime_error("lattice has no resolution limit; is the material stiffness zero?");
    s.dt_s = r.dt_factor * s.limit.explicit_substep_limit_s;

    s.ground_y = 0.0;
    s.tile_bottom_y = r.layout == SceneLayout::Flat ? 0.0 : r.ledge_height_m;
    s.tile_top_y = s.tile_bottom_y + r.tile_dimensions_m.y;
    const Vec3 tile_center{0.0, s.tile_bottom_y + 0.5 * r.tile_dimensions_m.y, 0.0};
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
    for (const LatticeNodeRest &node : s.asset.nodes) {
        const Vec3 position = tile_center + (node.local_position_m - s.asset.rest_center_of_mass_m);
        matter.nodes.push_back({position, position, {}, node.represented_volume_m3 * s.compiled.density_kg_m3, {}});
        matter.reference_positions_world_m.push_back(position);
    }
    matter.bonds.resize(s.asset.bonds.size());

    s.ball_tile = combineContactMaterials(compileContactMaterial(s.ball_material), compileContactMaterial(s.tile_material));
    s.tile_ground = combineContactMaterials(compileContactMaterial(s.tile_material), compileContactMaterial(s.ground_material));
    s.ball_ground = combineContactMaterials(compileContactMaterial(s.ball_material), compileContactMaterial(s.ground_material));

    const double volume = 4.0 / 3.0 * std::numbers::pi * std::pow(r.ball_radius_m, 3.0);
    s.sphere_world.center = {r.ball_offset_x_m, s.tile_top_y + r.ball_radius_m + r.ball_gap_m, r.ball_offset_z_m};
    s.sphere_world.velocity = {0.0, -r.ball_speed_m_s, 0.0};
    s.sphere_world.angular_velocity = {0.0, 0.0, 0.0};
    s.sphere_world.radius = r.ball_radius_m;
    s.sphere_world.mass = volume * s.ball_material.density_kg_m3;
    s.sphere_world.inertia = 0.4 * s.sphere_world.mass * r.ball_radius_m * r.ball_radius_m;

    s.settings_scene = buildSettings(s, s.origin);
    s.settings_world = buildSettings(s, Vec3{});

    std::vector<std::uint32_t> slabs = boxLatticeSlabs(s.layout, r.neighbor_horizon_cells, std::max(1U, r.blocks));
    s.schedule = buildLatticeSchedule(s.asset, slabs);

    s.quiet_steps = stepsFor(r.quiet_ms, s.dt_s);
    s.min_steps = stepsFor(r.min_ms, s.dt_s);
    s.max_steps = std::max<std::uint64_t>(1, stepsFor(r.max_ms, s.dt_s));
    s.no_failure_steps = stepsFor(r.no_failure_ms, s.dt_s);
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
    if (status.last_failure_step != std::numeric_limits<std::uint64_t>::max())
        m.last_failure_s = static_cast<double>(status.last_failure_step) * setup.dt_s;
    if (status.first_failure_step != std::numeric_limits<std::uint64_t>::max())
        m.first_failure_s = static_cast<double>(status.first_failure_step) * setup.dt_s;
    for (unsigned p = 0; p < kPhaseCount; ++p) m.phase_seconds[p] = status.phase_seconds[p];
    m.shared_memory_positions = status.shared_memory_positions;
    m.shared_memory_bytes = status.shared_memory_bytes;
    m.max_tensile_stretch = status.max_tensile_stretch;
    m.max_compressive_strain = status.max_compressive_strain;
    m.max_shear_strain = status.max_shear_strain;
    m.degenerate_disagreements = status.degenerate_disagreements;
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

    // Handoff: connected components -> rigid fragments -> Jolt.
    const auto handoff_begin = Clock::now();
    writeBackLatticeState(state, setup.schedule, setup.matter);
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
    const FragmentBuildResult build = buildFragmentRepresentations(setup.matter, components, {
        .first_body_id = 1000,
        .maximum_rigid_fragments = std::max<std::size_t>(1, components.size()),
        .minimum_nodes_per_rigid_fragment = 1,
        .maximum_collision_points = 192,
        .friction = setup.tile_ground.dynamic_friction,
        .restitution = setup.tile_ground.restitution,
    });
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
    world.addBall({.body_id = kBallId, .radius_m = r.ball_radius_m, .material = setup.ball_material,
                   .position_world_m = ball_center, .linear_velocity_m_s = toVec3(sphere.velocity),
                   .angular_velocity_rad_s = toVec3(sphere.angular_velocity),
                   .mass_override_kg = setup.sphere_world.mass, .sphere_inertia_factor = 0.4});
    world.addFragments(build.rigid_fragments);
    // Cell -> fragment mapping and the cells' offsets in the fragment frame at handoff.
    std::vector<std::int32_t> cell_fragment(N, -1);
    std::vector<Vec3> cell_offset(N);
    std::vector<std::uint32_t> handoff_component = componentIds(setup.matter, nullptr, nullptr, nullptr);
    {
        std::size_t fragment_index = 0;
        // buildFragmentRepresentations visits components sorted the same way
        // findConnectedComponents already sorted them; rigid ones keep that order.
        for (const auto &component : components) {
            if (fragment_index >= build.rigid_fragments.size()) break;
            const RigidFragmentDescription &fragment = build.rigid_fragments[fragment_index];
            if (fragment.source_node_count != component.node_indices.size()) continue;
            for (const std::uint32_t node : component.node_indices) {
                cell_fragment[node] = static_cast<std::int32_t>(fragment_index);
                cell_offset[node] = setup.matter.nodes[node].position_world_m -
                                    fragment.mass_properties.center_of_mass_world_m;
            }
            ++fragment_index;
        }
    }
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

    // Rigid phase: step Jolt until everything is at rest or the limit.
    const auto rigid_begin = Clock::now();
    const double rigid_dt = r.rigid_step_s;
    const std::uint64_t rigid_limit_steps = static_cast<std::uint64_t>(std::ceil(r.settle_limit_s / rigid_dt));
    const std::uint64_t rigid_stride = std::max<std::uint64_t>(1, rigid_limit_steps / std::max(1U, r.rigid_frames));
    double still_since = -1.0;
    double rigid_time = 0.0;
    // Rest is judged on the pieces. The ball is reported separately: under
    // Jolt's rolling resistance a ball that rolled off keeps rolling for tens
    // of seconds, which is physical and not the pieces' settling.
    std::vector<MatterBodyId> dynamic_ids;
    for (const auto &fragment : build.rigid_fragments) dynamic_ids.push_back(fragment.body_id);
    const auto capture_rigid = [&](double time_offset) {
        RecordedFrame frame;
        frame.time_s = m.lattice_simulated_s + time_offset;
        frame.phase = "rigid";
        frame.cell_positions.resize(N);
        frame.cell_orientations.assign(N, Quat{});
        for (std::size_t f = 0; f < build.rigid_fragments.size(); ++f) {
            const RigidSnapshot snap = world.snapshot(build.rigid_fragments[f].body_id);
            for (std::size_t i = 0; i < N; ++i) {
                if (cell_fragment[i] != static_cast<std::int32_t>(f)) continue;
                frame.cell_positions[i] = snap.center_of_mass_world_m + snap.orientation_world.rotate(cell_offset[i]);
                frame.cell_orientations[i] = snap.orientation_world;
            }
        }
        for (const Debris &d : debris)
            for (std::size_t k = 0; k < d.nodes.size(); ++k)
                frame.cell_positions[d.nodes[k]] = d.position + d.offsets[k];
        const RigidSnapshot ball = world.snapshot(kBallId);
        frame.ball_center = ball.center_of_mass_world_m;
        frame.ball_orientation = ball.orientation_world;
        frame.component_ids = handoff_component;
        frame.fracture_count = status.broken_bonds;
        result.frames.push_back(std::move(frame));
    };
    for (std::uint64_t step = 0; step < rigid_limit_steps; ++step) {
        world.step(rigid_dt);
        for (Debris &d : debris) {
            d.velocity += rigid_dt * r.gravity_m_s2;
            d.position += rigid_dt * d.velocity;
            if (d.position.y < setup.ground_y) { d.position.y = setup.ground_y; d.velocity = {}; }
        }
        rigid_time += rigid_dt;
        ++m.rigid_steps;
        bool still = true;
        for (const MatterBodyId id : dynamic_ids) {
            const RigidSnapshot snap = world.snapshot(id);
            if (length(snap.linear_velocity_m_s) > r.rest_speed_m_s ||
                length(snap.angular_velocity_rad_s) > r.rest_angular_rad_s) { still = false; break; }
        }
        if (still) {
            if (still_since < 0.0) still_since = rigid_time;
        } else {
            still_since = -1.0;
        }
        if ((step + 1) % rigid_stride == 0) capture_rigid(rigid_time);
        if (still && rigid_time - still_since >= r.rest_hold_s) {
            m.came_to_rest = true;
            m.rest_time_s = m.lattice_simulated_s + still_since;
            break;
        }
    }
    {
        const RigidSnapshot ball = world.snapshot(kBallId);
        m.ball_speed_at_end_m_s = length(ball.linear_velocity_m_s);
        m.ball_height_at_end_m = ball.center_of_mass_world_m.y;
    }
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
    result.bond_nodes.reserve(B);
    for (const BondRest &bond : setup.asset.bonds) result.bond_nodes.emplace_back(bond.node_a, bond.node_b);
    if (log) *log += notes.str();
    return result;
}

std::string measurementsJson(const TileImpactMeasurements &m) {
    Json phases = Json::object();
    for (unsigned p = 0; p < kPhaseCount; ++p) phases[latticePhaseName(p)] = m.phase_seconds[p];
    Json j{
        {"phase_seconds", phases},
        {"shared_memory_positions", m.shared_memory_positions},
        {"shared_memory_bytes", m.shared_memory_bytes},
        {"max_tensile_stretch", m.max_tensile_stretch},
        {"max_compressive_strain", m.max_compressive_strain},
        {"max_shear_strain", m.max_shear_strain},
        {"degenerate_disagreements", m.degenerate_disagreements},
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
                {"ball_support_events", m.contact.ball_support_events}}}}},
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
            {"ball_height_at_end_m", m.ball_height_at_end_m}}},
        {"simulated_total_s", m.simulated_total_s}, {"wall_total_s", m.wall_total_s},
        {"realtime_ratio", m.realtime_ratio}, {"rule_met", m.rule_met},
        {"recording_wall_s", m.recording_wall_s},
    };
    return j.dump();
}

void writePlayback(const TileImpactResult &result, const std::filesystem::path &path) {
    const auto vec = [](const Vec3 &v) { return Json{v.x, v.y, v.z}; };
    const auto quat = [](const Quat &q) { return Json{q.w, q.x, q.y, q.z}; };
    const std::size_t N = result.frames.empty() ? 0 : result.frames.front().cell_positions.size();
    const std::size_t B = result.bond_nodes.size();
    // The playground accepts 64 MiB per recording. A cell pose costs about
    // 130 bytes and a bond line about 130 bytes, so the frames are thinned to a
    // budget and bond lines are kept only for the lattice phase (a rigid frame
    // carries no bond state of its own) and only while they fit. Thinning
    // happens here, after the simulation: it never changes what was computed.
    constexpr std::size_t kBudgetBytes = 48U * 1024U * 1024U;
    constexpr std::size_t kBytesPerItem = 130;
    std::vector<std::size_t> kept;
    {
        const std::size_t per_frame = kBytesPerItem * std::max<std::size_t>(1, N + 1 + result.ledges.size());
        const std::size_t budget_frames = std::max<std::size_t>(8, kBudgetBytes / per_frame);
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
        B * lattice_frames_kept * kBytesPerItem + kept.size() * (N + 1) * kBytesPerItem <= kBudgetBytes;
    Json bodies = Json::array();
    const double h = result.cell_size_m;
    for (std::size_t i = 0; i < N; ++i) {
        bodies.push_back({{"id", "cell:" + std::to_string(i)}, {"object_id", 2}, {"element_id", i},
                          {"material_id", result.tile_material_name}, {"color_rgba", 0x9fd3ffffU},
                          {"shape", "box"}, {"dimensions_m", Json{h, h, h}}});
    }
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
        Json poses = Json::array();
        for (std::size_t i = 0; i < N; ++i) {
            poses.push_back({{"id", "cell:" + std::to_string(i)}, {"position_m", vec(frame.cell_positions[i])},
                             {"orientation_wxyz", quat(frame.cell_orientations[i])},
                             {"component_id", frame.component_ids.empty() ? 0U : frame.component_ids[i]}});
        }
        poses.push_back({{"id", "ball"}, {"position_m", vec(frame.ball_center)},
                         {"orientation_wxyz", quat(frame.ball_orientation)}, {"component_id", 0}});
        for (std::size_t k = 0; k < result.ledges.size(); ++k)
            poses.push_back({{"id", "ledge:" + std::to_string(k)}, {"position_m", vec(result.ledges[k].center_m)},
                             {"orientation_wxyz", Json{1, 0, 0, 0}}, {"component_id", 0}});
        Json bonds = Json::array();
        if (record_bonds && frame.phase == "lattice" && frame.bond_alive.size() == B) {
            for (std::size_t o = 0; o < B; ++o) {
                const auto [a, b] = result.bond_nodes[o];
                bonds.push_back({{"a_m", vec(frame.cell_positions[a])}, {"b_m", vec(frame.cell_positions[b])},
                                 {"live", frame.bond_alive[o] != 0},
                                 {"damage", static_cast<double>(frame.bond_damage[o])}});
            }
        }
        frames.push_back({{"time_s", frame.time_s}, {"phase", frame.phase}, {"poses", std::move(poses)},
                          {"bonds", std::move(bonds)}, {"fracture_count", frame.fracture_count}});
    }
    Json artifact{{"schema", "banjo.playback.v1"}, {"mode", "network"}, {"units", "SI"},
                  {"bodies", std::move(bodies)}, {"supports", std::move(supports)}, {"frames", std::move(frames)},
                  {"requested_steps", result.measurements.lattice_steps + result.measurements.rigid_steps},
                  {"completed_steps", result.measurements.lattice_steps + result.measurements.rigid_steps},
                  {"sampling", {{"stride_steps", 0}, {"maximum_frames", kept.size()}, {"interpolation", "none"},
                                {"captured_frames", result.frames.size()}, {"bond_lines", record_bonds}}},
                  {"physical_response_validated", false},
                  {"status", "complete"}, {"error", ""},
                  {"report", Json::parse(measurementsJson(result.measurements))}};
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
