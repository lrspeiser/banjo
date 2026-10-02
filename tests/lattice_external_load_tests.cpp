// CPU load-boundary oracles; this is not a held-tool fracture qualification.
#include "fastlattice/FastLattice.hpp"
#include "fastlattice/ExternalLoads.hpp"
#include "fastlattice/LatticeWorking.hpp"
#include "material/MaterialCompiler.hpp"
#include "material/MaterialCatalog.hpp"
#include "matter/BoxLattice.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;
constexpr double cell=.04, fixture_dt=1e-7;

void require(bool value,const std::string &why) { if (!value) throw std::runtime_error(why); }
void near(double value,double expected,double tolerance,const std::string &why) {
    std::ostringstream message;message.precision(15);
    message<<why<<": got "<<value<<", expected "<<expected<<", tolerance "<<tolerance;
    require(std::isfinite(value)&&std::abs(value-expected)<=tolerance,message.str());
}
void nearVec(Vec3 value,Vec3 expected,double tolerance,const std::string &why) {
    near(length(value-expected),0,tolerance,why);
}

struct Fixture {
    MaterialDefinition material;
    LatticeAsset asset;
    ActiveMatter matter;
    LatticeSchedule schedule;
    LatticeState state;
    StepSettings<double> settings{};
    Fixture(MaterialPreset preset,bool bonded=false,unsigned cells_per_axis=3) : material(makeReferenceMaterial(preset,17)) {
        const auto compiled=withStrengthDerivedFailure(compileElasticLatticeReference(material,cell,1),material);
        const double side=cells_per_axis*cell;
        asset=generateBoxTileLattice({{side,side,side},cell,1},compiled);
        matter.asset=&asset;matter.material=compiled;
        const Vec3 origin{2,.6,-1};
        for (const auto &node:asset.nodes) {
            const Vec3 where=origin+node.local_position_m;
            matter.nodes.push_back({where,where,{},node.represented_volume_m3*compiled.density_kg_m3,{}});
            matter.reference_positions_world_m.push_back(where);
        }
        matter.bonds.resize(asset.bonds.size());
        if (!bonded) for (auto &bond:matter.bonds) { bond.alive=false;bond.damage=1; }
        schedule=buildLatticeSchedule(asset);
        state=buildLatticeState(matter,schedule,origin);
        settings.dt=fixture_dt;settings.constraint_iterations=4;settings.direct_arithmetic=0;
        settings.audit_energy=1;
    }
    std::unique_ptr<LatticeBackend> backend(Precision precision,bool parallel) const {
        auto out=parallel?makeParallelCpuLatticeBackend(schedule,precision,2,1):makeCpuLatticeBackend(schedule,precision);
        out->upload(state,settings,{});return out;
    }
};

Vec3 momentum(const LatticeState &state) {
    Vec3 out{};
    for (std::uint32_t i=0;i<state.node_count;++i)
        out+=state.mass[i]*Vec3{state.v[3*i],state.v[3*i+1],state.v[3*i+2]};
    return out;
}
Vec3 angular(const LatticeState &state) {
    Vec3 out{};
    for (std::uint32_t i=0;i<state.node_count;++i) {
        const Vec3 where=state.origin+Vec3{state.x0[3*i]+state.u[3*i],state.x0[3*i+1]+state.u[3*i+1],state.x0[3*i+2]+state.u[3*i+2]};
        out+=cross(where,state.mass[i]*Vec3{state.v[3*i],state.v[3*i+1],state.v[3*i+2]});
    }
    return out;
}
LatticeState download(LatticeBackend &backend,const LatticeState &source) {
    auto state=source;SphereState<double> sphere{};backend.download(state,sphere);return state;
}
RunStatus run(LatticeBackend &backend,std::uint64_t count) { RunControl control{};control.max_steps=count;return backend.run(control); }

std::vector<Vec3> cornerLoads(const Fixture &fixture) {
    std::vector<Vec3> out(fixture.state.node_count);out.front()={8,-2,1};out.back()={-3,4,-2};return out;
}

