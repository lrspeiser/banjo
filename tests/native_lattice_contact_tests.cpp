#include "fastlattice/NativeFixedContact.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"
#include "physics/GripPull.hpp"
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
    explicit Target(MaterialPreset preset,bool bonded=true,double timestep=dt,std::uint8_t integrator=kBondXpbd):material(makeReferenceMaterial(preset,17)) {
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
        settings.bond_integrator=integrator;
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
void targetTransferPreservesHistoryAndAccounts(std::uint8_t integrator) {
    Target target(MaterialPreset::Oak,false,dt,integrator);auto backend=target.backend();
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
void sameTarget(const LatticeState &a,const LatticeState &b) {
    near(length(a.origin-b.origin),0,0,"rollback target origin");
#define SAME(field) require(a.field==b.field,"rollback/retry target " #field)
    SAME(node_count);SAME(bond_count);SAME(max_degree);SAME(x0);SAME(u);SAME(u_prev);SAME(v);SAME(inv_mass);SAME(mass);
    SAME(adj_offsets);SAME(adj_bonds);SAME(nbr_bond);SAME(nbr_other);SAME(nbr_rest);SAME(nbr_weight);SAME(nbr_alive);
    SAME(bond_slot_a);SAME(bond_slot_b);SAME(bond_a);SAME(bond_b);SAME(rest_edge);SAME(rest_length);
    SAME(rest_length_sq_minus);SAME(weight);SAME(compliance);SAME(threshold);SAME(alive);SAME(failure_mode);
    SAME(damage);SAME(prev_tensile);SAME(prev_compressive);SAME(prev_shear);SAME(plastic_extension);SAME(plastic_strain);
#undef SAME
}
void sameNative(const RigidSnapshot &a,const RigidSnapshot &b) {
    near(length(a.center_of_mass_world_m-b.center_of_mass_world_m),0,0,"rollback native position");
    near(length(a.linear_velocity_m_s-b.linear_velocity_m_s),0,0,"rollback native velocity");
    near(length(a.angular_velocity_rad_s-b.angular_velocity_rad_s),0,0,"rollback native spin");
    require(a.orientation_world.w==b.orientation_world.w&&a.orientation_world.x==b.orientation_world.x&&
        a.orientation_world.y==b.orientation_world.y&&a.orientation_world.z==b.orientation_world.z,"rollback native facing");
}
void pairedTrialsRestoreAndReplay() {
    for (auto mode:{kBondXpbd,kBondVelocityVerlet}) for (auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Target target(preset,true,dt,mode);auto backend=target.backend(),control=target.backend();Tool tool(6),reference(6);
        ExternalWrench queued{"queued",{},target.state.origin,{.3,.2,0},{0,0,.001}};
        for (unsigned i=0;i<target.state.node_count;++i) queued.nodes.push_back(i);
        for (auto *b:{backend.get(),control.get()}) {b->setExternalWrenches({queued},20);b->run({.max_steps=1,.capture_stride=1,.max_frames=40});}
        tool.world.step(dt);reference.world.step(dt); // Both clocks include the load/capture warm-up.
        const auto initial=target.download(*backend);const auto old=backend->status();const auto head=tool.world.snapshot(1),handle=tool.world.snapshot(10);
        const auto old_failure=backend->firstFailureBonds();
        const auto advance=[&](Tool &source,LatticeBackend &b) {
            for (unsigned k=0;k<2048;++k) {
                for (unsigned i=0;i<target.state.node_count;++i) {
                    const auto point=b.externalContactPoint(i);const auto query=source.world.pointShapeContacts(1,point.position_world_m,.016,.00001);
                    for (const auto &hit:query.contacts) {
                        const auto law=combineContactMaterials(compileContactMaterial(target.material),hit.body_contact);
                        (void)applyNativeFixedPointTransfer(source.world,b,i,2,1,hit.normal_world,hit.gap_m,
                            {law.static_friction,law.dynamic_friction,law.restitution},budget);
                    }
                }
                const auto root=source.world.mechanicalState(10);
                const auto feedback=makeGripFeedback(root,{root,source.world.mechanicalState(1)},{-.08,0,0});
                const auto pull=gripPull(feedback.held,feedback.grip_local,{-.24+6*(k+1)*dt,0,0},{6,0,0},{},800,60,{},100,20);
                source.world.pushBodyAt(10,pull.force,pull.grip);source.world.twistBody(10,pull.torque);source.world.wake(10);
                source.world.step(dt);b.run({.max_steps=1,.capture_stride=64,.max_frames=40});
            }
        };
        const auto restored=[&] {
            sameTarget(initial,target.download(*backend));sameNative(head,tool.world.snapshot(1));sameNative(handle,tool.world.snapshot(10));
            const auto &s=backend->status();
            require(s.total_steps==old.total_steps&&s.launches==old.launches&&s.frames_captured==old.frames_captured&&
                s.broken_bonds==old.broken_bonds&&s.failure_rounds==old.failure_rounds&&s.first_failure_step==old.first_failure_step&&
                s.last_failure_step==old.last_failure_step&&s.external_point_transfer.transfers==old.external_point_transfer.transfers&&
                s.external_sources.size()==old.external_sources.size()&&s.external_load.steps==old.external_load.steps&&
                s.external_load.work_j==old.external_load.work_j&&s.wall_seconds==old.wall_seconds&&
                s.plastic_work_j==old.plastic_work_j&&s.integration_numerical_energy_j==old.integration_numerical_energy_j&&
                backend->firstFailureBonds()==old_failure,"rollback target clocks/receipts/accounting");
            for (unsigned i=0;i<kPhaseCount;++i) near(s.phase_seconds[i],old.phase_seconds[i],0,"rollback phase clock");
        };
        require(!runNativeFixedTargetTrial(tool.world,*backend,[&] {advance(tool,*backend);return false;}),"paired refusal accepted");restored();
        bool threw=false;
        try {(void)runNativeFixedTargetTrial(tool.world,*backend,[&]() -> bool {
            advance(tool,*backend);(void)backend->takeFrames();backend->setExternalForces({},0);
            throw std::runtime_error("late test refusal");
        });} catch (const std::runtime_error &e) {if (std::string(e.what())!="late test refusal") throw;threw=true;}
        require(threw,"paired exception disappeared");restored();
        require(runNativeFixedTargetTrial(tool.world,*backend,[&] {advance(tool,*backend);return true;}),"paired acceptance rejected");
        require(runNativeFixedTargetTrial(reference.world,*control,[&] {advance(reference,*control);return true;}),"control acceptance rejected");
        sameTarget(target.download(*backend),target.download(*control));sameNative(tool.world.snapshot(1),reference.world.snapshot(1));
        sameNative(tool.world.snapshot(10),reference.world.snapshot(10));
        const auto &s=backend->status(),&c=control->status();
        require(s.total_steps==2049&&s.total_steps==c.total_steps&&s.external_load.steps==20&&s.external_load.steps==c.external_load.steps&&
            s.external_load.work_j==c.external_load.work_j&&s.external_point_transfer.transfers==c.external_point_transfer.transfers&&
            s.external_point_transfer.work_j==c.external_point_transfer.work_j&&s.plastic_work_j==c.plastic_work_j&&
            backend->firstFailureBonds()==control->firstFailureBonds(),"retry changed pending load/history/contact accounts");
        near(tool.world.jointTension(tool.fixing),reference.world.jointTension(reference.fixing),0,"retry native last timestep/load");
        auto frames=backend->takeFrames(),expected=control->takeFrames();require(frames.size()==expected.size()&&frames.size()>1,"rollback lost captures");
        for (std::size_t i=0;i<frames.size();++i) require(frames[i].step==expected[i].step&&frames[i].u==expected[i].u&&
            frames[i].alive==expected[i].alive&&frames[i].damage==expected[i].damage,"retry changed captured history");
        if (preset==MaterialPreset::Glass) require(s.broken_bonds>0&&!backend->firstFailureBonds().empty(),"rollback fixture missed fracture history");
        if (preset==MaterialPreset::Iron) require(s.plastic_work_j>0,"rollback fixture missed plastic history");
        std::cout<<"Rollback "<<(mode==kBondXpbd?"XPBD ":"Verlet ")<<materialPresetName(preset)<<": retry=exact steps="<<s.total_steps
            <<" fracture="<<s.broken_bonds<<" plastic="<<s.plastic_work_j<<" J\n";
    }
}
void trialAdmissionAndAbandonedPlans() {
    Tool tool;Target target(MaterialPreset::Oak,false);auto backend=target.backend();
    auto point=backend->externalContactPoint(0);PreparedFixedPointContact abandoned;
    require(!runNativeFixedTargetTrial(tool.world,*backend,[&] {
        abandoned=tool.world.prepareExternalFixedPointContact(2,1,point,{1,0,0},-.001,dt,{},budget);
        for (unsigned kind=0;kind<3;++kind) {
            bool refused=false;
            try {
                if (kind==0) backend->upload(target.state,target.settings,{});
                if (kind==1) (void)backend->runReversibleTrial([] {return true;});
                if (kind==2) (void)tool.world.runReversibleTrial([] {return true;});
            } catch (const std::exception &) {refused=true;}
            require(refused,"paired trial admitted nested trial/upload");
        }
        bool refused=false;try {tool.world.removeJoint(tool.fixing);}catch (const std::logic_error &) {refused=true;}
        require(refused&&tool.world.hasJoint(tool.fixing),"paired trial admitted topology change");
        const double facing[]{1,0,0,0};
        const std::vector<std::function<void()>> mutations{
            [&] {tool.world.setMass(1,2);},[&] {tool.world.setDamping(1,1,1);},
            [&] {tool.world.setGroundRollingResistance([](double,double) {return .1;});},
            [&] {tool.world.reshapePrimitive(1,false,{.08,.08,.08},facing,2,{1,1,1});},
            [&] {tool.world.driveHinge(tool.fixing,1,1);},[&] {tool.world.coastHinge(tool.fixing);},
            [&] {tool.world.setJointFriction(tool.fixing,1);},[&] {tool.world.updateKerf(tool.fixing,1,1);},
            [&] {tool.world.updateGroundBite(tool.fixing,1,1,1);}};
        for (const auto &mutate:mutations) {
            refused=false;try {mutate();}catch (const std::logic_error &) {refused=true;}
            require(refused,"paired trial admitted native configuration mutation");
        }
        return false;
    }),"abandoned plan trial accepted");
    bool refused=false;try {(void)tool.world.commitExternalFixedPointContact(abandoned,point);}catch (const std::invalid_argument &) {refused=true;}
    require(refused,"plan escaped an abandoned trial with no elapsed tick");
    require(!tool.world.runReversibleTrial([&] {
        bool rejected=false;try {(void)applyNativeFixedPointTransfer(tool.world,*backend,0,2,1,{1,0,0},-.001,{},budget);}
        catch (const std::logic_error &) {rejected=true;}require(rejected,"unpaired trial admitted external point mutation");return false;
    }),"unpaired trial accepted");
    for (auto precision:{Precision::Float,Precision::Double}) {
        auto unsupported=precision==Precision::Float?target.backend(precision):makeParallelCpuLatticeBackend(target.schedule,precision,2,1);
        if (precision==Precision::Double) unsupported->upload(target.state,target.settings,{});
        bool called=false;refused=false;
        try {(void)runNativeFixedTargetTrial(tool.world,*unsupported,[&] {called=true;return true;});}
        catch (const std::invalid_argument &) {refused=true;}require(refused&&!called,"unsupported backend entered paired trial");
    }
    ExternalWrench oversized{std::string(16U*1024U*1024U,'x'),{0},point.position_world_m,{1,0,0},{}};
    backend->setExternalWrenches({oversized},1);bool called=false;refused=false;
    try {(void)runNativeFixedTargetTrial(tool.world,*backend,[&] {called=true;return true;});}
    catch (const std::invalid_argument &) {refused=true;}
    require(refused&&!called,"oversized target entered paired trial");backend->setExternalForces({},0);
    require(runNativeFixedTargetTrial(tool.world,*backend,[] {return true;}),"budget refusal left trial state open");
}
void coupledMatchedTargets() {
    for(auto configuration:{std::pair{kBondXpbd,false},std::pair{kBondVelocityVerlet,false},std::pair{kBondVelocityVerlet,true}}) {
    const auto [integrator,held]=configuration;
    std::map<MaterialPreset,double> coarse_target_energy;
    for(double timestep:{dt,.5*dt})for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Tool tool(6);Target target(preset,true,timestep,integrator);auto backend=target.backend();
        const auto initial=totals(target.state,tool.world);double loss=0,reconcile=0,numerical=0,max_contact_work=0;
        Vec3 p_error{},l_error{},couple{};std::uint64_t contacts=0,native_steps=0;
        double native_step_energy=0,target_step_energy=0;
        double hand_work=0,max_hand_force=0,max_hand_torque=0,max_joint_impulse=0,max_native_step_energy=0;
        double max_native_joint_tension=0,max_native_joint_shear=0;
        Vec3 hand_impulse{},hand_angular{};
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
                    for (const auto &reaction:receipt.source.contact.contact_reactions)
                        max_joint_impulse=std::max(max_joint_impulse,length(reaction.impulse_on_b_n_s));
                    max_contact_work=std::max(max_contact_work,std::abs(receipt.source.contact.work_residual_j));
                }
            }
            const auto native_before=tool.world.mechanicalTotals();
            const auto root=tool.world.mechanicalState(10);
            const Vec3 grip_local{-.08,0,0},arm=root.motion.orientation_world.rotate(grip_local);
            const Vec3 grip_velocity=root.motion.linear_velocity_m_s+cross(root.motion.angular_velocity_rad_s,arm);
            GripPull hand{};
            if (held) {
                // Current actual fixed constituents and actual root feedback;
                // one bounded local wrench, never distributed over the members.
                const auto feedback=makeGripFeedback(root,{root,tool.world.mechanicalState(1)},grip_local);
                hand=gripPull(feedback.held,feedback.grip_local,{-.24+6*step*timestep,0,0},{6,0,0},{},800,60,{},100,20);
                tool.world.pushBodyAt(10,hand.force,hand.grip);tool.world.twistBody(10,hand.torque);tool.world.wake(10);
                max_hand_force=std::max(max_hand_force,length(hand.force));max_hand_torque=std::max(max_hand_torque,length(hand.torque));
            }
            tool.world.step(timestep);++native_steps;
            const auto native_after=tool.world.mechanicalTotals();
            const auto root_after=tool.world.mechanicalState(10);
            const Vec3 velocity_after=root_after.motion.linear_velocity_m_s+
                cross(root_after.motion.angular_velocity_rad_s,root_after.motion.orientation_world.rotate(grip_local));
            const double work=dot(hand.force,.5*timestep*(grip_velocity+velocity_after))+
                dot(hand.torque,.5*timestep*(root.motion.angular_velocity_rad_s+root_after.motion.angular_velocity_rad_s));
            hand_work+=work;hand_impulse+=timestep*hand.force;
            const Vec3 angular=timestep*(cross(hand.grip,hand.force)+hand.torque);hand_angular+=angular;
            const double step_energy=native_after.kinetic_energy_j-native_before.kinetic_energy_j-work;
            native_step_energy+=step_energy;max_native_step_energy=std::max(max_native_step_energy,std::abs(step_energy));
            const auto load=tool.world.jointLoad(tool.fixing,{1,0,0});
            max_native_joint_tension=std::max(max_native_joint_tension,load.tension_n);
            max_native_joint_shear=std::max(max_native_joint_shear,load.shear_n);
            const auto step_p=native_after.linear_momentum_kg_m_s-native_before.linear_momentum_kg_m_s-timestep*hand.force;
            const auto step_l=native_after.angular_momentum_kg_m2_s-native_before.angular_momentum_kg_m2_s-angular;
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
                status_after.damping_dissipated_j-status_before.damping_dissipated_j+
                status_after.plastic_return_numerical_loss_j-status_before.plastic_return_numerical_loss_j;
        }
        const auto final_state=target.download(*backend);const auto final=totals(final_state,tool.world);const auto status=backend->status();
        const double wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
        require(status.total_steps==count&&contacts>0&&status.external_point_transfer.transfers==contacts,"coupled target/contact counts");
        require(status.contact.candidate_overflow==0&&status.node_contact.pair_overflow==0,"coupled fixture exceeded target contact capacity");
        require(status.max_tensile_stretch>0||status.max_compressive_strain>0||status.max_shear_strain>0,
            "tool contact never entered target constitutive sampling");
        const Vec3 residual_p=final.linear_momentum_kg_m_s-initial.linear_momentum_kg_m_s-p_error-hand_impulse;
        const Vec3 residual_l=final.angular_momentum_kg_m2_s-initial.angular_momentum_kg_m2_s-l_error-couple-hand_angular;
        const double unallocated=final.mechanicalEnergy()-initial.mechanicalEnergy()+loss+reconcile+
            status.removed_energy_j+status.plastic_work_j+status.damping_dissipated_j+status.plastic_return_numerical_loss_j-numerical-hand_work;
        require(std::isfinite(unallocated)&&std::isfinite(length(residual_p))&&std::isfinite(length(residual_l)),"coupled trajectory audit became nonfinite");
        near(final.mass_kg,initial.mass_kg,1e-12,"coupled experiment lost mass");
        near(unallocated,native_step_energy+target_step_energy,1e-10,"coupled unallocated energy attribution");
        std::cout<<(held?"Held ":"")<<(integrator==kBondXpbd?"XPBD ":"Verlet ")<<materialPresetName(preset)<<": cells="<<target.state.node_count<<" h="<<cell<<" dt="<<timestep<<" elapsed="<<count*timestep
            <<" s; contacts="<<contacts<<" broken="<<status.broken_bonds<<" damage="<<status.max_damage
            <<" strain="<<status.max_tensile_stretch<<"; plastic="<<status.plastic_work_j<<" J; contact loss="<<loss<<" J; reconcile="<<reconcile
            <<" J; numerical="<<numerical<<" J; phase work="<<max_contact_work<<" J; p residual="<<length(residual_p)
            <<" N s; L residual="<<length(residual_l)<<" kg m2/s; unallocated energy="<<unallocated
            <<" J; plastic return numerical="<<status.plastic_return_numerical_loss_j
            <<" J; integrator measured="<<status.integration_numerical_energy_j
            <<" J; native step="<<native_step_energy<<" J; target step="<<target_step_energy
            <<" J; native step p/L="<<length(native_step_p)<<"/"<<length(native_step_l)
            <<"; target step p/L="<<length(target_step_p)<<"/"<<length(target_step_l)
            <<"; max native step p/L="<<max_native_step_p<<"/"<<max_native_step_l
            <<"; hand work="<<hand_work<<" J; max hand force/torque="<<max_hand_force<<"/"<<max_hand_torque
            <<"; hand impulse="<<length(hand_impulse)<<"; max contact joint impulse="<<max_joint_impulse
            <<"; max native force-step error="<<max_native_step_energy<<" J; native fixing tension/shear="
            <<max_native_joint_tension<<"/"<<max_native_joint_shear<<" N\n";
        std::cout<<"  audited reference loop wall="<<wall<<" s; wall/sim="<<wall/(count*timestep)<<"\n";
        near(length(residual_p-native_step_p-target_step_p),0,1e-10,"combined momentum attribution");
        near(length(residual_l-native_step_l-target_step_l),0,1e-10,"combined angular attribution");
        // Retain the unforced native step gates. The newly added finite-force
        // experiment has the same declared SI float-transfer budgets as its
        // contact phase; accumulated native errors remain unclosed and printed.
        // No tolerance certifies overall hand/world conservation.
        const double native_p_budget=held?budget.linear_impulse_n_s:1e-6;
        const double native_l_budget=held?budget.angular_impulse_kg_m2_s:1e-7;
        require(length(residual_p-native_step_p)<1e-9&&length(target_step_p)<1e-9&&max_native_step_p<native_p_budget&&max_native_step_l<native_l_budget&&
            max_contact_work<1e-12,"coupled transfer/native-step arithmetic bounds");
        if (held) require(max_native_step_energy<budget.energy_j,"native forced-step energy budget");
        // Target angular and energy residuals remain measured, unclosed solver
        // behavior. No broadened angular/energy tolerance certifies conservation.
        if(preset==MaterialPreset::Glass)require(status.broken_bonds>0,"matched tool input no longer enters glass fracture");
        if(preset==MaterialPreset::Oak)require(status.broken_bonds==0,"oak comparison became a brittle substitute");
        // A moving hand can absorb work when the grip recoils against its
        // pull. Signed work must be retained, not forced to be positive.
        if (held) require(std::isfinite(hand_work)&&std::abs(hand_work)>0&&max_hand_force>0&&max_hand_force<=800+1e-10&&max_hand_torque<=60+1e-10&&
            max_joint_impulse>0&&tool.world.hasJoint(tool.fixing),"held reference lost bounded local hand or actual fixing");
        if(integrator==kBondVelocityVerlet) {
            require(length(target_step_l)<1e-9,"central-force target angular drift");
            near(target_step_energy,status.integration_numerical_energy_j,1e-10,"measured Verlet integration energy attribution");
            // A bounded/convergent reference experiment, not certification of
            // hand work, joint strength or complete world conservation.
            require(std::abs(target_step_energy)<.001*initial.mechanicalEnergy(),"reference target integration error exceeds 0.1% of initial energy");
        }
        if(timestep==dt)coarse_target_energy[preset]=target_step_energy;
        else require(std::abs(target_step_energy)<(integrator==kBondVelocityVerlet?.27:1.0)*std::abs(coarse_target_energy.at(preset)),
            "matched target energy refinement gate");
    }
    }
}
}
int main(){try{std::cout.precision(12);targetTransferPreservesHistoryAndAccounts(kBondXpbd);targetTransferPreservesHistoryAndAccounts(kBondVelocityVerlet);preparedContactIsImmutableAndInvalidates();trialAdmissionAndAbandonedPlans();pairedTrialsRestoreAndReplay();coupledMatchedTargets();
    std::cout<<"[PASS] checked native/CPU contact transfer and continuous target integration\n";return 0;}
    catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
