#pragma once
#include "platform/PlatformWorld.hpp"
#include <atomic>
#include <future>
#include <deque>
namespace banjo {
struct PlatformFrame {
    double time_s{};
    unsigned broken_bonds{};
    std::vector<PlatformInstance> instances;
};
// Passive, render-only recordings of an exact initial package in this process.
// No interpolation, state resumption, persisted cache, or live-world substitution.
class PlatformPlayback {
public:
    ~PlatformPlayback(){clear();}
    void start(const std::string &package,double duration_s=1.25);
    void clear();
    void poll(double wall_seconds);
    void play();
    void pause(){playing_=false;}
    bool computing()const{return job_.valid();}
    bool ready()const{return bool(clip_);}
    bool playing()const{return playing_;}
    double progress()const{return progress_?progress_->load():0;}
    const PlatformFrame *frame()const;
    const std::string &error()const{return error_;}
    std::string finalReport()const;
private:
    struct Clip {std::vector<PlatformFrame> frames;std::string final_report;};
    std::shared_ptr<const Clip> clip_;
    std::future<std::shared_ptr<const Clip>> job_;
    std::shared_ptr<std::atomic<bool>> cancel_;
    std::shared_ptr<std::atomic<double>> progress_;
    std::deque<std::pair<std::string,std::shared_ptr<const Clip>>> recent_;
    std::string key_,error_;
    bool playing_{};
    double cursor_{};
};
}
