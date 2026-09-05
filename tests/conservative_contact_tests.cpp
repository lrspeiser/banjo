#include "physics/RollingKinematics.hpp"
#include "physics/SphereMaterialContact.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include <cmath>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;
void require(bool ok, std::string_view message) {
    if (!ok) throw std::runtime_error(std::string(message));
}
ActiveMatter point(Vec3 velocity) {
    ActiveMatter matter;
    matter.nodes.push_back({{0.999, 0.0, 0.0}, {0.999, 0.0, 0.0}, velocity, 1.0});
    return matter;
}
CoupledSphereState sphere() { return {{}, 1.0, 2.0, 0.8}; }
Vec3 momentum(const ActiveMatter &m, const CoupledSphereState &s) {
    Vec3 result = s.mass_kg * s.motion.linear_velocity_m_s;
    for (const auto &n : m.nodes) result += n.mass_kg * n.velocity_m_s;
    return result;
}
Vec3 angularMomentum(const ActiveMatter &m, const CoupledSphereState &s) {
    Vec3 result = cross(s.motion.center_of_mass_world_m,
        s.mass_kg * s.motion.linear_velocity_m_s) + s.inertia_kg_m2 * s.motion.angular_velocity_rad_s;
    for (const auto &n : m.nodes) result += cross(n.position_world_m, n.mass_kg * n.velocity_m_s);
    return result;
}
double energy(const ActiveMatter &m, const CoupledSphereState &s) {
    double result = 0.5 * s.mass_kg * lengthSquared(s.motion.linear_velocity_m_s) +
        0.5 * s.inertia_kg_m2 * lengthSquared(s.motion.angular_velocity_rad_s);
    for (const auto &n : m.nodes) result += 0.5 * n.mass_kg * lengthSquared(n.velocity_m_s);
    return result;
}
void elasticContactConserves() {
    auto m = point({-3, 0, 0}); auto s = sphere();
    const auto p = momentum(m, s); const auto l = angularMomentum(m, s); const double k = energy(m, s);
    const auto stats = solveSphereMaterialContacts(m, s, 0.001, {.restitution = 1.0});
    require(stats.impulse_contacts == 1, "closing point should collide");
    require(length(momentum(m,s)-p)<1e-12, "linear momentum must be conserved");
    require(length(angularMomentum(m,s)-l)<1e-12, "angular momentum must be conserved");
    require(std::abs(energy(m,s)-k)<1e-12, "elastic contact must conserve kinetic energy");
    require(std::abs(m.nodes[0].velocity_m_s.x-1.0)<1e-12, "analytical point velocity");
    require(std::abs(s.motion.linear_velocity_m_s.x+2.0)<1e-12, "analytical rigid reaction");
}
void frictionConservesMomentumAndDissipates() {
    auto m=point({-3,2,0.7}); auto s=sphere();
    const auto p=momentum(m,s); const auto l=angularMomentum(m,s); const double k=energy(m,s);
    const auto stats=solveSphereMaterialContacts(m,s,0.001,
        {.static_friction=0.8,.dynamic_friction=0.5,.restitution=0.2});
    require(length(momentum(m,s)-p)<1e-12, "friction must have equal opposite reaction");
    require(length(angularMomentum(m,s)-l)<1e-12, "shared contact point must preserve angular momentum");
    require(length(s.motion.angular_velocity_rad_s)>0.1, "tangential contact should spin the sphere");
    require(energy(m,s)<=k+1e-12, "passive contact must not add kinetic energy");
    require(std::abs(stats.dissipated_kinetic_energy_j-(k-energy(m,s)))<1e-12,
        "contact dissipation ledger must match the energy difference");
}
void separatingContactNeverAttracts() {
    auto m=point({1,0,0}); auto s=sphere();
    const auto stats=solveSphereMaterialContacts(m,s,0.001,{});
    require(stats.impulse_contacts==0, "separating point must not be pulled back");
    require(length(s.motion.linear_velocity_m_s)==0, "no spurious rigid reaction");
}
void speculativeContactStopsCrossing() {
    auto m=point({-100,0,0});m.nodes[0].position_world_m.x=1.1;auto s=sphere();
    (void)solveSphereMaterialContacts(m,s,0.01,{});
    const double gap_after=0.1+0.01*(m.nodes[0].velocity_m_s.x-s.motion.linear_velocity_m_s.x);
    require(gap_after>=-1e-12, "speculative normal impulse must prevent crossing at high speed");
}
void contactIsGalileanInvariant() {
    auto a=point({-3,2,0});auto b=a;auto sa=sphere();auto sb=sa;
    const Vec3 boost{4,-1,2};b.nodes[0].velocity_m_s+=boost;sb.motion.linear_velocity_m_s+=boost;
    const SphereMaterialContactSettings settings{.static_friction=.8,.dynamic_friction=.5,.restitution=.3};
    (void)solveSphereMaterialContacts(a,sa,.001,settings);
    (void)solveSphereMaterialContacts(b,sb,.001,settings);
    require(length(b.nodes[0].velocity_m_s-a.nodes[0].velocity_m_s-boost)<1e-12,
        "contact must not depend on observer translation");
    require(length(sb.motion.angular_velocity_rad_s-sa.motion.angular_velocity_rad_s)<1e-12,
        "boost must not alter rigid spin reaction");
}
void rollingReadoutUsesContactVelocity() {
    const auto plane=makeSupportPlaneFromSlopeDegrees(20);
    RigidSnapshot body{pointInPlaneFrame(plane,0,0,.25),{},8*plane.tangent_world,
        cross(plane.normal_world,8*plane.tangent_world)/.25};
    auto m=measureRollingKinematics(body,.25,plane);
    require(m.state==RollingState::Rolling && m.contact_slip_speed_m_s<1e-12,
        "v=r*omega should have zero tangential contact speed even on a slope");
    body.angular_velocity_rad_s={};m=measureRollingKinematics(body,.25,plane);
    require(m.state==RollingState::Slipping && std::abs(m.contact_slip_speed_m_s-8)<1e-12,
        "translation without spin is sliding");
    body.center_of_mass_world_m+=plane.normal_world;
    require(measureRollingKinematics(body,.25,plane).state==RollingState::Airborne,
        "airborne spinning is not supported rolling");
    body.center_of_mass_world_m-=plane.normal_world;
    require(measureRollingKinematics(body,.25,plane,false).state==RollingState::Airborne,
        "an infinite-plane approximation must not report support beyond the platform edge");
}
void dampingDoesNotDragBulkMotion() {
    auto material=makeReferenceMaterial(MaterialPreset::Glass,42);
    auto compiled=compileBrittleMaterial(material,.08,2);
    compiled.bond_damping=10;
    const auto asset=generateSphereLattice({.25,.08,2,2},compiled);
    BrittleBondSolver solver({.substeps=1,.constraint_iterations=8,.floor_height_m=-100});
    ImpactEvent impact;impact.body_a=1;impact.body_b=2;impact.normal_a_to_b={1,0,0};
    const Vec3 v{2,3,-1};
    auto active=solver.activate(2,asset,compiled,{{0,1,0},{},v,{}},impact);
    const double mass=asset.total_mass_kg;
    for(unsigned i=0;i<10;++i) (void)solver.step(active,.001,{});
    Vec3 p{};for(const auto &n:active.nodes)p+=n.mass_kg*n.velocity_m_s;
    require(length(p-mass*v)<1e-7,"internal damping must preserve bulk momentum in vacuum");
}
}
int main() {
    const std::vector<std::pair<std::string_view,std::function<void()>>> tests{
        {"elastic analytical contact",elasticContactConserves},
        {"friction momentum and energy",frictionConservesMomentumAndDissipates},
        {"no attractive contact",separatingContactNeverAttracts},
        {"speculative collision",speculativeContactStopsCrossing},
        {"Galilean contact invariance",contactIsGalileanInvariant},
        {"rolling vs slipping diagnostics",rollingReadoutUsesContactVelocity},
        {"internal damping preserves translation",dampingDoesNotDragBulkMotion},
    };
    unsigned failures=0;
    for(const auto &[name,test]:tests)try{test();std::cout<<"[PASS] "<<name<<'\n';}
        catch(const std::exception &e){++failures;std::cerr<<"[FAIL] "<<name<<": "<<e.what()<<'\n';}
    std::cout<<tests.size()-failures<<'/'<<tests.size()<<" tests passed\n";
    return failures?1:0;
}
