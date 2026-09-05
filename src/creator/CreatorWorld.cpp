#include "creator/CreatorWorld.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/RollingKinematics.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <fstream>
#include <numbers>
#include <set>
#include <stdexcept>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace banjo {
namespace {
using Json=nlohmann::json;
constexpr std::size_t max_document=1024*1024, max_objects=64;
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
    for (const auto &object:objects_) check(!primitivesOverlap(object.recipe.geometry(),object.state.center_of_mass_world_m,object.state.orientation_world,
        r.geometry(),result.position_world_m,r.orientation_world),
        "placement overlaps an existing object; choose another location");
    double remaining=result.mass_kg;
    for (const auto &lot:lots_) if (lot.collected&&lot.material==r.material&&lot.remaining_mass_kg>0&&remaining>0) {
        const double amount=std::min(remaining,lot.remaining_mass_kg);result.allocations.push_back({lot.id,amount});remaining-=amount;
    }
    check(remaining<=0,"not enough collected material for this geometry; collect more or reduce the size");
    return result;
}
MatterBodyId CreatorWorld::create(std::string request_id,const ObjectRecipe &r) {
    (void)string(Json(request_id));
    for (const auto &object:objects_) if (object.request_id==request_id) {
        check(recipe(object.recipe)==recipe(r),"request ID was already used for a different object specification");return object.id;
    }
    const auto plan=preview(r);
    auto next_lots=lots_;auto next_objects=objects_;
    for (const auto &a:plan.allocations) {
        auto lot=std::find_if(next_lots.begin(),next_lots.end(),[&](const auto &value){return value.id==a.lot_id;});
        lot->remaining_mass_kg-=a.mass_kg;
    }
    const auto id=static_cast<MatterBodyId>(objects_.size()+1);
    next_objects.push_back({id,std::move(request_id),r,plan.volume_m3,plan.mass_kg,plan.inertia_local_kg_m2,plan.allocations,
        {plan.position_world_m,r.orientation_world,r.linear_velocity_m_s,r.angular_velocity_rad_s}});
    // All allocations and validation finish before insertion. Jolt insertion
    // rolls back on failure, then these no-throw swaps commit the authoring state.
    insertObject(*world_,next_objects.back());
    lots_.swap(next_lots);objects_.swap(next_objects);return id;
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
    Json lots=Json::array(),objects=Json::array();
    for (const auto &lot:lots_) lots.push_back({{"id",lot.id},{"provenance",lot.provenance},{"material",materialPresetName(lot.material)},
        {"initial_mass_kg",lot.initial_mass_kg},{"remaining_mass_kg",lot.remaining_mass_kg},{"collected",lot.collected}});
    for (const auto &object:objects_) objects.push_back({{"id",object.id},{"request_id",object.request_id},{"recipe",recipe(object.recipe)},
        {"allocations",allocations(object.allocations)},{"state",state(object.state)}});
    return Json{{"world_version",2},{"physics_signature",signature()},
        {"settings",{{"slope_degrees",settings_.slope_degrees},{"gravity_m_s2",vector(settings_.gravity_m_s2)},{"surface",materialPresetName(settings_.surface)}}},
        {"ticks",ticks_},{"lots",lots},{"objects",objects}}.dump(2);
}
CreatorWorld CreatorWorld::deserialize(std::string_view document) {
    const auto j=parse(document);fields(j,{"world_version","physics_signature","settings","ticks","lots","objects"});
    const auto version=integer(j.at("world_version"),100);
    check(version==1||version==2,"incompatible world version");
    check(j.at("physics_signature")==signature(static_cast<unsigned>(version)),"saved material/runtime signature differs; explicit migration is required");
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
        fields(value,{"id","request_id","recipe","allocations","state"});
        const auto r=recipe(value.at("recipe"));const auto p=compile(r,config);
        check(version==2||r.schema_version==1,"legacy worlds may contain only schema-1 spheres");
        CreatedObject object{integer(value.at("id"),max_objects),string(value.at("request_id")),r,p.volume_m3,p.mass_kg,p.inertia_local_kg_m2,{},state(value.at("state"))};
        check(object.id==world.objects_.size()+1&&request_ids.insert(object.request_id).second,"duplicate or unordered object/request ID");
        const auto &allocation=value.at("allocations");check(allocation.is_array()&&!allocation.empty()&&allocation.size()<=world.lots_.size(),"invalid material allocations");
        std::set<std::string> object_lots;double allocated=0;
        for (const auto &a:allocation) {
            fields(a,{"lot_id","mass_kg"});MaterialAllocation part{string(a.at("lot_id")),number(a.at("mass_kg"))};
            const auto lot=std::find_if(world.lots_.begin(),world.lots_.end(),[&](const auto &v){return v.id==part.lot_id;});
            check(lot!=world.lots_.end()&&lot->collected&&lot->material==r.material&&part.mass_kg>0&&object_lots.insert(part.lot_id).second,"allocation does not match a collected material lot");
            used[static_cast<std::size_t>(lot-world.lots_.begin())]+=part.mass_kg;allocated+=part.mass_kg;object.allocations.push_back(part);
        }
        check(std::abs(allocated-p.mass_kg)<=1e-12*std::max(1.0,p.mass_kg),"allocated matter differs from compiled object mass");
        world.objects_.push_back(std::move(object));
    }
    for (std::size_t i=0;i<world.lots_.size();++i) {
        const auto &lot=world.lots_[i];check(std::abs(lot.remaining_mass_kg+used[i]-lot.initial_mass_kg)<=1e-12*std::max(1.0,lot.initial_mass_kg),"saved inventory/object mass ledger is inconsistent");
    }
    for (const auto &object:world.objects_)insertObject(*world.world_,object);
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
        {"unsupported",Json::array({"deformation","fracture","wood grain","metal plasticity","assemblies"})},
        {"limits",{{"objects",max_objects},{"radius_m",Json::array({.025,.5})},{"box_dimensions_m",Json::array({.025,1})},{"initial_speed_m_s",5},{"initial_spin_rad_s",50}}},
        {"orientation","schema-2 placement.orientation_wxyz is a unit quaternion in world coordinates; box dimensions_m are full local x/y/z lengths"},
        {"support_frame",{{"normal_world",vector(support().normal_world)},{"tangent_world",vector(support().tangent_world)},{"bitangent_world",vector(support().bitangent_world)}}}};
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
            else if (type=="step") {fields(command,{"type","ticks"});step(static_cast<unsigned>(integer(command.at("ticks"),2400)));value={{"time_s",timeSeconds()}};}
            else throw std::invalid_argument("unsupported command");
            results.push_back({{"ok",true},{"result",value}});
        } catch (const std::exception &error) {results.push_back({{"ok",false},{"error",error.what()}});}
    }
    return (batch ? results : results.at(0)).dump(2);
}
}
