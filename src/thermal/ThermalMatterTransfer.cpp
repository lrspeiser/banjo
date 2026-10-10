#include "thermal/ThermalMatterTransfer.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <vector>
extern "C" int banjo_thermal_matter_rebind(
 const double* source,const std::uint64_t* matter,const std::uint64_t* owner,
 const std::uint64_t* target,const std::uint64_t* next_owner,int count,double* output,double* receipt){
 try {
  if(!source||!matter||!owner||!target||!next_owner||!output||!receipt||count<1||count>64)return -1;
  std::vector<double> observations(static_cast<std::size_t>(2*count));
  if(banjo_thermal_field_observe(source,count,observations.data()))return -1;
  std::vector<double> candidate(static_cast<std::size_t>(16*count));std::array<double,7> audit{};
  std::array<bool,64> consumed{};
  for(int i=0;i<count;++i){
   if(!matter[i]||!owner[i]||!target[i]||!next_owner[i])return -1;
   for(int j=0;j<i;++j)if(matter[j]==matter[i])return -1;
   int from=-1;for(int j=0;j<count;++j)if(matter[j]==target[i])from=j;
   if(from<0||consumed[static_cast<std::size_t>(from)])return -1;
   consumed[static_cast<std::size_t>(from)]=true;
   const auto* c=source+16*from;std::copy_n(c,16,candidate.data()+16*i);
   audit[6]+=owner[from]!=next_owner[i]?1.:0.;
  }
  // Sum in persistent source order to preserve the reference's rounding;
  // permutation never appears as spurious work in the receipt.
  for(int i=0;i<count;++i){
   const auto* c=source+16*i;audit[0]+=c[1];audit[2]+=c[6]*c[10];
   audit[4]+=c[6]+c[7]+c[8]+c[9];
  }
  audit[1]=audit[0];audit[3]=audit[2];audit[5]=audit[4];
  for(double value:audit)if(!std::isfinite(value))return -1;
  std::copy(candidate.begin(),candidate.end(),output);std::copy(audit.begin(),audit.end(),receipt);return 0;
 }catch(...){return -1;}
}
