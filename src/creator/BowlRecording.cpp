#include "creator/BowlRecording.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
namespace banjo {
void BowlRecording::clear(){if(cancel_)cancel_->store(true);if(job_.valid()){try{(void)job_.get();}catch(...){}}frames_.clear();playing_=false;cursor_=0;error_.clear();}
void BowlRecording::start(const BondedBowl &initial,double duration){
 if(!std::isfinite(duration)||duration<=0||duration>2)throw std::invalid_argument("recording duration must be in (0,2] seconds");
 clear();cancel_=std::make_shared<std::atomic<bool>>(false);progress_=std::make_shared<std::atomic<double>>(0);
 job_=std::async(std::launch::async,[state=initial,duration,cancel=cancel_,progress=progress_]()mutable{
  std::vector<BondedBowl> frames{state};const unsigned ticks=unsigned(std::ceil(duration*2400));frames.reserve(ticks/20+2);
  for(unsigned i=1;i<=ticks;++i){if(cancel->load())return std::vector<BondedBowl>{};state.advance(1./2400);progress->store(double(i)/ticks);if(i%20==0||i==ticks)frames.push_back(state);}
  return frames;
 });
}
void BowlRecording::play(){if(frames_.empty())return;cursor_=0;playing_=true;}
void BowlRecording::poll(double wall){
 if(job_.valid()&&job_.wait_for(std::chrono::seconds(0))==std::future_status::ready){try{frames_=job_.get();cursor_=0;playing_=false;}catch(const std::exception &e){frames_.clear();error_=e.what();}return;}
 if(playing_&&!frames_.empty()){cursor_=std::min(cursor_+std::clamp(wall,0.,.1),frames_.back().time()-frames_.front().time());if(cursor_>=frames_.back().time()-frames_.front().time())playing_=false;}
}
const BondedBowl *BowlRecording::frame() const{if(frames_.empty())return nullptr;const double time=frames_.front().time()+cursor_;auto i=std::upper_bound(frames_.begin(),frames_.end(),time,[](double t,const auto &f){return t<f.time();});return &(i==frames_.begin()?frames_.front():*std::prev(i));}
}
