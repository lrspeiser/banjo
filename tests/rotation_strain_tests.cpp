#include "physics/RotationStrain.hpp"
#include <iostream>
#include <stdexcept>
using namespace banjo;
namespace {
void check(bool v,const char *message){if(!v)throw std::runtime_error(message);}
Quat multiply(Quat a,Quat b){return {a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,
    a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};}
Quat turn(Vec3 p){const double t=length(p);return t>0?Quat{std::cos(t/2),p.x*std::sin(t/2)/t,p.y*std::sin(t/2)/t,p.z*std::sin(t/2)/t}:Quat{};}
double energy(Quat a,Quat b,Vec3 k){const auto p=rotationStrain(a,b).angle_rad;return .5*(k.x*p.x*p.x+k.y*p.y*p.y+k.z*p.z*p.z);}
void gradient(Vec3 phi){
    const auto a=turn({.4,-.2,.7}),b=multiply(a,turn(phi));const auto strain=rotationStrain(a,b);
    check(length(strain.angle_rad-phi)<3e-15,"exact logarithmic strain");const Vec3 k{2,7,13},g{k.x*phi.x,k.y*phi.y,k.z*phi.z};
    const auto torque=strain.gradient_axes_world[0]*g.x+strain.gradient_axes_world[1]*g.y+strain.gradient_axes_world[2]*g.z;
    const Vec3 axes[]{{1,0,0},{0,1,0},{0,0,1}};const double eps=1e-6;double worst=0;
    for(unsigned i=0;i<3;++i){const auto n=axes[i];
        const double db=(energy(a,multiply(turn(n*eps),b),k)-energy(a,multiply(turn(-n*eps),b),k))/(2*eps);
        const double da=(energy(multiply(turn(n*eps),a),b,k)-energy(multiply(turn(-n*eps),a),b,k))/(2*eps);
        worst=std::max(worst,std::abs(db-dot(torque,n)));check(std::abs(db-dot(torque,n))<2e-8,"B torque is energy gradient");
        check(std::abs(da+db)<3e-8,"equal opposite orientation reactions");
    }
    const auto common=turn({-.2,.9,.3});check(std::abs(energy(multiply(common,a),multiply(common,b),k)-energy(a,b,k))<3e-14,"objective energy under rigid rotation");
    const Quat opposite{-b.w,-b.x,-b.y,-b.z};check(length(rotationStrain(a,opposite).angle_rad-phi)<3e-15,"quaternion sign independence");
    std::cout<<"angle="<<length(phi)<<" gradient_residual="<<worst<<'\n';
}
}
int main(){try{
    for(const auto phi:{Vec3{},Vec3{1e-9,-2e-9,3e-9},Vec3{.4,.9,-.3},Vec3{2.4,.8,-.6}})gradient(phi);
    bool refused=false;try{rotationStrain({},turn({3.141592653589793,0,0}));}catch(const std::invalid_argument &){refused=true;}
    check(refused,"pi branch refuses instead of clamps");refused=false;try{rotationStrain({2,0,0,0},{});}catch(const std::invalid_argument &){refused=true;}
    check(refused,"nonunit frame refuses");return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
