#include "machines/MechanicalCable.hpp"
#include "material/MaterialCatalog.hpp"
#include <chrono>
#include <iostream>
#include <stdexcept>

using namespace banjo;
using namespace banjo::machines;
using nlohmann::json;
namespace {
void check(bool b,const char *s){if(!b)throw std::runtime_error(s);}
void box(JoltWorld &w,unsigned id,Vec3 p,Vec3 size,MaterialPreset material,bool fixed=true){
    RigidBoxDescription d{};d.body_id=id;d.dimensions_m=size;d.material=makeReferenceMaterial(material);
    d.state.center_of_mass_world_m=p;d.fixed=fixed;w.addBox(d);
}
json declaration(double step=.04,double retention=15){return {{"name","lead"},{"circuit",1},
    {"area_mm2",2.5},{"radius_m",.003},{"segment_m",step},{"retention_n",retention},
    {"path_m",{{-.4,.8,0},{0,.95,0},{.4,.8,0}}}};}
double lowest(const json &r){double y=1e10;for(const auto &s:r.at("segments_m"))for(const auto &p:s)y=std::min(y,p[1].get<double>());return y;}
void sagAndContact(){
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        for(double segment:{.04,.02})for(double dt:{1./240,1./480}){
            JoltWorld w(0);box(w,1,{-.45,.8,0},{.1,.1,.1},MaterialPreset::Iron);
            box(w,2,{.45,.8,0},{.1,.1,.1},MaterialPreset::Iron);
            box(w,3,{0,.55,0},{.24,.4,.3},material);
            auto d=declaration(segment);MechanicalCable cable(w,d,1,2,100);
            const auto initial=cable.report();double max_gap=0,max_energy=0;bool contacted=false;
            for(unsigned i=0;i<unsigned(2/dt);++i){w.step(dt);cable.settle(dt);
                const auto r=cable.report();max_gap=std::max(max_gap,r["max_joint_gap_m"].get<double>());
                if(i%24==0)for(unsigned k=0;k<cable.bodyCount();++k)contacted|=w.touching(100+k,3,.003);
                max_energy=std::max(max_energy,r["kinetic_j"].get<double>()+r["gravity_potential_j"].get<double>()+r["elastic_j"].get<double>());
                for(const auto &s:r["segments_m"])for(unsigned k=0;k<=10;++k){
                    const double t=k/10.;Vec3 p{s[0][0].get<double>()*(1-t)+s[1][0].get<double>()*t,
                        s[0][1].get<double>()*(1-t)+s[1][1].get<double>()*t,s[0][2].get<double>()*(1-t)+s[1][2].get<double>()*t};
                    check(!(std::abs(p.x)<.115&&p.y>.355&&p.y<.745&&std::abs(p.z)<.145),"cable entered support interior");
                }
            }
            const auto end=cable.report();
            check(cable.connected(),"normal hanging lead pulled out");
            check(lowest(end)<lowest(initial)-.03,"lead did not sag under gravity");
            check(contacted,"cable never reached the support");
            check(max_gap<.003,"inextensible cable opened a large gap");
            const double span=initial["length_m"],expected=span*(2.5e-6*8960+(std::acos(-1.)*.003*.003-2.5e-6)*1200);
            check(std::abs(initial["mass_kg"].get<double>()-expected)<1e-7,"cable material mass incorrect");
            const double start=initial["gravity_potential_j"];
            check(max_energy<start+.005,"hanging cable gained unexplained energy");
            std::cout<<"support "<<materialSceneName(material)<<" dt="<<dt<<" segment="<<segment<<" mass="<<expected<<" low="<<lowest(end)
                <<" gap="<<max_gap<<" max_E_delta="<<max_energy-start<<" end="<<end.dump()<<'\n';
        }
    }
}
void pullout(){
    JoltWorld w(0);box(w,1,{-.45,.8,0},{.1,.1,.1},MaterialPreset::Iron);
    box(w,2,{.45,.8,0},{.1,.1,.1},MaterialPreset::Iron);
    auto d=declaration(.04,.05);MechanicalCable cable(w,d,1,2,100);
    for(unsigned i=0;i<240&&cable.connected();++i){w.step(1./240);cable.settle(1./240);}
    check(!cable.connected(),"weak terminal failed to pull out");
    const auto saved=cable.saved();const auto before=cable.report();
    JoltWorld restored(0);box(restored,1,{-.45,.8,0},{.1,.1,.1},MaterialPreset::Iron);
    box(restored,2,{.45,.8,0},{.1,.1,.1},MaterialPreset::Iron);
    MechanicalCable reopened(restored,saved,1,2,100);
    check(!reopened.connected(),"save restore reconnected pulled terminal");
    check(reopened.report()["segments_m"]==before["segments_m"],"save restore changed physical cable pose");
    std::cout<<"pullout "<<before.dump()<<'\n';
}
void fallingLoad(){
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        JoltWorld w(0);box(w,1,{-.45,.8,0},{.1,.1,.1},MaterialPreset::Iron);
        box(w,2,{.45,.8,0},{.1,.1,.1},MaterialPreset::Iron);
        box(w,3,{0,1.25,0},{.16,.16,.16},material,false);
        MechanicalCable cable(w,declaration(),1,2,100);
        unsigned i=0;for(;i<480&&cable.connected();++i){w.step(1./240);cable.settle(1./240);}
        check(!cable.connected(),"falling load passed through the cable without pulling a terminal");
        std::cout<<"falling load "<<materialSceneName(material)<<" time="<<i/240.<<" mass="<<w.mechanicalState(3).mass_kg
            <<" cable="<<cable.report().dump()<<'\n';
    }
}
void reactions(){
    double coarse=0;
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(double dt:{1./240,1./480}){
        JoltWorld w(0);w.setGravity({});
        box(w,1,{-.45,.8,0},{.1,.1,.1},material,false);
        box(w,2,{.45,.8,0},{.1,.1,.1},material,false);
        auto d=declaration(.04,1000);d["loss_time_s"]=0;
        MechanicalCable cable(w,d,1,2,100);
        const auto initial=w.mechanicalTotals();
        double work=0;Vec3 moment{};const unsigned driven=unsigned(std::lround(.05/dt));
        for(unsigned i=0;i<unsigned(.3/dt);++i){
            const auto before=w.snapshot(110);
            if(i<driven){w.pushBodyAt(110,{0,1,0},before.center_of_mass_world_m);moment+=cross(before.center_of_mass_world_m,Vec3{0,dt,0});}
            w.step(dt);cable.settle(dt);
            if(i<driven)work+=.5*dt*(before.linear_velocity_m_s.y+w.snapshot(110).linear_velocity_m_s.y);}
        const auto end=w.mechanicalTotals();const Vec3 impulse{0,driven*dt,0};
        const double p=length(end.linear_momentum_kg_m_s-initial.linear_momentum_kg_m_s-impulse);
        const double l=length(end.angular_momentum_kg_m2_s-initial.angular_momentum_kg_m2_s-moment);
        const double residual=end.kinetic_energy_j-initial.kinetic_energy_j+cable.report()["elastic_j"].get<double>()-work;
        check(p<2e-6,"free cable/terminals lost linear reaction momentum");
        check(l<1e-5,"free cable/terminals lost angular reaction momentum");
        check(length(w.snapshot(1).linear_velocity_m_s)>1e-7&&length(w.snapshot(2).linear_velocity_m_s)>1e-7,"terminals received no reactions");
        check(residual<1e-6,"passive cable gained energy beyond external work");
        if(dt==1./240)coarse=std::abs(residual);
        else check(std::abs(residual)<.25*coarse,"refining the same driven experiment did not reduce numerical energy loss");
        std::cout<<"reactions "<<materialSceneName(material)<<" dt="<<dt<<" P_residual="<<p<<" L_residual="<<l
            <<" kinetic="<<end.kinetic_energy_j<<" input_work="<<work<<" E_residual="<<residual<<'\n';
    }
}
}
int main(){try{const auto start=std::chrono::steady_clock::now();sagAndContact();pullout();fallingLoad();reactions();
    std::cout<<"mechanical cable checks passed in "<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<" s\n";return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
