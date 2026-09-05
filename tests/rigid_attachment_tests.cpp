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
        std::vector<AttachmentImpulse> sites{{pa,pb,j},{pa+Vec3{0,0,.02},pb+Vec3{0,-.01,.02},{0,.003,.004}}};
        const auto batch=applyAttachmentImpulses(a,b,sites);
        const Vec3 total=j+sites[1].impulse_on_a_n_s;
        const Vec3 torque=cross(pa-a.center_m,j)+cross(sites[1].point_a_m-a.center_m,sites[1].impulse_on_a_n_s);
        check(length(batch.a.velocity_m_s-(a.velocity_m_s+total/mass))<1e-12,"batch analytical net impulse");
        check(length(batch.a.angular_velocity_rad_s-(a.angular_velocity_rad_s+inertia.inverse(0).value()*torque))<1e-12,"batch analytical net torque");
        std::reverse(sites.begin(),sites.end());const auto reversed=applyAttachmentImpulses(a,b,sites);
        check(length(batch.a.angular_velocity_rad_s-reversed.a.angular_velocity_rad_s)<1e-12&&std::abs(batch.impulse_work_j-reversed.impulse_work_j)<1e-12,"batch order invariant within roundoff");
        std::vector<AttachmentImpulse> split;
        for(const auto &site:sites)for(unsigned k=0;k<4;++k)split.push_back({site.point_a_m,site.point_b_m,site.impulse_on_a_n_s/4});
        const auto refined=applyAttachmentImpulses(a,b,split);
        check(length(batch.a.angular_velocity_rad_s-refined.a.angular_velocity_rad_s)<1e-12&&std::abs(batch.impulse_work_j-refined.impulse_work_j)<1e-12,"same-point impulse subdivision preserves shared work");
        for(auto &site:sites){site.point_a_m=rotate(site.point_a_m);site.point_b_m=rotate(site.point_b_m);site.impulse_on_a_n_s=rotate(site.impulse_on_a_n_s);}
        const auto rotated_batch=applyAttachmentImpulses(ar,br,sites);
        check(length(rotated_batch.a.angular_velocity_rad_s-rotate(batch.a.angular_velocity_rad_s))<1e-12,"batch full tensor covariance");
        check(std::abs(batch.work_residual_j)<1e-12&&length(batch.angular_residual_kg_m2_s)<1e-12,"batch work and angular ledger");
        std::cout<<materialPresetName(preset)<<" mass_kg="<<mass<<" spin_change_rad_s="<<result.a.angular_velocity_rad_s.z-a.angular_velocity_rad_s.z<<" work_residual_j="<<result.work_residual_j<<" angular_residual="<<length(result.angular_residual_kg_m2_s)<<'\n';
        auto bad=a;bad.inertia_world_kg_m2.m[0][0]=-1;bool rejected=false;try{(void)applyAttachmentImpulse(bad,b,pa,pb,j);}catch(const std::invalid_argument&){rejected=true;}check(rejected,"nonphysical inertia rejected");
    }
    std::cout<<"[PASS] attachment force arms, spin, work, couples and rotated inertia\n";
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
