#include "machines/MechanicalCable.hpp"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>

namespace banjo::machines {
namespace {
using json=nlohmann::json;
Vec3 vec(const json &v){if(!v.is_array()||v.size()!=3)throw std::invalid_argument("cable needs xyz points");
    Vec3 r{v.at(0).get<double>(),v.at(1).get<double>(),v.at(2).get<double>()};
    if(!std::isfinite(lengthSquared(r)))throw std::invalid_argument("nonfinite cable point");return r;}
json arr(Vec3 v){return {v.x,v.y,v.z};}
json pose(const RigidSnapshot &s){return {{"p",arr(s.center_of_mass_world_m)},
    {"q",{s.orientation_world.w,s.orientation_world.x,s.orientation_world.y,s.orientation_world.z}},
    {"v",arr(s.linear_velocity_m_s)},{"w",arr(s.angular_velocity_rad_s)}};}
RigidSnapshot state(const json &j){RigidSnapshot s{};s.center_of_mass_world_m=vec(j.at("p"));
    const auto &q=j.at("q");s.orientation_world={q.at(0),q.at(1),q.at(2),q.at(3)};
    s.linear_velocity_m_s=vec(j.at("v"));s.angular_velocity_rad_s=vec(j.at("w"));return s;}
Quat along(Vec3 y){y=normalized(y);const Vec3 axis=cross({0,1,0},y);const double w=1+y.y;
    if(w<1e-10)return {0,1,0,0};const double n=std::sqrt(w*w+lengthSquared(axis));return {w/n,axis.x/n,axis.y/n,axis.z/n};}
double positive(const json &j,const char *key,double fallback,double low,double high){
    double x=j.value(key,fallback);if(!std::isfinite(x)||x<low||x>high)throw std::invalid_argument(std::string("cable invalid ")+key);return x;}
}
MechanicalCable::MechanicalCable(JoltWorld &world,const json &input,MatterBodyId a,MatterBodyId b,MatterBodyId first):
    world_(&world),declaration_(input),ends_{a,b},first_(first) {
    if(!world.contains(a)||!world.contains(b)||input.at("name").get<std::string>().empty())
        throw std::invalid_argument("cable needs existing terminal bodies");
    const double area=positive(input,"area_mm2",2.5,.001,100)*1e-6;
    radius_=positive(input,"radius_m",.003,.001,.03);
    if(area>=std::numbers::pi*radius_*radius_)throw std::invalid_argument("conductor exceeds cable envelope");
    const double copper=positive(input,"conductor_density_kg_m3",8960,100,30000);
    const double insulation=positive(input,"insulation_density_kg_m3",1200,100,5000);
    line_mass_=area*copper+(std::numbers::pi*radius_*radius_-area)*insulation;
    retention_=positive(input,"retention_n",15,.001,10000);
    const double bend=positive(input,"bend_rigidity_n_m2",.00002,1e-10,10);
    const double loss=positive(input,"loss_time_s",.002,0,.1);
    const double step=positive(input,"segment_m",.04,.01,.1);
    const double friction=positive(input,"friction",.5,0,2);
    std::vector<Vec3> nodes;const auto &path=input.at("path_m");
    if(!path.is_array()||path.size()<2||path.size()>64)throw std::invalid_argument("cable path needs 2..64 points");
    nodes.push_back(vec(path.front()));
    for(std::size_t i=1;i<path.size();++i){const Vec3 p=vec(path[i-1]),q=vec(path[i]);
        const double span=length(q-p);if(span<1e-6)continue;
        const auto n=unsigned(std::ceil(span/step));if(nodes.size()+n>257)throw std::invalid_argument("cable exceeds 256 rods");
        for(unsigned k=1;k<=n;++k)nodes.push_back(p+(q-p)*(double(k)/n));}
    if(nodes.size()<2)throw std::invalid_argument("empty cable");
    const RigidSnapshot actual[2]{world.snapshot(a),world.snapshot(b)};
    if(input.contains("_terminal_seed"))for(unsigned i=0;i<2;++i)world.applyRigidState(ends_[i],state(input.at("_terminal_seed")[i]));
    else declaration_["_terminal_seed"]={pose(actual[0]),pose(actual[1])};
    try {
        for(std::size_t i=1;i<nodes.size();++i){const double span=length(nodes[i]-nodes[i-1]);
            RigidSnapshot s{};s.center_of_mass_world_m=(nodes[i]+nodes[i-1])*.5;s.orientation_world=along(nodes[i]-nodes[i-1]);
            const auto id=first+MatterBodyId(i-1);world.addCableRod(id,s,span,radius_,span*line_mass_,friction);
            rods_.push_back(id);spans_.push_back(span);
            if(i>1)world.setPairContactOwner(rods_[i-2],id,PairContactOwner::External);
        }
        for(std::size_t i=0;i<=rods_.size();++i){
            const double span=i==0?spans_.front():i==rods_.size()?spans_.back():(spans_[i-1]+spans_[i])*.5;
            const Vec3 axis=i==rods_.size()?normalized(nodes.back()-nodes[nodes.size()-2]):normalized(nodes[i+1]-nodes[i]);
            const Vec3 tangent=normalized(cross(axis,std::abs(axis.y)<.9?Vec3{0,1,0}:Vec3{1,0,0}));
            JoltWorld::FaceSpringDescription d{};d.a=i?rods_[i-1]:a;d.b=i==rods_.size()?b:rods_[i];
            d.anchor_world_m=nodes[i];d.normal_world=axis;d.tangent_world=tangent;
            // Translation is fixed by native constraint rows (no spring).
            d.translation_stiffness_n_m={1,1,1};
            // Isotropic effective stranded-cable bending/twist, declared in SI.
            const double k=bend/span;d.rotation_stiffness_n_m_rad={k,k,k};
            d.translation_damping_n_s_m=d.translation_stiffness_n_m*loss;
            d.rotation_damping_n_m_s_rad=d.rotation_stiffness_n_m_rad*loss;d.inextensible_translation=true;
            laws_.push_back(d);joints_.push_back(world.addFaceSpring(d));
        }
        // Only the immediate rod is embedded in its terminal's connector.
        world.setPairContactOwner(a,rods_.front(),PairContactOwner::External);
        world.setPairContactOwner(b,rods_.back(),PairContactOwner::External);
        if(input.contains("_states")){
            if(input.at("_states").size()!=rods_.size())throw std::invalid_argument("saved cable rod count mismatch");
            for(std::size_t i=0;i<rods_.size();++i)world.applyRigidState(rods_[i],state(input.at("_states")[i]));
            for(unsigned e=0;e<2;++e){attached_[e]=input.at("_attached")[e];peak_[e]=input.at("_peak")[e];
                if(!attached_[e]){world.removeJoint(e?joints_.back():joints_.front());
                    world.setPairContactOwner(ends_[e],e?rods_.back():rods_.front(),PairContactOwner::Jolt);}}
            released_j_=input.value("_released_j",0.0);
        }
    }catch(...){for(auto j:joints_)if(world.hasJoint(j))world.removeJoint(j);
        for(auto id:rods_)world.removeAndDestroy(id);
        for(unsigned e=0;e<2;++e)world.applyRigidState(ends_[e],actual[e]);throw;}
    for(unsigned e=0;e<2;++e)world.applyRigidState(ends_[e],actual[e]);
}
double MechanicalCable::elasticEnergy(std::size_t i) const {
    if(!world_->hasJoint(joints_[i]))return 0;
    const auto s=world_->faceSpringObservation(joints_[i]);const auto &d=laws_[i];
    const auto energy=[](Vec3 k,Vec3 x){return .5*(k.x*x.x*x.x+k.y*x.y*x.y+k.z*x.z*x.z);};
    return energy(d.rotation_stiffness_n_m_rad,s.rotation_cs_rad);
}
void MechanicalCable::settle(double dt){
    for(unsigned e=0;e<2;++e){const auto i=e?joints_.size()-1:0;if(!attached_[e])continue;
        if(!world_->contains(ends_[e])||!world_->hasJoint(joints_[i])){attached_[e]=false;continue;}
        const double force=length(world_->faceSpringObservation(joints_[i]).linear_impulse_cs_n_s)/dt;
        peak_[e]=std::max(peak_[e],force);
        if(force>retention_){released_j_+=elasticEnergy(i);world_->removeJoint(joints_[i]);attached_[e]=false;
            world_->setPairContactOwner(ends_[e],e?rods_.back():rods_.front(),PairContactOwner::Jolt);
            world_->wake(e?rods_.back():rods_.front());}
    }
}
nlohmann::json MechanicalCable::report() const {
    json segments=json::array();double span=0,mass=0,kinetic=0,potential=0,stored=0,gap=0;
    Vec3 momentum{},angular{};
    for(std::size_t i=0;i<rods_.size();++i){const auto s=world_->snapshot(rods_[i]);const Vec3 half=s.orientation_world.rotate({0,spans_[i]/2,0});
        segments.push_back({arr(s.center_of_mass_world_m-half),arr(s.center_of_mass_world_m+half)});
        const auto m=world_->mechanicalState(rods_[i]);span+=spans_[i];mass+=m.mass_kg;
        kinetic+=.5*m.mass_kg*lengthSquared(s.linear_velocity_m_s)+.5*dot(s.angular_velocity_rad_s,m.inertia_world_kg_m2*s.angular_velocity_rad_s);
        potential-=m.mass_kg*dot(world_->gravity(),s.center_of_mass_world_m);momentum+=m.mass_kg*s.linear_velocity_m_s;
        angular+=cross(s.center_of_mass_world_m,m.mass_kg*s.linear_velocity_m_s)+m.inertia_world_kg_m2*s.angular_velocity_rad_s;
    }
    for(std::size_t i=0;i<joints_.size();++i){stored+=elasticEnergy(i);
        if(world_->hasJoint(joints_[i]))gap=std::max(gap,length(world_->faceSpringObservation(joints_[i]).displacement_cs_m));}
    return {{"name",branch()},{"connected",connected()},{"attached",{attached_[0],attached_[1]}},
        {"radius_m",radius_},{"length_m",span},{"mass_kg",mass},{"segments_m",segments},
        {"retention_n",retention_},{"peak_terminal_force_n",{peak_[0],peak_[1]}},
        {"max_joint_gap_m",gap},
        {"kinetic_j",kinetic},{"gravity_potential_j",potential},{"elastic_j",stored},
        {"pullout_dissipated_j",released_j_},{"momentum_kg_m_s",arr(momentum)},{"angular_momentum_kg_m2_s",arr(angular)}};
}
nlohmann::json MechanicalCable::saved() const {
    json out=declaration_;out["_first"]=first_;out["_states"]=json::array();
    for(auto id:rods_)out["_states"].push_back(pose(world_->snapshot(id)));
    out["_attached"]={attached_[0],attached_[1]};out["_peak"]={peak_[0],peak_[1]};out["_released_j"]=released_j_;return out;
}
}
