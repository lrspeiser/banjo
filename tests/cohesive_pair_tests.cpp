#include "physics/CohesivePair.hpp"
#include "material/MaterialCatalog.hpp"
#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <numbers>
#include <stdexcept>
using namespace banjo;
void require(bool b,const char *s){if(!b)throw std::runtime_error(s);}
void near(double a,double b,double t,const char *s){require(std::isfinite(a)&&std::abs(a-b)<=t,s);}
void rejects(const std::function<void()> &f){bool bad=false;try{f();}catch(const std::invalid_argument&){bad=true;}require(bad,"expected rejection");}
int main(){try{
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        const auto m=makeReferenceMaterial(material);const double a=.0001,ma=m.density_kg_m3*a*.01,mb=2*ma,mu=1/(1/ma+1/mb);
        const CohesiveInterfaceLaw law{2*m.tensile_strength_pa*m.tensile_strength_pa/m.fracture_energy_j_m2,m.tensile_strength_pa,m.fracture_energy_j_m2,a};
        const double onset=cohesiveDamageOpening(law),failure=cohesiveSeparationOpening(law),budget=a*m.fracture_energy_j_m2;
        const double omega=std::sqrt(law.stiffness_pa_per_m*a/mu),duration=std::numbers::pi/(4*omega),q0=.4*onset;
        double previous_error=1;
        for(unsigned count:{16U,32U,64U}){
            CohesivePairState state{0,0,0,{q0,q0}};
            for(unsigned i=0;i<count;++i)state=advanceCohesivePair(law,ma,mb,state,duration/count).state;
            const double error=std::abs(state.interface.opening_m-q0*std::cos(omega*duration))/q0;
            require(error<previous_error/3.5,"elastic midpoint solution converges toward analytical two-mass oscillator");previous_error=error;
            near(state.velocity_b_m_s-state.velocity_a_m_s,-omega*q0*std::sin(omega*duration),omega*q0*1e-3,"elastic relative motion matches analytical oscillator");
        }
        for(double energy_ratio:{.5,1.5}){
            const double speed=std::sqrt(2*energy_ratio*budget/mu),total_time=8*failure/speed;
            double last_gap=0;
            for(unsigned count:{128U,256U,512U}){
                CohesivePairState state{0,-mb/(ma+mb)*speed,ma/(ma+mb)*speed,{}};
                double total_impulse=0,max_energy_error=0;
                for(unsigned i=0;i<count;++i){const auto step=advanceCohesivePair(law,ma,mb,state,total_time/count);state=step.state;total_impulse+=step.impulse_on_a_n_s;max_energy_error=std::max(max_energy_error,std::abs(step.energy_residual_j));near(step.impulse_on_a_n_s+step.impulse_on_b_n_s,0,0,"interface impulses are equal and opposite");}
                const auto response=evaluateCohesiveInterface(law,state.interface);
                const double ke=.5*ma*state.velocity_a_m_s*state.velocity_a_m_s+.5*mb*state.velocity_b_m_s*state.velocity_b_m_s;
                near(ke+response.stored_energy_j+response.dissipated_energy_j,energy_ratio*budget,std::max(1e-12,budget*1e-8),"motion supplies stored and irreversible interface energy");
                near(ma*state.velocity_a_m_s+mb*state.velocity_b_m_s,0,1e-10,"finite pair momentum closes");
                require(response.separated==(energy_ratio>1),"subcritical launch cannot afford complete separation; supercritical launch separates");
                if(response.separated){near(response.dissipated_energy_j,budget,budget*1e-12,"dynamic separation spends exactly Gc area");near(state.velocity_b_m_s-state.velocity_a_m_s,std::sqrt(2*(energy_ratio-1)*budget/mu),speed*1e-8,"residual separation velocity follows available kinetic energy");}
                else require(response.dissipated_energy_j<budget,"subcritical damage stays below complete-separation work");
                if(count==512){require(std::abs(state.interface.opening_m-last_gap)<failure*.01,"refined opening trajectory agrees within one percent of critical opening");std::cout<<materialPresetName(material)<<" energy_ratio="<<energy_ratio<<" ma="<<ma<<" mb="<<mb<<" separated="<<response.separated<<" dissipated_j="<<response.dissipated_energy_j<<" max_step_residual_j="<<max_energy_error<<" total_impulse="<<total_impulse<<'\n';}
                last_gap=state.interface.opening_m;
            }
        }
        const double speed=std::sqrt(3*budget/mu),dt=failure/speed/32;
        CohesivePairState base{0,-mb/(ma+mb)*speed,ma/(ma+mb)*speed,{}};auto boosted=base;boosted.center_position_m=3;boosted.velocity_a_m_s+=.2;boosted.velocity_b_m_s+=.2;
        const auto plain=advanceCohesivePair(law,ma,mb,base,dt),boost=advanceCohesivePair(law,ma,mb,boosted,dt);
        near(plain.state.interface.opening_m,boost.state.interface.opening_m,failure*1e-12,"uniform translation does not alter cohesive opening");near(boost.state.center_position_m,3+.2*dt,1e-14,"center of mass follows free translation");
        rejects([&]{(void)advanceCohesivePair(law,ma,mb,base,1,1);});require(base.interface.opening_m==0,"budget failure leaves input untouched");
        rejects([&]{(void)advanceCohesivePair(law,0,mb,base,dt);});
    }
    std::cout<<"[PASS] finite cohesive pair dynamics/energy/momentum/refinement/bounds\n";return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
