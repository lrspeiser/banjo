// Exact local material cells: geometry, native mass/inertia and strict admission.
#include "fastlattice/PreciseRigidScene.hpp"
#include "fastlattice/LiveWorld.hpp"
#include "terrain/Environment.hpp"
#include <nlohmann/json.hpp>
#include <cmath>
#include <iostream>
#include <stdexcept>

using namespace banjo;
using namespace banjo::fastlattice;
using Json = nlohmann::json;
namespace {
void require(bool yes, const char *why) { if (!yes) throw std::runtime_error(why); }
void near(double a, double b, double tol, const char *why) {
    require(std::isfinite(a) && std::abs(a-b)<=tol,why);
}
Json blade(const std::string &material, double offset = 0) {
    return {{"name","blade"},{"material",material},{"position_m",{0,2,0}},
        {"cell_geometry","clipped-box-cells-v1"},{"parts",Json::array({
            {{"name","cell-0"},{"dimensions_m",{.1,.003,.18}},{"center_local_m",{offset-.05,0,0}}},
            {{"name","cell-1"},{"dimensions_m",{.1,.003,.18}},{"center_local_m",{offset+.05,0,0}}}})}};
}
void geometry() {
    for (const std::string material : {"glass","oak","iron","aluminum"}) {
        double baseline=0;
        for (double offset : {0.,.0037,.0231}) {
            auto b=readPreciseRigidScene(Json::array({blade(material,offset)}).dump())[0];
            const double mass=makeReferenceMaterial(b.material).density_kg_m3*.2*.003*.18;
            near(b.mass_kg,mass,1e-12,"density-derived clipped mass");
            near(b.dimensions_m.y,.003,1e-14,"blade thickness preserved");
            near(b.initial.center_of_mass_world_m.x,offset,1e-14,"offset does not snap COM");
            near(b.inertia.m[0][0],mass*(.003*.003+.18*.18)/12,1e-12,"thin x inertia");
            near(b.inertia.m[1][1],mass*(.2*.2+.18*.18)/12,1e-12,"thin y inertia");
            if (offset==0) baseline=b.mass_kg;
            near(b.mass_kg,baseline,1e-12,"grid alignment does not change mass");
            auto again=readPreciseRigidScene(Json::array({Json::parse(b.definition_json)}).dump())[0];
            require(again.local_cells && again.part_names==b.part_names,"cell identity round trip");
            near(again.mass_kg,b.mass_kg,0,"definition round trip mass");
        }
        std::cout<<"local cells "<<material<<" mass "<<baseline<<" kg, thickness 0.003 m; analytic mass/inertia residual <=1e-12\n";
    }
}
void refusals() {
    for (int mode=0;mode<5;++mode) {
        auto b=blade("iron");auto &cells=b["parts"];
        if(mode==0)cells[1]["center_local_m"][0]=.049; // overlap
        if(mode==1)cells[1]["center_local_m"][0]=.0505; // gap
        if(mode==2)cells[1]["name"]="cell-0";
        if(mode==3)cells[1]["material"]="glass";
        if(mode==4)cells[1]["center_local_m"]={.05,.003,.18}; // edge/point only
        bool refused=false;
        try {(void)readPreciseRigidScene(Json::array({b}).dump());}
        catch(const std::invalid_argument &) {refused=true;}
        require(refused,"invalid local matter accepted");
    }
}
void pointSurface() {
    TileImpactRequest r;r.backend=BackendKind::CpuParallel;r.cell_size_m=.05;
    r.bodies=readSceneJson(Json{{"bodies",Json::array({{{"name","marker"},{"shape","box"},
        {"material","concrete"},{"anchored",true},{"dimensions_m",{.05,.05,.05}},
        {"center_m",{-5,1,-5}}}})}}.dump());
    r.precise_rigid_scene_json=Json::array({blade("iron")}).dump();
    auto w=LiveWorld::open(r);
    require(w->toolPoint("blade",{.1,2,0},{1,0,0},.18,.003,30,.2,{0,2,0})!=0,"physical thin edge point admission");
    require(w->toolPoint("blade",{.11,2,0},{1,0,0},.18,.003,30,.2,{0,2,0})==0,"air point refused");
    require(w->toolPoint("blade",{.1,2,0},{-1,0,0},.18,.003,30,.2,{0,2,0})==0,"inward point refused");
    std::string why;auto saved=w->snapshot(why);require(!saved.empty(),"thin point save");
    auto reopened=LiveWorld::open(r,saved);
    require(reopened->toolPoints().size()==1 && reopened->toolPoints()[0].attached,"thin point restore");
    near(reopened->toolPoints()[0].thickness_m,.003,0,"restored point thickness");
    auto corrupt=Json::parse(saved);
    corrupt["tool_points"][0]["frame_nodes_b64"]="";
    bool refused=false;
    try {(void)LiveWorld::open(r,corrupt.dump());}
    catch(const std::invalid_argument &) {refused=true;}
    require(refused,"corrupt local frame must not restore attached");
}
void materialCuts() {
    for (const std::string material : {"glass","oak","iron","aluminum"}) {
        Json scene{{"terrain",{{"surface","columns"},{"generate",{{"kind","flat"},
            {"nx",20},{"nz",20},{"cell_m",.25},{"soil_m",.75},{"sand_m",0},
            {"discharge_m3_s",0}}}}},{"bodies",Json::array({{{"name","marker"},
            {"shape","box"},{"material","concrete"},{"anchored",true},
            {"dimensions_m",{.05,.05,.05}},{"center_m",{-5,1,-5}}}})}};
        TileImpactRequest r;r.cell_size_m=.05;r.backend=BackendKind::CpuParallel;
        r.bodies=readSceneJson(scene.dump());readSceneSettings(scene.dump(),r);
        r.precise_rigid_scene_json=Json::array({blade(material)}).dump();
        auto w=LiveWorld::open(r);w->selectHand("thin-tool-owner");
        require(w->toolPoint("blade",{.1,2,0},{1,0,0},.18,.003,30,.2,{0,2,0})!=0,"thin cutter admitted");
        require(w->wield("blade",{0,2,0}),"thin cutter wielded");
        const auto &g=w->environment()->terrain().grid();Vec3 at{g.xOf(10),.375,g.zOf(10)};
        auto cut=Json::parse(w->strikeCell(at,1000,"thin-cut").cut_receipt_json);
        require(cut["supported"].get<bool>(),"supported thin soil cutter");
        const double work=cut["consumed_work_j"];
        require(work>0 && work<=1000,"finite source work");
        near(cut["loosened"]["soil_m3"],.015625,1e-12,"actual band volume");
        auto debris=Json::parse(w->groundDebrisJson())["bodies"];
        require(debris.size()==1 && debris[0]["cells"].size()==125,"actual ground constituents");
        double mass=0;for(const auto &cell:debris[0]["cells"])mass+=cell["mass_kg"].get<double>();
        near(mass,25,1e-10,"soil density mass");
        near(w->environment()->terrain().residual().total(),0,1e-10,"terrain volume residual");
        for(const auto &v:debris[0]["pose"]["velocity_m_s"])near(v,0,0,"no launch velocity");
        std::cout<<"local "<<material<<" soil cut: "<<work<<" J, "<<mass<<" kg, residual <=1e-10 m3; "
            <<"50 mm rigid tool cells / 250 mm terrain; funded reduction, not full contact conservation\n";
    }
}
}
int main() {try {geometry();refusals();pointSurface();materialCuts();std::cout<<"local cell tool checks passed\n";return 0;}
    catch(const std::exception &e) {std::cerr<<"FAILED: "<<e.what()<<'\n';return 1;}}
