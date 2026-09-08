// Breaking a piece that has already broken.
//
// 1. The trigger IS its derivation: the admission speed is
//    s_min * c * (z_o + z_f) / (2 z_o) to the last bits, for glass, oak and
//    iron against iron and against concrete; a fragment with no live bond is
//    refused; the energy bound refuses a chip.
// 2. The return path carries the state: broken bonds stay broken, damage and
//    permanent extension come back, and the reference frame it re-enters on is
//    a RIGID placement -- every bond's stretch and the fragment's stored
//    elastic energy are what they were at the handoff.
// 3. The round trip closes: rigid -> lattice -> rigid conserves mass, linear
//    momentum, angular momentum and kinetic energy to rounding.
// 4. A window with nothing external acting conserves momentum exactly.
// 5. The whole scene is bit identical on the serial and the parallel backend
//    through a re-entry.
// 6. A scene whose fragments are never struck again is unchanged by turning
//    re-fracture on, and a refused re-entry is visible rather than silent.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/Refracture.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

void require(bool result, const std::string &message) {
    if (!result) throw std::runtime_error(message);
}

CompiledBrittleMaterial referenceMaterial(MaterialPreset preset, double cell, unsigned horizon) {
    const auto material = makeReferenceMaterial(preset, 17);
    return withStrengthDerivedFailure(compileElasticLatticeReference(material, cell, horizon), material);
}

// A box tile as an ActiveMatter, positioned in the world so that a fragment of
// it has somewhere to be.
struct Tile {
    std::unique_ptr<LatticeAsset> asset;
    ActiveMatter matter;
    BoxLatticeLayout layout{};
    CompiledBrittleMaterial compiled{};
    MaterialDefinition material{};
    double cell{};
    Tile(MaterialPreset preset, Vec3 dims, double cell_size, unsigned horizon) : cell(cell_size) {
        material = makeReferenceMaterial(preset, 17);
        compiled = referenceMaterial(preset, cell_size, horizon);
        asset = std::make_unique<LatticeAsset>(
            generateBoxTileLattice({dims, cell_size, horizon}, compiled, &layout));
        matter.asset = asset.get();
        matter.material = compiled;
        for (const auto &node : asset->nodes) {
            const Vec3 position = node.local_position_m - asset->rest_center_of_mass_m;
            matter.nodes.push_back(
                {position, position, {}, node.represented_volume_m3 * compiled.density_kg_m3, {}});
            matter.reference_positions_world_m.push_back(position);
        }
        matter.bonds.resize(asset->bonds.size());
    }
};

