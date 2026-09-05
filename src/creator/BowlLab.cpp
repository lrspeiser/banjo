#include "creator/BowlLab.hpp"
#include <nlohmann/json.hpp>
#include <numbers>
#include <stdexcept>
namespace banjo {
namespace { Quat rotation(const BowlSettings &s){double a=s.tilt_degrees*std::numbers::pi/360;return {std::cos(a),0,0,std::sin(a)};} }
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
    if(settings.impact_trial&&stock_.objects().size()<2)throw std::invalid_argument("impact trial requires two crafted balls");
    auto triangles=compileBowl(settings);auto world=std::make_unique<JoltWorld>();world->setGravity({0,-9.81,0});
    world->addTriangleSupport(triangles,makeReferenceMaterial(settings.surface));
    std::unique_ptr<BondedBowl> bonded;
    if(settings.experimental_fracture){bonded=std::make_unique<BondedBowl>();bonded->bowl_radius=settings.radius_m;bonded->bowl_depth=settings.depth_m;bonded->tilt_degrees=settings.tilt_degrees;bonded->surface=settings.surface;}
    std::size_t i=0;
    for(const auto &o:stock_.objects()){
        if(o.recipe.shape!="sphere"||o.recipe.radius_m!=.045||i>=9)throw std::invalid_argument("bowl stock requires at most nine 45 mm radius spheres");
        const double angle=2*std::numbers::pi*(i%3)/3+(i>=6?.45:0),radial=i<3?.115:(i<6?.82:1.0)*settings.radius_m;
        const double x=radial*std::cos(angle),z=radial*std::sin(angle);
        const auto normal=normalized(Vec3{-2*settings.depth_m*x/(settings.radius_m*settings.radius_m),1,-2*settings.depth_m*z/(settings.radius_m*settings.radius_m)});
        auto position=bowlPoint(settings,x,z)+rotation(settings).rotate(normal)*(o.recipe.radius_m+.005);
        Vec3 velocity;
        if(settings.impact_trial&&i<2){position={i==0?-.055:.055,.15,0};velocity={i==0?10.:-10.,0,0};}
        if(bonded)bonded->add(o.id,o.recipe.material,o.recipe.radius_m,{position,{},velocity,{}});
        world->addBall({.body_id=o.id,.radius_m=o.recipe.radius_m,.material=makeReferenceMaterial(o.recipe.material),.position_world_m=position,.linear_velocity_m_s=velocity});++i;
    }
    if(bonded)bonded->initialize();bonded_=std::move(bonded);
    initial_energy_j_=world->mechanicalTotals({0,-9.81,0}).mechanicalEnergy();
    world_=std::move(world);triangles_=std::move(triangles);settings_=settings;running_=false;ticks_=0;contacts_=0;
}
void BowlLab::presentRecordingFrame(const BondedBowl &frame){
 if(running_||!bonded_||frame.objects.size()!=bonded_->objects.size()||frame.bowl_radius!=settings_.radius_m||frame.bowl_depth!=settings_.depth_m||frame.tilt_degrees!=settings_.tilt_degrees||frame.surface!=settings_.surface)throw std::invalid_argument("recording does not match lab");
 for(unsigned i=0;i<frame.objects.size();++i)if(frame.objects[i].id!=bonded_->objects[i].id||frame.objects[i].material!=bonded_->objects[i].material)throw std::invalid_argument("recording object mismatch");
 *bonded_=frame;ticks_=frame.time()>0?1:0;
}
void BowlLab::release(){if(stock_.objects().empty())throw std::logic_error("craft balls before release");running_=true;}
void BowlLab::step(unsigned ticks){
    if(ticks>2400)throw std::invalid_argument("step exceeds 2400 ticks");
    if(!running_)return;
    for(unsigned k=0;k<ticks;++k){if(bonded_){try{bonded_->advance(1.0/2400);}catch(...){running_=false;throw;}}else{world_->step(1.0/240);contacts_+=unsigned(world_->drainImpacts().size());}++ticks_;}
}
RigidSnapshot BowlLab::state(MatterBodyId id)const{return bonded_?bonded_->state(id):world_->snapshot(id);}
std::string BowlLab::reportJson()const{
    using nlohmann::json;const auto vec=[](Vec3 v){return json::array({v.x,v.y,v.z});};
    auto objects=json::array();for(const auto &o:stock_.objects()){
        const auto s=state(o.id);const auto m=world_->mechanicalState(o.id);
        objects.push_back({{"id",o.id},{"material",materialPresetName(o.recipe.material)},{"mass_kg",m.mass_kg},{"radius_m",o.recipe.radius_m},
            {"position_m",vec(s.center_of_mass_world_m)},{"velocity_m_s",vec(s.linear_velocity_m_s)},{"angular_velocity_rad_s",vec(s.angular_velocity_rad_s)}});
    }
    auto result=json{{"experiment_version",1},{"fixture","parabolic-bowl-rigid-v1"},{"physics_signature",json::parse(CreatorWorld::physicsSignatureJson())},
        {"settings",{{"radius_m",settings_.radius_m},{"depth_m",settings_.depth_m},{"tilt_degrees",settings_.tilt_degrees},{"surface",materialPresetName(settings_.surface)},{"rings",settings_.rings},{"sectors",settings_.sectors}}},
        {"timestep_s",1.0/240},{"elapsed_s",timeSeconds()},{"initial_mechanical_energy_j",initial_energy_j_},{"mechanical_energy_j",world_->mechanicalTotals({0,-9.81,0}).mechanicalEnergy()},
        {"ball_contact_callbacks",contacts_},{"objects",objects},{"stock",json::parse(stock_.serialize())},
        {"fracture_supported",false},{"fabrication_energy_j",nullptr},
        {"limitations",{"Rigid bodies only; fracture integration pending","Mesh approximation; no curved-support rolling resistance","Energy difference includes contact losses and numerical error; not a heat ledger","Contact callbacks can be speculative; support callbacks excluded","Reset is an authoring operation; exported stock preserves allocations, not trajectory replay"}}};
    if(bonded_){const auto &b=*bonded_;result["fixture"]="bonded-cell-bowl-strength-v2";result["fracture_supported"]=true;result["strength_calibrated"]=false;result["catalog_strength_gate"]=true;result["impact_trial"]=settings_.impact_trial;result["elastic_release_to_kinetic_j"]=b.ledger.elastic_release_j;result["solver_model"]="strength-energy-release-lattice-v2";result["relative_energy_error_budget"]=.01;result["maximum_event_overshoot_fraction"]=.02;result["cells_per_ball"]=19;result["timestep_s"]=b.stepLimit();result["elapsed_s"]=b.time();result["initial_mechanical_energy_j"]=b.ledger.initial_energy_j;result["mechanical_energy_j"]=b.energy();
        result["fracture_work_j"]=b.ledger.fracture_work_j;result["event_overshoot_loss_j"]=b.ledger.event_overshoot_j;result["internal_damping_loss_j"]=b.ledger.internal_damping_j;result["contact_damping_loss_j"]=b.ledger.contact_damping_j;result["friction_loss_j"]=b.ledger.friction_j;result["energy_residual_j"]=b.energyResidual();
        result["support_impulse_kg_m_s"]=vec(b.ledger.support_impulse);result["support_angular_impulse_kg_m2_s"]=vec(b.ledger.support_angular_impulse);result["gravity_impulse_kg_m_s"]=vec(b.ledger.gravity_impulse);result["gravity_angular_impulse_kg_m2_s"]=vec(b.ledger.gravity_angular_impulse);
        auto cells=json::array();auto roots=b.components();for(unsigned i=0;i<b.cells.size();++i){auto &c=b.cells[i];cells.push_back({{"cell",i},{"object",b.objects[c.object].id},{"component",roots[i]},{"mass_kg",c.mass},{"collision_radius_m",c.radius},{"inertia_kg_m2",c.inertia},{"position_m",vec(c.x)},{"velocity_m_s",vec(c.v)},{"spin_rad_s",vec(c.spin)}});}result["cells"]=cells;
        auto events=json::array();for(auto &e:b.breaks)events.push_back({{"time_s",e.time_s},{"link",e.link},{"object",b.objects[e.object].id},{"work_j",e.work_j},{"overshoot_j",e.overshoot_j},{"elastic_release_j",e.elastic_release_j}});result["fractures"]=events;
        auto links=json::array();for(auto &e:b.links)links.push_back({{"a",e.a},{"b",e.b},{"live",e.live},{"rest_m",e.rest},{"stiffness_n_m",e.stiffness},{"fracture_work_j",e.work},{"threshold_elastic_energy_j",e.threshold_energy},{"failure_enabled",e.brittle}});result["links"]=links;
        result["limitations"]={"19-cell solid with catalog strength gate; continuum response and contact geometry remain uncalibrated","Glass strength-and-energy-gated tensile failure; oak/iron elastic, failure unsupported","Spherical cell contact proxies and analytic parabolic support differ from smooth rendered sphere/triangle mesh","No Jolt contact in bonded mode; retained cells continue internal motion and repeated contact","Simulation runs slower than real time; no replay persistence or fabrication energy model","Event overshoot and integration residual are numerical quantities, not heat"};
    }
    return result.dump(2);
}
}
