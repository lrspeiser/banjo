// Read actual retained native damage without stepping, healing or changing
// constitutive laws. This diagnostic is not a strength/fatigue certificate.
#include "fastlattice/LiveWorld.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <thread>

using namespace banjo;
using namespace banjo::fastlattice;
using Json=nlohmann::json;
namespace {
constexpr double dt=1./240.;
void require(bool ok,const std::string &why) {if(!ok) throw std::runtime_error(why);}
SceneBody box(const std::string &name,MaterialPreset material,Vec3 size,Vec3 at,bool fixed=false,Vec3 velocity={}) {
    SceneBody b;b.name=name;b.material=material;b.shape=BodyShape::Box;
    b.dimensions_m=size;b.center_m=at;b.anchored=fixed;b.velocity_m_s=velocity;return b;
}
Json condition(const LiveWorld &world,const std::string &name) {
    return Json::parse(world.conditionJson({name}))["bodies"][0];
}
void tick(LiveWorld &world) {
    world.step(dt);
    // Cutting-only comparison: this explicitly declines contact fracture,
    // as the existing blade oracle does; not a fracture validation.
    if(world.steppedBack()) for(const auto &name:world.breakable())world.declineBreak(name);
}
void coldAndHeated() {
    TileImpactRequest r;r.cell_size_m=.02;r.backend=BackendKind::CpuParallel;r.gravity_m_s2={};
    r.bodies={box("glass",MaterialPreset::Glass,{.08,.08,.08},{-1,.5,0},true),
              box("oak",MaterialPreset::Oak,{.08,.08,.08},{0,.5,0},true),
              box("iron",MaterialPreset::Iron,{.08,.08,.08},{1,.5,0},true)};
    auto world=LiveWorld::open(r);
    std::string why;const auto saved=world->snapshot(why);require(!saved.empty(),why);
    const auto begin=std::chrono::steady_clock::now();
    for(int i=0;i<100;++i) {
        const auto q=Json::parse(world->conditionJson({"glass","oak","iron"}));
        for(const auto &row:q["bodies"]) {
            require(row["state"]=="measured" && row["fraction"]==1.,"cold bonds are not whole");
            require(row["bonds"].get<unsigned>()>0 && row["broken_bonds"]==0,"no cold bond evidence");
        }
    }
    require(saved==world->snapshot(why),"inspection changed full native snapshot");
    std::cout<<"100 three-body queries: "<<std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count()<<" ms; exact unchanged snapshot\n";
    for(const auto &b:r.bodies)require(world->heat(b.name,2000.,30.)!=0,"heater refused");
    for(int i=0;i<2400;++i)tick(*world);
    bool loss=false;
    for(const auto &b:r.bodies) {
        const auto q=condition(*world,b.name);
        const auto states=world->materialStates();
        const auto found=std::find_if(states.begin(),states.end(),[&](const auto &s){return s.name==b.name;});
        require(found!=states.end(),"no native material state");
        const auto &state=*found;
        if(state.law.empty()) {
            require(q["thermal_fraction"].is_null(),"unsupported thermal law advertised whole strength");
            std::cout<<b.name<<" thermal strength unsupported: "<<q.dump()<<"\n";continue;
        }
        require(q["thermal_fraction"].is_number(),"missing supported thermal reading");
        const auto &s=state.section;
        const double expected=std::clamp(std::min({s.tension,s.compression,s.shear,s.bending,s.bending_compression}),0.,1.);
        require(std::abs(q["thermal_fraction"].get<double>()-expected)<1e-12,"thermal reading disagrees with native section law");
        loss=loss || expected<1.;
        std::cout<<b.name<<" 2 kW / 10 s, .02 m cells: "<<q.dump()<<"\n";
    }
    require(loss,"no actual heat damage/softening tested");
}
void realCuts() {
    for(const auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        TileImpactRequest r;r.cell_size_m=.01;r.backend=BackendKind::CpuParallel;r.gravity_m_s2={};
        r.bodies={box("block",material,{.1,.1,.1},{0,.5,0}),
            box("blade",MaterialPreset::Iron,{.2,.01,.03},{0,.5,.066},false,{0,0,-6})};
        auto world=LiveWorld::open(r);
        const auto cold=condition(*world,"block");require(cold["fraction"]==1.,"not whole before stroke");
        require(world->blade("blade",{-.09,.5,.051},{.09,.5,.051},{0,0,-1},.01,.00005,30.,{.09,.5,.066})!=0,"edge refused");
        for(int i=0;i<120;++i)tick(*world);
        const auto cut=condition(*world,"block");
        std::cout<<"same 6 m/s iron edge into material "<<static_cast<int>(material)<<": "<<cut.dump()<<"; cut work "<<world->blades().front().cut_work_j<<" J\n";
        if(material==MaterialPreset::Oak) {
            require(cut["state"]=="measured" && cut["fraction"].get<double>()<1.,"actual oak cut did not lower condition");
            require(cut["broken_bonds"].get<unsigned>()>0,"oak cut lost no bonds");
            for(int i=0;i<240;++i)tick(*world);
            require(condition(*world,"block")["connections_fraction"]==cut["connections_fraction"],"cut healed while drifting");
            require(world->grab("blade"),"cannot withdraw edge");
            for(const auto &p:world->poses())if(p.name=="blade")world->moveHeld(p.position_m+Vec3{0,0,.2});
            for(int i=0;i<10;++i)tick(*world);world->release();for(int i=0;i<10;++i)tick(*world);
            std::string why;const auto saved=world->snapshot(why);require(!saved.empty(),why);
            const auto before=condition(*world,"block");
            auto back=LiveWorld::open(r,saved);require(back->restored().tier=="whole",back->restored().why);
            require(condition(*back,"block")==before,"damage changed on whole-world reopen");
            require(back->park("block",why),"cannot park cut body: "+why);
            const auto parked=condition(*back,"block");
            require(parked["parked"]==true && parked["connections_fraction"]==before["connections_fraction"],"bag parking hid or healed the cut");
        } else require(world->blades().front().cut_work_j==0.,"brittle/equal-hardness target acquired unsupported blade cut");
    }
}
void boundedAndUnsupported() {
    const std::string text=R"({"bodies":[{"name":"reference","shape":"box","material":"oak","dimensions_m":[0.1,0.1,0.1],"center_m":[1,1,0]}],"precise_rigid_bodies":[{"name":"exact","material":"iron","position_m":[0,1,0],"parts":[{"dimensions_m":[0.1,0.1,0.1],"center_local_m":[0,0,0]}]}]})";
    TileImpactRequest r;r.cell_size_m=.02;r.backend=BackendKind::CpuParallel;
    r.bodies=readSceneJson(text);readSceneSettings(text,r);auto world=LiveWorld::open(r);
    const auto q=condition(*world,"exact");require(q["state"]=="unmodeled" && q["fraction"].is_null(),"exact rigid body advertised physical health");
    require(condition(*world,"missing")["fraction"].is_null(),"missing body advertised health");
    for(const auto &names:std::vector<std::vector<std::string>>{{},{"exact","exact"},{""},std::vector<std::string>(65,"exact")}) {
        bool refused=false;try{(void)world->conditionJson(names);}catch(const std::invalid_argument &){refused=true;}
        require(refused,"invalid request admitted");
    }
}
void unresolvedFracture() {
    TileImpactRequest r;r.cell_size_m=.02;r.backend=BackendKind::CpuParallel;
    auto left=box("left",MaterialPreset::Iron,{.08,.4,.2},{-.26,.2,0},true);
    auto right=left;right.name="right";right.center_m.x=.26;
    auto ball=box("ball",MaterialPreset::Iron,{.12,.12,.12},{0,3.48,0});ball.shape=BodyShape::Sphere;
    r.bodies={left,right,box("pane",MaterialPreset::Glass,{.6,.02,.2},{0,.41,0}),ball};
    auto world=LiveWorld::open(r);world->foreseeCollisions(0.);
    bool started=false;
    for(int i=0;i<2000 && !started;++i) {
        world->step(dt);
        for(const auto &name:world->breakable()) if(name=="pane") {
            const auto waiting=condition(*world,name);
            require(waiting["state"]=="unresolved" && waiting["fraction"].is_null(),"unresolved impact advertised intact health");
            started=world->beginFracture(name);break;
        }
    }
    require(started,"no actual unresolved impact tested");
    require(condition(*world,"pane")["state"]=="unresolved","pending native worker advertised known condition");
    const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(60);
    while(world->fracturePending() && std::chrono::steady_clock::now()<end) {
        if(world->fractureReady()) {(void)world->finishFracture();break;}
        world->step(dt);std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    require(!world->fracturePending(),"worker did not finish");
    const auto done=condition(*world,"pane");
    require(done["state"]=="broken" && done["fraction"]==0.,"separated pane reported whole integrity");
    std::cout<<"3 m glass impact pending -> "<<done.dump()<<"\n";
}
void separatedConnections() {
    // Same native finite-fixing experiment as the ordinary strike checkpoint.
    // No body damage is fabricated when the fixing, rather than a body, fails.
    for (const bool source_fails:{false,true})
    for (const auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        TileImpactRequest r;r.cell_size_m=.02;r.backend=BackendKind::CpuParallel;r.gravity_m_s2={};
        auto head=box("head",MaterialPreset::Iron,{.1,.1,.1},{.08,1.5,0});head.shape=BodyShape::Sphere;
        r.bodies={head,box("handle",MaterialPreset::Oak,{.04,.24,.04},{0,1.38,0}),
            box("target",material,{.1,.1,.1},{.24,1.5,0}),
            box("anchor",MaterialPreset::Iron,{.08,.08,.08},{.4,1.5,0},true)};
        auto world=LiveWorld::open(r);world->foreseeCollisions(0);
        const double capacity=source_fails?60:200;
        const auto source=world->fix("handle","head",{.02,1.49,0},{0,1,0},source_fails?capacity:0,source_fails?capacity:0);
        const auto target=world->fix("anchor","target",{.3,1.5,0},{1,0,0},source_fails?0:capacity,source_fails?0:capacity);
        require(source && target,"condition fixture cannot connect its parts");
        const Vec3 grip{0,1.3,0};
        require(world->toolPoint("head",{.12,1.5,0},{1,0,0},.04,.04,30,.1,grip,"handle")!=0,"condition fixture has no point");
        world->selectHand("condition player");require(world->wield("handle",grip),"condition fixture cannot wield");
        const std::vector<std::string> names{"handle","head","target","anchor"};
        const auto intact=Json::parse(world->conditionJson(names))["bodies"];
        for (const auto &row:intact)
            require(row["joints"].size()==1 && row["joints"][0]["attached"]==true,"intact fixing not reported");
        for (unsigned i=0;i<240;++i)tick(*world);
        LiveStroke stroke;stroke.path_m={world->hand().grip_m,world->hand().grip_m+Vec3{.14,0,0}};
        stroke.speed_m_s=4;stroke.accel_m_s2=80;stroke.lead_m=.025;stroke.give_up_s=.125;
        std::string why;require(world->stroke(stroke,why),why);
        for (unsigned i=0;i<120;++i) {
            world->step(dt);require(!world->steppedBack(),"condition fixture entered incomplete held fracture");
        }
        world->cancelStroke();const auto saved=world->snapshot(why);require(!saved.empty(),why);
        const auto broken=Json::parse(world->conditionJson(names))["bodies"];
        const auto &failure=broken[source_fails?0:2]["joints"][0];
        require(failure["id"]==(source_fails?source:target) && failure["attached"]==false,"condition lost failed connection");
        require(failure["parted_load_n"].get<double>()>capacity && failure["parted_capacity_n"]==capacity &&
                !failure["parted_because"].get<std::string>().empty(),"condition lost native failure evidence");
        require(broken[source_fails?1:3]["joints"][0]==failure,"two ends disagree about connection failure");
        for (const auto &row:broken)
            require(row["fraction"]==1 && row["broken_bonds"]==0,"joint failure manufactured internal damage");
        for (unsigned i=0;i<100;++i)
            require(Json::parse(world->conditionJson(names))["bodies"]==broken,"read-only failure history changed");
        require(world->snapshot(why)==saved,"connection inspection changed native state");
        auto reopened=LiveWorld::open(r,saved);
        require(reopened->restored().tier=="whole" && Json::parse(reopened->conditionJson(names))["bodies"]==broken,
                "connection condition/history changed on whole reopen");
        if (source_fails) {
            const auto head_pose=world->poses().front();
            require(world->park("handle",why),"separated handle cannot be stored with history: "+why);
            require(world->parked("handle") && !world->parked("head"),"stowing handle also stored its detached head");
            const auto packed=Json::parse(world->conditionJson(names))["bodies"];
            require(packed[0]["joints"][0]==failure && packed[1]["joints"][0]==failure,
                    "parking erased or healed failure history");
            const auto away=world->snapshot(why);require(!away.empty(),why);
            auto bag=LiveWorld::open(r,away);bag->selectHand("another player");
            require(!bag->unpark("handle",{0,1.38,0},{1,0,0,0},why),"another player took the separated handle from the bag");
            bag->selectHand("condition player");
            require(bag->unpark("handle",{0,1.38,0},{1,0,0,0},why),"separated handle cannot come back: "+why);
            require(condition(*bag,"handle")["joints"][0]==failure && !bag->toolPoints().front().grip_connected,
                    "unpark repaired failed fixing or working point");
            require(bag->poses().front().position_m.x==head_pose.position_m.x &&
                    bag->poses().front().position_m.y==head_pose.position_m.y &&
                    bag->poses().front().position_m.z==head_pose.position_m.z,
                    "bag operations moved the detached head in the world");
        }
        std::cout<<"condition / "<<(source_fails?"tool":"target")<<" / "<<materialPresetName(material)
            <<": "<<failure.dump()<<"; intact constituent bonds; read-only and whole reopen\n";
    }
}
}
int main() {
    try{coldAndHeated();realCuts();boundedAndUnsupported();unresolvedFracture();separatedConnections();std::cout<<"5 native condition cases passed\n";return 0;}
    catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}
}
