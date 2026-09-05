#include "creator/BowlLab.hpp"
#include <nlohmann/json.hpp>
#include <numbers>
#include <stdexcept>
namespace banjo {
namespace {
Quat rotation(const BowlSettings &s){const double a=s.tilt_degrees*std::numbers::pi/360;return {std::cos(a),0,0,std::sin(a)};}
void validate(const BowlSettings &s){
    if(!std::isfinite(s.radius_m)||s.radius_m<.8||s.radius_m>2||!std::isfinite(s.depth_m)||s.depth_m<.2||s.depth_m>1||
       !std::isfinite(s.tilt_degrees)||std::abs(s.tilt_degrees)>20||s.rings<8||s.rings>48||s.sectors<24||s.sectors>192)
        throw std::invalid_argument("bowl dimensions or resolution outside supported bounds");
    if(s.surface!=MaterialPreset::Concrete&&s.surface!=MaterialPreset::Glass&&s.surface!=MaterialPreset::Oak&&s.surface!=MaterialPreset::Iron)
        throw std::invalid_argument("unsupported bowl surface");
}
}
Vec3 bowlPoint(const BowlSettings &s,double x,double z){return rotation(s).rotate({x,s.depth_m*(x*x+z*z)/(s.radius_m*s.radius_m),z});}
std::vector<std::array<Vec3,3>> compileBowl(const BowlSettings &s){
    validate(s);std::vector<std::array<Vec3,3>> out;
    const auto point=[&](unsigned r,unsigned a){double t=2*std::numbers::pi*a/s.sectors,d=s.radius_m*r/s.rings;return bowlPoint(s,d*std::cos(t),d*std::sin(t));};
    for(unsigned r=0;r<s.rings;++r)for(unsigned a=0;a<s.sectors;++a){
        auto p=point(r,a),q=point(r+1,a),v=point(r+1,(a+1)%s.sectors),u=point(r,(a+1)%s.sectors);
        out.push_back({p,v,q});if(r)out.push_back({p,u,v});
    }
    return out;
}
BowlLab::BowlLab(CreatorWorld stock):stock_(std::move(stock)){configure(settings_);}
bool BowlLab::collect(MaterialPreset material){if(running_)throw std::logic_error("pause before collecting");return stock_.collect(std::string(materialPresetName(material))+"-pile");}
ObjectRecipe BowlLab::craftRecipe(MaterialPreset material) const{
    ObjectRecipe recipe;recipe.material=material;recipe.radius_m=.045;recipe.tangent_m=-2+.15*stock_.objects().size();recipe.name=std::string(materialPresetName(material))+" lab ball";return recipe;
}
MatterBodyId BowlLab::craft(MaterialPreset material){
    if(running_||ticks_)throw std::logic_error("reset the experiment before crafting");
    if(stock_.objects().size()>=9)throw std::invalid_argument("lab capacity is nine balls");
    const auto recipe=craftRecipe(material);
    // Build candidate first so support construction failure cannot spend stock.
    auto candidate=CreatorWorld::deserialize(stock_.serialize());
    const auto id=candidate.create("bowl-craft-"+std::to_string(stock_.objects().size()+1),recipe);
    BowlLab staged(std::move(candidate));staged.configure(settings_);*this=std::move(staged);return id;
}
void BowlLab::configure(BowlSettings settings){
    auto triangles=compileBowl(settings);auto world=std::make_unique<JoltWorld>();world->setGravity({0,-9.81,0});
    world->addTriangleSupport(triangles,makeReferenceMaterial(settings.surface));
    std::size_t i=0;
    for(const auto &o:stock_.objects()){
        if(o.recipe.shape!="sphere"||o.recipe.radius_m!=.045||i>=9)throw std::invalid_argument("bowl stock requires at most nine 45 mm radius spheres");
        const double angle=2*std::numbers::pi*(i%3)/3+(i>=6?.45:0),radial=i<3?.115:(i<6?.82:1.0)*settings.radius_m;
        const double x=radial*std::cos(angle),z=radial*std::sin(angle);
        const auto normal=normalized(Vec3{-2*settings.depth_m*x/(settings.radius_m*settings.radius_m),1,-2*settings.depth_m*z/(settings.radius_m*settings.radius_m)});
        const auto position=bowlPoint(settings,x,z)+rotation(settings).rotate(normal)*(o.recipe.radius_m+.005);
        world->addBall({.body_id=o.id,.radius_m=o.recipe.radius_m,.material=makeReferenceMaterial(o.recipe.material),.position_world_m=position});++i;
    }
    initial_energy_j_=world->mechanicalTotals({0,-9.81,0}).mechanicalEnergy();
    world_=std::move(world);triangles_=std::move(triangles);settings_=settings;running_=false;ticks_=0;contacts_=0;
}
void BowlLab::release(){if(stock_.objects().empty())throw std::logic_error("craft balls before release");running_=true;}
void BowlLab::step(unsigned ticks){
    if(ticks>2400)throw std::invalid_argument("step exceeds 2400 ticks");
    if(!running_)return;
    for(unsigned k=0;k<ticks;++k){world_->step(1.0/240);++ticks_;contacts_+=unsigned(world_->drainImpacts().size());}
}
RigidSnapshot BowlLab::state(MatterBodyId id)const{return world_->snapshot(id);}
std::string BowlLab::reportJson()const{
    using nlohmann::json;const auto vec=[](Vec3 v){return json::array({v.x,v.y,v.z});};
    auto objects=json::array();for(const auto &o:stock_.objects()){
        const auto s=state(o.id);const auto m=world_->mechanicalState(o.id);
        objects.push_back({{"id",o.id},{"material",materialPresetName(o.recipe.material)},{"mass_kg",m.mass_kg},{"radius_m",o.recipe.radius_m},
            {"position_m",vec(s.center_of_mass_world_m)},{"velocity_m_s",vec(s.linear_velocity_m_s)},{"angular_velocity_rad_s",vec(s.angular_velocity_rad_s)}});
    }
    return json{{"experiment_version",1},{"fixture","parabolic-bowl-rigid-v1"},{"physics_signature",json::parse(CreatorWorld::physicsSignatureJson())},
        {"settings",{{"radius_m",settings_.radius_m},{"depth_m",settings_.depth_m},{"tilt_degrees",settings_.tilt_degrees},{"surface",materialPresetName(settings_.surface)},{"rings",settings_.rings},{"sectors",settings_.sectors}}},
        {"timestep_s",1.0/240},{"elapsed_s",timeSeconds()},{"initial_mechanical_energy_j",initial_energy_j_},{"mechanical_energy_j",world_->mechanicalTotals({0,-9.81,0}).mechanicalEnergy()},
        {"ball_contact_callbacks",contacts_},{"objects",objects},{"stock",json::parse(stock_.serialize())},
        {"fracture_supported",false},{"fabrication_energy_j",nullptr},
        {"limitations",{"Rigid bodies only; fracture integration pending","Mesh approximation; no curved-support rolling resistance","Energy difference includes contact losses and numerical error; not a heat ledger","Contact callbacks can be speculative; support callbacks excluded","Reset is an authoring operation; exported stock preserves allocations, not trajectory replay"}}}.dump(2);
}
}
