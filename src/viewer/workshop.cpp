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
}
int main(int argc,char **argv) {
    try {
        std::filesystem::path workspace=std::filesystem::absolute(argv[0]).parent_path()/"workshop-data",capture;unsigned frames=180;
        std::filesystem::path assistant_exe=ChildProcess::findExecutable("codex");bool manual_assistant=false,shape_capture=false;
        for(int i=1;i<argc;++i) {
            const std::string option=argv[i];if(++i>=argc)throw std::invalid_argument("missing workshop option value");
            if(option=="--workspace")workspace=argv[i];else if(option=="--capture")capture=argv[i];
            else if(option=="--assistant-exe")assistant_exe=std::filesystem::absolute(argv[i]);
            else if(option=="--capture-layout") {const std::string layout=argv[i];if(layout!="materials"&&layout!="shapes")throw std::invalid_argument("capture layout must be materials or shapes");shape_capture=layout=="shapes";}
            else if(option=="--assistant") {const std::string mode=argv[i];if(mode!="auto"&&mode!="manual")throw std::invalid_argument("assistant must be auto or manual");manual_assistant=mode=="manual";}
            else if(option=="--frames")frames=static_cast<unsigned>(std::stoul(argv[i]));else throw std::invalid_argument("unknown workshop option");
        }
        if(frames==0||frames>3600)throw std::invalid_argument("capture frames must be 1–3600");
        std::filesystem::create_directories(workspace);workspace=std::filesystem::absolute(workspace);
        auto world=capture.empty()&&std::filesystem::exists(workspace/"world.json")?CreatorWorld::load(workspace/"world.json"):CreatorWorld{};
        CodexAssistant assistant(assistant_exe);
        const bool automatic_assistant=!manual_assistant&&assistant.available();
        ObjectRecipe draft;std::string prompt="Use some of my wood to make a ball that rolls down this ramp.";
        std::string status="Collect a material, then design an object.",request_id,pending_id,proposal_message;
        bool paused=capture.empty(),typing=false,built=false,follow=false;double accumulator=0,poll_at=0;unsigned rendered=0,serial=0;
        unsigned dimension_axis=0,orientation_preset=0;
        const auto session=std::to_string(std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
        const auto new_id=[&]{return "workshop-"+session+"-"+std::to_string(++serial);};request_id=new_id();
        const auto save=[&]{if(capture.empty())world.save(workspace/"world.json");};
        if(!capture.empty()) {
            for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
                world.collect(std::string(materialPresetName(m))+"-pile");auto r=draft;r.material=m;
                r.bitangent_m=.45*(static_cast<double>(world.objects().size())-(shape_capture?2.5:1));
                if(shape_capture)r.radius_m=.04;
                (void)world.create(std::string(materialPresetName(m))+"-capture",r);
                if(shape_capture) {
                    const double volume=r.geometry().volume();r.shape="box";r.schema_version=2;r.name=name(m)+" box";
                    r.dimensions_m={.08,.06,volume/(.08*.06)};r.orientation_world=tilt(-world.settings().slope_degrees);r.bitangent_m+=.45;
                    (void)world.create(std::string(materialPresetName(m))+"-box-capture",r);
                }
            }
            draft=world.objects().back().recipe;request_id=world.objects().back().request_id;
            built=true;status=shape_capture?"Equal-volume sphere/box pairs in glass, oak and iron. Same ramp, zero initial motion.":"Three materials, one creation path. Motion comes from contact and gravity.";
        }
        SetConfigFlags(FLAG_MSAA_4X_HINT);InitWindow(1440,900,"Banjo - Material Workshop");SetTargetFPS(60);
        SetExitKey(KEY_NULL);
        Camera3D camera{{1.4F,2.2F,3.7F},{-1.3F,.3F,0},{0,1,0},45,CAMERA_PERSPECTIVE};
        double yaw=.72,pitch=.4,distance=4.8;
        while(!WindowShouldClose()) {
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
            if(follow&&!world.objects().empty())camera.target=v(world.objects().back().state.center_of_mass_world_m);
            camera.position={camera.target.x+static_cast<float>(distance*std::cos(pitch)*std::sin(yaw)),camera.target.y+static_cast<float>(distance*std::sin(pitch)),camera.target.z+static_cast<float>(distance*std::cos(pitch)*std::cos(yaw))};
            if(!pending_id.empty()&&GetTime()>poll_at) {
                poll_at=GetTime()+.5;const auto path=workspace/("proposal-"+pending_id+".json");
                if(automatic_assistant)try {
                    if(auto reply=assistant.poll()) {
                        if(reply->recipe) {
                            (void)world.preview(*reply->recipe);draft=*reply->recipe;request_id=pending_id;built=false;
                            status="Assistant proposal ready. Review the cost, then build.";
                        }else status="The assistant needs a different choice. Update your request below.";
                        proposal_message=reply->explanation;pending_id.clear();paused=true;
                    }
                }catch(const std::exception &e){status=e.what();pending_id.clear();assistant.cancel();paused=true;}
                else if(std::filesystem::exists(path))try {
                    auto proposal=CreatorWorld::parseProposal(read(path));if(proposal.request_id!=pending_id)throw std::invalid_argument("AI response belongs to another request");
                    (void)world.preview(proposal.recipe);draft=proposal.recipe;request_id=pending_id;pending_id.clear();built=false;
                    proposal_message=proposal.explanation;status="AI proposal ready. Review its material cost, then build.";paused=true;
                }catch(const std::exception &e){status=std::string("Proposal needs revision: ")+e.what();}
            }
            std::optional<CreationPreview> preview;std::string problem;
            try {preview=world.preview(draft);}catch(const std::exception &e){problem=e.what();}
            BeginDrawing();ClearBackground(background);BeginMode3D(camera);
            rlPushMatrix();rlRotatef(static_cast<float>(-world.settings().slope_degrees),0,0,1);rlTranslatef(0,-.1F,0);
            DrawCube({0,0,0},16,.2F,6,{69,83,88,255});DrawCubeWires({0,0,0},16,.2F,6,{103,119,124,255});rlPopMatrix();
            const auto plane=world.support();
            for(int i=-8;i<=8;++i)DrawLine3D(v(pointInPlaneFrame(plane,i,-3,.001)),v(pointInPlaneFrame(plane,i,3,.001)),{83,99,105,255});
            for(const auto &object:world.objects())drawObject(object.recipe,object.state.center_of_mass_world_m,object.state.orientation_world,color(object.recipe.material));
            if(preview&&!built)drawObject(draft,preview->position_world_m,draft.orientation_world,accent,true);
            for(std::size_t i=0;i<world.lots().size();++i)if(!world.lots()[i].collected) {
                const auto &lot=world.lots()[i];const double size=std::cbrt(lot.remaining_mass_kg/makeReferenceMaterial(lot.material).density_kg_m3);
                DrawCubeV(v(pointInPlaneFrame(plane,-2.7,.45*(static_cast<double>(i)-1),size/2)),{static_cast<float>(size),static_cast<float>(size),static_cast<float>(size)},color(lot.material));
            }
            EndMode3D();
            DrawRectangle(0,0,1440,100,background);DrawText("BANJO / MATERIAL WORKSHOP",24,22,30,ink);
            DrawText("Collect. Describe. Build. Try it.",26,62,19,muted);
            DrawText((fixed(world.timeSeconds(),2)+" s").c_str(),1200,30,22,muted);
            DrawRectangleRounded({18,114,288,748},.035F,8,panel);DrawText("YOUR MATERIALS",36,135,20,accent);
            for(std::size_t i=0;i<world.lots().size()&&i<3;++i) {
                const auto &lot=world.lots()[i];const int y=180+static_cast<int>(i)*140;
                DrawCircle(48,y+12,9,color(lot.material));DrawText(name(lot.material).c_str(),69,y,22,ink);
                DrawText((fixed(lot.remaining_mass_kg)+" kg "+(lot.collected?"available":"in the world")).c_str(),38,y+32,17,muted);
                if(button({36,static_cast<float>(y+65),248,40},lot.collected?"Collected":"Collect material",!lot.collected))try {world.collect(lot.id);save();status="Material collected. Your inventory is ready.";}catch(const std::exception &e){status=e.what();}
            }
            wrap("Material keeps its identity. The object compiler calculates how much your design needs.",36,635,245);
            DrawText("SUPPORTED NOW",36,751,17,accent);wrap("Rigid spheres and boxes. No deformation or fracture.",36,780,242,17);
            DrawRectangleRounded({1092,114,330,748},.035F,8,panel);DrawText("OBJECT PREVIEW",1110,135,20,accent);
            DrawText(draft.name.substr(0,24).c_str(),1110,173,22,ink);
            const auto edit=[&]{assistant.cancel();pending_id.clear();request_id=new_id();built=false;proposal_message.clear();status="Design updated. Review the material cost before building.";};
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
                const auto found=std::find_if(world.objects().begin(),world.objects().end(),[&](const auto &o){return o.request_id==request_id;});
                if(found!=world.objects().end())DrawText(("Built with "+fixed(found->mass_kg)+" kg").c_str(),1110,468,22,ink);
                DrawText(("Available "+fixed(world.inventoryMass(draft.material))+" kg").c_str(),1110,500,18,muted);
            } else if(preview) {
                DrawText(("Uses "+fixed(preview->mass_kg)+" kg").c_str(),1110,468,22,ink);
                DrawText(("Leaves "+fixed(world.inventoryMass(draft.material)-preview->mass_kg)+" kg").c_str(),1110,500,18,muted);
            } else if(!built)wrap(problem,1110,464,288,17,{237,189,137,255});
            if(button({1110,548,292,48},built?"Object created":"Build this object",preview.has_value()&&!built&&pending_id.empty(),true))try {
                (void)world.create(request_id,draft);built=true;paused=true;save();status="Created from your inventory. Press Run to test it.";
            }catch(const std::exception &e){status=e.what();}
            if(button({1110,614,140,40},paused?"Run":"Pause"))paused=!paused;
            if(button({1262,614,140,40},"Step")){paused=true;world.step();}
            if(button({1110,669,292,38},"Save world"))try{save();status="Inventory, object recipes and motion saved.";}catch(const std::exception &e){status=e.what();}
            if(!world.objects().empty()) {
                const auto motion=measureCreatorMotion(world.objects().back(),plane);
                DrawText(("Last object: "+motion.state).c_str(),1110,739,17,ink);
                DrawText((motion.near_support_points?"Slip "+fixed(motion.slip_m_s)+" m/s":"Slip: no top-support sample").c_str(),1110,769,17,muted);
                DrawText(("Speed "+fixed(motion.speed_m_s)+" m/s").c_str(),1110,797,17,muted);
            }
            DrawRectangleRounded({324,681,750,181},.035F,8,panel);
            DrawRectangleRounded({330,700,725,76},.1F,5,typing?Color{47,60,67,255}:Color{37,48,55,255});wrap(prompt,345,714,690,18,ink);
            if(button({340,795,190,42},"Ask assistant",!prompt.empty()&&pending_id.empty(),true))try {
                pending_id=new_id();typing=false;
                if(automatic_assistant) {
                    assistant.start(workspace,pending_id,CodexAssistant::requestDocument(world,pending_id,prompt,draft,proposal_message));
                    status="The assistant is designing from your collected materials...";proposal_message.clear();
                }else {
                const auto request=Json{{"request_id",pending_id},{"prompt",prompt},{"world",Json::parse(world.inspectJson())},
                    {"example_recipe",Json::parse(CreatorWorld::recipeJson(draft))},
                    {"response_file",("proposal-"+pending_id+".json")},
                    {"instruction","Return request_id, explanation and a supported recipe. Use only collected materials. Do not invent capabilities or quantities. The application will validate and preview before creation."}};
                write(workspace/("request-"+pending_id+".json"),request);status="AI request saved in the workshop folder. Awaiting an assistant proposal.";
                proposal_message="Manual bridge: an assistant reads the request file and returns a proposal. For automatic replies, install/sign in to the Codex CLI and reopen the workshop.";
                }
            }catch(const std::exception &e){pending_id.clear();status=e.what();}
            if(button({545,795,175,42},"Cancel request",!pending_id.empty())) {assistant.cancel();pending_id.clear();proposal_message.clear();status="Request cancelled. No material was spent.";}
            DrawText(("Objects: "+std::to_string(world.objects().size())+" / 64").c_str(),852,807,17,muted);
            wrap(status,330,122,735,19,ink);
            DrawText(automatic_assistant?"Assistant: Codex (automatic)":"Assistant: manual file bridge",330,179,17,accent);
            if(!proposal_message.empty())wrap(proposal_message,330,212,730,17,muted);
            if(button({330,590,180,34},follow?"Following object":"Follow object",!world.objects().empty()))follow=!follow;
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
