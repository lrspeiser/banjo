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
// Stateless bounded experiment: output is untouched on any refusal.
extern "C" FLOW_EXPORT int banjo_flow_run(const double* config,const double* initial,double* states,double* accounts){
    try{
        if(!config||!initial||!states||!accounts)return -1;
        for(int i=0;i<7;++i)if(!std::isfinite(config[i]))return -1;
        if(config[0]!=std::floor(config[0])||config[1]!=std::floor(config[1])||config[6]!=std::floor(config[6])||config[6]<2||config[6]>241||config[5]<=0||config[5]>5)return -1;
        if(config[0]<2||config[0]>128||config[1]<2||config[1]>128||config[0]*config[1]>4096)return -1;
        if(config[0]*config[1]*config[6]>300000)return -1;
        banjo::flow::Settings s; s.nx=static_cast<int>(config[0]);s.nz=static_cast<int>(config[1]);s.dx=config[2];s.density=config[3];s.gravity=config[4];
        const int n=s.nx*s.nz,frames=static_cast<int>(config[6]);std::vector<banjo::flow::Cell> cells(static_cast<std::size_t>(n));
        for(int i=0;i<n;++i)cells[static_cast<std::size_t>(i)]={initial[3*i],initial[3*i+1],initial[3*i+2]};
        banjo::flow::Reference world(s,std::move(cells));std::vector<double> output(static_cast<std::size_t>(frames*n*3)),receipt(static_cast<std::size_t>(frames*18));
        for(int f=0;f<frames;++f){
            if(f)world.advance(config[5]/(frames-1));
            for(int i=0;i<n;++i){const auto c=world.cells()[static_cast<std::size_t>(i)];output[static_cast<std::size_t>((f*n+i)*3)]=c.h;output[static_cast<std::size_t>((f*n+i)*3+1)]=c.qx;output[static_cast<std::size_t>((f*n+i)*3+2)]=c.qz;}
            auto a=world.account();const double values[18]={a.time,a.mass,a.px,a.pz,a.ly,a.energy,a.wall_px,a.wall_pz,a.wall_ly,a.numerical_ly,a.numerical_energy,a.mass_residual,a.px_residual,a.pz_residual,a.ly_residual,a.energy_residual,static_cast<double>(a.steps),0};
            std::copy(values,values+18,receipt.begin()+static_cast<std::ptrdiff_t>(f*18));
        }std::copy(output.begin(),output.end(),states);std::copy(receipt.begin(),receipt.end(),accounts);return 0;
    }catch(const std::exception& e){const std::string reason=e.what();
        if(reason.find("positivity/finite/speed")!=std::string::npos)return -2;
        if(reason.find("entropy energy")!=std::string::npos)return -3;
        if(reason.find("work/CFL")!=std::string::npos)return -4;
        if(reason.find("mass/momentum account")!=std::string::npos)return -5;
        return -1;
    }catch(...){return -1;}
}
