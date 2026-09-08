#include "fastlattice/FastLattice.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace banjo::fastlattice {

const char *precisionName(Precision precision) {
    return precision == Precision::Float ? "float" : "double";
}

const char *latticePhaseName(unsigned phase) {
    static const char *const names[kPhaseCount] = {
        "capture", "start_sample_nodes", "start_sample_bonds", "kick_classify", "contact_pass_1",
        "sweep_interior", "sweep_boundary", "support_project", "velocity_update", "damping",
        "contact_pass_2", "end_sample_nodes", "end_sample_bonds", "sphere_exit",
        "node_contact_broad", "node_contact_narrow"};
    return phase < kPhaseCount ? names[phase] : "unknown";
}

LatticeState buildLatticeState(
    const ActiveMatter &matter, const LatticeSchedule &schedule, const Vec3 &origin) {
    if (matter.asset == nullptr) throw std::invalid_argument("lattice state needs an asset");
    const std::size_t node_count = matter.nodes.size();
    const std::size_t bond_count = matter.bonds.size();
    if (matter.asset->nodes.size() != node_count || matter.asset->bonds.size() != bond_count ||
        matter.reference_positions_world_m.size() != node_count)
        throw std::invalid_argument("lattice state needs matching nodes, bonds and reference positions");
    if (schedule.bond_order.size() != bond_count || schedule.node_block_begin.back() != node_count)
        throw std::invalid_argument("lattice schedule does not match the lattice");

    LatticeState s;
    s.origin = origin;
    s.node_count = static_cast<std::uint32_t>(node_count);
    s.bond_count = static_cast<std::uint32_t>(bond_count);
    s.x0.resize(3U * node_count);
    s.u.resize(3U * node_count);
    s.u_prev.resize(3U * node_count);
    s.v.resize(3U * node_count);
    s.inv_mass.resize(node_count);
    s.mass.resize(node_count);
    for (std::size_t i = 0; i < node_count; ++i) {
        const ActiveNodeState &node = matter.nodes[i];
        const Vec3 reference = matter.reference_positions_world_m[i];
        const Vec3 x0 = reference - origin;
        const Vec3 u = node.position_world_m - reference;
        s.x0[3 * i] = x0.x; s.x0[3 * i + 1] = x0.y; s.x0[3 * i + 2] = x0.z;
        s.u[3 * i] = u.x; s.u[3 * i + 1] = u.y; s.u[3 * i + 2] = u.z;
        s.u_prev[3 * i] = u.x; s.u_prev[3 * i + 1] = u.y; s.u_prev[3 * i + 2] = u.z;
        s.v[3 * i] = node.velocity_m_s.x; s.v[3 * i + 1] = node.velocity_m_s.y; s.v[3 * i + 2] = node.velocity_m_s.z;
        s.mass[i] = node.mass_kg;
        s.inv_mass[i] = node.mass_kg > 0.0 ? 1.0 / node.mass_kg : 0.0;
    }

    s.bond_a.resize(bond_count);
    s.bond_b.resize(bond_count);
    s.rest_edge.resize(3U * bond_count);
    s.rest_length.resize(bond_count);
    s.rest_length_sq_minus.resize(bond_count);
    s.weight.resize(bond_count);
    s.compliance.resize(bond_count);
    s.threshold.resize(6U * bond_count);
    s.alive.resize(bond_count);
    s.failure_mode.resize(bond_count);
    s.damage.resize(bond_count);
    s.plastic_extension.assign(bond_count, 0.0);
    s.plastic_strain.assign(bond_count, 0.0);
    s.prev_tensile.assign(bond_count, 0.0);
    s.prev_compressive.assign(bond_count, 0.0);
    s.prev_shear.assign(bond_count, 0.0);
    for (std::size_t k = 0; k < bond_count; ++k) {
        const std::uint32_t o = schedule.bond_order[k];
        const BondRest &rest = matter.asset->bonds[o];
        const ActiveBondState &state = matter.bonds[o];
        s.bond_a[k] = rest.node_a;
        s.bond_b[k] = rest.node_b;
        const Vec3 edge = matter.reference_positions_world_m[rest.node_b] -
                          matter.reference_positions_world_m[rest.node_a];
        s.rest_edge[3 * k] = edge.x; s.rest_edge[3 * k + 1] = edge.y; s.rest_edge[3 * k + 2] = edge.z;
        s.rest_length[k] = rest.rest_length_m;
        const double edge_sq = lengthSquared(edge);
        s.rest_length_sq_minus[k] = edge_sq - rest.rest_length_m * rest.rest_length_m;
        s.weight[k] = edge_sq > 1.0e-18 ? 1.0 / edge_sq : 0.0;
        s.compliance[k] = rest.compliance;
        s.threshold[6 * k] = rest.damage_start_stretch;
        s.threshold[6 * k + 1] = rest.damage_end_stretch;
        s.threshold[6 * k + 2] = rest.compression_damage_start_strain;
        s.threshold[6 * k + 3] = rest.compression_damage_end_strain;
        s.threshold[6 * k + 4] = rest.shear_damage_start_strain;
        s.threshold[6 * k + 5] = rest.shear_damage_end_strain;
        s.alive[k] = state.alive ? 1U : 0U;
        s.failure_mode[k] = static_cast<std::uint8_t>(state.failure_mode);
        s.damage[k] = state.damage;
    }

    // Adjacency in original bond order, as the asset's adjacency lists are, so
    // the node strain accumulates in the CPU lane's summation order.
    std::vector<std::uint32_t> degree(node_count, 0U);
    for (std::size_t o = 0; o < bond_count; ++o) {
        ++degree[matter.asset->bonds[o].node_a];
        ++degree[matter.asset->bonds[o].node_b];
    }
    s.adj_offsets.assign(node_count + 1U, 0U);
    for (std::size_t i = 0; i < node_count; ++i) s.adj_offsets[i + 1U] = s.adj_offsets[i] + degree[i];
    s.adj_bonds.resize(s.adj_offsets.back());
    std::vector<std::uint32_t> cursor = s.adj_offsets;
    for (std::size_t o = 0; o < bond_count; ++o) {
        const BondRest &rest = matter.asset->bonds[o];
        const std::uint32_t k = schedule.bond_schedule_index[o];
        s.adj_bonds[cursor[rest.node_a]++] = k;
        s.adj_bonds[cursor[rest.node_b]++] = k;
    }
    // Padded, k-major neighbour lists in the same order.
    s.max_degree = 0;
    for (std::size_t i = 0; i < node_count; ++i)
        s.max_degree = std::max<std::uint32_t>(s.max_degree, s.adj_offsets[i + 1U] - s.adj_offsets[i]);
    const std::size_t padded = static_cast<std::size_t>(s.max_degree) * node_count;
    s.nbr_bond.assign(padded, kNoBond);
    s.nbr_other.assign(padded, 0U);
    s.nbr_rest.assign(3U * padded, 0.0);
    s.nbr_weight.assign(padded, 0.0);
    s.nbr_alive.assign(padded, 0U);
    s.bond_slot_a.assign(bond_count, 0U);
    s.bond_slot_b.assign(bond_count, 0U);
    for (std::size_t i = 0; i < node_count; ++i) {
        for (std::uint32_t k = 0; k < s.adj_offsets[i + 1U] - s.adj_offsets[i]; ++k) {
            const std::uint32_t bond = s.adj_bonds[s.adj_offsets[i] + k];
            const std::size_t slot = static_cast<std::size_t>(k) * node_count + i;
            s.nbr_bond[slot] = bond;
            s.nbr_alive[slot] = s.alive[bond];
            const bool is_a = s.bond_a[bond] == i;
            (is_a ? s.bond_slot_a : s.bond_slot_b)[bond] = static_cast<std::uint32_t>(slot);
            s.nbr_other[slot] = is_a ? s.bond_b[bond] : s.bond_a[bond];
            // rest_edge = ref[other] - ref[node]: flip the stored b - a for node b.
            const double sign = is_a ? 1.0 : -1.0;
            s.nbr_rest[3 * slot] = sign * s.rest_edge[3 * bond];
            s.nbr_rest[3 * slot + 1] = sign * s.rest_edge[3 * bond + 1];
            s.nbr_rest[3 * slot + 2] = sign * s.rest_edge[3 * bond + 2];
            s.nbr_weight[slot] = s.weight[bond];
        }
    }
    return s;
}

