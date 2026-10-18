#include "machines/MechanicalCable.hpp"
#include "material/MaterialCatalog.hpp"
#include <cmath>
#include <iostream>
#include <numbers>
#include <stdexcept>

using namespace banjo;
using banjo::machines::MechanicalCable;
using nlohmann::json;
namespace {
constexpr double pi=std::numbers::pi,R=.15,C=.158;
void check(bool yes,const char *why){if(!yes)throw std::runtime_error(why);}
void box(JoltWorld &w,unsigned id,Vec3 at,Vec3 size,MaterialPreset mat,bool fixed){
    RigidBoxDescription d{};d.body_id=id;d.state.center_of_mass_world_m=at;d.dimensions_m=size;
    d.material=makeReferenceMaterial(mat);d.fixed=fixed;w.addBox(d);
}
void wheel(JoltWorld &w,unsigned id,Vec3 at){
    RigidCompoundDescription d{};d.body_id=id;d.material=makeReferenceMaterial(MaterialPreset::Oak);
    d.state.center_of_mass_world_m=at;
    // A solid hub and two non-overlapping flanges; their material volume
    // determines the complete wheel's mass and inertia.
    for(auto [r,length,z]:{std::tuple{R,.04,0.},std::tuple{R+.03,.008,-.024},std::tuple{R+.03,.008,.024}}){
        RigidPrimitive p{};p.kind=PrimitiveKind::Cylinder;p.dimensions_m={2*r,length,2*r};
        const double mass=p.volume()*700;
        RigidCompoundPart part{};part.geometry=p;part.center_local_m={0,0,z};part.rotation_local={std::sqrt(.5),std::sqrt(.5),0,0};
        d.parts.push_back(part);d.mass_kg+=mass;
        // Cylinder's y axis turns onto z. Parallel-axis terms for flanges.
        const auto inertia=p.inertia(mass);
        d.inertia_local_kg_m2.m[0][0]+=inertia.m[0][0]+mass*z*z;
        d.inertia_local_kg_m2.m[1][1]+=inertia.m[2][2]+mass*z*z;
        d.inertia_local_kg_m2.m[2][2]+=inertia.m[1][1];
    }
    w.addCompound(d);
}
void hinge(JoltWorld &w,unsigned a,unsigned b,Vec3 at){
    JoltWorld::HingeDescription d{};d.a=a;d.b=b;d.point_world_m=at;d.axis_world={0,0,1};
    (void)w.addHinge(d);
}
json point(Vec3 p){return {p.x,p.y,p.z};}
void arc(json &path,Vec3 center,double from,double to){
    for(unsigned i=0;i<=24;++i){const double a=from+(to-from)*i/24.;path.push_back(point(center+Vec3{C*std::cos(a),C*std::sin(a),0}));}
}
json rope(json path,double segment){return {{"name","rope"},{"kind","rope"},{"circuit",0},
    {"density_kg_m3",700},{"radius_m",.006},{"segment_m",segment},{"retention_n",1000},
    {"bend_rigidity_n_m2",1e-7},{"loss_time_s",.002},{"path_m",path}};}

void fixedPulley(MaterialPreset support,double segment,double dt,bool freeFrame=false){
    JoltWorld w(0);if(freeFrame)w.setGravity({});
    box(w,1,{0,1.6,.12},{.12,.12,.1},support,!freeFrame);
    wheel(w,4,{0,1.6,0});hinge(w,1,4,{0,1.6,0});
    box(w,2,{-C,.8,0},{.1,.1,.1},MaterialPreset::Glass,false);
    box(w,3,{C,.8,0},{.08,.08,.08},MaterialPreset::Iron,false);
    json path=json::array({point({-C,.85,0})});arc(path,{0,1.6,0},pi,0);path.push_back(point({C,.84,0}));
    auto d=rope(path,segment);if(freeFrame)d["loss_time_s"]=0;
    MechanicalCable strand(w,d,2,3,100);
    const auto start=w.mechanicalTotals(freeFrame?Vec3{}:Vec3{0,-9.81,0});
    const auto initial=strand.report();
    double work=0,maxGap=0,minCore=1,maxSpin=0,slip2=0;unsigned slipN=0;bool contact=false;
    Vec3 impulse{},moment{};
    const unsigned n=unsigned(std::lround((freeFrame?.4:.8)/dt));
    for(unsigned i=0;i<n;++i){
        const auto before=w.snapshot(3);
        Vec3 force{};if(freeFrame&&i<unsigned(.1/dt))force={0,-20,0};
        if(lengthSquared(force)>0)w.pushBodyAt(3,force,before.center_of_mass_world_m);
        w.step(dt);strand.settle(dt);
        const auto after=w.snapshot(3);
        work+=dt*dot(force,(before.linear_velocity_m_s+after.linear_velocity_m_s)*.5);
        impulse+=force*dt;moment+=cross((before.center_of_mass_world_m+after.center_of_mass_world_m)*.5,force*dt);
        const auto rotor=w.snapshot(4);maxSpin=std::max(maxSpin,std::abs(rotor.angular_velocity_rad_s.z));
        const auto r=strand.report();maxGap=std::max(maxGap,r["max_joint_gap_m"].get<double>());
        for(unsigned k=0;k<strand.bodyCount();++k){
            const auto s=w.snapshot(100+k);const auto local=s.center_of_mass_world_m-rotor.center_of_mass_world_m;
            if(std::abs(local.z)<.018&&local.y>-.17&&std::abs(local.x)<.17)minCore=std::min(minCore,std::hypot(local.x,local.y));
            if(w.touching(100+k,4,.002)){
                contact=true;const double rr=std::hypot(local.x,local.y);
                if(rr>1e-9){const Vec3 tangent{-local.y/rr,local.x/rr,0};
                    const double slip=dot(s.linear_velocity_m_s-rotor.linear_velocity_m_s-cross(rotor.angular_velocity_rad_s,local),tangent);
                    slip2+=slip*slip;++slipN;}
            }
        }
    }
    const auto finish=w.mechanicalTotals(freeFrame?Vec3{}:Vec3{0,-9.81,0});
    const double e=finish.mechanicalEnergy()-start.mechanicalEnergy()+strand.report()["elastic_j"].get<double>()-initial["elastic_j"].get<double>()-work;
    const double p=length(finish.linear_momentum_kg_m_s-start.linear_momentum_kg_m_s-impulse);
    const double l=length(finish.angular_momentum_kg_m2_s-start.angular_momentum_kg_m2_s-moment);
    std::cout<<"rope support="<<materialSceneName(support)<<" dt="<<dt<<" segment="<<segment<<" free="<<freeFrame
        <<" rise="<<w.snapshot(2).center_of_mass_world_m.y-.8<<" spin="<<maxSpin<<" contact="<<contact<<" gap="<<maxGap
        <<" core_min="<<minCore<<" slip_rms="<<std::sqrt(slip2/std::max(1u,slipN))<<" work="<<work<<" E_res="<<e<<" P_res="<<p<<" L_res="<<l<<'\n';
    check(strand.connected(),"rope end detached under its declared working load");
    check(contact,"rope never contacted the wheel");check(maxGap<.003,"rope joint gap exceeds 3 mm");
    check(minCore>R+.006-.003,"rope penetrated the hub beyond the 3 mm contact allowance");
    check(e<.005,"complete apparatus gained energy beyond supplied work");
    if(freeFrame){check(p<.0002,"complete free apparatus linear reaction residual");check(l<.0005,"complete free apparatus angular reaction residual");}
    else{check(w.snapshot(2).center_of_mass_world_m.y>.83,"counterweight did not lift its load");check(maxSpin>.01,"contact failed to turn the wheel");}
}

void movablePulley(MaterialPreset support,double segment,double dt,bool enough=true){
    JoltWorld w(0);
    box(w,1,{C,2,.12},{1,.12,.1},support,true);
    wheel(w,4,{2*C,2,0});hinge(w,1,4,{2*C,2,0});
    box(w,2,{0,.85,.10},{.04,.3,.04},MaterialPreset::Aluminum,false);
    wheel(w,5,{0,1,0});hinge(w,2,5,{0,1,0});
    box(w,3,{3*C,1.5,0},{.08,.08,.08},enough?MaterialPreset::Iron:MaterialPreset::Glass,false);
    json path=json::array({point({-C,2,0})});arc(path,{0,1,0},-pi,0);arc(path,{2*C,2,0},pi,0);path.push_back(point({3*C,1.54,0}));
    MechanicalCable strand(w,rope(path,segment),1,3,100);
    const auto initial=w.mechanicalTotals({0,-9.81,0});double maxGap=0;
    for(unsigned i=0;i<unsigned(.5/dt);++i){w.step(dt);strand.settle(dt);maxGap=std::max(maxGap,strand.report()["max_joint_gap_m"].get<double>());}
    const double rise=w.snapshot(5).center_of_mass_world_m.y-1,fall=1.54-strand.report()["segments_m"].back()[1][1].get<double>();
    const auto end=w.mechanicalTotals({0,-9.81,0});
    std::cout<<"tackle support="<<materialSceneName(support)<<" dt="<<dt<<" segment="<<segment<<" enough="<<enough
        <<" rise="<<rise<<" fall="<<fall<<" length_res="<<fall-2*rise<<" gap="<<maxGap
        <<" E_res="<<end.mechanicalEnergy()-initial.mechanicalEnergy()<<'\n';
    check(strand.connected(),"working tackle detached its rope");check(maxGap<.003,"tackle rope gap exceeds 3 mm");
    check(end.mechanicalEnergy()-initial.mechanicalEnergy()<.005,"tackle gained unexplained energy");
    if(enough){check(rise>.03,"routed tackle did not lift");check(std::abs(fall-2*rise)<.02,"tackle does not transfer twice its load travel");}
    else check(rise<-.03,"insufficient counterweight still lifted the tackle");
}
}
int main(int argc,char **argv){try{
    std::cout.setf(std::ios::unitbuf);
    if(argc==4){fixedPulley(MaterialPreset::Glass,std::stod(argv[1]),std::stod(argv[2]),std::stoi(argv[3])!=0);return 0;}
    if(argc==3){movablePulley(MaterialPreset::Glass,std::stod(argv[1]),std::stod(argv[2]));return 0;}
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})
        for(double segment:{.04,.02})for(double refinement:{1.,2.})fixedPulley(material,segment,segment/(.04*1920*refinement));
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(double dt:{1./1920,1./3840}){
        fixedPulley(material,.04,dt,true);movablePulley(material,.04,dt);movablePulley(material,.04,dt,false);
    }
    return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
