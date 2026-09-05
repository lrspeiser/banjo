#include "world/WorldLabFixture.hpp"
#include <stdexcept>

namespace banjo {
const char *worldLabMaterialName(unsigned material){
    switch(material){case 1:return "Glass";case 2:return "Oak + finite oxygen";
    case 3:return "Iron";case 4:return "Oak / no oxygen";default:return "Unknown";}
}
std::unique_ptr<SparseThermalWorld> makeWorldLab(unsigned chunks,unsigned regions){
    if(chunks<4||chunks>1000000||regions>256||regions>chunks)
        throw std::invalid_argument("fixture requires 4..1000000 chunks and 0..256 regions within those chunks");
    auto world=std::make_unique<SparseThermalWorld>(.01);
    // Illustrative constant properties; fuel/rate/O2 are declared toy reaction
    // parameters, not a calibrated wood combustion/airflow model.
    WorldThermalMaterial materials[]{
        {1,2500,0,0,{"glass",840,1,{}}},
        {2,700,.1,.15,{"oak",1700,.12,{true,600,2,16e6,1.5}}},
        {3,7870,0,0,{"iron",450,80,{}}},
        {4,700,.1,0,{"same oak without oxygen",1700,.12,{true,600,2,16e6,1.5}}}
    };
    for(auto material:materials)world->addMaterial(material);
    for(unsigned i=0;i<chunks;++i)world->addUniformChunk({int(i%1024),0,int(i/1024)},i%4+1,293.15);
    for(unsigned i=0;i<regions;++i){
        const ChunkAddress chunk{int(i%1024),0,int(i/1024)};
        std::vector<VoxelAddress> cells;
        for(unsigned y=0;y<8;++y)for(unsigned x=0;x<8;++x)cells.push_back({chunk,x,y,0});
        world->activateInsulatedRegion(i+1,cells,.05);
        const auto &material=materials[i%4];
        const double capacity=material.solid_density_kg_m3*1e-6*material.thermal.specific_heat_capacity_j_kg_k;
        const double work=capacity*(650-293.15);
        for(unsigned y=3;y<5;++y)for(unsigned x=3;x<5;++x)(void)world->addHeat({chunk,x,y,0},work,work,0);
    }
    return world;
}
}
