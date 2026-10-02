#include "fastlattice/NativeFixedContact.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"
#include <cmath>
#include <chrono>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>

namespace {
using namespace banjo;using namespace banjo::fastlattice;
constexpr double cell=.04,dt=1e-7;
constexpr PointContactRoundoffBudget budget{1e-5,1e-5,1e-5};
void require(bool value,const char *why){if(!value)throw std::runtime_error(why);}
void near(double value,double expected,double bound,const char *why){if(!std::isfinite(value)||std::abs(value-expected)>bound)throw std::runtime_error(why);}
struct Target {
    MaterialDefinition material;LatticeAsset asset;ActiveMatter matter;LatticeSchedule schedule;LatticeState state;
    StepSettings<double> settings{};
    explicit Target(MaterialPreset preset,bool bonded=true,double timestep=dt):material(makeReferenceMaterial(preset,17)) {
        const auto compiled=withPlasticFlow(withStrengthDerivedFailure(compileElasticLatticeReference(material,cell,1),material),material);
        asset=generateBoxTileLattice({{.12,.12,.12},cell,1},compiled);
        matter.asset=&asset;matter.material=compiled;
        const Vec3 origin{.095,0,0};
        for(const auto &n:asset.nodes) {
            const Vec3 at=origin+n.local_position_m;
            matter.nodes.push_back({at,at,{},n.represented_volume_m3*material.density_kg_m3,{}});
            matter.reference_positions_world_m.push_back(at);
        }
        matter.bonds.resize(asset.bonds.size());if(!bonded)for(auto &b:matter.bonds){b.alive=false;b.damage=1;}
        schedule=buildLatticeSchedule(asset);state=buildLatticeState(matter,schedule,origin);
        settings.dt=timestep;settings.constraint_iterations=4;settings.audit_energy=1;
        settings.plastic_yield_stretch=compiled.yield_stretch;settings.plastic_hardening=compiled.plastic_hardening_ratio;
    }
    std::unique_ptr<LatticeBackend> backend(Precision precision=Precision::Double) {
        auto out=makeCpuLatticeBackend(schedule,precision);out->upload(state,settings,{});return out;
    }
    LatticeState download(LatticeBackend &backend)const {auto out=state;SphereState<double> sphere;backend.download(out,sphere);return out;}
};
struct Tool {
    JoltWorld world;unsigned fixing{};
    explicit Tool(double speed=2) {
        world.setGravity({});const auto iron=makeReferenceMaterial(MaterialPreset::Iron,17),oak=makeReferenceMaterial(MaterialPreset::Oak,17);
        world.addBox({1,{.08,.08,.08},iron,{{},{},{speed,0,0},{}},false});
        world.addBox({10,{.24,.04,.04},oak,{{-.16,0,0},{},{speed,0,0},{}},false});
        world.addBox({2,{.01,.01,.01},oak,{{5,5,5},{},{},{}},true});
        fixing=world.addFixing({10,1,{-.04,0,0},{1,0,0},0,0,0}); // Declared ideal weld, no failure-strength claim.
        for(auto pair:{std::pair{1U,10U},std::pair{2U,1U},std::pair{2U,10U}})
            world.setPairContactOwner(pair.first,pair.second,PairContactOwner::External);
        world.setDamping(1,0,0);world.setDamping(10,0,0);
    }
};
MechanicalTotals totals(const LatticeState &state,JoltWorld &world) {
    auto out=world.mechanicalTotals();out.elastic_energy_j+=latticeStateElasticEnergy(state);
    out.kinetic_energy_j+=latticeStateKineticEnergy(state);
    for(unsigned i=0;i<state.node_count;++i) {
        const Vec3 at=state.origin+Vec3{state.x0[3*i]+state.u[3*i],state.x0[3*i+1]+state.u[3*i+1],state.x0[3*i+2]+state.u[3*i+2]};
        const Vec3 p=state.mass[i]*Vec3{state.v[3*i],state.v[3*i+1],state.v[3*i+2]};
        out.mass_kg+=state.mass[i];
        out.linear_momentum_kg_m_s+=p;out.angular_momentum_kg_m2_s+=cross(at,p);
    }
    return out;
}
void targetTransferPreservesHistoryAndAccounts() {
    Target target(MaterialPreset::Oak,false);auto backend=target.backend();
    std::vector<Vec3> forces(target.state.node_count,{.2,0,0});backend->setExternalForces(forces,3);
    backend->run({.max_steps=1,.capture_stride=1,.max_frames=3});
    const auto before=target.download(*backend);const auto old=backend->status();const auto point=backend->externalContactPoint(0);
    const Vec3 velocity=point.velocity_m_s+Vec3{2,.3,-.1};
    const auto checked=backend->validateExternalPointVelocity(0,point,velocity);
    const auto receipt=backend->applyExternalPointVelocity(0,point,velocity);const auto after=target.download(*backend);
    near(length(receipt.impulse_n_s-point.mass_kg*(velocity-point.velocity_m_s)),0,1e-15,"target impulse oracle");
    near(latticeStateKineticEnergy(after)-latticeStateKineticEnergy(before),receipt.work_j,1e-15,"target kinetic transfer oracle");
    near(receipt.work_j,checked.work_j,0,"target preflight/commit parity");
    require(after.u==before.u&&after.u_prev==before.u_prev&&after.alive==before.alive&&after.damage==before.damage&&
        after.prev_tensile==before.prev_tensile&&after.prev_compressive==before.prev_compressive&&after.prev_shear==before.prev_shear&&
        after.plastic_extension==before.plastic_extension&&after.plastic_strain==before.plastic_strain&&after.failure_mode==before.failure_mode,
        "contact reset target pose/bond history");
    require(backend->status().total_steps==old.total_steps&&backend->status().frames_captured==old.frames_captured&&
        backend->status().external_load.steps==old.external_load.steps,"contact reset elapsed step/capture/load state");
    backend->run({.max_steps=2,.capture_stride=1,.max_frames=3});
    require(backend->status().total_steps==3&&backend->status().external_load.steps==3&&backend->takeFrames().size()==3,
        "contact lost finite load expiry or continuous captures");
    auto stale=point;bool refused=false;const auto unchanged=target.download(*backend);
    try{(void)backend->applyExternalPointVelocity(0,stale,{});}catch(const std::invalid_argument &){refused=true;}
    require(refused&&target.download(*backend).v==unchanged.v,"stale target transfer changed state");
    const auto current=backend->externalContactPoint(0);refused=false;
    try{(void)backend->applyExternalPointVelocity(0,current,{std::numeric_limits<double>::infinity(),0,0});}
    catch(const std::invalid_argument &){refused=true;}require(refused&&target.download(*backend).v==unchanged.v,"invalid target velocity changed state");
    refused=false;const auto ledger_before=backend->status().external_point_transfer.transfers;
    try{(void)backend->applyExternalPointVelocity(0,current,{1e300,1e300,0});}
    catch(const std::overflow_error &){refused=true;}
    require(refused&&target.download(*backend).v==unchanged.v&&backend->status().external_point_transfer.transfers==ledger_before,
        "overflowing target transfer changed state or accounts");
    Target spent(MaterialPreset::Oak,false);spent.state.v[0]=2;auto empty=spent.backend();const auto moving=empty->externalContactPoint(0);
    (void)empty->applyExternalPointVelocity(0,moving,{});
    const auto stopped=empty->run({.max_steps=5,.removable_energy_j=.5*moving.mass_kg});
    require(stopped.exit_reason==6&&stopped.total_steps==1,"outgoing contact work did not reduce the target's enabled energy ceiling");
}
void preparedContactIsImmutableAndInvalidates() {
    Tool tool;Target target(MaterialPreset::Oak,false);auto backend=target.backend();auto point=backend->externalContactPoint(0);
    const auto native_before=tool.world.snapshot(1);
    const auto prepared=tool.world.prepareExternalFixedPointContact(2,1,point,{1,0,0},-.001,dt,{},budget);
    require(prepared.receipt().contact.modal_contact.applied,"prepared contact expected impulse");
    near(length(tool.world.snapshot(1).linear_velocity_m_s-native_before.linear_velocity_m_s),0,0,"preparation changed native source");
    Tool other;bool refused=false;
    try{(void)other.world.commitExternalFixedPointContact(prepared,point);}catch(const std::invalid_argument &){refused=true;}
    require(refused,"prepared contact accepted another native world");
    point.velocity_m_s.y=1;refused=false;
    try{(void)tool.world.commitExternalFixedPointContact(prepared,point);}catch(const std::invalid_argument &){refused=true;}
    require(refused,"prepared contact accepted changed point");point=backend->externalContactPoint(0);
    tool.world.step(dt);const auto after_step=tool.world.snapshot(1);refused=false;
    try{(void)tool.world.commitExternalFixedPointContact(prepared,point);}catch(const std::invalid_argument &){refused=true;}
    require(refused,"prepared contact reused across elapsed time");
    near(length(tool.world.snapshot(1).linear_velocity_m_s-after_step.linear_velocity_m_s),0,0,"refused preparation changed native state");
    Target float_target(MaterialPreset::Oak);auto float_backend=float_target.backend(Precision::Float);Tool float_tool;refused=false;
    const auto float_before=float_tool.world.snapshot(1);
    try{(void)applyNativeFixedPointTransfer(float_tool.world,*float_backend,0,2,1,{1,0,0},-.001,{},budget);}
    catch(const std::invalid_argument &){refused=true;}require(refused,"unqualified float coupling admitted");
    near(length(float_tool.world.snapshot(1).linear_velocity_m_s-float_before.linear_velocity_m_s),0,0,"unsupported target modified source");
    auto parallel=makeParallelCpuLatticeBackend(target.schedule,Precision::Double,2,1);parallel->upload(target.state,target.settings,{});
    refused=false;try{(void)applyNativeFixedPointTransfer(float_tool.world,*parallel,0,2,1,{1,0,0},-.001,{},budget);}
    catch(const std::invalid_argument &){refused=true;}require(refused,"unqualified parallel coupling silently admitted");
    near(length(float_tool.world.snapshot(1).linear_velocity_m_s-float_before.linear_velocity_m_s),0,0,"unsupported parallel target modified source");
    const auto rejects=[&](Tool &source,const PreparedFixedPointContact &plan) {
        auto candidate=backend->externalContactPoint(0);const auto head=source.world.snapshot(1),handle=source.world.snapshot(10);
        bool rejected=false;try{(void)source.world.commitExternalFixedPointContact(plan,candidate);}catch(const std::invalid_argument &){rejected=true;}
        require(rejected,"stale native preparation admitted");
        near(length(source.world.snapshot(1).linear_velocity_m_s-head.linear_velocity_m_s),0,0,"stale plan changed head velocity");
        near(length(source.world.snapshot(10).linear_velocity_m_s-handle.linear_velocity_m_s),0,0,"stale plan changed handle velocity");
        near(length(candidate.velocity_m_s-backend->externalContactPoint(0).velocity_m_s),0,0,"stale plan changed target velocity");
    };
    const auto prepare=[&](Tool &source){return source.world.prepareExternalFixedPointContact(2,1,backend->externalContactPoint(0),{1,0,0},-.001,dt,{},budget);};
    Tool ownership;const auto owned=prepare(ownership);ownership.world.setPairContactOwner(2,10,PairContactOwner::Jolt);rejects(ownership,owned);
    Tool moved;const auto motion_plan=prepare(moved);moved.world.translateBody(10,{0,.001,0});rejects(moved,motion_plan);
    Tool topology;const auto joint_plan=prepare(topology);topology.world.removeJoint(topology.fixing);rejects(topology,joint_plan);
    Tool reshaped;const auto shape_plan=prepare(reshaped);const auto state=reshaped.world.mechanicalState(1);const double rotation[]{1,0,0,0};
    reshaped.world.reshapePrimitive(1,false,{.08,.08,.08},rotation,state.mass_kg,
        {state.inertia_world_kg_m2.m[0][0],state.inertia_world_kg_m2.m[1][1],state.inertia_world_kg_m2.m[2][2]});
    rejects(reshaped,shape_plan);
}
void coupledMatchedTargets() {
    std::map<MaterialPreset,double> coarse_target_energy;
    for(double timestep:{dt,.5*dt})for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Tool tool(6);Target target(preset,true,timestep);auto backend=target.backend();
        const auto initial=totals(target.state,tool.world);double loss=0,reconcile=0,numerical=0,max_contact_work=0;
        Vec3 p_error{},l_error{},couple{};std::uint64_t contacts=0,native_steps=0;
        double native_step_energy=0,target_step_energy=0;
        Vec3 native_step_p{},native_step_l{},target_step_p{},target_step_l{};double max_native_step_p=0,max_native_step_l=0;
        const unsigned count=timestep==dt?2048:4096;
        const auto started=std::chrono::steady_clock::now();
        for(unsigned step=0;step<count;++step) {
            require(backend->status().total_steps==native_steps,"target/native clocks diverged");
            for(unsigned i=0;i<target.state.node_count;++i) {
                const auto point=backend->externalContactPoint(i);
                require(tool.world.pointShapeContacts(10,point.position_world_m,.016,.00001).contacts.empty(),
                    "matched fixture omitted an active handle/target witness");
                const auto query=tool.world.pointShapeContacts(1,point.position_world_m,.016,.00001);
                for(const auto &hit:query.contacts) {
                    const auto law=combineContactMaterials(compileContactMaterial(target.material),hit.body_contact);
                    const auto receipt=applyNativeFixedPointTransfer(tool.world,*backend,i,2,1,hit.normal_world,hit.gap_m,
                        {law.static_friction,law.dynamic_friction,law.restitution},budget);
                    require(receipt.target_step==step&&receipt.horizon_s==timestep,"contact used another substep clock");
                    if(!receipt.source.contact.modal_contact.applied)continue;
                    ++contacts;loss+=receipt.source.contact.modal_contact.dissipated_energy_j;
                    reconcile+=receipt.source.contact.reconciliation_loss_j;numerical+=receipt.source.numerical_energy_change_j;
                    p_error+=receipt.source.momentum_error_kg_m_s;l_error+=receipt.source.angular_momentum_error_kg_m2_s;
                    couple+=receipt.source.contact.geometry_couple_kg_m2_s;
                    max_contact_work=std::max(max_contact_work,std::abs(receipt.source.contact.work_residual_j));
                }
            }
            const auto native_before=tool.world.mechanicalTotals();
            tool.world.step(timestep);++native_steps;
            const auto native_after=tool.world.mechanicalTotals();
            native_step_energy+=native_after.kinetic_energy_j-native_before.kinetic_energy_j;
            const auto step_p=native_after.linear_momentum_kg_m_s-native_before.linear_momentum_kg_m_s;
            const auto step_l=native_after.angular_momentum_kg_m2_s-native_before.angular_momentum_kg_m2_s;
            native_step_p+=step_p;native_step_l+=step_l;
            max_native_step_p=std::max(max_native_step_p,length(step_p));max_native_step_l=std::max(max_native_step_l,length(step_l));
            const auto target_before=target.download(*backend);const auto status_before=backend->status();
            const auto target_before_totals=totals(target_before,tool.world);
            backend->run({.max_steps=1});
            const auto target_after=target.download(*backend);const auto status_after=backend->status();
            const auto target_after_totals=totals(target_after,tool.world);
            target_step_p+=target_after_totals.linear_momentum_kg_m_s-target_before_totals.linear_momentum_kg_m_s;
            target_step_l+=target_after_totals.angular_momentum_kg_m2_s-target_before_totals.angular_momentum_kg_m2_s;
            target_step_energy+=latticeStateKineticEnergy(target_after)+latticeStateElasticEnergy(target_after)-
                latticeStateKineticEnergy(target_before)-latticeStateElasticEnergy(target_before)+
                status_after.removed_energy_j-status_before.removed_energy_j+status_after.plastic_work_j-status_before.plastic_work_j+
                status_after.damping_dissipated_j-status_before.damping_dissipated_j;
        }
        const auto final_state=target.download(*backend);const auto final=totals(final_state,tool.world);const auto status=backend->status();
        const double wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
        require(status.total_steps==count&&contacts>0&&status.external_point_transfer.transfers==contacts,"coupled target/contact counts");
        require(status.contact.candidate_overflow==0&&status.node_contact.pair_overflow==0,"coupled fixture exceeded target contact capacity");
        require(status.max_tensile_stretch>0||status.max_compressive_strain>0||status.max_shear_strain>0,
            "tool contact never entered target constitutive sampling");
        const Vec3 residual_p=final.linear_momentum_kg_m_s-initial.linear_momentum_kg_m_s-p_error;
        const Vec3 residual_l=final.angular_momentum_kg_m2_s-initial.angular_momentum_kg_m2_s-l_error-couple;
        const double unallocated=final.mechanicalEnergy()-initial.mechanicalEnergy()+loss+reconcile+
            status.removed_energy_j+status.plastic_work_j+status.damping_dissipated_j-numerical;
        require(std::isfinite(unallocated)&&std::isfinite(length(residual_p))&&std::isfinite(length(residual_l)),"coupled trajectory audit became nonfinite");
        near(final.mass_kg,initial.mass_kg,1e-12,"coupled experiment lost mass");
        near(unallocated,native_step_energy+target_step_energy,1e-10,"coupled unallocated energy attribution");
        std::cout<<materialPresetName(preset)<<": cells="<<target.state.node_count<<" h="<<cell<<" dt="<<timestep<<" elapsed="<<count*timestep
            <<" s; contacts="<<contacts<<" broken="<<status.broken_bonds<<" damage="<<status.max_damage
            <<" strain="<<status.max_tensile_stretch<<"; plastic="<<status.plastic_work_j<<" J; contact loss="<<loss<<" J; reconcile="<<reconcile
            <<" J; numerical="<<numerical<<" J; phase work="<<max_contact_work<<" J; p residual="<<length(residual_p)
            <<" N s; L residual="<<length(residual_l)<<" kg m2/s; unallocated energy="<<unallocated
            <<" J; native step="<<native_step_energy<<" J; target step="<<target_step_energy
            <<" J; native step p/L="<<length(native_step_p)<<"/"<<length(native_step_l)
            <<"; target step p/L="<<length(target_step_p)<<"/"<<length(target_step_l)
            <<"; max native step p/L="<<max_native_step_p<<"/"<<max_native_step_l<<"\n";
        std::cout<<"  audited reference loop wall="<<wall<<" s; wall/sim="<<wall/(count*timestep)<<"\n";
        near(length(residual_p-native_step_p-target_step_p),0,1e-10,"combined momentum attribution");
        near(length(residual_l-native_step_l-target_step_l),0,1e-10,"combined angular attribution");
        require(length(residual_p-native_step_p)<1e-9&&length(target_step_p)<1e-9&&max_native_step_p<1e-6&&max_native_step_l<1e-7&&
            max_contact_work<1e-12,"coupled transfer/native-step arithmetic bounds");
        // Target angular and energy residuals remain measured, unclosed solver
        // behavior. No broadened angular/energy tolerance certifies conservation.
        if(preset==MaterialPreset::Glass)require(status.broken_bonds>0,"matched tool input no longer enters glass fracture");
        if(preset==MaterialPreset::Oak)require(status.broken_bonds==0,"oak comparison became a brittle substitute");
        if(timestep==dt)coarse_target_energy[preset]=target_step_energy;
        else require(std::abs(target_step_energy)<std::abs(coarse_target_energy.at(preset)),"smaller matched timestep no longer reduces target energy defect");
    }
}
}
int main(){try{std::cout.precision(12);targetTransferPreservesHistoryAndAccounts();preparedContactIsImmutableAndInvalidates();coupledMatchedTargets();
    std::cout<<"[PASS] checked native/CPU contact transfer and continuous target integration\n";return 0;}
    catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
