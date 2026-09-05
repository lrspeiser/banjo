#include "platform/PlatformWorld.hpp"
#include <raylib.h>
#include <rlgl.h>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <future>
#include <algorithm>
using namespace banjo;
namespace {
Vector3 v(Vec3 p){return {float(p.x),float(p.y),float(p.z)};}
Color color(MaterialPreset m){return m==MaterialPreset::Glass?Color{95,209,217,255}:m==MaterialPreset::Oak?Color{222,165,90,255}:Color{162,176,199,255};}
bool button(int y,const char *label){Rectangle r{980,float(y),350,32};bool hover=CheckCollisionPointRec(GetMousePosition(),r);DrawRectangleRec(r,hover?Color{63,83,90,255}:Color{40,57,65,255});DrawText(label,991,y+8,16,RAYWHITE);return hover&&IsMouseButtonPressed(MOUSE_BUTTON_LEFT);}
}
int main(int argc,char **argv){try{
    const std::filesystem::path directory=argc>1?argv[1]:"assets/platform";
    std::vector<std::filesystem::path> files;for(auto &entry:std::filesystem::directory_iterator(directory))if(entry.path().extension()==".json")files.push_back(entry.path());std::sort(files.begin(),files.end());if(files.empty())throw std::runtime_error("no scene packages");
    std::unique_ptr<PlatformWorld> world;std::vector<PlatformInstance> instances;std::vector<std::array<Vec3,3>> triangles;
    std::future<PlatformStep> job;std::size_t selected=0;bool running=false,reference=false;double accumulator=0,time=0,lastStep=0;std::string message;unsigned broken=0,referenceBatch=1;
    if(argc>2){auto chosen=std::find_if(files.begin(),files.end(),[&](auto &p){return p.filename()==argv[2];});if(chosen==files.end())throw std::runtime_error("requested example missing");selected=std::size_t(chosen-files.begin());}
    auto load=[&]{if(job.valid())job.get();running=false;accumulator=0;time=0;broken=0;std::ifstream f(files[selected]);if(std::filesystem::file_size(files[selected])>4194304)throw std::runtime_error("package too large");std::string source((std::istreambuf_iterator<char>(f)),{});auto candidate=PlatformWorld::load(source);auto definition=nlohmann::json::parse(candidate->packageJson());reference=definition["backend"]=="bonded-reference-v2";referenceBatch=std::min(24u,definition["max_steps_per_call"].get<unsigned>());world=std::move(candidate);instances=world->renderInstances();triangles=world->supportMesh();message=reference?"Detailed reference: slower than real time":"Live rigid runtime: fracture unsupported";};load();
    SetConfigFlags(FLAG_MSAA_4X_HINT);InitWindow(1360,850,"Banjo - Platform Test Laboratory");SetTargetFPS(60);
    RenderTexture2D viewport=LoadRenderTexture(960,570);
    Camera3D camera{{3.2F,3.1F,3.6F},{0,.25F,0},{0,1,0},40,CAMERA_PERSPECTIVE};
    while(!WindowShouldClose()){
        const float wheel=GetMouseWheelMove();if(wheel!=0){float factor=std::clamp(1-wheel*.1F,.5F,2.F);Vector3 d{camera.position.x-camera.target.x,camera.position.y-camera.target.y,camera.position.z-camera.target.z};float distance=std::sqrt(d.x*d.x+d.y*d.y+d.z*d.z);if(distance*factor>1&&distance*factor<30)camera.position={camera.target.x+d.x*factor,camera.target.y+d.y*factor,camera.target.z+d.z*factor};}

        if(job.valid()&&job.wait_for(std::chrono::seconds(0))==std::future_status::ready){auto r=job.get();time=r.elapsed_s;lastStep=r.wall_ms;instances=world->renderInstances();broken=world->fractureCount();if(!r.error.empty()){message=r.error;running=false;}}
        if(running&&!job.valid()){
            if(reference)job=std::async(std::launch::async,[&]{return world->step(referenceBatch);});
            else {accumulator+=std::min(double(GetFrameTime()),.1);unsigned steps=0;while(accumulator>=world->fixedStep()&&steps++<24){auto r=world->step();time=r.elapsed_s;lastStep=r.wall_ms;accumulator-=world->fixedStep();if(!r.error.empty()){message=r.error;running=false;break;}}instances=world->renderInstances();}
        }
        BeginTextureMode(viewport);ClearBackground({15,24,30,255});
        BeginMode3D(camera);DrawGrid(12,.5F);
        for(auto &t:triangles){DrawTriangle3D(v(t[0]),v(t[1]),v(t[2]),{61,85,91,255});DrawTriangle3D(v(t[2]),v(t[1]),v(t[0]),{37,53,60,255});}
        for(auto &o:instances){const auto p=o.state.center_of_mass_world_m;auto tint=color(o.material);if(o.geometry.kind==PrimitiveKind::Sphere){DrawSphere(v(p),float(o.geometry.radius_m),tint);auto pole=o.state.orientation_world.rotate({o.geometry.radius_m,0,0});DrawLine3D(v(p),v(p+pole),WHITE);}else {auto q=o.state.orientation_world;double angle=2*std::acos(std::clamp(q.w,-1.,1.));Vec3 axis=normalized(Vec3{q.x,q.y,q.z});if(lengthSquared(axis)<1e-12)axis={0,1,0};rlPushMatrix();rlTranslatef(float(p.x),float(p.y),float(p.z));rlRotatef(float(angle*180/3.141592653589793),float(axis.x),float(axis.y),float(axis.z));DrawCubeV({0,0,0},v(o.geometry.dimensions_m),tint);DrawCubeWiresV({0,0,0},v(o.geometry.dimensions_m),{35,43,48,255});rlPopMatrix();}}
        EndMode3D();EndTextureMode();BeginDrawing();ClearBackground({15,24,30,255});DrawTextureRec(viewport.texture,{0,0,960,-570},{0,155},WHITE);DrawRectangle(960,0,400,850,{25,39,47,255});
        DrawText("BANJO / PLATFORM LAB",30,26,27,{203,232,126,255});DrawText("Scene packages -> physics runtime -> render instances",30,63,18,{164,186,197,255});
        DrawText(files[selected].stem().string().c_str(),30,108,24,RAYWHITE);
        DrawText(TextFormat("Simulation %.3f s   |   %i render elements   |   last step %.2f ms",time,int(instances.size()),lastStep),30,750,18,RAYWHITE);
        DrawText(message.c_str(),30,785,17,{203,232,126,255});DrawText("Inventory-free SDK client / no model calls in physics",30,815,17,{164,186,197,255});
        DrawText(TextFormat("EXPERIMENT %i / %i",int(selected+1),int(files.size())),980,28,21,RAYWHITE);
        if(button(72,running?"Pause":"Run")||IsKeyPressed(KEY_SPACE)){running=!running;accumulator=0;}
        if(button(112,"Reset package")){try{load();}catch(const std::exception &e){message=e.what();}}
        if(button(152,"Next example")||IsKeyPressed(KEY_RIGHT)){selected=(selected+1)%files.size();try{load();}catch(const std::exception &e){message=e.what();}}
        if(button(192,"Previous example")||IsKeyPressed(KEY_LEFT)){selected=(selected+files.size()-1)%files.size();try{load();}catch(const std::exception &e){message=e.what();}}
        if(button(232,"Export report (platform-report.json)")&&!job.valid()){std::ofstream f("build/platform-report.json");f<<world->reportJson();message=f?"Report saved to build/platform-report.json":"Report write failed";}
        if(button(725,"Save image")){rlDrawRenderBatchActive();Image shot=LoadImageFromScreen();ExportImage(shot,"build/platform-lab.png");UnloadImage(shot);}
        DrawFPS(980,790);
        DrawText(reference?"REFERENCE / FRACTURE":"RIGID / LIVE",980,291,20,{203,232,126,255});
        DrawText(reference?"Actual cells and connectivity":"Spheres and oriented boxes",980,325,16,RAYWHITE);
        DrawText("Glass   Wood   Iron",980,357,18,{164,186,197,255});
        DrawText("Space: run / pause",980,414,17,RAYWHITE);DrawText("Arrow keys: select example",980,445,17,RAYWHITE);
        DrawText(TextFormat("Broken bonds: %u",broken),980,490,20,{222,165,90,255});
        DrawText("Mouse wheel: zoom",980,527,17,{164,186,197,255});
        DrawText(reference?"Reference runs slower than real time":"Offset comes from starting geometry",980,559,15,{164,186,197,255});
        DrawText("Adaptive detail and automatic",980,622,17,{164,186,197,255});DrawText("rigid/fracture switching:",980,648,17,{164,186,197,255});DrawText("NOT IMPLEMENTED",980,677,19,{222,165,90,255});
        EndDrawing();
    }
    if(job.valid())job.get();UnloadRenderTexture(viewport);CloseWindow();return 0;
}catch(const std::exception &e){TraceLog(LOG_ERROR,"%s",e.what());return 1;}}
