#include "physics/CompliantStep.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace {
using namespace banjo;
void require(bool condition, const char *message) { if (!condition) throw std::runtime_error(message); }
void near(double a, double b, double tolerance, const char *message) {
    if (!std::isfinite(a) || std::abs(a-b)>tolerance) throw std::runtime_error(message);
}
struct Point {
    LatticeAsset asset;
    ActiveMatter matter;
    Point(Vec3 p, Vec3 v, double mass=2) {
        asset.recipe.voxel_size_m=.02; matter.asset=&asset;
        matter.nodes.push_back({p,{},v,mass,{}});
    }
};
MechanicalTotals totals(const ActiveMatter &matter, const CoupledSphereState *sphere=nullptr, Vec3 gravity={}) {
    auto result=measureMaterialMechanics(matter,gravity);
    if (sphere) {
        Mat3 inertia; for (unsigned i=0;i<3;++i) inertia.m[i][i]=sphere->inertia_kg_m2;
        result+=measureRigidMechanics({sphere->motion,sphere->mass_kg,inertia},gravity);
    }
    return result;
}
void contactWorkAndTangents() {
    for (const auto gaps:std::vector<std::pair<double,double>>{{.1,.05},{.001,-.002},{-.002,.001},
            {-.002,-.003},{-.003,-.002},{-.003,-.003},{0,-.002},{-.002,0}}) {
        const auto [g0,g1]=gaps;
        const auto e=evaluateNormalCompliance(g0,g1-g0,.01,{2500,7});
        near(e.energy_after_j-e.energy_before_j+e.impulse_kg_m_s*(g1-g0)/.01+e.damping_loss_j,
            0,1e-12,"contact discrete work identity");
        require(e.impulse_kg_m_s>=0 && e.damping_loss_j>=0,"no attractive contact or negative damping loss");
    }
    for (const bool radial:{false,true}) {
        detail::ElasticNormalContact contact{0,radial ? 1 : detail::fixed_contact_body,
            {.49,.03,.04},normalized(Vec3{1,2,3}),-.01,radial ? .5 : 0,{2500,7}};
        if (radial) contact.gap0_m=length(contact.relative0)-contact.sphere_radius_m;
        const std::vector<Vec3> initial{{-.3,.1,.2},{.1,-.2,.1}};
        std::vector<Vec3> velocity{{-.2,.2,.3},{.05,-.1,.2}};
        const auto e=detail::evaluateElasticContact(contact,initial,velocity,.01);
        require(e.valid,"valid contact tangent fixture");
        for (unsigned axis=0;axis<3;++axis) {
            Vec3 direction; if (axis==0) direction.x=1; if (axis==1) direction.y=1; if (axis==2) direction.z=1;
            auto plus=velocity, minus=velocity;
            plus[0]+=1e-5*direction; minus[0]-=1e-5*direction;
            const auto p=detail::evaluateElasticContact(contact,initial,plus,.01);
            const auto m=detail::evaluateElasticContact(contact,initial,minus,.01);
            near(length(e.velocity_tangent*direction+(p.impulse_on_a-m.impulse_on_a)/2e-5),
                0,1e-8,"analytic contact Jacobian matches finite difference");
        }
    }
}
void analyticalBounceAndRefinement() {
    const auto plane=makeSupportPlane({}, {0,1,0});
    const double mass=2, stiffness=2000, omega=std::sqrt(stiffness/mass), duration=.25;
    for (const double zeta:{0.0,.25,.8,1.0,2.0}) {
        const double peak = zeta<1 ? std::acos(zeta)/(omega*std::sqrt(1-zeta*zeta)) :
            (zeta==1 ? 1/omega : std::acosh(zeta)/(omega*std::sqrt(zeta*zeta-1)));
        const double rebound=std::exp(-zeta*omega*peak), release=peak+std::numbers::pi/(2*omega);
        double coarse_error=0;
        for (const double dt:{.001,.00025}) {
            Point point({}, {.3,-1,.2},mass);
            const CompliantStepSettings settings{.solver={.support=&plane},
                .normal={stiffness,2*zeta*std::sqrt(stiffness*mass)},.maximum_compression_m=.1};
            double loss=0, contact_energy=0, impulse=0;
            const unsigned steps=static_cast<unsigned>(std::lround(duration/dt));
            for (unsigned i=0;i<steps;++i) {
                const auto result=tryCompliantStep(point.matter,dt,settings);
                require(result.balance.converged,"analytical contact bounce converges");
                loss+=result.contact_damping_loss_j; contact_energy=result.contact_energy_after_j;
                impulse+=result.balance.support_impulse_kg_m_s.y;
            }
            const auto &node=point.matter.nodes[0];
            const double error=std::abs(node.velocity_m_s.y-rebound)+omega*std::abs(node.position_world_m.y-rebound*(duration-release));
            std::cout<<"bounce zeta="<<zeta<<" dt="<<dt<<" error="<<error<<" rebound="<<node.velocity_m_s.y<<'\n';
            if (dt==.001) coarse_error=error;
            else {
                require(error<.5*coarse_error,"analytical contact trajectory improves with refinement");
                near(node.velocity_m_s.y,rebound,2e-4,"analytical compression-only rebound");
                near(node.position_world_m.y,rebound*(duration-release),1e-4,"analytical release and flight");
            }
            near(.5*mass*node.velocity_m_s.y*node.velocity_m_s.y+contact_energy+loss,1,1e-8,"independent normal work ledger");
            near(impulse,mass*(1+node.velocity_m_s.y),1e-8,"finite plane reaction");
            near(node.velocity_m_s.x,.3,1e-12,"no tangential drag");
        }
    }
}
void loadedSustainedContact() {
    const auto plane=makeSupportPlane({}, {0,1,0});
    const Vec3 gravity{0,-9.81,0};
    const double omega=std::sqrt(1000.0), equilibrium=.00981, dt=.001, duration=.5;
    const CompliantStepSettings settings{.solver={.support=&plane},
        .normal={2000,2*std::sqrt(4000.0)},.maximum_compression_m=.05};
    Point point({}, {.3,0,.2});
    const auto before=totals(point.matter,nullptr,gravity);
    double loss=0, energy=0; Vec3 impulse;
    for (unsigned i=0;i<500;++i) {
        const auto result=tryCompliantStep(point.matter,dt,settings,gravity);
        require(result.balance.converged,"loaded contact stays solvable");
        loss+=result.contact_damping_loss_j; energy=result.contact_energy_after_j;
        impulse+=result.balance.support_impulse_kg_m_s;
    }
    const double expected_y=-equilibrium*(1-(1+omega*duration)*std::exp(-omega*duration));
    near(point.matter.nodes[0].position_world_m.y,expected_y,1e-7,"critical damped settling follows load law");
    near(point.matter.nodes[0].velocity_m_s.y,0,2e-6,"settling without a velocity snap");
    const auto after=totals(point.matter,nullptr,gravity);
    near(after.mechanicalEnergy()+energy+loss,before.mechanicalEnergy(),1e-8,"gravity/contact storage/loss ledger");
    near(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s-duration*before.mass_kg*gravity-impulse),
        0,1e-8,"sustained external reaction");
    Point rest({0,-equilibrium,0},{.3,0,.2});
    const auto result=tryCompliantStep(rest.matter,.1,settings,gravity);
    require(result.balance.converged,"exact loaded equilibrium converges");
    near(rest.matter.nodes[0].position_world_m.y,-equilibrium,1e-12,"stored compression supports weight");
    near(result.balance.support_impulse_kg_m_s.y,1.962,1e-10,"equilibrium support impulse");
    std::cout<<"settling y="<<point.matter.nodes[0].position_world_m.y<<" vy="<<point.matter.nodes[0].velocity_m_s.y
             <<" damping_loss_j="<<loss<<" stored_j="<<energy<<'\n';
}
void finitePairAnalyticalRebound() {
    Point point({-.5,0,0},{2,0,0},1);
    CoupledSphereState sphere{{},.5,2,.2};
    const double reduced_mass=2.0/3, k=2000, zeta=.25, omega=std::sqrt(k/reduced_mass), duration=.1;
    const double peak=std::acos(zeta)/(omega*std::sqrt(1-zeta*zeta));
    const double rebound=std::exp(-zeta*omega*peak), release=peak+std::numbers::pi/(2*omega);
    const CompliantStepSettings settings{.normal={k,2*zeta*std::sqrt(k*reduced_mass)},.maximum_compression_m=.1};
    double loss=0;
    for (unsigned i=0;i<500;++i) {
        const auto result=tryCompliantStep(point.matter,.0002,settings,{},&sphere);
        if (!result.balance.converged) std::cerr << "pair failure step=" << i << " reason=" << compliantFailureName(result.failure)
            << " residual=" << result.balance.constitutive_velocity_residual_m_s << " E=" << result.balance.energy_residual_j
            << " P=" << length(result.balance.linear_momentum_residual_kg_m_s) << " compression=" << result.maximum_compression_m
            << " damping=" << result.contact_damping_loss_j << '\n';
        require(result.balance.converged,"finite pair analytical bounce converges");
        loss+=result.contact_damping_loss_j;
    }
    near(point.matter.nodes[0].velocity_m_s.x,2*(1-2*rebound)/3,2e-4,"reduced-mass point rebound");
    near(sphere.motion.linear_velocity_m_s.x,2*(1+rebound)/3,2e-4,"reduced-mass finite reaction");
    const double distance=.5+2*rebound*(duration-release), center=-1.0/6+2.0/3*duration;
    near(point.matter.nodes[0].position_world_m.x,center-2.0/3*distance,1e-4,"finite pair contact duration and flight");
    near(sphere.motion.center_of_mass_world_m.x,center+distance/3,1e-4,"finite sphere contact duration and flight");
    near(loss,.5*reduced_mass*4*(1-rebound*rebound),2e-4,"reduced-mass analytical contact loss");
}
void finiteSphereFramesAndLedger() {
    const Vec3 n=normalized(Vec3{-.8,.6,.1}), axis=normalized(Vec3{1,2,3}), offset{1,-2,.5}, boost{.3,-.4,.2};
    const Quat rotation{std::cos(.31),axis.x*std::sin(.31),axis.y*std::sin(.31),axis.z*std::sin(.31)};
    Point point(.5*n,{1.2,-.3,.2},1), moved(rotation.rotate(.5*n)+offset,rotation.rotate({1.2,-.3,.2})+boost,1);
    CoupledSphereState sphere{{},.5,2,.2};
    sphere.motion.linear_velocity_m_s={-.2,.1,0}; sphere.motion.angular_velocity_rad_s={.5,-.3,.1};
    auto other=sphere; other.motion.center_of_mass_world_m=offset;
    other.motion.linear_velocity_m_s=rotation.rotate(sphere.motion.linear_velocity_m_s)+boost;
    other.motion.angular_velocity_rad_s=rotation.rotate(sphere.motion.angular_velocity_rad_s); other.motion.orientation_world=rotation;
    const auto before=totals(point.matter,&sphere);
    const CompliantStepSettings settings{.normal={2000,4},.maximum_compression_m=.1};
    double loss=0, energy=0;
    for (unsigned i=0;i<200;++i) {
        const auto a=tryCompliantStep(point.matter,.0001,settings,{},&sphere);
        const auto b=tryCompliantStep(moved.matter,.0001,settings,{},&other);
        require(a.balance.converged && b.balance.converged,"finite sphere/frame contact converges");
        loss+=a.contact_damping_loss_j; energy=a.contact_energy_after_j;
    }
    const auto after=totals(point.matter,&sphere);
    near(after.mechanicalEnergy()+energy+loss,before.mechanicalEnergy(),1e-8,"finite sphere contact work");
    near(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s),0,1e-8,"finite pair momentum");
    near(length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s),0,1e-8,"off-center central impulse angular balance");
    near(length(moved.matter.nodes[0].position_world_m-offset-.02*boost-rotation.rotate(point.matter.nodes[0].position_world_m)),
        0,1e-8,"rotated boosted node trajectory");
    near(length(other.motion.center_of_mass_world_m-offset-.02*boost-rotation.rotate(sphere.motion.center_of_mass_world_m)),
        0,1e-8,"rotated boosted finite reaction trajectory");
}
void rejectionKeepsState() {
    Point point({-2,0,0},{40,0,0},1);
    CoupledSphereState sphere{{},.5,2,.2};
    const CompliantStepSettings settings{.normal={2000,4},.maximum_compression_m=.01};
    const auto result=tryCompliantStep(point.matter,.1,settings,{},&sphere);
    require(!result.balance.converged && result.failure==CompliantStepFailure::Compression,"deep swept crossing rejects");
    near(point.matter.nodes[0].position_world_m.x,-2,0,"rejected point retains position");
    near(point.matter.nodes[0].velocity_m_s.x,40,0,"rejected point retains velocity");
    near(length(sphere.motion.center_of_mass_world_m),0,0,"rejected sphere retains position");
    const auto plane=makeSupportPlane({}, {0,1,0});
    Point edge({.09,.01,0},{1,0,0});
    const auto e=tryCompliantStep(edge.matter,.1,{.solver={.support=&plane,.support_half_tangent_m=.1},
        .normal={2000,4},.maximum_compression_m=.01});
    require(!e.balance.converged && e.failure==CompliantStepFailure::Geometry,"finite footprint crossing rejects");
    near(edge.matter.nodes[0].position_world_m.x,.09,0,"edge rejection retains state");
    bool invalid=false;
    try { (void)tryCompliantStep(edge.matter,.1,{}); } catch(const std::invalid_argument &) { invalid=true; }
    require(invalid,"physical interface parameters must be explicit and valid");
}
void comparativeFullMaterialContact() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto compiled=compileElasticLatticeReference(makeReferenceMaterial(preset,17),.04,2);
        const auto asset=generateSphereLattice({.25,.04,2,3},compiled);
        for (const double damping:{0.0,1e4}) {
            ActiveMatter matter; matter.asset=&asset; matter.material=compiled; matter.bonds.resize(asset.bonds.size());
            double minimum_y=0;
            for (const auto &node:asset.nodes) {
                matter.nodes.push_back({node.local_position_m,{}, {.3,-1,.2},node.represented_volume_m3*compiled.density_kg_m3,{}});
                minimum_y=std::min(minimum_y,node.local_position_m.y);
            }
            const auto plane=makeSupportPlane({0,minimum_y-.001,0},{0,1,0});
            const CompliantStepSettings settings{.solver={.support=&plane},.normal={1e8,damping},.maximum_compression_m=.005};
            const auto before=totals(matter);
            double loss=0, energy=0, compression=0; Vec3 impulse, angular;
            for (unsigned i=0;i<40;++i) {
                const auto result=tryCompliantStep(matter,.00005,settings);
                if (!result.balance.converged) std::cout<<"material="<<materialPresetName(preset)<<" damping="<<damping
                    <<" step="<<i<<" failure="<<static_cast<int>(result.failure)<<" residual="<<result.balance.constitutive_velocity_residual_m_s<<'\n';
                require(result.balance.converged,"all retained materials finish compliant contact");
                loss+=result.contact_damping_loss_j; energy=result.contact_energy_after_j;
                compression=std::max(compression,result.maximum_compression_m);
                impulse+=result.balance.support_impulse_kg_m_s; angular+=result.balance.support_angular_impulse_kg_m2_s;
            }
            const auto after=totals(matter);
            near(after.mechanicalEnergy()+energy+loss,before.mechanicalEnergy(),1e-8*before.mechanicalEnergy(),"comparative stored/lost energy ledger");
            near(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s-impulse),0,1e-8*length(impulse),"comparative finite support reaction");
            near(length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s-angular),0,1e-8,"comparative angular balance");
            require(compression>0,"experiment actually compresses the interface");
            if (damping>0) require(loss>0,"declared damping removes contact work"); else near(loss,0,0,"undamped interface has no loss");
            std::cout<<"material="<<materialPresetName(preset)<<" damping="<<damping<<" loss_j="<<loss
                <<" stored_j="<<energy<<" max_compression_m="<<compression<<'\n';
        }
    }
}
}
int main() {
    const std::vector<std::pair<const char *,std::function<void()>>> tests{
        {"contact work and Jacobian",contactWorkAndTangents},
        {"analytical bounce and timestep refinement",analyticalBounceAndRefinement},
        {"loaded sustained contact",loadedSustainedContact},
        {"finite pair analytical rebound",finitePairAnalyticalRebound},
        {"finite sphere frame and energy ledger",finiteSphereFramesAndLedger},
        {"compression and geometry rollback",rejectionKeepsState},
        {"glass/oak/iron full compliant contact",comparativeFullMaterialContact}};
    unsigned failures=0;
    for (const auto &[name,test]:tests) {
        try {test();std::cout<<"[PASS] "<<name<<'\n';}
        catch(const std::exception &e) {++failures;std::cerr<<"[FAIL] "<<name<<": "<<e.what()<<'\n';}
    }
    return failures ? 1 : 0;
}
