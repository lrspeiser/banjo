#include "creator/CreatorWorld.hpp"
#include "physics/RollingKinematics.hpp"
#include <nlohmann/json.hpp>
#include <cmath>
#include <functional>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <chrono>

namespace {
using namespace banjo;
using Json=nlohmann::json;
void require(bool value,const char *message) {if (!value) throw std::runtime_error(message);}
void near(double a,double b,double tolerance,const char *message) {require(std::isfinite(a)&&std::abs(a-b)<=tolerance,message);}
void rejects(const std::function<void()> &action) {bool failed=false;try {action();}catch(const std::exception &){failed=true;}require(failed,"invalid command must reject");}
void assemblyAssessment(){
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        CreatorWorld world;const auto m=makeReferenceMaterial(preset);const auto name=std::string(materialPresetName(preset));
        // Small anisotropic boxes must not inherit Jolt's radius-one fallback.
        JoltWorld tiny;const Vec3 dimensions{.002,.003,.004};const double tiny_mass=m.density_kg_m3*.002*.003*.004;
        const double angle=std::numbers::pi/4;const Quat orientation{std::cos(angle/2),0,0,std::sin(angle/2)};
        tiny.addBox({1,dimensions,m,{{},orientation,{},{1,2,3}},false});const auto actual=tiny.mechanicalState(1);
        const double ix=tiny_mass*(.003*.003+.004*.004)/12,iy=tiny_mass*(.002*.002+.004*.004)/12,iz=tiny_mass*(.002*.002+.003*.003)/12;
        near(actual.inertia_world_kg_m2.m[0][0],.5*(ix+iy),ix*1e-6,"tiny rotated box diagonal inertia");
        near(actual.inertia_world_kg_m2.m[0][1],.5*(ix-iy),ix*1e-6,"tiny rotated box off-diagonal inertia");
        near(actual.inertia_world_kg_m2.m[2][2],iz,ix*1e-6,"tiny rotated box axial inertia");

        Json face={{"normal_axis",0},{"positive",true},{"u_offset_m",0},{"v_offset_m",0},{"width_m",.01},{"height_m",.012}};
        Json part={{"id","a"},{"material",name},{"dimensions_m",{.02,.02,.02}},{"center_m",{0,0,0}},{"orientation_wxyz",{1,0,0,0}}};auto second=part;second["id"]="b";second["dimensions_m"]={.03,.03,.03};second["center_m"]={.026,0,0};auto face_b=face;face_b["positive"]=false;
        Json law={{"model","central-cohesive-v1"},{"stiffness_pa_per_m",2*m.tensile_strength_pa*m.tensile_strength_pa/m.fracture_energy_j_m2},{"strength_pa",m.tensile_strength_pa},{"fracture_energy_j_m2",m.fracture_energy_j_m2},{"compression_stiffness_pa_per_m",0},{"provenance","illustrative test parameters; not calibrated"}};
        Json joint={{"id","join"},{"part_a","a"},{"part_b","b"},{"face_a",face},{"face_b",face_b},{"cells_per_axis",4},{"contact_owner","cohesive_patch_only"},{"law",law}};
        Json declaration={{"schema_version",1},{"parts",Json::array({part,second})},{"joint",joint}};
        const auto before=world.serialize();const auto response=Json::parse(world.executeJson(Json{{"type","assess_assembly"},{"assembly",declaration}}.dump()));require(response["ok"]==true,"assembly assessment command succeeds");const auto report=response["result"];
        require(report["compiled"]==true&&report["materials_sufficient"]==false&&report["creation_supported"]==false,"assembly reports missing inventory and unsupported creation independently");
        near(report["material_requirements"][0]["required_mass_kg"].get<double>(),m.density_kg_m3*.000035,1e-12,"assembly aggregates same material across parts");near(report["joint"]["area_m2"].get<double>(),.00012,1e-16,"assembly report uses geometry-derived area");require(world.serialize()==before,"assembly assessment changes no live state");
        world.collect(name+"-pile");const auto collected=world.serialize();const auto ready=Json::parse(world.assessAssemblyJson(declaration.dump()));require(ready["materials_sufficient"]==true&&ready["creation_supported"]==false,"sufficient material does not claim live assembly support");require(world.serialize()==collected,"read-only recheck does not reserve inventory");
        for(double loading:{.1,6.0}){
            const double area=.00012,work=area*m.fracture_energy_j_m2,ma=m.density_kg_m3*.000008,mb=m.density_kg_m3*.000027,mu=ma*mb/(ma+mb),speed=std::sqrt(2*loading*work/mu),duration=(loading==6?8:.5)*(2*m.fracture_energy_j_m2/m.tensile_strength_pa)/speed;
            Json spec={{"test_version",1},{"relative_kinetic_energy_j",loading*work},{"duration_s",duration},{"energy_error_budget_j",work*1e-6},{"state_error_tolerance",1e-5},{"maximum_evaluations",65536},{"minimum_separated_area_fraction",1}};
            const auto result=Json::parse(world.executeJson(Json{{"type","test_assembly"},{"assembly",declaration},{"test",spec}}.dump()));if(result["ok"]!=true)std::cerr<<name<<" loading="<<loading<<" "<<result.dump()<<std::endl;require(result["ok"]==true,"bounded assembly test executes");const auto test_report=result["result"];require(test_report["status"]==(loading==6?"passed":"failed"),"assembly test reports measured pass and fail");require(test_report["sites"].size()==16&&test_report["bodies"].size()==2,"assembly evidence bounded by compiled geometry");require(world.serialize()==collected,"assembly test leaves live state unchanged");
            if(preset==MaterialPreset::Iron&&loading==.1){auto unsupported=spec;unsupported["duration_s"]=16*duration;const auto error=Json::parse(world.executeJson(Json{{"type","test_assembly"},{"assembly",declaration},{"test",unsupported}}.dump()));require(error["ok"]==false,"unsupported closing geometry remains explicit");require(world.serialize()==collected,"unsupported geometry changes no live state");}
            spec["maximum_evaluations"]=3;const auto rejected=Json::parse(world.executeJson(Json{{"type","test_assembly"},{"assembly",declaration},{"test",spec}}.dump()));require(rejected["ok"]==false,"exhausted assembly test cannot pass");require(world.serialize()==collected,"exhausted assembly test changes no live state");
        }
        auto runtime=declaration;runtime["joint"]["contact_owner"]="tension_with_jolt_surfaces";
        const auto runtime_assessment=Json::parse(world.assessAssemblyJson(runtime.dump()));
        require(runtime_assessment["joint"]["contact_policy"]=="tension_with_jolt_surfaces"&&runtime_assessment["creation_supported"]==false,"explicit runtime policy is assessed without authorizing creation");
        auto compression=runtime;compression["joint"]["law"]["compression_stiffness_pa_per_m"]=1;
        rejects([&]{(void)world.assessAssemblyJson(compression.dump());});
        const double fracture_work=.00012*m.fracture_energy_j_m2,ma=m.density_kg_m3*.000008,mb=m.density_kg_m3*.000027;
        const double speed=std::sqrt(12*fracture_work/(ma*mb/(ma+mb)));
        Json runtime_spec={{"test_version",2},{"relative_kinetic_energy_j",6*fracture_work},{"duration_s",8*(2*m.fracture_energy_j_m2/m.tensile_strength_pa)/speed},
            {"steps",1024},{"energy_error_budget_j",fracture_work*1e-4},{"transfer_roundoff_budget_j",fracture_work*1e-6},{"minimum_separated_area_fraction",1}};
        const auto run=[&](const Json &d,const Json &spec){return Json::parse(world.executeJson(Json{{"type","test_assembly"},{"assembly",d},{"test",spec}}.dump()));};
        const auto result=run(runtime,runtime_spec);
        if(JoltWorld::positionPrecisionBits()==64) {
            if(result["ok"]!=true)std::cerr<<result.dump()<<'\n';
            require(result["ok"]==true,"runtime assembly test executes through public API");const auto &r=result["result"];
            std::cout<<name<<" runtime assembly "<<r["status"]<<" max_E="<<r["maximum_integration_energy_error_j"]<<" D="<<r["damage_work_j"]<<'\n';
            require(r["status"]=="passed"&&r["sites"].size()==16&&r["bodies"].size()==2,"runtime geometry-derived patch separates within energy budget");
            near(r["damage_work_j"].get<double>(),fracture_work,fracture_work*1e-12,"runtime patch retains complete Gc area work");
            auto coarse_spec=runtime_spec;coarse_spec["steps"]=512;const auto coarse=run(runtime,coarse_spec);
            require(coarse["ok"]==true&&coarse["result"]["maximum_integration_energy_error_j"].get<double>()>r["maximum_integration_energy_error_j"].get<double>(),"runtime energy error improves with timestep refinement");
            std::cout<<name<<" coarse runtime max_E="<<coarse["result"]["maximum_integration_energy_error_j"]<<'\n';
            auto reordered=runtime;std::swap(reordered["parts"][0],reordered["parts"][1]);const auto reordered_result=run(reordered,runtime_spec);
            require(reordered_result["ok"]==true&&reordered_result["result"]["bodies"]==r["bodies"],"part array order preserves referenced runtime body assignment");
            auto tight=runtime_spec;tight["energy_error_budget_j"]=fracture_work*1e-12;tight["transfer_roundoff_budget_j"]=0;
            const auto failed=run(runtime,tight);require(failed["ok"]==false||failed["result"]["status"]=="failed","insufficient transfer/integration budget cannot pass");
        } else require(result["ok"]==false,"legacy precision rejects runtime assembly fixture");
        auto spinning=runtime;auto &spin_law=spinning["joint"]["law"];
        spin_law["strength_pa"]=2*m.fracture_energy_j_m2/.02;spin_law["stiffness_pa_per_m"]=(2*m.fracture_energy_j_m2/.02)/.005;
        for(auto face_name:{"face_a","face_b"})spinning["joint"][face_name]["u_offset_m"]=.003;
        auto spin_spec=runtime_spec;spin_spec["relative_kinetic_energy_j"]=.1*fracture_work;spin_spec["duration_s"]=.1;spin_spec["minimum_separated_area_fraction"]=0;
        spin_spec["energy_error_budget_j"]=.0009*fracture_work;spin_spec["initial_angular_velocity_rad_s"]={{"a",{0,0,3}},{"b",{0,0,-2}}};
        if(JoltWorld::positionPrecisionBits()==64) {
            const double expected_spin=.5*(ma*.02*.02/6*9+mb*.03*.03/6*4);
            for(unsigned steps:{512u,1024u,2048u}) {
                spin_spec["steps"]=steps;const auto spinning_result=run(spinning,spin_spec);
                require(spinning_result["ok"]==true,"bounded off-center spin trial returns measured result");const auto &r=spinning_result["result"];
                near(r["initial_rotational_kinetic_energy_j"].get<double>(),expected_spin,expected_spin*1e-6,"declared spin contributes analytical solid-box rotational energy");
                near(r["energy_residual_j"].get<double>()-r["jolt_stage_energy_change_j"].get<double>()-r["signed_transfer_roundoff_j"].get<double>(),
                    r["cohesive_opening_work_j"].get<double>()+r["impulse_work_j"].get<double>(),1e-12+fracture_work*1e-9,"full trajectory work ledger closes independently of pass status");
                require(r["largest_error_steps"].size()==8,"diagnostic output retains only eight worst steps");
                for(const auto &entry:r["largest_error_steps"]){
                    near(entry["step_integration_error_j"].get<double>(),entry["cohesive_opening_work_j"].get<double>()+entry["impulse_work_j"].get<double>(),1e-12+fracture_work*1e-9,"step work discrepancy is explicitly accounted");
                    require(entry["tick"].get<unsigned>()>=1&&entry["tick"].get<unsigned>()<=steps,"diagnostic tick belongs to the tested interval");}

                require(std::abs(r["bodies"][0]["angular_velocity_rad_s"][2].get<double>()-3)>1e-4,"evolving spin is not continually imposed");
                if(preset==MaterialPreset::Iron)require(r["status"]=="failed","off-center iron integration failure remains visible");
                std::cout<<name<<" spin steps="<<steps<<" status="<<r["status"]<<" max_E="<<r["maximum_integration_energy_error_j"]<<" max_H="<<r["maximum_angular_momentum_change_kg_m2_s"]<<'\n';
            }
            for(unsigned variant=0;variant<3;++variant){auto bad=spin_spec;
                if(variant==0)bad["initial_angular_velocity_rad_s"]["a"]={0,0,11};
                if(variant==1)bad["initial_angular_velocity_rad_s"].erase("b");
                if(variant==2){bad["initial_angular_velocity_rad_s"].erase("b");bad["initial_angular_velocity_rad_s"]["unknown"]={0,0,0};}
                require(run(spinning,bad)["ok"]==false,"invalid spin bounds or part references reject");}
        }
        require(world.serialize()==collected,"rotational trials and failures leave live world unchanged");
        auto excessive=runtime_spec;excessive["steps"]=4097;require(run(runtime,excessive)["ok"]==false,"runtime test step budget is bounded");
        require(run(declaration,runtime_spec)["ok"]==false,"old contact policy cannot silently select Jolt fixture");
        require(world.serialize()==collected,"all temporary runtime tests preserve live inventory and state");
        auto old_runtime=Json::parse(world.serialize());old_runtime["physics_signature"]["runtime"]="jolt-5.6/banjo-rigid-primitives-v2";
        rejects([&]{(void)CreatorWorld::deserialize(old_runtime.dump());});
        CreatorWorld runtime_draft;(void)runtime_draft.rememberAssembly(runtime.dump(),0);
        require(CreatorWorld::deserialize(runtime_draft.serialize()).serialize()==runtime_draft.serialize(),"explicit contact policy survives draft persistence");
        for(unsigned invalid=0;invalid<4;++invalid){auto bad=declaration;if(invalid==0)bad["joint"]["contact_owner"]="cohesive_and_jolt";if(invalid==1)bad["joint"]["part_b"]="a";if(invalid==2)bad["parts"][0]["density_kg_m3"]=1;if(invalid==3)bad["joint"]["face_a"]["width_m"]=.04;const auto error=Json::parse(world.executeJson(Json{{"type","assess_assembly"},{"assembly",bad}}.dump()));require(error["ok"]==false,"invalid assembly rejects through public command");require(world.serialize()==collected,"invalid assembly leaves live state untouched");}
        CreatorWorld drafts;const auto original=Json::parse(drafts.serialize());
        const auto remembered=Json::parse(drafts.executeJson(Json{{"type","remember_assembly"},{"assembly",declaration},{"expected_revision",0}}.dump()));require(remembered["ok"]==true&&remembered["result"]["revision"]==1,"assembly draft command records first revision");
        const auto saved=drafts.serialize();auto loaded=CreatorWorld::deserialize(saved);require(loaded.serialize()==saved,"assembly declaration round trips exactly");
        const auto stored=Json::parse(saved);require(stored["lots"]==original["lots"]&&stored["objects"]==original["objects"]&&stored["ticks"]==original["ticks"],"remembering draft changes no physical resources or clock");
        require(loaded.rememberAssembly(declaration.dump(),0)==1&&loaded.serialize()==saved,"identical draft retry is idempotent");
        auto changed=declaration;changed["joint"]["id"]="revised-joint";rejects([&]{(void)loaded.rememberAssembly(changed.dump(),0);});require(loaded.serialize()==saved,"stale draft edit preserves state");
        loaded.collect(name+"-pile");const auto reassessed=Json::parse(loaded.executeJson(R"({"type":"assess_saved_assembly"})"));require(reassessed["result"]["materials_sufficient"]==true&&reassessed["result"]["declaration"]==declaration,"restored exact draft reassesses current stock");
        ObjectRecipe item;item.material=preset;item.radius_m=.03;(void)loaded.create("draft-preservation",item);require(Json::parse(loaded.serialize())["assembly_draft"]["declaration"]==declaration,"normal object publication preserves saved draft");
        auto legacy=Json::parse(loaded.serialize());legacy["world_version"]=3;legacy.erase("assembly_draft");legacy["physics_signature"].erase("position_bits");if(JoltWorld::positionPrecisionBits()==32){const auto migrated=Json::parse(CreatorWorld::deserialize(legacy.dump()).serialize());require(migrated["world_version"]==5&&migrated["assembly_draft"]["declaration"].is_null()&&migrated["lots"]==legacy["lots"],"known v3 migrates without inventing a draft");}else rejects([&]{(void)CreatorWorld::deserialize(legacy.dump());});
        auto bad=Json::parse(saved);bad["assembly_draft"]["declaration"]["joint"]["face_a"]["width_m"]=1;rejects([&]{(void)CreatorWorld::deserialize(bad.dump());});
        require(loaded.rememberAssembly(changed.dump(),1)==2,"current draft revision can be replaced");rejects([&]{(void)loaded.clearAssembly(1);});require(loaded.clearAssembly(2)==3,"explicit clear advances draft revision");require(Json::parse(loaded.serialize())["assembly_draft"]["declaration"].is_null(),"cleared draft is absent");
    }
}
void boundedFunctionalTests() {
    CreatorWorld live;const auto before=live.serialize();
    Json specification{{"test_version",1},{"fixture","concrete-incline-v1"},{"ticks",480},{"slope_degrees",10},{"minimum_travel_m",.3},{"maximum_final_slip_m_s",.02},{"require_rolling",true}};
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        ObjectRecipe sphere;sphere.schema_version=2;sphere.material=material;sphere.radius_m=.04;
        const Json command{{"type","test_recipe"},{"recipe",Json::parse(CreatorWorld::recipeJson(sphere))},{"test",specification}};
        const auto result=Json::parse(live.executeJson(command.dump()));require(result.at("ok").get<bool>(),"functional API accepts bounded test");
        const auto report=result.at("result");require(report["status"]=="passed","all three created spheres pass measured rolling criteria");
        near(report["mass_kg"].get<double>(),4.0/3*std::numbers::pi*.04*.04*.04*makeReferenceMaterial(material).density_kg_m3,1e-12,"test uses matter-derived sphere mass");
        require(report["samples"].size()==21&&report["samples"].back()["tick"]==480,"bounded trace includes exact final tick");
        require(live.serialize()==before,"test cannot collect create spend or advance live state");
        auto impossible=specification;impossible["minimum_travel_m"]=10;
        require(Json::parse(CreatorWorld::testRecipeJson(sphere,impossible.dump()))["status"]=="failed","valid geometry can fail its requested function");
        ObjectRecipe box=sphere;box.shape="box";const double side=std::cbrt(sphere.geometry().volume());box.dimensions_m={side,side,side};
        box.orientation_world={std::cos(-std::numbers::pi/36),0,0,std::sin(-std::numbers::pi/36)};
        require(Json::parse(CreatorWorld::testRecipeJson(box,specification.dump()))["status"]=="unsupported","box cannot silently inherit a sphere rolling test");
        auto travel_test=specification;travel_test["require_rolling"]=false;
        const auto box_report=Json::parse(CreatorWorld::testRecipeJson(box,travel_test.dump()));
        require(box_report["status"]=="failed"&&box_report["predicates"]["minimum_travel"]==false,"equal-volume flat box fails travel on the same incline");
        near(box_report["mass_kg"].get<double>(),report["mass_kg"].get<double>(),1e-12,"matched shape tests preserve mass and substance");
        std::cout<<materialPresetName(material)<<" test travel="<<report["final_travel_m"]<<" slip="<<report["final_slip_m_s"]<<" box travel="<<box_report["final_travel_m"]<<'\n';
    }
    auto invalid=specification;invalid["ticks"]=1201;rejects([&]{(void)CreatorWorld::testRecipeJson(ObjectRecipe{},invalid.dump());});
    invalid=specification;invalid["fixture"]="fracture-v1";rejects([&]{(void)CreatorWorld::testRecipeJson(ObjectRecipe{},invalid.dump());});
    invalid=specification;invalid["extra"]=true;rejects([&]{(void)CreatorWorld::testRecipeJson(ObjectRecipe{},invalid.dump());});
    require(live.serialize()==before,"failed and unsupported trials preserve live state");
}
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
        const auto motion=measureCreatorMotion(world.objects()[0],world.support());
        require(motion.near_support_points==0&&motion.state=="no top-support sample","absence of top-contact samples is not a claim about all contacts");
        require(Json::parse(world.inspectJson())["objects"][0]["contact_slip_m_s"].is_null(),"unmeasured contact slip is unavailable rather than zero");
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
void precisionIdentity() {
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld world;world.collect(std::string(materialPresetName(material))+"-pile");
        ObjectRecipe recipe;recipe.material=material;(void)world.create("precision",recipe);
        const auto saved=world.serialize();const auto current=Json::parse(saved);
        require(current["world_version"]==5&&current["physics_signature"]==Json::parse(CreatorWorld::physicsSignatureJson()),"v5 stores actual shared physics identity");
        require(current["physics_signature"]["position_bits"]==JoltWorld::positionPrecisionBits(),"signature reflects compiled Jolt precision");
        require(CreatorWorld::deserialize(saved).serialize()==saved,"matching precision round trips state and allocations");
        auto wrong=current;wrong["physics_signature"]["position_bits"]=JoltWorld::positionPrecisionBits()==32?64:32;
        rejects([&]{(void)CreatorWorld::deserialize(wrong.dump());});
        wrong=current;wrong["physics_signature"].erase("position_bits");rejects([&]{(void)CreatorWorld::deserialize(wrong.dump());});
        wrong=current;wrong["physics_signature"]["unrecognized_precision_option"]=true;rejects([&]{(void)CreatorWorld::deserialize(wrong.dump());});
        auto legacy=current;legacy["world_version"]=4;legacy["physics_signature"].erase("position_bits");
        if(JoltWorld::positionPrecisionBits()==32)require(CreatorWorld::deserialize(legacy.dump()).serialize()==saved,"v4 upgrades metadata without changing objects, inventory or history");
        else rejects([&]{(void)CreatorWorld::deserialize(legacy.dump());});
        require(world.serialize()==saved,"rejected saved precision does not mutate live world");
    }
}
void legacyWorldMigration() {
    CreatorWorld world;world.collect("oak-pile");(void)world.create("old",{});world.step(10);
    auto old=Json::parse(world.serialize());old["world_version"]=1;old["physics_signature"].erase("position_bits");old.erase("assembly_draft");old["physics_signature"]["object_compiler"]=1;
    old["physics_signature"]["runtime"]="jolt-5.6/banjo-rigid-v1";
    old.erase("history");old.erase("next_object_id");old.erase("authoring_policy");for(auto &o:old["objects"])o.erase("revision");
    if(JoltWorld::positionPrecisionBits()!=32){rejects([&]{(void)CreatorWorld::deserialize(old.dump());});return;}
    auto loaded=CreatorWorld::deserialize(old.dump());const auto migrated=Json::parse(loaded.serialize());
    require(migrated["lots"]==old["lots"]&&migrated["ticks"]==old["ticks"]&&migrated["objects"][0]["state"]==old["objects"][0]["state"],"known v1 migration retains quantities, time and motion");
    require(loaded.history().size()==1&&loaded.history()[0].operation=="import"&&loaded.create("old",{})==1,"migration marks imported history and preserves request replay");
    require(CreatorWorld::deserialize(loaded.serialize()).serialize()==loaded.serialize(),"migrated history persists");
    old["objects"][0]["recipe"]=Json::parse(CreatorWorld::recipeJson(boxRecipe()));
    rejects([&]{(void)CreatorWorld::deserialize(old.dump());});
}
double allocationMass(const std::vector<MaterialAllocation> &parts) {double mass=0;for(const auto &a:parts)mass+=a.mass_kg;return mass;}
void threeMaterialRebuildAndReclaim() {
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld world;world.collect(std::string(materialPresetName(material))+"-pile");
        ObjectRecipe original;original.material=material;original.radius_m=std::cbrt(9.9/(makeReferenceMaterial(material).density_kg_m3*4*std::numbers::pi/3));
        const auto id=world.create("original",original);world.step(120);
        const auto moving=measureRigidMechanics(world.mechanicalState(id));require(moving.kinetic_energy_j>.01,"rebuild starts from measured moving matter");
        const auto box=boxRecipe(material);const auto untouched=world.serialize();const auto plan=world.previewRebuild({id,1},box);
        require(world.serialize()==untouched,"rebuild preview neither releases old matter nor changes physical state");
        require(plan.creation.mass_kg>world.inventoryMass(material),"rebuild needs selected object matter beyond free inventory");
        near(allocationMass(plan.reused),plan.creation.mass_kg,1e-12,"selected matter is reused first");
        near(allocationMass(plan.withdrawn),0,0,"shrinking into the block needs no extra stock");
        near(allocationMass(plan.returned),9.9-plan.creation.mass_kg,1e-12,"unused original matter is returned to its lot");
        rejects([&]{(void)world.rebuild("stale",{id,0},box);});
        auto huge=box;huge.dimensions_m={1,1,1};rejects([&]{(void)world.rebuild("unaffordable",{id,1},huge);});
        require(world.serialize()==untouched,"failed rebuild preserves the old body, stock, clock and history");
        const double time=world.timeSeconds();require(world.rebuild("reshape",{id,1},box)==id,"replacement keeps object identity");
        require(world.objects().size()==1&&world.objects()[0].revision==2&&world.history().size()==2,"rebuild increments object revision and retains history");
        near(world.timeSeconds(),time,0,"authoring does not advance the physical clock");
        near(world.inventoryMass(material)+world.objects()[0].mass_kg,10,1e-12,"rebuild closes the material ledger");
        const auto &change=world.history().back();
        near(change.before_mechanics.kinetic_energy_j,moving.kinetic_energy_j,1e-12,"removed kinetic energy is recorded at the authoring boundary");
        near(change.after_mechanics.kinetic_energy_j,0,0,"accepted at-rest replacement has zero kinetic energy");
        require(length(change.before_mechanics.linear_momentum_kg_m_s)>.01&&length(change.after_mechanics.linear_momentum_kg_m_s)==0,"momentum discontinuity is explicit, not called conserved simulation");
        world.step(10);const auto rebuilt=world.serialize();
        require(world.create("original",original)==id&&world.rebuild("reshape",{id,1},box)==id&&world.serialize()==rebuilt,"past operation replays do not overwrite later state");
        rejects([&]{world.reclaim("bad-revision",{id,1});});require(world.serialize()==rebuilt,"stale reclamation does not release material");
        world.reclaim("return",{id,2});near(world.inventoryMass(material),10,1e-12,"full intact recovery restores the original lot quantity");
        require(world.objects().empty()&&world.history().size()==3,"reclaimed object is archived, not active");
        const auto reclaimed=world.serialize();world.reclaim("return",{id,2});(void)world.create("original",original);(void)world.rebuild("reshape",{id,1},box);
        require(world.serialize()==reclaimed,"old receipts cannot resurrect a reclaimed object or debit/refund twice");
        const auto fresh=world.create("fresh",box);require(fresh>id&&world.objects()[0].id==fresh,"new objects do not reuse reclaimed IDs");
        auto loaded=CreatorWorld::deserialize(world.serialize());require(loaded.serialize()==world.serialize(),"complete rebuild/reclaim history round trips");
        const auto loaded_before=loaded.serialize();loaded.reclaim("return",{id,2});require(loaded.serialize()==loaded_before,"saved tombstone receipts remain idempotent");
        std::cout<<materialPresetName(material)<<" recovered-block-mass="<<plan.creation.mass_kg<<" reused="<<allocationMass(plan.reused)<<" returned="<<allocationMass(plan.returned)<<" authoring-K-before="<<moving.kinetic_energy_j<<'\n';
    }
}
void materialSwapAndHistoryValidation() {
    CreatorWorld world;world.collect("glass-pile");world.collect("oak-pile");
    ObjectRecipe a;a.material=MaterialPreset::Glass;a.radius_m=.04;const auto id=world.create("glass-source",a);
    ObjectRecipe peer;peer.radius_m=.04;peer.tangent_m=2;(void)world.create("peer",peer);world.step(30);
    const auto before=world.serialize();const auto peer_before=Json::parse(before)["objects"][1];
    const auto iron=boxRecipe(MaterialPreset::Iron);rejects([&]{(void)world.rebuild("uncollected-metal",{id,1},iron);});
    require(world.serialize()==before,"material swap cannot spend an uncollected lot or prematurely return the source");
    const auto oak=boxRecipe();const auto plan=world.previewRebuild({id,1},oak);
    near(allocationMass(plan.reused),0,0,"different substances are not transmuted into each other");
    near(allocationMass(plan.returned),world.objects()[0].mass_kg,1e-12,"old substance is returned with its lot provenance");
    near(allocationMass(plan.withdrawn),plan.creation.mass_kg,1e-12,"new substance comes from its own collected stock");
    (void)world.rebuild("swap",{id,1},oak);const auto saved=world.serialize();const auto current=Json::parse(saved);
    require(current["objects"][1]==peer_before,"unrelated object identity, definition and physical state remain unchanged");
    near(world.inventoryMass(MaterialPreset::Glass),10,1e-12,"all glass returns to glass stock");
    near(world.inventoryMass(MaterialPreset::Oak)+world.objects()[0].mass_kg+world.objects()[1].mass_kg,10,1e-12,"oak ledger includes both active objects");
    for(unsigned mode=0;mode<7;++mode) {
        auto bad=current;
        if(mode==0)bad["history"][2]["expected_revision"]=9;
        if(mode==1)bad["history"][2]["request_id"]="peer";
        if(mode==2)bad["history"][2]["mechanics_before"]["kinetic_energy_j"]=100;
        if(mode==3)bad["history"].erase(bad["history"].begin());
        if(mode==4)bad["next_object_id"]=1;
        if(mode==5)bad["authoring_policy"]="mint-extra-material";
        if(mode==6)bad["objects"][0]["revision"]=1;
        rejects([&]{(void)CreatorWorld::deserialize(bad.dump());});
    }
    rejects([&]{world.reclaim("peer",{id,2});});require(world.serialize()==saved,"cross-operation request collisions preserve state");
    auto legacy=current;legacy["world_version"]=2;legacy["physics_signature"].erase("position_bits");legacy.erase("assembly_draft");legacy.erase("history");legacy.erase("next_object_id");legacy.erase("authoring_policy");
    for(auto &o:legacy["objects"])o.erase("revision");
    if(JoltWorld::positionPrecisionBits()!=32){rejects([&]{(void)CreatorWorld::deserialize(legacy.dump());});return;}
    auto imported=CreatorWorld::deserialize(legacy.dump());require(imported.history().size()==2&&imported.history()[1].operation=="import","known box worlds migrate as explicit baseline imports");
    require(imported.objects()[0].recipe.shape=="box"&&Json::parse(imported.serialize())["lots"]==legacy["lots"],"box migration preserves allocated matter and geometry");
}
void boundedAuthoringHistory() {
    CreatorWorld world;world.collect("oak-pile");ObjectRecipe r;r.radius_m=.025;
    const auto start=std::chrono::steady_clock::now();
    for(unsigned i=0;i<128;++i) {
        const auto id=world.create("create-"+std::to_string(i),r);world.reclaim("reclaim-"+std::to_string(i),{id,1});
    }
    require(world.history().size()==256&&world.objects().empty(),"bounded history retains all accepted operations");
    const auto before=world.serialize();rejects([&]{(void)world.create("overflow",r);});
    const auto assessment=Json::parse(world.assessJson(r));
    require(assessment["status"]=="blocked"&&!assessment["buildable_after_collection"].get<bool>()&&assessment["issues"][0]["code"]=="history_limit","more resources cannot solve exhausted authoring history");
    require(world.serialize()==before&&world.create("create-0",r)==1,"budget rejection and old receipt replay preserve the world");
    auto loaded=CreatorWorld::deserialize(before);require(loaded.serialize()==before,"full history budget remains loadable");
    std::cout<<"256 authoring operations seconds="<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<" saved-bytes="<<before.size()<<'\n';
}
void inventoryRequirements() {
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld world;auto r=boxRecipe(material);r.tangent_m=2;
        const double required=.08*.06*.1*makeReferenceMaterial(material).density_kg_m3;
        const auto initial=world.serialize();const auto uncollected=world.assess(r);
        require(!uncollected.buildable()&&uncollected.issues.size()==1&&uncollected.issues[0].code=="insufficient_material","uncollected lots are not spendable inventory");
        near(uncollected.material.required_mass_kg,required,1e-12,"requirements use occupied volume and catalog density");
        near(uncollected.material.inventory_mass_kg,0,0,"empty inventory stays empty");
        near(uncollected.material.collectible_mass_kg,10,0,"available world material is reported separately");
        near(uncollected.material.missing_mass_kg,required,1e-12,"all required mass must first be collected");
        near(uncollected.material.missing_after_collection_kg,0,0,"existing lot can satisfy this design after collection");
        require(uncollected.creation.allocations.empty(),"a short design does not reserve material");
        auto report=Json::parse(world.executeJson(Json{{"type","assess"},{"recipe",Json::parse(CreatorWorld::recipeJson(r))}}.dump()));
        require(report["ok"]==true&&report["result"]["status"]=="needs_resources"&&report["result"]["buildable_after_collection"]==true,"API returns actionable requirements as a successful query");
        require(report["result"]["fabrication_energy_j"].is_null(),"unsupported energy is not a zero-cost claim");
        require(world.serialize()==initial,"assessment cannot collect, debit, create, step or write history");
        require(world.collect(std::string(materialPresetName(material))+"-pile"),"collection transfers the lot into inventory");
        require(!world.collect(std::string(materialPresetName(material))+"-pile"),"repeated collection does not duplicate a resource");
        const auto collected=world.serialize();const auto available=world.assess(r);
        require(available.buildable()&&world.serialize()==collected,"collection makes the unchanged design buildable without building it");
        near(available.material.inventory_mass_kg,10,0,"collected lot enters inventory once");
        near(available.material.collectible_mass_kg,0,0,"collected lot is no longer available for pickup");
        auto huge=r;huge.dimensions_m={1,1,1};const auto shortage=world.assess(huge);
        near(shortage.material.missing_mass_kg,makeReferenceMaterial(material).density_kg_m3-10,1e-12,"larger designs report a real remaining shortfall");
        require(!shortage.buildable()&&Json::parse(world.assessJson(huge))["buildable_after_collection"]==false,"collecting existing lots cannot cover nonexistent material");
        ObjectRecipe original;original.material=material;original.radius_m=std::cbrt(9.9/(makeReferenceMaterial(material).density_kg_m3*4*std::numbers::pi/3));
        const auto id=world.create("original",original);world.step(120);const auto moving=world.serialize();
        const auto additional=world.assess(r),replacement=world.assess(r,RevisionTarget{id,1});
        near(additional.material.missing_mass_kg,required-.1,1e-12,"new object cannot use existing object matter");
        near(additional.material.recoverable_mass_kg,0,0,"new designs have no implicit recovery");
        require(replacement.buildable(),"explicit revision can reuse its own original matter");
        near(replacement.material.recoverable_mass_kg,9.9,1e-12,"selected object's recoverable mass is counted once");
        near(replacement.material.inventory_mass_kg,.1,1e-12,"selected recovery is distinct from free inventory");
        const auto other=material==MaterialPreset::Glass?MaterialPreset::Oak:MaterialPreset::Glass;
        auto swapped=r;swapped.material=other;const auto swap=world.assess(swapped,RevisionTarget{id,1});
        require(!swap.buildable()&&swap.material.inventory_mass_kg==0&&swap.material.recoverable_mass_kg==0,"recovering another substance cannot fund a material swap");
        near(swap.material.missing_mass_kg,swap.material.required_mass_kg,0,"missing replacement material cannot transmute from selected matter");
        auto overlap=original;const auto &position=world.objects()[0].state.center_of_mass_world_m;
        overlap.tangent_m=dot(position,world.support().tangent_world);overlap.bitangent_m=dot(position,world.support().bitangent_world);
        const auto blocked=Json::parse(world.assessJson(overlap));
        require(blocked["status"]=="blocked"&&blocked["issues"].size()==2&&blocked["issues"][0]["code"]=="placement_overlap","placement and shortage remain distinct blockers");
        rejects([&]{(void)world.create("too-short",r);});
        rejects([&]{(void)world.assess(r,RevisionTarget{id,0});});
        auto unsupported=r;unsupported.physics="hinged-door";rejects([&]{(void)world.assess(unsupported);});
        require(world.serialize()==moving,"requirements and all rejected operations preserve a moving source object");
        report=Json::parse(world.executeJson(Json{{"type","assess_rebuild"},{"object_id",id},{"expected_revision",1},{"recipe",Json::parse(CreatorWorld::recipeJson(r))}}.dump()));
        require(report["ok"]==true&&report["result"]["buildable_with_inventory"]==true&&world.serialize()==moving,"revision assessment shares the read-only API");
        std::cout<<materialPresetName(material)<<" required="<<required<<" free="<<additional.material.inventory_mass_kg<<" missing="<<additional.material.missing_mass_kg<<" recoverable="<<replacement.material.recoverable_mass_kg<<'\n';
    }
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
        {"bounded isolated functional test API",boundedFunctionalTests},
        {"read-only assembly assessment API",assemblyAssessment},
        {"inventory and transactional creation",inventoryAndAtomicCreation},{"glass/oak/iron creation and free fall",threeMaterialCreationAndFreeFall},
        {"three-material created-object rolling",createdObjectsRoll},{"finite created material collisions",finiteMaterialCollision},
        {"primitive geometry and oriented placement",primitiveGeometryAndPlacement},{"three-material box mass/tensor/free fall",threeMaterialBoxMassInertiaAndFall},
        {"matched-volume shape ramp and persistence",matchedShapeRampAndPersistence},{"asymmetric spin and mixed shape collisions",spinningBoxesAndMixedCollisions},
        {"saved runtime precision",precisionIdentity},
        {"known sphere world migration",legacyWorldMigration},
        {"three-material rebuild/reclaim lifecycle",threeMaterialRebuildAndReclaim},{"material swap, unrelated state and history validation",materialSwapAndHistoryValidation},
        {"bounded authoring history",boundedAuthoringHistory},{"glass/oak/iron inventory requirements",inventoryRequirements},
        {"persistence, multi-world lifetime and input boundary",persistenceAndInputBoundary}}) {
        try {action();std::cout<<"[PASS] "<<name<<'\n';}catch(const std::exception &e){++failures;std::cerr<<"[FAIL] "<<name<<": "<<e.what()<<'\n';}
    }
    return failures?1:0;
}