// ---------------------------------------------------------------------------
// 1. The trigger is its derivation.
// ---------------------------------------------------------------------------
void theTriggerIsItsDerivation() {
    const double cell = 0.02;
    for (const MaterialPreset preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        Tile tile(preset, {6 * cell, 2 * cell, 4 * cell}, cell, 2);
        std::vector<std::uint32_t> all(tile.matter.nodes.size());
        for (std::size_t i = 0; i < all.size(); ++i) all[i] = static_cast<std::uint32_t>(i);
        const FragmentFractureLimits limits = fragmentFractureLimits(
            tile.matter, all, tile.material.density_kg_m3, tile.material.young_modulus_pa);
        require(limits.live_bonds == tile.asset->bonds.size(), "every bond of an intact tile is live");

        const double c = std::sqrt(tile.material.young_modulus_pa / tile.material.density_kg_m3);
        require(std::abs(limits.bar_wave_speed_m_s - c) <= 1e-12 * c, "bar wave speed is sqrt(E/rho)");
        require(std::abs(limits.acoustic_impedance_pa_s_m -
                         std::sqrt(tile.material.density_kg_m3 * tile.material.young_modulus_pa)) <=
                    1e-12 * limits.acoustic_impedance_pa_s_m,
                "impedance is sqrt(rho E)");
        // The smallest removal threshold over the three modes, from the same
        // compiled material the criterion reads.
        const double expected_stretch = std::min(
            tile.compiled.damage_end_stretch,
            std::min(tile.compiled.compression_damage_end_strain > 0.0
                         ? tile.compiled.compression_damage_end_strain
                         : std::numeric_limits<double>::infinity(),
                     tile.compiled.shear_damage_end_strain > 0.0
                         ? tile.compiled.shear_damage_end_strain
                         : std::numeric_limits<double>::infinity()));
        require(std::abs(limits.minimum_removal_stretch - expected_stretch) <= 1e-12 * expected_stretch,
                "the trigger reads the criterion's own removal threshold");

        for (const MaterialPreset partner : {MaterialPreset::Iron, MaterialPreset::Concrete}) {
            const MaterialDefinition other = makeReferenceMaterial(partner, 17);
            const double z_o = std::sqrt(other.density_kg_m3 * other.young_modulus_pa);
            const double z_f = limits.acoustic_impedance_pa_s_m;
            const double expected = limits.minimum_removal_stretch * c * (z_o + z_f) / (2.0 * z_o);
            const RefractureAdmission at = admitRefracture(limits, z_o, expected, 1.0e9);
            require(std::abs(at.threshold_speed_m_s - expected) <= 1e-12 * expected,
                    "v* = s_min c (z_o + z_f) / (2 z_o)");
            require(admitRefracture(limits, z_o, expected * (1.0 + 1e-9), 1.0e9).admitted(),
                    "just above the threshold speed the contact is admitted");
            const RefractureAdmission below =
                admitRefracture(limits, z_o, expected * (1.0 - 1e-9), 1.0e9);
            require(below.verdict == RefractureVerdict::BelowStressBound,
                    "just below the threshold speed the contact is rejected");
            // The estimated peak stretch is the acoustic bound itself.
            const RefractureAdmission twice = admitRefracture(limits, z_o, 2.0 * expected, 1.0e9);
            require(std::abs(twice.estimated_peak_stretch - 2.0 * limits.minimum_removal_stretch) <=
                        1e-12 * limits.minimum_removal_stretch,
                    "the peak stretch estimate is linear in the closing speed");
            std::cout << "  " << materialPresetName(preset) << " on " << materialPresetName(partner)
                      << ": v* = " << expected << " m/s (s_min " << limits.minimum_removal_stretch
                      << ", c " << c << ")\n";
        }
        // The energy bound: fast enough, but the pair cannot pay for one bond.
        const MaterialDefinition iron = makeReferenceMaterial(MaterialPreset::Iron, 17);
        const double z_iron = std::sqrt(iron.density_kg_m3 * iron.young_modulus_pa);
        const double fast = 10.0 * admitRefracture(limits, z_iron, 1.0, 1.0).threshold_speed_m_s;
        require(admitRefracture(limits, z_iron, fast, limits.minimum_removal_energy_j).admitted(),
                "one bond's worth of energy is enough to be asked");
        require(admitRefracture(limits, z_iron, fast, limits.minimum_removal_energy_j * (1.0 - 1e-9))
                        .verdict == RefractureVerdict::BelowEnergyBound,
                "a hair less than one bond's energy is refused");
    }
    // A single cell has no bond and can never break, at any speed.
    Tile tile(MaterialPreset::Glass, {6 * cell, 2 * cell, 4 * cell}, cell, 2);
    const std::uint32_t one[1] = {0U};
    const FragmentFractureLimits alone = fragmentFractureLimits(
        tile.matter, one, tile.material.density_kg_m3, tile.material.young_modulus_pa);
    require(alone.live_bonds == 0, "a one-cell fragment holds no bond");
    require(admitRefracture(alone, 1.0e9, 1.0e6, 1.0e9).verdict == RefractureVerdict::NoLiveBond,
            "a bondless fragment is refused at a million metres a second");
}

