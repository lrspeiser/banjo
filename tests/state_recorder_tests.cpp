#include "rigid/BoundedStateRecorder.hpp"
#include <Jolt/Physics/StateRecorderImpl.h>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

namespace {
void check(bool value,const char *why){if(!value)throw std::runtime_error(why);}
}
int main(){try{
    banjo::BoundedStateRecorder measured(65536);
    JPH::StateRecorderImpl reference;
    std::string bytes(65536,'\0');std::uint32_t seed=43;
    for(auto &c:bytes){seed=1664525U*seed+1013904223U;c=static_cast<char>(seed>>24);}
    for(auto size:{std::size_t(0),std::size_t(1),std::size_t(4095),std::size_t(4096),std::size_t(65536)}){
        measured.Reset();reference.Clear();
        for(std::size_t offset=0;offset<size;){
            const auto count=std::min(size-offset,std::size_t((offset%97)+1));
            measured.WriteBytes(bytes.data()+offset,count);reference.WriteBytes(bytes.data()+offset,count);offset+=count;
        }
        check(!measured.IsFailed()&&measured.GetData()==reference.GetData(),"every written byte matches the original Jolt recorder");
        check(measured.StorageBytes()<=65536,"storage stays within its declared bound");
        std::string a(size,'\0'),b(size,'\0');measured.Rewind();reference.Rewind();
        for(std::size_t offset=0;offset<size;){
            const auto count=std::min(size-offset,std::size_t((offset%31)+1));
            measured.ReadBytes(a.data()+offset,count);reference.ReadBytes(b.data()+offset,count);offset+=count;
        }
        check(!measured.IsFailed()&&!measured.IsEOF()&&a==b&&a==bytes.substr(0,size),"mixed read/write boundaries retain exact state");
        char sentinel='z';measured.ReadBytes(&sentinel,1);
        check(measured.IsFailed()&&measured.IsEOF()&&sentinel=='z',"truncated reads refuse without corrupting output");
    }
    const auto storage=measured.StorageBytes();measured.Reset();
    check(measured.StorageBytes()==storage&&measured.GetDataSize()==0&&!measured.IsFailed(),"reset reuses storage and clears logical history");
    measured.WriteBytes(bytes.data(),65536);measured.WriteBytes(bytes.data(),1);
    check(measured.IsFailed()&&measured.GetDataSize()==65536,"over-budget writes refuse before extending storage");
    measured.Reset();measured.WriteBytes(bytes.data(),1);measured.Rewind();measured.SetValidating(true);
    auto identical=bytes[0];measured.ReadBytes(&identical,1);check(!measured.IsFailed(),"matching validation succeeds");
    measured.Rewind();auto different=static_cast<char>(bytes[0]^1);measured.ReadBytes(&different,1);
    check(measured.IsFailed()&&different==bytes[0],"validation mismatch is explicit and retains the recorded value");
    measured.Reset();check(!measured.IsValidating()&&measured.IsLastPart(),"reset clears optional recorder modes");
    measured.WriteBytes(nullptr,0);measured.ReadBytes(nullptr,0);check(!measured.IsFailed(),"empty operations need no pointer");
    measured.WriteBytes(bytes.data(),std::numeric_limits<std::size_t>::max());
    check(measured.IsFailed()&&measured.GetDataSize()==0,"size arithmetic refuses overflow");
    std::cout<<"PASS exact recorder transport, reuse, limits, truncation and validation\n";return 0;
}catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 1;}}