void writeBackLatticeState(
    const LatticeState &state, const LatticeSchedule &schedule, ActiveMatter &matter) {
    if (matter.nodes.size() != state.node_count || matter.bonds.size() != state.bond_count ||
        schedule.bond_order.size() != state.bond_count)
        throw std::invalid_argument("lattice state does not match the active matter");
    for (std::size_t i = 0; i < state.node_count; ++i) {
        ActiveNodeState &node = matter.nodes[i];
        const Vec3 x0{state.x0[3 * i], state.x0[3 * i + 1], state.x0[3 * i + 2]};
        node.position_world_m = state.origin + x0 + Vec3{state.u[3 * i], state.u[3 * i + 1], state.u[3 * i + 2]};
        node.previous_position_world_m = state.origin + x0 +
            Vec3{state.u_prev[3 * i], state.u_prev[3 * i + 1], state.u_prev[3 * i + 2]};
        node.velocity_m_s = {state.v[3 * i], state.v[3 * i + 1], state.v[3 * i + 2]};
    }
    bool any_dead = false;
    for (std::size_t k = 0; k < state.bond_count; ++k) {
        ActiveBondState &bond = matter.bonds[schedule.bond_order[k]];
        bond.accumulated_lambda = 0.0;
        bond.damage = state.damage[k];
        bond.peak_tensile_stretch = state.prev_tensile[k];
        bond.peak_compressive_strain = state.prev_compressive[k];
        bond.peak_shear_strain = state.prev_shear[k];
        bond.failure_mode = static_cast<BondFailureMode>(state.failure_mode[k]);
        bond.alive = state.alive[k] != 0U;
        any_dead = any_dead || !bond.alive;
    }
    if (any_dead) matter.connectivity_dirty = true;
}

