#include "physics/SmallStrainPatch.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>

namespace banjo {
namespace {
double component(const Vec3 &v,unsigned axis) { return axis==0?v.x:axis==1?v.y:v.z; }
void setComponent(Vec3 &v,unsigned axis,double value) { if(axis==0)v.x=value;else if(axis==1)v.y=value;else v.z=value; }
bool finite(Vec3 v) { return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z); }
void require(bool condition,const char *message) { if(!condition)throw std::invalid_argument(message); }
SymmetricTensor3 strainColumn(Vec3 g,unsigned axis) {
    if(axis==0)return {g.x,0,0,g.y*.5,0,g.z*.5};
    if(axis==1)return {0,g.y,0,g.x*.5,g.z*.5,0};
    return {0,0,g.z,0,g.y*.5,g.x*.5};
}
Vec3 stressTimes(const SymmetricTensor3 &s,Vec3 g) {
    return {s.xx*g.x+s.xy*g.y+s.zx*g.z,s.xy*g.x+s.yy*g.y+s.yz*g.z,s.zx*g.x+s.yz*g.y+s.zz*g.z};
}
std::pair<SymmetricTensor3,double> strainOf(const std::array<Vec3,4> &gradients,
    const PatchTet &tet,const std::vector<Vec3> &u) {
    Mat3 gradient;
    // Relative displacements avoid cancellation for uniform translation.
    for(unsigned i=1;i<4;++i) {
        const Vec3 d=u[tet.nodes[i]]-u[tet.nodes[0]],g=gradients[i];
        for(unsigned a=0;a<3;++a)for(unsigned b=0;b<3;++b)
            gradient.m[a][b]+=component(d,a)*component(g,b);
    }
    double norm2=0;for(const auto &row:gradient.m)for(double v:row)norm2+=v*v;
    return {{gradient.m[0][0],gradient.m[1][1],gradient.m[2][2],
        .5*(gradient.m[0][1]+gradient.m[1][0]),.5*(gradient.m[1][2]+gradient.m[2][1]),
        .5*(gradient.m[2][0]+gradient.m[0][2])},std::sqrt(norm2)};
}
double vectorDot(const std::vector<Vec3> &a,const std::vector<Vec3> &b) {
    double value=0;for(std::size_t i=0;i<a.size();++i)value+=dot(a[i],b[i]);return value;
}
double norm(const std::vector<Vec3> &v) {
    double value=0;for(auto entry:v){require(finite(entry),"Nonfinite patch vector");value=std::hypot(value,std::hypot(entry.x,entry.y,entry.z));}return value;
}
void zeroFixed(std::vector<Vec3> &v,const std::vector<std::array<bool,3>> &fixed) {
    for(std::size_t i=0;i<v.size();++i)for(unsigned a=0;a<3;++a)if(fixed[i][a])setComponent(v[i],a,0);
}
SymmetricTensor3 difference(const SymmetricTensor3 &a,const SymmetricTensor3 &b) {
    return {a.xx-b.xx,a.yy-b.yy,a.zz-b.zz,a.xy-b.xy,a.yz-b.yz,a.zx-b.zx};
}
}