// A tile with some bonds removed, some damaged, and a deformed, rotated,
// translated pose: the state a re-entry has to carry.
struct BrokenTile {
    Tile tile;
    std::vector<std::uint32_t> nodes;
    std::vector<Vec3> offsets;
    std::vector<double> plastic_extension, plastic_strain;
    FragmentPose pose{};
    explicit BrokenTile(MaterialPreset preset, double cell)
        : tile(preset, {6 * cell, 2 * cell, 4 * cell}, cell, 2) {
        // A deformation that is not a rigid motion, so the strain is nonzero.
        for (std::size_t i = 0; i < tile.matter.nodes.size(); ++i) {
            const Vec3 rest = tile.matter.reference_positions_world_m[i];
            const Vec3 shift{0.004 * std::sin(9.0 * rest.z), 0.003 * rest.x * rest.x / (cell * cell) * cell,
                             0.002 * std::cos(7.0 * rest.x)};
            tile.matter.nodes[i].position_world_m = rest + shift;
            tile.matter.nodes[i].previous_position_world_m = rest + shift;
            tile.matter.nodes[i].velocity_m_s = {0.3, -1.1, 0.2};
        }
        for (std::size_t o = 0; o < tile.matter.bonds.size(); ++o) {
            tile.matter.bonds[o].damage = 0.25 + 0.5 * static_cast<double>(o % 7) / 7.0;
            tile.matter.bonds[o].peak_tensile_stretch = 1.0e-4 * static_cast<double>(o % 5);
            if (o % 11 == 0) {
                tile.matter.bonds[o].alive = false;
                tile.matter.bonds[o].damage = 1.0;
                tile.matter.bonds[o].failure_mode = BondFailureMode::Tension;
            }
        }
        plastic_extension.assign(tile.matter.bonds.size(), 0.0);
        plastic_strain.assign(tile.matter.bonds.size(), 0.0);
        for (std::size_t o = 0; o < plastic_extension.size(); ++o) {
            plastic_extension[o] = 1.0e-6 * static_cast<double>((o % 13)) - 3.0e-6;
            plastic_strain[o] = std::abs(plastic_extension[o]);
        }
        // The largest connected component of what is left.
        const auto components = findConnectedComponents(tile.matter);
        require(!components.empty(), "the broken tile has a component");
        nodes = components.front().node_indices;
        // Offsets in the fragment frame, as the handoff takes them.
        double mass = 0.0;
        Vec3 centre{};
        for (const std::uint32_t node : nodes) {
            mass += tile.matter.nodes[node].mass_kg;
            centre += tile.matter.nodes[node].mass_kg * tile.matter.nodes[node].position_world_m;
        }
        centre = centre / mass;
        offsets.assign(tile.matter.nodes.size(), Vec3{});
        for (const std::uint32_t node : nodes)
            offsets[node] = tile.matter.nodes[node].position_world_m - centre;
        // A pose that is nowhere near the rest pose: moved, turned and spinning.
        const double angle = 0.9;
        pose.center_of_mass_world_m = {1.7, 0.6, -2.3};
        pose.orientation_world = {std::cos(0.5 * angle), 0.0, std::sin(0.5 * angle) * 0.6,
                                  std::sin(0.5 * angle) * 0.8};
        pose.linear_velocity_m_s = {0.7, -3.1, 0.4};
        pose.angular_velocity_rad_s = {0.9, -1.4, 2.2};
    }
};