void finiteLoadsExpireAndKeepACompleteLedger() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Fixture fixture(preset);
        for (const auto precision:{Precision::Double,Precision::Float}) {
            auto serial=fixture.backend(precision,false), parallel=fixture.backend(precision,true);
            const auto forces=cornerLoads(fixture);
            serial->setExternalForces(forces,64);parallel->setExternalForces(forces,64);
            run(*serial,20);run(*parallel,20);
            const auto status=run(*serial,108),other=run(*parallel,108);
            const auto result=download(*serial,fixture.state),result2=download(*parallel,fixture.state);
            require(result.v==result2.v&&result.u==result2.u&&result.alive==result2.alive,
                    "serial and parallel driven state differ");
            require(status.external_load.work_j==other.external_load.work_j&&
                    status.external_load.impulse_n_s.x==other.external_load.impulse_n_s.x,
                    "serial and parallel load reductions differ");
            require(status.external_load.steps==64,"load span reset across run calls or failed to expire");
            const double actual_dt=precision==Precision::Float?static_cast<double>(static_cast<float>(fixture_dt)):fixture_dt;
            near(status.external_load.elapsed_s,64*actual_dt,1e-19,"finite load elapsed time");
            // The unforced drift reconstructs v=(u-u_prev)/fixture_dt each step. Allow
            // accumulated float arithmetic, rather than treating the force
            // ledger as the final backend momentum. gamma(8*128) is a
            // conservative bound for this free-node, zero-origin-u oracle's
            // kick/predict/reconstruct operations; not a constitutive tolerance.
            const double unit_roundoff=std::numeric_limits<float>::epsilon()/2;
            const double gamma=(8*128*unit_roundoff)/(1-8*128*unit_roundoff);
            const double absolute_impulse=64*actual_dt*(length(forces.front())+length(forces.back()));
            const double tolerance=precision==Precision::Float?gamma*absolute_impulse:2e-15;
            std::cout<<"  load diagnostics "<<materialPresetName(preset)<<" "<<precisionName(precision)
                <<": requested residual="<<length(momentum(result)-64*actual_dt*Vec3{5,2,-1})
                <<"; kick-vs-request residual="<<length(status.external_load.impulse_n_s-status.external_load.requested_impulse_n_s)
                <<"; kick-vs-result residual="<<length(momentum(result)-status.external_load.impulse_n_s)
                <<"; work residual="<<latticeStateKineticEnergy(result)-status.external_load.work_j<<"\n";
            nearVec(momentum(result),64*actual_dt*Vec3{5,2,-1},tolerance,"total material-derived momentum");
            nearVec(momentum(result),status.external_load.impulse_n_s,tolerance,"delivered load momentum ledger");
            nearVec(angular(result),status.external_load.angular_impulse_kg_m2_s,4*tolerance,"angular impulse about world origin");
            const double energy=latticeStateKineticEnergy(result);
            near(energy,status.external_load.work_j,precision==Precision::Float?2*gamma*std::abs(status.external_load.work_j):2e-18,
                 "free-node final energy versus external phase work");
            const auto after=run(*serial,1);
            require(after.external_load.steps==64&&after.external_load.work_j==status.external_load.work_j,
                    "expired load applied again");
            std::cout<<"  "<<materialPresetName(preset)<<" "<<precisionName(precision)
                     <<": h="<<cell<<" dt="<<actual_dt<<" mass="<<fixture.asset.total_mass_kg
                     <<" kg; momentum residual="<<length(momentum(result)-status.external_load.impulse_n_s)
                     <<" N s; angular residual="<<length(angular(result)-status.external_load.angular_impulse_kg_m2_s)
                     <<" kg m2/s; work="<<status.external_load.work_j<<" J; energy residual="
                     <<energy-status.external_load.work_j<<" J; wall="<<status.wall_seconds<<" s\n";
        }
    }
}

template <typename Real>
void isolatedKickOracle(MaterialPreset preset) {
    Fixture fixture(preset);
    auto working=WorkingLattice<Real>::fromState(fixture.state,fixture.schedule);
    // Nonzero initial motion distinguishes signed work from force magnitude.
    working.v[0]=static_cast<Real>(-.001);
    working.v[working.v.size()-1]=static_cast<Real>(.002);
    const auto state=[&]() {
        auto out=fixture.state;working.toState(out);
        for (std::size_t i=0;i<out.mass.size();++i) out.mass[i]=static_cast<double>(working.mass[i]);
        return out;
    };
    const auto before=state();
    const auto original_u=working.u;
    const auto original_alive=working.alive;
    const auto original_compliance=working.compliance,original_threshold=working.threshold;
    CpuExternalLoads<Real> loads;loads.reset(fixture.state.origin);
    loads.set(cornerLoads(fixture),64,working.arrays());
    ExternalLoadLedger ledger;
    for (unsigned i=0;i<64;++i) loads.kick(working.arrays(),static_cast<Real>(fixture_dt),ledger);
    const auto after=state();
    nearVec(momentum(after)-momentum(before),ledger.impulse_n_s,1e-17,"isolated kick linear momentum");
    // Angular accounting uses the backend's actual position precision.
    auto angular_before=before,angular_after=after;
    for (std::size_t i=0;i<before.x0.size();++i)
        angular_before.x0[i]=angular_after.x0[i]=static_cast<double>(working.x0[i]);
    nearVec(angular(angular_after)-angular(angular_before),ledger.angular_impulse_kg_m2_s,1e-17,
            "isolated kick angular momentum");
    near(latticeStateKineticEnergy(after)-latticeStateKineticEnergy(before),ledger.work_j,1e-20,
         "isolated kick signed kinetic work");
    require(working.u==original_u&&working.alive==original_alive,"force kick assigned positions or bond state");
    require(working.compliance==original_compliance&&working.threshold==original_threshold,
            "force kick replaced the declared bond law");
    std::cout<<"  isolated "<<materialPresetName(preset)<<" "<<(sizeof(Real)==4?"float":"double")
             <<": energy residual="<<latticeStateKineticEnergy(after)-latticeStateKineticEnergy(before)-ledger.work_j<<" J\n";
}

