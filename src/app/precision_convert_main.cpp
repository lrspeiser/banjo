#include "creator/PrecisionConversion.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
int main(int argc,char **argv){try {
    if(argc!=4)throw std::invalid_argument("usage: banjo_precision_convert normalize|upgrade INPUT.json NEW_OUTPUT.json");
    const std::string mode=argv[1];if(mode!="normalize"&&mode!="upgrade")throw std::invalid_argument("unknown conversion operation");
    const std::filesystem::path input=argv[2],output=argv[3];
    if(std::filesystem::file_size(input)>1024*1024)throw std::invalid_argument("input exceeds 1 MiB");
    std::ifstream stream(input,std::ios::binary);if(!stream)throw std::runtime_error("cannot open input");
    std::string document;char c;while(stream.get(c)){if(document.size()>=1024*1024)throw std::invalid_argument("input exceeds 1 MiB");document+=c;}
    if(!stream.eof())throw std::runtime_error("cannot read input");
    const auto result=mode=="normalize"?banjo::normalizeSavedWorldJson(document):banjo::upgradePositionPrecisionJson(document);
    // Exclusive creation: never overwrite the source, a previous result or a
    // racing writer. Failed writes can leave an incomplete, invalid output;
    // this offline export is not an atomic live-world publication operation.
    std::ofstream target(output,std::ios::binary|std::ios::noreplace);
    if(!target)throw std::runtime_error("output must be a new writable file");
    target.write(result.data(),static_cast<std::streamsize>(result.size()));target.close();
    if(!target)throw std::runtime_error("cannot complete output write");
    std::cout<<(mode=="upgrade"?"Conversion review package":"Normalized save")<<" written; source unchanged.\n";return 0;
}catch(const std::exception &e){std::cerr<<"Conversion error: "<<e.what()<<'\n';return 1;}}