// ---------------------------------------------------------------------------
// 2. The return path carries the state, and re-enters on a rigid frame.
// ---------------------------------------------------------------------------
void theReturnPathCarriesTheState() {
    const double cell = 0.02;
    BrokenTile broken(MaterialPreset::Glass, cell);
    const FragmentLattice island = buildFragmentLattice(
        broken.tile.matter, broken.nodes, broken.offsets, broken.pose,
        broken.plastic_extension, broken.plastic_strain);
    require(island.parent_node.size() == broken.nodes.size(), "every cell came across");
    require(std::is_sorted(island.parent_node.begin(), island.parent_node.end()),
            "the cell order is the parent's, not the order a component search found them in");

    std::size_t dead = 0;
    for (std::size_t k = 0; k < island.matter.bonds.size(); ++k) {
        const std::uint32_t parent = island.parent_bond[k];
        require(island.matter.bonds[k].alive == broken.tile.matter.bonds[parent].alive,
                "a broken bond comes back broken");
        require(island.matter.bonds[k].damage == broken.tile.matter.bonds[parent].damage,
                "damage comes back exactly");
        require(island.matter.bonds[k].failure_mode == broken.tile.matter.bonds[parent].failure_mode,
                "the failure mode comes back");
        require(island.plastic_extension_m[k] == broken.plastic_extension[parent],
                "the permanent extension comes back exactly");
        require(island.plastic_strain_m[k] == broken.plastic_strain[parent],
                "the accumulated plastic flow comes back exactly");
        if (!island.matter.bonds[k].alive) ++dead;
    }
    require(dead > 0, "the fixture has broken bonds, so the check means something");

    // The reference frame is a RIGID placement of the original rest shape: every
    // bond's rest length is unchanged, and every bond's current stretch is what
    // it was in the parent.
    for (std::size_t k = 0; k < island.matter.bonds.size(); ++k) {
        const std::uint32_t parent_bond = island.parent_bond[k];
        const BondRest &here = island.asset->bonds[k];
        const BondRest &there = broken.tile.matter.asset->bonds[parent_bond];
        require(here.rest_length_m == there.rest_length_m, "rest lengths are untouched");
        require(here.compliance == there.compliance, "compliances are untouched");
        require(here.damage_end_stretch == there.damage_end_stretch, "thresholds are untouched");
        const Vec3 a_here = island.matter.nodes[here.node_a].position_world_m;
        const Vec3 b_here = island.matter.nodes[here.node_b].position_world_m;
        const Vec3 a_there = broken.tile.matter.nodes[there.node_a].position_world_m;
        const Vec3 b_there = broken.tile.matter.nodes[there.node_b].position_world_m;
        const double now = length(b_here - a_here), before = length(b_there - a_there);
        require(std::abs(now - before) <= 1e-12 * before, "the fragment re-enters at the shape it left in");
        // The rest edge is the original one, rigidly rotated.
        const Vec3 rest_here = island.matter.reference_positions_world_m[here.node_b] -
                               island.matter.reference_positions_world_m[here.node_a];
        const Vec3 rest_there = broken.tile.matter.reference_positions_world_m[there.node_b] -
                                broken.tile.matter.reference_positions_world_m[there.node_a];
        require(std::abs(length(rest_here) - length(rest_there)) <= 1e-12 * length(rest_there),
                "the reference configuration is placed rigidly");
    }

    // ... and therefore stores exactly the elastic energy it stored before.
    LatticeState state = buildLatticeState(island.matter, island.schedule, island.origin);
    for (std::size_t k = 0; k < state.bond_count; ++k) {
        const std::uint32_t local = island.schedule.bond_order[k];
        state.plastic_extension[k] = island.plastic_extension_m[local];
        state.plastic_strain[k] = island.plastic_strain_m[local];
    }
    double parent_energy = 0.0;
    for (const std::uint32_t node : broken.nodes) (void)node;
    for (std::size_t o = 0; o < broken.tile.matter.bonds.size(); ++o) {
        if (!broken.tile.matter.bonds[o].alive) continue;
        const BondRest &bond = broken.tile.matter.asset->bonds[o];
        const bool inside_a = std::binary_search(island.parent_node.begin(), island.parent_node.end(), bond.node_a);
        const bool inside_b = std::binary_search(island.parent_node.begin(), island.parent_node.end(), bond.node_b);
        if (!inside_a || !inside_b) continue;
        const Vec3 delta = broken.tile.matter.nodes[bond.node_b].position_world_m -
                           broken.tile.matter.nodes[bond.node_a].position_world_m;
        const double extension = length(delta) - bond.rest_length_m - broken.plastic_extension[o];
        parent_energy += 0.5 * extension * extension / bond.compliance;
    }
    const double island_energy = latticeStateElasticEnergy(state);
    require(std::abs(island_energy - parent_energy) <= 1e-9 * std::max(1.0, parent_energy),
            "re-entering stores neither more nor less strain energy than the piece already held");
    std::cout << "  carried " << island.matter.bonds.size() << " bonds (" << dead << " already broken), "
              << island.parent_node.size() << " cells, elastic energy " << island_energy << " J\n";

    // The displacement field is the deformation, not the pose: the frame the
    // island re-enters on absorbs the rigid rotation.
    double largest = 0.0;
    for (std::size_t i = 0; i < state.node_count; ++i)
        largest = std::max(largest, length(Vec3{state.u[3 * i], state.u[3 * i + 1], state.u[3 * i + 2]}));
    require(largest < 3.0 * cell, "the displacement field is the deformation, not the fragment's pose");
}

