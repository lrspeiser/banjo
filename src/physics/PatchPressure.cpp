#include "physics/PatchPressure.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace banjo {
namespace {
void require(bool condition,const char *message) {
    if(!condition)throw std::invalid_argument(message);
}
bool finite(Vec3 p) { return std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z); }
struct Vertex { double u{},v{}; std::array<double,3> shape{}; };
Vertex interpolate(const Vertex &a,const Vertex &b,double t) {
    Vertex p{a.u+(b.u-a.u)*t,a.v+(b.v-a.v)*t,{}};
    for(unsigned i=0;i<3;++i)p.shape[i]=a.shape[i]+(b.shape[i]-a.shape[i])*t;
    return p;
}
std::vector<Vertex> clip(const std::vector<Vertex> &input,unsigned axis,double bound,double side) {
    std::vector<Vertex> out;
    if(input.empty())return out;
    auto distance=[&](const Vertex &p) {return side*(axis==0?p.u:p.v)-bound;};
    auto previous=input.back();double before=distance(previous);
    for(const auto &current:input) {
        const double after=distance(current);
        // Boundary vertices are retained once; strict crossings avoid duplicate
        // polygon vertices when a mesh edge already lies on the footprint.
        if((before<0&&after>0)||(before>0&&after<0))out.push_back(interpolate(previous,current,before/(before-after)));
        if(after<=0)out.push_back(current);
        previous=current;before=after;
    }
    require(out.size()<=8,"Pressure clipping vertex budget exceeded");
    return out;
}
// Six-point Gauss-Legendre mapped to [0,1]. The square-to-triangle map has
// barycentrics (1-u,u*(1-v),u*v), Jacobian u. For the degree-8 pressure times
// degree-1 face shape functions the mapped degree is at most 10 in u and 9
// in v; these degree-11 rules integrate it exactly up to floating point error.
constexpr std::array<double,6> nodes{.033765242898423975,.16939530676686776,
    .38069040695840156,.6193095930415985,.8306046932331322,.966234757101576};
constexpr std::array<double,6> weights{.08566224618958517,.1803807865240693,
    .23395696728634552,.23395696728634552,.1803807865240693,.08566224618958517};
}

PatchPressureLoad makePatchPressureLoad(const SmallStrainPatch &patch,const PatchPressure &p) {
    require(finite(p.center_m)&&length(p.center_m)<=1000&&finite(p.axis_u)&&finite(p.axis_v),"Invalid pressure frame");
    require(std::abs(length(p.axis_u)-1)<=1e-12&&std::abs(length(p.axis_v)-1)<=1e-12&&
        std::abs(dot(p.axis_u,p.axis_v))<=1e-12,"Pressure axes must be orthonormal");
    require(std::isfinite(p.half_width_m)&&p.half_width_m>=1e-8&&p.half_width_m<=10&&
        std::isfinite(p.half_height_m)&&p.half_height_m>=1e-8&&p.half_height_m<=10,"Invalid pressure half extents");
    require(std::isfinite(p.peak_pressure_pa)&&p.peak_pressure_pa>=0&&p.peak_pressure_pa<=1e12,"Invalid peak pressure");
    require(p.profile==PatchPressureProfile::Uniform||p.profile==PatchPressureProfile::Smooth,"Unknown pressure profile");
    const auto &definition=patch.definition();const auto &positions=definition.reference_positions_m;
    const Vec3 normal=cross(p.axis_u,p.axis_v);
    PatchPressureLoad out;out.load.nodal_forces_n.resize(positions.size());out.load.prescribed_displacements_m.resize(positions.size());
    for(std::size_t i=0;i<positions.size();++i) {
        const auto fixed=definition.fixed_components[i];const auto u=patch.state().displacements_m[i];
        out.load.prescribed_displacements_m[i]={fixed[0]?u.x:0,fixed[1]?u.y:0,fixed[2]?u.z:0};
    }
    for(const auto &face:patch.boundaryTriangles()) {
        std::vector<Vertex> polygon;bool coplanar=true;
        for(unsigned i=0;i<3;++i) {
            const Vec3 relative=positions[face[i]]-p.center_m;
            if(std::abs(dot(relative,normal))>1e-10)coplanar=false;
            Vertex vertex{dot(relative,p.axis_u),dot(relative,p.axis_v),{}};vertex.shape[i]=1;
            polygon.push_back(vertex);
        }
        if(!coplanar||dot(cross(positions[face[1]]-positions[face[0]],positions[face[2]]-positions[face[0]]),normal)<=0)continue;
        polygon=clip(polygon,0,p.half_width_m,1);polygon=clip(polygon,0,p.half_width_m,-1);
        polygon=clip(polygon,1,p.half_height_m,1);polygon=clip(polygon,1,p.half_height_m,-1);
        for(std::size_t fan=1;fan+1<polygon.size();++fan) {
            const auto a=polygon[0],b=polygon[fan],c=polygon[fan+1];
            const double twiceArea=std::abs((b.u-a.u)*(c.v-a.v)-(b.v-a.v)*(c.u-a.u));
            if(twiceArea==0)continue;
            out.loaded_area_m2+=twiceArea*.5;
            std::array<double,3> integrals{};
            if(p.profile==PatchPressureProfile::Uniform) {
                ++out.quadrature_points;out.weighted_area_m2+=twiceArea*.5;
                for(unsigned i=0;i<3;++i)integrals[i]=twiceArea*(a.shape[i]+b.shape[i]+c.shape[i])/6;
            } else {
                for(unsigned i=0;i<6;++i)for(unsigned j=0;j<6;++j) {
                    const std::array<double,3> bary{1-nodes[i],nodes[i]*(1-nodes[j]),nodes[i]*nodes[j]};
                    const double u=(a.u*bary[0]+b.u*bary[1]+c.u*bary[2])/p.half_width_m;
                    const double v=(a.v*bary[0]+b.v*bary[1]+c.v*bary[2])/p.half_height_m;
                    const double fu=std::max(0.,1-u*u),fv=std::max(0.,1-v*v);
                    const double weight=twiceArea*nodes[i]*weights[i]*weights[j]*fu*fu*fv*fv;
                    ++out.quadrature_points;out.weighted_area_m2+=weight;
                    for(unsigned k=0;k<3;++k)integrals[k]+=weight*(a.shape[k]*bary[0]+b.shape[k]*bary[1]+c.shape[k]*bary[2]);
                }
            }
            for(unsigned i=0;i<3;++i)out.load.nodal_forces_n[face[i]]-=normal*(p.peak_pressure_pa*integrals[i]);
        }
    }
    require(out.loaded_area_m2>0,"Pressure footprint has no coplanar outward material surface");
    for(std::size_t i=0;i<positions.size();++i) {
        const auto f=out.load.nodal_forces_n[i];require(finite(f)&&length(f)<=1e12,"Pressure nodal force exceeds load range");
        out.resultant_force_n+=f;out.reference_moment_n_m+=cross(positions[i],f);
    }
    require(std::isfinite(out.loaded_area_m2)&&std::isfinite(out.weighted_area_m2)&&finite(out.resultant_force_n)&&
        finite(out.reference_moment_n_m),"Nonfinite pressure integral");
    return out;
}
} // namespace banjo
