#include "fastlattice/LiveWorld.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>

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
}
int main() {
    try {
        visibleIsNotReachable();
        for(const auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})
            for(const auto &family:{std::string("pick"),std::string("shovel"),std::string("hoe"),std::string("uncatalogued-q7")})
                fixture(material,family,family=="shovel"?.28:.20);
        std::cout<<"generic native pickup admission checks passed\n";return 0;
    } catch(const std::exception &e) {std::cerr<<e.what()<<"\n";return 1;}
}
