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
    Fixture(MaterialPreset preset,bool bonded=false) : material(makeReferenceMaterial(preset,17)) {
        const auto compiled=withStrengthDerivedFailure(compileElasticLatticeReference(material,cell,1),material);
        asset=generateBoxTileLattice({{.12,.12,.12},cell,1},compiled);
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
        {"withdrawing energy never disables a declared ceiling",withdrawingEnergyKeepsAnEnabledBudgetEnabled}};
    int failed=0;std::cout.precision(12);
    for (const auto &[name,check]:checks) {
        std::cout<<name<<"\n";
        try { check();std::cout<<"  ok\n"; } catch(const std::exception &e) { ++failed;std::cout<<"  FAILED: "<<e.what()<<"\n"; }
    }
    return failed?1:0;
}
