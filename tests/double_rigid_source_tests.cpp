#include "fastlattice/DoubleFixedContact.hpp"
#include "core/RigidPrimitive.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
using namespace banjo;using namespace banjo::fastlattice;
void require(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
void near(double x,double y,double tolerance,const char *why){
    if(!std::isfinite(x)||std::abs(x-y)>tolerance){std::cerr<<why<<": "<<x<<" vs "<<y<<" bound "<<tolerance<<'\n';throw std::runtime_error(why);}}
template<class F>void rejects(F f,const char *why){bool caught=false;try{f();}catch(const std::exception &){caught=true;}require(caught,why);}
RigidMechanicalState box(Vec3 dimensions,double density,Vec3 center,Vec3 velocity={6,.2,.1},Vec3 omega={}){
    const RigidPrimitive primitive{PrimitiveKind::Box,0,dimensions};const double mass=density*primitive.volume();
    return {{center,{},velocity,omega},mass,primitive.inertia(mass)};
}
MechanicalTotals totals(const std::vector<RigidMechanicalState> &bodies){MechanicalTotals out;
    for(const auto &body:bodies)out+=measureRigidMechanics(body);return out;}
MechanicalTotals totals(const DoubleFixedSource &source,const LatticeState &s){
    auto out=totals(source.bodies());out.kinetic_energy_j+=latticeStateKineticEnergy(s);out.elastic_energy_j+=latticeStateElasticEnergy(s);
    for(unsigned i=0;i<s.node_count;++i){const Vec3 p=s.origin+Vec3{s.x0[3*i]+s.u[3*i],s.x0[3*i+1]+s.u[3*i+1],s.x0[3*i+2]+s.u[3*i+2]};
        const Vec3 j=s.mass[i]*Vec3{s.v[3*i],s.v[3*i+1],s.v[3*i+2]};out.mass_kg+=s.mass[i];
        out.linear_momentum_kg_m_s+=j;out.angular_momentum_kg_m2_s+=cross(p,j);}
    return out;
}
bool sameMotion(const DoubleFixedSource &a,const DoubleFixedSource &b){
    const auto &x=a.state(),&y=b.state();const auto p=x.orientation_world,q=y.orientation_world;
    return a.elapsedTime()==b.elapsedTime()&&a.steps()==b.steps()&&x.mass_kg==y.mass_kg&&x.inertia_body_kg_m2.m==y.inertia_body_kg_m2.m&&
        length(x.center_world_m-y.center_world_m)==0&&length(x.velocity_world_m_s-y.velocity_world_m_s)==0&&
        length(x.spin_momentum_world_kg_m2_s-y.spin_momentum_world_kg_m2_s)==0&&p.w==q.w&&p.x==q.x&&p.y==q.y&&p.z==q.z;
}
double qdistance(Quat a,Quat b){const double d=std::hypot(std::hypot(a.w-b.w,a.x-b.x),std::hypot(a.y-b.y,a.z-b.z));
    const double p=std::hypot(std::hypot(a.w+b.w,a.x+b.x),std::hypot(a.y+b.y,a.z+b.z));return std::min(d,p);}
void rotationOracles(){
    auto body=box({1,2,3},1,{2,-1,3},{.4,.3,-.2},{0,0,2});auto state=makeDoubleRigidState(body);
    const auto step=advanceDoubleRigidFree(state,.025);
    near(qdistance(step.state.orientation_world,{std::cos(.025),0,0,std::sin(.025)}),0,2e-16,"principal-axis exact rotation");
    near(length(step.state.center_world_m-(state.center_world_m+.025*state.velocity_world_m_s)),0,0,"exact free translation");
    near(length(step.angular_residual_kg_m2_s),0,2e-14,"free angular origin account");
    near(std::abs(step.numerical_energy_j),0,2e-14,"principal-axis free energy");
    auto tiny=state;tiny.spin_momentum_world_kg_m2_s={0,0,body.inertia_world_kg_m2.m[2][2]*1e-4};
    const auto micro=advanceDoubleRigidFree(tiny,1e-4);near(micro.state.orientation_world.z,5e-9,1e-24,"small rotation lost in angular dead zone");
    const auto back=advanceDoubleRigidFree(step.state,-.025);near(qdistance(back.state.orientation_world,state.orientation_world),0,2e-16,"free rotation reversal");
    const Quat offaxis{std::cos(.31),0,std::sin(.31),0};
    body.inertia_world_kg_m2=rotateInertia(body.inertia_world_kg_m2,offaxis);body.motion.angular_velocity_rad_s={2,3,4};
    state=makeDoubleRigidState(body);
    const auto integrate=[&](unsigned n){auto s=state;for(unsigned i=0;i<n;++i)s=advanceDoubleRigidFree(s,.2/n).state;return s;};
    const auto reference=integrate(3200);double last_error=0;
    for(unsigned n:{20U,40U,80U}){
        const auto s=integrate(n);const auto before=measureRigidMechanics(doubleRigidMechanics(state)),after=measureRigidMechanics(doubleRigidMechanics(s));
        const double error=qdistance(s.orientation_world,reference.orientation_world);
        if(last_error)require(last_error/error>3.8&&last_error/error<4.2,"anisotropic free rotation did not refine at second order");
        near(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s),0,1e-14,"anisotropic free momentum");
        near(length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s),0,2e-13,"anisotropic free angular momentum");
        const auto reversed=[&]{auto r=s;for(unsigned i=0;i<n;++i)r=advanceDoubleRigidFree(r,-.2/n).state;return r;}();
        near(qdistance(reversed.orientation_world,state.orientation_world),0,5e-14,"anisotropic Hamiltonian reversal");
        std::cout<<"ROTATION {\"steps\":"<<n<<",\"dt_s\":"<<.2/n<<",\"orientation_error\":"<<error
            <<",\"energy_error_j\":"<<after.kinetic_energy_j-before.kinetic_energy_j<<",\"angular_residual\":"
            <<length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s)<<"}\n";last_error=error;
    }
    auto bad=state;bad.orientation_world.w=2;rejects([&]{(void)advanceDoubleRigidFree(bad,.01);},"nonunit quaternion admitted");
    bad=state;bad.inertia_body_kg_m2.m[0][1]+=.1;rejects([&]{(void)advanceDoubleRigidFree(bad,.01);},"asymmetric physical tensor admitted");
    rejects([&]{(void)advanceDoubleRigidFree(state,std::numeric_limits<double>::quiet_NaN());},"nonfinite drift admitted");
    rejects([&]{(void)advanceDoubleRigidFree(state,2);},"unbounded drift admitted");
    auto fast=state;fast.spin_momentum_world_kg_m2_s*=1000;rejects([&]{(void)advanceDoubleRigidFree(fast,.1);},"large rotation omitted refinement");
}
DoubleFixedSource source(MaterialPreset preset,Vec3 omega={}){
    const auto material=makeReferenceMaterial(preset,17),oak=makeReferenceMaterial(MaterialPreset::Oak,17);
    const Vec3 v{6,.2,.1};const Vec3 a{},b{-.16,0,0};
    return {{box({.08,.08,.08},material.density_kg_m3,a,v+cross(omega,a),omega),
        box({.24,.04,.04},oak.density_kg_m3,b,v+cross(omega,b),omega)},{{0,1,{-.04,0,0},{-.04,0,0}}}};
}
void assemblyAndImpulseOracles(){
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        auto s=source(preset,{.2,.4,.8});const auto initial=totals(s.bodies());
        near(s.importAudit().loss_j,0,3e-14,"compatible source import dissipated energy");
        const Vec3 at{.04,.01,.02},j{-.1,.03,.04},k{0,.001,0};const auto receipt=s.applyImpulse(0,at,j,k);
        const auto after=totals(s.bodies());
        near(length(after.linear_momentum_kg_m_s-initial.linear_momentum_kg_m_s-j),0,2e-14,"actual member impulse account");
        near(length(after.angular_momentum_kg_m2_s-initial.angular_momentum_kg_m2_s-cross(at,j)-k),0,2e-14,"actual member torque account");
        near(after.kinetic_energy_j-initial.kinetic_energy_j,receipt.aggregate.work_j,4e-14,"actual assembly impulse work");
        near(receipt.fixing.work_j,0,2e-14,"compatible ideal fixing impulse work");
        require(length(receipt.fixing.reactions[0].impulse_on_b_n_s)>0,"loaded head omitted handle reaction");
        const auto r0=length(s.bodies()[0].motion.center_of_mass_world_m-s.bodies()[1].motion.center_of_mass_world_m);
        double numerical=0;for(unsigned i=0;i<1000;++i)numerical+=s.advanceFree(1e-4).numerical_energy_j;
        const auto end=totals(s.bodies());near(length(end.linear_momentum_kg_m_s-after.linear_momentum_kg_m_s),0,2e-14,"compound free momentum");
        near(length(end.angular_momentum_kg_m2_s-after.angular_momentum_kg_m2_s),0,2e-14,"compound free spin and orbital momentum");
        near(length(s.bodies()[0].motion.center_of_mass_world_m-s.bodies()[1].motion.center_of_mass_world_m),r0,2e-15,"fixed geometry stretched during drift");
        near(end.kinetic_energy_j-after.kinetic_energy_j,numerical,5e-13,"compound numerical drift energy account");
        auto broken=s.bodies();broken[0].mass_kg*=2;const auto saved=s;
        rejects([&]{s.adoptContact(broken);},"contact altered source mass");require(sameMotion(s,saved),"refused contact mutated source");
        broken=s.bodies();broken[0].motion.linear_velocity_m_s.x+=1;
        rejects([&]{s.adoptContact(broken);},"incompatible contact velocity admitted");require(sameMotion(s,saved),"refused incompatibility mutated source");
        rejects([&]{s.applyImpulse(8,at,j,k);},"invalid loaded member admitted");
        rejects([&]{s.advanceFree(0);},"zero-time source step admitted");
        auto links=s.links();links[0].point_b_world_m.x+=1e-9;
        rejects([&]{(void)DoubleFixedSource(s.bodies(),links);},"drifted fixing silently snapped on import");
        std::cout<<"ASSEMBLY {\"material\":\""<<materialPresetName(preset)<<"\",\"mass_kg\":"<<end.mass_kg
            <<",\"impulse_work_j\":"<<receipt.aggregate.work_j<<",\"fixing_work_j\":"<<receipt.fixing.work_j
            <<",\"free_numerical_energy_j\":"<<numerical<<",\"angular_residual\":"<<length(end.angular_momentum_kg_m2_s-after.angular_momentum_kg_m2_s)<<"}\n";
    }
    auto s=source(MaterialPreset::Glass);auto b=s.bodies();b[1].motion.linear_velocity_m_s={};
    DoubleFixedSource reconciled(b,s.links());require(reconciled.importAudit().loss_j>0,"relative import velocity loss unreported");
    near(totals(b).kinetic_energy_j-totals(reconciled.bodies()).kinetic_energy_j,reconciled.importAudit().loss_j,1e-13,"import reconciliation loss mismatch");
}
void gravityOracles(){
    const Vec3 gravity{0,-9.81,0};const double dt=.01;
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        auto s=source(preset);const auto initial=s.state();double work=0;
        const auto half=[&]{const auto members=s.bodies();for(unsigned i=0;i<members.size();++i){
            const auto r=s.applyImpulse(i,members[i].motion.center_of_mass_world_m,.5*dt*members[i].mass_kg*gravity);
            work+=r.aggregate.work_j;near(r.fixing.work_j,0,1e-12,"gravity fixing reaction did work");}};
        half();const auto drift=s.advanceFree(dt);half();
        near(length(s.state().center_world_m-initial.center_world_m-dt*initial.velocity_world_m_s-.5*dt*dt*gravity),0,2e-17,"compound analytical freefall position");
        near(length(s.state().velocity_world_m_s-initial.velocity_world_m_s-dt*gravity),0,2e-15,"compound analytical freefall velocity");
        near(length(s.state().spin_momentum_world_kg_m2_s),0,2e-17,"uniform gravity created intrinsic spin");
        const double expected=initial.mass_kg*(dt*dot(gravity,initial.velocity_world_m_s)+.5*dt*dt*lengthSquared(gravity));
        near(work,expected,2e-14,"analytical gravity work");near(drift.numerical_energy_j,0,2e-14,"gravity free drift numerical energy");
        std::cout<<"GRAVITY {\"material\":\""<<materialPresetName(preset)<<"\",\"dt_s\":"<<dt
            <<",\"mass_kg\":"<<initial.mass_kg<<",\"vertical_displacement_m\":"<<s.state().center_world_m.y-initial.center_world_m.y
            <<",\"work_j\":"<<work<<",\"expected_work_j\":"<<expected<<"}\n";
    }
}
struct Target {
    MaterialDefinition material;LatticeAsset asset;LatticeSchedule schedule;LatticeState state;StepSettings<double> settings{};
    explicit Target(MaterialPreset preset):material(makeReferenceMaterial(preset,17)){
        const auto law=withPlasticFlow(withStrengthDerivedFailure(compileElasticLatticeReference(material,.04,1),material),material);
        asset=generateBoxTileLattice({{.08,.08,.08},.04,1},law);ActiveMatter matter;matter.asset=&asset;matter.material=law;
        for(const auto &n:asset.nodes){const auto p=n.local_position_m+Vec3{.08,0,0};
            matter.nodes.push_back({p,p,{},n.represented_volume_m3*material.density_kg_m3,{}});matter.reference_positions_world_m.push_back(p);}
        matter.bonds.resize(asset.bonds.size());schedule=buildLatticeSchedule(asset);state=buildLatticeState(matter,schedule,{.08,0,0});
        settings.dt=1e-7;settings.audit_energy=1;settings.bond_integrator=kBondVelocityVerlet;
        settings.plastic_yield_stretch=law.yield_stretch;settings.plastic_hardening=law.plastic_hardening_ratio;
    }
    std::unique_ptr<LatticeBackend> backend(){auto b=makeCpuLatticeBackend(schedule,Precision::Double);b->upload(state,settings,{});return b;}
    LatticeState download(LatticeBackend &b){auto out=state;SphereState<double> sphere;b.download(out,sphere);return out;}
};
void coupledOracles(){
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(bool loaded:{false,true}){
        Target fixture(preset);if(loaded)fixture.settings.gravity={0,-9.81,0};
        auto target=fixture.backend();auto s=source(MaterialPreset::Iron);const auto initial=s;
        std::vector<DoubleSourceWrench> wrenches;
        if(loaded){const auto members=s.bodies();for(unsigned i=0;i<members.size();++i)
            wrenches.push_back({i,{},members[i].mass_kg*Vec3{0,-9.81,0},{}});
            wrenches.push_back({1,{.02,.01,0},{1,2,3},{0,.001,0}});}
        // A declared touching box face, recomputed from actual CPU source pose.
        // This is a short contact/clock/rollback fixture, not collision discovery
        // or a claim that the slab fractures or a live world now uses this lane.
        const auto contact=[&](double){const auto head=s.bodies()[0];const auto &pose=head.motion;
            const Vec3 normal=pose.orientation_world.rotate({1,0,0}),surface=pose.center_of_mass_world_m+pose.orientation_world.rotate({.04,.008,.012});
            const auto cell=target->externalContactPoint(0);
            const double gap=dot(cell.position_world_m-Vec3{.02,0,0}-surface,normal);
            const MaterialSurfaceWitness w{0,surface,normal,gap,{.2,.1,0}};
            return applyDoubleFixedLocalSurfaceManifold(s,*target,std::span(&w,1),{.16,3,64,4096},0);};
        auto malformed=[&](double dt){auto out=contact(dt);s.advanceFree(dt);return out;};
        rejects([&]{(void)advanceDoubleFixedTargetStep(s,*target,fixture.settings.dt,malformed,wrenches);},"callback source stepping admitted");
        require(sameMotion(s,initial)&&target->status().total_steps==0&&target->status().external_point_transfer.transfers==0,"callback refusal leaked source or target");
        for(unsigned phase:{0U,1U}){
            unsigned calls=0;rejects([&]{(void)advanceDoubleFixedTargetStep(s,*target,fixture.settings.dt,[&](double dt){
                auto out=contact(dt);if(calls++==phase)throw std::runtime_error("phase failure");return out;},wrenches);},"phase failure committed");
            const auto restored=fixture.download(*target);require(restored.u==fixture.state.u&&restored.u_prev==fixture.state.u_prev&&
                restored.v==fixture.state.v&&restored.alive==fixture.state.alive&&restored.damage==fixture.state.damage&&
                restored.plastic_extension==fixture.state.plastic_extension&&restored.prev_tensile==fixture.state.prev_tensile,
                "phase failure leaked material history");
            require(sameMotion(s,initial)&&target->status().total_steps==0&&target->status().external_point_transfer.transfers==0,"phase failure leaked paired clocks/receipts");
        }
        require(!runDoubleFixedTargetTrial(s,*target,[&]{target->advanceCoupledContactStep(fixture.settings.dt,[&](auto phase){
            (void)contact(fixture.settings.dt);if(phase==ExternalContactPhase::BeforeDrift)s.advanceFree(fixture.settings.dt);});return false;}),"false trial committed");
        require(sameMotion(s,initial)&&target->status().total_steps==0,"false trial leaked source/target state");
        for(double dt:{0.,-1e-7,2e-7,std::numeric_limits<double>::quiet_NaN()})rejects([&]{(void)advanceDoubleFixedTargetStep(s,*target,dt,contact);},"invalid coupled horizon admitted");
        rejects([&]{(void)advanceDoubleFixedTargetStep(s,*target,1e-7,{});},"empty callback admitted");
        const auto unsupported=makeCpuLatticeBackend(fixture.schedule,Precision::Float);
        rejects([&]{(void)runDoubleFixedTargetTrial(s,*unsupported,[]{return true;});},"float paired trial silently supported");
        require(sameMotion(s,initial),"unsupported target mutated source");
        auto stale=s;stale.advanceFree(1e-7);
        rejects([&]{(void)advanceDoubleFixedTargetStep(stale,*target,1e-7,contact);},"different absolute clocks admitted");
        require(stale.elapsedTime()==1e-7&&target->status().total_steps==0,"clock refusal changed starting state");
        const MaterialSurfaceWitness bad_witnesses[2]{{0,{.04,.008,.012},{1,0,0},0,{.2,.1,0}},
            {0,{.04,.008,.012},{1,0,0},0,{-.2,.1,0}}};
        rejects([&]{(void)applyDoubleFixedLocalSurfaceManifold(s,*target,bad_witnesses,{.16,3,64,4096},0);},"malformed late manifold law admitted");
        require(sameMotion(s,initial)&&target->status().external_point_transfer.transfers==0,"late witness refusal partially committed");
        const DoubleSourceWrench invalid_load{99,{},{1,0,0},{}};
        rejects([&]{(void)advanceDoubleFixedTargetStep(s,*target,1e-7,contact,std::span(&invalid_load,1));},"invalid source load member admitted");
        require(sameMotion(s,initial)&&target->status().total_steps==0,"invalid source load mutated paired state");
        const auto started=std::chrono::steady_clock::now();const auto result=advanceDoubleFixedTargetStep(s,*target,fixture.settings.dt,contact,wrenches);
        require(result.contacts.size()==2&&s.steps()==1&&target->status().total_steps==1,"coupled interval did not own both phases and clocks");
        near(s.elapsedTime(),fixture.settings.dt,0,"source coupled clock");near(target->externalContactElapsedTime(),fixture.settings.dt,0,"material coupled clock");
        unsigned active=0;double loss=0,roundoff=0,work_residual=0;for(const auto &r:result.contacts){active+=r.contact.active_contacts;
            loss+=r.contact.dissipated_energy_j+r.contact.reconciliation_loss_j;roundoff=std::max(roundoff,std::abs(r.source_roundoff_energy_j));
            work_residual=std::max(work_residual,std::abs(r.work_residual_j));}
        require(active>0&&target->status().external_point_transfer.transfers>0,"declared actual CPU source contact missing");
        const auto end=fixture.download(*target);
        const auto whole_before=totals(initial,fixture.state),whole_after=totals(s,end);
        Vec3 source_impulse{},source_angular{};double source_work=0;
        require(result.source_loads.size()==2*wrenches.size(),"source loads missed force phase");
        for(const auto &r:result.source_loads){source_impulse+=r.aggregate.impulse_n_s;source_angular+=r.aggregate.angular_impulse_origin_kg_m2_s;
            source_work+=r.aggregate.work_j;near(r.fixing.work_j,0,1e-12,"loaded fixing work");}
        const double p_residual=length(whole_after.linear_momentum_kg_m_s-whole_before.linear_momentum_kg_m_s-
            target->status().bond_kick_roundoff_impulse_n_s-source_impulse-target->status().gravity_load.impulse_n_s);
        const double l_residual=length(whole_after.angular_momentum_kg_m2_s-whole_before.angular_momentum_kg_m2_s-
            target->status().bond_kick_roundoff_angular_kg_m2_s-source_angular-target->status().gravity_load.angular_impulse_kg_m2_s);
        near(p_residual,0,1e-9,"coupled full momentum attribution");near(l_residual,0,1e-9,"coupled full angular attribution");
        const double e0=totals(initial.bodies()).kinetic_energy_j+latticeStateKineticEnergy(fixture.state)+latticeStateElasticEnergy(fixture.state);
        const double e1=totals(s.bodies()).kinetic_energy_j+latticeStateKineticEnergy(end)+latticeStateElasticEnergy(end);
        const double attributed=e1-e0+loss+target->status().damping_dissipated_j+target->status().removed_energy_j+
            target->status().plastic_work_j+target->status().plastic_return_numerical_loss_j-result.free_drift.numerical_energy_j-
            target->status().integration_numerical_energy_j-source_work-target->status().gravity_load.work_j;
        if(std::abs(attributed)>1e-10)std::cerr<<"coupled audit E0="<<e0<<" E1="<<e1<<" contact loss="<<loss
            <<" transfer work="<<target->status().external_point_transfer.work_j<<" source E="<<totals(s.bodies()).kinetic_energy_j-totals(initial.bodies()).kinetic_energy_j
            <<" target numerical="<<target->status().integration_numerical_energy_j<<" source numerical="<<result.free_drift.numerical_energy_j
            <<" damping="<<target->status().damping_dissipated_j<<" removal="<<target->status().removed_energy_j<<" plastic="<<target->status().plastic_work_j<<'\n';
        near(attributed,0,1e-10,"coupled source/material full energy attribution");
        near(roundoff,0,1e-11,"double source contact retained float work floor");
        require(end.mass==fixture.state.mass,"CPU coupled step changed material mass");
        std::cout<<"DOUBLE_CONTACT {\"material\":\""<<materialPresetName(preset)<<"\",\"dt_s\":"<<fixture.settings.dt
            <<",\"gravity_and_wrench\":"<<(loaded?"true":"false")<<",\"source_external_work_j\":"<<source_work
            <<",\"source_mass_kg\":"<<s.state().mass_kg<<",\"target_mass_kg\":"<<fixture.material.density_kg_m3*.08*.08*.08
            <<",\"active_contacts\":"<<active<<",\"source_roundoff_j\":"<<roundoff<<",\"work_residual_j\":"<<work_residual
            <<",\"attributed_energy_j\":"<<attributed<<",\"attributed_momentum_n_s\":"<<p_residual
            <<",\"attributed_angular_kg_m2_s\":"<<l_residual<<",\"broken_bonds\":"<<target->status().broken_bonds
            <<",\"wall_s\":"<<std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()<<"}\n";
    }
}
}
int main(){try{std::cout<<std::setprecision(17);rotationOracles();assemblyAndImpulseOracles();gravityOracles();coupledOracles();
    std::cout<<"[PASS] double rigid source rotation, fixing reactions and coupled rollback oracles\n";return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
