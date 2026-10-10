#include "thermal/ThermalMatterTransfer.hpp"
#include <array>
#include <iostream>
#include <stdexcept>
void require(bool v){if(!v)throw std::runtime_error("matter transfer failed");}
int main(){try{
 std::array<double,32> cells{.01,5000,840,840,273.15,0,0,0,.01,0,0,0,600,1.5,0,0,
 .02,20000,1700,1700,273.15,0,.018,.00001,.002,0,16e6,.5,600,1.5,2,1};
 std::array<std::uint64_t,2> matter{11,22},owner{101,101},target{22,11},new_owner{202,303};
 std::array<double,32> out;out.fill(-77);std::array<double,7> receipt;receipt.fill(-88);
 require(banjo_thermal_matter_rebind(cells.data(),matter.data(),owner.data(),target.data(),new_owner.data(),2,out.data(),receipt.data())==0);
 for(int i=0;i<16;++i){require(out[i]==cells[i+16]);require(out[i+16]==cells[i]);}
 require(receipt[0]==receipt[1]&&receipt[2]==receipt[3]&&receipt[4]==receipt[5]&&receipt[6]==2);
 auto before=out;auto audit=receipt;target[1]=22;
 require(banjo_thermal_matter_rebind(cells.data(),matter.data(),owner.data(),target.data(),new_owner.data(),2,out.data(),receipt.data())==-1);require(out==before&&receipt==audit);
 new_owner[1]=303;cells[22]=1e290;cells[26]=1e290;cells[31]=0;
 require(banjo_thermal_matter_rebind(cells.data(),matter.data(),owner.data(),target.data(),new_owner.data(),2,out.data(),receipt.data())==-1);require(out==before&&receipt==audit);
 target[1]=11;new_owner[1]=0;
 require(banjo_thermal_matter_rebind(cells.data(),matter.data(),owner.data(),target.data(),new_owner.data(),2,out.data(),receipt.data())==-1);require(out==before&&receipt==audit);
 std::cout<<"Exact retained field permutation, energy/species and atomic duplicate/invalid owner refusals passed\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
