#include "physics/ResolutionBudget.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <vector>
namespace banjo {
ResolutionBudget assessSpringResolution(std::span<const double> masses,
    std::span<const ResolutionLink> links,double dt,unsigned budget,double phase){
    if(masses.empty()||masses.size()>1000000||links.size()>10000000||
       !std::isfinite(dt)||dt<=0||!budget||budget>1000000||
       !std::isfinite(phase)||phase<=0||phase>1)
        throw std::invalid_argument("invalid temporal resolution request");
    std::vector<double> sums(masses.size());
    for(double mass:masses)if(!std::isfinite(mass)||mass<=0)throw std::invalid_argument("invalid resolution mass");
    for(auto edge:links){
        if(edge.a>=masses.size()||edge.b>=masses.size()||edge.a==edge.b||
           !std::isfinite(edge.stiffness_n_m)||edge.stiffness_n_m<=0)
            throw std::invalid_argument("invalid resolution spring");
        sums[edge.a]+=edge.stiffness_n_m/masses[edge.a];
        sums[edge.b]+=edge.stiffness_n_m/masses[edge.b];
    }
    const double omega=std::sqrt(2 * *std::max_element(sums.begin(),sums.end()));
    const double product=omega*dt, count=std::max(1.,std::ceil(product/phase));
    if(!std::isfinite(count)||count>std::numeric_limits<unsigned>::max())
        throw std::invalid_argument("resolution request exceeds representable work budget");
    return {omega,omega>0?phase/omega:dt,product,unsigned(count),count<=1,count<=budget};
}
}
