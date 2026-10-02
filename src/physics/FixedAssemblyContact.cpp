#include "physics/FixedAssemblyContact.hpp"
#include "physics/ContactTensor.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace banjo {
namespace {
bool finite(Vec3 v) {return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
double norm(Vec3 v) {return std::hypot(v.x,v.y,v.z);}
void require(bool value,const char *why) {if(!value)throw std::invalid_argument(why);}
double kinetic(const std::vector<RigidMechanicalState> &bodies) {
    double result=0;for(const auto &body:bodies)result+=measureRigidMechanics(body).kinetic_energy_j;return result;
}
struct ReactionAudit {
    std::vector<FixedVelocityImpulse> impulses;
    double work{};
    Vec3 momentum{},couple{},angular{};
};
ReactionAudit reactions(const std::vector<RigidMechanicalState> &before,
    const std::vector<RigidMechanicalState> &after,const std::vector<FixedVelocityLink> &links,
    const std::vector<std::uint32_t> &order,const std::vector<std::uint32_t> &parent,
    const std::vector<std::uint32_t> &edge,std::uint32_t striker,Vec3 contact_point,Vec3 contact_j) {
    const auto count=before.size();
    std::vector<Vec3> force(count),moment(count);
    ReactionAudit out;out.impulses.resize(links.size());
    for(std::size_t i=0;i<count;++i) {
        force[i]=before[i].mass_kg*(after[i].motion.linear_velocity_m_s-before[i].motion.linear_velocity_m_s);
        moment[i]=cross(before[i].motion.center_of_mass_world_m,force[i])+before[i].inertia_world_kg_m2*
            (after[i].motion.angular_velocity_rad_s-before[i].motion.angular_velocity_rad_s);
        out.momentum+=force[i];out.angular+=moment[i];
    }
    force[striker]-=contact_j;moment[striker]-=cross(contact_point,contact_j);
    out.momentum-=contact_j;out.angular-=cross(contact_point,contact_j);
    for(std::size_t k=order.size();k-->1;) {
        const auto child=order[k],up=parent[child],link_id=edge[child];
        const auto &link=links[link_id];
        const bool child_is_b=child==link.b;
        const Vec3 at_child=child_is_b?link.point_b_world_m:link.point_a_world_m;
        const Vec3 at_parent=child_is_b?link.point_a_world_m:link.point_b_world_m;
        const Vec3 torque=moment[child]-cross(at_child,force[child]);
        auto &impulse=out.impulses[link_id];
        impulse.impulse_on_b_n_s=child_is_b?force[child]:-force[child];
        impulse.free_angular_impulse_on_b_kg_m2_s=child_is_b?torque:-torque;
        force[up]+=force[child];moment[up]+=cross(at_parent,force[child])+torque;
    }
    const auto speed=[](const RigidMechanicalState &a,const RigidMechanicalState &b,Vec3 at) {
        return .5*(a.motion.linear_velocity_m_s+b.motion.linear_velocity_m_s)+
            cross(.5*(a.motion.angular_velocity_rad_s+b.motion.angular_velocity_rad_s),at-a.motion.center_of_mass_world_m);
    };
    for(std::size_t i=0;i<links.size();++i) {
        const auto &link=links[i];auto &impulse=out.impulses[i];
        const auto a=link.a,b=link.b;
        impulse.work_j=dot(impulse.impulse_on_b_n_s,speed(before[b],after[b],link.point_b_world_m)-
            speed(before[a],after[a],link.point_a_world_m))+dot(impulse.free_angular_impulse_on_b_kg_m2_s,
            .5*(before[b].motion.angular_velocity_rad_s+after[b].motion.angular_velocity_rad_s-
                before[a].motion.angular_velocity_rad_s-after[a].motion.angular_velocity_rad_s));
        out.work+=impulse.work_j;
        out.couple+=cross(link.point_b_world_m-link.point_a_world_m,impulse.impulse_on_b_n_s);
    }
    out.angular-=out.couple;
    if(!finite(force[0])||!finite(moment[0])||norm(force[0])>1e-10*(1+norm(contact_j))||
        norm(moment[0])>1e-10*(1+norm(cross(contact_point,contact_j))))
        throw std::domain_error("fixed tree reaction does not close at its root");
    return out;
}
} // namespace
FixedAssemblyContactResult evaluatePointFixedAssemblyContact(const ActiveNodeState &point,
    const std::vector<RigidMechanicalState> &bodies,const std::vector<FixedVelocityLink> &links,
    std::uint32_t striker,Vec3 normal,double gap,double duration,const PointRigidContactSettings &settings) {
    const auto count=bodies.size();
    require(count>=1&&count<=256&&striker<count&&links.size()==count-1,"fixed contact needs a 1..256 body tree");
    const auto unseen=std::numeric_limits<std::uint32_t>::max();
    std::vector<std::vector<std::pair<std::uint32_t,std::uint32_t>>> graph(count);
    for(std::uint32_t i=0;i<links.size();++i) {
        const auto &link=links[i];
        require(link.a<count&&link.b<count&&link.a!=link.b&&finite(link.point_a_world_m)&&finite(link.point_b_world_m),
                "invalid fixed tree link");
        graph[link.a].push_back({link.b,i});graph[link.b].push_back({link.a,i});
    }
    std::vector<std::uint32_t> order{0},parent(count,unseen),edge(count,unseen);parent[0]=0;
    std::vector<Vec3> offset(count),radius(count);
    for(std::size_t k=0;k<order.size();++k) {
        const auto at=order[k];
        for(const auto &[next,link_id]:graph[at]) {
            if(link_id==edge[at])continue;
            require(parent[next]==unseen,"fixed contact graph contains a cycle");
            parent[next]=at;edge[next]=link_id;order.push_back(next);
            const auto &link=links[link_id];
            const Vec3 here=at==link.a?link.point_a_world_m:link.point_b_world_m;
            const Vec3 there=at==link.a?link.point_b_world_m:link.point_a_world_m;
            offset[next]=offset[at]+(here-bodies[at].motion.center_of_mass_world_m)-
                (there-bodies[next].motion.center_of_mass_world_m);
        }
    }
    require(order.size()==count,"fixed contact graph is disconnected");
    double mass=0;Vec3 centroid{},momentum{};
    for(std::size_t i=0;i<count;++i) {
        const auto &body=bodies[i];
        require(std::isfinite(body.mass_kg)&&body.mass_kg>0&&finite(body.motion.center_of_mass_world_m)&&
            finite(body.motion.linear_velocity_m_s)&&finite(body.motion.angular_velocity_rad_s)&&finite(offset[i]),
            "invalid fixed contact body or kinematic arm");
        (void)inverseContactTensor(body.inertia_world_kg_m2);
        mass+=body.mass_kg;centroid+=body.mass_kg*offset[i];momentum+=body.mass_kg*body.motion.linear_velocity_m_s;
    }
    require(std::isfinite(mass)&&finite(centroid)&&finite(momentum),"fixed contact total mass/momentum overflow");
    centroid=centroid/mass;
    Mat3 inertia;Vec3 angular{};
    for(std::size_t i=0;i<count;++i) {
        const auto &body=bodies[i];radius[i]=offset[i]-centroid;
        const double r[]{radius[i].x,radius[i].y,radius[i].z};
        for(unsigned a=0;a<3;++a)for(unsigned b=0;b<3;++b)
            inertia.m[a][b]+=body.inertia_world_kg_m2.m[a][b]+body.mass_kg*((a==b?lengthSquared(radius[i]):0)-r[a]*r[b]);
        angular+=body.inertia_world_kg_m2*body.motion.angular_velocity_rad_s+
            cross(radius[i],body.mass_kg*body.motion.linear_velocity_m_s);
    }
    const Vec3 velocity=momentum/mass,spin=inverseContactTensor(inertia)*angular;
    require(finite(velocity)&&finite(spin),"fixed contact reduced motion overflow");
    auto reconciled=bodies;
    for(std::size_t i=0;i<count;++i) {
        reconciled[i].motion.linear_velocity_m_s=velocity+cross(spin,radius[i]);
        reconciled[i].motion.angular_velocity_rad_s=spin;
    }
    RigidMechanicalState modal;
    modal.mass_kg=mass;modal.inertia_world_kg_m2=inertia;
    const Vec3 arm=radius[striker]+point.position_world_m-bodies[striker].motion.center_of_mass_world_m;
    modal.motion.center_of_mass_world_m=point.position_world_m-arm;
    modal.motion.linear_velocity_m_s=velocity;modal.motion.angular_velocity_rad_s=spin;
    FixedAssemblyContactResult out;
    out.modal_contact=evaluatePointRigidContact(point,modal,normal,gap,duration,settings);
    out.bodies=bodies;
    if(!out.modal_contact.applied)return out; // No contact does not publish a joint-only projection.
    const double before=kinetic(bodies),projected=kinetic(reconciled);
    const double bound=1e-12+1e-10*(std::abs(before)+std::abs(projected)+std::abs(out.modal_contact.impulse_work_j));
    if(!std::isfinite(before)||!std::isfinite(projected)||projected>before+bound)
        throw std::domain_error("fixed reconciliation gained kinetic energy");
    out.reconciliation_loss_j=std::max(0.,before-projected);
    out.bodies=reconciled;
    const auto &result=out.modal_contact.rigid.motion;
    for(std::size_t i=0;i<count;++i) {
        out.bodies[i].motion.linear_velocity_m_s=result.linear_velocity_m_s+cross(result.angular_velocity_rad_s,radius[i]);
        out.bodies[i].motion.angular_velocity_rad_s=result.angular_velocity_rad_s;
    }
    const auto reconcile=reactions(bodies,reconciled,links,order,parent,edge,striker,point.position_world_m,{});
    const auto contact=reactions(reconciled,out.bodies,links,order,parent,edge,striker,point.position_world_m,
                                -out.modal_contact.impulse_to_node_n_s);
    out.reconciliation=reconcile.impulses;out.contact_reactions=contact.impulses;
    out.geometry_couple_kg_m2_s=reconcile.couple+contact.couple;
    out.momentum_residual_kg_m_s=reconcile.momentum+contact.momentum;
    out.angular_residual_kg_m2_s=reconcile.angular+contact.angular;
    const double point_change=.5*point.mass_kg*dot(out.modal_contact.node_velocity_m_s-point.velocity_m_s,
        out.modal_contact.node_velocity_m_s+point.velocity_m_s);
    out.kinetic_change_j=kinetic(out.bodies)-before+point_change;
    out.work_residual_j=out.kinetic_change_j+out.reconciliation_loss_j+out.modal_contact.dissipated_energy_j;
    if(!std::isfinite(out.work_residual_j)||std::abs(out.work_residual_j)>bound||
        std::abs(reconcile.work+out.reconciliation_loss_j)>bound||std::abs(contact.work)>bound||
        !finite(out.momentum_residual_kg_m_s)||!finite(out.angular_residual_kg_m2_s))
        throw std::domain_error("fixed point contact failed its constraint/work audit");
    return out;
}
} // namespace banjo
