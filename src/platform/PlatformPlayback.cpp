#include "platform/PlatformPlayback.hpp"
#include <algorithm>
#include <bit>
#include <cmath>
#include <stdexcept>
namespace banjo {
void PlatformPlayback::clear(){
    if(cancel_)cancel_->store(true);
    if(job_.valid()){try{(void)job_.get();}catch(...){}}
    clip_.reset();playing_=false;cursor_=0;error_.clear();
}
void PlatformPlayback::start(const std::string &package,double duration){
    if(!std::isfinite(duration)||duration<=0||duration>2||package.size()>4194304)throw std::invalid_argument("recording admission budget");
    clear();key_=std::to_string(std::bit_cast<std::uint64_t>(duration))+"\n"+package;
    for(auto &entry:recent_)if(entry.first==key_){clip_=entry.second;return;}
    cancel_=std::make_shared<std::atomic<bool>>(false);progress_=std::make_shared<std::atomic<double>>(0);
    job_=std::async(std::launch::async,[package,duration,cancel=cancel_,progress=progress_]() -> std::shared_ptr<const Clip> {
        auto world=PlatformWorld::load(package);auto initial=world->renderInstances();
        const auto ticks=unsigned(std::ceil(duration/world->fixedStep()));
        // Capture at up to 120 Hz using accepted fixed-tick states, plus endpoints.
        const unsigned stride=std::max(1u,unsigned(std::ceil((1./120)/world->fixedStep())));
        if(initial.size()*(std::size_t(ticks/stride)+2)>100000)throw std::invalid_argument("recording exceeds 100000 render-instance samples");
        auto clip=std::make_shared<Clip>();clip->frames.push_back({0,0,std::move(initial)});
        for(unsigned tick=1;tick<=ticks;++tick){
            if(cancel->load())return {};
            auto result=world->step();if(!result.error.empty())throw std::runtime_error(result.error);
            if(tick%stride==0||tick==ticks)clip->frames.push_back({result.elapsed_s,world->fractureCount(),world->renderInstances()});
            progress->store(double(tick)/ticks);
        }
        clip->final_report=world->reportJson();return clip;
    });
}
void PlatformPlayback::poll(double wall){
    if(!std::isfinite(wall)||wall<0)throw std::invalid_argument("invalid playback clock");
    if(job_.valid()&&job_.wait_for(std::chrono::seconds(0))==std::future_status::ready){
        try{clip_=job_.get();if(clip_){recent_.push_back({key_,clip_});if(recent_.size()>4)recent_.pop_front();}}
        catch(const std::exception &e){error_=e.what();}return;
    }
    if(playing_&&clip_){cursor_=std::min(cursor_+wall,clip_->frames.back().time_s);if(cursor_>=clip_->frames.back().time_s)playing_=false;}
}
void PlatformPlayback::play(){if(clip_){cursor_=0;playing_=true;}}
const PlatformFrame *PlatformPlayback::frame()const{
    if(!clip_)return nullptr;
    auto i=std::upper_bound(clip_->frames.begin(),clip_->frames.end(),cursor_,[](double t,const PlatformFrame &f){return t<f.time_s;});
    return &(i==clip_->frames.begin()?clip_->frames.front():*std::prev(i));
}
std::string PlatformPlayback::finalReport()const{if(!clip_)throw std::logic_error("recording not ready");return clip_->final_report;}
}
