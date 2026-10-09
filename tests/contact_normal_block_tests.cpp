#include "physics/ContactNormalBlock.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>

using banjo::ContactNormalBlock;
namespace {
void check(bool yes,const char *why){if(!yes)throw std::runtime_error(why);}
void verify(const std::array<double,16>&k,unsigned n,const std::array<double,4>&q,const std::array<double,4>&x){
    double work=0;
    for(unsigned i=0;i<n;++i){double g=q[i];for(unsigned j=0;j<n;++j)g+=k[4*i+j]*x[j];
        check(x[i]>=0&&g>=-1e-10,"unilateral feasibility");check(std::abs(x[i]*g)<1e-10,"normal complementarity");
        work+=x[i]*(q[i]+g)/2;
    }
    check(work<=1e-10,"unforced contact increased kinetic energy");
}
void trials(){
    unsigned count=0;
    // Same net mass plus rotational responses: a coplanar four-point patch is
    // singular, whereas a synthetic fourth independent generalized mode is SPD.
    for(unsigned rank: {1u,3u,4u})for(unsigned seed=0;seed<160;++seed){
        const double px[4]={-1,1,1,-1},pz[4]={-1,-1,1,1};
        double j[4][4]{};std::array<double,16> k{};
        for(unsigned i=0;i<4;++i){j[i][0]=1;j[i][1]=rank>=3?px[i]:0;j[i][2]=rank>=3?pz[i]:0;j[i][3]=rank==4?px[i]*pz[i]*.7:0;}
        for(unsigned i=0;i<4;++i)for(unsigned r=0;r<4;++r)for(unsigned d=0;d<4;++d)k[4*i+r]+=j[i][d]*j[r][d];
        const ContactNormalBlock block(k,4);
        std::array<double,4> known{},g{},q{};
        for(unsigned i=0;i<4;++i){known[i]=(seed&(1u<<i))?0:.1+(seed+3*i)%11/7.;g[i]=known[i]>0?0:.2+(seed+i)%5;}
        for(unsigned i=0;i<4;++i){q[i]=g[i];for(unsigned r=0;r<4;++r)q[i]-=k[4*i+r]*known[r];}
        const auto x=block.solve(q);verify(k,4,q,x);
        // Reverse row order: the physical wrench and minimum-norm tie handling
        // must not depend on the arbitrary contact enumeration.
        std::array<double,16> reversed{};std::array<double,4> rq{};
        for(unsigned i=0;i<4;++i){rq[i]=q[3-i];for(unsigned r=0;r<4;++r)reversed[4*i+r]=k[4*(3-i)+3-r];}
        const auto rx=ContactNormalBlock(reversed,4).solve(rq);
        for(unsigned i=0;i<4;++i)check(std::abs(rx[3-i]-x[i])<1e-10,"point ordering changed minimum-norm solution");
        ++count;
    }
    const std::array<double,16> duplicate={1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1};
    const auto evenly=ContactNormalBlock(duplicate,4).solve({-2,-2,-2,-2});
    for(double x:evenly)check(std::abs(x-.5)<1e-12,"singular patch did not share normal force symmetrically");
    const auto zero=ContactNormalBlock(duplicate,4).solve({1,2,3,4});
    check(zero==std::array<double,4>{},"separating patch received impulse");
    for(unsigned n:{1u,2u,3u}){std::array<double,16> k{};std::array<double,4> q{};
        for(unsigned i=0;i<n;++i){k[4*i+i]=2+i;q[i]=-2;}
        verify(k,n,q,ContactNormalBlock(k,n).solve(q));}
    unsigned refused=0;
    for(unsigned scenario=0;scenario<5;++scenario)try{
        auto k=duplicate;if(scenario==0)k[0]=-1;if(scenario==1)k[1]=2;if(scenario==2)k[0]=0;
        if(scenario==4)k[1]=k[4]=2; // symmetric but indefinite
        ContactNormalBlock block(k,scenario==3?5:4);
    }catch(const std::invalid_argument&){++refused;}
    check(refused==5,"invalid normal patch accepted");
    const std::array<double,16> nullDirection={1,-1,0,0,-1,1,0,0,0,0,0,0,0,0,0,0};
    bool unbounded=false;try{ContactNormalBlock(nullDirection,2).solve({-1,-1,0,0});}
    catch(const std::runtime_error&){unbounded=true;}
    check(unbounded,"unbounded unilateral problem accepted");
    std::cout<<"PASS "<<count<<" known KKT / kinetic-work / permutation cases; singular, separated, 1..3-point and refusal controls\n";
}
}
int main(){try{trials();return 0;}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