// ---------------------------------------------------------------------------
// 3. The round trip closes.
// ---------------------------------------------------------------------------
void theRoundTripConserves() {
    const double cell = 0.02;
    BrokenTile broken(MaterialPreset::Oak, cell);
    const FragmentLattice island = buildFragmentLattice(
        broken.tile.matter, broken.nodes, broken.offsets, broken.pose,
        broken.plastic_extension, broken.plastic_strain);
    const LatticeState state = buildLatticeState(island.matter, island.schedule, island.origin);

    std::vector<std::uint32_t> all(island.matter.nodes.size());
    for (std::size_t i = 0; i < all.size(); ++i) all[i] = static_cast<std::uint32_t>(i);
    const FragmentMassProperties props = calculateFragmentMassProperties(island.matter, all);
    const MechanicalLedger lattice =
        latticeLedger(state, island.origin, island.carried_spin_rad_s, cell);
    const MechanicalLedger rigid = rigidLedger(
        props.mass_kg, props.center_of_mass_world_m, props.linear_velocity_m_s,
        props.inertia_world_kg_m2, props.angular_velocity_rad_s, island.origin);

    const double scale = std::max(1.0, length(lattice.linear_momentum_kg_m_s));
    require(std::abs(lattice.mass_kg - rigid.mass_kg) <= 1e-12 * rigid.mass_kg, "mass is conserved");
    require(length(lattice.linear_momentum_kg_m_s - rigid.linear_momentum_kg_m_s) <= 1e-12 * scale,
            "linear momentum is conserved across the conversion");
    const double angular_scale = std::max(1.0e-6, length(lattice.angular_momentum_kg_m2_s));
    require(length(lattice.angular_momentum_kg_m2_s - rigid.angular_momentum_kg_m2_s) <= 1e-9 * angular_scale,
            "angular momentum, cell spin included, is conserved across the conversion");
    require(std::abs(lattice.kinetic_energy_j - rigid.kinetic_energy_j) <=
                1e-9 * std::max(1.0e-9, rigid.kinetic_energy_j),
            "kinetic energy is conserved across the conversion");
    require(std::abs(props.coarsening_kinetic_loss_j) <= 1e-9 * std::max(1.0e-9, props.source_kinetic_energy_j),
            "a rigid velocity field loses nothing to the rigid representation");
    std::cout << "  entry ledger: |dp| " << length(lattice.linear_momentum_kg_m_s - rigid.linear_momentum_kg_m_s)
              << " kg m/s, |dL| " << length(lattice.angular_momentum_kg_m2_s - rigid.angular_momentum_kg_m2_s)
              << " kg m2/s, dE " << (lattice.kinetic_energy_j - rigid.kinetic_energy_j) << " J\n";

    // ... and on the way out, the pieces the lattice becomes carry the same
    // momentum and the same angular momentum, with the non-rigid part of the
    // motion named as the coarsening loss rather than dropped.
    const auto components = findConnectedComponents(island.matter);
    const FragmentBuildResult rebuilt = buildFragmentRepresentations(island.matter, components, {
        .first_body_id = 5000,
        .maximum_rigid_fragments = std::max<std::size_t>(1, components.size()),
        .minimum_nodes_per_rigid_fragment = 1,
        .maximum_collision_points = 192,
    });
    MechanicalLedger out{};
    double coarsening = 0.0;
    for (const RigidFragmentDescription &fragment : rebuilt.rigid_fragments) {
        const FragmentMassProperties &p = fragment.mass_properties;
        const MechanicalLedger piece = rigidLedger(p.mass_kg, p.center_of_mass_world_m, p.linear_velocity_m_s,
                                                   p.inertia_world_kg_m2, p.angular_velocity_rad_s, island.origin);
        out.mass_kg += piece.mass_kg;
        out.linear_momentum_kg_m_s += piece.linear_momentum_kg_m_s;
        out.angular_momentum_kg_m2_s += piece.angular_momentum_kg_m2_s;
        out.kinetic_energy_j += piece.kinetic_energy_j;
        coarsening += p.coarsening_kinetic_loss_j;
    }
    require(std::abs(out.mass_kg - lattice.mass_kg) <= 1e-12 * lattice.mass_kg, "no mass is lost on the way out");
    require(length(out.linear_momentum_kg_m_s - lattice.linear_momentum_kg_m_s) <= 1e-12 * scale,
            "the pieces carry the lattice's momentum");
    require(length(out.angular_momentum_kg_m2_s - lattice.angular_momentum_kg_m2_s) <= 1e-9 * angular_scale,
            "the pieces carry the lattice's angular momentum");
    require(std::abs(lattice.kinetic_energy_j - out.kinetic_energy_j - coarsening) <=
                1e-9 * std::max(1.0e-9, lattice.kinetic_energy_j),
            "the kinetic energy the pieces do not carry is exactly the coarsening loss");
}

