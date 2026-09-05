#include "creator/BondedBowl.hpp"
#include "creator/BowlLab.hpp"
#include "creator/BowlRecording.hpp"
#include <thread>
#include <iostream>
#include <stdexcept>
#include <set>
#include <map>
#include <numbers>
using namespace banjo;
void check(bool a,const char *m){if(!a)throw std::runtime_error(m);}
int main(int argc,char **){try{
 if(argc>1){BowlLab lab;for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){lab.collect(m);(void)lab.craft(m);}BowlSettings s;s.impact_trial=true;lab.configure(s);lab.release();lab.step(24);std::cout<<"crafted impact breaks="<<lab.bonded()->breaks.size()<<std::endl;check(!lab.bonded()->breaks.empty(),"crafted impact fixture produces fracture");return 0;}

 for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(double speed:{.05,2.,10.})for(double fraction:{.35,.175}){
  BondedBowl w;w.gravity={};w.support=false;w.wave_step_fraction=fraction;
  w.add(1,m,.045,{{-.03505,0,0},{},{speed,0,0},{}});w.add(2,m,.045,{{.03505,0,0},{},{-speed,0,0},{}});w.initialize();
  auto p=w.momentum(),h=w.angularMomentum();double mass=0;for(auto &c:w.cells)mass+=c.mass;
  w.advance(.002);
  auto roots=w.components();std::set<unsigned> groups(roots.begin(),roots.end());
  std::cout<<materialPresetName(m)<<" speed="<<speed<<" fraction="<<fraction<<" breaks="<<w.breaks.size()<<" groups="<<groups.size()<<" E0="<<w.ledger.initial_energy_j<<" residual="<<w.energyResidual()<<std::endl;
  check(length(w.momentum()-p)<1e-10,"closed linear momentum");check(length(w.angularMomentum()-h)<1e-10,"closed angular momentum");
  check(std::abs(w.energyResidual())<.01*w.ledger.initial_energy_j,"full energy including named losses");
  double finalMass=0;for(auto &c:w.cells)finalMass+=c.mass;check(finalMass==mass,"fracture retains allocated mass");
  if(m!=MaterialPreset::Glass||speed<=2)check(w.breaks.empty(),"unsupported failure / gentle impact stays intact");
  if(m==MaterialPreset::Glass&&speed==10){check(!w.breaks.empty()&&groups.size()>2&&groups.size()<w.cells.size(),"strong impact leaves some connected pieces");
   check(w.breaks.front().time_s<w.breaks.back().time_s,"failure evolves in time");
   auto replay=w;for(auto &e:replay.links)e.live=true;bool internalLater=false;
   for(auto &event:w.breaks){auto comp=replay.components();unsigned root=comp[replay.links[event.link].a],count=0;for(auto r:comp)count+=r==root;internalLater|=count<19;replay.links[event.link].live=false;}
   check(internalLater,"a detached piece retains bonds that can fail later");
  }
  auto saved=w.cells.front().x;bool rejected=false;try{w.advance(.1);}catch(const std::invalid_argument&){rejected=true;}check(rejected&&length(w.cells.front().x-saved)==0,"invalid budget rejected before mutation");
 }
 // Inclined/curved support reactions, friction and energy for all three substances.
 for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(auto surface:{MaterialPreset::Concrete,MaterialPreset::Oak})for(double tilt:{0.,10.}){
  BondedBowl w;w.surface=surface;w.tilt_degrees=tilt;double angle=tilt*std::numbers::pi/360;Quat q{std::cos(angle),0,0,std::sin(angle)};w.add(1,m,.045,{q.rotate({0,.036,0}),q,q.rotate({.2,-1,0}),{}});w.initialize();auto p=w.momentum(),h=w.angularMomentum();
  w.advance(.003);check(length(w.momentum()-p-w.ledger.gravity_impulse-w.ledger.support_impulse)<1e-8,"support reaction closes linear momentum");
  check(length(w.angularMomentum()-h-w.ledger.gravity_angular_impulse-w.ledger.support_angular_impulse)<1e-8,"support reaction closes angular momentum");
  check(std::abs(w.energyResidual())<.01*w.ledger.initial_energy_j,"support energy including losses");check(w.ledger.friction_j>0,"surface friction performs accounted work");
  std::cout<<"support "<<materialPresetName(m)<<" on "<<materialPresetName(surface)<<" tilt="<<tilt<<" residual="<<w.energyResidual()<<std::endl;
 }
 BondedBowl rollback;rollback.support=false;rollback.gravity={};rollback.wave_step_fraction=.01;
 rollback.add(1,MaterialPreset::Glass,.045,{{-.03505,0,0},{},{2,0,0},{}});rollback.add(2,MaterialPreset::Glass,.045,{{.03505,0,0},{},{-2,0,0},{}});rollback.initialize();
 auto original=rollback.cells;bool failed=false;try{rollback.advance(.005);}catch(const std::runtime_error&){failed=true;}
 check(failed&&rollback.time()==0&&rollback.breaks.empty()&&rollback.ledger.fracture_work_j==0,"evaluation failure rolls back events, clock and work");
 for(unsigned i=0;i<original.size();++i)check(length(rollback.cells[i].x-original[i].x)==0&&length(rollback.cells[i].v-original[i].v)==0,"evaluation failure rolls back physical states");
 BowlLab lab;for(int round=0;round<2;++round)for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){lab.collect(m);(void)lab.craft(m);}auto stock=lab.stock().serialize();lab.release();
 for(unsigned k=0;k<1440;++k)lab.step();
 auto b=lab.bonded();auto roots=b->components();std::set<unsigned> groups(roots.begin(),roots.end());
 check(b->breaks.empty()&&groups.size()==6,"normal six-ball release must not shatter");
 for(auto &e:b->breaks)check(b->objects[e.object].material==MaterialPreset::Glass,"only supported material fails in bowl");
 for(auto &c:b->cells)check(c.x.y>-.05,"fragments retained by level bowl");
 check(std::abs(b->energyResidual())<.01*b->ledger.initial_energy_j,"complete bowl energy bounded");
 check(lab.stock().serialize()==stock,"bowl fracture does not credit or spend inventory");
 std::cout<<"bowl time="<<lab.timeSeconds()<<" breaks="<<b->breaks.size()<<" groups="<<groups.size()<<" E0="<<b->ledger.initial_energy_j<<" residual="<<b->energyResidual()<<std::endl;
 for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
  BondedBowl rolling;BowlSettings setup;double x=.8;auto n=normalized(Vec3{-2*setup.depth_m*x/(setup.radius_m*setup.radius_m),1,0});auto initial=bowlPoint(setup,x,0)+n*.05;
  rolling.add(1,m,.045,{initial});rolling.initialize();double spin=0;for(unsigned i=0;i<720;++i){rolling.advance(1./2400);spin=std::max(spin,length(rolling.state(1).angular_velocity_rad_s));}
  auto movement=length(rolling.state(1).center_of_mass_world_m-initial);check(rolling.breaks.empty()&&movement>.01&&spin>.1,"isolated rolling translates and spins without fracture");
  std::cout<<"rolling "<<materialPresetName(m)<<" movement="<<movement<<" peak_spin="<<spin<<" breaks=0"<<std::endl;
 }
 lab.pause();BowlSettings impact;impact.impact_trial=true;lab.configure(impact);lab.release();lab.step(24);lab.pause();
 std::cout<<"crafted impact breaks="<<lab.bonded()->breaks.size()<<std::endl;
 check(!lab.bonded()->breaks.empty(),"crafted impact fixture produces fracture");
 BowlRecording recording;auto start=*lab.bonded();recording.start(start,1./120);
 while(recording.computing()){recording.poll(0);std::this_thread::sleep_for(std::chrono::milliseconds(1));}
 check(recording.ready()&&recording.error().empty(),"recording publishes only completed trajectory");
 recording.play();recording.poll(.02);auto displayed=recording.frame();check(displayed&&displayed->time()>start.time(),"wall time drives actual recorded motion");
 recording.play();recording.poll(0);check(recording.frame()->time()==start.time(),"replay restarts exact initial frame");
 recording.clear();recording.start(start,2);recording.clear();check(!recording.ready()&&!recording.computing(),"cancel discards prior frames and worker");

 for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
  BondedBowl flat;flat.flat_support=true;flat.add(1,m,.045,{{0,.045,0}});flat.initialize();
  auto p0=flat.momentum();for(unsigned i=0;i<240;++i)flat.advance(1./2400);
  check(flat.breaks.empty(),"flat-ground settling does not fracture");
  check(length(flat.momentum()-p0-flat.ledger.gravity_impulse-flat.ledger.support_impulse)<1e-8,"flat ground reaction ledger");
  check(std::abs(flat.energyResidual())<.01*flat.ledger.initial_energy_j,"flat ground energy");
  BondedBowl edge;edge.flat_support=true;edge.add(1,m,.045,{{2,1,0}});edge.initialize();
  for(unsigned i=0;i<120;++i)edge.advance(1./2400);
  check(std::abs(edge.state(1).center_of_mass_world_m.y-(1-.5*9.81*.05*.05))<1e-8,"finite ground has no support beyond its edge");
 }
 lab.configure({});check(lab.bonded()->breaks.empty()&&lab.stock().serialize()==stock,"authoring reset restores intact allocations");
 return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<std::endl;return 1;}}
