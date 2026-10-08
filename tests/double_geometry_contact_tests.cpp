#include "fastlattice/DoubleFixedContact.hpp"
#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"
#include <algorithm>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

namespace {
using namespace banjo;using namespace banjo::fastlattice;
void require(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
void near(double x,double y,double tolerance,const char *why){if(!std::isfinite(x)||std::abs(x-y)>tolerance){
    std::cerr<<why<<": "<<x<<" vs "<<y<<" tolerance "<<tolerance<<'\n';throw std::runtime_error(why);}}
template<class F>void rejects(F f){bool caught=false;try{f();}catch(const std::exception&){caught=true;}require(caught,"expected atomic refusal");}
bool same(const DoubleFixedSource &a,const DoubleFixedSource &b){const auto &x=a.state(),&y=b.state();const auto p=x.orientation_world,q=y.orientation_world;
    return a.steps()==b.steps()&&a.elapsedTime()==b.elapsedTime()&&x.mass_kg==y.mass_kg&&x.inertia_body_kg_m2.m==y.inertia_body_kg_m2.m&&
        length(x.center_world_m-y.center_world_m)==0&&length(x.velocity_world_m_s-y.velocity_world_m_s)==0&&
        length(x.spin_momentum_world_kg_m2_s-y.spin_momentum_world_kg_m2_s)==0&&p.w==q.w&&p.x==q.x&&p.y==q.y&&p.z==q.z;}
struct PhaseProbe {
    unsigned witnesses{},restitution_candidates{},active{},iterations{};
    double minimum_vn{std::numeric_limits<double>::infinity()},maximum_vn{-std::numeric_limits<double>::infinity()};
    double minimum_gap{std::numeric_limits<double>::infinity()},maximum_gap{-std::numeric_limits<double>::infinity()};
    double target_work{},loss{},source_work{};
    double before_force_vn_min{std::numeric_limits<double>::infinity()},before_force_vn_max{-std::numeric_limits<double>::infinity()};
};
struct Fixture {
    JoltWorld geometry;
    MaterialShapeBinding head,handle;
    MaterialDefinition material;
    LatticeAsset asset;LatticeSchedule schedule;LatticeState initial;StepSettings<double> settings{};
    Fixture(MaterialPreset preset,double width):material(makeReferenceMaterial(preset,17)) {
        geometry.setGravity({});const auto iron=makeReferenceMaterial(MaterialPreset::Iron,17),oak=makeReferenceMaterial(MaterialPreset::Oak,17);
        // Native bodies supply only actual geometry and accepted mass/inertia.
        // The declared ideal CPU fixing is not a snapped native joint import.
        geometry.addBox({1,{.08,width,.08},iron,{{},{},{6,.2,.1},{}},false});
        geometry.addBox({10,{.24,.04,.04},oak,{{-.16,0,0},{},{6,.2,.1},{}},false});
        head=geometry.bindMaterialShape(1);handle=geometry.bindMaterialShape(10);
        const auto law=withPlasticFlow(withStrengthDerivedFailure(compileElasticLatticeReference(material,.04,1),material),material);
        asset=generateBoxTileLattice({{.12,.12,.12},.04,1},law);ActiveMatter matter;matter.asset=&asset;matter.material=law;
        for(const auto &n:asset.nodes){const auto p=n.local_position_m+Vec3{.1,0,0};
            matter.nodes.push_back({p,p,{},n.represented_volume_m3*material.density_kg_m3,{}});matter.reference_positions_world_m.push_back(p);}
        matter.bonds.resize(asset.bonds.size());schedule=buildLatticeSchedule(asset);initial=buildLatticeState(matter,schedule,{.1,0,0});
        for(unsigned i=0;i<initial.node_count;++i)if(initial.x0[3*i]>.039)initial.inv_mass[i]=0;
        settings.dt=1e-7;settings.audit_energy=1;settings.bond_integrator=kBondVelocityVerlet;
        settings.plastic_yield_stretch=law.yield_stretch;settings.plastic_hardening=law.plastic_hardening_ratio;
    }
    DoubleFixedSource source()const{return DoubleFixedSource({geometry.mechanicalState(1),geometry.mechanicalState(10)},{{0,1,{-.04,0,0},{-.04,0,0}}});}
    std::unique_ptr<LatticeBackend> backend()const{auto b=makeCpuLatticeBackend(schedule,Precision::Double);b->upload(initial,settings,{});return b;}
    LatticeState download(LatticeBackend &b)const{auto state=initial;SphereState<double> sphere;b.download(state,sphere);return state;}
    DoubleFixedManifoldTransfer contact(DoubleFixedSource &source,LatticeBackend &target,PhaseProbe *probe=nullptr)const{
        const auto state=download(target);const auto bodies=source.bodies();std::vector<MaterialSurfaceWitness> witnesses;
        const RigidPrimitive cell{PrimitiveKind::Box,0,{.04,.04,.04}};const auto patch=MaterialContactGeometry::ClippedFace;
        for(unsigned i=0;i<state.node_count;++i){const auto at=state.origin+Vec3{state.x0[3*i]+state.u[3*i],state.x0[3*i+1]+state.u[3*i+1],state.x0[3*i+2]+state.u[3*i+2]};
            const auto &h=bodies[1].motion;
            require(geometry.materialShapeContactsAtPose(handle,{h.center_of_mass_world_m,h.orientation_world},at,cell,{},1e-5,64,patch).contacts.empty(),"fixture omitted handle contact");
            const auto &p=bodies[0].motion;
            const auto hits=geometry.materialShapeContactsAtPose(head,{p.center_of_mass_world_m,p.orientation_world},at,cell,{},1e-5,64,patch).contacts;
            if(state.inv_mass[i]==0){require(hits.empty(),"fixture omitted direct clamp contact");continue;}
            for(const auto &hit:hits){const auto law=combineContactMaterials(compileContactMaterial(material),hit.body_contact);
                witnesses.push_back({i,hit.point_on_body_world_m,hit.normal_world,hit.gap_m,{law.static_friction,law.dynamic_friction,law.restitution}});}
        }
        if(probe){probe->witnesses=static_cast<unsigned>(witnesses.size());
            for(const auto &w:witnesses){const auto region=target.externalContactRegion(w.seed,{.12,3,64,4096});
                std::vector<ActiveNodeState> support;for(const auto id:region.nodes)support.push_back(target.externalContactPoint(id));
                const auto stencil=makeMaterialContactStencil(support,w.surface_world_m);
                const auto &body=bodies[0].motion;
                const auto relative=stencil.point.velocity_m_s-body.linear_velocity_m_s-
                    cross(body.angular_velocity_rad_s,w.surface_world_m-body.center_of_mass_world_m);
                const auto vn=dot(relative,w.normal_world);
                for(std::size_t i=0;i<region.nodes.size();++i)support[i].velocity_m_s=target.externalContactForceStartPoint(region.nodes[i]).velocity_m_s;
                const auto start=makeMaterialContactStencil(support,w.surface_world_m);
                const auto before_vn=dot(start.point.velocity_m_s-body.linear_velocity_m_s-
                    cross(body.angular_velocity_rad_s,w.surface_world_m-body.center_of_mass_world_m),w.normal_world);
                probe->before_force_vn_min=std::min(probe->before_force_vn_min,before_vn);probe->before_force_vn_max=std::max(probe->before_force_vn_max,before_vn);
                probe->minimum_vn=std::min(probe->minimum_vn,vn);probe->maximum_vn=std::max(probe->maximum_vn,vn);
                probe->minimum_gap=std::min(probe->minimum_gap,w.gap_m);probe->maximum_gap=std::max(probe->maximum_gap,w.gap_m);
                if(-vn>w.settings.restitution_speed_threshold_m_s)++probe->restitution_candidates;}}
        auto out=applyDoubleFixedLocalSurfaceManifold(source,target,witnesses,{.12,3,64,4096},0);
        if(probe){probe->active=out.contact.active_contacts;probe->iterations=out.contact.iterations;
            probe->target_work=out.target.work_j;probe->loss=out.contact.dissipated_energy_j;probe->source_work=out.source_work_j;}
        return out;
    }
};
MechanicalTotals totals(const DoubleFixedSource &source,const LatticeState &s){MechanicalTotals out;
    for(const auto &b:source.bodies())out+=measureRigidMechanics(b);
    out.kinetic_energy_j+=latticeStateKineticEnergy(s);out.elastic_energy_j+=latticeStateElasticEnergy(s);
    for(unsigned i=0;i<s.node_count;++i){const auto p=s.origin+Vec3{s.x0[3*i]+s.u[3*i],s.x0[3*i+1]+s.u[3*i+1],s.x0[3*i+2]+s.u[3*i+2]};
        const auto j=s.mass[i]*Vec3{s.v[3*i],s.v[3*i+1],s.v[3*i+2]};out.mass_kg+=s.mass[i];out.linear_momentum_kg_m_s+=j;out.angular_momentum_kg_m2_s+=cross(p,j);}
    return out;
}
struct Accounts {double loss{},source_roundoff{},drift{},source_work{};Vec3 contact_p{},contact_l{},couple{},drift_p{},drift_l{},load_p{},load_l{};
    void add(const DoubleContactStepAudit &r){loss+=r.contact_loss_j+r.reconciliation_loss_j;source_roundoff+=r.source_roundoff_energy_j;drift+=r.source_drift_energy_j;source_work+=r.source_load_work_j;
        contact_p+=r.contact_impulse_residual_n_s;contact_l+=r.contact_angular_residual_kg_m2_s;couple+=r.geometry_couple_kg_m2_s;
        drift_p+=r.drift_impulse_residual_n_s;drift_l+=r.drift_angular_residual_kg_m2_s;load_p+=r.source_load_impulse_n_s;load_l+=r.source_load_angular_kg_m2_s;}
};
void controllerOracles(){
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        Fixture f(preset,.04);auto source=f.source(),saved=source;auto target=f.backend();ContactAccuracySettings bounds;
        const auto callback=[&](double){return f.contact(source,*target);};
        for(unsigned fault=1;fault<=6;++fault){unsigned calls=0;rejects([&]{(void)advanceDoubleFixedTargetControlled(source,*target,1e-7,bounds,[&](double dt){
            auto result=callback(dt);if(++calls==fault)throw std::runtime_error("injected geometry/contact failure");return result;});});
            require(same(source,saved)&&target->status().total_steps==0&&target->status().external_point_transfer.transfers==0,"full/fine exception leaked source/target state");
            require(f.download(*target).u==f.initial.u&&f.download(*target).damage==f.initial.damage,"exception leaked material state/history");}
        auto invalid=bounds;invalid.energy_j=0;rejects([&]{(void)advanceDoubleFixedTargetControlled(source,*target,1e-7,invalid,callback);});
        invalid=bounds;invalid.maximum_halvings=21;rejects([&]{(void)advanceDoubleFixedTargetControlled(source,*target,1e-7,invalid,callback);});
        const auto accepted=advanceDoubleFixedTargetControlled(source,*target,1e-7,bounds,callback);
        require(accepted.accepted&&accepted.topology_agrees&&accepted.normalized_error<=1&&accepted.accepted_audit.active_manifolds>0,"real-query initial controlled impact refused");
        require(source.steps()==2&&target->status().total_steps==2,"controller committed trial/full steps instead of two half steps");
        near(source.elapsedTime(),accepted.accepted_interval_s,0,"source accepted elapsed time");
        near(target->externalContactElapsedTime(),accepted.accepted_interval_s,0,"target accepted elapsed time");
        require(f.geometry.stepCount()==0,"CPU coupling advanced native dynamics");
        rejects([&]{(void)target->externalContactForceStartPoint(0);});
        rejects([&]{(void)target->externalContactForceMovableNodes();});
        near(accepted.accepted_audit.force_phases.energy_residual_j,0,1e-10,"actual force/contact work closure");
        near(accepted.accepted_audit.force_phases.cross_work_residual_j,0,1e-10,"actual force/contact cross-work closure");
        near(length(accepted.accepted_audit.force_phases.momentum_residual_n_s),0,1e-9,"actual force/contact impulse closure");
        near(length(accepted.accepted_audit.force_phases.angular_residual_kg_m2_s),0,1e-9,"actual force/contact torque closure");
        std::cout<<"DOUBLE_GEOMETRY_ORACLE material="<<materialPresetName(preset)<<" dt_s="<<accepted.accepted_interval_s<<" error="<<accepted.normalized_error<<" native_steps=0\n";
    }
    // Actual external wrench work also participates in full/half accuracy.
    Fixture f(MaterialPreset::Iron,.04);auto source=f.source(),saved=source;auto target=f.backend();ContactAccuracySettings bounds;
    const DoubleSourceWrench wrench{1,{.01,.02,0},{1,2,3},{.003,.002,.001}};
    const auto empty=[&](double){return applyDoubleFixedLocalSurfaceManifold(source,*target,{}, {.12,3,64,4096},0);};
    auto strict=bounds;strict.maximum_halvings=0;strict.energy_j=1e-30;strict.angular_velocity_rad_s=1e-30;
    const auto refused=advanceDoubleFixedTargetControlled(source,*target,1e-7,strict,empty,std::span(&wrench,1));
    require(!refused.accepted&&refused.normalized_error>1&&same(source,saved)&&target->status().total_steps==0,"accuracy refusal did not restore paired state");
    const auto loaded=advanceDoubleFixedTargetControlled(source,*target,1e-7,bounds,empty,std::span(&wrench,1));
    require(loaded.accepted&&loaded.accepted_audit.source_load_work_j!=0&&loaded.accepted_audit.fixing_reactions.size()==1,"controlled external load lost work/fixing audit");
    // Failed before compensated source time: hundreds of variable intervals
    // accumulate more than the retained absolute-clock agreement bound.
    source=f.source();target=f.backend();long double expected=0;
    for(unsigned i=0;i<1024;++i){const double dt=i%3==0?1e-7:(i%3==1?5e-8:2.5e-8);
        const auto accepted=advanceDoubleFixedTargetControlled(source,*target,dt,bounds,empty);
        require(accepted.accepted&&source.elapsedTime()==target->externalContactElapsedTime(),"variable accepted clocks drifted apart");
        expected+=static_cast<long double>(dt);}
    near(source.elapsedTime(),static_cast<double>(expected),1e-18,"compensated physical duration");
    require(source.steps()==2048&&target->status().total_steps==2048,"clock oracle lost accepted substeps");
    std::cout<<"DOUBLE_ACCEPTED_CLOCK variable_intervals=1024 source_steps="<<source.steps()<<" elapsed_s="<<source.elapsedTime()<<" exact_paired_agreement=pass\n";
}
unsigned runMatched(unsigned limit,bool sustained,bool probe=false){unsigned open=0;
    for(double width:{.04,.12})for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        Fixture f(preset,width);auto source=f.source();auto target=f.backend();const auto initial=totals(source,f.initial);Accounts sum;
        ContactAccuracySettings bounds;bounds.maximum_halvings=20;double proposal=1e-7;constexpr double duration=2048e-7;
        unsigned accepted=0,rejected=0;std::string refusal,metric;double error=0;const auto started=std::chrono::steady_clock::now();
        while(accepted<limit&&target->externalContactElapsedTime()<duration-1e-18){
            try{const auto result=advanceDoubleFixedTargetControlled(source,*target,std::min(proposal,duration-target->externalContactElapsedTime()),bounds,[&](double){return f.contact(source,*target);});
                error=result.normalized_error;metric=result.error_metric;rejected+=result.rejected_intervals;
                if(!result.accepted){refusal="accuracy bound or minimum timestep";break;}sum.add(result.accepted_audit);++accepted;proposal=result.suggested_interval_s;
            }catch(const std::exception &e){refusal=e.what();break;}
        }
        const auto end=f.download(*target);const auto final=totals(source,end);const auto &status=target->status();
        const double p=length(final.linear_momentum_kg_m_s-initial.linear_momentum_kg_m_s-status.fixed_boundary.impulse_n_s-
            status.bond_kick_roundoff_impulse_n_s-sum.contact_p-sum.drift_p-sum.load_p-status.gravity_load.impulse_n_s-status.external_load.impulse_n_s);
        const double l=length(final.angular_momentum_kg_m2_s-initial.angular_momentum_kg_m2_s-status.fixed_boundary.angular_impulse_kg_m2_s-
            status.bond_kick_roundoff_angular_kg_m2_s-sum.contact_l-sum.couple-sum.drift_l-sum.load_l-status.gravity_load.angular_impulse_kg_m2_s-status.external_load.angular_impulse_kg_m2_s);
        const double e=final.mechanicalEnergy()-initial.mechanicalEnergy()+sum.loss+status.removed_energy_j+status.plastic_work_j+
            status.plastic_return_numerical_loss_j+status.damping_dissipated_j-sum.source_roundoff-sum.drift-sum.source_work-
            status.integration_numerical_energy_j-status.gravity_load.work_j-status.external_load.work_j;
        near(p,0,1e-9,"matched whole-system linear attribution");near(l,0,1e-9,"matched whole-system angular attribution");near(e,0,1e-10,"matched whole-system energy attribution");
        near(final.mass_kg,initial.mass_kg,1e-12,"matched material mass changed");require(f.geometry.stepCount()==0,"geometry-only native world advanced");
        const bool passed=sustained?target->externalContactElapsedTime()>=duration-1e-18&&status.broken_bonds>0:accepted==limit&&refusal.empty();if(!passed)++open;
        std::cout<<"DOUBLE_GEOMETRY_CASE {\"material\":\""<<materialPresetName(preset)<<"\",\"width_m\":"<<width<<",\"cell_m\":0.04,\"proposal_s\":1e-7,\"required_duration_s\":"<<duration
            <<",\"accepted_intervals\":"<<accepted<<",\"rejected_intervals\":"<<rejected<<",\"elapsed_s\":"<<target->externalContactElapsedTime()<<",\"broken_bonds\":"<<status.broken_bonds
            <<",\"passed\":"<<(passed?"true":"false")<<",\"normalized_error\":"<<error<<",\"worst_metric\":\""<<metric<<"\",\"refusal\":\""<<refusal
            <<"\",\"attributed_energy_j\":"<<e<<",\"attributed_momentum_n_s\":"<<p<<",\"attributed_angular_kg_m2_s\":"<<l<<",\"source_mass_kg\":"<<source.state().mass_kg
            <<",\"target_mass_kg\":"<<f.material.density_kg_m3*.12*.12*.12<<",\"wall_s\":"<<std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()<<"}\n"<<std::flush;
        if(probe){auto diagnostic=bounds;diagnostic.maximum_halvings=0;
            for(double dt:{1e-7,5e-8,2.5e-8,1.25e-8}){std::vector<PhaseProbe> phases;
                const auto at=target->externalContactElapsedTime();
                const auto result=advanceDoubleFixedTargetControlled(source,*target,dt,diagnostic,[&](double){
                    PhaseProbe phase;auto receipt=f.contact(source,*target,&phase);phases.push_back(phase);return receipt;});
                std::cout<<"DOUBLE_CONTACT_PROBE material="<<materialPresetName(preset)<<" width_m="<<width<<" start_s="<<at
                    <<" dt_s="<<dt<<" accepted="<<result.accepted<<" error="<<result.normalized_error<<" metric="<<result.error_metric
                    <<" full="<<result.error_full_value.x<<" fine="<<result.error_fine_value.x<<'\n';
                const auto &full=result.full_force_phases,&fine=result.fine_force_phases;
                std::cout<<"DOUBLE_FORCE_PHASE_WORK sequential_full_j="<<full.sequential_contact_work_j<<" sequential_fine_j="<<fine.sequential_contact_work_j
                    <<" simultaneous_full_j="<<full.simultaneous_contact_work_j<<" simultaneous_fine_j="<<fine.simultaneous_contact_work_j
                    <<" cross_full_j="<<full.contact_cross_work_j<<" cross_fine_j="<<fine.contact_cross_work_j
                    <<" kinetic_full_j="<<full.kinetic_change_j<<" kinetic_fine_j="<<fine.kinetic_change_j
                    <<" work_residual_full_j="<<full.energy_residual_j<<" work_residual_fine_j="<<fine.energy_residual_j<<'\n';
                for(std::size_t i=0;i<phases.size();++i){const auto &phase=phases[i];
                    std::cout<<"DOUBLE_CONTACT_PHASE index="<<i<<" witnesses="<<phase.witnesses<<" restitution_candidates="<<phase.restitution_candidates
                        <<" vn_min="<<phase.minimum_vn<<" vn_max="<<phase.maximum_vn<<" gap_min="<<phase.minimum_gap<<" gap_max="<<phase.maximum_gap
                        <<" before_force_vn_min="<<phase.before_force_vn_min<<" before_force_vn_max="<<phase.before_force_vn_max
                        <<" active="<<phase.active<<" iterations="<<phase.iterations<<" target_work_j="<<phase.target_work<<" source_work_j="<<phase.source_work
                        <<" loss_j="<<phase.loss<<'\n';}
                if(result.accepted)break;
            }std::cout<<std::flush;}
    }return open;
}
}
int main(int argc,char **argv){try{std::cout<<std::setprecision(17);bool sustained=false,probe=false;unsigned limit=1;
    if(argc!=1){require(argc==3&&(std::string(argv[1])=="--sustained"||std::string(argv[1])=="--probe"),"expected --sustained/--probe <interval-limit>");
        const std::string value=argv[2];require(!value.empty()&&value.size()<=6&&value.find_first_not_of("0123456789")==std::string::npos,"invalid interval limit");
        limit=static_cast<unsigned>(std::stoul(value));require(limit>0&&limit<=100000,"interval limit exceeds budget");sustained=true;probe=std::string(argv[1])=="--probe";}
    if(!sustained)controllerOracles();const auto open=runMatched(limit,sustained,probe);
    std::cout<<(open?"[OPEN] ":"[PASS] ")<<"CPU current-pose native geometry and paired material accuracy; open cases="<<open<<'\n';return open?1:0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