void isolatedKicksCloseBeforePositionReconstruction() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        isolatedKickOracle<double>(preset);isolatedKickOracle<float>(preset);
    }
}

void invalidReplacementAndCancellationAreAtomic() {
    for (const auto precision:{Precision::Double,Precision::Float}) for (bool parallel:{false,true}) {
        Fixture fixture(MaterialPreset::Oak);
        auto backend=fixture.backend(precision,parallel);
        auto forces=cornerLoads(fixture);backend->setExternalForces(forces,4);
        auto invalid=forces;invalid[1].x=std::numeric_limits<double>::quiet_NaN();
        for (const auto &bad:{std::vector<Vec3>{Vec3{1,2,3}},invalid}) {
            bool refused=false;try { backend->setExternalForces(bad,20); } catch(const std::invalid_argument &) { refused=true; }
            require(refused,"invalid force replacement admitted");
        }
        bool refused=false;try { backend->setExternalForces(forces,0); } catch(const std::invalid_argument &) { refused=true; }
        require(refused,"nonempty zero-span force admitted");
        run(*backend,4);const auto saved=download(*backend,fixture.state);
        nearVec(momentum(saved),4*fixture_dt*Vec3{5,2,-1},precision==Precision::Float?1e-11:1e-16,"refusal retained original load");
        backend->setExternalForces(forces,20);backend->setExternalForces({},0);
        const auto status=run(*backend,20);require(status.external_load.steps==4,"cancelled load still ran");
        backend->upload(fixture.state,fixture.settings,{});
        const auto fresh=run(*backend,4);
        require(fresh.external_load.steps==0&&fresh.external_load.work_j==0&&momentum(download(*backend,fixture.state)).x==0,
                "upload retained old force or ledger");
    }
}

void emptyAndZeroLoadsKeepUnforcedPhysicsBitIdentical() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Fixture fixture(preset,true);
        for (auto precision:{Precision::Double,Precision::Float}) for (bool parallel:{false,true}) {
            auto baseline=fixture.backend(precision,parallel),loaded=fixture.backend(precision,parallel);
            loaded->setExternalForces(std::vector<Vec3>(fixture.state.node_count),64);
            run(*baseline,128);const auto status=run(*loaded,128);
            const auto a=download(*baseline,fixture.state),b=download(*loaded,fixture.state);
            require(a.v==b.v&&a.u==b.u&&a.damage==b.damage&&a.alive==b.alive&&a.plastic_extension==b.plastic_extension,
                    "zero-force path changed unforced state");
            require(status.external_load.steps==0&&status.external_load.work_j==0,"zero load fabricated external work");
        }
    }
}

void aLoadedSolidKeepsItsOwnMassAndLaw() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Fixture fixture(preset,true);
        auto serial=fixture.backend(Precision::Double,false),parallel=fixture.backend(Precision::Double,true);
        std::vector<Vec3> forces(fixture.state.node_count);
        for (auto &force:forces) force={20./forces.size(),0,0};
        serial->setExternalForces(forces,64);parallel->setExternalForces(forces,64);
        const auto status=run(*serial,128);run(*parallel,128);
        const auto a=download(*serial,fixture.state),b=download(*parallel,fixture.state);
        require(a.u==b.u&&a.v==b.v&&a.damage==b.damage,"driven solid lost serial/parallel parity");
        require(status.broken_bonds==0,"uniform translation broke an unloaded bond");
        const double expected=20*64*fixture_dt/fixture.asset.total_mass_kg;
        near(momentum(a).x,20*64*fixture_dt,1e-11,"solid force integrated once");
        for (std::uint32_t i=0;i<a.node_count;++i) near(a.v[3*i],expected,1e-10,"density-derived acceleration");
        const double residual=latticeStateKineticEnergy(a)+latticeStateElasticEnergy(a)-status.external_load.work_j;
        near(residual,0,2e-14,"uniform solid local energy ledger");
        std::cout<<"  solid "<<materialPresetName(preset)<<": density="<<fixture.material.density_kg_m3
                 <<" E="<<fixture.material.young_modulus_pa<<" Pa; speed="<<expected
                 <<" m/s; local energy residual="<<residual<<" J\n";
    }
}

