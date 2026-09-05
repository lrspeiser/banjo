#include "fracture/FracturePreview.hpp"
#include <cmath>
#include <functional>
#include <stdexcept>
namespace banjo {
FracturePreview buildFracturePreview(double speed){
    if(!std::isfinite(speed)||speed<4||speed>240)throw std::invalid_argument("preview impact speed must be within 4..240 m/s");
    FracturePreview runs;unsigned index=0;
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        auto material=makeReferenceMaterial(preset);LatticeAsset asset;ActiveMatter matter;CoupledSphereState sphere;
        const double h=1e-5,area=h*h;asset.recipe.voxel_size_m=h;asset.nodes.resize(8);matter.asset=&asset;
        for(unsigned i=0;i<8;++i){matter.nodes.push_back({{i*h,0,0},{},{},material.density_kg_m3*h*h*h,{}});
            if(i){asset.bonds.push_back({.node_a=i-1,.node_b=i,.rest_length_m=h,.compliance=h/(material.young_modulus_pa*area)});matter.bonds.emplace_back();}}
        sphere.radius_m=2e-6;sphere.mass_kg=2.5e-12;sphere.inertia_kg_m2=.4*sphere.mass_kg*sphere.radius_m*sphere.radius_m;
        sphere.motion.center_of_mass_world_m={-sphere.radius_m-1e-7,0,0};sphere.motion.linear_velocity_m_s={speed,0,0};
        RuptureCascadeSettings s;s.maximum_step_s=2e-11;s.minimum_step_s=1e-20;s.maximum_event_overshoot_j=8e-15;s.capture_interval_s=1e-10;
        s.contact.normal={2.8e6,0};s.contact.maximum_compression_m=1e-6;s.contact.solver.velocity_tolerance_m_s=1e-10;
        s.contact.maximum_residual_work_j=1e-20;s.contact.maximum_residual_linear_impulse_kg_m_s=1e-25;s.contact.maximum_residual_angular_impulse_kg_m2_s=1e-30;
        FracturePreviewRun run;run.material=preset;
        if(material.model==MaterialModel::BrittleBond){std::vector<double> areas(7,area);auto laws=compileMaterialRuptureInterfaces(material,asset,areas);
            auto result=tryRuptureCascade(matter,sphere,1e-7,laws,s);if(!result.accepted)throw std::runtime_error(result.failure);
            run.frames=std::move(result.frames);run.events=std::move(result.events);
        }else{
            const auto capture=[&](double time){RuptureCascadeFrame f;f.time_s=time;f.impactor_position=sphere.motion.center_of_mass_world_m;for(auto &n:matter.nodes)f.positions.push_back(n.position_world_m);for(auto &b:matter.bonds)f.live_bonds.push_back(b.alive);run.frames.push_back(std::move(f));};
            unsigned evaluations=0;
            std::function<void(double,unsigned)> advance=[&](double dt,unsigned depth){
                if(++evaluations>65536)throw std::runtime_error("elastic preview evaluation budget");
                auto r=tryCompliantStep(matter,dt,s.contact,{},&sphere);if(r.balance.converged)return;
                if(depth>=30||dt/2<1e-20)throw std::runtime_error("elastic comparison refinement floor");
                advance(dt/2,depth+1);advance(dt/2,depth+1);
            };
            capture(0);for(unsigned step=1;step<=5000;++step){advance(2e-11,0);if(step%5==0)capture(step*2e-11);}
        }
        runs[index++]=std::move(run);
    }
    return runs;
}
}
