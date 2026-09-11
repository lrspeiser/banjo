#include "fastlattice/Refracture.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <unordered_map>

namespace banjo::fastlattice {
namespace {

// The stretch at which one damage mode removes a bond, following
// LatticePhysics.hpp damageProgress exactly: a mode whose start is not finite
// never damages anything; a mode whose end is not finite (or not above the
// start) removes the bond as soon as the sample passes the start.
double modeRemovalStretch(double start, double end) {
    if (!std::isfinite(start)) return std::numeric_limits<double>::infinity();
    if (!std::isfinite(end) || end <= start) return start;
    return end;
}

// The rotation that best carries the fragment's REST shape onto the shape it
// was frozen in at the handoff. It is used only to choose the reference frame
// the lattice re-enters in, and a rigid rotation of the reference configuration
// changes no rest length, no threshold and no strain -- the criterion is frame
// indifferent. What it buys is conditioning: without it the displacement field
// carries the whole rotation a piece accumulated while it was breaking (90 mm
// on a 250 mm plate, measured), and the float path forms a bond vector as an
// exact rest edge plus a displacement difference.
Mat3 rotationMatrix(const Quat &q) {
    Mat3 out{};
    for (int c = 0; c < 3; ++c) {
        Vec3 axis{};
        (&axis.x)[c] = 1.0;
        const Vec3 rotated = q.rotate(axis);
        out.m[0][c] = rotated.x;
        out.m[1][c] = rotated.y;
        out.m[2][c] = rotated.z;
    }
    return out;
}

Quat multiplyQuat(const Quat &a, const Quat &b) {
    return {a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
            a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
            a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
            a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w};
}

Vec3 column(const Mat3 &a, int c) { return {a.m[0][c], a.m[1][c], a.m[2][c]}; }

// The rotation closest to `a`, by the quaternion iteration of Muller, Bender,
// Chentanez and Macklin, "A robust method to extract the rotational part of
// deformations" (MIG 2016). It is used instead of a polar decomposition because
// the correlation matrix here is routinely RANK DEFICIENT -- a plate one cell
// thick has every rest position in one plane -- and the polar factor of a
// singular matrix is not defined, where this iteration still returns the
// optimal rotation.
Mat3 closestRotation(const Mat3 &a) {
    Quat q{1.0, 0.0, 0.0, 0.0};
    for (int iteration = 0; iteration < 64; ++iteration) {
        const Mat3 r = rotationMatrix(q);
        Vec3 omega{};
        double denominator = 1.0e-12;
        for (int c = 0; c < 3; ++c) {
            omega += cross(column(r, c), column(a, c));
            denominator += std::abs(dot(column(r, c), column(a, c)));
        }
        omega = omega / denominator;
        const double angle = length(omega);
        if (!(angle > 1.0e-14)) break;
        const Vec3 axis = omega / angle;
        const double half = 0.5 * angle;
        const double sine = std::sin(half);
        q = multiplyQuat({std::cos(half), axis.x * sine, axis.y * sine, axis.z * sine}, q);
        const double norm = std::sqrt(q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z);
        if (!(norm > 0.0)) return rotationMatrix({1.0, 0.0, 0.0, 0.0});
        q = {q.w / norm, q.x / norm, q.y / norm, q.z / norm};
    }
    return rotationMatrix(q);
}

double bondRemovalStretch(const BondRest &bond) {
    double smallest = modeRemovalStretch(bond.damage_start_stretch, bond.damage_end_stretch);
    smallest = std::min(smallest, modeRemovalStretch(bond.compression_damage_start_strain,
                                                     bond.compression_damage_end_strain));
    smallest = std::min(smallest, modeRemovalStretch(bond.shear_damage_start_strain,
                                                     bond.shear_damage_end_strain));
    return smallest;
}

} // namespace

double acousticImpedance(double density_kg_m3, double young_modulus_pa) {
    if (!(density_kg_m3 > 0.0) || !(young_modulus_pa > 0.0)) return 0.0;
    return std::sqrt(density_kg_m3 * young_modulus_pa);
}

RefractureAdmission admitRefracture(
    const FragmentFractureLimits &fragment, double other_impedance_pa_s_m,
    double closing_speed_m_s, double available_normal_energy_j) {
    RefractureAdmission out{};
    out.available_energy_j = available_normal_energy_j;
    if (fragment.live_bonds == 0 || !(fragment.minimum_removal_stretch > 0.0) ||
        !std::isfinite(fragment.minimum_removal_stretch) || !(fragment.bar_wave_speed_m_s > 0.0)) {
        out.verdict = RefractureVerdict::NoLiveBond;
        out.threshold_speed_m_s = std::numeric_limits<double>::infinity();
        return out;
    }
    const double z_f = fragment.acoustic_impedance_pa_s_m;
    const double z_o = other_impedance_pa_s_m > 0.0 ? other_impedance_pa_s_m : z_f;
    // sigma / E_f: the strain the transmitted pulse carries, doubled for the
    // free-surface reflection (see the derivation in the header).
    const double transmission = z_o / (z_o + z_f);
    out.estimated_peak_stretch =
        2.0 * closing_speed_m_s * transmission / fragment.bar_wave_speed_m_s;
    out.threshold_speed_m_s =
        fragment.minimum_removal_stretch * fragment.bar_wave_speed_m_s / (2.0 * transmission);
    // The same bound against the yield stretch. Everything in the derivation is
    // about how much strain the transmitted pulse carries; which strain you
    // then compare it to is the only difference between "can this break" and
    // "can this take a permanent set".
    if (fragment.yield_stretch > 0.0) {
        out.yield_speed_m_s =
            fragment.yield_stretch * fragment.bar_wave_speed_m_s / (2.0 * transmission);
        out.yields = out.estimated_peak_stretch >= fragment.yield_stretch;
    }
    if (!(out.estimated_peak_stretch >= fragment.minimum_removal_stretch)) {
        out.verdict = RefractureVerdict::BelowStressBound;
        return out;
    }
    if (!(available_normal_energy_j >= fragment.minimum_removal_energy_j)) {
        out.verdict = RefractureVerdict::BelowEnergyBound;
        return out;
    }
    out.verdict = RefractureVerdict::Admitted;
    return out;
}

FragmentFractureLimits fragmentFractureLimits(
    const ActiveMatter &matter, std::span<const std::uint32_t> node_indices,
    double density_kg_m3, double young_modulus_pa, double yield_strength_pa) {
    FragmentFractureLimits limits{};
    limits.cells = node_indices.size();
    // sigma_y / E, the same number the plastic law uses for its yield
    // extension. Left at zero for anything with no yield strength declared,
    // which is every brittle material in the catalogue.
    limits.yield_stretch =
        std::isfinite(yield_strength_pa) && yield_strength_pa > 0.0 && young_modulus_pa > 0.0
            ? yield_strength_pa / young_modulus_pa
            : 0.0;
    limits.bar_wave_speed_m_s =
        density_kg_m3 > 0.0 && young_modulus_pa > 0.0 ? std::sqrt(young_modulus_pa / density_kg_m3) : 0.0;
    limits.acoustic_impedance_pa_s_m = acousticImpedance(density_kg_m3, young_modulus_pa);
    limits.minimum_removal_stretch = std::numeric_limits<double>::infinity();
    limits.minimum_removal_energy_j = std::numeric_limits<double>::infinity();
    if (matter.asset == nullptr) return limits;

    std::vector<std::uint8_t> inside(matter.nodes.size(), 0U);
    for (const std::uint32_t node : node_indices)
        if (node < inside.size()) inside[node] = 1U;
    for (std::size_t o = 0; o < matter.asset->bonds.size(); ++o) {
        if (!matter.bonds[o].alive) continue;
        const BondRest &bond = matter.asset->bonds[o];
        if (!inside[bond.node_a] || !inside[bond.node_b]) continue;
        ++limits.live_bonds;
        const double stretch = bondRemovalStretch(bond);
        if (!std::isfinite(stretch) || !(stretch > 0.0)) continue;
        limits.minimum_removal_stretch = std::min(limits.minimum_removal_stretch, stretch);
        if (bond.compliance > 0.0) {
            const double extension = stretch * bond.rest_length_m;
            limits.minimum_removal_energy_j = std::min(
                limits.minimum_removal_energy_j, 0.5 * extension * extension / bond.compliance);
        }
    }
    if (!std::isfinite(limits.minimum_removal_energy_j)) limits.minimum_removal_energy_j = 0.0;
    return limits;
}

FragmentLattice buildFragmentLattice(
    const ActiveMatter &parent, std::span<const std::uint32_t> node_indices,
    std::span<const Vec3> parent_cell_offset_m, const FragmentPose &pose,
    std::span<const double> parent_plastic_extension_m,
    std::span<const double> parent_plastic_strain_m) {
    if (parent.asset == nullptr) throw std::invalid_argument("a fragment lattice needs a parent asset");
    if (node_indices.empty()) throw std::invalid_argument("a fragment lattice needs at least one cell");

    FragmentLattice out;
    out.parent_node.assign(node_indices.begin(), node_indices.end());
    // Sorted, so the sub-lattice and everything derived from it -- the schedule,
    // the colouring, the sweep order -- depend on the fragment's membership and
    // not on the order a component search or a thread happened to produce.
    std::sort(out.parent_node.begin(), out.parent_node.end());
    out.parent_node.erase(std::unique(out.parent_node.begin(), out.parent_node.end()), out.parent_node.end());

    const std::size_t n = out.parent_node.size();
    std::vector<std::uint32_t> local_of_parent(parent.nodes.size(), std::numeric_limits<std::uint32_t>::max());
    for (std::size_t i = 0; i < n; ++i) local_of_parent[out.parent_node[i]] = static_cast<std::uint32_t>(i);

    out.asset = std::make_unique<LatticeAsset>();
    LatticeAsset &asset = *out.asset;
    asset.recipe = parent.asset->recipe;
    asset.nodes.reserve(n);
    for (const std::uint32_t p : out.parent_node) asset.nodes.push_back(parent.asset->nodes[p]);

    for (std::size_t o = 0; o < parent.asset->bonds.size(); ++o) {
        const BondRest &bond = parent.asset->bonds[o];
        const std::uint32_t a = local_of_parent[bond.node_a], b = local_of_parent[bond.node_b];
        if (a == std::numeric_limits<std::uint32_t>::max() || b == std::numeric_limits<std::uint32_t>::max())
            continue;
        BondRest copy = bond;
        copy.node_a = a;
        copy.node_b = b;
        asset.bonds.push_back(copy);
        out.parent_bond.push_back(static_cast<std::uint32_t>(o));
    }

    // CSR adjacency in ascending bond order, as the generators build it.
    asset.adjacency_offsets.assign(n + 1U, 0U);
    for (const BondRest &bond : asset.bonds) {
        ++asset.adjacency_offsets[bond.node_a + 1U];
        ++asset.adjacency_offsets[bond.node_b + 1U];
    }
    for (std::size_t i = 0; i < n; ++i) asset.adjacency_offsets[i + 1U] += asset.adjacency_offsets[i];
    asset.adjacent_bond_indices.assign(asset.adjacency_offsets.back(), 0U);
    {
        std::vector<std::uint32_t> cursor(asset.adjacency_offsets.begin(), asset.adjacency_offsets.end());
        for (std::size_t k = 0; k < asset.bonds.size(); ++k) {
            asset.adjacent_bond_indices[cursor[asset.bonds[k].node_a]++] = static_cast<std::uint32_t>(k);
            asset.adjacent_bond_indices[cursor[asset.bonds[k].node_b]++] = static_cast<std::uint32_t>(k);
        }
    }

    // Reference configuration: the ORIGINAL rest shape of these cells, rigidly
    // placed on the fragment's current pose. Rigid, so every rest length, rest
    // edge weight and threshold is untouched and the strain measure -- which is
    // frame indifferent by construction -- reads exactly what it read before.
    Vec3 reference_centroid{};
    double total_mass = 0.0;
    for (const std::uint32_t p : out.parent_node) {
        total_mass += parent.nodes[p].mass_kg;
        reference_centroid += parent.nodes[p].mass_kg * parent.reference_positions_world_m[p];
    }
    if (!(total_mass > 0.0)) throw std::runtime_error("a fragment lattice has no mass");
    reference_centroid = reference_centroid / total_mass;

    // The rest shape's own rotation inside the frozen fragment.
    Mat3 correlation{};
    for (const std::uint32_t p : out.parent_node) {
        const Vec3 rest = parent.reference_positions_world_m[p] - reference_centroid;
        const Vec3 frozen = parent_cell_offset_m[p];
        const double mass = parent.nodes[p].mass_kg;
        correlation.m[0][0] += mass * frozen.x * rest.x;
        correlation.m[0][1] += mass * frozen.x * rest.y;
        correlation.m[0][2] += mass * frozen.x * rest.z;
        correlation.m[1][0] += mass * frozen.y * rest.x;
        correlation.m[1][1] += mass * frozen.y * rest.y;
        correlation.m[1][2] += mass * frozen.y * rest.z;
        correlation.m[2][0] += mass * frozen.z * rest.x;
        correlation.m[2][1] += mass * frozen.z * rest.y;
        correlation.m[2][2] += mass * frozen.z * rest.z;
    }
    const Mat3 rest_rotation = closestRotation(correlation);

    out.origin = pose.center_of_mass_world_m;
    out.carried_spin_rad_s = pose.angular_velocity_rad_s;
    ActiveMatter &matter = out.matter;
    matter.body_id = parent.body_id;
    matter.asset = &asset;
    matter.material = parent.material;
    matter.nodes.resize(n);
    matter.reference_positions_world_m.resize(n);
    matter.bonds.resize(asset.bonds.size());
    for (std::size_t i = 0; i < n; ++i) {
        const std::uint32_t p = out.parent_node[i];
        const Vec3 position =
            pose.center_of_mass_world_m + pose.orientation_world.rotate(parent_cell_offset_m[p]);
        const Vec3 arm = position - pose.center_of_mass_world_m;
        matter.reference_positions_world_m[i] =
            pose.center_of_mass_world_m +
            pose.orientation_world.rotate(
                rest_rotation * (parent.reference_positions_world_m[p] - reference_centroid));
        ActiveNodeState &node = matter.nodes[i];
        node.position_world_m = position;
        node.previous_position_world_m = position;
        node.velocity_m_s = pose.linear_velocity_m_s + cross(pose.angular_velocity_rad_s, arm);
        node.mass_kg = parent.nodes[p].mass_kg;
        node.spin_angular_velocity_rad_s = pose.angular_velocity_rad_s;
    }
    asset.total_mass_kg = total_mass;
    asset.represented_volume_m3 = parent.asset->represented_volume_m3;
    asset.rest_center_of_mass_m = reference_centroid;

    out.plastic_extension_m.assign(asset.bonds.size(), 0.0);
    out.plastic_strain_m.assign(asset.bonds.size(), 0.0);
    for (std::size_t k = 0; k < asset.bonds.size(); ++k) {
        const std::uint32_t o = out.parent_bond[k];
        matter.bonds[k] = parent.bonds[o];
        matter.bonds[k].accumulated_lambda = 0.0;
        if (o < parent_plastic_extension_m.size()) out.plastic_extension_m[k] = parent_plastic_extension_m[o];
        if (o < parent_plastic_strain_m.size()) out.plastic_strain_m[k] = parent_plastic_strain_m[o];
    }

    out.schedule = buildLatticeSchedule(asset);
    return out;
}

MechanicalLedger latticeLedger(
    const LatticeState &state, const Vec3 &about_m, const Vec3 &cell_spin_rad_s, double cell_size_m) {
    MechanicalLedger ledger{};
    ledger.about_m = about_m;
    const double spin_speed_squared = lengthSquared(cell_spin_rad_s);
    for (std::size_t i = 0; i < state.node_count; ++i) {
        const double mass = state.mass[i];
        const Vec3 position = state.origin + Vec3{state.x0[3 * i], state.x0[3 * i + 1], state.x0[3 * i + 2]} +
                              Vec3{state.u[3 * i], state.u[3 * i + 1], state.u[3 * i + 2]};
        const Vec3 velocity{state.v[3 * i], state.v[3 * i + 1], state.v[3 * i + 2]};
        const double spin_inertia = mass * cell_size_m * cell_size_m / 6.0;
        ledger.mass_kg += mass;
        ledger.linear_momentum_kg_m_s += mass * velocity;
        ledger.angular_momentum_kg_m2_s +=
            cross(position - about_m, mass * velocity) + spin_inertia * cell_spin_rad_s;
        ledger.kinetic_energy_j +=
            0.5 * mass * lengthSquared(velocity) + 0.5 * spin_inertia * spin_speed_squared;
    }
    return ledger;
}

MechanicalLedger rigidLedger(
    double mass_kg, const Vec3 &center_of_mass_world_m, const Vec3 &linear_velocity_m_s,
    const Mat3 &inertia_world_kg_m2, const Vec3 &angular_velocity_rad_s, const Vec3 &about_m) {
    MechanicalLedger ledger{};
    ledger.about_m = about_m;
    ledger.mass_kg = mass_kg;
    ledger.linear_momentum_kg_m_s = mass_kg * linear_velocity_m_s;
    const Vec3 spin_momentum = inertia_world_kg_m2 * angular_velocity_rad_s;
    ledger.angular_momentum_kg_m2_s =
        cross(center_of_mass_world_m - about_m, mass_kg * linear_velocity_m_s) + spin_momentum;
    ledger.kinetic_energy_j = 0.5 * mass_kg * lengthSquared(linear_velocity_m_s) +
                              0.5 * dot(angular_velocity_rad_s, spin_momentum);
    return ledger;
}

} // namespace banjo::fastlattice
