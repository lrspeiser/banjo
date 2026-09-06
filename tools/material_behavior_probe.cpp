#include "MaterialJson.hpp"
#include <iostream>
using namespace banjo;
using banjo::material_json::Json;
namespace { Json tensor(const SymmetricTensor3 &v){return {v.xx,v.yy,v.zz,v.xy,v.yz,v.zx};} }
int main(){
 try{
  std::string input;char c;while(std::cin.get(c)){material_json::require(input.size()<262144,"Input exceeds 256 KiB");input.push_back(c);}
  const auto request=material_json::parseStrict(input);material_json::exactKeys(request,{"material","strains"});
  const auto material=material_json::parseMaterial(request["material"]);const auto &strains=request["strains"];
  material_json::require(strains.is_array()&&!strains.empty()&&strains.size()<=256,"Strain path must contain 1..256 points");
  J2State state;Json samples=Json::array();
  for(const auto &a:strains){material_json::require(a.is_array()&&a.size()==6,"Strain requires six tensor components");
   const SymmetricTensor3 strain{material_json::finiteNumber(a[0]),material_json::finiteNumber(a[1]),material_json::finiteNumber(a[2]),material_json::finiteNumber(a[3]),material_json::finiteNumber(a[4]),material_json::finiteNumber(a[5])};
   const auto r=evaluateSmallStrain(material.law,state,strain);state=r.state;
   samples.push_back({{"stress_pa",tensor(r.stress_pa)},{"strain",tensor(state.total_strain)},{"plastic_strain",tensor(state.plastic_strain)},
    {"equivalent_plastic_strain",state.equivalent_plastic_strain},{"stored_free_energy_j_m3",r.stored_free_energy_j_m3},
    {"plastic_dissipation_j_m3",r.plastic_dissipation_j_m3},{"backward_euler_work_excess_j_m3",r.backward_euler_work_excess_j_m3},{"yielded",r.yielded}});
  }
  std::cout<<Json({{"schema","banjo.material-response.v1"},{"status","complete"},{"scope","small-strain material-point path; no geometry, collision, fracture or rubber model"},{"samples",samples}}).dump()<<'\n';return 0;
 }catch(const std::exception &){std::cout<<Json({{"status","rejected"},{"error","Invalid material, unsupported capability, strain path or input budget"}}).dump()<<'\n';return 1;}
}
