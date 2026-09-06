#include "material/Plasticity.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;

void require(bool condition,std::string_view message){
    if(!condition)throw std::runtime_error(std::string(message));
}
void near(double actual,double expected,double tolerance,std::string_view message){
    if(!std::isfinite(actual)||std::abs(actual-expected)>tolerance){
        throw std::runtime_error(std::string(message)+": actual="+std::to_string(actual)+" expected="+std::to_string(expected));}
}

J2Material referenceJ2(){
    return {
        .family=ContinuumConstitutiveFamily::SmallStrainIsotropicJ2,
        .young_modulus_pa=200.e9,
        .poisson_ratio=.3,
        .initial_yield_stress_pa=200.e6,
        .isotropic_hardening_modulus_pa=10.e9,
        .maximum_total_strain_norm=.05,
    };
}

void tensorConventionAndAnalyticalPureShearReturn(){
    const auto material=referenceJ2();const double shear=material.young_modulus_pa/(2.*(1.+material.poisson_ratio));
    constexpr double engineering_shear=.006;
    const SymmetricTensor3 increment{.xy=engineering_shear/2.};
    near(doubleContract(increment,increment),engineering_shear*engineering_shear/2.,1e-20,
        "tensor shear components receive factor two in double contraction");
    const double trial_tau=shear*engineering_shear;
    const double trial_q=std::sqrt(3.)*trial_tau;
    const double expected_plastic_increment=(trial_q-material.initial_yield_stress_pa)/(3.*shear+material.isotropic_hardening_modulus_pa);
    const auto update=integrateJ2StrainIncrement(material,{},increment);
    require(update.yielded,"pure shear beyond von Mises yield must return plastically");
    near(update.trial_stress_pa.xy,trial_tau,1e-6,"elastic pure-shear trial stress");
    near(update.trial_equivalent_stress_pa,trial_q,1e-6,"pure-shear von Mises trial stress");
    near(update.equivalent_plastic_strain_increment,expected_plastic_increment,1e-15,
        "closed-form radial-return plastic multiplier");
    const double expected_yield=material.initial_yield_stress_pa+
        material.isotropic_hardening_modulus_pa*expected_plastic_increment;
    near(vonMisesEquivalentStressPa(update.stress_pa),expected_yield,1e-5,
        "returned stress lies on linearly hardened yield surface");
    near(update.stress_pa.xy,expected_yield/std::sqrt(3.),1e-5,
        "returned pure-shear tensor stress");
    near(trace(update.state.plastic_strain),0.,1e-18,"J2 plastic flow is isochoric");
}

void unloadingLeavesPermanentPlasticStrainAndReloadsElastically(){
    const auto material=referenceJ2();const double shear=material.young_modulus_pa/(2.*(1.+material.poisson_ratio));
    const auto loaded=integrateJ2StrainIncrement(material,{},SymmetricTensor3{.xy=.003});
    require(loaded.yielded&&loaded.state.plastic_strain.xy>0.,"loading must create permanent tensor shear strain");
    const double accumulated=loaded.state.equivalent_plastic_strain;
    const double dissipation=loaded.state.plastic_dissipation_j_m3;
    const SymmetricTensor3 unload{.xy=-loaded.stress_pa.xy/(2.*shear)};
    const auto unloaded=integrateJ2StrainIncrement(material,loaded.state,unload);
    require(!unloaded.yielded,"unloading to zero stress remains elastic");
    near(unloaded.stress_pa.xy,0.,1e-5,"unloaded shear stress");
    near(unloaded.state.total_strain.xy,loaded.state.plastic_strain.xy,1e-15,
        "zero-stress state retains permanent plastic shear");
    near(unloaded.state.equivalent_plastic_strain,accumulated,0.,"unloading cannot heal equivalent plastic history");
    near(unloaded.state.plastic_dissipation_j_m3,dissipation,0.,"unloading cannot refund plastic dissipation");

    const double current_yield=material.initial_yield_stress_pa+
        material.isotropic_hardening_modulus_pa*accumulated;
    const double tensor_shear_to_yield=current_yield/(2.*std::sqrt(3.)*shear);
    const auto elastic_reload=integrateJ2StrainIncrement(
        material,unloaded.state,SymmetricTensor3{.xy=.99*tensor_shear_to_yield});
    require(!elastic_reload.yielded,"reload below the hardened yield surface stays elastic");
    const auto plastic_reload=integrateJ2StrainIncrement(
        material,elastic_reload.state,SymmetricTensor3{.xy=.02*tensor_shear_to_yield});
    require(plastic_reload.yielded&&plastic_reload.yield_stress_after_pa>current_yield,
        "reload beyond the current surface resumes plastic flow and hardening");
}

