#include "viewer/FractureView.hpp"
#include "fracture/FracturePreview.hpp"
#include "material/MaterialCatalog.hpp"
#include <raylib.h>
#include <rlgl.h>
#include <algorithm>
#include <array>
#include <future>
#include <iomanip>
#include <sstream>
#include <stdexcept>
namespace {
using namespace banjo;
std::string fmt(double n,int digits=2){std::ostringstream s;s<<std::fixed<<std::setprecision(digits)<<n;return s.str();}
constexpr Color bg{17,25,31,255},ink{237,240,225,255},muted{153,177,186,255},accent{201,230,140,255},hot{255,140,95,255};
bool button(int x,int y,int width,const std::string &label,bool enabled=true){Rectangle r{float(x),float(y),float(width),34};bool hover=enabled&&CheckCollisionPointRec(GetMousePosition(),r);DrawRectangleRounded(r,.12F,4,hover?accent:Color{46,64,72,255});DrawText(label.c_str(),x+10,y+9,16,enabled?(hover?bg:ink):muted);return hover&&IsMouseButtonPressed(MOUSE_BUTTON_LEFT);}
const RuptureCascadeFrame &frameAt(const FracturePreviewRun &r,double time){auto i=std::upper_bound(r.frames.begin(),r.frames.end(),time,[](double t,const auto &f){return t<f.time_s;});return i==r.frames.begin()?r.frames.front():*std::prev(i);}
}
void runFractureView(const std::filesystem::path &workspace){
    double speed=60,time_ns=0;bool playing=false,back=false;FracturePreview runs;bool ready=false;std::string error;
    auto job=std::async(std::launch::async,[speed]{return buildFracturePreview(speed);});
    while(!back&&!WindowShouldClose()){
        if(job.valid()&&job.wait_for(std::chrono::seconds(0))==std::future_status::ready){try{runs=job.get();ready=true;playing=true;time_ns=0;}catch(const std::exception &e){error=e.what();}}
        if(playing&&ready){time_ns=std::min(100.0,time_ns+std::min(double(GetFrameTime()),.1)*5);if(time_ns==100)playing=false;}
        BeginDrawing();ClearBackground(bg);
        DrawText("BANJO / FRACTURE MICROSCOPE",32,28,19,accent);
        DrawText("An impact. A wave. A local break.",32,65,32,ink);
        DrawText("Eight connected material regions. Real solver states, slowed down for inspection.",32,110,18,muted);
        if(button(1110,28,230,"Back to bowl"))back=true;
        int x=32;for(double choice:{4.0,60.0,120.0,240.0}){
            if(button(x,149,170,fmt(choice,0)+" m/s impact",!job.valid())){speed=choice;ready=false;playing=false;error.clear();job=std::async(std::launch::async,[choice]{return buildFracturePreview(choice);});}x+=184;
        }
        DrawText(("Selected: "+fmt(speed,0)+" m/s").c_str(),800,158,18,accent);
        if(ready){
            for(unsigned row=0;row<3;++row){const auto &run=runs[row];const auto &f=frameAt(run,time_ns*1e-9);const int y=257+int(row)*137;
                Color tint=row==0?Color{110,207,219,255}:row==1?Color{207,154,90,255}:Color{162,176,196,255};
                DrawText(std::string(materialPresetName(run.material)).c_str(),32,y-22,22,tint);
                DrawText(row==0?"Brittle connector law":"Elastic reference",32,y+9,15,muted);if(row>0)DrawText("Failure unsupported",32,y+29,15,muted);
                // Fixed metric scale shared across materials and time. No exploded
                // gaps or per-component motion offsets. Regions are point samples.
                const auto screen=[&](double world){return float(345+world*1e6*10);};
                DrawLine(300,y+28,1345,y+28,{44,60,68,255});
                for(unsigned b=0;b<f.live_bonds.size();++b)if(f.live_bonds[b]){
                    const double extension=length(f.positions[b+1]-f.positions[b])-1e-5;
                    const double strain=extension/1e-5;const Color c=std::abs(strain)<1e-8?Color{107,130,139,255}:strain>0?Color{255,static_cast<unsigned char>(160-100*std::min(1.0,strain/.005)),80,255}:Color{75,148,196,255};
                    DrawLineEx({screen(f.positions[b].x),float(y)},{screen(f.positions[b+1].x),float(y)},5,c);
                }
                for(unsigned n=0;n<f.positions.size();++n){DrawCircleV({screen(f.positions[n].x),float(y)},11,tint);DrawText(std::to_string(n+1).c_str(),int(screen(f.positions[n].x))-4,y+18,13,muted);}
                DrawCircleV({screen(f.impactor_position.x),float(y)},20,accent);
                unsigned connected=1;std::string groups;for(bool live:f.live_bonds){if(live)++connected;else{groups+=std::to_string(connected)+" + ";connected=1;}}groups+=std::to_string(connected);
                DrawText(("Connected groups: "+groups).c_str(),345,y+46,17,ink);
            }
            DrawText((fmt(time_ns)+" ns").c_str(),32,661,26,accent);
            DrawText("Blue: compression   Orange: tension   Missing connection: failed bond",210,668,17,muted);
            Rectangle track{32,706,1310,14};DrawRectangleRec(track,{49,65,73,255});DrawRectangle(32,706,int(1310*time_ns/100),14,accent);
            for(const auto &e:runs[0].events)DrawCircle(32+int(1310*e.time_s/1e-7),713,5,hot);
            if(IsMouseButtonDown(MOUSE_BUTTON_LEFT)&&CheckCollisionPointRec(GetMousePosition(),{32,694,1310,38})){time_ns=std::clamp((GetMouseX()-32)/1310.0*100,0.0,100.0);playing=false;}
            if(button(32,744,145,playing?"Pause":"Play"))playing=!playing;
            if(button(188,744,145,"Restart")){time_ns=0;playing=true;}
            if(button(344,744,200,"Next fracture")){playing=false;for(const auto &e:runs[0].events)if(e.time_s*1e9>time_ns+1e-5){time_ns=e.time_s*1e9+1e-6;break;}}
            std::string event="No fracture yet";for(const auto &e:runs[0].events)if(e.time_s<=time_ns*1e-9){event="Glass at "+fmt(e.time_s*1e9,3)+" ns: connection "+std::to_string(e.broken_bonds.front()+1)+" failed";}
            DrawText(event.c_str(),570,753,18,ink);
        }else DrawText(error.empty()?"Computing all three material trajectories...":error.c_str(),32,300,23,accent);
        DrawText("Connector reference. Back to bowl opens the experimental cell-fracture lab.",32,814,17,muted);
        const bool capture=button(1110,797,230,"Save image")||IsKeyPressed(KEY_F12);
        if(capture){rlDrawRenderBatchActive();Image shot=LoadImageFromScreen();ExportImage(shot,(workspace/"fracture-microscope.png").string().c_str());UnloadImage(shot);}
        EndDrawing();
    }
}
