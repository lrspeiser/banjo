#include "creator/CreatorWorld.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
#include <optional>
#include <stdexcept>

int main(int argc,char **argv) {
    try {
        std::filesystem::path input,load,save;
        for (int i=1;i<argc;++i) {
            const std::string option=argv[i];
            if (option=="--help") {
                std::cout<<"banjo_creator_cli [--load WORLD.json] [--commands COMMANDS.json|-] [--save WORLD.json]\n"
                    "Without commands, prints inventory, supported capabilities and current objects.\n";
                return 0;
            }
            if (option!="--load" && option!="--commands" && option!="--save") throw std::invalid_argument("unknown creator option");
            if (++i>=argc) throw std::invalid_argument("missing option value");
            if (option=="--load") load=argv[i]; else if (option=="--save") save=argv[i]; else input=argv[i];
        }
        auto world=load.empty() ? banjo::CreatorWorld{} : banjo::CreatorWorld::load(load);
        if (input.empty()) std::cout<<world.inspectJson()<<'\n';
        else {
            std::ifstream file;
            if (input!="-") { file.open(input); if (!file) throw std::runtime_error("cannot read commands file"); }
            std::istream &stream=input=="-" ? std::cin : file;
            std::string document;
            char c;
            while (stream.get(c)) {
                if (document.size()>=1024*1024) throw std::invalid_argument("commands exceed 1 MiB");
                document+=c;
            }
            std::cout<<world.executeJson(document)<<'\n';
        }
        if (!save.empty()) world.save(save);
        return 0;
    } catch (const std::exception &error) {
        std::cerr<<"Creator error: "<<error.what()<<'\n'; return 1;
    }
}