void opposedLoadsActuallyDeformTheExistingSolid() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Fixture fixture(preset,true);
        auto serial=fixture.backend(Precision::Double,false),parallel=fixture.backend(Precision::Double,true);
        std::vector<Vec3> forces(fixture.state.node_count);
        const Vec3 pull=(20/std::sqrt(3.))*Vec3{1,1,1};
        forces.front()=-1*pull;forces.back()=pull;
        serial->setExternalForces(forces,64);parallel->setExternalForces(forces,64);
        const auto status=run(*serial,128);const auto other=run(*parallel,128);
        const auto a=download(*serial,fixture.state),b=download(*parallel,fixture.state);
        require(a.u==b.u&&a.v==b.v&&a.damage==b.damage&&a.plastic_extension==b.plastic_extension&&
                status.external_load.work_j==other.external_load.work_j,
                "localized driven solid lost CPU parity");
        const double stored=latticeStateElasticEnergy(a);
        require(stored>0&&std::isfinite(stored)&&status.external_load.work_j>0,
                "opposed forces did not load the existing elastic bonds");
        require(status.broken_bonds==0&&a.alive==fixture.state.alive,
                "small opposed load unexpectedly fractured the coupon");
        nearVec(momentum(a),status.external_load.impulse_n_s,1e-10,"opposed-load numerical momentum residual");
        // Report the projection/integration residual. No claim that the new
        // external phase closes the whole constitutive pipeline's energy.
        const double residual=latticeStateKineticEnergy(a)+stored+status.removed_energy_j+
            status.plastic_work_j+status.damping_dissipated_j+status.striker_dissipated_j+
            status.node_contact.dissipated_kinetic_energy_j-status.external_load.work_j;
        std::cout<<"  opposed "<<materialPresetName(preset)<<": elastic="<<stored
                 <<" J; external work="<<status.external_load.work_j<<" J; momentum residual="
                 <<length(momentum(a)-status.external_load.impulse_n_s)<<" N s; unclosed energy="<<residual<<" J\n";
    }
}

void immovableAndUnrepresentableLoadsRefuse() {
    Fixture fixture(MaterialPreset::Iron);
    fixture.state.inv_mass.front()=0;
    auto backend=fixture.backend(Precision::Double,false);
    bool refused=false;try { backend->setExternalForces(cornerLoads(fixture),1); } catch(const std::invalid_argument &) { refused=true; }
    require(refused,"force on an immovable node silently disappeared");
    fixture.state.inv_mass.front()=1/fixture.state.mass.front();
    auto floating=fixture.backend(Precision::Float,false);
    auto forces=cornerLoads(fixture);forces.front().x=1e100;
    refused=false;try { floating->setExternalForces(forces,1); } catch(const std::invalid_argument &) { refused=true; }
    require(refused,"force not representable in float admitted");
    backend=fixture.backend(Precision::Double,false);forces.front().x=1e308;
    backend->setExternalForces(forces,1);
    refused=false;try { run(*backend,1); } catch(const std::overflow_error &) { refused=true; }
    require(refused,"overflowing work ledger admitted");
    const auto untouched=download(*backend,fixture.state);
    require(untouched.v==fixture.state.v&&untouched.u==fixture.state.u&&backend->status().external_load.steps==0,
            "overflow partially changed velocities or applied ledger");
}

void withdrawingEnergyKeepsAnEnabledBudgetEnabled() {
    Fixture fixture(MaterialPreset::Oak);
    fixture.state.v.front()=1;
    std::vector<Vec3> forces(fixture.state.node_count);forces.front().x=-10;
    for (bool parallel:{false,true}) {
        auto backend=fixture.backend(Precision::Double,parallel);backend->setExternalForces(forces,64);
        RunControl control{};control.max_steps=64;control.removable_energy_j=1e-9;
        const auto status=backend->run(control);
        require(status.exit_reason==6&&status.total_steps==1&&status.external_load.work_j<0,
                "withdrawn caller budget became an unlimited run");
    }
}

