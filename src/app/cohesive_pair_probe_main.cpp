#include "physics/CohesivePair.hpp"
#include "material/MaterialCatalog.hpp"
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
using namespace banjo;
int main(int argc,char **argv){try{
    if(argc!=2)throw std::invalid_argument("Usage: banjo_cohesive_pair_probe OUTPUT.csv");std::ofstream out(argv[1]);if(!out)throw std::runtime_error("Cannot create pair report");out<<std::setprecision(17);
    out<<"material,energy_ratio,step,time_s,mass_a_kg,mass_b_kg,area_m2,Gc_j_m2,opening_m,maximum_opening_m,velocity_a_m_s,velocity_b_m_s,kinetic_energy_j,stored_energy_j,dissipated_energy_j,energy_residual_j,momentum_kg_m_s,impulse_on_a_n_s,substeps,separated\n";
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        const auto m=makeReferenceMaterial(preset);const double area=.0001,ma=m.density_kg_m3*area*.01,mb=2*ma,mu=1/(1/ma+1/mb),budget=area*m.fracture_energy_j_m2;
        const CohesiveInterfaceLaw law{2*m.tensile_strength_pa*m.tensile_strength_pa/m.fracture_energy_j_m2,m.tensile_strength_pa,m.fracture_energy_j_m2,area};
        for(double ratio:{.5,1.5}){
            const double speed=std::sqrt(2*ratio*budget/mu),duration=8*cohesiveSeparationOpening(law)/speed,dt=duration/512;
            CohesivePairState state{0,-mb/(ma+mb)*speed,ma/(ma+mb)*speed,{}};
            for(unsigned i=1;i<=512;++i){const auto step=advanceCohesivePair(law,ma,mb,state,dt);state=step.state;const auto response=evaluateCohesiveInterface(law,state.interface);
                const double ke=.5*ma*state.velocity_a_m_s*state.velocity_a_m_s+.5*mb*state.velocity_b_m_s*state.velocity_b_m_s;
                out<<materialPresetName(preset)<<','<<ratio<<','<<i<<','<<i*dt<<','<<ma<<','<<mb<<','<<area<<','<<m.fracture_energy_j_m2<<','<<state.interface.opening_m<<','<<state.interface.maximum_opening_m<<','<<state.velocity_a_m_s<<','<<state.velocity_b_m_s<<','<<ke<<','<<response.stored_energy_j<<','<<response.dissipated_energy_j<<','<<ke+response.stored_energy_j+response.dissipated_energy_j-ratio*budget<<','<<ma*state.velocity_a_m_s+mb*state.velocity_b_m_s<<','<<step.impulse_on_a_n_s<<','<<step.substeps<<','<<response.separated<<'\n';
            }
        }
    }
    out.close();if(!out)throw std::runtime_error("Cannot write pair report");return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
