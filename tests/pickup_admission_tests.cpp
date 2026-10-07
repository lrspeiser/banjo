#include "fastlattice/LiveWorld.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <nlohmann/json.hpp>

using namespace banjo;
using namespace banjo::fastlattice;

namespace {
void require(bool value,const char *message) { if(!value)throw std::runtime_error(message); }
SceneBody box(const std::string &name,MaterialPreset material,const Vec3 &dimensions,const Vec3 &center) {
    SceneBody b;b.name=name;b.shape=BodyShape::Box;b.material=material;
    b.dimensions_m=dimensions;b.center_m=center;return b;
}
void fixture(MaterialPreset material,const std::string &family,double head_width) {
    TileImpactRequest request;request.cell_size_m=.02;
    const std::string head=family+" head",handle=family+" handle";
    request.bodies={box(head,material,{head_width,.08,.08},{0,.5,1}),
        box(handle,material,{.04,.8,.04},{0,.94,1})};
    auto world=LiveWorld::open(request);world->foreseeCollisions(0);
    require(world->fix(handle,head,{0,.54,1},{0,1,0},5000,5000)!=0,"fixture fixing rejected");
    const Vec3 grip{0,1.2,1};
    require(world->toolPoint(head,{0,.46,1},{0,-1,0},.04,.04,30,.1,grip,handle)!=0,
        "declared functional grip rejected");
    world->spawnNativePlayer("alice",{0,0,0});world->selectHand("alice");
    const Vec3 from{0,1.62,0},toward=Vec3{0,.5,1}-from;
    const Vec3 direction=toward/length(toward);
    const auto hit=world->pick(from,direction,2);
    require(hit.hit&&!hit.name.empty(),"fixture ray missed actual matter");
    std::string why;const auto before=world->snapshot(why);
    const auto mass_before=world->carriedObjectsKg();
    double assembly_before=0;for(const auto &pose:world->poses())assembly_before+=pose.mass_kg;
    const auto admission=world->pickupAdmission(hit.name,from,direction,2);
    require(admission.admitted,"valid physical pickup was refused");
    require(length(admission.grip_world_m-grip)<1e-9,"pickup lost declared handle grip");
    require(world->snapshot(why)==before,"eligibility query changed physical state");
    require(world->carriedObjectsKg()==mass_before,"eligibility query changed custody/mass");
    require(!world->pickupAdmission(hit.name,{10,1.62,0},direction,2).admitted,"spoofed eye admitted");
    require(!world->pickupAdmission("missing",from,direction,2).admitted,"missing target admitted");
    require(!world->pickupAdmission(hit.name,from,direction*2,2).admitted,"non-unit ray admitted");
    require(!world->pickupAdmission(hit.name,from,direction,3).admitted,"unbounded reach admitted");
    require(!world->wield(hit.name,{3,1.2,1}),"legacy wield accepted an unreachable native grip");
    require(world->hand().holding.empty(),"refused wield changed the native hand");
    require(world->wield(hit.name,admission.grip_world_m),"admitted physical grip failed");
    world->step(1.0/240.0);
    require(world->hand().holding==hit.name,"native physical batch lost valid hold");
    const auto denied=world->pickupAdmission(hit.name,from,direction,2);
    require(!denied.admitted&&denied.reason=="already_holding","second pickup changed own hold");
    world->spawnNativePlayer("bob",{.5,0,0});world->selectHand("bob");
    const Vec3 bob_from{.5,1.62,0};const auto bob_toward=Vec3{0,.5,1}-bob_from;
    const auto contested=world->pickupAdmission(hit.name,bob_from,bob_toward/length(bob_toward),2);
    require(!contested.admitted&&contested.reason=="held_by_another_actor","another actor took fixed assembly");
    world->selectHand("alice");world->release();require(world->hand().holding.empty(),"release did not clear native hand");
    double total=0;for(const auto &pose:world->poses())total+=pose.mass_kg;
    require(std::abs(total-assembly_before)<1e-9,"pickup/release changed assembly mass");
    const auto label=material==MaterialPreset::Glass?"glass":material==MaterialPreset::Oak?"oak":"iron";
    std::cout<<family<<", material="<<label<<", dt=1/240, cell=.02, assembly kg="<<total<<", mass residual="<<total-assembly_before<<"\n";
}

void visibleIsNotReachable() {
    TileImpactRequest request;request.cell_size_m=.02;
    request.bodies={box("near-view-boundary",MaterialPreset::Iron,{.1,.1,.1},{0,1.4,1.95})};
    auto world=LiveWorld::open(request);world->spawnNativePlayer("alice",{0,0,0});world->selectHand("alice");
    const Vec3 from{0,1.62,0},toward=Vec3{0,1.4,1.95}-from;
    const Vec3 direction=toward/length(toward);
    require(world->pick(from,direction,2).hit,"visible-boundary fixture missed");
    const auto result=world->pickupAdmission("near-view-boundary",from,direction,2);
    require(!result.admitted&&result.reason=="out_of_reach","visible object beyond physical arm admitted");
}

void carryTravel(MaterialPreset material) {
    TileImpactRequest request;request.cell_size_m=.04;
    auto floor=box("floor",MaterialPreset::Iron,{10,.04,10},{0,-.02,0});floor.anchored=true;
    request.bodies={floor,box("unfamiliar head",material,{.12,.08,.12},{.65,1.05,.7}),
        box("unfamiliar handle",material,{.04,.4,.04},{.65,1.29,.7})};
    auto world=LiveWorld::open(request);world->foreseeCollisions(0);
    require(world->fix("unfamiliar handle","unfamiliar head",{.65,1.09,.7},{0,1,0},5000,5000)!=0,
        "carry fixture fixing rejected");
    const Vec3 grip{.65,1.4,.7};
    require(world->toolPoint("unfamiliar head",{.65,1.01,.7},{0,-1,0},.04,.04,30,.1,grip,"unfamiliar handle")!=0,
        "carry fixture functional point rejected");
    require(!world->carryWithNativePlayer(),"editor empty hand acquired native carry");
    world->spawnNativePlayer("alice",{0,0,0});world->selectHand("alice");
    require(!world->carryWithNativePlayer(),"native empty hand acquired carry");
    require(world->wield("unfamiliar head",grip),"carry fixture wield refused");
    const auto before=world->poses();
    require(world->carryWithNativePlayer(),"native carry refused valid physical grip");
    const auto after=world->poses();
    for(std::size_t i=0;i<before.size();++i)
        require(length(before[i].position_m-after[i].position_m)==0&&length(before[i].velocity_m_s-after[i].velocity_m_s)==0,
            "enabling carry assigned a held body pose or velocity");
    const auto actor_before=world->nativePlayers().front().state;
    const Quat inverse{actor_before.orientation_world.w,-actor_before.orientation_world.x,
        -actor_before.orientation_world.y,-actor_before.orientation_world.z};
    const Vec3 local_grip=inverse.rotate(grip-actor_before.center_of_mass_world_m);
    double mass_before=0;for(const auto &p:before)if(!p.anchored)mass_before+=p.mass_kg;
    for(int i=0;i<480;++i) {
        if(i%40==0)world->setNativePlayerWalk("alice",{1.5,0,0},0,.25);
        world->step(1.0/240);
        require(world->hand().holding=="unfamiliar head","travel released a valid native grip");
        require(length(world->hand().force_n)<=800+1e-8,"carry exceeded the declared hand force cap");
    }
    for(int i=0;i<480;++i) {
        // Turn while walking: the retained locomotion model leaves passive
        // foot friction on a standing actor, which can block in-place yaw.
        if(i%40==0)world->setNativePlayerWalk("alice",{0,0,.3},std::acos(-1.0)/2,.25);
        world->step(1.0/240);
        require(world->hand().holding=="unfamiliar head","turn released a valid native grip");
    }
    const auto actor=world->nativePlayers().front().state;
    const auto hand=world->hand();
    const Vec3 expected=actor.center_of_mass_world_m+actor.orientation_world.rotate(local_grip);
    require(actor.center_of_mass_world_m.x-actor_before.center_of_mass_world_m.x>1.5,"carry test did not actually travel");
    require(actor.orientation_world.rotate({0,0,1}).x>.8,"native actor did not actually turn toward the requested heading");
    for(const auto &pose:world->poses())if(pose.name=="unfamiliar head") {
        const auto &q=pose.orientation_wxyz;
        require(Quat{q[0],q[1],q[2],q[3]}.rotate({0,0,1}).x>.8,"physical carried assembly did not turn with the actor");
    }
    require(length(hand.target_m-expected)<.02,"desired carry frame did not follow actual native body");
    require(length(hand.grip_m-hand.target_m)<.02,"bounded physical grip did not follow carry target");
    require(hand.carrying_with_native_player&&world->carryingWithNativePlayer(),"native carry ownership disappeared");
    double mass_after=0;for(const auto &p:world->poses())if(!p.anchored)mass_after+=p.mass_kg;
    require(std::abs(mass_after-mass_before)<1e-9,"carry travel changed assembly mass");
    std::string why;const auto saved=world->snapshot(why);require(!saved.empty(),why.c_str());
    auto reopened=LiveWorld::open(request,saved);reopened->selectHand("alice");
    require(reopened->restored().tier=="whole","native carry reopened through a fallback tier");
    auto invalid=nlohmann::json::parse(saved);
    invalid["player_hands"]["alice"]["native_carry"]["model"]="unsupported";
    bool refused=false;try{auto bad=LiveWorld::open(request,invalid.dump());(void)bad;}catch(const std::exception &){refused=true;}
    require(refused,"unsupported saved native carry silently reopened a fresh world");
    auto older=nlohmann::json::parse(saved);older["player_hands"]["alice"].erase("native_carry");
    auto legacy=LiveWorld::open(request,older.dump());legacy->selectHand("alice");
    require(legacy->restored().tier=="whole"&&!legacy->carryingWithNativePlayer(),"old world-relative hand was not preserved");
    require(reopened->hand().holding=="unfamiliar head"&&reopened->carryingWithNativePlayer(),"reopen lost native carry identity");
    const auto saved_pose=reopened->nativePlayers().front().state;
    reopened->setNativePlayerWalk("alice",{0,0,-1},0,.25);
    for(int i=0;i<48;++i)reopened->step(1.0/240);
    const auto now=reopened->nativePlayers().front().state;
    require(length(reopened->hand().target_m-(now.center_of_mass_world_m+now.orientation_world.rotate(local_grip)))<.02,
        "restored hand reverted to a world-fixed target");
    require(length(now.center_of_mass_world_m-saved_pose.center_of_mass_world_m)>.02,"restored carry did not travel");
    reopened->moveHeld(reopened->hand().target_m);
    require(!reopened->carryingWithNativePlayer(),"manual hand movement retained competing carry authority");
    require(reopened->carryWithNativePlayer(),"could not reacquire carry after explicit hand movement");
    reopened->release();require(!reopened->carryingWithNativePlayer()&&reopened->hand().holding.empty(),"drop retained carry authority");
    const auto label=material==MaterialPreset::Glass?"glass":material==MaterialPreset::Oak?"oak":"iron";
    std::cout<<"carry "<<label<<", cell=.04, dt=1/240, travel m="<<actor.center_of_mass_world_m.x-actor_before.center_of_mass_world_m.x
        <<", grip error m="<<length(hand.grip_m-hand.target_m)<<", assembly kg="<<mass_before<<", mass residual kg="<<mass_after-mass_before
        <<", hand work J="<<hand.work_j<<"\n";
}

void separateCarryOwners() {
    TileImpactRequest request;request.cell_size_m=.04;
    auto floor=box("floor",MaterialPreset::Iron,{10,.04,10},{0,-.02,0});floor.anchored=true;
    request.bodies={floor,box("alpha",MaterialPreset::Iron,{.08,.08,.08},{-.5,1.3,.7}),
        box("beta",MaterialPreset::Iron,{.08,.08,.08},{.5,1.3,.7})};
    auto world=LiveWorld::open(request);world->foreseeCollisions(0);
    world->spawnNativePlayer("alice",{-.5,0,0});world->spawnNativePlayer("bob",{.5,0,0});
    world->selectHand("alice");require(world->wield("alpha",{-.5,1.3,.7})&&world->carryWithNativePlayer(),"alice carry failed");
    world->selectHand("bob");require(world->wield("beta",{.5,1.3,.7})&&world->carryWithNativePlayer(),"bob carry failed");
    for(int i=0;i<300;++i) {
        if(i%40==0){world->setNativePlayerWalk("alice",{-1.2,0,0},0,.25);world->setNativePlayerWalk("bob",{1.2,0,0},0,.25);}
        world->step(1.0/240);
    }
    const auto hands=world->playerHands();
    require(hands.at("alice").holding=="alpha"&&hands.at("alice").carrying_with_native_player&&hands.at("alice").grip_m.x<-1,
        "alice travel lost physical carry ownership");
    require(hands.at("bob").holding=="beta"&&hands.at("bob").carrying_with_native_player&&hands.at("bob").grip_m.x>1,
        "bob travel lost physical carry ownership");
    world->selectHand("alice");world->aimHeld({});require(!world->carryingWithNativePlayer(),"explicit wrist kept competing carry authority");
    world->selectHand("bob");require(world->carryingWithNativePlayer(),"alice wrist command changed bob carry");
    world->selectHand("alice");require(world->carryWithNativePlayer(),"alice carry could not resume");
    require(world->removeNativePlayer("alice"),"actor removal refused");
    require(world->hand().holding.empty()&&!world->carryingWithNativePlayer(),"departed actor retained physical hand authority");
    world->selectHand("bob");world->step(1.0/240);
    require(world->hand().holding=="beta"&&world->carryingWithNativePlayer(),"alice removal changed bob physical carry");
}
}
int main() {
    try {
        visibleIsNotReachable();
        separateCarryOwners();
        for(const auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})carryTravel(material);
        for(const auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})
            for(const auto &family:{std::string("pick"),std::string("shovel"),std::string("hoe"),std::string("uncatalogued-q7")})
                fixture(material,family,family=="shovel"?.28:.20);
        std::cout<<"generic native pickup admission checks passed\n";return 0;
    } catch(const std::exception &e) {std::cerr<<e.what()<<"\n";return 1;}
}
