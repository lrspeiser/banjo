#include "creator/CreatorWorld.hpp"
#include "physics/RollingKinematics.hpp"
#include <nlohmann/json.hpp>
#include <cmath>
#include <functional>
#include <iostream>
#include <numbers>
#include <stdexcept>

namespace {
using namespace banjo;
using Json=nlohmann::json;
void require(bool value,const char *message) {if (!value) throw std::runtime_error(message);}
void near(double a,double b,double tolerance,const char *message) {require(std::isfinite(a)&&std::abs(a-b)<=tolerance,message);}
void rejects(const std::function<void()> &action) {bool failed=false;try {action();}catch(const std::exception &){failed=true;}require(failed,"invalid command must reject");}
void inventoryAndAtomicCreation() {
    CreatorWorld world;ObjectRecipe r;
    const auto before=world.serialize();rejects([&]{(void)world.create("first",r);});require(world.serialize()==before,"uncollected material cannot be spent");
    require(world.collect("oak-pile")&&!world.collect("oak-pile"),"pickup is idempotent");
    const auto plan=world.preview(r);near(world.inventoryMass(MaterialPreset::Oak),10,0,"preview does not consume inventory");
    const auto id=world.create("first",r);near(world.inventoryMass(MaterialPreset::Oak)+plan.mass_kg,10,1e-12,"created matter plus inventory retains original lot mass");
    const auto created=world.serialize();require(world.create("first",r)==id&&world.serialize()==created,"request replay does not mint or debit twice");
    auto changed=r;changed.radius_m=.07;rejects([&]{(void)world.create("first",changed);});
    rejects([&]{(void)world.create("overlapping",r);});changed.shape="door";rejects([&]{(void)world.create("unsupported",changed);});
    changed=r;changed.radius_m=.5;rejects([&]{(void)world.create("unaffordable",changed);});changed=r;changed.physics="brittle";rejects([&]{(void)world.create("wrong-law",changed);});
    require(world.serialize()==created,"all failed creations retain object and inventory state");
    world.step(10);require(world.create("first",r)==id,"replay remains valid after the original object moves");
}
void threeMaterialCreationAndFreeFall() {
    double previous_y=0,previous_v=0;
    for (auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld world({.slope_degrees=0});ObjectRecipe r;r.material=material;r.clearance_m=1.5;
        world.collect(std::string(materialPresetName(material))+"-pile");const auto id=world.create("drop",r);(void)id;
        const auto &first=world.objects().front();const double expected=4.0/3*std::numbers::pi*std::pow(r.radius_m,3)*makeReferenceMaterial(material).density_kg_m3;
        near(first.mass_kg,expected,1e-12,"compiled mass comes from occupied sphere matter");
        near(first.inertia_local_kg_m2.m[0][0],.4*expected*r.radius_m*r.radius_m,1e-12,"compiled sphere inertia");
        near(world.inventoryMass(material)+expected,10,1e-12,"per-material inventory/matter ledger");
        world.step(48);const auto &s=world.objects().front().state;
        near(s.linear_velocity_m_s.y,-9.81*.2,1e-5,"created object follows gravitational acceleration");
        near(s.center_of_mass_world_m.y,r.radius_m+r.clearance_m-.5*9.81*.2*.2,.005,"created object follows free-fall position within fixed-step truncation bound");
        if (previous_y) {near(s.center_of_mass_world_m.y,previous_y,1e-6,"density does not change free-fall position");near(s.linear_velocity_m_s.y,previous_v,1e-6,"density does not change acceleration");}
        previous_y=s.center_of_mass_world_m.y;previous_v=s.linear_velocity_m_s.y;
        std::cout<<materialPresetName(material)<<" mass="<<expected<<" remaining="<<world.inventoryMass(material)<<" fall-vy="<<previous_v<<'\n';
    }
}
void createdObjectsRoll() {
    CreatorWorld world;
    for (auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        world.collect(std::string(materialPresetName(material))+"-pile");ObjectRecipe r;r.material=material;r.bitangent_m=static_cast<double>(world.objects().size())-1;
        (void)world.create(std::string(materialPresetName(material)),r);
    }
    world.step(240);
    for (const auto &object:world.objects()) {
        const auto measured=measureRollingKinematics(object.state,object.recipe.radius_m,world.support());
        require(dot(object.state.linear_velocity_m_s,world.support().tangent_world)>.2,"created sphere moves downhill");
        require(length(object.state.angular_velocity_rad_s)>.5,"contact creates spin from a nonspinning creation");
        require(measured.state==RollingState::Rolling&&measured.contact_slip_speed_m_s<.02,"rolling is measured from actual contact slip");
        std::cout<<materialPresetName(object.recipe.material)<<" slope-speed="<<measured.translation_speed_m_s<<" slip="<<measured.contact_slip_speed_m_s<<'\n';
    }
}
void finiteMaterialCollision() {
    for (auto target:{MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld world({.slope_degrees=0,.gravity_m_s2={}});
        world.collect("glass-pile");world.collect(std::string(materialPresetName(target))+"-pile");
        ObjectRecipe a;a.material=MaterialPreset::Glass;a.tangent_m=-.3;a.clearance_m=1;a.linear_velocity_m_s={.5,0,0};
        auto b=a;b.material=target;b.tangent_m=.3;b.linear_velocity_m_s={-.5,0,0};
        (void)world.create("a",a);(void)world.create("b",b);
        const double ma=world.objects()[0].mass_kg,mb=world.objects()[1].mass_kg,p0=.5*(ma-mb),k0=.125*(ma+mb);
        world.step(192);
        const auto va=world.objects()[0].state.linear_velocity_m_s,vb=world.objects()[1].state.linear_velocity_m_s;
        near(length(ma*va+mb*vb-Vec3{p0,0,0}),0,2e-6*(ma+mb),"finite created bodies exchange momentum");
        require(.5*ma*lengthSquared(va)+.5*mb*lengthSquared(vb)<=k0+1e-6,"created collision does not create kinetic energy");
        require(va.x<.5&&vb.x>-.5,"both created bodies receive collision reactions");
    }
}
Quat zRotation(double radians) {return {std::cos(radians/2),0,0,std::sin(radians/2)};}
ObjectRecipe boxRecipe(MaterialPreset material=MaterialPreset::Oak) {
    ObjectRecipe r;r.schema_version=2;r.shape="box";r.name="Rectangular test object";r.material=material;r.dimensions_m={.08,.06,.10};return r;
}
void primitiveGeometryAndPlacement() {
    const RigidPrimitive box{PrimitiveKind::Box,0,{.2,.2,.2}},sphere{PrimitiveKind::Sphere,.04,{}};
    require(!primitivesOverlap(sphere,{.14,.14,0},{},box,{},{}),"sphere clears actual box corner despite overlapping axis bounds");
    require(primitivesOverlap(sphere,{.125,.125,0},{},box,{},{}),"sphere intersects actual box corner");
    const RigidPrimitive slender{PrimitiveKind::Box,0,{.4,.04,.04}};
    require(!primitivesOverlap(slender,{}, {},slender,{0,0,.1},{}),"parallel boxes are not replaced by enclosing spheres");
    require(primitivesOverlap(slender,{}, {},slender,{},zRotation(std::numbers::pi/2)),"crossing boxes intersect");
    CreatorWorld world({.slope_degrees=0});world.collect("oak-pile");auto r=boxRecipe();r.dimensions_m={.5,.03,.03};r.tangent_m=7.8;
    rejects([&]{(void)world.preview(r);});r.orientation_world=zRotation(std::numbers::pi/2);
    const auto p=world.preview(r);near(p.position_world_m.y,.25+r.clearance_m,1e-12,"rotated support extent sets placement height");
    (void)world.create("rotated-edge",r);
    const auto before=world.serialize();rejects([&]{(void)world.create("overlap",r);});
    auto invalid=r;invalid.dimensions_m.y=0;rejects([&]{(void)world.create("zero-width",invalid);});
    invalid=r;invalid.orientation_world={2,0,0,0};rejects([&]{(void)world.create("bad-orientation",invalid);});
    invalid=r;invalid.schema_version=1;rejects([&]{(void)world.create("wrong-version",invalid);});
    require(world.serialize()==before,"failed shape transactions preserve inventory and state");
    auto wire=Json::parse(CreatorWorld::recipeJson(r));wire["shape"]["radius_m"]=.1;
    rejects([&]{(void)CreatorWorld::parseRecipe(wire.dump());});
}
void threeMaterialBoxMassInertiaAndFall() {
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld world({.slope_degrees=0});world.collect(std::string(materialPresetName(material))+"-pile");
        auto r=boxRecipe(material);r.clearance_m=1.5;r.orientation_world=zRotation(std::numbers::pi/4);
        const auto id=world.create("box",r);const auto &o=world.objects().front();
        const double expected_mass=.08*.06*.10*makeReferenceMaterial(material).density_kg_m3;
        near(o.mass_kg,expected_mass,1e-12,"box volume and material density set inventory mass");
        const double ix=expected_mass*(.06*.06+.10*.10)/12,iy=expected_mass*(.08*.08+.10*.10)/12,iz=expected_mass*(.08*.08+.06*.06)/12;
        near(o.inertia_local_kg_m2.m[0][0],ix,1e-12,"box Ixx analytical");
        near(o.inertia_local_kg_m2.m[1][1],iy,1e-12,"box Iyy analytical");
        near(o.inertia_local_kg_m2.m[2][2],iz,1e-12,"box Izz analytical");
        const auto measured=world.mechanicalState(id);
        near(measured.mass_kg,expected_mass,expected_mass*2e-7,"solver accepted material mass");
        near(measured.inertia_world_kg_m2.m[0][0],(ix+iy)/2,expected_mass*1e-8,"rotated solver inertia diagonal");
        near(measured.inertia_world_kg_m2.m[0][1],(ix-iy)/2,expected_mass*1e-8,"nonzero world off-diagonal inertia survives insertion");
        near(measured.inertia_world_kg_m2.m[2][2],iz,expected_mass*1e-8,"solver box principal inertia");
        const double initial_y=o.state.center_of_mass_world_m.y;world.step(48);
        near(world.objects()[0].state.linear_velocity_m_s.y,-1.962,1e-5,"box free-fall acceleration is density independent");
        near(world.objects()[0].state.center_of_mass_world_m.y,initial_y-.1962,.005,"box free-fall position within fixed-step truncation");
        near(world.inventoryMass(material)+expected_mass,10,1e-12,"box material ledger closes");
        std::cout<<materialPresetName(material)<<" box-mass="<<o.mass_kg<<" inertia="<<ix<<','<<iy<<','<<iz<<'\n';
    }
}
void matchedShapeRampAndPersistence() {
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld world;world.collect(std::string(materialPresetName(material))+"-pile");
        ObjectRecipe sphere;sphere.material=material;sphere.radius_m=.04;sphere.bitangent_m=-.25;
        auto box=boxRecipe(material);box.dimensions_m.z=sphere.geometry().volume()/(box.dimensions_m.x*box.dimensions_m.y);
        box.bitangent_m=.25;box.orientation_world=zRotation(-std::numbers::pi/18);
        (void)world.create("sphere",sphere);(void)world.create("box",box);
        near(world.objects()[0].mass_kg,world.objects()[1].mass_kg,1e-12,"shape comparison holds occupied volume and per-material mass fixed");
        const auto initial=world.objects()[1].state.center_of_mass_world_m;
        world.step(240);
        const auto sphere_motion=measureCreatorMotion(world.objects()[0],world.support());
        const auto box_motion=measureCreatorMotion(world.objects()[1],world.support());
        require(sphere_motion.state=="rolling (near-zero slip)"&&sphere_motion.speed_m_s>.5&&sphere_motion.slip_m_s<.02,"matched sphere rolls physically");
        require(box_motion.state=="resting"&&box_motion.near_support_points>=3,"flat box rests on its face rather than rolling as a sphere");
        require(length(world.objects()[1].state.center_of_mass_world_m-initial)<.005,"box stays on high-friction shallow ramp within settling displacement");
        const auto saved=world.serialize();auto reloaded=CreatorWorld::deserialize(saved);
        require(reloaded.serialize()==saved&&reloaded.create("box",box)==2,"box state, resources, recipe, orientation and replay survive reload");
        reloaded.step(2);require(measureCreatorMotion(reloaded.objects()[1],reloaded.support()).state=="resting","reloaded box has box collision geometry");
        std::cout<<materialPresetName(material)<<" matched-sphere-speed="<<sphere_motion.speed_m_s<<" box-speed="<<box_motion.speed_m_s<<" box-gap="<<box_motion.support_gap_m<<'\n';
    }
}
void spinningBoxesAndMixedCollisions() {
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld isolated({.slope_degrees=0,.gravity_m_s2={}});isolated.collect(std::string(materialPresetName(material))+"-pile");
        auto r=boxRecipe(material);r.clearance_m=2;r.angular_velocity_rad_s={2,3,4};const auto id=isolated.create("spin",r);
        const auto before=measureRigidMechanics(isolated.mechanicalState(id));isolated.step(120);
        const auto after=measureRigidMechanics(isolated.mechanicalState(id));
        const double h_error=length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s)/length(before.angular_momentum_kg_m2_s);
        const double e_error=std::abs(after.kinetic_energy_j-before.kinetic_energy_j)/before.kinetic_energy_j;
        std::cout<<materialPresetName(material)<<" free-spin relative-H="<<h_error<<" relative-K="<<e_error<<'\n';
        require(h_error<.005&&e_error<.005,"asymmetric free-spin conserves H/K within 0.5 percent over 0.5 s at 240 Hz");
        for(bool both_boxes:{false,true}) {
            CreatorWorld world({.slope_degrees=0,.gravity_m_s2={}});world.collect(std::string(materialPresetName(material))+"-pile");
            auto a=both_boxes?boxRecipe(material):ObjectRecipe{};a.material=material;a.radius_m=.04;a.tangent_m=-.25;a.bitangent_m=.015;
            a.clearance_m=1+(both_boxes?.01:0);a.linear_velocity_m_s={.5,0,0};
            auto b=boxRecipe(material);b.tangent_m=.25;b.clearance_m=1.01;b.linear_velocity_m_s={-.5,0,0};
            (void)world.create("a",a);(void)world.create("b",b);
            auto start=measureRigidMechanics(world.mechanicalState(1));start+=measureRigidMechanics(world.mechanicalState(2));
            world.step(144);
            auto end=measureRigidMechanics(world.mechanicalState(1));end+=measureRigidMechanics(world.mechanicalState(2));
            near(length(end.linear_momentum_kg_m_s-start.linear_momentum_kg_m_s),0,2e-6*start.mass_kg,"shape collision gives finite opposite reactions");
            near(length(end.angular_momentum_kg_m2_s-start.angular_momentum_kg_m2_s),0,3e-5*start.mass_kg,"off-center shape collision retains angular momentum within integration bound");
            require(end.kinetic_energy_j<=start.kinetic_energy_j+1e-6,"shape collision does not create kinetic energy");
            require(world.objects()[0].state.linear_velocity_m_s.x<.49&&world.objects()[1].state.linear_velocity_m_s.x>-.49,"actual shape collision occurred");
            require(length(world.objects()[1].state.angular_velocity_rad_s)>.01,"off-center contact applies torque to a box");
        }
    }
}
void legacyWorldMigration() {
    CreatorWorld world;world.collect("oak-pile");(void)world.create("old",{});world.step(10);
    auto old=Json::parse(world.serialize());old["world_version"]=1;old["physics_signature"]["object_compiler"]=1;
    old["physics_signature"]["runtime"]="jolt-5.6/banjo-rigid-v1";
    auto loaded=CreatorWorld::deserialize(old.dump());require(loaded.serialize()==world.serialize(),"known v1 sphere worlds migrate without changing matter/state");
    old["objects"][0]["recipe"]=Json::parse(CreatorWorld::recipeJson(boxRecipe()));
    rejects([&]{(void)CreatorWorld::deserialize(old.dump());});
}
void persistenceAndInputBoundary() {
    CreatorWorld world;world.collect("oak-pile");ObjectRecipe r;r.name="Collected oak ball";(void)world.create("persist",r);world.step(100);
    const auto document=world.serialize();
    {
        auto loaded=CreatorWorld::deserialize(document);
        require(loaded.serialize()==document,"inventory, provenance, recipes, IDs and physical states round trip");
        require(loaded.create("persist",r)==1,"saved request identity remains idempotent");loaded.step(2);
        auto bad=Json::parse(document);bad["lots"][1]["remaining_mass_kg"]=10;rejects([&]{(void)CreatorWorld::deserialize(bad.dump());});
        bad=Json::parse(document);bad["physics_signature"]["object_compiler"]=999;rejects([&]{(void)CreatorWorld::deserialize(bad.dump());});
    }
    world.step(2);(void)world.create("second",ObjectRecipe{.tangent_m=2});require(world.objects().size()==2,"destroying another world preserves this world's runtime");
    const auto before=world.serialize();
    rejects([&]{(void)world.executeJson(R"({"type":"collect","type":"inspect","lot_id":"iron-pile"})");});
    auto response=Json::parse(world.executeJson(R"({"type":"collect","lot_id":"missing","mass_kg":1000})"));require(!response["ok"].get<bool>(),"LLM cannot add quantities to a collection command");
    response=Json::parse(world.executeJson(R"({"type":"execute_code","code":"mint inventory"})"));require(!response["ok"].get<bool>(),"arbitrary commands are not executable capabilities");
    require(world.serialize()==before,"malformed or unauthorized command shapes preserve state");
    const auto path=std::filesystem::current_path()/"creator-test-world.json";world.save(path);world.save(path);
    auto loaded=CreatorWorld::load(path);require(loaded.serialize()==world.serialize(),"atomic save can replace a prior world");std::filesystem::remove(path);
}
}
int main() {
    unsigned failures=0;
    for (const auto &[name,action]:std::vector<std::pair<const char*,std::function<void()>>>{
        {"inventory and transactional creation",inventoryAndAtomicCreation},{"glass/oak/iron creation and free fall",threeMaterialCreationAndFreeFall},
        {"three-material created-object rolling",createdObjectsRoll},{"finite created material collisions",finiteMaterialCollision},
        {"primitive geometry and oriented placement",primitiveGeometryAndPlacement},{"three-material box mass/tensor/free fall",threeMaterialBoxMassInertiaAndFall},
        {"matched-volume shape ramp and persistence",matchedShapeRampAndPersistence},{"asymmetric spin and mixed shape collisions",spinningBoxesAndMixedCollisions},
        {"known sphere world migration",legacyWorldMigration},
        {"persistence, multi-world lifetime and input boundary",persistenceAndInputBoundary}}) {
        try {action();std::cout<<"[PASS] "<<name<<'\n';}catch(const std::exception &e){++failures;std::cerr<<"[FAIL] "<<name<<": "<<e.what()<<'\n';}
    }
    return failures?1:0;
}
