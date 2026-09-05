#include "platform/BowlGeometry.hpp"
#include <numbers>
#include <stdexcept>
namespace banjo {
namespace {
Quat rotation(const BowlSettings &s){const double a=s.tilt_degrees*std::numbers::pi/360;return {std::cos(a),0,0,std::sin(a)};}
void validate(const BowlSettings &s){
    if(!std::isfinite(s.radius_m)||s.radius_m<.8||s.radius_m>2||!std::isfinite(s.depth_m)||s.depth_m<.2||s.depth_m>1||
       !std::isfinite(s.tilt_degrees)||std::abs(s.tilt_degrees)>20||s.rings<8||s.rings>48||s.sectors<24||s.sectors>192)
        throw std::invalid_argument("bowl dimensions or resolution outside supported bounds");
    if(s.surface!=MaterialPreset::Concrete&&s.surface!=MaterialPreset::Glass&&s.surface!=MaterialPreset::Oak&&s.surface!=MaterialPreset::Iron)
        throw std::invalid_argument("unsupported bowl surface");
}
}
Vec3 bowlPoint(const BowlSettings &s,double x,double z){return rotation(s).rotate({x,s.depth_m*(x*x+z*z)/(s.radius_m*s.radius_m),z});}
std::vector<std::array<Vec3,3>> compileBowl(const BowlSettings &s){
    validate(s);std::vector<std::array<Vec3,3>> out;
    const auto point=[&](unsigned r,unsigned a){double t=2*std::numbers::pi*a/s.sectors,d=s.radius_m*r/s.rings;return bowlPoint(s,d*std::cos(t),d*std::sin(t));};
    for(unsigned r=0;r<s.rings;++r)for(unsigned a=0;a<s.sectors;++a){
        auto p=point(r,a),q=point(r+1,a),v=point(r+1,(a+1)%s.sectors),u=point(r,(a+1)%s.sectors);
        out.push_back({p,v,q});if(r)out.push_back({p,u,v});
    }
    return out;
}
}
