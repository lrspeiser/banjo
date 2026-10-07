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
void nearVec(Vec3 value,Vec3 expected,double tolerance,const char *message) {
    near(length(value-expected),0,tolerance,message);
}
const PointShapeContact &single(const auto &query) {
    require(query.contacts.size()==1,"expected one complete native leaf witness");return query.contacts.front();
}
void materialMatches(const CompiledContactMaterial &actual,const MaterialDefinition &material) {
    const auto expected=compileContactMaterial(material);
    require(actual.static_friction==expected.static_friction&&actual.dynamic_friction==expected.dynamic_friction&&
            actual.restitution==expected.restitution&&actual.rolling_resistance==expected.rolling_resistance&&
            actual.young_modulus_pa==expected.young_modulus_pa&&actual.poisson_ratio==expected.poisson_ratio&&
            actual.contact_damping_ratio==expected.contact_damping_ratio,"witness lost its native leaf material");
}
void nativeSphereAndRotatedBoxWitnesses() {
    constexpr double envelope=.016;
    const Vec3 normal=normalized(Vec3{1,2,-3}),centre{10,.5,-4};
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        JoltWorld world;world.setGravity({});
        const auto material=makeReferenceMaterial(preset,17);
        world.addBall({1,.08,material,centre,{1,2,3},{.1,-.2,.3}});
        const auto before=world.snapshot(1);
        for(double gap:{-.002,0.,.003}) {
            const Vec3 at=centre+(.08+envelope+gap)*normal;
            const auto query=world.pointShapeContacts(1,at,envelope,.004);
            const auto &hit=single(query);
            near(hit.gap_m,gap,1e-6,"sphere signed envelope gap");
            nearVec(hit.normal_world,normal,2e-6,"native sphere normal orientation");
            nearVec(hit.point_on_body_world_m,centre+.08*normal,2e-6,"actual sphere surface witness");
            nearVec(hit.point_on_envelope_world_m,at-query.envelope_radius_m*normal,2e-6,"actual point envelope witness");
            near(dot(hit.point_on_envelope_world_m-hit.point_on_body_world_m,hit.normal_world),hit.gap_m,
                 1e-6,"signed gap agrees with witness pair");
            materialMatches(hit.body_contact,material);
        }
        require(world.pointShapeContacts(1,centre+.2*normal,envelope,.004).contacts.empty(),"distant sphere returned a witness");
        same(before,world.snapshot(1));require(world.drainImpacts().empty(),"read-only sphere query produced a contact event");
    }
    const Quat turn{std::cos(std::numbers::pi/8),0,std::sin(std::numbers::pi/8),0};
    const auto iron=makeReferenceMaterial(MaterialPreset::Iron,17);
    JoltWorld world;world.addBox({1,{.4,.08,.06},iron,{centre,turn,{},{}},false});
    const Vec3 face{.2,.01,0},outward=turn.rotate({1,0,0});
    for(double gap:{-.004,0.,.002}) {
        const Vec3 at=centre+turn.rotate(face+(envelope+gap)*Vec3{1,0,0});
        const auto query=world.pointShapeContacts(1,at,envelope,.003);
        const auto &hit=single(query);
        near(hit.gap_m,gap,1e-6,"rotated box signed gap");
        nearVec(hit.normal_world,outward,2e-6,"rotated box actual face normal");
        nearVec(hit.point_on_body_world_m,centre+turn.rotate(face),2e-6,"rotated box surface witness");
    }
    // Inside the rotated box's world AABB, far outside its actual thin shape.
    require(world.pointShapeContacts(1,centre+Vec3{.14,0,.14},.01,.003).contacts.empty(),
            "native point query used the box's world bounds as occupied geometry");
    const Vec3 shift{1e8,-2e8,3e8};
    JoltWorld shifted;shifted.addBox({1,{.4,.08,.06},iron,{centre+shift,turn,{},{}},false});
    const Vec3 at=centre+turn.rotate(face+(envelope+.002)*Vec3{1,0,0});
    const auto base_query=world.pointShapeContacts(1,at,envelope,.003);
    const auto far_query=shifted.pointShapeContacts(1,at+shift,envelope,.003);
    const auto &base=single(base_query),&far=single(far_query);
    near(far.gap_m,base.gap_m,1e-6,"native geometry lost local precision at distant world origin");
    nearVec(far.normal_world,base.normal_world,2e-6,"origin shift changed native shape normal");
    std::cout<<"sphere/rotated-box witnesses retain signed gap, native surface and distant local precision\n";
}
RigidCompoundDescription compound(std::vector<RigidCompoundPart> parts,Vec3 at={},Quat turn={}) {
    RigidCompoundDescription out;out.body_id=1;out.material=makeReferenceMaterial(MaterialPreset::Oak,17);
    Vec3 centroid{};
    for(const auto &part:parts) {
        const auto &material=part.material?*part.material:out.material;
        const double mass=part.geometry.volume()*material.density_kg_m3;
        out.mass_kg+=mass;centroid+=mass*part.center_local_m;
    }
    centroid=centroid/out.mass_kg;
    out.state.center_of_mass_world_m=at+turn.rotate(centroid);out.state.orientation_world=turn;
    for(auto &part:parts) {
        const auto &material=part.material?*part.material:out.material;
        const double mass=part.geometry.volume()*material.density_kg_m3;
        part.center_local_m-=centroid;
        const auto intrinsic=rotateInertia(part.geometry.inertia(mass),part.rotation_local);
        const Vec3 arm=part.center_local_m;
        const double components[]{arm.x,arm.y,arm.z};
        for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)
            out.inertia_local_kg_m2.m[i][j]+=intrinsic.m[i][j]+mass*((i==j?lengthSquared(arm):0)-components[i]*components[j]);
    }
    out.parts=std::move(parts);return out;
}
void compoundMaterialsVoidsAndBudgets() {
    const auto glass=makeReferenceMaterial(MaterialPreset::Glass,17),iron=makeReferenceMaterial(MaterialPreset::Iron,17);
    const RigidPrimitive box{PrimitiveKind::Box,0,{.04,.04,.04}};
    const Vec3 at{3,.2,-1};
    JoltWorld world;
    world.addCompound(compound({{box,{-.06,0,0},{},glass},{box,{.06,0,0},{},iron}},at));
    const auto before=world.snapshot(1);
    require(world.pointShapeContacts(1,at,.01,.005).contacts.empty(),"compound void was filled by a bounding box");
    const auto left_query=world.pointShapeContacts(1,at+Vec3{-.025,0,0},.016,.003);
    const auto &left=single(left_query);
    require(left.shape_user_data==1,"left compound contact lost authored leaf tag");materialMatches(left.body_contact,glass);
    near(left.gap_m,-.001,1e-6,"compound left actual gap");nearVec(left.normal_world,{1,0,0},2e-6,"compound left outward normal");
    const auto right_query=world.pointShapeContacts(1,at+Vec3{.025,0,0},.016,.003);
    const auto &right=single(right_query);
    require(right.shape_user_data==2,"right compound contact lost authored leaf tag");materialMatches(right.body_contact,iron);
    near(right.gap_m,-.001,1e-6,"compound right actual gap");nearVec(right.normal_world,{-1,0,0},2e-6,"compound right outward normal");
    const auto both=world.pointShapeContacts(1,at,.045,0,2);
    require(both.contacts.size()==2&&both.contacts[0].shape_user_data==1&&both.contacts[1].shape_user_data==2,
            "query discarded another native leaf contact or lost canonical ordering");
    const auto again=world.pointShapeContacts(1,at,.045,0,2);
    for(unsigned i=0;i<2;++i) {
        require(both.contacts[i].gap_m==again.contacts[i].gap_m&&both.contacts[i].sub_shape_id==again.contacts[i].sub_shape_id,
                "identical query changed its native witness ordering");
        same(both.contacts[i].point_on_body_world_m,again.contacts[i].point_on_body_world_m,"identical query changed witness");
    }
    bool overflow=false;try {(void)world.pointShapeContacts(1,at,.045,0,1);}catch(const std::length_error &) {overflow=true;}
    require(overflow,"contact capacity silently truncated a multi-leaf result");
    same(before,world.snapshot(1));require(world.drainImpacts().empty(),"read-only compound query changed contact events");
    std::cout<<"mixed compound witnesses preserve both leaf materials and voids; overflow refuses\n";
}
void turnedCylinderAndConvexWitnesses() {
    const auto oak=makeReferenceMaterial(MaterialPreset::Oak,17),glass=makeReferenceMaterial(MaterialPreset::Glass,17);
    const RigidPrimitive cylinder{PrimitiveKind::Cylinder,0,{.08,.2,.08}};
    const Quat part_turn{std::sqrt(.5),0,0,std::sqrt(.5)};
    const Quat body_turn{std::cos(std::numbers::pi/12),0,std::sin(std::numbers::pi/12),0};
    const Vec3 centre{1,.4,-2};
    JoltWorld world;world.addCompound(compound({{cylinder,{},part_turn,oak}},centre,body_turn));
    for(bool cap:{false,true}) {
        const Vec3 local_normal=cap?Vec3{0,1,0}:Vec3{1,0,0};
        const double extent=cap?.1:.04;
        const Vec3 normal=body_turn.rotate(part_turn.rotate(local_normal));
        const Vec3 at=centre+(extent+.016+.002)*normal;
        const auto query=world.pointShapeContacts(1,at,.016,.003);
        const auto &hit=single(query);
        near(hit.gap_m,.002,3e-5,"turned native cylinder side/cap gap");
        nearVec(hit.normal_world,normal,3e-4,"turned native cylinder side/cap normal");
        materialMatches(hit.body_contact,oak);
    }
    // Uniform tetrahedron: independent simplex mass/covariance about centroid.
    constexpr double edge=.1;
    RigidConvexDescription tetra;tetra.body_id=2;tetra.material=glass;
    const Vec3 centroid{edge/4,edge/4,edge/4};
    tetra.state.center_of_mass_world_m=centre+centroid;
    for(Vec3 vertex:{Vec3{},Vec3{edge,0,0},Vec3{0,edge,0},Vec3{0,0,edge}})tetra.vertices_local_m.push_back(vertex-centroid);
    tetra.mass_kg=glass.density_kg_m3*edge*edge*edge/6;
    for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)
        tetra.inertia_local_kg_m2.m[i][j]=tetra.mass_kg*edge*edge*(i==j?3./40:1./80);
    world.addConvex(tetra);
    const Vec3 face{edge/3,edge/3,edge/3},normal=normalized(Vec3{1,1,1});
    const auto query=world.pointShapeContacts(2,centre+face+(.01+.002)*normal,.01,.003);
    const auto &hit=single(query);
    near(hit.gap_m,.002,3e-5,"convex tetrahedron diagonal face gap");
    nearVec(hit.normal_world,normal,3e-4,"convex tetrahedron diagonal normal");
    materialMatches(hit.body_contact,glass);
    require(world.pointShapeContacts(2,centre+Vec3{.075,.075,.075},.01,.003).contacts.empty(),
            "convex tetrahedron query substituted its enclosing box");
    std::cout<<"turned cylinder and convex tetrahedron use their actual native surfaces\n";
}
void actualWitnessFeedsNativeReaction() {
    constexpr double envelope=.016;
    const Vec3 centre{1,.5,-.5};
    const Quat turn{std::cos(std::numbers::pi/12),0,std::sin(std::numbers::pi/12),0};
    const auto oak=makeReferenceMaterial(MaterialPreset::Oak,17);
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        JoltWorld world;world.setGravity({});
        const auto material=makeReferenceMaterial(preset,17);
        world.addBox({1,{.4,.08,.06},material,{centre,turn,{-1,.2,.4},{1,-2,.3}},false});
        world.addBox({2,{.01,.01,.01},oak,{{4,4,4},{},{},{}},true});
        world.setPairContactOwner(2,1,PairContactOwner::External);
        const auto before=world.mechanicalState(1);
        ActiveNodeState point;
        point.position_world_m=centre+turn.rotate({.2+envelope-.001,.01,0});
        point.previous_position_world_m=point.position_world_m;
        point.mass_kg=oak.density_kg_m3*cell*cell*cell;
        const auto query=world.pointShapeContacts(1,point.position_world_m,envelope,.003);
        const auto &hit=single(query);
        const Vec3 tangent=turn.rotate({0,1,0});
        point.velocity_m_s=before.motion.linear_velocity_m_s+
            cross(before.motion.angular_velocity_rad_s,point.position_world_m-centre)-2*hit.normal_world+.5*tangent;
        const auto law=combineContactMaterials(compileContactMaterial(oak),hit.body_contact);
        const auto result=world.applyExternalPointContact(2,1,point,hit.normal_world,hit.gap_m,dt,
            {law.static_friction,law.dynamic_friction,law.restitution},rounding);
        require(result.contact.applied,"actual native shape witness did not produce contact reaction");
        require(std::abs(result.numerical_energy_change_j)<rounding.energy_j,"actual-witness native reaction work budget");
        std::cout<<"actual "<<materialPresetName(preset)<<" box: source mass="<<before.mass_kg<<" kg; gap="<<hit.gap_m
                 <<" m; Jn="<<result.contact.normal_impulse_n_s<<" N s; loss="<<result.contact.dissipated_energy_j
                 <<" J; dE="<<result.numerical_energy_change_j<<" J; dP="<<length(result.momentum_error_kg_m_s)
                 <<" N s; dL="<<length(result.angular_momentum_error_kg_m2_s)<<" kg m2/s\n";
    }
}
void nativeFixedToolRetainsItsLoadPath() {
    const auto oak=makeReferenceMaterial(MaterialPreset::Oak,17);
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        JoltWorld world;world.setGravity({});
        const auto material=makeReferenceMaterial(preset,17);
        world.addBox({1,{.08,.08,.08},material,{{},{},{2,0,0},{}},false});
        world.addBox({10,{.24,.04,.04},oak,{{-.16,0,0},{},{2,0,0},{}},false});
        world.addBox({2,{.01,.01,.01},oak,{{5,5,5},{},{},{}},true});
        const unsigned fixing=world.addFixing({10,1,{-.04,0,0},{1,0,0},5000,5000,0});
        // The fixing owns the joined seam's response; the external target owns
        // both source/target pairs. No head/handle is released or merged.
        for(auto pair:{std::pair{10U,1U},std::pair{2U,1U},std::pair{2U,10U}})
            world.setPairContactOwner(pair.first,pair.second,PairContactOwner::External);
        world.setDamping(1,0,0);world.setDamping(10,0,0);
        ActiveNodeState point;point.mass_kg=oak.density_kg_m3*cell*cell*cell;
        point.position_world_m={.04+.016-.001,.01,0};point.previous_position_world_m=point.position_world_m;
        const auto query=world.pointShapeContacts(1,point.position_world_m,.016,.003);
        const auto &hit=single(query);
        const auto law=combineContactMaterials(compileContactMaterial(oak),hit.body_contact);
        const auto handle_before=world.snapshot(10);
        const auto kick=world.applyExternalPointContact(2,1,point,hit.normal_world,hit.gap_m,dt,
            {law.static_friction,law.dynamic_friction,law.restitution},rounding);
        require(kick.contact.applied,"tool head witness produced no native reaction");
        same(handle_before,world.snapshot(10)); // A head contact is not spread over its handle.
        const auto before=world.mechanicalTotals();
        const auto root=world.snapshot(10);
        const Vec3 grip_local{-.08,0,0},grip=root.center_of_mass_world_m+root.orientation_world.rotate(grip_local);
        const Vec3 force{25,-7,3},torque{0,.2,-.1};
        require(length(force)<800&&length(torque)<60,"fixture exceeded the native hand bounds");
        const Vec3 old_grip_velocity=root.linear_velocity_m_s+
            cross(root.angular_velocity_rad_s,root.orientation_world.rotate(grip_local));
        world.pushBodyAt(10,force,grip);world.twistBody(10,torque);
        world.step(dt);
        const auto after=world.mechanicalTotals();
        const auto now=world.snapshot(10);
        const Vec3 grip_velocity=now.linear_velocity_m_s+cross(now.angular_velocity_rad_s,now.orientation_world.rotate(grip_local));
        const double work=dt*(dot(force,.5*(old_grip_velocity+grip_velocity))+
            dot(torque,.5*(root.angular_velocity_rad_s+now.angular_velocity_rad_s)));
        const Vec3 p_error=after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s-dt*force;
        const Vec3 l_error=after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s-dt*(cross(grip,force)+torque);
        require(length(p_error)<1e-5&&length(l_error)<1e-5,"native fixing/root load momentum residual exceeded fixture bound");
        const auto load=world.jointLoad(fixing,{1,0,0});
        require(std::isfinite(load.tension_n)&&std::isfinite(load.shear_n)&&load.tension_n>0&&
            load.tension_n<5000&&load.shear_n<5000,"ordinary tool fixing did not retain its measured finite load");
        require(length(now.linear_velocity_m_s-handle_before.linear_velocity_m_s)>0,"head reaction bypassed the native handle load path");
        std::cout<<materialPresetName(preset)<<" fixed source: head mass="<<kick.delivered_rigid.mass_kg
                 <<" kg; handle mass="<<world.mechanicalState(10).mass_kg<<" kg; axial="<<load.axial_n
                 <<" N; shear="<<load.shear_n<<" N; root work="<<work<<" J; dP="<<length(p_error)
                 <<" N s; dL="<<length(l_error)<<" kg m2/s; unallocated dK-work="
                 <<after.kinetic_energy_j-before.kinetic_energy_j-work<<" J\n";
    }
}
struct FixedFixture {
    JoltWorld world;ActiveNodeState point;PointRigidContactSettings law;unsigned fixing{};
    explicit FixedFixture(MaterialPreset preset=MaterialPreset::Glass,bool turned=false,bool static_handle=false,double one_way=0) {
        world.setGravity({});
        const auto oak=makeReferenceMaterial(MaterialPreset::Oak,17),material=makeReferenceMaterial(preset,17);
        const Quat rotation=turned?Quat{std::sqrt(.5),0,std::sqrt(.5),0}:Quat{};
        const Vec3 origin=turned?Vec3{1,.5,-.5}:Vec3{};
        world.addBox({1,{.08,.08,.08},material,{origin,rotation,rotation.rotate({2,0,0}),{}},false});
        world.addBox({10,{.24,.04,.04},oak,{origin+rotation.rotate({-.16,0,0}),rotation,
            static_handle?Vec3{}:rotation.rotate({2,0,0}),{}},static_handle});
        world.addBox({2,{.01,.01,.01},oak,{{5,5,5},{},{},{}},true});
        fixing=world.addFixing({10,1,origin+rotation.rotate({-.04,0,0}),rotation.rotate({1,0,0}),one_way>0?0.:5000.,5000,one_way});
        for(auto pair:{std::pair{10U,1U},std::pair{2U,1U},std::pair{2U,10U}})
            world.setPairContactOwner(pair.first,pair.second,PairContactOwner::External);
        world.setDamping(1,0,0);if(!static_handle)world.setDamping(10,0,0);
        point.mass_kg=oak.density_kg_m3*cell*cell*cell;
        point.position_world_m=origin+rotation.rotate({.055,.01,0});point.previous_position_world_m=point.position_world_m;
        const auto contact=combineContactMaterials(compileContactMaterial(material),compileContactMaterial(oak));
        law={contact.static_friction,contact.dynamic_friction,contact.restitution};
    }
    FixedPointContactKick kick(const PointContactRoundoffBudget &budget=rounding) {
        const auto query=world.pointShapeContacts(1,point.position_world_m,.016,.003);
        const auto &hit=single(query);
        return world.applyExternalFixedPointContact(2,1,point,hit.normal_world,hit.gap_m,dt,law,budget);
    }
};
void nativeFixedContactUsesActualConstraintInertia() {
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        FixedFixture f(preset);
        const auto head=f.world.mechanicalState(1),handle=f.world.mechanicalState(10);
        const auto old_point=f.point;const auto proxy=f.world.snapshot(2);
        const auto receipt=f.kick();
        require(receipt.contact.modal_contact.applied&&receipt.body_ids==std::vector<MatterBodyId>{1,10}&&
            receipt.joint_ids==std::vector<unsigned>{f.fixing},"native fixed contact lost member/constraint identity");
        require(receipt.links.size()==1&&receipt.links[0].a==1&&receipt.links[0].b==0,
            "native constraint orientation changed");
        near(length(receipt.links[0].point_a_world_m-Vec3{-.04,0,0}),0,2e-8,"native handle attachment witness");
        near(length(receipt.links[0].point_b_world_m-Vec3{-.04,0,0}),0,2e-8,"native head attachment witness");
        require(length(f.world.snapshot(10).linear_velocity_m_s-handle.motion.linear_velocity_m_s)>0&&
            length(receipt.contact.contact_reactions[0].impulse_on_b_n_s)>0,"handle had no simultaneous contact reaction");
        double change=0;
        for(std::size_t i=0;i<receipt.body_ids.size();++i) {
            const auto state=f.world.mechanicalState(receipt.body_ids[i]);const auto &before=i==0?head:handle;
            same(state.motion,receipt.delivered_bodies[i].motion);
            same(state.motion.center_of_mass_world_m,before.motion.center_of_mass_world_m,"fixed contact moved source geometry");
            require(state.mass_kg==before.mass_kg&&state.inertia_world_kg_m2.m==before.inertia_world_kg_m2.m,
                "native constrained response changed constituent mass/tensor");
            change+=measureRigidMechanics(state).kinetic_energy_j-measureRigidMechanics(before).kinetic_energy_j;
        }
        change+=.5*old_point.mass_kg*dot(f.point.velocity_m_s-old_point.velocity_m_s,f.point.velocity_m_s+old_point.velocity_m_s);
        near(change+receipt.contact.reconciliation_loss_j+receipt.contact.modal_contact.dissipated_energy_j,
            receipt.numerical_energy_change_j,1e-12,"actual fixed transfer kinetic/work ledger");
        same(proxy,f.world.snapshot(2));same(old_point.position_world_m,f.point.position_world_m,"fixed contact moved target");
        const auto &link=receipt.links[0];
        const auto &a=receipt.delivered_bodies[link.a].motion,&b=receipt.delivered_bodies[link.b].motion;
        near(length(a.linear_velocity_m_s+cross(a.angular_velocity_rad_s,link.point_a_world_m-a.center_of_mass_world_m)-
            b.linear_velocity_m_s-cross(b.angular_velocity_rad_s,link.point_b_world_m-b.center_of_mass_world_m)),0,2e-7,
            "native float fixing velocity residual");
        const auto load=f.world.jointLoad(f.fixing,{1,0,0});
        require(load.tension_n==0&&load.shear_n==0,"external contact falsely rewrote native cached constraint lambda");
        std::cout<<materialPresetName(preset)<<" simultaneous fixing: Jn="<<receipt.contact.modal_contact.normal_impulse_n_s
            <<" N s; joint impulse="<<length(receipt.contact.contact_reactions[0].impulse_on_b_n_s)
            <<" N s; loss="<<receipt.contact.modal_contact.dissipated_energy_j<<" J; reconcile="<<receipt.contact.reconciliation_loss_j
            <<" J; dE="<<receipt.numerical_energy_change_j<<" J; dP="<<length(receipt.momentum_error_kg_m_s)
            <<" N s; dL="<<length(receipt.angular_momentum_error_kg_m2_s)<<" kg m2/s\n";
        // The next native step retains source motion, rather than resetting the tool.
        const auto before=f.world.mechanicalTotals();f.world.step(dt);const auto after=f.world.mechanicalTotals();
        require(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s)<1e-5&&
            length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s)<1e-5,
            "following native fixed step lost momentum");
        require(f.world.drainImpacts().empty(),"proxy or seam supplied a duplicate native contact");
        std::cout<<"  subsequent free fixed step unallocated dK="<<after.kinetic_energy_j-before.kinetic_energy_j<<" J\n";
    }
    FixedFixture rotated(MaterialPreset::Iron,true);
    const auto receipt=rotated.kick();
    near(length(receipt.links[0].point_a_world_m-Vec3{1,.5,-.46}),0,2e-8,"rotated native constraint attachment");
    require(std::abs(receipt.numerical_energy_change_j)<rounding.energy_j,"rotated fixed native transfer roundoff");
}
template<class Action> void fixedRefusedWithoutMutation(FixedFixture &f,Action action) {
    const auto head=f.world.snapshot(1),handle=f.world.snapshot(10),proxy=f.world.snapshot(2);const auto point=f.point;
    bool refused=false;try{action();}catch(const std::invalid_argument &){refused=true;}
    require(refused,"unsupported fixed contact admitted");
    same(head,f.world.snapshot(1));same(handle,f.world.snapshot(10));same(proxy,f.world.snapshot(2));
    same(point.velocity_m_s,f.point.velocity_m_s,"refused fixed response changed external point");
}
void nativeFixedContactRefusesAtomically() {
    FixedFixture measured;const auto receipt=measured.kick();
    for(unsigned field=0;field<3;++field) {
        FixedFixture f;auto budget=rounding;
        if(field==0)budget.energy_j=.5*std::abs(receipt.numerical_energy_change_j);
        if(field==1)budget.linear_impulse_n_s=.5*length(receipt.momentum_error_kg_m_s);
        if(field==2)budget.angular_impulse_kg_m2_s=.5*length(receipt.angular_momentum_error_kg_m2_s);
        fixedRefusedWithoutMutation(f,[&]{(void)f.kick(budget);});
    }
    FixedFixture missing;missing.world.setPairContactOwner(2,10,PairContactOwner::Jolt);
    fixedRefusedWithoutMutation(missing,[&]{(void)missing.kick();});
    FixedFixture seam;seam.world.setPairContactOwner(1,10,PairContactOwner::Jolt);
    fixedRefusedWithoutMutation(seam,[&]{(void)seam.kick();});
    FixedFixture pinned;pinned.world.pinToWorld(10);fixedRefusedWithoutMutation(pinned,[&]{(void)pinned.kick();});
    FixedFixture anchored(MaterialPreset::Glass,false,true);fixedRefusedWithoutMutation(anchored,[&]{(void)anchored.kick();});
    FixedFixture one_way(MaterialPreset::Glass,false,false,100);fixedRefusedWithoutMutation(one_way,[&]{(void)one_way.kick();});
    FixedFixture spring;spring.world.addDistanceSpring(1,10,.16,1000,0);
    fixedRefusedWithoutMutation(spring,[&]{(void)spring.kick();});
    FixedFixture loop;(void)loop.world.addFixing({1,10,{-.04,0,0},{1,0,0},5000,5000,0});
    fixedRefusedWithoutMutation(loop,[&]{(void)loop.kick();});
    FixedFixture speed;speed.point.velocity_m_s={-1e6,0,0};fixedRefusedWithoutMutation(speed,[&]{(void)speed.kick();});
    FixedFixture trial;bool refused=false;const auto old_point=trial.point;
    const auto head=trial.world.snapshot(1),handle=trial.world.snapshot(10);
    const bool accepted=trial.world.runReversibleTrial([&]{try{(void)trial.kick();}catch(const std::logic_error &){refused=true;}return false;});
    require(refused&&!accepted,"fixed contact escaped native trial recorder");
    same(old_point.velocity_m_s,trial.point.velocity_m_s,"fixed trial changed external point");
    same(head,trial.world.snapshot(1));same(handle,trial.world.snapshot(10));
}
void orderedNativeFixedContactsRetainAllAccounts() {
    FixedFixture f(MaterialPreset::Iron);auto second=f.point;second.position_world_m.y=-.01;
    second.previous_position_world_m=second.position_world_m;
    const auto totals=[&]() {
        auto out=f.world.mechanicalTotals();
        for(const auto *p:{&f.point,&second}) {
            out.linear_momentum_kg_m_s+=p->mass_kg*p->velocity_m_s;
            out.angular_momentum_kg_m2_s+=cross(p->position_world_m,p->mass_kg*p->velocity_m_s);
            out.kinetic_energy_j+=.5*p->mass_kg*lengthSquared(p->velocity_m_s);
        }
        return out;
    };
    const auto before=totals();const auto first=f.kick();
    const auto query=f.world.pointShapeContacts(1,second.position_world_m,.016,.003);const auto &hit=single(query);
    const auto next=f.world.applyExternalFixedPointContact(2,1,second,hit.normal_world,hit.gap_m,dt,f.law,rounding);
    require(next.contact.modal_contact.applied,"second fixed contact lost source recoil");
    const auto after=totals();
    near(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s-first.momentum_error_kg_m_s-next.momentum_error_kg_m_s),
        0,1e-12,"cumulative fixed contact momentum receipts");
    near(length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s-first.contact.geometry_couple_kg_m2_s-
        next.contact.geometry_couple_kg_m2_s-first.angular_momentum_error_kg_m2_s-next.angular_momentum_error_kg_m2_s),
        0,1e-12,"cumulative fixed contact moment/couple receipts");
    near(after.kinetic_energy_j-before.kinetic_energy_j+first.contact.reconciliation_loss_j+next.contact.reconciliation_loss_j+
        first.contact.modal_contact.dissipated_energy_j+next.contact.modal_contact.dissipated_energy_j,
        first.numerical_energy_change_j+next.numerical_energy_change_j,1e-12,"cumulative fixed contact kinetic/work receipts");
    std::cout<<"ordered fixed contacts preserve actual native recoil and separate joint/work accounts\n";
}
void nativeOccupiedCuboidWitnesses() {
    const RigidPrimitive cell_box{PrimitiveKind::Box,0,{.04,.04,.04}};
    const Quat turn{std::cos(std::numbers::pi/8),0,0,std::sin(std::numbers::pi/8)};
    for(const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto material=makeReferenceMaterial(preset,17);JoltWorld world;
        world.addBox({1,{.08,.08,.08},material,{{},{},{},{}},false});
        const auto original=world.snapshot(1);
        for(const double gap:{-.002,.001,.003}) {
            const auto q=world.materialShapeContacts(1,{.06+gap,0,0},cell_box,{},.004);
            const auto &hit=single(q);
            near(hit.gap_m,gap,1e-6,"cuboid occupied face gap");
            nearVec(hit.normal_world,{1,0,0},2e-6,"cuboid face normal");
            near(dot(hit.point_on_envelope_world_m-hit.point_on_body_world_m,hit.normal_world),gap,1e-6,
                "cuboid witnesses disagree with signed separation");
            near(hit.point_on_envelope_world_m.x,.04+gap,1e-6,"native occupied cell face witness");
            materialMatches(hit.body_contact,material);
        }
        // The cube's corner enters occupied matter although its 16 mm sphere
        // does not. This is the missing geometric coverage, without a force.
        const Vec3 corner{.057,.057,0};
        require(world.pointShapeContacts(1,corner,.016).contacts.empty(),"corner fixture sphere unexpectedly contacts");
        require(!world.materialShapeContacts(1,corner,cell_box).contacts.empty(),"actual occupied cube corner was omitted");
        const double extent=.02*std::sqrt(2.);
        const auto turned_query=world.materialShapeContacts(1,{.04+extent+.001,0,0},cell_box,turn,.003);
        const auto &rotated=single(turned_query);
        near(rotated.gap_m,.001,2e-6,"turned cuboid used unturned lengths");
        JoltWorld sphere;sphere.addBall({1,.08,material,{},{},{}});
        const auto sphere_query=sphere.materialShapeContacts(1,{.101,0,0},cell_box,{},.003);
        near(single(sphere_query).gap_m,.001,2e-6,"occupied cuboid missed native sphere surface");
        JoltWorld rotated_source;rotated_source.addBox({1,{.4,.08,.06},material,{{},turn,{},{}},false});
        const Vec3 face=turn.rotate({.221,0,0});
        const auto turned_pair=rotated_source.materialShapeContacts(1,face,cell_box,turn,.003);
        near(single(turned_pair).gap_m,.001,2e-6,"turned source/cell face gap");
        nearVec(single(turned_pair).normal_world,turn.rotate({1,0,0}),3e-6,"turned source/cell normal");
        same(original,world.snapshot(1));require(world.drainImpacts().empty(),"occupied geometry query generated physical impact");
        // Actual compound leaves preserve the hole and native per-leaf material.
        JoltWorld hollow;const RigidPrimitive leaf{PrimitiveKind::Box,0,{.04,.04,.04}};
        hollow.addCompound(compound({{leaf,{-.06,0,0},{},material},{leaf,{.06,0,0},{},material}}));
        require(hollow.materialShapeContacts(1,{},cell_box).contacts.empty(),"compound hole replaced by bounds");
        const auto leaf_query=hollow.materialShapeContacts(1,{.091,0,0},cell_box,{},.002);
        const auto &leaf_hit=single(leaf_query);
        require(leaf_hit.shape_user_data==2,"cuboid query lost compound leaf identity");materialMatches(leaf_hit.body_contact,material);
        bool refused=false;
        try {(void)hollow.materialShapeContacts(1,{}, {PrimitiveKind::Box,0,{.2,.04,.04}},{},0,1);}
        catch(const std::length_error &) {refused=true;}
        require(refused,"cuboid witness overflow silently truncated leaves");
    }
    JoltWorld world;const auto iron=makeReferenceMaterial(MaterialPreset::Iron,17);
    const Vec3 shift{1e8,-2e8,3e8};world.addBox({1,{.08,.08,.08},iron,{shift,{},{},{}},false});
    const auto far_query=world.materialShapeContacts(1,shift+Vec3{.061,0,0},cell_box,{},.003);
    const auto &far=single(far_query);
    near(far.gap_m,.001,1e-6,"cuboid query lost local precision at distant origin");
    for(const auto geometry:std::vector<RigidPrimitive>{{PrimitiveKind::Box,0,{0,.04,.04}},
            {PrimitiveKind::Box,0,{201,.04,.04}},{PrimitiveKind::Cylinder,0,{.04,.04,.04}}}) {
        bool refused=false;try {(void)world.materialShapeContacts(1,shift,geometry);}
        catch(const std::invalid_argument &) {refused=true;}require(refused,"unsupported cell geometry admitted");
    }
    bool refused=false;try {(void)world.materialShapeContacts(1,shift,cell_box,{2,0,0,0});}
    catch(const std::invalid_argument &) {refused=true;}require(refused,"nonunit cuboid orientation admitted");
}
void invalidQueriesRefuse() {
    Fixture f;const auto before=f.world.snapshot(1);
    for(const auto values:std::vector<std::pair<double,double>>{{0,0},{1e-7,0},{101,0},{.01,-1},{.01,1.01},
        {std::numeric_limits<double>::infinity(),0},{.01,std::numeric_limits<double>::quiet_NaN()}}) {
        bool refused=false;try {(void)f.world.pointShapeContacts(1,f.point.position_world_m,values.first,values.second);}
        catch(const std::invalid_argument &) {refused=true;}require(refused,"invalid envelope/search distance admitted");
    }
    for(unsigned budget:{0U,257U}) {
        bool refused=false;try {(void)f.world.pointShapeContacts(1,f.point.position_world_m,.01,0,budget);}
        catch(const std::invalid_argument &) {refused=true;}require(refused,"invalid witness budget admitted");
    }
    for(Vec3 at:{Vec3{std::numeric_limits<double>::quiet_NaN(),0,0},Vec3{1e300,0,0}}) {
        bool refused=false;try {(void)f.world.pointShapeContacts(1,at,.01);}
        catch(const std::invalid_argument &) {refused=true;}require(refused,"invalid native query coordinates admitted");
    }
    bool refused=false;try {(void)f.world.pointShapeContacts(999,{},.01);}
    catch(const std::invalid_argument &) {refused=true;}require(refused,"missing native query body admitted");
    same(before,f.world.snapshot(1));
}
} // namespace
int main() {
    try { std::cout.precision(12);materialReactionAndRounding();atomicRefusal();repeatedContactRetainsNativeState();
        nativeSphereAndRotatedBoxWitnesses();compoundMaterialsVoidsAndBudgets();turnedCylinderAndConvexWitnesses();
        actualWitnessFeedsNativeReaction();invalidQueriesRefuse();nativeOccupiedCuboidWitnesses();
        nativeFixedToolRetainsItsLoadPath();
        nativeFixedContactUsesActualConstraintInertia();nativeFixedContactRefusesAtomically();
        orderedNativeFixedContactsRetainAllAccounts();
        std::cout<<"[PASS] native material-point transfer, shape witnesses, float accounting and atomic refusal\n";return 0;
    }catch(const std::exception &e) {std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}
}
