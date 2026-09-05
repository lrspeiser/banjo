#include "creator/CreatorWorld.hpp"
#include "creator/CodexAssistant.hpp"
#include "physics/RollingKinematics.hpp"
#include <raylib.h>
#include <rlgl.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <future>
#include <iomanip>
#include <iostream>
#include <optional>
#include <numbers>
#include <sstream>

namespace {
using namespace banjo;
using Json=nlohmann::json;
constexpr Color background{19,25,30,255},panel{28,36,42,250},line{57,70,77,255},muted{158,176,181,255},ink{239,244,236,255},accent{191,225,124,255};
Vector3 v(Vec3 x) {return {static_cast<float>(x.x),static_cast<float>(x.y),static_cast<float>(x.z)};}
std::string fixed(double x,int decimals=3) {std::ostringstream s;s<<std::fixed<<std::setprecision(decimals)<<x;return s.str();}
Color color(MaterialPreset m) {
    switch(m) {case MaterialPreset::Glass:return {121,205,216,255};case MaterialPreset::Oak:return {193,144,90,255};case MaterialPreset::Iron:return {148,159,175,255};default:return {180,185,190,255};}
}
std::string name(MaterialPreset m) {auto text=std::string(materialPresetName(m));if (!text.empty())text[0]=static_cast<char>(std::toupper(static_cast<unsigned char>(text[0])));return text;}
std::string allocationLabel(const CreatorWorld &world,const std::vector<MaterialAllocation> &allocations) {
    std::string label;
    for(auto material:kMaterialPresets) {
        double mass=0;
        for(const auto &part:allocations)for(const auto &lot:world.lots())if(part.lot_id==lot.id&&lot.material==material)mass+=part.mass_kg;
        if(mass>0) {if(!label.empty())label+=", ";label+=fixed(mass)+" kg "+name(material);}
    }
    return label.empty()?"0 kg":label;
}
bool button(Rectangle r,std::string_view label,bool enabled=true,bool strong=false) {
    const bool hover=enabled&&CheckCollisionPointRec(GetMousePosition(),r);
    DrawRectangleRounded(r,.16F,5,enabled?(strong?accent:(hover?Color{65,80,85,255}:Color{43,55,62,255})):Color{37,44,49,255});
    DrawText(std::string(label).c_str(),static_cast<int>(r.x+12),static_cast<int>(r.y+(r.height-18)/2),18,enabled?(strong?background:ink):muted);
    return hover&&IsMouseButtonPressed(MOUSE_BUTTON_LEFT);
}
void wrap(std::string_view text,int x,int y,int width,int size=18,Color tint=muted) {
    std::istringstream stream{std::string(text)};std::string word,current;
    while (stream>>word) {
        const std::string next=current.empty()?word:current+" "+word;
        if (!current.empty()&&MeasureText(next.c_str(),size)>width) {DrawText(current.c_str(),x,y,size,tint);y+=size+5;current=word;}
        else current=next;
    }
    DrawText(current.c_str(),x,y,size,tint);
}
std::string read(const std::filesystem::path &path) {
    if (std::filesystem::file_size(path)>1024*1024)throw std::runtime_error("Proposal exceeds 1 MiB");
    std::ifstream file(path,std::ios::binary);if(!file)throw std::runtime_error("Cannot read proposal");
    return {std::istreambuf_iterator<char>(file),std::istreambuf_iterator<char>()};
}
void write(const std::filesystem::path &path,const Json &j) {
    std::ofstream file(path,std::ios::binary);file<<j.dump(2);file.flush();if(!file)throw std::runtime_error("Cannot write AI request");
}
Quat tilt(double degrees) {const double half=degrees*std::numbers::pi/360;return {std::cos(half),0,0,std::sin(half)};}
void drawObject(const ObjectRecipe &recipe,Vec3 position,Quat q,Color tint,bool wire=false) {
    if(recipe.shape=="sphere") {
        if(wire)DrawSphereWires(v(position),static_cast<float>(recipe.radius_m),12,18,tint);
        else {
            DrawSphereEx(v(position),static_cast<float>(recipe.radius_m),20,30,tint);
            const auto tip=position+q.rotate({0,0,recipe.radius_m*1.02});
            DrawLine3D(v(position),v(tip),background);DrawSphere(v(tip),static_cast<float>(recipe.radius_m*.1),ink);
        }
    }else {
        const auto x=q.rotate({1,0,0}),y=q.rotate({0,1,0}),z=q.rotate({0,0,1});
        const float matrix[]{static_cast<float>(x.x),static_cast<float>(x.y),static_cast<float>(x.z),0,
            static_cast<float>(y.x),static_cast<float>(y.y),static_cast<float>(y.z),0,
            static_cast<float>(z.x),static_cast<float>(z.y),static_cast<float>(z.z),0,0,0,0,1};
        rlPushMatrix();rlTranslatef(static_cast<float>(position.x),static_cast<float>(position.y),static_cast<float>(position.z));rlMultMatrixf(matrix);
        if(!wire)DrawCubeV({0,0,0},v(recipe.dimensions_m),tint);
        DrawCubeWiresV({0,0,0},v(recipe.dimensions_m),wire?tint:ink);rlPopMatrix();
    }
}
struct AssemblyTestView {
    bool visible{};
    std::string specification, tested_declaration, error;
    std::uint64_t revision{};
    std::future<std::string> job;
    std::optional<Json> report;
};
void assemblyTestPanel(AssemblyTestView &test,const Json &saved,const std::filesystem::path &workspace) {
    const bool running=test.job.valid();
    const bool present=!saved.at("declaration").is_null();
    const bool current=present&&test.revision==saved.at("revision")&&test.tested_declaration==saved.at("declaration").dump();
    DrawText("ISOLATED SEPARATION TEST",748,147,22,accent);
    wrap("Test a virtual copy with outward motion. No gravity, external collisions or live material consumption.",748,190,615,18);
    if(button({748,248,295,38},"Load test specification",!running))try {
        test.specification=read(workspace/"assembly-test.json");
        test.report.reset();test.error.clear();
        const auto spec=Json::parse(test.specification);
        if(!spec.is_object())throw std::invalid_argument("Test specification must be an object");
    }catch(const std::exception &e){test.specification.clear();test.error=e.what();}
    if(button({1055,248,325,38},running?"TEST RUNNING...":"Run on saved revision",present&&!running&&!test.specification.empty()))try {
        test.report.reset();test.error.clear();test.revision=saved.at("revision");test.tested_declaration=saved.at("declaration").dump();
        test.job=std::async(std::launch::async,[declaration=test.tested_declaration,specification=test.specification]{return CreatorWorld::testAssemblyJson(declaration,specification);});
    }catch(const std::exception &e){test.error=e.what();}
    if(!test.specification.empty())try {
        const auto spec=Json::parse(test.specification);int y=304;
        for(const auto &[key,label]:std::initializer_list<std::pair<const char*,const char*>>{
            {"relative_kinetic_energy_j","Initial relative energy (J)"},{"duration_s","Duration (s)"},
            {"minimum_separated_area_fraction","Required separated fraction"},{"energy_error_budget_j","Numerical energy budget (J)"},
            {"state_error_tolerance","State tolerance"},{"maximum_evaluations","Evaluation limit"}}) {
            const std::string value=spec.contains(key)?spec.at(key).dump().substr(0,30):"missing";
            DrawText((std::string(label)+": "+value).c_str(),748,y,17,muted);y+=25;
        }
    }catch(const std::exception &e){test.error=e.what();}
    else wrap("Place the declared experiment in assembly-test.json in this workshop's folder, then load and review its settings.",748,310,615,19,muted);
    if(test.report&&current) {
        const auto &r=*test.report;
        DrawText(("Revision "+std::to_string(test.revision)+": "+r.at("status").get<std::string>()).c_str(),748,469,24,accent);
        DrawText(("Separated: "+fixed(100*r.at("separated_area_fraction").get<double>(),2)+"% / required: "+fixed(100*r.at("specification").at("minimum_separated_area_fraction").get<double>(),2)+"%").c_str(),748,505,18,ink);
        DrawText(("Energy residual (J): "+r.at("energy_residual_j").dump()).c_str(),748,534,17,muted);
        DrawText(("Accumulated error (J): "+r.at("accumulated_absolute_energy_error_j").dump()).c_str(),748,560,17,muted);
        if(button({748,602,230,36},"Export test evidence"))try {
            write(workspace/"assembly-test-result.json",Json{{"draft_revision",test.revision},{"report",r}});
            test.error="Evidence exported with declaration, settings and revision.";
        }catch(const std::exception &e){test.error=e.what();}
    }else if(test.report||running)wrap(current?"Computing the declared experiment...":"Design changed. Results for an earlier revision are not current; run again.",748,475,610,21,ink);
    if(!test.error.empty())wrap(test.error,748,643,615,15,ink);
}
// Assembly authoring is separate from live rigid-object creation. Publish only
// after the existing save succeeds, so failed imports do not replace the draft.
bool assemblyScreen(CreatorWorld &world,const std::filesystem::path &workspace,bool persistent,std::string &message,AssemblyTestView &test) {
    const auto saved=Json::parse(world.serialize()).at("assembly_draft");
    const auto revision=saved.at("revision").get<std::uint64_t>();
    const bool present=!saved.at("declaration").is_null();
    const auto change=[&](const auto &operation) {
        auto candidate=CreatorWorld::deserialize(world.serialize());operation(candidate);
        if(persistent)candidate.save(workspace/"world.json");
        world=std::move(candidate);
    };
    if(test.job.valid()&&test.job.wait_for(std::chrono::seconds(0))==std::future_status::ready)try {
        test.report=Json::parse(test.job.get());
    }catch(const std::exception &e){test.report.reset();test.error=std::string("Test rejected: ")+e.what();}
    BeginDrawing();ClearBackground(background);
    DrawText("BANJO / ASSEMBLY DESIGN",36,30,30,ink);
    DrawText("Keep a design. Gather its materials. Review what is supported.",36,76,20,muted);
    const bool back=button({1150,28,250,44},"Back to workshop");
    DrawRectangleRounded({28,123,680,585},.03F,8,panel);
    DrawRectangleRounded({728,123,680,585},.03F,8,panel);
    DrawText(("SAVED DESIGN / revision "+std::to_string(revision)).c_str(),48,147,22,accent);
    if(!test.visible)DrawText("MATERIAL REQUIREMENTS",748,147,22,accent);
    if(present)try {
        const auto &declaration=saved.at("declaration");
        const auto assessment=Json::parse(world.assessAssemblyJson(declaration.dump()));
        int y=203;
        for(const auto &part:assessment.at("parts")) {
            const auto &authored=*std::find_if(declaration.at("parts").begin(),declaration.at("parts").end(),[&](const auto &p){return p.at("id")==part.at("id");});
            const auto &d=authored.at("dimensions_m");
            DrawText((part.at("id").get<std::string>().substr(0,32)+" / "+part.at("material").get<std::string>()).c_str(),48,y,22,ink);
            DrawText((fixed(d[0])+" x "+fixed(d[1])+" x "+fixed(d[2])+" m").c_str(),48,y+33,19,muted);
            DrawText(("Mass "+fixed(part.at("mass_kg"),6)+" kg").c_str(),48,y+62,18,muted);y+=115;
        }
        const auto &joint=assessment.at("joint");
        DrawText("JOIN / experimental cohesive interface",48,454,20,accent);
        DrawText(("Area "+fixed(joint.at("area_m2"),6)+" m2 / gap "+fixed(joint.at("rest_gap_m"),6)+" m").c_str(),48,491,18,ink);
        DrawText(("Complete separation work: "+fixed(joint.at("complete_tensile_separation_work_j"),6)+" J").c_str(),48,524,18,ink);
        wrap("Separation work is not the energy cost of making this joint. Manufacturing processes and tools are not modeled yet.",48,570,625,18);
        if(!test.visible) {
        y=203;
        for(const auto &need:assessment.at("material_requirements")) {
            DrawText(need.at("material").get<std::string>().c_str(),748,y,23,ink);
            DrawText(("Required "+fixed(need.at("required_mass_kg"),6)+" kg / held "+fixed(need.at("inventory_mass_kg"),6)+" kg").c_str(),748,y+34,18,muted);
            DrawText(("Missing from inventory: "+fixed(need.at("missing_from_inventory_kg"),6)+" kg").c_str(),748,y+65,18,accent);
            DrawText(("Collectible "+fixed(need.at("collectible_mass_kg"),6)+" kg / still missing after: "+fixed(need.at("missing_after_collection_kg"),6)+" kg").c_str(),748,y+94,17,muted);
            y+=140;
        }
        DrawText(assessment.at("materials_sufficient").get<bool>()?"Materials ready":"Collect the missing materials",748,515,22,accent);
        wrap("Building assemblies is not supported yet. Having enough material does not enable construction. This design remains available as you gather.",748,559,620,20,ink);
        }
    }catch(const std::exception &e){message=e.what();}
    else {
        wrap("No assembly saved. Drop an assembly design file into this window, or place it in the workshop folder as assembly.json and choose Import design. A valid import replaces the saved design; a rejected import leaves it intact.",48,211,620,21,ink);
        if(!test.visible)wrap("Import a design to see exact material quantities. The current assembly model supports two boxes and one declared joint.",748,211,610,21,muted);
    }
    if(test.visible)assemblyTestPanel(test,saved,workspace);
    if(button({48,647,610,38},test.visible?"Show material requirements":"Review a physics test"))test.visible=!test.visible;
    if(button({36,730,225,44},"Import design"))try {
        const auto document=read(workspace/"assembly.json");
        change([&](CreatorWorld &w){(void)w.rememberAssembly(document,revision);});message="Design validated and saved. Its material requirements are current.";
    }catch(const std::exception &e){message=std::string("Import rejected: ")+e.what();}
    if(IsFileDropped()) {
        auto files=LoadDroppedFiles();
        try {
            if(files.count!=1)throw std::invalid_argument("Drop exactly one assembly design file");
            const auto document=read(files.paths[0]);
            change([&](CreatorWorld &w){(void)w.rememberAssembly(document,revision);});message="Design validated and saved. Its material requirements are current.";
        }catch(const std::exception &e){message=std::string("Import rejected: ")+e.what();}
        UnloadDroppedFiles(files);
    }
    if(button({277,730,225,44},"Clear saved design",present))try {
        change([&](CreatorWorld &w){(void)w.clearAssembly(revision);});message="Saved design cleared. Inventory is unchanged.";
    }catch(const std::exception &e){message=e.what();}
    unsigned i=0;
    // Do not retain references to the old world across a candidate publication.
    const auto lots=world.lots();
    for(const auto &lot:lots)if(!lot.collected&&i<3) {
        if(button({static_cast<float>(518+296*i),730,280,44},"Collect "+name(lot.material)))try {
            change([&](CreatorWorld &w){w.collect(lot.id);});message="Material collected and saved. Requirements have been refreshed.";
        }catch(const std::exception &e){message=e.what();}
        ++i;
    }
    wrap(message,36,802,1345,19,ink);
    DrawText("Design review only / live simulation paused / physical construction and cutting remain unfinished",36,869,17,muted);
    EndDrawing();return back;
}

}
int main(int argc,char **argv) {
    try {
        std::filesystem::path workspace=std::filesystem::absolute(argv[0]).parent_path()/"workshop-data",capture;unsigned frames=180;
        std::filesystem::path assistant_exe=ChildProcess::findExecutable("codex");bool manual_assistant=false,shape_capture=false,revision_capture=false,requirements_capture=false,assembly_capture=false,assembly_view=false;
        for(int i=1;i<argc;++i) {
            const std::string option=argv[i];if(++i>=argc)throw std::invalid_argument("missing workshop option value");
            if(option=="--workspace")workspace=argv[i];else if(option=="--capture")capture=argv[i];
            else if(option=="--view") {const std::string view=argv[i];if(view!="assembly"&&view!="objects")throw std::invalid_argument("view must be assembly or objects");assembly_view=view=="assembly";}
            else if(option=="--assistant-exe")assistant_exe=std::filesystem::absolute(argv[i]);
            else if(option=="--capture-layout") {const std::string layout=argv[i];if(layout!="materials"&&layout!="shapes"&&layout!="revisions"&&layout!="requirements"&&layout!="assembly")throw std::invalid_argument("capture layout must be materials, shapes, revisions, requirements or assembly");shape_capture=layout=="shapes";revision_capture=layout=="revisions";requirements_capture=layout=="requirements";assembly_capture=layout=="assembly";assembly_view=assembly_capture;}
            else if(option=="--assistant") {const std::string mode=argv[i];if(mode!="auto"&&mode!="manual")throw std::invalid_argument("assistant must be auto or manual");manual_assistant=mode=="manual";}
            else if(option=="--frames")frames=static_cast<unsigned>(std::stoul(argv[i]));else throw std::invalid_argument("unknown workshop option");
        }
        if(frames==0||frames>3600)throw std::invalid_argument("capture frames must be 1–3600");
        std::filesystem::create_directories(workspace);workspace=std::filesystem::absolute(workspace);
        auto world=(capture.empty()||assembly_capture)&&std::filesystem::exists(workspace/"world.json")?CreatorWorld::load(workspace/"world.json"):CreatorWorld{};
        CodexAssistant assistant(assistant_exe);
        const bool automatic_assistant=!manual_assistant&&assistant.available();
        ObjectRecipe draft;std::string prompt="Use some of my wood to make a ball that rolls down this ramp.";
        std::string status="Collect a material, then design an object.",request_id,pending_id,proposal_message;
        AssemblyTestView assembly_test;
        std::optional<RevisionTarget> editing;
        MatterBodyId selected_id=world.objects().empty()?0:world.objects().back().id,built_id=0;
        bool paused=capture.empty(),typing=false,built=false,follow=false,clarification_required=false;double accumulator=0,poll_at=0;unsigned rendered=0,serial=0;
        unsigned dimension_axis=0,orientation_preset=0;
        const auto session=std::to_string(std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
        const auto new_id=[&]{return "workshop-"+session+"-"+std::to_string(++serial);};request_id=new_id();
        const auto save=[&]{if(capture.empty())world.save(workspace/"world.json");};
        const auto find_object=[&](MatterBodyId id)->const CreatedObject* {
            const auto found=std::find_if(world.objects().begin(),world.objects().end(),[&](const auto &o){return o.id==id;});
            return found==world.objects().end()?nullptr:&*found;
        };
        const auto invalidate_design=[&] {
            assistant.cancel();pending_id.clear();request_id=new_id();built=false;built_id=0;proposal_message.clear();clarification_required=false;
            status="Design updated. Review the material cost before building.";
        };
        const auto select_edit=[&](MatterBodyId id) {
            const auto *object=find_object(id);if(!object)return;
            draft=object->recipe;editing=RevisionTarget{id,object->revision};selected_id=id;
            invalidate_design();paused=true;accumulator=0;typing=false;
            status="Editing object #"+std::to_string(id)+". Rebuild reuses its intact material and resets its motion to the design.";
        };
        if(!capture.empty()&&!assembly_capture) {
            for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
                world.collect(std::string(materialPresetName(m))+"-pile");auto r=draft;r.material=m;
                r.bitangent_m=.45*(static_cast<double>(world.objects().size())-(shape_capture?2.5:1));
                if(shape_capture)r.radius_m=.04;
                if(revision_capture||requirements_capture)r.radius_m=std::cbrt(9.9/(makeReferenceMaterial(m).density_kg_m3*(4.0/3)*std::numbers::pi));
                (void)world.create(std::string(materialPresetName(m))+"-capture",r);
                if(shape_capture) {
                    const double volume=r.geometry().volume();r.shape="box";r.schema_version=2;r.name=name(m)+" box";
                    r.dimensions_m={.08,.06,volume/(.08*.06)};r.orientation_world=tilt(-world.settings().slope_degrees);r.bitangent_m+=.45;
                    (void)world.create(std::string(materialPresetName(m))+"-box-capture",r);
                }
            }
            draft=world.objects().back().recipe;request_id=world.objects().back().request_id;
            selected_id=built_id=world.objects().back().id;
            built=true;status=shape_capture?"Equal-volume sphere/box pairs in glass, oak and iron. Same ramp, zero initial motion.":"Three materials, one creation path. Motion comes from contact and gravity.";
            if(revision_capture) {
                world.step(120);
                for(MatterBodyId id:{MatterBodyId{1},MatterBodyId{2}}) {
                    auto r=find_object(id)->recipe;r.schema_version=2;r.shape="box";r.name=name(r.material)+" rebuilt block";
                    r.dimensions_m={.08,.06,.1};r.orientation_world=tilt(-world.settings().slope_degrees);
                    (void)world.rebuild("capture-rebuild-"+std::to_string(id),{id,1},r);
                }
                select_edit(3);draft.schema_version=2;draft.shape="box";draft.name="Iron replacement";draft.dimensions_m={.08,.06,.1};draft.orientation_world=tilt(-world.settings().slope_degrees);
                prompt="Rebuild this iron ball as an 8 x 6 x 10 cm block using its recovered material.";
                status="Glass and oak were rebuilt from 9.9 kg spheres. Previewing an iron rebuild with 0.1 kg free stock.";
            }
            if(requirements_capture) {
                world.step(120);built=false;built_id=0;paused=true;draft.schema_version=2;draft.shape="box";draft.name="Requested iron block";
                draft.dimensions_m={.08,.06,.1};draft.orientation_world=tilt(-world.settings().slope_degrees);
                prompt="Keep my existing balls. Make a new solid iron block, 8 x 6 x 10 cm. What else do I need?";
                status="The requested design is kept. Its exact material shortfall comes from the compiler; nothing is built or collected.";
            }
        }
        SetConfigFlags(FLAG_MSAA_4X_HINT);InitWindow(1440,900,"Banjo - Material Workshop");SetTargetFPS(60);
        SetExitKey(KEY_NULL);
        Camera3D camera{{1.4F,2.2F,3.7F},{-1.3F,.3F,0},{0,1,0},45,CAMERA_PERSPECTIVE};
        double yaw=.72,pitch=.4,distance=4.8;
        while(!WindowShouldClose()) {
            if(assembly_view) {
                paused=true;accumulator=0;typing=false;
                bool screenshot_requested=false;
                for(int key=GetKeyPressed();key;key=GetKeyPressed()) {
                    if(key==KEY_ESCAPE)assembly_view=false;
                    if(key==KEY_F12)screenshot_requested=true;
                }
                if(assemblyScreen(world,workspace,capture.empty(),status,assembly_test))assembly_view=false;
                if(screenshot_requested&&capture.empty()) {
                    Image image=LoadImageFromScreen();const bool success=ExportImage(image,(workspace/"assembly.png").string().c_str());UnloadImage(image);
                    status=success?"Assembly image saved.":"Could not save assembly image.";
                }
                ++rendered;
                if(!capture.empty()&&rendered>=frames) {
                    if(capture.has_parent_path())std::filesystem::create_directories(capture.parent_path());
                    Image image=LoadImageFromScreen();const bool success=ExportImage(image,capture.string().c_str());UnloadImage(image);
                    if(!success)throw std::runtime_error("capture failed");break;
                }
                continue;
            }
            const auto mouse=GetMousePosition();
            if(IsMouseButtonPressed(MOUSE_BUTTON_LEFT))typing=pending_id.empty()&&CheckCollisionPointRec(mouse,{330,700,725,76});
            // Short press/release pairs can both arrive between rendered frames.
            // Consume the same key event queue used by the main laboratory.
            bool control=IsKeyDown(KEY_LEFT_CONTROL)||IsKeyDown(KEY_RIGHT_CONTROL),take_screenshot=false;
            for(int key=GetKeyPressed();key;key=GetKeyPressed()) {
                if(key==KEY_LEFT_CONTROL||key==KEY_RIGHT_CONTROL)control=true;
                if(key==KEY_F12)take_screenshot=true;
                if(typing) {
                    if(control&&key==KEY_A)prompt.clear();
                    if(key==KEY_BACKSPACE&&!prompt.empty())prompt.pop_back();
                    if(control&&key==KEY_V) {
                        const char *clipboard=GetClipboardText();
                        if(clipboard)for(const char *c=clipboard;*c&&prompt.size()<500;++c)if(*c>=32&&*c<127)prompt+=*c;
                    }
                    if(key==KEY_ESCAPE)typing=false;
                }else {
                    if(key==KEY_SPACE)paused=!paused;
                    if(key==KEY_F)follow=!follow;
                }
            }
            for(int c=GetCharPressed();c;c=GetCharPressed())if(typing&&!control&&c>=32&&c<127&&prompt.size()<500)prompt+=static_cast<char>(c);
            if(!typing&&mouse.x>310&&mouse.x<1080&&mouse.y<680) {
                if(IsMouseButtonDown(MOUSE_BUTTON_RIGHT)) {const auto delta=GetMouseDelta();yaw-=delta.x*.006;pitch=std::clamp(pitch+delta.y*.006,.08,1.3);}
                distance=std::clamp(distance-GetMouseWheelMove()*.25,1.2,12.0);
            }
            if(!paused) {
                accumulator+=capture.empty()?std::min(static_cast<double>(GetFrameTime()),.1):1.0/60;
                while(accumulator>=1.0/240){world.step();accumulator-=1.0/240;}
            }
            if(follow)if(const auto *object=find_object(selected_id))camera.target=v(object->state.center_of_mass_world_m);
            camera.position={camera.target.x+static_cast<float>(distance*std::cos(pitch)*std::sin(yaw)),camera.target.y+static_cast<float>(distance*std::sin(pitch)),camera.target.z+static_cast<float>(distance*std::cos(pitch)*std::cos(yaw))};
            if(!pending_id.empty()&&GetTime()>poll_at) {
                poll_at=GetTime()+.5;const auto path=workspace/("proposal-"+pending_id+".json");
                if(automatic_assistant)try {
                    if(auto reply=assistant.poll()) {
                        if(reply->recipe) {
                            const auto assessment=world.assess(*reply->recipe,editing);draft=*reply->recipe;request_id=pending_id;built=false;built_id=0;clarification_required=false;
                            status=assessment.buildable()?"Assistant proposal ready. Review the cost, then build.":"Requested design retained. Review what is missing, collect resources or ask for an alternative.";
                        }else {status="The assistant needs a different choice. Update your request below.";clarification_required=true;}
                        proposal_message=reply->explanation;pending_id.clear();paused=true;
                    }
                }catch(const std::exception &e){status=e.what();pending_id.clear();assistant.cancel();paused=true;}
                else if(std::filesystem::exists(path))try {
                    auto proposal=CreatorWorld::parseProposal(read(path));if(proposal.request_id!=pending_id)throw std::invalid_argument("AI response belongs to another request");
                    const auto assessment=world.assess(proposal.recipe,editing);draft=proposal.recipe;request_id=pending_id;pending_id.clear();built=false;built_id=0;clarification_required=false;
                    proposal_message=proposal.explanation;status=assessment.buildable()?"AI proposal ready. Review its material cost, then build.":"Requested design retained. Review its requirements before building.";paused=true;
                }catch(const std::exception &e){status=std::string("Proposal needs revision: ")+e.what();}
            }
            std::optional<CreationPreview> preview;std::optional<RebuildPreview> rebuild_preview;std::optional<CreationAssessment> assessment;std::string problem;
            try {
                assessment=world.assess(draft,editing);
                if(assessment->buildable()) {if(editing){rebuild_preview=world.previewRebuild(*editing,draft);preview=rebuild_preview->creation;}else preview=assessment->creation;}
                else problem=assessment->issues.front().message;
            }catch(const std::exception &e){problem=e.what();}
            BeginDrawing();ClearBackground(background);BeginMode3D(camera);
            rlPushMatrix();rlRotatef(static_cast<float>(-world.settings().slope_degrees),0,0,1);rlTranslatef(0,-.1F,0);
            DrawCube({0,0,0},16,.2F,6,{69,83,88,255});DrawCubeWires({0,0,0},16,.2F,6,{103,119,124,255});rlPopMatrix();
            const auto plane=world.support();
            for(int i=-8;i<=8;++i)DrawLine3D(v(pointInPlaneFrame(plane,i,-3,.001)),v(pointInPlaneFrame(plane,i,3,.001)),{83,99,105,255});
            for(const auto &object:world.objects())drawObject(object.recipe,object.state.center_of_mass_world_m,object.state.orientation_world,color(object.recipe.material));
            if(assessment&&!built)drawObject(draft,assessment->creation.position_world_m,draft.orientation_world,assessment->buildable()?accent:Color{244,165,131,255},true);
            for(std::size_t i=0;i<world.lots().size();++i)if(!world.lots()[i].collected) {
                const auto &lot=world.lots()[i];const double size=std::cbrt(lot.remaining_mass_kg/makeReferenceMaterial(lot.material).density_kg_m3);
                DrawCubeV(v(pointInPlaneFrame(plane,-2.7,.45*(static_cast<double>(i)-1),size/2)),{static_cast<float>(size),static_cast<float>(size),static_cast<float>(size)},color(lot.material));
            }
            EndMode3D();
            DrawRectangle(0,0,1440,100,background);DrawText("BANJO / MATERIAL WORKSHOP",24,22,30,ink);
            DrawText("Collect. Describe. Build. Try it.",26,62,19,muted);
            if(button({810,28,270,44},"Assembly designs")) {assistant.cancel();pending_id.clear();assembly_view=true;}
            DrawText((fixed(world.timeSeconds(),2)+" s").c_str(),1200,30,22,muted);
            DrawRectangleRounded({18,114,288,748},.035F,8,panel);DrawText("YOUR MATERIALS",36,135,20,accent);
            for(std::size_t i=0;i<world.lots().size()&&i<3;++i) {
                const auto &lot=world.lots()[i];const int y=180+static_cast<int>(i)*140;
                DrawCircle(48,y+12,9,color(lot.material));DrawText(name(lot.material).c_str(),69,y,22,ink);
                DrawText((fixed(lot.remaining_mass_kg)+" kg "+(lot.collected?"available":"in the world")).c_str(),38,y+32,17,muted);
                if(button({36,static_cast<float>(y+65),248,40},lot.collected?"Collected":"Collect material",!lot.collected))try {world.collect(lot.id);save();status="Material collected. Your inventory is ready.";}catch(const std::exception &e){status=e.what();}
            }
            wrap("Geometry and density determine the material cost. Lots keep their identity.",36,635,245);
            DrawText("Energy: not modeled yet",36,723,16,muted);
            DrawText("SUPPORTED NOW",36,751,17,accent);wrap("Rigid spheres and boxes. No deformation or fracture.",36,780,242,17);
            DrawRectangleRounded({1092,114,330,748},.035F,8,panel);DrawText(editing?"REBUILD PREVIEW":"OBJECT PREVIEW",1110,135,20,accent);
            DrawText(draft.name.substr(0,24).c_str(),1110,173,22,ink);
            const auto &edit=invalidate_design;
            if(button({1110,202,292,30},draft.shape=="sphere"?"Shape: sphere":"Shape: box")) {
                draft.shape=draft.shape=="sphere"?"box":"sphere";draft.schema_version=2;draft.name=name(draft.material)+(draft.shape=="sphere"?" ball":" box");
                draft.orientation_world=draft.shape=="box"?tilt(-world.settings().slope_degrees):Quat{};edit();
            }
            if(button({1110,244,292,40},"Material: "+name(draft.material))) {draft.material=draft.material==MaterialPreset::Oak?MaterialPreset::Glass:draft.material==MaterialPreset::Glass?MaterialPreset::Iron:MaterialPreset::Oak;edit();}
            if(draft.shape=="box") {
                if(button({1110,291,292,36},"Edit dimension: "+std::string(1,"XYZ"[dimension_axis])))dimension_axis=(dimension_axis+1)%3;
                DrawText((fixed(draft.dimensions_m.x)+" x "+fixed(draft.dimensions_m.y)+" x "+fixed(draft.dimensions_m.z)+" m").c_str(),1110,331,15,ink);
            }else DrawText(("Radius  "+fixed(draft.radius_m,3)+" m").c_str(),1110,306,20,ink);
            double &dimension=draft.shape=="sphere"?draft.radius_m:(dimension_axis==0?draft.dimensions_m.x:dimension_axis==1?draft.dimensions_m.y:draft.dimensions_m.z);
            if(button({1110,353,140,32},"- 5 mm")){dimension=std::max(.025,dimension-.005);edit();}
            if(button({1262,353,140,32},"+ 5 mm")){dimension=std::min(draft.shape=="sphere"?.5:1,dimension+.005);edit();}
            if(button({1110,390,292,36},"Lane: "+fixed(draft.bitangent_m,2)+" m")){draft.bitangent_m=draft.bitangent_m>=.45?-.45:draft.bitangent_m+.45;edit();}
            if(button({1110,430,292,28},"Orientation: cycle presets")) {
                orientation_preset=(orientation_preset+1)%3;draft.schema_version=2;
                draft.orientation_world=orientation_preset==0?Quat{}:tilt(orientation_preset==1?-world.settings().slope_degrees:45-world.settings().slope_degrees);edit();
            }
            if(built) {
                if(const auto *object=find_object(built_id))DrawText(("Built with "+fixed(object->mass_kg)+" kg").c_str(),1110,468,22,ink);
                DrawText(("Available "+fixed(world.inventoryMass(draft.material))+" kg").c_str(),1110,500,18,muted);
            } else if(assessment&&assessment->material.missing_mass_kg>0) {
                const auto &m=assessment->material;
                DrawText(("Requires: "+fixed(m.required_mass_kg)+" kg").c_str(),1110,466,17,ink);
                DrawText(("In inventory: "+fixed(m.inventory_mass_kg)+" kg").c_str(),1110,488,15,muted);
                DrawText(("Recoverable: "+fixed(m.recoverable_mass_kg)+" kg").c_str(),1110,508,15,muted);
                DrawText(("Need: "+fixed(m.missing_mass_kg)+" kg "+name(m.material)).c_str(),1110,528,15,{244,165,131,255});
            } else if(rebuild_preview) {
                DrawText(("New mass: "+fixed(rebuild_preview->creation.mass_kg)+" kg").c_str(),1110,466,17,ink);
                DrawText(("Reuse: "+allocationLabel(world,rebuild_preview->reused)).c_str(),1110,488,15,muted);
                DrawText(("From stock: "+allocationLabel(world,rebuild_preview->withdrawn)).c_str(),1110,508,15,muted);
                DrawText(("Return: "+allocationLabel(world,rebuild_preview->returned)).c_str(),1110,528,15,muted);
            } else if(preview) {
                DrawText(("Uses "+fixed(preview->mass_kg)+" kg").c_str(),1110,468,22,ink);
                DrawText(("Leaves "+fixed(world.inventoryMass(draft.material)-preview->mass_kg)+" kg").c_str(),1110,500,18,muted);
            } else if(!built)wrap(problem,1110,464,288,17,{237,189,137,255});
            if(button({1110,548,292,48},built?"Object ready":clarification_required?"Clarification needed":editing?"Rebuild from materials":"Build this object",preview.has_value()&&!built&&pending_id.empty()&&!clarification_required,true))try {
                const bool rebuilding=editing.has_value();
                built_id=rebuilding?world.rebuild(request_id,*editing,draft):world.create(request_id,draft);
                selected_id=built_id;editing=RevisionTarget{built_id,find_object(built_id)->revision};built=true;paused=true;accumulator=0;save();
                status=rebuilding?"Object rebuilt. Unused material returned; motion reset to the design. Press Run to test it.":"Created from your inventory. Press Run to test it, or revise this object.";
            }catch(const std::exception &e){status=e.what();}
            if(button({1110,614,140,40},paused?"Run":"Pause"))paused=!paused;
            if(button({1262,614,140,40},"Step")){paused=true;world.step();}
            if(button({1110,669,292,38},"Save world"))try{save();status="Inventory, object recipes and motion saved.";}catch(const std::exception &e){status=e.what();}
            if(const auto *object=find_object(selected_id)) {
                const auto motion=measureCreatorMotion(*object,plane);
                DrawText(("Selected: "+(motion.state=="no top-support sample"?std::string("contact not measured"):motion.state)).c_str(),1110,739,16,ink);
                DrawText((motion.near_support_points?"Slip "+fixed(motion.slip_m_s)+" m/s":"Slip: no top-support sample").c_str(),1110,769,17,muted);
                DrawText(("Speed "+fixed(motion.speed_m_s)+" m/s").c_str(),1110,797,17,muted);
            }
            DrawRectangleRounded({324,681,750,181},.035F,8,panel);
            DrawRectangleRounded({330,700,725,76},.1F,5,typing?Color{47,60,67,255}:Color{37,48,55,255});wrap(prompt,345,714,690,18,ink);
            if(button({340,795,190,42},"Ask assistant",!prompt.empty()&&pending_id.empty(),true))try {
                pending_id=new_id();typing=false;
                if(automatic_assistant) {
                    assistant.start(workspace,pending_id,CodexAssistant::requestDocument(world,pending_id,prompt,draft,proposal_message,editing));
                    status="The assistant is designing from your collected materials...";proposal_message.clear();
                }else {
                auto request=Json::parse(CodexAssistant::requestDocument(world,pending_id,prompt,draft,proposal_message,editing));
                request["response_file"]="proposal-"+pending_id+".json";
                request["instruction"]="Return request_id, explanation and a supported recipe. Editing, when present, identifies the only replacement target; available_after_recovery includes its intact matter once. Use only collected materials. Rebuild resets placement/motion as an authoring operation, not simulated manufacturing. The application validates the proposal before acceptance.";
                write(workspace/("request-"+pending_id+".json"),request);status="AI request saved in the workshop folder. Awaiting an assistant proposal.";
                proposal_message="Manual bridge: an assistant reads the request file and returns a proposal. For automatic replies, install/sign in to the Codex CLI and reopen the workshop.";
                }
            }catch(const std::exception &e){pending_id.clear();status=e.what();}
            if(button({545,795,175,42},"Cancel request",!pending_id.empty())) {assistant.cancel();pending_id.clear();proposal_message.clear();status="Request cancelled. No material was spent.";}
            DrawText(("Objects: "+std::to_string(world.objects().size())+" / 64").c_str(),852,807,17,muted);
            wrap(status,330,122,735,19,ink);
            DrawText(automatic_assistant?"Assistant: Codex (automatic)":"Assistant: manual file bridge",330,179,17,accent);
            if(!proposal_message.empty())wrap(proposal_message,330,212,730,17,muted);
            if(assessment&&!built&&assessment->material.missing_mass_kg>0) {
                const auto &m=assessment->material;
                wrap(m.collectible_mass_kg>0?"In the world: "+fixed(m.collectible_mass_kg)+" kg "+name(m.material)+" to collect. Remaining shortfall after collection: "+fixed(m.missing_after_collection_kg)+" kg.":"Collect "+fixed(m.missing_mass_kg)+" kg more "+name(m.material)+", or ask for an alternative. Existing objects are only reused when selected for editing.",330,451,725,15,{244,165,131,255});
            }
            if(editing)wrap("Rebuild returns or reuses intact material and places this object at the design's start position and motion. No manufacturing or damage repair is simulated.",330,493,725,15,muted);
            if(button({330,550,150,34},"New design")) {editing.reset();draft=ObjectRecipe{};invalidate_design();paused=true;accumulator=0;}
            if(button({490,550,170,34},"Edit selected",find_object(selected_id)!=nullptr))select_edit(selected_id);
            if(button({670,550,140,34},"Next object",!world.objects().empty())) {
                auto index=std::find_if(world.objects().begin(),world.objects().end(),[&](const auto &o){return o.id==selected_id;});
                if(index==world.objects().end()||++index==world.objects().end())index=world.objects().begin();
                select_edit(index->id);
            }
            if(button({820,550,230,34},"Reclaim selected",editing.has_value()&&pending_id.empty()))try {
                const auto target=*editing;world.reclaim(new_id(),target);editing.reset();invalidate_design();paused=true;accumulator=0;
                selected_id=world.objects().empty()?0:world.objects().back().id;save();status="Object #"+std::to_string(target.object_id)+" reclaimed. Its intact material is back in the original lots.";
            }catch(const std::exception &e){status=e.what();}
            if(button({330,590,180,34},follow?"Following object":"Follow object",!world.objects().empty()))follow=!follow;
            if(const auto *object=find_object(selected_id))DrawText(("Selected #"+std::to_string(object->id)+" / revision "+std::to_string(object->revision)+" / "+object->recipe.name.substr(0,22)).c_str(),530,599,17,ink);
            DrawText("Orbit: right-drag / Space: pause / F: follow / F12: image",330,644,16,muted);
            DrawText(automatic_assistant?"Ask assistant sends the prompt and virtual-world context to Codex. Build always requires your review.":"Inventory and recipes stay local. Material behavior is a declared approximation.",24,875,16,muted);
            EndDrawing();++rendered;
            if(capture.empty()&&take_screenshot) {
                Image screenshot=LoadImageFromScreen();const bool saved=ExportImage(screenshot,(workspace/"workshop.png").string().c_str());UnloadImage(screenshot);
                status=saved?"Workshop image saved in the world folder.":"Could not save workshop image.";
            }
            if(!capture.empty()&&rendered>=frames) {
                if(capture.has_parent_path())std::filesystem::create_directories(capture.parent_path());
                Image image=LoadImageFromScreen();const bool success=ExportImage(image,capture.string().c_str());UnloadImage(image);
                if(!success)throw std::runtime_error("capture failed");break;
            }
        }
        assistant.cancel();save();CloseWindow();return 0;
    }catch(const std::exception &e){std::cerr<<"Workshop error: "<<e.what()<<'\n';if(IsWindowReady())CloseWindow();return 1;}
}
