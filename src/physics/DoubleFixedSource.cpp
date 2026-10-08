#include "physics/DoubleFixedSource.hpp"
#include "core/RigidPrimitive.hpp"
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {
Quat product(Quat a,Quat b){return {a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,
    a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,
    a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};}
void require(bool ok,const char *why){if(!ok)throw std::invalid_argument(why);}
}
DoubleFixedSource::DoubleFixedSource(const std::vector<RigidMechanicalState> &bodies,
    const std::vector<FixedVelocityLink> &links) {
    // Validate physical tensor/rotation before reduction; display/material names
    // are never involved. Closed geometry is required, not silently snapped.
    for(const auto &body:bodies)(void)makeDoubleRigidState(body);
    for(const auto &link:links)require(length(link.point_a_world_m-link.point_b_world_m)==0,
        "double fixed source import requires exactly coincident fixing anchors");
    import_=reconcileFixedAssembly(bodies,links);
    state_=makeDoubleRigidState(import_.modal);
    for(const auto &body:bodies)members_.push_back({body.mass_kg,
        body.motion.center_of_mass_world_m-state_.center_world_m,body.motion.orientation_world,body.inertia_world_kg_m2});
    for(const auto &link:links)links_.push_back({link.a,link.b,link.point_a_world_m-state_.center_world_m});
}
std::vector<RigidMechanicalState> DoubleFixedSource::bodies() const {
    const auto aggregate=doubleRigidMechanics(state_);const auto omega=aggregate.motion.angular_velocity_rad_s;
    std::vector<RigidMechanicalState> out;out.reserve(members_.size());
    for(const auto &m:members_) {
        const auto radius=state_.orientation_world.rotate(m.offset);
        out.push_back({{state_.center_world_m+radius,product(state_.orientation_world,m.orientation),
            state_.velocity_world_m_s+cross(omega,radius),omega},m.mass,rotateInertia(m.inertia,state_.orientation_world)});
    }
    return out;
}
std::vector<FixedVelocityLink> DoubleFixedSource::links() const {
    std::vector<FixedVelocityLink> out;out.reserve(links_.size());
    for(const auto &link:links_){const auto at=state_.center_world_m+state_.orientation_world.rotate(link.anchor);
        out.push_back({link.a,link.b,at,at});}
    return out;
}
DoubleRigidTransfer DoubleFixedSource::advanceFree(double dt) {
    // Same compensated accepted-clock arithmetic as the material backend.
    // The dynamics still advance by dt, not by the rounding correction.
    const double corrected_dt=dt-time_correction_s_,next_time=elapsed_s_+corrected_dt;
    require(dt!=0&&std::isfinite(next_time)&&next_time>=0&&next_time!=elapsed_s_&&steps_!=std::numeric_limits<std::uint64_t>::max(),
        "double source clock/step overflow or negative absolute time");
    auto result=advanceDoubleRigidFree(state_,dt);
    time_correction_s_=(next_time-elapsed_s_)-corrected_dt;
    state_=result.state;elapsed_s_=next_time;++steps_;return result;
}
DoubleFixedSourceTransfer DoubleFixedSource::applyImpulse(std::uint32_t member,Vec3 at,Vec3 j,Vec3 couple) {
    require(member<members_.size(),"double source impulse has invalid member");
    const auto before=bodies();const auto result=applyDoubleRigidImpulse(state_,at,j,couple);
    auto candidate=*this;candidate.state_=result.state;
    const auto after=candidate.bodies();
    const auto fixing=auditFixedAssemblyVelocityChange(before,after,links(),member,j,cross(at,j)+couple);
    state_=result.state;return {result,fixing};
}
void DoubleFixedSource::adoptContact(const std::vector<RigidMechanicalState> &candidate) {
    const auto current=bodies();require(candidate.size()==current.size(),"double source contact changed member count");
    Vec3 momentum{},spin{};
    for(std::size_t i=0;i<current.size();++i) {
        const auto &a=current[i],&b=candidate[i];const auto qa=a.motion.orientation_world,qb=b.motion.orientation_world;
        require(a.mass_kg==b.mass_kg&&a.inertia_world_kg_m2.m==b.inertia_world_kg_m2.m&&
            length(a.motion.center_of_mass_world_m-b.motion.center_of_mass_world_m)==0&&
            qa.w==qb.w&&qa.x==qb.x&&qa.y==qb.y&&qa.z==qb.z,"double contact changed source physical geometry");
        (void)makeDoubleRigidState(b);
        const Vec3 p=b.mass_kg*b.motion.linear_velocity_m_s;
        momentum+=p;spin+=b.inertia_world_kg_m2*b.motion.angular_velocity_rad_s+
            cross(b.motion.center_of_mass_world_m-state_.center_world_m,p);
    }
    auto next=*this;next.state_.velocity_world_m_s=momentum/state_.mass_kg;next.state_.spin_momentum_world_kg_m2_s=spin;
    const auto derived=next.bodies();
    for(std::size_t i=0;i<derived.size();++i) {
        const auto &a=derived[i].motion,&b=candidate[i].motion;
        require(length(a.linear_velocity_m_s-b.linear_velocity_m_s)<=1e-10*(1+length(b.linear_velocity_m_s))&&
            length(a.angular_velocity_rad_s-b.angular_velocity_rad_s)<=1e-10*(1+length(b.angular_velocity_rad_s)),
            "double contact candidate violates fixed assembly motion");
    }
    state_=next.state_;
}
} // namespace banjo
