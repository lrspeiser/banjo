#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include <iostream>
#include <stdexcept>
#include <algorithm>
using namespace banjo;
void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
template<class F>void rejects(F f){bool bad=false;try{f();}catch(const std::invalid_argument&){bad=true;}require(bad,"unsupported tensile kick must reject");}
void bodies(JoltWorld &world,const MaterialDefinition &material,double distance,double closing=0) {
    world.setGravity({});world.addBox({1,{.1,.1,.1},material,{{-distance/2,0,0},{},{closing,0,0},{}},false});
    world.addBox({2,{.1,.1,.1},material,{{distance/2,0,0},{},{-closing,0,0},{}},false});
}
int main(){try {
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto material=makeReferenceMaterial(preset);
        // Explicit compliant interface example: its 5/20 mm onset/failure
        // openings are declared independently of the bulk tensile strength.
        const double gc=material.fracture_energy_j_m2,area=.001,rest=.12;
        const CohesiveInterfaceLaw law{(2*gc/.02)/.005,2*gc/.02,gc,area};
        JoltWorld sample;bodies(sample,material,.122);
        if(JoltWorld::positionPrecisionBits()!=64) {
            rejects([&]{(void)sample.applyCohesiveTensionKick(1,2,{},{},rest,law,{},.001,1);});continue;
        }
        const auto original=sample.snapshot(1);
        auto compression=law;compression.compression_stiffness_pa_per_m=law.stiffness_pa_per_m;
        rejects([&]{(void)sample.applyCohesiveTensionKick(1,2,{},{},rest,compression,{},.001,1);});
        sample.setPairContactOwner(1,2,PairContactOwner::External);
        rejects([&]{(void)sample.applyCohesiveTensionKick(1,2,{},{},rest,law,{},.001,1);});
        sample.setPairContactOwner(1,2,PairContactOwner::Jolt);
        rejects([&]{(void)sample.applyCohesiveTensionKick(1,2,{},{},rest,law,{},0,1);});
        require(length(sample.snapshot(1).linear_velocity_m_s-original.linear_velocity_m_s)==0,"rejected kick does not mutate body");
        if(preset==MaterialPreset::Glass) {
            RigidBallDescription activated;activated.body_id=3;activated.radius_m=.05;activated.material=material;
            activated.position_world_m={1,0,0};activated.defer_brittle_contacts_to_material=true;sample.addBall(activated);
            rejects([&]{(void)sample.applyCohesiveTensionKick(1,3,{},{},1,law,{},.001,1);});
        }

        // Failed connector must leave actual collision trajectories unchanged.
        JoltWorld plain,failed;bodies(plain,material,rest,1);bodies(failed,material,rest,1);
        CohesiveInterfaceState broken{0,cohesiveSeparationOpening(law)};unsigned events=0;
        for(unsigned i=0;i<40;++i) {
            const auto kick=failed.applyCohesiveTensionKick(1,2,{},{},rest,law,broken,1.0/240,1e-8);
            broken=kick.interface_increment.state;
            require(kick.interface_increment.response.force_n==0&&kick.interface_increment.response.dissipated_energy_j==area*gc,"failure retains fracture work without duplicate compression");
            plain.step(1.0/240);failed.step(1.0/240);events+=static_cast<unsigned>(failed.drainImpacts().size());(void)plain.drainImpacts();
            for(auto id:{1u,2u})require(length(plain.snapshot(id).center_of_mass_world_m-failed.snapshot(id).center_of_mass_world_m)<1e-7&&
                length(plain.snapshot(id).linear_velocity_m_s-failed.snapshot(id).linear_velocity_m_s)<1e-6,"failed connector preserves ordinary Jolt contact response");
        }
        require(events>0&&failed.snapshot(1).linear_velocity_m_s.x<.5,"failed bodies actually collide");

        double previous_error=0;
        for(unsigned count:{1024u,2048u}) {
            JoltWorld world;bodies(world,material,.122);
            const double distance=world.snapshot(2).center_of_mass_world_m.x-world.snapshot(1).center_of_mass_world_m.x;
            CohesiveInterfaceState history{distance-rest,distance-rest};
            auto response=evaluateCohesiveInterface(law,history);
            const double mass=world.mechanicalState(1).mass_kg,omega=std::sqrt(2*area*law.stiffness_pa_per_m/mass);
            const double dt=static_cast<float>(24/(omega*count)),e0=response.stored_energy_j;
            double jolt_change=0,transfer_error=0,max_error=0,max_energy=e0,min_distance=distance,max_p=0;
            unsigned contacts=0;bool pulled=false;
            const auto kick=[&] {
                const auto r=world.applyCohesiveTensionKick(1,2,{},{},rest,law,history,dt/2,e0*1e-4);
                history=r.interface_increment.state;response=r.interface_increment.response;
                transfer_error+=r.transfer.numerical_energy_change_j;pulled=pulled||response.force_n>0;
            };
            for(unsigned i=0;i<count;++i) {
                kick();const double before=world.mechanicalTotals().kinetic_energy_j;
                world.step(dt);const auto drift=world.mechanicalTotals();jolt_change+=drift.kinetic_energy_j-before;
                contacts+=static_cast<unsigned>(world.drainImpacts().size());kick();
                const auto total=world.mechanicalTotals();const double energy=total.kinetic_energy_j+response.stored_energy_j+response.dissipated_energy_j;
                max_energy=std::max(max_energy,energy);max_error=std::max(max_error,std::abs(energy-e0-jolt_change-transfer_error));
                max_p=std::max(max_p,length(total.linear_momentum_kg_m_s));
                min_distance=std::min(min_distance,length(world.snapshot(2).center_of_mass_world_m-world.snapshot(1).center_of_mass_world_m));
            }
            require(pulled&&contacts>0,"one trajectory contains tensile loading and surface collision");
            require(min_distance>.098&&min_distance<.1005,"surfaces reach contact with bounded penetration, not merely a speculative event");
            require(jolt_change<0&&max_energy<e0*1.001,"Jolt-stage energy change is measured without unexplained gain");
            require(max_error<e0*.001&&max_p<1e-7*mass,"coupled trajectory work and momentum bounds");
            if(previous_error>0)require(max_error<previous_error,"coupled splitting error improves under refinement");previous_error=max_error;
            std::cout<<materialPresetName(preset)<<" steps="<<count<<" contacts="<<contacts<<" min_distance="<<min_distance<<" jolt_dE="<<jolt_change<<" split_error="<<max_error<<" split_relative="<<max_error/e0<<" max_P="<<max_p<<'\n';
        }
    }
    std::cout<<"[PASS] tensile coupling retains Jolt surfaces and accounts for contact-stage energy\n";return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
