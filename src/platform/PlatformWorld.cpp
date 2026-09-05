#include "platform/PlatformWorld.hpp"
#include "platform/BowlGeometry.hpp"
#include "creator/BondedBowl.hpp"
#include "rigid/JoltWorld.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <set>
#include <stdexcept>
namespace banjo {
namespace {
using json=nlohmann::json;
using Clock=std::chrono::steady_clock;
void require(bool ok,const char *message){if(!ok)throw std::invalid_argument(message);}
void fields(const json &j,std::initializer_list<const char*> allowed){
    require(j.is_object(),"expected object");
    for(auto i=j.begin();i!=j.end();++i){bool found=false;for(auto k:allowed)found|=i.key()==k;require(found,"unknown package field");}
}
double number(const json &j,double lo,double hi){require(j.is_number(),"expected SI number");double v=j.get<double>();require(std::isfinite(v)&&v>=lo&&v<=hi,"SI value outside supported bounds");return v;}
unsigned integer(const json &j,unsigned lo,unsigned hi){require(j.is_number_unsigned()||j.is_number_integer(),"expected integer");auto v=j.get<std::int64_t>();require(v>=lo&&v<=hi,"integer outside supported bounds");return unsigned(v);}
Vec3 vector(const json &j,double limit){require(j.is_array()&&j.size()==3,"expected three SI components");return {number(j[0],-limit,limit),number(j[1],-limit,limit),number(j[2],-limit,limit)};}
json vec(Vec3 v){return {v.x,v.y,v.z};}
MaterialPreset material(const json &j){for(auto p:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron,MaterialPreset::Concrete})if(j==std::string(materialPresetName(p)))return p;throw std::invalid_argument("unsupported package material");}
struct Body {unsigned id;MaterialPreset material;RigidPrimitive geometry;RigidSnapshot state;};
}
struct PlatformWorld::Impl {
    json source;
    bool reference{};
    double dt{},initial_energy{};
    Vec3 gravity;
    unsigned max_steps{};
    std::uint64_t ticks{},contact_callbacks{};
    std::vector<Body> bodies;
    std::vector<ImpactEvent> impacts;
    std::uint64_t impacts_omitted{};
    std::vector<std::array<Vec3,3>> triangles;
    std::unique_ptr<JoltWorld> rigid;
    std::unique_ptr<BondedBowl> bonded;
    std::vector<double> timings;
    double total_ms{},max_ms{};
    std::size_t timing_cursor{};
    std::string fault;
};
PlatformWorld::PlatformWorld():impl_(std::make_unique<Impl>()){}
PlatformWorld::~PlatformWorld()=default;
std::string PlatformWorld::capabilitiesJson(){return json{
    {"package_version",1},{"physics_abi","banjo-platform-1"},{"units","SI"},
    {"backends",{{"rigid-v1",{"sphere","box","finite-bowl","finite-ground","gravity","contact","render-instances"}},
                 {"bonded-reference-v2",{"sphere","finite-bowl","finite-ground","gravity","contact","render-instances","experimental-glass-fracture"}}}},
    {"limits",{{"package_bytes",4194304},{"rigid_objects",4096},{"reference_objects",9},{"steps_per_call",240}}},
    {"unsupported",{"automatic-physical-LOD","plasticity","anisotropic-fracture","live-state-package-save","scripts","network-publishing"}},
    {"realtime_guaranteed",false}}.dump(2);}
