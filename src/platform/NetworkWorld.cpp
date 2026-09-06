#include "platform/NetworkWorld.hpp"
#include "material/NetworkMaterial.hpp"
#include "physics/ResolutionBudget.hpp"
#include "rigid/JoltWorld.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <chrono>
#include <functional>
#include <map>
#include <numeric>
#include <set>
#include <stdexcept>

namespace banjo {
namespace {
using json=nlohmann::json;
void require(bool ok,const char *message){if(!ok)throw std::invalid_argument(message);}
void fields(const json &j,std::initializer_list<const char*> allowed){
    require(j.is_object(),"network declaration must be an object");
    for(auto it=j.begin();it!=j.end();++it){bool found=false;for(auto key:allowed)found|=it.key()==key;require(found,"unknown network field");}
}
double scalar(const json &j,double lo,double hi){require(j.is_number(),"expected network SI number");auto v=j.get<double>();require(std::isfinite(v)&&v>=lo&&v<=hi,"network SI number outside bounds");return v;}
unsigned integer(const json &j,unsigned lo,unsigned hi){require(j.is_number_integer(),"expected network integer");const auto v=j.get<long long>();require(v>=lo&&v<=hi,"network integer outside bounds");return unsigned(v);}
Vec3 vector(const json &j,double lo,double hi){require(j.is_array()&&j.size()==3,"expected three network components");return {scalar(j[0],lo,hi),scalar(j[1],lo,hi),scalar(j[2],lo,hi)};}
Quat quaternion(const json &j){require(j.is_array()&&j.size()==4,"expected quaternion");Quat q{scalar(j[0],-1,1),scalar(j[1],-1,1),scalar(j[2],-1,1),scalar(j[3],-1,1)};require(std::abs(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z-1)<1e-8,"quaternion must be unit length");return q;}
json vec(Vec3 v){return {v.x,v.y,v.z};}
Quat leastTwist(Vec3 from,Vec3 to){
    from=normalized(from);to=normalized(to);const double cosine=std::clamp(dot(from,to),-1.,1.);
    if(cosine<-1.+1e-10){auto axis=cross(from,Vec3{1,0,0});if(lengthSquared(axis)<1e-10)axis=cross(from,Vec3{0,1,0});axis=normalized(axis);return {0,axis.x,axis.y,axis.z};}
    const auto axis=cross(from,to);const double scale=std::sqrt(2*(1+cosine));return {(1+cosine)/scale,axis.x/scale,axis.y/scale,axis.z/scale};
}
MaterialDefinition contactMaterial(const NetworkMaterial &m){
    MaterialDefinition c;c.name=m.name;c.model=MaterialModel::RigidOnly;c.density_kg_m3=m.density_kg_m3;
    c.young_modulus_pa=std::min({m.young_modulus_pa.x,m.young_modulus_pa.y,m.young_modulus_pa.z});c.poisson_ratio=.25;
    c.static_friction=c.dynamic_friction=c.friction=m.friction;c.restitution=0;c.contact_damping_ratio=0;c.derive_restitution_from_damping=false;return c;
}
}
struct NetworkWorld::Impl {
    struct Material {NetworkMaterial law;std::uint32_t color;};
    struct Node {unsigned object;MatterBodyId body;Vec3 reference;double mass;RigidPrimitive proxy;std::array<int,3> grid{};};
    struct Bond {unsigned object,a,b,spring;double rest,damping;DirectionalNetworkParameters parameters;NetworkBondHistory history;bool live{true};double current_stiffness{},current_damping{};Vec3 prestep_axis{1,0,0};};
    struct Object {unsigned id,material;std::string name;std::vector<unsigned> nodes;std::vector<std::array<Vec3,3>> mesh;double first_damage{-1},first_break{-1},max_pair_frequency{};
        Vec3 spacing;Quat authored_orientation;bool network{};std::vector<unsigned> face_bonds,all_bonds;std::uint64_t skin_revision{};
        mutable std::optional<CellSkinTopology> skin_topology;
    };
    explicit Impl(unsigned pairs,unsigned constraints):rigid(0,{pairs,constraints}){}
    JoltWorld rigid; // Small connected networks avoid thread-pool wakeup overhead.
    unsigned initial_pair_upper_bound{};
    std::vector<Material> materials;
    std::vector<Node> nodes;
    std::vector<Bond> bonds;
    std::vector<Object> objects;
    std::vector<RigidSnapshot> states;
    std::vector<std::array<Vec3,3>> surface;
    json events=json::array();
    Vec3 gravity;
    unsigned broken{},damaged{},pinned{};
    double time{},elastic{},fracture{},plastic{},initial_energy{},maximum_strain{};
    double total_spring_impulse{},unreleased{},maximum_extension_discrepancy{},dt{};
    ResolutionBudget resolution;
    struct DamageIntegration {
        bool enabled{},reject_on_limit{true};
        unsigned maximum_depth{4};
        double maximum_damage_increment{.05},maximum_plastic_strain_increment{.002},maximum_brittle_opening_overshoot{.05};
        std::uint64_t solver_trials{},rejected_trials{},terminal_limit_rejections{},accepted_substeps{},unresolved_substeps{},rolled_back_ticks{},discarded_substeps{};
        unsigned deepest_trial{};
        double smallest_accepted_step{},accepted_brittle_overshoot_j{};
        double accepted_maximum_damage_increment{},accepted_maximum_plastic_strain_increment{},accepted_maximum_brittle_opening_overshoot{};
    } integration;
    void singleStep(double step);
    void adaptiveStep(double step);
    mutable unsigned skin_rebuilds{},skin_queries{},skin_faces{},skin_fracture_faces{},skin_triangles{},skin_rank_fallbacks{};
    mutable double skin_last_ms{},skin_max_ms{};
    std::vector<unsigned> components() const {
        std::vector<unsigned> roots(nodes.size());std::iota(roots.begin(),roots.end(),0);
        auto root=[&](unsigned a){while(roots[a]!=a){roots[a]=roots[roots[a]];a=roots[a];}return a;};
        for(auto &b:bonds)if(b.live)roots[root(b.b)]=root(b.a);
        for(auto &r:roots)r=root(r);return roots;
    }
    void refresh(){states.clear();for(auto &n:nodes)states.push_back(rigid.snapshot(n.body));}
};
NetworkWorld::NetworkWorld(unsigned pairs,unsigned constraints):impl_(std::make_unique<Impl>(pairs,constraints)){}
NetworkWorld::~NetworkWorld()=default;

std::unique_ptr<NetworkWorld> NetworkWorld::load(const std::string &text){
    require(text.size()<=4194304,"network package byte budget");auto source=json::parse(text);
    fields(source,{"package_version","physics_abi","name","units","backend","required_capabilities","fixed_dt_s","max_steps_per_call","gravity_m_s2","ground","materials","objects","solver_iterations","temporal_policy","contact_budget","damage_integration"});
    const auto temporalPolicy=source.value("temporal_policy",std::string("diagnose"));
    require(temporalPolicy=="diagnose"||temporalPolicy=="require-resolved","unknown temporal policy");
    require(source.at("package_version")==2&&source.at("physics_abi")=="banjo-network-2"&&source.at("backend")=="material-network-v2"&&source.at("units")=="SI","unsupported network ABI or units");
    require(source.at("name").is_string()&&source["name"].get<std::string>().size()<=120,"invalid network name");
    scalar(source.at("fixed_dt_s"),1./4800,1./240);integer(source.at("max_steps_per_call"),1,240);
    const std::set<std::string> capabilities{"cell-deformation","cohesive-damage","axial-plasticity","directional-lattice","sphere","box","ellipsoid","wedge","finite-ground","gravity","contact","render-instances","blocky-cell-skins","adaptive-damage-integration"};
    require(source.at("required_capabilities").is_array()&&source["required_capabilities"].size()<=16,"invalid network capabilities");
    for(auto &v:source["required_capabilities"])require(v.is_string()&&capabilities.contains(v.get<std::string>()),"unsupported network capability");
    unsigned pairs=65536,constraints=32768;
    if(source.contains("contact_budget")){const auto &budget=source["contact_budget"];fields(budget,{"body_pairs","constraints"});
        pairs=integer(budget.at("body_pairs"),128,262144);constraints=integer(budget.at("constraints"),64,65536);require(pairs>=constraints,"body-pair budget must cover contact-constraint budget");}
    auto result=std::unique_ptr<NetworkWorld>(new NetworkWorld(pairs,constraints));auto &w=*result->impl_;
    w.rigid.setImpactObservationsEnabled(false);
    if(source.contains("damage_integration")){
        const auto &policy=source["damage_integration"];
        fields(policy,{"maximum_depth","maximum_damage_increment","maximum_plastic_strain_increment","maximum_brittle_opening_overshoot","on_limit"});
        w.integration.enabled=true;
        w.integration.maximum_depth=integer(policy.value("maximum_depth",json(4)),0,8);
        w.integration.maximum_damage_increment=scalar(policy.value("maximum_damage_increment",json(.05)),1e-6,1);
        w.integration.maximum_plastic_strain_increment=scalar(policy.value("maximum_plastic_strain_increment",json(.002)),1e-8,.1);
        w.integration.maximum_brittle_opening_overshoot=scalar(policy.value("maximum_brittle_opening_overshoot",json(.05)),1e-8,1);
        const auto limit=policy.value("on_limit",std::string("reject"));
        require(limit=="report"||limit=="reject","unknown damage integration limit policy");
        w.integration.reject_on_limit=limit=="reject";
    }
    w.dt=source["fixed_dt_s"].get<double>();
    w.gravity=vector(source.at("gravity_m_s2"),-30,30);w.rigid.setGravity(w.gravity);
    w.rigid.setContactSolverIterations(integer(source.value("solver_iterations",json(24)),4,128),4);
    require(source.at("materials").is_array()&&!source["materials"].empty()&&source["materials"].size()<=16,"network material budget");
    std::map<std::string,unsigned> materialIds;
    for(auto &m:source["materials"]){
        fields(m,{"id","density_kg_m3","young_modulus_pa","tensile_strength_pa","fracture_energy_j_m2","damping_ratio","friction","yield_strength_pa","fracture_enabled","failure_law","color_rgb","provenance"});
        require(m.at("id").is_string()&&m["id"].get<std::string>().size()<=80,"invalid network material ID");
        NetworkMaterial law;law.name=m["id"].get<std::string>();law.density_kg_m3=scalar(m.at("density_kg_m3"),10,25000);
        law.young_modulus_pa=vector(m.at("young_modulus_pa"),100,1e12);law.tensile_strength_pa=vector(m.at("tensile_strength_pa"),1,1e10);
        law.fracture_energy_j_m2=vector(m.at("fracture_energy_j_m2"),.001,1e7);law.damping_ratio=scalar(m.at("damping_ratio"),0,2);
        law.friction=scalar(m.at("friction"),0,2);law.yield_strength_pa=scalar(m.value("yield_strength_pa",json(0)),0,1e10);
        require(m.at("fracture_enabled").is_boolean(),"fracture_enabled must be boolean");law.fracture_enabled=m["fracture_enabled"].get<bool>();
        const auto failure=m.value("failure_law",std::string("cohesive"));require(failure=="cohesive"||failure=="brittle","unknown failure law");
        law.failure_law=failure=="brittle"?NetworkFailureLaw::Brittle:NetworkFailureLaw::Cohesive;
        require(m.at("provenance").is_string()&&m["provenance"].get<std::string>().size()<=500,"material provenance required");
        validateNetworkMaterial(law);const auto rgb=integer(m.at("color_rgb"),0,0xffffff);
        require(materialIds.emplace(law.name,unsigned(w.materials.size())).second,"duplicate material ID");
        w.materials.push_back({law,(rgb<<8)|255u});
    }
    if(!source.at("ground").is_null()){
        auto &g=source["ground"];fields(g,{"half_length_m","half_width_m","friction"});
        const double x=scalar(g.at("half_length_m"),.1,10),z=scalar(g.at("half_width_m"),.1,10);
        RigidSurfaceDescription floor;floor.material=contactMaterial(w.materials[0].law);floor.material.static_friction=floor.material.dynamic_friction=scalar(g.at("friction"),0,2);
        floor.half_length_tangent_m=x;floor.half_length_bitangent_m=z;floor.thickness_m=.1;w.rigid.addSupportSurface(floor);
        w.surface={{{{-x,0,-z},{x,0,z},{x,0,-z}}},{{{-x,0,-z},{-x,0,z},{x,0,z}}}};
    }
    require(source.at("objects").is_array()&&!source["objects"].empty()&&source["objects"].size()<=32,"network object budget");
    std::set<unsigned> ids;
    for(auto &o:source["objects"]){
        fields(o,{"id","name","material","shape","representation","dimensions_m","resolution","position_m","orientation_wxyz","velocity_m_s","spin_rad_s","pin_boundary","grain_wxyz"});
        const auto id=integer(o.at("id"),1,1000000);require(ids.insert(id).second,"duplicate network object ID");
        require(o.at("name").is_string()&&o["name"].get<std::string>().size()<=100,"invalid network object name");
        require(o.at("material").is_string()&&materialIds.contains(o["material"].get<std::string>()),"unknown network material");
        const auto material=materialIds.at(o["material"].get<std::string>());const auto &law=w.materials[material].law;
        const auto d=vector(o.at("dimensions_m"),.004,2);const auto p=vector(o.at("position_m"),-10,10);const auto q=quaternion(o.at("orientation_wxyz"));
        const auto velocity=vector(o.at("velocity_m_s"),-30,30),spin=vector(o.at("spin_rad_s"),-100,100);
        const auto shape=o.at("shape").get<std::string>(),representation=o.at("representation").get<std::string>();
        require(shape=="sphere"||shape=="box"||shape=="ellipsoid"||shape=="wedge","unsupported network shape");
        require(representation=="rigid"||representation=="network","unsupported representation");
        require(shape!="sphere"||representation=="rigid","sphere currently requires rigid representation");
        require(shape!="wedge"||representation=="rigid","wedge currently requires rigid representation");
        require(shape!="ellipsoid"||representation=="network","ellipsoid currently requires network representation");
        w.objects.push_back({id,material,o["name"].get<std::string>(),{}, {}});auto &object=w.objects.back();const unsigned objectIndex=unsigned(w.objects.size()-1);
        if(representation=="rigid"){
            require(w.nodes.size()<1024,"world cell budget exceeded");
            require(!o.contains("resolution")&&!o.contains("pin_boundary")&&!o.contains("grain_wxyz"),"network-only rigid object fields");
            const MatterBodyId body=1000001+w.nodes.size();RigidSnapshot state{p,q,velocity,spin};double mass;
            RigidPrimitive proxy;proxy.kind=PrimitiveKind::Box;proxy.dimensions_m=d;
            if(shape=="sphere"){
                const double tolerance=1e-12*std::max({1.0,d.x,d.y,d.z});
                require(std::abs(d.x-d.y)<=tolerance&&std::abs(d.x-d.z)<=tolerance,
                    "sphere dimensions must specify equal diameters");
                proxy.kind=PrimitiveKind::Sphere;proxy.radius_m=d.x/2;
                mass=law.density_kg_m3*proxy.volume();
                RigidBallDescription sphere;
                sphere.body_id=body;sphere.radius_m=proxy.radius_m;sphere.material=contactMaterial(law);
                sphere.position_world_m=p;sphere.linear_velocity_m_s=velocity;sphere.angular_velocity_rad_s=spin;
                w.rigid.addBall(sphere);
                // addBall's legacy sphere descriptor has no orientation field;
                // preserve the package's rigid state after creation even though
                // a homogeneous sphere has orientation-independent mechanics.
                w.rigid.applyRigidState(body,state);
            }else if(shape=="wedge"){
                std::vector<Vec3> points;
                for(double z:{-d.z/2,d.z/2}){points.push_back({-d.x/2,d.y/3,z});points.push_back({d.x/2,d.y/3,z});points.push_back({0,-2*d.y/3,z});}
                mass=law.density_kg_m3*d.x*d.y*d.z/2;Mat3 inertia;
                inertia.m[0][0]=mass*(d.y*d.y/18+d.z*d.z/12);inertia.m[1][1]=mass*(d.x*d.x/24+d.z*d.z/12);inertia.m[2][2]=mass*(d.x*d.x/24+d.y*d.y/18);
                w.rigid.addConvex({body,points,contactMaterial(law),state,mass,inertia});
                for(auto t:std::vector<std::array<unsigned,3>>{{0,2,1},{3,4,5},{0,1,4},{0,4,3},{1,2,5},{1,5,4},{2,0,3},{2,3,5}})object.mesh.push_back({points[t[0]],points[t[1]],points[t[2]]});
            }else {mass=law.density_kg_m3*proxy.volume();w.rigid.addBox({body,d,contactMaterial(law),state});}
            object.nodes.push_back(unsigned(w.nodes.size()));w.nodes.push_back({objectIndex,body,{},mass,proxy});continue;
        }
        require(o.at("resolution").is_array()&&o["resolution"].size()==3,"network resolution required");
        const unsigned nx=integer(o["resolution"][0],2,16),ny=integer(o["resolution"][1],2,16),nz=integer(o["resolution"][2],2,16);
        require(nx*ny*nz<=800,"network object cell budget");
        const Vec3 h{d.x/nx,d.y/ny,d.z/nz};const double volume=h.x*h.y*h.z,mass=law.density_kg_m3*volume;
        object.spacing=h;object.authored_orientation=q;object.network=true;
        const double radius=.49*std::min({h.x,h.y,h.z});
        require(radius>=.001,"network cells below collision resolution");
        const auto grain=quaternion(o.value("grain_wxyz",json::array({1,0,0,0})));const Quat inverseGrain{grain.w,-grain.x,-grain.y,-grain.z};
        bool pin=false;if(o.contains("pin_boundary")){require(o["pin_boundary"].is_boolean(),"pin_boundary must be boolean");pin=o["pin_boundary"].get<bool>();}
        std::map<std::array<int,3>,unsigned> indices;
        for(unsigned x=0;x<nx;++x)for(unsigned y=0;y<ny;++y)for(unsigned z=0;z<nz;++z){
            const Vec3 local{(x+.5)*h.x-d.x/2,(y+.5)*h.y-d.y/2,(z+.5)*h.z-d.z/2};
            if(shape=="ellipsoid"&&4*(local.x*local.x/(d.x*d.x)+local.y*local.y/(d.y*d.y)+local.z*local.z/(d.z*d.z))>1)continue;
            require(w.nodes.size()<1024,"world cell budget exceeded");const unsigned index=unsigned(w.nodes.size());const MatterBodyId body=1000001+index;
            RigidPrimitive proxy;proxy.radius_m=radius;
            RigidPrimitive matter;matter.kind=PrimitiveKind::Box;matter.dimensions_m=h;
            RigidCompoundDescription cell;cell.body_id=body;cell.material=contactMaterial(law);cell.parts={{proxy,{}}};cell.mass_kg=mass;cell.inertia_local_kg_m2=matter.inertia(mass);
            const auto offset=q.rotate(local);cell.state={p+offset,q,velocity+cross(spin,offset),spin};w.rigid.addCompound(cell);
            if(pin&&(x==0||x==nx-1||y==0||y==ny-1)){w.rigid.pinToWorld(body);++w.pinned;}
            indices.emplace(std::array<int,3>{int(x),int(y),int(z)},index);object.nodes.push_back(index);w.nodes.push_back({objectIndex,body,local,mass,proxy,{int(x),int(y),int(z)}});
        }
        require(!indices.empty(),"empty occupied network");
        const double area=std::pow(volume,2./3)/6;
        for(auto &[grid,a]:indices)for(int dx=-1;dx<=1;++dx)for(int dy=-1;dy<=1;++dy)for(int dz=-1;dz<=1;++dz){
            if(dx*dx+dy*dy+dz*dz>2||dx*dx+dy*dy+dz*dz==0)continue;
            const auto it=indices.find({grid[0]+dx,grid[1]+dy,grid[2]+dz});if(it==indices.end()||it->second<=a)continue;const auto b=it->second;
            const Vec3 rest=w.nodes[b].reference-w.nodes[a].reference;const double length0=length(rest);
            auto parameters=directionalNetworkParameters(law,inverseGrain.rotate(rest/length0),area,length0);
            object.max_pair_frequency=std::max(object.max_pair_frequency,std::sqrt(2*parameters.stiffness_n_m/mass));
            (void)advanceNetworkBond(law,parameters,{},0,length0);
            const double damping=2*law.damping_ratio*std::sqrt(parameters.stiffness_n_m*mass/2);
            const auto spring=w.rigid.addDistanceSpring(w.nodes[a].body,w.nodes[b].body,length0,parameters.stiffness_n_m,damping);
            w.bonds.push_back({objectIndex,a,b,spring,length0,damping,parameters,{},true});
            object.all_bonds.push_back(unsigned(w.bonds.size()-1));
            if(dx*dx+dy*dy+dz*dz==1)object.face_bonds.push_back(unsigned(w.bonds.size()-1));
            w.bonds.back().current_stiffness=parameters.stiffness_n_m;w.bonds.back().current_damping=damping;
        }
    }
    std::vector<double> masses;for(auto &node:w.nodes)masses.push_back(node.mass);
    std::vector<ResolutionLink> links;for(auto &bond:w.bonds)links.push_back({bond.a,bond.b,bond.parameters.stiffness_n_m});
    w.resolution=assessSpringResolution(masses,links,w.dt);
    require(temporalPolicy!="require-resolved"||w.resolution.temporally_resolved,
        "unresolved material dynamics: requested timestep exceeds the spring-network temporal bound; use a resolved local solver");
    w.initial_pair_upper_bound=w.rigid.contactPairUpperBound();
    require(w.initial_pair_upper_bound<=constraints&&w.initial_pair_upper_bound<=pairs,
        "initial contact envelope exceeds contact_budget; increase the explicit resource budget or reduce local density");
    w.refresh();w.initial_energy=w.rigid.mechanicalTotals(w.gravity).mechanicalEnergy();return result;
}
void NetworkWorld::step(double dt){
    auto &w=*impl_;require(std::isfinite(dt)&&std::abs(dt-w.dt)<1e-15,"network step must match admitted fixed timestep");
    if(w.integration.enabled)w.adaptiveStep(dt);else w.singleStep(dt);
}
void NetworkWorld::Impl::singleStep(double step_dt){
    auto &w=*this;
    // Jolt forms each DistanceConstraint axis from the positions at the start
    // of the step. Keep that axis for reaction decomposition: using the
    // rotated post-step axis would turn transverse velocity into fabricated
    // axial damping, and therefore fabricated elastic compression.
    for(auto &b:w.bonds)if(b.live)b.prestep_axis=normalized(
        w.states[b.b].center_of_mass_world_m-w.states[b.a].center_of_mass_world_m);
    w.rigid.step(step_dt);w.time+=step_dt;w.refresh();w.elastic=0;w.damaged=0;
    for(auto &b:w.bonds){
        if(!b.live)continue;
        auto &object=w.objects[b.object];const auto &law=w.materials[object.material].law;
        const Vec3 separation=w.states[b.b].center_of_mass_world_m-w.states[b.a].center_of_mass_world_m;
        const double geometricExtension=length(separation)-b.rest;
        const double rate=dot(w.states[b.b].linear_velocity_m_s-w.states[b.a].linear_velocity_m_s,b.prestep_axis);
        const double impulse=w.rigid.distanceSpringImpulse(b.spring);
        // Reconstruct the spring's elastic opening from its actually applied
        // axial reaction, separating its damping term. Finite-iteration
        // positional residuals must not masquerade as enormous elastic energy
        // in very stiff glass/metal networks. This remains an averaged-step
        // reaction model; unresolved wave peaks require temporal refinement.
        const double elasticForce=-impulse/step_dt-b.current_damping*rate;
        const double extension=elasticForce/b.current_stiffness+b.history.plastic_extension_m;
        w.maximum_extension_discrepancy=std::max(w.maximum_extension_discrepancy,std::abs(extension-geometricExtension));
        w.maximum_strain=std::max(w.maximum_strain,std::abs(extension/b.rest));
        w.total_spring_impulse+=std::abs(impulse);
        auto update=advanceNetworkBond(law,b.parameters,b.history,extension,b.rest);
        const bool changed=update.history.damage!=b.history.damage||update.history.plastic_extension_m!=b.history.plastic_extension_m;
        if(update.history.damage>0&&object.first_damage<0)object.first_damage=w.time;
        w.fracture+=update.fracture_increment_j;w.plastic+=update.plastic_increment_j;w.elastic+=update.elastic_energy_j;w.unreleased+=update.unreleased_energy_j;
        b.history=update.history;if(b.history.damage>0)++w.damaged;
        if(update.failed){
            b.live=false;++w.broken;++object.skin_revision;w.rigid.removeDistanceSpring(b.spring);if(object.first_break<0)object.first_break=w.time;
            if(w.events.size()<20000)w.events.push_back({{"time_s",w.time},{"object_id",object.id},{"a",b.a},{"b",b.b},{"position_m",vec((w.states[b.a].center_of_mass_world_m+w.states[b.b].center_of_mass_world_m)/2)},{"fracture_work_j",b.history.fracture_dissipation_j}});
        }else {
            // Compression remains recoverable even when the tensile branch is
            // damaged. The current branch is refreshed every physical step.
            const double stiffness=std::max(update.stiffness_n_m,1e-8);
            const double newRest=b.rest+b.history.plastic_extension_m;
            require(newRest>=1e-6,"plastic cell collapse exceeded model validity");
            const double damping=b.damping*std::sqrt(stiffness/b.parameters.stiffness_n_m);
            if(changed||stiffness!=b.current_stiffness)w.rigid.updateDistanceSpring(b.spring,newRest,stiffness,damping);
            b.current_stiffness=stiffness;b.current_damping=damping;
        }
    }
    (void)w.rigid.drainImpacts();
}
void NetworkWorld::Impl::adaptiveStep(double step){
    auto &w=*this;
    // The outer Jolt transaction covers contacts, spring settings/removals and
    // constraint ordering. Keep the corresponding authoritative material state
    // here; no trial may publish damage, work, lineage, timestamps or events.
    const auto savedBonds=w.bonds;const auto savedStates=w.states;
    struct ObjectProgress {double damage,fracture;std::uint64_t revision;};
    std::vector<ObjectProgress> savedObjects;for(const auto &o:w.objects)savedObjects.push_back({o.first_damage,o.first_break,o.skin_revision});
    const auto savedEvents=w.events.size();
    const auto savedTime=w.time,savedElastic=w.elastic,savedFracture=w.fracture,savedPlastic=w.plastic;
    const auto savedStrain=w.maximum_strain,savedImpulse=w.total_spring_impulse,savedUnreleased=w.unreleased,savedDiscrepancy=w.maximum_extension_discrepancy;
    const auto savedBroken=w.broken,savedDamaged=w.damaged;
    auto restore=[&]{
        w.bonds=savedBonds;w.states=savedStates;
        for(unsigned i=0;i<w.objects.size();++i){w.objects[i].first_damage=savedObjects[i].damage;w.objects[i].first_break=savedObjects[i].fracture;w.objects[i].skin_revision=savedObjects[i].revision;}
        w.events.erase(w.events.begin()+std::ptrdiff_t(savedEvents),w.events.end());
        w.time=savedTime;w.elastic=savedElastic;w.fracture=savedFracture;w.plastic=savedPlastic;
        w.maximum_strain=savedStrain;w.total_spring_impulse=savedImpulse;w.unreleased=savedUnreleased;w.maximum_extension_discrepancy=savedDiscrepancy;
        w.broken=savedBroken;w.damaged=savedDamaged;
    };
    struct PendingBond {unsigned index;NetworkBondUpdate update;double extension,discrepancy,impulse,brittle_overshoot_j;};
    struct Candidate {std::vector<RigidSnapshot> states;std::vector<PendingBond> bonds;bool exceeds{};double damage_increment{},plastic_increment{},brittle_overshoot{};};
    struct TrialStatistics {unsigned trials{},rejected{},terminal_rejections{},accepted{},unresolved{},depth{};double minimum_step{},brittle_overshoot_j{},damage_increment{},plastic_increment{},brittle_overshoot{};} stats;
    auto preview=[&](double dt){
        std::vector<Vec3> axes;axes.reserve(w.bonds.size());
        for(const auto &b:w.bonds)axes.push_back(b.live?normalized(w.states[b.b].center_of_mass_world_m-w.states[b.a].center_of_mass_world_m):Vec3{});
        w.rigid.step(dt);Candidate candidate;candidate.states.reserve(w.nodes.size());candidate.bonds.reserve(w.bonds.size());
        for(const auto &n:w.nodes)candidate.states.push_back(w.rigid.snapshot(n.body));
        for(unsigned i=0;i<w.bonds.size();++i){
            const auto &b=w.bonds[i];if(!b.live)continue;
            const auto &law=w.materials[w.objects[b.object].material].law;
            const auto &a=candidate.states[b.a],&c=candidate.states[b.b];
            const double rate=dot(c.linear_velocity_m_s-a.linear_velocity_m_s,axes[i]);
            const double impulse=w.rigid.distanceSpringImpulse(b.spring);
            const double extension=(-impulse/dt-b.current_damping*rate)/b.current_stiffness+b.history.plastic_extension_m;
            const auto update=advanceNetworkBond(law,b.parameters,b.history,extension,b.rest);
            double overshoot=0,overshootWork=0;
            if(update.failed&&law.failure_law==NetworkFailureLaw::Brittle){
                // The brittle law requires BOTH strength and fracture work.
                // Threshold energy above Gc is not integration overshoot.
                const double threshold=std::max(b.parameters.strength_n/b.parameters.stiffness_n_m,
                    std::sqrt(2*b.parameters.fracture_work_j/b.parameters.stiffness_n_m));
                const double opening=std::max(0.,extension-update.history.plastic_extension_m);
                overshoot=std::max(0.,opening/threshold-1.);
                overshootWork=std::max(0.,.5*b.parameters.stiffness_n_m*(opening*opening-threshold*threshold));
            }
            candidate.exceeds|=(law.failure_law==NetworkFailureLaw::Cohesive&&update.history.damage-b.history.damage>w.integration.maximum_damage_increment)||
                std::abs(update.history.plastic_extension_m-b.history.plastic_extension_m)/b.rest>w.integration.maximum_plastic_strain_increment||
                overshoot>w.integration.maximum_brittle_opening_overshoot;
            if(law.failure_law==NetworkFailureLaw::Cohesive)candidate.damage_increment=std::max(candidate.damage_increment,update.history.damage-b.history.damage);
            candidate.plastic_increment=std::max(candidate.plastic_increment,std::abs(update.history.plastic_extension_m-b.history.plastic_extension_m)/b.rest);
            candidate.brittle_overshoot=std::max(candidate.brittle_overshoot,overshoot);
            candidate.bonds.push_back({i,update,extension,std::abs(extension-(length(c.center_of_mass_world_m-a.center_of_mass_world_m)-b.rest)),std::abs(impulse),overshootWork});
        }
        return candidate;
    };
    auto commit=[&](Candidate &&candidate,double dt){
        stats.damage_increment=std::max(stats.damage_increment,candidate.damage_increment);
        stats.plastic_increment=std::max(stats.plastic_increment,candidate.plastic_increment);
        stats.brittle_overshoot=std::max(stats.brittle_overshoot,candidate.brittle_overshoot);
        w.states=std::move(candidate.states);w.time+=dt;w.elastic=0;w.damaged=0;
        for(const auto &pending:candidate.bonds){
            auto &b=w.bonds[pending.index];auto &object=w.objects[b.object];const auto &update=pending.update;
            const bool changed=update.history.damage!=b.history.damage||update.history.plastic_extension_m!=b.history.plastic_extension_m;
            w.maximum_extension_discrepancy=std::max(w.maximum_extension_discrepancy,pending.discrepancy);
            w.maximum_strain=std::max(w.maximum_strain,std::abs(pending.extension/b.rest));w.total_spring_impulse+=pending.impulse;
            w.fracture+=update.fracture_increment_j;w.plastic+=update.plastic_increment_j;w.elastic+=update.elastic_energy_j;w.unreleased+=update.unreleased_energy_j;
            stats.brittle_overshoot_j+=pending.brittle_overshoot_j;
            if(update.history.damage>0&&object.first_damage<0)object.first_damage=w.time;
            b.history=update.history;if(b.history.damage>0)++w.damaged;
            if(update.failed){
                b.live=false;++w.broken;++object.skin_revision;w.rigid.removeDistanceSpring(b.spring);if(object.first_break<0)object.first_break=w.time;
                if(w.events.size()<20000)w.events.push_back({{"time_s",w.time},{"object_id",object.id},{"a",b.a},{"b",b.b},{"position_m",vec((w.states[b.a].center_of_mass_world_m+w.states[b.b].center_of_mass_world_m)/2)},{"fracture_work_j",b.history.fracture_dissipation_j}});
            }else{
                const double stiffness=std::max(update.stiffness_n_m,1e-8),rest=b.rest+b.history.plastic_extension_m;
                require(rest>=1e-6,"plastic cell collapse exceeded model validity");
                const double damping=b.damping*std::sqrt(stiffness/b.parameters.stiffness_n_m);
                if(changed||stiffness!=b.current_stiffness)w.rigid.updateDistanceSpring(b.spring,rest,stiffness,damping);
                b.current_stiffness=stiffness;b.current_damping=damping;
            }
        }
        (void)w.rigid.drainImpacts();++stats.accepted;
        stats.minimum_step=stats.minimum_step==0?dt:std::min(stats.minimum_step,dt);
    };
    std::function<void(double,unsigned)> advance=[&](double dt,unsigned depth){
        ++stats.trials;stats.depth=std::max(stats.depth,depth);std::optional<Candidate> candidate;
        const bool accepted=w.rigid.runSpringTrial([&]{
            candidate=preview(dt);
            if(candidate->exceeds){
                if(depth<w.integration.maximum_depth)return false;
                if(w.integration.reject_on_limit){++stats.terminal_rejections;throw std::runtime_error("damage integration limit exceeded; complete outer tick rolled back");}
                ++stats.unresolved;
            }
            return true;
        });
        if(accepted)commit(std::move(*candidate),dt);
        else{++stats.rejected;candidate.reset();advance(dt/2,depth+1);advance(dt/2,depth+1);}
    };
    auto recordAttempts=[&]{w.integration.solver_trials+=stats.trials;w.integration.rejected_trials+=stats.rejected;w.integration.terminal_limit_rejections+=stats.terminal_rejections;w.integration.deepest_trial=std::max(w.integration.deepest_trial,stats.depth);};
    try{(void)w.rigid.runSpringTrial([&]{advance(step,0);return true;});}
    catch(...){restore();recordAttempts();++w.integration.rolled_back_ticks;w.integration.discarded_substeps+=stats.accepted;throw;}
    // Public time stays on its authored clock; substeps share that interval.
    w.time=savedTime+step;recordAttempts();w.integration.accepted_substeps+=stats.accepted;
    w.integration.unresolved_substeps+=stats.unresolved;w.integration.accepted_brittle_overshoot_j+=stats.brittle_overshoot_j;
    w.integration.accepted_maximum_damage_increment=std::max(w.integration.accepted_maximum_damage_increment,stats.damage_increment);
    w.integration.accepted_maximum_plastic_strain_increment=std::max(w.integration.accepted_maximum_plastic_strain_increment,stats.plastic_increment);
    w.integration.accepted_maximum_brittle_opening_overshoot=std::max(w.integration.accepted_maximum_brittle_opening_overshoot,stats.brittle_overshoot);
    if(stats.minimum_step>0)w.integration.smallest_accepted_step=w.integration.smallest_accepted_step==0?stats.minimum_step:std::min(w.integration.smallest_accepted_step,stats.minimum_step);
}
std::vector<PlatformInstance> NetworkWorld::renderInstances() const {
    const auto &w=*impl_;auto groups=w.components();std::vector<PlatformInstance> result;result.reserve(w.nodes.size());
    for(unsigned i=0;i<w.nodes.size();++i){const auto &n=w.nodes[i];const auto &o=w.objects[n.object];
        PlatformInstance instance{o.id,i,groups[i],MaterialPreset::Glass,n.proxy,w.states[i]};instance.color_rgba=w.materials[o.material].color;instance.material_id=w.materials[o.material].law.name;instance.local_mesh=o.mesh;instance.deformable_cell=o.network;result.push_back(std::move(instance));}
    return result;
}
std::vector<PlatformSkin> NetworkWorld::renderSkins() const {
    const auto start=std::chrono::steady_clock::now();const auto &w=*impl_;const auto groups=w.components();
    std::vector<PlatformSkin> result;unsigned faces=0,fractures=0,triangles=0,rankFallbacks=0;
    for(const auto &o:w.objects)if(o.network){
        std::vector<SkinCell> cells;cells.reserve(o.nodes.size());std::vector<unsigned> local(w.nodes.size());
        for(auto i:o.nodes){local[i]=unsigned(cells.size());const auto &n=w.nodes[i];const auto &s=w.states[i];
            cells.push_back({i,groups[i],n.grid,n.reference,s.center_of_mass_world_m,
                {s.orientation_world.rotate({o.spacing.x/2,0,0}),s.orientation_world.rotate({0,o.spacing.y/2,0}),s.orientation_world.rotate({0,0,o.spacing.z/2})}});}
        std::vector<SkinFaceLink> links;links.reserve(o.face_bonds.size());
        std::vector<std::array<Vec3,3>> axes(cells.size());std::vector<std::array<unsigned,3>> counts(cells.size());
        std::vector<Mat3> referenceMoments(cells.size()),currentMoments(cells.size());
        std::vector<Vec3> firstReference(cells.size()),firstCurrent(cells.size());std::vector<unsigned> neighborCounts(cells.size());
        for(auto i:o.all_bonds){const auto &b=w.bonds[i];if(!b.live)continue;const auto a=local[b.a],c=local[b.b];
            std::array<double,3> r{};for(unsigned k=0;k<3;++k)r[k]=cells[c].grid[k]-cells[a].grid[k];
            const auto delta=cells[c].center_world_m-cells[a].center_world_m;const std::array<double,3> p{delta.x,delta.y,delta.z};
            for(auto cell:{a,c})if(neighborCounts[cell]++==0){firstReference[cell]=o.authored_orientation.rotate(w.nodes[b.b].reference-w.nodes[b.a].reference);firstCurrent[cell]=delta;}
            for(auto cell:{a,c})for(unsigned row=0;row<3;++row)for(unsigned column=0;column<3;++column){
                referenceMoments[cell].m[row][column]+=r[row]*r[column];currentMoments[cell].m[row][column]+=p[row]*r[column];}
        }
        for(auto i:o.face_bonds){const auto &b=w.bonds[i];links.push_back({b.a,b.b,b.live});if(!b.live)continue;
            const auto a=local[b.a],c=local[b.b];unsigned axis=0;for(unsigned k=0;k<3;++k)if(cells[a].grid[k]!=cells[c].grid[k])axis=k;
            const int sign=cells[c].grid[axis]-cells[a].grid[axis];
            const auto half=(cells[c].center_world_m-cells[a].center_world_m)*(sign*.5);
            for(auto cell:{a,c}){axes[cell][axis]+=half;++counts[cell][axis];}
        }
        // Fit world displacement to reference-grid displacement using only
        // live neighbors. Intrinsic sphere spin is not material-frame motion.
        // The reference matrix is dimensionless to avoid a cell-size cutoff.
        for(unsigned i=0;i<cells.size();++i){
            if(const auto inverse=referenceMoments[i].inverse()){
                for(unsigned axis=0;axis<3;++axis){const Vec3 column{inverse->m[0][axis],inverse->m[1][axis],inverse->m[2][axis]};cells[i].half_axes_world_m[axis]=(currentMoments[i]*column)*.5;}
            }else{
                ++rankFallbacks;
                if(neighborCounts[i]){const auto rotation=leastTwist(firstReference[i],firstCurrent[i]);
                    cells[i].half_axes_world_m={rotation.rotate(o.authored_orientation.rotate({o.spacing.x/2,0,0})),rotation.rotate(o.authored_orientation.rotate({0,o.spacing.y/2,0})),rotation.rotate(o.authored_orientation.rotate({0,0,o.spacing.z/2}))};}
                unsigned observed=0,missing=0;for(unsigned axis=0;axis<3;++axis){if(counts[i][axis]){cells[i].half_axes_world_m[axis]=axes[i][axis]/counts[i][axis];++observed;}else missing=axis;}
                if(observed==2){const auto normal=cross(cells[i].half_axes_world_m[(missing+1)%3],cells[i].half_axes_world_m[(missing+2)%3]);
                    if(lengthSquared(normal)>1e-24){const std::array<double,3> half{ o.spacing.x/2,o.spacing.y/2,o.spacing.z/2};cells[i].half_axes_world_m[missing]=normalized(normal)*half[missing];}}
            }
        }
        if(!o.skin_topology||o.skin_topology->revision!=o.skin_revision){o.skin_topology=buildCellSkinTopology(cells,links,o.skin_revision);++w.skin_rebuilds;}
        auto mesh=evaluateCellSkin(*o.skin_topology,cells);faces+=mesh.exposed_faces;fractures+=mesh.fracture_faces;triangles+=unsigned(mesh.triangles.size());
        result.push_back({o.id,w.materials[o.material].law.name,w.materials[o.material].color,std::move(mesh)});
    }
    ++w.skin_queries;w.skin_faces=faces;w.skin_fracture_faces=fractures;w.skin_triangles=triangles;w.skin_rank_fallbacks=rankFallbacks;
    w.skin_last_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();w.skin_max_ms=std::max(w.skin_max_ms,w.skin_last_ms);
    return result;
}
std::vector<PlatformBondLine> NetworkWorld::renderBonds() const {
    const auto &w=*impl_;std::vector<PlatformBondLine> result;
    for(auto &b:w.bonds)if(b.live||length(w.states[b.a].center_of_mass_world_m-w.states[b.b].center_of_mass_world_m)<b.rest*1.5)
        result.push_back({w.states[b.a].center_of_mass_world_m,w.states[b.b].center_of_mass_world_m,b.live,b.history.damage,b.history.plastic_extension_m,w.objects[b.object].id,b.a,b.b});return result;
}
const std::vector<std::array<Vec3,3>> &NetworkWorld::supportMesh() const {return impl_->surface;}
unsigned NetworkWorld::fractureCount() const{return impl_->broken;}
double NetworkWorld::energy() const{return impl_->rigid.mechanicalTotals(impl_->gravity).mechanicalEnergy()+impl_->elastic;}
std::string NetworkWorld::reportJson() const {
    const auto &w=*impl_;auto groups=w.components();json objects=json::array();
    for(unsigned i=0;i<w.objects.size();++i){const auto &o=w.objects[i];double mass=0;Vec3 center,velocity;std::set<unsigned> components;unsigned broken=0,damaged=0,links=0;double plastic=0;
        for(auto node:o.nodes){const auto &n=w.nodes[node];mass+=n.mass;center+=w.states[node].center_of_mass_world_m*n.mass;velocity+=w.states[node].linear_velocity_m_s*n.mass;components.insert(groups[node]);}
        for(auto &b:w.bonds)if(b.object==i){++links;broken+=!b.live;damaged+=b.history.damage>0;plastic+=b.history.plastic_dissipation_j;}
        objects.push_back({{"id",o.id},{"name",o.name},{"material",w.materials[o.material].law.name},{"mass_kg",mass},{"position_m",vec(center/mass)},{"velocity_m_s",vec(velocity/mass)},{"spin_rad_s",nullptr},
            {"cells",o.nodes.size()},{"links",links},{"damaged_links",damaged},{"broken_links",broken},{"components",components.size()},{"largest_component_cells",0},{"first_damage_s",o.first_damage},{"first_break_s",o.first_break},{"plastic_work_j",plastic},
            {"max_isolated_pair_frequency_rad_s",o.max_pair_frequency},{"step_times_pair_frequency",w.dt*o.max_pair_frequency}});
        std::map<unsigned,unsigned> sizes;for(auto node:o.nodes)++sizes[groups[node]];unsigned largest=0;for(auto &[key,count]:sizes){(void)key;largest=std::max(largest,count);}objects.back()["largest_component_cells"]=largest;
    }
    const auto mechanics=w.rigid.mechanicalTotals(w.gravity);
    const auto contacts=w.rigid.contactDiagnostics();
    return json{{"model","material-network-v2"},{"physical_response_validated",false},
        {"damage_integration",{{"mode",w.integration.enabled?"adaptive-damage-trials":"single-step"},{"maximum_depth",w.integration.maximum_depth},
            {"maximum_damage_increment",w.integration.maximum_damage_increment},{"maximum_plastic_strain_increment",w.integration.maximum_plastic_strain_increment},{"maximum_brittle_opening_overshoot",w.integration.maximum_brittle_opening_overshoot},
            {"on_limit",w.integration.reject_on_limit?"reject":"report"},{"maximum_solver_trials_per_tick",w.integration.enabled?((1u<<(w.integration.maximum_depth+1))-1):1u},
            {"solver_trials",w.integration.solver_trials},{"rejected_trials",w.integration.rejected_trials},{"accepted_substeps",w.integration.accepted_substeps},{"unresolved_substeps",w.integration.unresolved_substeps},
            {"rejected_trials_meaning","bisected coarse trials"},{"terminal_limit_rejections",w.integration.terminal_limit_rejections},
            {"rolled_back_ticks",w.integration.rolled_back_ticks},{"discarded_substeps",w.integration.discarded_substeps},{"deepest_trial",w.integration.deepest_trial},{"smallest_accepted_step_s",w.integration.smallest_accepted_step},
            {"accepted_brittle_threshold_overshoot_j",w.integration.accepted_brittle_overshoot_j},{"overshoot_is_not_an_additional_energy_store",true},
            {"accepted_maximum_damage_increment",w.integration.accepted_maximum_damage_increment},{"accepted_maximum_plastic_strain_increment",w.integration.accepted_maximum_plastic_strain_increment},{"accepted_maximum_brittle_opening_overshoot",w.integration.accepted_maximum_brittle_opening_overshoot},
            {"configured_limits_are_targets_in_report_mode",true},{"endpoint_acceptance_criteria",true},{"detects_intra_substep_peaks",false},{"resolves_contact_or_elastic_wave_error",false},{"world_tick_transactional",w.integration.enabled}}},
        {"contact_budget",{{"body_pairs",contacts.capacity.body_pairs},{"constraints",contacts.capacity.constraints},{"initial_pair_upper_bound",w.initial_pair_upper_bound},{"initial_envelope_only",true},{"speculative_distance_m",contacts.speculative_distance_m},
            {"temporary_arena_bytes",contacts.temporary_arena_bytes},{"observations_are_allocator_occupancy",false},
            {"last_manifolds",contacts.last_manifolds},{"peak_manifolds",contacts.peak_manifolds},{"last_points",contacts.last_points},{"peak_points",contacts.peak_points},
            {"last_speculative_manifolds",contacts.last_speculative_manifolds},{"peak_speculative_manifolds",contacts.peak_speculative_manifolds},{"impact_event_estimation",false}}},
        {"skin",{{"mode","blocky-cell-surface-v1"},{"queries",w.skin_queries},{"object_topology_rebuilds",w.skin_rebuilds},{"exposed_faces",w.skin_faces},{"fracture_faces",w.skin_fracture_faces},{"triangles",w.skin_triangles},{"rank_deficient_frame_fallbacks",w.skin_rank_fallbacks},{"last_query_ms",w.skin_last_ms},{"max_query_ms",w.skin_max_ms},{"physical_mutation",false},{"contact_surface_matches_skin",false},{"smooth_surface",false},{"asynchronous_patches",false}}},
        {"temporal_resolution",{{"resolved",w.resolution.temporally_resolved},{"maximum_frequency_bound_rad_s",w.resolution.maximum_frequency_bound_rad_s},{"maximum_step_s",w.resolution.maximum_step_s},{"required_substeps",w.resolution.required_substeps},{"fits_256_substep_budget",w.resolution.fits_substep_budget},{"includes_contact_stiffness",false},{"material_validation",false}}},
        {"objects",objects},{"material_results",objects},{"cells",w.nodes.size()},{"links",w.bonds.size()},{"broken_links",w.broken},{"damaged_links",w.damaged},
        {"connected_components",std::set<unsigned>(groups.begin(),groups.end()).size()},{"pinned_cells",w.pinned},{"fracture_events",w.events},
        {"mechanical_energy_j",mechanics.mechanicalEnergy()},{"elastic_energy_j",w.elastic},{"fracture_work_j",w.fracture},{"plastic_work_j",w.plastic},
        {"energy_residual_j",nullptr},{"unreleased_fracture_energy_j",w.unreleased},{"unseparated_energy_change_j",mechanics.mechanicalEnergy()+w.elastic+w.fracture+w.plastic+w.unreleased-w.initial_energy},
        {"linear_momentum_kg_m_s",vec(mechanics.linear_momentum_kg_m_s)},{"angular_momentum_kg_m2_s",vec(mechanics.angular_momentum_kg_m2_s)},
        {"maximum_observed_axial_strain",w.maximum_strain},{"summed_spring_impulse_n_s",w.total_spring_impulse},
        {"maximum_reaction_geometric_extension_discrepancy_m",w.maximum_extension_discrepancy},
        {"runtime_limits",{{"cells",1024},{"links",20000},{"objects",32}}},
        {"limitations",{"Experimental central-force directional cohesive lattice; not a calibrated continuum or real tomato/wood prediction", "Cohesive state updates after each coupled spring/contact step; integration and damping/contact losses are not fully separated", "Cell sphere collision proxies leave subcell gaps; wedge sharpness below cell spacing unresolved", "All cells remain active representations; no automatic local refinement or rigid re-coarsening", "No fluid/pulp, skin pressure, full orthotropic shear/compression damage, hinge failure or live-state save", "Cell intrinsic spin is not coupled by center-to-center springs; finite-cell bending requires a richer connector"}}}.dump();
}
}