SmallStrainPatch::SmallStrainPatch(PatchDefinition definition):definition_(std::move(definition)) {
    const auto &d=definition_;const auto nodes=d.reference_positions_m.size();
    require(nodes>=4&&nodes<=4096,"Patch node count must be 4..4096");
    require(!d.elements.empty()&&d.elements.size()<=16384,"Patch element count must be 1..16384");
    require(!d.materials.empty()&&d.materials.size()<=64,"Patch material count must be 1..64");
    require(d.fixed_components.size()==nodes,"Patch constraint count differs from nodes");
    std::set<std::array<double,3>> uniquePositions;
    for(auto p:d.reference_positions_m) {
        require(finite(p)&&length(p)<=1000,"Invalid patch reference position");
        require(uniquePositions.insert({p.x,p.y,p.z}).second,"Coincident patch reference nodes");
    }
    for(const auto &m:d.materials) {
        validateSmallStrainLaw(m.law);
        require(std::isfinite(m.density_kg_m3)&&m.density_kg_m3>0&&m.density_kg_m3<=1e9,"Invalid patch density");
    }
    state_.displacements_m.resize(nodes);state_.material_points.resize(d.elements.size());
    state_.last_nodal_forces_n.resize(nodes);nodal_masses_.resize(nodes);
    struct Face { unsigned count{}; std::array<unsigned,3> outward; };
    std::map<std::array<unsigned,3>,Face> faces;
    std::set<std::array<unsigned,4>> unique;
    for(const auto &t:d.elements) {
        require(t.material<d.materials.size(),"Unknown patch element material");
        auto ids=t.nodes;for(auto id:ids)require(id<nodes,"Invalid tetrahedron node index");
        std::sort(ids.begin(),ids.end());
        require(std::adjacent_find(ids.begin(),ids.end())==ids.end()&&unique.insert(ids).second,"Duplicate tetrahedron or repeated node");
        const Vec3 p=d.reference_positions_m[t.nodes[0]],e1=d.reference_positions_m[t.nodes[1]]-p,
            e2=d.reference_positions_m[t.nodes[2]]-p,e3=d.reference_positions_m[t.nodes[3]]-p;
        const double det=dot(e1,cross(e2,e3)),scale=length(e1)*length(e2)*length(e3);
        require(std::isfinite(det)&&det>std::max(1e-24,scale*1e-12),"Tetrahedron must have positive nondegenerate volume");
        TetData g;g.volume=det/6;g.gradients[1]=cross(e2,e3)/det;g.gradients[2]=cross(e3,e1)/det;
        g.gradients[3]=cross(e1,e2)/det;g.gradients[0]=-g.gradients[1]-g.gradients[2]-g.gradients[3];
        geometry_.push_back(g);volume_+=g.volume;const double mass=g.volume*d.materials[t.material].density_kg_m3;
        mass_+=mass;for(auto id:t.nodes)nodal_masses_[id]+=mass*.25;
        for(unsigned opposite=0;opposite<4;++opposite) {
            std::array<unsigned,3> f{};unsigned at=0;for(unsigned i=0;i<4;++i)if(i!=opposite)f[at++]=t.nodes[i];
            const Vec3 a=d.reference_positions_m[f[0]],b=d.reference_positions_m[f[1]],c=d.reference_positions_m[f[2]];
            if(dot(cross(b-a,c-a),d.reference_positions_m[t.nodes[opposite]]-a)>0)std::swap(f[1],f[2]);
            auto key=f;std::sort(key.begin(),key.end());auto &entry=faces[key];
            if(entry.count==1) {
                const auto old=entry.outward;
                const auto oldNormal=cross(d.reference_positions_m[old[1]]-d.reference_positions_m[old[0]],d.reference_positions_m[old[2]]-d.reference_positions_m[old[0]]);
                const auto newNormal=cross(d.reference_positions_m[f[1]]-d.reference_positions_m[f[0]],d.reference_positions_m[f[2]]-d.reference_positions_m[f[0]]);
                require(dot(oldNormal,newNormal)<0,"Shared face has tetrahedra on the same side");
            }
            require(++entry.count<=2,"Nonmanifold tetrahedral face");entry.outward=f;
        }
    }
    for(double m:nodal_masses_)require(m>0&&std::isfinite(m),"Unused node or nonfinite patch mass");
    for(const auto &[key,face]:faces) { (void)key;if(face.count==1)boundary_.push_back(face.outward); }
}

