#include "creator/CreatorWorld.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/RollingKinematics.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <fstream>
#include <numbers>
#include <set>
#include <map>
#include <stdexcept>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace banjo {
namespace {
using Json=nlohmann::json;
constexpr std::size_t max_document=1024*1024, max_objects=64;
constexpr std::size_t max_changes=256;
constexpr const char *authoring_policy="intact-return-100pct-v1";
bool finite(Vec3 v) { return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z); }
void check(bool value,std::string_view message) { if (!value) throw std::invalid_argument(std::string(message)); }
void fields(const Json &j,std::initializer_list<const char*> keys) {
    check(j.is_object()&&j.size()==keys.size(),"unexpected or missing fields");
    for (auto key:keys) check(j.contains(key),std::string("missing field: ")+key);
}
Json parse(std::string_view text) {
    check(text.size()<=max_document,"document exceeds 1 MiB");
    std::vector<std::set<std::string>> keys;
    return Json::parse(text,[&](int depth,Json::parse_event_t event,Json &value) {
        check(depth<=24,"document nesting exceeds 24");
        if (event==Json::parse_event_t::object_start) keys.emplace_back();
        if (event==Json::parse_event_t::key) check(keys.back().insert(value.get<std::string>()).second,"duplicate JSON field");
        if (event==Json::parse_event_t::object_end) keys.pop_back();
        return true;
    });
}
std::string string(const Json &j,std::size_t limit=128) {
    check(j.is_string(),"expected a string");auto result=j.get<std::string>();
    check(!result.empty()&&result.size()<=limit,"string length is outside its limit");
    check(std::none_of(result.begin(),result.end(),[](unsigned char c){return c<32;}),"control characters are not allowed");
    return result;
}
double number(const Json &j) { check(j.is_number(),"expected a number with the declared units");const double x=j.get<double>();check(std::isfinite(x),"number must be finite");return x; }
std::uint64_t integer(const Json &j,std::uint64_t maximum) {
    check(j.is_number_integer()&&!j.is_boolean(),"expected an integer");
    check(!j.is_number_integer()||j.is_number_unsigned()||j.get<std::int64_t>()>=0,"integer must be nonnegative");
    const auto x=j.get<std::uint64_t>();check(x<=maximum,"integer exceeds its limit");return x;
}
Json vector(Vec3 v) { return Json::array({v.x,v.y,v.z}); }
Vec3 vector(const Json &j) { check(j.is_array()&&j.size()==3,"expected a three-component vector");return {number(j[0]),number(j[1]),number(j[2])}; }
Json quaternion(Quat q) {return Json::array({q.w,q.x,q.y,q.z});}
Quat quaternion(const Json &j) {
    check(j.is_array()&&j.size()==4,"orientation requires four components");
    const Quat q{number(j[0]),number(j[1]),number(j[2]),number(j[3])};
    check(std::abs(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z-1)<1e-5,"orientation must be a unit quaternion");return q;
}
Json matrix(const Mat3 &m) {return m.m;}
MaterialPreset material(const Json &j) {
    const auto name=string(j);
    for (auto preset:kMaterialPresets) if (name==materialPresetName(preset)) return preset;
    throw std::invalid_argument("unknown material; use a material ID from inventory");
}
Json recipe(const ObjectRecipe &r) {
    Json shape={{"type",r.shape}};
    if(r.shape=="box")shape["dimensions_m"]=vector(r.dimensions_m);else shape["radius_m"]=r.radius_m;
    Json result={{"schema_version",r.schema_version},{"name",r.name},{"shape",shape},
        {"material",materialPresetName(r.material)},{"physics",r.physics},
        {"placement",{{"tangent_m",r.tangent_m},{"bitangent_m",r.bitangent_m},{"clearance_m",r.clearance_m}}},
        {"motion",{{"linear_velocity_m_s",vector(r.linear_velocity_m_s)},{"angular_velocity_rad_s",vector(r.angular_velocity_rad_s)}}}};
    if(r.schema_version==2)result["placement"]["orientation_wxyz"]=quaternion(r.orientation_world);
    return result;
}
ObjectRecipe recipe(const Json &j) {
    fields(j,{"schema_version","name","shape","material","physics","placement","motion"});
    const auto version=static_cast<unsigned>(integer(j.at("schema_version"),100));
    check(version==1||version==2,"unsupported object schema version");
    check(j.at("shape").is_object()&&j.at("shape").contains("type"),"shape requires a type");
    const auto type=string(j.at("shape").at("type"));
    check(type=="sphere"||(type=="box"&&version==2),"unsupported shape/version; use sphere or schema-2 box");
    if(type=="sphere")fields(j.at("shape"),{"type","radius_m"});else fields(j.at("shape"),{"type","dimensions_m"});
    if(version==1)fields(j.at("placement"),{"tangent_m","bitangent_m","clearance_m"});
    else fields(j.at("placement"),{"tangent_m","bitangent_m","clearance_m","orientation_wxyz"});
    fields(j.at("motion"),{"linear_velocity_m_s","angular_velocity_rad_s"});
    ObjectRecipe result{version,string(j.at("name"),80),type,
        string(j.at("physics")),material(j.at("material")),type=="sphere"?number(j.at("shape").at("radius_m")):.06,
        number(j.at("placement").at("tangent_m")),number(j.at("placement").at("bitangent_m")),number(j.at("placement").at("clearance_m")),
        vector(j.at("motion").at("linear_velocity_m_s")),vector(j.at("motion").at("angular_velocity_rad_s"))};
    if(type=="box")result.dimensions_m=vector(j.at("shape").at("dimensions_m"));
    if(version==2)result.orientation_world=quaternion(j.at("placement").at("orientation_wxyz"));
    return result;
}
CreationPreview compile(const ObjectRecipe &r,const CreatorSettings &settings) {
    check(r.schema_version==1||r.schema_version==2,"unsupported object schema version");
    check(r.shape=="sphere"||(r.shape=="box"&&r.schema_version==2),"unsupported shape/version; use sphere or schema-2 box");
    check(r.physics=="rigid-v1","unsupported physics; this version supports intact rigid-v1 objects, not deformation or fracture");
    (void)string(Json(r.name),80);
    check(std::find(kMaterialPresets.begin(),kMaterialPresets.end(),r.material)!=kMaterialPresets.end(),"invalid material ID");
    if(r.shape=="sphere")check(std::isfinite(r.radius_m)&&r.radius_m>=.025&&r.radius_m<=.5,"sphere radius must be 0.025–0.5 m");
    else check(finite(r.dimensions_m)&&std::min({r.dimensions_m.x,r.dimensions_m.y,r.dimensions_m.z})>=.025&&
        std::max({r.dimensions_m.x,r.dimensions_m.y,r.dimensions_m.z})<=1,"box dimensions must each be 0.025–1 m");
    (void)quaternion(quaternion(r.orientation_world));
    if(r.schema_version==1)check(r.orientation_world.w==1&&r.orientation_world.x==0&&r.orientation_world.y==0&&r.orientation_world.z==0,
        "authored orientation requires schema version 2");
    const auto geometry=r.geometry();const auto plane=makeSupportPlaneFromSlopeDegrees(settings.slope_degrees);
    check(std::isfinite(r.tangent_m)&&std::abs(r.tangent_m)<=8-geometry.extent(plane.tangent_world,r.orientation_world)&&
        std::isfinite(r.bitangent_m)&&std::abs(r.bitangent_m)<=3-geometry.extent(plane.bitangent_world,r.orientation_world),
        "placement must fit on the 16 by 6 m test surface");
    check(std::isfinite(r.clearance_m)&&r.clearance_m>=.002&&r.clearance_m<=3,"clearance must be 0.002–3 m above the surface");
    check(finite(r.linear_velocity_m_s)&&length(r.linear_velocity_m_s)<=5&&finite(r.angular_velocity_rad_s)&&length(r.angular_velocity_rad_s)<=50,
        "initial speed/spin exceeds the supported 5 m/s or 50 rad/s limit");
    const double volume=geometry.volume();
    const double mass=volume*makeReferenceMaterial(r.material).density_kg_m3;
    return {r,volume,mass,geometry.inertia(mass),
        pointInPlaneFrame(plane,r.tangent_m,r.bitangent_m,geometry.extent(plane.normal_world,r.orientation_world)+r.clearance_m),{}};
}
Json signature(unsigned version=2) {
    Json profiles=Json::array();
    for (auto p:kMaterialPresets) {
        const auto m=makeReferenceMaterial(p);const auto c=compileContactMaterial(m);
        profiles.push_back({{"id",materialPresetName(p)},{"density_kg_m3",m.density_kg_m3},
            {"static_friction",c.static_friction},{"dynamic_friction",c.dynamic_friction},{"rolling_resistance",c.rolling_resistance},
            {"restitution",c.restitution},{"contact_damping_ratio",c.contact_damping_ratio},
            {"young_modulus_pa",c.young_modulus_pa},{"poisson_ratio",c.poisson_ratio}});
    }
    return {{"object_compiler",version},{"runtime",version==1?"jolt-5.6/banjo-rigid-v1":"jolt-5.6/banjo-rigid-primitives-v2"},{"profiles",profiles}};
}
Json state(const RigidSnapshot &s) {
    return {{"position_m",vector(s.center_of_mass_world_m)},
        {"orientation_wxyz",Json::array({s.orientation_world.w,s.orientation_world.x,s.orientation_world.y,s.orientation_world.z})},
        {"linear_velocity_m_s",vector(s.linear_velocity_m_s)},{"angular_velocity_rad_s",vector(s.angular_velocity_rad_s)}};
}
RigidSnapshot state(const Json &j) {
    fields(j,{"position_m","orientation_wxyz","linear_velocity_m_s","angular_velocity_rad_s"});
    const auto &q=j.at("orientation_wxyz");check(q.is_array()&&q.size()==4,"orientation requires four components");
    RigidSnapshot s{vector(j.at("position_m")),{number(q[0]),number(q[1]),number(q[2]),number(q[3])},
        vector(j.at("linear_velocity_m_s")),vector(j.at("angular_velocity_rad_s"))};
    const auto &r=s.orientation_world;
    check(std::abs(r.w*r.w+r.x*r.x+r.y*r.y+r.z*r.z-1)<1e-5,"orientation is not a unit quaternion");
    check(length(s.center_of_mass_world_m)<1e6&&length(s.linear_velocity_m_s)<1e5&&length(s.angular_velocity_rad_s)<=1000.01,"saved motion exceeds supported bounds");
    return s;
}
Json allocations(const std::vector<MaterialAllocation> &values) {
    Json j=Json::array();for (const auto &a:values) j.push_back({{"lot_id",a.lot_id},{"mass_kg",a.mass_kg}});return j;
}
Json previewJson(const CreationPreview &p) {
    return {{"recipe",recipe(p.recipe)},{"volume_m3",p.volume_m3},{"required_mass_kg",p.mass_kg},
        {"inertia_kg_m2",p.recipe.shape=="sphere"?Json(p.inertia_local_kg_m2.m[0][0]):Json(nullptr)},
        {"inertia_local_kg_m2",matrix(p.inertia_local_kg_m2)},{"position_m",vector(p.position_world_m)},
        {"orientation_wxyz",quaternion(p.recipe.orientation_world)},{"allocations",allocations(p.allocations)},
        {"approximation","intact homogeneous rigid primitive; catalog contact coefficients are not calibrated substance behavior"}};
}
Json rebuildJson(const RebuildPreview &p) {
    auto j=previewJson(p.creation);j["object_id"]=p.object_id;j["expected_revision"]=p.expected_revision;
    j["reused"]=allocations(p.reused);j["withdrawn"]=allocations(p.withdrawn);j["returned"]=allocations(p.returned);
    j["policy"]=authoring_policy;j["state_change"]="Rebuild replaces the object at the recipe placement and initial motion; this is authoring, not a simulation step.";
    return j;
}
void applyAllocations(std::vector<ResourceLot> &lots,const std::vector<MaterialAllocation> &allocation,double sign) {
    for(const auto &a:allocation) {
        const auto lot=std::find_if(lots.begin(),lots.end(),[&](const auto &l){return l.id==a.lot_id;});
        check(lot!=lots.end(),"allocation lot is missing");
        const double amount=lot->remaining_mass_kg+sign*a.mass_kg,tolerance=1e-12*std::max(1.0,lot->initial_mass_kg);
        check(amount>=-tolerance&&amount<=lot->initial_mass_kg+tolerance,"material transaction exceeds its lot balance");
        lot->remaining_mass_kg=std::clamp(amount,0.0,lot->initial_mass_kg);
    }
}
void allocate(CreationPreview &plan,const std::vector<ResourceLot> &lots,const std::vector<MaterialAllocation> &preferred={}) {
    double remaining=plan.mass_kg;
    for(bool prefer:{true,false})for(const auto &lot:lots) {
        const bool matches=std::any_of(preferred.begin(),preferred.end(),[&](const auto &a){return a.lot_id==lot.id;});
        if(matches!=prefer||!lot.collected||lot.material!=plan.recipe.material||lot.remaining_mass_kg<=0||remaining<=0)continue;
        const double amount=std::min(remaining,lot.remaining_mass_kg);plan.allocations.push_back({lot.id,amount});remaining-=amount;
    }
    check(remaining<=0,"not enough collected or selected-object material; collect more or reduce the size");
}
Json objectJson(const CreatedObject &o) {
    return {{"id",o.id},{"request_id",o.request_id},{"recipe",recipe(o.recipe)},
        {"allocations",allocations(o.allocations)},{"state",state(o.state)},{"revision",o.revision}};
}
CreatedObject objectFromJson(const Json &j,const CreatorSettings &settings,const std::vector<ResourceLot> &lots,unsigned version=3) {
    if(version<3)fields(j,{"id","request_id","recipe","allocations","state"});
    else fields(j,{"id","request_id","recipe","allocations","state","revision"});
    const auto r=recipe(j.at("recipe"));const auto plan=compile(r,settings);
    check(version!=1||r.schema_version==1,"legacy worlds may contain only schema-1 spheres");
    CreatedObject o{integer(j.at("id"),max_changes),string(j.at("request_id")),r,plan.volume_m3,plan.mass_kg,
        plan.inertia_local_kg_m2,{},state(j.at("state")),version<3?1:integer(j.at("revision"),max_changes)};
    check(o.id>0&&o.revision>0,"object identity and revision must be positive");
    const auto &parts=j.at("allocations");check(parts.is_array()&&!parts.empty()&&parts.size()<=lots.size(),"invalid material allocations");
    std::set<std::string> ids;double allocated=0;
    for(const auto &part:parts) {
        fields(part,{"lot_id","mass_kg"});MaterialAllocation a{string(part.at("lot_id")),number(part.at("mass_kg"))};
        const auto lot=std::find_if(lots.begin(),lots.end(),[&](const auto &l){return l.id==a.lot_id;});
        check(lot!=lots.end()&&lot->collected&&lot->material==r.material&&a.mass_kg>0&&ids.insert(a.lot_id).second,"allocation does not match collected material provenance");
        allocated+=a.mass_kg;o.allocations.push_back(a);
    }
    check(std::abs(allocated-o.mass_kg)<=1e-12*std::max(1.0,o.mass_kg),"allocated matter differs from compiled mass");return o;
}
bool sameObjectDefinition(const CreatedObject &a,const CreatedObject &b) {
    auto x=objectJson(a),y=objectJson(b);x.erase("state");y.erase("state");return x==y;
}
Json totalsJson(const MechanicalTotals &m) {
    return {{"mass_kg",m.mass_kg},{"first_moment_kg_m",vector(m.mass_first_moment_kg_m)},
        {"linear_momentum_kg_m_s",vector(m.linear_momentum_kg_m_s)},{"angular_momentum_kg_m2_s",vector(m.angular_momentum_kg_m2_s)},
        {"kinetic_energy_j",m.kinetic_energy_j},{"potential_energy_j",m.gravitational_potential_energy_j}};
}
MechanicalTotals totalsFromJson(const Json &j) {
    fields(j,{"mass_kg","first_moment_kg_m","linear_momentum_kg_m_s","angular_momentum_kg_m2_s","kinetic_energy_j","potential_energy_j"});
    MechanicalTotals m;m.mass_kg=number(j.at("mass_kg"));m.mass_first_moment_kg_m=vector(j.at("first_moment_kg_m"));
    m.linear_momentum_kg_m_s=vector(j.at("linear_momentum_kg_m_s"));m.angular_momentum_kg_m2_s=vector(j.at("angular_momentum_kg_m2_s"));
    m.kinetic_energy_j=number(j.at("kinetic_energy_j"));m.gravitational_potential_energy_j=number(j.at("potential_energy_j"));
    check(m.mass_kg>=0&&m.kinetic_energy_j>=0,"mechanics mass and kinetic energy cannot be negative");return m;
}
void validateTotals(const MechanicalTotals &actual,const std::optional<CreatedObject> &o,Vec3 gravity) {
    const auto expected=o?measureRigidMechanics({o->state,o->mass_kg,rotateInertia(o->inertia_local_kg_m2,o->state.orientation_world)},gravity):MechanicalTotals{};
    const auto check_scalar=[](double a,double b){check(std::abs(a-b)<=2e-6*std::max(1.0,std::abs(b)),"authoring mechanics disagree with recorded matter/state");};
    const auto check_vector=[&](Vec3 a,Vec3 b){check_scalar(a.x,b.x);check_scalar(a.y,b.y);check_scalar(a.z,b.z);};
    check_scalar(actual.mass_kg,expected.mass_kg);check_scalar(actual.kinetic_energy_j,expected.kinetic_energy_j);
    check_scalar(actual.gravitational_potential_energy_j,expected.gravitational_potential_energy_j);
    check_vector(actual.mass_first_moment_kg_m,expected.mass_first_moment_kg_m);check_vector(actual.linear_momentum_kg_m_s,expected.linear_momentum_kg_m_s);
    check_vector(actual.angular_momentum_kg_m2_s,expected.angular_momentum_kg_m2_s);
}
Json changeJson(const AuthoringChange &c) {
    return {{"request_id",c.request_id},{"operation",c.operation},{"object_id",c.object_id},{"expected_revision",c.expected_revision},{"tick",c.tick},
        {"before",c.before?objectJson(*c.before):Json(nullptr)},{"after",c.after?objectJson(*c.after):Json(nullptr)},
        {"mechanics_before",totalsJson(c.before_mechanics)},{"mechanics_after",totalsJson(c.after_mechanics)}};
}
std::string readFile(const std::filesystem::path &path) {
    check(std::filesystem::file_size(path)<=max_document,"file exceeds 1 MiB");
    std::ifstream input(path,std::ios::binary);check(bool(input),"cannot open file");
    std::string text;char c;while (input.get(c)) {check(text.size()<max_document,"file exceeds 1 MiB");text+=c;}return text;
}
}

