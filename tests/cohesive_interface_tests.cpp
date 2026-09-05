#include "physics/CohesiveInterface.hpp"
#include "material/MaterialCatalog.hpp"
#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace banjo;
void check(bool b,const char *s){if(!b)throw std::runtime_error(s);}
void near(double a,double b,double tolerance,const char *s){check(std::isfinite(a)&&std::abs(a-b)<=tolerance,s);}
void rejects(const std::function<void()> &f){bool rejected=false;try{f();}catch(const std::invalid_argument&){rejected=true;}check(rejected,"expected rejection");}
int main(){try{
    // Normal-opening coupon only. Stiffness is an explicit interface parameter;
    // this comparison does not assert a calibrated bulk law for wood or iron.
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto material=makeReferenceMaterial(preset);
        const double strength=material.tensile_strength_pa,gc=material.fracture_energy_j_m2,area=.0001;
        // Common nondimensional interface shape: delta0 = deltaf / 4.
        const CohesiveInterfaceLaw law{2*strength*strength/gc,strength,gc,area};
        const double onset=cohesiveDamageOpening(law),failure=cohesiveSeparationOpening(law),budget=gc*area,tolerance=std::max(1e-12,budget*1e-11);
        near(failure,4*onset,failure*1e-14,"declared strength/stiffness/Gc determine opening scales");
        for(unsigned steps:{1U,4U,17U,1000U}) {
            CohesiveInterfaceState state;double work=0,dissipation=0,max_residual=0;
            for(unsigned i=1;i<=steps;++i){auto step=advanceCohesiveInterface(law,state,1.2*failure*i/steps);work+=step.opening_work_j;dissipation+=step.dissipated_increment_j;max_residual=std::max(max_residual,std::abs(step.balance_residual_j));state=step.state;}
            auto final=evaluateCohesiveInterface(law,state);check(final.separated,"complete opening separates interface");near(work,budget,tolerance,"integrated traction work equals area times fracture energy");near(dissipation,budget,tolerance,"complete damage dissipates Gc once");near(final.stored_energy_j,0,0,"complete separation retains no recoverable tension energy");near(max_residual,0,tolerance,"independent force-work integration closes ledger");
        }
        auto peak=advanceCohesiveInterface(law,{},onset);near(peak.response.traction_pa,strength,strength*1e-14,"peak traction equals declared strength");near(peak.response.dissipated_energy_j,0,0,"elastic loading does not dissipate fracture work");
        auto damaged=advanceCohesiveInterface(law,{},.6*failure);const double irreversible=damaged.response.dissipated_energy_j;
        auto closed=advanceCohesiveInterface(law,damaged.state,-.1*failure);near(closed.response.dissipated_energy_j,irreversible,tolerance,"closing cannot refund fracture work");near(closed.opening_work_j,-damaged.response.stored_energy_j,tolerance,"unloading returns only stored energy");near(closed.response.force_n,0,0,"normal cohesive law does not implement compression contact");
        auto reloaded=advanceCohesiveInterface(law,closed.state,.6*failure);near(reloaded.dissipated_increment_j,0,0,"reloading below maximum cannot damage twice");near(reloaded.response.damage,damaged.response.damage,0,"unloading does not heal interface");near(reloaded.opening_work_j+closed.opening_work_j,0,tolerance,"unload/reload cycle has no invented work");
        auto separated=advanceCohesiveInterface(law,reloaded.state,failure);auto reclosed=advanceCohesiveInterface(law,separated.state,0);auto reopened=advanceCohesiveInterface(law,reclosed.state,failure);
        near(reopened.opening_work_j,0,0,"separated interface does not reform bonds on recontact");near(reopened.response.dissipated_energy_j,budget,tolerance,"separation cost cannot be refunded or charged twice");
        for(unsigned patches:{1U,4U,16U,100U}){auto patch_law=law;patch_law.area_m2=area/patches;const auto patch=advanceCohesiveInterface(patch_law,{},failure);near(patch.opening_work_j*patches,budget,tolerance,"same interface area partition preserves prescribed opening work");near(patch.response.dissipated_energy_j*patches,budget,tolerance,"fracture work follows physical area not number of samples");}
        std::cout<<materialPresetName(preset)<<" area_m2="<<area<<" Gc="<<gc<<" strength_pa="<<strength<<" delta0_m="<<onset<<" deltaf_m="<<failure<<" separation_work_j="<<budget<<'\n';
    }
    const CohesiveInterfaceLaw good{1000,10,1,.1};
    rejects([&]{(void)evaluateCohesiveInterface(good,{.1,.05});});
    auto bad=good;bad.fracture_energy_j_m2=.01;rejects([&]{(void)advanceCohesiveInterface(bad,{},1);});
    bad=good;bad.area_m2=-1;rejects([&]{(void)advanceCohesiveInterface(bad,{},1);});
    rejects([&]{(void)advanceCohesiveInterface(good,{},std::numeric_limits<double>::quiet_NaN());});
    std::cout<<"[PASS] cohesive traction/work/damage/cycles/area-partition/bounds\n";return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
