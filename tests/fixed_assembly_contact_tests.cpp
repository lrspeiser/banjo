#include "physics/FixedAssemblyContact.hpp"
#include "core/RigidPrimitive.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

namespace {
using namespace banjo;
constexpr double dt=1./240;
void require(bool value,const char *why) {if(!value)throw std::runtime_error(why);}
void near(double value,double expected,double bound,const char *why) {
    if(!std::isfinite(value)||std::abs(value-expected)>bound)
        throw std::runtime_error(std::string(why)+": "+std::to_string(value)+" vs "+std::to_string(expected));
}
void nearVec(Vec3 value,Vec3 expected,double bound,const char *why) {near(length(value-expected),0,bound,why);}
RigidMechanicalState box(Vec3 dimensions,double density,Vec3 center,Vec3 velocity={2,0,0}) {
    RigidPrimitive shape;shape.kind=PrimitiveKind::Box;shape.dimensions_m=dimensions;
    RigidMechanicalState out;out.mass_kg=shape.volume()*density;out.inertia_world_kg_m2=shape.inertia(out.mass_kg);
    out.motion.center_of_mass_world_m=center;out.motion.linear_velocity_m_s=velocity;return out;
}
ActiveNodeState node(Vec3 position={.055,.01,0},Vec3 velocity={}) {
    ActiveNodeState out;out.mass_kg=700*.04*.04*.04;out.position_world_m=position;
    out.previous_position_world_m=position;out.velocity_m_s=velocity;return out;
}
void audit(const FixedAssemblyContactResult &out,const std::vector<RigidMechanicalState> &before,
    const std::vector<FixedVelocityLink> &links) {
    require(out.modal_contact.applied,"expected constrained contact");
    nearVec(out.momentum_residual_kg_m_s,{},1e-12,"assembly momentum audit");
    nearVec(out.angular_residual_kg_m2_s,{},1e-12,"assembly angular audit");
    near(out.work_residual_j,0,1e-12,"assembly work audit");
    for(std::size_t i=0;i<before.size();++i) {
        require(out.bodies[i].mass_kg==before[i].mass_kg&&out.bodies[i].inertia_world_kg_m2.m==before[i].inertia_world_kg_m2.m,
            "constrained contact changed a physical mass/tensor");
        nearVec(out.bodies[i].motion.center_of_mass_world_m,before[i].motion.center_of_mass_world_m,0,"contact moved geometry");
    }
    for(std::size_t i=0;i<links.size();++i) {
        const auto &link=links[i];const auto &a=out.bodies[link.a].motion,&b=out.bodies[link.b].motion;
        nearVec(a.angular_velocity_rad_s,b.angular_velocity_rad_s,1e-12,"fixed angular velocity");
        nearVec(a.linear_velocity_m_s+cross(a.angular_velocity_rad_s,link.point_a_world_m-a.center_of_mass_world_m),
            b.linear_velocity_m_s+cross(b.angular_velocity_rad_s,link.point_b_world_m-b.center_of_mass_world_m),1e-12,
            "fixed attachment-point velocity");
        near(out.contact_reactions[i].work_j,0,1e-12,"compatible constraint contact work");
    }
}
void singleBodyAndAssemblyOracle() {
    const auto head=box({.08,.08,.08},2500,{});
    const auto p=node();
    const auto single=evaluatePointFixedAssemblyContact(p,{head},{},0,{1,0,0},-.001,dt,{0,0,1});
    const auto old=evaluatePointRigidContact(p,head,{1,0,0},-.001,dt,{0,0,1});
    audit(single,{head},{});
    nearVec(single.modal_contact.impulse_to_node_n_s,old.impulse_to_node_n_s,1e-12,"one-member contact reduction");
    const auto handle=box({.24,.04,.04},700,{-.16,0,0});
    const std::vector<RigidMechanicalState> bodies{head,handle};
    const std::vector<FixedVelocityLink> links{{0,1,{-.04,0,0},{-.04,0,0}}};
    const auto result=evaluatePointFixedAssemblyContact(p,bodies,links,0,{1,0,0},-.001,dt,{0,0,1});
    audit(result,bodies,links);
    const double mass=head.mass_kg+handle.mass_kg;
    const double center_x=-.16*handle.mass_kg/mass;
    const double iz=head.inertia_world_kg_m2.m[2][2]+handle.inertia_world_kg_m2.m[2][2]+
        head.mass_kg*center_x*center_x+handle.mass_kg*std::pow(-.16-center_x,2);
    // Independent frictionless normal compliance oracle, including full assembly inertia.
    const double impulse=4/(1/p.mass_kg+1/mass+.01*.01/iz);
    near(result.modal_contact.normal_impulse_n_s,impulse,1e-12,"constrained normal impulse oracle");
    near(result.bodies[1].motion.angular_velocity_rad_s.z,.01*impulse/iz,1e-12,"handle immediate angular response");
    require(length(result.contact_reactions[0].impulse_on_b_n_s)>0,"fixing bypassed the handle reaction");
    near(result.reconciliation_loss_j,0,1e-12,"compatible source reconciliation loss");
}
void retainedMaterialComparisons() {
    const auto oak=makeReferenceMaterial(MaterialPreset::Oak,17);
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto material=makeReferenceMaterial(preset,17);
        const std::vector<RigidMechanicalState> bodies{box({.08,.08,.08},material.density_kg_m3,{}),box({.24,.04,.04},700,{-.16,0,0})};
        const std::vector<FixedVelocityLink> links{{1,0,{-.04,0,0},{-.04,0,0}}};
        const auto law=combineContactMaterials(compileContactMaterial(material),compileContactMaterial(oak));
        const auto result=evaluatePointFixedAssemblyContact(node(),bodies,links,0,{1,0,0},-.001,dt,
            {law.static_friction,law.dynamic_friction,law.restitution});
        audit(result,bodies,links);
        std::cout<<materialPresetName(preset)<<": head="<<bodies[0].mass_kg<<" kg; handle="<<bodies[1].mass_kg
            <<" kg; Jn="<<result.modal_contact.normal_impulse_n_s<<" N s; loss="<<result.modal_contact.dissipated_energy_j
            <<" J; joint impulse="<<length(result.contact_reactions[0].impulse_on_b_n_s)
            <<" N s; p="<<length(result.momentum_residual_kg_m_s)<<"; L="<<length(result.angular_residual_kg_m2_s)
            <<"; work="<<result.work_residual_j<<" J\n";
    }
}
void relativeMotionAndAnchorDrift() {
    std::vector<RigidMechanicalState> bodies{box({1,1,1},1,{}, {2,0,0}),box({1,1,1},1,{-1,0,0},{})};
    std::vector<FixedVelocityLink> links{{0,1,{-.5,0,0},{-.5,0,0}}};
    auto p=node({.5,0,0});p.mass_kg=1;
    const auto result=evaluatePointFixedAssemblyContact(p,bodies,links,0,{1,0,0},0,dt);
    audit(result,bodies,links);
    near(result.reconciliation_loss_j,1,1e-12,"known axial velocity reconciliation loss");
    near(result.reconciliation[0].work_j,-1,1e-12,"reconciliation impulse work");
    links[0].point_b_world_m.y=.05;
    const auto drift=evaluatePointFixedAssemblyContact(p,bodies,links,0,{1,0,0},0,dt);
    audit(drift,bodies,links);
    require(length(drift.geometry_couple_kg_m2_s)>1e-5,"separated anchors' actual couple was hidden");
}
void branchedFramesAndLinkDirection() {
    std::vector<RigidMechanicalState> bodies{box({.08,.08,.08},2500,{}),box({.24,.04,.04},700,{-.16,0,0}),
        box({.04,.12,.04},7870,{-.16,.08,0})};
    std::vector<FixedVelocityLink> links{{0,1,{-.04,0,0},{-.04,0,0}},{0,2,{-.16,.02,0},{-.16,.02,0}}};
    const auto p=node();const PointRigidContactSettings law{.3,.2,0};
    const auto reference=evaluatePointFixedAssemblyContact(p,bodies,links,0,{1,0,0},0,dt,law);
    audit(reference,bodies,links);
    // Permuted member and link order with both constraint directions reversed.
    std::vector<RigidMechanicalState> permuted{bodies[2],bodies[0],bodies[1]};
    std::vector<FixedVelocityLink> reversed{{0,1,links[1].point_b_world_m,links[1].point_a_world_m},
        {2,1,links[0].point_b_world_m,links[0].point_a_world_m}};
    const auto reordered=evaluatePointFixedAssemblyContact(p,permuted,reversed,1,{1,0,0},0,dt,law);
    audit(reordered,permuted,reversed);
    nearVec(reordered.modal_contact.impulse_to_node_n_s,reference.modal_contact.impulse_to_node_n_s,1e-12,"tree order invariance");
    for(unsigned i=0;i<3;++i)nearVec(reordered.bodies[i].motion.linear_velocity_m_s,reference.bodies[i==0?2:i-1].motion.linear_velocity_m_s,
        1e-12,"permuted physical member response");
    const Quat turn{std::sqrt(.5),0,std::sqrt(.5),0};const Vec3 shift{7,-3,2},boost{.3,-.2,.1};
    for(auto &body:bodies) {
        body.motion.center_of_mass_world_m=turn.rotate(body.motion.center_of_mass_world_m)+shift;
        body.motion.linear_velocity_m_s=turn.rotate(body.motion.linear_velocity_m_s)+boost;
        body.inertia_world_kg_m2=rotateInertia(body.inertia_world_kg_m2,turn);
    }
    for(auto &link:links) {link.point_a_world_m=turn.rotate(link.point_a_world_m)+shift;link.point_b_world_m=turn.rotate(link.point_b_world_m)+shift;}
    auto moved=p;moved.position_world_m=turn.rotate(p.position_world_m)+shift;moved.velocity_m_s=boost;
    const auto transformed=evaluatePointFixedAssemblyContact(moved,bodies,links,0,turn.rotate({1,0,0}),0,dt,law);
    audit(transformed,bodies,links);
    nearVec(transformed.modal_contact.impulse_to_node_n_s,turn.rotate(reference.modal_contact.impulse_to_node_n_s),1e-12,"frame covariance");
    near(transformed.modal_contact.dissipated_energy_j,reference.modal_contact.dissipated_energy_j,1e-12,"boost invariant loss");
}
void refusalAndNoContact() {
    auto bodies=std::vector<RigidMechanicalState>{box({1,1,1},1,{}),box({1,1,1},1,{-1,0,0},{})};
    const std::vector<FixedVelocityLink> links{{0,1,{-.5,0,0},{-.5,0,0}}};
    const auto empty=evaluatePointFixedAssemblyContact(node(),bodies,links,0,{1,0,0},1,dt);
    require(!empty.modal_contact.applied,"out-of-range contact applied");
    nearVec(empty.bodies[0].motion.linear_velocity_m_s,bodies[0].motion.linear_velocity_m_s,0,"no contact projected source velocity");
    auto refuses=[&](const auto &states,const auto &graph,unsigned striker) {
        bool refused=false;try{(void)evaluatePointFixedAssemblyContact(node(),states,graph,striker,{1,0,0},0,dt);}
        catch(const std::invalid_argument &){refused=true;}require(refused,"invalid assembly admitted");
    };
    refuses(bodies,std::vector<FixedVelocityLink>{},0);refuses(bodies,links,2);
    refuses(bodies,std::vector<FixedVelocityLink>{{0,0,{},{}}},0);
    bodies.push_back(bodies[0]);refuses(bodies,std::vector<FixedVelocityLink>{{0,1,{},{}},{1,0,{},{}}},0);
    bodies.resize(2);bodies[0].mass_kg=0;refuses(bodies,links,0);
    bodies[0].mass_kg=1;bodies[0].inertia_world_kg_m2.m[0][0]=-1;refuses(bodies,links,0);
    nearVec(bodies[0].motion.linear_velocity_m_s,{2,0,0},0,"refusal mutated caller state");
}
void boundedTreeCapacity() {
    std::vector<RigidMechanicalState> bodies;
    std::vector<FixedVelocityLink> links;
    for(unsigned i=0;i<256;++i) {
        bodies.push_back(box({1,1,1},1,{-static_cast<double>(i),0,0}));
        if(i>0) {const Vec3 anchor{.5-static_cast<double>(i),0,0};links.push_back({i-1,i,anchor,anchor});}
    }
    auto p=node({.5,0,0});p.mass_kg=1;
    const auto result=evaluatePointFixedAssemblyContact(p,bodies,links,0,{1,0,0},0,dt,{0,0,1});
    audit(result,bodies,links);
    near(result.modal_contact.normal_impulse_n_s,4/(1+1./256),1e-12,"256 member axial assembly oracle");
    bodies.push_back(box({1,1,1},1,{-256,0,0}));links.push_back({255,256,{-255.5,0,0},{-255.5,0,0}});
    bool refused=false;try{(void)evaluatePointFixedAssemblyContact(p,bodies,links,0,{1,0,0},0,dt);}
    catch(const std::invalid_argument &){refused=true;}require(refused,"assembly capacity overflow admitted");
}
} // namespace
int main() {
    try {std::cout.precision(12);singleBodyAndAssemblyOracle();retainedMaterialComparisons();relativeMotionAndAnchorDrift();
        branchedFramesAndLinkDirection();refusalAndNoContact();boundedTreeCapacity();
        std::cout<<"[PASS] constrained assembly contact oracles and audits\n";return 0;}
    catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}
}
