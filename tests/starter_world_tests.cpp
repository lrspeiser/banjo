#include "creator/StarterWorld.hpp"
#include <nlohmann/json.hpp>
#include <cmath>
#include <iostream>
#include <functional>
#include <fstream>
#include <chrono>
using namespace banjo;
void check(bool ok,const char *s) {if(!ok)throw std::runtime_error(s);}
void near(double a,double b,double tolerance,const char *s) {check(std::isfinite(a)&&std::abs(a-b)<=tolerance,s);}
void rejects(std::function<void()> f){bool bad=false;try{f();}catch(const std::exception&){bad=true;}check(bad,"expected rejection");}
Vec3 eye(const StarterWorld &w,unsigned i) {auto p=w.objects().at(i-1).state.center_of_mass_world_m;p.y+=1;return p;}
void assemblyInventory() {
    using Json=nlohmann::json;
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        StarterWorld world;const auto m=makeReferenceMaterial(material);const auto name=std::string(materialPresetName(material));
        Json a={{"id","a"},{"material",name},{"dimensions_m",{.02,.02,.02}},{"center_m",{0,0,0}},{"orientation_wxyz",{1,0,0,0}}};auto b=a;b["id"]="b";b["dimensions_m"]={.03,.03,.03};b["center_m"]={.026,0,0};
        Json fa={{"normal_axis",0},{"positive",true},{"u_offset_m",0},{"v_offset_m",0},{"width_m",.01},{"height_m",.012}};auto fb=fa;fb["positive"]=false;
        Json law={{"model","central-cohesive-v1"},{"stiffness_pa_per_m",2*m.tensile_strength_pa*m.tensile_strength_pa/m.fracture_energy_j_m2},{"strength_pa",m.tensile_strength_pa},{"fracture_energy_j_m2",m.fracture_energy_j_m2},{"compression_stiffness_pa_per_m",0},{"provenance","illustrative regression law"}};
        Json declaration={{"schema_version",1},{"parts",Json::array({a,b})},{"joint",{{"id","join"},{"part_a","a"},{"part_b","b"},{"face_a",fa},{"face_b",fb},{"cells_per_axis",4},{"contact_owner","cohesive_patch_only"},{"law",law}}}};
        const auto initial=world.serialize();const auto report=Json::parse(world.assessAssemblyJson(declaration.dump()));
        check(world.serialize()==initial,"starter assembly assessment is read-only");check(report["inventory_scope"]=="first-person-starter"&&!report["materials_sufficient"].get<bool>()&&!report["creation_supported"].get<bool>(),"starter stock and unsupported creation are distinct");
        check(report["player"]["assembly_level_requirement"].is_null()&&report["player"]["assembly_stamina_cost"].is_null(),"unsupported construction costs are not fabricated");
        const auto bill=report["material_requirements"][0];near(bill["required_mass_kg"],.000035*m.density_kg_m3,1e-12,"shared compiler derives required material");near(bill["inventory_mass_kg"],0,0,"fresh starter has no held material");
        double loose=0;unsigned pickup=0;for(const auto &o:world.objects())if(o.recipe.material==material&&!o.attached&&!o.tool&&!o.collected){loose+=o.recipe.geometry().volume()*m.density_kg_m3;if(!pickup)pickup=static_cast<unsigned>(o.id);}
        near(bill["collectible_mass_kg"],6*(material==MaterialPreset::Oak?.2*.08*.08:.08*.08*.08)*m.density_kg_m3,1e-12,"six declared pickups exclude the attached branch");check(loose!=10,"starter must not inherit the workshop ten-kilogram pile");
        (void)world.interact("assembly-pickup",pickup,eye(world,pickup));const auto collected=world.serialize();auto ready=Json::parse(world.assessAssemblyJson(declaration.dump()));
        check(world.serialize()==collected,"readiness does not spend XP, stamina, stock or time");check(ready["materials_sufficient"].get<bool>()&&!ready["creation_supported"].get<bool>(),"pickup supplies material but cannot enable unsupported creation");
        const auto after=ready["material_requirements"][0];near(after["inventory_mass_kg"],world.inventoryKg(material),1e-12,"assembly uses real collected inventory");near(after["collectible_mass_kg"].get<double>()+after["inventory_mass_kg"].get<double>(),loose,1e-12,"pickup transfers mass without duplicating supply");
        auto restored=StarterWorld::deserialize(collected);check(restored.assessAssemblyJson(declaration.dump())==ready.dump(2),"restored starter reports identical assembly requirements");
        if(material==MaterialPreset::Oak) {
            (void)world.craft("assembly-tool","prybar",{0,1.65,0});const auto tools=Json::parse(world.assessAssemblyJson(declaration.dump()));
            near(tools["material_requirements"][0]["collectible_mass_kg"],after["collectible_mass_kg"],1e-12,"equipped tool is not counted as collectible material");
            near(tools["material_requirements"][0]["inventory_mass_kg"],world.inventoryKg(material),1e-12,"tool fabrication debit reaches assembly bill");
        }
        rejects([&]{(void)CreatorWorld::assessAssemblyWithStockJson(declaration.dump(),{{material,1,0},{material,2,0}});});
        rejects([&]{(void)CreatorWorld::assessAssemblyWithStockJson(declaration.dump(),{{material,-1,0}});});
        auto mixed=declaration;mixed["parts"][1]["material"]=material==MaterialPreset::Iron?"glass":"iron";
        const auto mixed_report=Json::parse(world.assessAssemblyJson(mixed.dump()));check(mixed_report["material_requirements"].size()==2,"mixed assembly keeps separate material bills");
        check(!mixed_report["materials_sufficient"].get<bool>(),"stock of one material cannot pay for another");
        const auto empty=Json::parse(CreatorWorld::assessAssemblyWithStockJson(declaration.dump(),{}));near(empty["material_requirements"][0]["collectible_mass_kg"],0,0,"missing stock entries never mint material");
        std::cout<<name<<" assembly required="<<bill["required_mass_kg"]<<" loose="<<loose<<" collected="<<after["inventory_mass_kg"]<<'\n';
    }
}
int main() {try {
    assemblyInventory();
    StarterWorld w;const auto initial=w.serialize();
    check(w.level()==1&&w.stamina()==100&&!w.quote("prybar").ready(),"fresh game starts with empty inventory and locked costs");
    rejects([&]{(void)w.interact("far",1,{10,2,10});});check(w.serialize()==initial,"out-of-reach action is atomic");
    (void)w.interact("wood",1,eye(w,1));near(w.inventoryKg(MaterialPreset::Oak),.2*.08*.08*700,1e-12,"picked volume becomes exact raw oak mass");
    const auto picked=w.serialize();(void)w.interact("wood",1,eye(w,1));check(w.serialize()==picked,"pickup retry changes neither XP nor stamina nor mass");
    rejects([&]{(void)w.interact("wood",2,eye(w,2));});
    (void)w.craft("pry","prybar",{0,1.65,0});check(w.equippedTool()=="Wooden pry tool","craft equips a persistent tool");
    near(w.gatheringCost(),5.6,1e-12,"crafted tool reduces gathering stamina");
    const auto made=w.serialize();(void)w.craft("pry","prybar",{0,1.65,0});check(w.serialize()==made,"craft replay cannot debit twice or award XP twice");
    rejects([&]{(void)w.craft("locked","chisel",{0,1.65,0});});check(w.serialize()==made,"missing level/material retains all state");
    (void)w.interact("iron",7,eye(w,7));check(w.level()==2&&w.quote("chisel").ready(),"experience unlocks an affordable iron tool");
    (void)w.craft("chisel","chisel",{0,1.65,0});near(w.gatheringCost(),3.6,1e-12,"iron tool reduces later gathering cost");
    const double branch_y=w.objects()[18].state.center_of_mass_world_m.y;w.step(120);
    near(w.objects()[18].state.center_of_mass_world_m.y,branch_y,1e-4,"attached branch carries gravity through a fixed constraint");
    for(unsigned i=0;i<4;++i)(void)w.interact("cut-"+std::to_string(i),19,eye(w,19));
    check(!w.objects()[18].attached&&!w.objects()[18].collected,"cut releases whole branch without silently collecting it");
    const auto released=w.objects()[18].state;
    near(length(released.linear_velocity_m_s),0,1e-3,"severing adds no launch impulse");
    w.step(120);check(w.objects()[18].state.center_of_mass_world_m.y<branch_y-.3,"severed branch falls through actual gravity");
    w.step(480);const double prior=w.inventoryKg(MaterialPreset::Oak);(void)w.interact("branch-pickup",19,eye(w,19));
    near(w.inventoryKg(MaterialPreset::Oak)-prior,.9*.08*.08*700,1e-12,"whole branch volume is conserved on inventory conversion");
    auto saved=StarterWorld::deserialize(w.serialize());check(saved.serialize()==w.serialize(),"progress, raw stock, cut state and receipts round trip");
    const auto basic_save_path=std::filesystem::current_path()/"starter-test-save.json";w.save(basic_save_path);w.save(basic_save_path);auto loaded=StarterWorld::load(basic_save_path);check(loaded.serialize()==w.serialize(),"save replacement and disk reload retain the complete starter state");std::filesystem::remove(basic_save_path);
    const auto before_rest=w.stamina();w.rest(1);near(w.stamina()-before_rest,std::min(12.0,100-before_rest),1e-12,"rest explicitly restores bounded gameplay stamina");
    const auto bad=nlohmann::json::parse(w.serialize());auto altered=bad;altered["inventory_m3"][0]=1;rejects([&]{(void)StarterWorld::deserialize(altered.dump());});
    altered=bad;altered["stamina"]=100;rejects([&]{(void)StarterWorld::deserialize(altered.dump());});
    altered=bad;altered["xp"]=100;rejects([&]{(void)StarterWorld::deserialize(altered.dump());});
    altered=bad;altered["bonus"]=true;rejects([&]{(void)StarterWorld::deserialize(altered.dump());});
    rejects([&]{(void)StarterWorld::deserialize("{\"starter_version\":1,\"starter_version\":1}");});
    auto exhausted=nlohmann::json::parse(initial);exhausted["stamina"]=0;exhausted["spent"]=100;
    auto tired=StarterWorld::deserialize(exhausted.dump());const auto tired_before=tired.serialize();
    rejects([&]{(void)tired.interact("tired",1,eye(tired,1));});check(tired.serialize()==tired_before,"insufficient stamina cannot partially collect or award experience");
    for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        StarterWorld game;const unsigned first=m==MaterialPreset::Glass?13:m==MaterialPreset::Oak?1:7;
        for(unsigned i=0;i<4;++i)(void)game.interact("gather-"+std::to_string(i),first+i,eye(game,first+i));
        const double held=game.inventoryKg(m);const auto name=m==MaterialPreset::Glass?"glass-ball":m==MaterialPreset::Oak?"oak-ball":"iron-ball";
        const auto plan=game.quote(name);check(plan.ready(),"all three material sphere designs are affordable after collection/XP");
        (void)game.craft("sphere",name,{0,1.65,0});const auto object=game.objects().back();
        near(held-game.inventoryKg(m),object.recipe.geometry().volume()*makeReferenceMaterial(m).density_kg_m3,1e-12,"craft debit equals actual sphere matter");
        game.step(24);near(game.objects().back().state.linear_velocity_m_s.y,-.981,1e-5,"three-material crafted sphere free fall follows same gravity");
        const double spent_before=game.spent();game.step(240);(void)game.interact("recover-sphere",object.id,eye(game,static_cast<unsigned>(object.id)));
        near(game.inventoryKg(m),held,1e-12,"collecting physical crafted sphere returns raw volume without creating material");check(game.spent()>spent_before,"recovering material does not refund spent stamina");
    }
    for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        StarterWorld custom;auto r=StarterWorld::defaultDraft();r.material=m;r.shape="box";r.dimensions_m={.08,.06,.1};r.name="Iron cutting tool";
        const auto empty=custom.serialize();check(!custom.quoteRecipe(r).ready(),"empty beginner cannot custom craft");
        rejects([&]{(void)custom.craftRecipe("early",r,{0,1.65,0});});check(custom.serialize()==empty,"blocked proposal spends nothing");
        const unsigned first=m==MaterialPreset::Glass?13:m==MaterialPreset::Oak?1:7;
        for(unsigned i=0;i<4;++i)(void)custom.interact("custom-gather-"+std::to_string(i),first+i,eye(custom,first+i));
        const auto stock=custom.inventoryKg(m),stamina=custom.stamina();const auto quote=custom.quoteRecipe(r);check(quote.ready(),"custom design ready for each substance");
        auto request=nlohmann::json::parse(custom.designerRequest("ask","Make a block"));check(request["player"]["level"]==2&&request["application"]=="starter","designer sees actual player progression");
        (void)custom.craftRecipe("custom",r,{0,1.65,0});near(stock-custom.inventoryKg(m),.08*.06*.1*makeReferenceMaterial(m).density_kg_m3,1e-12,"custom mass debit follows geometry and density");
        near(stamina-custom.stamina(),10.48,1e-12,"custom gameplay stamina schedule");check(custom.equippedTool()=="None","custom name cannot grant tool powers");
        const auto built=custom.serialize();(void)custom.craftRecipe("custom",r,{99,0,99});check(custom.serialize()==built,"custom retries replay without double debit");
        rejects([&]{(void)custom.craftRecipe("overlap",r,{0,1.65,0});});check(custom.serialize()==built,"occupied output rejects atomically");
        auto moving=r;moving.linear_velocity_m_s={1,0,0};rejects([&]{(void)custom.quoteRecipe(moving);});
        auto misplaced=r;misplaced.clearance_m=0;rejects([&]{(void)custom.quoteRecipe(misplaced);});
        check(StarterWorld::deserialize(built).serialize()==built,"custom recipe state round trips");
        custom.step(240);check(custom.objects().back().state.center_of_mass_world_m.y>1.19,"custom body rests on physical bench");
    }
    {auto legacy=nlohmann::json::parse(initial);legacy.erase("remembered_design");legacy["starter_version"]=2;check(StarterWorld::deserialize(legacy.dump()).serialize()==initial,"version two starter saves migrate with no invented design");legacy["starter_version"]=1;legacy["rules"]="starter-stamina-v1/whole-branch-cut-v1/raw-volume-v1";for(auto &o:legacy["objects"])o.erase("custom_design");check(StarterWorld::deserialize(legacy.dump()).serialize()==initial,"version one starter saves migrate without invented progress");}
    {
        const auto directory=std::filesystem::current_path()/("starter-transaction-test-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        check(std::filesystem::create_directory(directory),"fresh save test directory");
        for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
            StarterWorld game;const auto path=directory/(std::string(materialPresetName(m))+".json");auto pending=path;pending+=".pending";
            const unsigned first=m==MaterialPreset::Glass?13:m==MaterialPreset::Oak?1:7;
            auto retained=StarterWorld::defaultDraft();retained.material=m;retained.shape="box";retained.dimensions_m={.08,.06,.1};
            game.rememberDesignAndSave(path,{"remembered","Make an 8 by 6 by 10 cm block","Collect material and reach level 2.",retained});
            check(game.stamina()==100&&game.xp()==0&&game.inventoryKg(m)==0,"remembering does not collect spend or award progress");
            game=StarterWorld::load(path);check(game.rememberedDesign().has_value()&&!game.quoteRecipe(*game.rememberedDesign()->recipe).ready(),"resource-short design survives closing and reopening");
            check(CreatorWorld::recipeJson(*game.rememberedDesign()->recipe)==CreatorWorld::recipeJson(retained),"saved requested substance and size are exact");
            const auto followup=nlohmann::json::parse(game.designerRequest("followup","Make this design smaller"));
            check(followup["current_design"]==nlohmann::json::parse(CreatorWorld::recipeJson(retained))&&followup["previous_explanation"]=="Collect material and reach level 2.","follow-up context uses the saved design rather than an unrelated default");
            game.save(path);const auto before=game.serialize();
            {std::ofstream blocked(pending);blocked<<"retained recovery evidence";}
            rejects([&]{game.rememberDesignAndSave(path,{"replacement","Make a different object","Unsupported.",{}});});
            check(game.serialize()==before,"failed remembered-design save retains previous design");
            rejects([&]{(void)game.interactAndSave(path,"saved-pickup",first,eye(game,first));});
            check(game.serialize()==before&&StarterWorld::load(path).serialize()==before,"failed pickup save changes neither live state nor published save");
            {std::ifstream blocked(pending);std::string content{std::istreambuf_iterator<char>(blocked),{}};check(content=="retained recovery evidence","existing pending data is never truncated");}
            std::filesystem::remove(pending);
            (void)game.interactAndSave(path,"saved-pickup",first,eye(game,first));
            auto recovered=StarterWorld::load(path);const auto after=recovered.serialize();(void)recovered.interactAndSave(path,"saved-pickup",first,{99,0,99});
            check(recovered.serialize()==after&&game.serialize()==after,"uncertain acknowledged pickup replays after reload");
            for(unsigned i=1;i<4;++i)(void)game.interactAndSave(path,"saved-gather-"+std::to_string(i),first+i,eye(game,first+i));
            game=StarterWorld::load(path);check(game.quoteRecipe(*game.rememberedDesign()->recipe).ready(),"same saved design becomes ready after gathering without a provider call");
            auto recipe=StarterWorld::defaultDraft();recipe.material=m;recipe.shape="box";recipe.dimensions_m={.08,.06,.1};
            const auto funded=game.serialize();{std::ofstream blocked(pending);blocked<<"pending";}
            rejects([&]{(void)game.craftRecipeAndSave(path,"saved-custom",recipe,{0,1.65,0});});
            const auto preset=m==MaterialPreset::Glass?"glass-ball":m==MaterialPreset::Oak?"oak-ball":"iron-ball";
            rejects([&]{(void)game.craftAndSave(path,"saved-preset",preset,{0,1.65,0});});
            check(game.serialize()==funded&&StarterWorld::load(path).serialize()==funded,"both craft paths retain stock stamina XP and receipts on save failure");
            std::filesystem::remove(pending);
            (void)game.craftRecipeAndSave(path,"saved-custom",recipe,{0,1.65,0});
            recovered=StarterWorld::load(path);const auto crafted=recovered.serialize();(void)recovered.craftRecipeAndSave(path,"saved-custom",recipe,{99,0,99});
            check(recovered.serialize()==crafted&&game.serialize()==crafted,"custom craft receipt survives save and replay without duplicate debit");
            // A failure after writing/flushing the candidate still cannot publish
            // an in-memory action. A directory cannot be replaced by a save file.
            const auto blocked_target=directory/(std::string(materialPresetName(m))+"-directory");std::filesystem::create_directory(blocked_target);
            rejects([&]{(void)game.interactAndSave(blocked_target,"publish-fail",first+4,eye(game,first+4));});
            check(game.serialize()==crafted,"failed file publication cannot expose candidate state");
            auto evidence=blocked_target;evidence+=".pending";check(std::filesystem::is_regular_file(evidence),"failed publication retains candidate evidence");
            std::filesystem::remove(evidence);std::filesystem::remove(blocked_target);std::filesystem::remove(path);
        }
        StarterWorld remembered;const auto remembered_path=directory/"clarification.json";
        remembered.rememberDesignAndSave(remembered_path,{"unsupported","Make a functional saw","Physical cutting is unsupported.",{}});
        auto clarification=StarterWorld::load(remembered_path);check(clarification.rememberedDesign()&&!clarification.rememberedDesign()->recipe,"clarifications survive reload without a buildable recipe");
        auto malformed=nlohmann::json::parse(clarification.serialize());malformed["remembered_design"]["bonus"]=true;rejects([&]{(void)StarterWorld::deserialize(malformed.dump());});
        const auto unchanged=remembered.serialize();auto moving=StarterWorld::defaultDraft();moving.linear_velocity_m_s={1,0,0};
        rejects([&]{remembered.rememberDesignAndSave(remembered_path,{"bad","moving ball","Cannot create motion.",moving});});check(remembered.serialize()==unchanged,"unsupported saved recipes cannot replace valid context");
        std::filesystem::remove(remembered_path);
        std::filesystem::remove(directory);
    }
    for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        JoltWorld physics;physics.setGravity({0,-9.81,0});physics.addFloor();
        physics.addBox({1,{.08,.06,.1},makeReferenceMaterial(m),{{0,2,0},{},{},{}},false});physics.pinToWorld(1);
        for(unsigned i=0;i<120;++i)physics.step(1.0/240);
        near(physics.snapshot(1).center_of_mass_world_m.y,2,1e-4,"three-material attachment supports weight");
        const auto state=physics.snapshot(1);physics.releaseFromWorld(1);
        near(length(physics.snapshot(1).linear_velocity_m_s-state.linear_velocity_m_s),0,0,"constraint release has no invented impulse");
        for(unsigned i=0;i<48;++i)physics.step(1.0/240);
        near(physics.snapshot(1).linear_velocity_m_s.y,-9.81*.2,1e-4,"released material obeys gravity independently of density");
        std::cout<<materialPresetName(m)<<" release-vy="<<physics.snapshot(1).linear_velocity_m_s.y<<'\n';
    }
    std::cout<<"[PASS] starter collect/craft/tool/XP/stamina/replay/branch/gravity/persistence\n";return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
