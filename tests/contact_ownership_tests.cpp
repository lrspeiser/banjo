#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace banjo;
void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
template<class F> void rejects(F f){bool rejected=false;try{f();}catch(const std::invalid_argument&){rejected=true;}require(rejected,"invalid ownership must reject");}
void step(JoltWorld &w,unsigned count){for(unsigned i=0;i<count;++i)w.step(1.0/240);}
int main(){try {
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto material=makeReferenceMaterial(preset);
        // Equal bodies in free flight: suppressing their pair must add no impulse.
        JoltWorld free;free.setGravity({});
        free.addBox({1,{.1,.1,.1},material,{{-.15,0,0},{},{1,0,0},{}},false});
        free.addBox({2,{.1,.1,.1},material,{{.15,0,0},{},{-1,0,0},{}},false});
        const auto before=free.mechanicalTotals();free.setPairContactOwner(2,1,PairContactOwner::External);step(free,72);const auto after=free.mechanicalTotals();
        require(std::abs(after.kinetic_energy_j-before.kinetic_energy_j)<1e-12+1e-7*before.kinetic_energy_j&&length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s)<1e-12,"suppression conserves free-flight energy and momentum");
        const auto a=free.snapshot(1),b=free.snapshot(2);
        require(a.center_of_mass_world_m.x>b.center_of_mass_world_m.x,"external pair receives no Jolt blocking response");
        require(std::abs(a.linear_velocity_m_s.x-1)<1e-6&&std::abs(b.linear_velocity_m_s.x+1)<1e-6,"suppression adds no impulse");
        require(std::abs(a.center_of_mass_world_m.x-.15)<1e-5&&std::abs(b.center_of_mass_world_m.x+.15)<1e-5,"free flight follows the independent trajectory");
        require(free.drainImpacts().empty(),"external pair emits no Jolt impact event");
        // A warmed/sleeping contact must be invalidated, while another pair stays supported.
        JoltWorld world;world.setGravity({0,-9.81,0});
        world.addBox({10,{1,.1,1},material,{{0,0,0},{},{},{}},true});
        world.addBox({1,{.1,.1,.1},material,{{-.2,.11,0},{},{},{}},false});
        world.addBox({2,{.1,.1,.1},material,{{.2,.11,0},{},{},{}},false});step(world,240);
        const double supported=world.snapshot(1).center_of_mass_world_m.y;
        require(supported>.075&&world.snapshot(2).center_of_mass_world_m.y>.075,"both pairs initially supported");(void)world.drainImpacts();
        rejects([&]{world.setPairContactOwner(1,1,PairContactOwner::External);});rejects([&]{world.setPairContactOwner(1,99,PairContactOwner::External);});
        rejects([&]{world.setPairContactOwner(1,10,static_cast<PairContactOwner>(99));});
        world.setPairContactOwner(1,10,PairContactOwner::External);world.setPairContactOwner(10,1,PairContactOwner::External);
        require(world.pairContactOwner(10,1)==PairContactOwner::External&&world.pairContactOwner(2,10)==PairContactOwner::Jolt,"ownership is symmetric and pair-specific");step(world,72);
        const double falling=world.snapshot(1).center_of_mass_world_m.y,retained=world.snapshot(2).center_of_mass_world_m.y;
        require(falling<-.1&&retained>.075,"cached contact is removed without disabling unrelated support");
        for(const auto &event:world.drainImpacts())require(!(event.involves(1)&&event.involves(10)),"suppressed pair has no contact event");
        world.setPairContactOwner(10,1,PairContactOwner::Jolt);world.applyRigidState(1,{{-.2,.3,0},{},{},{}});step(world,240);
        require(world.snapshot(1).center_of_mass_world_m.y>.075,"Jolt collision resumes after ownership returns");
        world.setPairContactOwner(1,10,PairContactOwner::External);world.removeAndDestroy(1);
        world.addBox({1,{.1,.1,.1},material,{{-.2,.3,0},{},{},{}},false});
        require(world.pairContactOwner(1,10)==PairContactOwner::Jolt,"removed ownership cannot leak into reused logical IDs");step(world,240);require(world.snapshot(1).center_of_mass_world_m.y>.075,"recreated body collides normally");
        std::cout<<materialPresetName(preset)<<" supported-y="<<supported<<" external-y="<<falling<<" other-y="<<retained<<" free-x="<<a.center_of_mass_world_m.x<<" free-dE="<<(after.kinetic_energy_j-before.kinetic_energy_j)<<'\n';
    }
    std::cout<<"[PASS] pair contact ownership, cache invalidation, restore and ID reuse\n";return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
