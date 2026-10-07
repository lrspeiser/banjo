#include "fastlattice/ConstituentPartition.hpp"
#include "fastlattice/SolidMatterPatch.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"
#include <algorithm>
#include <cmath>
#include <chrono>
#include <iostream>
#include <limits>
#include <set>
#include <stdexcept>

namespace {
using namespace banjo;using namespace banjo::fastlattice;
void require(bool x,const char *why){if(!x)throw std::runtime_error(why);}
void near(double x,double y,double tolerance,const char *why){require(std::isfinite(x)&&std::abs(x-y)<=tolerance,why);}
Vec3 at(const std::vector<double> &v,unsigned i){return {v[3*i],v[3*i+1],v[3*i+2]};}
void exactPartition(const LatticeAsset &asset,const LatticeSchedule &order,const LatticeState &s,const ConstituentPartition &p) {
    std::set<unsigned> nodes,bonds;double mass=0,volume=0,kinetic=0,elastic=0;Vec3 momentum{},angular{};
    for(const auto &c:p.components) {
        const auto &d=c.state;require(d.node_count==c.parent_nodes.size()&&d.bond_count==c.parent_bonds.size(),"partition maps incomplete");
        bool attached=false;
        for(unsigned i=0;i<c.parent_nodes.size();++i) {
            const auto old=c.parent_nodes[i];require(nodes.insert(old).second,"constituent copied to two components");
            require(c.asset.nodes[i].grid==asset.nodes[old].grid&&c.asset.nodes[i].represented_volume_m3==asset.nodes[old].represented_volume_m3,
                "partition changed source cell identity or volume");
            for(unsigned axis=0;axis<3;++axis)
                require(d.x0[3*i+axis]==s.x0[3*old+axis]&&d.u[3*i+axis]==s.u[3*old+axis]&&
                    d.u_prev[3*i+axis]==s.u_prev[3*old+axis]&&d.v[3*i+axis]==s.v[3*old+axis],"partition rounded/reset physical state");
            require(d.mass[i]==s.mass[old]&&d.inv_mass[i]==s.inv_mass[old],"partition changed material mass or clamp");
            attached=attached||d.inv_mass[i]==0;mass+=d.mass[i];volume+=c.asset.nodes[i].represented_volume_m3;
            const Vec3 impulse=d.mass[i]*at(d.v,i);momentum+=impulse;angular+=cross(d.origin+at(d.x0,i)+at(d.u,i),impulse);
        }
        require(attached==c.attached_to_boundary,"partition lost attachment");
        for(unsigned o=0;o<c.parent_bonds.size();++o) {
            const auto original=c.parent_bonds[o];require(bonds.insert(original).second,"bond duplicated across partitions");
            const auto from=order.bond_schedule_index[original],to=c.schedule.bond_schedule_index[o];
            require(c.parent_nodes[d.bond_a[to]]==s.bond_a[from]&&c.parent_nodes[d.bond_b[to]]==s.bond_b[from],"bond endpoints changed");
            for(const auto pair:{std::pair{&d.rest_length,&s.rest_length},std::pair{&d.rest_length_sq_minus,&s.rest_length_sq_minus},
                std::pair{&d.weight,&s.weight},std::pair{&d.compliance,&s.compliance},std::pair{&d.damage,&s.damage},
                std::pair{&d.prev_tensile,&s.prev_tensile},std::pair{&d.prev_compressive,&s.prev_compressive},std::pair{&d.prev_shear,&s.prev_shear},
                std::pair{&d.plastic_extension,&s.plastic_extension},std::pair{&d.plastic_strain,&s.plastic_strain}})
                require((*pair.first)[to]==(*pair.second)[from],"partition erased constitutive history");
            require(d.alive[to]==s.alive[from]&&d.failure_mode[to]==s.failure_mode[from],"partition healed a failed bond");
            for(unsigned axis=0;axis<3;++axis)require(d.rest_edge[3*to+axis]==s.rest_edge[3*from+axis],"partition transformed material reference");
            for(unsigned axis=0;axis<6;++axis)require(d.threshold[6*to+axis]==s.threshold[6*from+axis],"partition recompiled strengths");
        }
        kinetic+=latticeStateKineticEnergy(d);elastic+=latticeStateElasticEnergy(d);
    }
    for(const auto &b:p.severed_interfaces) {
        require(bonds.insert(b.parent_bond).second,"severed interface duplicated");const auto k=order.bond_schedule_index[b.parent_bond];
        require(!s.alive[k]&&b.parent_node_a==s.bond_a[k]&&b.parent_node_b==s.bond_b[k]&&b.damage==s.damage[k]&&
            b.plastic_extension_m==s.plastic_extension[k]&&b.plastic_strain_m==s.plastic_strain[k]&&b.failure_mode==s.failure_mode[k],
            "crossing interface was live or lost history");
        require(b.previous_tensile==s.prev_tensile[k]&&b.previous_compressive==s.prev_compressive[k]&&b.previous_shear==s.prev_shear[k],"severed interface lost prior samples");
        require(b.rest_length_m==s.rest_length[k]&&b.rest_length_sq_minus_m2==s.rest_length_sq_minus[k]&&
            b.weight==s.weight[k]&&b.compliance==s.compliance[k],"severed interface lost material constants");
        const double edge[3]{b.rest_edge_m.x,b.rest_edge_m.y,b.rest_edge_m.z};
        for(unsigned axis=0;axis<3;++axis)require(edge[axis]==s.rest_edge[3*k+axis],"severed reference edge changed");
        for(unsigned axis=0;axis<6;++axis)require(b.thresholds[axis]==s.threshold[6*k+axis],"severed strengths changed");
    }
    require(nodes.size()==s.node_count&&bonds.size()==s.bond_count,"source cells or bond archives disappeared");
    double source_mass=0;Vec3 source_p{},source_l{};
    for(unsigned i=0;i<s.node_count;++i) {source_mass+=s.mass[i];source_p+=s.mass[i]*at(s.v,i);source_l+=cross(s.origin+at(s.x0,i)+at(s.u,i),s.mass[i]*at(s.v,i));}
    near(mass,source_mass,1e-10,"partition total mass");near(volume,asset.represented_volume_m3,1e-12,"partition volume");
    near(kinetic,latticeStateKineticEnergy(s),1e-9,"partition lost deformation kinetic energy");
    near(elastic,latticeStateElasticEnergy(s),1e-9,"partition lost elastic energy");
    near(length(momentum-source_p),0,1e-10,"partition linear momentum");near(length(angular-source_l),0,1e-9,"partition angular momentum");
}
void ownedPhysicalTransfer() {
    std::vector<unsigned> fixed;
    for(unsigned z=0;z<5;++z)for(unsigned x=0;x<5;++x)fixed.push_back(x+25*z);
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto material=makeReferenceMaterial(preset,17);
        SolidMatterPatch patch("terrain:0:0:0",{.25,.25,.25},.05,material,{2,.6,-1},.1,1e-7,fixed);
        SolidMatterPatch control("terrain:0:0:0",{.25,.25,.25},.05,material,{2,.6,-1},.1,1e-7,fixed);
        std::vector<Vec3> pull(125);pull[2+5*(4+5*2)]={0,1e6,0};
        patch.pulse(pull,512,50000);control.pulse(pull,512,50000);
        const auto before=patch.report();const auto snapshot=patch.state();
        const auto prepared=partitionConstituents(patch.asset(),patch.schedule(),snapshot);
        exactPartition(patch.asset(),patch.schedule(),snapshot,prepared);
        require(patch.state().u==snapshot.u&&patch.ownsConstituents(),"read-only preparation consumed or moved source");
        const auto started=std::chrono::steady_clock::now();
        auto transfer=patch.transferToComponents();
        const double transfer_wall_s=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
        require(!patch.ownsConstituents()&&!patch.report().owns_constituents,"old material solver still owns transferred cells");
        bool refused=false;try{patch.pulse(pull,1,1);}catch(const std::logic_error &){refused=true;}
        require(refused,"retired material stepped twice");
        refused=false;try{(void)patch.transferToComponents();}catch(const std::logic_error &){refused=true;}
        require(refused,"material transferred twice");
        require(transfer.before.source_work_j==before.source_work_j&&transfer.before.positive_source_work_j==before.positive_source_work_j,
            "ownership transfer refunded prior work");
        double mass=0,volume=0,kinetic=0,elastic=0;std::set<unsigned> ids;
        bool attached=false,free=false;
        // Retain the one parent receipt and add only post-transfer accounts.
        // Inherited K/U/P/L are baselines, not a second supply of work/impulse.
        double after_k=0,after_u=0,removed=before.removed_bond_energy_j,work=before.source_work_j,error=before.integration_error_j;
        Vec3 after_p{},after_l{},source_p=before.source_impulse_n_s,source_l=before.source_angular_impulse_kg_m2_s;
        Vec3 support_p=before.boundary_impulse_n_s,support_l=before.boundary_angular_impulse_kg_m2_s;
        Vec3 roundoff_p=before.bond_roundoff_impulse_n_s,roundoff_l=before.bond_roundoff_angular_kg_m2_s;
        for(auto &child:transfer.components) {
            const auto r=child->report();require(r.accepted_steps==before.accepted_steps&&r.time_s==before.time_s,"transfer restarted accepted clock");
            near(r.initial_mechanical_j,r.kinetic_j+r.elastic_j,1e-10,"inherited energy counted as new source work");
            near(r.source_work_j,0,0,"prior work duplicated into child");near(r.energy_residual_j,0,1e-10,"activation energy balance");
            near(length(r.momentum_residual_kg_m_s),0,1e-10,"activation momentum balance");
            for(const auto id:child->sourceNodeIds())require(ids.insert(id).second,"ownership transfer duplicated source identity");
            mass+=r.mass_kg;volume+=r.volume_m3;kinetic+=r.kinetic_j;elastic+=r.elastic_j;
            attached=attached||child->components()[0].attached_to_boundary;free=free||!child->components()[0].attached_to_boundary;
            std::vector<Vec3> coast(child->state().node_count);child->pulse(coast,128,0);
            near(child->report().energy_residual_j,0,1e-8,"deformable continuation energy ledger");
            near(length(child->report().momentum_residual_kg_m_s),0,1e-9,"deformable continuation momentum ledger");
            const auto end=child->report();
            after_k+=end.kinetic_j;after_u+=end.elastic_j;removed+=end.removed_bond_energy_j;work+=end.source_work_j;error+=end.integration_error_j;
            after_p+=end.momentum_kg_m_s;after_l+=end.angular_momentum_kg_m2_s;
            source_p+=end.source_impulse_n_s;source_l+=end.source_angular_impulse_kg_m2_s;
            support_p+=end.boundary_impulse_n_s;support_l+=end.boundary_angular_impulse_kg_m2_s;
            roundoff_p+=end.bond_roundoff_impulse_n_s;roundoff_l+=end.bond_roundoff_angular_kg_m2_s;
        }
        near(mass,before.mass_kg,1e-10,"owned transfer mass");near(volume,before.volume_m3,1e-12,"owned transfer volume");
        near(kinetic,before.kinetic_j,1e-9,"owned transfer kinetic");near(elastic,before.elastic_j,1e-9,"owned transfer elastic");
        require(ids.size()==125&&attached,"ownership transfer removed attached material");
        if(preset==MaterialPreset::Glass)require(free&&transfer.components.size()>1,"actual glass failure did not transfer free component");
        std::vector<Vec3> zero(125);control.pulse(zero,128,0);double maximum_position_error=0,maximum_velocity_error=0;
        const double energy_residual=after_k+after_u+removed-work-error;
        const double momentum_residual=length(after_p-source_p-support_p-roundoff_p);
        const double angular_residual=length(after_l-source_l-support_l-roundoff_l);
        near(energy_residual,0,1e-8,"past plus incremental energy ledger");
        near(momentum_residual,0,1e-9,"past plus incremental momentum ledger");
        near(angular_residual,0,1e-8,"past plus incremental angular ledger");
        near(removed,control.report().removed_bond_energy_j,1e-9,"split ledger lost or duplicated fracture energy");
        near(error,control.report().integration_error_j,1e-8,"split ledger lost integration correction");
        for(auto &child:transfer.components) {
            for(unsigned i=0;i<child->state().node_count;++i) {
                const auto p=child->sourceNodeIds()[i];
                maximum_position_error=std::max(maximum_position_error,length(at(child->state().u,i)-at(control.state().u,p)));
                maximum_velocity_error=std::max(maximum_velocity_error,length(at(child->state().v,i)-at(control.state().v,p)));
            }
            auto next=child->transferToComponents();
            for(const auto &grandchild:next.components)require(grandchild->report().accepted_steps==640,"nested transfer restarted time");
        }
        near(maximum_position_error,0,1e-10,"split continuation changed reference trajectory");
        near(maximum_velocity_error,0,1e-8,"split continuation reset material velocity");
        std::cout<<"TRANSFER_EVIDENCE material="<<materialPresetName(preset)<<" cells=125 steps=640 components="<<transfer.components.size()
            <<" dead_interfaces="<<transfer.severed_interfaces.size()<<" work_j="<<before.source_work_j<<" kinetic_j="<<before.kinetic_j
            <<" elastic_j="<<before.elastic_j<<" position_difference_m="<<maximum_position_error<<" velocity_difference_m_s="<<maximum_velocity_error
            <<" energy_residual_j="<<energy_residual<<" momentum_residual_n_s="<<momentum_residual<<" angular_residual_kg_m2_s="<<angular_residual
            <<" mass_kg="<<before.mass_kg<<" volume_m3="<<before.volume_m3<<" broken_bonds="<<before.broken_bonds
            <<" removed_energy_j="<<before.removed_bond_energy_j<<" integration_error_j="<<before.integration_error_j<<" transfer_wall_s="<<transfer_wall_s<<'\n';
    }
}
void exactPlasticHistoryAndInvalidInput() {
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto m=makeReferenceMaterial(preset,17);
        const auto material=withPlasticFlow(withStrengthDerivedFailure(compileElasticLatticeReference(m,.04,1),m),m);
        auto asset=generateBoxTileLattice({{.12,.12,.12},.04,1},material);ActiveMatter matter;matter.asset=&asset;matter.material=material;
        const Vec3 origin{1000000,2,-1000000};
        for(const auto &n:asset.nodes) {const auto p=origin+n.local_position_m;matter.nodes.push_back({p,p,{},n.represented_volume_m3*m.density_kg_m3,{}});matter.reference_positions_world_m.push_back(p);}
        matter.bonds.resize(asset.bonds.size());const auto order=buildLatticeSchedule(asset);auto state=buildLatticeState(matter,order,origin);
        StepSettings<double> settings{};settings.dt=1e-7;settings.bond_integrator=kBondVelocityVerlet;settings.audit_energy=1;
        settings.plastic_yield_stretch=material.yield_stretch;settings.plastic_hardening=material.plastic_hardening_ratio;
        auto backend=makeCpuLatticeBackend(order,Precision::Double);backend->upload(state,settings,{});
        std::vector<Vec3> force(27);force[26]={3e5,3e5,3e5};force[0]={-3e5,-3e5,-3e5};
        backend->setExternalForces(force,512);backend->run({.max_steps=512});SphereState<double> unused{};backend->download(state,unused);
        const auto p=partitionConstituents(asset,order,state);exactPartition(asset,order,state,p);
        if(preset==MaterialPreset::Iron)require(std::any_of(state.plastic_strain.begin(),state.plastic_strain.end(),[](double x){return x>0;}),
            "iron fixture never created real plastic history");
        // Resume both the intact canonical solver and each prepared component
        // under the exact same plastic law/settings. No fresh elastic preset,
        // rigid-motion fit or renewed force is used to make continuation pass.
        std::vector<std::unique_ptr<LatticeBackend>> children;
        for(const auto &part:p.components) {
            auto child=makeCpuLatticeBackend(part.schedule,Precision::Double);
            child->upload(part.state,settings,{});children.push_back(std::move(child));
        }
        backend->run({.max_steps=128});LatticeState control;backend->download(control,unused);
        double position_error=0,velocity_error=0,plastic_error=0;
        for(unsigned c=0;c<p.components.size();++c) {
            children[c]->run({.max_steps=128});LatticeState resumed;children[c]->download(resumed,unused);
            for(unsigned i=0;i<resumed.node_count;++i) {
                const auto old=p.components[c].parent_nodes[i];
                position_error=std::max(position_error,length(at(resumed.u,i)-at(control.u,old)));
                velocity_error=std::max(velocity_error,length(at(resumed.v,i)-at(control.v,old)));
            }
            for(unsigned o=0;o<p.components[c].parent_bonds.size();++o) {
                const auto k=p.components[c].schedule.bond_schedule_index[o],old=order.bond_schedule_index[p.components[c].parent_bonds[o]];
                plastic_error=std::max(plastic_error,std::abs(resumed.plastic_strain[k]-control.plastic_strain[old]));
                require(resumed.alive[k]==control.alive[old]&&resumed.failure_mode[k]==control.failure_mode[old],"resumed plastic failure differs");
            }
        }
        near(position_error,0,1e-10,"resumed plastic material trajectory");
        near(velocity_error,0,1e-8,"resumed plastic velocity");near(plastic_error,0,1e-12,"resumed plastic history");
        std::cout<<"PLASTIC_TRANSFER_EVIDENCE material="<<materialPresetName(preset)<<" cells=27 dt_s="<<settings.dt
            <<" steps=640 components="<<p.components.size()<<" max_plastic_strain="<<*std::max_element(state.plastic_strain.begin(),state.plastic_strain.end())
            <<" position_difference_m="<<position_error<<" velocity_difference_m_s="<<velocity_error<<" plastic_difference="<<plastic_error<<'\n';
        const auto rejects=[&](LatticeState bad,LatticeSchedule schedule= LatticeSchedule{}) {
            bool refused=false;try{(void)partitionConstituents(asset,schedule.bond_order.empty()?order:schedule,bad);}catch(const std::invalid_argument &){refused=true;}
            require(refused,"malformed material partition accepted");
        };
        auto bad=state;bad.plastic_strain.pop_back();rejects(bad);
        bad=state;bad.mass[0]=0;rejects(bad);
        bad=state;
        for(unsigned i=0;i<bad.node_count;++i){bad.mass[i]=1e308;bad.inv_mass[i]=1e-308;}rejects(bad);
        bad=state;bad.v[0]=1e300;rejects(bad);
        bad=state;bad.threshold[0]=std::numeric_limits<double>::quiet_NaN();rejects(bad);
        bad=state;bad.bond_a[0]=state.node_count;rejects(bad);
        auto malformed=order;malformed.bond_order[0]=malformed.bond_order[1];rejects(state,malformed);
    }
}
}
int main(){try{std::cout.precision(12);ownedPhysicalTransfer();exactPlasticHistoryAndInvalidInput();std::cout<<"[PASS] canonical constituent ownership and history transfer\n";}
catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
