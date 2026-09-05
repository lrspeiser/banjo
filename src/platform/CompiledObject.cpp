#include "platform/CompiledObject.hpp"
#include <algorithm>
#include <numeric>
#include <numbers>
#include <stdexcept>

namespace banjo {
namespace {
double component(Vec3 v,unsigned i){return i==0?v.x:i==1?v.y:v.z;}
std::uint64_t mix(std::uint64_t x){x+=0x9e3779b97f4a7c15ULL;x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;x=(x^(x>>27))*0x94d049bb133111ebULL;return x^(x>>31);}
std::vector<double> factor(const CompiledObject &o,const std::vector<unsigned char> &live){
    const auto n=o.samples.size()*3;std::vector<double> a(n*n);
    const double t2=o.response_duration_s*o.response_duration_s;
    for(unsigned i=0;i<o.samples.size();++i)for(unsigned d=0;d<3;++d)a[(i*3+d)*n+i*3+d]=o.samples[i].mass_kg;
    for(unsigned e=0;e<o.links.size();++e)if(live[e]){
        const auto &b=o.links[e];
        for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j){
            const double k=t2*b.stiffness_n_m*component(b.direction,i)*component(b.direction,j);
            a[(b.a*3+i)*n+b.a*3+j]+=k;a[(b.b*3+i)*n+b.b*3+j]+=k;
            a[(b.a*3+i)*n+b.b*3+j]-=k;a[(b.b*3+i)*n+b.a*3+j]-=k;
        }
    }
    for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<=i;++j){double v=a[i*n+j];for(std::size_t k=0;k<j;++k)v-=a[i*n+k]*a[j*n+k];
        if(i==j){if(!(v>0)||!std::isfinite(v))throw std::runtime_error("compiled response is not positive definite");a[i*n+j]=std::sqrt(v);}
        else a[i*n+j]=v/a[j*n+j];
    }
    return a;
}
void advanceResponse(const CompiledObject &o,const std::vector<unsigned char> &live,const std::vector<double> &l,std::vector<Vec3> &u,std::vector<Vec3> &velocity){
    const auto n=o.samples.size()*3;std::vector<double> v(n);
    for(unsigned i=0;i<u.size();++i)for(unsigned d=0;d<3;++d)v[i*3+d]=component(velocity[i],d)*o.samples[i].mass_kg;
    for(unsigned i=0;i<live.size();++i)if(live[i]){const auto &b=o.links[i];const Vec3 j=b.direction*(o.response_duration_s*b.stiffness_n_m*dot(u[b.b]-u[b.a],b.direction));
        for(unsigned d=0;d<3;++d){v[b.a*3+d]+=component(j,d);v[b.b*3+d]-=component(j,d);}}
    for(std::size_t i=0;i<n;++i){for(std::size_t j=0;j<i;++j)v[i]-=l[i*n+j]*v[j];v[i]/=l[i*n+i];}
    for(std::size_t i=n;i-->0;){for(std::size_t j=i+1;j<n;++j)v[i]-=l[j*n+i]*v[j];v[i]/=l[i*n+i];}
    for(unsigned i=0;i<u.size();++i){velocity[i]={v[3*i],v[3*i+1],v[3*i+2]};u[i]+=velocity[i]*o.response_duration_s;}
}
}
CompiledObject compileObject(const RigidPrimitive &shape,const MaterialDefinition &material,std::uint64_t seed){
    if(!std::isfinite(material.density_kg_m3)||material.density_kg_m3<=0||!std::isfinite(material.young_modulus_pa)||material.young_modulus_pa<=0||
       !std::isfinite(material.strength_variation)||material.strength_variation<0||material.strength_variation>.5||
       !std::isfinite(material.tensile_strength_pa)||material.tensile_strength_pa<=0||!std::isfinite(material.fracture_energy_j_m2)||material.fracture_energy_j_m2<=0)
        throw std::invalid_argument("unsupported compiled material properties");
    if(shape.kind==PrimitiveKind::Sphere&&(!std::isfinite(shape.radius_m)||shape.radius_m<.01||shape.radius_m>.5))throw std::invalid_argument("compiled sphere radius outside bounds");
    if(shape.kind==PrimitiveKind::Box&&(std::min({shape.dimensions_m.x,shape.dimensions_m.y,shape.dimensions_m.z})<.02||
       std::max({shape.dimensions_m.x,shape.dimensions_m.y,shape.dimensions_m.z})>1||!std::isfinite(lengthSquared(shape.dimensions_m))))throw std::invalid_argument("compiled box dimensions outside bounds");
    CompiledObject o;o.material=material;o.seed=seed;
    const bool sphere=shape.kind==PrimitiveKind::Sphere;
    const double h=sphere?shape.radius_m/(std::sqrt(2.)+.45):0;
    const Vec3 spacing=sphere?Vec3{h,h,h}:shape.dimensions_m/3;
    const double mass=shape.volume()*material.density_kg_m3/(sphere?19:27);
    for(int x=-1;x<=1;++x)for(int y=-1;y<=1;++y)for(int z=-1;z<=1;++z){
        if(sphere&&x*x+y*y+z*z>2)continue;
        CompiledSample s;s.center_m={x*spacing.x,y*spacing.y,z*spacing.z};s.mass_kg=mass;
        if(sphere){s.collision.radius_m=.45*h;for(unsigned i=0;i<3;++i)s.intrinsic_inertia.m[i][i]=mass*(.4*shape.radius_m*shape.radius_m-20*h*h/19);}
        else {s.collision.kind=PrimitiveKind::Box;s.collision.dimensions_m=spacing;s.intrinsic_inertia=s.collision.inertia(mass);}
        o.samples.push_back(s);
    }
    const double area=std::pow(spacing.x*spacing.y*spacing.z,2./3)/6;
    for(unsigned a=0;a<o.samples.size();++a)for(unsigned b=a+1;b<o.samples.size();++b){
        const Vec3 d=o.samples[b].center_m-o.samples[a].center_m;
        const double grid=std::pow(d.x/spacing.x,2)+std::pow(d.y/spacing.y,2)+std::pow(d.z/spacing.z,2);
        if(grid>2.01)continue;
        // A smooth seeded field sampled at the bond midpoint gives persistent,
        // spatially correlated strength variation. No per-collision reroll.
        const Vec3 p=(o.samples[a].center_m+o.samples[b].center_m)*.5;
        double field=0;for(unsigned axis=0;axis<3;++axis){const double phase=double(mix(seed+axis)>>11)*0x1.0p-53*2*std::numbers::pi;field+=std::sin(component(p,axis)/component(spacing,axis)+phase)/3;}
        o.links.push_back({a,b,normalized(d),length(d),area,material.young_modulus_pa*area/length(d),material.tensile_strength_pa*(1+material.strength_variation*field),material.fracture_energy_j_m2*area});
    }
    // Declared local predictor step: one eighth of a cell spring half-period.
    // A pulse advances 64 such steps, separate from the gameplay timestep.
    o.response_duration_s=std::numbers::pi/8*std::sqrt(mass/(material.young_modulus_pa*std::cbrt(spacing.x*spacing.y*spacing.z)));
    o.initial_factor=factor(o,std::vector<unsigned char>(o.links.size(),1));return o;
}
CompiledDamage::CompiledDamage(CompiledObject object):object_(std::move(object)),live_(object_.links.size(),1),factor_(object_.initial_factor){}
std::vector<unsigned> CompiledDamage::components() const{
    std::vector<unsigned> roots(object_.samples.size());std::iota(roots.begin(),roots.end(),0);
    auto root=[&](unsigned a){while(roots[a]!=a){roots[a]=roots[roots[a]];a=roots[a];}return a;};
    for(unsigned i=0;i<live_.size();++i)if(live_[i]){auto &b=object_.links[i];roots[root(b.b)]=root(b.a);}
    for(auto &r:roots)r=root(r);return roots;
}
LocalImpactResult CompiledDamage::impact(unsigned sample,Vec3 impulse,double allowance,unsigned maximum){
    if(sample>=object_.samples.size()||!std::isfinite(lengthSquared(impulse))||!std::isfinite(allowance)||allowance<0||maximum>256)throw std::invalid_argument("invalid bounded local impact");
    LocalImpactResult result;if(object_.material.model!=MaterialModel::BrittleBond||allowance==0||lengthSquared(impulse)==0)return result;
    std::vector<Vec3> u(object_.samples.size()),velocity(object_.samples.size());velocity[sample]=impulse/object_.samples[sample].mass_kg;
    for(unsigned iteration=0;iteration<64;++iteration){
        if(dirty_){factor_=factor(object_,live_);dirty_=false;++result.factor_builds;}
        advanceResponse(object_,live_,factor_,u,velocity);++result.solves;
        unsigned best=unsigned(live_.size());double score=0,bestStress=0,bestEnergy=0;
        for(unsigned i=0;i<live_.size();++i)if(live_[i]){auto &b=object_.links[i];const double extension=dot(u[b.b]-u[b.a],b.direction),stress=b.stiffness_n_m*extension/b.area_m2,energy=.5*b.stiffness_n_m*extension*extension;
            if(extension>0&&stress>=b.strength_pa&&energy>=b.work_j){if(b.work_j>allowance-result.work_j){result.budget_limited=true;continue;}
                if(energy/b.work_j>score){score=energy/b.work_j;best=i;bestStress=stress;bestEnergy=energy;}}
        }
        if(best==live_.size())continue;
        if(result.failures.size()==maximum){result.budget_limited=true;break;}
        live_[best]=0;dirty_=true;const double work=object_.links[best].work_j;result.work_j+=work;
        result.failures.push_back({best,result.solves,bestStress,bestEnergy,work});
        // The next local pulse step uses this changed structure. Compression
        // and later tensile unloading follow the evolving predictor state.
    }
    return result;
}
}
