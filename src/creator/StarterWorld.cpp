#include "creator/StarterWorld.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <fstream>
#include <set>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace banjo {
namespace {
using Json=nlohmann::json;
constexpr double voxel_volume=1e-6;
std::size_t index(MaterialPreset m) {
    if(m==MaterialPreset::Glass)return 0;if(m==MaterialPreset::Oak)return 1;if(m==MaterialPreset::Iron)return 2;
    throw std::invalid_argument("starter supports glass, oak and iron");
}
void check(bool ok,const char *message) {if(!ok)throw std::invalid_argument(message);}
bool finite(Vec3 p) {return std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z);}
ObjectRecipe box(MaterialPreset material,Vec3 size,std::string name) {
    ObjectRecipe r;r.schema_version=2;r.shape="box";r.material=material;r.dimensions_m=size;r.name=std::move(name);r.tangent_m=0;r.bitangent_m=0;return r;
}
Json vector(Vec3 v) {return Json::array({v.x,v.y,v.z});}
Vec3 vector(const Json &j) {check(j.is_array()&&j.size()==3,"invalid vector");Vec3 v{j.at(0).get<double>(),j.at(1).get<double>(),j.at(2).get<double>()};check(finite(v),"nonfinite vector");return v;}
StarterDesign design(std::string_view id) {for(auto d:StarterWorld::designs())if(d.id==id)return d;throw std::invalid_argument("unknown crafting design");}
}
std::vector<StarterDesign> StarterWorld::designs() {
    ObjectRecipe ball;ball.schema_version=2;ball.name="Glass rolling ball";ball.material=MaterialPreset::Glass;ball.radius_m=.04;ball.tangent_m=0;ball.bitangent_m=0;
    return {
        {"prybar","Wooden pry tool","Gather loose resources with 30% less stamina.",box(MaterialPreset::Oak,{.3,.04,.04},"Wooden pry tool"),1,12,true},
        {"chisel","Iron cutting tool","Cut attached branches; gather with 55% less stamina.",box(MaterialPreset::Iron,{.16,.025,.025},"Iron cutting tool"),2,18,true},
        {"glass-ball","Glass rolling ball","A physical sphere. Watch it fall, roll and collide.",ball,1,10,false},
        {"oak-block","Oak building block","A physical wood block for your clearing.",box(MaterialPreset::Oak,{.12,.12,.12},"Oak block"),1,10,false},
        {"iron-ball","Iron rolling ball","Same-size iron sphere for material comparisons.",[&]{auto r=ball;r.name="Iron rolling ball";r.material=MaterialPreset::Iron;return r;}(),2,14,false},
        {"oak-ball","Oak rolling ball","Same-size wood sphere for material comparisons.",[&]{auto r=ball;r.name="Oak rolling ball";r.material=MaterialPreset::Oak;return r;}(),1,10,false}
    };
}
StarterWorld::StarterWorld() {
    for(unsigned m=0;m<3;++m)for(unsigned n=0;n<6;++n) {
        const auto material=m==0?MaterialPreset::Oak:m==1?MaterialPreset::Iron:MaterialPreset::Glass;
        const Vec3 size=material==MaterialPreset::Oak?Vec3{.2,.08,.08}:Vec3{.08,.08,.08};
        auto r=box(material,size,std::string(materialPresetName(material))+" loose material");
        const Vec3 position{-2.8+static_cast<double>(n%3)*.45,size.y/2+.015,1.0+static_cast<double>(m)*.65+static_cast<double>(n/3)*.25};
        objects_.push_back({next_++,r,{position,{},{},{}},false,false,false,false,0});
    }
    auto branch=box(MaterialPreset::Oak,{.9,.08,.08},"Attached oak branch");
    objects_.push_back({next_++,branch,{{3.65,1.65,-2},{},{},{}},true,true,false,false,0});
    rebuildPhysics();
}
void StarterWorld::rebuildPhysics() {
    auto next=std::make_unique<JoltWorld>();next->setGravity({0,-9.81,0});
    next->addSupportSurface({.frame=makeSupportPlaneFromSlopeDegrees(0),.material=makeReferenceMaterial(MaterialPreset::Concrete),.half_length_tangent_m=12,.half_length_bitangent_m=12});
    next->addBox({10001,{1.65,1.08,.94},makeReferenceMaterial(MaterialPreset::Oak),{{0,.64,-2},{},{},{}},true});
    next->addBox({10002,{.45,3,.45},makeReferenceMaterial(MaterialPreset::Oak),{treePosition(),{},{},{}},true});
    next->addBox({10003,{1.3,.32,.5},makeReferenceMaterial(MaterialPreset::Oak),{{-1.5,.16,-3.5},{},{},{}},true});
    for(const auto &o:objects_)if(!o.collected&&!o.tool) {
        if(o.recipe.shape=="box")next->addBox({o.id,o.recipe.dimensions_m,makeReferenceMaterial(o.recipe.material),o.state});
        else {next->addBall({.body_id=o.id,.radius_m=o.recipe.radius_m,.material=makeReferenceMaterial(o.recipe.material),.position_world_m=o.state.center_of_mass_world_m});next->applyRigidState(o.id,o.state);}
        if(o.attached)next->pinToWorld(o.id);
    }
    physics_=std::move(next);
}
double StarterWorld::inventoryKg(MaterialPreset m) const {return inventory_m3_[index(m)]*makeReferenceMaterial(m).density_kg_m3;}
double StarterWorld::inventoryVoxels(MaterialPreset m) const {return inventory_m3_[index(m)]/voxel_volume;}
std::string StarterWorld::equippedTool() const {
    bool wood=false;for(const auto &o:objects_)if(o.tool) {if(o.recipe.material==MaterialPreset::Iron)return "Iron cutting tool";wood=true;}
    return wood?"Wooden pry tool":"None";
}
double StarterWorld::gatheringCost() const {const auto tool=equippedTool();return tool=="Iron cutting tool"?3.6:tool=="Wooden pry tool"?5.6:8;}
StarterQuote StarterWorld::quote(std::string_view id) const {
    const auto d=design(id);const auto compiled=CreatorWorld::compileRecipe(d.recipe,{.slope_degrees=0});
    StarterQuote q{compiled.mass_kg,inventoryKg(d.recipe.material),std::max(0.0,compiled.mass_kg-inventoryKg(d.recipe.material)),d.stamina,d.level,{}};
    if(q.missing_kg>1e-12)q.missing.push_back("Collect more "+std::string(materialPresetName(d.recipe.material)));
    if(level()<d.level)q.missing.push_back("Reach level "+std::to_string(d.level));
    if(stamina_<d.stamina)q.missing.push_back("Rest to recover stamina");
    if(d.tool&&std::any_of(objects_.begin(),objects_.end(),[&](const auto &o){return o.tool&&o.recipe.name==d.recipe.name;}))q.missing.push_back("Tool already owned");
    if(objects_.size()>=64)q.missing.push_back("Starter object limit reached");
    return q;
}
void StarterWorld::debit(double amount) {check(stamina_>=amount,"Not enough stamina. Rest at the camp.");stamina_-=amount;spent_+=amount;}
std::optional<std::string> StarterWorld::replay(const std::string &id,const std::string &command) const {
    check(!id.empty()&&id.size()<=100,"invalid action ID");
    for(const auto &r:receipts_)if(r.id==id){check(r.command==command,"action ID was already used for another action");return r.result;}
    check(receipts_.size()<512,"starter action history is full");return {};
}
std::string StarterWorld::interact(std::string request,MatterBodyId object,Vec3 eye) {
    const auto command="interact:"+std::to_string(object);if(auto old=replay(request,command))return *old;
    auto candidate=deserialize(serialize());auto result=candidate.interactUnchecked(object,eye);
    candidate.receipts_.push_back({std::move(request),command,result});*this=std::move(candidate);return result;
}
std::string StarterWorld::interactUnchecked(MatterBodyId id,Vec3 eye) {
    check(finite(eye),"invalid player position");auto found=std::find_if(objects_.begin(),objects_.end(),[&](const auto &o){return o.id==id;});
    check(found!=objects_.end()&&!found->collected&&!found->tool,"resource is no longer available");
    check(length(eye-found->state.center_of_mass_world_m)<=3.2,"Move closer to reach it");
    if(found->attached) {
        check(equippedTool()=="Iron cutting tool","Requires an iron cutting tool (level 2 craft)");
        debit(5);found->cut_fraction=std::min(1.0,found->cut_fraction+.25);
        if(found->cut_fraction>=1) {found->attached=false;physics_->releaseFromWorld(id);xp_+=10;return "Branch severed. Let it fall, then click to collect its wood.";}
        return "Cutting branch: "+std::to_string(static_cast<int>(found->cut_fraction*100))+"%";
    }
    check(length(found->state.linear_velocity_m_s)<1.5,"Let the moving object settle before collecting it");
    debit(gatheringCost());inventory_m3_[index(found->recipe.material)]+=found->recipe.geometry().volume();
    found->collected=true;physics_->removeAndDestroy(id);xp_+=5;
    return "Collected "+std::string(materialPresetName(found->recipe.material))+" into raw voxel inventory. +5 XP";
}
std::string StarterWorld::craft(std::string request,std::string_view id,Vec3 eye) {
    const auto command="craft:"+std::string(id);if(auto old=replay(request,command))return *old;
    auto candidate=deserialize(serialize());auto result=candidate.craftUnchecked(id,eye);
    candidate.receipts_.push_back({std::move(request),command,result});*this=std::move(candidate);return result;
}
std::string StarterWorld::craftUnchecked(std::string_view id,Vec3 eye) {
    check(finite(eye)&&length(eye-benchPosition())<=3.2,"Move to the crafting table");
    auto d=design(id);const auto q=quote(id);check(q.ready(),"Missing material, stamina, level or tool capacity; review the design");
    const Vec3 position{0,1.4,-2};
    if(!d.tool)for(const auto &o:objects_)if(!o.collected&&!o.tool)
        check(!primitivesOverlap(d.recipe.geometry(),position,{},o.recipe.geometry(),o.state.center_of_mass_world_m,o.state.orientation_world),"Crafting output is occupied. Collect the previous object first.");
    debit(d.stamina);auto &stock=inventory_m3_[index(d.recipe.material)];stock-=d.recipe.geometry().volume();check(stock>=-1e-15,"material deficit");stock=std::max(0.0,stock);
    objects_.push_back({next_++,d.recipe,{position,{},{},{}},false,false,false,d.tool,0});xp_+=10;rebuildPhysics();
    return d.tool?"Crafted and equipped "+d.label+". +10 XP":"Crafted "+d.label+" on the table. +10 XP";
}
void StarterWorld::rest(double seconds) {
    check(std::isfinite(seconds)&&seconds>=0&&seconds<=1,"rest interval must be 0–1 second");
    const double gain=std::min(100-stamina_,seconds*12);stamina_+=gain;restored_+=gain;
}
void StarterWorld::step(unsigned ticks) {
    check(ticks<=2400,"step exceeds ten seconds");
    for(unsigned i=0;i<ticks;++i){physics_->step(1.0/240);++ticks_;for(auto &o:objects_)if(!o.collected&&!o.tool)o.state=physics_->snapshot(o.id);(void)physics_->drainImpacts();}
}
std::string StarterWorld::serialize() const {
    Json objects=Json::array(),receipts=Json::array();
    for(const auto &o:objects_)objects.push_back({{"id",o.id},{"recipe",Json::parse(CreatorWorld::recipeJson(o.recipe))},{"position",vector(o.state.center_of_mass_world_m)},
        {"orientation",Json::array({o.state.orientation_world.w,o.state.orientation_world.x,o.state.orientation_world.y,o.state.orientation_world.z})},
        {"velocity",vector(o.state.linear_velocity_m_s)},{"spin",vector(o.state.angular_velocity_rad_s)},
        {"branch",o.branch},{"attached",o.attached},{"collected",o.collected},{"tool",o.tool},{"cut",o.cut_fraction}});
    for(const auto &r:receipts_)receipts.push_back({{"id",r.id},{"command",r.command},{"result",r.result}});
    return Json{{"starter_version",1},{"rules","starter-stamina-v1/whole-branch-cut-v1/raw-volume-v1"},{"inventory_m3",inventory_m3_},{"stamina",stamina_},{"spent",spent_},{"restored",restored_},{"xp",xp_},{"ticks",ticks_},{"next_id",next_},{"objects",objects},{"receipts",receipts}}.dump(2);
}
StarterWorld StarterWorld::deserialize(std::string_view document) {
    check(document.size()<=1024*1024,"starter save exceeds 1 MiB");
    std::vector<std::set<std::string>> keys;
    const auto j=Json::parse(document,[&](int depth,Json::parse_event_t event,Json &value){check(depth<=24,"starter save nesting exceeds 24");if(event==Json::parse_event_t::object_start)keys.emplace_back();if(event==Json::parse_event_t::key)check(keys.back().insert(value.get<std::string>()).second,"duplicate starter save field");if(event==Json::parse_event_t::object_end)keys.pop_back();return true;});
    check(j.is_object()&&j.size()==11,"unexpected starter save fields");check(j.at("starter_version")==1&&j.at("rules")=="starter-stamina-v1/whole-branch-cut-v1/raw-volume-v1","incompatible starter rules");
    StarterWorld w;const auto sources=w.objects_;w.objects_.clear();w.receipts_.clear();w.inventory_m3_=j.at("inventory_m3").get<std::array<double,3>>();
    w.stamina_=j.at("stamina").get<double>();w.spent_=j.at("spent").get<double>();w.restored_=j.at("restored").get<double>();
    check(std::isfinite(w.stamina_+w.spent_+w.restored_)&&w.stamina_>=0&&w.stamina_<=100&&w.spent_>=0&&w.restored_>=0&&std::abs(100+w.restored_-w.spent_-w.stamina_)<1e-8,"invalid stamina ledger");
    check(j.at("xp").is_number_unsigned()&&j.at("ticks").is_number_unsigned()&&j.at("next_id").is_number_unsigned(),"progress counters must be nonnegative integers");
    check(j.at("xp").get<std::uint64_t>()<=10000&&j.at("next_id").get<std::uint64_t>()<=65,"progress counters exceed limits");
    w.xp_=j.at("xp").get<unsigned>();w.ticks_=j.at("ticks").get<std::uint64_t>();w.next_=j.at("next_id").get<MatterBodyId>();
    check(w.xp_<=10000&&w.ticks_<=240ULL*86400*365&&w.next_>=20&&w.next_<=65,"invalid starter bounds");
    check(j.at("objects").is_array()&&j.at("objects").size()>=19&&j.at("objects").size()<=64,"invalid object count");
    std::array<double,3> balance=w.inventory_m3_;
    for(auto v:balance)check(std::isfinite(v)&&v>=0,"invalid stock");
    for(const auto &v:j.at("objects")) {
        check(v.is_object()&&v.size()==11&&v.at("id").is_number_unsigned()&&v.at("id").get<std::uint64_t>()<=64,"invalid object fields or ID");
        StarterObject o;o.id=v.at("id").get<MatterBodyId>();o.recipe=CreatorWorld::parseRecipe(v.at("recipe").dump());(void)CreatorWorld::compileRecipe(o.recipe,{.slope_degrees=0});
        check(o.id==w.objects_.size()+1,"unordered object ID");
        o.state.center_of_mass_world_m=vector(v.at("position"));o.state.linear_velocity_m_s=vector(v.at("velocity"));o.state.angular_velocity_rad_s=vector(v.at("spin"));
        const auto &q=v.at("orientation");check(q.is_array()&&q.size()==4,"invalid orientation");o.state.orientation_world={q[0].get<double>(),q[1].get<double>(),q[2].get<double>(),q[3].get<double>()};
        const auto r=o.state.orientation_world;check(std::isfinite(r.w+r.x+r.y+r.z)&&std::abs(r.w*r.w+r.x*r.x+r.y*r.y+r.z*r.z-1)<1e-5,"invalid rotation");
        o.branch=v.at("branch").get<bool>();o.attached=v.at("attached").get<bool>();o.collected=v.at("collected").get<bool>();o.tool=v.at("tool").get<bool>();o.cut_fraction=v.at("cut").get<double>();
        check(std::isfinite(o.cut_fraction)&&o.cut_fraction>=0&&o.cut_fraction<=1&&(!o.attached||(o.branch&&!o.collected&&o.cut_fraction<1)),"invalid branch state");
        if(o.id<=19)check(CreatorWorld::recipeJson(o.recipe)==CreatorWorld::recipeJson(sources[o.id-1].recipe)&&o.branch==(o.id==19)&&!o.tool,"starter source declaration changed");
        else {bool match=false;for(const auto &d:designs())if(CreatorWorld::recipeJson(o.recipe)==CreatorWorld::recipeJson(d.recipe)&&o.tool==d.tool)match=true;check(match&&!o.branch,"unsupported crafted declaration");}
        check((o.branch||o.cut_fraction==0)&&(!o.tool||!o.collected),"invalid tool or cut state");
        if(!o.collected)balance[index(o.recipe.material)]+=o.recipe.geometry().volume();w.objects_.push_back(o);
    }
    const std::array<double,3> original{6*.08*.08*.08,6*.2*.08*.08+.9*.08*.08,6*.08*.08*.08};
    for(std::size_t i=0;i<3;++i)check(std::abs(balance[i]-original[i])<1e-12,"raw stock/object material balance does not close");
    check(w.next_==w.objects_.size()+1,"invalid next identity");
    unsigned expected_xp=static_cast<unsigned>(w.objects_.size()-19)*10;
    for(const auto &o:w.objects_){if(o.collected)expected_xp+=5;if(o.branch&&o.cut_fraction==1)expected_xp+=10;}
    check(w.xp_==expected_xp,"experience disagrees with gathering/crafting progress");
    const auto &receipts=j.at("receipts");check(receipts.is_array()&&receipts.size()<=512,"invalid history");std::set<std::string> ids;
    for(const auto &v:receipts){Receipt r{v.at("id").get<std::string>(),v.at("command").get<std::string>(),v.at("result").get<std::string>()};check(!r.id.empty()&&r.id.size()<=100&&r.command.size()<150&&r.result.size()<512&&ids.insert(r.id).second,"invalid receipt");w.receipts_.push_back(std::move(r));}
    w.rebuildPhysics();return w;
}
void StarterWorld::save(const std::filesystem::path &path) const {
    const auto text=serialize();check(text.size()<=1024*1024,"save exceeds 1 MiB");auto pending=path;pending+=".pending";check(!std::filesystem::exists(pending),"pending save exists");
    std::ofstream stream(pending,std::ios::binary);stream<<text;stream.close();check(bool(stream),"cannot write starter save");
#ifdef _WIN32
    check(MoveFileExW(pending.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)!=0,"cannot publish starter save");
#else
    std::filesystem::rename(pending,path);
#endif
}
StarterWorld StarterWorld::load(const std::filesystem::path &path) {
    check(std::filesystem::file_size(path)<=1024*1024,"save exceeds 1 MiB");std::ifstream f(path,std::ios::binary);check(bool(f),"cannot read starter save");const std::string document{std::istreambuf_iterator<char>(f),{}};return deserialize(document);
}
}
