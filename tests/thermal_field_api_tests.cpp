#include "thermal/ThermalFieldApi.hpp"
#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <limits>
using Cell=std::array<double,16>;
void check(bool yes){if(!yes)throw std::runtime_error("thermal field oracle failed");}
void near(double a,double b,double t){check(std::abs(a-b)<=t);}
Cell make(double mass,double cp,double t){return {mass,mass*cp*t,cp,cp,273.15,0,0,0,mass,0,0,0,600,1.5,0,0};}
int main(){
 try{
 const std::array<double,4> cp{840,1700,450,2100},rho{2500,700,7870,917},k{1,.12,80,2.2};
 for(std::size_t m=0;m<4;++m){
 std::array<Cell,2> cells{make(rho[m]*1e-6,cp[m],400),make(rho[m]*1e-6,cp[m],200)},out{};
 std::array<double,3> edge{0,1,k[m]*.01};std::array<double,8> audit{};
 check(banjo_thermal_field_step(cells[0].data(),2,edge.data(),1,.1,out[0].data(),audit.data())==0);
 const double decay=std::exp(-2*edge[2]*.1/(cells[0][0]*cp[m]));
 near(out[0][1]/(cells[0][0]*cp[m]),300+100*decay,1e-10);
 near(out[1][1]/(cells[0][0]*cp[m]),300-100*decay,1e-10);
 near(audit[6],0,1e-10);near(audit[4],audit[5],1e-14);
 std::cout<<"material "<<m<<" mass_kg="<<cells[0][0]<<" energy_residual_J="<<audit[6]<<'\n';
 }
 auto ice=make(.01,2100,273.15);ice[3]=4180;ice[5]=334000;ice[14]=100;
 Cell melted{};std::array<double,8> audit{};std::array<double,2> observation{};
 check(banjo_thermal_field_step(ice.data(),1,nullptr,0,1,melted.data(),audit.data())==0);
 check(banjo_thermal_field_observe(melted.data(),1,observation.data())==0);
 near(observation[0],273.15,1e-12);near(observation[1],100/(.01*334000),1e-14);near(audit[2],100,1e-12);
 auto fuel=make(.01,1700,650);fuel[6]=.009;fuel[8]=.001;fuel[7]=.00001;fuel[10]=16e6;fuel[11]=.5;fuel[15]=1;
 Cell reacted{};check(banjo_thermal_field_step(fuel.data(),1,nullptr,0,.1,reacted.data(),audit.data())==0);
 const double burned=fuel[7]/1.5;near(reacted[6],fuel[6]-burned,1e-14);near(reacted[9],burned*2.5,1e-14);near(audit[3],burned*16e6,1e-10);near(audit[6],0,1e-9);
 // Exhausted oxygen stops additional reaction; no display-name switch exists.
 Cell exhausted{};check(banjo_thermal_field_step(reacted.data(),1,nullptr,0,.1,exhausted.data(),audit.data())==0);near(exhausted[1],reacted[1],1e-10);
 // Invalid input and a late temperature refusal must leave both outputs intact.
 Cell marker;marker.fill(-77);std::array<double,8> saved;saved.fill(-88);audit=saved;
 fuel[14]=std::numeric_limits<double>::quiet_NaN();check(banjo_thermal_field_step(fuel.data(),1,nullptr,0,.1,marker.data(),audit.data())==-1);check(marker[0]==-77&&audit==saved);
 fuel=make(.0001,1,2999);fuel[14]=1000;check(banjo_thermal_field_step(fuel.data(),1,nullptr,0,1,marker.data(),audit.data())==-1);check(marker[0]==-77&&audit==saved);
 std::cout<<"analytical pair, latent plateau, closed species/chemical energy and atomic refusals passed\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
