#include "thermal/ThermalFieldApi.hpp"
#include "thermal/ThermalKernel.hpp"
#include "thermal/EnthalpyLaw.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <vector>
#include <stdexcept>
namespace {
using namespace banjo::thermal;
using Cell=std::array<double,16>;
void require(bool value){if(!value)throw std::invalid_argument("invalid field declaration");}
EnthalpyMaterial phase(const Cell& c){return {c[2],c[3],c[4],c[5]};}
MaterialProperties material(const Cell& c){return {"metadata",c[2],0.,{c[15]==1.,c[12],c[11],c[10],c[13]}};}
LumpState lump(const Cell& c){return {c[6]+c[7]+c[8]+c[9],c[0]*c[2],c[1],c[6],c[7],c[8],c[9]};}
void validate(const Cell& c){
 for(double v:c)require(std::isfinite(v)&&v>=0.);
 require(c[0]>0.&&c[0]<=100.&&c[1]<=1e10&&c[14]<=1000.&&(c[15]==0.||c[15]==1.));
 validateEnthalpyMaterial(phase(c));validateEnthalpyLump({c[0],c[1]/c[0]});
 validateMaterial(material(c));validateLump(lump(c));
 require(c[15]==0.||c[5]==0.); // no unqualified reactive latent-heat coupling
 require(stateFromEnthalpy(phase(c),c[1]/c[0]).temperature_k<=3000.);
}
std::vector<Cell> read(const double* cells,int n){
 require(cells&&n>0&&n<=64);std::vector<Cell> out(static_cast<std::size_t>(n));
 for(int i=0;i<n;++i){std::copy_n(cells+16*i,16,out[static_cast<std::size_t>(i)].begin());validate(out[static_cast<std::size_t>(i)]);}return out;
}
std::array<double,2> totals(const std::vector<Cell>& cells){
 std::array<double,2> out{};for(const auto& c:cells){out[0]+=c[1]+c[6]*c[10];out[1]+=c[6]+c[7]+c[8]+c[9];}return out;
}
}
extern "C" int banjo_thermal_field_observe(const double* cells,int count,double* output){
 try{require(output);auto values=read(cells,count);std::vector<double> result(static_cast<std::size_t>(2*count));
 for(int i=0;i<count;++i){const auto& c=values[static_cast<std::size_t>(i)];auto s=stateFromEnthalpy(phase(c),c[1]/c[0]);result[static_cast<std::size_t>(2*i)]=s.temperature_k;result[static_cast<std::size_t>(2*i+1)]=c[5]>0.?s.liquid_fraction:0.;}
 std::copy(result.begin(),result.end(),output);return 0;}catch(...){return -1;}
}
extern "C" int banjo_thermal_field_step(const double* cells,int count,const double* edges,int edge_count,double dt,double* output,double* receipt){
 try{
 require(output&&receipt&&std::isfinite(dt)&&dt>0.&&dt<=1.&&edge_count>=0&&edge_count<=128&&(edges||edge_count==0));
 auto values=read(cells,count);const auto before=totals(values);std::vector<std::array<double,3>> links;
 for(int i=0;i<edge_count;++i){std::array<double,3> e{edges[3*i],edges[3*i+1],edges[3*i+2]};require(std::isfinite(e[0])&&std::isfinite(e[1])&&std::isfinite(e[2])&&e[0]==std::floor(e[0])&&e[1]==std::floor(e[1])&&e[0]>=0&&e[1]>=0&&e[0]<count&&e[1]<count&&e[0]!=e[1]&&e[2]>=0&&e[2]<=1e6);links.push_back(e);}
 double external=0.,released=0.;for(auto& c:values){const double q=c[14]*dt;c[1]+=q;external+=q;}
 auto exchange=[&](const auto& e){auto& a=values[static_cast<std::size_t>(e[0])];auto& b=values[static_cast<std::size_t>(e[1])];
 if(a[5]==0.&&b[5]==0.){auto q=exchangePairExact(lump(a),lump(b),e[2],dt*.5);a[1]=q.first.sensible_energy_j;b[1]=q.second.sensible_energy_j;}
 else{auto q=exchangePairBackwardEuler(phase(a),{a[0],a[1]/a[0]},phase(b),{b[0],b[1]/b[0]},e[2],dt*.5);a[1]=q.first.enthalpy_j_kg*a[0];b[1]=q.second.enthalpy_j_kg*b[0];}};
 for(const auto& e:links)exchange(e);
 for(auto it=links.rbegin();it!=links.rend();++it)exchange(*it);
 for(auto& c:values){if(c[15]==1.){auto q=reactAdiabatic(lump(c),material(c),dt);c[1]=q.state.sensible_energy_j;c[6]=q.state.remaining_fuel_kg;c[7]=q.state.available_oxygen_kg;c[9]=q.state.reaction_products_kg;released+=q.released_heat_j;}validate(c);}
 const auto after=totals(values);const double residual=after[0]-before[0]-external;
 require(std::abs(residual)<=1e-10*std::max(1.,std::abs(before[0])+external));require(std::abs(after[1]-before[1])<=1e-12*std::max(1.,before[1]));
 std::array<double,8> audit{before[0],after[0],external,released,before[1],after[1],residual,static_cast<double>(links.size()*2)};
 for(int i=0;i<count;++i)std::copy(values[static_cast<std::size_t>(i)].begin(),values[static_cast<std::size_t>(i)].end(),output+16*i);
 std::copy(audit.begin(),audit.end(),receipt);return 0;
 }catch(...){return -1;}
}
