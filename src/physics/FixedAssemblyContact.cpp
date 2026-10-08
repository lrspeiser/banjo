#include "physics/FixedAssemblyContact.hpp"
#include "physics/ContactTensor.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>
#include <sstream>
#include <tuple>

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
    const std::vector<std::uint32_t> &edge,std::uint32_t striker,Vec3 contact_j,Vec3 contact_moment) {
    const auto count=before.size();
    std::vector<Vec3> force(count),moment(count);
    ReactionAudit out;out.impulses.resize(links.size());
    for(std::size_t i=0;i<count;++i) {
        force[i]=before[i].mass_kg*(after[i].motion.linear_velocity_m_s-before[i].motion.linear_velocity_m_s);
        moment[i]=cross(before[i].motion.center_of_mass_world_m,force[i])+before[i].inertia_world_kg_m2*
            (after[i].motion.angular_velocity_rad_s-before[i].motion.angular_velocity_rad_s);
        out.momentum+=force[i];out.angular+=moment[i];
    }
    force[striker]-=contact_j;moment[striker]-=contact_moment;
    out.momentum-=contact_j;out.angular-=contact_moment;
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
        norm(moment[0])>1e-10*(1+norm(contact_moment)))
        throw std::domain_error("fixed tree reaction does not close at its root");
    return out;
}
struct FixedReduction {
    RigidMechanicalState modal;
    std::vector<RigidMechanicalState> reconciled;
    std::vector<Vec3> radius;
    std::vector<std::uint32_t> order,parent,edge;
};
FixedReduction reduceFixed(const std::vector<RigidMechanicalState> &bodies,
    const std::vector<FixedVelocityLink> &links,std::uint32_t striker) {
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
    modal.motion.center_of_mass_world_m=bodies[striker].motion.center_of_mass_world_m-radius[striker];
    modal.motion.linear_velocity_m_s=velocity;modal.motion.angular_velocity_rad_s=spin;
    return {modal,reconciled,radius,order,parent,edge};
}
} // namespace
FixedSurfaceManifoldResult evaluateFixedSurfaceManifold(std::span<const ActiveNodeState> nodes,
    const std::vector<FixedSurfaceContact> &contacts,const std::vector<RigidMechanicalState> &bodies,
    const std::vector<FixedVelocityLink> &links,std::uint32_t striker,double dt) {
    require(nodes.size()>=4&&nodes.size()<=64&&contacts.size()<=64&&std::isfinite(dt)&&dt>0,
        "fixed material manifold exceeds its bounded node/contact domain");
    for(const auto &n:nodes)require(std::isfinite(n.mass_kg)&&n.mass_kg>0&&finite(n.position_world_m)&&
        finite(n.previous_position_world_m)&&finite(n.velocity_m_s)&&norm(n.spin_angular_velocity_rad_s)==0,
        "invalid actual translational manifold node");
    const auto reduction=reduceFixed(bodies,links,striker);
    const auto &modal=reduction.modal;const auto inverse_inertia=inverseContactTensor(modal.inertia_world_kg_m2);
    FixedSurfaceManifoldResult out;out.bodies=bodies;
    for(const auto &n:nodes)out.node_velocities_m_s.push_back(n.velocity_m_s);
    out.impulses_n_s.resize(contacts.size());
    struct Block {std::size_t original;Vec3 normal,arm,relative;double wanted;std::vector<double> weights;};
    std::vector<Block> blocks;
    std::vector<std::size_t> order;
    for(std::size_t k=0;k<contacts.size();++k)order.push_back(k);
    std::sort(order.begin(),order.end(),[&](auto a,auto b) {
        const auto &x=contacts[a];const auto &y=contacts[b];
        return std::tie(x.surface_world_m.x,x.surface_world_m.y,x.surface_world_m.z,
            x.normal_world.x,x.normal_world.y,x.normal_world.z,x.gap_m,x.nodes)<
            std::tie(y.surface_world_m.x,y.surface_world_m.y,y.surface_world_m.z,
            y.normal_world.x,y.normal_world.y,y.normal_world.z,y.gap_m,y.nodes);
    });
    double speed_scale=1;
    for(const auto k:order) {
        const auto &c=contacts[k];std::vector<ActiveNodeState> support;
        require(c.nodes.size()>=4&&c.nodes.size()<=64,"invalid manifold material support");
        for(std::size_t j=0;j<c.nodes.size();++j) {
            require(c.nodes[j]<nodes.size(),"manifold support node outside actual state");
            for(std::size_t i=0;i<j;++i)require(c.nodes[i]!=c.nodes[j],"duplicate manifold support node");
            support.push_back(nodes[c.nodes[j]]);
        }
        const auto stencil=makeMaterialContactStencil(support,c.surface_world_m);
        // Admit declarations without solving an unused isolated response.
        // Targets use the reconciled PRE-impact velocities; the simultaneous
        // response retains its complete Coulomb residual and whole-work audit.
        validatePointRigidContactLaw(c.normal_world,c.gap_m,dt,c.settings);
        const Vec3 relative=stencil.point.velocity_m_s-modal.motion.linear_velocity_m_s-
            cross(modal.motion.angular_velocity_rad_s,c.surface_world_m-modal.motion.center_of_mass_world_m);
        const double vn=dot(relative,c.normal_world);
        require(finite(relative)&&std::isfinite(norm(relative))&&std::isfinite(vn),
            "manifold contact kinematics overflow");
        if(c.gap_m>std::max(c.settings.contact_margin_m,-vn*dt))continue;
        const double e=-vn>c.settings.restitution_speed_threshold_m_s?c.settings.restitution:0;
        const double wanted=c.gap_m>c.settings.contact_margin_m?-c.gap_m/dt:-e*std::min(vn,0.);
        require(std::isfinite(wanted),"manifold contact target overflow");
        Block b{k,c.normal_world,c.surface_world_m-modal.motion.center_of_mass_world_m,relative,wanted,
            std::vector<double>(nodes.size())};
        for(std::size_t j=0;j<c.nodes.size();++j)b.weights[c.nodes[j]]=stencil.weights[j];
        speed_scale=std::max({speed_scale,norm(relative),std::abs(wanted)});blocks.push_back(std::move(b));
    }
    if(blocks.empty())return out;
    const auto count=blocks.size();
    std::vector<std::vector<Mat3>> response(count,std::vector<Mat3>(count));
    const Vec3 axes[]{{1,0,0},{0,1,0},{0,0,1}};
    for(std::size_t a=0;a<count;++a)for(std::size_t b=0;b<count;++b) {
        double inverse_mass=1/modal.mass_kg;
        for(std::size_t n=0;n<nodes.size();++n)inverse_mass+=blocks[a].weights[n]*blocks[b].weights[n]/nodes[n].mass_kg;
        for(unsigned axis=0;axis<3;++axis) {
            const Vec3 v=inverse_mass*axes[axis]+cross(inverse_inertia*cross(blocks[b].arm,axes[axis]),blocks[a].arm);
            response[a][b].m[0][axis]=v.x;response[a][b].m[1][axis]=v.y;response[a][b].m[2][axis]=v.z;
        }
    }
    std::vector<Vec3> impulses(count);std::vector<bool> sliding(count,false);
    // Find a unilateral normal-contact starting guess before the Coulomb
    // search. Nearly redundant patches can leave block sweeps on a branch
    // carrying load at a separating contact. This bounded active-set solve
    // is only initialization: the unchanged complete friction residual and
    // whole-system work audit still decide the published response.
    const auto normal_start=[&]() {
        std::vector<std::vector<double>> matrix(count,std::vector<double>(count));
        std::vector<double> offset(count),x(count);std::vector<bool> active(count,false);
        double scale=0;
        for(std::size_t a=0;a<count;++a) {
            offset[a]=dot(blocks[a].relative,blocks[a].normal)-blocks[a].wanted;
            for(std::size_t b=0;b<count;++b)
                matrix[a][b]=dot(blocks[a].normal,response[a][b]*blocks[b].normal);
            scale=std::max(scale,std::abs(matrix[a][a]));
        }
        const double bound=1e-12*speed_scale;
        unsigned remaining=static_cast<unsigned>(4*count*count+1);
        while(remaining>0) {
            --remaining;
            std::size_t enter=count;double worst=-bound;
            for(std::size_t a=0;a<count;++a)if(!active[a]) {
                double gradient=offset[a];for(std::size_t b=0;b<count;++b)gradient+=matrix[a][b]*x[b];
                if(!std::isfinite(gradient))return std::vector<double>(count);
                if(gradient<worst){worst=gradient;enter=a;}
            }
            if(enter==count)return x;
            active[enter]=true;
            bool accepted=false;
            while(remaining>0) {
                --remaining;
                std::vector<std::size_t> ids;
                for(std::size_t a=0;a<count;++a)if(active[a])ids.push_back(a);
                std::vector<std::vector<double>> lower(ids.size(),std::vector<double>(ids.size()));
                for(std::size_t row=0;row<ids.size();++row)for(std::size_t col=0;col<=row;++col) {
                    double value=.5*(matrix[ids[row]][ids[col]]+matrix[ids[col]][ids[row]]);
                    for(std::size_t k=0;k<col;++k)value-=lower[row][k]*lower[col][k];
                    if(row==col) {
                        // Singular initialization is harmless: let the full
                        // bounded contact search start from zero as before.
                        if(!std::isfinite(value)||value<=64*std::numeric_limits<double>::epsilon()*scale)
                            return std::vector<double>(count);
                        lower[row][col]=std::sqrt(value);
                    } else lower[row][col]=value/lower[col][col];
                }
                std::vector<double> y(ids.size()),z(count);
                for(std::size_t row=0;row<ids.size();++row) {
                    double value=-offset[ids[row]];for(std::size_t k=0;k<row;++k)value-=lower[row][k]*y[k];
                    y[row]=value/lower[row][row];
                }
                for(std::size_t row=ids.size();row-->0;) {
                    double value=y[row];for(std::size_t k=row+1;k<ids.size();++k)value-=lower[k][row]*z[ids[k]];
                    z[ids[row]]=value/lower[row][row];
                    if(!std::isfinite(z[ids[row]]))return std::vector<double>(count);
                }
                double fraction=1;std::size_t leaving=count;
                for(const auto id:ids)if(z[id]<0) {
                    const double candidate=x[id]/(x[id]-z[id]);
                    if(candidate<=fraction){fraction=candidate;leaving=id;}
                }
                if(leaving==count){x=std::move(z);accepted=true;break;}
                for(std::size_t a=0;a<count;++a)x[a]+=fraction*(z[a]-x[a]);
                // The blocking variable is exactly on its zero bound. Do not
                // let interpolation roundoff keep it active and cycle forever
                // at a subsequent zero-length step.
                x[leaving]=0;active[leaving]=false;
                for(const auto id:ids)if(x[id]<=0){x[id]=0;active[id]=false;}
            }
            if(!accepted)break;
        }
        return std::vector<double>(count);
    };
    const auto initial_normal=normal_start();
    for(std::size_t a=0;a<count;++a)impulses[a]=initial_normal[a]*blocks[a].normal;
    const auto without=[&](std::size_t a) {
        Vec3 v=blocks[a].relative;
        for(std::size_t b=0;b<count;++b)if(b!=a)v+=response[a][b]*impulses[b];
        return v;
    };
    const bool initialized=std::any_of(initial_normal.begin(),initial_normal.end(),[](double j){return j>0;});
    std::vector<bool> inactive(count,false);
    if(initialized)for(std::size_t a=0;a<count;++a)inactive[a]=initial_normal[a]==0;
    const auto full_update=[&](std::size_t a) {
        const auto &c=contacts[blocks[a].original];
        return solveCoulombContactImpulse(without(a),blocks[a].normal,response[a][a],blocks[a].wanted,
            sliding[a]?c.settings.dynamic_friction:c.settings.static_friction,
            sliding[a]?c.settings.dynamic_friction:c.settings.static_friction);
    };
    const auto update=[&](std::size_t a) {return inactive[a]?Vec3{}:full_update(a);};
    // Checking all blocks after each sweep prevents accepting an early contact
    // that was invalidated by a later shared-cell/source impulse.
    const double tolerance=1e-10*speed_scale;
    bool converged=false;double last_residual=0;
        for(std::size_t phase=0;phase<=2*count;++phase) {
    converged=false;
    for(unsigned iteration=1;iteration<=((initialized&&phase==0)?0U:32U);++iteration) {
        for(std::size_t a=0;a<count;++a)impulses[a]=.5*(impulses[a]+update(a));
        double residual=0;
        for(std::size_t a=0;a<count;++a)residual=std::max(residual,norm(response[a][a]*(update(a)-impulses[a])));
        out.iterations=iteration;
        last_residual=residual;
        if(residual<=tolerance){converged=true;break;}
    }
    // Rank-deficient overlapping supports can make block sweeps arbitrarily
    // slow or cycle at a stick/slip switch. Solve the same fixed-point residual
    // with a damped least-squares Newton correction; damping affects the search
    // direction only, never the admitted physical response or acceptance bound.
    const auto residual_vector=[&]() {
        std::vector<double> r(3*count);
        for(std::size_t a=0;a<count;++a) {
            const auto v=response[a][a]*(impulses[a]-update(a));
            r[3*a]=v.x;r[3*a+1]=v.y;r[3*a+2]=v.z;
        }
        return r;
    };
    const auto squared=[](const std::vector<double> &r){double value=0;for(const auto x:r)value+=x*x;return value;};
    const auto maximum=[](const std::vector<double> &r){double value=0;for(std::size_t k=0;k<r.size();k+=3)
        value=std::max(value,std::hypot(r[k],r[k+1],r[k+2]));return value;};
    double damping=1e-8;
    for(unsigned attempt=0;!converged&&attempt<96;++attempt) {
        const auto base=impulses;const auto r=residual_vector();last_residual=maximum(r);
        if(last_residual<=tolerance){converged=true;break;}
        const std::size_t dimension=r.size();std::vector<std::vector<double>> jacobian(dimension,std::vector<double>(dimension));
        for(std::size_t col=0;col<dimension;++col) {
            const auto a=col/3;const unsigned axis=static_cast<unsigned>(col%3);
            // Nearly redundant face rows approach stick/slip boundaries with
            // corrections below the former relative 1e-7 probe. A smaller
            // Jacobian probe resolves that local branch; the full-law residual
            // and work bounds below still admit or refuse the response.
            const double h=1e-9*std::max(1e-3,norm(base[a]));
            impulses=base;impulses[a]+=h*axes[axis];const auto plus=residual_vector();
            impulses=base;impulses[a]-=h*axes[axis];const auto minus=residual_vector();
            for(std::size_t row=0;row<dimension;++row)jacobian[row][col]=(plus[row]-minus[row])/(2*h);
        }
        impulses=base;
        // Pivoted, reorthogonalized QR avoids squaring the condition number of
        // nearly redundant affine supports (normal equations lose their small
        // physical modes before the unchanged contact residual is satisfied).
        double scale=0;
        for(std::size_t col=0;col<dimension;++col) {
            double norm2=0;for(std::size_t row=0;row<dimension;++row)norm2+=jacobian[row][col]*jacobian[row][col];
            scale=std::max(scale,norm2);
        }
        std::vector<std::vector<double>> columns(dimension,std::vector<double>(2*dimension));
        std::vector<std::vector<double>> triangular(dimension,std::vector<double>(dimension));
        std::vector<double> projected(dimension);std::vector<std::size_t> permutation(dimension);
        for(std::size_t col=0;col<dimension;++col) {
            permutation[col]=col;
            for(std::size_t row=0;row<dimension;++row)columns[col][row]=jacobian[row][col];
            columns[col][dimension+col]=std::sqrt(damping*std::max(scale,1e-30));
        }
        std::size_t rank=dimension;
        for(std::size_t col=0;col<dimension;++col) {
            std::size_t pivot=col;for(std::size_t k=col+1;k<dimension;++k)
                if(squared(columns[k])>squared(columns[pivot]))pivot=k;
            std::swap(columns[pivot],columns[col]);std::swap(permutation[pivot],permutation[col]);
            for(std::size_t row=0;row<col;++row)std::swap(triangular[row][pivot],triangular[row][col]);
            const double diagonal=std::sqrt(squared(columns[col]));
            if(!std::isfinite(diagonal)||diagonal<=1e-14*std::sqrt(scale)){rank=col;break;}
            triangular[col][col]=diagonal;
            for(auto &x:columns[col])x/=diagonal;
            for(std::size_t row=0;row<dimension;++row)projected[col]-=columns[col][row]*r[row];
            for(std::size_t k=col+1;k<dimension;++k)for(unsigned pass=0;pass<2;++pass) {
                double coefficient=0;for(std::size_t row=0;row<2*dimension;++row)coefficient+=columns[col][row]*columns[k][row];
                triangular[col][k]+=coefficient;
                for(std::size_t row=0;row<2*dimension;++row)columns[k][row]-=coefficient*columns[col][row];
            }
        }
        std::vector<double> pivoted_step(dimension),step(dimension);
        for(std::size_t a=rank;a-->0;) {
            double value=projected[a];for(std::size_t b=a+1;b<rank;++b)value-=triangular[a][b]*pivoted_step[b];
            pivoted_step[a]=value/triangular[a][a];
        }
        for(std::size_t a=0;a<dimension;++a)step[permutation[a]]=pivoted_step[a];
        bool accepted=false;
        for(unsigned backtrack=0;backtrack<16;++backtrack) {
            const double fraction=std::ldexp(1.,-static_cast<int>(backtrack));impulses=base;
            for(std::size_t a=0;a<count;++a)impulses[a]+=fraction*Vec3{step[3*a],step[3*a+1],step[3*a+2]};
            for(std::size_t a=0;a<count;++a)if(inactive[a])impulses[a]={};
            const auto candidate=residual_vector();
            if(squared(candidate)<squared(r)){accepted=true;last_residual=maximum(candidate);break;}
        }
        ++out.iterations;
        if(accepted){damping=std::max(1e-24,damping*.1);converged=last_residual<=tolerance;}
        else {impulses=base;damping*=10;if(damping>1e8)break;}
    }
    if(!converged)break;
    bool changed=false;
    // A tentative inactive mode stays exactly zero while the active friction
    // equations converge. Then re-admit every contact that the FULL unchanged
    // Coulomb law says is violated. The normal-only guess never authorizes a
    // discarded contact or a weakened final residual.
    for(std::size_t a=0;a<count;++a)if(inactive[a]&&
        norm(response[a][a]*(full_update(a)-impulses[a]))>tolerance) {
        inactive[a]=false;changed=true;
    }
    for(std::size_t a=0;a<count;++a)if(!sliding[a]) {
        Vec3 final_relative=blocks[a].relative;
        for(std::size_t b=0;b<count;++b)final_relative+=response[a][b]*impulses[b];
        const auto tangent=final_relative-dot(final_relative,blocks[a].normal)*blocks[a].normal;
        if(norm(tangent)>tolerance&&norm(impulses[a])>0&&
            contacts[blocks[a].original].settings.static_friction!=contacts[blocks[a].original].settings.dynamic_friction) {
            sliding[a]=true;changed=true;
        }
    }
    if(!changed)break;
    }
    // Check the full law even if the bounded mode search exhausted its phases.
    // This also prevents a final static-to-dynamic switch from being published
    // without solving the newly selected law.
    last_residual=0;
    for(std::size_t a=0;a<count;++a)
        last_residual=std::max(last_residual,norm(response[a][a]*(impulses[a]-full_update(a))));
    converged=converged&&last_residual<=tolerance;
    if(!converged){
        std::ostringstream message;message<<"coupled material manifold did not converge within its search budget: residual "
        <<last_residual<<" m/s, tolerance "<<tolerance<<", blocks "<<count;
        for(std::size_t a=0;a<count;++a)message<<" [p="<<contacts[blocks[a].original].surface_world_m.x<<","<<contacts[blocks[a].original].surface_world_m.y<<","<<contacts[blocks[a].original].surface_world_m.z<<" n="<<blocks[a].normal.x<<","<<blocks[a].normal.y<<","<<blocks[a].normal.z<<" v="<<blocks[a].relative.x<<","<<blocks[a].relative.y<<","<<blocks[a].relative.z<<" target="<<blocks[a].wanted<<"]";
        throw std::domain_error(message.str());}
    Vec3 total_j{},total_moment{},modal_moment{};double work=0;
    for(std::size_t a=0;a<count;++a) {
        const auto &b=blocks[a];const auto j=impulses[a];out.impulses_n_s[b.original]=j;
        if(norm(j)>0)++out.active_contacts;
        total_j+=j;modal_moment+=cross(b.arm,j);total_moment+=cross(contacts[b.original].surface_world_m,j);
        Vec3 final_relative=b.relative;
        for(std::size_t k=0;k<count;++k)final_relative+=response[a][k]*impulses[k];
        work+=dot(j,.5*(b.relative+final_relative));
        for(std::size_t n=0;n<nodes.size();++n)out.node_velocities_m_s[n]+=(b.weights[n]/nodes[n].mass_kg)*j;
    }
    if(!out.active_contacts)return out; // No joint-only projection is published.
    auto final_modal=modal;
    final_modal.motion.linear_velocity_m_s-=total_j/modal.mass_kg;
    final_modal.motion.angular_velocity_rad_s-=inverse_inertia*modal_moment;
    out.bodies=reduction.reconciled;
    for(std::size_t i=0;i<bodies.size();++i) {
        out.bodies[i].motion.linear_velocity_m_s=final_modal.motion.linear_velocity_m_s+
            cross(final_modal.motion.angular_velocity_rad_s,reduction.radius[i]);
        out.bodies[i].motion.angular_velocity_rad_s=final_modal.motion.angular_velocity_rad_s;
    }
    const double before=kinetic(bodies),projected=kinetic(reduction.reconciled);
    const double bound=1e-12+1e-10*(std::abs(before)+std::abs(projected)+std::abs(work));
    if(!std::isfinite(work)||work>bound||projected>before+bound)
        throw std::domain_error("coupled material manifold gained kinetic energy");
    out.reconciliation_loss_j=std::max(0.,before-projected);out.dissipated_energy_j=std::max(0.,-work);
    const auto reconcile=reactions(bodies,reduction.reconciled,links,reduction.order,reduction.parent,reduction.edge,striker,{},{});
    const auto contact=reactions(reduction.reconciled,out.bodies,links,reduction.order,reduction.parent,reduction.edge,striker,-total_j,-total_moment);
    out.reconciliation=reconcile.impulses;out.contact_reactions=contact.impulses;
    out.geometry_couple_kg_m2_s=reconcile.couple+contact.couple;
    out.momentum_residual_kg_m_s=reconcile.momentum+contact.momentum;
    out.angular_residual_kg_m2_s=reconcile.angular+contact.angular;
    out.kinetic_change_j=kinetic(out.bodies)-before;
    for(std::size_t n=0;n<nodes.size();++n) {
        require(finite(out.node_velocities_m_s[n]),"coupled manifold node velocity overflow");
        out.kinetic_change_j+=.5*nodes[n].mass_kg*dot(out.node_velocities_m_s[n]-nodes[n].velocity_m_s,
            out.node_velocities_m_s[n]+nodes[n].velocity_m_s);
    }
    out.work_residual_j=out.kinetic_change_j+out.reconciliation_loss_j+out.dissipated_energy_j;
    if(!std::isfinite(out.work_residual_j)||std::abs(out.work_residual_j)>bound||
        std::abs(reconcile.work+out.reconciliation_loss_j)>bound||std::abs(contact.work)>bound)
        throw std::domain_error("coupled material manifold failed its whole-system work audit");
    return out;
}
FixedAssemblyContactResult evaluatePointFixedAssemblyContact(const ActiveNodeState &point,
    const std::vector<RigidMechanicalState> &bodies,const std::vector<FixedVelocityLink> &links,
    std::uint32_t striker,Vec3 normal,double gap,double duration,const PointRigidContactSettings &settings) {
    const auto count=bodies.size();
    const auto reduction=reduceFixed(bodies,links,striker);
    const auto &reconciled=reduction.reconciled;const auto &radius=reduction.radius;
    const auto &order=reduction.order;const auto &parent=reduction.parent;const auto &edge=reduction.edge;
    const auto &modal=reduction.modal;
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
    const auto reconcile=reactions(bodies,reconciled,links,order,parent,edge,striker,{},{});
    const auto contact=reactions(reconciled,out.bodies,links,order,parent,edge,striker,-out.modal_contact.impulse_to_node_n_s,
                                cross(point.position_world_m,-out.modal_contact.impulse_to_node_n_s));
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
