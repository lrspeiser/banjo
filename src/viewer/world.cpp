#include "world/WorldLabFixture.hpp"
#include <raylib.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <fstream>
#include <string>

namespace {
constexpr Color background{13,20,29,255},panel{23,33,44,255},ink{220,231,239,255},muted{145,167,184,255};
Color heatColor(double kelvin){
    const double t=std::clamp((kelvin-293.15)/1000,0.,1.);
    return {static_cast<unsigned char>(35+220*std::min(1.,t*2)),static_cast<unsigned char>(80+155*t*t),static_cast<unsigned char>(125*(1-t)),255};
}
}
int main(int argc,char **argv){
    // Optional automated capture runs the SAME stepping/drawing path, then exits.
    // Interactive mode has ordinary raylib frame/input control.
    const bool capture=argc==3&&std::string(argv[1])=="--capture";
    auto world=banjo::makeWorldLab();bool running=true;unsigned frame=0;double reportClock=1;
    auto report=nlohmann::json::parse(world->reportJson());
    SetConfigFlags(FLAG_MSAA_4X_HINT);InitWindow(1280,800,"Banjo - Sparse World Thermal Lab");SetTargetFPS(60);
    while(!WindowShouldClose()){
        if(IsKeyPressed(KEY_SPACE))running=!running;
        if(IsKeyPressed(KEY_R)){world=banjo::makeWorldLab();reportClock=1;}
        if(running){auto receipt=world->advance(capture?1./60:std::min(.25,double(GetFrameTime())));if(!receipt.error.empty())running=false;}
        reportClock+=GetFrameTime();if(reportClock>=.25){report=nlohmann::json::parse(world->reportJson());reportClock=0;}
        if(IsKeyPressed(KEY_S)){std::ofstream output("world-lab-report.json");output<<world->reportJson();TakeScreenshot("world-lab.png");}
        BeginDrawing();ClearBackground(background);
        DrawText("BANJO  /  WORLD FOUNDATIONS",30,24,28,ink);
        DrawText("16,777,216 stored voxels   |   256 active thermal cells   |   0 physics bodies",30,64,20,muted);
        DrawText("Same 8 x 8 x 1 cm samples. Four center cells start at 650 K; heater work depends on material.",30,99,18,ink);
        const auto cells=world->activeCells();
        for(unsigned coupon=0;coupon<4;++coupon){
            const int x=30+int(coupon)*310,y=143;DrawRectangleRounded({float(x),float(y),290,470},.03f,4,panel);
            DrawText(banjo::worldLabMaterialName(coupon+1),x+14,y+16,20,ink);
            for(auto &cell:cells)if(cell.region==coupon+1){const int cx=x+17+int(cell.address.x)*32,cy=y+59+int(cell.address.y)*32;DrawRectangle(cx,cy,30,30,heatColor(cell.temperature_k));}
            const auto &r=report["regions"][coupon];
            DrawText(TextFormat("Peak %.1f K",r["temperature_max_k"].get<double>()),x+16,y+334,20,ink);
            DrawText(TextFormat("Fuel left %.4f g",r["fuel_kg"].get<double>()*1000),x+16,y+367,18,muted);
            DrawText(TextFormat("Reaction heat %.1f J",r["reaction_heat_j"].get<double>()),x+16,y+397,18,muted);
            DrawText(TextFormat("Heater work %.1f J",r["external_work_j"].get<double>()),x+16,y+427,18,muted);
        }
        const auto &p=report["performance"];const auto &b=report["last_budget"];
        DrawText(TextFormat("%s  |  requested %.2f s  |  physics p95 %.3f ms  |  late regions %u",
            running?"RUNNING":"PAUSED",report["requested_time_s"].get<double>(),p["advance_p95_ms"].get<double>(),b["regions_late"].get<unsigned>()),30,637,20,ink);
        DrawText(TextFormat("Heat + chemical energy residual: %.3g J  |  SPACE pause   R reset   S save evidence",report["combined_active_energy_residual_j"].get<double>()),30,672,18,muted);
        DrawText("Insulated regions, constant properties, finite trapped oxygen. Numerical reaction model; no airflow or flames.",30,715,18,ink);
        DrawText("Cold voxels are stored, not fully simulated. Glass impact/contact correction is the next mechanical milestone.",30,745,18,muted);
        EndDrawing();++frame;
        if(capture&&frame==600){TakeScreenshot(argv[2]);std::ofstream output(std::string(argv[2])+".json");output<<world->reportJson();break;}
    }
    CloseWindow();return 0;
}
