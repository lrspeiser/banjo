#include "creator/BondedBowl.hpp"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>
#include <numeric>
namespace banjo {
namespace {
constexpr double skin=.008;
Quat tilt(double degrees){double a=degrees*std::numbers::pi/360;return {std::cos(a),0,0,std::sin(a)};}
double kinetic(const BowlCell &c){return .5*c.mass*lengthSquared(c.v)+.5*c.inertia*lengthSquared(c.spin);}
}
void BondedBowl::add(MatterBodyId id,MaterialPreset preset,double radius,const RigidSnapshot &s){
 if(objects.size()>=9||time_!=0||radius!=.045)throw std::invalid_argument("bonded bowl supports nine 45 mm balls");
 auto m=makeReferenceMaterial(preset);unsigned first=unsigned(cells.size()),object=unsigned(objects.size());
 const double h=radius/(std::sqrt(2.)+.45),r=.45*h,mass=m.density_kg_m3*4*std::numbers::pi*radius*radius*radius/3/19;
 for(int x=-1;x<=1;++x)for(int y=-1;y<=1;++y)for(int z=-1;z<=1;++z)if(x*x+y*y+z*z<=2){
  Vec3 offset=s.orientation_world.rotate(Vec3{double(x),double(y),double(z)}*h);
  cells.push_back({s.center_of_mass_world_m+offset,s.linear_velocity_m_s+cross(s.angular_velocity_rad_s,offset),s.angular_velocity_rad_s,mass,r,mass*(.4*radius*radius-20*h*h/19),object});
 }
 objects.push_back({id,preset,first,19,radius});
 // Same face/diagonal central-force stencil for every material. Area is a
 // declared quadrature weight, not a physical crack face reconstructed from voxels.
 const double area=h*h/6;
 for(unsigned a=first;a<cells.size();++a)for(unsigned b=a+1;b<cells.size();++b){double d=length(cells[b].x-cells[a].x);if(d>h*1.42)continue;
  double k=m.young_modulus_pa*area/d;
  links.push_back({a,b,d,k,m.fracture_energy_j_m2*area,2*m.damping_ratio*std::sqrt(k*mass/2),true,m.model==MaterialModel::BrittleBond});
 }
}
void BondedBowl::initialize(){
 if(!std::isfinite(wave_step_fraction)||wave_step_fraction<.01||wave_step_fraction>.35)throw std::invalid_argument("wave step fraction outside .01.. .35");
 std::vector<double> rows(cells.size());
 for(auto &e:links){rows[e.a]+=2*e.stiffness;rows[e.b]+=2*e.stiffness;}
 double omega=1;
 // Include a declared 24-neighbor contact estimate, not just current
 // contacts. This is not a proof for arbitrary overlap/packing; the whole
 // interval energy gate remains required. Catalog stiffness is retained.
 double maxE=makeReferenceMaterial(surface).young_modulus_pa;
 for(auto &o:objects)maxE=std::max(maxE,makeReferenceMaterial(o.material).young_modulus_pa);
 for(unsigned i=0;i<cells.size();++i)omega=std::max(omega,(rows[i]+24*maxE*cells[i].radius)/cells[i].mass);
 step_limit_=wave_step_fraction/std::sqrt(omega);ledger={};ledger.initial_energy_j=energy();
}
std::vector<BondedBowl::Contact> BondedBowl::contacts() const{
 bool rebuild=neighbor_positions_.size()!=cells.size();
 if(!rebuild)for(unsigned i=0;i<cells.size();++i)if(lengthSquared(cells[i].x-neighbor_positions_[i])>skin*skin/4){rebuild=true;break;}
 if(rebuild){neighbors_.clear();neighbor_positions_.clear();for(auto &p:cells)neighbor_positions_.push_back(p.x);
  for(unsigned a=0;a<cells.size();++a)for(unsigned b=a+1;b<cells.size();++b){double r=cells[a].radius+cells[b].radius+skin;if(lengthSquared(cells[a].x-cells[b].x)<r*r)neighbors_.push_back({a,b});}}
 std::vector<Contact> result;
 for(auto [a,b]:neighbors_){auto &p=cells[a];auto &q=cells[b];Vec3 delta=p.x-q.x;double d2=lengthSquared(delta),r=p.radius+q.radius;if(d2>=r*r)continue;
  double d=std::sqrt(d2);if(d<1e-12)throw std::runtime_error("coincident cell contact");
  auto ma=makeReferenceMaterial(objects[p.object].material),mb=makeReferenceMaterial(objects[q.object].material);
  double E=1/(1/ma.young_modulus_pa+1/mb.young_modulus_pa),k=E*std::min(p.radius,q.radius);
  Vec3 n=delta/d,point=(p.x-n*p.radius+q.x+n*q.radius)*.5;
  result.push_back({a,b,n,point,r-d,k,std::sqrt(ma.dynamic_friction*mb.dynamic_friction),.5*(ma.contact_damping_ratio+mb.contact_damping_ratio),false});
 }
 if(support){const auto rot=tilt(tilt_degrees),inv=tilt(-tilt_degrees);const double a=bowl_depth/(bowl_radius*bowl_radius);auto ms=makeReferenceMaterial(surface);
  for(unsigned i=0;i<cells.size();++i){auto &c=cells[i];Vec3 p=inv.rotate(c.x);double rho=std::hypot(p.x,p.z);
   if(rho>bowl_radius+c.radius||p.y-a*rho*rho>c.radius*2)continue;
   // Closest point on the paraboloid of revolution (bounded interior Newton).
   double r=std::min(rho,bowl_radius);for(unsigned it=0;it<12;++it){double f=r+2*a*r*(a*r*r-p.y)-rho,df=1+6*a*a*r*r-2*a*p.y; if(df<=0)break;double nr=std::clamp(r-f/df,0.,bowl_radius);if(std::abs(nr-r)<1e-13){r=nr;break;}r=nr;}
   Vec3 q=rho>1e-14?Vec3{p.x*r/rho,a*r*r,p.z*r/rho}:Vec3{};
   Vec3 up=normalized(Vec3{-2*a*q.x,1,-2*a*q.z}),delta=p-q;double sign=dot(delta,up)>=0?1.:-1.,distance=sign*length(delta);
   if(r>=bowl_radius-1e-10){distance=length(delta);sign=1;} // finite rim contact, no infinite extension
   if(distance>=c.radius)continue;
   Vec3 n=rot.rotate(length(delta)>1e-12?normalized(delta)*sign:up);
   auto m=makeReferenceMaterial(objects[c.object].material);double k=c.radius/(1/m.young_modulus_pa+1/ms.young_modulus_pa);
   result.push_back({i,0,n,c.x-n*c.radius,c.radius-distance,k,std::sqrt(m.dynamic_friction*ms.dynamic_friction),.5*(m.contact_damping_ratio+ms.contact_damping_ratio),true});
  }
 }
 return result;
}
void BondedBowl::forces(std::vector<Vec3> &f,const std::vector<Contact> &c) const{
 f.resize(cells.size());for(unsigned i=0;i<cells.size();++i)f[i]=gravity*cells[i].mass;
 for(auto &e:links)if(e.live){Vec3 delta=cells[e.b].x-cells[e.a].x;double d=length(delta);if(d<1e-12)throw std::runtime_error("collapsed live connector");Vec3 v=delta*(e.stiffness*(d-e.rest)/d);f[e.a]+=v;f[e.b]-=v;}
 for(auto &p:c){Vec3 v=p.n*(p.stiffness*p.compression);f[p.a]+=v;if(!p.fixed)f[p.b]-=v;}
}
void BondedBowl::dissipate(double dt,const std::vector<Contact> &c){
 // Exact dissipative pair maps. Central internal damping conserves angular
 // momentum. Surface friction includes finite-cell spin at one common point.
 for(auto &e:links)if(e.live){auto &a=cells[e.a];auto &b=cells[e.b];Vec3 n=normalized(b.x-a.x);double rel=dot(b.v-a.v,n),mu=1/(1/a.mass+1/b.mass);double j=mu*rel*(-std::expm1(-e.damping*dt/mu));
  double before=kinetic(a)+kinetic(b);a.v+=n*(j/a.mass);b.v-=n*(j/b.mass);ledger.internal_damping_j+=before-kinetic(a)-kinetic(b);}
 for(auto &p:c){auto &a=cells[p.a];BowlCell *b=p.fixed?nullptr:&cells[p.b];Vec3 ra=p.point-a.x,rb=b?p.point-b->x:Vec3{};
  auto relative=[&]{return a.v+cross(a.spin,ra)-(b?b->v+cross(b->spin,rb):Vec3{});};
  auto apply=[&](Vec3 j){a.v+=j/a.mass;a.spin+=cross(ra,j)/a.inertia;if(b){b->v-=j/b->mass;b->spin-=cross(rb,j)/b->inertia;}else{ledger.support_impulse+=j;ledger.support_angular_impulse+=cross(p.point,j);}};
  double inv=1/a.mass+(b?1/b->mass:0.),vn=dot(relative(),p.n),normalImpulse=p.stiffness*p.compression*dt;
  if(vn<0){double mu=1/inv,coefficient=2*p.damping*std::sqrt(p.stiffness*mu),j=-mu*vn*(-std::expm1(-coefficient*dt/mu));double before=kinetic(a)+(b?kinetic(*b):0);apply(p.n*j);ledger.contact_damping_j+=before-kinetic(a)-(b?kinetic(*b):0);normalImpulse+=j;}
  Vec3 tangent=relative()-p.n*dot(relative(),p.n);double speed=length(tangent);if(speed>1e-14){Vec3 t=tangent/speed;double inverse=inv+lengthSquared(cross(ra,t))/a.inertia+(b?lengthSquared(cross(rb,t))/b->inertia:0.);double j=std::min(speed/inverse,p.friction*normalImpulse);double before=kinetic(a)+(b?kinetic(*b):0);apply(t*(-j));ledger.friction_j+=before-kinetic(a)-(b?kinetic(*b):0);}
 }
}
bool BondedBowl::step(double dt,unsigned depth){
 if(++evaluations_>65536)throw std::runtime_error("bowl evaluation budget");
 auto before=cells;auto oldLedger=ledger;auto c=contacts();std::vector<Vec3> f;forces(f,c);
 for(auto &p:c)if(p.fixed){Vec3 j=p.n*(p.stiffness*p.compression*dt*.5);ledger.support_impulse+=j;ledger.support_angular_impulse+=cross(p.point,j);}
 for(unsigned i=0;i<cells.size();++i){auto &p=cells[i];p.v+=f[i]*(dt*.5/p.mass);p.x+=p.v*dt;ledger.gravity_impulse+=gravity*(p.mass*dt);ledger.gravity_angular_impulse+=cross((before[i].x+p.x)*.5,gravity*(p.mass*dt));}
 std::vector<unsigned> broken;double work=0,overshoot=0;
 if(failure_enabled)for(unsigned i=0;i<links.size();++i){auto &e=links[i];if(!e.live||!e.brittle)continue;double extension=length(cells[e.b].x-cells[e.a].x)-e.rest,U=.5*e.stiffness*extension*extension;
  if(extension>0&&U>=e.work){if(U-e.work>e.work*.02){cells=std::move(before);ledger=oldLedger;if(depth>=16)throw std::runtime_error("fracture event refinement floor");return step(dt/2,depth+1)&&step(dt/2,depth+1);}broken.push_back(i);work+=e.work;overshoot+=U-e.work;}}
 for(auto i:broken){auto &e=links[i];e.live=false;breaks.push_back({time_+dt,i,cells[e.a].object,e.work,.5*e.stiffness*std::pow(length(cells[e.b].x-cells[e.a].x)-e.rest,2)-e.work});}
 ledger.fracture_work_j+=work;ledger.event_overshoot_j+=overshoot;
 c=contacts();forces(f,c);
 for(auto &p:c)if(p.fixed){Vec3 j=p.n*(p.stiffness*p.compression*dt*.5);ledger.support_impulse+=j;ledger.support_angular_impulse+=cross(p.point,j);}
 for(unsigned i=0;i<cells.size();++i)cells[i].v+=f[i]*(dt*.5/cells[i].mass);
 dissipate(dt,c);time_+=dt;return true;
}
void BondedBowl::advance(double seconds){
 if(!std::isfinite(seconds)||seconds<=0||seconds>.005||step_limit_<=0)throw std::invalid_argument("bounded bowl advance requires initialized world and <=5 ms");
 // Exact common free flight before the first contact. Distance bounds prevent
 // stepping across a cell/support or cell/cell encounter. No elastic mode is
 // suppressed after impact; this path requires zero internal relative motion.
 bool free=breaks.empty()&&!cells.empty();Vec3 common=cells.empty()?Vec3{}:cells[0].v;
 for(auto &c:cells)if(length(c.v-common)>1e-12||length(c.spin)>1e-12)free=false;
 for(auto &e:links)if(std::abs(length(cells[e.b].x-cells[e.a].x)-e.rest)>1e-12)free=false;
 if(free){double travel=length(common)*seconds+.5*length(gravity)*seconds*seconds;auto inv=tilt(-tilt_degrees);double a=bowl_depth/(bowl_radius*bowl_radius);
  if(support)for(auto &c:cells){Vec3 p=inv.rotate(c.x);double rho=std::hypot(p.x,p.z);double bound=(p.y-a*rho*rho)/std::sqrt(1+4*a*a*std::pow(bowl_radius+c.radius+travel,2))-c.radius;if(bound<=travel)free=false;}
  if(!contacts().empty())free=false;
  if(free){for(auto &c:cells){Vec3 old=c.x;c.x+=common*seconds+gravity*(.5*seconds*seconds);c.v+=gravity*seconds;ledger.gravity_impulse+=gravity*(c.mass*seconds);ledger.gravity_angular_impulse+=cross((old+c.x)*.5,gravity*(c.mass*seconds));}time_+=seconds;return;}
 }
 // Whole caller interval rolls back, including prior accepted candidate breaks.
 auto savedCells=cells;auto savedLinks=links;auto savedLedger=ledger;auto savedBreaks=breaks;double savedTime=time_;
 evaluations_=0;
 try{double left=seconds;unsigned count=0;while(left>0){if(++count>65536)throw std::runtime_error("bowl evaluation budget");double dt=std::min(left,step_limit_);step(dt,0);left-=dt;}
  for(auto &p:cells)if(!std::isfinite(lengthSquared(p.x)+lengthSquared(p.v)+lengthSquared(p.spin)))throw std::runtime_error("nonfinite bowl state");
  if(std::abs(energyResidual())>.01*std::max(std::abs(ledger.initial_energy_j),1e-6))throw std::runtime_error("bowl total energy error exceeds 1% budget");
 }catch(...){cells=std::move(savedCells);links=std::move(savedLinks);ledger=savedLedger;breaks=std::move(savedBreaks);time_=savedTime;throw;}
}
double BondedBowl::energy() const{double sum=0;for(auto &p:cells)sum+=kinetic(p)-p.mass*dot(gravity,p.x);for(auto &e:links)if(e.live)sum+=.5*e.stiffness*std::pow(length(cells[e.b].x-cells[e.a].x)-e.rest,2);for(auto &c:contacts())sum+=.5*c.stiffness*c.compression*c.compression;return sum;}
double BondedBowl::energyResidual() const{return energy()+ledger.fracture_work_j+ledger.event_overshoot_j+ledger.internal_damping_j+ledger.contact_damping_j+ledger.friction_j-ledger.initial_energy_j;}
Vec3 BondedBowl::momentum() const{Vec3 p;for(auto &c:cells)p+=c.v*c.mass;return p;}
Vec3 BondedBowl::angularMomentum() const{Vec3 p;for(auto &c:cells)p+=cross(c.x,c.v*c.mass)+c.spin*c.inertia;return p;}
RigidSnapshot BondedBowl::state(MatterBodyId id) const{RigidSnapshot s;double mass=0;auto it=std::find_if(objects.begin(),objects.end(),[&](auto &o){return o.id==id;});if(it==objects.end())throw std::invalid_argument("unknown bowl object");for(unsigned i=it->first;i<it->first+it->count;++i){s.center_of_mass_world_m+=cells[i].x*cells[i].mass;s.linear_velocity_m_s+=cells[i].v*cells[i].mass;mass+=cells[i].mass;}s.center_of_mass_world_m=s.center_of_mass_world_m/mass;s.linear_velocity_m_s=s.linear_velocity_m_s/mass;
 Mat3 I;Vec3 H;for(unsigned i=it->first;i<it->first+it->count;++i){auto &c=cells[i];Vec3 r=c.x-s.center_of_mass_world_m;double v[3]{r.x,r.y,r.z};for(int a=0;a<3;++a)for(int b=0;b<3;++b)I.m[a][b]+=c.mass*((a==b?lengthSquared(r):0)-v[a]*v[b])+(a==b?c.inertia:0);H+=cross(r,(c.v-s.linear_velocity_m_s)*c.mass)+c.spin*c.inertia;}if(auto inv=I.inverse(1e-30))s.angular_velocity_rad_s=(*inv)*H;return s;}
std::vector<unsigned> BondedBowl::components() const{std::vector<unsigned> roots(cells.size());std::iota(roots.begin(),roots.end(),0);auto root=[&](unsigned a){while(roots[a]!=a){roots[a]=roots[roots[a]];a=roots[a];}return a;};for(auto &e:links)if(e.live){unsigned a=root(e.a),b=root(e.b);roots[b]=a;}for(auto &r:roots)r=root(r);return roots;}
}
