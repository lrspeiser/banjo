#pragma once
#include "creator/BondedBowl.hpp"
#include <atomic>
#include <future>
#include <memory>
#include <string>
namespace banjo {
// One exact starting-state recording, owned by one lab. No cross-experiment
// cache or interpolated topology. Edits discard it and cancel its worker.
class BowlRecording {
public:
 ~BowlRecording(){clear();}
 void start(const BondedBowl &initial,double duration=1.25);
 void clear(); void poll(double wall_seconds);
 void pause(){playing_=false;} void play();
 bool computing() const{return job_.valid();}
 bool playing() const{return playing_;}
 bool ready() const{return !frames_.empty();}
 double progress() const{return progress_?progress_->load():0;}
 const BondedBowl *frame() const;
 const std::string &error() const{return error_;}
private:
 std::future<std::vector<BondedBowl>> job_;
 std::shared_ptr<std::atomic<bool>> cancel_;
 std::shared_ptr<std::atomic<double>> progress_;
 std::vector<BondedBowl> frames_;
 double cursor_{};bool playing_{};std::string error_;
};
}
