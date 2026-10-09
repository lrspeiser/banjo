#include "rigid/RigidComponent.hpp"
#include <algorithm>
#include <cmath>
#include <set>
#include <stdexcept>
namespace banjo {
namespace {
Quat multiply(Quat a,Quat b){return {a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,
    a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,
    a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};}
bool close(const RepresentationTransferAudit &a,const ComponentTransferBudget &b){
    return std::abs(a.after.mass_kg-a.before.mass_kg)<=b.mass_kg&&
        length(a.after.linear_momentum_kg_m_s-a.before.linear_momentum_kg_m_s)<=b.linear_momentum_n_s&&
        length(a.after.angular_momentum_kg_m2_s-a.before.angular_momentum_kg_m2_s)<=b.angular_momentum_n_m_s&&
        std::abs(a.after.mechanicalEnergy()-a.before.mechanicalEnergy())<=b.energy_j;
}
}
RigidComponent::RigidComponent(MatterBodyId proxy,std::vector<RigidComponentCell> cells):proxy_(proxy),cells_(std::move(cells)){
    std::set<MatterBodyId> ids;
    if(cells_.empty()||cells_.size()>64)throw std::invalid_argument("component requires 1..64 occupied boxes");
    for(const auto &c:cells_)if(c.id==proxy_||!ids.insert(c.id).second||
        !std::isfinite(lengthSquared(c.size_m))||std::min({c.size_m.x,c.size_m.y,c.size_m.z})<=0)
        throw std::invalid_argument("invalid component cells");
}
ComponentTransferReceipt RigidComponent::collapse(JoltWorld &world,double elastic,ComponentTransferBudget budget,Vec3 gravity){
    ComponentTransferReceipt out;
    if(!std::isfinite(lengthSquared(gravity)))throw std::invalid_argument("invalid transfer gravity");
    if(collapsed_){out.reason="already collapsed";return out;}
    for(const auto x:{budget.mass_kg,budget.linear_momentum_n_s,budget.angular_momentum_n_m_s,budget.energy_j,budget.nonrigid_energy_j})
        if(!std::isfinite(x)||x<0)throw std::invalid_argument("invalid transfer budget");
    if(!std::isfinite(elastic)||elastic<0)throw std::invalid_argument("invalid component elastic energy");
    if(elastic>budget.nonrigid_energy_j){out.reason="stored elastic energy needs detailed continuation";return out;}
    std::vector<RigidMechanicalState> states;std::vector<MatterBodyId> ids;
    for(const auto &c:cells_){if(!world.contains(c.id)){out.reason="source body unavailable";return out;}
        const auto s=world.mechanicalState(c.id);if(s.mass_kg<=0){out.reason="source body is not dynamic";return out;}
        const auto [lo,hi]=world.shapeBoundsTurned(c.id,{});const auto actual=hi-lo;
        const double expected=c.size_m.x*c.size_m.y*c.size_m.z*c.material.density_kg_m3;
        if(length(actual-c.size_m)>1e-6*std::max(1.,length(c.size_m))||!std::isfinite(expected)||
            std::abs(s.mass_kg-expected)>1e-6*std::max(1.,expected)){
            out.reason="declared occupied box or material mass differs from native source";return out;}
        states.push_back(s);ids.push_back(c.id);out.audit.before+=measureRigidMechanics(s,gravity);}
    const auto center=out.audit.before.centerOfMass();Mat3 inertia;
    for(const auto &s:states){const auto r=s.motion.center_of_mass_world_m-center;const double x[]{r.x,r.y,r.z};
        for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)
            inertia.m[i][j]+=s.inertia_world_kg_m2.m[i][j]+s.mass_kg*((i==j?lengthSquared(r):0)-x[i]*x[j]);}
    // Relative scaling avoids an absolute determinant threshold on small cells.
    double scale=0;for(const auto &row:inertia.m)for(double x:row)scale=std::max(scale,std::abs(x));
    Mat3 scaled=inertia;for(auto &row:scaled.m)for(double &x:row)x/=scale;
    const auto inverse=scaled.inverse();if(!inverse){out.reason="singular component inertia";return out;}
    const auto velocity=out.audit.before.linear_momentum_kg_m_s/out.audit.before.mass_kg;
    const auto spin=(*inverse)*(out.audit.before.angular_momentum_kg_m2_s-cross(center,out.audit.before.linear_momentum_kg_m_s))/scale;
    RigidMechanicalState rigid{{center,{},velocity,spin},out.audit.before.mass_kg,inertia};
    out.nonrigid_energy_j=out.audit.before.kinetic_energy_j-measureRigidMechanics(rigid).kinetic_energy_j;
    if(!std::isfinite(out.nonrigid_energy_j)||std::abs(out.nonrigid_energy_j)>budget.nonrigid_energy_j){
        out.reason="nonrigid kinetic energy needs detailed continuation";return out;}
    RigidCompoundDescription compound;compound.body_id=proxy_;compound.material=cells_.front().material;
    compound.state=rigid.motion;compound.mass_kg=rigid.mass_kg;compound.inertia_local_kg_m2=inertia;
    centers_.clear();rotations_.clear();
    for(unsigned i=0;i<cells_.size();++i){const auto &c=cells_[i];const auto &s=states[i].motion;
        centers_.push_back(s.center_of_mass_world_m-center);rotations_.push_back(s.orientation_world);
        compound.parts.push_back({{PrimitiveKind::Box,0,c.size_m},centers_.back(),rotations_.back(),c.material});}
    world.addCompound(compound);world.setContinuousCollision(proxy_,false);
    out.audit.after=measureRigidMechanics(world.mechanicalState(proxy_),gravity);out.audit.measured=true;
    if(!close(out.audit,budget)){world.removeAndDestroy(proxy_);out.reason="native transfer exceeds measured budget";return out;}
    if(!world.parkFaceComponent(ids,out.reason)){world.removeAndDestroy(proxy_);return out;}
    budget_=budget;collapsed_=true;out.admitted=true;return out;
}
std::vector<RigidSnapshot> RigidComponent::snapshots(const JoltWorld &world) const {
    std::vector<RigidSnapshot> out;
    if(!collapsed_){for(const auto &c:cells_)out.push_back(world.snapshot(c.id));return out;}
    const auto s=world.snapshot(proxy_);
    for(unsigned i=0;i<cells_.size();++i){const auto r=s.orientation_world.rotate(centers_[i]);
        out.push_back({s.center_of_mass_world_m+r,multiply(s.orientation_world,rotations_[i]),
            s.linear_velocity_m_s+cross(s.angular_velocity_rad_s,r),s.angular_velocity_rad_s});}
    return out;
}
ComponentTransferReceipt RigidComponent::expand(JoltWorld &world,Vec3 gravity){
    ComponentTransferReceipt out;if(!collapsed_){out.reason="not collapsed";return out;}
    const auto states=snapshots(world);std::vector<MatterBodyId> ids;for(const auto &c:cells_)ids.push_back(c.id);
    out.audit.before=measureRigidMechanics(world.mechanicalState(proxy_),gravity);
    if(!world.restoreFaceComponent(ids,states,out.reason))return out;
    world.removeAndDestroy(proxy_);collapsed_=false;
    for(const auto &c:cells_)out.audit.after+=measureRigidMechanics(world.mechanicalState(c.id),gravity);
    out.audit.measured=true;out.admitted=close(out.audit,budget_);
    if(!out.admitted)out.reason="restored native transfer exceeds measured budget; original cells restored";
    return out;
}
}
