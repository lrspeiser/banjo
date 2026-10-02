#include "physics/PointRigidContact.hpp"
#include "physics/SphereMaterialContact.hpp"
#include "core/RigidPrimitive.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"

#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <numbers>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace {
using namespace banjo;
constexpr double cell=.04,step=1./240;
void require(bool value,const char *why) { if (!value) throw std::runtime_error(why); }
void near(double value,double expected,double bound,const char *why) {
    std::ostringstream message;message.precision(15);
    message<<why<<": "<<value<<" versus "<<expected<<" (bound "<<bound<<")";
    if (!std::isfinite(value)||std::abs(value-expected)>bound) throw std::runtime_error(message.str());
}
void nearVec(Vec3 value,Vec3 expected,double bound,const char *why) { near(length(value-expected),0,bound,why); }
RigidMechanicalState source() {
    const auto iron=makeReferenceMaterial(MaterialPreset::Iron,17);
    RigidPrimitive shape;shape.kind=PrimitiveKind::Box;shape.dimensions_m={.4,.08,.06};
    RigidMechanicalState out;out.mass_kg=shape.volume()*iron.density_kg_m3;
    out.motion.center_of_mass_world_m={1,.5,-.5};
    const double half=std::numbers::pi/12;
    out.motion.orientation_world={std::cos(half),0,std::sin(half),0};
    out.inertia_world_kg_m2=rotateInertia(shape.inertia(out.mass_kg),out.motion.orientation_world);
    out.motion.linear_velocity_m_s={-1,.2,.4};out.motion.angular_velocity_rad_s={1,-2,.3};return out;
}
ActiveNodeState point(const RigidMechanicalState &body,double mass,Vec3 relative) {
    const Vec3 arm{.12,.03,.02};
    ActiveNodeState node;node.position_world_m=body.motion.center_of_mass_world_m+arm;
    node.previous_position_world_m=node.position_world_m;node.mass_kg=mass;
    node.velocity_m_s=body.motion.linear_velocity_m_s+cross(body.motion.angular_velocity_rad_s,arm)+relative;
    node.spin_angular_velocity_rad_s={3,-1,2};return node;
}
void audit(const PointRigidContactResult &out,double bound=1e-12) {
    require(out.applied,"expected a finite-body contact impulse");
    nearVec(out.momentum_residual_kg_m_s,{},bound,"contact linear momentum");
    nearVec(out.angular_residual_kg_m2_s,{},bound,"contact angular momentum about world origin");
    near(out.work_residual_j,0,bound,"impulse-work and measured kinetic change");
    near(out.relative_normal_after_m_s,out.target_normal_speed_m_s,bound,"normal contact target");
    require(out.dissipated_energy_j>=0&&out.kinetic_change_j<=bound,"passive contact added kinetic energy");
}
void normalImpactMatchesTheElasticOracle() {
    RigidMechanicalState body;body.mass_kg=2;
    for (unsigned i=0;i<3;++i) body.inertia_world_kg_m2.m[i][i]=.8;
    ActiveNodeState node;node.position_world_m={1,0,0};node.mass_kg=1;node.velocity_m_s={-3,0,0};
    const auto out=evaluatePointRigidContact(node,body,{1,0,0},0,.001,{.restitution=1});
    audit(out);nearVec(out.node_velocity_m_s,{1,0,0},1e-12,"elastic point velocity");
    nearVec(out.rigid.motion.linear_velocity_m_s,{-2,0,0},1e-12,"finite source recoil");
    near(out.normal_impulse_n_s,4,1e-12,"analytical normal impulse");
    near(out.dissipated_energy_j,0,1e-12,"elastic energy loss");
}
void sphereLimitRetainsTheExistingResponse() {
    ActiveMatter matter;ActiveNodeState node;node.position_world_m={1,0,0};node.mass_kg=1;
    node.velocity_m_s={-3,2,.7};matter.nodes.push_back(node);
    CoupledSphereState sphere;sphere.radius_m=1;sphere.mass_kg=2;sphere.inertia_kg_m2=.8;
    const SphereMaterialContactSettings old_settings{.8,.5,.2};
    const auto old=solveSphereMaterialContacts(matter,sphere,.001,old_settings);
    RigidMechanicalState body;body.mass_kg=2;
    for (unsigned i=0;i<3;++i) body.inertia_world_kg_m2.m[i][i]=.8;
    const auto out=evaluatePointRigidContact(node,body,{1,0,0},0,.001,{.8,.5,.2});
    audit(out);nearVec(out.node_velocity_m_s,matter.nodes.front().velocity_m_s,1e-12,"sphere-limit node response");
    nearVec(out.rigid.motion.linear_velocity_m_s,sphere.motion.linear_velocity_m_s,1e-12,"sphere-limit source response");
    nearVec(out.rigid.motion.angular_velocity_rad_s,sphere.motion.angular_velocity_rad_s,1e-12,"sphere-limit spin reaction");
    near(out.dissipated_energy_j,old.dissipated_kinetic_energy_j,1e-12,"sphere-limit dissipation");
}
void materialMassAndContactPropertiesDriveTheResult() {
    const auto body=source();const auto iron=makeReferenceMaterial(MaterialPreset::Iron,17);
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto material=makeReferenceMaterial(preset,17);
        const auto contact=combineContactMaterials(compileContactMaterial(material),compileContactMaterial(iron));
        const auto node=point(body,material.density_kg_m3*cell*cell*cell,{3,.5,-2});
        const auto out=evaluatePointRigidContact(node,body,{0,0,1},0,step,
            {contact.static_friction,contact.dynamic_friction,contact.restitution});
        audit(out);
        require(out.rigid.mass_kg==body.mass_kg&&out.rigid.inertia_world_kg_m2.m==body.inertia_world_kg_m2.m,
                "contact replaced source matter-derived mass or tensor");
        require(out.rigid.motion.center_of_mass_world_m.x==body.motion.center_of_mass_world_m.x&&
                node.spin_angular_velocity_rad_s.x==3,"contact assigned a pose or target spin");
        std::cout<<"  "<<materialPresetName(preset)<<": h="<<cell<<" dt="<<step<<" point mass="<<node.mass_kg
                 <<" kg; source mass="<<body.mass_kg<<" kg; mu="<<contact.static_friction<<"/"<<contact.dynamic_friction
                 <<" e="<<contact.restitution<<"; Jn="<<out.normal_impulse_n_s<<" N s; Jt="<<out.tangent_impulse_n_s
                 <<" N s; loss="<<out.dissipated_energy_j<<" J; p residual="<<length(out.momentum_residual_kg_m_s)
                 <<" N s; L residual="<<length(out.angular_residual_kg_m2_s)<<" kg m2/s; work residual="
                 <<out.work_residual_j<<" J; iterations="<<out.friction_iterations<<"\n";
    }
}
void anisotropicFrictionUsesTheFinalSlipDirection() {
    const auto body=source();const Vec3 normal=normalized(Vec3{.2,1,-.3});
    const Vec3 tangent=Vec3{5,-2,7}-dot(Vec3{5,-2,7},normal)*normal;
    const auto node=point(body,.16,-3*normal+tangent);
    const auto out=evaluatePointRigidContact(node,body,normal,0,step,{.3,.2,0});
    audit(out);require(!out.sticking&&out.slip_after_m_s>0,"expected anisotropic sliding");
    near(out.tangent_impulse_n_s,.2*out.normal_impulse_n_s,1e-12,"dynamic Coulomb cone");
    const Vec3 arm=node.position_world_m-body.motion.center_of_mass_world_m;
    const Vec3 relative=out.node_velocity_m_s-out.rigid.motion.linear_velocity_m_s-
        cross(out.rigid.motion.angular_velocity_rad_s,arm);
    const Vec3 slip=relative-dot(relative,normal)*normal;
    const Vec3 jt=out.impulse_to_node_n_s-out.normal_impulse_n_s*normal;
    nearVec(jt,-out.tangent_impulse_n_s*normalized(slip),1e-11,"impulse opposes final anisotropic slip");
    const auto static_node=point(body,.16,-3*normal+.03*tangent);
    const auto stuck=evaluatePointRigidContact(static_node,body,normal,0,step,{1.5,1,0});
    audit(stuck);require(stuck.sticking,"expected a feasible static impulse");
    near(stuck.slip_after_m_s,0,1e-12,"static slip constraint");
}
void aFiniteRodRetainsItsAxialInertia() {
    const auto oak=makeReferenceMaterial(MaterialPreset::Oak,17);
    RigidPrimitive rod;rod.kind=PrimitiveKind::Box;rod.dimensions_m={.6,.04,.04};
    RigidMechanicalState body;body.mass_kg=rod.volume()*oak.density_kg_m3;
    body.inertia_world_kg_m2=rod.inertia(body.mass_kg);body.motion.angular_velocity_rad_s={2,0,0};
    ActiveNodeState node;node.position_world_m={0,.02,.02};node.mass_kg=.1;node.velocity_m_s={.5,-1,-2};
    const auto out=evaluatePointRigidContact(node,body,{0,0,1},0,step,{.5,.4,0});
    audit(out);require(std::abs(out.rigid.motion.angular_velocity_rad_s.x-2)>1,
                       "finite rod did not retain its axial angular reaction");
    std::cout<<"  finite rod: mass="<<body.mass_kg<<" kg; axial I="<<body.inertia_world_kg_m2.m[0][0]
             <<" kg m2; spin="<<out.rigid.motion.angular_velocity_rad_s.x<<" rad/s\n";
}
void noAttractionOrOverlapEnergyIsInvented() {
    RigidMechanicalState body;body.mass_kg=2;for(unsigned i=0;i<3;++i)body.inertia_world_kg_m2.m[i][i]=.8;
    ActiveNodeState node;node.position_world_m={1,0,0};node.mass_kg=1;node.velocity_m_s={-1,0,0};
    require(!evaluatePointRigidContact(node,body,{1,0,0},.01,.001).applied,"distant point was pulled into contact");
    const auto speculative=evaluatePointRigidContact(node,body,{1,0,0},.0004,.001);
    audit(speculative);near(speculative.relative_normal_after_m_s,-.4,1e-12,"speculative closing allowance");
    node.velocity_m_s={1,2,0};
    require(!evaluatePointRigidContact(node,body,{1,0,0},-.1,.001,{1,.5,.2}).applied,
            "separating overlap invented a correction impulse");
    node.velocity_m_s={-1,0,0};
    const auto overlap=evaluatePointRigidContact(node,body,{1,0,0},-.1,.001);
    const auto touching=evaluatePointRigidContact(node,body,{1,0,0},0,.001);
    nearVec(overlap.impulse_to_node_n_s,touching.impulse_to_node_n_s,1e-12,"overlap did not become kinetic energy");
}
void framesPreserveThePhysicalImpulse() {
    const auto body=source();const Vec3 normal=normalized(Vec3{.2,1,-.3});
    const auto node=point(body,.16,{3,-5,4});const PointRigidContactSettings law{.3,.2,0};
    const auto original=evaluatePointRigidContact(node,body,normal,0,step,law);
    const Vec3 boost{13,-7,4},shift{1e5,-2e5,3e5};
    auto shifted_body=body;auto shifted_node=node;
    shifted_body.motion.center_of_mass_world_m+=shift;shifted_node.position_world_m+=shift;
    shifted_body.motion.linear_velocity_m_s+=boost;shifted_node.velocity_m_s+=boost;
    const auto moved=evaluatePointRigidContact(shifted_node,shifted_body,normal,0,step,law);
    nearVec(moved.impulse_to_node_n_s,original.impulse_to_node_n_s,1e-10,"Galilean/world-origin invariance");
    near(moved.dissipated_energy_j,original.dissipated_energy_j,1e-10,"boost-invariant dissipation");
    const Quat turn{std::sqrt(.5),0,std::sqrt(.5),0};
    auto rotated_body=body;auto rotated_node=node;
    rotated_body.motion.center_of_mass_world_m=turn.rotate(body.motion.center_of_mass_world_m);
    rotated_body.motion.linear_velocity_m_s=turn.rotate(body.motion.linear_velocity_m_s);
    rotated_body.motion.angular_velocity_rad_s=turn.rotate(body.motion.angular_velocity_rad_s);
    rotated_body.inertia_world_kg_m2=rotateInertia(body.inertia_world_kg_m2,turn);
    rotated_node.position_world_m=turn.rotate(node.position_world_m);rotated_node.velocity_m_s=turn.rotate(node.velocity_m_s);
    const auto rotated=evaluatePointRigidContact(rotated_node,rotated_body,turn.rotate(normal),0,step,law);
    nearVec(rotated.impulse_to_node_n_s,turn.rotate(original.impulse_to_node_n_s),1e-11,"rotation covariance");
    near(rotated.dissipated_energy_j,original.dissipated_energy_j,1e-11,"rotation-invariant loss");
}
void unsupportedRestitutionRefusesWithoutMutation() {
    RigidMechanicalState body;body.mass_kg=1;for (unsigned i=0;i<3;++i)body.inertia_world_kg_m2.m[i][i]=.1;
    ActiveNodeState node;node.position_world_m={1,1,0};node.mass_kg=1;node.velocity_m_s={-1,5./6,0};
    bool refused=false;try { (void)evaluatePointRigidContact(node,body,{1,0,0},0,step,{1,1,1}); }
    catch(const std::domain_error &) { refused=true; }
    require(refused,"coupled restitution/static friction injected kinetic energy");
    require(node.velocity_m_s.x==-1&&body.motion.linear_velocity_m_s.x==0,
            "rejected restitution candidate changed caller state");
}
void malformedInputsRefuse() {
    const auto body=source();const auto node=point(body,.16,{3,.5,-2});
    std::vector<RigidMechanicalState> bad;
    auto candidate=body;candidate.mass_kg=0;bad.push_back(candidate);
    candidate=body;candidate.inertia_world_kg_m2.m[0][0]=-1;bad.push_back(candidate);
    candidate=body;candidate.inertia_world_kg_m2.m[0][1]+=.1;bad.push_back(candidate);
    candidate=body;candidate.motion.angular_velocity_rad_s.x=std::numeric_limits<double>::infinity();bad.push_back(candidate);
    for (const auto &invalid:bad) {
        bool refused=false;try { (void)evaluatePointRigidContact(node,invalid,{0,0,1},0,step); }
        catch(const std::invalid_argument &) { refused=true; }require(refused,"invalid source tensor/motion admitted");
    }
    for (const auto law:std::vector<PointRigidContactSettings>{{.1,.2,0},{-.1,0,0},{.5,.4,2},{.5,.4,.2,-1}}) {
        bool refused=false;try { (void)evaluatePointRigidContact(node,body,{0,0,1},0,step,law); }
        catch(const std::invalid_argument &) { refused=true; }require(refused,"invalid contact law admitted");
    }
    bool refused=false;try { (void)evaluatePointRigidContact(node,body,{0,0,2},0,step); }
    catch(const std::invalid_argument &) { refused=true; }require(refused,"nonunit normal admitted");
    refused=false;try { (void)evaluatePointRigidContact(node,body,{0,0,1},0,0); }
    catch(const std::invalid_argument &) { refused=true; }require(refused,"zero timestep admitted");
}
} // namespace
int main() {
    const std::vector<std::pair<const char *,std::function<void()>>> checks{
        {"elastic finite-body response matches the oracle",normalImpactMatchesTheElasticOracle},
        {"isotropic sphere retains the existing response",sphereLimitRetainsTheExistingResponse},
        {"retained materials drive measured mass/contact response",materialMassAndContactPropertiesDriveTheResult},
        {"anisotropic static/sliding impulses obey their contact law",anisotropicFrictionUsesTheFinalSlipDirection},
        {"finite rod retains axial inertia and spin reaction",aFiniteRodRetainsItsAxialInertia},
        {"separation and overlap invent no impulse energy",noAttractionOrOverlapEnergyIsInvented},
        {"coordinate changes preserve impulse and dissipation",framesPreserveThePhysicalImpulse},
        {"unsupported restitution refuses transactionally",unsupportedRestitutionRefusesWithoutMutation},
        {"invalid state and laws refuse",malformedInputsRefuse}};
    int failures=0;std::cout.precision(12);
    for (const auto &[name,check]:checks) { std::cout<<name<<"\n";
        try { check();std::cout<<"  ok\n"; } catch(const std::exception &e) { ++failures;std::cout<<"  FAILED: "<<e.what()<<"\n"; }
    }
    return failures?1:0;
}