std::unique_ptr<PlatformWorld> PlatformWorld::load(const std::string &text){
    require(text.size()<=4194304,"package byte budget exceeded");
    auto source=json::parse(text);
    fields(source,{"package_version","physics_abi","name","units","backend","required_capabilities","fixed_dt_s","max_steps_per_call","gravity_m_s2","bowl","ground","objects"});
    require(source.at("package_version")==1&&source.at("physics_abi")=="banjo-platform-1","incompatible package ABI");
    require(source.at("units")=="SI","package units must be SI");
    require(source.at("name").is_string()&&source.at("name").get<std::string>().size()<=120,"invalid package name");
    require(source.at("backend")=="rigid-v1"||source.at("backend")=="bonded-reference-v2","unsupported backend");
    auto result=std::unique_ptr<PlatformWorld>(new PlatformWorld);auto &w=*result->impl_;
    w.source=source;w.reference=source["backend"]=="bonded-reference-v2";
    auto capabilities=json::parse(capabilitiesJson())["backends"][source["backend"].get<std::string>()];
    require(source.at("required_capabilities").is_array()&&source["required_capabilities"].size()<=16,"invalid capabilities");
    for(auto &c:source["required_capabilities"])require(std::find(capabilities.begin(),capabilities.end(),c)!=capabilities.end(),"required capability unsupported by selected backend");
    w.dt=number(source.at("fixed_dt_s"),1./4800,1./60);
    require(!w.reference||w.dt<=.005,"reference step exceeds 5 ms");
    w.max_steps=integer(source.at("max_steps_per_call"),1,240);
    w.gravity=vector(source.at("gravity_m_s2"),100);
    BowlSettings bowl;bool support=!source.at("bowl").is_null();
    if(support){auto &b=source["bowl"];fields(b,{"radius_m","depth_m","tilt_degrees","surface"});bowl.radius_m=number(b.at("radius_m"),.8,2);bowl.depth_m=number(b.at("depth_m"),.2,1);bowl.tilt_degrees=number(b.at("tilt_degrees"),-20,20);bowl.surface=material(b.at("surface"));w.triangles=compileBowl(bowl);}
    const bool hasGround=source.contains("ground")&&!source["ground"].is_null();
    RigidSurfaceDescription ground;
    if(hasGround){
        require(!support,"finite ground and bowl are mutually exclusive");
        auto &g=source["ground"];fields(g,{"half_length_m","half_width_m","thickness_m","surface"});
        ground.half_length_tangent_m=number(g.at("half_length_m"),.2,10);
        ground.half_length_bitangent_m=number(g.at("half_width_m"),.2,10);
        ground.thickness_m=number(g.at("thickness_m"),.05,2);
        ground.material=makeReferenceMaterial(material(g.at("surface")));
        const double x=ground.half_length_tangent_m,z=ground.half_length_bitangent_m;
        w.triangles={{{{-x,0,-z},{x,0,z},{x,0,-z}}},{{{-x,0,-z},{-x,0,z},{x,0,z}}}};
    }
    require(source.at("objects").is_array()&&!source["objects"].empty()&&source["objects"].size()<=(w.reference?9:4096),"object budget exceeded or empty scene");
    std::set<unsigned> ids;
    for(auto &o:source["objects"]){
        fields(o,{"id","material","shape","radius_m","dimensions_m","position_m","orientation_wxyz","velocity_m_s","spin_rad_s"});
        Body b;b.id=integer(o.at("id"),1,1000000);require(ids.insert(b.id).second,"duplicate object ID");b.material=material(o.at("material"));
        require(o.at("shape")=="sphere"||o.at("shape")=="box","unsupported shape");
        if(o["shape"]=="sphere"){require(!o.contains("dimensions_m"),"sphere must not declare box dimensions");b.geometry.radius_m=number(o.at("radius_m"),.01,.5);require(!w.reference||b.geometry.radius_m==.045,"reference spheres require 45 mm radius");}
        else {require(!w.reference,"reference backend does not support boxes");require(!o.contains("radius_m"),"box must not declare radius");b.geometry.kind=PrimitiveKind::Box;b.geometry.dimensions_m=vector(o.at("dimensions_m"),1);require(b.geometry.dimensions_m.x>=.02&&b.geometry.dimensions_m.y>=.02&&b.geometry.dimensions_m.z>=.02,"invalid box dimensions");}
        b.state.center_of_mass_world_m=vector(o.at("position_m"),1000);b.state.linear_velocity_m_s=vector(o.at("velocity_m_s"),100);b.state.angular_velocity_rad_s=vector(o.at("spin_rad_s"),1000);require(length(b.state.angular_velocity_rad_s)<=1000,"spin exceeds runtime magnitude limit");
        auto &q=o.at("orientation_wxyz");require(q.is_array()&&q.size()==4,"expected quaternion wxyz");b.state.orientation_world={number(q[0],-1,1),number(q[1],-1,1),number(q[2],-1,1),number(q[3],-1,1)};
        double norm=0;for(auto &v:q)norm+=v.get<double>()*v.get<double>();require(std::abs(norm-1)<1e-8,"orientation must be unit quaternion");
        for(auto &prior:w.bodies)require(!primitivesOverlap(b.geometry,b.state.center_of_mass_world_m,b.state.orientation_world,prior.geometry,prior.state.center_of_mass_world_m,prior.state.orientation_world,0),"initial objects overlap");
        if(hasGround)require(b.state.center_of_mass_world_m.y-b.geometry.extent({0,1,0},b.state.orientation_world)>=-1e-8,"object begins below ground top");
        w.bodies.push_back(b);
    }
    // All declarations are validated before allocating a solver. No live world is mutated.
    if(w.reference){
        w.bonded=std::make_unique<BondedBowl>();auto &b=*w.bonded;b.gravity=w.gravity;b.support=support||hasGround;b.bowl_radius=bowl.radius_m;b.bowl_depth=bowl.depth_m;b.tilt_degrees=bowl.tilt_degrees;b.surface=bowl.surface;
        if(hasGround){b.flat_support=true;b.ground_half_length=ground.half_length_tangent_m;b.ground_half_width=ground.half_length_bitangent_m;b.ground_thickness=ground.thickness_m;b.surface=material(source["ground"]["surface"]);}
        for(auto &o:w.bodies)b.add(o.id,o.material,o.geometry.radius_m,o.state);b.initialize();w.initial_energy=b.energy();
    }else {
        w.rigid=std::make_unique<JoltWorld>();w.rigid->setGravity(w.gravity);
        if(hasGround)w.rigid->addSupportSurface(ground);
        if(support)w.rigid->addTriangleSupport(w.triangles,makeReferenceMaterial(bowl.surface));
        for(auto &o:w.bodies){auto m=makeReferenceMaterial(o.material);if(o.geometry.kind==PrimitiveKind::Sphere){w.rigid->addBall({.body_id=o.id,.radius_m=o.geometry.radius_m,.material=m,.position_world_m=o.state.center_of_mass_world_m,.linear_velocity_m_s=o.state.linear_velocity_m_s,.angular_velocity_rad_s=o.state.angular_velocity_rad_s});w.rigid->applyRigidState(o.id,o.state);}else w.rigid->addBox({.body_id=o.id,.dimensions_m=o.geometry.dimensions_m,.material=m,.state=o.state});}
        w.initial_energy=w.rigid->mechanicalTotals(w.gravity).mechanicalEnergy();
    }
    return result;
}
PlatformStep PlatformWorld::step(unsigned count){
    auto &w=*impl_;require(count>0&&count<=w.max_steps,"step call budget exceeded");
    PlatformStep result;auto start=Clock::now();
    for(unsigned i=0;i<count&&w.fault.empty();++i){
        auto t=Clock::now();try {if(w.reference)w.bonded->advance(w.dt);else {w.rigid->step(w.dt);auto events=w.rigid->drainImpacts();w.contact_callbacks+=events.size();
            for(auto &event:events){if(w.impacts.size()<256)w.impacts.push_back(event);else ++w.impacts_omitted;}}++w.ticks;++result.completed_steps;}
        catch(const std::exception &e){w.fault=e.what();}
        double ms=std::chrono::duration<double,std::milli>(Clock::now()-t).count();w.total_ms+=ms;w.max_ms=std::max(w.max_ms,ms);if(w.timings.size()<4096)w.timings.push_back(ms);else {w.timings[w.timing_cursor]=ms;w.timing_cursor=(w.timing_cursor+1)%4096;}
    }
    result.elapsed_s=w.ticks*w.dt;result.error=w.fault;result.wall_ms=std::chrono::duration<double,std::milli>(Clock::now()-start).count();return result;
}
std::vector<PlatformInstance> PlatformWorld::renderInstances() const{
    const auto &w=*impl_;std::vector<PlatformInstance> out;
    if(w.reference){const auto &b=*w.bonded;auto components=b.components();out.reserve(b.cells.size());for(unsigned i=0;i<b.cells.size();++i){auto &c=b.cells[i];auto &o=b.objects[c.object];RigidPrimitive shape;shape.radius_m=c.radius;out.push_back({o.id,i,components[i],o.material,shape,{c.x,{},c.v,c.spin}});}}
    else {out.reserve(w.bodies.size());for(auto &o:w.bodies)out.push_back({o.id,0,o.id,o.material,o.geometry,w.rigid->snapshot(o.id)});}
    return out;
}
std::string PlatformWorld::reportJson() const{
    auto &w=*impl_;auto times=w.timings;std::sort(times.begin(),times.end());auto percentile=[&](double p){return times.empty()?0:times[std::min(times.size()-1,std::size_t(std::ceil(p*times.size())-1))];};
    json result{{"package",w.source},{"position_bits",JoltWorld::positionPrecisionBits()},{"state_valid",w.reference||w.fault.empty()},{"ticks",w.ticks},{"elapsed_s",w.ticks*w.dt},{"fault",w.fault},{"initial_energy_j",w.initial_energy},
        {"performance",{{"step_wall_total_ms",w.total_ms},{"step_p50_ms",percentile(.5)},{"step_p95_ms",percentile(.95)},{"step_max_ms",w.max_ms},{"sample_count",times.size()},{"sample_window","last 4096 steps"},{"realtime_ratio",w.total_ms>0?w.ticks*w.dt*1000/w.total_ms:0},{"includes_rendering",false},{"includes_package_load",false}}}};
    auto bodies=json::array();for(auto &o:w.bodies){auto s=w.reference?w.bonded->state(o.id):w.rigid->snapshot(o.id);bodies.push_back({{"id",o.id},{"material",materialPresetName(o.material)},{"mass_kg",o.geometry.volume()*makeReferenceMaterial(o.material).density_kg_m3},{"position_m",vec(s.center_of_mass_world_m)},{"velocity_m_s",vec(s.linear_velocity_m_s)},{"spin_rad_s",vec(s.angular_velocity_rad_s)}});}result["objects"]=bodies;
    if(w.reference){auto &b=*w.bonded;result["mechanical_energy_j"]=b.energy();result["energy_residual_j"]=b.energyResidual();result["fracture_work_j"]=b.ledger.fracture_work_j;result["elastic_release_j"]=b.ledger.elastic_release_j;result["fracture_events"]=json::array();for(auto &e:b.breaks)result["fracture_events"].push_back({{"time_s",e.time_s},{"object_id",b.objects[e.object].id},{"link",e.link},{"work_j",e.work_j}});auto c=b.components();result["connected_components"]=std::set<unsigned>(c.begin(),c.end()).size();result["limitations"]={"Coarse 19-cell geometry; uncalibrated continuum strength", "Oak/iron failure unsupported", "All material cells active; no adaptive physical LOD", "Fracture events do not identify causative contact"};}
    else {result["mechanical_energy_j"]=w.rigid->mechanicalTotals(w.gravity).mechanicalEnergy();result["energy_residual_j"]=nullptr;result["ball_contact_callbacks"]=w.contact_callbacks;
        result["ball_contact_events"]=json::array();result["ball_contact_events_omitted"]=w.impacts_omitted;
        for(auto &e:w.impacts)result["ball_contact_events"].push_back({{"tick",e.fixed_tick},{"body_a",e.body_a},{"body_b",e.body_b},{"closing_speed_m_s",e.closing_speed_m_s},{"point_m",vec(e.contact_point_world_m)}});result["limitations"]={"Rigid only; no fracture or deformation", "Energy change includes unseparated contact losses and numerical error", "Contact callbacks may be speculative and exclude supports"};}
    return result.dump(2);
}
std::string PlatformWorld::packageJson() const{return impl_->source.dump(2);}
const std::vector<std::array<Vec3,3>> &PlatformWorld::supportMesh() const{return impl_->triangles;}
unsigned PlatformWorld::fractureCount() const{return impl_->bonded?unsigned(impl_->bonded->breaks.size()):0;}
double PlatformWorld::fixedStep() const{return impl_->dt;}
}
