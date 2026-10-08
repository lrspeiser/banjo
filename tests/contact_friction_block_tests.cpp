#include "physics/ContactFrictionBlock.hpp"
#include <cmath>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
using A=std::array<double,3>;
using K=std::array<double,9>;
void check(bool b,const char* m){if(!b)throw std::runtime_error(m);}
void oracle(K k,A q,double cap,double twist){
    const auto p=banjo::solveContactFrictionBlock(k,q,cap,twist);A g=q;
    for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)g[i]+=k[3*i+j]*p[j];
    check(std::hypot(p[0],p[1])<=cap+1e-12&&std::abs(p[2])<=twist,"feasible caps");
    const double vi=p[0]*g[0]+p[1]*g[1]+cap*std::hypot(g[0],g[1])+p[2]*g[2]+twist*std::abs(g[2]);
    check(std::abs(vi)<1e-10,"full coupled variational stationarity");
    double energy=0;for(unsigned i=0;i<3;++i){energy+=q[i]*p[i];for(unsigned j=0;j<3;++j)energy+=.5*p[i]*k[3*i+j]*p[j];}
    check(energy<=1e-12,"maximum dissipation does not add free kinetic energy");
}
void benchmark(){
    const K k{4,1,.8,1,2,-.3,.8,-.3,3};
    // Same frozen physical problem for both binaries. Timing is reported,
    // never a CI pass criterion; the checksum makes every solve observable.
    for(const std::string kind:{"sticking","sliding-no-twist","coupled-sliding"}){
        double checksum=0;
        const auto start=std::chrono::steady_clock::now();
        for(unsigned repeat=0;repeat<200;++repeat)for(unsigned i=0;i<256;++i){
            const double x=double(i)/256;
            const A q=kind=="sticking"?A{.1+x*.05,-.2,.3}:A{10+x,-5,7};
            const double cap=kind=="sticking"?100:1;
            const double twist=kind=="sliding-no-twist"?0:kind=="sticking"?100:.5;
            const auto p=banjo::solveContactFrictionBlock(k,q,cap,twist);
            checksum+=p[0]+2*p[1]+3*p[2];
        }
        const double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        std::cout<<std::setprecision(17)<<kind<<" solves=51200 ms="<<ms<<" checksum="<<checksum<<'\n';
    }
}
int main(int argc,char** argv){try{
    if(argc==2&&std::string(argv[1])=="--benchmark"){benchmark();return 0;}
    const K coupled{4,1,.8,1,2,-.3,.8,-.3,3};
    for(K k:{K{1,0,0,0,1,0,0,0,1},coupled})
        for(A q:{A{0,0,0},A{.1,-.2,.3},A{10,-5,7},A{-10,5,-7}})
            for(double cap:{0.,.1,1.,100.})for(double twist:{0.,.05,2.,100.})oracle(k,q,cap,twist);
    // Deterministic coverage of interior, tangent-boundary and twist-boundary
    // solutions. The independent variational inequality checks the full
    // feasible set rather than reproducing the optimizer's branch decisions.
    for(unsigned i=0;i<4096;++i){
        const double x=double(i)/4096;
        const A q{10*std::sin(23*x),8*std::cos(31*x),6*std::sin(47*x)};
        oracle(coupled,q,i%3==0?0:i%3==1?.15:20,i%4==0?0:i%4==1?.05:i%4==2?2:20);
    }
    // Tangent basis swap must rotate the solution, including tangent/twist coupling.
    const A q{10,-5,7};auto p=banjo::solveContactFrictionBlock(coupled,q,1,.5);
    const K swapped{2,1,-.3,1,4,.8,-.3,.8,3};auto r=banjo::solveContactFrictionBlock(swapped,{q[1],q[0],q[2]},1,.5);
    check(std::abs(p[0]-r[1])+std::abs(p[1]-r[0])+std::abs(p[2]-r[2])<1e-12,"basis invariant");
    bool refused=false;try{(void)banjo::solveContactFrictionBlock({1,2,0,2,1,0,0,0,1},q,1,1);}catch(const std::invalid_argument&){refused=true;}
    check(refused,"indefinite mass refused");
    for(double bad:{-1.,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN()}){
        refused=false;try{(void)banjo::solveContactFrictionBlock(coupled,q,bad,1);}catch(const std::invalid_argument&){refused=true;}
        check(refused,"invalid cap refused");
    }
    refused=false;try{(void)banjo::solveContactFrictionBlock({1e300,0,0,0,1e300,0,0,0,1e300},q,1,1);}catch(const std::invalid_argument&){refused=true;}
    check(refused,"overflowing mass arithmetic refused");
    std::cout<<"4224 coupled contact friction oracles passed\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
