#include "rigid/JoltWorld.hpp"
#include "physics/CohesiveInterface.hpp"
#include "material/MaterialCatalog.hpp"
#include <Jolt/Jolt.h>
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <stdexcept>
using namespace banjo;
// Isolated coupling experiment, deliberately not an application stepping API:
// two separated boxes, one axial cohesive connector, no gravity or other bodies.
// Jolt performs drift; the material law supplies both velocity-Verlet kicks.
// A failed run is diagnostic evidence, not a partly accepted world transaction.
int main(int argc,char **argv){try {
    if(argc<2||argc>3||(argc==3&&std::string(argv[2])!="--require-accuracy"))
        throw std::invalid_argument("usage: banjo_runtime_cohesive_probe OUTPUT.csv [--require-accuracy]");
    unsigned failures=0;
    std::ofstream out(argv[1]);if(!out)throw std::runtime_error("cannot open report");
    out<<std::setprecision(17)<<"material,position_bits,offset_m,mode,steps,duration_s,opening_m,separated,damage_j,initial_energy_j,max_energy_error_j,transfer_error_sum_j,absolute_transfer_error_sum_j,max_splitting_error_j,max_momentum_error,oracle_relative_error\n";
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})
    for(double offset:{0.,10.})for(bool fracture:{false,true})for(unsigned count:{128u,256u,512u,1024u}) {
        const auto m=makeReferenceMaterial(preset);const double side=.02,area=.0001,rest=.001;
        const CohesiveInterfaceLaw law{2*m.tensile_strength_pa*m.tensile_strength_pa/m.fracture_energy_j_m2,m.tensile_strength_pa,m.fracture_energy_j_m2,area};
        const double q0=fracture?0:.4*cohesiveDamageOpening(law),work=area*m.fracture_energy_j_m2;
        JoltWorld world;world.setGravity({});
        world.addBox({1,{side,side,side},m,{{offset-.5*(side+rest+q0),0,0},{},{},{}},false});
        world.addBox({2,{side,side,side},m,{{offset+.5*(side+rest+q0),0,0},{},{},{}},false});
        world.setPairContactOwner(1,2,PairContactOwner::External);
        const auto a=world.mechanicalState(1),b=world.mechanicalState(2);const double mu=1/(1/a.mass_kg+1/b.mass_kg);
        const double speed=fracture?std::sqrt(12*work/mu):0,omega=std::sqrt(area*law.stiffness_pa_per_m/mu);
        auto am=a.motion,bm=b.motion;am.linear_velocity_m_s={-speed/2,0,0};bm.linear_velocity_m_s={speed/2,0,0};
        world.applyRigidState(1,am);world.applyRigidState(2,bm);
        // Use the inserted separation as reference, retaining the chosen initial
        // strain exactly; this excludes initial placement quantization from the
        // measured subsequent drift error.
        const double reference=b.motion.center_of_mass_world_m.x-a.motion.center_of_mass_world_m.x-q0;
        CohesiveInterfaceState history{q0,q0};auto response=evaluateCohesiveInterface(law,history);
        const auto initial=world.mechanicalTotals();const double e0=initial.kinetic_energy_j+response.stored_energy_j;
        const double duration=fracture?8*cohesiveSeparationOpening(law)/speed:std::numbers::pi/(4*omega);
        const double dt=static_cast<float>(duration/count);double max_e=0,transfer_error=0,absolute_transfer_error=0,max_splitting_error=0,max_p=0;
        const auto kick=[&](double force) {
            const auto sa=world.snapshot(1),sb=world.snapshot(2);
            const auto receipt=world.applyPairImpulse(1,2,sa.center_of_mass_world_m+Vec3{side/2,0,0},
                sb.center_of_mass_world_m-Vec3{side/2,0,0},{force*dt/2,0,0},std::max(1e-12,work*1e-4));
            transfer_error+=receipt.numerical_energy_change_j;
            absolute_transfer_error+=std::abs(receipt.numerical_energy_change_j);
        };
        for(unsigned i=0;i<count;++i) {
            kick(response.force_n);world.step(dt);
            const auto sa=world.snapshot(1),sb=world.snapshot(2);
            const double q=sb.center_of_mass_world_m.x-sa.center_of_mass_world_m.x-reference;
            const auto increment=advanceCohesiveInterface(law,history,q);history=increment.state;response=increment.response;
            kick(response.force_n);const auto total=world.mechanicalTotals();
            const double error=total.kinetic_energy_j+response.stored_energy_j+response.dissipated_energy_j-e0;
            max_e=std::max(max_e,std::abs(error));max_splitting_error=std::max(max_splitting_error,std::abs(error-transfer_error));
            max_p=std::max(max_p,length(total.linear_momentum_kg_m_s-initial.linear_momentum_kg_m_s));
            if(!world.drainImpacts().empty())throw std::runtime_error("isolated connector received a Jolt impact");
        }
        const double actual_speed=world.snapshot(2).linear_velocity_m_s.x-world.snapshot(1).linear_velocity_m_s.x;
        const double oracle_error=fracture?std::abs(actual_speed-std::sqrt(2*(e0-work)/mu))/speed:
            std::abs(history.opening_m-q0*std::cos(omega*dt*count))/q0;
        out<<materialPresetName(preset)<<','<<8*sizeof(JPH::Real)<<','<<offset<<','<<(fracture?"separation":"elastic")<<','<<count<<','<<dt*count<<','<<history.opening_m<<','<<response.separated<<','<<response.dissipated_energy_j<<','<<e0<<','<<max_e<<','<<transfer_error<<','<<absolute_transfer_error<<','<<max_splitting_error<<','<<max_p<<','<<oracle_error<<'\n';
        if(count==1024) {
            const bool accurate=fracture?(response.separated&&std::abs(response.dissipated_energy_j-work)<work*1e-12&&max_e<work*1e-4&&oracle_error<1e-5):
                (!response.separated&&response.dissipated_energy_j==0&&max_e<e0*1e-5&&oracle_error<1e-6);
            if(!accurate){++failures;std::cerr<<"Accuracy unmet: "<<materialPresetName(preset)<<" offset="<<offset<<" mode="<<(fracture?"separation":"elastic")<<'\n';}
        }
    }
    out.close();if(!out)throw std::runtime_error("cannot write report");
    std::cout<<"Position bits="<<8*sizeof(JPH::Real)<<"; 48 experiments; finest accuracy failures="<<failures<<"/12\n";
    return argc==3&&failures?2:0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
