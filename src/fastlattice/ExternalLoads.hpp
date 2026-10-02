#pragma once

// Finite CPU load phase. No positions, bond state or material law are assigned;
// a force integrates through the same explicit velocity kick as gravity.
#include "fastlattice/FastLattice.hpp"

#include <cmath>
#include <algorithm>
#include <limits>
#include <set>
#include <stdexcept>
#include <utility>
#include <vector>

namespace banjo::fastlattice {

template <typename Real>
class CpuExternalLoads {
public:
    void reset(const Vec3 &origin) { origin_=origin; nodes_.clear(); wrenches_.clear(); remaining_=0; }

    void set(const std::vector<Vec3> &forces, std::uint64_t substeps,
             const LatticeArrays<Real> &lattice) {
        if (forces.empty()) {
            if (substeps != 0) throw std::invalid_argument("empty external load needs zero substeps");
            nodes_.clear(); wrenches_.clear(); remaining_=0; return;
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
        nodes_=std::move(staged);wrenches_.clear();remaining_=nodes_.empty()?0:substeps;
    }

    void setWrenches(const std::vector<ExternalWrench> &wrenches,std::uint64_t substeps,
                     const LatticeArrays<Real> &lattice) {
        if (wrenches.empty()) { set({},substeps,lattice);return; }
        if (!substeps) throw std::invalid_argument("external wrench needs a finite nonzero span");
        auto staged=wrenches;
        std::set<std::string> sources;
        std::set<std::uint32_t> used;
        for (auto &wrench:staged) {
            if (wrench.source.empty()||!sources.insert(wrench.source).second||wrench.nodes.empty())
                throw std::invalid_argument("external wrench needs distinct named nonempty regions");
            if (!finite(wrench.point_world_m)||!finite(wrench.force_n)||!finite(wrench.torque_n_m)||
                !std::isfinite(norm(wrench.force_n))||!std::isfinite(norm(wrench.torque_n_m)))
                throw std::invalid_argument("external wrench must be finite");
            std::sort(wrench.nodes.begin(),wrench.nodes.end());
            for (const auto node:wrench.nodes)
                if (node>=lattice.node_count||!used.insert(node).second)
                    throw std::invalid_argument("external wrench nodes repeat, overlap or exceed the lattice");
        }
        std::sort(staged.begin(),staged.end(),[](const ExternalWrench &a,const ExternalWrench &b) { return a.source<b.source; });
        staged.erase(std::remove_if(staged.begin(),staged.end(),[](const ExternalWrench &w) {
            return w.force_n.x==0&&w.force_n.y==0&&w.force_n.z==0&&
                   w.torque_n_m.x==0&&w.torque_n_m.y==0&&w.torque_n_m.z==0;
        }),staged.end());
        auto nodes=wrenchNodes(staged,lattice); // validate before replacing any active load
        nodes_=std::move(nodes);wrenches_=std::move(staged);remaining_=nodes_.empty()?0:substeps;
    }

    void kick(const LatticeArrays<Real> &lattice, Real dt, ExternalLoadLedger &ledger,
              std::vector<ExternalWrenchLedger> *source_ledgers=nullptr) {
        if (!remaining_) return;
        if (!(dt>0) || !std::isfinite(dt)) throw std::invalid_argument("external load needs a finite positive timestep");
        if (!wrenches_.empty()) {
            if (!source_ledgers) throw std::invalid_argument("external wrench needs its source ledgers");
            nodes_=wrenchNodes(wrenches_,lattice);
        }
        ExternalLoadLedger change;
        change.steps=1;change.elapsed_s=static_cast<double>(dt);
        std::vector<ExternalLoadLedger> source_changes(wrenches_.size(),change);
        // Validate every kick and its ledger before changing any velocity.
        for (Node &node:nodes_) {
            const auto before=load3(lattice.v,node.index);
            node.after=before+(dt*lattice.inv_mass[node.index])*node.applied;
            if (!finite(node.after)) throw std::overflow_error("external force kick exceeds backend precision");
            const Vec3 old=widen(before), next=widen(node.after);
            const Vec3 impulse=static_cast<double>(lattice.mass[node.index])*(next-old);
            const Vec3 where=origin_+widen(position(lattice,node.index));
            change.requested_impulse_n_s+=static_cast<double>(dt)*node.requested;
            change.requested_angular_impulse_kg_m2_s+=cross(where,static_cast<double>(dt)*node.requested);
            change.impulse_n_s+=impulse;
            change.angular_impulse_kg_m2_s+=cross(where,impulse);
            change.work_j+=dot(impulse,.5*(old+next));
            if (node.source!=kNoSource) {
                auto &own=source_changes[node.source];
                own.requested_impulse_n_s+=static_cast<double>(dt)*node.requested;
                own.requested_angular_impulse_kg_m2_s+=cross(where,static_cast<double>(dt)*node.requested);
                own.impulse_n_s+=impulse;own.angular_impulse_kg_m2_s+=cross(where,impulse);
                own.work_j+=dot(impulse,.5*(old+next));
            }
        }
        const auto total=added(ledger,change);
        // Preflight source totals and allocations before any velocity/ledger write.
        std::vector<ExternalWrenchLedger> source_totals;
        if (!wrenches_.empty()) {
            source_totals=*source_ledgers;
            for (std::size_t k=0;k<wrenches_.size();++k) {
                const auto found=std::find_if(source_totals.begin(),source_totals.end(),[&](const auto &own) {
                    return own.source==wrenches_[k].source;
                });
                if (found==source_totals.end()) source_totals.push_back({wrenches_[k].source,added({},source_changes[k])});
                else found->load=added(found->load,source_changes[k]);
            }
        }
        for (const Node &node:nodes_) store3(lattice.v,node.index,node.after);
        ledger=total;
        if (!wrenches_.empty()) *source_ledgers=std::move(source_totals);
        --remaining_;
    }

private:
    static constexpr std::size_t kNoSource=std::numeric_limits<std::size_t>::max();
    struct Node { std::uint32_t index; Vec3 requested; V3<Real> applied,after; std::size_t source{kNoSource}; };
    static ExternalLoadLedger added(const ExternalLoadLedger &a,const ExternalLoadLedger &b) {
        if (b.steps>std::numeric_limits<std::uint64_t>::max()-a.steps)
            throw std::overflow_error("external load step count overflow");
        ExternalLoadLedger out;
        out.steps=a.steps+b.steps;out.elapsed_s=a.elapsed_s+b.elapsed_s;
        out.requested_impulse_n_s=a.requested_impulse_n_s+b.requested_impulse_n_s;
        out.requested_angular_impulse_kg_m2_s=a.requested_angular_impulse_kg_m2_s+b.requested_angular_impulse_kg_m2_s;
        out.impulse_n_s=a.impulse_n_s+b.impulse_n_s;
        out.angular_impulse_kg_m2_s=a.angular_impulse_kg_m2_s+b.angular_impulse_kg_m2_s;
        out.work_j=a.work_j+b.work_j;
        if (!finite(b.requested_impulse_n_s)||!finite(b.requested_angular_impulse_kg_m2_s)||
            !finite(b.impulse_n_s)||!finite(b.angular_impulse_kg_m2_s)||
            !std::isfinite(b.work_j)||!std::isfinite(b.elapsed_s)||
            !finite(out.requested_impulse_n_s)||!finite(out.requested_angular_impulse_kg_m2_s)||
            !finite(out.impulse_n_s)||!finite(out.angular_impulse_kg_m2_s)||
            !std::isfinite(out.work_j)||!std::isfinite(out.elapsed_s))
            throw std::overflow_error("external load ledger exceeds finite range");
        return out;
    }
    std::vector<Node> wrenchNodes(const std::vector<ExternalWrench> &wrenches,const LatticeArrays<Real> &lattice) const {
        std::vector<Node> out;
        for (std::size_t k=0;k<wrenches.size();++k) {
            const auto &w=wrenches[k];
            double mass=0;
            std::vector<Vec3> points;points.reserve(w.nodes.size());
            const Vec3 anchor=widen(position(lattice,w.nodes.front()));
            for (const auto node:w.nodes) {
                if (!(lattice.mass[node]>0)||!(lattice.inv_mass[node]>0)||
                    !std::isfinite(lattice.mass[node])||!std::isfinite(lattice.inv_mass[node]))
                    throw std::invalid_argument("external wrench needs finite movable node masses");
                const Vec3 relative=widen(position(lattice,node))-anchor;
                if (!finite(relative)) throw std::invalid_argument("external wrench node position is not finite");
                points.push_back(relative);mass+=static_cast<double>(lattice.mass[node]);
            }
            if (!(mass>0)||!std::isfinite(mass)) throw std::invalid_argument("external wrench mass overflow");
            Vec3 center{};
            for (std::size_t i=0;i<points.size();++i) center+=(static_cast<double>(lattice.mass[w.nodes[i]])/mass)*points[i];
            double tensor[9]{};
            for (std::size_t i=0;i<points.size();++i) {
                points[i]-=center;
                const double r[3]{points[i].x,points[i].y,points[i].z};
                const double share=static_cast<double>(lattice.mass[w.nodes[i]])/mass;
                for (unsigned a=0;a<3;++a) for (unsigned b=0;b<3;++b)
                    tensor[3*a+b]+=share*(a==b?r[(a+1)%3]*r[(a+1)%3]+r[(a+2)%3]*r[(a+2)%3]:-r[a]*r[b]);
            }
            const Vec3 moment=w.torque_n_m+cross((w.point_world_m-origin_)-anchor-center,w.force_n);
            if (!finite(center)||!finite(moment)) throw std::invalid_argument("external wrench moment overflow");
            double scale=0;
            for (const double entry:tensor) {
                if (!std::isfinite(entry)) throw std::invalid_argument("external wrench inertia overflow");
                scale=std::max(scale,std::abs(entry));
            }
            Vec3 alpha{};
            if (scale>0) {
                for (double &entry:tensor) entry/=scale;
                double eigen[3],axes[9];symmetricEigen3(tensor,eigen,axes);
                const double largest=std::max({std::abs(eigen[0]),std::abs(eigen[1]),std::abs(eigen[2])});
                Vec3 unresolved=moment;
                for (unsigned axis=0;axis<3;++axis) {
                    if (!(eigen[axis]>1e-10*largest)) continue;
                    const Vec3 direction{axes[axis],axes[3+axis],axes[6+axis]};
                    const double component=dot(direction,moment);
                    unresolved-=component*direction;
                    alpha+=(component/mass/scale/eigen[axis])*direction;
                }
                if (norm(unresolved)>1024*std::numeric_limits<double>::epsilon()*norm(moment))
                    throw std::invalid_argument("external wrench torque is not represented by these nodes");
            } else if (norm(moment)>0) throw std::invalid_argument("external wrench torque needs a sampled lever arm");
            if (!finite(alpha)) throw std::invalid_argument("external wrench acceleration overflow");
            Vec3 force_sum{},moment_sum{};double absolute_force=0,absolute_moment=0;
            for (std::size_t i=0;i<points.size();++i) {
                const double m=static_cast<double>(lattice.mass[w.nodes[i]]);
                const Vec3 force=(m/mass)*w.force_n+m*cross(alpha,points[i]);
                const V3<Real> converted{static_cast<Real>(force.x),static_cast<Real>(force.y),static_cast<Real>(force.z)};
                if (!finite(force)||!finite(converted)) throw std::invalid_argument("external wrench node force exceeds backend precision");
                out.push_back({w.nodes[i],force,converted,{},k});
                force_sum+=force;moment_sum+=cross(points[i],force);
                absolute_force+=norm(force);absolute_moment+=norm(cross(points[i],force));
            }
            if (!finite(force_sum)||!finite(moment_sum)||!std::isfinite(absolute_force)||!std::isfinite(absolute_moment)||
                norm(force_sum-w.force_n)>1e-10*std::max(norm(w.force_n),absolute_force)||
                norm(moment_sum-moment)>1e-10*std::max(norm(moment),absolute_moment))
                throw std::invalid_argument("external wrench resultant cannot be represented accurately");
        }
        return out;
    }
    static double norm(const Vec3 &v) { return std::hypot(v.x,v.y,v.z); }
    static bool finite(const Vec3 &v) { return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z); }
    static bool finite(const V3<Real> &v) { return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z); }
    static Vec3 widen(const V3<Real> &v) { return {static_cast<double>(v.x),static_cast<double>(v.y),static_cast<double>(v.z)}; }
    Vec3 origin_{};
    std::vector<Node> nodes_;
    std::vector<ExternalWrench> wrenches_;
    std::uint64_t remaining_{};
};

} // namespace banjo::fastlattice
