#include "platform/PlatformWorld.hpp"
#include <raylib.h>
#include <rlgl.h>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <algorithm>
#include <map>
#include <set>

using namespace banjo;
namespace {
Vector3 v(Vec3 p){return {float(p.x),float(p.y),float(p.z)};}
Color tint(MaterialPreset m){return m==MaterialPreset::Glass?Color{99,222,228,255}:m==MaterialPreset::Oak?Color{221,165,92,255}:Color{163,181,203,255};}
bool button(int y,const char *label){Rectangle r{1000,float(y),330,34};bool hover=CheckCollisionPointRec(GetMousePosition(),r);DrawRectangleRec(r,hover?Color{65,91,101,255}:Color{37,60,72,255});DrawText(label,1012,y+9,16,RAYWHITE);return hover&&IsMouseButtonPressed(MOUSE_BUTTON_LEFT);}
void drawBody(const PlatformInstance &o,bool structure){
    const auto p=o.state.center_of_mass_world_m;const auto color=tint(o.material);
    if(o.geometry.kind==PrimitiveKind::Sphere){if(structure)DrawSphereWires(v(p),float(o.geometry.radius_m),8,12,color);else DrawSphere(v(p),float(o.geometry.radius_m),color);
        DrawLine3D(v(p),v(p+o.state.orientation_world.rotate({o.geometry.radius_m,0,0})),RAYWHITE);return;}
    auto q=o.state.orientation_world;double angle=2*std::acos(std::clamp(q.w,-1.,1.));Vec3 axis=normalized(Vec3{q.x,q.y,q.z});
    rlPushMatrix();rlTranslatef(float(p.x),float(p.y),float(p.z));rlRotatef(float(angle*180/3.141592653589793),float(axis.x),float(axis.y),float(axis.z));
    if(!structure)DrawCubeV({0,0,0},v(o.geometry.dimensions_m),color);DrawCubeWiresV({0,0,0},v(o.geometry.dimensions_m),structure?color:Color{42,59,65,255});rlPopMatrix();
}
}
int main(int argc,char **argv){try{
    using json=nlohmann::json;
    const std::filesystem::path directory=argc>1?argv[1]:"assets/runtime-v1";
    std::vector<std::filesystem::path> files;for(auto &e:std::filesystem::directory_iterator(directory))if(e.path().extension()==".json")files.push_back(e.path());
    std::sort(files.begin(),files.end());if(files.empty())throw std::runtime_error("No runtime v1 test packages");
    unsigned selected=2;selected=std::min(selected,unsigned(files.size()-1));
    if(argc>2){auto it=std::find_if(files.begin(),files.end(),[&](auto &p){return p.filename()==argv[2];});if(it==files.end())throw std::runtime_error("Unknown v1 test");selected=unsigned(it-files.begin());}
    std::unique_ptr<PlatformWorld> world;json report,package;std::vector<PlatformInstance> instances;
    bool running=false,structure=false,slow=false;double accumulator=0,time=0,refresh=0,lastStep=0,lag=0;unsigned frames=0;std::string notice="Ready. Release to run live.";
    Camera3D camera{{1.8F,1.5F,2.6F},{0,.45F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
    auto load=[&]{std::ifstream f(files[selected]);if(!f||std::filesystem::file_size(files[selected])>4194304)throw std::runtime_error("Cannot read bounded package");
        std::string source((std::istreambuf_iterator<char>(f)),{});auto next=PlatformWorld::load(source);package=json::parse(next->packageJson());
        if(package["backend"]!="compiled-impact-v1")throw std::runtime_error("This lab requires the compiled live backend");world=std::move(next);
        report=json::parse(world->reportJson());instances=world->renderInstances();running=false;accumulator=0;time=0;refresh=0;lastStep=0;lag=0;frames=0;notice="Ready. Release to run live.";
        double height=0;for(auto &o:package["objects"])height=std::max(height,o["position_m"][1].get<double>());
        camera={{1.8F,1.5F,2.6F},{0,.45F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
        if(height>2)camera={{2.7F,2.2F,4.2F},{0,1.15F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
        if(!package["bowl"].is_null())camera={{2.3F,2.3F,2.8F},{0,.15F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
        if(package["objects"].size()>12)camera={{3,3,4},{0,.6F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
    };load();
    SetConfigFlags(FLAG_MSAA_4X_HINT);InitWindow(1360,850,"Banjo - Live Material Runtime v1");SetTargetFPS(60);
    RenderTexture2D viewport=LoadRenderTexture(980,600);
    auto advance=[&](unsigned steps){for(unsigned i=0;i<steps&&time<3-1e-9;++i){auto s=world->step();lastStep=s.wall_ms;time=s.elapsed_s;if(!s.error.empty()){notice=s.error;running=false;break;}}
        instances=world->renderInstances();};
    while(!WindowShouldClose()){
        const double frame=GetFrameTime();refresh+=frame;++frames;
        if(running){accumulator+=frame*(slow?.25:1.);unsigned steps=0;while(accumulator>=world->fixedStep()&&steps<24){advance(1);accumulator-=world->fixedStep();++steps;if(!running)break;}
            lag=accumulator;if(lag>.25){running=false;notice="Frame budget exceeded. Paused; report retains the backlog.";}
            if(time>=3-1e-9){running=false;notice="3-second live trial complete. Reset for another run.";}}
        if(refresh>.2){report=json::parse(world->reportJson());refresh=0;}
        const float wheel=GetMouseWheelMove();if(wheel!=0){const float scale=std::clamp(1-wheel*.12F,.5F,2.F);Vector3 d{camera.position.x-camera.target.x,camera.position.y-camera.target.y,camera.position.z-camera.target.z};
            float length=std::sqrt(d.x*d.x+d.y*d.y+d.z*d.z);if(length*scale>.35&&length*scale<30)camera.position={camera.target.x+d.x*scale,camera.target.y+d.y*scale,camera.target.z+d.z*scale};}
        BeginTextureMode(viewport);ClearBackground({13,23,30,255});BeginMode3D(camera);DrawGrid(16,.25F);
        for(auto &t:world->supportMesh()){DrawTriangle3D(v(t[0]),v(t[1]),v(t[2]),{45,66,75,255});DrawTriangle3D(v(t[2]),v(t[1]),v(t[0]),{36,53,62,255});}
        for(auto &o:instances)drawBody(o,structure);
        if(structure)for(auto &b:world->renderBonds())DrawLine3D(v(b.a),v(b.b),b.live?Color{150,219,204,255}:Color{255,108,106,255});
        EndMode3D();EndTextureMode();
        BeginDrawing();ClearBackground({13,23,30,255});DrawTextureRec(viewport.texture,{0,0,980,-600},{0,115},WHITE);DrawRectangle(980,0,380,850,{23,38,48,255});
        DrawText("BANJO / LIVE MATERIAL RUNTIME",28,22,27,{207,237,135,255});DrawText(package["name"].get<std::string>().c_str(),28,66,21,RAYWHITE);
        DrawText("GLASS",28,705,16,tint(MaterialPreset::Glass));DrawText("WOOD",118,705,16,tint(MaterialPreset::Oak));DrawText("IRON",208,705,16,tint(MaterialPreset::Iron));
        DrawText(TextFormat("%.3f s   |   %u broken bonds   |   %u visible elements",time,world->fractureCount(),unsigned(instances.size())),28,734,20,RAYWHITE);
        DrawText(notice.c_str(),28,770,17,{207,237,135,255});DrawText("Actual live physics. Space: release/pause. Wheel: zoom. Arrows: experiment.",28,805,16,{148,177,191,255});
        DrawText(TextFormat("V1 TEST %u / %u",selected+1,unsigned(files.size())),1000,24,22,RAYWHITE);
        if(button(65,running?"Pause":"Release / continue")||IsKeyPressed(KEY_SPACE)){if(time>=3-1e-9)load();running=!running;accumulator=0;notice=running?"Simulating live; no precomputed trajectory.":"Paused. Step a frame or continue.";}
        if(button(107,"Reset initial state")||IsKeyPressed(KEY_R))load();
        if(button(149,"Next experiment")||IsKeyPressed(KEY_RIGHT)){selected=(selected+1)%unsigned(files.size());load();}
        if(button(191,"Previous experiment")||IsKeyPressed(KEY_LEFT)){selected=(selected+unsigned(files.size())-1)%unsigned(files.size());load();}
        if(button(233,structure?"Structure: ON":"Structure: OFF"))structure=!structure;
        if(button(275,slow?"Speed: 0.25x (inspection)":"Speed: 1x (live)"))slow=!slow;
        if(button(317,"Step one frame (paused)")){running=false;advance(unsigned(std::round(1./60/world->fixedStep())));report=json::parse(world->reportJson());}
        DrawText("MEASURED THIS RUN",1000,376,18,{207,237,135,255});
        auto perf=report["performance"];
        DrawText(TextFormat("Physics step p95: %.3f ms",perf.value("step_p95_ms",0.)),1000,409,17,RAYWHITE);
        DrawText(TextFormat("Peak step: %.3f ms",perf.value("step_max_ms",0.)),1000,437,17,RAYWHITE);
        DrawText(TextFormat("Local pulse solves: %u",report.value("local_solves",0u)),1000,465,17,RAYWHITE);
        DrawText(TextFormat("Connected bodies: %u",report.value("connected_components",0u)),1000,493,17,RAYWHITE);
        DrawText(TextFormat("Fracture work: %.4f J",report.value("fracture_work_j",0.)),1000,521,17,RAYWHITE);
        DrawText(TextFormat("Budget-limited impacts: %u",report.value("budget_limited_impacts",0u)),1000,549,17,RAYWHITE);
        DrawText("Approximate brittle fracture model",1000,591,16,{230,179,114,255});DrawText("Wood / iron: rigid response only",1000,616,16,{164,183,197,255});
        DrawText("Green intact / red failed connections",1000,647,15,{164,183,197,255});DrawText("No grain, plasticity or live save yet",1000,671,15,{164,183,197,255});
        if(button(710,"Export full report")){auto r=json::parse(world->reportJson());r["presentation"]={{"mode","live"},{"time_scale",slow?.25:1.},{"backlog_s",lag},{"rendered_frames",frames}};std::ofstream f("build/runtime-v1-report.json");f<<r.dump(2);notice=f?"Saved build/runtime-v1-report.json":"Report write failed";}
        if(button(752,"Save screenshot")){rlDrawRenderBatchActive();Image image=LoadImageFromScreen();ExportImage(image,"build/runtime-v1-lab.png");UnloadImage(image);notice="Saved build/runtime-v1-lab.png";}
        DrawFPS(1000,810);EndDrawing();
    }
    UnloadRenderTexture(viewport);CloseWindow();return 0;
}catch(const std::exception &e){TraceLog(LOG_ERROR,"%s",e.what());return 1;}}