// ---------------------------------------------------------------------------
// 4. A window with nothing external acting conserves momentum.
// ---------------------------------------------------------------------------
void aFreeWindowConservesMomentum() {
    const double cell = 0.02;
    BrokenTile broken(MaterialPreset::Glass, cell);
    // Free flight: no gravity, no support, one striker driven into the piece.
    FragmentPose pose = broken.pose;
    pose.linear_velocity_m_s = {};
    pose.angular_velocity_rad_s = {};
    const FragmentLattice island = buildFragmentLattice(
        broken.tile.matter, broken.nodes, broken.offsets, pose,
        broken.plastic_extension, broken.plastic_strain);
    LatticeState state = buildLatticeState(island.matter, island.schedule, island.origin);
    for (std::size_t k = 0; k < state.bond_count; ++k) {
        const std::uint32_t local = island.schedule.bond_order[k];
        state.plastic_extension[k] = island.plastic_extension_m[local];
        state.plastic_strain[k] = island.plastic_strain_m[local];
    }

    // The tile's top in the island frame, so the striker starts just above it.
    double top = -std::numeric_limits<double>::infinity();
    for (std::size_t i = 0; i < state.node_count; ++i)
        top = std::max(top, state.x0[3 * i + 1] + state.u[3 * i + 1]);

    const MaterialDefinition iron = makeReferenceMaterial(MaterialPreset::Iron, 17);
    SphereState<double> sphere{};
    sphere.radius = 0.03;
    sphere.mass = 4.0 / 3.0 * 3.14159265358979323846 * std::pow(sphere.radius, 3.0) * iron.density_kg_m3;
    sphere.inertia = 0.4 * sphere.mass * sphere.radius * sphere.radius;
    sphere.center = {0.0, top + sphere.radius + 0.5 * cell, 0.0};
    sphere.velocity = {0.0, -30.0, 0.0};

    StepSettings<double> settings{};
    settings.dt = 2.0e-7;
    settings.gravity = {0.0, 0.0, 0.0};
    settings.constraint_iterations = 1;
    settings.damping_fraction = 0.0;
    settings.sphere_enabled = 1;
    settings.direct_arithmetic = 1;
    settings.contact.static_friction = 0.4;
    settings.contact.dynamic_friction = 0.3;
    settings.contact.restitution = 0.1;
    settings.contact.restitution_speed_threshold = 0.5;
    settings.contact.node_contact_radius = 0.5 * cell;
    settings.contact.contact_margin = 1.0e-5;
    settings.contact.prefilter_slack = 0.05 * sphere.radius;
    settings.node_contact.mode = kNodeContactOn;
    settings.node_contact.radius = 0.5 * cell;
    settings.node_contact.skin = 0.25 * cell;
    settings.node_contact.margin = 1.0e-5;
    settings.node_contact.restitution = 0.1;
    settings.node_contact.restitution_speed_threshold = 0.5;
    settings.node_contact.static_friction = 0.4;
    settings.node_contact.dynamic_friction = 0.3;
    settings.node_contact.bucket_mask = latticeContactBucketMask(state.node_count);
    settings.support.plane_count = 0;

    const MechanicalLedger before = latticeLedger(state, island.origin, island.carried_spin_rad_s, cell);
    const Vec3 momentum_before = before.linear_momentum_kg_m_s + sphere.mass * Vec3{sphere.velocity.x, sphere.velocity.y, sphere.velocity.z};

    auto backend = makeCpuLatticeBackend(island.schedule, Precision::Double);
    backend->upload(state, settings, sphere);
    RunControl control{};
    control.max_steps = 4000;
    (void)backend->run(control);
    backend->download(state, sphere);
    const RunStatus &status = backend->status();
    require(status.broken_bonds > 0, "the window broke nothing, so it proves nothing");

    const MechanicalLedger after = latticeLedger(state, island.origin, island.carried_spin_rad_s, cell);
    const Vec3 momentum_after = after.linear_momentum_kg_m_s + sphere.mass * Vec3{sphere.velocity.x, sphere.velocity.y, sphere.velocity.z};
    const double drift = length(momentum_after - momentum_before);
    const double scale = length(momentum_before);
    require(drift <= 1e-11 * std::max(1.0, scale),
            "with no support and no gravity the window conserves momentum to rounding");
    std::cout << "  free window: " << status.broken_bonds << " bonds broken, |dp| = " << drift
              << " kg m/s on " << scale << " kg m/s\n";
}

