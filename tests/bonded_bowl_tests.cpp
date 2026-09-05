#include "creator/BondedBowl.hpp"
#include "creator/BowlLab.hpp"
#include <iostream>
#include <stdexcept>
#include <set>
#include <map>
#include <numbers>
using namespace banjo;
void check(bool a,const char *m){if(!a)throw std::runtime_error(m);}
int main(){try{
 for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(double speed:{.05,.5,2.})for(double fraction:{.35,.175}){
  BondedBowl w;w.gravity={};w.support=false;w.wave_step_fraction=fraction;
  w.add(1,m,.045,{{-.03505,0,0},{},{speed,0,0},{}});w.add(2,m,.045,{{.03505,0,0},{},{-speed,0,0},{}});w.initialize();
  auto p=w.momentum(),h=w.angularMomentum();double mass=0;for(auto &c:w.cells)mass+=c.mass;
  w.advance(.002);
  auto roots=w.components();std::set<unsigned> groups(roots.begin(),roots.end());
  std::cout<<materialPresetName(m)<<" speed="<<speed<<" fraction="<<fraction<<" breaks="<<w.breaks.size()<<" groups="<<groups.size()<<" E0="<<w.ledger.initial_energy_j<<" residual="<<w.energyResidual()<<std::endl;
  check(length(w.momentum()-p)<1e-10,"closed linear momentum");check(length(w.angularMomentum()-h)<1e-10,"closed angular momentum");
  check(std::abs(w.energyResidual())<.01*w.ledger.initial_energy_j,"full energy including named losses");
  double finalMass=0;for(auto &c:w.cells)finalMass+=c.mass;check(finalMass==mass,"fracture retains allocated mass");
  if(m!=MaterialPreset::Glass||speed==.05)check(w.breaks.empty(),"unsupported failure / gentle impact stays intact");
  if(m==MaterialPreset::Glass&&speed==2){check(!w.breaks.empty()&&groups.size()>2&&groups.size()<w.cells.size(),"strong impact leaves some connected pieces");
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
 check(!b->breaks.empty()&&groups.size()>6,"actual bowl release separates connected pieces");
 for(auto &e:b->breaks)check(b->objects[e.object].material==MaterialPreset::Glass,"only supported material fails in bowl");
 for(auto &c:b->cells)check(c.x.y>-.05,"fragments retained by level bowl");
 check(std::abs(b->energyResidual())<.01*b->ledger.initial_energy_j,"complete bowl energy bounded");
 check(lab.stock().serialize()==stock,"bowl fracture does not credit or spend inventory");
 std::cout<<"bowl time="<<lab.timeSeconds()<<" breaks="<<b->breaks.size()<<" groups="<<groups.size()<<" E0="<<b->ledger.initial_energy_j<<" residual="<<b->energyResidual()<<std::endl;
 lab.configure({});check(lab.bonded()->breaks.empty()&&lab.stock().serialize()==stock,"authoring reset restores intact allocations");
 return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<std::endl;return 1;}}