void hydrostaticLoadingDoesNotYield(){
    const auto material=referenceJ2();constexpr double strain=.001;
    const SymmetricTensor3 hydrostatic{strain,strain,strain,0.,0.,0.};
    const auto update=integrateJ2StrainIncrement(material,{},hydrostatic);
    require(!update.yielded&&update.state.equivalent_plastic_strain==0.,
        "J2 yield is independent of hydrostatic stress");
    const double expected=material.young_modulus_pa*strain/(1.-2.*material.poisson_ratio);
    near(update.stress_pa.xx,expected,1e-6,"hydrostatic xx stress");
    near(update.stress_pa.yy,expected,1e-6,"hydrostatic yy stress");
    near(update.stress_pa.zz,expected,1e-6,"hydrostatic zz stress");
    near(vonMisesEquivalentStressPa(update.stress_pa),0.,1e-6,"hydrostatic equivalent stress");
}

void hardeningEnergyAndDissipationAreExplicit(){
    const auto material=referenceJ2();
    const auto update=integrateJ2StrainIncrement(material,{},SymmetricTensor3{.xy=.003});
    const double alpha=update.equivalent_plastic_strain_increment;
    const double expected_dissipation=material.initial_yield_stress_pa*alpha;
    const double expected_hardening=.5*material.isotropic_hardening_modulus_pa*alpha*alpha;
    near(update.plastic_dissipation_increment_j_m3,expected_dissipation,1e-7,
        "physical plastic dissipation is initial yield stress times equivalent increment");
    near(update.hardening_free_energy_increment_j_m3,expected_hardening,1e-7,
        "linear isotropic hardening free energy");
    near(update.constitutive_plastic_work_j_m3,expected_dissipation+expected_hardening,1e-7,
        "constitutive plastic-work integral partitions into hardening and dissipation");
    require(update.plastic_dissipation_increment_j_m3>=0.&&
        update.backward_euler_work_excess_j_m3>=0.,
        "physical dissipation and end-stress quadrature excess are separately nonnegative");
    const auto energy=j2EnergyDensity(material,update.state);
    near(energy.isotropic_hardening_free_energy_j_m3,expected_hardening,1e-7,
        "state exposes retained hardening free energy");
    near(energy.plastic_dissipation_j_m3,expected_dissipation,1e-7,
        "state exposes cumulative irreversible dissipation");
    near(update.backward_euler_stress_work_j_m3,
        update.stored_free_energy_increment_j_m3+
            update.plastic_dissipation_increment_j_m3+
            update.backward_euler_work_excess_j_m3,
        1e-6,"backward-Euler work quadrature reports its algorithmic excess");
}

void prestrainedTinyElasticIncrementUsesStableEnergyDifference(){
    const auto material=referenceJ2();
    const auto loaded=integrateJ2StrainIncrement(
        material,{},SymmetricTensor3{.xy=.003});
    require(loaded.yielded,"tiny-increment regression requires a prestrained plastic state");
    const double neighbor=std::nextafter(
        loaded.state.total_strain.xy,0.0);
    const SymmetricTensor3 increment{
        .xy=neighbor-loaded.state.total_strain.xy};
    const auto tiny=integrateJ2StrainIncrement(
        material,loaded.state,increment);
    require(!tiny.yielded,"one-ulp unloading query must stay on the elastic branch");
    require(tiny.state.plastic_strain==loaded.state.plastic_strain&&
        tiny.state.equivalent_plastic_strain==loaded.state.equivalent_plastic_strain&&
        tiny.state.plastic_dissipation_j_m3==loaded.state.plastic_dissipation_j_m3,
        "one-ulp elastic query cannot change plastic history");
    const SymmetricTensor3 accepted{
        .xx=tiny.state.total_strain.xx-loaded.state.total_strain.xx,
        .yy=tiny.state.total_strain.yy-loaded.state.total_strain.yy,
        .zz=tiny.state.total_strain.zz-loaded.state.total_strain.zz,
        .xy=tiny.state.total_strain.xy-loaded.state.total_strain.xy,
        .yz=tiny.state.total_strain.yz-loaded.state.total_strain.yz,
        .zx=tiny.state.total_strain.zx-loaded.state.total_strain.zx};
    const SymmetricTensor3 stress_sum{
        .xx=loaded.stress_pa.xx+tiny.stress_pa.xx,
        .yy=loaded.stress_pa.yy+tiny.stress_pa.yy,
        .zz=loaded.stress_pa.zz+tiny.stress_pa.zz,
        .xy=loaded.stress_pa.xy+tiny.stress_pa.xy,
        .yz=loaded.stress_pa.yz+tiny.stress_pa.yz,
        .zx=loaded.stress_pa.zx+tiny.stress_pa.zx};
    const double expected_stored_increment=.5*doubleContract(stress_sum,accepted);
    near(tiny.stored_free_energy_increment_j_m3,expected_stored_increment,
        std::max(1e-24,std::abs(expected_stored_increment)*1e-12),
        "prestrained one-ulp elastic free-energy increment uses exact secant form");
    near(tiny.backward_euler_stress_work_j_m3,
        tiny.stored_free_energy_increment_j_m3+
            tiny.plastic_dissipation_increment_j_m3+
            tiny.backward_euler_work_excess_j_m3,
        1e-20,"tiny accepted increment retains backward-Euler accounting");
    require(tiny.backward_euler_work_excess_j_m3>=0.,
        "tiny prestrained query cannot create negative algorithmic dissipation");

    const auto restored=integrateJ2StrainIncrement(
        material,tiny.state,SymmetricTensor3{
            .xy=loaded.state.total_strain.xy-tiny.state.total_strain.xy});
    require(!restored.yielded&&restored.state.total_strain==loaded.state.total_strain,
        "reverse one-ulp query restores the represented total strain");
}