RigidPrimitive ObjectRecipe::geometry() const {
    if(shape=="sphere")return {PrimitiveKind::Sphere,radius_m,{}};
    if(shape=="box")return {PrimitiveKind::Box,0,dimensions_m};
    throw std::invalid_argument("unsupported geometry");
}
CreatorMotion measureCreatorMotion(const CreatedObject &object,const SupportPlaneFrame &plane) {
    const auto &s=object.state;const auto geometry=object.recipe.geometry();
    if(geometry.kind==PrimitiveKind::Sphere) {
        const auto m=measureRollingKinematics(s,geometry.radius_m,plane,insideSupportFootprint(plane,s.center_of_mass_world_m,8,3));
        return {std::string(rollingStateName(m.state)),m.translation_speed_m_s,m.contact_slip_speed_m_s,
            signedDistanceToPlane(plane,s.center_of_mass_world_m)-geometry.radius_m,m.state==RollingState::Airborne?0U:1U};
    }
    CreatorMotion result{"no top-support sample",length(projectVectorOntoPlane(plane,s.linear_velocity_m_s)),0,
        signedDistanceToPlane(plane,s.center_of_mass_world_m)-geometry.extent(plane.normal_world,s.orientation_world),0};
    double slip_squared=0;
    for(const auto local:geometry.corners()) {
        const auto arm=s.orientation_world.rotate(local),point=s.center_of_mass_world_m+arm;
        if(std::abs(signedDistanceToPlane(plane,point))<=.003&&insideSupportFootprint(plane,point,8,3)) {
            slip_squared+=lengthSquared(projectVectorOntoPlane(plane,s.linear_velocity_m_s+cross(s.angular_velocity_rad_s,arm)));
            ++result.near_support_points;
        }
    }
    if(result.near_support_points) {
        result.slip_m_s=std::sqrt(slip_squared/result.near_support_points);
        if(result.speed_m_s<.02&&length(s.angular_velocity_rad_s)*length(geometry.dimensions_m)/2<.02)result.state="resting";
        else if(result.slip_m_s>.02)result.state="sliding / slipping";
        else result.state="rotating on support";
    }
    return result;
}
namespace {
void insertObject(JoltWorld &world,const CreatedObject &o) {
    if(o.recipe.shape=="box")world.addBox({o.id,o.recipe.dimensions_m,makeReferenceMaterial(o.recipe.material),o.state});
    else {
        world.addBall({.body_id=o.id,.radius_m=o.recipe.radius_m,.material=makeReferenceMaterial(o.recipe.material),
            .position_world_m=o.state.center_of_mass_world_m,.linear_velocity_m_s=o.state.linear_velocity_m_s,
            .angular_velocity_rad_s=o.state.angular_velocity_rad_s,.mass_override_kg=o.mass_kg});
        world.applyRigidState(o.id,o.state);
    }
}
}

