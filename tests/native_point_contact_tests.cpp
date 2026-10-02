#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"

#include <iostream>
#include <limits>
#include <numbers>
#include <stdexcept>

namespace {
using namespace banjo;
constexpr double cell=.04,dt=1./240;
constexpr PointContactRoundoffBudget rounding{1e-5,1e-5,1e-5};
void require(bool condition,const char *message) { if(!condition)throw std::runtime_error(message); }
void near(double value,double expected,double tolerance,const char *message) {
    if(!std::isfinite(value)||std::abs(value-expected)>tolerance)throw std::runtime_error(message);
}
void same(Vec3 a,Vec3 b,const char *message) { require(length(a-b)==0,message); }
void same(const RigidSnapshot &a,const RigidSnapshot &b) {
    same(a.center_of_mass_world_m,b.center_of_mass_world_m,"contact/refusal changed source position");
    same(a.linear_velocity_m_s,b.linear_velocity_m_s,"refusal changed source velocity");
    same(a.angular_velocity_rad_s,b.angular_velocity_rad_s,"refusal changed source spin");
    require(a.orientation_world.w==b.orientation_world.w&&a.orientation_world.x==b.orientation_world.x&&
            a.orientation_world.y==b.orientation_world.y&&a.orientation_world.z==b.orientation_world.z,
            "contact/refusal changed source orientation");
}
struct Fixture {
    JoltWorld world;
    ActiveNodeState point;
    PointRigidContactSettings law;
    explicit Fixture(MaterialPreset target=MaterialPreset::Glass,bool external=true,bool fixed_source=false) {
        world.setGravity({});
        const auto iron=makeReferenceMaterial(MaterialPreset::Iron,17);
        const double angle=std::numbers::pi/12;
        world.addBox({1,{.4,.08,.06},iron,{{1,.5,-.5},{std::cos(angle),0,std::sin(angle),0},
            fixed_source?Vec3{}:Vec3{-1,.2,.4},fixed_source?Vec3{}:Vec3{1,-2,.3}},fixed_source});
        // Admission/geometry search belongs to the caller. This proxy exists
        // only to declare pair ownership; the point is the external target DOF.
        // Deliberately overlapping, so later native motion verifies the pair
        // mask, rather than passing only because the proxy is far away.
        world.addBox({2,{.3,.12,.12},makeReferenceMaterial(target,17),{{1,.5,-.5},{},{},{}},true});
        if(external)world.setPairContactOwner(2,1,PairContactOwner::External);
        const auto source=world.mechanicalState(1);
        const Vec3 arm{.12,.03,.02};
        point.position_world_m=source.motion.center_of_mass_world_m+arm;
        point.previous_position_world_m=point.position_world_m;
        const auto material=makeReferenceMaterial(target,17);
        point.mass_kg=material.density_kg_m3*cell*cell*cell;
        point.velocity_m_s=source.motion.linear_velocity_m_s+cross(source.motion.angular_velocity_rad_s,arm)+Vec3{3,.5,-2};
        point.spin_angular_velocity_rad_s={3,-1,2};
        const auto contact=combineContactMaterials(compileContactMaterial(material),compileContactMaterial(iron));
        law={contact.static_friction,contact.dynamic_friction,contact.restitution};
    }
    PointContactKick kick(const PointContactRoundoffBudget &budget=rounding) {
        return world.applyExternalPointContact(2,1,point,{0,0,1},0,dt,law,budget);
    }
};
void materialReactionAndRounding() {
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Fixture f(preset);
        const auto before=f.world.mechanicalState(1);
        const auto proxy=f.world.snapshot(2);
        const auto old_point=f.point;
        const auto receipt=f.kick();
        require(receipt.contact.applied,"expected native point contact");
        const auto actual=f.world.mechanicalState(1);
        same(actual.motion,receipt.delivered_rigid.motion);
        same(f.point.velocity_m_s,receipt.contact.node_velocity_m_s,"point did not receive its accepted impulse");
        same(f.point.position_world_m,old_point.position_world_m,"impulse changed point position");
        same(f.point.previous_position_world_m,old_point.previous_position_world_m,"impulse changed integration history");
        same(f.point.spin_angular_velocity_rad_s,old_point.spin_angular_velocity_rad_s,"point gained unsupported torque");
        require(f.point.mass_kg==old_point.mass_kg&&actual.mass_kg==before.mass_kg&&
                actual.inertia_world_kg_m2.m==before.inertia_world_kg_m2.m,"contact replaced source/target mass or tensor");
        same(f.world.snapshot(2),proxy);
        const double point_ke=.5*old_point.mass_kg*(lengthSquared(f.point.velocity_m_s)-lengthSquared(old_point.velocity_m_s));
        const double measured_change=point_ke+measureRigidMechanics(actual).kinetic_energy_j-
            measureRigidMechanics(before).kinetic_energy_j;
        near(measured_change+receipt.contact.dissipated_energy_j,receipt.numerical_energy_change_j,1e-12,
             "measured runtime loss did not retain numerical residual");
        require(std::abs(receipt.numerical_energy_change_j)<=rounding.energy_j&&
                length(receipt.momentum_error_kg_m_s)<=rounding.linear_impulse_n_s&&
                length(receipt.angular_momentum_error_kg_m2_s)<=rounding.angular_impulse_kg_m2_s,
                "native transfer exceeded accepted roundoff budgets");
        require(std::abs(receipt.numerical_energy_change_j)>0,"fixture missed native float rounding");
        std::cout<<materialPresetName(preset)<<": h="<<cell<<" dt="<<dt<<" target mass="<<old_point.mass_kg
                 <<" source mass="<<before.mass_kg<<" loss="<<receipt.contact.dissipated_energy_j
                 <<" roundoff J="<<receipt.numerical_energy_change_j<<" dP="<<length(receipt.momentum_error_kg_m_s)
                 <<" dL="<<length(receipt.angular_momentum_error_kg_m2_s)<<" normal error="
                 <<receipt.delivered_normal_speed_m_s-receipt.contact.target_normal_speed_m_s<<'\n';
        f.world.setDamping(1,0,0);
        f.world.step(dt);
        require(length(f.world.snapshot(1).center_of_mass_world_m-
            (actual.motion.center_of_mass_world_m+actual.motion.linear_velocity_m_s*dt))<1e-7,
            "accepted reaction did not drive subsequent native motion");
        require(f.world.drainImpacts().empty(),"unexpected second pair contact response");
    }
}
template<class Action> void refusedWithoutMutation(Fixture &f,Action action) {
    const auto source=f.world.snapshot(1),proxy=f.world.snapshot(2);
    const auto old=f.point;
    bool refused=false;
    try { action(); }catch(const std::invalid_argument &) { refused=true; }
    require(refused,"unsupported native point contact admitted");
    same(source,f.world.snapshot(1));same(proxy,f.world.snapshot(2));
    same(old.velocity_m_s,f.point.velocity_m_s,"rejected point candidate was committed");
    same(old.position_world_m,f.point.position_world_m,"refusal changed external point geometry");
}
void atomicRefusal() {
    Fixture measured;const auto receipt=measured.kick();
    for(unsigned field=0;field<3;++field) {
        Fixture f;
        auto budget=rounding;
        if(field==0)budget.energy_j=.5*std::abs(receipt.numerical_energy_change_j);
        if(field==1)budget.linear_impulse_n_s=.5*length(receipt.momentum_error_kg_m_s);
        if(field==2)budget.angular_impulse_kg_m2_s=.5*length(receipt.angular_momentum_error_kg_m2_s);
        refusedWithoutMutation(f,[&]{(void)f.kick(budget);});
    }
    Fixture owned(MaterialPreset::Glass,false);
    refusedWithoutMutation(owned,[&]{(void)owned.kick();});
    Fixture pinned;pinned.world.pinToWorld(1);
    refusedWithoutMutation(pinned,[&]{(void)pinned.kick();});
    Fixture anchored(MaterialPreset::Glass,true,true);
    refusedWithoutMutation(anchored,[&]{(void)anchored.kick();});
    Fixture bad;
    refusedWithoutMutation(bad,[&]{(void)bad.kick({-1,1,1});});
    refusedWithoutMutation(bad,[&]{(void)bad.kick({1,std::numeric_limits<double>::infinity(),1});});
    refusedWithoutMutation(bad,[&]{(void)bad.world.applyExternalPointContact(2,1,bad.point,{0,0,2},0,dt,bad.law,rounding);});
    refusedWithoutMutation(bad,[&]{(void)bad.world.applyExternalPointContact(1,1,bad.point,{0,0,1},0,dt,bad.law,rounding);});
    bool trial_refused=false;
    const auto point_before_trial=bad.point;
    const auto source_before_trial=bad.world.snapshot(1);
    const bool trial_accepted=bad.world.runReversibleTrial([&] {
        try {(void)bad.kick();}catch(const std::logic_error &) {trial_refused=true;}
        return false;
    });
    require(trial_refused&&!trial_accepted,"external point write escaped the native trial recorder");
    same(point_before_trial.velocity_m_s,bad.point.velocity_m_s,"trial refusal changed point velocity");
    same(source_before_trial,bad.world.snapshot(1));
    bad.point.velocity_m_s={1e6,0,-1e6};
    refusedWithoutMutation(bad,[&]{(void)bad.kick();});
}
void repeatedContactRetainsNativeState() {
    Fixture f;
    auto second=f.point;
    second.position_world_m+=Vec3{-.12,-.03,0};
    second.previous_position_world_m=second.position_world_m;
    second.velocity_m_s={-2,1,-4};
    const auto initial=f.world.mechanicalState(1);
    const auto first_point=f.point;
    const auto second_point=second;
    const auto first=f.kick();
    const auto second_kick=f.world.applyExternalPointContact(2,1,second,{0,0,1},0,dt,f.law,rounding);
    require(first.contact.applied&&second_kick.contact.applied,"ordered material contacts did not both act");
    const auto final=f.world.mechanicalState(1);
    const auto total_p=[](const ActiveNodeState &a,const ActiveNodeState &b,const RigidMechanicalState &s) {
        return a.mass_kg*a.velocity_m_s+b.mass_kg*b.velocity_m_s+s.mass_kg*s.motion.linear_velocity_m_s;
    };
    const auto total_l=[](const ActiveNodeState &a,const ActiveNodeState &b,const RigidMechanicalState &s) {
        return cross(a.position_world_m,a.mass_kg*a.velocity_m_s)+cross(b.position_world_m,b.mass_kg*b.velocity_m_s)+
            measureRigidMechanics(s).angular_momentum_kg_m2_s;
    };
    near(length(total_p(f.point,second,final)-total_p(first_point,second_point,initial)-
        first.momentum_error_kg_m_s-second_kick.momentum_error_kg_m_s),0,1e-12,"ordered contact momentum receipts");
    near(length(total_l(f.point,second,final)-total_l(first_point,second_point,initial)-
        first.angular_momentum_error_kg_m2_s-second_kick.angular_momentum_error_kg_m2_s),0,1e-12,"ordered contact torque receipts");
    const auto total_ke=[](const ActiveNodeState &a,const ActiveNodeState &b,const RigidMechanicalState &s) {
        return .5*a.mass_kg*lengthSquared(a.velocity_m_s)+.5*b.mass_kg*lengthSquared(b.velocity_m_s)+
            measureRigidMechanics(s).kinetic_energy_j;
    };
    near(total_ke(f.point,second,final)-total_ke(first_point,second_point,initial)+
        first.contact.dissipated_energy_j+second_kick.contact.dissipated_energy_j,
        first.numerical_energy_change_j+second_kick.numerical_energy_change_j,1e-12,"ordered contact loss and roundoff receipts");
    require(length(final.motion.angular_velocity_rad_s-initial.motion.angular_velocity_rad_s)>0,
            "repeated contact lost the native source spin reaction");
    std::cout<<"ordered contacts retain native recoil and separate measured reactions\n";
}
} // namespace
int main() {
    try { std::cout.precision(12);materialReactionAndRounding();atomicRefusal();repeatedContactRetainsNativeState();
        std::cout<<"[PASS] native material-point transfer, actual float accounting and atomic refusal\n";return 0;
    }catch(const std::exception &e) {std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}
}