std::vector<Vec3> SmallStrainPatch::positionsM() const {
    auto positions=definition_.reference_positions_m;
    for(std::size_t i=0;i<positions.size();++i)positions[i]+=state_.displacements_m[i];return positions;
}
PatchEvaluation SmallStrainPatch::evaluateFrom(const PatchState &base,const std::vector<Vec3> &u,double maximum_gradient_norm) const {
    require(u.size()==definition_.reference_positions_m.size(),"Patch displacement count differs from nodes");
    require(std::isfinite(maximum_gradient_norm)&&maximum_gradient_norm>0&&maximum_gradient_norm<=.25,"Invalid small-gradient limit");
    for(auto value:u)require(finite(value)&&length(value)<=1000,"Invalid patch displacement");
    PatchEvaluation out;out.internal_forces_n.resize(u.size());out.responses.reserve(geometry_.size());
    for(std::size_t e=0;e<geometry_.size();++e) {
        const auto &g=geometry_[e];const auto &t=definition_.elements[e];
        const auto [strain,gradient_norm]=strainOf(g.gradients,t,u);
        require(std::isfinite(gradient_norm)&&gradient_norm<=maximum_gradient_norm,"Patch exceeds small displacement-gradient validity limit");
        auto response=evaluateSmallStrain(definition_.materials[t.material].law,base.material_points[e],strain);
        for(unsigned i=0;i<4;++i)out.internal_forces_n[t.nodes[i]]+=g.volume*stressTimes(response.stress_pa,g.gradients[i]);
        out.stored_free_energy_j+=g.volume*response.stored_free_energy_j_m3;
        out.plastic_dissipation_j+=g.volume*response.plastic_dissipation_j_m3;
        out.backward_euler_work_excess_j+=g.volume*response.backward_euler_work_excess_j_m3;
        out.maximum_displacement_gradient_norm=std::max(out.maximum_displacement_gradient_norm,gradient_norm);
        out.responses.push_back(std::move(response));
    }
    require(std::isfinite(out.stored_free_energy_j)&&std::isfinite(out.plastic_dissipation_j)&&
        std::isfinite(out.backward_euler_work_excess_j),"Nonfinite patch energy");
    for(auto force:out.internal_forces_n)require(finite(force),"Nonfinite patch internal force");
    return out;
}
PatchEvaluation SmallStrainPatch::evaluate(const std::vector<Vec3> &u,double maximum_gradient_norm) const {
    return evaluateFrom(state_,u,maximum_gradient_norm);
}