ExternalWrench cubeWrench(const Fixture &fixture) {
    ExternalWrench out{"player-a",{},fixture.state.origin+Vec3{.02,-.03,.04},{20,-10,5},{.5,-.75,1.25}};
    for (std::uint32_t i=0;i<fixture.state.node_count;++i) out.nodes.push_back(i);
    return out;
}

void aWrenchMatchesTheRigidCubeOracle() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Fixture fixture(preset);
        const auto wrench=cubeWrench(fixture);
        const double mass=fixture.asset.total_mass_kg;
        // 3x3x3 equally weighted points at -40,0,+40 mm. Point inertia, not
        // the finite cell spin that this translational lattice does not carry.
        const double inertia=mass*(4./3)*cell*cell;
        const Vec3 moment=wrench.torque_n_m+cross(wrench.point_world_m-fixture.state.origin,wrench.force_n);
        const double expected_work=.5*fixture_dt*fixture_dt*(lengthSquared(wrench.force_n)/mass+lengthSquared(moment)/inertia);
        for (const auto precision:{Precision::Double,Precision::Float}) {
            auto serial=fixture.backend(precision,false),parallel=fixture.backend(precision,true);
            serial->setExternalWrenches({wrench},1);parallel->setExternalWrenches({wrench},1);
            const auto status=run(*serial,1),other=run(*parallel,1);
            const auto result=download(*serial,fixture.state),result2=download(*parallel,fixture.state);
            require(result.v==result2.v&&result.u==result2.u&&status.external_load.work_j==other.external_load.work_j,
                    "wrench lost CPU parity");
            const double actual_dt=precision==Precision::Float?static_cast<double>(static_cast<float>(fixture_dt)):fixture_dt;
            const double tolerance=precision==Precision::Float?1e-11:1e-16;
            nearVec(momentum(result),actual_dt*wrench.force_n,tolerance,"cube wrench linear resultant");
            nearVec(angular(result),actual_dt*(cross(wrench.point_world_m,wrench.force_n)+wrench.torque_n_m),
                    4*tolerance,"cube wrench moment about world origin");
            near(status.external_load.work_j,expected_work,precision==Precision::Float?1e-6*expected_work:1e-20,
                 "rigid point-cube analytical work");
            near(latticeStateKineticEnergy(result),status.external_load.work_j,
                 precision==Precision::Float?1e-6*expected_work:1e-20,"cube wrench kick work");
            require(status.external_sources.size()==1&&status.external_sources.front().source==wrench.source&&
                    status.external_sources.front().load.work_j==status.external_load.work_j,
                    "single hand source ledger was lost");
            std::cout<<"  wrench "<<materialPresetName(preset)<<" "<<precisionName(precision)
                     <<": point inertia="<<inertia<<" kg m2; work="<<status.external_load.work_j
                     <<" J; work residual="<<status.external_load.work_j-expected_work
                     <<" J; angular residual="<<length(angular(result)-status.external_load.angular_impulse_kg_m2_s)<<" kg m2/s\n";
        }
    }
}

