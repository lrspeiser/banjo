#include "physics/TetrahedronContactImpulse.hpp"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string_view>

using namespace banjo;
namespace {

void check(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}
void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message));
}
void near(Vec3 actual, Vec3 expected, double tolerance, std::string_view message) {
    near(length(actual - expected), 0., tolerance, message);
}
template<class F> void rejects(F&&f,std::string_view message){try{f();}catch(const std::invalid_argument&){return;}throw std::runtime_error(std::string(message));}

TetrahedronContactSide side(Vec3 offset, Vec3 velocity, double mass,
                            std::array<double,4> weights={1.,0.,0.,0.}) {
    TetrahedronContactSide result;
    result.positions_m={offset,offset+Vec3{1.,0.,0.},offset+Vec3{0.,1.,0.},offset+Vec3{0.,0.,1.}};
    result.velocities_m_s.fill(velocity);result.lumped_masses_kg.fill(mass);result.barycentric=weights;return result;
}

void equal_and_distributed_masses() {
    auto a=side({}, {1.,0.,0.},2.);auto b=side({}, {-1.,0.,0.},2.);
    auto result=evaluateTetrahedronContactImpulse(a,b,{1.,0.,0.});
    check(result.applied,"closing equal masses apply impulse");near(result.normal_impulse_n_s,2.,1.e-14,"equal impulse");
    near(result.velocities_a_m_s[0],{},1.e-14,"A stopped");near(result.velocities_b_m_s[0],{},1.e-14,"B stopped");
    near(result.kinetic_dissipation_j,2.,1.e-14,"exact equal-mass kinetic loss");near(result.work_residual_j,0.,1.e-14,"work closure");

    a=side({}, {1.,0.,0.},1.,{.25,.25,.25,.25});b=side({}, {-1.,0.,0.},1.,{.25,.25,.25,.25});
    result=evaluateTetrahedronContactImpulse(a,b,{1.,0.,0.});
    near(result.inverse_effective_mass_kg_inv,.5,1.e-14,"distributed inverse mass");near(result.normal_impulse_n_s,4.,1.e-14,"distributed impulse");
    for(unsigned i=0;i<4;++i){near(result.velocities_a_m_s[i],{},1.e-14,"distributed A stopped");near(result.velocities_b_m_s[i],{},1.e-14,"distributed B stopped");}
    near(result.kinetic_dissipation_j,4.,1.e-14,"distributed exact kinetic loss");
}

void unequal_and_supported_exchange() {
    auto a=side({}, {1.,0.,0.},2.);auto b=side({}, {-2.,0.,0.},4.);
    auto result=evaluateTetrahedronContactImpulse(a,b,{1.,0.,0.});
    near(result.normal_impulse_n_s,4.,1.e-14,"unequal mass impulse");near(result.velocities_a_m_s[0],{-1.,0.,0.},1.e-14,"unequal A velocity");near(result.velocities_b_m_s[0],{-1.,0.,0.},1.e-14,"unequal B velocity");
    near(result.kinetic_dissipation_j,6.,1.e-14,"unequal kinetic loss");near(result.raw_linear_momentum_change_kg_m_s,{},1.e-14,"free momentum closure");

    a=side({}, {},2.);a.fixed_components[0][0]=true;b=side({}, {-1.,0.,0.},4.);
    result=evaluateTetrahedronContactImpulse(a,b,{1.,0.,0.});
    near(result.normal_impulse_n_s,4.,1.e-14,"supported impulse");near(result.support_impulse_n_s,{4.,0.,0.},1.e-14,"support impulse reported");
    near(result.linear_momentum_residual_kg_m_s,{},1.e-14,"support-adjusted momentum closure");near(result.angular_momentum_residual_kg_m2_s,{},1.e-14,"support-adjusted moment closure");near(result.kinetic_dissipation_j,2.,1.e-14,"supported kinetic loss");
}

void inactive_contacts_are_unchanged() {
    auto a=side({}, {},1.);auto b=side({}, {1.,0.,0.},1.);
    auto result=evaluateTetrahedronContactImpulse(a,b,{1.,0.,0.});check(!result.applied,"separating contact inactive");
    for(unsigned i=0;i<4;++i){near(result.velocities_a_m_s[i],a.velocities_m_s[i],0.,"inactive A unchanged");near(result.velocities_b_m_s[i],b.velocities_m_s[i],0.,"inactive B unchanged");}
    b.velocities_m_s.fill({});result=evaluateTetrahedronContactImpulse(a,b,{1.,0.,0.});check(!result.applied&&result.normal_impulse_n_s==0.,"static contact inactive");
}

Vec3 rotateTranslate(Vec3 p){return {-p.y+3.,p.x-2.,p.z+.4};}
Vec3 rotate(Vec3 p){return {-p.y,p.x,p.z};}
void rigid_covariance_and_witness_depth() {
    auto a=side({}, {1.,0.,0.},2.,{.25,.25,.25,.25});auto b=side({.1,0.,0.},{-1.,0.,0.},3.,{.25,.25,.25,.25});
    const auto first=evaluateTetrahedronContactImpulse(a,b,{1.,0.,0.});
    for(auto&p:a.positions_m)p=rotateTranslate(p);for(auto&p:b.positions_m)p=rotateTranslate(p);
    for(auto&v:a.velocities_m_s)v=rotate(v);for(auto&v:b.velocities_m_s)v=rotate(v);
    const auto transformed=evaluateTetrahedronContactImpulse(a,b,{0.,1.,0.});
    near(transformed.normal_impulse_n_s,first.normal_impulse_n_s,1.e-13,"rigid impulse invariance");near(transformed.kinetic_dissipation_j,first.kinetic_dissipation_j,1.e-13,"rigid energy invariance");
    near(transformed.raw_angular_momentum_change_kg_m2_s-transformed.support_current_moment_n_m_s,{},1.e-13,"translated current-moment closure");
}

void invalid_inputs_reject_without_mutation() {
    auto a=side({}, {1.,0.,0.},1.);auto b=side({}, {-1.,0.,0.},1.);const auto original=a.velocities_m_s;
    a.barycentric={.5,.5,.5,0.};rejects([&]{(void)evaluateTetrahedronContactImpulse(a,b,{1.,0.,0.});},"invalid weights rejected");for(unsigned i=0;i<4;++i)near(a.velocities_m_s[i],original[i],0.,"invalid call leaves input unchanged");
    a=side({}, {1.,0.,0.},1.);b.positions_m[0].y=.1;rejects([&]{(void)evaluateTetrahedronContactImpulse(a,b,{1.,0.,0.});},"nonparallel witnesses rejected");
}

} // namespace
int main(){try{equal_and_distributed_masses();unequal_and_supported_exchange();inactive_contacts_are_unchanged();rigid_covariance_and_witness_depth();invalid_inputs_reject_without_mutation();std::cout<<"5 tetrahedron contact impulse tests passed\n";return EXIT_SUCCESS;}catch(const std::exception&e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return EXIT_FAILURE;}}
