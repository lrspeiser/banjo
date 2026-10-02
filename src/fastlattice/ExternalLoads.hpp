#pragma once

// Finite CPU load phase. No positions, bond state or material law are assigned;
// a force integrates through the same explicit velocity kick as gravity.
#include "fastlattice/FastLattice.hpp"

#include <cmath>
#include <stdexcept>
#include <utility>
#include <vector>

namespace banjo::fastlattice {

template <typename Real>
class CpuExternalLoads {
public:
    void reset(const Vec3 &origin) { origin_=origin; nodes_.clear(); remaining_=0; }

    void set(const std::vector<Vec3> &forces, std::uint64_t substeps,
             const LatticeArrays<Real> &lattice) {
        if (forces.empty()) {
            if (substeps != 0) throw std::invalid_argument("empty external load needs zero substeps");
            nodes_.clear(); remaining_=0; return;
        }
        if (forces.size()!=lattice.node_count || substeps==0)
            throw std::invalid_argument("external load needs one force per node and a finite nonzero span");
        std::vector<Node> staged;
        for (std::uint32_t i=0; i<lattice.node_count; ++i) {
            const Vec3 force=forces[i];
            const V3<Real> converted{static_cast<Real>(force.x),static_cast<Real>(force.y),static_cast<Real>(force.z)};
            if (!finite(force) || !std::isfinite(std::hypot(force.x,force.y,force.z)) ||
                !finite(converted)) throw std::invalid_argument("external force is not finite in backend precision");
            if (force.x==0 && force.y==0 && force.z==0) continue;
            if (!(lattice.mass[i]>0) || !(lattice.inv_mass[i]>0) ||
                !std::isfinite(lattice.mass[i]) || !std::isfinite(lattice.inv_mass[i]))
                throw std::invalid_argument("external force needs a finite positive movable node mass");
            staged.push_back({i,force,converted,{}});
        }
        nodes_=std::move(staged); remaining_=nodes_.empty()?0:substeps;
    }

    void kick(const LatticeArrays<Real> &lattice, Real dt, ExternalLoadLedger &ledger) {
        if (!remaining_) return;
        if (!(dt>0) || !std::isfinite(dt)) throw std::invalid_argument("external load needs a finite positive timestep");
        ExternalLoadLedger change;
        change.steps=1;change.elapsed_s=static_cast<double>(dt);
        // Validate every kick and its ledger before changing any velocity.
        for (Node &node:nodes_) {
            const auto before=load3(lattice.v,node.index);
            node.after=before+(dt*lattice.inv_mass[node.index])*node.applied;
            if (!finite(node.after)) throw std::overflow_error("external force kick exceeds backend precision");
            const Vec3 old=widen(before), next=widen(node.after);
            const Vec3 impulse=static_cast<double>(lattice.mass[node.index])*(next-old);
            const Vec3 where=origin_+widen(position(lattice,node.index));
            change.requested_impulse_n_s+=static_cast<double>(dt)*node.requested;
            change.impulse_n_s+=impulse;
            change.angular_impulse_kg_m2_s+=cross(where,impulse);
            change.work_j+=dot(impulse,.5*(old+next));
        }
        if (!finite(change.requested_impulse_n_s) || !finite(change.impulse_n_s) ||
            !finite(change.angular_impulse_kg_m2_s) || !std::isfinite(change.work_j))
            throw std::overflow_error("external load ledger exceeds finite range");
        const Vec3 requested=ledger.requested_impulse_n_s+change.requested_impulse_n_s;
        const Vec3 delivered=ledger.impulse_n_s+change.impulse_n_s;
        const Vec3 angular=ledger.angular_impulse_kg_m2_s+change.angular_impulse_kg_m2_s;
        const double work=ledger.work_j+change.work_j, elapsed=ledger.elapsed_s+change.elapsed_s;
        if (!finite(requested) || !finite(delivered) || !finite(angular) ||
            !std::isfinite(work) || !std::isfinite(elapsed))
            throw std::overflow_error("accumulated external load ledger exceeds finite range");
        for (const Node &node:nodes_) store3(lattice.v,node.index,node.after);
        ++ledger.steps; ledger.elapsed_s=elapsed; ledger.requested_impulse_n_s=requested;
        ledger.impulse_n_s=delivered;ledger.angular_impulse_kg_m2_s=angular;ledger.work_j=work;
        --remaining_;
    }

private:
    struct Node { std::uint32_t index; Vec3 requested; V3<Real> applied,after; };
    static bool finite(const Vec3 &v) { return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z); }
    static bool finite(const V3<Real> &v) { return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z); }
    static Vec3 widen(const V3<Real> &v) { return {static_cast<double>(v.x),static_cast<double>(v.y),static_cast<double>(v.z)}; }
    Vec3 origin_{};
    std::vector<Node> nodes_;
    std::uint64_t remaining_{};
};

} // namespace banjo::fastlattice
