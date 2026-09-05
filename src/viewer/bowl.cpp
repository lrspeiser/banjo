#include "creator/BowlLab.hpp"
#include "viewer/FractureView.hpp"
#include <raylib.h>
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
using namespace banjo;
namespace {
constexpr Color bg{17,25,31,255},panel{27,39,46,255},ink{237,240,225,255},muted{157,180,187,255},lime{201,230,140,255};
Vector3 v(Vec3 a){return {float(a.x),float(a.y),float(a.z)};}
std::string number(double value){std::ostringstream s;s<<std::fixed<<std::setprecision(2)<<value;return s.str();}
Color color(MaterialPreset m){return m==MaterialPreset::Glass?Color{110,207,219,255}:m==MaterialPreset::Oak?Color{207,154,90,255}:Color{162,176,196,255};}
bool button(int x,int y,int w,const std::string &label,bool enabled=true){
    Rectangle r{float(x),float(y),float(w),36};bool hover=enabled&&CheckCollisionPointRec(GetMousePosition(),r);
    DrawRectangleRounded(r,.15F,4,hover?lime:Color{49,66,73,255});DrawText(label.c_str(),x+10,y+10,17,enabled?(hover?bg:ink):muted);
    return hover&&IsMouseButtonPressed(MOUSE_BUTTON_LEFT);
}
void write(const std::filesystem::path &p,const std::string &s){std::ofstream f(p,std::ios::binary);f<<s;f.flush();if(!f)throw std::runtime_error("Cannot save lab file");}
}
int main(int argc,char **argv){try{
    std::filesystem::path workspace="build/bowl-play";bool capture=false;
    for(int i=1;i<argc;++i){std::string a=argv[i];if(a=="--workspace"&&i+1<argc)workspace=argv[++i];else if(a=="--capture")capture=true;else throw std::invalid_argument("usage: banjo_bowl [--workspace path] [--capture]");}
    std::filesystem::create_directories(workspace);
    BowlLab lab(std::filesystem::exists(workspace/"stock.json")?CreatorWorld::load(workspace/"stock.json"):CreatorWorld{});
    SetConfigFlags(FLAG_MSAA_4X_HINT);InitWindow(1380,850,"Banjo - Craft and Roll Bowl Lab");SetTargetFPS(60);
    RenderTexture2D scene=LoadRenderTexture(1000,560);
    Camera3D camera{{2.5F,2.8F,3.0F},{0,.15F,0},{0,1,0},28,CAMERA_PERSPECTIVE};
    std::string message="Collect each material, then craft two balls of each.";double accumulator=0;int frames=0;
    while(!WindowShouldClose()){
        bool open_fracture=false;
        const double frame=std::min(double(GetFrameTime()),.1);if(lab.running()){accumulator+=frame;while(accumulator>=1.0/240){lab.step();accumulator-=1.0/240;}}else accumulator=0;
        BeginTextureMode(scene);ClearBackground(bg);
        BeginMode3D(camera);
        for(const auto &t:lab.triangles()){
            const double light=.7+.25*normalized(cross(t[1]-t[0],t[2]-t[0])).y;
            const auto c=lab.settings().surface==MaterialPreset::Concrete?Color{95,116,119,255}:color(lab.settings().surface);
            DrawTriangle3D(v(t[0]),v(t[1]),v(t[2]),Color{static_cast<unsigned char>(c.r*light),static_cast<unsigned char>(c.g*light),static_cast<unsigned char>(c.b*light),255});
        }
        for(unsigned a=0;a<96;++a){const double t=a*2*3.141592653589793/96,u=(a+1)*2*3.141592653589793/96,r=lab.settings().radius_m;DrawLine3D(v(bowlPoint(lab.settings(),r*cos(t),r*sin(t))),v(bowlPoint(lab.settings(),r*cos(u),r*sin(u))),lime);}
        for(const auto &o:lab.stock().objects()){
            const auto s=lab.state(o.id);DrawSphereEx(v(s.center_of_mass_world_m),float(o.recipe.radius_m),16,24,color(o.recipe.material));
            const auto tip=s.center_of_mass_world_m+s.orientation_world.rotate({0,0,o.recipe.radius_m*1.02});DrawSphere(v(tip),.007F,ink);
        }
        for(unsigned ring=4;ring<=24;ring+=4)for(unsigned a=0;a<96;++a){
            const double t=a*2*3.141592653589793/96,u=(a+1)*2*3.141592653589793/96,r=lab.settings().radius_m*ring/24;
            const Vec3 lift{0,.001,0};DrawLine3D(v(bowlPoint(lab.settings(),r*cos(t),r*sin(t))+lift),v(bowlPoint(lab.settings(),r*cos(u),r*sin(u))+lift),Color{135,155,155,255});
        }
        EndMode3D();EndTextureMode();BeginDrawing();ClearBackground(bg);
        DrawTextureRec(scene.texture,{0,0,1000,-560},{0,145},WHITE);
        DrawText("BANJO / MATERIAL LAB",32,30,18,lime);DrawText("Craft. Release. Observe.",32,63,34,ink);
        DrawText("Real contact geometry / glass + wood + iron",32,110,18,muted);
        if(button(32,145,310,"Open fracture microscope")){lab.pause();open_fracture=true;}
        DrawRectangle(1000,0,380,850,panel);DrawText("01  COLLECT & CRAFT",1024,30,21,lime);
        int y=78;
        for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
            const auto name=std::string(materialPresetName(material));
            DrawText((name+"   "+number(lab.stock().inventoryMass(material))+" kg held").c_str(),1024,y,19,color(material));
            auto report=lab.stock().assess(lab.craftRecipe(material));
            DrawText(("Ball needs "+number(report.material.required_mass_kg)+" kg").c_str(),1024,y+27,16,muted);
            try{
                bool collected=false;for(const auto &lot:lab.stock().lots())if(lot.material==material)collected=lot.collected;
                if(button(1024,y+51,150,collected?"Collected":"Collect",!collected&&!lab.running())){lab.collect(material);lab.stock().save(workspace/"stock.json");message="Collected "+name+" into inventory.";}
                if(button(1185,y+51,170,"Craft ball",report.buildable()&&!lab.running()&&lab.timeSeconds()==0&&lab.stock().objects().size()<9)){(void)lab.craft(material);lab.stock().save(workspace/"stock.json");message="Crafted "+name+" ball. Allocated material retained on reset.";}
            }catch(const std::exception &e){message=e.what();}y+=116;
        }
        DrawText("02  SET THE EXPERIMENT",1024,437,21,lime);
        auto s=lab.settings();bool changed=false;
        DrawText(("Tilt: "+number(s.tilt_degrees)+" degrees").c_str(),1024,475,18,ink);
        if(button(1024,502,155,"Tilt -5",!lab.running()&&s.tilt_degrees>-20)){s.tilt_degrees-=5;changed=true;}
        if(button(1190,502,165,"Tilt +5",!lab.running()&&s.tilt_degrees<20)){s.tilt_degrees+=5;changed=true;}
        if(button(1024,548,331,"Surface: "+std::string(materialPresetName(s.surface)),!lab.running())){
            s.surface=s.surface==MaterialPreset::Concrete?MaterialPreset::Glass:s.surface==MaterialPreset::Glass?MaterialPreset::Oak:s.surface==MaterialPreset::Oak?MaterialPreset::Iron:MaterialPreset::Concrete;changed=true;
        }
        try{
            if(changed){lab.configure(s);message="New setup: same crafted balls, reset positions and energy.";}
            if(button(1024,604,155,lab.running()?"Pause":"Release",!lab.stock().objects().empty())){if(lab.running())lab.pause();else lab.release();}
            if(button(1190,604,165,"Reset placement")){lab.configure(s);message="Placement reset. Inventory unchanged.";}
            if(button(1024,650,331,"Export experiment")){write(workspace/"experiment.json",lab.reportJson());message="Saved experiment.json with settings, states and inventory.";}
        }catch(const std::exception &e){message=e.what();}
        DrawText(("Time "+number(lab.timeSeconds())+" s   /   "+std::to_string(lab.stock().objects().size())+" balls").c_str(),32,720,22,ink);
        DrawText(message.substr(0,95).c_str(),32,757,18,lime);
        DrawText("Rigid preview: fracture is not connected yet.",32,794,18,muted);
        DrawText("First 3 balls: center. Next 6: rim.",1024,714,16,ink);
        DrawText("Surface / tilt edits reset placement.",1024,741,16,muted);
        DrawText("Crafting work / energy: pending.",1024,780,16,muted);
        EndDrawing();if(open_fracture)runFractureView(workspace);if(capture&&++frames==3){TakeScreenshot((workspace/"bowl.png").string().c_str());break;}
    }
    write(workspace/"experiment.json",lab.reportJson());lab.stock().save(workspace/"stock.json");UnloadRenderTexture(scene);CloseWindow();return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
