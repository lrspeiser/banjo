#include "world/WorldLabFixture.hpp"
#include "world/WorldPackage.hpp"
#include <raylib.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <fstream>
#include <string>
#include <iostream>
#include <stdexcept>

namespace {
constexpr Color background{13,20,29,255},panel{23,33,44,255},ink{220,231,239,255},muted{145,167,184,255};
Color heatColor(double kelvin){
    const double t=std::clamp((kelvin-293.15)/1000,0.,1.);
    return {static_cast<unsigned char>(35+220*std::min(1.,t*2)),static_cast<unsigned char>(80+155*t*t),static_cast<unsigned char>(125*(1-t)),255};
}
}
int main(int argc,char **argv){try{
    // Optional automated capture runs the SAME stepping/drawing path, then exits.
    // Interactive mode has ordinary raylib frame/input control.
    std::string capturePath,packagePath;
    for(int i=1;i<argc;++i){const std::string option=argv[i];if(i+1>=argc)throw std::invalid_argument("missing option value");if(option=="--capture")capturePath=argv[++i];else if(option=="--package")packagePath=argv[++i];else throw std::invalid_argument("unknown world lab option");}
    const bool capture=!capturePath.empty();
    auto createWorld=[&]{if(packagePath.empty())return banjo::makeWorldLab();std::ifstream file(packagePath,std::ios::binary);if(!file)throw std::runtime_error("cannot open world package");std::string data(4194305,'\0');file.read(data.data(),static_cast<std::streamsize>(data.size()));data.resize(static_cast<std::size_t>(file.gcount()));return banjo::loadWorldPackage(data);};
    auto world=createWorld();bool running=true;unsigned frame=0;double reportClock=1,pendingElapsed=0;
    auto report=nlohmann::json::parse(world->reportJson());
    SetConfigFlags(FLAG_MSAA_4X_HINT);InitWindow(1280,800,"Banjo - Sparse World Thermal Lab");SetTargetFPS(60);
    while(!WindowShouldClose()){
        bool save=false;
        // Consume buffered key-down events so a press and release between
        // frames is still handled (important for quick taps and UI automation).
        for(int key=GetKeyPressed();key!=0;key=GetKeyPressed()){
            if(key==KEY_SPACE)running=!running;
            if(key==KEY_R){world=createWorld();reportClock=1;pendingElapsed=0;}
            if(key==KEY_S)save=true;
        }
        if(running){pendingElapsed+=capture?1./60:double(GetFrameTime());const double request=std::min(.25,pendingElapsed);auto receipt=world->advance(request);pendingElapsed-=request;if(!receipt.error.empty()){running=false;reportClock=1;}}
        reportClock+=GetFrameTime();if(reportClock>=.25||(capture&&frame==599)){report=nlohmann::json::parse(world->reportJson());reportClock=0;}
        if(save){std::ofstream output("world-lab-report.json");output<<world->reportJson();TakeScreenshot("world-lab.png");}
        BeginDrawing();ClearBackground(background);
        DrawText("BANJO  /  WORLD FOUNDATIONS",30,24,28,ink);
        DrawText(TextFormat("%llu stored voxels   |   %u active thermal cells   |   0 physics bodies",static_cast<unsigned long long>(world->representedVoxelCount()),unsigned(world->activeCellCount())),30,64,20,muted);
        const bool frontier=std::any_of(report["regions"].begin(),report["regions"].end(),[](const auto &r){return r.contains("frontier")&&r["frontier"].value("enabled",false);});
        DrawText(frontier?"HEAT FRONTIER  /  cold neighbors wake as heat reaches them  /  z = 0 slice of the 3D active volume":packagePath.empty()?"8 x 8 x 1 cm coupons; center 650 K. Equal temperatures require material-dependent heater work.":"Declared energy/phase coupons. Water retains its identity through melting and freezing; cyan bars show liquid.",30,99,18,ink);
        const auto cells=world->activeCells();
        for(unsigned coupon=0;coupon<std::min(4U,unsigned(report["regions"].size()));++coupon){
            const int x=30+int(coupon)*310,y=143;DrawRectangleRounded({float(x),float(y),290,470},.03f,4,panel);
            const auto &r=report["regions"][coupon];
            auto name=r["material"].get<std::string>();if(name.size()>24)name=name.substr(0,21)+"...";
            DrawText(name.c_str(),x+14,y+16,20,ink);
            const int width=frontier?16:8,pixel=256/width;
            for(int cy=0;cy<width;++cy)for(int cx=0;cx<width;++cx)DrawRectangle(x+17+cx*pixel,y+59+cy*pixel,pixel-2,pixel-2,{31,43,54,255});
            for(auto &cell:cells)if(cell.region==r["id"].get<unsigned>()&&cell.address.x<unsigned(width)&&cell.address.y<unsigned(width)&&cell.address.z==0){const int cx=x+17+int(cell.address.x)*pixel,cy=y+59+int(cell.address.y)*pixel;
                const Color color=cell.phase_change?Color{static_cast<unsigned char>(210-160*cell.liquid_fraction),static_cast<unsigned char>(235-65*cell.liquid_fraction),255,255}:heatColor(cell.temperature_k);
                DrawRectangle(cx,cy,pixel-2,pixel-2,color);if(cell.phase_change){DrawRectangle(cx,cy+pixel-7,pixel-2,5,{90,100,120,255});DrawRectangle(cx,cy+pixel-7,int((pixel-2)*cell.liquid_fraction),5,SKYBLUE);}}
            DrawText(TextFormat("Peak %.1f K",r["temperature_max_k"].get<double>()),x+16,y+322,20,ink);
            if(frontier)DrawText(TextFormat("Active %u / 512 | queued %u",r["cells"].get<unsigned>(),r["frontier"].value("pending_candidates",0u)),x+16,y+347,16,ink);
            DrawText(TextFormat("Fuel %.3f g / liquid %.3f g",r["fuel_kg"].get<double>()*1000,r["liquid_mass_kg"].get<double>()*1000),x+16,y+367,16,muted);
            DrawText(TextFormat("Reaction heat %.1f J",r["reaction_heat_j"].get<double>()),x+16,y+397,18,muted);
            DrawText(TextFormat("Heater work %.1f J",r["external_work_j"].get<double>()),x+16,y+427,18,muted);
        }
        const auto &p=report["performance"];const auto &b=report["last_budget"];
        DrawText(TextFormat("%s | world %.2f s | p95 %.3f ms | late regions %u | host pending %.2f s",
            running?"RUNNING":"PAUSED",report["requested_time_s"].get<double>(),p["advance_p95_ms"].get<double>(),b["regions_late"].get<unsigned>(),pendingElapsed),30,637,20,ink);
        DrawText(TextFormat("Heat + chemical energy residual: %.3g J  |  SPACE pause   R reset   S save evidence",report["combined_active_energy_residual_j"].get<double>()),30,672,18,muted);
        const std::string error=b["error"].get<std::string>();
        DrawText(error.empty()?(frontier?"Dark cells remain stored. Queued or uninspected boundaries are insulated approximations, not an error bound.":"Insulated regions; illustrative constants. Named chemical + thermal/latent energy. No flow or mechanical coupling."):error.c_str(),30,715,18,error.empty()?ink:RED);
        DrawText(frontier?"Bounded 3D activation; finite fuel and oxygen. No airflow, fluid motion, thermal weakening or automatic cooling demotion.":"Cold voxels are stored, not fully simulated. Contact, fracture and thermal coupling remain separate accuracy gates.",30,745,17,muted);
        EndDrawing();++frame;
        if(capture&&frame==600){
            Image screenshot=LoadImageFromScreen();const bool saved=ExportImage(screenshot,capturePath.c_str());UnloadImage(screenshot);
            if(!saved)throw std::runtime_error("could not save world lab capture");
            std::ofstream output(capturePath+".json");output<<world->reportJson();if(!output)throw std::runtime_error("could not save capture report");break;
        }
    }
    CloseWindow();return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