double latticeStateElasticEnergy(const LatticeState &state) {
    double total = 0.0;
    for (std::size_t k = 0; k < state.bond_count; ++k) {
        if (!state.alive[k]) continue;
        const double c = state.compliance[k];
        if (!(c > 0.0)) continue;
        const std::uint32_t a = state.bond_a[k], b = state.bond_b[k];
        const Vec3 delta{state.x0[3 * b] + state.u[3 * b] - state.x0[3 * a] - state.u[3 * a],
                         state.x0[3 * b + 1] + state.u[3 * b + 1] - state.x0[3 * a + 1] - state.u[3 * a + 1],
                         state.x0[3 * b + 2] + state.u[3 * b + 2] - state.x0[3 * a + 2] - state.u[3 * a + 2]};
        const double extension = length(delta) - state.rest_length[k] - state.plastic_extension[k];
        total += 0.5 * extension * extension / c;
    }
    return total;
}

double latticeStateKineticEnergy(const LatticeState &state) {
    double total = 0.0;
    for (std::size_t i = 0; i < state.node_count; ++i) {
        const double speed_squared = state.v[3 * i] * state.v[3 * i] +
                                     state.v[3 * i + 1] * state.v[3 * i + 1] +
                                     state.v[3 * i + 2] * state.v[3 * i + 2];
        total += 0.5 * state.mass[i] * speed_squared;
    }
    return total;
}

} // namespace banjo::fastlattice
