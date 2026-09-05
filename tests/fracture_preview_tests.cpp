#include "fracture/FracturePreview.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
using namespace banjo;
int main(){try{
    for(double speed:{4.0,60.0,120.0,240.0}){
        const auto preview=buildFracturePreview(speed);
        for(unsigned i=0;i<3;++i){const auto &run=preview[i];if(run.frames.empty()||run.frames.size()>2048)throw std::runtime_error("bounded nonempty preview");
            double time=-1;for(const auto &f:run.frames){if(f.time_s<=time||f.positions.size()!=8||f.live_bonds.size()!=7)throw std::runtime_error("ordered complete preview");time=f.time_s;for(auto p:f.positions)if(!std::isfinite(length(p)))throw std::runtime_error("finite preview positions");}
            const auto count=std::count(run.frames.back().live_bonds.begin(),run.frames.back().live_bonds.end(),false);
            if(i>0&&(count!=0||!run.events.empty()))throw std::runtime_error("elastic material does not become brittle");
            if(i==0&&count!=(speed==4?0:speed==60?2:speed==120?3:5))throw std::runtime_error("glass cascade topology");
            std::cout<<materialPresetName(run.material)<<" speed="<<speed<<" frames="<<run.frames.size()<<" breaks="<<count<<'\n';
        }
    }return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