void wrenchesFollowCurrentGeometryAndKeepEachSource() {
    Fixture fixture(MaterialPreset::Oak);
    for (std::uint32_t i=0;i<fixture.state.node_count;++i) {
        const Vec3 p{fixture.state.x0[3*i],fixture.state.x0[3*i+1],fixture.state.x0[3*i+2]};
        const Vec3 velocity=Vec3{3,-2,1}+cross(Vec3{0,30,0},p);
        fixture.state.v[3*i]=velocity.x;fixture.state.v[3*i+1]=velocity.y;fixture.state.v[3*i+2]=velocity.z;
    }
    const auto before_p=momentum(fixture.state),before_l=angular(fixture.state);
    auto a=cubeWrench(fixture),b=a;b.source="player-b";b.nodes.clear();
    a.nodes.clear();
    for (std::uint32_t i=0;i<fixture.state.node_count;++i) (i<9?a.nodes:b.nodes).push_back(i);
    a.force_n={8,2,1};b.force_n={-3,-4,.5};
    a.torque_n_m={.1,.2,-.3};b.torque_n_m={-.1,.05,.2};
    auto backend=fixture.backend(Precision::Double,false),permuted=fixture.backend(Precision::Double,true);
    backend->setExternalWrenches({b,a},64);
    std::reverse(a.nodes.begin(),a.nodes.end());std::reverse(b.nodes.begin(),b.nodes.end());
    permuted->setExternalWrenches({a,b},64);
    run(*backend,20);run(*permuted,20);
    const auto status=run(*backend,108),other=run(*permuted,108);
    const auto result=download(*backend,fixture.state),result2=download(*permuted,fixture.state);
    require(result.u==result2.u&&result.v==result2.v&&status.external_load.work_j==other.external_load.work_j,
            "source/node ordering changed the driven state");
    require(status.external_load.steps==64&&status.external_sources.size()==2,"finite multi-source span failed");
    Vec3 supplied{},moment{};double work=0;
    for (const auto &source:status.external_sources) {
        require(source.load.steps==64,"one hand did not receive its own elapsed load span");
        const auto &asked=source.source==a.source?a:b;
        nearVec(source.load.impulse_n_s,64*fixture_dt*asked.force_n,1e-14,"individual delivered source impulse");
        nearVec(source.load.angular_impulse_kg_m2_s,
                64*fixture_dt*(cross(asked.point_world_m,asked.force_n)+asked.torque_n_m),1e-13,
                "individual source world moment follows changing geometry");
        nearVec(source.load.requested_angular_impulse_kg_m2_s,
                64*fixture_dt*(cross(asked.point_world_m,asked.force_n)+asked.torque_n_m),1e-14,
                "requested moment retained independently of the delivered moment");
        supplied+=source.load.impulse_n_s;moment+=source.load.angular_impulse_kg_m2_s;work+=source.load.work_j;
    }
    nearVec(supplied,status.external_load.impulse_n_s,1e-15,"source impulse sum");
    nearVec(moment,status.external_load.angular_impulse_kg_m2_s,1e-15,"source angular impulse sum");
    near(work,status.external_load.work_j,1e-15,"source work sum");
    nearVec(momentum(result)-before_p,supplied,1e-10,"moving free-node final momentum residual");
    nearVec(angular(result)-before_l,moment,1e-10,"moving free-node final angular residual");
    std::cout<<"  two-source moving oracle: momentum residual="<<length(momentum(result)-before_p-supplied)
             <<" N s; angular residual="<<length(angular(result)-before_l-moment)<<" kg m2/s; wall="<<status.wall_seconds<<" s\n";
    const auto after=run(*backend,1);
    require(after.external_sources.front().load.steps==64,"expired source still applied");
    backend->upload(fixture.state,fixture.settings,{});
    require(run(*backend,1).external_sources.empty(),"upload retained another actor's load ledger");
}

void badWrenchesPreserveTheExistingLoad() {
    for (const auto precision:{Precision::Double,Precision::Float}) for (bool parallel:{false,true}) {
        Fixture fixture(MaterialPreset::Glass);
        auto backend=fixture.backend(precision,parallel);const auto original=cubeWrench(fixture);
        backend->setExternalWrenches({original},4);
        auto duplicate=original;duplicate.nodes.push_back(duplicate.nodes.front());
        auto outside=original;outside.nodes.front()=fixture.state.node_count;
        auto empty=original;empty.nodes.clear();
        auto unnamed=original;unnamed.source.clear();
        auto invalid=original;invalid.torque_n_m.x=std::numeric_limits<double>::quiet_NaN();
        auto overflow=original;overflow.force_n.x=std::numeric_limits<double>::max();overflow.force_n.y=overflow.force_n.x;
        auto overlap=original;overlap.source="player-b";
        for (const auto &bad:std::vector<std::vector<ExternalWrench>>{{duplicate},{outside},{empty},{unnamed},{invalid},{overflow},
                                                                  {original,original},{original,overlap}}) {
            bool refused=false;try { backend->setExternalWrenches(bad,20); } catch (const std::invalid_argument &) { refused=true; }
            require(refused,"invalid wrench replacement admitted");
        }
        bool refused=false;try { backend->setExternalWrenches({original},0); } catch(const std::invalid_argument &) { refused=true; }
        require(refused,"nonempty zero-span wrench admitted");
        const auto status=run(*backend,4);
        require(status.external_sources.size()==1&&status.external_sources.front().source==original.source&&
                status.external_sources.front().load.steps==4,"invalid replacement discarded the prior source");
        backend->setExternalWrenches({},0);
        require(run(*backend,20).external_load.steps==4,"cancelled wrench continued running");
    }
}

