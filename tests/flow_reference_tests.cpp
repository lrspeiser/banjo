#include "flow/FlowReference.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <chrono>
using namespace banjo::flow;
void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int main(){try{
    Settings s; s.nx=48;s.nz=24;s.dx=0.1;
    std::vector<Cell> lake(static_cast<std::size_t>(s.nx*s.nz),Cell{0.2,0,0});Reference resting(s,lake);
    resting.advance(1);check(resting.account().energy==s.density*s.dx*s.dx*0.5*s.gravity*0.2*0.2*s.nx*s.nz || std::abs(resting.account().energy_residual)<1e-9,"still lake energy");
    for(auto c:resting.cells())check(c.h==0.2&&c.qx==0&&c.qz==0,"lake rest changed");
    check(std::abs(resting.account().wall_px)<1e-10&&std::abs(resting.account().wall_pz)<1e-10,"opposed wall reactions to summation rounding");
    // Same pressure-driven experiment, density enters only physical mass/energy.
    std::vector<Cell> dam(lake.size());for(int j=0;j<s.nz;++j)for(int i=0;i<s.nx;++i)dam[static_cast<std::size_t>(j*s.nx+i)]={i<s.nx/3?0.2:0,0,0};
    std::vector<Cell> reference;double previous_mass=0;
    for(double rho:{700.0,917.0,1000.0,2500.0,7870.0}){
        s.density=rho;Reference w(s,dam);auto start=std::chrono::steady_clock::now();w.advance(1);auto a=w.account();double wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
        check(std::abs(a.mass_residual)<1e-8&&std::abs(a.px_residual)<1e-8&&std::abs(a.pz_residual)<1e-8&&std::abs(a.ly_residual)<1e-8,"full flow transfer account");
        check(a.numerical_energy<0&&std::abs(a.energy_residual)<1e-8,"numerical energy accounted");
        check(w.cells()[static_cast<std::size_t>(s.nx*s.nz/2+s.nx/3+5)].h>0.001,"front did not move");
        for(auto c:w.cells())check(c.h>=0&&std::isfinite(c.h),"negative flow depth");
        if(reference.empty())reference=w.cells();else for(std::size_t i=0;i<reference.size();++i)check(reference[i].h==w.cells()[i].h&&reference[i].qx==w.cells()[i].qx&&reference[i].qz==w.cells()[i].qz,"density changed geometric trajectory");
        check(a.mass>previous_mass,"density mass scaling");previous_mass=a.mass;
        std::cout<<"density_kg_m3="<<rho<<" time_s="<<a.time<<" wall_s="<<wall<<" mass_kg="<<a.mass<<" steps="<<a.steps<<" mass_residual_kg="<<a.mass_residual<<" momentum_residual_ns="<<a.px_residual<<" angular_residual_nms="<<a.ly_residual<<" numerical_energy_j="<<a.numerical_energy<<"\n";
        auto old=w.cells();auto before=w.account();bool failed=false;try{w.advance(6);}catch(...){failed=true;}check(failed,"bad request accepted");check(w.account().time==before.time,"refused clock changed");for(std::size_t i=0;i<old.size();++i)check(old[i].h==w.cells()[i].h&&old[i].qx==w.cells()[i].qx,"refused cells changed");
    }
    // Independent local pressure oracle: first wall impulse rho g h²/2 area dt.
    s.nx=4;s.nz=2;s.density=1000;std::vector<Cell> small(8);small[0]={0.2,0,0};small[4]={0.2,0,0};Reference pressure(s,small);pressure.advance(0.0001);const auto p=pressure.account();
    const double expected=1000*9.81*0.2*0.2*0.5*(2*s.dx)*0.0001;
    check(std::abs(p.wall_px-expected)<1e-12,"hydrostatic wall impulse oracle");
    // Asymmetric advected state exercises numerical angular transport separately.
    s.nx=12;s.nz=10;std::vector<Cell> oblique(120,Cell{0.2,0.01,0.005});Reference swirl(s,oblique);swirl.advance(0.05);check(std::abs(swirl.account().ly_residual)<1e-9,"angular face transport missing");
    bool bad=false;try{oblique[0].h=-0.1;Reference invalid(s,oblique);}catch(...){bad=true;}check(bad,"negative initial depth accepted");
    // Actual-loop work refusal, not merely an invalid request bound.
    Settings costly;costly.nx=128;costly.nz=32;costly.dx=.01;std::vector<Cell> slow(4096,Cell{.2,.2,0});Reference limited(costly,slow);bool stopped=false;try{limited.advance(5);}catch(const std::exception& e){stopped=std::string(e.what()).find("work/CFL")!=std::string::npos;}check(stopped,"whole-request work budget did not refuse");check(limited.account().time==0&&limited.account().steps==0,"failed loop clock committed");for(std::size_t i=0;i<slow.size();++i)check(limited.cells()[i].h==slow[i].h&&limited.cells()[i].qx==slow[i].qx,"failed loop cell committed");
    // Spatial refinement toward Ritter's analytical dry-bed dam release.
    double coarse=0;
    for(int n:{40,80}){Settings r;r.nx=n;r.nz=4;r.dx=8.0/n;r.density=1000;std::vector<Cell> state(static_cast<std::size_t>(n*4));for(int j=0;j<4;++j)for(int i=0;i<n;++i)state[static_cast<std::size_t>(j*n+i)]={i<n/2?0.2:0,0,0};Reference release(r,state);release.advance(0.5);double error=0;const double c=std::sqrt(9.81*0.2);for(int i=0;i<n;++i){const double x=(i+.5)*r.dx-4,xi=x/.5,exact=xi<=-c?.2:xi>=2*c?0:(2*c-xi)*(2*c-xi)/(9*9.81);error+=std::pow(release.cells()[static_cast<std::size_t>(n+i)].h-exact,2)*r.dx;}error=std::sqrt(error);std::cout<<"ritter_nx="<<n<<" dx_m="<<r.dx<<" depth_l2_error="<<error<<"\n";if(n==40)coarse=error;else check(error<coarse,"Ritter spatial refinement did not improve");}
    std::cout<<"flow analytical and transactional tests passed\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
