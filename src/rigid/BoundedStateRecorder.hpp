#pragma once
#include <Jolt/Jolt.h>
#include <Jolt/Physics/StateRecorder.h>
#include <algorithm>
#include <cstring>
#include <string_view>
#include <vector>

namespace banjo {
// Binary transport only: retain every byte that Jolt writes, including contact
// caches and constraint history. No compression, quantization or state filter.
// Reset retains storage; each nested trial must own a distinct recorder.
class BoundedStateRecorder final : public JPH::StateRecorder {
    std::vector<char> storage_;
    std::size_t limit_,written_{},read_{};
    bool failed_{},eof_{};
public:
    explicit BoundedStateRecorder(std::size_t limit=16U*1024U*1024U):limit_(limit){}
    void Reset(){written_=read_=0;failed_=eof_=false;SetValidating(false);SetIsLastPart(true);}
    void Rewind(){read_=0;eof_=false;}
    std::size_t GetDataSize() const{return written_;}
    std::size_t StorageBytes() const{return storage_.size();}
    std::string_view GetData() const{return {storage_.data(),written_};}
    bool IsEOF() const override{return eof_;}
    bool IsFailed() const override{return failed_;}
    void WriteBytes(const void *data,std::size_t bytes) override {
        if(failed_)return;
        if(bytes>limit_-written_){failed_=true;return;}
        const auto needed=written_+bytes;
        if(needed>storage_.size()){
            const auto doubled=storage_.size()>limit_/2?limit_:storage_.size()*2;
            storage_.resize(std::max(needed,std::min(limit_,std::max(std::size_t(4096),doubled))));
        }
        if(bytes)std::memcpy(storage_.data()+written_,data,bytes);
        written_=needed;
    }
    void ReadBytes(void *data,std::size_t bytes) override {
        if(failed_)return;
        if(bytes>written_-read_){failed_=eof_=true;return;}
        if(bytes){
            if(IsValidating()&&std::memcmp(data,storage_.data()+read_,bytes)!=0)failed_=true;
            std::memcpy(data,storage_.data()+read_,bytes);
        }
        read_+=bytes;
    }
};
}
