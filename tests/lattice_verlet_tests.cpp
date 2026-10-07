#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticeWorking.hpp"
#include "material/MaterialCompiler.hpp"
#include "material/MaterialCatalog.hpp"
#include "matter/BoxLattice.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;
void require(bool yes,const char *why) { if (!yes) throw std::runtime_error(why); }
void near(double x,double y,double tol,const char *why) { require(std::isfinite(x)&&std::abs(x-y)<=tol,why); }
struct Spring {
    LatticeAsset asset;LatticeSchedule schedule;LatticeState state;StepSettings<double> settings{};
    Spring(double dt=.001) {
        const auto material=makeReferenceMaterial(MaterialPreset::Oak,17);
        const auto compiled=compileElasticLatticeReference(material,1,1);
        asset=generateBoxTileLattice({{2,1,1},1,1},compiled);schedule=buildLatticeSchedule(asset);
        ActiveMatter matter;matter.asset=&asset;matter.material=compiled;
        for (const auto &node:asset.nodes) {
            matter.nodes.push_back({node.local_position_m,node.local_position_m,{},1,{}});
            matter.reference_positions_world_m.push_back(node.local_position_m);
        }
        matter.bonds.resize(asset.bonds.size());state=buildLatticeState(matter,schedule,{});
        require(state.node_count==2&&state.bond_count==1,"spring fixture dimensions");
        state.mass={2,3};state.inv_mass={.5,1.0/3};state.compliance[0]=.01;
        state.u[3]=.02; // q = 0.02 m, k = 100 N/m, reduced mass = 1.2 kg.
        settings.dt=dt;settings.bond_integrator=kBondVelocityVerlet;settings.audit_energy=1;settings.constraint_iterations=1;
    }
    std::unique_ptr<LatticeBackend> backend() const {
        auto out=makeCpuLatticeBackend(schedule,Precision::Double);out->upload(state,settings,{});return out;
    }
    LatticeState download(LatticeBackend &backend) const { auto out=state;SphereState<double> sphere;backend.download(out,sphere);return out; }
};
Vec3 momentum(const LatticeState &s) {
    Vec3 p{};for (unsigned i=0;i<s.node_count;++i) p+=s.mass[i]*Vec3{s.v[3*i],s.v[3*i+1],s.v[3*i+2]};return p;
}
Vec3 angular(const LatticeState &s) {
    Vec3 p{};for (unsigned i=0;i<s.node_count;++i) p+=cross(s.origin+Vec3{s.x0[3*i]+s.u[3*i],s.x0[3*i+1]+s.u[3*i+1],s.x0[3*i+2]+s.u[3*i+2]},
        s.mass[i]*Vec3{s.v[3*i],s.v[3*i+1],s.v[3*i+2]});return p;
}
double energy(const LatticeState &s) { return latticeStateElasticEnergy(s)+latticeStateKineticEnergy(s); }
void backwardEulerOracle() {
    Spring spring(.01);spring.settings.bond_integrator=kBondXpbd;spring.state.v[3]=.1;
    auto backend=spring.backend();backend->run({.max_steps=1});const auto after=spring.download(*backend);
    const double mu=1.2,k=100,q=.02,v=.1,dt=spring.settings.dt;
    const double next_q=(q+dt*v)/(1+dt*dt*k/mu),next_v=(next_q-q)/dt;
    const double loss=.5*mu*(next_v-v)*(next_v-v)+.5*k*(next_q-q)*(next_q-q);
    near(after.u[3]-after.u[0],next_q,3e-16,"XPBD is not the isolated backward Euler spring oracle");
    near(after.v[3]-after.v[0],next_v,3e-14,"XPBD reconstructed velocity oracle");
    near(energy(spring.state)-energy(after),loss,2e-14,"implicit spring numerical loss identity");
    std::cout<<"implicit single spring loss="<<loss<<" J\n";
}
void harmonicConvergence() {
    double old_error=0,old_energy=0;
    for (unsigned n:{100U,200U,400U}) {
        Spring spring(.5/n);auto backend=spring.backend();backend->run({.max_steps=n});const auto after=spring.download(*backend);
        const double omega=std::sqrt(100/1.2),q=.02*std::cos(omega*.5),v=-.02*omega*std::sin(omega*.5);
        const double error=std::abs(after.u[3]-after.u[0]-q)+std::abs(after.v[3]-after.v[0]-v)/omega;
        const double defect=std::abs(energy(after)-energy(spring.state));
        near(length(momentum(after)-momentum(spring.state)),0,2e-14,"spring momentum conservation");
        near(energy(after)-energy(spring.state),backend->status().integration_numerical_energy_j,3e-15,"signed integrator error account");
        require(backend->status().broken_bonds==0,"elastic oracle acquired fracture");
        if (old_error) require(error<.26*old_error&&defect<.26*old_energy,"Verlet harmonic error is not second order");
        old_error=error;old_energy=defect;
        std::cout<<"harmonic dt="<<spring.settings.dt<<" phase error="<<error<<" energy defect="<<defect<<" J\n";
    }
}
void rotatingSpring() {
    Spring spring(.002);const double r=1.02,omega=std::sqrt(100*.02/(1.2*r));
    // Mass-centred circular solution. The central spring, not a velocity
    // constraint, determines subsequent rotation.
    const double a=-3*r/5,b=2*r/5;
    spring.state.u[0]=a-spring.state.x0[0];spring.state.u[3]=b-spring.state.x0[3];
    spring.state.v[1]=omega*a;spring.state.v[4]=omega*b;
    auto backend=spring.backend();backend->run({.max_steps=10000});const auto after=spring.download(*backend);
    near(length(momentum(after)-momentum(spring.state)),0,2e-13,"rotating spring linear momentum");
    near(length(angular(after)-angular(spring.state)),0,2e-13,"rotating spring angular momentum");
    require(std::abs(energy(after)-energy(spring.state))<2e-8,"rotating spring bounded energy");
    near(length(backend->status().bond_kick_roundoff_angular_kg_m2_s),0,2e-13,"central kick angular arithmetic account");
    std::cout<<"rotating spring 20 s: L residual="<<length(angular(after)-angular(spring.state))<<" energy="<<energy(after)-energy(spring.state)<<" J\n";
}
void loadsGravityAndExpiry() {
    Spring spring(.01);spring.state.alive[0]=0;spring.state.nbr_alive.assign(spring.state.nbr_alive.size(),0);
    spring.settings.gravity={0,-9.81,0};auto backend=spring.backend();
    backend->setExternalForces({{4,0,0},{6,0,0}},3);
    backend->run({.max_steps=2});backend->run({.max_steps=3});const auto after=spring.download(*backend);const auto &status=backend->status();
    require(status.external_load.steps==3,
        "half kicks consumed or doubled finite force duration");
    near(status.external_load.elapsed_s,.03,1e-17,"half kick elapsed force time");
    near(status.gravity_load.elapsed_s,.05,2e-17,"half kick elapsed gravity time");
    near(status.external_load.impulse_n_s.x,.3,1e-15,"finite force impulse");
    for (unsigned i=0;i<2;++i) {
        near(after.v[3*i],.06,2e-15,"finite load final velocity");
        near(after.u[3*i]-spring.state.u[3*i],.0021,2e-15,"finite load coast displacement");
        near(after.v[3*i+1],-.4905,2e-15,"gravity velocity oracle");
        near(after.u[3*i+1],-.5*9.81*.05*.05,2e-15,"gravity displacement oracle");
    }
    near(energy(after)-energy(spring.state),status.gravity_load.work_j+status.external_load.work_j,2e-15,"separate gravity/source work");
    near(status.integration_numerical_energy_j,0,3e-15,"ballistic integration error");
    spring.settings.gravity={};auto named=spring.backend();
    named->setExternalWrenches({{"drive",{0,1},{0,0,0},{10,0,0},{}}},3);
    named->run({.max_steps=2});named->run({.max_steps=3});
    const auto &source=named->status();
    require(source.external_load.steps==3&&source.external_sources.size()==1&&source.external_sources[0].load.steps==3,
        "half kicks doubled named source duration");
    near(source.external_sources[0].load.elapsed_s,.03,1e-17,"named source elapsed time");
    near(source.external_sources[0].load.work_j,.009,2e-15,"named source signed work");
}
void plasticOvershootIdentity() {
    for (double hardening:{0.0,.2})for (double sign:{-1.0,1.0}) {
        Spring spring;spring.state.u[3]=sign*.02;spring.settings.plastic_yield_stretch=.005;spring.settings.plastic_hardening=hardening;
        auto working=WorkingLattice<double>::fromState(spring.state,spring.schedule);auto L=working.arrays();
        const double before=storedBondEnergy(L,0,false),work=bondPlasticReturn(L,spring.settings,0,false);
        const double increment=std::abs(L.plastic_extension[0]);
        const double overshoot=.5*(1+hardening)*increment*increment/L.compliance[0];
        near(before-storedBondEnergy(L,0,false)-work,overshoot,2e-15,"plastic overstress numerical loss identity");
    }
}
void fixedSpringOracleAndRollback() {
    double old_error=0;
    for (unsigned n:{100U,200U,400U}) {
        Spring spring(.5/n);spring.state.inv_mass[0]=0;
        spring.state.origin={2,3,-4};
        auto backend=spring.backend();backend->run({.max_steps=n});
        const auto after=spring.download(*backend);const auto &s=backend->status();
        const double omega=std::sqrt(100/3.0);
        const double error=std::abs(after.u[3]-.02*std::cos(omega*.5))+
            std::abs(after.v[3]+.02*omega*std::sin(omega*.5))/omega;
        require(after.u[0]==spring.state.u[0]&&after.v[0]==0&&after.inv_mass[0]==0&&after.mass[0]==2,
            "declared clamp moved or lost physical mass");
        near(length(momentum(after)-s.fixed_boundary.impulse_n_s-s.bond_kick_roundoff_impulse_n_s),0,1e-14,"fixed spring support momentum");
        near(length(angular(after)-s.fixed_boundary.angular_impulse_kg_m2_s-s.bond_kick_roundoff_angular_kg_m2_s),0,5e-14,"fixed spring support angular momentum");
        near(length(s.bond_kick_roundoff_impulse_n_s),0,1e-14,"physical support reaction hidden as roundoff");
        near(energy(after)-energy(spring.state),s.integration_numerical_energy_j,3e-15,"stationary boundary invented work");
        if (old_error) require(error<.26*old_error,"clamped harmonic trajectory does not refine at second order");
        old_error=error;
        const auto before=s;const auto state=after;
        require(!backend->runReversibleTrial([&]{backend->run({.max_steps=7});return false;}),"boundary trial accepted refusal");
        const auto restored=spring.download(*backend);
        require(restored.u==state.u&&restored.v==state.v&&restored.inv_mass==state.inv_mass&&
            backend->status().total_steps==before.total_steps&&
            length(backend->status().fixed_boundary.impulse_n_s-before.fixed_boundary.impulse_n_s)==0&&
            length(backend->status().fixed_boundary.angular_impulse_kg_m2_s-before.fixed_boundary.angular_impulse_kg_m2_s)==0,
            "refused trial leaked clamp reaction or state");
    }
    Spring spring(.01);spring.state.alive[0]=0;spring.state.nbr_alive.assign(spring.state.nbr_alive.size(),0);
    spring.state.inv_mass={0,0};spring.state.u_prev=spring.state.u;spring.settings.gravity={0,-9.81,0};
    spring.state.origin={2,3,-4};auto backend=spring.backend();
    backend->setExternalForces({{4,0,0},{6,0,0}},3);backend->run({.max_steps=5});
    const auto &s=backend->status();const auto after=spring.download(*backend);
    require(after.u==spring.state.u&&after.v==spring.state.v,"loads moved clamped nodes");
    near(s.external_load.impulse_n_s.x,.3,1e-15,"force on clamp lost source reaction");
    near(s.gravity_load.impulse_n_s.y,-5*9.81*.05,1e-14,"gravity on clamp lost weight");
    near(length(s.fixed_boundary.impulse_n_s+s.external_load.impulse_n_s+s.gravity_load.impulse_n_s),0,1e-14,"clamp external support reaction");
    near(length(s.fixed_boundary.angular_impulse_kg_m2_s+s.external_load.angular_impulse_kg_m2_s+s.gravity_load.angular_impulse_kg_m2_s),0,3e-14,"clamp external support torque");
    near(s.external_load.work_j+s.gravity_load.work_j,0,0,"stationary force produced work");
    near(s.integration_numerical_energy_j,0,0,"stationary clamp produced integration energy");
    require(s.external_load.steps==3,"clamp load expiry changed");
    bool refused=false;try {(void)backend->externalContactPoint(0);}catch(const std::invalid_argument &){refused=true;}
    require(refused,"finite point transfer accepted infinite clamp mobility");
}
void refusalPreservesUpload() {
    Spring spring;auto backend=spring.backend();backend->run({.max_steps=1});const auto before=spring.download(*backend);
    const auto rejects=[&](const LatticeState &state,const StepSettings<double> &settings) {
        bool refused=false;try {backend->upload(state,settings,{});}catch(const std::invalid_argument &) {refused=true;}
        require(refused&&spring.download(*backend).v==before.v&&backend->status().total_steps==1,"invalid upload changed prior state");
    };
    auto settings=spring.settings;settings.bond_integrator=99;rejects(spring.state,settings);
    settings=spring.settings;settings.dt=1;rejects(spring.state,settings);
    settings=spring.settings;settings.sphere_enabled=1;rejects(spring.state,settings);
    settings=spring.settings;settings.support.plane_count=1;rejects(spring.state,settings);
    settings=spring.settings;settings.node_contact.mode=1;rejects(spring.state,settings);
    auto bad=spring.state;bad.inv_mass[0]=-1;rejects(bad,spring.settings);
    bad=spring.state;bad.inv_mass[0]=0;bad.v[0]=1;rejects(bad,spring.settings);
    bad=spring.state;bad.inv_mass[0]=0;bad.v[0]=1e-200;rejects(bad,spring.settings);
    bad=spring.state;bad.inv_mass[0]=0;bad.u_prev[0]=.001;rejects(bad,spring.settings);
    bad=spring.state;bad.inv_mass[0]=0;bad.u_prev[0]=1e-200;rejects(bad,spring.settings);
    bad=spring.state;bad.inv_mass[0]=0;settings=spring.settings;settings.damping_fraction=.1;rejects(bad,settings);
    bad=spring.state;bad.compliance[0]=0;rejects(bad,spring.settings);
    bad=spring.state;bad.u[3]=-1;rejects(bad,spring.settings);
    bad=spring.state;bad.v.pop_back();rejects(bad,spring.settings);
    bad=spring.state;bad.mass[0]=3;rejects(bad,spring.settings);
    std::vector<std::unique_ptr<LatticeBackend>> others;
    others.push_back(makeCpuLatticeBackend(spring.schedule,Precision::Float));
    others.push_back(makeParallelCpuLatticeBackend(spring.schedule,Precision::Double,2,1));
    for (auto &other:others) {
        bool refused=false;try {other->upload(spring.state,spring.settings,{});}catch(const std::invalid_argument &) {refused=true;}
        require(refused,"unqualified backend silently accepted alternative integration");
    }
}
}
int main() {try {std::cout.precision(12);backwardEulerOracle();harmonicConvergence();rotatingSpring();loadsGravityAndExpiry();
    plasticOvershootIdentity();fixedSpringOracleAndRollback();refusalPreservesUpload();std::cout<<"[PASS] explicit spring reference analytical and refusal gates\n";return 0;
    }catch(const std::exception &e) {std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
