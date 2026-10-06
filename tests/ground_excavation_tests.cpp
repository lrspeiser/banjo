#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "terrain/Environment.hpp"
#include "terrain/GroundWork.hpp"
#include "rigid/JoltWorld.hpp"
#include <nlohmann/json.hpp>
#include <chrono>
#include <cmath>
#include <iostream>
#include <set>
#include <stdexcept>

namespace {
using namespace banjo;using namespace banjo::fastlattice;using Json=nlohmann::json;
void require(bool ok,const std::string &why){if(!ok)throw std::runtime_error(why);}
void near(double a,double b,double tol,const std::string &why){require(std::isfinite(a)&&std::abs(a-b)<=tol,why+": "+std::to_string(a)+" versus "+std::to_string(b));}
Json scene(const std::string &tool,const std::string &ground,double q=.25,double top=.75) {
    return {{"terrain",{{"surface","columns"},{"generate",{{"kind","flat"},{"nx",20},{"nz",20},{"cell_m",q},
        {"soil_m",ground=="soil"?top:0},{"sand_m",ground=="sand"?top:0},{"discharge_m3_s",0}}}}},
        {"bodies",Json::array({{{"name","point"},{"shape","box"},{"material",tool},
            {"dimensions_m",{.08,.24,.08}},{"center_m",{0,2,0}}}})}};
}
TileImpactRequest request(const Json &s){TileImpactRequest r;r.cell_size_m=.04;r.backend=BackendKind::CpuParallel;
    r.bodies=readSceneJson(s.dump());readSceneSettings(s.dump(),r);return r;}
std::unique_ptr<LiveWorld> world(const Json &s){auto w=LiveWorld::open(request(s));w->selectHand("alice");
    require(w->toolPoint("point",{0,1.88,0},{0,-1,0},.04,.04,30,.15,{0,2,0})!=0,"point admission");
    require(w->wield("point",{0,2,0}),"wield point");return w;}
Vec3 target(const LiveWorld &w,double y){const auto &g=w.environment()->terrain().grid();return {g.xOf(10),y,g.zOf(10)};}
Json cut(LiveWorld &w,Vec3 at,double work,const std::string &id){auto r=w.strikeCell(at,work,id);require(!r.cut_receipt_json.empty(),"cut receipt");return Json::parse(r.cut_receipt_json);}
void step(LiveWorld &w,int count){for(int n=0;n<count;++n){w.step(1./240);require(!w.steppedBack(),"debris native step refused");}}

void materialsAndFunding() {
    for(const std::string tool:{"glass","oak","iron"})for(const std::string ground:{"rock","soil","sand"}) {
        auto w=world(scene(tool,ground));const auto at=target(*w,ground=="rock"?-.375:.375);
        const auto &f=w->environment()->terrain();const auto c=f.cellAt(at.x,at.z).value();
        const auto none=cut(*w,at,0,"zero");near(none["consumed_work_j"],0,0,"no unfunded work");
        require(Json::parse(w->groundDebrisJson())["bodies"].empty(),"unfunded operation has no debris");
        const auto began=std::chrono::steady_clock::now();const auto result=cut(*w,at,1e6,"funded:"+tool+":"+ground);
        const double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-began).count();
        if(tool=="oak"&&ground=="rock") {
            require(!result["supported"].get<bool>(),"oak keeps hardness limit");
            near(result["consumed_work_j"],0,0,"unsupported material consumes no budget");
            require(f.kindAt(c,at.y)==terrain::RunKind::Rock,"unsupported point preserves rock");continue;
        }
        require(result["supported"].get<bool>(),"supported funded cut");
        const double consumed=result["consumed_work_j"];
        require(consumed>0&&consumed<=1e6,"work bounded by source");
        if(ground=="rock")near(consumed,468750,1e-6,"unchanged rock specific energy");
        near(result["loosened"][ground=="rock"?"rock_m3":ground=="sand"?"sand_m3":"soil_m3"],.015625,1e-12,"full band volume");
        near(w->environment()->carriedKg(),0,0,"released physical matter is not inventory");
        const auto bodies=Json::parse(w->groundDebrisJson())["bodies"];require(bodies.size()==1,"whole connected cut component");
        const auto &body=bodies[0];require(body["cells"].size()==125,"5 cm exact constituents");
        std::set<std::string> identities;double mass=0,volume=0;
        for(const auto &cell:body["cells"]) {
            require(identities.insert(cell["id"]).second,"unique constituents");mass+=cell["mass_kg"].get<double>();volume+=cell["volume_m3"].get<double>();
        }
        near(volume,.015625,1e-12,"constituent volumes exact");near(mass,body["mass_kg"],1e-9,"constituent masses exact");
        for(const auto &v:body["pose"]["velocity_m_s"])near(v,0,0,"no launched motion");
        require(f.kindAt(c,at.y)==terrain::RunKind::Void,"target band physically absent");
        near(f.height(c),ground=="rock"?0:.75,1e-12,"wall retains roof");
        near(f.residual().total(),0,1e-10,"terrain volume residual");
        const auto replay=cut(*w,at,1e6,"funded:"+tool+":"+ground);require(replay==result,"same source replays exact receipt");
        require(Json::parse(w->groundDebrisJson())["bodies"].size()==1,"replay creates no duplicate");
        bool mismatch=false;try{(void)cut(*w,at,999999,"funded:"+tool+":"+ground);}catch(const std::exception &){mismatch=true;}
        require(mismatch,"reused funding refuses different request");
        const auto id=body["id"].get<MatterBodyId>();
        bool far=false;try{(void)w->collectGroundDebris(id,{100,100,100},3);}catch(const std::exception &){far=true;}
        require(far,"collection measures reach");
        std::string why;const auto saved=w->snapshot(why);require(!saved.empty(),"component snapshot: "+why);
        auto restored=LiveWorld::open(request(scene(tool,ground)),saved);
        require(restored->restored().tier=="whole","whole native reopen");
        require(Json::parse(restored->groundDebrisJson())["bodies"]==bodies,"pose and all source cells survive reopening");
        restored->selectHand("bob");const auto p=Json::parse(restored->collectGroundDebris(id,at,3));
        require(p["cells"]==body["cells"],"collection returns same constituent cells");
        near(restored->environment()->carriedKg(),mass,1e-9,"single collection credits actual native mass");
        bool twice=false;try{(void)restored->collectGroundDebris(id,at,3);}catch(const std::exception &){twice=true;}
        require(twice,"second collection refused");restored->selectHand("alice");near(restored->environment()->carriedKg(),0,0,"peer gets no matter");
        std::cout<<tool<<" / "<<ground<<": "<<mass<<" kg, "<<consumed<<" J, "<<ms<<" ms; terrain residual "<<f.residual().total()<<" m3\n";
    }
}
void progressAndSettling() {
    const auto s=scene("iron","soil");auto w=world(s);const auto at=target(*w,.625);
    const auto quote=cut(*w,at,1,"partial-first");require(quote["kind"]=="working cell","weak work persists without extraction");
    std::string why;const auto saved=w->snapshot(why);require(!saved.empty(),"partial snapshot");
    auto reopened=LiveWorld::open(request(s),saved);reopened->selectHand("alice");
    const auto finish=cut(*reopened,at,1e6,"partial-finish");
    near(finish["consumed_work_j"].get<double>()+1,finish["required_work_j"],1e-8,"restart retains paid work exactly");
    const auto old=Json::parse(reopened->groundDebrisJson())["bodies"][0];const double oldY=old["pose"]["center_m"][1];
    // Cut the support immediately below the released top component, retaining
    // both actual chunks. Gravity must move the upper component with no kick.
    const auto support=cut(*reopened,target(*reopened,.375),1e6,"support-cut");
    (void)reopened->collectGroundDebris(support["body_id"].get<MatterBodyId>(),target(*reopened,.375),3);
    step(*reopened,240);
    const auto after=Json::parse(reopened->groundDebrisJson())["bodies"];
    require(after.size()==1,"upper component retained after collecting its actual support");
    const double nowY=after[0]["pose"]["center_m"][1];
    require(nowY<oldY-.05,"unsupported cut component falls under native gravity");
    step(*reopened,480);const auto settled=Json::parse(reopened->groundDebrisJson())["bodies"];
    const double speed=std::abs(settled[0]["pose"]["velocity_m_s"][1].get<double>());
    require(speed<.05,"native cut component settles on retained matter");
    const auto current=settled[0]["pose"]["center_m"];
    const auto collected=Json::parse(reopened->collectGroundDebris(settled[0]["id"],{current[0],current[1],current[2]},3));
    require(collected["pose"]==settled[0]["pose"],"collection packet retains actual settled native transform");
    std::cout<<"physical fall "<<oldY-nowY<<" m; settled vertical speed "<<speed<<" m/s at 1/240 s\n";
}
void clippingAndCorruptSave() {
    auto w=world(scene("iron","soil",.25,.73));const auto at=target(*w,.73);
    const auto r=cut(*w,at,1e6,"clipped");near(r["loosened"]["soil_m3"],.23*.25*.25,1e-12,"clipped layer volume");
    const auto body=Json::parse(w->groundDebrisJson())["bodies"][0];double volume=0;
    for(const auto &c:body["cells"])volume+=c["volume_m3"].get<double>();
    near(volume,.23*.25*.25,1e-12,"clipped constituent no rounding volume");
    std::string why;auto saved=Json::parse(w->snapshot(why));require(!saved.empty(),"clipped save");
    auto ground=Json::parse(w->environment()->groundStateJson());
    ground["debris"]["bodies"][0]["cells"][0]["mass_kg"]=1e9;
    bool refused=false;try{(void)terrain::Environment::fromScene(scene("iron","soil",.25,.73).dump(),ground.dump());}catch(const std::exception &){refused=true;}
    require(refused,"corrupt source mass refused");
    auto incompatible=world(scene("iron","soil",.24));const auto rejected=cut(*incompatible,target(*incompatible,.75),1e6,"bad-resolution");
    require(!rejected["supported"].get<bool>(),"incompatible cell hierarchy refused");near(rejected["consumed_work_j"],0,0,"no work consumed by unsupported resolution");
    // v5 bulk accounts stay bulk accounts; loading an old world invents no
    // historic fragment positions, constitutive damage, or provenance.
    const auto legacyScene=scene("iron","soil");auto old=world(legacyScene);
    (void)old->dig(0,0,0,0,.2,.1);
    auto legacy=Json::parse(old->environment()->groundStateJson());legacy["schema"]="banjo.ground-state.v5";legacy.erase("debris");legacy.erase("matter_revisions");
    const auto migrated=terrain::Environment::fromScene(legacyScene.dump(),legacy.dump());
    near(migrated->carriedTotal().total(),old->environment()->carriedTotal().total(),0,"legacy owner quantities retained");
    require(Json::parse(migrated->debrisJson())["bodies"].empty(),"legacy ledger gains no fabricated fragments");
    auto history=world(scene("iron","soil"));const auto paidAt=target(*history,.75);
    const auto first=cut(*history,paidAt,1,"history-first");
    auto neighbor=paidAt;neighbor.x+=.25;
    (void)cut(*history,neighbor,1e6,"history-neighbor");
    const auto resumed=cut(*history,paidAt,1e6,"history-resumed");
    near(resumed["consumed_work_j"].get<double>()+1,first["required_work_j"],1e-8,"neighbor edits preserve paid source work");
    // Replacing the same geometry is different matter. Credit on a removed
    // source cannot make newly deposited soil cheaper to extract.
    auto replaced=world(scene("iron","soil"));const auto replacedAt=target(*replaced,.75);
    const auto paid=cut(*replaced,replacedAt,1,"retired-source");
    (void)replaced->dig(replacedAt.x,replacedAt.z,replacedAt.x,replacedAt.z,.1,.25);
    const auto fresh=cut(*replaced,target(*replaced,.5),1e6,"new-source");
    near(fresh["consumed_work_j"],paid["required_work_j"],1e-8,"removed source work does not fund replacement matter");
}
void internalContactWorkDoesNotFillRetryReceipts() {
    auto env=terrain::Environment::fromScene(scene("iron","rock").dump());JoltWorld rigid;env->attach(rigid);
    const auto &g=env->terrain().grid();const Vec3 at{g.xOf(10),-.125,g.zOf(10)};
    for(int n=0;n<4100;++n) {
        const auto result=Json::parse(env->excavateCell(rigid,at,.01,"native-contact:point-1",false));
        require(result["supported"].get<bool>(),"accepted contact work stays supported beyond external receipt limit");
    }
    const auto saved=Json::parse(env->groundStateJson()).at("debris");
    require(saved.at("receipts").empty(),"accepted solver work does not accumulate external retry receipts");
    require(saved.at("progress").size()==1,"contact work retains one target progress state");
    const auto &progress=saved.at("progress").begin().value();
    near(progress.at("work_j"),41,1e-8,"accepted contact work summed without loss");
    require(progress.at("work_sources").size()==1,"bounded actual source ledger coalesces one native actuator identity");
}
}
int main(){try{materialsAndFunding();progressAndSettling();clippingAndCorruptSave();internalContactWorkDoesNotFillRetryReceipts();std::cout<<"all work-cut checks passed\n";return 0;}
    catch(const std::exception &e){std::cerr<<"FAILED: "<<e.what()<<'\n';return 1;}}