PatchSolveResult SmallStrainPatch::solveLoad(const PatchLoad &load,const PatchSolveOptions &options) {
    PatchSolveResult result;const auto started=std::chrono::steady_clock::now();
    try {
        const auto n=state_.displacements_m.size();const auto &fixed=definition_.fixed_components;
        require(load.nodal_forces_n.size()==n&&load.prescribed_displacements_m.size()==n,"Patch load arrays differ from nodes");
        require(options.maximum_newton_iterations>0&&options.maximum_newton_iterations<=100&&options.maximum_cg_iterations>0&&
            options.maximum_cg_iterations<=8192&&options.maximum_line_search_steps>0&&options.maximum_line_search_steps<=40,
            "Invalid bounded patch iteration budget");
        require(options.maximum_element_visits>0&&options.maximum_element_visits<=100000000,"Invalid patch work budget");
        require(std::isfinite(options.relative_force_tolerance)&&options.relative_force_tolerance>0&&options.relative_force_tolerance<=.01&&
            std::isfinite(options.absolute_force_tolerance_n)&&options.absolute_force_tolerance_n>0&&options.absolute_force_tolerance_n<=1,
            "Invalid patch force tolerance");
        for(std::size_t i=0;i<n;++i) {
            require(finite(load.nodal_forces_n[i])&&length(load.nodal_forces_n[i])<=1e12,"Invalid patch nodal load");
            require(finite(load.prescribed_displacements_m[i]),"Invalid prescribed displacement");
            for(unsigned a=0;a<3;++a)require(fixed[i][a]||component(load.prescribed_displacements_m[i],a)==0,"Prescribed displacement on free component");
        }
        auto charge=[&] { const auto cost=geometry_.size();if(cost>options.maximum_element_visits-result.element_visits)
            throw std::runtime_error("Patch element-work budget exhausted; state preserved");result.element_visits+=cost; };
        auto residual=[&](const PatchEvaluation &evaluation) { auto r=evaluation.internal_forces_n;
            for(std::size_t i=0;i<n;++i)r[i]-=load.nodal_forces_n[i];zeroFixed(r,fixed);return r; };
        charge();const auto before=evaluate(state_.displacements_m,options.maximum_displacement_gradient_norm);
        auto u=state_.displacements_m;
        for(std::size_t i=0;i<n;++i)for(unsigned a=0;a<3;++a)if(fixed[i][a])setComponent(u[i],a,component(load.prescribed_displacements_m[i],a));
        charge();auto evaluation=evaluate(u,options.maximum_displacement_gradient_norm);auto r=residual(evaluation);
        // Supports absorb fixed-component loads; these cannot loosen free equilibrium.
        auto freeLoads=load.nodal_forces_n;zeroFixed(freeLoads,fixed);
        // Freeze tolerance to load/initial residual so a bad iterate cannot loosen acceptance.
        result.force_tolerance_n=options.absolute_force_tolerance_n+options.relative_force_tolerance*
            std::max(norm(freeLoads),norm(r));
        while((result.free_force_residual_n=norm(r))>result.force_tolerance_n) {
            if(result.newton_iterations>=options.maximum_newton_iterations)throw std::runtime_error("Patch Newton limit; state preserved");
            ++result.newton_iterations;
            std::vector<Vec3> diagonal(n);
            charge();for(std::size_t e=0;e<geometry_.size();++e)for(unsigned i=0;i<4;++i)for(unsigned a=0;a<3;++a) {
                const auto col=strainColumn(geometry_[e].gradients[i],a);
                const double entry=geometry_[e].volume*doubleContract(col,applySmallStrainTangent(evaluation.responses[e],col));
                auto &d=diagonal[definition_.elements[e].nodes[i]];setComponent(d,a,component(d,a)+entry);
            }
            for(std::size_t i=0;i<n;++i)for(unsigned a=0;a<3;++a) {
                const double d=component(diagonal[i],a);
                require(fixed[i][a]||(d>0&&std::isfinite(d)),"Singular patch tangent diagonal");
                if(fixed[i][a])setComponent(diagonal[i],a,1);
            }
            auto precondition=[&](const std::vector<Vec3> &v) { auto z=v;for(std::size_t i=0;i<n;++i)
                for(unsigned a=0;a<3;++a)setComponent(z[i],a,component(v[i],a)/component(diagonal[i],a));return z; };
            auto multiply=[&](const std::vector<Vec3> &v) { charge();std::vector<Vec3> answer(n);
                for(std::size_t e=0;e<geometry_.size();++e) {
                    const auto strain=strainOf(geometry_[e].gradients,definition_.elements[e],v).first;
                    const auto stress=applySmallStrainTangent(evaluation.responses[e],strain);
                    for(unsigned i=0;i<4;++i)answer[definition_.elements[e].nodes[i]]+=geometry_[e].volume*stressTimes(stress,geometry_[e].gradients[i]);
                }zeroFixed(answer,fixed);return answer; };
            std::vector<Vec3> delta(n),cgResidual=r;for(auto &v:cgResidual)v=-v;
            auto z=precondition(cgResidual),direction=z;double rz=vectorDot(cgResidual,z);
            const double linearTolerance=std::max(result.force_tolerance_n*.1,result.free_force_residual_n*1e-5);
            unsigned localIterations=0;
            while(norm(cgResidual)>linearTolerance) {
                if(localIterations++>=options.maximum_cg_iterations)throw std::runtime_error("Patch CG limit; state preserved");
                ++result.cg_iterations;const auto kd=multiply(direction);const double denominator=vectorDot(direction,kd);
                require(std::isfinite(denominator)&&denominator>0&&std::isfinite(rz)&&rz>0,"Patch tangent is singular or not positive definite");
                const double alpha=rz/denominator;
                for(std::size_t i=0;i<n;++i){delta[i]+=alpha*direction[i];cgResidual[i]-=alpha*kd[i];}
                if(norm(cgResidual)<=linearTolerance)break;
                z=precondition(cgResidual);const double next=vectorDot(cgResidual,z),beta=next/rz;
                for(std::size_t i=0;i<n;++i)direction[i]=z[i]+beta*direction[i];rz=next;
            }
            bool found=false;double alpha=1;std::string invalidTrial;
            for(unsigned line=0;line<options.maximum_line_search_steps;++line,alpha*=.5) {
                ++result.line_search_trials;auto trial=u;for(std::size_t i=0;i<n;++i)trial[i]+=alpha*delta[i];
                charge();try {
                    auto candidate=evaluate(trial,options.maximum_displacement_gradient_norm);auto next=residual(candidate);
                    const double nextNorm=norm(next);
                    if(std::isfinite(nextNorm)&&(nextNorm<result.free_force_residual_n*(1-1e-4*alpha)||nextNorm<=result.force_tolerance_n)) {
                        u=std::move(trial);evaluation=std::move(candidate);r=std::move(next);found=true;break;
                    }
                } catch(const std::invalid_argument &error) { invalidTrial=error.what(); }
            }
            if(!found)throw std::runtime_error("Patch line search failed; state preserved"+(invalidTrial.empty()?std::string{}:"; "+invalidTrial));
        }
        result.reactions_n.resize(n);
        for(std::size_t i=0;i<n;++i) {
            const Vec3 delta=u[i]-state_.displacements_m[i];Vec3 previousTotal=state_.last_nodal_forces_n[i],nextTotal=load.nodal_forces_n[i];
            for(unsigned a=0;a<3;++a)if(fixed[i][a]) {
                setComponent(result.reactions_n[i],a,component(evaluation.internal_forces_n[i]-load.nodal_forces_n[i],a));
                setComponent(previousTotal,a,component(before.internal_forces_n[i],a));
                setComponent(nextTotal,a,component(evaluation.internal_forces_n[i],a));
            }
            result.trapezoidal_external_work_increment_j+=.5*dot(previousTotal+nextTotal,delta);
            result.backward_euler_external_work_increment_j+=dot(nextTotal,delta);
            result.applied_force_n+=load.nodal_forces_n[i];result.support_reaction_n+=result.reactions_n[i];
            result.reference_moment_residual_n_m+=cross(definition_.reference_positions_m[i],nextTotal);
        }
        result.stored_free_energy_j=evaluation.stored_free_energy_j;result.plastic_dissipation_j=evaluation.plastic_dissipation_j;
        result.stored_free_energy_increment_j=evaluation.stored_free_energy_j-before.stored_free_energy_j;
        result.plastic_dissipation_increment_j=evaluation.plastic_dissipation_j-before.plastic_dissipation_j;
        result.constitutive_backward_euler_excess_j=evaluation.backward_euler_work_excess_j;
        result.trapezoidal_work_residual_j=result.trapezoidal_external_work_increment_j-result.stored_free_energy_increment_j-result.plastic_dissipation_increment_j;
        result.backward_euler_balance_residual_j=result.backward_euler_external_work_increment_j-result.stored_free_energy_increment_j-
            result.plastic_dissipation_increment_j-result.constitutive_backward_euler_excess_j;
        result.maximum_displacement_gradient_norm=evaluation.maximum_displacement_gradient_norm;
        PatchState candidate=state_;candidate.displacements_m=std::move(u);candidate.last_nodal_forces_n=load.nodal_forces_n;
        for(std::size_t e=0;e<evaluation.responses.size();++e)candidate.material_points[e]=evaluation.responses[e].state;
        candidate.accumulated_trapezoidal_external_work_j+=result.trapezoidal_external_work_increment_j;
        candidate.accumulated_backward_euler_external_work_j+=result.backward_euler_external_work_increment_j;
        require(std::isfinite(candidate.accumulated_trapezoidal_external_work_j)&&std::isfinite(candidate.accumulated_backward_euler_external_work_j),"Patch work ledger overflow");
        require(candidate.revision<std::numeric_limits<std::uint64_t>::max(),"Patch revision exhausted");
        ++candidate.revision;state_=std::move(candidate);result.accepted=true;
    } catch(const std::exception &error) { result.error=error.what(); }
    result.wall_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();return result;
}