CreatorWorld::CreatorWorld(CreatorSettings settings):settings_(settings) {
    check(std::isfinite(settings.slope_degrees)&&std::abs(settings.slope_degrees)<=30,"sandbox slope must be within 30 degrees");
    check(finite(settings.gravity_m_s2)&&length(settings.gravity_m_s2)<=30,"sandbox gravity exceeds 30 m/s²");
    check(std::find(kMaterialPresets.begin(),kMaterialPresets.end(),settings.surface)!=kMaterialPresets.end(),"unknown surface material");
    for (auto p:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})
        lots_.push_back({std::string(materialPresetName(p))+"-pile","starter-world/pickup-v1",p,10,10,false});
    world_=std::make_unique<JoltWorld>();world_->setGravity(settings.gravity_m_s2);
    world_->addSupportSurface({.frame=support(),.material=makeReferenceMaterial(settings.surface),.half_length_tangent_m=8,.half_length_bitangent_m=3});
}
CreatorWorld::~CreatorWorld()=default;
CreatorWorld::CreatorWorld(CreatorWorld &&) noexcept=default;
CreatorWorld &CreatorWorld::operator=(CreatorWorld &&) noexcept=default;
SupportPlaneFrame CreatorWorld::support() const {return makeSupportPlaneFromSlopeDegrees(settings_.slope_degrees);}
double CreatorWorld::inventoryMass(MaterialPreset m) const { double amount=0;for (const auto &lot:lots_) if (lot.collected&&lot.material==m) amount+=lot.remaining_mass_kg;return amount; }
RigidMechanicalState CreatorWorld::mechanicalState(MatterBodyId id) const {return world_->mechanicalState(id);}
bool CreatorWorld::collect(std::string_view id) {
    auto found=std::find_if(lots_.begin(),lots_.end(),[&](const auto &lot){return lot.id==id;});
    check(found!=lots_.end(),"pickup is not in this world");if (found->collected)return false;found->collected=true;return true;
}
CreationPreview CreatorWorld::preview(const ObjectRecipe &r) const {
    auto result=compile(r,settings_);check(objects_.size()<max_objects,"world object budget of 64 is exhausted");
    check(history_.size()<max_changes,"authoring history budget of 256 operations is exhausted");
    for (const auto &object:objects_) check(!primitivesOverlap(object.recipe.geometry(),object.state.center_of_mass_world_m,object.state.orientation_world,
        r.geometry(),result.position_world_m,r.orientation_world),
        "placement overlaps an existing object; choose another location");
    allocate(result,lots_);
    return result;
}
MatterBodyId CreatorWorld::create(std::string request_id,const ObjectRecipe &r) {
    (void)string(Json(request_id));
    if(const auto *prior=receipt(request_id)) {
        check((prior->operation=="create"||prior->operation=="import")&&prior->after&&recipe(prior->after->recipe)==recipe(r),
            "request ID was already used for a different operation or specification");return prior->object_id;
    }
    const auto plan=preview(r);
    auto next_lots=lots_;auto next_objects=objects_;
    applyAllocations(next_lots,plan.allocations,-1);
    const auto id=next_object_id_;
    next_objects.push_back({id,request_id,r,plan.volume_m3,plan.mass_kg,plan.inertia_local_kg_m2,plan.allocations,
        {plan.position_world_m,r.orientation_world,r.linear_velocity_m_s,r.angular_velocity_rad_s}});
    AuthoringChange change{request_id,"create",id,0,ticks_,{},next_objects.back()};
    publish(std::move(next_lots),std::move(next_objects),std::move(change),id+1);return id;
}
const CreatedObject &CreatorWorld::targetObject(RevisionTarget target) const {
    const auto found=std::find_if(objects_.begin(),objects_.end(),[&](const auto &o){return o.id==target.object_id;});
    check(found!=objects_.end(),"selected object no longer exists");
    check(found->revision==target.expected_revision,"selected object revision is stale; inspect it again");return *found;
}
const AuthoringChange *CreatorWorld::receipt(std::string_view request_id) const {
    const auto found=std::find_if(history_.begin(),history_.end(),[&](const auto &c){return c.request_id==request_id;});
    return found==history_.end()?nullptr:&*found;
}
RebuildPreview CreatorWorld::previewRebuild(RevisionTarget target,const ObjectRecipe &r) const {
    const auto &old=targetObject(target);check(history_.size()<max_changes,"authoring history budget of 256 operations is exhausted");
    RebuildPreview result{compile(r,settings_),target.object_id,target.expected_revision};
    for(const auto &o:objects_)if(o.id!=old.id)check(!primitivesOverlap(o.recipe.geometry(),o.state.center_of_mass_world_m,o.state.orientation_world,
        r.geometry(),result.creation.position_world_m,r.orientation_world),"replacement placement overlaps another object");
    auto available=lots_;applyAllocations(available,old.allocations,1);allocate(result.creation,available,old.allocations);
    for(const auto &lot:lots_) {
        const auto amount=[&](const auto &parts){double value=0;for(const auto &p:parts)if(p.lot_id==lot.id)value+=p.mass_kg;return value;};
        const double prior=amount(old.allocations),next=amount(result.creation.allocations),reuse=std::min(prior,next);
        if(reuse>0)result.reused.push_back({lot.id,reuse});
        if(next>prior)result.withdrawn.push_back({lot.id,next-prior});
        if(prior>next)result.returned.push_back({lot.id,prior-next});
    }
    return result;
}
MatterBodyId CreatorWorld::rebuild(std::string request_id,RevisionTarget target,const ObjectRecipe &r) {
    (void)string(Json(request_id));
    if(const auto *prior=receipt(request_id)) {
        check(prior->operation=="rebuild"&&prior->object_id==target.object_id&&prior->expected_revision==target.expected_revision&&
            prior->after&&recipe(prior->after->recipe)==recipe(r),"request ID was already used for a different operation or specification");return prior->object_id;
    }
    const auto plan=previewRebuild(target,r);auto old=targetObject(target);
    old.state=world_->snapshot(old.id);
    auto next_lots=lots_;applyAllocations(next_lots,old.allocations,1);applyAllocations(next_lots,plan.creation.allocations,-1);
    auto next_objects=objects_;auto &replacement=*std::find_if(next_objects.begin(),next_objects.end(),[&](const auto &o){return o.id==old.id;});
    const auto &p=plan.creation;
    replacement={old.id,old.request_id,r,p.volume_m3,p.mass_kg,p.inertia_local_kg_m2,p.allocations,
        {p.position_world_m,r.orientation_world,r.linear_velocity_m_s,r.angular_velocity_rad_s},old.revision+1};
    AuthoringChange change{request_id,"rebuild",old.id,target.expected_revision,ticks_,old,replacement,
        measureRigidMechanics(world_->mechanicalState(old.id),settings_.gravity_m_s2)};
    publish(std::move(next_lots),std::move(next_objects),std::move(change),next_object_id_);return old.id;
}
void CreatorWorld::reclaim(std::string request_id,RevisionTarget target) {
    (void)string(Json(request_id));
    if(const auto *prior=receipt(request_id)) {
        check(prior->operation=="reclaim"&&prior->object_id==target.object_id&&prior->expected_revision==target.expected_revision,
            "request ID was already used for a different operation");return;
    }
    check(history_.size()<max_changes,"authoring history budget of 256 operations is exhausted");
    auto old=targetObject(target);old.state=world_->snapshot(old.id);
    auto next_lots=lots_;applyAllocations(next_lots,old.allocations,1);
    auto next_objects=objects_;std::erase_if(next_objects,[&](const auto &o){return o.id==old.id;});
    AuthoringChange change{request_id,"reclaim",old.id,target.expected_revision,ticks_,old,{},
        measureRigidMechanics(world_->mechanicalState(old.id),settings_.gravity_m_s2)};
    publish(std::move(next_lots),std::move(next_objects),std::move(change),next_object_id_);
}
void CreatorWorld::publish(std::vector<ResourceLot> lots,std::vector<CreatedObject> objects,AuthoringChange change,MatterBodyId next_id) {
    // Build a private candidate, including its complete rigid runtime. Failure
    // never removes the old body or releases inventory. This authoring boundary
    // rebuilds solver contact caches; it does not advance the simulation clock.
    CreatorWorld candidate(settings_);candidate.lots_=std::move(lots);candidate.objects_=std::move(objects);
    candidate.ticks_=ticks_;candidate.next_object_id_=next_id;candidate.history_=history_;
    for(auto &o:candidate.objects_) {insertObject(*candidate.world_,o);o.state=candidate.world_->snapshot(o.id);}
    if(change.after) {
        change.after=candidate.targetObject({change.object_id,change.after->revision});
        change.after_mechanics=measureRigidMechanics(candidate.world_->mechanicalState(change.object_id),settings_.gravity_m_s2);
    }
    candidate.history_.push_back(std::move(change));
    check(candidate.serialize().size()<=max_document,"operation would exceed the 1 MiB saved-world budget");
    *this=std::move(candidate);
}
void CreatorWorld::step(unsigned ticks) {
    check(ticks<=2400,"one command may advance at most 10 seconds");
    for (unsigned i=0;i<ticks;++i) {
        world_->step(1.0/240);++ticks_;
        for (auto &object:objects_) object.state=world_->snapshot(object.id);
        (void)world_->drainImpacts(); // Rigid-only mode has no material activation.
    }
}
ObjectRecipe CreatorWorld::parseRecipe(std::string_view document) {return recipe(parse(document));}
std::string CreatorWorld::recipeJson(const ObjectRecipe &r) {return recipe(r).dump(2);}
CreatorProposal CreatorWorld::parseProposal(std::string_view document) {
    const auto j=parse(document);fields(j,{"request_id","explanation","recipe"});
    return {string(j.at("request_id")),string(j.at("explanation"),512),recipe(j.at("recipe"))};
}
std::string CreatorWorld::serialize() const {
    Json lots=Json::array(),objects=Json::array(),history=Json::array();
    for (const auto &lot:lots_) lots.push_back({{"id",lot.id},{"provenance",lot.provenance},{"material",materialPresetName(lot.material)},
        {"initial_mass_kg",lot.initial_mass_kg},{"remaining_mass_kg",lot.remaining_mass_kg},{"collected",lot.collected}});
    for(const auto &o:objects_)objects.push_back(objectJson(o));
    for(const auto &c:history_)history.push_back(changeJson(c));
    return Json{{"world_version",3},{"physics_signature",signature()},{"authoring_policy",authoring_policy},
        {"settings",{{"slope_degrees",settings_.slope_degrees},{"gravity_m_s2",vector(settings_.gravity_m_s2)},{"surface",materialPresetName(settings_.surface)}}},
        {"ticks",ticks_},{"lots",lots},{"objects",objects},{"history",history},{"next_object_id",next_object_id_}}.dump(2);
}
CreatorWorld CreatorWorld::deserialize(std::string_view document) {
    const auto j=parse(document);check(j.is_object()&&j.contains("world_version"),"world version is required");
    const auto version=integer(j.at("world_version"),100);
    check(version>=1&&version<=3,"incompatible world version");
    if(version<3)fields(j,{"world_version","physics_signature","settings","ticks","lots","objects"});
    else fields(j,{"world_version","physics_signature","settings","ticks","lots","objects","authoring_policy","history","next_object_id"});
    check(j.at("physics_signature")==signature(version==1?1:2),"saved material/runtime signature differs; explicit migration is required");
    if(version==3)check(j.at("authoring_policy")==authoring_policy,"unsupported authoring recovery policy");
    const auto &s=j.at("settings");fields(s,{"slope_degrees","gravity_m_s2","surface"});
    const CreatorSettings config{number(s.at("slope_degrees")),vector(s.at("gravity_m_s2")),material(s.at("surface"))};
    const auto &lots=j.at("lots"),&objects=j.at("objects");
    check(lots.is_array()&&!lots.empty()&&lots.size()<=128,"world must have 1–128 material lots");
    check(objects.is_array()&&objects.size()<=max_objects,"saved object budget exceeds 64");
    CreatorWorld world(config);world.lots_.clear();world.ticks_=integer(j.at("ticks"),240ULL*60*60*24*365);
    std::set<std::string> lot_ids,request_ids;
    for (const auto &value:lots) {
        fields(value,{"id","provenance","material","initial_mass_kg","remaining_mass_kg","collected"});
        ResourceLot lot{string(value.at("id")),string(value.at("provenance")),material(value.at("material")),
            number(value.at("initial_mass_kg")),number(value.at("remaining_mass_kg")),false};
        check(value.at("collected").is_boolean(),"collected flag must be boolean");lot.collected=value.at("collected").get<bool>();
        check(lot_ids.insert(lot.id).second,"duplicate material lot ID");
        check(lot.initial_mass_kg>0&&lot.initial_mass_kg<=1e6&&lot.remaining_mass_kg>=0&&lot.remaining_mass_kg<=lot.initial_mass_kg,"invalid lot quantity");
        world.lots_.push_back(lot);
    }
    std::vector<double> used(world.lots_.size());
    for (const auto &value:objects) {
        auto object=objectFromJson(value,config,world.lots_,static_cast<unsigned>(version));
        check((world.objects_.empty()||object.id>world.objects_.back().id)&&request_ids.insert(object.request_id).second,"duplicate or unordered object/request ID");
        if(version<3)check(object.id==world.objects_.size()+1,"legacy object IDs must be sequential");
        for(const auto &a:object.allocations) {
            const auto lot=std::find_if(world.lots_.begin(),world.lots_.end(),[&](const auto &v){return v.id==a.lot_id;});
            used[static_cast<std::size_t>(lot-world.lots_.begin())]+=a.mass_kg;
        }
        world.objects_.push_back(std::move(object));
    }
    for (std::size_t i=0;i<world.lots_.size();++i) {
        const auto &lot=world.lots_[i];check(std::abs(lot.remaining_mass_kg+used[i]-lot.initial_mass_kg)<=1e-12*std::max(1.0,lot.initial_mass_kg),"saved inventory/object mass ledger is inconsistent");
    }
    if(version==3) {
        const auto &records=j.at("history");check(records.is_array()&&records.size()<=max_changes,"authoring history exceeds its budget");
        auto replay_lots=world.lots_;for(auto &l:replay_lots)l.remaining_mass_kg=l.initial_mass_kg;
        std::map<MatterBodyId,CreatedObject> live;std::set<std::string> receipts;MatterBodyId last_id=0;
        std::uint64_t last_tick=0;bool authored=false;
        for(const auto &value:records) {
            fields(value,{"request_id","operation","object_id","expected_revision","tick","before","after","mechanics_before","mechanics_after"});
            AuthoringChange c{string(value.at("request_id")),string(value.at("operation")),integer(value.at("object_id"),max_changes),
                integer(value.at("expected_revision"),max_changes),integer(value.at("tick"),world.ticks_)};
            check(receipts.insert(c.request_id).second&&c.tick>=last_tick,"duplicate authoring request or reversed history clock");last_tick=c.tick;
            if(!value.at("before").is_null())c.before=objectFromJson(value.at("before"),config,world.lots_);
            if(!value.at("after").is_null())c.after=objectFromJson(value.at("after"),config,world.lots_);
            c.before_mechanics=totalsFromJson(value.at("mechanics_before"));c.after_mechanics=totalsFromJson(value.at("mechanics_after"));
            validateTotals(c.before_mechanics,c.before,config.gravity_m_s2);validateTotals(c.after_mechanics,c.after,config.gravity_m_s2);
            if(c.operation=="create"||c.operation=="import") {
                if(c.operation=="import")check(!authored,"imported baseline must precede new operations");else authored=true;
                check(!c.before&&c.after&&c.expected_revision==0&&c.object_id==++last_id&&c.after->id==c.object_id&&
                    c.after->revision==1&&c.after->request_id==c.request_id,"invalid creation/import receipt");
            }else {
                authored=true;
                check((c.operation=="rebuild"||c.operation=="reclaim")&&c.before&&live.contains(c.object_id),"invalid authoring operation or missing prior object");
                check(c.before->id==c.object_id&&c.before->revision==c.expected_revision&&sameObjectDefinition(*c.before,live.at(c.object_id)),"authoring revision chain is inconsistent");
                if(c.operation=="rebuild")check(c.after&&c.after->id==c.object_id&&c.after->revision==c.expected_revision+1&&c.after->request_id==c.before->request_id,"invalid replacement identity");
                else check(!c.after,"reclamation cannot keep an active replacement");
                applyAllocations(replay_lots,c.before->allocations,1);live.erase(c.object_id);
            }
            if(c.after) {
                applyAllocations(replay_lots,c.after->allocations,-1);live.emplace(c.object_id,*c.after);
                if(c.operation!="import") {
                    const auto plan=compile(c.after->recipe,config);const auto &motion=c.after->state;
                    check(length(motion.center_of_mass_world_m-plan.position_world_m)<2e-6&&
                        length(motion.linear_velocity_m_s-c.after->recipe.linear_velocity_m_s)<2e-6&&
                        length(motion.angular_velocity_rad_s-c.after->recipe.angular_velocity_rad_s)<1e-5,"created state differs from the accepted recipe");
                    const auto q=motion.orientation_world,r=c.after->recipe.orientation_world;
                    check(std::abs(std::abs(q.w*r.w+q.x*r.x+q.y*r.y+q.z*r.z)-1)<1e-5,"created orientation differs from the accepted recipe");
                }
            }
            world.history_.push_back(std::move(c));
        }
        world.next_object_id_=integer(j.at("next_object_id"),max_changes+1);
        check(world.next_object_id_==last_id+1&&live.size()==world.objects_.size(),"object ID counter or active history is inconsistent");
        for(const auto &o:world.objects_)check(live.contains(o.id)&&sameObjectDefinition(o,live.at(o.id)),"active object disagrees with authoring history");
        for(std::size_t i=0;i<world.lots_.size();++i)check(std::abs(replay_lots[i].remaining_mass_kg-world.lots_[i].remaining_mass_kg)<=
            1e-12*std::max(1.0,world.lots_[i].initial_mass_kg),"saved balances disagree with authoring history");
    }else world.next_object_id_=world.objects_.size()+1;
    for(const auto &o:world.objects_) {
        insertObject(*world.world_,o);
        if(version<3)world.history_.push_back({o.request_id,"import",o.id,0,world.ticks_,{},o,{},measureRigidMechanics(world.world_->mechanicalState(o.id),config.gravity_m_s2)});
    }
    return world;
}
void CreatorWorld::save(const std::filesystem::path &path) const {
    const auto text=serialize();check(text.size()<=max_document,"saved world exceeds document budget");
    auto temporary=path;temporary+=".pending";
    check(!std::filesystem::exists(temporary),"a pending save already exists; preserve it before retrying");
    try {
        std::ofstream output(temporary,std::ios::binary);check(bool(output),"cannot open pending save");output<<text;output.flush();check(bool(output),"failed to write pending save");output.close();check(bool(output),"failed to close pending save");
#ifdef _WIN32
        check(MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)!=0,"cannot publish saved world");
#else
        std::filesystem::rename(temporary,path);
#endif
    } catch (...) { std::error_code error;std::filesystem::remove(temporary,error);throw; }
}
CreatorWorld CreatorWorld::load(const std::filesystem::path &path) {return deserialize(readFile(path));}
std::string CreatorWorld::inspectJson() const {
    auto result=parse(serialize());result["time_s"]=timeSeconds();
    result["capabilities"]={{"shapes",Json::array({"sphere","box"})},{"physics",Json::array({"rigid-v1"})},
        {"unsupported",Json::array({"deformation","fracture","wood grain","metal plasticity","assemblies","energy-limited fabrication","manufacturing","damage repair"})},
        {"limits",{{"objects",max_objects},{"radius_m",Json::array({.025,.5})},{"box_dimensions_m",Json::array({.025,1})},{"initial_speed_m_s",5},{"initial_spin_rad_s",50}}},
        {"orientation","schema-2 placement.orientation_wxyz is a unit quaternion in world coordinates; box dimensions_m are full local x/y/z lengths"},
        {"support_frame",{{"normal_world",vector(support().normal_world)},{"tangent_world",vector(support().tangent_world)},{"bitangent_world",vector(support().bitangent_world)}}}};
    result["capabilities"]["authoring"]={{"operations",Json::array({"create","rebuild","reclaim"})},{"policy",authoring_policy},
        {"history_limit",max_changes},{"note","Rebuild/reclaim are explicit authoring operations with full intact material recovery and before/after mechanics; no manufacturing process or damage repair is simulated."}};
    result["capabilities"]["energy"]={{"fabrication_supported",false},{"mode","authoring-sandbox"},
        {"note","No fabrication energy source, cost or power limit is implemented. Before/after mechanical quantities record authoring discontinuities; they do not pay for construction."}};
    result["history_count"]=history_.size();
    result["inventory"]=Json::array();for (auto m:kMaterialPresets) if (inventoryMass(m)>0) result["inventory"].push_back({{"material",materialPresetName(m)},{"mass_kg",inventoryMass(m)}});
    for (std::size_t i=0;i<objects_.size();++i) {
        const auto &object=objects_[i];auto &j=result["objects"][i];
        const auto motion=measureCreatorMotion(object,support());const auto measured=world_->mechanicalState(object.id);
        const auto totals=measureRigidMechanics(measured,settings_.gravity_m_s2);
        j["mass_kg"]=object.mass_kg;j["volume_m3"]=object.volume_m3;
        j["inertia_kg_m2"]=object.recipe.shape=="sphere"?Json(object.inertia_local_kg_m2.m[0][0]):Json(nullptr);
        j["inertia_local_kg_m2"]=matrix(object.inertia_local_kg_m2);j["solver_inertia_world_kg_m2"]=matrix(measured.inertia_world_kg_m2);
        j["motion_state"]=motion.state;j["contact_slip_m_s"]=motion.near_support_points?Json(motion.slip_m_s):Json(nullptr);
        j["support_gap_m"]=motion.support_gap_m;j["near_support_points"]=motion.near_support_points;
        j["motion_diagnostic"]=object.recipe.shape=="sphere"?"sphere/top-plane kinematics":"RMS slip at box vertices within 3 mm of finite top support; edge/side manifolds not measured";
        j["kinetic_energy_j"]=totals.kinetic_energy_j;j["linear_momentum_kg_m_s"]=vector(totals.linear_momentum_kg_m_s);
        j["angular_momentum_kg_m2_s"]=vector(totals.angular_momentum_kg_m2_s);
    }
    return result.dump(2);
}
std::string CreatorWorld::executeJson(std::string_view commands) {
    const auto input=parse(commands);const bool batch=input.is_array();
    check(!batch||input.size()<=128,"command batch exceeds 128");Json results=Json::array();
    for (const auto &command:batch ? input : Json::array({input})) {
        try {
            check(command.is_object()&&command.contains("type"),"command requires a type");const auto type=string(command.at("type"));Json value;
            if (type=="inspect") {fields(command,{"type"});value=parse(inspectJson());}
            else if (type=="collect") {fields(command,{"type","lot_id"});value={{"collected",collect(string(command.at("lot_id")))}};}
            else if (type=="preview") {fields(command,{"type","recipe"});value=previewJson(preview(recipe(command.at("recipe"))));}
            else if (type=="create") {fields(command,{"type","request_id","recipe"});value={{"object_id",create(string(command.at("request_id")),recipe(command.at("recipe")))}};}
            else if(type=="preview_rebuild"||type=="rebuild") {
                if(type=="rebuild")fields(command,{"type","request_id","object_id","expected_revision","recipe"});
                else fields(command,{"type","object_id","expected_revision","recipe"});
                const RevisionTarget target{integer(command.at("object_id"),max_changes),integer(command.at("expected_revision"),max_changes)};
                const auto r=recipe(command.at("recipe"));
                if(type=="rebuild")value={{"object_id",rebuild(string(command.at("request_id")),target,r)}};
                else value=rebuildJson(previewRebuild(target,r));
            }
            else if(type=="reclaim") {
                fields(command,{"type","request_id","object_id","expected_revision"});
                const RevisionTarget target{integer(command.at("object_id"),max_changes),integer(command.at("expected_revision"),max_changes)};
                reclaim(string(command.at("request_id")),target);value={{"object_id",target.object_id},{"reclaimed",true}};
            }
            else if (type=="step") {fields(command,{"type","ticks"});step(static_cast<unsigned>(integer(command.at("ticks"),2400)));value={{"time_s",timeSeconds()}};}
            else throw std::invalid_argument("unsupported command");
            results.push_back({{"ok",true},{"result",value}});
        } catch (const std::exception &error) {results.push_back({{"ok",false},{"error",error.what()}});}
    }
    return (batch ? results : results.at(0)).dump(2);
}
}