void zeroIncrementPreservesCompactPersistentStateExactly(){
    const auto material=referenceJ2();
    const auto loaded=integrateJ2StrainIncrement(material,{},SymmetricTensor3{.xy=.003});
    const J2State persisted=loaded.state;
    const auto zero=integrateJ2StrainIncrement(material,persisted,{});
    require(zero.state==persisted&&!zero.yielded&&zero.plastic_strain_increment==SymmetricTensor3{},
        "zero increment preserves every persistent scalar exactly");
    require(sizeof(J2State)==kJ2StateScalarCount*sizeof(double)&&kJ2StateScalarCount==14,
        "persistent J2 state is exactly fourteen ordered IEEE-754 scalars");
    near(frobeniusNorm(SymmetricTensor3{
        .xx=zero.stress_pa.xx-loaded.stress_pa.xx,.yy=zero.stress_pa.yy-loaded.stress_pa.yy,
        .zz=zero.stress_pa.zz-loaded.stress_pa.zz,.xy=zero.stress_pa.xy-loaded.stress_pa.xy,
        .yz=zero.stress_pa.yz-loaded.stress_pa.yz,.zx=zero.stress_pa.zx-loaded.stress_pa.zx}),0.,0.,
        "stress reconstructs exactly from compact persistent strain history");
}

J2State followCurvedPath(unsigned steps){
    const auto material=referenceJ2();J2State state;SymmetricTensor3 previous;
    for(unsigned i=1;i<=steps;++i){const double t=double(i)/double(steps);
        const SymmetricTensor3 target{.xx=.006*t,.yy=-.003*t,.zz=-.003*t,.xy=.003*t*t,.yz=.0015*std::sin(1.2*t)};
        const SymmetricTensor3 increment{target.xx-previous.xx,target.yy-previous.yy,target.zz-previous.zz,
            target.xy-previous.xy,target.yz-previous.yz,target.zx-previous.zx};
        state=integrateJ2StrainIncrement(material,state,increment).state;previous=target;
    }
    return state;
}
double stateError(const J2State &state,const J2State &reference){
    const SymmetricTensor3 plastic_error{
        state.plastic_strain.xx-reference.plastic_strain.xx,state.plastic_strain.yy-reference.plastic_strain.yy,
        state.plastic_strain.zz-reference.plastic_strain.zz,state.plastic_strain.xy-reference.plastic_strain.xy,
        state.plastic_strain.yz-reference.plastic_strain.yz,state.plastic_strain.zx-reference.plastic_strain.zx};
    return frobeniusNorm(plastic_error)+
        std::abs(state.equivalent_plastic_strain-reference.equivalent_plastic_strain);
}
void curvedLoadingConvergesUnderStepSubdivision(){
    const auto reference=followCurvedPath(4096),coarse=followCurvedPath(8),medium=followCurvedPath(32),fine=followCurvedPath(128);
    const double coarse_error=stateError(coarse,reference),medium_error=stateError(medium,reference),fine_error=stateError(fine,reference);
    require(medium_error<coarse_error&&fine_error<medium_error,
        "nonproportional radial-return history must converge under path subdivision");
    require(fine_error<2e-5,"subdivided curved path approaches the material-point reference");
}

