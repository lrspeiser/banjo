#include "platform/VoxelImpactWorld.hpp"
#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <map>
#include <numeric>
#include <set>
#include <stdexcept>
namespace banjo {
namespace {
using Json=nlohmann::json;
Json v(Vec3 x){return {x.x,x.y,x.z};}
MaterialPreset preset(std::string s){for(auto p:kMaterialPresets)if(materialSceneName(p)==s)return p;throw std::invalid_argument("unknown material");}
double scalar(const Json &j,const char *key,double fallback,double lo,double hi){
    const auto value=j.value(key,Json(fallback));if(!value.is_number()||value.is_boolean())throw std::invalid_argument(key);
    const double x=value.get<double>();if(!std::isfinite(x)||x<lo||x>hi)throw std::invalid_argument(key);return x;
}
double quadratic(Vec3 k,Vec3 x){return .5*(k.x*x.x*x.x+k.y*x.y*x.y+k.z*x.z*x.z);}
MaterialDefinition contact(MaterialDefinition m){m.model=MaterialModel::RigidOnly;return m;}
}
struct VoxelImpactWorld::Impl {
    struct Cell {unsigned object;MatterBodyId id;Vec3 size,initial;double mass;std::string material;bool fixed;};
    struct Bond {unsigned a,b,joint;double area,iy,iz,width,height,strength,shear,gc;Vec3 k,r,damping,rotation_damping;bool brittle,live{true};double energy{};};
    struct Pair {unsigned a,b;int bond{-1};};
    JoltWorld world{0,{32768,16384}};
    Json declaration,events=Json::array();std::vector<Cell> cells;std::vector<Bond> bonds;std::vector<Pair> internal;
    double linear_velocity_quadratic{},peak_spin{};unsigned spin_limit_samples{};
    double material_damping{},implicit_elastic_loss{},spring_endpoint_work{},spring_geometry_change{},spring_residual_work{},max_spring_residual_n{};
    double sweep_wall_ms{},trial_wall_ms{},observation_wall_ms{},native_step_wall_ms{},totals_wall_ms{},candidate_faces_wall_ms{};
    double feature{},dt{},time{},initial_energy{},fracture{},discarded_elastic{},max_wall_ms{},peak_stress_ratio{};
    unsigned ticks{},broken{},substeps{},rejected{};Vec3 gravity;MechanicalTotals initial,totals;
    std::vector<unsigned> components() const {
        std::vector<unsigned> p(cells.size());std::iota(p.begin(),p.end(),0);
        auto root=[&](unsigned x){while(p[x]!=x){p[x]=p[p[x]];x=p[x];}return x;};
        for(const auto &b:bonds)if(b.live)p[root(b.b)]=root(b.a);
        for(auto &x:p)x=root(x);return p;
    }
    void filtering(){const auto roots=components();for(const auto &p:internal){
        const bool joined=p.bond>=0?bonds[unsigned(p.bond)].live:roots[p.a]==roots[p.b];
        world.setPairContactOwner(cells[p.a].id,cells[p.b].id,joined?PairContactOwner::External:PairContactOwner::Jolt);
    }}
    unsigned cell(unsigned object,Vec3 size,Vec3 position,MaterialPreset p,bool fixed=false){
        const auto m=makeReferenceMaterial(p);const unsigned index=unsigned(cells.size());const MatterBodyId id=100+index;
        world.addBox({id,size,contact(m),{position,{}, {},{}},fixed});
        if(!fixed)world.setContinuousCollision(id,false);
        cells.push_back({object,id,size,position,size.x*size.y*size.z*m.density_kg_m3,std::string(materialSceneName(p)),fixed});return index;
    }
    void connect(unsigned a,unsigned b,Vec3 normal,Vec3 tangent,double length0,double width,double height,const MaterialDefinition &m){
        const double area=width*height,iy=width*height*height*height/12,iz=height*width*width*width/12;
        const double g=m.young_modulus_pa/(2*(1+m.poisson_ratio));
        const Vec3 k{m.young_modulus_pa*area/length0,g*area/length0,g*area/length0};
        // Polar-area torsion approximation; not a calibrated Saint-Venant law.
        const Vec3 r{g*(iy+iz)/length0,m.young_modulus_pa*iy/length0,m.young_modulus_pa*iz/length0};
        const double mass=cells[a].mass*cells[b].mass/(cells[a].mass+cells[b].mass);
        const auto inertia=RigidPrimitive{PrimitiveKind::Box,0,cells[a].size}.inertia(cells[a].mass);
        const double reduced_i=std::min({inertia.m[0][0],inertia.m[1][1],inertia.m[2][2]})/2;
        const auto damp=[&](Vec3 s,double reduced){return Vec3{2*m.damping_ratio*std::sqrt(s.x*reduced),2*m.damping_ratio*std::sqrt(s.y*reduced),2*m.damping_ratio*std::sqrt(s.z*reduced)};};
        const auto joint=world.addFaceSpring({cells[a].id,cells[b].id,(cells[a].initial+cells[b].initial)/2,normal,tangent,k,r,damp(k,mass),damp(r,reduced_i)});
        bonds.push_back({a,b,joint,area,iy,iz,width,height,m.tensile_strength_pa,m.shear_strength_pa,m.fracture_energy_j_m2,k,r,damp(k,mass),damp(r,reduced_i),m.model==MaterialModel::BrittleBond});
    }
    void grid(unsigned object,MaterialPreset p,Vec3 dimensions,Vec3 center,unsigned nx,unsigned ny,unsigned nz,bool round){
        const Vec3 h{dimensions.x/nx,dimensions.y/ny,dimensions.z/nz};std::map<std::array<int,3>,unsigned> ids;
        for(unsigned x=0;x<nx;++x)for(unsigned y=0;y<ny;++y)for(unsigned z=0;z<nz;++z){
            const Vec3 local{(x+.5)*h.x-dimensions.x/2,(y+.5)*h.y-dimensions.y/2,(z+.5)*h.z-dimensions.z/2};
            if(round&&4*(local.x*local.x/(dimensions.x*dimensions.x)+local.y*local.y/(dimensions.y*dimensions.y)+local.z*local.z/(dimensions.z*dimensions.z))>1)continue;
            ids[{int(x),int(y),int(z)}]=cell(object,h,center+local,p);
        }
        const auto m=makeReferenceMaterial(p);
        for(const auto &[g,a]:ids)for(int dx=-1;dx<=1;++dx)for(int dy=-1;dy<=1;++dy)for(int dz=-1;dz<=1;++dz){
            const auto it=ids.find({g[0]+dx,g[1]+dy,g[2]+dz});if(it==ids.end()||it->second<=a)continue;
            int bond=-1;
            if(dx*dx+dy*dy+dz*dz==1){bond=int(bonds.size());
                if(dx)connect(a,it->second,{double(dx),0,0},{0,1,0},h.x,h.y,h.z,m);
                if(dy)connect(a,it->second,{0,double(dy),0},{0,0,1},h.y,h.z,h.x,m);
                if(dz)connect(a,it->second,{0,0,double(dz)},{1,0,0},h.z,h.x,h.y,m);
            }
            internal.push_back({a,it->second,bond});
        }
    }
    explicit Impl(const Json &d):declaration(d){
        const std::set<std::string> keys{"sheet","ball","mass_kg","height_m","thickness_m","resolution","support_gap_m","offset_x_m","offset_z_m","dt_s","ball_enabled","gravity_m_s2","solver_iterations"};
        for(auto i=d.begin();i!=d.end();++i)if(!keys.contains(i.key()))throw std::invalid_argument("unknown voxel experiment field");
        const auto sheet=preset(d.value("sheet",std::string("glass"))),ball=preset(d.value("ball",std::string("iron")));
        const double requested=scalar(d,"resolution",8,4,16);const unsigned n=unsigned(requested);
        if(n!=requested||(n!=4&&n!=8&&n!=12&&n!=16))throw std::invalid_argument("resolution must be 4, 8, 12 or 16");
        const double thickness=scalar(d,"thickness_m",.004,.002,.04),gap=scalar(d,"support_gap_m",.32,.20,.36);
        const double mass=scalar(d,"mass_kg",1,.1,5),height=scalar(d,"height_m",10,.05,10);
        const double x=scalar(d,"offset_x_m",0,-.8,.8),z=scalar(d,"offset_z_m",0,-.8,.8);
        dt=scalar(d,"dt_s",1./960,1./3840,1./240);
        const double g=scalar(d,"gravity_m_s2",-9.81,-9.81,0);gravity={0,g,0};world.setGravity(gravity);
        const double requested_iterations=scalar(d,"solver_iterations",96,16,256);
        if(requested_iterations!=std::floor(requested_iterations))throw std::invalid_argument("solver_iterations must be integral");
        world.setContactSolverIterations(unsigned(requested_iterations),4);
        feature=thickness;world.configureVoxelContacts(thickness);
        world.setImpactObservationsEnabled(false);
        // Supports/floor are declared anchored coarse voxels; no fixed sheet edges.
        cell(3,{.06,.5,.46},{-gap/2,.25,0},MaterialPreset::Concrete,true);
        cell(4,{.06,.5,.46},{gap/2,.25,0},MaterialPreset::Concrete,true);
        for(int xx=-1;xx<=1;++xx)for(int zz=-1;zz<=1;++zz)cell(5,{1,.1,1},{double(xx),-.05,double(zz)},MaterialPreset::Concrete,true);
        grid(1,sheet,{.4,thickness,.4},{0,.5+thickness/2,0},n,1,n,false);
        const auto enabled=d.value("ball_enabled",Json(true));if(!enabled.is_boolean())throw std::invalid_argument("ball_enabled must be boolean");
        if(enabled.get<bool>()){
            const double diameter=std::cbrt(mass/(makeReferenceMaterial(ball).density_kg_m3*.5));
            grid(2,ball,{diameter,diameter,diameter},{x,.5+thickness+height+diameter/2,z},4,4,4,true);
        }
        if(internal.size()>4096)throw std::invalid_argument("voxel neighbour budget exceeded");
        filtering();initial=totals=world.mechanicalTotals(gravity);initial_energy=initial.mechanicalEnergy();
    }
    void interval(double h,unsigned depth=0){
        const auto sweep_start=std::chrono::steady_clock::now();
        double minBallY=1e20,maxSpeed=0;
        std::vector<RigidSnapshot> before_states;before_states.reserve(cells.size());
        for(const auto &c:cells){const auto s=world.snapshot(c.id);before_states.push_back(s);if(!c.fixed){maxSpeed=std::max(maxSpeed,length(s.linear_velocity_m_s)+length(s.angular_velocity_rad_s)*length(c.size)/2);if(c.object==2)minBallY=std::min(minBallY,s.center_of_mass_world_m.y-length(c.size)/2);}}
        sweep_wall_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-sweep_start).count();
        if(minBallY<.65&&maxSpeed*h>feature*.05){if(depth>=14)throw std::runtime_error("voxel swept distance gate refused");interval(h/2,depth+1);interval(h/2,depth+1);return;}
        const auto observation_start=std::chrono::steady_clock::now();
        std::vector<JoltWorld::FaceSpringObservation> faces_before(bonds.size()),faces_after(bonds.size());
        double before_elastic=0;
        for(unsigned i=0;i<bonds.size();++i)if(bonds[i].live){const auto &b=bonds[i];faces_before[i]=world.faceSpringObservation(b.joint);before_elastic+=quadratic(b.k,faces_before[i].displacement_cs_m)+quadratic(b.r,faces_before[i].rotation_cs_rad);}
        observation_wall_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-observation_start).count();
        const double before=totals.mechanicalEnergy()+before_elastic;
        double candidateEnergy=0;MechanicalTotals candidateTotals;
        const auto trial_start=std::chrono::steady_clock::now();
        const bool accepted=world.runReversibleTrial([&]{
            const auto native_start=std::chrono::steady_clock::now();world.step(h);
            const auto totals_start=std::chrono::steady_clock::now();
            native_step_wall_ms+=std::chrono::duration<double,std::milli>(totals_start-native_start).count();
            candidateTotals=world.mechanicalTotals(gravity);double after_elastic=0;
            const auto faces_start=std::chrono::steady_clock::now();
            totals_wall_ms+=std::chrono::duration<double,std::milli>(faces_start-totals_start).count();
            for(unsigned i=0;i<bonds.size();++i)if(bonds[i].live){const auto &b=bonds[i];faces_after[i]=world.faceSpringObservation(b.joint);after_elastic+=quadratic(b.k,faces_after[i].displacement_cs_m)+quadratic(b.r,faces_after[i].rotation_cs_rad);}
            candidate_faces_wall_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-faces_start).count();
            const double after=candidateTotals.mechanicalEnergy()+after_elastic;candidateEnergy=after;
            return std::isfinite(after)&&after-before<=1e-5*std::max(1.,std::abs(before))+1e-6&&after+fracture+discarded_elastic-initial_energy<=.1;
        });
        trial_wall_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-trial_start).count();
        if(!accepted){++rejected;if(depth>=14)throw std::runtime_error("native integration energy gate refused at "+std::to_string(time)+" s: before="+std::to_string(before)+", candidate="+std::to_string(candidateEnergy)+", h="+std::to_string(h)+"; last accepted state retained");interval(h/2,depth+1);interval(h/2,depth+1);return;}
        std::vector<RigidSnapshot> after_states;after_states.reserve(cells.size());for(unsigned i=0;i<cells.size();++i){const auto &c=cells[i];after_states.push_back(world.snapshot(c.id));if(!c.fixed){linear_velocity_quadratic+=.5*c.mass*lengthSquared(after_states[i].linear_velocity_m_s-before_states[i].linear_velocity_m_s);peak_spin=std::max(peak_spin,length(after_states[i].angular_velocity_rad_s));if(length(after_states[i].angular_velocity_rad_s)>=999.99)++spin_limit_samples;}}
        for(unsigned i=0;i<bonds.size();++i)if(bonds[i].live){
            const auto &b=bonds[i];const auto &geometry=faces_before[i],&response=faces_after[i];
            const auto &a=before_states[b.a],&c=before_states[b.b],&aa=after_states[b.a],&cc=after_states[b.b];
            // SixDOF applies equal/opposite linear impulses at B's anchor.
            const auto arm_a=geometry.anchor_b_world_m-a.center_of_mass_world_m,arm_b=geometry.anchor_b_world_m-c.center_of_mass_world_m;
            const auto relative=cc.linear_velocity_m_s+cross(cc.angular_velocity_rad_s,arm_b)-aa.linear_velocity_m_s-cross(aa.angular_velocity_rad_s,arm_a);
            const auto spin=cc.angular_velocity_rad_s-aa.angular_velocity_rad_s;
            Vec3 speed{},rate{};
            double *vs[]={&speed.x,&speed.y,&speed.z},*ws[]={&rate.x,&rate.y,&rate.z};
            for(unsigned axis=0;axis<3;++axis){*vs[axis]=dot(relative,geometry.translation_axes_world[axis]);*ws[axis]=dot(spin,geometry.rotation_axes_world[axis]);}
            const auto q0=geometry.displacement_cs_m,r0=geometry.rotation_error_cs_rad;
            material_damping+=2*h*(quadratic(b.damping,speed)+quadratic(b.rotation_damping,rate));
            implicit_elastic_loss+=h*h*(quadratic(b.k,speed)+quadratic(b.r,rate));
            const double work=dot(response.linear_impulse_cs_n_s,speed)+dot(response.angular_impulse_cs_n_m_s,rate);spring_endpoint_work+=work;
            const double predicted=quadratic(b.k,q0+speed*h)+quadratic(b.r,r0+rate*h);
            const double actual=quadratic(b.k,response.displacement_cs_m)+quadratic(b.r,response.rotation_cs_rad);
            const double old_native=quadratic(b.k,q0)+quadratic(b.r,r0);
            const double old_physical=quadratic(b.k,q0)+quadratic(b.r,geometry.rotation_cs_rad);
            // Compare increments, not absolute potentials. The native motor's
            // 2*sin(angle/2) error differs from the reported physical angle.
            // Counting that absolute offset every step would invent a loss.
            spring_geometry_change+=(actual-old_physical)-(predicted-old_native);
            spring_residual_work+=work+predicted-old_native+2*h*(quadratic(b.damping,speed)+quadratic(b.rotation_damping,rate))+h*h*(quadratic(b.k,speed)+quadratic(b.r,rate));
            const Vec3 residual{response.linear_impulse_cs_n_s.x/h+b.k.x*q0.x+(b.damping.x+h*b.k.x)*speed.x,
                response.linear_impulse_cs_n_s.y/h+b.k.y*q0.y+(b.damping.y+h*b.k.y)*speed.y,
                response.linear_impulse_cs_n_s.z/h+b.k.z*q0.z+(b.damping.z+h*b.k.z)*speed.z};
            max_spring_residual_n=std::max(max_spring_residual_n,length(residual));
        }

        time+=h;++substeps;
        bool changed=false;
        for(unsigned i=0;i<bonds.size();++i)if(bonds[i].live){
            auto &b=bonds[i];const auto &s=faces_after[i];b.energy=quadratic(b.k,s.displacement_cs_m)+quadratic(b.r,s.rotation_cs_rad);
            const auto f=s.linear_impulse_cs_n_s/h,m=s.angular_impulse_cs_n_m_s/h;
            const double tensile=std::max(0.,-f.x)/b.area+std::abs(m.y)*b.height/(2*b.iy)+std::abs(m.z)*b.width/(2*b.iz);
            const double shear=std::hypot(f.y,f.z)/b.area+std::abs(m.x)*std::max(b.width,b.height)/(2*(b.iy+b.iz));
            const double ratio=std::max(tensile/b.strength,shear/b.shear);peak_stress_ratio=std::max(peak_stress_ratio,ratio);
            if(b.brittle&&ratio>=1&&b.energy>=b.gc*b.area){
                const double work=b.gc*b.area;fracture+=work;discarded_elastic+=b.energy-work;
                b.live=false;changed=true;++broken;world.removeJoint(b.joint);
                if(events.size()<4096)events.push_back({{"time_s",time},{"object",cells[b.a].object},{"a",cells[b.a].id},{"b",cells[b.b].id},{"stress_ratio",ratio},{"stored_energy_j",b.energy},{"fracture_work_j",work}});
            }
        }
        if(changed)filtering();totals=candidateTotals;
    }
    void step(){const auto start=std::chrono::steady_clock::now();interval(dt);++ticks;
        max_wall_ms=std::max(max_wall_ms,std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());
    }
};
VoxelImpactWorld::VoxelImpactWorld(const std::string &source):impl_(std::make_unique<Impl>(Json::parse(source))){}
VoxelImpactWorld::~VoxelImpactWorld()=default;
void VoxelImpactWorld::step(unsigned count){if(count<1||count>64||impl_->time+count*impl_->dt>4.000001)throw std::invalid_argument("bounded steps/duration exceeded");for(unsigned i=0;i<count;++i)impl_->step();}
std::string VoxelImpactWorld::snapshotJson() const {
    const auto &w=*impl_;const auto roots=w.components();Json cells=Json::array(),objects=Json::array();
    double mass=0,elastic=0;for(const auto &b:w.bonds)if(b.live)elastic+=b.energy;
    for(unsigned i=0;i<w.cells.size();++i){const auto &c=w.cells[i];const auto s=w.world.snapshot(c.id);const auto q=s.orientation_world;
        if(!c.fixed)mass+=c.mass;
        cells.push_back({{"id",c.id},{"object",c.object},{"component",roots[i]},{"size_m",v(c.size)},{"position_m",v(s.center_of_mass_world_m)},{"quaternion_wxyz",{q.w,q.x,q.y,q.z}},{"velocity_m_s",v(s.linear_velocity_m_s)},{"spin_rad_s",v(s.angular_velocity_rad_s)},{"mass_kg",c.mass},{"material",c.material},{"fixed",c.fixed}});
    }
    for(unsigned object:{1U,2U}){double objectmass=0;unsigned count=0,breaks=0;std::set<unsigned> parts;Vec3 center{},speed{};double maxtravel=0;
        for(unsigned i=0;i<w.cells.size();++i)if(w.cells[i].object==object){const auto &c=w.cells[i];const auto s=w.world.snapshot(c.id);objectmass+=c.mass;++count;parts.insert(roots[i]);center+=s.center_of_mass_world_m*c.mass;speed+=s.linear_velocity_m_s*c.mass;maxtravel=std::max(maxtravel,length(s.center_of_mass_world_m-c.initial));}
        for(const auto &b:w.bonds)if(!b.live&&w.cells[b.a].object==object)++breaks;
        objects.push_back({{"id",object},{"mass_kg",objectmass},{"cells",count},{"pieces",parts.size()},{"broken_faces",breaks},{"center_m",v(objectmass?center/objectmass:Vec3{})},{"velocity_m_s",v(objectmass?speed/objectmass:Vec3{})},{"max_travel_m",maxtravel}});
    }
    return Json{{"schema","banjo.voxel-impact.v1"},{"declaration",w.declaration},{"time_s",w.time},{"dt_s",w.dt},{"ticks",w.ticks},{"substeps",w.substeps},{"rejected_trials",w.rejected},{"cells",cells},{"objects",objects},{"events",w.events},
        {"diagnostics",{{"dynamic_mass_kg",mass},{"kinetic_j",w.totals.kinetic_energy_j},{"potential_j",w.totals.gravitational_potential_energy_j},{"elastic_j",elastic},{"fracture_j",w.fracture},{"fracture_overshoot_loss_j",w.discarded_elastic},{"unclosed_energy_j",w.totals.mechanicalEnergy()+elastic+w.fracture+w.discarded_elastic-w.initial_energy},{"linear_momentum_n_s",v(w.totals.linear_momentum_kg_m_s)},{"angular_momentum_kg_m2_s",v(w.totals.angular_momentum_kg_m2_s)},{"max_step_wall_ms",w.max_wall_ms},{"peak_stress_ratio",w.peak_stress_ratio},{"linear_velocity_quadratic_j",w.linear_velocity_quadratic},{"peak_spin_rad_s",w.peak_spin},{"native_spin_limit_samples",w.spin_limit_samples},{"spring_material_damping_j",w.material_damping},{"spring_implicit_elastic_loss_j",w.implicit_elastic_loss},{"spring_endpoint_work_j",w.spring_endpoint_work},{"spring_geometry_change_j",w.spring_geometry_change},{"spring_residual_work_j",w.spring_residual_work},{"max_spring_solver_residual_n",w.max_spring_residual_n},{"profile",{{"sweep_ms",w.sweep_wall_ms},{"trial_ms",w.trial_wall_ms},{"observation_ms",w.observation_wall_ms},{"native_step_ms",w.native_step_wall_ms},{"totals_ms",w.totals_wall_ms},{"candidate_faces_ms",w.candidate_faces_wall_ms}}}}},
        {"qualification",{{"calibrated",false},{"model","Passive finite-box six-axis elastic interfaces; brittle strength AND stored fracture-work admission. Metals/oak remain elastic, not brittle; plasticity/grain are unsupported. Implicit temporal error/contact/damping/full momentum accounts are unqualified."}}}}.dump();
}
}
