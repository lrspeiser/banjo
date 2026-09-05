#include "creator/StarterWorld.hpp"
#include "creator/CodexAssistant.hpp"
#include <raylib.h>
#include <rlgl.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <future>
#include <fstream>
#include <nlohmann/json.hpp>

namespace {
using namespace banjo;
constexpr Color ink{243,241,220,255},muted{175,193,179,255},panel{22,37,33,248},gold{241,190,91,255},green{141,197,108,255};
Vector3 v(Vec3 p){return {static_cast<float>(p.x),static_cast<float>(p.y),static_cast<float>(p.z)};}
Vec3 v(Vector3 p){return {p.x,p.y,p.z};}
std::string number(double x,int digits=2){std::ostringstream out;out<<std::fixed<<std::setprecision(digits)<<x;return out.str();}
Color tint(MaterialPreset m){return m==MaterialPreset::Oak?Color{166,110,64,255}:m==MaterialPreset::Glass?Color{136,224,226,255}:Color{152,164,183,255};}
void text(std::string s,int x,int y,int size=20,Color c=ink){DrawText(s.c_str(),x,y,size,c);}
void wrap(std::string s,int x,int y,int width,int size=18,Color c=muted){std::istringstream in(s);std::string word,line;while(in>>word){auto next=line.empty()?word:line+" "+word;if(!line.empty()&&MeasureText(next.c_str(),size)>width){text(line,x,y,size,c);y+=size+6;line=word;}else line=next;}text(line,x,y,size,c);}
bool button(Rectangle r,std::string label,bool enabled=true){const bool hover=enabled&&CheckCollisionPointRec(GetMousePosition(),r);DrawRectangleRec(r,enabled?(hover?Color{174,213,118,255}:green):Color{63,77,67,255});text(label,static_cast<int>(r.x)+12,static_cast<int>(r.y)+12,18,enabled?panel:muted);return hover&&IsMouseButtonPressed(MOUSE_BUTTON_LEFT);}
void shape(const StarterObject &o,bool wire=false){
    if(o.recipe.shape=="sphere"){if(wire)DrawSphereWires(v(o.state.center_of_mass_world_m),static_cast<float>(o.recipe.radius_m)+.008F,12,16,gold);else DrawSphereEx(v(o.state.center_of_mass_world_m),static_cast<float>(o.recipe.radius_m),12,16,tint(o.recipe.material));return;}
    const auto q=o.state.orientation_world;const auto x=q.rotate({1,0,0}),y=q.rotate({0,1,0}),z=q.rotate({0,0,1});
    const float matrix[]{static_cast<float>(x.x),static_cast<float>(x.y),static_cast<float>(x.z),0,static_cast<float>(y.x),static_cast<float>(y.y),static_cast<float>(y.z),0,static_cast<float>(z.x),static_cast<float>(z.y),static_cast<float>(z.z),0,0,0,0,1};
    rlPushMatrix();rlTranslatef(static_cast<float>(o.state.center_of_mass_world_m.x),static_cast<float>(o.state.center_of_mass_world_m.y),static_cast<float>(o.state.center_of_mass_world_m.z));rlMultMatrixf(matrix);
    if(!wire)DrawCubeV({0,0,0},v(o.recipe.dimensions_m),tint(o.recipe.material));DrawCubeWiresV({0,0,0},v(o.recipe.dimensions_m+Vec3{.006,.006,.006}),wire?gold:Color{67,65,53,255});rlPopMatrix();
}
BoundingBox bounds(Vec3 center,Vec3 size){return {v(center-size/2),v(center+size/2)};}
float hit(Ray ray,const StarterObject &o){
    if(o.recipe.shape=="sphere"){const auto h=GetRayCollisionSphere(ray,v(o.state.center_of_mass_world_m),static_cast<float>(o.recipe.radius_m));return h.hit?h.distance:1e9F;}
    const auto q=o.state.orientation_world;const Quat inverse{q.w,-q.x,-q.y,-q.z};
    const Ray local{v(inverse.rotate(v(ray.position)-o.state.center_of_mass_world_m)),v(inverse.rotate(v(ray.direction)))};
    const auto h=GetRayCollisionBox(local,bounds({},o.recipe.dimensions_m));return h.hit?h.distance:1e9F;
}
void scenery(){
    for(int x=-12;x<12;++x)for(int z=-12;z<12;++z){const bool path=std::abs(x)<2&&z>-4&&z<6;const int variation=((x*17+z*31)%7+7)%7;DrawCube({static_cast<float>(x)+.5F,-.14F,static_cast<float>(z)+.5F},1,.28F,1,path?Color{149,127,85,255}:Color{static_cast<unsigned char>(71+variation*3),static_cast<unsigned char>(112+variation*3),65,255});}
    for(int i=0;i<18;++i){const float x=-11+static_cast<float>(i%6)*4.3F,z=i<6?-11.0F:i<12?11.0F:(i%2?-11.5F:11.5F);DrawCube({x,1.4F,z},.55F,2.8F,.55F,{108,76,48,255});DrawCube({x,3,z},2.4F,1.5F,2.2F,{63,107,65,255});DrawCube({x+.3F,4,z+.2F},1.7F,.8F,1.7F,{79,127,72,255});}
    DrawCubeV(v(StarterWorld::treePosition()),{.45F,3,.45F},{105,70,44,255});
    DrawCube({3,3.2F,-2},2.1F,1.2F,2.1F,{73,131,67,255});DrawCube({3.3F,4,-2.2F},1.5F,.8F,1.6F,{97,150,77,255});
    DrawCubeV(v(StarterWorld::benchPosition()),{1.5F,1,.8F},{112,76,48,255});DrawCube({0,1.12F,-2},1.65F,.12F,.94F,{189,143,82,255});
    for(int i=0;i<5;++i)DrawLine3D({-.7F+static_cast<float>(i)*.35F,1.185F,-2.4F},{-.7F+static_cast<float>(i)*.35F,1.185F,-1.6F},{95,64,40,255});
    DrawCube({-1.5F,.16F,-3.5F},1.3F,.32F,.5F,{131,99,62,255}); // Resting log, scenery only.
}
}
int main(int argc,char **argv){try{
    std::filesystem::path workspace="starter-data",capture;std::string layout="clearing";unsigned frames=60;
    for(int i=1;i<argc;++i){const std::string arg=argv[i];if(++i>=argc)throw std::invalid_argument("missing option");if(arg=="--workspace")workspace=argv[i];else if(arg=="--capture")capture=argv[i];else if(arg=="--layout")layout=argv[i];else if(arg=="--frames")frames=static_cast<unsigned>(std::stoul(argv[i]));else throw std::invalid_argument("unknown option");}
    if(frames==0||frames>3600)throw std::invalid_argument("invalid capture frame count");
    if(layout!="clearing"&&layout!="crafting"&&layout!="designer")throw std::invalid_argument("layout must be clearing, crafting or designer");
    std::filesystem::create_directories(workspace);const auto save_path=workspace/"starter-world.json";
    auto world=capture.empty()&&std::filesystem::exists(save_path)?StarterWorld::load(save_path):StarterWorld{};
    if(!capture.empty()&&layout=="crafting"){(void)world.interact("capture-pick",1,{-2.8,1.65,1});(void)world.craft("capture-pry","prybar",{0,1.65,0});}
    SetConfigFlags(FLAG_MSAA_4X_HINT);InitWindow(1440,900,"Banjo - First Person Clearing");SetTargetFPS(60);SetExitKey(KEY_NULL);
    Camera3D camera{{0,1.65F,4.7F},{0,1.25F,-2},{0,1,0},65,CAMERA_PERSPECTIVE};
    float yaw=0,pitch=-.15F;bool crafting=layout!="clearing",inventory=false,paused=false;unsigned selected=0,rendered=0,serial=0;double accumulator=0,save_timer=0;
    if(crafting){camera.position={0,1.65F,.2F};selected=layout=="designer"?6:1;}
    std::string message="Welcome to Willow Clearing. Collect loose wood to begin.";
    CodexAssistant assistant;std::string prompt,submitted_prompt,explanation="Describe a solid ball or block. Custom designs unlock at level 2.";std::optional<ObjectRecipe> proposal;bool prompt_focus=false;
    if(const auto &saved=world.rememberedDesign()){prompt=saved->prompt;explanation=saved->explanation;proposal=saved->recipe;}
    std::future<std::string> test_job;std::string tested_name;std::filesystem::path test_report_path;
    const auto session=std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
    const auto id=[&]{return "play-"+session+"-"+std::to_string(++serial);};
    const auto save=[&]{world.save(save_path);};
    if(capture.empty()&&!crafting)DisableCursor();
    while(!WindowShouldClose()){
        const float dt=std::min(GetFrameTime(),.05F);
        if(capture.empty()){
            // Consume key-down events, including taps released between frames.
            bool control_event=IsKeyDown(KEY_LEFT_CONTROL)||IsKeyDown(KEY_RIGHT_CONTROL);
            for(int key=GetKeyPressed();key;key=GetKeyPressed()) {
                if(key==KEY_LEFT_CONTROL||key==KEY_RIGHT_CONTROL)control_event=true;
                if(crafting&&selected==6&&prompt_focus&&key==KEY_BACKSPACE&&!prompt.empty())prompt.pop_back();
                if(crafting&&selected==6&&prompt_focus&&key==KEY_V&&control_event) {
                    if(const char *paste=GetClipboardText())for(;*paste&&prompt.size()<500;++paste)if(*paste>=32&&*paste<127)prompt+=*paste;
                }
                if(key==KEY_ESCAPE){crafting=false;inventory=false;paused=!paused;if(paused)EnableCursor();else DisableCursor();}
                if(key==KEY_TAB&&!crafting&&!paused){inventory=!inventory;if(inventory)EnableCursor();else DisableCursor();}
                if(key==KEY_HOME){yaw=0;pitch=-.15F;}
            }
            for(int ch=GetCharPressed();ch;ch=GetCharPressed())if(crafting&&selected==6&&prompt_focus&&ch>=32&&ch<127&&prompt.size()<500)prompt+=static_cast<char>(ch);
            if(!crafting&&!inventory&&!paused){
                const auto mouse=GetMouseDelta();yaw+=mouse.x*.0025F;pitch=std::clamp(pitch-mouse.y*.0025F,-1.35F,1.35F);
                Vec3 move{};const Vec3 forward{std::sin(yaw),0,-std::cos(yaw)},right{std::cos(yaw),0,std::sin(yaw)};
                if(IsKeyDown(KEY_W))move+=forward;if(IsKeyDown(KEY_S))move-=forward;if(IsKeyDown(KEY_D))move+=right;if(IsKeyDown(KEY_A))move-=right;
                if(length(move)>0){move=move/length(move)*static_cast<double>(dt)*2.8;auto next=v(camera.position)+move;next.x=std::clamp(next.x,-10.0,10.0);next.z=std::clamp(next.z,-10.0,10.0);
                    const auto blocked=[&](Vec3 p){const Vector2 point{static_cast<float>(p.x),static_cast<float>(p.z)};return CheckCollisionPointRec(point,{-1.07F,-2.71F,2.14F,1.42F})||CheckCollisionPointRec(point,{2.54F,-2.46F,.92F,.92F})||CheckCollisionPointRec(point,{-2.4F,-4.0F,1.8F,1.0F});};
                    if(!blocked(next))camera.position=v(next);
                }
                if(IsKeyDown(KEY_R)){world.rest(dt);message="Resting: stamina recovers. No materials or experience are created.";}
            }
        }
        if(assistant.running())try{if(auto reply=assistant.poll()){
            world.rememberDesignAndSave(save_path,{reply->request_id,submitted_prompt,reply->explanation,reply->recipe});
            prompt=submitted_prompt;proposal=reply->recipe;explanation=reply->explanation;message="Design saved. Collect what is missing, then return to this table.";
        }}catch(const std::exception &e){proposal.reset();explanation=e.what();}
        if(test_job.valid()&&test_job.wait_for(std::chrono::seconds(0))==std::future_status::ready)try{
            const auto document=test_job.get();const auto report=nlohmann::json::parse(document);
            std::ofstream output(test_report_path,std::ios::binary);output<<document;output.close();if(!output)throw std::runtime_error("Cannot save physical test report");
            message="Ramp test of "+tested_name+": "+report.at("status").get<std::string>()+". Travel "+number(report.at("final_travel_m").get<double>(),3)+" m; final slip "+(report.at("final_slip_m_s").is_null()?"no contact":number(report.at("final_slip_m_s").get<double>(),4)+" m/s")+". Isolated 2-second test; no materials spent.";
        }catch(const std::exception &e){message=std::string("Physical test: ")+e.what();}
        const bool modal=crafting||inventory||paused;
        camera.target={camera.position.x+std::sin(yaw)*std::cos(pitch),camera.position.y+std::sin(pitch),camera.position.z-std::cos(yaw)*std::cos(pitch)};
        if(!paused){accumulator+=capture.empty()?dt:1.0/60;while(accumulator>=1.0/240){world.step();accumulator-=1.0/240;}}
        const Ray ray{camera.position,v((v(camera.target)-v(camera.position))/length(v(camera.target)-v(camera.position)))};
        auto benchHit=GetRayCollisionBox(ray,bounds({0,.64,-2},{1.65,1.08,.94}));auto trunkHit=GetRayCollisionBox(ray,bounds(StarterWorld::treePosition(),{.45,3,.45}));
        float distance=benchHit.hit?benchHit.distance:1e9F;bool table=benchHit.hit&&distance<=3.2F;MatterBodyId target=0;
        if(trunkHit.hit&&trunkHit.distance<distance){distance=trunkHit.distance;table=false;}
        for(const auto &o:world.objects())if(!o.collected&&!o.tool){const float d=hit(ray,o);if(d<distance&&d<=3.2F){distance=d;target=o.id;table=false;}}
        if(!modal&&capture.empty()&&IsMouseButtonPressed(MOUSE_BUTTON_LEFT))try{
            if(table){crafting=true;EnableCursor();}else if(target){message=world.interactAndSave(save_path,id(),target,v(camera.position));}
        }catch(const std::exception &e){message=e.what();}
        save_timer+=dt;if(capture.empty()&&save_timer>10){try{save();}catch(const std::exception &e){message=e.what();}save_timer=0;}
        BeginDrawing();ClearBackground({159,199,210,255});BeginMode3D(camera);scenery();for(const auto &o:world.objects())if(!o.collected&&!o.tool){shape(o);if(o.id==target&&!modal)shape(o,true);}
        if(table&&!modal)DrawCubeWiresV({0,.64F,-2},{1.66F,1.09F,.95F},gold);EndMode3D();
        DrawRectangle(0,0,1440,92,{19,33,31,240});text("WILLOW CLEARING",28,20,28);text("BANJO / MATERIAL WORLDS",30,57,15,muted);
        text("LEVEL "+std::to_string(world.level()),900,20,23,gold);text(std::to_string(world.xp()%20)+" / 20 XP to next level",900,52,17,muted);
        DrawRectangle(1210,24,196,16,{63,76,65,255});DrawRectangle(1210,24,static_cast<int>(world.stamina()*1.96),16,green);text("Stamina "+number(world.stamina(),0)+" / 100",1210,52,17);
        if(!modal){DrawRectangle(24,112,405,108,{20,34,30,220});text("YOUR NEXT STEP",42,128,18,gold);wrap(world.equippedTool()=="None"?"Gather loose wood, then visit the crafting table to make a pry tool.":world.equippedTool()=="Wooden pry tool"?"Gather iron and reach level 2. Craft the cutting tool at the table.":"Use your cutting tool on the attached branch. Collect it after it falls.",42,160,365,18,ink);}
        if(!crafting&&!inventory&&!paused){DrawLine(712,450,728,450,ink);DrawLine(720,442,720,458,ink);
            std::string hint=table?"Click: open crafting table":target?"Click: collect / cut   |   reach 3.2 m":"Explore the clearing";
            DrawRectangle(385,650,670,44,{20,34,30,220});text(hint,407,663,19);
        }
        DrawRectangle(24,739,1392,137,{20,34,30,238});wrap(message,44,756,1320,20,ink);
        text("WASD move   Mouse look   Click interact   TAB inventory   Hold R rest   ESC pause",44,805,18,muted);
        text("Tool: "+world.equippedTool()+"   |   Gathering: "+number(world.gatheringCost(),1)+" stamina",44,841,17,gold);
        if(crafting||inventory){
            DrawRectangle(24,112,1392,607,panel);text(crafting?"CRAFTING TABLE":"YOUR INVENTORY",48,134,28,gold);
            text("Raw voxel materials / 1 cm cells",1000,145,18,muted);int y=195;
            for(auto m:{MaterialPreset::Oak,MaterialPreset::Iron,MaterialPreset::Glass}){DrawRectangle(1000,y,32,32,tint(m));text(std::string(materialPresetName(m)),1046,y,22);text(number(world.inventoryKg(m),3)+" kg",1046,y+34,20);text(number(world.inventoryVoxels(m),0)+" voxel equivalents",1046,y+64,16,muted);y+=119;}
            wrap("Tools are carried in inventory. Your body and hands are never drawn.",1000,578,345,18,muted);
            if(crafting){const auto designs=StarterWorld::designs();for(unsigned i=0;i<designs.size();++i){const auto &d=designs[i];const auto q=world.quote(d.id);Rectangle card{48,static_cast<float>(187+i*72),345,64};DrawRectangleRec(card,i==selected?Color{65,87,65,255}:Color{36,51,44,255});text(d.label,63,static_cast<int>(card.y)+10,20);text(q.ready()?"Ready to craft":"Requirements missing",63,static_cast<int>(card.y)+37,15,q.ready()?green:muted);if(IsMouseButtonPressed(MOUSE_BUTTON_LEFT)&&CheckCollisionPointRec(GetMousePosition(),card))selected=i;}
                if(button({48,619,345,64},"ASK THE DESIGNER")){selected=6;prompt_focus=false;}
                if(selected==6){
                    text("Make something from your materials",432,200,23);
                    Rectangle input{432,240,490,80};DrawRectangleRec(input,{36,51,44,255});DrawRectangleLinesEx(input,1,prompt_focus?gold:muted);
                    wrap(prompt.empty()?"Click here and describe your design...":prompt,444,250,465,17,ink);
                    if(IsMouseButtonPressed(MOUSE_BUTTON_LEFT))prompt_focus=CheckCollisionPointRec(GetMousePosition(),input);
                    if(button({432,335,235,43},assistant.running()?"DESIGNING...":"ASK DESIGNER",!assistant.running()&&!prompt.empty()&&assistant.available()))try{proposal.reset();explanation="Checking your request...";const auto request=id();submitted_prompt=prompt;assistant.start(workspace,request,world.designerRequest(request,submitted_prompt));}catch(const std::exception &e){explanation=e.what();}
                    if(button({687,335,235,43},"CANCEL",assistant.running())){assistant.cancel();proposal.reset();explanation="Request canceled. No resources spent.";}
                    wrap(proposal?"Original note: "+explanation:assistant.available()?explanation:"Codex is unavailable. Saved designs can still be built.",432,391,490,17,muted);
                    if(proposal)try{const auto q=world.quoteRecipe(*proposal);
                        text(proposal->shape=="sphere"?"Sphere diameter: "+number(2*proposal->radius_m,3)+" m":"Box: "+number(proposal->dimensions_m.x,3)+" x "+number(proposal->dimensions_m.y,3)+" x "+number(proposal->dimensions_m.z,3)+" m",432,456,17,gold);
                        text(std::string(materialPresetName(proposal->material))+": need "+number(q.required_kg,3)+" kg / held "+number(q.held_kg,3),432,483,18);
                        text("Level "+std::to_string(q.level)+" / stamina "+number(q.stamina,1)+" / missing "+number(q.missing_kg,3)+" kg",432,515,17);
                        if(!q.missing.empty())wrap(q.missing.front(),432,548,490,16,gold);
                        if(button({432,592,490,48},"BUILD REVIEWED DESIGN",q.ready()))try{message=world.craftRecipeAndSave(save_path,id(),*proposal,v(camera.position));}catch(const std::exception &e){message=e.what();}
                        if(button({432,654,490,43},test_job.valid()?"TESTING...":"TEST ON 10 DEGREE RAMP",!test_job.valid())){
                            const auto tested=*proposal;tested_name=tested.name;test_report_path=workspace/("test-"+id()+".json");
                            const nlohmann::json test{{"test_version",1},{"fixture","concrete-incline-v1"},{"ticks",480},{"slope_degrees",10},{"minimum_travel_m",.3},{"maximum_final_slip_m_s",.02},{"require_rolling",tested.shape=="sphere"}};
                            test_job=std::async(std::launch::async,[tested,spec=test.dump()]{return CreatorWorld::testRecipeJson(tested,spec);});message="Testing a virtual copy on a 10-degree concrete incline. Live resources are unchanged.";
                        }
                    }catch(const std::exception &e){wrap(e.what(),432,483,490,17,gold);}
                }else{
                const auto &d=designs[selected];const auto q=world.quote(d.id);text(d.label,432,200,27);wrap(d.description,432,244,510,20);text("Requires level "+std::to_string(q.level)+"  /  Your level "+std::to_string(world.level()),432,320,20,q.level>world.level()?gold:ink);
                text("Material: "+std::string(materialPresetName(d.recipe.material)),432,367,20);text("Need "+number(q.required_kg,3)+" kg   /   Have "+number(q.held_kg,3)+" kg",432,403,20);
                text("Missing: "+number(q.missing_kg,3)+" kg",432,439,20,q.missing_kg>1e-12?gold:green);text("Crafting stamina: "+number(q.stamina,0),432,485,20);
                if(!q.missing.empty())wrap(q.missing.front(),432,528,510,18,gold);
                if(button({432,592,490,48},q.ready()?"CRAFT AND USE MATERIALS":"NOT READY - SEE REQUIREMENTS",q.ready()))try{message=world.craftAndSave(save_path,id(),d.id,v(camera.position));}catch(const std::exception &e){message=e.what();}
                }
            }else{wrap("Click loose material to bring its substance and volume into inventory. Craft a wooden pry tool first, then gather iron and reach level 2 for the cutting tool. Cut the attached branch, let gravity drop it, and collect the wood.",64,220,800,24);text("Gathering costs "+number(world.gatheringCost(),1)+" stamina per pickup",64,425,23,green);}
            if(button({1190,654,195,43},"BACK TO WORLD")){crafting=false;inventory=false;if(capture.empty())DisableCursor();}
        }
        if(paused){DrawRectangle(400,250,640,340,panel);text("PAUSED",440,286,34,gold);wrap("A first-person starter world. Stamina and XP are game rules. Branch cutting currently releases a whole rigid branch; realistic grain, bending and fracture are still being developed.",440,344,560,21);if(button({440,502,560,48},"RESUME")){paused=false;DisableCursor();}}
        text("Prototype: gameplay stamina; whole-branch cutting approximation. Physical fabrication energy is not modeled.",25,881,14,muted);
        EndDrawing();if(!capture.empty()&&++rendered>=frames){TakeScreenshot(capture.string().c_str());break;}
    }
    assistant.cancel();if(capture.empty())save();EnableCursor();CloseWindow();return 0;
}catch(const std::exception &e){std::cerr<<"Starter error: "<<e.what()<<'\n';return 1;}}