void invalidInputsRejectTransactionally(){
    const auto material=referenceJ2();
    const auto loaded=integrateJ2StrainIncrement(material,{},SymmetricTensor3{.xy=.003}).state;
    const J2State before=loaded;
    bool rejected=false;
    try{(void)integrateJ2StrainIncrement(material,loaded,SymmetricTensor3{.xx=std::numeric_limits<double>::quiet_NaN()});}
    catch(const std::invalid_argument &){rejected=true;}
    require(rejected&&loaded==before,"nonfinite increment rejects without mutating authoritative state");
    rejected=false;
    try{(void)integrateJ2StrainIncrement(material,loaded,SymmetricTensor3{.xx=.1});}
    catch(const std::invalid_argument &){rejected=true;}
    require(rejected&&loaded==before,"out-of-validity strain rejects transactionally");
    auto corrupt=loaded;corrupt.plastic_strain.xx+=1e-3;
    rejected=false;try{validateJ2State(material,corrupt);}catch(const std::invalid_argument &){rejected=true;}
    require(rejected,"reload validation rejects nondeviatoric plastic strain");
    corrupt=loaded;corrupt.plastic_dissipation_j_m3=0.;
    rejected=false;try{validateJ2State(material,corrupt);}catch(const std::invalid_argument &){rejected=true;}
    require(rejected,"reload validation rejects healed dissipation history");
}

void lawFamilyRejectsGlassAndWoodControls(){
    J2Material glass{
        .family=ContinuumConstitutiveFamily::BrittleDamage,.young_modulus_pa=70.e9,.poisson_ratio=.22,
        .initial_yield_stress_pa=45.e6,.isotropic_hardening_modulus_pa=0.,.maximum_total_strain_norm=.01};
    J2Material oak{
        .family=ContinuumConstitutiveFamily::Orthotropic,.young_modulus_pa=12.e9,.poisson_ratio=.35,
        .initial_yield_stress_pa=45.e6,.isotropic_hardening_modulus_pa=0.,.maximum_total_strain_norm=.01};
    J2Material iron{
        .family=ContinuumConstitutiveFamily::SmallStrainIsotropicJ2,.young_modulus_pa=211.e9,.poisson_ratio=.29,
        .initial_yield_stress_pa=200.e6,.isotropic_hardening_modulus_pa=2.e9,.maximum_total_strain_norm=.02};
    for(const auto *unsupported:{&glass,&oak}){
        bool rejected=false;try{(void)integrateJ2StrainIncrement(*unsupported,{},SymmetricTensor3{.xy=.002});}
        catch(const std::invalid_argument &){rejected=true;}
        require(rejected,"brittle and orthotropic declarations cannot be mislabeled as J2 plasticity");
    }
    const auto update=integrateJ2StrainIncrement(iron,{},SymmetricTensor3{.xy=.002});
    require(update.yielded&&update.state.plastic_strain.xy!=0.,
        "explicit isotropic-J2 iron candidate provides persistent state for later continuum calibration");
    require(update.state.total_strain.xy==.002&&reconstructJ2StressPa(iron,update.state)==update.stress_pa,
        "iron candidate can persist total/plastic strain and reconstruct tensor stress after reload");
}
}

int main(){
    const std::vector<std::pair<std::string_view,std::function<void()>>> tests{
        {"analytical pure-shear radial return",tensorConventionAndAnalyticalPureShearReturn},
        {"permanent strain under unloading",unloadingLeavesPermanentPlasticStrainAndReloadsElastically},
        {"hydrostatic elastic control",hydrostaticLoadingDoesNotYield},
        {"hardening energy and plastic dissipation",hardeningEnergyAndDissipationAreExplicit},
        {"stable prestrained tiny-increment energy",prestrainedTinyElasticIncrementUsesStableEnergyDifference},
        {"zero increment compact state",zeroIncrementPreservesCompactPersistentStateExactly},
        {"step subdivision convergence",curvedLoadingConvergesUnderStepSubdivision},
        {"transactional input and reload rejection",invalidInputsRejectTransactionally},
        {"glass oak iron law-family controls",lawFamilyRejectsGlassAndWoodControls},
    };
    unsigned failures=0;for(const auto &[name,test]:tests){try{test();std::cout<<"[PASS] "<<name<<'\n';}
        catch(const std::exception &error){++failures;std::cerr<<"[FAIL] "<<name<<": "<<error.what()<<'\n';}}
    std::cout<<tests.size()-failures<<'/'<<tests.size()<<" tests passed\n";return failures==0?EXIT_SUCCESS:EXIT_FAILURE;
}
