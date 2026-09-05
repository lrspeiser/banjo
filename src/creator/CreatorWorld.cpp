#include "creator/CreatorWorld.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/RollingKinematics.hpp"
#include "physics/CohesiveRigidPair.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <fstream>
#include <numbers>
#include <set>
#include <map>
#include <tuple>
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
Json signature(unsigned version=2,bool include_precision=true) {
    Json profiles=Json::array();
    for (auto p:kMaterialPresets) {
        const auto m=makeReferenceMaterial(p);const auto c=compileContactMaterial(m);
        profiles.push_back({{"id",materialPresetName(p)},{"density_kg_m3",m.density_kg_m3},
            {"static_friction",c.static_friction},{"dynamic_friction",c.dynamic_friction},{"rolling_resistance",c.rolling_resistance},
            {"restitution",c.restitution},{"contact_damping_ratio",c.contact_damping_ratio},
            {"young_modulus_pa",c.young_modulus_pa},{"poisson_ratio",c.poisson_ratio}});
    }
    Json result={{"object_compiler",version},{"runtime",version==1?"jolt-5.6/banjo-rigid-v1":"jolt-5.6/banjo-rigid-primitives-v3-analytic-box"},{"profiles",profiles}};
    if(include_precision)result["position_bits"]=JoltWorld::positionPrecisionBits();
    return result;
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
std::string CreatorWorld::testRecipeJson(const ObjectRecipe &original,std::string_view specification) {
    const auto test=parse(specification);fields(test,{"test_version","fixture","ticks","slope_degrees","minimum_travel_m","maximum_final_slip_m_s","require_rolling"});
    check(integer(test.at("test_version"),1)==1,"unsupported test version");
    check(string(test.at("fixture"))=="concrete-incline-v1","unsupported test fixture");
    const auto ticks=integer(test.at("ticks"),1200);check(ticks>=24,"test needs at least 24 ticks");
    const double slope=number(test.at("slope_degrees")),minimum=number(test.at("minimum_travel_m")),slip_limit=number(test.at("maximum_final_slip_m_s"));
    check(slope>=0&&slope<=20&&minimum>=0&&minimum<=10&&slip_limit>=0&&slip_limit<=5,"test criteria exceed limits");
    check(test.at("require_rolling").is_boolean(),"require_rolling must be boolean");
    const bool require_rolling=test.at("require_rolling").get<bool>();
    (void)compile(original,{}); // Reject malformed declarations before applying fixture state.
    Json report{{"result_version",1},{"recipe",parse(recipeJson(original))},{"test",test},{"physics_signature",signature()},
        {"boundary","One virtual rigid object on a fixed concrete incline, gravity [0,-9.81,0]. No live inventory, objects, progress or clock are changed. Placement and initial motion are explicitly replaced by the fixture; geometry/material/orientation are retained."},
        {"limitations","Endpoint predicates and sampled kinematics only; not general functional certification. No deformation, fracture, manufacturing energy, support reaction/work or calibrated material realism. Box slip samples only vertices near the top plane."}};
    if(require_rolling&&original.shape!="sphere") {report["status"]="unsupported";report["reason"]="A rolling predicate is supported only for spheres; box rotation is not sphere rolling.";return report.dump(2);}
    ObjectRecipe fixture=original;fixture.tangent_m=-2;fixture.bitangent_m=0;fixture.clearance_m=.002;fixture.linear_velocity_m_s={};fixture.angular_velocity_rad_s={};
    const CreatorSettings settings{.slope_degrees=slope};const auto plan=compile(fixture,settings);const auto plane=makeSupportPlaneFromSlopeDegrees(slope);
    JoltWorld trial;trial.setGravity(settings.gravity_m_s2);trial.addSupportSurface({.frame=plane,.material=makeReferenceMaterial(MaterialPreset::Concrete),.half_length_tangent_m=8,.half_length_bitangent_m=3});
    CreatedObject object;object.id=1;object.recipe=fixture;object.mass_kg=plan.mass_kg;object.volume_m3=plan.volume_m3;object.inertia_local_kg_m2=plan.inertia_local_kg_m2;object.state={plan.position_world_m,fixture.orientation_world,{},{}};
    insertObject(trial,object);
    const auto before=measureRigidMechanics(trial.mechanicalState(1),settings.gravity_m_s2);
    Json samples=Json::array();CreatorMotion motion;double travel=0;
    const auto sample=[&](std::uint64_t tick){object.state=trial.snapshot(1);motion=measureCreatorMotion(object,plane);travel=dot(object.state.center_of_mass_world_m-plan.position_world_m,plane.tangent_world);
        const auto energy=measureRigidMechanics(trial.mechanicalState(1),settings.gravity_m_s2);
        check(finite(object.state.center_of_mass_world_m)&&finite(object.state.linear_velocity_m_s)&&finite(object.state.angular_velocity_rad_s)&&std::isfinite(energy.mechanicalEnergy()),"test produced nonfinite state");
        samples.push_back({{"tick",tick},{"time_s",static_cast<double>(tick)/240},{"state",state(object.state)},{"travel_m",travel},{"motion_state",motion.state},{"near_support_points",motion.near_support_points},{"slip_m_s",motion.near_support_points?Json(motion.slip_m_s):Json(nullptr)},{"mechanical_energy_j",energy.mechanicalEnergy()}});
    };
    sample(0);for(std::uint64_t tick=1;tick<=ticks;++tick){trial.step(1.0/240);(void)trial.drainImpacts();if(tick%24==0||tick==ticks)sample(tick);}
    const bool travel_pass=travel>=minimum,contact_pass=motion.near_support_points>0,slip_pass=contact_pass&&motion.slip_m_s<=slip_limit;
    const bool rolling_pass=!require_rolling||motion.state=="rolling (near-zero slip)";
    report["status"]=travel_pass&&contact_pass&&slip_pass&&rolling_pass?"passed":"failed";
    report["predicates"]={{"minimum_travel",travel_pass},{"final_top_contact",contact_pass},{"maximum_final_slip",slip_pass},{"rolling",require_rolling?Json(rolling_pass):Json(nullptr)}};
    report["final_travel_m"]=travel;report["final_slip_m_s"]=contact_pass?Json(motion.slip_m_s):Json(nullptr);report["mass_kg"]=plan.mass_kg;report["inertia_local_kg_m2"]=matrix(plan.inertia_local_kg_m2);
    report["fixture_recipe"]=parse(recipeJson(fixture));report["samples"]=samples;
    report["mechanical_energy_change_j"]=measureRigidMechanics(trial.mechanicalState(1),settings.gravity_m_s2).mechanicalEnergy()-before.mechanicalEnergy();
    report["energy_note"]="Measured mechanical change, not a closed work/dissipation ledger and not fabrication energy.";
    return report.dump(2);
}
CreatorWorld::CreatorWorld(CreatorWorld &&) noexcept=default;
CreatorWorld &CreatorWorld::operator=(CreatorWorld &&) noexcept=default;
SupportPlaneFrame CreatorWorld::support() const {return makeSupportPlaneFromSlopeDegrees(settings_.slope_degrees);}
double CreatorWorld::inventoryMass(MaterialPreset m) const { double amount=0;for (const auto &lot:lots_) if (lot.collected&&lot.material==m) amount+=lot.remaining_mass_kg;return amount; }
RigidMechanicalState CreatorWorld::mechanicalState(MatterBodyId id) const {return world_->mechanicalState(id);}
bool CreatorWorld::collect(std::string_view id) {
    auto found=std::find_if(lots_.begin(),lots_.end(),[&](const auto &lot){return lot.id==id;});
    check(found!=lots_.end(),"pickup is not in this world");if (found->collected)return false;found->collected=true;return true;
}
CreationAssessment CreatorWorld::assess(const ObjectRecipe &r,std::optional<RevisionTarget> editing) const {
    const auto *old=editing?&targetObject(*editing):nullptr;
    CreationAssessment result;result.creation=compile(r,settings_);
    result.material.material=r.material;result.material.required_mass_kg=result.creation.mass_kg;
    result.material.inventory_mass_kg=inventoryMass(r.material);
    if(old&&old->recipe.material==r.material)result.material.recoverable_mass_kg=old->mass_kg;
    for(const auto &lot:lots_)if(!lot.collected&&lot.material==r.material)result.material.collectible_mass_kg+=lot.remaining_mass_kg;
    auto available=lots_;if(old)applyAllocations(available,old->allocations,1);
    double total=0;for(const auto &lot:available)if(lot.collected&&lot.material==r.material)total+=lot.remaining_mass_kg;
    result.material.missing_mass_kg=std::max(0.0,result.creation.mass_kg-total);
    result.material.missing_after_collection_kg=std::max(0.0,result.material.missing_mass_kg-result.material.collectible_mass_kg);
    if(!editing&&objects_.size()>=max_objects)result.issues.push_back({"object_limit","world.objects","world object budget of 64 is exhausted"});
    if(history_.size()>=max_changes)result.issues.push_back({"history_limit","world.history","authoring history budget of 256 operations is exhausted"});
    for(const auto &object:objects_)if((!old||object.id!=old->id)&&primitivesOverlap(object.recipe.geometry(),object.state.center_of_mass_world_m,object.state.orientation_world,
        r.geometry(),result.creation.position_world_m,r.orientation_world)) {
        result.issues.push_back({"placement_overlap","recipe.placement","placement overlaps object #"+std::to_string(object.id)+"; choose another location"});break;
    }
    if(result.material.missing_mass_kg>0)result.issues.push_back({"insufficient_material","recipe.material","not enough collected or selected-object material; collect more or explicitly choose another design"});
    if(result.buildable())allocate(result.creation,available,old?old->allocations:std::vector<MaterialAllocation>{});
    return result;
}
namespace {
struct CompiledAssembly {Json declaration;CohesivePatchState patch;CohesiveInterfaceLaw law;std::array<std::string,2> ids;std::array<MaterialPreset,2> materials;unsigned a_index;};
CompiledAssembly compileAssembly(std::string_view declaration){
    const auto j=parse(declaration);fields(j,{"schema_version","parts","joint"});check(integer(j.at("schema_version"),1)==1,"unsupported assembly version");
    const auto &parts=j.at("parts");check(parts.is_array()&&parts.size()==2,"assembly assessment requires exactly two boxes");
    std::array<CohesiveBoxDeclaration,2> boxes;std::array<std::string,2> ids;std::array<MaterialPreset,2> materials;
    for(unsigned i=0;i<2;++i){const auto &p=parts[i];fields(p,{"id","material","dimensions_m","center_m","orientation_wxyz"});ids[i]=string(p.at("id"),64);materials[i]=material(p.at("material"));check(materials[i]==MaterialPreset::Glass||materials[i]==MaterialPreset::Oak||materials[i]==MaterialPreset::Iron,"assembly material is outside the tested reference set");
        boxes[i]={vector(p.at("dimensions_m")),makeReferenceMaterial(materials[i]).density_kg_m3,vector(p.at("center_m")),quaternion(p.at("orientation_wxyz"))};const auto d=boxes[i].dimensions_m,c=boxes[i].center_m;
        check(std::min({d.x,d.y,d.z})>=.001&&std::max({d.x,d.y,d.z})<=1,"assembly dimensions must be 0.001 to 1 m");check(std::max({std::abs(c.x),std::abs(c.y),std::abs(c.z)})<=10,"assembly centers must be within 10 m of origin");}
    check(ids[0]!=ids[1],"assembly part IDs must be distinct");const auto &joint=j.at("joint");fields(joint,{"id","part_a","part_b","face_a","face_b","cells_per_axis","law","contact_owner"});(void)string(joint.at("id"),64);
    const auto a_id=string(joint.at("part_a"),64),b_id=string(joint.at("part_b"),64);check(a_id!=b_id&&(a_id==ids[0]||a_id==ids[1])&&(b_id==ids[0]||b_id==ids[1]),"joint references must name the two declared parts");
    const auto policy=string(joint.at("contact_owner"));check(policy=="cohesive_patch_only"||policy=="tension_with_jolt_surfaces","unsupported assembly contact policy");
    const auto face=[](const Json &f){fields(f,{"normal_axis","positive","u_offset_m","v_offset_m","width_m","height_m"});check(f.at("positive").is_boolean(),"face positive must be boolean");return CohesiveBoxFace{static_cast<unsigned>(integer(f.at("normal_axis"),2)),f.at("positive").get<bool>(),number(f.at("u_offset_m")),number(f.at("v_offset_m")),number(f.at("width_m")),number(f.at("height_m"))};};
    const unsigned ai=a_id==ids[0]?0:1,bi=1-ai;const auto compiled=makeBoxFaceCohesivePatch(boxes[ai],boxes[bi],face(joint.at("face_a")),face(joint.at("face_b")),static_cast<unsigned>(integer(joint.at("cells_per_axis"),16)));
    double area=0;for(const auto &site:compiled.sites){check(site.rest_distance_m<=.1,"reference interface gap must be at most 0.1 m");area+=site.area_m2;}
    const auto &l=joint.at("law");fields(l,{"model","stiffness_pa_per_m","strength_pa","fracture_energy_j_m2","compression_stiffness_pa_per_m","provenance"});check(string(l.at("model"))=="central-cohesive-v1","unsupported assembly interface model");(void)string(l.at("provenance"),256);
    const CohesiveInterfaceLaw law{number(l.at("stiffness_pa_per_m")),number(l.at("strength_pa")),number(l.at("fracture_energy_j_m2")),area,number(l.at("compression_stiffness_pa_per_m"))};(void)evaluateCohesiveInterface(law,{});
    check(law.stiffness_pa_per_m<=1e22&&law.compression_stiffness_pa_per_m<=1e22&&law.strength_pa<=1e12&&law.fracture_energy_j_m2<=1e12,"interface law exceeds assessment numeric limits");
    check(policy!="tension_with_jolt_surfaces"||law.compression_stiffness_pa_per_m==0,"Jolt surface policy requires zero cohesive compression stiffness");
    return {j,compiled,law,ids,materials,ai};
}
}
std::string CreatorWorld::assessAssemblyJson(std::string_view declaration) const {
    std::vector<AssemblyMaterialStock> stock;
    for(auto m:kMaterialPresets) {
        double collectible=0;for(const auto &lot:lots_)if(!lot.collected&&lot.material==m)collectible+=lot.remaining_mass_kg;
        stock.push_back({m,inventoryMass(m),collectible});
    }
    return assessAssemblyWithStockJson(declaration,stock);
}
std::string CreatorWorld::assessAssemblyWithStockJson(std::string_view declaration,const std::vector<AssemblyMaterialStock> &stock) {
    check(stock.size()<=kMaterialPresets.size(),"assembly stock exceeds material catalog");
    std::map<MaterialPreset,AssemblyMaterialStock> supplied;
    for(const auto &entry:stock) {
        check(std::find(kMaterialPresets.begin(),kMaterialPresets.end(),entry.material)!=kMaterialPresets.end(),"unknown assembly stock material");
        check(std::isfinite(entry.inventory_mass_kg)&&entry.inventory_mass_kg>=0&&entry.inventory_mass_kg<=1e12&&std::isfinite(entry.collectible_mass_kg)&&entry.collectible_mass_kg>=0&&entry.collectible_mass_kg<=1e12,"invalid assembly stock mass");
        check(supplied.emplace(entry.material,entry).second,"duplicate assembly stock material");
    }
    const auto result=compileAssembly(declaration);const auto &j=result.declaration;const auto &compiled=result.patch;const auto &law=result.law;const auto &ids=result.ids;const auto &materials=result.materials;const auto ai=result.a_index;const double area=law.area_m2;
    Json derived=Json::array();std::map<MaterialPreset,double> requirements;
    for(unsigned i=0;i<2;++i){const auto &body=i==ai?compiled.a:compiled.b;requirements[materials[i]]+=body.mass_kg;derived.push_back({{"id",ids[i]},{"material",materialPresetName(materials[i])},{"mass_kg",body.mass_kg},{"principal_inertia_kg_m2",vector(body.principal_inertia_kg_m2)}});}
    Json bill=Json::array();bool sufficient=true;
    for(const auto &[m,required]:requirements){const auto it=supplied.find(m);const double held=it==supplied.end()?0:it->second.inventory_mass_kg,collectible=it==supplied.end()?0:it->second.collectible_mass_kg,missing=std::max(0.0,required-held);
        sufficient=sufficient&&missing==0;bill.push_back({{"material",materialPresetName(m)},{"required_mass_kg",required},{"inventory_mass_kg",held},{"collectible_mass_kg",collectible},{"missing_from_inventory_kg",missing},{"missing_after_collection_kg",std::max(0.0,missing-collectible)}});}
    return Json{{"assessment_version",1},{"declaration",j},{"compiled",true},{"materials_sufficient",sufficient},{"creation_supported",false},{"parts",derived},{"material_requirements",bill},
        {"joint",{{"area_m2",area},{"rest_gap_m",compiled.sites.front().rest_distance_m},{"site_count",compiled.sites.size()},{"complete_tensile_separation_work_j",area*law.fracture_energy_j_m2},{"contact_policy",j.at("joint").at("contact_owner")}}},
        {"limitations",Json::array({"Experimental two-box design; live assembly creation is unsupported. Test version 1 uses isolated cohesion; version 2 requires tension_with_jolt_surfaces and double positions.","No shear/friction, calibrated material failure or proven spatial damage-front convergence.","Separation work is not fabrication cost; joining energy, tools and processes remain unsupported."})}}.dump(2);
}
std::uint64_t CreatorWorld::rememberAssembly(std::string_view declaration,std::uint64_t expected){
    const auto compiled=compileAssembly(declaration);const auto canonical=compiled.declaration.dump();
    if(assembly_draft_&&*assembly_draft_==canonical)return assembly_revision_;
    check(expected==assembly_revision_,"stale assembly draft revision");check(assembly_revision_<1000000000,"assembly draft revision exhausted");
    assembly_draft_=canonical;return ++assembly_revision_;
}
std::uint64_t CreatorWorld::clearAssembly(std::uint64_t expected){
    check(expected==assembly_revision_,"stale assembly draft revision");if(!assembly_draft_)return assembly_revision_;
    check(assembly_revision_<1000000000,"assembly draft revision exhausted");assembly_draft_.reset();return ++assembly_revision_;
}
namespace {
std::string testRuntimeAssembly(const CompiledAssembly &compiled,std::string_view specification) {
    check(JoltWorld::positionPrecisionBits()==64,"runtime assembly tests require double positions");
    const auto spec=parse(specification);auto required=spec;
    std::array<Vec3,2> spin{};
    if(required.contains("initial_angular_velocity_rad_s")) {
        const auto &values=required.at("initial_angular_velocity_rad_s");
        check(values.is_object()&&values.size()==2,"initial spin must name exactly both declared parts");
        for(unsigned n=0;n<2;++n){const auto &id=compiled.ids[n==0?compiled.a_index:1-compiled.a_index];
            check(values.contains(id),"initial spin must use declared part IDs");spin[n]=vector(values.at(id));
            check(length(spin[n])<=10,"initial spin exceeds 10 rad/s");}
        required.erase("initial_angular_velocity_rad_s");
    }
    bool adaptive=false;std::uint64_t maximum_evaluations=0;double state_tolerance=0,minimum_step=0;
    if(required.contains("adaptive")) {
        adaptive=true;const auto &control=required.at("adaptive");fields(control,{"maximum_evaluations","state_error_tolerance","minimum_step_s"});
        maximum_evaluations=integer(control.at("maximum_evaluations"),65536);state_tolerance=number(control.at("state_error_tolerance"));minimum_step=number(control.at("minimum_step_s"));
        check(maximum_evaluations>=3&&state_tolerance>0&&state_tolerance<=.1&&minimum_step>0&&minimum_step<=1,"invalid adaptive runtime controls");
        required.erase("adaptive");
    }
    bool body_pair_cache=true;
    if(required.contains("body_pair_contact_cache")) {
        check(required.at("body_pair_contact_cache").is_boolean(),"body_pair_contact_cache must be boolean");
        body_pair_cache=required.at("body_pair_contact_cache").get<bool>();required.erase("body_pair_contact_cache");
    }
    unsigned velocity_iterations=10,position_iterations=2;
    if(required.contains("contact_iterations")) {
        const auto &iterations=required.at("contact_iterations");fields(iterations,{"velocity","position"});
        velocity_iterations=static_cast<unsigned>(integer(iterations.at("velocity"),256));position_iterations=static_cast<unsigned>(integer(iterations.at("position"),64));
        check(velocity_iterations>=2&&position_iterations>=1,"contact solver iteration counts are too small");required.erase("contact_iterations");
    }
    fields(required,{"test_version","relative_kinetic_energy_j","duration_s","steps","energy_error_budget_j","transfer_roundoff_budget_j","minimum_separated_area_fraction"});
    check(integer(spec.at("test_version"),2)==2,"Jolt assembly fixture requires test version 2");
    const auto input=number(spec.at("relative_kinetic_energy_j")),duration=number(spec.at("duration_s"));
    const auto budget=number(spec.at("energy_error_budget_j")),transfer_budget=number(spec.at("transfer_roundoff_budget_j")),minimum=number(spec.at("minimum_separated_area_fraction"));
    const auto steps=integer(spec.at("steps"),4096);
    check(input>0&&input<=1e4&&duration>0&&duration<=1&&steps>=1,"runtime assembly duration/energy/step bounds exceeded");
    check(budget>0&&budget<=.01*input&&transfer_budget>=0&&transfer_budget<=budget&&minimum>=0&&minimum<=1,"invalid runtime assembly error budget or criterion");
    const double dt=static_cast<float>(duration/static_cast<double>(steps));
    check(dt>0&&std::isfinite(dt),"unrepresentable runtime assembly timestep");
    check(!adaptive||minimum_step<=dt/2,"adaptive minimum step exceeds initial half step");
    auto sites=compiled.patch.sites;const auto &pa=compiled.patch.a,&pb=compiled.patch.b;
    const auto delta=pb.center_m+pb.orientation.rotate(sites.front().attachment_b_m)-pa.center_m-pa.orientation.rotate(sites.front().attachment_a_m);
    const auto normal=delta/length(delta);const double ma=pa.mass_kg,mb=pb.mass_kg,mu=ma*mb/(ma+mb),speed=std::sqrt(2*input/mu);
    check(std::isfinite(speed)&&speed<=100,"runtime assembly initialization speed exceeds 100 m/s");
    JoltWorld world;world.setGravity({});world.setBodyPairContactCacheEnabled(body_pair_cache);world.setContactSolverIterations(velocity_iterations,position_iterations);
    for(unsigned n=0;n<2;++n) {
        const unsigned index=n==0?compiled.a_index:1-compiled.a_index;const auto &body=n==0?pa:pb;
        const Vec3 velocity=(n==0?-mb:ma)/(ma+mb)*speed*normal;
        const auto &part=compiled.declaration.at("parts").at(index);
        world.addBox({n+1,vector(part.at("dimensions_m")),makeReferenceMaterial(compiled.materials[index]),
            {body.center_m,body.orientation,velocity,spin[n]},false});
    }
    const auto totals=[&]{auto result=measureRigidMechanics(world.mechanicalState(1));result+=measureRigidMechanics(world.mechanicalState(2));return result;};
    const auto initial=totals();check(initial.kinetic_energy_j<=1e4,"total initialized kinetic energy exceeds 10000 J");
    double initial_spin_energy=0;
    for(auto id:{1u,2u}){const auto state=world.mechanicalState(id);const auto w=state.motion.angular_velocity_rad_s;initial_spin_energy+=.5*dot(w,state.inertia_world_kg_m2*w);}
    double jolt_change=0,transfer_error=0,max_error=0,max_momentum=0,max_angular=0;unsigned contacts=0;
    double opening_work=0,kick_work=0,previous_residual=0,absolute_error=0,elapsed=0;std::vector<Json> worst_steps;
    std::uint64_t accepted_steps=0,evaluations=0,rejected_intervals=0;
    const auto energies=[&]{double stored=0,damage=0;for(const auto &site:sites){auto law=compiled.law;law.area_m2=site.area_m2;const auto response=evaluateCohesiveInterface(law,site.history);stored+=response.stored_energy_j;damage+=response.dissipated_energy_j;}return std::pair{stored,damage};};
    const auto kick=[&](double h){const auto result=world.applyCohesiveTensionPatchKick(1,2,sites,compiled.law,h/2,transfer_budget);
        for(std::size_t k=0;k<sites.size();++k)sites[k].history=result.interface_increments[k].state;
        transfer_error+=result.transfer.numerical_energy_change_j;kick_work+=result.transfer.impulse_work_j;
        for(const auto &increment:result.interface_increments)opening_work+=increment.opening_work_j;};
    const auto advance_step=[&](double h) {
        check(h>0&&static_cast<double>(static_cast<float>(h))==h&&std::isfinite(1.0F/static_cast<float>(h)),"runtime timestep is not representable with a finite reciprocal");
        if(adaptive&&evaluations>=maximum_evaluations)throw std::runtime_error("adaptive runtime evaluation budget exhausted");
        ++evaluations;++accepted_steps;elapsed+=h;
        const double previous_opening_work=opening_work,previous_kick_work=kick_work,previous_transfer=transfer_error;
        std::vector<double> previous_openings;previous_openings.reserve(sites.size());for(const auto &site:sites)previous_openings.push_back(site.history.opening_m);
        kick(h);const double before=totals().kinetic_energy_j;world.step(h);const double jolt_step_change=totals().kinetic_energy_j-before;jolt_change+=jolt_step_change;
        const auto new_contacts=static_cast<unsigned>(world.drainImpacts().size());contacts+=new_contacts;kick(h);
        const auto now=totals();const auto [stored,damage]=energies();
        const double residual=now.kinetic_energy_j+stored+damage-initial.kinetic_energy_j-jolt_change-transfer_error;
        check(std::isfinite(residual),"runtime assembly trajectory overflow");
        max_error=std::max(max_error,std::abs(residual));absolute_error+=std::abs(residual-previous_residual);
        unsigned slack_crossings=0;double minimum_opening=sites.front().history.opening_m,maximum_opening=minimum_opening;
        for(std::size_t k=0;k<sites.size();++k){const double q=sites[k].history.opening_m;
            if((q>0)!=(previous_openings[k]>0))++slack_crossings;minimum_opening=std::min(minimum_opening,q);maximum_opening=std::max(maximum_opening,q);}
        worst_steps.push_back({{"tick",accepted_steps},{"time_s",elapsed},{"step_integration_error_j",residual-previous_residual},
            {"cumulative_integration_error_j",residual},{"jolt_stage_energy_change_j",jolt_step_change},{"transfer_roundoff_j",transfer_error-previous_transfer},
            {"cohesive_opening_work_j",opening_work-previous_opening_work},{"impulse_work_j",kick_work-previous_kick_work},
            {"new_contact_events",new_contacts},{"slack_crossings",slack_crossings},{"minimum_opening_m",minimum_opening},{"maximum_opening_m",maximum_opening}});
        std::stable_sort(worst_steps.begin(),worst_steps.end(),[](const Json &a,const Json &b){return std::abs(a.at("step_integration_error_j").get<double>())>std::abs(b.at("step_integration_error_j").get<double>());});
        if(worst_steps.size()>8)worst_steps.pop_back();previous_residual=residual;
        max_momentum=std::max(max_momentum,length(now.linear_momentum_kg_m_s-initial.linear_momentum_kg_m_s));
        max_angular=std::max(max_angular,length(now.angular_momentum_kg_m2_s-initial.angular_momentum_kg_m2_s));
        check(std::isfinite(max_error),"runtime assembly trajectory overflow");
    };
    // Runtime checkpoints own solver state. This tuple owns every accompanying
    // history/diagnostic accumulator; evaluation cost deliberately never rewinds.
    const auto save=[&]{return std::tuple{sites,jolt_change,transfer_error,max_error,max_momentum,max_angular,contacts,opening_work,kick_work,previous_residual,absolute_error,elapsed,worst_steps,accepted_steps};};
    const auto restore=[&](const auto &saved){std::tie(sites,jolt_change,transfer_error,max_error,max_momentum,max_angular,contacts,opening_work,kick_work,previous_residual,absolute_error,elapsed,worst_steps,accepted_steps)=saved;};
    const auto dims_a=vector(compiled.declaration.at("parts")[0].at("dimensions_m")),dims_b=vector(compiled.declaration.at("parts")[1].at("dimensions_m"));
    const double length_scale=std::max({dims_a.x,dims_a.y,dims_a.z,dims_b.x,dims_b.y,dims_b.z});
    std::function<void(double,unsigned)> integrate;
    integrate=[&](double h,unsigned depth) {
        const auto saved=save();const double prior_absolute_error=absolute_error;
        std::array<RigidSnapshot,2> coarse;std::vector<CohesivePatchSite> coarse_sites;
        (void)world.runReversibleTrial([&]{advance_step(h);coarse={world.snapshot(1),world.snapshot(2)};coarse_sites=sites;return false;});restore(saved);
        // Spend only the remaining global absolute-work budget. The state
        // comparison supplies local refinement control; exhaustion rejects the
        // complete temporary trajectory instead of hiding cancellation.
        const double local_allowance=budget-prior_absolute_error;
        double candidate_difference=0,candidate_error=0;Json component_errors=Json::array(),fine_motion=Json::array(),coarse_motion=Json::array();
        const bool accepted=world.runReversibleTrial([&]{
            advance_step(h/2);advance_step(h/2);double difference=0;
            for(unsigned k=0;k<2;++k){const auto fine=world.snapshot(k+1);const auto &rough=coarse[k];
                difference=std::max(difference,length(fine.center_of_mass_world_m-rough.center_of_mass_world_m)/length_scale);
                difference=std::max(difference,length(fine.linear_velocity_m_s-rough.linear_velocity_m_s)/std::max({1.0,length(fine.linear_velocity_m_s),length(rough.linear_velocity_m_s)}));
                difference=std::max(difference,length(fine.angular_velocity_rad_s-rough.angular_velocity_rad_s)/std::max({1.0,length(fine.angular_velocity_rad_s),length(rough.angular_velocity_rad_s)}));
                const auto a=fine.orientation_world,b=rough.orientation_world;
                const double minus=(a.w-b.w)*(a.w-b.w)+(a.x-b.x)*(a.x-b.x)+(a.y-b.y)*(a.y-b.y)+(a.z-b.z)*(a.z-b.z);
                const double plus=(a.w+b.w)*(a.w+b.w)+(a.x+b.x)*(a.x+b.x)+(a.y+b.y)*(a.y+b.y)+(a.z+b.z)*(a.z+b.z);
                difference=std::max(difference,2*std::sqrt(std::min(minus,plus)));
                component_errors.push_back({{"part",compiled.ids[k==0?compiled.a_index:1-compiled.a_index]},
                    {"position",length(fine.center_of_mass_world_m-rough.center_of_mass_world_m)/length_scale},
                    {"linear_velocity",length(fine.linear_velocity_m_s-rough.linear_velocity_m_s)/std::max({1.0,length(fine.linear_velocity_m_s),length(rough.linear_velocity_m_s)})},
                    {"angular_velocity",length(fine.angular_velocity_rad_s-rough.angular_velocity_rad_s)/std::max({1.0,length(fine.angular_velocity_rad_s),length(rough.angular_velocity_rad_s)})},
                    {"orientation",2*std::sqrt(std::min(minus,plus))}});
                fine_motion.push_back(state(fine));coarse_motion.push_back(state(rough));
            }
            const double failure=cohesiveSeparationOpening(compiled.law);
            for(std::size_t k=0;k<sites.size();++k){difference=std::max(difference,std::abs(sites[k].history.opening_m-coarse_sites[k].history.opening_m)/failure);difference=std::max(difference,std::abs(sites[k].history.maximum_opening_m-coarse_sites[k].history.maximum_opening_m)/failure);}
            candidate_difference=difference;candidate_error=absolute_error-prior_absolute_error;
            return difference<=state_tolerance&&candidate_error<=local_allowance;
        });
        if(accepted)return;
        restore(saved);++rejected_intervals;
        if(depth>=20||h/4<minimum_step)throw std::runtime_error("adaptive runtime refinement floor reached: "+Json{{"time_s",elapsed},{"step_s",h},{"state_error",candidate_difference},{"work_error_j",candidate_error},{"allowed_work_j",local_allowance},{"contact_numerics",{{"body_pair_contact_cache",body_pair_cache},{"velocity_iterations",velocity_iterations},{"position_iterations",position_iterations}}},{"component_errors",component_errors},{"coarse_motion",coarse_motion},{"fine_motion",fine_motion}}.dump());
        integrate(h/2,depth+1);integrate(h/2,depth+1);
    };
    for(std::uint64_t tick=0;tick<steps;++tick){if(adaptive)integrate(dt,0);else advance_step(dt);}
    if(adaptive)check(absolute_error<=budget*(1+1e-10),"adaptive runtime accumulated work error exceeds budget");
    Json histories=Json::array(),bodies=Json::array();double separated=0;
    for(const auto &site:sites){auto law=compiled.law;law.area_m2=site.area_m2;const auto response=evaluateCohesiveInterface(law,site.history);if(response.separated)separated+=site.area_m2;
        histories.push_back({{"area_m2",site.area_m2},{"opening_m",site.history.opening_m},{"maximum_opening_m",site.history.maximum_opening_m},{"damage",response.damage}});}
    for(unsigned n=0;n<2;++n){const auto state=world.snapshot(n+1);bodies.push_back({{"id",compiled.ids[n==0?compiled.a_index:1-compiled.a_index]},{"center_m",vector(state.center_of_mass_world_m)},{"orientation_wxyz",quaternion(state.orientation_world)},{"linear_velocity_m_s",vector(state.linear_velocity_m_s)},{"angular_velocity_rad_s",vector(state.angular_velocity_rad_s)}});}
    const auto [stored,damage]=energies();const double fraction=separated/compiled.law.area_m2;
    return Json{{"test_version",2},{"fixture","jolt-tensile-patch-separation-v1"},{"declaration",compiled.declaration},{"specification",spec},
        {"physics_signature",Json::parse(CreatorWorld::physicsSignatureJson())},{"status",fraction>=minimum&&max_error<=budget?"passed":"failed"},
        {"predicates",{{"separated_area",fraction>=minimum},{"integration_energy",max_error<=budget}}},{"actual_duration_s",elapsed},{"integration",{{"mode",adaptive?"adaptive-step-doubling":"fixed"},{"body_pair_contact_cache",body_pair_cache},{"velocity_iterations",velocity_iterations},{"position_iterations",position_iterations},{"evaluations",evaluations},{"accepted_steps",accepted_steps},{"rejected_intervals",rejected_intervals},{"accumulated_absolute_error_j",absolute_error}}},
        {"initial_kinetic_energy_j",initial.kinetic_energy_j},{"initial_rotational_kinetic_energy_j",initial_spin_energy},{"final_kinetic_energy_j",totals().kinetic_energy_j},{"stored_energy_j",stored},{"damage_work_j",damage},
        {"separated_area_fraction",fraction},{"energy_residual_j",totals().kinetic_energy_j+stored+damage-initial.kinetic_energy_j},{"maximum_integration_energy_error_j",max_error},{"jolt_stage_energy_change_j",jolt_change},{"signed_transfer_roundoff_j",transfer_error},
        {"cohesive_opening_work_j",opening_work},{"impulse_work_j",kick_work},{"largest_error_steps",worst_steps},{"maximum_momentum_change_kg_m_s",max_momentum},{"maximum_angular_momentum_change_kg_m2_s",max_angular},{"contact_events",contacts},{"sites",histories},{"bodies",bodies},
        {"boundary","Temporary two-box world, zero gravity, initial separating velocity and optional declared spin. Jolt owns surfaces. Events may be speculative. Jolt-stage energy change includes solver effects, not automatically heat. Reported integration evidence is not a global convergence certificate. No live resources, objects or clock changed; no fabrication or cutting certification."}}.dump(2);
}
}
std::string CreatorWorld::testAssemblyJson(std::string_view declaration,std::string_view specification){
    const auto compiled=compileAssembly(declaration);
    if(compiled.declaration.at("joint").at("contact_owner")=="tension_with_jolt_surfaces")return testRuntimeAssembly(compiled,specification);
    auto state=compiled.patch;const auto &law=compiled.law;
    const auto spec=parse(specification);fields(spec,{"test_version","relative_kinetic_energy_j","duration_s","energy_error_budget_j","state_error_tolerance","maximum_evaluations","minimum_separated_area_fraction"});check(integer(spec.at("test_version"),1)==1,"unsupported assembly test version");
    const double input=number(spec.at("relative_kinetic_energy_j")),duration=number(spec.at("duration_s")),minimum=number(spec.at("minimum_separated_area_fraction"));check(input>0&&input<=1e4,"assembly test input energy must be positive and at most 10000 J");check(minimum>=0&&minimum<=1,"separated-area fraction must be 0 to 1");
    const CohesiveAdaptiveControls controls{number(spec.at("energy_error_budget_j")),number(spec.at("state_error_tolerance")),static_cast<unsigned>(integer(spec.at("maximum_evaluations"),65536))};
    check(controls.energy_error_budget_j<=input*.01,"numerical energy budget must be at most 1 percent of input energy");
    const auto &site=state.sites.front();const auto delta=state.b.center_m+state.b.orientation.rotate(site.attachment_b_m)-state.a.center_m-state.a.orientation.rotate(site.attachment_a_m);const auto normal=delta/length(delta);
    const double ma=state.a.mass_kg,mb=state.b.mass_kg,mu=ma*mb/(ma+mb),speed=std::sqrt(2*input/mu);check(std::isfinite(speed)&&speed<=1e4,"assembly test speed exceeds 10000 m/s bound");
    state.a.velocity_m_s=-mb/(ma+mb)*speed*normal;state.b.velocity_m_s=ma/(ma+mb)*speed*normal;
    const double initial_energy=cohesiveRigidKineticEnergy({state.a,state.b,{}});
    const auto result=advanceCohesivePatchAdaptive(law,state,duration,controls);
    double separated_area=0,stored=0,damage=0;Json histories=Json::array();
    for(const auto &s:result.state.sites){auto local=law;local.area_m2=s.area_m2;const auto response=evaluateCohesiveInterface(local,s.history);if(response.separated)separated_area+=s.area_m2;stored+=response.stored_energy_j;damage+=response.dissipated_energy_j;histories.push_back({{"area_m2",s.area_m2},{"opening_m",s.history.opening_m},{"maximum_opening_m",s.history.maximum_opening_m},{"damage",response.damage}});}
    const double fraction=separated_area/law.area_m2,kinetic=cohesiveRigidKineticEnergy({result.state.a,result.state.b,{}});
    const auto body=[](const CohesiveRigidBody &b,const std::string &id){return Json{{"id",id},{"center_m",vector(b.center_m)},{"orientation_wxyz",quaternion(b.orientation)},{"linear_velocity_m_s",vector(b.velocity_m_s)},{"angular_momentum_kg_m2_s",vector(b.angular_momentum_kg_m2_s)}};};
    return Json{{"test_version",1},{"fixture","isolated-cohesive-separation-v1"},{"declaration",compiled.declaration},{"specification",spec},{"status",fraction>=minimum?"passed":"failed"},{"separated_area_fraction",fraction},{"initial_kinetic_energy_j",initial_energy},{"final_kinetic_energy_j",kinetic},{"stored_energy_j",stored},{"damage_work_j",damage},{"energy_residual_j",kinetic+stored+damage-initial_energy},{"accumulated_absolute_energy_error_j",result.accumulated_absolute_energy_error_j},{"evaluations",result.evaluations},{"accepted_half_steps",result.accepted_half_steps},{"sites",histories},{"bodies",Json::array({body(result.state.a,compiled.ids[compiled.a_index]),body(result.state.b,compiled.ids[1-compiled.a_index])})},{"boundary","Virtual at-rest assembly initialized with separating normal kinetic energy and zero COM motion; no gravity or external collision owner. No live resources, objects or clock changed. Passing only measures the requested separation fraction; no general functional, material or cutting certification."}}.dump(2);
}
std::string CreatorWorld::assessJson(const ObjectRecipe &r,std::optional<RevisionTarget> editing) const {
    const auto report=assess(r,editing);const auto &m=report.material;Json issues=Json::array();
    bool other_blocker=false;for(const auto &issue:report.issues) {
        issues.push_back({{"code",issue.code},{"field",issue.field},{"message",issue.message}});
        other_blocker|=issue.code!="insufficient_material";
    }
    return Json{{"assessment_version",1},{"status",report.buildable()?"buildable":other_blocker?"blocked":"needs_resources"},
        {"buildable_with_inventory",report.buildable()},{"buildable_after_collection",!other_blocker&&m.missing_after_collection_kg==0},
        {"scope","intact-authoring sandbox; functional performance still requires a physical test"},
        {"fabrication_energy_j",nullptr},{"energy_note","fabrication energy is unsupported, not zero"},
        {"compiled",previewJson(report.creation)},{"issues",issues},
        {"material_requirements",Json::array({{{"material",materialPresetName(m.material)},{"required_mass_kg",m.required_mass_kg},
            {"inventory_mass_kg",m.inventory_mass_kg},{"recoverable_mass_kg",m.recoverable_mass_kg},{"collectible_mass_kg",m.collectible_mass_kg},
            {"missing_mass_kg",m.missing_mass_kg},{"missing_after_collection_kg",m.missing_after_collection_kg}}})}}.dump(2);
}
CreationPreview CreatorWorld::preview(const ObjectRecipe &r) const {
    auto result=assess(r);if(!result.buildable())throw std::invalid_argument(result.issues.front().message);return std::move(result.creation);
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
    auto report=assess(r,target);if(!report.buildable())throw std::invalid_argument(report.issues.front().message);
    const auto &old=targetObject(target);RebuildPreview result{std::move(report.creation),target.object_id,target.expected_revision};
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
    candidate.assembly_draft_=assembly_draft_;candidate.assembly_revision_=assembly_revision_;
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
CreationPreview CreatorWorld::compileRecipe(const ObjectRecipe &r,CreatorSettings settings) {return compile(r,settings);}
std::string CreatorWorld::recipeJson(const ObjectRecipe &r) {return recipe(r).dump(2);}
CreatorProposal CreatorWorld::parseProposal(std::string_view document) {
    const auto j=parse(document);fields(j,{"request_id","explanation","recipe"});
    return {string(j.at("request_id")),string(j.at("explanation"),512),recipe(j.at("recipe"))};
}
std::string CreatorWorld::physicsSignatureJson() { return signature().dump(); }
std::string CreatorWorld::serialize() const {
    Json lots=Json::array(),objects=Json::array(),history=Json::array();
    for (const auto &lot:lots_) lots.push_back({{"id",lot.id},{"provenance",lot.provenance},{"material",materialPresetName(lot.material)},
        {"initial_mass_kg",lot.initial_mass_kg},{"remaining_mass_kg",lot.remaining_mass_kg},{"collected",lot.collected}});
    for(const auto &o:objects_)objects.push_back(objectJson(o));
    for(const auto &c:history_)history.push_back(changeJson(c));
    return Json{{"world_version",5},{"physics_signature",signature()},{"authoring_policy",authoring_policy},
        {"assembly_draft",{{"revision",assembly_revision_},{"declaration",assembly_draft_?parse(*assembly_draft_):Json(nullptr)}}},
        {"settings",{{"slope_degrees",settings_.slope_degrees},{"gravity_m_s2",vector(settings_.gravity_m_s2)},{"surface",materialPresetName(settings_.surface)}}},
        {"ticks",ticks_},{"lots",lots},{"objects",objects},{"history",history},{"next_object_id",next_object_id_}}.dump(2);
}
CreatorWorld CreatorWorld::deserialize(std::string_view document) {
    const auto j=parse(document);check(j.is_object()&&j.contains("world_version"),"world version is required");
    const auto version=integer(j.at("world_version"),100);
    check(version>=1&&version<=5,"incompatible world version");
    if(version<3)fields(j,{"world_version","physics_signature","settings","ticks","lots","objects"});
    else if(version==3)fields(j,{"world_version","physics_signature","settings","ticks","lots","objects","authoring_policy","history","next_object_id"});
    else fields(j,{"world_version","physics_signature","settings","ticks","lots","objects","authoring_policy","history","next_object_id","assembly_draft"});
    check(version>=5||JoltWorld::positionPrecisionBits()==32,"legacy world has unrecorded position precision; load in the legacy 32-bit configuration before explicit conversion");
    check(j.at("physics_signature")==signature(version==1?1:2,version>=5),"saved material/runtime signature differs; explicit migration is required");
    if(version>=3)check(j.at("authoring_policy")==authoring_policy,"unsupported authoring recovery policy");
    const auto &s=j.at("settings");fields(s,{"slope_degrees","gravity_m_s2","surface"});
    const CreatorSettings config{number(s.at("slope_degrees")),vector(s.at("gravity_m_s2")),material(s.at("surface"))};
    const auto &lots=j.at("lots"),&objects=j.at("objects");
    check(lots.is_array()&&!lots.empty()&&lots.size()<=128,"world must have 1–128 material lots");
    check(objects.is_array()&&objects.size()<=max_objects,"saved object budget exceeds 64");
    CreatorWorld world(config);world.lots_.clear();world.ticks_=integer(j.at("ticks"),240ULL*60*60*24*365);
    if(version>=4){const auto &draft=j.at("assembly_draft");fields(draft,{"revision","declaration"});world.assembly_revision_=integer(draft.at("revision"),1000000000);if(!draft.at("declaration").is_null()){check(world.assembly_revision_>0,"saved assembly draft requires a revision");world.assembly_draft_=compileAssembly(draft.at("declaration").dump()).declaration.dump();}}
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
    if(version>=3) {
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
    result["capabilities"]["assessment"]={{"version",1},{"operations",Json::array({"assess","assess_rebuild"})},
        {"note","Read-only requirements distinguish collected inventory, recoverable selected matter, uncollected lots and remaining shortfall. Assessments do not reserve resources or prove functional performance."}};
    result["capabilities"]["functional_tests"]={{"version",1},{"operation","test_recipe"},{"fixture","concrete-incline-v1"},{"max_ticks",1200},{"dt_s",1.0/240},{"note","Isolated virtual fixture with explicit endpoint criteria; does not spend live resources. Rolling predicate supports spheres only."}};
    result["history_count"]=history_.size();
    result["capabilities"]["assembly_assessment"]={{"version",1},{"operation","assess_assembly"},{"parts",2},{"shape","box"},{"creation_supported",false},{"note","Read-only experimental interface geometry and material requirements; live assembly/contact integration is unsupported."}};
    result["capabilities"]["assembly_test"]={{"version",1},{"operation","test_assembly"},{"fixture","isolated-cohesive-separation-v1"},{"maximum_evaluations",65536},{"maximum_sites",256},{"note","Bounded isolated normal-separation experiment; no live resources consumed."}};
    result["capabilities"]["assembly_draft"]={{"version",1},{"operations",Json::array({"remember_assembly","clear_assembly","assess_saved_assembly"})},{"note","One revisioned declaration persists with world save. Assessments are recomputed; no stored test or review result is trusted as current."}};
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
            else if (type=="assess") {fields(command,{"type","recipe"});value=parse(assessJson(recipe(command.at("recipe"))));}
            else if (type=="assess_assembly") {fields(command,{"type","assembly"});value=parse(assessAssemblyJson(command.at("assembly").dump()));}
            else if (type=="test_assembly") {fields(command,{"type","assembly","test"});value=parse(testAssemblyJson(command.at("assembly").dump(),command.at("test").dump()));}
            else if (type=="remember_assembly") {fields(command,{"type","assembly","expected_revision"});value={{"revision",rememberAssembly(command.at("assembly").dump(),integer(command.at("expected_revision"),1000000000))}};}
            else if (type=="clear_assembly") {fields(command,{"type","expected_revision"});value={{"revision",clearAssembly(integer(command.at("expected_revision"),1000000000))}};}
            else if (type=="assess_saved_assembly") {fields(command,{"type"});check(assembly_draft_.has_value(),"no assembly draft is saved");value=parse(assessAssemblyJson(*assembly_draft_));value["draft_revision"]=assembly_revision_;}
            else if (type=="test_recipe") {fields(command,{"type","recipe","test"});value=parse(testRecipeJson(recipe(command.at("recipe")),command.at("test").dump()));}
            else if (type=="assess_rebuild") {
                fields(command,{"type","object_id","expected_revision","recipe"});
                value=parse(assessJson(recipe(command.at("recipe")),RevisionTarget{integer(command.at("object_id"),max_changes),integer(command.at("expected_revision"),max_changes)}));
            }
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