// ---------------------------------------------------------------------------
// 5 and 6. The scene: parity, unchanged first strike, visible refusals.
// ---------------------------------------------------------------------------
TileImpactRequest sceneRequest() {
    TileImpactRequest request;
    request.tile_material = MaterialPreset::Glass;
    request.tile_dimensions_m = {0.24, 0.04, 0.16};
    request.cell_size_m = 0.02;
    request.ball_radius_m = 0.04;
    request.ball_speed_m_s = 8.0;
    request.layout = SceneLayout::Bridge;
    request.backend = BackendKind::Cpu;
    request.precision = Precision::Double;
    request.settle_limit_s = 0.6;
    request.rigid_frames = 12;
    return request;
}

// Every number a run reports that a re-entry could touch, plus the final pose
// of every cell: what "bit for bit" is compared on.
std::vector<double> sceneFingerprint(const TileImpactResult &result) {
    const TileImpactMeasurements &m = result.measurements;
    std::vector<double> out{
        static_cast<double>(m.broken_bonds), m.removed_energy_j, m.first_failure_s, m.last_failure_s,
        static_cast<double>(m.components), static_cast<double>(m.rigid_fragments),
        static_cast<double>(m.largest_piece_cells), m.largest_piece_mass_kg,
        static_cast<double>(m.lattice_steps), m.lattice_simulated_s, m.elastic_energy_j, m.lattice_kinetic_j,
        static_cast<double>(m.rigid_steps), m.rigid_simulated_s, m.ball_speed_at_end_m_s,
        m.ball_height_at_end_m, static_cast<double>(m.came_to_rest), m.rest_time_s,
        m.contact.dissipated_kinetic_energy_j, m.node_contact.dissipated_kinetic_energy_j,
        static_cast<double>(m.contact.impulse_contacts), static_cast<double>(m.node_contact.contacts),
        static_cast<double>(result.frames.size()),
    };
    for (const RecordedFrame &frame : result.frames) {
        out.push_back(frame.time_s);
        for (const Vec3 &p : frame.cell_positions) { out.push_back(p.x); out.push_back(p.y); out.push_back(p.z); }
        out.push_back(frame.ball_center.x);
        out.push_back(frame.ball_center.y);
        out.push_back(frame.ball_center.z);
    }
    return out;
}

void turningItOnChangesNothingItDoesNotTouch() {
    TileImpactRequest off = sceneRequest();
    TileImpactRequest on = sceneRequest();
    on.refracture = true;
    const TileImpactResult a = runTileImpact(off);
    const TileImpactResult b = runTileImpact(on);
    require(a.measurements.broken_bonds > 0, "the scene does not fracture, so it proves nothing");
    require(b.measurements.refracture.enabled, "the second run had re-fracture on");
    require(b.measurements.refracture.admitted == 0,
            "this scene admits no re-entry, which is what makes it the control");
    require(b.measurements.refracture.contacts_tested > 0,
            "the trigger never ran, so the control is vacuous");
    const auto fa = sceneFingerprint(a), fb = sceneFingerprint(b);
    require(fa.size() == fb.size(), "the two runs recorded the same frames");
    for (std::size_t i = 0; i < fa.size(); ++i)
        require(fa[i] == fb[i], "a scene that admits no re-entry is bit for bit what it was");
    std::cout << "  control: " << a.measurements.broken_bonds << " bonds, "
              << a.measurements.components << " pieces, " << fa.size()
              << " compared values identical; " << b.measurements.refracture.contacts_tested
              << " contacts tested, none admitted\n";
}