void unsupportedTwistAndChangedRankRefuse() {
    Fixture fixture(MaterialPreset::Iron);
    for (std::uint32_t i=0;i<fixture.state.node_count;++i) {
        fixture.state.x0[3*i+1]=0;fixture.state.x0[3*i+2]=0;
    }
    auto good=cubeWrench(fixture);good.force_n={};good.point_world_m=fixture.state.origin;good.torque_n_m={0,1,0};
    for (bool parallel:{false,true}) {
        auto backend=fixture.backend(Precision::Double,parallel);backend->setExternalWrenches({good},1);
        auto twist=good;twist.torque_n_m={1,0,0};
        bool refused=false;try { backend->setExternalWrenches({twist},1); } catch (const std::invalid_argument &) { refused=true; }
        require(refused,"collinear point nodes invented axial spin");
        require(run(*backend,1).external_sources.front().load.steps==1,"rank refusal lost the compatible torque");
    }
    Fixture cube(MaterialPreset::Oak);
    auto working=WorkingLattice<double>::fromState(cube.state,cube.schedule);
    auto wrench=cubeWrench(cube);CpuExternalLoads<double> loads;loads.reset(cube.state.origin);
    loads.setWrenches({wrench},4,working.arrays());
    ExternalLoadLedger ledger;std::vector<ExternalWrenchLedger> sources;
    loads.kick(working.arrays(),fixture_dt,ledger,&sources);
    // Analytical boundary invalidation, not a physical collapse experiment:
    // a later solve can change this load region's rank before its next kick.
    for (std::size_t i=0;i<working.u.size();++i) working.u[i]=-working.x0[i];
    const auto before_v=working.v;const auto before_work=ledger.work_j;
    bool refused=false;try { loads.kick(working.arrays(),fixture_dt,ledger,&sources); } catch(const std::invalid_argument &) { refused=true; }
    require(refused&&working.v==before_v&&ledger.steps==1&&ledger.work_j==before_work&&sources.front().load.steps==1,
            "rank change partially advanced a force or source ledger");
}

void sourceOverflowAndZeroWrenchesAreAtomic() {
    Fixture fixture(MaterialPreset::Oak);
    auto wrench=cubeWrench(fixture);wrench.point_world_m=fixture.state.origin;wrench.force_n={1e155,0,0};wrench.torque_n_m={};
    auto working=WorkingLattice<double>::fromState(fixture.state,fixture.schedule);
    CpuExternalLoads<double> loads;loads.reset(fixture.state.origin);loads.setWrenches({wrench},1,working.arrays());
    ExternalLoadLedger ledger;std::vector<ExternalWrenchLedger> sources{{wrench.source,{}}};
    sources.front().load.work_j=std::numeric_limits<double>::max();
    const auto before_v=working.v;
    bool refused=false;try { loads.kick(working.arrays(),fixture_dt,ledger,&sources); } catch(const std::overflow_error &) { refused=true; }
    require(refused&&working.v==before_v&&ledger.steps==0&&sources.front().load.steps==0&&
            sources.front().load.work_j==std::numeric_limits<double>::max(),"source ledger overflow partially applied a wrench");
    wrench.force_n={};
    for (auto precision:{Precision::Double,Precision::Float}) for (bool parallel:{false,true}) {
        auto baseline=fixture.backend(precision,parallel),zero=fixture.backend(precision,parallel);
        zero->setExternalWrenches({wrench},64);run(*baseline,128);const auto status=run(*zero,128);
        const auto a=download(*baseline,fixture.state),b=download(*zero,fixture.state);
        require(a.v==b.v&&a.u==b.u&&status.external_load.steps==0&&status.external_sources.empty(),
                "zero wrench changed unforced physics or fabricated a source receipt");
    }
}

void wrenchMappingRespectsCoordinateChanges() {
    Fixture fixture(MaterialPreset::Glass);
    const auto original=cubeWrench(fixture);
    const Vec3 shift{1e6,-2e6,3e6};
    const auto rotate=[](Vec3 v) { return Vec3{v.z,v.y,-v.x}; };
    for (auto precision:{Precision::Double,Precision::Float}) for (bool parallel:{false,true}) {
        auto baseline=fixture.backend(precision,parallel);baseline->setExternalWrenches({original},1);
        const auto status=run(*baseline,1);const auto before=download(*baseline,fixture.state);
        auto translated_state=fixture.state;translated_state.origin+=shift;
        auto translated=fixture.backend(precision,parallel);translated->upload(translated_state,fixture.settings,{});
        auto moved=original;moved.point_world_m+=shift;translated->setExternalWrenches({moved},1);
        const auto moved_status=run(*translated,1);
        const auto moved_state=download(*translated,translated_state);
        auto rotated_state=fixture.state;rotated_state.origin=rotate(rotated_state.origin);
        for (std::uint32_t i=0;i<rotated_state.node_count;++i) {
            const Vec3 p=rotate({rotated_state.x0[3*i],rotated_state.x0[3*i+1],rotated_state.x0[3*i+2]});
            rotated_state.x0[3*i]=p.x;rotated_state.x0[3*i+1]=p.y;rotated_state.x0[3*i+2]=p.z;
        }
        auto rotated=fixture.backend(precision,parallel);rotated->upload(rotated_state,fixture.settings,{});
        auto turned=original;turned.point_world_m=rotate(turned.point_world_m);
        turned.force_n=rotate(turned.force_n);turned.torque_n_m=rotate(turned.torque_n_m);
        rotated->setExternalWrenches({turned},1);const auto turned_status=run(*rotated,1);
        const auto turned_state=download(*rotated,rotated_state);
        const double tolerance=precision==Precision::Float?3e-11:1e-13;
        for (std::uint32_t i=0;i<before.node_count;++i) {
            const Vec3 v{before.v[3*i],before.v[3*i+1],before.v[3*i+2]};
            nearVec({moved_state.v[3*i],moved_state.v[3*i+1],moved_state.v[3*i+2]},v,tolerance,
                    "world-origin shift changed the node load");
            nearVec({turned_state.v[3*i],turned_state.v[3*i+1],turned_state.v[3*i+2]},rotate(v),tolerance,
                    "coordinate rotation changed the physical wrench");
        }
        nearVec(moved_status.external_load.angular_impulse_kg_m2_s,
                status.external_load.angular_impulse_kg_m2_s+cross(shift,moved_status.external_load.impulse_n_s),1e-9,
                "world-origin angular impulse translation rule");
        nearVec(turned_status.external_load.angular_impulse_kg_m2_s,
                rotate(status.external_load.angular_impulse_kg_m2_s),4*tolerance,"angular impulse rotation rule");
    }
}

