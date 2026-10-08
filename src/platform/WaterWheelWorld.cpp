#include "platform/WaterWheelWorld.hpp"
#include "rigid/JoltWorld.hpp"
#include <nlohmann/json.hpp>
#include <numbers>
#include <algorithm>
#include <stdexcept>

namespace banjo {
namespace {
using Json=nlohmann::json;
constexpr double rho0=1000.,spacing=.04,h=.10,sound=20.,viscosity=.001;
constexpr double particleMass=rho0*spacing*spacing*spacing;
Json vec(Vec3 v){return {v.x,v.y,v.z};}
void require(bool ok,const char *why){if(!ok)throw std::invalid_argument(why);}
// Wendland C2, support h, normalized in 3D. Pressure is central and paired.
double kernel(double r){const double q=r/h;return q>=1?0:21/(2*std::numbers::pi*h*h*h)*std::pow(1-q,4)*(1+4*q);}
double minusGradient(double r){const double q=r/h;return q>=1?0:210/(std::numbers::pi*h*h*h*h)*q*std::pow(1-q,3);}
double pressure(double rho){return sound*sound*std::max(0.,rho-rho0);}
double specificEnergy(double rho){return rho<=rho0?0:sound*sound*(std::log(rho/rho0)+rho0/rho-1);}
Quat multiply(Quat a,Quat b){return {a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};}
}
struct WaterWheelWorld::Impl {
    JoltWorld rigid{0,{16384,8192}};
    MaterialPreset material{MaterialPreset::Oak};
    std::vector<RigidCompoundPart> parts;
    std::vector<MatterBodyId> drops;
    unsigned hinge{},ticks{};
    unsigned waterWheelContacts{};
    Json contactEvents=Json::array();
    double dt{},time{},wheelMass{},angle{},lastAngle{},initialEnergy{},initialWaterEnergy{},viscousWork{},internalEnergy{};
    double pairLinearResidual{},pairAngularResidual{},maxDensity{},maxMach{},maxCourant{};
    Vec3 gravity{0,-9.81,0},initialMomentum{},initialAngularMomentum{},gravityImpulse{},gravityAngularImpulse{};
    std::vector<RigidSnapshot> states;
    std::vector<double> density;
    void refresh(){states.clear();for(auto id:drops)states.push_back(rigid.snapshot(id));
        density.assign(drops.size(),particleMass*kernel(0));
        for(unsigned i=0;i<states.size();++i)for(unsigned j=i+1;j<states.size();++j){const double d=length(states[i].center_of_mass_world_m-states[j].center_of_mass_world_m);const double v=particleMass*kernel(d);density[i]+=v;density[j]+=v;}
        internalEnergy=0;for(double rho:density){internalEnergy+=particleMass*specificEnergy(rho);maxDensity=std::max(maxDensity,rho);}
    }
};
WaterWheelWorld::WaterWheelWorld():impl_(std::make_unique<Impl>()){}
WaterWheelWorld::~WaterWheelWorld()=default;
std::unique_ptr<WaterWheelWorld> WaterWheelWorld::load(const std::string &source){
    const auto r=Json::parse(source);require(r.is_object(),"Expected wheel declaration");
    for(auto it=r.begin();it!=r.end();++it)require(it.key()=="backend"||it.key()=="package_version"||it.key()=="physics_abi"||it.key()=="units"||it.key()=="fixed_dt_s"||it.key()=="max_steps_per_call"||it.key()=="paddle"||it.key()=="water"||it.key()=="offset_m","Unknown wheel field");
    require(r.at("package_version")==1&&r.at("physics_abi")=="banjo-fluid-wheel-1"&&r.at("units")=="SI"&&r.at("backend")=="fluid-wheel-v1","Unsupported wheel package");
    require(r.at("water").is_boolean(),"water must be boolean");
    auto result=std::unique_ptr<WaterWheelWorld>(new WaterWheelWorld);auto &w=*result->impl_;
    w.dt=r.at("fixed_dt_s").get<double>();require(w.dt==1./240||w.dt==1./480,"Wheel host step outside declared range");
    require(r.at("max_steps_per_call")==4,"Wheel batch must be bounded");
    const std::string material=r.at("paddle").get<std::string>();
    require(material=="oak"||material=="glass"||material=="iron","Unsupported comparison paddle");
    w.material=material=="oak"?MaterialPreset::Oak:material=="glass"?MaterialPreset::Glass:MaterialPreset::Iron;
    const double offset=r.at("offset_m").get<double>();require(std::isfinite(offset)&&std::abs(offset)<=1.,"Jet offset outside bounds");
    auto solid=makeReferenceMaterial(w.material);solid.model=MaterialModel::RigidOnly;
    w.rigid.setGravity(w.gravity);w.rigid.setContactSolverIterations(48,8);
    w.rigid.setImpactObservationsEnabled(true);
    RigidSurfaceDescription floor;floor.material=solid;floor.half_length_tangent_m=3;floor.half_length_bitangent_m=3;w.rigid.addSupportSurface(floor);
    // Symmetric wheel: eight spokes and eight paddles, represented by its real boxes.
    Mat3 inertia;
    auto part=[&](Vec3 d,Vec3 p,double rotation,bool hub=false){RigidPrimitive shape;shape.kind=hub?PrimitiveKind::Sphere:PrimitiveKind::Box;shape.radius_m=.04;shape.dimensions_m=d;const Quat q{std::cos(rotation/2),0,0,std::sin(rotation/2)};
        const double mass=solid.density_kg_m3*shape.volume();const auto local=shape.inertia(mass);
        const Vec3 axes[]={q.rotate({1,0,0}),q.rotate({0,1,0}),q.rotate({0,0,1})};
        for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j){const double a[]={p.x,p.y,p.z};
            for(unsigned k=0;k<3;++k){const double u[]={axes[k].x,axes[k].y,axes[k].z};inertia.m[i][j]+=local.m[k][k]*u[i]*u[j];}
            inertia.m[i][j]+=mass*((i==j?lengthSquared(p):0)-a[i]*a[j]);}
        w.wheelMass+=mass;w.parts.push_back({shape,p,q,solid,0});};
    part({.08,.08,.08},{},0,true);
    for(unsigned k=0;k<8;++k){const double a=k*std::numbers::pi/4;part({.28,.025,.035},{.18*std::cos(a),.18*std::sin(a),0},a);
        part({.16,.035,.18},{.40*std::cos(a),.40*std::sin(a),0},a);}
    w.rigid.addCompound({1,w.parts,solid,{{0,.65,0},{},{},{}},w.wheelMass,inertia});
    auto iron=makeReferenceMaterial(MaterialPreset::Iron);
    w.rigid.addBox({2,{.10,1.3,.10},iron,{{0,.65,-.25},{},{},{}},true});
    w.hinge=w.rigid.addHinge({2,1,{0,.65,0},{0,0,1}});
    if(r["water"].get<bool>()){
        MaterialDefinition fluid;fluid.name="water parcel";fluid.model=MaterialModel::RigidOnly;fluid.density_kg_m3=rho0;
        // Contact descriptor admission only; compressibility is the SPH EOS above.
        fluid.young_modulus_pa=3*rho0*sound*sound*(1-2*.25);fluid.poisson_ratio=.25;
        fluid.friction=fluid.dynamic_friction=fluid.static_friction=0;fluid.restitution=0;fluid.derive_restitution_from_damping=false;
        for(unsigned x=0;x<4;++x)for(unsigned y=0;y<5;++y)for(unsigned z=0;z<4;++z){RigidBallDescription drop;
            drop.body_id=100+unsigned(w.drops.size());drop.radius_m=spacing*.45;drop.material=fluid;drop.mass_override_kg=particleMass;
            drop.position_world_m={offset+(x-1.5)*spacing,1.65+y*spacing,(z-1.5)*spacing};w.rigid.addBall(drop);w.drops.push_back(drop.body_id);}
        // SPH owns all fluid-fluid pressure/viscosity; Jolt owns fluid-solid contact only.
        for(unsigned i=0;i<w.drops.size();++i)for(unsigned j=i+1;j<w.drops.size();++j)w.rigid.setPairContactOwner(w.drops[i],w.drops[j],PairContactOwner::External);
    }
    w.refresh();const auto totals=w.rigid.mechanicalTotals(w.gravity);w.initialEnergy=totals.mechanicalEnergy()+w.internalEnergy;
    w.initialMomentum=totals.linear_momentum_kg_m_s;w.initialAngularMomentum=totals.angular_momentum_kg_m2_s;
    for(auto id:w.drops)w.initialWaterEnergy+=measureRigidMechanics(w.rigid.mechanicalState(id),w.gravity).mechanicalEnergy();
    return result;
}
void WaterWheelWorld::step(double dt){
    auto &w=*impl_;require(dt==w.dt,"Wheel timestep must match declaration");
    const unsigned count=unsigned(std::ceil(dt/(.25*h/sound)));const double sub=dt/count;
    for(unsigned tick=0;tick<count;++tick){w.refresh();std::vector<Vec3> forces(w.drops.size());Vec3 sum{},torque{};
        for(unsigned i=0;i<w.drops.size();++i)for(unsigned j=i+1;j<w.drops.size();++j){const Vec3 r=w.states[i].center_of_mass_world_m-w.states[j].center_of_mass_world_m;const double d=length(r);if(d<1e-10||d>=h)continue;
            const Vec3 axis=r/d,dv=w.states[i].linear_velocity_m_s-w.states[j].linear_velocity_m_s;
            const double gradient=minusGradient(d),den=w.density[i]*w.density[j];
            const double p=particleMass*particleMass*(pressure(w.density[i])/(w.density[i]*w.density[i])+pressure(w.density[j])/(w.density[j]*w.density[j]))*gradient;
            // Angular-conserving central viscosity; nonpositive pair power.
            const double visc=-10*viscosity*particleMass*particleMass/den*dot(dv,r)/(d*d+.01*h*h)*gradient;
            const Vec3 f=axis*(p+visc);forces[i]+=f;forces[j]-=f;w.viscousWork-=visc*dot(dv,axis)*sub;}
        for(unsigned i=0;i<w.drops.size();++i){sum+=forces[i];torque+=cross(w.states[i].center_of_mass_world_m,forces[i]);w.rigid.pushBody(w.drops[i],forces[i]);
            const double speed=length(w.states[i].linear_velocity_m_s);w.maxMach=std::max(w.maxMach,speed/sound);w.maxCourant=std::max(w.maxCourant,sub*(sound+speed)/h);}
        w.pairLinearResidual=std::max(w.pairLinearResidual,length(sum));w.pairAngularResidual=std::max(w.pairAngularResidual,length(torque));
        const auto before=w.rigid.mechanicalTotals();w.gravityImpulse+=w.gravity*(before.mass_kg*sub);
        w.gravityAngularImpulse+=cross(before.mass_first_moment_kg_m,w.gravity)*sub;
        w.rigid.step(sub);const auto state=w.rigid.snapshot(1);const double angle=2*std::atan2(state.orientation_world.z,state.orientation_world.w);
        for(const auto &event:w.rigid.drainImpacts())if((event.body_a==1&&event.body_b>=100)||(event.body_b==1&&event.body_a>=100)){
            ++w.waterWheelContacts;if(w.contactEvents.size()<128)w.contactEvents.push_back({{"time_s",w.time+(tick+1)*sub},{"body_a",event.body_a},{"body_b",event.body_b},{"closing_speed_m_s",event.closing_speed_m_s},{"point_m",vec(event.contact_point_world_m)}});
        }
        w.angle+=std::remainder(angle-w.lastAngle,2*std::numbers::pi);w.lastAngle=angle;
        require(std::isfinite(w.angle)&&length(state.linear_velocity_m_s)<30,"Wheel state outside bounds");
    }
    w.time+=dt;++w.ticks;w.refresh();
    for(const auto &state:w.states)require(std::isfinite(lengthSquared(state.center_of_mass_world_m))&&std::isfinite(lengthSquared(state.linear_velocity_m_s))&&length(state.linear_velocity_m_s)<30,"Fluid parcel state outside admitted bounds");
    require(w.maxCourant<.5,"Fluid CFL budget exceeded; state not qualified");
}
std::vector<PlatformInstance> WaterWheelWorld::renderInstances() const{
    const auto &w=*impl_;std::vector<PlatformInstance> out;const auto state=w.rigid.snapshot(1);unsigned id=0;
    for(const auto &p:w.parts){auto pose=state;const auto offset=state.orientation_world.rotate(p.center_local_m);pose.center_of_mass_world_m+=offset;pose.orientation_world=multiply(state.orientation_world,p.rotation_local);pose.linear_velocity_m_s+=cross(state.angular_velocity_rad_s,offset);
        PlatformInstance i{1,id++,1,w.material,p.geometry,pose};i.material_id=materialSceneName(w.material);out.push_back(i);}
    RigidPrimitive stand;stand.kind=PrimitiveKind::Box;stand.dimensions_m={.1,1.3,.1};PlatformInstance post{2,id++,2,MaterialPreset::Iron,stand,w.rigid.snapshot(2)};post.material_id="iron";out.push_back(post);
    for(auto body:w.drops){RigidPrimitive shape;shape.radius_m=spacing*.45;PlatformInstance i{3,id++,3,MaterialPreset::Glass,shape,w.rigid.snapshot(body)};i.material_id="water";out.push_back(i);}
    return out;
}
std::string WaterWheelWorld::reportJson() const{
    const auto &w=*impl_;const auto totals=w.rigid.mechanicalTotals(w.gravity),wheel=measureRigidMechanics(w.rigid.mechanicalState(1),w.gravity);
    MechanicalTotals water;for(auto id:w.drops)water+=measureRigidMechanics(w.rigid.mechanicalState(id),w.gravity);
    return Json{{"experiment","water-wheel"},{"observation_duration_s",1.6},{"elapsed_s",w.time},{"ticks",w.ticks},{"state_valid",true},{"cells",w.drops.size()+w.parts.size()+1},
        {"wheel_angle_rad",w.angle},{"wheel_rate_rad_s",w.rigid.hingeRate(w.hinge)},{"wheel_mass_kg",w.wheelMass},{"wheel_kinetic_energy_j",wheel.kinetic_energy_j},
        {"water_particles",w.drops.size()},{"water_mass_kg",water.mass_kg},{"water_mechanical_energy_j",water.mechanicalEnergy()},{"initial_water_energy_j",w.initialWaterEnergy},
        {"water_wheel_contact_events",w.waterWheelContacts},{"contact_events",w.contactEvents},{"contact_events_omitted",w.waterWheelContacts-w.contactEvents.size()},
        {"fluid_internal_energy_j",w.internalEnergy},{"fluid_viscous_work_j",w.viscousWork},{"maximum_density_kg_m3",w.maxDensity},{"maximum_mach",w.maxMach},{"maximum_courant",w.maxCourant},
        {"pair_force_residual_n",w.pairLinearResidual},{"pair_torque_residual_n_m",w.pairAngularResidual},
        {"gravity_impulse_n_s",vec(w.gravityImpulse)},{"gravity_angular_impulse_kg_m2_s",vec(w.gravityAngularImpulse)},
        {"inferred_support_contact_impulse_n_s",vec(totals.linear_momentum_kg_m_s-w.initialMomentum-w.gravityImpulse)},
        {"inferred_support_contact_angular_impulse_kg_m2_s",vec(totals.angular_momentum_kg_m2_s-w.initialAngularMomentum-w.gravityAngularImpulse)},
        {"unseparated_energy_change_j",totals.mechanicalEnergy()+w.internalEnergy+w.viscousWork-w.initialEnergy},{"energy_residual_j",nullptr},
        {"fluid_model",{{"density_kg_m3",rho0},{"particle_spacing_m",spacing},{"kernel_support_m",h},{"sound_speed_m_s",sound},{"dynamic_viscosity_pa_s",viscosity},{"particle_volume_m3",spacing*spacing*spacing}}},
        {"limitations",{"Experimental weakly compressible SPH with reduced sound speed and zero tensile pressure; not calibrated water", "Finite released column, not an infinite inlet; no surface tension or solid boundary density correction", "Native sphere-parcel/solid contact, no duplicate fluid-fluid Jolt response", "Rigid paddle mass/inertia only; no grain, bending, denting or fracture", "Support/contact numerical and dissipative losses not independently closed; inferred impulse is not a conservation residual"}}}.dump();
}
}
