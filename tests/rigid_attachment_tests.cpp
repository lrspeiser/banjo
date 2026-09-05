#include "physics/RigidAttachment.hpp"
#include "material/MaterialCatalog.hpp"
#include <iostream>
using namespace banjo;
void check(bool b,const char *s){if(!b)throw std::runtime_error(s);}
int main(){try{
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        const auto m=makeReferenceMaterial(preset);const double mass=m.density_kg_m3*.2*.1*.08;
        Mat3 inertia;inertia.m[0][0]=mass*(.1*.1+.08*.08)/12;inertia.m[1][1]=mass*(.2*.2+.08*.08)/12;inertia.m[2][2]=mass*(.2*.2+.1*.1)/12;
        AttachmentBody a{mass,inertia,{-1,0,0},{.2,.1,0},{0,0,.3}},b{mass,inertia,{1,0,0},{-.1,.2,0},{0,0,-.2}};
        const Vec3 j{.01,0,0},pa{-.9,.04,0},pb{.9,.04,0};
        const auto result=applyAttachmentImpulse(a,b,pa,pb,j);
        check(std::abs(result.a.angular_velocity_rad_s.z-a.angular_velocity_rad_s.z+.04*.01/inertia.m[2][2])<1e-12,"off-center impulse produces analytical spin");
        check(length(result.angular_impulse_kg_m2_s)<1e-14&&length(result.angular_residual_kg_m2_s)<1e-12,"central attachment closes orbital plus intrinsic angular momentum");
        check(length(result.momentum_residual_kg_m_s)<1e-12&&std::abs(result.work_residual_j)<1e-12,"pair impulse/work accounting");
        const auto couple=applyAttachmentImpulse(a,b,pa,{.9,-.04,0},j);
        check(std::abs(couple.angular_impulse_kg_m2_s.z+.0008)<1e-14&&length(couple.angular_residual_kg_m2_s)<1e-12,"noncentral couple must be reported, not hidden as conservation");
        // Rotate the anisotropic inertia tensor and every vector 45 degrees.
        const double c=std::sqrt(.5);const auto rotate=[&](Vec3 v){return Vec3{c*(v.x-v.y),c*(v.x+v.y),v.z};};
        Mat3 rotated=inertia;rotated.m[0][0]=rotated.m[1][1]=.5*(inertia.m[0][0]+inertia.m[1][1]);rotated.m[0][1]=rotated.m[1][0]=.5*(inertia.m[0][0]-inertia.m[1][1]);
        auto ar=a,br=b;for(auto *x:{&ar,&br}){x->inertia_world_kg_m2=rotated;x->center_m=rotate(x->center_m);x->velocity_m_s=rotate(x->velocity_m_s);x->angular_velocity_rad_s=rotate(x->angular_velocity_rad_s);}
        const auto transformed=applyAttachmentImpulse(ar,br,rotate(pa),rotate(pb),rotate(j));
        check(length(transformed.a.velocity_m_s-rotate(result.a.velocity_m_s))<1e-12&&length(transformed.a.angular_velocity_rad_s-rotate(result.a.angular_velocity_rad_s))<1e-12,"tensor/frame covariance");
        // Exercise non-diagonal inverse with a torque in the xy plane.
        const auto tilt=applyAttachmentImpulse(a,b,pa,pb,{0,0,.01});const auto tilted=applyAttachmentImpulse(ar,br,rotate(pa),rotate(pb),rotate({0,0,.01}));
        check(length(tilted.a.angular_velocity_rad_s-rotate(tilt.a.angular_velocity_rad_s))<1e-12,"full rotated tensor inverse");
        std::cout<<materialPresetName(preset)<<" mass_kg="<<mass<<" spin_change_rad_s="<<result.a.angular_velocity_rad_s.z-a.angular_velocity_rad_s.z<<" work_residual_j="<<result.work_residual_j<<" angular_residual="<<length(result.angular_residual_kg_m2_s)<<'\n';
        auto bad=a;bad.inertia_world_kg_m2.m[0][0]=-1;bool rejected=false;try{(void)applyAttachmentImpulse(bad,b,pa,pb,j);}catch(const std::invalid_argument&){rejected=true;}check(rejected,"nonphysical inertia rejected");
    }
    std::cout<<"[PASS] attachment force arms, spin, work, couples and rotated inertia\n";
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
