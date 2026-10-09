#include "material/ConnectorPlasticity.hpp"
#include "material/MaterialCatalog.hpp"
#include "rigid/JoltWorld.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace banjo;
namespace {
void check(bool v,const char *why){if(!v)throw std::runtime_error(why);}
void near(double a,double b,const char *why){check(std::abs(a-b)<1e-11*std::max({1.,std::abs(a),std::abs(b)}),why);}
template<class F>void refuses(F f){bool caught=false;try{f();}catch(const std::invalid_argument&){caught=true;}check(caught,"invalid constitutive input refused");}
void constitutive(){
    for(auto preset:{MaterialPreset::Iron,MaterialPreset::Aluminum}){
        const auto m=makeReferenceMaterial(preset);const auto p=compileConnectorPlasticity(m,.05,.05,.006);
        near(p.stiffness[0],m.young_modulus_pa*.006,"section-derived axial stiffness");
        near(p.yield_load[0],m.yield_strength_pa*.05*.006,"section-derived axial yield load");
        for(unsigned axis=0;axis<6;++axis){
            const double k=p.stiffness[axis],y=p.yield_load[axis],qy=y/k;
            std::array<double,6> q{};q[axis]=qy/2;
            const auto elastic=advanceConnectorPlasticity(p,{},q);
            check(!elastic.yielded,"below yield stays elastic");near(elastic.stored_energy_j,.5*k*q[axis]*q[axis],"elastic oracle");
            q[axis]=3*qy;const auto plastic=advanceConnectorPlasticity(p,{},q);
            check(plastic.yielded&&plastic.state.yielded_updates==1,"yield retained");
            near(plastic.state.plastic_rest[axis],2*qy,"permanent generalized rest");
            near(plastic.plastic_increment_j,2*y*qy,"physical perfect-plastic work");
            near(plastic.return_excess_increment_j,2*k*qy*qy,"endpoint projection excess is separate");
            near(.5*k*q[axis]*q[axis],plastic.stored_energy_j+plastic.plastic_increment_j+plastic.return_excess_increment_j,"projection energy identity");
            const auto repeat=advanceConnectorPlasticity(p,plastic.state,q);
            near(repeat.plastic_increment_j,0,"holding displacement produces no additional work");
            q[axis]=plastic.state.plastic_rest[axis];const auto unloaded=advanceConnectorPlasticity(p,plastic.state,q);
            near(unloaded.stored_energy_j,0,"permanent rest has zero elastic force");near(unloaded.state.plastic_rest[axis],2*qy,"unloading preserves history");
            q[axis]=-qy;const auto reversed=advanceConnectorPlasticity(p,unloaded.state,q);
            near(reversed.state.plastic_rest[axis],0,"reverse plastic return");near(reversed.state.accumulated_flow[axis],4*qy,"reverse flow accumulates");
            near(reversed.state.plastic_dissipation_j,4*y*qy,"reverse work stays positive");
            // The endpoint return is first-order. Finer loading increments must
            // reduce numerical loss, rather than relabel it as material heat.
            double losses[2]{};
            for(unsigned pass=0;pass<2;++pass){ConnectorPlasticState history;const unsigned n=pass?128:64;
                for(unsigned j=1;j<=n;++j){q[axis]=3*qy*j/n;history=advanceConnectorPlasticity(p,history,q).state;}
                near(history.plastic_rest[axis],2*qy,"refined final permanent rest");near(history.plastic_dissipation_j,2*y*qy,"refined physical work");losses[pass]=history.return_excess_j;
            }
            check(losses[1]<.52*losses[0],"refinement reduces projection excess");
        }
    }
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak})refuses([&]{(void)compileConnectorPlasticity(makeReferenceMaterial(preset),.05,.05,.006);});
    auto m=makeReferenceMaterial(MaterialPreset::Iron);m.hardening_ratio=.1;refuses([&]{(void)compileConnectorPlasticity(m,.05,.05,.006);});
    const auto p=compileConnectorPlasticity(makeReferenceMaterial(MaterialPreset::Iron),.05,.05,.006);
    ConnectorPlasticState bad;bad.plastic_rest[0]=1;refuses([&]{(void)advanceConnectorPlasticity(p,bad,{});});
    std::array<double,6> invalid{};invalid[1]=std::numeric_limits<double>::quiet_NaN();refuses([&]{(void)advanceConnectorPlasticity(p,{},invalid);});
}
void native_history(RigidJobExecution runner){
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        auto m=makeReferenceMaterial(preset);m.model=MaterialModel::RigidOnly;
        JoltWorld world(0,{},runner);world.setGravity({});world.setCenteredIntegration(true);
        world.addBox({1,{.05,.05,.05},m,{{-.1,0,0},{},{},{}},true});
        world.addBox({2,{.05,.05,.05},m,{{ .1,0,0},{},{},{}},false});
        world.setContinuousCollision(2,false);
        const auto joint=world.addFaceSpring({1,2,{},{1,0,0},{0,1,0},{1000,1000,1000},{10,10,10},{},{},true,true});
        const auto initial_face=world.faceSpringObservation(joint);
        const auto before=world.snapshot(2);const auto totals=world.mechanicalTotals({});
        check(!world.runReversibleTrial([&]{world.setFacePlasticRest(joint,{.001,0,0},{0,.002,0});world.step(.001);return false;}),"rest trial refused");
        auto face=world.faceSpringObservation(joint);check(face.displacement_cs_m.x==initial_face.displacement_cs_m.x,"rejected translation rest restored exactly");check(face.rotation_cs_rad.y==initial_face.rotation_cs_rad.y,"rejected angular rest restored exactly");
        check(lengthSquared(world.snapshot(2).linear_velocity_m_s-before.linear_velocity_m_s)==0,"rejected native motion exactly restored");
        bool caught=false;try{(void)world.runReversibleTrial([&]()->bool{world.setFacePlasticRest(joint,{.003,0,0},{});throw std::runtime_error("history exception");});}catch(const std::runtime_error&){caught=true;}
        check(caught,"exception fixture");check(world.faceSpringObservation(joint).displacement_cs_m.x==initial_face.displacement_cs_m.x,"exception restores rest exactly");
        check(world.runReversibleTrial([&]{world.setFacePlasticRest(joint,{.001,0,0},{});return true;}),"accepted history");
        near(world.faceSpringObservation(joint).displacement_cs_m.x,initial_face.displacement_cs_m.x-.001,"accepted native rest persists");
        near(world.mechanicalTotals({}).kinetic_energy_j,totals.kinetic_energy_j,"rest change assigns no velocities");
        check(lengthSquared(world.snapshot(2).center_of_mass_world_m-before.center_of_mass_world_m)==0,"rest change assigns no poses");
        check(!world.runReversibleTrial([&]{
            check(world.runReversibleTrial([&]{world.setFacePlasticRest(joint,{.002,0,0},{0,.003,0});return true;}),"child rest accepted");
            return false;
        }),"parent refuses after child history acceptance");
        near(world.faceSpringObservation(joint).displacement_cs_m.x,initial_face.displacement_cs_m.x-.001,"parent restores its accepted rest");
        check(world.faceSpringObservation(joint).rotation_cs_rad.y==initial_face.rotation_cs_rad.y,"parent restores angular rest");
        world.step(.001);check(world.snapshot(2).linear_velocity_m_s.x>0,"actual native spring responds to changed rest");
        refuses([&]{world.setFacePlasticRest(joint,{11,0,0},{});});
    }
}
}
int main(){try{constitutive();native_history(RigidJobExecution::Inline);native_history(RigidJobExecution::ThreadPool);std::cout<<"PASS six-mode return, unload/reversal, refinement, admission and native history rollback in both runners\n";return 0;}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
