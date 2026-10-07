#include "fastlattice/ConstituentPartition.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <stdexcept>

namespace banjo::fastlattice {
namespace {
bool finite(Vec3 v) {return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
Vec3 at(const std::vector<double> &v,unsigned i) {return {v[3*i],v[3*i+1],v[3*i+2]};}
void validate(const LatticeAsset &a,const LatticeSchedule &order,const LatticeState &s) {
    const std::size_t n=s.node_count,b=s.bond_count;
    if (!n||n>1024||b>65536||a.nodes.size()!=n||a.bonds.size()!=b||!finite(s.origin)||
        order.bond_order.size()!=b||order.bond_schedule_index.size()!=b)
        throw std::invalid_argument("invalid bounded constituent partition dimensions");
    for (const auto *v:{&s.x0,&s.u,&s.u_prev,&s.v})
        if(v->size()!=3*n||!std::all_of(v->begin(),v->end(),[](double x){return std::isfinite(x);}))
            throw std::invalid_argument("constituent partition needs complete finite node state");
    if(s.mass.size()!=n||s.inv_mass.size()!=n)
        throw std::invalid_argument("constituent partition needs complete physical masses");
    for(unsigned i=0;i<n;++i) {
        if(!(s.mass[i]>0)||!std::isfinite(s.mass[i])||!std::isfinite(s.inv_mass[i])||s.inv_mass[i]<0||
            (s.inv_mass[i]>0&&std::abs(s.mass[i]*s.inv_mass[i]-1)>1e-12)||
            !(a.nodes[i].represented_volume_m3>0)||!std::isfinite(a.nodes[i].represented_volume_m3)||
            !finite(a.nodes[i].local_position_m)||!finite(s.origin+at(s.x0,i)+at(s.u,i)))
            throw std::invalid_argument("invalid constituent node geometry/mass");
        if(s.inv_mass[i]==0&&(s.v[3*i]!=0||s.v[3*i+1]!=0||s.v[3*i+2]!=0||
            s.u_prev[3*i]!=s.u[3*i]||s.u_prev[3*i+1]!=s.u[3*i+1]||s.u_prev[3*i+2]!=s.u[3*i+2]))
            throw std::invalid_argument("constituent boundary is not stationary");
    }
    if(s.bond_a.size()!=b||s.bond_b.size()!=b||s.alive.size()!=b||s.failure_mode.size()!=b||
        s.rest_edge.size()!=3*b||s.threshold.size()!=6*b)
        throw std::invalid_argument("constituent partition needs complete bond topology");
    for(const auto *v:{&s.rest_length,&s.rest_length_sq_minus,&s.weight,&s.compliance,&s.damage,
        &s.prev_tensile,&s.prev_compressive,&s.prev_shear,&s.plastic_extension,&s.plastic_strain})
        if(v->size()!=b||!std::all_of(v->begin(),v->end(),[](double x){return std::isfinite(x);}))
            throw std::invalid_argument("constituent partition needs finite constitutive histories");
    for(unsigned o=0;o<b;++o) {
        const auto k=order.bond_schedule_index[o];
        if(k>=b||order.bond_order[k]!=o||a.bonds[o].node_a>=n||a.bonds[o].node_b>=n||
            a.bonds[o].node_a==a.bonds[o].node_b||s.bond_a[k]!=a.bonds[o].node_a||s.bond_b[k]!=a.bonds[o].node_b||
            s.alive[k]>1||s.failure_mode[k]>3||!(s.compliance[k]>0)||!(s.rest_length[k]>0)||s.weight[k]<0||
            s.damage[k]<0||s.damage[k]>1||s.prev_tensile[k]<0||s.prev_compressive[k]<0||s.prev_shear[k]<0||
            s.plastic_strain[k]<0||!finite(at(s.rest_edge,k)))
            throw std::invalid_argument("invalid constituent bond mapping or history");
        for(unsigned axis=0;axis<6;++axis)
            if(std::isnan(s.threshold[6*k+axis])||s.threshold[6*k+axis]<0)
                throw std::invalid_argument("invalid constituent failure threshold");
    }
    // Finite individual scalars can still overflow mechanical totals. Refuse
    // those snapshots before any component is exposed to a replacement owner.
    double mass=0,volume=0;Vec3 momentum{},angular{};
    for(unsigned i=0;i<n;++i) {
        mass+=s.mass[i];volume+=a.nodes[i].represented_volume_m3;
        const Vec3 p=s.mass[i]*at(s.v,i);momentum+=p;
        angular+=cross(s.origin+at(s.x0,i)+at(s.u,i),p);
    }
    if(!std::isfinite(mass)||!std::isfinite(volume)||!finite(momentum)||!finite(angular)||
        !std::isfinite(latticeStateKineticEnergy(s))||!std::isfinite(latticeStateElasticEnergy(s)))
        throw std::invalid_argument("constituent mechanical totals overflow");
}
void adjacency(LatticeAsset &asset) {
    asset.adjacency_offsets.assign(asset.nodes.size()+1,0);
    for(const auto &b:asset.bonds) {++asset.adjacency_offsets[b.node_a+1];++asset.adjacency_offsets[b.node_b+1];}
    std::partial_sum(asset.adjacency_offsets.begin(),asset.adjacency_offsets.end(),asset.adjacency_offsets.begin());
    asset.adjacent_bond_indices.resize(2*asset.bonds.size());auto cursor=asset.adjacency_offsets;
    for(unsigned k=0;k<asset.bonds.size();++k) {
        asset.adjacent_bond_indices[cursor[asset.bonds[k].node_a]++]=k;
        asset.adjacent_bond_indices[cursor[asset.bonds[k].node_b]++]=k;
    }
}
SeveredConstituentBond archive(unsigned original,const LatticeSchedule &order,const LatticeState &s) {
    const auto k=order.bond_schedule_index[original];SeveredConstituentBond out;
    out.parent_bond=original;out.parent_node_a=s.bond_a[k];out.parent_node_b=s.bond_b[k];out.rest_edge_m=at(s.rest_edge,k);
    out.rest_length_m=s.rest_length[k];out.rest_length_sq_minus_m2=s.rest_length_sq_minus[k];out.weight=s.weight[k];out.compliance=s.compliance[k];
    for(unsigned j=0;j<6;++j)out.thresholds[j]=s.threshold[6*k+j];
    out.damage=s.damage[k];out.previous_tensile=s.prev_tensile[k];out.previous_compressive=s.prev_compressive[k];out.previous_shear=s.prev_shear[k];
    out.plastic_extension_m=s.plastic_extension[k];out.plastic_strain_m=s.plastic_strain[k];out.failure_mode=s.failure_mode[k];return out;
}
}

ConstituentPartition partitionConstituents(const LatticeAsset &asset,const LatticeSchedule &order,const LatticeState &s) {
    validate(asset,order,s);
    std::vector<unsigned> roots(s.node_count);std::iota(roots.begin(),roots.end(),0);
    const auto root=[&](unsigned i){while(roots[i]!=i){roots[i]=roots[roots[i]];i=roots[i];}return i;};
    for(unsigned k=0;k<s.bond_count;++k)if(s.alive[k]) {
        const auto a=root(s.bond_a[k]),b=root(s.bond_b[k]);roots[std::max(a,b)]=std::min(a,b);
    }
    ConstituentPartition out;
    std::vector<unsigned> owner(s.node_count,std::numeric_limits<unsigned>::max());
    for(unsigned i=0;i<s.node_count;++i) {
        const auto r=root(i);
        if(owner[r]==std::numeric_limits<unsigned>::max()) {
            owner[r]=static_cast<unsigned>(out.components.size());out.components.emplace_back();
        }
        owner[i]=owner[r];out.components[owner[i]].parent_nodes.push_back(i);
    }
    for(unsigned o=0;o<asset.bonds.size();++o) {
        const auto &b=asset.bonds[o];
        if(owner[b.node_a]==owner[b.node_b])out.components[owner[b.node_a]].parent_bonds.push_back(o);
        else out.severed_interfaces.push_back(archive(o,order,s));
    }
    for(auto &part:out.components) {
        auto &a=part.asset;a.recipe=asset.recipe;
        std::vector<unsigned> local(s.node_count,std::numeric_limits<unsigned>::max());
        for(unsigned i=0;i<part.parent_nodes.size();++i) {
            const auto p=part.parent_nodes[i];local[p]=i;a.nodes.push_back(asset.nodes[p]);
            a.total_mass_kg+=s.mass[p];a.represented_volume_m3+=asset.nodes[p].represented_volume_m3;
            a.rest_center_of_mass_m+=s.mass[p]*asset.nodes[p].local_position_m;
            part.attached_to_boundary=part.attached_to_boundary||s.inv_mass[p]==0;
        }
        a.rest_center_of_mass_m=a.rest_center_of_mass_m/a.total_mass_kg;
        for(const auto p:part.parent_nodes) {
            const auto arm=asset.nodes[p].local_position_m-a.rest_center_of_mass_m;
            const double r[3]{arm.x,arm.y,arm.z};
            for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)
                a.rest_inertia_kg_m2.m[i][j]+=s.mass[p]*((i==j?dot(arm,arm):0)-r[i]*r[j]);
        }
        if(!finite(a.rest_center_of_mass_m))throw std::invalid_argument("constituent rest centroid overflow");
        for(const auto &row:a.rest_inertia_kg_m2.m)for(const auto value:row)
            if(!std::isfinite(value))throw std::invalid_argument("constituent rest inertia overflow");
        for(const auto original:part.parent_bonds) {
            auto b=asset.bonds[original];b.node_a=local[b.node_a];b.node_b=local[b.node_b];a.bonds.push_back(b);
        }
        adjacency(a);part.schedule=buildLatticeSchedule(a);
        ActiveMatter matter;matter.asset=&a;matter.nodes.resize(a.nodes.size());matter.bonds.resize(a.bonds.size());
        for(const auto p:part.parent_nodes) {
            const Vec3 reference=s.origin+at(s.x0,p);matter.reference_positions_world_m.push_back(reference);
            matter.nodes[local[p]]={reference+at(s.u,p),reference+at(s.u_prev,p),at(s.v,p),s.mass[p],{}};
        }
        auto &d=part.state;d=buildLatticeState(matter,part.schedule,s.origin);
        // Copy canonical scalars, rather than subtracting a world-space origin
        // again (which can round away a small displacement on a distant map).
        for(unsigned i=0;i<part.parent_nodes.size();++i) {
            const auto p=part.parent_nodes[i];
            for(unsigned j=0;j<3;++j) {d.x0[3*i+j]=s.x0[3*p+j];d.u[3*i+j]=s.u[3*p+j];d.u_prev[3*i+j]=s.u_prev[3*p+j];d.v[3*i+j]=s.v[3*p+j];}
            d.mass[i]=s.mass[p];d.inv_mass[i]=s.inv_mass[p];
        }
        for(unsigned o=0;o<part.parent_bonds.size();++o) {
            const auto from=order.bond_schedule_index[part.parent_bonds[o]],to=part.schedule.bond_schedule_index[o];
            d.rest_length[to]=s.rest_length[from];d.rest_length_sq_minus[to]=s.rest_length_sq_minus[from];
            d.weight[to]=s.weight[from];d.compliance[to]=s.compliance[from];d.alive[to]=s.alive[from];
            d.failure_mode[to]=s.failure_mode[from];d.damage[to]=s.damage[from];
            d.prev_tensile[to]=s.prev_tensile[from];d.prev_compressive[to]=s.prev_compressive[from];d.prev_shear[to]=s.prev_shear[from];
            d.plastic_extension[to]=s.plastic_extension[from];d.plastic_strain[to]=s.plastic_strain[from];
            for(unsigned j=0;j<3;++j)d.rest_edge[3*to+j]=s.rest_edge[3*from+j];
            for(unsigned j=0;j<6;++j)d.threshold[6*to+j]=s.threshold[6*from+j];
            for(const auto slot:{d.bond_slot_a[to],d.bond_slot_b[to]}) {
                const double sign=d.nbr_other[slot]==d.bond_b[to]?1:-1;
                for(unsigned j=0;j<3;++j)d.nbr_rest[3*slot+j]=sign*d.rest_edge[3*to+j];
                d.nbr_weight[slot]=d.weight[to];d.nbr_alive[slot]=d.alive[to];
            }
        }
    }
    return out;
}
} // namespace banjo::fastlattice
