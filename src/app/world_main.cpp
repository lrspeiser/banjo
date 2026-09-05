#include "world/WorldLabFixture.hpp"
#include <nlohmann/json.hpp>
#include <charconv>
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>

int main(int argc,char **argv){
    try{
        unsigned chunks=4096,regions=4,frames=600,work=32768;std::string output;
        for(int i=1;i<argc;++i){
            const std::string_view option=argv[i];
            if(option=="--help"){
                std::cout<<"banjo_world_cli [--chunks 4096] [--regions 4] [--frames 600] [--work 32768] [--output file.json]\nInsulated thermal/reaction coupons. Cold storage is not full-world simulation.\n";return 0;
            }
            if(i+1>=argc)throw std::invalid_argument("missing option value");
            const std::string_view value=argv[++i];
            if(option=="--output"){output=value;continue;}
            unsigned number{};auto parsed=std::from_chars(value.data(),value.data()+value.size(),number);
            if(parsed.ec!=std::errc{}||parsed.ptr!=value.data()+value.size())throw std::invalid_argument("expected nonnegative integer");
            if(option=="--chunks")chunks=number;else if(option=="--regions")regions=number;
            else if(option=="--frames")frames=number;else if(option=="--work")work=number;
            else throw std::invalid_argument("unknown world option");
        }
        if(!frames||frames>36000||work>10000000)throw std::invalid_argument("frame/work limit exceeded");
        const auto start=std::chrono::steady_clock::now();auto world=banjo::makeWorldLab(chunks,regions);
        const double loadMs=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        for(unsigned i=0;i<frames;++i){const auto step=world->advance(1./60,{64,work,4});if(!step.error.empty())throw std::runtime_error(step.error);}
        auto report=nlohmann::json::parse(world->reportJson());
        report["fixture"]={{"id","insulated-glass-oak-iron-oxygen-control-v1"},{"cell_size_m",.01},{"coupon_grid",{8,8,1}},{"initial_temperature_k",293.15},{"heated_center_cells",4},{"center_temperature_after_heater_k",650},{"thermal_step_s",.05},{"host_step_s",1./60},{"frames",frames},{"wall_budget_ms",4},{"work_budget",work},{"load_ms",loadMs},{"calibrated_real_materials",false}};
        for(auto &region:report["regions"])region["material"]=banjo::worldLabMaterialName((region["id"].get<unsigned>()-1)%4+1);
        if(output.empty())std::cout<<report.dump(2)<<'\n';
        else{std::ofstream file(output);if(!file)throw std::runtime_error("cannot open output");file<<report.dump(2)<<'\n';if(!file)throw std::runtime_error("output write failed");std::cout<<"Saved "<<output<<'\n';}
        return 0;
    }catch(const std::exception &e){std::cerr<<"World runtime: "<<e.what()<<'\n';return 1;}
}
