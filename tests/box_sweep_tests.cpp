#include "physics/BoxSweep.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace banjo;
namespace {
void check(bool ok,const char*message){if(!ok)throw std::runtime_error(message);}
void run(){
    const auto thin=boundBoxSweep({.4,.004,.4},{0,0,0},{},0);
    const auto near=boundBoxSweep({.05,.05,.05},{0,.03,0},{},.004);
    check(std::abs(boxSweepRatio(thin,near,.0004)-20)<1e-10,"thin target feature lost");
    const auto far=boundBoxSweep({.05,.05,.05},{2,0,0},{},.1);
    check(boxSweepRatio(thin,far,.0004)==0,"distant fast body limited target");
    check(boxSweepRatio(thin,boundBoxSweep({.05,.05,.05},{0,1,0},{},1),0)>1,"crossing path missed");
    const auto block=boundBoxSweep({1,1,1},{0,0,0},{},0);
    check(std::abs(boxSweepRatio(block,near,0)-1.6)<1e-10,"coarse contact used sheet resolution");
    check(boxSweepRatio(thin,near,.0004)==boxSweepRatio(near,thin,.0004),"pair ordering changed bound");
    // Sample actual translated/rotated corners. Every intersecting trajectory
    // must remain a broad-phase candidate under the supplied arc-length bound.
    unsigned samples=0;
    for(unsigned seed=0;seed<100;++seed){
        const Vec3 size{.07,.004,.11};const double speed=.05+seed*.003,angle=.1+seed*.02;
        const Vec3 start{-.04,0,0};const double radius=length(size)/2;
        const auto sweep=boundBoxSweep(size,start,{},speed+radius*angle);
        for(unsigned t=0;t<=20;++t){const double u=t/20.;const Quat q{std::cos(angle*u/2),0,0,std::sin(angle*u/2)};
            for(int x:{-1,1})for(int y:{-1,1})for(int z:{-1,1}){
                const Vec3 point=start+Vec3{speed*u,0,0}+q.rotate({x*size.x/2,y*size.y/2,z*size.z/2});
                const auto probe=boundBoxSweep({.001,.001,.001},point,{},0);
                check(boxSweepRatio(sweep,probe,0)>0,"true travelled corner excluded");++samples;
            }
        }
    }
    unsigned refused=0;
    try{(void)boundBoxSweep({1,0,1},{},{},0);}catch(const std::invalid_argument&){++refused;}
    try{(void)boundBoxSweep({1,1,1},{},{2,0,0,0},0);}catch(const std::invalid_argument&){++refused;}
    try{(void)boundBoxSweep({1,1,1},{},{},-1);}catch(const std::invalid_argument&){++refused;}
    try{(void)boxSweepRatio(thin,near,-1);}catch(const std::invalid_argument&){++refused;}
    check(refused==4,"invalid sweep accepted");
    std::cout<<"PASS "<<samples<<" travelled corners; thin/coarse contacts, distant/crossing paths, symmetry and invalid inputs\n";
}
}
int main(){try{run();return 0;}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
