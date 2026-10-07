#include "fastlattice/NativeToolUse.hpp"
#include <algorithm>
#include <cmath>

namespace banjo::fastlattice {

NativeToolUseController::NativeToolUseController(const LiveToolUseAdmission &admission,
    const LiveToolContactPlan &plan, const NativeToolFeedback &actual, double native_s)
    : plan_(plan), initial_facing_(actual.facing), initial_work_j_(actual.hand_work_j) {
    state_.active=true;state_.phase="preparing";state_.tool=admission.tool;state_.point=admission.point;
    state_.target_m=plan.ready_tip_m-Vec3{0,.06,0};state_.started_s=state_.phase_started_s=native_s;
    lifting_=actual.pointing.y>-.98 && actual.tip_m.y<admission.target_m.y+.45;
    lift_grip_=actual.grip_m+Vec3{0,lifting_?.6:0,0};
    recovery_tip_=plan.ready_tip_m+(plan.contact.path_m.back()-plan.contact.path_m.front());
    recovery_tip_.y+=.14;
    recovery_facing_=plan.facing;
}

void NativeToolUseController::finish(double native_s,const std::string &reason) {
    state_.active=false;state_.phase="finished";state_.reason=reason;state_.ended_s=native_s;
    requested_speed_m_s_=0;
}
void NativeToolUseController::interrupt(double native_s,const std::string &reason) { finish(native_s,reason); }
void NativeToolUseController::recover(double native_s,const std::string &reason) {
    if(state_.phase=="recovering")return;
    recovery_from_current_=!reason.empty();
    state_.phase="recovering";state_.phase_started_s=native_s;state_.reason=reason;
    requested_speed_m_s_=0;
}
void NativeToolUseController::cancel(double native_s,const std::string &reason) {
    if(state_.active)recover(native_s,reason);
}

NativeToolWish NativeToolUseController::wish(const NativeToolFeedback &actual,double native_s,
    double dt_s,double available_acceleration_m_s2) {
    NativeToolWish out{actual.grip_m,{},actual.facing,false};
    if(!state_.active)return out;
    if(!actual.connected) { finish(native_s,actual.grip_present?"capability_changed":"grip_released");return out; }
    if(!actual.reachable) { finish(native_s,"out_of_reach");return out; }
    if(!actual.target_matches && state_.phase!="recovering")recover(native_s,"target_changed");
    Vec3 goal;
    if(state_.phase=="preparing") {
        goal=lifting_?lift_grip_:actual.grip_m+plan_.ready_tip_m-actual.tip_m;
        out.facing=lifting_?initial_facing_:plan_.facing;
    } else if(state_.phase=="acting") {
        const Vec3 desired_tip=contact_waypoint_==1?
            plan_.ready_tip_m+plan_.contact.path_m[1]-plan_.ready_grip_m:working_tip_;
        goal=actual.grip_m+desired_tip-actual.tip_m;
        out.facing=plan_.facing;out.cuts=true;
    } else {
        if(recovery_from_current_) {
            recovery_tip_=actual.tip_m;
            // A cancelled preparation stops here when already clear. An
            // existing buried contact withdraws vertically from its actual tip.
            if(actual.tip_m.y<actual.ground_height_m+.06 || actual.point_depth_m>0)
                recovery_tip_.y=std::max(actual.ground_height_m+.06,actual.tip_m.y+actual.point_depth_m+.06);
            recovery_facing_=actual.facing;recovery_from_current_=false;
        }
        goal=actual.grip_m+recovery_tip_-actual.tip_m;out.facing=recovery_facing_;
    }
    const Vec3 error=goal-actual.grip_m;
    const double distance=length(error);
    const double acceleration=std::clamp(available_acceleration_m_s2,0.0,80.0);
    requested_speed_m_s_=std::min({4.0,requested_speed_m_s_+dt_s*acceleration,
        std::sqrt(2*acceleration*distance)});
    if(distance>1e-9) {
        out.grip_m=actual.grip_m+(std::min(.025,distance)/distance)*error;
        out.grip_velocity_m_s=(requested_speed_m_s_/distance)*error;
    }
    return out;
}

void NativeToolUseController::accepted(const NativeToolFeedback &actual,double native_s,
    const std::vector<LiveGroundWork> &contacts,const std::string &actor) {
    // A released bite can close on the next accepted native step. Retain that
    // already-started contact without charging later hand work to this action.
    if(!state_.active && !pending_contact_close_)return;
    if(state_.active)state_.hand_work_j=actual.hand_work_j-initial_work_j_;
    state_.contact_work_j=state_.contact_impulse_n_s=state_.peak_contact_force_n=0;
    state_.loosened={};state_.contacted=false;pending_contact_close_=false;
    for(const auto &meeting:contacts) {
        if(meeting.actor!=actor||meeting.point!=state_.point||meeting.at_s<state_.started_s||
            (!state_.active && meeting.at_s>=state_.ended_s))continue;
        state_.contacted=true;state_.contact_work_j+=meeting.work_j;
        pending_contact_close_=pending_contact_close_||meeting.open;
        state_.contact_impulse_n_s+=meeting.impulse_n_s;
        state_.peak_contact_force_n=std::max(state_.peak_contact_force_n,meeting.peak_force_n);
        state_.loosened.soil_m3+=meeting.loosened.soil_m3;state_.loosened.sand_m3+=meeting.loosened.sand_m3;
        state_.loosened.rock_m3+=meeting.loosened.rock_m3;
    }
    if(!state_.active)return;
    if(!actual.connected) { finish(native_s,actual.grip_present?"capability_changed":"grip_released");return; }
    if(!actual.reachable) { finish(native_s,"out_of_reach");return; }
    const double elapsed=native_s-state_.phase_started_s;
    const bool slow=length(actual.grip_velocity_m_s)<.5;
    if(state_.phase=="preparing") {
        if(lifting_) {
            if(length(actual.grip_m-lift_grip_)<.025 && slow) { lifting_=false;requested_speed_m_s_=0; }
        } else if(length(actual.grip_m-plan_.ready_grip_m)<.025 &&
            length(actual.tip_m-plan_.ready_tip_m)<.025 && actual.pointing.y<-.98 && slow) {
            state_.phase="acting";state_.phase_started_s=native_s;requested_speed_m_s_=0;return;
        }
        if(elapsed>=2)recover(native_s,"blocked_path");
    } else if(state_.phase=="acting") {
        // Contact resistance may stop penetration before the desired maximum
        // depth. A measured bite is enough to begin lateral work at that actual
        // grip height; requiring the wish to bury itself first stalls every pry.
        const bool breakout=std::any_of(contacts.begin(),contacts.end(),[&](const LiveGroundWork &meeting) {
            return meeting.actor==actor && meeting.point==state_.point && meeting.at_s>=state_.started_s &&
                (meeting.kind=="broke out" || meeting.kind=="broke rock out");
        });
        // Withdraw on the native law's work result rather than continuing to
        // drive a path endpoint through a wedge which is already loosened.
        if(breakout) {
            recovery_tip_=actual.tip_m+Vec3{0,std::max(.06,actual.point_depth_m+.06),0};
            recover(native_s,"");return;
        }
        if(contact_waypoint_==1 && actual.point_depth_m>=.006) {
            working_tip_=actual.tip_m+(plan_.contact.path_m[2]-plan_.contact.path_m[1]);
            recovery_tip_=working_tip_+Vec3{0,std::max(.06,actual.point_depth_m+.06),0};
            ++contact_waypoint_;requested_speed_m_s_=0;
        } else if(length(actual.tip_m-(contact_waypoint_==1?
            plan_.ready_tip_m+plan_.contact.path_m[1]-plan_.ready_grip_m:working_tip_))<.015) {
            ++contact_waypoint_;
            if(contact_waypoint_==plan_.contact.path_m.size()) { recover(native_s,"");return; }
            requested_speed_m_s_=0;
        }
        if(elapsed>=1)recover(native_s,state_.contacted?"insufficient_work":"no_contact");
    } else if(state_.phase=="recovering") {
        if(length(actual.tip_m-recovery_tip_)<.025 && actual.tip_m.y>actual.ground_height_m+.02 &&
            actual.point_depth_m<=0 && slow) {
            const auto reason=!state_.reason.empty()?state_.reason:
                state_.loosened.total()>0?std::string{}:state_.contacted?"insufficient_work":"no_contact";
            finish(native_s,reason);
        } else if(elapsed>=2)finish(native_s,"recovery_blocked");
    }
}

} // namespace banjo::fastlattice