void SmallStrainPatch::restoreState(const PatchState &candidate,double forceTolerance,double maxGradient) {
    require(candidate.displacements_m.size()==state_.displacements_m.size()&&candidate.last_nodal_forces_n.size()==state_.last_nodal_forces_n.size()&&
        candidate.material_points.size()==state_.material_points.size(),"Patch restored state layout mismatch");
    require(std::isfinite(forceTolerance)&&forceTolerance>0&&forceTolerance<=1,"Invalid restored equilibrium tolerance");
    require(std::isfinite(candidate.accumulated_trapezoidal_external_work_j)&&std::isfinite(candidate.accumulated_backward_euler_external_work_j),"Nonfinite restored work ledger");
    for(auto f:candidate.last_nodal_forces_n)require(finite(f)&&length(f)<=1e12,"Invalid restored load");
    for(std::size_t e=0;e<geometry_.size();++e) {
        const auto strain=strainOf(geometry_[e].gradients,definition_.elements[e],candidate.displacements_m).first;
        require(frobeniusNorm(difference(strain,candidate.material_points[e].total_strain))<=1e-12,"Restored geometry and material strain disagree");
    }
    const auto evaluation=evaluateFrom(candidate,candidate.displacements_m,maxGradient);auto r=evaluation.internal_forces_n;
    for(std::size_t i=0;i<r.size();++i)r[i]-=candidate.last_nodal_forces_n[i];zeroFixed(r,definition_.fixed_components);
    require(norm(r)<=forceTolerance,"Restored patch is not in declared free equilibrium");
    state_=candidate;
}

