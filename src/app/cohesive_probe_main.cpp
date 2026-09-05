#include "physics/CohesiveInterface.hpp"
#include "material/MaterialCatalog.hpp"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
using namespace banjo;
int main(int argc,char **argv){try{
    if(argc!=2)throw std::invalid_argument("Usage: banjo_cohesive_probe OUTPUT.csv");
    std::ofstream out(argv[1]);if(!out)throw std::runtime_error("Cannot create coupon report");out<<std::setprecision(17);
    out<<"material,phase,increment,area_m2,stiffness_pa_per_m,strength_pa,Gc_j_m2,opening_m,maximum_opening_m,traction_pa,damage,stored_energy_j,dissipated_energy_j,opening_work_j,cumulative_work_j,balance_residual_j\n";
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        const auto material=makeReferenceMaterial(preset);const double strength=material.tensile_strength_pa,gc=material.fracture_energy_j_m2;
        const CohesiveInterfaceLaw law{2*strength*strength/gc,strength,gc,.0001};const double failure=cohesiveSeparationOpening(law);
        CohesiveInterfaceState state;double work=0;
        for(unsigned phase=0;phase<3;++phase)for(unsigned i=1;i<=100;++i){
            const double t=static_cast<double>(i)/100;const double opening=failure*(phase==0?.6*t:phase==1?.6*(1-t):1.2*t);
            const auto step=advanceCohesiveInterface(law,state,opening);state=step.state;work+=step.opening_work_j;
            out<<materialPresetName(preset)<<','<<phase<<','<<i<<','<<law.area_m2<<','<<law.stiffness_pa_per_m<<','<<strength<<','<<gc<<','<<opening<<','<<state.maximum_opening_m<<','<<step.response.traction_pa<<','<<step.response.damage<<','<<step.response.stored_energy_j<<','<<step.response.dissipated_energy_j<<','<<step.opening_work_j<<','<<work<<','<<step.balance_residual_j<<'\n';
        }
    }
    out.close();if(!out)throw std::runtime_error("Cannot write coupon report");return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
