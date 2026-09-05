#include "physics/ResolutionBudget.hpp"
#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace banjo;
void check(bool value,const char *message){if(!value)throw std::runtime_error(message);}
int main(){try{
    const std::array<double,2> masses{2,2};
    const std::array<ResolutionLink,1> links{{{0,1,100}}};
    auto plan=assessSpringResolution(masses,links,.05,2);
    check(std::abs(plan.maximum_frequency_bound_rad_s-10)<1e-12,"two-mass eigenfrequency bound is exact");
    check(plan.required_substeps==3&&!plan.temporally_resolved&&!plan.fits_substep_budget,"unresolved work cannot be admitted as accurate");
    const auto refined=assessSpringResolution(masses,links,.05/plan.required_substeps,2);
    check(refined.temporally_resolved,"planned subdivision meets declared phase budget");
    const std::array<double,3> chainMass{1,1,1};
    const std::array<ResolutionLink,2> chain{{{0,1,100},{1,2,100}}};
    const auto bound=assessSpringResolution(chainMass,chain,.01);
    check(bound.maximum_frequency_bound_rad_s>=std::sqrt(300.)&&bound.maximum_frequency_bound_rad_s==20,"bound covers analytical three-mass highest mode");
    auto empty=assessSpringResolution(masses,{},.1);
    check(empty.temporally_resolved&&empty.required_substeps==1,"rigid/no-spring case needs no fictitious microsteps");
    bool rejected=false;try{(void)assessSpringResolution(masses,links,0);}catch(const std::invalid_argument&){rejected=true;}
    check(rejected,"invalid timestep rejected");
    std::cout<<"[PASS] spectral resolution bound and explicit substep admission\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
