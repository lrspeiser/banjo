#include "physics/DoubleRigidDynamics.hpp"
#include "physics/ContactTensor.hpp"
#include "core/RigidPrimitive.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {
bool finite(Vec3 v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
Quat conjugate(Quat q){return {q.w,-q.x,-q.y,-q.z};}
Quat product(Quat a,Quat b){return {a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,
    a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,
    a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};}
void require(bool ok,const char *why){if(!ok)throw std::invalid_argument(why);}
void rotation(Quat q){
    const double n=std::hypot(std::hypot(q.w,q.x),std::hypot(q.y,q.z));
    require(std::isfinite(n)&&std::abs(n-1)<=1e-10,"double rigid orientation must be unit length");
}
void validate(const DoubleRigidState &s){
    require(std::isfinite(s.mass_kg)&&s.mass_kg>0&&finite(s.center_world_m)&&
        finite(s.velocity_world_m_s)&&finite(s.spin_momentum_world_kg_m2_s),"invalid double rigid mass/motion");
    rotation(s.orientation_world);(void)inverseContactTensor(s.inertia_body_kg_m2);
}
DoubleRigidTransfer audited(const DoubleRigidState &before,DoubleRigidState after,Vec3 j,Vec3 k,double work){
    const auto a=measureRigidMechanics(doubleRigidMechanics(before));
    const auto b=measureRigidMechanics(doubleRigidMechanics(after));
    DoubleRigidTransfer out{after,j,k,work,b.kinetic_energy_j-a.kinetic_energy_j-work,
        b.linear_momentum_kg_m_s-a.linear_momentum_kg_m_s-j,
        b.angular_momentum_kg_m2_s-a.angular_momentum_kg_m2_s-k};
    require(std::isfinite(out.work_j)&&std::isfinite(out.numerical_energy_j)&&finite(out.momentum_residual_n_s)&&
        finite(out.angular_residual_kg_m2_s),"double rigid transfer accounting overflow");
    return out;
}
}
DoubleRigidState makeDoubleRigidState(const RigidMechanicalState &body){
    rotation(body.motion.orientation_world);(void)inverseContactTensor(body.inertia_world_kg_m2);
    DoubleRigidState out{body.mass_kg,rotateInertia(body.inertia_world_kg_m2,conjugate(body.motion.orientation_world)),
        body.motion.center_of_mass_world_m,body.motion.linear_velocity_m_s,
        body.inertia_world_kg_m2*body.motion.angular_velocity_rad_s,body.motion.orientation_world};
    validate(out);return out;
}
RigidMechanicalState doubleRigidMechanics(const DoubleRigidState &s){
    validate(s);const auto inertia=rotateInertia(s.inertia_body_kg_m2,s.orientation_world);
    const auto omega=s.orientation_world.rotate(inverseContactTensor(s.inertia_body_kg_m2)*
        conjugate(s.orientation_world).rotate(s.spin_momentum_world_kg_m2_s));
    require(finite(omega),"double rigid angular velocity overflow");
    return {{s.center_world_m,s.orientation_world,s.velocity_world_m_s,omega},s.mass_kg,inertia};
}
Quat driftDoubleRigidOrientation(Quat q,Vec3 momentum,const Mat3 &inertia,double dt){
    rotation(q);require(finite(momentum)&&std::isfinite(dt)&&std::abs(dt)<=1,"invalid double rigid drift horizon/momentum");
    const auto inverse=inverseContactTensor(inertia);
    // A = C C^T; H = sum_i (c_i dot L_body)^2 / 2. A term's exact
    // flow is a rotation about c_i; c_i dot L_body is invariant in that flow.
    Mat3 c;
    for(unsigned i=0;i<3;++i)for(unsigned j=0;j<=i;++j){
        double value=inverse.m[i][j];for(unsigned k=0;k<j;++k)value-=c.m[i][k]*c.m[j][k];
        require(std::isfinite(value)&&(i!=j||value>0),"double rigid inverse inertia factorization failed");
        c.m[i][j]=i==j?std::sqrt(value):value/c.m[j][j];
    }
    const auto axis=[&](unsigned i,double h){
        const Vec3 column{c.m[0][i],c.m[1][i],c.m[2][i]};
        const double magnitude=std::hypot(column.x,column.y,column.z);
        const Vec3 unit=column/magnitude,l=conjugate(q).rotate(momentum);
        const double angle=.5*h*magnitude*magnitude*dot(unit,l);
        require(std::isfinite(angle)&&std::abs(2*angle)<=.25,"double rigid rotation step needs refinement");
        const double sn=std::sin(angle);q=product(q,{std::cos(angle),sn*unit.x,sn*unit.y,sn*unit.z});
    };
    axis(0,.5*dt);axis(1,.5*dt);axis(2,dt);axis(1,.5*dt);axis(0,.5*dt);
    // Normalizing orientation removes accumulated quaternion roundoff only;
    // spin momentum is untouched and resulting energy error stays in the audit.
    const double n=std::hypot(std::hypot(q.w,q.x),std::hypot(q.y,q.z));
    require(std::isfinite(n)&&n>0,"double rigid rotation overflow");
    return {q.w/n,q.x/n,q.y/n,q.z/n};
}
DoubleRigidTransfer advanceDoubleRigidFree(const DoubleRigidState &s,double dt){
    validate(s);auto out=s;out.center_world_m+=dt*s.velocity_world_m_s;
    out.orientation_world=driftDoubleRigidOrientation(s.orientation_world,s.spin_momentum_world_kg_m2_s,s.inertia_body_kg_m2,dt);
    validate(out);return audited(s,out,{},{},0);
}
DoubleRigidTransfer applyDoubleRigidImpulse(const DoubleRigidState &s,Vec3 point,Vec3 j,Vec3 free){
    validate(s);require(finite(point)&&finite(j)&&finite(free),"nonfinite double rigid impulse");
    const Vec3 arm=point-s.center_world_m,spin=cross(arm,j)+free;
    auto out=s;out.velocity_world_m_s+=j/s.mass_kg;out.spin_momentum_world_kg_m2_s+=spin;
    validate(out);
    const Vec3 before_omega=doubleRigidMechanics(s).motion.angular_velocity_rad_s;
    const Vec3 after_omega=doubleRigidMechanics(out).motion.angular_velocity_rad_s;
    const double work=dot(j,.5*(s.velocity_world_m_s+out.velocity_world_m_s))+
        dot(spin,.5*(before_omega+after_omega));
    return audited(s,out,j,cross(point,j)+free,work);
}
} // namespace banjo