PatchDefinition makeTetrahedralBrick(Vec3 size,std::array<unsigned,3> cells,PatchMaterial material) {
    require(finite(size)&&size.x>=1e-4&&size.y>=1e-4&&size.z>=1e-4&&length(size)<=10,"Invalid patch brick dimensions");
    std::uint64_t count=1,nodeCount=1;for(auto n:cells){require(n>0&&n<=64,"Invalid patch brick resolution");count*=n;nodeCount*=n+1;}
    require(count*6<=16384&&nodeCount<=4096,"Patch brick exceeds mesh budget");
    PatchDefinition d;d.materials.push_back(material);
    auto id=[&](unsigned x,unsigned y,unsigned z) {return (z*(cells[1]+1)+y)*(cells[0]+1)+x;};
    for(unsigned z=0;z<=cells[2];++z)for(unsigned y=0;y<=cells[1];++y)for(unsigned x=0;x<=cells[0];++x)
        d.reference_positions_m.push_back({size.x*x/cells[0]-size.x/2,size.y*y/cells[1],size.z*z/cells[2]-size.z/2});
    for(unsigned z=0;z<cells[2];++z)for(unsigned y=0;y<cells[1];++y)for(unsigned x=0;x<cells[0];++x) {
        const unsigned a=id(x,y,z),b=id(x+1,y,z),c=id(x+1,y+1,z),dd=id(x,y+1,z),
            e=id(x,y,z+1),f=id(x+1,y,z+1),g=id(x+1,y+1,z+1),h=id(x,y+1,z+1);
        for(auto nodes:std::array<std::array<unsigned,4>,6>{{{a,b,c,g},{a,c,dd,g},{a,dd,h,g},{a,h,e,g},{a,e,f,g},{a,f,b,g}}}) {
            const auto p=d.reference_positions_m[nodes[0]];
            if(dot(d.reference_positions_m[nodes[1]]-p,cross(d.reference_positions_m[nodes[2]]-p,d.reference_positions_m[nodes[3]]-p))<0)
                std::swap(nodes[1],nodes[2]);
            d.elements.push_back({nodes,0});
        }
    }
    d.fixed_components.resize(d.reference_positions_m.size());return d;
}
} // namespace banjo
