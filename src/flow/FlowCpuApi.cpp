#include "flow/FlowReference.hpp"
#include <algorithm>
#include <vector>
#include <cmath>
#include <string>
#include <exception>
#ifdef _WIN32
#define FLOW_EXPORT __declspec(dllexport)
#else
#define FLOW_EXPORT __attribute__((visibility("default")))
#endif
// Stateless bounded transaction over persistent state: outputs untouched on refusal.
namespace {
int run(const double* config,const double* initial,const double* continuation,double* states,double* accounts,double* final_continuation){
    try{
        if(!config||!initial||!states||!accounts)return -1;
        for(int i=0;i<7;++i)if(!std::isfinite(config[i]))return -1;
        if(config[0]!=std::floor(config[0])||config[1]!=std::floor(config[1])||config[6]!=std::floor(config[6])||config[6]<2||config[6]>241||config[5]<=0||config[5]>5)return -1;
        if(config[0]<2||config[0]>128||config[1]<2||config[1]>128||config[0]*config[1]>4096)return -1;
        if(config[0]*config[1]*config[6]>300000)return -1;
        banjo::flow::Settings s; s.nx=static_cast<int>(config[0]);s.nz=static_cast<int>(config[1]);s.dx=config[2];s.density=config[3];s.gravity=config[4];
        const int n=s.nx*s.nz,frames=static_cast<int>(config[6]);std::vector<banjo::flow::Cell> cells(static_cast<std::size_t>(n));
        for(int i=0;i<n;++i)cells[static_cast<std::size_t>(i)]={initial[3*i],initial[3*i+1],initial[3*i+2]};
        if(continuation){for(int i=0;i<12;++i)if(!std::isfinite(continuation[i]))return -1;
            if(continuation[11]<0||continuation[11]>1000000000||continuation[11]!=std::floor(continuation[11]))return -1;
        }
        auto world=[&](){if(!continuation)return banjo::flow::Reference(s,std::move(cells));
            banjo::flow::Reference::State old;old.settings=s;old.cells=std::move(cells);old.initial.mass=continuation[0];old.initial.px=continuation[1];old.initial.pz=continuation[2];old.initial.ly=continuation[3];old.initial.energy=continuation[4];
            old.crossings.time=continuation[5];old.crossings.wall_px=continuation[6];old.crossings.wall_pz=continuation[7];old.crossings.wall_ly=continuation[8];old.crossings.numerical_ly=continuation[9];old.crossings.numerical_energy=continuation[10];old.crossings.steps=static_cast<std::uint64_t>(continuation[11]);return banjo::flow::Reference::restore(old);
        }();
        const auto starting_steps=world.account().steps;std::vector<double> output(static_cast<std::size_t>(frames*n*3)),receipt(static_cast<std::size_t>(frames*18));
        for(int f=0;f<frames;++f){
            if(f){const auto used=world.account().steps-starting_steps;if(used>=20000||used*static_cast<std::uint64_t>(n)>=8000000)return -4;
                world.advance(config[5]/(frames-1),20000-used,8000000-used*static_cast<std::uint64_t>(n));}
            for(int i=0;i<n;++i){const auto c=world.cells()[static_cast<std::size_t>(i)];output[static_cast<std::size_t>((f*n+i)*3)]=c.h;output[static_cast<std::size_t>((f*n+i)*3+1)]=c.qx;output[static_cast<std::size_t>((f*n+i)*3+2)]=c.qz;}
            auto a=world.account();const double values[18]={a.time,a.mass,a.px,a.pz,a.ly,a.energy,a.wall_px,a.wall_pz,a.wall_ly,a.numerical_ly,a.numerical_energy,a.mass_residual,a.px_residual,a.pz_residual,a.ly_residual,a.energy_residual,static_cast<double>(a.steps),0};
            std::copy(values,values+18,receipt.begin()+static_cast<std::ptrdiff_t>(f*18));
        }
        auto full=world.state();const double continued[12]={full.initial.mass,full.initial.px,full.initial.pz,full.initial.ly,full.initial.energy,full.crossings.time,full.crossings.wall_px,full.crossings.wall_pz,full.crossings.wall_ly,full.crossings.numerical_ly,full.crossings.numerical_energy,static_cast<double>(full.crossings.steps)};
        std::copy(output.begin(),output.end(),states);std::copy(receipt.begin(),receipt.end(),accounts);if(final_continuation)std::copy(continued,continued+12,final_continuation);return 0;
    }catch(const std::exception& e){const std::string reason=e.what();
        if(reason.find("positivity/finite/speed")!=std::string::npos)return -2;
        if(reason.find("entropy energy")!=std::string::npos)return -3;
        if(reason.find("work/CFL")!=std::string::npos)return -4;
        if(reason.find("mass/momentum account")!=std::string::npos)return -5;
        return -1;
    }catch(...){return -1;}
}
}
extern "C" FLOW_EXPORT int banjo_flow_run(const double* config,const double* initial,double* states,double* accounts){return run(config,initial,nullptr,states,accounts,nullptr);}
extern "C" FLOW_EXPORT int banjo_flow_continue(const double* config,const double* initial,const double* continuation,double* states,double* accounts,double* final_continuation){
    if(!final_continuation)return -1;return run(config,initial,continuation,states,accounts,final_continuation);
}
