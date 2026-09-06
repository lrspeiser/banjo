#include "platform/PlatformWorld.hpp"
#include <raylib.h>
#include <rlgl.h>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <algorithm>
#include <map>
#include <set>
#include <chrono>

using namespace banjo;
namespace {
#ifdef BANJO_NETWORK_LAB
constexpr bool networkLab=true;
#else
constexpr bool networkLab=false;
#endif
Vector3 v(Vec3 p){return {float(p.x),float(p.y),float(p.z)};}
Color tint(MaterialPreset m){return m==MaterialPreset::Glass?Color{99,222,228,255}:m==MaterialPreset::Oak?Color{221,165,92,255}:Color{163,181,203,255};}
bool button(int y,const char *label){Rectangle r{1000,float(y),330,34};bool hover=CheckCollisionPointRec(GetMousePosition(),r);DrawRectangleRec(r,hover?Color{65,91,101,255}:Color{37,60,72,255});DrawText(label,1012,y+9,16,RAYWHITE);return hover&&IsMouseButtonPressed(MOUSE_BUTTON_LEFT);}
void drawCell(Vec3 center,double radius,Color color){
    // Render the actual collision cells with light, not a fabricated cut mesh.
    static const auto triangles=[] {
        std::vector<std::array<Vec3,3>> mesh;
        auto point=[](int y,int x){double a=3.141592653589793*y/8,b=2*3.141592653589793*x/12;return Vec3{std::sin(a)*std::cos(b),std::cos(a),std::sin(a)*std::sin(b)};};
        for(int y=0;y<8;++y)for(int x=0;x<12;++x){auto a=point(y,x),b=point(y+1,x),c=point(y+1,x+1),d=point(y,x+1);if(y<7)mesh.push_back({a,c,b});if(y>0)mesh.push_back({a,d,c});}return mesh;
    }();
    for(auto &t:triangles){const double light=.3+.7*std::max(0.,dot(normalized(t[0]+t[1]+t[2]),normalized(Vec3{-.4,1,.7})));
        const Color shade{static_cast<unsigned char>(color.r*light),static_cast<unsigned char>(color.g*light),static_cast<unsigned char>(color.b*light),255};
        DrawTriangle3D(v(center+t[0]*radius),v(center+t[1]*radius),v(center+t[2]*radius),shade);
    }
}
void drawBody(const PlatformInstance &o,bool structure){
    const auto p=o.state.center_of_mass_world_m;const auto color=o.color_rgba?Color{static_cast<unsigned char>(o.color_rgba>>24),static_cast<unsigned char>(o.color_rgba>>16),static_cast<unsigned char>(o.color_rgba>>8),255}:tint(o.material);
    if(!o.local_mesh.empty()){
        for(auto &triangle:o.local_mesh){std::array<Vec3,3> t;for(unsigned i=0;i<3;++i)t[i]=p+o.state.orientation_world.rotate(triangle[i]);
            const double light=.4+.6*std::abs(dot(normalized(cross(t[1]-t[0],t[2]-t[0])),normalized(Vec3{.4,1,.7})));
            const Color shade{static_cast<unsigned char>(color.r*light),static_cast<unsigned char>(color.g*light),static_cast<unsigned char>(color.b*light),255};
            if(!structure){DrawTriangle3D(v(t[0]),v(t[1]),v(t[2]),shade);DrawTriangle3D(v(t[2]),v(t[1]),v(t[0]),shade);}
            for(unsigned i=0;i<3;++i)DrawLine3D(v(t[i]),v(t[(i+1)%3]),structure?color:Color{56,65,78,255});}return;
    }
    if(o.geometry.kind==PrimitiveKind::Sphere){if(structure&&networkLab)DrawSphere(v(p),float(o.geometry.radius_m*.2),color);else if(structure)DrawSphereWires(v(p),float(o.geometry.radius_m),8,12,color);else if(networkLab)drawCell(p,o.geometry.radius_m,color);else DrawSphere(v(p),float(o.geometry.radius_m),color);
        if(!networkLab)DrawLine3D(v(p),v(p+o.state.orientation_world.rotate({o.geometry.radius_m,0,0})),RAYWHITE);return;}
    auto q=o.state.orientation_world;double angle=2*std::acos(std::clamp(q.w,-1.,1.));Vec3 axis=normalized(Vec3{q.x,q.y,q.z});
    rlPushMatrix();rlTranslatef(float(p.x),float(p.y),float(p.z));rlRotatef(float(angle*180/3.141592653589793),float(axis.x),float(axis.y),float(axis.z));
    if(!structure)DrawCubeV({0,0,0},v(o.geometry.dimensions_m),color);DrawCubeWiresV({0,0,0},v(o.geometry.dimensions_m),structure?color:Color{42,59,65,255});rlPopMatrix();
}
void drawSkin(const PlatformSkin &skin){
    const Color color{static_cast<unsigned char>(skin.color_rgba>>24),static_cast<unsigned char>(skin.color_rgba>>16),static_cast<unsigned char>(skin.color_rgba>>8),255};
    for(const auto &triangle:skin.mesh.triangles){const auto &t=triangle.positions_world_m;
        const auto normal=normalized(cross(t[1]-t[0],t[2]-t[0]));const double light=.35+.65*std::clamp(std::abs(dot(normal,normalized(Vec3{-.4,1,.7}))),0.,1.);
        const Color base=triangle.fracture_surface?Color{245,206,143,255}:color;
        const Color shade{static_cast<unsigned char>(base.r*light),static_cast<unsigned char>(base.g*light),static_cast<unsigned char>(base.b*light),255};
        DrawTriangle3D(v(t[0]),v(t[1]),v(t[2]),shade);DrawTriangle3D(v(t[2]),v(t[1]),v(t[0]),shade);
    }
}
}
int main(int argc,char **argv){try{
    using json=nlohmann::json;
    const std::filesystem::path directory=argc>1?argv[1]:networkLab?"assets/runtime-v2":"assets/runtime-v1";
    std::vector<std::filesystem::path> files;for(auto &e:std::filesystem::directory_iterator(directory))if(e.path().extension()==".json")files.push_back(e.path());
    std::sort(files.begin(),files.end());if(files.empty())throw std::runtime_error("No runtime test packages");
    unsigned selected=networkLab?3:2;selected=std::min(selected,unsigned(files.size()-1));
    if(argc>2){auto it=std::find_if(files.begin(),files.end(),[&](auto &p){return p.filename()==argv[2];});if(it==files.end())throw std::runtime_error("Unknown runtime test");selected=unsigned(it-files.begin());}
    std::string capture;bool showcase=false;double captureAt=3;
    for(int i=3;i<argc;++i){const std::string option=argv[i];
        if(option=="--showcase")showcase=true;
        else if(option=="--capture"&&i+1<argc)capture=argv[++i];
        else if(option=="--capture-at"&&i+1<argc){std::size_t end{};const std::string value=argv[++i];captureAt=std::stod(value,&end);if(end!=value.size()||!std::isfinite(captureAt)||captureAt<=0||captureAt>3)throw std::runtime_error("Capture time must be in (0,3] seconds");}
        else throw std::runtime_error("Expected --showcase, --capture image.png, or --capture-at seconds");
    }
    if(showcase&&!networkLab)throw std::runtime_error("Showcase requires the network lab");
    if(capture.empty()&&captureAt!=3)throw std::runtime_error("Capture time requires --capture");
    std::unique_ptr<PlatformWorld> world;json report,package;std::vector<PlatformInstance> instances;
    bool running=false;double timeScale=showcase?.25:1.;unsigned view=showcase?3:networkLab?0:1;double accumulator=0,time=0,refresh=0,lastStep=0,lag=0;unsigned frames=0;std::string notice="Ready. Release to run live.";
    std::vector<double> skinTimes;
    Camera3D camera{{1.8F,1.5F,2.6F},{0,.45F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
    auto load=[&]{std::ifstream f(files[selected]);if(!f||std::filesystem::file_size(files[selected])>4194304)throw std::runtime_error("Cannot read bounded package");
        std::string source((std::istreambuf_iterator<char>(f)),{});auto next=PlatformWorld::load(source);package=json::parse(next->packageJson());
        if(package["backend"]!=(networkLab?"material-network-v2":"compiled-impact-v1"))throw std::runtime_error("Package requires another lab backend");world=std::move(next);
        report=json::parse(world->reportJson());instances=world->renderInstances();running=false;accumulator=0;time=0;refresh=0;lastStep=0;lag=0;frames=0;skinTimes.clear();notice="Ready. Release to run live.";
        double height=0;for(auto &o:package["objects"])height=std::max(height,o["position_m"][1].get<double>());
        camera={{1.8F,1.5F,2.6F},{0,.45F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
        if(height>2)camera={{2.7F,2.2F,4.2F},{0,1.15F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
        if(!package["bowl"].is_null())camera={{2.3F,2.3F,2.8F},{0,.15F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
        if(package["objects"].size()>12)camera={{3,3,4},{0,.6F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
        if(networkLab)camera=package["objects"].size()>2?Camera3D{{.85F,.65F,1.8F},{0,.15F,0},{0,1,0},42,CAMERA_PERSPECTIVE}:Camera3D{{.44F,.39F,.69F},{0,.14F,0},{0,1,0},42,CAMERA_PERSPECTIVE};
        if(showcase){
            Vec3 lo{100,100,100},hi{-100,-100,-100};
            for(const auto &o:package["objects"]){Vec3 p{o["position_m"][0],o["position_m"][1],o["position_m"][2]},d{o["dimensions_m"][0],o["dimensions_m"][1],o["dimensions_m"][2]};
                Quat q{o["orientation_wxyz"][0],o["orientation_wxyz"][1],o["orientation_wxyz"][2],o["orientation_wxyz"][3]};
                for(int x:{-1,1})for(int y:{-1,1})for(int z:{-1,1}){auto c=p+q.rotate({x*d.x/2,y*d.y/2,z*d.z/2});lo={std::min(lo.x,c.x),std::min(lo.y,c.y),std::min(lo.z,c.z)};hi={std::max(hi.x,c.x),std::max(hi.y,c.y),std::max(hi.z,c.z)};}}
            const auto center=(lo+hi)/2;const double distance=std::max((hi.x-lo.x)/1.633,hi.y-lo.y)*1.9+(hi.z-lo.z)*.6;
            const bool single=package["objects"].size()<=2;
            camera={v(center+Vec3{distance*(single?.65:.12),distance*(single?.42:.24),distance*(single?.8:1.)}),v(center),{0,1,0},42,CAMERA_PERSPECTIVE};
        }
    };load();
    SetConfigFlags(FLAG_MSAA_4X_HINT);InitWindow(1360,850,networkLab?"Banjo - Local Material Runtime v2":"Banjo - Live Material Runtime v1");SetTargetFPS(60);
    RenderTexture2D viewport=LoadRenderTexture(980,600);
    const double trialEnd=capture.empty()?3:captureAt;
    auto advance=[&](unsigned steps){for(unsigned i=0;i<steps&&time<trialEnd-1e-9;++i){auto s=world->step();lastStep=s.wall_ms;time=s.elapsed_s;if(!s.error.empty()){if(!capture.empty())throw std::runtime_error(s.error);notice=s.error;running=false;break;}}
    };
    auto exportReport=[&](const std::string &path){auto r=json::parse(world->reportJson());auto times=skinTimes;std::sort(times.begin(),times.end());
        auto percentile=[&](double p){return times.empty()?0.:times[std::min(times.size()-1,std::size_t(p*double(times.size()-1)))];};
        r["presentation"]={{"mode",capture.empty()?"live":"offline-fixed-step-capture"},{"view",view==0?"skin":view==1?"cells":view==2?"structure":"skin-with-bond-diagnostics"},{"time_scale",capture.empty()?timeScale:1.},{"backlog_s",lag},{"rendered_frames",frames},{"skin_query_p95_ms",percentile(.95)},{"skin_query_p99_ms",percentile(.99)}};
        std::ofstream f(path);f<<r.dump(2);return bool(f);};
    while(!WindowShouldClose()){
        const double frame=GetFrameTime();refresh+=frame;++frames;
        std::set<int> keys;for(int key=GetKeyPressed();key;key=GetKeyPressed())keys.insert(key);
        if(!capture.empty()){advance(unsigned(std::round(1./60/world->fixedStep())));notice="Offline fixed-step capture; timing is not a realtime claim.";}
        if(running){accumulator+=frame*timeScale;unsigned steps=0;while(accumulator>=world->fixedStep()&&steps<24){advance(1);accumulator-=world->fixedStep();++steps;if(!running)break;}
            lag=accumulator;if(lag>.25){running=false;notice="Frame budget exceeded. Paused; report retains the backlog.";}
            if(time>=3-1e-9){running=false;notice="3-second live trial complete. Reset for another run.";}}
        if(refresh>.2||(!capture.empty()&&time>=trialEnd-1e-9)){report=json::parse(world->reportJson());refresh=0;}
        instances=world->renderInstances();const bool structure=view==2;std::vector<PlatformSkin> skins;
        if(view==0||view==3){const auto start=std::chrono::steady_clock::now();skins=world->renderSkins();skinTimes.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());if(skinTimes.size()>10000)skinTimes.erase(skinTimes.begin());}
        const float wheel=GetMouseWheelMove();if(wheel!=0){const float scale=std::clamp(1-wheel*.12F,.5F,2.F);Vector3 d{camera.position.x-camera.target.x,camera.position.y-camera.target.y,camera.position.z-camera.target.z};
            float length=std::sqrt(d.x*d.x+d.y*d.y+d.z*d.z);if(length*scale>.35&&length*scale<30)camera.position={camera.target.x+d.x*scale,camera.target.y+d.y*scale,camera.target.z+d.z*scale};}
        if(IsMouseButtonDown(MOUSE_BUTTON_RIGHT)&&GetMousePosition().x<980){const auto delta=GetMouseDelta();Vec3 d{camera.position.x-camera.target.x,camera.position.y-camera.target.y,camera.position.z-camera.target.z};const double radius=length(d),yaw=std::atan2(d.x,d.z)-delta.x*.006,pitch=std::clamp(std::asin(d.y/radius)+delta.y*.006,-1.3,1.3);
            camera.position={camera.target.x+float(radius*std::cos(pitch)*std::sin(yaw)),camera.target.y+float(radius*std::sin(pitch)),camera.target.z+float(radius*std::cos(pitch)*std::cos(yaw))};}
        BeginTextureMode(viewport);ClearBackground({13,23,30,255});BeginMode3D(camera);DrawGrid(16,.25F);
        for(auto &t:world->supportMesh()){DrawTriangle3D(v(t[0]),v(t[1]),v(t[2]),{45,66,75,255});DrawTriangle3D(v(t[2]),v(t[1]),v(t[0]),{36,53,62,255});}
        for(auto &o:instances)if((view!=0&&view!=3)||!o.deformable_cell)drawBody(o,structure);
        for(const auto &skin:skins)drawSkin(skin);
        if(structure)for(auto &b:world->renderBonds())DrawLine3D(v(b.a),v(b.b),!b.live?Color{255,108,106,255}:b.damage>0?Color{255,195,87,255}:Color{150,219,204,255});
        EndMode3D();
        // X-ray diagnostics of actual solver links, not fabricated skin cracks.
        // Long separated failed links are already omitted by renderBonds().
        if(view==3)for(const auto &b:world->renderBonds())if(!b.live||b.damage>0){const auto a=GetWorldToScreenEx(v(b.a),camera,980,600),c=GetWorldToScreenEx(v(b.b),camera,980,600);DrawLineEx(a,c,b.live?1.5F:2.5F,b.live?Color{255,195,87,255}:Color{255,108,106,255});}
        if(showcase)for(const auto &o:package["objects"])if(o["representation"]=="network"){
            const Vector3 anchor{o["position_m"][0].get<float>(),o["position_m"][1].get<float>()+o["dimensions_m"][1].get<float>()*.5F+.035F,o["position_m"][2].get<float>()};
            const auto point=GetWorldToScreenEx(anchor,camera,980,600);const auto label=o["name"].get<std::string>();const int width=MeasureText(label.c_str(),16);
            DrawRectangle(int(point.x)-width/2-7,int(point.y)-4,width+14,24,{13,23,30,230});DrawText(label.c_str(),int(point.x)-width/2,int(point.y),16,RAYWHITE);
        }
        EndTextureMode();
        BeginDrawing();ClearBackground({13,23,30,255});DrawTextureRec(viewport.texture,{0,0,980,-600},{0,115},WHITE);DrawRectangle(980,0,380,850,{23,38,48,255});
        DrawText("BANJO / LIVE MATERIAL RUNTIME",28,22,27,{207,237,135,255});DrawText(package["name"].get<std::string>().c_str(),28,66,21,RAYWHITE);
        if(showcase)DrawText(package["objects"].size()>2?"MODEL-SCALE DOOR PANELS / CLAMPED EDGES / IDENTICAL STRIKES":"TOMATO PROXY / SOFT TISSUE / NO SEPARATE PEEL OR JUICE",28,705,16,{207,237,135,255});
        else {DrawText("GLASS",28,705,16,tint(MaterialPreset::Glass));DrawText("WOOD",118,705,16,tint(MaterialPreset::Oak));DrawText("IRON",208,705,16,tint(MaterialPreset::Iron));if(networkLab)DrawText("SOFT TISSUE / EXPERIMENTAL",300,705,16,{233,108,86,255});}
        unsigned softened=0;if(networkLab)for(const auto &o:report["objects"])softened+=o.value("damaged_links",0u)-o.value("broken_links",0u);
        DrawText(TextFormat(networkLab?"%.3f s   |   %u broken bonds   |   %u softened bonds":"%.3f s   |   %u broken bonds   |   %u visible elements",time,world->fractureCount(),networkLab?softened:unsigned(instances.size())),28,734,20,RAYWHITE);
        DrawText(notice.c_str(),28,770,17,{207,237,135,255});DrawText("Space: release/pause. Arrows: experiment. Wheel: zoom. Right-drag: orbit.",28,805,16,{148,177,191,255});
        DrawText(TextFormat("V%u TEST %u / %u",networkLab?2:1,selected+1,unsigned(files.size())),1000,24,22,RAYWHITE);
        if(button(65,running?"Pause":"Release / continue")||keys.contains(KEY_SPACE)){if(time>=3-1e-9)load();running=!running;notice=running?"Simulating live; backlog preserved.":"Paused. Step a frame or continue.";}
        if(button(107,"Reset initial state")||keys.contains(KEY_R))load();
        if(button(149,"Next experiment")||keys.contains(KEY_RIGHT)){selected=(selected+1)%unsigned(files.size());load();}
        if(button(191,"Previous experiment")||keys.contains(KEY_LEFT)){selected=(selected+unsigned(files.size())-1)%unsigned(files.size());load();}
        if(button(233,view==0?"View: skin (K to cycle)":view==1?"View: cells (K to cycle)":view==2?"View: structure (K to cycle)":"View: skin + damage overlay (K)")||keys.contains(KEY_K))view=networkLab?(view+1)%(showcase?4:3):view==1?2:1;
        if(button(275,TextFormat("Time: %.2gx (click to change)",timeScale)))timeScale=timeScale==1?.25:timeScale==.25?.1:1.;
        if(button(317,"Step one frame (paused)")){running=false;advance(unsigned(std::round(1./60/world->fixedStep())));report=json::parse(world->reportJson());}
        if(!showcase){
        DrawText("MEASURED THIS RUN",1000,376,18,{207,237,135,255});
        auto perf=report["performance"];
        DrawText(TextFormat("Physics step p95: %.3f ms",perf.value("step_p95_ms",0.)),1000,409,17,RAYWHITE);
        DrawText(TextFormat("Peak step: %.3f ms",perf.value("step_max_ms",0.)),1000,437,17,RAYWHITE);
        DrawText(TextFormat(networkLab?"Physical cells: %u":"Local pulse solves: %u",report.value(networkLab?"cells":"local_solves",0u)),1000,465,17,RAYWHITE);
        DrawText(TextFormat("Connected bodies: %u",report.value("connected_components",0u)),1000,493,17,RAYWHITE);
        DrawText(TextFormat("Fracture work: %.4f J",report.value("fracture_work_j",0.)),1000,521,17,RAYWHITE);
        if(networkLab)DrawText(TextFormat("Plastic work: %.4f J",report.value("plastic_work_j",0.)),1000,549,17,RAYWHITE);
        else DrawText(TextFormat("Budget-limited impacts: %u",report.value("budget_limited_impacts",0u)),1000,549,17,RAYWHITE);
        DrawText(networkLab?"Experimental cohesive cell network":"Approximate brittle fracture model",1000,591,16,{230,179,114,255});DrawText(networkLab?"Continuous deformation and damage":"Wood / iron: rigid response only",1000,616,16,{164,183,197,255});
        DrawText(networkLab?"Blocky skin; gold = exposed cut face":"Green intact / red failed connections",1000,647,15,{164,183,197,255});DrawText(networkLab?"Skin differs from sphere contacts":"No grain, plasticity or live save yet",1000,671,15,{164,183,197,255});
        }else{
            DrawText("MEASURED MATERIAL RESPONSE",1000,373,17,{207,237,135,255});int y=405;
            for(const auto &o:report["objects"])if(o.value("links",0u)>0&&y<570){DrawText(o["name"].get<std::string>().c_str(),1000,y,17,RAYWHITE);
                DrawText(TextFormat("%u broken / %u softened",o.value("broken_links",0u),o.value("damaged_links",0u)-o.value("broken_links",0u)),1000,y+22,16,{207,237,135,255});
                DrawText(TextFormat("%u groups | core %u / %u cells",o.value("components",0u),o.value("largest_component_cells",0u),o.value("cells",0u)),1000,y+43,15,{164,183,197,255});y+=65;}
            DrawText(TextFormat("Step p95 %.3f ms | %u bodies",report["performance"].value("step_p95_ms",0.),unsigned(instances.size())),1000,610,15,RAYWHITE);
            DrawText(view==3?"X-ray bonds: red failed / gold soft":view==2?"Bonds: red failed / gold softened":view==1?"Spheres = actual cell contact proxies":"Gold = newly exposed failed faces",1000,635,15,{164,183,197,255});
            DrawText(package["objects"].size()>2?"Experimental; glass response unresolved":"Experimental; cutting not converged",1000,660,14,{230,179,114,255});
            DrawText("Coarse cells; no material calibration",1000,682,14,{230,179,114,255});
        }
        if(button(710,"Export full report")){const std::string path=networkLab?"build/runtime-v2-report.json":"build/runtime-v1-report.json";notice=exportReport(path)?"Saved "+path:"Report write failed";}
        if(button(752,"Save screenshot")){rlDrawRenderBatchActive();Image image=LoadImageFromScreen();ExportImage(image,networkLab?"build/runtime-v2-lab.png":"build/runtime-v1-lab.png");UnloadImage(image);notice=networkLab?"Saved build/runtime-v2-lab.png":"Saved build/runtime-v1-lab.png";}
        DrawFPS(1000,810);EndDrawing();
        if(!capture.empty()&&time>=trialEnd-1e-9){Image screen=LoadImageFromScreen();const bool saved=ExportImage(screen,capture.c_str());UnloadImage(screen);if(!saved||!exportReport(capture+".json"))throw std::runtime_error("Capture export failed");break;}
    }
    UnloadRenderTexture(viewport);CloseWindow();return 0;
}catch(const std::exception &e){TraceLog(LOG_ERROR,"%s",e.what());return 1;}}