void serialAndParallelAgreeThroughAReEntry() {
    TileImpactRequest request = sceneRequest();
    request.refracture = true;
    request.second_ball_radius_m = 0.04;
    request.second_ball_speed_m_s = 14.0;
    request.second_ball_offset_x_m = 0.08;
    request.second_strike_wait_s = 0.35;
    request.settle_limit_s = 0.5;
    TileImpactRequest parallel = request;
    parallel.backend = BackendKind::CpuParallel;
    parallel.cpu_threads = 4;
    const TileImpactResult serial = runTileImpact(request);
    const TileImpactResult threaded = runTileImpact(parallel);
    require(serial.measurements.refracture.admitted > 0, "no re-entry happened, so parity proves nothing");
    require(serial.measurements.refracture.broken_bonds > 0, "the re-entry broke nothing");
    const auto fs = sceneFingerprint(serial), ft = sceneFingerprint(threaded);
    require(fs.size() == ft.size(), "the two backends recorded the same frames");
    for (std::size_t i = 0; i < fs.size(); ++i)
        require(fs[i] == ft[i], "the serial and parallel backends disagree through a re-entry");
    require(serial.measurements.refracture.broken_bonds == threaded.measurements.refracture.broken_bonds,
            "the two backends broke different bonds in the re-entry");
    std::cout << "  parity: " << serial.measurements.refracture.admitted << " re-entries, "
              << serial.measurements.refracture.broken_bonds << " bonds broken, " << fs.size()
              << " values identical on serial and parallel\n";
}

void aRefusedReEntryIsVisible() {
    TileImpactRequest request = sceneRequest();
    request.refracture = true;
    request.second_ball_radius_m = 0.04;
    request.second_ball_speed_m_s = 14.0;
    request.second_ball_offset_x_m = 0.08;
    request.second_strike_wait_s = 0.35;
    request.settle_limit_s = 0.5;
    TileImpactRequest broke = request;
    broke.refracture_max_events = 0;
    const TileImpactResult allowed = runTileImpact(request);
    const TileImpactResult refused = runTileImpact(broke);
    require(allowed.measurements.refracture.broken_bonds > 0, "the control re-entry broke nothing");
    require(refused.measurements.refracture.admitted > 0, "the budget run admitted nothing to refuse");
    require(refused.measurements.refracture.refused_budget_events > 0,
            "a refusal for want of budget is counted, not silent");
    require(refused.measurements.refracture.broken_bonds == 0, "a refused re-entry broke bonds anyway");
    require(refused.measurements.refracture.events.empty(), "a refused re-entry left an event behind");
    std::cout << "  budget: " << refused.measurements.refracture.admitted << " admitted, "
              << refused.measurements.refracture.refused_budget_events
              << " refused for want of budget, 0 bonds broken\n";
}

} // namespace

int main() {
    try {
        theTriggerIsItsDerivation();
        std::cout << "[PASS] the trigger is its derivation, for glass, oak and iron\n";
        theReturnPathCarriesTheState();
        std::cout << "[PASS] a fragment comes back with its damage, its broken bonds and its permanent extension\n";
        theRoundTripConserves();
        std::cout << "[PASS] rigid -> lattice -> rigid conserves mass, momentum, angular momentum and energy\n";
        aFreeWindowConservesMomentum();
        std::cout << "[PASS] a window with nothing external acting conserves momentum\n";
        turningItOnChangesNothingItDoesNotTouch();
        std::cout << "[PASS] a scene that admits no re-entry is unchanged, bit for bit\n";
        serialAndParallelAgreeThroughAReEntry();
        std::cout << "[PASS] the serial and parallel backends agree bit for bit through a re-entry\n";
        aRefusedReEntryIsVisible();
        std::cout << "[PASS] a refused re-entry is counted rather than silent\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
