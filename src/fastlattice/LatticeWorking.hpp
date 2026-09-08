#pragma once

// Precision-specific working copy of a LatticeState, shared by the CPU and
// CUDA backends: the CPU backend runs on these vectors in place, the CUDA
// backend mirrors them into device memory.

#include "fastlattice/FastLattice.hpp"

#include <cstdint>
#include <vector>

namespace banjo::fastlattice {

template <typename Real>
struct WorkingLattice {
    std::uint32_t node_count{}, bond_count{}, block_count{}, color_count{};
    std::vector<Real> x0, u, u_prev, v, inv_mass, mass, rinv, node_unmeasured, strain, approach;
    std::vector<std::uint8_t> node_valid, node_dirty, engaged, candidate;
    std::vector<std::uint32_t> adj_offsets, adj_bonds, node_block_begin;
    std::uint32_t max_degree{};
    std::vector<std::uint32_t> nbr_bond, nbr_other;
    std::vector<Real> nbr_rest, nbr_weight;
    std::vector<std::uint8_t> nbr_alive;
    std::vector<std::uint32_t> bond_slot_a, bond_slot_b;
    std::vector<std::uint32_t> bond_a, bond_b;
    std::vector<Real> rest_edge, rest_length, rest_length_sq_minus, weight, compliance, threshold;
    std::vector<std::uint8_t> alive, failure_mode;
    std::vector<Real> damage, accumulated_lambda, prev_tensile, prev_compressive, prev_shear;
    std::vector<std::uint32_t> range_begin, range_end, bond_block_begin;
    std::vector<std::uint32_t> candidate_list, candidate_count;
    std::vector<std::uint32_t> rank_deficient_nodes; // 1 counter

    static WorkingLattice fromState(const LatticeState &state, const LatticeSchedule &schedule) {
        WorkingLattice w;
        w.node_count = state.node_count;
        w.bond_count = state.bond_count;
        w.block_count = schedule.block_count;
        w.color_count = schedule.color_count;
        const auto cast = [](const std::vector<double> &in) {
            std::vector<Real> out(in.size());
            for (std::size_t i = 0; i < in.size(); ++i) out[i] = static_cast<Real>(in[i]);
            return out;
        };
        w.x0 = cast(state.x0);
        w.u = cast(state.u);
        w.u_prev = cast(state.u_prev);
        w.v = cast(state.v);
        w.inv_mass = cast(state.inv_mass);
        w.mass = cast(state.mass);
        w.rinv.assign(9U * state.node_count, Real(0));
        w.node_unmeasured.assign(3U * state.node_count, Real(0));
        w.strain.assign(6U * state.node_count, Real(0));
        w.approach.assign(kMaxSupportPlanes * state.node_count, Real(0));
        w.node_valid.assign(state.node_count, 0U);
        w.node_dirty.assign(state.node_count, 1U);
        w.engaged.assign(kMaxSupportPlanes * state.node_count, 0U);
        w.candidate.assign(state.node_count, 0U);
        w.adj_offsets = state.adj_offsets;
        w.adj_bonds = state.adj_bonds;
        w.max_degree = state.max_degree;
        w.nbr_bond = state.nbr_bond;
        w.nbr_other = state.nbr_other;
        w.nbr_rest = cast(state.nbr_rest);
        w.nbr_weight = cast(state.nbr_weight);
        w.nbr_alive = state.nbr_alive;
        w.bond_slot_a = state.bond_slot_a;
        w.bond_slot_b = state.bond_slot_b;
        w.node_block_begin = schedule.node_block_begin;
        w.bond_a = state.bond_a;
        w.bond_b = state.bond_b;
        w.rest_edge = cast(state.rest_edge);
        w.rest_length = cast(state.rest_length);
        w.rest_length_sq_minus = cast(state.rest_length_sq_minus);
        w.weight = cast(state.weight);
        w.compliance = cast(state.compliance);
        w.threshold = cast(state.threshold);
        w.alive = state.alive;
        w.failure_mode = state.failure_mode;
        w.damage = cast(state.damage);
        w.accumulated_lambda.assign(state.bond_count, Real(0));
        w.prev_tensile = cast(state.prev_tensile);
        w.prev_compressive = cast(state.prev_compressive);
        w.prev_shear = cast(state.prev_shear);
        w.range_begin = schedule.range_begin;
        w.range_end = schedule.range_end;
        w.bond_block_begin = schedule.bond_block_begin;
        w.candidate_list.assign(static_cast<std::size_t>(schedule.block_count) * kMaxCandidatesPerBlock, 0U);
        w.candidate_count.assign(schedule.block_count, 0U);
        w.rank_deficient_nodes.assign(1, 0U);
        return w;
    }