void loadedNodesAlsoRunThroughTheThreadPool() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Fixture fixture(preset,false,5);
        require(fixture.state.node_count==125,"parallel fixture must exceed the 64-node pool threshold");
        const auto wrench=cubeWrench(fixture);
        for (auto precision:{Precision::Double,Precision::Float}) {
            auto serial=fixture.backend(precision,false),parallel=fixture.backend(precision,true);
            serial->setExternalWrenches({wrench},16);parallel->setExternalWrenches({wrench},16);
            const auto status=run(*serial,64),other=run(*parallel,64);
            const auto a=download(*serial,fixture.state),b=download(*parallel,fixture.state);
            require(a.u==b.u&&a.v==b.v&&a.alive==b.alive&&
                    status.external_load.work_j==other.external_load.work_j&&
                    status.external_load.angular_impulse_kg_m2_s.x==other.external_load.angular_impulse_kg_m2_s.x&&
                    status.external_sources.front().load.steps==16&&other.external_sources.front().load.steps==16,
                    "wrench state/source ledger changed through actual parallel node phases");
        }
    }
}
} // namespace

int main() {
    const std::vector<std::pair<const char *,std::function<void()>>> checks={
        {"finite loads expire and account for linear/angular momentum and work",finiteLoadsExpireAndKeepACompleteLedger},
        {"isolated kicks close before position reconstruction",isolatedKicksCloseBeforePositionReconstruction},
        {"invalid replacement, cancellation and upload keep load state",invalidReplacementAndCancellationAreAtomic},
        {"empty and zero loads retain unforced physics",emptyAndZeroLoadsKeepUnforcedPhysicsBitIdentical},
        {"loaded solids retain material mass, law and CPU parity",aLoadedSolidKeepsItsOwnMassAndLaw},
        {"opposed loads deform the existing solid with CPU parity",opposedLoadsActuallyDeformTheExistingSolid},
        {"immovable and unrepresentable loads refuse without partial kicks",immovableAndUnrepresentableLoadsRefuse},
        {"withdrawing energy never disables a declared ceiling",withdrawingEnergyKeepsAnEnabledBudgetEnabled},
        {"wrenches match a rigid point-cube oracle",aWrenchMatchesTheRigidCubeOracle},
        {"wrenches follow current geometry and retain each source",wrenchesFollowCurrentGeometryAndKeepEachSource},
        {"invalid wrenches preserve the existing load",badWrenchesPreserveTheExistingLoad},
        {"unsampled twist and changed rank refuse atomically",unsupportedTwistAndChangedRankRefuse},
        {"source overflow and zero wrenches are atomic",sourceOverflowAndZeroWrenchesAreAtomic},
        {"wrenches respect coordinate translation and rotation",wrenchMappingRespectsCoordinateChanges},
        {"driven nodes retain parity through the thread pool",loadedNodesAlsoRunThroughTheThreadPool}};
    int failed=0;std::cout.precision(12);
    for (const auto &[name,check]:checks) {
        std::cout<<name<<"\n";
        try { check();std::cout<<"  ok\n"; } catch(const std::exception &e) { ++failed;std::cout<<"  FAILED: "<<e.what()<<"\n"; }
    }
    return failed?1:0;
}