    void toState(LatticeState &state) const {
        const auto widen = [](const std::vector<Real> &in, std::vector<double> &out) {
            out.resize(in.size());
            for (std::size_t i = 0; i < in.size(); ++i) out[i] = static_cast<double>(in[i]);
        };
        widen(u, state.u);
        widen(u_prev, state.u_prev);
        widen(v, state.v);
        state.alive = alive;
        state.failure_mode = failure_mode;
        widen(damage, state.damage);
        widen(prev_tensile, state.prev_tensile);
        widen(prev_compressive, state.prev_compressive);
        widen(prev_shear, state.prev_shear);
    }

    // Pointers into the vectors; valid until any vector is resized.
    [[nodiscard]] LatticeArrays<Real> arrays() {
        LatticeArrays<Real> a{};
        a.node_count = node_count;
        a.bond_count = bond_count;
        a.block_count = block_count;
        a.color_count = color_count;
        a.x0 = x0.data();
        a.u = u.data();
        a.u_prev = u_prev.data();
        a.v = v.data();
        a.inv_mass = inv_mass.data();
        a.mass = mass.data();
        a.rinv = rinv.data();
        a.node_unmeasured = node_unmeasured.data();
        a.node_valid = node_valid.data();
        a.node_dirty = node_dirty.data();
        a.strain = strain.data();
        a.approach = approach.data();
        a.engaged = engaged.data();
        a.candidate = candidate.data();
        a.adj_offsets = adj_offsets.data();
        a.adj_bonds = adj_bonds.data();
        a.node_block_begin = node_block_begin.data();
        a.max_degree = max_degree;
        a.nbr_bond = nbr_bond.data();
        a.nbr_other = nbr_other.data();
        a.nbr_rest = nbr_rest.data();
        a.nbr_weight = nbr_weight.data();
        a.nbr_alive = nbr_alive.data();
        a.bond_slot_a = bond_slot_a.data();
        a.bond_slot_b = bond_slot_b.data();
        a.bond_a = bond_a.data();
        a.bond_b = bond_b.data();
        a.rest_edge = rest_edge.data();
        a.rest_length = rest_length.data();
        a.rest_length_sq_minus = rest_length_sq_minus.data();
        a.weight = weight.data();
        a.compliance = compliance.data();
        a.threshold = threshold.data();
        a.alive = alive.data();
        a.damage = damage.data();
        a.failure_mode = failure_mode.data();
        a.accumulated_lambda = accumulated_lambda.data();
        a.prev_tensile = prev_tensile.data();
        a.prev_compressive = prev_compressive.data();
        a.prev_shear = prev_shear.data();
        a.range_begin = range_begin.data();
        a.range_end = range_end.data();
        a.bond_block_begin = bond_block_begin.data();
        a.candidate_list = candidate_list.data();
        a.candidate_count = candidate_count.data();
        a.rank_deficient_nodes = rank_deficient_nodes.data();
        return a;
    }
};

template <typename Real>
[[nodiscard]] V3<Real> convertV3(const V3<double> &v) {
    return {static_cast<Real>(v.x), static_cast<Real>(v.y), static_cast<Real>(v.z)};
}

template <typename Real>
[[nodiscard]] SphereState<Real> convertSphere(const SphereState<double> &s) {
    return {convertV3<Real>(s.center), convertV3<Real>(s.velocity), convertV3<Real>(s.angular_velocity),
            static_cast<Real>(s.radius), static_cast<Real>(s.mass), static_cast<Real>(s.inertia)};
}

template <typename Real>
[[nodiscard]] V3<double> widenV3(const V3<Real> &v) {
    return {static_cast<double>(v.x), static_cast<double>(v.y), static_cast<double>(v.z)};
}

template <typename Real>
[[nodiscard]] SphereState<double> widenSphere(const SphereState<Real> &s) {
    return {widenV3(s.center), widenV3(s.velocity), widenV3(s.angular_velocity),
            static_cast<double>(s.radius), static_cast<double>(s.mass), static_cast<double>(s.inertia)};
}

template <typename Real>
[[nodiscard]] StepSettings<Real> convertSettings(const StepSettings<double> &s) {
    StepSettings<Real> out{};
    out.dt = static_cast<Real>(s.dt);
    out.gravity = convertV3<Real>(s.gravity);
    out.constraint_iterations = s.constraint_iterations;
    out.damping_fraction = static_cast<Real>(s.damping_fraction);
    out.sphere_enabled = s.sphere_enabled;
    out.direct_arithmetic = s.direct_arithmetic;
    out.contact.static_friction = static_cast<Real>(s.contact.static_friction);
    out.contact.dynamic_friction = static_cast<Real>(s.contact.dynamic_friction);
    out.contact.restitution = static_cast<Real>(s.contact.restitution);
    out.contact.restitution_speed_threshold = static_cast<Real>(s.contact.restitution_speed_threshold);
    out.contact.node_contact_radius = static_cast<Real>(s.contact.node_contact_radius);
    out.contact.contact_margin = static_cast<Real>(s.contact.contact_margin);
    out.contact.prefilter_slack = static_cast<Real>(s.contact.prefilter_slack);
    out.support.plane_count = s.support.plane_count;
    for (unsigned p = 0; p < kMaxSupportPlanes; ++p) {
        const SupportPlane<double> &in = s.support.planes[p];
        SupportPlane<Real> &plane = out.support.planes[p];
        plane.point = convertV3<Real>(in.point);
        plane.normal = convertV3<Real>(in.normal);
        plane.tangent = convertV3<Real>(in.tangent);
        plane.bitangent = convertV3<Real>(in.bitangent);
        plane.restitution = static_cast<Real>(in.restitution);
        plane.static_friction = static_cast<Real>(in.static_friction);
        plane.dynamic_friction = static_cast<Real>(in.dynamic_friction);
        plane.node_radius = static_cast<Real>(in.node_radius);
        plane.reach_capped = in.reach_capped;
        plane.footprint_count = in.footprint_count;
        for (unsigned f = 0; f < kMaxFootprints; ++f) {
            plane.footprints[f] = {static_cast<Real>(in.footprints[f].center_t),
                                   static_cast<Real>(in.footprints[f].center_b),
                                   static_cast<Real>(in.footprints[f].half_t),
                                   static_cast<Real>(in.footprints[f].half_b)};
        }
    }
    return out;
}

// Shared frame extraction from a working copy.
template <typename Real>
[[nodiscard]] FrameCapture captureFrame(const WorkingLattice<Real> &w, std::uint64_t step,
                                        const SphereState<Real> &sphere) {
    FrameCapture frame;
    frame.step = step;
    frame.u.resize(w.u.size());
    for (std::size_t i = 0; i < w.u.size(); ++i) frame.u[i] = static_cast<float>(w.u[i]);
    frame.alive = w.alive;
    frame.damage.resize(w.damage.size());
    for (std::size_t i = 0; i < w.damage.size(); ++i) frame.damage[i] = static_cast<float>(w.damage[i]);
    frame.sphere = widenSphere(sphere);
    return frame;
}

} // namespace banjo::fastlattice
